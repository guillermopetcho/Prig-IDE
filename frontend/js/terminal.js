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

    setResult(res) {
        this.setIdle();

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
    }
}

window.terminalMgr = new TerminalManager();
