/**
 * Recomendado: gestor de recursos de la máquina.
 *
 * Analiza la máquina (GPU, VRAM, RAM, CPU, sistema, Ollama), da un veredicto para
 * cada modelo instalado según el uso (tutor, extracción, flujos, revisión) y
 * propone cómo abrirlo: contexto, caché y cuánto mantenerlo cargado.
 *
 * Nada se aplica sin enseñar antes qué cambia. "Probar" carga el modelo de verdad
 * unos segundos, mide y lo descarga; lo medido corrige las estimaciones siguientes.
 * "Restaurar" vuelve a lo que había antes de la primera vez que se aplicó.
 */
(function () {
  const $ = (id) => document.getElementById(id);
  const esc = (t) => String(t ?? '').replace(/[&<>"']/g,
    (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

  const estado = {
    perfil: 'tutor', tirador: 'equilibrado', maquina: null, modelos: [],
    elegido: null, rec: null, perfiles: [], tiradores: [], ocupado: false,
  };

  const COLOR = {
    entero: 'var(--accent-green)', ajustando: 'var(--accent-green)',
    parcial: 'var(--accent-yellow)', solo_cpu: 'var(--accent-yellow)',
    lento: 'var(--accent-red)', no_viable: 'var(--accent-red)', embeddings: 'var(--text-muted)',
  };
  const CAMPOS = {
    agent1_model: 'Modelo del tutor', num_ctx: 'Contexto (num_ctx)', num_gpu: 'Capas en GPU',
    keep_alive: 'Mantener cargado', modelo: 'Modelo', think: 'Pensar en voz alta',
  };

  function valorBonito(campo, v) {
    if (v === null || v === undefined) return '—';
    if (campo === 'num_gpu') return Number(v) < 0 ? 'automático' : `${v} capas`;
    if (campo === 'num_ctx') return `${Number(v).toLocaleString('es')} tokens`;
    if (campo === 'think') return v ? 'sí' : 'no';
    return String(v);
  }

  // ------------------------------------------------------------------ modal
  function crearModal() {
    if ($('modal-recursos')) return;
    document.body.insertAdjacentHTML('beforeend', `
      <div id="modal-recursos" class="modal-overlay" style="display:none; position:fixed; inset:0;
        background:rgba(0,0,0,0.6); z-index:10050; justify-content:center; align-items:center;">
        <div class="modal-content" style="width:1120px; max-width:97vw; height:90vh; display:flex;
          flex-direction:column; background:var(--bg-panel); border:1px solid var(--border-color);
          border-radius:10px; overflow:hidden;">
          <div class="modal-header" style="display:flex; justify-content:space-between; align-items:center;
            padding:12px 16px; border-bottom:1px solid var(--border-color);">
            <h3 style="margin:0; display:flex; gap:8px; align-items:center; font-size:15px;">
              <i class="fa-solid fa-star" style="color:var(--accent-yellow);"></i> Recomendado
              <span style="font-size:11px; font-weight:normal; color:var(--text-muted);">
                gestor de recursos de tu máquina</span>
            </h3>
            <button class="modal-close-btn" id="rec-cerrar" title="Cerrar"><i class="fa-solid fa-xmark"></i></button>
          </div>
          <div style="flex:1; overflow:auto; padding:14px 16px; display:flex; flex-direction:column; gap:14px;
            font-size:12px;">
            <section id="rec-maquina"></section>
            <section id="rec-uso"></section>
            <section id="rec-modelos"></section>
            <section id="rec-detalle"></section>
            <section id="rec-log" style="display:none;"></section>
          </div>
        </div>
      </div>`);
    $('rec-cerrar').onclick = cerrar;
    $('modal-recursos').addEventListener('mousedown', (e) => {
      if (e.target.id === 'modal-recursos' && !estado.ocupado) cerrar();
    });
  }

  function cerrar() {
    if (estado.ocupado && !confirm('Hay una prueba en marcha. ¿Cancelarla y cerrar?')) return;
    if (estado.ocupado) fetch('/api/recursos/cancelar', { method: 'POST' }).catch(() => {});
    $('modal-recursos').style.display = 'none';
  }

  async function abrir(perfil) {
    crearModal();
    if (perfil) estado.perfil = perfil;
    $('modal-recursos').style.display = 'flex';
    $('rec-maquina').innerHTML = cargando('Analizando la máquina…');
    $('rec-modelos').innerHTML = '';
    $('rec-detalle').innerHTML = '';
    try {
      if (!estado.perfiles.length) {
        const p = await prigFetchJson('/api/recursos/perfiles');
        estado.perfiles = p.perfiles;
        estado.tiradores = p.tiradores;
      }
      await cargarMaquina();
      pintarUso();
      await cargarModelos(true);
    } catch (e) {
      $('rec-maquina').innerHTML = error(`No se pudo analizar la máquina: ${e.message}`);
    }
  }

  const cargando = (t) => `<div style="color:var(--text-muted); padding:10px;">
    <i class="fa-solid fa-spinner fa-spin"></i> ${esc(t)}</div>`;
  const error = (t) => `<div style="color:var(--accent-red); padding:10px;">
    <i class="fa-solid fa-triangle-exclamation"></i> ${esc(t)}</div>`;
  const titulo = (icono, t, extra = '') => `<div style="display:flex; align-items:center; gap:8px;
    margin-bottom:8px; font-weight:600; color:#eee; font-size:12.5px;">
    <i class="fa-solid ${icono}" style="color:var(--accent-blue);"></i> ${t}
    <span style="flex:1"></span>${extra}</div>`;
  const boton = (id, html, color = 'var(--accent-blue)', extra = '') => `<button id="${id}" ${extra}
    style="font-size:11.5px; padding:5px 11px; border-radius:5px; cursor:pointer; font-weight:600;
    background:color-mix(in srgb, ${color} 15%, transparent); color:${color};
    border:1px solid color-mix(in srgb, ${color} 45%, transparent);">${html}</button>`;

  // ------------------------------------------------------------------ máquina
  async function cargarMaquina(fresca = false) {
    estado.maquina = await prigFetchJson(`/api/recursos/maquina${fresca ? '?fresca=true' : ''}`);
    pintarMaquina();
  }

  function pintarMaquina() {
    const m = estado.maquina;
    const r = m.resumen;
    const g = (m.gpus || [])[0];
    const cpu = m.cpu || {};
    const mem = m.memoria || {};
    const srv = m.servidor || {};
    const vivo = m.vivo || {};
    const origen = (o) => o === 'medido'
      ? '<span style="color:var(--accent-green); font-size:10px;" title="Medido en tu máquina">medido</span>'
      : '<span style="color:var(--text-muted); font-size:10px;" title="Valor típico; calibra para medirlo">estimado</span>';
    const gb = (b) => (b / 1e9).toFixed(1);
    const temp = g && g.temperatura_c != null
      ? `<span style="color:${{ caliente: 'var(--accent-red)', templado: 'var(--accent-yellow)' }[vivo.termico] || 'var(--accent-green)'};">
          ${Math.round(g.temperatura_c)} °C</span>` : '';
    const dueno = { prig: 'arrancado por Prig', systemd: 'servicio del sistema',
      'systemd-usuario': 'servicio de usuario', usuario: 'lanzado a mano' }[srv.dueno] || 'no responde';
    const flags = [cpu.avx2 && 'AVX2', cpu.avx512 && 'AVX-512', cpu.amx && 'AMX'].filter(Boolean).join(' · ');
    const celda = (etq, val, sub = '') => `<div style="background:rgba(0,0,0,0.18); border-radius:6px;
      padding:8px 10px; min-width:0;"><div style="font-size:10px; color:var(--text-muted);">${etq}</div>
      <div style="font-size:12.5px; color:#fff; margin-top:2px; overflow:hidden; text-overflow:ellipsis;">${val}</div>
      ${sub ? `<div style="font-size:10.5px; color:var(--text-muted); margin-top:2px;">${sub}</div>` : ''}</div>`;

    const calibrada = !!m.calibracion;
    $('rec-maquina').innerHTML = `
      ${titulo('fa-microchip', 'Tu máquina',
        `${boton('rec-reanalizar', '<i class="fa-solid fa-rotate"></i> Volver a analizar', 'var(--text-muted)')}
         ${boton('rec-calibrar', `<i class="fa-solid fa-gauge-high"></i> ${calibrada ? 'Recalibrar' : 'Calibrar'}`,
           'var(--accent-purple)', 'title="Carga uno o dos modelos instalados unos segundos para medir tu GPU y tu RAM. Se descargan al terminar."')}`)}
      <div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(190px, 1fr)); gap:8px;">
        ${celda('GPU', g ? esc(g.nombre) : 'sin GPU dedicada',
          g ? `${gb(r.vram_total_gb * 1e9)} GB · ${temp} ${g.cuda ? `· CUDA ${esc(g.cuda)}` : ''}` : 'los modelos irán en CPU')}
        ${celda('Hasta dónde llena la GPU', `${r.presupuesto_gpu_gb} GB ${origen(r.origen.presupuesto)}`,
          `ancho GPU ${r.ancho_gpu_gbps} GB/s ${origen(r.origen.ancho_gpu)}`)}
        ${celda('RAM', `${gb(mem.ram_disponible || 0)} GB libres de ${gb(mem.ram_total || 0)}`,
          `ancho RAM ${r.ancho_cpu_gbps} GB/s ${origen(r.origen.ancho_cpu)}`)}
        ${celda('CPU', esc(cpu.modelo || '—'), `${cpu.nucleos_fisicos || '?'} núcleos ${flags ? '· ' + flags : ''}`)}
        ${celda('Sistema', esc((m.sistema || {}).distribucion || (m.sistema || {}).so || '—'),
          (m.energia || {}).portatil ? `portátil${m.energia.con_bateria ? ' · <b style="color:var(--accent-yellow);">con batería</b>' : ''}` : '')}
        ${celda('Ollama', srv.version ? `v${esc(srv.version)}` : 'no responde',
          `${esc(dueno)} · caché ${esc((srv.efectivo || {}).kv || 'f16')} · ${(srv.efectivo || {}).paralelo || 1} ranura(s)`)}
      </div>
      ${(vivo.avisos || []).map((a) => `<div style="margin-top:7px; padding:6px 10px; border-radius:5px;
          background:rgba(249,226,175,0.08); border-left:3px solid var(--accent-yellow); color:var(--accent-yellow);">
          <i class="fa-solid fa-circle-exclamation"></i> ${esc(a)}</div>`).join('')}
      ${!calibrada ? `<div style="margin-top:7px; color:var(--text-muted); font-size:11px;">
          Las cifras son estimaciones con valores típicos (error medido: memoria ±1 %, velocidad ±25 %).
          <b>Calibrar</b> las sustituye por medidas de tu equipo.</div>` : ''}`;
    $('rec-reanalizar').onclick = async () => {
      $('rec-maquina').innerHTML = cargando('Analizando…');
      try { await cargarMaquina(true); await cargarModelos(); } catch (e) { $('rec-maquina').innerHTML = error(e.message); }
    };
    $('rec-calibrar').onclick = calibrar;
  }

  // ------------------------------------------------------------------ uso
  function pintarUso() {
    const perfil = estado.perfiles.find((p) => p.id === estado.perfil) || {};
    $('rec-uso').innerHTML = `
      ${titulo('fa-sliders', 'Para qué lo vas a usar')}
      <div style="display:flex; gap:10px; flex-wrap:wrap; align-items:center;">
        <div style="display:flex; gap:4px; flex-wrap:wrap;">
          ${estado.perfiles.map((p) => `<button data-perfil="${p.id}" title="${esc(p.descripcion)}"
            style="font-size:11.5px; padding:5px 10px; border-radius:5px; cursor:pointer;
            background:${p.id === estado.perfil ? 'rgba(137,180,250,0.18)' : 'transparent'};
            color:${p.id === estado.perfil ? 'var(--accent-blue)' : 'var(--text-muted)'};
            border:1px solid ${p.id === estado.perfil ? 'var(--accent-blue)' : 'var(--border-color)'};">
            ${esc(p.nombre)}</button>`).join('')}
        </div>
        <span style="flex:1"></span>
        <div style="display:flex; gap:0; border:1px solid var(--border-color); border-radius:5px; overflow:hidden;">
          ${estado.tiradores.map((t) => `<button data-tirador="${t.id}" style="font-size:11px; padding:5px 10px;
            cursor:pointer; border:none; background:${t.id === estado.tirador ? 'rgba(203,166,247,0.2)' : 'transparent'};
            color:${t.id === estado.tirador ? 'var(--accent-purple)' : 'var(--text-muted)'};">${esc(t.nombre)}</button>`).join('')}
        </div>
      </div>
      <div style="margin-top:6px; color:var(--text-muted); font-size:11px;">
        ${esc(perfil.descripcion || '')} Prioriza ${esc(perfil.prioriza || '')};
        necesita al menos ${perfil.tok_s_min} tok/s y ${Number(perfil.ctx_min).toLocaleString('es')} tokens de contexto
        ${perfil.kv_cuantizable === false ? '· <span title="Medido: la caché q8_0 bajó las citas verificadas del 100 % al 79 %">caché sin cuantizar</span>' : ''}.
        ${estado.perfil !== 'tutor' ? '<br>Lo aplicado para este uso lo leen sus módulos; no cambia la configuración del tutor.' : ''}
      </div>`;
    $('rec-uso').querySelectorAll('[data-perfil]').forEach((b) => b.onclick = () => {
      if (estado.ocupado) return;
      estado.perfil = b.dataset.perfil; pintarUso(); cargarModelos(true);
    });
    $('rec-uso').querySelectorAll('[data-tirador]').forEach((b) => b.onclick = () => {
      if (estado.ocupado) return;
      estado.tirador = b.dataset.tirador; pintarUso(); cargarModelos(false);
    });
  }

  // ------------------------------------------------------------------ modelos
  async function cargarModelos(elegirMejor = false) {
    $('rec-modelos').innerHTML = cargando('Calculando cada modelo instalado…');
    try {
      const d = await prigFetchJson(`/api/recursos/modelos?perfil=${estado.perfil}&tirador=${estado.tirador}`);
      estado.modelos = d.modelos;
    } catch (e) {
      $('rec-modelos').innerHTML = error(e.message);
      return;
    }
    if (elegirMejor || !estado.modelos.some((m) => m.modelo === estado.elegido)) {
      const mejor = estado.modelos.find((m) => m.util) || estado.modelos[0];
      estado.elegido = mejor ? mejor.modelo : null;
    }
    pintarModelos();
    if (estado.elegido) await cargarDetalle();
    else $('rec-detalle').innerHTML = '';
  }

  function pintarModelos() {
    if (!estado.modelos.length) {
      $('rec-modelos').innerHTML = titulo('fa-cubes', 'Modelos instalados') +
        '<div style="color:var(--text-muted);">No hay modelos de texto instalados en Ollama.</div>';
      return;
    }
    const mejor = (estado.modelos.find((m) => m.util) || {}).modelo;
    const filas = estado.modelos.map((m) => {
      const e = m.estimacion || {};
      const p = m.prueba;
      const medido = p && p.ok ? `<span style="color:var(--accent-green);" title="Medido el ${esc(p.fecha)}">
          ${p.tok_s} tok/s${p.calidad != null ? ` · citas ${Math.round(p.calidad * 100)} %` : ''}</span>`
        : (p && !p.ok ? `<span style="color:var(--accent-red);" title="${esc(p.error || '')}">falló</span>` : '—');
      const sel = m.modelo === estado.elegido;
      return `<tr data-modelo="${esc(m.modelo)}" style="cursor:pointer; ${sel ? 'background:rgba(137,180,250,0.10);' : ''}">
        <td style="padding:6px 8px;"><code style="color:#fff;">${esc(m.modelo)}</code>
          ${m.modelo === mejor ? '<span style="color:var(--accent-yellow); font-size:10px; margin-left:4px;">★ mejor para este uso</span>' : ''}</td>
        <td style="padding:6px 8px; color:${COLOR[m.veredicto] || '#ccc'};">${esc(m.etiqueta)}</td>
        <td style="padding:6px 8px;">${e.ctx ? Number(e.ctx).toLocaleString('es') : '—'}${e.kv && e.kv !== 'f16' ? ` · ${esc(e.kv)}` : ''}</td>
        <td style="padding:6px 8px;">${e.fraccion_gpu != null ? Math.round(e.fraccion_gpu * 100) + ' %' : '—'}</td>
        <td style="padding:6px 8px;" title="Rango probable ${e.tok_s_rango ? e.tok_s_rango.join('–') : ''}">~${e.tok_s ?? '—'}</td>
        <td style="padding:6px 8px;">${e.total_gb ?? '—'} GB</td>
        <td style="padding:6px 8px;">${medido}</td>
      </tr>`;
    }).join('');
    $('rec-modelos').innerHTML = `
      ${titulo('fa-cubes', 'Modelos instalados')}
      <div style="overflow-x:auto;">
      <table style="width:100%; border-collapse:collapse; font-size:11.5px;">
        <thead><tr style="color:var(--text-muted); text-align:left; font-size:10.5px;">
          <th style="padding:4px 8px;">Modelo</th><th style="padding:4px 8px;">Veredicto</th>
          <th style="padding:4px 8px;">Contexto</th><th style="padding:4px 8px;">En GPU</th>
          <th style="padding:4px 8px;">tok/s</th><th style="padding:4px 8px;">Memoria</th>
          <th style="padding:4px 8px;">Medido</th></tr></thead>
        <tbody>${filas}</tbody>
      </table></div>`;
    $('rec-modelos').querySelectorAll('tr[data-modelo]').forEach((tr) => tr.onclick = () => {
      if (estado.ocupado) return;
      estado.elegido = tr.dataset.modelo; pintarModelos(); cargarDetalle();
    });
  }

  // ------------------------------------------------------------------ detalle
  async function cargarDetalle() {
    $('rec-detalle').innerHTML = cargando('Preparando la recomendación…');
    try {
      estado.rec = await prigFetchJson('/api/recursos/recomendar', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ modelo: estado.elegido, perfil: estado.perfil, tirador: estado.tirador }),
      });
      pintarDetalle();
    } catch (e) {
      $('rec-detalle').innerHTML = error(e.message);
    }
  }

  function pintarDetalle() {
    const r = estado.rec;
    const e = r.estimacion || {};
    const f = r.ficha || {};
    const cambios = r.cambios || [];
    const viable = r.veredicto !== 'no_viable';
    const mejora = r.mejora_con_servidor;
    const aplicado = r.aplicado;

    const tablaCambios = cambios.length
      ? `<table style="border-collapse:collapse; font-size:11.5px; margin-top:4px;">
          ${cambios.map((c) => `<tr><td style="padding:3px 10px 3px 0; color:var(--text-muted);">${esc(CAMPOS[c.campo] || c.campo)}</td>
            <td style="padding:3px 8px; color:var(--accent-red); text-decoration:line-through;">${esc(valorBonito(c.campo, c.actual))}</td>
            <td style="padding:3px 4px;">→</td>
            <td style="padding:3px 8px; color:var(--accent-green);">${esc(valorBonito(c.campo, c.nuevo))}</td></tr>`).join('')}
        </table>`
      : '<div style="color:var(--accent-green); margin-top:4px;"><i class="fa-solid fa-check"></i> Ya está configurado así.</div>';

    const detallesFicha = [
      f.arquitectura && esc(f.arquitectura),
      f.parametros && `${(f.parametros / 1e9).toFixed(1)} B parámetros`,
      f.es_moe && `MoE: ${(f.parametros_activos / 1e9).toFixed(1)} B activos`,
      f.cuantizacion && esc(f.cuantizacion), f.gb && `${f.gb} GB`,
      f.contexto_max && `hasta ${Number(f.contexto_max).toLocaleString('es')} tokens`,
      f.piensa && 'piensa', f.vision && 'visión', f.herramientas && 'herramientas',
    ].filter(Boolean).join(' · ');

    $('rec-detalle').innerHTML = `
      ${titulo('fa-wand-magic-sparkles', `Cómo abrir <code style="color:#fff;">${esc(r.modelo)}</code>`,
        `<span style="font-size:10.5px; color:var(--text-muted); font-weight:normal;">
          ${r.fiabilidad === 'calibrada' ? 'con medidas de tu máquina' : 'estimado'}${f.estimada ? ' · ficha aproximada' : ''}</span>`)}
      <div style="display:grid; grid-template-columns:minmax(0, 1.3fr) minmax(0, 1fr); gap:12px;">
        <div style="background:rgba(0,0,0,0.18); border-radius:7px; padding:10px 12px;">
          <div style="font-size:13px; color:${COLOR[r.veredicto] || '#fff'}; font-weight:600;">${esc(r.etiqueta)}</div>
          <div style="margin-top:5px; line-height:1.5;">${esc(r.motivo)}</div>
          <div style="margin-top:6px; color:var(--text-muted); font-size:10.5px;">${detallesFicha}</div>
          ${e.total_gb ? `<div style="margin-top:8px; display:flex; gap:14px; flex-wrap:wrap; font-size:11px;">
            <span>Memoria <b>${e.total_gb} GB</b> (caché ${e.cache_gb})</span>
            <span>GPU <b>${e.en_gpu_gb} GB</b> · RAM <b>${e.en_ram_gb} GB</b></span>
            <span>Velocidad <b>${e.tok_s_rango ? e.tok_s_rango.join('–') : e.tok_s} tok/s</b></span></div>` : ''}
          ${r.ajustada_por_prueba ? `<div style="margin-top:6px; color:var(--accent-yellow); font-size:11px;">
            El contexto se bajó porque la prueba en tu máquina no cupo con el previsto.</div>` : ''}
        </div>
        <div style="background:rgba(0,0,0,0.18); border-radius:7px; padding:10px 12px;">
          <div style="font-size:11px; color:var(--text-muted);">${estado.perfil === 'tutor'
            ? 'Qué cambia en la configuración de IA' : 'Qué se guardará para este uso'}</div>
          ${viable ? tablaCambios : '<div style="color:var(--accent-red); margin-top:4px;">No hay forma útil de abrirlo aquí.</div>'}
          ${aplicado ? `<div style="margin-top:8px; font-size:10.5px; color:var(--text-muted);">
            Aplicado ${esc(aplicado.modelo)} el ${esc((aplicado.fecha || '').replace('T', ' '))}.</div>` : ''}
          <div style="display:flex; gap:6px; margin-top:10px; flex-wrap:wrap;">
            ${viable ? boton('rec-probar', '<i class="fa-solid fa-flask"></i> Probar', 'var(--accent-purple)',
              'title="Carga el modelo con esta configuración unos segundos, mide la velocidad, la memoria y la calidad de las citas, y lo descarga"') : ''}
            ${viable && cambios.length ? boton('rec-aplicar', '<i class="fa-solid fa-check"></i> Aplicar', 'var(--accent-green)') : ''}
            ${aplicado ? boton('rec-restaurar', '<i class="fa-solid fa-rotate-left"></i> Restaurar lo anterior', 'var(--text-muted)') : ''}
          </div>
        </div>
      </div>
      ${r.aviso_servidor ? `<div style="margin-top:10px; padding:7px 12px; border-radius:6px;
          background:rgba(243,139,168,0.08); border-left:3px solid var(--accent-red); color:var(--accent-red);">
          <i class="fa-solid fa-triangle-exclamation"></i> ${esc(r.aviso_servidor)}</div>` : ''}
      ${mejora ? `<div style="margin-top:10px; padding:9px 12px; border-radius:6px; background:rgba(137,180,250,0.07);
          border-left:3px solid var(--accent-blue);">
          <b style="color:var(--accent-blue);">Cambiando el servidor de Ollama:</b>
          ${esc(mejora.ganancia)}.
          <div style="margin-top:4px; font-size:11px;">${Object.entries(mejora.cambios).map(([k, v]) =>
            `<code>${esc(k)}=${esc(v)}</code>`).join(' ')}</div>
          ${(mejora.contras || []).map((c) => `<div style="color:var(--accent-yellow); font-size:11px; margin-top:3px;">
            <i class="fa-solid fa-triangle-exclamation"></i> ${esc(c)}</div>`).join('')}
          <div style="margin-top:7px;">${boton('rec-servidor', '<i class="fa-solid fa-server"></i> Cambiar el servidor', 'var(--accent-blue)')}</div>
        </div>` : ''}
      ${(r.alternativas || []).length ? `<details style="margin-top:8px;"><summary style="cursor:pointer; color:var(--text-muted);">
          Otras configuraciones posibles (${r.alternativas.length})</summary>
          <div style="margin-top:6px; display:flex; flex-direction:column; gap:3px;">
          ${r.alternativas.map((a) => `<div style="font-size:11px;">
            ${Number(a.ctx).toLocaleString('es')} tokens · caché ${esc(a.kv)} · ${a.paralelo} ranura(s) →
            ${a.total_gb} GB, ${Math.round(a.fraccion_gpu * 100)} % en GPU, ~${a.tok_s} tok/s</div>`).join('')}
          </div></details>` : ''}`;

    if ($('rec-probar')) $('rec-probar').onclick = probar;
    if ($('rec-aplicar')) $('rec-aplicar').onclick = aplicar;
    if ($('rec-restaurar')) $('rec-restaurar').onclick = restaurar;
    if ($('rec-servidor')) $('rec-servidor').onclick = () => cambiarServidor(mejora.cambios);
  }

  // ------------------------------------------------------------------ acciones
  async function aplicar() {
    try {
      const d = await prigFetchJson('/api/recursos/aplicar', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ modelo: estado.elegido, perfil: estado.perfil, tirador: estado.tirador }),
      });
      window.aiConfig = d.config;
      if (estado.perfil === 'tutor' && window.globalConfigMgr) {
        await window.globalConfigMgr.loadSettingsIntoUI();
      }
      aviso(`Aplicado: ${d.cambios.length} cambio(s). Puedes restaurarlo cuando quieras.`, 'var(--accent-green)');
      await cargarDetalle();
    } catch (e) {
      aviso(`No se pudo aplicar: ${e.message}`, 'var(--accent-red)');
    }
  }

  async function restaurar() {
    try {
      const d = await prigFetchJson('/api/recursos/restaurar', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ perfil: estado.perfil }),
      });
      window.aiConfig = d.config;
      if (estado.perfil === 'tutor' && window.globalConfigMgr) {
        await window.globalConfigMgr.loadSettingsIntoUI();
      }
      aviso('Restaurados los ajustes que tenías antes.', 'var(--accent-green)');
      await cargarDetalle();
    } catch (e) {
      aviso(`No se pudo restaurar: ${e.message}`, 'var(--accent-red)');
    }
  }

  async function cambiarServidor(cambios, forzar = false) {
    const lista = Object.entries(cambios).map(([k, v]) => `${k}=${v}`).join('\n');
    if (!forzar && !confirm(`Se reiniciará Ollama con:\n\n${lista}\n\nAfecta a todos los usos de Prig. ¿Seguir?`)) return;
    try {
      const d = await prigFetchJson('/api/recursos/servidor', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ cambios, reiniciar: true, forzar }),
      });
      if (d.necesita_confirmar) {
        if (confirm(d.mensaje)) return cambiarServidor(cambios, true);
        return;
      }
      if (d.instrucciones) {
        alert(d.instrucciones);
      } else if (d.aplicado) {
        aviso('Ollama reiniciado con los nuevos ajustes.', 'var(--accent-green)');
      } else {
        aviso(d.mensaje || d.error || `Ollama no tomó: ${Object.keys(d.faltan || {}).join(', ')}`, 'var(--accent-yellow)');
      }
      await cargarMaquina(true);
      await cargarModelos();
    } catch (e) {
      aviso(`No se pudo cambiar el servidor: ${e.message}`, 'var(--accent-red)');
    }
  }

  function aviso(texto, color) {
    const caja = $('rec-detalle');
    if (!caja) return;
    const div = document.createElement('div');
    div.style.cssText = `margin-bottom:8px; padding:6px 10px; border-radius:5px; border-left:3px solid ${color}; color:${color};
      background:rgba(0,0,0,0.2);`;
    div.textContent = texto;
    caja.prepend(div);
    setTimeout(() => div.remove(), 6000);
  }

  // ------------------------------------------------------------------ en flujo
  function abrirLog(tituloTexto) {
    const log = $('rec-log');
    log.style.display = 'block';
    log.innerHTML = `${titulo('fa-terminal', esc(tituloTexto),
      boton('rec-cancelar', '<i class="fa-solid fa-stop"></i> Cancelar', 'var(--accent-red)'))}
      <div id="rec-log-lineas" style="background:rgba(0,0,0,0.25); border-radius:6px; padding:8px 10px;
        font-family:var(--font-mono, monospace); font-size:11px; max-height:220px; overflow:auto;"></div>`;
    $('rec-cancelar').onclick = () => fetch('/api/recursos/cancelar', { method: 'POST' }).catch(() => {});
    log.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }

  function linea(texto, color = '#ccc') {
    const caja = $('rec-log-lineas');
    if (!caja) return;
    caja.insertAdjacentHTML('beforeend', `<div style="color:${color}; padding:1px 0;">${esc(texto)}</div>`);
    caja.scrollTop = caja.scrollHeight;
  }

  async function enFlujo(url, cuerpo, alEvento) {
    estado.ocupado = true;
    try {
      const res = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(cuerpo || {}) });
      if (!res.ok) throw new Error(await prigErrorDetail(res));
      const lector = res.body.getReader();
      const dec = new TextDecoder();
      let resto = '';
      for (;;) {
        const { value, done } = await lector.read();
        if (done) break;
        resto += dec.decode(value, { stream: true });
        const partes = resto.split('\n');
        resto = partes.pop();
        for (const p of partes) {
          if (!p.trim()) continue;
          try { alEvento(JSON.parse(p)); } catch (e) { /* línea incompleta */ }
        }
      }
    } finally {
      estado.ocupado = false;
      const c = $('rec-cancelar');
      if (c) c.remove();
    }
  }

  function eventoComun(ev) {
    if (ev.tipo === 'intento' || ev.tipo === 'plan') linea(ev.mensaje);
    else if (ev.tipo === 'enfriando') linea(ev.mensaje, 'var(--accent-yellow)');
    else if (ev.tipo === 'fallo') linea(`${ev.oom ? 'Sin memoria' : 'Error'}: ${ev.mensaje}`, ev.oom ? 'var(--accent-yellow)' : 'var(--accent-red)');
    else if (ev.tipo === 'medido') {
      linea(`${ev.modelo}: ${ev.tok_s} tok/s generando, ${ev.prefill_tok_s} tok/s leyendo, ` +
        `${ev.total_gb ?? '?'} GB (${ev.fraccion_gpu != null ? Math.round(ev.fraccion_gpu * 100) : '?'} % en GPU), ` +
        (ev.calidad != null ? `citas literales ${Math.round(ev.calidad * 100)} %` : 'calidad sin medir'), 'var(--accent-green)');
    } else if (ev.tipo === 'error') linea(ev.mensaje, 'var(--accent-red)');
  }

  async function probar() {
    abrirLog(`Probando ${estado.elegido}`);
    linea('La prueba carga el modelo, genera unas líneas y lo descarga.');
    try {
      await enFlujo('/api/recursos/probar', { modelo: estado.elegido, perfil: estado.perfil, tirador: estado.tirador },
        (ev) => {
          eventoComun(ev);
          if (ev.tipo === 'fin') {
            const r = ev.resultado || {};
            if (!r.ok) { linea(`No funcionó: ${r.error || 'sin detalle'}`, 'var(--accent-red)'); return; }
            const d = r.desvio || {};
            linea(`Previsto frente a medido: velocidad ${d.tok_s_pct >= 0 ? '+' : ''}${d.tok_s_pct} %` +
              (d.total_gb_pct != null ? `, memoria ${d.total_gb_pct >= 0 ? '+' : ''}${d.total_gb_pct} %` : ''),
              Math.abs(d.tok_s_pct || 0) <= 25 ? 'var(--accent-green)' : 'var(--accent-yellow)');
            if (r.aviso) linea(r.aviso, 'var(--accent-yellow)');
            if (r.canario && !r.canario.fiable) linea('No dio citas suficientes para medir la calidad de extracción; solo cuenta la velocidad.', 'var(--accent-yellow)');
            if (r.deducido && Object.keys(r.deducido).length) linea('Medidas de tu máquina actualizadas.', 'var(--accent-green)');
          }
        });
      await cargarMaquina();
      await cargarModelos();
    } catch (e) {
      linea(e.message, 'var(--accent-red)');
    }
  }

  async function calibrar() {
    if (estado.ocupado) return;
    if (!confirm('La calibración carga uno o dos modelos instalados durante unos segundos cada uno ' +
                 '(la GPU trabajará un poco) y los descarga al terminar. ¿Calibrar ahora?')) return;
    abrirLog('Calibrando la máquina');
    try {
      await enFlujo('/api/recursos/calibrar', {}, (ev) => {
        eventoComun(ev);
        if (ev.tipo === 'calibrado') {
          const v = ev.valores || {};
          const partes = [];
          if (v.presupuesto_gpu) partes.push(`la GPU se llena hasta ${(v.presupuesto_gpu / 1e9).toFixed(2)} GB`);
          if (v.ancho_gpu) partes.push(`ancho GPU ${Math.round(v.ancho_gpu)} GB/s`);
          if (v.ancho_cpu) partes.push(`ancho RAM ${Math.round(v.ancho_cpu)} GB/s`);
          linea(`Calibrado: ${partes.join(', ')}.`, 'var(--accent-green)');
        }
        if (ev.tipo === 'fin' && ev.resultado && !ev.resultado.ok) {
          linea(`No se pudo calibrar: ${ev.resultado.error}`, 'var(--accent-red)');
        }
      });
      await cargarMaquina();
      await cargarModelos();
    } catch (e) {
      linea(e.message, 'var(--accent-red)');
    }
  }

  window.Recursos = { abrir };
})();
