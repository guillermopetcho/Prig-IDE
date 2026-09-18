# Extractor de conocimiento de Prig

Analiza libros con una GPU externa y produce un `.prigpack` por libro, que después
se carga en Prig para razonar en local.

Funciona **con o sin internet**: si el modelo está en disco, no hace falta conexión.

```
LOCAL                    GPU EXTERNA                    LOCAL
libros → chunks.jsonl  →  extracción por lotes  →  .prigpack  →  Prig
(sin GPU)                 (2×T4, ~30× más rápido)    (descargas)   (razona)
```

---

## 0 · Los seis campos y sus puentes

Cada libro declara a qué campo pertenece:

```
math · physics · cpp · python · machine_learning · deep_learning
```

No son seis bibliotecas separadas. El valor está en los **conceptos puente**, los que
aparecen en más de un campo:

```
math ──────► machine_learning ──────► deep_learning
  │                   ▲                    ▲
  └──► physics ───────┘         python ────┤
                                cpp ───────┘
```

`gradiente` es análisis matemático **y** descenso de gradiente. `convolución` es
física de señales **y** capa convolucional. Cuando el tutor explica algo, un concepto
puente le permite anclarlo en algo que ya sabes de otro campo.

Por eso el extractor pide en cada afirmación:

| Campo | Para qué |
|---|---|
| `bridges_to` | Qué otros campos conecta esta afirmación |
| `code_language` | `python`, `cpp`, `math`, `pseudocode` o `none` |
| `latex` | La fórmula, para poder renderizarla y compararla |
| `also_known_in` | Cómo llaman a este concepto en otro campo |

**Estos campos hay que pedirlos ahora.** Añadirlos después obliga a repetir toda la
extracción.

El dominio se propone solo por el título y el texto; conviene revisarlo, porque un
libro mal clasificado contamina todo lo que salga de él.

## 1 · Preparar el trabajo (en tu máquina)

Desde la aplicación: **Biblioteca → Preparar trabajo para GPU**. Elige los libros,
revisa el campo que se propone para cada uno y pulsa preparar. La carpeta queda en
`~/.prig_books/jobs/`.

O desde Python:

```python
import sys; sys.path.insert(0, "backend")
from job_exporter import JobExporter

ex = JobExporter()
libros = ex.libros_disponibles()          # PDFs y documentos de ~/.prig_books

# Con dominio explícito (recomendado)
ex.preparar([
    ("~/.prig_books/books/Apostol_Calculus.pdf",   "math"),
    ("~/.prig_books/books/Goodfellow_DL.pdf",      "deep_learning"),
    ("~/.prig_books/code/Effective_Modern_Cpp.pdf","cpp"),
], "./prig_job")

# O dejando que lo proponga por título y contenido
ex.preparar([b["path"] for b in libros], "./prig_job")
```

Un mismo libro guardado en dos carpetas se detecta por su sha256 y se incluye una
sola vez: procesarlo dos veces duplicaría los fragmentos y gastaría el doble de GPU
para nada.

Deja una carpeta con:

| Archivo | Qué es |
|---|---|
| `chunks.jsonl` | Un fragmento por línea, con libro y página |
| `manifest.json` | Libros, sha256 de cada uno, recuentos |
| `outline.json` | Índice detectado de cada libro |

**Se suben los fragmentos, no los PDF.** Es mucho más pequeño, el troceado es
determinista y así los libros originales no salen de tu equipo.

## 2 · Subir a Kaggle

Dos datasets privados:

1. **`prig-job`** — la carpeta `prig_job` del paso anterior.
2. **`modelo`** — los pesos del extractor. Descárgalos una vez y súbelos como
   dataset; así el cuaderno funciona con **internet desactivado**.

Y este mismo directorio (`prig_extract.py` + `extraction_schema.py`) como un tercer
dataset, o pégalo en una celda del cuaderno.

## 3 · Ejecutar en el cuaderno

Hay un cuaderno listo en este mismo directorio: **`prig_kaggle.ipynb`**. Súbelo a
Kaggle y ejecuta las celdas en orden; comprueba la máquina, los datasets y el
modelo antes de gastar cuota.

Acelerador: **GPU T4 ×2**. Internet: **On** solo para instalar vLLM.

### Las dos formas de usar las dos T4 (no son equivalentes)

**A · Reparto entre las dos GPU — recomendado.** Dos procesos, uno por GPU, cada
uno con la mitad de los fragmentos. Las T4 de Kaggle van por PCIe, no por NVLink:
repartir el *trabajo* rinde más que repartir el *modelo*, siempre que el modelo
quepa en una sola GPU (un 14B en AWQ ocupa ~9 GB de 15).

```python
import subprocess, time
procesos = []
for gpu in (0, 1):
    procesos.append(subprocess.Popen(
        ["python", "/kaggle/input/prig-worker/prig_extract.py",
         "--input", "/kaggle/input/prig-job",
         "--model", "/kaggle/input/qwen25-14b-awq",
         "--output", "/kaggle/working/packs",
         "--engine", "vllm", "--quantization", "awq",
         "--gpu", str(gpu),          # este proceso ve UNA sola GPU
         "--shard", f"{gpu}/2",      # y procesa la mitad de los fragmentos
         "--batch", "32"],
        stdout=open(f"/kaggle/working/gpu{gpu}.log", "w"),
        stderr=subprocess.STDOUT))
    time.sleep(20)
for p in procesos:
    p.wait()
```

**`--gpu` no es opcional aquí.** Sin él los dos procesos intentan ocupar la GPU 0
y el segundo muere sin memoria.

Después, **obligatoriamente**, el empaquetado final:

```python
!python /kaggle/input/prig-worker/prig_extract.py \
    --input /kaggle/input/prig-job --output /kaggle/working/packs \
    --model /kaggle/input/qwen25-14b-awq --pack-only
```

Cada proceso tiene solo su mitad de los fragmentos. Si empaquetara por su cuenta
produciría un `.prigpack` **que parece correcto y trae medio libro**: declara
exactamente las afirmaciones que contiene, así que nada lo delata salvo el recuento
de fragmentos. Por eso el extractor se niega a empaquetar al terminar un reparto, el
manifiesto lleva `chunks_expected` y `complete`, y Prig **rechaza** al importar
cualquier paquete incompleto.

**B · Un modelo partido entre las dos (`--tensor-parallel 2`).** Solo hace falta si
el modelo no cabe en una GPU (32B). Paga comunicación entre GPU en cada capa, pero
es un único proceso y empaqueta solo:

```python
!python /kaggle/input/prig-worker/prig_extract.py \
    --input  /kaggle/input/prig-job \
    --model  /kaggle/input/qwen25-32b-awq \
    --output /kaggle/working/packs \
    --engine vllm --tensor-parallel 2 --quantization awq --batch 16
```

Los `.prigpack` quedan en `/kaggle/working/packs` y se descargan al terminar.

### Antes de gastar cuota: el sondeo

```bash
--limit 50
```

Procesa 50 fragmentos y te da **la tasa de verificación de citas**. Con eso decides
si el modelo sirve antes de gastar horas:

| Tasa | Qué significa |
|---|---|
| > 85 % | Excelente, adelante |
| 60-85 % | Aceptable; el resto se descarta solo |
| < 60 % | Cambia de modelo o baja el lote antes de seguir |

---

## Qué modelo usar

2×T4 son 32 GB. La T4 es Turing: **sin bfloat16 y sin FlashAttention-2**.

| Tamaño | Precisión | VRAM | Comentario |
|---|---|---|---|
| 7B | fp16 | ~14 GB | Sobra sitio, calidad justa |
| **14B** | **AWQ 4-bit** | **~9 GB** | **Recomendado: lotes grandes** |
| 32B | AWQ 4-bit | ~19 GB | Techo, con `--tensor-parallel 2` |
| 70B | 4-bit | ~40 GB | No entra |

Para extraer estructura pesa más el tamaño del lote que los parámetros: un 14B con
lote de 32 rinde más que un 32B con lote de 4.

> Verifica la GPU que te asignan y la compatibilidad de vLLM con Turing antes de
> comprometerte con un modelo concreto: cambian con el tiempo.

---

## Si la sesión se corta

El trabajador escribe `_parcial*.jsonl` sobre la marcha. Al relanzarlo **reanuda**
donde se quedó. Para empezar de cero: `--restart`.

`/kaggle/working` no sobrevive a la sesión por sí solo. Para continuar en otra:

1. **Save Version** al terminar, conservando la salida
2. En la sesión siguiente, añade esa salida como dataset de entrada
3. Copia los parciales antes de relanzar:

```python
!mkdir -p /kaggle/working/packs
!cp /kaggle/input/<version-anterior>/packs/_parcial*.jsonl /kaggle/working/packs/
```

Con 100 libros conviene partir el trabajo en varios cuadernos de 20-30 libros, para
no depender de que una sola sesión larga llegue al final.

Los parciales de un trabajo **anterior** que queden en la carpeta de salida se
ignoran al empaquetar (se comparan con los fragmentos del trabajo actual), así que
mezclar dos trabajos en la misma carpeta no corrompe el paquete — pero avisa.

## Ajustes cuando algo va mal

| Síntoma | Ajuste |
|---|---|
| `CUDA out of memory` | `--batch 16` u `8`, o `--gpu-util 0.85` |
| Va lento | sube `--batch`; mantén `--max-len 4096` |
| Respuestas cortadas | sube `--max-new-tokens` |
| Tasa de citas baja | `--profile core`, o cambia de modelo |
| El segundo proceso muere al arrancar | falta `--gpu`: ambos van a la GPU 0 |
| Solo hay una GPU | un único proceso, sin `--gpu` ni `--shard` |

---

## Qué se extrae de cada fragmento

| Campo | Contenido |
|---|---|
| `claims` | Hechos tipados: definición, fórmula, procedimiento, ejemplo, límite, comparación, resultado, intuición, notación |
| `concepts` | Conceptos con **los otros nombres que el libro les da** |
| `relations` | Requiere, parte de, contrasta con, causa, ejemplo de, generaliza, equivale a |
| `symbols` | Notación matemática con su significado |
| `figures` | Figuras y tablas con su pie |
| `questions` | Preguntas de comprensión que el fragmento permite responder |
| `summary` | De qué trata, en una o dos frases |
| `difficulty` | Básico, intermedio o avanzado |

**Cada afirmación, relación y símbolo lleva su cita textual**, y se comprueba que
aparece de verdad en el fragmento. Lo que no cuadra se descarta antes de empaquetar:
es la defensa contra alucinaciones y cuesta prácticamente nada.

Los alias son lo que permite cruzar libros: cuando uno dice *weight decay*, otro
*regularización L2* y otro *ridge*, el sistema sabe que hablan de lo mismo.

---

## Correr en tu propia máquina

No hace falta Kaggle. Con una GPU modesta y paciencia, el mismo extractor procesa
tus libros en casa — mismo esquema, mismos prompts, misma verificación de citas y
el mismo `.prigpack`. Solo cambia el motor.

### Lo que hay que configurar en Ollama

**Esto es lo primero y casi nadie lo hace.** Ollama decide por su cuenta cuántas
peticiones atiende a la vez, y con la VRAM justa elige una. Pedirle dos en paralelo
desde el extractor no sirve de nada: se encolan. Hay que decírselo al servidor:

```bash
pkill ollama
OLLAMA_NUM_PARALLEL=2 \
OLLAMA_FLASH_ATTENTION=1 \
OLLAMA_KEEP_ALIVE=30m \
ollama serve
```

| Variable | Por qué |
|---|---|
| `OLLAMA_NUM_PARALLEL=2` | Sin esto el runner arranca con `--parallel 1` y el paralelismo del extractor no existe |
| `OLLAMA_FLASH_ATTENTION=1` | Viene apagado. Cualquier GPU Ampere o posterior lo soporta y libera memoria de caché KV |
| `OLLAMA_KEEP_ALIVE=30m` | Por defecto descarga el modelo a los 5 minutos y cada pausa cuesta una recarga |

**No actives `OLLAMA_KV_CACHE_TYPE=q8_0`.** Medido, cuesta más de lo que da.

### La corrida

```bash
cd kaggle_worker
python3 prig_extract.py \
    --input  ~/.prig_books/jobs/prig_job_XXXX \
    --output ~/.prig_books/packs \
    --model  qwen2.5-coder:7b \
    --engine ollama --paralelo 2 --batch 4 \
    --por-libro --temp-max 78
```

`--por-libro` termina y empaqueta cada libro antes de empezar el siguiente: puedes
parar entre libros y lo hecho ya sirve. `--temp-max 78` espera a que la GPU baje de
73 °C antes de seguir — en un portátil, sin eso el throttling térmico te ralentiza
igual pero sin avisar y castigando el equipo.

### Lo medido

RTX 4050 portátil (6 GB, Ada sm_89), 62 GB de RAM, `qwen2.5-coder:7b` en Q4_K_M,
tres fragmentos reales de tres libros distintos (deep learning, cálculo, C++):

| Configuración | Tiempo | Citas verificadas |
|---|---|---|
| Sin `format:json` | — | **50 %** |
| Con `format:json` | 46 s/frag | **100 %** |
| `--paralelo 2` sin tocar el servidor | 47 s/frag | 100 % |
| `--paralelo 2` + servidor bien configurado | **35 s/frag** | 100 % |
| … más caché KV en `q8_0` | 37 s/frag | **79 %** ❌ |

Dos lecturas de esta tabla:

**Obligar el formato JSON duplicó la calidad sin cambiar de modelo.** De 50 % a
100 % de citas verificadas. El cuello de botella no era lo que el modelo sabe, sino
su disciplina al escribir. Por eso el motor de Ollama lo fuerza siempre.

**Cuantizar la caché KV parecía gratis y no lo es.** Ahorra memoria y acelera un
poco, pero copiar texto literal es la operación más sensible a la precisión que
existe — y verificar citas es exactamente eso. Veinte puntos de caída.

A 35 s por fragmento, un libro de 600 páginas sale por **unas 6 horas**. Una noche
por libro.

### Qué modelo

| Modelo | VRAM | Veredicto |
|---|---|---|
| **7B en Q4_K_M** | 4,7 GB | **Recomendado con 6 GB.** Entra entero en la GPU |
| 14B en Q4_K_M | ~9 GB | Reparte con la CPU. Más calidad, bastante más lento |
| 32B en Q4_K_M | ~20 GB | **No.** Medido: 75 % en CPU, más de 10 minutos por fragmento |

El 32B no es lento: es inviable. Un libro serían semanas, y con los 12 núcleos al
100 % calentando la máquina todo el tiempo.

Sobre usar modelos de *math* o *code* especializados: están afinados para
**resolver** problemas de su campo, no para **leer y estructurar**. Lo que esta
tarea exige es seguir instrucciones y citar literalmente, que es virtud de los
modelos *instruct* generales. La prueba está en la tabla de arriba: la mejora vino
de constreñir el formato, no de cambiar de modelo.

### Cuando un fragmento sale mal

```bash
python3 prig_extract.py --input <job> --output <packs> \
    --model qwen2.5-coder:7b --engine ollama --reparar
```

Relee **solo** los fragmentos cuya primera lectura falló de forma comprobable: no
devolvió JSON, no extrajo nada, o citó mal más de la mitad. Los motivos se guardan
fragmento a fragmento durante la corrida, así que la reparación sabe exactamente
dónde mirar en lugar de releer el libro entero.

En la medición, un fragmento de C++ salió vacío y la reparación lo dejó en siete
afirmaciones al 100 %. Costó un fragmento de trabajo, no seiscientos.

Puedes cambiar `--model` para que lo relea **otro** modelo. Al empaquetar se
conserva la mejor de las lecturas, nunca la primera.

### Leer un libro con dos modelos

La verificación de citas caza lo que el modelo **inventa**. Lo que no puede cazar es
lo que el modelo **se dejó**, y ahí dos lecturas independientes se dejan cosas
distintas. Dos modelos leyendo el mismo libro entero y uniendo sus hallazgos ganan
cobertura:

```bash
python3 prig_extract.py --input <job> --output <packs> --model otro-modelo:7b \
    --engine ollama --restart                      # segunda lectura completa
python3 prig_extract.py --input <job> --output <packs> --model otro-modelo:7b \
    --engine ollama --pack-only --unir             # unir ambas
```

No hace falta que los modelos dialoguen, y más vale que no lo hagan: con 6 GB solo
cabe uno a la vez, así que un diálogo por fragmento significaría recargar 4,7 GB
desde disco miles de veces. Leer el libro entero con un modelo y luego con el otro
son **dos cargas en total**.

El coste es duplicar el tiempo por libro. Resérvalo para los libros que lo merezcan;
por eso `--unir` está apagado por defecto.

---

## Probar en local antes de subir nada

```bash
python prig_extract.py --input ./prig_job --output ./packs \
    --model qwen2.5-coder:7b --engine http --batch 2
```

Usa tu Ollama por HTTP. Va lento —no aprovecha el lote— pero verifica que todo el
circuito funciona antes de gastar cuota.

---

## Contenido del `.prigpack`

```
manifest.json     libro, sha256, modelo usado, recuentos, tasa de verificación
claims.jsonl      afirmaciones verificadas, con página y cita
concepts.jsonl    conceptos con alias y páginas donde aparecen
relations.jsonl   relaciones entre conceptos
symbols.jsonl     notación con su significado
figures.jsonl     figuras y tablas
questions.json    preguntas de comprensión
outline.json      índice del libro
checksums.json    integridad de todo lo anterior
```

Es un zip: puedes abrirlo y mirarlo. `input_manifest_sha256` ata el paquete a
exactamente los fragmentos de los que salió, así que siempre sabrás si un paquete
corresponde a la versión actual de un libro o a una anterior.

---

## De vuelta en Prig: importar los paquetes

Descarga los `.prigpack` de la salida de Kaggle y déjalos en:

```
~/.prig_books/packs/
```

Abre **Biblioteca** y pulsa **Importar** en el bloque *Base de conocimiento*. Esa
única acción hace cuatro cosas, en este orden, porque saltarse cualquiera deja la
base peor que vacía:

| Paso | Qué hace | Por qué no se puede omitir |
|---|---|---|
| **Verificar** | comprueba el sha256 de cada archivo del zip y que el manifiesto cuadre con el contenido | un paquete truncado por una descarga a medias importa "bien" y calla |
| **Importar** | vuelca el libro; si ya estaba, lo reemplaza entero | reimportar sin borrar duplica afirmaciones y el índice de texto acumula basura |
| **Unificar** | funde los conceptos de todos los libros en canónicos y marca los puentes | sin esto cien libros son cien islas: `weight decay`, `regularización L2` y `ridge` quedan como tres cosas sin relación |
| **Dosieres** | precomputa por concepto todo lo que dicen los libros de él | el tutor tendría que lanzar seis consultas por pregunta en vez de leer una ficha |

Al terminar aparece el informe **libro a libro**: cuántas afirmaciones, conceptos y
relaciones guardó cada uno, y qué le falta si algo no cuadró. Un libro con menos
afirmaciones de las que declara su manifiesto no da error por sí solo — simplemente
el tutor responde peor sobre ese libro y nadie se entera. Por eso el informe se
enseña siempre, no solo cuando algo falla.

### Comprobar desde la terminal

```bash
cd backend
python -c "
from pack_importer import PackImporter, informe_texto
print(informe_texto(PackImporter().verificar_integridad()))"
```

### Qué obtiene el modelo

Al preguntar algo, el tutor recibe una ficha ya montada con la definición, la
intuición, la fórmula, el código, los prerrequisitos y —si el concepto vive en
varios campos— cómo se cuenta desde cada uno:

```
### regularización L2  (también: weight decay, ridge)
[concepto puente entre deep_learning, machine_learning]
- [DEFINITION] Penaliza la norma al cuadrado de los pesos...
  «se añade la norma L2 de los pesos a la función de coste» — Goodfellow, p.228
- [DEFINITION] En regresión lineal se conoce como regresión ridge.
  «this particular case is known as ridge regression» — Bishop, p.10
- [CODE_PATTERN] En los optimizadores se implementa como weight decay.
  «weight_decay=1e-4» — Goodfellow, p.231
- [DESDE MACHINE_LEARNING] En regresión lineal se conoce como regresión ridge.
```

Cada línea lleva libro y página. Si la pregunta no toca nada de la biblioteca, el
contexto sale **vacío a propósito** y el tutor avisa de que responde sin respaldo,
en lugar de citar el libro de cálculo para hablar de otra cosa.
