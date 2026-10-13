//! Números como Python 3.12: `sum()` de floats con la suma compensada de Neumaier (desde 3.12), `round()` al
//! par sobre el valor decimal exacto, `repr(float)` con el dígito más corto que vuelve al mismo valor y los
//! formatos `{:.Nf}` / `{:.N%}` exactos. Las puntuaciones y los pesos de la partición dependen de estos bits.

use num_bigint::{BigInt, Sign};
use num_traits::{One, Signed, Zero};

/// `sum(xs)` de floats con el comienzo entero 0 de Python: el primero entra sumado a 0 (−0.0 queda 0.0) y
/// el resto con la compensación de Neumaier.
pub fn suma(xs: impl IntoIterator<Item = f64>) -> f64 {
    let mut iter = xs.into_iter();
    let mut f = match iter.next() {
        None => return 0.0,
        Some(x) => 0.0 + x,
    };
    let mut c = 0.0f64;
    for x in iter {
        let t = f + x;
        if f.abs() >= x.abs() {
            c += (f - t) + x;
        } else {
            c += (x - t) + f;
        }
        f = t;
    }
    if c != 0.0 && c.is_finite() {
        f += c;
    }
    f
}

/// El valor exacto de un f64 como fracción num / 2^k (k ≥ 0) con signo.
fn exacto(x: f64) -> (BigInt, u32) {
    let bits = x.to_bits();
    let signo = if bits >> 63 == 1 { -1 } else { 1 };
    let exponente = ((bits >> 52) & 0x7ff) as i64;
    let mantisa = bits & ((1u64 << 52) - 1);
    let (m, e) = if exponente == 0 { (mantisa, -1074i64) } else { (mantisa | (1u64 << 52), exponente - 1075) };
    let mut num = BigInt::from(m) * signo;
    if e >= 0 {
        num <<= e as usize;
        (num, 0)
    } else {
        (num, (-e) as u32)
    }
}

/// round(num / den) al par, con den > 0.
fn redondear_al_par(num: &BigInt, den: &BigInt) -> BigInt {
    let negativo = num.is_negative();
    let n = num.abs();
    let q = &n / den;
    let r = &n - &q * den;
    let doble = &r * 2;
    let q = if doble > *den || (doble == *den && (&q % 2u32) == BigInt::one()) { q + 1 } else { q };
    if negativo {
        -q
    } else {
        q
    }
}

/// x · 10^n redondeado al par al entero (n ≥ 0), exacto.
fn escalado(x: f64, n: u32) -> BigInt {
    let (num, k) = exacto(x);
    let num = num * BigInt::from(10u32).pow(n);
    let den = BigInt::one() << (k as usize);
    redondear_al_par(&num, &den)
}

/// `round(x, n)` de Python para floats (n puede ser negativo).
pub fn round(x: f64, n: i32) -> f64 {
    if !x.is_finite() || x == 0.0 {
        return x;
    }
    if n > 323 {
        return x;
    }
    if n < -308 {
        return 0.0 * x;
    }
    let texto = if n >= 0 {
        let q = escalado(x, n as u32);
        format!("{q}e-{n}")
    } else {
        // x / 10^-n redondeado al par, por 10^-n
        let (num, k) = exacto(x);
        let den = (BigInt::one() << (k as usize)) * BigInt::from(10u32).pow((-n) as u32);
        let q = redondear_al_par(&num, &den);
        format!("{q}e{}", -n)
    };
    let r: f64 = texto.parse().unwrap_or(x);
    if r == 0.0 {
        0.0f64.copysign(x)
    } else {
        r
    }
}

/// `round(x)` sin dígitos: un entero, al par.
pub fn round_entero(x: f64) -> i64 {
    x.round_ties_even() as i64
}

/// `format(x, ".Nf")` exacto (redondeo al par sobre el valor binario exacto, como Python).
pub fn fijo(x: f64, n: u32) -> String {
    if x.is_nan() {
        return "nan".to_string();
    }
    if x.is_infinite() {
        return if x > 0.0 { "inf".to_string() } else { "-inf".to_string() };
    }
    let q = escalado(x, n);
    let negativo = x.is_sign_negative();
    let digitos = q.abs().to_string();
    let n = n as usize;
    let cuerpo = if n == 0 {
        digitos
    } else {
        let relleno = if digitos.len() <= n { "0".repeat(n + 1 - digitos.len()) } else { String::new() };
        let d = format!("{relleno}{digitos}");
        let corte = d.len() - n;
        format!("{}.{}", &d[..corte], &d[corte..])
    };
    if negativo && (q.sign() != Sign::NoSign || x.is_sign_negative()) {
        format!("-{cuerpo}")
    } else {
        cuerpo
    }
}

/// `format(x, ".N%")`: x·100 en doble precisión y luego `.Nf`.
pub fn porciento(x: f64, n: u32) -> String {
    format!("{}%", fijo(x * 100.0, n))
}

/// Dígitos más cortos y posición del punto: x = 0.d1d2… × 10^punto.
fn corto(x: f64) -> (String, i32) {
    let e = format!("{:e}", x.abs());
    let (mantisa, exp) = e.split_once('e').unwrap();
    let exp: i32 = exp.parse().unwrap();
    let digitos: String = mantisa.chars().filter(|c| *c != '.').collect();
    let digitos = digitos.trim_end_matches('0');
    let digitos = if digitos.is_empty() { "0".to_string() } else { digitos.to_string() };
    (digitos, exp + 1)
}

/// `repr(float)`.
pub fn repr_float(x: f64) -> String {
    if x.is_nan() {
        return "nan".to_string();
    }
    if x.is_infinite() {
        return if x > 0.0 { "inf".to_string() } else { "-inf".to_string() };
    }
    let signo = if x.is_sign_negative() { "-" } else { "" };
    if x == 0.0 {
        return format!("{signo}0.0");
    }
    let (d, punto) = corto(x);
    if punto <= -4 || punto > 16 {
        let exp = punto - 1;
        let mantisa = if d.len() > 1 { format!("{}.{}", &d[..1], &d[1..]) } else { d.clone() };
        let signo_exp = if exp < 0 { "-" } else { "+" };
        return format!("{signo}{mantisa}e{signo_exp}{:02}", exp.abs());
    }
    if punto <= 0 {
        return format!("{signo}0.{}{}", "0".repeat((-punto) as usize), d);
    }
    let punto = punto as usize;
    if d.len() <= punto {
        format!("{signo}{}{}.0", d, "0".repeat(punto - d.len()))
    } else {
        format!("{signo}{}.{}", &d[..punto], &d[punto..])
    }
}

/// `repr(complex(0, im))` de un literal imaginario: sin «.0».
pub fn repr_imaginario(im: f64) -> String {
    let r = repr_float(im);
    let r = r.strip_suffix(".0").map(|s| s.to_string()).unwrap_or(r);
    format!("{r}j")
}

/// Un entero de Python escrito en decimal desde su literal (0x…, 0o…, 0b…, con «_»).
pub fn entero_decimal(literal: &str) -> String {
    let limpio: String = literal.chars().filter(|c| *c != '_').collect();
    let minus = limpio.to_ascii_lowercase();
    let (base, cifras) = if let Some(r) = minus.strip_prefix("0x") {
        (16, r.to_string())
    } else if let Some(r) = minus.strip_prefix("0o") {
        (8, r.to_string())
    } else if let Some(r) = minus.strip_prefix("0b") {
        (2, r.to_string())
    } else {
        (10, minus.clone())
    };
    match BigInt::parse_bytes(cifras.as_bytes(), base) {
        Some(n) => n.to_string(),
        None => {
            if cifras.chars().all(|c| c == '0') {
                "0".to_string()
            } else {
                limpio
            }
        }
    }
}

/// Para comparar con Python sin redondeos propios: `str(BigInt)` de un i64.
pub fn es_cero(x: &BigInt) -> bool {
    x.is_zero()
}

#[cfg(test)]
mod pruebas {
    use super::*;

    #[test]
    fn suma_como_312() {
        assert_eq!(suma(vec![1e16, 1.0, -1e16]), 1.0);
        assert_eq!(suma(vec![0.1; 10]), 1.0);
    }

    #[test]
    fn round_como_python() {
        assert_eq!(round(0.125, 2), 0.12);
        assert_eq!(round(0.375, 2), 0.38);
        assert_eq!(round(2.675, 2), 2.67);
        assert_eq!(round_entero(2.5), 2);
        assert_eq!(round_entero(1.5), 2);
    }

    #[test]
    fn repr_como_python() {
        assert_eq!(repr_float(1e16), "1e+16");
        assert_eq!(repr_float(1e-5), "1e-05");
        assert_eq!(repr_float(0.1 + 0.2), "0.30000000000000004");
        assert_eq!(repr_float(1e22), "1e+22");
        assert_eq!(repr_float(123456789012345678.0), "1.2345678901234568e+17");
        assert_eq!(repr_float(-0.0), "-0.0");
        assert_eq!(repr_float(1e15), "1000000000000000.0");
        assert_eq!(repr_float(0.0001), "0.0001");
        assert_eq!(repr_float(2.5), "2.5");
        assert_eq!(entero_decimal("0x10"), "16");
        assert_eq!(entero_decimal("1_000"), "1000");
    }

    #[test]
    fn formatos() {
        assert_eq!(fijo(0.5, 0), "0");
        assert_eq!(fijo(1.5, 0), "2");
        assert_eq!(fijo(0.125, 2), "0.12");
        assert_eq!(porciento(0.355, 0), "36%");
    }
}
