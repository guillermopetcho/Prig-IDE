/**
 * Apariencia: transparencia y desenfoque de la interfaz.
 *
 * Todo se controla con variables CSS, así que un cambio se ve al instante en toda la
 * aplicación sin repintar nada a mano. Se guarda en el navegador porque es una
 * preferencia visual de este equipo, no del proyecto.
 */
class AparienciaManager {
    constructor() {
        this.def = { opacidad: 0.92, desenfoque: 10, acento: '#89b4fa', densidad: 'normal' };
        this.estado = Object.assign({}, this.def, this._cargar());
    }

    _cargar() {
        try { return JSON.parse(localStorage.getItem('prig_apariencia') || '{}'); }
        catch (e) { return {}; }
    }

    _guardar() {
        try { localStorage.setItem('prig_apariencia', JSON.stringify(this.estado)); }
        catch (e) { /* almacenamiento bloqueado: se aplica igual en esta sesión */ }
    }

    aplicar() {
        const r = document.documentElement.style;
        r.setProperty('--superficie-alfa', String(this.estado.opacidad));
        r.setProperty('--desenfoque', `${this.estado.desenfoque}px`);
        r.setProperty('--acento-usuario', this.estado.acento);
        document.body.dataset.densidad = this.estado.densidad;
        // Con mucha transparencia el texto pierde contraste: se compensa con sombra
        document.body.classList.toggle('alta-transparencia', this.estado.opacidad < 0.75);
    }

    set(clave, valor) {
        this.estado[clave] = valor;
        this._guardar();
        this.aplicar();
    }

    ajustarOpacidad(delta) {
        const v = Math.max(0.35, Math.min(1, +(this.estado.opacidad + delta).toFixed(2)));
        this.set('opacidad', v);
        if (window.layoutMgr) {
            window.layoutMgr.mensajeEstado(`Opacidad de la interfaz: ${Math.round(v * 100)}%`, 1500);
        }
        const rango = document.getElementById('ap-opacidad');
        if (rango) rango.value = String(v);
        const etiqueta = document.getElementById('ap-opacidad-valor');
        if (etiqueta) etiqueta.textContent = `${Math.round(v * 100)}%`;
    }

    restablecer() {
        this.estado = Object.assign({}, this.def);
        this._guardar();
        this.aplicar();
    }
}

window.aparienciaMgr = new AparienciaManager();
// Se aplica antes del primer pintado para que no haya un parpadeo con los valores de fábrica
window.aparienciaMgr.aplicar();
