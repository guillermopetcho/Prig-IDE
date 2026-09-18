/*
 * Flujos de agentes: encadenar modelos pequeños, cada uno con una tarea.
 *
 * La pantalla tiene que dejar claras tres cosas que no se ven en un editor de
 * prompts corriente:
 *
 *   · CUÁNTAS VECES HAY QUE CARGAR UN MODELO. Con 6 GB solo cabe uno a la vez,
 *     así que alternar entre dos en pasos consecutivos cuesta una recarga cada
 *     vez. Reordenar los pasos para agrupar modelos es gratis y se nota.
 *   · QUÉ LEE CADA PASO. Las variables son la parte que más se equivoca al
 *     montar un flujo, y un error ahí no se ve hasta que el paso cuatro responde
 *     cualquier cosa.
 *   · QUÉ PASÓ EN CADA PASO AL EJECUTAR. Un flujo que da un mal resultado es
 *     imposible de arreglar si no sabes cuál de los cinco agentes lo estropeó.
 */

const Flujos = (() => {
  const $ = (id) => document.getElementById(id);

  let catalogo = { modelos: [], roles: [], variables: {}, variables_libro: {} };
  let flujoActual = null;
  let guardados = [];
  let plantillasDisponibles = [];
  let ambito = 'libre';
  let ejecutando = false;
  let cancelar = null;
  let libros = [];          // solo en el modo ficha
  let libroElegido = null;

  const ROL_POR_ID = () => Object.fromEntries(catalogo.roles.map((r) => [r.id, r]));

  // ------------------------------------------------------------------
  // Apertura
  // ------------------------------------------------------------------

  async function abrir(ambitoPedido) {
    ambito = ambitoPedido || 'libre';
    const modal = $('modal-flujos');
    if (!modal) return;
    modal.style.display = 'flex';

    const eti = $('flujos-ambito-eti');
    if (eti) {
      eti.textContent = { libro: '· desde la Biblioteca', plan: '· desde Aprendizaje Guiado',
                          ejercicio: '· para ejercicios',
                          ficha: '· analizar un libro entero' }[ambito] || '';
    }
    await cargarCatalogo();
    if (ambito === 'ficha') await cargarLibros();
    await cargarFlujos();
    if (ambito === 'ficha') {
      const f = plantillasDisponibles.find((x) => x.id === 'plantilla_ficha_libro');
      if (f) cargarEnEditor({ ...JSON.parse(JSON.stringify(f)), id: null });
    } else if (!flujoActual) {
      nuevoFlujo();
    }
  }

  async function cargarCatalogo() {
    try {
      catalogo = await prigFetchJson('/api/flujos/catalogo');
      const v = $('flujos-vram');
      if (v) {
        const caben = catalogo.modelos.filter((m) => m.instalado && m.cabe).length;
        v.innerHTML = `<i class="fa-solid fa-microchip"></i> ${catalogo.vram_gb} GB de VRAM · ` +
                      `${caben} modelos descargados que caben enteros`;
      }
    } catch (e) {
      catalogo = { modelos: [], roles: [], variables: {}, variables_libro: {} };
    }
  }

  async function recargarCatalogo() {
    await cargarCatalogo();
    const caja = $('flujo-editor');
    if (caja) {
      if (caja.dataset.vista === 'modelos') {
        caja.dataset.vista = '';
        abrirModelos();
      } else if (flujoActual) {
        pintarEditor();
      }
    }
  }

  async function cargarFlujos() {
    try {
      const r = await prigFetchJson('/api/flujos');
      guardados = r.flujos || [];
      plantillasDisponibles = (r.plantillas || []).filter(
        (p) => ambito === 'libre' || p.ambito === ambito || p.ambito === 'libre');
      if (!plantillasDisponibles.length) plantillasDisponibles = r.plantillas || [];
    } catch (e) {
      guardados = []; plantillasDisponibles = [];
    }
    pintarLateral();
  }

  async function cargarLibros() {
    try {
      const r = await prigFetchJson('/api/libros/analizables');
      libros = r.libros || [];
      if (!libroElegido && libros.length) libroElegido = libros[0].source_id;
    } catch (e) { libros = []; }
  }

  function selectorDeLibros() {
    if (ambito !== 'ficha') return '';
    if (!libros.length) {
      return `<div style="padding:8px 10px; margin-bottom:8px; border-radius:5px;
        background:rgba(249,226,175,0.10); border-left:3px solid var(--accent-yellow);
        font-size:11px;">
        No hay libros importados. Trae primero un <code>.prigpack</code> desde
        <b>Base de conocimiento → Importar</b>.</div>`;
    }
    return `
      <div style="padding:8px 10px; margin-bottom:8px; border-radius:5px;
        background:rgba(0,0,0,0.18);">
        <div style="font-size:10px; color:var(--text-muted); letter-spacing:.06em;
          text-transform:uppercase; margin-bottom:5px;">Qué libro analizar</div>
        <select id="libro-elegido" style="width:100%; padding:5px 8px; font-size:12px;
          background:var(--bg-dark); color:#fff; border:1px solid var(--border-color);
          border-radius:5px;">
          ${libros.map((l) => `<option value="${esc(l.source_id)}"
            ${l.source_id === libroElegido ? 'selected' : ''}>${esc(l.title)}
            — ${l.conceptos} conceptos, ${l.capitulos} capítulos${l.ficha_hecha ? ' · ya tiene ficha' : ''}
          </option>`).join('')}
        </select>
        <div id="libro-aviso" style="margin-top:5px; font-size:10.5px;"></div>
      </div>`;
  }

  function avisarSobreLibro() {
    const caja = $('libro-aviso');
    if (!caja) return;
    const l = libros.find((x) => x.source_id === libroElegido);
    if (!l) return;
    // Un libro con poco extraído dará una ficha pobre hagas lo que hagas: más vale
    // saberlo antes de gastar siete pasos de modelo.
    const pobre = l.conceptos < 10 || l.claims_verified < 25;
    const sinIndice = !l.capitulos;
    const partes = [];
    if (pobre) partes.push('Hay poco material extraído de este libro: la ficha saldrá pobre.');
    if (sinIndice) partes.push('Sin índice detectado, el temario se deducirá de las páginas de los conceptos.');
    caja.innerHTML = partes.length
      ? `<span style="color:var(--accent-yellow);">${esc(partes.join(' '))}</span>`
      : `<span style="color:var(--text-muted);">${l.claims_verified} afirmaciones ·
         ${l.figuras} figuras · ${l.pages || '?'} páginas</span>`;
  }

  // ------------------------------------------------------------------
  // Modelos: ver qué hay y descargar lo que falte
  // ------------------------------------------------------------------

  let descargando = null;

  function abrirModelos() {
    const caja = $('flujo-editor');
    if (!caja) return;
    if (caja.dataset.vista === 'modelos') { pintarEditor(); caja.dataset.vista = ''; return; }
    caja.dataset.vista = 'modelos';

    const generadores = catalogo.modelos.filter((m) => !m.embedding);
    const embebedores = catalogo.modelos.filter((m) => m.embedding);

    const fila = (m) => {
      // Un modelo que tu Ollama no puede descargar se marca ANTES de pulsar: el
      // registro responde con un error que ni siquiera dice qué versión tienes.
      const estado = m.instalado
        ? '<span style="color:var(--accent-green); font-size:11px;">descargado</span>'
        : (m.necesita_actualizar
          ? `<span style="font-size:10.5px; color:var(--accent-yellow);"
               title="Tu Ollama es anterior a este modelo">necesita Ollama ${esc(m.ollama_minimo)}</span>`
          : `<button class="mdl-bajar" data-modelo="${esc(m.modelo)}"
               style="font-size:10.5px; padding:2px 9px; border-radius:4px; cursor:pointer;
                 background:rgba(137,180,250,0.15); color:var(--accent-blue);
                 border:1px solid rgba(137,180,250,0.35);">
               <i class="fa-solid fa-download"></i> ${m.vram_gb} GB</button>`);
      // Un modelo que no cabe no se oculta: se puede usar, solo que repartiendo
      // con la CPU. Esconderlo obligaría a salir de Prig para decidirlo.
      const aviso = insigniaVeredicto(m);
      const piensa = { conmutable: ['piensa a demanda', 'var(--accent-purple)'],
                       siempre: ['piensa siempre', 'var(--accent-yellow)'] }[m.piensa];
      return `
        <div style="display:flex; gap:9px; align-items:baseline; padding:7px 4px;
          border-bottom:1px solid var(--border-color); flex-wrap:wrap;">
          <code style="font-size:12px; color:#fff; min-width:150px;">${esc(m.modelo)}</code>
          <span style="font-size:10.5px; color:var(--text-muted);">${esc(m.familia || '')}</span>
          ${m.razona ? `<span style="font-size:10px; color:var(--accent-green);"
            title="Capacidad de razonamiento, de 1 a 5">${'●'.repeat(m.razona)}</span>` : ''}
          ${piensa ? `<span style="font-size:10px; color:${piensa[1]};">${piensa[0]}</span>` : ''}
          ${aviso}
          <span style="flex:1"></span>
          ${estado}
          <div style="flex-basis:100%; font-size:10.5px; color:var(--text-muted); padding-left:2px;">
            ${esc(m.nota || '')}
            ${(m.fuerte_en || []).length ? `<b style="color:var(--accent-blue);">
              · para: ${esc(m.fuerte_en.join(', '))}</b>` : ''}
          </div>
        </div>`;
    };

    caja.innerHTML = `
      <div style="padding:4px 0 10px;">
        <div style="font-size:11px; color:var(--text-muted); margin-bottom:8px;">
          El veredicto de cada modelo lo calcula el gestor de recursos para tu
          máquina: pesos, caché de contexto y búfer, y la velocidad esperada. Un modelo
          repartido entre GPU y RAM funciona; un MoE repartido puede ir incluso rápido.
          El embebedor va en CPU para no competir por la GPU.
        </div>
        ${(catalogo.ollama_bloquea || []).length ? `
          <div style="padding:9px 11px; margin-bottom:9px; border-radius:5px;
            background:rgba(249,226,175,0.10); border-left:3px solid var(--accent-yellow);
            font-size:11.5px;">
            <b style="color:var(--accent-yellow);">Tu Ollama es la ${esc(catalogo.ollama)}</b>
            y no puede descargar ${esc(catalogo.ollama_bloquea.join(', '))} —
            incluido <b>Qwen3</b>, el más capaz que entra en tu tarjeta.
            <div style="margin-top:5px; font-family:monospace; font-size:10.5px;
              background:rgba(0,0,0,0.3); padding:5px 8px; border-radius:4px;
              user-select:all;">curl -fsSL https://ollama.com/install.sh | sh</div>
            <div style="margin-top:4px; color:var(--text-muted); font-size:10.5px;">
              En Linux conserva los modelos que ya tienes. Después, reabre este panel.</div>
          </div>` : ''}
        <div id="mdl-progreso" style="margin-bottom:8px;"></div>
        <div style="font-size:10px; letter-spacing:.06em; text-transform:uppercase;
          color:var(--text-muted); margin:6px 0 2px;">Generadores</div>
        ${generadores.map(fila).join('')}
        <div style="font-size:10px; letter-spacing:.06em; text-transform:uppercase;
          color:var(--text-muted); margin:14px 0 2px;">
          Embeddings <span style="text-transform:none; letter-spacing:0;">— eligen qué
          material se le da al generador; van en CPU y no ocupan VRAM</span></div>
        ${embebedores.map(fila).join('')}
      </div>`;

    caja.querySelectorAll('.mdl-bajar').forEach((b) =>
      b.addEventListener('click', () => descargar(b.dataset.modelo, b)));
  }

  async function descargar(modelo, boton) {
    if (descargando) return;
    descargando = modelo;
    const progreso = $('mdl-progreso');
    boton.disabled = true;
    boton.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> descargando';
    progreso.innerHTML = `<div style="padding:8px 10px; border-radius:5px;
      background:rgba(137,180,250,0.10); border-left:3px solid var(--accent-blue);
      font-size:11.5px;">Descargando <b>${esc(modelo)}</b>…</div>`;

    try {
      const res = await fetch('/api/flujos/descargar', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ modelo }),
      });
      if (!res.ok) throw new Error(await prigErrorDetail(res));
      const lector = res.body.getReader();
      const dec = new TextDecoder();
      let resto = '';
      while (true) {
        const { done, value } = await lector.read();
        if (done) break;
        resto += dec.decode(value, { stream: true });
        const lineas = resto.split('\n');
        resto = lineas.pop();
        for (const l of lineas) {
          if (!l.trim()) continue;
          let ev;
          try { ev = JSON.parse(l); } catch (e) { continue; }
          if (ev.tipo === 'avance' && ev.texto) {
            progreso.innerHTML = `<div style="padding:8px 10px; border-radius:5px;
              background:rgba(137,180,250,0.10); border-left:3px solid var(--accent-blue);
              font-size:11.5px;"><b>${esc(modelo)}</b> · ${esc(ev.texto)}</div>`;
          } else if (ev.tipo === 'error') {
            throw new Error(ev.mensaje);
          }
        }
      }
      progreso.innerHTML = `<div style="padding:8px 10px; border-radius:5px;
        background:rgba(166,227,161,0.10); border-left:3px solid var(--accent-green);
        font-size:11.5px; color:var(--accent-green);"><b>${esc(modelo)}</b> descargado.
        Ya puedes elegirlo en cualquier paso.</div>`;
      await recargarCatalogo();
      if (typeof window.refreshAllModelLists === 'function') {
        window.refreshAllModelLists(modelo);
      }
    } catch (e) {
      progreso.innerHTML = `<div style="padding:8px 10px; border-radius:5px;
        background:rgba(243,139,168,0.10); border-left:3px solid var(--accent-red);
        font-size:11.5px; color:var(--accent-red);">${esc(e.message)}</div>`;
      boton.disabled = false;
      boton.innerHTML = '<i class="fa-solid fa-download"></i> reintentar';
    } finally {
      descargando = null;
    }
  }

  // ------------------------------------------------------------------
  // Lateral
  // ------------------------------------------------------------------

  function pintarLateral() {
    const caja = $('flujos-lateral');
    if (!caja) return;

    const fila = (f, esPlantilla) => `
      <div class="flujo-item" data-id="${esc(f.id)}" data-plantilla="${esPlantilla ? 1 : 0}"
        style="padding:7px 8px; border-radius:5px; cursor:pointer; margin-bottom:3px;
               border:1px solid ${flujoActual && flujoActual.id === f.id ? 'var(--accent-purple)' : 'transparent'};
               background:${flujoActual && flujoActual.id === f.id ? 'rgba(203,166,247,0.10)' : 'transparent'};">
        <div style="display:flex; justify-content:space-between; gap:6px; align-items:baseline;">
          <b style="font-size:12px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">${esc(f.nombre)}</b>
          ${esPlantilla ? '' : `<button class="flujo-borrar" data-id="${esc(f.id)}" title="Borrar"
            style="background:none;border:none;color:var(--text-muted);cursor:pointer;font-size:10px;padding:0 2px;">✕</button>`}
        </div>
        <div style="color:var(--text-muted); font-size:10px; margin-top:2px;">
          ${(f.pasos || []).length} pasos · ${esc(f.descripcion || '').slice(0, 64)}
        </div>
      </div>`;

    caja.innerHTML = `
      ${guardados.length ? `<div style="color:var(--text-muted); font-size:10px; letter-spacing:.06em;
        text-transform:uppercase; margin:2px 0 6px;">Tus flujos</div>
        ${guardados.map((f) => fila(f, false)).join('')}` : ''}
      <div style="color:var(--text-muted); font-size:10px; letter-spacing:.06em; text-transform:uppercase;
        margin:${guardados.length ? '12px' : '2px'} 0 6px;">Plantillas</div>
      ${plantillasDisponibles.map((f) => fila(f, true)).join('')}
      <div style="color:var(--text-muted); font-size:10px; letter-spacing:.06em; text-transform:uppercase;
        margin:14px 0 6px;">Ejecuciones recientes</div>
      <div id="flujos-historial" style="font-size:11px; color:var(--text-muted);">cargando…</div>`;

    caja.querySelectorAll('.flujo-item').forEach((el) => {
      el.addEventListener('click', (ev) => {
        if (ev.target.classList.contains('flujo-borrar')) return;
        const esPlantilla = el.dataset.plantilla === '1';
        const lista = esPlantilla ? plantillasDisponibles : guardados;
        const f = lista.find((x) => x.id === el.dataset.id);
        if (!f) return;
        // Una plantilla se abre como copia: editarla no debe pisar el original
        cargarEnEditor(esPlantilla ? { ...JSON.parse(JSON.stringify(f)), id: null,
                                       nombre: f.nombre + ' (copia)' } : f);
      });
    });
    caja.querySelectorAll('.flujo-borrar').forEach((b) => {
      b.addEventListener('click', async (ev) => {
        ev.stopPropagation();
        try {
          await prigFetchJson(`/api/flujos/${encodeURIComponent(b.dataset.id)}`, { method: 'DELETE' });
          if (flujoActual && flujoActual.id === b.dataset.id) nuevoFlujo();
          await cargarFlujos();
        } catch (e) { alert(e.message); }
      });
    });
    cargarHistorial();
  }

  async function cargarHistorial() {
    const caja = $('flujos-historial');
    if (!caja) return;
    try {
      const r = await prigFetchJson('/api/flujos/historial?limite=8');
      const filas = r.ejecuciones || [];
      if (!filas.length) { caja.textContent = 'Todavía ninguna.'; return; }
      caja.innerHTML = filas.map((h) => `
        <div class="hist-item" data-id="${esc(h.id)}"
          style="padding:5px 7px; border-radius:4px; cursor:pointer; margin-bottom:2px;
                 border-left:2px solid var(--accent-blue);">
          <div style="overflow:hidden; text-overflow:ellipsis; white-space:nowrap; color:#fff; font-size:11px;">
            ${esc(h.flujo_nombre || 'sin nombre')}</div>
          <div style="font-size:10px;">${esc((h.entrada || '').slice(0, 40))} ·
            ${h.n_pasos} pasos · ${Math.round(h.segundos)}s</div>
        </div>`).join('');
      caja.querySelectorAll('.hist-item').forEach((el) => {
        el.addEventListener('click', () => verEjecucion(el.dataset.id));
      });
    } catch (e) {
      caja.textContent = 'No se pudo leer el historial.';
    }
  }

  // ------------------------------------------------------------------
  // Editor
  // ------------------------------------------------------------------

  function nuevoFlujo() {
    const base = (catalogo.modelos.find((m) => m.instalado && m.cabe) || {}).modelo
                 || 'qwen2.5-coder:7b';
    cargarEnEditor({
      id: null, nombre: 'Flujo sin título', descripcion: '', ambito,
      pasos: [pasoNuevo(1, base)],
    });
  }

  function pasoNuevo(n, modelo) {
    const rol = catalogo.roles[0] || { id: 'razonar', temperatura: 0.4, formato: 'texto' };
    return {
      id: `paso${n}`, nombre: `Paso ${n}`, rol: rol.id, modelo,
      prompt: n === 1 ? '{entrada}' : '{anterior}',
      sistema: '', formato: rol.formato, temperatura: rol.temperatura,
      max_tokens: 1200, si_falla: null,
    };
  }

  function cargarEnEditor(flujo) {
    flujoActual = flujo;
    $('flujo-nombre').value = flujo.nombre || '';
    $('flujo-descripcion').value = flujo.descripcion || '';
    $('flujo-ejecucion').style.display = 'none';
    $('flujo-editor').style.display = '';
    pintarEditor();
    pintarLateral();
  }

  function pintarEditor() {
    const caja = $('flujo-editor');
    if (!caja || !flujoActual) return;
    const roles = ROL_POR_ID();

    caja.innerHTML = selectorDeLibros()
      + flujoActual.pasos.map((p, i) => tarjetaPaso(p, i, roles)).join('')
      + `<button id="btn-anadir-paso" style="width:100%; margin-top:8px; padding:9px; border-radius:6px;
           background:transparent; border:1px dashed var(--border-color); color:var(--text-muted);
           cursor:pointer; font-size:12px;">
           <i class="fa-solid fa-plus"></i> Añadir paso</button>`;

    enlazarEditor();
    revisarFlujo();
  }

  function tarjetaPaso(paso, i, roles) {
    const rol = roles[paso.rol] || {};
    const opcRoles = catalogo.roles.map((r) =>
      `<option value="${r.id}" ${r.id === paso.rol ? 'selected' : ''}>${esc(r.nombre)}</option>`).join('');

    const opcModelos = catalogo.modelos.map((m) => {
      const marca = !m.instalado ? ' — sin descargar'
        : (m.veredicto && m.veredicto !== 'entero'
          ? ` — ${m.etiqueta}${m.tok_s ? ` (~${m.tok_s} tok/s)` : ''}`
          : (!m.cabe ? ' — no cabe entero' : ''));
      return `<option value="${esc(m.modelo)}" ${m.modelo === paso.modelo ? 'selected' : ''}
        ${!m.instalado ? 'disabled' : ''}>${esc(m.modelo)}${marca}</option>`;
    }).join('');

    const anteriores = flujoActual.pasos.slice(0, i).map((p) => p.id);
    const opcVolver = ['<option value="">no devolver el trabajo</option>']
      .concat(anteriores.map((id) => `<option value="${esc(id)}"
        ${(paso.si_falla || {}).volver_a === id ? 'selected' : ''}>volver a «${esc(id)}»</option>`)).join('');

    const puedeRevisar = paso.rol === 'criticar' || paso.rol === 'verificar';

    return `
      <div class="paso-tarjeta" data-i="${i}" style="border:1px solid var(--border-color); border-radius:7px;
        margin-top:10px; background: var(--bg-panel); overflow:hidden;">
        <div style="display:flex; align-items:center; gap:8px; padding:8px 10px;
          background: rgba(0,0,0,0.18); border-bottom:1px solid var(--border-color);">
          <span style="font-family:monospace; font-size:11px; color:var(--accent-purple);
            background:rgba(203,166,247,0.13); padding:2px 7px; border-radius:3px;">${i + 1}</span>
          <input class="p-nombre" value="${esc(paso.nombre)}" placeholder="Nombre del agente"
            style="flex:1; background:transparent; border:none; color:#fff; font-size:13px; font-weight:600;">
          <code style="font-size:10px; color:var(--text-muted);">${esc(paso.id)}</code>
          <button class="p-subir tool-btn" title="Subir" ${i === 0 ? 'disabled' : ''}
            style="font-size:10px; padding:2px 6px;">↑</button>
          <button class="p-bajar tool-btn" title="Bajar" ${i === flujoActual.pasos.length - 1 ? 'disabled' : ''}
            style="font-size:10px; padding:2px 6px;">↓</button>
          <button class="p-borrar tool-btn" title="Quitar este paso"
            style="font-size:10px; padding:2px 6px; color:var(--accent-red);">✕</button>
        </div>

        <div style="padding:9px 10px; display:flex; gap:8px; flex-wrap:wrap; align-items:center;">
          <select class="p-rol" style="font-size:11px; background:var(--bg-dark); color:#fff;
            border:1px solid var(--border-color); border-radius:4px; padding:3px 6px;">${opcRoles}</select>
          <select class="p-modelo" style="font-size:11px; background:var(--bg-dark); color:#fff;
            border:1px solid var(--border-color); border-radius:4px; padding:3px 6px; max-width:210px;">${opcModelos}</select>
          <span style="font-size:10px; color:var(--text-muted); flex:1; min-width:150px;">${esc(rol.ayuda || '')}</span>
        </div>

        <textarea class="p-prompt" rows="4" placeholder="Qué tiene que hacer este agente…"
          style="width:calc(100% - 20px); margin:0 10px; padding:7px 9px; background:var(--bg-dark);
            border:1px solid var(--border-color); color:#fff; border-radius:5px; font-size:12px;
            font-family:monospace; resize:vertical;">${esc(paso.prompt)}</textarea>

        <div style="padding:6px 10px 9px; display:flex; gap:5px; flex-wrap:wrap; align-items:center;">
          <span style="font-size:10px; color:var(--text-muted);">Insertar:</span>
          ${variablesDisponibles(i).map((v) => `<button class="p-var" data-v="${esc(v)}"
            title="${esc((catalogo.variables || {})[v] || (catalogo.variables_libro || {})[v]
                         || 'Salida del paso ' + v.replace('paso:', ''))}"
            style="font-size:10px; font-family:monospace; padding:1px 6px; border-radius:3px;
              background:rgba(137,180,250,0.13); color:var(--accent-blue);
              border:1px solid rgba(137,180,250,0.3); cursor:pointer;">{${esc(v)}}</button>`).join('')}
          <span style="flex:1"></span>
          <button class="p-avanzado" style="font-size:10px; background:none; border:none;
            color:var(--text-muted); cursor:pointer;">⚙ avanzado</button>
        </div>

        <div class="p-avanzado-caja" style="display:none; padding:0 10px 10px; gap:8px; flex-direction:column;">
          <div style="display:flex; gap:10px; flex-wrap:wrap; align-items:center; font-size:11px;">
            <label>Temperatura
              <input class="p-temp" type="number" min="0" max="1" step="0.1" value="${paso.temperatura}"
                style="width:56px; background:var(--bg-dark); color:#fff; border:1px solid var(--border-color);
                  border-radius:4px; padding:2px 5px;"></label>
            <label>Tope de salida
              <input class="p-tokens" type="number" min="200" max="4000" step="100" value="${paso.max_tokens}"
                style="width:72px; background:var(--bg-dark); color:#fff; border:1px solid var(--border-color);
                  border-radius:4px; padding:2px 5px;"></label>
            <label>Formato
              <select class="p-formato" style="background:var(--bg-dark); color:#fff;
                border:1px solid var(--border-color); border-radius:4px; padding:2px 5px;">
                <option value="texto" ${paso.formato === 'texto' ? 'selected' : ''}>texto</option>
                <option value="json" ${paso.formato === 'json' ? 'selected' : ''}>JSON</option>
              </select></label>
          </div>
          ${puedeRevisar ? `<div style="font-size:11px;">
            <label>Si encuentra problemas:
              <select class="p-volver" style="background:var(--bg-dark); color:#fff;
                border:1px solid var(--border-color); border-radius:4px; padding:2px 5px;">${opcVolver}</select></label>
            <label style="margin-left:8px;">como mucho
              <input class="p-vueltas" type="number" min="1" max="3"
                value="${(paso.si_falla || {}).max_vueltas || 2}"
                style="width:46px; background:var(--bg-dark); color:#fff; border:1px solid var(--border-color);
                  border-radius:4px; padding:2px 5px;"> veces</label>
            <div style="color:var(--text-muted); font-size:10px; margin-top:3px;">
              El paso al que vuelva verá los problemas señalados y rehará el trabajo.</div>
          </div>` : ''}
          <label style="font-size:11px; color:var(--text-muted);">Instrucción de sistema propia
            (vacío = la del rol, que suele ser mejor)
            <textarea class="p-sistema" rows="2" style="width:100%; margin-top:3px; background:var(--bg-dark);
              border:1px solid var(--border-color); color:#fff; border-radius:4px; padding:5px;
              font-size:11px;">${esc(paso.sistema || '')}</textarea></label>
        </div>
      </div>`;
  }

  function variablesDisponibles(i) {
    const base = ['entrada', 'contexto', 'titulo'];
    // En el modo ficha el libro entero está troceado en variables: son las que de
    // verdad se usan ahí, así que van primero.
    if (ambito === 'ficha') base.unshift(...Object.keys(catalogo.variables_libro || {}));
    if (i > 0) base.push('anterior');
    flujoActual.pasos.slice(0, i).forEach((p) => base.push(`paso:${p.id}`));
    // {critica} solo se ofrece si algún revisor devuelve el trabajo a este paso
    const miId = flujoActual.pasos[i].id;
    if (flujoActual.pasos.some((p) => (p.si_falla || {}).volver_a === miId)) base.push('critica');
    return base;
  }

  function enlazarEditor() {
    const caja = $('flujo-editor');

    const leer = (el, clase) => el.querySelector(clase);
    caja.querySelectorAll('.paso-tarjeta').forEach((tarjeta) => {
      const i = +tarjeta.dataset.i;
      const paso = flujoActual.pasos[i];

      leer(tarjeta, '.p-nombre').addEventListener('input', (e) => { paso.nombre = e.target.value; });
      leer(tarjeta, '.p-prompt').addEventListener('input', (e) => {
        paso.prompt = e.target.value; revisarFlujo();
      });
      leer(tarjeta, '.p-modelo').addEventListener('change', (e) => {
        paso.modelo = e.target.value; revisarFlujo();
      });
      leer(tarjeta, '.p-rol').addEventListener('change', (e) => {
        paso.rol = e.target.value;
        const r = ROL_POR_ID()[paso.rol];
        if (r) { paso.formato = r.formato; paso.temperatura = r.temperatura; }
        if (paso.rol !== 'criticar' && paso.rol !== 'verificar') paso.si_falla = null;
        pintarEditor();
      });

      const avz = leer(tarjeta, '.p-avanzado');
      const cajaAvz = leer(tarjeta, '.p-avanzado-caja');
      avz.addEventListener('click', () => {
        cajaAvz.style.display = cajaAvz.style.display === 'flex' ? 'none' : 'flex';
      });
      const temp = leer(tarjeta, '.p-temp');
      if (temp) temp.addEventListener('input', (e) => { paso.temperatura = parseFloat(e.target.value); });
      const tok = leer(tarjeta, '.p-tokens');
      if (tok) tok.addEventListener('input', (e) => { paso.max_tokens = parseInt(e.target.value, 10); });
      const fmt = leer(tarjeta, '.p-formato');
      if (fmt) fmt.addEventListener('change', (e) => { paso.formato = e.target.value; });
      const sis = leer(tarjeta, '.p-sistema');
      if (sis) sis.addEventListener('input', (e) => { paso.sistema = e.target.value; });

      const volver = leer(tarjeta, '.p-volver');
      if (volver) {
        volver.addEventListener('change', (e) => {
          paso.si_falla = e.target.value
            ? { volver_a: e.target.value, max_vueltas: +(leer(tarjeta, '.p-vueltas').value || 2) }
            : null;
          pintarEditor();
        });
        const vueltas = leer(tarjeta, '.p-vueltas');
        if (vueltas) vueltas.addEventListener('input', (e) => {
          if (paso.si_falla) paso.si_falla.max_vueltas = +e.target.value;
        });
      }

      tarjeta.querySelectorAll('.p-var').forEach((b) => {
        b.addEventListener('click', () => {
          const ta = leer(tarjeta, '.p-prompt');
          const pos = ta.selectionStart || ta.value.length;
          const texto = `{${b.dataset.v}}`;
          ta.value = ta.value.slice(0, pos) + texto + ta.value.slice(pos);
          paso.prompt = ta.value;
          ta.focus();
          ta.selectionStart = ta.selectionEnd = pos + texto.length;
          revisarFlujo();
        });
      });

      leer(tarjeta, '.p-subir').addEventListener('click', () => mover(i, -1));
      leer(tarjeta, '.p-bajar').addEventListener('click', () => mover(i, 1));
      leer(tarjeta, '.p-borrar').addEventListener('click', () => {
        if (flujoActual.pasos.length === 1) return;
        flujoActual.pasos.splice(i, 1);
        pintarEditor();
      });
    });

    const sel = $('libro-elegido');
    if (sel) {
      sel.addEventListener('change', () => { libroElegido = sel.value; avisarSobreLibro(); });
      avisarSobreLibro();
    }

    $('btn-anadir-paso').addEventListener('click', () => {
      const n = flujoActual.pasos.length + 1;
      const ultimo = flujoActual.pasos[flujoActual.pasos.length - 1];
      flujoActual.pasos.push(pasoNuevo(n, ultimo ? ultimo.modelo : 'qwen2.5-coder:7b'));
      pintarEditor();
    });
  }

  function mover(i, delta) {
    const j = i + delta;
    if (j < 0 || j >= flujoActual.pasos.length) return;
    const [p] = flujoActual.pasos.splice(i, 1);
    flujoActual.pasos.splice(j, 0, p);
    pintarEditor();
  }

  // ------------------------------------------------------------------
  // Validación y plan de carga
  // ------------------------------------------------------------------

  let temporizadorRevision = null;

  function revisarFlujo() {
    clearTimeout(temporizadorRevision);
    temporizadorRevision = setTimeout(async () => {
      if (!flujoActual) return;
      const caja = $('flujo-plan');
      try {
        const r = await prigFetchJson('/api/flujos/validar', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ ...flujoActual, nombre: $('flujo-nombre').value || 'x' }),
        });
        pintarPlan(r.plan, r.problemas);
      } catch (e) {
        if (caja) caja.innerHTML = `<span style="color:var(--accent-red);">${esc(e.message)}</span>`;
      }
    }, 350);
  }

  function pintarPlan(plan, problemas) {
    const caja = $('flujo-plan');
    if (!caja) return;
    const evitables = plan.recargas_evitables;
    caja.innerHTML = `
      <div style="display:flex; gap:12px; flex-wrap:wrap; align-items:center;
        padding:6px 10px; border-radius:5px; background:rgba(0,0,0,0.18);">
        <span><b style="color:var(--accent-purple);">${plan.modelos.length}</b> modelos ·
          <b>${plan.cargas}</b> cargas</span>
        ${evitables ? `<span style="color:var(--accent-yellow);" title="Con 6 GB solo cabe un modelo a la vez.
Si agrupas los pasos que usan el mismo modelo, te ahorras ${evitables} recargas de unos 8 s cada una.">
          ⚠ ${evitables} recarga(s) evitables reordenando</span>` : ''}
        <span style="color:var(--text-muted);">~${plan.segundos_estimados_de_carga}s solo en cargar modelos</span>
        ${!plan.cabe_en_vram ? `<span style="color:var(--accent-red);">
          algún modelo no cabe entero en la GPU: irá mucho más lento</span>` : ''}
      </div>
      ${(problemas || []).length ? `<div style="margin-top:6px; padding:7px 10px; border-radius:5px;
        background:rgba(243,139,168,0.10); border-left:3px solid var(--accent-red); font-size:11px;">
        ${problemas.map((p) => `<div style="color:var(--accent-red);">${esc(p)}</div>`).join('')}
      </div>` : ''}`;
  }

  // ------------------------------------------------------------------
  // Ejecución
  // ------------------------------------------------------------------

  async function guardar() {
    if (!flujoActual) return;
    flujoActual.nombre = $('flujo-nombre').value.trim() || 'Flujo sin título';
    flujoActual.descripcion = $('flujo-descripcion').value.trim();
    flujoActual.ambito = flujoActual.ambito || ambito;
    try {
      const g = await prigFetchJson('/api/flujos', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(flujoActual),
      });
      flujoActual = g;
      await cargarFlujos();
      avisar('Flujo guardado', 'var(--accent-green)');
    } catch (e) { avisar('No se pudo guardar: ' + e.message, 'var(--accent-red)'); }
  }

  async function ejecutar() {
    if (!flujoActual || ejecutando) return;
    flujoActual.nombre = $('flujo-nombre').value.trim() || 'Flujo sin título';

    let entrada = '';
    if (ambito === 'ficha') {
      if (!libroElegido) { alert('Elige primero un libro.'); return; }
      const l = libros.find((x) => x.source_id === libroElegido);
      if (l && l.ficha_hecha &&
          !confirm(`«${l.title}» ya tiene ficha. ¿Rehacerla? La anterior se reemplaza.`)) {
        return;
      }
    } else {
      entrada = prompt(
        'Sobre qué quieres que trabaje el flujo\n\n' +
        'Es lo que recibe el primer agente en {entrada}, y lo que se usa para buscar ' +
        'material en tu biblioteca si algún paso pide {contexto}.', '');
      if (entrada === null) return;
    }

    $('flujo-editor').style.display = 'none';
    const vista = $('flujo-ejecucion');
    vista.style.display = '';
    vista.innerHTML = '<div style="color:var(--text-muted); padding:14px;">Preparando…</div>';

    ejecutando = true;
    const btn = $('btn-flujo-ejecutar');
    btn.innerHTML = '<i class="fa-solid fa-stop"></i> Detener';

    const control = new AbortController();
    cancelar = () => control.abort();

    try {
      // El modo ficha va por su propio endpoint: le pasa al flujo el libro
      // entero troceado en variables y guarda la ficha que sale.
      const destino = ambito === 'ficha' ? '/api/libros/ficha' : '/api/flujos/ejecutar';
      const cuerpo = ambito === 'ficha'
        ? { source_id: libroElegido, flujo: flujoActual }
        : { flujo: flujoActual, entrada, consulta_contexto: entrada,
            guardar_historial: true };
      const res = await fetch(destino, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        signal: control.signal, body: JSON.stringify(cuerpo),
      });
      if (!res.ok) throw new Error(await prigErrorDetail(res));
      vista.innerHTML = '';
      await leerEventos(res, vista);
    } catch (e) {
      if (e.name !== 'AbortError') {
        vista.innerHTML += `<div style="color:var(--accent-red); padding:10px;">${esc(e.message)}</div>`;
      } else {
        vista.innerHTML += '<div style="color:var(--text-muted); padding:10px;">Detenido.</div>';
      }
    } finally {
      ejecutando = false; cancelar = null;
      btn.innerHTML = '<i class="fa-solid fa-play"></i> Ejecutar';
      cargarHistorial();
      if (ambito === 'ficha') cargarLibros();
    }
  }

  async function leerEventos(res, vista) {
    const lector = res.body.getReader();
    const dec = new TextDecoder();
    let resto = '';
    while (true) {
      const { done, value } = await lector.read();
      if (done) break;
      resto += dec.decode(value, { stream: true });
      const lineas = resto.split('\n');
      resto = lineas.pop();
      for (const l of lineas) {
        if (!l.trim()) continue;
        let ev;
        try { ev = JSON.parse(l); } catch (e) { continue; }
        pintarEvento(ev, vista);
        vista.scrollTop = vista.scrollHeight;
      }
    }
  }

  function insigniaVeredicto(m) {
    if (!m.veredicto) {
      return m.cabe ? '' :
        `<span title="No entra entero en tu GPU: parte iría a RAM y sería mucho más lento"
           style="font-size:10px; color:var(--accent-yellow);">no cabe</span>`;
    }
    const color = {
      entero: 'var(--accent-green)', ajustando: 'var(--accent-green)',
      parcial: 'var(--accent-yellow)', solo_cpu: 'var(--accent-yellow)',
      lento: 'var(--accent-red)', no_viable: 'var(--accent-red)',
      embeddings: 'var(--text-muted)',
    }[m.veredicto] || 'var(--text-muted)';
    const vel = m.tok_s && m.veredicto !== 'embeddings' ? ` · ~${m.tok_s} tok/s` : '';
    const est = m.estimado ? ' (estimado)' : '';
    return `<span title="${esc(m.motivo || '')}" style="font-size:10px; color:${color};">
      ${esc(m.etiqueta)}${vel}${est}</span>`;
  }

  function pintarEvento(ev, vista) {
    if (ev.tipo === 'enfriando' || ev.tipo === 'reanudando' || ev.tipo === 'aviso_termico') {
      const icono = { enfriando: 'fa-pause', reanudando: 'fa-play', aviso_termico: 'fa-temperature-high' }[ev.tipo];
      const col = ev.tipo === 'reanudando' ? 'var(--accent-green)' : 'var(--accent-yellow)';
      vista.insertAdjacentHTML('beforeend', `
        <div style="padding:5px 0; color:${col}; font-size:11px;">
          <i class="fa-solid ${icono}"></i> ${esc(ev.mensaje || 'Pausa para enfriar la GPU')}
        </div>`);
      if (window.Temperaturas) window.Temperaturas.actualizar();
      return;
    }
    if (ev.tipo === 'inicio') {
      vista.insertAdjacentHTML('beforeend', `
        <div style="padding:8px 0; color:var(--text-muted); font-size:11px;">
          ${ev.pasos} pasos · ${ev.plan.modelos.length} modelos · ${ev.plan.cargas} cargas
        </div>`);
    } else if (ev.tipo === 'paso_inicio') {
      vista.insertAdjacentHTML('beforeend', `
        <div id="ev-${ev.indice}-${ev.id}" style="border:1px solid var(--border-color); border-radius:7px;
          margin-bottom:9px; overflow:hidden;">
          <div style="padding:8px 11px; background:rgba(0,0,0,0.18); display:flex; gap:9px;
            align-items:center; flex-wrap:wrap;">
            <i class="fa-solid fa-spinner fa-spin" style="color:var(--accent-blue);"></i>
            <b style="font-size:12.5px;">${esc(ev.nombre)}</b>
            <span style="font-size:10px; color:var(--text-muted);">${esc(ev.rol)}</span>
            <code style="font-size:10px; color:var(--accent-purple);">${esc(ev.modelo)}</code>
            ${ev.recarga_modelo ? '<span style="font-size:10px; color:var(--accent-yellow);" title="Hay que cargar este modelo en la GPU: unos 8 segundos">cargando modelo…</span>' : ''}
            <span style="flex:1"></span>
            <span style="font-size:10px; color:var(--text-muted);">${ev.tokens_prompt} tokens de entrada</span>
          </div>
          <div class="ev-salida" style="padding:10px 12px; font-size:12px; white-space:pre-wrap;
            color:var(--text-muted);">trabajando…</div>
        </div>`);
    } else if (ev.tipo === 'paso_fin') {
      const nodo = document.getElementById(`ev-${ev.indice}-${ev.id}`);
      if (!nodo) return;
      nodo.querySelector('.fa-spinner').outerHTML =
        '<i class="fa-solid fa-circle-check" style="color:var(--accent-green);"></i>';
      const cab = nodo.querySelector('div');
      cab.insertAdjacentHTML('beforeend',
        `<span style="font-size:10px; color:var(--text-muted);"> · ${ev.segundos}s</span>`);
      const salida = nodo.querySelector('.ev-salida');
      salida.style.color = '#fff';
      salida.textContent = ev.salida;
      if (ev.formato === 'json') salida.style.fontFamily = 'monospace';
    } else if (ev.tipo === 'vuelta') {
      vista.insertAdjacentHTML('beforeend', `
        <div style="margin:-2px 0 9px; padding:8px 11px; border-radius:6px;
          background:rgba(249,226,175,0.10); border-left:3px solid var(--accent-yellow); font-size:11.5px;">
          <b style="color:var(--accent-yellow);">El revisor devuelve el trabajo a «${esc(ev.hacia)}»</b>
          <span style="color:var(--text-muted);"> (intento ${ev.vuelta} de ${ev.de})</span>
          <div style="margin-top:4px; white-space:pre-wrap; color:var(--text-muted);">${esc(ev.motivo)}</div>
        </div>`);
    } else if (ev.tipo === 'aviso') {
      vista.insertAdjacentHTML('beforeend',
        `<div style="padding:7px 11px; color:var(--accent-yellow); font-size:11.5px;">${esc(ev.mensaje)}</div>`);
    } else if (ev.tipo === 'error') {
      vista.insertAdjacentHTML('beforeend', `
        <div style="padding:9px 11px; border-radius:6px; background:rgba(243,139,168,0.10);
          border-left:3px solid var(--accent-red); font-size:12px;">
          <b style="color:var(--accent-red);">${esc(ev.mensaje)}</b>
          ${(ev.problemas || []).map((p) => `<div style="color:var(--accent-red);">· ${esc(p)}</div>`).join('')}
        </div>`);
    } else if (ev.tipo === 'ficha') {
      vista.insertAdjacentHTML('beforeend', pintarFicha(ev.ficha));
    } else if (ev.tipo === 'fin') {
      vista.insertAdjacentHTML('beforeend', `
        <div style="margin-top:6px; padding:9px 11px; border-radius:6px;
          background:rgba(166,227,161,0.10); border-left:3px solid var(--accent-green);
          display:flex; gap:10px; align-items:center; flex-wrap:wrap;">
          <b style="color:var(--accent-green);">Terminado en ${ev.segundos}s</b>
          <span style="flex:1"></span>
          <button id="btn-flujo-copiar" class="tool-btn" style="font-size:11px; padding:3px 10px;">
            <i class="fa-solid fa-copy"></i> Copiar resultado</button>
          <button id="btn-flujo-volver" class="tool-btn" style="font-size:11px; padding:3px 10px;">
            <i class="fa-solid fa-pen"></i> Volver al editor</button>
        </div>`);
      const copiar = $('btn-flujo-copiar');
      if (copiar) copiar.addEventListener('click', () => {
        navigator.clipboard.writeText(ev.final || '').then(
          () => { copiar.innerHTML = '<i class="fa-solid fa-check"></i> Copiado'; }, () => {});
      });
      const volver = $('btn-flujo-volver');
      if (volver) volver.addEventListener('click', () => {
        $('flujo-ejecucion').style.display = 'none';
        $('flujo-editor').style.display = '';
      });
    }
  }

  // ------------------------------------------------------------------
  // La ficha del libro
  // ------------------------------------------------------------------

  function pintarFicha(f) {
    if (!f) return '';
    const ident = f.identidad || {};
    const medido = f.medido || {};
    const bloque = (titulo, cuerpo) => cuerpo
      ? `<div style="margin-top:12px;">
           <div style="font-size:10px; letter-spacing:.07em; text-transform:uppercase;
             color:var(--accent-purple); margin-bottom:5px;">${esc(titulo)}</div>
           ${cuerpo}</div>`
      : '';

    const temario = (f.temario && (f.temario.capitulos || f.temario)) || [];
    const filasTemario = Array.isArray(temario) ? temario.filter((c) => c && c.titulo) : [];

    const ejercicios = (f.ejercicios && (f.ejercicios.propuestas || f.ejercicios)) || [];
    const lagunas = (f.lagunas && (f.lagunas.no_cubre || f.lagunas)) || [];
    const asume = (f.asume && (f.asume.asume || f.asume)) || [];
    const notacion = (f.notacion && (f.notacion.simbolos || f.notacion)) || [];
    const rutas = ident.rutas || [];

    return `
      <div style="margin-top:14px; padding:14px; border:1px solid var(--accent-purple);
        border-radius:8px; background:rgba(203,166,247,0.05);">
        <div style="display:flex; justify-content:space-between; align-items:baseline;
          flex-wrap:wrap; gap:8px;">
          <b style="font-size:15px;">${esc(f.titulo)}</b>
          <span style="font-size:11px; color:var(--text-muted);">
            ${esc(f.campo || '')} · ${f.paginas || '?'} páginas ·
            ${esc((ident.nivel || 'nivel sin determinar'))}</span>
        </div>
        ${ident.que_cubre ? `<div style="margin-top:6px; font-size:13px;">${esc(ident.que_cubre)}</div>` : ''}
        ${ident.para_quien ? `<div style="font-size:11px; color:var(--text-muted); margin-top:3px;">
          Para: ${esc(ident.para_quien)}${ident.estilo ? ' · ' + esc(ident.estilo) : ''}</div>` : ''}

        <div style="margin-top:10px; display:flex; gap:14px; flex-wrap:wrap; font-size:11px;
          color:var(--text-muted); padding-top:9px; border-top:1px solid var(--border-color);">
          <span><b style="color:#fff;">${medido.conceptos || 0}</b> conceptos</span>
          <span><b style="color:#fff;">${medido.afirmaciones || 0}</b> afirmaciones</span>
          <span><b style="color:#fff;">${medido.capitulos || 0}</b> capítulos</span>
          <span><b style="color:#fff;">${medido.figuras || 0}</b> figuras</span>
          <span title="Conceptos con al menos tres afirmaciones: sobre estos se puede montar un ejercicio que se apoye en el libro">
            <b style="color:var(--accent-green);">${(medido.conceptos_con_material || []).length}</b>
            con material para ejercicios</span>
        </div>

        ${bloque('Da por sabido', asume.length ? `<ul style="margin:0; padding-left:18px; font-size:12px;">
          ${asume.map((a) => `<li>${esc(nombrar(a))}${a.se_ve_en ? ` <span style="color:var(--text-muted);">— ${esc(a.se_ve_en)}</span>` : ''}</li>`).join('')}
        </ul>` : '')}

        ${bloque('Temario', filasTemario.length ? `
          <div style="overflow-x:auto;"><table style="width:100%; font-size:11.5px; border-collapse:collapse;">
            <tr style="color:var(--text-muted); font-size:10px; text-transform:uppercase;">
              <th style="text-align:left; padding:3px 8px 3px 0;">Cap</th>
              <th style="text-align:left; padding:3px 8px 3px 0;">Título</th>
              <th style="text-align:left; padding:3px 8px 3px 0;">Páginas</th>
              <th style="text-align:left; padding:3px 8px 3px 0;">Dif.</th>
              <th style="text-align:left; padding:3px 0;">Conceptos</th></tr>
            ${filasTemario.map((c) => `<tr style="border-top:1px solid var(--border-color);">
              <td style="padding:5px 8px 5px 0; font-family:monospace;">${esc(c.capitulo || '')}</td>
              <td style="padding:5px 8px 5px 0;">${esc(c.titulo || '')}</td>
              <td style="padding:5px 8px 5px 0; font-family:monospace; color:var(--text-muted);">
                ${esc(c.paginas || '')}${c.paginas_aproximadas ? '~' : ''}</td>
              <td style="padding:5px 8px 5px 0;">${'●'.repeat(c.dificultad || 0)}</td>
              <td style="padding:5px 0; color:var(--text-muted);">${esc((c.conceptos || []).join(', '))}</td>
            </tr>`).join('')}
          </table></div>` : '')}

        ${bloque('Rutas de lectura', rutas.length ? rutas.map((r) => `
          <div style="font-size:12px; margin-bottom:4px;">
            <b>${esc(r.objetivo || '')}</b> —
            capítulos ${esc((r.capitulos || []).join(', '))}
            ${(r.saltar || []).length ? `<span style="color:var(--text-muted);">, saltando ${esc(r.saltar.join(', '))}</span>` : ''}
            ${r.horas_estimadas ? `<span style="color:var(--text-muted);"> · ~${r.horas_estimadas} h</span>` : ''}
          </div>`).join('') : '')}

        ${bloque('Sobre qué se puede practicar', ejercicios.length ? ejercicios.map((e) => `
          <div style="font-size:12px; margin-bottom:5px;">
            <b>${esc(e.concepto || '')}</b>
            <span style="font-size:10px; padding:1px 6px; border-radius:3px;
              background:rgba(137,180,250,0.15); color:var(--accent-blue);">${esc(e.tipo || '')}</span>
            ${e.apoyado_en ? `<span style="color:var(--text-muted); font-size:11px;"> · ${esc(e.apoyado_en)}</span>` : ''}
            ${e.error_que_destapa ? `<div style="color:var(--text-muted); font-size:11px; margin-left:4px;">
              destapa: ${esc(e.error_que_destapa)}</div>` : ''}
          </div>`).join('') : '')}

        ${bloque('Notación', notacion.length ? `<div style="font-size:12px;">
          ${notacion.map((n) => `<span style="margin-right:12px;">
            <code>${esc(n.simbolo || '')}</code> ${esc(n.significa || '')}
            ${n.cuidado ? `<span style="color:var(--accent-yellow);" title="${esc(n.cuidado)}"> ⚠</span>` : ''}
          </span>`).join('')}</div>` : '')}

        ${bloque('Lo que NO cubre', lagunas.length ? `<ul style="margin:0; padding-left:18px; font-size:12px;">
          ${lagunas.map((l) => `<li>${esc(nombrar(l))}${l.por_que_importa ? `<span style="color:var(--text-muted);"> — ${esc(l.por_que_importa)}</span>` : ''}</li>`).join('')}
        </ul>` : '')}
      </div>`;
  }

  function nombrar(x) {
    if (typeof x === 'string') return x;
    if (x && typeof x === 'object') {
      for (const k of ['tema', 'nombre', 'concepto', 'titulo', 'que']) {
        if (typeof x[k] === 'string' && x[k].trim()) {
          const matiz = x.gravedad || x.como_de_necesario;
          return typeof matiz === 'string' ? `${x[k]} (${matiz})` : x[k];
        }
      }
    }
    return String(x);
  }

  // ------------------------------------------------------------------
  // Historial
  // ------------------------------------------------------------------

  async function verEjecucion(eid) {
    const vista = $('flujo-ejecucion');
    $('flujo-editor').style.display = 'none';
    vista.style.display = '';
    vista.innerHTML = '<div style="color:var(--text-muted); padding:12px;">Cargando…</div>';
    try {
      const e = await prigFetchJson(`/api/flujos/ejecucion/${encodeURIComponent(eid)}`);
      vista.innerHTML = `
        <div style="padding:9px 0 12px; border-bottom:1px solid var(--border-color); margin-bottom:10px;">
          <b>${esc(e.flujo_nombre || '')}</b>
          <span style="color:var(--text-muted); font-size:11px;"> · ${esc((e.cuando || '').slice(0, 16).replace('T', ' '))}
            · ${e.segundos}s</span>
          <div style="color:var(--text-muted); font-size:11px; margin-top:3px;">
            Entrada: ${esc(e.entrada)}</div>
        </div>
        ${(e.pasos || []).map((p, i) => `
          <div style="border:1px solid var(--border-color); border-radius:7px; margin-bottom:9px; overflow:hidden;">
            <div style="padding:7px 11px; background:rgba(0,0,0,0.18); display:flex; gap:9px;
              align-items:center; flex-wrap:wrap;">
              <b style="font-size:12px;">${i + 1}. ${esc(p.nombre)}</b>
              <code style="font-size:10px; color:var(--accent-purple);">${esc(p.modelo)}</code>
              <span style="font-size:10px; color:var(--text-muted);">${p.segundos}s</span>
              ${p.vuelta ? `<span style="font-size:10px; color:var(--accent-yellow);">reintento ${p.vuelta}</span>` : ''}
              <span style="flex:1"></span>
              <button class="ver-prompt tool-btn" data-i="${i}" style="font-size:10px; padding:2px 8px;">
                ver lo que leyó</button>
            </div>
            <div class="prompt-${i}" style="display:none; padding:9px 12px; font-size:11px;
              font-family:monospace; white-space:pre-wrap; color:var(--text-muted);
              background:rgba(0,0,0,0.25); border-bottom:1px solid var(--border-color);">${esc(p.prompt)}</div>
            <div style="padding:9px 12px; font-size:12px; white-space:pre-wrap;">${esc(p.salida)}</div>
          </div>`).join('')}`;
      vista.querySelectorAll('.ver-prompt').forEach((b) => {
        b.addEventListener('click', () => {
          const d = vista.querySelector(`.prompt-${b.dataset.i}`);
          d.style.display = d.style.display === 'none' ? 'block' : 'none';
        });
      });
    } catch (err) {
      vista.innerHTML = `<div style="color:var(--accent-red); padding:12px;">${esc(err.message)}</div>`;
    }
  }

  // ------------------------------------------------------------------

  function avisar(texto, color) {
    const caja = $('flujo-plan');
    if (!caja) return;
    const antes = caja.innerHTML;
    caja.innerHTML = `<div style="padding:6px 10px; color:${color};">${esc(texto)}</div>`;
    setTimeout(() => { caja.innerHTML = antes; revisarFlujo(); }, 1800);
  }

  function esc(t) {
    const d = document.createElement('div');
    d.textContent = t == null ? '' : String(t);
    return d.innerHTML;
  }

  function init() {
    const n = $('btn-flujo-nuevo');
    if (n) n.addEventListener('click', nuevoFlujo);
    const g = $('btn-flujo-guardar');
    if (g) g.addEventListener('click', guardar);
    const e = $('btn-flujo-ejecutar');
    if (e) e.addEventListener('click', () => (ejecutando ? cancelar && cancelar() : ejecutar()));
    const btnModelos = $('btn-flujo-modelos');
    if (btnModelos) btnModelos.addEventListener('click', abrirModelos);
    const nom = $('flujo-nombre');
    if (nom) nom.addEventListener('input', () => { if (flujoActual) flujoActual.nombre = nom.value; });

    document.addEventListener('keydown', (ev) => {
      const modal = $('modal-flujos');
      if (ev.key === 'Escape' && modal && modal.style.display === 'flex' && !ejecutando) {
        modal.style.display = 'none';
      }
    });
  }

  return { abrir, init, nuevoFlujo, abrirModelos, cargarCatalogo: recargarCatalogo };
})();

document.addEventListener('DOMContentLoaded', () => Flujos.init());
window.Flujos = Flujos;
