# T4 — Modo del banco forzable (auto / general / unidad), con el motivo informado

Leer antes el [README](README.md). Sin dependencias; conviene hacerla después de T3 (mismo bloque de `ai_chat`).

## Objetivo

Que el modo de responder con el banco se pueda elegir, por pregunta y en la configuración:

- **auto** (por defecto): como hoy. Modo unidad solo si la unidad elegida tiene su lectura guardada; si no, modo general.
- **general**: siempre modo general (contexto desde el texto del banco; no usa estados).
- **unidad**: modo unidad aunque la unidad no tenga lectura guardada. La lectura la hace T5; sin T5, se responde en modo
  unidad y el motor lee el prefijo en la misma petición.

Y que el chat diga **por qué** respondió en el modo que respondió. Hace falta para medir (T7) y para que el usuario lo
controle.

## Archivos

- `backend/app.py`: `AIChatRequest`, `_unidad_para`, `ai_chat` (donde se llama a `_unidad_para`), `BancoAjustesRequest`,
  `banco_ajustes` (`POST /api/banco/ajustes`), `banco_estado` (`GET /api/banco`).
- `backend/ai_engine/ai_engine_class.py`: configuración por defecto.
- `frontend/js/banco_proyecto.js`: ajustes del banco (donde están `banco-presupuesto` y `banco-mapa`).
- `frontend/js/ai_chat.js`: donde se pinta el evento `banco` (`ev.t === 'banco'`).
- `backend/tests/test_banco_proyecto.py`, clase `TestChat`.

## Cómo está hoy

```python
def _unidad_para(req, modelo, banco) -> Optional[Dict[str, Any]]:
    if (banco is None or not req.eventos or not motor_moe_mod.es_moe(modelo) or req.solo_codigo
            or req.hooked_files or req.code_context or req.continuar or req.think):
        return None
    try:
        lector = lectura_unidades.LectorUnidades(banco, ai_engine, modelo=modelo, generar_sub=_generador_subllamadas(modelo))
        if not lector._unidades:
            return None
        eleccion = lector.elegir_unidad(req.prompt)
        if eleccion.get("orden") is None or not eleccion.get("vigente"):
            return None
        return {**eleccion, "lector": lector, "datos": lector._unidades[eleccion["orden"]]}
    except Exception:
        return None
```

`ai_chat` hace `unidad = _unidad_para(req, modelo, banco)` y, si hay unidad, `banco_info.update({"modo": "unidad",
"unidad": ..., "unidad_orden": ..., "unidad_cuota": ...})`. `elegir_unidad` devuelve `orden` en `None` y un `motivo`
cuando la pregunta reparte su peso entre varias unidades.

## Cambios

1. **Configuración por defecto** (`ai_engine_class.py`, junto a `"banco_presupuesto"`):
   `"banco_modo": "auto",   # auto | general | unidad (docs/plan-texto-primero.md)`.
2. **`AIChatRequest`**: `banco_modo: Optional[str] = None` (`None` → el de la configuración).
3. **`_unidad_para`** pasa a devolver **`(unidad o None, motivo: str)`**:
   - `modo = (req.banco_modo or ai_engine.config.get("banco_modo") or "auto").lower()`; si no es `auto`, `general` ni
     `unidad`, usar `auto`;
   - `general` → `(None, "forzado: modo general")`;
   - si falla alguna de las condiciones de hoy → `(None, "modo unidad no disponible: <razón>")`. La razón es la primera
     que falle: «no es el motor MoE», «sin eventos», «archivos enganchados», «código del editor», «continuación» o «con
     razonamiento»;
   - sin unidades → `(None, "el proyecto todavía no está partido en unidades")`;
   - `orden` en `None` → `(None, f"la pregunta reparte su peso entre unidades: {eleccion.get('motivo')}")`;
   - unidad elegida **sin** lectura vigente:
     - en `unidad` → `({...igual que hoy..., "leer_antes": True}, f"forzado: «{nombre}» no tiene lectura guardada; se lee ahora")`;
     - en `auto` → `(None, f"«{nombre}» no tiene lectura guardada: modo general")`;
   - unidad vigente → `({...}, "lectura guardada de la unidad")`;
   - excepción → `(None, f"no se pudo elegir unidad: {type(e).__name__}")`.
4. **`ai_chat`**: `unidad, motivo = _unidad_para(req, modelo, banco)`. Si `banco_info` no es `None`:
   `banco_info["modo"] = "unidad" if unidad is not None else "general"` y `banco_info["motivo"] = motivo`, además de lo
   que ya agrega en modo unidad.
5. **`BancoAjustesRequest`**: `modo: Optional[str] = None`. En `banco_ajustes`: si viene, debe ser `auto`, `general` o
   `unidad` (si no, `HTTPException(400)`) → `cambios["banco_modo"]`. La respuesta incluye `"modo"`.
6. **`banco_estado`** (`GET /api/banco`): agregar `"modo": ai_engine.config.get("banco_modo") or "auto"`.
7. **`banco_proyecto.js`**: junto a los campos de presupuesto y mapa, un `<select id="banco-modo">` con:
   - `auto` → «Automático (lectura guardada si la hay)»;
   - `general` → «General (siempre desde el banco)»;
   - `unidad` → «Unidad (leerla si hace falta)».

   Valor inicial `estado.modo`. Al guardar los ajustes (el `post('/api/banco/ajustes', {...})` que ya existe), enviar
   también `modo: $('banco-modo').value`.
8. **`ai_chat.js`**, donde se pinta `ev.t === 'banco'`: agregar `b.motivo` al `title` en las dos ramas (unidad y general).
   En la rama general, si `b.hechos_caracteres` (T3) es mayor que 0, sumar a `partes` «hechos del banco». No cambiar el
   resto del texto.

## Tests (`backend/tests/test_banco_proyecto.py`, `TestChat`)

1. **Actualizar `test_modo_unidad`**: hoy parchea `_unidad_para` con `lambda *a: unidad`; pasa a
   `lambda *a: (unidad, "lectura guardada de la unidad")`. Comprobar que el evento `banco` trae
   `motivo == "lectura guardada de la unidad"`.
2. `test_modo_general_forzado`: `AIChatRequest(..., banco=True, banco_modo="general")` con el modelo MoE y un `mock` de
   `lectura_unidades.LectorUnidades` cuya `elegir_unidad` devolvería una unidad vigente → la respuesta va en modo general
   (los mensajes no empiezan con el prefijo de la unidad) y `motivo == "forzado: modo general"`.
3. `test_unidad_sin_lectura_en_auto_va_a_general` y `test_unidad_sin_lectura_forzada`: con `elegir_unidad` devolviendo
   `vigente: False` → en `auto`, `(None, "...no tiene lectura guardada: modo general")`; en `unidad`, una unidad con
   `leer_antes: True`. Se pueden probar llamando a `app._unidad_para(...)` directamente, con `LectorUnidades` parcheado.
4. `test_ajustes_del_modo`: `banco_ajustes(BancoAjustesRequest(modo="general"))` → la configuración queda en `general`
   (parchear `ai_engine._save_config`); `modo="otro"` → `HTTPException`.

## Aceptación

- Los tests nuevos fallan sin el cambio; los existentes, con la actualización de `test_modo_unidad`, pasan; la batería
  completa está en verde.
- En la app: con «General», toda pregunta con el banco responde en modo general, y el título del aviso del banco lo
  dice. Con «Automático», todo queda como hoy.
