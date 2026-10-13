# Estudio completo del banco del proyecto

Qué se implementó, qué está demostrado, qué no, y por qué. Se hace por pasos cortos (uno por sesión, se
retoma con «siga»); cada paso agrega aquí su sección con datos, no opiniones. Documentos de base:
`arquitectura-unificada.md` (diseño y resultados), `plan-lectura-unica.md`, `memoria-consulta.md`,
`motor-moe.md`, `banco-proyecto.md`.

## 0. Método (cómo se evita engañarse)

Cada paso declara **hipótesis**, **qué resultado la refutaría**, **medición** y **control**. Reglas:

1. **Verdad independiente.** El examen actual se genera con los mismos datos del banco que el modelo
   consulta: mide coherencia interna, no verdad. Toda afirmación de exactitud se contrasta con una fuente
   que no sea el banco (el intérprete de Python, la ejecución de los tests, la historia de git, lectura
   humana de una muestra).
2. **Ruido antes que diferencias.** Ninguna mejora se da por buena sin conocer la varianza: la misma
   corrida dos veces. Con n = 153, un 97,7 % tiene un intervalo del 95 % de aprox. [94 %, 99 %]; dos
   configuraciones que difieren menos que eso no se distinguen.
3. **Una variable por vez** (ablaciones): sin banco / modo general / modo unidad / sin consola / sin
   expertos calientes / sin fichas.
4. **Auditar al corrector.** El puntaje lo da `examen_proyecto.corregir()` buscando identificadores: puede
   premiar respuestas que listan muchos candidatos (inflar recall). Se audita a mano una muestra.
5. **Costo siempre junto a la calidad**: tokens leídos y escritos, segundos, VRAM, disco, temperatura.
6. **Sin tocar lo del usuario**: nada de modificar configuración ni `last_workspace`; el Ollama del sistema
   no se toca; todo proceso largo es reanudable (el equipo no tiene batería) y apaga su llama-server al
   terminar.

## Punto de partida (inventario del 30/09/2026)

| Pieza | Tamaño | Tests |
|---|---|---|
| `banco_proyecto.py` (esquema v5, símbolos, grafo, hechos, memoria) | 2.608 líneas | 31 |
| `memoria_consulta.py` (consola P aislada) | 739 | 17 |
| `particion_proyecto.py` (unidades) | 459 | 6 |
| `lectura_unidades.py` (lectura única, prefijo estable, enrutador) | 394 | 8 |
| `fichas_simbolos.py` (fichas verificadas) | 186 | 5 |
| `examen_proyecto.py` (examen y corrector) | 414 | 4 |
| `ai_engine/motor_moe.py` (motor, estados, expertos calientes) | 1.254 | 41 |
| `recursos/frio.py`, `termico.py` (gobernador térmico) | 1.088 | — |

**Banco de Prig** (`~/.prig_bancos/Prig-ac5380d79d/banco.db`, 38 MB): 380 archivos, 136.857 líneas,
~1,25 M tokens, 7.029 símbolos, 6.816 llamadas resueltas, 28.399 usos, 5.276 hechos, 8.244 fragmentos
(el 40 % del peso, con su índice FTS5), 94 unidades, 274 fichas, 313 resoluciones, 6 notas de
conocimiento, **0 vectores**, 0 resúmenes, tabla `lecturas` (4,85 MB) sin documentar.

**Estados del motor**: 27 GB en 105 archivos (`~/.cache/prig-moe/proyectos`), tope 32 GB con
desalojo por antigüedad. Unos **22 KB de disco por token leído**.

**Máquina**: i5-13420H (12 hilos, núcleos P y E), RTX 4050 6 GB (tope útil CUDA ~5.770 MiB), 62 GB de
RAM, NVMe con 190 GB libres, sin batería.

**Modelo**: Qwen3.6-35B-A3B MoE: 40 capas (30 Gated DeltaNet con estado fijo de ~66 MB, 10 de atención
con 2 cabezas KV de 256 y RoPE parcial), 256 expertos de 8 activos + 1 compartido, capa MTP; KV q8
~10,9 KB/token.

**Resultados previos**: sin banco 14,8 % (27 preguntas); con banco 97,7 % (153); prefijo estable
90,6 % (102 de 153, parcial, con un bug de `P.api` ya corregido y sin volver a medir). Mediana
16–18 s por pregunta; las preguntas de impacto, 5–8 min.

## Pasos

Cada paso cabe en una sesión. Los marcados con ⏱ usan el modelo durante horas: se lanzan en segundo
plano, reanudables, y el paso siguiente sin modelo avanza mientras tanto.

### E1. Mapa de datos e invariantes (sin modelo)
Cada tabla y columna: quién la escribe, quién la lee, qué invariante debe cumplir. Se verifica con SQL:
huérfanos (usos o llamadas a símbolos inexistentes), `sha` desactualizados frente al disco, duplicados,
unidades que no cubren todo el código o se pisan, fichas de símbolos que ya cambiaron. Qué es
`lecturas` y por qué `vectores`, `trabajo` y `resumenes` están vacías.
*Refuta «el banco es consistente»*: cualquier invariante roto.

### E2. Exactitud de la extracción, contra una verdad independiente (sin modelo)
Muestra estratificada de símbolos, llamadas, hechos (endpoints, claves de configuración, variables de
entorno) y usos. Se compara con el AST completo de Python, con búsqueda textual exhaustiva y con lectura
manual. Se mide precisión y recall del grafo de llamadas por tipo de resolución (receptor, alias,
anotación de retorno, nombre único, anidadas) y por lenguaje (Python frente a JS y otros).
*Por qué importa*: todo lo demás se apoya en el grafo; un 5 % de aristas falsas se hereda en impacto y
recorridos.

### E3. Partición y unidades (sin modelo)
Distribución de tamaños, cohesión (llamadas dentro de la unidad frente a entre unidades), qué preguntas
cruzan unidades, estabilidad de la partición ante un cambio pequeño (si se reordena todo, se invalidan
todos los estados). Simulación con topes de 8K, 16K y 24K tokens: cantidad de unidades, disco, cobertura.

### E4. Motor y máquina (poco modelo)
Anatomía de un estado guardado (KV, estado SSM, extras; por qué ~22 KB/token cuando el KV en q8 es
~10,9), latencia de restauración en frío y en caliente, efecto de la caché de páginas del sistema,
presupuesto de VRAM por contexto, acierto de expertos calientes por unidad, velocidad de lectura y de
escritura según temperatura. Ley de escala: disco y tiempo para 5 y 10 veces Prig.

### E5. Consola P: corrección y seguridad (sin modelo)
Cada método de `P` contra el banco: resultados esperados en casos borde (nombres repetidos, anidadas,
rutas con parámetros; el bug de `P.api` es un ejemplo de lo que busca). Pruebas adversariales del
aislamiento: escape del AST, lectura fuera del banco, memoria, tiempo, procesos hijos, red.

### E6. Validez del examen (sin modelo + auditoría)
Circularidad (el examen se genera desde el banco), sesgo del corrector (auditoría manual de ~40
respuestas: falsos positivos y negativos), qué capacidades **no** mide (por qué, diseño, errores). Se
construye un segundo examen con verdad independiente: preguntas desde la historia de git («qué cambió
para arreglar X»), desde la ejecución (qué devuelve esta función con esta entrada) y escritas a mano.

### E7. ⏱ Medición rigurosa de exactitud
Examen completo con el arreglo de `P.api`, dos veces (ruido); intervalos de confianza por tipo;
ablaciones de una variable por vez; el examen independiente de E6. Latencias por percentiles y tokens
leídos y escritos por respuesta.

### E8. ⏱ Razonamiento profundo: el «análisis completo» de verdad
Lo que el examen no cubre: localizar errores inyectados (off-by-one, caso borde, recurso sin cerrar,
clave de configuración mal escrita) con la verdad conocida; predecir el impacto de un cambio y
comprobarlo corriendo los tests; explicar un flujo de punta a punta y verificar cada afirmación con citas
comprobables. Aquí se decide si sirve para revisar código (los desafíos-proyecto).

### E9. Memoria viva y cambios (poco modelo)
Si las 313 resoluciones guardadas reinyectan respuestas equivocadas (bucle de contaminación); vigencia
de notas y fichas tras editar; una sesión de edición realista: cuántas unidades se invalidan, cuánto
cuesta releer, si el modelo ve el cambio.

### E10. Escala, costos y veredicto
Modelo de costos con los datos de E1–E9; límites (disco por token, tiempo de lectura, VRAM); diseño
por niveles para repositorios grandes (qué estados guardar y cuáles releer); qué hace falta para los
desafíos-proyecto. Veredicto: qué está demostrado, qué no, y las recomendaciones en orden de impacto.

## Resultados

### E1. Mapa de datos e invariantes (30/09/2026, sin modelo, todo en solo lectura)

**Quién escribe y quién lee.** Todas las tablas del núcleo las escribe solo `banco_proyecto.py`; las leen la
consola, la partición, la lectura por unidades y el examen. Cuatro tablas vienen de otros módulos:
`lecturas` (registro de las lecturas de unidades, `lectura_unidades.py`), `fichas`, `examen` y
`examen_resultados`. Las **fichas solo las lee su propio módulo**: ni `P.ficha` ni el chat las usan.

**Invariantes que se cumplen**

- 0 huérfanos en las 7 tablas con ruta; el índice FTS tiene las mismas 8.244 filas que `fragmentos`.
- **Grafo sin aristas colgadas**: de 6.816 llamadas, ninguna apunta a un símbolo inexistente ni sale de
  uno inexistente. Por confianza: exacta 5.759 (84 %), aproximada 763 (11 %), única 294 (4 %). Que exista
  el destino no dice si es el correcto: eso lo mide E2.
- Ningún símbolo con `fin < ini` ni fuera de su archivo; las 274 fichas corresponden al símbolo vigente.
- Las 94 lecturas registradas tienen su estado `.bin` en disco.

**Invariantes rotos o dudosos**

| # | Hallazgo | Consecuencia | Gravedad |
|---|---|---|---|
| 1 | **Memoria contaminada por el examen**: cada respuesta del chat con banco se guarda en `resoluciones` (313; 203 son preguntas del examen; 111 de preguntas que alguna vez puntuaron 0). En modo general, `componer()` inyecta las 3 más parecidas, y la pregunta repetida del examen es idéntica | Las corridas del examen **no son independientes**: la corrida N ve las respuestas de la N−1, correctas o no. Las mediciones anteriores pueden estar sesgadas (hacia arriba si copia aciertos, hacia abajo si copia errores) | **Alta** para la validez del estudio |
| 2 | **Cobertura de lectura del 63 %**: las unidades cubren el 100 % del código de producción (Python, JS, C) y el 0 % de documentos (22.000 líneas), **tests** (16.443), HTML, CSS, JSON y cuadernos | El proyecto no son 1,25 M tokens sino ~2,0 M; lo leído es el código. De los tests el modelo solo sabe lo que busque con la consola: relevante para revisar código | Media: es por diseño, no estaba documentado |
| 3 | **Disco por token**: los estados de las unidades vigentes ocupan 25,8 GB; cada uno guarda ~21K tokens (prompt fijo + código) a 14,3 KB por token (KV q8 10,9 + estado SSM fijo de 66 MB repartido). La tarjeta global (5.248 tokens) se repite en los 94 estados: **~7 GB (27 %)** | Un prefijo compartido (el «tronco» en investigación en la arquitectura) ahorraría más de un cuarto del disco | Media: es el límite de escala |
| 4 | **11 estados huérfanos (3 GB)** de la madrugada del 30/09 (época de la regresión, cuando la guía iba en el prefijo); nadie los borra hasta llegar al tope de 32 GB | Disco perdido; con desafíos compartiendo el tope, desalojarían unidades vigentes antes que a ellos | Baja: se arregla borrando lo no registrado |
| 5 | **`lecturas` se sobrescribe en cada uso**: guarda el tiempo de restauración (0,35 s), no el de la primera lectura; `aceptacion` (MTP) siempre vacía | Se perdió la medición del costo real de leer; «7.377 tok/s» en la tabla es restaurar, no leer | Baja, pero engaña al que lea la tabla |
| 6 | **Búsqueda semántica nunca activa**: `vectores` vacía porque el embebedor necesita Ollama (apagado); `_vector_consulta` devuelve None | Todos los resultados medidos son con búsqueda por palabras + grafo. No se sabe cuánto aporta la semántica | Media: variable no medida |
| 7 | **Extractor de Markdown**: 24 «secciones» cuyo nombre es una línea `=====` (subrayados), 14 duplicadas | Ruido en `simbolos` y en «dónde está»; no afecta al código | Baja |
| 8 | **Cuadernos**: en 2 `.ipynb` el contenido guardado (celdas extraídas) no corresponde al `sha` (del JSON crudo) | Por diseño; el invariante «contenido ↔ sha» no vale para cuadernos | Baja |
| 9 | **Tarjeta global congelada** dice 378 archivos; hay 380 (y 386 en disco hoy) | Es a propósito (congelarla evita invalidar los 94 estados), pero envejece sin aviso | Baja |
| 10 | **El banco va detrás del disco**: 6 archivos nuevos y 14 cambiados desde la última sincronización | Normal: se sincroniza al usarlo. El estudio debe sincronizar antes de medir | Nota de método |
| 11 | `resumenes` (0), `trabajo` (0): escritas pero nunca ejecutadas; `conocimiento` tiene 6 notas del modelo, una de ellas avisa que un hecho `lee_config` del banco es incorrecto | Funciones sin uso real; la nota confirma que el modelo detecta errores del banco | Baja |

**Correcciones para antes de E7** (medir con el banco contaminado invalidaría el estudio): excluir las
preguntas del examen de `resoluciones`, o correr el examen con la memoria de resoluciones desactivada, y
borrar las 203 filas del examen; borrar los 11 estados huérfanos; sincronizar el banco. Ninguna se
aplicó todavía: se deciden en la síntesis de E1–E6 para no cambiar el objeto de estudio a mitad del
estudio.

### E2. Exactitud de la extracción contra una verdad independiente (30/09/2026, sin modelo)

**Método.** Verdad externa: `jedi` 0.19 (análisis estático que resuelve cada llamada siguiendo imports,
clases y tipos; instalado en `~/.local`, no es dependencia de Prig) sobre una **instantánea del código
guardado en el banco** (no el disco actual, que ya cambió). Comparación **por arista** (quién llama →
a quién), que es lo que usan `llamadores`, `impacto` y `recorrido`; `Clase` y `Clase.__init__` son el
mismo destino. Donde jedi no puede juzgar o contradice al banco, **juicio manual** de muestras aleatorias
leyendo el código. Scripts en `docs/estudio-banco/` (`aristas.py`, `hechos.py`, `muestra.py`).

Dos errores del propio método que se corrigieron antes de concluir (quedan como aviso): comparar por
sitio de llamada contaba como «faltantes» las repeticiones (el banco guarda una arista por par
llamador→llamado, a propósito); y emparejar por línea de definición fallaba con decoradores (el banco
empieza el símbolo en el decorador, jedi en el `def`).

**Grafo Python (código de producción: 123 archivos, 20.029 llamadas; 12.983 van a librerías externas)**

| Confianza del banco | Aristas | Confirmadas por jedi | Contradichas | jedi no juzga → juicio manual | Precisión estimada |
|---|---|---|---|---|---|
| exacta | 2.875 | 2.824 | **0** | 51 → 20 de 20 correctas | **≈100 %** |
| aproximada | 382 | 250 | 1 | 131 → 16 de 18 correctas | **≈96 %** |
| única | 37 | 1 | 35 | 1 | **≈3 %** |
| **Total** | **3.294** | 3.075 | 36 | 183 | **≈98,5 %** |

- Los dos errores de «aproximada» enlazan a código de **tests** (`p.threads()` de psutil → un `Proc` de
  `test_ritmo.py`) o a una clase homónima (`descarga.cancel()` de Qt → `CodeRunner.cancel`).
- «Única» (nombre único en el lenguaje) enlaza **parámetros y variables locales** con métodos homónimos
  de otros módulos: `progreso(...)` → `Hub.progreso`, `autor()` → `hub/git.autor`, el builtin `all()` →
  `FeatureFlags.all`. Es la heurística que conviene quitar o restringir.

**Lo que falta (aristas que jedi encuentra y el banco no)**

| Hueco | Aristas | Causa |
|---|---|---|
| `obj.metodo()` con receptor de tipo no deducido | ~307 | instancia global (`book_service.get_book_citations`), atributo (`self.kb.buscar`), variable local construida (`session.execute`); con nombres repetidos en el proyecto (`get`, `load`, `delete`, o un endpoint homónimo) el banco no adivina: gana precisión, pierde aristas |
| llamadas a nivel de módulo | 59 | nunca se registran (no hay llamador «módulo»): `main()`, `PROVEEDORES = {"ollama": Ollama()}` |
| llamadas dentro de `lambda` | 31 | `_recorrer_sin_anidadas` no entra en `lambda` y la lambda no es símbolo |
| `self.x()` desde una función anidada y autollamadas recursivas | ~22 | el receptor `self` del cierre no se resuelve; la recursión no genera arista |

**Cobertura estimada**: ≈90 % de las aristas dentro de funciones y métodos, ≈88 % contando módulo y
lambdas. Resumen: **el grafo casi no inventa (≈98,5 % de precisión; ≈100 % sin «única») pero le falta
uno de cada diez enlaces**, casi todos a métodos de objetos globales o atributos. Consecuencia: `P.impacto`
y `P.llamadores` subestiman, sobre todo en `app.py` (usa instancias globales en todas partes). jedi
resuelve esos casos en ~220 s para todo el backend: un pase opcional con jedi recuperaría ~300 aristas.

**Grafo JavaScript (1.675 aristas)**: en el 100 % la llamada existe realmente en el cuerpo del llamador
(la identidad del destino no se pudo verificar con una herramienta externa; 420 «exactas» tienen
homónimos en otros archivos). **La línea de la arista es la de la función que llama, no la de la
llamada** (en Python es la de la llamada): la misma API devuelve significados distintos por lenguaje.

**Hechos**

| Hecho | Verdad independiente | Banco | Coinciden | Problema |
|---|---|---|---|---|
| `expone` (endpoints) | 372 (AST de decoradores + prefijo de `APIRouter`) | 374 | 343 | **los 29 endpoints del Hub sin el prefijo `/api/hub`** (`GET /estado` en vez de `GET /api/hub/estado`): `P.api` no los encuentra y el frontend que los llama nunca se enlaza con su función; +2 de tests |
| `lee_entorno` | 44 (AST de `os.environ`/`getenv`) | 43 | 43 | ninguno (la diferencia es una escritura) |
| `llama_api` (frontend) | 322 (toda cadena `/api/...` en JS/HTML) | 256 | 251 | **recall 78 %**: faltan casi todas las de `desafios.js` y otras URL armadas fuera de `fetch`; 5 rutas rotas por un ternario dentro de la plantilla |
| `lee_config` | muestra manual de 10 | 138 | ~5 de 10 | mezcla lecturas de configuración con `.get()` de cualquier diccionario (`loop_config`, `opciones`), escrituras (`config[...] = ...`) y tests |

**Qué significa para el examen (E6)**: las preguntas de tipo endpoint, frontend y config se generan
desde estos hechos. Donde el hecho está mal (Hub sin prefijo, `lee_config` que no es configuración), el
examen pregunta y corrige con el mismo error: el 98 % en «config» mide coherencia con el banco, no que
sean claves de configuración. Es la circularidad anunciada en el método, ahora con casos concretos.

**Correcciones propuestas (no aplicadas; se deciden al cierre de E1–E6)**: prefijo de routers en
`expone`; quitar o restringir «única» (nunca parámetros ni builtins; nunca hacia tests); registrar la
línea de la llamada en JS; aristas desde el módulo y dentro de lambdas; detectar URLs `/api/` en
cualquier argumento; `lee_config` solo sobre objetos de configuración conocidos y sin escrituras; pase
opcional con jedi para receptores de tipo inferible.

### E3. Partición y unidades (30/09/2026, sin modelo)

**Método.** La partición se reproduce en memoria con las funciones del propio módulo (sin escribir en el
banco) y se perturba de forma controlada: una función que crece 300 tokens (40 ensayos), una llamada
nueva entre dos piezas al azar (40), un archivo nuevo de 1.500 tokens con 3 llamadas (25), y los tamaños
reales de los últimos 30 commits de git. Una unidad cuenta como invalidada si cambia su texto (piezas,
orden o encabezados), que es lo que cambia su llave. Script: `docs/estudio-banco/particion.py`.

**Cómo funciona (lo que importa para los resultados)**: piezas = archivos de producción, y los que no
caben se cortan por símbolos de primer nivel (20 archivos partidos, 197 piezas); agrupamiento aglomerativo
con tope de 16K tokens por peso de llamadas (1), imports (2) y contigüidad en el archivo (3); orden de
lectura por dependencias (Tarjan + Kahn) y, a igualdad, lo más estable según git primero.

**Resultados**

| Medida | Valor | Lectura |
|---|---|---|
| Determinismo | sí: dos corridas dan exactamente la misma partición | condición para que las llaves sirvan |
| Tamaños | mín 8.041 · p25 11.212 · mediana 14.369 · p75 15.642 · máx 15.986 tokens | bien llenas: casi todas al 70–100 % del tope |
| **Cohesión real** | **70 %** de las llamadas quedan dentro de la unidad (3.267 dentro de la misma pieza + 192 entre piezas de la unidad; 1.512 cruzan) | el `peso_cortado: 0,847` guardado **exagera**: solo mide el peso entre piezas distintas y no ve las llamadas dentro de un mismo archivo, que son la mayoría |
| Prefijo fijo por estado | 3.765–9.566 tokens (mediana 6.000): sistema + tarjeta + herramientas + encabezados | un tercio de cada estado no es código |
| Modelo de disco | (código + 6.000) × 14,3 KB/token → **25,9 GB estimados contra 25,8 GB reales** | el modelo de costos es fiable para extrapolar (E10) |

**Estabilidad ante cambios**

| Perturbación | Unidades invalidadas (media · máx) | De rebote (no contenían lo tocado) | Sin rebote |
|---|---|---|---|
| una función crece 300 tokens | 1,2 · 4 | 0,2 · 3 | 34 de 40 |
| una llamada nueva | 0,75 · 7 | 0,57 · 6 | 33 de 40 |
| un archivo nuevo | 1,6 · 3 | 1,6 · 3 | 0 de 25 (siempre reacomoda algo) |
| **commits reales** (4,6 archivos de código en promedio) | **10,5 · 28** | 0,5 | 24 de 30 |

- No hay cascada: el agrupamiento es local y un cambio chico casi nunca reordena el resto.
- **Pero un commit típico invalida ~10 de las 94 unidades (11 %).** La causa principal no es la
  partición sino el **encabezado con números de línea** de las piezas de archivos partidos
  (`backend/app.py (lines 1200-1850)`, en `codigo_unidad`): una línea agregada arriba corre los números
  de todas las piezas siguientes y cambia el texto de todas sus unidades aunque su código sea idéntico.
  `app.py` está repartido en 6 unidades y aparece en 30 de los commits recientes; `youtube_hub.js`, en 6
  unidades y 19 commits.
- Costo por commit típico: releer ~10 × ~19K tokens ≈ 200K tokens (4–5 min a ~700 tok/s) y escribir
  ~3 GB de estados nuevos. Los viejos quedan huérfanos hasta el desalojo: **los 11 huérfanos de E1 son
  exactamente el rastro de un commit**.

**¿Cuántas unidades necesita cada pregunta del examen?** (cada nombre de la pregunta y de la respuesta
esperada, ubicado en la unidad que contiene su línea de definición)

| Tipo | 1 unidad | 2 | 3+ |
|---|---|---|---|
| ubicación, constante, endpoint, config | 55 de 68 | 5 | 1 |
| entorno, frontend, llamadores | 31 de 51 | 13 | 7 |
| **impacto** | 4 de 17 | 8 | 5 |
| **recorrido** | **0 de 17** | 5 | **12** |
| **Total** | **96 (63 %)** | 31 | 25 |

Coincide con lo observado: el enrutador elige modo unidad en ~70 % de las preguntas, y **impacto y
recorrido** (los que cruzan unidades) son los lentos (5–8 min) y los más débiles del examen. Con una sola
unidad restaurada, lo que cruza depende de la consola y del grafo, y el grafo tiene ~10 % de aristas
faltantes (E2): las dos debilidades se suman en las mismas preguntas.

**Otros topes (simulados; el disco con el modelo validado)**

| Tope | Unidades | Llamadas dentro | Disco | Contexto de un estado (código + prefijo) |
|---|---|---|---|---|
| 8K | 186 | 56 % | 33,8 GB | ~13K |
| **16K (actual)** | **94** | **70 %** | **25,9 GB** | ~21K |
| 24K | 62 | 76 % | 23,1 GB | ~30K |
| 32K | 49 | 82 % | 22,0 GB | ~38K |

Unidades más grandes: más cohesión y menos disco (el prefijo fijo se repite menos). Pero a 24K el estado
ya ocupa ~30K de los 32K de contexto con que el motor rinde bien, sin lugar para pregunta, consola y
respuesta, y 32K excede la ventana medida. El tope de 16K es razonable; 20K sería el único punto
intermedio a probar, y solo si E4 muestra margen de VRAM y velocidad.

**Correcciones propuestas (no aplicadas)**

1. **Encabezados sin números de línea** (por ejemplo, del primer al último símbolo de la pieza): un commit
   típico pasaría de invalidar ~10 unidades a invalidar solo las que contienen el código cambiado. Es la
   de mayor efecto sobre el costo de mantener el banco vivo.
2. **Borrar los estados anteriores al reemplazarlos** (o marcarlos para desalojo inmediato) en vez de
   esperar al tope.
3. Corregir la métrica `peso_cortado` (incluir las llamadas dentro de una misma pieza) para que el número
   guardado no engañe.
4. Para impacto y recorrido: dar al modelo las **vecinas** de la unidad (ya se calculan, con una
   cobertura de 0,94) o un modo de varias unidades; y completar el grafo (E2) antes de exigirle más al
   modelo.

### E4. Motor y máquina (30/09/2026, con el modelo ~5 min)

**Método.** Anatomía del estado por regresión sobre los 94 estados reales. Medición controlada sobre una
unidad real de 14–15,5K tokens de código (`frontend/js/modelos.js`, 20.034 tokens con el prefijo): leer
desde cero + pregunta con muestreo determinista (temperatura 0), guardar, borrar, restaurar desde disco en
frío (archivo sacado de la caché de páginas con `posix_fadvise`) y en caliente, y repetir la pregunta. Un
control separa el efecto de restaurar del de leer en dos pasos. Estados de prueba propios, borrados al
final. Scripts: `docs/estudio-banco/motor.py` y `motor_control.py`.

**Qué hay dentro de un estado guardado** (ajuste sobre 94 estados, R² = 1,00000, error máx < 0,01 MB):

`bytes = 10.904 × tokens + 65,9 MB`

- 10.904 B/token = KV en q8 de las **10 capas de atención** (la arquitectura predice 10.880: 2 cabezas KV
  × 256 × K y V × 34/32 bytes; la diferencia, ~24 B/token, son metadatos).
- 65,9 MB fijos = **estado recurrente de las 30 capas DeltaNet**, independiente del largo.
- **No incluye el KV de la capa MTP**. Aun así, la aceptación del MTP tras restaurar es la misma que tras
  leer (67,5 % frente a 68,7 %; ver abajo): no hace falta guardarlo.
- Consecuencia práctica: un estado de N tokens pesa 66 MB + 10,9 KB × N. El «14,3 KB/token» de E1 era un
  promedio que incluía la parte fija.

**Restauración: exacta**

| Comparación (misma unidad, misma pregunta, temperatura 0) | ¿Respuesta idéntica? |
|---|---|
| leer de una vez, dos veces | sí |
| leer en dos pasos (prefijo, luego pregunta), dos veces | sí |
| **dos pasos sin guardar ↔ guardar, borrar y restaurar** | **sí: bit a bit** |
| leer de una vez ↔ leer en dos pasos | no (841 frente a 632 caracteres) |

La restauración reproduce exactamente el estado. Que leer de una vez dé otro texto se debe al **reparto en
lotes de la GPU** (el prefijo y la pregunta juntos o separados cambian la aritmética de punto flotante y,
con muestreo voraz, el texto se bifurca): es una propiedad de la inferencia, no de la caché. Nota de
método para E7: una respuesta solo es reproducible con la misma forma de leer.

**Tiempos y velocidades**

| Operación | Medido |
|---|---|
| arrancar el motor (24 expertos calientes por capa, MTP, contexto 32K) | 14,7 s |
| leer 20.034 tokens | 32,0 s (**626 tok/s**) |
| guardar el estado (284 MB) | 0,13 s |
| **restaurar en frío** (desde el NVMe) | **0,22 s** (el disco lee a 1.547 MB/s: 0,18 s de los 0,22) |
| **restaurar en caliente** (desde la caché de páginas en RAM) | **0,09 s** |
| leer la pregunta tras restaurar (31 tokens) | ~0,6 s |
| generar con 20K tokens de contexto | **31,1 tok/s** (lo mismo tras leer o tras restaurar) |
| aceptación del MTP | 68,7 % tras leer (103 de 150) · 67,5 % tras restaurar (85 de 126) |

- Restaurar es ~150 veces más rápido que leer (0,22 s frente a 32 s), y **ni en frío es el cuello de
  botella**: el tiempo de una respuesta lo pone la generación (5 s para ~150 tokens).
- La generación a 20K de contexto (31 tok/s) es más lenta que los 38–42 tok/s medidos antes con contexto
  corto: las 10 capas de atención recorren todo el KV en cada token. A más contexto, respuestas más lentas.

**VRAM y temperatura**: 15 MB en reposo → **5.071 MB** con el motor cargado → 5.217 MB en uso, sobre un
tope útil de ~5.770 MB (queda ~550 MB: el motor ya elige cuántos expertos calientes caben). La GPU pasó de
38 °C a 55 °C y de 7 W a 32 W en ~2 minutos de trabajo: lejos de los límites; el gobernador térmico no
tuvo que intervenir.

**Ley de escala** (con el modelo de disco validado en E3 y los 626 tok/s medidos)

| Proyecto | Tokens leídos (código + prefijos) | Primera lectura | Disco de estados | Cabe hoy |
|---|---|---|---|---|
| Prig (1×) | ~2,0 M | ~52 min | 25,8 GB | sí |
| 5× Prig | ~10 M | ~4,4 h | ~129 GB | justo (190 GB libres) |
| 10× Prig | ~20 M | ~8,7 h | ~258 GB | **no** |
| desafío-proyecto (20–40 archivos) | 50–120K | 1,5–3 min | 0,7–1,6 GB | sí |

El límite no es la velocidad ni la GPU: es **el disco por token** (10,9 KB) más el prefijo repetido (E1).
Para repositorios grandes hacen falta niveles: guardar solo los estados de las unidades más usadas y
releer el resto bajo demanda (32 s por unidad), compartir el prefijo, o ambas.

### E5. Consola P: corrección y límites (30/09/2026, sin modelo)

**Método.** La consola real sobre el banco real, solo con métodos de lectura (sin `anotar`, `afirmar` ni
`guardar`, que escriben), con casos cuya respuesta se conoce por E2 o por SQL directo. Los límites se
prueban con usos normales exagerados (un bucle que no termina, una salida enorme, una lista enorme). La
seguridad se revisa de forma defensiva, leyendo la configuración; no se escribieron intentos de romper
el aislamiento. Script: `docs/estudio-banco/consola.py`.

**Corrección**

| Caso | Resultado | Veredicto |
|---|---|---|
| `P.api("POST /api/ai/chat")` | 1 función que lo expone (`ai_chat`), 5 consumidores | correcto |
| `P.api("GET /api/hub/estado")` (ruta real) | **0 que lo exponen**, 1 consumidor en el frontend | **error heredado de E2**: el endpoint quedó guardado como `GET /estado`, así que el enlace frontend → backend del Hub está roto |
| `P.llamadores("BancoProyecto.conectar")` | 37 | coincide con SQL (37) |
| `P.codigo("generar.elegir")` (función anidada) | el código con sus líneas | correcto |
| `P.camino("ai_chat", "BancoProyecto.registrar_resolucion")` | `ai_chat → _chat_eventos → registrar_resolucion` | correcto |
| `P.impacto("BookService.get_book_citations")` | 4 llamadores, 1 endpoint (`POST …/export`) | **incompleto**: omite `GET /api/books/citations`, que lo llama directamente vía la instancia global `book_service`: la arista que falta en E2. «Qué se rompe si cambio esto» sale corto |
| `P.llamadores("get")` (nombre muy repetido) | 10 llamadores de **una** función `get` de `ide.js` | **ambigüedad resuelta en silencio**: si existe un símbolo con ese nombre exacto gana, y los métodos `X.get` del resto del proyecto quedan fuera sin aviso (la ayuda promete pedir el nombre completo si hay varios) |
| `P.donde("moe_contexto")` | incluye un test entre los que «leen la configuración» | ruido heredado de `lee_config` (E2) |
| `P.donde("PRIG_BANCOS")` | 1 lectura + 3 apariciones literales | correcto |
| `P.simbolos(nombre="=====…")` | 24 | los títulos basura del Markdown (E1) son visibles para el modelo |
| `P.sql` de lectura / con `DELETE` | 6.816 / rechazado («solo consultas SELECT») | correcto |
| variables entre ejecuciones | persisten (`41` → `42`) | correcto |

**Límites** (todos funcionan y la consola sigue viva después)

| Uso excesivo | Respuesta |
|---|---|
| bucle que no termina | cortado a los 30 s con un mensaje que sugiere dividir el trabajo |
| salida de 100.000 caracteres | recortada a 6.000 con aviso del tamaño real |
| lista de ~3 GB | «Sin memoria (tope 2048 MB)» |

Detalle: la variable `PRIG_CONSOLA_ALARMA` (documentada para cambiar el tiempo) **no tiene efecto**: el
proceso padre la fija en 30 al lanzar el aislado.

**Revisión defensiva del aislamiento**

Capas que existen: revisión estática del código (sin nombres ni atributos que empiecen con `_`, sin
builtins peligrosos, imports solo de una lista corta); lista blanca de builtins; proceso aparte con Python
aislado (`-I`), entorno mínimo, `cwd=/` y sesión propia; base abierta en solo lectura y `P.sql` limitado a
SELECT; topes de memoria, tiempo y salida; las escrituras (`anotar`, `afirmar`, `guardar`) no las hace el
proceso aislado sino Prig, a pedido y con número de petición.

Límite del diseño: es un aislamiento **a nivel de lenguaje** dentro de CPython, sin barreras del sistema
operativo (el proceso corre como el usuario, con acceso al sistema de archivos y a la red si se sortean
las comprobaciones estáticas). Con el modelo de amenaza actual (el único autor del código es el modelo
local, respondiendo al propio usuario) el riesgo es bajo: un error del modelo, no un atacante. Si la
consola se abriera a código de terceros (por ejemplo, desafíos compartidos o repos descargados que
pudieran inducir al modelo), conviene sumar una capa del sistema operativo: usuario sin privilegios o
espacio de nombres propio, sin red, y topes de procesos y de tamaño de archivo.

**Correcciones propuestas (no aplicadas)**: avisar de la ambigüedad cuando un nombre exacto convive con
otros por nombre corto; respetar `PRIG_CONSOLA_ALARMA` (o quitar la documentación); las correcciones de
E2 (prefijo del Hub, receptores globales) arreglan `api` e `impacto`; excluir los tests de `lee_config`;
capa de aislamiento del sistema operativo antes de exponer la consola a código externo.

### E6. Validez del examen (30/09/2026, sin modelo)

**Método.** Lectura del corrector (`examen_proyecto.corregir`); auditoría manual de 40 respuestas elegidas
al azar de la corrida final, juzgadas contra el código; recorrección con el corrector real de los casos
dudosos; comparación pareada de corridas sobre las mismas preguntas; construcción de un examen con verdad
independiente. Script del examen nuevo: `docs/estudio-banco/examen_independiente.py`.

**Cómo puntúa el corrector**: el puntaje es la **fracción de los elementos esperados que aparecen en el
texto**. No penaliza lo que sobra (una lista con 20 candidatos saca 1,0 si incluye los esperados); los
«inventos» (nombres que no existen) se detectan pero **no restan**; en «ubicación» alcanza con que aparezca
el nombre del archivo en cualquier parte; en «valor», con que el número aparezca en cualquier lugar.

**Auditoría de 40 respuestas**

| | Casos | Detalle |
|---|---|---|
| Respuesta correcta según el código | **38 de 40 (95 %)** | los 2 errores: endpoints que `P.api` no encontraba por el bug del método (ya corregido) |
| Puntaje medio que les dio el corrector | 92,9 % | el corrector fue **más severo** que la verdad |
| Falsos positivos del corrector (puntúa bien una respuesta mala) | **0** | en esta muestra las respuestas no «disparan» listas largas para ganar puntos |
| Falsos negativos | 2 | n.º 5: `BookLibraryManager.promptAddProject` no cuenta como `promptAddProject` (el borde con punto es a propósito; afecta a 1 respuesta de 102); n.º 37: el esperado estaba mal |
| **Preguntas con la respuesta esperada defectuosa** | **5 de 40 (12,5 %)** | esperado impreciso (lee en `_ajustes`, no en `embeber`), **incompleto** (falta `_load_config`; `radiografia` tiene más endpoints que los del banco), incluye una **escritura** como lectura (`_save_last_workspace`), o la pregunta usa una **ruta que no existe** (`POST /manifiesto`, sin el prefijo del Hub) |
| Respuestas **mejores que la esperada** | 4 | el modelo leyó el código y corrigió al banco; el corrector no puede verlo (salvo cuando le resta, como en el n.º 37) |

Es la circularidad anunciada, medida: en una de cada ocho preguntas la «verdad» del examen hereda un
error del banco (E2), y en esas el modelo suele tener razón y el examen no lo registra.

**Comparaciones entre corridas: mezclaban preguntas distintas.** El examen se regenera cuando cambia el
código y las corridas guardan solo el id de la pregunta: la del 97,7 % y la final comparten **34
preguntas**. Sobre esas 34: 100 % antes, 96,1 % en la final; las dos diferencias son el esperado
equivocado (n.º 37) y un endpoint del bug de `P.api`. **La «regresión» de 97,7 % a 90,6 % era sobre todo
un cambio de preguntas** (la final incluía impacto y estaba afectada por el bug de `P.api` en todos los
endpoints), no un empeoramiento del sistema.

**Qué no mide el examen**: los 9 tipos son búsquedas estructurales (dónde, quién llama, qué endpoint, qué
valor). No mide entender lo que el código **hace** (seguir la ejecución), el **por qué** de una decisión,
encontrar **errores**, ni predecir el efecto de un cambio y comprobarlo. Tampoco nada que esté fuera de
las unidades (tests, documentación, HTML y CSS: E1).

**Examen independiente (27 preguntas, para E7)**: la verdad no sale del banco.

| Tipo | Preguntas | De dónde sale la respuesta correcta |
|---|---|---|
| ejecución: «sin ejecutarlo, ¿qué devuelve…?» | 13 | ejecutando la función (incluye casos con trampa, como `_aparece("guardar", "Hub.guardar()")` → `False`) |
| llamadores donde el banco pierde aristas | 4 | jedi (`get_references`), no el grafo; si el llamador se llama igual que el destino, se exige su archivo |
| endpoints del Hub con su ruta real | 4 | decorador + prefijo del `APIRouter` (AST) |
| diseño («por qué») | 6 | rúbrica escrita leyendo el código y sus docstrings; corrección manual |

### Revisión crítica de E1–E6 (30/09/2026): lo que estaba mal o mal ponderado

Se revisaron las conclusiones anteriores contra mediciones nuevas. **Estas correcciones prevalecen sobre
lo escrito en E1–E6.** Scripts nuevos: `invalidacion_real.py` y `velocidad_contexto.py`.

| Afirmación anterior | Qué se comprobó | Corrección |
|---|---|---|
| E1: «111 respuestas guardadas de preguntas que puntuaron 0»; contaminación de gravedad **alta** | el recuento usaba el prefijo de 60 caracteres y las preguntas son plantillas: una resolución coincidía con decenas de preguntas | con coincidencia exacta: 192 resoluciones de preguntas del examen actual, **7** con 0 en la final. Además, **en modo unidad (~70 %) las resoluciones no se inyectan** (el texto de `componer()` se descarta; solo el modo general las pone en el prompt). Gravedad **media**. Efecto secundario: `componer()` se calcula en cada pregunta aunque en modo unidad se tire |
| E1: la tarjeta repetida es el 27 % del disco y un prefijo compartido la ahorraría | se usó 14,3 KB/token (promedio con la parte fija); el costo marginal es 10,9 KB (E4) | desglose real: código 53 %, **estado SSM fijo 24 %** (66 MB × unidad, omitido antes), tarjeta 21 %, resto 3 %. Con el formato de guardado de llama.cpp **compartir el prefijo no ahorra disco** (cada estado guarda todos sus tokens). Lo que reduce disco: menos unidades (más grandes) o tarjeta más corta; da más peso a probar un tope de ~20K |
| E3: un commit invalida ~10 unidades «por los números de línea»; quitarlos es «la corrección de mayor efecto» | la simulación invalidaba por construcción (cambiaba los tokens de todas las piezas del archivo). Medición real: una copia del banco sincronizada con los cambios de una sesión de trabajo | la sesión invalida **24 de 94 unidades** (26 %, ~322K tokens, ~8,5 min de relectura); **sin números de línea, 23**: el efecto de los encabezados es despreciable. De las 23: 17 conservan sus archivos (su código cambió de verdad) y 6 se reagruparon. El costo es mayormente inherente a editar; lo que ayuda es **releer bajo demanda** y una **partición incremental**, no los encabezados |
| E2: quitar o restringir la heurística «única» (≈3 % de precisión) | los 3 % eran de Python; en JS hay 224 aristas «única» que no se habían juzgado | en JS «única» acierta ~10 de 12 (llamadas a gestores globales `window.xMgr.metodo()`); falla solo cuando hay una función local homónima. **Quitarla rompería ~180 aristas buenas**: restringirla en Python y, en JS, no usarla si hay definición local con ese nombre |
| E2: cobertura del grafo ≈90 % | jedi no resuelve 3.011 llamadas (dinámicas) | el 90 % es **respecto de lo que jedi ve**: es una cota superior; la cobertura real es menor y desconocida |
| E4: 31 tok/s a 20K «porque la atención recorre más memoria» | no se había controlado | con 377 tokens de contexto: 36,8 tok/s; con 20K: 31,0 (−16 %); aceptación del MTP 77 % frente a 69 %. Confirmado. Las mediciones de E4 son de **una** unidad (n = 1) |
| E5: «cientos de métodos `X.get`» | recuento | son **9** símbolos con nombre corto `get`; el problema (elige 1 de 9 sin avisar) sigue |
| E6: «la regresión 97,7 → 90,6 % no existió» | se mezclaron dos cosas | la caída 97,7 → 90,6 comparaba preguntas distintas; **pero la regresión de la etapa 3 fue real**: sobre las mismas 55 preguntas, 81,8 % (etapa 3) frente a 93,9 % (final), y 9 de sus 10 ceros eran respuestas que eran solo código `P.…`. Se corrigió |
| E6: «95 % de respuestas correctas» | representatividad de la muestra | la corrida final no incluía llamadores, recorrido ni ubicación: **los tipos más difíciles no se auditaron**. El 95 % vale para config, endpoint, entorno, frontend, constante e impacto; las respuestas se juzgaron sobre 650 caracteres (algunas truncadas) |

**Omisiones de fondo (no son errores de medición, sino cosas que no se miraron)**

1. **Todo se midió sobre Prig**, el código contra el que se diseñaron y ajustaron las heurísticas del
   banco (verbos comunes, resolución de receptores, tipos del examen). Nada garantiza los mismos números en
   un proyecto ajeno. El banco que el usuario usa en el chat es otro (`~/Escritorio/Python`, 24 archivos,
   29K tokens) y nunca se evaluó; los desafíos-proyecto usarían repositorios externos. **Falta un examen
   sobre al menos un repositorio que no sea Prig.**
2. **La usabilidad** quedó en segundo plano: la mediana de 18 s por respuesta es buena, pero las preguntas
   de impacto tardan 5–8 min, `sincronizar()` y `componer()` corren en cada pregunta, y un motor frío
   suma 15 s de arranque. Es lo que el usuario percibe, y no se midió de forma sistemática.
3. **La tarjeta global congelada** es el 21 % del disco y describe el proyecto de cuando se congeló; no se
   midió cuánto envejece ni si confunde al modelo.
4. **Método**: en esta revisión aparecieron 5 afirmaciones equivocadas o exageradas, todas por conclusiones
   sacadas sin un control (una simulación que invalidaba por construcción, un recuento por prefijo, una
   muestra no representativa). Para E7–E9: cada conclusión con su control, y las mediciones repetidas.
5. **Seguridad** (E5): se revisó solo la configuración; no se hizo una prueba adversarial del aislamiento.

### Cierre de E1–E6: qué corregir antes de medir con el modelo

Medir en E7–E9 sin corregir esto repetiría errores ya conocidos. Correcciones propuestas, en orden:

1. **Aislar la medición** (imprescindible): correr el examen sin la memoria de resoluciones, borrar las
   203 filas que son preguntas del examen, sincronizar el banco, guardar el texto de cada pregunta junto a
   su resultado (no solo el id) y borrar los 11 estados huérfanos (E1).
2. **Arreglar los hechos que envenenan el examen**: prefijo de routers en `expone` (Hub), `lee_config` solo
   sobre objetos de configuración y sin escrituras ni tests, URLs `/api/` en cualquier argumento (E2).
3. **Grafo**: restringir «única» en Python (nunca parámetros, builtins ni tests) y en JS no usarla si hay
   una definición local homónima; aristas desde el módulo y dentro de lambdas; línea de la llamada en JS;
   pase opcional con jedi para receptores globales y atributos (E2 y revisión crítica).
4. **Estabilidad y costo**: releer las unidades bajo demanda en vez de todas; partición incremental (ubicar
   lo nuevo sin reagrupar lo que no cambió); borrar los estados reemplazados; no calcular `componer()` en
   modo unidad. (Quitar los números de línea de los encabezados: efecto despreciable, 24 → 23.)
7. **Generalización**: armar el mismo examen (y el independiente) sobre un repositorio que no sea Prig.
5. **Consola**: avisar la ambigüedad de nombres; respetar `PRIG_CONSOLA_ALARMA` (E5).
6. **Corrector**: penalizar los inventos (o reportar precisión aparte de cobertura) y marcar las preguntas
   cuyo esperado no se verificó fuera del banco (E6).

Las 1 y 2 son condición para que E7 mida algo válido; las 3–6 mejoran el sistema y conviene medirlas
después con el mismo examen, para ver su efecto (antes y después).

### Correcciones aplicadas (30/09/2026) y primera prueba de generalización

**Aplicado** (respaldo previo del banco: `~/.cache/prig-estudio/banco-Prig-respaldo-2026-09-30`):

1. **Medición aislada**: `AIChatRequest.memoria` (por defecto `True`); con `False`, `componer()` no inyecta
   respuestas anteriores y la respuesta no se guarda. Borradas del banco de Prig las 313 resoluciones y las 6
   notas de conocimiento (**todas** venían de corridas del examen: ninguna de un uso real del chat). Borrados
   11 estados huérfanos (3,0 GB). Cada resultado del examen guarda ahora su tipo, pregunta y esperado.
2. **Hechos** (`VERSION_ESQUEMA = 6`, reindexa todo): prefijo de `APIRouter`/`Blueprint` en `expone`;
   `route(..., methods=[...])` genera un hecho por método; `lee_config` solo sobre objetos que se llaman
   `config`/`cfg`/`ajustes`/`settings` (no `loop_config` ni `opciones`), sin escrituras ni tests;
   `llama_api` con cualquier cadena `/api/...`; en `ruta_http_canonica`, los `${...}` se resuelven antes de
   cortar en `?` y uno pegado al final de un segmento es una consulta opcional.
3. **Emparejamiento por sufijo** (`banco_proyecto.endpoint_de`), usado en `P.api` y en el examen: el backend
   expone `/items` y el frontend llama a `/api/v1/items` cuando el prefijo se pone en otro archivo
   (`include_router(..., prefix=settings.API_V1_STR)`, `register_blueprint`).

**Verificación independiente sobre el banco de Prig ya reindexado** (mismo método de E2):

| Hecho | Antes | Después |
|---|---|---|
| `expone` | 343 de 372 (Hub sin prefijo) | **378 de 378** (sobran 2 de tests) |
| `llama_api` (frontend) | 251 de 322 | **328 de 328** |
| rutas del frontend que encuentran su endpoint | — | 271 de 278 |
| `lee_config` | 138 (≈50 % correctos, con tests y escrituras) | 85, ninguno en tests ni escrituras |
| `lee_entorno` | 43 | 42: `CUDA_VISIBLE_DEVICES` y `QTWEBENGINE_CHROMIUM_FLAGS` salieron porque son **escrituras** (y la pregunta vieja del examen sobre `CUDA_VISIBLE_DEVICES` tenía el esperado mal) |

Suite: 980 pruebas; fallan solo las 3 intermitentes conocidas (`test_motor_suave`, `test_troceado`), que
pasan solas. Pruebas nuevas en `test_banco_proyecto.py` (`TestHechosCorregidos`, `TestEndpointPorSufijo`,
memoria de resoluciones).

**Repositorio externo: `fastapi/full-stack-fastapi-template`** (commit `cb740b6`; backend FastAPI en Python,
frontend React + TypeScript; 193 archivos; banco en `~/.cache/prig-estudio/bancos`, separado de los del
usuario)

| Medida | Resultado |
|---|---|
| Indexar + particionar | 0,6 s · **8 unidades** (95K tokens de código) · cobertura de vecinas 1,0 |
| Tipos del examen que se pueden generar | **5 de 9** (83 preguntas): endpoint, frontend, llamadores, ubicación, impacto. Faltan config y entorno (la configuración es `pydantic-settings`: `settings.SECRET_KEY`, patrón que el banco no reconoce), constantes y recorrido |
| Enlace frontend ↔ backend | sin el emparejamiento por sufijo, **ninguno** (prefijo en otro archivo); con él, `P.api("/api/v1/items/*")` da 3 funciones y 4 consumidores |
| Grafo Python contra jedi | 65 aristas «exacta», **todas confirmadas**; faltan 5 (nivel de módulo). La precisión se mantiene fuera de Prig (muestra chica) |
| **Grafo del frontend React/TS** | **29 aristas** frente a **392 usos de componentes propios en JSX y 214 llamadas a funciones propias**: cubre ~5 %. JSX (`<ItemsTable />`) y hooks no se reconocen como llamadas y los imports de ES no se resuelven. En Prig el frontend funciona porque es JS sin framework con gestores globales |

Conclusión de generalización (sin modelo todavía): la parte Python generaliza bien; **el frontend moderno
(React/TS) queda casi ciego** y la configuración con `pydantic-settings` es invisible. Para desafíos-proyecto
sobre repositorios React/TS, esto hay que resolverlo antes (JSX como llamada, imports de ES). No se agregaron
esas heurísticas ahora a propósito: se ajustarían a un solo repositorio (el mismo sesgo de sobreajuste que la
revisión crítica señaló).

**Bug encontrado al lanzar E7: la pasada pisaba sus propios registros.** Tras reparticionar (96 unidades,
números corridos) la pasada arrancó con **5 de 96 vigentes** cuando las llaves de **66** coincidían con
lecturas guardadas. Causa: `lecturas` tiene como clave el número de unidad y la pasada reasignaba unidad por
unidad con `INSERT OR REPLACE`, pisando el registro de otra unidad todavía válida que aún no se había
procesado. Los estados seguían en disco (el motor los restauraba en 0,4 s por el contenido del prefijo),
así que no se perdía lectura ni disco, pero **se regeneraba el resumen de cada unidad** (~25–30 s del
modelo escribiendo, ~30 min en total). Arreglo: `LectorUnidades.reasignar()` reasigna todas las lecturas
reutilizables de una vez al empezar la pasada. Prueba nueva (`test_pasada_tras_renumerar_no_pisa_registros`),
que falla sin el arreglo. Aplicado al banco real: 66 de 96 vigentes sin usar el modelo.

Esto corrige también la medición de invalidación de la revisión crítica: sobre la copia se contaron 23
unidades inválidas por contenido; en el banco real hay 30 (el reindexado del esquema 6 y la sincronización
posterior incluyen los archivos de este mismo estudio).

**¿Los problemas encontrados afectaron a las pruebas anteriores?** (verificado con el respaldo del banco)

- **Contaminación por memoria**: en la corrida final, las preguntas con una respuesta previa guardada (misma
  pregunta, fecha anterior) sacaron 0,947 y las demás 0,840; pero dentro de cada tipo los grupos casi no se
  superponen (config y constantes: 100 % con previa; frontend e impacto: 0 %), así que **la diferencia la
  explica el tipo y el efecto no se puede medir con esos datos**: ni demostrado ni descartado. En la corrida
  del 97,7 %, las 34 preguntas recuperables no tenían respuesta previa. La prueba limpia es E7 sin memoria.
- **Hechos equivocados en el esperado**: recorrigiendo las respuestas de la corrida final con el esperado
  recalculado desde el banco corregido, config pasa de 0,970 a 1,000 y entorno y frontend quedan iguales:
  **los puntajes no estaban distorsionados**. Pero **7 de las 34 preguntas de config y entorno (20 %) no
  preguntaban por una lectura real** (`target`, `temperature`, `modulos`, opciones de Qt; `CUDA_VISIBLE_DEVICES`
  era una escritura): el examen viejo medía en parte otra cosa.
- **La regla nueva de `lee_config` tiene un falso negativo**: `ollama_url` se lee de verdad como configuración,
  pero a través de variables llamadas `new_cfg` y `saved`, que la regla por nombre ya no reconoce. Decidir qué es
  «configuración» por el nombre de la variable tiene un límite; queda anotado, sin ajustar la regla a este caso.
- **El bug de la pasada** afectó solo a la relectura (resúmenes regenerados), no a respuestas del examen.

**E7 por lotes** (pedido del usuario: pruebas más cortas y verificadas). `docs/estudio-banco/lote.py`: el
plan se congela (180 preguntas de Prig en 15 lotes de 12, 83 del externo en 7; cada lote mezcla todos los
tipos) y cada lote se corre por separado con **chequeos previos** (banco sin cambios desde el plan, examen no
regenerado, memoria vacía, unidades vigentes, sin otro motor, GPU fría) y **verificación posterior**
(resultados completos con su pregunta, sin respuestas vacías ni con error, memoria sin escrituras, modo
registrado, puntaje recalculado igual al guardado, sin estados nuevos en disco, comparación con la corrida
final para la misma pregunta). Un lote que no pasa la verificación no se cuenta y se revisa antes de seguir.
Informes en `~/.cache/prig-estudio/e7/<repo>_loteNN.json`.

### E7 por lotes — informe del lote 1 (30/09/2026, 15:26–15:36)

**Antes de correr: dos problemas más de infraestructura, encontrados y corregidos**

1. **El tope de disco desalojaba estados válidos y conservaba basura.** Al releer 30 unidades, el desalojo por
   antigüedad (tope 32 GB) borró los 6 estados válidos más viejos (unidades 0, 1, 2, 3, 8, 9) mientras
   quedaban en disco 28 estados viejos de las unidades releídas (7,6 GB) que ya no servían. Arreglo:
   `reasignar()` borra el estado de cada lectura descartada (salvo que otra vigente lo use); prueba nueva
   `test_reasignar_borra_los_estados_que_ya_no_sirven`. Limpieza: 118 → 90 estados; después de releer, 97
   estados (26,7 GB) y **0 huérfanos**.
2. **Medir un proyecto mientras se lo modifica.** Mis arreglos (en `lectura_unidades.py`, sus pruebas, y los
   scripts del estudio en `docs/estudio-banco/`, que el banco cuenta como código de producción) invalidaban
   unidades y cambiaban la versión del banco. El chequeo previo de los lotes ahora usa una **huella del código de
   producción** (no la versión global: documentos e informes pueden cambiar sin invalidar nada) y el código queda
   congelado durante E7. Huella: `c0ec1880799e807c`. Lección de método: el `pgrep -f`/`pkill -f` coincide con el
   propio comando que lo contiene (me pasó dos veces): usar PID.

Estado al empezar el lote 1: banco versión 13 (luego 14 solo por documentos), 97/97 unidades vigentes, memoria
vacía (0 resoluciones, 0 notas), examen de 153 preguntas con los 9 tipos, plan de 15 lotes.

**Lote 1: 12 preguntas (8 del examen del banco + 4 del independiente), 580 s, verificación automática OK**

| Pregunta | Tipo | Modo | Tiempo | Puntaje automático | Juicio manual |
|---|---|---|---|---|---|
| clave de configuración | config | — | ~30 s | 1,0 | — |
| constante | constante | — | 27 s | 1,0 | — |
| `POST /api/hub/ajustes` | endpoint | general | 39 s | 0,5 | **0**: respondió `Hub.ajustes` en `servicio.py` (el método al que delega), no la función del endpoint (`crear_router.ajustes` en `hub/api.py`); el corrector dio medio punto por el nombre corto |
| variable de entorno | entorno | — | 30 s | 1,0 | — |
| frontend | frontend | — | 16 s | 1,0 | — |
| impacto | impacto | — | 3 min 16 s | 1,0 | — |
| llamadores | llamadores | — | 16 s | 1,0 | — |
| recorrido | recorrido | — | 1 min 17 s | 1,0 | — |
| `ind_23` ¿por qué el estado exacto? | diseño | general | 36 s | (rúbrica) | **1,0**: las SSM no retroceden; un estado no sirve para otro sufijo |
| `ind_07` `_carpeta(…, 1)` | ejecución | — | 22 s | 1,0 | correcto |
| `ind_18` `GET /api/hub/estado` | endpoint real | — | ~60 s | 1,0 | correcto (el arreglo del prefijo funciona) |
| `ind_15` llamadores de `delete_item` | llamadores (jedi) | unidad | 18 s | 0,0 | **0**: consultó `P.llamadores`, el grafo no tiene la arista (la llamada pasa por la instancia global `book_service`) y **afirmó que nadie la llama**; la llama `delete_book` en `app.py` |

Modos: 6 unidad, 6 general. Media automática 0,864 (11 con puntaje); con el juicio manual, **10 de 12 correctas
(83 %)**. Sin diferencias con la corrida final en las preguntas comunes.

**Lo que muestra este lote** (n = 12: es una señal, no una medida; hacen falta los 15 lotes)

- El sistema responde bien los tipos que la auditoría de E6 no había cubierto (llamadores, recorrido, impacto) y
  las preguntas de verdad independiente de ejecución y diseño.
- **Los huecos del grafo (E2) se convierten en respuestas falsas y seguras de sí**: el modelo confía en
  `P.llamadores` y no lo contrasta con `P.grep`. Es el riesgo más importante para revisar código (y para los
  desafíos): «nadie llama a esto» dicho con seguridad y equivocado.
- El corrector sigue siendo permisivo con los nombres cortos (endpoint 0,5 cuando la respuesta era otra función).

**Cómo retomar** (desde `/home/ama-gi/Prig`):

```
.venv/bin/python docs/estudio-banco/lote.py estado prig          # qué lotes están hechos
.venv/bin/python docs/estudio-banco/lote.py correr prig 2        # el siguiente (≈10 min); se verifica solo
PRIG_BANCOS=~/.cache/prig-estudio/bancos .venv/bin/python backend/lectura_unidades.py --pasada ~/.cache/prig-estudio/repos/full-stack-fastapi-template
PRIG_BANCOS=~/.cache/prig-estudio/bancos .venv/bin/python docs/estudio-banco/lote.py correr externo 1
```

Si el chequeo previo dice que el código cambió: no mezclar; regenerar examen y plan (`lote.py plan prig`) y
empezar una serie nueva. Informes: `~/.cache/prig-estudio/e7/` y copia en `docs/estudio-banco/resultados/`.

**E7 lanzado** (versión inicial, reemplazada por los lotes; solo se usó su pasada de lectura): `~/.cache/prig-estudio/e7/correr_e7.sh` — pasada de lectura de Prig, examen de
Prig sin memoria (153), examen independiente (27), pasada del repositorio externo y su examen (83). Registro
en `~/.cache/prig-estudio/e7/log.txt`; script `docs/estudio-banco/e7.py`.

### E7 retomado (02/10/2026): copia congelada y condiciones controladas

**Qué se encontró al retomar** (la máquina se había reiniciado):

1. **Prig cambió**: `backend/referencias_dp.py` (trabajo del usuario, 30/09 16:07) es código de producción. Medir
   sobre el repositorio que se sigue editando no es fiable (lo mismo pasó antes con los scripts del estudio).
2. **Aparecieron 64 vectores (`bge-m3`) en el banco real** de Prig, que el 30/09 a las 11:35 tenía 0. Prig arranca
   solo su Ollama (`try_autostart_ollama`) y el vigilante del banco indexa vectores cada 4 s cuando el embebedor
   responde: **la búsqueda semántica es una variable oculta** que se puede encender sin que nadie lo pida. No se
   pueden fechar (Ollama no registra las peticiones de embeddings), pero se acotan: después de las 11:35 del 30/09 y
   antes de las 16:07 (el vigilante sincroniza en cada ciclo y el archivo de las 16:07 no está indexado). La única
   medición del estudio que pudo correr con esos vectores presentes es el **lote 1 del 30/09**: se archiva como
   piloto (`~/.cache/prig-estudio/e7/piloto/`) y **se repite** en condiciones controladas; la comparación de ambas
   corridas dirá si importó. Las corridas anteriores (incluida la del 97,7 %) fueron con 0 vectores.
3. **Hueco en el chequeo previo de los lotes**: comparaba la huella del código **sin sincronizar antes** el banco; un
   cambio en el disco pasaba el chequeo y entraba recién con la primera pregunta (que sincroniza).

**Qué se hizo** (`docs/estudio-banco/congelar.py`, `lote.py`, `~/.cache/prig-estudio/e7/serie.sh`):

- **Copia congelada** de Prig en `~/.cache/prig-estudio/repos/Prig`, armada **desde el banco** (el código tal como lo
  tiene indexado, no como está hoy en el disco) más su historia de git: 401 archivos idénticos por contenido, 1
  reconstruido desde el banco (`docs/estudio-banco.md`), 0 irreproducibles; 25 MB. Su banco es una copia del real,
  **sin los 64 vectores**. Verificación: al sincronizar, **0 cambios**; **97/97 lecturas vigentes** reutilizando los
  mismos estados del motor (los prefijos son idénticos: mismo contenido y misma carpeta «Prig»), sin releer ni
  ocupar disco; huella del código `c0ec1880799e807c` = la del plan; examen idéntico al del plan.
- **Condiciones fijas, verificadas en cada lote**: el proceso desactiva el embebedor (ni búsqueda semántica ni
  indexado) aunque Ollama esté en marcha; el banco tiene que tener 0 vectores antes y después; la GPU tiene que estar
  libre al empezar (< 600 MB, mismos expertos calientes que en los otros lotes); el banco se sincroniza antes de
  comparar la huella y su versión no puede cambiar durante el lote; el informe guarda las condiciones (huella,
  versión, GPU, contexto y expertos calientes del motor).
- La serie corre cada lote en su propio proceso y **se detiene sola** en el primero que no pase los chequeos.
- Prig puede seguir cambiando: el objeto medido ya no es el repositorio de trabajo.

### Filtración del examen hacia lo medido (03/10/2026): serie descartada y copia limpia

**Hallazgo.** En la repetición del lote 1 sobre la primera copia congelada, el modelo respondió la pregunta de diseño
`ind_23` **citando la clave de corrección**: «Esto se documenta en `docs/estudio-banco/examen_independiente.py:83-84`»,
con la rúbrica copiada. La copia se había armado desde el banco, y el banco tenía indexados los materiales del estudio.
Se detuvo la serie (lotes 1 y 2 del 02/10 descartados: `~/.cache/prig-estudio/e7/contaminada/`).

**Tres vías por las que la clave estaba al alcance del modelo**

| Vía | Qué exponía | Desde cuándo |
|---|---|---|
| Archivos del estudio indexados (17, cuatro de ellos dentro de unidades leídas) | rúbricas y respuestas del examen independiente; respuestas del piloto (`resultados/prig_lote01.json`); los informes del estudio | 30/09, ~13:00 |
| Consola: `P.esquema()` lista y `P.sql` lee las tablas `examen` y `examen_resultados`, que `examen_proyecto` guarda **en el mismo banco** | las respuestas esperadas y todas las respuestas anteriores | 29/09: **todas** las corridas del examen |
| Historial de cambios: `P.diff` muestra los diffs de los informes; y con `memoria=False` la versión vista quedó en 9 con el banco en 14, así que la sección «Cambios desde tu última respuesta» aparecía en cada pregunta del modo general | texto de los informes; ruido de archivos del estudio en el contexto | piloto del 30/09 y serie del 02/10 |

**¿Afectó a las mediciones anteriores?** Se buscaron rastros (menciones de las tablas del examen, de los archivos del
estudio o de la clave) en las 335 respuestas guardadas: **un solo caso**, `ind_23` del 02/10. En las corridas del
29–30/09 (97,7 %, etapa 3, final) y en el piloto del lote 1, ninguno; la única aparición de «esperado» es el uso común de
la palabra. Como antes no se registraban las llamadas a herramientas, el uso de la consola sin dejar rastro en el texto
**no se puede descartar del todo**; pero en ningún caso hay evidencia, y las respuestas suelen narrar sus consultas.

**Lección de método**: el examen no puede vivir en nada que el modelo pueda leer: ni en el proyecto, ni en la base que
consulta, ni en el historial de cambios.

**Copia limpia** (`congelar.py`, versión del 03/10): la misma copia desde el banco pero **sin** los materiales del
estudio (17 archivos), sin vectores, sin las tablas del examen y sin historial de cambios (102 entradas borradas), con la
versión vista al día. La pasada releyó 8 unidades (las que tenían scripts del estudio y vecinas reagrupadas: 487 s) y
reutilizó las otras 88: 96/96 vigentes. El examen se regeneró (153 preguntas) en una base aparte,
`~/.cache/prig-estudio/e7/examen_prig.db`, a la que se adjunta el banco solo para leer. Verificado desde la propia
consola del modelo: `P.esquema()` no menciona el examen, `P.sql` sobre `examen` da «no such table», `P.cambios()` está
vacío, la frase de la rúbrica de diseño solo aparece en `docs/motor-moe.md` (documentación legítima de Prig) y lo único
que queda del estudio son 7 comentarios de código con la ruta del informe (sin contenido).

**Otros cambios de `lote.py`**: registra qué herramientas usó el modelo en cada respuesta (y alarma si aparece un rastro
de la clave); huella del **sistema bajo prueba** (el backend de Prig) además de la del proyecto medido: si cambia durante
la serie, no se mezcla; modo `--rep` para repetir lotes; `por_tipo` ya no muestra 0 para las preguntas sin puntaje
automático.

**Ruido del muestreo** (encontrado al comparar el piloto con la repetición del lote 1): el perfil «preciso» del motor
usa temperatura 0,3 sin semilla fija, así que la misma pregunta puede recibir respuestas distintas. Sobre las 12
preguntas cambiaron 2, en sentidos opuestos: un endpoint (0,5 → 1,0, con el mismo error conceptual en las dos corridas:
la segunda solo agregó la línea del decorador, y el corrector premia lo largo) y un impacto (1,0 en 3 min 16 s → 0,0 en
17 s: el modelo escribió la consulta como texto **en medio de su respuesta** y terminó; la autoejecución solo atrapa
respuestas que son únicamente código). Al final de la serie se repiten lotes para estimar ese ruido.

### Serie limpia: estado al pausar (03/10/2026, 00:30) y cómo retomar

**Hecho**: lotes 1 y 2 de 15 (24 de 180 preguntas), ambos con verificación automática OK (copia limpia sin cambios,
sin memoria, vectores ni tablas del examen en el banco, sistema y examen idénticos al plan, sin rastros de la clave en
respuestas ni consultas). El lote 3 se cortó al empezar (sin respuestas): se corre completo al retomar.

| Lote | Tiempo | Media automática | Auditoría manual |
|---|---|---|---|
| 1 | 305 s | 0,909 | 11 correctas, 1 incorrecta |
| 2 | 340 s | 0,886 (0,795 antes de arreglar el corrector) | 10 correctas, 1 parcial, 1 incorrecta |

Se auditaron a mano todas las respuestas con puntaje distinto de 1 y dos de 1,0 (impacto y recorrido). Detalle por
pregunta: `docs/estudio-banco/resultados/serie-limpia/auditoria_prig.json`. Con 24 preguntas es una señal, no una medida.

**Lo que ya muestra la serie limpia**

1. **Los huecos del grafo producen respuestas falsas y seguras**, de forma sistemática: los llamadores de
   `delete_item` fallaron en las tres corridas (la llamada pasa por la instancia global `book_service`); el modelo hace
   una sola consulta (`P.llamadores` → `[]`) y concluye «nadie la llama», sin contrastarlo con `P.grep`. Con
   `get_book_citations`, mismo patrón: encontró los métodos de la clase y le faltó el endpoint de `app.py`.
2. **Confusión entre nombres parecidos**: `_ndjson` frente a `_ndjson_en_hilo` (21 endpoints equivocados con total
   seguridad); las dos funciones `resumen` (la ambigüedad de nombres de E5, en la práctica).
3. **La clave del examen también se equivoca**: en un impacto, `GET /api/inicio` sí depende de `siguientes`
   (`inicio_resumen` pasa `lambda: progreso.resumen(...)` y el grafo no ve llamadas dentro de lambda, E2): el piloto
   razonó bien sobre el grafo, concluyó mal y sacó 1,0; la serie limpia razonó mal (mezcló los dos `resumen`), concluyó
   bien y sacó 1,0. **El puntaje automático no distingue esos casos: la auditoría manual es parte de la medición.**
4. **Un error mío en el corrector independiente**: los valores exactos se guardan como JSON y una tupla de Python
   quedaba como lista: la respuesta correcta `(2048, 1803, 2580)` sacaba 0. Arreglado (`corregir_indep`) y
   recorregidos los lotes hechos con la misma regla (`lote.py recorregir prig`).
5. **El muestreo es estocástico** (temperatura 0,3, sin semilla): se repetirán lotes al final para medir el ruido.

**Cómo retomar** (desde `/home/ama-gi/Prig`):

```
.venv/bin/python docs/estudio-banco/lote.py estado prig      # lotes hechos y pendientes
~/.cache/prig-estudio/e7/serie.sh prig 3 15                  # el resto (≈75 min); se detiene sola si algo no cuadra
tail -f ~/.cache/prig-estudio/e7/serie_prig.log              # el avance
```

Después: repetir 2 lotes con `lote.py correr prig N --rep` (ruido, ≈11 min); el repositorio externo (`lote.py preparar
externo`, `examen externo`, su pasada, `plan externo`, `serie.sh externo 1 7`, ≈45 min); la auditoría y el informe de E7;
luego E8–E10.

**Condición para retomar**: el backend de Prig (el sistema bajo prueba) tiene que estar igual que en el plan (huella
`huella_sistema`). Si se edita algo en `backend/` antes de terminar E7, el chequeo previo no deja correr la serie (a
propósito: las respuestas no serían comparables). En ese caso hay que congelar también el sistema (una copia del backend
para medir, ≈15 min de preparación) o empezar una serie nueva. El trabajo en otras carpetas (frontend, docs) no afecta.

Todo lo necesario está en `~/.cache/prig-estudio/` (copia congelada, su banco, el examen en `e7/examen_prig.db`, los
informes) y una copia de los resultados en `docs/estudio-banco/resultados/serie-limpia/`.

### Serie limpia retomada (03/10/2026, desde las 10:21): lotes 3–5 y dos modos de falla nuevos

| Lote | Tiempo | Media automática | Auditoría manual |
|---|---|---|---|
| 3 | 256 s | 0,818 (0,727 antes de arreglar el corrector) | 9 correctas, 2 parciales, 1 incorrecta |
| 4 | 288 s (repetido; ver abajo) | 1,0 | 11 correctas, 1 parcial |
| 5 | 946 s (una agotada de 600 s) | 0,939 | 10 correctas, 1 parcial, 1 incorrecta (la agotada) |

Acumulado de los lotes 1–5: **51 correctas, 5 parciales, 4 incorrectas de 60** (detalle por pregunta en
`auditoria_prig.json`; desde el lote 3 se auditan todas las distintas de 1, las de diseño y los 1,0 de tipos con varias
respuestas).

**1. Respuestas que no terminan (hallazgo del sistema).** El chat con banco **no limita los tokens de la respuesta**. En
el primer intento del lote 4, una pregunta de impacto entró en un bucle de texto: 31.937 tokens en 17,7 min (el borrador
MTP se aceptaba al 99,7 %: texto que se repite), no cupo en 64K, el motor creció a 128K y **volvió a empezar la misma
petición**. En el lote 6 pasó otra vez (11.459 tokens hasta llenar 32K → reinicio a 64K → de nuevo desde cero). Sin
tope, una pregunta puede ocupar el motor hasta llenar 262K (≈2,5 h a 30 tok/s). En la aplicación, el usuario lo corta con
Detener; el arnés no tenía cómo.

**2. Bucle de consultas que no aprende de sus errores (hallazgo del modelo).** `ind_27` (lote 5): 28 consultas en 600 s
sin escribir la respuesta; intentó lo que la consola no permite (`import backend…`, `open()`), repitió 4 veces el mismo
código con el mismo error y pidió dos veces los mismos símbolos. Cada ronda restaura la unidad y relee una conversación
cada vez más larga (~5K tokens a ~235 tok/s), así que el tope de 16 rondas no llega a actuar antes de 10 minutos.

**3. Robustez: si el proceso del motor muere, Prig devuelve respuestas VACÍAS sin aviso** hasta que el vigía lo relanza
(visto al detener a mano el servidor en el lote 6: las 3 preguntas siguientes, vacías en 1 s cada una).

**Cambios del arnés** (no del sistema medido: la huella del backend no cambia):
- **Tope de 600 s por pregunta** (3 veces la respuesta más lenta medida antes, 196 s: no habría cortado ninguna). Al
  vencer, se corta como Detener; si el motor sigue ocupado (una respuesta en bucle que no emite trozos no ve la
  cancelación, y `asyncio.run` se queda esperando su hilo), se lo detiene **desde dentro** (`detener()`) y se espera a
  que quede libre. Probado sin modelo con el `_flujo_cancelable` real y un productor mudo: corta y libera en 11,5 s. La
  respuesta parcial se corrige igual, queda marcada «agotada» y se audita a mano.
- **Segundo error del corrector independiente**: los valores de texto se guardan con comillas JSON y el modelo los
  escribe entre backticks; `ind_02` exacto sacaba 0. Arreglado (vale entre comillas o backticks, no suelto: «js» suelto
  aparece en cualquier texto) y recorregido todo: solo cambió `ind_02`.
- Lotes repetidos: el primer intento del lote 4 (5 respuestas, cortado a mano a los 23 min) y el lote 6 con el motor
  detenido desde fuera quedan en `~/.cache/prig-estudio/e7/fallidos/` y en la base del examen con su propia corrida; no
  se mezclan.

**Defectos de la clave del examen encontrados al auditar** (el puntaje automático los esconde: el modelo sacaba 0 o 1
por la razón equivocada):
- **Recorrido con varios caminos**: la pregunta supone uno solo; el modelo dio otro camino real
  (`comprobar → validar_paginas → ErrorDesafio`) y sacó 0.
- **Impacto de funciones con dos rutas**: `examen_proyecto.py:178` arma `endpoint_de` como dict por función y la segunda
  ruta pisa a la primera (afecta a las 7 funciones con dos decoradores). El grafo y `P.impacto` las tienen bien.
- **Config ambigua o incompleta**: la clave omite a `_ajustes` (la que lee `truncar`); varias configuraciones usan la
  clave «activo».
- **Homónimos en el examen independiente**: `load_state` existe dos veces en el mismo archivo (repositorio y motor).

**El hueco del grafo con más consecuencias**: llamadas a través de una **instancia global o una fábrica**
(`book_service.x()`, `recursos_gestor().radiografia()`, `study_plan_engine.load_state()`): ya van 4 respuestas de
llamadores incompletas o falsas por esto, siempre con el mismo patrón: el modelo hace **una sola consulta** al grafo y no
la contrasta con `P.grep`.

### Serie limpia de Prig: resultado completo (15 lotes, 180 preguntas, 03/10/2026 hasta las 12:46)

Auditadas a mano todas las respuestas con puntaje distinto de 1, todas las de diseño y los 1,0 de los tipos con varias
respuestas (verificadas contra el código de la copia); los 1,0 de respuesta única (constante, endpoint, ubicación,
ejecución) tienen claves verificadas por construcción. Detalle: `resultados/serie-limpia/auditoria_prig.json`.

| | Resultado |
|---|---|
| **Correctas (a mano)** | **157 de 180 (87,2 %)** · 13 parciales (7,2 %) · 10 incorrectas (5,6 %) |
| Media automática | 0,922 (174 con puntaje; 6 de diseño solo a mano) · manual ponderada (parcial = ½) 0,908 |
| Corrector frente a la auditoría | 4 respuestas con 1,0 que no eran correctas (2,3 %; una NEGABA el camino pedido y nombraba las funciones al negarlo) y 1 con 0 que era correcta (otro camino real) |
| Tiempo por respuesta | mediana 21 s · p90 44 s · p95 85 s · máx 616 s (2 agotadas a los 600 s) · 104 min en total |
| Consultas | media 1,5 por respuesta; 59 sin ninguna; 5 con 10 o más |

**Por tipo** (correctas / total, a mano): constante 17/17, endpoint 17/17, ubicación 17/17, ejecución 13/13,
endpoint_real 4/4, llamadores 16/17, entorno 15/17, frontend 15/17, recorrido 15/17, config 13/17, diseño 4/6,
**impacto 11/17**, **llamadores_independiente 0/4** (3 parciales). Lo que se busca por nombre está resuelto; lo que exige
seguir el grafo hacia arriba (impacto, llamadores) es donde falla, y casi siempre por los huecos conocidos del grafo.

**Modo unidad frente a modo general — hallazgo principal de la serie.** El general acierta **95 %** (62/65) y el de
unidad **83 %** (95/115). La diferencia se mantiene dentro de cada tipo (config 4/8 frente a 9/9; entorno 6/8 frente a
9/9; impacto 9/15 frente a 2/2); con los 12 tipos que tienen ambos modos, ponderados por igual: **86 % frente a 97 %**.
No es un experimento aleatorio (el enrutador manda a modo unidad lo que cae en una unidad), pero el mecanismo se ve en
las respuestas: en modo general `componer()` pone en el prompt los hechos del grafo y el código literal de lo
preguntado; en modo unidad el modelo responde desde su lectura y **tiene que saber qué consultar**, y ahí falla: usa
`P.llamadores` para una clave de configuración (devuelve `[]`), hace **una sola consulta** y no la contrasta, o se enreda
en bucles de consultas. El modo unidad, la pieza nueva de la etapa 3, es hoy el menos fiable de los dos para preguntas
del grafo.

**Modos de falla de las 23 no correctas** (contados uno por uno en la auditoría): hueco del grafo seguido de una sola
consulta (instancia global, fábrica, lectura de configuración que el grafo no registra): 4; herramienta equivocada
(`P.llamadores` sobre una clave): 3; ruta HTTP inventada o no dada (nombra la función, no la ruta): 4; niega un camino
que existe: 2; salida degenerada (vacía, «...», 28 consultas o 16 rondas sin respuesta): 4; diseño con una afirmación
falsa: 1; pregunta ambigua (homónimos, varias configuraciones con la misma clave): 2; confusión de nombres parecidos
(`_ndjson` / `_ndjson_en_hilo`): 1; frontend incompleto (no nombró una de las funciones): 2.

**El examen también se audita**: 11 claves defectuosas encontradas en 180 preguntas (6 %) (incompletas por los mismos huecos
del grafo, dict que pisa la segunda ruta, módulo IIFE en vez de función, recorridos con varios caminos, homónimos). En
varias, la respuesta del modelo era **más completa que la clave** (por ejemplo, 26 endpoints reales donde la clave tenía 3).

**Ruido del muestreo (repeticiones)**: los lotes 3 y 6, elegidos al azar con semilla fija antes de ver resultados
(`random.Random(7)`), se corrieron otra vez. El puntaje automático coincidió en **22 de 22** preguntas y el veredicto
manual en **23 de 24** (solo cambió una de diseño: incorrecta → parcial). La redacción cambia mucho (similitud de texto
0,07–0,97) y la duración también (la misma pregunta: 38 s o 167 s). Lo sistemático se repite: el mismo camino
alternativo en el recorrido, la misma omisión en config, la misma respuesta **en inglés** para `parsearTimestamp`. El
ruido pesa poco en el agregado; puede cambiar el veredicto de preguntas abiertas.

**Variable no controlada: la carga de la CPU.** Durante las repeticiones la máquina estaba en uso (navegador, kdenlive,
OBS; carga 5,5) y la generación bajó de **33 a 12,7 tok/s** (el motor corre los expertos en CPU): el lote 6 tardó 566 s
frente a 292 s, con la misma exactitud. Desde ahí `lote.py` registra la carga de la CPU antes y después de cada lote. Los
tiempos de E7 sirven como orden de magnitud; los de lotes con la máquina ocupada no son comparables.

**Bug de infraestructura del sistema, encontrado al diseñar E8 — arreglado (03/10, 13:05)**: `reasignar()` borraba los
estados de las lecturas que su banco ya no usaba, pero la carpeta de estados del motor es **una sola para todos los
bancos**: dos carpetas con el mismo nombre y el mismo código comparten estados (es el caso de la copia limpia y el banco
real de Prig: 88 compartidos), y la pasada de uno borraba lecturas válidas del otro. Ahora `reasignar()` consulta (solo
lectura) las lecturas de los demás bancos (`~/.prig_bancos`, `PRIG_BANCOS` y la carpeta del propio banco) y no borra un
estado que otro use; si algún banco no se puede leer, no borra nada. Test nuevo
(`test_reasignar_no_borra_estados_que_usa_otro_banco`): **falla sin el arreglo y pasa con él**; los 11 de
`test_lectura_unidades` pasan. Se aplicó después de terminar la serie de Prig y sus repeticiones (cambia la huella del
sistema); el repositorio externo y E8–E9 se miden ya con el arreglo.

### Repositorio externo (full-stack-fastapi-template): en curso

Preparado igual que Prig: su banco tenía el examen viejo ADENTRO (83 preguntas, la misma vía de filtración): se quitó y
el examen nuevo vive aparte (`e7/examen_externo.db`, 83 preguntas: endpoint, llamadores, ubicación e impacto 17 cada uno;
frontend 15). Pasada de lectura: 8/8 unidades vigentes en 446 s (6 leídas a 16–33 s cada una, 2 restauradas del disco).
Plan de 7 lotes con la huella del sistema ya arreglado.

**Lote 1** (12 preguntas): automática 0,771; a mano **9 correctas, 1 parcial, 2 incorrectas**. Lo que muestra:
- **El examen de frontend no es válido en React/TypeScript**: la clave mezcla el servicio generado (`UsersService`) con
  **nombres de tipos** (`usersReadUserMeData`…) como si fueran funciones. El modelo nombró el servicio, sus métodos y los
  componentes que los usan: mejor que la clave, y sacó 0,25–0,5.
- El grafo de TS no ve llamadas a funciones importadas: `isLoggedIn` se llama en el `beforeLoad` de 5 rutas y la clave (y
  el modelo, que repitió el grafo) solo tiene `useAuth`.
- Pregunta defectuosa: «`GET /users/*`» (forma canónica interna de `/users/{user_id}`); el modelo la leyó como `/users/`.
- Una agotada a los 600 s (frontend), cortada por la vía suave.
- Lo de Python sale bien: impacto con el prefijo `/api/v1` real, llamadores completos.

**Lote 2**: cortado por la pausa tras 3 preguntas (endpoint 1,0; endpoint 1,0; frontend 1,0); se corre entero al retomar.

### E8 — preparación y verdad (03/10, sin modelo)

**Copia con 8 errores inyectados** (`docs/estudio-banco/e8.py`, `~/.cache/prig-estudio/repos-e8/Prig`): dos por clase,
en archivos distintos.

| | Error | Dónde | Tests que lo detectan (de 956) |
|---|---|---|---|
| B1 | off-by-one: la «mejor racha» empieza en 0 | `progreso.racha` | 1 (`test_racha`) |
| B2 | off-by-one: al cortar por líneas se pierde una | `particion_proyecto.piezas_de_archivo` | **ninguno** |
| B3 | caso borde: `startswith` en vez de `commonpath` (acepta `/ws-otro` si la raíz es `/ws`) | `FileManager.is_path_allowed` | **ninguno** (agujero de seguridad) |
| B4 | caso borde: `max([])` sin lecturas | `Tramo.pico_real` | **ninguno** |
| B5 | clave mal escrita: `"activa"` por `"activo"` | `Ritmo.activo` | 6 |
| B6 | clave mal escrita: `"max_chunks_tokens"` | `JobExporter.preparar` | **ninguno** |
| B7 | recurso: la conexión SQLite nunca se cierra | `BancoProyecto.conectar` | **ninguno** |
| B8 | proceso: al vencer el tiempo no se mata y `communicate()` espera para siempre | `CodeRunner.run_file` | 1 (se cuelga) |

**Los tests de Prig detectan 3 de 8 errores realistas.** (Base: 956 tests, 19 ya fallan en la copia limpia por el entorno
aislado —HOME temporal, sin GPU—; se descuentan.) Esto da la vara para E8: si el modelo encuentra los que los tests no
ven, aporta algo que la batería no da.

**Una sesión de edición (dato para E9)**: 8 archivos modificados → sincronizar 1,0 s, reparticionar 0,26 s, **9 de 96
unidades vencidas** (120.443 tokens para releer). Las 3 unidades de `banco_proyecto.py` vencieron aunque el error está en
una sola (borrar 3 líneas desplaza las siguientes).

Preguntas listas (`resultados/e8/preguntas_e8.json`): E8a, la MISMA pregunta («¿tiene algún error?») sobre las 8 funciones
con error y 4 sin tocar (controles, para los falsos positivos), en orden mezclado; E8b, el cambio (antes → ahora) y
«¿qué tests fallan?», contra la verdad de arriba; E8c, 3 flujos con citas `archivo:línea` que se verifican solas. Las E8a
van primero: el diff de las E8b no puede contaminarlas.

### E9 — preparación y E9b (03/10, sin modelo)

**E9b · Vigencia de las notas al editar** (`e9.py notas`; se cambió solo `Tramo.pico_real`):

| Nota | ¿Marcada «puede estar desactualizado»? | ¿Debería? |
|---|---|---|
| sobre la función cambiada | sí | sí |
| sobre otra cosa del mismo archivo, que no cambió | **sí** | no (falsa alarma: la marca es por archivo) |
| sobre algo que depende de la función cambiada, en otro archivo | **no** | sí (omisión: no sigue el grafo) |
| sin relación | no | no |

El aviso sí llega al contexto del modelo. Las fichas de símbolos con el código viejo (2) no importan: **ninguna parte del
chat ni de la consola usa la tabla de fichas**.

**E9a** preparada: copia `repos-e9/Prig` (reusa las 96 lecturas, 0 releídas); 12 preguntas del examen que tenían
resolución guardada el 30/09, **todas de modo general** (el único donde la memoria entra en el contexto) y todas correctas
en E7. Dos brazos: la memoria real del 30/09 (313 resoluciones + 6 notas) y una memoria **sembrada** con una respuesta
equivocada por pregunta. **Hallazgo previo**: `memoria=False` no impide que el modelo escriba notas con `anotar` (el
prompt del modo general se lo pide); visto en el lote 10 y desde entonces el arnés las borra tras cada pregunta.

### Pausa (03/10/2026, 13:33) — estado y cómo retomar

**Hecho**: E7 de Prig completo (15 lotes + 2 repeticiones, auditado); arreglo de `reasignar`; externo: preparado, pasada,
plan y lote 1 auditado; E8: copia, verdad de los tests y preguntas; E9: copia, selección y E9b.

**Falta** (≈1 h 30 min de modelo si la máquina está libre; más si está en uso):
1. Externo, lotes 2–7 (≈35 min) y su auditoría.
2. E8: pasada de la copia mutada (9 unidades, ≈5 min), las 23 preguntas (≈20 min), corrección y auditoría.
3. E9a: los dos brazos de memoria (12 + 12 preguntas, ≈15 min); E9c: un cambio sin pasada y 3 preguntas (≈3 min).
4. E10: costos y veredicto (sin modelo).

```
# desde /home/ama-gi/Prig; la GPU tiene que estar libre (nvidia-smi < 600 MB) y ningún llama-server corriendo
~/.cache/prig-estudio/e7/serie.sh externo 2 7                       # externo; se detiene sola si algo no cuadra
PRIG_BANCOS=~/.cache/prig-estudio/bancos .venv/bin/python backend/lectura_unidades.py --pasada ~/.cache/prig-estudio/repos-e8/Prig
.venv/bin/python docs/estudio-banco/sonda.py ~/.cache/prig-estudio/repos-e8/Prig ~/.cache/prig-estudio/e8/preguntas_e8.json ~/.cache/prig-estudio/e8/respuestas_e8.json
.venv/bin/python docs/estudio-banco/e8.py corregir
.venv/bin/python docs/estudio-banco/e9.py memoria real      && .venv/bin/python docs/estudio-banco/sonda.py ~/.cache/prig-estudio/repos-e9/Prig ~/.cache/prig-estudio/e9/preguntas_e9a.json ~/.cache/prig-estudio/e9/respuestas_e9a_real.json --memoria
.venv/bin/python docs/estudio-banco/e9.py memoria sembrada  && .venv/bin/python docs/estudio-banco/sonda.py ~/.cache/prig-estudio/repos-e9/Prig ~/.cache/prig-estudio/e9/preguntas_e9a.json ~/.cache/prig-estudio/e9/respuestas_e9a_sembrada.json --memoria
.venv/bin/python docs/estudio-banco/e9.py corregir_a
.venv/bin/python docs/estudio-banco/e9.py memoria vaciar && .venv/bin/python docs/estudio-banco/e9.py editar && .venv/bin/python docs/estudio-banco/sonda.py ~/.cache/prig-estudio/repos-e9/Prig ~/.cache/prig-estudio/e9/preguntas_e9c.json ~/.cache/prig-estudio/e9/respuestas_e9c.json
```

**Condiciones**: el sistema medido es el backend con el arreglo de `reasignar` (huella `375d999bef8b8b11` en
`plan_externo.json`). Si se edita algo en `backend/` antes de terminar, el chequeo previo del externo no deja correr (a
propósito). Los estados del motor ocupan ≈28 GB de 32,8 GB permitidos: la pasada de E8 suma ≈1,9 GB (queda por debajo).
Todo lo medido está en `~/.cache/prig-estudio/` y copiado en `docs/estudio-banco/resultados/` (serie-limpia, externo, e8,
e9). Nada está en git todavía.

### Reanudación (09/10/2026): el sistema cambió → sistema congelado

Al retomar, el backend ya no era el medido: entre el 03/10 y el 09/10 entraron `perfiles_config.py`, `audio_monitor.py`,
`llm_director.py` y endpoints nuevos en `app.py` (huella `375d999b…` → `09d615ce…`). El chequeo previo habría rechazado
los lotes (a propósito). **El estado del 03/10 no se puede reconstruir**: no quedó en git (el commit del 06/10 ya trae
cambios posteriores: ni completo ni sin `perfiles_config.py` da la huella del plan).

Decisión: **congelar el sistema actual** (`docs/estudio-banco/congelar_sistema.py` → `~/.cache/prig-estudio/sistema/
09d615ce45e84e2c`: copia de `backend/` y `main.py`, el resto del repositorio enlazado; `lote.py` y `sonda.py` lo usan con
`PRIG_SISTEMA`) y medir con él todo lo que falta: el externo **completo** (lotes 1–7 de nuevo: el lote 1 del 03/10 queda
archivado en `e7/sistema_0310/`), E8 y E9. Así la edición diaria del backend ya no interfiere.

¿Afecta a la comparación con la serie de Prig? Se revisó el diff desde el 06/10: endpoints nuevos de configuración, un
registro en `write_file` y la importación de `audio_monitor` (sin efectos al importar: solo captura con suscriptores por
WebSocket); `llm_director` se importa solo al guardar un archivo. **Nada toca el camino del chat con banco** (`ai_chat`,
`componer`, la consola, el motor). Entre la serie de Prig y lo que sigue, la diferencia que sí importa es el arreglo de
`reasignar` (no afecta las respuestas). El plan nuevo del externo tiene los mismos lotes, el mismo examen y el mismo
código medido.

### Implementación de lo medido (09/10/2026)

A pedido, la medición se detuvo (el externo se cortó en el lote 1, pregunta 4; E8 y E9a quedan preparados sin correr) y
lo encontrado se pasó al sistema. Cada cambio sale de un hallazgo medido; **se valida con el uso** (y, si se quiere, con
los lotes y sondas que siguen listos: `sonda.py`, `e8.py`, `e9.py`).

| Hallazgo (dónde se midió) | Cambio | Dónde |
|---|---|---|
| Respuestas sin tope: bucles de texto de 32K tokens, y al no caber el motor agrandaba el contexto y **repetía la petición desde cero** (E7, lotes 4 y 6) | Tope de **4096 tokens** en el chat con banco (lo mismo que el motor ya reservaba al elegir el contexto: no cambia su elección); cortada, se puede «Continuar» | `app.py` `TOPE_RESPUESTA_BANCO`, `chat_eventos(max_tokens=)` |
| Bucles de consultas: el mismo código fallido 4 veces; 16 rondas sin responder; con 9+ consultas, 1 de 5 correctas (E7) | Una consulta **idéntica** no se reejecuta (se le recuerda que el resultado está arriba); a la 2.ª repetida, o en la **última ronda**, se quitan las herramientas y se le pide responder. Con el banco: 9 rondas (8 de consultas + 1 para responder) | `ai_engine_class.chat_eventos`, `app.py` `RONDAS_BANCO` |
| «Etiquetas de cierre» inventadas en el código de la consola (`</print(...)`): la mitad de las consultas de una respuesta fallaban (E7, lote 15) | Se quitan antes de ejecutar (y las cercas de Markdown) | `memoria_consulta.limpiar_codigo` |
| **Modo unidad 86 % frente a 97 % del general** en las mismas clases de pregunta: no sabía qué consultar, una sola consulta, rutas inventadas o ausentes, respuestas en inglés (E7) | Con la pregunta (parte variable: **no invalida ninguna lectura guardada**) van los **hechos del banco** sobre lo que nombra: definición, `lee_config`/`lee_entorno`/`expone`…, llamadores (del grafo y por texto), rutas que expone, endpoints alcanzados y apariciones literales con la función que las contiene; si nombra un archivo, desambigua homónimos. La guía pide verificar antes de decir «nadie lo llama», dar método y ruta exactos y responder en el idioma de la pregunta | `memoria_consulta.hechos_de_la_pregunta`, `lectura_unidades.pregunta_con_contexto(hechos=True)`, `guia_consola` |
| Huecos del grafo (instancia global, fábrica, función pasada como argumento, lambda): llamadores falsos «nadie la llama» (E2, E7: 4+ casos) | `P.llamadores` agrega, marcados «texto: …, sin resolver» y con la línea, los llamadores que encuentra en el código; sin cruzar lenguajes y sin variables locales homónimas. Probado con los casos reales: `delete_item` (falló 3 de 3 en E7), `radiografia`, `load_state`, `progreso.historial`, `comprobar` → aparecen los que faltaban | `memoria_consulta.API.llamadores` |
| `memoria=False` no impedía que el modelo anotara notas, que entraban en las preguntas siguientes (E7, lote 10) | Sin memoria: `anotar` (herramienta) y `P.anotar/afirmar/guardar` (consola) no escriben, y el prompt general ya no pide anotar. La lista de herramientas del modo unidad no cambia (está en el prefijo guardado) | `herramientas_chat.Herramientas(escribir=)`, `memoria_consulta.Consola(escribir=)`, `app.py` `INSTRUCCION_BANCO_SIN_MEMORIA` |
| Con el motor caído, respuestas **vacías** sin aviso (E7, lote 6) | Si no llega ni texto ni aviso, el chat lo dice | `app.py` `ai_chat` |
| Notas: la marca «puede estar desactualizado» era por archivo y se le escapaba la nota que depende de una función cambiada desde otro archivo (E9b) | También se marcan las notas que **nombran** un símbolo que cambió (con forma de código, para no saltar con palabras comunes como «estado») | `banco_proyecto._marcar_revisar` |
| Clave del examen: la segunda ruta de una función con dos decoradores se perdía (E7, 7 funciones) | El generador guarda todas las rutas | `examen_proyecto.py` |

Tests nuevos (todos fallan sin su cambio): tope y consultas repetidas/última ronda (`test_ollama_modelos`), llamadores
por texto, hechos de la pregunta, términos, limpieza del código y consola sin memoria (`test_memoria_consulta`), nota
que nombra un símbolo cambiado (`test_banco_proyecto`); y los del chat actualizados (rondas, tope, hechos en modo
unidad). Nada de esto toca el prefijo guardado de las unidades: las 96 lecturas siguen vigentes.

**Qué observar al usarlo** (lo que el estudio no alcanzó a medir con el modelo después del cambio): si el modo unidad
deja de fallar en llamadores/impacto/config (los hechos le llegan hechos); si los llamadores «por texto» confunden en
nombres muy comunes (van marcados como posibles homónimos); si el tope de 4096 corta alguna respuesta legítima (se ve
como «cortada» y se puede continuar).

### Texto primero: medición corta (T7, 09/10/2026)

**Qué se midió** (`docs/plan-texto-primero/T7-medicion.md`). En vez de repetir el examen, una pregunta por cada modo de
falla que dejó E7 (11 de Prig + 1 control) y los 4 errores de E8 que ningún test detecta (+ 1 control), en modo general y
en modo unidad, con el sistema congelado `c56a3849…` (T1–T5 y los 9 cambios de «Implementación de lo medido»). Mismas
condiciones que E7: sin vectores ni memoria, GPU libre, `think=False`, tope de 600 s por respuesta; tope del caché en 60 GB
solo en memoria; CPU sin turbo (`auto-cpufreq`: turbo «never» y «powersave», como quedó el 05/10; solo afecta los
tiempos). Primera serie: 4 corridas, 34 respuestas, 32 min de modelo. Como el resultado quedó dudoso (la regla lo
prevé), una **segunda tanda** de 18 respuestas (11 min) solo con las preguntas en que los modos difirieron: otra muestra
de cada modo y una variante del general con los hechos al final (abajo). **Ninguna de las 52 respuestas salió vacía ni
agotada.** Cada una se auditó a mano contra el código, no contra una clave: `resultados/texto-primero/notas.md` (el
detalle, pregunta por pregunta) y `analisis.json`.

**Prig: las 11 preguntas de falla** (C correcta, P parcial, I incorrecta; una letra por muestra; C* = correcta con un
falso positivo de la herramienta)

| Pregunta (modo de falla en E7) | E7 | General | Unidad | General, hechos al final |
|---|---|---|---|---|
| ind_15 llamadores por una instancia global (`book_service.delete_item`) | I (3 de 3) | P, C | C, C | C |
| ind_16 llamadores por una fábrica (`recursos_gestor().radiografia`) | P | P, C | C*, C* | C |
| f46b impacto con lambda y función pasada como argumento | C | C (3 de 4) | C, 4 de 4 (fue a general) | — |
| a84a configuración con la lectora fuera del grafo | P | P | P | P (las 3 + 2 que no leen) |
| 29b4 impacto: nombró la función y no la ruta | P | C | C | C |
| 12bb impacto: ruta inventada | I | P, C | C, C | C |
| 0b5f recorrido: negó un camino | I | I | I (fue a general) | — |
| d408 recorrido: negó un camino | I | I | I (fue a general) | — |
| ind_27 diseño: bucle de 28 consultas | agotada | C, P | P, C | (sin hechos: igual al general) |
| 1f14 entorno: bucle de texto | agotada | C | C | — |
| 02bd llamadores: salida «...» | I | C | C | C |
| **Correctas esperadas** (fracción de C por pregunta, sumada) | **1** | **6,0** | **7,5** | **7,5** (el general donde no se midió) |
| control: una constante | C | C (la línea mal) | C, la línea mal (fue a general) | — |

**Lo que muestra cada mecanismo**

1. **Lo mecánico quedó arreglado en los dos modos.** Bucles: ninguna de las 52 respuestas se agotó; ind_27 respondió con
   0 a 5 consultas (en E7: 28 y agotada); 1f14 y 02bd, que en E7 terminaron vacía y en «...», salen correctas. Rutas
   HTTP: 29b4 y 12bb salen exactas de los hechos («endpoints reached through the graph»). Llamadores que el grafo no ve:
   el «posible llamador por texto» llega (ind_15, ind_16). De 7 incorrectas en E7 quedan 2.
2. **Recorridos: 4 de 4 respuestas niegan un camino que existe** (0b5f y d408, en los dos modos). Nunca caen en una
   unidad (reparten su peso entre las dos puntas) y los hechos miran cada nombre por separado. d408 llega a mostrar
   `termico.py:365`, donde `Gobernador.__init__` crea `ControladorFrio`, y aun así lo niega razonando «en régimen estable».
   **`P.camino` los encuentra exactos, sin modelo**: `modelos_borrar_parciales → _carpeta_modelos_servidor → estado →
   librerias_disponibles` y `recursos_ritmo → gobernador → Gobernador.__init__ → ControladorFrio`. Es el único modo de
   falla de E7 que sigue igual, y el arreglo está a mano (propuesta 1).
3. **Una muestra por pregunta no separa los modos.** Tres de las cuatro diferencias de la primera serie no se repitieron:
   ind_15, ind_16 y 12bb en general fueron P en la primera muestra y C en la segunda; ind_27 quedó 1 a 1 en los dos modos.
   f46b dio 3 de 4 y 4 de 4 en dos muestras del mismo modo. Diferencias de una o dos preguntas entre modos están dentro
   del ruido.
4. **Lo que sí se sostiene con dos muestras: los hechos rinden mejor pegados a la pregunta.** El modo unidad acertó 6 de 6
   en ind_15, ind_16 y 12bb (dos con el mismo falso positivo); el general, 3 de 6. Hoy el general pone los hechos en la
   posición 0 y el paquete del banco los separa de la pregunta (21.083 caracteres en ind_15); el de unidad los pone
   pegados a la pregunta (`unidad → hechos → guía → QUESTION`). Con los hechos al final (una variante del arnés:
   `sonda.py`, `hechos_al_final`; el sistema no cambia), el general acertó 3 de 3 y dio **las respuestas más precisas de
   esas tres preguntas**: verificó con la consola lo «sin resolver» y descartó el homónimo `file_mgr.delete_item` (ind_15)
   y el atributo `maq.radiografia` (ind_16), que el de unidad repitió como llamador las dos veces. No empeoró los controles
   (29b4 y 02bd igual; a84a ganó cobertura). Es una muestra por pregunta: indica el mecanismo, no lo prueba.
5. **a84a: los modos fallan en direcciones opuestas.** El general toma la lectura literal (`_ajustes`) y un falso positivo
   (`ConfigModelos._leer`, que define el valor por defecto); el de unidad toma lo del grafo (`embeber`, `estado`) y omite la
   literal; con los hechos al final aparecen las tres, más `_leer` y `fijar_embeddings`, que escribe. Los hechos de
   configuración tienen que separar «lee la clave» (`x.get("clave")`) de «la usa», «la escribe» y «la define».
6. **Lo que el modelo agrega por su cuenta, a veces es inventado**: rutas «indirectas» `/api/chat…` (12bb, general, 1 de
   2); en ind_27 (los dos modos, 1 de 2 cada uno), un orden de reintentos dado como «exacto» que no es el del código, «el
   mismo número de calientes sin MTP» (se recalcula), la ruta del registro (`/var/log/prig.log`; es `~/.prig_moe.log`) y un
   código «simplificado» presentado como literal. Los hechos arreglan lo que cubren, no el resto.
7. **El enrutador manda a general 4 de 12 aunque se pida unidad.** Tres reparten su peso de verdad (la mejor unidad 24–29
   %). El control no: `MESETA_S` no está en la tabla de símbolos (las constantes de módulo no se indexan) y las palabras de
   la ruta nombrada (`recursos`, `termico`, `backend`) cuentan como identificadores y reparten puntos: la mejor 5,36 contra
   4,0, menos de 1,5×. No es grave (el general responde igual), pero por eso la corrida «unidad» es mixta.
8. **Detalles**: los números de línea salen corridos (la constante: 22 y 39, es 60; B3: 37 y 39, es 40); el eco del código
   de la consola pegado al principio del texto (como en E7); un falso positivo sistemático de los llamadores por texto
   (`calibrar`, por el atributo `maq.radiografia`, patrón «pasada como valor»).

**E8: encontrar errores** (la misma pregunta, «¿tiene algún error?», sobre la copia con errores inyectados)

| | B2 `n + 1` al cortar | B3 `startswith` | B6 clave mal escrita | B7 conexión sin cerrar | C2 control |
|---|---|---|---|---|---|
| Tests de Prig | no | no | no | no | — |
| General | no (falso positivo) | **sí, 3 de 3** | no (salida degenerada) | no | limpio |
| Unidad | no (falso positivo) | 2 de 3 (una: «está protegido», falso) | no (falso positivo) | no | limpio |

- **Con `think=False`, ninguno de los dos modos sirve hoy para revisar código.** B3 (el agujero de seguridad) se encuentra
  casi siempre, con el caso y el arreglo; los otros tres no los ve ninguno, y están en el texto de la función que tenía
  delante (`n + 1`, «chunks», la falta de `close`): son fallas de lectura atenta, no de contexto. B6 cae en los dos modos
  en el patrón «Espera… el error está en la línea 159… esto es correcto», repetido. Falsos positivos: 1 en general, 2 en
  unidad.
- **El riesgo real**: B3 en unidad, una de tres veces, afirma que el caso `/workspace` frente a `/workspace2` «está
  protegido porque `startswith` se aplica sobre la ruta normalizada» (falso) y justifica el rastro del cambio (el `except
  ValueError` de `commonpath`). Los controles (C2) dicen, con la misma seguridad, que `resolve` no tiene huecos: en esta
  copia los tiene, por B3.
- La consola no puede importar el proyecto (lista blanca de módulos, E5): el modelo no puede ejecutar la función con un
  caso, solo reescribirla en comentarios. B2 lo revela cualquier ejecución con un tramo sin hijos mayor que el tope;
  ninguno de los dos modos eligió ese caso.
- El banco ya tiene lo necesario para señalar B6: `JobExporter.preparar lee_config max_chunks_tokens` (l.93) y, aparte,
  `SondeoLibro.recomendar lee_config max_chunk_tokens`. Una clave leída en un solo lugar que difiere en una letra de otra
  más usada es una «¿clave mal escrita?».

**T5 y el caché, en uso real.** Las 4 unidades vencidas de la copia E8 se leyeron al vuelo («forzado: … no tiene lectura
guardada; se lee ahora»), se guardaron y se reaprovecharon (C2 y las repeticiones de B3 restauraron la de B3 en 0,1–0,3 s).
Las preguntas en modo general no escribieron ningún estado. Un hallazgo del registro del motor: cuando el modelo agota las
8 consultas, **la última ronda sin herramientas cambia el prefijo guardado** (le faltan las definiciones de las
herramientas, 641 tokens): el motor releyó la unidad desde cero (26 s) y guardó otro estado de 246 MB que casi nunca se
reaprovecha. Pasó 1 vez en 19 respuestas en modo unidad (E8a_B2), que además pasó de 32K a 64K de contexto en medio de la
pregunta. La medición dejó 5 estados nuevos (1,3 GB), todos de la copia E8: son del estudio, para la limpieza de T8.

**Decisión** (reglas fijadas antes de medir, en T7-medicion.md)

- **Modo por defecto: queda `auto`** (ya es el valor por defecto: no se cambia nada). El general queda por debajo del de
  unidad en las 11 de falla: 6,0 contra 7,5 correctas esperadas con las dos muestras (5 contra 7 en la primera serie
  sola). Las otras dos condiciones sí se cumplen: el control sigue correcto y en E8 el general encuentra al menos tantos
  como el de unidad menos uno (B3 3 de 3 contra 2 de 3).
- **Tope del caché: queda en 32 GB**: con `auto`, lo que entre el proyecto principal (Prig ocupa ~30 GB).
- **Fichas por símbolo: no**: el de unidad no encontró ningún error que el general no encontrara.
- La variante con los hechos al final empata al de unidad (7,5), pero es una prueba del arnés, no el sistema medido: no
  decide; justifica el cambio 2 de abajo y volver a medir.

**Límites**: una o dos muestras por pregunta (y una de la variante): no mide porcentajes. Las preguntas se eligieron por
haber fallado en E7, así que parte de la mejora frente a E7 es regresión a la media (los bucles de E7 fueron azarosos);
pero E7 repetido dio 23 de 24 veredictos iguales, así que casi todas esas fallas eran sistemáticas. E7 → T7 compara
versiones del sistema (los 9 cambios y T1–T5), no solo modos. Todo con `think=False`.

**Propuestas, en orden** (1–5 implementadas y re-medidas el 10/10: ver la sección siguiente)

1. **`P.camino` en los hechos** cuando la pregunta nombra dos símbolos: los recorridos fallaron 4 de 4 y el camino exacto
   ya está en el banco.
2. **En modo general, los hechos después del paquete**, pegados a la pregunta: una línea en `ai_chat`; no toca ninguna
   lectura guardada (el general no guarda estados). Con el arnés: 3 de 3 y las respuestas más precisas.
3. **Hechos de configuración** que separen leer, escribir y definir una clave (a84a), y que marquen «¿clave mal
   escrita?» (B6).
4. **Llamadores por texto**: no tomar el atributo de otro objeto como «pasada como valor» (`maq.radiografia`, falso
   positivo sistemático en unidad); separar los de tests y los homónimos de otra clase (`file_mgr.delete_item`).
5. **La última ronda sin herramientas, sin cambiar el prefijo**: mantener las definiciones y forzar la respuesta de otro
   modo (`tool_choice: "none"` si el servidor lo respeta, o ignorar una llamada que llegue igual).
6. Impacto por texto de dos niveles (f46b: `/api/progreso/resumen` por dos saltos); en el enrutador, indexar las
   constantes de módulo como símbolos y no contar las palabras de una ruta nombrada como identificadores.
7. Revisión de código: medir E8 con `think=True` antes de recomendar Prig para eso; ejecutar una función del proyecto en un
   proceso aislado (`P.probar`) es una decisión de seguridad (E5).

Después de 1–5, volver a medir solo ind_15, ind_16, 12bb, a84a, 0b5f y d408, dos veces en cada modo (~10 min): si el
general queda a la par del de unidad, T8 pasa el modo por defecto a `general` y el tope del caché a 5 GB.

### Las propuestas de T7, implementadas y re-medidas (10/10/2026)

| Propuesta | Cambio | Dónde |
|---|---|---|
| 1. El camino en los hechos | Si la pregunta nombra dos símbolos, la cadena del grafo entre ellos (en cualquier sentido), **cada salto con la línea de su llamada** | `memoria_consulta.hechos_de_la_pregunta`, `API.camino_con_llamadas` |
| 2. Hechos pegados a la pregunta | En modo general van después del paquete, no arriba de todo | `app.py` `ai_chat` |
| 3. Hechos de configuración | Las apariciones de una clave, separadas en «la lee» (`x.get("k")`, `x["k"]`), «la escribe» (`x["k"] =`, `setdefault`) y «solo en un diccionario literal» (un valor por defecto); para un símbolo nombrado, las claves y variables de entorno que lee; y el aviso **«possible misspelled key»**: una clave que aparece en un solo lugar y difiere en una letra de otra leída que aparece en varios. En la copia limpia de Prig, 0 avisos en 45 claves; en la de E8, exactamente B6 | `memoria_consulta._hechos_de`, `_claves_sospechosas` |
| 4. Ruido de los llamadores por texto | No cuentan: el atributo de un objeto local pasado como valor (`Maquina(maq.radiografia)`: solo si lo de antes del punto es un módulo importado, una clase o `self` en el archivo propio), la instancia de otra clase con un método homónimo (`file_mgr = FileManager()` → `file_mgr.delete_item`) ni la función homónima de otro módulo (`detector.radiografia`); la instancia de la clase buscada se marca («instancia de BookService»); los llamadores en tests van aparte, contados | `memoria_consulta.API._llamadores_por_texto`, `_nombres_importados`, `_instancias_de` |
| 5. La última ronda sin cambiar el prefijo | Cuando se le pide responder (última ronda o dos consultas repetidas), las herramientas siguen en la petición; una consulta que pida igual no se ejecuta y recién entonces hay una ronda más sin herramientas | `ai_engine_class.chat_eventos` |

Con los casos reales: `P.llamadores("Gestor.radiografia")` da exactamente sus 4 llamadores (antes, más `calibrar` y `detector.radiografia`); `delete_item` de `book_service.py`, solo `delete_book` («instancia de BookService»; antes, también `file_mgr.delete_item`); `progreso.historial`, `comprobar` y `load_state` conservan los llamadores reales que E7 echaba de menos. Tests: 7 nuevos (`TestHechosT7`, la consulta en la última ronda) y 3 actualizados; cada uno falla sin su cambio; la batería, 1030 tests sin fallos. Nada toca el prefijo guardado de las unidades.

**Re-medición** (sistema congelado `68a29512…`; los recorridos con líneas, `ceaa9911…`; mismas condiciones que T7): 36 respuestas, ninguna vacía ni agotada.

| Pregunta | T7 general | T7 unidad | Ahora general | Ahora unidad |
|---|---|---|---|---|
| ind_15 llamadores por instancia global | P, C | C, C | C, C | C, C |
| ind_16 llamadores por fábrica | P, C | C*, C* | P (omite uno de los hechos), C | **C, C** (sin el falso positivo) |
| 12bb impacto | P, C | C, C | C, C | C, C |
| a84a lectoras de una clave | P | P | **C, C** | **C, C** |
| d408 recorrido | I | I | **C, C, C** | **C, C, C** (van a general) |
| 0b5f recorrido | I | I | C, I, I, I | I, I, I, P (van a general) |
| control (constante) | C | C | C (línea mal) | C (línea mal) |
| E8 B6 clave mal escrita | no | no | **sí, sí** | **sí, sí** |

- **Arreglado**: a84a (antes parcial en todas las muestras), d408 (6 de 6 con el camino en los hechos), el falso positivo
  sistemático de unidad en ind_16, las invenciones de 12bb y **B6, el error que ningún test detecta**: 4 de 4, con la
  línea, el caso y el arreglo; una respuesta cita el aviso del banco.
- **Sigue fallando 0b5f** (1 de 8 y un parcial), con y sin la línea de cada llamada: el modelo considera «borrar
  parciales» y «librerías disponibles» flujos sin relación, llama «falsa» o «imposible» a la cadena del banco y confunde
  «llama directamente» con «la ejecución pasa por». No es falta de información; el sesgo gana a la evidencia (con
  `think=False`).
- **Los dos modos quedan parejos.** En las cuatro preguntas que de verdad se responden en modo unidad, unidad 8 de 8 y
  general 7 de 8 (una omisión); los recorridos van a general en los dos. Correctas esperadas en las 11 de falla (las 6
  re-medidas y las otras 5 de T7), contando por el modo pedido como en T7: **9,5 y 9,5** (con la tanda de recorridos con
  líneas, 9,25 y 9,5). Es ruido de una respuesta.
- **Lo que sí los separa es el costo.** Unidad responde en 29 s de media en esas cuatro preguntas (11 consultas en 8
  respuestas) y el general en 45 s (16 consultas): el general lee el paquete en cada pregunta. A cambio, el modo unidad
  necesita las lecturas guardadas: hoy 109 estados, 28 GB.

**Decisión** (regla de T7: el general por defecto si queda a la par del de unidad, el control sigue correcto y en E8
encuentra al menos tantos menos uno): las tres condiciones se cumplen en la cuenta por modo pedido (empate; control
correcto; E8: B3 3 de 3 frente a 2 de 3 y B6 2 de 2 en los dos). Pasar a `general` con tope de 5 GB **borra unos 23 GB
de lecturas guardadas** y cuesta ~16 s por pregunta; mantener `auto` con 32 GB conserva esa velocidad. Lo decidió el
análisis de abajo.

### Decisión final: `auto` con 32 GB, y lo que se mejoró sin perder nada (10/10/2026)

El usuario pidió elegir lo mejor sin perder calidad. Las opciones, con lo medido:

| Opción | Exactitud | Velocidad | Disco | Qué se pierde |
|---|---|---|---|---|
| `general`, tope 5 GB | igual (9,5 de 11) | ~16 s más por pregunta | libera ~23 GB | velocidad, y borra 23 GB de lecturas |
| **`auto`, tope 32 GB** (el valor por defecto) | igual | la más rápida si la unidad está guardada | 28 GB, con tope y reserva de 20 GB | nada |
| `auto`, 10 GB por último uso | igual | rápida solo en lo usado hace poco | libera ~18 GB | velocidad en las unidades desalojadas |

**Queda `auto` con 32 GB y 20 GB de reserva** (ya son los valores por defecto: no se cambió la configuración ni se borró
nada). Ninguna respuesta depende de un estado: sin lectura guardada, la pregunta va al general, que ahora acierta lo
mismo; con lectura, el modo unidad responde antes. El caché no crece más allá del tope y quedan 103 GB libres.

Dos fallas que seguían, arregladas en la parte variable (no vencen ninguna lectura guardada):

- **El número de línea de las constantes** (mal en todas las muestras de T7: decía 22, 39, 35 o 20 por 60): las
  constantes de módulo no son símbolos del banco. Los hechos ahora traen «assigned at module level: ruta:línea: código»
  (`memoria_consulta._asignaciones_de`; no en la tabla de símbolos, que movería la partición). Con dos constantes nuevas
  además del control: **3 de 3 con la línea exacta**.
- **El idioma**: en modo unidad, con una unidad de código en inglés, una pregunta en castellano se respondía en inglés
  (1f14, 2 de 2). La guía lo pedía lejos de la pregunta; ahora va pegado a ella («(Responde en castellano.)»,
  `lectura_unidades.pregunta_con_contexto`): **3 de 3 en castellano**.

La redacción del camino también se hizo explícita («when the first one runs, execution reaches the last one… to deny it,
quote the line»); 0b5f siguió igual (1 de 4): no cambia nada más y se deja.

**El modo por defecto, medido entero** (`auto`, sistema `2f2520f6…`; una muestra por pregunta):

| | Resultado |
|---|---|
| Las 11 preguntas de falla de E7 | **10 de 11** (falla 0b5f; f46b con 3 de 4 endpoints, el criterio de E7). E7: 1 de 11; T7, primera serie: 5 (general) y 7 (unidad) |
| Constantes (control + 2 nuevas) | 3 de 3, valor y línea |
| E8, los 4 errores que ningún test detecta | **3 de 4** (B3, B6 y, por primera vez, B7), sin falsos positivos; B2 no. T7: 1 (general) y 0 (unidad) |
| Vacías, agotadas, estados nuevos | ninguna; ningún estado nuevo (todo restauró lecturas existentes) |

Tests: la batería, 1031 sin fallos (los de esta tanda fallan sin su cambio). Respuestas del modelo en el día: 62.

Pendiente: 0b5f (el modelo niega un camino real con la evidencia delante: un límite con `think=False`), el enrutador (las
palabras de una ruta nombrada cuentan como identificadores; sin efecto en la exactitud), B2 (nadie lo ve: haría falta
ejecutar la función, o `think=True`), y la limpieza de T8 (los estados que solo usa el estudio, con confirmación).

### Corrección de las fallas que quedaban (10/10/2026)

Cada falla, su causa (buscada antes de tocar nada) y lo medido después (40 respuestas; auditadas a mano):

| Falla | Causa | Arreglo | Antes → después |
|---|---|---|---|
| **0b5f** negaba un camino real | El paquete del modo general traía las dos puntas pero **no la función del medio** (`_carpeta_modelos_servidor`, la que llama a `estado`): el modelo le creía a lo que veía | El camino de los hechos trae el **código de las funciones intermedias** (entero si es corto; si no, la firma y la línea de la llamada, con su número) y dice que el camino indirecto es lo que se pregunta | 2 de 13 → **3 de 3** (y 3 C + 2 P de 5 con el código y la redacción anterior, que abría con «no pasa… de forma directa») |
| **f46b** sin `/api/progreso/resumen` | Los endpoints alcanzados salían solo del grafo; los llamadores por texto eran de un nivel | `API.alcance_por_texto`: sube hasta 3 llamadas por el grafo **y** por texto; un llamador por texto con homónimos solo se sigue si lo de antes del punto es el módulo que lo define (o su alias); también en `P.impacto` (`endpoints_por_texto`) | 3 de 4 → **4 de 4** (3 muestras; una agregó un endpoint de más) |
| Fábricas sin resolver | `gobernador().f()` no tenía clase | La clase sale del tipo de retorno anotado de la fábrica, si lo tiene; la de otra clase se descarta | test |
| **Enrutador** | Las palabras de una ruta nombrada (`backend`, `recursos`, `termico`) contaban como identificadores; una constante no es un símbolo | Se quitan las palabras de las rutas; una CONSTANTE suma donde se asigna | constantes: a general → **a su unidad** (3 de 3, con valor y línea) |
| **«Pensar» con banco: respuestas vacías** | `num_predict = 4096` de la configuración (que manda sobre el tope del chat): el razonamiento se comía todo | Con razonamiento, el tope del chat (16.384) manda si es mayor; el motor reserva ese espacio al elegir el contexto | vacía 4 de 4 → responde (pero ver abajo) |
| **Bucles de texto** («Espera, el error está en…» hasta el tope) | — | Si el final del texto ya apareció literal dos veces, se corta y se le pide la conclusión (una vez; las herramientas siguen en la petición). En 132 respuestas guardadas solo dispara el bucle real | test; no hubo bucles en la regresión |

**B2 sigue sin resolverse.** Sin razonar, en modo unidad lo encuentra cuando simula el corte por líneas en la consola: 2
de 6; las otras dan falsos positivos sobre el etiquetado de tramos. **Con razonamiento es peor**: una respuesta inventó un
error que no está en el código («línea 104: `actual = []`»; es `None`) y otra razonó 16.384 tokens y salió vacía. Por eso
el razonamiento **no** se activa solo (para 0b5f sí acertó, 1 de 1). Lo que lo resolvería es ejecutar la función con un
caso (una herramienta `P.probar` en un proceso aislado): es una decisión de seguridad (E5), no se hizo.

**Regresión final del modo por defecto** (`auto`, sistema `0d8e6643…`): Prig **10 de 11** (a84a parcial: en unidad omitió
la lectora directa, 3 de 4 en el día; ruido) y el control correcto en su unidad; E8 **3 de 4** (B3, B6 y B7 —este con el
caso de la excepción y `rollback`/`close` en `finally`—; B2 no). Ninguna vacía ni agotada. Tests: 5 nuevos y 2 ampliados,
cada uno falla sin su cambio; la batería, **1036 sin fallos**.

### «Sigue corrigiendo» y pausa (10/10/2026, 14:00) — estado y cómo retomar

**Hecho en esta ronda** (código y tests; la batería: **1044 sin fallos**; cada test nuevo falla sin su cambio):

| Falla | Arreglo | Dónde | Con el modelo |
|---|---|---|---|
| B2: revisando, el modelo solo podía reescribir la función a mano | **`P.cargar(ruta, sustituir={})`**: carga las funciones de un archivo .py en la consola para ejecutarlas con un caso. Cada definición pasa la **misma revisión que el código del modelo** (`revisar`: sin «_» en atributos, sin open/exec/getattr…, solo módulos permitidos), sin anotaciones de tipo, con los mismos builtins y en el mismo proceso aislado: **no amplía lo que la consola puede hacer**. Lo que no pasa queda en `.omitidos`; los ayudantes de otros módulos se reemplazan con `sustituir`. Solo funciona dentro de la caja | `memoria_consulta.API.cargar`, `_builtins_seguros`, `_SinAnotaciones`, `Cargado` | con la pista de abajo, B2 lo encontró **ejecutando** («tope 30 → (1, 30) y (32, 60): se salta la 31») |
| …pero el modelo no la usaba (0 de 3) | En una pregunta de revisión, los hechos sugieren ejecutarla («RUN it with a case…», con lo que hay que sustituir). Solo para funciones de primer nivel que pasan la revisión de la consola y cuyos ayudantes se sustituyen fácil (en E8a: B1 y B2) | `memoria_consulta._como_probarla`, `_REVISION` | B1 y B2: la usaron (2 y 7 veces) |
| B8: «communicate() vacía los buffers» (lo daba por correcto) | **Trampas conocidas** en preguntas de revisión: `communicate()` en un `except TimeoutExpired` sin `kill()` antes (documentación de Python). 0 avisos en la copia limpia; en la E8, solo B8 | `memoria_consulta._trampas` | B8: 2 de 2 (antes 0 de 3) |
| B5 sin aviso de clave mal escrita | Se cuentan **cadenas entre comillas del mismo lenguaje** («activa» es palabra y clase CSS) y la parecida se busca entre todas las cadenas | `_claves_sospechosas`, `_cadenas_del_codigo` | 0 avisos en la limpia; B5 y B6 en la E8 |
| Una frase en un f-string contaba como llamador | Se quita el texto de las cadenas antes de buscar | `_llamadores_por_texto` | los llamadores reales, idénticos |
| a84a en unidad: `P.hechos(r="lee_config")` daba 2 de 3 lectoras y el modelo respondía con eso | `P.hechos` de `lee_config`/`lee_entorno` con una clave suma las **lecturas literales**, marcadas «texto» (sin tocar el banco: cambiar el extractor obligaría a reindexar) | `API.hechos` | **sin medir todavía** |

**Validación** (sistema `f005dd92…`, modo `auto`; 21 respuestas, ninguna vacía ni agotada; las últimas 8 auditadas
solo provisionalmente, ver `resultados/texto-primero/notas.md`):

- Prig: ind_15, ind_16, f46b, 02bd y 12bb correctas; a84a parcial (antes del arreglo de `P.hechos`).
- E8a, 8 errores + 4 controles + 3 repeticiones: B1, B2 (2 de 3), B5, B6, B8 (2 de 2) detectados; **B3 y B4 no** esta vez
  (en la corrida anterior, sí): ruido entre corridas que hay que medir con más de una muestra; B7 dudosa. Controles: C1
  limpio; C2 y C3 señalan cosas reales (B3, que `resolve` usa; un JSON válido que no es objeto rompe `perfil`); C4 se
  contradice.

**Para retomar**

1. Auditar a mano las 8 últimas de la validación (`v_e8.json`: C4, B3, B7, B6, B4, B2 v2, B8 v2, B2 v3).
2. Congelar el sistema actual (`docs/estudio-banco/congelar_sistema.py`; incluye el arreglo de `P.hechos`) y medir a84a
   en unidad (×3) y B3/B4 en `auto` (×3 cada una), para separar ruido de regresión.
3. Documentar el resultado final de la ronda y actualizar el registro de pasos.
4. T8: la limpieza de los estados que solo usa el estudio, **con confirmación del usuario**.

Archivos: preguntas y respuestas en `~/.cache/prig-estudio/t7/` (`k_*`, `v_*`), copiadas en
`docs/estudio-banco/resultados/texto-primero/`. Nada quedó corriendo: el motor está detenido. No se hizo commit.

### Retomado y cerrado (10/10/2026, 17:15–17:45)

**Auditoría de las 8 pendientes** (a mano, contra el código): C4 limpio en la conclusión (con un arranque falso que se
corrige solo), B7 parcial, B6 / B2 v2 / B8 v2 detectados, B3 no («`startswith` es seguro»), B2 v3 no (falso positivo).
**B4 no, y por una razón nueva**: el modelo citó textualmente `return max(picos) if picos else None` —la versión
correcta, que **no está** en la copia: el banco tiene `return max(picos)` y ningún fragmento contiene la otra— y razonó
sobre su cita. Citó de memoria el código idiomático.

| Falla | Arreglo (en preguntas de revisión, salvo la primera) | Antes → después |
|---|---|---|
| a84a en unidad (2 de 3 lectoras) | `P.hechos` de una clave suma las lecturas literales (ver arriba) | 3 de 5 → **3 de 3** |
| B4: citaba de memoria la versión correcta | El **código literal** de la función (≤ 60 líneas, con números) va en los hechos, pegado a la pregunta: «quote THIS code, not from memory» | — |
| B4: aun con la cita correcta, no veía la lista vacía | Trampa: `max()`/`min()` de una lista **filtrada** sin `default=` ni comprobación (también sobre lo que se filtra: `elif entradas_orig:` la protege) | 0 de 3 → **3 de 3** |
| B7 y B3: «no tiene ningún error» en modo unidad, 1 de cada 3–4 | Trampas: `@contextmanager` con el `yield` fuera de `try/finally` (y sin `close`); `ruta.startswith(raiz)` como prueba de pertenencia (por partes del nombre: `database_url` no es una ruta) | B7 3 de 3, B3 3 de 3 |

Las trampas se ajustaron sobre este proyecto, así que sus falsas alarmas se midieron en todas las funciones de la copia
limpia (2147) y en el repositorio externo (71, que no se usó para ajustarlas): **0 falsas alarmas**, y en la copia
limpia **un aviso real**: `backend/desafios/catalogo_github.py:1159`, `path.startswith(ruta_sub)` deja pasar
`ejercicios_avanzados/…` si `ruta_sub` es `ejercicios` (un error latente del proyecto, no inyectado; no se tocó). Las
reglas solo se activan en preguntas de revisión: ninguna de las 11 de Prig las dispara.

**E8 con todo** (las muestras de esta ronda, sistema por sistema): B1 ✓ (arreglo correcto), B2 2 de 3 (con `P.cargar`,
ejecutando; la que falla no usó la pista), **B3 3 de 3, B4 3 de 3**, B5 ✓, B6 ✓, **B7 3 de 3**, **B8 2 de 2**. Controles:
C1, C3 y C4 limpios; C2 señala B3, real y en la función que `resolve` usa. En T7, el mejor modo encontraba **1 de 4**
de los errores que ningún test ve. Tests: la batería, **1047 sin fallos** (12 nuevos en la ronda, cada uno falla sin su
cambio).

Pendiente: B2 a veces (el modelo no siempre usa la pista de ejecutarla); la limpieza de T8, con confirmación; decidir
si se corrige el error latente de `catalogo_github.py:1159`.

### «Corrige todo» (10/10/2026, 17:45–18:30)

| Qué | Cambio | Resultado |
|---|---|---|
| El error latente de `catalogo_github.py` | `_dentro_de(ruta, carpeta)` en las dos comparaciones con `startswith` (l.1159 y l.1207) | test nuevo; «ejercicios» ya no deja pasar «ejercicios_avanzados/…» |
| B2: con la pista, el modelo no siempre ejecutaba la función | Si una pregunta de revisión sobre una función ejecutable (`memoria_consulta.sugiere_ejecutar`) se responde sin `P.cargar`, se le pide **una vez** que la ejecute con casos borde y confirme o corrija (`app.EJECUTALA`) | las 4 respuestas la ejecutaron; **2 de 4** detectan B2 (las otras eligieron casos que no pasan por el corte por líneas) |
| «Pensar»: si el razonamiento llena el tope, respuesta vacía | Se responde de nuevo **sin razonar**, con un aviso (`app.SIN_RAZONAR`) | test; en vivo, B2 con «Pensar» respondió dentro del tope (14.243 tokens) y lo **detectó** |
| Idioma en modo unidad | El recordatorio pide castellano «desde la primera línea» | 4 de 5 empiezan en castellano (una abrió en inglés) |
| T8: limpieza (confirmada por el usuario) | Se borraron los **21 estados que solo usaba el estudio** (20 de sus bancos y el de la ronda final de B2 en T7, sin banco): **5,24 GB**; antes de borrar se comprobó que ninguno figuraba en las lecturas de un banco real | quedan 88 estados (23 GB), todos de lecturas del banco real de Prig; 108 GB libres. `~/.cache/prig-estudio` (377 MB: copias, bancos del estudio, un respaldo del banco del 30/09) **no se tocó** |

Un dato de la limpieza: el registro de lecturas del banco real tiene 97 entradas y **9 ya no tenían su archivo antes
de borrar** (ninguna está entre las borradas hoy; vienen de antes: el tope del caché o el error de `reasignar` del 03/10,
ya corregido). Esas unidades van al modo general o se releen al usarse.

**Estado final de la revisión de código (E8, los 8 errores que ningún test detecta, modo `auto`)**: B1, B3, B4, B5, B6,
B7 y B8 de forma estable (las últimas muestras, todas detectadas); **B2 ~ la mitad** (lo encuentra cuando el caso que
ejecuta pasa por el corte por líneas; con «Pensar», 1 de 1). Controles limpios. Tests: **1051 sin fallos**.

## Registro de pasos

| Paso | Estado | Fecha | Hallazgo principal |
|---|---|---|---|
| E0 Método y plan | hecho | 30/09/2026 | este documento |
| E1 Mapa de datos e invariantes | hecho (corregido en la revisión) | 30/09/2026 | grafo íntegro; la memoria de resoluciones contamina el modo general (~30 %); lectura cubre el 63 % (todo el código, nada de tests); disco: SSM fijo 24 %, tarjeta 21 % |
| E2 Exactitud de la extracción | hecho | 30/09/2026 | grafo Python ≈98,5 % preciso (≈100 % sin «única») y ≈90 % de cobertura; endpoints del Hub sin prefijo; `llama_api` 78 %; `lee_config` ~50 % |
| E3 Partición y unidades | hecho (corregido en la revisión) | 30/09/2026 | determinista y sin cascadas, 70 % de cohesión; una sesión real de trabajo invalida 24 de 94 unidades, casi todo por código que cambió (los encabezados no influyen); 37 % de las preguntas necesita 2+ unidades |
| E4 Motor y máquina | hecho | 30/09/2026 | estado = 10,9 KB/token + 66 MB (explicado al 100 %); restaurar es exacto bit a bit, 0,09–0,22 s; lectura 626 tok/s; generación 31 tok/s a 20K; el límite de escala es el disco |
| E5 Consola P | hecho | 30/09/2026 | métodos correctos salvo los errores heredados del grafo (`api` del Hub, `impacto` corto) y una ambigüedad resuelta en silencio; límites funcionan; aislamiento solo a nivel de lenguaje |
| E6 Validez del examen | hecho | 30/09/2026 | respuestas correctas 95 % (auditoría de 40); 12,5 % de preguntas con esperado defectuoso; la «regresión» 97,7 → 90,6 % era cambio de preguntas; examen independiente de 27 preguntas listo |
| Revisión crítica E1–E6 | hecho | 30/09/2026 | 5 afirmaciones corregidas (contaminación, disco, encabezados, «única» en JS, regresión); omisión principal: todo medido sobre Prig |
| Correcciones 1 y 2 + generalización | hecho | 30/09/2026 | hechos verificados (endpoints 378/378, frontend 328/328); memoria aislada; repositorio externo: Python generaliza, React/TS casi ciego; 3 bugs de infraestructura corregidos (pasada que pisaba registros, desalojo de estados válidos, medir mientras se modifica) |
| E7 piloto y serie del 02/10 | descartados | 30/09–03/10 | el piloto pudo correr con vectores; la serie del 02/10 tuvo la clave del examen al alcance del modelo (citó la rúbrica); se descubrieron tres vías de filtración |
| E7 serie limpia, lotes 1–2 de 15 (Prig) | hecho, verificado y auditado | 03/10/2026 | 21 de 24 correctas a mano; huecos del grafo → respuestas falsas y seguras; confusión de nombres parecidos; la clave del examen también falla (lambda) |
| E7 serie limpia, lotes 3–5 (Prig) | hecho, verificado y auditado | 03/10/2026 | 51/5/4 de 60 a mano (lotes 1–5); respuestas sin tope de tokens (bucle de 32K) y bucle de consultas → tope de 600 s en el arnés; 4 defectos de clave; hueco del grafo con instancias globales (4 casos); bug de `reasignar` con estados compartidos |
| E7 serie limpia completa (Prig) + 2 repeticiones | hecho, verificado y auditado | 03/10/2026 | **157/13/10 de 180** a mano; modo unidad 86 % frente a general 97 %; ruido bajo (23 de 24 veredictos iguales); 11 claves defectuosas; el corrector dio 1,0 a 4 respuestas no correctas |
| Arreglo de `reasignar` (estados compartidos entre bancos) | hecho, con test | 03/10/2026 | el test falla sin el arreglo |
| E7 externo | parcial | 03/10 y 09/10 | lote 1: 9/1/2 a mano; el examen de frontend no es válido en React/TS (tipos como funciones); el grafo de TS no ve funciones importadas. Cortado a pedido |
| E8 | preparado; sin correr con el modelo | 03/10/2026 | los tests de Prig detectan **3 de 8** errores realistas inyectados |
| E9 | E9b hecho; E9a y E9c preparados | 03/10/2026 | aviso de notas por archivo: una falsa alarma y una omisión; las fichas no se usan |
| Sistema congelado para medir | hecho | 09/10/2026 | el backend cambió entre sesiones; el estado del 03/10 no era reconstruible |
| **Implementación de lo medido** | hecho, con tests | 09/10/2026 | 9 cambios (tope, consultas repetidas, hechos para el modo unidad, llamadores por texto, memoria, vacías, notas, examen); ver «Implementación de lo medido» |
| E10 (costos y veredicto) | no se hizo: se pasó a implementar | | lo esencial está en E3–E4 (disco y tiempos) y en el resumen de E7 |
| Plan «texto primero», fases A y B | hecho, con tests | 09/10/2026 | tope configurable del caché de estados (0 = no guardar), modo del banco auto/general/unidad con su motivo, hechos del banco también en modo general, lectura al vuelo; ver `docs/plan-texto-primero/` |
| **T7: medición corta** | hecho, auditado a mano | 09/10/2026 | 52 respuestas, ninguna vacía ni agotada; de 7 incorrectas en E7 a 2 (los recorridos: `P.camino` los resuelve); en las 11 de falla, general 6,0 frente a unidad 7,5 → **queda `auto` y 32 GB**; los hechos pegados a la pregunta: 3 de 3 en general; E8 con `think=False`: solo B3; la última ronda sin herramientas relee la unidad; ver «Texto primero: medición corta» |
| **Propuestas de T7 implementadas y re-medidas** | hecho, con tests, auditado a mano | 10/10/2026 | camino con la línea de cada llamada, hechos al final en general, claves leídas/escritas/definidas y «¿clave mal escrita?», llamadores por texto sin ruido, última ronda sin cambiar el prefijo; 36 respuestas: a84a, d408 y **B6** (4 de 4) arreglados, 0b5f sigue; los modos quedan parejos (9,5 y 9,5): unidad es ~16 s más rápido, general no necesita 28 GB de estados |
| **«Corrige todo» y limpieza de T8** | hecho, con tests, auditado a mano | 10/10/2026 | error latente de catalogo_github corregido; empujón a ejecutar (B2 2 de 4, siempre ejecuta); «Pensar» ya no queda vacía; 21 estados del estudio borrados (5,24 GB), 88 del banco real intactos; 1051 tests |
| **«Sigue corrigiendo»** | hecho, con tests, auditado a mano | 10/10/2026 | `P.cargar` (ejecutar la función real en la caja, mismas reglas), pista de ejecutarla, trampa de TimeoutExpired, claves mal escritas por cadenas, llamadores sin cadenas, `P.hechos` con lecturas literales; más el código literal en revisión y trampas de max/contextmanager/rutas; a84a 3 de 3; E8: B3, B4, B7 3 de 3, B8 2 de 2, B2 2 de 3; 0 falsas alarmas en 2147 + 71 funciones (y un error latente real en catalogo_github.py:1159) |
| **Corrección de las fallas que quedaban** | hecho, con tests, auditado a mano | 10/10/2026 | 0b5f 3 de 3 (el código de la función del medio en el camino), f46b 4 de 4 (endpoints a 3 llamadas por texto), constantes a su unidad, «Pensar» sin respuestas vacías, corte de bucles; B2 sigue (2 de 6; razonar es peor: haría falta ejecutar); modo por defecto: Prig 10 de 11, E8 3 de 4 |
| **Decisión final y modo auto medido** | hecho, auditado a mano | 10/10/2026 | queda `auto` con 32 GB (nada se pierde ni se borra); constantes con su línea (3 de 3) y el idioma pegado a la pregunta (3 de 3); el modo por defecto: 10 de 11 preguntas de falla, E8 3 de 4 sin falsos positivos |
