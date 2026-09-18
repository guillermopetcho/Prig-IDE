"""
Gestión de recursos: qué modelo puede correr en esta máquina, y cómo.

El paquete sigue el orden en que se toma la decisión:

    detector     qué máquina es (GPU, CPU, RAM, disco, sistema, Ollama)
    gguf         leer la cabecera de un modelo, incluso sin descargarlo
    ficha        qué modelo es (capas, caché KV, expertos, si piensa)
    calculadora  cuánta memoria ocupará, dónde irá y a qué velocidad
    perfiles     qué necesita cada uso: extraer no es charlar
    calibracion  comprobarlo cargándolo de verdad, y retroceder si falla
    servidor     las variables que solo se aplican reiniciando Ollama
    gestor       vigilar mientras corre: memoria, temperatura, OOM, swap
    almacen      recordar lo medido para no repetirlo

Todo lo que la calculadora da por bueno sale de mediciones en máquinas reales, no
de hojas de especificaciones. Los números de referencia están en los docstrings de
cada módulo, con su origen.
"""
