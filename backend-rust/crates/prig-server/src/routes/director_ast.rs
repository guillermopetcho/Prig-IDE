//! El analizador del director de LLM (`AnalizadorSintacticoAST` de `llm_director.py`): los símbolos, dependencias,
//! puntos críticos, pasos del grafo de flujo y la complejidad de un archivo. Python va por su árbol (el de
//! `banco_core::pyast`, con la forma del módulo `ast` de CPython); los demás lenguajes y el Python que no se puede
//! analizar, por un recorrido de líneas.

use banco_core::py::cadena::{primeros, splitlines};
use banco_core::pyast::unparse::unparse;
use banco_core::pyast::{Arbol, Id, K};
use prig_plataforma::py;
use prig_plataforma::valor::{Mapa, Valor};
use prig_recursos::valor::redondear;

/// `analizar_codigo(archivo, codigo, lenguaje)`
pub fn analizar(codigo: &str, lenguaje: &str) -> Mapa {
    if codigo.is_empty() {
        return Mapa::new()
            .con("simbolos", Valor::Lista(vec![]))
            .con("dependencias", Valor::Lista(vec![]))
            .con("puntos_criticos", Valor::Lista(vec![]))
            .con("pasos_cfg", Valor::Lista(vec![]))
            .con("complejidad_max", 1)
            .con("calidad_score", 90);
    }
    if lenguaje.to_lowercase() == "python" {
        if let Some(m) = Arbol::con_arbol(codigo, |a| python(a, codigo)) {
            return m;
        }
    }
    generico(codigo)
}

fn lista(v: Vec<Mapa>) -> Valor {
    Valor::Lista(v.into_iter().map(Valor::Mapa).collect())
}

fn textos(v: Vec<String>) -> Valor {
    Valor::Lista(v.into_iter().map(Valor::Texto).collect())
}

/// `round(min(0.85, max(0.15, (linea / max(1, total)) * 0.7 + 0.15)), 2)`
fn foco(linea: i128, total: i128) -> f64 {
    redondear((linea as f64 / total.max(1) as f64 * 0.7 + 0.15).clamp(0.15, 0.85), 2)
}

fn agente(x: f64, y: f64) -> Mapa {
    Mapa::new().con("x_ratio", x).con("y_ratio", y)
}

#[allow(clippy::too_many_arguments)]
fn paso(n: i128, etiqueta: String, tipo: &str, icono: &str, ini: i128, fin: i128, y: f64, pos: (f64, f64), expl: String, sug: String) -> Mapa {
    Mapa::new()
        .con("paso", n)
        .con("etiqueta", etiqueta)
        .con("tipo", tipo)
        .con("icono", icono)
        .con("linea_inicio", ini)
        .con("linea_fin", fin)
        .con("x_foco", 0.35)
        .con("y_foco", y)
        .con("posicion_agente", agente(pos.0, pos.1))
        .con("explicacion", expl)
        .con("sugerencia", sug)
}

/// `_analizar_python_ast`
fn python(a: &Arbol, codigo: &str) -> Mapa {
    let total = splitlines(codigo).len() as i128;
    let mut dependencias: Vec<String> = Vec::new();
    let todos = a.recorrer(a.modulo);
    let anadir = |d: String, deps: &mut Vec<String>| {
        if !deps.contains(&d) {
            deps.push(d);
        }
    };
    for &n in &todos {
        match a.k(n) {
            K::Import { names } => {
                for &al in names {
                    if let K::Alias { name, .. } = a.k(al) {
                        anadir(name.clone(), &mut dependencias);
                    }
                }
            }
            K::ImportFrom { module, names, .. } => {
                let m = module.clone().unwrap_or_default();
                for &al in names {
                    if let K::Alias { name, .. } = a.k(al) {
                        anadir(if m.is_empty() { name.clone() } else { format!("{m}.{name}") }, &mut dependencias);
                    }
                }
            }
            _ => {}
        }
    }
    let mut simbolos: Vec<Mapa> = Vec::new();
    let mut pasos: Vec<Mapa> = Vec::new();
    let mut complejidad_max: i128 = 1;
    let mut funcion = |f: Id, padre: &str, simbolos: &mut Vec<Mapa>, pasos: &mut Vec<Mapa>| {
        let K::FunctionDef { is_async, name, args, returns, .. } = a.k(f) else { return };
        let mut comp: i128 = 1;
        for s in a.recorrer(f) {
            match a.k(s) {
                K::If { .. } | K::While { .. } | K::ExceptHandler { .. } | K::Assert { .. } => comp += 1,
                K::For { is_async: false, .. } | K::With { is_async: false, .. } => comp += 1,
                K::BoolOp { values, .. } => comp += values.len() as i128 - 1,
                _ => {}
            }
        }
        complejidad_max = complejidad_max.max(comp);
        let mut lista_args = Vec::new();
        if let K::Arguments { args, .. } = a.k(*args) {
            for &x in args {
                if let K::Arg { arg, annotation } = a.k(x) {
                    lista_args.push(match annotation {
                        Some(t) => format!("{arg}: {}", unparse(a, *t)),
                        None => arg.clone(),
                    });
                }
            }
        }
        let retorno = returns.map(|r| format!(" -> {}", unparse(a, r))).unwrap_or_default();
        let firma = format!("{}def {name}({}){retorno}:", if *is_async { "async " } else { "" }, lista_args.join(", "));
        simbolos.push(
            Mapa::new()
                .con("tipo", if padre.is_empty() { "funcion" } else { "metodo" })
                .con("nombre", name.as_str())
                .con("clase_padre", padre)
                .con("firma", firma)
                .con("linea_inicio", a.linea(f) as i128)
                .con("linea_fin", a.linea_fin(f) as i128)
                .con("complejidad", if comp > 2 { "O(N)" } else { "O(1)" })
                .con("ciclomatica", comp),
        );
        pasos.extend(cfg(a, f, total));
    };
    let K::Module { body } = a.k(a.modulo) else { return generico(codigo) };
    for &n in body {
        match a.k(n) {
            K::FunctionDef { .. } => funcion(n, "", &mut simbolos, &mut pasos),
            K::ClassDef { name, bases, body, .. } => {
                let bases: Vec<String> = bases.iter().map(|b| unparse(a, *b)).collect();
                simbolos.push(
                    Mapa::new()
                        .con("tipo", "clase")
                        .con("nombre", name.as_str())
                        .con("firma", format!("class {name}({}):", bases.join(", ")))
                        .con("linea_inicio", a.linea(n) as i128)
                        .con("linea_fin", a.linea_fin(n) as i128)
                        .con("bases", textos(bases)),
                );
                for &m in body {
                    if matches!(a.k(m), K::FunctionDef { .. }) {
                        funcion(m, name, &mut simbolos, &mut pasos);
                    }
                }
            }
            _ => {}
        }
    }
    let mut criticos = Vec::new();
    for &n in &todos {
        let l = a.linea(n);
        match a.k(n) {
            K::For { is_async: false, .. } => criticos.push(format!("L{l}: Iteración For")),
            K::While { .. } => criticos.push(format!("L{l}: Iteración While")),
            K::Try { is_star: false, .. } => criticos.push(format!("L{l}: Manejo de Excepciones")),
            K::Await { .. } => criticos.push(format!("L{l}: Llamada Asíncrona (Await)")),
            _ => {}
        }
    }
    let calidad = (100 - (complejidad_max - 1) * 3).clamp(70, 99);
    simbolos.truncate(25);
    dependencias.truncate(15);
    criticos.truncate(15);
    pasos.truncate(6);
    Mapa::new()
        .con("simbolos", lista(simbolos))
        .con("dependencias", textos(dependencias))
        .con("puntos_criticos", textos(criticos))
        .con("pasos_cfg", lista(pasos))
        .con("complejidad_max", complejidad_max)
        .con("calidad_score", calidad)
}

/// `_construir_cfg_funcion`: la entrada y, del cuerpo, guardas, bucles, try y retornos (hasta el paso 4)
fn cfg(a: &Arbol, f: Id, total: i128) -> Vec<Mapa> {
    let K::FunctionDef { name, body, .. } = a.k(f) else { return vec![] };
    let ini = a.linea(f) as i128;
    let mut pasos = vec![paso(
        1,
        format!("Entrada [{name}]"),
        "entrada",
        "📥",
        ini,
        total.min(ini + 1),
        foco(ini, total),
        (0.88, 0.88),
        format!("Invocación de '{name}' con resolución de parámetros y tipos."),
        format!("def {name}(...)"),
    )];
    let mut orden: i128 = 2;
    for &item in body {
        let (l, lf) = (a.linea(item) as i128, a.linea_fin(item) as i128);
        let y = foco(l, total);
        let nuevo = match a.k(item) {
            K::If { body, .. } => {
                let guarda = body.iter().any(|s| matches!(a.k(*s), K::Return { .. } | K::Raise { .. }));
                Some(paso(
                    orden,
                    (if guarda { "Cláusula de Guarda" } else { "Bifurcación Condicional" }).into(),
                    "guarda",
                    "🛡️",
                    l,
                    lf,
                    y,
                    (0.85, 0.80),
                    "Validación temprana de invariantes para evitar fallos en tiempo de ejecución.".into(),
                    "if not valid: return None".into(),
                ))
            }
            K::For { is_async: false, .. } | K::While { .. } => Some(paso(
                orden,
                "Bucle de Procesamiento".into(),
                "proceso",
                "⚡",
                l,
                lf,
                y,
                (0.82, 0.74),
                "Iteración de colección de datos con optimización temporal O(N).".into(),
                "lookup_table = {k: v for k, v in items}".into(),
            )),
            K::Try { is_star: false, .. } => Some(paso(
                orden,
                "Bloque Resiliente Try/Except".into(),
                "seguridad",
                "🛡️",
                l,
                lf,
                y,
                (0.84, 0.78),
                "Captura granular de excepciones para asegurar estabilidad operativa.".into(),
                "except SpecificError as err: logger.error(err)".into(),
            )),
            K::Return { .. } => Some(paso(
                orden,
                "Emisión & Retorno".into(),
                "salida",
                "📤",
                l,
                lf,
                y,
                (0.88, 0.88),
                "Retorno determinista del estado inmutable procesado.".into(),
                "return result".into(),
            )),
            _ => None,
        };
        if let Some(p) = nuevo {
            pasos.push(p);
            orden += 1;
        }
        if orden > 4 {
            break;
        }
    }
    if pasos.len() == 1 {
        let fin = a.linea_fin(f) as i128;
        pasos.push(paso(
            2,
            "Salida de Función".into(),
            "salida",
            "📤",
            fin,
            fin,
            foco(fin, total),
            (0.88, 0.88),
            "Finalización de ejecución y liberación de pila de llamadas.".into(),
            "return final_value".into(),
        ));
    }
    pasos
}

/// `_analizar_generico_bloques`: declaraciones e imports reconocidos línea a línea
fn generico(codigo: &str) -> Mapa {
    let lineas = splitlines(codigo);
    let total = lineas.len() as i128;
    let mut simbolos: Vec<Mapa> = Vec::new();
    let mut dependencias: Vec<String> = Vec::new();
    let mut criticos: Vec<String> = Vec::new();
    for (i, l) in lineas.iter().enumerate() {
        let s = py::strip(l);
        let decl = if let Some(r) = s.strip_prefix("export default ") {
            py::strip(r)
        } else if let Some(r) = s.strip_prefix("export ") {
            py::strip(r)
        } else {
            s
        };
        let n = i as i128 + 1;
        let flecha = (decl.contains("=>") || decl.contains("= function") || decl.contains("= async"))
            && (decl.contains("const ") || decl.contains("let ") || decl.contains("var "));
        let estandar = ["function ", "async function ", "fn ", "def "].iter().any(|p| decl.starts_with(p));
        if estandar || flecha {
            let mut nombre = decl.split('=').next().unwrap_or("").split('(').next().unwrap_or("").to_string();
            for q in ["function ", "async ", "const ", "let ", "var ", "fn ", "def "] {
                nombre = nombre.replace(q, "");
            }
            let mut nombre = py::strip(&nombre).to_string();
            if nombre.contains(' ') {
                nombre = nombre.rsplit(' ').next().unwrap_or("").to_string();
            }
            simbolos.push(
                Mapa::new()
                    .con("tipo", "funcion")
                    .con("nombre", nombre)
                    .con("firma", primeros(s, 60))
                    .con("linea_inicio", n)
                    .con("linea_fin", total.min(n + 4)),
            );
        } else if decl.starts_with("class ") || decl.starts_with("interface ") || decl.starts_with("struct ") {
            let nombre = decl.split('{').next().unwrap_or("").split("extends").next().unwrap_or("").split("implements").next().unwrap_or("");
            let nombre = nombre.replace("class ", "").replace("interface ", "").replace("struct ", "");
            simbolos.push(
                Mapa::new()
                    .con("tipo", "clase")
                    .con("nombre", py::strip(&nombre))
                    .con("firma", primeros(s, 60))
                    .con("linea_inicio", n)
                    .con("linea_fin", total.min(n + 6)),
            );
        } else if s.starts_with("import ") || s.contains("require(") || s.starts_with("use ") {
            let dep = s.rsplit("from").next().unwrap_or("").replace(['\'', '"', ';'], "");
            let dep = py::strip(&dep).to_string();
            if dep.chars().count() < 50 && !dependencias.contains(&dep) {
                dependencias.push(dep);
            }
        }
        if s.contains("for ") || s.contains("while ") {
            criticos.push(format!("L{n}: Bucle de Iteración"));
        } else if s.contains("try {") || s.contains("catch") {
            criticos.push(format!("L{n}: Manejo de Errores"));
        } else if s.contains("await ") || s.contains("Promise") {
            criticos.push(format!("L{n}: Concurrencia / Asincronía"));
        }
    }
    let primero = simbolos.first();
    let (nombre0, ini0) = match primero {
        Some(p) => (p.valor("nombre").texto_py(), p.valor("linea_inicio").entero().unwrap_or(1)),
        None => ("Módulo".to_string(), 1),
    };
    let pasos = vec![
        paso(
            1,
            format!("Entrada [{nombre0}]"),
            "entrada",
            "📥",
            ini0,
            ini0 + 1,
            0.22,
            (0.88, 0.88),
            "Entrada y validación de tipos en la firma del módulo.".into(),
            "Validar argumentos".into(),
        ),
        paso(
            2,
            "Transformación Central".into(),
            "proceso",
            "⚡",
            (total / 2).max(1),
            total.min(total / 2 + 2),
            0.48,
            (0.82, 0.76),
            "Cómputo principal de datos y orquestación de funciones.".into(),
            "Optimizar estructura".into(),
        ),
    ];
    simbolos.truncate(20);
    dependencias.truncate(10);
    criticos.truncate(10);
    Mapa::new()
        .con("simbolos", lista(simbolos))
        .con("dependencias", textos(dependencias))
        .con("puntos_criticos", textos(criticos))
        .con("pasos_cfg", lista(pasos))
        .con("complejidad_max", 2)
        .con("calidad_score", 93)
}

#[cfg(test)]
mod pruebas {
    use super::*;

    #[test]
    fn analiza_python_como_ast() {
        let c = "import os\nfrom a import b\n\nclass C(Base):\n    def m(self, x: int) -> str:\n        if x and y or z:\n            return 1\n        for i in x:\n            pass\n\nasync def f(a: Dict[str, int]):\n    await g()\n";
        let r = analizar(c, "Python");
        assert_eq!(r.valor("dependencias"), &textos(vec!["os".into(), "a.b".into()]));
        let s = r.lista("simbolos").unwrap();
        assert_eq!(s.len(), 3);
        let firma = |i: usize| if let Valor::Mapa(m) = &s[i] { m.valor("firma").texto_py() } else { String::new() };
        assert_eq!(firma(0), "class C(Base):");
        assert_eq!(firma(1), "def m(self, x: int) -> str:");
        assert_eq!(firma(2), "async def f(a: Dict[str, int]):");
        assert_eq!(r.valor("complejidad_max"), &Valor::Entero(5));
        assert_eq!(r.valor("puntos_criticos"), &textos(vec!["L8: Iteración For".into(), "L12: Llamada Asíncrona (Await)".into()]));
    }

    #[test]
    fn lo_que_no_es_python_va_por_lineas() {
        let r = analizar("export const suma = (a, b) => a + b;\nclass Caja extends X {\nimport x from 'y';\n", "javascript");
        let s = r.lista("simbolos").unwrap();
        assert_eq!(s.len(), 2);
        assert_eq!(r.valor("dependencias"), &textos(vec!["y".into()]));
        assert_eq!(analizar("def roto(:\n", "python").valor("complejidad_max"), &Valor::Entero(2));
    }
}
