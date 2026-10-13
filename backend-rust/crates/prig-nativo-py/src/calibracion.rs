//! Calibración (prig_recursos::calibracion) para `backend/recursos/calibracion.py`

use crate::calculadora::MaquinaPy;
use crate::valor::{mapa_a_python, mapa_de_python};
use prig_recursos::calibracion::{self as cal, FinGenerar, MundoPrueba};
use prig_recursos::valor::Mapa;
use pyo3::exceptions::{PyKeyError, PyRuntimeError};
use pyo3::prelude::*;
use pyo3::types::{PyDict, PyList, PyTuple};

#[pyfunction]
#[pyo3(signature = (respuesta))]
fn puntuar_canario<'py>(py: Python<'py>, respuesta: Option<&Bound<'py, PyAny>>) -> PyResult<Bound<'py, PyDict>> {
    // json.loads(None) fallaba: sin texto, como si no fuera JSON
    let texto = match respuesta {
        Some(r) if r.is_instance_of::<pyo3::types::PyString>() => Some(r.extract::<String>()?),
        Some(r) if r.is_none() => None,
        Some(r) => Some(r.str()?.to_string()),
        None => None,
    };
    mapa_a_python(py, &cal::puntuar_canario(texto.as_deref()))
}

#[pyfunction]
#[pyo3(signature = (mensaje))]
fn es_oom(mensaje: Option<&str>) -> bool {
    cal::es_oom(mensaje.unwrap_or(""))
}

/// El siguiente escalón tras una falta de memoria, o None
#[pyfunction]
fn reducir<'py>(py: Python<'py>, ficha: &Bound<'py, PyAny>, opc: &Bound<'py, PyAny>) -> PyResult<Option<Bound<'py, PyDict>>> {
    let o = mapa_de_python(opc)?;
    if !o.contiene("num_ctx") {
        return Err(PyKeyError::new_err("num_ctx")); // nueva["num_ctx"] de Python, con el 4096 por defecto > 2048
    }
    cal::reducir(&mapa_de_python(ficha)?, &o).map(|m| mapa_a_python(py, &m)).transpose()
}

#[pyfunction]
fn deducir<'py>(py: Python<'py>, ficha: &Bound<'py, PyAny>, r: &Bound<'py, PyAny>, maq: &MaquinaPy) -> PyResult<Bound<'py, PyDict>> {
    mapa_a_python(py, &cal::deducir(&mapa_de_python(ficha)?, &mapa_de_python(r)?, maq.nucleo()))
}

#[pyfunction]
#[pyo3(signature = (previa, nuevas))]
fn combinar<'py>(py: Python<'py>, previa: Option<&Bound<'py, PyAny>>, nuevas: Vec<Bound<'py, PyAny>>) -> PyResult<Bound<'py, PyDict>> {
    let p = match previa {
        Some(p) if p.is_truthy()? => Some(mapa_de_python(p)?),
        _ => None,
    };
    let n = nuevas.iter().map(mapa_de_python).collect::<PyResult<Vec<_>>>()?;
    mapa_a_python(py, &cal::combinar(p.as_ref(), &n))
}

#[pyfunction]
fn elegir_modelos_prueba<'py>(py: Python<'py>, fichas: Vec<Bound<'py, PyAny>>, maq: &MaquinaPy) -> PyResult<Bound<'py, PyList>> {
    let f = fichas.iter().map(mapa_de_python).collect::<PyResult<Vec<_>>>()?;
    let l = PyList::empty(py);
    for x in cal::elegir_modelos_prueba(&f, maq.nucleo()) {
        l.append(mapa_a_python(py, &x)?)?;
    }
    Ok(l)
}

#[pyfunction]
fn estado_gpu<'py>(py: Python<'py>) -> PyResult<Option<Bound<'py, PyDict>>> {
    py.detach(cal::estado_gpu).map(|m| mapa_a_python(py, &m)).transpose()
}

/// Genera en streaming (sin el GIL); `parar()` se mira tras cada trozo. Lanza `por_calor` si hay que cortar y
/// RuntimeError con el mensaje de Ollama si falla.
#[pyfunction]
fn generar_stream<'py>(
    py: Python<'py>,
    url: &str,
    cuerpo: &Bound<'py, PyAny>,
    parar: Py<PyAny>,
    segundos: f64,
    por_calor: &Bound<'py, PyAny>,
) -> PyResult<Bound<'py, PyDict>> {
    let c = mapa_de_python(cuerpo)?;
    let fin = py.detach(|| {
        cal::generar_stream(url, &c, || Python::attach(|py| parar.call0(py).and_then(|v| v.is_truthy(py)).unwrap_or(false)), segundos)
    });
    match fin {
        FinGenerar::Hecho(d) => mapa_a_python(py, &d),
        FinGenerar::PorCalor => Err(PyErr::from_value(por_calor.call0()?)),
        FinGenerar::Error(e) => Err(PyRuntimeError::new_err(e)),
    }
}

#[pyfunction]
fn ps<'py>(py: Python<'py>, url: &str, modelo: &str) -> PyResult<Option<Bound<'py, PyDict>>> {
    py.detach(|| cal::ps(url, modelo)).map(|m| mapa_a_python(py, &m)).transpose()
}

#[pyfunction]
fn descargar(py: Python<'_>, url: &str, modelo: &str) {
    py.detach(|| cal::descargar(url, modelo));
}

/// El mundo de una prueba: el objeto de Python que da cada pieza (para que las pruebas puedan sustituirlas)
struct MundoPython<'a, 'py> {
    py: Python<'py>,
    mundo: &'a Bound<'py, PyAny>,
}

impl MundoPython<'_, '_> {
    fn llamar0(&self, metodo: &str) -> PyResult<Bound<'_, PyAny>> {
        self.mundo.call_method0(metodo)
    }
}

impl MundoPrueba for MundoPython<'_, '_> {
    type Error = PyErr;

    fn cancelado(&mut self) -> PyResult<bool> {
        self.llamar0("cancelado")?.is_truthy()
    }

    fn cancelar(&mut self) -> PyErr {
        match self.llamar0("cancelar") {
            Ok(e) => PyErr::from_value(e),
            Err(e) => e,
        }
    }

    fn esperar(&mut self, s: f64) -> PyResult<bool> {
        self.mundo.call_method1("esperar", (s,))?.is_truthy()
    }

    fn dormir(&mut self, s: f64) -> PyResult<()> {
        self.mundo.call_method1("dormir", (s,))?;
        Ok(())
    }

    fn ahora(&mut self) -> PyResult<f64> {
        self.llamar0("ahora")?.extract()
    }

    fn estado_gpu(&mut self) -> PyResult<Option<Mapa>> {
        let e = self.llamar0("estado_gpu")?;
        if !e.is_truthy()? {
            return Ok(None);
        }
        Ok(Some(mapa_de_python(&e)?))
    }

    fn reanudar(&mut self) -> PyResult<f64> {
        self.llamar0("reanudar")?.extract()
    }

    fn limite(&mut self) -> PyResult<f64> {
        self.llamar0("limite")?.extract()
    }

    fn avisar(&mut self, evento: Mapa) -> PyResult<()> {
        self.mundo.call_method1("avisar", (mapa_a_python(self.py, &evento)?,))?;
        Ok(())
    }

    fn muestreo_empezar(&mut self, limite: f64) -> PyResult<()> {
        self.mundo.call_method1("muestreo_empezar", (limite,))?;
        Ok(())
    }

    fn muestreo_terminar(&mut self) -> PyResult<(f64, f64)> {
        self.llamar0("muestreo_terminar")?.extract()
    }

    fn generar(&mut self, cuerpo: &Mapa) -> PyResult<FinGenerar> {
        let r = self.mundo.call_method1("generar", (mapa_a_python(self.py, cuerpo)?,))?;
        let t = r.cast::<PyTuple>()?;
        let tipo: String = t.get_item(0)?.extract()?;
        Ok(match tipo.as_str() {
            "hecho" => FinGenerar::Hecho(mapa_de_python(&t.get_item(1)?)?),
            "calor" => FinGenerar::PorCalor,
            _ => FinGenerar::Error(t.get_item(1)?.extract()?),
        })
    }

    fn ps(&mut self, modelo: &str) -> PyResult<Option<Mapa>> {
        let r = self.mundo.call_method1("ps", (modelo,))?;
        if !r.is_truthy()? {
            return Ok(None);
        }
        Ok(Some(mapa_de_python(&r)?))
    }

    fn descargar(&mut self, modelo: &str) -> PyResult<()> {
        self.mundo.call_method1("descargar", (modelo,))?;
        Ok(())
    }

    fn explicar(&mut self, error: &str) -> PyResult<String> {
        self.mundo.call_method1("explicar", (error,))?.extract()
    }
}

/// Una prueba completa con el mundo que da la fachada
#[pyfunction]
fn probar<'py>(
    py: Python<'py>,
    mundo: &Bound<'py, PyAny>,
    ficha: &Bound<'py, PyAny>,
    opciones: &Bound<'py, PyAny>,
    num_predict: i64,
    dejar_cargado: bool,
) -> PyResult<Bound<'py, PyDict>> {
    let f = mapa_de_python(ficha)?;
    if !f.contiene("nombre") {
        return Err(PyKeyError::new_err("nombre"));
    }
    let o = mapa_de_python(opciones)?;
    let mut m = MundoPython { py, mundo };
    let r = cal::probar(&f, &o, &mut m, num_predict, dejar_cargado)?;
    mapa_a_python(py, &r)
}

/// Espera a que la GPU se enfríe (false si no baja a tiempo)
#[pyfunction]
#[pyo3(signature = (mundo, tope, espera_max))]
fn esperar_temperatura(py: Python<'_>, mundo: &Bound<'_, PyAny>, tope: Option<f64>, espera_max: f64) -> PyResult<bool> {
    let mut m = MundoPython { py, mundo };
    cal::esperar_temperatura(&mut m, tope, espera_max)
}

pub fn registrar(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add("ESPERA_MAX_S", cal::ESPERA_MAX_S)?;
    m.add("MAX_INTENTOS", cal::MAX_INTENTOS)?;
    m.add("CITAS_MINIMAS", cal::CITAS_MINIMAS)?;
    m.add("TEXTO_CANARIO", cal::TEXTO_CANARIO)?;
    m.add("PROMPT_CANARIO", cal::prompt_canario())?;
    m.add_function(wrap_pyfunction!(puntuar_canario, m)?)?;
    m.add_function(wrap_pyfunction!(es_oom, m)?)?;
    m.add_function(wrap_pyfunction!(reducir, m)?)?;
    m.add_function(wrap_pyfunction!(deducir, m)?)?;
    m.add_function(wrap_pyfunction!(combinar, m)?)?;
    m.add_function(wrap_pyfunction!(elegir_modelos_prueba, m)?)?;
    m.add_function(wrap_pyfunction!(estado_gpu, m)?)?;
    m.add_function(wrap_pyfunction!(generar_stream, m)?)?;
    m.add_function(wrap_pyfunction!(ps, m)?)?;
    m.add_function(wrap_pyfunction!(descargar, m)?)?;
    m.add_function(wrap_pyfunction!(probar, m)?)?;
    m.add_function(wrap_pyfunction!(esperar_temperatura, m)?)?;
    Ok(())
}
