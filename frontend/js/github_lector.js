/**
 * GitHub dentro de Prig: buscar repositorios (o pegar su enlace) y leerlos con un profesor.
 *
 * Más sencillo que Kaggle, en dos pantallas:
 *   · Buscar: resultados a la izquierda y, al elegir uno, un cuadro con su información
 *     (estrellas, lenguaje, licencia, temas…) y lo que se puede hacer con él.
 *   · Repositorio: árbol de archivos, el README o el archivo abierto, y el profesor al
 *     lado: explica el repositorio en conjunto o el archivo elegido, y responde preguntas.
 *
 * Se puede guardar el repositorio, bajarlo al proyecto (github_repos/<nombre>/) y
 * exportar lo explicado: la explicación en Markdown o el código explicado en PDF.
 */
(function () {
    const $ = (id) => document.getElementById(id);
    const esc = (t) => String(t ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
    const json = (url, opciones) => window.prigFetchJson(url, opciones);
    const enviar = (url, cuerpo, metodo = 'POST') => json(url, { method: metodo, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(cuerpo || {}) });
    const leerLocal = (k) => { try { return localStorage.getItem(k); } catch (e) { return null; } };
    const guardarLocal = (k, v) => { try { localStorage.setItem(k, v); } catch (e) { /* sin almacenamiento */ } };

    const estado = {
        vista: 'buscar', busqueda: { q: '', lenguaje: '', orden: 'estrellas', estrellas_min: '', pagina: 1, datos: null, cargando: false, error: null },
        elegido: null, repo: null, archivo: null, contenido: null, explicacion: null, chat: [], guardados: [],
        modelo: null, modelos: [], nivel: leerLocal('prig_github_nivel') || 'intermedio', token: null, filtroArbol: '',
    };

    const LENGUAJES = ['', 'Python', 'JavaScript', 'TypeScript', 'Jupyter Notebook', 'Java', 'C++', 'C', 'Go', 'Rust', 'R', 'Julia', 'C#', 'PHP', 'Ruby', 'Kotlin', 'Swift'];
    const miles = (n) => n == null ? '—' : n >= 1000 ? `${(n / 1000).toFixed(1)}k` : String(n);
    const tam = (b) => b == null ? '' : b < 1024 ? `${b} B` : b < 1048576 ? `${(b / 1024).toFixed(1)} KB` : `${(b / 1048576).toFixed(1)} MB`;
    function hace(t) {
        if (!t) return '';
        const dias = Math.floor((Date.now() - new Date(t)) / 86400000);
        return dias <= 0 ? 'hoy' : dias === 1 ? 'ayer' : dias < 30 ? `hace ${dias} días` : dias < 365 ? `hace ${Math.round(dias / 30)} meses` : `hace ${Math.round(dias / 365)} años`;
    }

    function md(el, texto) {
        let html = typeof window.prigRenderMarkdown === 'function'
            ? window.prigRenderMarkdown(texto)
            : (window.marked ? window.marked.parse(String(texto || '')) : `<pre>${esc(texto)}</pre>`);
        if (window.DOMPurify && typeof window.prigRenderMarkdown !== 'function') html = DOMPurify.sanitize(html);
        el.innerHTML = html;
        el.querySelectorAll('a[href]').forEach(a => { a.target = '_blank'; a.rel = 'noopener noreferrer'; });
        if (window.hljs) el.querySelectorAll('pre code').forEach(b => { try { hljs.highlightElement(b); } catch (e) { /* sin resaltado */ } });
    }

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

    // ================================================================== estilos
    function estilos() {
        if ($('gh-estilos')) return;
        const css = document.createElement('style');
        css.id = 'gh-estilos';
        css.textContent = `
          #github-raiz { display:grid; grid-template-columns:180px 1fr; height:100%; min-height:0; background:var(--bg-dark); }
          #github-raiz a { color:#58a6ff; text-decoration:none; }
          #github-raiz select option { background:#1e1e2e; color:#cdd6f4; }
          .gh-nav { border-right:1px solid var(--border-color); background:var(--bg-panel); padding:12px 8px; display:flex; flex-direction:column; gap:2px; }
          .gh-logo { font-size:20px; font-weight:800; color:#fff; padding:2px 10px 14px; display:flex; gap:8px; align-items:center; }
          .gh-nav-item { display:flex; gap:10px; align-items:center; background:none; border:none; color:var(--text-main); padding:8px 12px; border-radius:18px; cursor:pointer; font-size:12.5px; text-align:left; }
          .gh-nav-item:hover { background:rgba(255,255,255,.05); }
          .gh-nav-item.activa { background:rgba(88,166,255,.15); color:#58a6ff; font-weight:600; }
          .gh-hoja { min-height:0; overflow:hidden; display:flex; flex-direction:column; }
          .gh-campo { background:var(--bg-dark); color:var(--text-main); border:1px solid var(--border-color); border-radius:7px; padding:7px 9px; font-size:12.5px; box-sizing:border-box; }
          .gh-btn { background:rgba(255,255,255,.05); color:var(--text-main); border:1px solid var(--border-color); border-radius:7px; padding:5px 11px; font-size:11.5px; cursor:pointer; display:inline-flex; gap:6px; align-items:center; white-space:nowrap; text-decoration:none !important; }
          .gh-btn:hover:not(:disabled) { border-color:#58a6ff; }
          .gh-btn:disabled { opacity:.5; cursor:default; }
          .gh-btn.verde { background:#238636; border-color:#2ea043; color:#fff; font-weight:600; }
          .gh-btn.morado { background:rgba(203,166,247,.15); border-color:rgba(203,166,247,.45); color:var(--accent-purple); }
          .gh-btn.activo { color:#58a6ff; border-color:rgba(88,166,255,.5); }
          .gh-fila { display:flex; gap:8px; align-items:center; flex-wrap:wrap; }
          .gh-ayuda { font-size:11px; color:var(--text-muted); line-height:1.45; }
          .gh-error { font-size:12px; color:var(--accent-red); background:rgba(243,139,168,.08); border:1px solid rgba(243,139,168,.3); border-radius:6px; padding:8px 10px; }
          .gh-barra-busqueda { padding:14px 18px; border-bottom:1px solid var(--border-color); display:flex; gap:8px; flex-wrap:wrap; align-items:center; }
          .gh-partes { flex:1; min-height:0; display:grid; grid-template-columns:minmax(0,1.2fr) minmax(320px,1fr); }
          .gh-resultados { overflow-y:auto; padding:6px 12px 20px 18px; }
          .gh-resultado { display:flex; gap:10px; padding:11px 10px; border-radius:9px; cursor:pointer; border:1px solid transparent; }
          .gh-resultado:hover { background:rgba(255,255,255,.03); }
          .gh-resultado.elegido { border-color:rgba(88,166,255,.55); background:rgba(88,166,255,.06); }
          .gh-avatar { width:34px; height:34px; border-radius:50%; flex:none; background:rgba(255,255,255,.08); }
          .gh-nombre { color:#58a6ff; font-weight:600; font-size:13px; }
          .gh-desc { font-size:12px; color:var(--text-main); margin:3px 0 5px; }
          .gh-meta { display:flex; gap:12px; font-size:11px; color:var(--text-muted); flex-wrap:wrap; }
          .gh-tema { font-size:10.5px; padding:1px 8px; border-radius:10px; background:rgba(88,166,255,.12); color:#58a6ff; }
          .gh-cuadro { border-left:1px solid var(--border-color); overflow-y:auto; padding:18px; }
          .gh-tarjeta { border:1px solid var(--border-color); border-radius:12px; background:var(--bg-panel); padding:16px; }
          .gh-cifras { display:grid; grid-template-columns:repeat(3,1fr); gap:8px; margin:12px 0; }
          .gh-cifras div { background:rgba(0,0,0,.18); border-radius:8px; padding:7px 9px; }
          .gh-cifras span { display:block; font-size:10px; color:var(--text-muted); }
          .gh-cifras b { color:#fff; font-size:13px; }
          .gh-lenguajes { display:flex; height:8px; border-radius:4px; overflow:hidden; margin:10px 0 5px; }
          /* Vista del repositorio como un IDE: árbol | código | profesor, con divisores arrastrables.
             Los anchos van en variables (--a árbol, --p profesor, --ph alto del profesor abajo) */
          .gh-repo { flex:1; min-height:0; display:grid; --a:250px; --p:38%; --ph:40%; --s1:6px; --s2:6px;
                     grid-template-columns:var(--a) var(--s1) minmax(0,1fr) var(--s2) var(--p); grid-template-rows:minmax(0,1fr); }
          .gh-repo.prof-abajo { grid-template-columns:var(--a) var(--s1) minmax(0,1fr); grid-template-rows:minmax(0,1fr) var(--s2) var(--ph); }
          .gh-repo > .gh-arbol { grid-column:1; grid-row:1 / -1; min-width:0; border-right:none; }
          .gh-repo > .gh-div-arbol { grid-column:2; grid-row:1 / -1; }
          .gh-repo > .gh-centro { grid-column:3; grid-row:1; }
          .gh-repo > .gh-div-prof { grid-column:4; grid-row:1; }
          .gh-repo > .gh-profesor { grid-column:5; grid-row:1; min-width:0; border-left:none; }
          .gh-repo.prof-abajo > .gh-div-prof { grid-column:3; grid-row:2; }
          .gh-repo.prof-abajo > .gh-profesor { grid-column:3; grid-row:3; }
          .gh-repo.sin-arbol { --a:0px; --s1:0px; } .gh-repo.sin-arbol > .gh-arbol, .gh-repo.sin-arbol > .gh-div-arbol { display:none; }
          .gh-repo.sin-prof { --p:0px; --ph:0px; --s2:0px; } .gh-repo.sin-prof > .gh-profesor, .gh-repo.sin-prof > .gh-div-prof { display:none; }
          .gh-div { background:transparent; position:relative; z-index:2; touch-action:none; }
          .gh-div::after { content:''; position:absolute; inset:0; background:var(--border-color); transition:background .12s; }
          .gh-div-arbol, .gh-div-prof { cursor:col-resize; }
          .gh-div-arbol::after, .gh-repo:not(.prof-abajo) .gh-div-prof::after { left:2px; right:2px; }
          .gh-repo.prof-abajo .gh-div-prof { cursor:row-resize; } .gh-repo.prof-abajo .gh-div-prof::after { top:2px; bottom:2px; }
          .gh-div:hover::after, .gh-div.arrastrando::after { background:#58a6ff; }
          body.gh-redimensionando, body.gh-redimensionando * { user-select:none !important; }
          .gh-vista-btns { display:inline-flex; border:1px solid var(--border-color); border-radius:7px; overflow:hidden; }
          .gh-vista-btns button { background:rgba(255,255,255,.04); border:none; color:var(--text-muted); padding:5px 9px; cursor:pointer; font-size:12px; }
          .gh-vista-btns button + button { border-left:1px solid var(--border-color); }
          .gh-vista-btns button.activo { color:#58a6ff; background:rgba(88,166,255,.14); }
          .gh-cabecera.compacta .gh-lenguajes, .gh-cabecera.compacta .gh-leyenda-leng, .gh-cabecera.compacta .gh-avatar { display:none; }
          /* Cuadernos Jupyter del repositorio, renderizados como cuaderno */
          .gh-nb { padding:12px 16px 30px; display:flex; flex-direction:column; gap:10px; }
          .gh-nb-celda { border:1px solid rgba(255,255,255,.07); border-radius:8px; overflow:hidden; }
          .gh-nb-celda.md { border-color:transparent; }
          .gh-nb-celda .gh-md { padding:4px 8px; }
          .gh-nb-in { display:flex; background:rgba(0,0,0,.2); }
          .gh-nb-prompt { color:#79c0ff; font-family:'Fira Code',monospace; font-size:11px; padding:10px 8px; min-width:52px; text-align:right; user-select:none; opacity:.8; }
          .gh-nb-in pre { margin:0; padding:10px 12px; overflow-x:auto; flex:1; font-family:'Fira Code',monospace; font-size:12px; line-height:1.5; }
          .gh-nb-in pre code { background:transparent !important; padding:0 !important; }
          .gh-nb-out { border-top:1px solid rgba(255,255,255,.06); padding:8px 12px 8px 72px; font-family:'Fira Code',monospace; font-size:11.5px; white-space:pre-wrap; word-break:break-word; color:var(--text-main); max-height:420px; overflow:auto; }
          .gh-nb-out.error { color:var(--accent-red); }
          .gh-nb-out img { max-width:100%; background:#fff; border-radius:4px; }
          .gh-nb-out table { border-collapse:collapse; font-size:11px; } .gh-nb-out td, .gh-nb-out th { border:1px solid rgba(255,255,255,.12); padding:2px 6px; }
          .gh-cabecera { padding:10px 16px; border-bottom:1px solid var(--border-color); background:var(--bg-panel); }
          .gh-arbol { border-right:1px solid var(--border-color); overflow-y:auto; padding:8px 6px; font-size:12px; }
          .gh-arbol details > summary { cursor:pointer; padding:3px 6px; border-radius:5px; list-style:none; color:var(--text-main); }
          .gh-arbol details > summary::before { content:'▸ '; color:var(--text-muted); }
          .gh-arbol details[open] > summary::before { content:'▾ '; }
          .gh-arbol details > div { padding-left:12px; }
          .gh-archivo { padding:3px 6px; border-radius:5px; cursor:pointer; display:flex; gap:6px; align-items:center; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; color:var(--text-main); }
          .gh-archivo:hover { background:rgba(255,255,255,.05); }
          .gh-archivo.activo { background:rgba(88,166,255,.14); color:#58a6ff; }
          .gh-centro { overflow:auto; min-width:0; }
          .gh-codigo { margin:0; padding:12px 14px; font-family:'Fira Code',monospace; font-size:12px; line-height:1.55; white-space:pre; background:transparent; }
          .gh-lineas { display:grid; grid-template-columns:auto 1fr; }
          .gh-codigo code.hljs, .gh-codigo code { padding:0 !important; background:transparent !important; font-size:12px !important; line-height:1.55 !important; font-family:'Fira Code',monospace !important; display:block; overflow:visible; }
          .gh-lineas .num { text-align:right; padding:12px 8px 12px 12px; color:rgba(255,255,255,.25); font-family:'Fira Code',monospace; font-size:12px; line-height:1.55; user-select:none; white-space:pre; border-right:1px solid rgba(255,255,255,.06); }
          .gh-md { padding:16px 22px; font-size:13px; line-height:1.65; color:var(--text-main); }
          .gh-md img { max-width:100%; }
          .gh-profesor { border-left:1px solid var(--border-color); display:flex; flex-direction:column; min-height:0; }
          .gh-explicacion { flex:1; overflow-y:auto; padding:12px 16px; font-size:12.8px; line-height:1.6; }
          .gh-explicacion h2 { font-size:13.5px; color:var(--accent-purple); margin:12px 0 4px; }
          .gh-explicacion h3 { font-size:12.8px; color:var(--accent-purple); margin:10px 0 3px; }
          .gh-chat { border-top:1px solid var(--border-color); padding:8px 12px; background:var(--bg-panel); }
          .gh-msgs { max-height:180px; overflow-y:auto; display:flex; flex-direction:column; gap:6px; margin-bottom:6px; }
          .gh-msg { padding:6px 10px; border-radius:8px; font-size:12px; line-height:1.5; max-width:92%; }
          .gh-msg.usuario { align-self:flex-end; background:rgba(88,166,255,.14); }
          .gh-msg.profesor { align-self:flex-start; background:rgba(255,255,255,.05); }
          .gh-vacio { text-align:center; color:var(--text-muted); padding:50px 20px; line-height:1.6; }
          .gh-vacio h2 { color:#fff; font-size:17px; }
          .gh-menu { position:absolute; z-index:20; background:var(--bg-panel); border:1px solid var(--border-color); border-radius:8px; padding:5px; box-shadow:0 8px 24px rgba(0,0,0,.4); min-width:250px; }
          .gh-menu button { display:flex; width:100%; gap:8px; align-items:flex-start; background:none; border:none; color:var(--text-main); padding:7px 9px; border-radius:6px; cursor:pointer; text-align:left; font-size:12px; }
          .gh-menu button:hover { background:rgba(255,255,255,.06); }
          @media (max-width: 1150px) { .gh-partes { grid-template-columns:1fr; } }
          @container (max-width: 1150px) { .gh-partes { grid-template-columns:1fr; } .gh-cuadro { border-left:none; border-top:1px solid var(--border-color); } }
          @container (max-width: 780px) {
            #github-raiz { grid-template-columns:52px 1fr; }
            .gh-nav { padding:10px 6px; align-items:center; }
            .gh-logo { font-size:0; padding:2px 0 12px; gap:0; }
            .gh-nav-item { font-size:0; gap:0; padding:9px; justify-content:center; }
            .gh-nav-item i { font-size:14px; }
            #gh-token { display:none; }
          }
          @container (max-width: 520px) { .gh-cifras { grid-template-columns:repeat(2,1fr); } }
        `;
        document.head.appendChild(css);
    }

    const COLOR_LENGUAJE = { Python: '#3572A5', JavaScript: '#f1e05a', TypeScript: '#3178c6', 'Jupyter Notebook': '#DA5B0B', Java: '#b07219', 'C++': '#f34b7d', C: '#555555',
                             Go: '#00ADD8', Rust: '#dea584', R: '#198CE7', Julia: '#a270ba', 'C#': '#178600', PHP: '#4F5D95', Ruby: '#701516', Shell: '#89e051',
                             HTML: '#e34c26', CSS: '#563d7c', Kotlin: '#A97BFF', Swift: '#F05138', Makefile: '#427819', Dockerfile: '#384d54' };
    const colorDe = (l) => COLOR_LENGUAJE[l] || '#8b949e';

    // ================================================================== estructura
    function montar() {
        estilos();
        const r = $('github-raiz');
        if (!r || $('gh-nav')) return;
        r.innerHTML = `
          <nav class="gh-nav" id="gh-nav">
            <div class="gh-logo"><i class="fa-brands fa-github" style="font-size:24px;"></i> GitHub</div>
            <button class="gh-nav-item" data-vista="buscar" title="Buscar"><i class="fa-solid fa-magnifying-glass"></i> Buscar</button>
            <button class="gh-nav-item" data-vista="guardados" title="Guardados"><i class="fa-solid fa-bookmark"></i> Guardados</button>
            <button class="gh-nav-item" data-vista="repo" id="gh-nav-repo" hidden><i class="fa-solid fa-book"></i> <span></span></button>
            <span style="flex:1"></span>
            <div id="gh-token" class="gh-ayuda" style="padding:6px;"></div>
          </nav>
          <main class="gh-hoja" id="gh-hoja"></main>`;
        $('gh-nav').onclick = (e) => {
            const b = e.target.closest('[data-vista]');
            if (b) ir(b.dataset.vista);
        };
        cargarToken();
        cargarModelos();
        ir('buscar');
        const ultimo = leerLocal('prig_github_repo');
        if (ultimo) estado.ultimo = ultimo;
    }

    function ir(vista) {
        estado.vista = vista;
        document.querySelectorAll('#gh-nav [data-vista]').forEach(b => b.classList.toggle('activa', b.dataset.vista === vista));
        if (vista === 'guardados') return vistaGuardados();
        if (vista === 'repo' && estado.repo) return pintarRepo();
        return vistaBuscar();
    }

    async function cargarToken() {
        try { estado.token = await json('/api/github/estado'); } catch (e) { estado.token = null; }
        const c = $('gh-token');
        if (!c || !estado.token) return;
        c.innerHTML = estado.token.con_token
            ? `<i class="fa-solid fa-key" style="color:#3fb950;"></i> Token activo<br>${esc(estado.token.limite)}<br><a href="#" data-token>Cambiar</a>`
            : `Sin token: ${esc(estado.token.limite)}.<br><a href="#" data-token>Añadir un token gratuito</a> para más.`;
        c.querySelector('[data-token]').onclick = (e) => { e.preventDefault(); dialogoToken(); };
    }

    function dialogoToken() {
        const capa = document.createElement('div');
        capa.style.cssText = 'position:fixed; inset:0; background:rgba(0,0,0,.55); z-index:10050; display:flex; align-items:center; justify-content:center;';
        capa.innerHTML = `<div class="gh-tarjeta" style="width:500px; max-width:94vw;">
            <div class="gh-fila" style="margin-bottom:8px;"><i class="fa-brands fa-github" style="font-size:20px;"></i><b style="color:#fff; flex:1;">Token de GitHub (opcional)</b></div>
            <div class="gh-ayuda" style="margin-bottom:8px;">Sin token GitHub permite 60 consultas por hora y 10 búsquedas por minuto. Con uno gratuito, 5000.
              Créalo en <a href="${esc((estado.token || {}).url_token || 'https://github.com/settings/tokens')}" target="_blank" rel="noopener noreferrer">github.com → Settings → Tokens</a>
              («Fine-grained», sin ningún permiso: para repositorios públicos no hace falta). Se guarda solo en tu equipo.</div>
            <input class="gh-campo" id="gh-token-campo" style="width:100%;" placeholder="github_pat_…" spellcheck="false">
            <div id="gh-token-error" style="margin-top:6px;"></div>
            <div class="gh-fila" style="margin-top:10px; justify-content:flex-end;">
              ${estado.token && estado.token.origen === 'Prig' ? '<button class="gh-btn" data-borrar style="color:var(--accent-red);">Olvidar token</button><span style="flex:1"></span>' : ''}
              <button class="gh-btn" data-cerrar>Cancelar</button><button class="gh-btn verde" data-guardar>Comprobar y guardar</button></div></div>`;
        document.body.appendChild(capa);
        const cerrar = () => capa.remove();
        capa.addEventListener('mousedown', (e) => { if (e.target === capa) cerrar(); });
        capa.querySelector('[data-cerrar]').onclick = cerrar;
        const borrar = capa.querySelector('[data-borrar]');
        if (borrar) borrar.onclick = async () => { await fetch('/api/github/token', { method: 'DELETE' }); cerrar(); cargarToken(); };
        capa.querySelector('[data-guardar]').onclick = async () => {
            try { await enviar('/api/github/token', { texto: $('gh-token-campo').value }); cerrar(); cargarToken(); }
            catch (e) { $('gh-token-error').innerHTML = `<div class="gh-error">${esc(e.message)}</div>`; }
        };
        setTimeout(() => { const c = $('gh-token-campo'); if (c) c.focus(); }, 20);
    }

    async function cargarModelos() {
        let locales = [], nube = [];
        try { locales = (await json('/api/modelos')).modelos.filter(m => !(m.capacidades || []).includes('embedding')).map(m => m.nombre); } catch (e) { /* sin Ollama */ }
        try {
            const g = await json('/api/gemini/estado');
            if (g.configurado) nube = (await json('/api/gemini/modelos')).modelos.map(m => `gemini:${m.id}`);
        } catch (e) { /* sin Gemini */ }
        estado.modelos = [...locales, ...nube];
        const preferido = (window.PrigModelos && window.PrigModelos.para('explicar')) || leerLocal('prig_github_modelo') || leerLocal('prig_kaggle_modelo') || leerLocal('prig_desafios_modelo');
        estado.modelo = estado.modelos.includes(preferido) ? preferido : (estado.modelos[0] || '');
        const sel = $('gh-modelo');
        if (sel) pintarModelos(sel);
    }

    function pintarModelos(sel) {
        const locales = estado.modelos.filter(m => !m.startsWith('gemini:'));
        const nube = estado.modelos.filter(m => m.startsWith('gemini:'));
        sel.innerHTML = (locales.length ? `<optgroup label="En tu equipo">${locales.map(m => `<option ${m === estado.modelo ? 'selected' : ''}>${esc(m)}</option>`).join('')}</optgroup>` : '')
            + (nube.length ? `<optgroup label="Google Gemini · nube">${nube.map(m => `<option value="${esc(m)}" ${m === estado.modelo ? 'selected' : ''}>${esc(m.replace('gemini:', ''))} (Gemini)</option>`).join('')}</optgroup>` : '')
            || '<option>sin modelos</option>';
        sel.onchange = () => { estado.modelo = sel.value; guardarLocal('prig_github_modelo', sel.value); };
    }

    // ================================================================== buscar
    const pareceRepo = (t) => /github\.com[/:]/i.test(t) || /^[\w.-]+\/[\w.-]+$/.test(t.trim());

    function vistaBuscar() {
        const b = estado.busqueda;
        const hoja = $('gh-hoja');
        hoja.innerHTML = `
          <div class="gh-barra-busqueda">
            <input class="gh-campo" id="gh-q" style="flex:1; min-width:260px;" value="${esc(b.q)}" placeholder="Buscar repositorios (web scraping, transformers, api rest…) o pegar un enlace github.com/usuario/repo" spellcheck="false">
            <select class="gh-campo" id="gh-lenguaje">${LENGUAJES.map(l => `<option value="${esc(l)}" ${l === b.lenguaje ? 'selected' : ''}>${l || 'Cualquier lenguaje'}</option>`).join('')}</select>
            <select class="gh-campo" id="gh-orden">${[['estrellas', 'Más estrellas'], ['actualizados', 'Actualizados'], ['forks', 'Más forks'], ['relevancia', 'Relevancia']].map(([v, t]) => `<option value="${v}" ${v === b.orden ? 'selected' : ''}>${t}</option>`).join('')}</select>
            <select class="gh-campo" id="gh-estrellas">${[['', 'Estrellas: todas'], ['100', '100+'], ['1000', '1000+'], ['10000', '10k+']].map(([v, t]) => `<option value="${v}" ${v === b.estrellas_min ? 'selected' : ''}>${t}</option>`).join('')}</select>
            <button class="gh-btn verde" id="gh-buscar"><i class="fa-solid fa-magnifying-glass"></i> Buscar</button>
          </div>
          <div class="gh-partes">
            <div class="gh-resultados" id="gh-resultados"></div>
            <div class="gh-cuadro" id="gh-cuadro"></div>
          </div>`;
        const lanzar = () => {
            const q = $('gh-q').value.trim();
            if (!q) return;
            if (pareceRepo(q)) return abrirRepo(q);
            Object.assign(b, { q, lenguaje: $('gh-lenguaje').value, orden: $('gh-orden').value, estrellas_min: $('gh-estrellas').value, pagina: 1 });
            buscar();
        };
        $('gh-buscar').onclick = lanzar;
        $('gh-q').onkeydown = (e) => { if (e.key === 'Enter') lanzar(); };
        ['gh-lenguaje', 'gh-orden', 'gh-estrellas'].forEach(id => $(id).onchange = () => { if (b.q) lanzar(); });
        $('gh-q').onpaste = () => setTimeout(() => { if (/github\.com\//i.test($('gh-q').value)) lanzar(); }, 0);
        pintarResultados();
        pintarCuadro();
        if (!b.datos) setTimeout(() => $('gh-q') && $('gh-q').focus(), 30);
    }

    async function buscar(anadir = false) {
        const b = estado.busqueda;
        b.cargando = true; b.error = null;
        pintarResultados();
        try {
            const q = new URLSearchParams({ q: b.q, lenguaje: b.lenguaje, orden: b.orden, pagina: b.pagina });
            if (b.estrellas_min) q.set('estrellas_min', b.estrellas_min);
            const d = await json(`/api/github/buscar?${q}`);
            b.datos = anadir && b.datos ? { ...d, repos: [...b.datos.repos, ...d.repos] } : d;
            if (!anadir) { estado.elegido = d.repos[0] || null; pintarCuadro(); }
        } catch (e) { b.error = e.message; }
        b.cargando = false;
        pintarResultados();
    }

    function pintarResultados() {
        const c = $('gh-resultados');
        if (!c) return;
        const b = estado.busqueda;
        const repos = (b.datos && b.datos.repos) || [];
        c.innerHTML = (b.error ? `<div class="gh-error" style="margin-top:10px;">${esc(b.error)}</div>` : '')
            + (b.datos ? `<div class="gh-ayuda" style="margin:8px 0 4px;">${miles(b.datos.total)} repositorios</div>` : '')
            + repos.map((r, i) => `<div class="gh-resultado ${estado.elegido && estado.elegido.ref === r.ref ? 'elegido' : ''}" data-i="${i}">
                <img class="gh-avatar" src="${esc(r.avatar || '')}&s=64" alt="" onerror="this.style.visibility='hidden'">
                <div style="min-width:0; flex:1;">
                  <div class="gh-nombre">${esc(r.ref)}${r.archivado ? ' <span class="gh-ayuda">(archivado)</span>' : ''}</div>
                  <div class="gh-desc">${esc(r.descripcion)}</div>
                  <div class="gh-meta">${r.lenguaje ? `<span><i class="fa-solid fa-circle" style="color:${colorDe(r.lenguaje)}; font-size:8px;"></i> ${esc(r.lenguaje)}</span>` : ''}
                    <span><i class="fa-regular fa-star"></i> ${miles(r.estrellas)}</span><span><i class="fa-solid fa-code-fork"></i> ${miles(r.forks)}</span>
                    <span>Actualizado ${hace(r.actualizado)}</span></div>
                </div></div>`).join('')
            + (b.cargando ? '<div class="gh-ayuda" style="margin:12px;"><i class="fa-solid fa-spinner fa-spin"></i> Buscando en GitHub…</div>' : '')
            + (!b.cargando && b.datos && !repos.length ? '<div class="gh-ayuda" style="margin:12px;">Sin resultados.</div>' : '')
            + (!b.cargando && b.datos && b.datos.hay_mas ? '<button class="gh-btn" id="gh-mas" style="margin:12px 0;">Cargar más</button>' : '')
            + (!b.datos && !b.cargando ? `<div class="gh-vacio"><i class="fa-brands fa-github" style="font-size:44px;"></i>
                <h2>Busca repositorios o pega su enlace</h2><p>Elige uno para ver su ficha; ábrelo para leer su código con el profesor,<br>guardarlo o bajarlo al proyecto.</p>
                <div style="margin-top:16px; padding:12px 16px; background:rgba(203,166,247,0.08); border:1px solid rgba(203,166,247,0.3); border-radius:10px; max-width:480px; text-align:left;">
                    <div style="font-weight:700; color:var(--accent-purple); font-size:13px; display:flex; align-items:center; gap:8px; margin-bottom:6px;">
                        <i class="fa-solid fa-graduation-cap"></i> Compendio de Papers Seminales de Prig IDE
                    </div>
                    <div style="font-size:11.5px; color:var(--text-main); margin-bottom:10px; line-height:1.4;">
                        Las 21 monografías doctorales y algoritmos de Machine Learning ya están publicados en el repositorio de Prig-IDE en GitHub.
                    </div>
                    <div style="display:flex; gap:8px; flex-wrap:wrap;">
                        <button class="gh-btn morado" onclick="window.GitHubLector.abrirRepo('guillermopetcho/Prig-IDE')"><i class="fa-brands fa-github"></i> Abrir guillermopetcho/Prig-IDE</button>
                        <button class="gh-btn" onclick="if(window.cambiarPestanaAprendizaje){window.workArea.abrirHerramienta('modal-seguimiento', 'Aprendizaje Guiado', 'fa-route'); window.cambiarPestanaAprendizaje('papers');}"><i class="fa-solid fa-book-open"></i> Ver Papers en Prig Hub</button>
                    </div>
                </div>
            </div>` : '');
        c.querySelectorAll('[data-i]').forEach(el => {
            el.onclick = () => { estado.elegido = repos[+el.dataset.i]; pintarResultados(); pintarCuadro(); };
            el.ondblclick = () => abrirRepo(repos[+el.dataset.i].ref);
        });
        const mas = $('gh-mas');
        if (mas) mas.onclick = () => { b.pagina++; buscar(true); };
    }

    /** El cuadro descriptivo del repositorio elegido, con lo que se puede hacer */
    function pintarCuadro() {
        const c = $('gh-cuadro');
        if (!c) return;
        const r = estado.elegido;
        if (!r) { c.innerHTML = '<div class="gh-ayuda" style="padding:30px 10px; text-align:center;">Elige un repositorio para ver su ficha.</div>'; return; }
        const guardado = estado.guardados.some(g => g.ref === r.ref);
        c.innerHTML = `<div class="gh-tarjeta">
            <div style="width:100%; aspect-ratio:16/9; border-radius:8px; overflow:hidden; margin-bottom:12px; background:#0d1117; border:1px solid rgba(255,255,255,0.08); display:flex; align-items:center; justify-content:center;">
              <img src="https://opengraph.githubassets.com/1/${esc(r.ref)}" style="width:100%; height:100%; object-fit:cover; display:block;" alt="${esc(r.ref)}" onerror="if(window.prigGhImgFallback){window.prigGhImgFallback(this, '${esc(r.dueno)}', '${esc(r.nombre)}', '${esc(r.lenguaje || '')}');}else{this.style.display='none';}">
            </div>
            <div class="gh-fila" style="flex-wrap:nowrap;"><img class="gh-avatar" style="width:40px; height:40px; border-radius:50%;" src="${esc(r.avatar || '')}&s=80" alt="" onerror="this.style.visibility='hidden'">
              <div style="min-width:0;"><div class="gh-ayuda">${esc(r.dueno)}</div><div style="color:#fff; font-size:17px; font-weight:700; word-break:break-word;">${esc(r.nombre)}</div></div></div>
            <div style="font-size:13px; margin-top:10px; line-height:1.5;">${esc(r.descripcion || 'Sin descripción.')}</div>
            ${r.temas && r.temas.length ? `<div class="gh-fila" style="margin-top:8px;">${r.temas.map(t => `<span class="gh-tema">${esc(t)}</span>`).join('')}</div>` : ''}
            <div class="gh-cifras">
              <div><span>Estrellas</span><b>${miles(r.estrellas)}</b></div><div><span>Forks</span><b>${miles(r.forks)}</b></div>
              <div><span>Issues abiertos</span><b>${miles(r.issues)}</b></div><div><span>Lenguaje</span><b>${esc(r.lenguaje || '—')}</b></div>
              <div><span>Licencia</span><b>${esc(r.licencia || '—')}</b></div><div><span>Tamaño</span><b>${r.kb != null ? tam(r.kb * 1024) : '—'}</b></div>
            </div>
            <div class="gh-ayuda">Último cambio ${hace(r.actualizado)} · rama <code>${esc(r.rama || '')}</code>${r.web ? ` · <a href="${esc(r.web)}" target="_blank" rel="noopener noreferrer">web del proyecto</a>` : ''}</div>
            <div style="display:flex; flex-direction:column; gap:7px; margin-top:14px;">
              <button class="gh-btn verde" data-accion="abrir" style="justify-content:center;"><i class="fa-solid fa-user-graduate"></i> Abrir y analizar con el profesor</button>
              <div class="gh-fila" style="flex-wrap:nowrap;">
                <button class="gh-btn ${guardado ? 'activo' : ''}" data-accion="guardar" style="flex:1; justify-content:center;"><i class="fa-${guardado ? 'solid' : 'regular'} fa-bookmark"></i> ${guardado ? 'Guardado' : 'Guardar'}</button>
                <button class="gh-btn" data-accion="descargar" style="flex:1; justify-content:center;"><i class="fa-solid fa-download"></i> Descargar al proyecto</button></div>
              <a class="gh-btn" href="${esc(r.url)}" target="_blank" rel="noopener noreferrer" style="justify-content:center;"><i class="fa-brands fa-github"></i> Ver en GitHub</a>
            </div>
            <div id="gh-cuadro-estado" style="margin-top:8px;"></div></div>`;
        c.querySelector('[data-accion="abrir"]').onclick = () => abrirRepo(r.ref);
        c.querySelector('[data-accion="guardar"]').onclick = () => alternarGuardado(r.ref).then(pintarCuadro);
        c.querySelector('[data-accion="descargar"]').onclick = () => descargar(r.ref, $('gh-cuadro-estado'));
    }

    // ================================================================== guardados
    async function cargarGuardados() {
        try { estado.guardados = (await json('/api/github/guardados')).repos; } catch (e) { /* sin guardados */ }
    }

    async function alternarGuardado(ref) {
        const esta = estado.guardados.some(g => g.ref === ref);
        try {
            estado.guardados = esta ? (await json(`/api/github/guardados?ref=${encodeURIComponent(ref)}`, { method: 'DELETE' })).repos
                                    : (await enviar('/api/github/guardados', { ref })).repos;
        } catch (e) { alertaEn($('gh-cuadro-estado') || $('gh-repo-estado'), e.message); }
    }

    function alertaEn(zona, mensaje, ok = false) {
        if (zona) zona.innerHTML = `<div class="${ok ? 'gh-ayuda' : 'gh-error'}" ${ok ? 'style="color:#3fb950;"' : ''}>${mensaje}</div>`;
    }

    async function vistaGuardados() {
        const hoja = $('gh-hoja');
        hoja.innerHTML = '<div class="gh-resultados" style="padding:18px 24px;"><div class="gh-ayuda"><i class="fa-solid fa-spinner fa-spin"></i> Cargando…</div></div>';
        await cargarGuardados();
        if (estado.vista !== 'guardados') return;
        hoja.innerHTML = `<div class="gh-resultados" style="padding:18px 24px;">
            <h2 style="color:#fff; margin:0 0 4px; font-size:20px;">Repositorios guardados</h2>
            <div class="gh-ayuda" style="margin-bottom:10px;">Los que marcaste para volver a ellos. Se abren sin gastar consultas de GitHub si los abriste hace menos de un día.</div>
            ${estado.guardados.map((r, i) => `<div class="gh-resultado" data-i="${i}">
                <img class="gh-avatar" src="${esc(r.avatar || '')}&s=64" alt="" onerror="this.style.visibility='hidden'">
                <div style="min-width:0; flex:1;"><div class="gh-nombre">${esc(r.ref)}</div><div class="gh-desc">${esc(r.descripcion || '')}</div>
                  <div class="gh-meta">${r.lenguaje ? `<span>${esc(r.lenguaje)}</span>` : ''}<span><i class="fa-regular fa-star"></i> ${miles(r.estrellas)}</span><span>guardado ${hace(r.guardado)}</span></div></div>
                <button class="gh-btn" data-quitar="${i}" title="Quitar de guardados"><i class="fa-solid fa-xmark"></i></button></div>`).join('')
              || '<div class="gh-vacio"><i class="fa-regular fa-bookmark" style="font-size:36px;"></i><h2>Nada guardado todavía</h2><p>Pulsa «Guardar» en la ficha de cualquier repositorio.</p></div>'}
          </div>`;
        hoja.querySelectorAll('[data-i]').forEach(el => el.onclick = (e) => {
            if (e.target.closest('[data-quitar]')) return;
            abrirRepo(estado.guardados[+el.dataset.i].ref);
        });
        hoja.querySelectorAll('[data-quitar]').forEach(b => b.onclick = async () => {
            await alternarGuardado(estado.guardados[+b.dataset.quitar].ref);
            vistaGuardados();
        });
    }

    // ================================================================== repositorio
    async function abrirRepo(ref) {
        estado.vista = 'repo';
        document.querySelectorAll('#gh-nav [data-vista]').forEach(b => b.classList.toggle('activa', b.dataset.vista === 'repo'));
        const hoja = $('gh-hoja');
        hoja.innerHTML = '<div class="gh-vacio"><i class="fa-solid fa-spinner fa-spin fa-2x"></i><p>Leyendo el repositorio de GitHub…</p></div>';
        try {
            estado.repo = await json(`/api/github/repo?ref=${encodeURIComponent(ref)}`);
        } catch (e) {
            hoja.innerHTML = `<div style="padding:20px;"><div class="gh-error">${esc(e.message)}</div><button class="gh-btn" style="margin-top:10px;" id="gh-volver-buscar">Volver a buscar</button></div>`;
            $('gh-volver-buscar').onclick = () => ir('buscar');
            return;
        }
        guardarLocal('prig_github_repo', estado.repo.ref);
        estado.archivo = null;
        estado.contenido = null;
        estado.chat = [];
        estado.explicacion = estado.repo.explicadas.repo ? { tipo: 'repo', texto: estado.repo.explicadas.repo.texto, guardada: true } : null;
        const nav = $('gh-nav-repo');
        nav.hidden = false;
        nav.querySelector('span').textContent = estado.repo.nombre;
        await cargarGuardados();
        pintarRepo();
    }

    // ================================================================== disposición tipo IDE
    // Anchos y posición del profesor, recordados entre sesiones
    const disposicion = (() => {
        const def = { arbol: true, prof: 'der', a: 250, p: 0.38, ph: 0.4 };
        try { return { ...def, ...JSON.parse(leerLocal('prig_gh_disposicion') || '{}') }; } catch (e) { return def; }
    })();

    function aplicarDisposicion() {
        const g = $('gh-repo');
        if (!g) return;
        g.classList.toggle('sin-arbol', !disposicion.arbol);
        g.classList.toggle('prof-abajo', disposicion.prof === 'abajo');
        g.classList.toggle('sin-prof', disposicion.prof === 'no');
        if (disposicion.arbol) g.style.setProperty('--a', `${Math.round(disposicion.a)}px`); else g.style.removeProperty('--a');
        if (disposicion.prof !== 'no') {
            g.style.setProperty('--p', `${(disposicion.p * 100).toFixed(1)}%`);
            g.style.setProperty('--ph', `${(disposicion.ph * 100).toFixed(1)}%`);
        } else { g.style.removeProperty('--p'); g.style.removeProperty('--ph'); }
        const marcar = (id, si) => { const b = $(id); if (b) b.classList.toggle('activo', si); };
        marcar('gh-v-arbol', disposicion.arbol);
        marcar('gh-v-der', disposicion.prof === 'der');
        marcar('gh-v-abajo', disposicion.prof === 'abajo');
        marcar('gh-v-no', disposicion.prof === 'no');
    }

    function cambiarDisposicion(cambios) {
        Object.assign(disposicion, cambios);
        guardarLocal('prig_gh_disposicion', JSON.stringify(disposicion));
        aplicarDisposicion();
    }

    function activarDivisores() {
        const g = $('gh-repo');
        const arrastrar = (div, mover) => {
            if (!div) return;
            div.addEventListener('pointerdown', (e) => {
                if (e.button !== 0) return;
                e.preventDefault();
                div.setPointerCapture(e.pointerId);
                div.classList.add('arrastrando');
                document.body.classList.add('gh-redimensionando');
                const r = g.getBoundingClientRect();
                const alMover = (ev) => { mover(ev, r); aplicarDisposicion(); };
                const alSoltar = () => {
                    div.removeEventListener('pointermove', alMover);
                    div.removeEventListener('pointerup', alSoltar);
                    div.removeEventListener('pointercancel', alSoltar);
                    div.classList.remove('arrastrando');
                    document.body.classList.remove('gh-redimensionando');
                    guardarLocal('prig_gh_disposicion', JSON.stringify(disposicion));
                };
                div.addEventListener('pointermove', alMover);
                div.addEventListener('pointerup', alSoltar);
                div.addEventListener('pointercancel', alSoltar);
            });
            // Doble clic: volver al tamaño por defecto
            div.addEventListener('dblclick', () => mover(null, null));
        };
        const lim = (v, a, b) => Math.max(a, Math.min(b, v));
        arrastrar($('gh-div-arbol'), (ev, r) => {
            disposicion.a = ev ? lim(ev.clientX - r.left, 120, r.width * 0.5) : 250;
            if (!ev) cambiarDisposicion({});
        });
        arrastrar($('gh-div-prof'), (ev, r) => {
            if (!ev) { disposicion.p = 0.38; disposicion.ph = 0.4; cambiarDisposicion({}); return; }
            if (disposicion.prof === 'abajo') disposicion.ph = lim((r.bottom - ev.clientY) / r.height, 0.15, 0.8);
            else disposicion.p = lim((r.right - ev.clientX) / r.width, 0.18, 0.7);
        });
    }

    function pintarRepo() {
        const r = estado.repo;
        const hoja = $('gh-hoja');
        const nExplicados = Object.keys(r.explicadas.archivos).length;
        hoja.innerHTML = `
          <div class="gh-cabecera ${estado.archivo ? 'compacta' : ''}" id="gh-cabecera">
            <div class="gh-fila" style="flex-wrap:nowrap;">
              <img class="gh-avatar" style="width:26px; height:26px;" src="${esc(r.avatar || '')}&s=52" alt="" onerror="this.style.visibility='hidden'">
              <span style="color:#fff; font-size:16px; font-weight:700; flex:1; min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">${esc(r.ref)}</span>
              <span class="gh-ayuda"><i class="fa-regular fa-star"></i> ${miles(r.estrellas)} · <i class="fa-solid fa-code-fork"></i> ${miles(r.forks)} · ${r.archivos.length} archivos${r.truncado ? ' (lista recortada)' : ''}</span>
            </div>
            ${r.lenguajes.length ? `<div class="gh-lenguajes" title="${esc(r.lenguajes.map(l => `${l.nombre} ${l.pct}%`).join(' · '))}">${r.lenguajes.map(l => `<div style="width:${l.pct}%; background:${colorDe(l.nombre)};"></div>`).join('')}</div>
              <div class="gh-fila gh-ayuda gh-leyenda-leng">${r.lenguajes.slice(0, 5).map(l => `<span><i class="fa-solid fa-circle" style="color:${colorDe(l.nombre)}; font-size:8px;"></i> ${esc(l.nombre)} ${l.pct}%</span>`).join('')}</div>` : ''}
            <div class="gh-fila" style="margin-top:8px;">
              <button class="gh-btn morado" id="gh-explicar-repo"><i class="fa-solid fa-diagram-project"></i> Explicar el repositorio</button>
              <button class="gh-btn ${estado.guardados.some(g => g.ref === r.ref) ? 'activo' : ''}" id="gh-guardar"><i class="fa-${estado.guardados.some(g => g.ref === r.ref) ? 'solid' : 'regular'} fa-bookmark"></i> ${estado.guardados.some(g => g.ref === r.ref) ? 'Guardado' : 'Guardar'}</button>
              <button class="gh-btn" id="gh-descargar"><i class="fa-solid fa-download"></i> ${r.local ? 'Volver a descargar' : 'Descargar al proyecto'}</button>
              <div style="position:relative;"><button class="gh-btn" id="gh-exportar"><i class="fa-solid fa-file-export"></i> Exportar lo explicado <i class="fa-solid fa-caret-down"></i></button></div>
              <a class="gh-btn" href="${esc(r.url)}" target="_blank" rel="noopener noreferrer"><i class="fa-brands fa-github"></i></a>
              <span style="flex:1"></span>
              <select class="gh-campo" id="gh-nivel" title="Profundidad de las explicaciones">${['principiante', 'intermedio', 'avanzado'].map(n => `<option ${n === estado.nivel ? 'selected' : ''}>${n}</option>`).join('')}</select>
              <select class="gh-campo" id="gh-modelo" style="max-width:220px;" title="Modelo que te acompaña"></select>
              <div class="gh-vista-btns" title="Disposición de los paneles (los divisores se arrastran)">
                <button id="gh-v-arbol" title="Mostrar u ocultar el árbol de archivos"><i class="fa-solid fa-folder-tree"></i></button>
                <button id="gh-v-der" title="Profesor a la derecha"><i class="fa-solid fa-table-columns"></i></button>
                <button id="gh-v-abajo" title="Profesor abajo"><i class="fa-solid fa-table-list"></i></button>
                <button id="gh-v-no" title="Ocultar el profesor"><i class="fa-regular fa-comment-slash"></i></button>
              </div>
            </div>
            <div id="gh-repo-estado" class="gh-ayuda" style="margin-top:6px;">${r.local ? `<i class="fa-solid fa-circle-check" style="color:#3fb950;"></i> Descargado en <b>${esc(r.local.relativa)}</b> · ` : ''}${nExplicados} archivos explicados${r.explicadas.repo ? ' · con explicación del repositorio' : ''}</div>
          </div>
          <div class="gh-repo" id="gh-repo">
            <div class="gh-arbol"><input class="gh-campo" id="gh-filtro" placeholder="Filtrar archivos…" value="${esc(estado.filtroArbol)}" style="width:100%; margin-bottom:6px;"><div id="gh-arbol"></div></div>
            <div class="gh-div gh-div-arbol" id="gh-div-arbol" title="Arrastra para cambiar el ancho del árbol"></div>
            <div class="gh-centro" id="gh-centro"></div>
            <div class="gh-div gh-div-prof" id="gh-div-prof" title="Arrastra para cambiar el tamaño del profesor"></div>
            <div class="gh-profesor">
              <div class="gh-explicacion" id="gh-explicacion"></div>
              <div class="gh-chat">
                <div class="gh-msgs" id="gh-msgs"></div>
                <div class="gh-fila" style="flex-wrap:nowrap;"><input class="gh-campo" id="gh-pregunta" style="flex:1;" placeholder="Pregunta al profesor sobre el repositorio o el archivo abierto…">
                  <button class="gh-btn verde" id="gh-preguntar"><i class="fa-solid fa-paper-plane"></i></button></div>
              </div>
            </div>
          </div>`;
        pintarModelos($('gh-modelo'));
        aplicarDisposicion();
        $('gh-v-arbol').onclick = () => cambiarDisposicion({ arbol: !disposicion.arbol });
        $('gh-v-der').onclick = () => cambiarDisposicion({ prof: 'der' });
        $('gh-v-abajo').onclick = () => cambiarDisposicion({ prof: 'abajo' });
        $('gh-v-no').onclick = () => cambiarDisposicion({ prof: disposicion.prof === 'no' ? 'der' : 'no' });
        activarDivisores();
        $('gh-nivel').onchange = (e) => { estado.nivel = e.target.value; guardarLocal('prig_github_nivel', estado.nivel); };
        $('gh-explicar-repo').onclick = () => explicar(null, !!estado.repo.explicadas.repo && estado.explicacion && estado.explicacion.tipo === 'repo');
        $('gh-guardar').onclick = async () => { await alternarGuardado(r.ref); pintarRepo(); };
        $('gh-descargar').onclick = () => descargar(r.ref, $('gh-repo-estado'), true);
        $('gh-exportar').onclick = (e) => menuExportar(e.currentTarget);
        $('gh-filtro').oninput = (e) => { estado.filtroArbol = e.target.value; pintarArbol(); };
        $('gh-preguntar').onclick = preguntar;
        $('gh-pregunta').onkeydown = (e) => { if (e.key === 'Enter') preguntar(); };
        pintarArbol();
        pintarCentro();
        pintarExplicacion();
        pintarChat();
    }

    function pintarArbol() {
        const c = $('gh-arbol');
        if (!c) return;
        const r = estado.repo;
        const filtro = estado.filtroArbol.trim().toLowerCase();
        const explicados = r.explicadas.archivos;
        const archivos = r.archivos.filter(a => !filtro || a.ruta.toLowerCase().includes(filtro));
        const raiz = { carpetas: {}, archivos: [] };
        archivos.forEach(a => {
            const partes = a.ruta.split('/');
            let nodo = raiz;
            partes.slice(0, -1).forEach(p => { nodo = nodo.carpetas[p] || (nodo.carpetas[p] = { carpetas: {}, archivos: [] }); });
            nodo.archivos.push(a);
        });
        const abiertoPor = (ruta) => estado.archivo && (estado.archivo + '/').startsWith(ruta + '/');
        const pintar = (nodo, prefijo, nivel) =>
            Object.keys(nodo.carpetas).sort().map(n => {
                const ruta = prefijo ? `${prefijo}/${n}` : n;
                return `<details ${filtro || abiertoPor(ruta) || (nivel === 0 && Object.keys(raiz.carpetas).length <= 2) ? 'open' : ''}><summary><i class="fa-regular fa-folder" style="color:#79c0ff;"></i> ${esc(n)}</summary><div>${pintar(nodo.carpetas[n], ruta, nivel + 1)}</div></details>`;
            }).join('')
            + nodo.archivos.sort((a, b) => a.ruta.localeCompare(b.ruta)).map(a => `<div class="gh-archivo ${estado.archivo === a.ruta ? 'activo' : ''}" data-ruta="${esc(a.ruta)}" title="${esc(a.ruta)} · ${tam(a.bytes)}">
                <i class="fa-regular ${a.ruta === r.readme_ruta ? 'fa-file-lines' : 'fa-file-code'}" style="opacity:.7;"></i><span style="overflow:hidden; text-overflow:ellipsis;">${esc(a.ruta.split('/').pop())}</span>
                ${explicados[a.ruta] ? '<i class="fa-solid fa-check" style="color:#3fb950; margin-left:auto;" title="Explicado"></i>' : ''}</div>`).join('');
        c.innerHTML = pintar(raiz, '', 0) || '<div class="gh-ayuda" style="padding:6px;">Ningún archivo coincide.</div>';
        c.querySelectorAll('[data-ruta]').forEach(el => el.onclick = () => abrirArchivo(el.dataset.ruta));
    }

    // ================================================================== cuadernos Jupyter
    const texto = (v) => Array.isArray(v) ? v.join('') : String(v ?? '');
    const sinAnsi = (t) => t.replace(/\x1b\[[0-9;]*[A-Za-z]/g, '');

    function lenguajeCuaderno(nb) {
        const m = nb.metadata || {};
        const l = String((m.kernelspec && m.kernelspec.language) || (m.language_info && m.language_info.name) || 'python').toLowerCase();
        return /c\+\+|cpp|xcpp|cling/.test(l) ? 'cpp' : l === 'r' ? 'r' : l === 'julia' ? 'julia' : 'python';
    }

    function resaltar(codigo, lenguaje) {
        if (!window.hljs || codigo.length > 100000) return esc(codigo);
        try { return hljs.getLanguage(lenguaje) ? hljs.highlight(codigo, { language: lenguaje }).value : hljs.highlightAuto(codigo).value; }
        catch (e) { return esc(codigo); }
    }

    /** Una salida de celda. El HTML y el SVG de un repositorio ajeno solo se muestran saneados
     * (DOMPurify); sin saneador, su versión en texto. */
    function salidaCelda(o) {
        const tipo = o.output_type;
        if (tipo === 'stream') {
            return `<div class="gh-nb-out ${o.name === 'stderr' ? 'error' : ''}">${esc(sinAnsi(texto(o.text)))}</div>`;
        }
        if (tipo === 'error' || tipo === 'pyerr') {
            const tb = (o.traceback || []).map(sinAnsi).join('\n') || `${o.ename}: ${o.evalue}`;
            return `<div class="gh-nb-out error">${esc(tb)}</div>`;
        }
        const d = o.data || (o.text ? { 'text/plain': o.text } : {});
        if (d['image/png']) return `<div class="gh-nb-out"><img alt="" src="data:image/png;base64,${esc(texto(d['image/png']).replace(/\s/g, ''))}"></div>`;
        if (d['image/jpeg']) return `<div class="gh-nb-out"><img alt="" src="data:image/jpeg;base64,${esc(texto(d['image/jpeg']).replace(/\s/g, ''))}"></div>`;
        if (window.DOMPurify && d['image/svg+xml']) return `<div class="gh-nb-out">${DOMPurify.sanitize(texto(d['image/svg+xml']), { USE_PROFILES: { svg: true } })}</div>`;
        if (window.DOMPurify && d['text/html']) return `<div class="gh-nb-out" style="white-space:normal;">${DOMPurify.sanitize(texto(d['text/html']))}</div>`;
        if (d['text/markdown']) return `<div class="gh-nb-out gh-md" data-md="${esc(texto(d['text/markdown']))}"></div>`;
        if (d['text/plain']) return `<div class="gh-nb-out">${esc(sinAnsi(texto(d['text/plain'])))}</div>`;
        return '';
    }

    /** El .ipynb como cuaderno: markdown, código resaltado y salidas. false si no se puede leer. */
    function pintarCuaderno(contenedor, crudo) {
        let nb;
        try { nb = JSON.parse(crudo); } catch (e) { return false; }
        const celdas = nb.cells || (nb.worksheets && nb.worksheets[0] && nb.worksheets[0].cells);
        if (!Array.isArray(celdas)) return false;
        const lenguaje = lenguajeCuaderno(nb);
        contenedor.innerHTML = `<div class="gh-nb">${celdas.map((cel, i) => {
            const src = texto(cel.source ?? cel.input);
            if (cel.cell_type === 'markdown') return `<div class="gh-nb-celda md"><div class="gh-md" data-celda="${i}"></div></div>`;
            if (cel.cell_type === 'code') {
                const n = cel.execution_count ?? cel.prompt_number;
                return `<div class="gh-nb-celda"><div class="gh-nb-in"><div class="gh-nb-prompt">[${n ?? ' '}]:</div>
                  <pre><code class="hljs">${resaltar(src, lenguaje)}</code></pre></div>${(cel.outputs || []).map(salidaCelda).join('')}</div>`;
            }
            return `<div class="gh-nb-celda"><div class="gh-nb-out">${esc(src)}</div></div>`;
        }).join('') || '<div class="gh-vacio">El cuaderno está vacío.</div>'}</div>`;
        contenedor.querySelectorAll('[data-celda]').forEach(el => md(el, texto(celdas[+el.dataset.celda].source)));
        contenedor.querySelectorAll('[data-md]').forEach(el => md(el, el.dataset.md));
        return true;
    }

    function pintarCentro() {
        const c = $('gh-centro');
        if (!c) return;
        const r = estado.repo;
        // Dentro de un archivo, la cabecera se compacta: sin barra de lenguajes ni foto
        const cab = $('gh-cabecera');
        if (cab) cab.classList.toggle('compacta', !!estado.archivo);
        if (!estado.archivo) {
            c.innerHTML = r.readme ? `<div class="gh-ayuda" style="padding:10px 22px 0;"><i class="fa-regular fa-file-lines"></i> ${esc(r.readme_ruta)}</div><div class="gh-md" id="gh-readme"></div>`
                : '<div class="gh-vacio">Este repositorio no tiene README. Elige un archivo a la izquierda.</div>';
            const el = $('gh-readme');
            if (el) {
                md(el, r.readme);
                // Imágenes relativas del README: se piden en crudo a GitHub
                el.querySelectorAll('img[src]').forEach(img => {
                    const src = img.getAttribute('src');
                    if (src && !/^(https?:|data:)/.test(src)) img.src = `https://raw.githubusercontent.com/${r.ref}/${r.rama}/${src.replace(/^\.?\//, '')}`;
                });
            }
            return;
        }
        const a = estado.contenido;
        if (!a) { c.innerHTML = '<div class="gh-ayuda" style="padding:16px;"><i class="fa-solid fa-spinner fa-spin"></i> Leyendo el archivo…</div>'; return; }
        if (a.error) { c.innerHTML = `<div style="padding:16px;"><div class="gh-error">${esc(a.error)}</div></div>`; return; }
        if (a.binario || a.grande) {
            c.innerHTML = `<div class="gh-vacio">${a.binario ? 'Es un archivo binario' : `Pesa ${tam(a.bytes)}: demasiado para leerlo aquí`}.<br>Descarga el repositorio para abrirlo en local.</div>`;
            return;
        }
        const esCodigo = /\.(py|cpp|cc|cxx|c|hpp|h|ipynb)$/i.test(a.ruta);
        const esCuaderno = /\.ipynb$/i.test(a.ruta);
        const cabecera = `<div class="gh-fila gh-ayuda" style="padding:8px 14px; border-bottom:1px solid rgba(255,255,255,.06); position:sticky; top:0; background:var(--bg-dark); z-index:1;">
            <i class="fa-regular ${esCuaderno ? 'fa-note-sticky' : 'fa-file-code'}"></i> <b style="color:#fff;">${esc(a.ruta)}</b> · ${esCuaderno ? 'cuaderno Jupyter' : `${a.lineas} líneas`} · ${tam(a.bytes)}
            <span style="flex:1"></span>
            ${esCuaderno ? `<button class="gh-btn" id="gh-ver-json" title="Alternar entre el cuaderno y su JSON">${estado.verJson ? '<i class="fa-solid fa-book-open"></i> Ver cuaderno' : '<i class="fa-solid fa-code"></i> Ver JSON'}</button>` : ''}
            ${esCodigo ? '<button class="gh-btn verde" id="gh-replicar-desafio" title="Replicar este archivo como un desafío interactivo en Prig"><i class="fa-solid fa-chess-knight"></i> Replicar como Desafío</button>' : ''}
            <button class="gh-btn" id="gh-volver-readme">README</button></div>`;
        if (a.lenguaje === 'markdown') {
            c.innerHTML = cabecera + '<div class="gh-md" id="gh-md-archivo"></div>';
            md($('gh-md-archivo'), a.contenido);
        } else if (esCuaderno && !estado.verJson && (() => {
            c.innerHTML = cabecera + '<div id="gh-cuaderno"></div>';
            return pintarCuaderno($('gh-cuaderno'), a.contenido);
        })()) {
            // pintado como cuaderno; si el JSON no se entiende, cae abajo como texto
        } else {
            let html = esc(a.contenido);
            if (window.hljs && a.contenido.length < 200000) {
                try { html = a.lenguaje !== 'plaintext' && hljs.getLanguage(a.lenguaje) ? hljs.highlight(a.contenido, { language: a.lenguaje }).value : hljs.highlightAuto(a.contenido).value; } catch (e) { /* texto plano */ }
            }
            const nums = Array.from({ length: a.lineas }, (_, i) => i + 1).join('\n');
            c.innerHTML = cabecera + `<div class="gh-lineas"><div class="num">${nums}</div><pre class="gh-codigo"><code class="hljs">${html}</code></pre></div>`;
        }
        $('gh-volver-readme').onclick = () => { estado.archivo = null; pintarArbol(); pintarCentro(); pintarExplicacion(); };
        const verJson = $('gh-ver-json');
        if (verJson) verJson.onclick = () => { estado.verJson = !estado.verJson; pintarCentro(); };
        const btnRep = $('gh-replicar-desafio');
        if (btnRep) btnRep.onclick = async () => {
            btnRep.disabled = true;
            const orig = btnRep.innerHTML;
            btnRep.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Replicando…';
            try {
                const ext = (a.ruta.split('.').pop() || '').toLowerCase();
                const lang = ['cpp', 'cc', 'cxx', 'c', 'h', 'hpp'].includes(ext) ? 'cpp' : 'python';
                const r = await flujo('/api/desafios/github/replicar', {
                    ref: estado.repo.ref,
                    ruta: a.ruta,
                    contenido: a.contenido,
                    lenguaje: lang,
                    modelo: estado.modelo
                }, (ev) => {
                    if (ev.tipo === 'progreso') {
                        btnRep.title = ev.mensaje;
                        if (ev.tokens) {
                            btnRep.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i> ${ev.tokens} tok…`;
                        } else if (ev.intento) {
                            btnRep.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i> Intento ${ev.intento}…`;
                        }
                    }
                });
                if (window.Desafios && window.Desafios.abrir) {
                    window.Desafios.abrir({ id: r.id });
                } else {
                    alert(`¡Desafío «${r.titulo}» creado con éxito! Puedes abrirlo en la herramienta Desafíos.`);
                }
            } catch (e) {
                alert(`Error al replicar como desafío: ${e.message}`);
            } finally {
                btnRep.disabled = false;
                btnRep.innerHTML = orig;
            }
        };
    }

    async function abrirArchivo(ruta) {
        estado.archivo = ruta;
        estado.contenido = null;
        const guardada = estado.repo.explicadas.archivos[ruta];
        estado.explicacion = guardada ? { tipo: 'archivo', ruta, texto: guardada.texto, guardada: true } : null;
        pintarArbol();
        pintarCentro();
        pintarExplicacion();
        try {
            estado.contenido = await json(`/api/github/archivo?ref=${encodeURIComponent(estado.repo.ref)}&ruta=${encodeURIComponent(ruta)}`);
        } catch (e) { estado.contenido = { error: e.message }; }
        if (estado.archivo === ruta) pintarCentro();
    }

    // ------------------------------------------------------------------ profesor
    function pintarExplicacion(cargando) {
        const c = $('gh-explicacion');
        if (!c) return;
        const r = estado.repo;
        const e = estado.explicacion;
        const sobreArchivo = !!estado.archivo;
        const titulo = sobreArchivo ? `<i class="fa-regular fa-file-code"></i> ${esc(estado.archivo.split('/').pop())}` : '<i class="fa-solid fa-diagram-project"></i> El repositorio en conjunto';
        if (!e || (sobreArchivo && e.tipo === 'repo')) {
            c.innerHTML = `<div class="gh-fila" style="margin-bottom:10px;"><b style="color:var(--accent-purple);">${titulo}</b></div>
                <div class="gh-ayuda" style="margin-bottom:10px;">${sobreArchivo
                    ? 'El profesor lee este archivo con la estructura del repositorio y te explica qué hace, sus partes importantes y cómo encaja.'
                    : 'El profesor lee el README, la estructura y el código de los archivos clave y te cuenta qué es, cómo está organizado, cómo funciona y por dónde empezar a leer.'}</div>
                <button class="gh-btn morado" id="gh-pedir"><i class="fa-solid fa-user-graduate"></i> ${sobreArchivo ? 'Explicar este archivo' : 'Explicar el repositorio'}</button>
                ${!sobreArchivo && Object.keys(r.explicadas.archivos).length ? `<div class="gh-ayuda" style="margin-top:14px;"><b>Archivos ya explicados:</b><br>${Object.keys(r.explicadas.archivos).map(x => `<a href="#" data-ir="${esc(x)}">${esc(x)}</a>`).join('<br>')}</div>` : ''}`;
            $('gh-pedir').onclick = () => explicar(sobreArchivo ? estado.archivo : null, false);
            c.querySelectorAll('[data-ir]').forEach(a => a.onclick = (ev) => { ev.preventDefault(); abrirArchivo(a.dataset.ir); });
            return;
        }
        c.innerHTML = `<div class="gh-fila" style="margin-bottom:6px;"><b style="color:var(--accent-purple); flex:1;">${titulo}</b>
              ${e.guardada && !cargando ? '<span class="gh-ayuda">guardada</span>' : ''}
              ${cargando ? '' : '<button class="gh-btn" id="gh-rehacer" title="Pedir otra explicación" style="padding:3px 7px;"><i class="fa-solid fa-rotate"></i></button>'}</div>
            <div id="gh-texto"></div>`;
        const t = $('gh-texto');
        if (e.texto) md(t, e.texto);
        else t.innerHTML = `<span class="gh-ayuda"><i class="fa-solid fa-spinner fa-spin"></i> ${e.pensando ? 'El profesor está razonando…' : 'El profesor está leyendo…'}</span>`;
        // Las rutas citadas en la explicación llevan al archivo
        t.querySelectorAll('code').forEach(code => {
            const ruta = code.textContent.trim().replace(/^\.?\//, '');
            if (r.archivos.some(a => a.ruta === ruta)) {
                code.style.cursor = 'pointer';
                code.style.textDecoration = 'underline dotted';
                code.title = 'Abrir este archivo';
                code.onclick = () => abrirArchivo(ruta);
            }
        });
        const rehacer = $('gh-rehacer');
        if (rehacer) rehacer.onclick = () => explicar(e.tipo === 'archivo' ? e.ruta : null, true);
    }

    async function explicar(ruta, regenerar) {
        const r = estado.repo;
        if (ruta === null && estado.archivo) { estado.archivo = null; pintarArbol(); pintarCentro(); }
        estado.explicacion = { tipo: ruta ? 'archivo' : 'repo', ruta, texto: '', guardada: false };
        pintarExplicacion(true);
        const actual = estado.explicacion;
        try {
            const fin = await flujo('/api/github/explicar', { ref: r.ref, ruta, nivel: estado.nivel, modelo: estado.modelo, regenerar }, (ev) => {
                if (estado.explicacion !== actual) return;
                if (ev.tipo === 'texto') { actual.texto += ev.delta; pintarExplicacion(true); }
                if (ev.tipo === 'pensando' && !actual.texto && !actual.pensando) { actual.pensando = true; pintarExplicacion(true); }
            });
            actual.texto = fin.texto;
            actual.guardada = fin.guardada;
            const ahora = { texto: fin.texto, fecha: new Date().toISOString(), ruta, nivel: estado.nivel };
            if (ruta) r.explicadas.archivos[ruta] = ahora; else r.explicadas.repo = ahora;
            if (estado.explicacion === actual) { pintarExplicacion(); pintarArbol(); actualizarEstadoRepo(); }
        } catch (e) {
            if (estado.explicacion === actual) {
                $('gh-explicacion').innerHTML = `<div class="gh-error">${esc(e.message)}</div><button class="gh-btn" style="margin-top:8px;" id="gh-reintentar">Reintentar</button>`;
                $('gh-reintentar').onclick = () => explicar(ruta, regenerar);
            }
        }
    }

    function actualizarEstadoRepo() {
        const r = estado.repo;
        const z = $('gh-repo-estado');
        if (z) z.innerHTML = `${r.local ? `<i class="fa-solid fa-circle-check" style="color:#3fb950;"></i> Descargado en <b>${esc(r.local.relativa)}</b> · ` : ''}${Object.keys(r.explicadas.archivos).length} archivos explicados${r.explicadas.repo ? ' · con explicación del repositorio' : ''}`;
    }

    function pintarChat() {
        const c = $('gh-msgs');
        if (!c) return;
        c.hidden = !estado.chat.length;
        c.innerHTML = estado.chat.map((m, i) => `<div class="gh-msg ${m.rol}" data-i="${i}"></div>`).join('');
        c.querySelectorAll('[data-i]').forEach(el => md(el, estado.chat[+el.dataset.i].texto || '…'));
        c.scrollTop = c.scrollHeight;
    }

    async function preguntar() {
        const campo = $('gh-pregunta');
        const t = campo.value.trim();
        if (!t || !estado.repo) return;
        campo.value = '';
        estado.chat.push({ rol: 'usuario', texto: t + (estado.archivo ? `  \n*(sobre ${estado.archivo})*` : '') });
        const respuesta = { rol: 'profesor', texto: '' };
        estado.chat.push(respuesta);
        pintarChat();
        try {
            await flujo('/api/github/preguntar', { ref: estado.repo.ref, ruta: estado.archivo, modelo: estado.modelo,
                                                   mensajes: estado.chat.slice(0, -1).map(m => ({ rol: m.rol, texto: m.texto })) }, (ev) => {
                if (ev.tipo === 'texto') {
                    respuesta.texto += ev.delta;
                    const el = document.querySelector(`#gh-msgs [data-i="${estado.chat.indexOf(respuesta)}"]`);
                    if (el) md(el, respuesta.texto);
                }
            });
        } catch (e) { respuesta.texto = `*No pude responder: ${e.message}*`; }
        pintarChat();
    }

    // ------------------------------------------------------------------ guardar, descargar y exportar
    async function descargar(ref, zona, refrescar) {
        if (!zona) return;
        zona.innerHTML = '<span class="gh-ayuda"><i class="fa-solid fa-spinner fa-spin"></i> Pidiendo el repositorio a GitHub…</span>';
        try {
            const r = await flujo('/api/github/descargar', { ref }, (ev) => {
                if (ev.tipo === 'progreso') zona.innerHTML = `<span class="gh-ayuda"><i class="fa-solid fa-spinner fa-spin"></i> ${esc(ev.mensaje)}</span>`;
            });
            if (window.fileTreeMgr) window.fileTreeMgr.loadTree();
            zona.innerHTML = `<span class="gh-ayuda" style="color:#3fb950;"><i class="fa-solid fa-check"></i> ${r.archivos} archivos (${tam(r.bytes)}) en <b>${esc(r.relativa)}</b>.</span>
                <a href="#" data-mostrar>Mostrar en la carpeta</a>`;
            zona.querySelector('[data-mostrar]').onclick = (e) => { e.preventDefault(); enviar('/api/ide/mostrar-en-sistema', { path: r.carpeta }).catch(() => {}); };
            if (refrescar && estado.repo && estado.repo.ref === ref) estado.repo.local = r;
        } catch (e) { alertaEn(zona, esc(e.message)); }
    }

    function menuExportar(boton) {
        const previo = document.querySelector('.gh-menu');
        if (previo) { previo.remove(); return; }
        const m = document.createElement('div');
        m.className = 'gh-menu';
        m.style.top = '32px';
        m.style.left = '0';
        m.innerHTML = `<button data-formato="md"><i class="fa-brands fa-markdown" style="margin-top:2px;"></i><span><b>Guardar la explicación</b><br><span class="gh-ayuda">Markdown con el resumen y cada archivo explicado</span></span></button>
            <button data-formato="pdf"><i class="fa-solid fa-file-pdf" style="margin-top:2px; color:#f38ba8;"></i><span><b>Código explicado (PDF)</b><br><span class="gh-ayuda">Cada archivo con su código y la explicación debajo</span></span></button>`;
        boton.parentElement.appendChild(m);
        const cerrar = (e) => { if (!m.contains(e.target) && e.target !== boton) { m.remove(); document.removeEventListener('mousedown', cerrar, true); } };
        setTimeout(() => document.addEventListener('mousedown', cerrar, true), 0);
        m.querySelectorAll('[data-formato]').forEach(b => b.onclick = async () => {
            m.remove();
            const zona = $('gh-repo-estado');
            zona.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Preparando el archivo…';
            try {
                const r = await enviar('/api/github/exportar', { ref: estado.repo.ref, nota: b.dataset.formato });
                const url = `/api/github/exportado?ruta=${encodeURIComponent(r.ruta)}`;
                zona.innerHTML = `<span style="color:#3fb950;"><i class="fa-solid fa-check"></i> Guardado en <b>${esc(r.relativa)}</b>${r.paginas ? ` · ${r.paginas} páginas` : ''} · ${r.archivos} archivos explicados${r.con_resumen ? ' + resumen' : ''}</span>
                    · <a href="${url}" target="_blank" rel="noopener noreferrer">ver</a> · <a href="${url}&descargar=true" download>guardar como…</a> · <a href="#" data-mostrar>mostrar en la carpeta</a>`;
                zona.querySelector('[data-mostrar]').onclick = (e) => { e.preventDefault(); enviar('/api/ide/mostrar-en-sistema', { path: r.ruta }).catch(() => {}); };
                if (window.fileTreeMgr) window.fileTreeMgr.loadTree();
            } catch (e) { alertaEn(zona, esc(e.message)); }
        });
    }

    // ================================================================== entrada
    function abrir(opciones = {}) {
        if (window.workArea) window.workArea.abrirHerramienta('modal-github', 'GitHub', 'fa-code-branch');
        montar();
        if (opciones.ref) abrirRepo(opciones.ref);
    }

    document.addEventListener('prig:herramienta-abierta', (e) => {
        if (e.detail && e.detail.modalId === 'modal-github') { montar(); cargarGuardados(); }
    });

    window.GitHubLector = { abrir, estado, abrirRepo };
})();
