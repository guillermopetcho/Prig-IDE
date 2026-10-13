# T3 — El modo general recibe los hechos del banco

Leer antes el [README](README.md). Sin dependencias.

## Objetivo

Que el modo general (el que no usa estados guardados) reciba con la pregunta el mismo bloque de hechos del banco que ya
recibe el modo unidad: dónde está definido lo que nombra la pregunta, quién lo llama (resuelto por el grafo y encontrado
por texto), qué rutas expone, a qué endpoints llega, quién lee una clave de configuración o una variable de entorno, y
las apariciones literales con la función que las contiene. Con el plan «texto primero», el modo general pasa a ser el
camino normal, así que tiene que tener lo mejor del contexto.

## Archivos

- `backend/app.py`, función `ai_chat`.
- `backend/tests/test_banco_proyecto.py`, clase `TestChat`.

## Cómo está hoy

- `memoria_consulta.hechos_de_la_pregunta(banco, pregunta, maximo_caracteres=5000) -> str` ya existe y está probada
  (`tests/test_memoria_consulta.py`, `TestHuecosDelGrafo`). Devuelve `""` si la pregunta no nombra nada del código, o un
  bloque que empieza con `FACTS FROM THE PROJECT BANK`. Tarda ~0,2 s sobre un banco de 1,3 M tokens.
- En modo unidad ya se usa: `lectura_unidades.LectorUnidades.pregunta_con_contexto(u, texto, hechos=True)`.
- `ai_chat`, cuando `req.banco` es verdadero:
  ```python
  banco, banco_info, mapa, contexto_banco = _preparar_banco(req, modelo)
  unidad = _unidad_para(req, modelo, banco)
  if unidad is not None and banco_info is not None:
      banco_info.update({"modo": "unidad", ...})
  if banco is not None:
      if contexto_banco:
          prompt = f"{contexto_banco}\n\n{prompt}"
      ...
  ```
  `contexto_banco` es el texto de `BancoProyecto.componer`: cambios recientes, notas, resoluciones y código literal
  relevante. En modo unidad ese `prompt` no se usa, porque `_chat_eventos` reemplaza los mensajes por el prefijo de la
  unidad.

## Cambios

1. En `ai_chat`, después de `unidad = _unidad_para(...)` y **antes** de armar `prompt` con `contexto_banco`:
   - solo si `banco is not None` y `unidad is None` (modo general);
   - `hechos = memoria_consulta.hechos_de_la_pregunta(banco, req.prompt)`, dentro de `try/except Exception` → `""`: un
     fallo de los hechos nunca puede romper el chat;
   - si hay hechos: `contexto_banco = f"{hechos}\n\n{contexto_banco}" if contexto_banco else hechos`;
   - `banco_info["hechos_caracteres"] = len(hechos)` (si `banco_info` no es `None`): así se ve en el evento `banco` del
     chat.
2. Un comentario breve con el porqué: en el estudio, el modo general era el más fiable, y desde este plan es el camino
   normal (`docs/plan-texto-primero.md`).
3. **Si T4 ya está hecha**, `_unidad_para` devuelve `(unidad, motivo)`: usar la variable `unidad` que ya existe.

## Tests (`backend/tests/test_banco_proyecto.py`, clase `TestChat`)

1. En `test_chat_con_banco` (pregunta «¿Qué hace calientes_para?», en modo general): agregar
   `self.assertIn("FACTS FROM THE PROJECT BANK", pregunta)` y `self.assertIn("calientes_para", pregunta)`, y que el evento
   `banco` traiga `hechos_caracteres > 0`.
2. `test_sin_nombres_de_codigo_no_hay_hechos`: una pregunta como «¿Cómo está organizado el proyecto?» en modo general →
   el último mensaje no contiene `FACTS FROM THE PROJECT BANK`.
3. En `test_modo_unidad`: parchear `memoria_consulta.hechos_de_la_pregunta` con un `mock` y comprobar que **no** se llama
   desde `ai_chat`. El de unidad pide sus hechos por `pregunta_con_contexto`; el lector falso de ese test ya registra el
   parámetro `hechos`.

## Aceptación

- Los tests nuevos fallan sin el cambio; la batería completa está en verde.
- Con el modelo real (T7 lo mide): en modo general, las preguntas de llamadores, impacto y configuración traen el bloque
  de hechos.
