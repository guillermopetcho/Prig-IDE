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

                // Crear SVG Overlay de Conexiones Visuales (Oculto: los números de línea iluminados reemplazan los corchetes)
                const svgOverlay = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
                svgOverlay.id = 'editor-overlay-conectores';
                svgOverlay.setAttribute('class', 'editor-overlay-conectores');
                svgOverlay.style.display = 'none';
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

            const ed = window.editorMgr ? window.editorMgr.editor : null;
            if (ed) {
                try {
                    if (enfocarMonaco) {
                        ed.revealLineInCenter(activo.lineaInicio);
                        ed.setPosition({ lineNumber: activo.lineaInicio, column: 1 });
                    }
                    this._aplicarDecoracionMonaco(ed, activo.lineaInicio, activo.lineaFin, colorActivo);
                } catch (e) {}
            }

            this.actualizarOverlay();
            this._actualizarScopeHeaderDOM();
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

                <!-- Ámbito Activo / Scope Header -->
                ${esRaz ? this._renderizarScopeHeaderHTML() : ''}

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

        _renderizarScopeHeaderHTML() {
            const sym = this.estructuraCodigo.simboloActivo;
            const padre = this.estructuraCodigo.simboloPadre;
            const ini = this.conectorFoco.lineaInicio || 1;
            const fin = this.conectorFoco.lineaFin || ini;
            const esClase = sym && sym.tipo === 'class';
            const icono = esClase ? 'fa-solid fa-cube' : (sym && sym.tipo.includes('async') ? 'fa-solid fa-bolt-lightning' : 'fa-solid fa-bolt');
            const colorIcono = esClase ? '#cba6f7' : '#00f0ff';

            let textoAmbito = '';
            if (padre && sym && padre.id !== sym.id) {
                textoAmbito = `${padre.nombre} › ${sym.nombre}`;
            } else if (sym) {
                textoAmbito = `${sym.tipo} ${sym.nombre}`;
            } else {
                const nombreBase = this.archivoActivo.split('/').pop();
                textoAmbito = `${nombreBase}`;
            }

            return `
                <div class="razonamiento-scope-header" id="razonamiento-scope-header">
                    <div class="razonamiento-scope-path" title="Ámbito activo en el editor">
                        <i class="${icono}" style="color: ${colorIcono}; font-size: 10px;"></i>
                        <span style="font-weight: 600;">${this._escaparHtml(textoAmbito)}</span>
                    </div>
                    <span class="razonamiento-scope-lineas" id="btn-scope-jump" title="Líneas resaltadas en el editor (Clic para centrar)" data-scope-ini="${ini}" data-scope-fin="${fin}">
                        <i class="fa-solid fa-crosshairs"></i> L${ini}–L${fin}
                    </span>
                </div>
            `;
        }

        _actualizarScopeHeaderDOM() {
            const header = document.getElementById('razonamiento-scope-header');
            if (header && this.tabActiva === 'razonamiento') {
                const tempDiv = document.createElement('div');
                tempDiv.innerHTML = this._renderizarScopeHeaderHTML();
                const nuevo = tempDiv.firstElementChild;
                if (nuevo) {
                    header.replaceWith(nuevo);
                    this._conectarEventosScopeHeader(nuevo);
                }
            }
        }

        _actualizarBreadcrumbsDOM() {
            this._actualizarScopeHeaderDOM();
        }

        _actualizarArbolASTDOM() {
            // Unificado en el Scope Header para evitar redundancia visual
        }

        _conectarEventosScopeHeader(header) {
            if (!header) return;
            const btnJump = header.querySelector('#btn-scope-jump');
            if (btnJump) {
                btnJump.onclick = () => {
                    const ini = parseInt(btnJump.dataset.scopeIni, 10) || 1;
                    const fin = parseInt(btnJump.dataset.scopeFin, 10) || ini;
                    this.enfocarEnCodigo(ini, fin, 'Ámbito Activo', '#00f0ff');
                };
            }
        }

        _renderizarVistaRazonamiento() {
            const r = this.razonamiento;
            return `
                <!-- Proceso de Razonamiento CoT (Cadena de Pensamiento) -->
                <div class="razonamiento-cot-box">
                    <div class="razonamiento-cot-header" id="cot-toggle-btn" style="cursor: pointer;">
                        <span class="cot-titulo">
                            <i class="fa-solid fa-microchip" style="color: #cba6f7;"></i>
                            Razonamiento CoT (${r.cotPasos.length} pasos)
                        </span>
                        <i class="fa-solid ${r.cotExpandido ? 'fa-chevron-up' : 'fa-chevron-down'}" style="font-size: 10px;"></i>
                    </div>
                    <div class="razonamiento-cot-content" style="display: ${r.cotExpandido ? 'block' : 'none'};">
                        ${r.cotPasos.map(p => `
                            <div class="razonamiento-cot-step">
                                <span class="razonamiento-step-num">#${p.num}</span>
                                <div>
                                    <div style="font-weight: 700; color: #f8fafc; font-size: 10.5px;">${this._escaparHtml(p.titulo)}</div>
                                    <div style="color: #bac2de; font-size: 10px; margin-top: 2px;">${this._escaparHtml(p.detalle)}</div>
                                </div>
                            </div>
                        `).join('')}
                        <div style="margin-top: 8px; padding-top: 6px; border-top: 1px dashed rgba(255,255,255,0.08); font-size: 10.5px; color: #a6e3a1; font-family: 'Fira Code', monospace; line-height: 1.4;">
                            💬 ${this._escaparHtml(r.dialogoTexto)}
                        </div>
                    </div>
                </div>

                <!-- Diagnóstico y Mejoras Sugeridas -->
                <div style="font-size: 11px; font-weight: 800; text-transform: uppercase; letter-spacing: 0.4px; color: #00f0ff; display: flex; align-items: center; justify-content: space-between; margin-top: 6px; margin-bottom: 2px;">
                    <span style="display: flex; align-items: center; gap: 6px;">
                        <i class="fa-solid fa-wand-magic-sparkles"></i> Hallazgos y Soluciones
                    </span>
                    <span style="font-size: 9.5px; color: #a6adc8; font-weight: 600;">${r.hallazgos.length} detectados</span>
                </div>

                ${r.hallazgos.map((h) => {
                    const esActivo = (this.conectorFoco.lineaInicio === h.lineaInicio);
                    return `
                    <div class="razonamiento-card ${esActivo ? 'activa' : ''}" data-hallazgo-id="${h.id}">
                        <div class="razonamiento-card-meta">
                            <span class="razonamiento-badge-categoria ${h.categoria}">${h.categoriaTexto}</span>
                            <span class="razonamiento-badge-linea" title="Resaltar líneas en editor" data-accion="conectar" data-linea-ini="${h.lineaInicio}" data-linea-fin="${h.lineaFin}" data-titulo="${this._escaparHtml(h.titulo)}" data-color="${h.color}">
                                <i class="fa-solid fa-crosshairs"></i> L${h.lineaInicio}–L${h.lineaFin}
                            </span>
                        </div>
                        <div class="razonamiento-card-titulo">${this._escaparHtml(h.titulo)}</div>
                        <div class="razonamiento-card-detalle">${this._escaparHtml(h.detalle)}</div>
                        ${h.codigoSugerido ? `<div class="razonamiento-codigo-snippet">${this._escaparHtml(h.codigoSugerido)}</div>` : ''}
                        <div class="razonamiento-card-acciones">
                            <button class="razonamiento-btn-conectar" data-accion="conectar" data-linea-ini="${h.lineaInicio}" data-linea-fin="${h.lineaFin}" data-titulo="${this._escaparHtml(h.titulo)}" data-color="${h.color}">
                                <i class="fa-solid fa-highlighter"></i> Resaltar Código
                            </button>
                            ${h.codigoSugerido ? `
                                <button class="razonamiento-btn-aplicar" data-accion="aplicar" data-linea-ini="${h.lineaInicio}" data-linea-fin="${h.lineaFin}" data-codigo="${encodeURIComponent(h.codigoSugerido)}">
                                    <i class="fa-solid fa-check-double"></i> Aplicar
                                </button>
                            ` : ''}
                        </div>
                    </div>
                `;}).join('')}
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
            // Eventos del Scope Header
            this._conectarEventosScopeHeader(panel.querySelector('#razonamiento-scope-header'));

            // Acordeón CoT
            const toggleCot = panel.querySelector('#cot-toggle-btn');
            if (toggleCot) {
                toggleCot.onclick = () => {
                    this.razonamiento.cotExpandido = !this.razonamiento.cotExpandido;
                    this.renderizar();
                };
            }

            // Conectar o resaltar hallazgo en el código
            panel.querySelectorAll('[data-accion="conectar"]').forEach(btn => {
                btn.onclick = (e) => {
                    e.stopPropagation();
                    const ini = parseInt(btn.dataset.lineaIni, 10);
                    const fin = parseInt(btn.dataset.lineaFin, 10);
                    const tit = btn.dataset.titulo;
                    const col = btn.dataset.color || '#00f0ff';
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

        /** Enfoca en Monaco y resalta las líneas en el editor con números de línea brillantes */
        enfocarEnCodigo(lineaInicio, lineaFin = null, etiqueta = '', color = '#00f0ff') {
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
                color: color || '#00f0ff',
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
                this._actualizarScopeHeaderDOM();
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

            const esVerde = (color && color.includes('a6e3a1'));
            const esMorado = (color && color.includes('cba6f7'));

            const marginClase = esVerde
                ? 'prig-line-number-bright-green'
                : esMorado
                ? 'prig-line-number-bright-purple'
                : 'prig-line-number-bright';

            const gutterClase = esVerde
                ? 'prig-gutter-neon-bar-green'
                : esMorado
                ? 'prig-gutter-neon-bar-purple'
                : 'prig-gutter-neon-bar';

            const tintClase = esVerde
                ? 'prig-code-active-tint-green'
                : 'prig-code-active-tint';

            const hexColor = esVerde ? '#a6e3a1' : (esMorado ? '#cba6f7' : '#00f0ff');

            this._decoracionesMonaco = ed.deltaDecorations(this._decoracionesMonaco, [
                {
                    range: new monaco.Range(lineaIni, 1, lineaFin, 1),
                    options: {
                        isWholeLine: true,
                        className: tintClase,
                        marginClassName: marginClase,
                        linesDecorationsClassName: gutterClase,
                        overviewRuler: {
                            color: hexColor,
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
            svg.style.display = 'none';

            const gCorchetes = svg.getElementById('capa-corchetes-codigo');
            const gFlechas = svg.getElementById('capa-flechas-codigo');
            const gBadges = svg.getElementById('capa-badges-codigo');
            if (gCorchetes) gCorchetes.innerHTML = '';
            if (gFlechas) gFlechas.innerHTML = '';
            if (gBadges) gBadges.innerHTML = '';
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

