//! Lo que el gestor de recursos recuerda entre sesiones (backend/recursos/almacen.py).
//!
//! Todo va en un único JSON (~/.prig_recursos.json) escrito de forma atómica: se escribe a un temporal y se renombra,
//! así un corte de luz a mitad no deja un archivo roto que haga perder la calibración. El archivo sale byte a byte
//! igual que lo escribía Python (`json.dump(..., ensure_ascii=False, indent=1)`, permisos 0600 de `mkstemp`).
//!
//! Las medidas se guardan POR HUELLA de máquina (GPU, driver, CPU, RAM, versión de Ollama). Si la huella cambia, lo
//! medido deja de aplicarse, pero no se borra: si se vuelve a la configuración anterior, las medidas vuelven a valer
//! sin recalibrar. Los ajustes que el usuario escribe a mano nunca se sobrescriben en silencio: «Aplicar» guarda una
//! copia de lo que había para poder «Restaurar».

use crate::json;
use crate::valor::{Mapa, Valor};
use std::ffi::CString;
use std::io::{self, Write};
use std::os::unix::ffi::OsStrExt;
use std::os::unix::io::FromRawFd;
use std::path::{Path, PathBuf};
use std::sync::{Mutex, MutexGuard};
use std::time::{SystemTime, UNIX_EPOCH};

pub const VERSION: i64 = 1;
pub const MAX_HUELLAS: usize = 5;
pub const MAX_EVENTOS: usize = 200;
pub const MAX_PRUEBAS_POR_HUELLA: usize = 60;

fn vacio() -> Mapa {
    Mapa::new()
        .con("version", VERSION)
        .con("huella_actual", Valor::Nulo)
        .con("radiografia", Valor::Nulo)
        .con("maquinas", Mapa::new()) // huella -> {calibracion, pruebas, vista}
        .con("aplicado", Mapa::new()) // perfil -> {modelo, opciones, fecha, anterior}
        .con("ultima_buena", Mapa::new()) // perfil -> {modelo, opciones, fecha, huella}
        .con("entorno_servidor", Mapa::new()) // OLLAMA_* que Prig pone al arrancar su servidor
        .con("termico", Mapa::new()) // límite de la GPU y lo aprendido por el gobernador
        .con("eventos", Valor::Lista(vec![]))
}

/// `PRIG_RECURSOS_ARCHIVO` o ~/.prig_recursos.json
pub fn ruta_por_defecto() -> PathBuf {
    match std::env::var_os("PRIG_RECURSOS_ARCHIVO") {
        Some(r) if !r.is_empty() => PathBuf::from(r),
        _ => PathBuf::from(std::env::var_os("HOME").unwrap_or_default()).join(".prig_recursos.json"),
    }
}

/// `time.strftime("%Y-%m-%dT%H:%M:%S")`: la hora local
pub fn ahora() -> String {
    // SAFETY: localtime_r escribe en la estructura que se le da; strftime, en el búfer con su tamaño
    unsafe {
        let t = libc::time(std::ptr::null_mut());
        let mut tm: libc::tm = std::mem::zeroed();
        libc::localtime_r(&t, &mut tm);
        let mut b = [0u8; 32];
        let n = libc::strftime(b.as_mut_ptr() as *mut libc::c_char, b.len(), c"%Y-%m-%dT%H:%M:%S".as_ptr(), &tm);
        String::from_utf8_lossy(&b[..n]).into_owned()
    }
}

/// El almacén del proceso (`almacen()` de Python): el de `ruta_por_defecto()`, reabierto si esa ruta cambia
pub fn global() -> std::sync::Arc<Almacen> {
    static GLOBAL: Mutex<Option<std::sync::Arc<Almacen>>> = Mutex::new(None);
    let ruta = ruta_por_defecto();
    let mut g = GLOBAL.lock().unwrap_or_else(|e| e.into_inner());
    match g.as_ref() {
        Some(a) if a.ruta == ruta => a.clone(),
        _ => {
            let a = std::sync::Arc::new(Almacen::abrir(&ruta));
            *g = Some(a.clone());
            a
        }
    }
}

pub struct Almacen {
    ruta: PathBuf,
    datos: Mutex<Mapa>,
    /// Cómo estaba el archivo la última vez que se leyó o escribió: si otro proceso de Prig lo cambia (el servidor de
    /// Rust y el backend de Python lo comparten mientras conviven), se relee antes de usarlo y no se pisa lo suyo
    firma: Mutex<Option<Firma>>,
}

type Firma = (SystemTime, u64, u64);

fn firma(ruta: &Path) -> Option<Firma> {
    use std::os::unix::fs::MetadataExt;
    let m = std::fs::metadata(ruta).ok()?;
    Some((m.modified().ok()?, m.len(), m.ino()))
}

/// `d.setdefault(clave, {})` que devuelve el mapa (si la clave tiene otra cosa, se reemplaza por un mapa)
fn mapa_de<'a>(d: &'a mut Mapa, clave: &str) -> &'a mut Mapa {
    if !matches!(d.get(clave), Some(Valor::Mapa(_))) {
        d.poner(clave, Mapa::new());
    }
    match d.get_mut(clave) {
        Some(Valor::Mapa(m)) => m,
        _ => unreachable!(),
    }
}

fn texto_o_vacio(v: Option<&Valor>) -> String {
    match v {
        Some(Valor::Texto(t)) => t.clone(),
        _ => String::new(),
    }
}

/// `lista[-n:]` de Python
fn ultimos(l: &[Valor], n: i64) -> &[Valor] {
    let largo = l.len() as i64;
    let inicio = if n == 0 {
        0
    } else if n > 0 {
        (largo - n).max(0)
    } else {
        (-n).min(largo)
    };
    &l[inicio as usize..]
}

impl Almacen {
    pub fn abrir(ruta: &Path) -> Almacen {
        let f = firma(ruta);
        Almacen { ruta: ruta.to_path_buf(), datos: Mutex::new(Self::leer(ruta)), firma: Mutex::new(f) }
    }

    pub fn ruta(&self) -> &Path {
        &self.ruta
    }

    fn cerrojo(&self) -> MutexGuard<'_, Mapa> {
        let mut d = self.datos.lock().unwrap_or_else(|e| e.into_inner());
        let ahora = firma(&self.ruta);
        let mut previa = self.firma.lock().unwrap_or_else(|e| e.into_inner());
        if ahora.is_some() && ahora != *previa {
            *d = Self::leer(&self.ruta);
            *previa = firma(&self.ruta);
        }
        d
    }

    // -------------------------------------------------------------- disco
    fn leer(ruta: &Path) -> Mapa {
        let datos = match std::fs::read(ruta) {
            Err(e) if e.kind() == io::ErrorKind::NotFound => return vacio(),
            Err(_) => None,
            Ok(bytes) => String::from_utf8(bytes).ok().and_then(|t| json::leer(&t).ok()).and_then(|v| match v {
                Valor::Mapa(m) if m.get("version") == Some(&Valor::Entero(VERSION as i128)) => Some(m),
                _ => None,
            }),
        };
        let Some(mut datos) = datos else {
            // Archivo roto o de otra versión: se aparta, no se pisa sin más
            let segundos = SystemTime::now().duration_since(UNIX_EPOCH).map(|d| d.as_secs()).unwrap_or(0);
            let mut apartado = ruta.as_os_str().to_owned();
            apartado.push(format!(".roto-{segundos}"));
            let _ = std::fs::rename(ruta, apartado);
            return vacio();
        };
        for (clave, valor) in vacio().iter() {
            if !datos.contiene(clave) {
                datos.poner(clave.clone(), valor.clone());
            }
        }
        datos
    }

    fn guardar(&self, datos: &Mapa) -> io::Result<()> {
        let absoluta = if self.ruta.is_absolute() { self.ruta.clone() } else { std::env::current_dir()?.join(&self.ruta) };
        let carpeta = absoluta.parent().map(Path::to_path_buf).unwrap_or_else(|| PathBuf::from("/"));
        std::fs::create_dir_all(&carpeta)?;
        let plantilla = CString::new(carpeta.join(".prig_recursos.XXXXXX").as_os_str().as_bytes())
            .map_err(|e| io::Error::new(io::ErrorKind::InvalidInput, e))?;
        let mut bytes = plantilla.into_bytes_with_nul();
        // SAFETY: mkstemp cambia las X de la plantilla (terminada en NUL) y abre el archivo con permisos 0600
        let fd = unsafe { libc::mkstemp(bytes.as_mut_ptr() as *mut libc::c_char) };
        if fd < 0 {
            return Err(io::Error::last_os_error());
        }
        bytes.pop();
        let tmp = PathBuf::from(std::ffi::OsStr::from_bytes(&bytes));
        // SAFETY: el descriptor es nuestro y pasa a ser del File
        let mut f = unsafe { std::fs::File::from_raw_fd(fd) };
        let resultado = f
            .write_all(json::escribir(&Valor::Mapa(datos.clone()), 1).as_bytes())
            .and_then(|_| f.flush())
            .and_then(|_| f.sync_all());
        drop(f);
        let resultado = resultado.and_then(|_| std::fs::rename(&tmp, &self.ruta));
        if resultado.is_err() {
            let _ = std::fs::remove_file(&tmp);
        } else {
            *self.firma.lock().unwrap_or_else(|e| e.into_inner()) = firma(&self.ruta);
        }
        resultado
    }

    // -------------------------------------------------------------- piezas internas (con el cerrojo ya tomado)

    /// `_maquina(huella, crear)`: la entrada de esa huella. Sin huella (o si no existe y no se crea) se trabaja
    /// sobre un mapa suelto que no se guarda, como el `{}` de Python.
    fn con_maquina<T>(d: &mut Mapa, huella: Option<&str>, crear: bool, f: impl FnOnce(&mut Mapa) -> T) -> T {
        let Some(h) = huella.filter(|h| !h.is_empty()) else { return f(&mut Mapa::new()) };
        let maquinas = mapa_de(d, "maquinas");
        if !maquinas.contiene(h) && crear {
            maquinas.poner(
                h,
                Mapa::new().con("calibracion", Valor::Nulo).con("pruebas", Mapa::new()).con("vista", ahora()),
            );
        }
        match maquinas.get_mut(h) {
            Some(Valor::Mapa(m)) => f(m),
            _ => f(&mut Mapa::new()),
        }
    }

    /// La clave de una huella en «maquinas» (Python usa el valor tal cual; en JSON acaba siendo texto)
    fn clave_huella(huella: &Valor) -> Option<String> {
        match huella {
            Valor::Texto(t) => Some(t.clone()),
            v if v.verdad() => Some(v.texto_py()),
            _ => None,
        }
    }

    fn huella(d: &Mapa) -> Option<String> {
        match d.get("huella_actual") {
            Some(Valor::Texto(t)) => Some(t.clone()),
            _ => None,
        }
    }

    fn evento_en(d: &mut Mapa, tipo: &str, texto: &str, datos: Option<Valor>) {
        let mut e = Mapa::new().con("fecha", ahora()).con("tipo", tipo).con("texto", texto);
        if let Some(datos) = datos.filter(Valor::verdad) {
            e.poner("datos", datos);
        }
        if !matches!(d.get("eventos"), Some(Valor::Lista(_))) {
            d.poner("eventos", Valor::Lista(vec![]));
        }
        if let Some(Valor::Lista(l)) = d.get_mut("eventos") {
            l.push(e.into());
            if l.len() > MAX_EVENTOS {
                l.drain(..l.len() - MAX_EVENTOS);
            }
        }
    }

    fn podar_huellas(d: &mut Mapa) {
        let actual = d.get("huella_actual").cloned();
        let maquinas = mapa_de(d, "maquinas");
        if maquinas.len() <= MAX_HUELLAS {
            return;
        }
        let mut viejas: Vec<(String, String)> = maquinas
            .iter()
            .filter(|(h, _)| actual.as_ref() != Some(&Valor::Texto((*h).clone())))
            .map(|(h, m)| {
                let vista = match m {
                    Valor::Mapa(m) => texto_o_vacio(m.get("vista")),
                    _ => String::new(),
                };
                (h.clone(), vista)
            })
            .collect();
        viejas.sort_by(|a, b| a.1.cmp(&b.1)); // estable
        let sobran = maquinas.len() - MAX_HUELLAS;
        for (h, _) in viejas.into_iter().take(sobran) {
            maquinas.quitar(&h);
        }
    }

    // -------------------------------------------------------------- máquina

    /// Guarda la radiografía y dice si la máquina cambió desde la última vez: {cambio, anterior, calibrada}
    pub fn registrar_radiografia(&self, radiografia: Mapa) -> io::Result<Mapa> {
        let mut d = self.cerrojo();
        let nueva = radiografia.get("huella").cloned().unwrap_or(Valor::Nulo);
        let anterior = d.get("huella_actual").cloned().unwrap_or(Valor::Nulo);
        let cambio = anterior.verdad() && nueva.verdad() && anterior != nueva;
        d.poner("huella_actual", nueva.clone());
        d.poner("radiografia", radiografia);
        let h = Self::clave_huella(&nueva);
        let calibrada = Self::con_maquina(&mut d, h.as_deref(), true, |m| {
            m.poner("vista", ahora());
            m.verdad("calibracion")
        });
        if cambio {
            let texto = format!(
                "La máquina cambió ({} → {}): las medidas anteriores no se aplican hasta volver a calibrar.",
                anterior.texto_py(),
                nueva.texto_py()
            );
            let datos = Mapa::new().con("anterior", anterior.clone()).con("nueva", nueva.clone());
            Self::evento_en(&mut d, "maquina_cambiada", &texto, Some(datos.into()));
        }
        Self::podar_huellas(&mut d);
        self.guardar(&d)?;
        Ok(Mapa::new().con("cambio", cambio).con("anterior", anterior).con("calibrada", calibrada))
    }

    // -------------------------------------------------------------- calibración

    /// Solo la de la huella actual (o la pedida): nunca la de otra máquina
    pub fn calibracion(&self, huella: Option<&str>) -> Option<Mapa> {
        let mut d = self.cerrojo();
        let h = huella.filter(|h| !h.is_empty()).map(str::to_string).or_else(|| Self::huella(&d));
        Self::con_maquina(&mut d, h.as_deref(), false, |m| match m.get("calibracion") {
            Some(Valor::Mapa(c)) if !c.is_empty() => Some(c.clone()),
            _ => None,
        })
    }

    /// Lo nuevo manda; lo que esta calibración no midió se conserva
    pub fn guardar_calibracion(&self, huella: &Valor, valores: &Mapa, detalle: Option<&Valor>) -> io::Result<()> {
        let mut d = self.cerrojo();
        Self::con_maquina(&mut d, Self::clave_huella(huella).as_deref(), true, |m| {
            let mut fusion = Mapa::new();
            if let Some(Valor::Mapa(previa)) = m.get("calibracion") {
                for (k, v) in previa.iter() {
                    if k != "fecha" && k != "detalle" {
                        fusion.poner(k.clone(), v.clone());
                    }
                }
            }
            for (k, v) in valores.iter() {
                if !v.es_nulo() {
                    fusion.poner(k.clone(), v.clone());
                }
            }
            fusion.poner("fecha", ahora());
            if let Some(det) = detalle.filter(|v| v.verdad()) {
                fusion.poner("detalle", det.clone());
            }
            m.poner("calibracion", fusion);
        });
        let datos = Mapa::new().con("huella", huella.clone()).con("valores", valores.clone());
        Self::evento_en(&mut d, "calibrada", "Calibración guardada.", Some(datos.into()));
        self.guardar(&d)
    }

    pub fn olvidar_calibracion(&self, huella: Option<&str>) -> io::Result<()> {
        let mut d = self.cerrojo();
        let h = huella.filter(|h| !h.is_empty()).map(str::to_string).or_else(|| Self::huella(&d));
        let habia = Self::con_maquina(&mut d, h.as_deref(), false, |m| {
            if m.is_empty() {
                return false;
            }
            m.poner("calibracion", Valor::Nulo);
            m.poner("pruebas", Mapa::new());
            true
        });
        if habia {
            Self::evento_en(&mut d, "calibracion_borrada", "Calibración y pruebas borradas.", None);
            self.guardar(&d)?;
        }
        Ok(())
    }

    // -------------------------------------------------------------- pruebas

    pub fn clave_prueba(modelo: &str, perfil: &str) -> String {
        format!("{modelo}|{perfil}")
    }

    pub fn guardar_prueba(&self, huella: &Valor, modelo: &str, perfil: &str, resultado: &Mapa) -> io::Result<()> {
        let mut d = self.cerrojo();
        Self::con_maquina(&mut d, Self::clave_huella(huella).as_deref(), true, |m| {
            let pruebas = mapa_de(m, "pruebas");
            pruebas.poner(Self::clave_prueba(modelo, perfil), resultado.clone().con("fecha", ahora()));
            if pruebas.len() > MAX_PRUEBAS_POR_HUELLA {
                let mut claves: Vec<(String, String)> = pruebas
                    .iter()
                    .map(|(k, v)| {
                        let fecha = match v {
                            Valor::Mapa(p) => texto_o_vacio(p.get("fecha")),
                            _ => String::new(),
                        };
                        (k.clone(), fecha)
                    })
                    .collect();
                claves.sort_by(|a, b| a.1.cmp(&b.1));
                let sobran = pruebas.len() - MAX_PRUEBAS_POR_HUELLA;
                for (k, _) in claves.into_iter().take(sobran) {
                    pruebas.quitar(&k);
                }
            }
        });
        if resultado.verdad("ok") {
            let buena = Mapa::new()
                .con("modelo", modelo)
                .con("opciones", resultado.get("opciones").cloned().unwrap_or_else(|| Mapa::new().into()))
                .con("fecha", ahora())
                .con("huella", huella.clone());
            mapa_de(&mut d, "ultima_buena").poner(perfil, buena);
        }
        self.guardar(&d)
    }

    pub fn pruebas(&self, huella: Option<&str>) -> Mapa {
        let mut d = self.cerrojo();
        let h = huella.filter(|h| !h.is_empty()).map(str::to_string).or_else(|| Self::huella(&d));
        Self::con_maquina(&mut d, h.as_deref(), false, |m| match m.get("pruebas") {
            Some(Valor::Mapa(p)) => p.clone(),
            _ => Mapa::new(),
        })
    }

    pub fn prueba(&self, modelo: &str, perfil: &str, huella: Option<&str>) -> Option<Valor> {
        self.pruebas(huella).get(&Self::clave_prueba(modelo, perfil)).cloned()
    }

    /// Solo si se midió en ESTA máquina
    pub fn ultima_buena(&self, perfil: &str) -> Option<Valor> {
        let d = self.cerrojo();
        let u = d.mapa("ultima_buena").and_then(|u| u.get(perfil)).filter(|u| u.verdad())?;
        let huella = match u {
            Valor::Mapa(m) => m.get("huella").cloned().unwrap_or(Valor::Nulo),
            _ => Valor::Nulo,
        };
        (huella == d.get("huella_actual").cloned().unwrap_or(Valor::Nulo)).then(|| u.clone())
    }

    // -------------------------------------------------------------- aplicar

    /// Guarda lo aplicado Y lo que había antes, para poder restaurar. Si se aplica dos veces seguidas, «anterior»
    /// sigue siendo lo que había antes de la PRIMERA vez.
    pub fn registrar_aplicado(&self, perfil: &str, modelo: &Valor, opciones: &Valor, anterior: &Valor) -> io::Result<()> {
        let mut d = self.cerrojo();
        let huella = d.get("huella_actual").cloned().unwrap_or(Valor::Nulo);
        let aplicado = mapa_de(&mut d, "aplicado");
        let original = match aplicado.get(perfil) {
            Some(Valor::Mapa(previo)) if !previo.is_empty() => previo.valor("anterior").clone(),
            _ => anterior.clone(),
        };
        aplicado.poner(
            perfil,
            Mapa::new()
                .con("modelo", modelo.clone())
                .con("opciones", opciones.clone())
                .con("fecha", ahora())
                .con("anterior", original)
                .con("huella", huella),
        );
        let texto = format!("Recomendación aplicada a {perfil}: {}.", modelo.texto_py());
        let datos = Mapa::new().con("perfil", perfil).con("opciones", opciones.clone());
        Self::evento_en(&mut d, "aplicado", &texto, Some(datos.into()));
        self.guardar(&d)
    }

    pub fn aplicado(&self, perfil: &str) -> Option<Valor> {
        let d = self.cerrojo();
        d.mapa("aplicado").and_then(|a| a.get(perfil)).filter(|a| a.verdad()).cloned()
    }

    /// Devuelve lo que había antes de aplicar y olvida la aplicación
    pub fn quitar_aplicado(&self, perfil: &str) -> io::Result<Option<Valor>> {
        let mut d = self.cerrojo();
        let a = mapa_de(&mut d, "aplicado").quitar(perfil).filter(Valor::verdad);
        let Some(a) = a else { return Ok(None) };
        let datos = Mapa::new().con("perfil", perfil);
        Self::evento_en(&mut d, "restaurado", &format!("Restaurados los ajustes previos de {perfil}."), Some(datos.into()));
        self.guardar(&d)?;
        Ok(Some(match a {
            Valor::Mapa(m) => m.valor("anterior").clone(),
            _ => Valor::Nulo,
        }))
    }

    // -------------------------------------------------------------- servidor, térmico, frío, ritmo

    /// Una sección de ajustes (`dict(datos.get(clave) or {})`)
    pub fn seccion(&self, clave: &str) -> Mapa {
        let d = self.cerrojo();
        match d.get(clave) {
            Some(Valor::Mapa(m)) => m.clone(),
            _ => Mapa::new(),
        }
    }

    /// Reemplaza una sección y, si hay texto, lo apunta como evento de ese tipo
    pub fn guardar_seccion(&self, clave: &str, ajustes: Mapa, evento: Option<(&str, &str, Option<Valor>)>) -> io::Result<()> {
        let mut d = self.cerrojo();
        d.poner(clave, ajustes);
        if let Some((tipo, texto, datos)) = evento.filter(|(_, t, _)| !t.is_empty()) {
            Self::evento_en(&mut d, tipo, texto, datos);
        }
        self.guardar(&d)
    }

    /// Solo OLLAMA_* y LLAMA_ARG_*, como texto, sin vacíos
    pub fn guardar_entorno_servidor(&self, entorno: &Mapa) -> io::Result<()> {
        let mut limpio = Mapa::new();
        for (k, v) in entorno.iter() {
            if (k.starts_with("OLLAMA_") || k.starts_with("LLAMA_ARG_")) && !v.es_nulo() && !v.texto_py().is_empty() {
                limpio.poner(k.clone(), v.texto_py());
            }
        }
        let datos: Valor = limpio.clone().into();
        self.guardar_seccion(
            "entorno_servidor",
            limpio,
            Some(("entorno_servidor", "Variables del servidor actualizadas.", Some(datos))),
        )
    }

    // -------------------------------------------------------------- eventos

    /// `_evento`: apunta sin guardar
    pub fn apuntar_evento(&self, tipo: &str, texto: &str, datos: Option<Valor>) {
        let mut d = self.cerrojo();
        Self::evento_en(&mut d, tipo, texto, datos);
    }

    pub fn evento(&self, tipo: &str, texto: &str, datos: Option<Valor>) -> io::Result<()> {
        let mut d = self.cerrojo();
        Self::evento_en(&mut d, tipo, texto, datos);
        self.guardar(&d)
    }

    /// Los últimos `limite`, del más nuevo al más viejo
    pub fn eventos(&self, limite: i64) -> Vec<Valor> {
        let d = self.cerrojo();
        let l = d.lista("eventos").unwrap_or(&[]);
        ultimos(l, limite).iter().rev().cloned().collect()
    }

    pub fn huella_actual(&self) -> Valor {
        self.cerrojo().get("huella_actual").cloned().unwrap_or(Valor::Nulo)
    }

    pub fn radiografia(&self) -> Valor {
        self.cerrojo().get("radiografia").cloned().unwrap_or(Valor::Nulo)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    struct Tmp(PathBuf);
    impl Tmp {
        fn nueva(n: &str) -> Tmp {
            let p = std::env::temp_dir().join(format!("prig-almacen-{n}-{}", std::process::id()));
            let _ = std::fs::remove_dir_all(&p);
            std::fs::create_dir_all(&p).unwrap();
            Tmp(p)
        }
    }
    impl Drop for Tmp {
        fn drop(&mut self) {
            let _ = std::fs::remove_dir_all(&self.0);
        }
    }

    #[test]
    fn dos_procesos_no_se_pisan() {
        let t = Tmp::nueva("dos");
        let ruta = t.0.join("r.json");
        let (a, b) = (Almacen::abrir(&ruta), Almacen::abrir(&ruta));
        a.guardar_seccion("ritmo", Mapa::new().con("activo", true), None).unwrap();
        assert!(b.seccion("ritmo").verdad("activo"));
        b.guardar_seccion("frio", Mapa::new().con("activo", true), None).unwrap();
        a.evento("x", "uno", None).unwrap();
        let c = Almacen::abrir(&ruta);
        assert!(c.seccion("ritmo").verdad("activo") && c.seccion("frio").verdad("activo"));
        assert_eq!(c.eventos(10).len(), 1);
    }

    #[test]
    fn calibracion_por_huella() {
        let t = Tmp::nueva("huella");
        let ruta = t.0.join("r.json");
        let a = Almacen::abrir(&ruta);
        a.registrar_radiografia(Mapa::new().con("huella", "A")).unwrap();
        a.guardar_calibracion(&"A".into(), &Mapa::new().con("ancho_gpu", 178), None).unwrap();
        assert_eq!(a.calibracion(None).unwrap().valor("ancho_gpu"), &Valor::Entero(178));
        let r = a.registrar_radiografia(Mapa::new().con("huella", "B")).unwrap();
        assert!(r.verdad("cambio"));
        assert!(a.calibracion(None).is_none());
        a.registrar_radiografia(Mapa::new().con("huella", "A")).unwrap();
        assert_eq!(Almacen::abrir(&ruta).calibracion(None).unwrap().valor("ancho_gpu"), &Valor::Entero(178));
        use std::os::unix::fs::PermissionsExt;
        assert_eq!(std::fs::metadata(&ruta).unwrap().permissions().mode() & 0o777, 0o600);
    }

    #[test]
    fn archivo_roto_se_aparta() {
        let t = Tmp::nueva("roto");
        let ruta = t.0.join("r.json");
        std::fs::write(&ruta, "{roto").unwrap();
        let a = Almacen::abrir(&ruta);
        assert!(a.calibracion(None).is_none());
        assert!(std::fs::read_dir(&t.0).unwrap().flatten().any(|e| e.file_name().to_string_lossy().starts_with("r.json.roto-")));
        a.evento("x", "y", None).unwrap();
        assert!(std::fs::read_to_string(&ruta).unwrap().contains("\"tipo\": \"x\""));
    }

    #[test]
    fn eventos_acotados_y_cortes_como_python() {
        let t = Tmp::nueva("eventos");
        let a = Almacen::abrir(&t.0.join("r.json"));
        for i in 0..260 {
            a.apuntar_evento("e", &i.to_string(), None);
        }
        assert_eq!(a.eventos(1000).len(), 200);
        assert_eq!(a.eventos(0).len(), 200); // lista[-0:] es la lista entera
        assert_eq!(a.eventos(3).len(), 3);
    }
}
