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
"""

PERFILES = {
    "extraccion": {
        "nombre": "Extracción de libros",
        "descripcion": "Leer libros enteros sacando afirmaciones con su cita literal.",
        "ctx_min": 3072,          # ~2000 de prompt + margen; la respuesta va en num_predict
        "ctx_preferido": 4096,
        "ctx_max": 6144,
        "kv_cuantizable": False,  # medido: q8_0 bajó las citas del 100 % al 79 %
        "paralelo_deseado": 2,    # medido: 2 ranuras dieron 1,32× de rendimiento
        "pensar": False,
        "keep_alive": "30m",
        "tok_s_min": 10.0,
        "prioriza": "exactitud y rendimiento sostenido",
        "gobernador_termico": True,
    },
    "tutor": {
        "nombre": "Tutor y chat",
        "descripcion": "Responder preguntas mientras estudias.",
        "ctx_min": 4096,
        "ctx_preferido": 8192,
        "ctx_max": 16384,
        "kv_cuantizable": True,
        "paralelo_deseado": 1,
        "pensar": "auto",
        "keep_alive": "30m",
        "tok_s_min": 8.0,         # algo más rápido de lo que se lee
        "prioriza": "que la respuesta empiece rápido",
        "gobernador_termico": False,
    },
    "flujos": {
        "nombre": "Flujos de agentes",
        "descripcion": "Cadenas de pasos: extraer, analizar, criticar, redactar.",
        "ctx_min": 4096,
        "ctx_preferido": 4096,
        "ctx_max": 8192,
        "kv_cuantizable": False,  # los revisores dependen de leer bien
        "paralelo_deseado": 1,
        "pensar": "por_rol",
        "keep_alive": "15m",
        "tok_s_min": 6.0,
        "prioriza": "no recargar modelos entre pasos",
        "gobernador_termico": True,
    },
    "revision": {
        "nombre": "Revisión final",
        "descripcion": "Un único paso de calidad sobre un texto ya corto.",
        "ctx_min": 4096,
        "ctx_preferido": 8192,
        "ctx_max": 16384,
        "kv_cuantizable": False,
        "paralelo_deseado": 1,
        "pensar": True,
        "keep_alive": "5m",
        "tok_s_min": 2.5,
        "prioriza": "calidad por encima de velocidad",
        "gobernador_termico": False,
    },
}

TIRADORES = {
    "calidad": "Máxima calidad",
    "equilibrado": "Equilibrado",
    "velocidad": "Máxima velocidad",
}


def perfil(nombre: str) -> dict:
    if nombre not in PERFILES:
        raise KeyError(f"perfil desconocido: {nombre}. Hay: {', '.join(PERFILES)}")
    return {"id": nombre, **PERFILES[nombre]}
