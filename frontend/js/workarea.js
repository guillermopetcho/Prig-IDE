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
        // El panel en el que se hace clic recibe el foco: los atajos actúan sobre él
        [['izq', this.panelIzq], ['der', this.panelDer]].forEach(([lado, panel]) => {
            if (!panel) return;
            panel.addEventListener('pointerdown', (e) => {
                const header = lado === 'izq' ? this.headerIzq : this.headerDer;
                if (!this.splitActivo || this.ladoFoco === lado || (header && header.contains(e.target))) return;
                this.ladoFoco = lado;
                if (this.paneles[lado].activa) this.activa = this.paneles[lado].activa;
                this.pintar();
            }, true);
        });
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
                this.abrirHerramienta('modal-kaggle-hub', 'Kaggle', 'fa-brands fa-kaggle', { lado: 'der' });
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
        this.moverA(id, ladoDestino);
    }

    ladoDe(id) {
        if (this.paneles.izq.vistas.includes(id)) return 'izq';
        if (this.paneles.der.vistas.includes(id)) return 'der';
        return null;
    }

    /**
     * Mueve una pestaña a un panel y a una posición, como al arrastrarla en VS Code:
     *  · en el mismo panel, solo cambia de orden;
     *  · al otro panel, lo abre si hacía falta (dividir);
     *  · un panel que se queda vacío se cierra y el otro ocupa todo el ancho.
     */
    moverA(id, destino, indice = null) {
        const origen = this.ladoDe(id);
        if (!origen || !this.paneles[destino]) return;
        const insertar = (lista) => {
            const resto = lista.filter(x => x !== id);
            const i = indice == null ? resto.length : Math.max(0, Math.min(indice, resto.length));
            resto.splice(i, 0, id);
            return resto;
        };

        if (origen === destino) {
            this.paneles[destino].vistas = insertar(this.paneles[destino].vistas);
            this.activar(id, destino);
            return;
        }

        // La única pestaña no puede irse a un lado que todavía no existe: no habría nada que dividir
        if (this.paneles[origen].vistas.length === 1 && this.paneles[destino].vistas.length === 0) {
            window.layoutMgr?.mensajeEstado('Abre otra ventana para ponerlas lado a lado', 2000);
            return;
        }

        const vecina = this._vecina(origen, id);
        this.paneles[origen].vistas = this.paneles[origen].vistas.filter(x => x !== id);
        if (this.paneles[origen].activa === id) this.paneles[origen].activa = vecina;
        this.paneles[destino].vistas = insertar(this.paneles[destino].vistas);
        this.paneles[destino].activa = id;

        // El panel izquierdo nunca queda vacío: si se vacía, el derecho pasa a ocupar su lugar
        if (!this.paneles.izq.vistas.length) {
            this.paneles.izq = this.paneles.der;
            this.paneles.der = { vistas: [], activa: null };
        }
        const dividido = this.paneles.der.vistas.length > 0;
        if (dividido !== this.splitActivo) {
            this.splitActivo = dividido;
            this.aplicarDisposicion();
        }

        const ladoFinal = this.ladoDe(id);
        const otro = ladoFinal === 'izq' ? 'der' : 'izq';
        if (this.splitActivo && this.paneles[otro].activa) this.activar(this.paneles[otro].activa, otro);
        this.activar(id, ladoFinal);
    }

    /** La pestaña que queda activa al quitar `id` de un panel: la de su derecha, o la de su izquierda */
    _vecina(lado, id) {
        const lista = this.paneles[lado].vistas;
        const i = lista.indexOf(id);
        return lista[i + 1] || lista[i - 1] || null;
    }

    // ------------------------------------------------------------------
    // Teclado: moverse entre ventanas y moverlas, sin ratón
    // ------------------------------------------------------------------

    /** Ventana siguiente (+1) o anterior (-1) del panel con el foco, dando la vuelta */
    ventanaSiguiente(delta) {
        const lado = this.ladoFoco || 'izq';
        const lista = this.paneles[lado].vistas;
        if (lista.length < 2) return;
        const i = lista.indexOf(this.paneles[lado].activa);
        this.activar(lista[(i + delta + lista.length) % lista.length], lado);
    }

    /** Cambia de lugar la ventana activa dentro de su barra (Ctrl+Shift+RePág/AvPág) */
    moverPestana(delta) {
        const lado = this.ladoFoco || 'izq';
        const id = this.paneles[lado].activa;
        const i = this.paneles[lado].vistas.indexOf(id);
        if (!id || i < 0) return;
        this.moverA(id, lado, Math.max(0, i + delta));
    }

    /** Lleva la ventana activa al panel izquierdo o derecho, dividiendo si hace falta */
    moverActivaA(destino) {
        const lado = this.ladoFoco || 'izq';
        const id = this.paneles[lado].activa;
        if (id) this.moverA(id, destino);
    }

    /** Pasa el foco al otro panel, sin mover nada */
    enfocarPanel(lado) {
        if (lado === 'der' && !this.splitActivo) return;
        const id = this.paneles[lado].activa;
        if (id) this.activar(id, lado);
    }

    aplicarDisposicion() {
        if (!this.panelIzq || !this.panelDer || !this.resizer) return;

        document.getElementById('trabajo-split-contenedor')?.classList.toggle('dividido', this.splitActivo);
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
                t.className = 'trabajo-tab' + (v.id === activaId ? ' activo' : '')
                    + (this.splitActivo && lado === this.ladoFoco && v.id === activaId ? ' foco' : '');
                t.dataset.id = v.id;
                t.title = `${v.titulo} · arrastra para moverla o ponerla al lado · clic derecho para más opciones`;

                t.innerHTML = `
                    <i class="fa-solid ${v.icono}"></i>
                    <span class="tab-txt">${v.titulo}</span>
                    ${v.fija ? '' : '<i class="fa-solid fa-xmark tab-cerrar" title="Cerrar pestaña"></i>'}
                `;

                t.onclick = () => { if (!this._recienArrastrada) this.activar(v.id, lado); };
                t.addEventListener('pointerdown', (e) => this._alPresionarPestana(e, v.id, lado, t));
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

    // ------------------------------------------------------------------
    // Arrastrar pestañas (clic sostenido), como en VS Code
    // ------------------------------------------------------------------

    _alPresionarPestana(e, id, lado, tabEl) {
        if (e.button !== 0 || e.target.closest('.tab-cerrar')) return;
        const inicio = { x: e.clientX, y: e.clientY };
        let arrastre = null;

        const mover = (ev) => {
            if (!arrastre) {
                if (Math.hypot(ev.clientX - inicio.x, ev.clientY - inicio.y) < 6) return;
                arrastre = this._empezarArrastre(ev, id, tabEl);
            }
            arrastre.fantasma.style.transform = `translate(${ev.clientX + 12}px, ${ev.clientY + 10}px)`;
            arrastre.destino = this._destinoArrastre(ev.clientX, ev.clientY, id);
            this._pintarDestino(arrastre.destino);
        };
        const terminar = (ev, cancelado = false) => {
            tabEl.removeEventListener('pointermove', mover);
            tabEl.removeEventListener('pointerup', soltar);
            tabEl.removeEventListener('pointercancel', cancelar);
            document.removeEventListener('keydown', teclaEsc, true);
            try { tabEl.releasePointerCapture(e.pointerId); } catch (err) { /* ya liberado */ }
            if (!arrastre) return;
            this._terminarArrastre(arrastre, tabEl);
            // El clic que sigue al soltar no debe activar la pestaña de origen
            this._recienArrastrada = true;
            setTimeout(() => { this._recienArrastrada = false; }, 0);
            const d = arrastre.destino;
            if (!cancelado && d) this._soltar(id, lado, d);
        };
        const soltar = (ev) => terminar(ev);
        const cancelar = (ev) => terminar(ev, true);
        const teclaEsc = (ev) => {
            if (ev.key === 'Escape') { ev.preventDefault(); ev.stopPropagation(); terminar(ev, true); }
        };

        // Con la captura, el movimiento llega aunque el puntero pase sobre Monaco o un iframe
        try { tabEl.setPointerCapture(e.pointerId); } catch (err) { /* sin captura */ }
        tabEl.addEventListener('pointermove', mover);
        tabEl.addEventListener('pointerup', soltar);
        tabEl.addEventListener('pointercancel', cancelar);
        document.addEventListener('keydown', teclaEsc, true);
    }

    _empezarArrastre(ev, id, tabEl) {
        const fantasma = tabEl.cloneNode(true);
        fantasma.classList.add('wa-fantasma');
        fantasma.classList.remove('foco');
        fantasma.removeAttribute('title');
        document.body.appendChild(fantasma);
        const zona = document.createElement('div');
        zona.className = 'wa-zona-drop';
        zona.hidden = true;
        const marca = document.createElement('div');
        marca.className = 'wa-marca-drop';
        marca.hidden = true;
        document.body.append(zona, marca);
        tabEl.classList.add('arrastrando');
        document.body.classList.add('wa-arrastrando');
        return { id, fantasma, zona, marca, destino: null };
    }

    _terminarArrastre(arrastre, tabEl) {
        arrastre.fantasma.remove();
        arrastre.zona.remove();
        arrastre.marca.remove();
        tabEl.classList.remove('arrastrando');
        document.body.classList.remove('wa-arrastrando');
    }

    /**
     * ¿Dónde caería la pestaña si se suelta en (x, y)?
     *  · sobre una barra de pestañas: en ese panel, en la posición marcada;
     *  · sobre el contenido de un panel: al final de ese panel;
     *  · sobre la mitad derecha con un solo panel: se abre al lado (dividir).
     */
    _destinoArrastre(x, y, id) {
        const el = document.elementFromPoint(x, y);
        if (!el) return null;
        for (const lado of ['izq', 'der']) {
            const barra = lado === 'izq' ? this.barraIzq : this.barraDer;
            const header = lado === 'izq' ? this.headerIzq : this.headerDer;
            if (header && !header.hidden && header.contains(el)) {
                const tabs = [...barra.querySelectorAll('.trabajo-tab')].filter(t => t.dataset.id !== id);
                let indice = tabs.length;
                for (let i = 0; i < tabs.length; i++) {
                    const r = tabs[i].getBoundingClientRect();
                    if (x < r.left + r.width / 2) { indice = i; break; }
                }
                const ref = tabs[indice] || tabs[indice - 1];
                let marcaX;
                if (!ref) marcaX = barra.getBoundingClientRect().left + 2;
                else if (tabs[indice]) marcaX = ref.getBoundingClientRect().left;
                else marcaX = ref.getBoundingClientRect().right;
                return { tipo: 'barra', lado, indice, marca: { x: marcaX, rect: header.getBoundingClientRect() } };
            }
        }
        for (const lado of ['izq', 'der']) {
            const panel = lado === 'izq' ? this.panelIzq : this.panelDer;
            if (!panel || panel.hidden || !panel.contains(el)) continue;
            const r = panel.getBoundingClientRect();
            if (!this.splitActivo && x > r.left + r.width * 0.6) {
                return { tipo: 'dividir', lado: 'der',
                         rect: { left: r.left + r.width / 2, top: r.top, width: r.width / 2, height: r.height } };
            }
            return { tipo: 'panel', lado, rect: { left: r.left, top: r.top, width: r.width, height: r.height } };
        }
        return null;
    }

    _pintarDestino(d) {
        const zona = document.querySelector('.wa-zona-drop');
        const marca = document.querySelector('.wa-marca-drop');
        if (!zona || !marca) return;
        zona.hidden = !(d && d.rect);
        marca.hidden = !(d && d.marca);
        if (d && d.rect) {
            Object.assign(zona.style, { left: `${d.rect.left}px`, top: `${d.rect.top}px`,
                                        width: `${d.rect.width}px`, height: `${d.rect.height}px` });
        }
        if (d && d.marca) {
            Object.assign(marca.style, { left: `${d.marca.x - 1}px`, top: `${d.marca.rect.top + 3}px`,
                                         height: `${d.marca.rect.height - 6}px` });
        }
    }

    _soltar(id, ladoOrigen, d) {
        if (d.tipo === 'barra') this.moverA(id, d.lado, d.indice);
        else if (d.tipo === 'dividir') this.moverA(id, 'der');
        else if (d.tipo === 'panel' && d.lado !== ladoOrigen) this.moverA(id, d.lado);
        else this.activar(id, ladoOrigen);     // soltada en su propio panel: nada cambia
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

        const atajo = (cmd) => {
            const a = window.shortcutMgr ? window.shortcutMgr.accel(cmd) : '';
            return a ? window.shortcutMgr.bonito(a) : '';
        };
        const destino = ladoActual === 'izq' ? 'der' : 'izq';
        const opciones = [
            {
                texto: ladoActual === 'izq' ? (this.splitActivo ? 'Mover al panel derecho' : 'Abrir al lado (dividir)') : 'Mover al panel izquierdo',
                icono: ladoActual === 'izq' ? 'fa-arrow-right' : 'fa-arrow-left',
                atajo: atajo(destino === 'der' ? 'vista.moverVentanaDerecha' : 'vista.moverVentanaIzquierda'),
                accion: () => this.moverA(vistaId, destino)
            },
            {
                texto: 'Intercambiar lados (Izquierda ↔ Derecha)',
                icono: 'fa-right-left',
                atajo: atajo('vista.intercambiarPaneles'),
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
            const otras = this.paneles[ladoActual].vistas.filter(x => x !== vistaId && !(this.vistas.find(w => w.id === x) || {}).fija);
            if (otras.length) {
                opciones.push({
                    texto: 'Cerrar las demás de este panel',
                    icono: 'fa-xmarks-lines',
                    accion: () => otras.forEach(x => this.cerrar(x))
                });
            }
        }

        opciones.forEach(op => {
            const div = document.createElement('div');
            div.style.cssText = itemEstilo;
            div.innerHTML = `<i class="fa-solid ${op.icono}" style="width:14px;"></i> <span style="flex:1;">${op.texto}</span>`
                + (op.atajo ? `<span style="color:var(--text-muted); font-size:11px; margin-left:18px;">${op.atajo}</span>` : '');
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
