/**
 * Avance del alumno dentro del Perfil.
 *
 * Junta en una sola vista lo que antes estaba suelto: los desafíos (con su historial
 * completo), los bloques del plan de estudios, los ejercicios y la biblioteca. Desde
 * aquí se vuelve a cualquier desafío y se practica lo que está flojo, para que el
 * recorrido sea continuo en vez de una colección de actividades sin relación.
 *
 * El análisis lo escribe un modelo de razonamiento (local o Gemini) a partir de datos
 * MEDIDOS —pruebas ejecutadas, intentos, pistas—, nunca de impresiones.
 */
(function () {
    const $ = (id) => document.getElementById(id);
    const esc = (t) => String(t ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
    const json = (url, opciones) => window.prigFetchJson(url, opciones);

    const ESTADOS = {
        nuevo: ['Sin empezar', 'fa-circle', 'var(--text-muted)'],
        en_curso: ['En curso', 'fa-circle-half-stroke', 'var(--accent-blue)'],
        resuelto: ['Resuelto', 'fa-circle-check', 'var(--accent-green)'],
        rendido: ['Visto con solución', 'fa-flag', 'var(--accent-yellow)'],
    };
    const FUENTES = { exercism: 'Exercism', thealgorithms: 'TheAlgorithms', projecteuler: 'Project Euler', modelo: 'Modelo', plan: 'Plan de estudios' };

    const estado = { resumen: null, historial: null, filtros: { estado: '', concepto: '', fuente: '' }, analisis: null, modelos: [] };

    function fecha(t) {
        if (!t) return '';
        const dias = Math.floor((Date.now() - new Date(t)) / 86400000);
        return dias <= 0 ? 'hoy' : dias === 1 ? 'ayer' : dias < 30 ? `hace ${dias} días` : new Date(t).toLocaleDateString('es');
    }

    const duracion = (s) => !s ? '' : s < 90 ? `${Math.round(s)} s` : `${Math.round(s / 60)} min`;

    function md(texto) {
        let html = window.marked ? window.marked.parse(String(texto || '')) : `<pre>${esc(texto)}</pre>`;
        if (window.DOMPurify) html = DOMPurify.sanitize(html, { USE_PROFILES: { html: true } });
        return html;
    }

    function estilos() {
        if ($('prog-estilos')) return;
        const css = document.createElement('style');
        css.id = 'prog-estilos';
        css.textContent = `
          .prog-caja { grid-column: 1 / -1; background: rgba(0,0,0,0.2); border: 1px solid var(--border-color); border-radius: 10px; padding: 16px; }
          .prog-titulo { display:flex; align-items:center; gap:8px; font-size:14px; color:var(--accent-purple); margin:0 0 12px; flex-wrap:wrap; }
          .prog-tarjetas { display:grid; grid-template-columns:repeat(auto-fit,minmax(130px,1fr)); gap:10px; }
          .prog-tarjeta { background:rgba(255,255,255,.04); border:1px solid var(--border-color); border-radius:8px; padding:9px 11px; }
          .prog-tarjeta b { display:block; font-size:19px; color:#fff; }
          .prog-tarjeta span { font-size:11px; color:var(--text-muted); }
          .prog-barra { height:8px; border-radius:4px; background:rgba(255,255,255,.07); overflow:hidden; }
          .prog-barra > div { height:100%; background:var(--accent-green); }
          .prog-fila { display:flex; align-items:center; gap:8px; font-size:12px; margin-top:8px; }
          .prog-tabla { width:100%; border-collapse:collapse; font-size:11.5px; }
          .prog-tabla th { text-align:left; color:var(--text-muted); font-weight:500; font-size:10.5px; padding:4px 6px; border-bottom:1px solid var(--border-color); }
          .prog-tabla td { padding:4px 6px; border-bottom:1px solid rgba(255,255,255,.05); }
          .prog-tabla tr[data-id] { cursor:pointer; }
          .prog-tabla tr[data-id]:hover td { background:rgba(137,180,250,.08); }
          .prog-chip { font-size:10px; padding:1px 7px; border-radius:9px; background:rgba(255,255,255,.07); color:var(--text-muted); white-space:nowrap; }
          .prog-btn { background:rgba(255,255,255,.05); color:var(--text-main); border:1px solid var(--border-color); border-radius:6px; padding:4px 9px; font-size:11px; cursor:pointer; white-space:nowrap; }
          .prog-btn:hover:not(:disabled) { border-color:var(--accent-blue); }
          .prog-btn.morado { background:rgba(203,166,247,.15); border-color:rgba(203,166,247,.45); color:var(--accent-purple); }
          .prog-btn.verde { background:var(--accent-green); border-color:var(--accent-green); color:#11111b; font-weight:600; }
          .prog-campo { background:var(--bg-dark); color:var(--text-main); border:1px solid var(--border-color); border-radius:6px; padding:3px 7px; font-size:11px; }
          .prog-ayuda { font-size:11px; color:var(--text-muted); line-height:1.5; }
          .prog-md { font-size:12.5px; line-height:1.6; color:var(--text-main); }
          .prog-md h2 { font-size:13px; color:var(--accent-purple); margin:12px 0 4px; }
          .prog-md ul { padding-left:20px; margin:6px 0; }
          .prog-concepto { display:grid; grid-template-columns:minmax(90px,1fr) 70px auto; gap:8px; align-items:center; font-size:11.5px; margin-top:6px; }
        `;
        document.head.appendChild(css);
    }

    /** Se inyecta al principio del perfil, antes de las secciones antiguas */
    async function render(contenedor) {
        estilos();
        let caja = $('perfil-progreso');
        if (!caja) {
            caja = document.createElement('div');
            caja.id = 'perfil-progreso';
            caja.className = 'prog-caja';
            caja.style.gridColumn = '1 / -1';
            contenedor.insertBefore(caja, contenedor.firstChild);
        }
        caja.innerHTML = '<div class="prog-ayuda"><i class="fa-solid fa-spinner fa-spin"></i> Reuniendo tu avance…</div>';
        try {
            const [r, h, a] = await Promise.all([
                json('/api/progreso/resumen'),
                json('/api/progreso/historial?limite=300'),
                json('/api/progreso/analisis').catch(() => ({ analisis: null })),
            ]);
            estado.resumen = r;
            estado.historial = h.desafios;
            estado.analisis = a.analisis;
        } catch (e) {
            caja.innerHTML = `<div class="prog-ayuda" style="color:var(--accent-red);">No se pudo cargar el avance: ${esc(e.message)}</div>`;
            return;
        }
        pintar(caja);
    }

    function pintar(caja) {
        const r = estado.resumen;
        const d = r.desafios;
        caja.innerHTML = `
          <h4 class="prog-titulo"><i class="fa-solid fa-chart-line"></i> Tu avance
            <span class="prog-ayuda" style="text-transform:none;">Desafíos, plan de estudios y ejercicios en un solo sitio</span>
            <span style="flex:1"></span>
            <button class="prog-btn" id="prog-recargar" title="Volver a calcular"><i class="fa-solid fa-rotate"></i></button></h4>

          <div class="prog-tarjetas">
            <div class="prog-tarjeta"><b>${d.por_estado.resuelto || 0}</b><span>desafíos resueltos de ${d.total}</span></div>
            <div class="prog-tarjeta"><b>${d.resueltos_sin_pistas}</b><span>resueltos sin pistas</span></div>
            <div class="prog-tarjeta"><b>${r.racha.actual}</b><span>días seguidos (mejor: ${r.racha.mejor})</span></div>
            <div class="prog-tarjeta"><b>${d.minutos}</b><span>minutos resolviendo</span></div>
            <div class="prog-tarjeta"><b>${d.media_intentos ?? '—'}</b><span>intentos por desafío</span></div>
            <div class="prog-tarjeta"><b>${d.con_razonamiento}</b><span>con caja de razonamiento</span></div>
          </div>

          <div style="margin-top:14px;">
            ${(r.actividades || []).map(a => `
              <div style="margin-top:8px;">
                <div class="prog-fila" style="margin:0;"><span style="flex:1;">${esc(a.nombre)}</span>
                  <span class="prog-ayuda">${a.hechos} de ${a.total}${a.detalle ? ' · ' + esc(a.detalle) : ''}</span></div>
                <div class="prog-barra" style="margin-top:3px;"><div style="width:${a.total ? Math.round(100 * a.hechos / a.total) : 0}%;"></div></div>
              </div>`).join('')}
          </div>

          <div style="display:grid; grid-template-columns:repeat(auto-fit,minmax(280px,1fr)); gap:16px; margin-top:16px;">
            <div>
              <div class="prog-ayuda" style="margin-bottom:4px;"><b>Dominio por concepto</b> · medido con las pruebas que pasaste</div>
              ${r.conceptos.length ? r.conceptos.slice(0, 10).map(c => `
                <div class="prog-concepto">
                  <span title="${c.vistos} desafíos · ${c.resueltos} resueltos · ${c.pistas} pistas">${esc(c.concepto)}</span>
                  <div class="prog-barra"><div style="width:${c.dominio}%; background:${c.dominio >= 70 ? 'var(--accent-green)' : c.dominio >= 40 ? 'var(--accent-yellow)' : 'var(--accent-red)'};"></div></div>
                  <button class="prog-btn" data-practicar="${esc(c.concepto)}" title="Practicar este concepto">${c.dominio}</button>
                </div>`).join('') : '<div class="prog-ayuda">Aún no hay conceptos medidos: resuelve algún desafío con pruebas.</div>'}
            </div>
            <div>
              <div class="prog-ayuda" style="margin-bottom:4px;"><b>Qué sigue</b> · a partir de tus datos</div>
              ${(r.siguientes || []).map((s, i) => `
                <div class="prog-fila"><i class="fa-${s.tipo === 'kaggle' ? 'brands fa-kaggle' : 'solid ' + (s.tipo === 'retomar' ? 'fa-play' : s.tipo === 'bloque' ? 'fa-route' : 'fa-dumbbell')}" style="color:var(--accent-blue);"></i>
                  <span style="flex:1;">${esc(s.texto)}</span>
                  <button class="prog-btn" data-siguiente="${i}">${s.tipo === 'retomar' || s.tipo === 'kaggle' ? 'Seguir' : 'Practicar'}</button></div>`).join('')
                || '<div class="prog-ayuda">Empieza un desafío y aquí aparecerá qué conviene hacer después.</div>'}
            </div>
          </div>

          <div style="margin-top:18px; border-top:1px dashed var(--border-color); padding-top:12px;">
            <div class="prog-fila" style="margin:0;"><b style="font-size:12.5px; color:#fff;">Análisis del tutor</b>
              <span class="prog-ayuda" id="prog-analisis-fecha"></span>
              <span style="flex:1"></span>
              <select id="prog-modelo" class="prog-campo" title="Modelo que analiza tu avance"></select>
              <button class="prog-btn morado" id="prog-analizar"><i class="fa-solid fa-brain"></i> Analizar mi avance</button></div>
            <div class="prog-md" id="prog-analisis" style="margin-top:8px;"></div>
            <div class="prog-fila" id="prog-analisis-temas" style="flex-wrap:wrap;"></div>
          </div>

          <div style="margin-top:18px; border-top:1px dashed var(--border-color); padding-top:12px;">
            <div class="prog-fila" style="margin:0;"><b style="font-size:12.5px; color:#fff;">Historial de desafíos</b>
              <span class="prog-ayuda" id="prog-historial-cuenta"></span>
              <span style="flex:1"></span>
              <select id="prog-f-estado" class="prog-campo"><option value="">Todos los estados</option>${Object.entries(ESTADOS).map(([k, v]) => `<option value="${k}">${v[0]}</option>`).join('')}</select>
              <select id="prog-f-fuente" class="prog-campo"><option value="">Todos los orígenes</option>${Object.entries(FUENTES).map(([k, v]) => `<option value="${k}">${v}</option>`).join('')}</select>
              <input id="prog-f-concepto" class="prog-campo" placeholder="Concepto o título" style="width:130px;"></div>
            <div style="max-height:320px; overflow:auto; margin-top:8px;"><table class="prog-tabla" id="prog-tabla"></table></div>
            <div class="prog-ayuda" style="margin-top:6px;">Pulsa cualquier fila para volver a abrir ese desafío.</div>
          </div>`;

        $('prog-recargar').onclick = () => render($('perfil-content-container'));
        caja.querySelectorAll('[data-practicar]').forEach(b => b.onclick = () => practicar(b.dataset.practicar));
        caja.querySelectorAll('[data-siguiente]').forEach(b => b.onclick = () => {
            const s = estado.resumen.siguientes[+b.dataset.siguiente];
            if (s.desafio_id) abrirDesafio(s.desafio_id);
            else if (s.tipo === 'kaggle' && window.KaggleLector) window.KaggleLector.abrir({ ref: s.ref, celda: s.celda });
            else if (s.ruta_id) abrirPlan(s);
            else practicar(s.tema);
        });
        ['estado', 'fuente', 'concepto'].forEach(f => {
            const el = $(`prog-f-${f}`);
            el.oninput = el.onchange = () => { estado.filtros[f] = el.value; pintarHistorial(); };
        });
        pintarHistorial();
        pintarAnalisis();
        cargarModelos();
        $('prog-analizar').onclick = () => analizar(false);
    }

    function pintarHistorial() {
        const t = $('prog-tabla');
        if (!t) return;
        const f = estado.filtros;
        const texto = (f.concepto || '').toLowerCase();
        const filas = estado.historial.filter(x =>
            (!f.estado || x.estado === f.estado) && (!f.fuente || x.fuente === f.fuente) &&
            (!texto || (x.titulo || '').toLowerCase().includes(texto) || (x.conceptos || []).some(c => c.toLowerCase().includes(texto))));
        $('prog-historial-cuenta').textContent = `${filas.length} de ${estado.historial.length}`;
        t.innerHTML = `<tr><th>Desafío</th><th>Estado</th><th>Origen</th><th>Pruebas</th><th>Intentos</th><th>Pistas</th><th>Tiempo</th><th>Cuándo</th></tr>` +
          (filas.length ? filas.map(x => {
              const [en, ie, ce] = ESTADOS[x.estado] || ESTADOS.nuevo;
              return `<tr data-id="${esc(x.id)}" title="${esc((x.conceptos || []).join(', '))}">
                <td><b style="color:#fff;">${esc(x.titulo)}</b>${x.bloque ? `<div class="prog-ayuda"><i class="fa-solid fa-route"></i> ${esc(x.bloque)}</div>` : ''}</td>
                <td style="color:${ce};"><i class="fa-solid ${ie}"></i> ${en}</td>
                <td>${esc(FUENTES[x.fuente] || x.fuente || '')}</td>
                <td>${x.verificable ? `${x.mejor.pasados}/${x.mejor.total || '?'}` : '<span class="prog-ayuda">sin pruebas</span>'}</td>
                <td>${x.intentos}</td><td>${x.pistas || ''}</td><td>${duracion(x.segundos)}</td>
                <td class="prog-ayuda">${fecha(x.actualizado || x.creado)}</td></tr>`;
          }).join('') : '<tr><td colspan="8" class="prog-ayuda" style="padding:10px;">Sin desafíos con esos filtros.</td></tr>');
        t.querySelectorAll('tr[data-id]').forEach(tr => tr.onclick = () => abrirDesafio(tr.dataset.id));
    }

    async function cargarModelos() {
        const sel = $('prog-modelo');
        if (!sel) return;
        const guardado = (() => { try { return localStorage.getItem('prig_desafios_modelo'); } catch (e) { return null; } })();
        let locales = [], nube = [];
        try { locales = (await json('/api/modelos')).modelos.filter(m => !m.capacidades.includes('embedding')).map(m => m.nombre); } catch (e) { /* sin Ollama */ }
        try {
            const g = await json('/api/gemini/estado');
            if (g.configurado) nube = (await json('/api/gemini/modelos')).modelos.map(m => `gemini:${m.id}`);
        } catch (e) { /* sin Gemini */ }
        estado.modelos = [...locales, ...nube];
        const elegido = estado.modelos.includes(guardado) ? guardado : estado.modelos[0] || '';
        sel.innerHTML = `${locales.length ? `<optgroup label="En tu equipo">${locales.map(m => `<option ${m === elegido ? 'selected' : ''}>${esc(m)}</option>`).join('')}</optgroup>` : ''}
          ${nube.length ? `<optgroup label="Google Gemini · nube">${nube.map(m => `<option value="${esc(m)}" ${m === elegido ? 'selected' : ''}>${esc(m.replace('gemini:', ''))} (Gemini)</option>`).join('')}</optgroup>` : ''}`;
        if (!estado.modelos.length) sel.innerHTML = '<option>sin modelos</option>';
    }

    function pintarAnalisis() {
        const cont = $('prog-analisis');
        const temas = $('prog-analisis-temas');
        const cuando = $('prog-analisis-fecha');
        if (!cont) return;
        const a = estado.analisis;
        if (!a) {
            cont.innerHTML = `<div class="prog-ayuda">El tutor lee tus datos (desafíos resueltos, intentos, pistas, dominio por concepto y bloques del plan)
              y te dice qué se te resiste y qué hacer en las próximas sesiones. Nada sale de tu equipo salvo que elijas un modelo Gemini.</div>`;
            temas.innerHTML = '';
            cuando.textContent = '';
            return;
        }
        cont.innerHTML = md(a.texto_visible !== undefined ? a.texto_visible : quitarJson(a.texto));
        cuando.textContent = `${fecha(a.fecha)} · ${a.modelo || ''} · con ${a.desafios} desafíos`;
        temas.innerHTML = (a.temas || []).map(t => `<button class="prog-btn verde" data-tema="${esc(t)}"><i class="fa-solid fa-dumbbell"></i> Practicar ${esc(t)}</button>`).join('');
        temas.querySelectorAll('[data-tema]').forEach(b => b.onclick = () => practicar(b.dataset.tema));
    }

    const quitarJson = (t) => String(t || '').replace(/```json[\s\S]*?```/g, '').trim();

    async function analizar(regenerar) {
        const boton = $('prog-analizar');
        const cont = $('prog-analisis');
        boton.disabled = true;
        boton.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Analizando…';
        let texto = '';
        try {
            const res = await fetch('/api/progreso/analisis', {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ modelo: $('prog-modelo').value, regenerar }),
            });
            if (!res.ok) throw new Error(await window.prigErrorDetail(res));
            const lector = res.body.getReader();
            const dec = new TextDecoder();
            let resto = '', fin = null;
            for (;;) {
                const { done, value } = await lector.read();
                if (done) break;
                resto += dec.decode(value, { stream: true });
                const partes = resto.split('\n');
                resto = partes.pop();
                for (const p of partes) {
                    if (!p.trim()) continue;
                    const ev = JSON.parse(p);
                    if (ev.tipo === 'error') throw new Error(ev.mensaje);
                    if (ev.tipo === 'fin') fin = ev.resultado;
                    else if (ev.tipo === 'texto') { texto += ev.delta; cont.innerHTML = md(quitarJson(texto)); }
                    else if (ev.tipo === 'pensando' && !texto) cont.innerHTML = '<div class="prog-ayuda"><i class="fa-solid fa-spinner fa-spin"></i> El tutor está razonando sobre tus datos…</div>';
                }
            }
            estado.analisis = fin;
            pintarAnalisis();
        } catch (e) {
            cont.innerHTML = `<div class="prog-ayuda" style="color:var(--accent-red);">${esc(e.message)}</div>`;
        } finally {
            boton.disabled = false;
            boton.innerHTML = '<i class="fa-solid fa-brain"></i> ' + (estado.analisis ? 'Volver a analizar' : 'Analizar mi avance');
            boton.onclick = () => analizar(true);
        }
    }

    // ------------------------------------------------------------------ enlaces con el resto
    /** El Perfil puede estar como ventana o como pestaña; en ambos casos se sale hacia Desafíos */
    function cerrarPerfil() {
        if (window.perfilMgr && window.perfilMgr.closeModal) window.perfilMgr.closeModal();
        else if (window.closePerfilModal) window.closePerfilModal();
    }

    function abrirDesafio(id) {
        cerrarPerfil();
        if (window.Desafios) window.Desafios.abrir({ id });
    }

    function practicar(tema) {
        cerrarPerfil();
        if (window.Desafios) window.Desafios.abrir({ tema });
    }

    function abrirPlan(s) {
        cerrarPerfil();
        if (window.Desafios) window.Desafios.abrir({ rutaId: s.ruta_id, bloqueId: s.bloque_id });
    }

    window.ProgresoPerfil = { render, estado };
})();
