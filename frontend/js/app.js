class App {
    constructor() {
        this.isSidebarCollapsed = false;
        this.lastSidebarWidth = '240px';
        this.isTerminalCollapsed = false;
        this.lastTerminalHeight = '180px';
        this.isAISidebarCollapsed = false;
        this.lastAISidebarWidth = '360px';
        this.isAIExpanded = false;
        this.currentLayoutMode = 'full';

        this.startSystemStatsTicker();
        this.initToolbar();
        this.loadWorkspaceInfo();
    }

    startSystemStatsTicker() {
        const updateStats = async () => {
            try {
                const res = await fetch('/api/system/stats');
                const stats = await res.json();

                const cpuEl = document.getElementById('hw-cpu');
                const ramEl = document.getElementById('hw-ram');
                const gpuEl = document.getElementById('hw-gpu');

                if (cpuEl) {
                    cpuEl.innerHTML = `<i class="fa-solid fa-microchip" style="color:var(--accent-blue);"></i> CPU: ${stats.cpu_pct}%`;
                    cpuEl.style.color = stats.cpu_pct > 85 ? 'var(--accent-red)' : (stats.cpu_pct > 70 ? 'var(--accent-yellow)' : 'var(--text-main)');
                }

                if (ramEl) {
                    ramEl.innerHTML = `<i class="fa-solid fa-memory" style="color:var(--accent-yellow);"></i> RAM: ${stats.ram_pct}% (${stats.ram_used_gb}/${stats.ram_total_gb}GB)`;
                    ramEl.style.color = stats.ram_pct > 85 ? 'var(--accent-red)' : 'var(--text-main)';
                }

                if (gpuEl) {
                    if (stats.gpu && stats.gpu.has_gpu) {
                        gpuEl.innerHTML = `<i class="fa-solid fa-bolt" style="color:var(--accent-green);"></i> GPU: ${stats.gpu.gpu_pct}% (${stats.gpu.vram_used_mb}MB)`;
                        gpuEl.style.color = stats.gpu.gpu_pct > 85 ? 'var(--accent-red)' : 'var(--text-main)';
                    } else {
                        gpuEl.innerHTML = `<i class="fa-solid fa-bolt" style="color:var(--text-muted);"></i> GPU: N/A`;
                    }
                }
            } catch (e) {
                // Silent fail
            }
        };

        updateStats();
        setInterval(updateStats, 3000);
    }

    /**
     * La barra de menú, los atajos y la paleta cubren ahora todas las acciones.
     * Aquí solo quedan los controles que viven dentro de los paneles.
     */
    initToolbar() {
        const bindClick = (id, handler) => {
            const el = document.getElementById(id);
            if (el) el.onclick = handler;
        };
        bindClick('btn-clear-terminal', () => window.terminalMgr.clear());
        bindClick('btn-stop-run', () => this.cancelRun());
        bindClick('btn-refresh-tree', () => window.fileTreeMgr.loadTree());
        bindClick('btn-view-notebook', () => window.editorMgr.showNotebookView());
        bindClick('btn-view-source', () => window.editorMgr.showSourceEditor());
        bindClick('btn-sidebar-open-folder', () => window.fileTreeMgr.openWorkspaceFolder());
    }








    ensureTerminalExpanded() {
        if (window.workArea) window.workArea.abrir('consola');
    }

    notifyEditorResize() {
        if (window.editorMgr && window.editorMgr.editor) {
            setTimeout(() => {
                window.editorMgr.editor.layout();
            }, 150);
        }
    }

    async loadWorkspaceInfo() {
        try {
            const res = await fetch('/api/workspace');
            const data = await res.json();
            document.getElementById('current-workspace-name').textContent = data.name || 'Prig Workspace';
            window.fileTreeMgr.loadTree();
        } catch (e) {
            console.error('Error al obtener carpeta de trabajo:', e);
            document.getElementById('current-workspace-name').textContent = 'Prig Workspace';
            window.fileTreeMgr.loadTree();
        }
    }

    /**
     * Guarda el archivo activo. Devuelve true solo si el backend confirmó la escritura,
     * para que quien lo llame (p. ej. runCode) no siga adelante con contenido sin guardar.
     */
    async saveCurrentFile() {
        const path = window.editorMgr.getActivePath();
        if (!path) {
            alert('No hay ningún archivo o notebook activo para guardar.');
            return false;
        }
        return this.saveFile(path, window.editorMgr.getContent());
    }

    /**
     * Guarda cualquier pestaña abierta, no solo la activa ("Guardar todo",
     * autoguardado). `silencioso` evita la ventana de alerta y la línea en consola:
     * el autoguardado no puede interrumpir mientras se escribe.
     */
    async saveFile(path, content = null, { silencioso = false } = {}) {
        const tab = window.editorMgr.openTabs.get(path);
        if (content === null) {
            if (!tab) return false;
            content = tab.model.getValue();
        }
        try {
            const res = await fetch('/api/file', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ path, content })
            });

            if (!res.ok) {
                const detail = await this.readErrorDetail(res);
                window.terminalMgr.appendLine(`[Error al guardar ${path}: ${detail}]`, 'stderr');
                if (!silencioso) alert(`No se pudo guardar el archivo:\n${detail}`);
                return false;
            }

            const data = await res.json();
            if (!data.success) {
                const detail = data.error || 'El backend no confirmó la escritura.';
                window.terminalMgr.appendLine(`[Error al guardar ${path}: ${detail}]`, 'stderr');
                if (!silencioso) alert(`No se pudo guardar el archivo:\n${detail}`);
                return false;
            }

            window.editorMgr.markSaved(path, content);
            if (!silencioso) window.terminalMgr.appendLine(`[Guardado exitoso: ${path}]`, 'info');
            return true;
        } catch (e) {
            if (!silencioso) alert('Error al guardar archivo: ' + e);
            return false;
        }
    }

    /** Extrae el mensaje de error de una respuesta que puede no ser JSON */
    async readErrorDetail(res) {
        try {
            const data = await res.clone().json();
            return data.detail || data.error || `HTTP ${res.status}`;
        } catch (e) {
            const text = await res.text().catch(() => '');
            return text.trim() || `HTTP ${res.status}`;
        }
    }

    async runCode() {
        const path = window.editorMgr.getActivePath();
        if (!path) {
            alert('Abre un archivo o notebook primero antes de ejecutar.');
            return;
        }

        // Auto save before running: si falla, no ejecutamos una versión antigua del archivo
        const saved = await this.saveCurrentFile();
        if (!saved) {
            this.ensureTerminalExpanded();
            window.terminalMgr.appendLine('[Ejecución cancelada: el archivo no pudo guardarse]', 'stderr');
            return;
        }

        // Auto expand terminal if collapsed
        this.ensureTerminalExpanded();

        // El identificador lo genera el cliente: /api/run no responde hasta que el
        // proceso acaba, así que el backend no puede devolverlo a tiempo para cancelar.
        this.currentRunId = `run_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;

        window.terminalMgr.clear();
        window.terminalMgr.setRunning(this.currentRunId);
        window.terminalMgr.appendLine(`$ ejecutando ${path}...\n`, 'info');

        try {
            const res = await fetch('/api/run', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ path, run_id: this.currentRunId })
            });
            const data = await prigJson(res);
            window.terminalMgr.setResult(data);
        } catch (e) {
            window.terminalMgr.setResult({
                success: false,
                stdout: '',
                stderr: 'Error de servidor backend: ' + e,
                exit_code: 1,
                elapsed: 0
            });
        }
    }

    /** Detiene la ejecución en curso */
    async cancelRun() {
        if (!this.currentRunId) return;
        try {
            await fetch('/api/run/cancel', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ run_id: this.currentRunId })
            });
        } catch (e) {
            window.terminalMgr.appendLine(`[No se pudo detener: ${e.message}]`, 'stderr');
        }
    }

}

document.addEventListener('DOMContentLoaded', () => {
    // Orden importante: apariencia y atajos antes de pintar la barra, para que los
    // menús muestren ya las teclas correctas y no haya un parpadeo de estilo.
    window.aparienciaMgr.aplicar();
    window.shortcutMgr.instalar();
    window.menuBar.montar(document.getElementById('prig-menubar-mount'));
    window.layoutMgr.init();
    window.layoutMgr.initResizer();
    window.workArea.init();
    window.planActualMgr.init();

    window.app = new App();
    
    // Restore tabs after a brief delay to ensure Monaco is ready
    setTimeout(() => {
        if (window.editorMgr) {
            window.editorMgr.restoreSessionState();
        }
    }, 500);
});

