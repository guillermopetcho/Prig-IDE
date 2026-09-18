/**
 * Kaggle dentro de Prig, con la misma estructura que su web: Código, Datasets y
 * Competiciones, cada uno con su ficha, y un profesor al lado.
 *
 *   · Código: notebooks de la comunidad leídos celda a celda con el modelo (qué hace,
 *     por qué, conceptos), con guía de lectura, lectura paso a paso y preguntas.
 *   · Datasets (sin cuenta) y Competiciones: ficha con descripción, etiquetas y cifras;
 *     explorador de archivos con resumen por columna y primeras filas; los notebooks que
 *     usan esos datos; y el profesor explicando qué contienen y qué hacer con ellos.
 *   · «Descargar al proyecto» baja los datos a kaggle_datos/<slug>/, que es donde los
 *     buscan los notebooks guardados en el proyecto: así se ejecutan en Prig y se ven sus
 *     tablas y gráficos (Kaggle no da las salidas por su API).
 *
 * Lo explicado se guarda y lo leído cuenta en el Perfil.
 */
(function () {
    const $ = (id) => document.getElementById(id);
    const esc = (t) => String(t ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
    const json = (url, opciones) => window.prigFetchJson(url, opciones);
    const enviar = (url, cuerpo, metodo = 'POST') => json(url, { method: metodo, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(cuerpo || {}) });
    const leerLocal = (k) => { try { return localStorage.getItem(k); } catch (e) { return null; } };
    const guardarLocal = (k, v) => { try { localStorage.setItem(k, v); } catch (e) { /* sin almacenamiento */ } };

    const estado = {
        cuenta: null, vista: null, pila: [], listas: {}, ficha: null, fichaPestana: 'datos', archivoActivo: null,
        previaVista: null, codigoFicha: {}, explicacionDatos: {}, descargando: false,
        colecciones: [], guardados: {}, coloresColeccion: [], coleccion: null, filtroColeccion: '',
        lecturas: [], nb: null, explicaciones: {}, abiertas: new Set(), activa: null, pidiendo: new Set(),
        guia: null, nivel: leerLocal('prig_kaggle_nivel') || 'intermedio', modelo: null, modelos: [],
        chat: [], pasoAPaso: false,
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
        if (window.hljs) el.querySelectorAll('pre code').forEach(b => { try { hljs.highlightElement(b); } catch (e) { /* sin resaltado */ } });
    }

    function codigoResaltado(texto) {
        if (window.hljs) {
            try { return hljs.highlight(texto, { language: 'python' }).value; } catch (e) { /* texto plano */ }
        }
        return esc(texto);
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
                else alEvento && alEvento(ev);
            }
        }
        return fin;
    }

    const fecha = (t) => {
        if (!t) return '';
        const dias = Math.floor((Date.now() - new Date(t)) / 86400000);
        return dias <= 0 ? 'hoy' : dias === 1 ? 'ayer' : dias < 30 ? `hace ${dias} días` : new Date(t).toLocaleDateString('es');
    };
    const miles = (n) => n == null ? '' : n >= 1000 ? `${(n / 1000).toFixed(1)}k` : String(n);


    // ================================================================== estilos
    function estilos() {
        if ($('kg-estilos')) return;
        const css = document.createElement('style');
        css.id = 'kg-estilos';
        css.textContent = `
          #kaggle-raiz { display:grid; grid-template-columns: 196px 1fr; height:100%; min-height:0; background:var(--bg-dark); }
          #kaggle-raiz a { color:#20beff; text-decoration:none; }
          #kaggle-raiz a:hover { text-decoration:underline; }
          #kaggle-raiz select option, #kaggle-raiz select optgroup { background:#1e1e2e; color:#cdd6f4; }
          .kg-nav { border-right:1px solid var(--border-color); display:flex; flex-direction:column; min-height:0; background:var(--bg-panel); padding:10px 8px; gap:2px; }
          .kg-logo { font-size:26px; font-weight:800; color:#20beff; letter-spacing:-1px; padding:2px 10px 12px; font-family:system-ui, sans-serif; }
          .kg-nav button.kg-nav-item { display:flex; align-items:center; gap:12px; background:none; border:none; border-radius:20px; color:var(--text-main); padding:9px 12px; cursor:pointer; font-size:12.5px; text-align:left; }
          .kg-nav button.kg-nav-item i { width:18px; text-align:center; color:var(--text-muted); }
          .kg-nav button.kg-nav-item:hover { background:rgba(255,255,255,.05); }
          .kg-nav button.kg-nav-item.activa { background:rgba(32,190,255,.14); color:#20beff; font-weight:600; }
          .kg-nav button.kg-nav-item.activa i { color:#20beff; }
          .kg-campo { width:100%; box-sizing:border-box; background:var(--bg-dark); color:var(--text-main); border:1px solid var(--border-color); border-radius:6px; padding:6px 8px; font-size:12px; }
          .kg-buscador { display:flex; align-items:center; gap:8px; background:var(--bg-panel); border:1px solid var(--border-color); border-radius:22px; padding:6px 14px; flex:1; }
          .kg-buscador input { flex:1; background:none; border:none; outline:none; color:var(--text-main); font-size:13px; }
          .kg-btn { background:rgba(255,255,255,.05); color:var(--text-main); border:1px solid var(--border-color); border-radius:6px; padding:5px 10px; font-size:11.5px; cursor:pointer; white-space:nowrap; display:inline-flex; gap:6px; align-items:center; text-decoration:none !important; }
          .kg-btn:hover:not(:disabled) { border-color:var(--accent-blue); }
          .kg-btn:disabled { opacity:.5; cursor:default; }
          .kg-btn.azul { background:rgba(32,190,255,.14); border-color:rgba(32,190,255,.45); color:#20beff; }
          .kg-btn.morado { background:rgba(203,166,247,.15); border-color:rgba(203,166,247,.45); color:var(--accent-purple); }
          .kg-btn.verde { background:var(--accent-green); border-color:var(--accent-green); color:#11111b; font-weight:600; }
          .kg-btn.solido { background:#20beff; border-color:#20beff; color:#0b1620; font-weight:600; }
          .kg-chip { background:rgba(255,255,255,.04); color:var(--text-main); border:1px solid var(--border-color); border-radius:16px; padding:4px 12px; font-size:11.5px; cursor:pointer; white-space:nowrap; display:inline-flex; gap:6px; align-items:center; }
          .kg-chip.activa { background:rgba(32,190,255,.16); border-color:#20beff; color:#20beff; }
          .kg-etiqueta { font-size:10.5px; padding:2px 9px; border-radius:10px; background:rgba(255,255,255,.07); color:var(--text-muted); white-space:nowrap; }
          .kg-fila { display:flex; gap:6px; align-items:center; flex-wrap:wrap; }
          .kg-ayuda { font-size:11px; color:var(--text-muted); line-height:1.45; }
          .kg-error { font-size:12px; color:var(--accent-red); background:rgba(243,139,168,.08); border:1px solid rgba(243,139,168,.3); border-radius:6px; padding:8px 10px; }
          .kg-mini { font-size:10px; padding:1px 7px; border-radius:9px; background:rgba(255,255,255,.07); color:var(--text-muted); white-space:nowrap; }
          .kg-hoja { overflow-y:auto; min-height:0; position:relative; }
          .kg-pagina { padding:18px 24px 40px; max-width:1300px; }
          .kg-h1 { font-size:24px; font-weight:700; color:#fff; margin:0 0 4px; }
          .kg-volver { background:none; border:none; color:var(--text-muted); cursor:pointer; font-size:12px; padding:4px 0; margin-bottom:6px; }
          .kg-volver:hover { color:#20beff; }
          .kg-rejilla { display:grid; grid-template-columns:repeat(auto-fill, minmax(240px, 1fr)); gap:14px; margin-top:14px; }
          .kg-tarjeta { border:1px solid var(--border-color); border-radius:12px; overflow:hidden; background:var(--bg-panel); cursor:pointer; display:flex; flex-direction:column; transition:border-color .15s, transform .15s; }
          .kg-tarjeta:hover { border-color:#20beff; transform:translateY(-1px); }
          .kg-portada { height:108px; background:linear-gradient(135deg, rgba(32,190,255,.25), rgba(203,166,247,.18)); display:flex; align-items:center; justify-content:center; color:rgba(255,255,255,.35); font-size:30px; overflow:hidden; }
          .kg-portada img { width:100%; height:100%; object-fit:cover; }
          .kg-tarjeta-cuerpo { padding:10px 12px 12px; display:flex; flex-direction:column; gap:4px; flex:1; }
          .kg-tarjeta-cuerpo b { color:#fff; font-size:13px; line-height:1.3; }
          .kg-dos-lineas { display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; overflow:hidden; }
          .kg-lista-fila { display:flex; gap:12px; align-items:center; padding:12px 6px; border-bottom:1px solid rgba(255,255,255,.06); cursor:pointer; }
          .kg-lista-fila:hover { background:rgba(255,255,255,.03); }
          .kg-avatar { width:34px; height:34px; border-radius:50%; background:rgba(32,190,255,.18); color:#20beff; display:flex; align-items:center; justify-content:center; font-weight:700; font-size:14px; flex:none; }
          .kg-heroe { display:flex; gap:18px; align-items:flex-start; }
          .kg-heroe .kg-portada { width:170px; height:120px; border-radius:10px; flex:none; }
          .kg-pestanas2 { display:flex; gap:4px; border-bottom:1px solid var(--border-color); margin:18px 0 14px; }
          .kg-pestanas2 button { background:none; border:none; border-bottom:2px solid transparent; color:var(--text-muted); padding:9px 14px; cursor:pointer; font-size:12.5px; }
          .kg-pestanas2 button.activa { color:#fff; border-bottom-color:#20beff; font-weight:600; }
          .kg-datos-rej { display:grid; grid-template-columns: 250px minmax(0,1fr); gap:14px; }
          .kg-archivos { border:1px solid var(--border-color); border-radius:8px; overflow:hidden; align-self:start; }
          .kg-archivos div[data-archivo] { padding:7px 10px; font-size:12px; cursor:pointer; display:flex; gap:8px; align-items:center; border-bottom:1px solid rgba(255,255,255,.05); }
          .kg-archivos div[data-archivo]:hover { background:rgba(255,255,255,.04); }
          .kg-archivos div[data-archivo].activo { background:rgba(32,190,255,.12); color:#20beff; }
          .kg-columnas { display:grid; grid-template-columns:repeat(auto-fill, minmax(190px,1fr)); gap:10px; }
          .kg-col { border:1px solid rgba(255,255,255,.08); border-radius:8px; padding:9px 10px; background:rgba(0,0,0,.14); font-size:11.5px; }
          .kg-col b { color:#fff; font-size:12px; word-break:break-all; }
          .kg-frec { display:grid; grid-template-columns: 1fr auto; gap:2px 6px; margin-top:5px; }
          .kg-frec .barra { grid-column:1 / -1; height:4px; border-radius:2px; background:rgba(255,255,255,.07); overflow:hidden; }
          .kg-frec .barra > div { height:100%; background:#20beff; }
          .kg-tabla { border-collapse:collapse; font-size:11.5px; font-family:'Fira Code',monospace; }
          .kg-tabla th, .kg-tabla td { border-bottom:1px solid rgba(255,255,255,.07); padding:4px 10px; text-align:left; white-space:nowrap; max-width:260px; overflow:hidden; text-overflow:ellipsis; }
          .kg-tabla th { color:#fff; position:sticky; top:0; background:var(--bg-panel); }
          .kg-info { display:grid; grid-template-columns:repeat(auto-fill, minmax(170px,1fr)); gap:10px; }
          .kg-info div { border:1px solid var(--border-color); border-radius:8px; padding:9px 12px; }
          .kg-info span { display:block; font-size:10.5px; color:var(--text-muted); }
          .kg-info b { color:#fff; font-size:13px; }
          .kg-barra { height:6px; border-radius:3px; background:rgba(255,255,255,.07); overflow:hidden; }
          .kg-barra > div { height:100%; background:#20beff; transition:width .3s; }
          .kg-md { font-size:13px; line-height:1.65; color:var(--text-main); }
          .kg-md img { max-width:100%; border-radius:6px; }
          #kg-descripcion img { max-height:240px; width:auto; object-fit:contain; }
          .kg-md code { font-family:'Fira Code',monospace; font-size:11.5px; }
          .kg-cabecera { position:sticky; top:0; z-index:3; background:var(--bg-panel); border-bottom:1px solid var(--border-color); padding:10px 16px; }
          .kg-titulo { font-size:17px; font-weight:700; color:#fff; }
          .kg-celda { display:grid; grid-template-columns: minmax(0,1.15fr) minmax(0,1fr); gap:0; border-bottom:1px solid rgba(255,255,255,.05); }
          .kg-celda.activa { background:rgba(32,190,255,.04); }
          .kg-original { padding:10px 14px; min-width:0; border-right:1px dashed rgba(255,255,255,.08); }
          .kg-explicacion { padding:10px 14px; min-width:0; font-size:12.5px; line-height:1.6; color:var(--text-main); }
          .kg-explicacion h3 { font-size:12.5px; color:var(--accent-purple); margin:10px 0 3px; }
          .kg-explicacion code { font-family:'Fira Code',monospace; font-size:11.5px; }
          .kg-codigo { margin:0; padding:9px 11px; background:rgba(0,0,0,.35); border-radius:6px; font-family:'Fira Code',monospace; font-size:11.8px; line-height:1.5; overflow-x:auto; white-space:pre; }
          .kg-num { font-size:10px; color:var(--text-muted); margin-bottom:4px; display:flex; gap:6px; align-items:center; }
          .kg-guia { margin:12px 16px; border:1px solid rgba(203,166,247,.4); border-radius:9px; background:rgba(203,166,247,.05); padding:10px 14px; font-size:12.5px; line-height:1.6; }
          .kg-guia h2 { font-size:13px; color:var(--accent-purple); margin:10px 0 4px; }
          .kg-profesor { border:1px solid rgba(203,166,247,.35); border-radius:10px; background:rgba(203,166,247,.04); padding:12px 16px; }
          .kg-profesor h2 { font-size:14px; color:var(--accent-purple); margin:12px 0 4px; }
          .kg-chat { position:sticky; bottom:0; z-index:3; background:var(--bg-panel); border-top:1px solid var(--border-color); padding:8px 16px; }
          .kg-msgs { max-height:220px; overflow-y:auto; display:flex; flex-direction:column; gap:6px; margin-bottom:6px; }
          .kg-msg { padding:6px 10px; border-radius:8px; font-size:12px; line-height:1.5; max-width:90%; }
          .kg-msg.usuario { align-self:flex-end; background:rgba(32,190,255,.12); }
          .kg-msg.profesor { align-self:flex-start; background:rgba(255,255,255,.05); }
          .kg-vacio { max-width:560px; margin:60px auto; text-align:center; color:var(--text-muted); line-height:1.6; }
          .kg-vacio h2 { color:#fff; }
          .kg-tarjeta { position:relative; }
          .kg-guardar { background:rgba(0,0,0,.35); border:1px solid rgba(255,255,255,.15); color:#fff; border-radius:8px; width:30px; height:30px; cursor:pointer; display:inline-flex; align-items:center; justify-content:center; flex:none; }
          .kg-guardar:hover { border-color:#20beff; color:#20beff; }
          .kg-guardar.guardado { color:#20beff; }
          .kg-guardar.sobre { position:absolute; top:8px; right:8px; z-index:2; backdrop-filter:blur(4px); }
          .kg-lista-fila .kg-guardar { background:none; border-color:transparent; color:var(--text-muted); }
          .kg-lista-fila .kg-guardar.guardado { color:#20beff; }
          .kg-btn[data-guardar].guardado { color:#20beff; border-color:rgba(32,190,255,.45); }
          .kg-panel-filtros { display:grid; grid-template-columns:repeat(auto-fill, minmax(210px,1fr)); gap:10px 14px; margin-top:10px; padding:12px; border:1px solid var(--border-color); border-radius:10px; background:var(--bg-panel); }
          .kg-panel-filtros label span { display:block; font-size:10.5px; color:var(--text-muted); margin-bottom:3px; }
          .kg-popover { position:fixed; z-index:10060; width:280px; background:var(--bg-panel); border:1px solid var(--border-color); border-radius:10px; padding:10px; box-shadow:0 10px 30px rgba(0,0,0,.45); }
          .kg-popover-lista { max-height:210px; overflow-y:auto; }
          .kg-popover-item { display:flex; gap:8px; align-items:center; padding:6px 4px; border-radius:6px; cursor:pointer; font-size:12.5px; }
          .kg-popover-item:hover { background:rgba(255,255,255,.05); }
          .kg-punto { width:10px; height:10px; border-radius:50%; flex:none; display:inline-block; }
          .kg-mosaico { height:108px; display:grid; grid-template-columns:1fr 1fr; background:linear-gradient(135deg, var(--color), rgba(0,0,0,.3)); overflow:hidden; place-items:center; color:rgba(255,255,255,.7); font-size:30px; }
          .kg-mosaico img { width:100%; height:100%; object-fit:cover; }
          .kg-mosaico img:only-child { grid-column:1 / -1; }
          .kg-miniatura { width:54px; height:40px; border-radius:6px; background:rgba(32,190,255,.14); color:#20beff; display:flex; align-items:center; justify-content:center; overflow:hidden; flex:none; position:relative; }
          .kg-miniatura img { position:absolute; inset:0; width:100%; height:100%; object-fit:cover; }
          .kg-nota { margin-top:5px; font-size:12px; color:var(--text-main); cursor:text; white-space:pre-wrap; border-left:2px solid rgba(203,166,247,.5); padding-left:8px; }
          .kg-color { width:20px; height:20px; border-radius:50%; border:2px solid transparent; cursor:pointer; }
          .kg-color.activo { border-color:#fff; }
          .kg-capa { position:fixed; inset:0; background:rgba(0,0,0,.55); z-index:10050; display:flex; align-items:center; justify-content:center; }
          .kg-dialogo { max-width:94vw; max-height:92vh; overflow:auto; background:var(--bg-panel); border:1px solid var(--border-color); border-radius:10px; padding:16px; }
          .kg-opcion { display:flex; align-items:center; gap:8px; font-size:12.5px; padding:4px 0; cursor:pointer; }
          @media (max-width: 1100px) { .kg-celda { grid-template-columns: 1fr; } .kg-original { border-right:none; } .kg-datos-rej { grid-template-columns:1fr; } }
          @container (max-width: 1100px) { .kg-celda { grid-template-columns: 1fr; } .kg-original { border-right:none; } .kg-datos-rej { grid-template-columns:1fr; } }
          @container (max-width: 780px) {
            #kaggle-raiz { grid-template-columns:52px 1fr; }
            .kg-nav { padding:10px 6px; align-items:center; }
            .kg-logo { font-size:0; padding:0; }
            .kg-logo::before { content:'k'; font-size:24px; }
            .kg-nav button.kg-nav-item { font-size:0; gap:0; padding:9px; justify-content:center; }
            .kg-nav button.kg-nav-item i { font-size:14px; width:auto; }
            #kg-cuenta { display:none; }
          }
        `;
        document.head.appendChild(css);
    }

    // ================================================================== estructura
    const SECCIONES = [
        ['codigo', 'fa-code', 'Código'],
        ['datasets', 'fa-table', 'Datasets'],
        ['competiciones', 'fa-trophy', 'Competiciones'],
        ['colecciones', 'fa-bookmark', 'Colecciones'],
        ['lecturas', 'fa-book-open-reader', 'Mis lecturas'],
        ['datos', 'fa-hard-drive', 'Mis datos'],
    ];

    function montar() {
        estilos();
        const r = $('kaggle-raiz');
        if (!r || $('kg-nav')) return;
        r.innerHTML = `
          <nav class="kg-nav" id="kg-nav">
            <div class="kg-logo">kaggle</div>
            ${SECCIONES.map(([id, icono, texto]) => `<button class="kg-nav-item" data-seccion="${id}" title="${texto}"><i class="fa-solid ${icono}"></i>${texto}</button>`).join('')}
            <span style="flex:1"></span>
            <div id="kg-cuenta" style="padding:6px 4px;"></div>
          </nav>
          <main class="kg-hoja" id="kg-hoja"></main>`;
        $('kg-nav').onclick = (e) => {
            const b = e.target.closest('[data-seccion]');
            if (b) ir({ tipo: b.dataset.seccion });
        };
        cargarCuenta();
        cargarModelos();
        cargarGuardados();
        conectarGuardar($('kg-hoja'), buscarDatosItem);
        let inicial = null;
        try { inicial = JSON.parse(leerLocal('prig_kaggle_vista') || 'null'); } catch (e) { /* vista vieja */ }
        ir(inicial && inicial.tipo ? inicial : { tipo: 'datasets' }, false);
    }

    /** Navegación con «volver», como en la web: listas → ficha → notebook */
    function ir(vista, apilar = true) {
        if (apilar && estado.vista && JSON.stringify(estado.vista) !== JSON.stringify(vista)) estado.pila.push(estado.vista);
        if (estado.pila.length > 30) estado.pila.shift();
        estado.vista = vista;
        guardarLocal('prig_kaggle_vista', JSON.stringify({ tipo: vista.tipo, ref: vista.ref }));
        estado.pasoAPaso = false;
        cerrarPopover();
        const seccion = { notebook: 'codigo', dataset: 'datasets', competicion: 'competiciones', coleccion: 'colecciones' }[vista.tipo] || vista.tipo;
        document.querySelectorAll('#kg-nav [data-seccion]').forEach(b => b.classList.toggle('activa', b.dataset.seccion === seccion));
        const hoja = $('kg-hoja');
        if (hoja) hoja.scrollTop = 0;
        if (vista.tipo === 'notebook') return abrirNotebook(vista.ref, vista.celda);
        if (vista.tipo === 'dataset' || vista.tipo === 'competicion') return abrirFicha(vista.tipo, vista.ref, vista.pestana);
        if (vista.tipo === 'lecturas') return vistaLecturas();
        if (vista.tipo === 'datos') return vistaMisDatos();
        if (vista.tipo === 'colecciones') return vistaColecciones();
        if (vista.tipo === 'coleccion') return abrirColeccion(vista.ref);
        return vistaLista(vista.tipo);
    }

    function volver() {
        const v = estado.pila.pop();
        if (v) ir(v, false);
    }

    function barraVolver() {
        return estado.pila.length ? '<button class="kg-volver" data-volver><i class="fa-solid fa-arrow-left"></i> Volver</button>' : '';
    }

    function conectarVolver(raiz) {
        (raiz || document).querySelectorAll('[data-volver]').forEach(b => b.onclick = volver);
    }

    async function cargarCuenta() {
        try { estado.cuenta = await json('/api/kaggle/estado'); } catch (e) { estado.cuenta = null; }
        pintarCuenta();
    }

    const conectado = () => !!(estado.cuenta && estado.cuenta.conectado);

    function pintarCuenta() {
        const c = $('kg-cuenta');
        if (!c) return;
        const k = estado.cuenta;
        c.innerHTML = k && k.conectado
            ? `<div class="kg-fila" style="flex-wrap:nowrap;"><div class="kg-avatar" style="width:28px; height:28px; font-size:12px;">${esc((k.usuario || '?')[0].toUpperCase())}</div>
                 <span class="kg-ayuda" style="flex:1; min-width:0; overflow:hidden; text-overflow:ellipsis;" title="desde ${esc(k.origen)}"><b style="color:#fff;">${esc(k.usuario || 'tu cuenta')}</b></span>
                 <button class="kg-btn" id="kg-cuenta-btn" title="Cuenta de Kaggle" style="padding:4px 7px;"><i class="fa-solid fa-gear"></i></button></div>`
            : `<button class="kg-btn azul" id="kg-cuenta-btn" style="width:100%; justify-content:center;"><i class="fa-brands fa-kaggle"></i> Conectar cuenta</button>`;
        $('kg-cuenta-btn').onclick = dialogoCuenta;
    }

    function dialogoCuenta() {
        const k = estado.cuenta || {};
        const capa = document.createElement('div');
        capa.id = 'kg-dialogo';
        capa.style.cssText = 'position:fixed; inset:0; background:rgba(0,0,0,.55); z-index:10050; display:flex; align-items:center; justify-content:center;';
        capa.innerHTML = `
          <div style="width:520px; max-width:94vw; background:var(--bg-panel); border:1px solid var(--border-color); border-radius:10px; padding:16px;">
            <div class="kg-fila" style="margin-bottom:8px;"><i class="fa-brands fa-kaggle" style="color:#20beff; font-size:20px;"></i>
              <b style="color:#fff; font-size:15px; flex:1;">Cuenta de Kaggle</b><button class="kg-btn" data-cerrar><i class="fa-solid fa-xmark"></i></button></div>
            ${k.conectado ? `<div class="kg-ayuda" style="margin-bottom:10px;">Ahora: <b style="color:#fff;">${esc(k.usuario || '')}</b> (${esc(k.origen)}).
               ${k.origen === 'Prig' ? '' : 'Prig usa las mismas credenciales que el cliente oficial de Kaggle; no las copia ni las envía a ningún otro sitio.'}</div>` : ''}
            <ol class="kg-ayuda" style="padding-left:18px; margin:0 0 8px;">
              <li>Entra en <a href="${esc(k.url_token || 'https://www.kaggle.com/settings/account')}" target="_blank" rel="noopener noreferrer">kaggle.com → Settings → API</a>.</li>
              <li>Crea un token (o una clave «Legacy», que descarga <code>kaggle.json</code>).</li>
              <li>Pega aquí el token, o el contenido completo de <code>kaggle.json</code>.</li>
            </ol>
            <textarea id="kg-cred" class="kg-campo" rows="3" spellcheck="false" style="font-family:'Fira Code',monospace;" placeholder='KGAT_…   o   {"username":"…","key":"…"}'></textarea>
            <div class="kg-ayuda" style="margin-top:4px;">Se comprueba con Kaggle y se guarda solo en tu equipo (~/.prig_kaggle.json, legible solo por tu usuario).</div>
            <div id="kg-cred-error"></div>
            <div class="kg-fila" style="margin-top:10px;">
              ${k.origen === 'Prig' ? '<button class="kg-btn" data-borrar style="color:var(--accent-red);"><i class="fa-solid fa-link-slash"></i> Olvidar credenciales</button>' : ''}
              <span style="flex:1"></span><button class="kg-btn" data-cerrar>Cancelar</button>
              <button class="kg-btn verde" data-guardar><i class="fa-solid fa-plug"></i> Comprobar y guardar</button></div>
          </div>`;
        document.body.appendChild(capa);
        const cerrar = () => capa.remove();
        capa.addEventListener('click', (e) => { if (e.target === capa) cerrar(); });
        capa.querySelectorAll('[data-cerrar]').forEach(b => b.onclick = cerrar);
        const borrar = capa.querySelector('[data-borrar]');
        if (borrar) borrar.onclick = async () => { await fetch('/api/kaggle/credenciales', { method: 'DELETE' }); cerrar(); await cargarCuenta(); if (estado.vista) ir(estado.vista, false); };
        capa.querySelector('[data-guardar]').onclick = async (e) => {
            const b = e.currentTarget;
            b.disabled = true;
            b.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Comprobando…';
            try {
                estado.cuenta = await enviar('/api/kaggle/credenciales', { texto: $('kg-cred').value });
                cerrar();
                pintarCuenta();
                if (estado.vista) ir(estado.vista, false);
            } catch (err) {
                $('kg-cred-error').innerHTML = `<div class="kg-error" style="margin-top:8px;">${esc(err.message)}</div>`;
                b.disabled = false;
                b.innerHTML = '<i class="fa-solid fa-plug"></i> Comprobar y guardar';
            }
        };
        setTimeout(() => { const campo = $('kg-cred'); if (campo) campo.focus(); }, 30);
    }

    async function cargarModelos() {
        let locales = [], nube = [];
        try { locales = (await json('/api/modelos')).modelos.filter(m => !m.capacidades.includes('embedding')).map(m => m.nombre); } catch (e) { /* sin Ollama */ }
        try {
            const g = await json('/api/gemini/estado');
            if (g.configurado) nube = (await json('/api/gemini/modelos')).modelos.map(m => `gemini:${m.id}`);
        } catch (e) { /* sin Gemini */ }
        estado.modelos = [...locales, ...nube];
        const preferido = (window.PrigModelos && window.PrigModelos.para('explicar')) || leerLocal('prig_kaggle_modelo') || leerLocal('prig_desafios_modelo') || (window.aiConfig && window.aiConfig.agent1_model);
        estado.modelo = estado.modelos.includes(preferido) ? preferido : (estado.modelos[0] || preferido || '');
        const sel = $('kg-modelo');
        if (sel) pintarSelectorModelo(sel);
    }

    function pintarSelectorModelo(sel) {
        const locales = estado.modelos.filter(m => !m.startsWith('gemini:'));
        const nube = estado.modelos.filter(m => m.startsWith('gemini:'));
        sel.innerHTML = `${locales.length ? `<optgroup label="En tu equipo">${locales.map(m => `<option ${m === estado.modelo ? 'selected' : ''}>${esc(m)}</option>`).join('')}</optgroup>` : ''}
          ${nube.length ? `<optgroup label="Google Gemini · nube">${nube.map(m => `<option value="${esc(m)}" ${m === estado.modelo ? 'selected' : ''}>${esc(m.replace('gemini:', ''))} (Gemini)</option>`).join('')}</optgroup>` : ''}`
          || `<option>${esc(estado.modelo || 'sin modelos')}</option>`;
    }


    // ================================================================== listas (código, datasets, competiciones)
    const LISTAS = {
        codigo: {
            titulo: 'Código', subtitulo: 'Notebooks de la comunidad para leerlos con el profesor.',
            placeholder: 'Buscar notebooks: titanic, eda, xgboost, pytorch cnn…', cuenta: true,
            filtros: { orden: ['votos', [['votos', 'Más votados'], ['populares', 'En tendencia'], ['recientes', 'Ejecutados hace poco'], ['nuevos', 'Nuevos'], ['vistos', 'Más vistos'], ['comentados', 'Más comentados'], ['relevancia', 'Relevancia']]] },
            url: (b) => `/api/kaggle/buscar?${parametros(b, ['q', 'orden', 'pagina', 'usuario', 'competicion', 'dataset', 'padre', 'tipo', 'votos_min', 'dias', 'gpu'])}`,
            items: (d) => d.notebooks, rejilla: false,
            item: (n) => `<div class="kg-lista-fila">
                <div class="kg-avatar">${esc((n.autor || '?')[0].toUpperCase())}</div>
                <div style="flex:1; min-width:0;"><b style="color:#fff; font-size:13px;">${esc(n.titulo)}</b>
                  <div class="kg-ayuda">${esc(n.autor || '')}${n.ejecutado ? ' · ' + fecha(n.ejecutado) : ''}${n.tipo === 'script' ? ' · script' : ''}</div></div>
                ${n.gpu ? '<span class="kg-mini" title="Usa GPU">GPU</span>' : ''}
                ${(n.datos || []).length ? `<span class="kg-mini" title="${esc(n.datos.join(', '))}"><i class="fa-solid fa-database"></i> ${n.datos.length}</span>` : ''}
                <span class="kg-mini"><i class="fa-solid fa-caret-up"></i> ${miles(n.votos)}</span>${botonGuardar('notebook', n.ref)}</div>`,
            abrir: (n) => ir({ tipo: 'notebook', ref: n.ref }),
        },
        datasets: {
            titulo: 'Datasets', subtitulo: 'Explora, descarga y analiza datos de la comunidad. No hace falta cuenta.',
            placeholder: 'Buscar datasets: housing, covid, spotify, imágenes de gatos…', cuenta: false,
            filtros: {
                orden: ['populares', [['populares', 'En tendencia'], ['votos', 'Más votados'], ['recientes', 'Actualizados'], ['nuevos', 'Nuevos']]],
                tipo_archivo: ['', [['', 'Todos'], ['csv', 'CSV'], ['json', 'JSON'], ['parquet', 'Parquet'], ['sqlite', 'SQLite']]],
            },
            url: (b) => `/api/kaggle/datasets?${parametros(b, ['q', 'orden', 'pagina', 'tipo_archivo', 'usuario', 'licencia', 'tamano'])}`,
            items: (d) => d.datasets, rejilla: true,
            item: (d) => `<div class="kg-tarjeta">${botonGuardar('dataset', d.ref, 'sobre')}
                ${portada(d.imagen, 'fa-table')}
                <div class="kg-tarjeta-cuerpo"><b class="kg-dos-lineas">${esc(d.titulo)}</b>
                  <span class="kg-ayuda">${esc(d.autor || '')} · ${fecha(d.actualizado)}</span>
                  <span class="kg-ayuda">Usabilidad ${d.usabilidad} · ${tam(d.bytes)}</span>
                  <span style="flex:1"></span>
                  <div class="kg-fila kg-ayuda"><span><i class="fa-solid fa-caret-up"></i> ${miles(d.votos)}</span>
                    <span><i class="fa-solid fa-download"></i> ${miles(d.descargas)}</span>
                    <span><i class="fa-solid fa-code"></i> ${miles(d.notebooks)}</span></div></div></div>`,
            abrir: (d) => ir({ tipo: 'dataset', ref: d.ref }),
        },
        competiciones: {
            titulo: 'Competiciones', subtitulo: 'Problemas reales con datos, métrica y clasificación. Las de «Para empezar» son ideales para aprender.',
            placeholder: 'Buscar competiciones…', cuenta: true,
            filtros: { categoria: ['', [['', 'Activas'], ['gettingStarted', 'Para empezar'], ['playground', 'Playground'], ['featured', 'Destacadas'], ['research', 'Investigación'], ['community', 'Comunidad']]] },
            url: (b) => `/api/kaggle/competiciones?${parametros(b, ['q', 'categoria', 'pagina', 'grupo', 'orden'])}`,
            items: (d) => d.competiciones, rejilla: true,
            item: (c) => `<div class="kg-tarjeta">${botonGuardar('competicion', c.ref, 'sobre')}
                ${portada(c.imagen, 'fa-trophy')}
                <div class="kg-tarjeta-cuerpo"><b class="kg-dos-lineas">${esc(c.titulo)}</b>
                  <span class="kg-ayuda kg-dos-lineas">${esc(c.subtitulo || '')}</span>
                  <span style="flex:1"></span>
                  <div class="kg-fila kg-ayuda"><span class="kg-etiqueta">${esc(c.categoria || '')}</span>${cierre(c)}</div>
                  <div class="kg-fila kg-ayuda"><span><i class="fa-solid fa-medal"></i> ${esc(c.premio || '')}</span><span><i class="fa-solid fa-users"></i> ${miles(c.equipos)} equipos</span></div></div></div>`,
            abrir: (c) => ir({ tipo: 'competicion', ref: c.ref }),
        },
    };

    /** Solo los parámetros con valor: los vacíos no viajan */
    function parametros(b, campos) {
        const p = new URLSearchParams();
        campos.forEach(c => { if (b[c] !== undefined && b[c] !== null && b[c] !== '') p.set(c, b[c]); });
        return p;
    }

    /** Lo que se sabe de un elemento para guardarlo: de la lista, la ficha o el notebook abiertos */
    function buscarDatosItem(tipo, ref) {
        if (tipo === 'notebook' && estado.nb && estado.nb.ref === ref) return estado.nb;
        if (estado.ficha && estado.ficha.tipo === tipo && estado.ficha.ref === ref) return estado.ficha;
        const listas = { notebook: ['codigo'], dataset: ['datasets'], competicion: ['competiciones'] }[tipo] || [];
        for (const l of listas) {
            const it = (((estado.listas[l] || {}).datos || {})._items || []).find(x => x.ref === ref);
            if (it) return it;
        }
        for (const b of Object.values(estado.codigoFicha || {})) {
            const it = (b.items || []).find(x => x.ref === ref);
            if (it) return it;
        }
        return { titulo: ref };
    }

    const tam = (n) => {
        if (n == null) return '';
        const u = ['B', 'KB', 'MB', 'GB', 'TB'];
        let i = 0;
        while (n >= 1024 && i < u.length - 1) { n /= 1024; i++; }
        return `${i ? n.toFixed(n < 10 ? 1 : 0) : n} ${u[i]}`;
    };

    function portada(url, icono) {
        return `<div class="kg-portada"><i class="fa-solid ${icono}"></i>${url ? `<img src="${esc(url)}" alt="" loading="lazy" onload="this.previousElementSibling.remove()" onerror="this.remove()">` : ''}</div>`;
    }

    function cierre(c) {
        if (!c.cierre) return '';
        const dias = Math.ceil((new Date(c.cierre) - Date.now()) / 86400000);
        if (dias < 0) return '<span>Cerrada</span>';
        return `<span>${dias > 365 ? 'Sin fecha de cierre' : dias === 0 ? 'Cierra hoy' : `Quedan ${dias} días`}</span>`;
    }

    function estadoLista(clave) {
        if (!estado.listas[clave]) {
            const b = { q: '', pagina: 1, datos: null, cargando: false, error: null };
            Object.entries(LISTAS[clave].filtros).forEach(([campo, [defecto]]) => { b[campo] = defecto; });
            (AVANZADOS[clave] || []).forEach(d => { if (!(d.campo in b)) b[d.campo] = ''; });
            estado.listas[clave] = b;
        }
        return estado.listas[clave];
    }

    function vistaLista(clave) {
        const cfg = LISTAS[clave];
        const b = estadoLista(clave);
        const hoja = $('kg-hoja');
        const bloqueada = cfg.cuenta && !conectado();
        hoja.innerHTML = `<div class="kg-pagina">
            <h1 class="kg-h1">${cfg.titulo}</h1>
            <div class="kg-ayuda" style="margin-bottom:12px;">${cfg.subtitulo}</div>
            <div class="kg-fila" style="flex-wrap:nowrap;">
              <label class="kg-buscador"><i class="fa-solid fa-magnifying-glass" style="color:var(--text-muted);"></i>
                <input id="kg-q" placeholder="${esc(cfg.placeholder)}" value="${esc(b.q)}" ${bloqueada ? 'disabled' : ''}></label>
            </div>
            ${Object.entries(cfg.filtros).map(([campo, [, opciones]]) => `<div class="kg-fila" style="margin-top:10px;" data-filtro="${campo}">
                ${opciones.map(([v, t]) => `<button class="kg-chip ${b[campo] === v ? 'activa' : ''}" data-valor="${esc(v)}" ${bloqueada ? 'disabled' : ''}>${t}</button>`).join('')}</div>`).join('')}
            ${filtrosAvanzadosHtml(clave, b, bloqueada)}
            ${clave === 'codigo' ? `<div class="kg-fila" style="margin-top:12px; flex-wrap:nowrap;"><span class="kg-ayuda" style="white-space:nowrap;"><i class="fa-solid fa-link"></i> Abrir por enlace (sin cuenta):</span>
                <input id="kg-enlace" class="kg-campo" placeholder="kaggle.com/code/usuario/nombre · kaggle.com/datasets/… · kaggle.com/competitions/…" spellcheck="false">
                <button class="kg-btn azul" id="kg-abrir">Abrir</button></div>` : ''}
            ${bloqueada ? `<div class="kg-profesor" style="margin-top:16px;"><b style="color:#fff;">Esta sección necesita tu cuenta de Kaggle</b>
                <div class="kg-ayuda" style="margin:4px 0 8px;">Kaggle solo deja buscar ${clave === 'codigo' ? 'notebooks' : 'competiciones'} con una cuenta. Los datasets se exploran sin ella, y cualquier notebook se abre pegando su enlace.</div>
                <button class="kg-btn solido" data-conectar><i class="fa-brands fa-kaggle"></i> Conectar mi cuenta</button></div>` : ''}
            <div id="kg-resultados"></div></div>`;
        const conectar = hoja.querySelector('[data-conectar]');
        if (conectar) conectar.onclick = dialogoCuenta;
        if (clave === 'codigo') {
            $('kg-abrir').onclick = () => abrirEnlace($('kg-enlace').value);
            $('kg-enlace').onkeydown = (e) => { if (e.key === 'Enter') $('kg-abrir').click(); };
        }
        if (bloqueada) return;
        $('kg-q').onkeydown = (e) => { if (e.key === 'Enter') { b.q = e.target.value.trim(); b.pagina = 1; buscarLista(clave); } };
        conectarFiltrosAvanzados(clave, b, hoja);
        hoja.querySelectorAll('[data-filtro]').forEach(fila => fila.onclick = (e) => {
            const chip = e.target.closest('[data-valor]');
            if (!chip) return;
            b[fila.dataset.filtro] = chip.dataset.valor;
            b.pagina = 1;
            b.q = $('kg-q').value.trim();
            vistaLista(clave);
            buscarLista(clave);
        });
        if (!b.datos && !b.cargando) buscarLista(clave);
        else pintarLista(clave);
    }

    function abrirEnlace(texto) {
        const t = (texto || '').trim();
        if (!t) return;
        if (/kaggle\.com\/datasets\//.test(t)) return ir({ tipo: 'dataset', ref: t });
        if (/kaggle\.com\/(competitions|c)\//.test(t)) return ir({ tipo: 'competicion', ref: t });
        ir({ tipo: 'notebook', ref: t });
    }

    async function buscarLista(clave, anadir = false) {
        const cfg = LISTAS[clave];
        const b = estadoLista(clave);
        b.cargando = true; b.error = null;
        pintarLista(clave);
        try {
            const d = await json(cfg.url(b));
            const nuevos = cfg.items(d);
            b.datos = anadir && b.datos ? { ...d, _items: [...b.datos._items, ...nuevos] } : { ...d, _items: nuevos };
        } catch (e) { b.error = e.message; }
        b.cargando = false;
        if (estado.vista && estado.vista.tipo === clave) pintarLista(clave);
    }

    function pintarLista(clave) {
        const c = $('kg-resultados');
        if (!c) return;
        const cfg = LISTAS[clave];
        const b = estadoLista(clave);
        const items = (b.datos && b.datos._items) || [];
        c.innerHTML = (b.error ? `<div class="kg-error" style="margin-top:14px;">${esc(b.error)}</div>` : '')
            + `<div class="${cfg.rejilla ? 'kg-rejilla' : ''}" style="${cfg.rejilla ? '' : 'margin-top:10px;'}">${items.map((it, i) => `<div data-i="${i}" style="display:contents;">${cfg.item(it)}</div>`).join('')}</div>`
            + (b.cargando ? '<div class="kg-ayuda" style="margin:14px 0;"><i class="fa-solid fa-spinner fa-spin"></i> Buscando en Kaggle…</div>' : '')
            + (!b.cargando && b.datos && !items.length ? '<div class="kg-ayuda" style="margin-top:14px;">Sin resultados con estos filtros.</div>' : '')
            + (!b.cargando && b.datos && b.datos.ocultos ? `<div class="kg-ayuda" style="margin-top:8px;"><i class="fa-solid fa-filter"></i> ${b.datos.ocultos} resultados de esta página no cumplen los filtros de votos, fecha, tipo o GPU (Kaggle no los filtra: se filtran aquí).</div>` : '')
            + (!b.cargando && b.datos && b.datos.hay_mas ? '<button class="kg-btn" id="kg-mas" style="margin-top:14px;">Cargar más</button>' : '');
        c.querySelectorAll('[data-i]').forEach(el => { el.firstElementChild.onclick = () => cfg.abrir(items[+el.dataset.i]); });
        const mas = $('kg-mas');
        if (mas) mas.onclick = () => { b.pagina++; buscarLista(clave, true); };
    }

    // ================================================================== filtros avanzados
    /** Los filtros que no caben en los chips: se abren con «Más filtros» y se ven como etiquetas quitables */
    const AVANZADOS = {
        codigo: [
            { campo: 'usuario', etiqueta: 'Autor', tipo: 'texto', ayuda: 'usuario de Kaggle, p. ej. alexisbcook' },
            { campo: 'competicion', etiqueta: 'Competición', tipo: 'texto', ayuda: 'p. ej. titanic' },
            { campo: 'dataset', etiqueta: 'Dataset', tipo: 'texto', ayuda: 'dueño/nombre' },
            { campo: 'padre', etiqueta: 'Copias de', tipo: 'texto', ayuda: 'enlace de un notebook: sus versiones copiadas' },
            { campo: 'tipo', etiqueta: 'Tipo', tipo: 'select', opciones: [['', 'Notebooks y scripts'], ['notebook', 'Solo notebooks'], ['script', 'Solo scripts']] },
            { campo: 'votos_min', etiqueta: 'Votos mínimos', tipo: 'select', opciones: [['', 'Cualquiera'], ['10', '10+'], ['50', '50+'], ['100', '100+'], ['500', '500+'], ['1000', '1000+']] },
            { campo: 'dias', etiqueta: 'Ejecutado', tipo: 'select', opciones: [['', 'Cuando sea'], ['7', 'Última semana'], ['30', 'Último mes'], ['365', 'Último año']] },
            { campo: 'gpu', etiqueta: 'GPU', tipo: 'select', opciones: [['', 'Indiferente'], ['true', 'Usa GPU'], ['false', 'Sin GPU']] },
        ],
        datasets: [
            { campo: 'usuario', etiqueta: 'Autor', tipo: 'texto', ayuda: 'usuario de Kaggle' },
            { campo: 'licencia', etiqueta: 'Licencia', tipo: 'select', opciones: [['', 'Cualquiera'], ['cc', 'Creative Commons'], ['gpl', 'GPL'], ['odb', 'Open Database'], ['other', 'Otras']] },
            { campo: 'tamano', etiqueta: 'Tamaño', tipo: 'select', opciones: [['', 'Cualquiera'], ['pequeno', 'Menos de 1 MB'], ['mediano', '1 MB – 100 MB'], ['grande', '100 MB – 1 GB'], ['enorme', 'Más de 1 GB']] },
        ],
        competiciones: [
            { campo: 'grupo', etiqueta: 'Mostrar', tipo: 'select', opciones: [['', 'Todas'], ['mias', 'En las que participo']] },
            { campo: 'orden', etiqueta: 'Orden', tipo: 'select', opciones: [['', 'Agrupadas'], ['premio', 'Mayor premio'], ['cierre', 'Cierran antes'], ['equipos', 'Más equipos'], ['nuevas', 'Más nuevas']] },
        ],
    };

    function textoFiltro(def, valor) {
        const op = def.opciones && def.opciones.find(([v]) => v === valor);
        return `${def.etiqueta}: ${op ? op[1] : valor}`;
    }

    function filtrosAvanzadosHtml(clave, b, bloqueada) {
        const defs = AVANZADOS[clave] || [];
        const activos = defs.filter(d => b[d.campo]);
        return `<div class="kg-fila" style="margin-top:10px;">
              <button class="kg-chip ${b._panel ? 'activa' : ''}" data-panel-filtros ${bloqueada ? 'disabled' : ''}><i class="fa-solid fa-sliders"></i> Más filtros${activos.length ? ` (${activos.length})` : ''}</button>
              ${activos.map(d => `<span class="kg-chip activa" data-quitar-filtro="${d.campo}" title="Quitar filtro">${esc(textoFiltro(d, b[d.campo]))} <i class="fa-solid fa-xmark"></i></span>`).join('')}
              ${activos.length > 1 ? '<button class="kg-chip" data-limpiar-filtros>Quitar todos</button>' : ''}
            </div>
            ${b._panel ? `<div class="kg-panel-filtros">
              ${defs.map(d => `<label><span>${d.etiqueta}</span>${d.tipo === 'select'
                ? `<select class="kg-campo" data-avanzado="${d.campo}">${d.opciones.map(([v, t]) => `<option value="${esc(v)}" ${b[d.campo] === v ? 'selected' : ''}>${t}</option>`).join('')}</select>`
                : `<input class="kg-campo" data-avanzado="${d.campo}" value="${esc(b[d.campo] || '')}" placeholder="${esc(d.ayuda || '')}" spellcheck="false">`}</label>`).join('')}
              <div class="kg-fila" style="grid-column:1 / -1; justify-content:flex-end;">
                <button class="kg-btn" data-limpiar-filtros>Limpiar</button><button class="kg-btn solido" data-aplicar-filtros>Aplicar filtros</button></div>
            </div>` : ''}`;
    }

    function conectarFiltrosAvanzados(clave, b, hoja) {
        const relanzar = () => { b.pagina = 1; b.q = $('kg-q').value.trim(); b.datos = null; vistaLista(clave); };
        const panel = hoja.querySelector('[data-panel-filtros]');
        if (panel) panel.onclick = () => { b._panel = !b._panel; vistaLista(clave); };
        hoja.querySelectorAll('[data-quitar-filtro]').forEach(x => x.onclick = () => { b[x.dataset.quitarFiltro] = ''; relanzar(); });
        hoja.querySelectorAll('[data-limpiar-filtros]').forEach(x => x.onclick = () => { (AVANZADOS[clave] || []).forEach(d => { b[d.campo] = ''; }); relanzar(); });
        const aplicar = hoja.querySelector('[data-aplicar-filtros]');
        if (aplicar) aplicar.onclick = () => {
            hoja.querySelectorAll('[data-avanzado]').forEach(el => { b[el.dataset.avanzado] = el.value.trim(); });
            b._panel = false;
            relanzar();
        };
        hoja.querySelectorAll('input[data-avanzado]').forEach(el => el.onkeydown = (e) => { if (e.key === 'Enter' && aplicar) aplicar.click(); });
    }

    // ================================================================== guardar en colecciones
    const TIPOS_ITEM = { notebook: ['fa-code', 'Notebook'], dataset: ['fa-table', 'Dataset'], competicion: ['fa-trophy', 'Competición'] };

    async function cargarGuardados() {
        try {
            const d = await json('/api/kaggle/colecciones');
            estado.colecciones = d.colecciones;
            estado.guardados = d.guardados;
            estado.coloresColeccion = d.colores;
        } catch (e) { /* sin colecciones todavía */ }
        refrescarMarcas();
    }

    const claveItem = (tipo, ref) => `${tipo}:${ref}`;
    const estaGuardado = (tipo, ref) => ((estado.guardados || {})[claveItem(tipo, ref)] || []).length > 0;

    function botonGuardar(tipo, ref, clase = '') {
        const si = estaGuardado(tipo, ref);
        return `<button class="kg-guardar ${clase} ${si ? 'guardado' : ''}" data-guardar="${esc(tipo)}|${esc(ref)}" title="${si ? 'Guardado · cambiar colecciones' : 'Guardar en una colección'}">
            <i class="fa-${si ? 'solid' : 'regular'} fa-bookmark"></i></button>`;
    }

    function refrescarMarcas() {
        document.querySelectorAll('#kaggle-raiz [data-guardar]').forEach(b => {
            const [tipo, ref] = b.dataset.guardar.split('|');
            const si = estaGuardado(tipo, ref);
            b.classList.toggle('guardado', si);
            const i = b.querySelector('i');
            if (i) i.className = `fa-${si ? 'solid' : 'regular'} fa-bookmark`;
            const texto = b.querySelector('span');
            if (texto) texto.textContent = si ? 'Guardado' : 'Guardar';
        });
    }

    /** Qué se guarda de cada cosa para pintarla en la colección sin red */
    function datosParaGuardar(tipo, it) {
        if (!it) return {};
        return { titulo: it.titulo, subtitulo: it.subtitulo || '', autor: it.autor || it.organizador || '',
                 imagen: it.imagen || null, votos: it.votos ?? null, url: it.url || null };
    }

    function cerrarPopover() {
        const p = $('kg-popover');
        if (p) p.remove();
        document.removeEventListener('mousedown', cerrarPopoverFuera, true);
    }

    function cerrarPopoverFuera(e) {
        const p = $('kg-popover');
        if (p && !p.contains(e.target) && !e.target.closest('[data-guardar]')) cerrarPopover();
    }

    function abrirGuardar(boton, tipo, ref, datos) {
        cerrarPopover();
        const p = document.createElement('div');
        p.id = 'kg-popover';
        p.className = 'kg-popover';
        const r = boton.getBoundingClientRect();
        p.style.top = `${Math.min(window.innerHeight - 340, r.bottom + 6)}px`;
        p.style.left = `${Math.max(8, Math.min(window.innerWidth - 300, r.right - 280))}px`;
        document.body.appendChild(p);
        const pintar = () => {
            const dentro = new Set((estado.guardados || {})[claveItem(tipo, ref)] || []);
            p.innerHTML = `<div class="kg-fila" style="margin-bottom:6px;"><b style="color:#fff; flex:1;">Guardar en…</b>
                  <button class="kg-btn" data-cerrar style="padding:2px 7px;"><i class="fa-solid fa-xmark"></i></button></div>
                <div class="kg-popover-lista">${(estado.colecciones || []).map(c => `<label class="kg-popover-item">
                    <input type="checkbox" data-col="${c.id}" ${dentro.has(c.id) ? 'checked' : ''}>
                    <span class="kg-punto" style="background:${esc(c.color)};"></span><span style="flex:1;">${esc(c.nombre)}</span>
                    <span class="kg-ayuda">${c.total}</span></label>`).join('') || '<div class="kg-ayuda" style="padding:6px 2px;">Aún no tienes colecciones: crea la primera.</div>'}</div>
                <div class="kg-fila" style="margin-top:8px; flex-wrap:nowrap;"><input class="kg-campo" id="kg-nueva-col" placeholder="Nueva colección…" maxlength="80">
                  <button class="kg-btn solido" id="kg-crear-col"><i class="fa-solid fa-plus"></i></button></div>
                <div class="kg-error" id="kg-col-error" hidden style="margin-top:6px;"></div>`;
            p.querySelector('[data-cerrar]').onclick = cerrarPopover;
            p.querySelectorAll('[data-col]').forEach(ch => ch.onchange = async () => {
                ch.disabled = true;
                try {
                    if (ch.checked) await enviar(`/api/kaggle/colecciones/${ch.dataset.col}/items`, { tipo, ref, datos });
                    else await fetch(`/api/kaggle/colecciones/${ch.dataset.col}/items?${new URLSearchParams({ tipo, ref })}`, { method: 'DELETE' });
                    await cargarGuardados();
                } catch (e) { mostrarError(e.message); ch.checked = !ch.checked; }
                ch.disabled = false;
                pintar();
            });
            const crear = async () => {
                const nombre = $('kg-nueva-col').value.trim();
                if (!nombre) return;
                try {
                    const c = await enviar('/api/kaggle/colecciones', { nombre });
                    await enviar(`/api/kaggle/colecciones/${c.id}/items`, { tipo, ref, datos });
                    await cargarGuardados();
                    pintar();
                } catch (e) { mostrarError(e.message); }
            };
            $('kg-crear-col').onclick = crear;
            $('kg-nueva-col').onkeydown = (e) => { if (e.key === 'Enter') crear(); if (e.key === 'Escape') cerrarPopover(); };
            setTimeout(() => { const n = $('kg-nueva-col'); if (n && !(estado.colecciones || []).length) n.focus(); }, 20);
        };
        const mostrarError = (m) => { const e = $('kg-col-error'); if (e) { e.hidden = false; e.textContent = m; } };
        pintar();
        setTimeout(() => document.addEventListener('mousedown', cerrarPopoverFuera, true), 0);
    }

    /** Un solo manejador para todos los botones «Guardar» dentro de Kaggle */
    function conectarGuardar(raiz, buscarDatos) {
        raiz.addEventListener('click', (e) => {
            const b = e.target.closest('[data-guardar]');
            if (!b || !raiz.contains(b)) return;
            e.stopPropagation();
            e.preventDefault();
            const [tipo, ref] = b.dataset.guardar.split('|');
            abrirGuardar(b, tipo, ref, datosParaGuardar(tipo, buscarDatos(tipo, ref)));
        }, true);
    }

    // ================================================================== vista: colecciones
    async function vistaColecciones() {
        const hoja = $('kg-hoja');
        hoja.innerHTML = `<div class="kg-pagina">
            <div class="kg-fila"><h1 class="kg-h1" style="flex:1;">Colecciones</h1>
              <button class="kg-btn solido" id="kg-nueva-coleccion"><i class="fa-solid fa-plus"></i> Nueva colección</button></div>
            <div class="kg-ayuda" style="margin-bottom:12px;">Agrupa notebooks, datasets y competiciones por tema o proyecto. Se ven sin conexión y puedes exportar sus notebooks explicados a un PDF.</div>
            <div id="kg-nueva-form"></div>
            <div id="kg-colecciones"><div class="kg-ayuda"><i class="fa-solid fa-spinner fa-spin"></i> Cargando…</div></div></div>`;
        $('kg-nueva-coleccion').onclick = () => formularioColeccion(null);
        await cargarGuardados();
        const c = $('kg-colecciones');
        if (!c) return;
        const cols = estado.colecciones || [];
        if (!cols.length) {
            c.innerHTML = `<div class="kg-vacio" style="margin:30px auto;"><i class="fa-regular fa-bookmark" style="font-size:36px; color:#20beff;"></i>
                <h2>Todavía no hay colecciones</h2><p>Pulsa <i class="fa-regular fa-bookmark"></i> en cualquier notebook, dataset o competición para guardarlo, o crea una colección aquí.</p></div>`;
            return;
        }
        c.innerHTML = `<div class="kg-rejilla">${cols.map(col => `
            <div class="kg-tarjeta" data-coleccion="${col.id}">
              <div class="kg-mosaico" style="--color:${esc(col.color)};">${col.portadas.length
                ? col.portadas.map(u => `<img src="${esc(u)}" alt="" loading="lazy" onerror="this.remove()">`).join('')
                : `<i class="fa-solid fa-layer-group"></i>`}</div>
              <div class="kg-tarjeta-cuerpo">
                <div class="kg-fila" style="flex-wrap:nowrap;"><span class="kg-punto" style="background:${esc(col.color)};"></span><b style="flex:1;">${esc(col.nombre)}</b></div>
                ${col.descripcion ? `<span class="kg-ayuda kg-dos-lineas">${esc(col.descripcion)}</span>` : ''}
                <span style="flex:1"></span>
                <div class="kg-fila kg-ayuda">${Object.entries(TIPOS_ITEM).map(([t, [ic]]) => col.cuenta[t] ? `<span><i class="fa-solid ${ic}"></i> ${col.cuenta[t]}</span>` : '').join('')}
                  <span style="flex:1"></span><span>${fecha(col.actualizada)}</span></div></div></div>`).join('')}</div>`;
        c.querySelectorAll('[data-coleccion]').forEach(el => el.onclick = () => ir({ tipo: 'coleccion', ref: el.dataset.coleccion }));
    }

    function formularioColeccion(col, alGuardar) {
        const zona = $('kg-nueva-form') || $('kg-col-editar');
        if (!zona) return;
        const colores = estado.coloresColeccion || ['#20beff'];
        let color = (col && col.color) || colores[(estado.colecciones || []).length % colores.length];
        zona.innerHTML = `<div class="kg-profesor" style="margin-bottom:14px;">
            <div class="kg-fila" style="flex-wrap:nowrap;"><input class="kg-campo" id="kg-col-nombre" placeholder="Nombre: Visión por computador, EDA, Mi TFM…" maxlength="80" value="${esc(col ? col.nombre : '')}">
              <div class="kg-fila" id="kg-col-colores" style="flex-wrap:nowrap;">${colores.map(c => `<button class="kg-color ${c === color ? 'activo' : ''}" data-color="${c}" style="background:${c};"></button>`).join('')}</div></div>
            <textarea class="kg-campo" id="kg-col-desc" rows="2" style="margin-top:8px;" placeholder="Descripción (opcional)" maxlength="400">${esc(col ? col.descripcion : '')}</textarea>
            <div class="kg-error" id="kg-col-form-error" hidden style="margin-top:6px;"></div>
            <div class="kg-fila" style="margin-top:8px; justify-content:flex-end;"><button class="kg-btn" data-cancelar>Cancelar</button>
              <button class="kg-btn solido" data-guardar-col>${col ? 'Guardar cambios' : 'Crear colección'}</button></div></div>`;
        zona.querySelectorAll('[data-color]').forEach(b => b.onclick = () => {
            color = b.dataset.color;
            zona.querySelectorAll('[data-color]').forEach(x => x.classList.toggle('activo', x === b));
        });
        zona.querySelector('[data-cancelar]').onclick = () => { zona.innerHTML = ''; };
        const guardar = async () => {
            const cuerpo = { nombre: $('kg-col-nombre').value, descripcion: $('kg-col-desc').value, color };
            try {
                if (col) await enviar(`/api/kaggle/colecciones/${col.id}`, cuerpo, 'PATCH');
                else await enviar('/api/kaggle/colecciones', cuerpo);
                zona.innerHTML = '';
                if (alGuardar) alGuardar(); else vistaColecciones();
            } catch (e) { const er = $('kg-col-form-error'); er.hidden = false; er.textContent = e.message; }
        };
        zona.querySelector('[data-guardar-col]').onclick = guardar;
        $('kg-col-nombre').onkeydown = (e) => { if (e.key === 'Enter') guardar(); };
        $('kg-col-nombre').focus();
    }

    async function abrirColeccion(id) {
        const hoja = $('kg-hoja');
        hoja.innerHTML = `<div class="kg-pagina">${barraVolver()}<div class="kg-ayuda"><i class="fa-solid fa-spinner fa-spin"></i> Cargando…</div></div>`;
        conectarVolver(hoja);
        let col;
        try { col = await json(`/api/kaggle/colecciones/${encodeURIComponent(id)}`); } catch (e) {
            hoja.innerHTML = `<div class="kg-pagina">${barraVolver()}<div class="kg-error">${esc(e.message)}</div></div>`;
            conectarVolver(hoja);
            return;
        }
        estado.coleccion = col;
        const filtro = estado.filtroColeccion || '';
        const items = col.items.filter(it => !filtro || it.tipo === filtro);
        hoja.innerHTML = `<div class="kg-pagina">
            ${barraVolver()}
            <div class="kg-heroe">
              <div class="kg-mosaico" style="--color:${esc(col.color)}; width:170px; height:120px; border-radius:10px; flex:none;">${col.portadas.length
                ? col.portadas.map(u => `<img src="${esc(u)}" alt="" onerror="this.remove()">`).join('') : '<i class="fa-solid fa-layer-group"></i>'}</div>
              <div style="flex:1; min-width:0;">
                <div class="kg-ayuda" style="text-transform:uppercase; letter-spacing:.5px;">Colección</div>
                <h1 class="kg-h1">${esc(col.nombre)}</h1>
                <div class="kg-md" style="color:var(--text-muted);">${esc(col.descripcion || '')}</div>
                <div class="kg-fila kg-ayuda" style="margin-top:6px;">${col.total} elementos · creada ${fecha(col.creada)} · actualizada ${fecha(col.actualizada)}</div>
              </div>
              <div style="display:flex; flex-direction:column; gap:6px; min-width:210px;">
                <button class="kg-btn solido" id="kg-col-pdf" ${col.cuenta.notebook ? '' : 'disabled title="La colección no tiene notebooks"'} style="justify-content:center;"><i class="fa-solid fa-file-pdf"></i> PDF de sus notebooks</button>
                <button class="kg-btn" id="kg-col-editar-btn" style="justify-content:center;"><i class="fa-solid fa-pen"></i> Editar</button>
                <button class="kg-btn" id="kg-col-borrar" style="justify-content:center; color:var(--accent-red);"><i class="fa-solid fa-trash"></i> Borrar colección</button>
              </div>
            </div>
            <div id="kg-col-editar" style="margin-top:12px;"></div>
            <div class="kg-fila" style="margin:16px 0 6px;" id="kg-col-filtro">
              ${[['', `Todo (${col.total})`], ...Object.entries(TIPOS_ITEM).map(([t, [, n]]) => [t, `${n}s (${col.cuenta[t] || 0})`])].map(([v, t]) =>
                `<button class="kg-chip ${filtro === v ? 'activa' : ''}" data-valor="${v}">${t.replace('Competicións', 'Competiciones')}</button>`).join('')}
            </div>
            <div id="kg-col-items">${items.map((it, i) => `
              <div class="kg-lista-fila" data-i="${i}" style="align-items:flex-start;">
                <div class="kg-miniatura">${it.imagen ? `<img src="${esc(it.imagen)}" alt="" onerror="this.remove()">` : ''}<i class="fa-solid ${TIPOS_ITEM[it.tipo][0]}"></i></div>
                <div style="flex:1; min-width:0;">
                  <b style="color:#fff; font-size:13px;">${esc(it.titulo)}</b>
                  <div class="kg-ayuda">${TIPOS_ITEM[it.tipo][1]}${it.autor ? ' · ' + esc(it.autor) : ''}${it.votos != null ? ` · <i class="fa-solid fa-caret-up"></i> ${miles(it.votos)}` : ''} · guardado ${fecha(it.anadido)}</div>
                  <div class="kg-nota" data-nota="${i}">${it.nota ? esc(it.nota) : '<span class="kg-ayuda">Añadir una nota…</span>'}</div>
                </div>
                <button class="kg-btn" data-quitar="${i}" title="Quitar de la colección"><i class="fa-solid fa-xmark"></i></button>
              </div>`).join('') || '<div class="kg-ayuda" style="margin-top:10px;">Nada por aquí todavía. Guarda cosas con <i class="fa-regular fa-bookmark"></i>.</div>'}</div>
            <div id="kg-pdf-resultado"></div>
          </div>`;
        conectarVolver(hoja);
        $('kg-col-filtro').onclick = (e) => {
            const chip = e.target.closest('[data-valor]');
            if (!chip) return;
            estado.filtroColeccion = chip.dataset.valor;
            abrirColeccion(id);
        };
        $('kg-col-pdf').onclick = () => dialogoPdf({ coleccion: col.id, titulo: col.nombre });
        $('kg-col-editar-btn').onclick = () => formularioColeccion(col, () => abrirColeccion(id));
        const borrar = $('kg-col-borrar');
        borrar.onclick = async () => {
            if (!borrar.dataset.seguro) {
                borrar.dataset.seguro = '1';
                borrar.innerHTML = '<i class="fa-solid fa-triangle-exclamation"></i> Pulsa otra vez para borrarla';
                setTimeout(() => { if (borrar.isConnected) { delete borrar.dataset.seguro; borrar.innerHTML = '<i class="fa-solid fa-trash"></i> Borrar colección'; } }, 4000);
                return;
            }
            await fetch(`/api/kaggle/colecciones/${col.id}`, { method: 'DELETE' });
            await cargarGuardados();
            estado.pila = estado.pila.filter(v => !(v.tipo === 'coleccion' && v.ref === col.id));
            ir({ tipo: 'colecciones' }, false);
        };
        const lista = $('kg-col-items');
        lista.querySelectorAll('[data-i]').forEach(fila => fila.onclick = (e) => {
            if (e.target.closest('[data-quitar], [data-nota], textarea, button')) return;
            const it = items[+fila.dataset.i];
            ir({ tipo: it.tipo, ref: it.ref });
        });
        lista.querySelectorAll('[data-quitar]').forEach(b => b.onclick = async (e) => {
            e.stopPropagation();
            const it = items[+b.dataset.quitar];
            await fetch(`/api/kaggle/colecciones/${col.id}/items?${new URLSearchParams({ tipo: it.tipo, ref: it.ref })}`, { method: 'DELETE' });
            await cargarGuardados();
            abrirColeccion(id);
        });
        lista.querySelectorAll('[data-nota]').forEach(n => n.onclick = (e) => {
            e.stopPropagation();
            if (n.querySelector('textarea')) return;
            const it = items[+n.dataset.nota];
            n.innerHTML = `<textarea class="kg-campo" rows="2" maxlength="2000" placeholder="Por qué lo guardaste, qué aprender de él…">${esc(it.nota || '')}</textarea>
                <div class="kg-fila" style="margin-top:4px;"><button class="kg-btn solido" data-ok>Guardar nota</button><button class="kg-btn" data-no>Cancelar</button></div>`;
            const area = n.querySelector('textarea');
            area.focus();
            n.querySelector('[data-no]').onclick = (ev) => { ev.stopPropagation(); abrirColeccion(id); };
            n.querySelector('[data-ok]').onclick = async (ev) => {
                ev.stopPropagation();
                await enviar(`/api/kaggle/colecciones/${col.id}/items`, { tipo: it.tipo, ref: it.ref, nota: area.value }, 'PATCH');
                abrirColeccion(id);
            };
        });
    }

    // ================================================================== PDF
    function dialogoPdf({ ref, coleccion, titulo }) {
        const capa = document.createElement('div');
        capa.id = 'kg-dialogo-pdf';
        capa.className = 'kg-capa';
        const conChat = !coleccion && estado.chat.filter(m => m.texto).length > 0;
        capa.innerHTML = `<div class="kg-dialogo" style="width:560px;">
            <div class="kg-fila" style="margin-bottom:10px;"><i class="fa-solid fa-file-pdf" style="color:#f38ba8; font-size:18px;"></i>
              <b style="color:#fff; font-size:15px; flex:1;">Exportar a PDF</b><button class="kg-btn" data-cerrar><i class="fa-solid fa-xmark"></i></button></div>
            <div class="kg-ayuda" style="margin-bottom:10px;">${coleccion ? `Todos los notebooks de «${esc(titulo)}» en un solo PDF, con índice.` : `«${esc(titulo)}» con el código de cada celda y la explicación del profesor debajo.`}
              Se usan las explicaciones que ya pediste (no se gasta el modelo).</div>
            <label class="kg-opcion"><input type="radio" name="kg-pdf-celdas" value="todas" checked> Todo el notebook <span class="kg-ayuda">· las celdas sin explicar salen solo con su código</span></label>
            <label class="kg-opcion"><input type="radio" name="kg-pdf-celdas" value="explicadas"> Solo las celdas explicadas</label>
            <label class="kg-opcion"><input type="checkbox" id="kg-pdf-guia" checked> Incluir la guía de lectura</label>
            <label class="kg-opcion"><input type="checkbox" id="kg-pdf-salidas" checked> Incluir las salidas guardadas</label>
            ${conChat ? '<label class="kg-opcion"><input type="checkbox" id="kg-pdf-chat" checked> Incluir las preguntas que hiciste al profesor</label>' : ''}
            <label class="kg-opcion">Si una celda tiene varias explicaciones, preferir el nivel
              <select class="kg-campo" id="kg-pdf-nivel" style="width:auto; margin-left:6px;">${['', 'principiante', 'intermedio', 'avanzado'].map(n => `<option value="${n}" ${n === (coleccion ? '' : estado.nivel) ? 'selected' : ''}>${n || 'el más reciente'}</option>`).join('')}</select></label>
            <div id="kg-pdf-estado" style="margin-top:10px;"></div>
            <div class="kg-fila" style="margin-top:12px; justify-content:flex-end;"><button class="kg-btn" data-cerrar>Cerrar</button>
              <button class="kg-btn solido" id="kg-pdf-generar"><i class="fa-solid fa-file-export"></i> Generar PDF</button></div>
          </div>`;
        document.body.appendChild(capa);
        const cerrar = () => capa.remove();
        capa.addEventListener('mousedown', (e) => { if (e.target === capa) cerrar(); });
        capa.querySelectorAll('[data-cerrar]').forEach(b => b.onclick = cerrar);
        $('kg-pdf-generar').onclick = async () => {
            const boton = $('kg-pdf-generar');
            const zona = $('kg-pdf-estado');
            boton.disabled = true;
            zona.innerHTML = '<div class="kg-ayuda"><i class="fa-solid fa-spinner fa-spin"></i> Maquetando el PDF…</div>';
            const cuerpo = {
                ref: ref || null, coleccion: coleccion || null, nivel: $('kg-pdf-nivel').value || null,
                solo_explicadas: capa.querySelector('input[name="kg-pdf-celdas"]:checked').value === 'explicadas',
                guia: $('kg-pdf-guia').checked, salidas: $('kg-pdf-salidas').checked,
                chat: $('kg-pdf-chat') && $('kg-pdf-chat').checked ? estado.chat.map(m => ({ rol: m.rol, texto: m.texto })) : null,
            };
            try {
                const r = await enviar('/api/kaggle/pdf', cuerpo);
                const url = `/api/kaggle/pdf?ruta=${encodeURIComponent(r.ruta)}`;
                zona.innerHTML = `<div class="kg-ayuda" style="color:var(--accent-green);"><i class="fa-solid fa-check"></i> Listo: <b>${esc(r.relativa)}</b> ·
                    ${r.paginas} páginas · ${r.explicadas} celdas explicadas${r.notebooks ? ` · ${r.notebooks} notebooks` : ''} · ${tam(r.bytes)}</div>
                  ${r.no_incluidos && r.no_incluidos.length ? `<div class="kg-ayuda" style="color:var(--accent-yellow);">No se pudieron incluir: ${esc(r.no_incluidos.join('; '))}</div>` : ''}
                  <div class="kg-fila" style="margin-top:8px;">
                    <button class="kg-btn azul" data-pdf-ver><i class="fa-solid fa-eye"></i> Vista previa</button>
                    <button class="kg-btn" data-pdf-abrir><i class="fa-solid fa-up-right-from-square"></i> Abrir con el visor</button>
                    <a class="kg-btn" href="${url}&descargar=true" download="${esc(r.relativa.split('/').pop())}"><i class="fa-solid fa-floppy-disk"></i> Guardar como…</a>
                    <button class="kg-btn" data-pdf-carpeta><i class="fa-solid fa-folder-open"></i> Mostrar en la carpeta</button></div>
                  <div id="kg-pdf-previa"></div>`;
                zona.querySelector('[data-pdf-ver]').onclick = () => {
                    $('kg-pdf-previa').innerHTML = `<iframe src="${url}" style="width:100%; height:55vh; border:1px solid var(--border-color); border-radius:8px; margin-top:8px; background:#fff;"></iframe>`;
                    capa.querySelector('.kg-dialogo').style.width = 'min(1000px, 94vw)';
                };
                zona.querySelector('[data-pdf-abrir]').onclick = () => enviar('/api/kaggle/pdf/abrir', { ref: r.ruta }).catch(e => { zona.insertAdjacentHTML('beforeend', `<div class="kg-error" style="margin-top:6px;">${esc(e.message)}</div>`); });
                zona.querySelector('[data-pdf-carpeta]').onclick = () => enviar('/api/ide/mostrar-en-sistema', { path: r.ruta }).catch(() => {});
                if (window.fileTreeMgr) window.fileTreeMgr.loadTree();
            } catch (e) {
                zona.innerHTML = `<div class="kg-error">${esc(e.message)}</div>`;
            }
            boton.disabled = false;
        };
    }

    // ================================================================== mis lecturas y mis datos
    async function vistaLecturas() {
        const hoja = $('kg-hoja');
        hoja.innerHTML = `<div class="kg-pagina"><h1 class="kg-h1">Mis lecturas</h1>
            <div class="kg-ayuda" style="margin-bottom:12px;">Los notebooks que estás leyendo con el profesor. Pulsa uno para seguir donde lo dejaste.</div>
            <div id="kg-lecturas"><div class="kg-ayuda"><i class="fa-solid fa-spinner fa-spin"></i> Cargando…</div></div></div>`;
        let lecturas = [];
        try { lecturas = (await json('/api/kaggle/lecturas')).lecturas; } catch (e) { $('kg-lecturas').innerHTML = `<div class="kg-error">${esc(e.message)}</div>`; return; }
        const c = $('kg-lecturas');
        if (!c) return;
        if (!lecturas.length) { c.innerHTML = '<div class="kg-ayuda">Aún no leíste ningún notebook con el profesor. Empieza en <a href="#" data-ir="codigo">Código</a>.</div>'; }
        else c.innerHTML = lecturas.map((l, i) => `
            <div class="kg-lista-fila" data-i="${i}">
              <div class="kg-avatar"><i class="fa-solid fa-book-open"></i></div>
              <div style="flex:1; min-width:0;"><b style="color:#fff;">${esc(l.titulo)}</b>
                <div class="kg-ayuda" style="margin:3px 0;">${l.leidas} de ${l.total} celdas · ${fecha(l.ultima)}</div>
                <div class="kg-barra" style="max-width:360px;"><div style="width:${l.total ? Math.round(100 * l.leidas / l.total) : 0}%;"></div></div></div>
              <span class="kg-btn">Seguir</span></div>`).join('');
        c.querySelectorAll('[data-i]').forEach(el => el.onclick = () => {
            const l = lecturas[+el.dataset.i];
            ir({ tipo: 'notebook', ref: l.ref, celda: l.ultima_celda });
        });
        c.querySelectorAll('[data-ir]').forEach(a => a.onclick = (e) => { e.preventDefault(); ir({ tipo: a.dataset.ir }); });
    }

    async function vistaMisDatos() {
        const hoja = $('kg-hoja');
        hoja.innerHTML = `<div class="kg-pagina"><h1 class="kg-h1">Mis datos</h1>
            <div class="kg-ayuda" style="margin-bottom:12px;">Lo que bajaste de Kaggle al proyecto abierto (carpeta <code>kaggle_datos/</code>). Los notebooks guardados en el proyecto los encuentran solos.</div>
            <div id="kg-misdatos"><div class="kg-ayuda"><i class="fa-solid fa-spinner fa-spin"></i> Cargando…</div></div></div>`;
        let datos = [];
        try { datos = (await json('/api/kaggle/mis_datos')).datos; } catch (e) { $('kg-misdatos').innerHTML = `<div class="kg-error">${esc(e.message)}</div>`; return; }
        const c = $('kg-misdatos');
        if (!c) return;
        if (!datos.length) { c.innerHTML = '<div class="kg-ayuda">Todavía no hay datos en este proyecto. Abre un <a href="#" data-ir="datasets">dataset</a> y pulsa «Descargar al proyecto».</div>'; }
        else c.innerHTML = `<div class="kg-rejilla">${datos.map((d, i) => `
            <div class="kg-tarjeta" data-i="${i}"><div class="kg-tarjeta-cuerpo">
              <div class="kg-fila"><i class="fa-solid ${d.tipo === 'competicion' ? 'fa-trophy' : 'fa-table'}" style="color:#20beff;"></i><b style="flex:1;">${esc(d.nombre)}</b></div>
              <span class="kg-ayuda">${esc(d.relativa)}</span>
              <span class="kg-ayuda">${d.archivos.length} archivos · ${tam(d.bytes)}${d.fecha ? ' · ' + fecha(d.fecha) : ''}</span></div></div>`).join('')}</div>`;
        c.querySelectorAll('[data-i]').forEach(el => el.onclick = () => {
            const d = datos[+el.dataset.i];
            if (d.tipo) ir({ tipo: d.tipo, ref: d.ref });
        });
        c.querySelectorAll('[data-ir]').forEach(a => a.onclick = (e) => { e.preventDefault(); ir({ tipo: a.dataset.ir }); });
    }

    // ================================================================== ficha de dataset o competición
    async function abrirFicha(tipo, ref, pestana) {
        const hoja = $('kg-hoja');
        hoja.innerHTML = `<div class="kg-pagina">${barraVolver()}<div class="kg-vacio"><i class="fa-solid fa-spinner fa-spin fa-2x" style="color:#20beff;"></i><p>Cargando de Kaggle…</p></div></div>`;
        conectarVolver(hoja);
        try {
            estado.ficha = await json(`/api/kaggle/${tipo === 'dataset' ? 'dataset' : 'competicion'}?ref=${encodeURIComponent(ref)}`);
        } catch (e) {
            hoja.innerHTML = `<div class="kg-pagina">${barraVolver()}<div class="kg-error">${esc(e.message)}</div></div>`;
            conectarVolver(hoja);
            return;
        }
        // La referencia buena (un enlace pegado se normaliza) para volver y recordar
        estado.vista.ref = estado.ficha.ref;
        guardarLocal('prig_kaggle_vista', JSON.stringify({ tipo, ref: estado.ficha.ref }));
        estado.fichaPestana = pestana || 'datos';
        estado.archivoActivo = null;
        pintarFicha();
    }

    function pintarFicha() {
        const f = estado.ficha;
        const esDataset = f.tipo === 'dataset';
        const hoja = $('kg-hoja');
        const loc = f.local;
        hoja.innerHTML = `<div class="kg-pagina">
            ${barraVolver()}
            <div class="kg-heroe">
              ${portada(f.imagen, esDataset ? 'fa-table' : 'fa-trophy')}
              <div style="flex:1; min-width:0;">
                <div class="kg-ayuda" style="text-transform:uppercase; letter-spacing:.5px;">${esDataset ? 'Dataset' : 'Competición' + (f.categoria ? ' · ' + esc(f.categoria) : '')}</div>
                <h1 class="kg-h1">${esc(f.titulo)}</h1>
                <div class="kg-md" style="font-size:13.5px; color:var(--text-muted);">${esc(f.subtitulo || '')}</div>
                <div class="kg-fila kg-ayuda" style="margin-top:6px;">
                  ${esDataset ? `<span>${esc(f.autor || '')}</span> · <span>Actualizado ${fecha(f.actualizado)}</span> · <span>Versión ${esc(f.version || '')}</span>`
                              : `<span>${esc(f.organizador || '')}</span>${cierre(f) ? ' · ' + cierre(f) : ''}`}
                </div>
                <div class="kg-fila" style="margin-top:8px;">${(f.etiquetas || []).map(t => `<span class="kg-etiqueta">${esc(t)}</span>`).join('')}</div>
              </div>
              <div style="display:flex; flex-direction:column; gap:6px; align-items:stretch; min-width:200px;">
                ${loc ? `<span class="kg-btn" style="color:var(--accent-green); justify-content:center;"><i class="fa-solid fa-circle-check"></i> En el proyecto · ${tam(loc.bytes)}</span>` : ''}
                <button class="kg-btn ${loc ? '' : 'solido'}" id="kg-descargar" style="justify-content:center;"><i class="fa-solid fa-download"></i> ${loc ? 'Volver a descargar' : 'Descargar al proyecto'}${f.bytes ? ` (${tam(f.bytes)})` : ''}</button>
                <button class="kg-btn" data-guardar="${esc(f.tipo)}|${esc(f.ref)}" style="justify-content:center;"><i class="fa-regular fa-bookmark"></i> <span>Guardar</span></button>
                <a class="kg-btn" href="${esc(f.url)}" target="_blank" rel="noopener noreferrer" style="justify-content:center;"><i class="fa-solid fa-arrow-up-right-from-square"></i> Ver en kaggle.com</a>
                ${!esDataset && f.reglas ? `<a class="kg-btn" href="${esc(f.reglas)}" target="_blank" rel="noopener noreferrer" style="justify-content:center;"><i class="fa-solid fa-scale-balanced"></i> Reglas</a>` : ''}
              </div>
            </div>
            <div id="kg-descarga-estado" style="margin-top:10px;"></div>
            <div class="kg-info" style="margin-top:14px;">${infoFicha(f).map(([t, v]) => `<div><span>${t}</span><b>${v}</b></div>`).join('')}</div>
            <div class="kg-pestanas2" id="kg-ficha-pestanas">
              ${[['datos', esDataset ? 'Datos' : 'Resumen y datos'], ['codigo', 'Código'], ['profesor', 'Profesor']].map(([id, t]) =>
                `<button data-pestana="${id}" class="${estado.fichaPestana === id ? 'activa' : ''}">${t}</button>`).join('')}
            </div>
            <div id="kg-ficha-cuerpo"></div></div>`;
        conectarVolver(hoja);
        $('kg-descargar').onclick = descargarDatos;
        refrescarMarcas();
        $('kg-ficha-pestanas').onclick = (e) => {
            const b = e.target.closest('[data-pestana]');
            if (!b) return;
            estado.fichaPestana = b.dataset.pestana;
            document.querySelectorAll('#kg-ficha-pestanas button').forEach(x => x.classList.toggle('activa', x === b));
            pintarPestanaFicha();
        };
        pintarPestanaFicha();
    }

    function infoFicha(f) {
        if (f.tipo === 'dataset') {
            return [['Usabilidad', `${f.usabilidad} / 10`], ['Tamaño', tam(f.bytes)], ['Archivos', (f.archivos || []).length],
                    ['Votos', miles(f.votos)], ['Descargas', miles(f.descargas)], ['Notebooks', miles(f.notebooks)], ['Licencia', esc(f.licencia || '—')]];
        }
        return [['Métrica', esc(f.metrica || '—')], ['Premio', esc(f.premio || '—')], ['Equipos', miles(f.equipos)],
                ['Cierre', f.cierre ? new Date(f.cierre).toLocaleDateString('es') : '—'], ['Equipo máximo', f.max_equipo || '—'],
                ['Envíos al día', f.envios_diarios || '—'], ['Datos', tam(f.bytes)]];
    }

    function pintarPestanaFicha() {
        const c = $('kg-ficha-cuerpo');
        if (!c) return;
        if (estado.fichaPestana === 'codigo') return pestanaCodigo(c);
        if (estado.fichaPestana === 'profesor') return pestanaProfesor(c);
        pestanaDatos(c);
    }

    // ------------------------------------------------------------------ pestaña Datos: descripción + explorador
    function archivosFicha() {
        const f = estado.ficha;
        if (f.local && f.local.archivos.length) {
            return f.local.archivos.map(a => ({ nombre: a.relativa, bytes: a.bytes, ruta: a.ruta,
                                                columnas: ((f.archivos || []).find(x => x.nombre === a.relativa.split('/').pop()) || {}).columnas || [] }));
        }
        return (f.archivos || []).map(a => ({ ...a, ruta: null }));
    }

    function iconoArchivo(nombre) {
        const ext = (nombre.split('.').pop() || '').toLowerCase();
        return { csv: 'fa-file-csv', tsv: 'fa-file-csv', json: 'fa-file-code', parquet: 'fa-database', sqlite: 'fa-database', db: 'fa-database',
                 png: 'fa-file-image', jpg: 'fa-file-image', jpeg: 'fa-file-image', zip: 'fa-file-zipper', txt: 'fa-file-lines', md: 'fa-file-lines' }[ext] || 'fa-file';
    }

    function pestanaDatos(c) {
        const f = estado.ficha;
        const archivos = archivosFicha();
        if (estado.archivoActivo == null) {
            // Como Kaggle: se abre la tabla principal (la mayor que no sea un ejemplo de envío)
            let tabla = -1;
            archivos.forEach((a, i) => {
                if (/\.(csv|tsv)$/i.test(a.nombre) && !/submission/i.test(a.nombre) && (tabla < 0 || (a.bytes || 0) > (archivos[tabla].bytes || 0))) tabla = i;
            });
            estado.archivoActivo = Math.max(0, tabla);
        }
        c.innerHTML = `
          ${f.descripcion ? `<div class="kg-md" id="kg-descripcion" style="max-height:340px; overflow:hidden; position:relative;"></div>
            <button class="kg-btn" id="kg-mas-desc" style="margin:6px 0 16px;">Leer toda la descripción</button>` : ''}
          <div class="kg-fila" style="margin-bottom:8px;"><b style="color:#fff; font-size:14px;">Explorador de datos</b>
            <span class="kg-ayuda">${archivos.length} archivos${f.local ? ' · en ' + esc(f.local.relativa) : ' · descárgalos para ver su contenido'}</span></div>
          <div class="kg-datos-rej">
            <div class="kg-archivos">${archivos.map((a, i) => `<div data-archivo="${i}" class="${i === estado.archivoActivo ? 'activo' : ''}" title="${esc(a.nombre)}">
                <i class="fa-solid ${iconoArchivo(a.nombre)}"></i><span style="flex:1; min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">${esc(a.nombre)}</span>
                <span class="kg-ayuda">${tam(a.bytes)}</span></div>`).join('') || '<div class="kg-ayuda" style="padding:10px;">Sin archivos.</div>'}</div>
            <div id="kg-previa" style="min-width:0;"></div>
          </div>`;
        if (f.descripcion) {
            pintarMd($('kg-descripcion'), f.descripcion);
            $('kg-mas-desc').onclick = (e) => { $('kg-descripcion').style.maxHeight = 'none'; e.target.remove(); };
        }
        c.querySelector('.kg-archivos').onclick = (e) => {
            const el = e.target.closest('[data-archivo]');
            if (!el) return;
            estado.archivoActivo = +el.dataset.archivo;
            c.querySelectorAll('[data-archivo]').forEach(x => x.classList.toggle('activo', x === el));
            pintarPrevia(archivos[estado.archivoActivo]);
        };
        if (archivos.length) pintarPrevia(archivos[estado.archivoActivo]);
    }

    async function pintarPrevia(a) {
        const c = $('kg-previa');
        if (!c || !a) return;
        if (!a.ruta) {
            c.innerHTML = `<div class="kg-profesor"><b style="color:#fff;">${esc(a.nombre)}</b> · <span class="kg-ayuda">${tam(a.bytes)}</span>
                ${a.columnas && a.columnas.length ? `<div class="kg-ayuda" style="margin:8px 0 4px;">Columnas (según Kaggle):</div>
                  <div class="kg-fila">${a.columnas.map(col => `<span class="kg-etiqueta" title="${esc(col.descripcion)}">${esc(col.nombre)} · ${esc(col.tipo || '')}</span>`).join('')}</div>` : ''}
                <div class="kg-ayuda" style="margin-top:10px;">Descarga los datos al proyecto para ver las filas, el resumen de cada columna y que el profesor los analice con cifras reales.</div>
                <button class="kg-btn solido" style="margin-top:8px;" data-descargar><i class="fa-solid fa-download"></i> Descargar al proyecto</button></div>`;
            c.querySelector('[data-descargar]').onclick = descargarDatos;
            return;
        }
        c.innerHTML = '<div class="kg-ayuda"><i class="fa-solid fa-spinner fa-spin"></i> Leyendo el archivo…</div>';
        let p;
        try { p = await json(`/api/kaggle/previa?ruta=${encodeURIComponent(a.ruta)}`); } catch (e) { c.innerHTML = `<div class="kg-error">${esc(e.message)}</div>`; return; }
        if (!$('kg-previa')) return;
        if (p.columnas) {
            c.innerHTML = `<div class="kg-fila" style="margin-bottom:10px;"><b style="color:#fff;">${esc(p.nombre)}</b>
                  <span class="kg-etiqueta">${miles(p.total_filas)} filas</span><span class="kg-etiqueta">${p.columnas.length} columnas</span><span class="kg-etiqueta">${tam(p.bytes)}</span>
                  ${p.analizadas < p.total_filas ? `<span class="kg-ayuda">resumen de las primeras ${miles(p.analizadas)} filas</span>` : ''}
                  <span style="flex:1"></span><button class="kg-btn" data-vista="tabla"><i class="fa-solid fa-table-list"></i> Filas</button><button class="kg-btn" data-vista="columnas"><i class="fa-solid fa-chart-simple"></i> Columnas</button></div>
                <div id="kg-previa-cuerpo"></div>`;
            const pintar = (vista) => {
                estado.previaVista = vista;
                const cuerpo = $('kg-previa-cuerpo');
                cuerpo.innerHTML = vista === 'tabla'
                    ? `<div style="overflow:auto; max-height:420px; border:1px solid var(--border-color); border-radius:8px;"><table class="kg-tabla">
                        <thead><tr><th>#</th>${p.columnas.map(col => `<th title="${esc(col.tipo)}">${col.tipo === 'número' ? '<span style="color:#20beff;">#</span>' : '<span style="color:var(--accent-purple);">A</span>'} ${esc(col.nombre)}</th>`).join('')}</tr></thead>
                        <tbody>${p.filas.map((f, i) => `<tr><td class="kg-ayuda">${i}</td>${p.columnas.map((_, j) => `<td title="${esc(f[j] ?? '')}">${esc(f[j] ?? '')}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`
                    : `<div class="kg-columnas">${p.columnas.map(columnaHtml).join('')}</div>`;
            };
            c.querySelectorAll('[data-vista]').forEach(b => b.onclick = () => pintar(b.dataset.vista));
            pintar(estado.previaVista || 'columnas');
        } else if (p.imagen) {
            c.innerHTML = `<b style="color:#fff;">${esc(p.nombre)}</b><div style="margin-top:8px;"><img src="/api/kaggle/archivo?ruta=${encodeURIComponent(a.ruta)}" style="max-width:100%; max-height:420px; border-radius:8px;"></div>`;
        } else if (p.texto != null) {
            c.innerHTML = `<b style="color:#fff;">${esc(p.nombre)}</b><pre class="kg-codigo" style="margin-top:8px; max-height:420px; white-space:pre-wrap;">${esc(p.texto)}</pre>`;
        } else {
            c.innerHTML = `<b style="color:#fff;">${esc(p.nombre)}</b> · <span class="kg-ayuda">${tam(p.bytes)} · ${esc(p.nota || '')}</span>`;
        }
    }

    function columnaHtml(col) {
        const max = Math.max(1, ...col.frecuentes.map(f => f.veces));
        const num = (x) => x == null ? '—' : Math.abs(x) >= 1000 ? miles(Math.round(x)) : (+x.toFixed(3)).toString();
        return `<div class="kg-col">
            <div class="kg-fila" style="flex-wrap:nowrap;">${col.tipo === 'número' ? '<span style="color:#20beff; font-weight:700;">#</span>' : '<span style="color:var(--accent-purple); font-weight:700;">A</span>'}
              <b style="flex:1;">${esc(col.nombre)}</b></div>
            <div class="kg-ayuda" style="margin-top:4px;">${col.tipo} · ${col.distintos} distintos</div>
            <div class="kg-ayuda" style="color:${col.faltan_pct > 20 ? 'var(--accent-red)' : col.faltan_pct > 0 ? 'var(--accent-yellow)' : 'var(--accent-green)'};">
              ${col.faltan_pct ? `faltan ${col.faltan_pct}% (${miles(col.faltan)})` : 'sin valores faltantes'}</div>
            ${col.tipo === 'número' ? `<div class="kg-ayuda" style="margin-top:3px;">mín ${num(col.min)} · media ${num(col.media)} · máx ${num(col.max)}</div>` : ''}
            ${col.frecuentes.length ? `<div class="kg-frec">${col.frecuentes.map(f => `<span class="kg-ayuda" style="overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">${esc(f.valor)}</span>
                <span class="kg-ayuda">${miles(f.veces)}</span><div class="barra"><div style="width:${Math.round(100 * f.veces / max)}%;"></div></div>`).join('')}</div>` : ''}
          </div>`;
    }

    // ------------------------------------------------------------------ descargar al proyecto
    async function descargarDatos() {
        const f = estado.ficha;
        const zona = $('kg-descarga-estado');
        const boton = $('kg-descargar');
        if (!zona || estado.descargando) return;
        // Más de 500 MB: se pide una segunda pulsación, sin diálogos que bloqueen la ventana
        if (f.bytes > 500 * 1024 * 1024 && !zona.dataset.confirmado) {
            zona.dataset.confirmado = '1';
            zona.innerHTML = `<div class="kg-profesor"><b style="color:#fff;">Son ${tam(f.bytes)}.</b> <span class="kg-ayuda">Ocupará eso en el disco del proyecto y puede tardar.</span>
                <button class="kg-btn solido" data-seguro style="margin-left:8px;">Descargar igualmente</button></div>`;
            zona.querySelector('[data-seguro]').onclick = descargarDatos;
            return;
        }
        estado.descargando = true;
        if (boton) boton.disabled = true;
        zona.innerHTML = `<div class="kg-fila"><span class="kg-ayuda" id="kg-dl-texto" style="flex:1;"><i class="fa-solid fa-spinner fa-spin"></i> Pidiendo los datos a Kaggle…</span></div>
            <div class="kg-barra" style="margin-top:6px;"><div id="kg-dl-barra" style="width:0%;"></div></div>`;
        try {
            await flujo('/api/kaggle/descargar', { tipo: f.tipo, ref: f.ref }, (ev) => {
                if (ev.tipo !== 'progreso') return;
                const t = $('kg-dl-texto');
                if (t) t.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i> ${esc(ev.mensaje)}`;
                const b = $('kg-dl-barra');
                if (b && ev.total) b.style.width = `${Math.round(100 * ev.bytes / ev.total)}%`;
            });
            estado.descargando = false;
            estado.archivoActivo = null;
            estado.ficha = await json(`/api/kaggle/${f.tipo === 'dataset' ? 'dataset' : 'competicion'}?ref=${encodeURIComponent(f.ref)}`);
            if (estado.vista && estado.vista.ref === f.ref) {
                pintarFicha();
                const z = $('kg-descarga-estado');
                if (z) z.innerHTML = `<div class="kg-ayuda" style="color:var(--accent-green);"><i class="fa-solid fa-check"></i> Datos en <b>${esc(estado.ficha.local.relativa)}</b>. Los notebooks que guardes en el proyecto los usarán directamente.</div>`;
            }
            if (window.fileTreeMgr) window.fileTreeMgr.loadTree();
        } catch (e) {
            estado.descargando = false;
            const z = $('kg-descarga-estado');
            if (z) z.innerHTML = `<div class="kg-error">${esc(e.message)}</div>`;
            const b = $('kg-descargar');
            if (b) b.disabled = false;
        }
    }

    // ------------------------------------------------------------------ pestaña Código: notebooks que usan estos datos
    async function pestanaCodigo(c) {
        const f = estado.ficha;
        if (!conectado()) {
            c.innerHTML = `<div class="kg-profesor"><b style="color:#fff;">Para ver los notebooks que usan estos datos hace falta tu cuenta de Kaggle.</b>
                <div style="margin-top:8px;"><button class="kg-btn solido" data-conectar><i class="fa-brands fa-kaggle"></i> Conectar mi cuenta</button></div></div>`;
            c.querySelector('[data-conectar]').onclick = dialogoCuenta;
            return;
        }
        const clave = `${f.tipo}:${f.ref}`;
        const b = estado.codigoFicha[clave] || (estado.codigoFicha[clave] = { orden: 'votos', pagina: 1, items: [], hay_mas: false });
        const pintar = (cargando, error) => {
            c.innerHTML = `<div class="kg-fila" data-orden>${[['votos', 'Más votados'], ['populares', 'En tendencia'], ['recientes', 'Recientes']].map(([v, t]) =>
                    `<button class="kg-chip ${b.orden === v ? 'activa' : ''}" data-valor="${v}">${t}</button>`).join('')}</div>
                ${error ? `<div class="kg-error" style="margin-top:10px;">${esc(error)}</div>` : ''}
                <div style="margin-top:8px;">${b.items.map((n, i) => `<div data-i="${i}" style="display:contents;">${LISTAS.codigo.item(n)}</div>`).join('')}</div>
                ${cargando ? '<div class="kg-ayuda" style="margin-top:10px;"><i class="fa-solid fa-spinner fa-spin"></i> Buscando notebooks…</div>' : ''}
                ${!cargando && !error && !b.items.length ? '<div class="kg-ayuda" style="margin-top:10px;">Nadie ha publicado notebooks con estos datos todavía.</div>' : ''}
                ${!cargando && b.hay_mas ? '<button class="kg-btn" data-mas style="margin-top:10px;">Cargar más</button>' : ''}`;
            c.querySelector('[data-orden]').onclick = (e) => {
                const chip = e.target.closest('[data-valor]');
                if (!chip) return;
                Object.assign(b, { orden: chip.dataset.valor, pagina: 1, items: [], cargado: false });
                cargar();
            };
            c.querySelectorAll('[data-i]').forEach(el => { el.firstElementChild.onclick = () => ir({ tipo: 'notebook', ref: b.items[+el.dataset.i].ref }); });
            const mas = c.querySelector('[data-mas]');
            if (mas) mas.onclick = () => { b.pagina++; cargar(true); };
        };
        const cargar = async (anadir) => {
            pintar(true);
            try {
                const q = { orden: b.orden, pagina: b.pagina, [f.tipo === 'dataset' ? 'dataset' : 'competicion']: f.ref };
                const d = await json(`/api/kaggle/buscar?${new URLSearchParams(q)}`);
                b.items = anadir ? [...b.items, ...d.notebooks] : d.notebooks;
                b.hay_mas = d.hay_mas;
                b.cargado = true;
                if (estado.fichaPestana === 'codigo' && $('kg-ficha-cuerpo') === c) pintar(false);
            } catch (e) { pintar(false, e.message); }
        };
        if (b.cargado) pintar(false); else cargar();
    }

    // ------------------------------------------------------------------ pestaña Profesor: qué son estos datos y qué hacer con ellos
    function pestanaProfesor(c) {
        const f = estado.ficha;
        const guardado = estado.explicacionDatos[`${f.tipo}:${f.ref}`];
        c.innerHTML = `<div class="kg-fila" style="margin-bottom:10px;">
              <button class="kg-btn morado" id="kg-explicar-datos"><i class="fa-solid fa-user-graduate"></i> ${guardado ? 'Volver a explicar' : `Explicar ${f.tipo === 'dataset' ? 'este dataset' : 'esta competición'}`}</button>
              <select id="kg-modelo" class="kg-campo" style="width:auto; max-width:240px;" title="Modelo que te acompaña"></select>
              <span class="kg-ayuda" style="flex:1;">${f.local ? 'Con los datos descargados: usa las columnas y cifras reales.' : 'Sin los datos descargados solo ve la descripción y los nombres de archivo; <a href="#" data-descargar>descárgalos</a> para un análisis con cifras reales.'}</span></div>
            <div class="kg-profesor kg-md" id="kg-explicacion-datos" ${guardado ? '' : 'hidden'}></div>`;
        pintarSelectorModelo($('kg-modelo'));
        $('kg-modelo').onchange = (e) => { estado.modelo = e.target.value; guardarLocal('prig_kaggle_modelo', estado.modelo); };
        const dl = c.querySelector('[data-descargar]');
        if (dl) dl.onclick = (e) => { e.preventDefault(); descargarDatos(); };
        if (guardado) pintarMd($('kg-explicacion-datos'), guardado);
        $('kg-explicar-datos').onclick = () => explicarDatos(!!guardado);
    }

    async function explicarDatos(regenerar) {
        const f = estado.ficha;
        const caja = $('kg-explicacion-datos');
        const boton = $('kg-explicar-datos');
        caja.hidden = false;
        caja.innerHTML = '<span class="kg-ayuda"><i class="fa-solid fa-spinner fa-spin"></i> El profesor está mirando los datos…</span>';
        boton.disabled = true;
        let texto = '';
        try {
            const r = await flujo('/api/kaggle/explicar_datos', { tipo: f.tipo, ref: f.ref, modelo: estado.modelo, regenerar }, (ev) => {
                if (ev.tipo === 'texto') { texto += ev.delta; if ($('kg-explicacion-datos')) pintarMd($('kg-explicacion-datos'), texto); }
            });
            estado.explicacionDatos[`${f.tipo}:${f.ref}`] = r.texto;
            if ($('kg-explicacion-datos')) pintarMd($('kg-explicacion-datos'), r.texto);
        } catch (e) {
            if ($('kg-explicacion-datos')) $('kg-explicacion-datos').innerHTML = `<div class="kg-error">${esc(e.message)}</div>`;
        } finally {
            if ($('kg-explicar-datos')) $('kg-explicar-datos').disabled = false;
        }
    }

    // ================================================================== notebook
    async function abrirNotebook(ref, irA) {
        const hoja = $('kg-hoja');
        hoja.innerHTML = `<div class="kg-pagina">${barraVolver()}<div class="kg-vacio"><i class="fa-solid fa-spinner fa-spin fa-2x" style="color:#20beff;"></i><p>Descargando el notebook de Kaggle…</p></div></div>`;
        conectarVolver(hoja);
        try {
            const nb = await json(`/api/kaggle/notebook?ref=${encodeURIComponent(ref)}`);
            estado.nb = nb;
            estado.explicaciones = {};
            Object.entries(nb.explicaciones || {}).forEach(([clave, e]) => {
                if (clave.startsWith('guia:')) { estado.guia = estado.guia && estado.guia.ref === nb.ref ? estado.guia : { ref: nb.ref, texto: e.texto }; return; }
                const i = e.indice;
                if (!estado.explicaciones[i] || (e.fecha || '') > (estado.explicaciones[i].fecha || '')) estado.explicaciones[i] = e;
            });
            if (estado.guia && estado.guia.ref !== nb.ref) estado.guia = null;
            estado.abiertas = new Set(Object.keys(estado.explicaciones).map(Number));
            estado.activa = null;
            estado.chat = [];
            estado.pasoAPaso = false;
            if (estado.vista && estado.vista.tipo === 'notebook') {
                estado.vista.ref = nb.ref;
                guardarLocal('prig_kaggle_vista', JSON.stringify({ tipo: 'notebook', ref: nb.ref }));
            }
            pintarHoja();
            if (irA != null) setTimeout(() => irACelda(irA), 60);
        } catch (e) {
            hoja.innerHTML = `<div class="kg-pagina">${barraVolver()}<div class="kg-error">${esc(e.message)}</div></div>`;
            conectarVolver(hoja);
        }
    }

    function pintarHoja() {
        const hoja = $('kg-hoja');
        if (!hoja) return;
        const nb = estado.nb;
        if (!nb) {
            hoja.innerHTML = `<div class="kg-vacio">
                <i class="fa-brands fa-kaggle" style="font-size:44px; color:#20beff;"></i>
                <h2>Lee notebooks de Kaggle con un profesional al lado</h2>
                <p>Busca un notebook de la comunidad (o pega su enlace) y ábrelo. Cada celda aparece junto a su explicación:
                qué hace, cómo, por qué está ahí y qué conceptos usa. Puedes pedir una guía de lectura antes de empezar,
                leerlo paso a paso o preguntar lo que quieras.</p>
                <p class="kg-ayuda">Las explicaciones se guardan y lo leído cuenta en tu Perfil.</p></div>`;
            return;
        }
        const leidas = (nb.lectura && nb.lectura.leidas) || [];
        const leidasSet = new Set([...leidas, ...estado.abiertas]);
        hoja.innerHTML = `
          <div class="kg-cabecera">
            ${barraVolver()}
            <div class="kg-fila"><span class="kg-titulo" style="flex:1;">${esc(nb.titulo)}</span>
              <button class="kg-btn" data-guardar="notebook|${esc(nb.ref)}" title="Guardar en una colección"><i class="fa-regular fa-bookmark"></i> <span>Guardar</span></button>
              <button class="kg-btn" id="kg-pdf" title="El notebook con las explicaciones del profesor, en PDF"><i class="fa-solid fa-file-pdf"></i> PDF</button>
              <a class="kg-btn" href="${esc(nb.url)}" target="_blank" rel="noopener noreferrer" title="Ver en kaggle.com"><i class="fa-solid fa-arrow-up-right-from-square"></i></a></div>
            <div class="kg-fila kg-ayuda" style="margin:3px 0 6px;">${esc(nb.autor || '')} · <i class="fa-solid fa-caret-up"></i> ${miles(nb.votos)} · ${nb.celdas.length} celdas · versión ${esc(nb.version || '')}${nb.gpu ? ' · GPU' : ''}</div>
            ${(nb.datos || []).length ? `<div class="kg-fila" style="margin-bottom:8px;"><span class="kg-ayuda">Datos:</span>${nb.datos.map((d, i) => `<button class="kg-chip" data-fuente="${i}" title="${d.descargado ? 'Ya está en el proyecto' : 'Ver y descargar'}">
                <i class="fa-solid ${d.tipo === 'competicion' ? 'fa-trophy' : 'fa-table'}"></i>${esc(d.ref)}${d.descargado ? ' <i class="fa-solid fa-circle-check" style="color:var(--accent-green);"></i>' : ''}</button>`).join('')}</div>` : ''}
            <div class="kg-fila">
              <button class="kg-btn morado" id="kg-guia-btn"><i class="fa-solid fa-map"></i> Guía de lectura</button>
              <button class="kg-btn azul" id="kg-paso"><i class="fa-solid fa-person-chalkboard"></i> Leer paso a paso</button>
              <button class="kg-btn" id="kg-importar" title="Guarda el notebook en kaggle_notebooks/ con las rutas apuntando a kaggle_datos/"><i class="fa-solid fa-file-arrow-down"></i> Guardar en el proyecto</button>
              <button class="kg-btn verde" id="kg-ejecutar" title="Lo guarda y lo abre en Prig para ejecutarlo y ver sus tablas y gráficos"><i class="fa-solid fa-play"></i> Ejecutar en Prig</button>
              <span style="flex:1"></span>
              <select id="kg-nivel" class="kg-campo" style="width:auto;" title="Profundidad de las explicaciones">
                ${['principiante', 'intermedio', 'avanzado'].map(n => `<option ${n === estado.nivel ? 'selected' : ''}>${n}</option>`).join('')}</select>
              <select id="kg-modelo" class="kg-campo" style="width:auto; max-width:220px;" title="Modelo que te acompaña"></select>
            </div>
            <div class="kg-fila" style="margin-top:8px;"><span class="kg-ayuda" id="kg-progreso-texto">${leidasSet.size} de ${nb.celdas.length} celdas leídas con el profesor</span></div>
            <div class="kg-barra" style="margin-top:4px;"><div id="kg-progreso" style="width:${Math.round(100 * leidasSet.size / Math.max(1, nb.celdas.length))}%;"></div></div>
            <div id="kg-importado"></div>
          </div>
          <div id="kg-guia"></div>
          <div id="kg-celdas">${nb.celdas.map(c => celdaHtml(c, leidasSet.has(c.indice))).join('')}</div>
          <div class="kg-ayuda" style="padding:10px 16px;">${esc(nb.licencia || '')}</div>
          <div class="kg-chat" id="kg-chat">
            <div class="kg-msgs" id="kg-msgs"></div>
            <div class="kg-fila"><input id="kg-pregunta" class="kg-campo" style="flex:1;" placeholder="Pregunta al profesor sobre el notebook${estado.activa != null ? '' : ' (o elige una celda para preguntar sobre ella)'}…">
              <button class="kg-btn azul" id="kg-preguntar"><i class="fa-solid fa-paper-plane"></i></button></div>
            <div class="kg-ayuda" id="kg-chat-contexto" style="margin-top:3px;"></div>
          </div>`;
        pintarSelectorModelo($('kg-modelo'));
        $('kg-modelo').onchange = (e) => { estado.modelo = e.target.value; guardarLocal('prig_kaggle_modelo', estado.modelo); };
        $('kg-nivel').onchange = (e) => { estado.nivel = e.target.value; guardarLocal('prig_kaggle_nivel', estado.nivel); };
        $('kg-guia-btn').onclick = () => pedirGuia(false);
        $('kg-paso').onclick = () => pasoAPaso();
        $('kg-importar').onclick = () => importar(false);
        $('kg-ejecutar').onclick = () => importar(true);
        $('kg-pdf').onclick = () => dialogoPdf({ ref: nb.ref, titulo: nb.titulo });
        refrescarMarcas();
        conectarVolver($('kg-hoja'));
        $('kg-hoja').querySelectorAll('[data-fuente]').forEach(b => b.onclick = () => {
            const d = nb.datos[+b.dataset.fuente];
            ir({ tipo: d.tipo, ref: d.ref });
        });
        $('kg-preguntar').onclick = preguntar;
        $('kg-pregunta').onkeydown = (e) => { if (e.key === 'Enter') preguntar(); };
        document.querySelectorAll('#kg-celdas .kg-celda').forEach(el => conectarCelda(el));
        Object.entries(estado.explicaciones).forEach(([i, e]) => pintarExplicacion(+i, e.texto, true));
        if (estado.guia) pintarGuia(estado.guia.texto);
        pintarChat();
    }

    function celdaHtml(c, leida) {
        const original = c.tipo === 'markdown'
            ? `<div class="kg-md" data-md="${c.indice}"></div>`
            : `<pre class="kg-codigo"><code class="hljs language-python">${codigoResaltado(c.fuente)}</code></pre>`
              + (c.salida ? `<details style="margin-top:4px;"><summary class="kg-ayuda" style="cursor:pointer;">Salida guardada</summary><pre class="kg-codigo" style="color:var(--text-muted);">${esc(c.salida)}</pre></details>` : '');
        return `<div class="kg-celda" data-celda="${c.indice}" id="kg-celda-${c.indice}">
            <div class="kg-original">
              <div class="kg-num"><span class="kg-mini">${c.indice}</span><span>${c.tipo === 'markdown' ? 'texto' : 'código'}</span>
                ${leida ? '<i class="fa-solid fa-check" style="color:var(--accent-green);" title="Leída con el profesor"></i>' : ''}</div>
              ${original}
            </div>
            <div class="kg-explicacion" data-exp="${c.indice}">
              ${c.fuente.trim() ? `<button class="kg-btn" data-explicar><i class="fa-solid fa-user-graduate"></i> ${c.tipo === 'markdown' ? 'Comentar' : 'Explicar esta celda'}</button>` : ''}
            </div>
          </div>`;
    }

    function conectarCelda(el) {
        const i = +el.dataset.celda;
        const c = estado.nb.celdas[i];
        const md = el.querySelector('[data-md]');
        if (md) pintarMd(md, c.fuente);
        const b = el.querySelector('[data-explicar]');
        if (b) b.onclick = () => explicar(i);
        el.querySelector('.kg-original').onclick = () => elegirCelda(i);
    }

    function elegirCelda(i) {
        estado.activa = i;
        document.querySelectorAll('#kg-celdas .kg-celda').forEach(x => x.classList.toggle('activa', +x.dataset.celda === i));
        const ctx = $('kg-chat-contexto');
        if (ctx) ctx.innerHTML = `Preguntando sobre la celda ${i} · <a href="#" id="kg-quitar-celda">preguntar sobre todo el notebook</a>`;
        const q = $('kg-quitar-celda');
        if (q) q.onclick = (e) => { e.preventDefault(); estado.activa = null; ctx.textContent = ''; document.querySelectorAll('.kg-celda.activa').forEach(x => x.classList.remove('activa')); };
    }

    function irACelda(i) {
        const el = $(`kg-celda-${i}`);
        if (el) el.scrollIntoView({ block: 'start', behavior: 'smooth' });
    }

    function pintarExplicacion(i, texto, guardada, cargando) {
        const cont = document.querySelector(`[data-exp="${i}"]`);
        if (!cont) return;
        cont.innerHTML = `<div class="kg-fila" style="margin-bottom:2px;"><span class="kg-ayuda" style="flex:1;"><i class="fa-solid fa-user-graduate" style="color:var(--accent-purple);"></i> Profesor${guardada ? ' · guardada' : ''}</span>
            ${cargando ? '' : `<button class="kg-btn" data-regenerar title="Pedir otra explicación" style="padding:2px 6px;"><i class="fa-solid fa-rotate"></i></button>`}</div>
          <div data-texto></div>`;
        const t = cont.querySelector('[data-texto]');
        if (texto) pintarMd(t, texto);
        else t.innerHTML = '<span class="kg-ayuda"><i class="fa-solid fa-spinner fa-spin"></i> Leyendo la celda…</span>';
        const r = cont.querySelector('[data-regenerar]');
        if (r) r.onclick = () => explicar(i, true);
    }

    async function explicar(i, regenerar = false) {
        if (estado.pidiendo.has(i)) return;
        estado.pidiendo.add(i);
        elegirCelda(i);
        let texto = '';
        pintarExplicacion(i, '', false, true);
        try {
            const r = await flujo('/api/kaggle/explicar', { ref: estado.nb.ref, indice: i, nivel: estado.nivel, modelo: estado.modelo, regenerar }, (ev) => {
                if (ev.tipo === 'texto') { texto += ev.delta; pintarExplicacion(i, texto, false, true); }
            });
            if (!estado.nb) return;
            estado.explicaciones[i] = { texto: r.texto, fecha: new Date().toISOString(), indice: i };
            estado.abiertas.add(i);
            pintarExplicacion(i, r.texto, r.guardada);
            marcarLeida(i);
        } catch (e) {
            const cont = document.querySelector(`[data-exp="${i}"]`);
            if (cont) cont.innerHTML = `<div class="kg-error">${esc(e.message)}</div><button class="kg-btn" style="margin-top:6px;" data-explicar>Reintentar</button>`;
            const b = cont && cont.querySelector('[data-explicar]');
            if (b) b.onclick = () => explicar(i, regenerar);
            throw e;
        } finally {
            estado.pidiendo.delete(i);
        }
    }

    function marcarLeida(i) {
        const nb = estado.nb;
        const num = document.querySelector(`#kg-celda-${i} .kg-num`);
        if (num && !num.querySelector('.fa-check')) num.insertAdjacentHTML('beforeend', '<i class="fa-solid fa-check" style="color:var(--accent-green);" title="Leída con el profesor"></i>');
        const leidas = new Set([...((nb.lectura && nb.lectura.leidas) || []), ...estado.abiertas]);
        const barra = $('kg-progreso');
        if (barra) barra.style.width = `${Math.round(100 * leidas.size / Math.max(1, nb.celdas.length))}%`;
        const t = $('kg-progreso-texto');
        if (t) t.textContent = `${leidas.size} de ${nb.celdas.length} celdas leídas con el profesor`;
    }

    // ------------------------------------------------------------------ leer paso a paso
    async function pasoAPaso() {
        const nb = estado.nb;
        const boton = $('kg-paso');
        if (estado.pasoAPaso) { estado.pasoAPaso = false; boton.innerHTML = '<i class="fa-solid fa-person-chalkboard"></i> Leer paso a paso'; return; }
        estado.pasoAPaso = true;
        boton.innerHTML = '<i class="fa-solid fa-pause"></i> Pausar lectura';
        // Desde la celda elegida; si ya está leída, desde la primera sin leer que venga después
        const sinLeer = (c) => !estado.abiertas.has(c.indice) && c.fuente.trim();
        const desde = estado.activa != null ? estado.activa : 0;
        let inicio = nb.celdas.findIndex(c => c.indice >= desde && sinLeer(c));
        if (inicio < 0) inicio = nb.celdas.findIndex(sinLeer);
        if (inicio < 0) { estado.pasoAPaso = false; boton.innerHTML = '<i class="fa-solid fa-person-chalkboard"></i> Leer paso a paso'; return; }
        for (let i = inicio; i < nb.celdas.length && estado.pasoAPaso && estado.nb === nb; i++) {
            if (!nb.celdas[i].fuente.trim()) continue;
            irACelda(i);
            if (!estado.abiertas.has(i)) {
                try { await explicar(i); } catch (e) { break; }
            }
            // Pausa para leer: el profesor espera a que pulses «Seguir» antes de pasar a la siguiente
            if (i < nb.celdas.length - 1 && estado.pasoAPaso) {
                const seguir = await esperarSeguir(i);
                if (!seguir) break;
            }
        }
        estado.pasoAPaso = false;
        const b = $('kg-paso');
        if (b) b.innerHTML = '<i class="fa-solid fa-person-chalkboard"></i> Leer paso a paso';
    }

    function esperarSeguir(i) {
        return new Promise((resolver) => {
            const cont = document.querySelector(`[data-exp="${i}"]`);
            if (!cont) return resolver(false);
            const barra = document.createElement('div');
            barra.className = 'kg-fila';
            barra.style.marginTop = '8px';
            barra.innerHTML = '<button class="kg-btn verde" data-seguir><i class="fa-solid fa-forward-step"></i> Seguir con la siguiente celda</button><button class="kg-btn" data-parar>Parar aquí</button>';
            cont.appendChild(barra);
            barra.querySelector('[data-seguir]').onclick = () => { barra.remove(); resolver(true); };
            barra.querySelector('[data-parar]').onclick = () => { barra.remove(); resolver(false); };
        });
    }

    // ------------------------------------------------------------------ guía de lectura
    function pintarGuia(texto, cargando) {
        const c = $('kg-guia');
        if (!c) return;
        c.innerHTML = `<div class="kg-guia"><div class="kg-fila"><b style="color:var(--accent-purple); flex:1;"><i class="fa-solid fa-map"></i> Guía de lectura</b>
            ${cargando ? '' : '<button class="kg-btn" data-regenerar title="Rehacer la guía" style="padding:2px 6px;"><i class="fa-solid fa-rotate"></i></button><button class="kg-btn" data-cerrar style="padding:2px 6px;"><i class="fa-solid fa-xmark"></i></button>'}</div>
            <div data-texto></div></div>`;
        const t = c.querySelector('[data-texto]');
        if (texto) {
            // «celdas 3–7» lleva a esa celda
            pintarMd(t, texto.replace(/celdas? (\d+)(?:\s*[–-]\s*(\d+))?/g, (m, a) => `[${m}](#kg-ir-${a})`));
            t.querySelectorAll('a[href^="#kg-ir-"]').forEach(a => { a.removeAttribute('target'); a.onclick = (e) => { e.preventDefault(); irACelda(+a.getAttribute('href').replace('#kg-ir-', '')); }; });
        } else t.innerHTML = '<span class="kg-ayuda"><i class="fa-solid fa-spinner fa-spin"></i> El profesor está hojeando el notebook…</span>';
        const r = c.querySelector('[data-regenerar]');
        if (r) r.onclick = () => pedirGuia(true);
        const x = c.querySelector('[data-cerrar]');
        if (x) x.onclick = () => { c.innerHTML = ''; };
    }

    async function pedirGuia(regenerar) {
        const nb = estado.nb;
        let texto = '';
        pintarGuia('', true);
        try {
            const r = await flujo('/api/kaggle/guia', { ref: nb.ref, modelo: estado.modelo, regenerar }, (ev) => {
                if (ev.tipo === 'texto') { texto += ev.delta; pintarGuia(texto, true); }
                if (ev.tipo === 'pensando' && !texto) { const t = document.querySelector('#kg-guia [data-texto]'); if (t) t.innerHTML = '<span class="kg-ayuda"><i class="fa-solid fa-spinner fa-spin"></i> El profesor está razonando sobre la estructura…</span>'; }
            });
            if (estado.nb !== nb) return;
            estado.guia = { ref: nb.ref, texto: r.texto };
            pintarGuia(r.texto);
        } catch (e) {
            const c = $('kg-guia');
            if (c) c.innerHTML = `<div class="kg-guia"><div class="kg-error">${esc(e.message)}</div></div>`;
        }
    }

    // ------------------------------------------------------------------ preguntas
    function pintarChat() {
        const c = $('kg-msgs');
        if (!c) return;
        c.innerHTML = estado.chat.map((m, i) => `<div class="kg-msg ${m.rol}" data-i="${i}"></div>`).join('');
        c.querySelectorAll('.kg-msg').forEach(el => pintarMd(el, estado.chat[+el.dataset.i].texto || '…'));
        c.hidden = !estado.chat.length;
        c.scrollTop = c.scrollHeight;
    }

    async function preguntar() {
        const campo = $('kg-pregunta');
        const t = campo.value.trim();
        if (!t || !estado.nb) return;
        campo.value = '';
        estado.chat.push({ rol: 'usuario', texto: t + (estado.activa != null ? `  \n*(sobre la celda ${estado.activa})*` : '') });
        const respuesta = { rol: 'profesor', texto: '' };
        estado.chat.push(respuesta);
        pintarChat();
        try {
            await flujo('/api/kaggle/preguntar', {
                ref: estado.nb.ref, indice: estado.activa, modelo: estado.modelo,
                mensajes: estado.chat.slice(0, -1).map(m => ({ rol: m.rol === 'usuario' ? 'usuario' : 'tutor', texto: m.texto })),
            }, (ev) => {
                if (ev.tipo === 'texto') {
                    respuesta.texto += ev.delta;
                    const el = document.querySelector(`#kg-msgs .kg-msg[data-i="${estado.chat.indexOf(respuesta)}"]`);
                    if (el) pintarMd(el, respuesta.texto);
                }
            });
        } catch (e) { respuesta.texto = `*No pude responder: ${e.message}*`; }
        pintarChat();
    }

    // ------------------------------------------------------------------ guardar en el proyecto y ejecutar
    async function importar(ejecutar) {
        const botones = ['kg-importar', 'kg-ejecutar'].map($).filter(Boolean);
        botones.forEach(b => { b.disabled = true; });
        const c = $('kg-importado');
        try {
            const r = await enviar('/api/kaggle/importar', { ref: estado.nb.ref });
            const faltan = (r.datos || []).filter(d => !d.descargado);
            c.innerHTML = `<div class="kg-ayuda" style="margin-top:6px; color:var(--accent-green);"><i class="fa-solid fa-check"></i> Guardado en <b>${esc(r.relativa)}</b>
               ${r.celdas_con_rutas ? `· ${r.celdas_con_rutas} celdas con rutas a kaggle_datos/` : ''} · <a href="#" id="kg-abrir-archivo">abrirlo en el editor</a></div>
               ${faltan.length ? `<div class="kg-fila" style="margin-top:4px;"><span class="kg-ayuda" style="color:var(--accent-yellow);">Para que funcione faltan sus datos:</span>
                 ${faltan.map(d => `<button class="kg-chip" data-bajar="${esc(d.tipo)}|${esc(d.ref)}"><i class="fa-solid fa-download"></i> ${esc(d.ref)}</button>`).join('')}</div>` : ''}`;
            if (window.fileTreeMgr) window.fileTreeMgr.loadTree();
            const abrirEditor = () => {
                if (window.workArea) window.workArea.activar('editor');
                if (window.editorMgr) window.editorMgr.openFileByPath(r.ruta);
            };
            $('kg-abrir-archivo').onclick = (e) => { e.preventDefault(); abrirEditor(); };
            c.querySelectorAll('[data-bajar]').forEach(b => b.onclick = () => {
                const [tipo, ref] = b.dataset.bajar.split('|');
                ir({ tipo, ref });
            });
            if (ejecutar && !faltan.length) abrirEditor();
        } catch (e) {
            c.innerHTML = `<div class="kg-error" style="margin-top:6px;">${esc(e.message)}</div>`;
        } finally { botones.forEach(b => { b.disabled = false; }); }
    }

    // ================================================================== entrada pública
    async function abrir(opciones = {}) {
        if (window.workArea) window.workArea.abrirHerramienta('modal-kaggle-hub', 'Kaggle', 'fa-k');
        montar();
        if (opciones.ref) ir({ tipo: opciones.tipo || 'notebook', ref: opciones.ref, celda: opciones.celda });
    }

    // Herramientas → Kaggle (Ctrl+5) abre la pestaña sin pasar por abrir(): se monta y
    // vuelve a la última vista
    document.addEventListener('prig:herramienta-abierta', (e) => {
        if (e.detail && e.detail.modalId === 'modal-kaggle-hub') montar();
    });

    window.KaggleLector = { abrir, estado, ir };
})();
