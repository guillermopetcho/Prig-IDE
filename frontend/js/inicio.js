/**
 * Inicio: la pestaña con la que abre Prig.
 *
 * En una pantalla: quién eres y a dónde vas (perfil editable), tu racha y tu semana,
 * qué te conviene hacer ahora, lo último que hiciste en cualquier parte del programa,
 * tu avance por actividad y concepto, tus modelos y el estado de la máquina, todas
 * las herramientas (con favoritas arriba), tus proyectos y lo que tienes a medias en
 * Kaggle. Todo sale de /api/inicio en una sola petición.
 *
 * Se abre sola al arrancar (se puede desactivar desde la propia pantalla) y siempre
 * con Secciones → Inicio (Alt+Inicio).
 */
(function () {
    const $ = (id) => document.getElementById(id);
    const esc = (t) => String(t ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
    const json = (url, opciones) => window.prigFetchJson(url, opciones);
    const enviar = (url, cuerpo, metodo = 'POST') => json(url, { method: metodo, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(cuerpo || {}) });

    const estado = { datos: null, cargando: false, editando: false, error: null, todasHerramientas: false, filtroNotas: 'todas' };

    /** Qué se ve de cada sección. Lo que ejecuta y su atajo salen de commands.js */
    const HERRAMIENTAS = [
        ['herr.inicio', 'fa-solid fa-house', '#89b4fa', 'Vista principal con tablero de bienvenida, métricas y accesos rápidos.'],
        ['herr.perfil', 'fa-solid fa-chart-pie', '#fab387', 'Historial completo, dominio por concepto y análisis de tu avance.'],
        ['herr.biblioteca', 'fa-solid fa-book-bookmark', '#f9e2af', 'Tus libros y documentos: pregunta y recibe respuestas con citas.'],
        ['herr.practica', 'fa-solid fa-chess-knight', '#cba6f7', 'Desafíos interactivos con razonamiento, código y pruebas en Python y C++.'],
        ['herr.diagramas', 'fa-solid fa-network-wired', '#a6e3a1', 'Diagramas de flujo interactivos para pipelines de ML y Deep Learning.'],
        ['herr.papers', 'fa-solid fa-book-open', '#fab387', 'Monografías seminales de Machine Learning y algoritmos clave explicados.'],
        ['herr.agentes', 'fa-solid fa-diagram-project', '#89b4fa', 'Estudio de flujos agénticos colaborativos y recursivos.'],
        ['herr.kaggle', 'fa-brands fa-kaggle', '#20beff', 'Notebooks, datasets y competiciones de la comunidad, con un profesor al lado.'],
        ['herr.github', 'fa-brands fa-github', '#e6edf3', 'Busca repositorios o pega su enlace y léelos con el profesor.'],
        ['herr.youtube', 'fa-brands fa-youtube', '#ff0000', 'Videos y clases magistrales de programación y ML con notas de IA.'],
        ['herr.hub', 'fa-solid fa-circle-nodes', '#cba6f7', 'Tus cursos, canales, perfiles y desafíos en texto plano: sigue a otros y comparte los tuyos por GitHub.'],
        ['herr.modelos', 'fa-solid fa-microchip', '#b4befe', 'Ajustes, pruebas, memoria y servidor de tus modelos.'],
        ['herr.buscarModelos', 'fa-solid fa-cloud-arrow-down', '#74c7ec', 'Busca y descarga modelos de Ollama, Hugging Face y ModelScope.'],
        ['herr.modelosServidor', 'fa-solid fa-server', '#94e2d5', 'Servidor de Ollama, estado de servicios y registro.'],
        ['herr.temperaturas', 'fa-solid fa-temperature-half', '#f38ba8', 'GPU, CPU, disco y el límite térmico de la GPU.'],
        ['herr.guiado', 'fa-solid fa-route', '#a6e3a1', 'Planes de estudio por bloques que se van desbloqueando.'],
        ['herr.note', 'fa-solid fa-note-sticky', '#f5c2e7', 'Notas rápidas en una ventana aparte.'],
        ['archivo.exportarPdf', 'fa-solid fa-file-pdf', '#eba0ac', 'Exporta el código y los cuadernos de una carpeta a PDF.'],
        ['config.general', 'fa-solid fa-gear', '#a6adc8', 'IA, editor, apariencia y atajos de teclado.'],
    ];

    const SALUDO = (h) => h < 6 ? 'Buenas noches' : h < 13 ? 'Buenos días' : h < 21 ? 'Buenas tardes' : 'Buenas noches';
    const miles = (n) => n == null ? '—' : n >= 1000 ? `${(n / 1000).toFixed(1)}k` : String(n);
    const gb = (b) => b == null ? '' : `${(b / 1024 ** 3).toFixed(1)} GB`;

    function hace(t) {
        if (!t) return '';
        const d = new Date(String(t).replace(' ', 'T'));
        const min = Math.round((Date.now() - d) / 60000);
        if (isNaN(min)) return '';
        if (min < 1) return 'ahora';
        if (min < 60) return `hace ${min} min`;
        if (min < 1440) return `hace ${Math.round(min / 60)} h`;
        const dias = Math.round(min / 1440);
        return dias === 1 ? 'ayer' : dias < 30 ? `hace ${dias} días` : d.toLocaleDateString('es');
    }

    function md(texto) {
        let html = window.marked ? window.marked.parseInline(String(texto || '')) : esc(texto);
        return window.DOMPurify ? DOMPurify.sanitize(html) : html;
    }

    function comando(id) { return window.PrigCommands && window.PrigCommands.get(id); }
    function ejecutar(id) { if (window.PrigCommands) window.PrigCommands.ejecutar(id); }
    function atajo(id) {
        const a = window.shortcutMgr ? window.shortcutMgr.accel(id) : (comando(id) || {}).accel;
        return a && window.shortcutMgr ? window.shortcutMgr.bonito(a) : (a || '');
    }

    // ================================================================== estilos
    function estilos() {
        if ($('inicio-estilos')) return;
        const css = document.createElement('style');
        css.id = 'inicio-estilos';
        css.textContent = `
          #inicio-raiz { height:100%; overflow-y:auto; background:var(--bg-dark); }
          .in-pagina { max-width:1320px; margin:0 auto; padding:22px 26px 40px; display:grid; grid-template-columns:minmax(0,1.55fr) minmax(0,1fr); gap:18px; }
          .in-ancho { grid-column:1 / -1; }
          .in-tarjeta { background:var(--bg-panel); border:1px solid var(--border-color); border-radius:14px; padding:16px 18px; min-width:0; }
          .in-tarjeta h2 { font-size:14px; color:#fff; margin:0 0 12px; display:flex; align-items:center; gap:8px; }
          .in-tarjeta h2 i { color:var(--accent-blue); }
          .in-tarjeta h2 .in-accion { margin-left:auto; }
          .in-heroe { display:flex; gap:20px; align-items:center; background:linear-gradient(120deg, rgba(137,180,250,.14), rgba(203,166,247,.10) 55%, rgba(32,190,255,.06)); }
          .in-avatar { width:66px; height:66px; border-radius:50%; background:linear-gradient(135deg,#89b4fa,#cba6f7); color:#11111b; font-size:28px; font-weight:800; display:flex; align-items:center; justify-content:center; flex:none; }
          .in-saludo { font-size:24px; font-weight:700; color:#fff; margin:0; }
          .in-sub { color:var(--text-muted); font-size:12.5px; margin-top:3px; }
          .in-cifras { display:flex; gap:10px; margin-left:auto; flex-wrap:wrap; justify-content:flex-end; }
          .in-cifra { background:rgba(0,0,0,.18); border:1px solid rgba(255,255,255,.07); border-radius:10px; padding:8px 14px; min-width:86px; text-align:center; }
          .in-cifra b { display:block; font-size:20px; color:#fff; }
          .in-cifra span { font-size:10.5px; color:var(--text-muted); }
          .in-semana { display:flex; gap:6px; align-items:flex-end; height:52px; margin-top:10px; }
          .in-dia { display:flex; flex-direction:column; align-items:center; gap:3px; font-size:10px; color:var(--text-muted); }
          .in-dia div { width:18px; border-radius:4px; background:rgba(255,255,255,.08); }
          .in-dia.activo div { background:linear-gradient(180deg,#a6e3a1,#94e2d5); }
          .in-dia.hoy { color:#fff; font-weight:700; }
          .in-btn { background:rgba(255,255,255,.05); color:var(--text-main); border:1px solid var(--border-color); border-radius:7px; padding:5px 11px; font-size:11.5px; cursor:pointer; display:inline-flex; gap:6px; align-items:center; white-space:nowrap; }
          .in-btn:hover { border-color:var(--accent-blue); }
          .in-btn.primario { background:var(--accent-blue); border-color:var(--accent-blue); color:#11111b; font-weight:600; }
          .in-fila { display:flex; gap:10px; align-items:center; padding:9px 4px; border-bottom:1px solid rgba(255,255,255,.05); }
          .in-fila:last-child { border-bottom:none; }
          .in-fila.clic { cursor:pointer; border-radius:8px; }
          .in-fila.clic:hover { background:rgba(255,255,255,.04); }
          .in-icono { width:32px; height:32px; border-radius:9px; display:flex; align-items:center; justify-content:center; flex:none; background:rgba(137,180,250,.12); color:var(--accent-blue); }
          .in-texto { flex:1; min-width:0; font-size:12.5px; color:var(--text-main); }
          .in-texto small { display:block; color:var(--text-muted); font-size:11px; margin-top:1px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
          .in-cuando { font-size:10.5px; color:var(--text-muted); white-space:nowrap; }
          .in-barra { height:6px; border-radius:3px; background:rgba(255,255,255,.07); overflow:hidden; }
          .in-barra div { height:100%; background:linear-gradient(90deg,#89b4fa,#cba6f7); }
          .in-herramientas { display:grid; grid-template-columns:repeat(auto-fill, minmax(215px,1fr)); gap:10px; }
          .in-herramienta { position:relative; display:flex; gap:10px; align-items:flex-start; padding:11px; border:1px solid rgba(255,255,255,.07); border-radius:11px; background:rgba(0,0,0,.14); cursor:pointer; transition:border-color .15s, transform .15s; }
          .in-herramienta:hover { border-color:var(--c); transform:translateY(-1px); }
          .in-herramienta .in-icono { background:color-mix(in srgb, var(--c) 18%, transparent); color:var(--c); }
          .in-herramienta b { color:#fff; font-size:12.5px; }
          .in-herramienta p { margin:3px 0 0; font-size:11px; color:var(--text-muted); line-height:1.35; }
          .in-tecla { font-size:9.5px; color:var(--text-muted); border:1px solid var(--border-color); border-radius:4px; padding:0 4px; margin-left:4px; }
          .in-estrella { position:absolute; top:7px; right:8px; background:none; border:none; color:rgba(255,255,255,.25); cursor:pointer; font-size:12px; }
          .in-estrella.activa, .in-estrella:hover { color:#f9e2af; }
          .in-chip { font-size:11px; padding:2px 9px; border-radius:10px; background:rgba(255,255,255,.07); color:var(--text-main); white-space:nowrap; cursor:pointer; border:1px solid transparent; }
          .in-chip:hover { border-color:var(--accent-blue); }
          .in-chip.flojo { background:rgba(243,139,168,.12); color:#f38ba8; }
          .in-chip.fuerte { background:rgba(166,227,161,.12); color:#a6e3a1; }
          .in-modelo-cap { font-size:9.5px; padding:0 6px; border-radius:8px; background:rgba(255,255,255,.07); color:var(--text-muted); }
          .in-badge { font-size:9.5px; padding:1px 7px; border-radius:8px; font-weight:600; }
          .in-badge.verde { background:rgba(166,227,161,.15); color:#a6e3a1; }
          .in-badge.azul { background:rgba(137,180,250,.15); color:#89b4fa; }
          .in-medidor { display:grid; grid-template-columns:repeat(4, 1fr); gap:8px; }
          .in-medidor div { background:rgba(0,0,0,.18); border-radius:9px; padding:8px 10px; }
          .in-medidor span { display:block; font-size:10px; color:var(--text-muted); }
          .in-medidor b { color:#fff; font-size:15px; }
          .in-campo { width:100%; box-sizing:border-box; background:var(--bg-dark); color:var(--text-main); border:1px solid var(--border-color); border-radius:7px; padding:7px 9px; font-size:12.5px; }
          .in-vacio { color:var(--text-muted); font-size:12px; padding:6px 2px; line-height:1.5; }
          .in-error { color:var(--accent-red); font-size:12px; }
          .in-cols { display:grid; grid-template-columns:1fr 1fr; gap:14px; }
          @media (max-width: 1150px) { .in-pagina { grid-template-columns:1fr; } .in-heroe { flex-wrap:wrap; } .in-cifras { margin-left:0; justify-content:flex-start; } }
        `;
        document.head.appendChild(css);
    }

    // ================================================================== carga
    async function cargar() {
        estado.cargando = true;
        try {
            estado.datos = await json('/api/inicio');
            estado.error = null;
        } catch (e) { estado.error = e.message; }
        estado.cargando = false;
        pintar();
    }

    function pintar() {
        const raiz = $('inicio-raiz');
        if (!raiz) return;
        estilos();
        if (!estado.datos) {
            raiz.innerHTML = estado.error
                ? `<div class="in-pagina"><div class="in-tarjeta in-ancho"><div class="in-error">No se pudo cargar el inicio: ${esc(estado.error)}</div>
                     <button class="in-btn" data-recargar style="margin-top:10px;">Reintentar</button></div></div>`
                : '<div class="in-pagina"><div class="in-vacio in-ancho"><i class="fa-solid fa-spinner fa-spin"></i> Preparando tu inicio…</div></div>';
            const r = raiz.querySelector('[data-recargar]');
            if (r) r.onclick = cargar;
            return;
        }
        const d = estado.datos;
        const scroll = raiz.scrollTop;
        raiz.innerHTML = `<div class="in-pagina">
            ${heroe(d)}
            <div style="display:flex; flex-direction:column; gap:18px; min-width:0;">
              ${continuar(d)}
              ${actividad(d)}
            </div>
            <div style="display:flex; flex-direction:column; gap:18px; min-width:0;">
              ${avance(d)}
              ${notas(d)}
              ${modelos(d)}
              ${proyectos(d)}
              ${kaggle(d)}
            </div>
            ${herramientas(d)}
          </div>`;
        raiz.scrollTop = scroll;
        conectar(raiz, d);
    }

    // ------------------------------------------------------------------ perfil y semana
    function heroe(d) {
        const p = d.perfil;
        const prog = d.progreso || {};
        const racha = prog.racha || {};
        const des = prog.desafios || {};
        const resueltos = (des.por_estado || {}).resuelto || 0;
        const leidas = ((d.kaggle || {}).lecturas || []).reduce((s, l) => s + (l.leidas || 0), 0);
        const max = Math.max(1, ...d.semana.map(x => x.n));
        const inicial = (p.nombre || '?').trim()[0] || '?';
        if (estado.editando) {
            return `<div class="in-tarjeta in-heroe in-ancho" style="flex-wrap:wrap;">
                <div class="in-avatar">${esc(inicial.toUpperCase())}</div>
                <div style="flex:1; min-width:260px; display:grid; grid-template-columns:1fr 1fr; gap:8px;">
                  <label class="in-sub">Tu nombre<input class="in-campo" id="in-nombre" maxlength="60" value="${esc(p.nombre)}" placeholder="¿Cómo te llamo?"></label>
                  <label class="in-sub">Nivel<select class="in-campo" id="in-nivel">${['principiante', 'intermedio', 'avanzado'].map(n => `<option ${n === p.nivel ? 'selected' : ''}>${n}</option>`).join('')}</select></label>
                  <label class="in-sub" style="grid-column:1 / -1;">Tu objetivo<input class="in-campo" id="in-objetivo" maxlength="300" value="${esc(p.objetivo)}" placeholder="Por ejemplo: entrar en machine learning y ganar una competición de Kaggle"></label>
                  <label class="in-sub" style="grid-column:1 / -1; display:flex; gap:8px; align-items:center;"><input type="checkbox" id="in-mostrar" ${p.mostrar_al_abrir ? 'checked' : ''}> Abrir esta pantalla al iniciar Prig</label>
                </div>
                <div style="display:flex; flex-direction:column; gap:6px;"><button class="in-btn primario" data-guardar-perfil><i class="fa-solid fa-check"></i> Guardar</button>
                  <button class="in-btn" data-cancelar-perfil>Cancelar</button></div>
              </div>`;
        }
        return `<div class="in-tarjeta in-heroe in-ancho">
            <div class="in-avatar" title="Editar perfil" data-editar-perfil style="cursor:pointer;">${esc(inicial.toUpperCase())}</div>
            <div style="min-width:0;">
              <h1 class="in-saludo">${SALUDO(d.hora)}${p.nombre ? `, ${esc(p.nombre)}` : ''}</h1>
              <div class="in-sub">${p.objetivo ? `<i class="fa-solid fa-flag-checkered"></i> ${esc(p.objetivo)} · ` : ''}nivel ${esc(p.nivel)}
                · <a href="#" data-editar-perfil style="color:var(--accent-blue);">${p.nombre ? 'editar perfil' : 'cuéntame quién eres'}</a>
                · <a href="#" data-abrir-gh-widget style="color:#cba6f7; display:inline-flex; align-items:center; gap:4px;"><i class="fa-brands fa-github"></i> tarjeta GitHub Profile</a></div>
              <div class="in-semana" title="Tu actividad de los últimos 7 días">${d.semana.map((x, i) => `<div class="in-dia ${x.n ? 'activo' : ''} ${i === d.semana.length - 1 ? 'hoy' : ''}" title="${x.fecha}: ${x.n} acciones">
                  <div style="height:${x.n ? 8 + Math.round(30 * x.n / max) : 5}px;"></div>${x.dia}</div>`).join('')}</div>
            </div>
            <div class="in-cifras">
              <div class="in-cifra"><b>${racha.actual || 0}<i class="fa-solid fa-fire" style="color:#fab387; font-size:14px; margin-left:4px;"></i></b><span>días de racha</span></div>
              <div class="in-cifra"><b>${racha.mejor || 0}</b><span>mejor racha</span></div>
              <div class="in-cifra"><b>${resueltos}</b><span>desafíos resueltos</span></div>
              <div class="in-cifra"><b>${racha.dias_activos || 0}</b><span>días activos</span></div>
              <div class="in-cifra"><b>${leidas}</b><span>celdas de Kaggle</span></div>
            </div>
          </div>`;
    }

    // ------------------------------------------------------------------ qué hacer ahora
    function continuar(d) {
        const sig = ((d.progreso || {}).siguientes || []).slice(0, 5);
        const icono = { retomar: 'fa-play', bloque: 'fa-route', kaggle: 'fa-brands fa-kaggle', practicar: 'fa-dumbbell' };
        return `<div class="in-tarjeta"><h2><i class="fa-solid fa-forward"></i> Para seguir</h2>
            ${sig.map((s, i) => `<div class="in-fila clic" data-siguiente="${i}">
                <div class="in-icono"><i class="${(icono[s.tipo] || 'fa-lightbulb').includes('fa-brands') ? icono[s.tipo] : 'fa-solid ' + (icono[s.tipo] || 'fa-lightbulb')}"></i></div>
                <div class="in-texto">${esc(s.texto)}</div>
                <button class="in-btn">${s.tipo === 'retomar' || s.tipo === 'kaggle' ? 'Seguir' : 'Empezar'} <i class="fa-solid fa-arrow-right"></i></button></div>`).join('')
              || `<div class="in-vacio">Aún no hay nada a medias. Prueba un <a href="#" data-cmd="herr.practica" style="color:var(--accent-blue);">desafío</a>,
                  crea un <a href="#" data-cmd="herr.guiado" style="color:var(--accent-blue);">plan de estudios</a> o lee un notebook en
                  <a href="#" data-cmd="herr.kaggle" style="color:var(--accent-blue);">Kaggle</a>.</div>`}
          </div>`;
    }

    // ------------------------------------------------------------------ línea de tiempo
    function actividad(d) {
        const ev = d.actividad || [];
        const color = { desafio: '#cba6f7', kaggle: '#20beff', coleccion: '#f9e2af', datos: '#a6e3a1', ejercicio: '#fab387' };
        return `<div class="in-tarjeta"><h2><i class="fa-solid fa-clock-rotate-left"></i> Actividad reciente
              <button class="in-btn in-accion" data-cmd="herr.perfil">Historial completo</button></h2>
            ${ev.map((e, i) => `<div class="in-fila ${e.abrir ? 'clic' : ''}" data-evento="${i}">
                <div class="in-icono" style="background:color-mix(in srgb, ${color[e.tipo] || '#89b4fa'} 16%, transparent); color:${color[e.tipo] || '#89b4fa'};"><i class="fa-solid ${esc(e.icono)}"></i></div>
                <div class="in-texto">${esc(e.texto)}${e.detalle ? `<small>${esc(e.detalle)}</small>` : ''}</div>
                <span class="in-cuando">${hace(e.fecha)}</span></div>`).join('')
              || '<div class="in-vacio">Todavía no hay actividad. Lo que hagas en desafíos, ejercicios, Kaggle o tus colecciones aparecerá aquí.</div>'}
          </div>`;
    }

    // ------------------------------------------------------------------ avance
    function avance(d) {
        const prog = d.progreso || {};
        const act = (prog.actividades || []).filter(a => a.total);
        const fuertes = (prog.fuertes || []).slice(0, 5);
        const flojos = (prog.flojos || []).slice(0, 5);
        const nombre = (c) => typeof c === 'string' ? c : (c.concepto || '');
        return `<div class="in-tarjeta"><h2><i class="fa-solid fa-chart-simple"></i> Tu avance
              <button class="in-btn in-accion" data-cmd="herr.perfil">Ver perfil</button></h2>
            ${act.map(a => `<div style="margin-bottom:9px;"><div style="display:flex; font-size:12px; margin-bottom:3px;"><span style="flex:1;">${esc(a.nombre)}</span>
                <span style="color:var(--text-muted);">${a.hechos} / ${a.total}</span></div>
                <div class="in-barra"><div style="width:${Math.round(100 * a.hechos / a.total)}%;"></div></div></div>`).join('')
              || '<div class="in-vacio">Cuando completes desafíos, bloques del plan o notebooks, aquí verás cuánto llevas de cada cosa.</div>'}
            ${fuertes.length || flojos.length ? `<div style="margin-top:10px; display:flex; flex-wrap:wrap; gap:5px; align-items:center;">
                ${fuertes.map(c => `<span class="in-chip fuerte" data-practicar="${esc(nombre(c))}" title="Dominas este concepto">${esc(nombre(c))}</span>`).join('')}
                ${flojos.map(c => `<span class="in-chip flojo" data-practicar="${esc(nombre(c))}" title="Practicar este concepto">${esc(nombre(c))}</span>`).join('')}</div>` : ''}
          </div>`;
    }

    // ------------------------------------------------------------------ modelos y máquina
    function modelos(d) {
        const lista = (d.modelos || []).filter(m => !(m.capacidades || []).includes('embedding'));
        const cargados = new Set((d.cargados || []).map(m => m.nombre));
        const t = d.temperaturas || {};
        const s = d.sistema || {};
        const g = (s.gpu || {});
        const gem = d.gemini || {};
        const errorModelos = (d.errores || {}).modelos;
        return `<div class="in-tarjeta"><h2><i class="fa-solid fa-microchip"></i> Modelos y máquina
              <button class="in-btn in-accion" data-cmd="herr.buscarModelos"><i class="fa-solid fa-plus"></i> Más modelos</button></h2>
            <div class="in-medidor" style="margin-bottom:10px;">
              <div><span>GPU</span><b style="color:${t.gpu >= (t.limite || 80) - 3 ? 'var(--accent-red)' : '#fff'};">${t.gpu != null ? Math.round(t.gpu) + ' °C' : '—'}</b></div>
              <div><span>VRAM</span><b>${g.has_gpu ? `${(g.vram_used_mb / 1024).toFixed(1)}/${(g.vram_total_mb / 1024).toFixed(0)} GB` : '—'}</b></div>
              <div><span>RAM</span><b>${s.ram_total_gb ? `${s.ram_used_gb}/${Math.round(s.ram_total_gb)} GB` : '—'}</b></div>
              <div><span>CPU</span><b>${t.cpu != null ? Math.round(t.cpu) + ' °C' : (s.cpu_pct != null ? s.cpu_pct + '%' : '—')}</b></div>
            </div>
            ${errorModelos ? `<div class="in-error" style="margin-bottom:8px;">Ollama no responde: ${esc(errorModelos)}</div>` : ''}
            <div style="max-height:250px; overflow-y:auto;">${lista.map(m => `<div class="in-fila clic" data-modelo="${esc(m.nombre)}" title="Abrir en Modelos">
                <div class="in-icono" style="width:28px; height:28px;"><i class="fa-solid fa-cube"></i></div>
                <div class="in-texto" style="font-size:12px;"><span style="font-family:'Fira Code',monospace;">${esc(m.nombre.replace(/^hf\.co\//, ''))}</span>
                  <small>${esc(m.parametros || '')} · ${gb(m.bytes)} ${(m.capacidades || []).filter(c => c !== 'completion').map(c => `<span class="in-modelo-cap">${esc(c)}</span>`).join(' ')}</small></div>
                ${m.nombre === d.modelo_tutor ? '<span class="in-badge azul" title="Modelo del tutor">tutor</span>' : ''}
                ${cargados.has(m.nombre) ? '<span class="in-badge verde" title="Cargado en memoria">en memoria</span>' : ''}</div>`).join('')
              || (errorModelos ? '' : '<div class="in-vacio">No tienes modelos locales. Busca uno pequeño para empezar (p. ej. qwen2.5-coder:1.5b).</div>')}</div>
            <div class="in-fila" style="margin-top:4px;">
              <div class="in-icono" style="width:28px; height:28px; background:rgba(66,133,244,.14); color:#8ab4f8;"><i class="fa-brands fa-google"></i></div>
              <div class="in-texto" style="font-size:12px;">Google Gemini<small>${gem.configurado ? `conectado · clave ${esc(gem.clave || '')}` : 'sin conectar · opcional, para desafíos y el profesor'}</small></div>
              <button class="in-btn" data-cmd="herr.practica">${gem.configurado ? 'Usar' : 'Conectar'}</button></div>
          </div>`;
    }

    // ------------------------------------------------------------------ proyectos
    function proyectos(d) {
        const actual = d.proyecto || {};
        const otros = (d.recientes || []).filter(r => r.path !== actual.path).slice(0, 5);
        return `<div class="in-tarjeta"><h2><i class="fa-solid fa-folder-tree"></i> Proyectos
              <button class="in-btn in-accion" data-cmd="archivo.abrirCarpeta"><i class="fa-solid fa-folder-open"></i> Abrir…</button></h2>
            ${actual.path ? `<div class="in-fila clic" data-ir-editor><div class="in-icono" style="background:rgba(166,227,161,.14); color:#a6e3a1;"><i class="fa-solid fa-folder-open"></i></div>
                <div class="in-texto"><b style="color:#fff;">${esc(actual.name)}</b><small>${esc(actual.path)}</small></div><span class="in-badge verde">abierto</span></div>` : ''}
            ${otros.map(r => `<div class="in-fila clic" data-carpeta="${esc(r.path)}"><div class="in-icono"><i class="fa-regular fa-folder"></i></div>
                <div class="in-texto">${esc(r.name)}<small>${esc(r.path)}</small></div></div>`).join('')}
            ${!otros.length ? '<div class="in-vacio">Las carpetas que abras aparecerán aquí para volver a ellas con un clic.</div>' : ''}
          </div>`;
    }

    // ------------------------------------------------------------------ kaggle
    function kaggle(d) {
        const k = d.kaggle || {};
        const lecturas = (k.lecturas || []).filter(l => l.total && l.leidas < l.total).slice(0, 3);
        const cols = (k.colecciones || []).slice(0, 4);
        return `<div class="in-tarjeta"><h2><i class="fa-brands fa-kaggle" style="color:#20beff;"></i> Kaggle
              <button class="in-btn in-accion" data-cmd="herr.kaggle">Explorar</button></h2>
            ${lecturas.map(l => `<div class="in-fila clic" data-kaggle='${esc(JSON.stringify({ tipo: 'notebook', ref: l.ref, celda: l.ultima_celda }))}'>
                <div class="in-icono" style="background:rgba(32,190,255,.14); color:#20beff;"><i class="fa-solid fa-book-open-reader"></i></div>
                <div class="in-texto">${esc(l.titulo)}<div class="in-barra" style="margin-top:5px;"><div style="width:${Math.round(100 * l.leidas / l.total)}%;"></div></div></div>
                <span class="in-cuando">${l.leidas}/${l.total}</span></div>`).join('')}
            ${cols.length ? `<div style="display:flex; flex-wrap:wrap; gap:6px; margin-top:${lecturas.length ? 10 : 0}px;">${cols.map(c => `<span class="in-chip" data-kaggle='${esc(JSON.stringify({ tipo: 'coleccion', ref: c.id }))}'>
                <span style="display:inline-block; width:8px; height:8px; border-radius:50%; background:${esc(c.color)}; margin-right:5px;"></span>${esc(c.nombre)} · ${c.total}</span>`).join('')}</div>` : ''}
            ${!lecturas.length && !cols.length ? `<div class="in-vacio">Lee notebooks de la comunidad celda a celda con el profesor, explora datasets y guárdalos en colecciones.
                ${k.cuenta && k.cuenta.conectado ? '' : 'Los datasets funcionan sin cuenta.'}</div>` : ''}
          </div>`;
    }

    // ------------------------------------------------------------------ notas unificadas
    function obtenerNotasUnificadas(d) {
        const todas = [];

        // 1. YouTube: fotogramas y marcas
        try {
            if (window.YouTubeHub && typeof window.YouTubeHub.obtenerTodasLasNotas === 'function') {
                const ytNotas = window.YouTubeHub.obtenerTodasLasNotas();
                ytNotas.forEach(y => {
                    todas.push({
                        origen: 'youtube',
                        id: y.id,
                        videoId: y.videoId,
                        videoTitulo: y.videoTitulo || 'Video de YouTube',
                        titulo: y.titulo || 'Nota visual',
                        minuto: y.minuto || '00:00',
                        segundos: y.segundos || 0,
                        texto: y.texto || '',
                        imagenUrl: y.imagenUrl || '',
                        fecha: y.fecha || 0
                    });
                });
            } else {
                const rawIdx = localStorage.getItem('prig_yt_indice_fotogramas');
                if (rawIdx) {
                    const idx = JSON.parse(rawIdx);
                    Object.values(idx).forEach(f => {
                        todas.push({
                            origen: 'youtube',
                            id: f.id,
                            videoId: f.videoId,
                            videoTitulo: f.videoTitulo || 'Video de YouTube',
                            titulo: f.titulo || 'Nota visual',
                            minuto: f.minuto || '00:00',
                            segundos: f.segundos || 0,
                            texto: f.explicacion || '',
                            imagenUrl: f.imagenUrl || '',
                            fecha: f.fecha || 0
                        });
                    });
                }
            }
        } catch (e) { /* continuar */ }

        // 2. Kaggle: items con nota en colecciones
        try {
            const kRecientes = (d.kaggle && d.kaggle.recientes) || [];
            kRecientes.forEach(it => {
                if (it.nota && it.nota.trim()) {
                    todas.push({
                        origen: 'kaggle',
                        id: `kg_${it.tipo}_${it.ref}`,
                        ref: it.ref,
                        tipoItem: it.tipo,
                        coleccion: it.coleccion || 'Kaggle',
                        titulo: it.titulo || it.ref,
                        texto: it.nota,
                        color: it.color || '#20beff',
                        fecha: it.anadido ? new Date(it.anadido).getTime() : 0
                    });
                }
            });
        } catch (e) { /* continuar */ }

        // 3. Notas rápidas (Prig Note)
        try {
            const rapida = localStorage.getItem('prig_note_saved_content');
            if (rapida && rapida.trim()) {
                todas.push({
                    origen: 'rapidas',
                    id: 'prig_rapida',
                    titulo: 'Nota Rápida',
                    texto: rapida.slice(0, 240),
                    fecha: 0
                });
            }
        } catch (e) { /* continuar */ }

        return todas.sort((a, b) => (b.fecha || 0) - (a.fecha || 0));
    }

    function notas(d) {
        const todas = obtenerNotasUnificadas(d);
        const ytCount = todas.filter(n => n.origen === 'youtube').length;
        const kgCount = todas.filter(n => n.origen === 'kaggle').length;
        const rapCount = todas.filter(n => n.origen === 'rapidas').length;

        const filtro = estado.filtroNotas || 'todas';
        const filtradas = filtro === 'todas' ? todas : todas.filter(n => n.origen === filtro);
        const visibles = filtradas.slice(0, 5);

        return `<div class="in-tarjeta">
            <h2>
              <i class="fa-solid fa-note-sticky" style="color:#f5c2e7;"></i> Apuntes y Notas
              <span class="in-sub" style="margin:0 0 0 6px; font-weight:400;">(${todas.length})</span>
              <button class="in-btn in-accion" data-cmd="herr.youtube" title="Abrir clases y notas en YouTube"><i class="fa-brands fa-youtube" style="color:#ff5555;"></i> YouTube</button>
            </h2>

            <div style="display:flex; gap:6px; flex-wrap:wrap; margin-bottom:10px;">
              <span class="in-chip ${filtro === 'todas' ? 'fuerte' : ''}" data-filtro-nota="todas">Todas (${todas.length})</span>
              <span class="in-chip ${filtro === 'youtube' ? 'fuerte' : ''}" data-filtro-nota="youtube"><i class="fa-brands fa-youtube" style="color:#ff5555;"></i> YouTube (${ytCount})</span>
              <span class="in-chip ${filtro === 'kaggle' ? 'fuerte' : ''}" data-filtro-nota="kaggle"><i class="fa-brands fa-kaggle" style="color:#20beff;"></i> Kaggle (${kgCount})</span>
              ${rapCount > 0 ? `<span class="in-chip ${filtro === 'rapidas' ? 'fuerte' : ''}" data-filtro-nota="rapidas"><i class="fa-solid fa-file-lines" style="color:#f5c2e7;"></i> Rápidas (${rapCount})</span>` : ''}
            </div>

            ${visibles.length === 0 ? `
              <div class="in-vacio">
                No hay notas todavía en esta categoría. Puedes capturar fotogramas con explicaciones mientras miras videos en <a href="#" data-cmd="herr.youtube" style="color:var(--accent-blue);">YouTube</a> o agregar notas a tus notebooks de <a href="#" data-cmd="herr.kaggle" style="color:var(--accent-blue);">Kaggle</a>.
              </div>
            ` : `
              <div style="display:flex; flex-direction:column; gap:4px;">
                ${visibles.map((n) => {
                    if (n.origen === 'youtube') {
                        return `<div class="in-fila clic" data-nota-yt="${esc(JSON.stringify({ videoId: n.videoId, segundos: n.segundos }))}">
                            <div style="width:48px; height:30px; border-radius:5px; overflow:hidden; flex-shrink:0; background:#11111b; border:1px solid rgba(255,255,255,0.12); position:relative; display:flex; align-items:center; justify-content:center;">
                              <img src="${esc(n.imagenUrl || (n.videoId ? `https://i.ytimg.com/vi/${n.videoId}/0.jpg` : ''))}" style="width:100%; height:100%; object-fit:cover;" alt="Fotograma" onerror="if(window.prigYtImgFallback){window.prigYtImgFallback(this, '${esc(n.videoId)}', '', '${esc(n.titulo)}');}else{this.src='https://i.ytimg.com/vi/${esc(n.videoId)}/0.jpg';}">
                            </div>
                            <div class="in-texto" style="font-size:12px;">
                              <div style="display:flex; align-items:center; gap:6px;">
                                <span class="in-badge azul" style="font-size:9px; padding:1px 5px;"><i class="fa-regular fa-clock"></i> ${esc(n.minuto)}</span>
                                <b style="color:#fff; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">${esc(n.titulo)}</b>
                              </div>
                              <small style="color:var(--text-muted);">${esc(n.videoTitulo)} ${n.texto ? `· ${esc(n.texto)}` : ''}</small>
                            </div>
                            <span class="in-cuando"><i class="fa-solid fa-play" style="font-size:9px; color:var(--accent-blue);"></i></span>
                          </div>`;
                    } else if (n.origen === 'kaggle') {
                        return `<div class="in-fila clic" data-kaggle='${esc(JSON.stringify({ tipo: n.tipoItem, ref: n.ref }))}'>
                            <div class="in-icono" style="width:28px; height:28px; background:color-mix(in srgb, ${n.color || '#20beff'} 16%, transparent); color:${n.color || '#20beff'};">
                              <i class="fa-brands fa-kaggle"></i>
                            </div>
                            <div class="in-texto" style="font-size:12px;">
                              <b style="color:#fff;">${esc(n.titulo)}</b>
                              <small><span class="in-badge" style="font-size:9px; background:rgba(255,255,255,0.06); color:var(--text-muted);">${esc(n.coleccion)}</span> ${esc(n.texto)}</small>
                            </div>
                          </div>`;
                    } else {
                        return `<div class="in-fila clic" data-cmd="herr.note">
                            <div class="in-icono" style="width:28px; height:28px; background:rgba(245,194,231,0.14); color:#f5c2e7;">
                              <i class="fa-solid fa-file-lines"></i>
                            </div>
                            <div class="in-texto" style="font-size:12px;">
                              <b style="color:#fff;">${esc(n.titulo)}</b>
                              <small>${esc(n.texto)}</small>
                            </div>
                          </div>`;
                    }
                }).join('')}
              </div>
            `}
          </div>`;
    }

    // ------------------------------------------------------------------ herramientas
    function herramientas(d) {
        const favoritas = d.perfil.favoritas || [];
        const disponibles = HERRAMIENTAS.filter(([id]) => comando(id));
        const orden = [...disponibles.filter(([id]) => favoritas.includes(id)), ...disponibles.filter(([id]) => !favoritas.includes(id))];
        const visibles = estado.todasHerramientas ? orden : orden.slice(0, Math.max(8, favoritas.length));
        return `<div class="in-tarjeta in-ancho"><h2><i class="fa-solid fa-layer-group"></i> Secciones
              <span class="in-sub" style="margin:0; font-weight:400;">· marca tus favoritas con <i class="fa-solid fa-star" style="color:#f9e2af;"></i> para tenerlas primero</span>
              <button class="in-btn in-accion" data-todas>${estado.todasHerramientas ? 'Ver menos' : `Ver todas (${orden.length})`}</button></h2>
            <div class="in-herramientas">${visibles.map(([id, icono, color, texto]) => {
                const c = comando(id);
                const tecla = atajo(id);
                return `<div class="in-herramienta" data-cmd="${id}" style="--c:${color};">
                    <div class="in-icono"><i class="${icono}"></i></div>
                    <div style="min-width:0; padding-right:14px;"><b>${esc(c.label.replace(/…$/, ''))}</b>${tecla ? `<span class="in-tecla">${esc(tecla)}</span>` : ''}<p>${esc(texto)}</p></div>
                    <button class="in-estrella ${favoritas.includes(id) ? 'activa' : ''}" data-favorita="${id}" title="${favoritas.includes(id) ? 'Quitar de favoritas' : 'Marcar como favorita'}"><i class="fa-solid fa-star"></i></button>
                  </div>`;
            }).join('')}</div>
            <div class="in-sub" style="margin-top:10px;">Todos los comandos, con su atajo: <span class="in-tecla">F1</span> o <span class="in-tecla">Ctrl+Shift+P</span>.</div>
          </div>`;
    }

    // ================================================================== acciones
    function conectar(raiz, d) {
        raiz.querySelectorAll('[data-editar-perfil]').forEach(el => el.onclick = (e) => { e.preventDefault(); estado.editando = true; pintar(); setTimeout(() => { const n = $('in-nombre'); if (n) n.focus(); }, 20); });
        raiz.querySelectorAll('[data-abrir-gh-widget]').forEach(el => el.onclick = (e) => { e.preventDefault(); if (window.GitHubWidget) window.GitHubWidget.abrir(); });
        const cancelar = raiz.querySelector('[data-cancelar-perfil]');
        if (cancelar) cancelar.onclick = () => { estado.editando = false; pintar(); };
        const guardar = raiz.querySelector('[data-guardar-perfil]');
        if (guardar) {
            const hacer = async () => {
                try {
                    d.perfil = await enviar('/api/inicio/perfil', { nombre: $('in-nombre').value, objetivo: $('in-objetivo').value,
                                                                   nivel: $('in-nivel').value, mostrar_al_abrir: $('in-mostrar').checked }, 'PATCH');
                    recordar(d.perfil.mostrar_al_abrir);
                    estado.editando = false;
                    pintar();
                } catch (e) { guardar.insertAdjacentHTML('afterend', `<div class="in-error">${esc(e.message)}</div>`); }
            };
            guardar.onclick = hacer;
            raiz.querySelectorAll('.in-heroe input.in-campo').forEach(i => i.onkeydown = (e) => { if (e.key === 'Enter') hacer(); if (e.key === 'Escape') cancelar.click(); });
        }
        raiz.querySelectorAll('[data-cmd]').forEach(el => el.onclick = (e) => {
            if (e.target.closest('[data-favorita]')) return;
            e.preventDefault();
            ejecutar(el.dataset.cmd);
        });
        raiz.querySelectorAll('[data-favorita]').forEach(b => b.onclick = async (e) => {
            e.stopPropagation();
            const id = b.dataset.favorita;
            const favs = new Set(d.perfil.favoritas || []);
            if (favs.has(id)) favs.delete(id); else favs.add(id);
            d.perfil.favoritas = [...favs];
            pintar();
            try { d.perfil = await enviar('/api/inicio/perfil', { favoritas: d.perfil.favoritas }, 'PATCH'); } catch (err) { /* se queda en pantalla */ }
        });
        const todas = raiz.querySelector('[data-todas]');
        if (todas) todas.onclick = () => { estado.todasHerramientas = !estado.todasHerramientas; pintar(); };
        raiz.querySelectorAll('[data-siguiente]').forEach(el => el.onclick = () => {
            const s = d.progreso.siguientes[+el.dataset.siguiente];
            if (!window.Desafios && s.tipo !== 'kaggle') return;
            if (s.desafio_id) window.Desafios.abrir({ id: s.desafio_id });
            else if (s.tipo === 'kaggle' && window.KaggleLector) window.KaggleLector.abrir({ ref: s.ref, celda: s.celda });
            else if (s.ruta_id) window.Desafios.abrir({ rutaId: s.ruta_id, bloqueId: s.bloque_id });
            else window.Desafios.abrir({ tema: s.tema });
        });
        raiz.querySelectorAll('[data-evento]').forEach(el => el.onclick = () => {
            const ev = d.actividad[+el.dataset.evento];
            const a = ev && ev.abrir;
            if (!a) return;
            if (a.desafio && window.Desafios) window.Desafios.abrir({ id: a.desafio });
            else if (a.kaggle && window.KaggleLector) window.KaggleLector.abrir(a.kaggle);
        });
        raiz.querySelectorAll('[data-kaggle]').forEach(el => el.onclick = () => {
            if (window.KaggleLector) window.KaggleLector.abrir(JSON.parse(el.dataset.kaggle));
        });
        raiz.querySelectorAll('[data-filtro-nota]').forEach(chip => {
            chip.onclick = () => {
                estado.filtroNotas = chip.dataset.filtroNota;
                pintar();
            };
        });
        raiz.querySelectorAll('[data-nota-yt]').forEach(el => {
            el.onclick = () => {
                try {
                    const info = JSON.parse(el.dataset.notaYt);
                    if (window.YouTubeHub) {
                        window.YouTubeHub.abrir({
                            id: info.videoId,
                            segundos: info.segundos,
                            tab: 'notas',
                            subtab: 'fotogramas'
                        });
                    }
                } catch (e) {
                    if (window.YouTubeHub) window.YouTubeHub.abrir({ tab: 'notas' });
                }
            };
        });
        raiz.querySelectorAll('[data-practicar]').forEach(el => el.onclick = () => { if (window.Desafios) window.Desafios.abrir({ tema: el.dataset.practicar }); });
        raiz.querySelectorAll('[data-modelo]').forEach(el => el.onclick = () => { if (window.Modelos) window.Modelos.abrir(); });
        raiz.querySelectorAll('[data-carpeta]').forEach(el => el.onclick = async () => {
            if (window.IDE && window.IDE.cambiarCarpeta) {
                await window.IDE.cambiarCarpeta(el.dataset.carpeta);
                cargar();
            }
        });
        const editor = raiz.querySelector('[data-ir-editor]');
        if (editor) editor.onclick = () => { if (window.workArea) window.workArea.activar('editor'); };
    }

    // ================================================================== entrada
    function abrir() {
        if (window.workArea) window.workArea.abrirHerramienta('modal-inicio', 'Inicio', 'fa-house');
    }

    document.addEventListener('prig:herramienta-abierta', (e) => {
        if (e.detail && e.detail.modalId === 'modal-inicio') {
            pintar();
            cargar();
        }
    });

    // Al arrancar, Prig abre directamente en Inicio (sin pasar antes por el editor). La
    // preferencia se recuerda en el navegador para decidir sin esperar al servidor, y se
    // sincroniza después con el perfil guardado.
    const CLAVE_ABRIR = 'prig_inicio_al_abrir';
    const leer = () => { try { return localStorage.getItem(CLAVE_ABRIR); } catch (e) { return null; } };
    const recordar = (v) => { try { localStorage.setItem(CLAVE_ABRIR, v ? '1' : '0'); } catch (e) { /* sin almacenamiento */ } };

    function arrancar() {
        if (leer() !== '0') abrir();
        json('/api/inicio/perfil').then(p => {
            recordar(p.mostrar_al_abrir);
            if (p.mostrar_al_abrir && !(window.workArea && window.workArea.vistas.some(v => v.id === 'h:modal-inicio'))) abrir();
        }).catch(() => { /* sin backend: se queda como está */ });
    }
    // app.js monta el área de trabajo en DOMContentLoaded; esto va justo después
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', () => setTimeout(arrancar, 0));
    else setTimeout(arrancar, 0);

    window.Inicio = { abrir, recargar: cargar, estado };
})();
