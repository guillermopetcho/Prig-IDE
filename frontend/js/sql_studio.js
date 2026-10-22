/**
 * SQL Studio (MySQL Workbench Style) - Prig IDE
 * Motor nativo en Rust (backend-rust/crates/prig-server/src/routes/sql.rs)
 */

(function () {
  'use strict';

  class SqlStudio {
    constructor() {
      this.databases = [];
      this.currentDb = 'mysql_prig';
      this.currentTable = null;
      this.tables = [];
      this.history = [];
      this.activeTab = 'results'; // 'results' | 'schema' | 'console'
      this.lastResult = null;
      this.currentSchema = null;
      this.iniciado = false;
    }

    inicializar() {
      if (this.iniciado) return;
      this.iniciado = true;
      this.render();
      this.cargarBasesDatos();
    }

    abrir() {
      this.inicializar();
      const modal = document.getElementById('modal-sql-studio');
      if (modal) {
        modal.style.display = 'flex';
      }
      if (window.workArea && typeof window.workArea.abrirHerramienta === 'function') {
        window.workArea.abrirHerramienta('modal-sql-studio', 'SQL Studio', 'fa-database');
      }
      this.refrescar();
    }

    cerrar() {
      const modal = document.getElementById('modal-sql-studio');
      if (modal) modal.style.display = 'none';
    }

    render() {
      const raiz = document.getElementById('sql-studio-raiz');
      if (!raiz) return;

      raiz.innerHTML = `
        <div class="sql-container">
          <!-- 1. Header Toolbar -->
          <header class="sql-header">
            <div class="sql-header-brand">
              <i class="fa-solid fa-database"></i>
              <span>SQL Studio</span>
              <span class="sql-badge-rust"><i class="fa-brands fa-rust"></i> Motor Rust</span>
            </div>

            <div class="sql-toolbar-controls">
              <!-- DB Selector -->
              <div style="display:flex; align-items:center; gap:6px;">
                <label style="font-size:12px; color:var(--sql-text-muted); font-weight:600;">Esquema:</label>
                <select id="sql-db-select" class="sql-select" title="Base de Datos Activa">
                  <option value="mysql_prig">mysql_prig</option>
                </select>
                <button class="sql-btn sql-btn-secondary" id="sql-btn-nueva-bd" title="Crear Base de Datos">
                  <i class="fa-solid fa-plus"></i>
                </button>
              </div>

              <!-- Action buttons -->
              <button class="sql-btn sql-btn-primary" id="sql-btn-ejecutar" title="Ejecutar Consulta (Ctrl + Enter)">
                <i class="fa-solid fa-bolt"></i> Ejecutar
              </button>

              <select id="sql-plantillas-select" class="sql-select" title="Plantillas de Consulta SQL">
                <option value="">⚡ Plantillas SQL...</option>
                <option value="SELECT * FROM usuarios LIMIT 50;">SELECT usuarios</option>
                <option value="SELECT * FROM productos WHERE stock > 0 ORDER BY precio DESC;">SELECT productos (ordenados)</option>
                <option value="SELECT u.username, u.email, count(p.id) as pedidos, ifnull(sum(p.total), 0) as total_gastado\nFROM usuarios u\nLEFT JOIN pedidos p ON u.id = p.usuario_id\nGROUP BY u.id;">INNER/LEFT JOIN Pedidos</option>
                <option value="SELECT modelo, count(*) as peticiones, round(avg(latencia_ms), 2) as latencia_media_ms\nFROM metricas_ia\nGROUP BY modelo;">Métricas IA agregadas</option>
                <option value="SHOW TABLES;">SHOW TABLES</option>
                <option value="DESCRIBE usuarios;">DESCRIBE usuarios</option>
                <option value="CREATE TABLE if not exists clientes (\n  id INTEGER PRIMARY KEY AUTO_INCREMENT,\n  nombre VARCHAR(100) NOT NULL,\n  email VARCHAR(120) NOT NULL UNIQUE,\n  saldo DECIMAL(10,2) DEFAULT 0.00,\n  creado_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP\n);">CREATE TABLE plantilla</option>
              </select>

              <button class="sql-btn sql-btn-seed" id="sql-btn-sembrar" title="Poblar tablas de ejemplo (usuarios, productos, pedidos, logs)">
                <i class="fa-solid fa-seedling"></i> Sembrar Ejemplo
              </button>

              <button class="sql-btn sql-btn-secondary" id="sql-btn-exportar-csv" title="Exportar resultado actual a CSV">
                <i class="fa-solid fa-file-csv"></i> CSV
              </button>

              <button class="sql-btn-close" id="sql-btn-cerrar" title="Cerrar SQL Studio">
                <i class="fa-solid fa-xmark"></i>
              </button>
            </div>
          </header>

          <!-- 2. Main Body: Schemas Sidebar + Workspace -->
          <div class="sql-main-body">
            <!-- Sidebar: Schemas Tree -->
            <aside class="sql-sidebar">
              <div class="sql-sidebar-header">
                <span><i class="fa-solid fa-layer-group"></i> ESQUEMAS (SCHEMAS)</span>
                <button class="sql-tree-mini-btn" id="sql-btn-refrescar-arbol" title="Recargar tablas">
                  <i class="fa-solid fa-rotate-right"></i>
                </button>
              </div>

              <div class="sql-sidebar-search">
                <input type="text" id="sql-filtro-tablas" placeholder="Buscar tablas..." autocomplete="off">
              </div>

              <div class="sql-tree-list" id="sql-lista-tablas">
                <!-- Se llena dinámicamente -->
                <div style="padding:15px; text-align:center; color:var(--sql-text-muted); font-size:12px;">
                  <i class="fa-solid fa-spinner fa-spin"></i> Cargando esquemas...
                </div>
              </div>
            </aside>

            <!-- Workspace: Editor + Results -->
            <main class="sql-workspace">
              <!-- Editor -->
              <section class="sql-editor-container">
                <div class="sql-editor-bar">
                  <div class="sql-tabs-bar">
                    <div class="sql-tab active"><i class="fa-solid fa-code"></i> Consulta 1</div>
                  </div>
                  <div style="display:flex; align-items:center; gap:8px;">
                    <button class="sql-tree-mini-btn" id="sql-btn-limpiar-editor" title="Limpiar Editor">
                      <i class="fa-solid fa-eraser"></i> Limpiar
                    </button>
                  </div>
                </div>

                <textarea id="sql-editor-input" class="sql-editor-textarea" spellcheck="false" placeholder="Escribe aquí tu consulta SQL (ej. SELECT * FROM usuarios;)...&#10;Presiona Ctrl + Enter para ejecutar.">SELECT * FROM usuarios LIMIT 50;</textarea>

                <div class="sql-editor-footer">
                  <span>Atajo: <b>Ctrl + Enter</b> para ejecutar</span>
                  <span id="sql-editor-status">Motor: Rust rusqlite / Dialecto MySQL activo</span>
                </div>
              </section>

              <!-- Results Tabs -->
              <section class="sql-results-panel">
                <nav class="sql-results-nav">
                  <div class="sql-nav-tabs">
                    <button class="sql-nav-btn active" data-tab="results" id="sql-nav-results">
                      <i class="fa-solid fa-table"></i> Resultados (<span id="sql-count-filas">0</span>)
                    </button>
                    <button class="sql-nav-btn" data-tab="schema" id="sql-nav-schema">
                      <i class="fa-solid fa-sitemap"></i> Estructura (<span id="sql-active-table-name">Ninguna</span>)
                    </button>
                    <button class="sql-nav-btn" data-tab="console" id="sql-nav-console">
                      <i class="fa-solid fa-terminal"></i> Consola / Historial
                    </button>
                  </div>

                  <div id="sql-badge-status-consulta" class="sql-status-msg">
                    Listo para consultar
                  </div>
                </nav>

                <!-- Panel 1: Resultados (Data Grid) -->
                <div class="sql-tab-content active" id="sql-tab-results">
                  <div class="sql-grid-container" id="sql-grid-contenedor">
                    <div class="sql-empty-state">
                      <i class="fa-solid fa-table-cells"></i>
                      <p>Ejecuta una consulta SQL para ver el grid de resultados aquí.</p>
                      <button class="sql-btn sql-btn-primary" style="margin-top:6px;" onclick="window.SqlStudio && window.SqlStudio.ejecutarConsulta()">
                        <i class="fa-solid fa-bolt"></i> Ejecutar consulta actual
                      </button>
                    </div>
                  </div>
                </div>

                <!-- Panel 2: Estructura (Schema) -->
                <div class="sql-tab-content" id="sql-tab-schema">
                  <div class="sql-grid-container" id="sql-schema-contenedor" style="padding:16px;">
                    <div class="sql-empty-state">
                      <i class="fa-solid fa-network-wired"></i>
                      <p>Selecciona una tabla en el panel izquierdo para inspeccionar sus columnas, claves y tipos.</p>
                    </div>
                  </div>
                </div>

                <!-- Panel 3: Consola / Historial -->
                <div class="sql-tab-content" id="sql-tab-console">
                  <div class="sql-console" id="sql-consola-logs">
                    <div class="sql-log-entry">
                      <div class="sql-log-meta">[${new Date().toLocaleTimeString()}] Conexión inicial</div>
                      <div class="sql-log-msg">Servicio de base de datos relacional inicializado correctamente con motor Rust.</div>
                    </div>
                  </div>
                </div>
              </section>
            </main>
          </div>
        </div>
      `;

      this.enlazarEventos();
    }

    enlazarEventos() {
      const selectDb = document.getElementById('sql-db-select');
      if (selectDb) {
        selectDb.addEventListener('change', (e) => {
          this.currentDb = e.target.value;
          this.cargarTablas();
        });
      }

      const btnEjecutar = document.getElementById('sql-btn-ejecutar');
      if (btnEjecutar) {
        btnEjecutar.addEventListener('click', () => this.ejecutarConsulta());
      }

      const editor = document.getElementById('sql-editor-input');
      if (editor) {
        editor.addEventListener('keydown', (e) => {
          if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
            e.preventDefault();
            this.ejecutarConsulta();
          }
        });
      }

      const btnSembrar = document.getElementById('sql-btn-sembrar');
      if (btnSembrar) {
        btnSembrar.addEventListener('click', () => this.sembrarEjemplo());
      }

      const btnNuevaDb = document.getElementById('sql-btn-nueva-bd');
      if (btnNuevaDb) {
        btnNuevaDb.addEventListener('click', () => this.crearBaseDatosPrompt());
      }

      const btnRefrescarArbol = document.getElementById('sql-btn-refrescar-arbol');
      if (btnRefrescarArbol) {
        btnRefrescarArbol.addEventListener('click', () => this.cargarTablas());
      }

      const btnLimpiar = document.getElementById('sql-btn-limpiar-editor');
      if (btnLimpiar) {
        btnLimpiar.addEventListener('click', () => {
          if (editor) {
            editor.value = '';
            editor.focus();
          }
        });
      }

      const plantillasSelect = document.getElementById('sql-plantillas-select');
      if (plantillasSelect) {
        plantillasSelect.addEventListener('change', (e) => {
          const val = e.target.value;
          if (val && editor) {
            editor.value = val;
            editor.focus();
            e.target.value = '';
          }
        });
      }

      const filtroInput = document.getElementById('sql-filtro-tablas');
      if (filtroInput) {
        filtroInput.addEventListener('input', (e) => {
          this.filtrarTablas(e.target.value);
        });
      }

      const btnExportarCsv = document.getElementById('sql-btn-exportar-csv');
      if (btnExportarCsv) {
        btnExportarCsv.addEventListener('click', () => this.exportarCSV());
      }

      const btnCerrar = document.getElementById('sql-btn-cerrar');
      if (btnCerrar) {
        btnCerrar.addEventListener('click', () => this.cerrar());
      }

      // Navegación entre pestañas de resultados
      const navBtns = document.querySelectorAll('.sql-nav-btn');
      navBtns.forEach(btn => {
        btn.addEventListener('click', (e) => {
          const tab = btn.dataset.tab;
          this.cambiarPestana(tab);
        });
      });
    }

    cambiarPestana(tabName) {
      this.activeTab = tabName;
      document.querySelectorAll('.sql-nav-btn').forEach(b => {
        b.classList.toggle('active', b.dataset.tab === tabName);
      });
      document.querySelectorAll('.sql-tab-content').forEach(c => {
        c.classList.toggle('active', c.id === `sql-tab-${tabName}`);
      });
    }

    async cargarBasesDatos() {
      try {
        const resp = await fetch('/api/sql/databases');
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const data = await resp.json();
        if (data.databases) {
          this.databases = data.databases;
          const select = document.getElementById('sql-db-select');
          if (select) {
            select.innerHTML = this.databases.map(d =>
              `<option value="${d.nombre}" ${d.nombre === this.currentDb ? 'selected' : ''}>${d.nombre} (${d.tablas_count} tablas)</option>`
            ).join('');
          }
        }
      } catch (e) {
        console.warn('Error al cargar bases de datos SQL:', e);
      }
      await this.cargarTablas();
    }

    async cargarTablas() {
      const lista = document.getElementById('sql-lista-tablas');
      if (!lista) return;

      lista.innerHTML = `
        <div style="padding:15px; text-align:center; color:var(--sql-text-muted); font-size:12px;">
          <i class="fa-solid fa-spinner fa-spin"></i> Inspeccionando tablas...
        </div>
      `;

      try {
        const resp = await fetch(`/api/sql/tables?db=${encodeURIComponent(this.currentDb)}`);
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const data = await resp.json();
        this.tables = data.tables || [];
        this.renderizarListaTablas(this.tables);
      } catch (e) {
        lista.innerHTML = `
          <div style="padding:15px; text-align:center; color:var(--sql-error); font-size:12px;">
            <i class="fa-solid fa-triangle-exclamation"></i> Error al cargar tablas: ${e.message}
          </div>
        `;
      }
    }

    renderizarListaTablas(tablas) {
      const lista = document.getElementById('sql-lista-tablas');
      if (!lista) return;

      if (!tablas || tablas.length === 0) {
        lista.innerHTML = `
          <div style="padding:20px 14px; text-align:center; color:var(--sql-text-muted); font-size:12px;">
            <i class="fa-solid fa-folder-open" style="font-size:24px; opacity:0.3; margin-bottom:8px; display:block;"></i>
            Sin tablas en esta BD.<br>
            <button class="sql-btn sql-btn-seed" style="margin-top:10px; font-size:11px;" onclick="window.SqlStudio && window.SqlStudio.sembrarEjemplo()">
              <i class="fa-solid fa-seedling"></i> Sembrar Ejemplo
            </button>
          </div>
        `;
        return;
      }

      lista.innerHTML = tablas.map(t => `
        <div class="sql-tree-item ${this.currentTable === t.nombre ? 'active' : ''}" data-tabla="${t.nombre}">
          <div class="sql-tree-item-label" title="Tabla ${t.nombre} (${t.filas} filas)">
            <i class="fa-solid fa-table" style="color:#89b4fa; font-size:12px;"></i>
            <span>${t.nombre}</span>
          </div>
          <div style="display:flex; align-items:center; gap:6px;">
            <span class="sql-badge-rows">${t.filas}</span>
            <div class="sql-tree-item-actions">
              <button class="sql-tree-mini-btn" title="SELECT * (Ver datos)" onclick="event.stopPropagation(); window.SqlStudio.consultarTabla('${t.nombre}')">
                <i class="fa-solid fa-play"></i>
              </button>
              <button class="sql-tree-mini-btn" title="Inspeccionar Estructura (DESCRIBE)" onclick="event.stopPropagation(); window.SqlStudio.inspeccionarEstructura('${t.nombre}')">
                <i class="fa-solid fa-info"></i>
              </button>
            </div>
          </div>
        </div>
      `).join('');

      lista.querySelectorAll('.sql-tree-item').forEach(el => {
        el.addEventListener('click', () => {
          const tabla = el.dataset.tabla;
          this.seleccionarTabla(tabla);
        });
      });
    }

    filtrarTablas(texto) {
      const filtro = (texto || '').toLowerCase().trim();
      if (!filtro) {
        this.renderizarListaTablas(this.tables);
        return;
      }
      const filtradas = this.tables.filter(t => t.nombre.toLowerCase().includes(filtro));
      this.renderizarListaTablas(filtradas);
    }

    seleccionarTabla(nombre) {
      this.currentTable = nombre;
      const lblTable = document.getElementById('sql-active-table-name');
      if (lblTable) lblTable.textContent = nombre;

      document.querySelectorAll('.sql-tree-item').forEach(el => {
        el.classList.toggle('active', el.dataset.tabla === nombre);
      });

      this.inspeccionarEstructura(nombre);
    }

    consultarTabla(nombre) {
      this.currentTable = nombre;
      const editor = document.getElementById('sql-editor-input');
      if (editor) {
        editor.value = `SELECT * FROM ${nombre} LIMIT 100;`;
      }
      this.ejecutarConsulta();
    }

    async inspeccionarEstructura(nombre) {
      this.currentTable = nombre;
      const lblTable = document.getElementById('sql-active-table-name');
      if (lblTable) lblTable.textContent = nombre;

      this.cambiarPestana('schema');
      const contenedor = document.getElementById('sql-schema-contenedor');
      if (!contenedor) return;

      contenedor.innerHTML = `
        <div style="padding:20px; text-align:center; color:var(--sql-text-muted);">
          <i class="fa-solid fa-spinner fa-spin"></i> Cargando estructura de ${nombre}...
        </div>
      `;

      try {
        const resp = await fetch(`/api/sql/schema?db=${encodeURIComponent(this.currentDb)}&table=${encodeURIComponent(nombre)}`);
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const data = await resp.json();
        this.currentSchema = data;

        let ddlHtml = '';
        if (data.create_table_sql) {
          ddlHtml = `
            <div style="margin-top:20px;">
              <h4 style="font-size:12px; text-transform:uppercase; color:var(--sql-text-muted); margin-bottom:8px;">
                <i class="fa-solid fa-code"></i> Definición DDL (CREATE TABLE)
              </h4>
              <pre style="background:#11111b; border:1px solid var(--sql-border); border-radius:5px; padding:12px; color:#a6e3a1; font-family:monospace; font-size:12px; overflow-x:auto;">${data.create_table_sql}</pre>
            </div>
          `;
        }

        contenedor.innerHTML = `
          <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:12px;">
            <h3 style="margin:0; font-size:15px; color:#89dceb; display:flex; align-items:center; gap:8px;">
              <i class="fa-solid fa-table"></i> Tabla: <code>${nombre}</code>
            </h3>
            <button class="sql-btn sql-btn-primary" onclick="window.SqlStudio && window.SqlStudio.consultarTabla('${nombre}')">
              <i class="fa-solid fa-magnifying-glass"></i> Ver Datos (SELECT *)
            </button>
          </div>

          <table class="sql-schema-grid">
            <thead>
              <tr>
                <th>Campo</th>
                <th>Tipo</th>
                <th>Nulo</th>
                <th>Clave</th>
                <th>Defecto</th>
                <th>Extra</th>
              </tr>
            </thead>
            <tbody>
              ${(data.columns || []).map(col => `
                <tr>
                  <td><b>${col.campo}</b></td>
                  <td style="color:#89b4fa;">${col.tipo}</td>
                  <td>${col.nulo === 'YES' ? '<span style="color:#a6adc8;">SÍ</span>' : '<b style="color:#f38ba8;">NO</b>'}</td>
                  <td>${col.clave === 'PRI' ? '<span class="sql-key-pri">PRI</span>' : col.clave}</td>
                  <td style="color:var(--sql-text-muted);">${col.defecto !== null && col.defecto !== undefined ? col.defecto : '<i>NULL</i>'}</td>
                  <td style="color:#fab387;">${col.extra || ''}</td>
                </tr>
              `).join('')}
            </tbody>
          </table>

          ${ddlHtml}
        `;
      } catch (e) {
        contenedor.innerHTML = `
          <div style="color:var(--sql-error); padding:20px; text-align:center;">
            <i class="fa-solid fa-triangle-exclamation"></i> Error al inspeccionar esquema: ${e.message}
          </div>
        `;
      }
    }

    async ejecutarConsulta() {
      const editor = document.getElementById('sql-editor-input');
      const sql = editor ? editor.value.trim() : '';
      if (!sql) return;

      const badgeStatus = document.getElementById('sql-badge-status-consulta');
      if (badgeStatus) {
        badgeStatus.className = 'sql-status-msg';
        badgeStatus.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Ejecutando en Rust...';
      }

      const inicioT = performance.now();

      try {
        const resp = await fetch('/api/sql/query', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            db: this.currentDb,
            sql: sql
          })
        });

        const data = await resp.json();
        const duracion = ((performance.now() - inicioT) / 1000).toFixed(3);
        this.lastResult = data;

        this.agregarLogConsola(sql, data.success, data.message || (data.success ? 'Query OK' : 'Error en consulta'), duracion);

        if (!data.success) {
          if (badgeStatus) {
            badgeStatus.className = 'sql-status-msg error';
            badgeStatus.textContent = data.message || 'Error en consulta SQL';
          }
          this.renderizarError(data.message || 'Error ejecutando consulta');
          return;
        }

        if (badgeStatus) {
          badgeStatus.className = 'sql-status-msg';
          badgeStatus.textContent = data.message || `OK (${duracion}s)`;
        }

        // Renderizar data grid
        this.renderizarDataGrid(data);
        this.cambiarPestana('results');

        // Si fue una mutación DDL/DML, refrescar tablas
        const upper = sql.toUpperCase().trim();
        if (upper.startsWith('CREATE') || upper.startsWith('DROP') || upper.startsWith('ALTER') || upper.startsWith('INSERT') || upper.startsWith('DELETE') || upper.startsWith('UPDATE')) {
          this.cargarTablas();
        }

      } catch (e) {
        if (badgeStatus) {
          badgeStatus.className = 'sql-status-msg error';
          badgeStatus.textContent = `Fallo de red/servidor: ${e.message}`;
        }
        this.renderizarError(e.message);
      }
    }

    renderizarDataGrid(data) {
      const grid = document.getElementById('sql-grid-contenedor');
      const countEl = document.getElementById('sql-count-filas');
      if (!grid) return;

      const columns = data.columns || [];
      const rows = data.rows || [];

      if (countEl) countEl.textContent = rows.length;

      if (columns.length === 0) {
        grid.innerHTML = `
          <div class="sql-empty-state">
            <i class="fa-solid fa-circle-check" style="color:var(--sql-success); font-size:36px;"></i>
            <h4 style="margin:0; color:#fff;">Sentencia ejecutada con éxito</h4>
            <p style="margin:0; font-family:monospace; color:var(--sql-success);">${data.message || 'Operación completada'}</p>
            <span style="font-size:12px; color:var(--sql-text-muted);">Filas afectadas: ${data.affected_rows || 0}</span>
          </div>
        `;
        return;
      }

      let ths = columns.map(c => `<th>${this.escaparHtml(c)}</th>`).join('');
      let trs = rows.map((row, idx) => {
        let tds = row.map(cell => {
          let cellHtml = '';
          if (cell === null || cell === undefined) {
            cellHtml = `<span class="sql-val-null">NULL</span>`;
          } else if (typeof cell === 'number') {
            cellHtml = `<span class="sql-val-number">${cell}</span>`;
          } else if (typeof cell === 'boolean') {
            cellHtml = `<span class="sql-val-bool">${cell ? 'TRUE' : 'FALSE'}</span>`;
          } else {
            cellHtml = `<span class="sql-val-string">${this.escaparHtml(String(cell))}</span>`;
          }
          return `<td>${cellHtml}</td>`;
        }).join('');
        return `
          <tr>
            <td class="td-row-num">${idx + 1}</td>
            ${tds}
          </tr>
        `;
      }).join('');

      grid.innerHTML = `
        <table class="sql-data-grid">
          <thead>
            <tr>
              <th class="th-row-num">#</th>
              ${ths}
            </tr>
          </thead>
          <tbody>
            ${trs}
          </tbody>
        </table>
      `;
    }

    renderizarError(mensaje) {
      const grid = document.getElementById('sql-grid-contenedor');
      if (!grid) return;
      grid.innerHTML = `
        <div class="sql-empty-state">
          <i class="fa-solid fa-circle-xmark" style="color:var(--sql-error); font-size:36px;"></i>
          <h4 style="margin:0; color:#fff;">Error de Sintaxis o Ejecución</h4>
          <pre style="background:#11111b; border:1px solid var(--sql-error); border-radius:6px; padding:12px; color:var(--sql-error); font-family:monospace; font-size:12px; max-width:80%; text-align:left; white-space:pre-wrap;">${this.escaparHtml(mensaje)}</pre>
        </div>
      `;
    }

    agregarLogConsola(query, ok, msg, duracion) {
      const consola = document.getElementById('sql-consola-logs');
      if (!consola) return;

      const hora = new Date().toLocaleTimeString();
      const div = document.createElement('div');
      div.className = `sql-log-entry ${ok ? '' : 'error'}`;
      div.innerHTML = `
        <div class="sql-log-meta">[${hora}] · Base de datos: <b>${this.currentDb}</b> · Tiempo: ${duracion}s</div>
        <div class="sql-log-query"><b>SQL:</b> ${this.escaparHtml(query)}</div>
        <div class="sql-log-msg">${this.escaparHtml(msg)}</div>
      `;
      consola.prepend(div);
    }

    async sembrarEjemplo() {
      const btn = document.getElementById('sql-btn-sembrar');
      if (btn) btn.disabled = true;

      try {
        const resp = await fetch('/api/sql/seed', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ db: this.currentDb })
        });
        const data = await resp.json();
        if (data.success) {
          await this.cargarTablas();
          this.consultarTabla('usuarios');
        } else {
          alert(`Error sembrando datos: ${data.error || 'Desconocido'}`);
        }
      } catch (e) {
        alert(`Fallo de conexión: ${e.message}`);
      } finally {
        if (btn) btn.disabled = false;
      }
    }

    async crearBaseDatosPrompt() {
      const nombre = prompt('Ingresa el nombre para la nueva base de datos:', 'app_proyecto');
      if (!nombre || !nombre.trim()) return;

      try {
        const resp = await fetch('/api/sql/databases/create', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ nombre: nombre.trim() })
        });
        const data = await resp.json();
        if (data.success) {
          this.currentDb = data.nombre;
          await this.cargarBasesDatos();
        } else {
          alert(`Error: ${data.message || data.error}`);
        }
      } catch (e) {
        alert(`Error al crear base de datos: ${e.message}`);
      }
    }

    exportarCSV() {
      if (!this.lastResult || !this.lastResult.rows || this.lastResult.rows.length === 0) {
        alert('No hay filas para exportar en la consulta actual.');
        return;
      }

      const cols = this.lastResult.columns || [];
      const rows = this.lastResult.rows || [];

      const escapeCsv = (val) => {
        if (val === null || val === undefined) return '';
        const str = String(val).replace(/"/g, '""');
        return `"${str}"`;
      };

      let csvContent = cols.map(escapeCsv).join(',') + '\n';
      for (const row of rows) {
        csvContent += row.map(escapeCsv).join(',') + '\n';
      }

      const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.setAttribute('href', url);
      link.setAttribute('download', `resultado_${this.currentDb}_${Date.now()}.csv`);
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
    }

    refrescar() {
      this.cargarBasesDatos();
    }

    escaparHtml(str) {
      if (!str) return '';
      return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
    }
  }

  window.SqlStudio = new SqlStudio();

  // Escuchar atajo global Ctrl+Shift+Q si no está en un input
  document.addEventListener('keydown', (e) => {
    if ((e.ctrlKey || e.metaKey) && e.shiftKey && (e.key === 'Q' || e.key === 'q')) {
      e.preventDefault();
      window.SqlStudio.abrir();
    }
  });

})();

