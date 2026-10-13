# T5 — Modo «unidad» con la unidad sin estado: leerla antes de responder

Leer antes el [README](README.md). Depende de **T4** (`_unidad_para` devuelve la unidad con `"leer_antes": True`). Usa la
clave de **T1** `moe_cache_gb`: si T1 todavía no está, vale `None`, que se trata como «hay caché».

## Objetivo

Cuando el modo es «unidad» (forzado por el usuario o la petición) y la unidad elegida no tiene lectura guardada:

- **con caché** (`moe_cache_gb` distinto de 0): leer la unidad **antes** de responder con `LectorUnidades.leer(orden)`.
  Eso la lee, el motor guarda su estado si cabe, y se registra la lectura (llave, archivo, resumen), así que las
  preguntas siguientes la restauran en ~0,3 s. Avisar al usuario mientras tanto (~30–40 s);
- **con el caché apagado** (`moe_cache_gb == 0`): no llamar a `leer()`, que leería el prefijo dos veces sin poder
  guardarlo. Se responde en modo unidad y el motor lee el prefijo en la misma petición. Avisar que tarda más.

## Archivos

- `backend/app.py`, generador `_chat_eventos(req, prompt, sys_prompt, modelo=None, contexto_fijo="", banco=None,
  banco_info=None, unidad=None, referencias=None)`.
- `backend/tests/test_banco_proyecto.py`, clase `TestChat`.

## Cómo está hoy

- `_chat_eventos` emite primero el evento `banco` (`yield json.dumps({"t": "banco", "v": banco_info}...)`) y las
  referencias. Después arma los mensajes. En modo unidad:
  `mensajes = unidad["lector"].mensajes(unidad["datos"]) + [{"role": "user", "content":
  unidad["lector"].pregunta_con_contexto(unidad["datos"], req.prompt, hechos=True)}]`. Luego corre el bucle con
  `ai_engine.chat_eventos(...)`.
- `LectorUnidades.leer(orden)` (`lectura_unidades.py`): lee la unidad con una pregunta de resumen (`PEDIDO_RESUMEN`,
  sin herramientas, 2 rondas). El motor guarda el estado y se inserta el registro en la tabla `lecturas`. Devuelve
  `{"orden", "archivo", "llave", "tokens", "segundos", "origen", "bytes", "expertos", "resumen", ...}`. Si la misma unidad
  ya se leyó con otro número, la reusa sin llamar al modelo (`origen: "reusada"`).
- Los avisos al usuario son eventos `{"t": "aviso", "v": "..."}`, que el chat ya muestra.

## Cambios

En `_chat_eventos`, **después** de emitir el evento `banco` y **antes** del bucle de `chat_eventos`:

```python
if unidad is not None and unidad.get("leer_antes"):
    try:
        tope = ai_engine.config.get("moe_cache_gb")
        tope = None if tope in (None, "") else float(tope)
    except (TypeError, ValueError):
        tope = None
    nombre = unidad.get("nombre") or f"unidad {unidad.get('orden')}"
    if tope == 0:
        yield aviso(f"«{nombre}» no tiene lectura guardada y el caché está apagado: se lee junto con la pregunta "
                    "(≈30 s más).")
    else:
        yield aviso(f"Leyendo «{nombre}» antes de responder (≈30–40 s; queda guardada para las próximas preguntas)…")
        try:
            r = unidad["lector"].leer(unidad["orden"])
            yield aviso(f"Unidad leída: {r.get('tokens') or 0:,} tokens en {r.get('segundos') or 0} s.".replace(",", "."))
        except Exception as e:
            yield aviso(f"No se pudo leer antes ({type(e).__name__}): se lee junto con la pregunta.")
```

Donde `aviso(texto)` es `json.dumps({"t": "aviso", "v": texto}, ensure_ascii=False) + "\n"`: el mismo formato que los
demás eventos de `_chat_eventos`. Si ya hay un ayudante para eso, usarlo.

Notas:

- No cambiar los mensajes: el prefijo de la unidad es el mismo, la lectura solo deja el estado guardado para que el motor
  lo restaure.
- La cancelación («Detener») ya corta `leer()`: corre dentro del mismo hilo con su evento de cancelación. No hace falta
  más.
- No tocar `lectura_unidades.py` (regla 1 del README).

## Tests (`backend/tests/test_banco_proyecto.py`, `TestChat`)

Partir de `test_modo_unidad`: tiene un `LectorFalso` y parchea `_unidad_para`. Desde T4 devuelve `(unidad, motivo)`.

1. `test_unidad_sin_lectura_se_lee_antes`: el `LectorFalso` tiene `leer(self, orden)`, que anota la llamada y devuelve
   `{"tokens": 1234, "segundos": 30.0}`; la unidad trae `"leer_antes": True`; con
   `mock.patch.dict(self.app.ai_engine.config, {"moe_cache_gb": 10})` → `leer` se llama una vez, **antes** de la
   respuesta: en el orden de los eventos, los avisos «Leyendo…» y «Unidad leída…» van antes del primer `texto`.
2. `test_caché_apagado_no_lee_antes`: igual con `{"moe_cache_gb": 0}` → `leer` no se llama, y hay un aviso con «el caché
   está apagado».
3. `test_si_leer_falla_responde_igual`: `leer` lanza `RuntimeError` → hay un aviso «No se pudo leer antes» y la
   respuesta sigue: el `chat_eventos` falso se llama igual.

## Aceptación

- Los tests nuevos fallan sin el cambio; la batería completa está en verde.
- En la app, con el modo «Unidad» y una unidad sin leer: aparece el aviso, la primera respuesta tarda ~30–40 s más, y la
  segunda pregunta sobre esa unidad la restaura (el aviso del banco dice «lectura guardada de la unidad»).
