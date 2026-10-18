//! El motor de aprendizaje por grafo de nodos (`motor_aprendizaje_nodos.py`): un DAG de competencias de Junior a
//! Senior, cada una con su marco teórico, sus recursos de YouTube, GitHub, Kaggle y Prig Hub y una tarea con su
//! solución de referencia y sus pruebas.
//!
//! Los nodos son fijos: `datos/grafo_nodos.json` guarda el grafo como lo deja Python al arrancar (con las aristas
//! inversas ya conectadas) y el texto de su índice de búsqueda. El progreso vive en
//! `<carpeta>/.prig_aprendizaje_progreso.json`, con la carpeta de trabajo del proceso al arrancar (`os.getcwd()`,
//! la raíz de Prig). Lo que en Python lanzaba una excepción es `Err` con su `str()`: la ruta responde
//! `{"ok": false, "error": ...}`.

use prig_plataforma::py;
use prig_plataforma::valor::{Mapa, Valor};
use std::io::{Read, Write};
use std::path::Path;
use std::process::{Command, Stdio};
use std::sync::LazyLock;
use std::time::{Duration, Instant};

type R<T> = Result<T, String>;

struct Datos {
    nodos: Vec<Mapa>,
    indice: Vec<String>,
}

static DATOS: LazyLock<Datos> = LazyLock::new(|| {
    let Ok(Valor::Mapa(d)) = prig_plataforma::json::leer(include_str!("../datos/grafo_nodos.json")) else {
        panic!("datos/grafo_nodos.json no es válido")
    };
    let nodos = d.lista("nodos").unwrap_or(&[]).iter().filter_map(|n| match n { Valor::Mapa(m) => Some(m.clone()), _ => None }).collect();
    let indice = d.lista("indice").unwrap_or(&[]).iter().map(Valor::texto_py).collect();
    Datos { nodos, indice }
});

/// La carpeta de trabajo de Python al importar el módulo
static CARPETA: LazyLock<String> = LazyLock::new(|| py::abspath(&py::getcwd()));

const NIVELES: [&str; 4] = ["junior", "intermedio", "avanzado", "senior"];

fn nodo(id: &str) -> Option<&'static Mapa> {
    DATOS.nodos.iter().find(|n| n.texto("id") == Some(id))
}

fn get(v: &Valor, k: &str, defecto: Valor) -> R<Valor> {
    py::get(v, k, defecto)
}

fn vacio() -> Valor {
    Valor::Mapa(Mapa::new())
}

fn t(m: &Mapa, k: &str) -> String {
    m.get(k).map(Valor::texto_py).unwrap_or_default()
}

/// `str.capitalize()`
fn capitalizar(s: &str) -> String {
    let mut c = s.chars();
    match c.next() {
        Some(p) => p.to_uppercase().chain(c.as_str().to_lowercase().chars()).collect(),
        None => String::new(),
    }
}

/// `seq[:n]` de Python
fn hasta<T>(v: &[T], n: i128) -> &[T] {
    let l = v.len() as i128;
    let fin = if n < 0 { (l + n).max(0) } else { n.min(l) };
    &v[..fin as usize]
}

pub struct Motor {
    carpeta: String,
}

impl Default for Motor {
    fn default() -> Self {
        Motor::en(&CARPETA)
    }
}

impl Motor {
    pub fn en(carpeta: &str) -> Motor {
        Motor { carpeta: py::abspath(carpeta) }
    }

    fn ruta_progreso(&self) -> String {
        py::join(&self.carpeta, ".prig_aprendizaje_progreso.json")
    }

    fn leer_progreso(&self) -> Valor {
        let ruta = self.ruta_progreso();
        if !Path::new(&ruta).exists() {
            return vacio();
        }
        prig_plataforma::leer_json(Path::new(&ruta)).unwrap_or_else(|_| vacio())
    }

    fn guardar_progreso(&self, datos: &Valor) {
        let _ = prig_plataforma::escribir_json(Path::new(&self.ruta_progreso()), datos, 2);
    }

    /// `obtener_grafo(filtro_nivel)`
    pub fn grafo(&self, nivel: Option<&str>) -> R<Mapa> {
        let progreso = self.leer_progreso();
        let filtro = nivel.filter(|n| !n.is_empty()).map(str::to_lowercase);
        let mut lista: Vec<Mapa> = Vec::new();
        for n in &DATOS.nodos {
            if let Some(f) = &filtro {
                if f != "todos" && n.get("nivel").map(Valor::texto_py).as_deref() != Some(f.as_str()) {
                    continue;
                }
            }
            let mut copia = n.clone();
            let p = get(&progreso, &t(n, "id"), vacio())?;
            copia.poner("completado", get(&p, "completado", Valor::Bool(false))?);
            let p = get(&progreso, &t(n, "id"), vacio())?;
            copia.poner("fecha_completado", get(&p, "fecha", Valor::Nulo)?);
            let p = get(&progreso, &t(n, "id"), vacio())?;
            copia.poner("intentos", get(&p, "intentos", Valor::Entero(0))?);
            lista.push(copia);
        }
        let mut aristas = Vec::new();
        for n in &lista {
            for destino in n.lista("siguientes").unwrap_or(&[]) {
                let destino = destino.texto_py();
                if nodo(&destino).is_some() {
                    // los nodos del grafo nunca tienen «completado»: `completado and False`
                    let c = n.valor("completado");
                    let completada = if c.verdad() { Valor::Bool(false) } else { c.clone() };
                    aristas.push(Valor::Mapa(
                        Mapa::new().con("desde", n.valor("id").clone()).con("hacia", destino).con("completada", completada),
                    ));
                }
            }
        }
        let global = self.estadisticas_de(&progreso)?;
        Ok(Mapa::new()
            .con("ok", true)
            .con("total_nodos", lista.len() as i128)
            .con("niveles_disponibles", Valor::Lista(["todos", "junior", "intermedio", "avanzado", "senior"].map(Valor::from).to_vec()))
            .con("nodos", Valor::Lista(lista.into_iter().map(Valor::Mapa).collect()))
            .con("aristas", Valor::Lista(aristas))
            .con("progreso_global", global))
    }

    /// `obtener_nodo(nodo_id)`: None si no existe
    pub fn nodo(&self, id: &str) -> R<Option<Mapa>> {
        let Some(n) = nodo(id) else { return Ok(None) };
        let mut n = n.clone();
        let p = get(&self.leer_progreso(), id, vacio())?;
        n.poner("completado", get(&p, "completado", Valor::Bool(false))?);
        n.poner("intentos", get(&p, "intentos", Valor::Entero(0))?);
        n.poner("ultimo_resultado", get(&p, "ultimo_resultado", Valor::Nulo)?);
        Ok(Some(n))
    }

    /// `buscar(query, limite)`
    pub fn buscar(&self, consulta: &str, limite: i128) -> Vec<Mapa> {
        if py::strip(consulta).is_empty() {
            return hasta(&DATOS.nodos, limite).to_vec();
        }
        let bajo = consulta.to_lowercase();
        let terminos: Vec<&str> = bajo.split_whitespace().collect();
        let mut encontrados: Vec<(i64, &Mapa)> = Vec::new();
        for (n, texto) in DATOS.nodos.iter().zip(&DATOS.indice) {
            let titulo = t(n, "titulo").to_lowercase();
            let id = t(n, "id").to_lowercase();
            let mut puntos = 0;
            for termino in &terminos {
                if titulo.contains(termino) {
                    puntos += 15;
                } else if id.contains(termino) {
                    puntos += 8;
                } else if texto.contains(termino) {
                    puntos += 3;
                }
            }
            if puntos > 0 {
                encontrados.push((puntos, n));
            }
        }
        encontrados.sort_by(|a, b| b.0.cmp(&a.0));
        hasta(&encontrados, limite).iter().map(|(_, n)| (*n).clone()).collect()
    }

    /// `ejecutar_tarea(nodo_id, codigo_usuario, usar_solucion)`
    pub fn ejecutar(&self, id: &str, codigo: &str, usar_solucion: bool) -> Mapa {
        let error = |e: String| Mapa::new().con("ok", false).con("error", e);
        let Some(n) = nodo(id) else { return error(format!("Nodo '{id}' no encontrado")) };
        let tarea = n.mapa("tarea_prerespondida").cloned().unwrap_or_default();
        if tarea.is_empty() {
            return error("El nodo no cuenta con una tarea ejecutable".into());
        }
        let probar = if usar_solucion { t(&tarea, "solucion_referencia") } else { codigo.to_string() };
        let script = format!(
            "# Runner de Verificación de Tarea Prig IDE\n{probar}\n\n{}\n\nif __name__ == '__main__':\n    \
             # Ejecutar funciones de prueba\n    import sys\n    \
             test_funcs = [v for k, v in list(globals().items()) if k.startswith('test_') and callable(v)]\n    \
             for tf in test_funcs:\n        tf()\n",
            t(&tarea, "pruebas_unitarias")
        );
        let inicio = Instant::now();
        let fallo = |e: String| Mapa::new().con("ok", false).con("nodo_id", id).con("error", e);
        // crear el temporal queda fuera del try de Python: su error no lleva el nodo
        let ruta = match temporal(&script) {
            Ok(r) => r,
            Err(e) => return error(e),
        };
        let res = correr(&ruta);
        let _ = std::fs::remove_file(&ruta);
        let (codigo_salida, salida, err) = match res {
            Ok(Some(x)) => x,
            Ok(None) => {
                return Mapa::new()
                    .con("ok", false)
                    .con("nodo_id", id)
                    .con("error", "Tiempo de ejecución agotado (posible bucle infinito en la solución). Límite: 4.0s.")
                    .con("tiempo_ms", 4000.0)
            }
            Err(e) => return fallo(e),
        };
        let ms = prig_recursos::valor::redondear(inicio.elapsed().as_secs_f64() * 1000.0, 2);
        let exito = codigo_salida == Some(0);
        let resultado = Mapa::new()
            .con("ok", exito)
            .con("nodo_id", id)
            .con("usado_solucion", usar_solucion)
            .con("tiempo_ms", ms)
            .con("salida", py::strip(&salida))
            .con("error", if exito { "" } else { py::strip(&err) })
            .con("mensaje", if exito { "¡Todas las pruebas superadas con éxito!" } else { "Hubo fallos en las pruebas unitarias." });
        let r = if exito && !usar_solucion { self.marcar(id, true, Some(&resultado)) } else { self.sumar_intento(id) };
        match r {
            Ok(()) => resultado,
            Err(e) => fallo(e),
        }
    }

    /// `abrir_en_editor(nodo_id)`: crea `aprendizaje/<nodo>/` con el ejercicio, sus pruebas, la teoría y la solución
    pub fn abrir_en_editor(&self, id: &str) -> R<Mapa> {
        let Some(n) = nodo(id) else { return Ok(Mapa::new().con("ok", false).con("error", format!("Nodo '{id}' no encontrado"))) };
        let tarea = n.mapa("tarea_prerespondida").cloned().unwrap_or_default();
        let mt = n.mapa("marco_teorico").cloned().unwrap_or_default();
        let herr = n.mapa("herramientas").cloned().unwrap_or_default();
        let de = |seccion: &str, k: &str| herr.mapa(seccion).map(|m| t(m, k)).unwrap_or_default();
        let carpeta = py::join(&py::join(&self.carpeta, "aprendizaje"), id);
        py::makedirs(&carpeta)?;
        let ejercicio = py::join(&carpeta, "ejercicio.py");
        let prueba = py::join(&carpeta, "test_ejercicio.py");
        let teoria = py::join(&carpeta, "MARCO_TEORICO.md");
        let solucion = py::join(&carpeta, "SOLUCION_PRE_RESPONDIDA.md");
        let titulo = t(n, "titulo");
        let nivel = t(n, "nivel");
        if !Path::new(&ejercicio).exists() {
            py::escribir_texto(
                &ejercicio,
                &format!(
                    "# PRIG IDE - NODO: {titulo} ({})\n# Carrera de Referencia: {}\n\n\"\"\"\n{}\n\"\"\"\n\n{}\n",
                    nivel.to_uppercase(),
                    t(n, "carrera_referencia"),
                    t(&tarea, "enunciado"),
                    t(&tarea, "codigo_inicial")
                ),
            )?;
        }
        py::escribir_texto(
            &prueba,
            &format!(
                "# Pruebas Automatizadas para: {titulo}\nfrom ejercicio import *\n\n{}\n\nif __name__ == '__main__':\n    \
                 test_funcs = [v for k, v in list(globals().items()) if k.startswith('test_') and callable(v)]\n    \
                 for tf in test_funcs:\n        tf()\n    print('✓ Todas las pruebas unitarias pasaron correctamente.')\n",
                t(&tarea, "pruebas_unitarias")
            ),
        )?;
        let principios = py::unir("\n", &Valor::Lista(mt.lista("principios_nucleares").unwrap_or(&[]).iter().map(|p| Valor::Texto(format!("- {}", p.texto_py()))).collect()))?;
        py::escribir_texto(
            &teoria,
            &format!(
                "# Marco Teórico: {titulo}\n\n> **Nivel:** {} | **Etapa:** {}\n\n## 📚 Resumen Conceptual\n{}\n\n\
                 ## ⚙️ Principios Nucleares\n{principios}\n\n## 📐 Fórmulas y Fundamento Formal\n{}\n\n\
                 ## 🎥 Recursos Audiovisuales (YouTube)\n- **Video:** {}\n- **Canal:** {}\n\n\
                 ## 🐙 Repositorios Relacionados (GitHub)\n- **Repo:** {}\n\n\
                 ## 📊 Datasets Prácticos (Kaggle)\n- **Dataset:** {}\n",
                capitalizar(&nivel),
                t(n, "etapa"),
                t(&mt, "resumen"),
                t(&mt, "formulas_o_axiomas"),
                de("youtube", "titulo"),
                de("youtube", "canal"),
                de("github", "repositorio"),
                de("kaggle", "dataset_slug")
            ),
        )?;
        let guia: Vec<String> = tarea
            .lista("guia_resolucion_paso_a_paso")
            .unwrap_or(&[])
            .iter()
            .enumerate()
            .map(|(i, g)| format!("{}. {}", i + 1, g.texto_py()))
            .collect();
        py::escribir_texto(
            &solucion,
            &format!(
                "# Solución Pre-respondida de Referencia: {titulo}\n\n```python\n{}\n```\n\n## 🧭 Guía de Resolución Paso a Paso\n{}\n",
                t(&tarea, "solucion_referencia"),
                guia.join("\n")
            ),
        )?;
        Ok(Mapa::new()
            .con("ok", true)
            .con("nodo_id", id)
            .con("carpeta", carpeta)
            .con("archivo_principal", py::relpath(&ejercicio, &self.carpeta))
            .con("archivo_test", py::relpath(&prueba, &self.carpeta)))
    }

    /// `prog[nodo_id]`, creándolo con `nuevo` si no está (`if nodo_id not in prog: prog[nodo_id] = nuevo`)
    fn entrada<'a>(prog: &'a mut Valor, id: &str, nuevo: Mapa) -> R<&'a mut Valor> {
        if !py::contiene(prog, id)? {
            py::poner_py(prog, id, Valor::Mapa(nuevo)).map_err(|e| e.texto())?;
        }
        match prog {
            Valor::Mapa(m) => Ok(m.get_mut(id).expect("recién puesta")),
            // `in` de una lista o un texto sin asignación posible: la asignación de arriba ya falló
            Valor::Lista(_) => Err("list indices must be integers or slices, not str".into()),
            _ => Err("string indices must be integers, not 'str'".into()),
        }
    }

    /// `marcar_progreso(nodo_id, completado, resultado)`
    pub fn marcar(&self, id: &str, completado: bool, resultado: Option<&Mapa>) -> R<()> {
        let mut prog = self.leer_progreso();
        let e = Self::entrada(&mut prog, id, Mapa::new().con("intentos", 0))?;
        py::poner_py(e, "completado", Valor::Bool(completado)).map_err(|e| e.texto())?;
        py::poner_py(e, "fecha", Valor::Texto(ahora())).map_err(|e| e.texto())?;
        if let Some(r) = resultado.filter(|r| !r.is_empty()) {
            py::poner_py(e, "ultimo_resultado", Valor::Mapa(r.clone())).map_err(|e| e.texto())?;
        }
        self.guardar_progreso(&prog);
        Ok(())
    }

    fn sumar_intento(&self, id: &str) -> R<()> {
        let mut prog = self.leer_progreso();
        let e = Self::entrada(&mut prog, id, Mapa::new().con("intentos", 0).con("completado", false))?;
        let n = get(e, "intentos", Valor::Entero(0))?;
        let mas = match n {
            Valor::Entero(n) => Valor::Entero(n + 1),
            Valor::Bool(b) => Valor::Entero(b as i128 + 1),
            Valor::Real(x) => Valor::Real(x + 1.0),
            Valor::Texto(_) => return Err("can only concatenate str (not \"int\") to str".into()),
            Valor::Lista(_) => return Err("can only concatenate list (not \"int\") to list".into()),
            otro => return Err(format!("unsupported operand type(s) for +: '{}' and 'int'", py::tipo(&otro))),
        };
        py::poner_py(e, "intentos", mas).map_err(|e| e.texto())?;
        self.guardar_progreso(&prog);
        Ok(())
    }

    /// `obtener_estadisticas_progreso()`
    pub fn estadisticas(&self) -> R<Valor> {
        self.estadisticas_de(&self.leer_progreso())
    }

    fn estadisticas_de(&self, prog: &Valor) -> R<Valor> {
        let Valor::Mapa(m) = prog else { return Err(format!("'{}' object has no attribute 'values'", py::tipo(prog))) };
        let total = DATOS.nodos.len() as i128;
        let mut completados = 0i128;
        for (_, v) in m.iter() {
            if get(v, "completado", Valor::Bool(false))?.verdad() {
                completados += 1;
            }
        }
        let pct = |c: i128, t: i128| prig_recursos::valor::redondear(c as f64 / t.max(1) as f64 * 100.0, 1);
        let mut por_nivel = [(0i128, 0i128); 4];
        for n in &DATOS.nodos {
            let nivel = t(n, "nivel");
            if let Some(i) = NIVELES.iter().position(|x| *x == nivel) {
                por_nivel[i].1 += 1;
                if get(&get(prog, &t(n, "id"), vacio())?, "completado", Valor::Bool(false))?.verdad() {
                    por_nivel[i].0 += 1;
                }
            }
        }
        let mut niveles = Mapa::new();
        for (i, (c, tot)) in por_nivel.iter().enumerate() {
            niveles.poner(NIVELES[i], Mapa::new().con("completados", *c).con("total", *tot).con("pct", pct(*c, *tot)));
        }
        Ok(Valor::Mapa(
            Mapa::new()
                .con("total_nodos", total)
                .con("completados", completados)
                .con("porcentaje", pct(completados, total))
                .con("niveles", niveles),
        ))
    }
}

/// `time.strftime("%Y-%m-%d %H:%M:%S")`
fn ahora() -> String {
    // SAFETY: localtime_r escribe en la estructura que se le da
    unsafe {
        let s = libc::time(std::ptr::null_mut());
        let mut tm: libc::tm = std::mem::zeroed();
        libc::localtime_r(&s, &mut tm);
        format!(
            "{:04}-{:02}-{:02} {:02}:{:02}:{:02}",
            tm.tm_year + 1900,
            tm.tm_mon + 1,
            tm.tm_mday,
            tm.tm_hour,
            tm.tm_min,
            tm.tm_sec
        )
    }
}

/// `tempfile.NamedTemporaryFile("w", suffix=".py", delete=False)`: tmpXXXXXXXX.py en la carpeta temporal
fn temporal(texto: &str) -> R<String> {
    let dir = std::env::temp_dir();
    for _ in 0..100 {
        let nombre: String = uuid::Uuid::new_v4().simple().to_string().chars().take(8).collect();
        let ruta = dir.join(format!("tmp{nombre}.py"));
        match std::fs::OpenOptions::new().write(true).create_new(true).open(&ruta) {
            Ok(mut f) => {
                f.write_all(texto.as_bytes()).map_err(|e| py::error_os(&e, &ruta.to_string_lossy()))?;
                return Ok(ruta.to_string_lossy().into_owned());
            }
            Err(e) if e.kind() == std::io::ErrorKind::AlreadyExists => continue,
            Err(e) => return Err(py::error_os(&e, &ruta.to_string_lossy())),
        }
    }
    Err("No usable temporary file name found".into())
}

/// `subprocess.run(["python3", ruta], capture_output=True, text=True, timeout=4.0)`: None si se agota el tiempo
#[allow(clippy::type_complexity)]
fn correr(ruta: &str) -> R<Option<(Option<i32>, String, String)>> {
    let mut hijo = Command::new("python3")
        .arg(ruta)
        .stdin(Stdio::inherit())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .map_err(|e| py::error_os(&e, "python3"))?;
    let leer = |mut r: Box<dyn Read + Send>| {
        std::thread::spawn(move || {
            let mut b = Vec::new();
            let _ = r.read_to_end(&mut b);
            b
        })
    };
    let salida = leer(Box::new(hijo.stdout.take().expect("stdout")));
    let errores = leer(Box::new(hijo.stderr.take().expect("stderr")));
    let limite = Instant::now() + Duration::from_secs(4);
    let estado = loop {
        match hijo.try_wait() {
            Ok(Some(e)) => break e,
            Ok(None) if Instant::now() >= limite => {
                let _ = hijo.kill();
                let _ = hijo.wait();
                return Ok(None);
            }
            Ok(None) => std::thread::sleep(Duration::from_millis(5)),
            Err(e) => return Err(e.to_string()),
        }
    };
    let texto = |b: Vec<u8>| String::from_utf8_lossy(&b).replace("\r\n", "\n").replace('\r', "\n");
    let salida = texto(salida.join().unwrap_or_default());
    let errores = texto(errores.join().unwrap_or_default());
    Ok(Some((estado.code(), salida, errores)))
}

#[cfg(test)]
mod pruebas {
    use super::*;

    fn tmp() -> String {
        let d = std::env::temp_dir().join(format!("prig-grafo-{}", uuid::Uuid::new_v4().simple()));
        std::fs::create_dir_all(&d).unwrap();
        d.to_string_lossy().into_owned()
    }

    #[test]
    fn el_grafo_es_consistente_y_cubre_los_niveles() {
        assert!(DATOS.nodos.len() >= 4);
        assert_eq!(DATOS.nodos.len(), DATOS.indice.len());
        for n in &DATOS.nodos {
            for k in ["prerrequisitos", "siguientes"] {
                for x in n.lista(k).unwrap() {
                    assert!(nodo(&x.texto_py()).is_some(), "{} en {}", x.texto_py(), t(n, "id"));
                }
            }
            let h = n.mapa("herramientas").unwrap();
            for k in ["youtube", "github", "kaggle", "prig_hub"] {
                assert!(h.contiene(k), "{} sin {k}", t(n, "id"));
            }
        }
        for nivel in NIVELES {
            assert!(DATOS.nodos.iter().any(|n| t(n, "nivel") == nivel));
        }
    }

    #[test]
    fn buscar_ordena_por_puntos() {
        let m = Motor::en(&tmp());
        assert!(m.buscar("transformers atencion", 5).iter().any(|n| t(n, "id").contains("deep-learning")));
        assert!(!m.buscar("titanic pandas", 5).is_empty());
        assert_eq!(m.buscar("  ", -2).len(), DATOS.nodos.len() - 2);
    }

    #[test]
    fn el_progreso_se_guarda_y_cuenta() {
        let d = tmp();
        let m = Motor::en(&d);
        m.marcar("nodo-py-01-fundamentos-sintaxis", true, None).unwrap();
        m.sumar_intento("nodo-py-01-fundamentos-sintaxis").unwrap();
        let n = m.nodo("nodo-py-01-fundamentos-sintaxis").unwrap().unwrap();
        assert_eq!(n.valor("completado"), &Valor::Bool(true));
        assert_eq!(n.valor("intentos"), &Valor::Entero(1));
        let e = m.estadisticas().unwrap();
        let Valor::Mapa(e) = e else { panic!() };
        assert_eq!(e.valor("completados"), &Valor::Entero(1));
        std::fs::write(py::join(&d, ".prig_aprendizaje_progreso.json"), "[1]").unwrap();
        assert_eq!(m.estadisticas().unwrap_err(), "'list' object has no attribute 'values'");
        assert_eq!(m.marcar("x", true, None).unwrap_err(), "list indices must be integers or slices, not str");
    }

    #[test]
    fn abrir_en_editor_crea_los_archivos() {
        let d = tmp();
        let r = Motor::en(&d).abrir_en_editor("nodo-py-01-fundamentos-sintaxis").unwrap();
        assert_eq!(r.texto("archivo_principal"), Some("aprendizaje/nodo-py-01-fundamentos-sintaxis/ejercicio.py"));
        for f in ["ejercicio.py", "test_ejercicio.py", "MARCO_TEORICO.md", "SOLUCION_PRE_RESPONDIDA.md"] {
            assert!(Path::new(&d).join("aprendizaje/nodo-py-01-fundamentos-sintaxis").join(f).is_file());
        }
    }
}
