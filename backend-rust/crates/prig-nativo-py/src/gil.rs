//! Esperar un cerrojo de Rust sin el GIL.
//!
//! Un objeto de Rust con estado (`Mutex`) que llama a Python mientras tiene el cerrojo (`Controlador.paso` lee la
//! temperatura por la fachada) y otro hilo que pide ese cerrojo teniendo el GIL (un getter desde una petición) se
//! esperan para siempre: el primero necesita el GIL para volver de Python y el segundo no lo suelta mientras espera
//! el cerrojo. Pasó: con la interfaz abierta, `/api/recursos/temperaturas` y el hilo del modo suave colgaban el
//! backend de Python entero. Aquí, si el cerrojo está ocupado, se espera sin el GIL y se vuelve a intentar.

use pyo3::prelude::*;
use std::sync::{Mutex, MutexGuard, TryLockError};

pub fn bloquear<T: Send>(m: &Mutex<T>) -> MutexGuard<'_, T> {
    loop {
        match m.try_lock() {
            Ok(g) => return g,
            Err(TryLockError::Poisoned(e)) => return e.into_inner(),
            Err(TryLockError::WouldBlock) => {
                // espera a que se suelte sin tener el GIL (si este hilo no lo tiene, es una espera normal)
                Python::attach(|py| {
                    py.detach(|| {
                        drop(m.lock());
                    })
                });
            }
        }
    }
}
