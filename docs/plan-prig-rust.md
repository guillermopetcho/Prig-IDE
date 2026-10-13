# Plan: Prig entero en Rust

**Para**: el usuario y quien implemente cada fase (también otra sesión u otro modelo, sin el contexto de la
conversación). **Fecha**: 13/10/2026. **Estado**: propuesta. Antecedentes:

- [plan-banco-rust.md](plan-banco-rust.md): el banco ya está en Rust, con su método y sus comparadores.
- [revision-rust-2026-10-13.md](revision-rust-2026-10-13.md): por qué reimplementar rutas sin portar su subsistema
  rompió Prig.
- [informe-rust-moe.md](informe-rust-moe.md): mediciones de dónde está el tiempo.

## 0. En una página

- **Qué pasa a Rust**:
  - el backend entero: 54.232 líneas de Python en 139 archivos y 382 rutas de `app.py`;
  - la ventana de escritorio (`main.py` con pywebview y Qt).
- **Qué queda como está** (no es Python de Prig):
  - **La interfaz** en HTML/JS dentro de la ventana. Sus partes pesadas ya van a WASM (motor gráfico).
  - **El motor del modelo**: el fork de llama.cpp en C++/CUDA.
  - **Python solo como intérprete externo** para ejecutar el código Python que escriben el usuario o el modelo
    (ejecutar archivos, cuadernos, tests de los desafíos, consola `P`). Igual que hoy se usan `gcc` o `node`: un IDE
    de Python necesita Python, pero Prig no corre sobre él.
- **Cómo**: subsistema por subsistema, cada uno **entero**, con su estado, sus hilos y sus archivos, como un crate
  de Rust puro. Cada uno se verifica contra Python con las mismas entradas antes de reemplazarlo (sección 4).
  **Transición** (decidida en F0, ver sección 4.1): mientras su anfitrión (el chat y las rutas) siga en Python, el
  crate se usa desde Python con PyO3 (módulo `prig_nativo`), como el banco con `prig_banco`. Un solo proceso y un solo
  dueño del estado, con la lógica, los hilos y los sensores en Rust, sin GIL. Cuando el chat y las rutas pasan al
  servidor en Rust (F4, F9), el mismo crate se usa ahí directamente. Al final se quita el backend de Python.
- **Qué gana Prig**: arranque en centésimas de segundo, mucha menos memoria, lo que corre de fondo sin pelear con el
  motor por la CPU y el calor, y operaciones de archivos, PDF y biblioteca varias veces más rápidas. **La respuesta
  del chat no se acelera**: la escribe el modelo (C++/CUDA); el Python que hay en ese camino cuesta 4,6 µs por token
  (sección 2).
- **Costo**: 42–60 sesiones en 11 fases (F0–F10). Las primeras dan resultados por sí solas.

## 1. Lo que hay

| Subsistema | Líneas | Módulos | Bibliotecas de Python que usa | En Rust |
|---|---|---|---|---|
| 1. Recursos, térmico y GPU | 5.176 | 20 | psutil, NVML por ctypes, subprocess | `sysinfo`, `nvml-wrapper`, hwmon; `prig_suave.c` y el ayudante `prig-energia` siguen igual |
| 2. Plataforma: archivos, IDE, configuración, ejecución | 2.983 | 12 | sqlite3, subprocess, tkinter (selector de carpeta) | `rusqlite`, `tokio::process`, `rfd` o zenity |
| 3. Motor de IA, MoE y chat | 8.965 | 19 | requests, subprocess (llama-server), ddgs (búsqueda web) | `reqwest`, `tokio::process`, `scraper`; el banco ya está (`banco-core`) |
| 4. Modelos y descargas | 1.598 | 3 | requests | `reqwest` con reanudación |
| 5. Biblioteca, conocimiento y PDF | 9.960 | 54 | pypdf, reportlab, pygments, beautifulsoup4, sqlite3 | `pdf-extract`/`lopdf` o pdfium, generación de PDF (`printpdf`/`typst` o imprimir desde la ventana), `syntect`, `scraper`, `tantivy` o FTS5 |
| 6. Aprendizaje y desafíos | 7.541 | 13 | sqlite3, subprocess (tests en Python) | `rusqlite`; los tests siguen corriendo con el intérprete de Python |
| 7. Integraciones: GitHub, Kaggle, YouTube, Hub | 6.943 | 14 | requests, git por subprocess | `reqwest`, `git2` o el `git` del sistema |
| 8. Agentes y director | 3.832 | 3 | requests | `reqwest` |
| 9. Rutas HTTP (`app.py`) | 7.668 | 1 | fastapi, uvicorn, pydantic | `axum` (ya en marcha), `serde` |
| Ventana de escritorio (`main.py`) | 459 | 1 | pywebview, PyQt6, QtWebEngine | `tao` + `wry` (o Tauri) |

Aparte: 18.117 líneas de tests de Python, que pasan a Rust con cada subsistema, y 54.482 líneas de JavaScript del
frontend, que se quedan.

## 2. Velocidad: qué mejora y qué no

| Qué | Hoy | En Rust | Fuente |
|---|---|---|---|
| Arranque del backend | 3,6 s | ~0,02 s | medido el 13/10 (el servidor en Rust actual arranca en 0,014 s) |
| Memoria del backend en reposo | 108 MB, sin proyecto ni modelos | 5–30 MB | medido (el servidor en Rust actual ocupa ~5 MB) |
| Indexar el banco de Prig | 9,3 s | 0,91 s | medido (hecho) |
| Hechos de una pregunta | 190–240 ms | 40–76 ms | medido (hecho) |
| Modo frío con Prig ocupado | el tramo de 6 ms se estira 5,2 ms (87 %) | < 0,3 ms | medido en Python; en Rust, estimado |
| FFT del visualizador de audio | 1,58 ms por cuadro (~9 % de un núcleo, con el GIL) | microsegundos | medido en Python; en Rust, estimado |
| Leer PDFs (pypdf es Python puro) | sin medir | estimado 5–20× | se mide en F5 |
| Búsqueda BM25 de la biblioteca (en Python, todo el índice en memoria) | sin medir | estimado varias veces | se mide en F5 |
| Traducir cada token del chat | 4,6 µs | igual | medido: no se nota |
| Escribir la respuesta del modelo | 38–68 tok/s | **igual** | la hace llama.cpp (C++/CUDA) |

Lo que el usuario va a notar:

- Prig abre al instante y ocupa poca memoria.
- Abrir y buscar en la biblioteca y los PDF es más rápido.
- Lo que corre de fondo (sensores, vigilantes, analistas) deja de competir con el motor por la CPU. Como el motor
  pierde hasta un 14 % con carga en los núcleos E, eso sí sube algo los tok/s con Prig ocupado.

Lo que no cambia es cuánto tarda el modelo en escribir.

## 3. Arquitectura de destino

```
prig (un solo binario de Rust)
├── ventana (tao + wry) ─────────── la interfaz HTML/JS (sin cambios) + el motor gráfico en WASM
├── servidor (axum) ─────────────── las 382 rutas, en crates por subsistema
│     ├── prig-recursos   (sensores, gobernador térmico, modo frío, calculadora)
│     ├── prig-plataforma (archivos, IDE, configuración, ejecución)
│     ├── prig-ia         (Ollama, Gemini, motor MoE, chat, herramientas, lectura por unidades)
│     ├── banco-core      (hecho)
│     ├── prig-biblioteca (libros, PDF, conocimiento, exportar)
│     ├── prig-aprendizaje, prig-integraciones, prig-agentes
├── llama-server (C++/CUDA, hijo) ── el motor MoE, como hoy
└── python3 (hijo, solo como herramienta) ── ejecutar el código Python del usuario o del modelo:
      archivos, cuadernos (kernel), tests de desafíos y la consola P aislada (usa prig_banco para los datos)
```

## 4. Reglas (aprendidas con el banco y en la revisión del 13/10)

1. **Un subsistema se porta entero o no se porta.** Nada de rutas en Rust que respondan por un estado que vive en
   Python: así se rompieron el chat, la configuración, el modo frío y el banco.
2. **Un solo dueño por estado.** Mientras dura la transición, cada archivo de configuración tiene un solo escritor.
   Cuando un subsistema pasa a Rust, el Python que lo necesita lo llama por la API interna del servidor (un cliente
   chico, `backend/nativo.py`), no por una copia propia.
3. **Igualdad verificada antes de cambiar de dueño.** Un comparador por subsistema manda las mismas peticiones a
   Python y a Rust, con `HOME` y carpetas temporales, y compara las respuestas. Las diferencias se corrigen o se
   aceptan por escrito.
4. **Los textos que ve el modelo, idénticos.** Las 94 lecturas guardadas del motor MoE dependen del texto exacto del
   prefijo (Regla 1: `SISTEMA_LECTOR`, `HERRAMIENTAS_UNIDAD`, `mensajes`, `tarjeta_global`, `llave`, `huella`). El
   chat portado tiene que armar los mismos prompts carácter por carácter, como se hizo con el banco.
5. **Tests aislados.** Nada de la configuración real, `~/.prig_bancos`, `Prig/.prig_dataset` ni el Ollama del usuario.
   Las pruebas de esfuerzo calculan su tamaño antes de armarse y corren con `ulimit -v`.
6. **Los módulos que el usuario tiene en curso se portan al final, o cuando los congele**: `llm_director.py`,
   `motor_aprendizaje_nodos.py`, `descargas_modelos.py`, `descargas_hf_completo.py` y `motor_aprendizaje_grafo.js`.
7. **Cada fase deja Prig funcionando**, con la suite de Python y la de Rust en verde.

### 4.1 Por qué el crate va primero dentro de Python (decisión de F0)

El gobernador térmico está dentro del ciclo de generación: el chat llama `debe_cortar(tramo)` en cada trozo de la
respuesta, y `empezar_tramo`, `enfriar`, `descansar` y `terminar_tramo` en cada respuesta; el modo frío pausa los
procesos del motor que lanza Python. Con el subsistema en el proceso del servidor de Rust y el chat en Python, cada
trozo sería una petición HTTP entre procesos, y habría dos dueños posibles del mismo estado. Con PyO3, la misma
instancia en Rust vive dentro del proceso que la usa: sin tráfico entre procesos ni estado duplicado (lo que se
validó con el banco: 10× más rápido e idéntico). El servidor de Rust no atiende las rutas de un subsistema hasta que
su anfitrión también pasa a Rust.

## 5. Fases

| Fase | Contenido | Verificación | Criterio para seguir | Sesiones |
|---|---|---|---|---|
| F0 | Base: crates por subsistema, la API interna y `backend/nativo_rust.py`, el comparador de rutas, y **una prueba de la interfaz en WebKitGTK** (la ventana de `wry` en Linux no es Chromium como QtWebEngine) | la interfaz completa abre en `wry`; el comparador corre | decisión de la ventana (sección 7) | 1–2 |
| F1 | Recursos y térmico: sensores (hwmon, NVML), gobernador, modo frío (pausador sin GIL), modo suave, energía, calculadora, calibración, fichas GGUF, visualizador de audio | mismas respuestas que Python con sensores simulados; desvío del pausador < 0,5 ms con carga | el chat de Python usa el gobernador de Rust por la API interna | 4–6 |
| F2 | Plataforma: configuración, banderas, perfiles, archivos (con el aviso al director por la API interna mientras siga en Python), IDE, explorador, ejecución y kernel de cuadernos (con Python como herramienta), inicio | comparador de rutas; tests de `file_manager`, `ide_servicios` y `runner` portados | mismas respuestas; ninguna escritura fuera del espacio de trabajo | 3–4 |
| F3 | Modelos y descargas: Ollama (gestión y opciones), buscador de modelos, descargas de Hugging Face y Ollama con reanudación | descargas reales en una carpeta temporal | descarga y reanuda igual; **coordinar** con el trabajo en curso en `descargas_*` | 2 |
| F4 | Motor de IA: clientes de Ollama y Gemini, motor MoE (ciclo de `llama-server`, traducción, listas calientes, estados de proyectos), contexto, búsqueda web, herramientas, consola `P` (el aislamiento en Python queda como herramienta), lectura por unidades, fichas, examen, y el chat (`_chat_eventos`: banco, modo unidad, ronda de herramientas, empujón, verificación) | **prompts idénticos** (por carácter) en el banco de preguntas del estudio; mismas lecturas guardadas vigentes; examen del proyecto con el motor MoE ≥ el de Python | 0 diferencias de prompt; examen igual o mejor | 8–12 |
| F5 | Biblioteca, conocimiento y PDF: libros, librerías, papers, ingesta (extracción de PDF, troceado, índices), búsqueda, exportar PDF, sondeo, referencias, packs | texto extraído comparado sobre la biblioteca del usuario (calidad, no solo velocidad); PDF exportados comparados a ojo | extracción igual o mejor; velocidad medida | 8–10 |
| F6 | Aprendizaje y desafíos: catálogo, tutor, ejecución de tests (con Python como herramienta), ejercicios, guiado, plan de estudios, progreso, telemetría, evals; **el grafo de aprendizaje al final** | comparador de rutas con `~/.prig_desafios` copiado (nunca el original) | mismas respuestas | 5–7 |
| F7 | Integraciones: GitHub, Kaggle, YouTube (búsqueda y transcripciones), Prig Hub (git) | contra los servicios reales, solo lectura | mismas respuestas | 5–7 |
| F8 | Agentes y director (cuando el usuario congele `llm_director.py`) | comparador de rutas y flujos con un modelo falso | mismas decisiones con las mismas entradas | 3–5 |
| F9 | Ventana: `tao` + `wry` (o Tauri) en lugar de pywebview/Qt; un binario dueño de todo (servidor, `llama-server`, Python herramienta) | la interfaz completa en la ventana nueva; descargas, portapapeles, enlaces externos, micrófono | lo que hacía `_blindar_qt` funciona igual | 2–3 |
| F10 | Retirar el backend de Python: se quitan `backend/` (salvo el aislamiento de la consola y los ayudantes de ejecución), el proxy y uvicorn | las suites de Rust en verde; una sesión real completa | Prig arranca sin el backend de Python | 1–2 |

Total: 42–60 sesiones. Orden pensado para que cada fase sirva sola: F1 ya da el modo frío preciso y quita sensores de
Python; F2 + F3 dejan en Rust todo lo que es archivo y descarga; F4 es la más grande y la más delicada.

## 6. Riesgos

| Riesgo | Cuidado |
|---|---|
| Que el chat portado cambie una coma de un prompt e invalide las 94 lecturas guardadas | comparador de prompts por carácter (como el banco); no se cambia de dueño con diferencias |
| WebKitGTK (la ventana de `wry` en Linux) no hace todo lo que hace QtWebEngine (Chromium) | se prueba en F0, antes de comprometerse; alternativa: CEF, o seguir con la ventana actual hasta el final |
| Extraer texto de PDF en Rust da peor calidad que pypdf | se compara sobre la biblioteca real; pdfium si hace falta |
| Generar PDF sin reportlab | imprimir desde la ventana (HTML → PDF) o `typst`; se decide en F5 |
| Que dos procesos escriban el mismo archivo en la transición | un escritor por archivo (regla 2) |
| Trabajo en curso del usuario en los mismos módulos | regla 6; se coordina antes de cada fase |
| Fases largas sin poder usar Prig | regla 7: cada fase deja Prig funcionando |

## 7. Decisiones que tiene que tomar el usuario

1. **La ventana.** Recomendado: `tao` + `wry`, si la prueba de F0 con WebKitGTK sale bien. Si no, seguir con la
   ventana actual hasta F9 y evaluar CEF.
2. **Python como intérprete externo.** Recomendado: sí. Ejecutar archivos `.py`, cuadernos, tests de desafíos y la
   consola `P` (el modelo escribe Python) necesita un intérprete. No es el backend: es una herramienta, como `node`.
3. **La interfaz se queda en HTML/JS.** Recomendado: sí. Reescribirla en Rust (Leptos, Dioxus) es otro proyecto del
   tamaño de este, y la interfaz no es lo lento. Lo pesado ya va a WASM.
4. **Cuándo se congelan los módulos en curso**: director, grafo de aprendizaje y descargas.

## 8. Bitácora

| Fecha | Fase | Estado | Notas |
|---|---|---|---|
| 13/10 | — | decisiones | Las cuatro decisiones de la sección 7 se toman como se recomiendan (el usuario: «empieza»). |
| 13/10 | F0 | hecha salvo el comparador de rutas | **Prueba de WebKitGTK** (`herramientas/prueba_webkitgtk.py`, WebKitGTK 2.52.6, el motor de `wry` en Linux, en una ventana fuera de pantalla): la interfaz carga y se dibuja, el motor gráfico WASM arranca y están todas las funciones que usa el frontend (OffscreenCanvas, WebAssembly, Worker, WebSocket, ResizeObserver, portapapeles, `:has`, `container`, `backdrop-filter`). Tres errores de JavaScript en el editor (`global_config.js:4184`, `ide.js:564`, `editor_razonamiento.js:320`), restos de Monaco; se arreglan en F9. Para compilar `wry` hacen falta los paquetes `-dev` de WebKitGTK (con root, en F9). **Transición**: cada subsistema se porta como crate y, mientras su anfitrión siga en Python, se usa desde Python con PyO3 (sección 4.1): módulo `prig_nativo` (`backend-rust/crates/prig-nativo-py`), cargador `backend/nativo_rust.py` con número de interfaz, compilación con `herramientas/compilar_nativo.sh`. Pendiente: el comparador de rutas (se hace con F2, que es donde se cambian rutas de dueño). |
| 13/10 | F1, tanda 1 | hecha | **Modo frío en Rust** (`crates/prig-recursos`, `frio.rs`): `Proceso` (pidfd), `Pausador` (hilo propio, plazos absolutos con `Condvar`), `tiempo_cpu`, `turbo_apagado`, `fraccion_objetivo`, `motores_de_prig` (lee `/proc`, sin psutil). `backend/recursos/frio.py` delega en él con la misma API; `ControladorFrio` sigue en Python (tanda posterior). Medido sobre un proceso real que anota sus propios huecos, fracción 0,12 (6 ms de 50): pausador de Python 6,11 ms en reposo y **11,19 ms con otro hilo de Python ocupado** (ciclo de 60,5 ms: el motor trabajaba el 18,5 % y no el 12 %); pausador de Rust **5,96 ms en reposo y 5,93 ms con carga**, ciclo de 50,00 ms. Encontrado de paso: `Proceso(pid).tiempo_cpu()` de Python abría un pidfd en cada llamada y no lo cerraba (300 llamadas → 300 descriptores; el controlador la llamaba cada segundo por motor en RAM sin pausas, ~86 000 al día); en Rust se cierra al soltarlo (300 → 0). `compilar.sh` del motor MoE y `termostato.py` usan ahora el Python del `.venv` (el del sistema no tiene `prig_nativo`). Suite de Python: 1054 en verde; `~/.prig_config.json` intacto. |
| 13/10 | F1, tanda 2 | hecha | **Sensores en Rust** (`crates/prig-recursos`, `sensores.rs` y `nvml.rs`): hwmon leído como psutil 7.2.2 (mismo orden y mismos casos raros), NVML con `dlopen` (sin dependencias nuevas), nvidia-smi sin NVML (plazo de 3 s) y la clasificación de `leer_sensores`. `termico._nvidia/_temperaturas/_ventiladores/leer_sensores` y `nvml.py` delegan en él; psutil ya no lee sensores. `INTERFAZ` 2. Verificado contra psutil + ctypes en esta máquina, 3 veces: 0 diferencias (chips, etiquetas, umbrales, NVML, componentes, ventiladores); 9 pruebas de Rust (con un /sys de mentira); suite de Python 1054 en verde; backend aislado: `/api/recursos/temperaturas`, `/api/system/stats`, `/api/recursos/frio` y `/api/system/health` responden 200 con los datos de Rust. Encontrado: (1) la función pública de psutil completa un umbral con el otro (`crítico = alto` si falta): por eso el NVMe tiene «crítico 65261,85» sin archivo `_crit`; replicado. (2) Sin hwmon, psutil lee `/sys/class/thermal` y divide los umbrales por 1000 en cada vuelta de un conjunto (resultado distinto en cada ejecución); en Rust, una vez. (3) Velocidad: `leer_sensores` pasa de 17 a 15 ms (CPU: 6,4 → 4,3 ms). Lo caro está en el núcleo y el firmware, no en Python: el NVMe tarda ~3 ms por temperatura (pregunta al disco), los ventiladores de HP ~1,1 ms (ACPI), acpitz 0,8; NVML 0,2 ms. **Oportunidades para la tanda 3** (cambian el comportamiento, se deciden aparte): el controlador del modo frío lee todos los sensores cada ~1,5 s para quedarse con la CPU (coretemp sola: < 0,04 ms y no despierta al disco ni a ACPI); los umbrales (`_max`, `_crit`) cuestan 3 ms por lectura y no cambian. |
| 13/10 | F1, tanda 3 | hecha | **Cálculo puro en Rust**: `gguf.rs` (cabecera GGUF, también por rangos con la función de Python que pide los bytes), `perfiles.rs` (la tabla vive en Rust; `PERFILES` de Python sale de ahí), `ficha.rs` (ficha desde los metadatos, caché KV, ficha del catálogo, registro de cada nombre; pedir los datos a Ollama y al registro sigue en Python hasta la tanda 7) y `calculadora.rs` (`Maquina`, `estimar`, `recomendar`, `elegir_modelo`…). Los diccionarios viajan como `Valor` propio (orden de claves de Python; no se activa `preserve_order` de serde_json, que cambiaría el orden en todo el espacio de trabajo, `banco-core` incluido). Operaciones de Python portadas a mano y comprobadas: `round` (empates al par sobre el valor exacto), `repr` de float dentro de los textos (`1e+16`, `1.5e-05`, `5.0`), `int()`, `float()`, `str()`, `max`/`sorted` estables, comparación de tuplas. `prig_nativo` pasa a un submódulo por subsistema (`INTERFAZ` 3). **Verificación**: `herramientas/diferencial_recursos/calculo.py` extrae `backend/recursos` del commit `9d9bb98` (Python puro) y compara con lo de ahora sobre entradas al azar: 168 000 casos con 5 semillas, 0 diferencias (todos los veredictos, errores KeyError/ValueError/FaltanBytes, cabeceras GGUF truncadas y rotas, textos de `motivo` y `ganancia`); suite de Python 1054 en verde. |
| 13/10 | F1, tanda 4 | hecha | **Almacén en Rust** (`almacen.rs` + `json.rs`): el JSON de `~/.prig_recursos.json` (calibración por huella, pruebas, aplicado/restaurar, térmico, frío, ritmo, eventos) con la misma semántica método a método, incluidas las rarezas (sin huella se trabaja sobre un `{}` suelto que no se guarda; `eventos(0)` devuelve todos, como `lista[-0:]`; poda estable por fecha). `json.rs` lee lo que acepta `json.load` (también `NaN`/`Infinity`, claves repetidas como un dict) y escribe byte a byte lo de `json.dump(ensure_ascii=False, indent=1)`; el temporal se crea con `mkstemp` (0600) y se renombra. Verificado: el archivo real (72 KB) se reescribe idéntico; 12 000 JSON al azar (escribir y leer, rotos incluidos) iguales a Python; secuencias de hasta 40 operaciones al azar sobre el almacén viejo y el nuevo (archivos rotos y de otra versión incluidos): mismos resultados, mismos bytes en disco, mismos permisos, mismos `.roto-*`. Encontrado al comparar: con huella `None` el puente la pasaba como `""`; ahora va tal cual. Suite 1054 en verde. |
| 13/10 | F1, tanda 5 | hecha | **Modo suave, motor suave y energía en Rust** (`ritmo.rs`, `motor_suave.rs`, `energia.rs`, `http.rs`). Patrón para lo que tiene «mundo»: el núcleo en Rust es un objeto pasivo con el estado y las decisiones; lo de fuera (reloj, monitor, Ollama, procesos) entra por un rasgo que en esta transición implementa la fachada de Python leyendo sus atributos en el momento (así `mock.patch` sigue valiendo), y en F4 lo implementará Rust. Los bucles que llaman a Python siguen siendo hilos de Python (un hilo de Rust que llama a Python puede abortar el intérprete al cerrarse). El reloj se lee exactamente donde lo leía Python: hay pruebas que sustituyen `time.time` por una lista de valores y cuentan las lecturas. `Ritmo` es una clase de Rust que Python hereda; `FijadorCPU` decide en Rust y toca el sistema con `/proc` y `sched_setaffinity` (las pruebas le dan un sistema falso en vez de simular psutil y `os`: mismas aserciones, y una nueva para procesos de otro usuario); Ollama por `reqwest` bloqueante. `motor_suave`: compilar, envoltorio (con `shlex.quote` portado), control y el controlador. `energia`: estado, ayudante por pkexec, ErrorEnergia. **Verificado** contra `9d9bb98`: 1000 secuencias de `Ritmo` y 1000 del fijador (mismos resultados, mismas lecturas de reloj, mismos núcleos fijados); el envoltorio byte a byte con rutas con espacios, comillas, «ñ», `$` y `;`; secuencias del controlador (mismo archivo de control, mismas lecturas de reloj); `energia.estado()` sobre /sys falsos al azar. Las pruebas que compilan la biblioteca C de verdad y corren el ayudante de root sobre un /sys falso pasan. Suite 1055 en verde. |
| 13/10 | F1, tanda 6 | hecha | **Gobernador, monitor y controlador del modo frío en Rust** (`termico.rs`, `frio.rs`). El gobernador (decidir el corte, enfriar con meseta, aprender salto, margen y reposo, viabilidad, avisos) es un núcleo con su estado; Python le da el mundo (monitor, ritmo, fijador, motor suave, MoE, reloj, `cancelar.wait`, avisos) y `g.ajustes` es un diccionario vivo sobre el estado de Rust (las pruebas lo cambian con `[]=` y `update`). Nunca se tiene el cerrojo de Rust mientras se llama a Python (una llamada que suelta el GIL podría bloquearlo todo): las operaciones devuelven «lo que hay que guardar» y se guarda fuera; `enfriar` publica y quita la pausa en el estado compartido (se ve en el panel mientras dura) y aprende el reposo con un cerrojo breve; `terminar_tramo` lee primero el reloj con las condiciones de Python y aprende después. `Tramo` es una clase de Rust que Python hereda (para darle la hora). El monitor guarda en Rust la última lectura y el historial; con el lector de siempre lee los sensores en Rust sin el GIL. **Cambio decidido** (la oportunidad de la tanda 2): el modo frío lee solo la CPU (`temp_cpu_rapida`: mismo valor que `temp_cpu(leer_sensores())` en 20 de 20 lecturas alternas, **0,38 ms en vez de 15 ms**, sin despertar al NVMe ni a ACPI). **Verificado** contra `9d9bb98`, con reloj controlado y monitores guionizados: 450 secuencias del gobernador (resultados, eventos, ajustes, pausa, aviso, almacén en disco y número de lecturas del reloj), 450 del controlador del modo frío y 450 del monitor, 0 diferencias. Encontrado: con temperaturas enteras Python guarda `salto_c` entero (`round(18, 1)` es `18`); se respeta (en producción las temperaturas son siempre float). Backend aislado: `/api/recursos/temperaturas`, `/ritmo`, `/frio`, `POST /termico` (límite, 400 fuera de rango, olvidar) y `/eventos` responden bien. Suite 1055 en verde. |
| 13/10 | F1, tanda 7 | hecha | **Detector, servidor, calibración, gestor y fichas por red en Rust** (`detector.rs`, `servidor.rs`, `calibracion.rs`, `gestor.rs`, red de `ficha.rs`). *Detector*: nvidia-smi, rocm-smi, CPU, memoria, batería y disco con las reglas de psutil (`core_cpus_list`, `MemAvailable`, `sysinfo`, `energy_now/full` y hasta los casos en que psutil fallaba y se pasaba al tipo de chasis), Ollama (versión, pid, dueño, entorno, ejecutores) y la **huella idéntica** (sha256): comprobada en esta máquina y en 3000 entradas al azar; el banco de memoria da lo mismo (medianas 12,3 y 12,5 GB/s), así que el factor calibrado de la calculadora sigue valiendo. *Servidor*: validar, estado, instrucciones, registro (journalctl o archivo, `splitlines` de Python) y parar Ollama; `aplicar` y `reiniciar_servidor` quedan en la fachada (llaman al motor de Python). *Calibración*: canario (con el JSON cortado y la expresión de las citas portada a mano), OOM, reducir, deducir, combinar (mediana), elegir modelos, GPU por nvidia-smi, generación en streaming sin el GIL (solo lo coge para preguntar si hay que parar) y la prueba completa con su mundo (`_MundoPrueba`); el hilo que mide la GPU y el encadenado de calibrar quedan en Python. *Gestor*: medidas, estado en vivo con avisos y la recomendación ajustada por lo probado; cachés y encadenado en la fachada hasta F4. *Fichas*: instalados, `/api/show`, registro por rangos con la caché por digest y `obtener`. **Verificado** contra `9d9bb98`: servidor 1500 casos, calibración 4 semillas (24 000 casos de funciones puras y 1600 pruebas completas guionizadas: OOM, calor, enfriar, cancelar), gestor 1800 casos, todo 0 diferencias; contra servicios reales: 3 modelos del registro (Ollama y Hugging Face) con la caché idéntica byte a byte, los 5 modelos del Ollama local y sus fichas. **Desvíos decididos**: `validar` ya no acepta cifras no ASCII (`OLLAMA_NUM_PARALLEL=٣` pasaba en Python y Ollama no lo entiende); los textos de los errores de red son los de reqwest, no los de urllib. Una prueba miraba el código fuente de `calibracion.probar`; ahora comprueba el comportamiento (el error del motor sale explicado). Suite 1055 en verde. |
| 13/10 | F1, tanda 8 | hecha | **Monitor de audio en Rust** (`audio.rs`): pactl (aplicaciones que suenan) y la captura con parec y la FFT en un hilo de Rust que no toca Python. Las cuentas, idénticas a las de Python: la FFT recursiva en el mismo orden con los giros calculados como `math.e ** complex` (el `_Py_c_pow` de CPython), la suma compensada de `sum()` de Python 3.12 (Neumaier) y el redondeo; comprobado bit a bit en 1500 trozos (silencio, amplitud máxima, tonos, ruido) y el listado con un pactl falso. Medido con parec de verdad: **CPU del monitor 8,0 % → 0,8 % de un núcleo**, y un hilo de Python haciendo cuentas pasa del 90 % al 98 % de su velocidad mientras suena (ya no compite por el GIL). **Encontrado**: en Python, quitar el último suscriptor se bloqueaba para siempre (`decrementar_suscriptor` tomaba un `threading.Lock` no reentrante y `_detener_captura` lo volvía a pedir); como lo llama el WebSocket del audio desde el bucle asíncrono, **al cerrar el efecto de audio se congelaba todo el backend**. En Rust no pasa. También: si parec moría, Python esperaba sin fin a un tubo vacío; ahora se vuelve a lanzar. Cada hilo de captura tiene su generación y su parec (si alguien se va y vuelve enseguida, el viejo no toca el nuevo). |
| 13/10 | **F1** | **hecha** | Todo `backend/recursos/` y `audio_monitor.py` tienen su lógica y su estado en Rust (`crates/prig-recursos`, 40 pruebas; módulo `prig_nativo`, `INTERFAZ` 13) y los módulos de Python son fachadas con la misma API. Queda en Python, a propósito, solo lo que está atado a su anfitrión (el motor de IA y las rutas) y se irá con él en F4: los hilos que llaman a Python (controladores, monitor, muestreador de la calibración), `servidor.aplicar`/`reiniciar_servidor` (arrancan Ollama con el motor), el encadenado de `calibrar` y `probar_recomendacion`, y las cachés de `Gestor`. **Criterio de F1 cumplido**: el chat de Python usa el gobernador de Rust (empezar, cortar, enfriar y aprender) y el pausador va sin el GIL (desvío 5,9 ms sobre 6 ms con Python ocupado, antes 11,2). **Mejoras medidas**: tramo del modo frío exacto con Python ocupado; lectura de la CPU para el modo frío 15 → 0,38 ms; monitor de audio 8 → 0,8 % de CPU. **Fallos de Python encontrados y corregidos**: el pidfd que se perdía cada segundo, el bloqueo del backend al cerrar el audio, el parec muerto que no se relanzaba. **Desvíos decididos**: cifras no ASCII en `validar`, textos de errores de red de reqwest, el modo frío lee solo la CPU. **Para volver a comprobarlo**: `herramientas/diferencial_recursos/todo.sh [semilla]` (diferenciales contra el commit `9d9bb98`, todos en verde con semillas nuevas). Suite de Python 1055 y de Rust 85, en verde. |
