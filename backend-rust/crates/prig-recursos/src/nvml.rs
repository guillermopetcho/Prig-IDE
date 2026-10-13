//! Sensores de la GPU NVIDIA por NVML (backend/recursos/nvml.py): la biblioteca del controlador que usa nvidia-smi por
//! dentro, cargada con `dlopen`.
//!
//! Cada `nvidia-smi --query-gpu=…` es un proceso nuevo de ~27 ms de CPU, y lanzarlo cada pocos segundos bastaba para
//! que auto-cpufreq encendiera el turbo (medido: de 51 a 57,5 °C de media en reposo). Por NVML la misma lectura cuesta
//! microsegundos. Si NVML no está (otra GPU, sin controlador), `lectura` devuelve `None` y quien llama usa nvidia-smi.

use std::ffi::{c_char, c_int, c_uint, c_void, CStr};
use std::sync::Mutex;

type Dispositivo = *mut c_void;

const NVML_TEMPERATURE_GPU: c_int = 0;
const NVML_CLOCK_GRAPHICS: c_int = 0;
const LARGO_NOMBRE: usize = 96; // NVML_DEVICE_NAME_V2_BUFFER_SIZE

#[repr(C)]
#[derive(Default)]
#[allow(dead_code)] // los campos los llena NVML; se lee solo el que hace falta
struct Uso {
    gpu: c_uint,
    memory: c_uint,
}

#[repr(C)]
#[derive(Default)]
#[allow(dead_code)]
struct Memoria {
    total: u64,
    free: u64,
    used: u64,
}

/// Una GPU leída por NVML (las claves de `nvml.lectura()` de Python)
#[derive(Debug, Clone, PartialEq)]
pub struct GpuNvml {
    pub indice: u32,
    pub nombre: String,
    pub temp: Option<f64>,
    pub consumo_w: Option<f64>,
    pub uso_pct: Option<f64>,
    pub ventilador_pct: Option<f64>,
    pub vram_usada_mb: Option<u64>,
    pub vram_total_mb: Option<u64>,
    pub reloj_mhz: Option<f64>,
}

struct Biblioteca {
    cantidad: unsafe extern "C" fn(*mut c_uint) -> c_int,
    por_indice: unsafe extern "C" fn(c_uint, *mut Dispositivo) -> c_int,
    nombre: unsafe extern "C" fn(Dispositivo, *mut c_char, c_uint) -> c_int,
    temperatura: unsafe extern "C" fn(Dispositivo, c_int, *mut c_uint) -> c_int,
    potencia: unsafe extern "C" fn(Dispositivo, *mut c_uint) -> c_int,
    uso: unsafe extern "C" fn(Dispositivo, *mut Uso) -> c_int,
    ventilador: unsafe extern "C" fn(Dispositivo, *mut c_uint) -> c_int,
    memoria: unsafe extern "C" fn(Dispositivo, *mut Memoria) -> c_int,
    reloj: unsafe extern "C" fn(Dispositivo, c_int, *mut c_uint) -> c_int,
}

enum Estado {
    SinIniciar,
    Lista(Biblioteca),
    Fallo, // no se vuelve a intentar (como en Python)
}

static ESTADO: Mutex<Estado> = Mutex::new(Estado::SinIniciar);

/// Busca un símbolo de la biblioteca abierta y lo devuelve con el tipo de función que se le indica
///
/// SAFETY: quien llama garantiza que `F` es la firma C real del símbolo `nombre`.
unsafe fn simbolo<F: Copy>(lib: *mut c_void, nombre: &CStr) -> Option<F> {
    let p = libc::dlsym(lib, nombre.as_ptr());
    if p.is_null() {
        None
    } else {
        Some(std::mem::transmute_copy::<*mut c_void, F>(&p))
    }
}

fn cargar() -> Option<Biblioteca> {
    // SAFETY: dlopen/dlsym con cadenas terminadas en NUL; las firmas son las de nvml.h (las mismas que usa
    // nvml.py con ctypes). La biblioteca no se cierra nunca: los punteros a sus funciones siguen valiendo.
    unsafe {
        let mut lib: *mut c_void = std::ptr::null_mut();
        for nombre in [c"libnvidia-ml.so.1", c"libnvidia-ml.so"] {
            lib = libc::dlopen(nombre.as_ptr(), libc::RTLD_NOW | libc::RTLD_LOCAL);
            if !lib.is_null() {
                break;
            }
        }
        if lib.is_null() {
            return None;
        }
        let iniciar: unsafe extern "C" fn() -> c_int = simbolo(lib, c"nvmlInit_v2")?;
        let b = Biblioteca {
            cantidad: simbolo(lib, c"nvmlDeviceGetCount_v2")?,
            por_indice: simbolo(lib, c"nvmlDeviceGetHandleByIndex_v2")?,
            nombre: simbolo(lib, c"nvmlDeviceGetName")?,
            temperatura: simbolo(lib, c"nvmlDeviceGetTemperature")?,
            potencia: simbolo(lib, c"nvmlDeviceGetPowerUsage")?,
            uso: simbolo(lib, c"nvmlDeviceGetUtilizationRates")?,
            ventilador: simbolo(lib, c"nvmlDeviceGetFanSpeed")?,
            memoria: simbolo(lib, c"nvmlDeviceGetMemoryInfo")?,
            reloj: simbolo(lib, c"nvmlDeviceGetClockInfo")?,
        };
        if iniciar() != 0 {
            return None;
        }
        Some(b)
    }
}

fn con_biblioteca<T>(f: impl FnOnce(&Biblioteca) -> T) -> Option<T> {
    let mut estado = ESTADO.lock().unwrap_or_else(|e| e.into_inner());
    if let Estado::SinIniciar = *estado {
        *estado = match cargar() {
            Some(b) => Estado::Lista(b),
            None => Estado::Fallo,
        };
    }
    match &*estado {
        Estado::Lista(b) => Some(f(b)),
        _ => None,
    }
}

/// ¿Hay NVML? La primera llamada la carga (tarda ~2 s)
pub fn disponible() -> bool {
    con_biblioteca(|_| ()).is_some()
}

/// Todas las GPU, o `None` sin NVML
pub fn lectura() -> Option<Vec<GpuNvml>> {
    con_biblioteca(|b| {
        let mut n: c_uint = 0;
        // SAFETY: cada función recibe punteros a variables locales del tamaño que pide nvml.h
        unsafe {
            if (b.cantidad)(&mut n) != 0 {
                return None;
            }
            let mut salida = Vec::new();
            for i in 0..n {
                let mut h: Dispositivo = std::ptr::null_mut();
                if (b.por_indice)(i, &mut h) != 0 {
                    continue;
                }
                let mut nombre = [0 as c_char; LARGO_NOMBRE];
                let nombre = if (b.nombre)(h, nombre.as_mut_ptr(), LARGO_NOMBRE as c_uint) == 0 {
                    nombre[LARGO_NOMBRE - 1] = 0;
                    String::from_utf8_lossy(CStr::from_ptr(nombre.as_ptr()).to_bytes()).into_owned()
                } else {
                    "GPU".to_string()
                };
                let mut v: c_uint = 0;
                let temp = ((b.temperatura)(h, NVML_TEMPERATURE_GPU, &mut v) == 0).then_some(v as f64);
                let consumo_w = ((b.potencia)(h, &mut v) == 0).then_some(v as f64 / 1000.0);
                let mut uso = Uso::default();
                let uso_pct = ((b.uso)(h, &mut uso) == 0).then_some(uso.gpu as f64);
                let ventilador_pct = ((b.ventilador)(h, &mut v) == 0).then_some(v as f64);
                let mut m = Memoria::default();
                let (vram_usada_mb, vram_total_mb) = if (b.memoria)(h, &mut m) == 0 {
                    (Some(m.used / 1_048_576), Some(m.total / 1_048_576))
                } else {
                    (None, None)
                };
                let reloj_mhz = ((b.reloj)(h, NVML_CLOCK_GRAPHICS, &mut v) == 0).then_some(v as f64);
                salida.push(GpuNvml {
                    indice: i,
                    nombre,
                    temp,
                    consumo_w,
                    uso_pct,
                    ventilador_pct,
                    vram_usada_mb,
                    vram_total_mb,
                    reloj_mhz,
                });
            }
            Some(salida)
        }
    })
    .flatten()
}
