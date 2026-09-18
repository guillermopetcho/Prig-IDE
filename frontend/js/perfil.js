/**
 * Gestor del Perfil de Aprendizaje, Árbol de Habilidades, Mapa de Calor y Hexágono de Competencias
 */
class PerfilManager {
    constructor() {
        this.modal = document.getElementById('modal-perfil');
        this.canvas = document.getElementById('perfil-hexagon-canvas');
        this.dataset = null;
    }

    async openModal() {
        const modal = document.getElementById('modal-perfil');
        if (!modal) return;
        modal.style.display = 'flex';
        await this.loadDataset();
    }

    closeModal() {
        const modal = document.getElementById('modal-perfil');
        if (modal) modal.style.display = 'none';
    }

    async loadDataset() {
        try {
            // Dos fuentes distintas a propósito: el dataset cuenta ACTIVIDAD (ítems
            // marcados) y las métricas miden COMPETENCIA (resultado de ejecutar el
            // código del alumno). Confundirlas era el defecto del perfil anterior.
            const [resDataset, resMetrics] = await Promise.all([
                fetch('/api/dataset/summary'),
                fetch('/api/learning/metrics?days=30').catch(() => null)
            ]);

            if (!resDataset.ok) throw new Error("Error obteniendo datos del usuario");
            this.dataset = await resDataset.json();

            this.metrics = null;
            if (resMetrics && resMetrics.ok) {
                try { this.metrics = await resMetrics.json(); } catch (e) {}
            }

            this.renderProfile();
        } catch (err) {
            console.error("⚠️ Error cargando perfil:", err);
            const container = document.getElementById('perfil-content-container');
            if (container) {
                container.innerHTML = `<div style="color:var(--accent-red); text-align:center; padding:20px;">Error al cargar el perfil: ${err.message}</div>`;
            }
        }
    }

    renderProfile() {
        if (!this.dataset) return;

        // Avance completo (desafíos, plan, ejercicios) al principio: es lo que conecta todo
        if (window.ProgresoPerfil) window.ProgresoPerfil.render(document.getElementById('perfil-content-container'));

        const metrics = this.dataset.metrics || {};
        const hexagon = this.dataset.hexagon || {};
        const heatmap = this.dataset.activity_heatmap || {};
        const mastered = this.dataset.mastered_topics || [];
        const competencies = this.dataset.acquired_competencies || [];

        // 0. Competencia real, antes que la actividad
        this.renderCompetencia();

        // 1. Actualizar Tarjetas de Métricas Principales
        document.getElementById('perfil-stat-recorridos').innerText = `${metrics.completed_recorridos || 0} / ${metrics.total_recorridos || 0}`;
        document.getElementById('perfil-stat-seguimientos').innerText = `${metrics.completed_seguimientos || 0} / ${metrics.total_seguimientos || 0}`;
        document.getElementById('perfil-stat-blocks').innerText = metrics.total_blocks_completed || 0;
        document.getElementById('perfil-stat-topics').innerText = metrics.total_topics_mastered || 0;

        // 2. Renderizar Hexágono / Gráfico Radar de Competencias
        this.drawRadarHexagon(hexagon);

        // 3. Renderizar Leyenda Detallada del Hexágono
        this.renderHexagonLegend(hexagon);

        // 4. Renderizar Mapa de Calor (Activity Heatmap)
        this.renderHeatmap(heatmap);

        // 5. Renderizar Árbol de Habilidades y Competencias
        this.renderSkillTree(mastered, competencies);
    }

    /** Métricas derivadas de ejecutar el código del alumno */
    renderCompetencia() {
        const stats = document.getElementById('perfil-competencia-stats');
        const errores = document.getElementById('perfil-errores');
        const debiles = document.getElementById('perfil-debiles');
        if (!stats) return;

        const m = this.metrics;
        const esc = (t) => String(t ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

        if (!m || !m.submissions) {
            stats.innerHTML = `
                <div style="grid-column: 1 / -1; padding: 18px; text-align: center; color: var(--text-muted); font-size: 12px; line-height: 1.6;">
                    Todavía no hay nada que medir.<br>
                    Resuelve un ejercicio en <strong style="color: var(--accent-green);">Práctica</strong> y aquí aparecerá
                    en qué fallas y qué conceptos se te resisten.
                </div>`;
            if (errores) errores.innerHTML = '';
            if (debiles) debiles.innerHTML = '';
            return;
        }

        const tile = (valor, etiqueta, color, ayuda) => `
            <div style="background: rgba(0,0,0,0.3); border: 1px solid var(--border-color); border-radius: 8px; padding: 10px 12px;" title="${esc(ayuda)}">
                <div style="font-size: 20px; font-weight: 700; color: ${color}; line-height: 1.2;">${valor}</div>
                <div style="font-size: 10px; color: var(--text-muted); margin-top: 2px; line-height: 1.3;">${etiqueta}</div>
            </div>`;

        const pct = (v) => (v === null || v === undefined) ? '—' : `${v}%`;
        const segundos = m.avg_seconds_to_green;
        const tiempo = segundos === null || segundos === undefined
            ? '—'
            : (segundos >= 60 ? `${Math.round(segundos / 60)} min` : `${Math.round(segundos)} s`);

        stats.innerHTML =
            tile(pct(m.first_try_pass_rate), 'Acierto al primer intento, sin pistas', 'var(--accent-green)',
                 'La métrica más honesta: resolver a la primera y sin ayuda.') +
            tile(pct(m.solve_rate), 'Ejercicios que terminas resolviendo', 'var(--accent-blue)',
                 'Incluye los que costaron varios intentos.') +
            tile(m.median_attempts_to_pass ?? '—', 'Intentos hasta acertar (mediana)', 'var(--accent-yellow)',
                 'Cuántos envíos necesitas de media.') +
            tile(tiempo, 'Hasta el primer test en verde', 'var(--accent-purple)',
                 'Tiempo desde el primer envío hasta que pasan todos los tests.');

        // Perfil de errores: clasificado a partir de tracebacks reales
        if (errores) {
            const entradas = Object.entries(m.error_profile || {});
            if (!entradas.length) {
                errores.innerHTML = `<div style="font-size:12px; color: var(--text-muted);">Sin fallos registrados todavía.</div>`;
            } else {
                const max = Math.max(...entradas.map(([, n]) => n));
                const nombres = {
                    logica_incorrecta: 'Lógica incorrecta', sintaxis: 'Sintaxis',
                    indentacion: 'Indentación', nombre_no_definido: 'Nombre no definido',
                    tipos: 'Tipos', valor_invalido: 'Valor inválido',
                    indice_fuera_de_rango: 'Índice fuera de rango', clave_inexistente: 'Clave inexistente',
                    atributo_inexistente: 'Atributo inexistente', division_por_cero: 'División por cero',
                    recursion_infinita: 'Recursión infinita', bucle_infinito: 'Bucle infinito', otro: 'Otro'
                };
                errores.innerHTML = entradas.map(([clave, n]) => `
                    <div style="display:flex; align-items:center; gap:8px; margin-bottom:5px;">
                        <div style="flex:1; font-size:11px; color: var(--text-main);">${esc(nombres[clave] || clave)}</div>
                        <div style="width:96px; height:6px; background: rgba(255,255,255,0.07); border-radius:3px; overflow:hidden;">
                            <div style="width:${Math.round(n / max * 100)}%; height:100%; background: var(--accent-red);"></div>
                        </div>
                        <div style="font-size:11px; color: var(--text-muted); width:18px; text-align:right;">${n}</div>
                    </div>`).join('');
            }
        }

        // Conceptos débiles, con acción directa: practicar justo eso
        if (debiles) {
            const lista = m.weak_concepts || [];
            if (!lista.length) {
                debiles.innerHTML = `<div style="font-size:12px; color: var(--text-muted);">Ningún concepto se te resiste por ahora.</div>`;
            } else {
                const reincidentes = new Set(m.repeated_concepts || []);
                debiles.innerHTML = lista.map(c => {
                    const repetido = reincidentes.has(c.concept);
                    return `
                    <div style="display:flex; align-items:center; gap:8px; margin-bottom:6px;">
                        <div style="flex:1; font-size:11px; color: var(--text-main); line-height:1.35;">
                            ${esc(c.concept)}
                            ${repetido ? '<span style="color: var(--accent-red); font-size:9px; margin-left:4px;" title="Vuelves a fallarlo en días distintos">reincidente</span>' : ''}
                        </div>
                        <span style="font-size:10px; color: var(--text-muted);">${c.failures}×</span>
                        <button onclick="window.perfilMgr.practicar('${esc(c.concept).replace(/'/g, "\\'")}')"
                            style="font-size:10px; padding:2px 7px; border-radius:4px; background: rgba(166,227,161,0.15); color: var(--accent-green); border:1px solid rgba(166,227,161,0.35); cursor:pointer; white-space:nowrap;">
                            Practicar
                        </button>
                    </div>`;
                }).join('');
            }
        }
    }

    /** Saltar del diagnóstico a desafíos de ese concepto concreto */
    practicar(concepto) {
        this.closeModal();
        if (window.Desafios) window.Desafios.abrir({ tema: concepto });
    }

    drawRadarHexagon(hexagonData) {
        const canvas = document.getElementById('perfil-hexagon-canvas');
        if (!canvas) return;
        const ctx = canvas.getContext('2d');
        const width = canvas.width;
        const height = canvas.height;
        const centerX = width / 2;
        const centerY = height / 2;
        const maxRadius = Math.min(width, height) / 2 - 45;

        ctx.clearRect(0, 0, width, height);

        const categories = [
            { key: "matematicas", label: "Matemáticas" },
            { key: "programacion", label: "Programación" },
            { key: "machine_learning", label: "Machine Learning" },
            { key: "deep_learning", label: "Deep Learning" },
            { key: "base_de_datos", label: "Base de Datos" },
            { key: "teoria_computacional", label: "Teoría Computacional" }
        ];

        const totalAxes = categories.length;

        // Dibujar Anillos Concentrativos Hexagonales (20%, 40%, 60%, 80%, 100%)
        const rings = 5;
        for (let r = 1; r <= rings; r++) {
            const radius = (maxRadius / rings) * r;
            ctx.beginPath();
            for (let i = 0; i < totalAxes; i++) {
                const angle = (Math.PI * 2 / totalAxes) * i - Math.PI / 2;
                const x = centerX + radius * Math.cos(angle);
                const y = centerY + radius * Math.sin(angle);
                if (i === 0) ctx.moveTo(x, y);
                else ctx.lineTo(x, y);
            }
            ctx.closePath();
            ctx.strokeStyle = r === rings ? "rgba(203, 166, 247, 0.4)" : "rgba(255, 255, 255, 0.08)";
            ctx.lineWidth = r === rings ? 1.5 : 1;
            ctx.stroke();
        }

        // Dibujar Ejes Radiales
        for (let i = 0; i < totalAxes; i++) {
            const angle = (Math.PI * 2 / totalAxes) * i - Math.PI / 2;
            const x = centerX + maxRadius * Math.cos(angle);
            const y = centerY + maxRadius * Math.sin(angle);
            ctx.beginPath();
            ctx.moveTo(centerX, centerY);
            ctx.lineTo(x, y);
            ctx.strokeStyle = "rgba(255, 255, 255, 0.12)";
            ctx.stroke();

            // Dibujar Etiquetas de Ejes
            const labelRadius = maxRadius + 22;
            const lx = centerX + labelRadius * Math.cos(angle);
            const ly = centerY + labelRadius * Math.sin(angle);

            ctx.font = "bold 11px Inter, sans-serif";
            ctx.fillStyle = "#cdd6f4";
            ctx.textAlign = "center";
            ctx.textBaseline = "middle";
            ctx.fillText(categories[i].label, lx, ly);
        }

        // Calcular puntos del polígono de habilidades del usuario
        const polygonPoints = [];
        categories.forEach((cat, i) => {
            const dataObj = hexagonData[cat.key] || { score: 0, max_scale: 100 };
            const ratio = Math.min(1.0, dataObj.score / dataObj.max_scale);
            // Mínimo de radio para visualización limpia cuando es 0
            const currentRadius = Math.max(12, maxRadius * ratio);
            const angle = (Math.PI * 2 / totalAxes) * i - Math.PI / 2;
            polygonPoints.push({
                x: centerX + currentRadius * Math.cos(angle),
                y: centerY + currentRadius * Math.sin(angle),
                score: dataObj.score,
                level: dataObj.level || 1
            });
        });

        // Dibujar Área Rellena del Polígono de Competencias
        ctx.beginPath();
        polygonPoints.forEach((pt, i) => {
            if (i === 0) ctx.moveTo(pt.x, pt.y);
            else ctx.lineTo(pt.x, pt.y);
        });
        ctx.closePath();

        ctx.fillStyle = "rgba(203, 166, 247, 0.3)";
        ctx.fill();
        ctx.strokeStyle = "#cba6f7";
        ctx.lineWidth = 2.5;
        ctx.stroke();

        // Dibujar Vértices Brillantes y Valores
        polygonPoints.forEach((pt) => {
            ctx.beginPath();
            ctx.arc(pt.x, pt.y, 5, 0, Math.PI * 2);
            ctx.fillStyle = "#a6e3a1";
            ctx.fill();
            ctx.strokeStyle = "#ffffff";
            ctx.lineWidth = 1.5;
            ctx.stroke();
        });
    }

    renderHexagonLegend(hexagonData) {
        const legendContainer = document.getElementById('perfil-hexagon-legend');
        if (!legendContainer) return;

        const categories = [
            { key: "matematicas", label: "Matemáticas", color: "#89b4fa" },
            { key: "programacion", label: "Programación", color: "#a6e3a1" },
            { key: "machine_learning", label: "Machine Learning", color: "#f9e2af" },
            { key: "deep_learning", label: "Deep Learning", color: "#cba6f7" },
            { key: "base_de_datos", label: "Base de Datos", color: "#f38ba8" },
            { key: "teoria_computacional", label: "Teoría Computacional", color: "#fab387" }
        ];

        let html = '';
        categories.forEach(cat => {
            const dataObj = hexagonData[cat.key] || { score: 0, level: 1, completed_items_count: 0 };
            html += `
                <div style="background: rgba(0,0,0,0.25); border: 1px solid var(--border-color); border-radius: 8px; padding: 10px; display: flex; align-items: center; justify-content: space-between;">
                    <div style="display: flex; align-items: center; gap: 8px;">
                        <span style="width: 10px; height: 10px; border-radius: 50%; background: ${cat.color}; display: inline-block;"></span>
                        <div>
                            <div style="font-weight: 600; font-size: 12px; color: #fff;">${cat.label}</div>
                            <div style="font-size: 11px; color: var(--text-muted);">${dataObj.completed_items_count} ítems completados</div>
                        </div>
                    </div>
                    <div style="text-align: right;">
                        <div style="font-weight: bold; font-size: 13px; color: ${cat.color};">${dataObj.score} pts</div>
                        <div style="font-size: 10px; color: var(--accent-yellow); font-weight: 500;">Nivel ${dataObj.level}</div>
                    </div>
                </div>
            `;
        });

        legendContainer.innerHTML = html;
    }

    renderHeatmap(heatmapData) {
        const container = document.getElementById('perfil-heatmap-grid');
        if (!container) return;

        // Generar matriz de 30 días recientes
        const today = new Date();
        const days = [];
        let totalActiveDays = 0;
        let totalEvents = 0;

        for (let i = 29; i >= 0; i--) {
            const d = new Date(today);
            d.setDate(d.getDate() - i);
            const dateStr = d.toISOString().split('T')[0];
            const count = heatmapData[dateStr] || 0;
            if (count > 0) {
                totalActiveDays++;
                totalEvents += count;
            }
            days.push({ date: dateStr, count: count });
        }

        document.getElementById('perfil-heatmap-active-days').innerText = `${totalActiveDays} días activos`;

        let html = '';
        days.forEach(day => {
            let color = 'rgba(255,255,255,0.05)';
            if (day.count >= 4) color = '#a6e3a1';
            else if (day.count >= 2) color = '#94e2d5';
            else if (day.count === 1) color = '#89b4fa';

            html += `<div title="${day.date}: ${day.count} actividades completadas" style="width: 16px; height: 16px; border-radius: 3px; background: ${color}; cursor: pointer; transition: transform 0.2s ease;"></div>`;
        });

        container.innerHTML = html;
    }

    renderSkillTree(masteredTopics, competencies) {
        const topicsListEl = document.getElementById('perfil-topics-list');
        const compListEl = document.getElementById('perfil-competencies-list');

        if (topicsListEl) {
            if (masteredTopics.length === 0) {
                topicsListEl.innerHTML = `<div style="color:var(--text-muted); font-size: 12px; font-style: italic; padding: 10px 0;">No hay temas dominados aún. Completa bloques en Recorrido o Seguimiento para sumarlos.</div>`;
            } else {
                let html = '';
                masteredTopics.forEach(t => {
                    html += `
                        <div style="background: rgba(166, 227, 161, 0.08); border: 1px solid rgba(166, 227, 161, 0.3); border-radius: 6px; padding: 6px 10px; font-size: 12px; display: flex; align-items: center; justify-content: space-between;">
                            <span style="color: #fff; font-weight: 500;"><i class="fa-solid fa-circle-check" style="color: var(--accent-green);"></i> ${t.topic}</span>
                            <span style="color: var(--text-muted); font-size: 10px;">${t.source_goal || 'Seguimiento'}</span>
                        </div>
                    `;
                });
                topicsListEl.innerHTML = html;
            }
        }

        if (compListEl) {
            if (competencies.length === 0) {
                compListEl.innerHTML = `<div style="color:var(--text-muted); font-size: 12px; font-style: italic; padding: 10px 0;">No hay competencias registradas aún.</div>`;
            } else {
                let html = '';
                competencies.forEach(c => {
                    html += `
                        <div style="background: rgba(203, 166, 247, 0.08); border: 1px solid rgba(203, 166, 247, 0.3); border-radius: 6px; padding: 8px 10px; font-size: 12px; display: flex; flex-direction: column; gap: 4px;">
                            <div style="color: var(--accent-purple); font-weight: 600;"><i class="fa-solid fa-award"></i> ${c.title}</div>
                            ${c.objective ? `<div style="color: var(--text-muted); font-size: 11px;">🎯 <b>Objetivo:</b> ${c.objective}</div>` : ''}
                            ${c.check ? `<div style="color: var(--accent-yellow); font-size: 11px;">⚡ <b>Hito:</b> ${c.check}</div>` : ''}
                        </div>
                    `;
                });
                compListEl.innerHTML = html;
            }
        }
    }
}

// Global initialization
window.perfilMgr = new PerfilManager();

// El Perfil se abre como pestaña del área de trabajo (Ctrl+4) y así también carga sus datos
document.addEventListener('prig:herramienta-abierta', (e) => {
    if (e.detail && e.detail.modalId === 'modal-perfil' && window.perfilMgr) window.perfilMgr.loadDataset();
});

window.openPerfilModal = function() {
    if (window.perfilMgr) {
        window.perfilMgr.openModal();
    } else {
        window.perfilMgr = new PerfilManager();
        window.perfilMgr.openModal();
    }
};

window.closePerfilModal = function() {
    if (window.perfilMgr) window.perfilMgr.closeModal();
};
