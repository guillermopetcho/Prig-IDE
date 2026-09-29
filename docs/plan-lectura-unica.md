# Plan: leer el repositorio una sola vez y analizarlo como un modelo grande

> **Antecedente.** La versión final y consolidada está en
> [arquitectura-unificada.md](arquitectura-unificada.md). Este documento conserva las fases
> originales y los experimentos de lectura congelada en RAM (sección 8).

Plan de razonamiento (sin implementar) para que el motor MoE (Qwen3.6-35B-A3B, contexto práctico de
32K en una GPU de 6 GB) se acerque a lo que hace un modelo con contexto enorme cuando analiza un
proyecto entero. Se apoya en lo medido en [motor-moe.md](motor-moe.md), [banco-proyecto.md](banco-proyecto.md)
y [memoria-consulta.md](memoria-consulta.md).

## 1. Qué hace bien un modelo grande con todo el proyecto en contexto

1. **Visión global:** sabe qué hay en todas partes a la vez.
2. **Detalle exacto a demanda:** puede citar cualquier línea que leyó.
3. **Referencias cruzadas en un solo razonamiento:** relaciona dos piezas lejanas sin buscarlas.
4. **Coherencia:** usa los mismos nombres y la misma idea del proyecto en toda la respuesta.

No se puede copiar la atención simultánea sobre 1,9 millones de tokens. Sí se puede reproducir cada
una de esas cuatro capacidades con una pieza distinta:

| Capacidad | Cómo se reproduce aquí |
|---|---|
| Visión global | **Tarjeta global** del proyecto (~8K tokens) al principio de toda lectura |
| Detalle exacto | Código literal en el banco + **instantáneas de lectura** por unidad (el estado del modelo tras leerla) |
| Referencias cruzadas | Grafo de llamadas resuelto, **interfaces de las vecinas** dentro de cada unidad y composición entre unidades |
| Coherencia | Glosario canónico, fichas verificadas y una sola fuente de verdad (el banco) |

Lo que no se reproduce de forma automática son los hallazgos transversales que surgen de ver todo
junto (dos módulos lejanos que duplican lógica, una convención rota en tres lugares). Para eso hay
**barridos transversales explícitos** (fase 6).

## 2. La idea central: «leer una vez» y guardar la lectura en dos formas

Durante la única lectura completa se guardan dos copias de lo leído:

1. **Copia simbólica** (legible y verificable): fichas por símbolo, resumen por unidad, conceptos y
   el mapa de dónde está cada cosa. Es la fuente de verdad.
2. **Copia neural** (en el idioma del modelo): la **instantánea** del motor justo después de leer
   cada unidad, es decir, la caché de las 10 capas de atención más el estado de las 30 capas SSM. Es
   literalmente "la lectura guardada". Restaurarla (0,2–0,6 s medidos) deja al modelo como si
   acabara de leer esa parte entera, con fidelidad total y no un resumen.

El motor ya guarda y restaura instantáneas de proyectos (`--slot-save-path`, `_preparar_proyecto`).
El plan convierte eso en un **árbol de instantáneas por unidad**.

**Por qué funciona con este modelo híbrido.** Cada instantánea es un prefijo completo y legítimo, que
es lo único que admiten las capas SSM (sus estados no se pueden empalmar). El estado SSM pesa 66 MB
fijos y la caché ~10,9 KB por token, así que una unidad leída en 32K ocupa ~0,4 GB.

## 3. La estructura de cada lectura (el prefijo)

Cada unidad se lee con el mismo orden de capas. Lo más estable va primero, para que un cambio
invalide lo menos posible:

| Capa | Contenido | Tamaño aprox. | Cambia… |
|---|---|---|---|
| 1. Sistema | Rol de lector, reglas y formato | ~1K | casi nunca |
| 2. Tarjeta global vN | Mapa, resúmenes de subsistemas, glosario y conceptos clave | ~6–8K | pocas veces (se versiona) |
| 3. Contexto de la unidad | Su papel en el proyecto, quién la usa y las interfaces de las vecinas | ~2–4K | cuando cambian las vecinas |
| 4. Código de la unidad | Archivos en formato de repositorio (`<|file_sep|>`), ordenados de definiciones a usos | ~14–18K | al editar |
| — | *Aquí se guarda la instantánea* | | |
| 5. Tarea o pregunta | Lo que se pide en ese momento | ~0,5–6K | cada vez |

Total: ≤ 32K. Es el tamaño en el que medimos 24 expertos calientes y ~40 tok/s. A 64K entran menos
expertos y se escribe más lento. Otro tamaño se decide con la medición de la fase 2.

**Versionado de la tarjeta global.** Si la tarjeta cambia, se invalidan TODAS las instantáneas. Por
eso se congela por versión. Los cambios chicos del proyecto no la tocan: van como **delta** después
de restaurar ("cambios desde que leíste esto", que el banco ya calcula con diff). La tarjeta se
rehace, y con ella las instantáneas, solo cuando el delta acumulado supera un umbral.

## 4. Fases

Cada fase tiene objetivo, hipótesis, método, medición y criterio para seguir o parar.

### Fase 0: Examen del proyecto (la vara de medir)
- **Objetivo:** medir "qué tan cerca de un modelo grande" está cada variante.
- **Método:**
  - 150–200 preguntas con respuesta comprobable, generadas del grafo y el código:
    - exactas: quién lee X, qué devuelve Y, qué endpoint usa Z;
    - de recorrido: qué pasa de punta a punta cuando…;
    - de impacto: qué se rompe si cambio…;
    - de ubicación: dónde cambio…;
    - transversales: qué módulos hacen lo mismo que….
  - Opcional, con tu permiso por privacidad: comparar con un modelo grande en la nube (Gemini ya está
    integrado y apagado por defecto) sobre las mismas preguntas.
- **Mide:** aciertos, citas correctas, inventos, tiempo y tokens.
- **Criterio:** sin esta fase no se sigue. Todo lo demás se compara contra ella.

### Fase 1: Organizar el repositorio para la lectura individual (sin modelo)
- **Objetivo:** partir el proyecto en unidades legibles de ≤16K tokens de código, en buen orden.
- **Método:**
  - Comunidades del grafo de llamadas e imports (Leiden o Louvain), respetando las carpetas.
  - Los archivos gigantes (`app.py` ~80K tokens, `index.html`) se parten por grupos de símbolos
    relacionados, nunca por líneas a ciegas.
  - **Orden de lectura** de abajo hacia arriba en el grafo condensado. Dentro de cada unidad, primero
    las definiciones y después los usos, como un libro.
  - Por unidad: lista de símbolos, interfaces que exporta, vecinas y su papel en el proyecto.
- **Mide:** tamaño de las unidades, aristas cortadas entre unidades (menos es mejor) y tiempo.
- **Criterio:** la partición es estable y cubre el 100 % del código de producción.

### Fase 2: Primer vistazo y tarjeta global (modelo, barato)
- **Objetivo:** que cada lectura profunda sepa de antemano de qué va todo el proyecto.
- **Método:** gists cortos por unidad (como ReadAgent), leyendo firmas y docstrings, no cuerpos. Con
  esos gists, más los hechos del grafo y el README, se arman los resúmenes de subsistemas, el
  glosario y los conceptos: la tarjeta global v1.
- **Medición paralela:** misma unidad leída a 32K contra 64K (calidad de ficha contra velocidad).
- **Criterio:** tarjeta ≤8K tokens; el examen mejora frente a no tenerla.

### Fase 3: Lectura profunda única (modelo, una vez)
- **Objetivo:** leer cada unidad una sola vez, dejando las dos copias.
- **Método, por unidad y en el orden de la fase 1:**
  1. Prefijo de las capas 1 a 4 y **guardar la instantánea**.
  2. Sobre ese prefijo, pedir las **fichas** de sus símbolos: qué hace y cómo (con líneas),
     contrato, efectos, invariantes, riesgos y "para cambiar X, tocar aquí". También las
     **preguntas que esta unidad responde** (índice inverso para el enrutador) y el resumen de la
     unidad. Inglés terso, perfil de muestreo "preciso" y sin razonar.
  3. Como la tarea va después del prefijo, pedirle más cosas a la misma unidad no relee nada.
- **Costo estimado para Prig** (~70 unidades):
  - lectura: ~50 s por unidad (~1 h en total);
  - fichas: ~1–1,5 min por unidad;
  - total: **2,5–3 h una sola vez**;
  - disco: ~70 × 0,4 GB ≈ **28 GB** (el tope actual de instantáneas es de 20 GB; hay que subirlo).
- **Criterio:** examen de "detalle exacto" ≥ 90 % restaurando la unidad correcta.

### Fase 4: Verificación (primero sin modelo)
- **Objetivo:** que la copia simbólica sea confiable, porque es la fuente de verdad.
- **Método:**
  - Chequeos automáticos: los nombres existen, cada línea citada dice lo que se afirma, las
    constantes coinciden y los efectos declarados están en el grafo.
  - Lo dudoso vuelve a su unidad restaurada para una segunda mirada.
  - Idea tomada de PROOF: una ficha es buena si desde ella se puede predecir el comportamiento del
    código (autoexamen por unidad).
- **Criterio:** afirmaciones verificadas ≥ 95 %; lo demás marcado con confianza baja.

### Fase 5: Integración y mapa de "dónde está cada cosa"
- **Objetivo:** visión de subsistemas, recorridos de punta a punta y el índice de concepto → lugares.
- **Método:**
  - Los recorridos salen del grafo (cadena exacta de llamadas) y se explican con las fichas, no con
    el código.
  - El mapa de conceptos une cada clave de configuración, endpoint, elemento de la interfaz y
    archivo de datos con quién lo define, lee, escribe, expone y consume.
  - El modelo solo pone los nombres humanos de los conceptos.
  - Se actualiza la tarjeta global a v2 si hace falta.
- **Criterio:** examen de "ubicación" e "impacto" ≥ 90 %.

### Fase 6: Barridos transversales (lo que solo "ve" un modelo grande)
- **Objetivo:** hallazgos que requieren ver todo junto.
- **Método:**
  - Comparar fichas entre unidades: vectores parecidos indican lógica duplicada.
  - Revisar convenciones (manejo de errores, uso de configuración, nombres) por tema, sobre las
    fichas.
  - Detectar endpoints sin uso, código muerto y riesgos agregados.
  - Cada barrido es un map-reduce sobre fichas, no sobre código (barato).
- **Criterio:** examen "transversal" ≥ 75 %. Es la parte más difícil y se acepta menos.

### Fase 7: Responder como un modelo grande (el flujo de preguntas y cambios)
1. **Enrutar:** mapa de conceptos + vectores de fichas + preguntas inversas + grafo, que eligen la o
   las unidades.
2. **Una sola unidad:** se restaura su instantánea (0,2–0,6 s), se suma el delta de cambios, y el
   modelo responde con la lectura completa de esa parte en la cabeza.
3. **Varias unidades** (como Chain-of-Agents y RLM): se restaura cada unidad por turno, cada una
   extrae lo suyo en una nota corta y un paso final sin instantánea sintetiza las notas con la
   tarjeta global. Para preguntas exactas alcanza la consola `P`, sin restaurar nada.
4. **Cambios:** localizar, planificar (con razonamiento acotado), editar sobre el código literal,
   correr los tests que da el grafo y registrar. Con tu aprobación del diff.

### Fase 8: Mantenimiento
- El vigilante marca las unidades cuyos archivos cambiaron.
- En horas ociosas, esas unidades se releen: nueva instantánea y fichas nuevas, 1–2 min cada una.
- Si cambió un contrato, se marcan las vecinas para revisar.
- La tarjeta global se rehace (y con ella todas las instantáneas) solo cuando el delta acumulado lo
  justifica.

## 5. Riesgos y límites

| Riesgo | Contención |
|---|---|
| La instantánea depende de la versión exacta del modelo, núcleo y motor | Se guarda con esa llave; si cambia, se regenera desde el banco simbólico en ocio |
| Disco (28 GB o más) | Hay 224 GB libres; poda por uso y tope configurable |
| Las preguntas que cruzan muchas unidades son caras | Primero la consola y los hechos, que son exactos y baratos; solo después restaurar unidades |
| Llamadas dinámicas que el grafo no ve | El lector las declara, se verifican y quedan como aristas "posibles" |
| Errores de las fichas que se propagan | Fase 4, confianza por ficha y el examen |
| Invalidación masiva al cambiar la tarjeta global | Versionado más deltas |
| Solo un slot: dos unidades no pueden estar "en la cabeza" a la vez | Composición por notas (fase 7.3) |

## 6. Qué se toma de cada trabajo publicado

- **ReadAgent** (gists y búsqueda de páginas): fase 2 y enrutamiento.
  [arXiv 2402.09727](https://arxiv.org/abs/2402.09727)
- **Recursive Language Models** (el contexto como variable y subllamadas): consola `P` y composición.
  [arXiv 2512.24601](https://arxiv.org/abs/2512.24601)
- **LocAgent / RepoGraph / CodexGraph** (grafos para localizar código): mapa de "dónde está".
  [LocAgent](https://arxiv.org/abs/2503.09089)
- **Codebase-Memory** (grafo con tree-sitter): con solo el grafo acierta 83 % contra 92 % leyendo
  archivos, pero usa 10 veces menos tokens. Por eso aquí se combinan grafo y lectura real
  (instantáneas). [arXiv 2603.27277](https://arxiv.org/abs/2603.27277)
- **PROOF** (especificación verificada que se mantiene en sincronía con el código): fase 4 y el
  mantenimiento de la copia simbólica. [arXiv 2609.06383](https://arxiv.org/abs/2609.06383)

## 7. Orden de ejecución propuesto

1. Fase 0 (examen) y fase 1 (partición): sin riesgo y rápidas.
2. Una prueba piloto de las fases 2–4 sobre **un subsistema** (el motor MoE, ~5 unidades): mide
   tiempos reales, calidad de las fichas y el efecto de las instantáneas en el examen.
3. Si el piloto cumple los criterios, el proyecto entero en una corrida nocturna y después las fases
   5–8.

## 8. Experimentos: la lectura congelada en RAM y dos barridos a la vez (29/09/2026)

Idea analizada: cargar el modelo dos veces (una copia para leer y otra para razonar, con los
núcleos E ayudando) y congelar la lectura en RAM.

**Correcciones de partida:**

- Leer no cambia los pesos, cambia el estado. En este modelo, las 30 capas Gated DeltaNet son
  «pesos rápidos» que aprenden durante la lectura (regla delta). Congelar la lectura es guardar ese
  estado (SSM + caché de atención), por unidad, porque esa memoria olvida.
- Dos copias de los pesos solo duplican RAM (~41 GB). Un servidor atiende varias lecturas con una
  sola copia.

**Mediciones** (turbo apagado, sin otros programas, núcleo Q8, 24 calientes):

| Experimento | Resultado |
|---|---|
| 1. Carga que solo lee memoria en los 4 núcleos E, mientras genera el motor | Motor de 42,0 a 36,3 tok/s (−14 %); la carga sacó igual 16 GB/s. Con 1 núcleo E: −4 %. El motor no satura la RAM: su límite es el cómputo de los núcleos P |
| 2. Volver a una unidad ya leída usando la caché de RAM del servidor (`--cache-ram`) | 5,2–5,9 s en lugar de 29–31 s. Reusa ~15.500 tokens, pero relee ~2.050: el estado híbrido se guarda en puntos de control |
| 2b. Estado guardado justo al final de la unidad (`/slots?action=save`) y restaurado desde el archivo | Guardar: 0,12 s (257 MB para 17,5K tokens). **Restaurar: 0,08 s** (el archivo sigue en la caché de páginas del sistema). Pregunta nueva: **1,1–1,5 s**, releyendo 23 tokens |
| 3. Dos secuencias en un mismo motor (`-np 2`, sin MTP) | Una sola: 30,8 tok/s. Dos juntas: 22,5 cada una, **43,8 de conjunto (1,42×)**. Una sola con MTP da 42: MTP ya aprovecha ese mismo efecto |

**Conclusiones:**

- **Sí: repositorio activo en RAM.** Una instantánea exacta por unidad (~0,25 GB cada 17,5K tokens),
  que el sistema operativo mantiene en RAM por sí solo. Cambiar de unidad cuesta 0,08 s y preguntar,
  ~1,5 s, contra ~30 s de releer (20 veces menos). Para ~70 unidades son ~18–21 GB, que caben junto
  a los ~21 GB de pesos.
- **No por ahora: dos barridos en paralelo.** Sin MTP no superan a una secuencia con MTP. Solo
  sumarían con MTP en ambas secuencias (6 tokens por paso), lo que exige extender el parche de
  reparto: esfuerzo alto y ganancia incierta.
- **Núcleos E: solo trabajo liviano.** Verificaciones, grafo, banco y un modelo chico. Nada que lea
  memoria a fondo.
- **Razonamiento más profundo:** con la lectura congelada, pensar más solo cuesta generar. Varias
  muestras (autoconsistencia), releer la unidad con la tarea al principio y razonar con `think`
  sobre una unidad restaurada son ahora baratos de probar contra el examen.

## 9. Decisiones pendientes del usuario

- Tamaño de contexto por unidad: 32K (más rápido) o 64K (más código por lectura). La fase 2 lo mide.
- Disco para las instantáneas: ~30 GB.
- Comparar con un modelo en la nube en la fase 0: sí o no (privacidad).
- Aprobación de los diffs en el flujo de cambios (recomendado al principio).
