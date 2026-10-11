# T2 — El tope del caché, visible y editable (API y panel del motor)

Leer antes el [README](README.md). Depende de **T1** (claves `moe_cache_gb`, `moe_cache_reserva_gb` y `Motor.podar()`).

## Objetivo

El usuario ve cuánto ocupa el caché de estados, cuál es el tope y cuánto disco queda libre, y puede cambiar el tope (0 =
no guardar) desde el panel del motor MoE, junto al botón «Borrar» que ya existe.

## Archivos

- `backend/app.py`: modelo `MoeRequest`, endpoint `recursos_moe_ajustar` (`POST /api/recursos/moe`) y `_moe_estado()`.
- `frontend/js/temperaturas.js`: función `pintarMoe()`.
- `backend/tests/test_motor_moe.py`: la clase con `test_estado_y_ajustes`, que importa `app`.

## Cómo está hoy

- `app.py`: `class MoeRequest(BaseModel)` tiene `contexto`, `hilos`, `calientes`, `modo`, `mtp`, `nucleo`, `detener`,
  `olvidar_proyectos`. `recursos_moe_ajustar(req)` valida cada campo, junta los cambios en `cambios`, llama
  `ai_engine.update_config(cambios)`, atiende `detener` y `olvidar_proyectos`, y devuelve `_moe_estado()`.
- `_moe_estado()` devuelve `{**ai_engine.motor_moe().estado(), "ajustes": {contexto, hilos, calientes, modo, mtp,
  nucleo}, "modos": [...]}`. Desde T1, `estado()["proyectos"]` trae `archivos`, `mb`, `tope_mb`, `reserva_mb` y
  `libre_mb`.
- `temperaturas.js`, `pintarMoe()`:
  - arma el formulario con ids `moe-modo`, `moe-nucleo`, `moe-mtp`, `moe-ctx`, `moe-calientes`, `moe-hilos` y el botón
    `moe-guardar`;
  - muestra la línea «Proyectos guardados: N (X GB)» y el botón `moe-olvidar`;
  - recuerda lo que el usuario está tocando con `dataset.tocado`: hay tres listas de ids, al principio de la función,
    en `enviar` y en el bucle que marca `tocado`;
  - `moe-guardar` envía `{contexto, calientes, hilos, modo, mtp, nucleo}` con `enviar(cuerpo)` (`POST
    /api/recursos/moe`).

## Cambios

1. **`MoeRequest`**: `cache_gb: Optional[float] = None` (tope en GB; 0 = no guardar) y
   `cache_reserva_gb: Optional[float] = None`.
2. **`recursos_moe_ajustar`**:
   - `cache_gb`: entre 0 y 2000 → `cambios["moe_cache_gb"]`; fuera de rango, `HTTPException(400, "cache_gb: entre 0 y
     2000 GB")`;
   - `cache_reserva_gb`: entre 0 y 1000 → `cambios["moe_cache_reserva_gb"]`; fuera de rango, 400;
   - después de `update_config`, si cambió alguno de los dos, llamar `ai_engine.motor_moe().podar()`, dentro de
     `try/except Exception`: el tope nuevo se aplica enseguida.
3. **`_moe_estado()`**: agregar a `"ajustes"` `"cache_gb": cfg.get("moe_cache_gb")` y
   `"cache_reserva_gb": cfg.get("moe_cache_reserva_gb")`.
4. **`temperaturas.js`, `pintarMoe()`**:
   - Junto a «Proyectos guardados», un campo `moe-cache` (`type="number" min="0" step="1"`, ancho ~48px, mismo estilo que
     `moe-hilos`) con la etiqueta «Caché de lecturas (GB)» y el `title` «Lecturas del motor guardadas en disco: responden
     en 0,1–0,4 s sin releer. 0 = no guardar (cada pregunta arma su contexto desde el banco)». Valor:
     `valor('moe-cache', a.cache_gb ?? 32)`.
   - La línea pasa a decir «Proyectos guardados: N (X GB de Y GB · Z GB libres)», con `m.proyectos.tope_mb` y
     `m.proyectos.libre_mb` (si faltan, la línea queda como hoy).
   - Agregar `'moe-cache'` a las tres listas de ids de `dataset.tocado`.
   - `moe-guardar` envía además `cache_gb: parseFloat($('moe-cache').value)` (si es `NaN`, no enviarlo).
5. No tocar el resto del panel.

## Tests (`backend/tests/test_motor_moe.py`)

1. **Actualizar `test_estado_y_ajustes`**: hoy compara `e["ajustes"]` con un diccionario **exacto**. Agregar
   `"cache_gb"` y `"cache_reserva_gb"` con los valores de la configuración de esa prueba (32 y 20 si es la de fábrica).
2. `test_ajustar_el_tope_del_cache`: `recursos_moe_ajustar(MoeRequest(cache_gb=5))` → la configuración queda en 5 y se
   llama `podar()`. Parchear `ai_engine.motor_moe` o `Motor.podar` con un `mock` y comprobar la llamada.
   `MoeRequest(cache_gb=-1)` y `MoeRequest(cache_gb=5000)` → `HTTPException`. `MoeRequest(cache_reserva_gb=30)` → 30.
3. La interfaz no tiene tests automáticos: describir en la entrega cómo se probó a mano (abrir el panel de temperaturas,
   cambiar el valor, guardar y ver la línea actualizada).

## Aceptación

- Los tests nuevos y el actualizado pasan; los nuevos fallan sin el cambio.
- La batería completa está en verde.
- En la app: el panel muestra el uso, el tope y el disco libre. **No probar topes chicos antes de T7**: borran lecturas
  guardadas que la medición necesita (se prueba en T7).
