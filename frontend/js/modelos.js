/**
 * Modelos: todo lo configurable de Ollama al alcance del usuario.
 *
 * Solo aparece lo que se verificó en esta máquina midiendo su efecto. Lo que dio
 * error o no hacía nada está en la pestaña "No incluidas", con el motivo.
 *
 *   Ajustes      opciones por capas: todos los modelos → este modelo → uso → modelo en uso
 *   Probar       una petición con cualquier opción: formato JSON, razonamiento,
 *                confianza por token, sin plantilla, relleno al medio; comparar A/B
 *   Ficha        capacidades, parámetros de fábrica, plantilla, licencia, Modelfile, tensores
 *   Gestionar    crear variantes, copiar, eliminar, importar GGUF, actualizaciones, descargas a medias
 *   Cargados     modelos en memoria; precargar y descargar
 *   Servidor     variables de entorno de Ollama y su registro
 *   Embeddings   modelo, dimensiones y truncado del índice semántico
 */
(function () {
    const $ = (id) => document.getElementById(id);
    const esc = (t) => String(t ?? '').replace(/[&<>"']/g,
        (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
    const json = (url, opciones) => window.prigFetchJson(url, opciones);
    const post = (url, cuerpo) => json(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(cuerpo) });
    const gb = (b) => b ? `${(b / 1e9).toFixed(b >= 1e10 ? 0 : 1)} GB` : '—';

    const estado = {
        catalogo: null, modelos: [], modelo: null, pestana: 'ajustes',
        capa: 'modelo', uso: 'tutor', config: null, resultadoA: null, temporizadorCargados: null,
    };
    const PESTANAS = [
        ['ajustes', 'fa-sliders', 'Ajustes'], ['probar', 'fa-flask', 'Probar'], ['ficha', 'fa-id-card', 'Ficha'],
        ['gestionar', 'fa-toolbox', 'Gestionar'], ['cargados', 'fa-memory', 'Cargados'],
        ['servidor', 'fa-server', 'Servidor'], ['embeddings', 'fa-diagram-project', 'Embeddings'],
        ['excluidas', 'fa-ban', 'No incluidas'],
    ];
    const CAPS = {
        completion: ['texto', 'fa-comment'], thinking: ['piensa', 'fa-lightbulb'], tools: ['herramientas', 'fa-screwdriver-wrench'],
        insert: ['rellena al medio', 'fa-i-cursor'], embedding: ['embeddings', 'fa-diagram-project'], vision: ['visión', 'fa-eye'],
    };

    // ------------------------------------------------------------------ estilos
    function estilos() {
        if ($('modelos-estilos')) return;
        const css = document.createElement('style');
        css.id = 'modelos-estilos';
        css.textContent = `
          #modelos-raiz { display:flex; height:100%; min-height:0; font-size:12px; color:var(--text-main,#cdd6f4); }
          #modelos-lista { width:250px; flex-shrink:0; border-right:1px solid var(--border-color); overflow:auto; padding:8px; }
          #modelos-principal { flex:1; min-width:0; display:flex; flex-direction:column; }
          #modelos-pestanas { display:flex; gap:2px; padding:6px 8px 0; border-bottom:1px solid var(--border-color); flex-wrap:wrap; }
          #modelos-pestanas button { background:none; border:none; border-bottom:2px solid transparent; color:var(--text-muted); padding:6px 10px; cursor:pointer; font-size:12px; }
          #modelos-pestanas button.activa { color:var(--accent-blue); border-bottom-color:var(--accent-blue); }
          #modelos-cuerpo { flex:1; overflow:auto; padding:12px 16px; }
          .mod-item { padding:7px 8px; border-radius:6px; cursor:pointer; margin-bottom:3px; border:1px solid transparent; }
          .mod-item:hover { background:rgba(255,255,255,.04); }
          .mod-item.activo { background:rgba(137,180,250,.12); border-color:rgba(137,180,250,.35); }
          .mod-caps { display:flex; gap:4px; flex-wrap:wrap; margin-top:3px; }
          .mod-cap { font-size:9.5px; padding:0 5px; border-radius:8px; background:rgba(255,255,255,.07); color:var(--text-muted); }
          .mod-seccion { margin-bottom:16px; }
          .mod-titulo { font-weight:600; font-size:12.5px; margin:0 0 8px; color:#eee; display:flex; align-items:center; gap:8px; }
          .mod-fila { display:grid; grid-template-columns: 22px minmax(150px, 1.1fr) minmax(140px, 1fr) minmax(150px, 1.2fr); gap:8px; align-items:center; padding:5px 0; border-bottom:1px solid rgba(255,255,255,.05); }
          .mod-fila input[type=text], .mod-fila input[type=number], .mod-fila select, .mod-campo { width:100%; box-sizing:border-box; padding:4px 6px; background:var(--bg-panel); color:#fff; border:1px solid var(--border-color); border-radius:4px; font-size:12px; font-family:inherit; }
          .mod-campo option, .mod-fila select option { background-color: #1e1e2e !important; color: #cdd6f4 !important; }
          .mod-campo optgroup, .mod-fila select optgroup { background-color: #181825 !important; color: #89b4fa !important; }
          .mod-fila input:disabled, .mod-fila select:disabled { opacity:.45; }
          .mod-efectivo { font-size:10.5px; color:var(--text-muted); }
          .mod-efectivo b { color:var(--text-main,#cdd6f4); font-weight:600; }
          .mod-boton { padding:5px 11px; border-radius:5px; cursor:pointer; font-size:11.5px; background:rgba(137,180,250,.15); color:var(--accent-blue); border:1px solid rgba(137,180,250,.35); }
          .mod-boton.peligro { background:rgba(243,139,168,.12); color:var(--accent-red); border-color:rgba(243,139,168,.4); }
          .mod-boton.ok { background:rgba(166,227,161,.12); color:var(--accent-green); border-color:rgba(166,227,161,.4); }
          .mod-boton:disabled { opacity:.45; cursor:default; }
          .mod-caja { background:rgba(0,0,0,.18); border-radius:7px; padding:10px 12px; margin-bottom:10px; }
          .mod-pre { white-space:pre-wrap; font-family:'Fira Code',monospace; font-size:11px; background:rgba(0,0,0,.25); padding:8px; border-radius:5px; max-height:300px; overflow:auto; margin:4px 0; }
          .mod-tabla { width:100%; border-collapse:collapse; font-size:11.5px; }
          .mod-tabla td, .mod-tabla th { padding:4px 8px; text-align:left; border-bottom:1px solid rgba(255,255,255,.05); }
          .mod-tabla th { color:var(--text-muted); font-weight:500; font-size:10.5px; }
          .mod-ayuda { color:var(--text-muted); font-size:10.5px; line-height:1.4; }
          .mod-aviso { padding:6px 10px; border-radius:5px; background:rgba(249,226,175,.08); border-left:3px solid var(--accent-yellow); color:var(--accent-yellow); margin:6px 0; font-size:11px; }
          .mod-error { padding:6px 10px; border-radius:5px; background:rgba(243,139,168,.08); border-left:3px solid var(--accent-red); color:var(--accent-red); margin:6px 0; font-size:11px; }
          .mod-barra { height:6px; background:rgba(255,255,255,.08); border-radius:3px; overflow:hidden; }
          .mod-barra > div { height:100%; background:var(--accent-blue); }
          .mod-capas button { padding:4px 9px; border-radius:4px; cursor:pointer; font-size:11px; background:transparent; color:var(--text-muted); border:1px solid var(--border-color); }
          .mod-capas button.activa { background:rgba(203,166,247,.15); color:var(--accent-purple); border-color:var(--accent-purple); }
          .mod-2col { display:grid; grid-template-columns:1fr 1fr; gap:12px; }
          @media (max-width: 900px) { .mod-2col { grid-template-columns:1fr; } .mod-fila { grid-template-columns: 22px 1fr; } }
        `;
        document.head.appendChild(css);
    }

    // ------------------------------------------------------------------ abrir
    async function abrir(pestana) {
        if (window.workArea) window.workArea.abrirHerramienta('modal-modelos', 'Modelos', 'fa-cubes');
        estilos();
        const cont = document.querySelector('#modal-modelos .modal-content, .modal-content[data-modal-origen="modal-modelos"]');
        if (!cont) return;
        if (!$('modelos-raiz')) {
            cont.innerHTML = `<div id="modelos-raiz">
                <div id="modelos-lista"><div class="mod-ayuda">Cargando modelos…</div></div>
                <div id="modelos-principal">
                  <div id="modelos-pestanas">${PESTANAS.map(([id, ic, t]) => `<button data-p="${id}"><i class="fa-solid ${ic}"></i> ${t}</button>`).join('')}</div>
                  <div id="modelos-cuerpo"></div>
                </div></div>`;
            $('modelos-pestanas').onclick = (e) => { const b = e.target.closest('button'); if (b) cambiarPestana(b.dataset.p); };
        }
        if (pestana) estado.pestana = pestana;
        try {
            if (!estado.catalogo) estado.catalogo = await json('/api/modelos/catalogo');
            await cargarModelos();
        } catch (e) {
            $('modelos-lista').innerHTML = `<div class="mod-error">${esc(e.message)}</div>`;
        }
        cambiarPestana(estado.pestana);
    }

    async function cargarModelos() {
        const d = await json('/api/modelos');
        estado.modelos = d.modelos.sort((a, b) => a.nombre.localeCompare(b.nombre));
        if (!estado.modelo || !estado.modelos.some(m => m.nombre === estado.modelo)) {
            const preferido = (window.aiConfig && window.aiConfig.agent1_model) || '';
            estado.modelo = (estado.modelos.find(m => m.nombre === preferido) || estado.modelos.find(m => !m.capacidades.includes('embedding')) || estado.modelos[0] || {}).nombre || null;
        }
        pintarLista(d.disco);
    }

    function pintarLista(disco) {
        const lista = $('modelos-lista');
        lista.innerHTML = `<div class="mod-ayuda" style="margin-bottom:6px;">${estado.modelos.length} modelos · ${gb(disco && disco.bytes)} en disco</div>` +
            estado.modelos.map(m => `<div class="mod-item ${m.nombre === estado.modelo ? 'activo' : ''}" data-m="${esc(m.nombre)}">
                <div style="display:flex; align-items:center; gap:6px;">
                  ${m.cargado ? '<i class="fa-solid fa-circle" title="Cargado en memoria" style="color:var(--accent-green); font-size:7px;"></i>' : ''}
                  <b style="overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">${esc(m.nombre)}</b></div>
                <div class="mod-ayuda">${esc(m.parametros || '')} · ${esc(m.cuantizacion || '')} · ${gb(m.bytes)}</div>
                <div class="mod-caps">${m.capacidades.filter(c => c !== 'completion').map(c => `<span class="mod-cap"><i class="fa-solid ${(CAPS[c] || [c, 'fa-tag'])[1]}"></i> ${(CAPS[c] || [c])[0]}</span>`).join('')}</div>
              </div>`).join('');
        lista.querySelectorAll('.mod-item').forEach(el => el.onclick = () => {
            estado.modelo = el.dataset.m;
            estado.resultadoA = null;
            pintarLista(disco);
            cambiarPestana(estado.pestana);
        });
    }

    const modeloActual = () => estado.modelos.find(m => m.nombre === estado.modelo);

    function cambiarPestana(p) {
        estado.pestana = p;
        clearInterval(estado.temporizadorCargados);
        $('modelos-pestanas').querySelectorAll('button').forEach(b => b.classList.toggle('activa', b.dataset.p === p));
        // Cada pestaña pinta en su propio contenedor. Si el usuario cambia de pestaña o
        // de modelo antes de que llegue la respuesta, el contenedor viejo ya no está en
        // la página y lo que pinte tarde no pisa a la pestaña nueva.
        const cuerpo = document.createElement('div');
        cuerpo.innerHTML = '<div class="mod-ayuda"><i class="fa-solid fa-spinner fa-spin"></i> Cargando…</div>';
        $('modelos-cuerpo').replaceChildren(cuerpo);
        const f = RENDER[p] || RENDER.ajustes;
        Promise.resolve(f(cuerpo)).catch(e => { if (cuerpo.isConnected) cuerpo.innerHTML = `<div class="mod-error">${esc(e.message)}</div>`; });
    }

    // ================================================================== AJUSTES
    async function ajustes(cuerpo) {
        const cat = estado.catalogo;
        const m = modeloActual();
        const necesitaModelo = estado.capa === 'modelo' || estado.capa === 'modelo_uso';
        if (necesitaModelo && !m) { cuerpo.innerHTML = '<div class="mod-ayuda">Elige un modelo a la izquierda.</div>'; return; }
        const q = new URLSearchParams();
        if (m) q.set('modelo', m.nombre);
        if (estado.capa === 'uso' || estado.capa === 'modelo_uso') q.set('uso', estado.uso);
        const cfg = await json(`/api/modelos/config?${q}`);
        if (!cuerpo.isConnected) return;
        estado.config = cfg;
        const capaValores = cfg.capas[estado.capa] || {};
        const efectivo = { ...cfg.efectivo.opciones, ...cfg.efectivo.campos };
        const origenes = cfg.efectivo.origen;
        const caps = m ? m.capacidades : [];
        const NOMBRE_CAPA = { global: 'todos los modelos', modelo: 'este modelo', uso: 'este uso', modelo_uso: 'este modelo en este uso' };

        const control = (o) => {
            const valor = o.clave in capaValores ? capaValores[o.clave] : (o.clave in efectivo ? efectivo[o.clave] : '');
            const fijado = o.clave in capaValores;
            const dis = fijado ? '' : 'disabled';
            if (o.tipo === 'bool') {
                return `<select data-k="${o.clave}" ${dis}><option value="true" ${valor === true ? 'selected' : ''}>Sí</option><option value="false" ${valor === false ? 'selected' : ''}>No</option></select>`;
            }
            if (o.tipo === 'lista') return `<input type="text" data-k="${o.clave}" ${dis} value="${esc(Array.isArray(valor) ? valor.join(' | ') : valor)}" placeholder="separados por |">`;
            if (o.tipo === 'texto') return `<textarea class="mod-campo" rows="2" data-k="${o.clave}" ${dis}>${esc(valor)}</textarea>`;
            if (o.tipo === 'duracion') return `<input type="text" data-k="${o.clave}" ${dis} value="${esc(valor)}" placeholder="5m, 30m, 0, -1">`;
            return `<input type="number" data-k="${o.clave}" ${dis} min="${o.min}" max="${o.max}" step="${o.paso}" value="${esc(valor)}">`;
        };
        const fila = (o) => {
            const fijado = o.clave in capaValores;
            const delModelo = cfg.del_modelo && cfg.del_modelo[o.clave];
            const ef = o.clave in efectivo
                ? `efectivo <b>${esc(JSON.stringify(efectivo[o.clave]))}</b> (${esc(NOMBRE_CAPA[origenes[o.clave]] || origenes[o.clave])})`
                : (delModelo !== undefined ? `usa el del modelo: <b>${esc(Array.isArray(delModelo) ? delModelo.join(' | ') : delModelo)}</b>`
                   : (o.clave in (cfg.configuracion_ia || {}) ? `configuración de IA: <b>${esc(cfg.configuracion_ia[o.clave])}</b>` : 'sin fijar: lo decide el modelo'));
            return `<div class="mod-fila">
                <input type="checkbox" data-fijar="${o.clave}" ${fijado ? 'checked' : ''} title="Fijar en ${NOMBRE_CAPA[estado.capa]}">
                <div><div>${esc(o.nombre)} <i class="fa-regular fa-circle-question" style="color:var(--text-muted);" title="${esc(o.ayuda + '\n\nVerificado: ' + o.prueba)}"></i></div>
                     <div class="mod-ayuda" style="font-family:'Fira Code',monospace;">${o.clave}</div></div>
                <div>${control(o)}</div>
                <div class="mod-efectivo">${ef}</div></div>`;
        };
        const grupos = {};
        [...cat.opciones, ...cat.campos].forEach(o => {
            if (o.requiere && !caps.includes(o.requiere) && necesitaModelo) return;
            (grupos[o.grupo] = grupos[o.grupo] || []).push(o);
        });

        cuerpo.innerHTML = `
          <div class="mod-seccion">
            <div class="mod-titulo">Dónde se aplica</div>
            <div class="mod-capas" style="display:flex; gap:4px; flex-wrap:wrap; align-items:center;">
              ${[['global', 'Todos los modelos'], ['modelo', `Solo ${m ? m.nombre : 'este modelo'}`], ['uso', 'Un uso'], ['modelo_uso', 'Este modelo en un uso']]
                .map(([c, t]) => `<button data-capa="${c}" class="${estado.capa === c ? 'activa' : ''}">${esc(t)}</button>`).join('')}
              ${estado.capa === 'uso' || estado.capa === 'modelo_uso' ? `<select id="mod-uso" class="mod-campo" style="width:auto;">
                ${Object.entries(cat.usos).map(([id, n]) => `<option value="${id}" ${estado.uso === id ? 'selected' : ''}>${esc(n)}</option>`).join('')}</select>` : ''}
            </div>
            <div class="mod-ayuda" style="margin-top:6px;">Prioridad: todos los modelos → este modelo → uso → modelo en uso. Lo que no fijes en ninguna capa
              no se envía y Ollama usa lo que recomienda el modelo. Marca la casilla para fijar un valor aquí.</div>
          </div>
          <div class="mod-seccion" style="display:flex; gap:6px; flex-wrap:wrap; align-items:center;">
            <span class="mod-ayuda">Plantillas de muestreo:</span>
            ${Object.entries(cat.plantillas).map(([id, p]) => `<button class="mod-boton" data-plantilla="${id}" title="${esc(p.ayuda || JSON.stringify(p.valores))}">${esc(p.nombre)}</button>`).join('')}
          </div>
          ${Object.entries(grupos).map(([g, ops]) => `<div class="mod-seccion"><div class="mod-titulo">${esc(g)}</div>${ops.map(fila).join('')}</div>`).join('')}
          <div style="position:sticky; bottom:-12px; background:var(--bg-panel); padding:10px 0; display:flex; gap:8px; align-items:center; border-top:1px solid var(--border-color);">
            <button class="mod-boton ok" id="mod-guardar"><i class="fa-solid fa-floppy-disk"></i> Guardar en ${esc(NOMBRE_CAPA[estado.capa])}</button>
            <button class="mod-boton" id="mod-vaciar" title="Quita todo lo fijado en esta capa">Vaciar esta capa</button>
            ${m && !m.capacidades.includes('embedding') ? `<span style="flex:1"></span>
              <button class="mod-boton" id="mod-precargar"><i class="fa-solid fa-upload"></i> Precargar</button>
              <button class="mod-boton" id="mod-descargar"><i class="fa-solid fa-download"></i> Descargar de memoria</button>` : ''}
            <span id="mod-ajustes-msg" class="mod-ayuda"></span>
          </div>`;

        cuerpo.querySelectorAll('[data-capa]').forEach(b => b.onclick = () => { estado.capa = b.dataset.capa; cambiarPestana('ajustes'); });
        if ($('mod-uso')) $('mod-uso').onchange = (e) => { estado.uso = e.target.value; cambiarPestana('ajustes'); };
        cuerpo.querySelectorAll('[data-fijar]').forEach(chk => chk.onchange = () => {
            cuerpo.querySelectorAll(`[data-k="${chk.dataset.fijar}"]`).forEach(el => { el.disabled = !chk.checked; });
        });
        const destino = () => ({ capa: estado.capa, modelo: m ? m.nombre : null, uso: estado.uso });
        const msg = (t, error) => { const el = $('mod-ajustes-msg'); el.textContent = t; el.style.color = error ? 'var(--accent-red)' : 'var(--accent-green)'; };

        $('mod-guardar').onclick = async () => {
            const valores = {};
            [...cat.opciones, ...cat.campos].forEach(o => {
                const chk = cuerpo.querySelector(`[data-fijar="${o.clave}"]`);
                if (!chk) return;
                if (!chk.checked) { if (o.clave in capaValores) valores[o.clave] = null; return; }
                const el = cuerpo.querySelector(`[data-k="${o.clave}"]`);
                let v = el.value;
                if (o.tipo === 'bool') v = v === 'true';
                else if (o.tipo === 'int') v = parseInt(v, 10);
                else if (o.tipo === 'float') v = parseFloat(v);
                else if (o.tipo === 'lista') v = v.split('|').map(x => x.trim()).filter(Boolean);
                if ((o.tipo === 'int' || o.tipo === 'float') && Number.isNaN(v)) return;
                valores[o.clave] = v;
            });
            try {
                await post('/api/modelos/config', { ...destino(), valores });
                msg('Guardado');
                setTimeout(() => { if (estado.pestana === 'ajustes') cambiarPestana('ajustes'); }, 500);
            } catch (e) { msg(e.message, true); }
        };
        $('mod-vaciar').onclick = async () => {
            if (!confirm(`¿Quitar todo lo fijado en ${NOMBRE_CAPA[estado.capa]}?`)) return;
            try { await post('/api/modelos/config', { ...destino(), valores: {}, reemplazar: true }); cambiarPestana('ajustes'); }
            catch (e) { msg(e.message, true); }
        };
        cuerpo.querySelectorAll('[data-plantilla]').forEach(b => b.onclick = async () => {
            try { await post('/api/modelos/plantilla', { ...destino(), plantilla: b.dataset.plantilla }); cambiarPestana('ajustes'); }
            catch (e) { msg(e.message, true); }
        });
        if ($('mod-precargar')) $('mod-precargar').onclick = async (e) => {
            e.target.disabled = true; msg('Cargando en memoria…');
            try { await post('/api/modelos/precargar', { modelo: m.nombre, uso: estado.capa.includes('uso') ? estado.uso : null }); msg('Cargado'); await cargarModelos(); }
            catch (err) { msg(err.message, true); }
            e.target.disabled = false;
        };
        if ($('mod-descargar')) $('mod-descargar').onclick = async () => {
            try { await post('/api/modelos/descargar', { modelo: m.nombre }); msg('Descargado de memoria'); await cargarModelos(); }
            catch (err) { msg(err.message, true); }
        };
    }

    // ================================================================== PROBAR
    async function probar(cuerpo) {
        const m = modeloActual();
        if (!m) { cuerpo.innerHTML = '<div class="mod-ayuda">Elige un modelo.</div>'; return; }
        if (m.capacidades.includes('embedding')) { cuerpo.innerHTML = '<div class="mod-ayuda">Es un modelo de embeddings: pruébalo en la pestaña Embeddings.</div>'; return; }
        const piensa = m.capacidades.includes('thinking');
        const inserta = m.capacidades.includes('insert');
        cuerpo.innerHTML = `
          <div class="mod-2col">
            <div>
              <div class="mod-titulo">Petición a ${esc(m.nombre)}</div>
              <textarea id="pr-prompt" class="mod-campo" rows="5" placeholder="Escribe el mensaje…">Explica en tres frases qué es la regularización L2.</textarea>
              <details style="margin:6px 0;"><summary class="mod-ayuda" style="cursor:pointer;">Instrucciones de sistema</summary>
                <textarea id="pr-system" class="mod-campo" rows="3" placeholder="Opcional"></textarea></details>
              <div style="display:grid; grid-template-columns:1fr 1fr; gap:6px 10px; margin-top:6px;">
                <label class="mod-ayuda">Uso (capas)<select id="pr-uso" class="mod-campo"><option value="">Ninguno</option>
                  ${Object.entries(estado.catalogo.usos).map(([id, n]) => `<option value="${id}">${esc(n)}</option>`).join('')}</select></label>
                <label class="mod-ayuda">Semilla<input id="pr-seed" type="number" class="mod-campo" placeholder="aleatoria"></label>
                <label class="mod-ayuda">Temperatura<input id="pr-temp" type="number" class="mod-campo" step="0.05" min="0" max="2" placeholder="la del modelo"></label>
                <label class="mod-ayuda">Máx. tokens<input id="pr-predict" type="number" class="mod-campo" placeholder="la configurada"></label>
                <label class="mod-ayuda">Formato<select id="pr-formato" class="mod-campo"><option value="">Texto libre</option><option value="json">JSON</option><option value="esquema">Esquema JSON…</option></select></label>
                <label class="mod-ayuda">Confianza por token<select id="pr-logprobs" class="mod-campo"><option value="0">No</option><option value="1">Sí</option><option value="3">Sí, con 3 alternativas</option><option value="5">Sí, con 5 alternativas</option></select></label>
                ${piensa ? `<label class="mod-ayuda">Pensar<select id="pr-think" class="mod-campo"><option value="">Lo configurado</option><option value="true">Sí</option><option value="false">No</option></select></label>` : ''}
                <label class="mod-ayuda" style="display:flex; align-items:center; gap:6px; margin-top:14px;"><input type="checkbox" id="pr-raw"> Sin plantilla (raw)</label>
              </div>
              <textarea id="pr-esquema" class="mod-campo" rows="5" hidden style="margin-top:6px; font-family:'Fira Code',monospace;">{"type": "object", "properties": {"resumen": {"type": "string"}, "puntos": {"type": "array", "items": {"type": "string"}}}, "required": ["resumen", "puntos"]}</textarea>
              <details style="margin:6px 0;"><summary class="mod-ayuda" style="cursor:pointer;">Avanzado: plantilla propia${inserta ? ' y relleno al medio' : ''}</summary>
                <label class="mod-ayuda">Plantilla (Go template; ej. <code>{{ .Prompt }}</code>)<textarea id="pr-template" class="mod-campo" rows="2"></textarea></label>
                ${inserta ? `<label class="mod-ayuda">Texto después del cursor (suffix): el modelo escribe lo que va entre el mensaje y esto
                  <textarea id="pr-suffix" class="mod-campo" rows="2" style="font-family:'Fira Code',monospace;"></textarea></label>` : ''}
              </details>
              <div style="display:flex; gap:8px; margin-top:8px; align-items:center;">
                <button class="mod-boton ok" id="pr-enviar"><i class="fa-solid fa-play"></i> Probar</button>
                <button class="mod-boton" id="pr-fijar" hidden title="Guarda este resultado a la izquierda para compararlo con la siguiente prueba">Fijar como A para comparar</button>
                <span id="pr-estado" class="mod-ayuda"></span>
              </div>
            </div>
            <div id="pr-resultados"></div>
          </div>`;
        $('pr-formato').onchange = () => { $('pr-esquema').hidden = $('pr-formato').value !== 'esquema'; };
        let ultimo = null;
        $('pr-fijar').onclick = () => { estado.resultadoA = ultimo; pintarResultados(null); };
        const pintarResultados = (actual) => {
            const r = $('pr-resultados');
            const tarjeta = (res, titulo) => res ? `<div class="mod-caja"><div class="mod-titulo">${titulo}</div>${tarjetaResultado(res)}</div>` : '';
            r.innerHTML = (estado.resultadoA ? tarjeta(estado.resultadoA, 'A (fijado)') : '') + tarjeta(actual, estado.resultadoA ? 'B (actual)' : 'Resultado');
            r.querySelectorAll('[data-confianza]').forEach(b => b.onclick = () => {
                const destino = b.nextElementSibling;
                destino.hidden = !destino.hidden;
            });
        };
        if (estado.resultadoA) pintarResultados(null);
        $('pr-enviar').onclick = async () => {
            const opciones = {};
            const num = (id, clave, entero) => { const v = $(id).value; if (v !== '') opciones[clave] = entero ? parseInt(v, 10) : parseFloat(v); };
            num('pr-seed', 'seed', true); num('pr-temp', 'temperature'); num('pr-predict', 'num_predict', true);
            const cuerpoPeticion = { modelo: m.nombre, prompt: $('pr-prompt').value, system: $('pr-system').value || null,
                uso: $('pr-uso').value || null, opciones, logprobs: parseInt($('pr-logprobs').value, 10), raw: $('pr-raw').checked,
                template: $('pr-template').value || null, suffix: $('pr-suffix') ? ($('pr-suffix').value || null) : null };
            const f = $('pr-formato').value;
            if (f === 'json') cuerpoPeticion.format = 'json';
            if (f === 'esquema') cuerpoPeticion.format = $('pr-esquema').value;
            if ($('pr-think') && $('pr-think').value !== '') cuerpoPeticion.think = $('pr-think').value === 'true';
            $('pr-enviar').disabled = true;
            $('pr-estado').innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Generando…';
            try {
                ultimo = { ...(await post('/api/modelos/probar', cuerpoPeticion)), formato: f };
                pintarResultados(ultimo);
                $('pr-fijar').hidden = false;
                $('pr-estado').textContent = '';
            } catch (e) {
                $('pr-estado').innerHTML = `<span style="color:var(--accent-red);">${esc(e.message)}</span>`;
            }
            $('pr-enviar').disabled = false;
        };
    }

    function tarjetaResultado(r) {
        const mt = r.metricas || {};
        let valido = '';
        if (r.formato === 'json' || r.formato === 'esquema') {
            try { JSON.parse(r.respuesta); valido = '<span style="color:var(--accent-green);"><i class="fa-solid fa-check"></i> JSON válido</span>'; }
            catch (e) { valido = '<span style="color:var(--accent-red);">JSON no válido</span>'; }
        }
        const confianza = (r.logprobs || []).length ? `<button class="mod-boton" data-confianza style="margin-top:6px;">Ver confianza por token</button>
            <div hidden style="margin-top:6px; line-height:1.7;">${r.logprobs.map(p => {
                const prob = Math.exp(p.logprob || 0);
                const fondo = prob >= 0.8 ? 'transparent' : prob >= 0.5 ? 'rgba(249,226,175,.18)' : prob >= 0.2 ? 'rgba(250,179,135,.32)' : 'rgba(243,139,168,.45)';
                const alt = (p.alternativas || []).map(a => `${JSON.stringify(a.token)} ${(Math.exp(a.logprob) * 100).toFixed(1)}%`).join('\n');
                return `<span style="background:${fondo}; white-space:pre-wrap;" title="${esc(`${(prob * 100).toFixed(1)}%\n${alt}`)}">${esc(p.token)}</span>`;
            }).join('')}</div>` : '';
        return `
          ${r.pensamiento ? `<details><summary class="mod-ayuda" style="cursor:pointer;"><i class="fa-solid fa-lightbulb"></i> Razonamiento (${r.pensamiento.length} caracteres)</summary><div class="mod-pre">${esc(r.pensamiento)}</div></details>` : ''}
          <div class="mod-pre" style="max-height:340px;">${esc(r.respuesta)}</div>
          <div class="mod-ayuda">${valido} ${mt.generacion_tok_s ? `${mt.generacion_tok_s} tok/s · ` : ''}${mt.tokens_respuesta} tokens · lectura ${mt.tokens_prompt} tokens
            ${mt.lectura_tok_s ? `a ${mt.lectura_tok_s} tok/s` : ''} · carga ${mt.carga_s}s · total ${mt.total_s}s · fin: ${esc(mt.motivo_fin)}
            ${mt.contexto ? ` · contexto ${mt.contexto_usado_pct}% de ${mt.contexto}` : ''}</div>
          ${mt.cortada ? '<div class="mod-aviso">Cortada por el límite de tokens.</div>' : ''}
          ${confianza}
          <details style="margin-top:6px;"><summary class="mod-ayuda" style="cursor:pointer;">Petición enviada a Ollama</summary><div class="mod-pre">${esc(JSON.stringify(r.peticion, null, 1))}</div></details>`;
    }

    // ================================================================== FICHA
    async function ficha(cuerpo) {
        const m = modeloActual();
        if (!m) { cuerpo.innerHTML = '<div class="mod-ayuda">Elige un modelo.</div>'; return; }
        const f = await json(`/api/modelos/ficha?modelo=${encodeURIComponent(m.nombre)}`);
        if (!cuerpo.isConnected) return;
        const info = f.info || {};
        const arq = info['general.architecture'] || '';
        const dato = (k) => info[`${arq}.${k}`];
        const filas = [
            ['Arquitectura', arq], ['Familia', f.detalles.family], ['Parámetros', f.detalles.parameter_size],
            ['Cuantización', f.detalles.quantization_level], ['Formato', f.detalles.format],
            ['Contexto máximo', dato('context_length')], ['Dimensión de embedding', dato('embedding_length')],
            ['Capas', dato('block_count')], ['Cabezas de atención', dato('attention.head_count')],
            ['Cabezas KV', dato('attention.head_count_kv')], ['Expertos', dato('expert_count')],
            ['Expertos por token', dato('expert_used_count')], ['Modificado', (f.modificado || '').slice(0, 19).replace('T', ' ')],
        ].filter(([, v]) => v !== undefined && v !== null && v !== '');
        cuerpo.innerHTML = `
          <div class="mod-2col">
            <div class="mod-caja"><div class="mod-titulo">${esc(f.modelo)}</div>
              <div class="mod-caps" style="margin-bottom:8px;">${f.capacidades.map(c => `<span class="mod-cap" style="font-size:11px;"><i class="fa-solid ${(CAPS[c] || [c, 'fa-tag'])[1]}"></i> ${(CAPS[c] || [c])[0]}</span>`).join('')}</div>
              <table class="mod-tabla">${filas.map(([k, v]) => `<tr><td class="mod-ayuda">${k}</td><td>${esc(v)}</td></tr>`).join('')}</table></div>
            <div class="mod-caja"><div class="mod-titulo">Parámetros de fábrica</div>
              ${Object.keys(f.parametros).length ? `<table class="mod-tabla">${Object.entries(f.parametros).map(([k, v]) => `<tr><td style="font-family:'Fira Code',monospace;">${esc(k)}</td><td>${esc(Array.isArray(v) ? v.join(' | ') : v)}</td></tr>`).join('')}</table>`
                : '<div class="mod-ayuda">No trae ninguno: usa los valores por defecto de Ollama.</div>'}
              ${f.system ? `<div class="mod-titulo" style="margin-top:10px;">Instrucciones de sistema</div><div class="mod-pre">${esc(f.system)}</div>` : ''}
            </div>
          </div>
          <details class="mod-caja"><summary class="mod-titulo" style="cursor:pointer;">Plantilla</summary><div class="mod-pre">${esc(f.plantilla)}</div></details>
          <details class="mod-caja"><summary class="mod-titulo" style="cursor:pointer;">Modelfile</summary><div class="mod-pre">${esc(f.modelfile)}</div></details>
          <details class="mod-caja"><summary class="mod-titulo" style="cursor:pointer;">Licencia</summary><div class="mod-pre">${esc(f.licencia || 'Sin licencia declarada')}</div></details>
          <details class="mod-caja"><summary class="mod-titulo" style="cursor:pointer;">Tensores (${f.tensores.total})</summary>
            <div class="mod-ayuda" style="margin:4px 0;">Por tipo: ${Object.entries(f.tensores.tipos).map(([t, n]) => `${esc(t)} × ${n}`).join(' · ')}</div>
            <table class="mod-tabla"><tr><th>Nombre</th><th>Tipo</th><th>Forma</th></tr>
            ${f.tensores.lista.map(t => `<tr><td style="font-family:'Fira Code',monospace;">${esc(t.name)}</td><td>${esc(t.type)}</td><td>${esc((t.shape || []).join(' × '))}</td></tr>`).join('')}</table>
            ${f.tensores.total > f.tensores.lista.length ? `<div class="mod-ayuda">Mostrando ${f.tensores.lista.length} de ${f.tensores.total}.</div>` : ''}
          </details>
          <details class="mod-caja"><summary class="mod-titulo" style="cursor:pointer;">Metadatos completos</summary><div class="mod-pre">${esc(JSON.stringify(info, null, 1))}</div></details>`;
    }

    // ================================================================== GESTIONAR
    async function leerNdjson(res, alEvento) {
        if (!res.ok) throw new Error(await window.prigErrorDetail(res));
        const lector = res.body.getReader();
        const dec = new TextDecoder();
        let resto = '';
        for (;;) {
            const { done, value } = await lector.read();
            if (done) break;
            resto += dec.decode(value, { stream: true });
            const partes = resto.split('\n');
            resto = partes.pop();
            for (const p of partes) {
                if (!p.trim()) continue;
                const ev = JSON.parse(p);
                if (ev.fase === 'error') throw new Error(ev.mensaje);
                alEvento(ev);
            }
        }
    }

    async function gestionar(cuerpo) {
        const m = modeloActual();
        const cat = estado.catalogo;
        cuerpo.innerHTML = `
          ${m ? `<div class="mod-caja">
            <div class="mod-titulo"><i class="fa-solid fa-code-branch"></i> Crear variante de ${esc(m.nombre)}</div>
            <div class="mod-ayuda" style="margin-bottom:6px;">Un modelo nuevo que comparte los pesos (no ocupa más disco) con sus propias instrucciones, parámetros y ejemplos.</div>
            <div style="display:grid; grid-template-columns:1fr 1fr; gap:8px;">
              <label class="mod-ayuda">Nombre<input id="va-nombre" class="mod-campo" placeholder="${esc(m.nombre.split(':')[0])}-tutor"></label>
              <label class="mod-ayuda">Parámetros<select id="va-param" class="mod-campo">
                <option value="">Los del modelo base</option><option value="capa">Los fijados en Ajustes → Solo este modelo</option></select></label>
            </div>
            <label class="mod-ayuda">Instrucciones de sistema<textarea id="va-system" class="mod-campo" rows="3" placeholder="Eres un tutor de Python paciente que explica con ejemplos…"></textarea></label>
            <div class="mod-ayuda" style="margin-top:6px;">Ejemplos de conversación (el modelo los toma como punto de partida)</div>
            <div id="va-ejemplos"></div>
            <button class="mod-boton" id="va-mas" style="margin:4px 0;"><i class="fa-solid fa-plus"></i> Añadir ejemplo</button>
            <details><summary class="mod-ayuda" style="cursor:pointer;">Licencia</summary><textarea id="va-licencia" class="mod-campo" rows="2"></textarea></details>
            <div style="display:flex; gap:8px; align-items:center; margin-top:8px;">
              <button class="mod-boton ok" id="va-crear"><i class="fa-solid fa-wand-magic-sparkles"></i> Crear variante</button><span id="va-estado" class="mod-ayuda"></span></div>
          </div>
          <div class="mod-2col">
            <div class="mod-caja"><div class="mod-titulo"><i class="fa-solid fa-copy"></i> Copiar</div>
              <input id="co-destino" class="mod-campo" placeholder="nombre-de-la-copia">
              <label class="mod-ayuda" style="display:flex; gap:6px; align-items:center; margin:6px 0;"><input type="checkbox" id="co-config" checked> Copiar también sus ajustes de Prig</label>
              <button class="mod-boton" id="co-copiar">Copiar</button> <span id="co-estado" class="mod-ayuda"></span></div>
            <div class="mod-caja"><div class="mod-titulo"><i class="fa-solid fa-trash-can"></i> Eliminar</div>
              <div class="mod-ayuda" style="margin-bottom:6px;">Borra ${esc(m.nombre)} del disco (${gb(m.bytes)}). Las variantes que comparten pesos siguen funcionando.</div>
              <button class="mod-boton peligro" id="el-borrar">Eliminar ${esc(m.nombre)}</button> <span id="el-estado" class="mod-ayuda"></span></div>
          </div>` : ''}
          <div class="mod-caja"><div class="mod-titulo"><i class="fa-solid fa-file-import"></i> Importar un GGUF</div>
            <div class="mod-ayuda" style="margin-bottom:6px;">Un modelo descargado de Hugging Face u otro sitio (archivo .gguf de tu carpeta personal).</div>
            <div style="display:grid; grid-template-columns:2fr 1fr auto; gap:8px; align-items:end;">
              <label class="mod-ayuda">Ruta del archivo<input id="im-ruta" class="mod-campo" placeholder="/home/usuario/Descargas/modelo.Q4_K_M.gguf"></label>
              <label class="mod-ayuda">Nombre en Ollama<input id="im-nombre" class="mod-campo" placeholder="mi-modelo"></label>
              <button class="mod-boton ok" id="im-importar">Importar</button></div>
            <div id="im-progreso" style="margin-top:8px;"></div></div>
          <div class="mod-2col">
            <div class="mod-caja"><div class="mod-titulo"><i class="fa-solid fa-arrows-rotate"></i> Actualizaciones</div>
              <div class="mod-ayuda" style="margin-bottom:6px;">Compara cada modelo con su versión en el registro de Ollama.</div>
              <button class="mod-boton" id="ac-buscar">Buscar actualizaciones</button><div id="ac-lista" style="margin-top:8px;"></div></div>
            <div class="mod-caja"><div class="mod-titulo"><i class="fa-solid fa-hourglass-half"></i> Descargas a medias</div>
              <div id="pa-info" class="mod-ayuda">Buscando…</div></div>
          </div>`;

        if (m) {
            const ejemplos = $('va-ejemplos');
            const nuevoEjemplo = () => {
                const fila = document.createElement('div');
                fila.style.cssText = 'display:grid; grid-template-columns:1fr 1fr auto; gap:6px; margin:3px 0;';
                fila.innerHTML = `<input class="mod-campo" data-rol="user" placeholder="Usuario: …"><input class="mod-campo" data-rol="assistant" placeholder="Modelo: …">
                    <button class="mod-boton peligro" title="Quitar">×</button>`;
                fila.querySelector('button').onclick = () => fila.remove();
                ejemplos.appendChild(fila);
            };
            $('va-mas').onclick = nuevoEjemplo;
            $('va-crear').onclick = async () => {
                const mensajes = [];
                ejemplos.querySelectorAll('div').forEach(f => f.querySelectorAll('input').forEach(i => { if (i.value.trim()) mensajes.push({ role: i.dataset.rol, content: i.value }); }));
                let parametros = {};
                if ($('va-param').value === 'capa') {
                    const c = await json(`/api/modelos/config?modelo=${encodeURIComponent(m.nombre)}`);
                    const permitidos = ['temperature', 'top_k', 'top_p', 'min_p', 'seed', 'repeat_penalty', 'repeat_last_n', 'presence_penalty', 'frequency_penalty', 'num_predict', 'stop', 'num_ctx', 'num_keep'];
                    parametros = Object.fromEntries(Object.entries(c.capas.modelo || {}).filter(([k]) => permitidos.includes(k)));
                }
                $('va-estado').innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Creando…';
                try {
                    const res = await fetch('/api/modelos/crear', { method: 'POST', headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ nombre: $('va-nombre').value, desde: m.nombre, system: $('va-system').value, parametros, mensajes, licencia: $('va-licencia').value }) });
                    await leerNdjson(res, ev => { if (ev.status) $('va-estado').textContent = ev.status; });
                    $('va-estado').innerHTML = '<span style="color:var(--accent-green);">Variante creada</span>';
                    const nombre = $('va-nombre').value.trim();
                    await cargarModelos();
                    refrescarSelectores(nombre);
                } catch (e) { $('va-estado').innerHTML = `<span style="color:var(--accent-red);">${esc(e.message)}</span>`; }
            };
            $('co-copiar').onclick = async () => {
                try {
                    const r = await post('/api/modelos/copiar', { origen: m.nombre, destino: $('co-destino').value, copiar_config: $('co-config').checked });
                    $('co-estado').innerHTML = `<span style="color:var(--accent-green);">Copiado como ${esc(r.modelo)}</span>`;
                    await cargarModelos();
                    refrescarSelectores();
                } catch (e) { $('co-estado').innerHTML = `<span style="color:var(--accent-red);">${esc(e.message)}</span>`; }
            };
            $('el-borrar').onclick = async () => {
                if (!confirm(`¿Eliminar ${m.nombre} del disco?\n\nPara volver a usarlo habrá que descargarlo de nuevo.`)) return;
                try {
                    await post('/api/modelos/borrar', { modelo: m.nombre });
                    estado.modelo = null;
                    await cargarModelos();
                    refrescarSelectores();
                    cambiarPestana('gestionar');
                } catch (e) { $('el-estado').innerHTML = `<span style="color:var(--accent-red);">${esc(e.message)}</span>`; }
            };
        }

        $('im-importar').onclick = async () => {
            const prog = $('im-progreso');
            const fase = { huella: 'Calculando la huella del archivo', subida: 'Pasándolo a Ollama', creando: 'Creando el modelo' };
            prog.innerHTML = '<div class="mod-ayuda">Empezando…</div>';
            try {
                const res = await fetch('/api/modelos/importar', { method: 'POST', headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ ruta: $('im-ruta').value.trim(), nombre: $('im-nombre').value.trim() }) });
                await leerNdjson(res, ev => {
                    if (ev.fase === 'listo') prog.innerHTML = `<span style="color:var(--accent-green);">Importado como ${esc(ev.modelo)}</span>`;
                    else if (ev.total) prog.innerHTML = `<div class="mod-ayuda">${fase[ev.fase] || ev.fase}: ${gb(ev.hecho)} de ${gb(ev.total)}</div>
                        <div class="mod-barra"><div style="width:${(100 * ev.hecho / ev.total).toFixed(1)}%"></div></div>`;
                    else if (ev.fase === 'creando') prog.innerHTML = `<div class="mod-ayuda">${fase.creando}: ${esc(ev.estado || '')}</div>`;
                });
                await cargarModelos();
                refrescarSelectores();
            } catch (e) { prog.innerHTML = `<div class="mod-error">${esc(e.message)}</div>`; }
        };

        $('ac-buscar').onclick = async () => {
            const lista = $('ac-lista');
            lista.innerHTML = '<div class="mod-ayuda"><i class="fa-solid fa-spinner fa-spin"></i> Consultando el registro…</div>';
            try {
                const d = await json('/api/modelos/actualizaciones');
                const etiqueta = { al_dia: ['al día', 'var(--accent-green)'], actualizable: ['hay versión nueva', 'var(--accent-yellow)'], local: ['creado aquí', 'var(--text-muted)'], error: ['error', 'var(--accent-red)'] };
                lista.innerHTML = `<table class="mod-tabla">${d.modelos.map(x => `<tr><td>${esc(x.modelo)}</td>
                    <td style="color:${etiqueta[x.estado][1]};" title="${esc(x.detalle || '')}">${etiqueta[x.estado][0]}</td>
                    <td>${x.estado === 'actualizable' ? `<button class="mod-boton" data-actualizar="${esc(x.modelo)}">Actualizar</button>` : ''}</td></tr>`).join('')}</table>`;
                lista.querySelectorAll('[data-actualizar]').forEach(b => b.onclick = async () => {
                    b.disabled = true; b.textContent = 'Descargando…';
                    try {
                        const res = await fetch('/api/ai/pull', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ model: b.dataset.actualizar }) });
                        const lector = res.body.getReader(); const dec = new TextDecoder(); let ultimo = '';
                        for (;;) { const { done, value } = await lector.read(); if (done) break; ultimo = dec.decode(value, { stream: true }).trim().split('\n').pop() || ultimo; b.textContent = ultimo.slice(0, 40); }
                        b.textContent = /error/i.test(ultimo) ? 'Falló' : 'Actualizado';
                    } catch (e) { b.textContent = 'Falló'; }
                });
            } catch (e) { lista.innerHTML = `<div class="mod-error">${esc(e.message)}</div>`; }
        };

        const pintarParciales = async () => {
            try {
                const p = await json('/api/modelos/parciales');
                if (!cuerpo.isConnected) return;
                $('pa-info').innerHTML = p.archivos.length
                    ? `${p.archivos.length} archivo(s) de descargas interrumpidas ocupan ${gb(p.bytes)}.<br>
                       <button class="mod-boton peligro" id="pa-borrar" style="margin-top:6px;">Borrarlos</button>
                       <div class="mod-aviso">No lo hagas mientras haya una descarga en curso.</div>`
                    : `No hay descargas a medias en <code>${esc(p.carpeta)}</code>.`;
                if ($('pa-borrar')) $('pa-borrar').onclick = async () => {
                    if (!confirm('¿Borrar los archivos de descargas interrumpidas?')) return;
                    await json('/api/modelos/parciales', { method: 'DELETE' });
                    pintarParciales();
                };
            } catch (e) { if (cuerpo.isConnected) $('pa-info').innerHTML = `<div class="mod-error">${esc(e.message)}</div>`; }
        };
        pintarParciales();
    }

    function refrescarSelectores(preferido) {
        if (typeof window.refreshAllModelLists === 'function') window.refreshAllModelLists(preferido || null);
    }

    // ================================================================== CARGADOS
    async function cargados(cuerpo) {
        const pintar = async () => {
            if (estado.pestana !== 'cargados' || !cuerpo.isConnected) return;
            let d;
            try { d = await json('/api/modelos/cargados'); } catch (e) { if (cuerpo.isConnected) cuerpo.innerHTML = `<div class="mod-error">${esc(e.message)}</div>`; return; }
            if (!cuerpo.isConnected) return;
            const texto = (m) => {
                const pct = m.bytes ? Math.round(100 * m.vram / m.bytes) : 0;
                const expira = m.expira ? new Date(m.expira) : null;
                const resta = expira ? Math.round((expira - Date.now()) / 60000) : null;
                return `<tr><td><b>${esc(m.nombre)}</b></td><td>${gb(m.bytes)}</td>
                    <td><div style="display:flex; align-items:center; gap:6px;"><div class="mod-barra" style="width:80px;"><div style="width:${pct}%"></div></div>${pct}% GPU</div></td>
                    <td>${m.contexto || '—'}</td><td>${resta === null ? '—' : resta > 100000 ? 'siempre' : resta <= 0 ? 'ya' : `${resta} min`}</td>
                    <td><button class="mod-boton" data-descargar="${esc(m.nombre)}">Descargar</button></td></tr>`;
            };
            cuerpo.innerHTML = `<div class="mod-titulo">Modelos en memoria ahora</div>
                ${d.modelos.length ? `<table class="mod-tabla"><tr><th>Modelo</th><th>Memoria</th><th>Reparto</th><th>Contexto</th><th>Se descarga en</th><th></th></tr>${d.modelos.map(texto).join('')}</table>`
                  : '<div class="mod-ayuda">Ninguno. Se cargan al usarlos, o con "Precargar" en Ajustes.</div>'}
                <div class="mod-ayuda" style="margin-top:8px;">Se actualiza cada 5 segundos.</div>`;
            cuerpo.querySelectorAll('[data-descargar]').forEach(b => b.onclick = async () => {
                b.disabled = true;
                await post('/api/modelos/descargar', { modelo: b.dataset.descargar }).catch(() => {});
                pintar(); cargarModelos();
            });
        };
        await pintar();
        estado.temporizadorCargados = setInterval(pintar, 5000);
    }

    // ================================================================== SERVIDOR
    async function servidor(cuerpo) {
        const s = await json('/api/recursos/servidor');
        if (!cuerpo.isConnected) return;
        const desc = s.descripciones || {};
        const valor = (k) => (k in s.guardado ? s.guardado[k] : (s.entorno[k] ?? ''));
        const campo = (k) => {
            const v = valor(k);
            if (['OLLAMA_IGPU_ENABLE', 'OLLAMA_DEBUG', 'OLLAMA_NO_CLOUD', 'OLLAMA_FLASH_ATTENTION'].includes(k)) {
                return `<select data-env="${k}" class="mod-campo"><option value="">Por defecto</option><option value="1" ${v === '1' ? 'selected' : ''}>Sí</option><option value="0" ${v === '0' ? 'selected' : ''}>No</option></select>`;
            }
            if (k === 'OLLAMA_LLM_LIBRARY') return `<select data-env="${k}" class="mod-campo"><option value="">Automático</option>${s.librerias.map(l => `<option ${v === l ? 'selected' : ''}>${l}</option>`).join('')}</select>`;
            if (k === 'OLLAMA_HOST') return `<select data-env="${k}" class="mod-campo"><option value="">Solo este equipo (por defecto)</option><option value="127.0.0.1:11434" ${v === '127.0.0.1:11434' ? 'selected' : ''}>127.0.0.1 — solo este equipo</option><option value="0.0.0.0:11434" ${v === '0.0.0.0:11434' ? 'selected' : ''}>0.0.0.0 — toda la red local</option></select>`;
            if (k === 'OLLAMA_KV_CACHE_TYPE') return `<select data-env="${k}" class="mod-campo"><option value="">f16 (por defecto)</option>${['f16', 'q8_0', 'q4_0'].map(x => `<option ${v === x ? 'selected' : ''}>${x}</option>`).join('')}</select>`;
            return `<input data-env="${k}" class="mod-campo" value="${esc(v)}" placeholder="por defecto">`;
        };
        const NOMBRES_BASE = { OLLAMA_KV_CACHE_TYPE: 'Precisión de la caché KV', OLLAMA_NUM_PARALLEL: 'Peticiones en paralelo', OLLAMA_FLASH_ATTENTION: 'FlashAttention',
            OLLAMA_MAX_LOADED_MODELS: 'Modelos cargados a la vez', OLLAMA_KEEP_ALIVE: 'Mantener cargado (por defecto)' };
        const claves = [...Object.keys(desc), ...Object.keys(NOMBRES_BASE)];
        const dueno = { prig: 'arrancado por Prig', systemd: 'servicio del sistema', 'systemd-usuario': 'servicio de usuario', usuario: 'lanzado a mano' }[s.dueno] || 'no responde';
        cuerpo.innerHTML = `
          <div class="mod-caja">Ollama ${esc(s.version || '?')} · ${esc(dueno)}
            ${Object.keys(s.pendiente || {}).length ? `<div class="mod-aviso">Guardado pero sin aplicar (falta reiniciar Ollama): ${Object.entries(s.pendiente).map(([k, v]) => `${k}=${v}`).join(', ')}</div>` : ''}
            ${!s.puede_reiniciar ? '<div class="mod-aviso">Este Ollama no lo arrancó Prig: al guardar recibirás las instrucciones para aplicarlo.</div>' : ''}</div>
          <div class="mod-titulo">Variables del servidor</div>
          ${claves.map(k => `<div class="mod-fila" style="grid-template-columns: minmax(180px,1fr) minmax(160px,1fr) minmax(200px,1.5fr);">
              <div>${esc((desc[k] || [NOMBRES_BASE[k]])[0])}<div class="mod-ayuda" style="font-family:'Fira Code',monospace;">${k}</div></div>
              <div>${campo(k)}</div>
              <div class="mod-ayuda">${esc((desc[k] || [])[1] || 'Gestionado también desde Recomendado.')}${desc[k] ? `<br><i>Verificado: ${esc(desc[k][2])}</i>` : ''}
                ${k in s.entorno ? `<br>Ahora: <b>${esc(s.entorno[k])}</b>` : ''}</div></div>`).join('')}
          <div style="display:flex; gap:8px; margin:10px 0; align-items:center;">
            <button class="mod-boton ok" id="sv-guardar"><i class="fa-solid fa-rotate"></i> Guardar y reiniciar Ollama</button>
            <span id="sv-estado" class="mod-ayuda"></span></div>
          <div class="mod-titulo" style="margin-top:16px;"><i class="fa-solid fa-scroll"></i> Registro del servidor
            <select id="sv-lineas" class="mod-campo" style="width:auto;"><option>200</option><option selected>400</option><option>1000</option><option>3000</option></select>
            <input id="sv-filtro" class="mod-campo" style="width:180px;" placeholder="filtrar (ej. error)">
            <button class="mod-boton" id="sv-leer">Actualizar</button></div>
          <div id="sv-registro" class="mod-pre" style="max-height:420px;">Cargando…</div>`;

        $('sv-guardar').onclick = async () => {
            const cambios = {};
            cuerpo.querySelectorAll('[data-env]').forEach(el => {
                const antes = valor(el.dataset.env);
                if (el.value !== antes) cambios[el.dataset.env] = el.value || null;
            });
            if (!Object.keys(cambios).length) { $('sv-estado').textContent = 'No hay cambios'; return; }
            if (cambios.OLLAMA_HOST === '0.0.0.0:11434' && !confirm('Con 0.0.0.0 cualquier equipo de tu red podrá usar tus modelos y ver cuáles tienes. ¿Seguir?')) return;
            if (cambios.OLLAMA_ORIGINS && cambios.OLLAMA_ORIGINS.includes('*') && !confirm('Con * cualquier web que visites podrá usar tu Ollama. ¿Seguir?')) return;
            const enviar = async (forzar) => post('/api/recursos/servidor', { cambios, reiniciar: true, forzar });
            try {
                $('sv-estado').innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Aplicando…';
                let r = await enviar(false);
                if (r.necesita_confirmar) {
                    if (!confirm(r.mensaje)) { $('sv-estado').textContent = 'Guardado sin reiniciar'; return; }
                    r = await enviar(true);
                }
                if (r.instrucciones) { alert(r.instrucciones); $('sv-estado').textContent = 'Guardado: aplícalo con las instrucciones'; }
                else $('sv-estado').innerHTML = r.aplicado ? '<span style="color:var(--accent-green);">Ollama reiniciado con los cambios</span>'
                    : `<span style="color:var(--accent-yellow);">${esc(r.mensaje || r.error || 'Reiniciado, pero no tomó: ' + Object.keys(r.faltan || {}).join(', '))}</span>`;
                setTimeout(() => { if (estado.pestana === 'servidor') cambiarPestana('servidor'); }, 1500);
            } catch (e) { $('sv-estado').innerHTML = `<span style="color:var(--accent-red);">${esc(e.message)}</span>`; }
        };
        const leer = async () => {
            try {
                const r = await json(`/api/modelos/registro?lineas=${$('sv-lineas').value}`);
                const filtro = $('sv-filtro').value.trim().toLowerCase();
                let texto = r.texto || '';
                if (filtro) texto = texto.split('\n').filter(l => l.toLowerCase().includes(filtro)).join('\n');
                $('sv-registro').textContent = (r.aviso ? `(${r.aviso})\n` : '') + (texto || '(vacío)');
                $('sv-registro').scrollTop = $('sv-registro').scrollHeight;
            } catch (e) { $('sv-registro').textContent = e.message; }
        };
        $('sv-leer').onclick = leer;
        $('sv-lineas').onchange = leer;
        $('sv-filtro').onkeydown = (e) => { if (e.key === 'Enter') leer(); };
        leer();
    }

    // ================================================================== EMBEDDINGS
    async function embeddings(cuerpo) {
        const d = await json('/api/modelos/embeddings');
        if (!cuerpo.isConnected) return;
        const modelosEmb = estado.modelos.filter(m => m.capacidades.includes('embedding'));
        const a = d.ajustes, ix = d.indice;
        cuerpo.innerHTML = `
          <div class="mod-caja"><div class="mod-titulo">Índice semántico de la biblioteca</div>
            <table class="mod-tabla">
              <tr><td class="mod-ayuda">Conceptos indexados</td><td>${ix.conceptos_indexados}</td></tr>
              <tr><td class="mod-ayuda">Indexado con</td><td>${ix.indexado_con ? `${esc(ix.indexado_con.modelo)} · ${ix.indexado_con.dimension} dimensiones` : '—'}</td></tr>
              <tr><td class="mod-ayuda">Fecha</td><td>${esc(ix.indexado_en || '—')}</td></tr></table>
            ${ix.necesita_reindexar ? `<div class="mod-aviso">El índice se hizo con otro modelo o dimensiones: hasta reindexar, la búsqueda usa solo palabras.</div>` : ''}
            <button class="mod-boton" id="em-reindexar" style="margin-top:6px;"><i class="fa-solid fa-arrows-rotate"></i> Reindexar ahora</button> <span id="em-reidx" class="mod-ayuda"></span></div>
          <div class="mod-caja"><div class="mod-titulo">Ajustes</div>
            <div style="display:grid; grid-template-columns:1fr 1fr 1fr; gap:10px;">
              <label class="mod-ayuda">Modelo<select id="em-modelo" class="mod-campo">${modelosEmb.map(m => `<option ${m.nombre.split(':')[0] === (a.modelo || 'bge-m3').split(':')[0] ? 'selected' : ''}>${esc(m.nombre)}</option>`).join('')}</select></label>
              <label class="mod-ayuda">Dimensiones (vacío = las del modelo)<input id="em-dim" type="number" min="16" max="8192" class="mod-campo" value="${a.dimensiones || ''}"></label>
              <label class="mod-ayuda" style="display:flex; align-items:center; gap:6px; margin-top:14px;"><input type="checkbox" id="em-truncar" ${a.truncar !== false ? 'checked' : ''}> Recortar textos que no caben</label>
            </div>
            <div class="mod-ayuda" style="margin-top:6px;">Menos dimensiones = índice más pequeño y rápido, algo menos preciso (verificado: 128 en vez de 1024 con bge-m3).
              Sin recortar, un texto más largo que el contexto da error en vez de perder el final.</div>
            <div style="display:flex; gap:8px; margin-top:8px; align-items:center;">
              <button class="mod-boton ok" id="em-guardar">Guardar</button>
              <button class="mod-boton" id="em-probar">Probar</button><span id="em-estado" class="mod-ayuda"></span></div></div>`;
        $('em-guardar').onclick = async () => {
            const dim = $('em-dim').value;
            try {
                const r = await post('/api/modelos/embeddings', { modelo: $('em-modelo').value, dimensiones: dim ? parseInt(dim, 10) : null,
                    quitar_dimensiones: !dim, truncar: $('em-truncar').checked });
                $('em-estado').innerHTML = `<span style="color:var(--accent-green);">Guardado</span>${r.indice.necesita_reindexar ? ' · el índice necesita reindexar' : ''}`;
                setTimeout(() => { if (estado.pestana === 'embeddings') cambiarPestana('embeddings'); }, 900);
            } catch (e) { $('em-estado').innerHTML = `<span style="color:var(--accent-red);">${esc(e.message)}</span>`; }
        };
        $('em-probar').onclick = async () => {
            $('em-estado').innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i>';
            try {
                const r = await post('/api/modelos/embeddings/probar', { texto: 'La regularización L2 penaliza los pesos grandes.' });
                $('em-estado').textContent = `${r.dimensiones} dimensiones en ${r.ms} ms · [${r.muestra.join(', ')}…]`;
            } catch (e) { $('em-estado').innerHTML = `<span style="color:var(--accent-red);">${esc(e.message)}</span>`; }
        };
        $('em-reindexar').onclick = async () => {
            if (!confirm('Reindexar recalcula el vector de cada concepto de la biblioteca. Con muchos libros tarda unos minutos. ¿Seguir?')) return;
            $('em-reidx').innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Indexando…';
            try { const r = await post('/api/kb/indexar', {}); $('em-reidx').textContent = `${r.conceptos} conceptos, ${r.dimension} dimensiones`; }
            catch (e) { $('em-reidx').innerHTML = `<span style="color:var(--accent-red);">${esc(e.message)}</span>`; }
        };
    }

    // ================================================================== EXCLUIDAS
    function excluidas(cuerpo) {
        const cat = estado.catalogo;
        const tipo = { error: ['Da error', 'var(--accent-red)'], sin_efecto: ['No hace nada', 'var(--accent-yellow)'], no_verificable: ['No se pudo comprobar', 'var(--text-muted)'] };
        const tabla = (titulo, datos) => `<div class="mod-seccion"><div class="mod-titulo">${titulo}</div><table class="mod-tabla">
            <tr><th>Opción</th><th>Resultado</th><th>Qué pasó</th></tr>
            ${Object.entries(datos).map(([k, v]) => `<tr><td style="font-family:'Fira Code',monospace;">${esc(k)}</td>
              <td style="color:${tipo[v.tipo][1]}; white-space:nowrap;">${tipo[v.tipo][0]}</td><td>${esc(v.motivo)}</td></tr>`).join('')}</table></div>`;
        cuerpo.innerHTML = `<div class="mod-ayuda" style="margin-bottom:10px;">Todo lo de Ollama se probó en esta máquina (Ollama ${esc('0.34.1')}) midiendo su efecto real.
            Esto no se añadió: mostrarlo sería un interruptor que falla o que no cambia nada.</div>
          ${tabla('Opciones de los modelos', cat.excluidas)}${tabla('Variables del servidor', cat.excluidas_servidor)}${tabla('Gestión y cuenta', cat.excluidas_gestion)}`;
    }

    const RENDER = { ajustes, probar, ficha, gestionar, cargados, servidor, embeddings, excluidas };

    /** Otros archivos añaden pestañas (el buscador de modelos) */
    function registrarPestana(id, icono, titulo, render, alPrincipio = false) {
        RENDER[id] = render;
        if (!PESTANAS.some(([x]) => x === id)) {
            if (alPrincipio) PESTANAS.unshift([id, icono, titulo]); else PESTANAS.push([id, icono, titulo]);
        }
        const barra = $('modelos-pestanas');
        if (barra) barra.innerHTML = PESTANAS.map(([pid, ic, t]) => `<button data-p="${pid}" class="${pid === estado.pestana ? 'activa' : ''}"><i class="fa-solid ${ic}"></i> ${t}</button>`).join('');
    }

    window.Modelos = {
        abrir, registrarPestana,
        recargarModelos: async () => { if ($('modelos-lista')) await cargarModelos(); },
        estilos,
    };
})();
