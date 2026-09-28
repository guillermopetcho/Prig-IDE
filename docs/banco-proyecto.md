# Banco del proyecto

Un modelo tiene un contexto finito y un proyecto grande no cabe. Releerlo en cada pregunta tampoco
sirve: Prig tiene ~1,9 millones de tokens, y el motor MoE lee ~800 tokens/s. El banco resuelve las
dos cosas con una memoria de trabajo indexada. El proyecto entero vive en un SQLite. A cada pregunta
el modelo recibe solo lo que le sirve y pide el resto con herramientas. El tamaño del proyecto deja
de depender del contexto del modelo.

Código: `backend/banco_proyecto.py`. Herramientas del modelo: `backend/herramientas_chat.py`.
Integración en el chat: `_preparar_banco` y `_chat_eventos` en `backend/app.py`. Interfaz:
`frontend/js/banco_proyecto.js`.

## Qué guarda

Un SQLite por carpeta de trabajo, en `~/.prig_bancos/<carpeta>-<hash>/banco.db`:

| Tabla | Qué contiene |
|---|---|
| `archivos` | Contenido comprimido (para calcular diffs), lenguaje, líneas, resumen del docstring y resumen del análisis con IA |
| `simbolos` | Clases, funciones y métodos con firma, docstring, líneas y clase padre. Python con `ast`; JS/TS, C/C++/CUDA, Java/C#/Kotlin, Go y Rust con patrones; Markdown por secciones |
| `fragmentos` | El código cortado por función (las clases como ficha: cabecera, doc y firmas de sus métodos), con índice FTS5 y un vector `bge-m3` |
| `usos`, `importaciones` | El grafo del proyecto: qué llama cada función y qué archivo importa a cuál |
| `cambios` | Cada archivo nuevo, modificado o borrado, con su diff y las funciones que cambiaron |
| `conocimiento` | Definiciones, teoría, decisiones, contexto y notas. Las escriben el usuario, el modelo (herramienta `anotar`) o el análisis con IA. Se marcan «por revisar» cuando cambia un archivo del que hablan |
| `resoluciones` | Cada pregunta respondida con el banco: resumen, respuesta completa, archivos, y si cambiaron después |

Qué se indexa: si la carpeta es un repositorio, lo que ve `git ls-files` (respeta `.gitignore`).
Si no, se recorre el disco sin `node_modules`, entornos virtuales, `build` y similares. Quedan fuera
los binarios, los minificados, los lockfiles y los archivos de datos de más de 200 KB.

## Cómo se mantiene al día

`sincronizar()` compara la fecha y el tamaño de cada archivo y solo relee los que cambiaron. De esos,
solo se re-embeben las funciones cuyo texto cambió: el vector se guarda por hash del fragmento.

| Paso | Prig (364 archivos, 130.000 líneas) |
|---|---|
| Indexado inicial | 5,8 s |
| Sincronizar sin cambios | 12 ms |
| Vectores de todo el proyecto (7.700 fragmentos) | 3,2 min en la GPU |

Un vigilante sincroniza cada 4 s la carpeta de trabajo activa. El chat también sincroniza antes de
cada pregunta, así que el modelo siempre ve el disco tal como está.

**Dónde se calculan los vectores.** `bge-m3` tarda 0,04 s por fragmento en la GPU y entre 0,5 y
1,1 s en la CPU. Por eso:

- **GPU libre** (sin motor MoE ni modelos de Ollama cargados): tandas de 128 fragmentos. El
  embebedor pide `num_gpu` de forma explícita, porque si no Ollama reutiliza la copia que una consulta
  dejó en la CPU. Además queda anotado como modelo de Prig, y el motor MoE lo descarga antes de
  ocupar la VRAM.
- **Con un generador en la GPU**: solo en la CPU, y solo si faltan 24 fragmentos o menos (lo que
  cambia con una edición). Un proyecto entero espera a que la GPU quede libre y, mientras tanto, la
  búsqueda por palabras funciona igual.

## Qué recibe el modelo en cada pregunta

1. **El mapa** (3.000 tokens por defecto) con carpetas, archivos, resúmenes y símbolos principales.
   Primero se pliegan los subárboles menos importantes (tests, datos, documentos) y después se detallan
   los archivos más usados por los demás. No lleva números de línea ni tamaños, así que no cambia al
   editar: con el motor MoE va en el mensaje fijo que el servidor reaprovecha entre preguntas.
2. **El paquete de la pregunta** (6.000 tokens por defecto):
   - Los cambios desde la última respuesta (hasta un 20 %), con los diffs de lo más relevante.
   - La memoria relacionada (hasta un 15 %), con aviso si puede estar desactualizada.
   - Las preguntas parecidas ya resueltas (hasta un 15 %), con aviso si sus archivos cambiaron después.
   - El código relevante con el resto del presupuesto, y como fichas lo que no entra, más las
     funciones que llama y las que lo llaman.
3. **Herramientas** (si el modelo las admite):
   - `consola`: la memoria de consulta, con el proyecto entero como objeto `P` en Python. Ver
     [memoria-consulta.md](memoria-consulta.md).
   - `buscar_proyecto` busca en todo el proyecto.
   - `ver_simbolo` devuelve el código completo de una función.
   - `anotar` guarda en la memoria.

   Con el banco activo el chat permite 16 rondas de herramientas en lugar de 6.

**Cómo se elige el código.** Se fusionan por rangos (RRF) cuatro señales:

- texto con BM25, con raíces por prefijo («guardan» → `guard*`);
- vectores cercanos al mejor;
- símbolos nombrados en la pregunta (`snake_case`, `camelCase`, entre comillas invertidas);
- rutas mencionadas.

Se descarta lo que no llega al 25 % del mejor resultado. Los tests pesan la mitad, salvo que la
pregunta hable de pruebas.

Con el motor MoE la búsqueda tarda 0,3–0,5 s por pregunta (la consulta se embebe en la CPU en
~0,1 s).

## Análisis con IA

En **Banco → Estado → Analizar con IA**, un modelo lee cada archivo y deja un resumen (que reemplaza
al del docstring en el mapa), hasta 6 definiciones del dominio y hasta 3 decisiones de diseño. Se
guarda el hash del archivo, así que solo se rehace lo que cambió. Por defecto usa el motor MoE si está
instalado; se cambia con `banco_modelo` en la configuración.

## Uso

- **Chat → Configuración → Banco del proyecto** activa el banco para la carpeta de trabajo. La primera
  vez la indexa.
- El botón de ajustes, al lado, abre el panel con cinco pestañas:
  - estado y acciones (sincronizar, reindexar, analizar, borrar);
  - la memoria (ver, añadir y olvidar);
  - las resoluciones;
  - los cambios con sus diffs;
  - «Probar una pregunta», que muestra exactamente qué recibiría el modelo.
- Ajustes: `banco_presupuesto` (tokens por pregunta) y `banco_mapa` (tokens del mapa), también desde
  el panel.

## Medido con el motor MoE

Copia de Prig (233 archivos, 5.361 fragmentos con vector). Las pruebas pasaron por el chat real
(`/api/ai/chat`, núcleo Q8, modo equilibrado, 32K de contexto), con el modo frío activo a 60 °C.

| | Sin banco | Con banco |
|---|---|---|
| Qué recibe el modelo | la pregunta (150 tokens) | mapa 3.000 + paquete 6.000 + pregunta (~11.400 tokens) |
| Búsqueda del banco | — | 0,27 s (3,2 s la primera vez, al cargar `bge-m3` en la CPU) |
| Lectura | — | ~430 tok/s con el modo frío (~815 sin él) |
| Generación | 15 tok/s | 8 tok/s |

Con el modo frío el motor va unas tres veces más lento que sin él (47–55 tok/s). La generación con
banco salió más lenta todavía; el motivo no se midió.

**La pregunta sobre cómo se decide cuántos expertos calientes van a la GPU:**

- **Primera versión de las reglas:** el modelo tenía delante `calientes_para` y `Motor.asegurar`
  literales, y aun así inventó funciones (`_calcular_calientes`) y constantes que no existen. La
  documentación iba antes que el código y la instrucción solo pedía «no suponer».
- **Con las reglas actuales** (código literal primero, documentación aparte, prohibido inventar
  nombres o valores y obligatorio buscar lo que falte): el modelo llamó a `ver_simbolo`, citó la
  fórmula y las constantes reales con sus líneas y dejó una resolución guardada.

**Después de editar `calientes_para`** (margen doble con MTP): el vigilante registró el cambio, y la
siguiente pregunta recibió «1 archivo cambiado desde la última respuesta» con el diff. El modelo
explicó el cambio línea por línea y qué implicaba (menos expertos calientes con MTP).

**Una resolución errónea también se guarda.** Por eso las resoluciones llegan al modelo marcadas
como «no verificadas: contrástalas con el código actual», y se pueden borrar desde el panel.
