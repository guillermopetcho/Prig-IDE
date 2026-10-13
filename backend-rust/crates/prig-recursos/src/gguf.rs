//! Lector mínimo de la cabecera GGUF (backend/recursos/gguf.py).
//!
//! Un GGUF empieza por sus metadatos: arquitectura, número de capas, cabezas de atención, contexto máximo, expertos.
//! Con eso se calcula exactamente cuánta caché KV ocupará el modelo. Solo se leen los metadatos, nunca los tensores:
//! el registro de Ollama sirve los blobs por rangos, así que de un modelo de 5 GB basta con sus primeros megas.

use crate::valor::{Mapa, Valor};

const MAGIA: &[u8] = b"GGUF";
const TIPO_CADENA: u32 = 8;
const TIPO_ARRAY: u32 = 9;

/// Arrays largos que no aportan nada a la calculadora (el vocabulario y las fusiones del tokenizador): se recorren,
/// porque hay que llegar a lo que viene detrás, pero no se guardan.
pub const NO_GUARDAR: &[&str] =
    &["tokenizer.ggml.tokens", "tokenizer.ggml.merges", "tokenizer.ggml.token_type", "tokenizer.ggml.scores"];

#[derive(Debug, Clone, PartialEq)]
pub enum ErrorGguf {
    /// El búfer se acabó antes que la cabecera: hay que pedir más
    FaltanBytes,
    /// No es un GGUF, o está roto (el ValueError de Python, con su mensaje)
    Invalido(String),
}

fn tamano_escalar(tipo: u32) -> Option<usize> {
    match tipo {
        0 | 1 | 7 => Some(1),
        2 | 3 => Some(2),
        4..=6 => Some(4),
        10..=12 => Some(8),
        _ => None,
    }
}

struct Lector<'a> {
    d: &'a [u8],
    p: usize,
}

impl<'a> Lector<'a> {
    fn tomar(&mut self, n: usize) -> Result<&'a [u8], ErrorGguf> {
        let fin = self.p.checked_add(n).filter(|&f| f <= self.d.len()).ok_or(ErrorGguf::FaltanBytes)?;
        let trozo = &self.d[self.p..fin];
        self.p = fin;
        Ok(trozo)
    }

    fn u32(&mut self) -> Result<u32, ErrorGguf> {
        Ok(u32::from_le_bytes(self.tomar(4)?.try_into().unwrap_or_default()))
    }

    fn u64(&mut self) -> Result<u64, ErrorGguf> {
        Ok(u64::from_le_bytes(self.tomar(8)?.try_into().unwrap_or_default()))
    }

    fn escalar(&mut self, tipo: u32) -> Result<Valor, ErrorGguf> {
        let n = tamano_escalar(tipo).ok_or_else(|| ErrorGguf::Invalido(format!("tipo GGUF desconocido: {tipo}")))?;
        let b = self.tomar(n)?;
        let arr = |k: usize| -> [u8; 8] {
            let mut a = [0u8; 8];
            a[..k].copy_from_slice(&b[..k]);
            a
        };
        Ok(match tipo {
            0 => Valor::Entero(b[0] as i128),
            1 => Valor::Entero(b[0] as i8 as i128),
            2 => Valor::Entero(u16::from_le_bytes([b[0], b[1]]) as i128),
            3 => Valor::Entero(i16::from_le_bytes([b[0], b[1]]) as i128),
            4 => Valor::Entero(u32::from_le_bytes([b[0], b[1], b[2], b[3]]) as i128),
            5 => Valor::Entero(i32::from_le_bytes([b[0], b[1], b[2], b[3]]) as i128),
            6 => Valor::Real(f32::from_le_bytes([b[0], b[1], b[2], b[3]]) as f64),
            7 => Valor::Bool(b[0] != 0),
            10 => Valor::Entero(u64::from_le_bytes(arr(8)) as i128),
            11 => Valor::Entero(i64::from_le_bytes(arr(8)) as i128),
            _ => Valor::Real(f64::from_le_bytes(arr(8))),
        })
    }

    fn cadena(&mut self) -> Result<String, ErrorGguf> {
        let n = self.u64()?;
        if n > 64 * 1024 * 1024 {
            return Err(ErrorGguf::Invalido("cadena GGUF imposible: archivo corrupto o no es GGUF".into()));
        }
        Ok(String::from_utf8_lossy(self.tomar(n as usize)?).into_owned())
    }

    fn valor(&mut self, tipo: u32, guardar: bool) -> Result<Valor, ErrorGguf> {
        if tamano_escalar(tipo).is_some() {
            return self.escalar(tipo);
        }
        if tipo == TIPO_CADENA {
            return Ok(Valor::Texto(self.cadena()?));
        }
        if tipo == TIPO_ARRAY {
            let sub = self.u32()?;
            let n = self.u64()?;
            if !guardar {
                // Saltarlo sin construir la lista: el vocabulario de Qwen son 150.000 cadenas
                match tamano_escalar(sub) {
                    Some(t) => {
                        let total = (t as u64).checked_mul(n).ok_or(ErrorGguf::FaltanBytes)?;
                        self.tomar(usize::try_from(total).map_err(|_| ErrorGguf::FaltanBytes)?)?;
                    }
                    None => {
                        for _ in 0..n {
                            self.valor(sub, false)?;
                        }
                    }
                }
                return Ok(Valor::Nulo);
            }
            let mut lista = Vec::new();
            for _ in 0..n {
                lista.push(self.valor(sub, true)?);
            }
            return Ok(Valor::Lista(lista));
        }
        Err(ErrorGguf::Invalido(format!("tipo GGUF desconocido: {tipo}")))
    }
}

/// Metadatos de una cabecera GGUF completa, con `_gguf_version`, `_tensores` y `_bytes_cabecera`
pub fn leer_metadatos(datos: &[u8]) -> Result<Mapa, ErrorGguf> {
    let mut r = Lector { d: datos, p: 0 };
    if r.tomar(4)? != MAGIA {
        return Err(ErrorGguf::Invalido("no es un archivo GGUF".into()));
    }
    let version = r.u32()?;
    if version != 2 && version != 3 {
        return Err(ErrorGguf::Invalido(format!("versión de GGUF no soportada: {version}")));
    }
    let n_tensores = r.u64()?;
    let n_claves = r.u64()?;
    let mut meta = Mapa::new().con("_gguf_version", version).con("_tensores", n_tensores);
    for _ in 0..n_claves {
        let clave = r.cadena()?;
        let tipo = r.u32()?;
        let guardar = !NO_GUARDAR.iter().any(|p| clave.starts_with(p));
        let valor = r.valor(tipo, guardar)?;
        if guardar {
            meta.poner(clave, valor);
        }
    }
    meta.poner("_bytes_cabecera", r.p);
    Ok(meta)
}

/// Un error al leer por rangos: el de quien da los bytes, o el de la cabecera
#[derive(Debug)]
pub enum ErrorRangos<E> {
    Pedir(E),
    Gguf(ErrorGguf),
}

/// Lee la cabecera pidiendo bytes por rangos, cada vez más (empieza por `inicial` y dobla), hasta que llega o se
/// pasa de `maximo`. `pedir(desde, hasta)` devuelve los bytes de ese rango.
pub fn leer_con_rangos<E>(
    mut pedir: impl FnMut(usize, usize) -> Result<Vec<u8>, E>,
    inicial: usize,
    maximo: usize,
) -> Result<Mapa, ErrorRangos<E>> {
    let mut tam = inicial;
    let mut datos: Vec<u8> = Vec::new();
    loop {
        if datos.len() < tam {
            let trozo = pedir(datos.len(), tam.saturating_sub(1)).map_err(ErrorRangos::Pedir)?;
            datos.extend_from_slice(&trozo);
        }
        match leer_metadatos(&datos) {
            Err(ErrorGguf::FaltanBytes) => {
                if tam >= maximo {
                    return Err(ErrorRangos::Gguf(ErrorGguf::Invalido(format!(
                        "la cabecera GGUF ocupa más de {} MB",
                        maximo / 1024 / 1024
                    ))));
                }
                tam = (tam * 2).min(maximo);
            }
            otro => return otro.map_err(ErrorRangos::Gguf),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn cadena(t: &str) -> Vec<u8> {
        let mut v = (t.len() as u64).to_le_bytes().to_vec();
        v.extend_from_slice(t.as_bytes());
        v
    }

    fn gguf(pares: &[(&str, u32, Vec<u8>)]) -> Vec<u8> {
        let mut v = b"GGUF".to_vec();
        v.extend_from_slice(&3u32.to_le_bytes());
        v.extend_from_slice(&0u64.to_le_bytes());
        v.extend_from_slice(&(pares.len() as u64).to_le_bytes());
        for (k, t, val) in pares {
            v.extend(cadena(k));
            v.extend_from_slice(&t.to_le_bytes());
            v.extend_from_slice(val);
        }
        v
    }

    #[test]
    fn lee_y_salta_el_vocabulario() {
        let mut tokens = 9u32.to_le_bytes().to_vec(); // array de cadenas
        tokens.extend_from_slice(&TIPO_CADENA.to_le_bytes());
        tokens.extend_from_slice(&2u64.to_le_bytes());
        tokens.extend(cadena("a"));
        tokens.extend(cadena("b"));
        let datos = gguf(&[
            ("general.architecture", TIPO_CADENA, cadena("qwen3")),
            ("qwen3.block_count", 4, 48u32.to_le_bytes().to_vec()),
            ("tokenizer.ggml.tokens", TIPO_ARRAY, tokens[4..].to_vec()),
            ("qwen3.rope.freq_base", 6, 1_000_000f32.to_le_bytes().to_vec()),
        ]);
        let meta = leer_metadatos(&datos).unwrap();
        assert_eq!(meta.texto("general.architecture"), Some("qwen3"));
        assert_eq!(meta.valor("qwen3.block_count"), &Valor::Entero(48));
        assert!(!meta.contiene("tokenizer.ggml.tokens"));
        assert_eq!(meta.valor("_bytes_cabecera"), &Valor::Entero(datos.len() as i128));
        // por rangos, empezando por muy poco
        let r: Result<Mapa, ErrorRangos<()>> =
            leer_con_rangos(|d, h| Ok(datos[d.min(datos.len())..(h + 1).min(datos.len())].to_vec()), 16, 1 << 20);
        assert_eq!(r.unwrap(), meta);
        assert_eq!(leer_metadatos(&datos[..20]), Err(ErrorGguf::FaltanBytes));
        assert!(matches!(leer_metadatos(b"PK\x03\x04aaaaaaaaaaaaaaaaaaaaa"), Err(ErrorGguf::Invalido(_))));
    }
}
