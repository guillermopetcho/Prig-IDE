/**
 * GlobalConfigManager - Panel de Configuración Completa para Prig IDE
 * Maneja:
 * 1. Gestor de Descarga de Modelos Ollama (Pull) & Selección de Cuantizaciones (Q4_K_M, Q5_K_M, Q8_0, FP16).
 * 2. Monitoreo de Disponibilidad y Tabla de Modelos Instalados (con opción de Eliminación).
 * 3. Parámetros Críticos de Rendimiento (num_ctx, num_gpu layers, temperatura, repeat_penalty).
 * 4. Preferencias del Módulo Note, Editor Monaco y Permisos de Ejecución.
 */
/**
 * Actualiza de forma sincronizada todos los selectores y catálogos de modelos
 * en todos los módulos de Prig (Chat, Configuración, Flujos, Note, Seguimiento y Workflow).
 */
window.refreshAllModelLists = async function(preferredModel = null) {
    console.log("🔄 Actualizando listas de modelos en todo el programa...", preferredModel || "");

    // 1. Refrescar modelos en Configuración Global (tabla de modelos y selector de tutor)
    if (window.globalConfigMgr && typeof window.globalConfigMgr.loadDetailedModels === 'function') {
        try {
            await window.globalConfigMgr.loadDetailedModels(preferredModel);
        } catch (e) {
            console.warn("Error refrescando modelos en globalConfigMgr:", e);
        }
    }

    // 2. Refrescar el selector principal de IA (#model-select) y aiChatMgr
    if (window.aiChatMgr && typeof window.aiChatMgr.checkStatus === 'function') {
        try {
            await window.aiChatMgr.checkStatus(preferredModel);
        } catch (e) {
            console.warn("Error refrescando aiChatMgr:", e);
        }
    }

    // 3. Refrescar selector en Prig Note (#prig-note-model-select)
    if (window.noteWindowMgr && typeof window.noteWindowMgr.loadAvailableModelsIntoSelect === 'function') {
        try {
            await window.noteWindowMgr.loadAvailableModelsIntoSelect(preferredModel);
        } catch (e) {
            console.warn("Error refrescando noteWindowMgr:", e);
        }
    }

    // 4. Refrescar catálogo y pasos de Flujos de Agentes (flujos.js)
    if (window.Flujos && typeof window.Flujos.cargarCatalogo === 'function') {
        try {
            await window.Flujos.cargarCatalogo();
        } catch (e) {
            console.warn("Error refrescando Flujos:", e);
        }
    }

    // 5. Refrescar selector en Aprendizaje Guiado / Seguimiento (#seguimiento-model)
    if (window.guiadoMgr && typeof window.guiadoMgr.loadModels === 'function') {
        try {
            await window.guiadoMgr.loadModels(preferredModel);
        } catch (e) {
            console.warn("Error refrescando guiadoMgr:", e);
        }
    }

    // 6. Refrescar Agent Workflow Manager
    if (window.agentWorkflowMgr && typeof window.agentWorkflowMgr.fetchModels === 'function') {
        try {
            await window.agentWorkflowMgr.fetchModels(preferredModel);
        } catch (e) {
            console.warn("Error refrescando agentWorkflowMgr:", e);
        }
    }

    // Disparar evento personalizado del DOM
    window.dispatchEvent(new CustomEvent('prig:models-updated', { detail: { model: preferredModel } }));
};

class GlobalConfigManager {
    constructor() {
        this.activeTab = 'ai';
    }

    init() {
        this.loadSettingsIntoUI();
        this.aplicarAccesibilidadGuardada();
    }

    openModal(tabName = 'ai') {
        const modal = document.getElementById('modal-global-config');
        if (!modal) return;
        modal.style.display = 'flex';
        this.switchTab(tabName);
        this.loadSettingsIntoUI();
        if (tabName === 'ai') {
            this.loadDetailedModels();
        } else if (tabName === 'apariencia') {
            this.initApariencia();
        } else if (tabName === 'accesibilidad' || tabName === 'atajos') {
            this.renderAccesibilidad();
        }
    }

    closeModal() {
        const modal = document.getElementById('modal-global-config');
        if (modal) modal.style.display = 'none';
    }

    switchTab(tabName) {
        if (tabName === 'atajos') tabName = 'accesibilidad';
        this.activeTab = tabName;
        const tabs = document.querySelectorAll('.config-tab-btn');
        const contents = document.querySelectorAll('.config-tab-content');

        tabs.forEach(btn => {
            // Los botones declaran su pestaña con data-tab o dentro del onclick
            const suyo = btn.dataset.tab ||
                (btn.getAttribute('onclick') || '').match(/switchTab\('([^']+)'\)/)?.[1];
            if (suyo === tabName || (tabName === 'accesibilidad' && suyo === 'atajos')) {
                btn.classList.add('active');
                btn.style.borderColor = 'var(--accent-blue)';
                btn.style.color = 'var(--accent-blue)';
                btn.style.background = 'rgba(137, 180, 250, 0.15)';
            } else {
                btn.classList.remove('active');
                btn.style.borderColor = 'transparent';
                btn.style.color = 'var(--text-muted)';
                btn.style.background = 'transparent';
            }
        });

        contents.forEach(content => {
            if (content.id === `config-tab-${tabName}`) {
                content.style.display = 'flex';
            } else {
                content.style.display = 'none';
            }
        });

        if (tabName === 'ai') {
            this.loadDetailedModels();
        } else if (tabName === 'accesibilidad') {
            this.renderAccesibilidad();
        }
    }

    async reloadOllama() {
        const statusText = document.getElementById('cfg-ollama-status-text');
        const statusBox = document.getElementById('cfg-ollama-status-box');
        const btn1 = document.getElementById('cfg-btn-reload-ollama');

        if (statusText) statusText.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i> Reconectando / Recargando servicio Ollama...`;
        if (btn1) { btn1.disabled = true; btn1.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i> Recargando...`; }

        try {
            const res = await fetch('/api/ai/reload', { method: 'POST' });
            const data = await res.json();

            if (data.online || data.status === 'ok') {
                const verText = data.version && data.version !== '?' ? ` (v${data.version})` : '';
                if (statusText) {
                    statusText.innerText = `Ollama Conectado en ${data.url || 'http://localhost:11434'}${verText}`;
                    statusText.style.color = 'var(--accent-green)';
                }
                if (statusBox) {
                    statusBox.style.background = 'rgba(166,227,161,0.1)';
                    statusBox.style.borderColor = 'var(--accent-green)';
                }
            } else {
                if (statusText) {
                    statusText.innerText = `⚠️ Servidor Ollama Desconectado (${data.message || 'No iniciado'})`;
                    statusText.style.color = 'var(--accent-red)';
                }
                if (statusBox) {
                    statusBox.style.background = 'rgba(243,139,168,0.1)';
                    statusBox.style.borderColor = 'var(--accent-red)';
                }
            }

            await this.loadDetailedModels();

            if (window.aiChatMgr && typeof window.aiChatMgr.checkStatus === 'function') {
                window.aiChatMgr.checkStatus();
            }
        } catch (e) {
            if (statusText) {
                statusText.innerText = `❌ Error al recargar Ollama: ${e.message}`;
                statusText.style.color = 'var(--accent-red)';
            }
            if (statusBox) {
                statusBox.style.background = 'rgba(243,139,168,0.1)';
                statusBox.style.borderColor = 'var(--accent-red)';
            }
        } finally {
            if (btn1) { btn1.disabled = false; btn1.innerHTML = `<i class="fa-solid fa-arrows-rotate"></i> Recargar Ollama`; }
        }
    }

    async updateOllama() {
        const btn = document.getElementById('cfg-btn-update-ollama');
        const box = document.getElementById('cfg-ollama-update-box');
        const statusText = document.getElementById('cfg-ollama-update-status');
        const bar = document.getElementById('cfg-ollama-update-bar');
        const manualCmd = document.getElementById('cfg-ollama-manual-cmd');

        if (box) box.style.display = 'block';
        if (manualCmd) manualCmd.style.display = 'none';
        if (bar) {
            bar.style.width = '10%';
            bar.style.background = 'var(--accent-purple)';
        }
        if (statusText) statusText.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Verificando versiones en el repositorio oficial...';
        if (btn) {
            btn.disabled = true;
            btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Actualizando...';
        }

        try {
            // 1. Consultar estado de versión actual y última disponible
            let verInfo = null;
            try {
                const vres = await fetch('/api/ai/ollama/version-info');
                if (vres.ok) verInfo = await vres.json();
            } catch (e) {}

            if (verInfo && verInfo.current_version && verInfo.latest_version && verInfo.latest_version !== 'desconocida' && !verInfo.has_update) {
                const proceed = confirm(
                    `Ollama ya se encuentra en la versión más reciente detectada (v${verInfo.current_version}).\n\n` +
                    `¿Deseas forzar la descarga y reinstalación de todos modos?`
                );
                if (!proceed) {
                    if (box) box.style.display = 'none';
                    if (btn) {
                        btn.disabled = false;
                        btn.innerHTML = '<i class="fa-solid fa-cloud-arrow-down"></i> Actualizar Ollama';
                    }
                    return;
                }
            }

            if (statusText) statusText.innerHTML = '<i class="fa-solid fa-cloud-arrow-down"></i> Descargando binarios de la última versión oficial de Ollama...';
            if (bar) bar.style.width = '20%';

            const res = await fetch('/api/ai/ollama/update', { method: 'POST' });
            if (!res.ok) throw new Error(`HTTP ${res.status}`);

            const reader = res.body.getReader();
            const decoder = new TextDecoder('utf-8');
            let buffer = '';

            while (true) {
                const { done, value } = await reader.read();
                if (done) break;
                buffer += decoder.decode(value, { stream: true });
                const lines = buffer.split('\n');
                buffer = lines.pop();

                for (const line of lines) {
                    if (!line.trim()) continue;
                    try {
                        const ev = JSON.parse(line.trim());
                        if (ev.porcentaje !== undefined && bar) {
                            bar.style.width = `${Math.min(100, ev.porcentaje)}%`;
                        }
                        if (ev.stage === 'error') {
                            if (statusText) statusText.innerHTML = `<span style="color: var(--accent-red);"><i class="fa-solid fa-triangle-exclamation"></i> ${ev.mensaje}</span>`;
                            if (bar) bar.style.background = 'var(--accent-red)';
                            if (manualCmd) manualCmd.style.display = 'block';
                        } else if (ev.stage === 'fin') {
                            if (statusText) statusText.innerHTML = `<span style="color: var(--accent-green); font-weight: bold;"><i class="fa-solid fa-circle-check"></i> ${ev.mensaje}</span>`;
                            if (bar) {
                                bar.style.width = '100%';
                                bar.style.background = 'var(--accent-green)';
                            }
                            await this.reloadOllama();
                        } else {
                            if (statusText) statusText.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i> ${ev.mensaje}`;
                        }
                    } catch (err) {}
                }
            }
        } catch (e) {
            if (statusText) statusText.innerHTML = `<span style="color: var(--accent-red);">❌ Error durante la actualización: ${e.message}</span>`;
            if (manualCmd) manualCmd.style.display = 'block';
        } finally {
            if (btn) {
                btn.disabled = false;
                btn.innerHTML = '<i class="fa-solid fa-cloud-arrow-down"></i> Actualizar Ollama';
            }
        }
    }

    async launchTerminalUpdate() {
        const statusText = document.getElementById('cfg-ollama-update-status');
        if (statusText) statusText.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Abriendo terminal del sistema para actualizar Ollama...';

        try {
            const res = await fetch('/api/ai/ollama/launch-terminal-update', { method: 'POST' });
            const data = await res.json();
            if (data.status === 'ok') {
                if (statusText) {
                    statusText.innerHTML = '<span style="color: var(--accent-green); font-weight: bold;"><i class="fa-solid fa-terminal"></i> Terminal abierta en tu escritorio. Sigue los pasos allí y luego pulsa "Recargar Ollama".</span>';
                }
            } else {
                if (statusText) {
                    statusText.innerHTML = `<span style="color: var(--accent-yellow);"><i class="fa-solid fa-triangle-exclamation"></i> ${data.message} Puedes copiar el comando oficial y pegarlo en una terminal.</span>`;
                }
            }
        } catch (e) {
            if (statusText) {
                statusText.innerHTML = `<span style="color: var(--accent-red);"><i class="fa-solid fa-circle-xmark"></i> Error abriendo terminal: ${e.message}</span>`;
            }
        }
    }

    copyOllamaCommand(btnEl) {
        const cmd = "curl -fsSL https://ollama.com/install.sh | sh";
        let copied = false;
        try {
            if (navigator.clipboard && navigator.clipboard.writeText) {
                navigator.clipboard.writeText(cmd)
                    .then(() => this._markCopied(btnEl))
                    .catch(() => this._fallbackCopy(cmd, btnEl));
                copied = true;
            }
        } catch (e) {}

        if (!copied) {
            this._fallbackCopy(cmd, btnEl);
        }
    }

    _fallbackCopy(text, btnEl) {
        try {
            const ta = document.createElement('textarea');
            ta.value = text;
            ta.style.position = 'fixed';
            ta.style.left = '-9999px';
            ta.style.top = '-9999px';
            document.body.appendChild(ta);
            ta.focus();
            ta.select();
            document.execCommand('copy');
            document.body.removeChild(ta);
            this._markCopied(btnEl);
        } catch (e) {
            console.error('Error al copiar:', e);
        }
    }

    _markCopied(btnEl) {
        if (!btnEl) return;
        const orig = btnEl.innerHTML;
        btnEl.innerHTML = '<i class="fa-solid fa-check"></i> ¡Copiado!';
        btnEl.style.background = 'var(--accent-green)';
        btnEl.style.color = '#11111b';
        setTimeout(() => {
            btnEl.innerHTML = orig;
            btnEl.style.background = 'var(--accent-blue)';
            btnEl.style.color = '#11111b';
        }, 2200);
    }

    async loadDetailedModels(preferredModel = null) {
        const tbody = document.getElementById('cfg-installed-models-tbody');
        const badge = document.getElementById('cfg-models-count-badge');
        const statusText = document.getElementById('cfg-ollama-status-text');
        const statusBox = document.getElementById('cfg-ollama-status-box');
        if (!tbody) return;

        tbody.innerHTML = `<tr><td colspan="5" style="padding: 12px; text-align: center; color: var(--text-muted);"><i class="fa-solid fa-spinner fa-spin"></i> Consultando modelos en servidor Ollama local...</td></tr>`;

        try {
            const res = await fetch('/api/ai/models/detailed');
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const data = await res.json();

            if (statusText) {
                const verText = data.version && data.version !== '?' ? ` (v${data.version})` : '';
                statusText.innerText = data.online 
                    ? `Ollama Conectado en ${data.url || 'http://localhost:11434'}${verText}`
                    : `⚠️ Servidor Ollama Desconectado (${data.message || 'No iniciado'})`;
                statusText.style.color = data.online ? 'var(--accent-green)' : 'var(--accent-red)';
            }

            if (statusBox) {
                if (data.online) {
                    statusBox.style.background = 'rgba(166,227,161,0.1)';
                    statusBox.style.borderColor = 'var(--accent-green)';
                } else {
                    statusBox.style.background = 'rgba(243,139,168,0.1)';
                    statusBox.style.borderColor = 'var(--accent-red)';
                }
            }

            const models = data.models || [];
            if (badge) badge.innerText = `${models.length} Modelo(s)`;

            // Actualizar el select de modelo de tutoría de este modal.
            const tutorSelect = document.getElementById('gcfg-tutor-model');
            if (tutorSelect) {
                const currentVal = preferredModel || tutorSelect.value || (window.aiConfig && window.aiConfig.agent1_model) || 'qwen2.5-coder:7b';
                tutorSelect.innerHTML = '';
                
                if (models.length > 0) {
                    const groupInstalled = document.createElement('optgroup');
                    groupInstalled.label = 'Modelos Instalados en Ollama';
                    groupInstalled.style.backgroundColor = '#181825';
                    groupInstalled.style.color = '#89b4fa';
                    models.forEach(m => {
                        const opt = document.createElement('option');
                        opt.value = m.name;
                        opt.textContent = `${m.name} (${m.size_gb} GB - ${m.quantization || 'GGUF'})`;
                        opt.style.backgroundColor = '#1e1e2e';
                        opt.style.color = '#cdd6f4';
                        if (m.name === currentVal) opt.selected = true;
                        groupInstalled.appendChild(opt);
                    });
                    tutorSelect.appendChild(groupInstalled);
                }

                const installedNames = new Set(models.map(m => m.name));
                const catalogPresets = [
                    'qwen3:14b', 'qwen3:8b', 'qwen3:4b',
                        'qwen2.5-coder:7b', 'qwen2.5-coder:14b', 'qwen2.5-coder:32b',
                        'deepseek-r1:8b', 'deepseek-r1:14b', 'deepseek-r1:1.5b', 'dolphin3:8b',
                        'hf.co/bartowski/OLMoE-1B-7B-0924-Instruct-GGUF:Q4_K_M', 'qwen3-coder:30b',
                        'hf.co/RichardErkhov/Qwen_-_Qwen1.5-MoE-A2.7B-Chat-gguf:Q4_K_M', 'deepseek-coder-v2:16b',
                        'qwen3.6:35b-a3b', 'hf.co/bartowski/Phi-3.5-MoE-instruct-GGUF:Q4_K_M', 'mixtral:8x7b',
                    'llama3.1:8b', 'mistral:7b', 'codellama:7b'
                ];
                const groupCatalog = document.createElement('optgroup');
                groupCatalog.label = 'Catálogo Soportado (agent_flows)';
                groupCatalog.style.backgroundColor = '#181825';
                groupCatalog.style.color = '#fab387';
                let catalogAdded = 0;
                catalogPresets.forEach(name => {
                    if (!installedNames.has(name) && !installedNames.has(`${name}:latest`)) {
                        const opt = document.createElement('option');
                        opt.value = name;
                        opt.textContent = `${name} (sin descargar)`;
                        opt.style.backgroundColor = '#1e1e2e';
                        opt.style.color = '#cdd6f4';
                        if (name === currentVal) opt.selected = true;
                        groupCatalog.appendChild(opt);
                        catalogAdded++;
                    }
                });
                if (catalogAdded > 0) {
                    tutorSelect.appendChild(groupCatalog);
                }

                if (currentVal && !tutorSelect.value) {
                    const opt = document.createElement('option');
                    opt.value = currentVal;
                    opt.textContent = currentVal;
                    opt.selected = true;
                    tutorSelect.appendChild(opt);
                }
            }

            if (models.length === 0) {
                tbody.innerHTML = `<tr><td colspan="5" style="padding: 14px; text-align: center; color: var(--accent-yellow);">No se encontraron modelos instalados localmente. Puedes descargar uno usando el panel superior.</td></tr>`;
                return;
            }

            // Saber si un modelo CABE en la GPU vale más que repetir "Disponible" en
            // todas las filas: el usuario descubría que no cabía por la lentitud.
            await this.cargarSalud();

            let html = '';
            models.forEach(m => {
                html += `
                    <tr style="border-bottom: 1px solid rgba(255,255,255,0.05);">
                        <td style="padding: 8px 12px; font-weight: bold; color: #fff;">
                            <i class="fa-solid fa-brain" style="color: var(--accent-purple); margin-right: 6px;"></i> ${m.name}
                        </td>
                        <td style="padding: 8px 12px; color: var(--accent-yellow); font-family: monospace;">
                            ${m.quantization || 'GGUF'}
                        </td>
                        <td style="padding: 8px 12px; color: var(--accent-blue); font-weight: bold;">
                            ${m.size_gb} GB
                        </td>
                        <td style="padding: 8px 12px;">
                            ${this.badgeAjuste(m.name)}
                        </td>
                        <td style="padding: 8px 12px; text-align: right;">
                            <button onclick="window.globalConfigMgr.deleteModel('${m.name}')" class="ubuntu-btn" style="background: rgba(243,139,168,0.2); border: 1px solid var(--accent-red); color: var(--accent-red); padding: 3px 8px; border-radius: 4px; font-size: 11px; cursor: pointer;">
                                <i class="fa-solid fa-trash-can"></i> Eliminar
                            </button>
                        </td>
                    </tr>
                `;
            });
            tbody.innerHTML = html;
        } catch (e) {
            tbody.innerHTML = `<tr><td colspan="5" style="padding: 12px; text-align: center; color: var(--accent-red);">Error conectando con Ollama: ${e.message}</td></tr>`;
        }
    }

    /** Estado del equipo: VRAM libre y qué modelos entran */
    async cargarSalud() {
        try {
            const res = await fetch('/api/system/health');
            this.salud = res.ok ? await res.json() : null;
        } catch (e) {
            this.salud = null;
        }
        this.renderAvisosSalud();
    }

    badgeAjuste(nombre) {
        const info = (this.salud && this.salud.models || []).find(m => m.name === nombre);
        if (!info) {
            return `<span style="color: var(--text-muted); font-size: 10px;">—</span>`;
        }
        if (info.fits_now) {
            return `<span style="color: var(--accent-green); background: rgba(166,227,161,0.15); padding: 2px 6px; border-radius: 4px; font-weight: bold; font-size: 10px;" title="Entra en la VRAM libre ahora mismo">
                <i class="fa-solid fa-microchip"></i> Cabe en GPU</span>`;
        }
        if (info.fits_in_gpu) {
            return `<span style="color: var(--accent-yellow); background: rgba(249,226,175,0.15); padding: 2px 6px; border-radius: 4px; font-weight: bold; font-size: 10px;" title="Cabe en la GPU, pero ahora mismo no hay VRAM libre suficiente">
                <i class="fa-solid fa-hourglass-half"></i> VRAM ocupada</span>`;
        }
        return `<span style="color: var(--accent-red); background: rgba(243,139,168,0.12); padding: 2px 6px; border-radius: 4px; font-weight: bold; font-size: 10px;" title="Necesita ~${info.estimated_vram_mb} MB y no caben en esta GPU: irá parcialmente por RAM y será lento">
            <i class="fa-solid fa-triangle-exclamation"></i> No cabe</span>`;
    }

    renderAvisosSalud() {
        const caja = document.getElementById('cfg-salud-avisos');
        if (!caja) return;
        const s = this.salud;

        if (!s) {
            caja.innerHTML = '';
            return;
        }

        const gpu = s.gpu || {};
        const resumen = gpu.has_gpu
            ? `GPU detectada · ${s.vram_free_mb} MB de VRAM libres de ${gpu.vram_total_mb} MB`
            : 'Sin GPU: la inferencia irá por CPU';

        const avisos = (s.warnings || []).map(w =>
            `<div style="color: var(--accent-yellow); font-size: 11px; margin-top: 4px;">
                <i class="fa-solid fa-triangle-exclamation"></i> ${String(w).replace(/</g, '&lt;')}</div>`).join('');

        caja.innerHTML = `
            <div style="background: rgba(0,0,0,0.25); border: 1px solid var(--border-color); border-radius: 6px; padding: 8px 10px; font-size: 11px;">
                <span style="color: ${gpu.has_gpu ? 'var(--accent-green)' : 'var(--accent-yellow)'};">
                    <i class="fa-solid fa-microchip"></i> ${resumen}
                </span>
                <span style="color: var(--text-muted); margin-left: 8px;">RAM ${s.ram_total_gb} GB</span>
                ${avisos}
            </div>`;
    }

    onPresetSelectChange(tag) {
        if (!tag) return;
        const inputTag = document.getElementById('cfg-pull-model-tag');
        if (inputTag) inputTag.value = tag;
        const progressBox = document.getElementById('cfg-pull-progress-box');
        if (progressBox) progressBox.style.display = 'none';
        const progressStatus = document.getElementById('cfg-pull-progress-status');
        if (progressStatus) progressStatus.innerText = '';
        this._syncTutorModel(tag);
    }

    onTagInput(tag) {
        const progressBox = document.getElementById('cfg-pull-progress-box');
        if (progressBox) progressBox.style.display = 'none';
        const sel = document.getElementById('cfg-pull-preset-select');
        if (sel) {
            const clean = (tag || '').trim().toLowerCase();
            let match = false;
            for (let opt of sel.options) {
                if (opt.value && opt.value.toLowerCase() === clean) {
                    sel.value = opt.value;
                    match = true;
                    break;
                }
            }
            if (!match) sel.value = '';
        }
    }

    clearPullInput() {
        const inputTag = document.getElementById('cfg-pull-model-tag');
        if (inputTag) inputTag.value = '';
        const sel = document.getElementById('cfg-pull-preset-select');
        if (sel) sel.value = '';
        const progressBox = document.getElementById('cfg-pull-progress-box');
        if (progressBox) progressBox.style.display = 'none';
        const progressStatus = document.getElementById('cfg-pull-progress-status');
        if (progressStatus) progressStatus.innerText = '';
    }

    async pullSelectedModel() {
        const inputTag = document.getElementById('cfg-pull-model-tag');
        const selectQuant = document.getElementById('cfg-pull-quant-level');
        const progressBox = document.getElementById('cfg-pull-progress-box');
        const progressStatus = document.getElementById('cfg-pull-progress-status');

        if (!inputTag || !inputTag.value.trim()) {
            alert("Por favor ingresa o selecciona un nombre o tag de modelo para descargar.");
            return;
        }

        let rawTag = inputTag.value.trim();
        // Sanitizar tag: extraer solo la parte antes de espacios o paréntesis descriptivos
        let cleanTag = rawTag.split(/[\s(]/)[0].trim();

        // Mapeo automático de tags comunitarios hacia tags oficiales en el registro de Ollama
        const aliasMap = {
            'olmoe:1b-7b': 'hf.co/bartowski/OLMoE-1B-7B-0924-Instruct-GGUF:Q4_K_M',
            'r1-distill-qwen-math:1.5b': 'deepseek-r1:1.5b',
            'deepseek-r1-0528-qwen3:8b': 'deepseek-r1:8b',
            'qwen3-coder-r1:slerp': 'qwen3-coder:30b',
            'dolphin-qwen3-r1:abliterated': 'dolphin3:8b',
            'dolphin-r1-qwen:14b': 'dolphin3:8b',
            'qwen2.5-moe:2.7b': 'hf.co/RichardErkhov/Qwen_-_Qwen1.5-MoE-A2.7B-Chat-gguf:Q4_K_M',
            'qwen3-30b-a3b:r1-distill': 'qwen3:30b-a3b',
            'qwen3.6-35b-a3b:latest': 'qwen3.6:35b-a3b',
            'phi3.5-moe:latest': 'hf.co/bartowski/Phi-3.5-MoE-instruct-GGUF:Q4_K_M',
            // Nombres antiguos que no existían en ningún registro (daban 404): se
            // redirigen a su equivalente real verificado
            'qwen3-30b-a3b': 'qwen3:30b-a3b',
            'qwen3.6-35b-a3b': 'qwen3.6:35b-a3b',
            'deepseek-coder-v2-lite': 'deepseek-coder-v2:16b',
            'deepseek-coder-v2:lite': 'deepseek-coder-v2:16b'
        };
        let fullTag = aliasMap[cleanTag] || cleanTag;

        const quant = selectQuant ? selectQuant.value : '';
        if (quant && !fullTag.includes(':')) {
            fullTag = `${fullTag}:${quant}`;
        } else if (quant && fullTag.includes(':') && !fullTag.endsWith(`:${quant}`)) {
            fullTag = `${fullTag}-${quant}`;
        }

        if (progressBox) progressBox.style.display = 'block';
        if (progressStatus) {
            progressStatus.style.color = 'var(--accent-blue)';
            progressStatus.innerText = `⏳ Conectando con Ollama para descargar '${fullTag}'...`;
        }

        try {
            const res = await fetch('/api/ai/pull', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ model: fullTag })
            });

            if (!res.ok) {
                const errText = await res.text().catch(() => '');
                throw new Error(`HTTP ${res.status}: ${errText || 'Error en servidor'}`);
            }

            const reader = res.body.getReader();
            const decoder = new TextDecoder('utf-8');
            let hasError = false;

            while (true) {
                const { done, value } = await reader.read();
                if (done) break;
                const chunk = decoder.decode(value, { stream: true });
                if (chunk.includes('Error') || chunk.includes('error')) {
                    hasError = true;
                    if (progressStatus) {
                        progressStatus.style.color = 'var(--accent-red)';
                        progressStatus.innerText = `❌ ${chunk.trim()}`;
                    }
                } else if (progressStatus) {
                    progressStatus.style.color = 'var(--accent-blue)';
                    progressStatus.innerText = `⬇️ ${chunk.trim() || 'Procesando descarga...'}`;
                }
            }

            if (!hasError) {
                if (progressStatus) {
                    progressStatus.style.color = 'var(--accent-green)';
                    progressStatus.innerText = `✅ ¡Descarga de '${fullTag}' completada con éxito! Actualizando listas de modelos...`;
                }
                if (typeof window.refreshAllModelLists === 'function') {
                    await window.refreshAllModelLists(fullTag);
                } else {
                    this.loadDetailedModels(fullTag);
                }
                if (progressStatus) progressStatus.innerText = `✅ ¡Descarga de '${fullTag}' completada con éxito! Ya está disponible en todo el programa.`;
            }
        } catch (e) {
            if (progressStatus) {
                progressStatus.style.color = 'var(--accent-red)';
                progressStatus.innerText = `❌ Error en descarga: ${e.message}`;
            }
        }
    }

    async deleteModel(modelName) {
        if (!confirm(`¿Estás seguro de eliminar el modelo '${modelName}' de tu almacenamiento local?`)) return;

        try {
            const res = await fetch('/api/ai/models/delete', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ model: modelName })
            });

            if (res.ok) {
                if (typeof window.refreshAllModelLists === 'function') {
                    await window.refreshAllModelLists();
                } else {
                    this.loadDetailedModels();
                }
            } else {
                console.error(`❌ No se pudo eliminar el modelo '${modelName}'.`);
            }
        } catch (e) {
            console.error(`Error al eliminar modelo: ${e.message}`);
        }
    }

    /**
     * Los tres selectores de «Modelos por tarea». Los que saben rellenar al medio
     * (capacidad `insert`) llevan ✦ y, en «Rellenar código», van primero.
     */
    async pintarModelosPorTarea(cfg) {
        const selects = [...document.querySelectorAll('#gcfg-roles select[data-rol]')];
        if (!selects.length) return;
        let modelos = [];
        try {
            const res = await fetch('/api/modelos');
            if (res.ok) modelos = ((await res.json()).modelos || []).filter(m => !(m.capacidades || []).includes('embedding'));
        } catch (e) { /* sin Ollama: solo «Automático» y lo ya elegido */ }
        const esc = (t) => String(t).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
        const gb = (b) => b ? ` · ${(b / 1e9).toFixed(1)} GB` : '';
        const rellena = (m) => (m.capacidades || []).includes('insert');

        selects.forEach(sel => {
            const rol = sel.dataset.rol;
            const elegido = (cfg && cfg[window.PrigModelos.ROLES[rol]]) || '';
            let lista = [...modelos].sort((a, b) => (a.bytes || 0) - (b.bytes || 0));
            if (rol === 'autocompletar') lista.sort((a, b) => rellena(b) - rellena(a));
            const auto = {
                codigo: 'Automático (el del chat)',
                explicar: 'Automático (el de cada sección)',
                autocompletar: 'Automático (el más pequeño que rellene al medio)',
            }[rol];
            let html = `<option value="">${auto}</option>`;
            html += lista.map(m => `<option value="${esc(m.nombre)}">${esc(m.nombre)}${gb(m.bytes)}${rellena(m) ? ' ✦' : ''}</option>`).join('');
            if (elegido && !lista.some(m => m.nombre === elegido)) {
                html += `<option value="${esc(elegido)}">${esc(elegido)} (no instalado)</option>`;
            }
            sel.innerHTML = html;
            sel.value = elegido;
            sel.onchange = () => this._avisoRoles(modelos);
        });
        this._avisoRoles(modelos);
    }

    _avisoRoles(modelos) {
        const aviso = document.getElementById('gcfg-roles-aviso');
        const sel = document.getElementById('gcfg-modelo-autocompletar');
        if (!aviso || !sel) return;
        const m = modelos.find(x => x.nombre === sel.value);
        const sinInsert = m && !(m.capacidades || []).includes('insert');
        aviso.hidden = !sinInsert;
        aviso.innerHTML = sinInsert
            ? `<i class="fa-solid fa-triangle-exclamation"></i> ${m.nombre} no sabe rellenar al medio: solo completará el final de la línea, sin mirar lo que hay después del cursor.`
            : '';
    }

    async loadSettingsIntoUI() {
        // 1. Cargar Configuración de IA desde el backend (fuente de verdad y persistente)
        try {
            const res = await fetch('/api/ai/config');
            if (res.ok) {
                const cfg = await res.json();
                // Publicar la config para el resto de módulos (seguimiento, recorrido...)
                window.aiConfig = cfg;

                const setValue = (id, value) => {
                    const el = document.getElementById(id);
                    if (!el || value === undefined || value === null) return;
                    // Un valor que el desplegable no trae (un contexto de 6144, un
                    // modelo recién aplicado desde "Recomendado") dejaba el campo en
                    // blanco, y al guardar se perdía. Se añade la opción que falte.
                    if (el.tagName === 'SELECT' &&
                        ![...el.options].some(o => o.value === String(value))) {
                        el.add(new Option(String(value), String(value)));
                    }
                    el.value = value;
                };

                setValue('gcfg-tutor-model', cfg.agent1_model || 'qwen2.5-coder:7b');
                this.pintarModelosPorTarea(cfg);
                setValue('gcfg-depth-level', cfg.depth_level || 'intermediate');
                setValue('cfg-num-ctx', cfg.num_ctx);
                setValue('cfg-num-gpu', cfg.num_gpu);
                setValue('cfg-num-thread', cfg.num_thread !== undefined ? cfg.num_thread : 0);
                setValue('cfg-num-predict', cfg.num_predict !== undefined ? cfg.num_predict : 2048);
                const delModelo = document.getElementById('cfg-muestreo-del-modelo');
                if (delModelo) {
                    delModelo.checked = cfg.muestreo_del_modelo !== false;
                    const t = document.getElementById('cfg-temperature');
                    if (t) t.disabled = delModelo.checked;
                }
                setValue('cfg-keep-alive', cfg.keep_alive !== undefined ? String(cfg.keep_alive) : '5m');
                setValue('cfg-temperature', cfg.temperature);
                setValue('cfg-exec-timeout', cfg.exec_timeout);

                const tempLabel = document.getElementById('val-temp');
                if (tempLabel && cfg.temperature !== undefined) tempLabel.innerText = cfg.temperature;
            }
        } catch (e) {
            console.error('No se pudo cargar la configuración de IA:', e);
        }

        // 2. Cargar Configuración de Note
        const noteMode = localStorage.getItem('prig_note_launch_mode') || 'standalone';
        if (document.getElementById('gcfg-note-launch-mode')) document.getElementById('gcfg-note-launch-mode').value = noteMode;

        // 3. Cargar Apariencia del Editor
        const fontSize = localStorage.getItem('prig_editor_font_size') || '14';
        const fontFamily = localStorage.getItem('prig_editor_font_family') || "'Fira Code', monospace";
        const tabSize = localStorage.getItem('prig_editor_tab_size') || '4';
        const theme = localStorage.getItem('prig_editor_theme') || 'prig-dark';

        if (document.getElementById('cfg-editor-font-size')) document.getElementById('cfg-editor-font-size').value = fontSize;
        if (document.getElementById('cfg-editor-font-family')) document.getElementById('cfg-editor-font-family').value = fontFamily;
        if (document.getElementById('cfg-editor-tab-size')) document.getElementById('cfg-editor-tab-size').value = tabSize;
        if (document.getElementById('cfg-editor-theme')) document.getElementById('cfg-editor-theme').value = theme;

        // 4. Permisos & Terminal
        const autoDiagnose = localStorage.getItem('prig_auto_diagnose_errors') || 'true';
        const allowAutoCmd = localStorage.getItem('prig_allow_auto_cmd') || 'ask';

        if (document.getElementById('cfg-auto-diagnose')) document.getElementById('cfg-auto-diagnose').value = autoDiagnose;
        if (document.getElementById('cfg-allow-auto-cmd')) document.getElementById('cfg-allow-auto-cmd').value = allowAutoCmd;

        // 5. Los parámetros de inferencia y el timeout los sirve el backend (paso 1)
    }

    // ==========================================
    // APARIENCIA
    // ==========================================

    initApariencia() {
        const ap = window.aparienciaMgr;
        const enlazar = (id, clave, transformar, formato) => {
            const el = document.getElementById(id);
            if (!el) return;
            el.value = String(ap.estado[clave]);
            const etiqueta = document.getElementById(`${id}-valor`);
            const pintar = () => { if (etiqueta) etiqueta.textContent = formato(ap.estado[clave]); };
            pintar();
            // "input" y no "change": el cambio debe verse mientras se arrastra
            el.oninput = () => { ap.set(clave, transformar(el.value)); pintar(); };
        };

        enlazar('ap-opacidad', 'opacidad', v => parseFloat(v), v => `${Math.round(v * 100)}%`);
        enlazar('ap-desenfoque', 'desenfoque', v => parseInt(v, 10), v => `${v}px`);

        const color = document.getElementById('ap-acento');
        if (color) { color.value = ap.estado.acento; color.oninput = () => ap.set('acento', color.value); }

        const dens = document.getElementById('ap-densidad');
        if (dens) { dens.value = ap.estado.densidad; dens.onchange = () => ap.set('densidad', dens.value); }

        const reset = document.getElementById('ap-restablecer');
        if (reset) reset.onclick = () => { ap.restablecer(); this.initApariencia(); };
    }

    // ==========================================
    // ACCESIBILIDAD Y ATAJOS DE TECLADO
    // ==========================================

    aplicarAccesibilidadGuardada() {
        try {
            const raw = localStorage.getItem('prig_accesibilidad');
            if (!raw) return;
            const cfg = JSON.parse(raw);
            const b = document.body;
            if (!b) return;

            // Escala de tipografía / interfaz
            b.classList.remove('ac-escala-110', 'ac-escala-125', 'ac-escala-140');
            if (cfg.escala && cfg.escala !== '100') {
                b.classList.add(`ac-escala-${cfg.escala}`);
            }

            // Modos de accesibilidad
            b.classList.toggle('ac-alto-contraste', !!cfg.altoContraste);
            b.classList.toggle('ac-foco-visible', !!cfg.focoVisible);
            b.classList.toggle('ac-reducir-movimiento', !!cfg.reducirMovimiento);
        } catch (e) {
            console.warn('Error aplicando accesibilidad guardada:', e);
        }
    }

    initOpcionesAccesibilidad() {
        let cfg = { escala: '100', altoContraste: false, focoVisible: false, reducirMovimiento: false };
        try {
            const raw = localStorage.getItem('prig_accesibilidad');
            if (raw) cfg = Object.assign(cfg, JSON.parse(raw));
        } catch (e) {}

        const guardar = () => {
            try {
                localStorage.setItem('prig_accesibilidad', JSON.stringify(cfg));
            } catch (e) {}
            this.aplicarAccesibilidadGuardada();
        };

        const selEscala = document.getElementById('acc-escala-fuente');
        if (selEscala && !selEscala.dataset.listo) {
            selEscala.dataset.listo = '1';
            selEscala.value = cfg.escala || '100';
            selEscala.onchange = () => {
                cfg.escala = selEscala.value;
                guardar();
            };
        }

        const chkContraste = document.getElementById('acc-alto-contraste');
        if (chkContraste && !chkContraste.dataset.listo) {
            chkContraste.dataset.listo = '1';
            chkContraste.checked = !!cfg.altoContraste;
            chkContraste.onchange = () => {
                cfg.altoContraste = chkContraste.checked;
                guardar();
            };
        }

        const chkFoco = document.getElementById('acc-foco-visible');
        if (chkFoco && !chkFoco.dataset.listo) {
            chkFoco.dataset.listo = '1';
            chkFoco.checked = !!cfg.focoVisible;
            chkFoco.onchange = () => {
                cfg.focoVisible = chkFoco.checked;
                guardar();
            };
        }

        const chkMovimiento = document.getElementById('acc-reducir-movimiento');
        if (chkMovimiento && !chkMovimiento.dataset.listo) {
            chkMovimiento.dataset.listo = '1';
            chkMovimiento.checked = !!cfg.reducirMovimiento;
            chkMovimiento.onchange = () => {
                cfg.reducirMovimiento = chkMovimiento.checked;
                guardar();
            };
        }
    }

    renderAccesibilidad() {
        this.initOpcionesAccesibilidad();
        this.renderAtajos(this._atajosFiltro || '', this._atajosCategoria || 'todas');
    }

    mostrarAlertaConflicto(htmlMsg) {
        const alerta = document.getElementById('atajos-alerta-conflicto');
        const txt = document.getElementById('atajos-alerta-texto');
        if (alerta && txt) {
            txt.innerHTML = htmlMsg;
            alerta.style.display = 'flex';
            alerta.classList.add('visible');
            const btnCerrar = document.getElementById('atajos-alerta-cerrar');
            if (btnCerrar) btnCerrar.onclick = () => this.ocultarAlertaConflicto();
        }
    }

    ocultarAlertaConflicto() {
        const alerta = document.getElementById('atajos-alerta-conflicto');
        if (alerta) {
            alerta.style.display = 'none';
            alerta.classList.remove('visible');
        }
    }

    renderAtajos(filtro = '', categoria = 'todas') {
        this._atajosFiltro = filtro;
        this._atajosCategoria = categoria;

        const lista = document.getElementById('atajos-lista');
        if (!lista) return;

        const buscar = document.getElementById('atajos-buscar');
        if (buscar && !buscar.dataset.listo) {
            buscar.dataset.listo = '1';
            buscar.oninput = () => {
                this.renderAtajos(buscar.value, this._atajosCategoria);
            };
        }

        const btnReset = document.getElementById('atajos-restablecer');
        if (btnReset && !btnReset.dataset.listo) {
            btnReset.dataset.listo = '1';
            btnReset.onclick = () => {
                if (!confirm('¿Devolver todos los atajos a sus valores de fábrica?')) return;
                this.ocultarAlertaConflicto();
                window.shortcutMgr.restablecerTodos();
                if (window.menuBar && typeof window.menuBar.refrescarAtajos === 'function') {
                    window.menuBar.refrescarAtajos();
                }
                this.renderAtajos(buscar ? buscar.value : '', this._atajosCategoria);
            };
        }

        // Renderizar barra interactiva de categorías
        const catBar = document.getElementById('atajos-categorias-bar');
        if (catBar) {
            const categorias = [
                { id: 'todas', label: 'Todas' },
                { id: 'Archivos', label: 'Archivos' },
                { id: 'Edición', label: 'Edición' },
                { id: 'Vista', label: 'Vista' },
                { id: 'Ejecutar', label: 'Ejecutar' },
                { id: 'Secciones', label: 'Secciones' },
                { id: 'Navegación', label: 'Navegación' },
                { id: 'Configuración', label: 'Configuración' },
                { id: 'Ayuda', label: 'Ayuda' }
            ];

            catBar.innerHTML = '';
            categorias.forEach(cat => {
                const pill = document.createElement('button');
                pill.type = 'button';
                pill.className = `atajos-categoria-pill ${categoria.toLowerCase() === cat.id.toLowerCase() ? 'activa' : ''}`;
                pill.textContent = cat.label;
                pill.onclick = () => {
                    this.renderAtajos(this._atajosFiltro, cat.id);
                };
                catBar.appendChild(pill);
            });
        }

        const q = filtro.trim().toLowerCase();
        const todosComandos = window.PrigCommands.todos();

        // Categorizar cada comando
        const comandosConCat = todosComandos.map(c => {
            let cat = c.menu;
            if (!cat) {
                if (c.id.startsWith('herr.')) cat = 'Secciones';
                else if (c.id.startsWith('ir.')) cat = 'Navegación';
                else if (c.id.startsWith('seleccion.')) cat = 'Edición';
                else cat = 'General';
            }
            const actual = window.shortcutMgr.accel(c.id);
            const actualBonito = window.shortcutMgr.bonito(actual);
            return { ...c, categoria: cat, actual, actualBonito };
        });

        // Filtrar por categoría y texto
        const comandos = comandosConCat.filter(c => {
            const coincideCat = (categoria === 'todas' || c.categoria.toLowerCase() === categoria.toLowerCase());
            if (!coincideCat) return false;
            if (!q) return true;

            const coincideLabel = c.label.toLowerCase().includes(q);
            const coincideMenu = c.categoria.toLowerCase().includes(q);
            const coincideTecla = (c.actualBonito || '').toLowerCase().includes(q) ||
                                  (c.actual || '').toLowerCase().includes(q);
            return coincideLabel || coincideMenu || coincideTecla;
        });

        lista.innerHTML = '';

        if (comandos.length === 0) {
            lista.innerHTML = `
                <div style="text-align: center; padding: 25px 10px; color: var(--text-muted); font-size: 12px;">
                    <i class="fa-solid fa-magnifying-glass" style="font-size: 20px; margin-bottom: 8px; opacity: 0.6; display: block;"></i>
                    No se encontraron acciones ni atajos que coincidan con la búsqueda.
                </div>`;
            return;
        }

        comandos.forEach(c => {
            const fila = document.createElement('div');
            fila.className = 'atajo-fila';

            const esPersonalizado = window.shortcutMgr.esPersonalizado(c.id);
            const tieneAtajo = !!c.actual;

            fila.innerHTML = `
                <span class="atajo-menu-badge" title="Categoría: ${c.categoria}">${c.categoria}</span>
                <div class="atajo-label-wrap">
                    <span class="atajo-label" title="${c.label}">${c.label}</span>
                    ${c.cuando === 'editor' ? '<span class="atajo-contexto-tag">editor</span>' : ''}
                </div>
                <div class="atajo-acciones-wrap">
                    <button type="button" class="atajo-tecla ${!tieneAtajo ? 'vacio' : ''}" title="${c.nativo ? 'Atajo protegido del editor/sistema' : (tieneAtajo ? 'Clic para cambiar combinación' : 'Clic para asignar combinación')}"></button>
                    ${(tieneAtajo && !c.nativo) ? '<button type="button" class="atajo-btn-accion eliminar" title="Quitar combinación de teclas"><i class="fa-solid fa-xmark"></i></button>' : ''}
                    ${(!c.nativo && esPersonalizado) ? '<button type="button" class="atajo-btn-accion reset" title="Restablecer combinación inicial"><i class="fa-solid fa-rotate-left"></i></button>' : ''}
                </div>`;

            const tecla = fila.querySelector('.atajo-tecla');
            tecla.textContent = c.actualBonito || '+ Asignar';

            if (c.nativo) {
                tecla.disabled = true;
                lista.appendChild(fila);
                return;
            }

            tecla.onclick = () => this._capturarAtajo(c, tecla, filtro, categoria);

            const btnEliminar = fila.querySelector('.atajo-btn-accion.eliminar');
            if (btnEliminar) {
                btnEliminar.onclick = (e) => {
                    e.stopPropagation();
                    this.ocultarAlertaConflicto();
                    window.shortcutMgr.eliminar(c.id);
                    if (window.menuBar && typeof window.menuBar.refrescarAtajos === 'function') {
                        window.menuBar.refrescarAtajos();
                    }
                    this.renderAtajos(filtro, categoria);
                };
            }

            const btnResetFila = fila.querySelector('.atajo-btn-accion.reset');
            if (btnResetFila) {
                btnResetFila.onclick = (e) => {
                    e.stopPropagation();
                    this.ocultarAlertaConflicto();
                    window.shortcutMgr.restablecer(c.id);
                    if (window.menuBar && typeof window.menuBar.refrescarAtajos === 'function') {
                        window.menuBar.refrescarAtajos();
                    }
                    this.renderAtajos(filtro, categoria);
                };
            }

            lista.appendChild(fila);
        });
    }

    _capturarAtajo(cmd, boton, filtro, categoria) {
        boton.classList.add('capturando');
        boton.textContent = 'Pulsa las teclas…';

        const terminar = () => {
            window.shortcutMgr.capturando = null;
            boton.classList.remove('capturando');
        };

        window.shortcutMgr.capturando = (combo) => {
            terminar();
            if (combo === 'escape') {
                this.renderAtajos(filtro, categoria);
                return;
            }

            // CONTROL ESTRICTO: Las combinaciones de teclas NO pueden coincidir
            const conflicto = window.shortcutMgr.buscarConflicto(combo, cmd.id);
            if (conflicto) {
                this.mostrarAlertaConflicto(
                    `<strong>No permitido (control de colisiones):</strong> La combinación <kbd style="background:rgba(255,255,255,0.15); padding:2px 6px; border-radius:4px; font-family:monospace;">${window.shortcutMgr.bonito(combo)}</kbd> ` +
                    `ya coincide con la acción "<strong>${conflicto.label}</strong>" (${conflicto.menu || 'Comando existente'}). ` +
                    `Para garantizar la accesibilidad y evitar colisiones, dos acciones no pueden tener el mismo atajo. Elige otra combinación de teclas.`
                );
                this.renderAtajos(filtro, categoria);
                return;
            }

            // Sin conflicto: asignar limpiamente
            this.ocultarAlertaConflicto();
            const res = window.shortcutMgr.asignar(cmd.id, combo, true);
            if (!res.ok) {
                this.mostrarAlertaConflicto(`No se pudo asignar el atajo debido a un conflicto.`);
            }

            if (window.menuBar && typeof window.menuBar.refrescarAtajos === 'function') {
                window.menuBar.refrescarAtajos();
            }
            this.renderAtajos(filtro, categoria);
        };
    }

    async saveSettings() {
        const noteMode = document.getElementById('gcfg-note-launch-mode')?.value || 'standalone';
        const fontSize = document.getElementById('cfg-editor-font-size')?.value || '14';
        const fontFamily = document.getElementById('cfg-editor-font-family')?.value || "'Fira Code', monospace";
        const tabSize = document.getElementById('cfg-editor-tab-size')?.value || '4';
        const theme = document.getElementById('cfg-editor-theme')?.value || 'prig-dark';

        const autoDiagnose = document.getElementById('cfg-auto-diagnose')?.value || 'true';
        const allowAutoCmd = document.getElementById('cfg-allow-auto-cmd')?.value || 'ask';

        // Preferencias que solo afectan a esta interfaz
        localStorage.setItem('prig_note_launch_mode', noteMode);
        localStorage.setItem('prig_editor_font_size', fontSize);
        localStorage.setItem('prig_editor_font_family', fontFamily);
        localStorage.setItem('prig_editor_tab_size', tabSize);
        localStorage.setItem('prig_editor_theme', theme);
        localStorage.setItem('prig_auto_diagnose_errors', autoDiagnose);
        localStorage.setItem('prig_allow_auto_cmd', allowAutoCmd);

        // Aplicarlas de verdad al editor: antes se guardaban y nadie las leía
        this.applyEditorSettings();

        // Ajustes que debe conocer el backend (inferencia y ejecución)
        const payload = {
            agent1_model: document.getElementById('gcfg-tutor-model')?.value || undefined,
            // "" = automático: se envía igual para poder volver a él
            ...Object.fromEntries(Object.entries(window.PrigModelos.ROLES)
                .map(([rol, clave]) => [clave, document.getElementById(`gcfg-modelo-${rol}`)?.value])
                .filter(([, v]) => v !== undefined)),
            depth_level: document.getElementById('gcfg-depth-level')?.value || undefined,
            temperature: parseFloat(document.getElementById('cfg-temperature')?.value ?? '0.3'),
            num_ctx: parseInt(document.getElementById('cfg-num-ctx')?.value ?? '4096', 10),
            num_gpu: parseInt(document.getElementById('cfg-num-gpu')?.value ?? '-1', 10),
            num_thread: parseInt(document.getElementById('cfg-num-thread')?.value ?? '0', 10),
            num_predict: parseInt(document.getElementById('cfg-num-predict')?.value ?? '2048', 10),
            muestreo_del_modelo: document.getElementById('cfg-muestreo-del-modelo')?.checked !== false,
            keep_alive: document.getElementById('cfg-keep-alive')?.value ?? '5m',
            exec_timeout: parseInt(document.getElementById('cfg-exec-timeout')?.value ?? '25', 10)
        };

        try {
            const res = await fetch('/api/ai/config', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            window.aiConfig = await res.json();
        } catch (e) {
            alert(`⚠️ Los ajustes del editor se guardaron, pero no se pudo guardar la configuración de IA:\n${e.message}`);
            this.closeModal();
            return;
        }

        alert("✅ Configuración global de Prig IDE guardada exitosamente.");
        this.closeModal();
    }

    /**
     * Aplica perfiles de rendimiento y consumo de 1-clic
     * @param {'ahorro'|'equilibrado'|'calidad'} type
     */
    applyProfile(type) {
        const setValue = (id, val) => {
            const el = document.getElementById(id);
            if (el) el.value = val;
        };

        if (type === 'ahorro') {
            // Optimizado para qwen3:14b en GPU 6GB o sistemas con CPU/RAM
            setValue('cfg-num-ctx', '2048');
            // Capas en automático: medido, forzar 20-24 capas no acelera y con 24
            // el 14B se quedó sin memoria. Ollama reparte mejor solo.
            setValue('cfg-num-gpu', '-1');
            setValue('cfg-num-thread', '6'); // 6 hilos para balancear la carga en CPU
            setValue('cfg-num-predict', '1024'); // Límite razonable para respuestas ágiles
            setValue('cfg-keep-alive', '0'); // Liberar VRAM inmediatamente al terminar
            setValue('cfg-temperature', '0.2');
            const tempVal = document.getElementById('val-temp');
            if (tempVal) tempVal.innerText = '0.2';

            const tutor = document.getElementById('gcfg-tutor-model');
            if (tutor) {
                for (let opt of tutor.options) {
                    if (opt.value.includes('qwen3:14b') || opt.value.includes('14b')) {
                        tutor.value = opt.value;
                        break;
                    }
                }
            }
            this._showToastNotice('🟢 Perfil "Ahorro" aplicado (contexto 2048, capas automáticas, keep_alive 0).');
        } else if (type === 'equilibrado') {
            setValue('cfg-num-ctx', '4096');
            setValue('cfg-num-gpu', '-1');
            setValue('cfg-num-thread', '0');
            setValue('cfg-num-predict', '2048');
            setValue('cfg-keep-alive', '5m');
            setValue('cfg-temperature', '0.2');
            const tempVal = document.getElementById('val-temp');
            if (tempVal) tempVal.innerText = '0.2';
            this._showToastNotice('🔵 Perfil "Equilibrado" aplicado (4096 ctx, capas automáticas, keep_alive 5m).');
        } else if (type === 'calidad') {
            setValue('cfg-num-ctx', '8192');
            setValue('cfg-num-gpu', '-1');
            setValue('cfg-num-thread', '0');
            setValue('cfg-num-predict', '4096');
            setValue('cfg-keep-alive', '15m');
            setValue('cfg-temperature', '0.3');
            const tempVal = document.getElementById('val-temp');
            if (tempVal) tempVal.innerText = '0.3';
            this._showToastNotice('🟣 Perfil "Máxima Calidad" aplicado (8192 ctx, Máxima VRAM, keep_alive 15m).');
        }
    }

    _showToastNotice(msg) {
        const avisos = document.getElementById('cfg-salud-avisos');
        if (avisos) {
            const banner = document.createElement('div');
            banner.style.cssText = 'background: rgba(137,180,250,0.15); border: 1px solid var(--accent-blue); color: var(--accent-blue); padding: 6px 10px; border-radius: 6px; font-size: 11px; margin-bottom: 6px;';
            banner.innerHTML = `<i class="fa-solid fa-circle-info"></i> ${msg}`;
            avisos.prepend(banner);
            setTimeout(() => banner.remove(), 4500);
        }
    }

    toggleCatalogView() {
        const catView = document.getElementById('cfg-catalog-view');
        if (!catView) return;
        if (catView.style.display === 'none' || !catView.style.display) {
            catView.style.display = 'block';
            this.loadCatalogGrid();
        } else {
            catView.style.display = 'none';
        }
    }

    async loadCatalogGrid() {
        const grid = document.getElementById('cfg-catalog-grid');
        if (!grid) return;
        grid.innerHTML = '<div style="color: var(--text-muted); font-size: 11px; padding: 8px;"><i class="fa-solid fa-spinner fa-spin"></i> Consultando catálogo completo de modelos (agent_flows)...</div>';

        try {
            const res = await fetch('/api/ai/catalog');
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const data = await res.json();
            const catalog = data.catalog || [];

            if (catalog.length === 0) {
                grid.innerHTML = '<div style="color: var(--text-muted); font-size: 11px;">No hay modelos disponibles en el catálogo.</div>';
                return;
            }

            let html = '';
            catalog.forEach(m => {
                const isInstalled = m.instalado;
                const badgeInstalled = isInstalled 
                    ? `<span style="background: rgba(166,227,161,0.2); color: var(--accent-green); padding: 1px 6px; border-radius: 4px; font-size: 10px; font-weight: bold;"><i class="fa-solid fa-check"></i> Instalado</span>`
                    : `<span style="background: rgba(249,226,175,0.15); color: var(--accent-yellow); padding: 1px 6px; border-radius: 4px; font-size: 10px;"><i class="fa-solid fa-cloud-arrow-down"></i> Por descargar</span>`;
                
                const vramBadge = m.vram_gb ? `${m.vram_gb} GB VRAM` : '';
                const familiaBadge = m.familia ? `<span style="color: var(--accent-purple); font-size: 10px; font-weight: bold;">${m.familia}</span>` : '';
                const fuerte = Array.isArray(m.fuerte_en) ? m.fuerte_en.slice(0, 2).join(', ') : '';
                const safeNota = String(m.nota || m.name).replace(/"/g, '&quot;');

                html += `
                    <div class="cfg-catalog-card" data-model="${m.name}" style="background: rgba(255,255,255,0.04); border: 1px solid var(--border-color); border-radius: 6px; padding: 8px; display: flex; flex-direction: column; justify-content: space-between; gap: 4px; cursor: pointer; transition: all 0.2s;" 
                         onmouseover="if (this.style.borderColor !== 'var(--accent-purple)') this.style.borderColor='var(--accent-blue)';" 
                         onmouseout="if (this.style.borderColor !== 'var(--accent-purple)') this.style.borderColor='var(--border-color)';"
                         onclick="window.globalConfigMgr.selectCatalogModel('${m.name}')"
                         title="${safeNota}">
                        <div style="display: flex; justify-content: space-between; align-items: flex-start;">
                            <span style="font-weight: bold; color: #fff; font-size: 11px; font-family: monospace;">${m.name}</span>
                            ${badgeInstalled}
                        </div>
                        <div style="display: flex; gap: 6px; align-items: center; font-size: 10px; color: var(--text-muted);">
                            ${familiaBadge}
                            ${vramBadge ? `<span style="color: var(--accent-blue);">${vramBadge}</span>` : ''}
                        </div>
                        ${fuerte ? `<div style="font-size: 10px; color: var(--accent-yellow); text-overflow: ellipsis; overflow: hidden; white-space: nowrap;">🎯 ${fuerte}</div>` : ''}
                        <div style="display: flex; justify-content: flex-end; margin-top: 4px;">
                            <button type="button" class="ubuntu-btn" style="padding: 2px 8px; font-size: 10px; background: rgba(137,180,250,0.2); color: var(--accent-blue); border: 1px solid var(--accent-blue); border-radius: 4px; cursor: pointer;"
                                    onclick="event.stopPropagation(); window.globalConfigMgr.selectCatalogModel('${m.name}')">
                                ${isInstalled ? 'Seleccionar' : 'Descargar'}
                            </button>
                        </div>
                    </div>
                `;
            });
            grid.innerHTML = html;
        } catch (e) {
            grid.innerHTML = `<div style="color: var(--accent-red); font-size: 11px;">Error cargando catálogo: ${e.message}</div>`;
        }
    }

    filterCatalogGrid(query) {
        const q = (query || '').trim().toLowerCase();
        const cards = document.querySelectorAll('.cfg-catalog-card');
        cards.forEach(c => {
            const txt = (c.textContent || '').toLowerCase() + ' ' + (c.dataset.model || '').toLowerCase();
            c.style.display = (!q || txt.includes(q)) ? 'flex' : 'none';
        });
    }

    selectCatalogModel(modelName) {
        const inputTag = document.getElementById('cfg-pull-model-tag');
        if (inputTag) inputTag.value = modelName;

        const sel = document.getElementById('cfg-pull-preset-select');
        if (sel) {
            let found = false;
            for (let opt of sel.options) {
                if (opt.value === modelName) {
                    sel.value = modelName;
                    found = true;
                    break;
                }
            }
            if (!found) sel.value = '';
        }

        // Limpiar cualquier aviso o error previo para desbloquear la interfaz del usuario
        const progressBox = document.getElementById('cfg-pull-progress-box');
        if (progressBox) progressBox.style.display = 'none';
        const progressStatus = document.getElementById('cfg-pull-progress-status');
        if (progressStatus) progressStatus.innerText = '';

        // Resaltar tarjeta seleccionada en el catálogo
        const cards = document.querySelectorAll('.cfg-catalog-card');
        cards.forEach(card => {
            if (card.dataset.model === modelName) {
                card.style.borderColor = 'var(--accent-purple)';
                card.style.boxShadow = '0 0 10px rgba(203, 166, 247, 0.4)';
            } else {
                card.style.borderColor = 'var(--border-color)';
                card.style.boxShadow = 'none';
            }
        });

        this._syncTutorModel(modelName);
        this._showToastNotice(`Modelo '${modelName}' cargado y listo para descargar.`);
    }

    _syncTutorModel(modelName) {
        const tutor = document.getElementById('gcfg-tutor-model');
        if (!tutor || !modelName) return;
        let exists = false;
        for (let opt of tutor.options) {
            if (opt.value === modelName) {
                tutor.value = modelName;
                exists = true;
                break;
            }
        }
        if (!exists) {
            const opt = document.createElement('option');
            opt.value = modelName;
            opt.textContent = `${modelName} (del catálogo)`;
            tutor.appendChild(opt);
            tutor.value = modelName;
        }
    }

    /** Aplica al editor Monaco las preferencias de apariencia guardadas */
    applyEditorSettings() {
        const editor = window.editorMgr && window.editorMgr.editor;
        if (!editor) return;

        const fontSize = parseInt(localStorage.getItem('prig_editor_font_size') || '14', 10);
        const fontFamily = localStorage.getItem('prig_editor_font_family') || "'Fira Code', monospace";
        const tabSize = parseInt(localStorage.getItem('prig_editor_tab_size') || '4', 10);
        const theme = localStorage.getItem('prig_editor_theme') || 'prig-dark';

        editor.updateOptions({ fontSize, fontFamily, tabSize });
        if (typeof monaco !== 'undefined') {
            monaco.editor.setTheme(theme);
        }
    }
}

// Instancia global
window.globalConfigMgr = new GlobalConfigManager();

window.openGlobalConfigModal = function(tabName = 'ai') {
    if (window.globalConfigMgr) {
        window.globalConfigMgr.openModal(tabName);
    }
};

window.closeGlobalConfigModal = function() {
    if (window.globalConfigMgr) {
        window.globalConfigMgr.closeModal();
    }
};

/**
 * El modelo de cada tarea (Configuración global → Modelos por tarea).
 * `para(rol, respaldo)`: el elegido para ese rol, o `respaldo` si está en automático.
 */
window.PrigModelos = {
    ROLES: { codigo: 'modelo_codigo', explicar: 'modelo_explicar', autocompletar: 'modelo_autocompletar' },
    para(rol, respaldo = null) {
        const cfg = window.aiConfig || {};
        return String(cfg[this.ROLES[rol]] || '').trim() || respaldo || null;
    },
};

document.addEventListener('DOMContentLoaded', () => {
    if (!window.globalConfigMgr) return;
    window.globalConfigMgr.init();

    // Publicar la configuración de IA en cuanto arranca la app: otros módulos
    // (seguimiento, recorrido) leen window.aiConfig para elegir modelo.
    fetch('/api/ai/config')
        .then(res => res.ok ? res.json() : null)
        .then(cfg => { if (cfg) window.aiConfig = cfg; })
        .catch(() => {});

    // Monaco se crea de forma asíncrona; aplicar la apariencia cuando esté listo
    const applyWhenReady = (attempt = 0) => {
        if (window.editorMgr && window.editorMgr.editor) {
            window.globalConfigMgr.applyEditorSettings();
        } else if (attempt < 20) {
            setTimeout(() => applyWhenReady(attempt + 1), 250);
        }
    };
    applyWhenReady();
});
