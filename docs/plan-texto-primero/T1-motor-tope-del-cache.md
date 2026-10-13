# T1 — Tope configurable del caché de estados en el motor

Leer antes el [README](README.md) de esta carpeta (reglas comunes).

## Objetivo

El caché de estados del motor MoE respeta un **tope configurable en GB** (0 = no guarda ni restaura nada) y una
**reserva de disco libre** que nunca se toca. Hoy el tope está fijo en el código (32 GB).

## Archivos

- `backend/ai_engine/motor_moe.py`
- `backend/ai_engine/ai_engine_class.py`
- `backend/tests/test_motor_moe.py`

## Cómo está hoy

En `motor_moe.py`:

- `PROYECTOS_MAX_MB = 32768`, una constante.
- `def podar_proyectos(carpeta: Optional[str] = None, limite_mb: float = PROYECTOS_MAX_MB) -> int`: borra los `*.bin`
  más viejos por fecha de modificación (y su `*.calientes.json`) hasta quedar bajo el límite. **Ojo**: el valor por
  defecto del parámetro se fija al definir la función; cambiar la constante después no lo cambia.
- `def proyectos_guardados(carpeta=None) -> {"archivos", "mb", "carpeta"}`.
- `class Motor`:
  - `__init__(self, liberar_gpu=None, ajustes=None)`: `self.ajustes()` devuelve la configuración del motor.
  - `asegurar(self)`: arranca el servidor si hace falta; tras arrancar llama `self._arrancar_vigia()` y devuelve los
    segundos.
  - `_preparar_proyecto(self, cuerpo)`: si la conversación empieza con un bloque grande (`prefijo_de`), calcula `clave`;
    si existe `<clave>.bin` lo restaura (`/slots/0?action=restore`, y `os.utime(ruta)` para marcarlo como usado); si no,
    lo lee (`/completion` con `n_predict: 0`) y lo guarda (`/slots/0?action=save`), y llama `podar_proyectos()`. Deja
    `self.ultimo_proyecto` con `origen`, `tokens`, `segundos`, `guardado`, `clave`.
  - `estado(self)`: devuelve, entre otras cosas, `"proyectos": {**proyectos_guardados(), "ultimo": self.ultimo_proyecto}`.

En `ai_engine_class.py`:

- La configuración por defecto (un diccionario con `"moe_contexto"`, `"moe_hilos"`, `"moe_calientes"`, `"moe_modo"`,
  `"moe_mtp"`, `"moe_nucleo"`, …).
- `AIEngine.motor_moe(self)` crea el motor con
  `ajustes=lambda: {"contexto": …, "hilos": …, "calientes": …, "modo": …, "mtp": …, "nucleo": …}`.

## Cambios

1. **`ai_engine_class.py`, configuración por defecto** (junto a `"moe_nucleo"`):
   ```python
   # Caché de estados del motor en disco (docs/plan-texto-primero.md): tope en GB (0 = no se guarda ninguno) y
   # disco libre que el caché nunca toca. 32 = el tope fijo de hoy: esta tarea no cambia el comportamiento; el valor
   # final se decide al medir (T7)
   "moe_cache_gb": 32,
   "moe_cache_reserva_gb": 20,
   ```
   **Importante**: el valor por defecto inicial es **32**, no menos. Con un tope menor, el motor podaría solo, en el
   primer uso, los ~28 GB de lecturas guardadas que hay hoy, entre ellas las que T7 necesita para medir y las del banco
   real de Prig.
2. **`ai_engine_class.py`, `motor_moe()`**: agregar al diccionario de `ajustes`
   `"cache_gb": self.config.get("moe_cache_gb")` y `"cache_reserva_gb": self.config.get("moe_cache_reserva_gb")`.
3. **`motor_moe.py`**:
   1. Constantes medidas (E4 de `docs/estudio-banco.md`: estado = 10.904 B por token + 65,9 MB fijos):
      `BYTES_POR_TOKEN_ESTADO = 10_904`, `BYTES_FIJOS_ESTADO = 65_900_000`, y
      `def estimar_estado_mb(tokens: int) -> float`.
   2. `podar_proyectos(carpeta=None, limite_mb: Optional[float] = None, reserva_mb: float = 0.0) -> int`:
      - `limite_mb is None` → usar `PROYECTOS_MAX_MB`, **leído al llamar**;
      - borrar los más viejos hasta quedar ≤ `limite_mb`;
      - además, si el disco libre de la carpeta (`shutil.disk_usage(carpeta).free`) es menor que `reserva_mb`, seguir
        borrando los más viejos hasta recuperar la diferencia, o hasta vaciar el caché;
      - si `disk_usage` falla, ignorar la reserva; si la carpeta no existe, devolver 0;
      - la llamada vieja `podar_proyectos(d, limite_mb=2)` tiene que seguir funcionando igual (hay un test).
   3. `Motor.tope_cache_mb(self) -> float`: de `self.ajustes().get("cache_gb")`. `None` o `""` → `PROYECTOS_MAX_MB`; un
      número o un texto numérico → `max(0, float(x)) * 1000`; un valor inválido → `PROYECTOS_MAX_MB`.
      `Motor.reserva_mb(self) -> float`: igual con `"cache_reserva_gb"` (`None` → 0).
   4. `Motor.podar(self) -> int`: `podar_proyectos(CARPETA_PROYECTOS, self.tope_cache_mb(), self.reserva_mb())`.
      - Reemplazar la llamada `podar_proyectos()` de `_preparar_proyecto` por `self.podar()`.
      - Llamar `self.podar()` también en `asegurar()` después de un arranque exitoso (tras `_arrancar_vigia()`), dentro de
        `try/except Exception: pass`: podar nunca puede impedir arrancar.
   5. En `_preparar_proyecto`:
      - **al principio**: si `self.tope_cache_mb() == 0`, `return None`. No se restaura ni se guarda: la petición se
        procesa entera como cualquier otra y no se escribe nada en disco;
      - **después de leer el prefijo**: si `estimar_estado_mb(leidos) > self.tope_cache_mb()`, no hacer el `slot save`
        (no entra ni solo), y dejar en `ultimo_proyecto` `"guardado": False, "motivo": "no cabe en el caché"`.
   6. `estado()`: en `"proyectos"` agregar `"tope_mb"`, `"reserva_mb"` y `"libre_mb"` (disco libre de
      `CARPETA_PROYECTOS`, entero; `None` si no se puede medir).
4. **No cambiar** el cálculo de `clave`/`huella` ni el formato de los archivos (regla 1 del README).

## Tests (`backend/tests/test_motor_moe.py`)

Junto a `test_podar_proyectos` (funciones sueltas) y en la clase `DePuntaAPunta` (servidor falso; en el `setUp` el motor
se crea con `motor_moe.Motor()`, así que cada test puede fijar `self.motor.ajustes = lambda: {...}`):

1. `test_podar_respeta_la_reserva_de_disco`: 3 archivos de 1 MB con fechas distintas, `limite_mb=10`,
   `reserva_mb=5`, y `shutil.disk_usage` parcheado con `free = 3,5 MB` → borra los 2 más viejos.
2. `test_tope_del_cache_desde_los_ajustes`: carpeta parcheada con 3 archivos de 1 MB;
   `self.motor.ajustes = lambda: {"cache_gb": 0.002}` (2 MB) → `self.motor.podar()` deja los 2 más nuevos.
3. `test_cache_apagado_no_guarda_ni_restaura`: como `test_proyecto_se_lee_una_vez_y_despues_se_restaura`, con
   `cache_gb: 0` → el servidor falso solo recibe `/v1/chat/completions` y la carpeta queda vacía. Con un `.bin`
   preexistente cualquiera en la carpeta, tampoco se pide `/slots/0?action=restore`.
4. `test_estado_que_no_cabe_no_se_guarda`: tope menor que `BYTES_FIJOS_ESTADO` (p. ej. `cache_gb: 0.05`) → se pide
   `/completion` pero no `/slots/0?action=save`, no queda archivo y `ultimo_proyecto["guardado"]` es `False`.
5. `test_estado_informa_el_tope`: `self.motor.estado()["proyectos"]` tiene `tope_mb`, `reserva_mb` y `libre_mb`.

**Test existente que hay que actualizar**: ninguno de esta tarea (el diccionario `ajustes` del endpoint lo toca T2).

## Aceptación

- Los 5 tests nuevos fallan sin el cambio y pasan con él; `test_podar_proyectos` sigue pasando.
- La batería completa está en verde.
- Con el motor real: con el valor por defecto (32) nada cambia respecto de hoy. Probar topes chicos recién en T7:
  borran lecturas guardadas.
