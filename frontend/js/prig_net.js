/**
 * Control de errores compartido para las llamadas a la API.
 *
 * Poco más de la mitad de los fetch comprobaba res.ok; el resto interpretaba un 400
 * o un 500 como respuesta válida y seguía adelante con datos vacíos. Ese patrón es
 * el que hacía que guardar un archivo fallara sin que nadie se enterara.
 *
 * prigJson(res) lanza un Error con el mensaje REAL del backend (el campo `detail` de
 * FastAPI) para que el try/catch que ya rodea cada llamada pueda mostrarlo.
 */
(function () {
    async function detalleDeError(res) {
        try {
            const data = await res.clone().json();
            return data.detail || data.error || data.message || `HTTP ${res.status}`;
        } catch (e) {
            try {
                const texto = (await res.text()).trim();
                if (texto) return texto.slice(0, 300);
            } catch (e2) { /* cuerpo ilegible */ }
            return `HTTP ${res.status} ${res.statusText || ''}`.trim();
        }
    }

    /** Motivo legible de un fallo, para respuestas en flujo que no devuelven JSON */
    window.prigErrorDetail = detalleDeError;

    /** Devuelve el JSON de la respuesta, o lanza con el motivo del backend */
    window.prigJson = async function (res) {
        if (!res || !res.ok) {
            const motivo = res ? await detalleDeError(res) : 'Sin respuesta del servidor';
            const err = new Error(motivo);
            err.status = res ? res.status : 0;
            throw err;
        }
        return res.json();
    };

    /** fetch + comprobación + JSON en un solo paso */
    window.prigFetchJson = async function (url, options) {
        options = options ? Object.assign({}, options) : {};
        if (options.body && typeof options.body === 'string') {
            options.headers = Object.assign({ 'Content-Type': 'application/json' }, options.headers || {});
        }
        return window.prigJson(await fetch(url, options));
    };
})();
