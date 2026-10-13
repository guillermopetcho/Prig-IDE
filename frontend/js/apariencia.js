/**
 * Apariencia y Personalización Visual Completa para Prig IDE.
 *
 * Características:
 * 1. Paleta de colores completa (fondo general, paneles, editor, bordes, textos y acentos).
 * 2. Temas predefinidos (Catppuccin Mocha, Midnight, Cyberpunk, Nord, Dracula, Monokai Pro, etc.).
 * 3. Fondos estáticos (Color sólido, Gradientes estáticos o Fotografía / Imagen personalizada).
 * 4. Fondos con Movimiento (Partículas, Lluvia Matrix, Campo de Estrellas, Aurora Boreal, Luces Neón).
 * 5. Motor de Código en Vivo: el usuario puede programar y ejecutar su propio código JS Canvas o CSS personalizado.
 * 6. Fondos por Sección (Barra Superior, Explorador, Editor, Chat IA, Terminal, Modales, Módulos):
 *    con color, fotografía, animaciones de movimiento o CSS individual.
 * 7. Respaldo (Importar/Exportar JSON) y persistencia en localStorage.
 */

const TEMAS_PREDEFINIDOS = {
    catppuccin_mocha: {
        nombre: 'Catppuccin Mocha (Predeterminado)',
        icono: 'fa-cat',
        colores: {
            bg_dark: '#1e1e2e',
            bg_panel: '#181825',
            bg_editor: '#11111b',
            bg_hover: '#313244',
            border_color: '#313244',
            text_main: '#cdd6f4',
            text_muted: '#a6adc8',
            accent_blue: '#89b4fa',
            accent_purple: '#cba6f7',
            accent_green: '#a6e3a1',
            accent_red: '#f38ba8',
            accent_yellow: '#f9e2af'
        }
    },
    midnight_dark: {
        nombre: 'Midnight Dark (Oscuro Profundo)',
        icono: 'fa-moon',
        colores: {
            bg_dark: '#0d1117',
            bg_panel: '#161b22',
            bg_editor: '#0d1117',
            bg_hover: '#21262d',
            border_color: '#30363d',
            text_main: '#c9d1d9',
            text_muted: '#8b949e',
            accent_blue: '#58a6ff',
            accent_purple: '#bc8cff',
            accent_green: '#3fb950',
            accent_red: '#ff7b72',
            accent_yellow: '#d29922'
        }
    },
    cyberpunk: {
        nombre: 'Cyberpunk Neon',
        icono: 'fa-bolt',
        colores: {
            bg_dark: '#0f051d',
            bg_panel: '#1a0933',
            bg_editor: '#0b0217',
            bg_hover: '#2a1152',
            border_color: '#ff007f55',
            text_main: '#00ffff',
            text_muted: '#a277ff',
            accent_blue: '#00f0ff',
            accent_purple: '#ff007f',
            accent_green: '#00ff66',
            accent_red: '#ff0055',
            accent_yellow: '#ffe600'
        }
    },
    nord: {
        nombre: 'Nord Frost',
        icono: 'fa-snowflake',
        colores: {
            bg_dark: '#2e3440',
            bg_panel: '#3b4252',
            bg_editor: '#242933',
            bg_hover: '#434c5e',
            border_color: '#4c566a',
            text_main: '#eceff4',
            text_muted: '#d8dee9',
            accent_blue: '#88c0d0',
            accent_purple: '#b48ead',
            accent_green: '#a3be8c',
            accent_red: '#bf616a',
            accent_yellow: '#ebcb8b'
        }
    },
    dracula: {
        nombre: 'Dracula Classic',
        icono: 'fa-vampire',
        colores: {
            bg_dark: '#282a36',
            bg_panel: '#21222c',
            bg_editor: '#191a21',
            bg_hover: '#44475a',
            border_color: '#6272a4',
            text_main: '#f8f8f2',
            text_muted: '#6272a4',
            accent_blue: '#8be9fd',
            accent_purple: '#bd93f9',
            accent_green: '#50fa7b',
            accent_red: '#ff5555',
            accent_yellow: '#f1fa8c'
        }
    },
    monokai_pro: {
        nombre: 'Monokai Pro',
        icono: 'fa-fire',
        colores: {
            bg_dark: '#2d2a2e',
            bg_panel: '#221f22',
            bg_editor: '#19181a',
            bg_hover: '#403e41',
            border_color: '#5b595c',
            text_main: '#fcfcfa',
            text_muted: '#939293',
            accent_blue: '#78dce8',
            accent_purple: '#ab9df2',
            accent_green: '#a9dc76',
            accent_red: '#ff6188',
            accent_yellow: '#ffd866'
        }
    },
    emerald_forest: {
        nombre: 'Emerald Forest',
        icono: 'fa-tree',
        colores: {
            bg_dark: '#0a1913',
            bg_panel: '#10261e',
            bg_editor: '#06100c',
            bg_hover: '#1b3d30',
            border_color: '#285946',
            text_main: '#d4ebd9',
            text_muted: '#7fa88c',
            accent_blue: '#48cae4',
            accent_purple: '#9d4edd',
            accent_green: '#52b788',
            accent_red: '#e76f51',
            accent_yellow: '#e9c46a'
        }
    },
    solarized_dark: {
        nombre: 'Solarized Dark',
        icono: 'fa-sun',
        colores: {
            bg_dark: '#002b36',
            bg_panel: '#073642',
            bg_editor: '#00212b',
            bg_hover: '#586e75',
            border_color: '#094959',
            text_main: '#93a1a1',
            text_muted: '#657b83',
            accent_blue: '#268bd2',
            accent_purple: '#6c71c4',
            accent_green: '#859900',
            accent_red: '#dc322f',
            accent_yellow: '#b58900'
        }
    },
    tokyo_night: {
        nombre: 'Tokyo Night',
        icono: 'fa-city',
        colores: {
            bg_dark: '#1a1b26',
            bg_panel: '#16161e',
            bg_editor: '#13141c',
            bg_hover: '#2f354b',
            border_color: '#3b4261',
            text_main: '#c0caf5',
            text_muted: '#7aa2f7',
            accent_blue: '#7aa2f7',
            accent_purple: '#bb9af7',
            accent_green: '#9ece6a',
            accent_red: '#f7768e',
            accent_yellow: '#e0af68'
        }
    },
    obsidian_gold: {
        nombre: 'Obsidian Gold',
        icono: 'fa-gem',
        colores: {
            bg_dark: '#141414',
            bg_panel: '#1c1c1c',
            bg_editor: '#0d0d0d',
            bg_hover: '#292929',
            border_color: '#3d382d',
            text_main: '#e6e6e6',
            text_muted: '#999487',
            accent_blue: '#64b5f6',
            accent_purple: '#ba68c8',
            accent_green: '#81c784',
            accent_red: '#e57373',
            accent_yellow: '#ffd54f'
        }
    },
    vaporwave_1999: {
        nombre: 'Vaporwave 1999 Glitch',
        icono: 'fa-tape',
        colores: {
            bg_dark: '#18092a',
            bg_panel: '#280c45',
            bg_editor: '#0f041a',
            bg_hover: '#40136e',
            border_color: '#ff71ce66',
            text_main: '#01cdfe',
            text_muted: '#b967ff',
            accent_blue: '#01cdfe',
            accent_purple: '#ff71ce',
            accent_green: '#05ffa1',
            accent_red: '#ff2a6d',
            accent_yellow: '#fffb96'
        }
    },
    psicodelia_fractal: {
        nombre: 'Psicodelia Cósmica Fractal',
        icono: 'fa-eye',
        colores: {
            bg_dark: '#120024',
            bg_panel: '#20003b',
            bg_editor: '#090014',
            bg_hover: '#3a026a',
            border_color: '#ff00ff88',
            text_main: '#00ffcc',
            text_muted: '#e056fd',
            accent_blue: '#00d2d3',
            accent_purple: '#ff007f',
            accent_green: '#10ac84',
            accent_red: '#ff4757',
            accent_yellow: '#ff9ff3'
        }
    },
    crt_ambar_retro: {
        nombre: 'Terminal Ámbar CRT 1978',
        icono: 'fa-tv',
        colores: {
            bg_dark: '#0e0b04',
            bg_panel: '#1a1408',
            bg_editor: '#050401',
            bg_hover: '#2e230e',
            border_color: '#ffb00055',
            text_main: '#ffb000',
            text_muted: '#c48600',
            accent_blue: '#ffd700',
            accent_purple: '#e69500',
            accent_green: '#ffcc00',
            accent_red: '#ff5500',
            accent_yellow: '#ffb000'
        }
    },
    surrealismo_dali: {
        nombre: 'Relojes Derretidos de Dalí',
        icono: 'fa-hourglass-half',
        colores: {
            bg_dark: '#211812',
            bg_panel: '#2e2118',
            bg_editor: '#150e09',
            bg_hover: '#453225',
            border_color: '#d4a37366',
            text_main: '#fefae0',
            text_muted: '#cca785',
            accent_blue: '#6096ba',
            accent_purple: '#a2708a',
            accent_green: '#8da9c4',
            accent_red: '#bc6c25',
            accent_yellow: '#dda15e'
        }
    },
    void_glitch_aberration: {
        nombre: 'Fallo de Realidad (Glitch RGB)',
        icono: 'fa-skull-crossbones',
        colores: {
            bg_dark: '#07070a',
            bg_panel: '#101017',
            bg_editor: '#000000',
            bg_hover: '#20202e',
            border_color: '#ff003366',
            text_main: '#00f7ff',
            text_muted: '#8080a0',
            accent_blue: '#00e5ff',
            accent_purple: '#bd00ff',
            accent_green: '#00ff66',
            accent_red: '#ff003c',
            accent_yellow: '#ffe600'
        }
    },
    hongo_bioluminiscente: {
        nombre: 'Micelio Alienígena Bioluminiscente',
        icono: 'fa-dna',
        colores: {
            bg_dark: '#031716',
            bg_panel: '#072422',
            bg_editor: '#010c0b',
            bg_hover: '#0e3a37',
            border_color: '#00ffc255',
            text_main: '#78ffd6',
            text_muted: '#4da892',
            accent_blue: '#00d4ff',
            accent_purple: '#a855f7',
            accent_green: '#00ffaa',
            accent_red: '#f43f5e',
            accent_yellow: '#eefc57'
        }
    },
    alquimia_oculta: {
        nombre: 'Grimorio Alquímico Oculto',
        icono: 'fa-ankh',
        colores: {
            bg_dark: '#1c1514',
            bg_panel: '#291d1c',
            bg_editor: '#120c0b',
            bg_hover: '#3d2b29',
            border_color: '#d4af3766',
            text_main: '#f5e6c8',
            text_muted: '#bfa588',
            accent_blue: '#5c80bc',
            accent_purple: '#8e44ad',
            accent_green: '#27ae60',
            accent_red: '#c0392b',
            accent_yellow: '#d4af37'
        }
    },
    bauhaus_abstracto: {
        nombre: 'Vanguardia Bauhaus Abstracta',
        icono: 'fa-shapes',
        colores: {
            bg_dark: '#1b1c1e',
            bg_panel: '#25272a',
            bg_editor: '#121314',
            bg_hover: '#383b40',
            border_color: '#e6394666',
            text_main: '#f1faee',
            text_muted: '#a8dadc',
            accent_blue: '#1d3557',
            accent_purple: '#457b9d',
            accent_green: '#2a9d8f',
            accent_red: '#e63946',
            accent_yellow: '#e9c46a'
        }
    },
    dreamcore_liminal: {
        nombre: 'Dreamcore & Weirdcore Liminal',
        icono: 'fa-cloud-moon',
        colores: {
            bg_dark: '#1d192b',
            bg_panel: '#28233c',
            bg_editor: '#13101c',
            bg_hover: '#3f375e',
            border_color: '#fbcfe866',
            text_main: '#fce7f3',
            text_muted: '#c4b5fd',
            accent_blue: '#93c5fd',
            accent_purple: '#f472b6',
            accent_green: '#86efac',
            accent_red: '#fda4af',
            accent_yellow: '#fef08a'
        }
    },
    lava_arcade_8bit: {
        nombre: '8-Bit Lava Arcade Retro',
        icono: 'fa-gamepad',
        colores: {
            bg_dark: '#26100c',
            bg_panel: '#3b1712',
            bg_editor: '#1a0b08',
            bg_hover: '#5c160c',
            border_color: '#ff450066',
            text_main: '#ffbe0b',
            text_muted: '#fb5607',
            accent_blue: '#3a86ff',
            accent_purple: '#8338ec',
            accent_green: '#06d6a0',
            accent_red: '#ff006e',
            accent_yellow: '#ffbe0b'
        }
    },
    singularidad_inversa: {
        nombre: 'Singularidad Cuántica Invertida',
        icono: 'fa-atom',
        colores: {
            bg_dark: '#0f1422',
            bg_panel: '#161c2e',
            bg_editor: '#111625',
            bg_hover: '#222b45',
            border_color: '#7000ff77',
            text_main: '#ffffff',
            text_muted: '#a0b3d6',
            accent_blue: '#00f0ff',
            accent_purple: '#7000ff',
            accent_green: '#00ffb3',
            accent_red: '#ff0055',
            accent_yellow: '#fff01f'
        }
    },
    hiperespacio_radiactivo: {
        nombre: 'Hiperespacio Radioactivo',
        icono: 'fa-radiation',
        colores: {
            bg_dark: '#121e0b',
            bg_panel: '#1b2d10',
            bg_editor: '#101a0a',
            bg_hover: '#284517',
            border_color: '#76ff0355',
            text_main: '#b2ff59',
            text_muted: '#76ff03',
            accent_blue: '#00e5ff',
            accent_purple: '#d500f9',
            accent_green: '#00e676',
            accent_red: '#ff1744',
            accent_yellow: '#ffff00'
        }
    }
};

const GRADIENTES_PREDEFINIDOS = [
    { id: 'deep_space', nombre: 'Deep Space', valor: 'linear-gradient(135deg, #0b0c10 0%, #1f2833 50%, #0b0c10 100%)' },
    { id: 'catppuccin_aurora', nombre: 'Catppuccin Velvet', valor: 'linear-gradient(135deg, #1e1e2e 0%, #313244 50%, #181825 100%)' },
    { id: 'sunset_horizon', nombre: 'Sunset Horizon', valor: 'linear-gradient(135deg, #1a0b2e 0%, #30124e 45%, #63194a 100%)' },
    { id: 'aurora_borealis', nombre: 'Aurora Borealis', valor: 'linear-gradient(135deg, #051e22 0%, #0b3c49 50%, #14596b 100%)' },
    { id: 'cyber_matrix', nombre: 'Cyber Matrix', valor: 'linear-gradient(135deg, #060b14 0%, #0f1d36 50%, #1c0a35 100%)' },
    { id: 'emerald_abyss', nombre: 'Emerald Abyss', valor: 'linear-gradient(135deg, #051610 0%, #0b3426 50%, #051610 100%)' },
    { id: 'obsidian_ember', nombre: 'Obsidian Ember', valor: 'linear-gradient(135deg, #171210 0%, #381f18 50%, #171210 100%)' },
    { id: 'minimal_slate', nombre: 'Slate Minimal', valor: 'linear-gradient(135deg, #0f172a 0%, #1e293b 50%, #0f172a 100%)' }
];

const EFECTOS_MOVIMIENTO_GLOBAL = [
    { id: 'particulas', nombre: 'Constelación Neuronal', icono: 'fa-circle-nodes', desc: 'Red neuronal interactiva de nodos conectados con física de repulsión al cursor' },
    { id: 'matrix', nombre: 'Lluvia Digital Matrix', icono: 'fa-terminal', desc: 'Caracteres digitales verdes y cian cayendo en cascada con estela cyberpunk' },
    { id: 'estrellas', nombre: 'Campo de Estrellas 3D', icono: 'fa-star', desc: 'Viaje espacial a velocidad hiperespacial con estrellas en profundidad 3D' },
    { id: 'aurora', nombre: 'Aurora Boreal Fluida', icono: 'fa-water', desc: 'Olas continuas de luz de colores etéreos fluyendo suavemente en el fondo' },
    { id: 'bokeh', nombre: 'Luces Neón Bokeh', icono: 'fa-lightbulb', desc: 'Orbes luminosos desenfocados pulsando suavemente y elevándose' },
    { id: 'ondas_liquidas', nombre: 'Olas Líquidas Neón', icono: 'fa-wave-square', desc: 'Líneas senoidales líquidas de interferencia con resplandor neón' },
    { id: 'malla_cyberpunk', nombre: 'Cuadrícula 3D Synthwave', icono: 'fa-border-all', desc: 'Malla tridimensional en perspectiva con horizonte ondulante estilo Synthwave' },
    { id: 'poligonos_cuanticos', nombre: 'Polígonos Cuánticos', icono: 'fa-shapes', desc: 'Formas geométricas translúcidas que rotan suavemente e interactúan' },
    { id: 'lluvia_neon', nombre: 'Lluvia Neón en Cristal', icono: 'fa-cloud-rain', desc: 'Gotas de lluvia luminosas cayendo a diferentes profundidades y velocidades' },
    { id: 'fuego_fatuo', nombre: 'Luciérnagas del Bosque', icono: 'fa-wand-magic', desc: 'Partículas orgánicas con parpadeo suave y movimiento Browniano natural' },
    { id: 'tunel_vortex', nombre: 'Vórtice Dimensional', icono: 'fa-compact-disc', desc: 'Anillos concéntricos giratorios que crean una sensación de túnel infinito' },
    { id: 'ondas_gradiente', nombre: 'Degradado Líquido Fluido', icono: 'fa-wand-magic-sparkles', desc: 'Transición continua de gradientes suaves con armonía de colores' },
    { id: 'atractor_lorentz', nombre: 'Atractor Caótico de Lorenz 3D', icono: 'fa-infinity', desc: 'Ecuaciones diferenciales no lineales trazando la mística mariposa del caos matemático en 3D' },
    { id: 'agujero_negro_interstellar', nombre: 'Agujero Negro Interstellar', icono: 'fa-circle-notch', desc: 'Disco de acreción gravitacional con curvatura del espaciotiempo e interacción orbital al cursor' },
    { id: 'red_micelio_fungico', nombre: 'Micelio Alienígena Bioluminiscente', icono: 'fa-dna', desc: 'Ramificación biológica de hifas fosforescentes con emisión de esporas de plasma' },
    { id: 'glitch_cyber_digital', nombre: 'Glitch Cuántico Cyberpunk', icono: 'fa-bug', desc: 'Bloques de datos fragmentados y aberración cuántica con decodificación en tiempo real' },
    { id: 'hipercubo_4d_tesseract', nombre: 'Hipercubo 4D Tesseract', icono: 'fa-cube', desc: 'Proyección matemática tridimensional de un teseracto de 4 dimensiones rotando en el hiperespacio' },
    { id: 'robot_matrix', nombre: 'Robot Matrix Artillero', icono: 'fa-robot', desc: 'Robot cibernético gigante de código Matrix que apunta y dispara caracteres donde escribes en el editor' },
    { id: 'ascii_monolito_cosmico', nombre: 'Monolito Cósmico ASCII', icono: 'fa-cubes-stacked', desc: 'Obelisco 3D en arte ASCII con sombreado de bloques dithered y anillos de runas giratorios' },
    { id: 'ascii_santuario_torii', nombre: 'Santuario Torii & Pagoda Zen', icono: 'fa-torii-gate', desc: 'Arquitectura tradicional japonesa en arte ASCII minimalista con caída suave de flores de cerezo' },
    { id: 'ascii_oni_cyberpunk', nombre: 'Guardián Oni Cyberpunk', icono: 'fa-mask', desc: 'Máscara cibernética Oni en arte ASCII venam con visor de barrido óptico y corrientes de datos' },
    { id: 'ascii_paisaje_zen', nombre: 'Olas Japonesas & Solsticio', icono: 'fa-water', desc: 'Olas matemáticas dithered estilo Ukiyo-e en arte ASCII minimalista con gran sol naciente' },
    { id: 'ascii_nave_interceptor', nombre: 'Caza Espacial Interceptor', icono: 'fa-jet-fighter', desc: 'Nave espacial geométrica retro en arte ASCII venam cruzando el hiperespacio con estelas de plasma' },
    { id: 'tema_mecha_patrol', nombre: 'Mecha Titan Defense [IA 7B]', icono: 'fa-robot', desc: 'Escuadrón Mecha Titán y Droides orbitales con física y diálogos traseros dirigidos por modelo LLM 7B' },
    { id: 'tema_cyber_netrunner', nombre: 'Netrunner 2077 [IA 7B]', icono: 'fa-user-secret', desc: 'Cyborg Skull y Caza furtivo en matriz de datos controlados autónomamente por IA 7B' },
    { id: 'tema_dragon_sanctuary', nombre: 'Santuario del Dragón [IA 7B]', icono: 'fa-dragon', desc: 'Dragón serpentino místico y carpas koi con vuelo libre e interacción poética por LLM' },
    { id: 'tema_deep_space', nombre: 'Odisea Interestelar [IA 7B]', icono: 'fa-satellite', desc: 'Crucero estelar y satélite orbital explorando el espacio profundo bajo la guía del modelo 7B' },
    { id: 'tema_dungeon_crawler', nombre: 'Catacumba Rúnica [IA 7B]', icono: 'fa-dungeon', desc: 'El Segador y espadas rúnicas en las profundidades de la fortaleza con narrativa oscura por IA' },
    { id: 'tema_wild_nature', nombre: 'Bosque Místico [IA 7B]', icono: 'fa-tree', desc: 'Lobo aullando, búho sabio y león majestuoso en diálogo armónico con el ritmo de tu código' },
    { id: 'tema_retro_arcade', nombre: 'Arcade 1989 [IA 7B]', icono: 'fa-gamepad', desc: 'Space Invaders y Pacman con IA retro competitiva y sintetizador chiptune reactivo' },
    { id: 'tema_quantum_void', nombre: 'Vacío Isométrico [IA 7B]', icono: 'fa-cube', desc: 'Poliedros isométricos cuánticos con transformaciones espaciales en 4D dirigidas por el modelo' }
];

const SECCIONES_IDE = [
    { id: 'topbar', nombre: 'Barra Superior de Menús', selector: '#prig-topbar', icono: 'fa-window-maximize', colorKey: 'bg_panel', defAlfa: 0.92 },
    { id: 'sidebar_left', nombre: 'Explorador y Barra Lateral Izq.', selector: '#sidebar-left, #vista-archivos', icono: 'fa-folder-tree', colorKey: 'bg_panel', defAlfa: 0.88 },
    { id: 'sidebar_right', nombre: 'Chat IA y Tutor Prig', selector: '#seccion-modelo', icono: 'fa-brain', colorKey: 'bg_panel', defAlfa: 0.88 },
    { id: 'editor', nombre: 'Editor de Código y Trabajo', selector: '#seccion-trabajo, #panel-trabajo-izq, #trabajo-split-contenedor, #trabajo-vistas, #vista-editor, #editor-grid-container, .editor-col, .editor-col-body, .monaco-container, .monaco-editor-pane, #notebook-view-container', icono: 'fa-code', colorKey: 'bg_editor', defAlfa: 0.90 },
    { id: 'terminal', nombre: 'Terminal y Panel Inferior', selector: '#bottom-panel, #terminal-container', icono: 'fa-terminal', colorKey: 'bg_panel', defAlfa: 0.88 },
    { id: 'chat_messages', nombre: 'Área de Mensajes del Chat', selector: '#ai-chat-messages', icono: 'fa-comments', colorKey: 'bg_panel', defAlfa: 0.85 },
    { id: 'modales', nombre: 'Ventanas y Modales Flotantes', selector: '.modal-content, .des-eval-dialog, .config-modal-content, .gcfg-modal-content', icono: 'fa-window-restore', colorKey: 'bg_panel', defAlfa: 0.95 },
    { id: 'desafios', nombre: 'Módulo de Desafíos y Hojas', selector: '#desafios-raiz, .des-lado, .des-hoja', icono: 'fa-chess-knight', colorKey: 'bg_dark', defAlfa: 0.90 },
    { id: 'biblioteca', nombre: 'Biblioteca de Libros y Hubs', selector: '.book-library-container, #youtube-hub-root', icono: 'fa-book', colorKey: 'bg_panel', defAlfa: 0.92 }
];

const EJEMPLOS_CODIGO_FONDO = {
    canvas_ondas: `// Ejemplo: Olas senoidales líquidas de colores
function render(ctx, width, height, time) {
    ctx.fillStyle = "rgba(10, 10, 20, 0.25)";
    ctx.fillRect(0, 0, width, height);

    const cols = ["#89b4fa", "#cba6f7", "#a6e3a1", "#f9e2af"];
    for (let i = 0; i < cols.length; i++) {
        ctx.beginPath();
        ctx.strokeStyle = cols[i];
        ctx.lineWidth = 2.5;
        ctx.shadowColor = cols[i];
        ctx.shadowBlur = 12;
        for (let x = 0; x < width; x += 8) {
            const y = height / 2 + Math.sin(x * 0.005 + time * 0.002 + i) * 60 + Math.cos(x * 0.003 - time * 0.001) * 30;
            if (x === 0) ctx.moveTo(x, y);
            else ctx.lineTo(x, y);
        }
        ctx.stroke();
    }
}`,
    canvas_red_neuronal: `// Ejemplo: Red neuronal interactiva de nodos conectados
const nodos = [];
for (let i = 0; i < 45; i++) {
    nodos.push({
        x: Math.random() * (canvas.width || 800),
        y: Math.random() * (canvas.height || 600),
        vx: (Math.random() - 0.5) * 0.8,
        vy: (Math.random() - 0.5) * 0.8,
        r: Math.random() * 3 + 2
    });
}

function render(ctx, width, height, time) {
    ctx.clearRect(0, 0, width, height);

    for (let i = 0; i < nodos.length; i++) {
        const n = nodos[i];
        n.x += n.vx;
        n.y += n.vy;
        if (n.x < 0 || n.x > width) n.vx *= -1;
        if (n.y < 0 || n.y > height) n.vy *= -1;

        ctx.fillStyle = "#89b4fa";
        ctx.shadowColor = "#89b4fa";
        ctx.shadowBlur = 8;
        ctx.beginPath();
        ctx.arc(n.x, n.y, n.r, 0, Math.PI * 2);
        ctx.fill();

        for (let j = i + 1; j < nodos.length; j++) {
            const m = nodos[j];
            const dist = Math.hypot(n.x - m.x, n.y - m.y);
            if (dist < 130) {
                ctx.strokeStyle = "rgba(203, 166, 247, " + (1 - dist / 130) * 0.4 + ")";
                ctx.lineWidth = 1;
                ctx.beginPath();
                ctx.moveTo(n.x, n.y);
                ctx.lineTo(m.x, m.y);
                ctx.stroke();
            }
        }
    }
}`,
    css_animado: `/* Ejemplo: Degradado animado fluido y bordes con resplandor neón */
body, #app-container {
    background: linear-gradient(-45deg, #0d0221, #0f0c29, #302b63, #24243e) !important;
    background-size: 400% 400% !important;
    animation: prigGradienteFluido 16s ease infinite !important;
}

@keyframes prigGradienteFluido {
    0% { background-position: 0% 50%; }
    50% { background-position: 100% 50%; }
    100% { background-position: 0% 50%; }
}

#prig-topbar {
    border-bottom: 1.5px solid rgba(137, 180, 250, 0.45) !important;
    box-shadow: 0 2px 14px rgba(137, 180, 250, 0.15) !important;
}`
};

class AparienciaManager {
    constructor() {
        this.def = {
            temaActivo: 'catppuccin_mocha',
            opacidad: 0.92,
            desenfoque: 10,
            acento: '#89b4fa',
            densidad: 'normal',
            colores: Object.assign({}, TEMAS_PREDEFINIDOS.catppuccin_mocha.colores),
            transparenciasSecciones: {
                topbar: 0.92,
                sidebar_left: 0.88,
                sidebar_right: 0.88,
                editor: 0.90,
                terminal: 0.88,
                chat_messages: 0.85,
                modales: 0.95,
                desafios: 0.90,
                biblioteca: 0.92
            },
            fondoGlobal: {
                tipo: 'defecto', // 'defecto' | 'color' | 'gradiente' | 'imagen' | 'movimiento' | 'codigo_js' | 'codigo_css'
                color: '#181825',
                gradiente: 'linear-gradient(135deg, #1e1e2e 0%, #11111b 100%)',
                imagenUrl: '',
                imagenAjuste: 'cover', // 'cover' | 'contain' | 'repeat' | 'center'
                opacidad: 0.85,
                blur: 0,
                overlayTint: '#000000',
                overlayAlfa: 0.35,
                efectoMovimiento: 'particulas', // 'particulas' | 'matrix' | 'estrellas' | 'aurora' | 'bokeh' | 'ondas_gradiente'
                codigoJs: EJEMPLOS_CODIGO_FONDO.canvas_red_neuronal,
                codigoCss: EJEMPLOS_CODIGO_FONDO.css_animado
            },
            secciones: {} // seccionId: { tipo, color, alfa, gradiente, imagenUrl, blur, bordeColor, sombra, movimiento, codigoCss }
        };

        this.estado = this._cargar();
        this._animFrameId = null;
        this._canvasData = null;
        this._guardarTimer = null;

        // Sincronizar con el backend de inmediato
        this.sincronizarBackend();
    }

    _cargar() {
        try {
            const raw = localStorage.getItem('prig_apariencia');
            if (!raw) return JSON.parse(JSON.stringify(this.def));
            const data = JSON.parse(raw);
            return {
                ...JSON.parse(JSON.stringify(this.def)),
                ...data,
                colores: { ...this.def.colores, ...(data.colores || {}) },
                fondoGlobal: { ...this.def.fondoGlobal, ...(data.fondoGlobal || {}) },
                secciones: { ...(data.secciones || {}) },
                transparenciasSecciones: { ...this.def.transparenciasSecciones, ...(data.transparenciasSecciones || {}) }
            };
        } catch (e) {
            return JSON.parse(JSON.stringify(this.def));
        }
    }

    async sincronizarBackend() {
        try {
            const res = await fetch('/api/config/apariencia');
            if (res.ok) {
                const data = await res.json();
                if (data && typeof data === 'object' && Object.keys(data).length > 0 && data.colores) {
                    this.estado = {
                        ...JSON.parse(JSON.stringify(this.def)),
                        ...data,
                        colores: { ...this.def.colores, ...(data.colores || {}) },
                        fondoGlobal: { ...this.def.fondoGlobal, ...(data.fondoGlobal || {}) },
                        secciones: { ...(data.secciones || {}) },
                        transparenciasSecciones: { ...this.def.transparenciasSecciones, ...(data.transparenciasSecciones || {}) }
                    };
                    try {
                        localStorage.setItem('prig_apariencia', JSON.stringify(this.estado));
                    } catch (e) {}
                    this.aplicar();
                } else if (!localStorage.getItem('prig_apariencia')) {
                    // Si el backend estaba vacío pero tenemos estado por defecto, guardarlo en backend
                    this._guardarBackendInmediato();
                }
            }
        } catch (e) {
            // Silencioso si no hay conexión al backend
        }
    }

    _guardarBackendInmediato() {
        try {
            fetch('/api/config/apariencia', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(this.estado)
            }).catch(() => {});
        } catch (e) {}
    }

    _guardar() {
        // 1. Guardar en localStorage para respuesta visual a 0ms
        try {
            localStorage.setItem('prig_apariencia', JSON.stringify(this.estado));
        } catch (e) {
            console.warn("No se pudo guardar la configuración de apariencia en localStorage:", e);
        }

        // 2. Guardar en backend (disco persistente) con debounce para optimizar rendimiento
        if (this._guardarTimer) clearTimeout(this._guardarTimer);
        this._guardarTimer = setTimeout(() => {
            this._guardarBackendInmediato();
        }, 200);
    }

    aplicar() {
        const r = document.documentElement.style;
        const c = this.estado.colores;

        // 1. Inyectar variables de color a :root
        r.setProperty('--bg-dark', c.bg_dark || '#1e1e2e');
        r.setProperty('--bg-panel', c.bg_panel || '#181825');
        r.setProperty('--bg-editor', c.bg_editor || '#11111b');
        r.setProperty('--bg-hover', c.bg_hover || '#313244');
        r.setProperty('--border-color', c.border_color || '#313244');
        r.setProperty('--text-main', c.text_main || '#cdd6f4');
        r.setProperty('--text-muted', c.text_muted || '#a6adc8');
        r.setProperty('--accent-blue', c.accent_blue || '#89b4fa');
        r.setProperty('--accent-purple', c.accent_purple || '#cba6f7');
        r.setProperty('--accent-green', c.accent_green || '#a6e3a1');
        r.setProperty('--accent-red', c.accent_red || '#f38ba8');
        r.setProperty('--accent-yellow', c.accent_yellow || '#f9e2af');

        r.setProperty('--superficie-alfa', String(this.estado.opacidad));
        r.setProperty('--desenfoque', `${this.estado.desenfoque}px`);
        r.setProperty('--acento-usuario', this.estado.acento || c.accent_blue);
        document.body.dataset.densidad = this.estado.densidad || 'normal';
        document.body.classList.toggle('alta-transparencia', this.estado.opacidad < 0.75);

        // 2. Generar y aplicar estilos dinámicos de fondos estáticos, movimiento y secciones
        this._aplicarEstilosDinamicos();

        // 3. Iniciar o detener el motor de Canvas de Fondo
        this._sincronizarMotorCanvas();

        // 4. Re-sincronizar los efectos de sintaxis personalizada para que Monaco no pierda estilos ni brillos
        if (window.sintaxisMgr && typeof window.sintaxisMgr._inyectarEfectosEnMonacoMtk === 'function') {
            window.sintaxisMgr._inyectarEfectosEnMonacoMtk();
        }

        // 5. Re-sincronizar estilos de luz del motor audio reactivo
        if (window.audioReactivoMgr && typeof window.audioReactivoMgr._actualizarEstilosCss === 'function') {
            window.audioReactivoMgr._actualizarEstilosCss();
        }
    }

    _hexToRgba(hex, alpha = 1) {
        if (!hex || typeof hex !== 'string') return `rgba(30, 30, 46, ${alpha})`;
        let c = hex.replace('#', '');
        if (c.length === 3) c = c.split('').map(x => x + x).join('');
        const num = parseInt(c, 16);
        if (isNaN(num)) return hex;
        const r = (num >> 16) & 255;
        const g = (num >> 8) & 255;
        const b = num & 255;
        return `rgba(${r}, ${g}, ${b}, ${alpha})`;
    }

    _aplicarEstilosDinamicos() {
        let el = document.getElementById('prig-estilos-personalizados');
        if (!el) {
            el = document.createElement('style');
            el.id = 'prig-estilos-personalizados';
            document.head.appendChild(el);
        }

        const fg = this.estado.fondoGlobal || {};
        let cssReglas = [];

        // Keyframes comunes de animaciones de movimiento
        cssReglas.push(`
            @keyframes prigOndasGradiente {
                0% { background-position: 0% 50%; }
                50% { background-position: 100% 50%; }
                100% { background-position: 0% 50%; }
            }
            @keyframes prigPulsoNeon {
                0%, 100% { box-shadow: 0 0 8px rgba(137,180,250,0.2); border-color: rgba(137,180,250,0.3); }
                50% { box-shadow: 0 0 20px rgba(203,166,247,0.45); border-color: rgba(203,166,247,0.6); }
            }
            @keyframes prigDestelloBorde {
                0% { border-color: var(--accent-blue); }
                33% { border-color: var(--accent-purple); }
                66% { border-color: var(--accent-green); }
                100% { border-color: var(--accent-blue); }
            }
            @keyframes prigDegradadoSeccion {
                0% { background-position: 0% 0%; }
                50% { background-position: 100% 100%; }
                100% { background-position: 0% 0%; }
            }
        `);

        // Fondo global del programa
        if (fg.tipo === 'color' && fg.color) {
            cssReglas.push(`
                body, #app-container {
                    background-color: ${fg.color} !important;
                    background-image: none !important;
                }
            `);
        } else if (fg.tipo === 'gradiente' && fg.gradiente) {
            cssReglas.push(`
                body, #app-container {
                    background-image: ${fg.gradiente} !important;
                    background-attachment: fixed !important;
                }
            `);
        } else if (fg.tipo === 'imagen' && fg.imagenUrl) {
            const ajuste = fg.imagenAjuste || 'cover';
            const rep = ajuste === 'repeat' ? 'repeat' : 'no-repeat';
            const size = ajuste === 'repeat' ? 'auto' : (ajuste === 'center' ? 'auto' : ajuste);
            const tint = fg.overlayTint || '#000000';
            const tintAlfa = fg.overlayAlfa !== undefined ? fg.overlayAlfa : 0.35;
            const tintRgba = this._hexToRgba(tint, tintAlfa);

            cssReglas.push(`
                body, #app-container {
                    background-image: linear-gradient(${tintRgba}, ${tintRgba}), url("${fg.imagenUrl}") !important;
                    background-size: ${size} !important;
                    background-repeat: ${rep} !important;
                    background-position: center center !important;
                    background-attachment: fixed !important;
                }
            `);
        } else if (fg.tipo === 'movimiento' && fg.efectoMovimiento === 'ondas_gradiente') {
            cssReglas.push(`
                body, #app-container {
                    background: linear-gradient(-45deg, #18052e, #1e1e2e, #14596b, #060b14) !important;
                    background-size: 400% 400% !important;
                    animation: prigOndasGradiente 14s ease infinite !important;
                }
            `);
        } else if (fg.tipo === 'codigo_css' && fg.codigoCss) {
            cssReglas.push(fg.codigoCss);
        }

        // Fondos y transparencias por sección
        const c = this.estado.colores || {};
        const secciones = this.estado.secciones || {};
        const transSec = this.estado.transparenciasSecciones || {};
        const globalAlfa = this.estado.opacidad !== undefined ? this.estado.opacidad : 0.92;
        const globalBlur = this.estado.desenfoque !== undefined ? this.estado.desenfoque : 10;

        SECCIONES_IDE.forEach(secDef => {
            const secCfg = secciones[secDef.id] || {};

            // Determinar alfa de esta sección
            let alfa = globalAlfa;
            if (secCfg.alfa !== undefined) {
                alfa = secCfg.alfa;
            } else if (transSec[secDef.id] !== undefined) {
                alfa = transSec[secDef.id];
            } else if (secDef.defAlfa !== undefined) {
                alfa = secDef.defAlfa;
            }

            let propFondo = '';
            let propFiltro = '';
            let propBorde = '';
            let propSombra = '';
            let propAnim = '';

            const blurVal = secCfg.blur !== undefined ? secCfg.blur : globalBlur;
            if (blurVal > 0) {
                propFiltro = `backdrop-filter: blur(${blurVal}px) !important; -webkit-backdrop-filter: blur(${blurVal}px) !important;`;
            }

            if (secCfg.tipo === 'color' && secCfg.color) {
                const rgba = this._hexToRgba(secCfg.color, alfa);
                propFondo = `background: ${rgba} !important;`;
            } else if (secCfg.tipo === 'gradiente' && secCfg.gradiente) {
                propFondo = `background: ${secCfg.gradiente} !important;`;
            } else if (secCfg.tipo === 'imagen' && secCfg.imagenUrl) {
                const imgAjuste = secCfg.imagenAjuste || 'cover';
                const rep = imgAjuste === 'repeat' ? 'repeat' : 'no-repeat';
                const size = imgAjuste === 'repeat' ? 'auto' : imgAjuste;
                propFondo = `background-image: url("${secCfg.imagenUrl}") !important; background-size: ${size} !important; background-repeat: ${rep} !important; background-position: center !important;`;
            } else if (secCfg.tipo === 'movimiento') {
                if (secCfg.movimiento === 'pulso_neon') {
                    propAnim = `animation: prigPulsoNeon 4s ease-in-out infinite !important;`;
                } else if (secCfg.movimiento === 'destello_borde') {
                    propAnim = `animation: prigDestelloBorde 6s linear infinite !important;`;
                } else if (secCfg.movimiento === 'degradado_fluido') {
                    propFondo = `background: linear-gradient(135deg, rgba(30,30,46,0.9), rgba(49,50,68,0.9), rgba(24,24,37,0.9)) !important; background-size: 200% 200% !important;`;
                    propAnim = `animation: prigDegradadoSeccion 8s ease infinite !important;`;
                }
            } else if (secCfg.tipo === 'codigo' && secCfg.codigoCss) {
                cssReglas.push(`
                    ${secDef.selector} {
                        ${secCfg.codigoCss}
                    }
                `);
            } else {
                // Modo estándar / heredar: aplicar color base del tema con la transparencia individual de la sección
                const baseHex = (c && c[secDef.colorKey]) || (c && c.bg_panel) || '#181825';
                const rgba = this._hexToRgba(baseHex, alfa);
                propFondo = `background: ${rgba} !important;`;
            }

            if (secCfg.bordeColor) {
                propBorde = `border-color: ${secCfg.bordeColor} !important;`;
            }

            if (secCfg.sombra) {
                propSombra = `box-shadow: ${secCfg.sombra} !important;`;
            }

            if (propFondo || propFiltro || propBorde || propSombra || propAnim) {
                cssReglas.push(`
                    ${secDef.selector} {
                        ${propFondo}
                        ${propFiltro}
                        ${propBorde}
                        ${propSombra}
                        ${propAnim}
                    }
                `);
            }
        });

        // Garantizar que los contenedores internos de Monaco no acumulen capas oscuras adicionales
        cssReglas.push(`
            .monaco-editor, .monaco-editor-background, .monaco-container, .editor-col-body, .editor-col, #editor-cols-container, .monaco-editor .margin, .monaco-editor .overflow-guard, .monaco-editor-pane, .trabajo-vistas, .panel-trabajo, .trabajo-split-contenedor, #notebook-view-container {
                background: transparent !important;
            }
        `);

        el.textContent = cssReglas.join('\n');
    }

    // ==========================================
    // MOTOR DE ANIMACIÓN CANVAS DE FONDO
    // ==========================================

    _sincronizarMotorCanvas() {
        const fg = this.estado.fondoGlobal || {};
        const requiereCanvas = (fg.tipo === 'movimiento' && fg.efectoMovimiento !== 'ondas_gradiente') || fg.tipo === 'codigo_js';

        if (!window.motorMovimiento) return;

        if (!requiereCanvas) {
            window.motorMovimiento.detener();
            return;
        }

        if (fg.tipo === 'codigo_js') {
            window.motorMovimiento.ejecutarCodigoUsuario(fg.codigoJs || EJEMPLOS_CODIGO_FONDO.canvas_red_neuronal);
        } else {
            window.motorMovimiento.activarEfecto(fg.efectoMovimiento || 'particulas');
        }
    }

    setTema(nombreTema) {
        const tema = TEMAS_PREDEFINIDOS[nombreTema];
        if (!tema) return;
        this.estado.temaActivo = nombreTema;
        this.estado.colores = Object.assign({}, tema.colores);
        this.estado.acento = tema.colores.accent_blue;
        
        // Si el fondo global actual es por defecto o un color sólido, sincronizarlo con el nuevo fondo oscuro del tema
        if (this.estado.fondoGlobal) {
            if (this.estado.fondoGlobal.tipo === 'color' || this.estado.fondoGlobal.tipo === 'defecto') {
                this.estado.fondoGlobal.color = tema.colores.bg_dark;
            }
        }
        
        this._guardar();
        this.aplicar();
    }

    setColor(variable, valorHex) {
        if (!this.estado.colores) this.estado.colores = {};
        this.estado.colores[variable] = valorHex;
        if (variable === 'accent_blue') this.estado.acento = valorHex;
        if (variable === 'bg_dark' && this.estado.fondoGlobal && (this.estado.fondoGlobal.tipo === 'color' || this.estado.fondoGlobal.tipo === 'defecto')) {
            this.estado.fondoGlobal.color = valorHex;
        }
        this.estado.temaActivo = 'personalizado';
        this._guardar();
        this.aplicar();
    }

    setTransparenciaSeccion(seccionId, alfa) {
        alfa = Math.max(0, Math.min(1, parseFloat(alfa)));
        if (!this.estado.transparenciasSecciones) this.estado.transparenciasSecciones = {};
        this.estado.transparenciasSecciones[seccionId] = alfa;
        if (!this.estado.secciones) this.estado.secciones = {};
        if (!this.estado.secciones[seccionId]) {
            this.estado.secciones[seccionId] = { tipo: 'heredar', alfa: alfa };
        } else {
            this.estado.secciones[seccionId].alfa = alfa;
        }
        this._guardar();
        this.aplicar();
    }

    setTransparenciaGlobal(alfa) {
        alfa = Math.max(0.05, Math.min(1, parseFloat(alfa)));
        this.estado.opacidad = alfa;
        this._guardar();
        this.aplicar();
    }

    setDesenfoqueGlobal(blurPx) {
        blurPx = Math.max(0, Math.min(40, parseInt(blurPx, 10)));
        this.estado.desenfoque = blurPx;
        this._guardar();
        this.aplicar();
    }

    aplicarPresetTransparencia(preset) {
        let nivel = 0.92;
        let blur = 10;
        if (preset === 'solido') { nivel = 1.0; blur = 0; }
        else if (preset === 'vidrio_suave') { nivel = 0.88; blur = 12; }
        else if (preset === 'cristal') { nivel = 0.60; blur = 16; }
        else if (preset === 'ultra_transparente') { nivel = 0.35; blur = 20; }
        else if (preset === 'ghost') { nivel = 0.15; blur = 8; }

        this.estado.opacidad = nivel;
        this.estado.desenfoque = blur;
        if (!this.estado.transparenciasSecciones) this.estado.transparenciasSecciones = {};
        SECCIONES_IDE.forEach(s => {
            this.estado.transparenciasSecciones[s.id] = nivel;
            if (this.estado.secciones && this.estado.secciones[s.id]) {
                this.estado.secciones[s.id].alfa = nivel;
            }
        });
        this._guardar();
        this.aplicar();
    }

    setFondoGlobal(propiedad, valor) {
        if (!this.estado.fondoGlobal) this.estado.fondoGlobal = JSON.parse(JSON.stringify(this.def.fondoGlobal));
        this.estado.fondoGlobal[propiedad] = valor;
        this._guardar();
        this.aplicar();
    }

    setSeccion(seccionId, propiedad, valor) {
        if (!this.estado.secciones) this.estado.secciones = {};
        if (!this.estado.secciones[seccionId]) {
            this.estado.secciones[seccionId] = { tipo: 'heredar', color: '#181825', alfa: 0.9, blur: 0 };
        }
        this.estado.secciones[seccionId][propiedad] = valor;
        if (propiedad === 'alfa') {
            if (!this.estado.transparenciasSecciones) this.estado.transparenciasSecciones = {};
            this.estado.transparenciasSecciones[seccionId] = valor;
        }
        this._guardar();
        this.aplicar();
    }

    restablecerSeccion(seccionId) {
        if (this.estado.secciones && this.estado.secciones[seccionId]) {
            delete this.estado.secciones[seccionId];
        }
        if (this.estado.transparenciasSecciones && this.estado.transparenciasSecciones[seccionId] !== undefined) {
            const secDef = SECCIONES_IDE.find(s => s.id === seccionId);
            this.estado.transparenciasSecciones[seccionId] = secDef ? secDef.defAlfa : this.estado.opacidad;
        }
        this._guardar();
        this.aplicar();
    }

    set(clave, valor) {
        this.estado[clave] = valor;
        this._guardar();
        this.aplicar();
    }

    ajustarOpacidad(delta) {
        const v = Math.max(0.15, Math.min(1, +(this.estado.opacidad + delta).toFixed(2)));
        this.set('opacidad', v);
        if (window.layoutMgr) {
            window.layoutMgr.mensajeEstado(`Opacidad de la interfaz: ${Math.round(v * 100)}%`, 1500);
        }
        const rango = document.getElementById('ap-opacidad');
        if (rango) rango.value = String(v);
        const etiqueta = document.getElementById('ap-opacidad-valor');
        if (etiqueta) etiqueta.textContent = `${Math.round(v * 100)}%`;
    }

    exportarTema() {
        return JSON.stringify({
            version: '2.6',
            creado: new Date().toISOString(),
            temaActivo: this.estado.temaActivo,
            colores: this.estado.colores,
            fondoGlobal: this.estado.fondoGlobal,
            secciones: this.estado.secciones,
            transparenciasSecciones: this.estado.transparenciasSecciones,
            opacidad: this.estado.opacidad,
            desenfoque: this.estado.desenfoque,
            acento: this.estado.acento,
            densidad: this.estado.densidad
        }, null, 2);
    }

    importarTema(jsonStr) {
        try {
            const data = typeof jsonStr === 'string' ? JSON.parse(jsonStr) : jsonStr;
            if (!data || typeof data !== 'object') throw new Error('Formato de tema inválido.');
            
            // Reemplazo limpio y completo fusionando con los valores por defecto
            this.estado.colores = { ...this.def.colores, ...(data.colores || {}) };
            this.estado.fondoGlobal = { ...this.def.fondoGlobal, ...(data.fondoGlobal || {}) };
            this.estado.secciones = { ...(data.secciones || {}) };
            this.estado.transparenciasSecciones = { ...this.def.transparenciasSecciones, ...(data.transparenciasSecciones || {}) };
            this.estado.opacidad = data.opacidad !== undefined ? data.opacidad : this.def.opacidad;
            this.estado.desenfoque = data.desenfoque !== undefined ? data.desenfoque : this.def.desenfoque;
            this.estado.acento = data.acento || this.estado.colores.accent_blue || this.def.acento;
            this.estado.densidad = data.densidad || this.def.densidad;
            this.estado.temaActivo = data.temaActivo || 'personalizado';
            
            this._guardar();
            this.aplicar();
            return { exito: true };
        } catch (e) {
            return { exito: false, error: e.message };
        }
    }

    restablecerTodo() {
        this.estado = JSON.parse(JSON.stringify(this.def));
        this._guardar();
        this.aplicar();
    }
}

window.TEMAS_PREDEFINIDOS = TEMAS_PREDEFINIDOS;
window.GRADIENTES_PREDEFINIDOS = GRADIENTES_PREDEFINIDOS;
window.EFECTOS_MOVIMIENTO_GLOBAL = EFECTOS_MOVIMIENTO_GLOBAL;
window.SECCIONES_IDE = SECCIONES_IDE;
window.EJEMPLOS_CODIGO_FONDO = EJEMPLOS_CODIGO_FONDO;

window.aparienciaMgr = new AparienciaManager();
// Se aplica de inmediato al cargar el script para evitar parpadeos visuales
window.aparienciaMgr.aplicar();
