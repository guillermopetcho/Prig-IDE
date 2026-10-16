//! Diferencial del `csv.Sniffer` y el lector de CSV contra Python: lee una lista JSON de textos por la entrada y
//! escribe, por línea, `[separador, filas]` (o `[separador, "error"]`)
use prig_integrations::kaggle_datos::{adivinar_separador, LectorCsv};
use prig_plataforma::valor::Valor;
use std::io::Read;

fn main() {
    let mut e = String::new();
    std::io::stdin().read_to_string(&mut e).unwrap();
    let Valor::Lista(casos) = prig_plataforma::json::leer(&e).unwrap() else { panic!() };
    for c in casos {
        let t = c.texto_py();
        let sep = adivinar_separador(&t.chars().take(20000).collect::<String>());
        let mut l = LectorCsv::new(&t, sep);
        let mut filas = Vec::new();
        let mut error = false;
        while let Some(f) = l.fila() {
            match f {
                Ok(f) => filas.push(Valor::Lista(f.into_iter().map(Valor::Texto).collect())),
                Err(_) => {
                    error = true;
                    break;
                }
            }
        }
        let r = if error { Valor::Texto("error".into()) } else { Valor::Lista(filas) };
        println!("{}", prig_plataforma::json::escribir_compacto(&Valor::Lista(vec![Valor::Texto(sep.to_string()), r])));
    }
}
