# Plan: el motor del banco de datos en Rust

**Para**: el usuario y quien implemente cada fase (también otro modelo, sin el contexto de la conversación en que se
diseñó). **Fecha**: 10/10/2026. **Estado**: hecho (11/10/2026): Prig usa solo el motor de Rust (sección 12); el de Python se retiró de Prig tras
una revisión completa (sección 13).

## 0. En una página

- **Qué se mueve**: todo lo que guarda, indexa y consulta el conocimiento del proyecto: leer y sincronizar los archivos,
  analizar el código (Python, otros lenguajes y Markdown), el grafo de llamadas, los hechos, los fragmentos y la
  búsqueda, el mapa y el paquete de contexto, la memoria (notas, resoluciones, cambios), la partición en unidades, las
  consultas de la consola (`P.*`) y los hechos de cada pregunta. Son unas 4.200 de las 5.300 líneas de
  `banco_proyecto.py`, `particion_proyecto.py`, `memoria_consulta.py` y `lectura_unidades.py`.
- **Qué queda en Python**: lo que habla con el modelo (análisis y resúmenes con IA, `P.llm`, la lectura de unidades), la
  consola aislada donde el modelo ejecuta Python (`Consola`, `revisar`, `P.cargar`), el gestor de bancos, los endpoints
  y los módulos que guardan sus propias tablas en el mismo archivo (`lecturas`, `fichas`, `examen`). Todo eso sigue
  igual: llama al motor por la misma interfaz.
- **Cómo**: una carpeta aparte, `~/prig-memoria/`, con el motor en Rust, que Prig importa como módulo de Python
  (`prig_banco`). Prig conserva sus clases y funciones con los mismos nombres, y un interruptor elige el motor (`python`
  o `rust`). Los dos conviven hasta que pase la prueba base; después, Python queda de respaldo. (Así fue hasta la
  revisión del 11/10: el interruptor y el motor de Python ya no están en Prig; sección 13.)
- **Pruebas**: cada fase cierra con una **prueba sencilla**, un comando (`./probar F3`) que compara Rust con Python sobre
  los mismos proyectos y corre los tests que ya existen de esa parte. Al final, la **prueba base** (sección 7): datos,
  unidades, consultas, los 1051 tests, el modelo y la velocidad; se corrige cada diferencia y se repite.
- **Costo**: 15–17 sesiones; ~10.000–12.000 líneas de Rust y ~3.000 de tests.
- **Ganancia, sin exagerar**: indexar Prig pasaría de ~10 s a ~1 s, y los hechos de una pregunta de ~0,2 s a ~0,02 s.
  Cada respuesta del modelo mejora apenas ~1 %, porque el tiempo está en el modelo (20–60 s). Lo que sí cambia:
  proyectos de 20–50 millones de tokens se vuelven manejables, y queda la base para las ideas nuevas (sección 9).

## 1. Línea base (Python, 10/10/2026)

Copia limpia de Prig (`~/.cache/prig-estudio/repos/Prig`): 385 archivos, 2.041.841 tokens, 7.257 símbolos y 6.984
llamadas resueltas. Dos corridas de `docs/estudio-banco/linea_base_banco.py` (banco temporal, sin modelo ni vectores):

| Operación | Tiempo |
|---|---|
| Indexar desde cero (`sincronizar`) | 9,7–10,3 s |
| Sincronizar sin cambios | 12 ms |
| Partir en unidades | 234–312 ms |
| `P.llamadores` (grafo y texto) | 27 ms |
| `P.grep` en todo el proyecto | 15 ms |
| `P.donde` de una clave | 72–77 ms |
| `P.camino` | 2–3 ms |
| `P.impacto` (grafo y texto, 3 saltos) | 138–147 ms |
| Hechos de una pregunta | 190–250 ms |
| Búsqueda de texto completo | 4–5 ms |

## 2. Qué se mueve y qué queda

| Archivo | A Rust | Queda en Python |
|---|---|---|
| `banco_proyecto.py` (2.669 líneas) | esquema y almacén; listado, lectura y sincronización; análisis de Python, de otros lenguajes y de Markdown; hechos; grafo de llamadas; fragmentos y búsqueda; mapa y paquete de contexto; memoria (conocimiento, resoluciones, cambios, trabajo, resúmenes, unidades); vectores | `analizar`, `sintetizar`, `resumir_respuesta` (llaman al modelo); `Embebedor` (HTTP a Ollama); `Bancos`, el gestor: ~130 líneas de hilos y análisis en segundo plano; lo pesado que hace, sincronizar, ya corre en Rust |
| `particion_proyecto.py` (459) | todo | — |
| `memoria_consulta.py` (1.687) | la API `P` de datos (`lineas`, `leer`, `simbolos`, `codigo`, `hechos`, `llamadores`, `camino`, `impacto`, `donde`, `api`, `ficha`…) y los hechos de la pregunta | `Consola` (el proceso aislado), `revisar`, `P.cargar`, `P.llm`; `P.grep` (la expresión la escribe el modelo con la sintaxis de `re`); «cómo probarla» (usa `revisar`) |
| `lectura_unidades.py` (504) | el enrutador (`LectorUnidades.elegir_unidad`) | lo demás: la lectura con el motor, `mensajes`, la tabla `lecturas` |
| `fichas_simbolos.py`, `examen_proyecto.py` | — | sin cambios: sus tablas (`fichas`, `examen`, `examen_resultados`) van en el mismo archivo, por `conectar()` |
| `app.py`, `herramientas_chat.py` | — | sin cambios |
| `indice_semantico.py`, `knowledge_base.py` | — | fuera del plan: son la biblioteca de libros, otra base de datos |

## 3. Arquitectura

```
~/prig-memoria/                 carpeta nueva, fuera del repositorio de Prig
  Cargo.toml                    workspace
  crates/banco-core/            la biblioteca: todo el motor
    src/ almacen texto archivos python unparse difflib generico grafo
         busqueda contexto memoria particion consultas vectores
  crates/banco-py/              el módulo de Python «prig_banco» (PyO3; maturin lo instala en el .venv de Prig)
  crates/banco-cli/             «banco indexar | consultar | comparar»: pruebas y mediciones sin Prig
  herramientas/
    comparar_motores.py         indexa con los dos motores y compara tablas, unidades y consultas
    doradas/                    las tablas doradas: entradas reales y la salida de Python, en JSON
    probar                      «./probar F3»: la prueba sencilla de cada fase
  pruebas/fixtures/             proyectos chicos (los de los tests de Prig)
```

- **El mismo archivo SQLite, el mismo esquema** (`VERSION_ESQUEMA = 6`: 19 tablas y la vista `grafo`). Un banco creado
  por un motor lo lee el otro: se compara sobre el mismo formato, los bancos que existen siguen sirviendo sin reindexar
  y se puede volver a Python en cualquier momento.
- **Una sola copia de SQLite en el proceso.** El Python de Prig (3.12.3, el del sistema) usa la `libsqlite3.so.0` del
  sistema (3.45.1, con FTS5), y Rust se enlaza con esa misma (`rusqlite` **sin** `bundled`). Con dos copias de SQLite
  en un proceso, cerrar una conexión de una puede soltar los bloqueos de la otra y corromper el banco
  (<https://www.sqlite.org/howtocorrupt.html>, 2.2.1). WAL y `timeout=30`, como hoy.
- **Fachada en Prig** (`backend/banco_motor.py`, nuevo): decide el motor (variable `PRIG_BANCO_MOTOR` o ajuste
  `banco_motor`; `python` por defecto hasta la prueba base). `BancoProyecto`, `particion_proyecto`, la `API` de la
  consola, `hechos_de_la_pregunta` y `elegir_unidad` conservan nombres, parámetros y lo que devuelven; con `rust`
  delegan en `prig_banco`. Una operación se delega recién cuando está completa en Rust (`sincronizar`, por ejemplo,
  desde F6); antes, cada fase se prueba con el comparador. Si el módulo no está o su versión de interfaz no es la
  esperada, todo usa Python: Prig nunca queda roto.
- **`conectar()` sigue en Python**: devuelve un `sqlite3.Connection` al mismo archivo, porque `fichas_simbolos`,
  `examen_proyecto`, `lectura_unidades` y los tests hacen SQL directo.
- **Hilos**: Rust suelta el GIL en todo lo largo (sincronizar, partir, componer, consultas, hechos). Una conexión por
  operación, como hoy; el objeto de Rust guarda solo rutas y ajustes, así que se comparte entre hilos sin cuidado
  extra. La consola aislada (otro proceso) también importa `prig_banco`.
- **Bibliotecas de Rust**: `rusqlite`, `pyo3`, `ruff_python_parser` y `ruff_python_ast` (fijadas a una etiqueta de git;
  ver F0), `regex` y `fancy-regex`, `unicode-normalization`, `sha1`, `flate2`, `indexmap` y `rayon` (analizar archivos
  en paralelo e insertar en el orden de Python).

## 4. Reglas

1. **No vencer las lecturas guardadas** (88 estados, 23 GB, ~45 min de relectura). El texto de cada unidad
   (`LectorUnidades.mensajes`) se arma con la partición, el contenido de los archivos y la firma, la línea y las
   llamadas de cada símbolo: todo eso tiene que salir idéntico. La puerta es el hash de `mensajes(u)` en todas las
   unidades (F9 y prueba base).
2. **Los mismos datos que Python**: cada tabla igual fila por fila, ids incluidos (el orden de los empates de la
   búsqueda puede depender de ellos). Lo que no puede coincidir (fechas, bytes comprimidos) se compara normalizado.
   Cualquier otra diferencia se documenta y la acepta el usuario, una por una.
3. **El mismo texto hacia el modelo**: hechos, paquete, mapa, tarjeta y resultados de `P`, idénticos.
4. **Prig funciona sin Rust**: la fachada vuelve a Python.
5. **Rust no escribe en los bancos reales antes de la prueba base**: trabaja con copias y bancos temporales. El motor
   por defecto cambia después, con una copia de respaldo del banco real.
6. **Solo los archivos que nombra cada fase.** El trabajo en curso del usuario no se toca (`backend/llm_director.py`,
   `backend/motor_aprendizaje_nodos.py` y su test, los archivos de `frontend/` que tiene modificados). Sin commits: los
   hace el usuario.
7. **Cada fase cierra con su prueba sencilla en verde**; si no, no se pasa a la siguiente.

## 5. Trampas de traducción (Python → Rust)

Lo que hace que dos programas «iguales» den resultados distintos. Cada una tiene sus casos en las tablas doradas.

| En Python | En Rust | Qué se hace |
|---|---|---|
| `ast.unparse` arma las firmas (argumentos, retorno, bases), los receptores y las excepciones (14 usos); las firmas llegan al texto de las unidades | no existe | un `unparse` propio con las reglas de CPython 3.12, ya comprobadas: `a: int=5`, `1_000` → `1000`, `0x10` → `16`, `1e3` → `1000.0`, `1e20` → `1e+20`, comillas de `repr` (`"it's"`), `(1, 2)`, paréntesis por precedencia |
| `ast.parse` de CPython 3.12: el inicio de un símbolo incluye sus decoradores; un error de sintaxis manda el archivo a otro camino | `ruff_python_parser` se recupera de los errores y mide en bytes | un error de Ruff cuenta como error; gramática de 3.12; líneas calculadas desde los bytes |
| `difflib.unified_diff(..., n=2)`: los diffs de `cambios` | `similar` usa otro algoritmo y corta distinto | se porta `SequenceMatcher` (con `autojunk`) y `unified_diff`: ~350 líneas deterministas |
| `str.splitlines()` corta también en `\r`, `\v`, `\f`, `\x1c`–`\x1e`, `\x85`, ` ` y ` ` (17 usos) | `lines()` corta solo en `\n` | una función propia |
| `max` y `min` devuelven el **primero** de los empatados (44 usos) | `Iterator::max_by` devuelve el **último** | `max_primero` y `min_primero` propias |
| los `dict` conservan el orden de inserción; `sorted` es estable | `HashMap` no tiene orden | `IndexMap`; `sort_by` (estable), nunca `sort_unstable` |
| `json.dumps`: separadores `", "` y `": "`, `ensure_ascii=True` salvo donde se pide `False`, floats con `repr` (así guardan las unidades `piezas`, `rutas`, `simbolos` y `vecinas`) | `serde_json` compacta y no escapa | un serializador con el formato de Python |
| `re` con mirar adelante o atrás (13 líneas); `\w` y `\d` de Unicode | `regex` no mira adelante ni atrás | `fancy-regex` para esas 13 |
| `unicodedata` 15.0 (NFKD), `str.lower`, `str.strip`, `decode("utf-8", "replace")` | otras versiones de Unicode; `trim` no quita lo mismo | tablas doradas con acentos, símbolos raros y bytes inválidos |
| `//` y `%` redondean hacia abajo; `round` redondea al par | `/` y `%` truncan | `div_euclid`, `rem_euclid`, `round_ties_even` |
| `zlib` nivel 6 para el contenido | `flate2` puede dar otros bytes | se compara el texto descomprimido |
| el orden de un `set` cambia entre ejecuciones | — | el comparador corre Python dos veces con `PYTHONHASHSEED` distinto: lo que cambia ahí es ruido de Python, no un error de Rust |

## 6. Fases

Cada fase: qué se hace, su prueba sencilla y la estimación en sesiones.

### F0. Preparación (1 sesión)

- Instalar Rust (`rustup`, canal estable, perfil mínimo) y `maturin` en el `.venv` de Prig. Necesita internet una vez y
  ~1–2 GB entre herramientas y compilación; después, `cargo vendor` guarda las dependencias y se compila sin red.
- Enlazar con el SQLite del sistema sin ser administrador: si falta `libsqlite3-dev`, un enlace
  `libsqlite3.so → /lib/x86_64-linux-gnu/libsqlite3.so.0` en `~/prig-memoria/lib/`, con `SQLITE3_LIB_DIR` apuntando ahí.
- Crear `~/prig-memoria/` con los tres crates; `prig_banco.version()` y `prig_banco.INTERFAZ`; la fachada
  `banco_motor.py` con el interruptor, todavía sin delegar nada.
- `comparar_motores.py`: indexa una carpeta con cada motor en bancos temporales separados y compara tablas (ids
  incluidos; sin fechas; contenido descomprimido; JSON como texto y además interpretado), unidades y consultas.
- **El analizador de Python** (decide F3): `ruff_python_parser` frente al `ast` de Python 3.12 en los `.py` de la copia
  limpia (190), de la copia E8, del repositorio externo y de la biblioteca estándar (1.771): los mismos símbolos
  (nombre, tipo, inicio, fin, padre) y los mismos archivos con error. Si quedan diferencias que no se pueden corregir,
  `tree-sitter-python` (más trabajo: da un árbol concreto, no el de CPython).
- **Prueba sencilla**: `cargo test` en verde; `import prig_banco` desde el `.venv`; `ldd` del módulo muestra
  `libsqlite3.so.0` y las dos versiones de SQLite coinciden; Python contra Python (dos corridas) da 0 diferencias o la
  lista del ruido; el comparador corre sobre un proyecto de dos archivos.

### F1. Base: almacén y texto (1 sesión)

- Esquema v6 (crear, migrar desde versiones anteriores, `meta`, `version`).
- Utilidades: `estimar_tokens`, sha1, `_sin_acentos`, `terminos`, `terminos_consulta`, `identificadores_nombrados`,
  `lenguaje_de`, palabras vacías, zlib, vectores en float32, y las de la sección 5 (`splitlines`, `max_primero`,
  `json_dumps`, `repr` de cadenas y de floats).
- **Prueba sencilla**: las tablas doradas (~2.000 casos de Prig y de la biblioteca estándar: identificadores, acentos,
  camelCase, snake_case, bytes inválidos), iguales una por una; y la convivencia: Python y Rust escriben a la vez en el
  mismo banco (dos hilos, 10.000 operaciones) y `PRAGMA integrity_check` responde `ok`.

### F2. Archivos y sincronización (1 sesión)

- Listado (`git ls-files` o disco, exclusiones, `MAX_ARCHIVOS`, `MAX_BYTES`, `MAX_BYTES_DATOS`); lectura (UTF-8 con
  reemplazo, cuadernos `.ipynb` a texto); `sincronizar` (nuevos, modificados, borrados); versión; `cambios` con su diff
  (el `difflib` portado) y `_marcar_revisar`.
- **Prueba sencilla**: en un proyecto de juguete, crear, modificar, renombrar y borrar archivos: `archivos` y `cambios`
  iguales a Python (la columna de símbolos cambiados se completa en F3). Abrir con Rust un banco hecho por Python y
  sincronizar: 0 archivos tocados, y al revés. Mientras Rust sincroniza, otro hilo de Python sigue corriendo (el GIL
  está suelto).

### F3. Análisis de Python (2–3 sesiones)

- Símbolos (clases, funciones, métodos y anidadas; firma con el `unparse` propio, docstring, inicio con decoradores,
  fin, padre), alias de importación, usos con receptor, hechos (`lee_config`, `lee_entorno`, `expone` con el prefijo de
  `APIRouter`/`Blueprint`, `llama_api`, `ejecuta`, `atributo`, `hereda`, `captura`…) e importaciones.
- **Prueba sencilla**: los `.py` de las cuatro fuentes de F0: símbolos, firmas, usos, alias, hechos e importaciones
  idénticos, archivo por archivo.

### F4. Otros lenguajes y Markdown (1 sesión)

- Símbolos genéricos (las expresiones de hoy y el cierre por llaves), importaciones genéricas, secciones de Markdown,
  hechos de texto (`llama_api`, `usa_dom`, `define_dom`), `ruta_http_canonica` y `endpoint_de`.
- **Prueba sencilla**: `frontend/`, los `.md` y el repositorio externo, idénticos.

### F5. Grafo de llamadas (1 sesión)

- Resolución de importaciones y de llamadas (receptor, `self`, alias, tipo de retorno anotado, confianza) y la vista
  `grafo`.
- **Prueba sencilla**: `importaciones` y `llamadas` idénticas (6.984 llamadas en la copia limpia; también E8 y el
  externo).

### F6. Fragmentos y búsqueda (1 sesión)

- Fragmentación, términos para FTS5, `buscar` (bm25, rutas mencionadas, vecinos y vectores si los hay) y
  `texto_busqueda`.
- **Prueba sencilla**: `fragmentos` idéntica (ids incluidos), y los 12 primeros resultados de `buscar` iguales para las
  76 preguntas del estudio (`docs/estudio-banco/**/*preguntas*.json`, `examen_independiente.json` y las de los
  scripts) y para 300 consultas armadas con símbolos, claves y rutas del propio banco.

### F7. Mapa y paquete de contexto (1 sesión)

- `mapa` (también la tarjeta del proyecto, `mapa(TOPE_TARJETA)`), `componer`, `resumen_archivo`, `ver_simbolo`,
  `quien_usa`, el resumen básico y `estado`.
- **Prueba sencilla**: el texto de `componer` y el de la tarjeta, idénticos carácter por carácter, para las mismas
  preguntas.

### F8. Memoria (1 sesión)

- Conocimiento (anotar, afirmar, olvidar, listar, buscar), resoluciones (registrar, listar, buscar, olvidar,
  recordar), cambios (`cambios_desde`, `texto_cambios`), trabajo, resúmenes y el guardado de unidades.
- **Prueba sencilla**: los tests de memoria de `test_banco_proyecto.py` con `PRIG_BANCO_MOTOR=rust`, y 500 operaciones
  al azar (la misma secuencia en los dos motores) que dejan las tablas iguales.

### F9. Partición (1 sesión), la crítica

- `particion_proyecto` completo: piezas, pesos, aristas, agrupación, componentes fuertes, orden (con `git log`) y
  `nombre_unidad`.
- **Prueba sencilla**: `unidades` idéntica y **el hash de `mensajes(u)` igual en todas las unidades** (las copias y una
  copia del banco real); `test_particion_proyecto.py` con Rust. Si no coincide, no se avanza.

### F10. Consultas y hechos de la pregunta (2 sesiones)

- La API `P` de datos: `lineas`, `leer`, `simbolos`, `codigo`, `hechos` (con las lecturas literales), `llamadores`
  (grafo y texto: instancias, fábricas, módulos, cadenas, valores), `camino`, `camino_con_llamadas`,
  `codigo_del_salto`, `impacto`, `alcance_por_texto`, `donde`, `api` y `ficha`; los hechos de la pregunta
  (`terminos_de`, `_hechos_de`, trampas conocidas, claves sospechosas, asignaciones de módulo, código en revisión); y
  el enrutador `elegir_unidad`.
- Rust devuelve los hechos por partes, y la fachada pone «cómo probarla» en su lugar (usa `revisar`, que queda en
  Python). `P.grep` sigue con `re` de Python.
- **Prueba sencilla**: `test_memoria_consulta.py` (42 tests) y `test_lectura_unidades.py` (12) con Rust; los hechos
  idénticos para todas las preguntas; las consultas `P` iguales para los 300 símbolos, claves y rutas de F6.

### F11. Vectores, estado y gestor (1 sesión)

- Vectores (guardar, cargar, coseno, pendientes) y `estado()`. `Bancos` y `Embebedor` siguen en Python, ahora sobre el
  motor elegido.
- **Prueba sencilla**: los tests de vectores y de `Bancos` con Rust; `test_examen_proyecto.py` y
  `test_fichas_simbolos.py` sobre un banco hecho por Rust (escriben sus tablas con `conectar()`).

## 7. Prueba base final y corrección (F12, 1–2 sesiones)

La prueba completa, la que decide el cambio de motor.

1. **Datos**: indexar con los dos motores la copia limpia de Prig, la copia E8, el repositorio externo y una copia del
   Prig real, y comparar las 19 tablas fila por fila. Criterio: 0 diferencias, o cada una documentada y aceptada.
2. **Unidades**: el hash de `mensajes(u)`, igual en todas. Con una copia del banco real abierta por Rust, las unidades
   con lectura guardada la siguen encontrando (el mismo número antes y después).
3. **Ida y vuelta**: Python indexa, Rust sincroniza cambios y Python vuelve a sincronizar: nada que reindexar, ningún
   cambio fantasma.
4. **Consultas**: para las 76 preguntas y las 300 consultas armadas, `componer`, `buscar`, los hechos y las consultas
   `P`, iguales.
5. **Tests**: los 1051 de Prig con `PRIG_BANCO_MOTOR=rust`, y también con `python` (la fachada no rompió nada).
6. **Con el modelo**: la medición corta en modo `auto` (las 11 preguntas de falla y el control; E8a). El mismo
   resultado que con Python, dentro de la variación conocida: hoy, 10 de 11, y 7 de los 8 errores ocultos de forma
   estable.
7. **Velocidad**: `linea_base_banco.py` con Rust. Ninguna operación puede ser más lenta que en Python; se espera ~1 s
   para indexar Prig y ~20 ms para los hechos.
8. **Corregir** cada diferencia, volver a correr lo afectado y repetir hasta que todo pase. Recién entonces el motor por
   defecto pasa a `rust` (con respaldo del banco real), y Python queda de respaldo hasta que el uso diario lo confirme.

## 8. Riesgos

| Riesgo | Qué se hace |
|---|---|
| El análisis de Python no coincide con el de CPython | la prueba de F0 sobre ~2.100 archivos; Ruff o tree-sitter, el que dé igual |
| El formato de `ast.unparse` cambia las firmas y vence lecturas | `unparse` propio con tabla dorada (sección 5); puertas en F3 y F9 |
| Una diferencia en la partición vence las 88 lecturas | la puerta de F9 y la prueba base |
| Dos copias de SQLite en el proceso corrompen el banco | Rust usa la `libsqlite3` del sistema; prueba de convivencia en F1 |
| Una actualización de Ubuntu cambia el SQLite del sistema | la usan los dos motores, así que cambian juntos |
| Ruff no publica su analizador como biblioteca estable | fijado a una etiqueta de git y guardado con `cargo vendor` |
| Instalar Rust necesita internet | una sola vez; después, `cargo vendor` |
| Dos motores a mantener por un tiempo | la fachada y el interruptor; Python se retira solo después de la prueba base y del uso real |

## 9. Después (fuera de este plan)

Con el motor en Rust quedan al alcance las ideas que sí aceleran las respuestas, cada una con su propio plan y su
medición: respuestas instantáneas a preguntas estructurales, un corrector de citas (líneas exactas, rutas reales), un
contexto de sesión que reaprovecha lo ya leído, la relectura incremental en segundo plano, un almacén de estados sin
repetidos, el grafo exacto para JS/TS con tree-sitter y la vigilancia de archivos sin sondear (`notify`).

## 10. Estimación y para empezar

| | |
|---|---|
| Sesiones | 15–17 (F0–F11: 14–15; prueba base y corrección: 1–2) |
| Rust | ~10.000–12.000 líneas y ~3.000 de tests |
| Python | ~800 (fachada, comparador, generadores de las tablas doradas) |

Para empezar hace falta que el usuario apruebe:

1. la carpeta `~/prig-memoria/`;
2. instalar Rust con `rustup` (internet una vez, ~1–2 GB);
3. instalar `maturin` y el módulo `prig_banco` en el `.venv` de Prig (se deshace con `pip uninstall`).

## 11. Bitácora

| Fase | Estado | Prueba sencilla | Notas |
|---|---|---|---|
| F0 Preparación | hecha (10/10) | Rust 1.99 sin tocar `.bashrc`; `prig_banco` en el `.venv`; una sola `libsqlite3` (3.45.1) en el proceso | analizador: Ruff 0.0.17 de crates.io (no hizo falta git); el BOM inicial lo acepta Ruff y CPython no: se trata como error |
| F1 Almacén y texto | hecha (10/10) | `terminos` igual en 3.023 archivos; `sum` de 3.12 (Neumaier), `round`, `repr`, `json.dumps`, `splitlines`, conjuntos de enteros de CPython: tests unitarios | — |
| F2 Archivos y sincronización | hecha (10/10) | copia limpia: 19 tablas idénticas (ids incluidos); con cambios (modificar, crear, borrar, renombrar): 0 diferencias, `cambios` con sus diffs y notas a revisar iguales; cruzado sin cambios: 0 archivos tocados | indexar Prig: 10,2 s → 1,07 s |
| F3 Análisis de Python | hecha (10/10) | 3.023 archivos (copia limpia, E8, externo, biblioteca estándar): árbol, líneas, `unparse`, símbolos, hechos e importaciones iguales | diferencias aceptadas: cadenas con sustitutos sueltos (`'\ud800'`, solo en tests de la biblioteca estándar; en Python ese texto ni se puede guardar en SQLite) y la línea de las partes de un f-string (el banco no la usa) |
| F4 Otros lenguajes y Markdown | hecha (10/10) | símbolos genéricos, importaciones, secciones y hechos de texto iguales en los cuatro corpus | — |
| F5 Grafo de llamadas | hecha (10/10) | `importaciones` y `llamadas` idénticas en la copia limpia (6.984), E8 y el externo | — |
| F6 Fragmentos y búsqueda | hecha (11/10) | `fragmentos` idéntica; `buscar`, `buscar_conocimiento`, `buscar_resoluciones` y `texto_busqueda` iguales en las 76 preguntas del estudio + 300 armadas, con y sin vectores | la consulta de símbolos nombrados (`simbolos.nombre` sin índice) tardaba ~190 ms en los dos motores; Rust la resuelve por el índice de `corto` con el mismo orden que deja SQLite (fr.ini, fr.id, s.id): ids iguales en 676 consultas × 3 corpus; `buscar` 209 → 14 ms |
| F7 Mapa y paquete | hecha (11/10) | `componer` (texto y datos) y `mapa` (1.500–20.000 tokens) iguales carácter por carácter | `buscar` + `componer` de 752 consultas: Python 237 s, Rust 21 s (11,5×) |
| F8 Memoria | hecha (11/10) | anotar (y actualizar), resoluciones, afirmar, trabajo, resúmenes, carpetas y estado: tablas idénticas; las listas y textos, iguales salvo la hora | — |
| F9 Partición | hecha (11/10) | **puerta OK**: tabla `unidades` y resumen idénticos y el hash de `mensajes(u)` igual en todas las unidades: copia limpia (96), E8 (96), externo (8) y una copia del banco real (97). Las lecturas guardadas siguen valiendo | partir: 0,25–0,31 s → 0,1 s |
| F10 Consultas y hechos | hecha (11/10) | API `P` (código, llamadores, llamados, camino, ficha, recorrido, impacto, donde, api, hechos con lecturas literales, cambios, diff…), `hechos_de_la_pregunta` y `terminos_de`: iguales en ~4.000 comparaciones (196 preguntas, 180 símbolos, 114 claves, 1.310 endpoints) | hechos de una pregunta 287 → 90 ms; `P.donde` 75 → 20 ms; `P.impacto` 141 → 60 ms. Diferencias aceptadas: abajo |
| F11 Vectores, estado y gestor | hecha (11/10) | fachada `backend/banco_motor.py`: 37 métodos de `BancoProyecto`, 24 de la `API`, `particionar`, `hechos_de_la_pregunta` y `elegir_unidad` delegan en Rust; los 1.051 tests de Prig en verde con `rust` y con `python` | la consola aislada (`python -I`) también usa Rust (`PRIG_BANCO_MOTOR` pasa a su entorno) |
| F12 Prueba base y corrección | hecha (11/10) | datos: 0 diferencias en las 19 tablas (copia limpia, E8, externo y el Prig real); unidades: puerta F9; ida y vuelta: 0 archivos tocados; consultas y tests: arriba | ver sección 12 |
| Revisión y retiro de Python | hecha (11/10) | `comparar_fachada` (por los módulos de Prig): 0 diferencias en ~3.800 llamadas; todas las demás pruebas otra vez; 1.054 tests | 4 errores corregidos (bloqueos con WAL, pila desbordada, topes de CPython, archivos ocultos): sección 13 |

## 12. Resultado (11/10/2026)

**Prig usa solo el motor de Rust** (desde la revisión del 11/10, sección 13: el motor de Python se quitó de Prig y quedó
congelado en `~/prig-memoria/referencia`, solo para comparar). Sin `prig_banco` instalado, Prig no arranca el banco:
`banco_motor.py` da un ImportError que dice cómo compilarlo.

| Operación (copia limpia de Prig) | Python | Rust |
|---|---|---|
| Indexar desde cero | 9,5–10,3 s | 0,9–1,1 s |
| Indexar el Prig real | 12,7 s | 1,2 s |
| Partir en unidades | 0,25 s | 0,10 s |
| `buscar` + `componer` (752 consultas) | 237 s | 21 s |
| Hechos de una pregunta | 190–290 ms | 90–120 ms |
| `P.donde` / `P.impacto` / `P.llamadores` | 75 / 141 / 28 ms | 20 / 60 / 20 ms |

**Dónde está y cómo se mantiene**

- Código: `~/prig-memoria/` (workspace: `crates/banco-core` el motor, `crates/banco-py` el módulo `prig_banco`,
  `crates/banco-cli`). Rust 1.99 en `~/.rustup` y `~/.cargo` (sin tocar `.bashrc`).
- Recompilar e instalar en el `.venv` de Prig:
  `cd ~/prig-memoria/crates/banco-py && VIRTUAL_ENV=~/Prig/.venv PATH=~/.cargo/bin:~/Prig/.venv/bin:$PATH maturin develop --release`
- Se enlaza con la `libsqlite3.so.0` del sistema (`~/prig-memoria/lib/libsqlite3.so` y `.cargo/config.toml`): una sola
  copia de SQLite en el proceso.
- Un cambio en el banco se hace en Rust (`~/prig-memoria/crates/banco-core`). Si debe dar lo mismo que antes, se
  comprueba con `~/prig-memoria/herramientas/`: comparan Rust con la referencia de Python sobre los mismos proyectos
  (comparar_extraccion, comparar_motores, probar_sincronizacion, comparar_consultas, probar_particion,
  comparar_consola, probar_bordes, probar_convivencia y comparar_fachada, que pasa por los módulos de Prig). Si el
  cambio es a propósito, se cambia también la referencia o se anota como diferencia aceptada.
- Lo que sigue en Python a propósito: los bucles con el modelo de `analizar` y `sintetizar` (los datos que leen y
  escriben los da Rust), el embebedor y el gestor de bancos (llaman al modelo o a Ollama), la consola aislada
  (`revisar`, `P.cargar`, `P.grep` con `re`, `P.sql`, «cómo probarla»), y las tablas de lecturas, fichas y examen (sus
  módulos escriben con `conectar()`).

**Diferencias aceptadas** (documentadas, ninguna llega al texto de las unidades guardadas)

1. Cadenas con sustitutos sueltos (`'\ud800'`, solo en tests de la biblioteca estándar): Rust no puede representarlas
   y escribe `�`; en Python ese texto ni siquiera se puede guardar en SQLite (la sincronización fallaba).
2. Donde Python recorre un `set` de textos (cambia en cada proceso con la semilla de hash): `alcance_por_texto`
   (frontera inicial; afecta `endpoints_por_texto` cuando el tope de 15 búsquedas corta) y los empates de puntos en
   `elegir_unidad` (orden de las alternativas empatadas). Rust usa un orden fijo; con la mayoría de las semillas da lo
   mismo que Python (p. ej. 4 de 6 en `impacto("explicaciones")`).
3. Un `.ipynb` cuyo JSON no es un objeto: Python fallaba con AttributeError en toda la sincronización; Rust lo trata
   como un cuaderno sin celdas.
4. La línea de las partes de un f-string en el árbol (el banco no la usa).

**Mejoras de velocidad que no cambian resultados**: la consulta de símbolos nombrados de `buscar` (~190 ms en los dos
motores, sin índice en `simbolos.nombre`) se resuelve por el índice de `corto` con el mismo orden que deja SQLite
(verificado en 676 consultas × 3 corpus); expresiones compiladas una vez; la búsqueda de cadenas con forma de nombre
sin retroceso (igual en 200.884 líneas).

**No se corrió** la medición con el modelo (paso 6 de la sección 7): los textos que recibe el modelo (paquete,
mapa, tarjeta, hechos, resultados de `P` y el prefijo de cada unidad) son idénticos a los de Python, así que la
respuesta no puede cambiar por el motor. Queda para cuando se use la GPU.

## 13. Revisión completa y retiro del motor de Python (11/10/2026)

**Qué se quitó.** El motor de Python ya no está en Prig. `banco_proyecto.py` (2.772 → 764 líneas),
`particion_proyecto.py` (463 → 39) y la parte de datos de `memoria_consulta.py` (1.764 → 862) quedaron como una cara
del módulo `prig_banco`, con los mismos nombres y firmas; `lectura_unidades.elegir_unidad` usa solo Rust; y
`banco_motor.py` ya no elige motor: carga `prig_banco` o da un ImportError que dice cómo compilarlo
(`PRIG_BANCO_MOTOR` ya no existe). `analizar` y `sintetizar` siguen en Python (llaman al modelo), pero los datos que
leen y escriben los da Rust (`para_analizar`, `guardar_analisis`, `notas_de_analisis`, `shas_de_resumenes`,
`readme_y_previo`). El motor de Python quedó congelado en `~/prig-memoria/referencia`, solo para comparar (su README
lista los defectos que conserva); `docs/estudio-banco/particion.py` (E3) usa esa copia y
`linea_base_banco.py --referencia` la mide.

**Errores encontrados y corregidos**

| Error | Efecto | Arreglo |
|---|---|---|
| Escrituras con transacción diferida (lectura → escritura) bajo WAL | con Python y Rust escribiendo a la vez, 2.056 «database is locked» en `probar_convivencia` (SQLITE_BUSY sin esperar) | las 9 transacciones de escritura de Rust son `BEGIN IMMEDIATE`: 0 errores, `integrity_check` ok |
| Anidamiento extremo (`x = ------…1`, `a.b.b.b…`, `[[[…]]]`) | con unos 5.000 niveles se desbordaba la pila del hilo y **moría el proceso entero de Prig** (Python daba RecursionError o MemoryError y la sincronización fallaba) | `pyast::cota_de_profundidad` aplica los topes del tokenizador de CPython que Ruff no tiene (más de 200 paréntesis abiertos o de 99 niveles de sangría: SyntaxError, igual que Python) y da una cota de la recursión; `con_pila` corre el análisis en un hilo con pila a medida cuando pasa de 1.000 niveles (medido: ~350 B por nivel, ~900 B en el peor caso, las firmas; se reservan 4 KB, solo virtuales). Un archivo de 1 MB con un millón de niveles: 3,6 s y 1,1 GB, sin caerse |
| Topes de CPython no copiados | 100 clases anidadas o 201 paréntesis: Python no veía nada (SyntaxError) y Rust sí | ahora es igual en los bordes medidos (99/100 niveles de sangría, 200/201 paréntesis, la llave de un f-string cuenta; lo que está en cadenas y comentarios no) |
| Archivos ocultos (heredado de Python): `strip("./")` les quitaba el punto | `resumen_archivo(".pre-commit-config.yaml")` se llamaba a sí mismo sin fin: RecursionError en Python, **pila desbordada en Rust** (la herramienta del chat podía tirar Prig); `anotar`, las rutas mencionadas y las resoluciones no los reconocían | primero la ruta tal cual y después la recortada; el candidato único se resume sin volver a llamarse |

**Mejoras**: el límite de retroceso de fancy-regex sube a 200 millones (el `re` de Python no tiene límite: con el de
1 millón, un patrón interno del motor con retroceso podía dar error sobre un archivo grande donde Python solo tardaba
más); las líneas de cada archivo se
comparten entre las consolas del proceso (validadas por el sha del archivo, con tope de 256 MB); las expresiones
compiladas se guardan; `banco_motor.consulta` falla claro con una conexión que no es a un archivo.

**Verificación** (Prig sin motor de Python contra la referencia congelada)

- `comparar_fachada` (nuevo): pasa por los módulos de Prig, no por `prig_banco` directo. Cada lado sincroniza su copia,
  consulta, escribe memoria, embebe con un embebedor falso, analiza y sintetiza con un modelo falso, edita la copia y
  vuelve a sincronizar, parte en unidades, enruta preguntas y usa la consola: 1.287 llamadas en la copia limpia y en
  E8, 1.245 en el externo, **0 diferencias** (solo las aceptadas: el orden por la hora de la memoria, que es por
  segundos, y un empate en `elegir_unidad`). Referencia 98 s, Prig 22 s.
- Tablas (19, ids incluidos), sincronización con cambios y cruzada, bordes con y sin git, migración desde el esquema 5:
  0 diferencias. Convivencia: 0 errores. Partición: puerta F9 en los cuatro bancos (incluido el real).
- Consultas (`comparar_consultas`, 68–69 secciones por corpus): 0 diferencias en la copia limpia y en E8; en el externo,
  solo las 2 preguntas que nombran `.pre-commit-config.yaml`, donde Rust ahora trae ese archivo (diferencia 5).
  `buscar` + `componer` de 752 consultas: 239 s → 21 s. Consola (`comparar_consola`, 24 secciones × 3 corpus): solo
  empates de `elegir_unidad` (diferencia 2); hechos de una pregunta 298 → 97 ms. Los tests de Prig: 1.054 en verde.
- Línea base (`linea_base_banco.py`, copia limpia; con `--referencia`, el de Python): indexar 9,3 s → 0,91 s; partir
  229 → 106 ms; hechos de una pregunta 190–240 → 40–76 ms; `P.donde` 73 → 20 ms; `P.impacto` 137 → 61 ms. `P.grep`
  sigue en Python (`re` sobre las líneas que da Rust): 15 → 18 ms, por pasar las líneas a listas de Python.
- Los topes y el anidamiento extremo: `TestBordesDelMotor` en `test_banco_proyecto.py` (el de la pila corre en otro
  proceso, con un hilo de 2 MB).

**Diferencias aceptadas nuevas** (se suman a las de la sección 12; en todas, Python fallaba)

5. Archivos ocultos: Rust los reconoce; Python se colgaba en una recursión o los ignoraba.
6. Anidamiento más allá de lo que CPython analiza (MemoryError «Parser stack overflowed» o RecursionError al construir
   el árbol): Python hacía fallar toda la sincronización; Rust analiza el archivo. En una firma con más de ~300
   niveles, Python la dejaba en `(...)` (RecursionError dentro de `ast.unparse`, con un umbral que depende de la
   profundidad de la llamada); Rust la escribe completa.

**Lección de la prueba de esfuerzo**: un texto de prueba que crece con n² (clases anidadas con sangría creciente)
llegó a 59 GB y el kernel mató el proceso; con la memoria agotada se cayeron VS Code y la sesión. Las pruebas de
esfuerzo calculan el tamaño antes de armar el texto y corren con `ulimit -v`.
