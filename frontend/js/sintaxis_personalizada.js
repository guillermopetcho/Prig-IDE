/**
 * Gestor de Sintaxis, Resaltado de Código y Efectos Raros de Tokens para Prig IDE.
 * 
 * Características:
 * 1. Personalización de colores, tipografía (negrita/cursiva/subrayado) y efectos raros para:
 *    - Keywords (palabras reservadas: def, class, import, return, if, while...)
 *    - Types (tipos de datos y clases: int, str, dict, Promise, Any...)
 *    - Functions (funciones y métodos: print(), calculate(), render()...)
 *    - Strings (cadenas de texto: "...", '...', `...`, f"...")
 *    - Numbers (números y booleanos: 42, 3.14, true, false, null...)
 *    - Comments (comentarios: #, //, /*, """docstring""")
 *    - Operators (operadores y símbolos: +, -, =>, ===, &&, ||...)
 *    - Variables (identificadores y variables: mi_var, x, total...)
 * 2. Efectos visuales raros y de arte abstracto (Glitch RGB, Arcoíris animado, Resplandor neón,
 *    Subrayado en onda, Fuego retro, Fantasma holográfico, Líneas de escaneo CRT).
 * 3. Inyección de CSS libre en vivo para Monaco Editor.
 * 4. Integración nativa y dinámica con Monaco Editor (monaco.editor.defineTheme y setTheme).
 * 5. Persistencia dual: guardado instantáneo en localStorage y persistencia permanente en backend (.prig_dataset).
 */

const PRESETS_SINTAXIS_RARA = {
    cyberpunk_glitch: {
        nombre: 'Cyberpunk Glitch Matrix',
        icono: 'fa-bolt',
        desc: 'Palabras reservadas con aberración cromática Glitch RGB, strings verde flúor y resplandor neón.',
        tokens: {
            keyword: { color: '#ff007f', fontStyle: 'bold', efectoRaro: 'glitch_rgb' },
            type: { color: '#00ffff', fontStyle: 'bold', efectoRaro: 'resplandor_neon' },
            function: { color: '#00ff66', fontStyle: 'bold', efectoRaro: 'resplandor_neon' },
            string: { color: '#ffe600', fontStyle: '', efectoRaro: 'ninguno' },
            number: { color: '#ff0055', fontStyle: 'bold', efectoRaro: 'ninguno' },
            comment: { color: '#a277ff', fontStyle: 'italic', efectoRaro: 'ninguno' },
            operator: { color: '#00f0ff', fontStyle: '', efectoRaro: 'ninguno' },
            variable: { color: '#00ffff', fontStyle: '', efectoRaro: 'ninguno' }
        },
        efectosGlobales: {
            lineasEscaneo: false,
            resplandorCursor: true,
            codigoCss: ''
        }
    },
    psicodelia_fractal: {
        nombre: 'Psicodelia Cósmica Arcoíris',
        icono: 'fa-eye',
        desc: 'Palabras reservadas con degradado arcoíris animado en vivo, funciones fucsia y tipos ácido.',
        tokens: {
            keyword: { color: '#ff007f', fontStyle: 'bold', efectoRaro: 'arcoiris_animado' },
            type: { color: '#39ff14', fontStyle: 'bold italic', efectoRaro: 'resplandor_neon' },
            function: { color: '#ffff00', fontStyle: 'bold', efectoRaro: 'resplandor_neon' },
            string: { color: '#00f5d4', fontStyle: '', efectoRaro: 'ninguno' },
            number: { color: '#ff007f', fontStyle: 'bold', efectoRaro: 'ninguno' },
            comment: { color: '#7b2cbf', fontStyle: 'italic', efectoRaro: 'ninguno' },
            operator: { color: '#ff007f', fontStyle: 'bold', efectoRaro: 'ninguno' },
            variable: { color: '#ffffff', fontStyle: '', efectoRaro: 'ninguno' }
        },
        efectosGlobales: {
            lineasEscaneo: false,
            resplandorCursor: true,
            codigoCss: ''
        }
    },
    terminal_crt_ambar: {
        nombre: 'Terminal Fósforo Ámbar 1978',
        icono: 'fa-tv',
        desc: 'Estética analógica monocromo ámbar con líneas de escaneo CRT y resplandor de fósforo.',
        tokens: {
            keyword: { color: '#ffb000', fontStyle: 'bold', efectoRaro: 'resplandor_neon' },
            type: { color: '#ff8000', fontStyle: 'bold', efectoRaro: 'ninguno' },
            function: { color: '#ffd000', fontStyle: 'bold', efectoRaro: 'resplandor_neon' },
            string: { color: '#ff9900', fontStyle: '', efectoRaro: 'ninguno' },
            number: { color: '#ffcc00', fontStyle: '', efectoRaro: 'ninguno' },
            comment: { color: '#b36b00', fontStyle: 'italic', efectoRaro: 'ninguno' },
            operator: { color: '#ffb000', fontStyle: '', efectoRaro: 'ninguno' },
            variable: { color: '#ffaa00', fontStyle: '', efectoRaro: 'ninguno' }
        },
        efectosGlobales: {
            lineasEscaneo: true,
            resplandorCursor: true,
            codigoCss: `
                .monaco-editor {
                    text-shadow: 0 0 5px rgba(255, 176, 0, 0.6) !important;
                }
            `
        }
    },
    grimorio_alquimico: {
        nombre: 'Grimorio Alquímico Oculto',
        icono: 'fa-book-skull',
        desc: 'Palabras reservadas en oro alquímico ardiente, comentarios en rojo sangre y strings papiro.',
        tokens: {
            keyword: { color: '#dfb15b', fontStyle: 'bold', efectoRaro: 'fuego_retro' },
            type: { color: '#c49746', fontStyle: 'bold', efectoRaro: 'resplandor_neon' },
            function: { color: '#e8c170', fontStyle: '', efectoRaro: 'ninguno' },
            string: { color: '#bca16d', fontStyle: '', efectoRaro: 'ninguno' },
            number: { color: '#e2725b', fontStyle: 'bold', efectoRaro: 'ninguno' },
            comment: { color: '#9b111e', fontStyle: 'italic', efectoRaro: 'ninguno' },
            operator: { color: '#dfb15b', fontStyle: '', efectoRaro: 'ninguno' },
            variable: { color: '#e6dec8', fontStyle: '', efectoRaro: 'ninguno' }
        },
        efectosGlobales: {
            lineasEscaneo: false,
            resplandorCursor: false,
            codigoCss: ''
        }
    },
    bioluminiscencia_alien: {
        nombre: 'Bioluminiscencia Alienígena',
        icono: 'fa-dna',
        desc: 'Verde radioactivo uranio, esporas violeta plasma y palabras reservadas en cian Cerenkov.',
        tokens: {
            keyword: { color: '#00e5ff', fontStyle: 'bold', efectoRaro: 'resplandor_neon' },
            type: { color: '#52ff00', fontStyle: 'bold', efectoRaro: 'resplandor_neon' },
            function: { color: '#00ff41', fontStyle: 'bold', efectoRaro: 'ninguno' },
            string: { color: '#7209b7', fontStyle: '', efectoRaro: 'ninguno' },
            number: { color: '#39ff14', fontStyle: 'bold', efectoRaro: 'ninguno' },
            comment: { color: '#386641', fontStyle: 'italic', efectoRaro: 'ninguno' },
            operator: { color: '#00ff41', fontStyle: '', efectoRaro: 'ninguno' },
            variable: { color: '#a7ff83', fontStyle: '', efectoRaro: 'ninguno' }
        },
        efectosGlobales: {
            lineasEscaneo: false,
            resplandorCursor: true,
            codigoCss: ''
        }
    },
    vaporwave_dream: {
        nombre: 'Vaporwave 1999 Dream',
        icono: 'fa-compact-disc',
        desc: 'Magenta chill hiperpop, cian retro, comentarios pastel y subrayados ondulantes.',
        tokens: {
            keyword: { color: '#ff71ce', fontStyle: 'bold', efectoRaro: 'subrayado_onda' },
            type: { color: '#01cdfe', fontStyle: 'bold', efectoRaro: 'resplandor_neon' },
            function: { color: '#05ffa1', fontStyle: 'bold', efectoRaro: 'ninguno' },
            string: { color: '#fffb96', fontStyle: '', efectoRaro: 'ninguno' },
            number: { color: '#b967ff', fontStyle: 'bold', efectoRaro: 'ninguno' },
            comment: { color: '#7a5299', fontStyle: 'italic', efectoRaro: 'ninguno' },
            operator: { color: '#01cdfe', fontStyle: '', efectoRaro: 'ninguno' },
            variable: { color: '#fcfcfc', fontStyle: '', efectoRaro: 'ninguno' }
        },
        efectosGlobales: {
            lineasEscaneo: false,
            resplandorCursor: true,
            codigoCss: ''
        }
    },
    surrealismo_dali: {
        nombre: 'Relojes Derretidos de Dalí',
        icono: 'fa-clock',
        desc: 'Azul cobalto onírico, ocre desierto y comentarios terracota con tipografía flotante.',
        tokens: {
            keyword: { color: '#f4d35e', fontStyle: 'bold', efectoRaro: 'resplandor_neon' },
            type: { color: '#3a86ff', fontStyle: 'bold', efectoRaro: 'ninguno' },
            function: { color: '#ee964b', fontStyle: 'bold italic', efectoRaro: 'ninguno' },
            string: { color: '#f95738', fontStyle: '', efectoRaro: 'ninguno' },
            number: { color: '#f4d35e', fontStyle: 'bold', efectoRaro: 'ninguno' },
            comment: { color: '#a08070', fontStyle: 'italic', efectoRaro: 'ninguno' },
            operator: { color: '#ee964b', fontStyle: '', efectoRaro: 'ninguno' },
            variable: { color: '#ebebd3', fontStyle: '', efectoRaro: 'ninguno' }
        },
        efectosGlobales: {
            lineasEscaneo: false,
            resplandorCursor: false,
            codigoCss: ''
        }
    },
    monokai_bizarro: {
        nombre: 'Monokai Bizarro Multiverso',
        icono: 'fa-cubes-stacked',
        desc: 'Versión psicodélica saturada de Monokai con palabras reservadas fucsia y funciones cian eléctrico.',
        tokens: {
            keyword: { color: '#ff007f', fontStyle: 'bold', efectoRaro: 'resplandor_neon' },
            type: { color: '#66d9ef', fontStyle: 'bold italic', efectoRaro: 'ninguno' },
            function: { color: '#a6e22e', fontStyle: 'bold', efectoRaro: 'resplandor_neon' },
            string: { color: '#e6db74', fontStyle: '', efectoRaro: 'ninguno' },
            number: { color: '#ae81ff', fontStyle: 'bold', efectoRaro: 'ninguno' },
            comment: { color: '#88846f', fontStyle: 'italic', efectoRaro: 'ninguno' },
            operator: { color: '#f92672', fontStyle: '', efectoRaro: 'ninguno' },
            variable: { color: '#fd971f', fontStyle: '', efectoRaro: 'ninguno' }
        },
        efectosGlobales: {
            lineasEscaneo: false,
            resplandorCursor: true,
            codigoCss: ''
        }
    },
    dracula_vampirico: {
        nombre: 'Drácula Sangre & Niebla',
        icono: 'fa-vampire',
        desc: 'Comentarios en niebla espectral, palabras reservadas en sangre carmesí y funciones en amatista.',
        tokens: {
            keyword: { color: '#ff5555', fontStyle: 'bold', efectoRaro: 'fuego_retro' },
            type: { color: '#8be9fd', fontStyle: 'bold', efectoRaro: 'ninguno' },
            function: { color: '#50fa7b', fontStyle: 'bold', efectoRaro: 'resplandor_neon' },
            string: { color: '#f1fa8c', fontStyle: '', efectoRaro: 'ninguno' },
            number: { color: '#bd93f9', fontStyle: 'bold', efectoRaro: 'ninguno' },
            comment: { color: '#8a99c7', fontStyle: 'italic', efectoRaro: 'fantasma_italica' },
            operator: { color: '#ff79c6', fontStyle: '', efectoRaro: 'ninguno' },
            variable: { color: '#f8f8f2', fontStyle: '', efectoRaro: 'ninguno' }
        },
        efectosGlobales: {
            lineasEscaneo: false,
            resplandorCursor: true,
            codigoCss: ''
        }
    },
    nord_aurora_mistica: {
        nombre: 'Nord Aurora Boreal Mística',
        icono: 'fa-snowflake',
        desc: 'Azules glaciales, turquesas árticos y palabras reservadas que fluyen con resplandor boreal.',
        tokens: {
            keyword: { color: '#88c0d0', fontStyle: 'bold', efectoRaro: 'resplandor_neon' },
            type: { color: '#81a1c1', fontStyle: 'bold', efectoRaro: 'ninguno' },
            function: { color: '#8fbcbb', fontStyle: 'bold', efectoRaro: 'subrayado_onda' },
            string: { color: '#a3be8c', fontStyle: '', efectoRaro: 'ninguno' },
            number: { color: '#b48ead', fontStyle: 'bold', efectoRaro: 'ninguno' },
            comment: { color: '#616e88', fontStyle: 'italic', efectoRaro: 'ninguno' },
            operator: { color: '#81a1c1', fontStyle: '', efectoRaro: 'ninguno' },
            variable: { color: '#eceff4', fontStyle: '', efectoRaro: 'ninguno' }
        },
        efectosGlobales: {
            lineasEscaneo: false,
            resplandorCursor: true,
            codigoCss: ''
        }
    },
    lava_arcade_8bit: {
        nombre: '8-Bit Lava Arcade Retro',
        icono: 'fa-gamepad',
        desc: 'Rojo volcánico, naranja píxel incandescente y efectos de fuego para palabras reservadas.',
        tokens: {
            keyword: { color: '#ff3d00', fontStyle: 'bold', efectoRaro: 'fuego_retro' },
            type: { color: '#ff9100', fontStyle: 'bold', efectoRaro: 'resplandor_neon' },
            function: { color: '#ffea00', fontStyle: 'bold', efectoRaro: 'ninguno' },
            string: { color: '#00e676', fontStyle: '', efectoRaro: 'ninguno' },
            number: { color: '#d500f9', fontStyle: 'bold', efectoRaro: 'ninguno' },
            comment: { color: '#a1887f', fontStyle: 'italic', efectoRaro: 'ninguno' },
            operator: { color: '#ff3d00', fontStyle: '', efectoRaro: 'ninguno' },
            variable: { color: '#ffffff', fontStyle: '', efectoRaro: 'ninguno' }
        },
        efectosGlobales: {
            lineasEscaneo: false,
            resplandorCursor: true,
            codigoCss: ''
        }
    },
    singularidad_inversa: {
        nombre: 'Singularidad Cuántica Invertida',
        icono: 'fa-atom',
        desc: 'Fondo de alta visibilidad, palabras en arcoíris cuántico, tipos en cian láser y funciones en plasma.',
        tokens: {
            keyword: { color: '#ff77e9', fontStyle: 'bold', efectoRaro: 'arcoiris_animado' },
            type: { color: '#00f0ff', fontStyle: 'bold', efectoRaro: 'resplandor_neon' },
            function: { color: '#bd66ff', fontStyle: 'bold', efectoRaro: 'resplandor_neon' },
            string: { color: '#00ffb3', fontStyle: '', efectoRaro: 'ninguno' },
            number: { color: '#ff0055', fontStyle: 'bold', efectoRaro: 'ninguno' },
            comment: { color: '#8899b8', fontStyle: 'italic', efectoRaro: 'ninguno' },
            operator: { color: '#fff01f', fontStyle: 'bold', efectoRaro: 'ninguno' },
            variable: { color: '#ffffff', fontStyle: '', efectoRaro: 'ninguno' }
        },
        efectosGlobales: {
            lineasEscaneo: false,
            resplandorCursor: true,
            codigoCss: ''
        }
    },
    bauhaus_abstracto: {
        nombre: 'Vanguardia Bauhaus Abstracta',
        icono: 'fa-shapes',
        desc: 'Rojo primario constructivista, azul cobalto, amarillo puro y tipografía geométrica.',
        tokens: {
            keyword: { color: '#e63946', fontStyle: 'bold', efectoRaro: 'resplandor_neon' },
            type: { color: '#4895ef', fontStyle: 'bold', efectoRaro: 'ninguno' },
            function: { color: '#4cc9f0', fontStyle: 'bold', efectoRaro: 'ninguno' },
            string: { color: '#2a9d8f', fontStyle: '', efectoRaro: 'ninguno' },
            number: { color: '#e9c46a', fontStyle: 'bold', efectoRaro: 'ninguno' },
            comment: { color: '#8d99ae', fontStyle: 'italic', efectoRaro: 'ninguno' },
            operator: { color: '#e63946', fontStyle: '', efectoRaro: 'ninguno' },
            variable: { color: '#f1faee', fontStyle: '', efectoRaro: 'ninguno' }
        },
        efectosGlobales: {
            lineasEscaneo: false,
            resplandorCursor: false,
            aberracionCromaticaGlobal: false,
            vignetteRetro: false,
            fondoVidrioLiquido: false,
            lineaActivaPulsante: false,
            seleccionGalactica: false,
            codigoCss: ''
        }
    },
    abismo_cuantico: {
        nombre: 'Abismo Cuántico Event Horizon',
        icono: 'fa-circle-notch',
        desc: 'Singularidad gravitacional con vórtice oscuro en palabras reservadas y radiación Hawking en funciones.',
        tokens: {
            keyword: { color: '#d000ff', fontStyle: 'bold', efectoRaro: 'vortice_gravedad_negra' },
            type: { color: '#00f7ff', fontStyle: 'bold', efectoRaro: 'plasma_pulsar_electrico' },
            function: { color: '#ff007f', fontStyle: 'bold', efectoRaro: 'resplandor_neon' },
            string: { color: '#7000ff', fontStyle: '', efectoRaro: 'niebla_espectral' },
            number: { color: '#00ffc2', fontStyle: 'bold', efectoRaro: 'arcoiris_animado' },
            comment: { color: '#9d81ba', fontStyle: 'italic', efectoRaro: 'fantasma_italica' },
            operator: { color: '#d000ff', fontStyle: 'bold', efectoRaro: 'ninguno' },
            variable: { color: '#ffffff', fontStyle: '', efectoRaro: 'ninguno' }
        },
        efectosGlobales: {
            lineasEscaneo: false,
            resplandorCursor: true,
            aberracionCromaticaGlobal: false,
            vignetteRetro: false,
            fondoVidrioLiquido: false,
            lineaActivaPulsante: true,
            seleccionGalactica: true,
            codigoCss: ''
        }
    },
    uraniocore_radiactivo: {
        nombre: 'UranioCore Fisión 235',
        icono: 'fa-radiation',
        desc: 'Verde radiactivo extremo con niebla tóxica pulsante y resplandor Cerenkov en tipos.',
        tokens: {
            keyword: { color: '#76ff03', fontStyle: 'bold', efectoRaro: 'radioactivo_uranio' },
            type: { color: '#00e5ff', fontStyle: 'bold', efectoRaro: 'plasma_pulsar_electrico' },
            function: { color: '#b2ff59', fontStyle: 'bold', efectoRaro: 'resplandor_neon' },
            string: { color: '#ffd600', fontStyle: '', efectoRaro: 'ninguno' },
            number: { color: '#ff1744', fontStyle: 'bold', efectoRaro: 'fuego_retro' },
            comment: { color: '#7cb342', fontStyle: 'italic', efectoRaro: 'niebla_espectral' },
            operator: { color: '#76ff03', fontStyle: '', efectoRaro: 'ninguno' },
            variable: { color: '#ccff90', fontStyle: '', efectoRaro: 'ninguno' }
        },
        efectosGlobales: {
            lineasEscaneo: false,
            resplandorCursor: true,
            aberracionCromaticaGlobal: false,
            vignetteRetro: false,
            fondoVidrioLiquido: false,
            lineaActivaPulsante: true,
            seleccionGalactica: true,
            codigoCss: ''
        }
    },
    matriz_alquimica_oro: {
        nombre: 'Matriz Alquímica Dorada',
        icono: 'fa-gem',
        desc: 'Shimmer reflectante de oro líquido sobre papiro místico y símbolos esotéricos.',
        tokens: {
            keyword: { color: '#ffd700', fontStyle: 'bold', efectoRaro: 'oro_alquimico_brillo' },
            type: { color: '#ffb703', fontStyle: 'bold', efectoRaro: 'cristal_prismatico' },
            function: { color: '#ffea75', fontStyle: 'bold', efectoRaro: 'resplandor_neon' },
            string: { color: '#e0c068', fontStyle: '', efectoRaro: 'ninguno' },
            number: { color: '#ff7b54', fontStyle: 'bold', efectoRaro: 'fuego_retro' },
            comment: { color: '#bca16d', fontStyle: 'italic', efectoRaro: 'fantasma_italica' },
            operator: { color: '#ffd700', fontStyle: '', efectoRaro: 'ninguno' },
            variable: { color: '#fff8dc', fontStyle: '', efectoRaro: 'ninguno' }
        },
        efectosGlobales: {
            lineasEscaneo: false,
            resplandorCursor: true,
            aberracionCromaticaGlobal: false,
            vignetteRetro: false,
            fondoVidrioLiquido: false,
            lineaActivaPulsante: true,
            seleccionGalactica: false,
            codigoCss: ''
        }
    }
};

class SintaxisManager {
    constructor() {
        this.def = {
            presetActivo: 'personalizado',
            tokens: {
                keyword: { color: '#cba6f7', fontStyle: 'bold', efectoRaro: 'ninguno' },
                type: { color: '#89b4fa', fontStyle: 'bold', efectoRaro: 'ninguno' },
                function: { color: '#89dceb', fontStyle: '', efectoRaro: 'ninguno' },
                string: { color: '#a6e3a1', fontStyle: '', efectoRaro: 'ninguno' },
                number: { color: '#fab387', fontStyle: '', efectoRaro: 'ninguno' },
                comment: { color: '#6c7086', fontStyle: 'italic', efectoRaro: 'ninguno' },
                operator: { color: '#89dceb', fontStyle: '', efectoRaro: 'ninguno' },
                variable: { color: '#cdd6f4', fontStyle: '', efectoRaro: 'ninguno' }
            },
            efectosGlobales: {
                lineasEscaneo: false,
                resplandorCursor: false,
                aberracionCromaticaGlobal: false,
                vignetteRetro: false,
                fondoVidrioLiquido: false,
                lineaActivaPulsante: false,
                seleccionGalactica: false,
                codigoCss: ''
            }
        };

        this.estado = this._cargar();
        this._guardarTimer = null;

        // Sincronizar con el backend de inmediato
        this.sincronizarBackend();
    }

    _cargar() {
        try {
            const raw = localStorage.getItem('prig_sintaxis_personalizada');
            if (!raw) return JSON.parse(JSON.stringify(this.def));
            const data = JSON.parse(raw);
            return {
                ...JSON.parse(JSON.stringify(this.def)),
                ...data,
                tokens: { ...this.def.tokens, ...(data.tokens || {}) },
                efectosGlobales: { ...this.def.efectosGlobales, ...(data.efectosGlobales || {}) }
            };
        } catch (e) {
            return JSON.parse(JSON.stringify(this.def));
        }
    }

    async sincronizarBackend() {
        try {
            const res = await fetch('/api/config/sintaxis');
            if (res.ok) {
                const data = await res.json();
                if (data && typeof data === 'object' && Object.keys(data).length > 0 && data.tokens) {
                    this.estado = {
                        ...JSON.parse(JSON.stringify(this.def)),
                        ...data,
                        tokens: { ...this.def.tokens, ...(data.tokens || {}) },
                        efectosGlobales: { ...this.def.efectosGlobales, ...(data.efectosGlobales || {}) }
                    };
                    try {
                        localStorage.setItem('prig_sintaxis_personalizada', JSON.stringify(this.estado));
                    } catch (e) {}
                    this.aplicar();
                } else if (!localStorage.getItem('prig_sintaxis_personalizada')) {
                    this._guardarBackendInmediato();
                }
            }
        } catch (e) {
            // Silencioso
        }
    }

    _guardarBackendInmediato() {
        try {
            fetch('/api/config/sintaxis', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(this.estado)
            }).catch(() => {});
        } catch (e) {}
    }

    _guardar() {
        // 1. Guardar en localStorage para respuesta 0ms
        try {
            localStorage.setItem('prig_sintaxis_personalizada', JSON.stringify(this.estado));
        } catch (e) {
            console.warn("No se pudo guardar la configuración de sintaxis:", e);
        }

        // 2. Guardar en disco persistente backend
        if (this._guardarTimer) clearTimeout(this._guardarTimer);
        this._guardarTimer = setTimeout(() => {
            this._guardarBackendInmediato();
        }, 200);
    }

    aplicar() {
        // 1. Inyectar estilos CSS especiales (glitch, arcoiris, neon, scanlines, custom css)
        this._inyectarEstilosEspeciales();

        // 2. Definir y aplicar tema dinámico en Monaco Editor
        this._aplicarTemaMonaco();
    }

    _inyectarEstilosEspeciales() {
        let el = document.getElementById('prig-estilos-sintaxis-especial');
        if (!el) {
            el = document.createElement('style');
            el.id = 'prig-estilos-sintaxis-especial';
            document.head.appendChild(el);
        }

        const tokens = this.estado.tokens || {};
        const glob = this.estado.efectosGlobales || {};
        let reglas = [];

        // Keyframes completos de efectos raros (usando text-shadow para máxima nitidez y cero degradación)
        reglas.push(`
            @keyframes prigGlitchTexto {
                0%, 100% { text-shadow: 0 0 4px currentColor; }
                20% { text-shadow: -2px 0 #ff0055, 2px 0 #00ffff, 0 0 8px currentColor; }
                40% { text-shadow: 2px 0 #ff0055, -2px 0 #00ffff, 0 0 8px currentColor; }
                60% { text-shadow: -1.5px 0 #00ff66, 1.5px 0 #ff007f, 0 0 10px currentColor; }
                80% { text-shadow: 2px 0 #ffe600, -2px 0 #00f0ff, 0 0 8px currentColor; }
            }

            @keyframes prigArcoirisTexto {
                0% { color: #ff007f !important; text-shadow: 0 0 8px #ff007f, 0 0 16px #ff007f !important; }
                20% { color: #ff00ff !important; text-shadow: 0 0 8px #ff00ff, 0 0 16px #ff00ff !important; }
                40% { color: #00ffff !important; text-shadow: 0 0 8px #00ffff, 0 0 16px #00ffff !important; }
                60% { color: #00ff66 !important; text-shadow: 0 0 8px #00ff66, 0 0 16px #00ff66 !important; }
                80% { color: #ffe600 !important; text-shadow: 0 0 8px #ffe600, 0 0 16px #ffe600 !important; }
                100% { color: #ff007f !important; text-shadow: 0 0 8px #ff007f, 0 0 16px #ff007f !important; }
            }

            @keyframes prigPulsoNeonTexto {
                0%, 100% { text-shadow: 0 0 4px currentColor, 0 0 10px currentColor; opacity: 0.95; }
                50% { text-shadow: 0 0 8px currentColor, 0 0 20px currentColor, 0 0 32px currentColor; opacity: 1; }
            }

            @keyframes prigOndaSubrayado {
                0% { text-decoration-color: #ff007f; }
                50% { text-decoration-color: #00ffff; }
                100% { text-decoration-color: #ff007f; }
            }

            @keyframes prigFuegoTexto {
                0%, 100% { text-shadow: 0 0 5px #ff4500, 0 -2px 10px #ffd700; }
                50% { text-shadow: 0 0 10px #ff8c00, 0 -4px 18px #ff0000; }
            }

            @keyframes prigPlasmaPulsar {
                0%, 100% { text-shadow: 0 0 6px #7000ff, 0 0 12px #00ffff; }
                30% { text-shadow: 0 0 14px #ff007f, 0 0 24px #7000ff; }
                60% { text-shadow: 0 0 4px #00ffff, 0 0 10px #7000ff; }
            }

            @keyframes prigOroBrillo {
                0%, 100% { text-shadow: 0 0 6px #ffd700, 0 0 12px #ffd700; }
                50% { text-shadow: 0 0 14px #fff078, 0 0 26px #ffd700, 0 0 36px #ffffff; }
            }

            @keyframes prigMatrixRain {
                0%, 100% { text-shadow: 0 0 4px #00ff66, 0 0 8px #00ff66; opacity: 0.95; }
                50% { text-shadow: 0 0 10px #00ffaa, 0 0 20px #00ffaa; opacity: 1; }
            }

            @keyframes prigVaporwave3D {
                0%, 100% { text-shadow: -1.5px -0.5px 0 #00ffff, 1.5px 0.5px 0 #ff007f; }
                50% { text-shadow: -2.5px -1px 0 #00ffff, 2.5px 1px 0 #ff007f; }
            }

            @keyframes prigEspejismoCalor {
                0%, 100% { text-shadow: 0 0 6px #ee964b, 0 0 12px #f4d35e; }
                50% { text-shadow: 0 0 12px #ee964b, 0 0 22px #f4d35e; }
            }

            @keyframes prigCristalPrisma {
                0%, 100% { text-shadow: -1.5px 0 6px #ff007f, 1.5px 0 6px #00ffff, 0 0 10px #ffffff; }
                50% { text-shadow: -2px 0 10px #00ff88, 2px 0 10px #ff0055, 0 0 16px #ffffff; }
            }

            @keyframes prigRadioactivoUranio {
                0%, 100% { text-shadow: 0 0 6px #76ff03, 0 0 14px #76ff03; }
                50% { text-shadow: 0 0 14px #ccff90, 0 0 28px #76ff03; }
            }

            @keyframes prigVorticeGravedad {
                0%, 100% { text-shadow: 0 0 8px #d000ff, 0 0 16px #7000ff; }
                50% { text-shadow: 0 0 16px #ff007f, 0 0 28px #7000ff; }
            }

            @keyframes prigDerretidoDali {
                0%, 100% { text-shadow: 0 1px 4px rgba(244, 211, 94, 0.7), 0 0 8px rgba(238, 150, 75, 0.6); }
                50% { text-shadow: 0 2px 8px rgba(244, 211, 94, 0.95), 0 0 16px rgba(238, 150, 75, 0.85); }
            }

            @keyframes prigNieblaEspectral {
                0%, 100% { text-shadow: 0 0 6px rgba(180, 200, 255, 0.7), 0 0 12px rgba(180, 200, 255, 0.5); opacity: 0.92; }
                50% { text-shadow: 0 0 12px rgba(180, 200, 255, 0.95), 0 0 22px rgba(180, 200, 255, 0.75); opacity: 1; }
            }

            @keyframes prigLineaActivaNeon {
                0%, 100% { box-shadow: inset 0 0 8px rgba(137, 180, 250, 0.15), inset 2px 0 0 var(--accent-blue) !important; }
                50% { box-shadow: inset 0 0 16px rgba(203, 166, 247, 0.35), inset 3px 0 0 var(--accent-purple) !important; }
            }
        `);

        // Helper para normalizar colores CSS (rgb/hex) a hex estándar
        // Generar reglas de efectos raros para cada token
        Object.entries(tokens).forEach(([tokenKey, cfg]) => {
            if (!cfg) return;
            const efecto = cfg.efectoRaro;
            const hex = '#' + this._toHex6(cfg.color, 'cba6f7');
            const isBold = (cfg.fontStyle || '').includes('bold');
            const isItalic = (cfg.fontStyle || '').includes('italic');
            const isUnderline = (cfg.fontStyle || '').includes('underline');
            const propEfecto = this._obtenerCssEfecto(efecto, hex);

            reglas.push(`
                .monaco-editor span.token-${tokenKey},
                .monaco-editor .token-${tokenKey},
                .prig-tok-${tokenKey} {
                    color: ${hex} !important;
                    ${isBold ? 'font-weight: bold !important;' : ''}
                    ${isItalic ? 'font-style: italic !important;' : ''}
                    ${isUnderline ? 'text-decoration: underline !important;' : ''}
                    ${propEfecto}
                }
            `);
        });

        // Efectos globales del editor:
        // 1. Líneas de escaneo CRT analógicas (sutil y sin tapar el texto)
        if (glob.lineasEscaneo) {
            reglas.push(`
                .monaco-editor::before {
                    content: " ";
                    position: absolute;
                    inset: 0;
                    background: linear-gradient(rgba(18, 16, 16, 0) 50%, rgba(0, 0, 0, 0.25) 50%);
                    background-size: 100% 4px;
                    z-index: 1;
                    pointer-events: none;
                    opacity: 0.35;
                }
            `);
        }

        // 2. Resplandor del cursor
        if (glob.resplandorCursor) {
            reglas.push(`
                .monaco-editor .cursor {
                    box-shadow: 0 0 10px var(--accent-blue), 0 0 18px var(--accent-purple) !important;
                }
            `);
        }

        // 3. Aberración cromática global en todo el texto
        if (glob.aberracionCromaticaGlobal) {
            reglas.push(`
                .monaco-editor .view-line {
                    text-shadow: -1px 0 rgba(255, 0, 85, 0.6), 1px 0 rgba(0, 240, 255, 0.6) !important;
                }
            `);
        }

        // 4. Viñeta analógica retro (suave en bordes, sin bloquear visibilidad)
        if (glob.vignetteRetro) {
            reglas.push(`
                .monaco-editor::after {
                    content: " ";
                    position: absolute;
                    inset: 0;
                    box-shadow: inset 0 0 50px rgba(0, 0, 0, 0.4);
                    z-index: 1;
                    pointer-events: none;
                    opacity: 0.5;
                }
            `);
        }

        // 5. Fondo vidrio ahumado líquido (Glassmorphism Monaco)
        if (glob.fondoVidrioLiquido) {
            reglas.push(`
                .monaco-editor {
                    backdrop-filter: blur(8px) !important;
                    -webkit-backdrop-filter: blur(8px) !important;
                }
            `);
        }

        // 6. Línea activa pulsante neón
        if (glob.lineaActivaPulsante) {
            reglas.push(`
                .monaco-editor .current-line {
                    animation: prigLineaActivaNeon 3s ease-in-out infinite !important;
                }
            `);
        }

        // 7. Selección galáctica de texto
        if (glob.seleccionGalactica) {
            reglas.push(`
                .monaco-editor .selected-text {
                    background: rgba(203, 166, 247, 0.35) !important;
                    box-shadow: 0 0 10px rgba(203, 166, 247, 0.6) !important;
                }
            `);
        }

        // Código CSS libre del usuario
        if (glob.codigoCss) {
            reglas.push(glob.codigoCss);
        }

        el.textContent = reglas.join('\n');
    }

    _toHex6(colorStr, fallback = 'cba6f7') {
        const fb = (fallback || 'cba6f7').replace('#', '').toLowerCase();
        if (!colorStr || typeof colorStr !== 'string') return fb;
        let c = colorStr.trim().toLowerCase();
        if (c.startsWith('#')) {
            const h = c.replace('#', '');
            if (h.length === 3) {
                return (h[0] + h[0] + h[1] + h[1] + h[2] + h[2]).toLowerCase();
            }
            if (h.length >= 6) {
                const h6 = h.substring(0, 6);
                if (/^[0-9a-f]{6}$/.test(h6)) return h6;
            }
        }
        const rgbMatch = c.match(/^rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)/);
        if (rgbMatch) {
            const r = Math.min(255, Math.max(0, parseInt(rgbMatch[1], 10))).toString(16).padStart(2, '0');
            const g = Math.min(255, Math.max(0, parseInt(rgbMatch[2], 10))).toString(16).padStart(2, '0');
            const b = Math.min(255, Math.max(0, parseInt(rgbMatch[3], 10))).toString(16).padStart(2, '0');
            return `${r}${g}${b}`;
        }
        return fb;
    }

    _aplicarTemaMonaco() {
        if (!window.monaco || !window.monaco.editor) return;

        const t = this.estado.tokens || {};
        const kwHex = this._toHex6(t.keyword && t.keyword.color, 'cba6f7');
        const kwStyle = (t.keyword && t.keyword.fontStyle) || '';

        const typeHex = this._toHex6(t.type && t.type.color, '89b4fa');
        const typeStyle = (t.type && t.type.fontStyle) || '';

        const fnHex = this._toHex6(t.function && t.function.color, '89dceb');
        const fnStyle = (t.function && t.function.fontStyle) || '';

        const strHex = this._toHex6(t.string && t.string.color, 'a6e3a1');
        const strStyle = (t.string && t.string.fontStyle) || '';

        const numHex = this._toHex6(t.number && t.number.color, 'fab387');
        const numStyle = (t.number && t.number.fontStyle) || '';

        const comHex = this._toHex6(t.comment && t.comment.color, '6c7086');
        const comStyle = (t.comment && t.comment.fontStyle) || 'italic';

        const opHex = this._toHex6(t.operator && t.operator.color, '89dceb');
        const opStyle = (t.operator && t.operator.fontStyle) || '';

        const varHex = this._toHex6(t.variable && t.variable.color, 'cdd6f4');
        const varStyle = (t.variable && t.variable.fontStyle) || '';

        const rules = [
            // Base default rule for unclassified tokens & default text
            { token: '', foreground: varHex, fontStyle: varStyle },

            // Keywords & Declarations across all languages
            { token: 'keyword', foreground: kwHex, fontStyle: kwStyle },
            { token: 'keyword.control', foreground: kwHex, fontStyle: kwStyle },
            { token: 'keyword.control.flow', foreground: kwHex, fontStyle: kwStyle },
            { token: 'keyword.control.from', foreground: kwHex, fontStyle: kwStyle },
            { token: 'keyword.control.import', foreground: kwHex, fontStyle: kwStyle },
            { token: 'keyword.flow', foreground: kwHex, fontStyle: kwStyle },
            { token: 'keyword.operator', foreground: opHex, fontStyle: opStyle },
            { token: 'keyword.operator.logical', foreground: opHex, fontStyle: opStyle },
            { token: 'keyword.operator.new', foreground: kwHex, fontStyle: kwStyle },
            { token: 'keyword.operator.expression', foreground: opHex, fontStyle: opStyle },
            { token: 'keyword.other', foreground: kwHex, fontStyle: kwStyle },
            { token: 'keyword.other.unit', foreground: kwHex, fontStyle: kwStyle },
            { token: 'keyword.declaration', foreground: kwHex, fontStyle: kwStyle },
            { token: 'keyword.async', foreground: kwHex, fontStyle: kwStyle },
            { token: 'keyword.python', foreground: kwHex, fontStyle: kwStyle },
            { token: 'keyword.js', foreground: kwHex, fontStyle: kwStyle },
            { token: 'keyword.ts', foreground: kwHex, fontStyle: kwStyle },
            { token: 'keyword.html', foreground: kwHex, fontStyle: kwStyle },
            { token: 'keyword.css', foreground: kwHex, fontStyle: kwStyle },
            { token: 'keyword.sql', foreground: kwHex, fontStyle: kwStyle },
            { token: 'storage', foreground: kwHex, fontStyle: kwStyle },
            { token: 'storage.type', foreground: typeHex, fontStyle: typeStyle },
            { token: 'storage.modifier', foreground: kwHex, fontStyle: kwStyle },

            // Types, Classes, Interfaces
            { token: 'type', foreground: typeHex, fontStyle: typeStyle },
            { token: 'type.identifier', foreground: typeHex, fontStyle: typeStyle },
            { token: 'entity.name.type', foreground: typeHex, fontStyle: typeStyle },
            { token: 'entity.name.class', foreground: typeHex, fontStyle: typeStyle },
            { token: 'entity.other.inherited-class', foreground: typeHex, fontStyle: typeStyle },
            { token: 'support.type', foreground: typeHex, fontStyle: typeStyle },
            { token: 'support.class', foreground: typeHex, fontStyle: typeStyle },

            // Functions & Methods
            { token: 'function', foreground: fnHex, fontStyle: fnStyle },
            { token: 'entity.name.function', foreground: fnHex, fontStyle: fnStyle },
            { token: 'support.function', foreground: fnHex, fontStyle: fnStyle },
            { token: 'meta.function-call', foreground: fnHex, fontStyle: fnStyle },

            // Strings & Escapes
            { token: 'string', foreground: strHex, fontStyle: strStyle },
            { token: 'string.escape', foreground: strHex, fontStyle: strStyle },
            { token: 'string.delim', foreground: strHex, fontStyle: strStyle },
            { token: 'string.regexp', foreground: strHex, fontStyle: strStyle },

            // Numbers, Booleans, Constants
            { token: 'number', foreground: numHex, fontStyle: numStyle },
            { token: 'number.float', foreground: numHex, fontStyle: numStyle },
            { token: 'number.hex', foreground: numHex, fontStyle: numStyle },
            { token: 'number.octal', foreground: numHex, fontStyle: numStyle },
            { token: 'number.binary', foreground: numHex, fontStyle: numStyle },
            { token: 'constant', foreground: numHex, fontStyle: numStyle },
            { token: 'constant.language', foreground: numHex, fontStyle: numStyle },
            { token: 'constant.numeric', foreground: numHex, fontStyle: numStyle },
            { token: 'constant.character', foreground: numHex, fontStyle: numStyle },

            // Comments
            { token: 'comment', foreground: comHex, fontStyle: comStyle },
            { token: 'comment.doc', foreground: comHex, fontStyle: comStyle },
            { token: 'comment.line', foreground: comHex, fontStyle: comStyle },
            { token: 'comment.block', foreground: comHex, fontStyle: comStyle },

            // Operators & Delimiters
            { token: 'operator', foreground: opHex, fontStyle: opStyle },
            { token: 'delimiter', foreground: opHex, fontStyle: opStyle },
            { token: 'delimiter.bracket', foreground: opHex, fontStyle: opStyle },
            { token: 'delimiter.parenthesis', foreground: opHex, fontStyle: opStyle },
            { token: 'delimiter.square', foreground: opHex, fontStyle: opStyle },
            { token: 'delimiter.curly', foreground: opHex, fontStyle: opStyle },

            // Variables & Identifiers
            { token: 'variable', foreground: varHex, fontStyle: varStyle },
            { token: 'variable.name', foreground: varHex, fontStyle: varStyle },
            { token: 'variable.parameter', foreground: varHex, fontStyle: varStyle },
            { token: 'variable.language', foreground: varHex, fontStyle: varStyle },
            { token: 'identifier', foreground: varHex, fontStyle: varStyle }
        ];

        this._temaVersion = (this._temaVersion || 0) + 1;
        const nombreTema = 'prig-custom-syntax-v' + this._temaVersion;

        try {
            window.monaco.editor.defineTheme(nombreTema, {
                base: 'vs-dark',
                inherit: true,
                rules: rules,
                colors: {
                    'editor.background': '#00000000',
                    'editorGutter.background': '#00000000',
                    'editor.foreground': '#' + varHex,
                    'editor.lineHighlightBackground': 'rgba(255,255,255,0.04)',
                    'editorLineNumber.foreground': '#585b70',
                    'editorLineNumber.activeForeground': '#' + varHex,
                    'editorIndentGuide.background': 'rgba(255,255,255,0.06)'
                }
            });

            window.monaco.editor.setTheme(nombreTema);
            try {
                localStorage.setItem('prig_editor_theme', nombreTema);
            } catch (e) {}

            // Forzar actualización inmediata en todos los paneles abiertos de Monaco
            if (window.editorMgr && Array.isArray(window.editorMgr.panes)) {
                window.editorMgr.panes.forEach(p => {
                    if (p && p.editor) {
                        try {
                            p.editor.updateOptions({ theme: nombreTema });
                        } catch (e) {}
                    }
                });
            }

            if (window.noteWindowMgr && window.noteWindowMgr.fullEditor) {
                try {
                    window.noteWindowMgr.fullEditor.updateOptions({ theme: nombreTema });
                } catch (e) {}
            }

            // Mantener estilos y transparencias de secciones en sincronía
            if (window.aparienciaMgr && typeof window.aparienciaMgr._aplicarEstilosDinamicos === 'function') {
                window.aparienciaMgr._aplicarEstilosDinamicos();
            }

            // Inyectar efectos visuales raros a las clases .mtk compiladas de Monaco con pases múltiples
            this._inyectarEfectosEnMonacoMtk();
            if (typeof requestAnimationFrame === 'function') {
                requestAnimationFrame(() => this._inyectarEfectosEnMonacoMtk());
            }
            setTimeout(() => this._inyectarEfectosEnMonacoMtk(), 40);
            setTimeout(() => this._inyectarEfectosEnMonacoMtk(), 150);
            setTimeout(() => this._inyectarEfectosEnMonacoMtk(), 350);
            setTimeout(() => this._inyectarEfectosEnMonacoMtk(), 700);
        } catch (e) {
            console.warn("No se pudo aplicar tema dinámico de Monaco:", e);
        }
    }

    _colorCssAHex(colorStr) {
        if (!colorStr || typeof colorStr !== 'string') return '';
        let c = colorStr.trim().toLowerCase();
        if (c.startsWith('#')) {
            if (c.length === 4) {
                return ('#' + c[1] + c[1] + c[2] + c[2] + c[3] + c[3]).toLowerCase();
            }
            return c.substring(0, 7).toLowerCase();
        }
        const rgbMatch = c.match(/^rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)/);
        if (rgbMatch) {
            const r = Math.min(255, Math.max(0, parseInt(rgbMatch[1], 10))).toString(16).padStart(2, '0');
            const g = Math.min(255, Math.max(0, parseInt(rgbMatch[2], 10))).toString(16).padStart(2, '0');
            const b = Math.min(255, Math.max(0, parseInt(rgbMatch[3], 10))).toString(16).padStart(2, '0');
            return `#${r}${g}${b}`.toLowerCase();
        }
        return c;
    }

    _obtenerCssEfecto(efecto, color) {
        if (!efecto || efecto === 'ninguno') return '';
        const col = color || 'currentColor';
        switch (efecto) {
            case 'resplandor_neon':
                return `text-shadow: 0 0 6px ${col}, 0 0 14px ${col}, 0 0 24px ${col} !important; font-weight: bold !important; animation: prigPulsoNeonTexto 2s ease-in-out infinite !important;`;
            case 'glitch_rgb':
                return `text-shadow: -2px 0 #ff0055, 2px 0 #00ffff, 0 0 10px ${col} !important; font-weight: bold !important; animation: prigGlitchTexto 1.8s steps(2, start) infinite !important;`;
            case 'arcoiris_animado':
                return `animation: prigArcoirisTexto 4s linear infinite !important; font-weight: bold !important;`;
            case 'subrayado_onda':
                return `text-decoration: underline wavy ${col} !important; text-underline-offset: 3.5px !important; text-shadow: 0 0 8px ${col} !important; animation: prigOndaSubrayado 4s ease infinite !important;`;
            case 'fuego_retro':
                return `text-shadow: 0 0 6px #ff4500, 0 -3px 12px #ffd700, 0 0 22px #ff0000 !important; font-weight: bold !important; animation: prigFuegoTexto 2s ease-in-out infinite !important;`;
            case 'fantasma_italica':
                return `font-style: italic !important; opacity: 0.95 !important; text-shadow: 0 0 8px ${col}, 0 0 16px ${col} !important;`;
            case 'plasma_pulsar_electrico':
                return `text-shadow: 0 0 8px #7000ff, 0 0 16px #00ffff, 0 0 28px #ff007f !important; font-weight: bold !important; animation: prigPlasmaPulsar 2.4s ease-in-out infinite !important;`;
            case 'oro_alquimico_brillo':
                return `text-shadow: 0 0 6px #ffd700, 0 0 16px #fff078, 0 0 26px #d4af37 !important; font-weight: bold !important; animation: prigOroBrillo 2.2s ease-in-out infinite !important;`;
            case 'matrix_digital_rain':
                return `text-shadow: 0 0 6px #00ff66, 0 0 14px #00ff66, 0 0 22px #00ffaa !important; animation: prigMatrixRain 1.6s steps(3, start) infinite !important;`;
            case 'vaporwave_3d_anaglyph':
                return `text-shadow: -2px -1px 0 #00ffff, 2px 1px 0 #ff007f, 0 0 10px #ff71ce !important; animation: prigVaporwave3D 3s ease-in-out infinite !important;`;
            case 'espejismo_calor_desierto':
                return `text-shadow: 0 0 6px #ee964b, 0 0 14px #f4d35e !important; animation: prigEspejismoCalor 3s ease-in-out infinite !important;`;
            case 'cristal_prismatico':
                return `text-shadow: -1.5px 0 6px #ff007f, 1.5px 0 6px #00ffff, 0 0 10px #ffffff !important; animation: prigCristalPrisma 4s ease-in-out infinite !important;`;
            case 'radioactivo_uranio':
                return `text-shadow: 0 0 8px #76ff03, 0 0 16px #76ff03, 0 0 28px #ccff90 !important; font-weight: bold !important; animation: prigRadioactivoUranio 2s ease-in-out infinite !important;`;
            case 'vortice_gravedad_negra':
                return `text-shadow: 0 0 8px #d000ff, 0 0 16px #7000ff, 0 0 24px #ff007f !important; font-weight: bold !important; animation: prigVorticeGravedad 3.5s ease-in-out infinite !important;`;
            case 'pixel_arcade_8bit':
                return `text-shadow: 1px 1px 0 rgba(0,0,0,0.6), 0 0 10px ${col} !important; font-weight: bold !important;`;
            case 'derretido_dali':
                return `text-shadow: 0 2px 6px rgba(244, 211, 94, 0.8), 0 0 14px rgba(238, 150, 75, 0.7) !important; animation: prigDerretidoDali 3.5s ease-in-out infinite !important;`;
            case 'niebla_espectral':
                return `text-shadow: 0 0 8px rgba(180, 200, 255, 0.85), 0 0 16px rgba(180, 200, 255, 0.65) !important; opacity: 0.95 !important; animation: prigNieblaEspectral 4s ease-in-out infinite !important;`;
            default:
                return '';
        }
    }

    _inyectarEfectosEnMonacoMtk() {
        let el = document.getElementById('prig-estilos-monaco-mtk');
        if (!el) {
            el = document.createElement('style');
            el.id = 'prig-estilos-monaco-mtk';
            document.head.appendChild(el);
        }

        const tokens = this.estado.tokens || {};
        const tokColorMap = {}; // hex -> Array of token info objects
        Object.entries(tokens).forEach(([tokKey, cfg]) => {
            if (!cfg) return;
            const hex = '#' + this._toHex6(cfg.color, 'cba6f7');
            if (!tokColorMap[hex]) tokColorMap[hex] = [];
            tokColorMap[hex].push({
                color: hex,
                fontStyle: cfg.fontStyle || '',
                efectoRaro: cfg.efectoRaro || 'ninguno',
                tokKey: tokKey
            });
        });

        const reglas = [];
        const mtkClassesFound = new Set();

        // 1. Escanear hojas de estilo generadas por Monaco en el DOM (IGNORANDO estilos propios de prig-*)
        try {
            const allSheets = [];
            document.querySelectorAll('head style, style').forEach(s => {
                if (s.id && s.id.startsWith('prig-')) return; // NUNCA escanear nuestras propias hojas de estilo
                try { if (s.sheet) allSheets.push(s.sheet); } catch(e) {}
            });
            Array.from(document.styleSheets || []).forEach(s => {
                try {
                    const owner = s.ownerNode;
                    if (owner && owner.id && owner.id.startsWith('prig-')) return;
                } catch(e) {}
                if (!allSheets.includes(s)) allSheets.push(s);
            });

            for (const sheet of allSheets) {
                let rules;
                try {
                    rules = sheet.cssRules || sheet.rules;
                } catch (e) {
                    continue;
                }
                if (!rules) continue;

                for (let i = 0; i < rules.length; i++) {
                    const rule = rules[i];
                    if (!rule.selectorText || !rule.style) continue;

                    if (rule.selectorText.includes('.mtk')) {
                        const ruleColorHex = '#' + this._toHex6(rule.style.color, '');
                        const candidates = tokColorMap[ruleColorHex];
                        if (candidates && candidates.length > 0) {
                            let tokInfo = candidates[0];
                            if (candidates.length > 1) {
                                const isRuleBold = (rule.style.fontWeight === 'bold' || parseInt(rule.style.fontWeight, 10) >= 700);
                                const isRuleItalic = (rule.style.fontStyle === 'italic');
                                const isRuleUnderline = (rule.style.textDecoration && rule.style.textDecoration.includes('underline'));
                                const exact = candidates.find(c => {
                                    const cBold = c.fontStyle.includes('bold');
                                    const cItalic = c.fontStyle.includes('italic');
                                    const cUnderline = c.fontStyle.includes('underline');
                                    return (cBold === isRuleBold && cItalic === isRuleItalic && cUnderline === isRuleUnderline);
                                });
                                tokInfo = exact || candidates.find(c => c.efectoRaro !== 'ninguno') || candidates[0];
                            }

                            const mtkMatches = rule.selectorText.match(/\.mtk\d+/g) || [];
                            for (const mtkCls of mtkMatches) {
                                if (mtkCls === '.mtk1' && tokInfo.tokKey !== 'variable') continue;
                                if (!mtkClassesFound.has(mtkCls)) {
                                    mtkClassesFound.add(mtkCls);
                                    const isBold = tokInfo.fontStyle.includes('bold');
                                    const isItalic = tokInfo.fontStyle.includes('italic');
                                    const isUnderline = tokInfo.fontStyle.includes('underline');
                                    const cssEfecto = this._obtenerCssEfecto(tokInfo.efectoRaro, tokInfo.color);
                                    
                                    reglas.push(`
                                        .monaco-editor span${mtkCls}, .monaco-editor ${mtkCls}, ${mtkCls} {
                                            color: ${tokInfo.color} !important;
                                            ${isBold ? 'font-weight: bold !important;' : ''}
                                            ${isItalic ? 'font-style: italic !important;' : ''}
                                            ${isUnderline ? 'text-decoration: underline !important;' : ''}
                                            ${cssEfecto}
                                        }
                                    `);
                                }
                            }
                        }
                    }
                }
            }
        } catch (e) {
            console.warn("Error mapeando reglas mtk de Monaco:", e);
        }

        // 2. Inspeccionar elementos span .mtk en vivo dentro del DOM de Monaco
        try {
            const domSpans = document.querySelectorAll('.monaco-editor .view-line span[class*="mtk"]');
            domSpans.forEach(span => {
                const classList = Array.from(span.classList || []);
                for (const cls of classList) {
                    if (cls.startsWith('mtk')) {
                        const mtkCls = '.' + cls;
                        if (!mtkClassesFound.has(mtkCls)) {
                            const compColor = window.getComputedStyle ? window.getComputedStyle(span).color : '';
                            const hex = '#' + this._toHex6(compColor, '');
                            const candidates = tokColorMap[hex];
                            if (candidates && candidates.length > 0) {
                                const tokInfo = candidates.find(c => c.efectoRaro !== 'ninguno') || candidates[0];
                                mtkClassesFound.add(mtkCls);
                                const isBold = tokInfo.fontStyle.includes('bold');
                                const isItalic = tokInfo.fontStyle.includes('italic');
                                const isUnderline = tokInfo.fontStyle.includes('underline');
                                const cssEfecto = this._obtenerCssEfecto(tokInfo.efectoRaro, tokInfo.color);
                                reglas.push(`
                                    .monaco-editor span${mtkCls}, .monaco-editor ${mtkCls}, ${mtkCls} {
                                        color: ${tokInfo.color} !important;
                                        ${isBold ? 'font-weight: bold !important;' : ''}
                                        ${isItalic ? 'font-style: italic !important;' : ''}
                                        ${isUnderline ? 'text-decoration: underline !important;' : ''}
                                        ${cssEfecto}
                                    }
                                `);
                            }
                        }
                    }
                }
            });
        } catch (e) {}

        // 3. Reglas directas para componentes y previews
        Object.entries(tokens).forEach(([tokKey, cfg]) => {
            if (!cfg) return;
            const hex = '#' + this._toHex6(cfg.color, 'cba6f7');
            const isBold = (cfg.fontStyle || '').includes('bold');
            const isItalic = (cfg.fontStyle || '').includes('italic');
            const isUnderline = (cfg.fontStyle || '').includes('underline');
            const cssEfecto = this._obtenerCssEfecto(cfg.efectoRaro, hex);
            reglas.push(`
                .monaco-editor span.token-${tokKey},
                .monaco-editor .token-${tokKey},
                .prig-tok-${tokKey} {
                    color: ${hex} !important;
                    ${isBold ? 'font-weight: bold !important;' : ''}
                    ${isItalic ? 'font-style: italic !important;' : ''}
                    ${isUnderline ? 'text-decoration: underline !important;' : ''}
                    ${cssEfecto}
                }
            `);
        });

        el.textContent = reglas.join('\n');
    }

    _iniciarObserver() {
        if (typeof MutationObserver === 'undefined') return;
        if (this._observer) return;

        let debounceTimer = null;
        this._observer = new MutationObserver((mutations) => {
            let hasViewLines = false;
            for (const m of mutations) {
                if (m.addedNodes && m.addedNodes.length > 0) {
                    for (const n of m.addedNodes) {
                        if (n.nodeType === 1 && (n.classList && (n.classList.contains('view-line') || n.classList.contains('view-lines')) || (n.querySelector && n.querySelector('.view-line')))) {
                            hasViewLines = true;
                            break;
                        }
                    }
                }
                if (hasViewLines) break;
            }

            if (hasViewLines) {
                if (debounceTimer) clearTimeout(debounceTimer);
                debounceTimer = setTimeout(() => {
                    this._inyectarEfectosEnMonacoMtk();
                }, 40);
            }
        });

        const observeTarget = () => {
            const elTarget = document.getElementById('seccion-trabajo') || document.body;
            if (elTarget && this._observer) {
                try {
                    this._observer.observe(elTarget, { childList: true, subtree: true });
                } catch(e) {}
            }
        };

        if (typeof document !== 'undefined') {
            if (document.readyState === 'loading') {
                document.addEventListener('DOMContentLoaded', observeTarget);
            } else {
                observeTarget();
            }
        }
    }

    setToken(tokenKey, prop, valor) {
        if (!this.estado.tokens[tokenKey]) this.estado.tokens[tokenKey] = {};
        this.estado.tokens[tokenKey][prop] = valor;
        this.estado.presetActivo = 'personalizado';
        this._guardar();
        this.aplicar();
    }

    setEfectoGlobal(clave, valor) {
        this.estado.efectosGlobales[clave] = valor;
        this._guardar();
        this.aplicar();
    }

    aplicarPreset(presetId) {
        const p = PRESETS_SINTAXIS_RARA[presetId];
        if (!p) return;
        this.estado.presetActivo = presetId;
        this.estado.tokens = JSON.parse(JSON.stringify(p.tokens));
        this.estado.efectosGlobales = JSON.parse(JSON.stringify(p.efectosGlobales || {}));
        this._guardar();
        this.aplicar();
    }

    restablecer() {
        this.estado = JSON.parse(JSON.stringify(this.def));
        this._guardar();
        this.aplicar();
    }

    exportarJSON() {
        return JSON.stringify({
            version: '2.5',
            tipo: 'prig_sintaxis_personalizada',
            presetActivo: this.estado.presetActivo,
            tokens: this.estado.tokens,
            efectosGlobales: this.estado.efectosGlobales
        }, null, 2);
    }

    importarJSON(jsonStr) {
        try {
            const data = JSON.parse(jsonStr);
            if (!data || typeof data !== 'object') throw new Error('Formato inválido');
            if (data.tokens) this.estado.tokens = { ...this.estado.tokens, ...data.tokens };
            if (data.efectosGlobales) this.estado.efectosGlobales = { ...this.estado.efectosGlobales, ...data.efectosGlobales };
            this.estado.presetActivo = data.presetActivo || 'personalizado';
            this._guardar();
            this.aplicar();
            return { exito: true };
        } catch (e) {
            return { exito: false, error: e.message };
        }
    }
}

// Instanciar singleton
window.PRESETS_SINTAXIS_RARA = PRESETS_SINTAXIS_RARA;
window.SintaxisManager = SintaxisManager;
window.sintaxisMgr = new SintaxisManager();

// Aplicar sintaxis de inmediato
document.addEventListener('DOMContentLoaded', () => {
    if (window.sintaxisMgr) window.sintaxisMgr.aplicar();
});
setTimeout(() => {
    if (window.sintaxisMgr) window.sintaxisMgr.aplicar();
}, 600);

