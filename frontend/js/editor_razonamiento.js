/**
 * ============================================================================
 * MOTOR DE RAZONAMIENTO, NOTAS Y RELACIÓN VISUAL DEL EDITOR (PRIG IDE)
 * ============================================================================
 * - Panel lateral derecho fijado (25% de ancho, 100% de altura, estilo minimapa ampliado).
 * - Muestra el proceso de pensamiento (Chain of Thought), diagnóstico y lógica de ejecución.
 * - Conecta con el código mediante corchetes grandes de rango multilínea y flechas curvas SVG.
 * - Gestiona notas técnicas profesionales guardadas por archivo con saltos directos a línea.
 * - Mantiene al personaje interactivo discretamente de fondo, colocando la interfaz
 *   inteligente nítida en el frente.
 */

(function(root) {
    'use strict';

    class EditorRazonamientoManager {
        constructor() {
            this.activo = true;
            this.panelVisible = true;
            this.tabActiva = 'razonamiento'; // 'razonamiento' | 'notas'
            this.relacionVisualActiva = true;

            this.anchoPorcentaje = 25; // 25% de ancho por defecto
            this.archivoActivo = 'main.py';
            this.lineaCursor = 1;

            // Datos de Razonamiento del Modelo
            this.razonamiento = {
                modelo: 'qwen2.5-coder:7b',
                estado: 'listo', // 'listo' | 'pensando' | 'pausado'
                tiempoCoT: '1.4s',
                tokSeg: '44 tok/s',
                cotExpandido: true,
                cotPasos: [
                    { num: 1, titulo: 'Análisis de Árbol Sintáctico (AST)', detalle: 'Estructura modular verificada; no se detectan bucles infinitos no acotados.' },
                    { num: 2, titulo: 'Inferencia de Control de Flujo y Casos Borde', detalle: 'Evaluación de ramas condicionales; precondición en L12 carece de cláusula de guarda.' },
                    { num: 3, titulo: 'Evaluación de Complejidad Temporal y Espacial', detalle: 'Costo asintótico global estimado en O(N) con consumo de memoria amortizado estable.' }
                ],
                dialogoTexto: 'He analizado el código fuente. Se recomienda estructurar una cláusula de guarda temprana en el encabezado de la función para descartar parámetros nulos y reducir la profundidad de anidación.',
                hallazgos: [
                    {
                        id: 'h1',
                        categoria: 'arq',
                        categoriaTexto: 'Arquitectura',
                        lineaInicio: 12,
                        lineaFin: 28,
                        titulo: 'Cláusula de Guarda y Validación Temprana',
                        detalle: 'El bloque de procesamiento central asume argumentos no nulos. Aislar la validación en el inicio simplifica el flujo de datos.',
                        codigoSugerido: 'if not payload or not isinstance(payload, dict):\n    return {"error": "payload_invalido", "ok": False}',
                        color: '#89b4fa'
                    },
                    {
                        id: 'h2',
                        categoria: 'opt',
                        categoriaTexto: 'Optimización',
                        lineaInicio: 34,
                        lineaFin: 42,
                        titulo: 'Búsqueda e Indexación de Conjuntos O(1)',
                        detalle: 'La comprobación secuencial en listas dentro del bucle añade costo O(N*M). Un conjunto hash reduce la latencia a tiempo constante.',
                        codigoSugerido: 'claves_permitidas = set(configuracion.keys())\nitems_filtrados = [k for k in items if k in claves_permitidas]',
                        color: '#f9e2af'
                    }
                ],
                grafoNodos: [
                    { id: 'n1', nombre: 'ENTRY: main()', linea: 1, sub: 'Inicialización de contexto' },
                    { id: 'n2', nombre: 'VALIDAR: argumentos', linea: 12, sub: 'Cláusula de guarda y tipo' },
                    { id: 'n3', nombre: 'PROCESO: transformación', linea: 34, sub: 'Normalización de datos' },
                    { id: 'n4', nombre: 'RETURN: resultado seguro', linea: 48, sub: 'Respuesta estructurada' }
                ],
                metricas: {
                    complejidad: 'O(N)',
                    calidad: '96%',
                    modularidad: '94%',
                    guardas: '100%'
                }
            };

            // Notas Técnicas por Archivo (Persistidas en localStorage)
            this.notasPorArchivo = {};
            this.notaActivaIndex = null;
            this.filtroCategoriaNota = 'todas';

            // Configuración Profesional de Corchetes y Jerarquía
            this.configJerarquia = {
                modoCorchetes: 'jerarquico', // 'jerarquico' (class + def anidados) | 'unitario' (solo bloque activo)
                autoSincronizarCursor: true, // Sincroniza corchetes con la posición del cursor
                arbolExpandido: true         // Expansión del panel de símbolos AST
            };

            // Estructura Jerárquica del Código Parseado (AST)
            this.estructuraCodigo = {
                simbolos: [],        // Lista plana de todos los símbolos
                arbol: [],           // Árbol jerárquico [class -> [def, def], def...]
                simboloActivo: null, // Símbolo actualmente seleccionado
                simboloPadre: null,  // Símbolo contenedor (ej. class)
                caminoJerarquico: [] // [Archivo, Clase, Función/Método]
            };
            this._timerParseo = null;

            // Conectores Activos para el SVG Overlay
            this.conectorFoco = {
                activo: true,
                lineaInicio: 12,
                lineaFin: 28,
                tipo: 'def',
                etiqueta: 'def procesar_datos()',
                firma: 'def procesar_datos(self, payload: dict)',
                color: '#89b4fa',
                elementoOrigenId: null,
                simboloId: null,
                padre: {
                    lineaInicio: 5,
                    lineaFin: 65,
                    tipo: 'class',
                    nombre: 'FlowEngine',
                    etiqueta: 'class FlowEngine',
                    firma: 'class FlowEngine:',
                    totalLineas: 61,
                    color: '#cba6f7'
                }
            };

            // Decoraciones activas en Monaco
            this._decoracionesMonaco = [];
            this._timerRedibujado = null;
            this._iniciado = false;
        }

        init() {
            if (this._iniciado) return;
            this._iniciado = true;

            this._cargarNotasAlmacenadas();
            this._estructurarDOM();
            this._vincularEventos();
            this.renderizar();

            // Sincronizar conectores y enlazar buffer de Monaco cuando esté listo
            this._intentarVincularMonaco();
            setTimeout(() => {
                this.actualizarOverlay();
            }, 600);
        }

        /** Estructura el contenedor del editor dividiéndolo en cuadrícula + panel 25% */
        _estructurarDOM() {
            const vistaEditor = document.getElementById('vista-editor');
            if (!vistaEditor) return;

            const gridContainer = document.getElementById('editor-grid-container');
            if (!gridContainer) return;

            // Si ya existe el wrapper, no volver a crearlo
            let wrapper = document.getElementById('editor-area-wrapper');
            if (!wrapper) {
                wrapper = document.createElement('div');
                wrapper.id = 'editor-area-wrapper';
                wrapper.className = 'editor-area-wrapper';

                // Insertar wrapper después de la barra de layout
                const layoutBar = document.getElementById('editor-layout-bar');
                if (layoutBar && layoutBar.nextSibling) {
                    vistaEditor.insertBefore(wrapper, layoutBar.nextSibling);
                } else {
                    vistaEditor.appendChild(wrapper);
                }

                // Mover gridContainer dentro del wrapper
                wrapper.appendChild(gridContainer);

                // Crear SVG Overlay de Conexiones Visuales
                const svgOverlay = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
                svgOverlay.id = 'editor-overlay-conectores';
                svgOverlay.setAttribute('class', 'editor-overlay-conectores');
                svgOverlay.innerHTML = `
                    <defs>
                        <marker id="flecha-conector-azul" viewBox="0 0 10 10" refX="7" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
                            <path d="M 0 1.5 L 8 5 L 0 8.5 z" fill="#89b4fa" />
                        </marker>
                        <marker id="flecha-conector-verde" viewBox="0 0 10 10" refX="7" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
                            <path d="M 0 1.5 L 8 5 L 0 8.5 z" fill="#a6e3a1" />
                        </marker>
                        <marker id="flecha-conector-morado" viewBox="0 0 10 10" refX="7" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
                            <path d="M 0 1.5 L 8 5 L 0 8.5 z" fill="#cba6f7" />
                        </marker>
                    </defs>
                    <g id="capa-corchetes-codigo"></g>
                    <g id="capa-flechas-codigo"></g>
                    <g id="capa-badges-codigo"></g>
                `;
                wrapper.appendChild(svgOverlay);

                // Crear divisor redimensionable
                const resizer = document.createElement('div');
                resizer.id = 'editor-razonamiento-resizer';
                resizer.className = 'editor-razonamiento-resizer';
                resizer.title = 'Arrastra para ajustar el ancho del panel de razonamiento';
                wrapper.appendChild(resizer);

                // Crear Panel de Razonamiento (25% ancho, 100% altura)
                const panel = document.createElement('aside');
                panel.id = 'editor-panel-razonamiento';
                panel.className = 'editor-panel-razonamiento';
                wrapper.appendChild(panel);
            }

            // Inyectar botones en la barra superior del editor si no existen
            this._inyectarBotonesBarraSuperior();
        }

        _inyectarBotonesBarraSuperior() {
            const accionesBar = document.querySelector('#editor-layout-bar .editor-layout-actions');
            if (!accionesBar) return;

            // Botón "Razonamiento"
            if (!document.getElementById('btn-editor-razonamiento')) {
                const btnRaz = document.createElement('button');
                btnRaz.id = 'btn-editor-razonamiento';
                btnRaz.className = 'btn-editor-hud-secundario activo';
                btnRaz.title = 'Mostrar / Ocultar panel de razonamiento del modelo (25% ancho)';
                btnRaz.style.cssText = 'display: flex; align-items: center; gap: 6px; background: rgba(137, 180, 250, 0.18); border: 1px solid rgba(137, 180, 250, 0.45); color: #89b4fa; border-radius: 6px; padding: 4px 10px; font-size: 12px; font-weight: 700; cursor: pointer; transition: all 0.2s ease;';
                btnRaz.innerHTML = `
                    <i class="fa-solid fa-brain-circuit" style="font-size: 12px;"></i>
                    <span>Razonamiento</span>
                    <span id="badge-razonamiento-estado" style="background: rgba(137, 180, 250, 0.28); color: #89b4fa; font-size: 9.5px; font-weight: 800; padding: 1px 5px; border-radius: 8px;">CoT</span>
                `;
                btnRaz.onclick = () => this.alternarTabOVisibilidad('razonamiento');
                accionesBar.appendChild(btnRaz);
            }

            // Botón "Notas"
            if (!document.getElementById('btn-editor-notas')) {
                const btnNotas = document.createElement('button');
                btnNotas.id = 'btn-editor-notas';
                btnNotas.className = 'btn-editor-hud-secundario';
                btnNotas.title = 'Notas técnicas profesionales y anotaciones sobre el código';
                btnNotas.style.cssText = 'display: flex; align-items: center; gap: 6px; background: rgba(166, 227, 161, 0.14); border: 1px solid rgba(166, 227, 161, 0.4); color: #a6e3a1; border-radius: 6px; padding: 4px 10px; font-size: 12px; font-weight: 700; cursor: pointer; transition: all 0.2s ease;';
                const totalNotas = this._obtenerNotasArchivoActual().length;
                btnNotas.innerHTML = `
                    <i class="fa-solid fa-clipboard-list" style="font-size: 12px;"></i>
                    <span>Notas</span>
                    <span id="badge-notas-contador" style="background: rgba(166, 227, 161, 0.25); color: #a6e3a1; font-size: 9.5px; font-weight: 800; padding: 1px 5px; border-radius: 8px;">${totalNotas}</span>
                `;
                btnNotas.onclick = () => this.alternarTabOVisibilidad('notas');
                accionesBar.appendChild(btnNotas);
            }

            // Botón "Conectores Visuales"
            if (!document.getElementById('btn-editor-relacion-visual')) {
                const btnConectores = document.createElement('button');
                btnConectores.id = 'btn-editor-relacion-visual';
                btnConectores.className = 'btn-editor-hud-secundario activo';
                btnConectores.title = 'Activar / Desactivar corchetes grandes y flechas de conexión sobre el código';
                btnConectores.style.cssText = 'display: flex; align-items: center; gap: 5px; background: rgba(203, 166, 247, 0.14); border: 1px solid rgba(203, 166, 247, 0.35); color: #cba6f7; border-radius: 6px; padding: 4px 9px; font-size: 11.5px; font-weight: 600; cursor: pointer; transition: all 0.2s ease;';
                btnConectores.innerHTML = `
                    <i class="fa-solid fa-diagram-project"></i>
                    <span>Conectores</span>
                `;
                btnConectores.onclick = () => this.alternarConectores();
                accionesBar.appendChild(btnConectores);
            }
        }

        _vincularEventos() {
            // Eventos de arrastre para redimensionar el panel
            const resizer = document.getElementById('editor-razonamiento-resizer');
            if (resizer) {
                let startX = 0;
                let startWidth = 0;
                let arrastrando = false;

                const onMouseMove = (e) => {
                    if (!arrastrando) return;
                    const wrapper = document.getElementById('editor-area-wrapper');
                    if (!wrapper) return;
                    const wrapperWidth = wrapper.getBoundingClientRect().width;
                    const deltaX = startX - e.clientX;
                    const newWidth = Math.max(260, Math.min(wrapperWidth * 0.45, startWidth + deltaX));
                    const newPct = (newWidth / wrapperWidth) * 100;
                    this.anchoPorcentaje = Math.round(newPct);

                    const panel = document.getElementById('editor-panel-razonamiento');
                    if (panel) {
                        panel.style.width = `${this.anchoPorcentaje}%`;
                        panel.style.flex = `0 0 ${this.anchoPorcentaje}%`;
                    }
                    this._refrescarLayoutMonaco();
                    this.actualizarOverlay();
                };

                const onMouseUp = () => {
                    if (arrastrando) {
                        arrastrando = false;
                        resizer.classList.remove('arrastrando');
                        document.body.style.cursor = '';
                        document.removeEventListener('mousemove', onMouseMove);
                        document.removeEventListener('mouseup', onMouseUp);
                    }
                };

                resizer.addEventListener('mousedown', (e) => {
                    arrastrando = true;
                    startX = e.clientX;
                    const panel = document.getElementById('editor-panel-razonamiento');
                    startWidth = panel ? panel.getBoundingClientRect().width : 300;
                    resizer.classList.add('arrastrando');
                    document.body.style.cursor = 'col-resize';
                    document.addEventListener('mousemove', onMouseMove);
                    document.addEventListener('mouseup', onMouseUp);
                    e.preventDefault();
                });
            }

            // Atajo de teclado: Ctrl+Shift+R para alternar Razonamiento
            window.addEventListener('keydown', (e) => {
                if (e.ctrlKey && e.shiftKey && (e.key === 'R' || e.key === 'r')) {
                    e.preventDefault();
                    this.alternarTabOVisibilidad('razonamiento');
                } else if (e.ctrlKey && e.shiftKey && (e.key === 'N' || e.key === 'n')) {
                    e.preventDefault();
                    this.alternarTabOVisibilidad('notas');
                }
            });

            // Escuchar cambios de archivo en Prig
            window.addEventListener('prig:archivo-abierto', (e) => {
                if (e.detail && e.detail.path) {
                    this.cargarArchivo(e.detail.path);
                }
            });

            // Redibujar overlay al redimensionar la ventana
            window.addEventListener('resize', () => {
                this._refrescarLayoutMonaco();
                this.actualizarOverlay();
            });
        }

        /** Alterna la visibilidad del panel o cambia de pestaña */
        alternarTabOVisibilidad(tabDestino) {
            if (!this.panelVisible) {
                this.panelVisible = true;
                this.tabActiva = tabDestino;
            } else if (this.tabActiva === tabDestino) {
                this.panelVisible = false;
            } else {
                this.tabActiva = tabDestino;
            }

            this._actualizarVisibilidadDOM();
            this.renderizar();
            this._refrescarLayoutMonaco();
            this.actualizarOverlay();
        }

        alternarConectores() {
            this.relacionVisualActiva = !this.relacionVisualActiva;
            const btn = document.getElementById('btn-editor-relacion-visual');
            if (btn) {
                btn.classList.toggle('activo', this.relacionVisualActiva);
                btn.style.opacity = this.relacionVisualActiva ? '1' : '0.5';
            }
            this.actualizarOverlay();
        }

        _actualizarVisibilidadDOM() {
            const panel = document.getElementById('editor-panel-razonamiento');
            const resizer = document.getElementById('editor-razonamiento-resizer');
            const btnRaz = document.getElementById('btn-editor-razonamiento');
            const btnNotas = document.getElementById('btn-editor-notas');

            if (panel) {
                if (this.panelVisible) {
                    panel.classList.remove('oculto');
                    panel.style.display = 'flex';
                    panel.style.width = `${this.anchoPorcentaje}%`;
                    panel.style.flex = `0 0 ${this.anchoPorcentaje}%`;
                } else {
                    panel.classList.add('oculto');
                    panel.style.display = 'none';
                }
            }

            if (resizer) {
                resizer.style.display = this.panelVisible ? 'flex' : 'none';
            }

            if (btnRaz) {
                btnRaz.classList.toggle('activo', this.panelVisible && this.tabActiva === 'razonamiento');
                btnRaz.style.borderColor = (this.panelVisible && this.tabActiva === 'razonamiento') ? '#89b4fa' : 'rgba(137, 180, 250, 0.45)';
            }

            if (btnNotas) {
                btnNotas.classList.toggle('activo', this.panelVisible && this.tabActiva === 'notas');
                btnNotas.style.borderColor = (this.panelVisible && this.tabActiva === 'notas') ? '#a6e3a1' : 'rgba(166, 227, 161, 0.4)';
            }
        }

        _intentarVincularMonaco() {
            const ed = window.editorMgr ? window.editorMgr.editor : null;
            if (ed && ed.getModel()) {
                const model = ed.getModel();
                this.analizarCodigoBuffer(model.getValue(), model.uri ? model.uri.path : this.archivoActivo);
                this.actualizarOverlay();
            } else {
                setTimeout(() => this._intentarVincularMonaco(), 400);
            }
        }

        /** Analiza el búfer de código y extrae la jerarquía completa de clases, funciones y métodos */
        analizarCodigoBuffer(codigo, ruta = '') {
            if (typeof codigo !== 'string' || !codigo.trim()) return;
            const rutaNormalizada = (ruta || this.archivoActivo || '').toLowerCase();
            const esJsTs = rutaNormalizada.endsWith('.js') || rutaNormalizada.endsWith('.ts') || rutaNormalizada.endsWith('.jsx') || rutaNormalizada.endsWith('.tsx');

            const simbolos = esJsTs ? this._parsearJavaScript(codigo) : this._parsearPython(codigo);

            if (simbolos.length === 0) {
                const totalLineas = codigo.split(/\r?\n/).length;
                simbolos.push({
                    id: 'sym_root',
                    tipo: 'bloque',
                    nombre: 'Módulo Principal',
                    firma: `${this.archivoActivo.split('/').pop()}`,
                    lineaInicio: 1,
                    lineaFin: Math.max(1, totalLineas),
                    totalLineas: totalLineas,
                    nivel: 1,
                    padreId: null,
                    complejidad: 1,
                    hijos: []
                });
            }

            this.estructuraCodigo.simbolos = simbolos;

            const arbol = [];
            const mapa = new Map();
            simbolos.forEach(s => {
                s.hijos = [];
                mapa.set(s.id, s);
            });

            simbolos.forEach(s => {
                if (!s.padreId) {
                    arbol.push(s);
                } else {
                    const padre = mapa.get(s.padreId);
                    if (padre) {
                        padre.hijos.push(s);
                    } else {
                        arbol.push(s);
                    }
                }
            });
            this.estructuraCodigo.arbol = arbol;

            this.sincronizarAmbitoConCursor(this.lineaCursor, false);
        }

        _parsearPython(codigo) {
            const lineas = codigo.split(/\r?\n/);
            const simbolos = [];
            const pilaPadres = [];

            const reInicioClass = /^(\s*)class\s+([A-Za-z0-9_]+)/;
            const reInicioDef = /^(\s*)(async\s+)?def\s+([A-Za-z0-9_]+)/;
            const reRamaComplejidad = /\b(if|elif|for|while|except|case)\b/;

            for (let i = 0; i < lineas.length; i++) {
                const numLinea = i + 1;
                const linea = lineas[i];
                const matchEspacios = linea.match(/^(\s*)/);
                const indent = matchEspacios ? matchEspacios[1].length : 0;
                const recortada = linea.trim();

                if (!recortada || recortada.startsWith('#')) continue;

                while (pilaPadres.length > 0 && indent <= pilaPadres[pilaPadres.length - 1].indent) {
                    const cerrado = pilaPadres.pop();
                    cerrado.lineaFin = numLinea - 1;
                    while (cerrado.lineaFin > cerrado.lineaInicio && !lineas[cerrado.lineaFin - 1].trim()) {
                        cerrado.lineaFin--;
                    }
                    cerrado.totalLineas = cerrado.lineaFin - cerrado.lineaInicio + 1;
                }

                const matchClase = linea.match(reInicioClass);
                if (matchClase) {
                    let firma = recortada;
                    let j = i;
                    while (j < lineas.length && !firma.includes(':')) {
                        j++;
                        if (j < lineas.length) firma += ' ' + lineas[j].trim();
                    }
                    const padre = pilaPadres.length > 0 ? pilaPadres[pilaPadres.length - 1] : null;
                    const sym = {
                        id: 'sym_py_' + numLinea,
                        tipo: 'class',
                        nombre: matchClase[2],
                        firma: firma.replace(/:.*$/, '').replace(/\s+/g, ' ').trim(),
                        indent: indent,
                        lineaInicio: numLinea,
                        lineaFin: lineas.length,
                        totalLineas: 1,
                        padreId: padre ? padre.id : null,
                        padreNombre: padre ? padre.nombre : null,
                        nivel: pilaPadres.length + 1,
                        complejidad: 1,
                        hijos: []
                    };
                    simbolos.push(sym);
                    pilaPadres.push(sym);
                    continue;
                }

                const matchDef = linea.match(reInicioDef);
                if (matchDef) {
                    let firma = recortada;
                    let j = i;
                    while (j < lineas.length && !firma.includes(':')) {
                        j++;
                        if (j < lineas.length) firma += ' ' + lineas[j].trim();
                    }
                    const esAsync = !!matchDef[2];
                    const nombre = matchDef[3];
                    const padre = pilaPadres.length > 0 ? pilaPadres[pilaPadres.length - 1] : null;
                    const sym = {
                        id: 'sym_py_' + numLinea,
                        tipo: esAsync ? 'async def' : 'def',
                        nombre: nombre,
                        firma: firma.replace(/:.*$/, '').replace(/\s+/g, ' ').trim(),
                        indent: indent,
                        lineaInicio: numLinea,
                        lineaFin: lineas.length,
                        totalLineas: 1,
                        padreId: padre ? padre.id : null,
                        padreNombre: padre ? padre.nombre : null,
                        nivel: pilaPadres.length + 1,
                        complejidad: 1,
                        hijos: []
                    };
                    simbolos.push(sym);
                    pilaPadres.push(sym);
                    continue;
                }

                if (pilaPadres.length > 0 && reRamaComplejidad.test(recortada)) {
                    pilaPadres[pilaPadres.length - 1].complejidad++;
                }
            }

            while (pilaPadres.length > 0) {
                const cerrado = pilaPadres.pop();
                cerrado.lineaFin = lineas.length;
                while (cerrado.lineaFin > cerrado.lineaInicio && !lineas[cerrado.lineaFin - 1].trim()) {
                    cerrado.lineaFin--;
                }
                cerrado.totalLineas = cerrado.lineaFin - cerrado.lineaInicio + 1;
            }

            return simbolos;
        }

        _parsearJavaScript(codigo) {
            const lineas = codigo.split(/\r?\n/);
            const simbolos = [];
            const pilaBloques = [];

            const reClass = /^(\s*)class\s+([A-Za-z0-9_$]+)/;
            const reFunc = /^(\s*)(async\s+)?function\s+([A-Za-z0-9_$]+)/;
            const reMethod = /^(\s*)(async\s+)?([A-Za-z0-9_$]+)\s*\([^)]*\)\s*\{/;
            const reRamaComplejidad = /\b(if|else if|for|while|catch|case)\b/;

            let balanceLlaves = 0;

            for (let i = 0; i < lineas.length; i++) {
                const numLinea = i + 1;
                const linea = lineas[i];
                const recortada = linea.trim();
                if (!recortada || recortada.startsWith('//') || recortada.startsWith('/*')) continue;

                const matchClase = linea.match(reClass);
                if (matchClase) {
                    const padre = pilaBloques.length > 0 ? pilaBloques[pilaBloques.length - 1].sym : null;
                    const sym = {
                        id: 'sym_js_' + numLinea,
                        tipo: 'class',
                        nombre: matchClase[2],
                        firma: recortada.replace(/\{.*$/, '').trim(),
                        lineaInicio: numLinea,
                        lineaFin: lineas.length,
                        totalLineas: 1,
                        padreId: padre ? padre.id : null,
                        padreNombre: padre ? padre.nombre : null,
                        nivel: pilaBloques.length + 1,
                        complejidad: 1,
                        hijos: []
                    };
                    simbolos.push(sym);
                    pilaBloques.push({ sym, nivelLlaves: balanceLlaves + (linea.includes('{') ? 1 : 0) });
                } else if (linea.match(reFunc)) {
                    const m = linea.match(reFunc);
                    const padre = pilaBloques.length > 0 ? pilaBloques[pilaBloques.length - 1].sym : null;
                    const sym = {
                        id: 'sym_js_' + numLinea,
                        tipo: m[2] ? 'async function' : 'function',
                        nombre: m[3],
                        firma: recortada.replace(/\{.*$/, '').trim(),
                        lineaInicio: numLinea,
                        lineaFin: lineas.length,
                        totalLineas: 1,
                        padreId: padre ? padre.id : null,
                        padreNombre: padre ? padre.nombre : null,
                        nivel: pilaBloques.length + 1,
                        complejidad: 1,
                        hijos: []
                    };
                    simbolos.push(sym);
                    pilaBloques.push({ sym, nivelLlaves: balanceLlaves + (linea.includes('{') ? 1 : 0) });
                } else if (pilaBloques.length > 0 && pilaBloques[pilaBloques.length - 1].sym.tipo === 'class' && linea.match(reMethod)) {
                    const m = linea.match(reMethod);
                    if (!['if', 'for', 'while', 'switch', 'catch'].includes(m[3])) {
                        const padre = pilaBloques[pilaBloques.length - 1].sym;
                        const sym = {
                            id: 'sym_js_' + numLinea,
                            tipo: m[2] ? 'async method' : 'def',
                            nombre: m[3],
                            firma: recortada.replace(/\{.*$/, '').trim(),
                            lineaInicio: numLinea,
                            lineaFin: lineas.length,
                            totalLineas: 1,
                            padreId: padre.id,
                            padreNombre: padre.nombre,
                            nivel: pilaBloques.length + 1,
                            complejidad: 1,
                            hijos: []
                        };
                        simbolos.push(sym);
                        pilaBloques.push({ sym, nivelLlaves: balanceLlaves + (linea.includes('{') ? 1 : 0) });
                    }
                }

                if (pilaBloques.length > 0 && reRamaComplejidad.test(recortada)) {
                    pilaBloques[pilaBloques.length - 1].sym.complejidad++;
                }

                for (const ch of linea) {
                    if (ch === '{') balanceLlaves++;
                    else if (ch === '}') {
                        balanceLlaves--;
                        if (pilaBloques.length > 0 && balanceLlaves < pilaBloques[pilaBloques.length - 1].nivelLlaves) {
                            const cerrado = pilaBloques.pop();
                            cerrado.sym.lineaFin = numLinea;
                            cerrado.sym.totalLineas = cerrado.sym.lineaFin - cerrado.sym.lineaInicio + 1;
                        }
                    }
                }
            }

            return simbolos;
        }

        obtenerSimboloEnLinea(numLinea) {
            const simbolos = this.estructuraCodigo.simbolos;
            if (!simbolos || simbolos.length === 0) return null;

            let mejor = null;
            let menorSpan = Infinity;
            for (const s of simbolos) {
                if (numLinea >= s.lineaInicio && numLinea <= s.lineaFin) {
                    const span = s.lineaFin - s.lineaInicio;
                    if (span < menorSpan) {
                        menorSpan = span;
                        mejor = s;
                    }
                }
            }
            return mejor || simbolos[0];
        }

        sincronizarAmbitoConCursor(numLinea, enfocarMonaco = false) {
            const simbolo = this.obtenerSimboloEnLinea(numLinea);
            if (simbolo) {
                this.establecerAmbitoJerarquico(simbolo.id, enfocarMonaco);
            }
        }

        establecerAmbitoJerarquico(simboloId, enfocarMonaco = true) {
            const simbolos = this.estructuraCodigo.simbolos;
            const activo = simbolos.find(s => s.id === simboloId);
            if (!activo) return;

            this.estructuraCodigo.simboloActivo = activo;

            let padre = null;
            if (activo.padreId) {
                padre = simbolos.find(s => s.id === activo.padreId);
            }
            this.estructuraCodigo.simboloPadre = padre;

            // Construir camino jerárquico
            const camino = [
                { id: 'root_file', tipo: 'file', nombre: this.archivoActivo.split('/').pop(), linea: 1 }
            ];
            if (padre) {
                camino.push({ id: padre.id, tipo: padre.tipo, nombre: `${padre.tipo} ${padre.nombre}`, linea: padre.lineaInicio });
            }
            camino.push({ id: activo.id, tipo: activo.tipo, nombre: `${activo.tipo} ${activo.nombre}`, linea: activo.lineaInicio });
            this.estructuraCodigo.caminoJerarquico = camino;

            // Actualizar conectorFoco
            const colorActivo = activo.tipo === 'class' ? '#cba6f7' : (activo.tipo.includes('async') ? '#a6e3a1' : '#89b4fa');
            this.conectorFoco = {
                activo: true,
                lineaInicio: activo.lineaInicio,
                lineaFin: activo.lineaFin,
                tipo: activo.tipo,
                nombre: activo.nombre,
                etiqueta: `${activo.tipo} ${activo.nombre}`,
                firma: activo.firma,
                color: colorActivo,
                simboloId: activo.id,
                padre: padre ? {
                    lineaInicio: padre.lineaInicio,
                    lineaFin: padre.lineaFin,
                    tipo: padre.tipo,
                    nombre: padre.nombre,
                    etiqueta: `class ${padre.nombre}`,
                    firma: padre.firma,
                    totalLineas: padre.totalLineas,
                    color: '#cba6f7'
                } : null
            };

            if (enfocarMonaco) {
                const ed = window.editorMgr ? window.editorMgr.editor : null;
                if (ed) {
                    try {
                        ed.revealLineInCenter(activo.lineaInicio);
                        ed.setPosition({ lineNumber: activo.lineaInicio, column: 1 });
                        this._aplicarDecoracionMonaco(ed, activo.lineaInicio, activo.lineaFin, colorActivo);
                    } catch (e) {}
                }
            }

            this.actualizarOverlay();
            this._actualizarBreadcrumbsDOM();
            this._actualizarArbolASTDOM();
        }

        alternarModoCorchetes() {
            this.configJerarquia.modoCorchetes = (this.configJerarquia.modoCorchetes === 'jerarquico') ? 'unitario' : 'jerarquico';
            const btn = document.getElementById('btn-cfg-modo-corchetes');
            if (btn) {
                btn.classList.toggle('activo', this.configJerarquia.modoCorchetes === 'jerarquico');
                btn.innerHTML = `<i class="fa-solid fa-layer-group"></i> ${this.configJerarquia.modoCorchetes === 'jerarquico' ? 'Jerárquico' : 'Unitario'}`;
            }
            this.actualizarOverlay();
        }

        alternarSyncCursor() {
            this.configJerarquia.autoSincronizarCursor = !this.configJerarquia.autoSincronizarCursor;
            const btn = document.getElementById('btn-cfg-sync-cursor');
            if (btn) {
                btn.classList.toggle('activo', this.configJerarquia.autoSincronizarCursor);
                btn.innerHTML = `<i class="fa-solid fa-crosshairs"></i> Auto-Sync: ${this.configJerarquia.autoSincronizarCursor ? 'ON' : 'OFF'}`;
            }
        }

        /** Carga el contexto del archivo abierto */
        cargarArchivo(ruta) {
            this.archivoActivo = ruta || 'main.py';
            const base = this.archivoActivo.split('/').pop();

            // Actualizar nodos y notas para el archivo
            this.razonamiento.grafoNodos[0].nombre = `ENTRY: ${base}`;
            this._actualizarContadorNotas();

            const ed = window.editorMgr ? window.editorMgr.editor : null;
            if (ed && ed.getModel()) {
                this.analizarCodigoBuffer(ed.getModel().getValue(), this.archivoActivo);
            }

            this.renderizar();
            this.actualizarOverlay();
        }

        /** Renderiza el panel principal según la pestaña activa */
        renderizar() {
            const panel = document.getElementById('editor-panel-razonamiento');
            if (!panel || !this.panelVisible) return;

            const esRaz = (this.tabActiva === 'razonamiento');
            const notas = this._obtenerNotasArchivoActual();

            panel.innerHTML = `
                <!-- Cabecera Superior del Panel -->
                <div class="razonamiento-header">
                    <div class="razonamiento-header-tabs">
                        <button class="razonamiento-tab-btn ${esRaz ? 'activo' : ''}" id="p-tab-raz">
                            <i class="fa-solid fa-brain-circuit"></i> Razonamiento
                        </button>
                        <button class="razonamiento-tab-btn tab-notas ${!esRaz ? 'activo' : ''}" id="p-tab-not">
                            <i class="fa-solid fa-clipboard-list"></i> Notas (${notas.length})
                        </button>
                    </div>
                    <div class="razonamiento-header-acciones">
                        <button class="razonamiento-btn-icon" id="btn-p-analizar" title="Re-ejecutar análisis de razonamiento">
                            <i class="fa-solid fa-rotate-right"></i>
                        </button>
                        <button class="razonamiento-btn-icon" id="btn-p-cerrar" title="Ocultar panel">
                            <i class="fa-solid fa-xmark"></i>
                        </button>
                    </div>
                </div>

                <!-- Barra de Telemetría Profesional -->
                <div class="razonamiento-telemetria-bar">
                    <span class="razonamiento-modelo-pill">
                        <span class="razonamiento-dot-pulse ${this.razonamiento.estado === 'pensando' ? 'pensando' : ''}"></span>
                        ${this.razonamiento.modelo}
                    </span>
                    <span>${this.razonamiento.tokSeg} · CoT ${this.razonamiento.tiempoCoT}</span>
                </div>

                <!-- Breadcrumbs Jerárquicos de Ámbito (Scope) -->
                ${esRaz ? this._renderizarBreadcrumbsHTML() : ''}

                <!-- Barra de Configuración Profesional (Jerárquico / Auto-Sync) -->
                ${esRaz ? this._renderizarConfigToolbarHTML() : ''}

                <!-- Cuerpo del Panel -->
                <div class="razonamiento-body" id="razonamiento-body-scroll">
                    ${esRaz ? this._renderizarVistaRazonamiento() : this._renderizarVistaNotas()}
                </div>
            `;

            // Conectar eventos del panel
            panel.querySelector('#p-tab-raz').onclick = () => { this.tabActiva = 'razonamiento'; this._actualizarVisibilidadDOM(); this.renderizar(); this.actualizarOverlay(); };
            panel.querySelector('#p-tab-not').onclick = () => { this.tabActiva = 'notas'; this._actualizarVisibilidadDOM(); this.renderizar(); this.actualizarOverlay(); };
            panel.querySelector('#btn-p-cerrar').onclick = () => { this.panelVisible = false; this._actualizarVisibilidadDOM(); this._refrescarLayoutMonaco(); this.actualizarOverlay(); };
            panel.querySelector('#btn-p-analizar').onclick = () => this.dispararAnalisisManual();

            this._conectarEventosInternos(panel);
        }

        _renderizarBreadcrumbsHTML() {
            const camino = this.estructuraCodigo.caminoJerarquico;
            if (!camino || camino.length === 0) {
                const nombreBase = this.archivoActivo.split('/').pop();
                return `
                    <div class="razonamiento-breadcrumb-bar" id="razonamiento-breadcrumb-bar">
                        <span class="razonamiento-crumb-item activo" data-crumb-linea="1">
                            <i class="fa-regular fa-file-code"></i> ${this._escaparHtml(nombreBase)}
                        </span>
                    </div>
                `;
            }

            return `
                <div class="razonamiento-breadcrumb-bar" id="razonamiento-breadcrumb-bar">
                    ${camino.map((c, idx) => {
                        const esUltimo = (idx === camino.length - 1);
                        const esClase = (c.tipo === 'class');
                        const icono = (c.tipo === 'file') ? 'fa-regular fa-file-code' : (esClase ? 'fa-solid fa-cube' : 'fa-solid fa-bolt');
                        const claseItem = `razonamiento-crumb-item ${esClase ? 'crumb-class' : ''} ${esUltimo ? 'activo' : ''}`;
                        return `
                            <span class="${claseItem}" data-crumb-simbolo="${c.id || ''}" data-crumb-linea="${c.linea || 1}" title="${c.nombre} (Línea ${c.linea || 1})">
                                <i class="${icono}"></i> ${this._escaparHtml(c.nombre)}
                            </span>
                            ${!esUltimo ? '<span class="razonamiento-crumb-sep">❯</span>' : ''}
                        `;
                    }).join('')}
                </div>
            `;
        }

        _renderizarConfigToolbarHTML() {
            const esJer = (this.configJerarquia.modoCorchetes === 'jerarquico');
            const sync = this.configJerarquia.autoSincronizarCursor;
            const svgAct = this.relacionVisualActiva;

            return `
                <div class="razonamiento-config-toolbar">
                    <div class="razonamiento-toolbar-grupo">
                        <button class="razonamiento-toggle-pill pill-purple ${esJer ? 'activo' : ''}" id="btn-cfg-modo-corchetes" title="Alternar entre corchetes jerárquicos (Class + Def anidados) o foco unitario">
                            <i class="fa-solid fa-layer-group"></i> ${esJer ? 'Jerárquico' : 'Unitario'}
                        </button>
                        <button class="razonamiento-toggle-pill ${sync ? 'activo' : ''}" id="btn-cfg-sync-cursor" title="Sincronizar automáticamente corchetes con la posición del cursor en Monaco">
                            <i class="fa-solid fa-crosshairs"></i> Sync: ${sync ? 'ON' : 'OFF'}
                        </button>
                    </div>
                    <button class="razonamiento-toggle-pill ${svgAct ? 'activo' : ''}" id="btn-cfg-conectores-svg" title="Mostrar u ocultar corchetes y flechas visuales">
                        <i class="fa-solid fa-draw-polygon"></i> SVG
                    </button>
                </div>
            `;
        }

        _renderizarArbolASTHTML() {
            const arbol = this.estructuraCodigo.arbol || [];
            const totalSimbolos = this.estructuraCodigo.simbolos.length;
            const expandido = this.configJerarquia.arbolExpandido;
            const activoId = this.estructuraCodigo.simboloActivo ? this.estructuraCodigo.simboloActivo.id : null;

            return `
                <div class="razonamiento-ast-card">
                    <div class="razonamiento-ast-header" id="ast-header-toggle">
                        <span style="display: flex; align-items: center; gap: 6px;">
                            <i class="fa-solid fa-sitemap" style="color: #cba6f7;"></i>
                            <span>Jerarquía de Bloques (AST)</span>
                            <span style="font-size: 9px; padding: 1px 5px; border-radius: 8px; background: rgba(203, 166, 247, 0.2); color: #cba6f7; font-weight: 800;">${totalSimbolos}</span>
                        </span>
                        <i class="fa-solid ${expandido ? 'fa-chevron-up' : 'fa-chevron-down'}" style="font-size: 10px; color: #a6adc8;"></i>
                    </div>
                    <div class="razonamiento-ast-tree" id="ast-tree-lista" style="display: ${expandido ? 'flex' : 'none'};">
                        ${totalSimbolos === 0 ? `
                            <div style="padding: 10px; text-align: center; color: #a6adc8; font-size: 10px;">
                                No se detectaron declaraciones class o def en este archivo.
                            </div>
                        ` : arbol.map(nodo => this._renderizarNodoAST(nodo, activoId)).join('')}
                    </div>
                </div>
            `;
        }

        _renderizarNodoAST(nodo, activoId) {
            const esClase = (nodo.tipo === 'class');
            const esActivo = (nodo.id === activoId);
            const badgeClass = esClase ? 'badge-tipo-class' : (nodo.tipo.includes('async') ? 'badge-tipo-async' : (nodo.tipo === 'bloque' ? 'badge-tipo-block' : 'badge-tipo-def'));
            const icono = esClase ? 'fa-cube' : (nodo.tipo.includes('async') ? 'fa-bolt-lightning' : 'fa-bolt');

            let htmlHijos = '';
            if (nodo.hijos && nodo.hijos.length > 0) {
                htmlHijos = nodo.hijos.map(h => {
                    const hActivo = (h.id === activoId);
                    const hBadge = h.tipo.includes('async') ? 'badge-tipo-async' : 'badge-tipo-def';
                    return `
                        <div class="razonamiento-ast-node nodo-hijo ${hActivo ? 'activo' : ''}" data-ast-simbolo="${h.id}" title="${h.firma}">
                            <div class="razonamiento-ast-node-info">
                                <span class="razonamiento-ast-badge-tipo ${hBadge}">${h.tipo === 'async def' ? 'ASYNC' : 'DEF'}</span>
                                <span style="color: ${hActivo ? '#89b4fa' : '#cdd6f4'}; font-weight: ${hActivo ? '700' : '500'};">${this._escaparHtml(h.nombre)}</span>
                            </div>
                            <div class="razonamiento-ast-meta">
                                <span>L${h.lineaInicio}-${h.lineaFin}</span>
                                <span style="color: #6c7086;">·</span>
                                <span style="color: #f9e2af;">CC:${h.complejidad}</span>
                            </div>
                        </div>
                    `;
                }).join('');
            }

            return `
                <div class="razonamiento-ast-node ${esClase ? 'nodo-class' : ''} ${esActivo ? 'activo' : ''}" data-ast-simbolo="${nodo.id}" title="${nodo.firma}">
                    <div class="razonamiento-ast-node-info">
                        <span class="razonamiento-ast-badge-tipo ${badgeClass}">${nodo.tipo.toUpperCase()}</span>
                        <span style="color: ${esClase ? '#cba6f7' : (esActivo ? '#89b4fa' : '#cdd6f4')}; font-weight: 700;">${this._escaparHtml(nodo.nombre)}</span>
                    </div>
                    <div class="razonamiento-ast-meta">
                        <span>L${nodo.lineaInicio}-${nodo.lineaFin}</span>
                        <span style="color: #6c7086;">·</span>
                        <span style="color: #a6e3a1;">${nodo.totalLineas}L</span>
                    </div>
                </div>
                ${htmlHijos}
            `;
        }

        _actualizarBreadcrumbsDOM() {
            const contenedor = document.getElementById('razonamiento-breadcrumb-bar');
            if (contenedor && this.tabActiva === 'razonamiento') {
                const tempDiv = document.createElement('div');
                tempDiv.innerHTML = this._renderizarBreadcrumbsHTML();
                const nuevo = tempDiv.firstElementChild;
                if (nuevo) {
                    contenedor.replaceWith(nuevo);
                    this._conectarEventosBreadcrumbs(nuevo);
                }
            }
        }

        _actualizarArbolASTDOM() {
            const lista = document.getElementById('ast-tree-lista');
            if (lista && this.tabActiva === 'razonamiento') {
                const arbol = this.estructuraCodigo.arbol || [];
                const activoId = this.estructuraCodigo.simboloActivo ? this.estructuraCodigo.simboloActivo.id : null;
                lista.innerHTML = arbol.map(nodo => this._renderizarNodoAST(nodo, activoId)).join('');
                this._conectarEventosNodosAST(lista);
            }
        }

        _obtenerNombreBloqueParaRango(ini, fin) {
            const sym = this.obtenerSimboloEnLinea(ini);
            if (!sym) return `L${ini}-L${fin}`;
            if (sym.padreNombre) return `${sym.padreNombre}.${sym.nombre}()`;
            return `${sym.tipo} ${sym.nombre}()`;
        }

        _conectarEventosBreadcrumbs(bar) {
            if (!bar) return;
            bar.querySelectorAll('[data-crumb-simbolo]').forEach(el => {
                el.onclick = () => {
                    const symId = el.dataset.crumbSimbolo;
                    const linea = parseInt(el.dataset.crumbLinea, 10);
                    if (symId) {
                        this.establecerAmbitoJerarquico(symId, true);
                    } else if (linea) {
                        this.enfocarEnCodigo(linea, linea, 'Inicio');
                    }
                };
            });
        }

        _conectarEventosNodosAST(treeContainer) {
            if (!treeContainer) return;
            treeContainer.querySelectorAll('[data-ast-simbolo]').forEach(el => {
                el.onclick = () => {
                    const symId = el.dataset.astSimbolo;
                    if (symId) {
                        this.establecerAmbitoJerarquico(symId, true);
                    }
                };
            });
        }

        _renderizarVistaRazonamiento() {
            const r = this.razonamiento;
            return `
                <!-- Árbol Jerárquico de Símbolos (AST Scope Inspector) -->
                ${this._renderizarArbolASTHTML()}

                <!-- Acordeón de Proceso de Pensamiento (CoT) -->
                <div class="razonamiento-cot-box">
                    <div class="razonamiento-cot-header" id="cot-toggle-btn">
                        <span class="cot-titulo">
                            <i class="fa-solid fa-microchip" style="color: #cba6f7;"></i>
                            Proceso de Razonamiento CoT (${r.cotPasos.length} pasos)
                        </span>
                        <i class="fa-solid ${r.cotExpandido ? 'fa-chevron-up' : 'fa-chevron-down'}" style="font-size: 10px;"></i>
                    </div>
                    <div class="razonamiento-cot-content" style="display: ${r.cotExpandido ? 'block' : 'none'};">
                        ${r.cotPasos.map(p => `
                            <div class="razonamiento-cot-step">
                                <span class="razonamiento-step-num">#${p.num}</span>
                                <div>
                                    <div style="font-weight: 700; color: #f8fafc; font-size: 10.5px;">${p.titulo}</div>
                                    <div style="color: #bac2de; font-size: 10px; margin-top: 2px;">${p.detalle}</div>
                                </div>
                            </div>
                        `).join('')}
                        <div style="margin-top: 8px; padding-top: 6px; border-top: 1px dashed rgba(255,255,255,0.08); font-size: 10.5px; color: #a6e3a1; font-family: 'Fira Code', monospace;">
                            💬 ${r.dialogoTexto}
                        </div>
                    </div>
                </div>

                <!-- Tarjetas de Diagnóstico y Relación con Código -->
                <div style="font-size: 11px; font-weight: 800; text-transform: uppercase; letter-spacing: 0.4px; color: #89b4fa; display: flex; align-items: center; gap: 6px;">
                    <i class="fa-solid fa-magnifying-glass-chart"></i> Hallazgos y Diagnóstico en Código
                </div>

                ${r.hallazgos.map((h, i) => {
                    const nombreBloque = h.bloqueNombre || this._obtenerNombreBloqueParaRango(h.lineaInicio, h.lineaFin);
                    return `
                    <div class="razonamiento-card ${this.conectorFoco.lineaInicio === h.lineaInicio ? 'activa' : ''}" data-hallazgo-id="${h.id}">
                        <div class="razonamiento-card-meta">
                            <div style="display: flex; align-items: center; gap: 5px; overflow: hidden;">
                                <span class="razonamiento-badge-categoria ${h.categoria}">${h.categoriaTexto}</span>
                                <span style="font-size: 9.5px; color: #cba6f7; font-family: 'Fira Code', monospace; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">
                                    <i class="fa-solid fa-code-commit" style="font-size: 8.5px;"></i> ${this._escaparHtml(nombreBloque)}
                                </span>
                            </div>
                            <span class="razonamiento-badge-linea" title="Ir a líneas ${h.lineaInicio}-${h.lineaFin}">
                                <i class="fa-solid fa-arrow-turn-down"></i> L${h.lineaInicio}-L${h.lineaFin}
                            </span>
                        </div>
                        <div class="razonamiento-card-titulo">${h.titulo}</div>
                        <div class="razonamiento-card-detalle">${h.detalle}</div>
                        ${h.codigoSugerido ? `<div class="razonamiento-codigo-snippet">${this._escaparHtml(h.codigoSugerido)}</div>` : ''}
                        <div class="razonamiento-card-acciones">
                            <button class="razonamiento-btn-conectar" data-accion="conectar" data-linea-ini="${h.lineaInicio}" data-linea-fin="${h.lineaFin}" data-titulo="${h.titulo}" data-color="${h.color}">
                                <i class="fa-solid fa-code-fork"></i> Conectar con Código
                            </button>
                            ${h.codigoSugerido ? `
                                <button class="razonamiento-btn-aplicar" data-accion="aplicar" data-linea-ini="${h.lineaInicio}" data-linea-fin="${h.lineaFin}" data-codigo="${encodeURIComponent(h.codigoSugerido)}">
                                    <i class="fa-solid fa-wand-magic-sparkles"></i> Aplicar
                                </button>
                            ` : ''}
                        </div>
                    </div>
                `;}).join('')}

                <!-- Grafo de Lógica de Ejecución -->
                <div class="razonamiento-flujo-grafo">
                    <div class="razonamiento-grafo-titulo">
                        <i class="fa-solid fa-diagram-next"></i> Flujo Lógico de Ejecución
                    </div>
                    ${r.grafoNodos.map((n, idx) => `
                        <div class="razonamiento-grafo-nodo ${this.conectorFoco.lineaInicio === n.linea ? 'activo' : ''}" data-linea="${n.linea}" data-nombre="${n.nombre}">
                            <div>
                                <div style="font-weight: 700; color: #ffffff;">${n.nombre}</div>
                                <div style="font-size: 9.5px; color: #a6adc8;">${n.sub}</div>
                            </div>
                            <span class="razonamiento-badge-linea">L${n.linea}</span>
                        </div>
                        ${idx < r.grafoNodos.length - 1 ? '<div class="razonamiento-grafo-flecha">▼</div>' : ''}
                    `).join('')}
                </div>

                <!-- Métricas de Código -->
                <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 6px; padding: 8px; background: rgba(0,0,0,0.25); border-radius: 6px; border: 1px solid rgba(255,255,255,0.06); font-size: 10.5px;">
                    <div><span style="color: #a6adc8;">Complejidad:</span> <b style="color: #f9e2af;">${r.metricas.complejidad}</b></div>
                    <div><span style="color: #a6adc8;">Calidad:</span> <b style="color: #a6e3a1;">${r.metricas.calidad}</b></div>
                    <div><span style="color: #a6adc8;">Modularidad:</span> <b style="color: #89b4fa;">${r.metricas.modularidad}</b></div>
                    <div><span style="color: #a6adc8;">Guardas:</span> <b style="color: #cba6f7;">${r.metricas.guardas}</b></div>
                </div>
            `;
        }

        _renderizarVistaNotas() {
            const notas = this._obtenerNotasArchivoActual();
            const notasFiltradas = this.filtroCategoriaNota === 'todas'
                ? notas
                : notas.filter(n => n.categoria === this.filtroCategoriaNota);

            return `
                <div class="notas-toolbar">
                    <button class="notas-btn-nueva" id="btn-mostrar-form-nota">
                        <i class="fa-solid fa-plus"></i> Añadir Nota en Línea ${this.lineaCursor}
                    </button>
                </div>

                <!-- Formulario de Creación de Nota (oculto por defecto) -->
                <div class="notas-form-crear" id="form-crear-nota" style="display: none;">
                    <div style="font-size: 11px; font-weight: 700; color: #a6e3a1; display: flex; justify-content: space-between; align-items: center;">
                        <span>Nueva Nota Técnica</span>
                        <button id="btn-cerrar-form-nota" style="background: none; border: none; color: #a6adc8; cursor: pointer;"><i class="fa-solid fa-xmark"></i></button>
                    </div>
                    <div class="notas-input-fila">
                        <input type="number" id="nota-input-linea-ini" class="notas-input" value="${this.lineaCursor}" style="width: 70px;" placeholder="Línea">
                        <input type="number" id="nota-input-linea-fin" class="notas-input" style="width: 70px;" placeholder="Fin">
                        <select id="nota-select-cat" class="notas-input" style="flex: 1;">
                            <option value="arq">Arquitectura</option>
                            <option value="opt">Optimización</option>
                            <option value="seg">Seguridad</option>
                            <option value="todo">TODO / Pendiente</option>
                        </select>
                    </div>
                    <input type="text" id="nota-input-titulo" class="notas-input" placeholder="Título de la nota (ej: Refactorizar cláusula)">
                    <textarea id="nota-textarea-detalle" class="notas-textarea" placeholder="Detalle técnico de la anotación..."></textarea>
                    <div style="display: flex; gap: 6px; justify-content: flex-end;">
                        <button class="razonamiento-btn-aplicar" id="btn-guardar-nota">
                            <i class="fa-solid fa-floppy-disk"></i> Guardar Nota
                        </button>
                    </div>
                </div>

                <!-- Filtros de Categorías -->
                <div style="display: flex; gap: 4px; overflow-x: auto; padding-bottom: 4px;">
                    ${['todas', 'arq', 'opt', 'seg', 'todo'].map(cat => `
                        <button class="razonamiento-badge-categoria ${cat} ${this.filtroCategoriaNota === cat ? 'activa' : ''}" style="cursor: pointer; border: 1px solid rgba(255,255,255,0.15);" data-filtro-cat="${cat}">
                            ${cat.toUpperCase()}
                        </button>
                    `).join('')}
                </div>

                <!-- Lista de Notas Guardadas -->
                ${notasFiltradas.length === 0 ? `
                    <div style="padding: 24px 12px; text-align: center; color: #a6adc8; font-size: 11px;">
                        <i class="fa-regular fa-clipboard" style="font-size: 24px; opacity: 0.4; margin-bottom: 8px;"></i>
                        <div>No hay notas registradas para este archivo.</div>
                        <div style="font-size: 10px; color: #6c7086; margin-top: 4px;">Usa el botón superior para anotar sobre la línea activa.</div>
                    </div>
                ` : notasFiltradas.map((n, idx) => `
                    <div class="notas-item-card" data-nota-id="${n.id}">
                        <div class="notas-item-header">
                            <span class="razonamiento-badge-categoria ${n.categoria}">${n.categoria.toUpperCase()}</span>
                            <div style="display: flex; align-items: center; gap: 6px;">
                                <span class="razonamiento-badge-linea" data-saltar-linea="${n.lineaInicio}">
                                    <i class="fa-solid fa-code"></i> L${n.lineaInicio}${n.lineaFin ? `-${n.lineaFin}` : ''}
                                </span>
                                <button class="razonamiento-btn-icon" data-borrar-nota="${n.id}" title="Eliminar nota" style="color: #f38ba8;">
                                    <i class="fa-solid fa-trash-can"></i>
                                </button>
                            </div>
                        </div>
                        <div style="font-weight: 700; color: #ffffff; font-size: 11.5px;">${n.titulo}</div>
                        <div class="notas-item-texto">${n.detalle}</div>
                        <div style="margin-top: 4px;">
                            <button class="razonamiento-btn-conectar" data-conectar-nota="${n.id}" data-linea-ini="${n.lineaInicio}" data-linea-fin="${n.lineaFin || n.lineaInicio}" data-titulo="${n.titulo}">
                                <i class="fa-solid fa-link"></i> Vincular Visualmente
                            </button>
                        </div>
                    </div>
                `).join('')}
            `;
        }

        _conectarEventosInternos(panel) {
            // Breadcrumbs interactivos
            this._conectarEventosBreadcrumbs(panel.querySelector('#razonamiento-breadcrumb-bar'));

            // Botones de la barra de configuración profesional
            const btnModo = panel.querySelector('#btn-cfg-modo-corchetes');
            if (btnModo) btnModo.onclick = () => this.alternarModoCorchetes();

            const btnSync = panel.querySelector('#btn-cfg-sync-cursor');
            if (btnSync) btnSync.onclick = () => this.alternarSyncCursor();

            const btnCon = panel.querySelector('#btn-cfg-conectores-svg');
            if (btnCon) btnCon.onclick = () => this.alternarConectores();

            // Desplegable del árbol AST
            const astToggle = panel.querySelector('#ast-header-toggle');
            if (astToggle) {
                astToggle.onclick = () => {
                    this.configJerarquia.arbolExpandido = !this.configJerarquia.arbolExpandido;
                    const tree = panel.querySelector('#ast-tree-lista');
                    const icon = astToggle.querySelector('i.fa-solid:last-child');
                    if (tree) tree.style.display = this.configJerarquia.arbolExpandido ? 'flex' : 'none';
                    if (icon) {
                        icon.className = `fa-solid ${this.configJerarquia.arbolExpandido ? 'fa-chevron-up' : 'fa-chevron-down'}`;
                    }
                };
            }

            // Nodos del árbol AST
            this._conectarEventosNodosAST(panel.querySelector('#ast-tree-lista'));

            // Acordeón CoT
            const toggleCot = panel.querySelector('#cot-toggle-btn');
            if (toggleCot) {
                toggleCot.onclick = () => {
                    this.razonamiento.cotExpandido = !this.razonamiento.cotExpandido;
                    this.renderizar();
                };
            }

            // Conectar hallazgo visualmente con el código
            panel.querySelectorAll('[data-accion="conectar"]').forEach(btn => {
                btn.onclick = (e) => {
                    e.stopPropagation();
                    const ini = parseInt(btn.dataset.lineaIni, 10);
                    const fin = parseInt(btn.dataset.lineaFin, 10);
                    const tit = btn.dataset.titulo;
                    const col = btn.dataset.color || '#89b4fa';
                    this.enfocarEnCodigo(ini, fin, tit, col);
                };
            });

            // Aplicar solución sugerida en el código
            panel.querySelectorAll('[data-accion="aplicar"]').forEach(btn => {
                btn.onclick = (e) => {
                    e.stopPropagation();
                    const ini = parseInt(btn.dataset.lineaIni, 10);
                    const fin = parseInt(btn.dataset.lineaFin, 10);
                    const codigo = decodeURIComponent(btn.dataset.codigo);
                    this.aplicarParcheEnCodigo(ini, fin, codigo);
                };
            });

            // Clic en nodo del grafo de ejecución
            panel.querySelectorAll('.razonamiento-grafo-nodo').forEach(nodo => {
                nodo.onclick = () => {
                    const l = parseInt(nodo.dataset.linea, 10);
                    const nom = nodo.dataset.nombre;
                    this.enfocarEnCodigo(l, l + 2, nom, '#a6e3a1');
                };
            });

            // Botones de Notas
            const btnMostrarForm = panel.querySelector('#btn-mostrar-form-nota');
            const formCrear = panel.querySelector('#form-crear-nota');
            const btnCerrarForm = panel.querySelector('#btn-cerrar-form-nota');
            if (btnMostrarForm && formCrear) {
                btnMostrarForm.onclick = () => { formCrear.style.display = 'flex'; };
            }
            if (btnCerrarForm && formCrear) {
                btnCerrarForm.onclick = () => { formCrear.style.display = 'none'; };
            }

            // Guardar Nota
            const btnGuardar = panel.querySelector('#btn-guardar-nota');
            if (btnGuardar) {
                btnGuardar.onclick = () => {
                    const lIni = parseInt(panel.querySelector('#nota-input-linea-ini').value, 10) || this.lineaCursor;
                    const lFin = parseInt(panel.querySelector('#nota-input-linea-fin').value, 10) || null;
                    const cat = panel.querySelector('#nota-select-cat').value;
                    const tit = (panel.querySelector('#nota-input-titulo').value || '').trim() || `Nota en L${lIni}`;
                    const det = (panel.querySelector('#nota-textarea-detalle').value || '').trim() || 'Anotación técnica de arquitectura.';

                    this.agregarNota({
                        lineaInicio: lIni,
                        lineaFin: lFin,
                        categoria: cat,
                        titulo: tit,
                        detalle: det
                    });
                    this.renderizar();
                    this.enfocarEnCodigo(lIni, lFin || lIni, tit, '#a6e3a1');
                };
            }

            // Saltar a línea desde nota
            panel.querySelectorAll('[data-saltar-linea]').forEach(btn => {
                btn.onclick = () => {
                    const l = parseInt(btn.dataset.saltarLinea, 10);
                    this.enfocarEnCodigo(l, l, `Nota L${l}`, '#a6e3a1');
                };
            });

            // Vincular nota visualmente
            panel.querySelectorAll('[data-conectar-nota]').forEach(btn => {
                btn.onclick = () => {
                    const ini = parseInt(btn.dataset.lineaIni, 10);
                    const fin = parseInt(btn.dataset.lineaFin, 10);
                    const tit = btn.dataset.titulo;
                    this.enfocarEnCodigo(ini, fin, tit, '#a6e3a1');
                };
            });

            // Borrar nota
            panel.querySelectorAll('[data-borrar-nota]').forEach(btn => {
                btn.onclick = (e) => {
                    e.stopPropagation();
                    const id = btn.dataset.borrarNota;
                    this.eliminarNota(id);
                    this.renderizar();
                    this.actualizarOverlay();
                };
            });

            // Filtros de categoría de notas
            panel.querySelectorAll('[data-filtro-cat]').forEach(btn => {
                btn.onclick = () => {
                    this.filtroCategoriaNota = btn.dataset.filtroCat;
                    this.renderizar();
                };
            });
        }

        /** Enfoca en Monaco y actualiza los conectores visuales (corchete grande y flecha) */
        enfocarEnCodigo(lineaInicio, lineaFin = null, etiqueta = '', color = '#89b4fa') {
            const lIni = Math.max(1, lineaInicio);
            const sym = this.obtenerSimboloEnLinea(lIni);
            const padre = (sym && sym.padreId) ? this.estructuraCodigo.simbolos.find(s => s.id === sym.padreId) : null;
            const lFin = lineaFin ? Math.max(lIni, lineaFin) : (sym ? sym.lineaFin : lIni);
            const tit = etiqueta || (sym ? `${sym.tipo} ${sym.nombre}` : `L${lIni}`);

            this.conectorFoco = {
                activo: true,
                lineaInicio: lIni,
                lineaFin: lFin,
                tipo: sym ? sym.tipo : 'bloque',
                nombre: sym ? sym.nombre : tit,
                etiqueta: tit,
                firma: sym ? sym.firma : tit,
                color: color || '#89b4fa',
                simboloId: sym ? sym.id : null,
                padre: padre ? {
                    id: padre.id,
                    lineaInicio: padre.lineaInicio,
                    lineaFin: padre.lineaFin,
                    tipo: padre.tipo,
                    nombre: padre.nombre,
                    etiqueta: `class ${padre.nombre}`,
                    firma: padre.firma,
                    totalLineas: padre.totalLineas,
                    color: '#cba6f7'
                } : null
            };

            if (sym) {
                this.estructuraCodigo.simboloActivo = sym;
                this.estructuraCodigo.simboloPadre = padre;
                const camino = [
                    { id: 'root_file', tipo: 'file', nombre: this.archivoActivo.split('/').pop(), linea: 1 }
                ];
                if (padre) {
                    camino.push({ id: padre.id, tipo: padre.tipo, nombre: `${padre.tipo} ${padre.nombre}`, linea: padre.lineaInicio });
                }
                camino.push({ id: sym.id, tipo: sym.tipo, nombre: `${sym.tipo} ${sym.nombre}`, linea: sym.lineaInicio });
                this.estructuraCodigo.caminoJerarquico = camino;
                this._actualizarBreadcrumbsDOM();
                this._actualizarArbolASTDOM();
            }

            const ed = window.editorMgr ? window.editorMgr.editor : null;
            if (ed) {
                try {
                    ed.revealLineInCenter(lIni);
                    ed.setPosition({ lineNumber: lIni, column: 1 });
                    this._aplicarDecoracionMonaco(ed, lIni, lFin, color);
                } catch (e) {}
            }

            this.actualizarOverlay();
        }

        _aplicarDecoracionMonaco(ed, lineaIni, lineaFin, color) {
            if (!ed || typeof monaco === 'undefined') return;

            const claseResalte = color.includes('a6e3a1')
                ? 'prig-line-highlight-note'
                : color.includes('f9e2af')
                ? 'prig-line-highlight-opt'
                : 'prig-line-highlight-reasoning';

            this._decoracionesMonaco = ed.deltaDecorations(this._decoracionesMonaco, [
                {
                    range: new monaco.Range(lineaIni, 1, lineaFin, 1),
                    options: {
                        isWholeLine: true,
                        className: claseResalte,
                        overviewRuler: {
                            color: color,
                            position: monaco.editor.OverviewRulerLane.Right
                        }
                    }
                }
            ]);
        }

        /** Aplica un parche sugerido por el modelo en Monaco con soporte completo de Deshacer (Ctrl+Z) */
        aplicarParcheEnCodigo(lineaIni, lineaFin, nuevoCodigo) {
            const ed = window.editorMgr ? window.editorMgr.editor : null;
            if (!ed || typeof monaco === 'undefined') return;

            try {
                const model = ed.getModel();
                if (!model) return;

                const lineaRealFin = Math.min(model.getLineCount(), lineaFin);
                const maxCol = model.getLineMaxColumn(lineaRealFin);

                ed.pushUndoStop();
                ed.executeEdits('prig-reasoning-patch', [
                    {
                        range: new monaco.Range(lineaIni, 1, lineaRealFin, maxCol),
                        text: nuevoCodigo
                    }
                ]);
                ed.pushUndoStop();

                if (window.layoutMgr) {
                    window.layoutMgr.mensajeEstado(`✨ Solución aplicada con éxito en líneas ${lineaIni}-${lineaRealFin}`, 4000);
                }

                this.analizarCodigoBuffer(model.getValue(), this.archivoActivo);
                this.renderizar();
                this.actualizarOverlay();
            } catch (err) {
                console.error('Error aplicando parche en código:', err);
            }
        }

        /** Actualiza el SVG Overlay con flechas curvas y corchetes grandes jerárquicos */
        actualizarOverlay() {
            if (typeof requestAnimationFrame === 'undefined') return;
            if (this._timerRedibujado) cancelAnimationFrame(this._timerRedibujado);
            this._timerRedibujado = requestAnimationFrame(() => this._dibujarConectoresSVG());
        }

        _dibujarConectoresSVG() {
            const svg = document.getElementById('editor-overlay-conectores');
            if (!svg) return;

            const gCorchetes = svg.getElementById('capa-corchetes-codigo');
            const gFlechas = svg.getElementById('capa-flechas-codigo');
            const gBadges = svg.getElementById('capa-badges-codigo');
            if (!gCorchetes || !gFlechas || !gBadges) return;

            gCorchetes.innerHTML = '';
            gFlechas.innerHTML = '';
            gBadges.innerHTML = '';

            if (!this.relacionVisualActiva || !this.conectorFoco.activo || !this.panelVisible) {
                return;
            }

            const ed = window.editorMgr ? window.editorMgr.editor : null;
            if (!ed) return;

            const domNode = ed.getDomNode();
            const wrapper = document.getElementById('editor-area-wrapper');
            const panel = document.getElementById('editor-panel-razonamiento');
            if (!domNode || !wrapper || !panel) return;

            const wrapRect = wrapper.getBoundingClientRect();
            const edRect = domNode.getBoundingClientRect();
            const panelRect = panel.getBoundingClientRect();

            const ini = this.conectorFoco.lineaInicio;
            const fin = this.conectorFoco.lineaFin;
            const padre = this.conectorFoco.padre;
            const model = ed.getModel();
            if (!model || ini > model.getLineCount()) return;

            try {
                const lineHeight = ed.getOption(monaco.editor.EditorOption.lineHeight) || 20;
                const scrollTop = ed.getScrollTop();
                const margenSuperior = edRect.top - wrapRect.top;
                const margenInferior = margenSuperior + edRect.height;

                // Posición X base del corchete en el editor
                const xBaseEditor = (edRect.left - wrapRect.left);
                const anchoEditor = edRect.width;
                const xCorchete = Math.min(xBaseEditor + anchoEditor - 24, xBaseEditor + 480);
                const profCorchete = 14;

                // -------------------------------------------------------------
                // 1. DIBUJAR CORCHETE PADRE EXTERIOR (JERÁRQUICO / CLASE)
                // -------------------------------------------------------------
                if (this.configJerarquia.modoCorchetes === 'jerarquico' && padre && padre.lineaInicio) {
                    const yPadreTop = ed.getTopForLineNumber(padre.lineaInicio) - scrollTop;
                    const yPadreBottom = ed.getTopForLineNumber(padre.lineaFin) - scrollTop + lineHeight - 4;
                    const yPadreIniReal = margenSuperior + yPadreTop + 2;
                    const yPadreFinReal = margenSuperior + yPadreBottom;

                    if (yPadreFinReal >= margenSuperior - 30 && yPadreIniReal <= margenInferior + 30) {
                        const yPadreDrawIni = Math.max(margenSuperior + 2, yPadreIniReal);
                        const yPadreDrawFin = Math.min(margenInferior - 2, yPadreFinReal);

                        const xCorchetePadre = xCorchete + 16;
                        const profPadre = 10;
                        const colorPadre = padre.color || '#cba6f7';

                        const dPadre = `
                            M ${xCorchetePadre} ${yPadreDrawIni}
                            H ${xCorchetePadre - profPadre}
                            V ${yPadreDrawFin}
                            H ${xCorchetePadre}
                        `;
                        const pathPadre = document.createElementNS('http://www.w3.org/2000/svg', 'path');
                        pathPadre.setAttribute('class', 'conector-bracket-outer');
                        pathPadre.setAttribute('d', dPadre);
                        pathPadre.setAttribute('stroke', colorPadre);
                        gCorchetes.appendChild(pathPadre);

                        // Badge superior del corchete padre (interactivo)
                        const totalLineasPadre = padre.totalLineas || (padre.lineaFin - padre.lineaInicio + 1);
                        const etiquetaPadre = `📦 class ${padre.nombre} · ${totalLineasPadre}L`;
                        const anchoBadgePadre = Math.min(240, Math.max(100, etiquetaPadre.length * 6.5 + 20));
                        const xBadgePadre = xCorchetePadre - profPadre - anchoBadgePadre - 4;
                        const yBadgePadre = Math.max(margenSuperior + 4, yPadreDrawIni);

                        const gBadgePadre = document.createElementNS('http://www.w3.org/2000/svg', 'g');
                        gBadgePadre.setAttribute('class', 'conector-badge-parent');
                        gBadgePadre.setAttribute('title', `Ámbito de Clase: ${padre.nombre} (L${padre.lineaInicio}-L${padre.lineaFin}). Clic para enfocar.`);
                        gBadgePadre.innerHTML = `
                            <rect x="${xBadgePadre}" y="${yBadgePadre}" width="${anchoBadgePadre}" height="17" rx="3.5"
                                  fill="rgba(17, 17, 27, 0.95)" stroke="${colorPadre}" stroke-width="1.2"
                                  filter="drop-shadow(0 2px 6px rgba(0,0,0,0.5))" />
                            <text x="${xBadgePadre + anchoBadgePadre / 2}" y="${yBadgePadre + 12}" fill="#f8fafc"
                                  text-anchor="middle" font-size="9" font-family="'Fira Code', monospace" font-weight="700">
                                ${this._escaparHtml(etiquetaPadre)}
                            </text>
                        `;
                        gBadgePadre.onclick = (e) => {
                            e.stopPropagation();
                            this.enfocarEnCodigo(padre.lineaInicio, padre.lineaFin, `class ${padre.nombre}`, colorPadre);
                        };
                        gBadges.appendChild(gBadgePadre);
                    }
                }

                // -------------------------------------------------------------
                // 2. DIBUJAR CORCHETE INTERIOR (MÉTODO / FUNCIÓN ACTIVA)
                // -------------------------------------------------------------
                const y1Top = ed.getTopForLineNumber(ini) - scrollTop;
                const y2Top = ed.getTopForLineNumber(fin) - scrollTop;
                const yInicio = margenSuperior + y1Top + 2;
                const yFin = margenSuperior + y2Top + lineHeight - 4;
                const yCentro = (yInicio + yFin) / 2;

                if (yFin >= margenSuperior - 20 && yInicio <= margenInferior + 20) {
                    const color = this.conectorFoco.color || '#89b4fa';
                    const idMarcador = color.includes('a6e3a1')
                        ? 'flecha-conector-verde'
                        : color.includes('cba6f7')
                        ? 'flecha-conector-morado'
                        : 'flecha-conector-azul';

                    const dCorchete = `
                        M ${xCorchete} ${yInicio}
                        H ${xCorchete - profCorchete}
                        V ${yFin}
                        H ${xCorchete}
                    `;
                    const pathCorchete = document.createElementNS('http://www.w3.org/2000/svg', 'path');
                    pathCorchete.setAttribute('class', 'conector-bracket-path conector-bracket-inner');
                    pathCorchete.setAttribute('d', dCorchete);
                    pathCorchete.setAttribute('stroke', color);
                    gCorchetes.appendChild(pathCorchete);

                    // Muesca central angular
                    const dMuesca = `
                        M ${xCorchete - profCorchete} ${yCentro - 6}
                        L ${xCorchete - profCorchete - 5} ${yCentro}
                        L ${xCorchete - profCorchete} ${yCentro + 6}
                    `;
                    const pathMuesca = document.createElementNS('http://www.w3.org/2000/svg', 'path');
                    pathMuesca.setAttribute('d', dMuesca);
                    pathMuesca.setAttribute('stroke', color);
                    pathMuesca.setAttribute('stroke-width', '2');
                    pathMuesca.setAttribute('fill', 'none');
                    gCorchetes.appendChild(pathMuesca);

                    // -------------------------------------------------------------
                    // 3. FLECHA CURVA BÉZIER DESDE EL PANEL DE RAZONAMIENTO
                    // -------------------------------------------------------------
                    const xPanel = (panelRect.left - wrapRect.left);
                    const yPanelInicio = Math.min(wrapRect.height - 40, Math.max(60, yCentro));
                    const cp1X = xPanel - (xPanel - xCorchete) * 0.45;
                    const cp1Y = yPanelInicio;
                    const cp2X = xCorchete + (xPanel - xCorchete) * 0.35;
                    const cp2Y = yCentro;

                    const dFlecha = `
                        M ${xPanel} ${yPanelInicio}
                        C ${cp1X} ${cp1Y}, ${cp2X} ${cp2Y}, ${xCorchete + 4} ${yCentro}
                    `;
                    const pathFlecha = document.createElementNS('http://www.w3.org/2000/svg', 'path');
                    pathFlecha.setAttribute('class', 'conector-arrow-path');
                    pathFlecha.setAttribute('d', dFlecha);
                    pathFlecha.setAttribute('stroke', color);
                    pathFlecha.setAttribute('marker-end', `url(#${idMarcador})`);
                    gFlechas.appendChild(pathFlecha);

                    // -------------------------------------------------------------
                    // 4. BADGE FLOTANTE DEL SÍMBOLO ACTIVO
                    // -------------------------------------------------------------
                    const totalLineasBloque = fin - ini + 1;
                    const prefijoIcono = (this.conectorFoco.tipo === 'class') ? '📦' : ((this.conectorFoco.tipo || '').includes('async') ? '⚡' : '⚡');
                    const etiquetaTexto = `${prefijoIcono} ${this.conectorFoco.etiqueta || `L${ini}-${fin}`} · ${totalLineasBloque}L`;
                    const anchoBadge = Math.min(260, Math.max(90, etiquetaTexto.length * 6.6 + 22));
                    const altoBadge = 18;
                    const xBadge = xCorchete - profCorchete - anchoBadge - 8;
                    const yBadge = yCentro - altoBadge / 2;

                    const gBadge = document.createElementNS('http://www.w3.org/2000/svg', 'g');
                    gBadge.setAttribute('class', 'conector-badge-callout');
                    gBadge.setAttribute('title', `Bloque: ${this.conectorFoco.firma || this.conectorFoco.etiqueta}. Líneas ${ini}-${fin}.`);
                    gBadge.innerHTML = `
                        <rect x="${xBadge}" y="${yBadge}" width="${anchoBadge}" height="${altoBadge}" rx="4"
                              fill="rgba(17, 24, 39, 0.94)" stroke="${color}" stroke-width="1.3"
                              filter="drop-shadow(0 2px 8px rgba(0,0,0,0.5))" />
                        <text x="${xBadge + anchoBadge / 2}" y="${yBadge + 12.5}" fill="#f8fafc"
                              text-anchor="middle" font-size="9.5" font-family="'Fira Code', monospace" font-weight="700">
                            ${this._escaparHtml(etiquetaTexto)}
                        </text>
                    `;
                    gBadges.appendChild(gBadge);
                }

            } catch (err) {
                // Monaco no listo o fuera de vista
            }
        }

        /** Notifica al manager el movimiento del cursor en Monaco */
        notificarCursor(ed) {
            if (!ed) return;
            const pos = ed.getPosition();
            if (pos && pos.lineNumber) {
                this.lineaCursor = pos.lineNumber;
                const btnNotas = document.getElementById('btn-mostrar-form-nota');
                if (btnNotas) {
                    btnNotas.innerHTML = `<i class="fa-solid fa-plus"></i> Añadir Nota en Línea ${this.lineaCursor}`;
                }
                const inputLinea = document.getElementById('nota-input-linea-ini');
                if (inputLinea && !inputLinea.matches(':focus')) {
                    inputLinea.value = this.lineaCursor;
                }

                if (this.configJerarquia.autoSincronizarCursor) {
                    this.sincronizarAmbitoConCursor(this.lineaCursor, false);
                }
            }
        }

        /** Actualizaciones al cambiar código en el editor */
        alCambiarCodigo(ed) {
            if (this._timerParseo) clearTimeout(this._timerParseo);
            this._timerParseo = setTimeout(() => {
                if (ed && ed.getModel()) {
                    this.analizarCodigoBuffer(ed.getModel().getValue(), this.archivoActivo);
                    this.renderizar();
                }
            }, 180);
            this.actualizarOverlay();
        }

        /** Recibe decisiones y telemetría emitidas por el Director / LLM */
        actualizarDesdeDecision(decision) {
            if (!decision) return;

            if (decision.dialogo) {
                this.razonamiento.dialogoTexto = decision.dialogo;
            }
            if (decision.metricas) {
                this.razonamiento.metricas = decision.metricas;
            }
            if (decision.consejo) {
                const c = decision.consejo;
                this.razonamiento.hallazgos[0] = {
                    id: 'h-live',
                    categoria: c.tipo || 'arq',
                    categoriaTexto: c.categoria || 'Arquitectura',
                    lineaInicio: c.linea_inicio || 1,
                    lineaFin: c.linea_fin || 6,
                    titulo: c.titulo || 'Optimización Arquitectónica',
                    detalle: c.detalle || 'Revisión en vivo por el evaluador.',
                    codigoSugerido: c.sugerencia_codigo || '',
                    color: '#89b4fa'
                };
                this.conectorFoco.lineaInicio = c.linea_inicio || 1;
                this.conectorFoco.lineaFin = c.linea_fin || 6;
                this.conectorFoco.etiqueta = c.titulo || 'Revisión LLM';
            }
            if (decision.flujo_grafico && decision.flujo_grafico.pasos) {
                this.razonamiento.grafoNodos = decision.flujo_grafico.pasos.map((p, i) => ({
                    id: `n-${i}`,
                    nombre: p.titulo || `PASO ${i+1}`,
                    linea: p.linea || (i * 10 + 1),
                    sub: p.subtitulo || 'Operación de ejecución'
                }));
            }

            this.renderizar();
            this.actualizarOverlay();
        }

        /** Actualiza el stream en vivo de tokens CoT / diálogo */
        actualizarStreamDialogo(textoStream) {
            this.razonamiento.dialogoTexto = textoStream;
            this.razonamiento.estado = 'pensando';

            const cotBox = document.querySelector('.razonamiento-cot-content');
            if (cotBox) {
                const liveEl = cotBox.querySelector('div:last-child');
                if (liveEl) liveEl.textContent = `💬 ${textoStream}`;
            }
        }

        dispararAnalisisManual() {
            this.razonamiento.estado = 'pensando';
            this.renderizar();

            if (window.DIRECTOR_ASCII) {
                window.DIRECTOR_ASCII.dispararDecisionDirector('solicitud_manual').finally(() => {
                    this.razonamiento.estado = 'listo';
                    this.renderizar();
                });
            } else {
                setTimeout(() => {
                    this.razonamiento.estado = 'listo';
                    this.renderizar();
                }, 1200);
            }
        }

        // ==========================================
        // GESTIÓN DE NOTAS TÉCNICAS (PERSISTENCIA)
        // ==========================================

        _obtenerClaveStorage() {
            return `prig_notas_${this.archivoActivo.replace(/[\/\\:]/g, '_')}`;
        }

        _cargarNotasAlmacenadas() {
            try {
                const clave = this._obtenerClaveStorage();
                const guardadas = localStorage.getItem(clave);
                if (guardadas) {
                    this.notasPorArchivo[this.archivoActivo] = JSON.parse(guardadas);
                } else if (!this.notasPorArchivo[this.archivoActivo]) {
                    // Notas iniciales de muestra profesionales para arrancar
                    this.notasPorArchivo[this.archivoActivo] = [
                        {
                            id: 'n-init-1',
                            lineaInicio: 12,
                            lineaFin: 18,
                            categoria: 'arq',
                            titulo: 'Validación de Contratos y Precondiciones',
                            detalle: 'Aislar las excepciones de parámetros antes de instanciar la conexión del socket.'
                        },
                        {
                            id: 'n-init-2',
                            lineaInicio: 34,
                            lineaFin: 40,
                            categoria: 'opt',
                            titulo: 'Posible cuello de botella en parseo JSON',
                            detalle: 'Si el lote excede 10MB, migrar a streaming con orjson o ujson.'
                        }
                    ];
                }
            } catch (e) {
                this.notasPorArchivo[this.archivoActivo] = [];
            }
        }

        _guardarNotasStorage() {
            try {
                const clave = this._obtenerClaveStorage();
                const lista = this.notasPorArchivo[this.archivoActivo] || [];
                localStorage.setItem(clave, JSON.stringify(lista));
                this._actualizarContadorNotas();
            } catch (e) {}
        }

        _obtenerNotasArchivoActual() {
            if (!this.notasPorArchivo[this.archivoActivo]) {
                this._cargarNotasAlmacenadas();
            }
            return this.notasPorArchivo[this.archivoActivo] || [];
        }

        agregarNota(datos) {
            const notas = this._obtenerNotasArchivoActual();
            const nueva = {
                id: 'n-' + Date.now(),
                lineaInicio: datos.lineaInicio || this.lineaCursor,
                lineaFin: datos.lineaFin || null,
                categoria: datos.categoria || 'arq',
                titulo: datos.titulo || 'Nueva Anotación',
                detalle: datos.detalle || ''
            };
            notas.unshift(nueva);
            this.notasPorArchivo[this.archivoActivo] = notas;
            this._guardarNotasStorage();
        }

        eliminarNota(id) {
            let notas = this._obtenerNotasArchivoActual();
            notas = notas.filter(n => n.id !== id);
            this.notasPorArchivo[this.archivoActivo] = notas;
            this._guardarNotasStorage();
        }

        _actualizarContadorNotas() {
            const total = this._obtenerNotasArchivoActual().length;
            const badge = document.getElementById('badge-notas-contador');
            if (badge) badge.textContent = String(total);
        }

        _escaparHtml(str) {
            return String(str || '').replace(/[&<>"']/g, c => ({
                '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
            }[c]));
        }
    }

    // Instancia global disponible en window
    if (typeof window !== 'undefined') {
        window.EditorRazonamiento = new EditorRazonamientoManager();
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', () => window.EditorRazonamiento.init());
        } else {
            window.EditorRazonamiento.init();
        }
    }

})(typeof window !== 'undefined' ? window : globalThis);

