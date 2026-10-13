"""
Temperaturas de la máquina y gobernador térmico.

SENSORES. GPU por nvidia-smi (o amdgpu por hwmon), y del sistema lo que publique
el kernel: CPU (paquete y núcleos), SSD NVMe, placa, wifi, batería, ventiladores.

LÍMITE. La GPU no debe pasar de 60 °C (ajustable). Medido en un portátil con RTX
4050 generando con un 7B entero en GPU:

    reposo 36 °C → 44 °C a los 3 s → 53 °C a los 28 s (≈ +0,36 °C/s sostenido)
    al cortar la generación: de 53 a 48 °C en 3 s

Llega a 60 °C tras unos 45-50 s seguidos, y un solo paso de un flujo (1200 tokens)
puede durar eso. Pausar solo entre pasos no basta: el gobernador corta DENTRO de la
generación y se continúa después sin perder nada (Ollama retoma una respuesta a
medias como prefijo del asistente y reaprovecha su caché: 26 ms en releerlo).

La CPU no se gobierna con ese límite: con el modelo entero en GPU sube a 67-81 °C
en segundos (un núcleo alimentando la GPU), así que nunca bajaría de 60. Se
muestra y avisa con sus propios umbrales.

APRENDER. Medido con límites bajos: al RETOMAR, la GPU salta +7-8 °C en el primer
segundo (el chip pasa de 7 a 40 W; el disipador tarda mucho más en calentarse). Ese
salto llega antes que la primera lectura, así que cortar antes no sirve: lo que
evita volver a llegar es REANUDAR más frío. El gobernador aprende:
  · salto: cuánto sube la GPU al empezar un tramo (media móvil, 8 °C de partida);
    se reanuda a límite − salto − 2.
  · margen: cuánto sigue subiendo tras cortar, por inercia; se corta a límite − margen.
  · reposo: de cuánto no baja la GPU parada. Si límite − salto no deja sitio por
    encima del reposo, el límite es inalcanzable trabajando a plena potencia: se
    avisa con el límite mínimo viable en vez de esperar sin fin.
Lo aprendido se guarda en el almacén de recursos y sobrevive a reinicios.
"""

import os
import threading
import time
from typing import Any, Callable, Dict, List, Optional

from .almacen import almacen
from .ritmo import FijadorCPU, Ritmo
from . import motor_suave

def _t():
    from nativo_rust import rust
    return rust().termico


LIMITE_GPU = _t().LIMITE_GPU
CPU_AVISO = _t().CPU_AVISO
CPU_ALTO = _t().CPU_ALTO

INTERVALO_S = _t().INTERVALO_S
INACTIVO_S = _t().INACTIVO_S           # sin nadie mirando ni trabajando, el monitor se duerme
HISTORIAL = _t().HISTORIAL             # 6 minutos a 2 s

SALTO_INICIAL = _t().SALTO_INICIAL     # medido en RTX 4050 portátil con un 7B
SEGUNDOS_SALTO = _t().SEGUNDOS_SALTO   # el salto se mide en los primeros segundos del tramo
MARGEN_MAXIMO = _t().MARGEN_MAXIMO
FRESCAS_PARA_AFLOJAR = _t().FRESCAS_PARA_AFLOJAR
ESPERA_MAXIMA_S = _t().ESPERA_MAXIMA_S
MESETA_S = _t().MESETA_S               # sin bajar 1 °C en este tiempo, no va a enfriar más

Evento = Callable[[Dict[str, Any]], None]


# ===========================================================================
# Sensores
# ===========================================================================

# Los sensores se leen en Rust (backend-rust/crates/prig-recursos, sensores.rs y nvml.rs): hwmon como psutil, la GPU
# por NVML (o nvidia-smi sin NVML) y la misma clasificación que tenía esta función.

def _rs():
    from nativo_rust import rust
    return rust().sensores


def _nvidia() -> List[Dict[str, Any]]:
    """ Las GPU NVIDIA: por NVML (microsegundos, sin procesos; lanzar nvidia-smi cada segundo calentaba la CPU) """
    return _rs().gpus_nvidia()


def _temperaturas() -> Dict[str, Any]:
    """ {chip: [(etiqueta, actual, alto, crítico)]}, lo que daba psutil.sensors_temperatures() """
    return _rs().temperaturas_hwmon()


def _ventiladores() -> Dict[str, Any]:
    """ {chip: [(etiqueta, rpm)]}, lo que daba psutil.sensors_fans() """
    return _rs().ventiladores_hwmon() or {}


def leer_sensores() -> Dict[str, Any]:
    """ {tomada, componentes: [{id, tipo, nombre, temp, …}], ventiladores: [{id, nombre, rpm}]}. Un registro por
    placa (acpitz y el del fabricante suelen medir lo mismo); sin los sensores internos del NVMe ni el acpi_fan que
    duplica a uno del fabricante. """
    return _rs().clasificar_sensores(_nvidia(), _temperaturas(), _ventiladores())


def temp_gpu(lectura: Optional[Dict[str, Any]]) -> Optional[float]:
    """ La GPU más caliente de una lectura """
    return _t().temp_gpu(lectura)


def temp_cpu(lectura: Optional[Dict[str, Any]]) -> Optional[float]:
    """ La primera CPU de una lectura """
    return _t().temp_cpu(lectura)


def temp_cpu_rapida() -> Optional[float]:
    """ La temperatura de la CPU leyendo solo sus sensores: la misma que temp_cpu(leer_sensores()), sin tocar el
    disco, la GPU ni ACPI (cada lectura de un NVMe cuesta ~3 ms y lo despierta). Para el modo frío. """
    return _t().temp_cpu_rapida()


# ===========================================================================
# Monitor
# ===========================================================================

class Monitor:
    """ Lee los sensores cada 2 s mientras alguien mire o haya trabajo en marcha. El estado (última lectura,
    historial) vive en Rust; con el lector de siempre, también la lectura (sin el GIL). """

    def __init__(self, lector: Callable[[], Dict[str, Any]] = leer_sensores,
                 intervalo: float = INTERVALO_S):
        self.lector = lector
        self.intervalo = intervalo
        self._n = _t().NucleoMonitor()
        self._nativo = lector is leer_sensores
        self._cerrojo = threading.Lock()
        self._hilo: Optional[threading.Thread] = None

    @property
    def historial(self) -> List[Dict[str, Any]]:
        return self._n.historial

    # -- ciclo
    def _vivo(self) -> bool:
        return self._n.vivo(time.time())

    def _bucle(self):
        while True:
            self._muestrear()
            with self._cerrojo:
                if not self._vivo():
                    self._hilo = None
                    return
            time.sleep(self.intervalo)

    def _muestrear(self) -> Dict[str, Any]:
        if self._nativo:
            return self._n.muestrear_nativo()
        lectura = self.lector()
        self._n.registrar(lectura)
        return lectura

    def _asegurar(self):
        with self._cerrojo:
            self._n.consultar(time.time())
            if self._hilo is None:
                self._hilo = threading.Thread(target=self._bucle, daemon=True,
                                              name="prig-monitor-termico")
                self._hilo.start()

    # -- uso
    def lectura(self, max_edad: float = 3.0) -> Dict[str, Any]:
        self._asegurar()
        ultima = self._n.ultima
        if ultima is None or time.time() - ultima["tomada"] > max_edad:
            return self._muestrear()
        return ultima

    def gpu(self, max_edad: float = 2.5) -> Optional[float]:
        return temp_gpu(self.lectura(max_edad))

    def tendencia_gpu(self, desde: Optional[float] = None) -> float:
        """ °C por segundo en las últimas lecturas de hasta 5 s (positivo: calentando).
        Ventana corta a propósito: al retomar tras una pausa, lecturas más viejas son
        de enfriamiento y esconderían la subida brusca del arranque. """
        return self._n.tendencia_gpu(desde)

    def trabajando(self):
        monitor = self

        class _Ctx:
            def __enter__(self_inner):
                monitor._n.sumar_trabajo(1)
                monitor._asegurar()
                return monitor

            def __exit__(self_inner, *exc):
                monitor._n.sumar_trabajo(-1)
        return _Ctx()


# ===========================================================================
# Gobernador
# ===========================================================================

AJUSTES_POR_DEFECTO = _t().AJUSTES_POR_DEFECTO


class Tramo(_t().Tramo):
    """ Un tramo seguido de generación, entre dos pausas (en Rust; aquí se le da la hora) """

    def __new__(cls, temp_inicio: Optional[float]):
        return super().__new__(cls, temp_inicio, time.time())

    def __init__(self, temp_inicio: Optional[float]):
        pass

    def anotar(self, temp: Optional[float]):
        super().anotar(temp, lambda: time.time())

    @property
    def segundos(self) -> float:
        return time.time() - self.inicio


def _moe_generando() -> bool:
    try:
        from ai_engine import motor_moe
        return motor_moe.generando()
    except Exception:
        return False


class Gobernador:
    """ Decide cuándo cortar y cuándo reanudar, y aprende de cada tramo. Las decisiones y lo aprendido viven en
    Rust (termico.rs); esta clase le da el mundo: el monitor, el ritmo, el fijador, el motor suave, el MoE. """

    def __init__(self, monitor: Monitor, guardar: bool = True):
        self.monitor = monitor
        self.guardar = guardar
        self._n = _t().NucleoGobernador(almacen().termico() if guardar else None, guardar)
        # Modo suave (recursos/ritmo.py): dosifica el trabajo antes de que haga falta cortar.
        # En las pruebas (guardar=False) queda apagado para que el comportamiento sea el de siempre.
        if guardar:
            self.ritmo = Ritmo(almacen().ritmo(), guardar=almacen().guardar_ritmo)
        else:
            self.ritmo = Ritmo({"activo": False})
        self.fijador = FijadorCPU()
        # Motor suave (recursos/motor_suave.py): la dosificación dentro del proceso del modelo
        self.controlador = motor_suave.Controlador(self.ritmo, monitor)
        self.motor_suave: Dict[str, Any] = {"ok": False, "motivo": "Sin iniciar."}
        # Modo frío (recursos/frio.py): pausas por ciclos para los modelos que viven en RAM. La temperatura de la
        # CPU se lee sola, sin pasar por todos los sensores (el disco y ACPI cuestan milisegundos y se despiertan).
        from . import frio
        self._ram_cache: Dict[str, Any] = {"t": 0.0, "pids": set()}
        self._ajustes_frio = (lambda: almacen().frio()) if guardar else (lambda: {"activo": False})
        self.frio = frio.ControladorFrio(
            ajustes=self._ajustes_frio,
            leer_temp=temp_cpu_rapida,
            motores_en_ram=self.motores_en_ram,
            holgura=self._holgura_frio)
        # Con el modo frío, los modelos en RAM van a los núcleos E (el fijador no los devuelve a todos)
        self.fijador.ram_en_eficientes = lambda: bool({**frio.POR_DEFECTO, **(self._ajustes_frio() or {})}["activo"])
        # PRIG_SIN_MOTOR_SUAVE=1 (lo fijan las pruebas): no instalar ni arrancar el controlador,
        # que escribiría en el archivo de control de un Prig que esté abierto a la vez.
        if guardar and os.environ.get("PRIG_SIN_MOTOR_SUAVE") != "1":
            threading.Thread(target=self._preparar_motor, daemon=True, name="prig-motor-suave-inicio").start()

    def _preparar_motor(self):
        try:
            from . import nvml
            nvml.disponible()                  # la primera carga de NVML tarda ~2 s: mejor ahora
        except Exception:
            pass
        self.aplicar_motor_suave()
        self.controlador.iniciar()
        from . import frio
        frio.reanudar_huerfanos()              # un cierre brusco pudo dejar un motor congelado
        self.frio.iniciar()

    @staticmethod
    def _holgura_frio(pids) -> float:
        """ El motor MoE solo, con el turbo apagado: se le pausa solo por encima del objetivo (frio.py) """
        from . import frio
        try:
            from ai_engine import motor_moe
            moe = motor_moe.pid_en_marcha()
        except Exception:
            return 0.0
        return frio.HOLGURA_MOE_SIN_TURBO_C if moe and set(pids) == {moe} and frio.turbo_apagado() else 0.0

    def motores_en_ram(self):
        """ Motores de Prig cuyo modelo NO cabe entero en la GPU (se revisa cada 3 s). Se fijan a
        los núcleos E: con el modelo en RAM, 4 hilos ahí rinden como 8 en todos y calientan menos. """
        from . import frio
        ahora = time.time()
        if ahora - self._ram_cache["t"] < 3:
            return self._ram_cache["pids"]
        en_gpu = self.fijador._modelos_en_gpu()
        pids = {m["pid"] for m in frio.motores_de_prig() if m["blob"] and m["blob"] in en_gpu and not en_gpu[m["blob"]]}
        eficientes = frio.nucleos_eficientes()
        for pid in pids - self._ram_cache["pids"]:
            if eficientes:
                self.fijador.fijar_proceso(pid, eficientes)
        # El motor MoE también tiene los expertos en RAM, pero sigue en los núcleos P: con él,
        # los núcleos E rinden la mitad (medido). El modo frío solo lo pausa por ciclos.
        try:
            from ai_engine import motor_moe
            moe = motor_moe.pid_en_marcha()
        except Exception:
            moe = None
        if moe:
            pids = pids | {moe}
        self._ram_cache = {"t": ahora, "pids": pids}
        return pids

    def aplicar_motor_suave(self) -> Dict[str, Any]:
        """ Instala o retira el envoltorio del motor según el modo suave esté activo o no """
        try:
            self.motor_suave = motor_suave.instalar() if self.ritmo.activo else {**motor_suave.desinstalar(), "motivo": "Modo suave apagado."}
        except Exception as e:
            self.motor_suave = {"ok": False, "motivo": str(e)[:200]}
        if not self.ritmo.activo:
            motor_suave.quitar_control()
        return self.motor_suave

    def estado_motor(self) -> Dict[str, Any]:
        motor = motor_suave.leer_estado()
        return {"instalado": bool(self.motor_suave.get("instalado")), "motivo": self.motor_suave.get("motivo"),
                "generando": motor_suave.generando(motor), "estado": motor,
                "fraccion": (self.controlador.ultimo or {}).get("fraccion")}

    def dosifica_el_motor(self) -> bool:
        """ El modo suave actúa dentro del motor (y no hace falta pausar peticiones) """
        return self.ritmo.activo and bool(self.motor_suave.get("instalado")) and motor_suave.generando()

    @staticmethod
    def _moe() -> bool:
        return _moe_generando()

    def _persistir_ajustes(self, ajustes: Dict[str, Any], texto: Optional[str], datos: Optional[dict]):
        almacen().guardar_termico(ajustes, texto, datos)

    # -- ajustes
    @property
    def ajustes(self):
        """ Diccionario vivo: lo que se cambia aquí lo ve el gobernador """
        return _t().AjustesVivos(self._n)

    @property
    def pausa(self) -> Optional[Dict[str, Any]]:
        return self._n.pausa

    @property
    def aviso(self) -> Optional[str]:
        return self._n.aviso

    @property
    def limite(self) -> float:
        return self._n.limite

    @property
    def salto(self) -> float:
        return self._n.salto

    @property
    def corte(self) -> float:
        return self._n.corte

    @property
    def reanudar(self) -> float:
        return self._n.reanudar

    @property
    def viable(self) -> bool:
        return self._n.viable

    @property
    def limite_minimo_viable(self) -> Optional[float]:
        return self._n.limite_minimo_viable

    def fijar_limite(self, limite: float):
        self._n.fijar_limite(self, limite)

    def olvidar(self):
        self._n.olvidar(self)

    def estado(self) -> Dict[str, Any]:
        return self._n.estado({**self.ritmo.estado(self.monitor.gpu()), "motor": self.estado_motor()})

    # -- tramos
    def empezar_tramo(self) -> Tramo:
        return self._n.empezar_tramo(self, Tramo)

    def debe_cortar(self, tramo: Tramo) -> Optional[str]:
        """ ¿Hay que parar ya la generación en curso? """
        return self._n.debe_cortar(self, tramo)

    def descansar(self, tramo: Tramo, cancelar: Optional[threading.Event] = None) -> float:
        """ La pausa corta del modo suave: un tiempo fijo, no «hasta que baje a X» """
        return self._n.descansar(self, tramo, cancelar)

    def enfriar(self, motivo: str, cancelar: Optional[threading.Event] = None,
                avisar: Optional[Evento] = None, objetivo: Optional[float] = None,
                maximo_s: float = ESPERA_MAXIMA_S, tramo: Optional[Tramo] = None) -> float:
        """ Espera hasta que la GPU baje a `objetivo` (por defecto, la de reanudar).
        Anota en el tramo lo que siguió subiendo ya en pausa. """
        if motivo == "ritmo":
            return self.descansar(tramo, cancelar) if tramo is not None else 0.0
        return self._n.enfriar(self, motivo, cancelar, avisar, objetivo, maximo_s, tramo)

    def _anotar_reposo(self, minima: float):
        self._n._anotar_reposo(self, minima)

    def _revisar_viabilidad(self):
        self._n._revisar_viabilidad()

    def antes_de_trabajar(self, cancelar: Optional[threading.Event] = None,
                          avisar: Optional[Evento] = None) -> float:
        """ Entre pasos: si la GPU no está a la temperatura de reanudar, se espera """
        temp = self.monitor.gpu()
        if temp is None or temp <= self.reanudar:
            return 0.0
        return self.enfriar("antes_de_paso", cancelar, avisar)

    def terminar_tramo(self, tramo: Tramo, motivo: Optional[str]):
        """ Aprende del tramo: salto al empezar, inercia al cortar, si llegó al límite """
        self._n.terminar_tramo(self, tramo, motivo)


def _texto_pausa(motivo: str, temp: float, objetivo: float, limite: float) -> str:
    return _t().texto_pausa(motivo, temp, objetivo, limite)


# ===========================================================================

_monitor: Optional[Monitor] = None
_gobernador: Optional[Gobernador] = None
_cerrojo_global = threading.Lock()


def monitor() -> Monitor:
    global _monitor
    with _cerrojo_global:
        if _monitor is None:
            _monitor = Monitor()
        return _monitor


def gobernador() -> Gobernador:
    global _gobernador
    m = monitor()
    with _cerrojo_global:
        if _gobernador is None:
            _gobernador = Gobernador(m)
        return _gobernador
