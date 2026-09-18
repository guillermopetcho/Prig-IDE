/*
 * Explorador de libros con sondeo previo.
 *
 * Dos cosas que hace y que un selector de archivos corriente no:
 *
 *   · NAVEGA MOSTRANDO CUÁNTOS LIBROS HAY EN CADA CARPETA, para no entrar a
 *     ciegas en veinte carpetas buscando dónde los dejaste.
 *   · SONDEA ANTES DE EXTRAER. Un PDF escaneado no tiene texto que sacar y
 *     ningún modelo lo arregla; un libro con un cuarto de páginas de código
 *     necesita que la extracción pida el lenguaje; uno de mil páginas conviene
 *     partirlo. Todo eso se mide en menos de un segundo por archivo, y saberlo
 *     antes ahorra horas de GPU gastadas en el ajuste equivocado.
 */

const ExploradorLibros = (() => {
  const $ = (id) => document.getElementById(id);

  let rutaActual = null;
  let seleccion = new Set();
  let sondeos = {};        // ruta -> resultado
  let sondeando = false;
  let cancelar = null;

  const CAMPOS = {
    math: '∑ Matemáticas', physics: '⚛ Física', cpp: '⚙ C++',
    python: '🐍 Python', machine_learning: '📈 Machine Learning',
    deep_learning: '🧠 Deep Learning',
  };

  // ------------------------------------------------------------------

  async function abrir() {
    const modal = $('modal-explorador');
    if (!modal) return;
    modal.style.display = 'flex';
    mostrarProgreso(false);
    if (!rutaActual) {
      try {
        const r = await prigFetchJson('/api/explorador/atajos');
        pintarAtajos(r.atajos || []);
        if (r.atajos && r.atajos.length) await navegar(r.atajos[0].ruta);
      } catch (e) { pintarError(e.message); }
    }
  }

  function pintarAtajos(atajos) {
    const caja = $('exp-atajos');
    if (!caja) return;
    caja.innerHTML = atajos.map((a) => `
      <button class="exp-atajo" data-ruta="${esc(a.ruta)}" title="${esc(a.ruta)}"
        style="display:block; width:100%; text-align:left; padding:6px 9px; margin-bottom:2px;
          background:transparent; border:none; border-radius:5px; color:var(--text-muted);
          cursor:pointer; font-size:12px;">
        <i class="fa-regular fa-folder"></i> ${esc(a.nombre)}</button>`).join('');
    caja.querySelectorAll('.exp-atajo').forEach((b) =>
      b.addEventListener('click', () => navegar(b.dataset.ruta)));
  }

  async function navegar(ruta, recursivo = false) {
    const lista = $('exp-lista');
    lista.innerHTML = '<div style="padding:16px; color:var(--text-muted);">Leyendo…</div>';
    try {
      const d = await prigFetchJson(
        `/api/explorador/listar?ruta=${encodeURIComponent(ruta)}&recursivo=${recursivo}`);
      rutaActual = d.ruta;
      pintarMigas(d);
      pintarContenido(d);
    } catch (e) { pintarError(e.message); }
  }

  function pintarMigas(d) {
    const caja = $('exp-migas');
    if (!caja) return;
    caja.innerHTML = (d.migas || []).map((m, i, todas) => `
      <span><button class="exp-miga" data-ruta="${esc(m.ruta)}"
        style="background:none; border:none; color:${i === todas.length - 1 ? '#fff' : 'var(--accent-blue)'};
          cursor:pointer; font-size:12px; padding:2px 3px;">${esc(m.nombre)}</button
      >${i < todas.length - 1 ? '<span style="color:var(--text-muted);">/</span>' : ''}</span>`).join('');
    caja.querySelectorAll('.exp-miga').forEach((b) =>
      b.addEventListener('click', () => navegar(b.dataset.ruta)));
  }

  function pintarContenido(d) {
    const lista = $('exp-lista');
    const carpetas = d.carpetas || [];
    const libros = d.libros || [];

    lista.innerHTML = `
      ${carpetas.map((c) => `
        <div class="exp-carpeta" data-ruta="${esc(c.ruta)}"
          style="display:flex; align-items:center; gap:9px; padding:7px 10px; cursor:pointer;
            border-radius:5px; font-size:13px;">
          <i class="fa-solid fa-folder" style="color:var(--accent-yellow);"></i>
          <span style="flex:1;">${esc(c.nombre)}</span>
          ${c.libros_dentro ? `<span style="font-size:10.5px; color:var(--text-muted);">
            ${c.libros_dentro} libro${c.libros_dentro === 1 ? '' : 's'}</span>` : ''}
        </div>`).join('')}
      ${libros.length ? `<div style="margin:10px 0 4px; font-size:10px; letter-spacing:.06em;
        text-transform:uppercase; color:var(--text-muted);">
        ${libros.length} libro${libros.length === 1 ? '' : 's'}</div>` : ''}
      ${libros.map((l) => filaLibro(l)).join('')}
      ${!carpetas.length && !libros.length
        ? '<div style="padding:16px; color:var(--text-muted);">Esta carpeta no tiene libros.</div>'
        : ''}`;

    lista.querySelectorAll('.exp-carpeta').forEach((el) =>
      el.addEventListener('click', () => navegar(el.dataset.ruta)));
    enlazarLibros(lista);
    actualizarBarra();
  }

  function filaLibro(l) {
    const s = sondeos[l.ruta];
    const marcado = seleccion.has(l.ruta);
    return `
      <div class="exp-libro" data-ruta="${esc(l.ruta)}"
        style="border-radius:5px; padding:6px 10px; margin-bottom:2px;
          background:${marcado ? 'rgba(203,166,247,0.08)' : 'transparent'};">
        <div style="display:flex; align-items:center; gap:9px; font-size:13px;">
          <input type="checkbox" class="exp-check" ${marcado ? 'checked' : ''}
            style="accent-color:var(--accent-purple); cursor:pointer;">
          <i class="fa-regular fa-file-lines" style="color:var(--accent-blue);"></i>
          <span style="flex:1; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;"
            title="${esc(l.ruta)}">${esc(l.nombre)}</span>
          ${l.subcarpeta ? `<span style="font-size:10px; color:var(--text-muted);">${esc(l.subcarpeta)}</span>` : ''}
          <span style="font-size:10.5px; color:var(--text-muted); white-space:nowrap;">
            ${esc(l.tipo)} · ${l.mb} MB</span>
          <button class="tool-btn exp-btn-extraer-fila" data-ruta="${esc(l.ruta)}"
            title="Extraer e indexar este libro directamente en la biblioteca"
            style="font-size:11px; padding:2px 8px; margin-left:6px; background:rgba(166,227,161,0.18);
              color:var(--accent-green); border:1px solid rgba(166,227,161,0.35); border-radius:4px; cursor:pointer;">
            <i class="fa-solid fa-file-import"></i> Extraer
          </button>
        </div>
        ${s ? resumenSondeo(s) : ''}
      </div>`;
  }

  function resumenSondeo(s) {
    const m = s.medicion || {};
    const r = s.recomendacion || {};
    const c = s.clasificacion || {};
    if (m.error || (r.bloqueos || []).length) {
      return `<div style="margin:5px 0 2px 26px; font-size:11px; color:var(--accent-red);">
        ${esc(m.error || r.bloqueos.join(' '))}</div>`;
    }
    const etiqueta = (texto, color) => `<span style="font-size:10px; padding:1px 6px;
      border-radius:3px; background:${color}22; color:${color}; white-space:nowrap;">${texto}</span>`;

    const mat = Math.round((m.fraccion_paginas_matematicas || 0) * 100);
    const cod = Math.round((m.fraccion_paginas_codigo || 0) * 100);
    return `
      <div style="margin:6px 0 3px 26px; display:flex; gap:6px; flex-wrap:wrap; align-items:center;">
        ${c.campo ? etiqueta(esc(CAMPOS[c.campo] || c.campo), 'var(--accent-purple)') : ''}
        ${c.nivel ? etiqueta(esc(c.nivel), 'var(--accent-blue)') : ''}
        ${etiqueta(`${m.paginas} pág`, 'var(--text-muted)')}
        ${mat ? etiqueta(`${mat}% matemáticas`, 'var(--accent-green)') : ''}
        ${cod ? etiqueta(`${cod}% código`, 'var(--accent-yellow)') : ''}
        ${m.imagenes_por_pagina >= 0.5 ? etiqueta(`${m.imagenes_por_pagina} img/pág`, 'var(--accent-blue)') : ''}
        ${m.tiene_indice ? etiqueta(`índice de ${m.entradas_indice}`, 'var(--text-muted)')
                         : etiqueta('sin índice', 'var(--accent-yellow)')}
        ${m.idioma && m.idioma !== '?' ? etiqueta(esc(m.idioma), 'var(--text-muted)') : ''}
      </div>
      ${c.de_que_trata ? `<div style="margin-left:26px; font-size:11.5px; color:#fff;">
        ${esc(c.de_que_trata)}</div>` : ''}
      <div style="margin-left:26px; font-size:11px; color:var(--text-muted);">
        ~${(r.coste || {}).fragmentos || 0} fragmentos ·
        ${(r.coste || {}).horas_en_local || 0} h en local ·
        ${(r.coste || {}).minutos_en_dos_T4 || 0} min en dos T4
      </div>
      ${(r.avisos || []).map((a) => `<div style="margin-left:26px; font-size:11px;
        color:var(--accent-yellow);">· ${esc(a)}</div>`).join('')}`;
  }

  function enlazarLibros(caja) {
    caja.querySelectorAll('.exp-libro').forEach((el) => {
      const ruta = el.dataset.ruta;
      const check = el.querySelector('.exp-check');
      const btnFila = el.querySelector('.exp-btn-extraer-fila');

      if (btnFila) {
        btnFila.addEventListener('click', (ev) => {
          ev.stopPropagation();
          extraerLibros([ruta]);
        });
      }

      const alternar = () => {
        if (seleccion.has(ruta)) seleccion.delete(ruta); else seleccion.add(ruta);
        check.checked = seleccion.has(ruta);
        el.style.background = seleccion.has(ruta) ? 'rgba(203,166,247,0.08)' : 'transparent';
        actualizarBarra();
      };
      check.addEventListener('click', (ev) => { ev.stopPropagation(); alternar(); });
      el.addEventListener('click', (ev) => {
        if (ev.target !== check && (!btnFila || !btnFila.contains(ev.target))) alternar();
      });
    });
  }

  function pintarError(mensaje) {
    $('exp-lista').innerHTML =
      `<div style="padding:16px; color:var(--accent-red); font-size:12px;">${esc(mensaje)}</div>`;
  }

  // ------------------------------------------------------------------
  // Búsqueda por nombre
  // ------------------------------------------------------------------

  let tempBusqueda = null;

  function buscar(texto) {
    clearTimeout(tempBusqueda);
    if (!texto.trim()) {
      if (rutaActual) navegar(rutaActual);
      return;
    }
    tempBusqueda = setTimeout(async () => {
      const lista = $('exp-lista');
      lista.innerHTML = '<div style="padding:16px; color:var(--text-muted);">Buscando…</div>';
      try {
        const d = await prigFetchJson(
          `/api/explorador/buscar?q=${encodeURIComponent(texto)}` +
          (rutaActual ? `&desde=${encodeURIComponent(rutaActual)}` : ''));
        const res = d.resultados || [];
        lista.innerHTML = res.length
          ? `<div style="margin:4px 0 6px; font-size:10px; letter-spacing:.06em;
               text-transform:uppercase; color:var(--text-muted);">
               ${res.length} resultado${res.length === 1 ? '' : 's'}</div>`
            + res.map((l) => filaLibro({ ...l, subcarpeta: acortar(l.carpeta) })).join('')
          : '<div style="padding:16px; color:var(--text-muted);">Nada con ese nombre.</div>';
        enlazarLibros(lista);
        actualizarBarra();
      } catch (e) { pintarError(e.message); }
    }, 350);
  }

  function acortar(ruta) {
    const casa = '/home/';
    const partes = String(ruta || '').split('/');
    return partes.slice(-2).join('/') || ruta;
  }

  // ------------------------------------------------------------------
  // Barra de progreso interactiva
  // ------------------------------------------------------------------

  function mostrarProgreso(visible, etiqueta = '', porcentaje = 0, detalle = '', contador = '') {
    const cont = $('exp-progreso-contenedor');
    if (!cont) return;
    cont.style.display = visible ? 'block' : 'none';
    if (!visible) return;

    const barra = $('exp-progreso-barra');
    const eti = $('exp-progreso-etiqueta');
    const pct = $('exp-progreso-porcentaje');
    const det = $('exp-progreso-detalle');
    const cnt = $('exp-progreso-contador');

    const pctNum = Math.max(0, Math.min(100, Math.round(porcentaje)));
    if (barra) barra.style.width = `${pctNum}%`;
    if (pct) pct.textContent = `${pctNum}%`;
    if (eti && etiqueta) eti.innerHTML = etiqueta;
    if (det && detalle) det.textContent = detalle;
    if (cnt) cnt.textContent = contador || '';
  }

  // ------------------------------------------------------------------
  // Sondeo
  // ------------------------------------------------------------------

  async function sondear(todaLaCarpeta) {
    if (sondeando) { if (cancelar) cancelar(); return; }
    const cuerpo = todaLaCarpeta
      ? { carpeta: rutaActual, con_modelo: $('exp-con-modelo').checked }
      : { rutas: [...seleccion], con_modelo: $('exp-con-modelo').checked };
    if (!todaLaCarpeta && !seleccion.size) return;

    sondeando = true;
    const btn = $('btn-exp-sondear');
    const estado = $('exp-estado');
    btn.innerHTML = '<i class="fa-solid fa-stop"></i> Detener';

    mostrarProgreso(true, '<i class="fa-solid fa-spinner fa-spin" style="color:var(--accent-blue);"></i> Sondeando libros...', 0, 'Analizando archivos...');

    const control = new AbortController();
    cancelar = () => {
      control.abort();
      mostrarProgreso(false);
    };
    try {
      const res = await fetch('/api/sondeo', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        signal: control.signal, body: JSON.stringify(cuerpo),
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
          if (ev.tipo === 'sondeando') {
            const pct = Math.round(((ev.n - 1) / (ev.total || 1)) * 100);
            mostrarProgreso(
              true,
              `<i class="fa-solid fa-spinner fa-spin" style="color:var(--accent-blue);"></i> Sondeando (${ev.n}/${ev.total}): ${esc(ev.nombre)}`,
              pct,
              'Midiendo páginas, matemáticas y código...',
              `${ev.n} de ${ev.total}`
            );
            estado.textContent = `${ev.n}/${ev.total} · ${ev.nombre}`;
          } else if (ev.tipo === 'resultado') {
            sondeos[ev.medicion.ruta] = ev;
            refrescarFila(ev.medicion.ruta);
            const pct = Math.round((ev.n / (ev.total || 1)) * 100);
            mostrarProgreso(
              true,
              `<i class="fa-solid fa-spinner fa-spin" style="color:var(--accent-blue);"></i> Sondeando (${ev.n}/${ev.total})`,
              pct,
              `✔ ${esc(ev.nombre || '')}: medido con éxito`,
              `${ev.n} de ${ev.total}`
            );
          } else if (ev.tipo === 'fallo') {
            sondeos[ev.ruta] = { medicion: { ruta: ev.ruta, error: ev.mensaje } };
            refrescarFila(ev.ruta);
          } else if (ev.tipo === 'fin') {
            mostrarProgreso(
              true,
              '<i class="fa-solid fa-circle-check" style="color:var(--accent-green);"></i> Sondeo terminado',
              100,
              'Medición completada. Ya puedes extraer los libros seleccionados.'
            );
            estado.textContent = 'Sondeo terminado.';
            setTimeout(() => { mostrarProgreso(false); }, 4000);
          }
        }
      }
    } catch (e) {
      estado.textContent = e.name === 'AbortError' ? 'Detenido.' : e.message;
      mostrarProgreso(false);
    } finally {
      sondeando = false; cancelar = null;
      btn.innerHTML = '<i class="fa-solid fa-gauge-high"></i> Sondear';
      actualizarBarra();
    }
  }

  function refrescarFila(ruta) {
    const fila = document.querySelector(`.exp-libro[data-ruta="${cssEscape(ruta)}"]`);
    if (!fila) return;
    const viejo = fila.querySelector('.exp-resumen');
    if (viejo) viejo.remove();
    const div = document.createElement('div');
    div.className = 'exp-resumen';
    div.innerHTML = resumenSondeo(sondeos[ruta]);
    fila.appendChild(div);
  }

  function cssEscape(s) {
    return String(s).replace(/["\\]/g, '\\$&');
  }

  // ------------------------------------------------------------------
  // Barra inferior
  // ------------------------------------------------------------------

  function actualizarBarra() {
    const n = seleccion.size;
    const sondeados = [...seleccion].filter((r) => sondeos[r] &&
      !(sondeos[r].medicion || {}).error).length;
    const extraibles = [...seleccion].filter((r) =>
      sondeos[r] && (sondeos[r].recomendacion || {}).se_puede_extraer).length;

    $('exp-resumen-sel').innerHTML = n
      ? `<b>${n}</b> seleccionado${n === 1 ? '' : 's'}` +
        (sondeados ? ` · ${sondeados} sondeado${sondeados === 1 ? '' : 's'}` : '') +
        (sondeados && extraibles < sondeados
          ? `<span style="color:var(--accent-yellow);"> · ${sondeados - extraibles} no se pueden extraer</span>`
          : '')
      : '<span style="color:var(--text-muted);">Nada seleccionado</span>';

    $('btn-exp-sondear').disabled = !n && !rutaActual;

    const btnExtraer = $('btn-exp-extraer');
    if (btnExtraer) {
      btnExtraer.disabled = !n;
      btnExtraer.innerHTML = n
        ? `<i class="fa-solid fa-file-import"></i> Extraer ${n} ${n === 1 ? 'libro' : 'libros'} a Biblioteca`
        : '<i class="fa-solid fa-file-import"></i> Extraer libro a Biblioteca';
    }

    const btnPrep = $('btn-exp-preparar');
    if (btnPrep) {
      btnPrep.disabled = !n;
      btnPrep.innerHTML = n
        ? `<i class="fa-solid fa-box-open"></i> Preparar ${n} para extraer`
        : '<i class="fa-solid fa-box-open"></i> Preparar para extraer';
    }
  }

  // ------------------------------------------------------------------
  // Extracción directa a la Biblioteca
  // ------------------------------------------------------------------

  async function extraerLibros(rutasPersonalizadas = null) {
    let elegidos = rutasPersonalizadas || [...seleccion];
    if (!elegidos.length) {
      const estado = $('exp-estado');
      if (estado) {
        estado.innerHTML = '<span style="color:var(--accent-yellow);"><i class="fa-solid fa-triangle-exclamation"></i> Selecciona uno o más libros marcando su casilla para extraerlos.</span>';
      }
      return;
    }

    const total = elegidos.length;
    mostrarProgreso(true, '<i class="fa-solid fa-spinner fa-spin" style="color:var(--accent-blue);"></i> Extrayendo libro...', 0, 'Iniciando proceso de extracción...', `0 de ${total}`);

    const btnExtraer = $('btn-exp-extraer');
    const btnPrep = $('btn-exp-preparar');
    const btnSond = $('btn-exp-sondear');
    if (btnExtraer) btnExtraer.disabled = true;
    if (btnPrep) btnPrep.disabled = true;
    if (btnSond) btnSond.disabled = true;

    const estado = $('exp-estado');
    let importados = 0;
    const fallos = [];

    for (let i = 0; i < total; i++) {
      const ruta = elegidos[i];
      const nombre = ruta.split('/').pop() || ruta;
      const pctInicio = Math.round((i / total) * 100);

      mostrarProgreso(
        true,
        `<i class="fa-solid fa-spinner fa-spin" style="color:var(--accent-blue);"></i> Extrayendo (${i + 1}/${total}): ${esc(nombre)}`,
        pctInicio + Math.round(50 / total),
        'Leyendo páginas, detectando estructura y generando fragmentos...',
        `${i + 1} de ${total}`
      );
      if (estado) estado.textContent = `Extrayendo ${nombre}…`;

      try {
        // 1. Importar e indexar en la biblioteca (~/.prig_books y catalog.db)
        const res = await fetch('/api/books/import', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ path: ruta }),
        });

        if (!res.ok) {
          const detalleErr = await prigErrorDetail(res);
          throw new Error(detalleErr);
        }

        const dataImport = await res.json();

        // 2. Trocear y preparar también para job/dataset de extracción si es posible
        try {
          const s = sondeos[ruta];
          await fetch('/api/job/prepare-stream', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              libros: [{
                path: ruta,
                domain: (s && s.clasificacion && s.clasificacion.campo) || null,
                ajustes: (s && s.recomendacion && s.recomendacion.ajustes_extraccion) || { max_chunk_tokens: 500 },
              }],
            }),
          });
        } catch (_) {}

        importados++;
        const pctFin = Math.round(((i + 1) / total) * 100);
        mostrarProgreso(
          true,
          `<i class="fa-solid fa-spinner fa-spin" style="color:var(--accent-blue);"></i> Extrayendo (${i + 1}/${total}): ${esc(nombre)}`,
          pctFin,
          `✔ ${esc(nombre)} extraído e indexado (${dataImport.chunks_count || 'OK'} fragmentos)`,
          `${i + 1} de ${total}`
        );
      } catch (err) {
        fallos.push({ nombre, error: err.message });
        const pctFin = Math.round(((i + 1) / total) * 100);
        mostrarProgreso(
          true,
          `<i class="fa-solid fa-triangle-exclamation" style="color:var(--accent-yellow);"></i> Error en (${i + 1}/${total})`,
          pctFin,
          `⚠ ${esc(nombre)}: ${err.message}`,
          `${i + 1} de ${total}`
        );
      }
    }

    // Al finalizar todos
    if (importados > 0) {
      mostrarProgreso(
        true,
        '<i class="fa-solid fa-circle-check" style="color:var(--accent-green);"></i> Extracción completada',
        100,
        `${importados} libro(s) extraído(s) y agregado(s) a tu Biblioteca con éxito.`,
        `${importados} de ${total}`
      );
      if (estado) {
        estado.innerHTML = `<span style="color:var(--accent-green); font-weight:bold;"><i class="fa-solid fa-check"></i> ${importados} libro(s) en Biblioteca</span>`;
      }

      // Refrescar la lista de libros en la ventana Biblioteca de inmediato
      if (window.bookLibraryMgr && typeof window.bookLibraryMgr.loadBooks === 'function') {
        try {
          window.bookLibraryMgr.loadBooks();
        } catch (e) {
          console.warn('Error refrescando bookLibraryMgr:', e);
        }
      }

      // Auto-ocultar la barra de progreso a los 6 segundos
      setTimeout(() => {
        mostrarProgreso(false);
      }, 6000);
    } else {
      mostrarProgreso(
        true,
        '<i class="fa-solid fa-circle-xmark" style="color:var(--accent-red);"></i> Fallo en la extracción',
        100,
        fallos.map((f) => `${f.nombre}: ${f.error}`).join('; ') || 'No se pudo extraer ningún libro.',
        `0 de ${total}`
      );
      if (estado) {
        estado.innerHTML = '<span style="color:var(--accent-red);">Error al extraer libro(s)</span>';
      }
    }

    if (btnExtraer) btnExtraer.disabled = false;
    if (btnPrep) btnPrep.disabled = false;
    if (btnSond) btnSond.disabled = false;
    actualizarBarra();
  }

  // ------------------------------------------------------------------
  // Preparar trabajo de extracción (Kaggle / Dataset)
  // ------------------------------------------------------------------

  async function prepararTrabajo() {
    const elegidos = [...seleccion].map((r) => {
      const s = sondeos[r];
      return {
        path: r,
        domain: (s && s.clasificacion && s.clasificacion.campo) || null,
        ajustes: (s && s.recomendacion && s.recomendacion.ajustes_extraccion) || { max_chunk_tokens: 500 },
      };
    });

    if (!elegidos.length) {
      const estado = $('exp-estado');
      if (estado) {
        estado.innerHTML = '<span style="color:var(--accent-yellow);"><i class="fa-solid fa-triangle-exclamation"></i> Selecciona uno o más libros para preparar la extracción.</span>';
      }
      return;
    }

    const total = elegidos.length;
    mostrarProgreso(true, '<i class="fa-solid fa-spinner fa-spin" style="color:var(--accent-blue);"></i> Preparando para extraer...', 0, 'Iniciando troceado semántico...', `0 de ${total}`);

    const estado = $('exp-estado');
    const btn = $('btn-exp-preparar');
    const btnExtraer = $('btn-exp-extraer');
    if (btn) btn.disabled = true;
    if (btnExtraer) btnExtraer.disabled = true;
    if (estado) estado.textContent = 'Preparando…';

    let manifest = null;
    try {
      const res = await fetch('/api/job/prepare-stream', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ libros: elegidos }),
      });
      if (!res.ok) throw new Error(await prigErrorDetail(res));

      const lector = res.body.getReader();
      const dec = new TextDecoder();
      let resto = '';
      const hechos = [];
      const fallos = [];
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
          if (ev.tipo === 'libro') {
            const pct = Math.round(((ev.n - 1) / (ev.total || total)) * 100);
            mostrarProgreso(
              true,
              `<i class="fa-solid fa-spinner fa-spin" style="color:var(--accent-blue);"></i> Troceando (${ev.n}/${ev.total}): ${esc(ev.nombre)}`,
              pct,
              'Generando fragmentos semánticos deterministas...',
              `${ev.n} de ${ev.total}`
            );
            if (estado) estado.textContent = `${ev.n}/${ev.total} · troceando ${ev.nombre}`;
          } else if (ev.tipo === 'listo') {
            hechos.push(ev);
            const pct = Math.round((ev.n / (ev.total || total)) * 100);
            mostrarProgreso(
              true,
              `<i class="fa-solid fa-spinner fa-spin" style="color:var(--accent-blue);"></i> Troceando...`,
              pct,
              `✔ ${esc(ev.nombre)}: ${ev.fragmentos} fragmentos`,
              `${ev.n} de ${ev.total || total}`
            );
            if (estado) {
              estado.innerHTML = `<span style="color:var(--accent-green);">${esc(ev.nombre)}: ${ev.fragmentos} fragmentos</span>`;
            }
          } else if (ev.tipo === 'fallo') {
            fallos.push(ev);
          } else if (ev.tipo === 'repetido') {
            fallos.push({ nombre: ev.nombre, motivo: `repetido de ${ev.ya_como}` });
          } else if (ev.tipo === 'error') {
            throw new Error(ev.mensaje);
          } else if (ev.tipo === 'fin') {
            manifest = ev.manifest;
          }
        }
      }

      mostrarProgreso(
        true,
        '<i class="fa-solid fa-circle-check" style="color:var(--accent-green);"></i> Preparación completada',
        100,
        `${manifest?.total_books || hechos.length} libro(s) procesado(s) (${manifest?.total_chunks || 0} fragmentos totales).`,
        `${hechos.length} listos`
      );

      // Asegurar que también se indexen en la biblioteca
      for (const el of elegidos) {
        try {
          await fetch('/api/books/import', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ path: el.path }),
          });
        } catch (_) {}
      }
      if (window.bookLibraryMgr && typeof window.bookLibraryMgr.loadBooks === 'function') {
        window.bookLibraryMgr.loadBooks();
      }

      pintarResultado(manifest, fallos);
      setTimeout(() => { mostrarProgreso(false); }, 6000);
    } catch (e) {
      mostrarProgreso(
        true,
        '<i class="fa-solid fa-circle-xmark" style="color:var(--accent-red);"></i> Error preparando extracción',
        100,
        e.message
      );
      if (estado) estado.innerHTML = `<span style="color:var(--accent-red);">${esc(e.message)}</span>`;
    } finally {
      if (btn) btn.disabled = false;
      if (btnExtraer) btnExtraer.disabled = false;
      actualizarBarra();
    }
  }

  function pintarResultado(m, fallos) {
    const estado = $('exp-estado');
    if (!m) { estado.textContent = 'No se preparó nada.'; return; }
    const rechazados = (m.rechazados || []).concat(m.failed || []).concat(fallos || []);
    estado.innerHTML = `
      <div style="color:var(--accent-green);">
        <b>${m.total_books} libros · ${m.total_chunks} fragmentos · ${m.estimated_mb} MB</b></div>
      <div style="color:var(--text-muted); font-size:10.5px; word-break:break-all;">
        ${esc(m.output_dir || '')}</div>
      ${rechazados.length ? `<div style="color:var(--accent-yellow); font-size:10.5px; margin-top:3px;">
        ${rechazados.slice(0, 3).map((r) =>
          `${esc(r.nombre || r.ruta || '')}: ${esc(r.motivo || '')}`).join('<br>')}
        ${rechazados.length > 3 ? `<br>y ${rechazados.length - 3} más` : ''}</div>` : ''}`;
  }

  // ------------------------------------------------------------------

  function esc(t) {
    const d = document.createElement('div');
    d.textContent = t == null ? '' : String(t);
    return d.innerHTML;
  }

  function init() {
    const b = $('btn-exp-sondear');
    if (b) b.addEventListener('click', () => sondear(!seleccion.size));
    const p = $('btn-exp-preparar');
    if (p) p.addEventListener('click', prepararTrabajo);
    const ex = $('btn-exp-extraer');
    if (ex) ex.addEventListener('click', () => extraerLibros());
    const buscador = $('exp-buscar');
    if (buscador) buscador.addEventListener('input', () => buscar(buscador.value));
    const hondo = $('exp-recursivo');
    if (hondo) hondo.addEventListener('change', () => navegar(rutaActual, hondo.checked));
    const limpiar = $('btn-exp-limpiar');
    if (limpiar) limpiar.addEventListener('click', () => {
      seleccion.clear();
      mostrarProgreso(false);
      if (rutaActual) navegar(rutaActual, $('exp-recursivo').checked);
    });

    document.addEventListener('keydown', (ev) => {
      const modal = $('modal-explorador');
      if (ev.key === 'Escape' && modal && modal.style.display === 'flex' && !sondeando) {
        modal.style.display = 'none';
      }
    });
  }

  return { abrir, init };
})();

document.addEventListener('DOMContentLoaded', () => ExploradorLibros.init());
window.ExploradorLibros = ExploradorLibros;
