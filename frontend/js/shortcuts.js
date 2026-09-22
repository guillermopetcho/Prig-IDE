/**
 * Atajos de teclado reasignables.
 *
 * Los enlaces por defecto viven en el registro de comandos; aquí solo se guardan las
 * DIFERENCIAS que elija el usuario, para que al cambiar un atajo por defecto en una
 * versión futura no queden congelados los antiguos.
 */
class ShortcutManager {
    constructor() {
        this.CLAVE = 'prig_atajos';
        this.personalizados = this._cargar();
        this.pendienteCadena = null;   // para atajos de dos pulsaciones (Ctrl+K Ctrl+S)
        this.capturando = null;
    }

    _cargar() {
        try {
            const s = (typeof window !== 'undefined' && window.localStorage) ? window.localStorage : (typeof localStorage !== 'undefined' ? localStorage : null);
            return s ? JSON.parse(s.getItem(this.CLAVE) || '{}') : {};
        } catch (e) { return {}; }
    }

    _guardar() {
        try {
            const s = (typeof window !== 'undefined' && window.localStorage) ? window.localStorage : (typeof localStorage !== 'undefined' ? localStorage : null);
            if (s) s.setItem(this.CLAVE, JSON.stringify(this.personalizados));
        } catch (e) { console.error('No se pudieron guardar los atajos:', e); }
    }

    /** Atajo vigente de un comando: el del usuario si lo cambió, si no el de fábrica */
    accel(id) {
        if (Object.prototype.hasOwnProperty.call(this.personalizados, id)) {
            return this.personalizados[id];
        }
        const c = window.PrigCommands.get(id);
        return c ? (c.accel || '') : '';
    }

    asignar(id, accel, estricto = false) {
        if (!accel) {
            this.personalizados[id] = '';
            this._guardar();
            return { ok: true };
        }
        const conflicto = this.buscarConflicto(accel, id);
        if (conflicto && estricto) {
            return { ok: false, conflicto };
        }
        this.personalizados[id] = accel;
        this._guardar();
        return { ok: true, conflicto };
    }

    eliminar(id) {
        this.personalizados[id] = '';
        this._guardar();
    }

    esPersonalizado(id) {
        return Object.prototype.hasOwnProperty.call(this.personalizados, id);
    }

    restablecer(id) {
        delete this.personalizados[id];
        this._guardar();
    }

    restablecerTodos() {
        this.personalizados = {};
        this._guardar();
    }

    buscarConflicto(accel, exceptoId) {
        if (!accel) return null;
        const normal = this.normalizar(accel);
        return window.PrigCommands.todos().find(
            c => c.id !== exceptoId && this.normalizar(this.accel(c.id)) === normal
        ) || null;
    }

    /** "ctrl+shift+p" a partir de cualquier forma escrita */
    normalizar(accel) {
        if (!accel) return '';
        return accel.split(' ')
            .map(parte => parte.toLowerCase().split('+').map(t => t.trim()).filter(Boolean).sort().join('+'))
            .join(' ');
    }

    /** Descripción del evento de teclado en el mismo formato */
    desdeEvento(e) {
        const partes = [];
        if (e.ctrlKey || e.metaKey) partes.push('ctrl');
        if (e.altKey) partes.push('alt');
        if (e.shiftKey) partes.push('shift');

        let tecla = e.key;
        if (['Control', 'Alt', 'Shift', 'Meta', 'AltGraph', 'Dead'].includes(tecla)) return null;
        const mapa = {
            ' ': 'space', 'ArrowUp': 'up', 'ArrowDown': 'down', 'ArrowLeft': 'left', 'ArrowRight': 'right',
            'Escape': 'escape', 'Enter': 'enter', 'PageUp': 'pageup', 'PageDown': 'pagedown',
            'Backspace': 'backspace', 'Delete': 'delete', 'Tab': 'tab', 'Home': 'home', 'End': 'end',
            // "+" no puede ir dentro de un atajo (es el separador): se trata como "="
            '+': '=',
        };
        // Con Alt pulsado, algunos sistemas devuelven un carácter especial en e.key
        // (Alt+Z → "Ω" en macOS): se usa la tecla física para letras y números.
        if (e.altKey && /^Key[A-Z]$/.test(e.code || '')) tecla = e.code.slice(3);
        else if (e.altKey && /^Digit[0-9]$/.test(e.code || '')) tecla = e.code.slice(5);
        tecla = mapa[tecla] || tecla.toLowerCase();
        // Símbolos que en cada distribución salen con o sin Mayús: en un teclado
        // español "/" es Mayús+7. Para que "Ctrl+/" funcione en cualquier teclado, un
        // símbolo se identifica por el carácter y no cuenta la Mayús que lo produjo.
        if (tecla.length === 1 && !/[a-z0-9]/.test(tecla)) {
            const i = partes.indexOf('shift');
            if (i >= 0) partes.splice(i, 1);
        }
        partes.push(tecla);
        return partes.sort().join('+');
    }

    /** Texto legible para la interfaz: Ctrl+Shift+P */
    bonito(accel) {
        if (!accel) return '';
        return accel.split(' ').map(parte =>
            parte.split('+').map(t => {
                const k = t.trim();
                if (!k) return '';
                if (k.length === 1) return k.toUpperCase();
                return k.charAt(0).toUpperCase() + k.slice(1);
            }).join('+')
        ).join(' ');
    }

    instalar() {
        document.addEventListener('keydown', (e) => this._alPulsar(e), true);
    }

    _enCampoDeTexto(e) {
        const t = e.target;
        if (!t) return false;
        const etiqueta = (t.tagName || '').toLowerCase();
        return etiqueta === 'input' || etiqueta === 'textarea' || t.isContentEditable;
    }

    /** ¿El foco está dentro de un editor de código (Monaco)? */
    _enEditor(e) {
        const t = e.target;
        return !!(t && t.closest && t.closest('.monaco-editor'));
    }

    /**
     * ¿Aplica este comando aquí? `cuando: 'editor'` son las acciones de edición de
     * código: fuera del editor, Ctrl+Z, Ctrl+A o Alt+Arriba tienen que seguir
     * haciendo lo normal en el cuadro de chat o en un campo de búsqueda. Antes
     * Ctrl+Z y Ctrl+F se secuestraban en cualquier sitio.
     */
    _aplica(cmd, e) {
        if (cmd.nativo) return false;
        if (cmd.cuando === 'editor') return this._enEditor(e);
        return true;
    }

    _alPulsar(e) {
        // Capturando una nueva combinación desde el editor de atajos
        if (this.capturando) {
            const combo = this.desdeEvento(e);
            if (combo) {
                e.preventDefault();
                e.stopPropagation();
                this.capturando(combo);
            }
            return;
        }

        const combo = this.desdeEvento(e);
        if (!combo) return;

        // Cadena de dos pulsaciones
        const buscado = this.pendienteCadena ? `${this.pendienteCadena} ${combo}` : combo;
        this.pendienteCadena = null;

        // ¿Es el prefijo de algún atajo encadenado?
        const esPrefijo = window.PrigCommands.todos().some(c => {
            const a = this.normalizar(this.accel(c.id));
            return a.includes(' ') && a.split(' ')[0] === combo;
        });

        const cmd = window.PrigCommands.todos().find(
            c => this.normalizar(this.accel(c.id)) === buscado && this._aplica(c, e)
        );

        if (cmd) {
            // Dentro de un campo de texto solo se permiten atajos con modificador (o
            // teclas de función), para no secuestrar la escritura normal.
            const funcion = /^f([1-9]|1[0-2])$/.test(combo.split('+').pop());
            if (this._enCampoDeTexto(e) && !(e.ctrlKey || e.metaKey || e.altKey) && !funcion
                && !(cmd.cuando === 'editor' && this._enEditor(e))) return;
            e.preventDefault();
            e.stopPropagation();
            cmd.run();
            return;
        }

        if (esPrefijo && (e.ctrlKey || e.metaKey)) {
            e.preventDefault();
            this.pendienteCadena = combo;
            if (window.layoutMgr) window.layoutMgr.mensajeEstado(`${this.bonito(combo)} …`, 1800);
            setTimeout(() => { this.pendienteCadena = null; }, 1800);
        }
    }
}

window.shortcutMgr = new ShortcutManager();
