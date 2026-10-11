# T6 (opcional) — Precalentar lecturas desde la app, hasta llenar el tope

Leer antes el [README](README.md). Depende de **T1** (tope del caché y `motor_moe.estimar_estado_mb`) y de **T4**.
Se puede omitir si el caché queda chico o apagado.

## Objetivo

Hoy la lectura por unidades (la «pasada») solo se lanza por línea de comandos (`python lectura_unidades.py --pasada`).
Esta tarea agrega un botón en el panel del banco, «Precalentar lecturas», que lee en segundo plano las unidades sin
lectura guardada. Se detiene sola al llenar el tope del caché. Cede el paso al chat. Se puede cancelar y muestra su
avance.

## Archivos

- `backend/app.py`: endpoints nuevos, junto a los del banco (`/api/banco/...`).
- `frontend/js/banco_proyecto.js`: panel del banco.
- Tests: `backend/tests/test_banco_proyecto.py` (o un archivo nuevo `tests/test_precalentar.py`).

## Piezas que ya existen (reusar)

- `_guardia_analista()` en `app.py`: devuelve el motivo para esperar («el chat está respondiendo», poca RAM, GPU
  caliente…) o `None`.
- El patrón de trabajo en segundo plano con cancelación de `Bancos.analizar_en_fondo` (`banco_proyecto.py`): un
  diccionario de estado, un `threading.Event` para cancelar y un hilo `daemon`.
- `lectura_unidades.LectorUnidades(banco, ai_engine, modelo=motor_moe.NOMBRE,
  generar_sub=_generador_subllamadas(motor_moe.NOMBRE))`, con `reasignar()`, `vigente(orden)`, `leer(orden)` y
  `_unidades` (`orden → {"tokens", "nombre", ...}`).
- `particion_proyecto.particionar(banco)`: siempre antes de leer, como hace `lectura_unidades.main()`.
- `motor_moe.proyectos_guardados()["mb"]`, `Motor.tope_cache_mb()` (T1) y `motor_moe.estimar_estado_mb(tokens)` (T1).

## Cambios

1. Estado global en `app.py`: `_precalentar = {"activo": False}` y `_cancelar_precalentar = threading.Event()`.
2. **`POST /api/banco/lectura/precalentar`** (`{"maximo": Optional[int]}`): si ya está activo, devolver el estado. Si no,
   lanzar un hilo que:
   1. `banco = _banco_actual(crear=False)`; `banco.sincronizar()`; `particion_proyecto.particionar(banco)`;
   2. crea el `LectorUnidades` y llama `reasignar()`;
   3. recorre `sorted(lector._unidades)` saltando las vigentes. Para cada unidad:
      - si se canceló, termina;
      - mientras `_guardia_analista()` devuelva un motivo, espera (`_cancelar_precalentar.wait(5)`) y lo anota en
        `"esperando"`;
      - **espacio**: si `proyectos_guardados()["mb"] + estimar_estado_mb(tokens de la unidad + 6000) > tope_mb`, termina
        con `"fin": "caché lleno"`. Los 6000 son la tarjeta global que va en cada prefijo;
      - `leer(orden)`, y actualiza `leidas`, `ultima` (nombre, tokens y segundos) y `vigentes`;
      - con `maximo`, se detiene al leer esa cantidad;
   4. al terminar: `"activo": False` y `"fin"` («todas vigentes», «caché lleno», «cancelado», «máximo alcanzado» o
      «error: …»).
3. **`GET /api/banco/lectura`** → `{"activo", "total", "vigentes", "leidas", "ultima", "esperando", "fin", "cache_mb",
   "tope_mb"}`. `total` y `vigentes` se calculan con un `LectorUnidades` del banco actual aunque no haya nada activo.
4. **`POST /api/banco/lectura/cancelar`** → activa el evento.
5. **`banco_proyecto.js`**: en el panel del banco, una línea «Lecturas guardadas: V de T unidades (X GB de Y GB)», un
   botón «Precalentar lecturas» (y «Cancelar» mientras corre) y el avance (`ultima`, `esperando`, `fin`). Consultar
   `GET /api/banco/lectura` cada 3 s mientras esté activo.

## Tests

Con `LectorUnidades` reemplazado por uno falso (unidades con `tokens`, `vigente` y `leer` que anota la llamada) y la
guardia parcheada:

1. Lee solo las no vigentes y termina con «todas vigentes».
2. Se detiene con «caché lleno» cuando `proyectos_guardados` más la estimación pasan el tope (parchear las dos
   funciones).
3. Cancelar detiene antes de la próxima unidad.
4. Con la guardia ocupada espera y anota `"esperando"`; al liberarse, sigue.
5. Dos `POST` seguidos no lanzan dos hilos.

## Aceptación

- Los tests nuevos fallan sin el cambio; la batería completa está en verde.
- En la app: el botón lee unidades una tras otra (~30–40 s cada una), se pausa mientras el chat responde y se detiene al
  llegar al tope.
