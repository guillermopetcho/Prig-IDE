/*
 * Base de conocimiento: paquetes de libros analizados con GPU externa.
 *
 * Un .prigpack es el resultado de haber leído un libro entero con un modelo
 * grande: afirmaciones clasificadas, con su cita textual y su página. Este panel
 * los mete en la base local, une los conceptos entre libros y enseña, libro a
 * libro, qué se guardó de cada uno — que es lo único que distingue una biblioteca
 * completa de una a la que le faltan cosas sin avisar.
 */

const BaseConocimiento = (() => {
  let estado = null;
  let cargando = false;

  const $ = (id) => document.getElementById(id);

  const DOMINIOS = {
    math: { icono: '∑', nombre: 'Matemáticas', color: '#89b4fa' },
    physics: { icono: '⚛', nombre: 'Física', color: '#94e2d5' },
    cpp: { icono: '⚙', nombre: 'C++', color: '#f38ba8' },
    python: { icono: '🐍', nombre: 'Python', color: '#f9e2af' },
    machine_learning: { icono: '📈', nombre: 'Machine Learning', color: '#a6e3a1' },
    deep_learning: { icono: '🧠', nombre: 'Deep Learning', color: '#cba6f7' },
  };

  const dominio = (d) => DOMINIOS[d] || { icono: '📘', nombre: d || 'sin campo', color: '#9399b2' };

  async function refrescar() {
    const caja = $('kb-resumen');
    if (!caja) return;
    try {
      estado = await prigFetchJson('/api/kb/status');
      pintarResumen();
    } catch (e) {
      caja.innerHTML = `<span style="color: var(--accent-red);">Base no disponible: ${escapar(e.message)}</span>`;
    }
  }

  function pintarResumen() {
    const caja = $('kb-resumen');
    const btn = $('btn-kb-importar');
    if (!caja) return;

    const pendientes = (estado.sin_importar || []).length;
    const enCarpeta = (estado.packs_en_carpeta || []).length;

    if (!enCarpeta && !estado.disponible) {
      caja.innerHTML = `<span style="color: var(--text-muted);">Sin paquetes. Deja los <code>.prigpack</code>
        en <code style="font-size:9px;">~/.prig_books/packs</code></span>`;
      if (btn) btn.style.display = 'none';
      return;
    }

    const porDominio = Object.entries(estado.libros_por_dominio || {})
      .map(([d, n]) => {
        const info = dominio(d);
        return `<span title="${info.nombre}: ${n} libro(s)" style="color:${info.color};">${info.icono} ${n}</span>`;
      }).join(' ');

    caja.innerHTML = `
      <div style="display:flex; gap:10px; flex-wrap:wrap; align-items:baseline;">
        <b style="color: var(--accent-green);">${estado.libros || 0} libros</b>
        <span>${(estado.conceptos || 0).toLocaleString()} conceptos</span>
        <span>${(estado.afirmaciones || 0).toLocaleString()} afirmaciones</span>
      </div>
      <div style="margin-top:4px; display:flex; gap:8px; flex-wrap:wrap;">
        ${porDominio}
        ${estado.puentes ? `<span title="Conceptos que aparecen en más de un campo: el tutor los usa para explicar un tema apoyándose en otro que ya conoces" style="color: var(--accent-purple);">🔗 ${estado.puentes} puentes</span>` : ''}
      </div>
      ${pendientes ? `<div style="margin-top:5px; color: var(--accent-yellow);">
          ${pendientes} paquete(s) sin importar</div>` : ''}`;

    if (btn) {
      btn.style.display = enCarpeta ? '' : 'none';
      btn.innerHTML = pendientes
        ? `<i class="fa-solid fa-download"></i> Importar ${pendientes}`
        : `<i class="fa-solid fa-rotate"></i> Reunificar`;
      btn.title = pendientes
        ? 'Importar los paquetes nuevos y unir sus conceptos con los que ya hay'
        : 'Volver a unir los conceptos y recalcular los dosieres';
    }
  }

  async function importar() {
    if (cargando) return;
    cargando = true;
    const btn = $('btn-kb-importar');
    const detalle = $('kb-detalle');
    if (btn) { btn.disabled = true; btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Importando…'; }
    if (detalle) detalle.innerHTML = '<span style="color: var(--text-muted);">Leyendo paquetes, uniendo conceptos y construyendo dosieres…</span>';
    try {
      const r = await prigFetchJson('/api/kb/import', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({}),
      });
      pintarInforme(r);
      await refrescar();
    } catch (e) {
      if (detalle) detalle.innerHTML = `<span style="color: var(--accent-red);">No se pudo importar: ${escapar(e.message)}</span>`;
    } finally {
      cargando = false;
      if (btn) btn.disabled = false;
      pintarResumen();
    }
  }

  function pintarInforme(r) {
    const detalle = $('kb-detalle');
    if (!detalle) return;
    const v = r.verificacion || {};
    const u = r.unificacion || {};
    const fallidos = (r.importacion && r.importacion.fallidos) || [];

    const filas = (v.libros || []).map((l) => {
      const info = dominio(l.dominio);
      const color = l.ok ? 'var(--accent-green)' : 'var(--accent-red)';
      return `
        <div style="padding:5px 0; border-bottom:1px solid var(--border-color);">
          <div style="display:flex; gap:6px; align-items:baseline;">
            <span style="color:${color};">${l.ok ? '✓' : '✗'}</span>
            <span style="flex:1; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;"
                  title="${escapar(l.titulo || '')}">${escapar(l.titulo || l.source_id)}</span>
            <span style="color:${info.color}; font-size:10px;" title="${info.nombre}">${info.icono}</span>
          </div>
          <div style="color: var(--text-muted); font-size:10px; margin-left:14px;">
            ${l.afirmaciones} afirmaciones · ${l.conceptos} conceptos · ${l.relaciones} relaciones
          </div>
          ${(l.fallos || []).map((f) => `<div style="color: var(--accent-red); font-size:10px; margin-left:14px;">! ${escapar(f)}</div>`).join('')}
        </div>`;
    }).join('');

    detalle.innerHTML = `
      <div style="margin-bottom:6px; color:${v.integro ? 'var(--accent-green)' : 'var(--accent-yellow)'};">
        <b>${v.libros_ok || 0}/${v.total_libros || 0} libros guardados correctamente</b>
      </div>
      <div style="color: var(--text-muted); font-size:10px; margin-bottom:6px;">
        ${u.fusionados || 0} grupos de sinónimos unidos · ${u.puentes || 0} conceptos puente ·
        ${(r.dosieres && r.dosieres.dosieres) || 0} dosieres
      </div>
      ${fallidos.length ? `<div style="color: var(--accent-red); font-size:10px; margin-bottom:6px;">
        ${fallidos.map((f) => `${escapar(f.pack)}: ${escapar(f.error)}`).join('<br>')}</div>` : ''}
      ${(v.problemas_globales || []).map((p) => `<div style="color: var(--accent-yellow); font-size:10px;">! ${escapar(p)}</div>`).join('')}
      <div style="max-height:190px; overflow:auto; margin-top:4px;">${filas}</div>`;
  }

  async function verLibros() {
    const detalle = $('kb-detalle');
    if (!detalle) return;
    detalle.innerHTML = '<span style="color: var(--text-muted);">Revisando…</span>';
    try {
      pintarInforme({ verificacion: await prigFetchJson('/api/kb/books') });
    } catch (e) {
      detalle.innerHTML = `<span style="color: var(--accent-red);">${escapar(e.message)}</span>`;
    }
  }

  async function consultar(nombre) {
    const detalle = $('kb-detalle');
    if (!detalle || !nombre.trim()) return;
    detalle.innerHTML = '<span style="color: var(--text-muted);">Buscando…</span>';
    try {
      const r = await prigFetchJson(`/api/kb/concept?nombre=${encodeURIComponent(nombre)}`);
      const d = r.dosier || {};
      const c = r.concepto || {};
      const dominios = (c.domains || []).map((x) => {
        const i = dominio(x);
        return `<span style="color:${i.color};">${i.icono} ${i.nombre}</span>`;
      }).join(' · ');
      const bloques = Object.entries(d.por_tipo || {}).map(([tipo, items]) => `
        <div style="margin-top:6px;">
          <b style="color: var(--accent-blue); font-size:10px;">${tipo}</b>
          ${items.map((a) => `
            <div style="margin:3px 0 0 6px;">
              ${escapar(a.text || '')}
              <div style="color: var(--text-muted); font-size:10px;">«${escapar((a.quote || '').slice(0, 150))}» — ${escapar(a.book || '')}, p.${a.page || '?'}</div>
            </div>`).join('')}
        </div>`).join('');
      detalle.innerHTML = `
        <div><b style="color: var(--accent-green);">${escapar(c.canonical_name || nombre)}</b>
          ${c.is_bridge ? '<span title="Aparece en varios campos" style="color: var(--accent-purple);"> 🔗 puente</span>' : ''}</div>
        <div style="font-size:10px; margin-top:2px;">${dominios}</div>
        ${(d.alias || []).length > 1 ? `<div style="color: var(--text-muted); font-size:10px; margin-top:2px;">también: ${escapar(d.alias.join(', '))}</div>` : ''}
        <div style="max-height:220px; overflow:auto;">${bloques}</div>`;
    } catch (e) {
      detalle.innerHTML = `<span style="color: var(--text-muted);">"${escapar(nombre)}" no aparece en la biblioteca.</span>`;
    }
  }

  // ------------------------------------------------------------------
  // Preparar el trabajo que se sube a la GPU externa
  // ------------------------------------------------------------------

  let librosTrabajo = [];

  async function abrirPreparador() {
    const caja = $('kb-trabajo');
    if (!caja) return;
    if (caja.dataset.abierto === '1') {
      caja.dataset.abierto = '0';
      caja.innerHTML = '';
      return;
    }
    caja.dataset.abierto = '1';
    caja.innerHTML = '<span style="color: var(--text-muted);">Leyendo la biblioteca…</span>';
    try {
      const r = await prigFetchJson('/api/job/books');
      librosTrabajo = r.libros.map((b) => ({ ...b, elegido: !b.duplicado }));
      pintarPreparador(r.dominios);
    } catch (e) {
      caja.innerHTML = `<span style="color: var(--accent-red);">${escapar(e.message)}</span>`;
    }
  }

  function pintarPreparador(dominios) {
    const caja = $('kb-trabajo');
    if (!librosTrabajo.length) {
      caja.innerHTML = '<span style="color: var(--text-muted);">No hay libros en la biblioteca todavía.</span>';
      return;
    }
    const opciones = Object.entries(dominios)
      .map(([k, v]) => `<option value="${k}">${escapar(v.nombre)}</option>`).join('');

    const filas = librosTrabajo.map((b, i) => `
      <div style="display:flex; gap:5px; align-items:center; padding:3px 0; ${b.duplicado ? 'opacity:.5;' : ''}">
        <input type="checkbox" data-libro="${i}" ${b.elegido ? 'checked' : ''}
               style="accent-color: var(--accent-purple); cursor:pointer;">
        <span style="flex:1; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; font-size:10px;"
              title="${escapar(b.path)}${b.duplicado ? '\n(copia de ' + escapar(b.duplicado_de || '') + ')' : ''}">
          ${escapar(b.name)}${b.duplicado ? ' <i>(repetido)</i>' : ''}</span>
        <select data-dominio="${i}" title="${b.revisar ? escapar(b.motivo) : 'Campo propuesto por el título'}"
          style="font-size:9px; background: var(--bg-panel); color:${b.revisar ? 'var(--accent-yellow)' : '#fff'}; border:1px solid var(--border-color); border-radius:4px; max-width:110px;">
          ${opciones}</select>
      </div>`).join('');

    const dudosos = librosTrabajo.filter((b) => b.revisar && !b.duplicado).length;
    caja.innerHTML = `
      <div style="border-top:1px solid var(--border-color); margin-top:6px; padding-top:6px;">
        <div style="color: var(--text-muted); font-size:10px; margin-bottom:4px;">
          Revisa el campo de cada libro: uno mal clasificado contamina todo lo que salga de él.
          ${dudosos ? `<b style="color: var(--accent-yellow);">${dudosos} sin clasificar con seguridad.</b>` : ''}
        </div>
        <div style="max-height:170px; overflow:auto;">${filas}</div>
        <button id="btn-kb-preparar"
          style="width:100%; margin-top:6px; font-size:10px; padding:4px; border-radius:4px; background: rgba(137,180,250,0.15); color: var(--accent-blue); border:1px solid rgba(137,180,250,0.35); cursor:pointer;">
          <i class="fa-solid fa-box-open"></i> Preparar trabajo para GPU</button>
        <div id="kb-trabajo-salida" style="margin-top:5px;"></div>
      </div>`;

    caja.querySelectorAll('[data-libro]').forEach((c) => {
      c.addEventListener('change', () => { librosTrabajo[+c.dataset.libro].elegido = c.checked; });
    });
    caja.querySelectorAll('[data-dominio]').forEach((sel) => {
      const i = +sel.dataset.dominio;
      sel.value = librosTrabajo[i].domain;
      sel.addEventListener('change', () => {
        librosTrabajo[i].domain = sel.value;
        sel.style.color = '#fff';        // ya lo ha revisado una persona
      });
    });
    $('btn-kb-preparar').addEventListener('click', prepararTrabajo);
  }

  async function prepararTrabajo() {
    const salida = $('kb-trabajo-salida');
    const elegidos = librosTrabajo.filter((b) => b.elegido);
    if (!elegidos.length) {
      salida.innerHTML = '<span style="color: var(--accent-yellow);">No has elegido ningún libro.</span>';
      return;
    }
    salida.innerHTML = '<span style="color: var(--text-muted);"><i class="fa-solid fa-spinner fa-spin"></i> Troceando… puede tardar con PDF grandes.</span>';
    try {
      const m = await prigFetchJson('/api/job/prepare', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ libros: elegidos.map((b) => ({ path: b.path, domain: b.domain })) }),
      });
      const repes = (m.duplicates_skipped || []).length;
      salida.innerHTML = `
        <div style="color: var(--accent-green);"><b>Listo: ${m.total_books} libros · ${m.total_chunks} fragmentos · ${m.estimated_mb} MB</b></div>
        <div style="color: var(--text-muted); font-size:10px; margin-top:3px;">
          Sube esta carpeta a Kaggle como dataset privado:<br>
          <code style="font-size:9px; word-break:break-all;">${escapar(m.output_dir)}</code>
          ${repes ? `<br>${repes} libro(s) repetidos omitidos.` : ''}
        </div>`;
    } catch (e) {
      salida.innerHTML = `<span style="color: var(--accent-red);">${escapar(e.message)}</span>`;
    }
  }

  function escapar(t) {
    const d = document.createElement('div');
    d.textContent = t == null ? '' : String(t);
    return d.innerHTML;
  }

  function init() {
    const btn = $('btn-kb-importar');
    if (btn) btn.addEventListener('click', importar);
    const btnLibros = $('btn-kb-libros');
    if (btnLibros) btnLibros.addEventListener('click', verLibros);
    const btnTrabajo = $('btn-kb-trabajo');
    if (btnTrabajo) btnTrabajo.addEventListener('click', abrirPreparador);
    const input = $('input-kb-concepto');
    if (input) {
      input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') consultar(input.value);
      });
    }
    refrescar();
  }

  return { init, refrescar, importar, consultar, verLibros, abrirPreparador };
})();

document.addEventListener('DOMContentLoaded', () => BaseConocimiento.init());
window.BaseConocimiento = BaseConocimiento;
