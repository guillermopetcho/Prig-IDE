# Arquitectura unificada: contexto ilimitado para el motor MoE

Documento de referencia para construir el sistema con el que Qwen3.6-35B-A3B, en una GPU de 6 GB,
se acerca a un modelo de contexto enorme que analiza un proyecto entero. Consolida todo lo pensado y
medido hasta el 29/09/2026. Es la guía para implementar y para retomar el trabajo en otra sesión.

Documentos relacionados:

- [plan-lectura-unica.md](plan-lectura-unica.md): antecedente (fases originales y los experimentos
  de lectura congelada en RAM).
- [memoria-consulta.md](memoria-consulta.md): bitácora de la consola `P` y del grafo.
- [banco-proyecto.md](banco-proyecto.md): el banco simbólico.
- [motor-moe.md](motor-moe.md): el motor, su arquitectura y todas sus mediciones.

Estado de cada pieza: **hecho** (en el código), **validado** (medido, falta construirlo),
**por construir** (diseño firme) e **investigación** (resultado incierto).

---

## 1. Hechos que condicionan el diseño

Todo lo de esta sección está leído del GGUF o medido en esta máquina (i5-13420H con turbo apagado,
RTX 4050 de 6 GB, 62 GB de RAM, NVMe).

### 1.1 El modelo

| Dato | Valor | Consecuencia para el diseño |
|---|---|---|
| Capas | 40: **30 SSM** (Gated DeltaNet) + **10 de atención** (3, 7 … 39) + 1 MTP | solo 10 capas miran tokens individuales |
| Estado SSM | 32 cabezas × 128×128, f32: **~66 MB fijos** | memoria que no crece con lo leído, pero olvida (compuerta de decaimiento). Son «pesos rápidos» que aprenden durante la lectura (regla delta) |
| Caché de atención | 2 cabezas KV × 256 dimensiones × 10 capas: **~10,9 KB por token** en q8 | el único costo que crece con el contexto |
| RoPE | solo **64 de 256** dimensiones llevan posición; base 10⁷ | reubicar un bloque de caché es barato (rotar 64 dimensiones) |
| Atención con compuerta de salida | menos «sumideros» de atención | favorece ventanas deslizantes y atención recuperable (sin probar aquí) |
| MoE | 256 expertos de 1,9 MB por capa, 8 activos + 1 compartido | los expertos calientes en la GPU marcan la velocidad |
| Capa MTP | capa completa con sus propios 256 expertos (Q4_K), siempre en la CPU | pendiente: expertos calientes de la capa MTP |
| Tokens especiales | `<|repo_name|>`, `<|file_sep|>`, FIM, `<think>`, `<tool_call>` presentes | formato de repositorio del preentrenamiento disponible |
| Entrenamiento | agéntico (SWE-bench Verified 73,4); herramientas en XML con parámetros multilínea en crudo | explorar con herramientas es su terreno; el código viaja sin escapar |
| Contexto | 262.144 nativo (hasta ~1M con YaRN) | nunca se usa entero: la VRAM manda |

**Regla que deriva de la arquitectura:** un estado solo es exacto como **prefijo**. Dos lecturas hechas
por separado no se pueden empalmar: el SSM depende de las capas anteriores y la caché de su propio
contexto. Cualquier combinación de lecturas es aproximada (estrategia D) o pasa por texto.

### 1.2 Velocidades y costos medidos

| Medición | Valor |
|---|---|
| Leer (prefill), ubatch 2.048 / 4.096 | 612 / 805 tok/s |
| Escribir, núcleo Q8, 24 calientes, 32K, sin pausas del modo frío | 38–42 tok/s |
| Escribir con las pausas del modo frío anteriores | 22,8 tok/s de media (13,7 con la CPU caliente) |
| **Relación entre escribir y leer** | escribir es **20–80 veces más caro** por token |
| Guardar el estado al final de una unidad de 17,5K tokens | 0,12 s, 257 MB |
| **Restaurar ese estado** (el archivo sigue en la caché de páginas) | **0,08 s** |
| Pregunta nueva sobre una unidad restaurada | 1,1–1,5 s (relee 23 tokens) |
| Volver a una unidad con la caché de RAM del servidor (`--cache-ram`) | 5–6 s (relee ~2.050 tokens desde el último punto de control) |
| Dos secuencias en el mismo motor sin MTP | 43,8 tok/s de conjunto (1,42×), igual que una sola con MTP (42) |
| Carga que lee memoria en los 4 núcleos E | motor −14 % (1 núcleo E: −4 %); el motor no satura la RAM, su límite es el cómputo |
| Aceptación del borrador MTP | 0,87–0,93 en código e inglés técnico; 0,69–0,72 en prosa castellana |
| Muestreo (temperatura 0,2 a 1,0) | no cambia la velocidad |
| Caché KV contra f16 | q8: KL 0,017 · q4: KL 0,034 (descartada) |
| Techo de VRAM | CUDA deja usar ~5.770 de 6.141 MiB; los márgenes actuales son correctos |
| SSD | 4,2 GB/s de lectura directa |

### 1.3 Presupuesto de memoria

| Qué | Tamaño | Dónde |
|---|---|---|
| Pesos (núcleo Q8 + expertos Q4) | ~21 GB | RAM (y los expertos calientes, en la GPU) |
| Un contexto de trabajo de 32K | ~0,36 GB de caché + 66 MB de SSM | GPU |
| Estado de una unidad (17,5K tokens) | ~0,26 GB | SSD, y en RAM por la caché de páginas |
| Biblioteca de ~70 unidades de Prig | ~18–21 GB | SSD / RAM |
| Caché de atención de todo Prig en una pasada (~1,2M tokens) | ~13 GB | RAM (solo con la estrategia C) |
| Total de RAM | 62 GB, ~54 disponibles | alcanza para pesos + biblioteca + sistema |

**Módulos DDR4 de 2 × 32 GB.** Solo sirven si la placa es DDR4 y tiene ranuras libres. El i5-13420H
admite DDR4 o DDR5, pero cada placa usa un tipo, y hoy ya se ven 62 GB (2 × 32 GB probablemente
instalados). Más RAM no agranda el contexto activo, que depende de la VRAM: agranda la biblioteca
residente. Solo haría falta en la etapa C, con varias bibliotecas a la vez.

---

## 2. Principios de diseño

1. **Leer mucho, escribir poco.** Cada agente recibe contexto rico y responde corto y estructurado.
   Una ronda de herramienta obliga a escribir, así que es cara: lo frecuente va precalculado.
2. **Contextos chicos y muchos, no uno gigante.** Trabajar a ≤32K deja 24 expertos calientes y ~40
   tok/s; a 128K o 262K casi no quedan.
3. **El estado se guarda como prefijo, con lo más estable primero.** Así un cambio invalida lo
   menos posible.
4. **Una lectura, muchos productos.** La pasada por el proyecto guarda estados y además mide el
   proyecto con los sentidos del modelo (sección 3.2).
5. **La verdad es simbólica.** El banco (código literal, grafo, fichas verificadas) manda. Lo neural
   (estados, memoria del SSM, atención recuperable) es caché y acelerador: se regenera desde el banco.
6. **Lo borroso propone, lo exacto confirma.** Lo que sale de una memoria con pérdida es una
   hipótesis hasta verificarla contra el grafo, el código o una rama exacta.
7. **Cada escalón funciona aunque falle el siguiente.** Ninguna apuesta de investigación es un punto
   único de falla.
8. **Idioma interno del modelo:** inglés terso, notación de código y formato de repositorio. El
   castellano solo para el usuario. Da menos tokens y más aceptación del borrador (0,9 contra 0,7).
9. **El usuario primero.** Todo trabajo de fondo pasa por la guardia: espera si el chat está en uso,
   si la GPU o la CPU se calientan o si falta RAM.
10. **Medir antes de construir.** El examen del proyecto decide cada etapa.

---

## 3. Componentes

### 3.1 C0: Banco simbólico (hecho)

Índice por archivo, símbolos, fragmentos con FTS5 y vectores `bge-m3`, cambios con diff, memoria,
resoluciones, resúmenes jerárquicos. **Grafo resuelto:** cada llamada va al símbolo exacto (misma
clase, imports, tipo de retorno anotado o nombre único del mismo lenguaje). Además:

- hechos de configuración, entorno, endpoints, frontend, DOM y excepciones;
- consola aislada `P` (`ficha`, `recorrido`, `impacto`, `camino`, SQL, `llm`);
- vigilante que resincroniza cada 4 s;
- analista autónomo con guardia.

Código: `banco_proyecto.py`, `memoria_consulta.py`, `herramientas_chat.py`.

### 3.2 C1 + C2: Partición (hecha) y pasada única con captura múltiple (por construir)

**Partición: hecha** (`backend/particion_proyecto.py`, tabla `unidades` del banco). En Prig (29/09/2026):

| Medida | Valor |
|---|---|
| Código de producción | 162 archivos, 1,22M tokens (sin tests ni documentación) |
| Piezas | 193 (20 archivos partidos por símbolos; `youtube_hub.js` 89K y `app.py` 79K son los mayores) |
| Unidades | 94, de 13K tokens de media y 16K como máximo |
| Peso de las conexiones que cruza entre unidades | 0,85 (partición ingenua por ruta: 0,96) |
| **Cobertura por las 6 vecinas** (lo que cruza, cubierto por las interfaces que irán en el contexto) | **0,94 de media**; mínimo 0,32 en los «centros» como `app.py`, que dependen de la tarjeta global |
| Tiempo | 0,2 s |

Las variantes de normalización del agrupamiento dan casi lo mismo. Con un tope de 20K salen 79
unidades y el corte baja a 0,76, a cambio de contextos más largos.


**Partición (sin modelo):**

- Comunidades del grafo resuelto (Leiden o Louvain) respetando las carpetas: **unidades de ≤16K
  tokens de código**.
- Los archivos gigantes (`app.py` ~80K tokens, `index.html`) se parten por grupos de símbolos
  relacionados.

**Orden de lectura** (clave para la memoria del SSM, que olvida con la distancia):

1. Primero las dependencias (de abajo hacia arriba en el grafo condensado).
2. Lo relacionado, contiguo: un orden lineal que minimice la distancia entre las partes que se
   llaman.
3. Lo estable primero y lo que se edita seguido al final, según git. Así una edición invalida solo
   la cola del tronco.
4. Dentro de cada unidad: definiciones antes que usos, como un libro.

**Productos de una sola pasada:**

| # | Producto | Para qué | Cómo se captura hoy |
|---|---|---|---|
| 1 | Estado al final de cada unidad | ramas (C3) | `/slots?action=save` tras leer con `n_predict: 0` (validado) |
| 2 | Caché de atención completa | atención recuperable (C, investigación) | requiere parche |
| 3 | Expertos usados por la unidad | lista caliente por rama (velocidad) | contadores `AIPC_CONTAR` / `/aipc/uso` |
| 4 | Estados ocultos por fragmento | índice en el idioma del modelo (enrutador) | parche liviano (salida de embeddings de una capa intermedia) |
| 5 | Sorpresa por token (log-probabilidad) | zonas raras o sospechosas: dónde analizar y razonar más | logprobs del servidor |
| 6 | Aceptación del borrador MTP por zona | qué tan predecible es cada parte; estimar costos | estadísticas del borrador |

### 3.3 C3: Biblioteca de lecturas, tronco y ramas (ramas validadas; tronco en investigación)

**Ramas (estrategia A, validada).** Cada unidad se guarda como estado exacto con este prefijo por
capas:

| Capa | Contenido | Tamaño | Cambia |
|---|---|---|---|
| 1 | Sistema del lector (reglas y formato) | ~1K | casi nunca |
| 2 | Tarjeta global vN (mapa, subsistemas, glosario, conceptos) | ~6–8K | por versión |
| 3 | Contexto de la unidad (papel, quién la usa, interfaces de las vecinas) | ~2–4K | cuando cambian las vecinas |
| 4 | Código de la unidad en formato de repositorio | ~14–18K | al editar |
| — | **estado guardado aquí** | | |
| 5 | Tarea o pregunta | ~0,5–6K | cada vez |

**Tronco (estrategia B, investigación).** Lectura en cadena de todo el proyecto con la atención
limitada a una ventana (p. ej., 32K), mientras las capas SSM acumulan. Se guarda el estado en cada
frontera. Así cada rama que sale del tronco tiene el detalle exacto de su unidad **más** la memoria
comprimida de todo lo anterior.

- **Repaso espaciado:** reinsertar cada tanto la tarjeta global y las interfaces clave (cientos de
  tokens) para refrescar la memoria del SSM.
- **Requiere un parche:** llama.cpp no descarta hoy la caché vieja en modelos híbridos mientras el SSM
  sigue. El RoPE parcial abarata el desplazamiento de posiciones.
- **Si falla, las ramas siguen funcionando solas.**

**Llave de cada estado:** modelo + núcleo (Q4/Q8) + versión del motor + tipo de caché + versión de la
tarjeta global + hash del contenido de la unidad. Si cambia cualquiera, el estado deja de valer y se
regenera en horas ociosas.

**Almacenamiento:**

- en el SSD, bajo `~/.cache/prig-moe/`, con el tope subido de 20 a ~30 GB;
- lo usado reciente queda en RAM por la caché de páginas;
- poda por uso.

### 3.4 C4: Fichas, verificación y mapa de conceptos (por construir)

**Fichas por símbolo**, producidas desde la rama restaurada (solo cuesta escribir), en inglés terso:

- qué hace y cómo (con líneas);
- contrato: entradas, salidas y precondiciones;
- efectos: archivos, red, configuración y estado global;
- invariantes y riesgos;
- «para cambiar X, tocar aquí»;
- preguntas que la unidad responde (índice inverso).

**Verificación sin modelo:**

- los nombres existen;
- cada `archivo:línea` citado dice lo que se afirma;
- las constantes coinciden;
- los efectos declarados figuran en el grafo.

Lo dudoso vuelve a su rama para una segunda mirada. Idea de PROOF: una ficha es buena si desde ella
se puede predecir el comportamiento del código.

**Mapa de conceptos** (casi sin modelo, sobre los hechos del grafo): cada clave de configuración,
endpoint, elemento de la interfaz y archivo de datos del usuario, con quién lo define, lee, escribe,
expone y consume. El modelo solo pone los nombres humanos.

**Círculo virtuoso:**

- las ramas abaratan las fichas;
- las fichas verificadas alimentan la tarjeta global y el repaso del tronco;
- las fichas son el puente entre ramas (C6);
- las fichas le dan al banco el «entender».

### 3.5 C5: Enrutador (parcialmente hecho)

Elige qué rama o ramas abrir. Combina, de más barato a más fino:

1. el mapa de conceptos y los hechos del grafo (exacto);
2. las preguntas inversas y los vectores de las fichas;
3. **las claves y estados ocultos del propio modelo** (producto 4): se lee la pregunta y se compara
   con las unidades en el espacio del modelo. Es la parte útil de la atención recuperable (C), sin
   tocar CUDA.

### 3.6 C6: Razonador (por construir sobre piezas hechas)

| Caso | Cómo |
|---|---|
| Pregunta exacta («quién lee X») | consola `P` / hechos: sin restaurar nada |
| Una unidad | restaurar la rama (0,08 s) + delta de cambios + responder |
| Varias unidades | rama principal restaurada + **fichas de las otras inyectadas como texto** (leer es barato); o una nota por rama y una síntesis final (RLM / Chain-of-Agents) |
| Zona rara o difícil (mucha sorpresa) | más esfuerzo donde rinde: varias muestras sobre la rama restaurada (autoconsistencia), releer la unidad con la tarea al principio, `think` acotado |

La rama restaura también su **lista de expertos calientes** (por `/aipc/calientes`, sin reiniciar):
la velocidad viaja con la rama.

### 3.7 C7: Verificación de respuestas (parcialmente hecho)

Toda afirmación con nombre, número o `archivo:línea` se contrasta con el banco antes de mostrarse.
Lo que viene de memorias con pérdida (tronco, atención recuperable, fusión) es hipótesis hasta
confirmarse.

### 3.8 C8: Flujo de cambio (por construir)

1. **Localizar:** mapa de conceptos + enrutador; una llamada corta para elegir.
2. **Planificar:** fichas + `P.impacto`, con razonamiento acotado. Sale un plan de archivos, orden y
   tests exactos (del grafo).
3. **Editar:** un contexto por archivo, sobre el código literal y actual, en modo «solo código» o
   como diff.
4. **Verificar:** sintaxis + los tests del plan; si fallan, como máximo 2 o 3 vueltas y después
   parar y mostrar.
5. **Registrar:** resolución, decisión y notas. El vigilante reindexa y la rama tocada se reestudia.

Con aprobación del usuario al principio.

### 3.9 C9: Mantenimiento (parcialmente hecho: vigilante y guardia)

- Una edición invalida la rama de su unidad, y en el tronco, todo lo posterior. Por eso lo estable va
  primero (C1).
- Cambios chicos: se inyecta el **delta** (diff) tras restaurar, hasta la reconstrucción nocturna.
- Si cambió un **contrato**, se marcan las vecinas para revisar; si cambió solo el cuerpo, no se
  propaga.
- La tarjeta global se versiona y se rehace (y con ella todas las ramas) solo cuando el delta
  acumulado lo justifica.

### 3.10 Módulos de investigación

| Módulo | Idea | Riesgo principal | Depende de |
|---|---|---|---|
| B: ventana deslizante | tronco para todo el proyecto con la memoria del SSM | cuánto olvida el SSM; el modelo no se entrenó con ventana | parche en llama.cpp |
| C: atención recuperable | cada capa de atención trae de la RAM los bloques del proyecto más parecidos a lo que está pensando (InfLLM adaptado); buscar cada ~16 tokens con las consultas del paso anterior; búfer fijo en la GPU con los mejores bloques; posición «lejana» con RoPE parcial | no probado en híbridos; la sincronización por capa ya costó −38 % con los expertos | B (claves calculadas en contexto) y semanas de CUDA/C++ |
| D: fusión de lecturas | SSM de la raíz + lo que aportó cada rama; atención concatenada con posiciones corridas; recalcular solo los tokens de las costuras (CacheBlend) | interferencia entre memorias | exportar e importar estados (sin CUDA) |

---

## 4. Flujo completo

```
                 ┌──────────── BANCO SIMBÓLICO (verdad) ────────────┐
                 │ código literal · grafo resuelto · fichas · mapa  │
                 └──────────────┬───────────────────────▲───────────┘
                    ordena y     │                       │ verifica
                    enruta       ▼                       │ (hipótesis → confirmación)
   PASADA ÚNICA (tronco) ──▶ estados en cada frontera ──▶ RAMAS por unidad
   orden por grafo + git       + caché de atención (RAM)     detalle exacto
   repaso espaciado            + expertos por unidad         + fichas (texto)
                               + estados ocultos (índice)    + expertos calientes
                               + sorpresa y aceptación MTP
                                          │
                          PREGUNTA ──▶ enrutador en el idioma del modelo
                                          │
                  una rama ◀──────────────┼──────────────▶ varias ramas
          (restaurar 0,1 s + responder)   │     (rama principal + fichas de las otras)
                                          ▼
                     esfuerzo guiado por sorpresa (muestras, relectura)
                                          ▼
                     verificación exacta ──▶ respuesta + registro
```

**Ciclo de vida:**

1. **Primera vez:** partición → pasada única de noche, con guardia → fichas → verificación → mapa.
2. **Cada pregunta:** enrutar → restaurar → responder → verificar → registrar.
3. **Cada cambio:** flujo de cambio → vigilante → invalidar → reestudiar en ocio.

---

## 5. Degradación elegante

| Si falla… | Queda funcionando… |
|---|---|
| la memoria del tronco (B) es muy borrosa | ramas exactas (A) + fichas como puente |
| la atención recuperable (C) no rinde | enrutador con las claves del modelo + ramas |
| la fusión (D) degrada | inyectar fichas como texto |
| las fichas se equivocan | verificación contra el grafo y el código |
| el enrutador elige mal | consola + hechos exactos |
| un estado quedó viejo (cambió el modelo o el motor) | se regenera desde el banco; mientras, lectura normal |

---

## 6. Hoja de ruta

| Etapa | Contenido | Riesgo | Criterio para seguir | Costo estimado |
|---|---|---|---|---|
| 0 | **Examen del proyecto** (`examen_proyecto.py`, **hecho**): 153 preguntas de 9 tipos generadas del banco, corrección automática con aciertos e inventos, guardado en el banco | nulo | existe y es reproducible | cumplido |
| 1 | **Partición y orden** (`particion_proyecto.py`, **hecho**) | nulo | 100 % del código de producción, unidades ≤16K | cumplido: 94 unidades, 0,2 s |
| 2 | **Pasada por unidades con captura múltiple** (`lectura_unidades.py`): **hecha** (94 unidades, 26 GB), con enrutador y modo unidad en el chat; **examen completo 97,7 %** | bajo | «detalle exacto» ≥ 90 %; < 2 s por pregunta | aciertos cumplidos; tiempo: mediana 16,6 s (4 s en ubicación, pero la mayoría de los tipos llevan una consulta) |
| 3 | **Fichas, verificación y mapa de conceptos**; puente de fichas entre ramas | bajo-medio | afirmaciones verificadas ≥ 95 %; «ubicación» e «impacto» ≥ 90 % | ~1,5 h para Prig |
| 4 | **Tronco sin parche** (en cadena hasta 262K) + **curva de recuerdo** del SSM + repaso espaciado | medio | recuerdo útil fuera de la ventana | ~1 h |
| 5 | **Enrutador con estados ocultos** (producto 4) | medio | mejor elección de rama que `bge-m3` | parche liviano |
| 6 | **Parche de ventana deslizante** (B completo) | alto | lo justifica la curva de la etapa 4 | semanas |
| 7 | **Atención recuperable** (C) | muy alto | el examen supera a ramas + orquestación | semanas |
| — | **Fusión D** (experimento lateral, cuando convenga) | medio | ≥ 80 % de lo que da la lectura secuencial | días |

Las etapas 0 a 3 ya dan un sistema completo y mejor que el actual. La 4 decide, con números, si la 6
y la 7 valen las semanas de ingeniería.

---

## 6.1 Resultados del examen (piloto, 29/09/2026)

Piloto de 27 preguntas (3 por tipo) por `/api/ai/chat`, con el motor MoE (núcleo Q8, 24 calientes,
modo frío con holgura). **Ollama estaba apagado, así que el banco buscó sin vectores** (palabras +
grafo).

| Variante | Aciertos | Respuestas con inventos | Tiempo medio |
|---|---|---|---|
| Sin banco (solo la pregunta) | 14,8 % | 13 de 27 | 24 s |
| Banco actual (contexto + consola `P`) | 95,1 % | 1 de 27 | 31 s |
| **Banco + empujón de continuación** | **96,3 %** | 2 de 27 | 28,5 s |

Por tipo, con el empujón:

- 100 %: config, constante, endpoint, entorno, frontend, impacto, recorrido y ubicación.
- 67 %: llamadores.

**Hallazgos:**

- **Anunciar sin hacer.** Con herramientas, el modelo a veces anuncia la próxima consulta («Ahora
  busco qué endpoints…») y cierra el turno sin ejecutarla. Una respuesta de impacto quedó en 0.
  Solución: `anuncia_sin_hacer` + `EMPUJON` en `app.py` (hasta dos veces, con lo ya dicho delante).
  Impacto subió de 0,67 a 1,0.
- **Inventos mal contados.** El corrector contaba como inventados atributos, constantes y
  manejadores que sí existen. Ahora un nombre solo es invento si no aparece en ninguna parte del
  código. Los recorridos alternativos que son cadenas reales del grafo cuentan como correctos.
- **Punto débil que queda:** los llamadores dentro de archivos JS gigantes (`youtube_hub.js`, 89K
  tokens). El modelo usa `grep` en lugar de `P.llamadores` y nombra otros llamadores. También hubo
  un invento real (`servidor_efecto`) dentro de una respuesta correcta.

**Pendiente:** el examen completo (153 preguntas) en las dos variantes como línea de base, y la
misma medición con vectores cuando Ollama esté en marcha.

## 6.2 Etapa 2: lectura por unidades, piloto (29/09/2026)

`backend/lectura_unidades.py`, sobre 5 unidades del subsistema motor/térmica (37–41).

**Diseño final (después de tres intentos):**

- **La lectura pasa por el mismo camino que el chat** (`AIEngine.chat_eventos` → motor MoE). El motor ya
  guarda el estado de cada prefijo grande como «proyecto», con clave por el texto renderizado, y
  también sus expertos calientes. Así cualquier pregunta posterior con el mismo prefijo restaura la
  unidad y su lista de expertos sin nada extra.
- **La lista de herramientas es fija** (`consola`, `ver_simbolo`, `anotar`, con
  `Herramientas(solo=…)`). La plantilla del modelo pone las herramientas antes del sistema: si la
  lista cambiara, el prefijo no coincidiría y habría que releer.
- **El sistema del lector incluye la ayuda de la consola y una guía de qué primitiva usar según la
  pregunta.** Sin la ayuda, el modelo inventaba métodos de `P` (`P.vista_previa`, `P.ficheros`) e
  intentaba importar módulos: 0,37 de aciertos. Con la ayuda, 0,77. Con la guía, 0,955.
- **Tope de estados guardados del motor:** de 20 a 32 GB (`PROYECTOS_MAX_MB`).

**Mediciones:**

| Medida | Valor |
|---|---|
| Lectura de una unidad (15–26K tokens con tarjeta global y contexto) | 25–43 s, una sola vez |
| Estado guardado | 232–348 MB por unidad |
| Restaurar (clave encontrada en disco) | 0,2–0,3 s por el camino del chat; 0,07–0,10 s directo al servidor |
| Pregunta cuya respuesta está en la unidad (constante, ubicación) | **1,4–1,8 s, sin herramientas** |
| Pregunta que cruza unidades (llamadores, recorridos) | 6–10 s con 1 llamada a la consola; algunos recorridos 60–130 s |
| **Aciertos del examen** (11 preguntas de estas unidades) | **95,5 %** |
| Expertos calientes de la unidad contra los globales | aciertos en GPU 35,9 → 46,2 %; 29,6 → 33,2 tok/s (+12 %) |
| Solo la lectura restaurada, sin herramientas | 100 % en preguntas dentro de la unidad; 0,42 en recorridos que empiezan en otra unidad, e **inventa** cuando le falta información |

**Lecciones:**

- Una sola unidad restaurada no alcanza para las preguntas que cruzan unidades, y sin herramientas
  el modelo inventa. La combinación unidad restaurada + consola resuelve las dos cosas.
- Cambiar el código cambia las respuestas del examen (una constante editada quedó con una respuesta
  vieja): **el examen hay que regenerarlo después de cada cambio.** `generar()` ahora descarta
  preguntas repetidas.
- La **sorpresa** por token no está disponible: el servidor no devuelve la probabilidad de los tokens
  leídos (`echo` rechazado). Hace falta un parche, o `llama-perplexity` por ventanas de 512 tokens.

**Pasada completa (29/09/2026): hecha.** Las 94 unidades vigentes, con
`python backend/lectura_unidades.py --pasada`, que es reanudable: salta lo vigente y deja el registro
en `~/.cache/prig-moe/pasada.log`.

- 76 unidades leídas en 64 min (las otras 18 venían de antes de un corte de energía).
- 26 GB en `~/.cache/prig-moe/proyectos`, después de borrar 17 estados viejos de los pilotos.
- Hubo un corte abrupto a mitad de camino: el equipo no detecta batería y el registro no muestra
  eventos de temperatura. Por eso la pasada es reanudable.

**Enrutador y modo unidad en el chat: hechos.**

- `LectorUnidades.elegir_unidad`: símbolos y rutas nombrados, búsqueda del banco y hechos del grafo.
  Elige solo si una unidad se despega (cuota ≥ 0,35 y 1,5 veces la segunda). Sobre el examen: elige
  en el 70 % de las preguntas y acierta la unidad en el 92 % de esas.
- `app._unidad_para` + modo unidad en `_chat_eventos`: con el banco, el motor MoE y sin gancho ni
  código del editor, la conversación usa el prefijo de la unidad (el motor la restaura con sus
  expertos) y las herramientas fijas. Si no hay unidad clara, se usa el modo general.

**Examen completo en modo unidad (153 preguntas, 29/09/2026).** Se completó en tres corridas: 98
preguntas, 55 restantes y las 2 que se habían colgado, repetidas tras corregir la consola.

| Tipo | Aciertos | Tiempo medio | Mediana |
|---|---|---|---|
| config | 1,000 | 32,2 s | 21,6 s |
| constante | 1,000 | 15,5 s | 13,8 s |
| endpoint | 0,941 | 18,6 s | 17,7 s |
| entorno | 1,000 | 18,2 s | 15,6 s |
| frontend | 0,882 | 23,3 s | 19,8 s |
| impacto | 1,000 | 48,2 s | 26,4 s |
| llamadores | 1,000 | 10,2 s | 8,0 s |
| recorrido | 0,971 | 51,5 s | 36,4 s |
| ubicacion | 1,000 | 4,1 s | 4,0 s |
| **Total** | **0,977** | **24,7 s** | **16,6 s** |

- 3 respuestas de 153 con inventos.
- El enrutador eligió unidad en el 68 % de las preguntas de la continuación (39 de 57); el resto fue
  por el modo general.
- Comparación con el piloto de 27 preguntas: sin banco 14,8 %; banco general 96,3 %.

**El «tiempo alto» no era el enrutador** (mide 0,2–0,25 s, incluida la verificación de vigencia).
Eran dos preguntas colgadas, una de **30 minutos**, por tres fallas de la consola, ya corregidas en
`memoria_consulta.py`:

1. **Espera sin límite.** Prig esperaba con `readline()` bloqueante y el tope de 630 s nunca se
   aplicaba. Ahora espera con `select` y tiene un tope real de 180 s por ejecución, subllamadas
   incluidas; si lo pasa, la consola se reinicia.
2. **Respuestas desordenadas.** La alarma de 30 s corría mientras la consola esperaba una subllamada
   `P.llm`; al saltar, la respuesta tardía se tomaba como la de la ejecución siguiente. Ahora la
   alarma se pausa durante la espera y cada petición lleva un número.
3. **Sin tope por respuesta.** No había límite de `P.llm` por respuesta, solo 12 por ejecución.
   Ahora son 24 por respuesta.

Repetidas, las dos preguntas tardan 28 s y aciertan.

**Pendientes:**

- Tras cada edición, releer las unidades tocadas: `--pasada` lo hace solo.

## 6.3 Etapa 3 (en curso): datos más finos, prefijo estable y mapa de «dónde está»

**Lo que mostraron las fallas del examen completo:**

- **Funciones anidadas.** Los endpoints de un `APIRouter` son funciones dentro de otra
  (`crear_router`). No eran símbolos: el endpoint quedaba atribuido a la función de afuera y las
  cadenas de llamadas que pasaban por ellas se perdían («no hay camino», cuando sí lo había).
  Esquema 5 del banco: 231 funciones anidadas en Prig, 31 endpoints ahora atribuidos a la función
  que los implementa, y las llamadas se resuelven hacia ellas.
- **Preguntas de frontend ambiguas.** La llamada vive en un manejador anónimo dentro de una función
  con nombre. La pregunta ahora pide explícitamente la función con nombre que la contiene.

**Falla de diseño corregida: el prefijo guardado tenía partes volátiles.** Cada unidad guardaba en
su prefijo:

- su contexto del grafo («qué usa de otras unidades, quién la usa»);
- la ayuda de la consola.

Una mejora del grafo o una línea nueva en la ayuda invalidaba las 94 lecturas; peor, **editar OTRA
unidad** cambiaba el «quién la usa» de esta, y las invalidaciones se propagaban en cascada. Pasó dos
veces. Ahora:

| Parte | Dónde va | Cambia cuando… |
|---|---|---|
| Sistema del lector (corto, fijo) | prefijo guardado | nunca |
| Tarjeta global | prefijo guardado, **congelada en el banco** (`renovar_tarjeta()` a pedido) | el usuario la renueva |
| Código de la unidad | prefijo guardado | se edita esa unidad |
| Contexto del grafo, guía y API de la consola, pregunta | **mensaje de cada pregunta** (~1–2K tokens, ~2 s de lectura) | siempre fresco |

Además, la partición se recalcula antes de cada pasada (las líneas se corren al editar). Una unidad
cuyo contenido no cambió se reconoce por su llave y se reusa sin llamar al modelo, aunque cambie de
número.

**Mapa de «dónde está cada cosa»: `P.donde(x)`** (sin modelo, < 0,2 s). Para una clave de
configuración, un endpoint, una variable de entorno, un id del DOM, un archivo de datos o un símbolo,
junta en un llamado:

- los hechos del grafo por relación (quién lo lee, lo expone o lo consume);
- la función que implementa el endpoint y quién la llama;
- dónde aparece como texto literal (defaults, formularios, rutas).

Por ejemplo, `P.donde("moe_modo")` devuelve el valor por defecto, los dos lectores y el endpoint que
lo escribe.

**Fichas por símbolo** (`backend/fichas_simbolos.py`), piloto sobre las 5 unidades del motor y la
térmica (30/09/2026):

- 246 fichas, a ~6 s por símbolo, en inglés terso: qué hace, contrato, efectos, riesgos y dónde
  cambiarlo.
- **240 verificadas sin problemas (97,6 %).** La verificación sin modelo comprueba que:
  - el símbolo exista;
  - cada nombre citado exista en el código;
  - cada línea citada caiga en el símbolo, o contenga lo que la ficha cita (la constante o el
    default que usa).
- Las 6 marcadas citan líneas que no contienen lo afirmado (por ejemplo, `RESERVA_CUDA_MB` en
  l.68-69, cuando está en la 54).
- Con tandas de 20 símbolos, 2 tandas no devolvieron JSON válido (40 símbolos). Ahora las tandas son
  de 12; esos 40 quedan pendientes (se rehacen con `fichar_unidad`, que solo toma lo que falta).

**Examen completo con el prefijo estable: pausado a pedido en 58 de 153, con una REGRESIÓN.**

| Tipo | Antes (corrida anterior) | Ahora |
|---|---|---|
| config | 1,000 | 0,824 |
| constante | 1,000 | 0,882 |
| endpoint | 0,941 | 0,588 |
| entorno | 1,000 | 0,857 |
| **Total (58 preguntas)** | — | **0,776** |

**Causa encontrada:** en modo unidad, el modelo escribe la consulta como texto de su respuesta (por
ejemplo `P.api("DELETE /api/banco/resoluciones/*")`) en vez de llamar a la herramienta `consola`.
Empezó al mover la guía de la consola del sistema al mensaje de la pregunta: el modelo la toma como
«responde con este código».

**Arreglos previstos:**

1. En `guia_consola()`: «llama a la herramienta `consola` con ese código; nunca escribas código de P
   como respuesta».
2. En `_chat_eventos`: si la respuesta es solo código `P.…`, ejecutarlo en la consola y pedirle al
   modelo que responda con el resultado (como el empujón).

Después, retomar el examen con
`ex.correr(banco, "etapa3", preguntar, saltar_de="etapa3-20260930-012218")`.

## 7. Experimentos pendientes

1. **Examen del proyecto** (etapa 0). Generado del grafo y el código, con corrección automática.
   Opcional: comparar con un modelo en la nube (Gemini está integrado y apagado; mandaría código
   afuera).
2. **32K contra 64K por unidad.** Calidad de ficha contra velocidad (a 64K entran menos expertos
   calientes).
3. **Curva de recuerdo del SSM** (etapa 4). Leer las unidades 1…k en cadena y preguntar por la
   unidad j < k según la distancia. Primero sin parche, hasta 262K, con la GPU sin expertos calientes.
4. **Repaso espaciado.** La misma curva, con y sin reinserción de la tarjeta global.
5. **Sorpresa como señal.** ¿Coinciden las zonas de mayor sorpresa con bugs conocidos, código
   inconsistente o partes difíciles del examen?
6. **Expertos calientes por rama.** Aciertos en GPU y tok/s contra la lista global (medido por
   proyecto: 30,7 % → 39,0 %).
7. **Autoconsistencia y relectura dirigida sobre una rama restaurada.** Ganancia en el examen contra
   el costo en escritura.
8. **Fusión D.** Exportar el estado de dos ramas, fusionarlas con y sin recalcular las costuras, y
   comparar con la lectura secuencial.
9. **Expertos calientes de la capa MTP** (parche del motor). Esperado: +3–8 %.

---

## 8. Descartado (con el número que lo descarta)

| Idea | Por qué no |
|---|---|
| Dos copias del modelo (una lee, otra razona) | ~41 GB de RAM sin ganancia: un servidor atiende varias lecturas con una sola copia |
| Dos secuencias en paralelo sin MTP | 43,8 tok/s de conjunto = una sola con MTP (42). Solo sumaría con MTP en ambas (parche del reparto a >4 tokens por paso) |
| Motor grande en los núcleos E | rinden la mitad; una carga de memoria allí frena al motor principal un 14 % |
| Traer expertos por PCIe o desde el SSD por token | −38 % medido; la sincronización por capa cuesta más que el cálculo |
| Contexto de 1M con la caché en RAM | ~0,3 s por token al generar |
| Caché KV en q4 | duplica la pérdida (KL 0,034 contra 0,017) |
| Caché KV mixta (K f16, V q8) | sin kernel rápido de flash attention: ~24 min contra 3 |
| Borrador MTP de 3 tokens | la aceptación cae de 0,91 a 0,78 y la velocidad no sube |
| Achicar los márgenes de VRAM | CUDA solo deja usar ~5.770 MiB: ya están calibrados |
| Pausas del modo frío para el MoE con el turbo apagado | costaban casi la mitad de la velocidad por 4 °C (reemplazadas por una holgura de 8 °C) |
| Entrenar pesos con el repositorio (LoRA / TTT) | sin entrenamiento posible para esta arquitectura en este hardware; lo más cercano ya está en el SSM |
| Empalmar estados SSM de lecturas distintas | no son sumables de forma exacta (solo como la fusión aproximada D) |
| El muestreo como palanca de velocidad | medido: no cambia |

---

## 9. Decisiones

**Tomadas y aplicadas:**

- Holgura térmica del MoE con el turbo apagado.
- Ubatch 2.048 hasta 32K.
- Muestreo por uso.
- Analista en inglés terso.
- Grafo resuelto al símbolo exacto.

**Pendientes del usuario:**

1. Aprobación de diffs en el flujo de cambio (recomendado al principio).
2. Disco para la biblioteca: ~20–30 GB.
3. Comparar con un modelo en la nube en el examen: sí o no.
4. Tamaño por unidad: lo decide el experimento 2.
5. Módulos DDR4: verificar el tipo de RAM de la placa y las ranuras libres antes de instalarlos.
6. **Contexto del motor fijo en 262.144 en la configuración del usuario:** conviene ponerlo en
   «auto». Con 262K no entra ningún experto caliente.

---

## 10. Fuentes

- ReadAgent: gists y búsqueda de páginas. [arXiv 2402.09727](https://arxiv.org/abs/2402.09727)
- Recursive Language Models: el contexto como variable y subllamadas. [arXiv 2512.24601](https://arxiv.org/abs/2512.24601)
- LocAgent: grafos para localizar código. [arXiv 2503.09089](https://arxiv.org/abs/2503.09089)
- Codebase-Memory: grafo con tree-sitter; 83 % contra 92 % leyendo archivos, con 10× menos tokens. [arXiv 2603.27277](https://arxiv.org/abs/2603.27277)
- PROOF: especificación verificada que se mantiene sincronizada con el código. [arXiv 2609.06383](https://arxiv.org/abs/2609.06383)
- Qwen3.6-35B-A3B: ficha del modelo (arquitectura, muestreo, MTP). [Hugging Face](https://huggingface.co/Qwen/Qwen3.6-35B-A3B)
- Ideas citadas sin medir aquí: InfLLM / RetrievalAttention (atención recuperable), CacheBlend
  (reparar costuras), Titans / TTT (memoria que aprende en inferencia), RE2 (releer mejora el
  razonamiento).
