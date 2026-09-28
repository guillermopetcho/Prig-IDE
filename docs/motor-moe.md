# Motor MoE: Qwen3.6-35B-A3B con expertos en la GPU

Qwen3.6-35B-A3B es un modelo de *mezcla de expertos*: 40 capas con 256 expertos cada una, de
los que cada token usa 8. Pesa 20 GB en 4 bits y no cabe en una GPU de 6 GB. Ollama lo reparte
por **capas enteras**: unas pocas en la GPU y el resto en la RAM.

El motor MoE de Prig lo reparte por **expertos** y hace trabajar a la vez a la CPU y a la GPU.
Para el resto de Prig es un modelo más, `qwen3.6-35b-moe:prig`: aparece en los selectores y
admite razonamiento, herramientas y «Continuar».

## Resultado

RTX 4050 Laptop (6 GB), i5-13420H, turbo apagado, 4 hilos en los núcleos P. Generación real
de 256 tokens (scikit-learn, PyTorch, XGBoost en C++, statsmodels), sin otros programas pesados
abiertos.

| Configuración | Velocidad | CPU por token | CPU máx. |
|---|---|---|---|
| Ollama (7 capas enteras en la GPU, con turbo) | 27,7 tok/s | — | 83–93 °C |
| Expertos calientes en la GPU (48 por capa) | 36,9 tok/s | 58 ms | 57 °C |
| + MTP y CPU/GPU a la vez · **modo exacto** | **53,0 tok/s** | 51 ms | 55 °C |
| + omitir expertos fríos de peso < 0,08 · **modo equilibrado** | **59,6 tok/s** | 42 ms | 55 °C |
| + omitir expertos fríos de peso < 0,10 · **modo rápido** | **68,1 tok/s** | 33 ms | 55 °C |

La GPU se mantuvo en ~29 W y 57 °C en todas las pruebas.

### Solo lo necesario: sin razonamiento, sin extras, «Solo código»

La velocidad de arriba es por token. Lo que siente el usuario es el tiempo hasta tener la
respuesta, y ahí pesa más **cuántos tokens escribe el modelo**. Medido con un mismo pedido
(«función que cargue un CSV, rellene nulos con la mediana y entrene un RandomForest con validación
cruzada»):

| Cómo responde | Tiempo | Tokens | Qué escribe |
|---|---|---|---|
| Razonando (lo que hacía por defecto) | 95,9 s | 3.609 | 10.900 caracteres de razonamiento + explicación + código |
| Sin razonar | 16,2 s | 809 | explicación + código |
| **Solo código** | **~3 s** (156 tokens a 66,5 tok/s, sin contar el arranque del motor) | **156** | solo el bloque de código, sin comentarios |

- **Sin razonamiento salvo que se pida.** Qwen3.6 razona por defecto, y el chat de Prig no
  mostraba la opción «Pensar» para este motor, así que razonaba siempre. Ahora solo razona si se
  marca «Pensar».
- **Nada automático que no se pidió:** con este motor no se añaden citas de libros ni búsqueda
  web automáticas (una pregunta sobre el código del proyecto sumaba ~2.200 tokens de la web).
- **«Solo código»** (casilla en el chat, solo con este motor): no razona, reemplaza el prompt de
  tutor por uno que pide solo código sin comentarios ni docstrings, y **limita la salida con una
  gramática GBNF** a bloques de código, con `### Archivo: ruta` opcional para editar archivos
  enganchados. El modelo no puede escribir prosa. La gramática cuesta ~4 % de velocidad por token;
  MTP sigue funcionando (acierta ~71 %). Las explicaciones quedan para el modelo de «explicar».

**Calidad**, frente al modelo original. Divergencia KL por token y coincidencia del token más
probable, sobre ~9.000 tokens de texto que no se usó para elegir los expertos calientes (código
de Prig, documentación en español, C++):

| Modo | Perplejidad | Divergencia KL | Mismo token más probable |
|---|---|---|---|
| Exacto | = | 0 | 100 % |
| Equilibrado | +0,5 % | 0,037 | 93,1 % |
| Rápido | +1,6 % | 0,066 | 90,9 % |

Como referencia, pasar un modelo de 16 a 4 bits suele costar una divergencia de 0,02 a 0,05, así
que el modo equilibrado cuesta lo que un escalón de cuantización.

## Las técnicas

La base es [moe-autopilot](https://github.com/JigSawPT/moe-autopilot) (rama `aipc-hardening`
de JigSawPT/llama.cpp): en cada capa, los expertos calientes corren en la GPU y los fríos en la
CPU, y se suman. El parche de Prig
([`prig-moe.diff`](../backend/recursos/nativo/moe/prig-moe.diff)) añade el resto. Todo se activa
con variables de entorno, que pone [`motor_moe.py`](../backend/ai_engine/motor_moe.py).

1. **La CPU omite lo que ya calculó la GPU** (`AIPC_COLD_SKIP`). moe-autopilot seguía
   calculando en la CPU las 8 posiciones de cada token, y redirigía las calientes al experto 0.
   Con el turbo apagado, ese cálculo cuesta tanto como leer la RAM. Ahora esas posiciones llegan
   con id −1 y `mul_mat_id` de la CPU no las calcula.
2. **Sin relleno en la VRAM** (`AIPC_NO_PAD`). moe-autopilot reserva 8 espacios en cero por capa
   (~570 MB) para que CUDA nunca vea ids repetidos. Con hasta 4 tokens por paso, CUDA usa el núcleo
   vectorial MMVQ, que calcula cada par (token, experto) por separado y los admite.
3. **Decodificación especulativa con MTP** (`--spec-type draft-mtp`). El GGUF trae una capa extra
   que propone 2 tokens, y el modelo los verifica de una sola pasada. Acierta el 80–92 % en
   código, y el resultado es el mismo que sin ella. Para que ayude, el reparto caliente/frío tuvo
   que cubrir también la verificación (2–4 tokens por paso). Sin eso, MTP empeoraba
   (31 frente a 35 tok/s).
4. **CPU y GPU a la vez** (`AIPC_OVERLAP`). Antes cada capa iba por turnos: cuando la CPU
   necesita un dato de la GPU, el planificador de ggml espera a que la GPU termine todo lo que
   tiene encolado. Ahora el grafo ordena cada capa así:
   1. se copian a la CPU la entrada y los ids fríos, y eso solo espera al router;
   2. se encola la cadena caliente en la GPU;
   3. la CPU calcula la fría sin esperar a la GPU;
   4. la GPU suma los dos resultados.

   Para lograrlo, las copias calientes tenían que estar en un búfer marcado como «pesos». Si no,
   el planificador las llevaba a la CPU y copiaba 81 MB por capa y token: 2 tok/s.
5. **Omitir expertos fríos de poco peso** (`AIPC_COLD_DROP`, modos equilibrado y rápido). Los 8
   expertos de cada token se mezclan con pesos distintos. Los fríos que pesan menos que el umbral
   no se calculan, y su peso pasa a 0. Los calientes se calculan siempre, porque en la GPU no
   cuestan. Es la forma más barata de ahorrar CPU que se encontró.

## Proyectos grandes: contexto hasta 262.144 tokens

El modelo admite 262K tokens de contexto, y aquí se aprovechan en una GPU de 6 GB:

- **Caché de atención en 8 bits** (`-ctk/-ctv q8_0`): la mitad de VRAM. Solo 10 de las 40 capas
  guardan contexto, así que 128K ocupan 1,36 GB.
- **Lectura en lotes grandes.** Al leer, la GPU trae cada experto por PCIe una vez por lote; con
  lotes más grandes, cada experto sirve para más tokens. Medido con 26.600 tokens del proyecto:
  lote 512, 273 tok/s; 1024, 439; 2048, 646; 4096, **815 tok/s**. El trabajo de la CPU baja a
  menos de la mitad, y la GPU pasa al 88–96 % de uso con 38 W y 63 °C.
- **Contexto automático** (por defecto). El motor arranca con 32K. Si una petición no cabe (lo
  estima por caracteres o se lo dice `llama-server`), se reinicia con el siguiente tamaño:
  64K, 128K o 256K (~15 s). Más contexto deja menos VRAM para expertos calientes:

  | Contexto | Lote | Calientes por capa (con MTP) | Leer | Generar a esa profundidad |
  |---|---|---|---|---|
  | 32K | 4096 | ~24–29 | 815 tok/s | 44–57 tok/s |
  | 64K | 2048 | ~31 | ~650 tok/s | — |
  | 128K | 2048 | ~10 | 480–530 tok/s | 21 tok/s a 100K tokens |
  | 256K | 1024 | 0–2 (sin MTP) | — | — |

  Con 128K, MTP con 10 calientes rinde más que 25 calientes sin MTP (21,3 contra 19,7 tok/s).
  Medido de punta a punta desde Prig: leyó 70.134 tokens del código de Prig a 529 tok/s y
  respondió bien. CPU máx. 60 °C, GPU máx. 66 °C y 42,5 W (tope de la tarjeta: 50 W y 87 °C).
- **Lo ya leído se queda en RAM** (`--cache-ram`, 16 GB). Una segunda pregunta sobre el mismo
  proyecto reutilizó 20.082 de 24.178 tokens: 6,7 s en lugar de 31 s.

**VRAM base medida** (sin expertos calientes, caché q8_0), con la que `motor_moe.py` calcula
cuántos caben. CUDA deja usar ~5.770 de los 6.141 MB:

| Contexto | Lote | Sin MTP | Con MTP |
|---|---|---|---|
| 16K | 4096 | 2.375 MB | 3.075 MB |
| 32K | 4096 | 2.673 MB | 3.447 MB |
| 64K | 2048 | 2.689 MB | 3.367 MB |
| 128K | 2048 | 3.739 MB | 4.799 MB |
| 256K | 1024 | 5.305 MB | no cabe |

### Proyectos guardados en disco

Cuando enganchas archivos en el chat (o el proyecto entero con «Seleccionar todos»), Prig los
manda en su propio mensaje, antes de la pregunta. El código del editor, las citas y la web van con
la pregunta, porque cambian en cada una. Con eso, el motor puede **leer el proyecto una sola vez**:

1. Detecta el primer mensaje grande del usuario (más de 12.000 caracteres) que tenga la pregunta
   después. Genera con `/apply-template` el texto exacto que ve el modelo hasta ahí, sin el
   comienzo de la respuesta.
2. **La primera vez**, lee solo ese texto (`n_predict: 0`) y guarda el estado del modelo en
   `~/.cache/prig-moe/proyectos/`. Tiene que ser el estado **exacto** al final del proyecto: las
   capas SSM de este modelo no pueden retroceder.
3. **Las siguientes**, en la misma sesión o después de cerrar Prig, lo restaura (~0,1–0,6 s) y
   solo lee la pregunta.

La clave es una huella del texto, de la versión del motor y del modo. Si un archivo cambia, el
proyecto se vuelve a leer: nunca se sirve un estado viejo. Se guardan hasta 20 GB; al pasarse, se
borran los usados hace más tiempo.

Medido desde Prig, con 15 archivos de `backend/recursos` (49.310 tokens):

| Pregunta | Proyecto | Tiempo total |
|---|---|---|
| 1.ª | leído y guardado en 96–123 s (~600 MB) | 140–163 s |
| 2.ª | restaurado en 0,2–0,65 s | 6,5–13 s |
| tras cerrar y reabrir Prig | restaurado en 0,46 s | 34 s (15 s son el arranque del motor) |

En el chat, la línea de métricas lo indica («proyecto restaurado (49.310 tokens en 0,3 s)»). En
**Temperaturas → Motor MoE** se ve cuántos hay guardados y se pueden borrar.

**Dos correcciones que salieron de estas pruebas:**

- **El modo frío arranca sin rampa cuando el turbo está apagado.** La rampa desde el 30 % evita
  el salto del turbo (50 → 90 °C en segundos). Sin turbo no hay salto, y tardaba ~23 s en llegar
  al 100 % con la CPU a 47 °C.
- **El fijador de CPU del modo suave ya no toca el motor MoE.** Como usa el mismo GGUF que el
  modelo de Ollama y no aparece en su `/api/ps`, el fijador le habría puesto todos los núcleos,
  deshaciendo su fijación a los P.

Resultado desde Prig, con el turbo apagado y el modo frío activo: CPU a 41–54 °C, proyecto de
49.761 tokens restaurado, código a 30 tok/s y explicaciones a 17–19 tok/s. La cabeza MTP acierta
menos en prosa larga en español (56–72 %) que en código (80–92 %).

### Lista caliente por proyecto (sin reiniciar el motor)

Al leer un proyecto, el motor cuenta qué expertos usa cada capa (`AIPC_CONTAR`, en el planificador
de ggml, donde ya se leen los ids de cada lote). Con eso arma la lista caliente del proyecto: los más
usados al leerlo; los empates, en el orden de la lista global. La sube a la GPU sin reiniciar
(`POST /aipc/calientes`: copia los expertos a los espacios ya reservados y rehace las tablas; 40 capas
en 0,18 s) y la guarda junto al estado del proyecto. Al restaurar el proyecto se aplica la suya.

Medido directamente, contando en la CPU cuántos expertos elegidos al generar ya estaban en la GPU
(modo exacto, proyecto de 49.000 tokens, 64K de contexto, 25 calientes por capa, 4 preguntas de
código):

| Lista | Aciertos en la GPU |
|---|---|
| Global | 30,7 % (23–37 %) |
| **Del proyecto** | **39,0 %** (30–44 %) |

La velocidad sube poco (~5 %, dentro del ruido): con 25 calientes por capa, casi todo el trabajo sigue
en la CPU. Rinde más cuanto más expertos calientes caben (contextos menores).

### Calidad: el núcleo en Q8 (y por qué no los expertos)

Para medir la calidad contra algo mejor que nuestro Q4, se construyó una **referencia Q8 con el
vocabulario recortado**: metadatos, vocabulario, embeddings y salida del Q4 recortado, y todo lo
demás del Q8_0 de unsloth (731 de 753 tensores). El Q8_0 original no sirve directamente: su
vocabulario tiene 248.320 tokens con otros ids. Todo se midió por el camino de generación (lotes de
4 tokens, con el reparto caliente/frío activo) sobre ~9.000 tokens.

| Variante | Perplejidad | Divergencia KL | Mismo token |
|---|---|---|---|
| Q4 completo | +2,1 % | 0,071 | 91,0 % |
| 40 calientes en Q4 | +1,6 % | 0,073 | 91,0 % |
| 40 calientes en Q6 | +0,6 % | 0,072 | 91,5 % |
| 28 calientes en Q6 (misma VRAM) | +1,0 % | 0,071 | 91,3 % |
| 20 calientes en Q8 (misma VRAM) | +1,2 % | 0,072 | 91,1 % |
| **Núcleo Q8 + expertos Q4** | **+0,1 %** | **0,022** | **95,2 %** |

**Poner los expertos calientes en más precisión no mejora nada medible**: los expertos Q4_K_S ya son
buenos. **La pérdida del Q4 viene casi toda del núcleo** (atención, SSM, router, experto compartido):
subirlo a Q8 recupera ~70 % de la calidad, y solo cuesta 0,7 GB más de VRAM (1,3 → 2,0 GB).

Con los modos (frente a la referencia Q8, y velocidad con MTP y solapamiento):

| Núcleo + modo | Divergencia KL | Mismo token | Velocidad |
|---|---|---|---|
| Q4 + equilibrado (antes, por defecto) | 0,083 | 90,2 % | ~66 tok/s |
| Q4 + rápido | 0,105 | 88,9 % | ~75 tok/s |
| Q8 + exacto | 0,026 | 94,8 % | — |
| **Q8 + equilibrado (ahora, por defecto)** | **0,041** | **92,3 %** | **~55 tok/s** |
| Q8 + rápido | 0,081 | 90,3 % | ~63 tok/s |

Las velocidades de la tabla son del banco de pruebas (contexto chico: 40 calientes con Q4, 30 con
Q8). Dentro de Prig el contexto automático arranca en 32K y deja menos VRAM para calientes; medido
con un pedido de ~1.500 tokens: **Q4 equilibrado 24 calientes/capa, 52–55 tok/s; Q8 equilibrado
14 calientes/capa, 46–48 tok/s** (5,1 GB de VRAM, GPU 65–70 °C).

El núcleo Q8 + equilibrado tiene **la mitad de pérdida** que el Q4 + equilibrado, a cambio de
~12–17 % de velocidad. En **Temperaturas → Motor MoE → Núcleo** se elige Q8 (calidad) o Q4
(velocidad). Para prepararlo: `backend/recursos/nativo/moe/preparar_nucleo_q8.sh` (descarga el
Q8_0 de 37 GB en paralelo, verifica su SHA-256 y construye el híbrido de 21 GB).

### Umbral de omisión por capa: probado y descartado

Omitir expertos fríos (umbral 0,15) solo en un grupo de 5 capas cambia mucho según la capa: capas
0–14 → divergencia KL 0,047–0,058; capas 20–29 → 0,018. Pero repartir el umbral según esa
sensibilidad **no mejoró** a los umbrales fijos: a igual calidad (KL 0,037), 63,8 contra 64,4 tok/s;
el perfil intermedio (KL 0,057) fue un 11 % más lento que el umbral fijo 0,10 (KL 0,066). Quedan
los modos con umbral fijo; `AIPC_COLD_DROP_CAPAS` sigue disponible en el motor.

## Qué se probó y se descartó

| Idea | Resultado |
|---|---|
| Usar los 12 núcleos | 12 hilos: 21 tok/s; 4 P + 4 E con MTP: la misma velocidad y 93 ms de CPU por token en lugar de 58. Generar lee de la RAM; más núcleos esperan y calientan. |
| Núcleos E en lugar de P | Mitad de velocidad con este modelo (14 contra 24–30 tok/s). |
| Sin espera activa de los hilos (`--poll 0`) | Igual velocidad y CPU: casi no giran en vacío. |
| Preferir expertos calientes en el router (`AIPC_HOT_BIAS`) | Funciona (sesgo 0,01: 67,5 tok/s), pero pierde más calidad que omitir fríos: con 0,01, KL 0,074; con 0,03 escribió `StratifiedKFout`. Queda disponible, sin usar. |
| 7 o 6 expertos por token | 7: 54,9 tok/s con KL 0,046. Omitir fríos da más velocidad por la misma calidad. |
| MTP proponiendo 3 tokens, o con corte por confianza | Peor o igual que 2 tokens. |
| Traer expertos por PCIe token a token (caché LRU) | Descartado: el PCIe (12 GB/s) es más lento que la RAM (21 GB/s) y con una sola GPU dio pérdidas en otras pruebas. |
| Traer por PCIe el experto frío de más peso de cada token y calcularlo en la GPU mientras la CPU hace el resto | Probado (MTP + solapamiento + equilibrado, pares alternados): **42,8 contra 68,9 tok/s**, y la CPU no trabajó menos (43 contra 37 ms/token). Leer los ids, sincronizar, una copia chica por PCIe y un tramo más de GPU en cada capa cuestan más de lo que ahorran con 1–4 tokens por paso. Haría falta traerlos por anticipado con núcleos CUDA propios. |

## Cómo se usa

1. Descargar el modelo:
   `ollama pull hf.co/Elsephire/Qwen3.6-35B-A3B-vocabulary-trimming-GGUF:Q4_K_S`.
   Es solo texto, sin archivo de visión, conserva el español e incluye la capa MTP.
2. Compilar el motor: `backend/recursos/nativo/moe/compilar.sh`.
   - No necesita root: instala CUDA 12.9 con micromamba.
   - Compila bajo un termostato a 72 °C en los núcleos E.
   - Deja todo en `lib/moe` (~900 MB), que git ignora.
3. Elegir `qwen3.6-35b-moe:prig` en **Configuración → Modelos por tarea** o en el chat.

**Temperaturas → Motor MoE** muestra el estado y los ajustes. Se aplican en el próximo arranque
del motor:

- **Modo:** exacto, equilibrado (por defecto) o rápido.
- **MTP:** activado por defecto; no cambia el resultado.
- **Contexto:** automático por defecto (32K → 256K según haga falta), o fijo.
- **Expertos por capa en la GPU.** `auto` pone los que caben:

  | VRAM | Medida en una RTX 4050 |
  |---|---|
  | Base | 1.711 MB + 0,0205 MB por token de contexto |
  | MTP | ~340 MB |
  | Cada experto caliente por capa | 68,65 MB |
  | Margen | 450 MB |

  Con 6 GB y 16K: 47 con MTP, 52 sin él. Si no cabe, el motor reintenta con menos expertos y
  después sin MTP.
- **Hilos:** `0` usa uno por núcleo P, hasta 4.

## Cómo funciona dentro de Prig

- **Arranque y parada:** arranca con la primera petición (~15 s) y se para tras `keep_alive` sin
  uso. Antes de arrancar descarga los modelos de Ollama de Prig.
- **Traducción:** las peticiones con el formato de Ollama se traducen al `llama-server` propio y
  la respuesta vuelve con el formato de Ollama. Al continuar un mensaje del asistente,
  `llama-server` repite lo ya escrito, y se quita.
- **Modo frío:** lo pausa por ciclos, pero no lo mueve a los núcleos E.
- **Gobernador de la GPU:** no lo corta por ritmo. Es un modelo híbrido, y retomar le obliga a
  releer casi todo el prompt.
- **Cierre:** se para al descargar modelos o al cerrar Prig. Si Prig se cae, al volver a abrirse
  cierra el servidor que quedó vivo.

## Temperatura

Con el turbo encendido, la CPU se calienta como con cualquier modelo en RAM y el modo frío frena
el motor para respetar su objetivo. Medido con el objetivo en 60 °C, antes de estas mejoras:
8,4 tok/s. Con el turbo apagado no hace falta frenarlo, porque todas las pruebas quedaron en
53–57 °C. Se apaga en **Modo frío → Energía de la CPU**. Cada mejora de esta página reduce
además el trabajo de CPU por token, de 58 a 33–51 ms: menos calor por token.

## Lo que queda

- **Lista caliente que aprende del uso.** Una lista hecha con la propia conversación acertaba
  +10 % más que la global (medido sin MTP). Sube los aciertos sin cambiar el resultado del
  modelo.
- **Umbral de omisión por capa.** Las últimas capas son las del idioma y probablemente las más
  sensibles. Un umbral por capa, calibrado con la divergencia KL, ganaría velocidad con la misma
  calidad.
- **Predecir los expertos de la capa siguiente** y traerlos por PCIe mientras la CPU trabaja,
  sumando el ancho de banda del PCIe al de la RAM. Es lo más complejo: exige streams de CUDA
  propios y un predictor.
- **N-gramas especulativos** para reescribir archivos (`--spec-type ngram-mod`), combinables con
  MTP.
