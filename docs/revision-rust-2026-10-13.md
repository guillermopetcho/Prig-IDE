# Revisión del código en Rust (13/10/2026)

**Alcance**: `backend-rust/` (servidor Axum `prig-server`, `prig-fs`, `prig-runner`, `prig-integrations`,
`prig-hardware` y la copia de `banco-core`), `prig-graficos/` (núcleo, WASM y motor ASCII), la integración
(`run.sh`, `main.py`) y el frontend que los usa (`motor_grafico_fachada.js`, `worker_motor_grafico.js`).
**Para**: el usuario y quien corrija cada punto en otra sesión.

**Cómo se revisó**:

- Compilación, tests y clippy de los dos workspaces, y la suite de Python.
- Lectura de cada ruta del servidor, comparada con su versión en Python.
- Un cruce automático de las 337 rutas de Python contra las 110 de Rust.
- Reproducción del hueco de rutas en una carpeta temporal.
- Pruebas sobre el servidor en marcha, solo con peticiones sin efectos: el 405 se rechaza antes de ejecutar nada y la
  consulta de CORS es de solo lectura.
- El registro real `/tmp/prig_rust_server.log`.
- Una réplica aislada del servidor (`HOME` temporal y carpeta propia) cargada en un navegador sin ventana.

**Lo que está bien**:

- Tests: Rust 45 + 9 en verde; Python 1054 en verde.
- La copia de `banco-core` tiene el mismo código que `~/prig-memoria`, con los arreglos del 11/10.
- El WASM publicado es idéntico byte a byte al que sale del código actual.
- En una carga real, el motor gráfico arranca en Rust (`modo: wasm`) y no hay excepciones de JavaScript.
- `prig-fs` rechaza `../x` y las rutas absolutas de fuera.
- Abrir el banco con otro nombre de modelo de vectores no borra los vectores.

## Causa de fondo

El servidor en Rust ocupa el puerto 8000 y reimplementa o **sustituye con respuestas fijas** 121 combinaciones de ruta y método de Python. Pero
el estado vive en el proceso de Python (8001): la carpeta de trabajo, la configuración de IA cargada, el motor MoE, el
modo frío, el vigilante del banco, las descargas y el director. Cada ruta que Rust responde por su cuenta deja a los
dos procesos con estados distintos, o le muestra al usuario datos que no son los reales.

Regla sugerida:

- **Rust** atiende solo lo que es suyo y no tiene estado compartido: archivos, árbol, búsqueda, estáticos y lecturas
  del banco.
- **Todo lo demás va a Python** por el proxy, incluidos los métodos que Rust no tiene en una ruta compartida y los
  WebSockets.

## Críticos: seguridad

| # | Dónde | Qué pasa | Evidencia |
|---|---|---|---|
| S1 | `prig-server/src/lib.rs:61` | CORS `allow_origin(Any)`. Python lo limitaba a `127.0.0.1/localhost:8000/8080` a propósito («permitiría que cualquier web visitada por el usuario leyera y escribiera sus archivos»). Con Rust, cualquier página abierta en el navegador puede usar `/api/file`, `/api/run`, `/api/banco` y `/api/ide/*` | En vivo: `OPTIONS /api/file` con `Origin: https://sitio-malicioso.example` responde `access-control-allow-origin: *` |
| S2 | `prig-fs/src/lib.rs:115` (`resolve`) | Si un componente de la ruta no existe, no se normaliza: `zz/../../x` pasa el control (`starts_with` compara componentes), y `write_file`/`create_item` crean `zz` y escriben **fuera** del espacio de trabajo. Afecta también al destino de `ide_renombrar`. Python normaliza con `os.path.abspath` | Reproducido en carpeta temporal: `write_file("zz/../../fuera_write.txt")` y `create_item("yy/../../fuera_carpeta")` quedaron fuera |
| S3 | `prig-runner/src/lib.rs:66` | `/api/run` ejecuta cualquier archivo del disco (no pasa por `FileManager`). Solo con S1, una web puede escribir un script dentro del espacio de trabajo (`POST /api/file`) y ejecutarlo (`POST /api/run`): ejecución remota de código. Python tampoco limitaba la ruta, pero su CORS lo impedía desde otra web | Lectura del código |
| S4 | `routes/ai.rs:546` | La clave de Gemini se guarda con `fs::write`, con permisos por defecto. Python la escribe con `0600` de forma atómica (`gemini_motor.py:134`) | Lectura del código; el archivo actual está en 600 porque lo escribió Python |

## Críticos: funcionalidad

| # | Dónde | Qué pasa |
|---|---|---|
| F1 | `routes/ai.rs:129` | `/api/ai/chat` reenvía el cuerpo de Prig (`prompt`, `hooked_files`, `banco`…) tal cual al `/api/chat` de Ollama, que espera `messages`: el chat de Prig no funciona por el 8000. El modelo MoE da error, porque no es de Ollama, y se pierden el banco, las herramientas, el gobernador térmico y «Solo código» |
| F2 | `routes/config.rs:371`, `workspace.rs:36` | La configuración de IA se lee y se guarda en `~/.prig_config.json`, el de los espacios de trabajo. La de Python es `~/.prig_ai_config.json`. **En vivo**, `/api/ai/config` muestra `qwen2.5-coder:7b` y `num_ctx` 8192, mezclados con `last_workspace`, en lugar de tu Qwen3.6 MoE, `num_ctx` 4096 y los 12 ajustes `moe_*` y `banco_*`. Afecta a `/ai/config`, `/recursos/moe`, el autocompletado (usa 7b en lugar de tu 1.5b y carga otro modelo en la VRAM) y `Prig//` |
| F3 | `routes/workspace.rs:157` | Abrir carpeta cambia solo el `FileManager` de Rust. Python no se entera (su `open_workspace` llama a `rebind_workspace`), así que el chat, el banco, los repositorios y el runner de Python siguen en la carpeta anterior |
| F4 | router `lib.rs` | Axum responde **405** cuando la ruta existe en Rust con otro método, y no la pasa al proxy. Rotas: `POST /api/descargas`, `POST /api/flags`, `POST /api/modelos/config`, `POST /api/modelos/embeddings`, `DELETE /api/modelos/parciales`, `POST /api/progreso/analisis`, `POST /api/recursos/servidor`. En vivo: 405 en las cuatro probadas |
| F5 | `routes/proxy.rs:14` | El proxy quita `upgrade`/`connection` y usa `reqwest`: el WebSocket `/ws/audio_reactivo` no puede pasar |
| F6 | varias | Sustitutos que devuelven datos fijos o no guardan (tabla siguiente) |
| F7 | `routes/ai.rs:66` | `"propios": []` y `capacidades: ["completion"]` fijas: el motor MoE (`qwen3.6-35b-moe:prig`) desaparece de los selectores (Python lo agrega con `_modelos_propios`) |
| F8 | `prig-runner/src/lib.rs` | Usa el `python3` del sistema, no el del `.venv` (Python usa `sys.executable`), así que fallan los scripts que importan paquetes del `.venv`. Además: sin grupo de procesos (cancelar y el tiempo límite dejan vivos a los hijos; Python usa `start_new_session`); `cancelled` siempre `false`; ignora `exec_timeout` de la configuración; la salida se junta entera en memoria, sin tope |
| F9 | `prig-integrations/src/lib.rs:91` | Tiempo límite **total** de 120 s en el cliente de Ollama, usado también para el chat en streaming y para `pull`: corta las respuestas largas y las descargas de modelos grandes |
| F10 | `run.sh:24`, `main.py:409` | Nadie cierra el servidor en Rust al salir de Prig (vivo 45 min sin Prig abierto). Nadie vigila al respaldo de Python: en el registro real hubo 26 minutos de 502 (10:42–11:08), con 60 peticiones fallidas (transcripciones de YouTube, director, KB, GitHub, Kaggle, Hub). La ventana se abre a los ~4 s aunque Python no responda. El binario de release es anterior a los últimos cambios de `ai.rs` e `inicio.rs` (08:03 contra 08:04) |
| F11 | `routes/system.rs:14` | `/system/stats` lanza `nvidia-smi` en cada consulta (la barra consulta cada 3 s). Python lo había pasado a NVML porque eso calentaba la CPU. El `cpu_pct` es la carga media, no un porcentaje |
| F12 | `state.rs` | `OllamaClient::new(None)`: la URL de Ollama queda fija en `127.0.0.1:11434` e ignora la configurada |

**Sustitutos de F6** (Rust responde en lugar de Python):

| Ruta | Lo que hace Rust |
|---|---|
| `/recursos/frio`, `/recursos/ritmo` (GET/POST) | el POST responde como si guardara y no guarda nada: la protección térmica no se puede configurar. El GET dice «inactivo» |
| `/recursos/moe` | siempre «no disponible»; guarda los ajustes donde Python no los lee; núcleo por defecto `q4` (el tuyo es `q8`) |
| `/recursos/maquina`, `/temperaturas`, `/modelos` | sin GPU, ancho de banda inventado (25,6), velocidades fijas (24/12 tok/s) en lugar de la calculadora calibrada |
| `/banco` (GET), `/banco/ajustes` | vigilante, análisis y presupuestos fijos; los ajustes no se guardan; `activar` sincroniza una vez y no arranca el vigilante |
| `/aprendizaje/grafo`, `/aprendizaje/estadisticas` | vacíos (es el `motor_aprendizaje_nodos` en curso) |
| `/learning/metrics`, `/progreso/resumen`, `/inicio` | ceros; sin conceptos, racha ni rutas; Kaggle siempre desconectado; sin GPU |
| `/descargas` (GET), `/modelos/*` | listas vacías y plantillas fijas |
| `/llm/director_decision`, `/llm/limpiar_memoria_cerebro` | texto fijo («Sistema nominal en Rust nativo»); dice que limpia y no limpia |
| `/ai/cancel` | no cancela nada: las generaciones de Python siguen ocupando la GPU |
| `/ai/ollama/version-info` | nunca hay actualizaciones |

## Medios

| # | Dónde | Qué pasa |
|---|---|---|
| M1 | `routes/ide.rs:671` | `ide/problemas`: Ruff sin versión fija (acepta sintaxis posterior a 3.12), otros mensajes, sin el aviso de tabuladores y espacios, y **sin la protección de pila** del banco: un código muy anidado en el editor puede tirar el servidor entero (pilas de Tokio de 2 MiB, `panic = "abort"`). Usar `banco_core::pyast::cota_de_profundidad` + `con_pila` |
| M2 | handlers en general | E/S y SQLite bloqueantes dentro de handlers `async` (sincronizar el banco, buscar en 20.000 archivos, copiar carpetas) sin `spawn_blocking`: ocupan hilos de Tokio por los que también pasa el streaming del proxy |
| M3 | `routes/ide.rs:396` | Reemplazar escribe un temporal y lo renombra: el archivo pierde sus permisos (un script ejecutable deja de serlo). Con regex, la sintaxis de reemplazo es la de Rust (`$1`), no la de Python (`\1`) |
| M4 | `routes/ide.rs:1079` | `explorador_buscar` sigue enlaces simbólicos (Python usa `os.walk`, que no): con un enlace a `/` y sin coincidencias, recorre el disco entero |
| M5 | `routes/ide.rs:1165` | `folder/code-files` acepta cualquier carpeta (`/`, `/etc`) y lee cada archivo entero. Python tampoco limita, pero su CORS impedía usarlo desde otra web |
| M6 | `routes/banco.rs:488` | Borrar el banco elimina los archivos aunque el proceso de Python los tenga abiertos. Además, el banco se abre de nuevo en cada petición y las búsquedas van sin vectores |
| M7 | `backend-rust/crates/banco-core` | Segunda copia del motor del banco (idéntica hoy, con SQLite incluido): hay que mantenerla sincronizada a mano con `~/prig-memoria` |
| M8 | `routes/proxy.rs` | `headers_mut.insert` colapsa las cabeceras repetidas de la respuesta (`set-cookie`); habría que usar `append` |

## Bajos: motor gráfico

| # | Dónde | Qué pasa |
|---|---|---|
| G1 | `frontend/js/motor_grafico_fachada.js:206` | Toma `memory.buffer` *antes* de `update_particles`. Si la memoria de WASM crece, el búfer viejo queda inválido y ese cuadro lanza una excepción (el bucle sigue). El worker lo hace bien |
| G2 | `motor_grafico_fachada.js:70` | El mensaje `OFFSCREEN_ERROR` del worker no se atiende: quedaría «cargando» para siempre, con el lienzo ya transferido. Hoy es código muerto: `motor_movimiento.js:173` llama `inicializar(null, …)` y siempre se usa el modo `wasm` en el hilo principal |
| G3 | `prig-render-core/src/particion_espacial.rs` (`resize`) | `cols`/`rows` solo se actualizan si cambia el total de celdas (10×6 a 6×10 no): faltan conexiones |
| G4 | `prig-render-wasm/src/lib.rs` (`drones_update`) | El color va como `f32` (24 bits de mantisa): el byte bajo se redondea |
| G5 | `atractores.rs:132,162,163`, `spring_physics.rs:37` | clippy: TAU escrito a mano (error del lint `approx_constant`) |
| G6 | `frontend/wasm/.gitignore` | El WASM no está en git: un clon nuevo cae al modo JS. `frontend/static/wasm/` es una copia que no usa nadie |

## Orden sugerido para corregir

1. **Seguridad**:
   - S1: CORS igual que en Python.
   - S2: normalizar la ruta de forma léxica antes de comprobarla.
   - S3: el runner, por `FileManager`.
   - S4: `0600`.
2. **Que Rust no tape a Python**:
   - quitar los sustitutos de F6 (que vayan al proxy);
   - dar un respaldo (`fallback`) de proxy por método en las rutas compartidas (F4);
   - pasar los WebSockets (F5).
3. **Estado único**:
   - el chat (F1), la configuración de IA (F2) y las listas de modelos (F7) los atiende Python;
   - abrir carpeta (F3) va a Python, o Rust se lo avisa.
4. **Procesos** (F10): uno solo es dueño de los dos servidores, los arranca y los cierra juntos, y no abre la ventana
   hasta que Python responde.
5. Los medios y el motor gráfico.

## Correcciones (13/10/2026)

Copia de lo que había antes: `~/.cache/prig-respaldos/2026-10-13-antes-de-corregir-rust.tar.gz` (las fuentes de
`backend-rust/` y `prig-graficos/` no están en git).

**El servidor en Rust ya no tapa a Python.** Atiende solo lo suyo, sin estado compartido:

- `/api/workspace`, que sigue a Python;
- `/api/tree`;
- `/api/ide/archivos` y `/api/ide/buscar`;
- las consultas del banco que no existen en Python (`/api/banco/simbolos`, `/ficha`, `/grafo`);
- `/api/health`, `/api/hardware` y `/api/system/hardware`;
- el índice y los estáticos.

Todo lo demás va a Python por el proxy. Se borraron los módulos `ai`, `config`, `inicio`, `hardware` y `runner` del
servidor, y las rutas de escritura de archivos.

| # | Estado | Cómo |
|---|---|---|
| S1 | corregido | CORS con los mismos orígenes que Python (`127.0.0.1`/`localhost` en 8000, 8080 y el puerto propio). Las cabeceras CORS que trae Python se descartan en el proxy (duplicadas, el navegador rechaza la respuesta). Test `test_cors_solo_origenes_locales` |
| S2 | corregido | `prig_fs::normalizar` (como `os.path.abspath`): las rutas se normalizan sobre el texto antes de comprobarlas, sin resolver enlaces (igual que Python). Test `test_no_escapa_por_componente_inexistente` |
| S3, S4 | corregido | `/api/run` y la clave de Gemini los atiende Python (proceso con `start_new_session`, clave con 0600) |
| F1, F2, F6, F7, F11, F12 | corregido | el chat, la configuración de IA, los recursos, el banco con su vigilante, el aprendizaje, el director, las descargas, `/system/stats` y las listas de modelos (con el motor MoE) son los de Python |
| F3 | corregido | Rust lee `last_workspace` de `~/.prig_config.json` cada vez que cambia (Python lo escribe al abrir una carpeta): las dos mitades trabajan sobre la misma carpeta. Test `test_workspace_sigue_a_python` |
| F4 | corregido | cada ruta propia tiene `.fallback(proxy)` por método: ningún 405 por métodos que tiene Python. Test `test_proxy_reenvia_lo_que_no_atiende_rust` (las siete rutas) |
| F5 | corregido | el proxy pasa WebSockets (puente con `tokio-tungstenite`). Test `test_websocket_pasa_a_python` |
| F8 | corregido | Python ejecuta el código. Además, en `prig-runner`: grupo de procesos propio (cancelar y el tiempo límite matan a los hijos), `cancelled` verdadero, salida con tope de 2 MB, intérprete de `PRIG_PYTHON` |
| F9 | corregido | el proxy no tiene tiempo límite total. `prig-integrations` lo pone solo en las consultas cortas |
| F10 | corregido | ver «Ciclo de vida» abajo |
| M1, M3, M4, M5, M6 | corregido | `ide/problemas` (CPython), reemplazar, renombrar y duplicar (conservan permisos y la sintaxis `\1` de Python), el explorador (`os.walk`, sin seguir enlaces), `folder/code-files` y el banco van a Python |
| M2 | corregido | lo que queda en Rust corre en `spawn_blocking` |
| M7 | mitigado | `herramientas/sincronizar_banco_core.sh` compara las dos copias (y con `--copiar` trae la de `~/prig-memoria`). Hoy son iguales |
| M8 | corregido | el proxy usa `append`: las cabeceras repetidas pasan todas |
| G1–G5 | corregido | búfer tomado después de actualizar; `OFFSCREEN_ERROR` y errores del worker atendidos (modo JS, `lienzoTransferido`); el worker avisa «listo» solo con el bucle en marcha (con `setTimeout` si no hay `requestAnimationFrame`); la grilla actualiza `cols`/`rows` siempre (test nuevo); el color de los drones viaja como bits (`f32::from_bits` + `Uint32Array`); `TAU` en lugar de constantes a mano (clippy: 0 errores) |
| G6 | corregido | `compilar_wasm.sh` ya no copia a `frontend/static/wasm` y borra el `.gitignore` que genera wasm-pack: `frontend/wasm/` entra en git. La carpeta `frontend/static/wasm/` quedó sin uso (se puede borrar) |

**Paridad de lo que atiende Rust con Python**:

- **Búsqueda del IDE:**
  - recorrido como `os.walk`: no entra en carpetas enlazadas y recorre todos los archivos, sin el tope de 20.000;
  - patrones como `fnmatch` (distingue mayúsculas en Linux);
  - expresiones con la sintaxis de `re` (vía `banco_core::re`);
  - palabra completa `(?<!\w)…(?!\w)` en lugar de `\b`;
  - `splitlines` de Python.
- **Árbol:** `"children": null` en los archivos.
- **`target`:** se ignora también en Python (`file_manager.py`, `ide_servicios.py`); las compilaciones de Rust tienen
  miles de archivos.
- **Alias:** `/api/file/raw` también existe en Python.
- **Diferencia que queda:** Rust salta los archivos especiales (FIFO); Python los abría y se quedaba esperando.

**Ciclo de vida** (`main.py` es el único dueño):

- Arranca Python en el primer puerto libre desde 8001 y Rust en el 8000, los dos con `PR_SET_PDEATHSIG`.
- Abre la ventana cuando Python responde.
- Vigila los dos y reinicia el que se caiga (hasta 5 veces por minuto).
- Al cerrar, apaga Rust y después Python, con hasta 20 s para su limpieza.
- Antes de arrancar, cierra los servidores de Prig huérfanos de sesiones viejas (padre `init`/`systemd`). Hoy cerró
  el pid 9819: binario borrado, sin Python detrás.
- Mientras Python arranca o se reinicia, el proxy hace esperar a las peticiones hasta 60 s en lugar de dar 502,
  también cuando la conexión del pool quedó cerrada.
- `run.sh` ya no lanza Rust por su cuenta. El registro de Rust va a `~/.prig_rust_server.log`.
- `PRIG_SIN_RUST=1` arranca solo Python.
- Corregido además en `main.py`: faltaba `global _fallback_proc`, y el Python de respaldo nunca se cerraba.

**Verificación**:

| Prueba | Resultado |
|---|---|
| Tests de Rust | `backend-rust` 45 (15 del servidor, reescritos con configuración, carpeta y bancos temporales y un «Python falso» local; los anteriores usaban la configuración real del usuario); `prig-graficos` 10 |
| Clippy | 0 errores en los dos workspaces |
| Suite de Python | 1054 en verde |
| Modo dual de punta a punta (`HOME` temporal, puertos 18000/18001) | arranque en 3,7 s; `POST /api/flags` 200 (antes 405); abrir carpeta por Python y Rust la sigue; Python muerto a la fuerza: el vigilante lo reinicia y la petición espera 2,3 s y responde 200; cierre en 0,2 s sin procesos sueltos; `main.py` con `SIGKILL`: los dos hijos mueren |
| Interfaz completa en un navegador sin ventana (copia de Prig) | motor gráfico en WASM; sin excepciones de JavaScript; la única petición fallida es `/api/modelos` (503 de Python porque Ollama apuntaba a un puerto cerrado). En la sesión real del 13/10 habían fallado 60 |

**Pendiente, fuera de estas correcciones**: si se quiere que el chat, el banco con su vigilante, el modo frío o el
motor MoE corran en Rust, hace falta portarlos enteros (como `plan-banco-rust.md`), no reimplementar sus endpoints.
