/**
 * Gestor de Perfiles de Configuración para Prig IDE.
 * 
 * Permite al usuario:
 * 1. Guardar y alternar entre múltiples perfiles completos (Colores, Fondos, Motor de Movimiento,
 *    densidad, transparencias y preferencias).
 * 2. Crear nuevos perfiles personalizados a partir del estado actual del entorno.
 * 3. Duplicar, renombrar, exportar e importar perfiles en formato JSON.
 * 4. Sincronización bidireccional automática: guardado local en localStorage y persistencia en backend (.prig_dataset).
 */

class PerfilesConfigManager {
    constructor() {
        this.perfiles = [];
        this.perfilActivoId = 'catppuccin_equilibrado';
        this._iniciado = false;
    }

    async init() {
        if (this._iniciado) return;
        this._iniciado = true;

        // 1. Cargar desde localStorage primero para arranque instantáneo
        this._cargarLocal();

        // 2. Sincronizar en segundo plano con el backend
        await this._sincronizarBackend();
    }

    _cargarLocal() {
        try {
            const raw = localStorage.getItem('prig_perfiles_config');
            if (raw) {
                const datos = JSON.parse(raw);
                if (datos && Array.isArray(datos.perfiles) && datos.perfiles.length > 0) {
                    this.perfiles = datos.perfiles;
                    this.perfilActivoId = datos.perfil_activo || this.perfiles[0].id;
                    return;
                }
            }
        } catch (e) {
            console.warn("Error leyendo perfiles locales:", e);
        }

        // Si no había en localStorage, usar presets iniciales
        this._cargarPresetsPorDefecto();
    }

    _cargarPresetsPorDefecto() {
        this.perfiles = [
            {
                id: 'catppuccin_equilibrado',
                nombre: 'Catppuccin Mocha Equilibrado',
                icono: 'fa-cat',
                desc: 'Tema pastel suave con constelación neuronal a 60 FPS. Máximo confort visual diario.',
                esPreset: true,
                apariencia: {
                    temaActivo: 'catppuccin_mocha',
                    opacidad: 0.92,
                    desenfoque: 10,
                    acento: '#89b4fa',
                    densidad: 'normal',
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
                    },
                    fondoGlobal: {
                        tipo: 'movimiento',
                        color: '#181825',
                        efectoMovimiento: 'particulas',
                        overlayAlfa: 0.35
                    },
                    secciones: {}
                },
                motorMovimiento: {
                    efecto: 'particulas',
                    fpsLimite: 60,
                    escalaRender: 0.75,
                    densidad: 'media',
                    velocidad: 1.0,
                    interaccionMouse: true,
                    pausarEnSegundoPlano: true
                }
            },
            {
                id: 'cyberpunk_neon',
                nombre: 'Cyberpunk Neón Extremo',
                icono: 'fa-bolt',
                desc: 'Estilo futurista de alto contraste con lluvia digital Matrix y resplandor cian/magenta.',
                esPreset: true,
                apariencia: {
                    temaActivo: 'cyberpunk',
                    opacidad: 0.88,
                    desenfoque: 12,
                    acento: '#00f0ff',
                    densidad: 'normal',
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
                    },
                    fondoGlobal: {
                        tipo: 'movimiento',
                        color: '#0f051d',
                        efectoMovimiento: 'matrix',
                        overlayAlfa: 0.25
                    },
                    secciones: {}
                },
                motorMovimiento: {
                    efecto: 'matrix',
                    fpsLimite: 60,
                    escalaRender: 0.75,
                    densidad: 'alta',
                    velocidad: 1.2,
                    interaccionMouse: true,
                    pausarEnSegundoPlano: true
                }
            },
            {
                id: 'midnight_ahorro',
                nombre: 'Midnight Oscuro (Modo Batería)',
                icono: 'fa-moon',
                desc: 'Fondo estático oscuro profundo (#0d1117) con motor en pausa. 0% consumo de GPU.',
                esPreset: true,
                apariencia: {
                    temaActivo: 'midnight_dark',
                    opacidad: 1.0,
                    desenfoque: 0,
                    acento: '#58a6ff',
                    densidad: 'compacta',
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
                    },
                    fondoGlobal: {
                        tipo: 'color',
                        color: '#0d1117'
                    },
                    secciones: {}
                },
                motorMovimiento: {
                    efecto: 'particulas',
                    fpsLimite: 30,
                    escalaRender: 0.5,
                    densidad: 'baja',
                    velocidad: 0.8,
                    interaccionMouse: false,
                    pausarEnSegundoPlano: true
                }
            },
            {
                id: 'nord_frost',
                nombre: 'Nord Frost Minimalista',
                icono: 'fa-snowflake',
                desc: 'Gama ártica fría y elegante con aurora boreal fluida suave de fondo.',
                esPreset: true,
                apariencia: {
                    temaActivo: 'nord',
                    opacidad: 0.94,
                    desenfoque: 8,
                    acento: '#88c0d0',
                    densidad: 'normal',
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
                    },
                    fondoGlobal: {
                        tipo: 'movimiento',
                        color: '#2e3440',
                        efectoMovimiento: 'aurora',
                        overlayAlfa: 0.35
                    },
                    secciones: {}
                },
                motorMovimiento: {
                    efecto: 'aurora',
                    fpsLimite: 45,
                    escalaRender: 0.75,
                    densidad: 'media',
                    velocidad: 0.7,
                    interaccionMouse: true,
                    pausarEnSegundoPlano: true
                }
            },
            {
                id: 'synthwave_retro',
                nombre: 'Synthwave 3D Retro',
                icono: 'fa-border-all',
                desc: 'Cuadrícula retro 3D en perspectiva con horizonte ondulante y tonos magenta/oro.',
                esPreset: true,
                apariencia: {
                    temaActivo: 'obsidian_gold',
                    opacidad: 0.90,
                    desenfoque: 10,
                    acento: '#ffd54f',
                    densidad: 'normal',
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
                    },
                    fondoGlobal: {
                        tipo: 'movimiento',
                        color: '#141414',
                        efectoMovimiento: 'malla_cyberpunk',
                        overlayAlfa: 0.30
                    },
                    secciones: {}
                },
                motorMovimiento: {
                    efecto: 'malla_cyberpunk',
                    fpsLimite: 60,
                    escalaRender: 0.75,
                    densidad: 'media',
                    velocidad: 1.0,
                    interaccionMouse: true,
                    pausarEnSegundoPlano: true
                }
            }
        ];
        this.perfilActivoId = 'catppuccin_equilibrado';
        this._guardarLocal();
    }

    async _sincronizarBackend() {
        try {
            const res = await fetch('/api/config/profiles');
            if (res.ok) {
                const data = await res.json();
                if (data && Array.isArray(data.perfiles) && data.perfiles.length > 0) {
                    this.perfiles = data.perfiles;
                    if (data.perfil_activo) this.perfilActivoId = data.perfil_activo;
                    this._guardarLocal();
                }
            }
        } catch (e) {
            // Si el backend no está disponible, continuar con local
        }
    }

    _guardarLocal() {
        try {
            localStorage.setItem('prig_perfiles_config', JSON.stringify({
                perfil_activo: this.perfilActivoId,
                perfiles: this.perfiles
            }));
        } catch (e) {
            console.warn("No se pudo guardar perfiles en localStorage:", e);
        }
    }

    async _guardarBackend() {
        try {
            await fetch('/api/config/profiles', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    perfil_activo: this.perfilActivoId,
                    perfiles: this.perfiles
                })
            });
        } catch (e) {
            // Ignorar fallo de red
        }
    }

    guardarTodo() {
        this._guardarLocal();
        this._guardarBackend();
    }

    obtenerPerfiles() {
        return this.perfiles;
    }

    obtenerPerfilActivo() {
        return this.perfiles.find(p => p.id === this.perfilActivoId) || this.perfiles[0];
    }

    activarPerfil(id) {
        const perfil = this.perfiles.find(p => p.id === id);
        if (!perfil) return false;

        this.perfilActivoId = id;

        // 1. Aplicar apariencia completa
        if (window.aparienciaMgr && perfil.apariencia) {
            window.aparienciaMgr.importarTema(JSON.stringify(perfil.apariencia));
        }

        // 2. Aplicar motor de movimiento
        if (window.motorMovimiento && perfil.motorMovimiento) {
            window.motorMovimiento.config = { ...window.motorMovimiento.config, ...perfil.motorMovimiento };
            window.motorMovimiento.guardarConfig();
            window.motorMovimiento.activarEfecto(perfil.motorMovimiento.efecto || 'particulas');
        }

        this.guardarTodo();

        if (window.layoutMgr) {
            window.layoutMgr.mensajeEstado(`✨ Perfil activado: ${perfil.nombre}`, 2000);
        }

        return true;
    }

    guardarPerfilActual(nombre, icono = 'fa-sliders', desc = '', idSobrescribir = null) {
        const id = idSobrescribir || ('perfil_' + Date.now().toString(36));
        
        // Extraer estado actual en vivo
        const estadoApariencia = window.aparienciaMgr ? JSON.parse(JSON.stringify(window.aparienciaMgr.estado)) : {};
        const configMotor = window.motorMovimiento ? JSON.parse(JSON.stringify(window.motorMovimiento.config)) : {};

        const nuevoPerfil = {
            id,
            nombre: nombre || 'Mi Perfil Personalizado',
            icono: icono || 'fa-sliders',
            desc: desc || `Guardado el ${new Date().toLocaleDateString()}`,
            esPreset: false,
            fechaModificacion: new Date().toISOString(),
            apariencia: estadoApariencia,
            motorMovimiento: configMotor
        };

        const idx = this.perfiles.findIndex(p => p.id === id);
        if (idx >= 0) {
            this.perfiles[idx] = nuevoPerfil;
        } else {
            this.perfiles.push(nuevoPerfil);
        }

        this.perfilActivoId = id;
        this.guardarTodo();

        if (window.layoutMgr) {
            window.layoutMgr.mensajeEstado(`💾 Perfil guardado: ${nuevoPerfil.nombre}`, 2000);
        }

        return nuevoPerfil;
    }

    duplicarPerfil(id) {
        const origen = this.perfiles.find(p => p.id === id);
        if (!origen) return null;

        const nuevoId = 'perfil_' + Date.now().toString(36);
        const clon = JSON.parse(JSON.stringify(origen));
        clon.id = nuevoId;
        clon.nombre = `${origen.nombre} (Copia)`;
        clon.esPreset = false;
        clon.fechaModificacion = new Date().toISOString();

        this.perfiles.push(clon);
        this.guardarTodo();
        return clon;
    }

    eliminarPerfil(id) {
        const idx = this.perfiles.findIndex(p => p.id === id);
        if (idx < 0) return false;

        const perfil = this.perfiles[idx];
        if (perfil.esPreset) {
            alert('Los perfiles predeterminados del sistema no se pueden eliminar.');
            return false;
        }

        this.perfiles.splice(idx, 1);
        if (this.perfilActivoId === id) {
            this.perfilActivoId = this.perfiles[0].id;
            this.activarPerfil(this.perfilActivoId);
        } else {
            this.guardarTodo();
        }

        return true;
    }

    exportarJSON(id = null) {
        let datos;
        if (id) {
            const p = this.perfiles.find(item => item.id === id);
            if (!p) return;
            datos = { tipo: 'prig_perfil_unico', perfil: p };
        } else {
            datos = {
                tipo: 'prig_catalogo_perfiles',
                perfil_activo: this.perfilActivoId,
                perfiles: this.perfiles,
                version: '2.5',
                exportado: new Date().toISOString()
            };
        }

        const blob = new Blob([JSON.stringify(datos, null, 2)], { type: 'application/json' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = id ? `prig_perfil_${id}.json` : `prig_perfiles_todos_${Date.now()}.json`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
    }

    importarJSON(jsonStr) {
        try {
            const data = JSON.parse(jsonStr);
            if (!data || typeof data !== 'object') throw new Error('Formato JSON inválido');

            if (data.tipo === 'prig_perfil_unico' && data.perfil) {
                const p = data.perfil;
                p.id = 'importado_' + Date.now().toString(36);
                p.esPreset = false;
                this.perfiles.push(p);
                this.activarPerfil(p.id);
                return { exito: true, mensaje: `Perfil "${p.nombre}" importado y activado.` };
            } else if (data.perfiles && Array.isArray(data.perfiles)) {
                // Combinar perfiles importados evitando duplicados
                data.perfiles.forEach(imp => {
                    const existente = this.perfiles.find(p => p.id === imp.id);
                    if (!existente) {
                        this.perfiles.push(imp);
                    }
                });
                if (data.perfil_activo) {
                    this.activarPerfil(data.perfil_activo);
                } else {
                    this.guardarTodo();
                }
                return { exito: true, mensaje: `Se importaron ${data.perfiles.length} perfiles con éxito.` };
            } else {
                throw new Error('Estructura de perfiles no reconocida.');
            }
        } catch (e) {
            return { exito: false, error: e.message };
        }
    }

    restablecerPresets() {
        this._cargarPresetsPorDefecto();
        this.activarPerfil('catppuccin_equilibrado');
        this.guardarTodo();
    }
}

// Instanciar singleton
window.PerfilesConfigManager = PerfilesConfigManager;
window.perfilesConfigMgr = new PerfilesConfigManager();
window.perfilesConfigMgr.init();
