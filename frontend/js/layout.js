/**
 * Disposición en dos secciones y barra de entornos al estilo de Ubuntu.
 *
 *   ┌── barra de menú ───────────────────────────────┐
 *   ├── entornos: 1 Archivos · 2 Editor · 3 Cuaderno…┤
 *   ├─────────────────┬──────────────────────────────┤
 *   │     MODELO      │          TRABAJO             │
 *   └─────────────────┴──────────────────────────────┘
 *
 * La sección de trabajo cambia de contenido según el entorno elegido, igual que
 * cambiar de escritorio en Ubuntu. La del modelo se mantiene al lado para poder
 * preguntar sin perder de vista lo que estás haciendo.
 */
class LayoutManager {
    constructor() {
                this.zen = false;
        this.oculto = { modelo: false, archivos: false, terminal: true };
    }

    init() {
        this.estado = document.getElementById('prig-mensaje-estado');
        try { this.oculto.modelo = localStorage.getItem('prig_panel_modelo_oculto') === '1'; } catch (e) { /* sin almacenamiento */ }
        const barra = document.getElementById('barra-modelo-oculto');
        if (barra) {
            barra.addEventListener('click', (e) => {
                const b = e.target.closest('[data-mostrar]');
                if (b) this.mostrarModelo(b.dataset.mostrar);
            });
        }
        this.aplicarPanelModelo();
    }

    /** Oculta o muestra Modelo/Archivos; el trabajo ocupa el ancho que queda libre */
    togglePanel(cual) {
        if (cual !== 'modelo') return;
        this.establecerPanelModelo(!this.oculto.modelo);
        if (this.oculto.modelo) this.mensajeEstado('Modelo y Archivos ocultos: vuelve a abrirlos con la barra de la izquierda o Ctrl+L', 3500);
    }

    establecerPanelModelo(oculto) {
        this.oculto.modelo = !!oculto;
        try { localStorage.setItem('prig_panel_modelo_oculto', this.oculto.modelo ? '1' : '0'); } catch (e) { /* sin almacenamiento */ }
        this.aplicarPanelModelo();
    }

    /** Vuelve a mostrar el panel en la pestaña indicada (modelo o archivos) */
    mostrarModelo(vista) {
        if (this.zen) this.alternarZen();
        if (this.oculto.modelo) this.establecerPanelModelo(false);
        if (vista && window.workArea) window.workArea.verEnModelo(vista);
    }

    aplicarPanelModelo() {
        const ocultar = this.oculto.modelo || this.zen;
        const s = document.getElementById('seccion-modelo');
        const r = document.getElementById('resizer-secciones');
        const barra = document.getElementById('barra-modelo-oculto');
        if (s) s.hidden = ocultar;
        if (r) r.hidden = ocultar;
        if (barra) barra.hidden = !this.oculto.modelo || this.zen;
        setTimeout(() => {
            if (window.editorMgr && window.editorMgr.editor) window.editorMgr.editor.layout();
            window.dispatchEvent(new Event('resize'));
        }, 60);
    }

    alternarZen() {
        this.zen = !this.zen;
        document.body.classList.toggle('modo-zen', this.zen);
        // Al salir se respeta si el panel estaba oculto antes
        this.aplicarPanelModelo();
        this.mensajeEstado(this.zen ? 'Modo concentración activado' : 'Modo concentración desactivado', 1500);
    }

    mensajeEstado(texto, ms = 2000) {
        if (!this.estado) this.estado = document.getElementById('prig-mensaje-estado');
        if (!this.estado) return;
        this.estado.textContent = texto;
        clearTimeout(this._t);
        this._t = setTimeout(() => { if (this.estado) this.estado.textContent = ''; }, ms);
    }

    initResizer() {
        const r = document.getElementById('resizer-secciones');
        const modelo = document.getElementById('seccion-modelo');
        if (!r || !modelo) return;
        let arrastrando = false;

        r.addEventListener('mousedown', () => {
            arrastrando = true;
            document.body.style.cursor = 'col-resize';
            document.body.style.userSelect = 'none';
        });
        document.addEventListener('mousemove', (e) => {
            if (!arrastrando) return;
            const ancho = Math.max(260, Math.min(Math.floor(window.innerWidth * 0.6), e.clientX));
            modelo.style.width = `${ancho}px`;
            if (window.editorMgr && window.editorMgr.editor) window.editorMgr.editor.layout();
        });
        document.addEventListener('mouseup', () => {
            if (!arrastrando) return;
            arrastrando = false;
            document.body.style.cursor = '';
            document.body.style.userSelect = '';
        });
        r.addEventListener('dblclick', () => this.togglePanel('modelo'));
    }
}

window.layoutMgr = new LayoutManager();
