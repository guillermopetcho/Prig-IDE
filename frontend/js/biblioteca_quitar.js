// Quitar elementos de la biblioteca sin borrar los archivos del usuario, eligiendo qué borrar de lo que Prig guardó
// de ellos (ficha de IA, citas, recortes, índice, base de conocimiento) y, en una carpeta, qué archivos quitar.
// Lo quitado se puede volver a poner desde «Quitados». Lo sirve el servidor de Rust (/api/books/inventario, delete,
// ocultos, restaurar).
(function () {
    const $ = (id) => document.getElementById(id);
    const esc = (t) => String(t ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
    const tam = (b) => b < 1024 ? `${b} B` : b < 1048576 ? `${(b / 1024).toFixed(1)} KB` : `${(b / 1048576).toFixed(1)} MB`;

    // Lo que se marca por defecto: lo regenerable se borra; lo que el usuario escribió a mano (citas, recortes,
    // páginas corregidas) se conserva salvo que lo pida.
    const POR_DEFECTO = { ficha: true, indice: true, conocimiento: true, citas: false, recortes: false, ediciones: false };

    function modal(titulo, icono) {
        cerrar();
        document.body.insertAdjacentHTML('beforeend', `
          <div id="modal-bib-quitar" class="modal-overlay" style="display:flex; position:fixed; inset:0;
            background:rgba(0,0,0,0.6); z-index:10060; justify-content:center; align-items:center;">
            <div class="modal-content" style="width:640px; max-width:96vw; max-height:88vh; display:flex; flex-direction:column;
              background:var(--bg-panel); border:1px solid var(--border-color); border-radius:10px; overflow:hidden;">
              <div class="modal-header" style="display:flex; justify-content:space-between; align-items:center;
                padding:12px 16px; border-bottom:1px solid var(--border-color);">
                <h3 style="margin:0; display:flex; gap:8px; align-items:center; font-size:15px;">
                  <i class="fa-solid ${icono}" style="color:var(--accent-red);"></i> ${esc(titulo)}
                </h3>
                <button class="modal-close-btn" id="bib-quitar-cerrar" title="Cerrar"><i class="fa-solid fa-xmark"></i></button>
              </div>
              <div id="bib-quitar-cuerpo" style="flex:1; overflow:auto; padding:14px 16px; font-size:13px;">
                <div style="text-align:center; color:var(--text-muted); padding:20px;"><i class="fa-solid fa-spinner fa-spin"></i></div>
              </div>
              <div id="bib-quitar-pie" style="display:flex; gap:8px; justify-content:flex-end; padding:10px 16px;
                border-top:1px solid var(--border-color);"></div>
            </div>
          </div>`);
        $('bib-quitar-cerrar').onclick = cerrar;
        $('modal-bib-quitar').addEventListener('mousedown', (e) => { if (e.target.id === 'modal-bib-quitar') cerrar(); });
    }

    function cerrar() {
        const m = $('modal-bib-quitar');
        if (m) m.remove();
    }

    async function json(url, opciones) {
        const r = await fetch(url, opciones);
        const d = await r.json().catch(() => ({}));
        if (!r.ok) throw new Error(d.detail || `HTTP ${r.status}`);
        return d;
    }

    function resumenPiezas(p) {
        const nombres = { ficha: 'ficha', citas: 'citas', ediciones: 'pág. corregidas', recortes: 'recortes', indice: 'fragmentos', conocimiento: 'conocimiento' };
        const partes = Object.entries(p || {}).filter(([, n]) => n > 0).map(([k, n]) => `${n} ${nombres[k] || k}`);
        return partes.length ? partes.join(' · ') : 'nada guardado';
    }

    // ------------------------------------------------------------------ quitar
    async function abrir(id, alTerminar) {
        modal('Quitar de la biblioteca', 'fa-eye-slash');
        let inv;
        try {
            inv = await json(`/api/books/inventario?id=${encodeURIComponent(id)}`);
        } catch (e) {
            $('bib-quitar-cuerpo').innerHTML = `<div style="color:var(--accent-red);">No se pudo leer el elemento: ${esc(e.message)}</div>`;
            return;
        }
        const piezas = inv.piezas || [];
        const archivos = inv.archivos || [];
        const filasPiezas = piezas.map(p => `
            <label style="display:flex; gap:10px; align-items:flex-start; padding:7px 4px; cursor:pointer; ${p.cuenta ? '' : 'opacity:.5;'}">
              <input type="checkbox" data-pieza="${esc(p.id)}" ${p.cuenta && POR_DEFECTO[p.id] ? 'checked' : ''} ${p.cuenta ? '' : 'disabled'} style="margin-top:3px;">
              <span style="flex:1;">
                <b>${esc(p.nombre)}</b> <span style="color:var(--text-muted); font-size:11px;">(${p.cuenta || 'nada'})</span><br>
                <span style="color:var(--text-muted); font-size:11px;">${esc(p.descripcion)}</span>
              </span>
            </label>`).join('');

        const bloqueCarpeta = inv.es_carpeta ? `
            <div style="margin:14px 0 6px; display:flex; gap:14px; align-items:center;">
              <b>Qué quitar</b>
              <label style="cursor:pointer;"><input type="radio" name="bib-alcance" value="todo" checked> La carpeta entera</label>
              <label style="cursor:pointer;"><input type="radio" name="bib-alcance" value="parte" ${archivos.length ? '' : 'disabled'}> Solo algunos archivos</label>
            </div>
            <div id="bib-archivos" style="display:none; border:1px solid var(--border-color); border-radius:6px; max-height:220px; overflow:auto; padding:4px 8px;">
              <div style="display:flex; gap:8px; padding:4px 0 6px; border-bottom:1px solid var(--border-color); font-size:11px;">
                <input id="bib-filtro-archivos" placeholder="Filtrar…" style="flex:1; font-size:11px; padding:3px 6px; background:var(--bg-input, transparent); color:inherit; border:1px solid var(--border-color); border-radius:4px;">
                <button class="tool-btn" id="bib-todos" style="font-size:11px; padding:2px 8px;">Todos</button>
                <button class="tool-btn" id="bib-ninguno" style="font-size:11px; padding:2px 8px;">Ninguno</button>
              </div>
              ${archivos.map(a => `
                <label data-rel="${esc(a.rel.toLowerCase())}" style="display:flex; gap:8px; align-items:center; padding:3px 0; cursor:pointer; ${a.oculto ? 'opacity:.45;' : ''}">
                  <input type="checkbox" data-archivo="${esc(a.rel)}" ${a.oculto ? 'disabled' : ''}>
                  <span style="flex:1; font-family:var(--font-mono, monospace); font-size:11px;">${esc(a.rel)}${a.oculto ? ' <i>(ya quitado)</i>' : ''}</span>
                  <span style="color:var(--text-muted); font-size:10px; white-space:nowrap;">${tam(a.bytes)} · ${esc(resumenPiezas(a.piezas))}</span>
                </label>`).join('')}
            </div>` : '';

        $('bib-quitar-cuerpo').innerHTML = `
            <div style="padding:10px 12px; background:rgba(166,227,161,0.08); border:1px solid rgba(166,227,161,0.25); border-radius:6px; margin-bottom:12px;">
              <i class="fa-solid fa-shield-halved" style="color:var(--accent-green);"></i>
              <b>${esc(inv.titulo)}</b> dejará de verse en la biblioteca y de usarse en el tutor.
              <b>Tus archivos no se borran</b>${inv.dentro_de_la_biblioteca ? '' : ' (la carpeta sigue donde está)'}, y podrás volver a ponerlo desde «Quitados».
              <div style="color:var(--text-muted); font-size:11px; margin-top:4px; word-break:break-all;">${esc(inv.ruta)}</div>
            </div>
            ${bloqueCarpeta}
            <div style="margin:12px 0 4px;"><b>Qué borrar de lo que Prig guardó</b>
              <span style="color:var(--text-muted); font-size:11px;">${inv.es_carpeta ? '(de la carpeta y de lo que contiene)' : ''}</span></div>
            <div>${filasPiezas || '<i style="color:var(--text-muted);">Prig no guarda nada de este elemento.</i>'}</div>
            <div style="color:var(--text-muted); font-size:11px; margin-top:6px;">
              Lo que no marques se conserva: si vuelves a ponerlo, tus citas y notas siguen ahí.
            </div>`;

        $('bib-quitar-pie').innerHTML = `
            <button class="tool-btn" id="bib-cancelar">Cancelar</button>
            <button class="tool-btn" id="bib-confirmar" style="background:rgba(243,139,168,0.15); color:var(--accent-red); border-color:rgba(243,139,168,0.35);">
              <i class="fa-solid fa-eye-slash"></i> Quitar</button>`;
        $('bib-cancelar').onclick = cerrar;

        const caja = $('bib-archivos');
        if (caja) {
            document.querySelectorAll('input[name="bib-alcance"]').forEach(r => r.onchange = () => {
                caja.style.display = r.value === 'parte' && r.checked ? 'block' : (r.value === 'todo' && r.checked ? 'none' : caja.style.display);
            });
            const visibles = () => [...caja.querySelectorAll('label[data-rel]')].filter(l => l.style.display !== 'none');
            $('bib-filtro-archivos').oninput = (e) => {
                const q = e.target.value.trim().toLowerCase();
                caja.querySelectorAll('label[data-rel]').forEach(l => { l.style.display = !q || l.dataset.rel.includes(q) ? 'flex' : 'none'; });
            };
            $('bib-todos').onclick = () => visibles().forEach(l => { const c = l.querySelector('input'); if (!c.disabled) c.checked = true; });
            $('bib-ninguno').onclick = () => visibles().forEach(l => { l.querySelector('input').checked = false; });
        }

        $('bib-confirmar').onclick = async () => {
            const cuerpo = {
                id: inv.ruta,
                piezas: [...document.querySelectorAll('#bib-quitar-cuerpo input[data-pieza]:checked')].map(c => c.dataset.pieza),
            };
            const parte = document.querySelector('input[name="bib-alcance"][value="parte"]');
            if (parte && parte.checked) {
                cuerpo.archivos = [...document.querySelectorAll('#bib-archivos input[data-archivo]:checked')].map(c => c.dataset.archivo);
                if (!cuerpo.archivos.length) { alert('Marca al menos un archivo.'); return; }
            }
            const boton = $('bib-confirmar');
            boton.disabled = true;
            boton.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Quitando…';
            try {
                const res = await json('/api/books/delete', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(cuerpo) });
                const borrado = resumenPiezas(res.borrado);
                $('bib-quitar-cuerpo').innerHTML = `
                    <div style="padding:14px; text-align:center;">
                      <i class="fa-solid fa-circle-check fa-2x" style="color:var(--accent-green);"></i>
                      <p><b>${res.ocultados.length === 1 ? 'Quitado' : `${res.ocultados.length} elementos quitados`}</b> de la biblioteca.</p>
                      <p style="color:var(--text-muted); font-size:12px;">Borrado de lo guardado: ${esc(borrado)}.<br>Ningún archivo tuyo se ha borrado.</p>
                    </div>`;
                $('bib-quitar-pie').innerHTML = `<button class="tool-btn" id="bib-listo">Listo</button>`;
                $('bib-listo').onclick = cerrar;
                if (alTerminar) alTerminar(res, !!cuerpo.archivos);
            } catch (e) {
                boton.disabled = false;
                boton.innerHTML = '<i class="fa-solid fa-eye-slash"></i> Quitar';
                alert(`No se pudo quitar: ${e.message}`);
            }
        };
    }

    // ------------------------------------------------------------------ quitados
    async function quitados(alTerminar) {
        modal('Quitados de la biblioteca', 'fa-box-archive');
        const pintar = async () => {
            let l;
            try {
                l = (await json('/api/books/ocultos')).ocultos || [];
            } catch (e) {
                $('bib-quitar-cuerpo').innerHTML = `<div style="color:var(--accent-red);">${esc(e.message)}</div>`;
                return;
            }
            $('bib-quitar-pie').innerHTML = `<button class="tool-btn" id="bib-listo">Cerrar</button>`;
            $('bib-listo').onclick = cerrar;
            if (!l.length) {
                $('bib-quitar-cuerpo').innerHTML = `<div style="text-align:center; color:var(--text-muted); padding:24px;">No has quitado nada de la biblioteca.</div>`;
                return;
            }
            $('bib-quitar-cuerpo').innerHTML = `
                <div style="color:var(--text-muted); font-size:12px; margin-bottom:8px;">Sus archivos siguen en disco. Volver a ponerlos los muestra otra vez (y el índice los vuelve a leer al indexar).</div>
                ${l.map(o => `
                  <div style="display:flex; gap:10px; align-items:center; padding:8px 4px; border-bottom:1px solid var(--border-color);">
                    <i class="fa-solid ${o.proyecto ? 'fa-folder-tree' : 'fa-file-lines'}" style="color:var(--text-muted);"></i>
                    <div style="flex:1; min-width:0;">
                      <b>${esc(o.titulo)}</b> <span style="color:var(--text-muted); font-size:11px;">${esc((o.categoria || '').toUpperCase())}</span><br>
                      <span style="color:var(--text-muted); font-size:11px; word-break:break-all;">${esc(o.ruta)}</span>
                      ${o.existe ? '' : '<br><span style="color:var(--accent-yellow); font-size:11px;"><i class="fa-solid fa-triangle-exclamation"></i> Ya no existe en disco</span>'}
                    </div>
                    <span style="color:var(--text-muted); font-size:10px; white-space:nowrap;">${esc((o.quitado_en || '').slice(0, 10))}</span>
                    <button class="tool-btn" data-ruta="${esc(o.ruta)}" style="font-size:11px;">${o.existe ? '<i class="fa-solid fa-rotate-left"></i> Volver a poner' : 'Olvidar'}</button>
                  </div>`).join('')}`;
            $('bib-quitar-cuerpo').querySelectorAll('button[data-ruta]').forEach(b => b.onclick = async () => {
                b.disabled = true;
                try {
                    await json('/api/books/restaurar', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ruta: b.dataset.ruta }) });
                    if (alTerminar) alTerminar();
                    pintar();
                } catch (e) {
                    b.disabled = false;
                    alert(`No se pudo: ${e.message}`);
                }
            });
        };
        pintar();
    }

    window.BibliotecaQuitar = { abrir, quitados, cerrar };
})();
