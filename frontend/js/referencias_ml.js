/**
 * Biblioteca → 🔗 REFERENCIAS ML: libros, papers, formularios (cheat sheets), apuntes y documentación de los
 * modelos de ML, ordenados por familia de modelo (catálogo verificado: frontend/data/referencias_ml.json,
 * backend/referencias_ml.py).
 *
 * Lista a la izquierda (agrupada por familia, con filtro por tipo y búsqueda), ficha a la derecha con:
 * leer el PDF dentro de Prig, abrir en el navegador, copiar el enlace, guardar el PDF en la biblioteca
 * (queda indexado para «Mi biblioteca») y pedir al chat un resumen.
 *
 * `ReferenciasML.abrir(id)` abre la Biblioteca directamente en una referencia: lo usan los chips de
 * «Referencias relacionadas» que el chat muestra bajo cada respuesta.
 */
(function () {
    const esc = (t) => String(t ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
    const ICONO_TIPO = {
        formulario: 'fa-table-list', libro: 'fa-book', apuntes: 'fa-note-sticky', curso: 'fa-chalkboard-user',
        survey: 'fa-layer-group', paper: 'fa-file-lines', articulo: 'fa-newspaper', documentacion: 'fa-book-open-reader'
    };
    const COLOR_TIPO = {
        formulario: 'var(--accent-yellow)', libro: 'var(--accent-purple)', apuntes: 'var(--accent-green)', curso: 'var(--accent-green)',
        survey: 'var(--accent-blue)', paper: 'var(--accent-blue)', articulo: '#fab387', documentacion: 'var(--text-muted)'
    };

    const estado = {
        datos: null,          // {categorias, tipos, referencias}
        tipo: '',             // filtro por tipo ('' = todos)
        q: '',
        abiertas: new Set(),  // familias desplegadas en la lista
        actual: null,         // id seleccionado
        leyendo: false        // visor de PDF abierto en la ficha
    };

    const mgr = () => window.bookLibraryMgr;
    const lista = () => document.getElementById('book-list-items');
    const panel = () => document.getElementById('referencias-viewer-content');

    async function cargar(forzar = false) {
        if (estado.datos && !forzar) return estado.datos;
        const r = await fetch('/api/referencias');
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        estado.datos = await r.json();
        return estado.datos;
    }

    function coincide(ref, palabras) {
        const texto = [ref.titulo, (ref.autores || []).join(' '), ref.descripcion, (ref.temas || []).join(' '), ref.anio, ref.fuente]
            .join(' ').toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '');
        return palabras.every(p => texto.includes(p));
    }

    function visibles() {
        const palabras = (estado.q || '').toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '').split(/\s+/).filter(Boolean);
        return (estado.datos ? estado.datos.referencias : []).filter(r =>
            (!estado.tipo || r.tipo === estado.tipo) && (!palabras.length || coincide(r, palabras)));
    }

    async function mostrarLista(forzar = false) {
        const cont = lista();
        if (!cont) return;
        cont.innerHTML = '<div style="padding:15px; color:var(--text-muted); text-align:center;"><i class="fa-solid fa-spinner fa-spin"></i> Cargando referencias…</div>';
        try {
            await cargar(forzar);
        } catch (e) {
            cont.innerHTML = `<div style="padding:15px; color:var(--accent-red);">No se pudo cargar el catálogo: ${esc(e.message)}</div>`;
            return;
        }
        estado.q = (document.getElementById('input-search-books') || {}).value || '';
        pintarLista();
        if (!estado.actual) pintarPortada();
        mgr() && mgr().switchTab('referencias');
    }

    function pintarLista() {
        const cont = lista();
        if (!cont || !estado.datos) return;
        const refs = visibles();
        const porTipo = {};
        estado.datos.referencias.forEach(r => { porTipo[r.tipo] = (porTipo[r.tipo] || 0) + 1; });
        const chips = [['', `Todos (${estado.datos.referencias.length})`]].concat(
            Object.entries(estado.datos.tipos).filter(([t]) => porTipo[t]).map(([t, nombre]) => [t, `${nombre} (${porTipo[t]})`]));
        const buscando = Boolean(estado.q.trim()) || Boolean(estado.tipo);

        const grupos = estado.datos.categorias.map(c => {
            const propias = refs.filter(r => r.categorias[0] === c.id);
            if (!propias.length) return '';
            const abierta = buscando || estado.abiertas.has(c.id);
            return `
              <details class="ref-grupo" data-cat="${esc(c.id)}" ${abierta ? 'open' : ''} style="border:1px solid var(--border-color); border-radius:6px; background:var(--bg-dark);">
                <summary style="cursor:pointer; padding:6px 8px; font-size:11px; font-weight:700; color:var(--text-main); display:flex; align-items:center; gap:6px;">
                  <i class="fa-solid ${esc(c.icono)}" style="color:var(--accent-blue); width:14px;"></i>
                  <span style="flex:1;">${esc(c.nombre)}</span>
                  <span style="font-size:9.5px; color:var(--text-muted); font-weight:400;">${propias.length}</span>
                </summary>
                <div style="display:flex; flex-direction:column; gap:3px; padding:0 5px 6px;">
                  ${propias.map(itemHtml).join('')}
                </div>
              </details>`;
        }).join('');

        cont.innerHTML = `
          <div style="display:flex; flex-wrap:wrap; gap:3px; margin-bottom:6px;">
            ${chips.map(([t, nombre]) => `<button class="ref-tipo" data-tipo="${esc(t)}" style="font-size:9.5px; padding:2px 6px; border-radius:10px; cursor:pointer;
                border:1px solid ${estado.tipo === t ? 'var(--accent-blue)' : 'var(--border-color)'}; background:${estado.tipo === t ? 'rgba(137,180,250,0.18)' : 'transparent'};
                color:${estado.tipo === t ? 'var(--accent-blue)' : 'var(--text-muted)'};">${esc(nombre)}</button>`).join('')}
          </div>
          <div style="font-size:10px; color:var(--text-muted); margin:0 2px 6px;">
            ${refs.length} de ${estado.datos.referencias.length} · enlaces verificados · lista completa en <code>docs/referencias-ml.md</code>
          </div>
          <div style="display:flex; flex-direction:column; gap:5px;">${grupos || '<div style="padding:12px; color:var(--text-muted); font-size:11px;">Nada coincide con la búsqueda.</div>'}</div>`;

        cont.querySelectorAll('.ref-tipo').forEach(b => b.onclick = () => { estado.tipo = b.dataset.tipo; pintarLista(); });
        cont.querySelectorAll('.ref-grupo').forEach(d => d.addEventListener('toggle', () => {
            if (d.open) estado.abiertas.add(d.dataset.cat); else estado.abiertas.delete(d.dataset.cat);
        }));
        cont.querySelectorAll('.ref-item').forEach(el => el.onclick = () => seleccionar(el.dataset.id));
    }

    function itemHtml(r) {
        const activo = r.id === estado.actual;
        return `
          <div class="ref-item" data-id="${esc(r.id)}" title="${esc(r.descripcion || r.titulo)}"
               style="padding:5px 7px; border-radius:5px; cursor:pointer; background:${activo ? 'rgba(137,180,250,0.15)' : 'transparent'};
                      border:1px solid ${activo ? 'var(--accent-blue)' : 'transparent'};">
            <div style="display:flex; gap:6px; align-items:flex-start;">
              <i class="fa-solid ${ICONO_TIPO[r.tipo] || 'fa-link'}" style="color:${COLOR_TIPO[r.tipo] || 'var(--text-muted)'}; font-size:10.5px; margin-top:2px; width:12px;"></i>
              <div style="flex:1; min-width:0;">
                <div style="font-size:11px; color:var(--text-main); line-height:1.3;">${esc(r.titulo)}</div>
                <div style="font-size:9.5px; color:var(--text-muted); margin-top:1px;">
                  ${esc(r.cita)}${r.tiene_pdf ? ' · <span style="color:var(--accent-green);">PDF</span>' : ''}${r.acceso === 'pago' ? ' · <span title="En la editorial: puede requerir suscripción">💲</span>' : ''}${r.idioma === 'es' ? ' · ES' : ''}
                </div>
              </div>
            </div>
          </div>`;
    }

    function pintarPortada() {
        const p = panel();
        if (!p || !estado.datos) return;
        const total = estado.datos.referencias.length;
        const n = (t) => estado.datos.referencias.filter(r => r.tipo === t).length;
        p.innerHTML = `
          <div style="max-width:720px; margin:30px auto; text-align:center; color:var(--text-muted);">
            <i class="fa-solid fa-link" style="font-size:38px; color:var(--accent-blue); opacity:0.8; margin-bottom:14px;"></i>
            <h3 style="color:#fff; margin:0 0 8px;">Referencias de Machine Learning</h3>
            <p style="font-size:13px; line-height:1.6; margin:0 auto 14px;">
              ${total} obras para estudiar todos los modelos de ML, ordenadas por familia: ${n('libro')} libros, ${n('formulario')} formularios
              (cheat sheets), ${n('paper') + n('survey')} papers y surveys, además de apuntes, artículos y documentación oficial.
              Todos los enlaces son oficiales y fueron verificados; los papers de arXiv, con los datos de arXiv.</p>
            <p style="font-size:12px; line-height:1.6;">Elige una a la izquierda para leerla aquí, abrirla en el navegador o guardar el PDF en tu
              biblioteca (queda indexado y el tutor puede citarlo por página con <b>Mi biblioteca</b>).<br>
              En el chat de cualquier sección, cuando preguntes o pidas un resumen sobre un modelo, el tutor puede citar
              estas referencias con su enlace.</p>
          </div>`;
    }

    async function seleccionar(id) {
        estado.actual = id;
        estado.leyendo = false;
        pintarLista();
        mgr() && mgr().switchTab('referencias');
        const p = panel();
        if (!p) return;
        p.innerHTML = '<div style="padding:40px; text-align:center; color:var(--text-muted);"><i class="fa-solid fa-spinner fa-spin fa-2x"></i></div>';
        try {
            const r = await fetch(`/api/referencias/detalle?id=${encodeURIComponent(id)}`);
            if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || `HTTP ${r.status}`);
            pintarFicha(await r.json());
        } catch (e) {
            p.innerHTML = `<div style="padding:20px; color:var(--accent-red);">No se pudo abrir la referencia: ${esc(e.message)}</div>`;
        }
    }

    function pintarFicha(r) {
        const p = panel();
        const tipos = (estado.datos && estado.datos.tipos) || {};
        const autores = (r.autores || []).join(', ');
        p.innerHTML = `
          <div style="max-width:980px; margin:0 auto; display:flex; flex-direction:column; gap:12px; height:100%;">
            <div style="background:var(--bg-panel); border:1px solid var(--border-color); border-radius:8px; padding:14px 16px;">
              <div style="display:flex; gap:6px; flex-wrap:wrap; margin-bottom:6px;">
                <span style="font-size:10px; padding:1px 7px; border-radius:10px; background:rgba(137,180,250,0.15); color:${COLOR_TIPO[r.tipo] || 'var(--accent-blue)'};">
                  <i class="fa-solid ${ICONO_TIPO[r.tipo] || 'fa-link'}"></i> ${esc(tipos[r.tipo] || r.tipo)}</span>
                ${(r.categorias_nombres || []).map(c => `<span style="font-size:10px; padding:1px 7px; border-radius:10px; border:1px solid var(--border-color); color:var(--text-muted);">${esc(c)}</span>`).join('')}
                ${r.acceso === 'pago' ? '<span style="font-size:10px; padding:1px 7px; border-radius:10px; background:rgba(249,226,175,0.12); color:var(--accent-yellow);" title="Enlace a la editorial">💲 editorial: puede requerir suscripción</span>' : '<span style="font-size:10px; padding:1px 7px; border-radius:10px; background:rgba(166,227,161,0.12); color:var(--accent-green);">acceso gratuito</span>'}
              </div>
              <h2 style="margin:0 0 4px; font-size:17px; color:#fff; line-height:1.3;">${esc(r.titulo)}</h2>
              <div style="font-size:12px; color:var(--text-muted);">${esc(autores)}${r.anio ? ` · ${esc(r.anio)}` : ''}${r.fuente ? ` · ${esc(r.fuente)}` : ''}</div>
              ${r.descripcion ? `<p style="font-size:13px; color:var(--text-main); line-height:1.55; margin:10px 0 0;">${esc(r.descripcion)}</p>` : ''}
              <div style="display:flex; gap:6px; flex-wrap:wrap; margin-top:12px;">
                ${r.tiene_pdf ? `<button class="tool-btn ref-leer" style="font-size:11px; padding:4px 10px; background:rgba(137,180,250,0.15); color:var(--accent-blue);"><i class="fa-solid fa-book-open"></i> Leer aquí (PDF)</button>` : ''}
                <button class="tool-btn ref-navegador" style="font-size:11px; padding:4px 10px;"><i class="fa-solid fa-arrow-up-right-from-square"></i> Abrir en el navegador</button>
                <button class="tool-btn ref-copiar" style="font-size:11px; padding:4px 10px;"><i class="fa-solid fa-copy"></i> Copiar enlace</button>
                ${r.tiene_pdf ? `<button class="tool-btn ref-guardar" style="font-size:11px; padding:4px 10px; background:rgba(203,166,247,0.15); color:var(--accent-purple);" title="Descarga el PDF a tu biblioteca y lo indexa para que el tutor lo cite por página"><i class="fa-solid fa-download"></i> Guardar en mi biblioteca</button>` : ''}
                <button class="tool-btn ref-chat" style="font-size:11px; padding:4px 10px; background:rgba(166,227,161,0.15); color:var(--accent-green);"><i class="fa-solid fa-comments"></i> Resumir en el chat</button>
              </div>
              <div class="ref-mensaje" style="font-size:11px; margin-top:8px; color:var(--text-muted);"></div>
              <div style="font-size:10.5px; margin-top:6px; color:var(--text-muted); word-break:break-all;">
                <a href="${esc(r.url)}" target="_blank" rel="noopener noreferrer" style="color:var(--accent-blue);">${esc(r.url)}</a>
                ${r.url_pdf && r.url_pdf !== r.url ? ` · <a href="${esc(r.url_pdf)}" target="_blank" rel="noopener noreferrer" style="color:var(--accent-blue);">PDF</a>` : ''}
                ${r.verificado ? ` · verificado ${esc(r.verificado)}` : ''}
              </div>
            </div>
            ${r.resumen_original ? `
              <details style="background:var(--bg-panel); border:1px solid var(--border-color); border-radius:8px; padding:10px 14px;" ${r.tiene_pdf ? '' : 'open'}>
                <summary style="cursor:pointer; font-size:12px; font-weight:700; color:var(--text-main);">Resumen de los autores (${r.fuente === 'arXiv' ? 'arXiv' : 'original'})</summary>
                <p style="font-size:12.5px; line-height:1.6; color:var(--text-main); margin:8px 0 0;">${esc(r.resumen_original)}</p>
              </details>` : ''}
            <div class="ref-visor" style="flex:1; min-height:0; display:none; border:1px solid var(--border-color); border-radius:8px; overflow:hidden; background:#525659;"></div>
          </div>`;

        const msg = p.querySelector('.ref-mensaje');
        const leer = p.querySelector('.ref-leer');
        if (leer) leer.onclick = () => leerPdf(r, p.querySelector('.ref-visor'), leer);
        p.querySelector('.ref-navegador').onclick = () => abrirEnNavegador(r.id, r.url);
        p.querySelector('.ref-copiar').onclick = async () => {
            try { await navigator.clipboard.writeText(r.url); msg.textContent = 'Enlace copiado.'; }
            catch (e) { msg.textContent = r.url; }
        };
        const guardar = p.querySelector('.ref-guardar');
        if (guardar) guardar.onclick = () => guardarEnBiblioteca(r, guardar, msg);
        p.querySelector('.ref-chat').onclick = () => resumirEnChat(r);
    }

    function leerPdf(r, visor, boton) {
        estado.leyendo = !estado.leyendo;
        if (!estado.leyendo) {
            visor.style.display = 'none';
            visor.innerHTML = '';
            boton.innerHTML = '<i class="fa-solid fa-book-open"></i> Leer aquí (PDF)';
            return;
        }
        visor.style.display = 'block';
        visor.style.minHeight = '70vh';
        // Servido por Prig: muchas webs no se dejan incrustar en un iframe ajeno, el PDF sí
        visor.innerHTML = `<iframe src="/api/referencias/pdf?id=${encodeURIComponent(r.id)}" title="${esc(r.titulo)}"
                              style="width:100%; height:100%; min-height:70vh; border:none;"></iframe>`;
        boton.innerHTML = '<i class="fa-solid fa-xmark"></i> Cerrar lector';
        visor.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }

    async function abrirEnNavegador(id, url) {
        try {
            if (id) {
                const r = await fetch('/api/referencias/abrir', {
                    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ id })
                });
                const d = await r.json();
                if (r.ok && d.ok) return;
            }
        } catch (e) { /* abajo: pestaña nueva */ }
        window.open(url, '_blank', 'noopener');
    }

    async function guardarEnBiblioteca(r, boton, msg) {
        boton.disabled = true;
        boton.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Descargando…';
        try {
            const res = await fetch('/api/referencias/guardar', {
                method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ id: r.id })
            });
            const d = await res.json();
            if (!res.ok) throw new Error(d.detail || `HTTP ${res.status}`);
            boton.innerHTML = '<i class="fa-solid fa-check"></i> En tu biblioteca';
            msg.innerHTML = `Guardado en <b>${esc(d.category || '')}</b> como «${esc(d.filename)}»` +
                (d.indexed ? ` e indexado (${d.chunks_count || 0} fragmentos): el tutor ya puede citarlo con «Mi biblioteca».`
                           : '. Pulsa «Indexar» en la barra de la izquierda para que el tutor pueda citarlo.');
            if (mgr()) {
                // la lista de libros se actualiza por detrás, sin pintarla encima de las referencias
                fetch('/api/books/list').then(x => x.json()).then(b => { mgr().allBooks = b || []; }).catch(() => {});
                if (mgr().refreshIndexStatus) mgr().refreshIndexStatus();
            }
        } catch (e) {
            boton.disabled = false;
            boton.innerHTML = '<i class="fa-solid fa-download"></i> Guardar en mi biblioteca';
            msg.innerHTML = `<span style="color:var(--accent-red);">No se pudo guardar: ${esc(e.message)}</span>`;
        }
    }

    function resumirEnChat(r) {
        const autores = (r.autores || []).slice(0, 3).join(', ') + ((r.autores || []).length > 3 ? ' et al.' : '');
        const texto = `Resume «${r.titulo}» (${autores}${r.anio ? ', ' + r.anio : ''}): qué problema resuelve, sus ideas y fórmulas ` +
            `principales y cuándo conviene usarlo. Cita la referencia con su enlace.`;
        // La Biblioteca queda abierta: el chat está en el panel lateral y la respuesta se ve al lado
        if (window.aiChatMgr && window.aiChatMgr.sendMessage) {
            window.aiChatMgr.sendMessage(texto);
        } else {
            const input = document.getElementById('ai-chat-input');
            if (input) { input.value = texto; input.focus(); }
        }
    }

    /** Abre la Biblioteca en la categoría de referencias y, si se indica, en una referencia concreta */
    async function abrir(id = null) {
        if (window.workArea && window.workArea.abrirHerramienta) {
            window.workArea.abrirHerramienta('modal-book-library', 'Biblioteca', 'fa-book-bookmark');
        }
        const m = mgr();
        if (m) {
            if (!(window.workArea && window.workArea.abrirHerramienta)) await m.openModal();
            const pill = document.querySelector('#library-category-pills .cat-pill[data-cat="referencias"]');
            m.selectCategoryFilter('referencias', pill);
        }
        await cargar();
        if (id) {
            const ref = estado.datos.referencias.find(r => r.id === id);
            if (ref) estado.abiertas.add(ref.categorias[0]);
            await seleccionar(id);
            const el = document.querySelector(`.ref-item[data-id="${CSS.escape(id)}"]`);
            if (el) el.scrollIntoView({ block: 'center' });
        }
    }

    function abrirPestana() {
        const pill = document.querySelector('#library-category-pills .cat-pill[data-cat="referencias"]');
        if (mgr()) mgr().selectCategoryFilter('referencias', pill);
    }

    /** Chips «Referencias relacionadas» para mostrar bajo una respuesta del chat */
    function chipsHtml(refs) {
        if (!refs || !refs.length) return '';
        const tipos = (estado.datos && estado.datos.tipos) || {};
        return `<div class="msg-referencias" style="margin:8px 0 2px; font-size:10.5px;">
            <div style="color:var(--text-muted); margin-bottom:4px;"><i class="fa-solid fa-link" style="color:var(--accent-blue);"></i> Referencias relacionadas (Biblioteca)</div>
            <div style="display:flex; flex-wrap:wrap; gap:4px;">
              ${refs.map(r => `<button class="ref-chip" data-id="${esc(r.id)}" title="${esc((tipos[r.tipo] || r.tipo) + ' · ' + r.cita + ' — abrir en la Biblioteca')}"
                  onclick="window.ReferenciasML && window.ReferenciasML.abrir('${esc(r.id)}')"
                  style="text-align:left; max-width:320px; background:rgba(137,180,250,0.10); border:1px solid rgba(137,180,250,0.3); color:var(--text-main); border-radius:5px; padding:3px 7px; cursor:pointer; line-height:1.35;">
                  <i class="fa-solid ${ICONO_TIPO[r.tipo] || 'fa-link'}" style="color:${COLOR_TIPO[r.tipo] || 'var(--accent-blue)'};"></i>
                  ${esc(r.titulo.length > 60 ? r.titulo.slice(0, 58) + '…' : r.titulo)} <span style="color:var(--text-muted);">· ${esc(r.cita)}</span>
                </button>`).join('')}
            </div></div>`;
    }

    // Los tipos (para las etiquetas de los chips) se cargan en segundo plano
    setTimeout(() => { cargar().catch(() => {}); }, 3000);

    window.ReferenciasML = {
        mostrarLista, filtrar: (q) => { estado.q = q || ''; pintarLista(); }, seleccionar, abrir, abrirPestana, chipsHtml,
        estado
    };
})();
