//! Un validador con las reglas de pydantic 2 en modo flexible (lax), para los modelos de Prig que se guardan en JSON
//! (planes de estudio, rutas guiadas, el dataset de aprendizaje...): `model_validate` sobre lo leído del disco y
//! `model_dump` de vuelta, con los campos en el orden del modelo, los valores por defecto y los validadores `before`
//! de cada modelo. Las conversiones, comprobadas contra pydantic 2.13:
//!
//! * `str`: solo texto (un número es `string_type`).
//! * `int`: enteros, `True`/`False`, reales sin decimales y texto numérico (con espacios, también `"3.0"`).
//! * `float`: números, booleanos y texto numérico (`"nan"`, `"inf"` incluidos).
//! * `bool`: booleanos, `0`/`1` (también `0.0`/`1.0`) y los textos de pydantic (`yes`, `on`, `t`...).
//! * enumeraciones de texto: el valor exacto.
//! * `Optional`, `List`, `Dict[str, ...]`, `Any` y modelos anidados.
//!
//! Lo que pydantic tira con un error aquí es `Err` con su tipo (`string_type`, `int_parsing`...). Los campos que no
//! son del modelo se descartan, como en pydantic.

use crate::valor::{Mapa, Valor};

pub enum Tipo {
    Texto,
    Entero,
    Real,
    Booleano,
    Cualquiera,
    Opcional(&'static Tipo),
    Lista(&'static Tipo),
    /// `Dict[str, T]`
    Dict(&'static Tipo),
    /// Una enumeración de texto: sus valores
    Enum(&'static [&'static str]),
    Modelo(&'static Modelo),
}

pub enum Defecto {
    /// Obligatorio: si falta, `missing`
    No,
    /// Un valor fijo o una fábrica (`default_factory`: un id al azar, la hora)
    Valor(fn() -> Valor),
}

pub struct Campo {
    pub nombre: &'static str,
    pub tipo: Tipo,
    pub defecto: Defecto,
}

pub struct Modelo {
    pub nombre: &'static str,
    pub campos: &'static [Campo],
    /// El `model_validator(mode="before")`: recibe la entrada y devuelve la que se valida
    pub antes: Option<fn(Valor) -> Valor>,
}

/// El primer error de validación: (tipo de pydantic, dónde)
#[derive(Debug, Clone, PartialEq)]
pub struct Fallo {
    pub tipo: &'static str,
    pub donde: String,
}

fn fallo(tipo: &'static str, donde: &str) -> Fallo {
    Fallo { tipo, donde: donde.to_string() }
}

/// `int` de pydantic desde texto: entero, o real sin decimales
fn entero_de_texto(t: &str) -> Option<i128> {
    let t = t.trim();
    if let Ok(n) = t.parse::<i128>() {
        return Some(n);
    }
    let x: f64 = t.parse().ok()?;
    (x.is_finite() && x.fract() == 0.0).then_some(x as i128)
}

pub fn validar_tipo(t: &Tipo, v: Valor, donde: &str) -> Result<Valor, Fallo> {
    validar_tipo_todos(t, v, donde).map_err(|mut l| l.swap_remove(0))
}

/// Como `validar_tipo`, con todos los errores (pydantic sigue con los demás elementos y campos tras el primero)
pub fn validar_tipo_todos(t: &Tipo, v: Valor, donde: &str) -> Result<Valor, Vec<Fallo>> {
    let uno = |r: Result<Valor, Fallo>| r.map_err(|f| vec![f]);
    match t {
        Tipo::Opcional(interno) => match v {
            Valor::Nulo => Ok(Valor::Nulo),
            otro => validar_tipo_todos(interno, otro, donde),
        },
        Tipo::Lista(interno) => match v {
            Valor::Lista(l) => {
                let mut salida = Vec::with_capacity(l.len());
                let mut fallos = Vec::new();
                for (i, x) in l.into_iter().enumerate() {
                    match validar_tipo_todos(interno, x, &format!("{donde}.{i}")) {
                        Ok(x) => salida.push(x),
                        Err(f) => fallos.extend(f),
                    }
                }
                if fallos.is_empty() { Ok(Valor::Lista(salida)) } else { Err(fallos) }
            }
            _ => Err(vec![fallo("list_type", donde)]),
        },
        Tipo::Dict(interno) => match v {
            Valor::Mapa(m) => {
                let mut salida = Mapa::new();
                let mut fallos = Vec::new();
                for (k, x) in m.iter() {
                    match validar_tipo_todos(interno, x.clone(), &format!("{donde}.{k}")) {
                        Ok(x) => salida.poner(k.clone(), x),
                        Err(f) => fallos.extend(f),
                    }
                }
                if fallos.is_empty() { Ok(Valor::Mapa(salida)) } else { Err(fallos) }
            }
            _ => Err(vec![fallo("dict_type", donde)]),
        },
        Tipo::Modelo(m) => validar_en(m, v, donde).map(Valor::Mapa),
        _ => uno(validar_simple(t, v, donde)),
    }
}

fn validar_simple(t: &Tipo, v: Valor, donde: &str) -> Result<Valor, Fallo> {
    match t {
        Tipo::Cualquiera => Ok(v),
        Tipo::Texto => match v {
            Valor::Texto(_) => Ok(v),
            _ => Err(fallo("string_type", donde)),
        },
        Tipo::Entero => match v {
            Valor::Entero(_) => Ok(v),
            Valor::Bool(b) => Ok(Valor::Entero(b as i128)),
            Valor::Real(x) if x.is_finite() && x.fract() == 0.0 => Ok(Valor::Entero(x as i128)),
            Valor::Real(_) => Err(fallo("int_from_float", donde)),
            Valor::Texto(ref s) => entero_de_texto(s).map(Valor::Entero).ok_or_else(|| fallo("int_parsing", donde)),
            _ => Err(fallo("int_type", donde)),
        },
        Tipo::Real => match v {
            Valor::Real(_) => Ok(v),
            Valor::Entero(n) => Ok(Valor::Real(n as f64)),
            Valor::Bool(b) => Ok(Valor::Real(if b { 1.0 } else { 0.0 })),
            Valor::Texto(ref s) => {
                let s = s.trim().to_lowercase();
                let x = match s.as_str() {
                    "nan" => Some(f64::NAN),
                    "inf" | "infinity" | "+inf" => Some(f64::INFINITY),
                    "-inf" | "-infinity" => Some(f64::NEG_INFINITY),
                    _ => s.parse::<f64>().ok(),
                };
                x.map(Valor::Real).ok_or_else(|| fallo("float_parsing", donde))
            }
            _ => Err(fallo("float_type", donde)),
        },
        Tipo::Booleano => match v {
            Valor::Bool(_) => Ok(v),
            Valor::Entero(0) => Ok(Valor::Bool(false)),
            Valor::Entero(1) => Ok(Valor::Bool(true)),
            Valor::Entero(_) => Err(fallo("bool_parsing", donde)),
            Valor::Real(x) if x == 0.0 => Ok(Valor::Bool(false)),
            Valor::Real(x) if x == 1.0 => Ok(Valor::Bool(true)),
            Valor::Texto(ref s) => match s.trim().to_lowercase().as_str() {
                "0" | "off" | "f" | "false" | "n" | "no" => Ok(Valor::Bool(false)),
                "1" | "on" | "t" | "true" | "y" | "yes" => Ok(Valor::Bool(true)),
                _ => Err(fallo("bool_parsing", donde)),
            },
            _ => Err(fallo("bool_type", donde)),
        },
        Tipo::Enum(valores) => match v {
            Valor::Texto(ref s) if valores.contains(&s.as_str()) => Ok(v),
            _ => Err(fallo("enum", donde)),
        },
        _ => unreachable!(),
    }
}

fn validar_en(m: &Modelo, v: Valor, donde: &str) -> Result<Mapa, Vec<Fallo>> {
    let v = match m.antes {
        Some(f) => f(v),
        None => v,
    };
    let Valor::Mapa(entrada) = v else { return Err(vec![fallo("model_type", donde)]) };
    let mut salida = Mapa::new();
    let mut fallos = Vec::new();
    for c in m.campos {
        let lugar = if donde.is_empty() { c.nombre.to_string() } else { format!("{donde}.{}", c.nombre) };
        match (entrada.get(c.nombre), &c.defecto) {
            (Some(x), _) => match validar_tipo_todos(&c.tipo, x.clone(), &lugar) {
                Ok(valor) => salida.poner(c.nombre, valor),
                Err(f) => fallos.extend(f),
            },
            // un valor por defecto no se valida (pydantic no lo hace)
            (None, Defecto::Valor(f)) => salida.poner(c.nombre, f()),
            (None, Defecto::No) => fallos.push(fallo("missing", &lugar)),
        }
    }
    if fallos.is_empty() { Ok(salida) } else { Err(fallos) }
}

/// `Modelo.model_validate(v).model_dump()`: el primer error, si hay
pub fn validar(m: &Modelo, v: Valor) -> Result<Mapa, Fallo> {
    validar_en(m, v, "").map_err(|mut l| l.swap_remove(0))
}

// ---------------------------------------------------------------------------------------------- ayudas de los modelos

/// `_texto(valor, por_defecto)` de study_plan_engine.py: lo que devuelve un modelo pequeño no siempre es una cadena
pub fn texto(valor: Option<&Valor>, por_defecto: &str) -> String {
    match valor {
        None | Some(Valor::Nulo) => por_defecto.to_string(),
        Some(Valor::Texto(t)) => {
            let t = crate::py::strip(t);
            if t.is_empty() { por_defecto.to_string() } else { t.to_string() }
        }
        Some(Valor::Lista(l)) => {
            let unido = l.iter().map(|x| x.texto_o_repr()).collect::<Vec<_>>().join(", ");
            if unido.is_empty() { por_defecto.to_string() } else { unido }
        }
        Some(otro) => otro.texto_o_repr(),
    }
}

/// `_rellenar(valores, reglas)`: los campos que faltan o están vacíos se completan, en orden, con lo que va quedando
pub fn rellenar(v: Valor, reglas: &[(&str, &dyn Fn(&Mapa) -> Valor)]) -> Valor {
    let Valor::Mapa(mut datos) = v else { return v };
    for (campo, generar) in reglas {
        let vacio = match datos.get(campo) {
            None | Some(Valor::Nulo) => true,
            Some(Valor::Texto(t)) => crate::py::strip(t).is_empty(),
            _ => false,
        };
        if vacio {
            let nuevo = generar(&datos);
            datos.poner(*campo, nuevo);
        }
    }
    Valor::Mapa(datos)
}

/// `f"{prefijo}_{uuid.uuid4().hex[:n]}"`
pub fn id_al_azar(prefijo: &str, n: usize) -> String {
    let mut b = [0u8; 16];
    // SAFETY: getrandom llena el búfer que se le da
    unsafe {
        libc::getrandom(b.as_mut_ptr() as *mut libc::c_void, b.len(), 0);
    }
    let hex: String = b.iter().map(|x| format!("{x:02x}")).collect();
    format!("{prefijo}_{}", &hex[..n])
}

#[cfg(test)]
mod pruebas {
    use super::*;

    static HIJO: Modelo = Modelo {
        nombre: "Hijo",
        campos: &[Campo { nombre: "n", tipo: Tipo::Entero, defecto: Defecto::Valor(|| Valor::Entero(0)) }],
        antes: None,
    };
    static PADRE: Modelo = Modelo {
        nombre: "Padre",
        campos: &[
            Campo { nombre: "nombre", tipo: Tipo::Texto, defecto: Defecto::No },
            Campo { nombre: "hijos", tipo: Tipo::Lista(&Tipo::Modelo(&HIJO)), defecto: Defecto::Valor(|| Valor::Lista(Vec::new())) },
            Campo { nombre: "activo", tipo: Tipo::Booleano, defecto: Defecto::Valor(|| Valor::Bool(true)) },
        ],
        antes: None,
    };

    fn json(t: &str) -> Valor {
        crate::json::leer(t).unwrap()
    }

    #[test]
    fn como_pydantic() {
        let m = validar(&PADRE, json(r#"{"hijos": [{"n": "3.0"}, {}], "nombre": "a", "extra": 1, "activo": "yes"}"#)).unwrap();
        assert_eq!(crate::json::escribir_compacto(&Valor::Mapa(m)), r#"{"nombre": "a", "hijos": [{"n": 3}, {"n": 0}], "activo": true}"#);
        assert_eq!(validar(&PADRE, json(r#"{"nombre": 1}"#)).unwrap_err().tipo, "string_type");
        assert_eq!(validar(&PADRE, json(r#"{}"#)).unwrap_err().tipo, "missing");
        assert_eq!(validar(&PADRE, json(r#"{"nombre": "a", "activo": 2}"#)).unwrap_err().tipo, "bool_parsing");
        assert_eq!(validar(&PADRE, json(r#"{"nombre": "a", "hijos": [{"n": 1.5}]}"#)).unwrap_err().tipo, "int_from_float");
    }
}
