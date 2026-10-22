//! Monitor, tramo, gobernador (prig_recursos::termico) y controlador del modo frío (prig_recursos::frio) para
//! `backend/recursos/termico.py` y `frio.py`.
//!
//! El mundo de cada núcleo es su fachada de Python: el gobernador mira `fachada.monitor`, `fachada.ritmo`,
//! `fachada.fijador`, `fachada.dosifica_el_motor()`… en el momento de cada llamada, así que reemplazar esas piezas
//! (como hacen las pruebas) sigue funcionando.

use crate::ritmo::{reloj, RitmoPy};
use crate::valor::{a_python, de_python, mapa_a_python, mapa_de_python};
use prig_recursos::frio::{self, ControladorFrio, MundoFrio};
use prig_recursos::sensores;
use prig_recursos::termico::{self, Gobernador, Guardar, MundoGobernador, NucleoMonitor, Tramo};
use prig_recursos::valor::{Mapa, Valor};
use pyo3::exceptions::{PyKeyError, PyValueError};
use pyo3::prelude::*;
use pyo3::types::{PyDict, PyList, PySet, PyTuple};
use std::path::Path;
use std::sync::{Mutex, MutexGuard};

fn bloquear<T: Send>(m: &Mutex<T>) -> MutexGuard<'_, T> {
    crate::gil::bloquear(m)
}

// =========================================================================== monitor

/// El estado del `Monitor` de Python (su hilo y su lector siguen en Python)
#[pyclass(name = "NucleoMonitor", frozen)]
pub struct MonitorPy {
    inner: Mutex<NucleoMonitor>,
}

#[pymethods]
impl MonitorPy {
    #[new]
    fn new() -> Self {
        MonitorPy { inner: Mutex::new(NucleoMonitor::default()) }
    }

    /// Guarda una lectura (la del lector de Python)
    fn registrar(&self, lectura: &Bound<'_, PyAny>) -> PyResult<()> {
        let v = de_python(lectura)?;
        bloquear(&self.inner).registrar(v);
        Ok(())
    }

    /// Lee todos los sensores en Rust (sin el GIL), la guarda y la devuelve
    fn muestrear_nativo<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        let l = py.detach(sensores::leer_sensores);
        let d = crate::sensores::lectura_a_python(py, &l)?;
        let v = de_python(d.as_any())?;
        bloquear(&self.inner).registrar(v);
        Ok(d.into_any())
    }

    #[getter]
    fn ultima<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        let u = bloquear(&self.inner).ultima.clone();
        a_python(py, &u.unwrap_or(Valor::Nulo))
    }

    fn consultar(&self, ahora: f64) {
        bloquear(&self.inner).consulta = ahora;
    }

    fn vivo(&self, ahora: f64) -> bool {
        bloquear(&self.inner).vivo(ahora)
    }

    fn sumar_trabajo(&self, delta: i64) {
        bloquear(&self.inner).trabajos += delta;
    }

    #[getter]
    fn historial<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyList>> {
        let h: Vec<Mapa> = bloquear(&self.inner).historial.iter().cloned().collect();
        let l = PyList::empty(py);
        for x in &h {
            l.append(mapa_a_python(py, x)?)?;
        }
        Ok(l)
    }

    #[pyo3(signature = (desde = None))]
    fn tendencia_gpu(&self, desde: Option<f64>) -> f64 {
        bloquear(&self.inner).tendencia_gpu(desde)
    }
}

#[pyfunction]
fn temp_gpu<'py>(py: Python<'py>, lectura: &Bound<'py, PyAny>) -> PyResult<Bound<'py, PyAny>> {
    a_python(py, &termico::temp_gpu(&de_python(lectura)?))
}

#[pyfunction]
fn temp_cpu<'py>(py: Python<'py>, lectura: &Bound<'py, PyAny>) -> PyResult<Bound<'py, PyAny>> {
    a_python(py, &termico::temp_cpu(&de_python(lectura)?))
}

/// La temperatura de la CPU leyendo solo sus sensores (la misma que `temp_cpu(leer_sensores())`)
#[pyfunction]
fn temp_cpu_rapida(py: Python<'_>) -> Option<f64> {
    py.detach(|| sensores::temp_cpu_rapida(Path::new("/")))
}

#[pyfunction]
fn texto_pausa(motivo: &str, temp: f64, objetivo: f64, limite: f64) -> String {
    termico::texto_pausa(motivo, temp, objetivo, limite)
}

// =========================================================================== tramo

/// Un tramo de generación entre dos pausas. Python la hereda para leer el reloj (`time.time()`).
#[pyclass(name = "Tramo", subclass)]
pub struct TramoPy {
    pub inner: Tramo,
}

#[pymethods]
impl TramoPy {
    #[new]
    fn new(temp_inicio: &Bound<'_, PyAny>, ahora: f64) -> PyResult<Self> {
        Ok(TramoPy { inner: Tramo::new(de_python(temp_inicio)?, ahora) })
    }

    #[getter]
    fn inicio(&self) -> f64 {
        self.inner.inicio
    }
    #[setter]
    fn set_inicio(&mut self, v: f64) {
        self.inner.inicio = v;
    }
    #[getter]
    fn temp_inicio<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        a_python(py, &self.inner.temp_inicio)
    }
    #[setter]
    fn set_temp_inicio(&mut self, v: &Bound<'_, PyAny>) -> PyResult<()> {
        self.inner.temp_inicio = de_python(v)?;
        Ok(())
    }
    #[getter]
    fn pico<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        a_python(py, &self.inner.pico)
    }
    #[setter]
    fn set_pico(&mut self, v: &Bound<'_, PyAny>) -> PyResult<()> {
        self.inner.pico = de_python(v)?;
        Ok(())
    }
    #[getter]
    fn max_arranque<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        a_python(py, &self.inner.max_arranque)
    }
    #[setter]
    fn set_max_arranque(&mut self, v: &Bound<'_, PyAny>) -> PyResult<()> {
        self.inner.max_arranque = de_python(v)?;
        Ok(())
    }
    #[getter]
    fn temp_corte<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        a_python(py, &self.inner.temp_corte)
    }
    #[setter]
    fn set_temp_corte(&mut self, v: &Bound<'_, PyAny>) -> PyResult<()> {
        self.inner.temp_corte = de_python(v)?;
        Ok(())
    }
    #[getter]
    fn pico_en_pausa<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        a_python(py, &self.inner.pico_en_pausa)
    }
    #[setter]
    fn set_pico_en_pausa(&mut self, v: &Bound<'_, PyAny>) -> PyResult<()> {
        self.inner.pico_en_pausa = de_python(v)?;
        Ok(())
    }
    #[getter]
    fn pausa_ritmo<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        a_python(py, &self.inner.pausa_ritmo)
    }
    #[setter]
    fn set_pausa_ritmo(&mut self, v: &Bound<'_, PyAny>) -> PyResult<()> {
        self.inner.pausa_ritmo = de_python(v)?;
        Ok(())
    }

    /// `reloj`: la función que da la hora (solo se llama si hay temperatura)
    fn anotar(&mut self, temp: &Bound<'_, PyAny>, reloj: &Bound<'_, PyAny>) -> PyResult<()> {
        let t = de_python(temp)?;
        self.inner.anotar(&t, || reloj.call0()?.extract::<f64>())
    }

    #[getter]
    fn pico_real<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        a_python(py, &self.inner.pico_real())
    }
}

/// Copia el tramo de un objeto de Python (para no tenerlo prestado mientras se llama a Python)
fn tramo_de(obj: &Bound<'_, PyAny>) -> PyResult<Tramo> {
    Ok(obj.cast::<TramoPy>()?.borrow().inner.clone())
}

fn tramo_a(obj: &Bound<'_, PyAny>, t: Tramo) -> PyResult<()> {
    obj.cast::<TramoPy>()?.borrow_mut().inner = t;
    Ok(())
}

// =========================================================================== gobernador

/// El mundo del gobernador para una llamada: su fachada y, si los hay, el evento para cancelar y la función de avisos
struct MundoPython<'a, 'py> {
    py: Python<'py>,
    fachada: &'a Bound<'py, PyAny>,
    cancelar: Option<Bound<'py, PyAny>>,
    avisar: Option<Bound<'py, PyAny>>,
    contexto: Option<Bound<'py, PyAny>>,
}

impl<'py> MundoPython<'_, 'py> {
    fn ritmo(&self) -> PyResult<Bound<'py, RitmoPy>> {
        Ok(self.fachada.getattr("ritmo")?.cast_into::<RitmoPy>()?)
    }
}

impl MundoGobernador for MundoPython<'_, '_> {
    type Error = PyErr;

    fn ahora(&mut self) -> PyResult<f64> {
        reloj(self.py)
    }

    fn gpu(&mut self, max_edad: Option<f64>) -> PyResult<Valor> {
        let monitor = self.fachada.getattr("monitor")?;
        let v = match max_edad {
            Some(e) => {
                let kw = PyDict::new(self.py);
                kw.set_item("max_edad", e)?;
                monitor.call_method("gpu", (), Some(&kw))?
            }
            None => monitor.call_method0("gpu")?,
        };
        de_python(&v)
    }

    fn tendencia_gpu(&mut self, desde: f64) -> PyResult<f64> {
        let kw = PyDict::new(self.py);
        kw.set_item("desde", desde)?;
        self.fachada.getattr("monitor")?.call_method("tendencia_gpu", (), Some(&kw))?.extract()
    }

    fn trabajando_entrar(&mut self) -> PyResult<()> {
        let ctx = self.fachada.getattr("monitor")?.call_method0("trabajando")?;
        ctx.call_method0("__enter__")?;
        self.contexto = Some(ctx);
        Ok(())
    }

    fn trabajando_salir(&mut self) -> PyResult<()> {
        if let Some(ctx) = self.contexto.take() {
            ctx.call_method1("__exit__", (self.py.None(), self.py.None(), self.py.None()))?;
        }
        Ok(())
    }

    fn dosifica_el_motor(&mut self) -> PyResult<bool> {
        self.fachada.call_method0("dosifica_el_motor")?.is_truthy()
    }

    fn moe_generando(&mut self) -> PyResult<bool> {
        self.fachada.call_method0("_moe")?.is_truthy()
    }

    fn ritmo_marcar(&mut self) -> PyResult<()> {
        let a = reloj(self.py)?;
        self.ritmo()?.get().bloquear().marcar(a);
        Ok(())
    }

    fn ritmo_activo(&mut self) -> PyResult<bool> {
        Ok(self.ritmo()?.get().bloquear().activo())
    }

    fn ritmo_cpu_eficiente(&mut self) -> PyResult<bool> {
        Ok(self.ritmo()?.get().bloquear().ajustes.verdad("cpu_eficiente"))
    }

    fn ritmo_pausa(&mut self, segundos: f64, temp: &Valor) -> PyResult<Option<f64>> {
        let py = self.py;
        let ritmo = self.ritmo()?;
        let mut error = None;
        let p = ritmo.get().bloquear().pausa(
            segundos,
            temp,
            || reloj(py).unwrap_or_else(|e| {
                error = Some(e);
                f64::NAN
            }),
            || reloj(py).unwrap_or(f64::NAN),
        );
        match error {
            Some(e) => Err(e),
            None => Ok(p),
        }
    }

    fn aplicar_fijador(&mut self) {
        let _ = self.fachada.getattr("fijador").and_then(|f| f.call_method0("aplicar"));
    }

    fn esperar(&mut self, s: f64) -> PyResult<bool> {
        match &self.cancelar {
            Some(c) => c.call_method1("wait", (s,))?.is_truthy(),
            None => {
                self.py.import("time")?.getattr("sleep")?.call1((s,))?;
                Ok(false)
            }
        }
    }

    fn hay_avisos(&mut self) -> bool {
        self.avisar.as_ref().is_some_and(|a| a.is_truthy().unwrap_or(false))
    }

    fn avisar(&mut self, evento: Mapa) -> PyResult<()> {
        if let Some(a) = &self.avisar {
            a.call1((mapa_a_python(self.py, &evento)?,))?;
        }
        Ok(())
    }

    fn persistir(&mut self, g: Guardar) -> PyResult<()> {
        let d = match g.datos {
            Some(d) => mapa_a_python(self.py, &d)?.into_any(),
            None => self.py.None().into_bound(self.py),
        };
        self.fachada.call_method1("_persistir_ajustes", (mapa_a_python(self.py, &g.ajustes)?, g.texto, d))?;
        Ok(())
    }
}

/// El estado del `Gobernador` de Python: ajustes aprendidos, pausa en curso y aviso
#[pyclass(name = "NucleoGobernador", frozen)]
pub struct GobernadorPy {
    inner: Mutex<Gobernador>,
}

fn opcional<'py>(v: &Option<Bound<'py, PyAny>>) -> Option<Bound<'py, PyAny>> {
    v.as_ref().filter(|x| !x.is_none()).cloned()
}

#[pymethods]
impl GobernadorPy {
    #[new]
    #[pyo3(signature = (guardados, guardar))]
    fn new(guardados: Option<&Bound<'_, PyAny>>, guardar: bool) -> PyResult<Self> {
        let g = match guardados {
            Some(g) if !g.is_none() => Some(mapa_de_python(g)?),
            _ => None,
        };
        Ok(GobernadorPy { inner: Mutex::new(Gobernador::new(g.as_ref(), guardar)) })
    }

    // -- ajustes (los usa AjustesVivos)
    fn _leer(&self, clave: &str) -> PyResult<Option<Py<PyAny>>> {
        let v = bloquear(&self.inner).ajustes.get(clave).cloned();
        Python::attach(|py| v.map(|v| a_python(py, &v).map(Bound::unbind)).transpose())
    }

    fn _poner(&self, clave: String, valor: &Bound<'_, PyAny>) -> PyResult<()> {
        let v = de_python(valor)?;
        bloquear(&self.inner).ajustes.poner(clave, v);
        Ok(())
    }

    fn _quitar(&self, clave: &str) -> bool {
        bloquear(&self.inner).ajustes.quitar(clave).is_some()
    }

    fn _ajustes<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
        let a = bloquear(&self.inner).ajustes.clone();
        mapa_a_python(py, &a)
    }

    #[getter]
    fn limite(&self) -> f64 {
        bloquear(&self.inner).limite()
    }
    #[getter]
    fn salto(&self) -> f64 {
        bloquear(&self.inner).salto()
    }
    #[getter]
    fn corte(&self) -> f64 {
        bloquear(&self.inner).corte()
    }
    #[getter]
    fn reanudar(&self) -> f64 {
        bloquear(&self.inner).reanudar()
    }
    #[getter]
    fn viable(&self) -> bool {
        bloquear(&self.inner).viable()
    }
    #[getter]
    fn limite_minimo_viable(&self) -> Option<f64> {
        bloquear(&self.inner).limite_minimo_viable()
    }
    #[getter]
    fn aviso(&self) -> Option<String> {
        bloquear(&self.inner).aviso.clone()
    }
    #[getter]
    fn pausa<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        let p = bloquear(&self.inner).pausa.clone();
        a_python(py, &p.map(Valor::Mapa).unwrap_or(Valor::Nulo))
    }

    fn fijar_limite(&self, py: Python<'_>, fachada: &Bound<'_, PyAny>, limite: f64) -> PyResult<()> {
        let g = bloquear(&self.inner).fijar_limite(limite).map_err(PyValueError::new_err)?;
        self.guardar(py, fachada, g)
    }

    fn olvidar(&self, py: Python<'_>, fachada: &Bound<'_, PyAny>) -> PyResult<()> {
        let g = bloquear(&self.inner).olvidar();
        self.guardar(py, fachada, g)
    }

    fn estado<'py>(&self, py: Python<'py>, ritmo: &Bound<'py, PyAny>) -> PyResult<Bound<'py, PyDict>> {
        let r = mapa_de_python(ritmo)?;
        let e = bloquear(&self.inner).estado(r);
        mapa_a_python(py, &e)
    }

    /// Marca el ritmo, fija los núcleos si toca y devuelve el tramo nuevo (de la clase `clase`, que lee el reloj)
    fn empezar_tramo<'py>(&self, py: Python<'py>, fachada: &Bound<'py, PyAny>, clase: &Bound<'py, PyAny>) -> PyResult<Bound<'py, PyAny>> {
        let mut mundo = MundoPython { py, fachada, cancelar: None, avisar: None, contexto: None };
        let temp = Gobernador::preparar_tramo(&mut mundo)?;
        clase.call1((a_python(py, &temp)?,))
    }

    /// Solo lee el gobernador: se usa una copia y no se bloquea mientras se llama a Python
    fn debe_cortar(&self, py: Python<'_>, fachada: &Bound<'_, PyAny>, tramo: &Bound<'_, PyAny>) -> PyResult<Option<&'static str>> {
        let mut t = tramo_de(tramo)?;
        let mut mundo = MundoPython { py, fachada, cancelar: None, avisar: None, contexto: None };
        let g = bloquear(&self.inner).clone();
        let r = g.debe_cortar(&mut t, &mut mundo);
        tramo_a(tramo, t)?;
        r
    }

    #[pyo3(signature = (fachada, tramo, cancelar = None))]
    fn descansar(&self, py: Python<'_>, fachada: &Bound<'_, PyAny>, tramo: &Bound<'_, PyAny>, cancelar: Option<Bound<'_, PyAny>>) -> PyResult<f64> {
        let t = tramo_de(tramo)?;
        let mut mundo = MundoPython { py, fachada, cancelar: opcional(&cancelar), avisar: None, contexto: None };
        Gobernador::descansar(&t, &mut mundo)
    }

    #[pyo3(signature = (fachada, motivo, cancelar, avisar, objetivo, maximo_s, tramo))]
    #[allow(clippy::too_many_arguments)]
    fn enfriar(
        &self,
        py: Python<'_>,
        fachada: &Bound<'_, PyAny>,
        motivo: &str,
        cancelar: Option<Bound<'_, PyAny>>,
        avisar: Option<Bound<'_, PyAny>>,
        objetivo: Option<f64>,
        maximo_s: f64,
        tramo: Option<Bound<'_, PyAny>>,
    ) -> PyResult<f64> {
        let tramo = opcional(&tramo);
        let mut t = tramo.as_ref().map(tramo_de).transpose()?;
        let mut mundo = MundoPython { py, fachada, cancelar: opcional(&cancelar), avisar: opcional(&avisar), contexto: None };
        let r = Gobernador::enfriar(&self.inner, motivo, objetivo, maximo_s, t.as_mut(), &mut mundo);
        if let (Some(obj), Some(t)) = (tramo.as_ref(), t) {
            tramo_a(obj, t)?;
        }
        r
    }

    fn _anotar_reposo(&self, py: Python<'_>, fachada: &Bound<'_, PyAny>, minima: &Bound<'_, PyAny>) -> PyResult<()> {
        let m = de_python(minima)?;
        let g = bloquear(&self.inner).anotar_reposo(&m);
        self.guardar(py, fachada, g)
    }

    fn _revisar_viabilidad(&self) {
        bloquear(&self.inner).revisar_viabilidad();
    }

    #[pyo3(signature = (fachada, tramo, motivo = None))]
    fn terminar_tramo(&self, py: Python<'_>, fachada: &Bound<'_, PyAny>, tramo: &Bound<'_, PyAny>, motivo: Option<&str>) -> PyResult<()> {
        let t = tramo_de(tramo)?;
        let segundos = termico::segundos_para_terminar(&t, motivo, || reloj(py))?;
        let g = bloquear(&self.inner).terminar_tramo(&t, motivo, segundos);
        self.guardar(py, fachada, g)
    }
}

impl GobernadorPy {
    /// Guarda en el almacén (por la fachada), ya sin el gobernador bloqueado
    fn guardar(&self, py: Python<'_>, fachada: &Bound<'_, PyAny>, g: Option<Guardar>) -> PyResult<()> {
        match g {
            Some(g) => MundoPython { py, fachada, cancelar: None, avisar: None, contexto: None }.persistir(g),
            None => Ok(()),
        }
    }
}

/// `gobernador.ajustes`: un diccionario vivo sobre los ajustes que guarda Rust (las pruebas y la fachada los
/// cambian con `[]=` y `update`)
#[pyclass(name = "AjustesVivos", frozen, mapping)]
pub struct AjustesVivos {
    nucleo: Py<GobernadorPy>,
}

#[pymethods]
impl AjustesVivos {
    #[new]
    fn new(nucleo: Py<GobernadorPy>) -> Self {
        AjustesVivos { nucleo }
    }

    fn _dict<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
        self.nucleo.get()._ajustes(py)
    }

    fn __getitem__(&self, clave: &str) -> PyResult<Py<PyAny>> {
        self.nucleo.get()._leer(clave)?.ok_or_else(|| PyKeyError::new_err(clave.to_string()))
    }

    fn __setitem__(&self, clave: String, valor: &Bound<'_, PyAny>) -> PyResult<()> {
        self.nucleo.get()._poner(clave, valor)
    }

    fn __delitem__(&self, clave: &str) -> PyResult<()> {
        if self.nucleo.get()._quitar(clave) {
            Ok(())
        } else {
            Err(PyKeyError::new_err(clave.to_string()))
        }
    }

    fn __contains__(&self, clave: &str) -> bool {
        bloquear(&self.nucleo.get().inner).ajustes.contiene(clave)
    }

    fn __len__(&self) -> usize {
        bloquear(&self.nucleo.get().inner).ajustes.len()
    }

    fn __iter__<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        self._dict(py)?.call_method0("keys")?.try_iter().map(Bound::into_any)
    }

    fn keys<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        self._dict(py)?.call_method0("keys")
    }

    fn values<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        self._dict(py)?.call_method0("values")
    }

    fn items<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        self._dict(py)?.call_method0("items")
    }

    #[pyo3(signature = (clave, defecto = None))]
    fn get(&self, py: Python<'_>, clave: &str, defecto: Option<Py<PyAny>>) -> PyResult<Py<PyAny>> {
        Ok(self.nucleo.get()._leer(clave)?.unwrap_or_else(|| defecto.unwrap_or_else(|| py.None())))
    }

    #[pyo3(signature = (*otros, **cambios))]
    fn update(&self, py: Python<'_>, otros: &Bound<'_, PyTuple>, cambios: Option<&Bound<'_, PyDict>>) -> PyResult<()> {
        let d = PyDict::new(py);
        for o in otros.iter() {
            d.call_method1("update", (o,))?;
        }
        if let Some(c) = cambios {
            d.update(c.as_mapping())?;
        }
        for (k, v) in d.iter() {
            self.nucleo.get()._poner(k.extract()?, &v)?;
        }
        Ok(())
    }

    fn copy<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
        self._dict(py)
    }

    fn __eq__(&self, py: Python<'_>, otro: &Bound<'_, PyAny>) -> PyResult<bool> {
        let d = self._dict(py)?;
        match otro.cast::<AjustesVivos>() {
            Ok(a) => d.eq(a.get()._dict(py)?),
            Err(_) => d.eq(otro),
        }
    }

    fn __repr__(&self, py: Python<'_>) -> PyResult<String> {
        Ok(self._dict(py)?.repr()?.to_string())
    }
}

// =========================================================================== controlador del modo frío

/// El mundo del controlador del modo frío: su fachada (ajustes, motores en RAM, reloj, temperatura, holgura, turbo,
/// pausador), con los motores como el set de Python que se recorre y se pasa tal cual
struct MundoFrioPython<'a, 'py> {
    py: Python<'py>,
    fachada: &'a Bound<'py, PyAny>,
    pids: Option<Bound<'py, PySet>>,
}

impl MundoFrio for MundoFrioPython<'_, '_> {
    type Error = PyErr;

    fn ajustes(&mut self) -> PyResult<Mapa> {
        let a = self.fachada.call_method0("ajustes")?;
        if a.is_truthy()? {
            mapa_de_python(&a)
        } else {
            Ok(Mapa::new())
        }
    }

    fn motores_en_ram(&mut self) -> PyResult<Vec<i32>> {
        let m = self.fachada.call_method0("motores_en_ram")?;
        let conjunto = if m.is_truthy()? { PySet::new(self.py, m.try_iter()?.collect::<PyResult<Vec<_>>>()?)? } else { PySet::empty(self.py)? };
        let pids = conjunto.iter().map(|p| p.extract::<i32>()).collect::<PyResult<Vec<_>>>()?;
        self.pids = Some(conjunto);
        Ok(pids)
    }

    fn tiempo_cpu(&mut self, pid: i32) -> PyResult<Option<f64>> {
        self.fachada.call_method1("_tiempo_cpu", (pid,))?.extract()
    }

    fn reloj(&mut self) -> PyResult<f64> {
        self.fachada.call_method0("reloj")?.extract()
    }

    fn leer_temp(&mut self) -> PyResult<Valor> {
        de_python(&self.fachada.call_method0("leer_temp")?)
    }

    fn holgura(&mut self, _pids: &[i32]) -> PyResult<f64> {
        let pids = self.pids.clone().map(Bound::into_any).unwrap_or_else(|| self.py.None().into_bound(self.py));
        let h = self.fachada.call_method1("holgura", (pids,))?;
        if h.is_truthy()? {
            h.extract()
        } else {
            Ok(0.0)
        }
    }

    fn sin_turbo(&mut self) -> PyResult<bool> {
        self.fachada.call_method0("sin_turbo")?.is_truthy()
    }

    fn fijar(&mut self, pids: &[i32], fraccion: f64) -> PyResult<()> {
        let conjunto = if pids.is_empty() { PySet::empty(self.py)? } else { self.pids.clone().map_or_else(|| PySet::empty(self.py), Ok)? };
        self.fachada.getattr("pausador")?.call_method1("fijar", (conjunto, fraccion))?;
        Ok(())
    }
}

/// El estado del `ControladorFrio` de Python
#[pyclass(name = "NucleoFrio", frozen)]
pub struct FrioPy {
    inner: Mutex<ControladorFrio>,
}

#[pymethods]
impl FrioPy {
    #[new]
    fn new() -> Self {
        FrioPy { inner: Mutex::new(ControladorFrio::default()) }
    }

    fn paso<'py>(&self, py: Python<'py>, fachada: &Bound<'py, PyAny>) -> PyResult<Bound<'py, PyDict>> {
        let mut mundo = MundoFrioPython { py, fachada, pids: None };
        let mut c = std::mem::take(&mut *bloquear(&self.inner));
        let r = c.paso(&mut mundo);
        *bloquear(&self.inner) = c;
        mapa_a_python(py, &r?)
    }

    #[getter]
    fn fraccion(&self) -> Option<f64> {
        bloquear(&self.inner).fraccion
    }

    #[getter]
    fn temp_media<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        let t = bloquear(&self.inner).temp_media.clone();
        a_python(py, &t.unwrap_or(Valor::Nulo))
    }

    #[getter]
    fn generaba(&self) -> bool {
        bloquear(&self.inner).generaba
    }

    #[getter]
    fn ultimo<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
        let u = bloquear(&self.inner).ultimo.clone();
        mapa_a_python(py, &u)
    }
}

pub fn registrar(m: &Bound<'_, PyModule>) -> PyResult<()> {
    let py = m.py();
    for (nombre, v) in [
        ("LIMITE_GPU", termico::LIMITE_GPU),
        ("CPU_AVISO", termico::CPU_AVISO),
        ("CPU_ALTO", termico::CPU_ALTO),
        ("INTERVALO_S", termico::INTERVALO_S),
        ("INACTIVO_S", termico::INACTIVO_S),
        ("SALTO_INICIAL", termico::SALTO_INICIAL),
        ("SEGUNDOS_SALTO", termico::SEGUNDOS_SALTO),
        ("MARGEN_MAXIMO", termico::MARGEN_MAXIMO),
        ("ESPERA_MAXIMA_S", termico::ESPERA_MAXIMA_S),
        ("MESETA_S", termico::MESETA_S),
        ("INICIO", frio::INICIO),
        ("ACTIVIDAD", frio::ACTIVIDAD),
        ("HOLGURA_MOE_SIN_TURBO_C", frio::HOLGURA_MOE_SIN_TURBO_C),
        ("FRIO_PERIODO_S", frio::controlador::PERIODO_S),
        ("FRIO_SUBIDA", frio::controlador::SUBIDA),
        ("FRIO_BAJADA", frio::controlador::BAJADA),
        ("FRIO_SUAVIZADO", frio::controlador::SUAVIZADO),
    ] {
        m.add(nombre, v)?;
    }
    m.add("HISTORIAL", termico::HISTORIAL)?;
    m.add("FRESCAS_PARA_AFLOJAR", termico::FRESCAS_PARA_AFLOJAR)?;
    m.add("AJUSTES_POR_DEFECTO", mapa_a_python(py, &termico::ajustes_por_defecto())?)?;
    m.add("FRIO_POR_DEFECTO", mapa_a_python(py, &frio::por_defecto())?)?;
    m.add_class::<MonitorPy>()?;
    m.add_class::<TramoPy>()?;
    m.add_class::<GobernadorPy>()?;
    m.add_class::<AjustesVivos>()?;
    m.add_class::<FrioPy>()?;
    m.add_function(wrap_pyfunction!(temp_gpu, m)?)?;
    m.add_function(wrap_pyfunction!(temp_cpu, m)?)?;
    m.add_function(wrap_pyfunction!(temp_cpu_rapida, m)?)?;
    m.add_function(wrap_pyfunction!(texto_pausa, m)?)?;
    Ok(())
}
