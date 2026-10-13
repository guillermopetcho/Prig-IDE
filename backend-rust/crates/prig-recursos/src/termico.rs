//! Monitor de temperaturas y gobernador térmico (backend/recursos/termico.py).
//!
//! LÍMITE. La GPU no debe pasar de 60 °C (ajustable). Medido en un portátil con RTX 4050 generando con un 7B entero
//! en GPU: reposo 36 °C → 44 °C a los 3 s → 53 °C a los 28 s (≈ +0,36 °C/s sostenido); al cortar, de 53 a 48 °C en
//! 3 s. Pausar solo entre pasos no basta: el gobernador corta DENTRO de la generación y se continúa después sin
//! perder nada.
//!
//! APRENDER. Al RETOMAR, la GPU salta +7-8 °C en el primer segundo. Ese salto llega antes que la primera lectura, así
//! que lo que evita volver a llegar es REANUDAR más frío. El gobernador aprende el salto (se reanuda a
//! límite − salto − 2), el margen (cuánto sigue subiendo tras cortar: se corta a límite − margen) y el reposo (de
//! cuánto no baja la GPU parada: si límite − salto no deja sitio, avisa con el límite mínimo viable). Lo aprendido se
//! guarda en el almacén.
//!
//! Todo lo de fuera (reloj, monitor, ritmo, motor MoE, almacén) entra por `MundoGobernador`, en el mismo orden en que
//! lo pedía Python: hay pruebas que cuentan las lecturas del reloj.

use crate::valor::{fijo, redondear, redondear_entero, Mapa, Valor};
use std::collections::VecDeque;
use std::sync::{Mutex, MutexGuard};

pub const LIMITE_GPU: f64 = 60.0;
pub const CPU_AVISO: f64 = 85.0;
pub const CPU_ALTO: f64 = 95.0;
pub const INTERVALO_S: f64 = 2.0;
pub const INACTIVO_S: f64 = 25.0; // sin nadie mirando ni trabajando, el monitor se duerme
pub const HISTORIAL: usize = 180; // 6 minutos a 2 s
pub const SALTO_INICIAL: f64 = 8.0; // medido en RTX 4050 portátil con un 7B
pub const SEGUNDOS_SALTO: f64 = 4.0; // el salto se mide en los primeros segundos del tramo
pub const MARGEN_MAXIMO: f64 = 3.0;
pub const FRESCAS_PARA_AFLOJAR: i128 = 8;
pub const ESPERA_MAXIMA_S: f64 = 600.0;
pub const MESETA_S: f64 = 20.0; // sin bajar 1 °C en este tiempo, no va a enfriar más

pub fn ajustes_por_defecto() -> Mapa {
    Mapa::new()
        .con("limite_gpu", LIMITE_GPU)
        .con("margen", 1.0) // se corta a límite − margen
        .con("salto_c", Valor::Nulo) // subida al empezar un tramo (None: SALTO_INICIAL)
        .con("reposo_c", Valor::Nulo) // de aquí no baja la GPU parada
        .con("alcances", 0)
        .con("frescas_seguidas", 0)
}

fn min_py(a: f64, b: f64) -> f64 {
    if b < a {
        b
    } else {
        a
    }
}

fn max_py(a: f64, b: f64) -> f64 {
    if b > a {
        b
    } else {
        a
    }
}

/// `max(a, b)` de Python sobre valores: el primero si empatan
fn max_valor(a: &Valor, b: &Valor) -> Valor {
    match (a.num(), b.num()) {
        (Some(x), Some(y)) if y > x => b.clone(),
        _ => a.clone(),
    }
}

fn num(v: &Valor) -> f64 {
    v.num().unwrap_or(f64::NAN)
}

/// `a - b` de Python: un entero si los dos lo son
fn restar(a: &Valor, b: &Valor) -> Valor {
    match (a, b) {
        (Valor::Entero(x), Valor::Entero(y)) => Valor::Entero(x - y),
        _ => Valor::Real(num(a) - num(b)),
    }
}

// =========================================================================== lecturas

fn componentes(lectura: &Valor) -> &[Valor] {
    match lectura {
        Valor::Mapa(m) => m.lista("componentes").unwrap_or(&[]),
        _ => &[],
    }
}

/// La GPU más caliente de una lectura
pub fn temp_gpu(lectura: &Valor) -> Valor {
    let mut mayor = Valor::Nulo;
    for c in componentes(lectura) {
        let Valor::Mapa(c) = c else { continue };
        if c.texto("tipo") == Some("gpu") && c.get("temp").is_some_and(|t| !t.es_nulo()) {
            let t = c.valor("temp");
            mayor = if mayor.es_nulo() { t.clone() } else { max_valor(&mayor, t) };
        }
    }
    mayor
}

/// La primera CPU de una lectura
pub fn temp_cpu(lectura: &Valor) -> Valor {
    for c in componentes(lectura) {
        let Valor::Mapa(c) = c else { continue };
        if c.texto("tipo") == Some("cpu") {
            return c.valor("temp").clone();
        }
    }
    Valor::Nulo
}

// =========================================================================== monitor

/// El estado del monitor: la última lectura, el historial (6 minutos) y quién lo está usando. El bucle que lee cada
/// 2 s lo lleva quien lo usa (en Python, su hilo).
#[derive(Debug, Default)]
pub struct NucleoMonitor {
    pub ultima: Option<Valor>,
    pub historial: VecDeque<Mapa>,
    pub consulta: f64,
    pub trabajos: i64,
}

impl NucleoMonitor {
    pub fn vivo(&self, ahora: f64) -> bool {
        self.trabajos > 0 || ahora - self.consulta < INACTIVO_S
    }

    /// Guarda una lectura y apunta {t, gpu, cpu} en el historial
    pub fn registrar(&mut self, lectura: Valor) {
        let tomada = match &lectura {
            Valor::Mapa(m) => m.valor("tomada").clone(),
            _ => Valor::Nulo,
        };
        let t = match tomada {
            Valor::Entero(n) => Valor::Entero(n),
            v => Valor::Real(redondear(num(&v), 1)),
        };
        self.historial.push_back(Mapa::new().con("t", t).con("gpu", temp_gpu(&lectura)).con("cpu", temp_cpu(&lectura)));
        while self.historial.len() > HISTORIAL {
            self.historial.pop_front();
        }
        self.ultima = Some(lectura);
    }

    /// La última lectura si tiene menos de `max_edad` segundos
    pub fn fresca(&self, ahora: f64, max_edad: f64) -> Option<Valor> {
        let u = self.ultima.as_ref()?;
        let tomada = match u {
            Valor::Mapa(m) => m.num_o("tomada", f64::NAN),
            _ => f64::NAN,
        };
        if ahora - tomada > max_edad {
            return None;
        }
        Some(u.clone())
    }

    /// °C por segundo en las últimas lecturas de hasta 5 s (positivo: calentando). Ventana corta a propósito: al
    /// retomar tras una pausa, lecturas más viejas son de enfriamiento y esconderían la subida del arranque.
    pub fn tendencia_gpu(&self, desde: Option<f64>) -> f64 {
        let t = |h: &Mapa| h.num_o("t", f64::NAN);
        let g = |h: &Mapa| h.num_o("gpu", f64::NAN);
        let mut recientes: Vec<&Mapa> = self
            .historial
            .iter()
            .filter(|h| h.get("gpu").is_some_and(|v| !v.es_nulo()) && desde.is_none_or(|d| t(h) >= d))
            .collect();
        if let Some(ultimo) = recientes.last().copied() {
            let n = recientes.len();
            recientes = recientes[n.saturating_sub(3)..].iter().copied().filter(|h| t(ultimo) - t(h) <= 5.0).collect();
        }
        if recientes.len() < 2 || t(recientes[recientes.len() - 1]) <= t(recientes[0]) {
            return 0.0;
        }
        let (a, b) = (recientes[0], recientes[recientes.len() - 1]);
        (g(b) - g(a)) / (t(b) - t(a))
    }
}

// =========================================================================== tramo

/// Un tramo seguido de generación, entre dos pausas
#[derive(Debug, Clone)]
pub struct Tramo {
    pub inicio: f64,
    pub temp_inicio: Valor,
    pub pico: Valor,
    pub max_arranque: Valor, // máximo en los primeros SEGUNDOS_SALTO
    pub temp_corte: Valor,
    pub pico_en_pausa: Valor,
    pub pausa_ritmo: Valor,
}

impl Tramo {
    pub fn new(temp_inicio: Valor, ahora: f64) -> Tramo {
        Tramo {
            inicio: ahora,
            pico: temp_inicio.clone(),
            max_arranque: temp_inicio.clone(),
            temp_inicio,
            temp_corte: Valor::Nulo,
            pico_en_pausa: Valor::Nulo,
            pausa_ritmo: Valor::Nulo,
        }
    }

    /// El reloj solo se lee si hay temperatura
    pub fn anotar<E>(&mut self, temp: &Valor, ahora: impl FnOnce() -> Result<f64, E>) -> Result<(), E> {
        if temp.es_nulo() {
            return Ok(());
        }
        self.pico = if self.pico.es_nulo() { temp.clone() } else { max_valor(&self.pico, temp) };
        if ahora()? - self.inicio <= SEGUNDOS_SALTO {
            self.max_arranque = if self.max_arranque.es_nulo() { temp.clone() } else { max_valor(&self.max_arranque, temp) };
        }
        Ok(())
    }

    pub fn segundos(&self, ahora: f64) -> f64 {
        ahora - self.inicio
    }

    pub fn pico_real(&self) -> Valor {
        match (self.pico.es_nulo(), self.pico_en_pausa.es_nulo()) {
            (true, true) => Valor::Nulo,
            (false, true) => self.pico.clone(),
            (true, false) => self.pico_en_pausa.clone(),
            (false, false) => max_valor(&self.pico, &self.pico_en_pausa),
        }
    }
}

// =========================================================================== gobernador

/// Lo de fuera del gobernador. `Error` es el de quien lo implementa (en Python, la excepción): se propaga.
pub trait MundoGobernador {
    type Error;
    fn ahora(&mut self) -> Result<f64, Self::Error>;
    /// `monitor.gpu(max_edad=…)`; con None, `monitor.gpu()`
    fn gpu(&mut self, max_edad: Option<f64>) -> Result<Valor, Self::Error>;
    fn tendencia_gpu(&mut self, desde: f64) -> Result<f64, Self::Error>;
    fn trabajando_entrar(&mut self) -> Result<(), Self::Error>;
    fn trabajando_salir(&mut self) -> Result<(), Self::Error>;
    fn dosifica_el_motor(&mut self) -> Result<bool, Self::Error>;
    fn moe_generando(&mut self) -> Result<bool, Self::Error>;
    fn ritmo_marcar(&mut self) -> Result<(), Self::Error>;
    fn ritmo_activo(&mut self) -> Result<bool, Self::Error>;
    fn ritmo_cpu_eficiente(&mut self) -> Result<bool, Self::Error>;
    fn ritmo_pausa(&mut self, segundos: f64, temp: &Valor) -> Result<Option<f64>, Self::Error>;
    /// `fijador.aplicar()`; sus fallos no paran nada (try/except en Python)
    fn aplicar_fijador(&mut self);
    /// Espera `s` segundos (`cancelar.wait(s)` o `time.sleep(s)`); true si se canceló
    fn esperar(&mut self, s: f64) -> Result<bool, Self::Error>;
    fn hay_avisos(&mut self) -> bool;
    fn avisar(&mut self, evento: Mapa) -> Result<(), Self::Error>;
    fn persistir(&mut self, guardar: Guardar) -> Result<(), Self::Error>;
}

/// Lo que hay que guardar en el almacén: los ajustes, y el evento con su texto y sus datos. Las operaciones del
/// gobernador lo devuelven en vez de guardarlo: así se guarda sin tenerlo bloqueado.
#[derive(Debug, Clone)]
pub struct Guardar {
    pub ajustes: Mapa,
    pub texto: Option<String>,
    pub datos: Option<Mapa>,
}

#[derive(Debug, Clone)]
pub struct Gobernador {
    pub ajustes: Mapa,
    pub pausa: Option<Mapa>,
    pub aviso: Option<String>,
    pub guardar: bool,
}

/// Texto de una pausa para enfriar
pub fn texto_pausa(motivo: &str, temp: f64, objetivo: f64, limite: f64) -> String {
    let base = match motivo {
        "limite" => format!("La GPU está a {} °C, al borde del límite de {}", fijo(temp, 0), fijo(limite, 0)),
        "prevision" => format!("La GPU va a llegar a {} °C (ahora {})", fijo(limite, 0), fijo(temp, 0)),
        "antes_de_paso" => format!("La GPU está a {} °C", fijo(temp, 0)),
        _ => format!("GPU a {} °C", fijo(temp, 0)),
    };
    format!("{base}: pausa hasta {} °C.", fijo(objetivo, 0))
}

fn bloquear(g: &Mutex<Gobernador>) -> MutexGuard<'_, Gobernador> {
    g.lock().unwrap_or_else(|e| e.into_inner())
}

/// Las lecturas del reloj que hace `terminar_tramo`, con las condiciones de Python (solo dependen del tramo)
pub fn segundos_para_terminar<E>(
    tramo: &Tramo,
    motivo: Option<&str>,
    mut ahora: impl FnMut() -> Result<f64, E>,
) -> Result<(Option<f64>, Option<f64>), E> {
    if motivo == Some("ritmo") || tramo.temp_inicio.es_nulo() || tramo.max_arranque.es_nulo() {
        return Ok((None, None));
    }
    let primero = tramo.segundos(ahora()?);
    let segundo = if primero >= 1.5 && !tramo.pico_en_pausa.es_nulo() { Some(tramo.segundos(ahora()?)) } else { None };
    Ok((Some(primero), segundo))
}

impl Gobernador {
    /// Con lo guardado (solo las claves conocidas; lo viejo desconocido se ignora)
    pub fn new(guardados: Option<&Mapa>, guardar: bool) -> Gobernador {
        let mut ajustes = ajustes_por_defecto();
        if let Some(g) = guardados {
            for (k, v) in g.iter() {
                if ajustes.contiene(k) {
                    ajustes.poner(k.clone(), v.clone());
                }
            }
        }
        Gobernador { ajustes, pausa: None, aviso: None, guardar }
    }

    pub fn limite(&self) -> f64 {
        self.ajustes.num_o("limite_gpu", f64::NAN)
    }

    pub fn salto(&self) -> f64 {
        match self.ajustes.get("salto_c") {
            Some(v) if v.verdad() => num(v),
            _ => SALTO_INICIAL,
        }
    }

    pub fn corte(&self) -> f64 {
        let margen = match self.ajustes.get("margen") {
            Some(v) if v.verdad() => num(v),
            _ => 0.0,
        };
        self.limite() - margen
    }

    fn reposo(&self) -> Option<f64> {
        self.ajustes.get("reposo_c").filter(|v| !v.es_nulo()).map(num)
    }

    pub fn reanudar(&self) -> f64 {
        let mut objetivo = min_py(self.limite() - 4.0, self.limite() - self.salto() - 2.0);
        if let Some(r) = self.reposo() {
            objetivo = max_py(objetivo, r + 1.0);
        }
        redondear(objetivo, 1)
    }

    pub fn viable(&self) -> bool {
        self.reposo().is_none_or(|r| r + self.salto() + 1.0 < self.limite())
    }

    pub fn limite_minimo_viable(&self) -> Option<f64> {
        self.reposo().map(|r| redondear_entero(r + self.salto() + 2.0) as f64)
    }

    fn guardado(&self, texto: Option<String>, datos: Option<Mapa>) -> Option<Guardar> {
        self.guardar.then(|| Guardar { ajustes: self.ajustes.clone(), texto, datos })
    }

    /// Error: el mensaje del ValueError de Python
    pub fn fijar_limite(&mut self, limite: f64) -> Result<Option<Guardar>, String> {
        if !(40.0..=95.0).contains(&limite) {
            return Err("El límite de la GPU debe estar entre 40 y 95 °C".into());
        }
        self.ajustes.poner("limite_gpu", limite);
        self.aviso = None;
        Ok(self.guardado(Some(format!("Límite térmico de la GPU: {} °C", fijo(limite, 0))), None))
    }

    pub fn olvidar(&mut self) -> Option<Guardar> {
        let limite = self.ajustes.valor("limite_gpu").clone();
        self.ajustes = ajustes_por_defecto().con("limite_gpu", limite);
        self.aviso = None;
        self.guardado(Some("Olvidado lo aprendido sobre el calor de la GPU".into()), None)
    }

    /// `{**ajustes, ritmo, salto, corte, reanudar, viable, limite_minimo_viable, aviso, pausa}`
    pub fn estado(&self, ritmo: Mapa) -> Mapa {
        self.ajustes
            .clone()
            .con("ritmo", ritmo)
            .con("salto", self.salto())
            .con("corte", self.corte())
            .con("reanudar", self.reanudar())
            .con("viable", self.viable())
            .con("limite_minimo_viable", self.limite_minimo_viable())
            .con("aviso", self.aviso.clone())
            .con("pausa", self.pausa.clone().map(Valor::Mapa).unwrap_or(Valor::Nulo))
    }

    // -- tramos

    /// Lo previo a empezar un tramo: marca el ritmo, fija los núcleos si toca y devuelve la temperatura de partida
    pub fn preparar_tramo<M: MundoGobernador>(mundo: &mut M) -> Result<Valor, M::Error> {
        mundo.ritmo_marcar()?;
        if mundo.ritmo_activo()? && mundo.ritmo_cpu_eficiente()? {
            mundo.aplicar_fijador();
        }
        mundo.gpu(Some(1.0))
    }

    pub fn empezar_tramo<M: MundoGobernador>(mundo: &mut M) -> Result<Tramo, M::Error> {
        let temp = Self::preparar_tramo(mundo)?;
        Ok(Tramo::new(temp, mundo.ahora()?))
    }

    /// ¿Hay que parar ya la generación en curso? "limite", "prevision", "ritmo" o None. Solo lee el gobernador.
    pub fn debe_cortar<M: MundoGobernador>(&self, tramo: &mut Tramo, mundo: &mut M) -> Result<Option<&'static str>, M::Error> {
        let temp = mundo.gpu(Some(1.0))?;
        tramo.anotar(&temp, || mundo.ahora())?;
        if temp.es_nulo() {
            return Ok(None);
        }
        let t = num(&temp);
        let mut motivo = None;
        if t >= self.corte() {
            motivo = Some("limite");
        } else if t + max_py(0.0, mundo.tendencia_gpu(tramo.inicio + SEGUNDOS_SALTO)?) * 2.0 >= self.corte() {
            // Leer y cortar tardan ~2 s: si a este ritmo se llega antes, se corta ya
            motivo = Some("prevision");
        }
        if let Some(m) = motivo {
            tramo.temp_corte = temp;
            return Ok(Some(m));
        }
        // Modo suave: si el motor ya dosifica por dentro, no se corta la petición
        if mundo.dosifica_el_motor()? {
            return Ok(None);
        }
        // El motor MoE tampoco: retomar tras un corte le obliga a releer casi todo el prompt (lo regula el modo frío)
        if mundo.moe_generando()? {
            return Ok(None);
        }
        mundo.ritmo_marcar()?;
        let segundos = tramo.segundos(mundo.ahora()?);
        if let Some(p) = mundo.ritmo_pausa(segundos, &temp)?.filter(|p| *p != 0.0) {
            tramo.pausa_ritmo = Valor::Real(p);
            return Ok(Some("ritmo"));
        }
        Ok(None)
    }

    /// La pausa corta del modo suave: un tiempo fijo, no «hasta que baje a X»
    pub fn descansar<M: MundoGobernador>(tramo: &Tramo, mundo: &mut M) -> Result<f64, M::Error> {
        let s = if tramo.pausa_ritmo.verdad() { num(&tramo.pausa_ritmo) } else { 0.0 };
        if s <= 0.0 {
            return Ok(0.0);
        }
        mundo.esperar(s)?;
        Ok(s)
    }

    /// Espera hasta que la GPU baje a `objetivo` (por defecto, la de reanudar), con avisos. Anota en el tramo lo que
    /// siguió subiendo ya en pausa. Si la GPU deja de bajar (meseta), aprende el reposo y sigue. El gobernador solo se
    /// bloquea un instante para apuntar y quitar la pausa (se ve desde fuera mientras dura) y para aprender.
    pub fn enfriar<M: MundoGobernador>(
        compartido: &Mutex<Gobernador>,
        motivo: &str,
        objetivo: Option<f64>,
        maximo_s: f64,
        mut tramo: Option<&mut Tramo>,
        mundo: &mut M,
    ) -> Result<f64, M::Error> {
        let objetivo = objetivo.unwrap_or_else(|| bloquear(compartido).reanudar());
        let inicio = mundo.ahora()?;
        let temp = mundo.gpu(Some(1.0))?;
        if let Some(t) = tramo.as_deref_mut() {
            t.pico_en_pausa = temp.clone();
        }
        if temp.es_nulo() || num(&temp) <= objetivo {
            return Ok(0.0);
        }
        bloquear(compartido).pausa = Some(
            Mapa::new().con("motivo", motivo).con("desde", inicio).con("temp", temp.clone()).con("objetivo", objetivo),
        );
        if mundo.hay_avisos() {
            let limite = bloquear(compartido).limite();
            let texto = texto_pausa(motivo, num(&temp), objetivo, limite);
            // en Python, antes del try: si falla, la pausa queda apuntada
            mundo.avisar(
                Mapa::new()
                    .con("tipo", "enfriando")
                    .con("motivo", motivo)
                    .con("temp_c", temp.clone())
                    .con("objetivo_c", objetivo)
                    .con("mensaje", texto),
            )?;
        }
        let mut minima = temp.clone();
        let mut meseta = false;
        let bucle = (|| -> Result<(), M::Error> {
            let mut t_minima = mundo.ahora()?;
            mundo.trabajando_entrar()?;
            let r = (|| -> Result<(), M::Error> {
                while mundo.ahora()? - inicio < maximo_s {
                    if mundo.esperar(1.0)? {
                        break;
                    }
                    let temp = mundo.gpu(Some(1.0))?;
                    if temp.es_nulo() || num(&temp) <= objetivo {
                        break;
                    }
                    if let Some(t) = tramo.as_deref_mut() {
                        if mundo.ahora()? - inicio <= 4.0 {
                            let previo = if t.pico_en_pausa.verdad() { t.pico_en_pausa.clone() } else { temp.clone() };
                            t.pico_en_pausa = max_valor(&previo, &temp);
                        }
                    }
                    if num(&temp) <= num(&minima) - 1.0 {
                        minima = temp;
                        t_minima = mundo.ahora()?;
                    } else if mundo.ahora()? - t_minima >= MESETA_S {
                        meseta = true;
                        break;
                    }
                }
                Ok(())
            })();
            let salir = mundo.trabajando_salir();
            r?;
            salir
        })();
        bloquear(compartido).pausa = None;
        bucle?;
        if meseta {
            let g = bloquear(compartido).anotar_reposo(&minima);
            if let Some(g) = g {
                mundo.persistir(g)?;
            }
        }
        let esperado = mundo.ahora()? - inicio;
        if mundo.hay_avisos() {
            let ahora = mundo.gpu(None)?;
            let texto = if meseta {
                format!("La GPU no baja de {} °C: se reanuda tras {} s.", fijo(num(&minima), 0), fijo(esperado, 0))
            } else {
                let a = if ahora.verdad() { num(&ahora) } else { 0.0 };
                format!("GPU a {} °C tras {} s: se reanuda.", fijo(a, 0), fijo(esperado, 0))
            };
            mundo.avisar(
                Mapa::new()
                    .con("tipo", "reanudando")
                    .con("segundos", redondear_entero(esperado))
                    .con("temp_c", ahora)
                    .con("meseta", meseta)
                    .con("mensaje", texto),
            )?;
            let aviso = bloquear(compartido).aviso.clone();
            if let Some(aviso) = aviso.filter(|a| !a.is_empty()) {
                mundo.avisar(Mapa::new().con("tipo", "aviso_termico").con("mensaje", aviso))?;
            }
        }
        Ok(esperado)
    }

    /// La GPU no baja de `minima` en pausa: se apunta como reposo (si cambió medio grado o más)
    pub fn anotar_reposo(&mut self, minima: &Valor) -> Option<Guardar> {
        if let Some(previo) = self.reposo() {
            if (previo - num(minima)).abs() < 0.5 {
                return None;
            }
        }
        self.ajustes.poner("reposo_c", minima.clone());
        self.revisar_viabilidad();
        let texto = format!(
            "La GPU no baja de {} °C en pausa: se reanuda a {} °C.",
            fijo(num(minima), 0),
            fijo(self.reanudar(), 0)
        );
        self.guardado(Some(texto), Some(Mapa::new().con("reposo", minima.clone())))
    }

    pub fn revisar_viabilidad(&mut self) {
        if self.viable() {
            self.aviso = None;
            return;
        }
        self.aviso = Some(format!(
            "Con el límite de {} °C la GPU no puede trabajar sin pasarlo: parada no baja de {} °C y al empezar sube {} °C \
             de golpe. Seguirá pausando, pero irá muy lento. Límite mínimo viable: {} °C.",
            fijo(self.limite(), 0),
            fijo(self.reposo().unwrap_or(f64::NAN), 0),
            fijo(self.salto(), 0),
            fijo(self.limite_minimo_viable().unwrap_or(f64::NAN), 0)
        ));
    }

    /// Aprende del tramo: salto al empezar, inercia al cortar, si llegó al límite. `segundos`: las lecturas de
    /// `segundos_para_terminar`.
    pub fn terminar_tramo(&mut self, tramo: &Tramo, motivo: Option<&str>, segundos: (Option<f64>, Option<f64>)) -> Option<Guardar> {
        if motivo == Some("ritmo") {
            return None; // tramos de un segundo: no enseñan nada sobre el salto ni la inercia
        }
        let mut cambios: Vec<String> = Vec::new();
        // Salto: solo si el tramo duró lo bastante para medirlo
        if segundos.0.is_some_and(|s| s >= 1.5) {
            // Con los tipos de Python: restar dos enteros da un entero, y round(entero, 1) sigue siendo un entero
            let mut medido = max_valor(&Valor::Real(0.0), &restar(&tramo.max_arranque, &tramo.temp_inicio));
            if segundos.1.is_some_and(|s2| s2 <= SEGUNDOS_SALTO) {
                medido = max_valor(&medido, &restar(&tramo.pico_en_pausa, &tramo.temp_inicio));
            }
            let previo = self.ajustes.get("salto_c").filter(|v| !v.es_nulo()).map(num);
            let mut nuevo = match previo {
                None => medido.clone(),
                Some(p) => Valor::Real(0.5 * p + 0.5 * num(&medido)),
            };
            // Solo se aprende hacia arriba de golpe; hacia abajo, despacio
            if let Some(p) = previo {
                if num(&nuevo) < p {
                    nuevo = Valor::Real(0.8 * p + 0.2 * num(&medido));
                }
            }
            let salto = match max_valor(&Valor::Real(1.0), &nuevo) {
                Valor::Entero(n) => Valor::Entero(n),
                v => Valor::Real(redondear(num(&v), 1)),
            };
            self.ajustes.poner("salto_c", salto);
        }
        // Inercia tras cortar
        if !tramo.temp_corte.es_nulo() && !tramo.pico_en_pausa.es_nulo() {
            let inercia = num(&tramo.pico_en_pausa) - num(&tramo.temp_corte);
            if inercia + 0.5 > self.ajustes.num_o("margen", f64::NAN) {
                self.ajustes.poner("margen", redondear(min_py(MARGEN_MAXIMO, inercia + 0.5), 1));
                cambios.push(format!("corta a {} °C", fijo(self.corte(), 0)));
            }
        }
        let pico = tramo.pico_real();
        let entero = |v: Option<&Valor>| match v {
            Some(v) if v.verdad() => v.entero().unwrap_or(0),
            _ => 0,
        };
        if !pico.es_nulo() && num(&pico) >= self.limite() {
            let alcances = entero(self.ajustes.get("alcances")) + 1;
            self.ajustes.poner("alcances", alcances);
            self.ajustes.poner("frescas_seguidas", 0);
            self.revisar_viabilidad();
            let texto = format!(
                "La GPU llegó a {} °C (límite {}). Salto al empezar: {} °C; ahora reanuda a {} °C{}.",
                fijo(num(&pico), 0),
                fijo(self.limite(), 0),
                fijo(self.salto(), 0),
                fijo(self.reanudar(), 0),
                cambios.first().map(|c| format!(" y {c}")).unwrap_or_default()
            );
            let datos = Mapa::new().con("pico", pico).con("salto", self.salto());
            return self.guardado(Some(texto), Some(datos));
        }
        if !pico.es_nulo() && num(&pico) < self.limite() - 3.0 {
            let frescas = entero(self.ajustes.get("frescas_seguidas")) + 1;
            self.ajustes.poner("frescas_seguidas", frescas);
            let margen = self.ajustes.num_o("margen", f64::NAN);
            if frescas >= FRESCAS_PARA_AFLOJAR && margen > 1.0 {
                self.ajustes.poner("margen", max_py(1.0, margen - 0.5));
                self.ajustes.poner("frescas_seguidas", 0);
            }
        }
        let frescas = self.ajustes.get("frescas_seguidas").and_then(Valor::entero).unwrap_or(0);
        if !cambios.is_empty() || frescas.rem_euclid(4) == 0 {
            return self.guardado(None, None);
        }
        None
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn por_defecto_corta_a_59_y_reanuda_a_50() {
        let g = Gobernador::new(None, false);
        assert_eq!((g.limite(), g.corte(), g.reanudar()), (60.0, 59.0, 50.0));
        assert!(g.viable());
    }

    #[test]
    fn limite_inalcanzable() {
        let mut g = Gobernador::new(Some(&Mapa::new().con("limite_gpu", 50.0).con("salto_c", 8.0)), false);
        assert!(g.anotar_reposo(&Valor::Real(42.0)).is_none()); // sin guardar
        assert!(!g.viable());
        assert_eq!(g.limite_minimo_viable(), Some(52.0));
        assert!(g.aviso.as_deref().unwrap().contains("52"));
        assert_eq!(g.reanudar(), 43.0);
    }

    #[test]
    fn tendencia_del_monitor() {
        let mut m = NucleoMonitor::default();
        for (t, g) in [(102.0, 50), (104.0, 52), (106.0, 54), (108.0, 56)] {
            m.registrar(Valor::Mapa(Mapa::new().con("tomada", t).con(
                "componentes",
                Valor::Lista(vec![
                    Mapa::new().con("tipo", "gpu").con("temp", g).into(),
                    Mapa::new().con("tipo", "cpu").con("temp", 70).into(),
                ]),
            )));
        }
        assert!((m.tendencia_gpu(None) - 1.0).abs() < 1e-9);
        assert_eq!(m.tendencia_gpu(Some(107.5)), 0.0);
    }
}
