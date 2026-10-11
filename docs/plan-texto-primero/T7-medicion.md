# T7 — Medición corta: pocas preguntas, cada una analizada a fondo

> **Hecha el 09/10/2026.** Resultado, decisión y propuestas: `docs/estudio-banco.md`, «Texto primero: medición corta»;
> datos y auditoría: `docs/estudio-banco/resultados/texto-primero/`. Como la primera serie quedó dudosa, se agregó la
> segunda tanda que prevé la regla: las preguntas en que los modos difirieron, otra muestra de cada modo y el general con
> los hechos al final (`sonda.py`: cada pregunta puede traer su `modo` y `hechos_al_final`).

Leer antes el [README](README.md). Se hace después de T1–T5 (hechas el 09/10/2026), con la **máquina libre**: sin
kdenlive, OBS ni navegador pesado, y un solo proceso del modelo a la vez.

En vez de repetir el examen entero (~170 respuestas), cada pregunta prueba **un modo de falla concreto** que el estudio
encontró (docs/estudio-banco.md, «Modos de falla de las 23 no correctas»). Cada respuesta se analiza a fondo: el texto
completo, las consultas que hizo, el modo y su motivo, y los hechos que recibió, contra el código.

## Las preguntas (ya preparadas en `~/.cache/prig-estudio/t7/`)

**Prig** (`preguntas_prig.json`, 12, sobre la copia limpia `~/.cache/prig-estudio/repos/Prig`):

| id | Qué prueba | E7 |
|---|---|---|
| ind_15 | llamadores por una instancia global (`book_service.delete_item`) | falló 3 de 3 |
| ind_16 | llamadores por una fábrica (`recursos_gestor().radiografia`) | parcial |
| f46b5c0819d3 | impacto con función pasada como argumento y lambda (`progreso.historial`) | correcta, clave incompleta |
| a84a7fe1bad7 | config cuya lectora real no está en el grafo (`truncar` → `_ajustes`) | parcial |
| 29b468d8a2cb | impacto: nombró la función y no la ruta HTTP (`rebind_workspace`) | parcial |
| 12bb842411c5 | impacto: ruta HTTP inventada (`cleanup_all_processes`) | incorrecta |
| 0b5f93c17f28 | recorrido: negó un camino que existe | incorrecta (el corrector le dio 1,0) |
| d408dee5873f | recorrido: negó un camino que existe (2) | incorrecta |
| ind_27 | diseño: bucle de 28 consultas sin responder | agotada |
| 1f14bd2a14dd | entorno: bucle de texto, respuesta vacía | agotada |
| 02bd1db0d170 | llamadores: salida degenerada («...») | incorrecta |
| 8caebf27e7ba | control: constante | correcta |

**E8** (`preguntas_e8.json`, 5, sobre la copia con errores inyectados `~/.cache/prig-estudio/repos-e8/Prig`): los 4
errores que **ningún test de Prig detecta** (B2 línea perdida al partir, B3 `startswith` en la validación de rutas, B6
clave de configuración mal escrita, B7 conexión que nunca se cierra) y un control sin error (C2). La pregunta es la
misma para todas: «¿tiene algún error?».

## Cómo se corre (~35 min de modelo)

```
cd /home/ama-gi/Prig
nvidia-smi --query-gpu=memory.used,temperature.gpu --format=csv,noheader   # < 600 MiB y ≤ 70 °C
pgrep -x llama-server || echo libre
.venv/bin/python docs/estudio-banco/congelar_sistema.py                    # congela el backend con T1–T5
export PRIG_SISTEMA=~/.cache/prig-estudio/sistema/<huella que imprime>
T=~/.cache/prig-estudio/t7
.venv/bin/python docs/estudio-banco/sonda.py ~/.cache/prig-estudio/repos/Prig    $T/preguntas_prig.json $T/prig_general.json --modo general
.venv/bin/python docs/estudio-banco/sonda.py ~/.cache/prig-estudio/repos/Prig    $T/preguntas_prig.json $T/prig_unidad.json  --modo unidad
.venv/bin/python docs/estudio-banco/sonda.py ~/.cache/prig-estudio/repos-e8/Prig $T/preguntas_e8.json   $T/e8_general.json   --modo general
.venv/bin/python docs/estudio-banco/sonda.py ~/.cache/prig-estudio/repos-e8/Prig $T/preguntas_e8.json   $T/e8_unidad.json    --modo unidad
```

- `sonda.py` fija el tope del caché en 60 GB **solo en memoria**: no poda lecturas guardadas.
- En modo unidad, las unidades de la copia E8 que cambiaron se leen al vuelo la primera vez (T5): eso también lo prueba.
- Cada respuesta tiene un tope de 600 s.

## Análisis de cada respuesta

Para cada pregunta, en los dos modos:

1. **Veredicto contra el código** (no contra una clave): correcta, parcial o incorrecta, con el porqué.
2. **Mecanismo**: ¿llegaron los hechos (`hechos_caracteres`)? ¿Traían lo que faltaba en E7 (el llamador por texto, la
   ruta exacta, la línea de `_ajustes`)? ¿El modelo lo usó? ¿Cuántas consultas hizo? ¿Cortó una repetida o forzó la
   respuesta la última ronda? ¿Se agotó?
3. **Comparado con E7**: ¿se arregló el modo de falla, sigue igual o apareció otro?

Salida: `~/.cache/prig-estudio/t7/analisis.json` (una entrada por pregunta y modo) y una sección «Texto primero:
medición corta» en `docs/estudio-banco.md`.

## Qué decide (reglas fijadas antes de medir)

- **Modo por defecto `general`** si en las 11 preguntas de falla el general queda correcto en al menos tantas como el de
  unidad, si el control sigue correcto y si en E8 encuentra al menos tantos errores como el de unidad menos uno. Si no,
  queda en `auto`.
- **Tope del caché**: con `general`, 5 GB (solo acelera prefijos y lo que se lea a pedido); con `auto`, lo que entre el
  proyecto principal (Prig: ~30 GB) o 10 GB por último uso.
- **Fichas por símbolo**: solo si el general deja de encontrar en E8 un error que el de unidad sí encuentra.
- Con tan pocas preguntas, esto **no mide un porcentaje**: muestra si cada mecanismo funciona. Si el resultado queda
  parejo o es dudoso, se agrega una segunda tanda solo de esa clase de pregunta.

## Al final: el tope elegido (~10 min)

Fijar el tope decidido en el panel del motor y comprobar que `~/.cache/prig-moe/proyectos` queda por debajo, y que una
pregunta sobre una unidad desalojada responde en modo general, con su motivo en el aviso. **Esto borra lecturas
guardadas.**
