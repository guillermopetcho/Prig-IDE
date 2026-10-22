# Diferenciales de la plataforma (F2) y de los modelos (F3)

Comparan la versión de Python puro de cada módulo de la plataforma (el commit `REFERENCIA` de `_referencia.py`,
antes de pasar a Rust) con la de ahora (Rust por `prig_nativo`). Las mismas entradas al azar tienen que dar lo mismo:
valores devueltos, excepciones (tipo y texto), lo que se imprime y cómo queda el disco.

| Archivo | Módulos |
|---|---|
| `banderas_perfiles.py` | `feature_flags.py`, `perfiles_config.py` |
| `archivos.py` | `file_manager.py` (rutas, árbol, leer, cuadernos, escribir, crear, borrar, configuración) |
| `ide.py` | `ide_servicios.py` (listar, buscar y reemplazar con expresiones de Python, renombrar, duplicar, recientes, proyectos, explorar carpetas) |
| `explorador.py` | `explorador.py` (explorador de libros) |
| `inicio.py` | `inicio.py` (perfil, actividad, semana) |
| `ejecucion.py` | `runner.py`, `kernel_session.py` (scripts, C/C++, cuadernos, celdas) |
| `opciones.py` | `ollama_opciones.py` (validar, catálogo, almacén de capas) |
| `gestion.py` | `ollama_gestion.py`, contra un Ollama falso local (fichas, copias, variantes, importar GGUF, registro) |
| `buscador.py` | `buscador_modelos.py`, con las páginas y JSON de las pruebas mutados y un servidor falso local |

    herramientas/diferencial_plataforma/todo.sh [semilla]     # todos, pocas vueltas (unos minutos)
    .venv/bin/python herramientas/diferencial_plataforma/ide.py 7 100

Todo corre en carpetas temporales (también `HOME`), con `ulimit -v`; nada toca la configuración del usuario. Las
peticiones van a servidores falsos locales: nunca al Ollama del usuario ni a internet.

Diferencias aceptadas (escritas en el código):

- El texto de los errores de una expresión regular mal escrita es el de Rust (`fancy-regex`); el diferencial los
  compara solo por tipo. Después de un acierto vacío, si el patrón podía casar algo no vacío en ese mismo sitio con
  otra alternativa, Python lo toma y Rust sigue desde el carácter siguiente (`regex_py.rs`).
- Ejecutar: al pasarse del tiempo límite se mata el grupo de procesos entero, y una sesión de cuaderno que escribe en
  stderr bytes que no son UTF-8 sigue vaciando la tubería (`ejecucion.rs`). Las dos eran fallos de Python.
- Los problemas de sintaxis de Python (`ide_servicios.problemas_python`) siguen con el compilador de Python.
- Los nombres de archivo que no son UTF-8 se muestran con U+FFFD.
- Red (F3): el texto de un error de conexión es el de reqwest; una espera de flujo largo (crear o subir un modelo)
  no tiene límite de lectura, solo de conexión (requests cortaba a la hora sin datos).
- Buscador: la caché de Rust devuelve copias (en Python, marcar «destacar» en un resultado lo dejaba marcado
  dentro de la caché); `\w` es el de Rust (incluye las marcas combinantes, no los números como «²»).
