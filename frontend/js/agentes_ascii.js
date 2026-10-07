/**
 * ============================================================================
 * PERSONAJE Y MOTOR DE RELACIÓN VISUAL ASCII (PANEL VERTICAL HUD DERECHO)
 * ============================================================================
 * - Panel HUD vertical fijado y pegado al margen derecho (altura > anchura).
 * - Pestañas interactivas de Telemetría: [1. DIÁLOGO] [2. CONSEJOS] [3. FLUJO].
 * - Motor de relación visual: Haz láser telemétrico, paquetes de datos, corchetes
 *   de rango multilínea en el código y badges flotantes de buenas prácticas.
 * - Personaje ASCII miniatura posicionado en la zona inferior derecha con drones orbitales.
 */

(function(root) {
    'use strict';

    class PersonajeEvaluadorASCII {
        constructor(id, arteId, catArte, nombre, rol, opciones = {}) {
            this.id = id;
            this.arteId = arteId || 'TITAN_MECHA_COMBATE';
            this.catArte = catArte || 'ROBOTS_Y_MECHAS';
            this.nombre = nombre || 'Titán Mecha MK-VII';
            this.rol = rol || 'Evaluador de Arquitectura Táctica';

            // Ubicación del personaje: zona inferior derecha con Física de Resortes (Spring-Damper 2do Orden)
            this.xRatio = 0.88;
            this.yRatio = 0.88;
            this.currentX = 0;
            this.currentY = 0;
            this.targetX = 0;
            this.targetY = 0;
            this.vx = 0;
            this.vy = 0;
            this.springK = 0.055;
            this.springDamping = 0.80;
            this.impulsoX = 0;
            this.impulsoY = 0;
            this.animModoCentro = 0; // 0 = lateral derecho, 1 = centro de pantalla (Ctrl+Alt)
            this._iniciado = false;

            this.color = opciones.color || '#a6e3a1';
            this.fuente = opciones.fuente || 'bold 6px "Fira Code", monospace';
            this.interlineado = opciones.interlineado || 7;
            this.opacidadBase = opciones.opacidad || 0.60;
            this.opacidadActual = this.opacidadBase;

            // Metadatos y contexto activo del editor
            this.moduloActivo = 'main.py';
            this.lenguajeActivo = 'python';
            this.lineaActiva = 1;
            this.metricas = { complejidad: 'O(N)', calidad: 96, modularidad: 94, mantenibilidad: 95 };

            // Pestañas del HUD Vertical: 'dialogo' | 'consejos' | 'flujo' | 'debug'
            this.modoPestana = 'dialogo';
            this.pestanasDisponibles = ['dialogo', 'consejos', 'flujo', 'debug'];
            this.ultimoCambioPestana = performance.now();
            this.intervaloAutoCicloPestana = 14000; // auto-ciclo suave cada 14s

            // Estado de Sincronización del Depurador (Debugger Walk Engine)
            this.debugger = {
                activo: false,
                lineaActual: 1,
                stackFrames: ['<module> main.py:L1', 'ejecutar() -> L3'],
                variables: {
                    'ctx': '{status: "OK"}',
                    'payload': '<StreamBuffer 256b>',
                    'pc': '0x004A'
                },
                historialPasos: [],
                estadoEjecucion: 'PAUSED' // 'PAUSED' | 'STEPPING' | 'RUNNING' | 'EXCEPTION'
            };

            // Datos del Motor de Relación Visual
            this.consejo = {
                tipo: 'buenas_practicas',
                categoria: 'Clean Architecture',
                titulo: 'Modularización y Cláusula de Guarda',
                detalle: 'Aplica validación temprana de parámetros nulos para simplificar el flujo y reducir anidación.',
                linea_inicio: 1,
                linea_fin: 6,
                sugerencia_codigo: 'if not params: return fallback_state'
            };

            this.flujoAscii = [
                "[ENTRY: func()]",
                "   │",
                "   ▼",
                "[VALIDAR PARAMS]",
                "   │",
                "   ▼",
                "[PROCESAR DATOS]",
                "   │",
                "   ▼",
                "[RETURN RESULT]"
            ];

            // Ecosistema interactivo: haz de inspección elástico, corchete de rango y drones
            this.inspeccion = {
                activo: true,
                linea: 1,
                linea_fin: 6,
                x_foco: 0.35,
                y_foco: 0.35,
                currentX_foco: 0.35,
                currentY_foco: 0.35,
                vx_foco: 0,
                vy_foco: 0,
                modo: 'explicar',
                tipo_relacion: 'buenas_practicas',
                pulso: 0
            };

            this.drones = [
                { id: 'dron_alfa', angulo: 0, radio: 38, radioActual: 38, vRadio: 0, velocidad: 0.030, glifo: '◄●►', color: '#89b4fa' },
                { id: 'dron_beta', angulo: Math.PI, radio: 48, radioActual: 48, vRadio: 0, velocidad: -0.022, glifo: '⌖', color: '#cba6f7' }
            ];

            // Web Worker offloader para simulación física off-thread
            this.workerFisica = null;
            this.workerListo = false;
            this._iniciarWorkerFisica();

            // Paquetes de energía / partículas telemétricas en tránsito
            this.particulasHaz = [];
            for (let i = 0; i < 4; i++) {
                this.particulasHaz.push({ progreso: i * 0.25, velocidad: 0.008 });
            }

            // ================================================================
            // MOTOR DE FLUJO Y MOVIMIENTO DE GRÁFICOS (CODE WALKTHROUGH ENGINE)
            // ================================================================
            this.flujoGrafico = {
                activo: true,
                pasos: [
                    {
                        paso: 1,
                        etiqueta: "Entrada y Parámetros",
                        tipo: "entrada",
                        icono: "📥",
                        linea_inicio: 1,
                        linea_fin: 2,
                        x_foco: 0.35,
                        y_foco: 0.20,
                        posicion_agente: { x_ratio: 0.88, y_ratio: 0.88 },
                        explicacion: "Recepción de argumentos y validación de contratos de entrada.",
                        sugerencia: "def procesar(datos: list) -> dict:"
                    },
                    {
                        paso: 2,
                        etiqueta: "Cláusula de Guarda",
                        tipo: "guarda",
                        icono: "🛡️",
                        linea_inicio: 3,
                        linea_fin: 4,
                        x_foco: 0.35,
                        y_foco: 0.35,
                        posicion_agente: { x_ratio: 0.85, y_ratio: 0.81 },
                        explicacion: "Early Return para evitar anidación y descartar estados nulos.",
                        sugerencia: "if not datos: return None"
                    },
                    {
                        paso: 3,
                        etiqueta: "Cómputo & Pipeline",
                        tipo: "proceso",
                        icono: "⚡",
                        linea_inicio: 5,
                        linea_fin: 6,
                        x_foco: 0.35,
                        y_foco: 0.50,
                        posicion_agente: { x_ratio: 0.82, y_ratio: 0.74 },
                        explicacion: "Transformación lineal con baja huella de memoria y complejidad O(1).",
                        sugerencia: "lookup_set = set(datos)"
                    },
                    {
                        paso: 4,
                        etiqueta: "Emisión & Retorno",
                        tipo: "salida",
                        icono: "📤",
                        linea_inicio: 7,
                        linea_fin: 8,
                        x_foco: 0.35,
                        y_foco: 0.65,
                        posicion_agente: { x_ratio: 0.88, y_ratio: 0.88 },
                        explicacion: "Retorno determinista del estado procesado final.",
                        sugerencia: "return resultado"
                    }
                ],
                pasoActivoIndex: 0,
                tiempoInicioPaso: performance.now(),
                duracionPasoMs: 3400,
                reproduciendo: true,
                particulasRuta: []
            };

            // Inicializar partículas de viaje entre nodos del flujo
            for (let p = 0; p < 8; p++) {
                this.flujoGrafico.particulasRuta.push({
                    progreso: Math.random(),
                    velocidad: 0.005 + Math.random() * 0.008,
                    segmento: 0,
                    glifo: '•'
                });
            }

            // Animación suave de respiración / flotación en su puesto
            this.anguloFlotacion = 0;
            this.velocidadFlotacion = 0.025;
            this.amplitudFlotacion = 2.0;

            // Diálogo de razonamiento
            this.dialogo = {
                texto: "[EVALUACIÓN]: Analizando funciones, arquitectura y flujo lógico del código en tiempo real...",
                lineasFormateadas: [],
                charIndex: 0,
                tiempoInicio: performance.now(),
                duracion: 26000,
                opacidad: 0.85,
                ultimoCharTime: performance.now(),
                estado: "razonando"
            };

            // Enlazar eventos de click en el lienzo para interacción con los nodos del flujo
            this._iniciarListenersCanvas();
        }

        _iniciarWorkerFisica() {
            if (typeof window === 'undefined' || typeof Worker === 'undefined') return;
            try {
                this.workerFisica = new Worker('/static/js/worker_particulas.js');
                this.workerFisica.onmessage = (e) => {
                    const data = e.data;
                    if (!data || !data.tipo) return;
                    if (data.tipo === 'READY') {
                        this.workerListo = true;
                    } else if (data.tipo === 'PHYSICS_RESULT' && data.payload) {
                        this._aplicarResultadoWorker(data.payload);
                    }
                };
                this.workerFisica.postMessage({
                    tipo: 'INIT',
                    payload: {
                        w: window.innerWidth,
                        h: window.innerHeight,
                        springK: this.springK,
                        springDamping: this.springDamping
                    }
                });
            } catch (err) {
                // Fallback automático transparente en hilo principal
                this.workerFisica = null;
                this.workerListo = false;
            }
        }

        _aplicarResultadoWorker(res) {
            if (!res) return;
            // Sincronizar suavemente la física calculada en worker
            this.currentX = this.currentX * 0.2 + res.currentX * 0.8;
            this.currentY = this.currentY * 0.2 + res.currentY * 0.8;
            this.vx = res.vx || this.vx;
            this.vy = res.vy || this.vy;

            if (Array.isArray(res.drones) && this.drones) {
                res.drones.forEach((dRes, idx) => {
                    if (this.drones[idx]) {
                        this.drones[idx].x = dRes.x;
                        this.drones[idx].y = dRes.y;
                        this.drones[idx].radioActual = dRes.radioActual;
                    }
                });
            }

            if (Array.isArray(res.particulasRuta) && this.flujoGrafico && this.flujoGrafico.particulasRuta) {
                res.particulasRuta.forEach((pRes, idx) => {
                    if (this.flujoGrafico.particulasRuta[idx]) {
                        this.flujoGrafico.particulasRuta[idx].progreso = pRes.progreso;
                        this.flujoGrafico.particulasRuta[idx].segmento = pRes.segmento;
                        this.flujoGrafico.particulasRuta[idx].px = pRes.px;
                        this.flujoGrafico.particulasRuta[idx].py = pRes.py;
                    }
                });
            }
        }

        aplicarImpulso(ix, iy) {
            this.impulsoX += (ix || 0);
            this.impulsoY += (iy || 0);
            if (this.workerFisica && this.workerListo) {
                this.workerFisica.postMessage({
                    tipo: 'RESET_IMPULSO',
                    payload: { ix, iy }
                });
            }
        }

        _iniciarListenersCanvas() {
            if (typeof window === 'undefined') return;
            const handlerClick = (e) => {
                const w = window.innerWidth;
                const h = window.innerHeight;
                this.manejarClick(e.clientX, e.clientY, w, h);
            };
            window.addEventListener('click', handlerClick, { passive: true });

            // Atajos de Depurador Walk en Vivo: F10 (Step Over), F11 (Step Into), Shift+F11 (Step Out)
            const handlerKey = (e) => {
                if (e.key === 'F10') {
                    e.preventDefault();
                    this.pasoDebugger('over');
                } else if (e.key === 'F11') {
                    e.preventDefault();
                    if (e.shiftKey) {
                        this.pasoDebugger('out');
                    } else {
                        this.pasoDebugger('into');
                    }
                }
            };
            window.addEventListener('keydown', handlerKey);
        }

        iniciarDebugger(lineaInicial = 1) {
            this.debugger.activo = true;
            this.debugger.estadoEjecucion = 'STEPPING';
            this.debugger.lineaActual = Math.max(1, parseInt(lineaInicial) || 1);
            this.modoPestana = 'debug';
            this._sincronizarPasoDebugger();
        }

        toggleDebugger() {
            this.debugger.activo = !this.debugger.activo;
            this.debugger.estadoEjecucion = this.debugger.activo ? 'STEPPING' : 'PAUSED';
            if (this.debugger.activo) {
                this.modoPestana = 'debug';
                this._sincronizarPasoDebugger();
            }
        }

        pasoDebugger(tipo = 'over') {
            this.debugger.activo = true;
            this.debugger.estadoEjecucion = 'STEPPING';
            this.modoPestana = 'debug';

            // Avanzar a través de los nodos de la topología CFG o líneas del código
            if (this.flujoGrafico.pasos && this.flujoGrafico.pasos.length > 0) {
                if (tipo === 'over' || tipo === 'into') {
                    this.flujoGrafico.pasoActivoIndex = (this.flujoGrafico.pasoActivoIndex + 1) % this.flujoGrafico.pasos.length;
                } else if (tipo === 'out') {
                    this.flujoGrafico.pasoActivoIndex = this.flujoGrafico.pasos.length - 1; // Salto a return
                }
                const paso = this.flujoGrafico.pasos[this.flujoGrafico.pasoActivoIndex];
                this.debugger.lineaActual = paso.linea_inicio || 1;
            } else {
                this.debugger.lineaActual = (this.debugger.lineaActual % 20) + 1;
            }

            // Simular actualización de variables del Stack Frame
            const lAct = this.debugger.lineaActual;
            this.debugger.variables = {
                'pc': `0x${(lAct * 16).toString(16).toUpperCase().padStart(4, '0')}`,
                'linea': `L${lAct}`,
                'scope': lAct <= 2 ? 'Global' : 'LocalFunc',
                'frame': `exec_${this.moduloActivo || 'main'}:L${lAct}`
            };

            this.debugger.stackFrames = [
                `<module> ${this.moduloActivo || 'main.py'}:L1`,
                `run_pipeline() -> L${lAct}`,
                `eval_step(action='${tipo.toUpperCase()}')`
            ];

            // Inyectar impulso físico de resorte para respuesta táctil en el personaje
            this.aplicarImpulso(tipo === 'into' ? 2.5 : -2.5, -1.8);
            this._sincronizarPasoDebugger();
        }

        _sincronizarPasoDebugger() {
            const linea = this.debugger.lineaActual;
            this.inspeccion.linea = linea;
            this.inspeccion.linea_fin = linea;
            this.inspeccion.tipo_relacion = 'flujo';

            // NO mover la vista ni el cursor del programador automáticamente: el modelo solo apunta con corchetes en el fondo
            this.evaluarCodigo(`[🐞 DEPURADOR]: Inspeccionando L${linea}. Frame [${this.debugger.variables.frame}]. Presiona F10 para Paso Siguiente.`, 16000);
        }

        capturarExcepcionRuntime(archivo, linea, mensaje) {
            this.debugger.activo = true;
            this.debugger.estadoEjecucion = 'EXCEPTION';
            this.debugger.lineaActual = parseInt(linea) || 1;
            this.modoPestana = 'debug';

            this.inspeccion.linea = this.debugger.lineaActual;
            this.inspeccion.linea_fin = this.debugger.lineaActual;
            this.inspeccion.tipo_relacion = 'seguridad';

            this.evaluarCodigo(`[🚨 EXCEPCIÓN RUNTIME]: ${mensaje || 'Error detectado'} en ${archivo || 'main.py'}:L${linea}.`, 24000);
            this._sincronizarPasoDebugger();
        }

        establecerFlujoGrafico(flujoData) {
            if (!flujoData || typeof flujoData !== 'object') return;
            if (Array.isArray(flujoData.pasos) && flujoData.pasos.length > 0) {
                this.flujoGrafico.pasos = flujoData.pasos;
                this.flujoGrafico.pasoActivoIndex = 0;
                this.flujoGrafico.tiempoInicioPaso = performance.now();
                if (typeof flujoData.velocidad_ms === 'number') {
                    this.flujoGrafico.duracionPasoMs = flujoData.velocidad_ms;
                }
                this.flujoGrafico.activo = true;
                this._aplicarPasoActivo();
            }
        }

        siguientePaso() {
            if (!this.flujoGrafico.pasos || this.flujoGrafico.pasos.length === 0) return;
            this.flujoGrafico.pasoActivoIndex = (this.flujoGrafico.pasoActivoIndex + 1) % this.flujoGrafico.pasos.length;
            this.flujoGrafico.tiempoInicioPaso = performance.now();
            this._aplicarPasoActivo();
        }

        anteriorPaso() {
            if (!this.flujoGrafico.pasos || this.flujoGrafico.pasos.length === 0) return;
            this.flujoGrafico.pasoActivoIndex = (this.flujoGrafico.pasoActivoIndex - 1 + this.flujoGrafico.pasos.length) % this.flujoGrafico.pasos.length;
            this.flujoGrafico.tiempoInicioPaso = performance.now();
            this._aplicarPasoActivo();
        }

        toggleReproduccion() {
            this.flujoGrafico.reproduciendo = !this.flujoGrafico.reproduciendo;
            this.flujoGrafico.tiempoInicioPaso = performance.now();
        }

        irAPaso(index) {
            if (index >= 0 && index < this.flujoGrafico.pasos.length) {
                this.flujoGrafico.pasoActivoIndex = index;
                this.flujoGrafico.tiempoInicioPaso = performance.now();
                this._aplicarPasoActivo();
            }
        }

        _aplicarPasoActivo() {
            const paso = this.flujoGrafico.pasos[this.flujoGrafico.pasoActivoIndex];
            if (!paso) return;

            // 1. Mover el personaje suavemente al waypoint del paso
            if (paso.posicion_agente) {
                this.establecerDestino(paso.posicion_agente.x_ratio, paso.posicion_agente.y_ratio);
            }

            // 2. Mover la retícula de inspección a las líneas del código en el fondo (sin forzar scroll del editor)
            this.inspeccion.linea = paso.linea_inicio || 1;
            this.inspeccion.linea_fin = paso.linea_fin || paso.linea_inicio || 1;
            this.inspeccion.x_foco = paso.x_foco || 0.35;
            this.inspeccion.y_foco = paso.y_foco || 0.35;
            this.inspeccion.tipo_relacion = paso.tipo || 'flujo';
        }

        aplicarRefactorEnMonaco(sugerencia, lineaInicio, lineaFin) {
            if (!sugerencia) return;
            if (typeof window === 'undefined' || !window.editorMgr || !window.editorMgr.editor) {
                console.warn("Editor Monaco no disponible para refactor.");
                return;
            }
            const ed = window.editorMgr.editor;
            const lIni = Math.max(1, parseInt(lineaInicio) || 1);
            const lFin = Math.max(lIni, parseInt(lineaFin) || lIni);

            try {
                if (typeof monaco !== 'undefined' && monaco.Range) {
                    const range = new monaco.Range(lIni, 1, lFin, 999);
                    ed.pushUndoStop();
                    ed.executeEdits('prig-llm-refactor', [{
                        range: range,
                        text: sugerencia + '\n',
                        forceMoveMarkers: true
                    }]);
                    ed.pushUndoStop();
                    ed.revealLineInCenter(lIni);
                    ed.setPosition({ lineNumber: lIni, column: 1 });
                    ed.focus();

                    // Feedback visual: confirmación en el diálogo del personaje
                    this.evaluarCodigo(`[✨ REFACTOR APLICADO]: Código insertado en L${lIni}-L${lFin}. Puedes deshacer los cambios con Ctrl+Z.`, 12000);
                    this.inspeccion.linea = lIni;
                    this.inspeccion.linea_fin = lIni + sugerencia.split('\n').length;
                    this.inspeccion.tipo_relacion = 'buenas_practicas';
                }
            } catch (err) {
                console.error("Error aplicando refactor en Monaco:", err);
            }
        }

        manejarClick(clickX, clickY, w, h) {
            // Dimensiones del panel HUD Vertical
            const anchoPanel = Math.min(320, Math.max(250, Math.floor(w * 0.22)));
            const altoPanel = Math.min(620, Math.max(440, Math.floor(h * 0.62)));
            const posXPanel = w - anchoPanel - 6;
            const posYPanel = Math.max(20, Math.floor(h * 0.16));

            // 1. Verificar click en las pestañas HUD [DIÁLOGO | CONSEJOS | FLUJO | DEBUG]
            const yTabs = posYPanel + 32;
            const anchoTab = (anchoPanel - 16) / this.pestanasDisponibles.length;
            if (clickY >= yTabs - 9 && clickY <= yTabs + 12 && clickX >= posXPanel + 8 && clickX <= posXPanel + anchoPanel - 8) {
                const tabIdx = Math.floor((clickX - (posXPanel + 8)) / anchoTab);
                if (tabIdx >= 0 && tabIdx < this.pestanasDisponibles.length) {
                    this.modoPestana = this.pestanasDisponibles[tabIdx];
                    this.ultimoCambioPestana = performance.now();
                    return;
                }
            }

            // 2. Click en botón "Aplicar Refactor" dentro de la pestaña CONSEJOS
            if (this.modoPestana === 'consejos' && this.consejo && this.consejo.sugerencia_codigo) {
                const yBtnRefactor = posYPanel + 200;
                if (clickY >= yBtnRefactor && clickY <= yBtnRefactor + 26 && clickX >= posXPanel + 10 && clickX <= posXPanel + anchoPanel - 10) {
                    this.aplicarRefactorEnMonaco(
                        this.consejo.sugerencia_codigo,
                        this.consejo.linea_inicio || 1,
                        this.consejo.linea_fin || 4
                    );
                    return;
                }
            }

            // 3. Click en controles de la pestaña DEBUG [F10 OVER | F11 INTO | F5 CONT | RESET]
            if (this.modoPestana === 'debug') {
                const yDebugBtns = posYPanel + 104;
                if (clickY >= yDebugBtns && clickY <= yDebugBtns + 24 && clickX >= posXPanel + 8 && clickX <= posXPanel + anchoPanel - 8) {
                    const btnW = (anchoPanel - 24) / 4;
                    const bIdx = Math.floor((clickX - (posXPanel + 8)) / btnW);
                    if (bIdx === 0) {
                        this.pasoDebugger('over'); // F10 Step Over
                    } else if (bIdx === 1) {
                        this.pasoDebugger('into'); // F11 Step Into
                    } else if (bIdx === 2) {
                        this.pasoDebugger('out'); // Step Out
                    } else if (bIdx === 3) {
                        this.toggleDebugger(); // F5 / Toggle
                    }
                    return;
                }

                const yBtnJump = posYPanel + 215;
                if (clickY >= yBtnJump && clickY <= yBtnJump + 22 && clickX >= posXPanel + 10 && clickX <= posXPanel + anchoPanel - 10) {
                    this._sincronizarPasoDebugger();
                    return;
                }
            }

            // 3. Si está en pestaña de FLUJO, verificar controles de reproducción y aplicar paso
            if (this.modoPestana === 'flujo' && this.flujoGrafico.activo) {
                const yPlayer = posYPanel + 106;
                if (clickY >= yPlayer - 8 && clickY <= yPlayer + 18 && clickX >= posXPanel + 10 && clickX <= posXPanel + anchoPanel - 10) {
                    if (clickX < posXPanel + 40) {
                        this.anteriorPaso();
                        return;
                    } else if (clickX < posXPanel + 80) {
                        this.toggleReproduccion();
                        return;
                    } else if (clickX < posXPanel + 115) {
                        this.siguientePaso();
                        return;
                    }
                }

                // Click en botón aplicar del paso activo
                const yBtnPaso = posYPanel + 215;
                if (clickY >= yBtnPaso && clickY <= yBtnPaso + 22 && clickX >= posXPanel + 10 && clickX <= posXPanel + anchoPanel - 10) {
                    const paso = this.flujoGrafico.pasos[this.flujoGrafico.pasoActivoIndex];
                    if (paso && paso.sugerencia) {
                        this.aplicarRefactorEnMonaco(paso.sugerencia, paso.linea_inicio, paso.linea_fin);
                        return;
                    }
                }

                // Click en tarjetas de pasos en la lista vertical del panel
                const yListIni = posYPanel + 245;
                this.flujoGrafico.pasos.forEach((p, idx) => {
                    const yCard = yListIni + idx * 40;
                    if (clickY >= yCard && clickY <= yCard + 34 && clickX >= posXPanel + 8 && clickX <= posXPanel + anchoPanel - 8) {
                        this.irAPaso(idx);
                    }
                });
            }

            // 4. Verificar click directo en los nodos gráficos flotantes en el código
            if (this.flujoGrafico.pasos && this.flujoGrafico.pasos.length > 0) {
                this.flujoGrafico.pasos.forEach((paso, idx) => {
                    const nx = w * (paso.x_foco || 0.35);
                    const ny = h * (paso.y_foco || 0.35);
                    const dist = Math.hypot(clickX - nx, clickY - ny);
                    if (dist < 32) {
                        this.irAPaso(idx);
                        this.modoPestana = 'flujo';
                    }
                });
            }
        }

        asignarArte(catArte, arteId, nombre, color, opciones = {}) {
            this.catArte = catArte;
            this.arteId = arteId;
            if (nombre) this.nombre = nombre;
            if (color) this.color = color;
            if (opciones.fuente) this.fuente = opciones.fuente;
            if (opciones.interlineado) this.interlineado = opciones.interlineado;
        }

        evaluarCodigo(textoEvaluacion, duracionMs = 26000) {
            if (!textoEvaluacion) return;
            this.dialogo = {
                texto: textoEvaluacion,
                lineasFormateadas: [],
                charIndex: 0,
                tiempoInicio: performance.now(),
                duracion: duracionMs,
                opacidad: 0.94,
                ultimoCharTime: performance.now(),
                estado: "evaluando"
            };
        }

        establecerConsejo(consejo) {
            if (consejo && typeof consejo === 'object') {
                this.consejo = consejo;
            }
        }

        establecerFlujo(flujoAscii) {
            if (Array.isArray(flujoAscii) && flujoAscii.length > 0) {
                this.flujoAscii = flujoAscii;
            }
        }

        cambiarPestana(modo) {
            if (this.pestanasDisponibles.includes(modo)) {
                this.modoPestana = modo;
                this.ultimoCambioPestana = performance.now();
            }
        }

        establecerDestino(xRatio, yRatio) {
            this.xRatio = Math.max(0.78, Math.min(0.95, xRatio));
            this.yRatio = Math.max(0.70, Math.min(0.94, yRatio));
        }

        establecerInspeccion(infoInspeccion) {
            if (!infoInspeccion) return;
            this.inspeccion.activo = !!infoInspeccion.activo;
            if (typeof infoInspeccion.linea === 'number') this.inspeccion.linea = infoInspeccion.linea;
            if (typeof infoInspeccion.linea_fin === 'number') this.inspeccion.linea_fin = infoInspeccion.linea_fin;
            if (typeof infoInspeccion.x_foco === 'number') this.inspeccion.x_foco = infoInspeccion.x_foco;
            if (typeof infoInspeccion.y_foco === 'number') this.inspeccion.y_foco = infoInspeccion.y_foco;
            if (infoInspeccion.modo) this.inspeccion.modo = infoInspeccion.modo;
            if (infoInspeccion.tipo_relacion) this.inspeccion.tipo_relacion = infoInspeccion.tipo_relacion;
        }

        actualizar(dt, cursorTexto, canvasW, canvasH) {
            this.anguloFlotacion += this.velocidadFlotacion;

            const w = canvasW || window.innerWidth;
            const h = canvasH || window.innerHeight;
            const ahora = performance.now();

            // Auto-avance rítmico del flujo gráfico animado
            if (this.flujoGrafico.activo && this.flujoGrafico.reproduciendo && this.flujoGrafico.pasos.length > 0) {
                if (ahora - this.flujoGrafico.tiempoInicioPaso > this.flujoGrafico.duracionPasoMs) {
                    this.flujoGrafico.pasoActivoIndex = (this.flujoGrafico.pasoActivoIndex + 1) % this.flujoGrafico.pasos.length;
                    this.flujoGrafico.tiempoInicioPaso = ahora;
                    this._aplicarPasoActivo();
                }
            }

            // Auto-ciclo suave de pestañas en el HUD si no está en interacción directa
            if (ahora - this.ultimoCambioPestana > this.intervaloAutoCicloPestana) {
                const idx = this.pestanasDisponibles.indexOf(this.modoPestana);
                this.modoPestana = this.pestanasDisponibles[(idx + 1) % this.pestanasDisponibles.length];
                this.ultimoCambioPestana = ahora;
            }

            // Escala dinámica del personaje: se agranda al estar en modo diálogo/inmersión
            const modoFondoActivo = !!(window.modoCerebroFondo && window.modoCerebroFondo.activo);
            const targetScale = modoFondoActivo ? 1.85 : 1.0;
            this.scaleChar = this.scaleChar || 1.0;
            this.scaleChar += (targetScale - this.scaleChar) * 0.12;

            // 1. Cinemática de Resorte Amortiguado (Spring-Damper 2do Orden / Hooke)
            const xRatioDinamico = modoFondoActivo ? 0.90 : this.xRatio;
            const yRatioDinamico = modoFondoActivo ? 0.74 : this.yRatio;
            const targetRealX = w * xRatioDinamico;
            const targetRealY = h * yRatioDinamico + Math.sin(this.anguloFlotacion) * this.amplitudFlotacion;

            if (!this._iniciado) {
                this.currentX = targetRealX;
                this.currentY = targetRealY;
                this._iniciado = true;
            } else {
                // Cálculo de fuerza elástica con amortiguación viscosa
                const fx = (targetRealX - this.currentX) * this.springK + this.impulsoX;
                const fy = (targetRealY - this.currentY) * this.springK + this.impulsoY;
                this.vx = (this.vx + fx) * this.springDamping;
                this.vy = (this.vy + fy) * this.springDamping;
                this.currentX += this.vx;
                this.currentY += this.vy;
                this.impulsoX *= 0.70;
                this.impulsoY *= 0.70;
            }

            // 2. Cinemática de resorte para la retícula y corchetes de inspección en Monaco
            if (this.inspeccion) {
                const targetFocoX = this.inspeccion.x_foco || 0.35;
                const targetFocoY = this.inspeccion.y_foco || 0.35;
                const fRetX = (targetFocoX - (this.inspeccion.currentX_foco || targetFocoX)) * 0.14;
                const fRetY = (targetFocoY - (this.inspeccion.currentY_foco || targetFocoY)) * 0.14;
                this.inspeccion.vx_foco = ((this.inspeccion.vx_foco || 0) + fRetX) * 0.76;
                this.inspeccion.vy_foco = ((this.inspeccion.vy_foco || 0) + fRetY) * 0.76;
                this.inspeccion.currentX_foco = (this.inspeccion.currentX_foco || targetFocoX) + this.inspeccion.vx_foco;
                this.inspeccion.currentY_foco = (this.inspeccion.currentY_foco || targetFocoY) + this.inspeccion.vy_foco;
            }

            // 3. Cinemática orbital elástica de drones satélite (con resorte radial escalable)
            if (this.drones) {
                this.drones.forEach((drone, idx) => {
                    drone.angulo += drone.velocidad;
                    const radObj = (drone.radio || 38) * this.scaleChar;
                    const fRad = (radObj - (drone.radioActual || radObj)) * 0.08;
                    drone.vRadio = ((drone.vRadio || 0) + fRad) * 0.82;
                    drone.radioActual = (drone.radioActual || radObj) + drone.vRadio;

                    drone.x = this.currentX + Math.cos(drone.angulo + idx) * drone.radioActual;
                    drone.y = (this.currentY - 30 * this.scaleChar) + Math.sin(drone.angulo * 1.5 + idx) * (drone.radioActual * 0.45);
                });
            }

            // 4. Actualizar paquetes de energía telemétrica en tránsito por el haz
            if (this.particulasHaz) {
                this.particulasHaz.forEach(p => {
                    p.progreso += p.velocidad;
                    if (p.progreso > 1.0) p.progreso -= 1.0;
                });
            }

            // 5. Actualizar partículas que viajan por las curvas del flujo gráfico (o delegar a Worker)
            if (this.flujoGrafico.particulasRuta && this.flujoGrafico.pasos.length > 1) {
                if (this.workerFisica && this.workerListo) {
                    this.workerFisica.postMessage({
                        tipo: 'STEP_PHYSICS',
                        payload: {
                            w: w,
                            h: h,
                            xRatio: this.xRatio,
                            yRatio: this.yRatio,
                            anguloFlotacion: this.anguloFlotacion,
                            drones: this.drones,
                            pasos: this.flujoGrafico.pasos,
                            particulasRuta: this.flujoGrafico.particulasRuta
                        }
                    });
                } else {
                    const numSegmentos = this.flujoGrafico.pasos.length - 1;
                    this.flujoGrafico.particulasRuta.forEach(p => {
                        p.progreso += p.velocidad;
                        if (p.progreso > 1.0) {
                            p.progreso -= 1.0;
                            p.segmento = (p.segmento + 1) % numSegmentos;
                        }
                    });
                }
            }

            // Atenuación si el cursor de escritura se acerca mucho a la esquina inferior derecha
            let factorAtenuacion = 1.0;
            if (cursorTexto && cursorTexto.activo) {
                const dist = Math.hypot(this.currentX - cursorTexto.x, this.currentY - cursorTexto.y);
                if (dist < 220) {
                    factorAtenuacion = Math.max(0.15, dist / 220);
                }
            }
            this.opacidadActual = this.opacidadBase * factorAtenuacion;

            // Typewriter del texto de evaluación
            if (this.dialogo) {
                if (ahora - this.dialogo.ultimoCharTime > 14) {
                    if (this.dialogo.charIndex < this.dialogo.texto.length) {
                        this.dialogo.charIndex++;
                        this.dialogo.ultimoCharTime = ahora;
                    }
                }
            }
        }

        dibujar(ctx, canvasW, canvasH) {
            if (!window.BIBLIOTECA_ASCII || !ctx) return;

            const w = canvasW || (ctx.canvas ? ctx.canvas.width : window.innerWidth);
            const h = canvasH || (ctx.canvas ? ctx.canvas.height : window.innerHeight);

            // 1. DIBUJAR FLUJO GRÁFICO ANIMADO CON CONECTORES SPLINE Y NODOS FLOTANTES EN EL CÓDIGO
            this._dibujarFlujoGraficoEnCodigo(ctx, w, h);

            // 2. DIBUJAR ECOSISTEMA DE DRONES SATÉLITES ORBITALES
            this._dibujarDronesSatelite(ctx, w, h);

            // 3. DIBUJAR HAZ TELEMÉTRICO Y RETÍCULA DE RELACIÓN VISUAL CON EL CÓDIGO
            this._dibujarHazInspeccion(ctx, w, h);

            // 4. DIBUJAR CUADRO DE DIÁLOGO VERTICAL AMPLIADO CON TIMELINE PLAYER
            this._dibujarPanelEvaluacionFijo(ctx, w, h);

            // 5. DIBUJAR EL PERSONAJE ASCII EN SU POSICIÓN DE NAVEGACIÓN (CON ESCALA DINÁMICA)
            const lineas = window.BIBLIOTECA_ASCII.obtener(this.catArte, this.arteId);
            if (!lineas) return;

            ctx.save();
            ctx.globalAlpha = this.opacidadActual * 0.78;

            const scale = this.scaleChar || 1.0;
            const tamFuente = Math.max(6, Math.round(6 * scale));
            const fuenteDinamica = `bold ${tamFuente}px "Fira Code", monospace`;
            const interlineadoDinamico = Math.max(7, Math.round(7 * scale));

            window.BIBLIOTECA_ASCII.renderizarArte(
                ctx,
                lineas,
                this.currentX,
                this.currentY,
                {
                    color: this.color,
                    fuente: fuenteDinamica,
                    interlineado: interlineadoDinamico,
                    alineacion: 'center',
                    resplandorColor: this.color,
                    resplandorBlur: Math.round(2 * scale)
                }
            );

            ctx.restore();
        }

        _dibujarFlujoGraficoEnCodigo(ctx, w, h) {
            if (!this.flujoGrafico.activo || !this.flujoGrafico.pasos || this.flujoGrafico.pasos.length === 0) return;

            const pasos = this.flujoGrafico.pasos;
            const pasoActivo = this.flujoGrafico.pasoActivoIndex;
            const ahora = performance.now();

            ctx.save();

            // 1. DIBUJAR LÍNEAS / CURVAS DE CONEXIÓN ENTRE NODOS CONSECUTIVOS DEL FLUJO
            for (let i = 0; i < pasos.length - 1; i++) {
                const p1 = pasos[i];
                const p2 = pasos[i + 1];

                const x1 = w * (p1.x_foco || 0.35);
                const y1 = h * (p1.y_foco || 0.35);
                const x2 = w * (p2.x_foco || 0.35);
                const y2 = h * (p2.y_foco || 0.35);

                const cpx1 = x1 + (x2 - x1) * 0.5;
                const cpy1 = y1;
                const cpx2 = x1 + (x2 - x1) * 0.5;
                const cpy2 = y2;

                const esSegmentoActivo = (pasoActivo === i);

                // Curva de conexión resplandeciente
                ctx.beginPath();
                ctx.moveTo(x1, y1);
                ctx.bezierCurveTo(cpx1, cpy1, cpx2, cpy2, x2, y2);
                ctx.strokeStyle = esSegmentoActivo ? this.color : 'rgba(137, 180, 250, 0.30)';
                ctx.lineWidth = esSegmentoActivo ? 2.0 : 1.0;
                ctx.setLineDash([4, 6]);
                ctx.lineDashOffset = -ahora * 0.015;
                ctx.stroke();

                // Flecha direccional en el centro de la curva
                const midT = 0.5;
                const mx = Math.pow(1-midT, 3)*x1 + 3*Math.pow(1-midT, 2)*midT*cpx1 + 3*(1-midT)*Math.pow(midT, 2)*cpx2 + Math.pow(midT, 3)*x2;
                const my = Math.pow(1-midT, 3)*y1 + 3*Math.pow(1-midT, 2)*midT*cpy1 + 3*(1-midT)*Math.pow(midT, 2)*cpy2 + Math.pow(midT, 3)*y2;

                ctx.setLineDash([]);
                ctx.fillStyle = esSegmentoActivo ? '#ffffff' : 'rgba(137, 180, 250, 0.6)';
                ctx.font = 'bold 8px "Fira Code", monospace';
                ctx.textAlign = 'center';
                ctx.fillText('▼', mx, my + 3);
            }

            // 2. DIBUJAR PARTÍCULAS / TOKENS DE DATOS VIAJANDO POR LAS CURVAS
            if (this.flujoGrafico.particulasRuta) {
                this.flujoGrafico.particulasRuta.forEach(part => {
                    const segIdx = Math.min(pasos.length - 2, Math.max(0, part.segmento));
                    const p1 = pasos[segIdx];
                    const p2 = pasos[segIdx + 1];
                    if (!p1 || !p2) return;

                    const x1 = w * (p1.x_foco || 0.35);
                    const y1 = h * (p1.y_foco || 0.35);
                    const x2 = w * (p2.x_foco || 0.35);
                    const y2 = h * (p2.y_foco || 0.35);
                    const cpx1 = x1 + (x2 - x1) * 0.5;
                    const cpy1 = y1;
                    const cpx2 = x1 + (x2 - x1) * 0.5;
                    const cpy2 = y2;

                    const t = part.progreso;
                    const px = Math.pow(1-t, 3)*x1 + 3*Math.pow(1-t, 2)*t*cpx1 + 3*(1-t)*Math.pow(t, 2)*cpx2 + Math.pow(t, 3)*x2;
                    const py = Math.pow(1-t, 3)*y1 + 3*Math.pow(1-t, 2)*t*cpy1 + 3*(1-t)*Math.pow(t, 2)*cpy2 + Math.pow(t, 3)*y2;

                    ctx.fillStyle = this.color;
                    ctx.font = 'bold 8px "Fira Code", monospace';
                    ctx.textAlign = 'center';
                    ctx.fillText(part.glifo, px, py);
                });
            }

            // 3. DIBUJAR CADA NODO DEL FLUJO CON TARJETA ESTRUCTURADA Y RESPLANDOR
            pasos.forEach((paso, idx) => {
                const nx = w * (paso.x_foco || 0.35);
                const ny = h * (paso.y_foco || 0.35);
                const esActivo = (idx === pasoActivo);

                // Fondo de la tarjeta del nodo
                const anchoCard = 150;
                const altoCard = 24;
                const cardX = nx - anchoCard / 2;
                const cardY = ny - altoCard / 2;

                ctx.fillStyle = esActivo ? 'rgba(17, 24, 39, 0.95)' : 'rgba(10, 15, 26, 0.75)';
                ctx.fillRect(cardX, cardY, anchoCard, altoCard);

                ctx.strokeStyle = esActivo ? this.color : 'rgba(137, 180, 250, 0.40)';
                ctx.lineWidth = esActivo ? 1.6 : 0.8;
                ctx.strokeRect(cardX, cardY, anchoCard, altoCard);

                // Esquinas reforzadas si es el nodo activo
                if (esActivo) {
                    const cSz = 4;
                    ctx.lineWidth = 2.0;
                    ctx.strokeStyle = '#ffffff';
                    ctx.beginPath();
                    ctx.moveTo(cardX, cardY + cSz); ctx.lineTo(cardX, cardY); ctx.lineTo(cardX + cSz, cardY);
                    ctx.moveTo(cardX + anchoCard - cSz, cardY); ctx.lineTo(cardX + anchoCard, cardY); ctx.lineTo(cardX + anchoCard, cardY + cSz);
                    ctx.moveTo(cardX, cardY + altoCard - cSz); ctx.lineTo(cardX, cardY + altoCard); ctx.lineTo(cardX + cSz, cardY + altoCard);
                    ctx.moveTo(cardX + anchoCard - cSz, cardY + altoCard); ctx.lineTo(cardX + anchoCard, cardY + altoCard); ctx.lineTo(cardX + anchoCard, cardY + altoCard - cSz);
                    ctx.stroke();
                }

                // Ícono del nodo y etiqueta clara
                ctx.font = 'bold 8.5px "Fira Code", monospace';
                ctx.fillStyle = esActivo ? '#ffffff' : '#94e2d5';
                ctx.textAlign = 'left';
                ctx.fillText(`${paso.icono || '⚡'} Paso ${idx + 1}: ${paso.etiqueta.slice(0, 14)}`, cardX + 6, cardY + 15);

                // Badge de línea de código
                ctx.font = 'bold 7.5px "Fira Code", monospace';
                ctx.fillStyle = esActivo ? this.color : '#89b4fa';
                ctx.textAlign = 'right';
                ctx.fillText(`L${paso.linea_inicio}-${paso.linea_fin}`, cardX + anchoCard - 6, cardY + 15);
            });

            ctx.restore();
        }

        _dibujarDronesSatelite(ctx, w, h) {
            if (!this.drones || this.drones.length === 0) return;
            ctx.save();
            const scale = this.scaleChar || 1.0;
            ctx.font = `bold ${Math.max(7.5, Math.round(7.5 * scale))}px "Fira Code", monospace`;
            ctx.textAlign = 'center';
            ctx.textBaseline = 'middle';

            this.drones.forEach((drone) => {
                ctx.globalAlpha = this.opacidadActual * (0.50 + Math.sin(drone.angulo * 2) * 0.25);
                ctx.fillStyle = this.color;
                ctx.fillText(drone.glifo, drone.x, drone.y);
            });

            ctx.restore();
        }

        _dibujarHazInspeccion(ctx, w, h) {
            if (!this.inspeccion || !this.inspeccion.activo) return;

            const focoX = w * (this.inspeccion.currentX_foco || this.inspeccion.x_foco || 0.35);
            const focoY = h * (this.inspeccion.currentY_foco || this.inspeccion.y_foco || 0.40);
            const linea = this.inspeccion.linea || 1;
            const lineaFin = this.inspeccion.linea_fin || linea;

            ctx.save();
            const pulso = 0.5 + Math.sin(performance.now() * 0.005) * 0.4;
            ctx.globalAlpha = this.opacidadActual * (0.35 + pulso * 0.3);

            // 1. Haz láser / telemétrico punteado desde el HUD/personaje hasta la línea de código
            ctx.strokeStyle = this.color;
            ctx.lineWidth = 1.2;
            ctx.setLineDash([4, 6]);
            ctx.lineDashOffset = -performance.now() * 0.02;

            ctx.beginPath();
            ctx.moveTo(this.currentX, this.currentY - 40);
            ctx.lineTo(focoX, focoY);
            ctx.stroke();

            // 2. Paquetes de energía viajando por el haz
            ctx.setLineDash([]);
            if (this.particulasHaz) {
                this.particulasHaz.forEach(p => {
                    const px = this.currentX + (focoX - this.currentX) * p.progreso;
                    const py = (this.currentY - 40) + (focoY - (this.currentY - 40)) * p.progreso;
                    ctx.fillStyle = '#ffffff';
                    ctx.font = 'bold 7px "Fira Code", monospace';
                    ctx.fillText('•', px, py);
                });
            }

            // 3. Selección y Corchetes de Rango Detrás del Código (Background Code Backdrop & Brackets)
            const altoRango = Math.min(160, Math.max(26, (lineaFin - linea + 1) * 20));
            const yInicio = focoY - 10;
            const yFin = yInicio + altoRango;
            const anchoSeleccion = Math.min(w * 0.50, 520);
            const xInicioBloque = Math.max(25, focoX - 18);

            // Franja translúcida de selección en el fondo (sin tapar el texto)
            ctx.fillStyle = (this.inspeccion.tipo_relacion === 'seguridad') ? 'rgba(243, 139, 168, 0.05)' : 'rgba(166, 227, 161, 0.04)';
            ctx.fillRect(xInicioBloque, yInicio, anchoSeleccion, altoRango);

            // Corchete izquierdo delimitador
            ctx.strokeStyle = this.color;
            ctx.lineWidth = 1.3;
            ctx.beginPath();
            ctx.moveTo(xInicioBloque + 8, yInicio);
            ctx.lineTo(xInicioBloque, yInicio);
            ctx.lineTo(xInicioBloque, yFin);
            ctx.lineTo(xInicioBloque + 8, yFin);
            ctx.stroke();

            // Corchete derecho delimitador
            ctx.beginPath();
            ctx.moveTo(xInicioBloque + anchoSeleccion - 8, yInicio);
            ctx.lineTo(xInicioBloque + anchoSeleccion, yInicio);
            ctx.lineTo(xInicioBloque + anchoSeleccion, yFin);
            ctx.lineTo(xInicioBloque + anchoSeleccion - 8, yFin);
            ctx.stroke();

            // Puntero triangular afilado hacia la línea
            ctx.fillStyle = this.color;
            ctx.beginPath();
            ctx.moveTo(focoX - 14, focoY);
            ctx.lineTo(focoX - 4, focoY);
            ctx.lineTo(focoX - 9, focoY - 4);
            ctx.fill();

            // 4. Anotación técnica discreta en el fondo detrás del código (Background Note)
            const tipo = this.inspeccion.tipo_relacion || 'buenas_practicas';
            let etiqueta = `▶ Línea ${linea}-${lineaFin}`;
            let colorBadge = '#89b4fa';

            if (tipo === 'optimizacion') {
                etiqueta = `⚡ Optimización en Línea ${linea}-${lineaFin}`;
                colorBadge = '#f9e2af';
            } else if (tipo === 'seguridad') {
                etiqueta = `🛡️ Validación en Línea ${linea}-${lineaFin}`;
                colorBadge = '#f38ba8';
            } else if (tipo === 'buenas_practicas') {
                etiqueta = `✨ Buenas Prácticas en Línea ${linea}-${lineaFin}`;
                colorBadge = '#a6e3a1';
            } else if (tipo === 'flujo') {
                etiqueta = `🔀 Flujo de Ejecución en Línea ${linea}-${lineaFin}`;
                colorBadge = '#cba6f7';
            }

            ctx.font = 'bold 8.5px "Fira Code", monospace';
            ctx.fillStyle = colorBadge;
            ctx.textAlign = 'left';
            ctx.fillText(etiqueta, focoX + 6, focoY + 3);

            // Anotación contextual en el fondo (sugerencia de código discreta detrás de la línea)
            if (this.consejo && this.consejo.titulo) {
                ctx.font = 'italic 7.5px "Fira Code", monospace';
                ctx.fillStyle = this.color;
                ctx.globalAlpha = this.opacidadActual * 0.40;
                ctx.fillText(`// [Nota]: ${this.consejo.titulo.slice(0, 46)}`, xInicioBloque + 12, yFin + 11);
            }

            ctx.restore();
        }

        _dibujarPanelEvaluacionFijo(ctx, w, h) {
            ctx.save();

            // Sincronización con el modo fondo / centro del diálogo (Ctrl + Alt)
            const modoCentroActivo = !!(window.modoCerebroFondo && window.modoCerebroFondo.activo);
            const targetCentro = modoCentroActivo ? 1.0 : 0.0;
            this.animModoCentro += (targetCentro - this.animModoCentro) * 0.16;
            const t = this.animModoCentro;

            // Dimensiones en modo normal (pegado al lateral derecho)
            const anchoNorm = Math.min(320, Math.max(250, Math.floor(w * 0.22)));
            const altoNorm = Math.min(620, Math.max(440, Math.floor(h * 0.62)));
            const posXNorm = w - anchoNorm - 6;
            const posYNorm = Math.max(20, Math.floor(h * 0.16));

            // Dimensiones en modo central (ocupa el centro de la pantalla para máxima visibilidad del fondo)
            const anchoCent = Math.min(620, Math.max(440, Math.floor(w * 0.50)));
            const altoCent = Math.min(680, Math.max(480, Math.floor(h * 0.70)));
            const posXCent = Math.floor((w - anchoCent) / 2);
            const posYCent = Math.floor((h - altoCent) / 2);

            const anchoPanel = Math.floor(anchoNorm + (anchoCent - anchoNorm) * t);
            const altoPanel = Math.floor(altoNorm + (altoCent - altoNorm) * t);
            const posXPanel = Math.floor(posXNorm + (posXCent - posXNorm) * t);
            const posYPanel = Math.floor(posYNorm + (posYCent - posYNorm) * t);

            // Si está en transición o modo centro, dibujar haz de conexión láser desde el personaje (abajo a la derecha)
            if (t > 0.04) {
                ctx.save();
                ctx.globalAlpha = t * 0.85;
                ctx.strokeStyle = this.color;
                ctx.lineWidth = 1.6;
                ctx.setLineDash([6, 4]);

                const charX = this.currentX || (w * 0.88);
                const charY = this.currentY || (h * 0.88);
                const centroDialogoX = posXPanel + anchoPanel / 2;
                const centroDialogoY = posYPanel + altoPanel;

                ctx.beginPath();
                ctx.moveTo(charX, charY - 20);
                ctx.quadraticCurveTo(
                    (charX + centroDialogoX) / 2, 
                    Math.max(charY, centroDialogoY) + 30, 
                    centroDialogoX, 
                    centroDialogoY
                );
                ctx.stroke();

                // Paquete de datos en tránsito por la curva
                const ahora = performance.now();
                const progHaz = (ahora * 0.001) % 1.0;
                const tCurva = progHaz;
                const p0x = charX, p0y = charY - 20;
                const p1x = (charX + centroDialogoX) / 2, p1y = Math.max(charY, centroDialogoY) + 30;
                const p2x = centroDialogoX, p2y = centroDialogoY;
                const bX = (1 - tCurva) * (1 - tCurva) * p0x + 2 * (1 - tCurva) * tCurva * p1x + tCurva * tCurva * p2x;
                const bY = (1 - tCurva) * (1 - tCurva) * p0y + 2 * (1 - tCurva) * tCurva * p1y + tCurva * tCurva * p2y;

                ctx.fillStyle = '#ffffff';
                ctx.beginPath();
                ctx.arc(bX, bY, 3.5, 0, Math.PI * 2);
                ctx.fill();
                ctx.restore();
            }

            ctx.globalAlpha = this.opacidadActual * Math.max(0, 1.0 - t * 1.15);
            if (ctx.globalAlpha <= 0.01) {
                ctx.restore();
                return;
            }

            // Fondo translúcido HUD Glass de alta definición con relieve
            ctx.fillStyle = 'rgba(6, 9, 17, 0.93)';
            ctx.fillRect(posXPanel, posYPanel, anchoPanel, altoPanel);

            // Borde neón temático con resplandor sutil
            ctx.strokeStyle = this.color;
            ctx.lineWidth = t > 0.5 ? 1.8 : 1.3;
            ctx.strokeRect(posXPanel, posYPanel, anchoPanel, altoPanel);

            // Esquinas reforzadas HUD (Corner accents)
            const cornerSize = t > 0.5 ? 14 : 9;
            ctx.lineWidth = 2.5;
            ctx.strokeStyle = '#ffffff';
            ctx.beginPath();
            ctx.moveTo(posXPanel, posYPanel + cornerSize); ctx.lineTo(posXPanel, posYPanel); ctx.lineTo(posXPanel + cornerSize, posYPanel);
            ctx.moveTo(posXPanel + anchoPanel - cornerSize, posYPanel); ctx.lineTo(posXPanel + anchoPanel, posYPanel); ctx.lineTo(posXPanel + anchoPanel, posYPanel + cornerSize);
            ctx.moveTo(posXPanel, posYPanel + altoPanel - cornerSize); ctx.lineTo(posXPanel, posYPanel + altoPanel); ctx.lineTo(posXPanel + cornerSize, posYPanel + altoPanel);
            ctx.moveTo(posXPanel + anchoPanel - cornerSize, posYPanel + altoPanel); ctx.lineTo(posXPanel + anchoPanel, posYPanel + altoPanel); ctx.lineTo(posXPanel + anchoPanel, posYPanel + altoPanel - cornerSize);
            ctx.stroke();

            // 1. Cabecera con Nombre del Director y Modelo
            ctx.globalAlpha = this.opacidadActual;
            ctx.font = 'bold 10px "Fira Code", monospace';
            ctx.fillStyle = this.color;
            ctx.textAlign = 'left';
            ctx.fillText(`🧠 [${this.nombre.toUpperCase()}]`, posXPanel + 10, posYPanel + 18);

            ctx.textAlign = 'right';
            ctx.font = '8.5px "Fira Code", monospace';
            ctx.fillStyle = '#89b4fa';
            ctx.fillText("⚡ 7B LLM DIRECTOR", posXPanel + anchoPanel - 10, posYPanel + 18);

            // 2. Barra de Selección de Pestañas HUD: [1. DIÁLOGO] [2. CONSEJOS] [3. FLUJO] [4. DEBUG]
            const yTabs = posYPanel + 32;
            const pestañasInfo = [
                { id: 'dialogo', label: '💬 DIÁLOG' },
                { id: 'consejos', label: '⚡ TIPS' },
                { id: 'flujo', label: '🔀 FLOW' },
                { id: 'debug', label: '🐞 DEBUG' }
            ];
            const anchoTab = (anchoPanel - 16) / pestañasInfo.length;

            for (let t = 0; t < pestañasInfo.length; t++) {
                const tab = pestañasInfo[t];
                const xTab = posXPanel + 8 + t * anchoTab;
                const activo = (this.modoPestana === tab.id);

                if (activo) {
                    ctx.fillStyle = 'rgba(137, 180, 250, 0.22)';
                    ctx.fillRect(xTab, yTabs - 9, anchoTab - 3, 16);
                    ctx.strokeStyle = this.color;
                    ctx.lineWidth = 1;
                    ctx.strokeRect(xTab, yTabs - 9, anchoTab - 3, 16);
                    ctx.fillStyle = '#ffffff';
                } else {
                    ctx.fillStyle = '#6c7086';
                }

                ctx.font = 'bold 7px "Fira Code", monospace';
                ctx.textAlign = 'center';
                ctx.fillText(tab.label, xTab + (anchoTab - 3) / 2, yTabs + 3);
            }



            // 3. Sub-bloque vertical de telemetría y métricas del ecosistema
            ctx.textAlign = 'left';
            ctx.font = '8px "Fira Code", monospace';
            ctx.fillStyle = '#94e2d5';
            ctx.fillText(`MOD: ${this.moduloActivo || 'main'} | COMPL: ${this.metricas.complejidad || 'O(N)'}`, posXPanel + 10, posYPanel + 54);

            ctx.fillStyle = '#a6adc8';
            ctx.fillText(`CALIDAD: ${this.metricas.calidad || 96}% | MODUL: ${this.metricas.modularidad || 94}%`, posXPanel + 10, posYPanel + 66);

            // Línea divisoria de telemetría a contenido
            ctx.beginPath();
            ctx.moveTo(posXPanel + 8, posYPanel + 74);
            ctx.lineTo(posXPanel + anchoPanel - 8, posYPanel + 74);
            ctx.strokeStyle = '#45475a';
            ctx.lineWidth = 0.8;
            ctx.stroke();

            // 4. CONTENIDO SEGÚN LA PESTAÑA ACTIVA
            const yOffsetInicio = posYPanel + 90;
            const maxAnchoLinea = anchoPanel - 20;

            if (this.modoPestana === 'dialogo') {
                // PESTAÑA 1: DIÁLOGO DE RAZONAMIENTO Y EVALUACIÓN
                if (this.dialogo && this.dialogo.charIndex > 0) {
                    const textoVisible = this.dialogo.texto.substring(0, this.dialogo.charIndex);
                    ctx.font = '10px "Fira Code", monospace';
                    ctx.fillStyle = '#f8fafc';
                    ctx.textAlign = 'left';

                    const palabras = textoVisible.split(' ');
                    let lineaActual = '';
                    let yOffset = yOffsetInicio;
                    const lineasMax = 23;
                    let countLineas = 0;

                    for (let i = 0; i < palabras.length; i++) {
                        const prueba = lineaActual + (lineaActual ? ' ' : '') + palabras[i];
                        if (ctx.measureText(prueba).width > maxAnchoLinea && lineaActual) {
                            ctx.fillText(lineaActual, posXPanel + 10, yOffset);
                            lineaActual = palabras[i];
                            yOffset += 15;
                            countLineas++;
                            if (countLineas >= lineasMax) break;
                        } else {
                            lineaActual = prueba;
                        }
                    }
                    if (lineaActual && countLineas < lineasMax) {
                        ctx.fillText(lineaActual, posXPanel + 10, yOffset);
                    }
                }
            } else if (this.modoPestana === 'consejos') {
                // PESTAÑA 2: BUENAS PRÁCTICAS & REFACTORIZACIÓN
                const c = this.consejo;
                if (c) {
                    ctx.textAlign = 'left';

                    // Badge de categoría
                    ctx.font = 'bold 8.5px "Fira Code", monospace';
                    ctx.fillStyle = '#f9e2af';
                    ctx.fillText(`🏷️ CATEGORÍA: ${c.categoria || 'Clean Code'}`, posXPanel + 10, yOffsetInicio);

                    // Título del consejo
                    ctx.font = 'bold 9.5px "Fira Code", monospace';
                    ctx.fillStyle = this.color;
                    ctx.fillText(`📌 ${c.titulo || 'Optimización Estructural'}`, posXPanel + 10, yOffsetInicio + 16);

                    // Detalle explicativo
                    ctx.font = '9.5px "Fira Code", monospace';
                    ctx.fillStyle = '#cdd6f4';
                    const palabras = (c.detalle || '').split(' ');
                    let lineaActual = '';
                    let yOffset = yOffsetInicio + 34;

                    for (let i = 0; i < palabras.length; i++) {
                        const prueba = lineaActual + (lineaActual ? ' ' : '') + palabras[i];
                        if (ctx.measureText(prueba).width > maxAnchoLinea && lineaActual) {
                            ctx.fillText(lineaActual, posXPanel + 10, yOffset);
                            lineaActual = palabras[i];
                            yOffset += 14;
                        } else {
                            lineaActual = prueba;
                        }
                    }
                    if (lineaActual) ctx.fillText(lineaActual, posXPanel + 10, yOffset);

                    // Caja de código sugerido
                    if (c.sugerencia_codigo) {
                        const yCaja = yOffset + 18;
                        ctx.fillStyle = 'rgba(17, 17, 27, 0.85)';
                        ctx.fillRect(posXPanel + 8, yCaja, anchoPanel - 16, 44);
                        ctx.strokeStyle = '#89b4fa';
                        ctx.lineWidth = 0.9;
                        ctx.strokeRect(posXPanel + 8, yCaja, anchoPanel - 16, 44);

                        ctx.font = 'bold 8px "Fira Code", monospace';
                        ctx.fillStyle = '#89b4fa';
                        ctx.fillText('💡 SUGERENCIA RECOMENDADA:', posXPanel + 14, yCaja + 14);

                        ctx.font = '9px "Fira Code", monospace';
                        ctx.fillStyle = '#a6e3a1';
                        ctx.fillText(c.sugerencia_codigo.slice(0, 36), posXPanel + 14, yCaja + 30);

                        // Botón Interactivo: Aplicar Refactor en Monaco (1-Click)
                        const yBtnRefactor = yCaja + 50;
                        ctx.fillStyle = 'rgba(166, 227, 161, 0.22)';
                        ctx.fillRect(posXPanel + 8, yBtnRefactor, anchoPanel - 16, 24);
                        ctx.strokeStyle = '#a6e3a1';
                        ctx.lineWidth = 1.2;
                        ctx.strokeRect(posXPanel + 8, yBtnRefactor, anchoPanel - 16, 24);

                        ctx.font = 'bold 8.5px "Fira Code", monospace';
                        ctx.fillStyle = '#a6e3a1';
                        ctx.textAlign = 'center';
                        ctx.fillText('✨ APLICAR EN MONACO (1-CLICK)', posXPanel + anchoPanel / 2, yBtnRefactor + 16);
                        ctx.textAlign = 'left';
                    }
                }
            } else if (this.modoPestana === 'flujo') {
                // PESTAÑA 3: MOTOR DE MOVIMIENTO Y TIMELINE INTERACTIVO DEL FLUJO
                const pasos = this.flujoGrafico.pasos || [];
                const pasoIdx = this.flujoGrafico.pasoActivoIndex || 0;
                const pasoActual = pasos[pasoIdx];
                const ahora = performance.now();

                ctx.textAlign = 'left';
                ctx.font = 'bold 8.5px "Fira Code", monospace';
                ctx.fillStyle = '#cba6f7';
                ctx.fillText(`🔀 MOTOR DE MOVIMIENTO [PASO ${pasoIdx + 1}/${pasos.length || 1}]`, posXPanel + 10, yOffsetInicio);

                // Barra de Controles de Reproducción: [⏮ ANT] [⏯ PLAY/PAUSA] [⏭ SIG]
                const yPlayer = yOffsetInicio + 16;
                ctx.fillStyle = 'rgba(17, 24, 39, 0.85)';
                ctx.fillRect(posXPanel + 8, yPlayer, anchoPanel - 16, 22);
                ctx.strokeStyle = '#45475a';
                ctx.lineWidth = 0.8;
                ctx.strokeRect(posXPanel + 8, yPlayer, anchoPanel - 16, 22);

                // Botones interactivos renderizados en Canvas
                ctx.font = 'bold 8px "Fira Code", monospace';
                ctx.textAlign = 'left';
                ctx.fillStyle = '#89b4fa';
                ctx.fillText('⏮ ANT', posXPanel + 14, yPlayer + 14);

                ctx.fillStyle = this.flujoGrafico.reproduciendo ? '#a6e3a1' : '#f9e2af';
                ctx.fillText(this.flujoGrafico.reproduciendo ? '⏸ PAUSA' : '▶ PLAY', posXPanel + 52, yPlayer + 14);

                ctx.fillStyle = '#89b4fa';
                ctx.fillText('⏭ SIG', posXPanel + 104, yPlayer + 14);

                // Barra de progreso continuo del paso actual
                const yProgreso = yPlayer + 24;
                const transcurrido = ahora - this.flujoGrafico.tiempoInicioPaso;
                const pctPaso = Math.min(1.0, Math.max(0.0, transcurrido / (this.flujoGrafico.duracionPasoMs || 3400)));

                ctx.fillStyle = 'rgba(49, 50, 68, 0.6)';
                ctx.fillRect(posXPanel + 8, yProgreso, anchoPanel - 16, 3);
                ctx.fillStyle = this.color;
                ctx.fillRect(posXPanel + 8, yProgreso, (anchoPanel - 16) * (this.flujoGrafico.reproduciendo ? pctPaso : 1.0), 3);

                // Tarjeta de Detalle del Paso Activo
                if (pasoActual) {
                    const yInfo = yProgreso + 10;
                    const altoCardInfo = pasoActual.sugerencia ? 96 : 74;
                    ctx.fillStyle = 'rgba(24, 24, 37, 0.95)';
                    ctx.fillRect(posXPanel + 8, yInfo, anchoPanel - 16, altoCardInfo);
                    ctx.strokeStyle = this.color;
                    ctx.lineWidth = 1.2;
                    ctx.strokeRect(posXPanel + 8, yInfo, anchoPanel - 16, altoCardInfo);

                    // Título del paso e icono
                    ctx.font = 'bold 9px "Fira Code", monospace';
                    ctx.fillStyle = '#ffffff';
                    ctx.textAlign = 'left';
                    ctx.fillText(`${pasoActual.icono || '⚡'} ${pasoActual.etiqueta}`, posXPanel + 14, yInfo + 15);

                    ctx.font = 'bold 8px "Fira Code", monospace';
                    ctx.fillStyle = this.color;
                    ctx.textAlign = 'right';
                    ctx.fillText(`L${pasoActual.linea_inicio}-${pasoActual.linea_fin}`, posXPanel + anchoPanel - 14, yInfo + 15);

                    // Explicación narrativa
                    ctx.font = '8.5px "Fira Code", monospace';
                    ctx.fillStyle = '#cdd6f4';
                    ctx.textAlign = 'left';

                    const palabrasExp = (pasoActual.explicacion || '').split(' ');
                    let lineaExp = '';
                    let yOffsetExp = yInfo + 30;

                    for (let p = 0; p < palabrasExp.length; p++) {
                        const prueba = lineaExp + (lineaExp ? ' ' : '') + palabrasExp[p];
                        if (ctx.measureText(prueba).width > maxAnchoLinea - 10 && lineaExp) {
                            ctx.fillText(lineaExp, posXPanel + 14, yOffsetExp);
                            lineaExp = palabrasExp[p];
                            yOffsetExp += 13;
                        } else {
                            lineaExp = prueba;
                        }
                    }
                    if (lineaExp) ctx.fillText(lineaExp, posXPanel + 14, yOffsetExp);

                    // Botón de aplicación 1-click del paso
                    if (pasoActual.sugerencia) {
                        const yBtnPaso = yInfo + 70;
                        ctx.fillStyle = 'rgba(148, 226, 213, 0.20)';
                        ctx.fillRect(posXPanel + 12, yBtnPaso, anchoPanel - 24, 20);
                        ctx.strokeStyle = '#94e2d5';
                        ctx.lineWidth = 1.0;
                        ctx.strokeRect(posXPanel + 12, yBtnPaso, anchoPanel - 24, 20);

                        ctx.font = 'bold 8px "Fira Code", monospace';
                        ctx.fillStyle = '#94e2d5';
                        ctx.textAlign = 'center';
                        ctx.fillText(`⚡ APLICAR PASO ${pasoIdx + 1} EN MONACO`, posXPanel + anchoPanel / 2, yBtnPaso + 14);
                        ctx.textAlign = 'left';
                    }
                }

                // Lista de todos los pasos con navegación clickeable
                const yListHeader = yOffsetInicio + 135;
                ctx.font = 'bold 8px "Fira Code", monospace';
                ctx.fillStyle = '#6c7086';
                ctx.textAlign = 'left';
                ctx.fillText('SECUENCIA DE PASOS (CLICK PARA INSPECCIONAR):', posXPanel + 10, yListHeader);

                const yListIni = yListHeader + 10;
                pasos.forEach((p, idx) => {
                    const yCard = yListIni + idx * 36;
                    if (yCard + 32 > posYPanel + altoPanel - 26) return;

                    const esEste = (idx === pasoIdx);
                    ctx.fillStyle = esEste ? 'rgba(137, 180, 250, 0.20)' : 'rgba(17, 17, 27, 0.65)';
                    ctx.fillRect(posXPanel + 8, yCard, anchoPanel - 16, 30);

                    ctx.strokeStyle = esEste ? this.color : '#313244';
                    ctx.lineWidth = esEste ? 1.2 : 0.6;
                    ctx.strokeRect(posXPanel + 8, yCard, anchoPanel - 16, 30);

                    ctx.font = 'bold 8px "Fira Code", monospace';
                    ctx.fillStyle = esEste ? '#ffffff' : '#a6adc8';
                    ctx.textAlign = 'left';
                    ctx.fillText(`${p.icono || '•'} [${idx + 1}] ${p.etiqueta.slice(0, 18)}`, posXPanel + 14, yCard + 14);

                    ctx.font = '7.5px "Fira Code", monospace';
                    ctx.fillStyle = esEste ? this.color : '#89b4fa';
                    ctx.textAlign = 'right';
                    ctx.fillText(`L${p.linea_inicio}-${p.linea_fin}`, posXPanel + anchoPanel - 14, yCard + 14);

                    ctx.font = '7.5px "Fira Code", monospace';
                    ctx.fillStyle = '#6c7086';
                    ctx.textAlign = 'left';
                    ctx.fillText((p.explicacion || '').slice(0, 34) + '...', posXPanel + 14, yCard + 25);
                });
            } else if (this.modoPestana === 'debug') {
                // PESTAÑA 4: DEPURADOR EN VIVO (STEP-BY-STEP WALKTHROUGH ENGINE)
                this._dibujarTabDebugger(ctx, posXPanel, yOffsetInicio, anchoPanel, posYPanel, altoPanel);
            }

            // 5. Barra de estado inferior del panel vertical
            ctx.beginPath();
            ctx.moveTo(posXPanel, posYPanel + altoPanel - 22);
            ctx.lineTo(posXPanel + anchoPanel, posYPanel + altoPanel - 22);
            ctx.strokeStyle = this.color;
            ctx.lineWidth = 0.8;
            ctx.globalAlpha = this.opacidadActual * 0.35;
            ctx.stroke();

            ctx.globalAlpha = this.opacidadActual;
            ctx.font = '8px "Fira Code", monospace';
            ctx.fillStyle = '#a6adc8';
            ctx.textAlign = 'left';
            ctx.fillText(`STATUS: ACTIVE [TAB:${this.modoPestana.toUpperCase()}]`, posXPanel + 10, posYPanel + altoPanel - 8);

            ctx.textAlign = 'right';
            ctx.fillStyle = this.color;
            ctx.fillText(`[DEBUG-WALK]`, posXPanel + anchoPanel - 10, posYPanel + altoPanel - 8);

            ctx.restore();
        }

        _dibujarTabDebugger(ctx, posXPanel, yOffsetInicio, anchoPanel, posYPanel, altoPanel) {
            const dbg = this.debugger || {};
            const estado = dbg.estadoEjecucion || 'PAUSED';
            const lineaActual = dbg.lineaActual || 1;

            ctx.textAlign = 'left';

            // Cabecera de estado del depurador
            ctx.font = 'bold 8.5px "Fira Code", monospace';
            ctx.fillStyle = (estado === 'EXCEPTION') ? '#f38ba8' : ((estado === 'STEPPING') ? '#a6e3a1' : '#f9e2af');
            ctx.fillText(`🐞 DEPURADOR [${estado}]`, posXPanel + 10, yOffsetInicio);

            ctx.font = 'bold 8px "Fira Code", monospace';
            ctx.fillStyle = '#89b4fa';
            ctx.textAlign = 'right';
            ctx.fillText(`PC: ${dbg.variables ? dbg.variables.pc : '0x0010'}`, posXPanel + anchoPanel - 10, yOffsetInicio);

            // Barra de Controles de Paso en Vivo: [F10 OVER] [F11 INTO] [SHIFT+F11] [F5 / PAUSE]
            const yBtns = yOffsetInicio + 14;
            const btnW = (anchoPanel - 24) / 4;
            const botones = [
                { label: 'F10 ↷', tooltip: 'Over' },
                { label: 'F11 ⇲', tooltip: 'Into' },
                { label: '⇧F11 ⇱', tooltip: 'Out' },
                { label: (estado === 'STEPPING' ? '⏸' : '▶ F5'), tooltip: 'Run' }
            ];

            botones.forEach((btn, bIdx) => {
                const bx = posXPanel + 8 + bIdx * btnW;
                ctx.fillStyle = 'rgba(24, 24, 37, 0.95)';
                ctx.fillRect(bx, yBtns, btnW - 3, 22);
                ctx.strokeStyle = (bIdx === 0) ? '#a6e3a1' : '#45475a';
                ctx.lineWidth = (bIdx === 0) ? 1.1 : 0.7;
                ctx.strokeRect(bx, yBtns, btnW - 3, 22);

                ctx.font = 'bold 7.5px "Fira Code", monospace';
                ctx.fillStyle = (bIdx === 0) ? '#a6e3a1' : '#cdd6f4';
                ctx.textAlign = 'center';
                ctx.fillText(btn.label, bx + (btnW - 3) / 2, yBtns + 14);
            });

            // Tarjeta de Línea Activa en Ejecución y Frame
            const yFrameCard = yBtns + 28;
            ctx.fillStyle = (estado === 'EXCEPTION') ? 'rgba(243, 139, 168, 0.15)' : 'rgba(17, 24, 39, 0.85)';
            ctx.fillRect(posXPanel + 8, yFrameCard, anchoPanel - 16, 42);
            ctx.strokeStyle = (estado === 'EXCEPTION') ? '#f38ba8' : this.color;
            ctx.lineWidth = 1.0;
            ctx.strokeRect(posXPanel + 8, yFrameCard, anchoPanel - 16, 42);

            ctx.font = 'bold 8.5px "Fira Code", monospace';
            ctx.fillStyle = (estado === 'EXCEPTION') ? '#f38ba8' : this.color;
            ctx.textAlign = 'left';
            ctx.fillText(`⌖ LÍNEA ACTIVA: L${lineaActual} (${this.moduloActivo || 'main.py'})`, posXPanel + 14, yFrameCard + 15);

            ctx.font = '8px "Fira Code", monospace';
            ctx.fillStyle = '#a6adc8';
            ctx.fillText(`FRAME: ${dbg.variables ? dbg.variables.frame : 'exec_main:L1'}`, posXPanel + 14, yFrameCard + 30);

            // Botón Enfocar en Monaco Editor
            const yBtnFocus = yFrameCard + 48;
            ctx.fillStyle = 'rgba(137, 180, 250, 0.20)';
            ctx.fillRect(posXPanel + 8, yBtnFocus, anchoPanel - 16, 20);
            ctx.strokeStyle = '#89b4fa';
            ctx.lineWidth = 0.9;
            ctx.strokeRect(posXPanel + 8, yBtnFocus, anchoPanel - 16, 20);

            ctx.font = 'bold 8px "Fira Code", monospace';
            ctx.fillStyle = '#89b4fa';
            ctx.textAlign = 'center';
            ctx.fillText('🎯 ENFOCAR LÍNEA EN MONACO', posXPanel + anchoPanel / 2, yBtnFocus + 13);

            // Tabla de Variables Inspeccionadas / Watches
            const yVarHeader = yBtnFocus + 26;
            ctx.font = 'bold 8px "Fira Code", monospace';
            ctx.fillStyle = '#fab387';
            ctx.textAlign = 'left';
            ctx.fillText('📊 VARIABLES DEL STACK FRAME:', posXPanel + 10, yVarHeader);

            const yVarList = yVarHeader + 8;
            const vars = Object.entries(dbg.variables || {});
            vars.slice(0, 4).forEach(([k, v], vIdx) => {
                const yRow = yVarList + vIdx * 18;
                ctx.fillStyle = 'rgba(17, 17, 27, 0.65)';
                ctx.fillRect(posXPanel + 8, yRow, anchoPanel - 16, 16);
                ctx.strokeStyle = '#313244';
                ctx.lineWidth = 0.5;
                ctx.strokeRect(posXPanel + 8, yRow, anchoPanel - 16, 16);

                ctx.font = 'bold 7.5px "Fira Code", monospace';
                ctx.fillStyle = '#cba6f7';
                ctx.textAlign = 'left';
                ctx.fillText(`• ${k}:`, posXPanel + 14, yRow + 11);

                ctx.font = '7.5px "Fira Code", monospace';
                ctx.fillStyle = '#a6e3a1';
                ctx.textAlign = 'right';
                ctx.fillText(String(v).slice(0, 20), posXPanel + anchoPanel - 14, yRow + 11);
            });

            // Call Stack Trace
            const yStackHeader = yVarList + Math.min(4, vars.length) * 18 + 10;
            if (yStackHeader + 40 < posYPanel + altoPanel - 24) {
                ctx.font = 'bold 8px "Fira Code", monospace';
                ctx.fillStyle = '#f9e2af';
                ctx.textAlign = 'left';
                ctx.fillText('📜 PILA DE LLAMADAS (CALL STACK):', posXPanel + 10, yStackHeader);

                const frames = dbg.stackFrames || [];
                frames.slice(0, 3).forEach((fr, fIdx) => {
                    const yFr = yStackHeader + 8 + fIdx * 15;
                    ctx.font = '7.5px "Fira Code", monospace';
                    ctx.fillStyle = (fIdx === 0) ? '#ffffff' : '#6c7086';
                    ctx.fillText(`↳ [${fIdx}] ${fr}`, posXPanel + 14, yFr + 9);
                });
            }
        }
    }

    class DirectorEscenarioASCII {
        constructor() {
            this.temaActivo = 'tema_mecha_patrol';
            this.modeloLLM = 'qwen2.5-coder:7b';
            this.endpointLLM = 'http://localhost:11434';
            this.intervaloDecisionMs = 12000;
            this.ultimoTrigger = 0;
            this.habilitado = true;
            this.consultando = false;
            this.historialReciente = [];

            // Personaje evaluador único situado más atrás y en la zona inferior derecha
            this.evaluador = new PersonajeEvaluadorASCII('evaluador', 'TITAN_MECHA_COMBATE', 'ROBOTS_Y_MECHAS', 'Titán Mecha MK-VII', 'Evaluador');

            this.inicializarEscenario(this.temaActivo);
        }

        inicializarEscenario(temaId) {
            this.temaActivo = temaId || 'tema_mecha_patrol';

            switch (this.temaActivo) {
                case 'tema_mecha_patrol':
                case 'robot_matrix':
                    this.evaluador.asignarArte('ROBOTS_Y_MECHAS', 'TITAN_MECHA_COMBATE', 'Titán Mecha MK-VII', '#a6e3a1', {
                        fuente: 'bold 6px "Fira Code", monospace',
                        interlineado: 7
                    });
                    break;

                case 'tema_cyber_netrunner':
                case 'matrix':
                    this.evaluador.asignarArte('ROBOTS_Y_MECHAS', 'CIBORG_CYBER_SKULL', 'Cyborg Netrunner', '#f38ba8', {
                        fuente: 'bold 6.5px "Fira Code", monospace',
                        interlineado: 7.5
                    });
                    break;

                case 'tema_dragon_sanctuary':
                case 'ascii_santuario_torii':
                case 'ascii_paisaje_zen':
                    this.evaluador.asignarArte('ANIMALES', 'DRAGON_SERPENTINO', 'Dragón Celestial Zen', '#94e2d5', {
                        fuente: 'bold 5.5px "Fira Code", monospace',
                        interlineado: 6.5
                    });
                    break;

                case 'tema_deep_space':
                case 'estrellas':
                case 'ascii_nave_interceptor':
                    this.evaluador.asignarArte('ESPACIO_Y_SCIFI', 'CRUCERO_ESTELAR_GALACTICO', 'Comandante Interestelar', '#89b4fa', {
                        fuente: 'bold 6px "Fira Code", monospace',
                        interlineado: 7
                    });
                    break;

                case 'tema_dungeon_crawler':
                    this.evaluador.asignarArte('CALAVERAS', 'REAPER_SEGADOR', 'El Segador de Código', '#cba6f7', {
                        fuente: 'bold 6.5px "Fira Code", monospace',
                        interlineado: 7.5
                    });
                    break;

                case 'tema_wild_nature':
                    this.evaluador.asignarArte('ANIMALES', 'BUHO_SABIO', 'Búho Filósofo', '#89dceb', {
                        fuente: 'bold 6.5px "Fira Code", monospace',
                        interlineado: 7.5
                    });
                    break;

                case 'tema_retro_arcade':
                    this.evaluador.asignarArte('RETRO_GAMING', 'GAMEBOY_RETRO', 'Gameboy 8-Bit Evaluator', '#f9e2af', {
                        fuente: 'bold 6.5px "Fira Code", monospace',
                        interlineado: 7.5
                    });
                    break;

                case 'tema_quantum_void':
                case 'ascii_monolito_cosmico':
                    this.evaluador.asignarArte('GEOMETRIA_3D', 'CUBO_ISOMETRICO_DITHER', 'Oráculo Hipercubo 4D', '#cba6f7', {
                        fuente: 'bold 6px "Fira Code", monospace',
                        interlineado: 7
                    });
                    break;

                case 'tema_neural_cybergrid':
                    this.evaluador.asignarArte('ROBOTS_Y_MECHAS', 'CIBORG_CYBER_SKULL', 'Núcleo Synapse-X', '#89dceb', {
                        fuente: 'bold 6.5px "Fira Code", monospace',
                        interlineado: 7.5
                    });
                    break;

                case 'tema_steampunk_observatory':
                    this.evaluador.asignarArte('ROBOTS_Y_MECHAS', 'ANDROIDE_COMPACTO', 'Autómata de Engranajes', '#f9e2af', {
                        fuente: 'bold 6.5px "Fira Code", monospace',
                        interlineado: 7.5
                    });
                    break;

                case 'tema_bioluminescent_abyss':
                    this.evaluador.asignarArte('ANIMALES', 'DRAGON_SERPENTINO', 'Leviatán Abisal', '#74c7ec', {
                        fuente: 'bold 5.5px "Fira Code", monospace',
                        interlineado: 6.5
                    });
                    break;

                case 'tema_alchemist_laboratory':
                    this.evaluador.asignarArte('CALAVERAS', 'REAPER_SEGADOR', 'Maestro Transmutador', '#cba6f7', {
                        fuente: 'bold 6.5px "Fira Code", monospace',
                        interlineado: 7.5
                    });
                    break;

                default:
                    this.evaluador.asignarArte('ROBOTS_Y_MECHAS', 'ANDROIDE_COMPACTO', 'Androide Evaluador', '#a6e3a1', {
                        fuente: 'bold 6.5px "Fira Code", monospace',
                        interlineado: 7.5
                    });
                    break;
            }

            setTimeout(() => this.dispararDecisionDirector('cambio_tema'), 250);
        }

        _obtenerContextoEditor() {
            let codigo = '';
            let archivo = 'main.py';
            let lenguaje = 'python';
            let linea = 1;

            if (window.editorMgr) {
                if (window.editorMgr.editor) {
                    codigo = window.editorMgr.editor.getValue() || '';
                    const pos = window.editorMgr.editor.getPosition();
                    if (pos) linea = pos.lineNumber;
                }
                if (window.editorMgr.activeTab) {
                    archivo = window.editorMgr.activeTab;
                    if (archivo.endsWith('.js')) lenguaje = 'javascript';
                    else if (archivo.endsWith('.ts')) lenguaje = 'typescript';
                    else if (archivo.endsWith('.py')) lenguaje = 'python';
                    else if (archivo.endsWith('.html')) lenguaje = 'html';
                    else if (archivo.endsWith('.css')) lenguaje = 'css';
                    else if (archivo.endsWith('.cpp') || archivo.endsWith('.c')) lenguaje = 'c_cpp';
                    else if (archivo.endsWith('.rs')) lenguaje = 'rust';
                }
            }

            return {
                archivo_actual: archivo,
                lenguaje: lenguaje,
                linea_cursor: linea,
                codigo_reciente: codigo,
                codigo_completo: codigo,
                total_lineas: codigo.split('\n').length,
                audio_activo: !!(window.AUDIO_REACTIVO_GLOBAL && window.AUDIO_REACTIVO_GLOBAL.activo)
            };
        }

        actualizar(dt, cursorTexto, canvasW, canvasH) {
            const ahora = performance.now();

            if (this.evaluador) {
                this.evaluador.actualizar(dt, cursorTexto, canvasW, canvasH);
            }

            if (this.habilitado && ahora - this.ultimoTrigger > this.intervaloDecisionMs && !this.consultando) {
                this.dispararDecisionDirector();
            }
        }

        dibujar(ctx, canvasW, canvasH) {
            if (this.evaluador) {
                this.evaluador.dibujar(ctx, canvasW, canvasH);
            }
        }

        async dispararDecisionDirector(eventoManual = null) {
            if (this.consultando) return;
            this.consultando = true;
            this.ultimoTrigger = performance.now();

            const contexto = this._obtenerContextoEditor();
            if (eventoManual) contexto.actividad = eventoManual;

            try {
                // 1. Intentar streaming reactivo Server-Sent Events (<150ms latencia)
                const resp = await fetch('/api/llm/director_stream', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        tema_id: this.temaActivo,
                        contexto: contexto,
                        modelo: this.modeloLLM,
                        endpoint: this.endpointLLM
                    })
                });

                if (resp.ok && resp.body) {
                    const reader = resp.body.getReader();
                    const decoder = new TextDecoder('utf-8');
                    let buffer = '';
                    let textoStream = '';

                    while (true) {
                        const { done, value } = await reader.read();
                        if (done) break;
                        buffer += decoder.decode(value, { stream: true });

                        const lineas = buffer.split('\n');
                        buffer = lineas.pop() || '';

                        for (const linea of lineas) {
                            const lTrim = linea.trim();
                            if (lTrim.startsWith('data: ')) {
                                try {
                                    const evento = JSON.parse(lTrim.slice(6));
                                    if (evento.tipo === 'token' && evento.contenido) {
                                        textoStream += evento.contenido;
                                        if (this.evaluador && this.evaluador.dialogo) {
                                            this.evaluador.dialogo.texto = textoStream;
                                            this.evaluador.dialogo.charIndex = textoStream.length;
                                            this.evaluador.dialogo.estado = 'streaming';
                                        }
                                    } else if (evento.tipo === 'decision_completa' && evento.data) {
                                        this.aplicarDecision(evento.data.decision || evento.data);
                                    }
                                } catch (e) {}
                            }
                        }
                    }
                } else {
                    // 2. Fallback a llamada directa si no hay soporte de streaming
                    const fallResp = await fetch('/api/llm/director_decision', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            tema_id: this.temaActivo,
                            contexto: contexto,
                            modelo: this.modeloLLM,
                            endpoint: this.endpointLLM
                        })
                    });
                    if (fallResp.ok) {
                        const data = await fallResp.json();
                        if (data.ok && data.data && data.data.decision) {
                            this.aplicarDecision(data.data.decision);
                        }
                    }
                }
            } catch (err) {
                console.debug('Fallo conexión con Evaluador LLM (Stream):', err);
            } finally {
                this.consultando = false;
            }
        }

        aplicarDecision(decision) {
            if (!decision) return;
            const dialogo = decision.dialogo;
            const pos = decision.posicion;

            if (dialogo && this.evaluador) {
                this.evaluador.evaluarCodigo(dialogo, 20000);
            }

            // El personaje puede moverse en la zona inferior según la decisión del modelo
            if (pos && typeof pos.x_ratio === 'number' && this.evaluador) {
                this.evaluador.establecerDestino(pos.x_ratio, pos.y_ratio);
            }

            // Ecosistema: Haz de inspección y retícula de telemetría de código
            if (decision.inspeccion && this.evaluador) {
                this.evaluador.establecerInspeccion(decision.inspeccion);
            }

            // Motor de Relación Visual: Consejos y Flujo
            if (decision.consejo && this.evaluador) {
                this.evaluador.establecerConsejo(decision.consejo);
            }
            if (decision.flujo_ascii && this.evaluador) {
                this.evaluador.establecerFlujo(decision.flujo_ascii);
            }
            if (decision.flujo_grafico && this.evaluador) {
                this.evaluador.establecerFlujoGrafico(decision.flujo_grafico);
            }

            // Métricas y módulo activo para el panel HUD
            if (decision.metricas && this.evaluador) {
                this.evaluador.metricas = decision.metricas;
            }
            if (decision.modulo_activo && this.evaluador) {
                this.evaluador.moduloActivo = decision.modulo_activo;
            }

            this.historialReciente.push(decision);
            if (this.historialReciente.length > 20) this.historialReciente.shift();

            if (typeof window !== 'undefined' && window.CerebroMemoria) {
                window.CerebroMemoria.actualizarMemoria();
            }
        }
    }

    // Instancia global
    if (typeof window !== 'undefined') {
        window.DIRECTOR_ASCII = new DirectorEscenarioASCII();
    }

})(typeof window !== 'undefined' ? window : globalThis);

