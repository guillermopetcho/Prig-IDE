/**
 * Bloque de plan de estudio en la barra superior.
 *
 * Ocupa el sitio donde antes estaba el estado de Ollama, que bajó junto a CPU y GPU
 * porque es información de máquina, no de aprendizaje. Aquí arriba va lo que importa
 * mientras trabajas: en qué bloque estás y cuánto llevas.
 */
class PlanActualManager {
    constructor() {
        this.ruta = null;
        this.CLAVE = 'prig_plan_actual';
    }

    async init() {
        this.boton = document.getElementById('plan-actual');
        this.texto = document.getElementById('plan-actual-texto');
        this.detalle = document.getElementById('plan-actual-detalle');
        if (!this.boton) return;

        this.boton.onclick = () => window.PrigCommands.ejecutar('herr.guiado');
        this.boton.onmouseenter = () => this.mostrarDetalle();
        this.boton.onmouseleave = () => this.ocultarDetalle();
        this.detalle.onmouseenter = () => { clearTimeout(this._t); };
        this.detalle.onmouseleave = () => this.ocultarDetalle();

        await this.refrescar();
    }

    /** Ruta elegida por el usuario, o la más reciente si no eligió ninguna */
    async refrescar() {
        try {
            const payload = await prigJson(await fetch('/api/guided/list'));
            const rutas = payload.paths || [];
            if (!rutas.length) { this.ruta = null; this.pintar(); return; }

            const preferida = localStorage.getItem(this.CLAVE);
            const resumen = rutas.find(r => r.id === preferida) || rutas[0];
            this.ruta = await prigJson(await fetch(`/api/guided/${encodeURIComponent(resumen.id)}`));
        } catch (e) {
            this.ruta = null;
        }
        this.pintar();
    }

    fijar(id) {
        try { localStorage.setItem(this.CLAVE, id); } catch (e) { /* sin persistencia */ }
        this.refrescar();
    }

    _bloqueActual() {
        if (!this.ruta || !this.ruta.blocks || !this.ruta.blocks.length) return null;
        const hechos = new Set(this.ruta.completed_blocks || []);
        return this.ruta.blocks.find(b => !hechos.has(b.block_id)) || null;
    }

    _progreso() {
        if (!this.ruta || !this.ruta.blocks || !this.ruta.blocks.length) return 0;
        return Math.round(((this.ruta.completed_blocks || []).length / this.ruta.blocks.length) * 100);
    }

    pintar() {
        if (!this.texto) return;

        if (!this.ruta) {
            this.texto.textContent = 'Sin aprendizaje guiado';
            this.boton.classList.remove('con-plan');
            this.boton.title = 'Crear una ruta de aprendizaje';
            return;
        }

        const bloque = this._bloqueActual();
        const pct = this._progreso();
        this.texto.textContent = bloque ? bloque.title : 'Ruta completada';
        this.boton.classList.add('con-plan');
        this.boton.title = `${this.ruta.goal} · ${pct}% completado`;

        // Aro de progreso alrededor del icono
        this.boton.style.setProperty('--pct', `${pct}%`);
    }

    mostrarDetalle() {
        if (!this.detalle) return;
        clearTimeout(this._t);

        if (!this.ruta) {
            this.detalle.innerHTML = `
                <div class="plan-det-titulo">Sin aprendizaje guiado</div>
                <div class="plan-det-texto">
                    No tienes ninguna ruta creada todavía. Pulsa aquí para generar una:
                    Prig ordena tus temas en bloques con objetivos y una comprobación práctica.
                </div>`;
            this.detalle.hidden = false;
            return;
        }

        const esc = (t) => String(t ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;');
        const bloque = this._bloqueActual();
        const pct = this._progreso();
        const hechos = (this.ruta.completed_blocks || []).length;
        const total = (this.ruta.blocks || []).length;
        const modo = { rapido: 'Rápida', profundo: 'Profunda', migrado: 'Migrada' }[this.ruta.source] || this.ruta.source;

        this.detalle.innerHTML = `
            <div class="plan-det-titulo">${esc(this.ruta.goal)}</div>
            <div class="plan-det-barra"><div style="width:${pct}%"></div></div>
            <div class="plan-det-cifras">
                <span><b>${pct}%</b> completado</span>
                <span>${hechos} de ${total} bloques</span>
                <span class="plan-det-modo">${esc(modo)}</span>
            </div>
            ${bloque ? `
                <div class="plan-det-sep"></div>
                <div class="plan-det-etiqueta">Bloque actual</div>
                <div class="plan-det-bloque">${esc(bloque.title)}</div>
                ${bloque.learning_objective ? `<div class="plan-det-texto">🎯 ${esc(bloque.learning_objective)}</div>` : ''}
                ${bloque.validation_check ? `<div class="plan-det-texto">⚡ ${esc(bloque.validation_check)}</div>` : ''}
                ${(bloque.topics || []).length ? `<div class="plan-det-temas">${bloque.topics.slice(0, 5).map(t => `<span>${esc(t)}</span>`).join('')}</div>` : ''}
            ` : `<div class="plan-det-texto" style="color: var(--accent-green);">✓ Has completado todos los bloques.</div>`}
            <div class="plan-det-pie">Clic para abrir Aprendizaje Guiado</div>`;
        this.detalle.hidden = false;
    }

    ocultarDetalle() {
        this._t = setTimeout(() => { if (this.detalle) this.detalle.hidden = true; }, 180);
    }
}

window.planActualMgr = new PlanActualManager();
