/**
 * Opciones de IDE: lo que cualquier editor de código trae y Prig no tenía.
 *
 *   · Ir a archivo (Ctrl+P), abrir reciente, ir a pestaña, ir a símbolo
 *   · Guardar como, guardar todo, autoguardado, revertir
 *   · Renombrar, duplicar, eliminar, copiar ruta, mostrar en el sistema
 *   · Cerrar otras / guardadas / todas, reabrir pestaña cerrada, clic central
 *   · Buscar y reemplazar en todos los archivos
 *   · Ajuste de línea, minimapa, espacios, guías, tamaño de letra, pantalla completa
 *   · Atrás / adelante entre posiciones
 *   · Python: símbolos del archivo, ir a definición, referencias y errores de sintaxis
 *   · Barra de estado: línea y columna, sangría, fin de línea, lenguaje, problemas
 *   · Menús contextuales en pestañas y en el árbol de archivos
 *
 * Los comandos (commands.js) llaman a window.IDE; este archivo no registra atajos.
 */
(function () {
    const $ = (id) => document.getElementById(id);
    const esc = (t) => String(t ?? '').replace(/[&<>"']/g,
        (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
    const LS = {
        get(clave, defecto) {
            try { const v = localStorage.getItem(clave); return v === null ? defecto : JSON.parse(v); }
            catch (e) { return defecto; }
        },
        set(clave, valor) { try { localStorage.setItem(clave, JSON.stringify(valor)); } catch (e) { /* sin almacenamiento */ } },
    };
    const mensaje = (texto, ms = 2500) => window.layoutMgr && window.layoutMgr.mensajeEstado(texto, ms);
    const nombreDe = (ruta) => (ruta || '').split('/').pop();
    const carpetaDe = (ruta) => (ruta || '').substring(0, (ruta || '').lastIndexOf('/'));
    const ed = () => window.editorMgr;

    async function json(url, opciones) { return window.prigFetchJson(url, opciones); }
    const post = (url, cuerpo) => json(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(cuerpo) });

    let raizWorkspace = '';
    async function raiz() {
        if (!raizWorkspace) {
            try { raizWorkspace = (await json('/api/workspace')).path || ''; } catch (e) { /* sin backend */ }
        }
        return raizWorkspace;
    }
    function relativa(ruta) {
        if (raizWorkspace && ruta.startsWith(raizWorkspace + '/')) return ruta.slice(raizWorkspace.length + 1);
        return ruta;
    }

    // =====================================================================
    // Estilos propios (menú contextual, panel de búsqueda, barra de estado)
    // =====================================================================
    function instalarEstilos() {
        if ($('ide-estilos')) return;
        const css = document.createElement('style');
        css.id = 'ide-estilos';
        css.textContent = `
          .ide-contextual { position: fixed; top: 0; left: 0; border-radius: 7px; z-index: 5000; max-height: 80vh; overflow-y: auto; }
          .menu-item[disabled] { opacity: .45; pointer-events: none; }
          .ide-selector-detalle { color: var(--text-muted); font-size: 11px; margin-left: 8px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
          .ide-selector-grupo { padding: 6px 16px 2px; font-size: 9.5px; text-transform: uppercase; letter-spacing: .05em; color: var(--text-muted); }
          #estado-editor { display: inline-flex; gap: 12px; align-items: center; }
          #estado-editor[hidden] { display: none; }
          #estado-editor > span { cursor: pointer; white-space: nowrap; }
          #estado-editor > span:hover { color: var(--text-main); }
          #vista-buscar { padding: 10px 12px; gap: 8px; overflow: hidden; font-size: 12px; }
          .buscar-fila { display: flex; gap: 6px; align-items: center; }
          .buscar-fila input[type=text] { flex: 1; min-width: 0; padding: 6px 8px; background: var(--bg-panel); color: #fff; border: 1px solid var(--border-color); border-radius: 5px; font-family: inherit; font-size: 12px; }
          .buscar-fila input[type=text]:focus { outline: none; border-color: var(--acento-usuario, var(--accent-blue)); }
          .buscar-opcion { min-width: 28px; padding: 4px 6px; border-radius: 4px; background: transparent; color: var(--text-muted); border: 1px solid transparent; cursor: pointer; font-family: 'Fira Code', monospace; font-size: 11px; }
          .buscar-opcion.activa { color: var(--accent-blue); border-color: var(--accent-blue); background: rgba(137,180,250,.12); }
          .buscar-boton { padding: 5px 10px; border-radius: 5px; cursor: pointer; font-size: 11.5px; background: rgba(137,180,250,.15); color: var(--accent-blue); border: 1px solid rgba(137,180,250,.35); white-space: nowrap; }
          .buscar-resultados { flex: 1; overflow: auto; min-height: 0; }
          .buscar-archivo { display: flex; gap: 6px; align-items: center; padding: 4px 4px; cursor: pointer; border-radius: 4px; }
          .buscar-archivo:hover { background: rgba(255,255,255,.05); }
          .buscar-archivo .cuenta { margin-left: auto; font-size: 10px; background: rgba(255,255,255,.08); border-radius: 8px; padding: 0 6px; }
          .buscar-linea { display: flex; gap: 8px; padding: 2px 4px 2px 22px; cursor: pointer; border-radius: 4px; font-family: 'Fira Code', monospace; font-size: 11.5px; white-space: pre; overflow: hidden; text-overflow: ellipsis; }
          .buscar-linea:hover { background: rgba(137,180,250,.10); }
          .buscar-linea .num { color: var(--text-muted); min-width: 34px; text-align: right; }
          .buscar-linea mark { background: rgba(249,226,175,.35); color: inherit; border-radius: 2px; }
          .buscar-linea del { background: rgba(243,139,168,.25); text-decoration: line-through; }
          .buscar-linea ins { background: rgba(166,227,161,.25); text-decoration: none; }
        `;
        document.head.appendChild(css);
    }

    // =====================================================================
    // Editores
    // =====================================================================
    let ultimoEditor = null;
    const editores = new Set();

    function editorActivo() {
        const principal = ed() && ed().editor;
        if (ultimoEditor && editores.has(ultimoEditor)) {
            const paneEditors = (ed() && ed().panes || []).map(p => p.editor).filter(Boolean);
            const grupos = (window.workArea && window.workArea.grupos || []).map(g => g.editor);
            if (ultimoEditor === principal || paneEditors.includes(ultimoEditor) || grupos.includes(ultimoEditor)) return ultimoEditor;
        }
        return principal;
    }

    function accion(id) {
        const editor = editorActivo();
        if (!editor) { mensaje('El editor todavía se está cargando'); return; }
        if (window.workArea && window.workArea.activa !== 'editor') window.workArea.activar('editor');
        editor.focus();
        const a = editor.getAction(id);
        if (a) a.run();
        else editor.trigger('prig', id, null);
    }

    function alCrearEditor(editor) {
        if (!editor || editores.has(editor)) return;
        editores.add(editor);
        aplicarVista(editor);
        editor.onDidFocusEditorWidget(() => { ultimoEditor = editor; pintarEstado(); });
        editor.onDidChangeCursorSelection(() => pintarEstado());
        editor.onDidChangeModel(() => pintarEstado());
        editor.onDidChangeCursorPosition((e) => anotarPosicion(editor, e));
        editor.onDidDispose(() => { editores.delete(editor); if (ultimoEditor === editor) ultimoEditor = null; });
    }

    // =====================================================================
    // Selector rápido (Ctrl+P, recientes, lenguaje…)
    // =====================================================================
    function puntuar(consulta, texto) {
        if (!consulta) return 1;
        const q = consulta.toLowerCase(), t = texto.toLowerCase();
        const i = t.indexOf(q);
        if (i >= 0) return 1000 - i - (t.length - q.length) * 0.1;
        // Subsecuencia: "edjs" encuentra "editor.js"
        let pos = -1, huecos = 0;
        for (const c of q) {
            const j = t.indexOf(c, pos + 1);
            if (j < 0) return -1;
            huecos += j - pos - 1;
            pos = j;
        }
        return 500 - huecos;
    }

    /**
     * items: [{label, detalle, grupo, valor, icono}] o función async (consulta) → items.
     * Devuelve {item, consulta} o null si se cancela.
     */
    function elegir({ placeholder = 'Escribe para filtrar…', items, filtrar = true, valorInicial = '' }) {
        return new Promise((resolver) => {
            document.getElementById('ide-selector')?.remove();
            const capa = document.createElement('div');
            capa.id = 'ide-selector';
            capa.className = 'prig-paleta';
            capa.innerHTML = `<div class="paleta-caja"><input type="text" class="ide-selector-input" autocomplete="off" spellcheck="false"
                style="width:100%; padding:13px 16px; background:transparent; border:none; border-bottom:1px solid var(--border-color); color:#fff; font-size:14px; outline:none;">
                <div class="paleta-lista"></div></div>`;
            document.body.appendChild(capa);
            const input = capa.querySelector('input');
            const lista = capa.querySelector('.paleta-lista');
            input.placeholder = placeholder;
            input.value = valorInicial;
            let visibles = [], indice = 0, terminado = false;
            const previoFoco = document.activeElement;

            const cerrar = (resultado) => {
                if (terminado) return;
                terminado = true;
                capa.remove();
                if (!resultado && previoFoco && previoFoco.focus) previoFoco.focus();
                resolver(resultado);
            };

            const pintar = () => {
                if (!visibles.length) {
                    lista.innerHTML = '<div class="paleta-vacio">Nada coincide.</div>';
                    return;
                }
                lista.innerHTML = '';
                let grupoActual = null;
                visibles.forEach((it, i) => {
                    if (it.grupo && it.grupo !== grupoActual) {
                        grupoActual = it.grupo;
                        const g = document.createElement('div');
                        g.className = 'ide-selector-grupo';
                        g.textContent = it.grupo;
                        lista.appendChild(g);
                    }
                    const fila = document.createElement('button');
                    fila.className = 'paleta-item' + (i === indice ? ' activo' : '');
                    fila.innerHTML = `${it.icono ? `<i class="fa-solid ${esc(it.icono)}" style="width:14px; color:var(--text-muted);"></i>` : ''}
                        <span class="paleta-label" style="flex:0 1 auto; white-space:nowrap;"></span><span class="ide-selector-detalle"></span>`;
                    fila.querySelector('.paleta-label').textContent = it.label;
                    fila.querySelector('.ide-selector-detalle').textContent = it.detalle || '';
                    fila.onclick = () => cerrar({ item: it, consulta: input.value });
                    lista.appendChild(fila);
                });
                const activo = lista.querySelector('.paleta-item.activo');
                if (activo) activo.scrollIntoView({ block: 'nearest' });
            };

            let ultimaPeticion = 0;
            const filtrarItems = async () => {
                const consulta = input.value.trim();
                const peticion = ++ultimaPeticion;
                let base = typeof items === 'function' ? await items(consulta) : items;
                if (peticion !== ultimaPeticion || terminado) return;
                if (filtrar) {
                    const sinSufijo = consulta.replace(/:\d+(:\d+)?$/, '');
                    base = base.map(it => ({ it, p: Math.max(puntuar(sinSufijo, it.label) + 200, puntuar(sinSufijo, `${it.detalle || ''} ${it.label}`)) }))
                        .filter(x => x.p >= 0)
                        .sort((a, b) => sinSufijo ? b.p - a.p : 0)
                        .map(x => sinSufijo ? { ...x.it, grupo: undefined } : x.it);
                }
                visibles = base.slice(0, 80);
                indice = 0;
                pintar();
            };

            input.oninput = filtrarItems;
            input.onkeydown = (e) => {
                if (e.key === 'Escape') { e.preventDefault(); cerrar(null); }
                else if (e.key === 'ArrowDown') { e.preventDefault(); indice = Math.min(indice + 1, visibles.length - 1); pintar(); }
                else if (e.key === 'ArrowUp') { e.preventDefault(); indice = Math.max(indice - 1, 0); pintar(); }
                else if (e.key === 'Enter') {
                    e.preventDefault();
                    const it = visibles[indice];
                    if (it) cerrar({ item: it, consulta: input.value });
                    else if (!filtrar || typeof items === 'function') cerrar({ item: null, consulta: input.value });
                }
            };
            capa.onmousedown = (e) => { if (e.target === capa) cerrar(null); };
            filtrarItems();
            setTimeout(() => { input.focus(); input.select(); }, 10);
        });
    }

    // =====================================================================
    // Abrir: ir a archivo, recientes, pestañas
    // =====================================================================
    const CLAVE_RECIENTES = 'prig_archivos_recientes';

    function anotarArchivoReciente(ruta) {
        const lista = LS.get(CLAVE_RECIENTES, []).filter(p => p !== ruta);
        lista.unshift(ruta);
        LS.set(CLAVE_RECIENTES, lista.slice(0, 30));
    }

    /** "archivo.py:42:5" → abre y va a la línea 42, columna 5 */
    async function abrirEnPosicion(ruta, linea = null, columna = 1, seleccionHasta = null) {
        if (window.workArea && window.workArea.activa !== 'editor') window.workArea.activar('editor');
        const ok = ed().openTabs.has(ruta) ? (ed().setActiveTab(ruta), true) : await ed().openFileByPath(ruta);
        if (!ok || !linea) return ok;
        const editor = ed().editor;
        setTimeout(() => {
            const rango = new monaco.Range(linea, columna, linea, seleccionHasta || columna);
            editor.setSelection(rango);
            editor.revealRangeInCenter(rango);
            editor.focus();
        }, 30);
        return ok;
    }

    async function irAArchivo() {
        await raiz();
        let archivos = null;
        const cargar = async () => {
            if (archivos) return archivos;
            try {
                const datos = await json('/api/ide/archivos');
                raizWorkspace = datos.raiz;
                archivos = datos.archivos;
            } catch (e) {
                mensaje(`No se pudo listar la carpeta: ${e.message}`);
                archivos = [];
            }
            return archivos;
        };
        const resultado = await elegir({
            placeholder: 'Nombre del archivo (añade :línea para ir a una línea)',
            items: async () => {
                const todos = await cargar();
                const existentes = new Set(todos.map(a => a.path));
                const recientes = LS.get(CLAVE_RECIENTES, []).filter(p => existentes.has(p)).slice(0, 8);
                const r = new Set(recientes);
                return [
                    ...recientes.map(p => ({ label: nombreDe(p), detalle: carpetaDe(relativa(p)), valor: p, grupo: 'abiertos recientemente', icono: 'fa-clock-rotate-left' })),
                    ...todos.filter(a => !r.has(a.path)).map(a => ({ label: nombreDe(a.rel), detalle: carpetaDe(a.rel), valor: a.path, grupo: 'archivos', icono: 'fa-file-code' })),
                ];
            },
        });
        if (!resultado || !resultado.item) return;
        const m = resultado.consulta.match(/:(\d+)(?::(\d+))?$/);
        await abrirEnPosicion(resultado.item.valor, m ? parseInt(m[1], 10) : null, m && m[2] ? parseInt(m[2], 10) : 1);
    }

    async function abrirReciente() {
        await raiz();
        let carpetas = [];
        try { carpetas = (await json('/api/ide/recientes')).carpetas; } catch (e) { /* sin backend */ }
        const archivos = LS.get(CLAVE_RECIENTES, []);
        const items = [
            ...carpetas.map(c => ({ label: c.name, detalle: c.path + (c.actual ? ' · actual' : ''), valor: { carpeta: c.path }, grupo: 'carpetas', icono: 'fa-folder' })),
            ...archivos.map(p => ({ label: nombreDe(p), detalle: carpetaDe(p), valor: { archivo: p }, grupo: 'archivos', icono: 'fa-file-code' })),
        ];
        if (carpetas.length || archivos.length) {
            items.push({ label: 'Borrar la lista de recientes', valor: { borrar: true }, grupo: 'lista', icono: 'fa-trash-can' });
        }
        const r = await elegir({ placeholder: 'Abrir reciente…', items });
        if (!r || !r.item) return;
        const v = r.item.valor;
        if (v.borrar) {
            LS.set(CLAVE_RECIENTES, []);
            try { await json('/api/ide/recientes', { method: 'DELETE' }); } catch (e) { /* nada que borrar */ }
            mensaje('Lista de recientes borrada');
        } else if (v.carpeta) {
            await cambiarCarpeta(v.carpeta);
        } else if (v.archivo) {
            await abrirEnPosicion(v.archivo);
        }
    }

    async function cambiarCarpeta(ruta) {
        if (ed().hasUnsavedChanges() && !confirm('Hay pestañas con cambios sin guardar. ¿Cambiar de carpeta igualmente? Las pestañas seguirán abiertas.')) return;
        try {
            const d = await post('/api/workspace/open', { path: ruta });
            raizWorkspace = d.path;
            const nombre = $('current-workspace-name');
            if (nombre) nombre.textContent = d.name;
            window.fileTreeMgr.loadTree();
            mensaje(`Carpeta: ${d.path}`);
        } catch (e) {
            alert(`No se pudo abrir la carpeta: ${e.message}`);
        }
    }

    async function irAPestana() {
        const items = Array.from(ed().openTabs.values()).map(t => ({
            label: `${t.name}${ed().isDirty(t.path) ? ' ●' : ''}`, detalle: carpetaDe(relativa(t.path)), valor: t.path, icono: 'fa-file-lines' }));
        if (!items.length) { mensaje('No hay pestañas abiertas'); return; }
        const r = await elegir({ placeholder: 'Ir a pestaña abierta…', items });
        if (r && r.item) abrirEnPosicion(r.item.valor);
    }

    function cambiarPestana(delta) {
        const rutas = Array.from(ed().openTabs.keys());
        if (rutas.length < 2) return;
        const i = rutas.indexOf(ed().activePath);
        ed().setActiveTab(rutas[(i + delta + rutas.length) % rutas.length]);
    }

    // =====================================================================
    // Guardar, revertir, autoguardado
    // =====================================================================
    function rutaActiva() {
        const p = ed() && ed().getActivePath();
        if (!p) mensaje('No hay ningún archivo abierto');
        return p;
    }

    async function guardarComo() {
        const origen = rutaActiva();
        if (!origen) return;
        await raiz();
        const destino = prompt('Guardar como (ruta relativa a la carpeta de trabajo):', relativa(origen));
        if (!destino || destino === relativa(origen)) return;
        const tab = ed().openTabs.get(origen);
        const contenido = tab.model.getValue();
        try {
            // No pisar un archivo existente sin preguntar
            const existe = await fetch(`/api/file?path=${encodeURIComponent(destino)}`).then(r => r.ok).catch(() => false);
            if (existe && !confirm(`"${destino}" ya existe. ¿Reemplazarlo?`)) return;
            const d = await post('/api/file', { path: destino, content: contenido });
            ed().openFile(d.path, nombreDe(d.path), contenido, tab.notebookData);
            ed().closeTab(origen, null, true);   // el contenido ya está en el archivo nuevo
            window.fileTreeMgr.loadTree();
            mensaje(`Guardado como ${destino}`);
        } catch (e) {
            alert(`No se pudo guardar: ${e.message}`);
        }
    }

    async function guardarTodo() {
        const sucias = Array.from(ed().openTabs.keys()).filter(p => ed().isDirty(p));
        if (!sucias.length) { mensaje('No hay cambios sin guardar'); return; }
        let ok = 0;
        for (const p of sucias) if (await window.app.saveFile(p, null, { silencioso: true })) ok++;
        mensaje(ok === sucias.length ? `Guardados ${ok} archivos` : `Guardados ${ok} de ${sucias.length}: revisa la consola`, 3000);
    }

    async function revertir(ruta = null) {
        ruta = ruta || rutaActiva();
        if (!ruta) return;
        if (ed().isDirty(ruta) && !confirm(`¿Descartar los cambios sin guardar de "${nombreDe(ruta)}" y volver a lo que hay en disco?`)) return;
        try {
            const d = await json(`/api/file?path=${encodeURIComponent(ruta)}`);
            const tab = ed().openTabs.get(ruta);
            if (!tab) return;
            tab.model.setValue(d.content);
            ed().markSaved(ruta, d.content);
            mensaje('Archivo revertido');
        } catch (e) {
            alert(`No se pudo leer el archivo: ${e.message}`);
        }
    }

    const temporizadoresGuardado = {};
    const autoguardado = () => LS.get('prig_autoguardado', false);

    function alternarAutoguardado() {
        LS.set('prig_autoguardado', !autoguardado());
        mensaje(autoguardado() ? 'Autoguardado activado (1 s después de dejar de escribir)' : 'Autoguardado desactivado', 3000);
        pintarEstado();
        if (autoguardado()) guardarTodo();
    }

    function alCambiarContenido(ruta) {
        programarProblemas(ruta);
        if (!autoguardado()) return;
        clearTimeout(temporizadoresGuardado[ruta]);
        temporizadoresGuardado[ruta] = setTimeout(() => {
            if (ed().openTabs.has(ruta) && ed().isDirty(ruta)) window.app.saveFile(ruta, null, { silencioso: true });
        }, 1000);
    }

    // =====================================================================
    // Renombrar, duplicar, eliminar, rutas
    // =====================================================================
    async function renombrar(ruta = null) {
        ruta = ruta || rutaActiva();
        if (!ruta) return;
        const nuevo = prompt('Nuevo nombre (o ruta relativa para moverlo):', nombreDe(ruta));
        if (!nuevo || nuevo === nombreDe(ruta)) return;
        try {
            const d = await post('/api/ide/renombrar', { path: ruta, destino: nuevo });
            // Pestañas del archivo o de lo que había dentro de la carpeta
            Array.from(ed().openTabs.keys()).forEach(p => {
                if (p === d.anterior) ed().renombrarPestana(p, d.path);
                else if (p.startsWith(d.anterior + '/')) ed().renombrarPestana(p, d.path + p.slice(d.anterior.length));
            });
            window.fileTreeMgr.loadTree();
            mensaje(`Renombrado a ${nombreDe(d.path)}`);
        } catch (e) {
            alert(`No se pudo renombrar: ${e.message}`);
        }
    }

    async function duplicar(ruta = null) {
        ruta = ruta || rutaActiva();
        if (!ruta) return;
        try {
            const d = await post('/api/ide/duplicar', { path: ruta });
            window.fileTreeMgr.loadTree();
            mensaje(`Copia creada: ${nombreDe(d.path)}`);
        } catch (e) {
            alert(`No se pudo duplicar: ${e.message}`);
        }
    }

    async function eliminar(ruta = null, esCarpeta = false) {
        ruta = ruta || rutaActiva();
        if (!ruta) return;
        const que = esCarpeta ? `la carpeta "${nombreDe(ruta)}" y TODO su contenido` : `"${nombreDe(ruta)}"`;
        if (!confirm(`¿Eliminar ${que}?\n\nNo se puede deshacer.`)) return;
        try {
            await json(`/api/file?path=${encodeURIComponent(ruta)}`, { method: 'DELETE' });
            Array.from(ed().openTabs.keys())
                .filter(p => p === ruta || p.startsWith(ruta + '/'))
                .forEach(p => ed().closeTab(p, null, true));
            window.fileTreeMgr.loadTree();
            mensaje(`Eliminado: ${nombreDe(ruta)}`);
        } catch (e) {
            alert(`No se pudo eliminar: ${e.message}`);
        }
    }

    async function copiarTexto(texto) {
        try {
            await navigator.clipboard.writeText(texto);
        } catch (e) {
            const t = document.createElement('textarea');
            t.value = texto;
            t.style.cssText = 'position:fixed; opacity:0;';
            document.body.appendChild(t);
            t.select();
            document.execCommand('copy');
            t.remove();
        }
    }

    async function copiarRuta(rel, ruta = null) {
        ruta = ruta || rutaActiva();
        if (!ruta) return;
        await raiz();
        const texto = rel ? relativa(ruta) : ruta;
        await copiarTexto(texto);
        mensaje(`Copiado: ${texto}`);
    }

    async function mostrarEnSistema(ruta = null) {
        ruta = ruta || rutaActiva() || await raiz();
        if (!ruta) return;
        try { await post('/api/ide/mostrar-en-sistema', { path: ruta }); }
        catch (e) { alert(`No se pudo abrir el explorador: ${e.message}`); }
    }

    // =====================================================================
    // Pestañas
    // =====================================================================
    const cerradas = [];

    function cerrarVarias(filtro) {
        Array.from(ed().openTabs.keys()).filter(filtro).forEach(p => ed().closeTab(p));
    }
    const cerrarOtras = (ruta = null) => {
        const mantener = ruta || ed().activePath;
        cerrarVarias(p => p !== mantener);
    };
    const cerrarGuardadas = () => cerrarVarias(p => !ed().isDirty(p));
    const cerrarTodas = () => cerrarVarias(() => true);
    function cerrarALaDerecha(ruta) {
        const rutas = Array.from(ed().openTabs.keys());
        const i = rutas.indexOf(ruta);
        rutas.slice(i + 1).forEach(p => ed().closeTab(p));
    }

    async function reabrirCerrada() {
        while (cerradas.length) {
            const p = cerradas.pop();
            if (!ed().openTabs.has(p) && await ed().openFileByPath(p)) return;
        }
        mensaje('No hay pestañas cerradas que reabrir');
    }

    // =====================================================================
    // Portapapeles desde el menú
    // =====================================================================
    async function portapapeles(que) {
        const editor = editorActivo();
        if (!editor) return;
        editor.focus();
        if (que === 'pegar') {
            try {
                const texto = await navigator.clipboard.readText();
                editor.executeEdits('prig-pegar', editor.getSelections().map(sel => ({ range: sel, text: texto, forceMoveMarkers: true })));
            } catch (e) {
                mensaje('Este entorno no deja leer el portapapeles desde el menú: usa Ctrl+V', 3500);
            }
            return;
        }
        const id = que === 'cortar' ? 'editor.action.clipboardCutAction' : 'editor.action.clipboardCopyAction';
        const a = editor.getAction(id);
        if (a) await a.run();
    }

    // =====================================================================
    // Vista del editor
    // =====================================================================
    const VISTA_DEFECTO = { ajusteLinea: false, minimapa: false, espacios: false, guias: true, numeros: true, fijos: false };
    const NOMBRES_VISTA = {
        ajusteLinea: 'Ajuste de línea', minimapa: 'Minimapa', espacios: 'Espacios en blanco visibles',
        guias: 'Guías de sangría', numeros: 'Números de línea', fijos: 'Encabezados fijos',
    };
    const vista = () => ({ ...VISTA_DEFECTO, ...LS.get('prig_editor_vista', {}) });

    function aplicarVista(editor) {
        const v = vista();
        editor.updateOptions({
            wordWrap: v.ajusteLinea ? 'on' : 'off',
            minimap: { enabled: v.minimapa },
            renderWhitespace: v.espacios ? 'all' : 'selection',
            guides: { indentation: v.guias, bracketPairs: v.guias ? 'active' : false },
            lineNumbers: v.numeros ? 'on' : 'off',
            stickyScroll: { enabled: v.fijos },
            fontSize: parseInt(localStorage.getItem('prig_editor_font_size') || '14', 10),
        });
    }

    function alternarVista(opcion) {
        const v = vista();
        v[opcion] = !v[opcion];
        LS.set('prig_editor_vista', v);
        editores.forEach(aplicarVista);
        mensaje(`${NOMBRES_VISTA[opcion]}: ${v[opcion] ? 'sí' : 'no'}`);
    }

    function tamanoLetra(delta) {
        const actual = parseInt(localStorage.getItem('prig_editor_font_size') || '14', 10);
        const nuevo = delta === 0 ? 14 : Math.max(8, Math.min(40, actual + delta));
        localStorage.setItem('prig_editor_font_size', String(nuevo));
        editores.forEach(e => e.updateOptions({ fontSize: nuevo }));
        const consola = $('terminal-body');
        if (consola) consola.style.fontSize = `${Math.round(nuevo * 0.86)}px`;
        mensaje(`Tamaño de letra: ${nuevo}`);
    }

    async function pantallaCompleta() {
        // En la ventana nativa (pywebview) la API del navegador suele estar bloqueada:
        // se le pide al backend, que controla la ventana.
        try {
            if (document.fullscreenElement) { await document.exitFullscreen(); return; }
            if (document.documentElement.requestFullscreen) {
                await document.documentElement.requestFullscreen();
                return;
            }
        } catch (e) { /* se intenta por la ventana nativa */ }
        try {
            await post('/api/ide/pantalla-completa', {});
        } catch (e) {
            mensaje('Este entorno no permite la pantalla completa');
        }
    }

    function alternarBarraEstado() {
        const barra = $('prig-estado');
        if (!barra) return;
        barra.hidden = !barra.hidden;
        LS.set('prig_barra_estado_oculta', barra.hidden);
        setTimeout(() => editores.forEach(e => e.layout()), 50);
    }

    // =====================================================================
    // Atrás / adelante
    // =====================================================================
    const historial = [];
    let posHistorial = -1;
    let navegando = false;

    function anotarPosicion(editor, e) {
        if (navegando || editor !== (ed() && ed().editor)) return;
        const ruta = ed().activePath;
        if (!ruta) return;
        const linea = e.position.lineNumber;
        const ultimo = historial[posHistorial];
        // Solo saltos, no cada tecla: cambio de archivo, más de 10 líneas, o un salto
        // hecho por código (ir a la definición, ir a línea, resultado de búsqueda)
        // aunque sea cerca. Escribir o moverse con flechas solo actualiza la posición.
        const saltoDeCodigo = e.source && !['keyboard', 'mouse', 'model', 'modelChange', 'restoreState'].includes(e.source)
            && ultimo && ultimo.linea !== linea;
        if (ultimo && ultimo.ruta === ruta && Math.abs(ultimo.linea - linea) < 10 && !saltoDeCodigo) {
            ultimo.linea = linea;
            ultimo.columna = e.position.column;
            return;
        }
        historial.splice(posHistorial + 1);
        historial.push({ ruta, linea, columna: e.position.column });
        if (historial.length > 60) historial.shift();
        posHistorial = historial.length - 1;
    }

    async function navegar(delta) {
        const destino = posHistorial + delta;
        if (destino < 0 || destino >= historial.length) { mensaje(delta < 0 ? 'No hay posición anterior' : 'No hay posición siguiente', 1500); return; }
        const p = historial[destino];
        navegando = true;
        try {
            if (!await abrirEnPosicion(p.ruta, p.linea, p.columna)) {
                historial.splice(destino, 1);
                if (posHistorial >= destino) posHistorial--;
                return;
            }
            posHistorial = destino;
        } finally {
            setTimeout(() => { navegando = false; }, 120);
        }
    }

    // =====================================================================
    // Python: símbolos, definición, referencias
    // =====================================================================
    function simbolosPython(model) {
        const K = monaco.languages.SymbolKind;
        const lineas = model.getLinesContent();
        const raices = [];
        const pila = [];            // {sangria, simbolo}
        const re = /^(\s*)(async\s+def|def|class)\s+([A-Za-z_]\w*)/;
        const reVariable = /^([A-Za-z_]\w*)\s*(?::[^=]+)?=(?!=)/;
        lineas.forEach((texto, i) => {
            const n = i + 1;
            if (!texto.trim() || texto.trim().startsWith('#')) return;
            const sangria = texto.length - texto.trimStart().length;
            while (pila.length && pila[pila.length - 1].sangria >= sangria) {
                const cerrado = pila.pop().simbolo;
                cerrado.range = new monaco.Range(cerrado.range.startLineNumber, 1, Math.max(cerrado.range.startLineNumber, n - 1), 1);
            }
            const m = texto.match(re);
            const mv = !m && sangria === 0 ? texto.match(reVariable) : null;
            if (!m && !mv) return;
            const nombre = m ? m[3] : mv[1];
            const col = texto.indexOf(nombre) + 1;
            const esClase = m && m[2] === 'class';
            const dentroDeClase = pila.length && pila[pila.length - 1].simbolo.kind === K.Class;
            const simbolo = {
                name: nombre, detail: '', tags: [],
                kind: esClase ? K.Class : (m ? (dentroDeClase ? K.Method : K.Function) : (nombre === nombre.toUpperCase() ? K.Constant : K.Variable)),
                range: new monaco.Range(n, 1, lineas.length, 1),
                selectionRange: new monaco.Range(n, col, n, col + nombre.length),
                children: [],
            };
            if (pila.length) pila[pila.length - 1].simbolo.children.push(simbolo);
            else raices.push(simbolo);
            if (m) pila.push({ sangria, simbolo });
        });
        return raices;
    }

    function modelosPython() {
        return Array.from(ed().openTabs.values()).filter(t => !t.isNotebook && t.model.getLanguageId() === 'python').map(t => t.model);
    }

    function registrarPython() {
        if (typeof monaco === 'undefined' || registrarPython.hecho) return;
        registrarPython.hecho = true;
        monaco.languages.registerDocumentSymbolProvider('python', {
            displayName: 'Prig',
            provideDocumentSymbols: (model) => simbolosPython(model),
        });
        monaco.languages.registerDefinitionProvider('python', {
            provideDefinition(model, posicion) {
                const palabra = model.getWordAtPosition(posicion);
                if (!palabra) return [];
                const w = palabra.word.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
                const patrones = [
                    new RegExp(`^\\s*(?:async\\s+def|def|class)\\s+(${w})\\b`),
                    new RegExp(`^\\s*(${w})\\s*(?::[^=]+)?=(?!=)`),
                    new RegExp(`^\\s*(?:from\\s+\\S+\\s+)?import\\s+.*\\b(${w})\\b`),
                ];
                // Primero el archivo actual, después el resto de pestañas Python
                const modelos = [model, ...modelosPython().filter(m => m !== model)];
                for (const patron of patrones) {
                    for (const m of modelos) {
                        const lineas = m.getLinesContent();
                        for (let i = 0; i < lineas.length; i++) {
                            const r = lineas[i].match(patron);
                            if (!r) continue;
                            if (m === model && i + 1 === posicion.lineNumber && patron !== patrones[0]) continue;
                            const col = lineas[i].indexOf(r[1], lineas[i].search(/\S/)) + 1;
                            return [{ uri: m.uri, range: new monaco.Range(i + 1, col, i + 1, col + r[1].length) }];
                        }
                    }
                }
                return [];
            },
        });
        monaco.languages.registerReferenceProvider('python', {
            provideReferences(model, posicion) {
                const palabra = model.getWordAtPosition(posicion);
                if (!palabra) return [];
                const re = new RegExp(`\\b${palabra.word.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}\\b`, 'g');
                const salida = [];
                [model, ...modelosPython().filter(m => m !== model)].forEach(m => {
                    m.getLinesContent().forEach((texto, i) => {
                        let r;
                        re.lastIndex = 0;
                        while ((r = re.exec(texto))) salida.push({ uri: m.uri, range: new monaco.Range(i + 1, r.index + 1, i + 1, r.index + 1 + r[0].length) });
                    });
                });
                return salida.slice(0, 1000);
            },
        });
        // Ir a la definición en otra pestaña: Monaco abre modelos por uri, Prig por ruta
        if (monaco.editor.registerEditorOpener) {
            monaco.editor.registerEditorOpener({
                openCodeEditor(fuente, recurso, seleccion) {
                    const tab = Array.from(ed().openTabs.values()).find(t => t.model.uri.toString() === recurso.toString());
                    if (!tab) return false;
                    const rango = seleccion && seleccion.startLineNumber ? seleccion : null;
                    abrirEnPosicion(tab.path, rango ? rango.startLineNumber : null, rango ? rango.startColumn : 1);
                    return true;
                },
            });
        }
    }

    // =====================================================================
    // Problemas (errores de sintaxis de Python)
    // =====================================================================
    const temporizadoresProblemas = {};

    function programarProblemas(ruta, espera = 700) {
        clearTimeout(temporizadoresProblemas[ruta]);
        temporizadoresProblemas[ruta] = setTimeout(() => revisarProblemas(ruta), espera);
    }

    async function revisarProblemas(ruta) {
        const tab = ed().openTabs.get(ruta);
        if (!tab || tab.isNotebook || typeof monaco === 'undefined') return;
        const lenguaje = tab.model.getLanguageId();
        if (lenguaje !== 'python') {
            monaco.editor.setModelMarkers(tab.model, 'prig', []);
            pintarEstado();
            return;
        }
        const version = tab.model.getVersionId();
        try {
            const d = await post('/api/ide/problemas', { lenguaje, codigo: tab.model.getValue() });
            if (tab.model.isDisposed() || tab.model.getVersionId() !== version) return;
            const S = monaco.MarkerSeverity;
            monaco.editor.setModelMarkers(tab.model, 'prig', d.problemas.map(p => ({
                startLineNumber: p.linea, startColumn: p.col, endLineNumber: p.fin_linea, endColumn: p.fin_col,
                message: p.mensaje, severity: p.gravedad === 'error' ? S.Error : S.Warning, source: 'Python',
            })));
        } catch (e) { /* backend ocupado: se revisa en el próximo cambio */ }
        pintarEstado();
    }

    function marcadores(model) {
        return model ? monaco.editor.getModelMarkers({ resource: model.uri }) : [];
    }

    async function listaProblemas() {
        const editor = editorActivo();
        const model = editor && editor.getModel();
        const lista = marcadores(model);
        if (!lista.length) { mensaje('Sin problemas en este archivo'); return; }
        const S = monaco.MarkerSeverity;
        const r = await elegir({
            placeholder: 'Problemas del archivo',
            items: lista.map(m => ({
                label: m.message, detalle: `línea ${m.startLineNumber}, columna ${m.startColumn} · ${m.source || ''}`,
                icono: m.severity === S.Error ? 'fa-circle-xmark' : 'fa-triangle-exclamation', valor: m })),
        });
        if (r && r.item) {
            const m = r.item.valor;
            editor.setSelection(new monaco.Range(m.startLineNumber, m.startColumn, m.endLineNumber, m.endColumn));
            editor.revealRangeInCenter(editor.getSelection());
            editor.focus();
        }
    }

    // =====================================================================
    // Barra de estado del editor
    // =====================================================================
    function montarEstado() {
        const derecha = $('prig-estado-derecha');
        if (!derecha || $('estado-editor')) return;
        const cont = document.createElement('span');
        cont.id = 'estado-editor';
        cont.hidden = true;
        cont.innerHTML = `
            <span data-e="problemas" title="Problemas del archivo (Ctrl+Shift+M)"></span>
            <span data-e="posicion" title="Ir a línea (Ctrl+G)"></span>
            <span data-e="sangria" title="Sangría del archivo"></span>
            <span data-e="codificacion" title="Prig lee y guarda los archivos en UTF-8">UTF-8</span>
            <span data-e="eol" title="Fin de línea"></span>
            <span data-e="lenguaje" title="Lenguaje del archivo"></span>
            <span data-e="autoguardado"></span>`;
        derecha.insertBefore(cont, derecha.firstChild);
        cont.querySelector('[data-e=problemas]').onclick = () => listaProblemas();
        cont.querySelector('[data-e=posicion]').onclick = () => accion('editor.action.gotoLine');
        cont.querySelector('[data-e=sangria]').onclick = () => elegirSangria();
        cont.querySelector('[data-e=eol]').onclick = () => elegirFinDeLinea();
        cont.querySelector('[data-e=lenguaje]').onclick = () => elegirLenguaje();
        cont.querySelector('[data-e=autoguardado]').onclick = () => alternarAutoguardado();
        if (LS.get('prig_barra_estado_oculta', false) && $('prig-estado')) $('prig-estado').hidden = true;
    }

    let pintadoPendiente = false;
    function pintarEstado() {
        if (pintadoPendiente) return;
        pintadoPendiente = true;
        requestAnimationFrame(() => {
            pintadoPendiente = false;
            const cont = $('estado-editor');
            if (!cont || typeof monaco === 'undefined') return;
            const editor = editorActivo();
            const model = editor && editor.getModel();
            const hayArchivo = !!(ed() && ed().activePath && model);
            cont.hidden = !hayArchivo;
            if (!hayArchivo) return;
            const pos = editor.getPosition();
            const selecciones = editor.getSelections() || [];
            const seleccionados = selecciones.reduce((n, s) => n + model.getValueLengthInRange(s), 0);
            const g = (e) => cont.querySelector(`[data-e=${e}]`);
            g('posicion').textContent = `Lín ${pos ? pos.lineNumber : 1}, col ${pos ? pos.column : 1}` +
                (selecciones.length > 1 ? ` (${selecciones.length} cursores)` : (seleccionados ? ` (${seleccionados} selec.)` : ''));
            const o = model.getOptions();
            g('sangria').textContent = o.insertSpaces ? `Espacios: ${o.tabSize}` : `Tabulador: ${o.tabSize}`;
            g('eol').textContent = model.getEOL() === '\r\n' ? 'CRLF' : 'LF';
            const idioma = monaco.languages.getLanguages().find(l => l.id === model.getLanguageId());
            g('lenguaje').textContent = idioma && idioma.aliases ? idioma.aliases[0] : model.getLanguageId();
            const lista = marcadores(model);
            const S = monaco.MarkerSeverity;
            const errores = lista.filter(m => m.severity === S.Error).length;
            const avisos = lista.length - errores;
            g('problemas').innerHTML = `<i class="fa-solid fa-circle-xmark" style="color:${errores ? 'var(--accent-red)' : 'inherit'}"></i> ${errores}
                <i class="fa-solid fa-triangle-exclamation" style="color:${avisos ? 'var(--accent-yellow)' : 'inherit'}; margin-left:4px;"></i> ${avisos}`;
            g('autoguardado').innerHTML = autoguardado()
                ? '<i class="fa-solid fa-floppy-disk" style="color:var(--accent-green)"></i> auto'
                : '<i class="fa-solid fa-floppy-disk" style="opacity:.45"></i>';
            g('autoguardado').title = autoguardado() ? 'Autoguardado activado: pulsa para desactivarlo' : 'Autoguardado desactivado: pulsa para activarlo';
        });
    }

    async function elegirSangria() {
        const editor = editorActivo();
        const model = editor && editor.getModel();
        if (!model || !ed().activePath) { mensaje('No hay ningún archivo abierto'); return; }
        const r = await elegir({
            placeholder: 'Sangría',
            filtrar: false,
            items: [
                ...[2, 4, 8].map(n => ({ label: `Espacios: ${n}`, valor: { insertSpaces: true, tabSize: n }, icono: 'fa-arrow-right-long' })),
                ...[2, 4, 8].map(n => ({ label: `Tabulador (ancho ${n})`, valor: { insertSpaces: false, tabSize: n }, icono: 'fa-arrow-right-to-bracket' })),
                { label: 'Detectar a partir del contenido', valor: 'detectar', icono: 'fa-wand-magic-sparkles' },
                { label: 'Convertir la sangría a espacios', valor: 'aEspacios', icono: 'fa-right-left' },
                { label: 'Convertir la sangría a tabuladores', valor: 'aTabuladores', icono: 'fa-right-left' },
            ],
        });
        if (!r || !r.item) return;
        const v = r.item.valor;
        if (v === 'detectar') model.detectIndentation(true, 4);
        else if (v === 'aEspacios') { editor.focus(); editor.trigger('prig', 'editor.action.indentationToSpaces', null); }
        else if (v === 'aTabuladores') { editor.focus(); editor.trigger('prig', 'editor.action.indentationToTabs', null); }
        else model.updateOptions(v);
        pintarEstado();
    }

    async function elegirFinDeLinea() {
        const model = editorActivo() && editorActivo().getModel();
        if (!model || !ed().activePath) { mensaje('No hay ningún archivo abierto'); return; }
        const r = await elegir({
            placeholder: 'Fin de línea', filtrar: false,
            items: [{ label: 'LF (Linux, macOS)', valor: 0 }, { label: 'CRLF (Windows)', valor: 1 }],
        });
        if (!r || !r.item) return;
        model.pushEOL(r.item.valor);
        pintarEstado();
    }

    async function elegirLenguaje() {
        const model = editorActivo() && editorActivo().getModel();
        if (!model || !ed().activePath) { mensaje('No hay ningún archivo abierto'); return; }
        const r = await elegir({
            placeholder: 'Lenguaje del archivo',
            items: monaco.languages.getLanguages().map(l => ({
                label: (l.aliases && l.aliases[0]) || l.id, detalle: (l.extensions || []).slice(0, 4).join(' '), valor: l.id })),
        });
        if (!r || !r.item) return;
        monaco.editor.setModelLanguage(model, r.item.valor);
        programarProblemas(ed().activePath, 0);
        pintarEstado();
    }

    // =====================================================================
    // Ejecutar selección
    // =====================================================================
    async function ejecutarSeleccion() {
        const editor = editorActivo();
        const model = editor && editor.getModel();
        const ruta = ed() && ed().activePath;
        if (!model || !ruta) { mensaje('Abre un archivo primero'); return; }
        if (model.getLanguageId() !== 'python') { mensaje('Ejecutar selección solo está disponible para Python'); return; }
        const sel = editor.getSelection();
        const codigo = sel && !sel.isEmpty() ? model.getValueInRange(sel) : model.getLineContent(editor.getPosition().lineNumber);
        if (!codigo.trim()) { mensaje('La línea está vacía'); return; }
        window.workArea.abrir('consola');
        window.terminalMgr.appendLine(`>>> ${codigo.split('\n')[0]}${codigo.includes('\n') ? ' …' : ''}`, 'info');
        try {
            // Misma sesión persistente que el cuaderno: lo definido se conserva entre ejecuciones
            const d = await post('/api/notebook/cell/run', { code: dedent(codigo), path: `${ruta}#seleccion` });
            if (d.stdout) window.terminalMgr.appendLine(d.stdout, 'stdout');
            if (d.stderr) window.terminalMgr.appendLine(d.stderr, 'stderr');
            if (!d.stdout && !d.stderr) window.terminalMgr.appendLine(d.success ? '[ok]' : '[falló]', d.success ? 'info' : 'stderr');
        } catch (e) {
            window.terminalMgr.appendLine(`[No se pudo ejecutar: ${e.message}]`, 'stderr');
        }
        window.workArea.activar('editor');
        editor.focus();
    }

    function dedent(texto) {
        const lineas = texto.split('\n');
        const sangrias = lineas.filter(l => l.trim()).map(l => l.length - l.trimStart().length);
        const minimo = sangrias.length ? Math.min(...sangrias) : 0;
        return lineas.map(l => l.slice(Math.min(minimo, l.length - l.trimStart().length))).join('\n');
    }

    // =====================================================================
    // Menú contextual
    // =====================================================================
    function menuContextual(x, y, items) {
        document.getElementById('ide-contextual')?.remove();
        const panel = document.createElement('div');
        panel.id = 'ide-contextual';
        panel.className = 'menu-panel ide-contextual';
        items.forEach(it => {
            if (it === '-') {
                const s = document.createElement('div');
                s.className = 'menu-separador';
                panel.appendChild(s);
                return;
            }
            const b = document.createElement('button');
            b.className = 'menu-item';
            b.innerHTML = '<span class="menu-item-label"></span><span class="menu-item-accel"></span>';
            b.querySelector('.menu-item-label').textContent = it.label;
            const cmd = it.comando && window.PrigCommands.get(it.comando);
            b.querySelector('.menu-item-accel').textContent = cmd ? window.shortcutMgr.bonito(window.shortcutMgr.accel(cmd.id)) : '';
            if (it.deshabilitado) b.disabled = true;
            b.onclick = (e) => { e.stopPropagation(); cerrar(); it.run(); };
            panel.appendChild(b);
        });
        document.body.appendChild(panel);
        const r = panel.getBoundingClientRect();
        panel.style.left = `${Math.max(4, Math.min(x, window.innerWidth - r.width - 4))}px`;
        panel.style.top = `${Math.max(4, Math.min(y, window.innerHeight - r.height - 4))}px`;
        const cerrar = () => {
            panel.remove();
            document.removeEventListener('mousedown', fuera, true);
            document.removeEventListener('keydown', tecla, true);
            window.removeEventListener('blur', cerrar);
        };
        const fuera = (e) => { if (!panel.contains(e.target)) cerrar(); };
        const tecla = (e) => { if (e.key === 'Escape') { e.stopPropagation(); cerrar(); } };
        setTimeout(() => {
            document.addEventListener('mousedown', fuera, true);
            document.addEventListener('keydown', tecla, true);
            window.addEventListener('blur', cerrar);
        }, 0);
    }

    function instalarContextuales() {
        const gridCont = $('editor-grid-container') || $('vista-editor');
        if (gridCont && !gridCont.dataset.ideContextual) {
            gridCont.dataset.ideContextual = '1';
            gridCont.addEventListener('contextmenu', (e) => {
                const el = e.target.closest('.tab-item');
                if (!el || !el.dataset.path) return;
                e.preventDefault();
                const ruta = el.dataset.path;
                const col = parseInt(el.dataset.col !== undefined ? el.dataset.col : (ed()?.activeCol || 0), 10);

                const items = [
                    { label: 'Cerrar', run: () => (ed() && ed().closeTabInPane) ? ed().closeTabInPane(col, ruta) : ed().closeTab(ruta) },
                    { label: 'Cerrar las demás', run: () => cerrarOtras(ruta) },
                    { label: 'Cerrar las de la derecha', run: () => cerrarALaDerecha(ruta) },
                    { label: 'Cerrar guardadas', comando: 'archivo.cerrarGuardadas', run: cerrarGuardadas },
                    { label: 'Cerrar todas', comando: 'archivo.cerrarTodas', run: cerrarTodas },
                    '-',
                    { label: 'Abrir al lado', comando: 'vista.dividir', run: () => {
                        if (ed() && ed().splitRight) ed().splitRight(ruta);
                        else { ed().setActiveTab(ruta); window.workArea.dividir(); }
                    } },
                    { label: 'Mover al panel derecho', deshabilitado: col >= 2, run: () => {
                        if (ed() && ed().moveTabToPane) ed().moveTabToPane(ruta, col, Math.min(2, col + 1));
                    } },
                ];

                if (col > 0) {
                    items.push({
                        label: 'Mover al panel izquierdo',
                        run: () => { if (ed() && ed().moveTabToPane) ed().moveTabToPane(ruta, col, col - 1); }
                    });
                }

                items.push(
                    '-',
                    { label: 'Revertir archivo', deshabilitado: !ed().isDirty(ruta), run: () => revertir(ruta) },
                    '-',
                    { label: 'Copiar ruta', comando: 'archivo.copiarRuta', run: () => copiarRuta(false, ruta) },
                    { label: 'Copiar ruta relativa', comando: 'archivo.copiarRutaRelativa', run: () => copiarRuta(true, ruta) },
                    { label: 'Mostrar en el explorador del sistema', comando: 'archivo.revelar', run: () => mostrarEnSistema(ruta) },
                    '-',
                    { label: 'Renombrar…', run: () => renombrar(ruta) },
                    { label: 'Duplicar', run: () => duplicar(ruta) },
                    { label: 'Eliminar…', run: () => eliminar(ruta) },
                );
                menuContextual(e.clientX, e.clientY, items);
            });
        }

        const arbol = $('file-tree-container');
        if (arbol && !arbol.dataset.ideContextual) {
            arbol.dataset.ideContextual = '1';
            arbol.addEventListener('contextmenu', async (e) => {
                e.preventDefault();
                const el = e.target.closest('.tree-item');
                const base = await raiz();
                if (!el || !el.dataset.path) {
                    menuContextual(e.clientX, e.clientY, [
                        { label: 'Nuevo archivo…', run: () => window.fileTreeMgr.createItem(false, base) },
                        { label: 'Nueva carpeta…', run: () => window.fileTreeMgr.createItem(true, base) },
                        '-',
                        { label: 'Actualizar', run: () => window.fileTreeMgr.loadTree() },
                        { label: 'Abrir carpeta de trabajo…', comando: 'archivo.abrirCarpeta', run: () => window.fileTreeMgr.openWorkspaceFolder() },
                        { label: 'Mostrar en el explorador del sistema', run: () => mostrarEnSistema(base) },
                    ]);
                    return;
                }
                const ruta = el.dataset.path;
                const esCarpeta = el.dataset.dir === '1';
                const carpeta = esCarpeta ? ruta : carpetaDe(ruta);
                const ejecutable = /\.(py|sh|js)$/i.test(ruta);
                const items = esCarpeta ? [
                    { label: 'Nuevo archivo…', run: () => window.fileTreeMgr.createItem(false, carpeta) },
                    { label: 'Nueva carpeta…', run: () => window.fileTreeMgr.createItem(true, carpeta) },
                    { label: 'Buscar en esta carpeta…', run: () => abrirBusqueda({ incluir: relativa(ruta) + '/' }) },
                    '-',
                ] : [
                    { label: 'Abrir', run: () => abrirEnPosicion(ruta) },
                    { label: 'Abrir al lado', run: async () => {
                        if (await abrirEnPosicion(ruta)) {
                            if (ed() && ed().splitRight) ed().splitRight(ruta);
                            else window.workArea.dividir();
                        }
                    } },
                    ...(ejecutable ? [{ label: 'Ejecutar', run: async () => { if (await abrirEnPosicion(ruta)) window.app.runCode(); } }] : []),
                    '-',
                    { label: 'Nuevo archivo aquí…', run: () => window.fileTreeMgr.createItem(false, carpeta) },
                    '-',
                ];
                items.push(
                    { label: 'Renombrar…', run: () => renombrar(ruta) },
                    { label: 'Duplicar', run: () => duplicar(ruta) },
                    { label: 'Eliminar…', run: () => eliminar(ruta, esCarpeta) },
                    '-',
                    { label: 'Copiar ruta', run: () => copiarRuta(false, ruta) },
                    { label: 'Copiar ruta relativa', run: () => copiarRuta(true, ruta) },
                    { label: 'Mostrar en el explorador del sistema', run: () => mostrarEnSistema(ruta) },
                );
                menuContextual(e.clientX, e.clientY, items);
            });
        }
    }

    // =====================================================================
    // Buscar y reemplazar en archivos
    // =====================================================================
    const busqueda = { regex: false, mayusculas: false, palabra: false, reemplazar: false, datos: null, contraidos: new Set(), descartados: new Set() };

    function montarBusqueda() {
        const vistaEl = $('vista-buscar');
        if (!vistaEl || vistaEl.dataset.montada) return vistaEl;
        vistaEl.dataset.montada = '1';
        vistaEl.innerHTML = `
            <div class="buscar-fila">
              <button class="buscar-opcion" id="buscar-alternar-reemplazo" title="Mostrar reemplazar"><i class="fa-solid fa-chevron-right"></i></button>
              <input type="text" id="buscar-consulta" placeholder="Buscar en todos los archivos (Intro)">
              <button class="buscar-opcion" data-op="mayusculas" title="Distinguir mayúsculas">Aa</button>
              <button class="buscar-opcion" data-op="palabra" title="Palabra completa">ab</button>
              <button class="buscar-opcion" data-op="regex" title="Expresión regular">.*</button>
            </div>
            <div class="buscar-fila" id="buscar-fila-reemplazo" hidden>
              <span style="width:28px;"></span>
              <input type="text" id="buscar-reemplazo" placeholder="Reemplazar por">
              <button class="buscar-boton" id="buscar-reemplazar-todo" title="Reemplazar en todos los resultados"><i class="fa-solid fa-right-left"></i> Reemplazar todo</button>
            </div>
            <div class="buscar-fila">
              <span style="width:28px;"></span>
              <input type="text" id="buscar-incluir" placeholder="Archivos a incluir (ej. *.py, src/)">
              <input type="text" id="buscar-excluir" placeholder="Archivos a excluir (ej. tests, *.md)">
            </div>
            <div class="buscar-fila" style="color:var(--text-muted); font-size:11px;">
              <span id="buscar-resumen" style="flex:1;"></span>
              <button class="buscar-opcion" id="buscar-refrescar" title="Buscar de nuevo"><i class="fa-solid fa-rotate"></i></button>
              <button class="buscar-opcion" id="buscar-contraer" title="Contraer / expandir todo"><i class="fa-solid fa-layer-group"></i></button>
              <button class="buscar-opcion" id="buscar-limpiar" title="Limpiar"><i class="fa-solid fa-eraser"></i></button>
            </div>
            <div class="buscar-resultados" id="buscar-resultados"></div>`;

        let temporizador = null;
        const lanzar = (inmediato = false) => {
            clearTimeout(temporizador);
            temporizador = setTimeout(buscar, inmediato ? 0 : 450);
        };
        $('buscar-consulta').oninput = () => lanzar();
        $('buscar-consulta').onkeydown = (e) => { if (e.key === 'Enter') lanzar(true); };
        $('buscar-incluir').onkeydown = $('buscar-excluir').onkeydown = (e) => { if (e.key === 'Enter') lanzar(true); };
        $('buscar-reemplazo').oninput = () => pintarResultados();
        vistaEl.querySelectorAll('[data-op]').forEach(b => {
            b.onclick = () => { busqueda[b.dataset.op] = !busqueda[b.dataset.op]; b.classList.toggle('activa', busqueda[b.dataset.op]); lanzar(true); };
        });
        $('buscar-alternar-reemplazo').onclick = () => fijarModoReemplazo(!busqueda.reemplazar);
        $('buscar-reemplazar-todo').onclick = reemplazarTodo;
        $('buscar-refrescar').onclick = () => lanzar(true);
        $('buscar-contraer').onclick = () => {
            const archivos = (busqueda.datos && busqueda.datos.resultados) || [];
            if (busqueda.contraidos.size < archivos.length) archivos.forEach(a => busqueda.contraidos.add(a.path));
            else busqueda.contraidos.clear();
            pintarResultados();
        };
        $('buscar-limpiar').onclick = () => {
            $('buscar-consulta').value = '';
            $('buscar-reemplazo').value = '';
            busqueda.datos = null;
            pintarResultados();
        };
        return vistaEl;
    }

    function fijarModoReemplazo(activo) {
        busqueda.reemplazar = activo;
        $('buscar-fila-reemplazo').hidden = !activo;
        $('buscar-alternar-reemplazo').innerHTML = `<i class="fa-solid fa-chevron-${activo ? 'down' : 'right'}"></i>`;
        pintarResultados();
    }

    function abrirBusqueda({ reemplazar = null, consulta = null, incluir = null } = {}) {
        window.workArea.abrir('buscar');
        montarBusqueda();
        if (reemplazar !== null) fijarModoReemplazo(reemplazar);
        // Como en cualquier IDE: la selección del editor (si es una sola línea) se busca
        const editor = editorActivo();
        let semilla = consulta;
        if (semilla === null && editor && editor.getModel() && ed().activePath) {
            const sel = editor.getSelection();
            const texto = sel && !sel.isEmpty() ? editor.getModel().getValueInRange(sel) : '';
            if (texto && !texto.includes('\n') && texto.length < 200) semilla = texto;
        }
        if (semilla) $('buscar-consulta').value = semilla;
        if (incluir !== null) $('buscar-incluir').value = incluir;
        setTimeout(() => { $('buscar-consulta').focus(); $('buscar-consulta').select(); }, 30);
        if ($('buscar-consulta').value) buscar();
    }

    function parametros() {
        return {
            consulta: $('buscar-consulta').value,
            regex: busqueda.regex, mayusculas: busqueda.mayusculas, palabra: busqueda.palabra,
            incluir: $('buscar-incluir').value, excluir: $('buscar-excluir').value,
        };
    }

    let peticionBusqueda = 0;
    async function buscar() {
        const p = parametros();
        const n = ++peticionBusqueda;
        busqueda.descartados.clear();
        if (!p.consulta) { busqueda.datos = null; pintarResultados(); return; }
        $('buscar-resumen').textContent = 'Buscando…';
        try {
            const d = await post('/api/ide/buscar', p);
            if (n !== peticionBusqueda) return;
            busqueda.datos = d;
        } catch (e) {
            if (n !== peticionBusqueda) return;
            busqueda.datos = { error: e.message };
        }
        pintarResultados();
    }

    function expresionCliente() {
        const p = parametros();
        try {
            let patron = p.regex ? p.consulta : p.consulta.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
            if (p.palabra) patron = `(?<![\\w])${patron}(?![\\w])`;
            return new RegExp(patron, p.mayusculas ? 'g' : 'gi');
        } catch (e) { return null; }
    }

    function previsualizar(c) {
        const texto = c.texto;
        const ini = c.col - 1, fin = c.fin - 1;
        const antes = texto.slice(Math.max(0, ini - 60), ini).replace(/^\s+/, '');
        const trozo = texto.slice(ini, fin);
        const despues = texto.slice(fin, fin + 120);
        if (!busqueda.reemplazar) return `${esc(antes)}<mark>${esc(trozo)}</mark>${esc(despues)}`;
        let nuevo = $('buscar-reemplazo').value;
        if (busqueda.regex) {
            const re = expresionCliente();
            if (re) { try { nuevo = trozo.replace(new RegExp(re.source, re.flags.replace('g', '')), nuevo.replace(/\\(\d)/g, '$$$1')); } catch (e) { /* vista aproximada */ } }
        }
        return `${esc(antes)}<del>${esc(trozo)}</del><ins>${esc(nuevo)}</ins>${esc(despues)}`;
    }

    function pintarResultados() {
        const cont = $('buscar-resultados');
        const resumen = $('buscar-resumen');
        if (!cont) return;
        const d = busqueda.datos;
        if (!d) { cont.innerHTML = ''; resumen.textContent = ''; return; }
        if (d.error) { cont.innerHTML = `<div style="color:var(--accent-red); padding:6px;">${esc(d.error)}</div>`; resumen.textContent = ''; return; }
        const archivos = d.resultados.filter(a => !busqueda.descartados.has(a.path));
        const total = archivos.reduce((n, a) => n + a.coincidencias.length, 0);
        resumen.textContent = total
            ? `${total} resultado${total === 1 ? '' : 's'} en ${archivos.length} archivo${archivos.length === 1 ? '' : 's'}` +
              (d.truncado ? ' · hay más: afina la búsqueda' : '')
            : `Sin resultados (${d.revisados} archivos revisados)`;
        $('buscar-reemplazar-todo').disabled = !total;
        cont.innerHTML = '';
        archivos.forEach(a => {
            const sucio = ed().openTabs.has(a.path) && ed().isDirty(a.path);
            const cab = document.createElement('div');
            cab.className = 'buscar-archivo';
            const contraido = busqueda.contraidos.has(a.path);
            cab.innerHTML = `<i class="fa-solid fa-chevron-${contraido ? 'right' : 'down'}" style="width:10px; font-size:9px; color:var(--text-muted);"></i>
                <b></b><span style="color:var(--text-muted); font-size:10.5px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;"></span>
                ${sucio ? '<span title="Tiene cambios sin guardar" style="color:var(--accent-yellow);">●</span>' : ''}
                <span class="cuenta">${a.coincidencias.length}</span>
                <button class="buscar-opcion" title="Quitar de los resultados"><i class="fa-solid fa-xmark"></i></button>`;
            cab.querySelector('b').textContent = nombreDe(a.rel);
            cab.querySelector('span').textContent = carpetaDe(a.rel);
            cab.onclick = () => { contraido ? busqueda.contraidos.delete(a.path) : busqueda.contraidos.add(a.path); pintarResultados(); };
            cab.querySelector('button').onclick = (e) => { e.stopPropagation(); busqueda.descartados.add(a.path); pintarResultados(); };
            cont.appendChild(cab);
            if (contraido) return;
            a.coincidencias.forEach(c => {
                const fila = document.createElement('div');
                fila.className = 'buscar-linea';
                fila.title = c.texto;
                fila.innerHTML = `<span class="num">${c.linea}</span><span>${previsualizar(c)}</span>`;
                fila.onclick = () => abrirEnPosicion(a.path, c.linea, c.col, c.fin);
                cont.appendChild(fila);
            });
        });
    }

    async function reemplazarTodo() {
        const d = busqueda.datos;
        if (!d || !d.resultados) return;
        const archivos = d.resultados.filter(a => !busqueda.descartados.has(a.path));
        const total = archivos.reduce((n, a) => n + a.coincidencias.length, 0);
        if (!total) return;
        const reemplazo = $('buscar-reemplazo').value;
        const sucios = archivos.filter(a => ed().openTabs.has(a.path) && ed().isDirty(a.path));
        let rutas = archivos.map(a => a.path);
        if (sucios.length) {
            const guardar = confirm(`${sucios.length} archivo(s) tienen cambios sin guardar:\n${sucios.map(a => '· ' + a.rel).join('\n')}\n\n` +
                'Aceptar: guardarlos primero y reemplazar también en ellos.\nCancelar: dejarlos fuera del reemplazo.');
            if (guardar) {
                for (const a of sucios) await window.app.saveFile(a.path, null, { silencioso: true });
            } else {
                const fuera = new Set(sucios.map(a => a.path));
                rutas = rutas.filter(p => !fuera.has(p));
            }
        }
        if (!rutas.length) return;
        if (!confirm(`¿Reemplazar ${total} coincidencia(s) en ${rutas.length} archivo(s) por "${reemplazo}"?\n\nSe escribe en disco.`)) return;
        try {
            const r = await post('/api/ide/reemplazar', { ...parametros(), reemplazo, solo: rutas });
            // Pestañas abiertas de los archivos cambiados: recargar sin cambiar de pestaña
            for (const a of r.archivos) {
                const tab = ed().openTabs.get(a.path);
                if (!tab || ed().isDirty(a.path)) continue;
                const f = await json(`/api/file?path=${encodeURIComponent(a.path)}`);
                tab.model.setValue(f.content);
                ed().markSaved(a.path, f.content);
            }
            mensaje(`Reemplazadas ${r.total} coincidencias en ${r.archivos.length} archivos`, 4000);
            buscar();
        } catch (e) {
            alert(`No se pudo reemplazar: ${e.message}`);
        }
    }

    // =====================================================================
    // Ayuda
    // =====================================================================
    function dialogo(titulo, html) {
        document.getElementById('ide-dialogo')?.remove();
        const capa = document.createElement('div');
        capa.id = 'ide-dialogo';
        capa.className = 'prig-paleta';
        capa.innerHTML = `<div class="paleta-caja" style="padding:16px 18px; font-size:12.5px; max-height:70vh; overflow:auto;">
            <div style="display:flex; align-items:center; margin-bottom:10px;"><b style="font-size:14px;"></b>
            <span style="flex:1"></span><button class="buscar-opcion" title="Cerrar"><i class="fa-solid fa-xmark"></i></button></div>
            <div class="ide-dialogo-cuerpo">${html}</div></div>`;
        capa.querySelector('b').textContent = titulo;
        const cerrar = () => { capa.remove(); document.removeEventListener('keydown', tecla, true); };
        const tecla = (e) => { if (e.key === 'Escape') { e.stopPropagation(); cerrar(); } };
        capa.querySelector('button').onclick = cerrar;
        capa.onmousedown = (e) => { if (e.target === capa) cerrar(); };
        document.addEventListener('keydown', tecla, true);
        document.body.appendChild(capa);
    }

    async function acercaDe() {
        let d = {};
        try { d = await json('/api/ide/acerca'); } catch (e) { d = { error: e.message }; }
        const fila = (k, v) => `<tr><td style="color:var(--text-muted); padding:3px 14px 3px 0;">${esc(k)}</td><td style="font-family:'Fira Code',monospace; font-size:11.5px;">${esc(v)}</td></tr>`;
        dialogo('Acerca de Prig IDE', `
            <p style="margin:0 0 10px; color:var(--text-muted);">Editor y tutor de IA local.</p>
            <table>${[
                fila('Python', d.python || '—'), fila('Sistema', d.sistema || '—'), fila('Ollama', d.ollama || '—'),
                fila('Carpeta de trabajo', d.workspace || '—'), fila('Backend', d.backend || '—'),
                fila('Editor', `Monaco ${typeof monaco !== 'undefined' && monaco.version ? monaco.version : '0.45'}`),
                fila('Navegador', navigator.userAgent),
            ].join('')}</table>`);
    }

    async function registroEventos() {
        let eventos = [];
        try { eventos = (await json('/api/recursos/eventos?limite=100')).eventos; } catch (e) { /* sin backend */ }
        dialogo('Registro de eventos', eventos.length
            ? eventos.map(e => `<div style="padding:5px 0; border-bottom:1px solid rgba(255,255,255,.06);">
                <span style="color:var(--text-muted); font-size:10.5px;">${esc((e.fecha || '').replace('T', ' '))} · ${esc(e.tipo)}</span><br>${esc(e.texto)}</div>`).join('')
            : '<span style="color:var(--text-muted);">Todavía no hay eventos registrados.</span>');
    }

    function recargar() {
        if (ed().hasUnsavedChanges() && !confirm('Hay cambios sin guardar. ¿Recargar igualmente y perderlos?')) return;
        window.__prigSinAvisoAlSalir = true;     // ya se preguntó: que no vuelva a preguntar
        location.reload();
    }

    // =====================================================================
    // Arranque
    // =====================================================================
    window.addEventListener('prig:editor-creado', (e) => { registrarPython(); alCrearEditor(e.detail.editor); pintarEstado(); });
    window.addEventListener('prig:archivo-abierto', (e) => { anotarArchivoReciente(e.detail.path); programarProblemas(e.detail.path, 50); });
    window.addEventListener('prig:pestana-activa', () => pintarEstado());
    window.addEventListener('prig:pestana-cerrada', (e) => {
        cerradas.push(e.detail.path);
        if (cerradas.length > 30) cerradas.shift();
        pintarEstado();
    });
    window.addEventListener('prig:pestana-renombrada', (e) => {
        const lista = LS.get(CLAVE_RECIENTES, []).map(p => p === e.detail.anterior ? e.detail.nueva : p);
        LS.set(CLAVE_RECIENTES, lista);
    });
    window.addEventListener('prig:contenido-cambiado', (e) => { alCambiarContenido(e.detail.path); pintarEstado(); });

    function iniciar() {
        instalarEstilos();
        montarEstado();
        instalarContextuales();
        raiz();
        // Si Monaco ya estaba creado antes de cargar este archivo
        if (ed() && ed().editor) { registrarPython(); alCrearEditor(ed().editor); }
        // El árbol se vuelve a pintar a menudo: la delegación en su contenedor aguanta
        const nombre = $('current-workspace-name');
        if (nombre) new MutationObserver(() => { raizWorkspace = ''; raiz(); }).observe(nombre, { childList: true, characterData: true, subtree: true });
    }
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', iniciar);
    else iniciar();

    window.IDE = {
        editorActivo, accion, elegir, menuContextual,
        autoguardadoActivo: () => autoguardado(), estadoVista: (op) => !!vista()[op],
        irAArchivo, abrirReciente, cambiarCarpeta, irAPestana, cambiarPestana, abrirEnPosicion,
        guardarComo, guardarTodo, revertir, alternarAutoguardado,
        renombrar, duplicar, eliminar, copiarRuta, mostrarEnSistema,
        cerrarOtras, cerrarGuardadas, cerrarTodas, reabrirCerrada,
        portapapeles, alternarVista, tamanoLetra, pantallaCompleta, alternarBarraEstado,
        navegar, listaProblemas, elegirSangria, elegirFinDeLinea, elegirLenguaje,
        ejecutarSeleccion, abrirBusqueda, acercaDe, registroEventos, recargar,
        // para pruebas
        _puntuar: puntuar, _simbolosPython: simbolosPython, _dedent: dedent,
    };
})();
