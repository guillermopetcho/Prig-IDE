/**
 * Prig Hub: tu aprendizaje en texto plano, versionado en git (docs/prig-hub.md).
 *
 *   · Todo:        lo tuyo y lo que sigues, junto, con filtros por plataforma, tipo, origen y estado.
 *                  Arriba, un solo campo «Agregar enlace» que reconoce qué es lo que pegaste.
 *   · Rutas:       pasos con enlaces a recursos y desafíos, con tu progreso.
 *   · Desafíos:    los de los packs; se ven con todo su código ANTES de importarlos.
 *   · Siguiendo:   las novedades se revisan antes de aplicarlas; pregúntale al tutor por un pack.
 *   · Descubrir:   perfiles y packs publicados en GitHub (topics prig-perfil / prig-pack).
 *   · Mis repos:   tu perfil y tus packs: ficha, rutas, desafíos y publicar en GitHub.
 *
 * El progreso es tuyo y local: nunca se publica (salvo un resumen, si lo activas).
 */
(function () {
    const $ = (id) => document.getElementById(id);
    const esc = (t) => String(t ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
    const json = (url, opciones) => window.prigFetchJson(url, opciones);
    const enviar = (url, cuerpo) => json(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(cuerpo || {}) });
    const leerLocal = (k) => { try { return localStorage.getItem(k); } catch (e) { return null; } };
    const guardarLocal = (k, v) => { try { localStorage.setItem(k, v); } catch (e) { /* sin almacenamiento */ } };

    const ICONOS = {
        persona: 'fa-user', curso: 'fa-graduation-cap', video: 'fa-circle-play', lista: 'fa-list-ol', notebook: 'fa-book',
        dataset: 'fa-table', competicion: 'fa-trophy', repositorio: 'fa-code-branch', archivo: 'fa-file-code',
        modelo: 'fa-brain', articulo: 'fa-newspaper', ejercicio: 'fa-puzzle-piece', web: 'fa-link',
    };
    const PLAT_ICONO = {
        github: 'fa-brands fa-github', kaggle: 'fa-brands fa-kaggle', youtube: 'fa-brands fa-youtube',
        huggingface: 'fa-solid fa-face-smile', gitlab: 'fa-brands fa-gitlab', linkedin: 'fa-brands fa-linkedin', x: 'fa-brands fa-x-twitter',
    };
    const PLAT_COLOR = { github: '#e6edf3', kaggle: '#20beff', youtube: '#ff4e45', huggingface: '#ffd21e', coursera: '#2a73cc', arxiv: '#b31b1b' };
    const TIPO_NOMBRE = {
        persona: 'Persona', curso: 'Curso', video: 'Video', lista: 'Lista', notebook: 'Notebook', dataset: 'Dataset',
        competicion: 'Competición', repositorio: 'Repositorio', archivo: 'Archivo', modelo: 'Modelo', articulo: 'Artículo',
        ejercicio: 'Ejercicio', web: 'Web',
    };
    const ESTADO_NOMBRE = { pendiente: 'Pendiente', en_curso: 'En curso', terminado: 'Terminado' };

    const estado = {
        vista: leerLocal('prig_hub_vista') || 'todo', datos: null, cargando: false, error: null, info: null,
        filtros: { plataforma: '', tipo: '', origen: '', progreso: '', q: '' },
        analisis: null, destino: leerLocal('prig_hub_destino') || 'prig', ruta: null, desafio: null,
        novedades: {}, chat: {}, descubrir: { q: '', tipo: 'pack', datos: null, cargando: false, error: null },
        editorRuta: null, repoAbierto: null,
    };

    async function flujo(url, cuerpo, alEvento) {
        const res = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(cuerpo) });
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
                else if (alEvento) alEvento(ev);
            }
        }
        return fin;
    }

    function md(el, texto) {
        let html = typeof window.prigRenderMarkdown === 'function'
            ? window.prigRenderMarkdown(texto)
            : (window.marked ? window.marked.parse(String(texto || '')) : `<pre>${esc(texto)}</pre>`);
        if (window.DOMPurify && typeof window.prigRenderMarkdown !== 'function') html = DOMPurify.sanitize(html);
        el.innerHTML = html;
        el.querySelectorAll('a[href]').forEach(a => { a.target = '_blank'; a.rel = 'noopener noreferrer'; });
    }

    function hace(t) {
        if (!t) return '';
        const min = Math.floor((Date.now() - new Date(t)) / 60000);
        return min < 1 ? 'ahora' : min < 60 ? `hace ${min} min` : min < 1440 ? `hace ${Math.floor(min / 60)} h`
            : min < 2880 ? 'ayer' : `hace ${Math.floor(min / 1440)} días`;
    }

    // ================================================================== estilos
    function estilos() {
        if ($('ph-estilos')) return;
        const css = document.createElement('style');
        css.id = 'ph-estilos';
        css.textContent = `
          #prig-hub-raiz { display:grid; grid-template-columns:188px 1fr; height:100%; min-height:0; background:var(--bg-dark); color:var(--text-main); }
          #prig-hub-raiz a { color:#89b4fa; text-decoration:none; }
          #prig-hub-raiz select option { background:#1e1e2e; color:#cdd6f4; }
          .ph-nav { border-right:1px solid var(--border-color); background:var(--bg-panel); padding:12px 8px; display:flex; flex-direction:column; gap:2px; min-height:0; }
          .ph-logo { font-size:19px; font-weight:800; padding:2px 10px 4px; display:flex; gap:8px; align-items:center; color:#fff; }
          .ph-logo i { color:var(--accent-purple); }
          .ph-sub { font-size:10.5px; color:var(--text-muted); padding:0 10px 12px; line-height:1.4; }
          .ph-nav-item { display:flex; gap:10px; align-items:center; background:none; border:none; color:var(--text-main); padding:8px 12px; border-radius:18px; cursor:pointer; font-size:12.5px; text-align:left; }
          .ph-nav-item:hover { background:rgba(255,255,255,.05); }
          .ph-nav-item.activa { background:rgba(203,166,247,.15); color:var(--accent-purple); font-weight:600; }
          .ph-nav-item .ph-cuenta { margin-left:auto; font-size:10px; background:rgba(255,255,255,.08); border-radius:9px; padding:0 6px; }
          .ph-nav-item .ph-punto { margin-left:auto; width:7px; height:7px; border-radius:50%; background:var(--accent-yellow, #f9e2af); }
          .ph-hoja { min-height:0; overflow-y:auto; padding:16px 20px 30px; }
          .ph-h1 { font-size:18px; font-weight:700; margin:0 0 4px; color:#fff; }
          .ph-ayuda { font-size:11.5px; color:var(--text-muted); line-height:1.5; }
          .ph-campo { background:var(--bg-dark); color:var(--text-main); border:1px solid var(--border-color); border-radius:7px; padding:7px 9px; font-size:12.5px; box-sizing:border-box; }
          .ph-campo:focus { outline:none; border-color:var(--accent-purple); }
          .ph-btn { background:rgba(255,255,255,.05); color:var(--text-main); border:1px solid var(--border-color); border-radius:7px; padding:5px 11px; font-size:11.5px; cursor:pointer; display:inline-flex; gap:6px; align-items:center; white-space:nowrap; }
          .ph-btn:hover:not(:disabled) { border-color:var(--accent-purple); }
          .ph-btn:disabled { opacity:.5; cursor:default; }
          .ph-btn.morado { background:rgba(203,166,247,.16); border-color:rgba(203,166,247,.5); color:var(--accent-purple); font-weight:600; }
          .ph-btn.verde { background:#238636; border-color:#2ea043; color:#fff; font-weight:600; }
          .ph-btn.rojo { color:var(--accent-red); }
          .ph-btn.chico { padding:3px 8px; font-size:10.5px; }
          .ph-fila { display:flex; gap:8px; align-items:center; flex-wrap:wrap; }
          .ph-agregar { border:1px solid rgba(203,166,247,.35); background:rgba(203,166,247,.05); border-radius:10px; padding:12px; margin:12px 0 14px; }
          .ph-agregar .ph-campo[type=text] { flex:1; min-width:220px; }
          .ph-analisis { margin-top:10px; border-top:1px dashed var(--border-color); padding-top:10px; display:grid; gap:8px; }
          .ph-chips { display:flex; gap:6px; flex-wrap:wrap; margin:6px 0; }
          .ph-chip { border:1px solid var(--border-color); background:none; color:var(--text-main); border-radius:14px; padding:3px 10px; font-size:11px; cursor:pointer; display:inline-flex; gap:5px; align-items:center; }
          .ph-chip.activo { border-color:var(--accent-purple); color:var(--accent-purple); background:rgba(203,166,247,.1); }
          .ph-lista { display:grid; grid-template-columns:repeat(auto-fill, minmax(290px, 1fr)); gap:10px; margin-top:10px; }
          .ph-tarjeta { border:1px solid var(--border-color); background:var(--bg-panel); border-radius:10px; padding:11px 12px; display:flex; flex-direction:column; gap:6px; min-width:0; }
          .ph-tarjeta:hover { border-color:rgba(203,166,247,.45); }
          .ph-tarjeta.terminado { opacity:.72; }
          .ph-t-cab { display:flex; gap:9px; align-items:flex-start; }
          .ph-t-icono { width:30px; height:30px; border-radius:8px; background:rgba(255,255,255,.06); display:flex; align-items:center; justify-content:center; flex:none; font-size:14px; }
          .ph-t-titulo { font-weight:600; font-size:12.8px; color:#fff; line-height:1.35; word-break:break-word; cursor:pointer; }
          .ph-t-titulo:hover { color:var(--accent-purple); }
          .ph-t-meta { font-size:10.5px; color:var(--text-muted); display:flex; gap:8px; flex-wrap:wrap; }
          .ph-t-nota { font-size:11.5px; color:var(--text-main); line-height:1.45; }
          .ph-etq { font-size:10px; padding:0 7px; border-radius:9px; background:rgba(137,180,250,.12); color:#89b4fa; }
          .ph-origen { font-size:10px; padding:0 7px; border-radius:9px; background:rgba(255,255,255,.06); color:var(--text-muted); }
          .ph-origen.propio { background:rgba(166,227,161,.12); color:var(--accent-green); }
          .ph-t-acc { display:flex; gap:5px; flex-wrap:wrap; margin-top:auto; }
          .ph-estado { font-size:10.5px; border-radius:6px; border:1px solid var(--border-color); background:var(--bg-dark); color:var(--text-main); padding:2px 4px; }
          .ph-estado.terminado { color:var(--accent-green); border-color:rgba(166,227,161,.45); }
          .ph-estado.en_curso { color:var(--accent-yellow, #f9e2af); border-color:rgba(249,226,175,.45); }
          .ph-vacio { text-align:center; color:var(--text-muted); padding:40px 20px; line-height:1.6; font-size:12.5px; }
          .ph-vacio i.grande { font-size:34px; color:rgba(203,166,247,.5); display:block; margin-bottom:10px; }
          .ph-error { font-size:12px; color:var(--accent-red); background:rgba(243,139,168,.08); border:1px solid rgba(243,139,168,.3); border-radius:6px; padding:8px 10px; margin:8px 0; }
          .ph-ok { font-size:12px; color:var(--accent-green); }
          .ph-aviso { font-size:11.5px; color:var(--accent-yellow, #f9e2af); background:rgba(249,226,175,.07); border:1px solid rgba(249,226,175,.3); border-radius:6px; padding:8px 10px; margin:8px 0; line-height:1.5; }
          .ph-progreso { height:6px; border-radius:3px; background:rgba(255,255,255,.07); overflow:hidden; }
          .ph-progreso > div { height:100%; background:var(--accent-green); }
          .ph-pasos { display:flex; flex-direction:column; gap:6px; margin-top:12px; }
          .ph-paso { display:flex; gap:10px; align-items:flex-start; padding:9px 11px; border:1px solid var(--border-color); border-radius:9px; background:var(--bg-panel); }
          .ph-paso.hecho { border-color:rgba(166,227,161,.35); }
          .ph-paso-n { width:24px; height:24px; border-radius:50%; background:rgba(203,166,247,.15); color:var(--accent-purple); display:flex; align-items:center; justify-content:center; font-size:11px; font-weight:700; flex:none; cursor:pointer; border:none; }
          .ph-paso.hecho .ph-paso-n { background:var(--accent-green); color:#11111b; }
          .ph-codigo { background:#11111b; border:1px solid var(--border-color); border-radius:8px; padding:10px 12px; font-family:'Fira Code',monospace; font-size:11.5px; white-space:pre; overflow:auto; max-height:320px; margin:4px 0 10px; }
          .ph-sec { font-size:12px; font-weight:700; color:#fff; margin:14px 0 4px; display:flex; gap:6px; align-items:center; }
          .ph-cambios li { font-size:12px; margin:2px 0; }
          .ph-mas { color:var(--accent-green); } .ph-menos { color:var(--accent-red); } .ph-cambia { color:var(--accent-yellow, #f9e2af); }
          .ph-chat { border-top:1px solid var(--border-color); margin-top:10px; padding-top:8px; }
          .ph-msgs { max-height:260px; overflow-y:auto; display:flex; flex-direction:column; gap:6px; margin-bottom:6px; }
          .ph-msg { padding:6px 10px; border-radius:8px; font-size:12px; line-height:1.5; max-width:92%; }
          .ph-msg.usuario { align-self:flex-end; background:rgba(203,166,247,.14); }
          .ph-msg.tutor { align-self:flex-start; background:rgba(255,255,255,.05); }
          .ph-rejilla2 { display:grid; grid-template-columns:1fr 1fr; gap:8px; }
          .ph-editor-paso { display:grid; grid-template-columns:1fr 1.6fr 1fr auto; gap:6px; align-items:center; margin-bottom:6px; }
          @container (max-width: 780px) {
            #prig-hub-raiz { grid-template-columns:52px 1fr; }
            .ph-nav { padding:10px 6px; align-items:center; }
            .ph-logo { font-size:0; padding:2px 0 10px; gap:0; } .ph-logo i { font-size:20px; }
            .ph-sub { display:none; }
            .ph-nav-item { font-size:0; gap:0; padding:9px; justify-content:center; position:relative; }
            .ph-nav-item i { font-size:14px; }
            .ph-nav-item .ph-cuenta, .ph-nav-item .ph-punto { position:absolute; top:2px; right:2px; font-size:8px; }
            .ph-rejilla2, .ph-editor-paso { grid-template-columns:1fr; }
          }
        `;
        document.head.appendChild(css);
    }

    // ================================================================== carga
    async function cargar() {
        estado.cargando = true;
        estado.error = null;
        try {
            const [datos, info] = await Promise.all([json('/api/hub/todo'), json('/api/hub/estado')]);
            estado.datos = datos;
            estado.info = info;
        } catch (e) { estado.error = e.message; }
        estado.cargando = false;
        pintarNav();
        pintar();
    }

    const propios = () => (estado.datos ? estado.datos.repos.propios : []).filter(r => !r.error);
    const sigo = () => (estado.datos ? estado.datos.repos.sigo : []);

    // ================================================================== navegación
    const VISTAS = [
        ['todo', 'fa-layer-group', 'Todo'], ['rutas', 'fa-route', 'Rutas'], ['desafios', 'fa-chess-knight', 'Desafíos'],
        ['siguiendo', 'fa-users', 'Siguiendo'], ['descubrir', 'fa-compass', 'Descubrir'], ['repos', 'fa-box-archive', 'Mis repos'],
    ];

    function montar() {
        const r = $('prig-hub-raiz');
        if (!r || $('ph-nav')) return;
        estilos();
        r.innerHTML = `
          <nav class="ph-nav" id="ph-nav"></nav>
          <main class="ph-hoja" id="ph-hoja"></main>`;
        pintarNav();
        cargar();
    }

    function pintarNav() {
        const nav = $('ph-nav');
        if (!nav) return;
        const d = estado.datos;
        const cuentas = d ? { todo: d.elementos.length, rutas: d.rutas.length, desafios: d.desafios.length, siguiendo: sigo().length, repos: propios().length } : {};
        const pendientes = sigo().some(s => s.pendiente);
        nav.innerHTML = `
          <div class="ph-logo"><i class="fa-solid fa-circle-nodes"></i> Prig Hub</div>
          <div class="ph-sub">Tu aprendizaje en texto plano, versionado en git.</div>
          ${VISTAS.map(([id, icono, nombre]) => `<button class="ph-nav-item ${estado.vista === id ? 'activa' : ''}" data-vista="${id}" title="${nombre}">
              <i class="fa-solid ${icono}"></i> ${nombre}
              ${id === 'siguiendo' && pendientes ? '<span class="ph-punto" title="Hay novedades por revisar"></span>' : (cuentas[id] ? `<span class="ph-cuenta">${cuentas[id]}</span>` : '')}</button>`).join('')}
          <span style="flex:1"></span>
          <div class="ph-sub" style="padding-bottom:0;"><a href="#" id="ph-formato"><i class="fa-solid fa-file-lines"></i> Formato de los archivos</a></div>`;
        nav.querySelectorAll('[data-vista]').forEach(b => b.onclick = () => ir(b.dataset.vista));
        $('ph-formato').onclick = (e) => { e.preventDefault(); verFormato(); };
    }

    function ir(vista) {
        estado.vista = vista;
        guardarLocal('prig_hub_vista', vista);
        if (vista !== 'rutas') estado.ruta = null;
        if (vista !== 'desafios') estado.desafio = null;
        pintarNav();
        pintar();
    }

    function pintar() {
        const h = $('ph-hoja');
        if (!h) return;
        if (estado.cargando && !estado.datos) { h.innerHTML = '<div class="ph-vacio"><i class="fa-solid fa-spinner fa-spin grande"></i>Leyendo tus repositorios…</div>'; return; }
        if (estado.error && !estado.datos) { h.innerHTML = `<div class="ph-error">${esc(estado.error)}</div><button class="ph-btn" id="ph-reintentar">Reintentar</button>`; $('ph-reintentar').onclick = cargar; return; }
        ({ todo: vistaTodo, rutas: vistaRutas, desafios: vistaDesafios, siguiendo: vistaSiguiendo, descubrir: vistaDescubrir, repos: vistaRepos }[estado.vista] || vistaTodo)(h);
    }

    // ================================================================== agregar enlace (un solo campo)
    function opcionesDestino(sel) {
        return propios().map(r => `<option value="${esc(r.nombre)}" ${r.nombre === sel ? 'selected' : ''}>${r.nombre === 'prig' ? 'Mi perfil' : esc(r.titulo)}</option>`).join('');
    }

    function cajaAgregar() {
        return `
          <div class="ph-agregar">
            <div class="ph-fila">
              <input type="text" class="ph-campo" id="ph-enlace" placeholder="Pega un enlace (video, curso, notebook, repo, canal…) o un usuario de GitHub para seguir su perfil" autocomplete="off">
              <button class="ph-btn morado" id="ph-analizar"><i class="fa-solid fa-wand-magic-sparkles"></i> Agregar</button>
            </div>
            <div id="ph-analisis"></div>
          </div>`;
    }

    function enlazarAgregar() {
        const campo = $('ph-enlace');
        if (!campo) return;
        const lanzar = () => analizar(campo.value);
        $('ph-analizar').onclick = lanzar;
        campo.onkeydown = (e) => { if (e.key === 'Enter') lanzar(); };
        campo.onpaste = () => setTimeout(lanzar, 30);
    }

    async function analizar(texto) {
        const zona = $('ph-analisis');
        if (!zona || !(texto || '').trim()) return;
        zona.innerHTML = '<div class="ph-analisis ph-ayuda"><span><i class="fa-solid fa-spinner fa-spin"></i> Reconociendo el enlace…</span></div>';
        try {
            const a = await enviar('/api/hub/analizar', { texto });
            estado.analisis = a;
            pintarAnalisis();
        } catch (e) { zona.innerHTML = `<div class="ph-error">${esc(e.message)}</div>`; }
    }

    function pintarAnalisis() {
        const a = estado.analisis;
        const zona = $('ph-analisis');
        if (!a || !zona) return;
        const icono = PLAT_ICONO[a.plataforma] || `fa-solid ${ICONOS[a.tipo] || 'fa-link'}`;
        if (a.sugerencia === 'seguir') {
            zona.innerHTML = `<div class="ph-analisis">
                <div class="ph-fila"><i class="${icono}" style="font-size:18px;"></i>
                  <div><b>${esc(a.ref)}</b> es un repositorio de <b>Prig Hub</b>.<div class="ph-ayuda">Síguelo para ver sus recursos, rutas y desafíos junto a los tuyos. Sus actualizaciones las revisas antes de aplicarlas.</div></div></div>
                <div class="ph-fila">${a.ya_sigo ? '<span class="ph-ok"><i class="fa-solid fa-check"></i> Ya lo sigues</span>'
                    : `<button class="ph-btn verde" id="ph-seguir-a"><i class="fa-solid fa-user-plus"></i> Seguir</button>`}
                  <button class="ph-btn" id="ph-como-recurso">Guardarlo solo como repositorio</button></div>
                <div id="ph-a-estado"></div></div>`;
            if ($('ph-seguir-a')) $('ph-seguir-a').onclick = () => seguir(a.url, $('ph-a-estado'));
            $('ph-como-recurso').onclick = () => { estado.analisis = { ...a, sugerencia: 'recurso' }; pintarAnalisis(); };
            return;
        }
        const tipos = a.sugerencia === 'persona' ? ['persona'] : Object.keys(TIPO_NOMBRE).filter(t => t !== 'persona');
        zona.innerHTML = `<div class="ph-analisis">
            <div class="ph-fila"><i class="${icono}" style="font-size:18px; color:${PLAT_COLOR[a.plataforma] || 'inherit'};"></i>
              <span class="ph-ayuda">${esc(a.plataforma_nombre)} · ${esc(TIPO_NOMBRE[a.tipo] || a.tipo)}${a.autor ? ` · ${esc(a.autor)}` : ''} · <code>${esc(a.clave)}</code></span></div>
            <div class="ph-rejilla2">
              <input type="text" class="ph-campo" id="ph-a-titulo" placeholder="Título" value="${esc(a.titulo)}">
              <select class="ph-campo" id="ph-a-tipo">${tipos.map(t => `<option value="${t}" ${t === a.tipo ? 'selected' : ''}>${TIPO_NOMBRE[t]}</option>`).join('')}</select>
              <input type="text" class="ph-campo" id="ph-a-nota" placeholder="Nota (por qué lo guardas)">
              <input type="text" class="ph-campo" id="ph-a-etq" placeholder="Etiquetas: python, pandas…">
            </div>
            <div class="ph-fila">
              <span class="ph-ayuda">Guardar en</span>
              <select class="ph-campo" id="ph-a-destino">${opcionesDestino(estado.destino)}</select>
              <button class="ph-btn verde" id="ph-a-guardar"><i class="fa-solid fa-plus"></i> ${a.sugerencia === 'persona' ? 'Seguir a esta persona' : 'Guardar'}</button>
              <button class="ph-btn" id="ph-a-cancelar">Cancelar</button>
            </div>
            <div id="ph-a-estado"></div></div>`;
        $('ph-a-cancelar').onclick = () => { estado.analisis = null; $('ph-analisis').innerHTML = ''; };
        $('ph-a-guardar').onclick = async () => {
            const b = $('ph-a-guardar');
            b.disabled = true;
            estado.destino = $('ph-a-destino').value;
            guardarLocal('prig_hub_destino', estado.destino);
            try {
                await enviar('/api/hub/agregar', {
                    destino: estado.destino, url: a.url, titulo: $('ph-a-titulo').value, nota: $('ph-a-nota').value,
                    etiquetas: $('ph-a-etq').value.split(/[,\s]+/).filter(Boolean), tipo: $('ph-a-tipo').value,
                });
                estado.analisis = null;
                if ($('ph-enlace')) $('ph-enlace').value = '';
                window.layoutMgr?.mensajeEstado('Guardado en Prig Hub', 1800);
                await cargar();
            } catch (e) { $('ph-a-estado').innerHTML = `<div class="ph-error">${esc(e.message)}</div>`; b.disabled = false; }
        };
    }

    // ================================================================== abrir un elemento en Prig
    function abrirElemento(e) {
        const url = e.url;
        if (e.plataforma === 'kaggle' && ['notebook', 'dataset', 'competicion'].includes(e.tipo) && window.KaggleLector) {
            window.KaggleLector.abrir();
            setTimeout(() => window.KaggleLector.ir({ tipo: e.tipo, ref: url }), 50);
            return;
        }
        if (e.plataforma === 'github' && ['repositorio', 'archivo'].includes(e.tipo) && window.GitHubLector) {
            window.GitHubLector.abrir({ ref: e.ref });
            return;
        }
        if (e.plataforma === 'youtube' && e.tipo === 'video' && window.YouTubeHub) {
            window.YouTubeHub.abrir({ url });
            return;
        }
        window.open(url, '_blank', 'noopener');
    }

    async function marcar(clave, valor, origen, version) {
        try {
            await enviar('/api/hub/progreso', { clave, estado: valor || 'quitar', origen: origen || '', version: version || '' });
            await cargar();
        } catch (err) { window.layoutMgr?.mensajeEstado(err.message, 3000); }
    }

    function selectorProgreso(clave, actual, origen, version) {
        return `<select class="ph-estado ${actual || ''}" data-progreso="${esc(clave)}" data-origen="${esc(origen || '')}" data-version="${esc(version || '')}" title="Tu progreso (solo en tu equipo)">
            <option value="" ${!actual ? 'selected' : ''}>Sin empezar</option>
            ${Object.entries(ESTADO_NOMBRE).map(([k, v]) => `<option value="${k}" ${actual === k ? 'selected' : ''}>${v}</option>`).join('')}
          </select>`;
    }

    function enlazarProgreso(raiz) {
        raiz.querySelectorAll('[data-progreso]').forEach(s => s.onchange = () => marcar(s.dataset.progreso, s.value, s.dataset.origen, s.dataset.version));
    }

    // ================================================================== Todo
    function filtrar(lista) {
        const f = estado.filtros;
        const q = f.q.trim().toLowerCase();
        return lista.filter(e => (!f.plataforma || e.plataforma === f.plataforma)
            && (!f.tipo || (f.tipo === 'persona' ? e.tipo === 'persona' : e.tipo === f.tipo))
            && (!f.origen || e.origenes.some(o => o.id === f.origen))
            && (!f.progreso || (f.progreso === 'sin' ? !e.progreso : e.progreso === f.progreso))
            && (!q || `${e.titulo} ${e.url} ${e.nota} ${(e.etiquetas || []).join(' ')}`.toLowerCase().includes(q)));
    }

    function tarjeta(e) {
        const icono = PLAT_ICONO[e.plataforma] || `fa-solid ${ICONOS[e.tipo] || 'fa-link'}`;
        const propio = e.origenes.find(o => o.propio);
        const origen0 = e.origenes[0];
        return `<div class="ph-tarjeta ${e.progreso === 'terminado' ? 'terminado' : ''}" data-clave="${esc(e.clave)}">
            <div class="ph-t-cab">
              <div class="ph-t-icono" style="color:${PLAT_COLOR[e.plataforma] || 'var(--text-main)'};"><i class="${icono}"></i></div>
              <div style="min-width:0; flex:1;">
                <div class="ph-t-titulo" data-abrir title="Abrir">${esc(e.titulo || e.url)}</div>
                <div class="ph-t-meta"><span><i class="fa-solid ${ICONOS[e.tipo] || 'fa-link'}"></i> ${esc(TIPO_NOMBRE[e.tipo] || e.tipo)}</span>
                  ${e.minutos ? `<span><i class="fa-regular fa-clock"></i> ${e.minutos} min</span>` : ''}
                  ${e.nivel ? `<span>${esc(e.nivel)}</span>` : ''}</div>
              </div>
            </div>
            ${e.nota ? `<div class="ph-t-nota">${esc(e.nota)}</div>` : ''}
            <div class="ph-fila" style="gap:4px;">
              ${(e.etiquetas || []).map(t => `<span class="ph-etq">${esc(t)}</span>`).join('')}
              ${e.origenes.map(o => `<span class="ph-origen ${o.propio ? 'propio' : ''}" title="${o.propio ? 'Tuyo' : 'De ' + esc(o.autor || o.titulo)}">${o.propio ? '<i class="fa-solid fa-house"></i> ' : '<i class="fa-solid fa-user-group"></i> '}${esc(o.titulo)}</span>`).join('')}
            </div>
            <div class="ph-t-acc">
              ${e.tipo !== 'persona' ? selectorProgreso(e.clave, e.progreso, origen0.id, origen0.version) : ''}
              <button class="ph-btn chico" data-abrir><i class="fa-solid fa-arrow-up-right-from-square"></i> Abrir</button>
              ${!propio ? `<button class="ph-btn chico" data-copiar title="Copiarlo a tu perfil (con atribución)"><i class="fa-solid fa-copy"></i> A mi perfil</button>` : ''}
              ${propio ? `<button class="ph-btn chico rojo" data-quitar="${esc(propio.id)}" title="Quitarlo de ${esc(propio.titulo)}"><i class="fa-solid fa-trash"></i></button>` : ''}
            </div>
          </div>`;
    }

    function vistaTodo(h) {
        const d = estado.datos;
        const f = estado.filtros;
        const lista = filtrar(d.elementos);
        const plataformas = [...new Set(d.elementos.map(e => e.plataforma))];
        const tipos = [...new Set(d.elementos.map(e => e.tipo))];
        const origenes = [...propios(), ...sigo()].filter(r => !r.error);
        h.innerHTML = `
          <div class="ph-h1">Todo lo que sigues</div>
          <div class="ph-ayuda">Tus listas y las de la gente que sigues, juntas. Un mismo enlace en dos listas aparece una sola vez, y tu progreso vale para las dos.</div>
          ${cajaAgregar()}
          ${d.elementos.length ? `
          <div class="ph-fila">
            <input type="text" class="ph-campo" id="ph-q" placeholder="Filtrar…" value="${esc(f.q)}" style="flex:1; min-width:160px;">
            <select class="ph-campo" id="ph-f-origen"><option value="">Todos los orígenes</option>${origenes.map(r => `<option value="${esc(r.origen)}" ${f.origen === r.origen ? 'selected' : ''}>${r.origen.startsWith('propio:') ? '🏠 ' : '👥 '}${esc(r.nombre === 'prig' ? 'Mi perfil' : r.titulo)}</option>`).join('')}</select>
            <select class="ph-campo" id="ph-f-progreso"><option value="">Cualquier estado</option><option value="sin" ${f.progreso === 'sin' ? 'selected' : ''}>Sin empezar</option>${Object.entries(ESTADO_NOMBRE).map(([k, v]) => `<option value="${k}" ${f.progreso === k ? 'selected' : ''}>${v}</option>`).join('')}</select>
          </div>
          <div class="ph-chips">
            <button class="ph-chip ${!f.plataforma ? 'activo' : ''}" data-plataforma="">Todas</button>
            ${plataformas.map(p => `<button class="ph-chip ${f.plataforma === p ? 'activo' : ''}" data-plataforma="${esc(p)}"><i class="${PLAT_ICONO[p] || 'fa-solid fa-link'}"></i> ${esc(d.plataformas[p] || p)}</button>`).join('')}
          </div>
          <div class="ph-chips">
            <button class="ph-chip ${!f.tipo ? 'activo' : ''}" data-tipo="">Todo tipo</button>
            ${tipos.map(t => `<button class="ph-chip ${f.tipo === t ? 'activo' : ''}" data-tipo="${esc(t)}"><i class="fa-solid ${ICONOS[t] || 'fa-link'}"></i> ${esc(TIPO_NOMBRE[t] || t)}</button>`).join('')}
          </div>
          <div class="ph-lista">${lista.map(tarjeta).join('') || '<div class="ph-vacio">Nada con esos filtros.</div>'}</div>`
          : `<div class="ph-vacio"><i class="fa-solid fa-circle-nodes grande"></i>
              Pega arriba un enlace de YouTube, Kaggle, GitHub, un curso o un artículo y queda guardado en tu perfil, en texto plano.<br>
              Pega un usuario de GitHub para seguir su perfil de Prig, o busca packs en <a href="#" data-ir="descubrir">Descubrir</a>.</div>`}
          ${d.avisos.length ? `<div class="ph-aviso"><b>${d.avisos.length} avisos</b> al leer los repositorios (lo que no se entendió se saltó). <a href="#" data-ir="repos">Ver en Mis repos</a></div>` : ''}`;
        enlazarAgregar();
        h.querySelectorAll('[data-ir]').forEach(a => a.onclick = (e) => { e.preventDefault(); ir(a.dataset.ir); });
        if (!d.elementos.length) return;
        const refiltrar = () => { const pos = $('ph-q').selectionStart; pintar(); const q = $('ph-q'); q.focus(); q.setSelectionRange(pos, pos); };
        $('ph-q').oninput = (e) => { f.q = e.target.value; refiltrar(); };
        $('ph-f-origen').onchange = (e) => { f.origen = e.target.value; pintar(); };
        $('ph-f-progreso').onchange = (e) => { f.progreso = e.target.value; pintar(); };
        h.querySelectorAll('[data-plataforma]').forEach(b => b.onclick = () => { f.plataforma = b.dataset.plataforma; pintar(); });
        h.querySelectorAll('[data-tipo]').forEach(b => b.onclick = () => { f.tipo = b.dataset.tipo; pintar(); });
        enlazarProgreso(h);
        h.querySelectorAll('.ph-tarjeta').forEach(t => {
            const e = d.elementos.find(x => x.clave === t.dataset.clave);
            t.querySelectorAll('[data-abrir]').forEach(b => b.onclick = () => abrirElemento(e));
            const copiar = t.querySelector('[data-copiar]');
            if (copiar) copiar.onclick = async () => {
                copiar.disabled = true;
                try { await enviar('/api/hub/copiar', { origen: e.origenes[0].id, clave: e.clave, destino: 'prig' }); await cargar(); }
                catch (err) { window.layoutMgr?.mensajeEstado(err.message, 3000); copiar.disabled = false; }
            };
            const quitar = t.querySelector('[data-quitar]');
            if (quitar) quitar.onclick = async () => {
                if (!confirm(`¿Quitar «${e.titulo || e.url}» de tu lista?`)) return;
                try { await enviar('/api/hub/quitar', { destino: quitar.dataset.quitar, clave: e.clave }); await cargar(); }
                catch (err) { window.layoutMgr?.mensajeEstado(err.message, 3000); }
            };
        });
    }

    // ================================================================== Rutas
    function vistaRutas(h) {
        const d = estado.datos;
        if (estado.ruta) return vistaRuta(h);
        h.innerHTML = `
          <div class="ph-fila" style="justify-content:space-between;"><div><div class="ph-h1">Rutas</div>
            <div class="ph-ayuda">Pasos en orden: videos, notebooks, repositorios y desafíos. Tu avance se guarda por enlace, así que reordenar una ruta no lo pierde.</div></div>
            <button class="ph-btn morado" id="ph-nueva-ruta"><i class="fa-solid fa-plus"></i> Nueva ruta</button></div>
          <div class="ph-lista">${d.rutas.map((r, i) => {
              const pct = r.pasos.length ? Math.round(100 * r.hechos / r.pasos.length) : 0;
              return `<div class="ph-tarjeta" data-ruta="${i}">
                <div class="ph-t-cab"><div class="ph-t-icono" style="color:var(--accent-purple);"><i class="fa-solid fa-route"></i></div>
                  <div style="flex:1; min-width:0;"><div class="ph-t-titulo" data-abrir>${esc(r.titulo)}</div>
                  <div class="ph-t-meta"><span>${r.pasos.length} pasos</span>${r.nivel ? `<span>${esc(r.nivel)}</span>` : ''}
                    <span class="ph-origen ${r.origen.propio ? 'propio' : ''}">${esc(r.origen.titulo)}</span></div></div></div>
                ${r.descripcion ? `<div class="ph-t-nota">${esc(r.descripcion)}</div>` : ''}
                <div class="ph-progreso" title="${r.hechos} de ${r.pasos.length}"><div style="width:${pct}%"></div></div>
                <div class="ph-t-acc"><button class="ph-btn chico" data-abrir><i class="fa-solid fa-play"></i> ${r.hechos ? 'Seguir' : 'Empezar'}</button>
                  <span class="ph-ayuda">${r.hechos}/${r.pasos.length}</span></div></div>`;
          }).join('') || '<div class="ph-vacio"><i class="fa-solid fa-route grande"></i>Todavía no hay rutas. Crea una con tus recursos o sigue un pack que traiga rutas.</div>'}</div>`;
        $('ph-nueva-ruta').onclick = () => editorRuta();
        h.querySelectorAll('[data-ruta]').forEach(t => t.querySelectorAll('[data-abrir]').forEach(b => b.onclick = () => {
            estado.ruta = d.rutas[+t.dataset.ruta];
            pintar();
        }));
    }

    /** El texto del paso sin repetir el título (en Markdown el título es el texto del enlace) */
    function notaPaso(p) {
        let t = (p.texto || '').trim();
        if (p.titulo && t.startsWith(p.titulo)) t = t.slice(p.titulo.length).replace(/^[\s—–:-]+/, '');
        return t;
    }

    function vistaRuta(h) {
        const d = estado.datos;
        const r = d.rutas.find(x => x.id === estado.ruta.id && x.origen.id === estado.ruta.origen.id) || estado.ruta;
        const pct = r.pasos.length ? Math.round(100 * r.hechos / r.pasos.length) : 0;
        h.innerHTML = `
          <button class="ph-btn chico" id="ph-volver"><i class="fa-solid fa-arrow-left"></i> Rutas</button>
          <div class="ph-h1" style="margin-top:10px;">${esc(r.titulo)}</div>
          <div class="ph-ayuda">${esc(r.origen.titulo)}${r.nivel ? ` · ${esc(r.nivel)}` : ''} · ${r.hechos} de ${r.pasos.length} pasos</div>
          <div class="ph-progreso" style="margin:8px 0;"><div style="width:${pct}%"></div></div>
          ${r.descripcion ? `<div class="ph-t-nota">${esc(r.descripcion)}</div>` : ''}
          <div id="ph-intro" class="ph-t-nota"></div>
          <div class="ph-pasos">${r.pasos.map((p, i) => {
              const dest = p.destino || {};
              const hecho = p.progreso === 'terminado';
              const icono = dest.tipo === 'desafio' ? 'fa-solid fa-chess-knight' : (PLAT_ICONO[dest.plataforma] || `fa-solid ${ICONOS[dest.tipo] || 'fa-link'}`);
              return `<div class="ph-paso ${hecho ? 'hecho' : ''}">
                <button class="ph-paso-n" data-hecho="${i}" title="${hecho ? 'Marcar como no hecho' : 'Marcar como hecho'}">${hecho ? '<i class="fa-solid fa-check"></i>' : p.n}</button>
                <div style="flex:1; min-width:0;"><div style="font-weight:600; font-size:12.5px;"><i class="${icono}"></i> ${esc(p.titulo || dest.url || 'Paso')}</div>
                  ${notaPaso(p) ? `<div class="ph-ayuda">${esc(notaPaso(p))}</div>` : ''}</div>
                ${p.destino ? `<button class="ph-btn chico" data-ir-paso="${i}">${dest.tipo === 'desafio' ? 'Ver desafío' : 'Abrir'}</button>` : ''}</div>`;
          }).join('')}</div>
          ${r.origen.propio ? `<div class="ph-fila" style="margin-top:14px;"><button class="ph-btn" id="ph-editar-ruta"><i class="fa-solid fa-pen"></i> Editar</button>
             <button class="ph-btn rojo" id="ph-borrar-ruta"><i class="fa-solid fa-trash"></i> Borrar</button></div>` : ''}`;
        if (r.introduccion) md($('ph-intro'), r.introduccion);
        $('ph-volver').onclick = () => { estado.ruta = null; pintar(); };
        h.querySelectorAll('[data-hecho]').forEach(b => b.onclick = () => {
            const p = r.pasos[+b.dataset.hecho];
            if (p.clave) marcar(p.clave, p.progreso === 'terminado' ? '' : 'terminado', r.origen.id, r.origen.version);
        });
        h.querySelectorAll('[data-ir-paso]').forEach(b => b.onclick = () => {
            const p = r.pasos[+b.dataset.irPaso];
            if (p.destino.tipo === 'desafio') { estado.desafio = { origen: r.origen.id, id: p.destino.id }; ir('desafios'); return; }
            abrirElemento(p.destino);
            if (!p.progreso && p.clave) marcar(p.clave, 'en_curso', r.origen.id, r.origen.version);
        });
        if ($('ph-editar-ruta')) $('ph-editar-ruta').onclick = () => editorRuta(r);
        if ($('ph-borrar-ruta')) $('ph-borrar-ruta').onclick = async () => {
            if (!confirm(`¿Borrar la ruta «${r.titulo}»? Queda en el historial de git del repositorio.`)) return;
            try { await enviar('/api/hub/rutas/borrar', { destino: r.origen.id, id: r.id }); estado.ruta = null; await cargar(); }
            catch (e) { alert(e.message); }
        };
    }

    function editorRuta(r = null) {
        const d = estado.datos;
        const h = $('ph-hoja');
        const pasos = r ? r.pasos.map(p => ({ titulo: p.titulo, destino: p.destino ? (p.destino.tipo === 'desafio' ? `desafio:${p.destino.id}` : p.destino.url) : '', nota: '' }))
            : [{ titulo: '', destino: '', nota: '' }];
        const destino = r ? r.origen.id.split(':')[1] : estado.destino;
        const sugerencias = d.elementos.filter(e => e.tipo !== 'persona');
        h.innerHTML = `
          <button class="ph-btn chico" id="ph-volver"><i class="fa-solid fa-arrow-left"></i> Rutas</button>
          <div class="ph-h1" style="margin-top:10px;">${r ? 'Editar ruta' : 'Nueva ruta'}</div>
          <div class="ph-ayuda">Cada paso es un enlace (o un desafío de este repositorio: <code>desafio:&lt;id&gt;</code>). Se guarda como Markdown en <code>rutas/</code>.</div>
          <div class="ph-rejilla2" style="margin-top:10px;">
            <input class="ph-campo" id="ph-r-titulo" placeholder="Título" value="${esc(r ? r.titulo : '')}">
            <select class="ph-campo" id="ph-r-destino" ${r ? 'disabled' : ''}>${opcionesDestino(destino)}</select>
            <input class="ph-campo" id="ph-r-desc" placeholder="Descripción breve" value="${esc(r ? r.descripcion : '')}">
            <select class="ph-campo" id="ph-r-nivel"><option value="">Nivel</option>${['principiante', 'intermedio', 'avanzado'].map(n => `<option ${r && r.nivel === n ? 'selected' : ''}>${n}</option>`).join('')}</select>
          </div>
          <div class="ph-sec">Pasos</div>
          <datalist id="ph-r-sugerencias">${sugerencias.map(e => `<option value="${esc(e.url)}">${esc(e.titulo || e.url)}</option>`).join('')}</datalist>
          <div id="ph-r-pasos"></div>
          <button class="ph-btn chico" id="ph-r-mas"><i class="fa-solid fa-plus"></i> Paso</button>
          <div class="ph-fila" style="margin-top:14px;"><button class="ph-btn verde" id="ph-r-guardar"><i class="fa-solid fa-floppy-disk"></i> Guardar ruta</button><span id="ph-r-estado"></span></div>`;
        const pintarPasos = () => {
            $('ph-r-pasos').innerHTML = pasos.map((p, i) => `<div class="ph-editor-paso">
                <input class="ph-campo" data-i="${i}" data-k="titulo" placeholder="Paso ${i + 1}: título" value="${esc(p.titulo)}">
                <input class="ph-campo" data-i="${i}" data-k="destino" list="ph-r-sugerencias" placeholder="Enlace o desafio:id" value="${esc(p.destino)}">
                <input class="ph-campo" data-i="${i}" data-k="nota" placeholder="Nota" value="${esc(p.nota)}">
                <button class="ph-btn chico rojo" data-quitar-paso="${i}" title="Quitar paso"><i class="fa-solid fa-xmark"></i></button></div>`).join('');
            $('ph-r-pasos').querySelectorAll('[data-k]').forEach(c => c.oninput = () => {
                pasos[+c.dataset.i][c.dataset.k] = c.value;
                if (c.dataset.k === 'destino' && !pasos[+c.dataset.i].titulo) {
                    const e = sugerencias.find(x => x.url === c.value);
                    if (e) { pasos[+c.dataset.i].titulo = e.titulo; pintarPasos(); }
                }
            });
            $('ph-r-pasos').querySelectorAll('[data-quitar-paso]').forEach(b => b.onclick = () => { pasos.splice(+b.dataset.quitarPaso, 1); pintarPasos(); });
        };
        pintarPasos();
        $('ph-volver').onclick = () => pintar();
        $('ph-r-mas').onclick = () => { pasos.push({ titulo: '', destino: '', nota: '' }); pintarPasos(); };
        $('ph-r-guardar').onclick = async () => {
            const b = $('ph-r-guardar');
            b.disabled = true;
            try {
                const res = await enviar('/api/hub/rutas', {
                    destino: r ? r.origen.id : $('ph-r-destino').value, id: r ? r.id : '', titulo: $('ph-r-titulo').value,
                    descripcion: $('ph-r-desc').value, nivel: $('ph-r-nivel').value, introduccion: r ? r.introduccion : '',
                    etiquetas: r ? r.etiquetas : [], pasos: pasos.filter(p => p.destino.trim()),
                });
                await cargar();
                const nueva = estado.datos.rutas.find(x => x.id === res.id && x.origen.propio);
                estado.ruta = nueva || null;
                ir('rutas');
            } catch (e) { $('ph-r-estado').innerHTML = `<span class="ph-error">${esc(e.message)}</span>`; b.disabled = false; }
        };
    }

    // ================================================================== Desafíos
    function vistaDesafios(h) {
        if (estado.desafio) return vistaDesafio(h);
        const d = estado.datos;
        h.innerHTML = `
          <div class="ph-h1">Desafíos de los packs</div>
          <div class="ph-ayuda">Antes de importar un desafío ves todo su código. Al importarlo, Prig lo verifica <b>ejecutándolo en tu equipo</b>: la solución tiene que pasar sus pruebas y el código de partida no.</div>
          <div class="ph-lista">${d.desafios.map((x, i) => `<div class="ph-tarjeta" data-i="${i}">
              <div class="ph-t-cab"><div class="ph-t-icono" style="color:var(--accent-purple);"><i class="fa-solid fa-chess-knight"></i></div>
                <div style="flex:1; min-width:0;"><div class="ph-t-titulo" data-ver>${esc(x.titulo)}</div>
                <div class="ph-t-meta">${x.nivel ? `<span>${esc(x.nivel)}</span>` : ''}<span class="ph-origen ${x.origen.propio ? 'propio' : ''}">${esc(x.origen.titulo)}</span>
                  ${x.verificable ? '' : '<span style="color:var(--accent-red);">incompleto</span>'}</div></div></div>
              <div class="ph-fila" style="gap:4px;">${(x.etiquetas || []).map(t => `<span class="ph-etq">${esc(t)}</span>`).join('')}</div>
              <div class="ph-t-acc">${selectorProgreso(x.clave, x.progreso, x.origen.id, x.origen.version)}
                <button class="ph-btn chico" data-ver><i class="fa-solid fa-eye"></i> Ver código</button></div></div>`).join('')
            || '<div class="ph-vacio"><i class="fa-solid fa-chess-knight grande"></i>Ningún pack trae desafíos todavía. Comparte uno tuyo desde <b>Mis repos → Agregar desafío</b>.</div>'}</div>`;
        enlazarProgreso(h);
        h.querySelectorAll('.ph-tarjeta').forEach(t => t.querySelectorAll('[data-ver]').forEach(b => b.onclick = () => {
            const x = d.desafios[+t.dataset.i];
            estado.desafio = { origen: x.origen.id, id: x.id };
            pintar();
        }));
    }

    async function vistaDesafio(h) {
        const { origen, id } = estado.desafio;
        h.innerHTML = '<div class="ph-vacio"><i class="fa-solid fa-spinner fa-spin"></i> Leyendo el desafío…</div>';
        let x;
        try { x = await json(`/api/hub/desafio?origen=${encodeURIComponent(origen)}&id=${encodeURIComponent(id)}`); }
        catch (e) { h.innerHTML = `<div class="ph-error">${esc(e.message)}</div>`; return; }
        const ajeno = !x.origen.propio;
        const bloque = (titulo, archivos) => archivos.map(a => `<div class="ph-ayuda"><i class="fa-solid fa-file-code"></i> ${titulo}/${esc(a.nombre)}</div><div class="ph-codigo">${esc(a.contenido)}</div>`).join('');
        h.innerHTML = `
          <button class="ph-btn chico" id="ph-volver"><i class="fa-solid fa-arrow-left"></i> Desafíos</button>
          <div class="ph-h1" style="margin-top:10px;">${esc(x.titulo)}</div>
          <div class="ph-ayuda">${esc(x.manifiesto.titulo)}${x.manifiesto.autor.nombre ? ` · ${esc(x.manifiesto.autor.nombre)}` : ''} · licencia del código: ${esc(x.manifiesto.licencia.codigo || 'sin declarar')}</div>
          <div id="ph-d-enunciado" class="ph-t-nota" style="margin:10px 0;"></div>
          ${ajeno ? `<div class="ph-aviso"><i class="fa-solid fa-shield-halved"></i> <b>Código de otra persona.</b> Al importarlo, Prig ejecuta su solución y sus pruebas en tu equipo (con límite de tiempo, sin aislamiento completo). Revisa abajo que no haga nada raro: abrir archivos fuera de la carpeta, conectarse a internet, borrar cosas…</div>` : ''}
          ${x.verificable ? '' : '<div class="ph-error">Este desafío está incompleto: le falta el código de partida, la solución o las pruebas.</div>'}
          <div class="ph-sec"><i class="fa-solid fa-code"></i> Código de partida</div>${bloque('inicio', x.inicio)}
          <div class="ph-sec"><i class="fa-solid fa-flask"></i> Pruebas</div>${bloque('pruebas', x.pruebas)}
          <details><summary class="ph-sec" style="cursor:pointer;">Solución de referencia (spoiler)</summary>${bloque('solucion', x.solucion)}</details>
          <div class="ph-fila" style="margin-top:14px;">
            ${ajeno ? '<label class="ph-ayuda"><input type="checkbox" id="ph-d-confirmo"> Revisé el código y quiero ejecutarlo</label>' : ''}
            <button class="ph-btn verde" id="ph-d-importar" ${x.verificable && !ajeno ? '' : 'disabled'}><i class="fa-solid fa-play"></i> Resolver y Ejecutar en Prig IDE</button>
            <span id="ph-d-estado"></span></div>`;
        md($('ph-d-enunciado'), x.enunciado || '');
        $('ph-volver').onclick = () => { estado.desafio = null; pintar(); };
        const confirmo = $('ph-d-confirmo');
        if (confirmo) confirmo.onchange = () => { $('ph-d-importar').disabled = !(confirmo.checked && x.verificable); };
        $('ph-d-importar').onclick = async () => {
            const b = $('ph-d-importar');
            b.disabled = true;
            $('ph-d-estado').innerHTML = '<span class="ph-ayuda"><i class="fa-solid fa-spinner fa-spin"></i> Verificando: ejecutando la solución y las pruebas en local…</span>';
            try {
                const d = await enviar('/api/hub/desafio/importar', { origen, id, confirmado: true });
                $('ph-d-estado').innerHTML = `<span class="ph-ok"><i class="fa-solid fa-check"></i> Verificado con éxito (${d.comprobacion && d.comprobacion.pruebas || 0} pruebas locales) e importado en la sección Desafíos</span>`;
                // Refrescar sin repintar esta vista, para no borrar el mensaje
                json('/api/hub/todo').then(datos => { estado.datos = datos; pintarNav(); }).catch(() => {});
                if (window.Desafios) window.Desafios.abrir({ id: d.id });
            } catch (e) { $('ph-d-estado').innerHTML = `<span class="ph-error">${esc(e.message)}</span>`; b.disabled = false; }
        };
    }

    // ================================================================== Siguiendo
    async function seguir(url, zona) {
        if (zona) zona.innerHTML = '<span class="ph-ayuda"><i class="fa-solid fa-spinner fa-spin"></i> Descargando el repositorio (solo texto)…</span>';
        try {
            const r = await enviar('/api/hub/seguir', { url });
            if (zona) zona.innerHTML = `<span class="ph-ok"><i class="fa-solid fa-check"></i> Ahora sigues «${esc(r.titulo)}»</span>${r.avisos.length ? ` <span class="ph-ayuda">(${r.avisos.length} avisos al leerlo)</span>` : ''}`;
            estado.analisis = null;
            await cargar();
        } catch (e) { if (zona) zona.innerHTML = `<div class="ph-error">${esc(e.message)}</div>`; }
    }

    function resumenCambios(res) {
        const nombres = { personas: 'Personas', recursos: 'Recursos', rutas: 'Rutas', desafios: 'Desafíos' };
        const lineas = [];
        Object.entries(res.secciones).forEach(([sec, c]) => {
            c.agregados.forEach(x => lineas.push(`<li class="ph-mas">+ ${nombres[sec]}: ${esc(x.titulo || x.id)}</li>`));
            c.cambiados.forEach(x => lineas.push(`<li class="ph-cambia">~ ${nombres[sec]}: ${esc(x.titulo || x.id)}</li>`));
            c.quitados.forEach(x => lineas.push(`<li class="ph-menos">− ${nombres[sec]}: ${esc(x.titulo || x.id)}</li>`));
        });
        return `
          ${res.version[0] !== res.version[1] ? `<div class="ph-ayuda">Versión ${esc(res.version[0] || '—')} → <b>${esc(res.version[1] || '—')}</b></div>` : ''}
          ${res.ficha ? '<div class="ph-ayuda">Cambió la ficha del repositorio.</div>' : ''}
          <ul class="ph-cambios" style="margin:6px 0; padding-left:16px;">${lineas.join('') || '<li class="ph-ayuda">Sin cambios en el contenido (quizá solo el README o la licencia).</li>'}</ul>
          ${res.ejecutable.length ? `<div class="ph-aviso"><i class="fa-solid fa-triangle-exclamation"></i> <b>Trae código ejecutable nuevo o cambiado:</b> ${res.ejecutable.map(x => `${esc(x.titulo)} (${esc(x.motivo)})`).join(', ')}. Nada se ejecuta al aplicar; revisa el código antes de importar esos desafíos.</div>` : ''}
          ${res.avisos && res.avisos.length ? `<div class="ph-ayuda">${res.avisos.length} avisos al leer la nueva versión.</div>` : ''}`;
    }

    function vistaSiguiendo(h) {
        const lista = sigo();
        h.innerHTML = `
          <div class="ph-h1">Siguiendo</div>
          <div class="ph-ayuda">Perfiles y packs de otras personas, como copias de solo lectura. Las novedades se descargan, se resumen y <b>solo se aplican si las aceptas</b>.</div>
          <div class="ph-agregar"><div class="ph-fila">
            <input type="text" class="ph-campo" id="ph-seguir-url" placeholder="Enlace del repositorio (github.com/ana/prig-ml) o usuario de GitHub (ana)" style="flex:1; min-width:220px;">
            <button class="ph-btn verde" id="ph-seguir-btn"><i class="fa-solid fa-user-plus"></i> Seguir</button></div><div id="ph-seguir-estado"></div></div>
          ${lista.map(s => {
              const clave = s.origen.split(':')[1];
              const nov = estado.novedades[clave];
              return `<div class="ph-tarjeta" style="margin-bottom:10px;" data-clave="${esc(clave)}">
                <div class="ph-t-cab"><div class="ph-t-icono" style="color:var(--accent-purple);"><i class="fa-solid ${s.tipo === 'perfil' ? 'fa-user' : 'fa-box'}"></i></div>
                  <div style="flex:1; min-width:0;"><div class="ph-t-titulo">${esc(s.titulo || s.nombre)}</div>
                    <div class="ph-t-meta"><span>${s.tipo === 'perfil' ? 'Perfil' : 'Pack'}</span>${s.autor ? `<span>${esc(s.autor)}</span>` : ''}${s.version ? `<span>v${esc(s.version)}</span>` : ''}
                      <span>${Object.entries(s.cuentas || {}).filter(([, n]) => n).map(([k, n]) => `${n} ${k}`).join(' · ')}</span>
                      ${s.url ? `<a href="${esc(s.url)}" target="_blank" rel="noopener noreferrer">${esc(s.url.replace(/^https:\/\//, ''))}</a>` : ''}
                      <span>revisado ${esc(hace(s.revisado))}</span></div></div></div>
                ${s.error ? `<div class="ph-error">${esc(s.error)}</div>` : ''}
                ${s.descripcion ? `<div class="ph-t-nota">${esc(s.descripcion)}</div>` : ''}
                <div data-nov>${nov ? (nov.cargando ? '<span class="ph-ayuda"><i class="fa-solid fa-spinner fa-spin"></i> Buscando novedades…</span>'
                    : nov.error ? `<div class="ph-error">${esc(nov.error)}</div>`
                    : nov.al_dia ? '<span class="ph-ok"><i class="fa-solid fa-check"></i> Al día</span>'
                    : `<div class="ph-aviso" style="color:var(--text-main);"><b>Hay novedades</b>${resumenCambios(nov.resumen)}
                        <div class="ph-fila"><button class="ph-btn verde chico" data-aplicar="${esc(nov.commit)}"><i class="fa-solid fa-check"></i> Aplicar</button>
                        <button class="ph-btn chico" data-descartar>Ahora no</button></div></div>`) : (s.pendiente ? '<span class="ph-aviso" style="display:inline-block;">Tiene novedades sin revisar</span>' : '')}</div>
                <div class="ph-t-acc">
                  <button class="ph-btn chico" data-novedades><i class="fa-solid fa-rotate"></i> Buscar novedades</button>
                  <button class="ph-btn chico" data-filtrar><i class="fa-solid fa-filter"></i> Ver su contenido</button>
                  <button class="ph-btn chico" data-chat><i class="fa-solid fa-comments"></i> Preguntar al tutor</button>
                  <button class="ph-btn chico rojo" data-dejar><i class="fa-solid fa-user-minus"></i> Dejar de seguir</button></div>
                <div data-chat-zona></div></div>`;
          }).join('') || '<div class="ph-vacio"><i class="fa-solid fa-users grande"></i>No sigues a nadie todavía. Pega arriba un usuario de GitHub o busca en <a href="#" data-ir="descubrir">Descubrir</a>.</div>'}`;
        const lanzar = () => seguir($('ph-seguir-url').value.trim(), $('ph-seguir-estado'));
        $('ph-seguir-btn').onclick = lanzar;
        $('ph-seguir-url').onkeydown = (e) => { if (e.key === 'Enter') lanzar(); };
        h.querySelectorAll('[data-ir]').forEach(a => a.onclick = (e) => { e.preventDefault(); ir(a.dataset.ir); });
        h.querySelectorAll('.ph-tarjeta[data-clave]').forEach(t => {
            const clave = t.dataset.clave;
            const s = lista.find(x => x.origen === `sigo:${clave}`);
            t.querySelector('[data-novedades]').onclick = async () => {
                estado.novedades[clave] = { cargando: true };
                pintar();
                try { estado.novedades[clave] = await enviar('/api/hub/novedades', { clave }); }
                catch (e) { estado.novedades[clave] = { error: e.message }; }
                await cargar();
            };
            const aplicar = t.querySelector('[data-aplicar]');
            if (aplicar) aplicar.onclick = async () => {
                aplicar.disabled = true;
                try { await enviar('/api/hub/aplicar', { clave, commit: aplicar.dataset.aplicar }); delete estado.novedades[clave]; await cargar(); }
                catch (e) { estado.novedades[clave] = { error: e.message }; pintar(); }
            };
            const descartar = t.querySelector('[data-descartar]');
            if (descartar) descartar.onclick = async () => { await enviar('/api/hub/descartar', { clave }).catch(() => {}); delete estado.novedades[clave]; await cargar(); };
            t.querySelector('[data-filtrar]').onclick = () => { estado.filtros = { plataforma: '', tipo: '', origen: s.origen, progreso: '', q: '' }; ir('todo'); };
            t.querySelector('[data-dejar]').onclick = async () => {
                if (!confirm(`¿Dejar de seguir «${s.titulo}»? Se borra su copia local; tu progreso se conserva.`)) return;
                try { await enviar('/api/hub/dejar', { clave }); await cargar(); } catch (e) { alert(e.message); }
            };
            t.querySelector('[data-chat]').onclick = () => chat(t.querySelector('[data-chat-zona]'), s.origen);
        });
    }

    // ================================================================== el tutor sobre un repositorio (el contenido va como DATOS)
    function chat(zona, origen) {
        const hilo = estado.chat[origen] = estado.chat[origen] || [];
        const pintarChat = () => {
            zona.innerHTML = `<div class="ph-chat">
                <div class="ph-ayuda" style="margin-bottom:6px;"><i class="fa-solid fa-shield-halved"></i> El tutor lee este repositorio como información: no sigue instrucciones escritas dentro y no ejecuta nada.</div>
                <div class="ph-msgs">${hilo.map(m => `<div class="ph-msg ${m.rol}">${m.rol === 'usuario' ? esc(m.texto) : ''}</div>`).join('')}</div>
                <div class="ph-fila"><input class="ph-campo" style="flex:1;" placeholder="¿Por dónde empiezo? ¿Qué video explica mejor los gradientes?" data-pregunta>
                <button class="ph-btn morado chico" data-enviar><i class="fa-solid fa-paper-plane"></i></button></div></div>`;
            const burbujas = zona.querySelectorAll('.ph-msg.tutor');
            hilo.filter(m => m.rol === 'tutor').forEach((m, i) => md(burbujas[i], m.texto || '…'));
            const campo = zona.querySelector('[data-pregunta]');
            const mandar = async () => {
                const texto = campo.value.trim();
                if (!texto) return;
                hilo.push({ rol: 'usuario', texto });
                const respuesta = { rol: 'tutor', texto: '' };
                hilo.push(respuesta);
                pintarChat();
                const ultima = [...zona.querySelectorAll('.ph-msg.tutor')].pop();
                try {
                    const modelo = window.PrigModelos ? window.PrigModelos.para('explicar') : null;
                    await flujo('/api/hub/preguntar', { origen, mensajes: hilo.slice(0, -1), modelo }, (ev) => {
                        if (ev.tipo === 'texto') { respuesta.texto += ev.delta || ''; md(ultima, respuesta.texto); }
                    });
                } catch (e) { respuesta.texto = `⚠️ ${e.message}`; md(ultima, respuesta.texto); }
            };
            zona.querySelector('[data-enviar]').onclick = mandar;
            campo.onkeydown = (e) => { if (e.key === 'Enter') mandar(); };
            campo.focus();
        };
        pintarChat();
    }

    // ================================================================== Descubrir
    function vistaDescubrir(h) {
        const b = estado.descubrir;
        h.innerHTML = `
          <div class="ph-h1">Descubrir Repositorios Prig</div>
          <div class="ph-ayuda">Red descentralizada de aprendizaje: busca por sigla <code>Prig-NOMBRE</code> (ej. <code>Prig-Python</code>, <code>Prig-DeepLearning</code>), por tema o escribe directamente <code>usuario/Prig-NOMBRE</code>.</div>
          <div class="ph-agregar"><div class="ph-fila">
            <input type="text" class="ph-campo" id="ph-d-q" placeholder="Buscar por sigla Prig-NOMBRE, tema (machine learning, c++…) o usuario/repo..." value="${esc(b.q)}" style="flex:1; min-width:240px;">
            <select class="ph-campo" id="ph-d-tipo"><option value="pack" ${b.tipo === 'pack' ? 'selected' : ''}>Packs</option><option value="perfil" ${b.tipo === 'perfil' ? 'selected' : ''}>Perfiles</option></select>
            <button class="ph-btn morado" id="ph-d-buscar"><i class="fa-solid fa-magnifying-glass"></i> Buscar</button>
            <button class="ph-btn verde" id="ph-d-cargar-directo" title="Seguir o cargar directamente este repositorio"><i class="fa-solid fa-cloud-arrow-down"></i> Cargar Directo</button>
          </div></div>
          <div id="ph-d-res">${b.cargando ? '<div class="ph-vacio"><i class="fa-solid fa-spinner fa-spin"></i> Buscando repositorios en GitHub...</div>'
            : b.error ? `<div class="ph-error">${esc(b.error)}</div>`
            : b.datos ? (b.datos.repos.length ? `<div class="ph-ayuda">${b.datos.total} repositorios encontrados</div><div class="ph-lista">${b.datos.repos.map((r, i) => `
                <div class="ph-tarjeta"><div class="ph-t-cab">${r.avatar ? `<img src="${esc(r.avatar)}" style="width:30px; height:30px; border-radius:50%;" alt="">` : ''}
                  <div style="flex:1; min-width:0;"><div class="ph-t-titulo">${esc(r.ref)}</div>
                  <div class="ph-t-meta">
                    <span class="ph-etq morado" style="font-weight:600;"><i class="fa-brands fa-github"></i> ${(r.ref.split('/')[1] || '').toLowerCase().startsWith('prig-') ? 'Pack Prig' : 'Perfil Prig'}</span>
                    <span><i class="fa-regular fa-star"></i> ${r.estrellas}</span>
                    <span>${esc(hace(r.actualizado))}</span>
                  </div></div></div>
                  ${r.descripcion ? `<div class="ph-t-nota">${esc(r.descripcion)}</div>` : ''}
                  <div class="ph-fila" style="gap:4px;">${r.temas.filter(t => !t.startsWith('prig')).slice(0, 6).map(t => `<span class="ph-etq">${esc(t)}</span>`).join('')}</div>
                  <div class="ph-t-acc"><button class="ph-btn verde chico" data-seguir="${i}"><i class="fa-solid fa-cloud-arrow-down"></i> Seguir y Cargar</button>
                    <a class="ph-btn chico" href="${esc(r.url)}" target="_blank" rel="noopener noreferrer"><i class="fa-brands fa-github"></i> Ver</a><span data-estado></span></div></div>`).join('')}</div>`
              : '<div class="ph-vacio">No se encontraron repositorios con ese nombre o tema. ¡Puedes ser el primero en publicar desde <b>Mis repos</b>!</div>')
            : '<div class="ph-vacio"><i class="fa-solid fa-compass grande"></i>Busca por sigla <code>Prig-NOMBRE</code> o tema para explorar repositorios de otros estudiantes.</div>'}</div>`;
        const buscar = async () => {
            b.q = $('ph-d-q').value;
            b.tipo = $('ph-d-tipo').value;
            b.cargando = true; b.error = null;
            pintar();
            try { b.datos = await json(`/api/hub/descubrir?q=${encodeURIComponent(b.q)}&tipo=${b.tipo}`); }
            catch (e) { b.error = e.message; }
            b.cargando = false;
            pintar();
        };
        $('ph-d-buscar').onclick = buscar;
        $('ph-d-q').onkeydown = (e) => { if (e.key === 'Enter') buscar(); };
        const btnDirecto = $('ph-d-cargar-directo');
        if (btnDirecto) {
            btnDirecto.onclick = () => {
                const val = $('ph-d-q').value.trim();
                if (!val) {
                    alert('Escribe el nombre del repositorio (ej. usuario/Prig-Python o Prig-Python).');
                    return;
                }
                seguir(val, $('ph-d-res'));
            };
        }
        h.querySelectorAll('[data-seguir]').forEach(btn => btn.onclick = () => seguir(b.datos.repos[+btn.dataset.seguir].url, btn.parentElement.querySelector('[data-estado]')));
    }

    // ================================================================== Mis repos
    function vistaRepos(h) {
        const info = estado.info || {};
        const lista = propios();
        const avisos = estado.datos.avisos;
        h.innerHTML = `
          <div class="ph-fila" style="justify-content:space-between; gap:10px; flex-wrap:wrap;">
            <div><div class="ph-h1">Mis repos</div>
            <div class="ph-ayuda">Tu perfil y tus packs son carpetas git con texto plano en <code>${esc(info.carpeta || '~/.prig_hub')}/propios</code>. Puedes editarlos aquí o a mano.</div></div>
            <div class="ph-fila" style="gap:8px;">
              <button class="ph-btn morado" id="ph-btn-sync-general"><i class="fa-solid fa-arrows-rotate"></i> Cargar Cursos & Desafíos desde Prig</button>
              <button class="ph-btn" id="ph-nuevo-pack"><i class="fa-solid fa-plus"></i> Nuevo pack</button>
            </div>
          </div>
          ${info.git === false ? '<div class="ph-error">git no está instalado: sudo apt install git</div>' : ''}
          <div id="ph-pack-form"></div>
          ${lista.map(r => `<div class="ph-tarjeta" style="margin:10px 0;" data-nombre="${esc(r.nombre)}">
              <div class="ph-t-cab"><div class="ph-t-icono" style="color:var(--accent-green);"><i class="fa-solid ${r.tipo === 'perfil' ? 'fa-house-user' : 'fa-box'}"></i></div>
                <div style="flex:1; min-width:0;"><div class="ph-t-titulo">${esc(r.titulo)}</div>
                  <div class="ph-t-meta"><code>${esc(r.nombre)}</code><span>${r.tipo === 'perfil' ? 'Perfil' : 'Pack'}</span>${r.version ? `<span>v${esc(r.version)}</span>` : ''}
                    <span>${Object.entries(r.cuentas || {}).map(([k, n]) => `${n} ${k}`).join(' · ')}</span>
                    ${r.url ? `<a href="${esc(r.url)}" target="_blank" rel="noopener noreferrer"><i class="fa-brands fa-github"></i> publicado ${esc(hace(r.publicado))}</a>` : '<span>sin publicar</span>'}</div></div></div>
              ${r.descripcion ? `<div class="ph-t-nota">${esc(r.descripcion)}</div>` : ''}
              ${r.avisos ? `<div class="ph-aviso">${avisos.filter(a => a.origen === r.origen).map(a => `<div><code>${esc(a.archivo || '')}</code> ${esc(a.mensaje)}</div>`).join('')}</div>` : ''}
              <div class="ph-t-acc">
                <button class="ph-btn chico morado" data-sync-repo title="Cargar cursos de YouTube y desafíos a este repositorio"><i class="fa-solid fa-arrows-rotate"></i> Cargar desde Prig</button>
                <button class="ph-btn chico" data-ficha><i class="fa-solid fa-id-card"></i> Ficha</button>
                <button class="ph-btn chico" data-desafio><i class="fa-solid fa-chess-knight"></i> Agregar desafío</button>
                <button class="ph-btn chico" data-archivos title="Abrir prig.yaml en el editor"><i class="fa-solid fa-file-pen"></i> Editar a mano</button>
                <button class="ph-btn verde chico" data-publicar><i class="fa-brands fa-github"></i> ${r.url ? 'Publicar cambios' : 'Publicar en GitHub'}</button></div>
              <div data-zona></div></div>`).join('')}
          <label class="ph-ayuda" style="display:flex; gap:6px; align-items:center; margin-top:14px;">
            <input type="checkbox" id="ph-resumen" ${(estado.datos.repos.ajustes || {}).publicar_resumen ? 'checked' : ''}>
            Publicar en mi perfil un <b>resumen</b> de mi progreso (solo recuentos: recursos terminados, rutas completas, desafíos resueltos). Tu progreso detallado nunca se publica.</label>`;
        $('ph-resumen').onchange = (e) => enviar('/api/hub/ajustes', { publicar_resumen: e.target.checked }).catch(() => {});
        $('ph-nuevo-pack').onclick = () => formularioPack();
        const btnSyncG = $('ph-btn-sync-general');
        if (btnSyncG) btnSyncG.onclick = () => formularioSincronizarPrig($('ph-pack-form'), lista[0] ? lista[0].nombre : 'prig');

        h.querySelectorAll('.ph-tarjeta[data-nombre]').forEach(t => {
            const nombre = t.dataset.nombre;
            const r = lista.find(x => x.nombre === nombre);
            const zona = t.querySelector('[data-zona]');
            t.querySelector('[data-ficha]').onclick = () => formularioFicha(zona, nombre);
            t.querySelector('[data-desafio]').onclick = () => formularioDesafio(zona, nombre);
            t.querySelector('[data-publicar]').onclick = () => formularioPublicar(zona, r);
            const btnSync = t.querySelector('[data-sync-repo]');
            if (btnSync) btnSync.onclick = () => formularioSincronizarPrig(zona, nombre);
            t.querySelector('[data-archivos]').onclick = () => {
                const ruta = `${info.carpeta}/propios/${nombre}/prig.yaml`;
                if (window.editorMgr) window.editorMgr.openFileByPath(ruta);
            };
        });
    }

    async function formularioSincronizarPrig(zona, nombre_inicial) {
        zona.innerHTML = '<div class="ph-agregar"><div class="ph-ayuda"><i class="fa-solid fa-spinner fa-spin"></i> Consultando cursos y desafíos disponibles en Prig IDE…</div></div>';
        let catalogo = { total_cursos_youtube: 0, categorias_youtube: {}, total_desafios: 0, desafios: [] };
        try {
            catalogo = await json('/api/hub/recursos_locales');
        } catch (e) {
            zona.innerHTML = `<div class="ph-error">Error al consultar recursos: ${esc(e.message)}</div>`;
            return;
        }

        const cats = [
            { id: 'python', label: '🐍 Python', desc: 'Harvard CS50P, programación modular, POO' },
            { id: 'cpp', label: '⚡ C++ Moderno', desc: 'Templates, punteros inteligentes, algoritmos' },
            { id: 'ml', label: '🤖 Machine Learning', desc: 'Stanford CS229, MIT 6.036, Caltech' },
            { id: 'dl', label: '🧠 Deep Learning & Redes', desc: 'PyTorch, transformers, redes neuronales' },
            { id: 'matematicas', label: '📐 Matemáticas para IA', desc: 'Álgebra lineal, cálculo, probabilidad' },
            { id: 'arquitectura_so', label: '💻 Arquitectura & SO', desc: 'Kernels, CPU, memoria, ensamblador' },
            { id: 'algoritmos', label: '🧩 Algoritmos & ED', desc: 'Grafos, árboles, complejidad algorítmica' }
        ];

        const reposDisponibles = propios();
        const selRepoHtml = `
          <div class="ph-fila" style="margin-bottom:10px;">
            <label class="ph-ayuda" style="font-weight:600;">Repositorio destino:</label>
            <select class="ph-campo" id="ph-sync-destino" style="min-width:200px;">
              ${reposDisponibles.map(r => `<option value="${esc(r.nombre)}" ${r.nombre === nombre_inicial ? 'selected' : ''}>${r.nombre === 'prig' ? 'Mi perfil (prig)' : esc(r.titulo) + ' (' + esc(r.nombre) + ')'}</option>`).join('')}
              <option value="__nuevo__">+ Crear nuevo pack Prig-&lt;tema&gt;</option>
            </select>
            <input class="ph-campo" id="ph-sync-nuevo-nombre" placeholder="Nombre: Prig-Python, Prig-ML..." style="display:none; min-width:220px;">
          </div>
        `;

        zona.innerHTML = `
          <div class="ph-agregar">
            <div class="ph-sec" style="margin-top:0;"><i class="fa-solid fa-arrows-rotate"></i> Cargar y Sincronizar Recursos desde Prig IDE</div>
            <div class="ph-ayuda">Vuelca tus cursos de YouTube y desafíos locales de Prig en el repositorio en texto plano (<code>recursos.yaml</code>, <code>desafios/</code> y <code>rutas/</code>), listo para publicar en GitHub con la sigla <b>Prig-NOMBRE</b>.</div>
            
            ${selRepoHtml}

            <div style="font-size:11.5px; font-weight:700; color:#cdd6f4; margin:10px 0 6px;">1. Cursos y Listas de YouTube (${catalogo.total_cursos_youtube} disponibles):</div>
            <div style="display:grid; grid-template-columns:repeat(auto-fill, minmax(260px, 1fr)); gap:6px;">
              ${cats.map(c => {
                  const cant = catalogo.categorias_youtube[c.id] || 0;
                  return `
                    <label class="ph-ayuda" style="display:flex; gap:8px; align-items:flex-start; background:rgba(255,255,255,0.03); padding:6px 8px; border-radius:6px; border:1px solid var(--border-color); cursor:pointer;">
                      <input type="checkbox" class="ph-sync-cat" value="${c.id}" checked style="margin-top:2px;">
                      <div>
                        <div style="font-weight:600; color:#fff;">${c.label} <span style="font-size:10px; color:#89b4fa;">(${cant})</span></div>
                        <div style="font-size:10px; color:var(--text-muted);">${c.desc}</div>
                      </div>
                    </label>
                  `;
              }).join('')}
            </div>

            <div style="font-size:11.5px; font-weight:700; color:#cdd6f4; margin:12px 0 6px;">2. Desafíos Locales de Programación:</div>
            <label class="ph-ayuda" style="display:flex; gap:8px; align-items:center; cursor:pointer;">
              <input type="checkbox" id="ph-sync-desafios" checked>
              <span>Exportar los desafíos locales de la sección Desafíos (${catalogo.total_desafios} disponibles en tu almacén)</span>
            </label>

            <div style="font-size:11.5px; font-weight:700; color:#cdd6f4; margin:12px 0 6px;">3. Rutas de Aprendizaje:</div>
            <label class="ph-ayuda" style="display:flex; gap:8px; align-items:center; cursor:pointer;">
              <input type="checkbox" id="ph-sync-ruta" checked>
              <span>Generar ruta de estudio estructurada automática (<code>rutas/ruta-principal.md</code>) vinculando clases y desafíos</span>
            </label>

            <div class="ph-fila" style="margin-top:14px; gap:10px;">
              <button class="ph-btn verde" id="ph-sync-ejecutar"><i class="fa-solid fa-arrows-rotate"></i> Sincronizar Repositorio</button>
              <button class="ph-btn" id="ph-sync-cancelar">Cancelar</button>
              <span id="ph-sync-status"></span>
            </div>
          </div>
        `;

        const selDest = zona.querySelector('#ph-sync-destino');
        const inpNuevo = zona.querySelector('#ph-sync-nuevo-nombre');
        selDest.onchange = () => {
            if (selDest.value === '__nuevo__') {
                inpNuevo.style.display = 'inline-block';
                inpNuevo.focus();
            } else {
                inpNuevo.style.display = 'none';
            }
        };

        zona.querySelector('#ph-sync-cancelar').onclick = () => { zona.innerHTML = ''; };

        zona.querySelector('#ph-sync-ejecutar').onclick = async () => {
            const btn = zona.querySelector('#ph-sync-ejecutar');
            const status = zona.querySelector('#ph-sync-status');
            btn.disabled = true;
            status.innerHTML = '<span class="ph-ayuda"><i class="fa-solid fa-spinner fa-spin"></i> Sincronizando recursos y generando README...</span>';

            let destino = selDest.value;
            if (destino === '__nuevo__') {
                const nombreNuevo = inpNuevo.value.trim();
                if (!nombreNuevo) {
                    status.innerHTML = '<span class="ph-error">Escribe el nombre del nuevo pack (ej. Prig-Python).</span>';
                    btn.disabled = false;
                    return;
                }
                try {
                    const rPack = await enviar('/api/hub/packs', {
                        titulo: nombreNuevo,
                        descripcion: `Pack ${nombreNuevo} de cursos y desafíos de programación`,
                        etiquetas: ['programacion', 'prig', 'cursos']
                    });
                    destino = rPack.nombre;
                } catch (e) {
                    status.innerHTML = `<span class="ph-error">Error al crear pack: ${esc(e.message)}</span>`;
                    btn.disabled = false;
                    return;
                }
            }

            const catsSeleccionadas = Array.from(zona.querySelectorAll('.ph-sync-cat:checked')).map(el => el.value);
            const incDes = zona.querySelector('#ph-sync-desafios').checked;
            const incRuta = zona.querySelector('#ph-sync-ruta').checked;

            try {
                const res = await enviar('/api/hub/sincronizar_local', {
                    destino: destino,
                    categorias_youtube: catsSeleccionadas,
                    incluir_desafios: incDes,
                    crear_ruta_estudio: incRuta
                });

                status.innerHTML = `
                  <span class="ph-ok"><i class="fa-solid fa-check"></i> ¡Sincronizado! Se agregaron ${res.cursos_agregados} cursos y ${res.desafios_exportados} desafíos.</span>
                  <button class="ph-btn verde chico" id="ph-sync-publicar-ahora" style="margin-left:8px;"><i class="fa-brands fa-github"></i> Publicar en GitHub ahora</button>
                `;

                const btnPub = zona.querySelector('#ph-sync-publicar-ahora');
                if (btnPub) {
                    btnPub.onclick = async () => {
                        btnPub.disabled = true;
                        btnPub.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Publicando...';
                        try {
                            const resPub = await enviar('/api/hub/publicar', { destino: destino });
                            status.innerHTML = `<span class="ph-ok"><i class="fa-solid fa-check"></i> Publicado en GitHub:</span> <a href="${esc(resPub.url)}" target="_blank">${esc(resPub.url)}</a>`;
                            await cargar();
                        } catch (errPub) {
                            status.innerHTML = `<span class="ph-error">Error al publicar: ${esc(errPub.message)}</span>`;
                        }
                    };
                }

                await cargar();
            } catch (err) {
                status.innerHTML = `<span class="ph-error">Error: ${esc(err.message)}</span>`;
                btn.disabled = false;
            }
        };
    }

    function formularioPack() {
        const z = $('ph-pack-form');
        z.innerHTML = `<div class="ph-agregar"><div class="ph-rejilla2">
            <input class="ph-campo" id="ph-p-titulo" placeholder="Título: Prig-Python, Prig-ML...">
            <select class="ph-campo" id="ph-p-nivel"><option value="">Nivel</option><option>principiante</option><option>intermedio</option><option>avanzado</option></select>
            <input class="ph-campo" id="ph-p-desc" placeholder="Descripción breve">
            <input class="ph-campo" id="ph-p-etq" placeholder="Etiquetas: ml, python…"></div>
          <div class="ph-fila" style="margin-top:8px;"><button class="ph-btn verde" id="ph-p-crear">Crear pack</button><button class="ph-btn" id="ph-p-cancelar">Cancelar</button>
            <span class="ph-ayuda">Se crea como <code>Prig-&lt;tema&gt;</code> con licencia CC BY 4.0 (contenido) y MIT (código).</span></div><div id="ph-p-estado"></div></div>`;
        $('ph-p-titulo').focus();
        $('ph-p-cancelar').onclick = () => { z.innerHTML = ''; };
        $('ph-p-crear').onclick = async () => {
            try {
                const r = await enviar('/api/hub/packs', { titulo: $('ph-p-titulo').value, descripcion: $('ph-p-desc').value, nivel: $('ph-p-nivel').value,
                                                          etiquetas: $('ph-p-etq').value.split(/[,\s]+/).filter(Boolean) });
                estado.destino = r.nombre;
                guardarLocal('prig_hub_destino', r.nombre);
                await cargar();
            } catch (e) { $('ph-p-estado').innerHTML = `<div class="ph-error">${esc(e.message)}</div>`; }
        };
    }

    async function formularioFicha(zona, nombre) {
        let d;
        try { d = await json(`/api/hub/repo?origen=${encodeURIComponent('propio:' + nombre)}`); } catch (e) { zona.innerHTML = `<div class="ph-error">${esc(e.message)}</div>`; return; }
        const m = d.manifiesto;
        zona.innerHTML = `<div class="ph-agregar"><div class="ph-rejilla2">
            <input class="ph-campo" data-k="titulo" placeholder="Título" value="${esc(m.titulo)}">
            <input class="ph-campo" data-k="autor" placeholder="Tu nombre (visible)" value="${esc(m.autor.nombre)}">
            <input class="ph-campo" data-k="descripcion" placeholder="Descripción" value="${esc(m.descripcion)}">
            <input class="ph-campo" data-k="etiquetas" placeholder="Etiquetas" value="${esc(m.etiquetas.join(', '))}">
            <select class="ph-campo" data-k="nivel"><option value="">Nivel</option>${['principiante', 'intermedio', 'avanzado'].map(n => `<option ${m.nivel === n ? 'selected' : ''}>${n}</option>`).join('')}</select>
            ${m.tipo === 'pack' ? `<input class="ph-campo" data-k="version" placeholder="Versión del contenido (1.2.0)" value="${esc(m.version)}" title="Súbela cuando publiques cambios: quien te sigue ve de qué versión a cuál pasa">`
              : `<input class="ph-campo" data-k="enlaces" placeholder="Tus perfiles: github.com/tu, kaggle.com/tu… (separados por espacios)" value="${esc(m.enlaces.map(e => e.url).join(' '))}">`}
          </div><div class="ph-fila" style="margin-top:8px;"><button class="ph-btn verde chico" data-guardar>Guardar ficha</button><span data-estado></span></div></div>`;
        zona.querySelector('[data-guardar]').onclick = async () => {
            const cambios = {};
            zona.querySelectorAll('[data-k]').forEach(c => { cambios[c.dataset.k] = c.value; });
            if ('etiquetas' in cambios) cambios.etiquetas = cambios.etiquetas.split(/[,\s]+/).filter(Boolean);
            if ('enlaces' in cambios) cambios.enlaces = cambios.enlaces.split(/\s+/).filter(Boolean);
            try { await enviar('/api/hub/manifiesto', { destino: nombre, cambios }); await cargar(); }
            catch (e) { zona.querySelector('[data-estado]').innerHTML = `<span class="ph-error">${esc(e.message)}</span>`; }
        };
    }

    async function formularioDesafio(zona, nombre) {
        let lista = [];
        try { lista = (await json('/api/hub/desafios_locales')).desafios; } catch (e) { /* sin desafíos */ }
        zona.innerHTML = `<div class="ph-agregar">
            <div class="ph-ayuda">Comparte un desafío de la sección <b>Desafíos</b>: se guarda con su código de partida, su solución y sus pruebas, en texto plano. Solo Python por ahora.</div>
            ${lista.length ? `<div class="ph-fila" style="margin-top:8px;"><select class="ph-campo" data-sel style="flex:1;">${lista.map(x => `<option value="${esc(x.id)}">${esc(x.titulo)}${x.origen ? ` · ${esc(x.origen)}` : ''}</option>`).join('')}</select>
              <button class="ph-btn verde chico" data-exportar>Agregar al repositorio</button></div>` : '<div class="ph-ayuda" style="margin-top:6px;">No tienes desafíos todavía: crea o importa uno en Desafíos.</div>'}
            <div data-estado></div></div>`;
        const b = zona.querySelector('[data-exportar]');
        if (b) b.onclick = async () => {
            try {
                const r = await enviar('/api/hub/desafio/exportar', { destino: nombre, id_desafio: zona.querySelector('[data-sel]').value });
                zona.querySelector('[data-estado]').innerHTML = `<span class="ph-ok"><i class="fa-solid fa-check"></i> Guardado en desafios/${esc(r.id)}</span>`;
                cargar();
            } catch (e) { zona.querySelector('[data-estado]').innerHTML = `<span class="ph-error">${esc(e.message)}</span>`; }
        };
    }

    function formularioPublicar(zona, r) {
        const info = estado.info || {};
        const cuenta = info.github ? info.github.login : null;
        zona.innerHTML = `<div class="ph-agregar">
            <div class="ph-sec" style="margin-top:0;"><i class="fa-brands fa-github"></i> Publicar «${esc(r.titulo)}»</div>
            <div class="ph-ayuda">Se ${r.url ? 'actualiza' : 'crea'} el repositorio <b>público</b> <code>${esc(cuenta || 'tu-usuario')}/${esc(r.nombre)}</code> con el topic <code>${r.tipo === 'perfil' ? 'prig-perfil' : 'prig-pack'}</code>, para que otros te encuentren.</div>
            <ul class="ph-ayuda" style="margin:6px 0; padding-left:18px;">
              <li><b>Se publica:</b> ${r.tipo === 'perfil' ? 'tu ficha, tus listas y a quién sigues' : 'la ficha, los recursos, las rutas y los desafíos del pack'}.</li>
              <li><b>No se publica:</b> tu progreso (${(estado.datos.repos.ajustes || {}).publicar_resumen && r.tipo === 'perfil' ? 'solo el resumen que activaste' : 'nada, ni siquiera un resumen'}), tus desafíos resueltos ni tu correo (los cambios van firmados con el correo «noreply» de GitHub).</li></ul>
            ${info.token ? '' : `<div class="ph-aviso">Hace falta un token de GitHub con permiso para crear repositorios (Fine-grained: «Administration» y «Contents» de escritura). Guárdalo en la sección <a href="#" data-gh>GitHub</a>.</div>`}
            <div class="ph-fila"><button class="ph-btn verde chico" data-ok ${info.token ? '' : 'disabled'}><i class="fa-solid fa-cloud-arrow-up"></i> Publicar</button><span data-estado></span></div></div>`;
        const gh = zona.querySelector('[data-gh]');
        if (gh) gh.onclick = (e) => { e.preventDefault(); window.GitHubLector && window.GitHubLector.abrir(); };
        zona.querySelector('[data-ok]').onclick = async (e) => {
            e.target.disabled = true;
            zona.querySelector('[data-estado]').innerHTML = '<span class="ph-ayuda"><i class="fa-solid fa-spinner fa-spin"></i> Publicando…</span>';
            try {
                const res = await enviar('/api/hub/publicar', { destino: r.nombre });
                zona.querySelector('[data-estado]').innerHTML = `<span class="ph-ok"><i class="fa-solid fa-check"></i> Publicado:</span> <a href="${esc(res.url)}" target="_blank" rel="noopener noreferrer">${esc(res.url)}</a>`;
                cargar();
            } catch (err) { zona.querySelector('[data-estado]').innerHTML = `<span class="ph-error">${esc(err.message)}</span>`; e.target.disabled = false; }
        };
    }

    function verFormato() {
        const h = $('ph-hoja');
        h.innerHTML = `<button class="ph-btn chico" id="ph-volver"><i class="fa-solid fa-arrow-left"></i> Volver</button>
          <div class="ph-h1" style="margin-top:10px;">Formato de un repositorio de Prig Hub</div>
          <div class="ph-ayuda">Es texto plano: puedes escribirlo a mano, en GitHub o con cualquier editor. Especificación completa: <code>docs/prig-hub.md</code>.</div>
          <div class="ph-codigo" style="max-height:none;">prig.yaml            formato: 1 · tipo: perfil | pack · titulo · version…
personas.yaml        - url: https://www.kaggle.com/ana
                       titulo: Ana en Kaggle
recursos.yaml        - url: https://youtu.be/aircAruvnKk
                       titulo: ¿Qué es una red neuronal?
                       etiquetas: [redes, ml]
                       minutos: 19
rutas/intro.md       ---
                     titulo: Redes neuronales desde cero
                     ---
                     1. [El video](https://youtu.be/aircAruvnKk) primero la intuición
                     2. [Un notebook](https://www.kaggle.com/code/ana/mlp) luego el código
                     3. [Tu turno](desafio:perceptron)
desafios/perceptron/ desafio.md · inicio/*.py · solucion/*.py · pruebas/test_*.py</div>
          <div class="ph-ayuda">El progreso NO va en el repositorio: vive en tu equipo. Lo mal escrito no rompe nada: se salta y se avisa en Mis repos.</div>`;
        $('ph-volver').onclick = () => pintar();
    }

    // ================================================================== entrada
    function abrir(opciones = {}) {
        if (window.workArea) window.workArea.abrirHerramienta('modal-prig-hub', 'Prig Hub', 'fa-circle-nodes');
        montar();
        if (opciones.vista) ir(opciones.vista);
        if (opciones.enlace) setTimeout(() => { ir('todo'); const c = $('ph-enlace'); if (c) { c.value = opciones.enlace; analizar(opciones.enlace); } }, 60);
    }

    document.addEventListener('prig:herramienta-abierta', (e) => {
        if (e.detail && e.detail.modalId === 'modal-prig-hub') { montar(); if (estado.datos) cargar(); }
    });

    window.PrigHub = { abrir, estado, recargar: cargar };
})();
