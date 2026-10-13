//! Extracción de Python (banco_proyecto.py: alias_python, simbolos_python, hechos_python): símbolos con
//! firma, docstring y líneas; las llamadas de cada uno con su receptor; los alias de import; los módulos
//! importados y los hechos (hereda, expone, lanza, captura, lee_entorno, lee_config, ejecuta, atributo).

use std::collections::{HashMap, HashSet};
use std::sync::LazyLock;

use super::{dentro, ruta_http_canonica, Hecho, Simbolo, Uso, ES_TEST};
use crate::py::cadena::{primeros, upper};
use crate::pyast::unparse::unparse;
use crate::pyast::{Arbol, Constante, Ctx, Id, K};
use crate::re::Re;

/// `alias_python`: (alias, ruta con puntos) de cada import, en el orden de `ast.walk`.
pub fn alias_python(texto: &str) -> Vec<(String, String)> {
    Arbol::con_arbol(texto, alias_de).unwrap_or_default()
}

pub fn alias_de(a: &Arbol) -> Vec<(String, String)> {
    let mut salida = vec![];
    for n in a.recorrer(a.modulo) {
        match a.k(n) {
            K::Import { names } => {
                for al in names {
                    if let K::Alias { name, asname } = a.k(*al) {
                        match asname {
                            Some(asn) => salida.push((asn.clone(), name.clone())),
                            None => {
                                let primero = name.split('.').next().unwrap_or("").to_string();
                                salida.push((primero.clone(), primero));
                            }
                        }
                    }
                }
            }
            K::ImportFrom { module, names, level } => {
                let base = format!("{}{}", ".".repeat(*level as usize), module.clone().unwrap_or_default());
                for al in names {
                    if let K::Alias { name, asname } = a.k(*al) {
                        if name != "*" {
                            let destino = if module.is_some() { format!("{base}.{name}") } else { format!("{base}{name}") };
                            salida.push((asname.clone().unwrap_or_else(|| name.clone()), destino));
                        }
                    }
                }
            }
            _ => {}
        }
    }
    salida
}

/// `_definiciones_directas`: las definiciones de este cuerpo y las de dentro de if/with/try/for (campos
/// body, orelse, finalbody y handlers, en ese orden), sin entrar en otras funciones o clases.
fn definiciones_directas(a: &Arbol, cuerpo: &[Id], salida: &mut Vec<Id>) {
    for &n in cuerpo {
        if a.es_def(n) {
            salida.push(n);
            continue;
        }
        let (body, orelse, finalbody, handlers): (&[Id], &[Id], &[Id], &[Id]) = match a.k(n) {
            K::For { body, orelse, .. } | K::While { body, orelse, .. } | K::If { body, orelse, .. } => (body, orelse, &[], &[]),
            K::With { body, .. } => (body, &[], &[], &[]),
            K::Try { body, handlers, orelse, finalbody, .. } => (body, orelse, finalbody, handlers),
            K::ExceptHandler { body, .. } => (body, &[], &[], &[]),
            _ => (&[], &[], &[], &[]),
        };
        definiciones_directas(a, body, salida);
        definiciones_directas(a, orelse, salida);
        definiciones_directas(a, finalbody, salida);
        definiciones_directas(a, handlers, salida);
    }
}

/// `_recorrer_sin_anidadas`: el nodo y lo de adentro, sin entrar en funciones, clases ni lambdas anidadas.
fn recorrer_sin_anidadas(a: &Arbol, nodo: Id) -> Vec<Id> {
    let mut salida = vec![];
    let mut pendientes = vec![nodo];
    while let Some(n) = pendientes.pop() {
        salida.push(n);
        for h in a.hijos(n) {
            if !matches!(a.k(h), K::FunctionDef { .. } | K::ClassDef { .. } | K::Lambda { .. }) {
                pendientes.push(h);
            }
        }
    }
    salida
}

/// Las llamadas de una función: (nombre, línea de la primera, receptor), ordenadas como tuplas de Python.
fn llamadas(a: &Arbol, nodo: Id) -> Vec<Uso> {
    let mut primeras: HashMap<(String, String), u32> = HashMap::new();
    for n in recorrer_sin_anidadas(a, nodo) {
        if let K::Call { func, .. } = a.k(n) {
            let clave = match a.k(*func) {
                K::Name { id, .. } => (id.clone(), String::new()),
                K::Attribute { value, attr, .. } => (attr.clone(), primeros(&unparse(a, *value), 80).to_string()),
                _ => continue,
            };
            let linea = a.linea(n);
            let e = primeras.entry(clave).or_insert(linea);
            if linea < *e {
                *e = linea;
            }
        }
    }
    let mut salida: Vec<Uso> = primeras.into_iter().map(|((nombre, receptor), linea)| Uso { nombre, linea: linea as i64, receptor: Some(receptor) }).collect();
    salida.sort_by(|x, y| (&x.nombre, x.linea, &x.receptor).cmp(&(&y.nombre, y.linea, &y.receptor)));
    salida
}

fn firma(a: &Arbol, nodo: Id) -> String {
    match a.k(nodo) {
        K::ClassDef { name, bases, .. } => {
            if bases.is_empty() {
                format!("class {name}")
            } else {
                let b: Vec<String> = bases.iter().map(|b| unparse(a, *b)).collect();
                format!("class {name}({})", b.join(", "))
            }
        }
        K::FunctionDef { is_async, name, args, returns, .. } => {
            let argumentos = unparse(a, *args);
            let ret = match returns {
                Some(r) => format!(" -> {}", unparse(a, *r)),
                None => String::new(),
            };
            let pre = if *is_async { "async def" } else { "def" };
            format!("{pre} {name}({argumentos}){ret}")
        }
        _ => String::new(),
    }
}

/// `simbolos_python`: (símbolos, módulos importados, docstring del módulo).
pub fn simbolos_python(texto: &str) -> (Vec<Simbolo>, Vec<String>, String) {
    Arbol::con_arbol(texto, simbolos_de).unwrap_or_default()
}

pub fn simbolos_de(a: &Arbol) -> (Vec<Simbolo>, Vec<String>, String) {
    let mut simbolos = vec![];
    let K::Module { body } = a.k(a.modulo) else { return (vec![], vec![], String::new()) };
    visitar(a, body, "", false, &mut simbolos);
    let mut importados = vec![];
    for n in a.recorrer(a.modulo) {
        match a.k(n) {
            K::Import { names } => {
                for al in names {
                    if let K::Alias { name, .. } = a.k(*al) {
                        importados.push(name.clone());
                    }
                }
            }
            K::ImportFrom { module, names, level } => {
                let modulo = format!("{}{}", ".".repeat(*level as usize), module.clone().unwrap_or_default());
                importados.push(modulo.clone());
                for al in names {
                    if let K::Alias { name, .. } = a.k(*al) {
                        if !modulo.trim_matches('.').is_empty() {
                            importados.push(format!("{modulo}.{name}"));
                        } else {
                            importados.push(format!("{}{}", ".".repeat(*level as usize), name));
                        }
                    }
                }
            }
            _ => {}
        }
    }
    (simbolos, importados, a.docstring(a.modulo).unwrap_or_default())
}

fn visitar(a: &Arbol, cuerpo: &[Id], padre: &str, padre_es_funcion: bool, simbolos: &mut Vec<Simbolo>) {
    let mut defs = vec![];
    definiciones_directas(a, cuerpo, &mut defs);
    for nodo in defs {
        let (nombre_corto, decorators, body, es_clase) = match a.k(nodo) {
            K::FunctionDef { name, decorators, body, .. } => (name, decorators, body, false),
            K::ClassDef { name, decorators, body, .. } => (name, decorators, body, true),
            _ => continue,
        };
        let mut ini = a.linea(nodo);
        for d in decorators {
            ini = ini.min(a.linea(*d));
        }
        let nombre = if padre.is_empty() { nombre_corto.clone() } else { format!("{padre}.{nombre_corto}") };
        let tipo = if es_clase {
            "clase"
        } else if padre_es_funcion {
            "anidada"
        } else if !padre.is_empty() {
            "metodo"
        } else {
            "funcion"
        };
        let doc = a.docstring(nodo).unwrap_or_default();
        simbolos.push(Simbolo {
            nombre: nombre.clone(),
            corto: nombre_corto.clone(),
            tipo: tipo.to_string(),
            firma: firma(a, nodo),
            doc: primeros(&doc, 600).to_string(),
            ini: ini as i64,
            fin: a.linea_fin(nodo) as i64,
            padre: padre.to_string(),
            usos: if tipo == "clase" { vec![] } else { llamadas(a, nodo) },
        });
        visitar(a, body, &nombre, !es_clase, simbolos);
    }
}

static ES_CONFIG: LazyLock<Re> = LazyLock::new(|| Re::nuevo(r"(^|\.)(config|cfg|configuracion|ajustes|settings)$", "i"));
const ROUTERS: [&str; 2] = ["APIRouter", "Blueprint"];
const METODOS_HTTP: [&str; 8] = ["get", "post", "put", "delete", "patch", "websocket", "route", "api_route"];
const SUBPROCESO: [&str; 5] = ["run", "Popen", "check_output", "check_call", "call"];

/// `hechos_python`: los hechos del grafo, en el orden de `ast.walk` y sin repetir (s, r, o).
pub fn hechos_python(rel: &str, texto: &str, simbolos: &[Simbolo]) -> Vec<Hecho> {
    Arbol::con_arbol(texto, |a| hechos_de(a, rel, simbolos)).unwrap_or_default()
}

pub fn hechos_de(a: &Arbol, rel: &str, simbolos: &[Simbolo]) -> Vec<Hecho> {
    let mut salida: Vec<Hecho> = vec![];
    let es_test = ES_TEST.hay(rel);
    let donde = |n: Id| dentro(simbolos, a.linea(n) as i64, rel);
    let recorrido = a.recorrer(a.modulo);
    // r = APIRouter(prefix="/api/hub") / bp = Blueprint(..., url_prefix="/x"): el prefijo va en la ruta expuesta
    let mut prefijos: HashMap<String, String> = HashMap::new();
    for &n in &recorrido {
        if let K::Assign { targets, value } = a.k(n) {
            if targets.len() != 1 {
                continue;
            }
            let Some(objetivo) = a.nombre(targets[0]) else { continue };
            let K::Call { func, keywords, .. } = a.k(*value) else { continue };
            let nombre = match a.k(*func) {
                K::Name { id, .. } => id.as_str(),
                K::Attribute { attr, .. } => attr.as_str(),
                _ => "",
            };
            if ROUTERS.contains(&nombre) {
                for kw in keywords {
                    if let K::Keyword { arg: Some(arg), value } = a.k(*kw) {
                        if arg == "prefix" || arg == "url_prefix" {
                            if let Some(c) = a.cadena(*value) {
                                if c.starts_with('/') {
                                    prefijos.insert(objetivo.to_string(), c.trim_end_matches('/').to_string());
                                }
                            }
                        }
                    }
                }
            }
        }
    }
    for &n in &recorrido {
        match a.k(n) {
            K::ClassDef { name, bases, .. } => {
                let clase = dentro(simbolos, a.linea(n) as i64, name);
                for b in bases {
                    salida.push(Hecho::nuevo(&clase, "hereda", &unparse(a, *b), a.linea(n) as i64));
                }
            }
            K::FunctionDef { name, decorators, .. } => {
                for &d in decorators {
                    let K::Call { func, args, keywords } = a.k(d) else { continue };
                    let K::Attribute { value: fv, attr, .. } = a.k(*func) else { continue };
                    if !METODOS_HTTP.contains(&attr.as_str()) || args.is_empty() {
                        continue;
                    }
                    let Some(ruta0) = a.cadena(args[0]) else { continue };
                    if !ruta0.starts_with('/') {
                        continue;
                    }
                    let receptor = a.nombre(*fv).unwrap_or("");
                    let ruta = format!("{}{}", prefijos.get(receptor).map(|s| s.as_str()).unwrap_or(""), ruta0);
                    let metodos: Vec<String> = if attr == "route" || attr == "api_route" {
                        let mut metodos = vec!["GET".to_string()];
                        for kw in keywords {
                            if let K::Keyword { arg: Some(arg), value } = a.k(*kw) {
                                if arg == "methods" {
                                    if let K::List { elts, .. } | K::Tuple { elts, .. } = a.k(*value) {
                                        let m: Vec<String> = elts.iter().filter_map(|e| a.cadena(*e)).filter(|s| !s.is_empty()).map(upper).collect();
                                        metodos = if m.is_empty() { vec!["GET".to_string()] } else { m };
                                    }
                                }
                            }
                        }
                        metodos
                    } else {
                        vec![upper(attr)]
                    };
                    for metodo in metodos {
                        salida.push(Hecho::nuevo(&dentro(simbolos, a.linea(n) as i64, name), "expone", &format!("{metodo} {}", ruta_http_canonica(&ruta)), a.linea(n) as i64));
                    }
                }
            }
            K::Raise { exc: Some(exc), .. } => {
                let f = match a.k(*exc) {
                    K::Call { func, .. } => *func,
                    _ => *exc,
                };
                let nombre = match a.k(f) {
                    K::Name { id, .. } => Some(id.clone()),
                    K::Attribute { attr, .. } => Some(attr.clone()),
                    _ => None,
                };
                if let Some(nombre) = nombre {
                    if !nombre.is_empty() {
                        salida.push(Hecho::nuevo(&donde(n), "lanza", &nombre, a.linea(n) as i64));
                    }
                }
            }
            K::ExceptHandler { type_: Some(t), .. } => {
                let tipos: Vec<Id> = match a.k(*t) {
                    K::Tuple { elts, .. } => elts.clone(),
                    _ => vec![*t],
                };
                for t in tipos {
                    salida.push(Hecho::nuevo(&donde(n), "captura", &unparse(a, t), a.linea(n) as i64));
                }
            }
            K::Call { func, args, .. } => {
                let K::Attribute { value: fv, attr, .. } = a.k(*func) else { continue };
                let base = unparse(a, *fv);
                let clave = args.first().and_then(|x| a.cadena(*x));
                let clave = clave.filter(|c| !c.is_empty());
                if let (Some(c), true) = (clave, attr == "get" && base.ends_with("environ")) {
                    salida.push(Hecho::nuevo(&donde(n), "lee_entorno", c, a.linea(n) as i64));
                } else if let (Some(c), true) = (clave, attr == "getenv") {
                    salida.push(Hecho::nuevo(&donde(n), "lee_entorno", c, a.linea(n) as i64));
                } else if let (Some(c), true) = (clave, attr == "get" && ES_CONFIG.hay(&base) && !es_test) {
                    salida.push(Hecho::nuevo(&donde(n), "lee_config", c, a.linea(n) as i64));
                } else if SUBPROCESO.contains(&attr.as_str()) && base == "subprocess" && !args.is_empty() {
                    let a0 = args[0];
                    let prog = match a.cadena(a0) {
                        Some(s) => Some(s.to_string()),
                        None => match a.k(a0) {
                            K::List { elts, .. } | K::Tuple { elts, .. } if !elts.is_empty() => a.cadena(elts[0]).map(|s| s.to_string()),
                            _ => None,
                        },
                    };
                    if let Some(p) = prog.filter(|p| !p.is_empty()) {
                        match crate::py::cadena::split_espacios(&p).first() {
                            Some(primera) => salida.push(Hecho::nuevo(&donde(n), "ejecuta", primera, a.linea(n) as i64)),
                            // `prog.split()[0]` de una cadena de solo espacios: IndexError, y extraer_hechos deja el
                            // archivo entero sin hechos
                            None => return vec![],
                        }
                    }
                }
            }
            K::Subscript { value, slice, ctx } => {
                let Some(clave) = a.cadena(*slice).filter(|c| !c.is_empty()) else { continue };
                let base = unparse(a, *value);
                let escritura = matches!(ctx, Ctx::Store | Ctx::Del);
                if base.ends_with("environ") && !escritura {
                    salida.push(Hecho::nuevo(&donde(n), "lee_entorno", clave, a.linea(n) as i64));
                } else if ES_CONFIG.hay(&base) && !escritura && !es_test {
                    salida.push(Hecho::nuevo(&donde(n), "lee_config", clave, a.linea(n) as i64));
                }
            }
            K::Assign { targets, .. } => {
                for t in targets {
                    if let K::Attribute { value, attr, .. } = a.k(*t) {
                        if a.nombre(*value) == Some("self") {
                            let duenio = dentro(simbolos, a.linea(n) as i64, "");
                            let clase = match duenio.rfind('.') {
                                Some(i) => duenio[..i].to_string(),
                                None => String::new(),
                            };
                            if !clase.is_empty() {
                                salida.push(Hecho::nuevo(&clase, "atributo", attr, a.linea(n) as i64));
                            }
                        }
                    }
                }
            }
            _ => {}
        }
    }
    let mut vistos: HashSet<(String, String, String)> = HashSet::new();
    salida.into_iter().filter(|h| vistos.insert((h.s.clone(), h.r.clone(), h.o.clone()))).collect()
}

/// Para las pruebas: la lista de constantes de cadena no vacías (lo que en Python es `_constante(x) or ""`).
pub fn es_cadena(c: &Constante) -> bool {
    matches!(c, Constante::Cadena(_))
}
