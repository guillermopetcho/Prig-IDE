# Prig-IDE: guía para Claude Code

Prig se está pasando de Python a Rust. Esta guía resume lo hecho y el método para seguir. El detalle de cada paso está
en la bitácora de `docs/plan-prig-rust.md` (sección 8); las reglas, en su sección 4. Léelas antes de tocar nada.

## Cómo está armado

- `backend-rust/`: el workspace de Rust.
  - `crates/prig-ventana` (binario `prig`): la ventana (tao + wry). Sirve el servidor en el mismo proceso y arranca
    el backend de Python como hijo.
  - `crates/prig-server` (binario `prig-server`): el servidor axum. Atiende las rutas portadas
    (`src/routes/*.rs`, registradas en `src/lib.rs`) y pasa al backend de Python, por el proxy, las que no tiene.
  - Los crates de cálculo: `prig-ia`, `prig-biblioteca`, `prig-documentos`, `prig-plataforma`, `prig-recursos`,
    `prig-runner`, `prig-modelos`, `prig-fs`, `prig-hardware`, `prig-aprendizaje`, `prig-integrations`, `banco-core`.
  - `crates/prig-nativo-py`: el módulo `prig_nativo` (PyO3) que usa el Python que queda.
- `backend/app.py`: el backend FastAPI. Cada ruta portada se borró de aquí, con su código y sus tests.
- `frontend/`: la interfaz. No cambia: habla con las mismas rutas.

## Lo hecho (tandas 1 a 51)

Todo esto ya está en Rust, comparado con Python y retirado de Python:

- La ventana, la configuración, las banderas, Ollama, los modelos y su buscador, Gemini y la generación.
- Los recursos y el gobernador térmico, el modo frío y el motor MoE.
- La biblioteca: PDF con PDFium, troceado, índices BM25 y TF-IDF, índice semántico, conocimiento, sondeo, fichas,
  paquetes, papers, notas, librerías y referencias.
- Los PDF de salida, que ahora salen de Typst en lugar de reportlab.
- Los desafíos (almacén, comprobación, tutor, crear e importar), ejercicios, guiado, seguimiento y planes de estudio.
- Kaggle, GitHub, YouTube, Prig Hub, inicio, progreso y telemetría.
- Los profesores, los flujos de agentes, el asistente del editor y lo básico del editor.
- El grafo de aprendizaje (tanda 49), la cola de descargas y la copia de Hugging Face (tanda 50) y el director de
  LLM (tanda 51).

## Lo que queda en Python

- **El banco** (`/api/banco*`, `banco_motor.py`, `banco_proyecto.py`) y **el chat** (`/api/ai/chat`): esperan a que
  el usuario suba `prig_banco`. No se portan sin ese código.
- Lo que depende del chat: `/api/app/shutdown`, `/api/interno/cancelar`, `/api/interno/herramienta` y
  `/api/ai/ocupada`.
- Al final se borran los módulos de Python que queden sin uso.

## El método, tanda por tanda

1. Portar las rutas a `prig-server/src/routes/<tema>.rs` y registrarlas en `lib.rs`. Hay que copiar los textos que
   ve el modelo carácter por carácter (regla 4), y las respuestas y los errores tienen que ser los mismos que en
   Python.
2. Añadir casos al comparador `herramientas/comparador_rutas/comparar.py` (una función `casos_<tema>()`). Corre con
   un HOME temporal y una Ollama falsa, sin tocar los datos del usuario.
3. Compilar el servidor:
   `cd backend-rust && CARGO_INCREMENTAL=0 cargo build --release -p prig-server`
4. Comparar solo lo nuevo:
   `.venv/bin/python herramientas/comparador_rutas/comparar.py --solo /api/ruta1,/api/ruta2`
   Todo tiene que dar igual. Una diferencia se corrige o se anota en la bitácora como aceptada.
5. Borrar de `backend/app.py` las rutas, sus modelos y los módulos que queden sin uso, y revisar con `pyflakes`.
6. En el comparador, envolver los casos como `solo_rust`, porque Python ya no los tiene.
7. Pasar las dos suites:
   - Python, desde `backend/`: `../.venv/bin/python -m unittest discover -s tests -t .`
     No pueden aparecer fallos nuevos. Ya había fallos antes y `test_modo_frio` falla a veces por tiempos.
   - Rust: `CARGO_PROFILE_DEV_DEBUG=0 cargo test --workspace --exclude prig-ventana --no-fail-fast`
     Solo puede fallar `corregir_una_pagina_y_buscar`, que necesita PDFium instalado.
8. Añadir una fila a la bitácora con lo hecho, los casos iguales y las diferencias aceptadas. Después, commit.

## Compilar y arrancar en local (Ubuntu)

```bash
sudo apt install build-essential pkg-config python3-venv libwebkit2gtk-4.1-dev libgtk-3-dev
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt maturin
bash herramientas/compilar_nativo.sh   # PDFium, prig-server, la ventana y prig_nativo
./run.sh
```

## Cuidados

- Los tests no tocan nunca `~/.prig_bancos`, `.prig_dataset`, la configuración real ni el Ollama del usuario
  (regla 5).
- `target/debug` llega a ocupar decenas de GB. Usa `CARGO_PROFILE_DEV_DEBUG=0` y bórralo si falta espacio.
- La rama de trabajo es `retirar-duplicados` (PR #2). No se mergea sin que el usuario lo diga.
