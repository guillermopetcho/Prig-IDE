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

import shutil
import subprocess
import os
import threading
import time
from collections import deque
from typing import Any, Callable, Deque, Dict, List, Optional

from .almacen import almacen
from .ritmo import FijadorCPU, Ritmo
from . import motor_suave

LIMITE_GPU = 60.0
CPU_AVISO = 85.0
CPU_ALTO = 95.0

INTERVALO_S = 2.0
INACTIVO_S = 25.0           # sin nadie mirando ni trabajando, el monitor se duerme
HISTORIAL = 180             # 6 minutos a 2 s

SALTO_INICIAL = 8.0         # medido en RTX 4050 portátil con un 7B
SEGUNDOS_SALTO = 4.0        # el salto se mide en los primeros segundos del tramo
MARGEN_MAXIMO = 3.0
FRESCAS_PARA_AFLOJAR = 8
ESPERA_MAXIMA_S = 600.0
MESETA_S = 20.0             # sin bajar 1 °C en este tiempo, no va a enfriar más

Evento = Callable[[Dict[str, Any]], None]


# ===========================================================================
# Sensores
# ===========================================================================

def _nvidia() -> List[Dict[str, Any]]:
    # Por NVML (microsegundos, sin procesos): lanzar nvidia-smi cada segundo calentaba la CPU
    from . import nvml
    por_nvml = nvml.lectura()
    if por_nvml is not None:
        return [{"id": f"gpu{g['indice']}", "tipo": "gpu", "nombre": g["nombre"], "temp": g["temp"],
                 "consumo_w": g["consumo_w"], "uso_pct": g["uso_pct"], "ventilador_pct": g["ventilador_pct"]}
                for g in por_nvml if g["temp"] is not None]
    if not shutil.which("nvidia-smi"):
        return []
    try:
        salida = subprocess.run(
            ["nvidia-smi", "--query-gpu=index,name,temperature.gpu,power.draw,"
             "utilization.gpu,fan.speed", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=3).stdout
    except Exception:
        return []

    def num(x):
        try:
            return float(x)
        except (TypeError, ValueError):
            return None
    gpus = []
    for linea in salida.strip().splitlines():
        p = [x.strip() for x in linea.split(",")]
        if len(p) < 6 or num(p[2]) is None:
            continue
        gpus.append({"id": f"gpu{p[0]}", "tipo": "gpu", "nombre": p[1], "temp": num(p[2]),
                     "consumo_w": num(p[3]), "uso_pct": num(p[4]), "ventilador_pct": num(p[5])})
    return gpus


# Cómo se llaman los sensores en hwmon según el fabricante
_CPU = ("coretemp", "k10temp", "zenpower", "cpu_thermal", "cpu-thermal", "soc_thermal")
_DISCO = ("nvme", "drivetemp")
_PLACA = ("acpitz", "pch_", "thinkpad", "dell_smm", "asus", "hp")
_OTROS = {"iwlwifi": ("wifi", "Wi-Fi"), "BAT": ("bateria", "Batería"),
          "amdgpu": ("gpu", "GPU AMD"), "radeon": ("gpu", "GPU AMD")}


def _psutil_temps() -> Dict[str, Any]:
    try:
        import psutil
        return psutil.sensors_temperatures() or {}
    except Exception:
        return {}


def _psutil_fans() -> Dict[str, Any]:
    try:
        import psutil
        return psutil.sensors_fans() or {}
    except Exception:
        return {}


def leer_sensores() -> Dict[str, Any]:
    componentes: List[Dict[str, Any]] = list(_nvidia())
    temps = _psutil_temps()

    for chip, lecturas in temps.items():
        if not lecturas:
            continue
        valores = [s for s in lecturas if s.current is not None and 0 < s.current < 150]
        if not valores:
            continue
        if chip.startswith(_CPU):
            paquete = next((s for s in valores if s.label.lower().startswith(
                ("package", "tctl", "tdie"))), None)
            nucleos = [{"etiqueta": s.label, "temp": s.current} for s in valores
                       if s.label.lower().startswith("core")]
            principal = paquete or max(valores, key=lambda s: s.current)
            componentes.append({
                "id": "cpu", "tipo": "cpu", "nombre": "CPU", "temp": principal.current,
                "nucleo_max": max((n["temp"] for n in nucleos), default=None),
                "nucleos": nucleos, "alto": principal.high, "critico": principal.critical})
        elif chip.startswith(_DISCO):
            for i, s in enumerate(valores):
                if s.label and s.label.lower().startswith("sensor"):
                    continue          # sensores internos del NVMe, con límites absurdos
                componentes.append({"id": f"{chip}{i}", "tipo": "disco", "nombre": "SSD",
                                    "temp": s.current, "alto": s.high, "critico": s.critical})
        elif chip.startswith(_PLACA):
            s = max(valores, key=lambda s: s.current)
            componentes.append({"id": chip, "tipo": "placa", "nombre": "Placa",
                                "temp": s.current, "alto": s.high, "critico": s.critical})
        else:
            for prefijo, (tipo, nombre) in _OTROS.items():
                if chip.startswith(prefijo):
                    s = max(valores, key=lambda s: s.current)
                    componentes.append({"id": chip, "tipo": tipo, "nombre": nombre,
                                        "temp": s.current, "alto": s.high,
                                        "critico": s.critical})
                    break

    # Un solo registro por placa: acpitz y el del fabricante suelen medir lo mismo
    vistos, unicos = set(), []
    for c in componentes:
        clave = (c["tipo"], c["nombre"]) if c["tipo"] in ("placa", "cpu") else c["id"]
        if clave in vistos:
            continue
        vistos.add(clave)
        unicos.append(c)

    ventiladores = []
    for chip, lecturas in _psutil_fans().items():
        for i, s in enumerate(lecturas):
            ventiladores.append({"id": f"{chip}{i}", "nombre": s.label or chip, "rpm": s.current})
    # acpi_fan suele duplicar uno de los del fabricante
    if len(ventiladores) > 1:
        ventiladores = [v for v in ventiladores if not v["id"].startswith("acpi_fan")] or ventiladores

    for c in componentes:
        if c.get("temp") is not None:
            c["temp"] = round(c["temp"], 1)
    return {"tomada": time.time(), "componentes": unicos, "ventiladores": ventiladores}


def temp_gpu(lectura: Optional[Dict[str, Any]]) -> Optional[float]:
    temps = [c["temp"] for c in (lectura or {}).get("componentes", [])
             if c["tipo"] == "gpu" and c.get("temp") is not None]
    return max(temps) if temps else None


def temp_cpu(lectura: Optional[Dict[str, Any]]) -> Optional[float]:
    return next((c["temp"] for c in (lectura or {}).get("componentes", [])
                 if c["tipo"] == "cpu"), None)


# ===========================================================================
# Monitor
# ===========================================================================

class Monitor:
    """ Lee los sensores cada 2 s mientras alguien mire o haya trabajo en marcha """

    def __init__(self, lector: Callable[[], Dict[str, Any]] = leer_sensores,
                 intervalo: float = INTERVALO_S):
        self.lector = lector
        self.intervalo = intervalo
        self._cerrojo = threading.Lock()
        self._hilo: Optional[threading.Thread] = None
        self._ultima: Optional[Dict[str, Any]] = None
        self._consulta = 0.0
        self._trabajos = 0
        self.historial: Deque[Dict[str, Any]] = deque(maxlen=HISTORIAL)

    # -- ciclo
    def _vivo(self) -> bool:
        return self._trabajos > 0 or time.time() - self._consulta < INACTIVO_S

    def _bucle(self):
        while True:
            self._muestrear()
            with self._cerrojo:
                if not self._vivo():
                    self._hilo = None
                    return
            time.sleep(self.intervalo)

    def _muestrear(self) -> Dict[str, Any]:
        lectura = self.lector()
        with self._cerrojo:
            self._ultima = lectura
            self.historial.append({"t": round(lectura["tomada"], 1), "gpu": temp_gpu(lectura),
                                   "cpu": temp_cpu(lectura)})
        return lectura

    def _asegurar(self):
        with self._cerrojo:
            self._consulta = time.time()
            if self._hilo is None:
                self._hilo = threading.Thread(target=self._bucle, daemon=True,
                                              name="prig-monitor-termico")
                self._hilo.start()

    # -- uso
    def lectura(self, max_edad: float = 3.0) -> Dict[str, Any]:
        self._asegurar()
        with self._cerrojo:
            ultima = self._ultima
        if ultima is None or time.time() - ultima["tomada"] > max_edad:
            return self._muestrear()
        return ultima

    def gpu(self, max_edad: float = 2.5) -> Optional[float]:
        return temp_gpu(self.lectura(max_edad))

    def tendencia_gpu(self, desde: Optional[float] = None) -> float:
        """ °C por segundo en las últimas lecturas de hasta 5 s (positivo: calentando).
        Ventana corta a propósito: al retomar tras una pausa, lecturas más viejas son
        de enfriamiento y esconderían la subida brusca del arranque. """
        with self._cerrojo:
            recientes = [h for h in self.historial if h["gpu"] is not None
                         and (desde is None or h["t"] >= desde)]
        if recientes:
            recientes = [h for h in recientes[-3:] if recientes[-1]["t"] - h["t"] <= 5.0]
        puntos = recientes
        if len(puntos) < 2 or puntos[-1]["t"] <= puntos[0]["t"]:
            return 0.0
        return (puntos[-1]["gpu"] - puntos[0]["gpu"]) / (puntos[-1]["t"] - puntos[0]["t"])

    def trabajando(self):
        monitor = self

        class _Ctx:
            def __enter__(self_inner):
                with monitor._cerrojo:
                    monitor._trabajos += 1
                monitor._asegurar()
                return monitor

            def __exit__(self_inner, *exc):
                with monitor._cerrojo:
                    monitor._trabajos -= 1
        return _Ctx()


# ===========================================================================
# Gobernador
# ===========================================================================

AJUSTES_POR_DEFECTO = {
    "limite_gpu": LIMITE_GPU,
    "margen": 1.0,             # se corta a límite − margen
    "salto_c": None,           # subida al empezar un tramo (None: SALTO_INICIAL)
    "reposo_c": None,          # de aquí no baja la GPU parada
    "alcances": 0,
    "frescas_seguidas": 0,
}


class Tramo:
    """ Un tramo seguido de generación, entre dos pausas """

    def __init__(self, temp_inicio: Optional[float]):
        self.inicio = time.time()
        self.temp_inicio = temp_inicio
        self.pico = temp_inicio
        self.max_arranque = temp_inicio   # máximo en los primeros SEGUNDOS_SALTO
        self.temp_corte: Optional[float] = None
        self.pico_en_pausa: Optional[float] = None

    def anotar(self, temp: Optional[float]):
        if temp is None:
            return
        self.pico = temp if self.pico is None else max(self.pico, temp)
        if time.time() - self.inicio <= SEGUNDOS_SALTO:
            self.max_arranque = temp if self.max_arranque is None else max(self.max_arranque, temp)

    @property
    def segundos(self) -> float:
        return time.time() - self.inicio

    @property
    def pico_real(self) -> Optional[float]:
        picos = [p for p in (self.pico, self.pico_en_pausa) if p is not None]
        return max(picos) if picos else None


class Gobernador:
    """ Decide cuándo cortar y cuándo reanudar, y aprende de cada tramo """

    def __init__(self, monitor: Monitor, guardar: bool = True):
        self.monitor = monitor
        self.guardar = guardar
        self._cerrojo = threading.RLock()
        self.ajustes = dict(AJUSTES_POR_DEFECTO)
        if guardar:
            guardados = almacen().termico()
            self.ajustes.update({k: v for k, v in guardados.items() if k in AJUSTES_POR_DEFECTO})
        self.pausa: Optional[Dict[str, Any]] = None
        self.aviso: Optional[str] = None
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

    # -- ajustes
    @property
    def limite(self) -> float:
        return float(self.ajustes["limite_gpu"])

    @property
    def salto(self) -> float:
        return float(self.ajustes.get("salto_c") or SALTO_INICIAL)

    @property
    def corte(self) -> float:
        return self.limite - float(self.ajustes.get("margen") or 0)

    @property
    def reanudar(self) -> float:
        objetivo = min(self.limite - 4.0, self.limite - self.salto - 2.0)
        reposo = self.ajustes.get("reposo_c")
        if reposo is not None:
            objetivo = max(objetivo, float(reposo) + 1.0)
        return round(objetivo, 1)

    @property
    def viable(self) -> bool:
        reposo = self.ajustes.get("reposo_c")
        return reposo is None or float(reposo) + self.salto + 1.0 < self.limite

    @property
    def limite_minimo_viable(self) -> Optional[float]:
        reposo = self.ajustes.get("reposo_c")
        return None if reposo is None else float(round(float(reposo) + self.salto + 2.0))

    def _persistir(self, evento: Optional[str] = None, datos: Optional[dict] = None):
        if self.guardar:
            almacen().guardar_termico(self.ajustes, evento, datos)

    def fijar_limite(self, limite: float):
        if not 40 <= limite <= 95:
            raise ValueError("El límite de la GPU debe estar entre 40 y 95 °C")
        with self._cerrojo:
            self.ajustes["limite_gpu"] = float(limite)
            self.aviso = None
            self._persistir(f"Límite térmico de la GPU: {limite:.0f} °C")

    def olvidar(self):
        with self._cerrojo:
            limite = self.ajustes["limite_gpu"]
            self.ajustes = {**AJUSTES_POR_DEFECTO, "limite_gpu": limite}
            self.aviso = None
            self._persistir("Olvidado lo aprendido sobre el calor de la GPU")

    def estado(self) -> Dict[str, Any]:
        with self._cerrojo:
            return {**self.ajustes, "ritmo": {**self.ritmo.estado(self.monitor.gpu()), "motor": self.estado_motor()},
                    "salto": self.salto, "corte": self.corte,
                    "reanudar": self.reanudar, "viable": self.viable,
                    "limite_minimo_viable": self.limite_minimo_viable,
                    "aviso": self.aviso, "pausa": self.pausa}

    # -- tramos
    def empezar_tramo(self) -> Tramo:
        self.ritmo.marcar()
        if self.ritmo.activo and self.ritmo.ajustes.get("cpu_eficiente"):
            try:
                self.fijador.aplicar()
            except Exception:
                pass
        return Tramo(self.monitor.gpu(max_edad=1.0))

    def debe_cortar(self, tramo: Tramo) -> Optional[str]:
        """ ¿Hay que parar ya la generación en curso? """
        temp = self.monitor.gpu(max_edad=1.0)
        tramo.anotar(temp)
        if temp is None:
            return None
        motivo = None
        if temp >= self.corte:
            motivo = "limite"
        # Leer y cortar tardan ~2 s: si a este ritmo se llega antes, se corta ya. La
        # tendencia no mira el salto del arranque: ya está descontado al reanudar, y
        # tomarlo como ritmo cortaba cada tramo nada más empezar.
        elif temp + max(0.0, self.monitor.tendencia_gpu(
                desde=tramo.inicio + SEGUNDOS_SALTO)) * 2.0 >= self.corte:
            motivo = "prevision"
        if motivo:
            tramo.temp_corte = temp
            return motivo
        # Modo suave: lejos del límite, pero cerca del objetivo o arrancando → pausa corta.
        # Si el motor ya dosifica por dentro (tramos de milisegundos), no se corta la petición.
        if self.dosifica_el_motor():
            return None
        self.ritmo.marcar()
        pausa = self.ritmo.pausa(tramo.segundos, temp)
        if pausa:
            tramo.pausa_ritmo = pausa
            return "ritmo"
        return None

    def descansar(self, tramo: Tramo, cancelar: Optional[threading.Event] = None) -> float:
        """ La pausa corta del modo suave: un tiempo fijo, no «hasta que baje a X» """
        segundos = float(getattr(tramo, "pausa_ritmo", 0) or 0)
        if segundos <= 0:
            return 0.0
        if cancelar is not None:
            cancelar.wait(segundos)
        else:
            time.sleep(segundos)
        return segundos

    def enfriar(self, motivo: str, cancelar: Optional[threading.Event] = None,
                avisar: Optional[Evento] = None, objetivo: Optional[float] = None,
                maximo_s: float = ESPERA_MAXIMA_S, tramo: Optional[Tramo] = None) -> float:
        """ Espera hasta que la GPU baje a `objetivo` (por defecto, la de reanudar).
        Anota en el tramo lo que siguió subiendo ya en pausa. """
        if motivo == "ritmo":
            return self.descansar(tramo, cancelar) if tramo is not None else 0.0
        objetivo = self.reanudar if objetivo is None else objetivo
        inicio = time.time()
        temp = self.monitor.gpu(max_edad=1.0)
        if tramo is not None:
            tramo.pico_en_pausa = temp
        if temp is None or temp <= objetivo:
            return 0.0
        with self._cerrojo:
            self.pausa = {"motivo": motivo, "desde": inicio, "temp": temp, "objetivo": objetivo}
        if avisar:
            avisar({"tipo": "enfriando", "motivo": motivo, "temp_c": temp,
                    "objetivo_c": objetivo, "mensaje": _texto_pausa(motivo, temp, objetivo,
                                                                    self.limite)})
        # Meseta: si la GPU deja de bajar, esperar más no sirve (el objetivo quedó
        # por debajo de su reposo: día caluroso, límite bajo). Sin esto se esperaría
        # hasta el tope de 10 minutos en cada pausa.
        minima, t_minima, meseta = temp, time.time(), False
        try:
            with self.monitor.trabajando():
                while time.time() - inicio < maximo_s:
                    if cancelar is not None and cancelar.wait(1.0):
                        break
                    if cancelar is None:
                        time.sleep(1.0)
                    temp = self.monitor.gpu(max_edad=1.0)
                    if temp is None or temp <= objetivo:
                        break
                    if tramo is not None and time.time() - inicio <= 4.0:
                        tramo.pico_en_pausa = max(tramo.pico_en_pausa or temp, temp)
                    if temp <= minima - 1:
                        minima, t_minima = temp, time.time()
                    elif time.time() - t_minima >= MESETA_S:
                        meseta = True
                        break
        finally:
            with self._cerrojo:
                self.pausa = None
        if meseta:
            self._anotar_reposo(minima)
        esperado = time.time() - inicio
        if avisar:
            ahora = self.monitor.gpu()
            texto = (f"La GPU no baja de {minima:.0f} °C: se reanuda tras {esperado:.0f} s."
                     if meseta else f"GPU a {ahora or 0:.0f} °C tras {esperado:.0f} s: se reanuda.")
            avisar({"tipo": "reanudando", "segundos": round(esperado), "temp_c": ahora,
                    "meseta": meseta, "mensaje": texto})
            if self.aviso:
                avisar({"tipo": "aviso_termico", "mensaje": self.aviso})
        return esperado

    def _anotar_reposo(self, minima: float):
        with self._cerrojo:
            previo = self.ajustes.get("reposo_c")
            if previo is not None and abs(float(previo) - minima) < 0.5:
                return
            self.ajustes["reposo_c"] = minima
            self._revisar_viabilidad()
            self._persistir(f"La GPU no baja de {minima:.0f} °C en pausa: se reanuda a "
                            f"{self.reanudar:.0f} °C.", {"reposo": minima})

    def _revisar_viabilidad(self):
        if self.viable:
            self.aviso = None
            return
        self.aviso = (f"Con el límite de {self.limite:.0f} °C la GPU no puede trabajar sin "
                      f"pasarlo: parada no baja de {self.ajustes['reposo_c']:.0f} °C y al "
                      f"empezar sube {self.salto:.0f} °C de golpe. Seguirá pausando, pero irá "
                      f"muy lento. Límite mínimo viable: {self.limite_minimo_viable:.0f} °C.")

    def antes_de_trabajar(self, cancelar: Optional[threading.Event] = None,
                          avisar: Optional[Evento] = None) -> float:
        """ Entre pasos: si la GPU no está a la temperatura de reanudar, se espera """
        temp = self.monitor.gpu()
        if temp is None or temp <= self.reanudar:
            return 0.0
        return self.enfriar("antes_de_paso", cancelar, avisar)

    def terminar_tramo(self, tramo: Tramo, motivo: Optional[str]):
        """ Aprende del tramo: salto al empezar, inercia al cortar, si llegó al límite """
        if motivo == "ritmo":
            return                  # tramos de un segundo: no enseñan nada sobre el salto ni la inercia
        with self._cerrojo:
            a = self.ajustes
            cambios = []
            # Salto: solo si el tramo duró lo bastante para medirlo
            if (tramo.temp_inicio is not None and tramo.max_arranque is not None
                    and tramo.segundos >= 1.5):
                medido = max(0.0, tramo.max_arranque - tramo.temp_inicio)
                if tramo.pico_en_pausa is not None and tramo.segundos <= SEGUNDOS_SALTO:
                    medido = max(medido, tramo.pico_en_pausa - tramo.temp_inicio)
                previo = a.get("salto_c")
                nuevo = medido if previo is None else 0.5 * float(previo) + 0.5 * medido
                # Solo se aprende hacia arriba de golpe; hacia abajo, despacio
                if previo is not None and nuevo < float(previo):
                    nuevo = 0.8 * float(previo) + 0.2 * medido
                a["salto_c"] = round(max(1.0, nuevo), 1)
            # Inercia tras cortar
            if tramo.temp_corte is not None and tramo.pico_en_pausa is not None:
                inercia = tramo.pico_en_pausa - tramo.temp_corte
                if inercia + 0.5 > float(a["margen"]):
                    a["margen"] = round(min(MARGEN_MAXIMO, inercia + 0.5), 1)
                    cambios.append(f"corta a {self.corte:.0f} °C")
            pico = tramo.pico_real
            if pico is not None and pico >= self.limite:
                a["alcances"] = int(a.get("alcances") or 0) + 1
                a["frescas_seguidas"] = 0
                self._revisar_viabilidad()
                self._persistir(
                    f"La GPU llegó a {pico:.0f} °C (límite {self.limite:.0f}). Salto al empezar: "
                    f"{self.salto:.0f} °C; ahora reanuda a {self.reanudar:.0f} °C"
                    + (f" y {cambios[0]}" if cambios else "") + ".",
                    {"pico": pico, "salto": self.salto})
                return
            if pico is not None and pico < self.limite - 3:
                a["frescas_seguidas"] = int(a.get("frescas_seguidas") or 0) + 1
                if a["frescas_seguidas"] >= FRESCAS_PARA_AFLOJAR and float(a["margen"]) > 1.0:
                    a["margen"] = max(1.0, float(a["margen"]) - 0.5)
                    a["frescas_seguidas"] = 0
            if cambios or a["frescas_seguidas"] % 4 == 0:
                self._persistir()


def _texto_pausa(motivo: str, temp: float, objetivo: float, limite: float) -> str:
    base = {
        "limite": f"La GPU está a {temp:.0f} °C, al borde del límite de {limite:.0f}",
        "prevision": f"La GPU va a llegar a {limite:.0f} °C (ahora {temp:.0f})",
        "antes_de_paso": f"La GPU está a {temp:.0f} °C",
    }.get(motivo, f"GPU a {temp:.0f} °C")
    return f"{base}: pausa hasta {objetivo:.0f} °C."


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
