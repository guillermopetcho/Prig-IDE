/**
 * Desafíos: primero pensar, después programar.
 *
 * A la izquierda, de dónde sale el desafío: un chat con el modelo, el plan de estudios,
 * internet (Exercism, TheAlgorithms, Project Euler) o los desafíos ya empezados.
 *
 * A la derecha, la hoja, de arriba abajo:
 *   1. Desafío       título, fuente, nivel y enunciado
 *   2. Caja de razonamiento   cómo pensar el problema, paso a paso y sin código
 *   3. Tu plan       opcional: escribir cómo lo resolverías y que el tutor lo revise
 *   4. Páginas       una o varias; cada página es un archivo .py y se usan con import
 *   5. Comprobar     pruebas ocultas, pistas graduadas, solución, reflexión y siguiente
 *
 * El veredicto sale de EJECUTAR las pruebas en el backend, nunca de la opinión del modelo.
 */
(function () {
    const $ = (id) => document.getElementById(id);
    const esc = (t) => String(t ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
    const json = (url, opciones) => window.prigFetchJson(url, opciones);
    const enviar = (url, cuerpo, metodo = 'POST') => json(url, { method: metodo, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(cuerpo || {}) });
    const guardarLocal = (k, v) => { try { localStorage.setItem(k, v); } catch (e) { /* sin almacenamiento */ } };
    const leerLocal = (k) => { try { return localStorage.getItem(k); } catch (e) { return null; } };

    const FUENTES = {
        exercism: ['Exercism', 'fa-dumbbell', 'var(--accent-green)'],
        thealgorithms: ['TheAlgorithms', 'fa-diagram-project', 'var(--accent-blue)'],
        projecteuler: ['Project Euler', 'fa-square-root-variable', 'var(--accent-yellow)'],
        modelo: ['Modelo', 'fa-robot', 'var(--accent-purple)'],
        plan: ['Plan de estudios', 'fa-route', 'var(--accent-purple)'],
    };
    const ESTADOS = { nuevo: ['Nuevo', 'fa-circle', 'var(--text-muted)'], en_curso: ['En curso', 'fa-circle-half-stroke', 'var(--accent-blue)'],
        resuelto: ['Resuelto', 'fa-circle-check', 'var(--accent-green)'], rendido: ['Visto con solución', 'fa-flag', 'var(--accent-yellow)'] };
    const NIVELES = ['principiante', 'intermedio', 'avanzado'];

    const estado = {
        panel: 'chat', modelo: null, modelos: [],
        chat: [{ rol: 'tutor', texto: '¿Qué quieres practicar hoy? Cuéntame el tema (por ejemplo «recursividad», «diccionarios» o «una pila con clases») y tu nivel. Cuando lo tengas claro, crea el desafío o búscalo en internet.' }],
        chatNivel: 'intermedio',
        internet: { tema: '', nivel: '', fuentes: new Set(['exercism', 'thealgorithms', 'projecteuler']), datos: null, cargando: false, error: null },
        plan: { rutas: null, rutaId: null, ruta: null, bloqueDestacado: null },
        mis: null,
        d: null,               // desafío abierto (vista pública)
        paginas: [],           // trabajo actual del alumno
        editores: new Map(),   // nombre → editor Monaco
        pasosVisibles: 0,
        ultimo: null,          // última comprobación
        tarea: null,           // {titulo, lineas[], error} mientras el modelo crea
        chatDesafio: {},       // id → mensajes del tutor del desafío
        guardado: null,
        idioma: 'es',
        pedido: 0,
    };

    // ================================================================== utilidades
    function md(texto) {
        let html = window.marked ? window.marked.parse(String(texto || '')) : `<pre>${esc(texto)}</pre>`;
        if (window.DOMPurify) html = DOMPurify.sanitize(html, { USE_PROFILES: { html: true, svg: true, mathMl: true } });
        return html;
    }

    function pintarMd(el, texto) {
        el.innerHTML = md(texto);
        el.querySelectorAll('a[href]').forEach(a => { a.target = '_blank'; a.rel = 'noopener noreferrer'; });
        if (window.hljs) el.querySelectorAll('pre code').forEach(b => { try { hljs.highlightElement(b); } catch (e) { /* lenguaje raro */ } });
    }

    async function leerNdjson(res, alEvento) {
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
                else alEvento(ev);
            }
        }
        return fin;
    }

    const flujo = (url, cuerpo, alEvento) => fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(cuerpo || {}) })
        .then(res => leerNdjson(res, alEvento || (() => {})));

    const nombreModulo = (texto) => {
        let n = String(texto || '').trim().replace(/\.py$/i, '').replace(/[^A-Za-z0-9_]/g, '_');
        if (!/^[A-Za-z_]/.test(n)) n = 'pagina_' + n;
        return (n || 'pagina') + '.py';
    };

    // ================================================================== estilos
    function estilos() {
        if ($('des-estilos')) return;
        const css = document.createElement('style');
        css.id = 'des-estilos';
        css.textContent = `
          #desafios-raiz { display:grid; grid-template-columns: 340px 1fr; height:100%; min-height:0; background:var(--bg-dark); }
          .des-lado { border-right:1px solid var(--border-color); display:flex; flex-direction:column; min-height:0; background:var(--bg-panel); }
          .des-pestanas { display:flex; border-bottom:1px solid var(--border-color); }
          .des-pestanas button { flex:1; background:none; border:none; border-bottom:2px solid transparent; color:var(--text-muted); padding:9px 4px; cursor:pointer; font-size:11px; }
          .des-pestanas button.activa { color:var(--accent-blue); border-bottom-color:var(--accent-blue); }
          .des-modelo { display:flex; gap:6px; align-items:center; padding:6px 10px; border-bottom:1px solid var(--border-color); font-size:11px; color:var(--text-muted); }
          .des-modelo select { flex:1; min-width:0; }
          .des-lado-cuerpo { flex:1; min-height:0; overflow-y:auto; padding:10px; display:flex; flex-direction:column; gap:8px; }
          .des-campo { width:100%; background:var(--bg-dark); color:var(--text-main); border:1px solid var(--border-color); border-radius:6px; padding:6px 8px; font-size:12px; font-family:inherit; box-sizing:border-box; }
          textarea.des-campo { resize:vertical; }
          .des-btn { background:rgba(255,255,255,.05); color:var(--text-main); border:1px solid var(--border-color); border-radius:6px; padding:5px 10px; font-size:11.5px; cursor:pointer; white-space:nowrap; display:inline-flex; gap:6px; align-items:center; }
          .des-btn:hover:not(:disabled) { border-color:var(--accent-blue); }
          .des-btn:disabled { opacity:.5; cursor:default; }
          .des-btn.primario { background:var(--accent-green); border-color:var(--accent-green); color:#11111b; font-weight:600; }
          .des-btn.azul { background:rgba(137,180,250,.15); border-color:rgba(137,180,250,.45); color:var(--accent-blue); }
          .des-btn.amarillo { background:rgba(249,226,175,.12); border-color:rgba(249,226,175,.4); color:var(--accent-yellow); }
          .des-btn.rojo { background:rgba(243,139,168,.1); border-color:rgba(243,139,168,.35); color:var(--accent-red); }
          .des-btn.morado { background:rgba(203,166,247,.14); border-color:rgba(203,166,247,.45); color:var(--accent-purple); }
          .des-fila { display:flex; gap:6px; align-items:center; flex-wrap:wrap; }
          .des-ayuda { font-size:11px; color:var(--text-muted); line-height:1.45; }
          .des-error { font-size:12px; color:var(--accent-red); background:rgba(243,139,168,.08); border:1px solid rgba(243,139,168,.3); border-radius:6px; padding:8px 10px; white-space:pre-wrap; }
          .des-mini { font-size:10px; padding:1px 7px; border-radius:9px; background:rgba(255,255,255,.07); color:var(--text-muted); white-space:nowrap; }
          .des-msg { padding:7px 10px; border-radius:8px; font-size:12px; line-height:1.5; max-width:92%; }
          .des-msg.usuario { align-self:flex-end; background:rgba(137,180,250,.14); }
          .des-msg.tutor { align-self:flex-start; background:rgba(255,255,255,.05); }
          .des-msg p { margin:0 0 6px; } .des-msg p:last-child { margin:0; }
          .des-item { border:1px solid rgba(255,255,255,.07); border-radius:7px; padding:8px; background:rgba(0,0,0,.15); cursor:pointer; }
          .des-item:hover { border-color:rgba(137,180,250,.35); }
          .des-item.destacado { border-color:var(--accent-purple); box-shadow:0 0 0 1px var(--accent-purple) inset; }
          .des-item-titulo { font-weight:600; color:#fff; font-size:12px; }
          .des-hoja { overflow-y:auto; min-height:0; padding:18px 26px 60px; }
          .des-hoja-interior { max-width:980px; margin:0 auto; display:flex; flex-direction:column; gap:14px; }
          .des-seccion { background:var(--bg-panel); border:1px solid var(--border-color); border-radius:10px; padding:14px 16px; }
          .des-seccion-titulo { display:flex; gap:8px; align-items:center; font-size:11px; letter-spacing:.06em; text-transform:uppercase; color:var(--text-muted); margin-bottom:8px; }
          .des-seccion-titulo .des-mini, .des-seccion-titulo .des-btn, .des-seccion-titulo .des-ayuda { text-transform:none; letter-spacing:0; }
          .des-seccion-titulo .num { background:rgba(137,180,250,.18); color:var(--accent-blue); border-radius:50%; width:18px; height:18px; display:inline-flex; align-items:center; justify-content:center; font-size:10px; }
          .des-titulo { font-size:20px; font-weight:700; color:#fff; margin:2px 0 6px; }
          .des-md { font-size:13.5px; line-height:1.65; color:var(--text-main); }
          .des-md h1 { font-size:17px; margin:14px 0 6px; } .des-md h2 { font-size:15px; margin:12px 0 6px; } .des-md h3, .des-md h4 { font-size:13.5px; margin:10px 0 4px; }
          .des-md ul, .des-md ol { padding-left:22px; margin:6px 0; } .des-md p { margin:6px 0; }
          .des-md pre { background:rgba(0,0,0,.35); padding:8px 10px; border-radius:6px; overflow-x:auto; font-size:12px; }
          .des-md code { font-family:'Fira Code',monospace; font-size:12px; }
          .des-md blockquote { margin:8px 0; padding:4px 12px; border-left:3px solid var(--accent-yellow); color:var(--text-main); background:rgba(249,226,175,.05); }
          .des-md table { border-collapse:collapse; } .des-md td, .des-md th { border:1px solid var(--border-color); padding:3px 7px; }
          .des-caja-boton { width:100%; justify-content:center; padding:12px; font-size:14px; border-radius:9px; border:1px dashed rgba(203,166,247,.6); background:linear-gradient(90deg, rgba(203,166,247,.10), rgba(137,180,250,.08)); color:var(--accent-purple); font-weight:600; }
          .des-paso { border-left:3px solid var(--accent-purple); background:rgba(203,166,247,.05); border-radius:0 8px 8px 0; padding:10px 14px; margin-top:10px; }
          .des-paso-titulo { font-weight:700; color:var(--accent-purple); margin-bottom:4px; font-size:13px; }
          .des-pagina { border:1px solid var(--border-color); border-radius:9px; overflow:hidden; margin-top:10px; background:rgba(0,0,0,.18); }
          .des-pagina-cab { display:flex; gap:8px; align-items:center; padding:6px 10px; background:rgba(255,255,255,.03); border-bottom:1px solid var(--border-color); }
          .des-pagina-nombre { font-family:'Fira Code',monospace; color:#fff; font-size:12.5px; }
          .des-pagina-editor { min-height:120px; }
          .des-salida { border-top:1px solid var(--border-color); padding:8px 10px; font-family:'Fira Code',monospace; font-size:12px; white-space:pre-wrap; max-height:260px; overflow:auto; }
          .des-barra-prog { height:8px; border-radius:4px; background:rgba(255,255,255,.07); overflow:hidden; }
          .des-barra-prog > div { height:100%; background:var(--accent-green); transition:width .3s; }
          .des-fallo { border-left:3px solid var(--accent-red); background:rgba(243,139,168,.06); padding:6px 10px; margin-top:6px; border-radius:0 6px 6px 0; font-size:12px; }
          .des-fallo pre { margin:4px 0 0; white-space:pre-wrap; font-size:11.5px; color:var(--text-main); }
          .des-exito { border:1px solid var(--accent-green); background:rgba(166,227,161,.08); border-radius:9px; padding:12px 14px; }
          .des-vacio { max-width:620px; margin:40px auto; text-align:center; color:var(--text-muted); }
          .des-vacio h2 { color:#fff; font-size:22px; margin:10px 0 6px; }
          .des-orden { display:grid; grid-template-columns:repeat(5,1fr); gap:6px; margin:18px 0; font-size:11px; }
          .des-orden div { background:var(--bg-panel); border:1px solid var(--border-color); border-radius:8px; padding:8px 4px; }
          .des-orden i { display:block; font-size:16px; margin-bottom:4px; color:var(--accent-blue); }
        `;
        document.head.appendChild(css);
    }

    // ================================================================== estructura
    function raiz() { return $('desafios-raiz'); }

    function montar() {
        estilos();
        const r = raiz();
        if (!r || $('des-lado')) return;
        r.innerHTML = `
          <aside class="des-lado" id="des-lado">
            <div class="des-pestanas" id="des-pestanas">
              ${[['chat', 'fa-comments', 'Chat'], ['plan', 'fa-route', 'Plan'], ['internet', 'fa-globe', 'Internet'], ['mis', 'fa-list-check', 'Mis desafíos']]
                .map(([id, ic, t]) => `<button data-panel="${id}"><i class="fa-solid ${ic}"></i><br>${t}</button>`).join('')}
            </div>
            <div class="des-modelo"><i class="fa-solid fa-microchip"></i> Modelo <select id="des-modelo" class="des-campo"></select>
              <span class="des-mini" id="des-modelo-nube" hidden title="Este modelo funciona en los servidores de Google" style="color:var(--accent-yellow);"><i class="fa-solid fa-cloud"></i> nube</span></div>
            <div class="des-lado-cuerpo" id="des-lado-cuerpo"></div>
          </aside>
          <main class="des-hoja" id="des-hoja"><div class="des-hoja-interior" id="des-hoja-interior"></div></main>`;
        $('des-pestanas').onclick = (e) => { const b = e.target.closest('button'); if (b) cambiarPanel(b.dataset.panel); };
        $('des-modelo').onchange = (e) => {
            if (e.target.value === '__gemini__') { e.target.value = estado.modelo; return dialogoGemini(); }
            estado.modelo = e.target.value;
            guardarLocal('prig_desafios_modelo', estado.modelo);
            marcarNube();
        };
        cargarModelos();
        cambiarPanel(estado.panel);
        pintarHoja();
    }

    async function cargarModelos(preferir) {
        const sel = $('des-modelo');
        try {
            const d = await json('/api/modelos');
            estado.modelos = d.modelos.filter(m => !m.capacidades.includes('embedding')).map(m => m.nombre);
        } catch (e) { estado.modelos = []; }
        estado.gemini = { estado: null, modelos: [], error: null };
        try {
            estado.gemini.estado = await json('/api/gemini/estado');
            if (estado.gemini.estado.configurado) estado.gemini.modelos = (await json('/api/gemini/modelos')).modelos;
        } catch (e) { estado.gemini.error = e.message; }
        const nube = estado.gemini.modelos.map(m => `gemini:${m.id}`);
        const todos = [...estado.modelos, ...nube];
        const preferido = preferir || (window.PrigModelos && window.PrigModelos.para('codigo')) || leerLocal('prig_desafios_modelo') || (window.aiConfig && window.aiConfig.agent1_model) || todos[0] || '';
        estado.modelo = todos.includes(preferido) ? preferido : (estado.modelos[0] || nube[0] || preferido);
        if (!sel) return;
        const opcion = (valor, texto) => `<option style="background-color:#1e1e2e; color:#cdd6f4;" value="${esc(valor)}" ${valor === estado.modelo ? 'selected' : ''}>${esc(texto)}</option>`;
        const g = estado.gemini;
        sel.innerHTML = `
          <optgroup label="En tu equipo (Ollama)" style="background-color:#181825; color:#89b4fa;">${(estado.modelos.length ? estado.modelos : [estado.modelo].filter(m => m && !m.startsWith('gemini:'))).map(m => opcion(m, m)).join('')}</optgroup>
          ${g.modelos.length ? `<optgroup label="Google Gemini · nube" style="background-color:#181825; color:#89b4fa;">${g.modelos.map(m => opcion(`gemini:${m.id}`, `${m.nombre} (Gemini)`)).join('')}</optgroup>` : ''}
          <optgroup label="Google Gemini" style="background-color:#181825; color:#89b4fa;">${opcion('__gemini__', g.estado && g.estado.configurado
            ? (g.error ? `⚠ Gemini: ${g.error.slice(0, 60)}` : 'Gestionar la conexión con Gemini…') : 'Conectar Google Gemini…')}</optgroup>`;
        guardarLocal('prig_desafios_modelo', estado.modelo);
        marcarNube();
    }

    function marcarNube() {
        const marca = $('des-modelo-nube');
        if (marca) marca.hidden = !String(estado.modelo || '').startsWith('gemini:');
    }

    // ================================================================== conectar Google Gemini
    async function dialogoGemini() {
        let e;
        try { e = await json('/api/gemini/estado'); } catch (err) { return alert(err.message); }
        const previo = $('des-gemini');
        if (previo) previo.remove();
        const capa = document.createElement('div');
        capa.id = 'des-gemini';
        capa.style.cssText = 'position:fixed; inset:0; background:rgba(0,0,0,.55); z-index:10050; display:flex; align-items:center; justify-content:center;';
        capa.innerHTML = `
          <div class="des-seccion" style="width:560px; max-width:94vw; max-height:90vh; overflow:auto;">
            <div class="des-fila" style="margin-bottom:8px;"><i class="fa-brands fa-google" style="color:var(--accent-blue); font-size:18px;"></i>
              <b style="font-size:15px; color:#fff; flex:1;">Google Gemini para los desafíos</b>
              <button class="des-btn" data-cerrar><i class="fa-solid fa-xmark"></i></button></div>
            ${e.configurado ? `
              <div class="des-exito" style="padding:8px 12px;"><i class="fa-solid fa-circle-check" style="color:var(--accent-green);"></i>
                Conectado con la clave <code>${esc(e.clave)}</code> ${e.origen === 'entorno' ? '(de la variable GEMINI_API_KEY)' : ''}
                ${e.aviso_aceptado ? `<div class="des-ayuda">Aviso de privacidad aceptado el ${esc(e.aviso_aceptado.replace('T', ' '))}</div>` : ''}</div>
              <div class="des-ayuda" style="margin:8px 0;">${esc(e.aviso)}</div>
              <div class="des-fila">${e.origen === 'prig' ? '<button class="des-btn rojo" data-desconectar><i class="fa-solid fa-link-slash"></i> Desconectar y borrar la clave</button>' : ''}
                <span style="flex:1"></span><button class="des-btn" data-cerrar>Cerrar</button></div>`
            : `
              <p class="des-ayuda" style="font-size:12px;">Gemini se conecta con una <b>clave de API gratuita</b> que creas entrando con tu cuenta de Google en Google AI Studio.
                Prig no usa la sesión de Gemini CLI o Antigravity que ya tienes: las condiciones de Google no permiten usarla desde otros programas.</p>
              <div class="des-paso" style="margin-top:6px;"><div class="des-paso-titulo">1. Crea tu clave</div>
                <div class="des-ayuda">Entra con tu cuenta de Google, pulsa «Create API key» y cópiala.</div>
                <a class="des-btn azul" style="margin-top:6px; text-decoration:none;" href="${esc(e.url_claves)}" target="_blank" rel="noopener noreferrer"><i class="fa-solid fa-arrow-up-right-from-square"></i> Abrir Google AI Studio</a></div>
              <div class="des-paso"><div class="des-paso-titulo">2. Pégala aquí</div>
                <div class="des-fila"><input id="des-gemini-clave" class="des-campo" type="password" autocomplete="off" spellcheck="false" placeholder="AQ.… (o AIza… si es una clave antigua)" style="flex:1; font-family:'Fira Code',monospace;">
                  <button class="des-btn" data-ver title="Mostrar u ocultar"><i class="fa-solid fa-eye"></i></button></div>
                <div class="des-ayuda">Se guarda solo en tu equipo (~/.prig_gemini.json, legible solo por tu usuario) y nunca vuelve a mostrarse entera.</div></div>
              <div class="des-paso" style="border-left-color:var(--accent-yellow);"><div class="des-paso-titulo" style="color:var(--accent-yellow);">3. Qué se envía a Google</div>
                <div class="des-ayuda" style="color:var(--text-main);">${esc(e.aviso)}</div>
                <div class="des-ayuda" style="margin-top:4px;">El nivel gratuito tiene límites por minuto y por día; si se agotan, Prig te lo dice y puedes seguir con un modelo local. Los modelos locales no envían nada fuera de tu equipo.</div>
                <label class="des-fila" style="margin-top:6px; font-size:12px; cursor:pointer;"><input type="checkbox" id="des-gemini-acepto"> Entiendo qué se envía a Google y lo acepto</label></div>
              <div id="des-gemini-error"></div>
              <div class="des-fila" style="margin-top:10px;"><span style="flex:1"></span><button class="des-btn" data-cerrar>Cancelar</button>
                <button class="des-btn primario" data-conectar><i class="fa-solid fa-plug"></i> Comprobar y conectar</button></div>`}
          </div>`;
        document.body.appendChild(capa);
        const cerrar = () => capa.remove();
        capa.addEventListener('click', (ev) => { if (ev.target === capa) cerrar(); });
        capa.querySelectorAll('[data-cerrar]').forEach(b => b.onclick = cerrar);
        const ver = capa.querySelector('[data-ver]');
        if (ver) ver.onclick = () => { const c = $('des-gemini-clave'); c.type = c.type === 'password' ? 'text' : 'password'; };
        const desconectar = capa.querySelector('[data-desconectar]');
        if (desconectar) desconectar.onclick = async () => {
            if (!confirm('¿Desconectar Gemini y borrar la clave de este equipo?')) return;
            await fetch('/api/gemini/clave', { method: 'DELETE' });
            cerrar();
            await cargarModelos(estado.modelos[0]);
        };
        const conectar = capa.querySelector('[data-conectar]');
        if (conectar) {
            const campo = $('des-gemini-clave');
            setTimeout(() => campo.focus(), 30);
            conectar.onclick = async () => {
                const error = $('des-gemini-error');
                error.innerHTML = '';
                if (!$('des-gemini-acepto').checked) { error.innerHTML = '<div class="des-error" style="margin-top:8px;">Marca que entiendes qué se envía a Google para continuar.</div>'; return; }
                conectar.disabled = true;
                conectar.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Comprobando con Google…';
                try {
                    const r = await enviar('/api/gemini/clave', { clave: campo.value, acepto_aviso: true });
                    campo.value = '';
                    cerrar();
                    const primero = (r.modelos || [])[0];
                    await cargarModelos(primero ? `gemini:${primero.id}` : null);
                } catch (err) {
                    error.innerHTML = `<div class="des-error" style="margin-top:8px;">${esc(err.message)}</div>`;
                    conectar.disabled = false;
                    conectar.innerHTML = '<i class="fa-solid fa-plug"></i> Comprobar y conectar';
                }
            };
            campo.onkeydown = (ev) => { if (ev.key === 'Enter') conectar.click(); };
        }
    }

    function cambiarPanel(p) {
        estado.panel = p;
        document.querySelectorAll('#des-pestanas button').forEach(b => b.classList.toggle('activa', b.dataset.panel === p));
        ({ chat: panelChat, plan: panelPlan, internet: panelInternet, mis: panelMis }[p] || panelChat)();
    }

    // ================================================================== panel: chat
    function panelChat() {
        const c = $('des-lado-cuerpo');
        c.innerHTML = `
          <div id="des-chat-msgs" style="display:flex; flex-direction:column; gap:6px; flex:1;"></div>
          <textarea id="des-chat-texto" class="des-campo" rows="3" placeholder="Escribe al entrenador… (Enter envía, Mayús+Enter salto de línea)"></textarea>
          <div class="des-fila"><button class="des-btn azul" id="des-chat-enviar"><i class="fa-solid fa-paper-plane"></i> Enviar</button>
            <span style="flex:1"></span>
            <select id="des-chat-nivel" class="des-campo" style="width:auto;">${NIVELES.map(n => `<option ${n === estado.chatNivel ? 'selected' : ''}>${n}</option>`).join('')}</select></div>
          <div class="des-fila">
            <button class="des-btn primario" id="des-chat-crear" style="flex:1;"><i class="fa-solid fa-wand-magic-sparkles"></i> Crear desafío</button>
            <button class="des-btn" id="des-chat-internet" style="flex:1;"><i class="fa-solid fa-globe"></i> Buscar en internet</button>
          </div>
          <div class="des-ayuda">«Crear desafío» usa toda la conversación. El desafío solo aparece si su solución pasa las pruebas ejecutándolas.</div>`;
        pintarChat();
        const texto = $('des-chat-texto');
        texto.onkeydown = (e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); enviarChat(); } };
        $('des-chat-enviar').onclick = enviarChat;
        $('des-chat-nivel').onchange = (e) => { estado.chatNivel = e.target.value; };
        $('des-chat-crear').onclick = () => {
            const usuario = estado.chat.filter(m => m.rol === 'usuario');
            if (!usuario.length && !texto.value.trim()) { texto.focus(); texto.placeholder = 'Primero cuéntame qué quieres practicar'; return; }
            if (texto.value.trim()) estado.chat.push({ rol: 'usuario', texto: texto.value.trim() });
            crearConModelo({ tema: usuario.length ? '' : texto.value.trim(), nivel: estado.chatNivel, conversacion: estado.chat.slice(1) });
        };
        $('des-chat-internet').onclick = () => {
            const tema = texto.value.trim() || estado.chat.filter(m => m.rol === 'usuario').map(m => m.texto).join(' ');
            if (!tema) { texto.focus(); return; }
            estado.internet.tema = tema.slice(0, 200);
            cambiarPanel('internet');
            buscarInternet();
        };
    }

    function pintarChat() {
        const c = $('des-chat-msgs');
        if (!c) return;
        c.innerHTML = estado.chat.map((m, i) => `<div class="des-msg ${m.rol}" data-i="${i}"></div>`).join('');
        c.querySelectorAll('.des-msg').forEach(el => pintarMd(el, estado.chat[+el.dataset.i].texto || '…'));
        const cuerpo = $('des-lado-cuerpo');
        if (cuerpo) cuerpo.scrollTop = cuerpo.scrollHeight;
    }

    async function enviarChat() {
        const texto = $('des-chat-texto');
        const t = texto.value.trim();
        if (!t) return;
        texto.value = '';
        estado.chat.push({ rol: 'usuario', texto: t });
        const respuesta = { rol: 'tutor', texto: '' };
        estado.chat.push(respuesta);
        pintarChat();
        const burbuja = () => document.querySelector(`#des-chat-msgs .des-msg[data-i="${estado.chat.indexOf(respuesta)}"]`);
        try {
            await flujo('/api/desafios/chat', { mensajes: estado.chat.slice(1, -1), modelo: estado.modelo }, (ev) => {
                if (ev.tipo === 'texto') { respuesta.texto += ev.delta; const b = burbuja(); if (b) pintarMd(b, respuesta.texto); }
                else if (ev.tipo === 'pensando' && !respuesta.texto) { const b = burbuja(); if (b) b.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> pensando…'; }
            });
        } catch (e) {
            respuesta.texto = `*No pude responder: ${e.message}*`;
        }
        pintarChat();
    }

    // ================================================================== panel: plan de estudios
    async function panelPlan() {
        const c = $('des-lado-cuerpo');
        c.innerHTML = '<div class="des-ayuda"><i class="fa-solid fa-spinner fa-spin"></i> Cargando tus rutas…</div>';
        try {
            if (!estado.plan.rutas) estado.plan.rutas = (await json('/api/guided/list')).paths || [];
            if (!estado.plan.rutaId && estado.plan.rutas.length) estado.plan.rutaId = leerLocal('prig_plan_actual') || estado.plan.rutas[0].id;
            if (estado.plan.rutaId && (!estado.plan.ruta || estado.plan.ruta.id !== estado.plan.rutaId)) {
                estado.plan.ruta = await json(`/api/guided/${encodeURIComponent(estado.plan.rutaId)}`);
            }
        } catch (e) {
            c.innerHTML = `<div class="des-error">${esc(e.message)}</div>`;
            return;
        }
        if (estado.panel !== 'plan') return;
        if (!estado.plan.rutas.length) {
            c.innerHTML = `<div class="des-ayuda">Todavía no tienes un plan de estudios.</div>
              <button class="des-btn azul" id="des-ir-guiado"><i class="fa-solid fa-route"></i> Crear uno en Aprendizaje Guiado</button>`;
            $('des-ir-guiado').onclick = () => window.PrigCommands && window.PrigCommands.ejecutar('herr.guiado');
            return;
        }
        const ruta = estado.plan.ruta;
        const hechos = new Set(ruta.completed_blocks || []);
        c.innerHTML = `
          <select id="des-ruta" class="des-campo">${estado.plan.rutas.map(r => `<option value="${esc(r.id)}" ${r.id === estado.plan.rutaId ? 'selected' : ''}>${esc(r.goal)}</option>`).join('')}</select>
          <div class="des-ayuda">Elige un bloque: el modelo crea un desafío con sus temas y su objetivo, o se buscan desafíos de internet sobre esos temas.</div>
          ${ruta.blocks.map((b, i) => `
            <div class="des-item ${b.block_id === estado.plan.bloqueDestacado ? 'destacado' : ''}" data-bloque="${esc(b.block_id)}">
              <div class="des-fila"><span class="des-mini">${i + 1}</span><span class="des-item-titulo" style="flex:1;">${esc(b.title)}</span>
                ${hechos.has(b.block_id) ? '<i class="fa-solid fa-circle-check" style="color:var(--accent-green);" title="Bloque completado"></i>' : ''}</div>
              <div class="des-ayuda" style="margin:4px 0;">${esc((b.topics || []).join(' · '))}</div>
              <div class="des-fila">
                <button class="des-btn primario" data-crear><i class="fa-solid fa-wand-magic-sparkles"></i> Crear desafío</button>
                <button class="des-btn" data-internet><i class="fa-solid fa-globe"></i> Internet</button>
              </div>
            </div>`).join('')}`;
        $('des-ruta').onchange = (e) => { estado.plan.rutaId = e.target.value; estado.plan.bloqueDestacado = null; panelPlan(); };
        c.querySelectorAll('[data-bloque]').forEach(el => {
            const bloque = ruta.blocks.find(b => b.block_id === el.dataset.bloque);
            el.querySelector('[data-crear]').onclick = () => crearConModelo({ ruta_id: ruta.id, bloque_id: bloque.block_id, nivel: nivelDeRuta(ruta) });
            el.querySelector('[data-internet]').onclick = () => {
                estado.internet.tema = [bloque.title, ...(bloque.topics || [])].join(', ');
                estado.internet.bloque = { ruta_id: ruta.id, bloque_id: bloque.block_id };
                cambiarPanel('internet');
                buscarInternet();
            };
        });
        const destacado = c.querySelector('.des-item.destacado');
        if (destacado) destacado.scrollIntoView({ block: 'center' });
    }

    const nivelDeRuta = (ruta) => {
        const n = String(ruta.level || '').toLowerCase();
        return n.startsWith('princ') || n.startsWith('básic') || n.startsWith('basic') ? 'principiante' : n.startsWith('avanz') ? 'avanzado' : 'intermedio';
    };

    // ================================================================== panel: internet
    function panelInternet() {
        const c = $('des-lado-cuerpo');
        const i = estado.internet;
        c.innerHTML = `
          <input id="des-int-tema" class="des-campo" placeholder="Tema: recursividad, búsqueda binaria, clases…" value="${esc(i.tema)}">
          <div class="des-fila">
            <select id="des-int-nivel" class="des-campo" style="width:auto;"><option value="">Cualquier nivel</option>${NIVELES.map(n => `<option ${n === i.nivel ? 'selected' : ''}>${n}</option>`).join('')}</select>
            <button class="des-btn azul" id="des-int-buscar" style="flex:1;"><i class="fa-solid fa-magnifying-glass"></i> Buscar</button>
          </div>
          <div class="des-fila">${Object.entries(FUENTES).filter(([k]) => ['exercism', 'thealgorithms', 'projecteuler'].includes(k))
            .map(([k, [n, ic, col]]) => `<label class="des-mini" style="cursor:pointer; ${i.fuentes.has(k) ? `color:${col};` : ''}"><input type="checkbox" data-fuente="${k}" ${i.fuentes.has(k) ? 'checked' : ''} style="vertical-align:middle;"> ${n}</label>`).join('')}</div>
          <div class="des-ayuda">Solo fuentes cuya licencia permite copiar: Exercism y TheAlgorithms (MIT, con pruebas) y Project Euler (CC BY-NC-SA, sin respuestas publicadas).</div>
          <div id="des-int-res"></div>`;
        $('des-int-tema').onkeydown = (e) => { if (e.key === 'Enter') { i.bloque = null; buscarInternet(); } };
        $('des-int-buscar').onclick = () => { i.bloque = null; buscarInternet(); };
        $('des-int-nivel').onchange = (e) => { i.nivel = e.target.value; };
        c.querySelectorAll('[data-fuente]').forEach(ch => ch.onchange = () => {
            if (ch.checked) i.fuentes.add(ch.dataset.fuente); else i.fuentes.delete(ch.dataset.fuente);
        });
        pintarResultadosInternet();
    }

    async function buscarInternet(ayudaModelo = false) {
        const i = estado.internet;
        const campo = $('des-int-tema');
        if (campo) i.tema = campo.value.trim() || i.tema;
        if (!i.tema) { if (campo) campo.focus(); return; }
        i.cargando = true; i.error = null;
        pintarResultadosInternet();
        const q = new URLSearchParams({ tema: i.tema, fuentes: [...i.fuentes].join(',') });
        if (i.nivel) q.set('nivel', i.nivel);
        if (ayudaModelo) { q.set('ayuda_modelo', 'true'); q.set('modelo', estado.modelo || ''); }
        try { i.datos = await json(`/api/desafios/internet/buscar?${q}`); } catch (e) { i.error = e.message; }
        i.cargando = false;
        pintarResultadosInternet();
    }

    function pintarResultadosInternet() {
        const c = $('des-int-res');
        if (!c) return;
        const i = estado.internet;
        if (i.cargando) { c.innerHTML = '<div class="des-ayuda"><i class="fa-solid fa-spinner fa-spin"></i> Buscando…</div>'; return; }
        if (i.error) { c.innerHTML = `<div class="des-error">${esc(i.error)}</div>`; return; }
        if (!i.datos) { c.innerHTML = ''; return; }
        const r = i.datos.resultados;
        const errores = Object.entries(i.datos.errores || {});
        c.innerHTML = `
          ${i.datos.terminos_del_modelo ? `<div class="des-ayuda">El modelo sugirió buscar: ${esc(i.datos.terminos_del_modelo.join(', '))}</div>` : ''}
          ${!r.length ? `<div class="des-ayuda" style="margin:6px 0;">No encontré desafíos sobre «${esc(i.tema)}».</div>
            <button class="des-btn morado" id="des-int-ayuda"><i class="fa-solid fa-robot"></i> Pedir al modelo términos de búsqueda</button>` : ''}
          ${r.map((x, n) => {
              const [nombre, ic, col] = FUENTES[x.fuente];
              return `<div class="des-item" data-n="${n}" style="margin-top:6px;">
                <div class="des-fila"><span class="des-mini" style="color:${col};"><i class="fa-solid ${ic}"></i> ${nombre}</span>
                  <span class="des-mini">${esc(x.nivel)}</span>
                  ${x.verificable ? '<span class="des-mini" style="color:var(--accent-green);" title="Se comprueba ejecutando pruebas">con pruebas</span>' : '<span class="des-mini" title="Sin comprobación automática">sin pruebas</span>'}</div>
                <div class="des-item-titulo" style="margin-top:4px;">${esc(x.titulo)}</div>
                <div class="des-ayuda">${esc(x.tipo || '')}${x.etiquetas && x.etiquetas.length ? ' · ' + esc(x.etiquetas.slice(0, 3).join(', ')) : ''}</div>
              </div>`;
          }).join('')}
          ${errores.length ? `<div class="des-ayuda" style="color:var(--accent-red);">No respondió: ${errores.map(([f, e]) => `${FUENTES[f][0]} (${esc(e)})`).join(', ')}</div>` : ''}`;
        const ayuda = $('des-int-ayuda');
        if (ayuda) ayuda.onclick = () => buscarInternet(true);
        c.querySelectorAll('[data-n]').forEach(el => el.onclick = () => importar(r[+el.dataset.n]));
    }

    async function importar(x, funcion) {
        const i = estado.internet;
        mostrarTarea(`Trayendo «${x.titulo}» de ${FUENTES[x.fuente][0]}`, [x.verificable
            ? 'Se descarga el enunciado, el código de partida y las pruebas, y se comprueba ejecutándolos que funcionan en tu equipo…'
            : 'Se descarga el enunciado…']);
        try {
            const d = await enviar('/api/desafios/internet/importar', { fuente: x.fuente, ref: x.ref, funcion, tema: i.tema, ...(i.bloque || {}) });
            abrirDesafio(d);
        } catch (e) {
            estado.tarea.error = e.message;
            pintarHoja();
        }
    }

    // ================================================================== panel: mis desafíos
    async function panelMis() {
        const c = $('des-lado-cuerpo');
        c.innerHTML = '<div class="des-ayuda"><i class="fa-solid fa-spinner fa-spin"></i> Cargando…</div>';
        try { estado.mis = (await json('/api/desafios')).desafios; } catch (e) { c.innerHTML = `<div class="des-error">${esc(e.message)}</div>`; return; }
        if (estado.panel !== 'mis') return;
        if (!estado.mis.length) { c.innerHTML = '<div class="des-ayuda">Aún no empezaste ningún desafío.</div>'; return; }
        const resueltos = estado.mis.filter(x => x.estado === 'resuelto').length;
        c.innerHTML = `<div class="des-fila"><span class="des-ayuda" style="flex:1;">${estado.mis.length} desafíos · ${resueltos} resueltos</span>
            <button class="des-btn" id="des-ver-perfil" title="Historial completo, dominio por concepto y análisis del tutor"><i class="fa-solid fa-chart-line"></i> Mi avance</button></div>`
          + estado.mis.map(x => {
            const [en, ie, ce] = ESTADOS[x.estado] || ESTADOS.nuevo;
            const [fn, fi, fc] = FUENTES[x.origen.tipo] || FUENTES.modelo;
            return `<div class="des-item ${estado.d && estado.d.id === x.id ? 'destacado' : ''}" data-id="${esc(x.id)}">
              <div class="des-fila"><i class="fa-solid ${ie}" style="color:${ce};" title="${en}"></i><span class="des-item-titulo" style="flex:1;">${esc(x.titulo)}</span>
                <button class="des-btn rojo" data-borrar title="Borrar" style="padding:2px 6px;"><i class="fa-solid fa-trash"></i></button></div>
              <div class="des-ayuda"><i class="fa-solid ${fi}" style="color:${fc};"></i> ${fn} · ${esc(x.nivel || '')} · ${x.verificable ? `${x.mejor ? x.mejor.pasados : 0}/${x.mejor ? x.mejor.total : '?'} pruebas` : 'sin pruebas'} · ${x.intentos} intentos${x.pistas ? ` · ${x.pistas} pistas` : ''}</div>
            </div>`;
        }).join('');
        $('des-ver-perfil').onclick = () => window.PrigCommands && window.PrigCommands.ejecutar('herr.perfil');
        c.querySelectorAll('[data-id]').forEach(el => {
            el.onclick = (e) => { if (!e.target.closest('[data-borrar]')) abrirPorId(el.dataset.id); };
            el.querySelector('[data-borrar]').onclick = async () => {
                if (!confirm('¿Borrar este desafío y tu trabajo en él?')) return;
                await fetch(`/api/desafios/${el.dataset.id}`, { method: 'DELETE' });
                if (estado.d && estado.d.id === el.dataset.id) { cerrarDesafio(); }
                panelMis();
            };
        });
    }

    // ================================================================== crear con el modelo
    async function crearConModelo(cuerpo) {
        const tema = cuerpo.tema || (cuerpo.bloque_id ? 'el bloque del plan' : cuerpo.basado_en ? 'el siguiente desafío' : 'lo hablado en el chat');
        mostrarTarea(`Creando un desafío sobre ${tema}`, ['El modelo escribe el enunciado, el código de partida, la solución y las pruebas. Después se ejecutan: solo llega a ti si la solución pasa y el código de partida no.']);
        const pedido = ++estado.pedido;
        try {
            const d = await flujo('/api/desafios/crear', { ...cuerpo, modelo: estado.modelo }, (ev) => {
                if (ev.tipo === 'progreso' && estado.tarea && pedido === estado.pedido) { estado.tarea.lineas.push(ev.mensaje); pintarHoja(); }
            });
            if (pedido !== estado.pedido) return;
            abrirDesafio(d);
            if (estado.panel === 'mis') panelMis();
        } catch (e) {
            if (pedido !== estado.pedido || !estado.tarea) return;
            estado.tarea.error = e.message;
            pintarHoja();
        }
    }

    function mostrarTarea(titulo, lineas) {
        guardarAhora();
        destruirEditores();
        estado.d = null;
        estado.tarea = { titulo, lineas: [...lineas], error: null };
        pintarHoja();
    }

    // ================================================================== abrir / cerrar
    async function abrirPorId(id, silencioso = false) {
        try { abrirDesafio(await json(`/api/desafios/${encodeURIComponent(id)}`)); }
        catch (e) {
            if (silencioso) guardarLocal('prig_desafio_abierto', '');
            else alert(e.message);
        }
    }

    function abrirDesafio(d) {
        guardarAhora();
        destruirEditores();
        estado.tarea = null;
        estado.d = d;
        estado.ultimo = d.ultima_comprobacion || null;
        estado.paginas = JSON.parse(JSON.stringify(d.paginas_usuario && d.paginas_usuario.length ? d.paginas_usuario : d.paginas));
        estado.pasosVisibles = Math.max(d.razonamiento ? 1 : 0, (d.progreso || {}).pasos_vistos || 0);
        estado.idioma = d.enunciado_es ? 'es' : (d.idioma || 'es');
        estado.solucion = null;
        guardarLocal('prig_desafio_abierto', d.id);
        pintarHoja();
        const hoja = $('des-hoja');
        if (hoja) hoja.scrollTop = 0;
    }

    function cerrarDesafio() {
        destruirEditores();
        estado.d = null;
        estado.tarea = null;
        guardarLocal('prig_desafio_abierto', '');
        pintarHoja();
    }

    // ================================================================== hoja
    function pintarHoja() {
        const c = $('des-hoja-interior');
        if (!c) return;
        if (estado.tarea) return pintarTarea(c);
        if (!estado.d) return pintarVacio(c);
        destruirEditores();
        const d = estado.d;
        const p = d.progreso || {};
        const [fn, fi, fc] = FUENTES[(d.origen || {}).tipo] || FUENTES.modelo;
        const [en, ie, ce] = ESTADOS[p.estado] || ESTADOS.nuevo;
        const original = d.idioma && d.idioma !== 'es';
        c.innerHTML = `
          <section class="des-seccion" id="des-sec-desafio">
            <div class="des-seccion-titulo"><span class="num">1</span> Desafío <span style="flex:1"></span>
              <span class="des-mini" style="color:${ce};"><i class="fa-solid ${ie}"></i> ${en}</span></div>
            <div class="des-fila">
              <span class="des-mini" style="color:${fc};"><i class="fa-solid ${fi}"></i> ${esc((d.origen || {}).nombre || fn)}</span>
              <span class="des-mini">${esc(d.nivel || '')}</span>
              ${(d.conceptos || []).slice(0, 5).map(x => `<span class="des-mini">${esc(x)}</span>`).join('')}
              <span style="flex:1"></span>
              ${original ? `<button class="des-btn" id="des-traducir">${d.enunciado_es && estado.idioma === 'es' ? '<i class="fa-solid fa-language"></i> Ver original' : '<i class="fa-solid fa-language"></i> Traducir al español'}</button>` : ''}
              ${(d.origen || {}).otras_funciones && d.origen.otras_funciones.length ? `<select id="des-otra-funcion" class="des-campo" style="width:auto;" title="Otra función del mismo archivo"><option value="">Otra función…</option>${d.origen.otras_funciones.map(f => `<option>${esc(f)}</option>`).join('')}</select>` : ''}
            </div>
            <div class="des-titulo">${esc(d.titulo)}</div>
            ${(d.origen || {}).bloque ? `<div class="des-ayuda"><i class="fa-solid fa-route"></i> Bloque «${esc(d.origen.bloque)}» de tu plan</div>` : ''}
            ${d.teoria ? `<details style="margin:8px 0;"><summary class="des-ayuda" style="cursor:pointer;"><i class="fa-solid fa-book-open"></i> Teoría del concepto</summary><div class="des-md" id="des-teoria"></div></details>` : ''}
            <div class="des-md" id="des-enunciado"></div>
            ${d.origen && d.origen.atribucion ? `<div class="des-ayuda" style="margin-top:10px; border-top:1px dashed var(--border-color); padding-top:6px;">
              <i class="fa-solid fa-scale-balanced"></i> ${esc(d.origen.atribucion)} ${d.origen.url ? `<a href="${esc(d.origen.url)}" target="_blank" rel="noopener noreferrer">Ver original</a>` : ''}
              ${d.origen.nota ? `<div style="margin-top:4px; color:var(--accent-yellow);"><i class="fa-solid fa-circle-info"></i> ${esc(d.origen.nota)}</div>` : ''}</div>` : ''}
          </section>

          <section class="des-seccion" id="des-sec-razonamiento">
            <div class="des-seccion-titulo"><span class="num">2</span> Razonar antes de programar</div>
            <div id="des-razonamiento"></div>
          </section>

          <section class="des-seccion" id="des-sec-plan">
            <details ${p.plan ? 'open' : ''}><summary class="des-seccion-titulo" style="cursor:pointer; margin:0;"><span class="num">3</span> Tu plan <span class="des-ayuda" style="text-transform:none; letter-spacing:0;">(opcional) escribe con tus palabras cómo lo resolverías</span></summary>
              <textarea id="des-plan" class="des-campo" rows="4" style="margin-top:8px;" placeholder="1. Recorro la lista…&#10;2. Si encuentro…&#10;3. Al final devuelvo…">${esc(p.plan || '')}</textarea>
              <div class="des-fila" style="margin-top:6px;"><button class="des-btn morado" id="des-plan-revisar"><i class="fa-solid fa-user-graduate"></i> Revisar mi plan con el tutor</button></div>
              <div class="des-md" id="des-plan-respuesta" style="margin-top:8px;"></div>
            </details>
          </section>

          <section class="des-seccion" id="des-sec-paginas">
            <div class="des-seccion-titulo"><span class="num">4</span> Páginas de código <span style="flex:1"></span>
              <button class="des-btn" id="des-pagina-nueva"><i class="fa-solid fa-file-circle-plus"></i> Nueva página</button>
              <button class="des-btn" id="des-pagina-importar"><i class="fa-solid fa-file-import"></i> Importar archivo .py</button>
              <input type="file" id="des-pagina-archivo" accept=".py,text/x-python" multiple hidden></div>
            <div class="des-ayuda">Cada página es un archivo de Python. Desde una página se usa otra con <code>import</code>:
              ${estado.paginas.length > 1 ? `por ejemplo <code>from ${esc(estado.paginas[0].nombre.replace(/\.py$/, ''))} import …</code>` : 'si creas <code>utiles.py</code>, en otra página escribe <code>from utiles import …</code>'}.
              <b>Mayús+Enter</b> ejecuta la página · <b>Ctrl+Enter</b> comprueba · se guarda solo <span id="des-guardado"></span></div>
            <div id="des-paginas"></div>
          </section>

          <section class="des-seccion" id="des-sec-comprobar">
            <div class="des-seccion-titulo"><span class="num">5</span> Comprobar</div>
            <div class="des-fila">
              ${d.comprobacion && d.comprobacion.tipo !== 'ninguna'
                ? `<button class="des-btn primario" id="des-comprobar"><i class="fa-solid fa-circle-check"></i> Comprobar con ${d.comprobacion.pruebas || ''} pruebas</button>`
                : '<span class="des-ayuda"><i class="fa-solid fa-circle-info"></i> Este desafío no tiene pruebas automáticas: ejecuta tu página y compara el resultado.</span>'}
              <button class="des-btn amarillo" id="des-pista" ${(p.pistas || 0) >= 3 ? 'disabled' : ''}><i class="fa-solid fa-lightbulb"></i> Pista ${(p.pistas || 0) ? `(${Math.min(p.pistas, 3)}/3)` : ''}</button>
              ${d.pistas_fuente ? '<button class="des-btn amarillo" id="des-pista-autor"><i class="fa-solid fa-book"></i> Pistas del autor</button>' : ''}
              ${d.comprobacion && d.comprobacion.tipo !== 'ninguna' ? `<button class="des-btn rojo" id="des-solucion"><i class="fa-solid fa-flag"></i> ${d.solucion_disponible ? 'Ver solución' : 'Rendirme y ver solución'}</button>` : ''}
              <span style="flex:1"></span>
              <span class="des-ayuda" id="des-contadores"></span>
            </div>
            <div id="des-resultado" style="margin-top:10px;"></div>
            <div id="des-pistas" style="display:flex; flex-direction:column; gap:8px; margin-top:8px;"></div>
            <div id="des-solucion-caja" style="margin-top:8px;"></div>
          </section>

          <section class="des-seccion" id="des-sec-tutor">
            <details><summary class="des-seccion-titulo" style="cursor:pointer; margin:0;"><i class="fa-solid fa-comments"></i> Preguntar al tutor sobre este desafío</summary>
              <div id="des-tutor-msgs" style="display:flex; flex-direction:column; gap:6px; margin:8px 0;"></div>
              <div class="des-fila"><input id="des-tutor-texto" class="des-campo" style="flex:1;" placeholder="¿Por qué falla la prueba…? ¿Qué es un generador…?">
                <button class="des-btn azul" id="des-tutor-enviar"><i class="fa-solid fa-paper-plane"></i></button></div>
              <div class="des-ayuda" style="margin-top:4px;">El tutor ve tu código y la última comprobación, pero no te da la solución.</div>
            </details>
          </section>`;

        pintarEnunciado();
        pintarRazonamiento();
        pintarPaginas();
        pintarContadores();
        pintarResultado();
        pintarTutor();
        conectarHoja();
        if (estado.solucion) pintarSolucion(estado.solucion);
    }

    function pintarVacio(c) {
        c.innerHTML = `
          <div class="des-vacio">
            <i class="fa-solid fa-chess-knight" style="font-size:40px; color:var(--accent-purple);"></i>
            <h2>Desafíos: primero pensar, después programar</h2>
            <p style="line-height:1.6;">Cada desafío empieza por entender el problema y razonarlo. El código viene al final, en páginas que se usan entre sí como un proyecto de verdad.</p>
            <div class="des-orden">
              <div><i class="fa-solid fa-flag-checkered"></i>Desafío</div><div><i class="fa-solid fa-brain"></i>Caja de razonamiento</div>
              <div><i class="fa-solid fa-pen"></i>Tu plan</div><div><i class="fa-solid fa-file-code"></i>Páginas de código</div><div><i class="fa-solid fa-vial-circle-check"></i>Pruebas</div>
            </div>
            <div class="des-fila" style="justify-content:center;">
              <input id="des-rapido" class="des-campo" style="max-width:340px;" placeholder="¿Qué quieres practicar? p. ej. recursividad">
              <select id="des-rapido-nivel" class="des-campo" style="width:auto;">${NIVELES.map(n => `<option ${n === 'intermedio' ? 'selected' : ''}>${n}</option>`).join('')}</select>
            </div>
            <div class="des-fila" style="justify-content:center; margin-top:8px;">
              <button class="des-btn primario" id="des-rapido-crear"><i class="fa-solid fa-wand-magic-sparkles"></i> Crear con el modelo</button>
              <button class="des-btn" id="des-rapido-internet"><i class="fa-solid fa-globe"></i> Buscar en internet</button>
            </div>
            <p class="des-ayuda" style="margin-top:14px;">También puedes conversarlo en el <b>Chat</b>, partir de un bloque de tu <b>Plan</b> o retomar uno de <b>Mis desafíos</b>.</p>
          </div>`;
        const tema = () => $('des-rapido').value.trim();
        $('des-rapido').value = estado.internet.tema || '';
        $('des-rapido').onkeydown = (e) => { if (e.key === 'Enter' && tema()) crearConModelo({ tema: tema(), nivel: $('des-rapido-nivel').value }); };
        $('des-rapido-crear').onclick = () => { if (!tema()) return $('des-rapido').focus(); crearConModelo({ tema: tema(), nivel: $('des-rapido-nivel').value }); };
        $('des-rapido-internet').onclick = () => {
            if (!tema()) return $('des-rapido').focus();
            estado.internet.tema = tema(); estado.internet.nivel = $('des-rapido-nivel').value; estado.internet.bloque = null;
            cambiarPanel('internet'); buscarInternet();
        };
    }

    function pintarTarea(c) {
        const t = estado.tarea;
        c.innerHTML = `
          <div class="des-seccion" style="margin-top:30px;">
            <div class="des-titulo" style="font-size:16px;">${t.error ? '<i class="fa-solid fa-circle-exclamation" style="color:var(--accent-red);"></i>' : '<i class="fa-solid fa-spinner fa-spin" style="color:var(--accent-purple);"></i>'} ${esc(t.titulo)}</div>
            ${t.lineas.map((l, i) => `<div class="des-ayuda" style="margin-top:6px; ${i === t.lineas.length - 1 && !t.error ? 'color:var(--text-main);' : ''}">${esc(l)}</div>`).join('')}
            ${t.error ? `<div class="des-error" style="margin-top:10px;">${esc(t.error)}</div>
              <div class="des-fila" style="margin-top:10px;"><button class="des-btn" id="des-tarea-volver"><i class="fa-solid fa-arrow-left"></i> Volver</button></div>`
              : '<div class="des-fila" style="margin-top:12px;"><button class="des-btn rojo" id="des-tarea-cancelar"><i class="fa-solid fa-stop"></i> Cancelar</button></div>'}
          </div>`;
        const volver = $('des-tarea-volver');
        if (volver) volver.onclick = () => { estado.tarea = null; pintarHoja(); };
        const cancelar = $('des-tarea-cancelar');
        if (cancelar) cancelar.onclick = async () => {
            estado.pedido++;
            estado.tarea = null;
            await fetch('/api/ai/cancel', { method: 'POST' }).catch(() => {});
            pintarHoja();
        };
    }

    function pintarEnunciado() {
        const d = estado.d;
        const usarEs = estado.idioma === 'es' && d.enunciado_es;
        const e = $('des-enunciado');
        if (e) pintarMd(e, usarEs ? d.enunciado_es : d.enunciado);
        const t = $('des-teoria');
        if (t) pintarMd(t, usarEs && d.teoria_es ? d.teoria_es : d.teoria);
    }

    // ------------------------------------------------------------------ caja de razonamiento
    function pintarRazonamiento() {
        const c = $('des-razonamiento');
        const d = estado.d;
        if (!c) return;
        const r = d.razonamiento;
        if (!r || !estado.pasosVisibles) {
            c.innerHTML = `
              <button class="des-btn des-caja-boton" id="des-caja"><i class="fa-solid fa-brain"></i> Caja de razonamiento</button>
              <div class="des-ayuda" style="margin-top:6px; text-align:center;">Cómo pensar este problema, lógica y algorítmicamente, paso a paso y sin darte el código.
                Intenta responder cada pregunta antes de abrir el siguiente paso.</div>
              <div id="des-caja-progreso"></div>`;
            $('des-caja').onclick = () => abrirRazonamiento(false);
            return;
        }
        const pasos = r.pasos;
        const visibles = Math.min(estado.pasosVisibles, pasos.length);
        c.innerHTML = `
          <div class="des-fila"><span class="des-ayuda"><i class="fa-solid fa-brain" style="color:var(--accent-purple);"></i> Caja de razonamiento · paso ${visibles} de ${pasos.length}</span>
            <span style="flex:1"></span>
            <button class="des-btn" id="des-caja-regenerar" title="Pedir otra explicación"><i class="fa-solid fa-rotate"></i></button></div>
          ${pasos.slice(0, visibles).map((p, i) => `<div class="des-paso"><div class="des-paso-titulo">${i + 1}. ${esc(p.titulo)}</div><div class="des-md" data-paso="${i}"></div></div>`).join('')}
          ${visibles < pasos.length ? `<div class="des-fila" style="margin-top:10px;">
              <button class="des-btn morado" id="des-caja-siguiente"><i class="fa-solid fa-forward-step"></i> Siguiente paso: ${esc(pasos[visibles].titulo)}</button>
              <button class="des-btn" id="des-caja-todo">Ver todos</button>
              <span class="des-ayuda">¿Ya lo pensaste tú? Compáralo con el siguiente paso.</span></div>`
            : '<div class="des-ayuda" style="margin-top:8px;"><i class="fa-solid fa-check"></i> Ya tienes el razonamiento completo. Escribe tu plan o pasa a las páginas.</div>'}`;
        c.querySelectorAll('[data-paso]').forEach(el => pintarMd(el, pasos[+el.dataset.paso].contenido));
        const sig = $('des-caja-siguiente');
        if (sig) sig.onclick = () => verPasos(visibles + 1, true);
        const todo = $('des-caja-todo');
        if (todo) todo.onclick = () => verPasos(pasos.length, false);
        $('des-caja-regenerar').onclick = () => { if (confirm('¿Pedir al modelo otra explicación del razonamiento?')) abrirRazonamiento(true); };
    }

    function verPasos(n, desplazar) {
        estado.pasosVisibles = n;
        enviar(`/api/desafios/${estado.d.id}/razonamiento/visto`, { pasos_vistos: n }).catch(() => {});
        pintarRazonamiento();
        if (desplazar) {
            const pasos = document.querySelectorAll('#des-razonamiento .des-paso');
            if (pasos.length) pasos[pasos.length - 1].scrollIntoView({ block: 'nearest', behavior: 'smooth' });
        }
    }

    async function abrirRazonamiento(regenerar) {
        const d = estado.d;
        const c = $('des-razonamiento');
        let escrito = '';
        c.innerHTML = `<div class="des-ayuda"><i class="fa-solid fa-spinner fa-spin" style="color:var(--accent-purple);"></i> El tutor prepara el razonamiento… <span id="des-caja-avance"></span></div>`;
        try {
            const r = await flujo(`/api/desafios/${d.id}/razonamiento`, { modelo: estado.modelo, regenerar }, (ev) => {
                if (ev.tipo === 'texto') {
                    escrito += ev.delta;
                    const n = (escrito.match(/^##\s/gm) || []).length;
                    const a = $('des-caja-avance');
                    if (a) a.textContent = n ? `(escribiendo el paso ${n} de 6)` : '';
                }
            });
            if (!estado.d || estado.d.id !== d.id) return;
            d.razonamiento = r;
            estado.pasosVisibles = Math.max(1, regenerar ? 1 : estado.pasosVisibles);
            enviar(`/api/desafios/${d.id}/razonamiento/visto`, { pasos_vistos: estado.pasosVisibles }).catch(() => {});
            pintarRazonamiento();
        } catch (e) {
            if (!estado.d || estado.d.id !== d.id) return;
            c.innerHTML = `<div class="des-error">${esc(e.message)}</div><button class="des-btn" style="margin-top:6px;" id="des-caja-reintentar">Reintentar</button>`;
            $('des-caja-reintentar').onclick = () => abrirRazonamiento(regenerar);
        }
    }

    // ------------------------------------------------------------------ páginas
    function iniciales() { return new Map((estado.d.paginas || []).map(p => [p.nombre, p])); }

    function pintarPaginas() {
        const c = $('des-paginas');
        if (!c) return;
        destruirEditores();
        const base = iniciales();
        c.innerHTML = estado.paginas.map((p, i) => {
            const deBase = base.get(p.nombre);
            return `<div class="des-pagina" data-i="${i}">
              <div class="des-pagina-cab">
                <i class="fa-brands fa-python" style="color:var(--accent-yellow);"></i>
                <span class="des-pagina-nombre">${esc(p.nombre)}</span>
                ${p.solo_lectura ? '<span class="des-mini" title="Página de apoyo del ejercicio">solo lectura</span>' : ''}
                <span class="des-ayuda" style="flex:1; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">${esc(p.descripcion || (deBase || {}).descripcion || '')}</span>
                <button class="des-btn azul" data-ejecutar title="Ejecutar esta página (Mayús+Enter)"><i class="fa-solid fa-play"></i> Ejecutar</button>
                ${deBase && !p.solo_lectura ? '<button class="des-btn" data-restaurar title="Volver al código de partida"><i class="fa-solid fa-clock-rotate-left"></i></button>' : ''}
                ${!deBase ? '<button class="des-btn" data-renombrar title="Cambiar nombre"><i class="fa-solid fa-pen"></i></button><button class="des-btn rojo" data-quitar title="Quitar página"><i class="fa-solid fa-trash"></i></button>' : ''}
              </div>
              <div class="des-pagina-editor"></div>
              <div class="des-salida" hidden></div>
            </div>`;
        }).join('');
        c.querySelectorAll('.des-pagina').forEach(el => {
            const i = +el.dataset.i;
            const pagina = estado.paginas[i];
            crearEditor(el.querySelector('.des-pagina-editor'), pagina);
            el.querySelector('[data-ejecutar]').onclick = () => ejecutarPagina(pagina.nombre);
            const restaurar = el.querySelector('[data-restaurar]');
            if (restaurar) restaurar.onclick = () => {
                if (!confirm(`¿Volver al código de partida de ${pagina.nombre}? Pierdes lo escrito en esta página.`)) return;
                const ed = estado.editores.get(pagina.nombre);
                if (ed) ed.setValue(base.get(pagina.nombre).contenido);
            };
            const renombrar = el.querySelector('[data-renombrar]');
            if (renombrar) renombrar.onclick = () => {
                const nuevo = prompt('Nuevo nombre de la página (termina en .py):', pagina.nombre);
                if (!nuevo) return;
                const nombre = nombreModulo(nuevo);
                if (estado.paginas.some(x => x !== pagina && x.nombre.toLowerCase() === nombre.toLowerCase())) return alert('Ya hay una página con ese nombre.');
                pagina.nombre = nombre;
                guardarPronto();
                pintarPaginas();
            };
            const quitar = el.querySelector('[data-quitar]');
            if (quitar) quitar.onclick = () => {
                if (!confirm(`¿Quitar la página ${pagina.nombre}?`)) return;
                estado.paginas.splice(i, 1);
                guardarPronto();
                pintarPaginas();
            };
        });
    }

    function crearEditor(cont, pagina) {
        if (typeof monaco === 'undefined') {
            cont.innerHTML = `<textarea class="des-campo" rows="12" style="font-family:'Fira Code',monospace; border:none;">${esc(pagina.contenido)}</textarea>`;
            const ta = cont.querySelector('textarea');
            ta.readOnly = !!pagina.solo_lectura;
            ta.oninput = () => { pagina.contenido = ta.value; guardarPronto(); };
            return;
        }
        const ed = monaco.editor.create(cont, {
            value: pagina.contenido || '', language: 'python', readOnly: !!pagina.solo_lectura,
            theme: leerLocal('prig_editor_theme') || 'prig-dark',
            fontSize: parseInt(leerLocal('prig_editor_font_size') || '14', 10),
            fontFamily: leerLocal('prig_editor_font_family') || "'Fira Code', monospace",
            tabSize: parseInt(leerLocal('prig_editor_tab_size') || '4', 10),
            minimap: { enabled: false }, scrollBeyondLastLine: false, automaticLayout: true,
            scrollbar: { alwaysConsumeMouseWheel: false }, lineNumbersMinChars: 3, padding: { top: 6, bottom: 6 },
        });
        const ajustar = () => {
            const alto = Math.max(120, Math.min(560, ed.getContentHeight()));
            cont.style.height = `${alto}px`;
            ed.layout({ width: cont.clientWidth, height: alto });
        };
        ed.onDidContentSizeChange(ajustar);
        ajustar();
        ed.onDidChangeModelContent(() => { pagina.contenido = ed.getValue(); guardarPronto(); });
        ed.addCommand(monaco.KeyMod.Shift | monaco.KeyCode.Enter, () => ejecutarPagina(pagina.nombre));
        ed.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.Enter, () => comprobar());
        estado.editores.set(pagina.nombre, ed);
    }

    function destruirEditores() {
        estado.editores.forEach(ed => { try { ed.dispose(); } catch (e) { /* ya destruido */ } });
        estado.editores.clear();
    }

    function paginasActuales() {
        return estado.paginas.map(p => ({ nombre: p.nombre, contenido: p.contenido || '', descripcion: p.descripcion || '' }));
    }

    function guardarPronto() {
        clearTimeout(estado.guardado);
        const g = $('des-guardado');
        if (g) g.textContent = '· cambios sin guardar';
        estado.guardado = setTimeout(guardarAhora, 1200);
    }

    function guardarAhora() {
        if (!estado.guardado || !estado.d) return;
        clearTimeout(estado.guardado);
        estado.guardado = null;
        const id = estado.d.id;
        fetch(`/api/desafios/${id}/paginas`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ paginas: paginasActuales() }) })
            .then(async res => {
                const g = $('des-guardado');
                if (!g || !estado.d || estado.d.id !== id) return;
                g.textContent = res.ok ? '· guardado' : `· no se guardó: ${await window.prigErrorDetail(res)}`;
            }).catch(() => {});
    }

    function nuevaPagina(nombre, contenido) {
        let n = nombreModulo(nombre);
        let k = 2;
        while (estado.paginas.some(p => p.nombre.toLowerCase() === n.toLowerCase())) n = n.replace(/(_\d+)?\.py$/, `_${k++}.py`);
        estado.paginas.push({ nombre: n, contenido: contenido || '', descripcion: '' });
        guardarPronto();
        pintarPaginas();
        const ultima = document.querySelector('#des-paginas .des-pagina:last-child');
        if (ultima) ultima.scrollIntoView({ block: 'center', behavior: 'smooth' });
    }

    async function ejecutarPagina(nombre) {
        const el = [...document.querySelectorAll('#des-paginas .des-pagina')].find(x => estado.paginas[+x.dataset.i] && estado.paginas[+x.dataset.i].nombre === nombre);
        if (!el) return;
        const salida = el.querySelector('.des-salida');
        salida.hidden = false;
        salida.innerHTML = `<span class="des-ayuda"><i class="fa-solid fa-spinner fa-spin"></i> Ejecutando ${esc(nombre)}…</span>
          <button class="des-btn rojo" style="float:right; padding:1px 6px;" data-detener>Detener</button>`;
        salida.querySelector('[data-detener]').onclick = () => fetch(`/api/desafios/${estado.d.id}/detener`, { method: 'POST' });
        try {
            const r = await enviar(`/api/desafios/${estado.d.id}/ejecutar`, { paginas: paginasActuales(), pagina: nombre });
            salida.innerHTML = `<div class="des-fila" style="margin-bottom:4px;"><span class="des-mini" style="color:${r.ok ? 'var(--accent-green)' : 'var(--accent-red)'};">${r.cancelado ? 'detenido' : r.ok ? 'terminó bien' : 'terminó con error'}</span>
                <span class="des-ayuda">${r.elapsed}s</span><span style="flex:1"></span><button class="des-btn" style="padding:1px 6px;" data-cerrar><i class="fa-solid fa-xmark"></i></button></div>
              ${r.stdout ? `<div>${esc(r.stdout)}</div>` : ''}${r.stderr ? `<div style="color:var(--accent-red);">${esc(r.stderr)}</div>` : ''}
              ${!r.stdout && !r.stderr ? '<span class="des-ayuda">(sin salida: usa print para ver resultados)</span>' : ''}`;
        } catch (e) {
            salida.innerHTML = `<div style="color:var(--accent-red);">${esc(e.message)}</div><button class="des-btn" style="padding:1px 6px;" data-cerrar><i class="fa-solid fa-xmark"></i></button>`;
        }
        const cerrar = salida.querySelector('[data-cerrar]');
        if (cerrar) cerrar.onclick = () => { salida.hidden = true; };
    }

    // ------------------------------------------------------------------ comprobar, pistas, solución
    function pintarContadores() {
        const c = $('des-contadores');
        if (!c || !estado.d) return;
        const p = estado.d.progreso || {};
        const partes = [];
        if (p.intentos) partes.push(`${p.intentos} ${p.intentos === 1 ? 'intento' : 'intentos'}`);
        if (p.pistas) partes.push(`${p.pistas} ${p.pistas === 1 ? 'pista' : 'pistas'}`);
        if (p.pasos_vistos) partes.push(`razonamiento: ${p.pasos_vistos} pasos`);
        if (p.mejor && p.mejor.total) partes.push(`mejor: ${p.mejor.pasados}/${p.mejor.total}`);
        c.textContent = partes.join(' · ');
    }

    async function comprobar() {
        const d = estado.d;
        if (!d || !d.comprobacion || d.comprobacion.tipo === 'ninguna') return;
        const boton = $('des-comprobar');
        const c = $('des-resultado');
        if (boton) boton.disabled = true;
        c.innerHTML = '<div class="des-ayuda"><i class="fa-solid fa-spinner fa-spin"></i> Ejecutando las pruebas contra tus páginas…</div>';
        try {
            const r = await enviar(`/api/desafios/${d.id}/comprobar`, { paginas: paginasActuales() });
            if (!estado.d || estado.d.id !== d.id) return;
            const antes = (d.progreso || {}).estado;
            d.progreso = r.progreso;
            estado.ultimo = r;
            clearTimeout(estado.guardado); estado.guardado = null;
            const g = $('des-guardado'); if (g) g.textContent = '· guardado';
            if (r.aprobado && antes !== 'resuelto' && antes !== 'rendido') { pintarHoja(); $('des-sec-comprobar').scrollIntoView({ block: 'start', behavior: 'smooth' }); }
            else { pintarResultado(); pintarContadores(); }
        } catch (e) {
            c.innerHTML = `<div class="des-error">No se pudo comprobar: ${esc(e.message)}</div>`;
        } finally {
            const b = $('des-comprobar');
            if (b) b.disabled = false;
        }
    }

    function pintarResultado() {
        const c = $('des-resultado');
        const r = estado.ultimo;
        const d = estado.d;
        if (!c || !d) return;
        if (!r) { c.innerHTML = ''; return; }
        const p = d.progreso || {};
        const pct = r.total ? Math.round(100 * r.pasados / r.total) : 0;
        if (r.aprobado) {
            const esOrigenPlan = d.origen && d.origen.ruta_id && d.origen.bloque_id;
            c.innerHTML = `<div class="des-exito">
              <div style="font-size:15px; font-weight:700; color:var(--accent-green);"><i class="fa-solid fa-trophy"></i> ¡Pasan las ${r.total} pruebas!</div>
              <div class="des-ayuda" style="margin-top:4px;">${p.estado === 'rendido' ? 'Ya habías visto la solución, así que cuenta como practicado, no como resuelto por ti.'
                : `Resuelto en ${p.intentos} ${p.intentos === 1 ? 'intento' : 'intentos'}${p.pistas ? ` con ${p.pistas} ${p.pistas === 1 ? 'pista' : 'pistas'}` : ' sin pistas'}${p.segundos_hasta_resolver ? `, ${Math.max(1, Math.round(p.segundos_hasta_resolver / 60))} min desde que empezaste` : ''}.`}</div>
              <div class="des-fila" style="margin-top:10px;">
                ${p.estado === 'resuelto' ? '<button class="des-btn morado" id="des-reflexion"><i class="fa-solid fa-magnifying-glass-chart"></i> Reflexión del tutor sobre tu solución</button>' : ''}
                <button class="des-btn" id="des-ver-referencia"><i class="fa-solid fa-code-compare"></i> Comparar con la solución de referencia</button>
                ${esOrigenPlan ? '<button class="des-btn azul" id="des-completar-bloque"><i class="fa-solid fa-circle-check"></i> Marcar el bloque del plan como completado</button>' : ''}
              </div>
              <div class="des-md" id="des-reflexion-texto" style="margin-top:8px;"></div>
              <div class="des-ayuda" style="margin-top:10px;">Siguiente desafío:</div>
              <div class="des-fila" style="margin-top:4px;">
                <button class="des-btn" data-siguiente="mas_facil"><i class="fa-solid fa-arrow-down"></i> Más fácil</button>
                <button class="des-btn azul" data-siguiente="parecido"><i class="fa-solid fa-equals"></i> Otro parecido</button>
                <button class="des-btn primario" data-siguiente="mas_dificil"><i class="fa-solid fa-arrow-up"></i> Más difícil</button>
              </div></div>`;
            const refl = $('des-reflexion');
            if (refl) refl.onclick = reflexionar;
            $('des-ver-referencia').onclick = verSolucion;
            const comp = $('des-completar-bloque');
            if (comp) comp.onclick = () => completarBloque(comp);
            c.querySelectorAll('[data-siguiente]').forEach(b => b.onclick = () => crearConModelo({ basado_en: d.id, ajuste: b.dataset.siguiente, nivel: d.nivel }));
            return;
        }
        c.innerHTML = `
          <div class="des-fila"><b style="color:${r.pasados ? 'var(--accent-yellow)' : 'var(--accent-red)'};">${r.error && !r.total ? 'No se pudieron ejecutar las pruebas' : `Pasan ${r.pasados} de ${r.total} pruebas`}</b>
            <span style="flex:1"></span><span class="des-ayuda">${r.elapsed != null ? r.elapsed + 's' : ''}</span></div>
          ${r.total ? `<div class="des-barra-prog" style="margin:6px 0;"><div style="width:${pct}%;"></div></div>` : ''}
          ${r.error ? `<div class="des-error" style="margin-top:6px;">${esc(r.error)}</div>` : ''}
          ${(r.fallos || []).slice(0, 6).map(f => `<div class="des-fallo"><b>${f.tipo === 'error' ? 'Error en' : 'Falla'}: ${esc(f.nombre)}</b>
              ${f.codigo ? `<pre style="color:var(--text-muted);">${esc(f.codigo)}</pre>` : ''}<pre>${esc(f.mensaje)}</pre></div>`).join('')}
          ${(r.fallos || []).length > 6 ? `<div class="des-ayuda">…y ${r.fallos.length - 6} más.</div>` : ''}
          ${r.stdout ? `<details style="margin-top:6px;"><summary class="des-ayuda" style="cursor:pointer;">Lo que imprimió tu código</summary><pre class="des-salida">${esc(r.stdout)}</pre></details>` : ''}
          <div class="des-ayuda" style="margin-top:6px;">Lee qué caso falla, vuelve a la caja de razonamiento si hace falta, o pide una pista.</div>`;
    }

    async function pedirPista(nivelAutor) {
        const d = estado.d;
        const p = d.progreso || {};
        const nivel = nivelAutor ? 0 : Math.min(3, (p.pistas || 0) + 1);
        const cont = $('des-pistas');
        const caja = document.createElement('div');
        caja.className = 'des-paso';
        caja.style.borderLeftColor = 'var(--accent-yellow)';
        caja.innerHTML = '<div class="des-paso-titulo" style="color:var(--accent-yellow);"><i class="fa-solid fa-spinner fa-spin"></i> Pensando una pista…</div><div class="des-md"></div>';
        cont.appendChild(caja);
        caja.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
        const titulo = caja.querySelector('.des-paso-titulo');
        const cuerpo = caja.querySelector('.des-md');
        try {
            if (nivel === 0) {
                const r = await enviar(`/api/desafios/${d.id}/pista`, { nivel: 0 });
                titulo.innerHTML = `<i class="fa-solid fa-book"></i> ${esc(r.titulo)}`;
                pintarMd(cuerpo, r.texto);
                d.progreso.pistas = Math.max(d.progreso.pistas || 0, 1);
            } else {
                let texto = '';
                await flujo(`/api/desafios/${d.id}/pista`, { nivel, modelo: estado.modelo, paginas: paginasActuales() }, (ev) => {
                    if (ev.tipo === 'titulo') titulo.innerHTML = `<i class="fa-solid fa-lightbulb"></i> ${esc(ev.texto)}`;
                    if (ev.tipo === 'texto') { texto += ev.delta; pintarMd(cuerpo, texto); }
                });
                d.progreso.pistas = Math.max(d.progreso.pistas || 0, nivel);
            }
        } catch (e) {
            titulo.textContent = 'No se pudo obtener la pista';
            cuerpo.textContent = e.message;
        }
        const b = $('des-pista');
        if (b) { b.innerHTML = `<i class="fa-solid fa-lightbulb"></i> Pista (${Math.min(d.progreso.pistas, 3)}/3)`; b.disabled = d.progreso.pistas >= 3; }
        pintarContadores();
    }

    async function verSolucion() {
        const d = estado.d;
        if (!d.solucion_disponible && !confirm('Ver la solución deja este desafío como «visto con solución» en tu progreso.\n\n¿Seguro? Una pista o la caja de razonamiento quizá basten.')) return;
        try {
            const r = await enviar(`/api/desafios/${d.id}/rendirse`, {});
            d.progreso = r.progreso;
            d.solucion_disponible = true;
            estado.solucion = r;
            pintarSolucion(r);
            pintarContadores();
            const s = $('des-sol-caja');
            if (s) s.scrollIntoView({ block: 'start', behavior: 'smooth' });
        } catch (e) { alert(e.message); }
    }

    function pintarSolucion(r) {
        const c = $('des-solucion-caja');
        if (!c) return;
        const pruebas = r.pruebas == null ? '' : typeof r.pruebas === 'string' ? r.pruebas
            : Array.isArray(r.pruebas) ? r.pruebas.join('\n\n') : Object.entries(r.pruebas).map(([n, t]) => `# ${n}\n${t}`).join('\n\n');
        c.innerHTML = `<div class="des-paso" id="des-sol-caja" style="border-left-color:var(--accent-red);">
            <div class="des-paso-titulo" style="color:var(--accent-red);"><i class="fa-solid fa-flag"></i> Solución de referencia</div>
            ${(r.referencia || []).map(p => `<div class="des-ayuda" style="margin-top:6px;">${esc(p.nombre)}</div><pre class="des-salida" style="border:1px solid var(--border-color); border-radius:6px;"><code class="language-python">${esc(p.contenido)}</code></pre>`).join('')}
            ${pruebas ? `<details><summary class="des-ayuda" style="cursor:pointer;">Pruebas con las que se comprueba</summary><pre class="des-salida"><code class="language-python">${esc(pruebas)}</code></pre></details>` : ''}
            <div class="des-ayuda">Consejo: no la copies. Ciérrala, espera unos minutos y vuelve a escribir tu versión desde cero.</div></div>`;
        if (window.hljs) c.querySelectorAll('pre code').forEach(b => { try { hljs.highlightElement(b); } catch (e) { /* sin resaltado */ } });
    }

    async function reflexionar() {
        const c = $('des-reflexion-texto');
        const b = $('des-reflexion');
        if (b) b.disabled = true;
        let texto = '';
        c.innerHTML = '<span class="des-ayuda"><i class="fa-solid fa-spinner fa-spin"></i> El tutor revisa tu solución…</span>';
        try {
            await flujo(`/api/desafios/${estado.d.id}/reflexion`, { modelo: estado.modelo, paginas: paginasActuales() }, (ev) => {
                if (ev.tipo === 'texto') { texto += ev.delta; pintarMd(c, texto); }
            });
        } catch (e) { c.innerHTML = `<div class="des-error">${esc(e.message)}</div>`; if (b) b.disabled = false; }
    }

    async function completarBloque(boton) {
        const { ruta_id, bloque_id } = estado.d.origen;
        boton.disabled = true;
        try {
            const ruta = await json(`/api/guided/${encodeURIComponent(ruta_id)}`);
            const hechos = new Set(ruta.completed_blocks || []);
            hechos.add(bloque_id);
            await enviar(`/api/guided/${encodeURIComponent(ruta_id)}/progress`, { completed_blocks: [...hechos] });
            boton.innerHTML = '<i class="fa-solid fa-check"></i> Bloque completado';
            estado.plan.ruta = null;
            if (window.planActualMgr && window.planActualMgr.refrescar) window.planActualMgr.refrescar();
        } catch (e) { boton.disabled = false; alert(e.message); }
    }

    // ------------------------------------------------------------------ tutor del desafío
    function pintarTutor() {
        const c = $('des-tutor-msgs');
        if (!c || !estado.d) return;
        const msgs = estado.chatDesafio[estado.d.id] || [];
        c.innerHTML = msgs.map((m, i) => `<div class="des-msg ${m.rol}" data-i="${i}"></div>`).join('');
        c.querySelectorAll('.des-msg').forEach(el => pintarMd(el, msgs[+el.dataset.i].texto || '…'));
    }

    async function preguntarTutor() {
        const campo = $('des-tutor-texto');
        const t = campo.value.trim();
        const d = estado.d;
        if (!t || !d) return;
        campo.value = '';
        const msgs = estado.chatDesafio[d.id] = estado.chatDesafio[d.id] || [];
        msgs.push({ rol: 'usuario', texto: t });
        const respuesta = { rol: 'tutor', texto: '' };
        msgs.push(respuesta);
        pintarTutor();
        try {
            await flujo('/api/desafios/chat', { mensajes: msgs.slice(0, -1), modelo: estado.modelo, desafio_id: d.id, paginas: paginasActuales() }, (ev) => {
                if (ev.tipo === 'texto' && estado.d && estado.d.id === d.id) {
                    respuesta.texto += ev.delta;
                    const el = document.querySelector(`#des-tutor-msgs .des-msg[data-i="${msgs.indexOf(respuesta)}"]`);
                    if (el) pintarMd(el, respuesta.texto);
                }
            });
        } catch (e) { respuesta.texto = `*No pude responder: ${e.message}*`; }
        if (estado.d && estado.d.id === d.id) pintarTutor();
    }

    // ------------------------------------------------------------------ eventos de la hoja
    function conectarHoja() {
        const d = estado.d;
        const on = (id, fn) => { const el = $(id); if (el) el.onclick = fn; };
        on('des-traducir', async () => {
            if (d.enunciado_es) { estado.idioma = estado.idioma === 'es' ? 'orig' : 'es'; return pintarHoja(); }
            const b = $('des-traducir');
            b.disabled = true;
            let texto = '';
            b.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Traduciendo…';
            try {
                const r = await flujo(`/api/desafios/${d.id}/traducir`, { modelo: estado.modelo }, (ev) => {
                    if (ev.tipo === 'texto') { texto += ev.delta; const e = $('des-enunciado'); if (e) pintarMd(e, texto); }
                });
                if (!estado.d || estado.d.id !== d.id) return;
                Object.assign(d, r);
                estado.idioma = 'es';
                pintarEnunciado();
                b.disabled = false;
                b.innerHTML = '<i class="fa-solid fa-language"></i> Ver original';
            } catch (e) { b.disabled = false; b.innerHTML = '<i class="fa-solid fa-language"></i> Traducir al español'; alert(e.message); }
        });
        const otra = $('des-otra-funcion');
        if (otra) otra.onchange = () => { if (otra.value) importar({ fuente: d.origen.tipo, ref: d.origen.ref, titulo: otra.value, verificable: true }, otra.value); };
        on('des-plan-revisar', async () => {
            const plan = $('des-plan').value.trim();
            const c = $('des-plan-respuesta');
            if (!plan) { $('des-plan').focus(); return; }
            let texto = '';
            c.innerHTML = '<span class="des-ayuda"><i class="fa-solid fa-spinner fa-spin"></i> El tutor lee tu plan…</span>';
            try {
                await flujo(`/api/desafios/${d.id}/plan`, { plan, modelo: estado.modelo }, (ev) => { if (ev.tipo === 'texto') { texto += ev.delta; pintarMd(c, texto); } });
                d.progreso.plan = plan;
            } catch (e) { c.innerHTML = `<div class="des-error">${esc(e.message)}</div>`; }
        });
        on('des-pagina-nueva', () => {
            const nombre = prompt('Nombre de la nueva página (por ejemplo utiles.py):', 'utiles.py');
            if (nombre) nuevaPagina(nombre, '');
        });
        on('des-pagina-importar', () => $('des-pagina-archivo').click());
        const archivo = $('des-pagina-archivo');
        if (archivo) archivo.onchange = async () => {
            for (const f of archivo.files) {
                if (f.size > 200000) { alert(`${f.name} es demasiado grande.`); continue; }
                nuevaPagina(f.name, await f.text());
            }
            archivo.value = '';
        };
        on('des-comprobar', comprobar);
        on('des-pista', () => pedirPista(false));
        on('des-pista-autor', () => pedirPista(true));
        on('des-solucion', verSolucion);
        on('des-tutor-enviar', preguntarTutor);
        const tt = $('des-tutor-texto');
        if (tt) tt.onkeydown = (e) => { if (e.key === 'Enter') preguntarTutor(); };
    }

    // ================================================================== entrada pública
    /**
     * abrir()                              la sección tal cual
     * abrir({tema})                        busca ese tema en internet y lo deja listo para crear
     * abrir({rutaId, bloqueId})            el plan de estudios con ese bloque señalado
     * abrir({id})                          un desafío concreto
     */
    async function abrir(opciones = {}) {
        if (window.workArea) window.workArea.abrirHerramienta('modal-desafios', 'Desafíos', 'fa-chess-knight');
        else { const m = $('modal-desafios'); if (m) m.style.display = 'flex'; }
        montar();
        if (opciones.id) abrirPorId(opciones.id);
        else if (!estado.d && !estado.tarea) {
            const ultimo = leerLocal('prig_desafio_abierto');
            if (ultimo) abrirPorId(ultimo, true);
        }
        if (opciones.tema) {
            estado.internet.tema = opciones.tema;
            estado.internet.bloque = null;
            cambiarPanel('internet');
            buscarInternet();
        } else if (opciones.rutaId) {
            estado.plan.rutaId = opciones.rutaId;
            estado.plan.bloqueDestacado = opciones.bloqueId || null;
            estado.plan.rutas = null;
            cambiarPanel('plan');
        }
        setTimeout(() => estado.editores.forEach(ed => ed.layout()), 80);
    }

    window.addEventListener('beforeunload', guardarAhora);
    window.Desafios = { abrir, estado };
})();
