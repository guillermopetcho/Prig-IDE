//! El cuerpo de una petición como lo lee FastAPI: JSON (con el error 422 `json_invalid` de FastAPI si no lo es) y
//! validado como pydantic, con sus errores (`missing`, `dict_type`, `model_attributes_type`, `list_type`,
//! `string_type`, `bool_parsing`, ...). La interfaz enseña esos mensajes; el comparador de rutas los compara.

// El error de estas funciones es la respuesta 422 que se devuelve tal cual: así lo hace axum
#![allow(clippy::result_large_err)]

use axum::{body::Bytes, http::StatusCode, response::Response};
use prig_plataforma::valor::{Mapa, Valor};

use crate::routes::json_py;

/// Un error de validación de pydantic: (tipo, ubicación, mensaje, entrada)
pub struct Error {
    pub tipo: &'static str,
    pub loc: Vec<Valor>,
    pub msg: String,
    pub entrada: Valor,
    pub ctx: Option<Mapa>,
}

pub fn respuesta(errores: Vec<Error>) -> Response {
    let lista = errores
        .into_iter()
        .map(|e| {
            let mut m = Mapa::new().con("type", e.tipo).con("loc", Valor::Lista(e.loc)).con("msg", e.msg).con("input", e.entrada);
            if let Some(c) = e.ctx {
                m.poner("ctx", c);
            }
            Valor::Mapa(m)
        })
        .collect();
    json_py(StatusCode::UNPROCESSABLE_ENTITY, &Valor::Mapa(Mapa::new().con("detail", Valor::Lista(lista))))
}

fn loc(partes: &[&str]) -> Vec<Valor> {
    partes.iter().map(|p| Valor::Texto(p.to_string())).collect()
}

/// El cuerpo como JSON. Sin cuerpo: `missing`; JSON roto: `json_invalid` con la posición y el mensaje de `json`
pub fn json(cuerpo: &Bytes) -> Result<Valor, Response> {
    if cuerpo.is_empty() {
        return Err(respuesta(vec![Error { tipo: "missing", loc: loc(&["body"]), msg: "Field required".into(), entrada: Valor::Nulo, ctx: None }]));
    }
    let texto = String::from_utf8_lossy(cuerpo);
    prig_plataforma::json::leer(&texto).map_err(|e| {
        // «Expecting value: line 1 column 1 (char 0)» → mensaje y posición
        let (msg, resto) = e.split_once(": line ").unwrap_or((e.as_str(), ""));
        let pos: i128 = resto.rsplit_once("(char ").and_then(|(_, n)| n.trim_end_matches(')').parse().ok()).unwrap_or(0);
        respuesta(vec![Error {
            tipo: "json_invalid",
            loc: vec![Valor::Texto("body".into()), Valor::Entero(pos)],
            msg: "JSON decode error".into(),
            entrada: Valor::Mapa(Mapa::new()),
            ctx: Some(Mapa::new().con("error", msg.to_string())),
        }])
    })
}

/// Un cuerpo `Dict[str, Any]`
pub fn dict(cuerpo: &Bytes) -> Result<Mapa, Response> {
    match json(cuerpo)? {
        Valor::Mapa(m) => Ok(m),
        otro => Err(respuesta(vec![Error {
            tipo: "dict_type",
            loc: loc(&["body"]),
            msg: "Input should be a valid dictionary".into(),
            entrada: otro,
            ctx: None,
        }])),
    }
}

/// Un cuerpo que es un modelo de pydantic (sus campos se validan después con `Campos`)
pub fn modelo(cuerpo: &Bytes) -> Result<Mapa, Response> {
    match json(cuerpo)? {
        Valor::Mapa(m) => Ok(m),
        otro => Err(respuesta(vec![Error {
            tipo: "model_attributes_type",
            loc: loc(&["body"]),
            msg: "Input should be a valid dictionary or object to extract fields from".into(),
            entrada: otro,
            ctx: None,
        }])),
    }
}

/// Validar los campos de un modelo juntando todos los errores, como pydantic
pub struct Campos<'a> {
    cuerpo: &'a Mapa,
    pub errores: Vec<Error>,
}

impl<'a> Campos<'a> {
    pub fn new(cuerpo: &'a Mapa) -> Campos<'a> {
        Campos { cuerpo, errores: Vec::new() }
    }

    fn error(&mut self, tipo: &'static str, campo: &str, msg: &str, entrada: Valor) {
        self.errores.push(Error { tipo, loc: loc(&["body", campo]), msg: msg.into(), entrada, ctx: None });
    }

    fn falta(&mut self, campo: &str) {
        let todo = Valor::Mapa(self.cuerpo.clone());
        self.error("missing", campo, "Field required", todo);
    }

    /// `campo: str` (obligatorio) u `Optional[str] = defecto` (con `defecto`: None también vale)
    pub fn texto(&mut self, campo: &str, defecto: Option<Valor>) -> Valor {
        match self.cuerpo.get(campo) {
            None => match defecto {
                Some(d) => d,
                None => {
                    self.falta(campo);
                    Valor::Nulo
                }
            },
            Some(Valor::Nulo) if defecto.is_some() => Valor::Nulo,
            Some(Valor::Texto(t)) => Valor::Texto(t.clone()),
            Some(v) => {
                self.error("string_type", campo, "Input should be a valid string", v.clone());
                Valor::Nulo
            }
        }
    }

    /// `Optional[bool] = None`, con la conversión flexible de pydantic (`"true"`, `"0"`, `1`, ...)
    pub fn booleano_opcional(&mut self, campo: &str) -> Option<bool> {
        match self.cuerpo.get(campo) {
            None | Some(Valor::Nulo) => None,
            Some(Valor::Bool(b)) => Some(*b),
            Some(Valor::Entero(0)) => Some(false),
            Some(Valor::Entero(1)) => Some(true),
            Some(Valor::Real(x)) if *x == 0.0 => Some(false),
            Some(Valor::Real(x)) if *x == 1.0 => Some(true),
            Some(v @ Valor::Texto(t)) => match t.to_lowercase().as_str() {
                "0" | "off" | "f" | "false" | "n" | "no" => Some(false),
                "1" | "on" | "t" | "true" | "y" | "yes" => Some(true),
                _ => {
                    let v = v.clone();
                    self.error("bool_parsing", campo, "Input should be a valid boolean, unable to interpret input", v);
                    None
                }
            },
            Some(v @ (Valor::Entero(_) | Valor::Real(_))) => {
                let v = v.clone();
                self.error("bool_parsing", campo, "Input should be a valid boolean, unable to interpret input", v);
                None
            }
            Some(v) => {
                let v = v.clone();
                self.error("bool_type", campo, "Input should be a valid boolean", v);
                None
            }
        }
    }

    /// `campo: int` (obligatorio), con la conversión flexible de pydantic: entero, real sin decimales, texto numérico
    pub fn entero(&mut self, campo: &str) -> Option<i128> {
        let v = match self.cuerpo.get(campo) {
            None => {
                self.falta(campo);
                return None;
            }
            Some(v) => v.clone(),
        };
        match &v {
            Valor::Entero(n) => Some(*n),
            Valor::Bool(b) => Some(*b as i128),
            Valor::Real(x) if x.fract() == 0.0 && x.is_finite() => Some(*x as i128),
            Valor::Real(_) => {
                self.error("int_from_float", campo, "Input should be a valid integer, got a number with a fractional part", v);
                None
            }
            Valor::Texto(t) => match t.trim().parse::<i128>() {
                Ok(n) => Some(n),
                Err(_) => {
                    self.error("int_parsing", campo, "Input should be a valid integer, unable to parse string as an integer", v);
                    None
                }
            },
            _ => {
                self.error("int_type", campo, "Input should be a valid integer", v);
                None
            }
        }
    }

    /// `campo: List[Dict[str, Any]]` (obligatorio)
    pub fn lista_de_dicts(&mut self, campo: &str) -> Vec<Valor> {
        match self.cuerpo.get(campo) {
            None => {
                self.falta(campo);
                Vec::new()
            }
            Some(Valor::Lista(l)) => {
                for (i, x) in l.iter().enumerate() {
                    if !matches!(x, Valor::Mapa(_)) {
                        self.errores.push(Error {
                            tipo: "dict_type",
                            loc: vec![Valor::Texto("body".into()), Valor::Texto(campo.into()), Valor::Entero(i as i128)],
                            msg: "Input should be a valid dictionary".into(),
                            entrada: x.clone(),
                            ctx: None,
                        });
                    }
                }
                l.clone()
            }
            Some(v) => {
                let v = v.clone();
                self.error("list_type", campo, "Input should be a valid list", v);
                Vec::new()
            }
        }
    }

    /// `campo: List[str]` (obligatorio)
    pub fn lista_de_textos(&mut self, campo: &str) -> Vec<String> {
        match self.cuerpo.get(campo) {
            None => {
                self.falta(campo);
                Vec::new()
            }
            Some(Valor::Lista(l)) => {
                let mut v = Vec::new();
                for (i, x) in l.iter().enumerate() {
                    match x {
                        Valor::Texto(t) => v.push(t.clone()),
                        _ => self.errores.push(Error {
                            tipo: "string_type",
                            loc: vec![Valor::Texto("body".into()), Valor::Texto(campo.into()), Valor::Entero(i as i128)],
                            msg: "Input should be a valid string".into(),
                            entrada: x.clone(),
                            ctx: None,
                        }),
                    }
                }
                v
            }
            Some(v) => {
                let v = v.clone();
                self.error("list_type", campo, "Input should be a valid list", v);
                Vec::new()
            }
        }
    }

    pub fn fin(self) -> Result<(), Response> {
        if self.errores.is_empty() {
            Ok(())
        } else {
            Err(respuesta(self.errores))
        }
    }
}

/// Un parámetro de consulta `int` con `ge`/`le`, validado como FastAPI (con sus 422)
pub fn entero_consulta(q: &std::collections::HashMap<String, String>, campo: &str, defecto: i64, ge: i64, le: i64) -> Result<i64, Response> {
    let Some(crudo) = q.get(campo) else { return Ok(defecto) };
    let loc = vec![Valor::Texto("query".into()), Valor::Texto(campo.into())];
    let n = match crudo.trim().parse::<i64>() {
        Ok(n) => n,
        Err(_) => {
            return Err(respuesta(vec![Error {
                tipo: "int_parsing",
                loc,
                msg: "Input should be a valid integer, unable to parse string as an integer".into(),
                entrada: Valor::Texto(crudo.clone()),
                ctx: None,
            }]))
        }
    };
    if n < ge {
        return Err(respuesta(vec![Error {
            tipo: "greater_than_equal",
            loc,
            msg: format!("Input should be greater than or equal to {ge}"),
            entrada: Valor::Texto(crudo.clone()),
            ctx: Some(Mapa::new().con("ge", Valor::Entero(ge as i128))),
        }]));
    }
    if n > le {
        return Err(respuesta(vec![Error {
            tipo: "less_than_equal",
            loc,
            msg: format!("Input should be less than or equal to {le}"),
            entrada: Valor::Texto(crudo.clone()),
            ctx: Some(Mapa::new().con("le", Valor::Entero(le as i128))),
        }]));
    }
    Ok(n)
}


/// `campo: Optional[bool] = None` (o `bool = defecto`) en la consulta, con la conversión de pydantic
pub fn booleano_consulta(q: &std::collections::HashMap<String, String>, campo: &str) -> Result<Option<bool>, Response> {
    let Some(crudo) = q.get(campo) else { return Ok(None) };
    match crudo.trim().to_lowercase().as_str() {
        "0" | "off" | "f" | "false" | "n" | "no" => Ok(Some(false)),
        "1" | "on" | "t" | "true" | "y" | "yes" => Ok(Some(true)),
        _ => Err(respuesta(vec![Error {
            tipo: "bool_parsing",
            loc: vec![Valor::Texto("query".into()), Valor::Texto(campo.into())],
            msg: "Input should be a valid boolean, unable to interpret input".into(),
            entrada: Valor::Texto(crudo.clone()),
            ctx: None,
        }])),
    }
}

/// `campo: str` obligatorio en la consulta
pub fn texto_consulta(q: &std::collections::HashMap<String, String>, campo: &str) -> Result<String, Response> {
    q.get(campo).cloned().ok_or_else(|| {
        respuesta(vec![Error { tipo: "missing", loc: vec![Valor::Texto("query".into()), Valor::Texto(campo.into())], msg: "Field required".into(), entrada: Valor::Nulo, ctx: None }])
    })
}

/// El mensaje de pydantic de un tipo de error de `validar_tipo`
pub fn mensaje(tipo: &str) -> &'static str {
    match tipo {
        "string_type" => "Input should be a valid string",
        "float_parsing" => "Input should be a valid number, unable to parse string as a number",
        "float_type" => "Input should be a valid number",
        "int_parsing" => "Input should be a valid integer, unable to parse string as an integer",
        "int_from_float" => "Input should be a valid integer, got a number with a fractional part",
        "int_type" => "Input should be a valid integer",
        "bool_parsing" => "Input should be a valid boolean, unable to interpret input",
        "dict_type" => "Input should be a valid dictionary",
        _ => "Input should be a valid boolean",
    }
}

/// Los campos de un modelo de pydantic, con todos sus errores juntos: los enviados, ya validados
/// (`exclude_unset`). `(campo, tipo, obligatorio)`
pub fn tipados(m: &Mapa, campos: &[(&str, &prig_plataforma::modelo::Tipo, bool)]) -> Result<Mapa, Response> {
    let (salida, errores) = tipados_con_errores(m, campos);
    if errores.is_empty() {
        Ok(salida)
    } else {
        Err(respuesta(errores))
    }
}

/// Como `tipados`, con los errores sueltos (para juntarlos con los de otros campos)
pub fn tipados_con_errores(m: &Mapa, campos: &[(&str, &prig_plataforma::modelo::Tipo, bool)]) -> (Mapa, Vec<Error>) {
    let mut salida = Mapa::new();
    let mut errores = Vec::new();
    for (k, t, obligatorio) in campos {
        let Some(v) = m.get(k) else {
            if *obligatorio {
                errores.push(Error { tipo: "missing", loc: loc(&["body", k]), msg: "Field required".into(), entrada: Valor::Mapa(m.clone()), ctx: None });
            }
            continue;
        };
        match prig_plataforma::modelo::validar_tipo(t, v.clone(), k) {
            Ok(x) => salida.poner(*k, x),
            Err(f) => errores.push(Error { tipo: f.tipo, loc: loc(&["body", k]), msg: mensaje(f.tipo).into(), entrada: v.clone(), ctx: None }),
        }
    }
    (salida, errores)
}
