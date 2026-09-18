/**
 * Barra de menú superior y paleta de comandos.
 *
 * Se construye entera a partir del registro de comandos: no hay una sola etiqueta
 * escrita a mano aquí. Añadir un comando lo hace aparecer en su menú, en la paleta
 * y en el editor de atajos sin tocar este archivo.
 */
class MenuBar {
    constructor() {
        this.abierto = null;
        this.paletaVisible = false;
    }

    montar(contenedor) {
        this.contenedor = contenedor;
        if (!contenedor) return;
        contenedor.innerHTML = '';
        contenedor.className = 'prig-menubar';

        window.PrigCommands.MENUS.forEach(menu => {
            const raiz = document.createElement('div');
            raiz.className = 'menu-raiz';
            raiz.dataset.menu = menu;

            const titulo = document.createElement('button');
            titulo.className = 'menu-titulo';
            titulo.textContent = menu;
            titulo.setAttribute('aria-haspopup', 'true');
            titulo.setAttribute('aria-expanded', 'false');

            const panel = document.createElement('div');
            panel.className = 'menu-panel';
            panel.hidden = true;
            this._llenarPanel(panel, menu);

            titulo.onclick = (e) => {
                e.stopPropagation();
                this._alternar(raiz, titulo, panel);
            };
            // Con un menú ya abierto, pasar el ratón cambia de menú (como en Ubuntu)
            titulo.onmouseenter = () => {
                if (this.abierto && this.abierto.raiz !== raiz) this._alternar(raiz, titulo, panel);
            };

            raiz.appendChild(titulo);
            raiz.appendChild(panel);
            contenedor.appendChild(raiz);
        });

        document.addEventListener('click', () => this._cerrar());
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') this._cerrar();
        });
    }

    _llenarPanel(panel, menu) {
        const comandos = window.PrigCommands.porMenu(menu);
        // Si el menú tiene opciones con ✓, todas reservan su hueco para quedar alineadas
        const conMarcas = comandos.some(c => typeof c.marcado === 'function');
        comandos.forEach(cmd => {
            if (cmd.separadorAntes) {
                const sep = document.createElement('div');
                sep.className = 'menu-separador';
                panel.appendChild(sep);
            }
            const item = document.createElement('button');
            item.className = 'menu-item';
            // Las opciones que se activan y desactivan muestran su estado
            const marcado = typeof cmd.marcado === 'function' ? !!cmd.marcado() : null;
            item.innerHTML = `<span style="display:flex; align-items:center;">${conMarcas ?
                `<span class="menu-item-check">${marcado ? '✓' : ''}</span>` : ''}<span class="menu-item-label"></span></span><span class="menu-item-accel"></span>`;
            if (marcado !== null) item.setAttribute('aria-checked', String(marcado));
            item.querySelector('.menu-item-label').textContent = cmd.label;
            item.querySelector('.menu-item-accel').textContent =
                window.shortcutMgr.bonito(window.shortcutMgr.accel(cmd.id));
            item.onclick = (e) => {
                e.stopPropagation();
                this._cerrar();
                cmd.run();
            };
            panel.appendChild(item);
        });
    }

    /** Los atajos cambian: la barra debe reflejarlo sin recargar la página */
    refrescarAtajos() {
        if (this.contenedor) this.montar(this.contenedor);
    }

    _alternar(raiz, titulo, panel) {
        if (this.abierto && this.abierto.raiz === raiz) { this._cerrar(); return; }
        this._cerrar();
        // Se rellena al abrir: así las marcas (✓) reflejan el estado de ahora
        panel.innerHTML = '';
        this._llenarPanel(panel, raiz.dataset.menu);
        panel.hidden = false;
        titulo.setAttribute('aria-expanded', 'true');
        raiz.classList.add('abierto');
        this.abierto = { raiz, titulo, panel };
    }

    _cerrar() {
        if (!this.abierto) return;
        this.abierto.panel.hidden = true;
        this.abierto.titulo.setAttribute('aria-expanded', 'false');
        this.abierto.raiz.classList.remove('abierto');
        this.abierto = null;
    }

    // ------------------------------------------------------------------
    // Paleta de comandos
    // ------------------------------------------------------------------

    abrirPaleta() {
        let paleta = document.getElementById('prig-paleta');
        if (!paleta) {
            paleta = document.createElement('div');
            paleta.id = 'prig-paleta';
            paleta.className = 'prig-paleta';
            paleta.innerHTML = `
                <div class="paleta-caja">
                    <input type="text" id="paleta-input" placeholder="Escribe una acción…" autocomplete="off" spellcheck="false">
                    <div id="paleta-lista" class="paleta-lista"></div>
                </div>`;
            document.body.appendChild(paleta);
            paleta.onclick = (e) => { if (e.target === paleta) this.cerrarPaleta(); };
            const input = paleta.querySelector('#paleta-input');
            input.oninput = () => this._filtrarPaleta(input.value);
            input.onkeydown = (e) => this._teclasPaleta(e);
        }
        paleta.hidden = false;
        this.paletaVisible = true;
        this.indice = 0;
        const input = paleta.querySelector('#paleta-input');
        input.value = '';
        this._filtrarPaleta('');
        setTimeout(() => input.focus(), 20);
    }

    cerrarPaleta() {
        const p = document.getElementById('prig-paleta');
        if (p) p.hidden = true;
        this.paletaVisible = false;
    }

    _filtrarPaleta(texto) {
        const q = texto.trim().toLowerCase();
        this.resultados = window.PrigCommands.todos().filter(c =>
            !q || c.label.toLowerCase().includes(q) || c.menu.toLowerCase().includes(q)
        ).slice(0, 12);
        this.indice = 0;
        this._pintarPaleta();
    }

    _pintarPaleta() {
        const lista = document.getElementById('paleta-lista');
        if (!lista) return;
        if (!this.resultados.length) {
            lista.innerHTML = '<div class="paleta-vacio">Ninguna acción coincide.</div>';
            return;
        }
        lista.innerHTML = '';
        this.resultados.forEach((c, i) => {
            const fila = document.createElement('button');
            fila.className = 'paleta-item' + (i === this.indice ? ' activo' : '');
            fila.innerHTML = `<span class="paleta-menu"></span><span class="paleta-label"></span><span class="paleta-accel"></span>`;
            fila.querySelector('.paleta-menu').textContent = c.menu;
            fila.querySelector('.paleta-label').textContent = c.label;
            fila.querySelector('.paleta-accel').textContent =
                window.shortcutMgr.bonito(window.shortcutMgr.accel(c.id));
            fila.onclick = () => { this.cerrarPaleta(); c.run(); };
            lista.appendChild(fila);
        });
    }

    _teclasPaleta(e) {
        if (e.key === 'Escape') { e.preventDefault(); this.cerrarPaleta(); return; }
        if (e.key === 'ArrowDown') { e.preventDefault(); this.indice = Math.min(this.indice + 1, this.resultados.length - 1); this._pintarPaleta(); }
        if (e.key === 'ArrowUp') { e.preventDefault(); this.indice = Math.max(this.indice - 1, 0); this._pintarPaleta(); }
        if (e.key === 'Enter') {
            e.preventDefault();
            const c = this.resultados[this.indice];
            if (c) { this.cerrarPaleta(); c.run(); }
        }
    }
}

window.menuBar = new MenuBar();
