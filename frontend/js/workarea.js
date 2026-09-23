/**
 * Área de trabajo: pestañas, división en paneles (Izquierdo / Derecho) y herramientas incrustadas.
 *
 * Reglas de diseño:
 *  · Con solo el editor abierto NO se ve ninguna barra de pestañas.
 *  · Cada herramienta que se abre ocupa una pestaña, no una ventana flotante.
 *  · Se pueden organizar las ventanas en dos paneles lado a lado (izq y der).
 *  · Cualquier ventana (Editor, Kaggle, Consola, etc.) puede colocarse a la izquierda o derecha.
 *  · Se pueden intercambiar instantáneamente con el botón (⇄).
 *  · Se pueden ver varios archivos de código uno al lado del otro dentro del editor.
 */
class WorkAreaManager {
    constructor() {
        this.vistas = [];          // [{id, titulo, icono, tipo, modalId}]
        this.activa = 'editor';
        this.grupos = [];          // divisiones del editor de código: [{id, path}]

        this.splitActivo = false;  // Secciones estrictamente separadas en vista completa
        this.ladoFoco = 'izq';     // Siempre en el contenedor principal
        this.anchoIzq = 100;

        this.paneles = {
            izq: { vistas: ['editor'], activa: 'editor' },
            der: { vistas: [], activa: null }
        };
    }

    get FIJAS() {
        return {
            editor:   { titulo: 'Editor',   icono: 'fa-code',          fija: true },
            cuaderno: { titulo: 'Cuaderno',  icono: 'fa-book-bookmark' },
            consola:  { titulo: 'Consola',   icono: 'fa-terminal' },
            buscar:   { titulo: 'Buscar',    icono: 'fa-magnifying-glass' },
        };
    }

    init() {
        // Elementos panel principal
        this.panelIzq = document.getElementById('panel-trabajo-izq');
        this.headerIzq = document.getElementById('trabajo-header-izq');
        this.barraIzq = document.getElementById('trabajo-tabs');
        this.accionesIzq = document.getElementById('trabajo-acciones-izq');
        this.vistasIzq = document.getElementById('trabajo-vistas');

        // Divisor y panel secundario permanecen ocultos (modo panel único permanente)
        this.resizer = document.getElementById('resizer-trabajo');
        this.panelDer = document.getElementById('panel-trabajo-der');
        this.headerDer = document.getElementById('trabajo-header-der');
        this.barraDer = document.getElementById('trabajo-tabs-der');
        this.accionesDer = document.getElementById('trabajo-acciones-der');
        this.vistasDer = document.getElementById('trabajo-vistas-der');

        this.barra = this.barraIzq;
        this.vistas = [{ id: 'editor', ...this.FIJAS.editor }];
        this.aplicarDisposicion();
        this.pintar();
        this.initTabsModelo();
    }

    // ------------------------------------------------------------------
    // Pestañas de la sección Modelo (Chat / Archivos)
    // ------------------------------------------------------------------

    initTabsModelo() {
        const cont = document.getElementById('tabs-modelo');
        if (!cont) return;
        cont.addEventListener('click', (e) => {
            const b = e.target.closest('.sub-tab');
            if (b) this.verEnModelo(b.dataset.vista);
        });
    }

    verEnModelo(vista) {
        if (window.layoutMgr && window.layoutMgr.oculto.modelo) window.layoutMgr.establecerPanelModelo(false);
        ['modelo', 'archivos'].forEach(v => {
            const el = document.getElementById(`vista-${v}`);
            if (el) el.hidden = (v !== vista);
        });
        const cont = document.getElementById('tabs-modelo');
        if (cont) {
            cont.querySelectorAll('.sub-tab').forEach(b =>
                b.classList.toggle('activo', b.dataset.vista === vista));
        }
        const sel = document.getElementById('model-select');
        if (sel) sel.style.visibility = (vista === 'modelo') ? 'visible' : 'hidden';
    }

    // ------------------------------------------------------------------
    // Gestión de Pestañas y Vistas
    // ------------------------------------------------------------------

    abrir(id, opciones = {}) {
        let vista = this.vistas.find(v => v.id === id);
        if (!vista) {
            vista = {
                id,
                titulo: opciones.titulo || (this.FIJAS[id] && this.FIJAS[id].titulo) || id,
                icono: opciones.icono || (this.FIJAS[id] && this.FIJAS[id].icono) || 'fa-window-maximize',
                tipo: opciones.tipo || 'fija',
                modalId: opciones.modalId || null,
            };
            this.vistas.push(vista);
        }

        let lado = 'izq';
        if (!this.paneles.izq.vistas.includes(id)) {
            this.paneles.izq.vistas.push(id);
        }
        this.activar(id, 'izq');
    }

    activar(id, lado = 'izq') {
        this.ladoFoco = 'izq';
        this.paneles.izq.activa = id;
        this.activa = id;

        const vista = this.vistas.find(v => v.id === id);
        const contenedor = this.vistasIzq;

        if (contenedor) {
            // Ocultar las otras vistas que estén dentro de este contenedor
            contenedor.querySelectorAll('.vista-trabajo').forEach(v => { v.hidden = true; });

            let destinoEl = null;
            if (vista && vista.tipo === 'herramienta') {
                destinoEl = this._obtenerOcrearContenedorHerramienta(vista);
                if (destinoEl.parentElement !== contenedor) {
                    contenedor.appendChild(destinoEl);
                }
                destinoEl.hidden = false;
                this._montarHerramienta(vista, destinoEl);
            } else {
                destinoEl = document.getElementById(`vista-${id}`);
                if (destinoEl) {
                    if (destinoEl.parentElement !== contenedor) {
                        contenedor.appendChild(destinoEl);
                    }
                    destinoEl.hidden = false;
                }
            }
        }

        this.pintar();
        setTimeout(() => {
            if (window.editorMgr && window.editorMgr.editor) window.editorMgr.editor.layout();
            if (window.editorMgr && typeof window.editorMgr.refreshEditorLayouts === 'function') {
                window.editorMgr.refreshEditorLayouts();
            }
            this.grupos.forEach(g => g.editor && g.editor.layout());
        }, 60);
    }

    cerrar(id) {
        const vista = this.vistas.find(v => v.id === id);
        if (!vista || vista.fija) return;

        if (vista.tipo === 'herramienta') this._devolverHerramienta(vista);

        this.vistas = this.vistas.filter(v => v.id !== id);

        // Remover de panel izquierdo
        if (this.paneles.izq.vistas.includes(id)) {
            this.paneles.izq.vistas = this.paneles.izq.vistas.filter(x => x !== id);
            if (this.paneles.izq.activa === id) {
                this.paneles.izq.activa = this.paneles.izq.vistas[0] || 'editor';
                if (!this.paneles.izq.vistas.includes('editor')) {
                    this.paneles.izq.vistas.unshift('editor');
                }
            }
        }

        this.activar(this.paneles.izq.activa || 'editor', 'izq');
    }

    // ------------------------------------------------------------------
    // Operaciones de Paneles (La división pertenece exclusivamente al Editor)
    // ------------------------------------------------------------------

    abrirDivision(vistaId = null) {
        // Redirigir la división exclusivamente a las columnas del Editor de código
        if (this.activa === 'editor' && window.editorMgr) {
            window.editorMgr.splitRight();
        } else {
            this.activar('editor');
            if (window.editorMgr) window.editorMgr.splitRight();
        }
    }

    cerrarDivision() {
        this.splitActivo = false;
        this.aplicarDisposicion();
    }

    intercambiarPaneles() {
        if (this.activa === 'editor' && window.editorMgr && window.editorMgr.numColumns > 1) {
            const nextCol = (window.editorMgr.activeCol + 1) % window.editorMgr.numColumns;
            if (window.editorMgr.activePath) {
                window.editorMgr.moveTabToPane(window.editorMgr.activePath, window.editorMgr.activeCol, nextCol);
            }
        }
    }

    moverALado(id, ladoDestino) {
        // No-op para secciones; las secciones son únicas y separadas
    }

    ladoDe(id) {
        return 'izq';
    }

    moverA(id, destino = 'izq', indice = null) {
        const resto = this.paneles.izq.vistas.filter(x => x !== id);
        const i = indice == null ? resto.length : Math.max(0, Math.min(indice, resto.length));
        resto.splice(i, 0, id);
        this.paneles.izq.vistas = resto;
        this.activar(id, 'izq');
    }

    /** La pestaña que queda activa al quitar `id`: la de su derecha, o la de su izquierda */
    _vecina(lado, id) {
        const lista = this.paneles.izq.vistas;
        const i = lista.indexOf(id);
        return lista[i + 1] || lista[i - 1] || null;
    }

    // ------------------------------------------------------------------
    // Teclado: moverse entre pestañas de trabajo
    // ------------------------------------------------------------------

    /** Pestaña siguiente (+1) o anterior (-1) */
    ventanaSiguiente(delta) {
        const lista = this.paneles.izq.vistas;
        if (lista.length < 2) return;
        const i = lista.indexOf(this.paneles.izq.activa);
        this.activar(lista[(i + delta + lista.length) % lista.length], 'izq');
    }

    /** Cambia de lugar la pestaña activa dentro de su barra */
    moverPestana(delta) {
        const id = this.paneles.izq.activa;
        const i = this.paneles.izq.vistas.indexOf(id);
        if (!id || i < 0) return;
        this.moverA(id, 'izq', Math.max(0, i + delta));
    }

    moverActivaA(destino) {
        // No-op para secciones
    }

    enfocarPanel(lado) {
        this.ladoFoco = 'izq';
    }

    aplicarDisposicion() {
        if (!this.panelIzq) return;

        document.getElementById('trabajo-split-contenedor')?.classList.remove('dividido');
        if (this.panelDer) this.panelDer.hidden = true;
        if (this.resizer) this.resizer.hidden = true;
        this.panelIzq.style.width = '100%';
        this.panelIzq.style.flex = '1';

        setTimeout(() => {
            if (window.editorMgr && window.editorMgr.editor) window.editorMgr.editor.layout();
            if (window.editorMgr && typeof window.editorMgr.refreshEditorLayouts === 'function') {
                window.editorMgr.refreshEditorLayouts();
            }
            this.grupos.forEach(g => g.editor && g.editor.layout());
        }, 50);
    }

    initResizer() {
        // No-op: las secciones se mantienen al 100% de ancho sin división de espacio de trabajo
    }

    // ------------------------------------------------------------------
    // Renderizado de Pestañas y Cabeceras
    // ------------------------------------------------------------------

    pintar() {
        ['izq', 'der'].forEach(lado => {
            const barra = (lado === 'izq') ? this.barraIzq : this.barraDer;
            const header = (lado === 'izq') ? this.headerIzq : this.headerDer;
            const acciones = (lado === 'izq') ? this.accionesIzq : this.accionesDer;
            if (!barra || !header || !acciones) return;

            const listaIds = this.paneles[lado].vistas;
            const activaId = this.paneles[lado].activa;

            if (lado === 'der' && !this.splitActivo) {
                header.hidden = true;
                barra.innerHTML = '';
                acciones.innerHTML = '';
                return;
            }

            // Regla: con solo el editor abierto en panel único, no se ve barra de pestañas
            if (lado === 'izq' && !this.splitActivo && listaIds.length <= 1 && listaIds[0] === 'editor') {
                header.hidden = true;
                barra.innerHTML = '';
                acciones.innerHTML = '';
                return;
            }

            header.hidden = false;
            barra.innerHTML = '';

            // Pintar pestañas del panel
            listaIds.forEach(id => {
                const v = this.vistas.find(x => x.id === id);
                if (!v) return;

                const t = document.createElement('div');
                t.className = 'trabajo-tab' + (v.id === activaId ? ' activo' : '');
                t.dataset.id = v.id;
                t.title = v.titulo;

                t.innerHTML = `
                    <i class="fa-solid ${v.icono}"></i>
                    <span class="tab-txt">${v.titulo}</span>
                    ${v.fija ? '' : '<i class="fa-solid fa-xmark tab-cerrar" title="Cerrar pestaña"></i>'}
                `;

                t.onclick = () => this.activar(v.id, lado);
                // Clic con la rueda: cerrar, como en VS Code
                t.addEventListener('auxclick', (e) => { if (e.button === 1 && !v.fija) { e.preventDefault(); this.cerrar(v.id); } });

                const btnCerrar = t.querySelector('.tab-cerrar');
                if (btnCerrar) {
                    btnCerrar.onclick = (e) => {
                        e.stopPropagation();
                        this.cerrar(v.id);
                    };
                }

                // Menú contextual en la pestaña
                t.oncontextmenu = (e) => {
                    e.preventDefault();
                    this._mostrarMenuContextualTab(e, v.id, lado);
                };

                barra.appendChild(t);
            });

            // Pintar botones de acción de la cabecera
            acciones.innerHTML = '';
        });
    }

    _mostrarMenuContextualTab(e, vistaId, ladoActual) {
        // Remover menú anterior si existe
        const anterior = document.getElementById('menu-ctx-tab-trabajo');
        if (anterior) anterior.remove();

        const v = this.vistas.find(x => x.id === vistaId);
        const opciones = [];
        if (v && !v.fija) {
            opciones.push({
                texto: 'Cerrar pestaña',
                icono: 'fa-xmark',
                accion: () => this.cerrar(vistaId)
            });
            const otras = this.paneles.izq.vistas.filter(x => x !== vistaId && !(this.vistas.find(w => w.id === x) || {}).fija);
            if (otras.length) {
                opciones.push({
                    texto: 'Cerrar las demás pestañas',
                    icono: 'fa-xmarks-lines',
                    accion: () => otras.forEach(x => this.cerrar(x))
                });
            }
        }

        if (!opciones.length) return;

        const menu = document.createElement('div');
        menu.id = 'menu-ctx-tab-trabajo';
        menu.style.position = 'fixed';
        menu.style.left = `${e.clientX}px`;
        menu.style.top = `${e.clientY}px`;
        menu.style.background = 'var(--bg-card, #1e1e2e)';
        menu.style.border = '1px solid var(--border-color)';
        menu.style.borderRadius = '6px';
        menu.style.boxShadow = '0 6px 18px rgba(0,0,0,0.4)';
        menu.style.padding = '4px 0';
        menu.style.zIndex = '10000';
        menu.style.fontSize = '12px';

        const itemEstilo = 'padding:6px 14px; cursor:pointer; display:flex; align-items:center; gap:8px; color:var(--text-main);';

        opciones.forEach(op => {
            const div = document.createElement('div');
            div.style.cssText = itemEstilo;
            div.innerHTML = `<i class="fa-solid ${op.icono}" style="width:14px;"></i> <span style="flex:1;">${op.texto}</span>`;
            div.onmouseover = () => { div.style.background = 'rgba(137, 180, 250, 0.15)'; };
            div.onmouseout = () => { div.style.background = 'transparent'; };
            div.onclick = () => {
                menu.remove();
                op.accion();
            };
            menu.appendChild(div);
        });

        document.body.appendChild(menu);

        const cerrarAlClickFuera = (ev) => {
            if (!menu.contains(ev.target)) {
                menu.remove();
                document.removeEventListener('click', cerrarAlClickFuera);
            }
        };
        setTimeout(() => document.addEventListener('click', cerrarAlClickFuera), 10);
    }

    // ------------------------------------------------------------------
    // Herramientas dentro de pestañas y paneles
    // ------------------------------------------------------------------

    abrirHerramienta(modalId, titulo, icono, opciones = {}) {
        const id = `h:${modalId}`;
        this.abrir(id, { titulo, icono, tipo: 'herramienta', modalId, ...opciones });
    }

    _obtenerOcrearContenedorHerramienta(vista) {
        const idCont = `vista-tool-${vista.modalId}`;
        let el = document.getElementById(idCont);
        if (!el) {
            el = document.createElement('div');
            el.id = idCont;
            el.className = 'vista-trabajo vista-herramienta-contenedor';
            el.hidden = true;
        }
        return el;
    }

    _montarHerramienta(vista, destino) {
        const modal = document.getElementById(vista.modalId);
        if (!destino || !modal) return;

        const contenido = modal.querySelector('.modal-content') || destino.querySelector('.modal-content');
        if (!contenido) return;

        if (contenido.parentElement !== destino) {
            contenido.dataset.modalOrigen = vista.modalId;
            contenido.classList.add('incrustado');

            // Moverla de lado ya no necesita botón propio: se arrastra su pestaña o se usa el teclado
            destino.appendChild(contenido);
            modal.style.display = 'none';
        }

        document.dispatchEvent(new CustomEvent('prig:herramienta-abierta', { detail: { modalId: vista.modalId } }));
    }

    _devolverHerramienta(vista) {
        const modal = document.getElementById(vista.modalId);
        const destino = document.getElementById(`vista-tool-${vista.modalId}`) || document.getElementById('vista-herramienta');
        if (!modal || !destino) return;

        const contenido = destino.querySelector('.modal-content');
        if (contenido) {
            contenido.classList.remove('incrustado');
            delete contenido.dataset.modalOrigen;
            const accionesLado = contenido.querySelector('.modal-header-acciones-lado');
            if (accionesLado) accionesLado.remove();
            modal.appendChild(contenido);
        }
        destino.remove();
        modal.style.display = 'none';
    }

    // ------------------------------------------------------------------
    // Ver varios archivos a la vez dentro del Editor (Ctrl+\)
    // ------------------------------------------------------------------

    dividir() {
        if (window.editorMgr) {
            window.editorMgr.splitRight();
        }
    }

    cerrarGrupo(id) {
        if (window.editorMgr) {
            window.editorMgr.setColumnLayout(Math.max(1, window.editorMgr.numColumns - 1));
        }
    }
}

window.workArea = new WorkAreaManager();
