/**
 * carrera.js - Gestión de Carreras Universitarias, Materias y Rutas Formativas en Prig IDE.
 *
 * Permite a los usuarios consultar las materias de Ingeniería en IA y Licenciatura en Programación,
 * seguir el estado de aprobación (Pendiente, En curso, Aprobada), visualizar el avance porcentual,
 * explorar el syllabus completo (archivos Markdown de carreras/), y vincular cada materia con:
 * - Cursos audiovisuales en YouTube Hub
 * - Repositorios de código en GitHub Lector
 * - Desafíos interactivos de código en Prig IDE
 */

(function () {
    const $ = (id) => document.getElementById(id);
    const esc = (t) => String(t ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

    class CarreraManager {
        constructor() {
            this.carreras = [];
            this.carreraActivaId = localStorage.getItem('prig_carrera_seleccionada') || 'ingenieria_inteligencia_artificial';
            this.progreso = this.cargarProgreso();
            this.filtroEtapa = 'todas';
            this.filtroEstado = 'todos';
            this.busqueda = '';
            this.cargado = false;
        }

        cargarProgreso() {
            try {
                const guardado = localStorage.getItem('prig_carrera_progreso');
                return guardado ? JSON.parse(guardado) : {};
            } catch (e) {
                console.error("Error leyendo progreso de carrera:", e);
                return {};
            }
        }

        guardarProgreso() {
            try {
                localStorage.setItem('prig_carrera_progreso', JSON.stringify(this.progreso));
            } catch (e) {
                console.error("Error guardando progreso de carrera:", e);
            }
        }

        async cargarDatos() {
            if (this.cargado && this.carreras.length > 0) return;
            try {
                const res = await fetch('/api/carreras');
                if (res.ok) {
                    this.carreras = await res.json();
                } else {
                    const fallbackRes = await fetch('/static/data/carreras.json');
                    if (fallbackRes.ok) this.carreras = await fallbackRes.json();
                }
                this.cargado = true;
            } catch (err) {
                console.error("Error cargando carreras:", err);
            }
        }

        obtenerCarreraActual() {
            if (!this.carreras || this.carreras.length === 0) return null;
            return this.carreras.find(c => c.id === this.carreraActivaId) || this.carreras[0];
        }

        seleccionarCarrera(id) {
            this.carreraActivaId = id;
            localStorage.setItem('prig_carrera_seleccionada', id);
            this.filtroEtapa = 'todas';
            this.filtroEstado = 'todos';
            this.busqueda = '';
            this.render();
        }

        cambiarEstadoMateria(codigo, nuevoEstado) {
            if (!codigo) return;
            this.progreso[codigo] = nuevoEstado;
            this.guardarProgreso();
            this.render();
        }

        toggleEstadoMateria(codigo) {
            const actual = this.progreso[codigo] || 'pendiente';
            const secuencia = {
                'pendiente': 'en_curso',
                'en_curso': 'aprobada',
                'aprobada': 'pendiente'
            };
            this.cambiarEstadoMateria(codigo, secuencia[actual] || 'en_curso');
        }

        abrirEnYouTube(query) {
            if (!query) return;
            if (window.YouTubeHub && typeof window.YouTubeHub.abrir === 'function') {
                window.YouTubeHub.abrir({ busqueda: query });
            } else if (window.workArea) {
                window.workArea.abrirHerramienta('modal-youtube', 'YouTube', 'fa-brands fa-youtube');
            }
        }

        abrirEnGitHub(repoUrl) {
            if (!repoUrl) return;
            if (repoUrl.startsWith('http')) {
                window.open(repoUrl, '_blank', 'noopener,noreferrer');
            } else if (window.GitHubLector && typeof window.GitHubLector.abrir === 'function') {
                window.GitHubLector.abrir({ ref: repoUrl });
            }
        }

        abrirDesafios() {
            if (window.workArea) {
                window.workArea.abrirHerramienta('modal-desafios', 'Desafíos', 'fa-trophy');
            } else if (window.Desafios && typeof window.Desafios.abrir === 'function') {
                window.Desafios.abrir();
            }
        }

        async verDetalleMateria(archivoRelativo, codigo, nombre) {
            const modal = $('modal-materia-detalle');
            const tituloEl = $('materia-detalle-titulo');
            const contEl = $('materia-detalle-contenido');
            if (!modal || !contEl) return;

            if (tituloEl) tituloEl.innerHTML = `<i class="fa-solid fa-book-open" style="color:var(--accent-purple);"></i> ${esc(codigo)}: ${esc(nombre)}`;
            contEl.innerHTML = `<div style="text-align:center; padding: 40px; color: var(--text-muted);"><i class="fa-solid fa-spinner fa-spin" style="font-size:24px;"></i> Cargando programa académico...</div>`;
            modal.style.display = 'flex';

            try {
                const res = await fetch(`/api/carreras/materia?archivo=${encodeURIComponent(archivoRelativo)}`);
                if (!res.ok) throw new Error("No se pudo cargar el archivo de la materia");
                const data = await res.json();
                const mdRaw = data.contenido || '';
                
                let renderedHtml = '';
                if (typeof marked !== 'undefined') {
                    renderedHtml = marked.parse(mdRaw);
                    if (typeof DOMPurify !== 'undefined') {
                        renderedHtml = DOMPurify.sanitize(renderedHtml);
                    }
                } else {
                    renderedHtml = `<pre style="white-space: pre-wrap; font-family: monospace;">${esc(mdRaw)}</pre>`;
                }
                contEl.innerHTML = `<div class="markdown-preview" style="line-height: 1.6;">${renderedHtml}</div>`;
            } catch (err) {
                contEl.innerHTML = `<div style="color:var(--accent-red); padding: 20px; text-align: center;"><i class="fa-solid fa-triangle-exclamation"></i> Error al cargar el programa de la materia: ${esc(err.message)}</div>`;
            }
        }

        async render() {
            const contenedor = $('pane-perfil-carrera');
            if (!contenedor) return;

            await this.cargarDatos();

            const carrera = this.obtenerCarreraActual();
            if (!carrera) {
                contenedor.innerHTML = `<div style="color:var(--text-muted); text-align:center; padding:40px;">Cargando planes de estudio universitarios...</div>`;
                return;
            }

            // Calcular métricas de avance
            let totalMaterias = 0;
            let aprobadas = 0;
            let enCurso = 0;
            let totalHoras = 0;
            let horasAprobadas = 0;

            (carrera.etapas || []).forEach(et => {
                (et.materias || []).forEach(m => {
                    totalMaterias++;
                    totalHoras += (m.horas || 0);
                    const st = this.progreso[m.codigo] || 'pendiente';
                    if (st === 'aprobada') {
                        aprobadas++;
                        horasAprobadas += (m.horas || 0);
                    } else if (st === 'en_curso') {
                        enCurso++;
                    }
                });
            });

            const pendientes = totalMaterias - aprobadas - enCurso;
            const pctAprobado = totalMaterias > 0 ? Math.round((aprobadas / totalMaterias) * 100) : 0;

            // Header con selector de carreras y estadísticas globales
            let html = `
            <div style="display: flex; flex-direction: column; gap: 16px;">
                <!-- Selector de Carrera Superior -->
                <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 12px; background: rgba(0,0,0,0.3); border: 1px solid var(--border-color); border-radius: 10px; padding: 12px 16px;">
                    <div style="display: flex; align-items: center; gap: 10px;">
                        <span style="font-size: 13px; font-weight: 600; color: var(--text-muted);"><i class="fa-solid fa-graduation-cap" style="color: var(--accent-purple);"></i> Programa Universitario:</span>
                        <div style="display: flex; gap: 6px;">
                            ${this.carreras.map(c => `
                                <button class="tool-btn ${c.id === carrera.id ? 'active' : ''}" 
                                        style="font-size: 12px; padding: 6px 12px; border-radius: 6px; cursor: pointer;"
                                        onclick="window.carreraMgr.seleccionarCarrera('${esc(c.id)}')">
                                    <i class="${c.codigo === 'IIA' ? 'fa-solid fa-brain' : 'fa-solid fa-code'}"></i> ${esc(c.nombre)}
                                </button>
                            `).join('')}
                        </div>
                    </div>
                    <div style="font-size: 12px; color: var(--text-muted); display: flex; align-items: center; gap: 6px;">
                        <i class="fa-solid fa-clock"></i> Carga: <b style="color: #fff;">${totalHoras} hrs</b> reloj · <b style="color: var(--accent-blue);">${carrera.duracion_anios} años</b>
                    </div>
                </div>

                <!-- Tarjeta de Progreso Académico y Estadísticas -->
                <div style="background: rgba(0,0,0,0.25); border: 1px solid var(--border-color); border-radius: 10px; padding: 16px; display: flex; flex-direction: column; gap: 14px;">
                    <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px;">
                        <div>
                            <h4 style="margin: 0; color: #fff; font-size: 15px; font-weight: 700;">
                                <i class="fa-solid fa-chart-pie" style="color: var(--accent-green); margin-right: 6px;"></i> Avance de la Carrera: ${esc(carrera.nombre)}
                            </h4>
                            <span style="font-size: 12px; color: var(--text-muted);">${esc(carrera.titulo_obtenido)} · ${esc(carrera.descripcion)}</span>
                        </div>
                        <div style="text-align: right;">
                            <span style="font-size: 20px; font-weight: 800; color: var(--accent-green);">${pctAprobado}%</span>
                            <div style="font-size: 11px; color: var(--text-muted);">Completado (${aprobadas}/${totalMaterias} materias)</div>
                        </div>
                    </div>

                    <!-- Barra de progreso -->
                    <div style="width: 100%; height: 8px; background: rgba(255,255,255,0.08); border-radius: 4px; overflow: hidden; display: flex;">
                        <div style="width: ${pctAprobado}%; height: 100%; background: linear-gradient(90deg, #a6e3a1, #94e2d5); transition: width 0.3s ease;"></div>
                    </div>

                    <!-- Métricas de estado de materias -->
                    <div style="display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px;">
                        <div style="background: rgba(166, 227, 161, 0.1); border: 1px solid rgba(166, 227, 161, 0.25); border-radius: 8px; padding: 10px; text-align: center;">
                            <div style="font-size: 11px; color: var(--accent-green); font-weight: 600;"><i class="fa-solid fa-circle-check"></i> Aprobadas</div>
                            <div style="font-size: 18px; font-weight: bold; color: #fff; margin-top: 2px;">${aprobadas}</div>
                        </div>
                        <div style="background: rgba(249, 226, 175, 0.1); border: 1px solid rgba(249, 226, 175, 0.25); border-radius: 8px; padding: 10px; text-align: center;">
                            <div style="font-size: 11px; color: var(--accent-yellow); font-weight: 600;"><i class="fa-solid fa-spinner"></i> En Curso</div>
                            <div style="font-size: 18px; font-weight: bold; color: #fff; margin-top: 2px;">${enCurso}</div>
                        </div>
                        <div style="background: rgba(205, 214, 244, 0.05); border: 1px solid rgba(255,255,255,0.1); border-radius: 8px; padding: 10px; text-align: center;">
                            <div style="font-size: 11px; color: var(--text-muted); font-weight: 600;"><i class="fa-regular fa-circle"></i> Pendientes</div>
                            <div style="font-size: 18px; font-weight: bold; color: #fff; margin-top: 2px;">${pendientes}</div>
                        </div>
                        <div style="background: rgba(137, 180, 250, 0.1); border: 1px solid rgba(137, 180, 250, 0.25); border-radius: 8px; padding: 10px; text-align: center;">
                            <div style="font-size: 11px; color: var(--accent-blue); font-weight: 600;"><i class="fa-solid fa-book-bookmark"></i> Total Materias</div>
                            <div style="font-size: 18px; font-weight: bold; color: #fff; margin-top: 2px;">${totalMaterias}</div>
                        </div>
                    </div>
                </div>

                <!-- Filtros y Búsqueda -->
                <div style="display: flex; gap: 10px; align-items: center; flex-wrap: wrap; background: rgba(0,0,0,0.2); border: 1px solid var(--border-color); border-radius: 8px; padding: 10px 14px;">
                    <div style="flex: 1; min-width: 200px; position: relative;">
                        <i class="fa-solid fa-magnifying-glass" style="position: absolute; left: 10px; top: 9px; font-size: 12px; color: var(--text-muted);"></i>
                        <input id="carrera-input-buscar" type="text" placeholder="Buscar materias por nombre, código o palabra clave..." 
                               value="${esc(this.busqueda)}"
                               oninput="window.carreraMgr.busqueda = this.value; window.carreraMgr.renderMateriasFiltradas();"
                               style="width: 100%; padding: 6px 10px 6px 30px; background: rgba(0,0,0,0.4); border: 1px solid var(--border-color); border-radius: 6px; color: #fff; font-size: 12px; box-sizing: border-box;">
                    </div>

                    <div style="display: flex; gap: 8px; align-items: center;">
                        <label style="font-size: 11px; color: var(--text-muted);">Etapa:</label>
                        <select id="carrera-select-etapa" onchange="window.carreraMgr.filtroEtapa = this.value; window.carreraMgr.renderMateriasFiltradas();"
                                style="padding: 5px 8px; background: var(--bg-panel); border: 1px solid var(--border-color); color: #fff; border-radius: 6px; font-size: 12px;">
                            <option value="todas">Todas las etapas (1 a 5)</option>
                            ${(carrera.etapas || []).map(et => `
                                <option value="${et.numero}" ${this.filtroEtapa == et.numero ? 'selected' : ''}>Etapa ${et.numero}: ${esc(et.nombre.split(':')[1] || et.nombre)}</option>
                            `).join('')}
                        </select>

                        <label style="font-size: 11px; color: var(--text-muted); margin-left: 6px;">Estado:</label>
                        <select id="carrera-select-estado" onchange="window.carreraMgr.filtroEstado = this.value; window.carreraMgr.renderMateriasFiltradas();"
                                style="padding: 5px 8px; background: var(--bg-panel); border: 1px solid var(--border-color); color: #fff; border-radius: 6px; font-size: 12px;">
                            <option value="todos" ${this.filtroEstado === 'todos' ? 'selected' : ''}>Todos los estados</option>
                            <option value="aprobada" ${this.filtroEstado === 'aprobada' ? 'selected' : ''}>Aprobadas</option>
                            <option value="en_curso" ${this.filtroEstado === 'en_curso' ? 'selected' : ''}>En Curso</option>
                            <option value="pendiente" ${this.filtroEstado === 'pendiente' ? 'selected' : ''}>Pendientes</option>
                        </select>
                    </div>
                </div>

                <!-- Lista de Etapas y Materias -->
                <div id="carrera-lista-etapas" style="display: flex; flex-direction: column; gap: 16px;">
                    <!-- Renderizado dinámico de materias -->
                </div>
            </div>
            `;

            contenedor.innerHTML = html;
            this.renderMateriasFiltradas();
        }

        renderMateriasFiltradas() {
            const listEl = $('carrera-lista-etapas');
            if (!listEl) return;

            const carrera = this.obtenerCarreraActual();
            if (!carrera) return;

            const q = (this.busqueda || '').toLowerCase().trim();
            let totalVisibles = 0;

            let html = '';

            (carrera.etapas || []).forEach(et => {
                if (this.filtroEtapa !== 'todas' && String(et.numero) !== String(this.filtroEtapa)) {
                    return;
                }

                const materiasFiltradas = (et.materias || []).filter(m => {
                    const st = this.progreso[m.codigo] || 'pendiente';
                    if (this.filtroEstado !== 'todos' && st !== this.filtroEstado) return false;

                    if (q) {
                        const coincideTexto = m.nombre.toLowerCase().includes(q) ||
                                              m.codigo.toLowerCase().includes(q) ||
                                              (m.objetivos && m.objetivos.toLowerCase().includes(q)) ||
                                              (m.temas && m.temas.some(t => t.toLowerCase().includes(q)));
                        if (!coincideTexto) return false;
                    }
                    return true;
                });

                if (materiasFiltradas.length === 0) return;

                totalVisibles += materiasFiltradas.length;

                html += `
                <div style="background: rgba(0,0,0,0.2); border: 1px solid var(--border-color); border-radius: 10px; overflow: hidden;">
                    <!-- Cabecera de Etapa -->
                    <div style="padding: 12px 16px; background: rgba(255,255,255,0.03); border-bottom: 1px solid var(--border-color); display: flex; justify-content: space-between; align-items: center;">
                        <div>
                            <h5 style="margin: 0; color: var(--accent-purple); font-size: 13.5px; font-weight: 700;">
                                <i class="fa-solid fa-layer-group" style="margin-right: 6px;"></i> ${esc(et.nombre)}
                            </h5>
                            <span style="font-size: 11.5px; color: var(--text-muted);">${esc(et.descripcion)}</span>
                        </div>
                        <span style="font-size: 11px; color: var(--text-muted); background: rgba(0,0,0,0.3); padding: 3px 8px; border-radius: 4px; border: 1px solid var(--border-color);">
                            ${materiasFiltradas.length} materia${materiasFiltradas.length === 1 ? '' : 's'}
                        </span>
                    </div>

                    <!-- Grid de Materias en la Etapa -->
                    <div style="padding: 14px; display: grid; grid-template-columns: repeat(auto-fill, minmax(360px, 1fr)); gap: 12px;">
                        ${materiasFiltradas.map(m => {
                            const st = this.progreso[m.codigo] || 'pendiente';
                            const stColor = st === 'aprobada' ? '#a6e3a1' : (st === 'en_curso' ? '#f9e2af' : 'var(--text-muted)');
                            const stBg = st === 'aprobada' ? 'rgba(166, 227, 161, 0.12)' : (st === 'en_curso' ? 'rgba(249, 226, 175, 0.12)' : 'rgba(255, 255, 255, 0.04)');
                            const stIcon = st === 'aprobada' ? 'fa-solid fa-circle-check' : (st === 'en_curso' ? 'fa-solid fa-spinner' : 'fa-regular fa-circle');
                            const stLabel = st === 'aprobada' ? 'Aprobada' : (st === 'en_curso' ? 'En Curso' : 'Pendiente');

                            const primeraBusquedaYt = (m.youtube_queries && m.youtube_queries.length > 0) ? m.youtube_queries[0] : `${m.nombre} curso completo`;
                            const primerRepo = (m.github_repos && m.github_repos.length > 0) ? m.github_repos[0] : null;

                            return `
                            <div style="background: rgba(0,0,0,0.3); border: 1px solid ${st === 'aprobada' ? 'rgba(166, 227, 161, 0.35)' : (st === 'en_curso' ? 'rgba(249, 226, 175, 0.35)' : 'var(--border-color)')}; border-radius: 8px; padding: 14px; display: flex; flex-direction: column; justify-content: space-between; gap: 10px; transition: border-color 0.2s;">
                                <div>
                                    <!-- Encabezado de la tarjeta -->
                                    <div style="display: flex; justify-content: space-between; align-items: flex-start; gap: 8px; margin-bottom: 6px;">
                                        <div>
                                            <span style="font-size: 10px; font-weight: 700; color: var(--accent-blue); background: rgba(137, 180, 250, 0.15); padding: 2px 6px; border-radius: 4px; border: 1px solid rgba(137, 180, 250, 0.3);">
                                                ${esc(m.codigo)}
                                            </span>
                                            <h6 style="margin: 6px 0 2px 0; color: #fff; font-size: 13px; font-weight: 700; line-height: 1.3;">
                                                ${esc(m.nombre)}
                                            </h6>
                                        </div>

                                        <!-- Botón de Estado Clickeable para cambiar rápidamente -->
                                        <button onclick="window.carreraMgr.toggleEstadoMateria('${esc(m.codigo)}')"
                                                title="Haz clic para alternar estado (Pendiente → En Curso → Aprobada)"
                                                style="background: ${stBg}; color: ${stColor}; border: 1px solid ${stColor}; border-radius: 12px; padding: 3px 9px; font-size: 11px; cursor: pointer; display: flex; align-items: center; gap: 4px; font-weight: 600; white-space: nowrap; transition: transform 0.1s;">
                                            <i class="${stIcon}"></i> ${stLabel}
                                        </button>
                                    </div>

                                    <!-- Datos de carga horaria y correlatividades -->
                                    <div style="display: flex; gap: 10px; font-size: 11px; color: var(--text-muted); margin-bottom: 6px;">
                                        <span><i class="fa-regular fa-clock"></i> ${m.horas || 0} hrs</span>
                                        <span><i class="fa-solid fa-award"></i> ${m.creditos || 0} créditos</span>
                                    </div>

                                    <!-- Breve descripción -->
                                    <p style="margin: 0; font-size: 11.5px; color: #a6adc8; line-height: 1.4; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden;">
                                        ${esc(m.objetivos || '')}
                                    </p>
                                </div>

                                <!-- Acciones: YouTube, GitHub, Desafíos, Detalle Markdown -->
                                <div style="display: flex; gap: 6px; flex-wrap: wrap; pt: 6px; border-top: 1px solid rgba(255,255,255,0.06); padding-top: 8px;">
                                    <button class="tool-btn" style="font-size: 11px; padding: 4px 8px; border-radius: 4px; cursor: pointer;"
                                            onclick="window.carreraMgr.abrirEnYouTube('${esc(primeraBusquedaYt)}')"
                                            title="Buscar cursos y clases magistrales de esta materia en YouTube">
                                        <i class="fa-brands fa-youtube" style="color: #f38ba8;"></i> YouTube
                                    </button>

                                    ${primerRepo ? `
                                    <button class="tool-btn" style="font-size: 11px; padding: 4px 8px; border-radius: 4px; cursor: pointer;"
                                            onclick="window.carreraMgr.abrirEnGitHub('${esc(primerRepo)}')"
                                            title="Abrir repositorio de referencia en GitHub">
                                        <i class="fa-brands fa-github" style="color: #cba6f7;"></i> GitHub
                                    </button>
                                    ` : ''}

                                    <button class="tool-btn" style="font-size: 11px; padding: 4px 8px; border-radius: 4px; cursor: pointer;"
                                            onclick="window.carreraMgr.abrirDesafios()"
                                            title="Practicar con desafíos de código en Prig IDE">
                                        <i class="fa-solid fa-trophy" style="color: var(--accent-yellow);"></i> Desafíos
                                    </button>

                                    <button class="tool-btn" style="font-size: 11px; padding: 4px 8px; border-radius: 4px; cursor: pointer; margin-left: auto; background: rgba(137, 180, 250, 0.1); border-color: rgba(137, 180, 250, 0.3);"
                                            onclick="window.carreraMgr.verDetalleMateria('${esc(m.archivo_markdown)}', '${esc(m.codigo)}', '${esc(m.nombre)}')"
                                            title="Ver programa analítico completo y apuntes clave de la materia">
                                        <i class="fa-solid fa-book-open" style="color: var(--accent-blue);"></i> Syllabus
                                    </button>
                                </div>
                            </div>
                            `;
                        }).join('')}
                    </div>
                </div>
                `;
            });

            if (totalVisibles === 0) {
                html = `
                <div style="text-align: center; padding: 40px; color: var(--text-muted); background: rgba(0,0,0,0.2); border-radius: 8px; border: 1px dashed var(--border-color);">
                    <i class="fa-solid fa-filter-circle-xmark" style="font-size: 28px; margin-bottom: 10px; color: var(--text-muted); opacity: 0.6;"></i>
                    <p style="margin: 0;">No se encontraron materias con los filtros seleccionados.</p>
                </div>
                `;
            }

            listEl.innerHTML = html;
        }
    }

    window.carreraMgr = new CarreraManager();

    // Función global para alternar pestañas en el perfil
    window.cambiarPestanaPerfil = function(pestana) {
        const btnResumen = $('tab-btn-perfil-resumen');
        const btnCarrera = $('tab-btn-perfil-carrera');
        const paneResumen = $('pane-perfil-resumen');
        const paneCarrera = $('pane-perfil-carrera');

        if (pestana === 'carrera') {
            if (btnResumen) btnResumen.classList.remove('active');
            if (btnCarrera) btnCarrera.classList.add('active');
            if (paneResumen) paneResumen.style.display = 'none';
            if (paneCarrera) {
                paneCarrera.style.display = 'flex';
                window.carreraMgr.render();
            }
        } else {
            if (btnResumen) btnResumen.classList.add('active');
            if (btnCarrera) btnCarrera.classList.remove('active');
            if (paneResumen) paneResumen.style.display = 'flex';
            if (paneCarrera) paneCarrera.style.display = 'none';
        }
    };
})();
