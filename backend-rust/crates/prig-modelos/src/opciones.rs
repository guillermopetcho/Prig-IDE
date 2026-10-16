//! Todo lo configurable de los modelos de Ollama y en qué capa lo decide el usuario (`ollama_opciones.py`): el
//! catálogo de opciones verificadas (y las excluidas, con su motivo), la validación de tipos y rangos, y el almacén
//! de capas (`~/.prig_modelos.json` o `PRIG_MODELOS_ARCHIVO`): global < modelo < uso < modelo_uso.

use prig_plataforma::py::{self, ErrorPy};
use prig_plataforma::regex_py::ExpresionPy;
use prig_recursos::valor::{Mapa, Valor};
use std::sync::{Mutex, OnceLock};

pub const CAPAS: [&str; 4] = ["global", "modelo", "uso", "modelo_uso"];

type R<T> = Result<T, ErrorPy>;

/// El catálogo tal cual estaba en Python (opciones, campos, excluidas, usos, plantillas)
pub fn catalogo_base() -> &'static Mapa {
    static C: OnceLock<Mapa> = OnceLock::new();
    C.get_or_init(|| match prig_recursos::json::leer(include_str!("opciones_catalogo.json")) {
        Ok(Valor::Mapa(m)) => m,
        _ => panic!("catálogo de opciones"),
    })
}

fn lista_de(clave: &str) -> &'static [Valor] {
    catalogo_base().lista(clave).unwrap_or(&[])
}

fn mapa_de(clave: &str) -> &'static Mapa {
    static VACIO: OnceLock<Mapa> = OnceLock::new();
    catalogo_base().mapa(clave).unwrap_or_else(|| VACIO.get_or_init(Mapa::new))
}

fn definicion_opcion(clave: &str) -> Option<&'static Mapa> {
    lista_de("OPCIONES").iter().filter_map(|o| if let Valor::Mapa(m) = o { Some(m) } else { None }).find(|m| m.texto("clave") == Some(clave))
}

fn definicion_campo(clave: &str) -> Option<&'static Mapa> {
    lista_de("CAMPOS").iter().filter_map(|o| if let Valor::Mapa(m) = o { Some(m) } else { None }).find(|m| m.texto("clave") == Some(clave))
}

pub fn es_uso(uso: &str) -> bool {
    mapa_de("USOS").contiene(uso)
}

/// La excepción del módulo (ErrorConfig, un ValueError)
fn error(t: impl Into<String>) -> ErrorPy {
    ErrorPy::Propia(t.into())
}

/// `int(valor)` de Python: (resultado, o la excepción que no es TypeError/ValueError)
enum Entero {
    Si(i128),
    No,
    Desborde(String),
}

fn int_py(v: &Valor) -> Entero {
    match v {
        Valor::Bool(b) => Entero::Si(*b as i128),
        Valor::Entero(n) => Entero::Si(*n),
        Valor::Real(x) if x.is_nan() => Entero::No,
        Valor::Real(x) if x.is_infinite() => Entero::Desborde("cannot convert float infinity to integer".into()),
        Valor::Real(x) => Entero::Si(x.trunc() as i128),
        Valor::Texto(t) => match prig_recursos::valor::entero_de_texto(t) {
            Some(n) => Entero::Si(n),
            None => Entero::No,
        },
        _ => Entero::No,
    }
}

fn float_py(v: &Valor) -> Option<f64> {
    match v {
        Valor::Texto(t) => prig_recursos::valor::real_de_texto(t),
        otro => otro.num(),
    }
}

fn duracion() -> &'static ExpresionPy {
    static D: OnceLock<ExpresionPy> = OnceLock::new();
    D.get_or_init(|| ExpresionPy::compilar(r"^-?\d+(\.\d+)?(ms|s|m|h)?$", true).expect("DURACION"))
}

/// `validar(valores)`: tipos y rangos. Una clave excluida o desconocida es un error, no se ignora.
pub fn validar(valores: &Valor) -> R<Mapa> {
    let vacio = Mapa::new();
    let entrada = match valores {
        v if !v.verdad() => &vacio,
        Valor::Mapa(m) => m,
        otro => return Err(ErrorPy::Atributo(format!("'{}' object has no attribute 'items'", py::tipo(otro)))),
    };
    let excluidas = mapa_de("EXCLUIDAS");
    let mut limpio = Mapa::new();
    for (clave, valor) in entrada.iter() {
        if let Some(e) = excluidas.mapa(clave) {
            return Err(error(format!("{clave} no se admite: {}", e.texto("motivo").unwrap_or(""))));
        }
        let Some(def) = definicion_opcion(clave).or_else(|| definicion_campo(clave)) else {
            return Err(error(format!("Opción desconocida: {clave}")));
        };
        let nombre = def.texto("nombre").unwrap_or("");
        let no_valido = || error(format!("{nombre}: valor no válido ({})", valor.repr_py()));
        let tipo = def.texto("tipo").unwrap_or("");
        let v: Valor = match tipo {
            "int" => match int_py(valor) {
                Entero::Si(n) => match float_py(valor) {
                    Some(f) if f == n as f64 => Valor::Entero(n),
                    _ => return Err(no_valido()),
                },
                Entero::No => return Err(no_valido()),
                Entero::Desborde(t) => return Err(ErrorPy::Desborde(t)),
            },
            "float" => match float_py(valor) {
                Some(f) => Valor::Real(f),
                None => return Err(no_valido()),
            },
            "bool" => match valor {
                Valor::Bool(_) => valor.clone(),
                _ => return Err(no_valido()),
            },
            "lista" => {
                let elementos = match valor {
                    Valor::Texto(_) => vec![valor.clone()],
                    otro => py::iterar(otro).map_err(|_| no_valido())?,
                };
                let textos: Vec<Valor> =
                    elementos.iter().map(|x| x.texto_py()).filter(|t| !t.is_empty()).map(Valor::Texto).collect();
                if textos.len() > 8 {
                    return Err(error("Como mucho 8 textos de parada"));
                }
                Valor::Lista(textos)
            }
            "duracion" => {
                let t = py::strip(&valor.texto_py()).to_string();
                if duracion().aciertos(&t).is_empty() {
                    return Err(no_valido());
                }
                Valor::Texto(t)
            }
            "texto" => {
                let t = valor.texto_py();
                if t.chars().count() > 4000 {
                    return Err(error("Las instrucciones adicionales no pueden pasar de 4000 caracteres"));
                }
                Valor::Texto(t)
            }
            _ => return Err(no_valido()),
        };
        if tipo == "int" || tipo == "float" {
            let (min, max) = (def.valor("min"), def.valor("max"));
            let x = v.num().unwrap_or(0.0);
            let fuera = match (&v, min, max) {
                (Valor::Entero(n), Valor::Entero(a), Valor::Entero(b)) => n < a || n > b,
                _ => x < min.num().unwrap_or(f64::NEG_INFINITY) || x > max.num().unwrap_or(f64::INFINITY),
            };
            if fuera {
                return Err(error(format!("{nombre}: debe estar entre {} y {}", min.texto_py(), max.texto_py())));
            }
        }
        limpio.poner(clave.clone(), v);
    }
    Ok(limpio)
}

/// `separar(valores)`: (options del motor, campos de la petición)
pub fn separar(valores: &Mapa) -> (Mapa, Mapa) {
    let mut opciones = Mapa::new();
    let mut campos = Mapa::new();
    for (k, v) in valores.iter() {
        if definicion_opcion(k).is_some() {
            opciones.poner(k.clone(), v.clone());
        }
        if definicion_campo(k).is_some() {
            campos.poner(k.clone(), v.clone());
        }
    }
    (opciones, campos)
}

/// `limpiar_para_ollama(opciones)`: sin lo que Ollama rechaza o ignora
pub fn limpiar_para_ollama(opciones: &Mapa) -> Mapa {
    let excluidas = mapa_de("EXCLUIDAS");
    let mut m = Mapa::new();
    for (k, v) in opciones.iter() {
        if !excluidas.contiene(k) {
            m.poner(k.clone(), v.clone());
        }
    }
    m
}

/// `catalogo(num_gpus)`
pub fn catalogo(num_gpus: i64) -> Mapa {
    let opciones: Vec<Valor> = lista_de("OPCIONES")
        .iter()
        .filter(|o| match o {
            Valor::Mapa(m) => num_gpus as f64 >= m.num_o("requiere_gpus", 1.0),
            _ => true,
        })
        .cloned()
        .collect();
    let c = catalogo_base();
    Mapa::new()
        .con("opciones", Valor::Lista(opciones))
        .con("campos", c.valor("CAMPOS").clone())
        .con("campos_prueba", c.valor("CAMPOS_PRUEBA").clone())
        .con("excluidas", c.valor("EXCLUIDAS").clone())
        .con("excluidas_servidor", c.valor("EXCLUIDAS_SERVIDOR").clone())
        .con("excluidas_gestion", c.valor("EXCLUIDAS_GESTION").clone())
        .con("usos", c.valor("USOS").clone())
        .con("capas", c.valor("CAPAS").clone())
        .con("plantillas", c.valor("PLANTILLAS").clone())
}

// =========================================================================== almacén de capas

fn vacio() -> Mapa {
    Mapa::new()
        .con("version", 1)
        .con("global", Mapa::new())
        .con("modelo", Mapa::new())
        .con("uso", Mapa::new())
        .con("modelo_uso", Mapa::new())
        .con("embeddings", Mapa::new().con("modelo", Valor::Nulo).con("dimensiones", Valor::Nulo).con("truncar", true))
}

fn sin_excluidas(m: &Mapa) -> Mapa {
    limpiar_para_ollama(m)
}

/// `_leer`: lo guardado, con lo que falte de lo vacío; un archivo roto se aparta (`.roto`) y se empieza de cero
fn leer(ruta: &str) -> Mapa {
    let bytes = match std::fs::read(ruta) {
        Ok(b) => b,
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => return vacio(),
        Err(_) => return roto(ruta),
    };
    let Ok(texto) = String::from_utf8(bytes) else { return roto(ruta) };
    let texto = texto.replace("\r\n", "\n").replace('\r', "\n");
    let Ok(Valor::Mapa(mut datos)) = prig_recursos::json::leer(&texto) else { return roto(ruta) };
    for (k, v) in vacio().iter() {
        if !datos.contiene(k) {
            datos.poner(k.clone(), v.clone());
        }
    }
    let Some(Valor::Mapa(g)) = datos.get("global") else { return roto(ruta) };
    let g = sin_excluidas(g);
    datos.poner("global", g);
    for capa in ["modelo", "uso", "modelo_uso"] {
        let Some(Valor::Mapa(c)) = datos.get(capa) else { return roto(ruta) };
        let mut nueva = Mapa::new();
        for (n, d) in c.iter() {
            let Valor::Mapa(d) = d else { return roto(ruta) };
            nueva.poner(n.clone(), sin_excluidas(d));
        }
        datos.poner(capa, nueva);
    }
    datos
}

fn roto(ruta: &str) -> Mapa {
    let _ = std::fs::rename(ruta, format!("{ruta}.roto"));
    vacio()
}

/// `PRIG_MODELOS_ARCHIVO` o ~/.prig_modelos.json
pub fn ruta_por_defecto() -> String {
    std::env::var("PRIG_MODELOS_ARCHIVO").ok().filter(|r| !r.is_empty()).unwrap_or_else(|| {
        let casa = std::env::var("HOME").unwrap_or_default();
        format!("{casa}/.prig_modelos.json")
    })
}

/// La configuración del proceso (`config()` de Python): la de `ruta_por_defecto()`, reabierta si esa ruta cambia
pub fn config() -> std::sync::Arc<ConfigModelos> {
    static C: Mutex<Option<std::sync::Arc<ConfigModelos>>> = Mutex::new(None);
    let ruta = ruta_por_defecto();
    let mut g = C.lock().unwrap_or_else(|e| e.into_inner());
    match g.as_ref() {
        Some(c) if c.ruta == ruta => c.clone(),
        _ => {
            let c = std::sync::Arc::new(ConfigModelos::new(&ruta));
            *g = Some(c.clone());
            c
        }
    }
}

pub struct ConfigModelos {
    pub ruta: String,
    datos: Mutex<Mapa>,
    /// Cómo estaba el archivo al leerlo o escribirlo: si otro proceso de Prig lo cambia (el servidor de Rust y el
    /// backend de Python lo comparten mientras conviven), se relee antes de usarlo
    firma: Mutex<Option<Firma>>,
}

type Firma = (std::time::SystemTime, u64, u64);

fn firma(ruta: &str) -> Option<Firma> {
    use std::os::unix::fs::MetadataExt;
    let m = std::fs::metadata(ruta).ok()?;
    Some((m.modified().ok()?, m.len(), m.ino()))
}

fn mapa_mut<'a>(m: &'a mut Mapa, clave: &str) -> &'a mut Mapa {
    if !matches!(m.get(clave), Some(Valor::Mapa(_))) {
        m.poner(clave, Mapa::new());
    }
    match m.get_mut(clave) {
        Some(Valor::Mapa(x)) => x,
        _ => unreachable!(),
    }
}

impl ConfigModelos {
    pub fn new(ruta: &str) -> ConfigModelos {
        let f = firma(ruta);
        ConfigModelos { ruta: ruta.to_string(), datos: Mutex::new(leer(ruta)), firma: Mutex::new(f) }
    }

    /// Los datos, releídos si el archivo cambió desde la última vez
    fn bloquear(&self) -> std::sync::MutexGuard<'_, Mapa> {
        let mut d = self.datos.lock().unwrap_or_else(|e| e.into_inner());
        let ahora = firma(&self.ruta);
        let mut previa = self.firma.lock().unwrap_or_else(|e| e.into_inner());
        if ahora.is_some() && ahora != *previa {
            *d = leer(&self.ruta);
            *previa = firma(&self.ruta);
        }
        d
    }

    /// `_guardar`: a un temporal (0600, como mkstemp) en la misma carpeta y renombrado
    fn guardar(&self, datos: &Mapa) -> R<()> {
        use std::io::Write;
        use std::os::unix::fs::OpenOptionsExt;
        let carpeta = py::dirname(&py::abspath(&self.ruta));
        py::makedirs_py(&carpeta)?;
        let mut n = std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map(|d| d.as_nanos()).unwrap_or(0);
        let tmp = loop {
            let t = py::join(&carpeta, &format!(".prig_modelos.{:08x}", (n as u64) & 0xffff_ffff));
            match std::fs::OpenOptions::new().write(true).create_new(true).mode(0o600).open(&t) {
                Ok(mut f) => {
                    f.write_all(prig_recursos::json::escribir(&Valor::Mapa(datos.clone()), 1).as_bytes())
                        .map_err(|e| ErrorPy::os(&e, &t))?;
                    break t;
                }
                Err(e) if e.kind() == std::io::ErrorKind::AlreadyExists => n = n.wrapping_add(7919),
                Err(e) => return Err(ErrorPy::os(&e, &t)),
            }
        };
        std::fs::rename(&tmp, &self.ruta).map_err(|e| ErrorPy::os2(&e, &tmp, &self.ruta))?;
        *self.firma.lock().unwrap_or_else(|e| e.into_inner()) = firma(&self.ruta);
        Ok(())
    }

    fn clave(capa: &str, modelo: Option<&str>, uso: Option<&str>) -> R<Option<String>> {
        let modelo = modelo.filter(|m| !m.is_empty());
        match capa {
            "global" => Ok(None),
            "modelo" => modelo.map(|m| Some(m.to_string())).ok_or_else(|| error("Falta el modelo")),
            "uso" => match uso {
                Some(u) if es_uso(u) => Ok(Some(u.to_string())),
                _ => Err(error(format!("Uso desconocido: {}", uso.map(String::from).unwrap_or_else(|| "None".into())))),
            },
            "modelo_uso" => match (modelo, uso) {
                (Some(m), Some(u)) if es_uso(u) => Ok(Some(format!("{m}|{u}"))),
                _ => Err(error("Hacen falta modelo y uso")),
            },
            otra => Err(error(format!("Capa desconocida: {otra}"))),
        }
    }

    /// `capa(capa, modelo, uso)`
    pub fn capa(&self, capa: &str, modelo: Option<&str>, uso: Option<&str>) -> R<Mapa> {
        let d = self.bloquear();
        let clave = Self::clave(capa, modelo, uso)?;
        Ok(match clave {
            None => d.mapa("global").cloned().unwrap_or_default(),
            Some(k) => d.mapa(capa).and_then(|c| c.mapa(&k)).cloned().unwrap_or_default(),
        })
    }

    /// `fijar(capa, valores, ...)`: `None` en un valor lo quita de la capa
    pub fn fijar(&self, capa: &str, valores: &Mapa, modelo: Option<&str>, uso: Option<&str>, reemplazar: bool) -> R<Mapa> {
        let quitar: Vec<String> = valores.iter().filter(|(_, v)| v.es_nulo()).map(|(k, _)| k.clone()).collect();
        let mut validos = Mapa::new();
        for (k, v) in valores.iter() {
            if !v.es_nulo() {
                validos.poner(k.clone(), v.clone());
            }
        }
        let limpio = validar(&Valor::Mapa(validos))?;
        let mut d = self.bloquear();
        let clave = Self::clave(capa, modelo, uso)?;
        let resultado = match clave {
            None => {
                let mut destino = if reemplazar { Mapa::new() } else { d.mapa("global").cloned().unwrap_or_default() };
                for (k, v) in limpio.iter() {
                    destino.poner(k.clone(), v.clone());
                }
                for k in &quitar {
                    destino.quitar(k);
                }
                d.poner("global", destino.clone());
                destino
            }
            Some(k) => {
                let c = mapa_mut(&mut d, capa);
                let mut destino = if reemplazar { Mapa::new() } else { c.mapa(&k).cloned().unwrap_or_default() };
                for (kk, v) in limpio.iter() {
                    destino.poner(kk.clone(), v.clone());
                }
                for q in &quitar {
                    destino.quitar(q);
                }
                if !destino.is_empty() {
                    c.poner(k, destino.clone());
                } else {
                    c.quitar(&k);
                }
                destino
            }
        };
        let copia = d.clone();
        self.guardar(&copia)?;
        Ok(resultado)
    }

    /// `embeddings()`
    pub fn embeddings(&self) -> Mapa {
        self.bloquear().mapa("embeddings").cloned().unwrap_or_default()
    }

    /// `fijar_embeddings(...)`
    pub fn fijar_embeddings(&self, modelo: Option<&Valor>, dimensiones: Option<&Valor>, truncar: Option<&Valor>, quitar_dimensiones: bool) -> R<Mapa> {
        let mut d = self.bloquear();
        let e = mapa_mut(&mut d, "embeddings");
        if let Some(m) = modelo {
            let t = py::strip(&m.texto_py()).to_string();
            e.poner("modelo", if t.is_empty() { Valor::Nulo } else { Valor::Texto(t) });
        }
        if quitar_dimensiones {
            e.poner("dimensiones", Valor::Nulo);
        } else if let Some(dim) = dimensiones {
            let n = match int_py(dim) {
                Entero::Si(n) => n,
                _ => {
                    return Err(match dim {
                        Valor::Texto(t) => ErrorPy::Valor(format!(
                            "invalid literal for int() with base 10: {}",
                            Valor::Texto(t.clone()).repr_py()
                        )),
                        otro => ErrorPy::Tipo(format!(
                            "int() argument must be a string, a bytes-like object or a real number, not '{}'",
                            py::tipo(otro)
                        )),
                    })
                }
            };
            if !(16..=8192).contains(&n) {
                return Err(error("Las dimensiones deben estar entre 16 y 8192"));
            }
            e.poner("dimensiones", Valor::Entero(n));
        }
        if let Some(t) = truncar {
            e.poner("truncar", t.verdad());
        }
        let resultado = e.clone();
        let copia = d.clone();
        self.guardar(&copia)?;
        Ok(resultado)
    }

    /// `renombrar_modelo`: al copiar un modelo, su configuración viaja con él
    pub fn renombrar_modelo(&self, anterior: &str, nuevo: &str) -> R<()> {
        let mut d = self.bloquear();
        {
            let m = mapa_mut(&mut d, "modelo");
            if let Some(v) = m.get(anterior).cloned() {
                m.poner(nuevo, v);
            }
        }
        {
            let mu = mapa_mut(&mut d, "modelo_uso");
            let claves: Vec<String> = mu.claves().cloned().collect();
            for k in claves {
                let (m, u) = match k.rfind('|') {
                    Some(i) => (&k[..i], &k[i + 1..]),
                    None => ("", k.as_str()),
                };
                if m == anterior {
                    let v = mu.get(&k).cloned().unwrap_or(Valor::Nulo);
                    mu.poner(format!("{nuevo}|{u}"), v);
                }
            }
        }
        let copia = d.clone();
        self.guardar(&copia)
    }

    /// `resolver(modelo, uso)`: los valores efectivos y de qué capa sale cada uno
    pub fn resolver(&self, modelo: Option<&str>, uso: Option<&str>) -> Mapa {
        let d = self.bloquear();
        let capa = |c: &str, k: &str| d.mapa(c).and_then(|m| m.mapa(k)).cloned().unwrap_or_default();
        let mut capas: Vec<(&str, Mapa)> = vec![("global", d.mapa("global").cloned().unwrap_or_default())];
        let modelo = modelo.filter(|m| !m.is_empty());
        if let Some(m) = modelo {
            capas.push(("modelo", capa("modelo", m)));
            if let Some(base) = m.strip_suffix(":latest") {
                capas.insert(1, ("modelo", capa("modelo", base)));
            }
        }
        if let Some(u) = uso.filter(|u| es_uso(u)) {
            capas.push(("uso", capa("uso", u)));
            if let Some(m) = modelo {
                capas.push(("modelo_uso", capa("modelo_uso", &format!("{m}|{u}"))));
            }
        }
        drop(d);
        let mut valores = Mapa::new();
        let mut origen = Mapa::new();
        for (nombre, datos) in capas {
            for (k, v) in datos.iter() {
                valores.poner(k.clone(), v.clone());
                origen.poner(k.clone(), nombre);
            }
        }
        let (opciones, campos) = separar(&valores);
        Mapa::new().con("opciones", opciones).con("campos", campos).con("origen", origen)
    }

    /// `todo()`
    pub fn todo(&self) -> Mapa {
        self.bloquear().clone()
    }
}
