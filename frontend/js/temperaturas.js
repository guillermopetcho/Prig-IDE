/**
 * Temperaturas de la máquina en la barra de estado.
 *
 * Abajo a la derecha: GPU, CPU, SSD y ventiladores, con color según el límite. Si
 * el gobernador térmico está pausando un flujo, se ve "enfriando" y hasta cuántos
 * grados. Al pulsar se abre el detalle: todos los sensores, cada núcleo, la gráfica
 * de los últimos minutos, el límite de la GPU (editable) y lo que el gobernador ha
 * aprendido para no volver a llegar a él.
 */
(function () {
  const $ = (id) => document.getElementById(id);
  const esc = (t) => String(t ?? '').replace(/[&<>"']/g,
    (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

  const INTERVALO_MS = 3000;
  let ultimo = null;
  let abierto = false;
  let temporizador = null;

  const VERDE = 'var(--accent-green)', AMARILLO = 'var(--accent-yellow)', ROJO = 'var(--accent-red)';

  function color(c, u) {
    if (c.temp == null) return 'var(--text-muted)';
    if (c.tipo === 'gpu') return c.temp >= u.gpu_limite ? ROJO : (c.temp >= u.gpu_reanudar ? AMARILLO : VERDE);
    if (c.tipo === 'cpu') return c.temp >= u.cpu_alto ? ROJO : (c.temp >= u.cpu_aviso ? AMARILLO : VERDE);
    const alto = c.alto || c.critico;
    if (alto) return c.temp >= alto ? ROJO : (c.temp >= alto - 10 ? AMARILLO : VERDE);
    return c.temp >= 80 ? ROJO : (c.temp >= 65 ? AMARILLO : VERDE);
  }

  const ETIQUETA_CORTA = { gpu: 'GPU', cpu: 'CPU', disco: 'SSD', placa: 'Placa', wifi: 'Wi-Fi', bateria: 'Bat.' };

  // ------------------------------------------------------------------ barra
  function asegurarHueco() {
    let el = $('hw-temp');
    if (el) {
      if (!el.dataset.listo) { el.dataset.listo = '1'; el.onclick = alternarPanel; }
      return el;
    }
    const derecha = $('prig-estado-derecha');
    if (!derecha) return null;
    el = document.createElement('span');
    el.id = 'hw-temp';
    el.title = 'Temperaturas de la máquina: pulsa para ver el detalle';
    el.style.cssText = 'cursor:pointer; display:inline-flex; gap:8px; align-items:center;';
    el.onclick = alternarPanel;
    derecha.appendChild(el);
    return el;
  }

  function pintarBarra(d) {
    const el = asegurarHueco();
    if (!el) return;
    const u = d.umbrales;
    const visibles = d.componentes.filter((c) => ['gpu', 'cpu', 'disco'].includes(c.tipo));
    const partes = visibles.map((c) =>
      `<span style="color:${color(c, u)};">${ETIQUETA_CORTA[c.tipo] || esc(c.nombre)} ${Math.round(c.temp)}°</span>`);
    const vent = d.ventiladores || [];
    if (vent.length) {
      const rpm = Math.max(...vent.map((v) => v.rpm || 0));
      partes.push(`<span style="color:var(--text-muted);"><i class="fa-solid fa-fan"></i> ${rpm}</span>`);
    }
    const pausa = d.gobernador && d.gobernador.pausa;
    if (pausa) {
      partes.push(`<span style="color:${AMARILLO}; font-weight:600;" title="El gobernador térmico pausó el trabajo">
        <i class="fa-solid fa-pause"></i> enfriando → ${Math.round(pausa.objetivo)}°</span>`);
    }
    el.innerHTML = `<i class="fa-solid fa-temperature-half" style="color:var(--accent-red);"></i> ${partes.join('')}`;
    if (!visibles.length && !vent.length) el.innerHTML = '<i class="fa-solid fa-temperature-half"></i> sin sensores';
  }

  async function actualizar() {
    if (document.hidden) return;
    try {
      const res = await fetch(`/api/recursos/temperaturas${abierto ? '?historial=true' : ''}`);
      if (!res.ok) return;
      ultimo = await res.json();
      pintarBarra(ultimo);
      if (abierto) {
        try { const f = await fetch('/api/recursos/frio'); if (f.ok) ultimoFrio = await f.json(); } catch (e) { /* sin modo frío */ }
        try { const m = await fetch('/api/recursos/moe'); if (m.ok) ultimoMoe = await m.json(); } catch (e) { /* sin motor MoE */ }
        pintarPanel(ultimo);
      }
    } catch (e) { /* el backend puede estar reiniciando */ }
  }

  // ------------------------------------------------------------------ panel
  function alternarPanel() {
    abierto = !abierto;
    let panel = $('panel-temperaturas');
    if (!abierto) { if (panel) panel.style.display = 'none'; return; }
    if (!panel) {
      panel = document.createElement('div');
      panel.id = 'panel-temperaturas';
      panel.style.cssText = `position:fixed; right:10px; bottom:34px; width:420px; max-width:calc(100vw - 20px);
        max-height:70vh; overflow:auto; z-index:3000; background:rgba(30,30,46,0.98); border:1px solid var(--border-color);
        border-radius:9px; box-shadow:0 12px 40px rgba(0,0,0,0.5); padding:12px 14px; font-size:12px; color:var(--text-main, #cdd6f4);`;
      document.body.appendChild(panel);
      document.addEventListener('mousedown', (e) => {
        if (abierto && !panel.contains(e.target) && !$('hw-temp').contains(e.target)) alternarPanel();
      });
    }
    panel.style.display = 'block';
    panel.innerHTML = '<div style="color:var(--text-muted);"><i class="fa-solid fa-spinner fa-spin"></i> Leyendo sensores…</div>';
    actualizar();
  }

  function barra(temp, maximo, col) {
    const pct = Math.max(2, Math.min(100, (temp / maximo) * 100));
    return `<div style="height:5px; background:rgba(255,255,255,0.07); border-radius:3px; overflow:hidden; margin-top:3px;">
      <div style="width:${pct}%; height:100%; background:${col};"></div></div>`;
  }

  function pintarPanel(d) {
    const panel = $('panel-temperaturas');
    if (!panel) return;
    const u = d.umbrales;
    const g = d.gobernador || {};
    // Conservar el valor que el usuario está escribiendo en el límite
    const enEdicion = document.activeElement && document.activeElement.id === 'temp-limite';
    const limiteEscrito = enEdicion ? document.activeElement.value : null;
    // Lo que se está escribiendo en el modo suave tampoco se pisa al refrescar
    const escritoRitmo = {};
    ['rit-objetivo', 'rit-rampa'].forEach((id) => { const el = $(id); if (el && el.dataset.tocado) escritoRitmo[id] = el.value; });
    const r = g.ritmo || {};
    const eficientes = (r.nucleos_eficientes || []).length;

    const filas = d.componentes.map((c) => {
      const col = color(c, u);
      const extra = [];
      if (c.tipo === 'gpu') {
        if (c.consumo_w != null) extra.push(`${c.consumo_w.toFixed(0)} W`);
        if (c.uso_pct != null) extra.push(`uso ${c.uso_pct.toFixed(0)} %`);
        extra.push(`límite ${u.gpu_limite}°`);
      }
      if (c.tipo === 'cpu' && c.nucleo_max != null) extra.push(`núcleo más caliente ${c.nucleo_max}°`);
      if (c.alto && c.tipo !== 'cpu') extra.push(`alto ${Math.round(c.alto)}°`);
      const nucleos = c.tipo === 'cpu' && (c.nucleos || []).length
        ? `<div style="display:flex; flex-wrap:wrap; gap:4px; margin-top:5px;">${c.nucleos.map((n) =>
            `<span title="${esc(n.etiqueta)}" style="font-size:10px; padding:1px 5px; border-radius:3px;
              background:rgba(255,255,255,0.05); color:${color({ tipo: 'cpu', temp: n.temp }, u)};">${Math.round(n.temp)}°</span>`).join('')}</div>`
        : '';
      const maximo = c.tipo === 'gpu' ? Math.max(90, u.gpu_limite + 10) : (c.critico || c.alto || 100);
      return `<div style="padding:7px 0; border-bottom:1px solid rgba(255,255,255,0.06);">
        <div style="display:flex; justify-content:space-between; gap:8px;">
          <span><b>${esc(ETIQUETA_CORTA[c.tipo] || c.nombre)}</b>
            <span style="color:var(--text-muted); font-size:10.5px;">${c.tipo === 'gpu' ? esc(c.nombre) : ''}</span></span>
          <span style="color:${col}; font-weight:700;">${c.temp != null ? c.temp.toFixed(0) : '—'} °C</span>
        </div>
        ${c.temp != null ? barra(c.temp, maximo, col) : ''}
        ${extra.length ? `<div style="font-size:10.5px; color:var(--text-muted); margin-top:3px;">${extra.join(' · ')}</div>` : ''}
        ${nucleos}
      </div>`;
    }).join('');

    const vent = (d.ventiladores || []).map((v) =>
      `<span style="margin-right:12px;"><i class="fa-solid fa-fan"></i> ${esc(v.nombre)} ${v.rpm} rpm</span>`).join('');

    const saltoMedido = g.salto_c != null;
    const aprendido = `Corta a <b>${(g.corte ?? u.gpu_limite - 1).toFixed(0)} °C</b> y reanuda a
      <b>${Math.round(u.gpu_reanudar)} °C</b>: al retomar, la GPU sube
      ${saltoMedido ? `<b>${g.salto.toFixed(0)} °C</b> de golpe (medido)` : `unos ${Math.round(g.salto || 8)} °C de golpe (valor inicial, se mide al usarla)`}.
      ${g.alcances ? `Llegó al límite ${g.alcances} ${g.alcances === 1 ? 'vez' : 'veces'} y se reajustó.` : 'No ha llegado al límite.'}
      ${g.reposo_c != null ? `Parada no baja de ${Math.round(g.reposo_c)} °C.` : ''}`;

    panel.innerHTML = `
      <div style="display:flex; align-items:center; gap:8px; margin-bottom:6px;">
        <b style="font-size:13px;"><i class="fa-solid fa-temperature-half" style="color:var(--accent-red);"></i> Temperaturas</b>
        <span style="flex:1"></span>
        <span style="font-size:10px; color:var(--text-muted);">cada ${INTERVALO_MS / 1000} s</span>
        <button id="temp-cerrar" title="Cerrar" style="background:none; border:none; color:var(--text-muted); cursor:pointer;">
          <i class="fa-solid fa-xmark"></i></button>
      </div>
      ${g.pausa ? `<div style="padding:6px 9px; border-radius:5px; margin-bottom:6px; background:rgba(249,226,175,0.1);
          border-left:3px solid ${AMARILLO}; color:${AMARILLO};">
          <i class="fa-solid fa-pause"></i> Pausado para enfriar: GPU a ${Math.round(g.pausa.temp)}°, se reanuda a
          ${Math.round(g.pausa.objetivo)}° (${Math.round(Date.now() / 1000 - g.pausa.desde)} s)</div>` : ''}
      ${filas || '<div style="color:var(--text-muted);">No se encontraron sensores de temperatura.</div>'}
      ${vent ? `<div style="padding:7px 0; font-size:11px; color:var(--text-muted);">${vent}</div>` : ''}
      <canvas id="temp-grafica" width="390" height="90" style="width:100%; height:90px; margin-top:4px;"></canvas>
      <div style="display:flex; gap:12px; font-size:10px; color:var(--text-muted);">
        <span><span style="color:var(--accent-purple);">━</span> GPU</span>
        <span><span style="color:var(--accent-blue);">━</span> CPU</span>
        <span><span style="color:${ROJO};">┅</span> límite GPU</span>
        <span style="flex:1"></span><span>últimos ${Math.round(((d.historial || []).length * 2) / 60)} min</span>
      </div>
      <div style="margin-top:10px; padding-top:9px; border-top:1px solid rgba(255,255,255,0.08);">
        <div style="display:flex; align-items:center; gap:8px; margin-bottom:5px;">
          <label style="font-weight:600; display:flex; gap:6px; align-items:center; cursor:pointer;">
            <input type="checkbox" id="rit-activo" ${r.activo ? 'checked' : ''}> Modo suave</label>
          <span style="flex:1"></span>
          ${r.activo ? (() => { const f = ((r.motor || {}).instalado && (r.motor || {}).fraccion != null) ? r.motor.fraccion : (r.fraccion_ahora ?? 1);
              return `<span style="font-size:10.5px; color:${f < 0.98 ? AMARILLO : VERDE};">${(r.motor || {}).generando || !(r.motor || {}).instalado ? 'trabajando' : 'arrancará'} al ${Math.round(f * 100)} %</span>`; })() : ''}
        </div>
        <div style="font-size:10.5px; color:var(--text-muted); line-height:1.5; margin-bottom:6px;">
          El modelo trabaja dosificado en tramos de milisegundos: arranca despacio, sube poco a poco y se frena al acercarse
          a la temperatura objetivo. Mientras espera a la GPU, la CPU duerme en vez de girar. Más lento (en torno a la mitad),
          pero sin picos de calor. Vale para todo: chat, desafíos, Kaggle, GitHub y flujos.</div>
        ${r.activo ? `<div style="font-size:10.5px; margin-bottom:6px; color:${(r.motor || {}).instalado ? VERDE : AMARILLO};">
          <i class="fa-solid ${(r.motor || {}).instalado ? 'fa-microchip' : 'fa-triangle-exclamation'}"></i>
          ${(r.motor || {}).instalado
            ? `Actuando dentro del motor${(r.motor || {}).generando ? ` · ahora al ${Math.round(((r.motor || {}).fraccion ?? 1) * 100)} %` : ' · en reposo'}`
            : `Pausando peticiones (menos fino): ${esc((r.motor || {}).motivo || 'el motor propio no está disponible')}`}</div>` : ''}
        <div style="display:flex; align-items:center; gap:7px; flex-wrap:wrap; ${r.activo ? '' : 'opacity:.5;'}">
          <label for="rit-objetivo">Mantener la GPU cerca de</label>
          <input id="rit-objetivo" type="number" min="40" max="90" step="1" value="${escritoRitmo['rit-objetivo'] ?? Math.round(r.objetivo_c ?? 60)}"
            style="width:52px; padding:3px 5px; background:var(--bg-panel); color:#fff; border:1px solid var(--border-color); border-radius:4px;"> °C
          <label for="rit-rampa" style="margin-left:6px;">arranque gradual</label>
          <input id="rit-rampa" type="number" min="0" max="300" step="5" value="${escritoRitmo['rit-rampa'] ?? Math.round(r.rampa_s ?? 40)}"
            style="width:52px; padding:3px 5px; background:var(--bg-panel); color:#fff; border:1px solid var(--border-color); border-radius:4px;"> s
          <button id="rit-guardar" style="font-size:11px; padding:3px 9px; border-radius:4px; cursor:pointer;
            background:rgba(137,180,250,0.15); color:var(--accent-blue); border:1px solid rgba(137,180,250,0.4);">Guardar</button>
        </div>
        ${eficientes ? `<label style="display:flex; gap:6px; align-items:center; margin-top:6px; font-size:11px; cursor:pointer; ${r.activo ? '' : 'opacity:.5;'}">
            <input type="checkbox" id="rit-cpu" ${r.cpu_eficiente ? 'checked' : ''}> Motor del modelo en los ${eficientes} núcleos de eficiencia
            <span style="color:var(--text-muted);">(solo si el modelo cabe entero en la GPU)</span></label>` : ''}
      </div>
      <div id="frio-seccion"></div>
      <div id="moe-seccion"></div>
      <div style="margin-top:10px; padding-top:9px; border-top:1px solid rgba(255,255,255,0.08);">
        <div style="font-weight:600; margin-bottom:5px;">Gobernador térmico de la GPU</div>
        <div style="display:flex; align-items:center; gap:7px; flex-wrap:wrap;">
          <label for="temp-limite">Pausar al llegar a</label>
          <input id="temp-limite" type="number" min="40" max="95" step="1" value="${limiteEscrito ?? Math.round(u.gpu_limite)}"
            style="width:58px; padding:3px 5px; background:var(--bg-panel); color:#fff; border:1px solid var(--border-color); border-radius:4px;"> °C
          <button id="temp-guardar" style="font-size:11px; padding:3px 9px; border-radius:4px; cursor:pointer;
            background:rgba(137,180,250,0.15); color:var(--accent-blue); border:1px solid rgba(137,180,250,0.4);">Guardar</button>
          <span style="color:var(--text-muted); font-size:10.5px;">corte de emergencia: pausa hasta que enfríe</span>
        </div>
        <div style="margin-top:6px; font-size:11px; color:var(--text-muted); line-height:1.5;">${aprendido}</div>
        ${g.aviso ? `<div style="margin-top:6px; padding:6px 9px; border-radius:5px; font-size:11px; background:rgba(243,139,168,0.1);
            border-left:3px solid ${ROJO}; color:${ROJO};"><i class="fa-solid fa-triangle-exclamation"></i> ${esc(g.aviso)}</div>` : ''}
        ${(saltoMedido || g.alcances || g.reposo_c != null) ? `<button id="temp-olvidar" style="margin-top:6px; font-size:10.5px; padding:2px 8px; border-radius:4px;
            cursor:pointer; background:none; color:var(--text-muted); border:1px solid var(--border-color);">Olvidar lo aprendido</button>` : ''}
        <div style="margin-top:6px; font-size:10.5px; color:var(--text-muted);">
          La CPU la regula el modo frío (modelos en RAM)${eficientes ? '; con el modo suave, los que caben en la GPU usan los núcleos de eficiencia' : ''}. Se avisa a partir de ${u.cpu_aviso} °C.
        </div>
      </div>`;

    $('temp-cerrar').onclick = alternarPanel;
    const guardarRitmo = async (cambios) => {
      try {
        await prigFetchJson('/api/recursos/ritmo', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(cambios) });
        ['rit-objetivo', 'rit-rampa'].forEach((id) => { const el = $(id); if (el) delete el.dataset.tocado; });
        actualizar();
      } catch (e) { alert(`No se pudo guardar el modo suave: ${e.message}`); }
    };
    ['rit-objetivo', 'rit-rampa'].forEach((id) => { const el = $(id); if (el) el.oninput = () => { el.dataset.tocado = '1'; }; });
    if (Object.keys(escritoRitmo).length) Object.keys(escritoRitmo).forEach((id) => { $(id).dataset.tocado = '1'; });
    $('rit-activo').onchange = (e) => guardarRitmo({ activo: e.target.checked });
    $('rit-guardar').onclick = () => guardarRitmo({ objetivo_c: parseFloat($('rit-objetivo').value), rampa_s: parseFloat($('rit-rampa').value) });
    if ($('rit-cpu')) $('rit-cpu').onchange = (e) => guardarRitmo({ cpu_eficiente: e.target.checked });
    $('temp-guardar').onclick = async () => {
      const valor = parseFloat($('temp-limite').value);
      try {
        await prigFetchJson('/api/recursos/termico', { method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ limite_gpu: valor }) });
        $('temp-limite').blur();
        actualizar();
      } catch (e) { alert(`No se pudo guardar el límite: ${e.message}`); }
    };
    if ($('temp-olvidar')) {
      $('temp-olvidar').onclick = async () => {
        if (!confirm('¿Olvidar lo aprendido (salto al empezar, margen de corte, temperatura de reposo)? Se volverá a medir al usar la GPU.')) return;
        await prigFetchJson('/api/recursos/termico', { method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ olvidar: true }) }).catch(() => {});
        actualizar();
      };
    }
    if (enEdicion) {
      const input = $('temp-limite');
      input.focus();
      input.setSelectionRange(input.value.length, input.value.length);
    }
    dibujarGrafica(d.historial || [], u);
    pintarFrio();
    pintarMoe();
  }

  // ------------------------------------------------------------------ motor MoE (expertos en la GPU)
  let ultimoMoe = null;

  function pintarMoe() {
    const z = $('moe-seccion');
    const m = ultimoMoe;
    if (!z || !m) return;
    const escrito = {};
    ['moe-ctx', 'moe-calientes', 'moe-hilos', 'moe-modo'].forEach((id) => { const el = $(id); if (el && el.dataset.tocado) escrito[id] = el.value; });
    const a = m.ajustes || {};
    let estado;
    if (!m.disponible) {
      estado = `<span style="color:var(--text-muted);">${esc(m.motivo || 'No disponible')}</span>`;
    } else if (m.en_marcha) {
      estado = `<span style="color:${VERDE};"><i class="fa-solid fa-microchip"></i> En marcha · ${m.calientes_por_capa} expertos por capa en la GPU ·
        ${m.mtp ? 'MTP · ' : ''}modo ${esc(m.modo || '')} ·
        contexto ${Math.round((m.contexto || 0) / 1024)}K${a.contexto === 'auto' ? ' (automático)' : ''} · núcleos P ${esc((m.nucleos || []).join(', '))}${m.activas ? ` · ${m.activas} respuesta${m.activas > 1 ? 's' : ''} en curso` : ''}</span>`;
    } else {
      estado = `<span style="color:var(--text-muted);"><i class="fa-solid fa-microchip"></i> Parado: arranca solo con la primera petición a
        <code>${esc(m.nombre)}</code> (≈10 s) y se para tras ${Math.round((m.keep_alive_s || 300) / 60)} min sin uso.</span>`;
    }
    const valor = (id, def) => escrito[id] ?? def;
    const contextos = ['auto', 16384, 32768, 65536, 131072, 262144].map((c) =>
      `<option value="${c}" ${String(valor('moe-ctx', a.contexto)) === String(c) ? 'selected' : ''}>${c === 'auto' ? 'automático' : `${c / 1024}K`}</option>`).join('');
    z.innerHTML = `
      <div style="margin-top:10px; padding-top:9px; border-top:1px solid rgba(255,255,255,0.08);">
        <div style="font-weight:600; margin-bottom:4px;">Motor MoE · Qwen3.6-35B-A3B con expertos en la GPU</div>
        <div style="font-size:10.5px; color:var(--text-muted); line-height:1.5; margin-bottom:6px;">
          Copia a la GPU los expertos más usados de cada capa, la CPU calcula el resto a la vez, y la cabeza MTP del
          modelo propone 2 tokens por paso: ~53 tok/s exacto, ~60 equilibrado, ~68 rápido (Ollama: ~27), con la CPU
          por debajo de 60 °C sin turbo. Al arrancar descarga los modelos de Ollama para dejarle la VRAM.</div>
        <div style="font-size:10.5px; margin-bottom:6px;">${estado}${m.ultimo_error ? ` <span style="color:${ROJO};">${esc(m.ultimo_error)}</span>` : ''}</div>
        ${m.disponible ? `<div style="display:flex; align-items:center; gap:7px; flex-wrap:wrap; font-size:11px;">
          <label for="moe-modo" title="exacto: igual que el modelo original · equilibrado: +0,5 % de perplejidad · rápido: +1,6 %">Modo</label>
          <select id="moe-modo" style="${estiloCampo}">${(m.modos || ['exacto', 'equilibrado', 'rapido']).map((x) =>
            `<option value="${x}" ${String(valor('moe-modo', a.modo)) === x ? 'selected' : ''}>${x === 'rapido' ? 'rápido' : x}</option>`).join('')}</select>
          <label style="display:flex; gap:4px; align-items:center;" title="La cabeza MTP propone 2 tokens por paso; el resultado no cambia">
            <input type="checkbox" id="moe-mtp" ${a.mtp !== false ? 'checked' : ''}> MTP</label>
          <label for="moe-ctx">Contexto</label>
          <select id="moe-ctx" style="${estiloCampo}">${contextos}</select>
          <label for="moe-calientes" title="auto: los que quepan en la VRAM libre">Expertos por capa</label>
          <input id="moe-calientes" value="${esc(String(valor('moe-calientes', a.calientes ?? 'auto')))}" style="width:44px; ${estiloCampo}">
          <label for="moe-hilos" title="0: uno por núcleo P, hasta 4">Hilos</label>
          <input id="moe-hilos" type="number" min="0" max="16" value="${esc(String(valor('moe-hilos', a.hilos ?? 0)))}" style="width:40px; ${estiloCampo}">
          <button id="moe-guardar" style="${estiloBoton}">Guardar</button>
          ${m.en_marcha ? `<button id="moe-parar" style="${estiloBoton}"><i class="fa-solid fa-stop"></i> Parar ahora</button>` : ''}
        </div>
        <div style="font-size:10px; color:var(--text-muted); margin-top:3px;">Los cambios se aplican en el próximo arranque del motor.</div>
        <div style="font-size:10.5px; margin-top:6px; display:flex; gap:7px; align-items:center; flex-wrap:wrap;">
          <span title="Archivos enganchados que el motor ya leyó: preguntar de nuevo sobre ellos los restaura del disco en ~0,1 s en lugar de releerlos">
            <i class="fa-solid fa-box-archive"></i> Proyectos guardados: ${(m.proyectos || {}).archivos || 0}
            (${(((m.proyectos || {}).mb || 0) / 1000).toFixed(1)} GB)${(m.proyectos || {}).ultimo && m.proyectos.ultimo.origen
              ? ` · último: ${m.proyectos.ultimo.origen === 'disco' ? 'restaurado' : 'leído'}, ${(m.proyectos.ultimo.tokens || 0).toLocaleString('es')} tokens en ${m.proyectos.ultimo.segundos} s` : ''}</span>
          ${((m.proyectos || {}).archivos || 0) ? `<button id="moe-olvidar" style="${estiloBoton}"><i class="fa-solid fa-trash-can"></i> Borrar</button>` : ''}
        </div>` : ''}
        <div id="moe-msg" style="font-size:10.5px; margin-top:4px;"></div>
      </div>`;
    const msg = (t, error) => { const el = $('moe-msg'); if (el) { el.style.color = error ? ROJO : 'var(--text-muted)'; el.textContent = t; } };
    const enviar = async (cuerpo) => {
      try {
        ultimoMoe = await prigFetchJson('/api/recursos/moe', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(cuerpo) });
        ['moe-ctx', 'moe-calientes', 'moe-hilos', 'moe-modo'].forEach((id) => { const el = $(id); if (el) delete el.dataset.tocado; });
        pintarMoe();
      } catch (err) { msg(err.message, true); }
    };
    ['moe-ctx', 'moe-calientes', 'moe-hilos', 'moe-modo'].forEach((id) => {
      const el = $(id);
      if (el) el.oninput = el.onchange = () => { el.dataset.tocado = '1'; };
    });
    Object.keys(escrito).forEach((id) => { if ($(id)) $(id).dataset.tocado = '1'; });
    if ($('moe-guardar')) $('moe-guardar').onclick = () => enviar({
      contexto: $('moe-ctx').value, calientes: $('moe-calientes').value.trim() || 'auto',
      hilos: parseInt($('moe-hilos').value, 10) || 0, modo: $('moe-modo').value, mtp: $('moe-mtp').checked });
    if ($('moe-parar')) $('moe-parar').onclick = () => enviar({ detener: true });
    if ($('moe-olvidar')) $('moe-olvidar').onclick = () => {
      if (confirm('¿Borrar los proyectos guardados? La próxima pregunta sobre cada uno lo volverá a leer.')) enviar({ olvidar_proyectos: true });
    };
  }

  // ------------------------------------------------------------------ modo frío (modelos en RAM)
  let ultimoFrio = null;
  const estiloCampo = 'padding:3px 5px; background:var(--bg-panel); color:#fff; border:1px solid var(--border-color); border-radius:4px;';
  const estiloBoton = 'font-size:11px; padding:3px 9px; border-radius:4px; cursor:pointer; background:rgba(137,180,250,0.15); color:var(--accent-blue); border:1px solid rgba(137,180,250,0.4);';

  function pintarFrio() {
    const z = $('frio-seccion');
    const f = ultimoFrio;
    if (!z || !f) return;
    // Lo que se está escribiendo no se pisa al refrescar
    const escrito = {};
    ['fr-objetivo', 'fr-vatios'].forEach((id) => { const el = $(id); if (el && el.dataset.tocado) escrito[id] = el.value; });
    const a = f.ajustes || {}, c = f.control || {}, e = f.energia || {};
    let estado;
    if (!a.activo) {
      estado = '<span style="color:var(--text-muted);">Apagado: los modelos en RAM trabajan sin pausas.</span>';
    } else if (!c.en_ram) {
      estado = `<span style="color:var(--text-muted);"><i class="fa-solid fa-snowflake"></i> Esperando: ahora no hay ningún modelo en RAM (los que caben en la GPU los regula el modo suave).</span>`;
    } else if (c.generando) {
      estado = `<span style="color:${(c.fraccion ?? 1) < 0.98 ? AMARILLO : VERDE};"><i class="fa-solid fa-snowflake"></i> CPU a ${c.temp_media ?? '—'} °C · el modelo trabaja el ${Math.round((c.fraccion ?? 1) * 100)} % de cada ciclo${f.hilos ? ` en ${f.hilos} núcleos de eficiencia` : ''}</span>`;
    } else {
      estado = `<span style="color:${VERDE};"><i class="fa-solid fa-snowflake"></i> Modelo en RAM listo · la próxima respuesta arranca al ${Math.round((c.fraccion ?? 0.3) * 100)} % y sube poco a poco</span>`;
    }
    const turbo = e.turbo === true ? 'encendido' : e.turbo === false ? 'apagado' : 'desconocido';
    let energia;
    if (e.error) energia = `<span style="color:var(--text-muted);">${esc(e.error)}</span>`;
    else if (!e.instalado) {
      energia = `<button id="fr-instalar" style="${estiloBoton}"><i class="fa-solid fa-key"></i> Instalar el ayudante de energía</button>
        <span style="color:var(--text-muted);">pide la contraseña de administrador una vez</span>`;
    } else if (!e.seguro || !e.al_dia) {
      energia = `<span style="color:${AMARILLO};">${!e.seguro ? 'El ayudante instalado no es solo de root.' : 'El ayudante instalado es de otra versión de Prig.'}</span>
        <button id="fr-instalar" style="${estiloBoton} margin-left:6px;">Reinstalar</button>`;
    } else if (e.modo === 'frio') {
      energia = `<span style="color:${VERDE};"><i class="fa-solid fa-check"></i> Energía fría activa</span>
        <button id="fr-normal" style="${estiloBoton} margin-left:6px;">Volver a normal</button>`;
    } else {
      energia = `<label for="fr-vatios">Tope de potencia</label>
        <input id="fr-vatios" type="number" min="10" max="45" step="1" value="${escrito['fr-vatios'] ?? (f.vatios || 20)}" style="width:48px; ${estiloCampo}"> W
        <button id="fr-aplicar" style="${estiloBoton}"><i class="fa-solid fa-snowflake"></i> Apagar turbo y aplicar</button>`;
    }
    z.innerHTML = `
      <div style="margin-top:10px; padding-top:9px; border-top:1px solid rgba(255,255,255,0.08);">
        <div style="display:flex; align-items:center; gap:8px; margin-bottom:5px;">
          <label style="font-weight:600; display:flex; gap:6px; align-items:center; cursor:pointer;">
            <input type="checkbox" id="fr-activo" ${a.activo ? 'checked' : ''}> Modo frío · modelos en RAM</label>
        </div>
        <div style="font-size:10.5px; color:var(--text-muted); line-height:1.5; margin-bottom:6px;">
          Para modelos que no caben en la GPU (32–40B): el motor trabaja solo una parte de cada ciclo de 50 ms,
          en los núcleos de eficiencia, y la CPU se mantiene cerca de la temperatura objetivo. Mucho más lento,
          pero sin calentar la máquina.</div>
        <div style="font-size:10.5px; margin-bottom:6px;">${estado}</div>
        <div style="display:flex; align-items:center; gap:7px; flex-wrap:wrap; ${a.activo ? '' : 'opacity:.5;'}">
          <label for="fr-objetivo">Mantener la CPU cerca de</label>
          <input id="fr-objetivo" type="number" min="40" max="85" step="1" value="${escrito['fr-objetivo'] ?? Math.round(a.objetivo_c ?? 60)}" style="width:52px; ${estiloCampo}"> °C
          <button id="fr-guardar" style="${estiloBoton}">Guardar</button>
        </div>
        <div style="margin-top:8px; font-size:11px; font-weight:600;">Energía de la CPU <span style="font-weight:400; color:var(--text-muted);">(con permiso de administrador)</span></div>
        <div style="font-size:10.5px; color:var(--text-muted); margin:2px 0 5px;">
          Turbo ${turbo} · ${esc(e.gobernador || '—')}${e.preferencia ? ` / ${esc(e.preferencia)}` : ''} · tope ${e.pl1_w ?? '—'} W${e.auto_cpufreq ? ' · con auto-cpufreq' : ''}.
          Sin turbo cada token cuesta menos calor: a la misma temperatura, el modelo va más rápido.</div>
        <div style="display:flex; align-items:center; gap:7px; flex-wrap:wrap; font-size:11px;">${energia}</div>
        <div id="fr-msg" style="font-size:10.5px; margin-top:4px;"></div>
      </div>`;
    const msg = (t, error) => { const el = $('fr-msg'); if (el) { el.style.color = error ? ROJO : 'var(--text-muted)'; el.textContent = t; } };
    const enviar = async (url, cuerpo, espera) => {
      if (espera) msg(espera);
      try {
        ultimoFrio = await prigFetchJson(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(cuerpo || {}) });
        ['fr-objetivo', 'fr-vatios'].forEach((id) => { const el = $(id); if (el) delete el.dataset.tocado; });
        pintarFrio();
      } catch (err) { msg(err.message, true); }
    };
    ['fr-objetivo', 'fr-vatios'].forEach((id) => { const el = $(id); if (el) el.oninput = () => { el.dataset.tocado = '1'; }; });
    Object.keys(escrito).forEach((id) => { if ($(id)) $(id).dataset.tocado = '1'; });
    $('fr-activo').onchange = (ev) => enviar('/api/recursos/frio', { activo: ev.target.checked });
    $('fr-guardar').onclick = () => enviar('/api/recursos/frio', { objetivo_c: parseFloat($('fr-objetivo').value) });
    if ($('fr-instalar')) $('fr-instalar').onclick = () => enviar('/api/recursos/energia/instalar', {}, 'Esperando la contraseña de administrador…');
    if ($('fr-aplicar')) $('fr-aplicar').onclick = () => enviar('/api/recursos/energia', { frio: true, vatios: parseInt($('fr-vatios').value, 10) }, 'Esperando la contraseña de administrador…');
    if ($('fr-normal')) $('fr-normal').onclick = () => enviar('/api/recursos/energia', { frio: false }, 'Esperando la contraseña de administrador…');
  }

  function dibujarGrafica(historial, u) {
    const lienzo = $('temp-grafica');
    if (!lienzo || historial.length < 2) return;
    const ctx = lienzo.getContext('2d');
    const W = lienzo.width, H = lienzo.height;
    ctx.clearRect(0, 0, W, H);
    const valores = historial.flatMap((h) => [h.gpu, h.cpu]).filter((v) => v != null).concat([u.gpu_limite]);
    const min = Math.floor(Math.min(...valores) / 10) * 10;
    const max = Math.ceil(Math.max(...valores) / 10) * 10 + 5;
    const y = (v) => H - 4 - ((v - min) / (max - min)) * (H - 10);
    const x = (i) => (i / (historial.length - 1)) * W;
    const css = getComputedStyle(document.documentElement);
    const tono = (nombre, defecto) => (css.getPropertyValue(nombre).trim() || defecto);

    ctx.fillStyle = 'rgba(255,255,255,0.35)';
    ctx.font = '9px sans-serif';
    ctx.fillText(`${max}°`, 2, 10);
    ctx.fillText(`${min}°`, 2, H - 6);

    ctx.setLineDash([4, 3]);
    ctx.strokeStyle = tono('--accent-red', '#f38ba8');
    ctx.beginPath(); ctx.moveTo(0, y(u.gpu_limite)); ctx.lineTo(W, y(u.gpu_limite)); ctx.stroke();
    ctx.setLineDash([]);

    [['cpu', tono('--accent-blue', '#89b4fa')], ['gpu', tono('--accent-purple', '#cba6f7')]].forEach(([clave, col]) => {
      ctx.strokeStyle = col;
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      let empezado = false;
      historial.forEach((h, i) => {
        if (h[clave] == null) return;
        if (!empezado) { ctx.moveTo(x(i), y(h[clave])); empezado = true; } else ctx.lineTo(x(i), y(h[clave]));
      });
      ctx.stroke();
    });
  }

  function iniciar() {
    asegurarHueco();
    actualizar();
    temporizador = setInterval(actualizar, INTERVALO_MS);
    document.addEventListener('visibilitychange', () => { if (!document.hidden) actualizar(); });
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', iniciar);
  else iniciar();

  window.Temperaturas = { actualizar, abrir: () => { if (!abierto) alternarPanel(); } };
})();
