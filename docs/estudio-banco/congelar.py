"""Copia congelada y LIMPIA de Prig para medir (E7).

Lo medido no puede cambiar mientras se mide ni contener el examen:
  · el 02/10 apareció un archivo nuevo en Prig (trabajo del usuario): se mide sobre una copia;
  · la primera copia (02/10) incluyó los materiales del estudio, que el banco había indexado: el modelo citó la
    clave de corrección del examen independiente (docs/estudio-banco/examen_independiente.py) en una respuesta.

La copia se arma DESDE EL BANCO (el código tal como lo tiene indexado, no como está hoy en el disco) más la historia
de git, SIN los materiales del estudio. Su banco es una copia del real, después:
  · sin vectores (todo lo medido antes fue sin búsqueda semántica);
  · sin las tablas del examen (examen_proyecto las guarda en el banco y la consola P las lee con P.sql/P.esquema:
    el examen vive ahora en una base aparte, docs/estudio-banco/lote.py);
  · sin historial de cambios y con la versión vista al día (los diffs de los informes del estudio se leían con
    P.diff, y la sección «Cambios desde tu última respuesta» aparecía en cada pregunta del modo general).

Las unidades que no contenían archivos del estudio quedan idénticas: reutilizan las lecturas guardadas del motor.
Después de esto hay que correr la pasada sobre la copia (relee las pocas unidades que cambiaron).

Uso: .venv/bin/python docs/estudio-banco/congelar.py [--rehacer]
"""
import hashlib, json, os, shutil, sqlite3, sys, zlib

REAL = "/home/ama-gi/Prig"
ORIGEN_DB = os.path.expanduser("~/.prig_bancos/Prig-ac5380d79d/banco.db")
DESTINO = os.path.expanduser("~/.cache/prig-estudio/repos/Prig")
BANCOS = os.path.expanduser("~/.cache/prig-estudio/bancos")
EXCLUIR = ("docs/estudio-banco.md", "docs/estudio-banco/")       # los materiales del estudio
os.environ["PRIG_BANCOS"] = BANCOS
sys.path.insert(0, os.path.join(REAL, "backend"))
import banco_proyecto as bp

excluido = lambda ruta: ruta == EXCLUIR[0] or ruta.startswith(EXCLUIR[1])
clave = hashlib.sha1(os.path.abspath(DESTINO).encode()).hexdigest()[:10]
CARPETA_BANCO = os.path.join(BANCOS, f"Prig-{clave}")
if os.path.exists(DESTINO) or os.path.exists(CARPETA_BANCO):
    if "--rehacer" not in sys.argv:
        sys.exit(f"Ya existe la copia ({DESTINO}) o su banco ({CARPETA_BANCO}): --rehacer para empezar de nuevo")
    shutil.rmtree(DESTINO, ignore_errors=True); shutil.rmtree(CARPETA_BANCO, ignore_errors=True)

# 1. El código, tal como lo tiene el banco, sin el estudio
os.makedirs(DESTINO)
shutil.copytree(os.path.join(REAL, ".git"), os.path.join(DESTINO, ".git"))
for punto in (".gitignore", ".gitattributes"):
    if os.path.exists(os.path.join(REAL, punto)):
        shutil.copy2(os.path.join(REAL, punto), os.path.join(DESTINO, punto))
origen = sqlite3.connect(f"file:{ORIGEN_DB}?mode=ro", uri=True)
del_disco, del_banco, irreproducibles, fuera = 0, [], [], []
for ruta, sha, contenido in origen.execute("SELECT ruta, sha, contenido FROM archivos"):
    if excluido(ruta):
        fuera.append(ruta); continue
    src, dst = os.path.join(REAL, ruta), os.path.join(DESTINO, ruta)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    texto = bp.BancoProyecto._leer(src) if os.path.exists(src) else None
    if texto is not None and bp._sha(texto) == sha:
        shutil.copy2(src, dst); del_disco += 1                     # igual en el disco: los bytes exactos
    else:
        guardado = zlib.decompress(contenido).decode("utf-8", "replace") if contenido else ""
        if bp._sha(guardado) != sha:
            irreproducibles.append(ruta)
        with open(dst, "w", encoding="utf-8") as f:
            f.write(guardado)
        del_banco.append(ruta)

# 2. El banco de la copia: copia consistente (API de respaldo de SQLite), sin vectores ni examen
os.makedirs(CARPETA_BANCO)
destino_db = sqlite3.connect(os.path.join(CARPETA_BANCO, "banco.db"))
origen.backup(destino_db)
vectores = destino_db.execute("SELECT COUNT(*) FROM vectores").fetchone()[0]
destino_db.execute("DELETE FROM vectores")
for tabla in ("examen", "examen_resultados"):
    destino_db.execute(f"DROP TABLE IF EXISTS {tabla}")
destino_db.execute("INSERT OR REPLACE INTO meta VALUES ('raiz', ?)", (DESTINO,))
destino_db.commit(); destino_db.close()

# 3. Sincronizar con la copia (quita del banco los archivos del estudio) y borrar el historial de cambios
banco = bp.BancoProyecto(DESTINO)
assert banco.ruta_db.startswith(BANCOS), banco.ruta_db
sinc = banco.sincronizar()
with banco.conectar() as c:
    n_cambios = c.execute("SELECT COUNT(*) FROM cambios").fetchone()[0]
    c.execute("DELETE FROM cambios")
    version = c.execute("SELECT valor FROM meta WHERE clave = 'version'").fetchone()[0]
    c.execute("INSERT OR REPLACE INTO meta VALUES ('version_vista', ?)", (version,))
    restos = c.execute("SELECT COUNT(*) FROM archivos WHERE ruta LIKE 'docs/estudio-banco%'").fetchone()[0]
print(json.dumps({"copia": DESTINO, "banco": CARPETA_BANCO, "archivos_del_disco": del_disco,
                  "archivos_desde_el_banco": del_banco, "irreproducibles": irreproducibles,
                  "excluidos_del_estudio": len(fuera), "vectores_quitados": vectores,
                  "sincronizacion": {k: sinc[k] for k in ("nuevos", "modificados", "borrados", "archivos", "version")},
                  "cambios_borrados": n_cambios, "archivos_del_estudio_que_quedan": restos}, ensure_ascii=False, indent=1))
