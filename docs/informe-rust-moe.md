# Informe: qué más pasar a Rust en Prig (velocidad, eficiencia y conocer el MoE)

**Para**: el usuario y quien implemente (otra sesión u otro modelo, sin el contexto de la conversación). **Fecha**:
11/10/2026. **Estado**: propuesta; nada de esto está hecho. Se apoya en [motor-moe.md](motor-moe.md),
[arquitectura-unificada.md](arquitectura-unificada.md) y [plan-banco-rust.md](plan-banco-rust.md). Las cifras dicen
si están **medidas** (en esta máquina, con la fuente) o **estimadas**.

## 0. En una página

- **El motor que genera ya es C++/CUDA** (el fork de llama.cpp con el parche `prig-moe.diff`). Generar y leer no
  pasan por Python, y Python agrega poco por token: **4,6 µs por token** al traducir del formato del servidor al de
  Ollama (medido; 0,03 % de un núcleo a 60 tok/s). Reescribir el motor en Rust perdería los parches propios y los
  núcleos optimizados de llama.cpp. **Las mejoras del motor siguen en C++/CUDA.**
- **Rust rinde alrededor del motor**, en tres frentes:
  1. **Lo que corre en Python mientras el motor genera y le roba precisión o CPU.** El pausador del modo frío se
     atrasa **+5,2 ms en un tramo de 6 ms** cuando otro hilo de Python trabaja: el tramo en que el motor trabaja dura
     un 87 % más de lo que pide el control térmico. El visualizador de audio calcula una FFT en Python puro: **1,58 ms por cuadro, ~9 % de
     un núcleo con el GIL tomado**.
  2. **Observar el MoE por dentro.** Hoy solo se cuenta el uso agregado de cada experto (`AIPC_CONTAR`). Para estudiar
     el modelo (especialización de expertos, co-activación, qué experto sigue a cuál entre capas, peso que se omite,
     capa MTP) hace falta la **traza por token**. Son ~1 KB por token, y procesarla en Python no alcanza: la misma
     estadística cuesta **17,8 µs por token y capa en Python y 0,67 µs en Rust** (medido con una traza sintética: una
     pasada por Prig, ~23 min contra 52 s, en un hilo).
  3. **Simular antes de construir.** Con la traza, un simulador en Rust prueba políticas de expertos calientes,
     prebúsqueda por PCIe y umbrales sin correr el modelo. Así se decide con números qué vale el trabajo en CUDA.
- **Primeros pasos recomendados** (baratos, medibles):
  1. el pausador del modo frío en Rust;
  2. la FFT del audio en Rust;
  3. la traza de enrutamiento: parche C++ mínimo más consumidor en Rust;
  4. el analizador de trazas y el simulador.

| # | Qué | Para qué | Ganancia | Esfuerzo | Prioridad |
|---|---|---|---|---|---|
| B1 | Pausador del modo frío | eficiencia térmica | el tramo de trabajo deja de estirarse +5,2 ms con Python ocupado (medido) | 1 sesión | **alta** |
| B3 | FFT del visualizador de audio | eficiencia | 1,58 ms → microsegundos por cuadro; libera ~9 % de un núcleo y el GIL (medido el costo actual) | < 1 sesión | **alta** |
| A1 | Traza de enrutamiento (C++ + Rust) | aprender | la base de todo lo demás del grupo A | 2–3 sesiones | **alta** |
| A2 | Analizador de trazas | aprender | 26× más rápido que Python en un hilo (medido) | 2 sesiones | **alta** |
| A3 | Simulador de colocación de expertos | velocidad (decidir) | evita semanas de CUDA en ideas que no rinden | 2–3 sesiones | **alta** |
| B2 | Lista caliente que aprende en línea | velocidad | lista por proyecto: aciertos 30,7 → 39,0 %; por unidad, +12 % tok/s (medido) | 1–2 sesiones | media (después de A3) |
| A6 | Telemetría de alta frecuencia | aprender, eficiencia | energía y temperatura por token y por modo | 1–2 sesiones | media |
| A4 | Analizador de pesos GGUF | aprender | estructura de los 10.240 expertos sin la GPU | 2–3 sesiones | media |
| A5 | Inspector de estados guardados | aprender | curva de olvido del SSM; tamaño real de la biblioteca (23 GB) | 2 sesiones | media (investigación) |
| B4 | Índice BM25 de la biblioteca | velocidad | sin medir | 1–2 sesiones | baja |
| B5 | Extracción de PDF | velocidad | sin medir (`pypdf` es Python puro) | 1–2 sesiones | baja |
| B6 | Embebedor bge-m3 dentro de Prig | calidad del banco | vectores sin depender de Ollama | 2–3 sesiones | baja |

---

## 1. Dónde está el tiempo hoy

| Pieza | Lenguaje | Costo | ¿Limita? |
|---|---|---|---|
| Generar un token | C++/CUDA (fork de llama.cpp) | 33–58 ms de CPU por token; 38–68 tok/s según modo y contexto (medido, motor-moe.md) | **sí: es el límite** |
| Leer un prompt | C++/CUDA | 600–815 tok/s (medido) | sí, al leer unidades |
| Restaurar un estado guardado | C++ | 0,07–0,3 s (medido) | no |
| Traducir cada token al formato de Ollama (`motor_moe.a_ollama`) | Python | **4,6 µs por token** (medido hoy, 5.000 trozos sintéticos) | no |
| Banco del proyecto | Rust (`prig_banco`) | indexar Prig 0,91 s; hechos de una pregunta 40–76 ms; buscar 4 ms (medido, plan-banco-rust.md) | no |
| Sensores (térmico cada 2 s, GPU por NVML) | Python + ctypes | microsegundos por lectura | no |
| Pausador del modo frío (ciclo de 50 ms) | Python (hilo) | sin carga, +0,1 ms de desvío; **con otro hilo de Python ocupado, +5,2 ms** (medido hoy) | **sí, en la precisión térmica** |
| Visualizador de audio (FFT de 512 muestras) | Python puro | **1,58 ms por cuadro**, ~55 cuadros/s: ~9 % de un núcleo (medido hoy; solo con el visualizador abierto) | compite con el motor |
| Leer una unidad del proyecto | modelo | 25–43 s por unidad (medido) | el modelo |
| Estadística de una traza de enrutamiento | (no existe) | Python 17,8 µs por token y capa; Rust 0,67 µs (medido hoy, sintético) | impide estudiar el MoE en Python |

**Por qué importa lo que corre al lado del motor:** el motor no satura la RAM, su límite es el cómputo. Una carga que
lee memoria en los núcleos E le quita un 14 %, y una en un solo núcleo E, un 4 % (medido, arquitectura-unificada.md
§1.2). Todo lo que Prig hace en Python mientras genera (y el calor que suma) cuesta velocidad o temperatura.

## 2. Mediciones de esta revisión

Hechas el 11/10/2026 con el `.venv` de Prig y tope de memoria (`ulimit -v`). Los scripts eran de un solo uso (en el
scratchpad de la sesión); el método está aquí para repetirlas.

| Medición | Método | Resultado |
|---|---|---|
| Traducción por token | `motor_moe.a_ollama` sobre 5.000 líneas SSE sintéticas | 4,6 µs por token |
| Precisión del pausador | el mismo esquema de `frio.Pausador` (`Event.wait` del tramo de trabajo y del resto), fracción 0,12 (6 ms de 50 ms), 60 ciclos | sin carga: +0,11 ms de media, +0,25 máx.; **con la FFT del audio en otro hilo: +5,21 ms de media, +5,43 máx.** |
| Cuadro del visualizador | ventana, RMS, FFT recursiva y 32 bandas de `audio_monitor`, 200 cuadros | 1,58 ms por cuadro (FFT sola: 1,41 ms) |
| Estadística de la traza | uso por capa, co-activación por pares y transición capa → capa siguiente; 8 de 256 expertos, 41 capas | Python 17,76 µs por (token, capa); Rust 0,671 µs (1,9 M tokens en 52 s, un hilo) |

El atraso del pausador es el intervalo de cambio del GIL (5 ms): el hilo que debe congelar el motor espera a que el
otro suelte el intérprete. Con la fracción mínima (0,12) el tramo de trabajo dura 11,2 ms en lugar de 6. La pausa
también se estira, así que el motor trabaja entre 0,19 y 0,22 del ciclo en vez de 0,12 (estimado a partir de la
medición): la protección térmica queda más floja de lo que se diseñó justo cuando Prig está ocupado.

---

## 3. Velocidad y eficiencia

### B1. Pausador del modo frío (alta)

| | Hoy | Con Rust |
|---|---|---|
| Dónde | hilo de Python (`recursos/frio.py`, `Pausador`) | hilo nativo en un módulo PyO3, sin GIL |
| Reloj | `Event.wait` relativo | `clock_nanosleep` con tiempo absoluto: el ciclo no se corre |
| Señales | por pidfd (ya) | igual (`pidfd_send_signal`) |
| Desvío con Python ocupado | +5,2 ms en un tramo de 6 ms (medido) | esperado ≈ el de hoy sin carga (+0,1–0,25 ms); a medir |

`ControladorFrio` (una vez por segundo, decide la fracción) puede seguir en Python. Solo baja a Rust el ciclo de 50 ms.
Alternativa: hacerlo dentro de `llama-server` en C, como `prig_suave.c`. Rust tiene a favor que comparte módulo con la
FFT (B3) y la telemetría (A6), y que ya está la cadena de compilación de `prig_banco`.

### B2. Lista caliente que aprende en línea (media, después de A3)

| Lista | Aciertos en la GPU | Velocidad | Fuente |
|---|---|---|---|
| Global | 30,7 % | — | motor-moe.md |
| Del proyecto (al leerlo) | 39,0 % | ~+5 % con 25 calientes | motor-moe.md |
| De la unidad | 35,9 → 46,2 % | 29,6 → 33,2 tok/s (+12 %) | arquitectura-unificada.md §6.2 |
| De la propia conversación | +10 % de aciertos sobre la global (sin MTP) | sin medir | motor-moe.md, «Lo que queda» |

Con la traza (A1), un consumidor en Rust lleva un recuento con olvido por capa durante la conversación. Entre
peticiones, si la ganancia prevista pasa un umbral, sube la lista nueva con `POST /aipc/calientes` (0,18 s para las 40
capas, sin reiniciar). En modo exacto no cambia el resultado. En equilibrado y rápido cambia qué expertos se pueden
omitir, así que la calidad hay que medirla con KL. El simulador (A3) dice antes qué política conviene.

### B3. FFT del visualizador de audio (alta)

`audio_monitor.py` calcula una FFT de Cooley-Tukey recursiva en Python puro, ~55 veces por segundo, mientras alguien
mira el visualizador: 1,58 ms por cuadro (medido), con el GIL tomado. Eso es justo lo que atrasa al pausador (B1).
`numpy` no está en el `.venv`; `rustfft`/`realfft` en el módulo PyO3 lo hace en microsegundos (estimado) y suelta el
GIL. Puede bajar el cuadro entero: muestras → ventana → RMS → FFT → 32 bandas. La lectura de `parec` sigue igual.

### B4–B6. Biblioteca y vectores (baja)

| # | Pieza | Hoy | Con Rust | Nota |
|---|---|---|---|---|
| B4 | Índice BM25 (`knowledge/indexing/bm25_index.py`) | se arma entero en memoria al crear el recuperador y puntúa todos los documentos en Python en cada consulta | `tantivy`, o el FTS5 que ya usa el banco | sin medir: no se tocó el catálogo del usuario |
| B5 | Extracción de PDF (`pdf_parser.py`, `sondeo_libro.py`) | `pypdf`, Python puro | `lopdf`/`pdf-extract`, o pdfium | la calidad del texto extraído hay que compararla, no solo la velocidad |
| B6 | Vectores bge-m3 (`Embebedor`) | por Ollama; si Ollama está apagado, el banco busca sin vectores (pasó en el examen piloto) | `ort` (ONNX) o `candle` dentro de Prig | cuesta CPU mientras corre: pasa por la guardia del vigilante |

---

## 4. Rust para conocer el MoE

### 4.1 Qué no se ve hoy

| Pregunta sobre el modelo | Dato que falta | Cómo se obtendría |
|---|---|---|
| ¿Qué expertos se especializan en qué (Python, castellano, razonamiento)? | expertos elegidos por token, junto al token | traza (A1) + analizador (A2) |
| ¿Qué expertos se activan juntos? | los 8 elegidos de cada token y capa | co-activación (A2) |
| ¿Se puede adivinar el experto de la capa siguiente? | la elección en la capa *i* y en la *i*+1 | transición entre capas (A2) |
| ¿Cuánto peso se pierde al omitir fríos? | pesos del router y máscara de omitidos | traza con pesos (A1) |
| ¿Qué tan seguro está el router? | entropía de los pesos por token y capa | traza (A1) |
| ¿Qué usa la capa MTP? (pendiente: +3–8 % esperado con su propia lista caliente) | elección de la capa MTP | traza de la capa 41 (A1) |
| ¿Qué tan rápido cambia el uso en una conversación? | uso a lo largo del tiempo | distancia de reuso (A2) |
| ¿Cuánta energía cuesta cada token según el modo? | potencia y temperatura alineadas con los tokens | telemetría (A6) + traza |
| ¿Cuánto recuerda el SSM y cómo olvida? | el estado SSM a lo largo de una lectura | inspector de estados (A5) |
| ¿Qué tan distintos son los expertos entre sí? | los pesos de los expertos | analizador GGUF (A4) |

### 4.2 A1. La traza de enrutamiento

**Diseño propuesto:**

1. **Parche C++, mínimo.** El fork ya lee en la CPU los ids de expertos de cada capa (`AIPC_CONTAR` y la cadena
   fría). En ese punto copiaría un registro por token y capa a un anillo en memoria compartida (`/dev/shm`), sin
   bloquear: si el anillo se llena, cuenta lo perdido y sigue. Hay que confirmar en el parche que los pesos del router
   también estén en la CPU en ese punto (la omisión de fríos los usa).
2. **Consumidor en Rust** (proceso propio o hilo de un módulo PyO3). Lee el anillo, agrega en vivo (uso, aciertos de la
   lista caliente, entropía, peso omitido) y guarda la traza comprimida por petición o por unidad.
3. **Prig** lee los agregados para **Temperaturas → Motor MoE**, y el analizador (A2) lee las trazas.

| Registro (por token y capa) | Tamaño |
|---|---|
| 8 ids de experto (`u8`, 256 expertos) | 8 B |
| 8 pesos del router (`f16`) | 16 B |
| máscaras: calientes y omitidos | 2 B |
| **Por token (40 capas + MTP)** | **~1,07 KB** |

| Situación | Volumen |
|---|---|
| Generar a 50 tok/s | ~53 KB/s |
| Leer a 800 tok/s | ~0,85 MB/s |
| Pasada completa por Prig (~1,9 M tokens) | ~2 GB sin comprimir (estimado) |

**Presupuesto:** la traza no puede costar más de ~1 % de velocidad, y apagada (variable de entorno, como las demás
`AIPC_*`) no puede costar nada. No cambia ningún resultado: solo copia datos que ya están en la CPU.

### 4.3 A2. Experimentos que habilita el analizador

| Experimento | Qué responde | Decide |
|---|---|---|
| Mapa de uso por capa y por tipo de texto (código, castellano, inglés técnico, razonamiento) | ¿hay expertos «de Python» o «de español»? | listas calientes por perfil de uso (charla, código, preciso) |
| Co-activación | qué expertos van juntos | si conviene subirlos juntos a la GPU |
| Transición capa → capa | recall de un predictor del experto siguiente (top-k) | **si la prebúsqueda por PCIe vale las semanas de CUDA** (hoy, sin predictor: 42,8 contra 68,9 tok/s, descartada) |
| Distancia de reuso | cuánto tarda un experto en volver a usarse | LRU/LFU contra lista fija |
| Distribución de pesos | cuánto peso cae bajo 0,08 y 0,10, por capa | candidatos de umbral para probar con KL |
| Entropía del router | dónde duda el modelo | cruzarla con la aceptación de MTP y con la sorpresa (C++) |
| Capa MTP | sus expertos más usados | lista caliente de la capa MTP (+3–8 % esperado) |
| Deriva de la conversación | cuánto se aleja el uso de la lista global | el umbral de B2 |

La co-activación y las transiciones son matrices de 256 × 256 por capa (~10 MB por tipo). Rust las llena con
1,9 M tokens en 52 s en un hilo (medido, traza sintética) y admite repartir las capas entre núcleos. Python tardaría
~23 min por pasada (extrapolado de 20.000 tokens medidos).

### 4.4 A3. Simulador de colocación de expertos

Reproduce una traza contra una política y estima aciertos y velocidad con un modelo de costos calibrado con lo que ya
se midió:

| Costo | Valor medido |
|---|---|
| Experto en la GPU | ~gratis por token (la GPU se mantuvo en ~29 W) |
| CPU por token | 33–58 ms según el modo |
| Un experto caliente más en todas las capas | 68,65 MB de VRAM |
| RAM y PCIe | 21 GB/s y 12 GB/s |
| Subir una lista caliente nueva | 0,18 s (40 capas) |

| Política | Qué prueba |
|---|---|
| Lista global fija | la base (30,7 % de aciertos) |
| Lista por proyecto o por unidad | lo medido (39 % y 46 %), para calibrar el simulador |
| LFU con olvido, por conversación | B2 |
| Presupuesto de VRAM distinto por capa | ¿más calientes donde el uso se concentra? |
| Prebúsqueda con predictor (A2) y costo de PCIe | el techo de la idea antes de escribir CUDA |
| Calientes de la capa MTP | el +3–8 % esperado |

**Límite honesto:** el simulador estima aciertos y cómputo, no calidad. Omitir expertos cambia lo que el modelo
escribe, y eso solo lo mide `llama-perplexity` con KL. El simulador sirve para elegir qué pocas variantes vale la pena
medir con KL.

### 4.5 A4–A6. Pesos, estados y energía

| # | Herramienta | Qué hace | Qué se aprende | Riesgo |
|---|---|---|---|---|
| A4 | Analizador de pesos GGUF | abre el GGUF con mmap, decuantiza Q4_K/Q8_0 con SIMD en paralelo y calcula normas, similitud entre expertos y grupos | expertos redundantes; expertos de la capa MTP frente a los del modelo; experto compartido frente a los ruteados. De paso, rehace `construir_nucleo_q8.py` sin Python | bajo |
| A5 | Inspector de estados | lee los estados guardados (`~/.cache/prig-moe/proyectos`, 23 GB, 176 archivos): caché de atención y SSM | cómo cambia el estado SSM (32 cabezas × 128×128) entre unidades: la «curva de olvido» de la etapa 4, sin el modelo. También cuánto prefijo repetido hay entre estados (sistema y tarjeta global) | medio: el formato de los estados de llama.cpp no es estable entre versiones |
| A6 | Telemetría de alta frecuencia | temperatura y frecuencia por núcleo (hwmon) y GPU por NVML a 20–100 Hz, con marca de tiempo alineable a la traza | energía y temperatura por token y por modo; qué capas o fases calientan | bajo; la potencia de la CPU (RAPL) suele requerir root: iría por el ayudante `prig-energia` o se omite |

---

## 5. Lo que va en C++/CUDA, no en Rust

Para aprender del modelo también hacen falta cambios en el fork. Son de C++ porque viven en el motor:

| Pieza | Para qué | Estado |
|---|---|---|
| Emitir la traza (A1) | todo el grupo A | por hacer (mínimo) |
| Probabilidad de los tokens leídos («sorpresa») | zonas raras del código; dónde razonar más | pendiente: el servidor rechaza `echo` (arquitectura-unificada.md §6.2) |
| Estados ocultos de una capa intermedia | enrutador en el idioma del modelo (etapa 5) | por hacer |
| Expertos calientes de la capa MTP | +3–8 % esperado | por hacer; A2 y A3 dicen cuánto antes de escribirlo |
| Prebúsqueda por PCIe con streams propios | sumar el ancho de banda del PCIe al de la RAM | solo si A3 muestra que el predictor alcanza |

---

## 6. Lo que no conviene pasar a Rust

| Pieza | Por qué no |
|---|---|
| El motor de inferencia (candle, mistral.rs) | perdería el reparto caliente/frío, el solapamiento CPU/GPU, MTP, la omisión de fríos y los núcleos de llama.cpp. Lo medido (38–68 tok/s) es mérito de esos parches |
| Traducción de peticiones y tokens (`motor_moe.py`) | 4,6 µs por token (medido): no hay nada que ganar |
| `app.py` y FastAPI | ~7.700 líneas de E/S y orquestación, sin cálculo pesado |
| Consola aislada `P` | ejecuta el Python que escribe el modelo; sus datos ya los da Rust |
| Lectura por unidades, fichas y examen | el tiempo está en el modelo (25–43 s por unidad) |
| Sensores a 2 s y NVML | ya cuestan microsegundos; solo cambia con A6 |
| Descargas y SHA-256 | `hashlib` ya es C; manda la red |
| Banco del proyecto | ya está en Rust (plan-banco-rust.md) |

---

## 7. Arquitectura propuesta

En el mismo workspace `~/prig-memoria`, con la cadena de compilación que ya existe (`maturin develop --release` en el
`.venv` de Prig):

| Crate | Contenido | Se usa desde |
|---|---|---|
| `moe-traza` | anillo en memoria compartida, consumidor, agregados en vivo, escritura comprimida | Prig (PyO3) y la línea de comandos |
| `moe-analisis` | analizador (A2), simulador (A3), pesos GGUF (A4), estados (A5) | línea de comandos; resultados a `docs/` |
| `prig-sistema` | pausador (B1), FFT (B3), telemetría (A6) | Prig (PyO3) |
| `prig_moe` (PyO3) | la cara de Python de los tres | `frio.py`, `audio_monitor.py`, `motor_moe.py`, Temperaturas |

```
llama-server (C++/CUDA, fork)
   │  por cada capa: ids + pesos ──► anillo en /dev/shm (sin bloquear)
   ▼
moe-traza (Rust) ──► agregados en vivo ──► Prig: Temperaturas → Motor MoE, lista caliente en línea (B2)
   │
   └─► trazas comprimidas ──► moe-analisis (Rust): mapas, co-activación, transiciones, simulador
                                     │
                                     └─► decisiones: listas por perfil, MTP, prebúsqueda, umbrales (medir con KL)
prig-sistema (Rust): pausador sin GIL · FFT · telemetría alineada con la traza
```

---

## 8. Hoja de ruta

| Etapa | Contenido | Criterio para seguir | Esfuerzo |
|---|---|---|---|
| 1 | B1 pausador + B3 FFT | desvío del tramo < 0,5 ms con Python ocupado; el visualizador deja de verse en el uso de CPU | 1–2 sesiones |
| 2 | A1 traza (parche + consumidor) | velocidad con la traza ≥ 99 % de sin ella; salida del modelo idéntica con la traza encendida | 2–3 sesiones |
| 3 | A2 analizador + A3 simulador | el simulador reproduce los aciertos medidos (30,7 / 39,0 / 46,2 %) con ±3 puntos | 4–5 sesiones |
| 4 | Lo que A3 apruebe: B2 y la lista MTP | +5 % de tok/s o más en el uso real (39–42 tok/s hoy), sin perder calidad (KL) | 1–3 sesiones |
| 5 | A6 telemetría, A4 pesos, A5 estados | cada uno deja una tabla nueva en motor-moe.md o arquitectura-unificada.md | 4–7 sesiones |
| — | B4–B6 (biblioteca y vectores) | independientes; medir antes de tocar | 1–3 sesiones cada uno |

La prebúsqueda por PCIe con CUDA propio (semanas) solo entra si la etapa 3 muestra un predictor con recall alto y una
ganancia simulada clara: hoy está descartada con números (42,8 contra 68,9 tok/s sin predictor).

## 9. Riesgos

| Riesgo | Cuidado |
|---|---|
| La traza frena al motor | copia sin bloquear y con presupuesto de 1 %; apagada por defecto; medir con y sin |
| El parche crece y cuesta seguir a llama.cpp | la traza es un punto de enganche chico, junto a `AIPC_CONTAR` |
| Las trazas llenan el disco | rotación y tope, como `PROYECTOS_MAX_MB`; comprimidas |
| El análisis compite con el chat | pasa por la guardia (chat en uso, temperatura, RAM), como el analista |
| Pruebas de esfuerzo que agotan la RAM (pasó el 11/10 con un texto de prueba de 59 GB) | calcular el tamaño antes de armar la entrada; `ulimit -v` |

## 10. Cómo se verifica cada pieza

- **B1:** el mismo experimento de §2 (fracción 0,12, con y sin carga de Python), más la temperatura y los tok/s con el
  modo frío activo antes y después.
- **B3:** el costo por cuadro y el uso de CPU de Prig con el visualizador abierto; las 32 bandas iguales a las de hoy
  (salvo redondeo).
- **A1:** tokens idénticos con la traza encendida y apagada (mismo prompt, semilla y modo exacto); tok/s; registros
  perdidos = 0 en uso normal.
- **A2/A3:** reproducir los aciertos ya medidos antes de confiar en una política nueva.
- **B2 y la lista MTP:** tok/s en uso real y KL con `llama-perplexity` en los modos equilibrado y rápido.
