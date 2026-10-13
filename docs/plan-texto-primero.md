# Plan 0 — Texto primero: el banco es la memoria, los estados del motor un caché descartable

**Tareas especificadas para implementar** (una por archivo, para repartir entre modelos): `docs/plan-texto-primero/`
(README con reglas comunes, dependencias y reparto; T1–T8).

Origen: el estudio del banco (`docs/estudio-banco.md`). Allí el **modo general**, que no usa ningún estado guardado y arma
el contexto con texto del banco, acertó **97 %** frente a **86 %** del modo unidad (que restaura la lectura guardada).
Los estados ocupan ~21 GB por millón de tokens y no se comprimen (zstd: −4 %); el banco de texto, ~30 MB por millón. La
capa de estados fue además la fuente de 3 de los bugs de infraestructura del estudio. Conclusión: la memoria del
proyecto es el texto; los estados son un acelerador.

## 1. Qué es «hecho» (criterios)

1. **Disco acotado**: los estados del motor nunca superan un tope configurable; con tope 0 no se guarda ninguno. El banco
   (SQLite) es lo único obligatorio.
2. **Ninguna respuesta depende de un estado**: sin estado, la pregunta se responde en modo general con un contexto de la
   misma calidad, sin errores ni avisos raros.
3. **Exactitud medida**: el modo general (sin estados) iguala o supera al de unidad en las mismas preguntas (examen de E7)
   y en encontrar errores (E8). Si en algo pierde, está medido cuánto y hay un camino para recuperarlo (leer al vuelo).
4. **Visible y controlable**: el usuario ve cuánto ocupa el caché, cambia el tope y lo vacía desde la app.
5. **Probado**: tests de cada pieza y la batería completa en verde.

## 2. Lo que hay hoy (revisado en el código, 09/10/2026)

| Pieza | Qué hace | Lo que importa para el plan |
|---|---|---|
| Banco (`banco_proyecto.py`, SQLite) | código comprimido, símbolos, grafo y hechos, fragmentos con FTS, resúmenes, notas, resoluciones, cambios, unidades, lecturas, fichas | ya es la memoria permanente (Prig: 38 MB para 1,27 M tokens) |
| Motor (`ai_engine/motor_moe.py`) | guarda un estado para **cualquier** conversación cuyo primer mensaje tenga ≥ 12.000 caracteres y siga después (unidades, mapa + archivos enganchados del modo general); lo restaura si existe | tope global **fijo** `PROYECTOS_MAX_MB = 32 GB`, poda por último uso (restaurar actualiza la fecha); `olvidar_proyectos()` y un botón «borrar proyectos» en el panel del motor (`temperaturas.js`); `proyectos_guardados()` informa archivos y MB. En RAM, llama-server guarda prompts recientes (`--cache-ram 16384`) |
| Lectura por unidades (`lectura_unidades.py`) | parte el proyecto en unidades de ≤ 16K, las lee y guarda su estado; `vigente` = misma llave **y** archivo en disco; `reasignar` borra estados que ya no sirven (respetando otros bancos) | la pasada **solo existe por línea de comandos**; el resumen de cada unidad se guarda pero **nada lo usa** |
| Chat (`app.ai_chat`) | modo unidad **solo si** la unidad elegida está vigente; si no, modo general | el desvío al modo general **ya existe**: es la base del plan |
| Contexto del modo general (`componer`) | cambios recientes, notas, resoluciones parecidas, **código literal** relevante, símbolos relacionados | **no** recibe los hechos del grafo que desde hoy recibe el modo unidad (`hechos_de_la_pregunta`) |
| Texto destilado | «Analizar» (resumen por archivo y jerárquicos) se usa en el mapa y el contexto; fichas por símbolo verificadas | las fichas **no se usan** |

Disco hoy: 104 estados = 28,2 GB; 88 son del banco real de Prig (24,3 GB) y 16 solo del estudio (3,9 GB); 0 huérfanos.
Restos del estudio en `~/.cache/prig-estudio`: 253 MB.

## 3. Decisiones (alternativas analizadas)

| # | Decisión | Alternativas | Elegida y por qué |
|---|---|---|---|
| D1 | Fuente de verdad | texto / estados | **Texto (el banco)**. Los estados son un caché que se puede borrar en cualquier momento sin perder nada |
| D2 | Qué pasa si la unidad no tiene estado | modo general · leer al vuelo (25–35 s y guardar) · rechazar | **Modo general** por defecto (ya existe, midió mejor). **Leer al vuelo** solo si se pide (modo «unidad» forzado o «análisis a fondo»). Rechazar, nunca |
| D3 | Tope del caché | fijo en el código (hoy) · configurable · % del disco libre | **Configurable** (`moe_cache_gb`, 0 = apagado) **y** una reserva de disco libre que nunca se toca (`moe_cache_reserva_gb`). Valor por defecto al implementar: **32 GB**, el tope fijo de hoy: así nada cambia ni se poda lo que hay que medir. El valor final se decide con la medición (fase D / T7) |
| D4 | Qué entra en el caché | todo prefijo grande (hoy) · solo unidades leídas a pedido · solo las usadas ≥ 2 veces | **Todo prefijo grande, dentro del tope, desalojando por último uso** (ya funciona así; solo cambia el tope). Con tope 0, el motor lee y **no guarda** |
| D5 | Paridad del modo general | dejarlo como está · darle los hechos del grafo | **Darle los mismos hechos** (`hechos_de_la_pregunta`) que al modo unidad: es lo único que tiene el de unidad y el general no |
| D6 | Conocimiento destilado para compensar la falta de lectura completa | ninguno (solo código literal) · resúmenes por unidad · fichas por símbolo | **Ninguno nuevo de entrada** (el general ya ganó sin ellos). Si E8 muestra que el general no encuentra errores que la lectura completa sí, se activan las **fichas** (ya existen y están verificadas) |
| D7 | La pasada de lectura | obligatoria · opcional desde la app · eliminarla | **Opcional, desde la app**, como «precalentar»: lee hasta llenar el tope (no más), cancelable |
| D8 | Elegir el modo | solo automático · forzable | **Forzable** (`banco_modo`: auto, general, unidad) en la petición y la configuración: hace falta para medir y le da control al usuario |
| D9 | Lo que ya hay en disco | dejarlo · podar al tope · borrar todo | **Podar al tope** al arrancar; los 3,9 GB del estudio y sus copias (253 MB) se borran **con confirmación** |
| D10 | Varios bancos con estados compartidos | — | se mantiene el arreglo de `reasignar` (no borra lo que usa otro banco); el tope es uno solo para todos |

## 4. Fases

### Fase A — Caché acotado (código, sin modelo) · ~3 h · **hecha el 09/10 (T1, T2)**

- A1. `moe_cache_gb` y `moe_cache_reserva_gb` en la configuración; `podar_proyectos` usa el tope configurado y la reserva
  (si el disco libre baja de la reserva, poda más); poda también al arrancar el motor. Con tope 0, el motor lee el prefijo
  y **no** hace `slot save` (no escribe nada).
- A2. `/api/recursos/moe`: devolver tope, ocupado, libre en disco y archivos; `POST` para cambiar el tope. En el panel del
  motor (`temperaturas.js`), el tope junto al botón «borrar proyectos».
- A3. Tests: el tope se respeta, 0 no escribe, poda por último uso (restaurar cuenta como uso), la reserva de disco manda.

### Fase B — El chat no depende de los estados (código) · ~2–3 h · **hecha el 09/10 (T3, T4, T5)**

- B1. Modo general con `hechos_de_la_pregunta` (paridad con el de unidad).
- B2. `banco_modo` (auto | general | unidad) en `AIChatRequest` y en la configuración; auto = como hoy (unidad solo si
  está vigente). El evento `banco` informa el modo usado y por qué (sin estado, forzado, repartida entre unidades).
- B3. Leer al vuelo: con modo «unidad» forzado y la unidad sin estado, se lee (25–35 s) y se guarda si cabe en el tope.
- B4. Tests de cada caso.

### Fase C — Precalentar desde la app (opcional) · ~2 h

- C1. Endpoint y botón «Leer unidades» en el panel del banco: en segundo plano, con progreso y cancelación, hasta llenar
  el tope.
- C2. El resumen por unidad que nadie usa: o se agrega al mapa, o se deja de generar (decidir con la fase D).

### Fase D — Medir (con el modelo; máquina libre) · ~3 h · **hecha el 09/10 en versión corta (T7)**

**Resultado** (detalle en `docs/estudio-banco.md`, «Texto primero: medición corta»): 52 respuestas, ninguna vacía ni
agotada. En las 11 preguntas de falla, el general queda en 6,0 correctas esperadas frente a 7,5 del de unidad (dos
muestras) → **D4: el modo queda `auto` y el tope en 32 GB; las fichas no hacen falta**. La diferencia está en dónde van
los hechos: pegados a la pregunta, el general acertó 3 de 3. Quedan 5 propuestas (P.camino en los hechos, hechos al final
en el general, hechos de configuración, ruido de los llamadores por texto, la última ronda sin cambiar el prefijo) y una
re-medición corta que podría pasar el modo a `general` y el tope a 5 GB. D3 (tope chico real) no se hizo.

**10/10: las 5 propuestas, implementadas y re-medidas** (`docs/estudio-banco.md`, «Las propuestas de T7, implementadas y
re-medidas»): a84a, d408 y el error B6 de E8 quedan arreglados; 0b5f sigue fallando. Los dos modos quedan parejos en
exactitud (9,5 y 9,5): unidad responde ~16 s más rápido; general no necesita los 28 GB de estados. La regla de D4 da
`general` con 5 GB, pero eso borra ~23 GB de lecturas y cuesta ~16 s por pregunta. **Decidido: `auto` con 32 GB**
(sin perder exactitud ni velocidad; sin lectura guardada, la pregunta va al general). Medido el modo por defecto: 10 de 11
preguntas de falla y 3 de 4 errores de E8.

- D1. **Mismas preguntas en los dos modos**: 60 del examen de Prig (las 23 que fallaron en E7 más una muestra estratificada)
  con `banco_modo=general` y con `banco_modo=unidad`, con los cambios de hoy. Arnés: `lote.py`/`sonda.py` con el sistema
  congelado. ~40 min por modo + auditoría.
- D2. **E8 en los dos modos**: la copia con 8 errores inyectados ya está preparada (`e8.py`); 23 preguntas × 2.
  ~1 h + auditoría.
- D3. **Tope chico real**: tope de 2 GB sobre Prig; verificar que el disco no lo supera, que las preguntas sobre unidades
  desalojadas van al modo general sin errores y cuánto cambia la latencia.
- D4. Decidir con los datos: el tope por defecto (0, 5 o 10 GB), si el modo automático sigue prefiriendo la unidad, y si
  hacen falta las fichas (D6).

### Fase E — Un proyecto grande de verdad · ~½ día (casi todo modelo sin atender)

- E1. Elegir un repositorio de 2–5 M tokens (en el lenguaje de los proyectos reales del usuario).
- E2. Banco sin pasada: tiempo de sincronización y tamaño. Preguntas en modo general: exactitud y latencia.
- E3. Opcional: precalentar 20 unidades y comparar.

### Fase F — Limpieza y documentación · ~1 h

- F1. Con confirmación: borrar `~/.cache/prig-estudio` (253 MB) y los 16 estados que solo usa el estudio (3,9 GB), más
  los 5 que dejó T7 sobre la copia E8 (1,3 GB, creados el 09/10 entre las 23:03 y las 23:13).
  **Hecho el 10/10** para los estados: 21 borrados (5,24 GB); `~/.cache/prig-estudio` se conserva (copias y bancos del
  estudio, para poder volver a medir).
- F2. Actualizar `docs/banco-proyecto.md`, `docs/motor-moe.md`, `docs/plan-lectura-unica.md` y `docs/estudio-banco.md`.

**Total**: código (A+B, más C opcional) ~5–8 h; medición (D) ~3 h con la máquina libre; proyecto grande (E) ~½ día; F ~1 h.
Unos **2 días**, de los que ~1 día es modelo corriendo solo.

## 5. Riesgos y cómo se controlan

| Riesgo | Control |
|---|---|
| El modo general es ~10 s más lento por respuesta (medido: mediana 27 s frente a 16 s) | La caché de RAM del servidor ayuda en las preguntas seguidas; el caché de disco (con tope) sigue acelerando las unidades más usadas |
| El general no encuentra errores que la lectura completa sí | Lo mide D2; si pasa: leer al vuelo para el análisis a fondo y fichas (D6) |
| Los hechos con nombres comunes meten ruido | Van marcados («sin resolver», «homónimas»); D1 lo mide |
| Un tope chico desaloja demasiado | Solo cuesta latencia; D3 da el número para elegir el valor por defecto |
| El disco se llena por otras cosas | Reserva de disco libre que el caché nunca toca |
| El backend cambia mientras se mide | Medir con el sistema congelado (`docs/estudio-banco/congelar_sistema.py`) |

## 6. Qué se puede omitir

- **Fase C** si el caché queda chico o apagado.
- **Fase E** si los proyectos reales no pasan de ~1,5 M tokens (Prig ya es de ese tamaño).
- **Fichas y resúmenes por unidad**, salvo que D2 los justifique.
- **Comprimir o cuantizar estados** (estrategias 1–7 del análisis): con un tope configurable dejan de ser necesarias.

## 7. Orden y puntos de decisión

A → B → **D** (decide el tope por defecto, el modo automático y si hacen falta fichas) → C si conviene → E → F.
