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
      if (abierto) pintarPanel(ultimo);
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
          La CPU no pausa nada${eficientes ? '; con el modo suave el motor usa los núcleos de eficiencia' : ''}. Se avisa a partir de ${u.cpu_aviso} °C.
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
