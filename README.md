# Prig IDE

Un entorno de desarrollo local para **aprender a programar**, con un tutor de IA que
funciona sin conexión a ningún servicio de pago.

No es un editor con un chat al lado. La idea que lo ordena todo es otra:

> **El IDE que sabe qué NO sabes.**

Los ejercicios se verifican ejecutándolos, el tutor responde citando los libros que
tú tienes, y el perfil mide competencia real en lugar de casillas marcadas.

---

## Qué necesitas

| Requisito | Detalle |
|---|---|
| Linux | Probado en Ubuntu con X11 |
| Python | 3.10 o superior |
| [Ollama](https://ollama.com) | Para los modelos locales |
| GPU | Opcional. Con 6 GB de VRAM funciona `qwen2.5-coder:7b` |

```bash
ollama pull qwen2.5-coder:7b
```

## Arrancar

```bash
git clone <este-repositorio> Prig
cd Prig
./run.sh
```

`run.sh` crea el entorno virtual, instala dependencias, levanta Ollama si hace falta
y abre la ventana. Si el puerto 8000 está ocupado busca otro; si Prig ya está
abierto, reutiliza esa instancia.

Sin ventana nativa disponible, cae al navegador en `http://127.0.0.1:8000`.

---

## Cómo funciona

### Biblioteca y tutor con citas

Importa PDFs, apuntes o cuadernos a la **Biblioteca**. Prig los trocea e indexa en un
catálogo SQLite. Al marcar **Mi biblioteca** en el chat, el tutor responde apoyándose
en ese material y cita **libro y página**; si la respuesta no está ahí, lo dice en
lugar de inventarla.

### Práctica verificada por ejecución

En **Práctica** escribes un concepto y Prig genera un ejercicio. Antes de enseñártelo:

1. Ejecuta la solución de referencia contra sus propios tests.
2. Ejecuta esos tests contra el código sin implementar.

Si la solución no pasa, o si los tests pasan con el esqueleto vacío, el ejercicio se
descarta y se reintenta. Solo llega lo que supera ambas comprobaciones.

Tu entrega se corrige **ejecutándola**, no preguntándole al modelo si está bien.
Las pistas son graduadas (conceptual → estructura → línea concreta) y se cuentan:
resolver sin ayuda y resolver con tres pistas no significan lo mismo.

### Cuadernos con kernel persistente

Las celdas comparten espacio de nombres, como en Jupyter: lo que defines en una está
disponible en la siguiente. Editables in situ, con `Ctrl+Enter` para ejecutar y un
botón para reiniciar el intérprete.

### Perfil

Mide acierto al primer intento sin pistas, intentos hasta acertar, tiempo hasta el
primer test en verde, en qué tipos de error fallas y qué conceptos se te resisten.
Cada debilidad tiene un botón para practicar justo eso.

---

## Estructura

```
backend/
  app.py                 API FastAPI
  knowledge/             Ingestión, recuperación y evidencias (RAG)
  knowledge_service.py   Puente entre la biblioteca y el catálogo
  exercise_engine.py     Generación y verificación por ejecución
  kernel_session.py      Intérpretes persistentes para cuadernos
  learning_telemetry.py  Métricas de aprendizaje
  schema_migrations.py   Versionado de los datos del usuario
  evals/                 Banco de evaluación de agentes
  tests/                 Tests de los módulos que tocan datos del usuario
frontend/                Interfaz (HTML + JS, sin framework)
```

### Dónde se guardan tus datos

| Ruta | Contenido |
|---|---|
| `~/.prig_books/` | Biblioteca y su catálogo (`.index/catalog.db`) |
| `~/.prig_ai_config.json` | Modelos y parámetros de inferencia |
| `~/.prig_flags.json` | Banderas de funcionalidad |
| `<workspace>/.prig_dataset/` | Ejercicios, telemetría y dataset |
| `<workspace>/.prig_seguimientos/` | Rutas de aprendizaje |
| `<workspace>/.prig_plans/` | Planes de estudio versionados |

Todo local. Nada sale de tu equipo salvo la búsqueda web, que es opcional.

---

## Desarrollo

```bash
# Tests
.venv/bin/python -m unittest discover -s backend/tests -t .
.venv/bin/python -m unittest discover -s backend/knowledge/tests -t . -p 'test_*.py'

# Banco de evaluación: mide si un modelo sirve para generar ejercicios
.venv/bin/python backend/evals/run_eval.py --model qwen2.5-coder:7b --attempts 3

# Datos de demostración, para no generar un plan real en cada prueba
.venv/bin/python backend/seed_demo.py --workspace /ruta/al/proyecto
```

### Banderas de funcionalidad

```bash
PRIG_FLAG_KAGGLE_WINDOW=1 ./run.sh     # activar algo puntualmente
curl localhost:8000/api/flags          # ver el estado
```

### Referencia de calidad

`qwen2.5-coder:7b` genera ejercicios válidos el **65 %** de las veces al primer
intento y el **90 %** con hasta tres. Unos 14 s por ejercicio. Si tocas un prompt o
cambias de modelo, vuelve a pasar el banco de evaluación antes de darlo por bueno.

---

## Limitaciones conocidas

- **Recorrido** y **Seguimiento** son dos sistemas de plan de estudio en paralelo que
  hacen casi lo mismo. Pendiente de fusionar.
- La importación de Kaggle **no descarga el cuaderno original** (su API no lo permite
  sin autenticación): crea una plantilla de práctica y lo advierte.
- El recuperador de la biblioteca es léxico (BM25 + TF-IDF). Se compensa reformulando
  la consulta con el modelo antes de buscar.
- Sin empaquetado: por ahora se ejecuta desde el repositorio.
>>>>>>> 4408db5 (Initial commit: Prig IDE)
