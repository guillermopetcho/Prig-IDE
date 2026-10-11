# T8 — Limpieza y documentación

Leer antes el [README](README.md). Después de T7.

## 1. Fijar los valores por defecto decididos en T7

En `backend/ai_engine/ai_engine_class.py` (configuración por defecto): `moe_cache_gb` y `banco_modo` con los valores que
eligió T7, con un comentario que cite la medición (`docs/estudio-banco.md`, sección «Texto primero: medición»).
Actualizar los tests que comparan esos valores. La configuración guardada del usuario no se toca: si ya tiene un valor,
manda el suyo.

## 2. Limpieza (pedir confirmación al usuario antes de borrar nada)

| Qué | Dónde | Tamaño (09/10/2026) |
|---|---|---|
| Copias, bancos y examen del estudio | `~/.cache/prig-estudio/` (repos, repos-e8, repos-e9, bancos, sistema, e7, e8, e9, respaldo) | ~253 MB |
| Estados que solo usan los bancos del estudio | `~/.cache/prig-moe/proyectos/*.bin`, los que **no** figuran en la tabla `lecturas` de ningún banco de `~/.prig_bancos/` | ~3,9 GB (16 archivos) |

Para listar los estados que solo usa el estudio, cruzar los archivos `*.bin` con
`SELECT archivo FROM lecturas` de cada `~/.prig_bancos/*/banco.db` (solo lectura). **Antes** de borrar
`~/.cache/prig-estudio`, copiar lo que falte a `docs/estudio-banco/resultados/`: informes, auditorías, `plan_*.json`,
`verdad_tests.json` y respuestas.

## 3. Documentación

- `docs/banco-proyecto.md`: el banco es la memoria; los estados del motor son un caché con tope; el modo del banco (auto,
  general, unidad) y el motivo que informa el chat; los hechos del banco en los dos modos; `P.llamadores` con los
  llamadores «por texto».
- `docs/motor-moe.md`: el tope del caché y la reserva de disco (`moe_cache_gb`, `moe_cache_reserva_gb`); con 0 no se
  guarda nada; el panel del motor.
- `docs/plan-lectura-unica.md`: nota al principio que remite a `docs/plan-texto-primero.md` (la lectura por unidades pasa
  a ser un acelerador opcional).
- `docs/plan-texto-primero.md`: marcar las fases hechas y enlazar el informe de T7.

## Aceptación

- Los valores por defecto coinciden con lo decidido; la batería completa está en verde.
- Nada se borró sin confirmación; los resultados del estudio quedaron en `docs/estudio-banco/resultados/`.
