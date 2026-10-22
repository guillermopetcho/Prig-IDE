//! El contexto del tutor sobre la base de `PRIG_KB_RUTA` (para comparar con Python). A mano:
//! `PRIG_KB_RUTA=... PRIG_KB_PREGUNTAS=... cargo test -p prig-biblioteca --test kb_carpeta -- --ignored`

use prig_biblioteca::base_kb::BaseKb;
use prig_biblioteca::contexto_kb::{Compilador, Ensamblador};
use prig_plataforma::valor::{Mapa, Valor};

fn linea(m: Mapa) {
    println!("{}", prig_plataforma::json::escribir_linea(&Valor::Mapa(m)));
}

#[test]
#[ignore]
fn contexto_de_preguntas() {
    let (Ok(ruta), Ok(qs)) = (std::env::var("PRIG_KB_RUTA"), std::env::var("PRIG_KB_PREGUNTAS")) else { return };
    let kb = BaseKb::new(&ruta).unwrap();
    let sin = |_: &[String]| -> Result<Vec<Vec<f64>>, String> { Err("sin embebedor".into()) };
    let e = Ensamblador::new(&kb, &sin);
    for q in qs.lines() {
        linea(e.ensamblar(q, 1200, None, "intermedio", true).unwrap());
        linea(e.ensamblar(q, 1200, None, "intermedio", false).unwrap());
        linea(e.prompt_tutor(q, 2600, Some("math"), "principiante").unwrap());
        linea(e.ensamblar(q, 300, Some("deep_learning"), "avanzado", true).unwrap());
        linea(Mapa::new().con("r", Valor::Lista(kb.buscar(q, 20, &[], &[], None).unwrap().into_iter().map(Valor::Mapa).collect())));
        linea(Mapa::new().con("c", kb.resolver(q).unwrap().map(Valor::Mapa).unwrap_or(Valor::Nulo)));
    }
    linea(Compilador { kb: &kb }.precompilar().unwrap());
    linea(Mapa::new().con("p", Valor::Lista(kb.puentes(50).unwrap().into_iter().map(Valor::Mapa).collect())));
}

/// Importa los paquetes de `PRIG_KB_PACKS` en la base de `PRIG_KB_RUTA`: importar, unificar, dosieres e integridad
#[test]
#[ignore]
fn importar_paquetes() {
    let (Ok(ruta), Ok(packs)) = (std::env::var("PRIG_KB_RUTA"), std::env::var("PRIG_KB_PACKS")) else { return };
    use prig_biblioteca::paquetes as p;
    let kb = BaseKb::new(&ruta).unwrap();
    linea(p::importar_carpeta(&kb, &packs).unwrap());
    linea(p::unificar(&kb).unwrap());
    linea(p::construir_dosieres(&kb).unwrap());
    linea(p::verificar_integridad(&kb).unwrap());
    for f in ["bk_roto.prigpack", "bk_math.prigpack"] {
        match p::verificar(&format!("{packs}/{f}")) {
            Ok(m) => linea(m),
            Err(e) => linea(Mapa::new().con("error", e.texto())),
        }
    }
    linea(p::importar(&kb, &format!("{packs}/bk_math.prigpack"), false).unwrap());
    linea(p::unificar(&kb).unwrap());
}
