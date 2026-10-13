/**
 * Motor de Aprendizaje por Grafo de Nodos (Knowledge Graph Learning Engine) para Prig IDE.
 * 
 * Articula de forma unificada las 4 herramientas educativas de Prig:
 *   - YouTube:  Reproducción con marcas de tiempo pedagógicas.
 *   - GitHub:   Repositorios open-source y código base de la industria.
 *   - Kaggle:   Datasets reales y cuadernos de análisis exploratorio.
 *   - Prig Hub: Blueprints y paquetes curriculares en texto plano.
 * 
 * Estructura:
 *   - Visualización DAG interactiva (Canvas SVG de curvas de Bezier y cuadrícula por niveles).
 *   - Marcos teóricos formales (resúmenes, principios, fórmulas y definiciones).
 *   - Tareas pre-respondidas con guía paso a paso y ejecutor determinista de pruebas (<50ms).
 *   - Integración nativa con el Editor Prig (scaffolding y apertura con un solo clic).
 */

(function () {
    const $ = (id) => document.getElementById(id);
    const esc = (t) => String(t ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
    const json = (url, opciones) => window.prigFetchJson(url, opciones);
    const enviar = (url, cuerpo, metodo = 'POST') => json(url, {
        method: metodo,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(cuerpo || {})
    });

    const COLORES_NIVEL = {
        junior: { fondo: 'rgba(166, 227, 161, 0.15)', borde: '#a6e3a1', texto: '#a6e3a1', badge: '#2e7d32' },
        intermedio: { fondo: 'rgba(203, 166, 247, 0.15)', borde: '#cba6f7', texto: '#cba6f7', badge: '#7b1fa2' },
        avanzado: { fondo: 'rgba(243, 139, 168, 0.15)', borde: '#f38ba8', texto: '#f38ba8', badge: '#c2185b' },
        senior: { fondo: 'rgba(116, 199, 236, 0.15)', borde: '#74c7ec', texto: '#74c7ec', badge: '#0277bd' }
    };

    const estado = {
        montado: false,
        cargando: false,
        error: null,
        datosGrafo: null,
        nodos: [],
        aristas: [],
        nodoActivoId: null,
        nodoActivo: null,
        filtroNivel: 'todos',
        queryBusqueda: '',
        vista: 'grafo', // 'grafo' | 'ruta'
        pestanaDetalle: 'teoria', // 'teoria' | 'herramientas' | 'desafio'
        mostrarSolucion: false,
        ejecutandoTest: false,
        resultadoTest: null,
        codigoEditor: '',
        pistasAbiertas: {}
    };

    // =========================================================================
    // ESTILOS CSS INYECTADOS
    // =========================================================================

    function estilos() {
        if ($('mag-estilos')) return;
        const css = document.createElement('style');
        css.id = 'mag-estilos';
        css.textContent = `
            #aprendizaje-grafo-raiz {
                display: flex;
                flex-direction: column;
                height: 100%;
                width: 100%;
                background: var(--bg-dark, #11111b);
                color: var(--text-main, #cdd6f4);
                font-family: var(--font-sans, system-ui, -apple-system, sans-serif);
                overflow: hidden;
            }

            /* Barra de control superior */
            .mag-toolbar {
                display: flex;
                align-items: center;
                justify-content: space-between;
                padding: 10px 18px;
                background: var(--bg-panel, #181825);
                border-bottom: 1px solid var(--border-color, #313244);
                gap: 12px;
                flex-shrink: 0;
                z-index: 10;
            }
            .mag-toolbar-izq {
                display: flex;
                align-items: center;
                gap: 12px;
                flex: 1;
                min-width: 0;
            }
            .mag-toolbar-der {
                display: flex;
                align-items: center;
                gap: 10px;
                flex-shrink: 0;
            }
            .mag-busqueda-wrap {
                position: relative;
                width: 280px;
            }
            .mag-busqueda-wrap i {
                position: absolute;
                left: 10px;
                top: 50%;
                transform: translateY(-50%);
                color: var(--text-muted, #a6adc8);
                font-size: 12px;
            }
            .mag-busqueda-input {
                width: 100%;
                background: var(--bg-dark, #11111b);
                border: 1px solid var(--border-color, #313244);
                border-radius: 7px;
                padding: 6px 10px 6px 30px;
                font-size: 12px;
                color: #fff;
                outline: none;
                transition: border-color 0.15s;
            }
            .mag-busqueda-input:focus {
                border-color: #cba6f7;
            }
            .mag-filtros-nivel {
                display: inline-flex;
                background: rgba(255,255,255,0.04);
                border: 1px solid var(--border-color, #313244);
                border-radius: 8px;
                padding: 2px;
                gap: 2px;
            }
            .mag-btn-filtro {
                background: none;
                border: none;
                color: var(--text-muted, #a6adc8);
                font-size: 11.5px;
                font-weight: 500;
                padding: 4px 10px;
                border-radius: 6px;
                cursor: pointer;
                transition: all 0.15s;
            }
            .mag-btn-filtro:hover {
                color: #fff;
                background: rgba(255,255,255,0.06);
            }
            .mag-btn-filtro.activo {
                background: #cba6f7;
                color: #11111b;
                font-weight: 700;
            }

            /* Métricas de progreso global */
            .mag-stats-pill {
                display: flex;
                align-items: center;
                gap: 8px;
                background: rgba(255,255,255,0.05);
                border: 1px solid var(--border-color, #313244);
                border-radius: 8px;
                padding: 4px 12px;
                font-size: 11.5px;
            }
            .mag-barra-progreso-wrap {
                width: 80px;
                height: 6px;
                background: rgba(255,255,255,0.1);
                border-radius: 3px;
                overflow: hidden;
            }
            .mag-barra-progreso-fill {
                height: 100%;
                background: #a6e3a1;
                transition: width 0.3s ease;
            }

            /* Layout principal dividido: Grafo / Lista (Izq) + Inspector de Nodo (Der) */
            .mag-cuerpo {
                display: flex;
                flex: 1;
                min-height: 0;
                overflow: hidden;
                position: relative;
            }

            /* Contenedor del Grafo interactivo */
            .mag-grafo-lienzo-wrap {
                flex: 1;
                position: relative;
                overflow: auto;
                background: radial-gradient(circle at 50% 50%, rgba(203,166,247,0.03) 0%, transparent 80%),
                            linear-gradient(rgba(255,255,255,0.02) 1px, transparent 1px),
                            linear-gradient(90deg, rgba(255,255,255,0.02) 1px, transparent 1px);
                background-size: 100% 100%, 32px 32px, 32px 32px;
                padding: 30px;
                min-width: 0;
            }
            .mag-svg-conexiones {
                position: absolute;
                top: 0;
                left: 0;
                pointer-events: none;
                z-index: 1;
            }

            /* Cuadrícula de Niveles en el Grafo */
            .mag-grafo-grid {
                display: flex;
                gap: 50px;
                position: relative;
                z-index: 2;
                min-width: 900px;
                padding: 20px 10px 60px 10px;
            }
            .mag-columna-nivel {
                display: flex;
                flex-direction: column;
                gap: 24px;
                width: 260px;
                flex-shrink: 0;
            }
            .mag-columna-header {
                font-size: 12px;
                font-weight: 700;
                text-transform: uppercase;
                letter-spacing: 0.8px;
                padding: 6px 12px;
                border-radius: 6px;
                text-align: center;
                border: 1px solid transparent;
            }

            /* Tarjetas de Nodos de Conocimiento */
            .mag-nodo-card {
                background: var(--bg-panel, #181825);
                border: 1px solid var(--border-color, #313244);
                border-radius: 12px;
                padding: 14px;
                cursor: pointer;
                transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
                box-shadow: 0 4px 12px rgba(0,0,0,0.25);
                position: relative;
                user-select: none;
            }
            .mag-nodo-card:hover {
                transform: translateY(-2px);
                box-shadow: 0 8px 24px rgba(0,0,0,0.35);
                border-color: #89b4fa;
            }
            .mag-nodo-card.activo {
                border-color: #cba6f7 !important;
                box-shadow: 0 0 0 2px rgba(203,166,247,0.35), 0 8px 24px rgba(0,0,0,0.4);
                background: #1e1e2e;
            }
            .mag-nodo-card.completado {
                border-color: rgba(166, 227, 161, 0.6);
            }
            .mag-nodo-card.completado::after {
                content: '✓';
                position: absolute;
                top: -8px;
                right: -8px;
                width: 22px;
                height: 22px;
                background: #a6e3a1;
                color: #11111b;
                border-radius: 50%;
                display: flex;
                align-items: center;
                justify-content: center;
                font-size: 12px;
                font-weight: 900;
                box-shadow: 0 2px 6px rgba(0,0,0,0.4);
            }
            .mag-nodo-cabecera {
                display: flex;
                align-items: flex-start;
                gap: 10px;
                margin-bottom: 8px;
            }
            .mag-nodo-icono {
                width: 32px;
                height: 32px;
                border-radius: 8px;
                display: flex;
                align-items: center;
                justify-content: center;
                font-size: 15px;
                flex-shrink: 0;
            }
            .mag-nodo-titulo {
                font-size: 13px;
                font-weight: 700;
                line-height: 1.35;
                color: #fff;
                flex: 1;
            }
            .mag-nodo-etapa {
                font-size: 10.5px;
                color: var(--text-muted, #a6adc8);
                margin-bottom: 10px;
                display: block;
            }
            .mag-nodo-pilares {
                display: flex;
                align-items: center;
                gap: 6px;
                margin-top: 10px;
                padding-top: 8px;
                border-top: 1px solid rgba(255,255,255,0.06);
            }
            .mag-pilar-badge {
                font-size: 9.5px;
                font-weight: 700;
                padding: 2px 6px;
                border-radius: 4px;
                display: inline-flex;
                align-items: center;
                gap: 3px;
            }
            .mag-pilar-yt { background: rgba(255,0,0,0.12); color: #ff5555; border: 1px solid rgba(255,0,0,0.25); }
            .mag-pilar-gh { background: rgba(88,166,255,0.12); color: #58a6ff; border: 1px solid rgba(88,166,255,0.25); }
            .mag-pilar-kg { background: rgba(32,190,255,0.12); color: #20beff; border: 1px solid rgba(32,190,255,0.25); }
            .mag-pilar-hub { background: rgba(203,166,247,0.12); color: #cba6f7; border: 1px solid rgba(203,166,247,0.25); }

            /* Panel Inspector de Detalle (Lateral Derecho) */
            .mag-inspector {
                width: 520px;
                background: var(--bg-panel, #181825);
                border-left: 1px solid var(--border-color, #313244);
                display: flex;
                flex-direction: column;
                min-height: 0;
                flex-shrink: 0;
                z-index: 5;
            }
            .mag-inspector-header {
                padding: 16px 20px;
                border-bottom: 1px solid var(--border-color, #313244);
                background: rgba(0,0,0,0.15);
            }
            .mag-inspector-titulo-fila {
                display: flex;
                align-items: flex-start;
                justify-content: space-between;
                gap: 12px;
                margin-bottom: 8px;
            }
            .mag-inspector-titulo {
                font-size: 16px;
                font-weight: 700;
                color: #fff;
                line-height: 1.3;
            }
            .mag-inspector-acciones-rapidas {
                display: flex;
                gap: 8px;
                margin-top: 12px;
                flex-wrap: wrap;
            }
            .mag-btn-accion {
                display: inline-flex;
                align-items: center;
                gap: 6px;
                font-size: 11.5px;
                font-weight: 600;
                padding: 6px 12px;
                border-radius: 7px;
                cursor: pointer;
                transition: all 0.15s;
                border: 1px solid transparent;
            }
            .mag-btn-accion.primario {
                background: #89b4fa;
                color: #11111b;
            }
            .mag-btn-accion.primario:hover {
                background: #b4befe;
            }
            .mag-btn-accion.exito {
                background: rgba(166, 227, 161, 0.15);
                border-color: #a6e3a1;
                color: #a6e3a1;
            }
            .mag-btn-accion.exito:hover {
                background: rgba(166, 227, 161, 0.25);
            }
            .mag-btn-accion.neutro {
                background: rgba(255,255,255,0.06);
                border-color: var(--border-color, #313244);
                color: var(--text-main, #cdd6f4);
            }
            .mag-btn-accion.neutro:hover {
                background: rgba(255,255,255,0.1);
            }

            /* Pestañas del Inspector */
            .mag-inspector-tabs {
                display: flex;
                border-bottom: 1px solid var(--border-color, #313244);
                background: rgba(0,0,0,0.1);
                padding: 0 16px;
            }
            .mag-inspector-tab-btn {
                background: none;
                border: none;
                color: var(--text-muted, #a6adc8);
                font-size: 12px;
                font-weight: 600;
                padding: 10px 14px;
                cursor: pointer;
                border-bottom: 2px solid transparent;
                transition: all 0.15s;
                display: inline-flex;
                align-items: center;
                gap: 6px;
            }
            .mag-inspector-tab-btn:hover {
                color: #fff;
            }
            .mag-inspector-tab-btn.activo {
                color: #cba6f7;
                border-bottom-color: #cba6f7;
            }

            .mag-inspector-contenido {
                flex: 1;
                overflow-y: auto;
                padding: 18px 20px 40px 20px;
                min-height: 0;
            }

            /* Secciones de Contenido */
            .mag-card-teoria {
                background: rgba(255,255,255,0.03);
                border: 1px solid rgba(255,255,255,0.07);
                border-radius: 9px;
                padding: 14px;
                margin-bottom: 14px;
            }
            .mag-card-teoria h4 {
                margin: 0 0 8px 0;
                font-size: 13px;
                color: #cba6f7;
                display: flex;
                align-items: center;
                gap: 6px;
            }
            .mag-card-teoria p {
                margin: 0;
                font-size: 12px;
                line-height: 1.6;
                color: #a6adc8;
            }
            .mag-principios-lista {
                list-style: none;
                padding: 0;
                margin: 0;
                display: flex;
                flex-direction: column;
                gap: 8px;
            }
            .mag-principios-lista li {
                font-size: 12px;
                line-height: 1.5;
                color: #cdd6f4;
                position: relative;
                padding-left: 18px;
            }
            .mag-principios-lista li::before {
                content: '•';
                position: absolute;
                left: 4px;
                color: #89b4fa;
                font-weight: bold;
            }
            .mag-formula-box {
                background: #11111b;
                border: 1px solid rgba(203,166,247,0.3);
                border-radius: 7px;
                padding: 10px 14px;
                font-family: 'Fira Code', monospace;
                font-size: 12px;
                color: #f9e2af;
                margin-top: 8px;
                overflow-x: auto;
            }

            /* Herramientas Tabs */
            .mag-herramienta-card {
                background: rgba(255,255,255,0.02);
                border: 1px solid var(--border-color, #313244);
                border-radius: 10px;
                padding: 14px;
                margin-bottom: 14px;
            }
            .mag-herramienta-card-header {
                display: flex;
                align-items: center;
                justify-content: space-between;
                margin-bottom: 10px;
            }
            .mag-herramienta-titulo {
                display: flex;
                align-items: center;
                gap: 8px;
                font-size: 13px;
                font-weight: 700;
                color: #fff;
            }

            /* Tarea y Desafío */
            .mag-desafio-box {
                background: #11111b;
                border: 1px solid var(--border-color, #313244);
                border-radius: 10px;
                overflow: hidden;
                margin-bottom: 16px;
            }
            .mag-desafio-enunciado {
                padding: 14px;
                font-size: 12.5px;
                line-height: 1.6;
                color: #cdd6f4;
                border-bottom: 1px solid var(--border-color, #313244);
                background: rgba(255,255,255,0.02);
            }
            .mag-editor-codigo-tarea {
                width: 100%;
                min-height: 160px;
                background: #11111b;
                color: #a6e3a1;
                font-family: 'Fira Code', monospace;
                font-size: 12px;
                line-height: 1.5;
                padding: 12px;
                border: none;
                outline: none;
                resize: vertical;
                box-sizing: border-box;
            }
            .mag-consola-salida {
                background: #09090f;
                border-top: 1px solid var(--border-color, #313244);
                padding: 10px 14px;
                font-family: 'Fira Code', monospace;
                font-size: 11.5px;
                max-height: 180px;
                overflow-y: auto;
            }
            .mag-consola-salida.exito { color: #a6e3a1; }
            .mag-consola-salida.error { color: #f38ba8; }

            .mag-solucion-desplegable {
                background: rgba(255,255,255,0.03);
                border: 1px solid rgba(255,255,255,0.08);
                border-radius: 8px;
                padding: 12px;
                margin-top: 14px;
            }
        `;
        document.head.appendChild(css);
    }

    // =========================================================================
    // INICIALIZACIÓN Y MONTAJE DEL COMPONENTE
    // =========================================================================

    function montar() {
        estilos();
        const raiz = $('aprendizaje-grafo-raiz');
        if (!raiz || estado.montado) return;

        raiz.innerHTML = `
            <div class="mag-toolbar">
                <div class="mag-toolbar-izq">
                    <div class="mag-busqueda-wrap">
                        <i class="fa-solid fa-magnifying-glass"></i>
                        <input type="text" id="mag-input-busqueda" class="mag-busqueda-input" placeholder="Buscar concepto, fórmula o dataset...">
                    </div>
                    <div class="mag-filtros-nivel" id="mag-filtros-nivel">
                        <button class="mag-btn-filtro activo" data-nivel="todos">Todos</button>
                        <button class="mag-btn-filtro" data-nivel="junior">Junior</button>
                        <button class="mag-btn-filtro" data-nivel="intermedio">Intermedio</button>
                        <button class="mag-btn-filtro" data-nivel="avanzado">Avanzado</button>
                        <button class="mag-btn-filtro" data-nivel="senior">Senior</button>
                    </div>
                </div>
                <div class="mag-toolbar-der">
                    <div class="mag-stats-pill" id="mag-stats-pill" title="Progreso de nodos completados">
                        <span><i class="fa-solid fa-diagram-project" style="color:#cba6f7;"></i> Progreso:</span>
                        <div class="mag-barra-progreso-wrap">
                            <div class="mag-barra-progreso-fill" id="mag-progreso-fill" style="width: 0%;"></div>
                        </div>
                        <b id="mag-progreso-txt" style="color:#a6e3a1;">0%</b>
                    </div>
                    <button class="mag-btn-accion neutro" id="mag-btn-recargar" title="Recargar Grafo"><i class="fa-solid fa-arrows-rotate"></i></button>
                </div>
            </div>

            <div class="mag-cuerpo">
                <div class="mag-grafo-lienzo-wrap" id="mag-lienzo-wrap">
                    <svg class="mag-svg-conexiones" id="mag-svg-aristas" width="2000" height="2000"></svg>
                    <div class="mag-grafo-grid" id="mag-grafo-grid"></div>
                </div>

                <aside class="mag-inspector" id="mag-inspector">
                    <div style="padding: 40px 20px; text-align: center; color: var(--text-muted);">
                        <i class="fa-solid fa-diagram-project" style="font-size: 32px; color: #cba6f7; margin-bottom: 12px; display: block;"></i>
                        <p>Selecciona un nodo del grafo para estudiar su marco teórico y resolver su desafío.</p>
                    </div>
                </aside>
            </div>
        `;

        configurarEventosBarra();
        estado.montado = true;
        cargarDatosGrafo();
    }

    function configurarEventosBarra() {
        // 1. Búsqueda instantánea en tiempo real (<5ms)
        const inputB = $('mag-input-busqueda');
        if (inputB) {
            inputB.oninput = () => {
                estado.queryBusqueda = inputB.value.trim().toLowerCase();
                renderizarGrafo();
            };
        }

        // 2. Filtros de nivel pedagógico
        const fContainer = $('mag-filtros-nivel');
        if (fContainer) {
            fContainer.onclick = (e) => {
                const btn = e.target.closest('[data-nivel]');
                if (!btn) return;
                estado.filtroNivel = btn.dataset.nivel;
                fContainer.querySelectorAll('.mag-btn-filtro').forEach(b => b.classList.toggle('activo', b === btn));
                renderizarGrafo();
            };
        }

        // 3. Botón recargar
        const btnR = $('mag-btn-recargar');
        if (btnR) {
            btnR.onclick = () => cargarDatosGrafo(true);
        }
    }

    // =========================================================================
    // CARGA DE DATOS DE LA API
    // =========================================================================

    async function cargarDatosGrafo(forzar = false) {
        try {
            estado.cargando = true;
            const res = await json('/api/aprendizaje/grafo');
            if (res && res.ok) {
                estado.datosGrafo = res;
                estado.nodos = res.nodos || [];
                estado.aristas = res.aristas || [];

                // Optimización física del grafo con Barnes-Hut en Rust WASM (O(N log N))
                if (window.motorGraficoFachada && typeof window.motorGraficoFachada.calcularLayoutGrafoBarnesHut === 'function') {
                    try {
                        const nodosOpt = window.motorGraficoFachada.calcularLayoutGrafoBarnesHut(estado.nodos, estado.aristas);
                        if (nodosOpt && nodosOpt.length === estado.nodos.length) {
                            estado.nodos = nodosOpt;
                        }
                    } catch (eLayout) {
                        // Fallback transparente al layout de cuadrícula estándar
                    }
                }

                actualizarStats(res.progreso_global);
                renderizarGrafo();

                // Si no hay nodo activo seleccionado, elegir el primero sugerido
                if (!estado.nodoActivoId && estado.nodos.length > 0) {
                    seleccionarNodo(estado.nodos[0].id);
                } else if (estado.nodoActivoId) {
                    // Refrescar el nodo activo
                    const actualizado = estado.nodos.find(n => n.id === estado.nodoActivoId);
                    if (actualizado) seleccionarNodo(actualizado.id);
                }
            }
        } catch (e) {
            console.error('Error cargando grafo de aprendizaje:', e);
        } finally {
            estado.cargando = false;
        }
    }

    function actualizarStats(stats) {
        if (!stats) return;
        const fill = $('mag-progreso-fill');
        const txt = $('mag-progreso-txt');
        if (fill) fill.style.width = `${stats.porcentaje || 0}%`;
        if (txt) txt.textContent = `${stats.porcentaje || 0}% (${stats.completados}/${stats.total_nodos})`;
    }

    // =========================================================================
    // RENDERIZADO DEL GRAFO Y LÍNEAS DE CONEXIÓN
    // =========================================================================

    function renderizarGrafo() {
        const grid = $('mag-grafo-grid');
        if (!grid) return;

        // Filtrar nodos por nivel y búsqueda
        const nodosVisibles = estado.nodos.filter(n => {
            if (estado.filtroNivel !== 'todos' && n.nivel !== estado.filtroNivel) return false;
            if (estado.queryBusqueda) {
                const q = estado.queryBusqueda;
                const matchTitulo = (n.titulo || '').toLowerCase().includes(q);
                const matchId = (n.id || '').toLowerCase().includes(q);
                const matchEtapa = (n.etapa || '').toLowerCase().includes(q);
                const matchCarrera = (n.carrera_referencia || '').toLowerCase().includes(q);
                return matchTitulo || matchId || matchEtapa || matchCarrera;
            }
            return true;
        });

        // Agrupar en 4 columnas por nivel
        const niveles = [
            { id: 'junior', titulo: 'Junior · Fundamentos' },
            { id: 'intermedio', titulo: 'Intermedio · Estructuras' },
            { id: 'avanzado', titulo: 'Avanzado · ML Supervisado' },
            { id: 'senior', titulo: 'Senior · IA y Transformers' }
        ];

        let html = '';
        for (const lvl of niveles) {
            const nodosDelNivel = nodosVisibles.filter(n => n.nivel === lvl.id);
            const estiloLvl = COLORES_NIVEL[lvl.id] || COLORES_NIVEL.junior;

            html += `
                <div class="mag-columna-nivel" data-nivel="${lvl.id}">
                    <div class="mag-columna-header" style="background:${estiloLvl.fondo}; color:${estiloLvl.texto}; border-color:${estiloLvl.borde};">
                        ${lvl.titulo}
                    </div>
                    ${nodosDelNivel.map(n => renderizarNodoCard(n)).join('')}
                    ${nodosDelNivel.length === 0 ? `<div style="text-align:center; padding:20px; font-size:11px; color:var(--text-muted);">Sin nodos visibles</div>` : ''}
                </div>
            `;
        }

        grid.innerHTML = html;

        // Configurar clics en tarjetas de nodo
        grid.querySelectorAll('.mag-nodo-card').forEach(card => {
            card.onclick = () => seleccionarNodo(card.dataset.id);
        });

        // Dibujar curvas de conexión después de que el DOM se haya posicionado
        requestAnimationFrame(() => dibujarAristas());
    }

    function renderizarNodoCard(n) {
        const estiloLvl = COLORES_NIVEL[n.nivel] || COLORES_NIVEL.junior;
        const esActivo = (n.id === estado.nodoActivoId);
        const esCompletado = !!n.completado;

        return `
            <div class="mag-nodo-card ${esActivo ? 'activo' : ''} ${esCompletado ? 'completado' : ''}" 
                 id="nodo-card-${n.id}" 
                 data-id="${n.id}">
                <div class="mag-nodo-cabecera">
                    <div class="mag-nodo-icono" style="background:${estiloLvl.fondo}; color:${estiloLvl.texto}; border:1px solid ${estiloLvl.borde};">
                        <i class="${n.icono || 'fa-solid fa-code'}"></i>
                    </div>
                    <div style="flex:1; min-width:0;">
                        <div class="mag-nodo-titulo">${esc(n.titulo)}</div>
                        <span class="mag-nodo-etapa">${esc(n.carrera_referencia || '')}</span>
                    </div>
                </div>
                <div class="mag-nodo-pilares">
                    <span class="mag-pilar-badge mag-pilar-yt" title="YouTube"><i class="fa-brands fa-youtube"></i> Video</span>
                    <span class="mag-pilar-badge mag-pilar-gh" title="GitHub"><i class="fa-brands fa-github"></i> Repo</span>
                    <span class="mag-pilar-badge mag-pilar-kg" title="Kaggle"><i class="fa-brands fa-kaggle"></i> Data</span>
                    <span class="mag-pilar-badge mag-pilar-hub" title="Prig Hub"><i class="fa-solid fa-circle-nodes"></i> Hub</span>
                </div>
            </div>
        `;
    }

    function dibujarAristas() {
        const svg = $('mag-svg-aristas');
        const lienzo = $('mag-lienzo-wrap');
        if (!svg || !lienzo) return;

        svg.innerHTML = '';
        const lienzoRect = lienzo.getBoundingClientRect();

        // Ajustar dimensiones del SVG al contenedor scrollable
        svg.setAttribute('width', Math.max(lienzo.scrollWidth, 2000));
        svg.setAttribute('height', Math.max(lienzo.scrollHeight, 2000));

        for (const arista of estado.aristas) {
            const elDesde = $(`nodo-card-${arista.desde}`);
            const elHacia = $(`nodo-card-${arista.hacia}`);
            if (!elDesde || !elHacia) continue;

            const r1 = elDesde.getBoundingClientRect();
            const r2 = elHacia.getBoundingClientRect();

            // Coordenadas relativas al lienzo scrollable
            const x1 = r1.right - lienzoRect.left + lienzo.scrollLeft;
            const y1 = r1.top + r1.height / 2 - lienzoRect.top + lienzo.scrollTop;

            const x2 = r2.left - lienzoRect.left + lienzo.scrollLeft;
            const y2 = r2.top + r2.height / 2 - lienzoRect.top + lienzo.scrollTop;

            const dx = Math.max(40, (x2 - x1) / 2);
            const d = `M ${x1} ${y1} C ${x1 + dx} ${y1}, ${x2 - dx} ${y2}, ${x2} ${y2}`;

            const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
            path.setAttribute('d', d);
            path.setAttribute('fill', 'none');
            path.setAttribute('stroke', arista.completada ? '#a6e3a1' : 'rgba(203,166,247,0.3)');
            path.setAttribute('stroke-width', arista.completada ? '2.5' : '1.8');
            path.setAttribute('stroke-dasharray', arista.completada ? 'none' : '4,4');

            svg.appendChild(path);
        }
    }

    // =========================================================================
    // SELECCIÓN E INSPECTOR DEL NODO
    // =========================================================================

    async function seleccionarNodo(nodoId) {
        estado.nodoActivoId = nodoId;
        estado.mostrarSolucion = false;
        estado.resultadoTest = null;
        estado.pistasAbiertas = {};

        // Actualizar clase activa en cards
        document.querySelectorAll('.mag-nodo-card').forEach(c => {
            c.classList.toggle('activo', c.dataset.id === nodoId);
        });

        // Buscar en memoria para actualización inmediata (<2ms)
        let n = estado.nodos.find(item => item.id === nodoId);
        if (n) {
            estado.nodoActivo = n;
            estado.codigoEditor = (n.tarea_prerespondida && n.tarea_prerespondida.codigo_inicial) || '';
            renderizarInspector();
        }

        // Consultar detalle completo
        try {
            const res = await json(`/api/aprendizaje/nodo/${nodoId}`);
            if (res && res.ok && res.nodo) {
                estado.nodoActivo = res.nodo;
                if (!estado.codigoEditor) {
                    estado.codigoEditor = (res.nodo.tarea_prerespondida && res.nodo.tarea_prerespondida.codigo_inicial) || '';
                }
                renderizarInspector();
            }
        } catch (e) {
            console.error('Error cargando detalle del nodo:', e);
        }
    }

    function renderizarInspector() {
        const panel = $('mag-inspector');
        const n = estado.nodoActivo;
        if (!panel || !n) return;

        const estiloLvl = COLORES_NIVEL[n.nivel] || COLORES_NIVEL.junior;
        const mt = n.marco_teorico || {};
        const herrs = n.herramientas || {};
        const tarea = n.tarea_prerespondida || {};

        panel.innerHTML = `
            <div class="mag-inspector-header">
                <div class="mag-inspector-titulo-fila">
                    <span class="mag-inspector-titulo">${esc(n.titulo)}</span>
                    <span class="mag-pilar-badge" style="background:${estiloLvl.fondo}; color:${estiloLvl.texto}; border:1px solid ${estiloLvl.borde};">
                        ${n.nivel.toUpperCase()}
                    </span>
                </div>
                <div style="font-size:11px; color:var(--text-muted); margin-bottom:10px;">
                    <i class="fa-solid fa-graduation-cap"></i> ${esc(n.carrera_referencia || '')} · ${esc(n.etapa || '')}
                </div>

                <div class="mag-inspector-acciones-rapidas">
                    <button class="mag-btn-accion primario" id="mag-btn-abrir-editor" title="Abrir y resolver en el Editor Prig">
                        <i class="fa-solid fa-code"></i> Abrir en Editor Prig
                    </button>
                    <button class="mag-btn-accion ${n.completado ? 'exito' : 'neutro'}" id="mag-btn-toggle-progreso" title="Marcar como completado">
                        <i class="fa-solid ${n.completado ? 'fa-circle-check' : 'fa-circle'}"></i> 
                        ${n.completado ? 'Completado' : 'Marcar Hecho'}
                    </button>
                </div>
            </div>

            <div class="mag-inspector-tabs">
                <button class="mag-inspector-tab-btn ${estado.pestanaDetalle === 'teoria' ? 'activo' : ''}" data-tab="teoria">
                    <i class="fa-solid fa-book-open"></i> Marco Teórico
                </button>
                <button class="mag-inspector-tab-btn ${estado.pestanaDetalle === 'herramientas' ? 'activo' : ''}" data-tab="herramientas">
                    <i class="fa-solid fa-toolbox"></i> 4 Herramientas Prig
                </button>
                <button class="mag-inspector-tab-btn ${estado.pestanaDetalle === 'desafio' ? 'activo' : ''}" data-tab="desafio">
                    <i class="fa-solid fa-vial-circle-check"></i> Tarea & Desafío
                </button>
            </div>

            <div class="mag-inspector-contenido" id="mag-inspector-tab-body">
                ${renderizarCuerpoPestana(n)}
            </div>
        `;

        configurarEventosInspector(n);
    }

    function renderizarCuerpoPestana(n) {
        if (estado.pestanaDetalle === 'teoria') {
            return renderizarTabTeoria(n);
        } else if (estado.pestanaDetalle === 'herramientas') {
            return renderizarTabHerramientas(n);
        } else {
            return renderizarTabDesafio(n);
        }
    }

    // -------------------------------------------------------------------------
    // TAB 1: MARCO TEÓRICO FORMAL
    // -------------------------------------------------------------------------
    function renderizarTabTeoria(n) {
        const mt = n.marco_teorico || {};
        return `
            <div class="mag-card-teoria">
                <h4><i class="fa-solid fa-brain"></i> Fundamento Conceptual</h4>
                <p>${esc(mt.resumen || 'Sin resumen conceptual registrado.')}</p>
            </div>

            <div class="mag-card-teoria">
                <h4><i class="fa-solid fa-list-check"></i> Principios Nucleares</h4>
                <ul class="mag-principios-lista">
                    ${(mt.principios_nucleares || []).map(p => `<li>${esc(p)}</li>`).join('')}
                </ul>
            </div>

            ${(mt.definiciones_formales && mt.definiciones_formales.length > 0) ? `
                <div class="mag-card-teoria">
                    <h4><i class="fa-solid fa-spell-check"></i> Definiciones Formales</h4>
                    <div style="display:flex; flex-direction:column; gap:8px;">
                        ${mt.definiciones_formales.map(df => `
                            <div>
                                <b style="color:#89b4fa; font-size:11.5px;">${esc(df.termino)}:</b>
                                <span style="font-size:11.5px; color:#cdd6f4;"> ${esc(df.definicion)}</span>
                            </div>
                        `).join('')}
                    </div>
                </div>
            ` : ''}

            ${mt.formulas_o_axiomas ? `
                <div class="mag-card-teoria">
                    <h4><i class="fa-solid fa-square-root-variable"></i> Fórmulas y Fundamento Matemático</h4>
                    <div class="mag-formula-box">${esc(mt.formulas_o_axiomas)}</div>
                </div>
            ` : ''}
        `;
    }

    // -------------------------------------------------------------------------
    // TAB 2: LAS 4 HERRAMIENTAS PRIG (YouTube, GitHub, Kaggle, Prig Hub)
    // -------------------------------------------------------------------------
    function renderizarTabHerramientas(n) {
        const herrs = n.herramientas || {};
        const yt = herrs.youtube || {};
        const gh = herrs.github || {};
        const kg = herrs.kaggle || {};
        const hub = herrs.prig_hub || {};

        return `
            <!-- 1. YOUTUBE -->
            <div class="mag-herramienta-card">
                <div class="mag-herramienta-card-header">
                    <span class="mag-herramienta-titulo">
                        <i class="fa-brands fa-youtube" style="color:#ff3333;"></i> YouTube · Clase Magistral
                    </span>
                    <button class="mag-btn-accion neutro" id="mag-btn-ir-yt" style="padding:4px 8px; font-size:10.5px;">
                        <i class="fa-solid fa-play"></i> Reproducir en YouTube
                    </button>
                </div>
                <div style="font-size:12px; font-weight:600; color:#fff; margin-bottom:4px;">${esc(yt.titulo || '')}</div>
                <div style="font-size:11px; color:var(--text-muted); margin-bottom:8px;">
                    <i class="fa-solid fa-user-tie"></i> ${esc(yt.canal || '')} · Duración: ${esc(yt.duracion || '')}
                </div>
                ${(yt.marcas_de_tiempo && yt.marcas_de_tiempo.length > 0) ? `
                    <div style="background:rgba(0,0,0,0.2); border-radius:6px; padding:6px 10px;">
                        <span style="font-size:10.5px; font-weight:700; color:#cba6f7;">Marcas pedagógicas clave:</span>
                        <div style="display:flex; flex-direction:column; gap:4px; margin-top:4px;">
                            ${yt.marcas_de_tiempo.map(m => `
                                <div style="display:flex; justify-content:space-between; font-size:11px;">
                                    <span style="color:#cdd6f4;">${esc(m.tema)}</span>
                                    <span style="color:#89b4fa; font-family:'Fira Code',monospace; cursor:pointer;" class="mag-ts-link" data-minuto="${esc(m.minuto)}">${esc(m.minuto)}</span>
                                </div>
                            `).join('')}
                        </div>
                    </div>
                ` : ''}
            </div>

            <!-- 2. GITHUB -->
            <div class="mag-herramienta-card">
                <div class="mag-herramienta-card-header">
                    <span class="mag-herramienta-titulo">
                        <i class="fa-brands fa-github" style="color:#58a6ff;"></i> GitHub · Repositorio & Código Real
                    </span>
                    <button class="mag-btn-accion neutro" id="mag-btn-ir-gh" style="padding:4px 8px; font-size:10.5px;">
                        <i class="fa-brands fa-github"></i> Abrir en GitHub Lector
                    </button>
                </div>
                <div style="font-size:12px; font-weight:600; color:#58a6ff; margin-bottom:4px;">${esc(gh.repositorio || '')}</div>
                <div style="font-size:11.5px; color:#cdd6f4; margin-bottom:6px;">${esc(gh.descripcion || '')}</div>
                <div style="font-size:10.5px; font-family:'Fira Code',monospace; color:var(--text-muted);">
                    Ruta: ${esc(gh.ruta_archivos || '')}
                </div>
            </div>

            <!-- 3. KAGGLE -->
            <div class="mag-herramienta-card">
                <div class="mag-herramienta-card-header">
                    <span class="mag-herramienta-titulo">
                        <i class="fa-brands fa-kaggle" style="color:#20beff;"></i> Kaggle · Dataset & Pipelines de Datos
                    </span>
                    <button class="mag-btn-accion neutro" id="mag-btn-ir-kg" style="padding:4px 8px; font-size:10.5px;">
                        <i class="fa-brands fa-kaggle"></i> Explorar en Kaggle
                    </button>
                </div>
                <div style="font-size:12px; font-weight:600; color:#fff; margin-bottom:4px;">${esc(kg.titulo || '')}</div>
                <div style="font-size:11.5px; color:#cdd6f4; margin-bottom:6px;">${esc(kg.tarea_datos || '')}</div>
                <div style="font-size:10.5px; font-family:'Fira Code',monospace; color:var(--text-muted);">
                    Dataset: ${esc(kg.dataset_slug || '')}
                </div>
            </div>

            <!-- 4. PRIG HUB -->
            <div class="mag-herramienta-card">
                <div class="mag-herramienta-card-header">
                    <span class="mag-herramienta-titulo">
                        <i class="fa-solid fa-circle-nodes" style="color:#cba6f7;"></i> Prig Hub · Paquete Curricular
                    </span>
                    <button class="mag-btn-accion neutro" id="mag-btn-ir-hub" style="padding:4px 8px; font-size:10.5px;">
                        <i class="fa-solid fa-circle-nodes"></i> Ver en Prig Hub
                    </button>
                </div>
                <div style="font-size:11.5px; color:#cdd6f4;">
                    Paquete asociado: <b style="color:#cba6f7;">${esc(hub.pack_id || '')}</b>
                </div>
                <div style="font-size:10.5px; color:var(--text-muted); margin-top:4px;">
                    Ruta en documentación: ${esc(hub.ruta_guia || '')}
                </div>
            </div>
        `;
    }

    // -------------------------------------------------------------------------
    // TAB 3: TAREA PRE-RESPONDIDA Y EJECUTOR DE PRUEBAS
    // -------------------------------------------------------------------------
    function renderizarTabDesafio(n) {
        const tarea = n.tarea_prerespondida || {};
        const res = estado.resultadoTest;

        return `
            <div class="mag-desafio-box">
                <div class="mag-desafio-enunciado">
                    <b style="color:#cba6f7; display:block; margin-bottom:4px;">
                        <i class="fa-solid fa-bullseye"></i> ${esc(tarea.titulo || 'Desafío Práctico')}
                    </b>
                    ${esc(tarea.enunciado || '')}
                </div>

                <textarea class="mag-editor-codigo-tarea" id="mag-editor-tarea" spellcheck="false" placeholder="Escribe tu solución aquí...">${esc(estado.codigoEditor)}</textarea>

                <div style="display:flex; align-items:center; justify-content:space-between; padding:8px 12px; background:rgba(0,0,0,0.25); border-top:1px solid var(--border-color, #313244);">
                    <div style="display:flex; gap:8px;">
                        <button class="mag-btn-accion primario" id="mag-btn-probar-codigo" ${estado.ejecutandoTest ? 'disabled' : ''}>
                            <i class="fa-solid ${estado.ejecutandoTest ? 'fa-spinner fa-spin' : 'fa-play'}"></i> 
                            ${estado.ejecutandoTest ? 'Ejecutando...' : 'Ejecutar Pruebas'}
                        </button>
                        <button class="mag-btn-accion neutro" id="mag-btn-restablecer-codigo" title="Restablecer código inicial">
                            <i class="fa-solid fa-rotate-left"></i> Restablecer
                        </button>
                    </div>
                    <button class="mag-btn-accion neutro" id="mag-btn-toggle-solucion" style="border-color:rgba(203,166,247,0.3); color:#cba6f7;">
                        <i class="fa-solid ${estado.mostrarSolucion ? 'fa-eye-slash' : 'fa-lightbulb'}"></i> 
                        ${estado.mostrarSolucion ? 'Ocultar Solución' : 'Ver Solución Pre-respondida'}
                    </button>
                </div>

                ${res ? `
                    <div class="mag-consola-salida ${res.ok ? 'exito' : 'error'}">
                        <div><b>${res.ok ? '✓ PRUEBAS SUPERADAS' : '✗ FALLO EN PRUEBAS'}</b> (${res.tiempo_ms || 0} ms)</div>
                        ${res.salida ? `<div style="margin-top:4px;">${esc(res.salida)}</div>` : ''}
                        ${res.error ? `<div style="margin-top:4px; color:#f38ba8;">${esc(res.error)}</div>` : ''}
                    </div>
                ` : ''}
            </div>

            <!-- Pistas Progresivas -->
            ${(tarea.pistas_progresivas && tarea.pistas_progresivas.length > 0) ? `
                <div style="margin-bottom:14px;">
                    <div style="font-size:11.5px; font-weight:700; color:#f9e2af; margin-bottom:6px;">
                        <i class="fa-solid fa-wand-magic-sparkles"></i> Pistas Progresivas:
                    </div>
                    <div style="display:flex; flex-direction:column; gap:6px;">
                        ${tarea.pistas_progresivas.map((p, idx) => `
                            <details style="background:rgba(255,255,255,0.03); border:1px solid rgba(255,255,255,0.07); border-radius:6px; padding:6px 10px; font-size:11.5px;">
                                <summary style="cursor:pointer; color:#89b4fa; font-weight:600;">Pista ${idx + 1}</summary>
                                <p style="margin:6px 0 0 0; color:#cdd6f4;">${esc(p)}</p>
                            </details>
                        `).join('')}
                    </div>
                </div>
            ` : ''}

            <!-- Solución Pre-respondida Desplegable -->
            ${estado.mostrarSolucion ? `
                <div class="mag-solucion-desplegable">
                    <div style="display:flex; align-items:center; justify-content:space-between; margin-bottom:8px;">
                        <span style="font-size:12px; font-weight:700; color:#a6e3a1;">
                            <i class="fa-solid fa-code-check"></i> Solución Pre-respondida de Referencia
                        </span>
                        <button class="mag-btn-accion exito" id="mag-btn-probar-solucion" style="padding:2px 8px; font-size:10.5px;">
                            Probar esta solución
                        </button>
                    </div>
                    <pre style="background:#09090f; padding:10px; border-radius:6px; font-family:'Fira Code',monospace; font-size:11.5px; color:#a6e3a1; overflow-x:auto; margin:0 0 10px 0;"><code>${esc(tarea.solucion_referencia || '')}</code></pre>

                    ${(tarea.guia_resolucion_paso_a_paso && tarea.guia_resolucion_paso_a_paso.length > 0) ? `
                        <div style="font-size:11.5px; font-weight:700; color:#cba6f7; margin-bottom:6px;">
                            Guía de Resolución Paso a Paso:
                        </div>
                        <ol style="margin:0; padding-left:18px; font-size:11.5px; color:#cdd6f4; display:flex; flex-direction:column; gap:4px;">
                            ${tarea.guia_resolucion_paso_a_paso.map(g => `<li>${esc(g)}</li>`).join('')}
                        </ol>
                    ` : ''}
                </div>
            ` : ''}
        `;
    }

    // =========================================================================
    // EVENTOS Y ACCIONES DEL INSPECTOR
    // =========================================================================

    function configurarEventosInspector(n) {
        const panel = $('mag-inspector');
        if (!panel) return;

        // 1. Cambio de pestaña
        panel.querySelectorAll('.mag-inspector-tab-btn').forEach(btn => {
            btn.onclick = () => {
                estado.pestanaDetalle = btn.dataset.tab;
                panel.querySelectorAll('.mag-inspector-tab-btn').forEach(b => b.classList.toggle('activo', b === btn));
                const body = $('mag-inspector-tab-body');
                if (body) {
                    body.innerHTML = renderizarCuerpoPestana(n);
                    configurarEventosInspector(n);
                }
            };
        });

        // 2. Abrir en Editor Prig
        const btnAbrirEditor = $('mag-btn-abrir-editor');
        if (btnAbrirEditor) {
            btnAbrirEditor.onclick = async () => {
                try {
                    btnAbrirEditor.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Abriendo...';
                    btnAbrirEditor.disabled = true;
                    const res = await enviar(`/api/aprendizaje/nodo/${n.id}/abrir_en_editor`, {});
                    if (res && res.ok) {
                        // Refrescar el árbol de archivos en el explorador
                        if (window.fileTreeMgr && typeof window.fileTreeMgr.recargar === 'function') {
                            window.fileTreeMgr.recargar();
                        }
                        // Abrir archivo de ejercicio en el editor Prig
                        if (window.editorMgr && typeof window.editorMgr.openFileByPath === 'function') {
                            await window.editorMgr.openFileByPath(res.archivo_principal);
                        }
                        // Opcional: Cerrar herramienta o notificar
                        if (window.workArea && typeof window.workArea.cerrar === 'function') {
                            // Minimizar o cambiar vista
                        }
                    }
                } catch (e) {
                    alert('Error al abrir ejercicio en el Editor Prig: ' + e.message);
                } finally {
                    btnAbrirEditor.innerHTML = '<i class="fa-solid fa-code"></i> Abrir en Editor Prig';
                    btnAbrirEditor.disabled = false;
                }
            };
        }

        // 3. Marcar completado
        const btnToggleProgreso = $('mag-btn-toggle-progreso');
        if (btnToggleProgreso) {
            btnToggleProgreso.onclick = async () => {
                const nuevoEstado = !n.completado;
                try {
                    await enviar(`/api/aprendizaje/nodo/${n.id}/progreso`, { completado: nuevoEstado });
                    n.completado = nuevoEstado;
                    cargarDatosGrafo();
                } catch (e) {
                    console.error('Error actualizando progreso:', e);
                }
            };
        }

        // 4. Puentes hacia las 4 herramientas
        const herrs = n.herramientas || {};

        // YouTube
        const btnIrYt = $('mag-btn-ir-yt');
        if (btnIrYt) {
            btnIrYt.onclick = () => {
                const yt = herrs.youtube || {};
                if (window.YouTubeHub && typeof window.YouTubeHub.abrir === 'function') {
                    window.YouTubeHub.abrir();
                    if (yt.video_id) {
                        window.YouTubeHub.reproducir({ id: yt.video_id, titulo: yt.titulo, canal: yt.canal });
                    }
                }
            };
        }

        // Clic en marcas de tiempo específicas de YouTube
        panel.querySelectorAll('.mag-ts-link').forEach(el => {
            el.onclick = () => {
                const minutoStr = el.dataset.minuto || '00:00';
                const partes = minutoStr.split(':').map(Number);
                let segs = 0;
                if (partes.length === 3) segs = partes[0] * 3600 + partes[1] * 60 + partes[2];
                else if (partes.length === 2) segs = partes[0] * 60 + partes[1];

                const yt = herrs.youtube || {};
                if (window.YouTubeHub && typeof window.YouTubeHub.abrir === 'function') {
                    window.YouTubeHub.abrir();
                    if (yt.video_id) {
                        window.YouTubeHub.reproducir({ id: yt.video_id, titulo: yt.titulo, canal: yt.canal });
                        setTimeout(() => {
                            if (typeof window.YouTubeHub.saltarAMinuto === 'function') {
                                window.YouTubeHub.saltarAMinuto(segs);
                            }
                        }, 500);
                    }
                }
            };
        });

        // GitHub
        const btnIrGh = $('mag-btn-ir-gh');
        if (btnIrGh) {
            btnIrGh.onclick = () => {
                const gh = herrs.github || {};
                if (window.GitHubLector && typeof window.GitHubLector.abrir === 'function') {
                    window.GitHubLector.abrir({ ref: gh.repositorio });
                }
            };
        }

        // Kaggle
        const btnIrKg = $('mag-btn-ir-kg');
        if (btnIrKg) {
            btnIrKg.onclick = () => {
                const kg = herrs.kaggle || {};
                if (window.KaggleLector && typeof window.KaggleLector.abrir === 'function') {
                    window.KaggleLector.abrir({ tipo: 'dataset', ref: kg.dataset_slug });
                }
            };
        }

        // Prig Hub
        const btnIrHub = $('mag-btn-ir-hub');
        if (btnIrHub) {
            btnIrHub.onclick = () => {
                if (window.PrigHub && typeof window.PrigHub.abrir === 'function') {
                    window.PrigHub.abrir();
                }
            };
        }

        // 5. Acciones del Desafío y Runner
        const editorTextarea = $('mag-editor-tarea');
        if (editorTextarea) {
            editorTextarea.oninput = () => {
                estado.codigoEditor = editorTextarea.value;
            };
        }

        const btnProbar = $('mag-btn-probar-codigo');
        if (btnProbar) {
            btnProbar.onclick = async () => {
                await ejecutarPruebasNodo(n.id, estado.codigoEditor, false);
            };
        }

        const btnRestablecer = $('mag-btn-restablecer-codigo');
        if (btnRestablecer) {
            btnRestablecer.onclick = () => {
                const ini = (n.tarea_prerespondida && n.tarea_prerespondida.codigo_inicial) || '';
                estado.codigoEditor = ini;
                if (editorTextarea) editorTextarea.value = ini;
            };
        }

        const btnToggleSol = $('mag-btn-toggle-solucion');
        if (btnToggleSol) {
            btnToggleSol.onclick = () => {
                estado.mostrarSolucion = !estado.mostrarSolucion;
                const body = $('mag-inspector-tab-body');
                if (body) {
                    body.innerHTML = renderizarCuerpoPestana(n);
                    configurarEventosInspector(n);
                }
            };
        }

        const btnProbarSol = $('mag-btn-probar-solucion');
        if (btnProbarSol) {
            btnProbarSol.onclick = async () => {
                await ejecutarPruebasNodo(n.id, '', true);
            };
        }
    }

    async function ejecutarPruebasNodo(nodoId, codigo, usarSolucion) {
        try {
            estado.ejecutandoTest = true;
            renderizarInspector();

            const res = await enviar(`/api/aprendizaje/nodo/${nodoId}/ejecutar`, {
                codigo: codigo || '',
                usar_solucion: usarSolucion
            });

            estado.resultadoTest = res;
            if (res && res.ok && !usarSolucion) {
                // Marcar completado en el estado local
                if (estado.nodoActivo) estado.nodoActivo.completado = true;
                cargarDatosGrafo();
            }
        } catch (e) {
            estado.resultadoTest = { ok: false, error: e.message, tiempo_ms: 0 };
        } finally {
            estado.ejecutandoTest = false;
            renderizarInspector();
        }
    }

    // =========================================================================
    // API PÚBLICA DE APERTURA Y CONTROL
    // =========================================================================

    function abrir(opciones = {}) {
        if (window.workArea && typeof window.workArea.abrirHerramienta === 'function') {
            window.workArea.abrirHerramienta('modal-aprendizaje-grafo', 'Grafo de Aprendizaje', 'fa-solid fa-diagram-project');
        } else {
            const m = $('modal-aprendizaje-grafo');
            if (m) m.style.display = 'flex';
        }
        montar();

        if (opciones.nodoId) {
            setTimeout(() => seleccionarNodo(opciones.nodoId), 50);
        } else if (opciones.query) {
            setTimeout(() => {
                const inputB = $('mag-input-busqueda');
                if (inputB) {
                    inputB.value = opciones.query;
                    estado.queryBusqueda = opciones.query.toLowerCase();
                    renderizarGrafo();
                }
            }, 50);
        }
    }

    document.addEventListener('prig:herramienta-abierta', (e) => {
        if (e.detail && e.detail.modalId === 'modal-aprendizaje-grafo') {
            montar();
            if (!estado.datosGrafo) cargarDatosGrafo();
        }
    });

    window.MotorAprendizajeGrafo = {
        abrir,
        seleccionarNodo,
        abrirConBusqueda: (q) => abrir({ query: q }),
        estado,
        recargar: () => cargarDatosGrafo(true)
    };
})();

