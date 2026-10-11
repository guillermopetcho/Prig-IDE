/**
 * Buscar y descargar modelos de Ollama, Hugging Face y ModelScope sin salir de Prig.
 *
 * Ollama descarga de las tres plataformas por sí solo (verificado en esta máquina),
 * así que no hace falta ningún complemento. Aquí se busca en todas a la vez, se ven
 * las variantes (cuantizaciones) con su tamaño exacto, se comprueba ANTES de
 * descargar que el registro puede servirlas, se estima si caben en esta máquina, y
 * se descargan en una cola con progreso, velocidad y tiempo restante.
 *
 * También: novedades de cada plataforma, modelos seguidos (avisa de variantes nuevas
 * o cambiadas) y actualizaciones de lo instalado. En la barra de estado se ve la
 * descarga en curso y cuántas actualizaciones hay.
 */
(function () {
    const $ = (id) => document.getElementById(id);
    const esc = (t) => String(t ?? '').replace(/[&<>"']/g,
        (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
    const json = (url, opciones) => window.prigFetchJson(url, opciones);
    const post = (url, cuerpo) => json(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(cuerpo || {}) });
    const gb = (b) => b == null ? '—' : b >= 1e9 ? `${(b / 1e9).toFixed(b >= 1e10 ? 0 : 1)} GB` : `${Math.max(1, Math.round(b / 1e6))} MB`;
    const cifra = (n) => n == null ? '' : n >= 1e6 ? `${(n / 1e6).toFixed(1)} M` : n >= 1e3 ? `${(n / 1e3).toFixed(1)} K` : String(n);
    const fecha = (t) => {
        if (!t) return '';
        if (!/^\d{4}-/.test(t)) return t;               // ollama.com ya da "2 weeks ago"
        const dias = Math.round((Date.now() - new Date(t)) / 86400000);
        return dias <= 0 ? 'hoy' : dias === 1 ? 'ayer' : dias < 60 ? `hace ${dias} días` : `hace ${Math.round(dias / 30)} meses`;
    };
    const FUENTES = { ollama: ['Ollama', 'fa-cube', 'var(--accent-blue)'], huggingface: ['Hugging Face', 'fa-face-smile', 'var(--accent-yellow)'],
        modelscope: ['ModelScope', 'fa-cubes-stacked', 'var(--accent-purple)'] };
    const CAP = { tools: 'herramientas', thinking: 'piensa', vision: 'visión', embedding: 'embeddings', audio: 'audio', cloud: 'nube', chat: 'chat' };

    const estado = {
        vista: 'resultados', consulta: '', fuentes: new Set(['ollama', 'huggingface', 'modelscope']), orden: 'relevancia', capacidad: '',
        resultados: {}, abiertos: new Set(), descargas: [], sondeo: null, actualizables: 0,
        localizar: { texto: '', cargando: false, datos: null, error: null },
    };

    // ------------------------------------------------------------------ estilos
    function estilos() {
        if ($('bm-estilos')) return;
        const css = document.createElement('style');
        css.id = 'bm-estilos';
        css.textContent = `
          .bm-barra { display:flex; gap:6px; flex-wrap:wrap; align-items:center; margin-bottom:8px; }
          .bm-chip { padding:4px 9px; border-radius:12px; cursor:pointer; font-size:11px; border:1px solid var(--border-color); background:transparent; color:var(--text-muted); }
          .bm-chip.activo { color:#11111b; font-weight:600; }
          .bm-sub { display:flex; gap:2px; border-bottom:1px solid var(--border-color); margin:8px 0 10px; }
          .bm-sub button { background:none; border:none; border-bottom:2px solid transparent; color:var(--text-muted); padding:5px 10px; cursor:pointer; font-size:11.5px; }
          .bm-sub button.activo { color:var(--accent-blue); border-bottom-color:var(--accent-blue); }
          .bm-fuente { margin-bottom:14px; }
          .bm-tarjeta { border:1px solid rgba(255,255,255,.07); border-radius:7px; padding:8px 10px; margin-bottom:6px; background:rgba(0,0,0,.14); }
          .bm-tarjeta:hover { border-color:rgba(137,180,250,.3); }
          .bm-cab { display:flex; gap:8px; align-items:center; flex-wrap:wrap; }
          .bm-nombre { font-weight:600; color:#fff; cursor:pointer; }
          .bm-meta { color:var(--text-muted); font-size:10.5px; display:flex; gap:10px; flex-wrap:wrap; margin-top:3px; }
          .bm-desc { color:var(--text-muted); font-size:11px; margin-top:3px; line-height:1.35; }
          .bm-mini { font-size:9.5px; padding:0 6px; border-radius:8px; background:rgba(255,255,255,.07); color:var(--text-muted); white-space:nowrap; }
          .bm-mini.ok { background:rgba(166,227,161,.15); color:var(--accent-green); }
          .bm-mini.aviso { background:rgba(249,226,175,.15); color:var(--accent-yellow); }
          .bm-mini.mal { background:rgba(243,139,168,.15); color:var(--accent-red); }
          .bm-variantes { margin-top:8px; }
          .bm-variantes table { width:100%; border-collapse:collapse; font-size:11px; }
          .bm-variantes td, .bm-variantes th { padding:4px 6px; border-bottom:1px solid rgba(255,255,255,.05); text-align:left; white-space:nowrap; }
          .bm-variantes td .mod-ayuda { white-space:normal; }
          .bm-variantes th { color:var(--text-muted); font-weight:500; font-size:10px; }
          .bm-variantes .mod-boton, .bm-cab .mod-boton, .bm-descarga .mod-boton { white-space:nowrap; padding:3px 9px; }
          .bm-descarga { display:grid; grid-template-columns: minmax(160px,1.5fr) 2fr auto; gap:10px; align-items:center; padding:6px 8px; border-radius:6px; background:rgba(0,0,0,.18); margin-bottom:4px; font-size:11px; }
          .bm-descarga .mod-barra { height:7px; }
          .bm-localizar { margin-bottom:10px; }
          .bm-localizar .mod-titulo { margin-bottom:6px; }
          .bm-variantes tr.bm-destacada td { background:rgba(137,180,250,.16); }
          .bm-variantes tr.bm-destacada td:first-child { box-shadow: inset 3px 0 0 var(--accent-blue); }
          .bm-modal-overlay { position:fixed; top:0; left:0; width:100vw; height:100vh; background:rgba(11,11,18,.85); backdrop-filter:blur(5px); display:flex; align-items:center; justify-content:center; z-index:2500; }
          .bm-modal-caja { background:var(--bg-panel, #1e1e2e); border:1px solid var(--border-color, rgba(255,255,255,.15)); border-radius:10px; box-shadow:0 16px 40px rgba(0,0,0,.6); width:640px; max-width:95vw; max-height:88vh; display:flex; flex-direction:column; overflow:hidden; }
          .bm-modal-cab { display:flex; align-items:center; justify-content:space-between; padding:12px 16px; border-bottom:1px solid rgba(255,255,255,.08); background:rgba(0,0,0,.2); }
          .bm-modal-cab h3 { margin:0; font-size:13.5px; color:#fff; display:flex; align-items:center; gap:8px; font-weight:600; }
          .bm-modal-cuerpo { padding:16px; overflow-y:auto; font-size:11.5px; line-height:1.5; color:var(--text-color, #cdd6f4); }
          .bm-modal-pie { display:flex; justify-content:flex-end; gap:8px; padding:12px 16px; border-top:1px solid rgba(255,255,255,.08); background:rgba(0,0,0,.2); }
          .bm-archivos-lista { max-height:130px; overflow-y:auto; background:rgba(0,0,0,.25); border:1px solid rgba(255,255,255,.06); border-radius:6px; padding:6px 10px; font-family:'Fira Code',monospace; font-size:11px; margin-top:6px; }
          .bm-archivos-lista div { display:flex; justify-content:space-between; padding:2px 0; border-bottom:1px dashed rgba(255,255,255,.04); }
          .bm-opcion-respaldo { display:flex; gap:10px; align-items:flex-start; padding:9px 12px; border-radius:6px; border:1px solid rgba(255,255,255,.08); margin-bottom:8px; cursor:pointer; background:rgba(0,0,0,.14); transition:border-color .15s, background .15s; }
          .bm-opcion-respaldo:hover { border-color:rgba(137,180,250,.35); background:rgba(137,180,250,.06); }
          .bm-opcion-respaldo input[type="radio"] { margin-top:3px; cursor:pointer; }
          .bm-opcion-respaldo.activo { border-color:var(--accent-blue); background:rgba(137,180,250,.12); }
        `;
        document.head.appendChild(css);
    }

    // ================================================================== render principal
    async function render(cuerpo) {
        estilos();
        cuerpo.innerHTML = `
          <div id="bm-descargas"></div>
          <div class="mod-caja bm-localizar">
            <div class="mod-titulo"><i class="fa-solid fa-crosshairs"></i> Encontrar un modelo concreto</div>
            <div class="bm-barra" style="margin-bottom:4px;">
              <input id="bm-loc" class="mod-campo" style="flex:1; min-width:220px; padding:6px 10px;" spellcheck="false"
                placeholder="Nombre (Qwen3-8B, qwen3:8b) o enlace de ollama.com, huggingface.co o modelscope.cn" value="${esc(estado.localizar.texto)}">
              <button class="mod-boton ok" id="bm-loc-ir"><i class="fa-solid fa-crosshairs"></i> Encontrar</button>
              <button class="mod-boton" id="bm-loc-cerrar" title="Quitar el resultado" ${estado.localizar.datos || estado.localizar.error ? '' : 'hidden'}><i class="fa-solid fa-xmark"></i></button>
            </div>
            <div class="mod-ayuda">Vale el enlace a la página del modelo o a un archivo .gguf, «propietario/repositorio» o la orden «ollama run …». Se busca en las tres plataformas.</div>
            <div id="bm-loc-res"></div>
          </div>
          <div class="bm-barra">
            <input id="bm-q" class="mod-campo" style="flex:1; min-width:220px; padding:7px 10px; font-size:13px;" placeholder="Buscar modelos: qwen3, deepseek, gemma, llama, coder, vision…" value="${esc(estado.consulta)}">
            <button class="mod-boton ok" id="bm-buscar"><i class="fa-solid fa-magnifying-glass"></i> Buscar</button>
          </div>
          <div class="bm-barra">
            ${Object.entries(FUENTES).map(([id, [n, ic, col]]) => `<button class="bm-chip ${estado.fuentes.has(id) ? 'activo' : ''}" data-fuente="${id}"
                style="${estado.fuentes.has(id) ? `background:${col}; border-color:${col};` : ''}"><i class="fa-solid ${ic}"></i> ${n}</button>`).join('')}
            <span style="flex:1"></span>
            <label class="mod-ayuda">Orden <select id="bm-orden" class="mod-campo" style="width:auto;">
              ${[['relevancia', 'Relevancia'], ['descargas', 'Más descargados'], ['tendencia', 'Tendencia'], ['recientes', 'Más nuevos'], ['actualizados', 'Actualizados']]
                .map(([v, t]) => `<option value="${v}" ${estado.orden === v ? 'selected' : ''}>${t}</option>`).join('')}</select></label>
            <label class="mod-ayuda">Capacidad <select id="bm-cap" class="mod-campo" style="width:auto;" title="Solo filtra en Ollama">
              <option value="">Cualquiera</option>${['tools', 'thinking', 'vision', 'embedding'].map(c => `<option value="${c}" ${estado.capacidad === c ? 'selected' : ''}>${CAP[c]}</option>`).join('')}</select></label>
          </div>
          <div class="bm-sub">
            ${[['resultados', 'Resultados'], ['novedades', 'Novedades'], ['seguidos', 'Seguidos'], ['actualizaciones', 'Actualizaciones']]
              .map(([v, t]) => `<button data-vista="${v}" class="${estado.vista === v ? 'activo' : ''}">${t}${v === 'actualizaciones' && estado.actualizables ? ` <span class="bm-mini aviso">${estado.actualizables}</span>` : ''}</button>`).join('')}
          </div>
          <div id="bm-contenido"></div>`;

        const lanzar = () => { estado.consulta = $('bm-q').value.trim(); estado.vista = 'resultados'; estado.resultados = {}; render(cuerpo); };
        $('bm-buscar').onclick = lanzar;
        $('bm-q').onkeydown = (e) => { if (e.key === 'Enter') lanzar(); };
        cuerpo.querySelectorAll('.bm-chip[data-fuente]').forEach(b => b.onclick = () => {
            const f = b.dataset.fuente;
            if (estado.fuentes.has(f) && estado.fuentes.size > 1) estado.fuentes.delete(f); else estado.fuentes.add(f);
            estado.resultados = {};
            render(cuerpo);
        });
        $('bm-orden').onchange = (e) => { estado.orden = e.target.value; estado.resultados = {}; render(cuerpo); };
        $('bm-cap').onchange = (e) => { estado.capacidad = e.target.value; estado.resultados = {}; render(cuerpo); };
        cuerpo.querySelectorAll('[data-vista]').forEach(b => b.onclick = () => { estado.vista = b.dataset.vista; render(cuerpo); });

        const ir = () => localizar($('bm-loc').value);
        $('bm-loc-ir').onclick = ir;
        $('bm-loc').onkeydown = (e) => { if (e.key === 'Enter') ir(); };
        // Al pegar un enlace u orden no hace falta pulsar nada
        $('bm-loc').onpaste = () => setTimeout(() => { if (/^\s*(https?:\/\/|www\.|hf\.co\/|huggingface\.co\/|modelscope\.cn\/|ollama\.com\/|ollama\s+(run|pull)\s)/i.test($('bm-loc').value)) ir(); }, 0);
        $('bm-loc-cerrar').onclick = () => { estado.localizar = { texto: '', cargando: false, datos: null, error: null }; $('bm-loc').value = ''; pintarLocalizar(); };
        pintarLocalizar();

        pintarDescargas();
        Descargas.sondear();
        const cont = $('bm-contenido');
        const f = { resultados: vistaResultados, novedades: vistaNovedades, seguidos: vistaSeguidos, actualizaciones: vistaActualizaciones }[estado.vista];
        try { await f(cont); } catch (e) { if (cont.isConnected) cont.innerHTML = `<div class="mod-error">${esc(e.message)}</div>`; }
    }

    // ================================================================== resultados
    async function vistaResultados(cont) {
        if (!Object.keys(estado.resultados).length) {
            cont.innerHTML = '<div class="mod-ayuda"><i class="fa-solid fa-spinner fa-spin"></i> Buscando en ' +
                [...estado.fuentes].map(f => FUENTES[f][0]).join(', ') + '…</div>';
            const q = new URLSearchParams({ q: estado.consulta, fuentes: [...estado.fuentes].join(','), orden: estado.orden });
            if (estado.capacidad) q.set('capacidad', estado.capacidad);
            const d = await json(`/api/buscador/buscar?${q}`);
            if (!cont.isConnected) return;
            estado.resultados = d.fuentes;
        }
        cont.innerHTML = [...estado.fuentes].map(f => {
            const r = estado.resultados[f] || { modelos: [] };
            const [nombre, ic, col] = FUENTES[f];
            return `<div class="bm-fuente" data-seccion="${f}">
                <div class="mod-titulo" style="color:${col};"><i class="fa-solid ${ic}"></i> ${nombre}
                  <span class="mod-ayuda" style="font-weight:normal;">${r.modelos.length} resultado(s)</span></div>
                ${r.error ? `<div class="mod-error">${esc(r.error)}</div>` : ''}
                ${!r.error && !r.modelos.length ? '<div class="mod-ayuda">Sin resultados.</div>' : ''}
                <div data-lista="${f}">${r.modelos.map(tarjeta).join('')}</div>
                ${r.siguiente ? `<button class="mod-boton" data-mas="${f}">Más resultados de ${nombre}</button>` : ''}
              </div>`;
        }).join('');
        conectarTarjetas(cont);
        cont.querySelectorAll('[data-mas]').forEach(b => b.onclick = async () => {
            const f = b.dataset.mas;
            b.disabled = true; b.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i>';
            const q = new URLSearchParams({ q: estado.consulta, fuentes: f, orden: estado.orden, [`pagina_${f}`]: estado.resultados[f].siguiente });
            if (estado.capacidad) q.set('capacidad', estado.capacidad);
            try {
                const d = await json(`/api/buscador/buscar?${q}`);
                const extra = d.fuentes[f];
                estado.resultados[f] = { ...extra, modelos: [...estado.resultados[f].modelos, ...extra.modelos] };
                vistaResultados(cont);
            } catch (e) { b.textContent = e.message; }
        });
    }

    const clave = (m) => `${m.fuente}:${m.id}`;

    function tarjeta(m, conFuente = false) {
        const [nombreFuente, iconoFuente, col] = FUENTES[m.fuente];
        const abierto = estado.abiertos.has(clave(m));
        const meta = [
            m.descargas != null ? `<span title="Descargas"><i class="fa-solid fa-download"></i> ${cifra(m.descargas)}</span>` : '',
            m.me_gusta ? `<span title="Me gusta"><i class="fa-solid fa-heart"></i> ${cifra(m.me_gusta)}</span>` : '',
            m.actualizado ? `<span title="Actualizado"><i class="fa-solid fa-clock"></i> ${esc(fecha(m.actualizado))}</span>` : '',
            m.contexto ? `<span title="Contexto máximo">${cifra(m.contexto)} tokens</span>` : '',
            m.variantes_total ? `<span>${m.variantes_total} variantes</span>` : '',
            m.licencia ? `<span title="Licencia">${esc(m.licencia)}</span>` : '',
        ].filter(Boolean).join('');
        return `<div class="bm-tarjeta" data-tarjeta="${esc(clave(m))}" data-fuente="${m.fuente}" data-id="${esc(m.id)}" data-destacar="${esc(m.destacar || '')}">
            <div class="bm-cab">
              ${conFuente ? `<span class="bm-mini" style="color:${col}; border:1px solid ${col};"><i class="fa-solid ${iconoFuente}"></i> ${nombreFuente}</span>` : ''}
              <span class="bm-nombre" data-ver title="Ver variantes">${esc(m.id)}</span>
              ${m.oficial ? `<span class="bm-mini ok">oficial</span>` : `<span class="bm-mini" style="color:${col};">${esc(m.autor || '')}</span>`}
              ${m.instalado ? '<span class="bm-mini ok"><i class="fa-solid fa-check"></i> instalado</span>' : ''}
              ${m.requiere_licencia ? '<span class="bm-mini aviso" title="Hay que aceptar la licencia en Hugging Face: Ollama no puede descargarlo sin sesión">licencia por aceptar</span>' : ''}
              ${m.solo_nube ? '<span class="bm-mini aviso" title="Solo se ejecuta en la nube de Ollama">solo nube</span>' : ''}
              ${m.sin_gguf ? '<span class="bm-mini mal" title="Ollama solo usa archivos GGUF: busca una versión GGUF de este modelo">sin GGUF</span>' : ''}
              ${(m.capacidades || []).map(c => `<span class="bm-mini">${esc(CAP[c] || c)}</span>`).join('')}
              ${(m.tamanos || []).map(t => `<span class="bm-mini" style="color:var(--accent-blue);">${esc(t)}</span>`).join('')}
              <span style="flex:1"></span>
              ${m.fuente === 'huggingface' ? `<button class="mod-boton" data-respaldo-tarjeta title="Descargar modelo completo con todas las configuraciones para respaldo offline (por si se borra de Hugging Face)"><i class="fa-solid fa-box-archive" style="color:var(--accent-yellow);"></i> Respaldo HF</button>` : ''}
              <button class="mod-boton" data-seguir title="Avisar cuando tenga variantes nuevas o cambios">${m.seguido ? '<i class="fa-solid fa-star" style="color:var(--accent-yellow);"></i> Siguiendo' : '<i class="fa-regular fa-star"></i> Seguir'}</button>
              <button class="mod-boton" data-ver>${abierto ? 'Ocultar' : 'Variantes'}</button>
            </div>
            ${m.descripcion ? `<div class="bm-desc">${esc(m.descripcion)}</div>` : ''}
            <div class="bm-meta">${meta}<span style="flex:1"></span><span title="Página del modelo" style="user-select:all;">${esc(m.url || '')}</span></div>
            <div class="bm-variantes" data-variantes ${abierto ? '' : 'hidden'}></div>
          </div>`;
    }

    function conectarTarjetas(cont) {
        cont.querySelectorAll('.bm-tarjeta').forEach(t => {
            const fuente = t.dataset.fuente, id = t.dataset.id, k = t.dataset.tarjeta;
            t.querySelectorAll('[data-respaldo-tarjeta]').forEach(b => b.onclick = (e) => {
                e.stopPropagation();
                dialogoRespaldoHF(id);
            });
            t.querySelectorAll('[data-ver]').forEach(b => b.onclick = () => {
                const panel = t.querySelector('[data-variantes]');
                if (estado.abiertos.has(k)) { estado.abiertos.delete(k); panel.hidden = true; t.querySelector('button[data-ver]').textContent = 'Variantes'; return; }
                estado.abiertos.add(k);
                panel.hidden = false;
                t.querySelector('button[data-ver]').textContent = 'Ocultar';
                cargarVariantes(panel, fuente, id, t.dataset.destacar);
            });
            t.querySelector('[data-seguir]').onclick = async (e) => {
                const b = e.currentTarget;
                const siguiendo = b.textContent.includes('Siguiendo');
                b.disabled = true;
                try {
                    await post(siguiendo ? '/api/buscador/seguidos/dejar' : '/api/buscador/seguidos', { fuente, id, titulo: id });
                    b.innerHTML = siguiendo ? '<i class="fa-regular fa-star"></i> Seguir' : '<i class="fa-solid fa-star" style="color:var(--accent-yellow);"></i> Siguiendo';
                    Object.values(estado.resultados).forEach(r => (r.modelos || []).forEach(m => { if (clave(m) === k) m.seguido = !siguiendo; }));
                } catch (err) { alert(err.message); }
                b.disabled = false;
            };
            if (estado.abiertos.has(k)) cargarVariantes(t.querySelector('[data-variantes]'), fuente, id, t.dataset.destacar);
        });
    }

    async function cargarVariantes(panel, fuente, id, destacar) {
        panel.innerHTML = '<div class="mod-ayuda"><i class="fa-solid fa-spinner fa-spin"></i> Leyendo variantes y comprobando cada una en el registro…</div>';
        let d;
        try { d = await json(`/api/buscador/variantes?fuente=${fuente}&id=${encodeURIComponent(id)}`); }
        catch (e) { panel.innerHTML = `<div class="mod-error">${esc(e.message)}</div>`; return; }
        if (!panel.isConnected) return;
        const esHf = fuente === 'huggingface';
        if (!d.variantes.length) {
            if (esHf) {
                panel.innerHTML = `
                  <div class="mod-ayuda" style="margin-bottom:8px;">No tiene archivos GGUF directos para Ollama, pero puedes descargar el repositorio completo con todas sus configuraciones y pesos para tener un respaldo offline independiente:</div>
                  <button class="mod-boton ok" data-respaldo-todo><i class="fa-solid fa-box-archive"></i> Descargar modelo completo con configs</button>`;
                panel.querySelector('[data-respaldo-todo]').onclick = () => dialogoRespaldoHF(id);
                return;
            }
            panel.innerHTML = '<div class="mod-ayuda">No tiene archivos GGUF que Ollama pueda usar.</div>';
            return;
        }
        const descargables = d.variantes.filter(v => v.descargable).length;
        panel.innerHTML = `
          <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:6px; margin-bottom:6px;">
            <div class="mod-ayuda">${d.variantes.length} variantes · ${descargables} descargables con Ollama
              ${d.requiere_licencia ? ' · <span style="color:var(--accent-yellow);">requiere aceptar la licencia en Hugging Face</span>' : ''}
              ${d.vision ? ' · incluye proyector de visión' : ''}</div>
            ${esHf ? `<button class="mod-boton" data-respaldo-todo title="Descarga todas las configuraciones (config.json, tokenizer, etc.) y pesos seleccionados para respaldo offline"><i class="fa-solid fa-box-archive" style="color:var(--accent-yellow);"></i> Descargar completo con configs</button>` : ''}
          </div>
          <table><tr><th>Variante</th><th>Tamaño</th><th>Contexto</th><th>Entrada</th><th>Estado</th><th>¿Cómo iría aquí?</th><th>Acciones</th></tr>
          ${d.variantes.map(v => `<tr data-ref="${esc(v.ref)}" data-etiqueta="${esc(v.etiqueta)}">
              <td style="font-family:'Fira Code',monospace;">${esc(v.etiqueta)}${v.predeterminada ? ' <span class="bm-mini">por defecto</span>' : ''}</td>
              <td>${gb(v.bytes)}${v.partes > 1 ? ` <span class="bm-mini">${v.partes} partes</span>` : ''}</td>
              <td>${esc(v.contexto || (d.contexto ? cifra(d.contexto) : ''))}</td>
              <td>${esc((v.entrada || []).join(', ') || (v.vision ? 'texto, imagen' : ''))}</td>
              <td>${v.instalado ? '<span class="bm-mini ok">instalado</span>' : v.descargable ? '<span class="bm-mini ok">descargable</span>'
                : `<span class="bm-mini mal" title="${esc(v.nota || '')}">no disponible</span><div class="mod-ayuda">${esc(v.nota || '')}</div>`}</td>
              <td data-veredicto>${v.descargable ? '<button class="mod-boton" data-analizar title="Lee solo la cabecera del modelo y calcula memoria y velocidad en tu máquina">Calcular</button>' : ''}</td>
              <td><div style="display:flex; gap:4px; flex-wrap:wrap;">
                ${v.descargable && !v.instalado ? `<button class="mod-boton ok" data-descargar><i class="fa-solid fa-download"></i> Descargar</button>` : ''}
                ${esHf ? `<button class="mod-boton" data-descargar-completo title="Descarga este archivo junto con todas las configuraciones, tokenizador y metadatos"><i class="fa-solid fa-box-archive"></i> Completo + configs</button>` : ''}
              </div></td>
            </tr>`).join('')}</table>`;
        if (destacar) {
            // La variante que traía el enlace o el nombre (8b, Q4_K_M…): marcada y a la vista
            const fila = [...panel.querySelectorAll('tr[data-ref]')].find(tr => tr.dataset.ref.split(':').pop().toLowerCase() === destacar.toLowerCase());
            if (fila) {
                fila.classList.add('bm-destacada');
                fila.scrollIntoView({ block: 'center', behavior: 'smooth' });
            } else {
                panel.insertAdjacentHTML('afterbegin', `<div class="mod-aviso" style="margin-bottom:6px;">No hay ninguna variante «${esc(destacar)}» en este modelo: elige una de la lista.</div>`);
            }
        }
        panel.querySelectorAll('[data-analizar]').forEach(b => b.onclick = async () => {
            const fila = b.closest('tr');
            const celda = fila.querySelector('[data-veredicto]');
            celda.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> leyendo cabecera…';
            try {
                const r = await json(`/api/buscador/analizar?ref=${encodeURIComponent(fila.dataset.ref)}`);
                const v = r.veredicto;
                const color = { entero: 'ok', ajustando: 'ok', parcial: 'aviso', solo_cpu: 'aviso', lento: 'mal', no_viable: 'mal' }[v.veredicto] || '';
                celda.innerHTML = `<span class="bm-mini ${color}" title="${esc(v.motivo || '')}">${esc(v.etiqueta)}</span>
                    <div class="mod-ayuda">${v.memoria_gb ? `${v.memoria_gb} GB` : ''}${v.tok_s ? ` · ~${v.tok_s} tok/s` : ''}${r.ficha.piensa ? ' · piensa' : ''}</div>`;
            } catch (e) { celda.innerHTML = `<span class="mod-ayuda" style="color:var(--accent-red);">${esc(e.message)}</span>`; }
        });
        panel.querySelectorAll('[data-descargar]').forEach(b => b.onclick = async () => {
            const ref = b.closest('tr').dataset.ref;
            b.disabled = true;
            try { await Descargas.encolar(ref); b.innerHTML = '<i class="fa-solid fa-clock"></i> En cola'; }
            catch (e) { b.disabled = false; alert(e.message); }
        });
        if (esHf) {
            panel.querySelectorAll('[data-respaldo-todo]').forEach(b => b.onclick = () => dialogoRespaldoHF(id));
            panel.querySelectorAll('[data-descargar-completo]').forEach(b => b.onclick = () => {
                const fila = b.closest('tr');
                const etiqueta = fila.dataset.etiqueta || (fila.dataset.ref.includes(':') ? fila.dataset.ref.split(':').pop() : null);
                dialogoRespaldoHF(id, etiqueta);
            });
        }
    }

    // ================================================================== encontrar un modelo concreto
    async function localizar(texto) {
        texto = (texto || '').trim();
        if (!texto) return;
        const pedido = { texto, cargando: true, datos: null, error: null };
        estado.localizar = pedido;
        pintarLocalizar();
        try {
            pedido.datos = await json(`/api/buscador/localizar?texto=${encodeURIComponent(texto)}`);
            // Lo encontrado se abre con sus variantes (si son pocos, para no comprobar decenas a la vez)
            if (pedido.datos.exactos.length <= 2) pedido.datos.exactos.filter(m => !m.sin_gguf).forEach(m => estado.abiertos.add(clave(m)));
        } catch (e) {
            pedido.error = e.message;
        }
        pedido.cargando = false;
        if (estado.localizar === pedido) pintarLocalizar();     // si mientras tanto se pidió otra cosa, manda la última
    }

    function pintarLocalizar() {
        const cont = $('bm-loc-res');
        if (!cont) return;
        const { cargando, datos, error, texto } = estado.localizar;
        if ($('bm-loc-cerrar')) $('bm-loc-cerrar').hidden = !(datos || error);
        if (cargando) { cont.innerHTML = `<div class="mod-ayuda" style="margin-top:8px;"><i class="fa-solid fa-spinner fa-spin"></i> Buscando «${esc(texto)}»…</div>`; return; }
        if (error) { cont.innerHTML = `<div class="mod-error" style="margin-top:8px;">${esc(error)}</div>`; return; }
        if (!datos) { cont.innerHTML = ''; return; }
        const q = datos.interpretado;
        const variante = q.etiqueta ? ` · variante <b>${esc(q.etiqueta)}</b>` : '';
        const como = q.tipo === 'enlace' ? `Enlace de ${FUENTES[q.fuente][0]}: <b>${esc(q.id)}</b>${variante}`
            : q.tipo === 'repo' ? `Repositorio <b>${esc(q.id)}</b>${variante}, buscado en las tres plataformas`
            : `Nombre «<b>${esc(q.consulta)}</b>»${variante}, buscado en las tres plataformas`;
        const todosSinGguf = datos.exactos.length && datos.exactos.every(m => m.sin_gguf);
        let aviso = '';
        if (!datos.exactos.length) {
            aviso = q.tipo === 'enlace' ? `No existe en ${FUENTES[q.fuente][0]} (o es privado).`
                : q.tipo === 'repo' ? 'Ese repositorio no está en ninguna de las tres plataformas (o es privado).'
                : 'Ningún modelo se llama exactamente así.';
            aviso += datos.parecidos.length ? ' Estos se parecen:' : ' Prueba con otro nombre o pega el enlace.';
        } else if (todosSinGguf) {
            aviso = 'Existe, pero no tiene archivos GGUF y Ollama no puede usarlo. Versiones GGUF y parecidos:';
        }
        const errores = Object.entries(datos.errores || {});
        cont.innerHTML = `
          <div class="mod-ayuda" style="margin:8px 0 6px;"><i class="fa-solid fa-circle-info"></i> ${como}</div>
          ${datos.exactos.length ? `<div data-loc="exactos">${datos.exactos.map(m => tarjeta(m, true)).join('')}</div>` : ''}
          ${aviso ? `<div class="mod-aviso" style="margin:6px 0;">${aviso}</div>` : ''}
          ${datos.parecidos.length ? `${aviso ? '' : '<div class="mod-ayuda" style="margin:8px 0 4px;">También se parecen:</div>'}
             <div data-loc="parecidos">${datos.parecidos.map(m => tarjeta(m, true)).join('')}</div>` : ''}
          ${errores.length ? `<div class="mod-ayuda" style="color:var(--accent-red); margin-top:4px;">No se pudo mirar en ${errores.map(([f, e]) => `${FUENTES[f][0]} (${esc(e)})`).join(', ')}</div>` : ''}`;
        conectarTarjetas(cont);
    }

    // ================================================================== novedades
    async function vistaNovedades(cont) {
        cont.innerHTML = '<div class="mod-ayuda"><i class="fa-solid fa-spinner fa-spin"></i> Consultando lo último de cada plataforma…</div>';
        const d = await json('/api/buscador/novedades');
        if (!cont.isConnected) return;
        const seccion = (titulo, fuente, datos) => `<div class="bm-fuente"><div class="mod-titulo" style="color:${FUENTES[fuente][2]};"><i class="fa-solid ${FUENTES[fuente][1]}"></i> ${titulo}</div>
            ${datos.error ? `<div class="mod-error">${esc(datos.error)}</div>` : datos.modelos.map(tarjeta).join('')}</div>`;
        cont.innerHTML = seccion('Nuevos en Ollama', 'ollama', d.ollama_nuevos) +
            seccion('En tendencia en Hugging Face (GGUF)', 'huggingface', d.huggingface_tendencia) +
            seccion('Recién actualizados en ModelScope (GGUF)', 'modelscope', d.modelscope_actualizados);
        conectarTarjetas(cont);
    }

    // ================================================================== seguidos
    async function vistaSeguidos(cont, revisar = false) {
        cont.innerHTML = `<div class="mod-ayuda"><i class="fa-solid fa-spinner fa-spin"></i> ${revisar ? 'Comprobando cambios…' : 'Cargando…'}</div>`;
        const d = await json(`/api/buscador/seguidos${revisar ? '?revisar=true' : ''}`);
        if (!cont.isConnected) return;
        if (!d.seguidos.length) {
            cont.innerHTML = '<div class="mod-ayuda">No sigues ningún modelo. Pulsa <i class="fa-regular fa-star"></i> Seguir en un resultado para que Prig te avise de variantes nuevas o cambiadas.</div>';
            return;
        }
        cont.innerHTML = `<div style="margin-bottom:8px;"><button class="mod-boton" id="bm-revisar"><i class="fa-solid fa-arrows-rotate"></i> Comprobar cambios ahora</button></div>` +
            d.seguidos.map(s => {
                const c = s.cambios;
                const lista = (t, xs, cls) => xs && xs.length ? `<div><span class="bm-mini ${cls}">${t}</span> ${xs.map(esc).join(', ')}</div>` : '';
                return `<div class="bm-tarjeta" data-tarjeta="${esc(s.fuente + ':' + s.id)}" data-fuente="${s.fuente}" data-id="${esc(s.id)}">
                    <div class="bm-cab"><span class="bm-nombre" data-ver>${esc(s.id)}</span><span class="bm-mini">${FUENTES[s.fuente][0]}</span>
                      ${c ? '<span class="bm-mini aviso">hay cambios</span>' : '<span class="bm-mini ok">sin cambios</span>'}
                      <span style="flex:1"></span>
                      ${c ? '<button class="mod-boton" data-visto>Marcar como visto</button>' : ''}
                      <button class="mod-boton" data-seguir><i class="fa-solid fa-star" style="color:var(--accent-yellow);"></i> Siguiendo</button>
                      <button class="mod-boton" data-ver>Variantes</button></div>
                    <div class="bm-meta">siguiendo desde ${esc(fecha(s.desde))} · comprobado ${esc(fecha(s.revisado))}${s.error ? ` · <span style="color:var(--accent-red);">${esc(s.error)}</span>` : ''}</div>
                    ${c ? `<div class="bm-desc">${lista('nuevas', c.nuevas, 'ok')}${lista('cambiadas', c.cambiadas, 'aviso')}${lista('retiradas', c.retiradas, 'mal')}</div>` : ''}
                    <div class="bm-variantes" data-variantes hidden></div></div>`;
            }).join('');
        $('bm-revisar').onclick = () => vistaSeguidos(cont, true);
        conectarTarjetas(cont);
        cont.querySelectorAll('[data-visto]').forEach(b => b.onclick = async () => {
            const t = b.closest('.bm-tarjeta');
            await post('/api/buscador/seguidos/visto', { fuente: t.dataset.fuente, id: t.dataset.id }).catch(e => alert(e.message));
            vistaSeguidos(cont);
        });
    }

    // ================================================================== actualizaciones
    async function vistaActualizaciones(cont, forzar = false) {
        cont.innerHTML = '<div class="mod-ayuda"><i class="fa-solid fa-spinner fa-spin"></i> Comparando cada modelo instalado con su registro…</div>';
        const d = await json(`/api/buscador/actualizaciones?max_edad=${forzar ? 0 : 3600}${forzar ? '&forzar=true' : ''}`);
        if (!cont.isConnected) return;
        estado.actualizables = d.actualizables;
        pintarIndicador();
        const etiqueta = { al_dia: ['al día', 'ok'], actualizable: ['hay versión nueva', 'aviso'], local: ['creado aquí', ''], error: ['error', 'mal'] };
        cont.innerHTML = `
          <div class="bm-barra"><span class="mod-ayuda">Comprobado ${esc(fecha(d.fecha))}${d.de_cache ? ' (guardado)' : ''} · ${d.actualizables} con versión nueva</span>
            <span style="flex:1"></span>
            <button class="mod-boton" id="bm-forzar"><i class="fa-solid fa-arrows-rotate"></i> Comprobar ahora</button>
            ${d.actualizables ? '<button class="mod-boton ok" id="bm-todo"><i class="fa-solid fa-download"></i> Actualizar todo</button>' : ''}</div>
          <table class="mod-tabla"><tr><th>Modelo</th><th>Origen</th><th>Estado</th><th>Tamaño</th><th></th></tr>
          ${d.modelos.map(m => `<tr><td style="font-family:'Fira Code',monospace;">${esc(m.modelo)}</td><td>${FUENTES[m.fuente][0]}</td>
              <td><span class="bm-mini ${etiqueta[m.estado][1]}" title="${esc(m.detalle || '')}">${etiqueta[m.estado][0]}</span></td>
              <td>${m.bytes ? gb(m.bytes) : ''}</td>
              <td>${m.estado === 'actualizable' ? `<button class="mod-boton ok" data-actualizar="${esc(m.modelo)}">Actualizar</button>` : ''}</td></tr>`).join('')}</table>
          <div class="mod-ayuda" style="margin-top:6px;">Prig lo comprueba solo una vez al día al arrancar. Actualizar vuelve a descargar solo lo que cambió.</div>`;
        $('bm-forzar').onclick = () => vistaActualizaciones(cont, true);
        cont.querySelectorAll('[data-actualizar]').forEach(b => b.onclick = async () => {
            b.disabled = true;
            try { await Descargas.encolar(b.dataset.actualizar, `Actualizar ${b.dataset.actualizar}`); b.textContent = 'En cola'; }
            catch (e) { b.disabled = false; alert(e.message); }
        });
        if ($('bm-todo')) $('bm-todo').onclick = () => cont.querySelectorAll('[data-actualizar]:not([disabled])').forEach(b => b.click());
    }

    // ================================================================== diálogo de respaldo completo HF
    async function dialogoRespaldoHF(repoId, varianteInicial = null) {
        let modal = $('bm-modal-respaldo');
        if (modal) modal.remove();

        modal = document.createElement('div');
        modal.id = 'bm-modal-respaldo';
        modal.className = 'bm-modal-overlay';
        modal.innerHTML = `
          <div class="bm-modal-caja">
            <div class="bm-modal-cab">
              <h3><i class="fa-solid fa-box-archive" style="color:var(--accent-yellow);"></i> Descargar modelo completo con configuraciones</h3>
              <button class="mod-boton" id="bm-modal-cerrar"><i class="fa-solid fa-xmark"></i></button>
            </div>
            <div class="bm-modal-cuerpo" id="bm-modal-cuerpo">
              <div class="mod-ayuda"><i class="fa-solid fa-spinner fa-spin"></i> Inspeccionando repositorio en Hugging Face…</div>
            </div>
          </div>
        `;
        document.body.appendChild(modal);

        const cerrar = () => modal.remove();
        modal.querySelector('#bm-modal-cerrar').onclick = cerrar;
        modal.onclick = (e) => { if (e.target === modal) cerrar(); };

        const repoLimpio = String(repoId || '').replace(/^https?:\/\//i, '').replace(/^(huggingface\.co|hf\.co)\//i, '');
        const repoParte = repoLimpio.includes(':') ? repoLimpio.split(':')[0] : repoLimpio;
        const varExtraida = varianteInicial || (repoLimpio.includes(':') ? repoLimpio.split(':')[1] : null);

        let d;
        try {
            const q = new URLSearchParams({ repo: repoParte });
            if (varExtraida) q.set('variante', varExtraida);
            d = await json(`/api/buscador/hf/inspeccionar_completo?${q}`);
        } catch (err) {
            const cuerpo = modal.querySelector('#bm-modal-cuerpo');
            if (cuerpo) {
                cuerpo.innerHTML = `
                  <div class="mod-error">${esc(err.message)}</div>
                  <div class="mod-ayuda" style="margin-top:8px;">Verifica que el repositorio existe y no requiere token o permisos especiales.</div>
                  <div style="text-align:right; margin-top:14px;"><button class="mod-boton" id="bm-modal-err-cerrar">Cerrar</button></div>
                `;
                cuerpo.querySelector('#bm-modal-err-cerrar').onclick = cerrar;
            }
            return;
        }

        const cuerpo = modal.querySelector('#bm-modal-cuerpo');
        if (!cuerpo) return;

        const hayVariantes = d.variantes_gguf && d.variantes_gguf.length > 0;
        const varianteActiva = d.variante_elegida || (hayVariantes ? d.variantes_gguf[0].etiqueta : '');

        cuerpo.innerHTML = `
          <div class="mod-ayuda" style="margin-bottom:12px; background:rgba(249,226,175,0.08); border-left:3px solid var(--accent-yellow); padding:8px 10px; border-radius:4px;">
            <b>Respaldo independiente offline:</b> Guarda todas las configuraciones esenciales (<code>config.json</code>, <code>tokenizer</code>, metadatos y plantilla) junto con los pesos en una carpeta local de tu espacio de trabajo. Si el modelo es borrado o privatizado en Hugging Face, tu copia seguirá 100% funcional y operable con Ollama.
          </div>

          <div style="margin-bottom:10px;">
            <div><b>Repositorio:</b> <span style="font-family:'Fira Code',monospace; color:#fff;">${esc(d.repo_id)}</span></div>
            <div class="mod-ayuda">Archivos detectados: ${d.total_archivos_repo} archivos · ${d.archivos_config.length} configuraciones (${gb(d.bytes_configs)})</div>
          </div>

          <div style="font-weight:600; margin-bottom:6px; color:#fff;">¿Qué deseas descargar?</div>

          ${hayVariantes ? `
            <label class="bm-opcion-respaldo activo" id="bm-opc-var-label">
              <input type="radio" name="bm_modo_respaldo" value="variante" checked>
              <div style="flex:1;">
                <div style="font-weight:600; color:#fff;">Variante específica + todas las configuraciones (Recomendado)</div>
                <div class="mod-ayuda">Descarga los pesos de la variante elegida junto con todo el paquete de configuraciones y tokenizador.</div>
                <div style="margin-top:6px; display:flex; align-items:center; gap:8px;">
                  <span>Variante:</span>
                  <select id="bm-respaldo-sel-var" class="mod-campo" style="font-family:'Fira Code',monospace; font-size:11px;">
                    ${d.variantes_gguf.map(v => `<option value="${esc(v.etiqueta)}" ${v.etiqueta.toLowerCase() === (varianteActiva || '').toLowerCase() ? 'selected' : ''}>${esc(v.etiqueta)} (${gb(v.bytes)})</option>`).join('')}
                  </select>
                  <span id="bm-calc-tamano" class="bm-mini ok"></span>
                </div>
              </div>
            </label>
          ` : d.archivos_pesos_seleccionados.length ? `
            <label class="bm-opcion-respaldo activo" id="bm-opc-var-label">
              <input type="radio" name="bm_modo_respaldo" value="variante" checked>
              <div style="flex:1;">
                <div style="font-weight:600; color:#fff;">Pesos del modelo + configuraciones (${gb(d.total_bytes_respaldo)})</div>
                <div class="mod-ayuda">Descarga los archivos de pesos del repositorio junto con todas las configuraciones.</div>
              </div>
            </label>
          ` : ''}

          <label class="bm-opcion-respaldo ${!hayVariantes && !d.archivos_pesos_seleccionados.length ? 'activo' : ''}">
            <input type="radio" name="bm_modo_respaldo" value="solo_configs" ${!hayVariantes && !d.archivos_pesos_seleccionados.length ? 'checked' : ''}>
            <div style="flex:1;">
              <div style="font-weight:600; color:#fff;">Solo archivos de configuración y metadatos (${d.archivos_config.length} archivos, ${gb(d.bytes_configs)})</div>
              <div class="mod-ayuda">Ideal si ya descargaste el archivo GGUF por separado o solo necesitas tokenizer, templates y parámetros para tu registro offline.</div>
            </div>
          </label>

          <label class="bm-opcion-respaldo">
            <input type="radio" name="bm_modo_respaldo" value="todo">
            <div style="flex:1;">
              <div style="font-weight:600; color:#fff;">Espejo completo del repositorio (${d.total_archivos_repo} archivos)</div>
              <div class="mod-ayuda">Descarga todos los archivos y variantes disponibles en el repositorio para un respaldo exhaustivo.</div>
            </div>
          </label>

          <div style="margin-top:12px;">
            <label style="font-weight:600; display:block; margin-bottom:4px; color:#fff;">Carpeta de destino en tu espacio de trabajo:</label>
            <input id="bm-respaldo-destino" class="mod-campo" style="width:100%; font-family:'Fira Code',monospace; font-size:11px;" value="${esc(d.carpeta_sugerida)}">
            <div class="mod-ayuda" style="margin-top:2px;">La carpeta se creará dentro del espacio de trabajo y aparecerá en el explorador de archivos.</div>
          </div>

          <div style="margin-top:12px;">
            <details>
              <summary style="cursor:pointer; color:var(--accent-blue); font-size:11px;"><i class="fa-solid fa-list-check"></i> Ver archivos de configuración que se incluirán (${d.archivos_config.length})</summary>
              <div class="bm-archivos-lista">
                ${d.archivos_config.map(f => `<div><span>${esc(f.nombre)}</span><span style="color:var(--text-muted);">${gb(f.bytes)}</span></div>`).join('')}
              </div>
            </details>
          </div>
          <div class="mod-ayuda" style="margin-top:8px;">
            <i class="fa-solid fa-file-circle-check" style="color:var(--accent-green);"></i> Prig creará <b>prig_backup_manifest.json</b> (con sumas SHA-256) y un <b>Modelfile</b> listo para Ollama.
          </div>
        `;

        const pie = document.createElement('div');
        pie.className = 'bm-modal-pie';
        pie.innerHTML = `
          <button class="mod-boton" id="bm-respaldo-btn-cancelar">Cancelar</button>
          <button class="mod-boton ok" id="bm-respaldo-btn-iniciar"><i class="fa-solid fa-cloud-arrow-down"></i> Iniciar descarga completa</button>
        `;
        modal.querySelector('.bm-modal-caja').appendChild(pie);

        pie.querySelector('#bm-respaldo-btn-cancelar').onclick = cerrar;

        const radios = cuerpo.querySelectorAll('input[name="bm_modo_respaldo"]');
        radios.forEach(r => r.onchange = () => {
            cuerpo.querySelectorAll('.bm-opcion-respaldo').forEach(op => op.classList.remove('activo'));
            const contenedor = r.closest('.bm-opcion-respaldo');
            if (contenedor) contenedor.classList.add('activo');
        });

        const selVar = cuerpo.querySelector('#bm-respaldo-sel-var');
        const calcSpan = cuerpo.querySelector('#bm-calc-tamano');
        const actualizarTam = () => {
            if (!selVar || !calcSpan) return;
            const elegida = selVar.value;
            const match = (d.variantes_gguf || []).find(v => v.etiqueta.toLowerCase() === elegida.toLowerCase());
            const tamBytes = (match ? match.bytes : 0) + (d.bytes_configs || 0);
            calcSpan.textContent = `Total: ~${gb(tamBytes)}`;
        };
        if (selVar) {
            selVar.onchange = actualizarTam;
            actualizarTam();
        }

        pie.querySelector('#bm-respaldo-btn-iniciar').onclick = async () => {
            const btn = pie.querySelector('#bm-respaldo-btn-iniciar');
            btn.disabled = true;
            btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Encolando…';

            const modo = cuerpo.querySelector('input[name="bm_modo_respaldo"]:checked')?.value || 'variante';
            let varianteParam = null;
            if (modo === 'variante' && selVar) {
                varianteParam = selVar.value;
            } else if (modo === 'solo_configs') {
                varianteParam = 'solo_configs';
            } else if (modo === 'todo') {
                varianteParam = 'todo';
            }

            const destino = (cuerpo.querySelector('#bm-respaldo-destino')?.value || '').trim() || d.carpeta_sugerida;
            const titulo = `Respaldo ${d.repo_id}${varianteParam === 'solo_configs' ? ' (configs)' : varianteParam === 'todo' ? ' (completo)' : varianteParam ? ` (${varianteParam})` : ''}`;

            try {
                await Descargas.encolar(d.repo_id, titulo, 'hf_completo', varianteParam, destino);
                cerrar();
                if (window.layoutMgr) window.layoutMgr.mensajeEstado(`Encolado respaldo completo de ${d.repo_id}`, 5000);
            } catch (err) {
                btn.disabled = false;
                btn.innerHTML = '<i class="fa-solid fa-cloud-arrow-down"></i> Iniciar descarga completa';
                alert('No se pudo encolar el respaldo: ' + err.message);
            }
        };
    }

    // ================================================================== descargas
    const Descargas = {
        async encolar(ref, titulo, tipo = 'ollama', variante = null, destino = null) {
            const r = await post('/api/descargas', { ref, titulo, tipo, variante, destino });
            this.sondear();
            return r;
        },
        sondear() {
            if (estado.sondeo) return;
            const paso = async () => {
                try {
                    const anteriores = new Map(estado.descargas.map(d => [d.id, d.estado]));
                    estado.descargas = (await json('/api/descargas')).descargas;
                    const recienCompletadas = estado.descargas.filter(d => d.estado === 'completado' && anteriores.get(d.id) && anteriores.get(d.id) !== 'completado');
                    if (recienCompletadas.length) {
                        if (typeof window.refreshAllModelLists === 'function') window.refreshAllModelLists(recienCompletadas[0].ref);
                        if (window.Modelos && window.Modelos.recargarModelos) window.Modelos.recargarModelos();
                        if (window.layoutMgr) window.layoutMgr.mensajeEstado(`Descargado: ${recienCompletadas.map(d => d.ref).join(', ')}`, 5000);
                        try { estado.actualizables = (await json('/api/buscador/actualizaciones?max_edad=86400')).actualizables || 0; } catch (e) { /* sin conexión */ }
                    }
                } catch (e) { /* backend reiniciando */ }
                pintarDescargas();
                pintarIndicador();
                const activas = estado.descargas.some(d => ['en_cola', 'comprobando', 'descargando'].includes(d.estado));
                estado.sondeo = activas ? setTimeout(paso, 1000) : null;
            };
            estado.sondeo = setTimeout(paso, 50);
        },
    };

    function pintarDescargas() {
        const cont = $('bm-descargas');
        if (!cont) return;
        if (!estado.descargas.length) { cont.innerHTML = ''; return; }
        const velocidad = (v) => v ? `${(v / 1e6).toFixed(1)} MB/s` : '';
        const resto = (s) => s == null ? '' : s > 3600 ? `${Math.floor(s / 3600)} h ${Math.round(s % 3600 / 60)} min` : s > 60 ? `${Math.round(s / 60)} min` : `${Math.round(s)} s`;
        cont.innerHTML = `<div class="mod-caja"><div class="mod-titulo"><i class="fa-solid fa-download"></i> Descargas
            <span style="flex:1"></span><button class="mod-boton" id="bm-limpiar">Quitar terminadas</button></div>
          ${estado.descargas.map(d => {
              const activo = ['en_cola', 'comprobando', 'descargando'].includes(d.estado);
              const color = { completado: 'var(--accent-green)', error: 'var(--accent-red)', cancelado: 'var(--text-muted)' }[d.estado] || 'var(--accent-blue)';
              const esHfCompleto = d.tipo === 'hf_completo';
              return `<div class="bm-descarga">
                <div><div style="font-family:'Fira Code',monospace; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;" title="${esc(d.ref)}">${esc(d.titulo)}</div>
                  <div class="mod-ayuda">${FUENTES[d.fuente][0]} · <span style="color:${color};">${esc(d.fase || d.estado)}</span>${esHfCompleto ? ' · <span class="bm-mini" style="color:var(--accent-yellow); border:1px solid rgba(249,226,175,.4);"><i class="fa-solid fa-box-archive"></i> respaldo completo</span>' : ''}</div>
                  ${d.carpeta_guardada ? `<div class="mod-ayuda" style="margin-top:2px; font-size:10px; color:var(--accent-green);"><i class="fa-solid fa-folder-check"></i> ${esc(d.carpeta_guardada)}</div>` : ''}</div>
                <div>${d.estado === 'error' ? `<div style="color:var(--accent-red);">${esc(d.error)}</div>`
                  : `<div class="mod-barra"><div style="width:${d.porcentaje || (d.estado === 'completado' ? 100 : 0)}%; background:${color};"></div></div>
                     <div class="mod-ayuda">${d.porcentaje != null ? `${d.porcentaje}% · ` : ''}${gb(d.completado)} de ${gb(d.total)} ${velocidad(d.velocidad) ? '· ' + velocidad(d.velocidad) : ''} ${d.restante_s ? '· quedan ' + resto(d.restante_s) : ''}</div>`}</div>
                <div>${activo ? `<button class="mod-boton peligro" data-cancelar="${d.id}">Cancelar</button>`
                  : ['error', 'cancelado'].includes(d.estado) ? `<button class="mod-boton" data-reintentar="${d.id}">Reintentar</button>` : ''}</div></div>`;
          }).join('')}</div>`;
        cont.querySelectorAll('[data-cancelar]').forEach(b => b.onclick = () => post(`/api/descargas/${b.dataset.cancelar}/cancelar`).then(() => Descargas.sondear()));
        cont.querySelectorAll('[data-reintentar]').forEach(b => b.onclick = () => post(`/api/descargas/${b.dataset.reintentar}/reintentar`).then(() => Descargas.sondear()));
        $('bm-limpiar').onclick = async () => { await json('/api/descargas/terminadas', { method: 'DELETE' }); estado.descargas = (await json('/api/descargas')).descargas; pintarDescargas(); pintarIndicador(); };
    }

    /** En la barra de estado: descarga en curso y actualizaciones pendientes */
    function pintarIndicador() {
        const derecha = $('prig-estado-derecha');
        if (!derecha) return;
        let el = $('estado-descargas');
        if (!el) {
            el = document.createElement('span');
            el.id = 'estado-descargas';
            el.style.cssText = 'cursor:pointer; display:inline-flex; gap:8px; align-items:center;';
            el.onclick = () => window.Modelos && window.Modelos.abrir('buscar');
            derecha.insertBefore(el, derecha.firstChild);
        }
        const activa = estado.descargas.find(d => d.estado === 'descargando') || estado.descargas.find(d => ['en_cola', 'comprobando'].includes(d.estado));
        const partes = [];
        if (activa) {
            const pendientes = estado.descargas.filter(d => ['en_cola', 'comprobando', 'descargando'].includes(d.estado)).length;
            partes.push(`<span style="color:var(--accent-blue);" title="${esc(activa.ref)}"><i class="fa-solid fa-download"></i> ${activa.porcentaje != null ? activa.porcentaje + '%' : '…'}${pendientes > 1 ? ` (+${pendientes - 1})` : ''}</span>`);
        }
        if (estado.actualizables) partes.push(`<span style="color:var(--accent-yellow);" title="Modelos instalados con versión nueva"><i class="fa-solid fa-circle-up"></i> ${estado.actualizables}</span>`);
        el.innerHTML = partes.join('');
        el.hidden = !partes.length;
    }

    // ================================================================== arranque
    async function comprobarAlArrancar() {
        try {
            estado.descargas = (await json('/api/descargas')).descargas;
            if (estado.descargas.some(d => ['en_cola', 'comprobando', 'descargando'].includes(d.estado))) Descargas.sondear();
        } catch (e) { /* sin backend */ }
        // Actualizaciones: como mucho una comprobación de red al día
        try {
            const d = await json('/api/buscador/actualizaciones?max_edad=86400');
            estado.actualizables = d.actualizables || 0;
            if (estado.actualizables && window.layoutMgr) window.layoutMgr.mensajeEstado(`${estado.actualizables} modelo(s) con versión nueva: Secciones → Gestión de modelos`, 8000);
        } catch (e) { /* sin conexión */ }
        pintarIndicador();
    }

    function iniciar() {
        if (!window.Modelos || !window.Modelos.registrarPestana) return;
        window.Modelos.registrarPestana('buscar', 'fa-magnifying-glass', 'Buscar y descargar', render, true);
        setTimeout(comprobarAlArrancar, 4000);
    }
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', iniciar);
    else iniciar();

    window.BuscadorModelos = {
        abrir: () => window.Modelos && window.Modelos.abrir('buscar'),
        encolar: (ref, t, tipo, v, d) => Descargas.encolar(ref, t, tipo, v, d),
        respaldoHF: (repo, variante) => dialogoRespaldoHF(repo, variante),
        /** Abre la pestaña y busca un nombre o enlace concreto */
        encontrar: async (texto) => { estado.localizar.texto = texto; await window.Modelos.abrir('buscar'); return localizar(texto); },
    };
})();
