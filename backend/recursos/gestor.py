"""
Gestor: la fachada que usa el resto de Prig.

Junta detector, fichas, calculadora, almacén y servidor, y añade lo que solo tiene
sentido con el programa en marcha:

  · radiografía con caché: lo estático (GPU, CPU, ancho de banda de la RAM) se
    mide una vez por huella; lo que cambia (VRAM usada, temperatura, RAM libre) se
    refresca cada pocos segundos.
  · veredictos de todos los modelos instalados para un uso.
  · opciones para una petición: lo aplicado por el usuario manda; si no hay, la
    recomendación.
  · recuperación de falta de memoria en caliente, recordando lo que funcionó.
"""

import threading
import time
from typing import Any, Dict, List, Optional

from . import calibracion, detector, ficha as fichas_mod, termico as termico_mod
from .almacen import almacen
from .calculadora import GB, Maquina, elegir_modelo, recomendar
from .perfiles import PERFILES

REFRESCO_S = 5


class Gestor:
    def __init__(self, catalogo: Optional[Dict[str, Any]] = None):
        self.catalogo = catalogo or {}
        self._cerrojo = threading.RLock()
        self._rad: Optional[Dict[str, Any]] = None
        self._rad_t = 0.0
        self._fichas: Dict[str, Dict[str, Any]] = {}   # nombre|digest -> ficha
        self.ultimo_oom: Dict[str, Dict[str, Any]] = {}

    # ------------------------------------------------------------ máquina
    def radiografia(self, fresca: bool = False) -> Dict[str, Any]:
        with self._cerrojo:
            if self._rad and not fresca and time.time() - self._rad_t < REFRESCO_S:
                return self._rad
            previa = self._rad or almacen().radiografia or {}
            rad = detector.radiografia(medir_ram=False)
            # El ancho de banda de la RAM no cambia mientras la huella sea la misma
            if previa.get("huella") == rad["huella"] and previa.get("ancho_banda_ram_gbps"):
                rad["ancho_banda_ram_gbps"] = previa["ancho_banda_ram_gbps"]
            else:
                rad["ancho_banda_ram_gbps"] = detector.ancho_banda_ram()
            if not self._rad or self._rad.get("huella") != rad["huella"] or fresca:
                almacen().registrar_radiografia(rad)
            self._rad, self._rad_t = rad, time.time()
            return rad

    def maquina(self, fresca: bool = False) -> Maquina:
        rad = self.radiografia(fresca)
        return Maquina(rad, almacen().calibracion(rad["huella"]))

    # ------------------------------------------------------------ fichas
    def ficha(self, nombre: str, red: bool = True) -> Dict[str, Any]:
        clave = nombre
        with self._cerrojo:
            if clave in self._fichas:
                return self._fichas[clave]
        f = fichas_mod.obtener(nombre, self.catalogo, red=red)
        if not f.get("estimada"):
            with self._cerrojo:
                self._fichas[clave] = f
        return f

    def fichas_instaladas(self) -> List[Dict[str, Any]]:
        try:
            inst = fichas_mod.instalados()
        except Exception:
            return []
        salida = []
        for nombre, info in inst.items():
            clave = f"{nombre}|{info.get('digest', '')}"
            with self._cerrojo:
                f = self._fichas.get(clave)
            if f is None:
                try:
                    f = fichas_mod.desde_ollama(nombre)
                except Exception:
                    continue
                with self._cerrojo:
                    self._fichas[clave] = f
                    self._fichas[nombre] = f
            salida.append(f)
        return salida

    def olvidar_fichas(self):
        with self._cerrojo:
            self._fichas.clear()

    # ------------------------------------------------------------ recomendar
    def medidas(self) -> Dict[str, Dict[str, Any]]:
        """ Calidad del canario por modelo, de las pruebas en esta máquina """
        por_modelo: Dict[str, Dict[str, Any]] = {}
        for clave, p in almacen().pruebas().items():
            modelo = clave.split("|")[0]
            if p.get("ok") and p.get("calidad") is not None:
                previa = por_modelo.get(modelo)
                if not previa or p.get("fecha", "") > previa.get("fecha", ""):
                    por_modelo[modelo] = p
        return por_modelo

    def veredictos(self, perfil: str = "tutor", tirador: str = "equilibrado") -> Dict[str, Any]:
        maq = self.maquina()
        filas = elegir_modelo(self.fichas_instaladas(), maq, perfil, tirador, self.medidas())
        pruebas = almacen().pruebas()
        for fila in filas:
            p = pruebas.get(almacen().clave_prueba(fila["modelo"], perfil))
            if p:
                fila["prueba"] = {k: p.get(k) for k in
                                  ("ok", "tok_s", "calidad", "fecha", "error", "opciones")}
        return {"perfil": perfil, "tirador": tirador, "maquina": maq.resumen(),
                "servidor": maq.servidor, "modelos": filas}

    def recomendar(self, modelo: str, perfil: str = "tutor",
                   tirador: str = "equilibrado") -> Dict[str, Any]:
        maq = self.maquina()
        f = self.ficha(modelo)
        rec = recomendar(f, maq, perfil, tirador)
        p = almacen().prueba(f["nombre"], perfil)
        if p:
            rec["prueba"] = p
            # Lo medido manda: si la prueba tuvo que bajar el contexto, se respeta
            if p.get("ok") and p.get("opciones", {}).get("num_ctx", 1e9) < rec["opciones"].get("num_ctx", 0):
                rec["opciones"]["num_ctx"] = p["opciones"]["num_ctx"]
                rec["ajustada_por_prueba"] = True
        rec["ficha"] = {k: f.get(k) for k in
                        ("nombre", "origen", "arquitectura", "cuantizacion", "parametros",
                         "parametros_activos", "es_moe", "capas", "contexto_max", "piensa",
                         "vision", "herramientas", "estimada")}
        rec["ficha"]["gb"] = round(f.get("bytes_peso", 0) / GB, 2)
        return rec

    def opciones_para(self, perfil: str, modelo: str) -> Dict[str, Any]:
        """ Lo que una petición de este uso debe mandar a Ollama """
        aplicado = almacen().aplicado(perfil)
        if aplicado and aplicado.get("modelo") == modelo:
            return dict(aplicado.get("opciones") or {})
        try:
            return dict(self.recomendar(modelo, perfil)["opciones"])
        except Exception:
            return {}

    # ------------------------------------------------------------ en vivo
    def estado_vivo(self) -> Dict[str, Any]:
        rad = self.radiografia()
        g = (rad.get("gpus") or [{}])[0]
        mem = rad.get("memoria") or {}
        temp = g.get("temperatura_c")
        gob = termico_mod.gobernador()
        if temp is None:
            termico = "desconocido"
        elif temp >= gob.limite:
            termico = "caliente"
        elif temp >= gob.reanudar:
            termico = "templado"
        else:
            termico = "normal"
        avisos = []
        ajenos = g.get("otros_procesos") or []
        if ajenos:
            mb = sum(p.get("mb", 0) for p in ajenos)
            avisos.append(f"Otros programas usan {mb / 1024:.1f} GB de la GPU "
                          f"({', '.join(sorted({p['proceso'] for p in ajenos}))}): "
                          f"queda menos sitio para los modelos.")
        if mem.get("swap_usada", 0) > 1 * GB:
            avisos.append(f"El sistema está usando {mem['swap_usada'] / GB:.1f} GB de swap: "
                          f"con un modelo repartido en RAM irá muy lento.")
        ener = rad.get("energia") or {}
        if ener.get("con_bateria"):
            avisos.append("Estás con batería: la GPU rinde menos y se agota rápido.")
        if termico == "caliente":
            avisos.append(f"La GPU está a {temp:.0f} °C (límite {gob.limite:.0f}). Los "
                          f"flujos se pausan hasta que baje a {gob.reanudar:.0f}.")
        return {
            "gpu": {k: g.get(k) for k in ("nombre", "vram_total_mb", "vram_usada_mb",
                                           "temperatura_c", "consumo_w", "uso_pct")},
            "termico": termico,
            "ram_disponible_gb": round(mem.get("ram_disponible", 0) / GB, 1),
            "swap_usada_gb": round(mem.get("swap_usada", 0) / GB, 1),
            "energia": ener,
            "ollama": {k: (rad.get("ollama") or {}).get(k) for k in
                       ("responde", "version", "dueno", "modelos_cargados")},
            "otros_procesos_gpu": ajenos,
            "avisos": avisos,
        }

    # ------------------------------------------------------------ OOM
    def recuperar_oom(self, modelo: str, opciones: Dict[str, Any],
                      mensaje: str) -> Optional[Dict[str, Any]]:
        """ Opciones más pequeñas tras una falta de memoria, o None si no queda margen """
        if not calibracion.es_oom(mensaje):
            return None
        try:
            f = self.ficha(modelo, red=False)
        except Exception:
            f = {"capas": 32}
        base = {k: v for k, v in opciones.items() if k in ("num_ctx", "num_gpu")}
        if base.get("num_gpu", -1) < 0:
            base.pop("num_gpu", None)
        siguiente = calibracion.reducir(f, base)
        if siguiente is None:
            return None
        self.ultimo_oom[modelo] = {"fecha": time.strftime("%Y-%m-%dT%H:%M:%S"),
                                   "antes": base, "despues": siguiente}
        almacen().evento("oom", f"{modelo} se quedó sin memoria; reintento con {siguiente}.",
                         {"modelo": modelo, "antes": base, "despues": siguiente,
                          "mensaje": mensaje[:300]})
        return siguiente


PERFILES_IDS = list(PERFILES)

_gestor: Optional[Gestor] = None
_gestor_cerrojo = threading.Lock()


def gestor(catalogo: Optional[Dict[str, Any]] = None) -> Gestor:
    global _gestor
    with _gestor_cerrojo:
        if _gestor is None:
            _gestor = Gestor(catalogo)
        elif catalogo and not _gestor.catalogo:
            _gestor.catalogo = catalogo
        return _gestor
