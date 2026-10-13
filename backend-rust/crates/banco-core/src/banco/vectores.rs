//! Vectores del banco (BancoProyecto.vectores_pendientes, indexar_vectores, _empaquetar): lo que falta
//! embeber y cómo se guarda (float32 normalizado). El embebedor (HTTP a Ollama) lo llama Python.

use rusqlite::params;

use super::{error, Banco, Resultado};
use crate::py::cadena::primeros;
use crate::py::numero::suma;

/// `_empaquetar`: el vector normalizado, en float32 (array("f").tobytes()).
pub fn empaquetar(v: &[f64]) -> Vec<u8> {
    let norma = suma(v.iter().map(|x| x * x)).sqrt();
    let norma = if norma == 0.0 { 1.0 } else { norma };
    let mut salida = Vec::with_capacity(v.len() * 4);
    for x in v {
        salida.extend_from_slice(&((x / norma) as f32).to_le_bytes());
    }
    salida
}

/// La norma de `_vector_consulta`: [x / norma for x in v].
pub fn normalizar(v: &[f64]) -> Vec<f64> {
    let norma = suma(v.iter().map(|x| x * x)).sqrt();
    let norma = if norma == 0.0 { 1.0 } else { norma };
    v.iter().map(|x| x / norma).collect()
}

impl Banco {
    pub fn vectores_pendientes(&self) -> Resultado<i64> {
        let c = self.conectar()?;
        let f: i64 = c
            .query_row("SELECT COUNT(DISTINCT sha) n FROM fragmentos WHERE 'f:' || sha NOT IN (SELECT clave FROM vectores)", [], |r| r.get(0))
            .map_err(error)?;
        let g: i64 = c.query_row("SELECT COUNT(*) n FROM conocimiento WHERE 'c:' || id NOT IN (SELECT clave FROM vectores)", [], |r| r.get(0)).map_err(error)?;
        let h: i64 = c.query_row("SELECT COUNT(*) n FROM resoluciones WHERE 'r:' || id NOT IN (SELECT clave FROM vectores)", [], |r| r.get(0)).map_err(error)?;
        Ok(f + g + h)
    }

    /// Lo que `indexar_vectores` mandaría a embeber: (clave, texto), hasta `maximo`.
    pub fn vectores_por_hacer(&self, maximo: i64) -> Resultado<Vec<(String, String)>> {
        let c = self.conectar()?;
        let mut filas: Vec<(String, String)> = vec![];
        {
            let mut st = c
                .prepare(
                    "SELECT ruta, simbolo, texto, sha FROM fragmentos
                                          WHERE 'f:' || sha NOT IN (SELECT clave FROM vectores)
                                          GROUP BY sha LIMIT ?",
                )
                .map_err(error)?;
            let v = st
                .query_map(params![maximo], |f| {
                    let ruta: Option<String> = f.get(0)?;
                    let simbolo: Option<String> = f.get(1)?;
                    let texto: Option<String> = f.get(2)?;
                    let sha: Option<String> = f.get(3)?;
                    let t = format!("{} {}\n{}", ruta.unwrap_or_else(|| "None".into()), simbolo.unwrap_or_default(), texto.unwrap_or_else(|| "None".into()));
                    Ok((format!("f:{}", sha.unwrap_or_else(|| "None".into())), primeros(&t, 1800).to_string()))
                })
                .map_err(error)?
                .collect::<rusqlite::Result<Vec<_>>>()
                .map_err(error)?;
            filas.extend(v);
        }
        if (filas.len() as i64) < maximo {
            let mut st = c.prepare("SELECT id, titulo, texto FROM conocimiento WHERE 'c:' || id NOT IN (SELECT clave FROM vectores) LIMIT ?").map_err(error)?;
            let v = st
                .query_map(params![maximo - filas.len() as i64], |f| {
                    let id: i64 = f.get(0)?;
                    let t = format!("{}\n{}", f.get::<_, Option<String>>(1)?.unwrap_or_else(|| "None".into()), f.get::<_, Option<String>>(2)?.unwrap_or_else(|| "None".into()));
                    Ok((format!("c:{id}"), primeros(&t, 1500).to_string()))
                })
                .map_err(error)?
                .collect::<rusqlite::Result<Vec<_>>>()
                .map_err(error)?;
            filas.extend(v);
        }
        if (filas.len() as i64) < maximo {
            let mut st = c.prepare("SELECT id, pregunta, resumen FROM resoluciones WHERE 'r:' || id NOT IN (SELECT clave FROM vectores) LIMIT ?").map_err(error)?;
            let v = st
                .query_map(params![maximo - filas.len() as i64], |f| {
                    let id: i64 = f.get(0)?;
                    let t = format!("{}\n{}", f.get::<_, Option<String>>(1)?.unwrap_or_else(|| "None".into()), f.get::<_, Option<String>>(2)?.unwrap_or_else(|| "None".into()));
                    Ok((format!("r:{id}"), primeros(&t, 1500).to_string()))
                })
                .map_err(error)?
                .collect::<rusqlite::Result<Vec<_>>>()
                .map_err(error)?;
            filas.extend(v);
        }
        Ok(filas)
    }

    /// Guarda una tanda de vectores (INSERT OR REPLACE, normalizados a float32).
    pub fn guardar_vectores(&self, tanda: &[(String, Vec<f64>)]) -> Resultado<()> {
        let mut c = self.conectar()?;
        let tx = c.transaction_with_behavior(rusqlite::TransactionBehavior::Immediate).map_err(error)?;
        for (clave, v) in tanda {
            tx.execute("INSERT OR REPLACE INTO vectores VALUES (?,?,?)", params![clave, empaquetar(v), self.modelo_vectores]).map_err(error)?;
        }
        tx.commit().map_err(error)?;
        self.invalidar_vectores();
        Ok(())
    }

    /// `bool(self._cargar_vectores())`: hay vectores guardados.
    pub fn hay_vectores(&self) -> Resultado<bool> {
        Ok(!self.cargar_vectores()?.is_empty())
    }
}
