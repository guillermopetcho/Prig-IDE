class TerminalManager {
    constructor() {
        this.outputEl = document.getElementById('terminal-body');
        this.statusTag = document.getElementById('exec-status-tag');
        this.aiErrorBtn = document.getElementById('btn-ai-explain-error');
        this.lastError = '';

        if (this.aiErrorBtn) {
            this.aiErrorBtn.onclick = () => {
                if (this.lastError && window.aiChatMgr) {
                    window.aiChatMgr.diagnoseErrorWithWeb(this.lastError);
                }
            };
        }
    }

    clear() {
        this.outputEl.innerHTML = '';
        this.aiErrorBtn.style.display = 'none';
        this.lastError = '';
        this.lastResult = null;
        this.lastFilePath = null;
        this.statusTag.textContent = 'Listo';
        this.statusTag.className = 'exec-badge';
    }

    appendLine(text, type = 'info') {
        const line = document.createElement('div');
        line.className = `term-line ${type}`;
        line.textContent = text;
        this.outputEl.appendChild(line);
        this.outputEl.scrollTop = this.outputEl.scrollHeight;
    }

    setRunning(runId = null) {
        this.statusTag.textContent = 'Ejecutando...';
        this.statusTag.className = 'exec-badge running';
        this.currentRunId = runId;
        const stop = document.getElementById('btn-stop-run');
        if (stop) stop.hidden = false;
    }

    setIdle() {
        const stop = document.getElementById('btn-stop-run');
        if (stop) stop.hidden = true;
        this.currentRunId = null;
    }

    esArchivoDesafio(filePath) {
        let p = filePath;
        if (!p && window.editorMgr && window.editorMgr.getActivePath) {
            p = window.editorMgr.getActivePath();
        }
        if (p && /([/\\]|^)desafios[/\\]/i.test(p)) return true;
        const tab = window.editorMgr && window.editorMgr.openTabs && window.editorMgr.activePath ? window.editorMgr.openTabs.get(window.editorMgr.activePath) : null;
        const contenido = tab ? (tab.savedContent || (tab.editor ? tab.editor.getValue() : '')) : '';
        if (/(?:#|\/\/)\s*Prig-Desafio-ID:/i.test(contenido)) return true;
        return false;
    }

    mostrarBannerDesafio(filePath, res) {
        const existente = this.outputEl.querySelector('.term-desafio-banner');
        if (existente) existente.remove();

        const banner = document.createElement('div');
        banner.className = 'term-desafio-banner';
        banner.style.cssText = 'margin:12px 0 6px; padding:10px 14px; background:rgba(203,166,247,0.12); border:1px solid rgba(203,166,247,0.45); border-radius:8px; display:flex; align-items:center; justify-content:space-between; gap:12px; flex-wrap:wrap; box-shadow:0 4px 12px rgba(0,0,0,0.25);';
        banner.innerHTML = `
          <div style="display:flex; align-items:center; gap:10px; font-size:12px; color:var(--text-main);">
            <i class="fa-solid fa-robot" style="color:var(--accent-purple); font-size:18px;"></i>
            <div>
              <div style="font-weight:700; color:#fff; display:flex; align-items:center; gap:6px;">
                <span>Desafío de programación detectado</span>
                <span class="des-mini" style="background:rgba(203,166,247,0.2); color:var(--accent-purple); font-size:10px; padding:1px 6px; border-radius:6px;">IA Tutor</span>
              </div>
              <div style="color:var(--text-muted); font-size:11px; margin-top:2px;">El modelo puede analizar tu código junto con esta salida de consola para calificarlo y darte feedback.</div>
            </div>
          </div>
          <button class="des-btn morado" id="btn-term-evaluar-ia" style="font-weight:700; cursor:pointer; padding:6px 14px; font-size:12px; border-radius:6px; box-shadow:0 2px 8px rgba(203,166,247,0.3); display:inline-flex; align-items:center; gap:6px;">
            <i class="fa-solid fa-wand-magic-sparkles"></i> Evaluar salida con IA
          </button>
        `;
        const btn = banner.querySelector('#btn-term-evaluar-ia');
        if (btn) {
            btn.onclick = () => {
                if (window.desafiosEvaluador) {
                    window.desafiosEvaluador.evaluarArchivoActivo({
                        filePath: filePath,
                        salida: res.stdout || '',
                        stderr: res.stderr || '',
                        exitCode: res.exit_code !== undefined ? res.exit_code : (res.success ? 0 : 1)
                    });
                }
            };
        }
        this.outputEl.appendChild(banner);
        this.outputEl.scrollTop = this.outputEl.scrollHeight;
    }

    setResult(res, filePath = null) {
        this.setIdle();
        this.lastResult = res;
        this.lastFilePath = filePath || (window.app && window.app.getActiveFilePath ? window.app.getActiveFilePath() : (window.editorMgr && window.editorMgr.getActivePath ? window.editorMgr.getActivePath() : null));

        if (res.cancelled) {
            this.appendLine('\n[Ejecución detenida por ti]', 'info');
            this.statusTag.textContent = 'Detenido';
            this.statusTag.className = 'exec-badge';
            return;
        }

        // El backend devuelve {"error": ...} cuando ni siquiera pudo lanzar el proceso
        // (archivo inexistente, ruta fuera del workspace...). Sin esto el usuario solo
        // veía "[Proceso falló]" sin saber por qué.
        if (res.error) {
            this.appendLine(res.error, 'stderr');
            this.lastError = res.error;
            this.aiErrorBtn.style.display = 'inline-flex';
        }

        if (res.stdout) {
            this.appendLine(res.stdout, 'stdout');
        }
        if (res.stderr) {
            this.appendLine(res.stderr, 'stderr');
            this.lastError = res.stderr;
            this.aiErrorBtn.style.display = 'inline-flex';
        } else if (!res.error) {
            this.aiErrorBtn.style.display = 'none';
        }

        if (res.success) {
            this.appendLine(`\n[Proceso finalizado con código ${res.exit_code} en ${res.elapsed}s]`, 'info');
            this.statusTag.textContent = `Éxito (${res.elapsed}s)`;
            this.statusTag.className = 'exec-badge success';
        } else {
            this.appendLine(`\n[Proceso falló con código ${res.exit_code}]`, 'stderr');
            this.statusTag.textContent = 'Error de ejecución';
            this.statusTag.className = 'exec-badge error';
        }

        if (this.esArchivoDesafio(this.lastFilePath)) {
            this.mostrarBannerDesafio(this.lastFilePath, res);
        }
    }
}

window.terminalMgr = new TerminalManager();
