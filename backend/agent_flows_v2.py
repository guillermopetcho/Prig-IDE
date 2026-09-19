"""
Motor de Flujos de Agentes Dinámicos, Grafos de Estado y Ciclos Recursivos (v2).
Inspirado en las arquitecturas estado del arte de LangGraph, CrewAI, AutoGen y Dify.

Características:
  1. GRAFO DE ESTADO (StateGraph): Estado tipado blackboard compartido entre nodos.
  2. CICLOS RECURSIVOS (Loops): Bucles de auto-reflexión (Generador <-> Crítico) con
     inyección iterativa de feedback, límite de profundidad y guardarraíles.
  3. ENRUTAMIENTO DINÁMICO (Router / Supervisor): Bifurcaciones inteligentes que deciden
     el siguiente nodo o subgrafo en tiempo de ejecución.
  4. SANDBOX DE HERRAMIENTAS: Ejecución aislada de código Python, captura de stdout/stderr
     y auto-depuración guiada ante Tracebacks.
  5. STREAMING TOKEN A TOKEN: Emisión de eventos NDJSON/SSE en vivo para interactividad total.
  6. GOBERNANZA TÉRMICA Y DE VRAM: Compatibilidad con el optimizador de hardware de Prig IDE.
"""

import os
import sys
import re
import json
import time
import queue
import subprocess
import threading
from datetime import datetime
from typing import Any, Dict, Generator, List, Optional, Tuple

# Constantes de configuración y límites seguros
MAX_RECURSION_DEPTH_DEFAULT = 4
MAX_RECURSION_DEPTH_HARD_LIMIT = 20
CARACTERES_POR_TOKEN = 3.6
TIMEOUT_SANDBOX_DEFECTO = 15

# Roles especializados con arquetipos de comportamiento
ROLES_V2 = {
    "programador": {
        "nombre": "Programador",
        "icono": "fa-code",
        "color": "#a6e3a1",
        "formato": "codigo",
        "temperatura": 0.2,
        "sistema": (
            "Eres un Ingeniero de Software y Algoritmos Senior. Escribes código limpio, "
            "completamente ejecutable, sin dependencias innecesarias y tratando exhaustivamente "
            "los casos límite. Cuando se te solicite código, devuélvelo dentro de un bloque ```python ... ``` "
            "listo para ser evaluado en un entorno de pruebas."
        ),
    },
    "analista": {
        "nombre": "Analista / Razonador",
        "icono": "fa-brain",
        "color": "#cba6f7",
        "formato": "texto",
        "temperatura": 0.4,
        "sistema": (
            "Eres un Investigador y Analista de Inteligencia Artificial. Descompones problemas complejos "
            "paso a paso, distinguiendo hechos comprobados de deducciones inferenciales. Expones el "
            "razonamiento formal antes de llegar a la conclusión."
        ),
    },
    "critico": {
        "nombre": "Crítico / Evaluador",
        "icono": "fa-magnifying-glass",
        "color": "#f38ba8",
        "formato": "json",
        "temperatura": 0.1,
        "sistema": (
            "Eres un Auditor de Calidad y Revisor Crítico. Inspeccionas el trabajo previo en busca de "
            "errores de lógica, fallas matemáticas, vulnerabilidades o modos de falla. "
            "Devuelves EXCLUSIVAMENTE un objeto JSON válido con la siguiente estructura exacta:\n"
            "{\n"
            '  "aprobado": true|false,\n'
            '  "score": 0.0 a 1.0,\n'
            '  "motivo": "resumen en una frase",\n'
            '  "problemas": ["problema 1", "problema 2"],\n'
            '  "sugerencias_mejora": ["accion concreta 1", "accion concreta 2"]\n'
            "}"
        ),
    },
    "corrector": {
        "nombre": "Corrector / Refinador",
        "icono": "fa-wrench",
        "color": "#fab387",
        "formato": "texto",
        "temperatura": 0.2,
        "sistema": (
            "Eres un Especialista en Refinamiento y Corrección. Recibes un trabajo anterior junto con la "
            "crítica o el Traceback de error recibido. Tu única tarea es corregir los defectos señalados "
            "preservando íntegramente las partes que ya funcionaban bien. Devuelve el resultado final pulido."
        ),
    },
    "router": {
        "nombre": "Supervisor / Enrutador",
        "icono": "fa-arrows-split_up_and_left",
        "color": "#89dceb",
        "formato": "json",
        "temperatura": 0.1,
        "sistema": (
            "Eres un Supervisor de Orquestación Multi-Agente. Evalúas la solicitud del usuario o el estado "
            "actual del flujo y determinas cuál es el siguiente agente especializado que debe intervenir. "
            "Devuelves EXCLUSIVAMENTE un objeto JSON con la forma:\n"
            '{"decision": "id_del_nodo_objetivo", "razon": "justificacion de la eleccion"}'
        ),
    },
    "sintetizador": {
        "nombre": "Sintetizador / Redactor Final",
        "icono": "fa-feather",
        "color": "#89b4fa",
        "formato": "markdown",
        "temperatura": 0.4,
        "sistema": (
            "Eres el Redactor y Sintetizador Ejecutivo. Consolidarás las salidas de los agentes previos, "
            "organizando un informe final coherente, estructurado con Markdown claro, diagramas o código verificado, "
            "listo para el usuario final."
        ),
    },
}


# ===========================================================================
# Herramientas del Entorno y Sandbox
# ===========================================================================

def ejecutar_sandbox_python(codigo: str, timeout: int = TIMEOUT_SANDBOX_DEFECTO) -> Dict[str, Any]:
    """ Ejecuta código Python en un subproceso aislado, capturando salida y errores. """
    # Extraer código si viene envuelto en markdown ```python
    match = re.search(r"```(?:python)?\s*([\s\S]*?)```", codigo)
    codigo_puro = match.group(1).strip() if match else codigo.strip()

    if not codigo_puro:
        return {
            "exito": False,
            "stdout": "",
            "stderr": "No se proporcionó código Python ejecutable.",
            "exit_code": 1,
            "segundos": 0.0,
        }

    t0 = time.time()
    try:
        proc = subprocess.run(
            [sys.executable, "-c", codigo_puro],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        dt = time.time() - t0
        stdout = proc.stdout.strip()
        stderr = proc.stderr.strip()
        exito = proc.returncode == 0 and not stderr

        return {
            "exito": exito,
            "stdout": stdout[:4000],
            "stderr": stderr[:4000],
            "exit_code": proc.returncode,
            "segundos": round(dt, 2),
        }
    except subprocess.TimeoutExpired:
        return {
            "exito": False,
            "stdout": "",
            "stderr": f"Error: La ejecución excedió el tiempo límite de {timeout} segundos (Timeout).",
            "exit_code": -1,
            "segundos": timeout,
        }
    except Exception as e:
        return {
            "exito": False,
            "stdout": "",
            "stderr": f"Error del entorno de ejecución: {str(e)}",
            "exit_code": -1,
            "segundos": round(time.time() - t0, 2),
        }


def extraer_json_seguro(texto: str) -> Optional[Any]:
    """ Extrae el primer objeto o lista JSON del texto, tolerando markdown alrededor """
    if not texto:
        return None
    
    # Limpiar bloques <think>
    limpio = re.sub(r"<think(?:ing)?>.*?</think(?:ing)?>\s*", "", texto, flags=re.S | re.I).strip()
    
    # Intento 1: parse directo
    try:
        return json.loads(limpio)
    except Exception:
        pass

    # Intento 2: buscar bloque ```json ... ```
    match_bloque = re.search(r"```(?:json)?\s*([\{\[][\s\S]*?[\}\]])\s*```", limpio)
    if match_bloque:
        try:
            return json.loads(match_bloque.group(1))
        except Exception:
            pass

    # Intento 3: parse balanceado de llaves
    for abre, cierra in (("{", "}"), ("[", "]")):
        inicio = limpio.find(abre)
        if inicio < 0:
            continue
        profundidad = 0
        en_cadena = False
        escape = False
        for i in range(inicio, len(limpio)):
            c = limpio[i]
            if escape:
                escape = False
                continue
            if c == "\\":
                escape = True
                continue
            if c == '"':
                en_cadena = not en_cadena
                continue
            if en_cadena:
                continue
            if c == abre:
                profundidad += 1
            elif c == cierra:
                profundidad -= 1
                if profundidad == 0:
                    try:
                        return json.loads(limpio[inicio:i + 1])
                    except Exception:
                        break
    return None


# ===========================================================================
# Estado del Flujo (AgentState)
# ===========================================================================

class AgentState:
    """ Blackboard Memory compartida que viaja a través de todos los nodos del grafo """
    def __init__(self, entrada_inicial: str = "", variables: Optional[Dict[str, Any]] = None):
        self.entrada_inicial = entrada_inicial
        self.variables: Dict[str, Any] = dict(variables or {})
        self.variables["entrada"] = entrada_inicial
        self.mensajes: List[Dict[str, Any]] = []
        self.salidas_nodos: Dict[str, str] = {}
        self.datos_nodos: Dict[str, Any] = {}
        self.artefactos: Dict[str, Any] = {}
        self.iteraciones_nodos: Dict[str, int] = {}
        self.criticas_pendientes: Dict[str, str] = {}
        self.historial_rutas: List[str] = []

    def set_var(self, clave: str, valor: Any) -> None:
        self.variables[clave] = valor

    def get_var(self, clave: str, defecto: Any = "") -> Any:
        return self.variables.get(clave, defecto)

    def registrar_salida(self, nodo_id: str, salida: str, datos: Optional[Any] = None) -> None:
        self.salidas_nodos[nodo_id] = salida
        self.variables[f"paso:{nodo_id}"] = salida
        self.variables["anterior"] = salida
        if datos is not None:
            self.datos_nodos[nodo_id] = datos
            self.variables[f"datos:{nodo_id}"] = datos
        self.historial_rutas.append(nodo_id)
        self.iteraciones_nodos[nodo_id] = self.iteraciones_nodos.get(nodo_id, 0) + 1

    def exportar_resumen(self) -> Dict[str, Any]:
        return {
            "entrada_inicial": self.entrada_inicial,
            "salidas_nodos": self.salidas_nodos,
            "datos_nodos": self.datos_nodos,
            "artefactos": self.artefactos,
            "iteraciones": self.iteraciones_nodos,
            "ruta_ejecucion": self.historial_rutas,
        }


# ===========================================================================
# Motor de Grafos Dinámicos y Recursivos (DynamicFlowEngine)
# ===========================================================================

class DynamicFlowEngine:
    """ Motor ejecutor de grafos multi-agente con enrutamiento dinámico y ciclos recursivos """

    def __init__(self, ai_engine, gobernador=None, num_ctx: int = 8192):
        self.ai = ai_engine
        self.gobernador = gobernador
        self.num_ctx = num_ctx
        self._stop_event = threading.Event()
        self._pausa_checkpoint = threading.Event()
        self._pausa_checkpoint.set() # No pausado por defecto
        self._checkpoint_respuesta: Optional[Dict[str, Any]] = None

    def detener(self) -> None:
        self._stop_event.set()
        self._pausa_checkpoint.set()

    def responder_checkpoint(self, decision: Dict[str, Any]) -> None:
        """ Reanuda la ejecución tras una pausa en un HumanCheckpoint """
        self._checkpoint_respuesta = decision
        self._pausa_checkpoint.set()

    def renderizar_prompt(self, plantilla: str, state: AgentState, nodo_id: str) -> str:
        """ Interpola variables del estado {entrada}, {anterior}, {paso:id}, {critica}, etc. """
        texto = plantilla or ""

        def reemplazar(match):
            clave = match.group(1).strip()
            if clave == "entrada":
                return state.entrada_inicial
            if clave == "anterior":
                return state.get_var("anterior", "")
            if clave == "critica":
                return state.criticas_pendientes.get(nodo_id, "")
            if clave.startswith("paso:"):
                pid = clave.split(":", 1)[1]
                return state.salidas_nodos.get(pid, "")
            if clave in state.variables:
                val = state.variables[clave]
                return str(val) if not isinstance(val, (dict, list)) else json.dumps(val, ensure_ascii=False, indent=2)
            return match.group(0)

        resultado = re.sub(r"\{([^{}]+)\}", reemplazar, texto)

        # Inyección automática de feedback si venimos de un bucle de crítica y el prompt no tenía {critica}
        critica_activa = state.criticas_pendientes.get(nodo_id, "")
        if critica_activa and "{critica}" not in plantilla:
            resultado += (
                "\n\n---\n⚠️ RETROALIMENTACIÓN DE LA REVISIÓN ANTERIOR:\n"
                "Tu intento previo fue auditado y se detectaron los siguientes aspectos a corregir:\n"
                f"{critica_activa}\n"
                "Por favor, genera una nueva versión refinada corrigiendo estos puntos específicos."
            )

        return resultado

    def _llamar_modelo_stream(self, nodo: Dict[str, Any], prompt: str) -> Generator[str, None, None]:
        """ Genera la respuesta del modelo emitiendo chunks de tokens en tiempo real """
        rol = ROLES_V2.get(nodo.get("rol"), ROLES_V2["analista"])
        modelo = nodo.get("modelo") or "qwen2.5-coder:7b"
        sistema = (nodo.get("system_prompt") or nodo.get("sistema") or "").strip() or rol["sistema"]
        temperatura = float(nodo.get("temperature", nodo.get("temperatura", rol["temperatura"])))
        max_tokens = int(nodo.get("max_tokens", 1600))
        pensar = nodo.get("think", nodo.get("pensar"))

        kwargs = {
            "model": modelo,
            "system_prompt": sistema,
            "options": {
                "temperature": temperatura,
                "num_predict": max_tokens
            }
        }
        if pensar is not None:
            kwargs["think"] = bool(pensar)

        for chunk in self.ai.generate_response(prompt, **kwargs):
            yield chunk

    def ejecutar_grafo(self, grafo: Dict[str, Any], entrada_inicial: str = "") -> Generator[Dict[str, Any], None, None]:
        """ Ejecuta el grafo dinámico emitiendo eventos de ciclo de vida en vivo """
        self._stop_event.clear()
        self._pausa_checkpoint.set()
        self._checkpoint_respuesta = None

        nodos = grafo.get("nodos") or grafo.get("pasos") or []
        if not nodos:
            yield {"tipo": "error", "mensaje": "El grafo no contiene nodos para ejecutar."}
            return

        mapa_nodos = {n["id"]: n for n in nodos}
        nodo_inicial = grafo.get("nodo_inicial") or nodos[0]["id"]
        
        state = AgentState(entrada_inicial=entrada_inicial, variables=grafo.get("variables_iniciales"))
        yield {
            "tipo": "grafo_inicio",
            "titulo": grafo.get("nombre") or grafo.get("titulo") or "Flujo de Agentes",
            "nodos_totales": len(nodos),
            "nodo_inicial": nodo_inicial,
            "timestamp": datetime.now().isoformat()
        }

        nodo_actual_id = nodo_inicial
        pasos_ejecutados = 0
        limite_pasos_seguridad = 40  # Evita cuelgues absolutos en bucles infinitos no controlados
        t_inicio_grafo = time.time()

        while nodo_actual_id and pasos_ejecutados < limite_pasos_seguridad:
            if self._stop_event.is_set():
                yield {"tipo": "cancelado", "mensaje": "Ejecución cancelada por el usuario."}
                return

            if nodo_actual_id not in mapa_nodos:
                yield {"tipo": "error", "mensaje": f"Nodo '{nodo_actual_id}' no encontrado en el grafo."}
                break

            nodo = mapa_nodos[nodo_actual_id]
            tipo_nodo = nodo.get("tipo", "agent")
            pasos_ejecutados += 1
            iteracion_actual = state.iteraciones_nodos.get(nodo_actual_id, 0) + 1

            yield {
                "tipo": "nodo_inicio",
                "id": nodo_actual_id,
                "nombre": nodo.get("nombre") or nodo_actual_id,
                "tipo_nodo": tipo_nodo,
                "rol": nodo.get("rol"),
                "modelo": nodo.get("modelo"),
                "iteracion": iteracion_actual,
                "segundos_acumulados": round(time.time() - t_inicio_grafo, 1)
            }

            # -------------------------------------------------------------
            # Caso 1: NODO TOOL / SANDBOX (Ejecución de código o herramienta)
            # -------------------------------------------------------------
            if tipo_nodo == "tool" or nodo.get("herramienta") == "python_sandbox":
                codigo_a_ejecutar = state.get_var("anterior", "")
                if nodo.get("codigo"):
                    codigo_a_ejecutar = self.renderizar_prompt(nodo["codigo"], state, nodo_actual_id)

                yield {"tipo": "tool_inicio", "id": nodo_actual_id, "herramienta": "python_sandbox"}
                res_tool = ejecutar_sandbox_python(codigo_a_ejecutar)
                salida_texto = (
                    f"--- RESULTADO DE EJECUCIÓN (Exit Code: {res_tool['exit_code']}, Tiempo: {res_tool['segundos']}s) ---\n"
                )
                if res_tool["stdout"]:
                    salida_texto += f"STDOUT:\n{res_tool['stdout']}\n"
                if res_tool["stderr"]:
                    salida_texto += f"STDERR / TRACEBACK:\n{res_tool['stderr']}\n"
                if not res_tool["stdout"] and not res_tool["stderr"]:
                    salida_texto += "(El proceso finalizó sin salida en consola)\n"

                state.registrar_salida(nodo_actual_id, salida_texto, res_tool)
                yield {
                    "tipo": "tool_fin",
                    "id": nodo_actual_id,
                    "exito": res_tool["exito"],
                    "salida": salida_texto,
                    "detalles": res_tool
                }

                # Determinación del siguiente nodo
                nodo_actual_id = nodo.get("next_node") or self._siguiente_secuencial(nodos, nodo_actual_id)
                continue

            # -------------------------------------------------------------
            # Caso 2: NODO HUMAN CHECKPOINT (Pausa para revisión / HITL)
            # -------------------------------------------------------------
            if tipo_nodo == "checkpoint":
                yield {
                    "tipo": "checkpoint_pausa",
                    "id": nodo_actual_id,
                    "mensaje": nodo.get("mensaje") or "Pausa para inspección humana del estado.",
                    "estado_actual": state.exportar_resumen()
                }
                self._pausa_checkpoint.clear()
                self._pausa_checkpoint.wait() # Bloquea hasta que la UI llame responder_checkpoint()
                
                if self._stop_event.is_set():
                    yield {"tipo": "cancelado", "mensaje": "Cancelado durante el checkpoint."}
                    return

                if self._checkpoint_respuesta and self._checkpoint_respuesta.get("modificacion"):
                    state.set_var("anterior", self._checkpoint_respuesta["modificacion"])
                    state.registrar_salida(nodo_actual_id, self._checkpoint_respuesta["modificacion"])
                
                nodo_actual_id = nodo.get("next_node") or self._siguiente_secuencial(nodos, nodo_actual_id)
                continue

            # -------------------------------------------------------------
            # Caso 3: NODO AGENT / ROUTER / CRITIC (Inferencia con LLM)
            # -------------------------------------------------------------
            prompt_procesado = self.renderizar_prompt(nodo.get("prompt", "{anterior}"), state, nodo_actual_id)
            chunks_salida = []

            yield {"tipo": "prompt_listo", "id": nodo_actual_id, "prompt_preview": prompt_procesado[:400]}

            try:
                for token in self._llamar_modelo_stream(nodo, prompt_procesado):
                    if self._stop_event.is_set():
                        break
                    chunks_salida.append(token)
                    yield {"tipo": "node_token", "id": nodo_actual_id, "token": token}
            except Exception as err:
                chunks_salida.append(f"\n[Error en ejecución del modelo: {err}]")
                yield {"tipo": "nodo_error", "id": nodo_actual_id, "error": str(err)}

            salida_completa = "".join(chunks_salida).strip()
            # Limpiar razonamiento interno <think> si es necesario
            salida_limpia = re.sub(r"<think(?:ing)?>.*?</think(?:ing)?>\s*", "", salida_completa, flags=re.S | re.I).strip()
            datos_json = extraer_json_seguro(salida_limpia)

            state.registrar_salida(nodo_actual_id, salida_limpia, datos_json)

            yield {
                "tipo": "nodo_fin",
                "id": nodo_actual_id,
                "salida": salida_limpia,
                "datos_json": datos_json,
                "iteracion": iteracion_actual
            }

            # -------------------------------------------------------------
            # LÓGICA DE TRANSICIÓN: BUCLES RECURSIVOS O ENRUTAMIENTO DINÁMICO
            # -------------------------------------------------------------
            siguiente = None

            # A) Verificar si este nodo tiene un ciclo recursivo configurado (Loop / Self-Reflection)
            loop_config = nodo.get("loop") or nodo.get("si_falla")
            if loop_config:
                destino_loop = loop_config.get("target") or loop_config.get("volver_a")
                max_iter = int(loop_config.get("max_iterations", loop_config.get("max_vueltas", MAX_RECURSION_DEPTH_DEFAULT)))
                vueltas_hechas = state.iteraciones_nodos.get(destino_loop, 0)

                # Comprobar si requiere re-ejecución recursiva
                debe_reciclar = False
                motivo_critica = ""

                if isinstance(datos_json, dict):
                    if datos_json.get("aprobado") is False:
                        debe_reciclar = True
                    elif datos_json.get("score") is not None and float(datos_json.get("score", 1.0)) < float(loop_config.get("min_score", 0.8)):
                        debe_reciclar = True
                    elif datos_json.get("problemas") or datos_json.get("incorrectas"):
                        debe_reciclar = True

                    # Formatear crítica para el siguiente intento
                    problemas = datos_json.get("problemas") or datos_json.get("incorrectas") or []
                    sugs = datos_json.get("sugerencias_mejora") or []
                    motivo_critica = f"Motivo: {datos_json.get('motivo', 'Fallas detectadas')}\n"
                    if problemas:
                        motivo_critica += "Problemas:\n" + "\n".join(f"- {p}" for p in problemas) + "\n"
                    if sugs:
                        motivo_critica += "Sugerencias:\n" + "\n".join(f"- {s}" for s in sugs)
                elif "Traceback" in salida_limpia or "Error:" in salida_limpia:
                    debe_reciclar = True
                    motivo_critica = f"Error de ejecución detectado:\n{salida_limpia[-1000:]}"

                if debe_reciclar and vueltas_hechas < max_iter:
                    state.criticas_pendientes[destino_loop] = motivo_critica
                    yield {
                        "tipo": "vuelta_recursiva",
                        "desde": nodo_actual_id,
                        "hacia": destino_loop,
                        "vuelta": vueltas_hechas + 1,
                        "max_vueltas": max_iter,
                        "motivo": motivo_critica[:300]
                    }
                    siguiente = destino_loop
                else:
                    if debe_reciclar:
                        yield {
                            "tipo": "limite_recursivo_alcanzado",
                            "nodo": nodo_actual_id,
                            "mensaje": f"Se alcanzó el límite máximo de {max_iter} iteraciones recursivas; avanzando."
                        }
                    state.criticas_pendientes.pop(destino_loop, None)

            # B) Si no hubo ciclo recursivo, verificar enrutamiento dinámico (Router / Supervisor)
            if not siguiente and tipo_nodo == "router":
                if isinstance(datos_json, dict) and datos_json.get("decision"):
                    decision = str(datos_json["decision"]).strip()
                    if decision in mapa_nodos:
                        siguiente = decision
                        yield {
                            "tipo": "enrutamiento_dinamico",
                            "supervisor": nodo_actual_id,
                            "destino": siguiente,
                            "razon": datos_json.get("razon", "Decisión del supervisor")
                        }

            # C) Reglas de bifurcación condicional explícitas
            if not siguiente and nodo.get("routing_rules"):
                for regla in nodo["routing_rules"]:
                    cond = regla.get("condition", "")
                    target = regla.get("target")
                    if target in mapa_nodos:
                        if cond == "default" or cond == "*" or not cond:
                            siguiente = target
                            break
                        if cond == "aprobado" and isinstance(datos_json, dict) and datos_json.get("aprobado") is True:
                            siguiente = target
                            break
                        if cond == "rechazado" and isinstance(datos_json, dict) and datos_json.get("aprobado") is False:
                            siguiente = target
                            break
                        if cond in salida_limpia:
                            siguiente = target
                            break

            # D) Conexión directa (Edge estándar)
            if not siguiente:
                siguiente = nodo.get("next_node") or self._siguiente_secuencial(nodos, nodo_actual_id)

            nodo_actual_id = siguiente

        # Fin del flujo
        resultado_final = state.get_var("anterior", "")
        yield {
            "tipo": "grafo_fin",
            "resultado_final": resultado_final,
            "resumen_estado": state.exportar_resumen(),
            "segundos_totales": round(time.time() - t_inicio_grafo, 1),
            "pasos_totales": pasos_ejecutados
        }

    @staticmethod
    def _siguiente_secuencial(nodos: List[Dict[str, Any]], actual_id: str) -> Optional[str]:
        """ Obtiene el siguiente nodo en orden lineal por defecto """
        for i, n in enumerate(nodos):
            if n["id"] == actual_id:
                if i + 1 < len(nodos):
                    return nodos[i + 1]["id"]
                return None
        return None


# ===========================================================================
# Biblioteca de Plantillas Profesionales SOTA
# ===========================================================================

def plantillas_profesionales_sota(modelo_base: str = "qwen2.5-coder:7b", modelo_razona: str = "qwen3:8b") -> List[Dict[str, Any]]:
    """ Colección de arquitecturas multi-agente de nivel industrial """
    m_coder = modelo_base or "qwen2.5-coder:7b"
    m_reason = modelo_razona or "qwen3:8b"

    return [
        {
            "id": "sota_self_healing_code",
            "nombre": "Auto-Corrección Recursiva de Código (Self-Healing Loop)",
            "descripcion": "El programador genera código, el sandbox lo ejecuta, el auditor examina el Traceback y cicla recursivamente hasta 4 veces hasta que el código corra perfecto sin errores.",
            "categoria": "Desarrollo y Código",
            "icono": "fa-rotate",
            "nodo_inicial": "coder",
            "nodos": [
                {
                    "id": "coder",
                    "nombre": "Ingeniero de Software",
                    "tipo": "agent",
                    "rol": "programador",
                    "modelo": m_coder,
                    "prompt": (
                        "Problema a resolver:\n{entrada}\n\n"
                        "Genera el código Python completo que resuelva el requerimiento de forma óptima. "
                        "Incluye casos de prueba al final del archivo ejecutando afirmaciones assert para validar la solución."
                    ),
                    "next_node": "sandbox"
                },
                {
                    "id": "sandbox",
                    "nombre": "Entorno Sandbox Python",
                    "tipo": "tool",
                    "herramienta": "python_sandbox",
                    "next_node": "evaluator"
                },
                {
                    "id": "evaluator",
                    "nombre": "Auditor de Código y Pruebas",
                    "tipo": "agent",
                    "rol": "critico",
                    "modelo": m_reason,
                    "prompt": (
                        "Inspecciona el código generado y la salida del sandbox:\n{anterior}\n\n"
                        "Determina si la solución es correcta y si todos los casos de prueba pasaron sin lanzar ningún Traceback o AssertionError. "
                        "Devuelve únicamente el JSON con 'aprobado', 'problemas' y 'sugerencias_mejora'."
                    ),
                    "loop": {
                        "target": "coder",
                        "max_iterations": 4,
                        "min_score": 0.95
                    },
                    "next_node": "synthesizer"
                },
                {
                    "id": "synthesizer",
                    "nombre": "Documentador y Entregable Final",
                    "tipo": "agent",
                    "rol": "sintetizador",
                    "modelo": m_coder,
                    "prompt": (
                        "Presenta la solución final verificada:\n{paso:coder}\n\n"
                        "Muestra el código pulido, explica la complejidad algorítmica temporal y espacial, y documenta la verificación exitosa obtenida en el sandbox."
                    )
                }
            ]
        },
        {
            "id": "sota_hierarchical_supervisor",
            "nombre": "Supervisor Jerárquico Dinámico (Router & Specialists)",
            "descripcion": "Un agente Supervisor analiza la complejidad y delega dinámicamente al especialista adecuado (Deep Learning, Tabular o Matemáticas), con verificación final.",
            "categoria": "Orquestación",
            "icono": "fa-arrows-split_up_and_left",
            "nodo_inicial": "supervisor",
            "nodos": [
                {
                    "id": "supervisor",
                    "nombre": "Supervisor Orquestador",
                    "tipo": "router",
                    "rol": "router",
                    "modelo": m_reason,
                    "prompt": (
                        "Analiza la siguiente tarea del usuario:\n{entrada}\n\n"
                        "Decide a cuál de estos especialistas enviar la tarea:\n"
                        "- 'dl_specialist': si involucra redes neuronales, PyTorch, visión o NLP.\n"
                        "- 'tabular_specialist': si involucra datos tabulares, XGBoost, LightGBM o feature engineering.\n"
                        "- 'math_specialist': si involucra demostraciones matemáticas, teoremas, álgebra lineal o probabilidad.\n\n"
                        "Devuelve el JSON con tu 'decision' y 'razon'."
                    )
                },
                {
                    "id": "dl_specialist",
                    "nombre": "Especialista en Deep Learning",
                    "tipo": "agent",
                    "rol": "programador",
                    "modelo": m_coder,
                    "prompt": "Diseña la arquitectura de Red Neuronal y código PyTorch para:\n{entrada}",
                    "next_node": "final_auditor"
                },
                {
                    "id": "tabular_specialist",
                    "nombre": "Especialista en Datos Tabulares y Ensembles",
                    "tipo": "agent",
                    "rol": "programador",
                    "modelo": m_coder,
                    "prompt": "Diseña la estrategia de Feature Engineering y modelo GBDT (LightGBM/XGBoost) para:\n{entrada}",
                    "next_node": "final_auditor"
                },
                {
                    "id": "math_specialist",
                    "nombre": "Especialista en Demostraciones y Teoría",
                    "tipo": "agent",
                    "rol": "analista",
                    "modelo": m_reason,
                    "prompt": "Formula la deducción matemática rigurosa y derivaciones de pérdida para:\n{entrada}",
                    "next_node": "final_auditor"
                },
                {
                    "id": "final_auditor",
                    "nombre": "Auditor y Sintetizador Ejecutivo",
                    "tipo": "agent",
                    "rol": "sintetizador",
                    "modelo": m_reason,
                    "prompt": "Consolida y presenta de forma exhaustiva la solución provista por el especialista:\n{anterior}"
                }
            ]
        },
        {
            "id": "sota_multi_agent_debate",
            "nombre": "Debate Dialéctico y Consenso Multi-Agente",
            "descripcion": "Dos agentes con perspectivas opuestas (Tesis optimista vs Antítesis crítica) debaten durante varias rondas hasta que un Árbitro neutral emite una resolución balanceada.",
            "categoria": "Razonamiento Avanzado",
            "icono": "fa-comments",
            "nodo_inicial": "thesis",
            "nodos": [
                {
                    "id": "thesis",
                    "nombre": "Agente Tesis (Proponente)",
                    "tipo": "agent",
                    "rol": "analista",
                    "modelo": m_reason,
                    "prompt": (
                        "Tema o decisión en cuestión:\n{entrada}\n\n"
                        "Propón la mejor estrategia arquitectónica defendiendo sus ventajas con rigor y casos de uso concretos."
                    ),
                    "next_node": "antithesis"
                },
                {
                    "id": "antithesis",
                    "nombre": "Agente Antítesis (Opositor Crítico)",
                    "tipo": "agent",
                    "rol": "critico",
                    "modelo": m_reason,
                    "prompt": (
                        "Inspecciona la propuesta del proponente:\n{paso:thesis}\n\n"
                        "Cuestiona duramente los puntos ciegos, sobrecostos de memoria/cómputo, posibles cuellos de botella y modos de falla inesperados."
                    ),
                    "next_node": "synthesis"
                },
                {
                    "id": "synthesis",
                    "nombre": "Árbitro Neutral (Consenso de Producción)",
                    "tipo": "agent",
                    "rol": "sintetizador",
                    "modelo": m_reason,
                    "prompt": (
                        "Examina el debate entre el Proponente y el Opositor:\n"
                        "PROPUESTA:\n{paso:thesis}\n\n"
                        "OBJECIONES Y CONTRA-ARGUMENTOS:\n{paso:antithesis}\n\n"
                        "Actuando como Ingeniero Principal, emite la recomendación definitiva balanceando robustez, simplicidad y rendimiento real."
                    )
                }
            ]
        },
        {
            "id": "sota_paper_deconstruction",
            "nombre": "Deconstrucción Científica de Papers y Algoritmos ML",
            "descripcion": "Extrae formulaciones matemáticas de un algoritmo, realiza la demostración de sus teoremas, implementa NumPy puro y valida en sandbox.",
            "categoria": "Machine Learning",
            "icono": "fa-graduation-cap",
            "nodo_inicial": "extractor",
            "nodos": [
                {
                    "id": "extractor",
                    "nombre": "Extractor Teórico Formal",
                    "tipo": "agent",
                    "rol": "analista",
                    "modelo": m_reason,
                    "prompt": "Paper o Algoritmo:\n{entrada}\n\nIdentifica la función objetivo canónica, espacio de hipótesis y formulación matemática formal.",
                    "next_node": "numpy_coder"
                },
                {
                    "id": "numpy_coder",
                    "nombre": "Implementador NumPy Puro",
                    "tipo": "agent",
                    "rol": "programador",
                    "modelo": m_coder,
                    "prompt": (
                        "A partir de la formulación teórica:\n{paso:extractor}\n\n"
                        "Escribe la clase completa en Python utilizando únicamente NumPy (sin scikit-learn). "
                        "Incluye fit(), predict() y un bloque final de prueba sintética con datos generados aleatoriamente."
                    ),
                    "next_node": "sandbox_val"
                },
                {
                    "id": "sandbox_val",
                    "nombre": "Verificador Numérico en Sandbox",
                    "tipo": "tool",
                    "herramienta": "python_sandbox",
                    "next_node": "reporter"
                },
                {
                    "id": "reporter",
                    "nombre": "Monografía Técnica Final",
                    "tipo": "agent",
                    "rol": "sintetizador",
                    "modelo": m_coder,
                    "prompt": "Presenta la monografía técnica consolidada con fórmulas LaTeX, análisis de condicionamiento espectral y el código NumPy verificado."
                }
            ]
        }
    ]

