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

        this.splitActivo = false;  // Panel secundario derecho abierto
        this.ladoFoco = 'izq';     // 'izq' | 'der'
        this.anchoIzq = 50;        // Porcentaje de ancho para el panel izquierdo
        try {
            const guardado = localStorage.getItem('prig_workarea_split_pct');
            if (guardado) this.anchoIzq = Math.max(20, Math.min(80, parseFloat(guardado)));
        } catch (e) { /* sin almacenamiento */ }

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
        // Elementos panel izquierdo
        this.panelIzq = document.getElementById('panel-trabajo-izq');
        this.headerIzq = document.getElementById('trabajo-header-izq');
        this.barraIzq = document.getElementById('trabajo-tabs');
        this.accionesIzq = document.getElementById('trabajo-acciones-izq');
        this.vistasIzq = document.getElementById('trabajo-vistas');

        // Divisor
        this.resizer = document.getElementById('resizer-trabajo');

        // Elementos panel derecho
        this.panelDer = document.getElementById('panel-trabajo-der');
        this.headerDer = document.getElementById('trabajo-header-der');
        this.barraDer = document.getElementById('trabajo-tabs-der');
        this.accionesDer = document.getElementById('trabajo-acciones-der');
        this.vistasDer = document.getElementById('trabajo-vistas-der');

        // Barra antigua por compatibilidad
        this.barra = this.barraIzq;

        this.vistas = [{ id: 'editor', ...this.FIJAS.editor }];
        this.aplicarDisposicion();
        this.initResizer();
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

        let lado = opciones.lado;
        if (!lado) {
            if (this.paneles.der.vistas.includes(id)) lado = 'der';
            else if (this.paneles.izq.vistas.includes(id)) lado = 'izq';
            else lado = this.splitActivo ? this.ladoFoco : 'izq';
        }

        if (!this.paneles[lado].vistas.includes(id)) {
            this.paneles[lado].vistas.push(id);
        }

        if (lado === 'der' && !this.splitActivo) {
            this.abrirDivision(id);
        } else {
            this.activar(id, lado);
        }
    }

    activar(id, lado = null) {
        if (!lado) {
            if (this.paneles.der.vistas.includes(id)) lado = 'der';
            else lado = 'izq';
        }

        this.ladoFoco = lado;
        this.paneles[lado].activa = id;
        this.activa = id;

        const vista = this.vistas.find(v => v.id === id);
        const contenedor = (lado === 'der') ? this.vistasDer : this.vistasIzq;

        if (contenedor) {
            // Ocultar las otras vistas que estén dentro de este contenedor
            contenedor.querySelectorAll('.vista-trabajo').forEach(v => { v.hidden = true; });

            let destinoEl = null;
            if (vista && vista.tipo === 'herramienta') {
                destinoEl = this._obtenerOcrearContenedorHerramienta(vista);
                this._montarHerramienta(vista, destinoEl);
            } else {
                destinoEl = document.getElementById(`vista-${id}`);
            }

            if (destinoEl) {
                if (destinoEl.parentElement !== contenedor) {
                    contenedor.appendChild(destinoEl);
                }
                destinoEl.hidden = false;
            }
        }

        // Si el modo dividido está activo, asegurarse de que el otro lado también muestre su vista activa
        if (this.splitActivo) {
            const otroLado = (lado === 'izq') ? 'der' : 'izq';
            const otroId = this.paneles[otroLado].activa;
            const otroContenedor = (otroLado === 'der') ? this.vistasDer : this.vistasIzq;
            if (otroId && otroContenedor) {
                const otraVista = this.vistas.find(v => v.id === otroId);
                let otroEl = null;
                if (otraVista && otraVista.tipo === 'herramienta') {
                    otroEl = this._obtenerOcrearContenedorHerramienta(otraVista);
                    this._montarHerramienta(otraVista, otroEl);
                } else {
                    otroEl = document.getElementById(`vista-${otroId}`);
                }
                if (otroEl) {
                    if (otroEl.parentElement !== otroContenedor) otroContenedor.appendChild(otroEl);
                    otroEl.hidden = false;
                }
            }
        }

        this.pintar();
        setTimeout(() => {
            if (window.editorMgr && window.editorMgr.editor) window.editorMgr.editor.layout();
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
                if (!this.paneles.izq.vistas.includes('editor') && !this.paneles.der.vistas.includes('editor')) {
                    this.paneles.izq.vistas.unshift('editor');
                }
            }
        }

        // Remover de panel derecho
        if (this.paneles.der.vistas.includes(id)) {
            this.paneles.der.vistas = this.paneles.der.vistas.filter(x => x !== id);
            if (this.paneles.der.activa === id) {
                this.paneles.der.activa = this.paneles.der.vistas[0] || null;
            }
            if (this.paneles.der.vistas.length === 0) {
                this.cerrarDivision();
                return;
            }
        }

        this.activar(this.paneles.izq.activa || 'editor', 'izq');
        if (this.splitActivo && this.paneles.der.activa) {
            this.activar(this.paneles.der.activa, 'der');
        }
        this.pintar();
    }

    // ------------------------------------------------------------------
    // Operaciones de Paneles Divididos (Izquierda / Derecha)
    // ------------------------------------------------------------------

    abrirDivision(vistaId = null) {
        this.splitActivo = true;
        this.aplicarDisposicion();

        if (vistaId) {
            this.paneles.izq.vistas = this.paneles.izq.vistas.filter(x => x !== vistaId);
            if (!this.paneles.der.vistas.includes(vistaId)) this.paneles.der.vistas.push(vistaId);
            this.paneles.der.activa = vistaId;
            if (this.paneles.izq.activa === vistaId) {
                this.paneles.izq.activa = this.paneles.izq.vistas[0] || 'editor';
                if (!this.paneles.izq.vistas.includes('editor')) this.paneles.izq.vistas.unshift('editor');
            }
        } else if (this.paneles.der.vistas.length === 0) {
            // Si no hay vistas en la derecha, mover una secundaria o abrir Kaggle por defecto
            const sobrantes = this.paneles.izq.vistas.filter(x => x !== this.paneles.izq.activa);
            if (sobrantes.length > 0) {
                const mover = sobrantes[sobrantes.length - 1];
                this.paneles.izq.vistas = this.paneles.izq.vistas.filter(x => x !== mover);
                this.paneles.der.vistas.push(mover);
                this.paneles.der.activa = mover;
            } else {
                // Solo estaba el editor: abrir Kaggle a la derecha como herramienta de apoyo
                this.abrirHerramienta('modal-kaggle-hub', 'Kaggle', 'fa-k', { lado: 'der' });
                return;
            }
        }

        this.activar(this.paneles.izq.activa, 'izq');
        if (this.paneles.der.activa) this.activar(this.paneles.der.activa, 'der');
        this.pintar();
        window.layoutMgr?.mensajeEstado('Área de trabajo dividida en dos paneles', 1600);
    }

    cerrarDivision() {
        if (!this.splitActivo) return;

        // Trasladar cualquier pestaña del panel derecho de vuelta al panel izquierdo
        this.paneles.der.vistas.forEach(v => {
            if (!this.paneles.izq.vistas.includes(v)) this.paneles.izq.vistas.push(v);
        });
        this.paneles.der.vistas = [];
        this.paneles.der.activa = null;
        this.splitActivo = false;

        this.aplicarDisposicion();
        this.activar(this.paneles.izq.activa || 'editor', 'izq');
        this.pintar();
        window.layoutMgr?.mensajeEstado('Modo de panel único restablecido', 1500);
    }

    intercambiarPaneles() {
        if (!this.splitActivo) {
            // Si no está dividido, dividir primero
            this.abrirDivision();
            return;
        }

        // Intercambiar listas de vistas y vistas activas
        const tmpVistas = [...this.paneles.izq.vistas];
        this.paneles.izq.vistas = [...this.paneles.der.vistas];
        this.paneles.der.vistas = tmpVistas;

        const tmpActiva = this.paneles.izq.activa;
        this.paneles.izq.activa = this.paneles.der.activa;
        this.paneles.der.activa = tmpActiva;

        // Reactivar vistas en sus nuevas posiciones
        if (this.paneles.izq.activa) this.activar(this.paneles.izq.activa, 'izq');
        if (this.paneles.der.activa) this.activar(this.paneles.der.activa, 'der');

        this.pintar();
        window.layoutMgr?.mensajeEstado('Paneles intercambiados (Izquierda ↔ Derecha)', 1600);
    }

    moverALado(id, ladoDestino) {
        const ladoOrigen = (ladoDestino === 'izq') ? 'der' : 'izq';
        if (!this.paneles[ladoOrigen].vistas.includes(id)) return;

        this.paneles[ladoOrigen].vistas = this.paneles[ladoOrigen].vistas.filter(x => x !== id);

        if (!this.paneles[ladoDestino].vistas.includes(id)) {
            this.paneles[ladoDestino].vistas.push(id);
        }
        this.paneles[ladoDestino].activa = id;

        // Si el origen era la derecha y quedó vacío, cerrar división
        if (ladoOrigen === 'der' && this.paneles.der.vistas.length === 0) {
            this.cerrarDivision();
            return;
        }

        // Si el origen era la izquierda y quedó vacío
        if (ladoOrigen === 'izq' && this.paneles.izq.vistas.length === 0) {
            // Asegurar que el editor esté en la izquierda si no está en la derecha
            if (!this.paneles.der.vistas.includes('editor')) {
                this.paneles.izq.vistas.push('editor');
                this.paneles.izq.activa = 'editor';
            } else if (this.paneles.der.vistas.length > 1) {
                // Trasladar otra vista a la izquierda para equilibrar
                const otra = this.paneles.der.vistas.find(x => x !== id);
                if (otra) {
                    this.paneles.der.vistas = this.paneles.der.vistas.filter(x => x !== otra);
                    this.paneles.izq.vistas.push(otra);
                    this.paneles.izq.activa = otra;
                }
            }
        } else if (this.paneles[ladoOrigen].activa === id) {
            this.paneles[ladoOrigen].activa = this.paneles[ladoOrigen].vistas[0] || null;
        }

        if (ladoDestino === 'der' && !this.splitActivo) {
            this.splitActivo = true;
            this.aplicarDisposicion();
        }

        if (this.paneles.izq.activa) this.activar(this.paneles.izq.activa, 'izq');
        if (this.splitActivo && this.paneles.der.activa) this.activar(this.paneles.der.activa, 'der');

        this.pintar();
    }

    aplicarDisposicion() {
        if (!this.panelIzq || !this.panelDer || !this.resizer) return;

        if (this.splitActivo) {
            this.panelDer.hidden = false;
            this.resizer.hidden = false;
            this.panelIzq.style.width = `${this.anchoIzq}%`;
            this.panelDer.style.flex = '1';
        } else {
            this.panelDer.hidden = true;
            this.resizer.hidden = true;
            this.panelIzq.style.width = '100%';
        }

        setTimeout(() => {
            if (window.editorMgr && window.editorMgr.editor) window.editorMgr.editor.layout();
            this.grupos.forEach(g => g.editor && g.editor.layout());
        }, 50);
    }

    initResizer() {
        if (!this.resizer) return;
        let arrastrando = false;

        this.resizer.addEventListener('mousedown', (e) => {
            if (!this.splitActivo) return;
            arrastrando = true;
            this.resizer.classList.add('arrastrando');
            document.body.style.cursor = 'col-resize';
            document.body.style.userSelect = 'none';
        });

        document.addEventListener('mousemove', (e) => {
            if (!arrastrando || !this.splitActivo) return;
            const cont = document.getElementById('trabajo-split-contenedor');
            if (!cont) return;
            const rect = cont.getBoundingClientRect();
            const offsetX = e.clientX - rect.left;
            const pct = Math.max(15, Math.min(85, (offsetX / rect.width) * 100));
            this.anchoIzq = pct;
            this.panelIzq.style.width = `${pct}%`;
            if (window.editorMgr && window.editorMgr.editor) window.editorMgr.editor.layout();
        });

        document.addEventListener('mouseup', () => {
            if (arrastrando) {
                arrastrando = false;
                this.resizer.classList.remove('arrastrando');
                document.body.style.cursor = '';
                document.body.style.userSelect = '';
                try {
                    localStorage.setItem('prig_workarea_split_pct', this.anchoIzq.toFixed(1));
                } catch (e) { /* ignorar */ }
                if (window.editorMgr && window.editorMgr.editor) window.editorMgr.editor.layout();
            }
        });
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
                t.title = `${v.titulo} (clic derecho para más opciones)`;

                const otroLadoTexto = (lado === 'izq') ? 'Mover a la derecha' : 'Mover a la izquierda';
                const flechaIcono = (lado === 'izq') ? 'fa-arrow-right' : 'fa-arrow-left';

                t.innerHTML = `
                    <i class="fa-solid ${v.icono}"></i>
                    <span class="tab-txt">${v.titulo}</span>
                    <button class="tab-mover" title="${otroLadoTexto}">
                        <i class="fa-solid ${flechaIcono}"></i>
                    </button>
                    ${v.fija ? '' : '<i class="fa-solid fa-xmark tab-cerrar" title="Cerrar pestaña"></i>'}
                `;

                t.onclick = () => this.activar(v.id, lado);

                const btnMover = t.querySelector('.tab-mover');
                if (btnMover) {
                    btnMover.onclick = (e) => {
                        e.stopPropagation();
                        this.moverALado(v.id, lado === 'izq' ? 'der' : 'izq');
                    };
                }

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

            if (this.splitActivo) {
                // Botón intercambiar lados
                const btnSwap = document.createElement('button');
                btnSwap.className = 'btn-accion-panel btn-swap';
                btnSwap.title = 'Intercambiar lados (Izquierda ↔ Derecha)';
                btnSwap.innerHTML = '<i class="fa-solid fa-right-left"></i>';
                btnSwap.onclick = () => this.intercambiarPaneles();
                acciones.appendChild(btnSwap);

                // Botón restablecer 50/50
                const btn50 = document.createElement('button');
                btn50.className = 'btn-accion-panel';
                btn50.title = 'Restablecer división 50/50';
                btn50.innerHTML = '<i class="fa-solid fa-table-columns"></i>';
                btn50.onclick = () => {
                    this.anchoIzq = 50;
                    this.aplicarDisposicion();
                };
                acciones.appendChild(btn50);

                // Botón cerrar división (en panel derecho o en ambos)
                if (lado === 'der') {
                    const btnCerrarDer = document.createElement('button');
                    btnCerrarDer.className = 'btn-accion-panel btn-cerrar-panel';
                    btnCerrarDer.title = 'Cerrar panel derecho (Unificar)';
                    btnCerrarDer.innerHTML = '<i class="fa-solid fa-xmark"></i>';
                    btnCerrarDer.onclick = () => this.cerrarDivision();
                    acciones.appendChild(btnCerrarDer);
                }
            } else {
                // Modo simple: botón para dividir
                const btnSplit = document.createElement('button');
                btnSplit.className = 'btn-accion-panel';
                btnSplit.title = 'Dividir área de trabajo (Lado a lado)';
                btnSplit.innerHTML = '<i class="fa-solid fa-table-columns"></i>';
                btnSplit.onclick = () => this.abrirDivision();
                acciones.appendChild(btnSplit);
            }
        });
    }

    _mostrarMenuContextualTab(e, vistaId, ladoActual) {
        // Remover menú anterior si existe
        const anterior = document.getElementById('menu-ctx-tab-trabajo');
        if (anterior) anterior.remove();

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

        const opciones = [
            {
                texto: (ladoActual === 'izq') ? 'Mover a la derecha' : 'Mover a la izquierda',
                icono: (ladoActual === 'izq') ? 'fa-arrow-right' : 'fa-arrow-left',
                accion: () => this.moverALado(vistaId, ladoActual === 'izq' ? 'der' : 'izq')
            },
            {
                texto: 'Intercambiar lados (Izquierda ↔ Derecha)',
                icono: 'fa-right-left',
                accion: () => this.intercambiarPaneles()
            }
        ];

        const v = this.vistas.find(x => x.id === vistaId);
        if (v && !v.fija) {
            opciones.push({
                texto: 'Cerrar pestaña',
                icono: 'fa-xmark',
                accion: () => this.cerrar(vistaId)
            });
        }

        opciones.forEach(op => {
            const div = document.createElement('div');
            div.style.cssText = itemEstilo;
            div.innerHTML = `<i class="fa-solid ${op.icono}" style="width:14px;"></i> <span>${op.texto}</span>`;
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

            // Inyectar botón de lado en la cabecera si aún no existe
            const header = contenido.querySelector('.modal-header');
            if (header && !header.querySelector('.modal-header-acciones-lado')) {
                const divLado = document.createElement('div');
                divLado.className = 'modal-header-acciones-lado';
                const btnLado = document.createElement('button');
                btnLado.className = 'btn-herramienta-lado';
                btnLado.title = 'Mover herramienta al panel opuesto (Izquierda ↔ Derecha)';
                btnLado.innerHTML = '<i class="fa-solid fa-right-left"></i> Cambiar lado';
                btnLado.onclick = (e) => {
                    e.stopPropagation();
                    const enDer = this.paneles.der.vistas.includes(`h:${vista.modalId}`);
                    this.moverALado(`h:${vista.modalId}`, enDer ? 'izq' : 'der');
                };
                divLado.appendChild(btnLado);
                header.insertBefore(divLado, header.querySelector('.modal-close-btn') || header.lastElementChild);
            }

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
        const principal = window.editorMgr;
        if (!principal || !principal.activePath) {
            window.layoutMgr?.mensajeEstado('Abre un archivo antes de dividir', 2000);
            return;
        }
        if (this.grupos.length >= 2) {
            window.layoutMgr?.mensajeEstado('Máximo tres columnas de código', 2000);
            return;
        }

        const cont = document.getElementById('editor-grupos');
        if (!cont || typeof monaco === 'undefined') return;

        const path = principal.activePath;
        const tab = principal.openTabs.get(path);
        const id = `grupo_${Date.now()}`;

        const col = document.createElement('div');
        col.className = 'editor-grupo';
        col.innerHTML = `
            <div class="grupo-cabecera">
                <span class="grupo-nombre"></span>
                <button class="grupo-cerrar" title="Cerrar columna"><i class="fa-solid fa-xmark"></i></button>
            </div>
            <div class="grupo-monaco"></div>`;
        col.querySelector('.grupo-nombre').textContent = tab ? tab.name : path.split('/').pop();
        cont.appendChild(col);
        cont.hidden = false;

        const ed = monaco.editor.create(col.querySelector('.grupo-monaco'), {
            model: tab ? tab.model : null,
            theme: localStorage.getItem('prig_editor_theme') || 'prig-dark',
            fontSize: parseInt(localStorage.getItem('prig_editor_font_size') || '14', 10),
            automaticLayout: true,
            minimap: { enabled: false },
            scrollBeyondLastLine: false,
        });

        const grupo = { id, path, editor: ed, el: col };
        this.grupos.push(grupo);
        window.dispatchEvent(new CustomEvent('prig:editor-creado', { detail: { editor: ed, principal: false } }));
        col.querySelector('.grupo-cerrar').onclick = () => this.cerrarGrupo(id);

        document.getElementById('monaco-editor-container')?.classList.add('con-divisiones');
        setTimeout(() => { ed.layout(); if (principal.editor) principal.editor.layout(); }, 60);
        window.layoutMgr?.mensajeEstado(`Dividido: ${grupo.path.split('/').pop()}`, 1600);
    }

    cerrarGrupo(id) {
        const g = this.grupos.find(x => x.id === id);
        if (!g) return;
        g.editor.dispose();
        g.el.remove();
        this.grupos = this.grupos.filter(x => x.id !== id);
        if (!this.grupos.length) {
            const cont = document.getElementById('editor-grupos');
            if (cont) cont.hidden = true;
            document.getElementById('monaco-editor-container')?.classList.remove('con-divisiones');
        }
        setTimeout(() => {
            if (window.editorMgr && window.editorMgr.editor) window.editorMgr.editor.layout();
        }, 60);
    }
}

window.workArea = new WorkAreaManager();
