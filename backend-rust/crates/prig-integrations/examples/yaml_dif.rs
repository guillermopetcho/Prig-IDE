//! Prueba diferencial del YAML de Prig Hub contra PyYAML: `yaml_dif cargar|volcar ANCHO < entrada`
use prig_integrations::hub::yaml;
use std::io::Read;

fn main() {
    let modo = std::env::args().nth(1).unwrap_or_default();
    let ancho: usize = std::env::args().nth(2).and_then(|x| x.parse().ok()).unwrap_or(80);
    let mut texto = String::new();
    std::io::stdin().read_to_string(&mut texto).unwrap();
    for trozo in texto.split("\u{1e}") {
        if modo == "cargar" {
            match yaml::cargar(trozo) {
                Ok(v) => println!("{}", prig_plataforma::json::escribir_compacto(&v)),
                Err(e) => println!("ERROR {:?}", e.linea),
            }
        } else {
            let v = prig_plataforma::json::leer(trozo).unwrap();
            print!("{}\u{1e}", yaml::volcar(&v, ancho));
        }
    }
}
