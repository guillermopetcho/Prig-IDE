# Diferenciales de backend/recursos

Comparan la versión de Python puro de `backend/recursos` y `backend/audio_monitor.py` (el commit `9d9bb98`, antes
de pasar a Rust) con la de ahora (Rust, por `prig_nativo`): las mismas entradas al azar tienen que dar el mismo
resultado, con el orden de las claves, los `int` y `float`, los textos y las excepciones (docs/plan-prig-rust.md, F1).

    herramientas/diferencial_recursos/todo.sh [semilla]          # todos, con pocas vueltas
    .venv/bin/python herramientas/diferencial_recursos/termico.py 3 400

| Archivo | Qué compara |
|---|---|
| `calculo.py` | gguf, ficha, perfiles, calculadora |
| `almacen.py` | el almacén (archivo en disco byte a byte) y el JSON |
| `ritmo.py` | modo suave y fijador de núcleos (lecturas del reloj incluidas) |
| `suave.py` | motor suave (envoltorio, controlador) y energía |
| `termico.py` | gobernador, controlador del modo frío y monitor |
| `servidor.py` | ajustes del servidor de Ollama |
| `calibracion.py` | canario, decisiones y pruebas completas guionizadas |
| `gestor.py` | medidas, estado en vivo y recomendación ajustada |
| `audio.py` | análisis del audio bit a bit y listado de aplicaciones |
| `maquina.py` | radiografía y huella en esta máquina (solo lee) |

`_referencia.py` extrae la versión vieja con `git archive` en una carpeta temporal que se borra al salir. Los
archivos de prueba van a carpetas temporales; nada escribe en el almacén ni en la configuración del usuario
(`almacen.py` solo lee `~/.prig_recursos.json` para comprobar que se reescribe igual).

Desvíos decididos (no son fallos): ver la bitácora del plan, F1.
