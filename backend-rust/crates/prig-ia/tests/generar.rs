//! El núcleo de generación contra una Ollama falsa (las pruebas de `test_ollama_modelos.py` de Python): opciones por
//! capas, think solo a los modelos que piensan, métricas, el chat con razonamiento, herramientas, consultas repetidas,
//! la última ronda, el corte de un bucle de texto, y generar sin perder lo escrito.

use prig_ia::generar::{self, Herramientas, PedidoChat, PedidoGenerar, PedidoPausas};
use prig_ia::valor::{Mapa, Valor};
use prig_ia::vivo::Cancelar;
use std::collections::VecDeque;
use std::io::{BufRead, BufReader, Read, Write};
use std::net::TcpListener;
use std::path::{Path, PathBuf};

use std::sync::{Arc, Mutex, MutexGuard, OnceLock};

/// Las pruebas cambian el entorno del proceso (HOME, la configuración): de una en una
fn turno() -> MutexGuard<'static, ()> {
    static T: Mutex<()> = Mutex::new(());
    T.lock().unwrap_or_else(|e| e.into_inner())
}

fn casa() -> &'static PathBuf {
    static C: OnceLock<PathBuf> = OnceLock::new();
    C.get_or_init(|| {
        let c = std::env::temp_dir().join(format!("prig-generar-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&c);
        std::fs::create_dir_all(&c).unwrap();
        std::env::set_var("HOME", &c);
        std::env::set_var("PRIG_SIN_MOTOR_SUAVE", "1");
        std::env::set_var("PRIG_SIN_AUTOARRANQUE_OLLAMA", "1");
        c
    })
}

/// Una Ollama falsa: responde por orden los guiones de /api/chat y /api/generate, y las capacidades de /api/show
struct Falsa {
    url: String,
    guiones: Arc<Mutex<VecDeque<(u16, Vec<Valor>)>>>,
    enviados: Arc<Mutex<Vec<(String, Mapa)>>>,
}

impl Falsa {
    fn new(caps: &[&str]) -> Falsa {
        let l = TcpListener::bind("127.0.0.1:0").unwrap();
        let url = format!("http://{}", l.local_addr().unwrap());
        let guiones: Arc<Mutex<VecDeque<(u16, Vec<Valor>)>>> = Arc::default();
        let enviados: Arc<Mutex<Vec<(String, Mapa)>>> = Arc::default();
        let caps: Vec<Valor> = caps.iter().map(|c| Valor::from(*c)).collect();
        let (g, e) = (guiones.clone(), enviados.clone());
        std::thread::spawn(move || {
            for s in l.incoming().flatten() {
                let mut r = BufReader::new(s.try_clone().unwrap());
                let mut primera = String::new();
                if r.read_line(&mut primera).is_err() {
                    continue;
                }
                let ruta = primera.split_whitespace().nth(1).unwrap_or("").to_string();
                let mut largo = 0usize;
                loop {
                    let mut h = String::new();
                    if r.read_line(&mut h).is_err() || h.trim().is_empty() {
                        break;
                    }
                    if let Some(v) = h.to_lowercase().strip_prefix("content-length:") {
                        largo = v.trim().parse().unwrap_or(0);
                    }
                }
                let mut cuerpo = vec![0u8; largo];
                let _ = r.read_exact(&mut cuerpo);
                let pedido = match prig_ia::json::leer(&String::from_utf8_lossy(&cuerpo)) {
                    Ok(Valor::Mapa(m)) => m,
                    _ => Mapa::new(),
                };
                let (codigo, texto) = match ruta.as_str() {
                    "/api/show" => (200, prig_ia::json::escribir_compacto(&Valor::Mapa(Mapa::new().con("capabilities", caps.clone())))),
                    "/api/ps" => (200, "{\"models\": []}".to_string()),
                    "/api/chat" | "/api/generate" => {
                        e.lock().unwrap().push((ruta.clone(), pedido));
                        let (c, lineas) = g.lock().unwrap().pop_front().unwrap_or((500, vec![]));
                        let t: String = lineas.iter().map(|l| prig_ia::json::escribir_compacto(l) + "\n").collect();
                        let error = lineas.first().map(prig_ia::json::escribir_compacto).unwrap_or_else(|| "{\"error\": \"fallo\"}".into());
                        (c, if c == 200 { t } else { error })
                    }
                    _ => (404, "{}".into()),
                };
                let mut s = s;
                let _ = write!(s, "HTTP/1.1 {codigo} X\r\nContent-Type: application/x-ndjson\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{texto}", texto.len());
            }
        });
        let c = casa();
        std::fs::write(c.join(".prig_ai_config.json"), format!("{{\"ollama_url\": \"{url}\", \"num_predict\": 0, \"keep_alive\": \"5m\"}}")).unwrap();
        let _ = std::fs::remove_file(c.join(".prig_modelos.json"));
        // sin modo frío: así las opciones no dependen de los núcleos de esta máquina
        std::fs::write(c.join(".prig_recursos.json"), "{\"version\": 1, \"frio\": {\"activo\": false}}").unwrap();
        Falsa { url, guiones, enviados }
    }

    fn guion(&self, lineas: Vec<Valor>) -> &Falsa {
        self.guiones.lock().unwrap().push_back((200, lineas));
        self
    }

    fn enviados(&self) -> Vec<Mapa> {
        self.enviados.lock().unwrap().iter().map(|(_, m)| m.clone()).collect()
    }
}

fn v(texto: &str) -> Valor {
    prig_ia::json::leer(texto).unwrap()
}

fn raiz() -> &'static Path {
    Path::new("/nonexistent-prig")
}

fn chat(p: &PedidoChat, h: Option<&mut dyn Herramientas>) -> Vec<Mapa> {
    let mut eventos = Vec::new();
    generar::chat_eventos(raiz(), p, h, &Cancelar::default(), &mut |e| eventos.push(e));
    eventos
}

fn tipos(e: &[Mapa]) -> Vec<String> {
    e.iter().map(|x| x.valor("t").texto_py()).collect()
}

fn usuario(t: &str) -> Valor {
    Valor::Mapa(Mapa::new().con("role", "user").con("content", t))
}

struct Sumar {
    ejecutadas: Vec<Valor>,
}

impl Herramientas for Sumar {
    fn definiciones(&mut self) -> Option<Vec<Valor>> {
        Some(vec![v(r#"{"type": "function", "function": {"name": "sumar"}}"#)])
    }

    fn ejecutar(&mut self, _nombre: &str, a: &Valor) -> String {
        self.ejecutadas.push(a.clone());
        let Valor::Mapa(m) = a else { return String::new() };
        format!("{}", m.num_o("a", 0.0) as i64 + m.num_o("b", 0.0) as i64)
    }
}

const FIN: &str = r#"{"message": {}, "done": true, "done_reason": "stop"}"#;

#[test]
fn opciones_por_capas() {
    let _t = turno();
    let _f = Falsa::new(&["completion"]);
    let o = generar::opciones(None, "qwen3:14b", Some("tutor"), raiz());
    for clave in ["temperature", "top_k", "top_p", "repeat_penalty", "low_vram", "f16_kv", "num_gpu"] {
        assert!(!o.contiene(clave), "{clave}");
    }
    assert_eq!(o.valor("num_ctx"), &Valor::Entero(4096));
    prig_modelos::opciones::config()
        .fijar("modelo", &Mapa::new().con("temperature", 0.6).con("num_ctx", 8192), Some("m-capas"), None, false)
        .unwrap();
    let o = generar::opciones(Some(&Mapa::new().con("temperature", 0.0).con("typical_p", 0.9)), "m-capas", None, raiz());
    assert_eq!(o.valor("temperature"), &Valor::Real(0.0)); // lo exige la llamada
    assert_eq!(o.valor("num_ctx"), &Valor::Entero(8192)); // la capa pisa la configuración global
    assert!(!o.contiene("typical_p")); // jamás llega a Ollama
}

#[test]
fn think_solo_a_modelos_que_piensan() {
    let _t = turno();
    for (caps, espera) in [(vec!["completion", "thinking"], Some(Valor::Bool(true))), (vec!["completion"], None)] {
        let _f = Falsa::new(&caps);
        let modelo = format!("piensa-{}", caps.len());
        prig_modelos::opciones::config()
            .fijar(
                "uso",
                &Mapa::new().con("think", true).con("system_extra", "Sé breve.").con("keep_alive", "30m").con("shift", false),
                None,
                Some("tutor"),
                false,
            )
            .unwrap();
        let mut p = Mapa::new();
        let sistema = generar::completar_payload(&mut p, &modelo, Some("tutor"), None, "Eres un tutor.");
        assert_eq!(p.get("think").cloned(), espera);
        assert_eq!(sistema, "Eres un tutor.\n\nSé breve.");
        assert_eq!((p.valor("keep_alive"), p.valor("shift")), (&Valor::Texto("30m".into()), &Valor::Bool(false)));
    }
}

#[test]
fn generar_informa_de_las_metricas() {
    let _t = turno();
    let f = Falsa::new(&["completion"]);
    f.guion(vec![
        v(r#"{"response": "hola", "done": false}"#),
        v(r#"{"response": "", "done": true, "done_reason": "stop", "eval_count": 2, "eval_duration": 100000000, "prompt_eval_count": 3, "prompt_eval_duration": 10000000, "total_duration": 200000000, "load_duration": 0}"#),
    ]);
    let mut eventos = Vec::new();
    let p = PedidoGenerar { prompt: "x".into(), modelo: "m-gen".into(), ..Default::default() };
    generar::generar(raiz(), &p, &Cancelar::default(), &mut |e| eventos.push(e));
    let texto: String = eventos.iter().filter(|e| e.texto("t") == Some("texto")).map(|e| e.valor("v").texto_py()).collect();
    assert_eq!(texto, "hola");
    let stats = eventos.iter().find(|e| e.texto("t") == Some("stats")).unwrap();
    assert_eq!(stats.mapa("v").unwrap().valor("motivo_fin"), &Valor::Texto("stop".into()));
    assert_eq!(f.enviados()[0].valor("prompt"), &Valor::Texto("x".into()));
}

#[test]
fn generar_con_error_de_ollama() {
    let _t = turno();
    let f = Falsa::new(&["completion"]);
    f.guiones.lock().unwrap().push_back((500, vec![]));
    let mut eventos = Vec::new();
    let p = PedidoGenerar { prompt: "x".into(), modelo: "m-error".into(), ..Default::default() };
    generar::generar(raiz(), &p, &Cancelar::default(), &mut |e| eventos.push(e));
    assert_eq!(eventos[0].valor("v"), &Valor::Texto("[Error Ollama: 500: fallo]".into()));
}

#[test]
fn chat_razonamiento_texto_confianza_y_stats() {
    let _t = turno();
    let f = Falsa::new(&["completion", "thinking"]);
    f.guion(vec![
        v(r#"{"message": {"thinking": "pienso"}}"#),
        v(r#"{"message": {"content": "Hola"}, "logprobs": [{"token": "Hola", "logprob": -0.1, "top_logprobs": [{"token": "Hola", "logprob": -0.1}]}]}"#),
        v(r#"{"message": {"content": ""}, "done": true, "done_reason": "length", "eval_count": 1, "eval_duration": 100000000, "prompt_eval_count": 1, "prompt_eval_duration": 10000000, "total_duration": 100000000, "load_duration": 0}"#),
    ]);
    let p = PedidoChat {
        mensajes: vec![usuario("hola"), v(r#"{"role": "assistant", "content": "Ho"}"#)],
        modelo: "m-chat".into(),
        think: Some(true),
        logprobs: 2,
        ..Default::default()
    };
    let e = chat(&p, None);
    assert_eq!(tipos(&e), ["pensando", "texto", "logprobs", "stats"]);
    assert_eq!(e[3].mapa("v").unwrap().valor("cortada"), &Valor::Bool(true));
    let enviado = &f.enviados()[0];
    let msgs = enviado.lista("messages").unwrap();
    assert_eq!(msgs.last().unwrap(), &v(r#"{"role": "assistant", "content": "Ho"}"#)); // continuar
    assert_eq!((enviado.valor("think"), enviado.valor("top_logprobs")), (&Valor::Bool(true), &Valor::Entero(2)));
}

#[test]
fn chat_bucle_de_herramientas() {
    let _t = turno();
    let f = Falsa::new(&["completion", "tools"]);
    f.guion(vec![v(r#"{"message": {"content": "", "tool_calls": [{"function": {"name": "sumar", "arguments": {"a": 2, "b": 3}}}]}}"#), v(FIN)])
        .guion(vec![v(r#"{"message": {"content": "Da 5."}}"#), v(FIN)]);
    let mut h = Sumar { ejecutadas: vec![] };
    let p = PedidoChat { mensajes: vec![usuario("2+3")], modelo: "m-herr".into(), ..Default::default() };
    let e = chat(&p, Some(&mut h));
    assert_eq!(tipos(&e), ["herramienta", "resultado", "texto", "stats"]);
    let segunda = f.enviados()[1].lista("messages").unwrap().to_vec();
    assert_eq!(segunda[segunda.len() - 1], v(r#"{"role": "tool", "tool_name": "sumar", "content": "5"}"#));
    assert!(matches!(&segunda[segunda.len() - 2], Valor::Mapa(m) if m.contiene("tool_calls")));
}

#[test]
fn chat_tope_de_tokens() {
    let _t = turno();
    let f = Falsa::new(&["completion", "thinking"]);
    let ok = || vec![v(r#"{"message": {"content": "ok"}, "done": true}"#)];
    f.guion(ok());
    chat(&PedidoChat { mensajes: vec![usuario("x")], modelo: "m-tope".into(), max_tokens: Some(4096), ..Default::default() }, None);
    assert_eq!(f.enviados()[0].mapa("options").unwrap().valor("num_predict"), &Valor::Entero(4096));
    // Con «Pensar» el razonamiento cuenta dentro del tope: supera al de la configuración
    std::fs::write(casa().join(".prig_ai_config.json"), format!("{{\"ollama_url\": \"{}\", \"num_predict\": 4096}}", f.url)).unwrap();
    for (think, max, esperado) in [(false, 4096, 4096), (true, 16384, 16384)] {
        f.guion(ok());
        chat(
            &PedidoChat { mensajes: vec![usuario("x")], modelo: "m-tope".into(), think: Some(think), max_tokens: Some(max), ..Default::default() },
            None,
        );
        let ultimo = f.enviados().last().cloned().unwrap();
        assert_eq!(ultimo.mapa("options").unwrap().valor("num_predict"), &Valor::Entero(esperado));
    }
}

#[test]
fn chat_consulta_repetida_no_se_repite_y_termina_respondiendo() {
    let _t = turno();
    let f = Falsa::new(&["completion", "tools"]);
    let llamada = || v(r#"{"message": {"content": "", "tool_calls": [{"function": {"name": "sumar", "arguments": {"a": 2, "b": 3}}}]}}"#);
    for _ in 0..3 {
        f.guion(vec![llamada(), v(FIN)]);
    }
    f.guion(vec![v(r#"{"message": {"content": "Da 5."}}"#), v(FIN)]);
    let mut h = Sumar { ejecutadas: vec![] };
    let e = chat(&PedidoChat { mensajes: vec![usuario("2+3")], modelo: "m-rep".into(), max_rondas: 9, ..Default::default() }, Some(&mut h));
    assert_eq!(h.ejecutadas.len(), 1); // las repetidas no se ejecutan
    let resultados: Vec<String> = e.iter().filter(|x| x.texto("t") == Some("resultado")).map(|x| x.valor("v").texto_py()).collect();
    assert_eq!(resultados[0], "5");
    assert!(resultados[1..].iter().all(|r| r.contains("Ya hiciste exactamente esta consulta")));
    let enviados = f.enviados();
    assert_eq!(enviados.last().unwrap().get("tools"), enviados[0].get("tools")); // el mismo prefijo
    let ultimo = enviados.last().unwrap().lista("messages").unwrap().last().cloned().unwrap();
    assert!(matches!(ultimo, Valor::Mapa(m) if m.valor("content").texto_py().contains("No hay más consultas")));
    let textos: Vec<String> = e.iter().filter(|x| x.texto("t") == Some("texto")).map(|x| x.valor("v").texto_py()).collect();
    assert_eq!(textos, ["Da 5."]);
}

#[test]
fn chat_la_ultima_ronda_responde_y_si_insiste_va_sin_herramientas() {
    let _t = turno();
    let f = Falsa::new(&["completion", "tools"]);
    f.guion(vec![v(r#"{"message": {"content": "", "tool_calls": [{"function": {"name": "sumar", "arguments": {"a": 1, "b": 1}}}]}}"#), v(FIN)])
        .guion(vec![v(r#"{"message": {"content": "", "tool_calls": [{"function": {"name": "sumar", "arguments": {"a": 5, "b": 5}}}]}}"#), v(FIN)])
        .guion(vec![v(r#"{"message": {"content": "Da 2."}}"#), v(FIN)]);
    let mut h = Sumar { ejecutadas: vec![] };
    let e = chat(&PedidoChat { mensajes: vec![usuario("1+1")], modelo: "m-ult".into(), max_rondas: 2, ..Default::default() }, Some(&mut h));
    assert_eq!(h.ejecutadas, vec![v(r#"{"a": 1, "b": 1}"#)]); // la de la última ronda, no
    let enviados = f.enviados();
    assert_eq!(enviados.len(), 3);
    assert!(enviados[1].contiene("tools"));
    assert!(!enviados[2].contiene("tools"));
    let ultimo1 = enviados[1].lista("messages").unwrap().last().cloned().unwrap();
    assert!(matches!(ultimo1, Valor::Mapa(m) if m.valor("content").texto_py().contains("No hay más consultas")));
    let textos: Vec<String> = e.iter().filter(|x| x.texto("t") == Some("texto")).map(|x| x.valor("v").texto_py()).collect();
    assert_eq!(textos, ["Da 2."]);
    assert!(!e.iter().any(|x| x.valor("v").texto_py().contains("Se alcanzó el máximo")));
}

#[test]
fn chat_corta_un_bucle_de_texto_y_pide_la_conclusion() {
    let _t = turno();
    let f = Falsa::new(&["completion", "tools"]);
    let parrafo = "Espera, creo que el error está en la línea 96. Cuando se cierra una sub-pieza intermedia se usa \
`nombres if primero else []`, pero `nombres` es la lista del tramo original, así que esto es correcto. ";
    let mut enbucle = vec![Valor::Mapa(Mapa::new().con("message", Mapa::new().con("content", "Reviso. ")))];
    for _ in 0..40 {
        enbucle.push(Valor::Mapa(Mapa::new().con("message", Mapa::new().con("content", parrafo))));
    }
    enbucle.push(v(r#"{"message": {}, "done": true, "done_reason": "length"}"#));
    f.guion(enbucle).guion(vec![v(r#"{"message": {"content": "Conclusión: la línea 97 pierde una línea."}}"#), v(FIN)]);
    let mut h = Sumar { ejecutadas: vec![] };
    let e = chat(
        &PedidoChat { mensajes: vec![usuario("¿Tiene algún error?")], modelo: "m-bucle".into(), max_rondas: 9, ..Default::default() },
        Some(&mut h),
    );
    let textos: String = e.iter().filter(|x| x.texto("t") == Some("texto")).map(|x| x.valor("v").texto_py()).collect();
    assert!(textos.matches("Espera, creo").count() < 10); // se cortó, no llegó a las 40
    assert!(textos.contains("Conclusión: la línea 97"));
    let enviados = f.enviados();
    let segunda = enviados[1].lista("messages").unwrap().to_vec();
    assert_eq!(segunda[segunda.len() - 1], Valor::Mapa(Mapa::new().con("role", "user").con("content", generar::SALIR_DEL_BUCLE)));
    let previo = match &segunda[segunda.len() - 2] {
        Valor::Mapa(m) => m.clone(),
        _ => panic!(),
    };
    assert_eq!(previo.valor("role"), &Valor::Texto("assistant".into()));
    assert!(previo.valor("content").texto_py().matches("Espera, creo").count() <= 2); // sin el bucle
    assert_eq!(enviados[1].get("tools"), enviados[0].get("tools"));
    assert_eq!(generar::corte_de_bucle(&format!("{parrafo}{parrafo}Fin."), 240, 3), None); // repetir una vez no es bucle
}

#[test]
fn herramientas_a_modelo_sin_capacidad() {
    let _t = turno();
    let f = Falsa::new(&["completion"]);
    f.guion(vec![v(r#"{"message": {"content": "ok"}, "done": true}"#)]);
    let mut h = Sumar { ejecutadas: vec![] };
    let e = chat(&PedidoChat { mensajes: vec![usuario("x")], modelo: "m-sin".into(), ..Default::default() }, Some(&mut h));
    assert_eq!(e[0].valor("t"), &Valor::Texto("aviso".into()));
    assert!(!f.enviados()[0].contiene("tools"));
}

#[test]
fn generar_con_pausas_devuelve_todo() {
    let _t = turno();
    let f = Falsa::new(&["completion"]);
    f.guion(vec![v(r#"{"message": {"content": "uno "}}"#), v(r#"{"message": {"content": "dos"}, "done": true}"#)]);
    let p = PedidoPausas { prompt: "x".into(), modelo: "m-pausas".into(), sistema: "Sé breve.".into(), ..Default::default() };
    let r = generar::generar_con_pausas(raiz(), &p, &Cancelar::default(), None).unwrap();
    assert_eq!(r, "uno dos");
    let msgs = f.enviados()[0].lista("messages").unwrap().to_vec();
    assert_eq!(msgs[0], v(r#"{"role": "system", "content": "Sé breve."}"#));
    f.guiones.lock().unwrap().push_back((500, vec![]));
    let e = generar::generar_con_pausas(raiz(), &p, &Cancelar::default(), None).unwrap_err();
    assert_eq!(e, "Error Ollama 500: fallo");
}

// =========================================================================== con el gobernador

/// Un gobernador que corta cuando se le dice (en cada control: sin esperar un segundo entre controles)
struct GobFalso {
    cortes: Mutex<VecDeque<Option<&'static str>>>,
    temps: Mutex<VecDeque<f64>>,
    enfriados: Mutex<Vec<String>>,
    tramos: Mutex<Vec<Option<String>>>,
}

impl GobFalso {
    fn new(cortes: &[Option<&'static str>], temps: &[f64]) -> GobFalso {
        GobFalso {
            cortes: Mutex::new(cortes.iter().copied().collect()),
            temps: Mutex::new(temps.iter().copied().collect()),
            enfriados: Mutex::default(),
            tramos: Mutex::default(),
        }
    }
}

impl generar::Gobernar for GobFalso {
    fn empezar(&self) -> Option<prig_recursos::termico::Tramo> {
        Some(prig_recursos::termico::Tramo::new(Valor::Real(40.0), 0.0))
    }

    fn debe_cortar(&self, _t: &mut Option<prig_recursos::termico::Tramo>) -> Option<&'static str> {
        self.cortes.lock().unwrap().pop_front().flatten()
    }

    fn terminar(&self, _t: &Option<prig_recursos::termico::Tramo>, motivo: Option<&str>) {
        self.tramos.lock().unwrap().push(motivo.map(String::from));
    }

    fn enfriar(&self, motivo: &str, _t: &mut Option<prig_recursos::termico::Tramo>, _a: Option<&mut dyn FnMut(Mapa)>) -> f64 {
        self.enfriados.lock().unwrap().push(motivo.into());
        12.0
    }

    fn temperaturas(&self, _max_edad: f64) -> Option<(Valor, f64, f64)> {
        let t = self.temps.lock().unwrap().pop_front().unwrap_or(40.0);
        Some((Valor::Real(t), 60.0, 50.0))
    }

    fn intervalo(&self) -> f64 {
        0.0
    }
}

fn trozos(partes: &[(&str, bool)]) -> Vec<Valor> {
    partes.iter().map(|(t, fin)| Valor::Mapa(Mapa::new().con("message", Mapa::new().con("content", *t)).con("done", *fin))).collect()
}

#[test]
fn con_pausas_corta_enfria_y_continua_sin_perder_lo_escrito() {
    let _t = turno();
    let f = Falsa::new(&["completion"]);
    std::fs::write(casa().join(".prig_ai_config.json"), format!("{{\"ollama_url\": \"{}\", \"num_predict\": 100}}", f.url)).unwrap();
    f.guion(trozos(&[("Hola", false), (" mun", false), ("do", false), (" cruel", false)])).guion(trozos(&[("do", false), (".", true)]));
    let g = GobFalso::new(&[None, Some("limite")], &[]); // corta en el segundo control, tras « mun»
    let p = PedidoPausas { prompt: "di hola".into(), modelo: "m-corta".into(), sistema: "s".into(), gobernador: true, ..Default::default() };
    let texto = generar::generar_con_pausas_con(raiz(), &p, &Cancelar::default(), None, &g).unwrap();
    assert_eq!(texto, "Hola mundo.");
    assert_eq!(*g.enfriados.lock().unwrap(), ["limite"]);
    let segunda = f.enviados()[1].clone();
    let msgs = segunda.lista("messages").unwrap().to_vec();
    // Lo generado va como inicio de la respuesta del asistente
    assert_eq!(msgs.last().unwrap(), &v(r#"{"role": "assistant", "content": "Hola mun"}"#));
    assert_eq!(msgs[0], v(r#"{"role": "system", "content": "s"}"#));
    assert_eq!(segunda.mapa("options").unwrap().valor("num_predict"), &Valor::Entero(98));
    // Cada tramo se cierra para aprender: el cortado y el que terminó
    assert_eq!(*g.tramos.lock().unwrap(), [Some("limite".to_string()), None]);
}

#[test]
fn chat_corta_avisa_y_continua_la_misma_respuesta() {
    let _t = turno();
    let f = Falsa::new(&["completion"]);
    f.guion(trozos(&[("Hola", false), (" mun", false), ("do", false)]));
    let mut fin = trozos(&[("do", false), (".", true)]);
    if let Some(Valor::Mapa(m)) = fin.last_mut() {
        m.poner("eval_count", 3);
        m.poner("eval_duration", 1_000_000_000i64);
    }
    f.guion(fin);
    let g = GobFalso::new(&[None, Some("limite")], &[40.0, 62.0, 62.0]);
    let p = PedidoChat { mensajes: vec![usuario("hola")], modelo: "m-chat-corta".into(), gobernador: true, ..Default::default() };
    let mut eventos = Vec::new();
    generar::chat_eventos_con(raiz(), &p, None, &Cancelar::default(), &mut |e| eventos.push(e), &g);
    let texto: String = eventos.iter().filter(|e| e.texto("t") == Some("texto")).map(|e| e.valor("v").texto_py()).collect();
    assert_eq!(texto, "Hola mundo.");
    let termicos: Vec<&Mapa> = eventos.iter().filter(|e| e.texto("t") == Some("termico")).collect();
    assert_eq!(termicos.iter().map(|e| e.valor("pausa").clone()).collect::<Vec<_>>(), [Valor::Bool(true), Valor::Bool(false)]);
    assert!(termicos[0].valor("v").texto_py().contains("pausa para enfriar"));
    assert_eq!(termicos[1].valor("v").texto_py(), "GPU a 62 °C tras 12 s: se reanuda.");
    assert_eq!(g.enfriados.lock().unwrap().len(), 1);
    let msgs = f.enviados()[1].lista("messages").unwrap().to_vec();
    assert_eq!(msgs.last().unwrap(), &v(r#"{"role": "assistant", "content": "Hola mun"}"#));
    assert!(eventos.iter().any(|e| e.texto("t") == Some("stats")));
}

#[test]
fn generar_sigue_por_chat_tras_cortar() {
    let _t = turno();
    let f = Falsa::new(&["completion"]);
    f.guion(vec![v(r#"{"response": "Hola", "done": false}"#), v(r#"{"response": " mun", "done": false}"#), v(r#"{"response": "do", "done": false}"#)])
        .guion(trozos(&[("do", false), (".", true)]));
    let g = GobFalso::new(&[None, Some("limite")], &[]);
    let p = PedidoGenerar { prompt: "di hola".into(), modelo: "m-gen-corta".into(), sistema: "s".into(), gobernador: true, ..Default::default() };
    let mut eventos = Vec::new();
    generar::generar_con(raiz(), &p, &Cancelar::default(), &mut |e| eventos.push(e), &g);
    let texto: String = eventos.iter().filter(|e| e.texto("t") == Some("texto")).map(|e| e.valor("v").texto_py()).collect();
    assert_eq!(texto, "Hola mundo.");
    let enviados = f.enviados.lock().unwrap().clone();
    assert_eq!(enviados[0].0, "/api/generate");
    assert_eq!(enviados[1].0, "/api/chat"); // se sigue por /api/chat con lo escrito como inicio del asistente
    let msgs = enviados[1].1.lista("messages").unwrap().to_vec();
    assert_eq!(msgs, vec![v(r#"{"role": "system", "content": "s"}"#), v(r#"{"role": "user", "content": "di hola"}"#), v(r#"{"role": "assistant", "content": "Hola mun"}"#)]);
    assert!(!enviados[1].1.contiene("prompt") && !enviados[1].1.contiene("system"));
}

#[test]
fn el_modo_suave_no_corta_a_mitad_del_razonamiento() {
    let _t = turno();
    let f = Falsa::new(&["completion", "thinking"]);
    f.guion(vec![v(r#"{"message": {"thinking": "a"}}"#), v(r#"{"message": {"thinking": "b"}}"#), v(r#"{"message": {"content": "ok"}, "done": true}"#)]);
    let g = GobFalso::new(&[Some("ritmo"), Some("ritmo")], &[]);
    let p = PedidoChat { mensajes: vec![usuario("x")], modelo: "m-suave".into(), gobernador: true, ..Default::default() };
    let mut eventos = Vec::new();
    generar::chat_eventos_con(raiz(), &p, None, &Cancelar::default(), &mut |e| eventos.push(e), &g);
    assert_eq!(f.enviados().len(), 1); // una sola petición: el ritmo esperó a que respondiera
    assert!(g.enfriados.lock().unwrap().is_empty());
}

#[test]
fn detener_corta_y_avisa() {
    let _t = turno();
    let f = Falsa::new(&["completion"]);
    f.guion(trozos(&[("uno", false), ("dos", false), ("tres", true)]));
    let c = Cancelar::default();
    c.poner();
    let p = PedidoChat { mensajes: vec![usuario("x")], modelo: "m-detener".into(), ..Default::default() };
    let mut eventos = Vec::new();
    generar::chat_eventos(raiz(), &p, None, &c, &mut |e| eventos.push(e));
    assert_eq!(tipos(&eventos), ["texto", "aviso"]);
    assert_eq!(eventos[1].valor("v"), &Valor::Texto("Detenido.".into()));
}

#[test]
fn generar_sobrevive_a_una_falta_de_memoria() {
    let _t = turno();
    let f = Falsa::new(&["completion"]);
    std::env::set_var("PRIG_OLLAMA_URL", &f.url); // la ficha del modelo (sin /api/tags: la del catálogo)
    f.guiones.lock().unwrap().push_back((500, vec![v(r#"{"error": "llama runner process has terminated: cudaMalloc failed: out of memory"}"#)]));
    f.guion(vec![v(r#"{"response": "hola", "done": true}"#)]);
    let mut eventos = Vec::new();
    let p = PedidoGenerar { prompt: "hola".into(), modelo: "qwen2.5-coder:7b".into(), ..Default::default() };
    generar::generar(raiz(), &p, &Cancelar::default(), &mut |e| eventos.push(e));
    std::env::remove_var("PRIG_OLLAMA_URL");
    let texto: String = eventos.iter().filter(|e| e.texto("t") == Some("texto")).map(|e| e.valor("v").texto_py()).collect();
    assert_eq!(texto, "hola");
    let enviados = f.enviados();
    assert_eq!(enviados[0].mapa("options").unwrap().valor("num_ctx"), &Valor::Entero(4096));
    assert_eq!(enviados[1].mapa("options").unwrap().valor("num_ctx"), &Valor::Entero(2048));
}

#[test]
fn cancelar_corta_la_conexion_con_ollama() {
    let _t = turno();
    // Una Ollama lenta que cuenta los trozos que llegó a enviar
    let l = TcpListener::bind("127.0.0.1:0").unwrap();
    let url = format!("http://{}", l.local_addr().unwrap());
    let enviados = Arc::new(Mutex::new(0usize));
    let e = enviados.clone();
    std::thread::spawn(move || {
        for s in l.incoming().flatten() {
            let mut r = BufReader::new(s.try_clone().unwrap());
            let mut largo = 0usize;
            loop {
                let mut h = String::new();
                if r.read_line(&mut h).is_err() || h.trim().is_empty() {
                    break;
                }
                if let Some(v) = h.to_lowercase().strip_prefix("content-length:") {
                    largo = v.trim().parse().unwrap_or(0);
                }
            }
            let mut cuerpo = vec![0u8; largo];
            let _ = r.read_exact(&mut cuerpo);
            let mut s = s;
            if write!(s, "HTTP/1.1 200 OK\r\nContent-Type: application/x-ndjson\r\nTransfer-Encoding: chunked\r\n\r\n").is_err() {
                continue;
            }
            for i in 0..400 {
                let linea = format!("{{\"response\": \"t{i} \", \"done\": false}}\n");
                if write!(s, "{:x}\r\n{linea}\r\n", linea.len()).and_then(|_| s.flush()).is_err() {
                    break;
                }
                *e.lock().unwrap() += 1;
                std::thread::sleep(std::time::Duration::from_millis(20));
            }
        }
    });
    let c = casa();
    std::fs::write(c.join(".prig_ai_config.json"), format!("{{\"ollama_url\": \"{url}\"}}")).unwrap();
    let cancelar = Arc::new(Cancelar::default());
    let (cc, inicio) = (cancelar.clone(), std::time::Instant::now());
    let mut vistos = 0;
    let p = PedidoGenerar { prompt: "x".into(), modelo: "m-lenta".into(), ..Default::default() };
    generar::generar(raiz(), &p, &cancelar, &mut |_| {
        vistos += 1;
        if vistos == 3 {
            cc.poner(); // el usuario cerró la sección
        }
    });
    assert!(inicio.elapsed().as_secs_f64() < 3.0, "siguió leyendo para nadie");
    std::thread::sleep(std::time::Duration::from_millis(600));
    let total = *enviados.lock().unwrap();
    std::thread::sleep(std::time::Duration::from_millis(400));
    assert_eq!(*enviados.lock().unwrap(), total, "Ollama siguió generando tras cortar");
    assert!(total < 100, "{total} de 400");
}

#[test]
fn con_el_gobernador_de_verdad_no_se_cuelga() {
    let _t = turno();
    let f = Falsa::new(&["completion"]);
    f.guion(vec![v(r#"{"message": {"content": "ok"}, "done": true}"#)]);
    let (tx, rx) = std::sync::mpsc::channel();
    std::thread::spawn(move || {
        let p = PedidoChat { mensajes: vec![usuario("x")], modelo: "m-real".into(), gobernador: true, ..Default::default() };
        let mut e = Vec::new();
        generar::chat_eventos(raiz(), &p, None, &Cancelar::default(), &mut |x| e.push(x));
        let _ = tx.send(e);
    });
    let e = rx.recv_timeout(std::time::Duration::from_secs(20)).expect("se colgó con el gobernador de verdad");
    assert!(e.iter().any(|x| x.texto("t") == Some("texto")));
}
