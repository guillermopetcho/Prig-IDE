"""
Perfiles de uso: el mejor rendimiento depende de para qué se use el modelo.

Una sola configuración "óptima" no existe, y está medido. Cuantizar la caché KV a
q8_0 hizo el tutor algo más rápido, y en la extracción de libros bajó las citas
verificadas del 100 % al 79 %: copiar texto literal es la operación más sensible a
la precisión que hay. Lo que es bueno para charlar es malo para extraer.

Cada perfil fija lo que su tarea necesita de verdad:

  · ctx_min / ctx_preferido: el contexto que la tarea usa. No se reserva más porque
    cada token ocioso de caché es memoria que no puede ir a otra ranura o a una capa
    más en GPU.
  · kv_cuantizable: si la tarea tolera perder precisión en la caché.
  · tok_s_min: por debajo, el modelo "funciona" pero no sirve para esto. Un tutor a
    3 tok/s desespera; una revisión final de un solo paso lo aguanta.
  · pensar: si el razonamiento en voz alta aporta o estorba.
La tabla está en Rust (backend-rust/crates/prig-recursos, perfiles.rs).
"""


def _rs():
    from nativo_rust import rust
    return rust().perfiles


# {id: {nombre, descripcion, ctx_min, ctx_preferido, ctx_max, kv_cuantizable, paralelo_deseado, pensar,
#       keep_alive, tok_s_min, prioriza, gobernador_termico}}
PERFILES = _rs().perfiles()

TIRADORES = _rs().tiradores()


def perfil(nombre: str) -> dict:
    """ {"id": nombre, **PERFILES[nombre]}; KeyError si no existe """
    return _rs().perfil(nombre)
