/**
 * Banco del proyecto: el interruptor del chat y el panel para verlo y gestionarlo.
 *
 * El banco (backend/banco_proyecto.py) guarda el proyecto entero indexado: símbolos, código por
 * función, cambios con su diff, memoria (definiciones, teoría, decisiones) y las preguntas ya
 * resueltas. Con el interruptor activo, cada pregunta del chat lleva el mapa del proyecto y lo
 * relevante, y el modelo puede consultar el resto con herramientas.
 */
(function () {
    const $ = (id) => document.getElementById(id);
    const json = (url, opciones) => window.prigFetchJson(url, opciones);
    const post = (url, cuerpo) => json(url, { method: 'POST', body: JSON.stringify(cuerpo || {}) });
    const esc = (t) => String(t == null ? '' : t).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
    const num = (n) => (n || 0).toLocaleString('es');
    const CLAVE = 'prig_chat_banco';
    let estado = null;
    let sondeo = null;

    // ------------------------------------------------------------------ interruptor del chat
    function iniciarInterruptor() {
        const chk = $('chk-banco');
        if (!chk) return;
        try { chk.checked = localStorage.getItem(CLAVE) === '1'; } catch (e) { /* sin almacenamiento */ }
        chk.addEventListener('change', async () => {
            try { localStorage.setItem(CLAVE, chk.checked ? '1' : '0'); } catch (e) { /* sin almacenamiento */ }
            if (chk.checked) {
                // Indexar al activarlo: la primera pregunta no espera
                $('banco-resumen').textContent = 'indexando…';
                try { await post('/api/banco/activar'); } catch (e) { $('banco-resumen').textContent = e.message; return; }
            }
            resumen();
        });
        const boton = $('btn-banco-panel');
        if (boton) boton.addEventListener('click', (e) => { e.preventDefault(); abrir(); });
        resumen();
    }

    async function resumen() {
        const el = $('banco-resumen');
        if (!el) return;
        try {
            estado = await json('/api/banco');
        } catch (e) { el.textContent = ''; return; }
        const b = estado.banco;
        if (!b) { el.textContent = estado.raiz ? 'sin indexar' : 'sin carpeta'; return; }
        const semantico = b.fragmentos ? Math.round(100 * Math.min(b.vectores, b.fragmentos) / b.fragmentos) : 0;
        el.textContent = `${num(b.archivos)} arch · ${num(b.tokens)} tok · ${b.resoluciones} resueltas` +
            (semantico < 100 ? ` · semántico ${semantico}%` : '');
        el.title = `${b.raiz}\n${num(b.simbolos)} símbolos · ${b.conocimiento} notas de memoria`;
    }

    // ------------------------------------------------------------------ panel
    function crearModal() {
        if ($('modal-banco')) return;
        document.body.insertAdjacentHTML('beforeend', `
          <div id="modal-banco" class="modal-overlay" style="display:none; position:fixed; inset:0;
            background:rgba(0,0,0,0.6); z-index:10050; justify-content:center; align-items:center;">
            <div class="modal-content" style="width:980px; max-width:97vw; height:88vh; display:flex;
              flex-direction:column; background:var(--bg-panel); border:1px solid var(--border-color);
              border-radius:10px; overflow:hidden;">
              <div class="modal-header" style="display:flex; justify-content:space-between; align-items:center;
                padding:12px 16px; border-bottom:1px solid var(--border-color);">
                <h3 style="margin:0; display:flex; gap:8px; align-items:center; font-size:15px;">
                  <i class="fa-solid fa-database" style="color:var(--accent-green);"></i> Banco del proyecto
                  <span id="banco-titulo" style="font-size:11px; font-weight:normal; color:var(--text-muted);"></span>
                </h3>
                <button class="modal-close-btn" id="banco-cerrar" title="Cerrar"><i class="fa-solid fa-xmark"></i></button>
              </div>
              <div style="display:flex; gap:4px; padding:8px 16px 0; border-bottom:1px solid var(--border-color);" id="banco-pestanas">
                ${['estado:Estado', 'consola:Consola', 'memoria:Memoria', 'resoluciones:Resoluciones', 'cambios:Cambios', 'probar:Probar una pregunta']
                    .map(p => { const [id, t] = p.split(':'); return `<button data-pestana="${id}" class="tool-btn" style="font-size:12px; padding:5px 10px; border:none; background:none; color:var(--text-muted); cursor:pointer; border-bottom:2px solid transparent;">${t}</button>`; }).join('')}
              </div>
              <div id="banco-cuerpo" style="flex:1; overflow:auto; padding:14px 16px; font-size:12px;"></div>
            </div>
          </div>`);
        $('banco-cerrar').onclick = cerrar;
        $('modal-banco').addEventListener('mousedown', (e) => { if (e.target.id === 'modal-banco') cerrar(); });
        document.querySelectorAll('#banco-pestanas [data-pestana]').forEach(b => b.onclick = () => pestana(b.dataset.pestana));
    }

    function abrir() {
        crearModal();
        $('modal-banco').style.display = 'flex';
        pestana('estado');
    }

    function cerrar() {
        $('modal-banco').style.display = 'none';
        if (sondeo) { clearInterval(sondeo); sondeo = null; }
        resumen();
    }

    function pestana(nombre) {
        document.querySelectorAll('#banco-pestanas [data-pestana]').forEach(b => {
            const activa = b.dataset.pestana === nombre;
            b.style.color = activa ? 'var(--accent-green)' : 'var(--text-muted)';
            b.style.borderBottomColor = activa ? 'var(--accent-green)' : 'transparent';
        });
        if (sondeo) { clearInterval(sondeo); sondeo = null; }
        ({ estado: pintarEstado, consola: pintarConsola, memoria: pintarMemoria, resoluciones: pintarResoluciones,
           cambios: pintarCambios, probar: pintarProbar })[nombre]();
    }

    const cuerpo = () => $('banco-cuerpo');
    const boton = (id, html, color) => `<button id="${id}" class="tool-btn" style="font-size:11.5px; padding:5px 10px; border-radius:5px;
        border:1px solid ${color || 'var(--border-color)'}; background:rgba(255,255,255,0.04); color:${color || 'var(--text-color)'}; cursor:pointer;">${html}</button>`;
    const error = (e) => { cuerpo().insertAdjacentHTML('afterbegin', `<div style="color:var(--accent-red); margin-bottom:8px;">${esc(e.message || e)}</div>`); };

    async function pintarEstado() {
        try { estado = await json('/api/banco'); } catch (e) { cuerpo().innerHTML = ''; error(e); return; }
        $('banco-titulo').textContent = estado.raiz || '';
        const b = estado.banco;
        const a = estado.analisis || {};
        if (!b) {
            cuerpo().innerHTML = `<p>Este proyecto todavía no tiene banco. Al activarlo se indexa la carpeta de trabajo
                (archivos, funciones, clases y quién usa a quién) y un vigilante lo mantiene al día cada vez que guardas.</p>
                ${boton('banco-activar', '<i class="fa-solid fa-play"></i> Activar el banco', 'var(--accent-green)')}`;
            $('banco-activar').onclick = async () => {
                cuerpo().innerHTML = '<p><i class="fa-solid fa-spinner fa-spin"></i> Indexando el proyecto…</p>';
                try { await post('/api/banco/activar'); } catch (e) { error(e); }
                pintarEstado();
            };
            return;
        }
        const semantico = b.fragmentos ? Math.round(100 * Math.min(b.vectores, b.fragmentos) / b.fragmentos) : 0;
        const fila = (t, v, nota) => `<tr><td style="color:var(--text-muted); padding:3px 14px 3px 0;">${t}</td><td style="padding:3px 0;"><b>${v}</b>${nota ? ` <span style="color:var(--text-muted);">${nota}</span>` : ''}</td></tr>`;
        const analisisTxt = a.activo
            ? (a.esperando ? `<i class="fa-solid fa-pause"></i> analista en espera: ${esc(a.esperando)}`
               : a.fase === 'al día' ? '<i class="fa-solid fa-check"></i> analista al día: vigila los cambios'
               : `<i class="fa-solid fa-spinner fa-spin"></i> analista (${esc(a.fase || '')}): ${esc(a.archivo || '')}${a.fase === 'archivos' ? ` (${a.n || 0}/${a.total || 0})` : ''} con ${esc(a.modelo)}`)
            : (a.hechos != null ? `último análisis: ${a.hechos} archivos, ${a.carpetas || 0} carpetas${a.errores ? `, ${a.errores} sin respuesta válida` : ''}${a.error ? ` · ${esc(a.error)}` : ''}` : '');
        cuerpo().innerHTML = `
          <table style="border-collapse:collapse; margin-bottom:12px;">
            ${fila('Archivos', num(b.archivos), `${num(b.lineas)} líneas · ~${num(b.tokens)} tokens`)}
            ${fila('Símbolos', num(b.simbolos), `${num(b.fragmentos)} fragmentos buscables`)}
            ${fila('Búsqueda semántica', `${semantico}%`, b.vectores_pendientes ? `${num(b.vectores_pendientes)} pendientes · se completa en la GPU cuando no hay ningún modelo cargado` : (estado.embebedor.disponible ? '' : `falta ${esc(estado.embebedor.modelo)} en Ollama: solo búsqueda por palabras`))}
            ${fila('Memoria', num(b.conocimiento), b.conocimiento_revisar ? `${b.conocimiento_revisar} por revisar (sus archivos cambiaron)` : 'definiciones, teoría, decisiones')}
            ${fila('Resoluciones', num(b.resoluciones), 'preguntas ya respondidas')}
            ${fila('Cambios registrados', num(b.cambios), `versión ${b.version} · actualizado ${esc(b.actualizado || '')}`)}
            ${fila('Grafo de hechos', num(b.hechos), 'define, llama, hereda, lanza, lee config/entorno, expone y consume endpoints, DOM')}
            ${fila('Análisis con IA', `${num(b.analizados)} / ${num(b.analizados + b.pendientes_analisis)} archivos`,
                   `${num(b.resumenes_carpeta)} carpetas resumidas${b.carpetas_pendientes ? ` (${b.carpetas_pendientes} por rehacer)` : ''} · proyecto ${b.resumen_proyecto ? 'resumido' : 'sin resumir'}`)}
            ${fila('Vigilante', estado.vigilando ? 'activo' : 'parado', estado.error ? esc(estado.error) : 'sincroniza cada 4 s')}
            ${fila('En disco', `${b.mb} MB`, esc(b.carpeta))}
          </table>
          <div style="display:flex; flex-wrap:wrap; gap:8px; margin-bottom:10px;">
            ${boton('banco-sinc', '<i class="fa-solid fa-rotate"></i> Sincronizar ahora')}
            ${boton('banco-forzar', '<i class="fa-solid fa-hammer"></i> Reindexar todo')}
            ${a.activo ? boton('banco-cancelar', '<i class="fa-solid fa-stop"></i> Parar el analista', 'var(--accent-yellow)')
                       : boton('banco-analizar', `<i class="fa-solid fa-brain"></i> Analista autónomo (${num(b.pendientes_analisis)} archivos pendientes)`, 'var(--accent-purple)')}
            ${boton('banco-borrar', '<i class="fa-solid fa-trash"></i> Borrar el banco', 'var(--accent-red)')}
          </div>
          <div id="banco-analisis" style="color:var(--text-muted); margin-bottom:12px;">${analisisTxt}
            ${a.activo ? '' : `<div style="margin-top:4px;">El analista lee cada archivo con ${esc(estado.modelo_analisis)} (resumen, definiciones del
            dominio y decisiones de diseño), después resume cada carpeta y el proyecto, y sigue vivo rehaciendo solo lo que cambia.
            Espera solo si usas el chat, si la GPU o la CPU se calientan o si falta RAM.</div>`}</div>
          <fieldset style="border:1px solid var(--border-color); border-radius:6px; padding:8px 12px;">
            <legend style="color:var(--text-muted); font-size:11px;">Contexto por pregunta</legend>
            <label>Código y memoria <input id="banco-presupuesto" type="number" min="1000" max="100000" step="500" value="${estado.presupuesto}" style="width:80px;"> tokens</label>
            <label style="margin-left:14px;">Mapa del proyecto <input id="banco-mapa" type="number" min="0" max="30000" step="500" value="${estado.mapa}" style="width:80px;"> tokens</label>
            ${boton('banco-guardar-ajustes', 'Guardar')}
            <div style="color:var(--text-muted); margin-top:4px;">El motor MoE lee ~800 tokens/s: 6.000 tokens son ~7 s por pregunta. El mapa se reaprovecha entre preguntas;
              lo que no entra, el modelo lo pide con sus herramientas.</div>
          </fieldset>`;
        $('banco-sinc').onclick = async () => { try { await post('/api/banco/sincronizar'); } catch (e) { error(e); } pintarEstado(); };
        $('banco-forzar').onclick = async () => {
            cuerpo().insertAdjacentHTML('afterbegin', '<p><i class="fa-solid fa-spinner fa-spin"></i> Reindexando…</p>');
            try { await post('/api/banco/sincronizar?forzar=true'); } catch (e) { error(e); } pintarEstado();
        };
        if ($('banco-analizar')) $('banco-analizar').onclick = async () => { try { await post('/api/banco/analizar', { continuo: true }); } catch (e) { error(e); } pintarEstado(); };
        if ($('banco-cancelar')) $('banco-cancelar').onclick = async () => { await post('/api/banco/analizar/cancelar'); pintarEstado(); };
        $('banco-borrar').onclick = async () => {
            if (!confirm('¿Borrar el banco de este proyecto? Se pierden la memoria, las resoluciones y el historial de cambios (el proyecto no se toca).')) return;
            try { await json('/api/banco', { method: 'DELETE' }); } catch (e) { error(e); }
            pintarEstado();
        };
        $('banco-guardar-ajustes').onclick = async () => {
            try { await post('/api/banco/ajustes', { presupuesto: +$('banco-presupuesto').value, mapa: +$('banco-mapa').value }); }
            catch (e) { error(e); }
        };
        if (a.activo || b.vectores_pendientes) sondeo = setInterval(() => { if ($('modal-banco').style.display === 'flex') pintarEstado(); }, 4000);
    }

    function pintarConsola() {
        cuerpo().innerHTML = `
          <p style="color:var(--text-muted); margin-top:0;">La memoria de consulta que usa el modelo: el proyecto entero es el objeto <code>P</code>.
            Las variables persisten entre ejecuciones (Ctrl+Enter para ejecutar). Escribe <code>ayuda()</code> para ver la API.</p>
          <textarea id="consola-codigo" rows="6" spellcheck="false" style="width:100%; font-family:monospace; font-size:12px;"
            placeholder='expuestos = {h["o"] for h in P.hechos(r="expone")}\nlen(expuestos)'></textarea>
          <div style="display:flex; gap:8px; margin:6px 0 10px;">
            ${boton('consola-ir', '<i class="fa-solid fa-play"></i> Ejecutar', 'var(--accent-green)')}
            ${boton('consola-reiniciar', '<i class="fa-solid fa-rotate-left"></i> Reiniciar sesión')}
          </div>
          <div id="consola-salida"></div>`;
        const correr = async (reiniciar) => {
            const codigo = reiniciar ? '' : $('consola-codigo').value;
            const destino = $('consola-salida');
            destino.insertAdjacentHTML('afterbegin', '<div class="consola-pendiente"><i class="fa-solid fa-spinner fa-spin"></i></div>');
            try {
                const r = await post('/api/banco/consola', { codigo, reiniciar: !!reiniciar });
                destino.querySelector('.consola-pendiente').remove();
                if (reiniciar) { destino.innerHTML = '<p style="color:var(--text-muted);">Sesión nueva.</p>'; return; }
                destino.insertAdjacentHTML('afterbegin', `<div style="border:1px solid var(--border-color); border-radius:6px; padding:6px 10px; margin-bottom:8px;">
                    <pre style="margin:0 0 4px; color:var(--text-muted); white-space:pre-wrap;">${esc(codigo)}</pre>
                    ${r.salida ? `<pre style="margin:0; white-space:pre-wrap; max-height:360px; overflow:auto;">${esc(r.salida)}</pre>` : ''}
                    ${r.error ? `<div style="color:var(--accent-red);">${esc(r.error)}</div>` : ''}
                    ${(r.variables || []).length ? `<div style="color:var(--text-muted); font-size:10.5px;">variables: ${r.variables.map(esc).join(', ')}</div>` : ''}</div>`);
            } catch (e) { const p = destino.querySelector('.consola-pendiente'); if (p) p.remove(); error(e); }
        };
        $('consola-ir').onclick = () => correr(false);
        $('consola-reiniciar').onclick = () => correr(true);
        $('consola-codigo').addEventListener('keydown', (e) => { if (e.key === 'Enter' && e.ctrlKey) { e.preventDefault(); correr(false); } });
    }

    async function pintarMemoria() {
        let lista = [];
        try { lista = (await json('/api/banco/conocimiento')).conocimiento; } catch (e) { cuerpo().innerHTML = ''; error(e); return; }
        const tipos = ['definicion', 'teoria', 'decision', 'contexto', 'nota'];
        cuerpo().innerHTML = `
          <p style="color:var(--text-muted); margin-top:0;">Lo que el modelo sabe del proyecto además del código. Lo anotas tú, lo anota
            el modelo con su herramienta «anotar», o sale del análisis con IA. Cuando un archivo del que habla cambia, se marca para revisar.</p>
          <div style="display:grid; grid-template-columns:130px 1fr; gap:6px; margin-bottom:12px;">
            <select id="mem-tipo">${tipos.map(t => `<option>${t}</option>`).join('')}</select>
            <input id="mem-titulo" placeholder="Término o tema">
            <span></span><textarea id="mem-texto" rows="3" placeholder="Qué es, por qué se hizo así, qué teoría lo explica…"></textarea>
            <span></span><input id="mem-rutas" placeholder="Archivos relacionados, separados por comas (opcional)">
            <span></span><div>${boton('mem-guardar', '<i class="fa-solid fa-plus"></i> Guardar en la memoria', 'var(--accent-green)')}</div>
          </div>
          <div>${lista.length ? lista.map(k => `
            <div style="border:1px solid var(--border-color); border-radius:6px; padding:6px 10px; margin-bottom:6px;">
              <div style="display:flex; justify-content:space-between; gap:8px;">
                <div><span style="color:var(--accent-purple);">${esc(k.tipo)}</span> <b>${esc(k.titulo)}</b>
                  <span style="color:var(--text-muted);"> · ${esc(k.origen)} · ${esc((k.actualizado || '').slice(0, 10))}</span>
                  ${k.revisar ? '<span style="color:var(--accent-yellow);"> · ⚠ revisar: sus archivos cambiaron</span>' : ''}</div>
                <button data-olvidar="${k.id}" class="tool-btn" title="Olvidar" style="background:none; border:none; color:var(--accent-red); cursor:pointer;"><i class="fa-solid fa-trash"></i></button>
              </div>
              <div style="white-space:pre-wrap; margin-top:3px;">${esc(k.texto)}</div>
              ${k.rutas.length ? `<div style="color:var(--text-muted); margin-top:2px;">${k.rutas.map(esc).join(', ')}</div>` : ''}
            </div>`).join('') : '<p style="color:var(--text-muted);">Todavía no hay nada anotado.</p>'}</div>`;
        $('mem-guardar').onclick = async () => {
            try {
                await post('/api/banco/conocimiento', { tipo: $('mem-tipo').value, titulo: $('mem-titulo').value, texto: $('mem-texto').value,
                    rutas: $('mem-rutas').value.split(',').map(s => s.trim()).filter(Boolean) });
                pintarMemoria();
            } catch (e) { error(e); }
        };
        cuerpo().querySelectorAll('[data-olvidar]').forEach(b => b.onclick = async () => {
            try { await json(`/api/banco/conocimiento/${b.dataset.olvidar}`, { method: 'DELETE' }); } catch (e) { error(e); }
            pintarMemoria();
        });
    }

    async function pintarResoluciones() {
        let lista = [];
        try { lista = (await json('/api/banco/resoluciones')).resoluciones; } catch (e) { cuerpo().innerHTML = ''; error(e); return; }
        cuerpo().innerHTML = `
          <p style="color:var(--text-muted); margin-top:0;">Cada pregunta respondida con el banco activo. Cuando preguntas algo parecido, el modelo
            recibe el resumen y sabe si esos archivos cambiaron después.</p>
          ${lista.length ? lista.map(r => `
            <div style="border:1px solid var(--border-color); border-radius:6px; padding:6px 10px; margin-bottom:6px;">
              <div style="display:flex; justify-content:space-between; gap:8px;">
                <div><span style="color:var(--text-muted);">${esc(r.cuando.replace('T', ' ').slice(0, 16))} · ${esc(r.modelo)}</span><br><b>${esc(r.pregunta.slice(0, 300))}</b></div>
                <div style="white-space:nowrap;">
                  <button data-ver="${r.id}" class="tool-btn" title="Ver la respuesta" style="background:none; border:none; color:var(--accent-blue); cursor:pointer;"><i class="fa-solid fa-eye"></i></button>
                  <button data-olvidar="${r.id}" class="tool-btn" title="Olvidar" style="background:none; border:none; color:var(--accent-red); cursor:pointer;"><i class="fa-solid fa-trash"></i></button>
                </div>
              </div>
              <div style="margin-top:3px;">${esc(r.resumen)}</div>
              ${r.rutas.length ? `<div style="color:var(--text-muted); margin-top:2px;">${r.rutas.map(esc).join(', ')}</div>` : ''}
              <div class="res-completa" data-id="${r.id}"></div>
            </div>`).join('') : '<p style="color:var(--text-muted);">Todavía no hay preguntas resueltas con el banco.</p>'}`;
        cuerpo().querySelectorAll('[data-ver]').forEach(b => b.onclick = async () => {
            const destino = cuerpo().querySelector(`.res-completa[data-id="${b.dataset.ver}"]`);
            if (destino.innerHTML) { destino.innerHTML = ''; return; }
            try {
                const r = await json(`/api/banco/resoluciones/${b.dataset.ver}`);
                destino.innerHTML = `<pre style="white-space:pre-wrap; max-height:320px; overflow:auto; background:rgba(0,0,0,.25); padding:8px; border-radius:6px;">${esc(r.respuesta)}</pre>`;
            } catch (e) { error(e); }
        });
        cuerpo().querySelectorAll('[data-olvidar]').forEach(b => b.onclick = async () => {
            try { await json(`/api/banco/resoluciones/${b.dataset.olvidar}`, { method: 'DELETE' }); } catch (e) { error(e); }
            pintarResoluciones();
        });
    }

    async function pintarCambios() {
        let datos;
        try { datos = await json('/api/banco/cambios?limite=100'); } catch (e) { cuerpo().innerHTML = ''; error(e); return; }
        const lista = datos.cambios;
        cuerpo().innerHTML = `
          <p style="color:var(--text-muted); margin-top:0;">Lo que cambió en el proyecto (versión ${datos.version}). El modelo recibe con cada pregunta
            los cambios desde su última respuesta, con los diffs de lo relevante.</p>
          ${lista.length ? lista.map(c => {
              const s = c.simbolos || {};
              const toc = [['modificados', 'cambió'], ['nuevos', 'nuevo'], ['borrados', 'borró']]
                  .filter(([k]) => (s[k] || []).length).map(([k, t]) => `${t}: ${s[k].slice(0, 8).map(esc).join(', ')}`).join(' · ');
              return `<details style="border:1px solid var(--border-color); border-radius:6px; padding:5px 10px; margin-bottom:5px;">
                <summary style="cursor:pointer;"><b>${esc(c.ruta)}</b> <span style="color:var(--text-muted);">${esc(c.tipo)} · +${c.mas} −${c.menos} · ${esc(c.cuando.replace('T', ' '))}</span>
                  ${toc ? `<div style="color:var(--accent-green); margin-left:14px;">${toc}</div>` : ''}</summary>
                ${c.diff ? `<pre style="white-space:pre-wrap; max-height:300px; overflow:auto; background:rgba(0,0,0,.25); padding:8px; border-radius:6px;">${esc(c.diff)}</pre>` : ''}
              </details>`;
          }).join('') : '<p style="color:var(--text-muted);">Sin cambios desde que se indexó.</p>'}`;
    }

    function pintarProbar() {
        cuerpo().innerHTML = `
          <p style="color:var(--text-muted); margin-top:0;">Escribe una pregunta para ver exactamente qué le daría el banco al modelo (sin preguntarle nada).</p>
          <div style="display:flex; gap:8px; margin-bottom:10px;">
            <input id="probar-q" style="flex:1;" placeholder="p. ej. ¿dónde se decide cuántos expertos van a la GPU?">
            ${boton('probar-ir', '<i class="fa-solid fa-magnifying-glass"></i> Ver contexto', 'var(--accent-green)')}
          </div>
          <div id="probar-salida"></div>`;
        const ir = async () => {
            const q = $('probar-q').value.trim();
            if (!q) return;
            $('probar-salida').innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i>';
            try {
                const r = await json(`/api/banco/contexto?q=${encodeURIComponent(q)}&presupuesto=${(estado && estado.presupuesto) || 6000}`);
                $('probar-salida').innerHTML = `<div style="color:var(--text-muted); margin-bottom:6px;">${r.fragmentos} fragmentos · ${num(r.tokens)} tokens ·
                    ${r.cambios} cambios · ${r.conocimiento} notas · ${r.resoluciones} resoluciones · ${r.segundos} s ·
                    ${r.vectores ? 'con búsqueda semántica' : 'solo por palabras'}</div>
                    <pre style="white-space:pre-wrap; background:rgba(0,0,0,.25); padding:10px; border-radius:6px;">${esc(r.texto || '(nada relevante)')}</pre>`;
            } catch (e) { $('probar-salida').innerHTML = ''; error(e); }
        };
        $('probar-ir').onclick = ir;
        $('probar-q').addEventListener('keydown', (e) => { if (e.key === 'Enter') ir(); });
    }

    window.prigBanco = { abrir, resumen };
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', iniciarInterruptor);
    else iniciarInterruptor();
})();
