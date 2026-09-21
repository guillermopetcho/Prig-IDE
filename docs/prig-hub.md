# Prig Hub · Formato de repositorio (versión 1)

Prig Hub guarda tu aprendizaje en **texto plano dentro de un repositorio git**. Contiene
lo que sigues, tus cursos, tus rutas y tus desafíos. Cualquiera puede leer el
repositorio, editarlo a mano o compartirlo, con Prig o sin él.

Este documento es el contrato: un repositorio que lo cumple funciona en cualquier Prig.

---

## Dos tipos de repositorio

| Tipo | Nombre recomendado | Qué es |
|---|---|---|
| **perfil** | `usuario/prig` (uno por persona) | Quién eres, a quién sigues y tus listas personales |
| **pack** | `usuario/prig-<tema>` (los que quieras) | Algo para compartir: una ruta de ML, un set de desafíos, una lista de canales |

Prig reconoce un repositorio por su archivo **`prig.yaml`**, no por el nombre. El nombre
es una convención que ayuda a encontrarlos: con solo el usuario, Prig sabe dónde está su
perfil. Los repositorios publicados desde Prig llevan además el *topic* de GitHub
`prig-perfil` o `prig-pack`, que es lo que usa **Descubrir**.

Cualquier servidor git con HTTPS sirve: GitHub, GitLab, Codeberg…

## Estructura

```
prig.yaml            manifiesto (obligatorio)
personas.yaml        gente a seguir: perfiles de GitHub, Kaggle, canales de YouTube…
recursos.yaml        cursos, videos, listas, notebooks, datasets, repositorios, artículos…
suscripciones.yaml   solo en un perfil: los perfiles y packs que sigues
rutas/<id>.md        una ruta de estudio por archivo
desafios/<id>/       un desafío por carpeta
README.md            portada para GitHub (Prig la genera)
LICENSE.md           licencias del contenido y del código
```

Se organiza **por tipo de elemento, no por plataforma**. La plataforma (GitHub, Kaggle,
YouTube, Hugging Face, Coursera…) se deduce del enlace. Las secciones de Prig son vistas
filtradas, así que una plataforma nueva no obliga a cambiar el formato.

Un único formato por archivo: **YAML** para las listas y **Markdown** para el texto
largo (rutas y enunciados).

## `prig.yaml`

| Campo | Obligatorio | Descripción |
|---|---|---|
| `formato` | sí | Versión de este formato. Hoy, `1`. |
| `tipo` | sí | `perfil` o `pack` |
| `titulo` | sí | Nombre visible |
| `descripcion` | | Una o dos frases |
| `autor` | | `nombre` y, si quieres, `github` |
| `idioma` | | Código de idioma: `es`, `en`… |
| `nivel` | | `principiante`, `intermedio` o `avanzado` |
| `etiquetas` | | Lista de temas: `python`, `pytorch`… |
| `version` | | **Versión del contenido**, por ejemplo `1.2.0`. Súbela al publicar cambios en un pack. |
| `licencia` | | `contenido` (p. ej. `CC-BY-4.0`) y `codigo` (p. ej. `MIT`) |
| `enlaces` | | Solo en un perfil: tus perfiles en otras plataformas |

`formato` y `version` son cosas distintas. El primero dice **cómo leer** los archivos y
el segundo **qué edición** del contenido tienes.

## `personas.yaml` y `recursos.yaml`

Cada archivo es una lista. Cada entrada tiene:

| Campo | Obligatorio | Descripción |
|---|---|---|
| `url` | sí | El enlace, que es lo que identifica al elemento |
| `titulo` | | Si falta, Prig intenta leerlo de la página |
| `tipo` | | Si falta, se deduce del enlace (ver abajo) |
| `etiquetas` | | Lista de temas |
| `nivel` | | Como en el manifiesto |
| `minutos` | | Tiempo de estudio estimado |
| `nota` | | Tu comentario |
| `id` | | Identificador propio, si no quieres usar el del enlace |

**Tipos de recurso:** `curso`, `video`, `lista`, `notebook`, `dataset`, `competicion`,
`repositorio`, `archivo`, `modelo`, `articulo`, `ejercicio`, `web`. En `personas.yaml`
el tipo es siempre `persona`.

## Identidad estable

Cada elemento tiene un identificador que **no depende de su posición**. Es el `id`
explícito, si lo hay, o si no la clave canónica del enlace:

- `youtube.com/watch?v=abc`, `youtu.be/abc` y `m.youtube.com/watch?v=abc&t=30` son
  `youtube:video:abc`;
- `kaggle.com/code/ana/eda-titanic` es `kaggle:notebook:ana/eda-titanic`;
- `https://www.GitHub.com/Ana/Calc/` es `github:repositorio:ana/calc`.

El progreso se guarda por esa clave. Así, reordenar una ruta no rompe nada, y un video
que aparece en dos packs se marca como visto en los dos.

## `rutas/<id>.md`

Una cabecera YAML entre `---` y, debajo, la ruta en Markdown. **Cada elemento de lista de
primer nivel es un paso.** Su primer enlace es el destino y el resto del texto, la
explicación:

- `[Texto](https://…)`: un recurso;
- `[Texto](desafio:<id>)`: un desafío de este mismo repositorio.

Campos de la cabecera: `titulo` (obligatorio), `descripcion`, `nivel`, `etiquetas`.

## `desafios/<id>/`

| Archivo | Contenido |
|---|---|
| `desafio.md` | Cabecera (`titulo` obligatorio, `nivel`, `etiquetas`, `lenguaje: python`) y el enunciado en Markdown |
| `inicio/*.py` | El código de partida que recibe el alumno |
| `solucion/*.py` | La solución de referencia, con los mismos nombres de archivo |
| `pruebas/test_*.py` | Pruebas `unittest` |

Un desafío se marca como **verificado** solo si Prig comprueba, ejecutándolo, que la
solución pasa todas las pruebas y el código de partida no. Es la misma verificación
que usan los desafíos de Exercism.

## `suscripciones.yaml` (solo perfil)

Una lista de entradas con `url` (el repositorio seguido) y `nota`. Es pública: indica a
quién sigues.

## Qué NO va en el repositorio

**Tu progreso.** Lo que viste, lo que terminaste y los desafíos que resolviste se guardan
en tu equipo (`~/.prig_hub/progreso.jsonl`). Cada línea es un evento, así que dos
equipos nunca se pisan. En un perfil puedes publicar voluntariamente un **resumen**
(`progreso.md`, con recuentos y sin detalles). Está apagado por defecto.

## Reglas de lectura

- Prig **nunca falla** por un archivo mal escrito: salta la entrada, lo avisa y sigue.
- Los campos desconocidos se ignoran, para que las versiones futuras del formato puedan
  agregar campos sin romper las anteriores.
- Un `formato` mayor que el que Prig conoce se lee igual, con un aviso.

## Seguridad

- **Actualizar lo que sigues nunca es automático.** Prig descarga los cambios, muestra
  un resumen (qué se agregó, quitó o cambió, y si cambió código ejecutable) y solo
  aplica si lo confirmas.
- **Desafíos ajenos:** su código solo se ejecuta cuando lo importas, después de que lo
  hayas visto.
- **Contenido ajeno e IA:** cuando el tutor lee un repositorio de otro, lo recibe como
  *datos*, nunca como instrucciones, y sin herramientas.
- **Qué se descarga:** solo repositorios git por HTTPS, con un tamaño máximo, y nunca se
  ejecuta nada al descargarlos. De YouTube, Kaggle y demás plataformas solo se guardan
  enlaces y títulos públicos.
