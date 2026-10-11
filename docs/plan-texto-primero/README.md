# Plan 0 — tareas para implementar

**Para**: el modelo que programe cada tarea (sin el contexto de la conversación en que se diseñó) y quien coordina.
Cada tarea es un archivo de esta carpeta (`T1` … `T8`) y se puede entregar sola a un modelo junto con este README.

## Estado (09/10/2026)

| Tarea | Estado |
|---|---|
| T1 tope del caché | **hecha**: tope por defecto 32 GB (el de antes) y reserva de 20 GB; 4 tests nuevos |
| T2 API y panel | **hecha**: `cache_gb`/`cache_reserva_gb` en `POST /api/recursos/moe`, campo en el panel del motor; 1 test nuevo y 1 actualizado |
| T3 hechos en modo general | **hecha**: `hechos_caracteres` en el evento del banco; `test_chat_con_banco` ampliado y 1 test nuevo |
| T4 modo del banco | **hecha**: `banco_modo` (petición y configuración), `_unidad_para` devuelve `(unidad, motivo)`, selector en el panel del banco, motivo en el aviso del chat; 2 tests nuevos y `test_modo_unidad` actualizado |
| T5 leer al vuelo | **hecha**: `_leer_unidad_antes` en `app.py`; 3 tests nuevos |
| T6 precalentar | pendiente (opcional) |
| T7 medición | **hecha** (09/10, versión corta: 34 respuestas + una segunda tanda de 18, auditadas a mano): el modo queda `auto` y el tope en 32 GB, sin fichas; ver `docs/estudio-banco.md`, «Texto primero: medición corta», y `docs/estudio-banco/resultados/texto-primero/` |
| T7, propuestas | **hechas** (10/10): las 5 propuestas implementadas (7 tests nuevos, 1030 en verde) y re-medidas: los modos quedan parejos; ver `docs/estudio-banco.md` |
| Corrección de fallas (10/10) | **hecha**: 1047 tests en verde; a84a 3 de 3; E8: 7 de los 8 errores detectados de forma estable (B2, 2 de 3); ver `docs/estudio-banco.md`, «Retomado y cerrado» |
| T8 limpieza y documentación | **hecha** (10/10): modo `auto` con 32 GB y reserva de 20 GB; borrados los 21 estados que solo usaba el estudio (5,24 GB, confirmado por el usuario); `~/.cache/prig-estudio` se conserva |

Los 12 tests nuevos fallan sobre el backend anterior (sistema congelado `09d615ce…`) y pasan con los cambios; la batería
completa: 1017 tests, 0 fallos.

## Contexto (lo mínimo para no romper nada)

- Prig es un IDE de aprendizaje con un motor MoE local: Qwen3.6-35B-A3B servido por un `llama-server` propio
  (`backend/ai_engine/motor_moe.py`), con expertos en CPU y núcleo en GPU.
- El **banco del proyecto** (`backend/banco_proyecto.py`, SQLite) indexa el código, los símbolos, el grafo de llamadas y
  hechos (quién lee qué configuración, qué endpoint expone cada función…). Ocupa ~30 MB por millón de tokens.
- El motor guarda en disco el **estado** tras leer un prefijo grande y lo restaura en 0,1–0,4 s. Ocupa ~21 GB por millón
  de tokens y no se comprime (zstd: −4 %).
- **Modo unidad** (`backend/lectura_unidades.py`): el proyecto se parte en unidades de ≤ 16K tokens; si la unidad que
  corresponde a la pregunta tiene su lectura guardada, se restaura y el modelo responde desde ahí.
  **Modo general**: si no, el contexto se arma con texto del banco (`BancoProyecto.componer`) en cada pregunta.
- Medido (docs/estudio-banco.md): el modo general acertó 97 % y el de unidad 86 % en las mismas clases de pregunta.
- **Objetivo del plan**: el texto (el banco) es la memoria; los estados del motor son un caché descartable con tope
  configurable (0 = apagado). Ninguna respuesta debe depender de que exista un estado.
- Plan, decisiones y riesgos: `docs/plan-texto-primero.md`.

## Reglas para todas las tareas

1. **No tocar nada que forme parte del prefijo guardado de las unidades**: `lectura_unidades.SISTEMA_LECTOR`,
   `HERRAMIENTAS_UNIDAD` (nombres y orden), `LectorUnidades.mensajes`, `LectorUnidades.tarjeta_global`,
   `LectorUnidades.llave`; los textos de las definiciones de las herramientas `consola`, `ver_simbolo` y `anotar`
   (`herramientas_chat.py`, `DEFINICIONES` / `DEFINICIONES_BANCO`); ni cómo `motor_moe.Motor._preparar_proyecto`
   calcula la clave del estado (`huella`). Cambiar cualquiera de esas cosas invalida las ~96 lecturas guardadas
   (≈45 min de relectura y ~25 GB).
2. **Los tests no tocan la configuración real** (`~/.prig_ai_config.json`), ni el Ollama del sistema, ni arrancan el
   `llama-server` real. Patrones que ya existen y hay que usar:
   - `mock.patch.object(app.ai_engine, "_save_config", lambda: None)` (ver `tests/test_motor_moe.py`, clase con
     `test_estado_y_ajustes`);
   - `tempfile.TemporaryDirectory()` + `mock.patch.object(motor_moe, "CARPETA_PROYECTOS", d)`;
   - el servidor falso de `tests/test_motor_moe.py` (`ServidorFalso`, clase `DePuntaAPunta`: el motor se crea con
     `motor_moe.Motor()` y `asegurar` está parcheado).
3. Comentarios, docstrings y textos de la interfaz **en español**, con el estilo de cada archivo: explican el porqué y
   citan la fuente de los números medidos (`docs/estudio-banco.md`, `docs/plan-texto-primero.md`).
4. **Solo los archivos que nombra la tarea.** Hay trabajo del usuario en curso en otros archivos (`backend/llm_director.py`,
   `backend/motor_aprendizaje_nodos.py`, varios de `frontend/js/`): no tocarlos ni reformatearlos.
5. **Sin commits**: los hace el usuario.
6. **Cada test nuevo tiene que fallar sin el cambio** (comprobarlo una vez, por ejemplo desactivando el cambio con un
   `mock`) y la batería completa tiene que quedar en verde:

   ```
   cd backend && PRIG_SIN_MOTOR_SUAVE=1 ../.venv/bin/python -m unittest discover -s tests -t .
   ```
   Al 09/10/2026: 1006 tests en ~80 s, 0 fallos.

## Tareas

| Tarea | Qué | Archivos | Depende de | Tiempo |
|---|---|---|---|---|
| [T1](T1-motor-tope-del-cache.md) | Tope configurable del caché de estados en el motor (0 = no guardar), reserva de disco | `ai_engine/motor_moe.py`, `ai_engine/ai_engine_class.py`, `tests/test_motor_moe.py` | — | 1–1,5 h |
| [T2](T2-api-y-panel-del-tope.md) | El tope visible y editable: API y panel del motor | `app.py` (endpoint del motor), `frontend/js/temperaturas.js`, `tests/test_motor_moe.py` | T1 | ~1 h |
| [T3](T3-hechos-en-modo-general.md) | El modo general recibe los hechos del banco (paridad con el de unidad) | `app.py` (`ai_chat`), `tests/test_banco_proyecto.py` | — | 30–45 min |
| [T4](T4-modo-del-banco.md) | Modo del banco forzable: auto / general / unidad, con el motivo informado | `app.py`, `ai_engine/ai_engine_class.py` (config), `frontend/js/banco_proyecto.js`, `tests/test_banco_proyecto.py` | — | 1–1,5 h |
| [T5](T5-leer-al-vuelo.md) | Con modo «unidad» y la unidad sin estado: leerla antes de responder | `app.py` (`_chat_eventos`), `tests/test_banco_proyecto.py` | T4 (y T1 para el tope) | ~1 h |
| [T6](T6-precalentar.md) | (Opcional) Precalentar lecturas desde la app hasta llenar el tope | `app.py`, `frontend/js/banco_proyecto.js`, tests | T1, T4 | 1,5–2 h |
| [T7](T7-medicion.md) | Medición corta: 12 preguntas de Prig (una por modo de falla) y 5 de E8, en los dos modos, analizadas a fondo | `docs/estudio-banco/sonda.py`; GPU libre | T1–T5 | ~35 min de modelo + ~45 min de análisis |
| [T8](T8-limpieza-y-documentacion.md) | Limpieza (con confirmación) y documentación | docs; `~/.cache` | T7 | 30–45 min |

**Reparto en paralelo** (dos modelos):

- Línea 1, motor: **T1 → T2**.
- Línea 2, chat: **T3 → T4 → T5**. T5 lee `ai_engine.config.get("moe_cache_gb")`; si T1 todavía no está, ese valor es
  `None` y se trata como «sin tope explícito» (comportamiento de hoy).
- Después, de a una: T6 (opcional), **T7** (necesita la GPU y la máquina libre: un solo modelo a la vez), T8.

**Conflictos posibles**: T2, T3, T4 y T5 tocan `backend/app.py` en zonas distintas (endpoint del motor, `ai_chat`,
`_unidad_para`, `_chat_eventos`). T1 y T2 tocan `tests/test_motor_moe.py`. Si se hacen en paralelo, integrar por bloques
y correr la batería completa después de cada integración.

## Qué entrega cada tarea

1. Los archivos cambiados y, para cada uno, qué se cambió.
2. Los tests nuevos y la comprobación de que fallan sin el cambio.
3. La salida final de la batería completa.
4. Cualquier desvío de la especificación, y por qué.

## Cuándo está terminado el plan

1. El disco de estados nunca supera el tope configurado; con 0 no se escribe ninguno. El banco (SQLite) es lo único
   obligatorio.
2. Ninguna respuesta depende de un estado: sin estado, la pregunta se responde en modo general con los mismos hechos.
3. T7 midió el modo general frente al de unidad, y encontrar errores (E8) en los dos.
4. El usuario ve cuánto ocupa el caché, cambia el tope y lo vacía desde la app.
5. La batería completa está en verde.
