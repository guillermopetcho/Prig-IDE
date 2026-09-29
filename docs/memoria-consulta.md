# Memoria de consulta: contexto ilimitado para el modelo

Bitácora de diseño y de hallazgos, para seguir avanzando. Complementa
[banco-proyecto.md](banco-proyecto.md), que describe el índice sobre el que trabaja.

## La idea

Un modelo no necesita tener el proyecto en su contexto: le basta con poder preguntarle cosas con la
precisión de un programa. Por eso el banco no se le entrega como texto. Es un objeto, `P`, dentro de
una consola de Python que el propio modelo maneja con la herramienta `consola`:

- **Tamaño ilimitado.** El modelo recorre millones de tokens con un bucle y solo trae al contexto lo
  que imprime, recortado a 6.000 caracteres. Lo intermedio queda en variables, fuera del contexto:
  es su memoria de trabajo.
- **Consultas exactas.** `P.hechos` y `P.sql` responden preguntas que la búsqueda aproximada no
  puede responder, del tipo «qué endpoints no llama nadie» o «quién lee la clave `moe_modo`».
- **Recursión.** `P.llm(pregunta, contexto)` le pide al mismo modelo que lea un trozo con un
  contexto limpio y devuelva lo esencial. Un bucle de `P.llm` es un map-reduce sobre el proyecto
  entero.
- **Memoria entre sesiones.** `P.guardar` y `P.recuperar` guardan resultados; `P.anotar` y
  `P.afirmar` agregan conocimiento y hechos al grafo.

Código:

- `backend/memoria_consulta.py`: la API, el proceso aislado y la sesión.
- `backend/banco_proyecto.py`: el grafo de hechos, los resúmenes jerárquicos y el analista.
- `backend/herramientas_chat.py`: la herramienta `consola`.
- `backend/app.py`: la sesión por respuesta, `P.llm`, la guardia del analista y
  `/api/banco/consola`.
- `frontend/js/banco_proyecto.js`: las pestañas Consola y Estado (analista).

## Ideas tomadas y cómo se adaptaron

| Idea | Origen | Aquí |
|---|---|---|
| El contexto largo como variable de un entorno, con llamadas recursivas al modelo | Recursive Language Models (Zhang y Khattab, 2025) | `P` en una consola Python; `P.llm` con el mismo modelo; hasta 12 subllamadas por ejecución |
| Acciones como código ejecutable en lugar de JSON | CodeAct (Wang et al., 2024) | una sola herramienta `consola`, en lugar de una herramienta por consulta |
| Memoria jerárquica que el modelo gestiona | MemGPT / Letta | variables (trabajo), `P.guardar` (entre sesiones), `P.anotar` (conocimiento) |
| Grafo de propiedades del código consultable | Code Property Graph (Joern) | vista `grafo` (hechos + llamadas + imports + definiciones) consultable por SQL |
| Árbol de resúmenes para recuperar a distintos niveles | RAPTOR (Sarthi et al., 2024) | resúmenes de archivo → carpeta → proyecto, rehechos solo si cambia su entrada; el mapa los usa |
| Mapa del repositorio por importancia | Aider repo-map | el mapa detalla primero los archivos más usados por los demás |

## El grafo de hechos

Se extrae al indexar, sin modelo: Python con `ast`, JS y HTML con patrones, C con `getenv`.

| Relación | Ejemplo |
|---|---|
| `define`, `llama`, `importa` | `ai_chat llama post` (con la línea de la llamada) |
| `hereda`, `atributo` | `Motor atributo _contexto_pedido` |
| `lanza`, `captura` | `Consola._atender lanza ValueError` |
| `lee_config`, `lee_entorno` | `_presupuesto_banco lee_config banco_presupuesto` |
| `expone` | `banco_mapa expone GET /api/banco/mapa` |
| `llama_api` | `iniciarInterruptor llama_api /api/banco/activar` (frontend → backend) |
| `usa_dom`, `define_dom` | une el JS con los `id` del HTML |
| `ejecuta` | `subprocess` con el programa que lanza |

Medido en Prig: 368 archivos → 37.600 hechos en 7,9 s.

## Aislamiento de la consola

El código lo escribe un modelo, así que corre con estos límites:

- Proceso aparte (`python -I`), sin variables de entorno y con la base de datos abierta en solo
  lectura (`mode=ro`).
- El código se revisa antes de ejecutarse. Se rechazan:
  - los atributos que empiezan por `_`;
  - `eval`, `exec`, `open`, `getattr` y otros nombres peligrosos;
  - los `import` fuera de una lista de módulos puros;
  - `global` y `async`.
- Tope de 2 GB de memoria (`RLIMIT_AS`) y 30 s por ejecución (`SIGALRM`).
- Escribir (`anotar`, `afirmar`, `guardar`) y llamar a un modelo pasa por Prig.

Probado: todo eso se rechaza y la sesión sigue viva después. No es un sandbox de seguridad fuerte (el
formato de cadenas puede leer atributos), pero no puede escribir, abrir archivos, importar ni usar
la red.

## Analista autónomo

Desde **Banco → Estado → Analista autónomo**:

1. Analiza cada archivo pendiente: resumen, definiciones y decisiones.
2. Resume las carpetas de la más profunda a la raíz, y después el proyecto.
3. Queda vivo: cada 30 s mira si el vigilante registró cambios y rehace solo eso.

Antes de cada paso consulta una guardia (`_guardia_analista`) y espera si:

- hay una respuesta del chat en curso (el usuario siempre tiene prioridad);
- quedan menos de 6 GB de RAM libre;
- la GPU está a 3 °C o menos de su límite;
- la CPU está a 85 °C o más.

## Hallazgos

1. **Empalmar la caché KV por trozos no sirve con este modelo.** Técnicas como CacheBlend o
   TurboRAG precalculan la caché de atención de cada trozo y la concatenan. Qwen3.6-35B-A3B tiene
   30 de sus 40 capas SSM, con un estado recurrente que no se puede cortar ni pegar. Solo sirve
   guardar prefijos completos (lo que ya hace el motor con los proyectos). Por eso la memoria de
   «bajo nivel» se hizo en los datos y en la forma de consultarlos, no en la caché.
2. **Con el código literal delante, el modelo inventaba igual.** La prosa de la documentación iba
   antes y la instrucción era blanda. Con el código primero, la documentación aparte y reglas
   explícitas, citó la fórmula y las líneas reales.
3. **Ollama reutiliza la copia del embebedor que haya cargada.** Si una consulta dejó `bge-m3` en la
   CPU, las tandas «de GPU» iban a la CPU, 25 veces más lentas. Hace falta pedir `num_gpu` de forma
   explícita.
4. **El modo frío domina la velocidad en el chat real.** Con el objetivo de 60 °C, el motor MoE
   generó 8–15 tok/s por `/api/ai/chat`, contra 47–55 sin el control térmico. Cada ronda de
   herramientas vuelve a leer el contexto, así que las rondas cuestan.
5. **Las respuestas erróneas se guardan como resoluciones.** Por eso llegan al modelo marcadas «no
   verificadas».
6. **El grafo une backend y frontend sin ningún modelo.** De 337 endpoints expuestos en Prig, 99 no
   aparecen en ninguna llamada del frontend (algunos los usan otros clientes o tests).

7. **El modelo sabe manejar la consola sin ejemplos.** Pruebas por `/api/ai/chat`, con el motor MoE
   y el modo frío activo (copia de Prig, 235 archivos):
   - «¿Qué endpoints `/api/banco…` no llama el frontend?»: 5 rondas en 260 s. Se corrigió solo tras
     un `import` rechazado, cruzó endpoints con llamadas y leyó cada función. 3 de las 5
     conclusiones eran falsas porque el extractor no normalizaba las rutas con parámetros
     (`{id}` en el backend, `${id}` en el frontend). Con las rutas canónicas (`/api/x/*` en ambos
     lados), la misma consulta da la respuesta correcta.
   - «Resume cada archivo de `backend/recursos/` leyendo su código y di cuál controla la GPU»: 13
     llamadas a la consola en 586 s. Resultado: una tabla correcta de los 16 archivos y la mecánica
     de `Gobernador` con sus líneas. Eligió leer los docstrings con `P.leer` en lugar de gastar
     `P.llm`, que es lo más barato.
8. **Las rondas de herramientas no releen el contexto.** El servidor reutiliza el prefijo del slot:
   cada ronda lee solo lo nuevo (141 a 2.180 tokens, 2,3–5 s con el modo frío). Lo que cuesta es
   la generación (≈9 tok/s con el modo frío).
9. **El analista autónomo tarda 41–72 s por archivo con el modo frío.** Son 5 archivos de
   `backend/recursos`, lo que da unas 5–6 h para las 368 de Prig. Los resúmenes y definiciones son
   buenos. Las «decisiones» salen como títulos largos y algunas definiciones son triviales (nombres
   de módulos). La síntesis de carpetas tarda unos 21 s por carpeta (11 carpetas en 233 s) y el
   resumen del proyecto es correcto.

10. **El grafo de llamadas por nombre corto era engañoso.** 280 nombres están definidos en más de un
    archivo (`__init__` 112 veces, `buscar` 15), y `requests.post(...)` se confundía con
    `Motor.post`: `P.impacto("calientes_para")` devolvía medio proyecto. Ahora cada llamada guarda su
    receptor (nada, `self`, un módulo importado u otro objeto) y los alias de import, y una
    resolución global (0,2 s en Prig) la une al símbolo exacto:
    1. misma clase y sus bases;
    2. import;
    3. tipo de retorno anotado (`-> "Motor"`);
    4. nombre único del mismo lenguaje que no sea un verbo común de librería.

    Resultado en Prig: 6.522 aristas (5.480 exactas, 282 por nombre único, 760 aproximadas) en lugar
    de 27.000 ambiguas, sin cruces entre lenguajes. `P.camino("ai_chat", "calientes_para")` da la
    cadena real de 7 pasos con líneas, y el impacto de `calientes_para` son exactamente sus 6
    llamadores reales más 2 tests.

## Próximos pasos

- **Arquitectura unificada (referencia principal para seguir):** banco simbólico + pasada única con
  captura múltiple + tronco y ramas de estados + fichas verificadas + enrutador en el idioma del
  modelo. Ver [arquitectura-unificada.md](arquitectura-unificada.md).
- **Plan de lectura única:** leer el repositorio una sola vez, guardando fichas verificadas y una
  instantánea del motor por unidad, para acercarse a un modelo de contexto enorme. Ver
  [plan-lectura-unica.md](plan-lectura-unica.md).

- Afinar el análisis por archivo: título corto para las decisiones y descartar definiciones que son
  solo el nombre del módulo.
- Correr el analista con un modelo chico en la CPU cuando la GPU está ocupada, o por lotes de
  archivos chicos en una sola llamada, para bajar las 5–6 h.

- Medir cuánto cuesta `P.llm` en el chat. Cada subllamada ocupa el único slot del motor; la
  `--cache-ram` debería restaurar el contexto principal sin releerlo, pero no está verificado.
- Un modelo chico en la CPU para `P.llm` de extracción masiva, y dejar el MoE para razonar.
- Tree-sitter para extraer hechos exactos en JS/C++ (hoy son patrones).
- Aprender qué consultas funcionan: guardar las ejecuciones de la consola que llevaron a una buena
  respuesta y ofrecerlas como ejemplos (memoria procedimental).
- Hechos de tipos y flujo de datos (qué función escribe o lee cada clave o tabla), para preguntas
  de impacto de un cambio.
