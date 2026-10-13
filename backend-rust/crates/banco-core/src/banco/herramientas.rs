//! Consultas para las herramientas del chat y el estado (BancoProyecto: ver_simbolo, quien_usa,
//! resumen_archivo, texto_cambios, recordar, estado).

use rusqlite::params;
use serde_json::{json, Value};

use super::busqueda::numero;
use super::{descomprimir, error, filas, Banco, Resultado};
use crate::extraer::generico::primera_linea;
use crate::py::cadena::{primeros, rstrip_de, splitlines, strip, strip_de};
use crate::py::numero::round;

fn s(v: &Value) -> String {
    match v {
        Value::Null => "None".into(),
        Value::String(x) => x.clone(),
        otro => otro.to_string(),
    }
}

fn limpiar_nombre(nombre: &str) -> String {
    rstrip_de(strip_de(strip(nombre), "`"), "()").to_string()
}

impl Banco {
    /// `ver_simbolo`: el código de un símbolo con números de línea y cuántas llamadas tiene.
    pub fn ver_simbolo(&self, nombre: &str, maximo: i64) -> Resultado<String> {
        let nombre = limpiar_nombre(nombre);
        let c = self.conectar()?;
        let corto = nombre.rsplit('.').next().unwrap_or(&nombre).to_string();
        let como = format!("%.{nombre}");
        let lista = filas(
            &c,
            "SELECT ruta, nombre, tipo, firma, ini, fin FROM simbolos
                                 WHERE nombre = ? OR corto = ? OR nombre LIKE ? ORDER BY (nombre = ?) DESC, ruta
                                 LIMIT ?",
            &[&nombre, &corto, &como, &nombre, &maximo],
        )?;
        if lista.is_empty() {
            return Ok(format!("No hay ningún símbolo llamado «{nombre}». Prueba buscar_proyecto."));
        }
        let mut partes = vec![];
        for x in &lista {
            let ruta = s(&x["ruta"]);
            let ini = x["ini"].as_i64().unwrap_or(0);
            let fin_s = x["fin"].as_i64().unwrap_or(0);
            let blob: Option<Vec<u8>> = c.query_row("SELECT contenido FROM archivos WHERE ruta = ?", params![ruta], |f| f.get(0)).ok().flatten();
            let texto = blob.map(|b| descomprimir(&b)).unwrap_or_default();
            let lineas = splitlines(&texto);
            let fin = fin_s.min(ini + 400);
            let mut cuerpo = vec![];
            for n in ini..=fin {
                if n >= 1 && (n as usize) <= lineas.len() {
                    cuerpo.push(format!("{:>5}  {}", n, lineas[(n - 1) as usize]));
                }
            }
            let n_usos: i64 = c
                .query_row("SELECT COUNT(*) n FROM llamadas WHERE a_ruta = ? AND a_nombre = ?", params![ruta, s(&x["nombre"])], |f| f.get(0))
                .map_err(error)?;
            let mut parte = format!("{ruta}:{ini}-{fin_s} ({}, {n_usos} llamadas en el proyecto)\n{}", s(&x["tipo"]), cuerpo.join("\n"));
            if fin < fin_s {
                parte.push_str("\n[… recortado]");
            }
            partes.push(parte);
        }
        Ok(partes.join("\n\n"))
    }

    /// `quien_usa`: las llamadas resueltas a un nombre.
    pub fn quien_usa(&self, nombre: &str, maximo: i64) -> Resultado<String> {
        let nombre = limpiar_nombre(nombre);
        let c = self.conectar()?;
        let corto = nombre.rsplit('.').next().unwrap_or(&nombre).to_string();
        let como = format!("%.{corto}");
        let lista = filas(
            &c,
            "SELECT l.ruta, l.desde, l.linea, l.a_nombre FROM llamadas l
                                 WHERE l.a_nombre = ? OR l.a_nombre LIKE ? ORDER BY l.ruta, l.linea LIMIT ?",
            &[&nombre, &como, &maximo],
        )?;
        if lista.is_empty() {
            return Ok(format!("Nadie llama a «{nombre}» en el proyecto (o se usa de forma dinámica)."));
        }
        let mut salida = vec![format!("Llamadas a {nombre}:")];
        for f in &lista {
            salida.push(format!("- {}:{} dentro de {} → {}", s(&f["ruta"]), s(&f["linea"]), s(&f["desde"]), s(&f["a_nombre"])));
        }
        Ok(salida.join("\n"))
    }

    /// `resumen_archivo`.
    pub fn resumen_archivo(&self, ruta: &str) -> Resultado<String> {
        let c = self.conectar()?;
        // La ruta tal cual primero: strip("./") le quita el punto a un archivo oculto (`.env` → `env`)
        let tal_cual = strip(ruta).to_string();
        let mut ruta = strip_de(&tal_cual, "./").to_string();
        if ruta != tal_cual && !filas(&c, "SELECT 1 FROM archivos WHERE ruta = ?", &[&tal_cual])?.is_empty() {
            ruta = tal_cual;
        }
        let mut a = filas(&c, "SELECT * FROM archivos WHERE ruta = ?", &[&ruta])?.into_iter().next();
        let mut cands: Vec<String> = vec![];
        if a.is_none() {
            let como = format!("%{ruta}");
            let mut st = c.prepare("SELECT ruta FROM archivos WHERE ruta LIKE ? LIMIT 5").map_err(error)?;
            cands = st.query_map(params![como], |f| f.get::<_, String>(0)).map_err(error)?.collect::<rusqlite::Result<Vec<_>>>().map_err(error)?;
            if cands.len() == 1 {
                // Python se llamaba a sí mismo con el candidato, que volvía a recortar: con `.env` no terminaba nunca
                // (RecursionError en Python; en Rust, la pila desbordada tiraba el proceso). Se usa el candidato tal cual
                a = filas(&c, "SELECT * FROM archivos WHERE ruta = ?", &[&cands[0]])?.into_iter().next();
                if a.is_some() {
                    ruta = cands[0].clone();
                }
            }
        }
        let Some(a) = a else {
            let mut t = format!("No está en el banco: {ruta}");
            if !cands.is_empty() {
                t.push_str(&format!(". ¿Quisiste decir {}?", cands.join(", ")));
            }
            return Ok(t);
        };
        let sims = filas(&c, "SELECT nombre, tipo, firma, doc, ini, fin FROM simbolos WHERE ruta = ? ORDER BY ini", &[&ruta])?;
        let importa: Vec<String> = filas(&c, "SELECT destino FROM importaciones WHERE ruta = ?", &[&ruta])?.iter().map(|f| s(&f["destino"])).collect();
        let importado: Vec<String> = filas(&c, "SELECT ruta FROM importaciones WHERE destino = ?", &[&ruta])?.iter().map(|f| s(&f["ruta"])).collect();
        let ultimos = filas(&c, "SELECT cuando, tipo, mas, menos FROM cambios WHERE ruta = ? ORDER BY id DESC LIMIT 3", &[&ruta])?;
        let mut salida = vec![format!("{ruta} ({}, {} líneas, ~{} tokens)", s(&a["lenguaje"]), s(&a["lineas"]), s(&a["tokens"]))];
        let resumen = [a.get("resumen_ia"), a.get("resumen")].into_iter().flatten().find(|v| v.as_str().map(|x| !x.is_empty()).unwrap_or(false)).cloned();
        if let Some(r) = resumen {
            salida.push(format!("Resumen: {}", s(&r)));
        }
        if !sims.is_empty() {
            salida.push("Símbolos:".into());
            for x in sims.iter().take(120) {
                let doc = match x["doc"].as_str() {
                    Some(d) if !d.is_empty() => format!(" — {}", primera_linea(d, 100)),
                    _ => String::new(),
                };
                salida.push(format!("  l.{}-{} {}{doc}", s(&x["ini"]), s(&x["fin"]), s(&x["firma"])));
            }
        }
        if !importa.is_empty() {
            salida.push(format!("Importa: {}", importa.join(", ")));
        }
        if !importado.is_empty() {
            salida.push(format!("Lo importan: {}", importado.join(", ")));
        }
        if !ultimos.is_empty() {
            let u: Vec<String> = ultimos.iter().map(|u| format!("{} {} +{} −{}", s(&u["cuando"]), s(&u["tipo"]), s(&u["mas"]), s(&u["menos"]))).collect();
            salida.push(format!("Últimos cambios: {}", u.join("; ")));
        }
        Ok(salida.join("\n"))
    }

    /// `texto_cambios`.
    pub fn texto_cambios(&self, limite: i64) -> Resultado<String> {
        let cambios: Vec<Value> = self.cambios_desde(0.max(self.version()? - 50), limite * 3)?.into_iter().take(limite.max(0) as usize).collect();
        if cambios.is_empty() {
            return Ok("No hay cambios registrados desde que se indexó el proyecto.".into());
        }
        let mut salida = vec![];
        for ch in &cambios {
            let mut toc = vec![];
            if let Some(m) = ch["simbolos"].as_object() {
                for (k, v) in m {
                    if let Some(xs) = v.as_array().filter(|x| !x.is_empty()) {
                        let l: Vec<String> = xs.iter().take(6).map(s).collect();
                        toc.push(format!("{k}: {}", l.join(", ")));
                    }
                }
            }
            let mut l = format!("- {} {}: {} (+{} −{})", s(&ch["cuando"]), s(&ch["ruta"]), s(&ch["tipo"]), s(&ch["mas"]), s(&ch["menos"]));
            if !toc.is_empty() {
                l.push_str(&format!(" · {}", toc.join("; ")));
            }
            salida.push(l);
            if let Some(d) = ch["diff"].as_str().filter(|d| !d.is_empty()) {
                salida.push(format!("```diff\n{}\n```", primeros(d, 1200)));
            }
        }
        Ok(salida.join("\n"))
    }

    /// `recordar` con el vector de la consulta ya calculado.
    pub fn recordar(&self, consulta: &str, vector: Option<&[f64]>) -> Resultado<String> {
        let conocimiento = self.buscar_conocimiento(consulta, 8, vector, None)?;
        let resoluciones = self.buscar_resoluciones(consulta, 5, vector)?;
        if conocimiento.is_empty() && resoluciones.is_empty() {
            return Ok("No hay nada guardado sobre eso.".into());
        }
        let mut salida = vec![];
        for k in &conocimiento {
            let revisar = k["revisar"].as_i64().unwrap_or(0) != 0;
            salida.push(format!("- ({}) {}: {}{}", s(&k["tipo"]), s(&k["titulo"]), s(&k["texto"]), if revisar { " [puede estar desactualizado]" } else { "" }));
        }
        for r in &resoluciones {
            let cambiaron: Vec<String> = r["cambiaron_despues"].as_array().map(|xs| xs.iter().map(s).collect()).unwrap_or_default();
            let despues = if cambiaron.is_empty() { String::new() } else { format!(" [después cambiaron: {}]", cambiaron.join(", ")) };
            salida.push(format!("- (resolución {}) «{}» → {}{despues}", primeros(&s(&r["cuando"]), 10), primeros(&s(&r["pregunta"]), 200), s(&r["resumen"])));
        }
        Ok(salida.join("\n"))
    }

    /// `estado`: conteos del banco.
    pub fn estado(&self) -> Resultado<Value> {
        let c = self.conectar()?;
        let cuenta = |sql: &str| -> Resultado<i64> { c.query_row(sql, [], |f| f.get(0)).map_err(error) };
        let actualizado: Option<String> = c.query_row("SELECT valor FROM meta WHERE clave = 'actualizado'", [], |f| f.get(0)).ok();
        let vista: i64 = c
            .query_row("SELECT valor FROM meta WHERE clave = 'version_vista'", [], |f| f.get::<_, String>(0))
            .ok()
            .and_then(|v| v.trim().parse().ok())
            .unwrap_or(0);
        let mut datos = json!({
            "raiz": self.raiz, "carpeta": self.carpeta, "version": self.version()?,
            "archivos": cuenta("SELECT COUNT(*) FROM archivos")?,
            "lineas": cuenta("SELECT COALESCE(SUM(lineas), 0) FROM archivos")?,
            "tokens": cuenta("SELECT COALESCE(SUM(tokens), 0) FROM archivos")?,
            "simbolos": cuenta("SELECT COUNT(*) FROM simbolos")?,
            "fragmentos": cuenta("SELECT COUNT(*) FROM fragmentos")?,
            "vectores": cuenta("SELECT COUNT(*) FROM vectores")?,
            "conocimiento": cuenta("SELECT COUNT(*) FROM conocimiento")?,
            "conocimiento_revisar": cuenta("SELECT COUNT(*) FROM conocimiento WHERE revisar > 0")?,
            "resoluciones": cuenta("SELECT COUNT(*) FROM resoluciones")?,
            "cambios": cuenta("SELECT COUNT(*) FROM cambios")?,
            "analizados": cuenta("SELECT COUNT(*) FROM archivos WHERE analizado_sha = sha")?,
            "actualizado": actualizado,
            "version_vista": vista,
        });
        let o = datos.as_object_mut().unwrap();
        o.insert("vectores_pendientes".into(), Value::from(self.vectores_pendientes()?));
        o.insert("pendientes_analisis".into(), Value::from(self.pendientes_de_analisis()?.len()));
        o.insert("hechos".into(), Value::from(cuenta("SELECT COUNT(*) FROM hechos")?));
        o.insert("resumenes_carpeta".into(), Value::from(cuenta("SELECT COUNT(*) FROM resumenes WHERE nivel = 'carpeta'")?));
        o.insert("resumen_proyecto".into(), Value::from(c.query_row("SELECT 1 FROM resumenes WHERE nivel = 'proyecto'", [], |_| Ok(())).is_ok()));
        o.insert("trabajo_guardado".into(), Value::from(cuenta("SELECT COUNT(*) FROM trabajo")?));
        o.insert("carpetas_pendientes".into(), self.trabajo_pendiente()?["carpetas"].clone());
        let mb = match std::fs::read_dir(&self.carpeta) {
            Ok(entradas) => {
                let total: u64 = entradas.flatten().filter_map(|e| std::fs::metadata(e.path()).ok()).map(|m| m.len()).sum();
                numero(round(total as f64 / 1e6, 1))
            }
            Err(_) => Value::from(0),
        };
        o.insert("mb".into(), mb);
        Ok(datos)
    }
}
