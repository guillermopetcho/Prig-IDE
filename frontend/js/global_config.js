/**
 * GlobalConfigManager - Panel de Configuración Completa para Prig IDE
 * Maneja:
 * 1. Gestor de Descarga de Modelos Ollama (Pull) & Selección de Cuantizaciones (Q4_K_M, Q5_K_M, Q8_0, FP16).
 * 2. Monitoreo de Disponibilidad y Tabla de Modelos Instalados (con opción de Eliminación).
 * 3. Parámetros Críticos de Rendimiento (num_ctx, num_gpu layers, temperatura, repeat_penalty).
 * 4. Preferencias del Módulo Note, Editor Monaco y Permisos de Ejecución.
 */
const esc = (t) => String(t ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

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
        this.initApariencia();
        this.actualizarSelectorTopPerfil();
    }

    actualizarSelectorTopPerfil() {
        const sel = document.getElementById('cfg-top-perfil-select');
        if (!sel || !window.perfilesConfigMgr) return;
        const perfiles = window.perfilesConfigMgr.obtenerPerfiles();
        const activo = window.perfilesConfigMgr.obtenerPerfilActivo();

        sel.innerHTML = perfiles.map(p => `
            <option value="${p.id}" ${p.id === activo.id ? 'selected' : ''}>
                ${p.nombre} ${p.esPreset ? '★' : '👤'}
            </option>
        `).join('');
    }

    onTopPerfilChange(id) {
        if (!id || !window.perfilesConfigMgr) return;
        window.perfilesConfigMgr.activarPerfil(id);
        this.actualizarSelectorTopPerfil();
        if (this.activeTab === 'apariencia') {
            this.initApariencia();
        } else if (this.activeTab === 'perfiles') {
            this.initPerfiles();
        }
    }

    openModal(tabName = 'ai') {
        const modal = document.getElementById('modal-global-config');
        if (!modal) return;
        modal.style.display = 'flex';
        this.actualizarSelectorTopPerfil();
        this.switchTab(tabName);
        this.loadSettingsIntoUI();
        if (tabName === 'ai') {
            this.loadDetailedModels();
        } else if (tabName === 'perfiles') {
            this.initPerfiles();
        } else if (tabName === 'apariencia') {
            this.initApariencia();
        } else if (tabName === 'accesibilidad' || tabName === 'atajos') {
            this.renderAccesibilidad();
        }
    }

    closeModal() {
        if (this._telemetriaTimer) {
            clearInterval(this._telemetriaTimer);
            this._telemetriaTimer = null;
        }
        const modal = document.getElementById('modal-global-config');
        if (modal) modal.style.display = 'none';
    }

    switchTab(tabName) {
        if (this._telemetriaTimer) {
            clearInterval(this._telemetriaTimer);
            this._telemetriaTimer = null;
        }
        if (tabName === 'atajos') tabName = 'accesibilidad';
        this.activeTab = tabName;
        this.actualizarSelectorTopPerfil();
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
        } else if (tabName === 'perfiles') {
            this.initPerfiles();
        } else if (tabName === 'apariencia') {
            this.initApariencia();
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
                            ${m.motor === 'moe'
                                ? `<span style="color: var(--accent-green); background: rgba(166,227,161,0.15); padding: 2px 6px; border-radius: 4px; font-weight: bold; font-size: 10px;" title="Los expertos más usados van a la GPU y el resto a la RAM (Temperaturas → Motor MoE)">
                                    <i class="fa-solid fa-microchip"></i> Expertos en GPU</span>`
                                : this.badgeAjuste(m.name)}
                        </td>
                        <td style="padding: 8px 12px; text-align: right;">
                            ${m.motor === 'moe'
                                ? `<span style="color: var(--text-muted); font-size: 10px;" title="Lo sirve Prig con su propio motor; el modelo base es el de Ollama">Motor de Prig</span>`
                                : `<button onclick="window.globalConfigMgr.deleteModel('${m.name}')" class="ubuntu-btn" style="background: rgba(243,139,168,0.2); border: 1px solid var(--accent-red); color: var(--accent-red); padding: 3px 8px; border-radius: 4px; font-size: 11px; cursor: pointer;">
                                <i class="fa-solid fa-trash-can"></i> Eliminar
                            </button>`}
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
    // GESTIÓN DE PERFILES DE CONFIGURACIÓN
    // ==========================================

    initPerfiles() {
        const cont = document.getElementById('config-tab-perfiles');
        if (!cont || !window.perfilesConfigMgr) return;

        const pm = window.perfilesConfigMgr;
        const perfiles = pm.obtenerPerfiles();
        const activo = pm.obtenerPerfilActivo();

        const iconosDisponibles = [
            ['fa-sliders', 'General'],
            ['fa-cat', 'Gato / Pastel'],
            ['fa-bolt', 'Neón / Cyber'],
            ['fa-moon', 'Noche / Oscuro'],
            ['fa-snowflake', 'Ártico / Frío'],
            ['fa-terminal', 'Hacker / Matrix'],
            ['fa-border-all', 'Synthwave 3D'],
            ['fa-code', 'Programación'],
            ['fa-star', 'Estelar'],
            ['fa-tree', 'Naturaleza'],
            ['fa-palette', 'Artístico'],
            ['fa-battery-half', 'Ahorro Batería']
        ];

        cont.innerHTML = `
          <!-- Resumen del Perfil Activo -->
          <div style="background: linear-gradient(135deg, rgba(137,180,250,0.15) 0%, rgba(203,166,247,0.1) 100%); border: 1.5px solid var(--accent-blue); border-radius: 8px; padding: 14px; display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 12px; box-shadow: 0 4px 16px rgba(0,0,0,0.3);">
            <div style="display: flex; align-items: center; gap: 12px;">
              <div style="width: 44px; height: 44px; border-radius: 10px; background: rgba(137,180,250,0.25); display: flex; align-items: center; justify-content: center; font-size: 22px; color: var(--accent-blue);">
                <i class="fa-solid ${activo.icono || 'fa-sliders'}"></i>
              </div>
              <div>
                <div style="display: flex; align-items: center; gap: 8px;">
                  <span style="font-weight: 800; color: #fff; font-size: 14px;">${activo.nombre}</span>
                  <span style="background: var(--accent-green); color: #11111b; font-weight: 800; font-size: 10px; padding: 2px 6px; border-radius: 4px; text-transform: uppercase;">
                    <i class="fa-solid fa-circle-check"></i> Activo en Prig IDE
                  </span>
                  ${activo.esPreset ? '<span style="background: rgba(137,180,250,0.2); color: var(--accent-blue); font-weight: 700; font-size: 10px; padding: 2px 6px; border-radius: 4px;">★ Predeterminado</span>' : '<span style="background: rgba(203,166,247,0.2); color: var(--accent-purple); font-weight: 700; font-size: 10px; padding: 2px 6px; border-radius: 4px;">👤 Creado por Usuario</span>'}
                </div>
                <div style="font-size: 11px; color: var(--text-muted); margin-top: 3px;">${activo.desc || 'Perfil completo de personalización.'}</div>
              </div>
            </div>

            <!-- Botones de Acción de Perfiles -->
            <div style="display: flex; gap: 6px; flex-wrap: wrap;">
              <button class="tool-btn primary" id="cfg-prf-btn-nuevo" style="font-size: 11.5px; padding: 6px 14px; background: linear-gradient(135deg, var(--accent-blue), var(--accent-purple)); border: none; color: #fff; font-weight: 700; box-shadow: 0 0 10px rgba(137,180,250,0.3);">
                <i class="fa-solid fa-floppy-disk"></i> Guardar Estado Actual como Nuevo Perfil
              </button>
              <label class="tool-btn" style="cursor: pointer; font-size: 11.5px; padding: 6px 12px; display: inline-flex; align-items: center; gap: 6px;">
                <i class="fa-solid fa-file-import"></i> Importar (JSON)
                <input type="file" id="cfg-prf-file-importar" accept=".json" style="display: none;">
              </label>
              <button class="tool-btn" id="cfg-prf-btn-exportar-todos" style="font-size: 11.5px; padding: 6px 12px;" title="Exportar catálogo completo de perfiles">
                <i class="fa-solid fa-download"></i> Exportar Todos
              </button>
              <button class="tool-btn" id="cfg-prf-btn-reset-presets" style="font-size: 11.5px; padding: 6px 10px; color: var(--accent-red);" title="Restablecer perfiles de fábrica">
                <i class="fa-solid fa-rotate-left"></i>
              </button>
            </div>
          </div>

          <!-- Formulario de Guardado de Nuevo Perfil (Oculto por defecto) -->
          <div id="cfg-prf-form-crear" style="display: none; background: rgba(0,0,0,0.35); border: 1.5px solid var(--accent-purple); border-radius: 8px; padding: 14px; flex-direction: column; gap: 10px;">
            <div style="display: flex; align-items: center; justify-content: space-between;">
              <span style="font-weight: 700; color: #fff; font-size: 12px; display: flex; align-items: center; gap: 6px;">
                <i class="fa-solid fa-plus-circle" style="color: var(--accent-purple);"></i> Guardar Perfil Personalizado
              </span>
              <button class="tool-btn" id="cfg-prf-form-cerrar" style="padding: 2px 6px; font-size: 11px;"><i class="fa-solid fa-xmark"></i></button>
            </div>

            <div style="display: grid; grid-template-columns: 1fr auto; gap: 10px;">
              <div>
                <label style="font-weight: 600; color: #fff; font-size: 11px; display: block; margin-bottom: 3px;">Nombre del Perfil:</label>
                <input type="text" id="cfg-prf-input-nombre" placeholder="Ej: Mi Configuración Favorita" style="width: 100%; box-sizing: border-box; padding: 6px 10px; background: var(--bg-dark); border: 1px solid var(--border-color); color: #fff; border-radius: 6px; font-size: 11.5px;">
              </div>
              <div>
                <label style="font-weight: 600; color: #fff; font-size: 11px; display: block; margin-bottom: 3px;">Icono:</label>
                <select id="cfg-prf-select-icono" style="padding: 6px 10px; background: var(--bg-panel); border: 1px solid var(--border-color); color: #fff; border-radius: 6px; font-size: 11.5px;">
                  ${iconosDisponibles.map(([ico, nom]) => `<option value="${ico}">${nom}</option>`).join('')}
                </select>
              </div>
            </div>

            <div>
              <label style="font-weight: 600; color: #fff; font-size: 11px; display: block; margin-bottom: 3px;">Descripción (opcional):</label>
              <input type="text" id="cfg-prf-input-desc" placeholder="Detalles de este perfil de trabajo..." style="width: 100%; box-sizing: border-box; padding: 6px 10px; background: var(--bg-dark); border: 1px solid var(--border-color); color: #fff; border-radius: 6px; font-size: 11.5px;">
            </div>

            <div style="display: flex; justify-content: flex-end; gap: 8px; margin-top: 4px;">
              <button class="tool-btn" id="cfg-prf-form-cancelar" style="font-size: 11px; padding: 4px 12px;">Cancelar</button>
              <button class="tool-btn primary" id="cfg-prf-form-guardar" style="font-size: 11px; padding: 4px 16px; background: var(--accent-purple); color: #fff; font-weight: 700;"><i class="fa-solid fa-check"></i> Guardar y Activar Perfil</button>
            </div>
          </div>

          <!-- Catálogo de Todos los Perfiles -->
          <div style="display: flex; flex-direction: column; gap: 10px; margin-top: 4px;">
            <div style="font-size: 12px; font-weight: 700; color: #fff; display: flex; align-items: center; gap: 6px;">
              <i class="fa-solid fa-layer-group" style="color: var(--accent-blue);"></i> Catálogo de Perfiles Guardados (${perfiles.length})
            </div>

            <div style="display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 12px;">
              ${perfiles.map(p => {
                  const esActivo = p.id === activo.id;
                  const c = (p.apariencia && p.apariencia.colores) || {};
                  const mot = p.motorMovimiento || {};
                  const fg = (p.apariencia && p.apariencia.fondoGlobal) || {};

                  return `
                    <div class="cfg-prf-card" data-prf-id="${p.id}" style="background: ${esActivo ? 'rgba(137,180,250,0.14)' : 'rgba(0,0,0,0.25)'}; border: 1.5px solid ${esActivo ? 'var(--accent-blue)' : 'var(--border-color)'}; border-radius: 8px; padding: 14px; display: flex; flex-direction: column; gap: 10px; transition: all 0.2s ease; ${esActivo ? 'box-shadow: 0 0 14px rgba(137,180,250,0.25);' : ''}">
                      
                      <!-- Cabecera de la tarjeta -->
                      <div style="display: flex; align-items: flex-start; justify-content: space-between; gap: 8px;">
                        <div style="display: flex; align-items: center; gap: 10px;">
                          <div style="width: 34px; height: 34px; border-radius: 8px; background: ${esActivo ? 'var(--accent-blue)' : 'rgba(255,255,255,0.08)'}; color: ${esActivo ? '#11111b' : '#cdd6f4'}; display: flex; align-items: center; justify-content: center; font-size: 16px;">
                            <i class="fa-solid ${p.icono || 'fa-sliders'}"></i>
                          </div>
                          <div>
                            <div style="font-weight: 700; color: #fff; font-size: 12px;">${p.nombre}</div>
                            <div style="font-size: 10px; color: ${p.esPreset ? 'var(--accent-blue)' : 'var(--accent-purple)'}; font-weight: 600;">
                              ${p.esPreset ? '★ Preset del Sistema' : '👤 Perfil de Usuario'}
                            </div>
                          </div>
                        </div>

                        ${esActivo ? '<span style="background: var(--accent-green); color: #111; font-weight: 800; font-size: 9px; padding: 2px 6px; border-radius: 4px;">ACTIVO</span>' : ''}
                      </div>

                      <div style="font-size: 11px; color: var(--text-muted); line-height: 1.35; min-height: 30px;">
                        ${p.desc || 'Sin descripción adicional.'}
                      </div>

                      <!-- Muestra de Colores y Ajustes del Perfil -->
                      <div style="display: flex; align-items: center; justify-content: space-between; background: rgba(0,0,0,0.3); padding: 6px 10px; border-radius: 6px; font-size: 10.5px;">
                        <div style="display: flex; gap: 4px;" title="Paleta de colores del perfil">
                          <span style="width: 12px; height: 12px; border-radius: 50%; background: ${c.bg_dark || '#1e1e2e'}; border: 1px solid rgba(255,255,255,0.2);"></span>
                          <span style="width: 12px; height: 12px; border-radius: 50%; background: ${c.accent_blue || '#89b4fa'};"></span>
                          <span style="width: 12px; height: 12px; border-radius: 50%; background: ${c.accent_purple || '#cba6f7'};"></span>
                          <span style="width: 12px; height: 12px; border-radius: 50%; background: ${c.accent_green || '#a6e3a1'};"></span>
                        </div>

                        <div style="color: var(--text-muted); font-family: monospace;">
                          ${fg.tipo === 'movimiento' ? `<i class="fa-solid fa-wand-magic-sparkles" style="color: var(--accent-blue);"></i> ${mot.efecto || 'particulas'} (${mot.fpsLimite || 60} FPS)` : (fg.tipo === 'imagen' ? '📷 Fotografía' : '🎨 Sólido')}
                        </div>
                      </div>

                      <!-- Botones de Acción -->
                      <div style="display: flex; gap: 6px; margin-top: 2px; flex-wrap: wrap;">
                        <button class="tool-btn ${esActivo ? 'primary' : ''} btn-activar-prf" data-id="${p.id}" style="flex: 1; font-size: 11px; padding: 4px 8px; justify-content: center;">
                          ${esActivo ? '<i class="fa-solid fa-check"></i> Activo' : '<i class="fa-solid fa-play"></i> Activar'}
                        </button>
                        <button class="tool-btn btn-duplicar-prf" data-id="${p.id}" style="font-size: 11px; padding: 4px 8px;" title="Duplicar este perfil">
                          <i class="fa-solid fa-copy"></i>
                        </button>
                        <button class="tool-btn btn-sobrescribir-prf" data-id="${p.id}" style="font-size: 11px; padding: 4px 8px;" title="Sobrescribir con la configuración actual del entorno">
                          <i class="fa-solid fa-arrow-down-to-bracket"></i>
                        </button>
                        <button class="tool-btn btn-exportar-prf" data-id="${p.id}" style="font-size: 11px; padding: 4px 8px;" title="Exportar perfil como archivo JSON">
                          <i class="fa-solid fa-download"></i>
                        </button>
                        ${!p.esPreset ? `
                          <button class="tool-btn btn-eliminar-prf" data-id="${p.id}" style="font-size: 11px; padding: 4px 8px; color: var(--accent-red); border-color: rgba(243,139,168,0.3);" title="Eliminar este perfil">
                            <i class="fa-solid fa-trash"></i>
                          </button>
                        ` : ''}
                      </div>

                    </div>
                  `;
              }).join('')}
            </div>
          </div>
        `;

        // Eventos del Formulario de Creación de Perfil
        const btnNuevo = document.getElementById('cfg-prf-btn-nuevo');
        const formCrear = document.getElementById('cfg-prf-form-crear');
        const formCerrar = document.getElementById('cfg-prf-form-cerrar');
        const formCancelar = document.getElementById('cfg-prf-form-cancelar');
        const formGuardar = document.getElementById('cfg-prf-form-guardar');
        const inputNombre = document.getElementById('cfg-prf-input-nombre');
        const selectIcono = document.getElementById('cfg-prf-select-icono');
        const inputDesc = document.getElementById('cfg-prf-input-desc');

        if (btnNuevo && formCrear) {
            btnNuevo.onclick = () => {
                formCrear.style.display = 'flex';
                if (inputNombre) {
                    inputNombre.value = `Mi Perfil ${new Date().toLocaleDateString()}`;
                    inputNombre.focus();
                }
            };
        }

        const ocultarForm = () => {
            if (formCrear) formCrear.style.display = 'none';
        };

        if (formCerrar) formCerrar.onclick = ocultarForm;
        if (formCancelar) formCancelar.onclick = ocultarForm;

        if (formGuardar && inputNombre) {
            formGuardar.onclick = () => {
                const nom = inputNombre.value.trim();
                if (!nom) {
                    alert('Por favor ingresa un nombre para el perfil.');
                    return;
                }
                const ico = selectIcono ? selectIcono.value : 'fa-sliders';
                const desc = inputDesc ? inputDesc.value.trim() : '';
                pm.guardarPerfilActual(nom, ico, desc);
                this.actualizarSelectorTopPerfil();
                this.initPerfiles();
            };
        }

        // Eventos de Activar Perfil
        cont.querySelectorAll('.btn-activar-prf').forEach(btn => {
            btn.onclick = () => {
                const id = btn.dataset.id;
                pm.activarPerfil(id);
                this.actualizarSelectorTopPerfil();
                this.initPerfiles();
            };
        });

        // Eventos de Duplicar Perfil
        cont.querySelectorAll('.btn-duplicar-prf').forEach(btn => {
            btn.onclick = () => {
                const id = btn.dataset.id;
                pm.duplicarPerfil(id);
                this.actualizarSelectorTopPerfil();
                this.initPerfiles();
            };
        });

        // Eventos de Sobrescribir Perfil
        cont.querySelectorAll('.btn-sobrescribir-prf').forEach(btn => {
            btn.onclick = () => {
                const id = btn.dataset.id;
                const p = perfiles.find(item => item.id === id);
                if (!p) return;
                if (confirm(`¿Deseas sobrescribir el perfil "${p.nombre}" con toda la configuración visual actual de tu IDE?`)) {
                    pm.guardarPerfilActual(p.nombre, p.icono, p.desc, p.id);
                    this.actualizarSelectorTopPerfil();
                    this.initPerfiles();
                }
            };
        });

        // Eventos de Exportar Perfil Individual
        cont.querySelectorAll('.btn-exportar-prf').forEach(btn => {
            btn.onclick = () => {
                pm.exportarJSON(btn.dataset.id);
            };
        });

        // Eventos de Eliminar Perfil
        cont.querySelectorAll('.btn-eliminar-prf').forEach(btn => {
            btn.onclick = () => {
                const id = btn.dataset.id;
                const p = perfiles.find(item => item.id === id);
                if (!p) return;
                if (confirm(`¿Estás seguro de que deseas eliminar el perfil "${p.nombre}"?`)) {
                    pm.eliminarPerfil(id);
                    this.actualizarSelectorTopPerfil();
                    this.initPerfiles();
                }
            };
        });

        // Exportar todos
        const btnExpTodos = document.getElementById('cfg-prf-btn-exportar-todos');
        if (btnExpTodos) {
            btnExpTodos.onclick = () => pm.exportarJSON();
        }

        // Importar archivo
        const fileImp = document.getElementById('cfg-prf-file-importar');
        if (fileImp) {
            fileImp.onchange = () => {
                const file = fileImp.files[0];
                if (!file) return;
                const reader = new FileReader();
                reader.onload = (e) => {
                    const res = pm.importarJSON(e.target.result);
                    if (res.exito) {
                        alert(res.mensaje || 'Perfiles importados exitosamente.');
                        this.actualizarSelectorTopPerfil();
                        this.initPerfiles();
                    } else {
                        alert('Error al importar perfil: ' + (res.error || 'Archivo inválido'));
                    }
                };
                reader.readAsText(file);
            };
        }

        // Restablecer presets
        const btnResetPresets = document.getElementById('cfg-prf-btn-reset-presets');
        if (btnResetPresets) {
            btnResetPresets.onclick = () => {
                if (confirm('¿Restablecer los perfiles predeterminados del sistema? Los perfiles personalizados se conservarán.')) {
                    pm.restablecerPresets();
                    this.actualizarSelectorTopPerfil();
                    this.initPerfiles();
                }
            };
        }
    }

    // ==========================================
    // APARIENCIA Y PERSONALIZACIÓN DE COLORES Y FONDOS
    // ==========================================

    initApariencia(subTab = null) {
        const cont = document.getElementById('config-tab-apariencia');
        if (!cont) return;
        if (subTab) this.aparienciaSubTab = subTab;
        if (!this.aparienciaSubTab) this.aparienciaSubTab = 'colores';

        const ap = window.aparienciaMgr;
        if (!ap) return;

        cont.innerHTML = `
          <!-- Sub-navegación de Apariencia -->
          <div style="display: flex; gap: 6px; border-bottom: 1px solid var(--border-color); padding-bottom: 10px; flex-wrap: wrap;">
            <button class="tool-btn ${this.aparienciaSubTab === 'colores' ? 'primary' : ''}" id="ap-subtab-btn-colores" style="font-size: 11.5px; padding: 6px 14px; border-radius: 6px;">
              <i class="fa-solid fa-palette"></i> 1. Colores y Temas
            </button>
            <button class="tool-btn ${this.aparienciaSubTab === 'fondo-global' ? 'primary' : ''}" id="ap-subtab-btn-fondo" style="font-size: 11.5px; padding: 6px 14px; border-radius: 6px;">
              <i class="fa-solid fa-image"></i> 2. Fondo Global del Programa
            </button>
            <button class="tool-btn ${this.aparienciaSubTab === 'secciones' ? 'primary' : ''}" id="ap-subtab-btn-secciones" style="font-size: 11.5px; padding: 6px 14px; border-radius: 6px;">
              <i class="fa-solid fa-layer-group"></i> 3. Fondos por Sección
            </button>
            <button class="tool-btn ${this.aparienciaSubTab === 'efectos' ? 'primary' : ''}" id="ap-subtab-btn-efectos" style="font-size: 11.5px; padding: 6px 14px; border-radius: 6px;">
              <i class="fa-solid fa-sliders"></i> 4. Efectos y Respaldo
            </button>
            <button class="tool-btn ${this.aparienciaSubTab === 'sintaxis' ? 'primary' : ''}" id="ap-subtab-btn-sintaxis" style="font-size: 11.5px; padding: 6px 14px; border-radius: 6px; border-color: rgba(203,166,247,0.4);">
              <i class="fa-solid fa-code" style="color: var(--accent-purple);"></i> 5. Sintaxis y Tokens Raros
            </button>
          </div>

          <!-- Contenedor del contenido del sub-tab activo -->
          <div id="ap-subtab-body" style="display: flex; flex-direction: column; gap: 14px; margin-top: 4px;"></div>
        `;

        const btnColores = document.getElementById('ap-subtab-btn-colores');
        const btnFondo = document.getElementById('ap-subtab-btn-fondo');
        const btnSecciones = document.getElementById('ap-subtab-btn-secciones');
        const btnEfectos = document.getElementById('ap-subtab-btn-efectos');
        const btnSintaxis = document.getElementById('ap-subtab-btn-sintaxis');

        if (btnColores) btnColores.onclick = () => this.initApariencia('colores');
        if (btnFondo) btnFondo.onclick = () => this.initApariencia('fondo-global');
        if (btnSecciones) btnSecciones.onclick = () => this.initApariencia('secciones');
        if (btnEfectos) btnEfectos.onclick = () => this.initApariencia('efectos');
        if (btnSintaxis) btnSintaxis.onclick = () => this.initApariencia('sintaxis');

        const body = document.getElementById('ap-subtab-body');
        if (!body) return;

        if (this.aparienciaSubTab === 'colores') {
            this._renderSubTabColores(body, ap);
        } else if (this.aparienciaSubTab === 'fondo-global') {
            this._renderSubTabFondoGlobal(body, ap);
        } else if (this.aparienciaSubTab === 'secciones') {
            this._renderSubTabSecciones(body, ap);
        } else if (this.aparienciaSubTab === 'efectos') {
            this._renderSubTabEfectos(body, ap);
        } else if (this.aparienciaSubTab === 'sintaxis') {
            this._renderSubTabSintaxis(body, ap);
        }
    }

    _renderSubTabColores(container, ap) {
        const est = ap.estado;
        const colores = est.colores || {};
        const temas = window.TEMAS_PREDEFINIDOS || {};

        const definicionColores = [
            { key: 'bg_dark', label: 'Fondo Oscuro Principal', desc: 'Fondo general del IDE y contenedor principal', css: '--bg-dark' },
            { key: 'bg_panel', label: 'Fondo de Paneles y Barras', desc: 'Barras laterales, encabezados y menús', css: '--bg-panel' },
            { key: 'bg_editor', label: 'Fondo del Editor de Código', desc: 'Área de escritura en Monaco Editor y Notebooks', css: '--bg-editor' },
            { key: 'bg_hover', label: 'Fondo Hover / Selección', desc: 'Resaltado de botones y elementos al pasar cursor', css: '--bg-hover' },
            { key: 'border_color', label: 'Color de Bordes y Divisores', desc: 'Líneas divisorias y marcos de paneles', css: '--border-color' },
            { key: 'text_main', label: 'Texto Principal', desc: 'Tipografía general, código y títulos', css: '--text-main' },
            { key: 'text_muted', label: 'Texto Secundario / Ayuda', desc: 'Comentarios, fechas e información secundaria', css: '--text-muted' },
            { key: 'accent_blue', label: 'Acento Azul (Interactivo)', desc: 'Botones primarios, enlaces y selecciones activas', css: '--accent-blue' },
            { key: 'accent_purple', label: 'Acento Morado (IA & Tutor)', desc: 'Tutor Prig, botones IA y razonamiento', css: '--accent-purple' },
            { key: 'accent_green', label: 'Acento Verde (Éxito & Pruebas)', desc: 'Pruebas aprobadas, completados y terminal exitoso', css: '--accent-green' },
            { key: 'accent_red', label: 'Acento Rojo (Error & Peligro)', desc: 'Errores, fallos en pruebas y botones de eliminar', css: '--accent-red' },
            { key: 'accent_yellow', label: 'Acento Amarillo (Avisos & Pistas)', desc: 'Pistas, advertencias y favoritos', css: '--accent-yellow' }
        ];

        container.innerHTML = `
          <!-- Galería de Temas Predefinidos -->
          <div style="background: rgba(0,0,0,0.2); border: 1px solid var(--border-color); border-radius: 8px; padding: 12px;">
            <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px;">
              <span style="font-weight: 700; color: #fff; font-size: 12px; display: flex; align-items: center; gap: 6px;">
                <i class="fa-solid fa-swatchbook" style="color: var(--accent-blue);"></i> Temas Predefinidos de un Clic
              </span>
              <span style="font-size: 11px; color: var(--text-muted);">Haz clic en cualquier tema para aplicarlo al instante</span>
            </div>
            <div style="display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); gap: 8px;">
              ${Object.entries(temas).map(([k, t]) => {
                  const activo = est.temaActivo === k;
                  const c = t.colores;
                  return `
                    <div class="ap-card-tema" data-tema="${k}" style="background: ${c.bg_panel}; border: 1.5px solid ${activo ? 'var(--accent-blue)' : 'var(--border-color)'}; border-radius: 8px; padding: 8px 10px; cursor: pointer; transition: all 0.2s ease; ${activo ? 'box-shadow: 0 0 10px rgba(137,180,250,0.25);' : ''}">
                      <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 6px;">
                        <span style="font-weight: 600; font-size: 11px; color: ${c.text_main}; display: flex; align-items: center; gap: 5px;">
                          <i class="fa-solid ${t.icono || 'fa-palette'}" style="color: ${c.accent_blue};"></i> ${t.nombre.split('(')[0].trim()}
                        </span>
                        ${activo ? '<i class="fa-solid fa-circle-check" style="color: var(--accent-blue); font-size: 11px;"></i>' : ''}
                      </div>
                      <div style="display: flex; gap: 4px; align-items: center;">
                        <span style="width: 14px; height: 14px; border-radius: 50%; background: ${c.bg_dark}; border: 1px solid rgba(255,255,255,0.2);" title="Fondo general"></span>
                        <span style="width: 14px; height: 14px; border-radius: 50%; background: ${c.accent_blue}; border: 1px solid rgba(255,255,255,0.2);" title="Acento Azul"></span>
                        <span style="width: 14px; height: 14px; border-radius: 50%; background: ${c.accent_purple}; border: 1px solid rgba(255,255,255,0.2);" title="Acento Morado"></span>
                        <span style="width: 14px; height: 14px; border-radius: 50%; background: ${c.accent_green}; border: 1px solid rgba(255,255,255,0.2);" title="Acento Verde"></span>
                        <span style="width: 14px; height: 14px; border-radius: 50%; background: ${c.accent_yellow}; border: 1px solid rgba(255,255,255,0.2);" title="Acento Amarillo"></span>
                      </div>
                    </div>
                  `;
              }).join('')}
            </div>
          </div>

          <!-- Editor Completo de Paleta de Colores Individuales -->
          <div>
            <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px;">
              <span style="font-weight: 700; color: #fff; font-size: 12px; display: flex; align-items: center; gap: 6px;">
                <i class="fa-solid fa-eye-dropper" style="color: var(--accent-purple);"></i> Modificar Colores Individuales de la Interfaz
              </span>
              <span style="font-size: 11px; color: var(--text-muted);">Puedes seleccionar con el cuentagotas o escribir el código hexadecimal</span>
            </div>

            <div style="display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 8px;">
              ${definicionColores.map(item => {
                  const val = colores[item.key] || '#1e1e2e';
                  return `
                    <div style="display: flex; align-items: center; gap: 10px; background: rgba(0,0,0,0.25); border: 1px solid var(--border-color); border-radius: 8px; padding: 7px 10px;">
                      <input type="color" id="cfg-color-picker-${item.key}" value="${val.length === 7 ? val : val.slice(0, 7)}" style="width: 34px; height: 34px; border: none; border-radius: 6px; cursor: pointer; background: transparent; padding: 0;">
                      <div style="flex: 1; min-width: 0;">
                        <div style="font-weight: 600; color: #fff; font-size: 11.5px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">${item.label}</div>
                        <div style="font-size: 10px; color: var(--text-muted); font-family: monospace;">${item.css}</div>
                      </div>
                      <input type="text" id="cfg-color-hex-${item.key}" value="${val}" style="width: 76px; background: var(--bg-dark); border: 1px solid var(--border-color); color: var(--text-main); border-radius: 5px; padding: 4px 6px; font-family: 'Fira Code', monospace; font-size: 11px; text-transform: uppercase;">
                    </div>
                  `;
              }).join('')}
            </div>
          </div>
        `;

        // Conectar eventos en tarjetas de temas
        container.querySelectorAll('.ap-card-tema').forEach(card => {
            card.onclick = () => {
                ap.setTema(card.dataset.tema);
                this.initApariencia('colores');
            };
        });

        // Conectar pickers y text inputs de colores
        definicionColores.forEach(item => {
            const picker = document.getElementById(`cfg-color-picker-${item.key}`);
            const hexInp = document.getElementById(`cfg-color-hex-${item.key}`);

            if (picker && hexInp) {
                picker.oninput = () => {
                    const val = picker.value;
                    hexInp.value = val.toUpperCase();
                    ap.setColor(item.key, val);
                };

                hexInp.onchange = () => {
                    let val = hexInp.value.trim();
                    if (!val.startsWith('#')) val = '#' + val;
                    if (/^#[0-9A-Fa-f]{6}$/.test(val)) {
                        picker.value = val;
                        ap.setColor(item.key, val);
                    }
                };
            }
        });
    }

    _renderSubTabFondoGlobal(container, ap) {
        const est = ap.estado;
        const fg = est.fondoGlobal || {};
        const gradientes = window.GRADIENTES_PREDEFINIDOS || [];
        const efectosMov = window.EFECTOS_MOVIMIENTO_GLOBAL || [];
        const ejemplosCod = window.EJEMPLOS_CODIGO_FONDO || {};

        // Mapear tipo activo para el botón principal
        let modoActivo = fg.tipo || 'defecto';
        if (modoActivo === 'codigo_js' || modoActivo === 'codigo_css') {
            modoActivo = 'codigo';
        }

        const tipoCodigoActual = fg.tipo === 'codigo_css' ? 'codigo_css' : 'codigo_js';

        const paletaRapida = ['#181825', '#0d1117', '#000000', '#0f051d', '#0a1913', '#002b36', '#1a1b26', '#141414'];

        container.innerHTML = `
          <div style="background: rgba(0,0,0,0.2); border: 1px solid var(--border-color); border-radius: 8px; padding: 12px; display: flex; flex-direction: column; gap: 12px;">
            <div style="display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 8px;">
              <span style="font-weight: 700; color: #fff; font-size: 12px; display: flex; align-items: center; gap: 6px;">
                <i class="fa-solid fa-panorama" style="color: var(--accent-green);"></i> Tipo de Fondo Global del Programa
              </span>
              <div style="display: flex; gap: 4px; flex-wrap: wrap;">
                ${[
                    ['color', '🎨 Color Estático', 'fa-palette'],
                    ['imagen', '📷 Fotografía / Imagen', 'fa-image'],
                    ['movimiento', '✨ Con Movimiento', 'fa-wand-magic-sparkles'],
                    ['codigo', '💻 Código en Vivo', 'fa-code'],
                    ['gradiente', '🌈 Degradados', 'fa-brush'],
                    ['defecto', '⚙️ Tema Base', 'fa-circle-dot']
                ].map(([t, nom, ico]) => `
                    <button class="tool-btn ${modoActivo === t ? 'primary' : ''}" data-fg-modo="${t}" style="font-size: 11px; padding: 4px 10px; display: inline-flex; align-items: center; gap: 5px;">
                      <i class="fa-solid ${ico}"></i> ${nom}
                    </button>
                  `).join('')}
              </div>
            </div>

            <!-- 1. COLOR ESTÁTICO (SÓLIDO) -->
            ${modoActivo === 'color' ? `
              <div style="display: flex; flex-direction: column; gap: 10px; background: rgba(0,0,0,0.3); padding: 12px; border-radius: 8px; border: 1px solid var(--border-color);">
                <div style="display: flex; align-items: center; gap: 12px;">
                  <input type="color" id="cfg-fg-color-picker" value="${(fg.color || '#181825').slice(0, 7)}" style="width: 44px; height: 38px; border: none; border-radius: 6px; cursor: pointer; background: transparent;">
                  <div style="flex: 1;">
                    <div style="font-weight: 700; color: #fff; font-size: 12px;">Color Sólido Personalizado</div>
                    <div style="font-size: 11px; color: var(--text-muted);">Aplica un tono plano y limpio en todo el fondo del entorno</div>
                  </div>
                  <input type="text" id="cfg-fg-color-hex" value="${fg.color || '#181825'}" style="width: 95px; background: var(--bg-dark); border: 1px solid var(--border-color); color: var(--text-main); border-radius: 5px; padding: 6px 8px; font-family: 'Fira Code', monospace; font-size: 11.5px; text-transform: uppercase;">
                </div>
                
                <div style="border-top: 1px solid rgba(255,255,255,0.07); padding-top: 8px;">
                  <div style="font-size: 11px; color: var(--text-muted); margin-bottom: 6px; font-weight: 600;">Tonos Rápidos Recomendados:</div>
                  <div style="display: flex; gap: 6px; flex-wrap: wrap;">
                    ${paletaRapida.map(c => `
                      <button class="cfg-fg-color-chip" data-color="${c}" style="background: ${c}; border: 1.5px solid ${fg.color === c ? 'var(--accent-blue)' : 'rgba(255,255,255,0.2)'}; width: 28px; height: 28px; border-radius: 6px; cursor: pointer; transition: transform 0.15s ease;" title="${c}"></button>
                    `).join('')}
                  </div>
                </div>
              </div>
            ` : ''}

            <!-- 2. FOTOGRAFÍA / IMAGEN -->
            ${modoActivo === 'imagen' ? `
              <div style="display: flex; flex-direction: column; gap: 12px; background: rgba(0,0,0,0.3); padding: 12px; border-radius: 8px; border: 1px solid var(--border-color);">
                <div style="display: flex; gap: 10px; align-items: center; flex-wrap: wrap;">
                  <label class="tool-btn primary" style="cursor: pointer; display: inline-flex; align-items: center; gap: 6px; font-size: 11.5px; padding: 6px 14px;">
                    <i class="fa-solid fa-upload"></i> Subir fotografía local
                    <input type="file" id="cfg-fg-archivo" accept="image/*" style="display: none;">
                  </label>
                  <span style="font-size: 11px; color: var(--text-muted);">o ingresa un enlace web:</span>
                  <input type="text" id="cfg-fg-imagen-url" value="${esc(fg.imagenUrl && !fg.imagenUrl.startsWith('data:') ? fg.imagenUrl : '')}" placeholder="https://ejemplo.com/fondo.jpg" style="flex: 1; min-width: 200px; padding: 6px 10px; background: var(--bg-dark); border: 1px solid var(--border-color); color: #fff; border-radius: 6px; font-size: 11.5px;">
                  <button class="tool-btn" id="cfg-fg-aplicar-url" style="padding: 6px 12px;"><i class="fa-solid fa-check"></i> Aplicar</button>
                  ${fg.imagenUrl ? '<button class="tool-btn" id="cfg-fg-quitar-img" style="background: rgba(243,139,168,0.15); color: var(--accent-red); border-color: rgba(243,139,168,0.4);"><i class="fa-solid fa-trash"></i> Quitar fotografía</button>' : ''}
                </div>

                ${fg.imagenUrl ? `
                  <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 12px; border-top: 1px solid rgba(255,255,255,0.08); padding-top: 10px;">
                    <div>
                      <label style="font-weight: 600; color: #fff; font-size: 11px; display: block; margin-bottom: 4px;">Ajuste de la Fotografía:</label>
                      <select id="cfg-fg-ajuste" style="width: 100%; padding: 6px; background: var(--bg-panel); border: 1px solid var(--border-color); color: #fff; border-radius: 6px; font-size: 11.5px;">
                        <option value="cover" ${fg.imagenAjuste === 'cover' ? 'selected' : ''}>Cubrir pantalla completa (Cover)</option>
                        <option value="contain" ${fg.imagenAjuste === 'contain' ? 'selected' : ''}>Ajustar proporción (Contain)</option>
                        <option value="repeat" ${fg.imagenAjuste === 'repeat' ? 'selected' : ''}>Mosaico / Repetir textura</option>
                        <option value="center" ${fg.imagenAjuste === 'center' ? 'selected' : ''}>Centrado original</option>
                      </select>
                    </div>

                    <div>
                      <label style="font-weight: 600; color: #fff; font-size: 11px; display: block; margin-bottom: 4px;">Capa de Oscurecimiento: <span id="cfg-fg-overlay-val">${Math.round((fg.overlayAlfa !== undefined ? fg.overlayAlfa : 0.35) * 100)}%</span></label>
                      <input type="range" id="cfg-fg-overlay" min="0" max="0.9" step="0.05" value="${fg.overlayAlfa !== undefined ? fg.overlayAlfa : 0.35}" style="width: 100%; accent-color: var(--accent-blue);">
                      <div style="font-size: 10.5px; color: var(--text-muted); margin-top: 2px;">Permite que el código y texto sigan siendo 100% legibles</div>
                    </div>
                  </div>
                ` : '<div class="des-ayuda" style="text-align: center; padding: 12px;">Sube una imagen o pega una URL para activar el fondo fotográfico.</div>'}
              </div>
            ` : ''}

            <!-- 3. FONDOS CON MOVIMIENTO Y MOTOR DE ALTO RENDIMIENTO -->
            ${modoActivo === 'movimiento' ? `
              <div style="display: flex; flex-direction: column; gap: 14px;">
                <!-- Telemetría y Controles de Eficiencia del Motor -->
                <div style="background: rgba(0,0,0,0.35); border: 1.5px solid rgba(137,180,250,0.3); border-radius: 8px; padding: 12px; display: flex; flex-direction: column; gap: 10px;">
                  <div style="display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 8px; border-bottom: 1px solid rgba(255,255,255,0.08); padding-bottom: 8px;">
                    <div style="display: flex; align-items: center; gap: 8px;">
                      <i class="fa-solid fa-gauge-high" style="color: var(--accent-green); font-size: 15px;"></i>
                      <div>
                        <span style="font-weight: 700; color: #fff; font-size: 12px;">Motor de Movimiento de Alto Rendimiento (Zero-Lag)</span>
                        <div style="font-size: 10.5px; color: var(--text-muted);">Optimizado para animaciones ultra fluidas sin consumir CPU del IDE</div>
                      </div>
                    </div>
                    
                    <!-- HUD Telemetría en Vivo -->
                    <div style="display: flex; align-items: center; gap: 10px; background: rgba(0,0,0,0.4); border: 1px solid var(--border-color); border-radius: 6px; padding: 4px 10px; font-family: 'Fira Code', monospace; font-size: 11px;">
                      <span title="Tasa de cuadros por segundo"><i class="fa-solid fa-tv" style="color: var(--accent-blue);"></i> <b id="cfg-mot-fps-val" style="color: var(--accent-green);">${window.motorMovimiento ? window.motorMovimiento.telemetria.fps : 60} FPS</b></span>
                      <span style="color: rgba(255,255,255,0.2);">|</span>
                      <span title="Tiempo de renderizado de cada fotograma"><i class="fa-solid fa-stopwatch" style="color: var(--accent-yellow);"></i> <b id="cfg-mot-ms-val" style="color: #fff;">${window.motorMovimiento ? window.motorMovimiento.telemetria.frameTimeMs : 0.8} ms</b></span>
                      <span style="color: rgba(255,255,255,0.2);">|</span>
                      <span title="Estado del bucle"><i class="fa-solid fa-circle" style="color: var(--accent-green); font-size: 8px;"></i> <span id="cfg-mot-estado-val" style="color: var(--text-muted);">${window.motorMovimiento ? window.motorMovimiento.telemetria.estado : 'activo'}</span></span>
                    </div>
                  </div>

                  <!-- Ajustes de Rendimiento y Ahorro -->
                  <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 10px; font-size: 11px;">
                    <div>
                      <label style="font-weight: 600; color: #fff; display: block; margin-bottom: 4px;">⚡ Límite de FPS:</label>
                      <select id="cfg-mot-fps-limite" style="width: 100%; padding: 5px 8px; background: var(--bg-panel); border: 1px solid var(--border-color); color: #fff; border-radius: 6px;">
                        <option value="30" ${window.motorMovimiento && window.motorMovimiento.config.fpsLimite === 30 ? 'selected' : ''}>30 FPS (Modo Ahorro / Batería)</option>
                        <option value="45" ${window.motorMovimiento && window.motorMovimiento.config.fpsLimite === 45 ? 'selected' : ''}>45 FPS (Equilibrado)</option>
                        <option value="60" ${!window.motorMovimiento || window.motorMovimiento.config.fpsLimite === 60 ? 'selected' : ''}>60 FPS (Fluido - Recomendado)</option>
                        <option value="0" ${window.motorMovimiento && window.motorMovimiento.config.fpsLimite === 0 ? 'selected' : ''}>Ilimitado (144Hz+ Monitor)</option>
                      </select>
                    </div>

                    <div>
                      <label style="font-weight: 600; color: #fff; display: block; margin-bottom: 4px;">🎯 Escala de Render (Downsampling):</label>
                      <select id="cfg-mot-escala-render" style="width: 100%; padding: 5px 8px; background: var(--bg-panel); border: 1px solid var(--border-color); color: #fff; border-radius: 6px;">
                        <option value="0.5" ${window.motorMovimiento && window.motorMovimiento.config.escalaRender === 0.5 ? 'selected' : ''}>50% (Ultra Ligero / GPU Básica)</option>
                        <option value="0.75" ${!window.motorMovimiento || window.motorMovimiento.config.escalaRender === 0.75 ? 'selected' : ''}>75% (Equilibrado Inteligente)</option>
                        <option value="1.0" ${window.motorMovimiento && window.motorMovimiento.config.escalaRender === 1.0 ? 'selected' : ''}>100% (Máxima Nitidez Nativa)</option>
                      </select>
                    </div>

                    <div>
                      <label style="font-weight: 600; color: #fff; display: block; margin-bottom: 4px;">🌌 Densidad de Entidades:</label>
                      <select id="cfg-mot-densidad" style="width: 100%; padding: 5px 8px; background: var(--bg-panel); border: 1px solid var(--border-color); color: #fff; border-radius: 6px;">
                        <option value="baja" ${window.motorMovimiento && window.motorMovimiento.config.densidad === 'baja' ? 'selected' : ''}>Baja (0.5x)</option>
                        <option value="media" ${!window.motorMovimiento || window.motorMovimiento.config.densidad === 'media' ? 'selected' : ''}>Media (1.0x - Normal)</option>
                        <option value="alta" ${window.motorMovimiento && window.motorMovimiento.config.densidad === 'alta' ? 'selected' : ''}>Alta (1.5x)</option>
                        <option value="ultra" ${window.motorMovimiento && window.motorMovimiento.config.densidad === 'ultra' ? 'selected' : ''}>Ultra (2.2x)</option>
                      </select>
                    </div>

                    <div>
                      <label style="font-weight: 600; color: #fff; display: block; margin-bottom: 4px;">⏩ Velocidad: <span id="cfg-mot-vel-val">${window.motorMovimiento ? window.motorMovimiento.config.velocidad : 1.0}x</span></label>
                      <input type="range" id="cfg-mot-velocidad" min="0.2" max="3.0" step="0.1" value="${window.motorMovimiento ? window.motorMovimiento.config.velocidad : 1.0}" style="width: 100%; accent-color: var(--accent-blue);">
                    </div>
                  </div>

                  <div style="display: flex; gap: 16px; align-items: center; flex-wrap: wrap; border-top: 1px solid rgba(255,255,255,0.06); padding-top: 8px;">
                    <label style="display: inline-flex; align-items: center; gap: 6px; cursor: pointer; color: #cdd6f4; font-size: 11px;">
                      <input type="checkbox" id="cfg-mot-mouse" ${!window.motorMovimiento || window.motorMovimiento.config.interaccionMouse ? 'checked' : ''} style="accent-color: var(--accent-purple);">
                      <span><i class="fa-solid fa-arrow-pointer" style="color: var(--accent-purple);"></i> Reacción física al cursor del mouse</span>
                    </label>

                    <label style="display: inline-flex; align-items: center; gap: 6px; cursor: pointer; color: #cdd6f4; font-size: 11px;">
                      <input type="checkbox" id="cfg-mot-pausa-fondo" ${!window.motorMovimiento || window.motorMovimiento.config.pausarEnSegundoPlano ? 'checked' : ''} style="accent-color: var(--accent-green);">
                      <span><i class="fa-solid fa-battery-half" style="color: var(--accent-green);"></i> Suspender motor cuando la pestaña esté inactiva</span>
                    </label>
                  </div>
                </div>

                <!-- Catálogo de 12 Efectos de Movimiento -->
                <div style="display: flex; flex-direction: column; gap: 8px;">
                  <div style="font-size: 11.5px; color: #fff; font-weight: 700; display: flex; align-items: center; gap: 6px;">
                    <i class="fa-solid fa-wand-magic-sparkles" style="color: var(--accent-purple);"></i> Elige un Efecto de Movimiento del Catálogo:
                  </div>
                  <div style="display: grid; grid-template-columns: repeat(auto-fill, minmax(210px, 1fr)); gap: 10px;">
                    ${efectosMov.map(ef => {
                        const activo = fg.tipo === 'movimiento' && fg.efectoMovimiento === ef.id;
                        return `
                          <div class="cfg-fg-efecto-card" data-efecto-id="${ef.id}" style="background: ${activo ? 'rgba(137,180,250,0.18)' : 'rgba(0,0,0,0.3)'}; border: 1.5px solid ${activo ? 'var(--accent-blue)' : 'var(--border-color)'}; border-radius: 8px; padding: 12px; cursor: pointer; transition: all 0.2s ease; ${activo ? 'box-shadow: 0 0 12px rgba(137,180,250,0.35);' : ''}">
                            <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 6px;">
                              <div style="display: flex; align-items: center; gap: 8px;">
                                <i class="fa-solid ${ef.icono}" style="color: ${activo ? 'var(--accent-blue)' : 'var(--accent-purple)'}; font-size: 14px;"></i>
                                <span style="font-weight: 700; font-size: 11.5px; color: #fff;">${ef.nombre}</span>
                              </div>
                              ${activo ? '<i class="fa-solid fa-circle-check" style="color: var(--accent-blue);"></i>' : ''}
                            </div>
                            <div style="font-size: 10.5px; color: var(--text-muted); line-height: 1.35;">${ef.desc}</div>
                          </div>
                        `;
                    }).join('')}
                  </div>
                </div>
              </div>
            ` : ''}

            <!-- 4. PROGRAMAR FONDO CON CÓDIGO EN VIVO (JS CANVAS / CSS) -->
            ${modoActivo === 'codigo' ? `
              <div style="display: flex; flex-direction: column; gap: 12px; background: rgba(0,0,0,0.3); padding: 12px; border-radius: 8px; border: 1px solid var(--border-color);">
                <div style="display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 8px;">
                  <div style="display: flex; gap: 4px;">
                    <button class="tool-btn ${tipoCodigoActual === 'codigo_js' ? 'primary' : ''}" id="cfg-fg-switch-js" style="font-size: 11px; padding: 4px 10px;">
                      <i class="fa-brands fa-js"></i> Canvas JavaScript (render)
                    </button>
                    <button class="tool-btn ${tipoCodigoActual === 'codigo_css' ? 'primary' : ''}" id="cfg-fg-switch-css" style="font-size: 11px; padding: 4px 10px;">
                      <i class="fa-brands fa-css3-alt"></i> Estilos y Animaciones CSS
                    </button>
                  </div>
                  
                  <div style="display: flex; align-items: center; gap: 6px;">
                    <span style="font-size: 11px; color: var(--text-muted);">Plantilla:</span>
                    <select id="cfg-fg-plantilla-sel" style="padding: 4px 8px; background: var(--bg-panel); border: 1px solid var(--border-color); color: #fff; border-radius: 5px; font-size: 11px;">
                      <option value="">-- Cargar ejemplo interactivo --</option>
                      <option value="canvas_red_neuronal">Red neuronal interactiva (Canvas JS)</option>
                      <option value="canvas_ondas">Olas senoidales líquidas (Canvas JS)</option>
                      <option value="css_animado">Degradado fluido y resplandor neón (CSS)</option>
                    </select>
                  </div>
                </div>

                <div>
                  <textarea id="cfg-fg-codigo-editor" rows="12" style="width: 100%; box-sizing: border-box; background: #0b0c14; border: 1px solid var(--accent-purple); color: #cdd6f4; border-radius: 6px; padding: 10px; font-family: 'Fira Code', 'Cascadia Code', monospace; font-size: 11.5px; line-height: 1.45; resize: vertical;" placeholder="// Escribe tu código aquí...">${esc(tipoCodigoActual === 'codigo_css' ? (fg.codigoCss || ejemplosCod.css_animado) : (fg.codigoJs || ejemplosCod.canvas_red_neuronal))}</textarea>
                </div>

                <div style="display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 8px;">
                  <button class="tool-btn primary" id="cfg-fg-ejecutar-codigo" style="font-size: 11.5px; padding: 6px 16px; background: linear-gradient(135deg, var(--accent-blue), var(--accent-purple)); border: none; color: #fff; font-weight: 700; box-shadow: 0 0 10px rgba(137,180,250,0.35);">
                    <i class="fa-solid fa-play"></i> Ejecutar y Guardar Fondo
                  </button>
                  <span style="font-size: 11px; color: var(--accent-green); display: inline-flex; align-items: center; gap: 5px;">
                    <i class="fa-solid fa-bolt"></i> Ejecución en vivo e interactiva
                  </span>
                </div>

                <div class="des-ayuda" style="font-size: 10.5px; line-height: 1.4; padding: 8px 10px;">
                  ${tipoCodigoActual === 'codigo_js' 
                    ? '<b>Guía Canvas JS:</b> Define una función <code>render(ctx, width, height, time)</code>. Se ejecutará en cada frame en un lienzo 2D en pantalla completa detrás del IDE.'
                    : '<b>Guía CSS:</b> Escribe reglas CSS aplicables a <code>body</code> o <code>#app-container</code> incluyendo animaciones <code>@keyframes</code>.'}
                </div>
              </div>
            ` : ''}

            <!-- 5. DEGRADADOS ESTÁTICOS -->
            ${modoActivo === 'gradiente' ? `
              <div style="display: flex; flex-direction: column; gap: 10px;">
                <span style="font-weight: 600; color: #fff; font-size: 11.5px;">Degradados Predefinidos:</span>
                <div style="display: grid; grid-template-columns: repeat(auto-fill, minmax(170px, 1fr)); gap: 8px;">
                  ${gradientes.map(g => {
                      const activo = fg.tipo === 'gradiente' && fg.gradiente === g.valor;
                      return `
                        <div class="ap-card-gradiente" data-grad="${esc(g.valor)}" style="background: ${g.valor}; border: 1.5px solid ${activo ? 'var(--accent-blue)' : 'rgba(255,255,255,0.15)'}; border-radius: 8px; padding: 12px 10px; cursor: pointer; transition: all 0.2s ease; ${activo ? 'box-shadow: 0 0 10px rgba(137,180,250,0.35);' : ''}">
                          <div style="display: flex; align-items: center; justify-content: space-between;">
                            <span style="font-weight: 700; font-size: 11px; color: #ffffff; text-shadow: 0 1px 3px rgba(0,0,0,0.8);">${g.nombre}</span>
                            ${activo ? '<i class="fa-solid fa-circle-check" style="color: #ffffff; text-shadow: 0 1px 3px rgba(0,0,0,0.8);"></i>' : ''}
                          </div>
                        </div>
                      `;
                  }).join('')}
                </div>
                <div style="margin-top: 4px;">
                  <label style="font-weight: 600; color: var(--text-muted); font-size: 11px; margin-bottom: 4px; display: block;">O escribe tu propio CSS Linear / Radial Gradient:</label>
                  <input type="text" id="cfg-fg-gradiente-custom" value="${esc(fg.gradiente || '')}" placeholder="linear-gradient(135deg, #1e1e2e 0%, #11111b 100%)" style="width: 100%; padding: 7px 10px; background: var(--bg-dark); border: 1px solid var(--border-color); color: #fff; border-radius: 6px; font-family: 'Fira Code', monospace; font-size: 11px; box-sizing: border-box;">
                </div>
              </div>
            ` : ''}

            <!-- 6. POR DEFECTO DEL TEMA -->
            ${modoActivo === 'defecto' ? `
              <div class="des-ayuda" style="padding: 12px; font-size: 11.5px;">
                <i class="fa-solid fa-circle-info"></i> El fondo del programa utiliza el color general configurado en el tema activo (<code>${est.colores.bg_dark}</code>). Elige cualquiera de las opciones superiores para personalizarlo.
              </div>
            ` : ''}
          </div>
        `;

        // Eventos selector principal de modo de fondo
        container.querySelectorAll('[data-fg-modo]').forEach(btn => {
            btn.onclick = () => {
                const modo = btn.dataset.fgModo;
                if (modo === 'codigo') {
                    ap.setFondoGlobal('tipo', tipoCodigoActual);
                } else {
                    ap.setFondoGlobal('tipo', modo);
                }
                this.initApariencia('fondo-global');
            };
        });

        // Eventos color estático
        const fgColorPick = document.getElementById('cfg-fg-color-picker');
        const fgColorHex = document.getElementById('cfg-fg-color-hex');
        if (fgColorPick && fgColorHex) {
            fgColorPick.oninput = () => {
                fgColorHex.value = fgColorPick.value.toUpperCase();
                ap.setFondoGlobal('color', fgColorPick.value);
            };
            fgColorHex.onchange = () => {
                let v = fgColorHex.value.trim();
                if (!v.startsWith('#')) v = '#' + v;
                if (/^#[0-9A-Fa-f]{6}$/.test(v)) {
                    fgColorPick.value = v;
                    ap.setFondoGlobal('color', v);
                }
            };
        }

        container.querySelectorAll('.cfg-fg-color-chip').forEach(chip => {
            chip.onclick = () => {
                const col = chip.dataset.color;
                if (fgColorPick) fgColorPick.value = col;
                if (fgColorHex) fgColorHex.value = col.toUpperCase();
                ap.setFondoGlobal('color', col);
                this.initApariencia('fondo-global');
            };
        });

        // Eventos imagen
        const inpArchivo = document.getElementById('cfg-fg-archivo');
        if (inpArchivo) {
            inpArchivo.onchange = () => {
                const file = inpArchivo.files[0];
                if (!file) return;
                if (file.size > 10 * 1024 * 1024) {
                    alert('La imagen seleccionada supera el límite recomendado de 10 MB.');
                    return;
                }
                const reader = new FileReader();
                reader.onload = (ev) => {
                    ap.setFondoGlobal('tipo', 'imagen');
                    ap.setFondoGlobal('imagenUrl', ev.target.result);
                    this.initApariencia('fondo-global');
                };
                reader.readAsDataURL(file);
            };
        }

        const btnAplicarUrl = document.getElementById('cfg-fg-aplicar-url');
        const inpUrl = document.getElementById('cfg-fg-imagen-url');
        if (btnAplicarUrl && inpUrl) {
            btnAplicarUrl.onclick = () => {
                const val = inpUrl.value.trim();
                if (val) {
                    ap.setFondoGlobal('tipo', 'imagen');
                    ap.setFondoGlobal('imagenUrl', val);
                    this.initApariencia('fondo-global');
                }
            };
        }

        const btnQuitarImg = document.getElementById('cfg-fg-quitar-img');
        if (btnQuitarImg) {
            btnQuitarImg.onclick = () => {
                ap.setFondoGlobal('imagenUrl', '');
                ap.setFondoGlobal('tipo', 'defecto');
                this.initApariencia('fondo-global');
            };
        }

        const selAjuste = document.getElementById('cfg-fg-ajuste');
        if (selAjuste) {
            selAjuste.onchange = () => {
                ap.setFondoGlobal('imagenAjuste', selAjuste.value);
            };
        }

        const rangeOverlay = document.getElementById('cfg-fg-overlay');
        const lblOverlay = document.getElementById('cfg-fg-overlay-val');
        if (rangeOverlay) {
            rangeOverlay.oninput = () => {
                const val = parseFloat(rangeOverlay.value);
                if (lblOverlay) lblOverlay.textContent = `${Math.round(val * 100)}%`;
                ap.setFondoGlobal('overlayAlfa', val);
            };
        }

        // Eventos controles de eficiencia del motor de movimiento
        const selFps = document.getElementById('cfg-mot-fps-limite');
        if (selFps && window.motorMovimiento) {
            selFps.onchange = () => {
                window.motorMovimiento.setOpcion('fpsLimite', parseInt(selFps.value, 10));
            };
        }

        const selEscala = document.getElementById('cfg-mot-escala-render');
        if (selEscala && window.motorMovimiento) {
            selEscala.onchange = () => {
                window.motorMovimiento.setOpcion('escalaRender', parseFloat(selEscala.value));
            };
        }

        const selDens = document.getElementById('cfg-mot-densidad');
        if (selDens && window.motorMovimiento) {
            selDens.onchange = () => {
                window.motorMovimiento.setOpcion('densidad', selDens.value);
            };
        }

        const rngVel = document.getElementById('cfg-mot-velocidad');
        const lblVel = document.getElementById('cfg-mot-vel-val');
        if (rngVel && window.motorMovimiento) {
            rngVel.oninput = () => {
                const v = parseFloat(rngVel.value);
                if (lblVel) lblVel.textContent = `${v.toFixed(1)}x`;
                window.motorMovimiento.setOpcion('velocidad', v);
            };
        }

        const chkMouse = document.getElementById('cfg-mot-mouse');
        if (chkMouse && window.motorMovimiento) {
            chkMouse.onchange = () => {
                window.motorMovimiento.setOpcion('interaccionMouse', chkMouse.checked);
            };
        }

        const chkPausa = document.getElementById('cfg-mot-pausa-fondo');
        if (chkPausa && window.motorMovimiento) {
            chkPausa.onchange = () => {
                window.motorMovimiento.setOpcion('pausarEnSegundoPlano', chkPausa.checked);
            };
        }

        // Bucle de actualización de Telemetría HUD (en vivo cada 400ms mientras el modal esté abierto)
        if (this._telemetriaTimer) clearInterval(this._telemetriaTimer);
        this._telemetriaTimer = setInterval(() => {
            const elFps = document.getElementById('cfg-mot-fps-val');
            const elMs = document.getElementById('cfg-mot-ms-val');
            const elEst = document.getElementById('cfg-mot-estado-val');
            if (!elFps) {
                clearInterval(this._telemetriaTimer);
                this._telemetriaTimer = null;
                return;
            }
            if (window.motorMovimiento) {
                const t = window.motorMovimiento.telemetria;
                elFps.textContent = `${t.fps} FPS`;
                elFps.style.color = t.fps >= 50 ? 'var(--accent-green)' : (t.fps >= 30 ? 'var(--accent-yellow)' : 'var(--accent-red)');
                elMs.textContent = `${t.frameTimeMs} ms`;
                elEst.textContent = t.estado;
            }
        }, 400);

        // Eventos efectos de movimiento
        container.querySelectorAll('.cfg-fg-efecto-card').forEach(card => {
            card.onclick = () => {
                const efectoId = card.dataset.efectoId;
                ap.setFondoGlobal('tipo', 'movimiento');
                ap.setFondoGlobal('efectoMovimiento', efectoId);
                this.initApariencia('fondo-global');
            };
        });

        // Eventos código en vivo (JS / CSS)
        const btnSwitchJs = document.getElementById('cfg-fg-switch-js');
        const btnSwitchCss = document.getElementById('cfg-fg-switch-css');
        if (btnSwitchJs && btnSwitchCss) {
            btnSwitchJs.onclick = () => {
                ap.setFondoGlobal('tipo', 'codigo_js');
                this.initApariencia('fondo-global');
            };
            btnSwitchCss.onclick = () => {
                ap.setFondoGlobal('tipo', 'codigo_css');
                this.initApariencia('fondo-global');
            };
        }

        const selPlantilla = document.getElementById('cfg-fg-plantilla-sel');
        const txtEditor = document.getElementById('cfg-fg-codigo-editor');
        if (selPlantilla && txtEditor) {
            selPlantilla.onchange = () => {
                const val = selPlantilla.value;
                if (!val || !ejemplosCod[val]) return;
                txtEditor.value = ejemplosCod[val];
                if (val.startsWith('canvas_')) {
                    ap.setFondoGlobal('tipo', 'codigo_js');
                    ap.setFondoGlobal('codigoJs', txtEditor.value);
                } else if (val.startsWith('css_')) {
                    ap.setFondoGlobal('tipo', 'codigo_css');
                    ap.setFondoGlobal('codigoCss', txtEditor.value);
                }
                this.initApariencia('fondo-global');
            };
        }

        const btnEjecutarCod = document.getElementById('cfg-fg-ejecutar-codigo');
        if (btnEjecutarCod && txtEditor) {
            btnEjecutarCod.onclick = () => {
                const codeVal = txtEditor.value;
                if (tipoCodigoActual === 'codigo_js') {
                    ap.setFondoGlobal('tipo', 'codigo_js');
                    ap.setFondoGlobal('codigoJs', codeVal);
                } else {
                    ap.setFondoGlobal('tipo', 'codigo_css');
                    ap.setFondoGlobal('codigoCss', codeVal);
                }
                this.initApariencia('fondo-global');
            };
        }

        // Eventos degradados
        container.querySelectorAll('.ap-card-gradiente').forEach(card => {
            card.onclick = () => {
                ap.setFondoGlobal('tipo', 'gradiente');
                ap.setFondoGlobal('gradiente', card.dataset.grad);
                this.initApariencia('fondo-global');
            };
        });

        const customGrad = document.getElementById('cfg-fg-gradiente-custom');
        if (customGrad) {
            customGrad.onchange = () => {
                if (customGrad.value.trim()) {
                    ap.setFondoGlobal('tipo', 'gradiente');
                    ap.setFondoGlobal('gradiente', customGrad.value.trim());
                    this.initApariencia('fondo-global');
                }
            };
        }
    }

    _renderSubTabSecciones(container, ap) {
        const est = ap.estado;
        const seccionesIde = window.SECCIONES_IDE || [];
        if (!this.seccionSeleccionada) this.seccionSeleccionada = 'topbar';

        const secActual = seccionesIde.find(s => s.id === this.seccionSeleccionada) || seccionesIde[0];
        const secCfg = (est.secciones && est.secciones[secActual.id]) || { tipo: 'heredar', color: est.colores.bg_panel, alfa: 0.9, blur: 0 };

        container.innerHTML = `
          <div style="background: rgba(0,0,0,0.2); border: 1px solid var(--border-color); border-radius: 8px; padding: 12px; display: flex; flex-direction: column; gap: 12px;">
            <div style="display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 8px;">
              <span style="font-weight: 700; color: #fff; font-size: 12px; display: flex; align-items: center; gap: 6px;">
                <i class="fa-solid fa-layer-group" style="color: var(--accent-purple);"></i> Selecciona la Sección del IDE a Personalizar:
              </span>
              <select id="cfg-sec-selector" style="padding: 6px 12px; background: var(--bg-panel); border: 1.5px solid var(--accent-purple); color: #fff; border-radius: 6px; font-weight: 600; font-size: 12px;">
                ${seccionesIde.map(s => `
                  <option value="${s.id}" ${s.id === secActual.id ? 'selected' : ''}>${s.nombre}</option>
                `).join('')}
              </select>
            </div>

            <!-- Panel de Personalización de la Sección Seleccionada -->
            <div style="background: rgba(0,0,0,0.3); border: 1px solid var(--border-color); border-radius: 8px; padding: 12px; display: flex; flex-direction: column; gap: 12px;">
              <div style="display: flex; align-items: center; justify-content: space-between; border-bottom: 1px solid var(--border-color); padding-bottom: 8px; flex-wrap: wrap; gap: 6px;">
                <div style="display: flex; align-items: center; gap: 8px;">
                  <i class="fa-solid ${secActual.icono || 'fa-window-maximize'}" style="font-size: 16px; color: var(--accent-blue);"></i>
                  <div>
                    <span style="font-weight: 700; color: #fff; font-size: 13px;">${secActual.nombre}</span>
                    <div style="font-size: 10.5px; color: var(--text-muted); font-family: monospace;">Selectores: ${secActual.selector}</div>
                  </div>
                </div>
                <button class="tool-btn" id="cfg-sec-restablecer" style="font-size: 11px; padding: 3px 8px; color: var(--accent-red);"><i class="fa-solid fa-rotate-left"></i> Restablecer a tema</button>
              </div>

              <!-- Tipo de Fondo de Sección -->
              <div style="display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 8px;">
                <span style="font-weight: 600; color: #fff; font-size: 11px;">Fondo de esta sección:</span>
                <div style="display: flex; gap: 4px; flex-wrap: wrap;">
                  ${[
                    ['heredar', 'Heredar tema', 'fa-circle-dot'],
                    ['color', 'Color Estático', 'fa-palette'],
                    ['imagen', 'Fotografía', 'fa-image'],
                    ['movimiento', 'Movimiento', 'fa-wand-magic-sparkles'],
                    ['gradiente', 'Degradado', 'fa-brush'],
                    ['codigo', 'Código CSS', 'fa-code']
                  ].map(([t, nom, ico]) => `
                      <button class="tool-btn ${secCfg.tipo === t ? 'primary' : ''}" data-sec-tipo="${t}" style="font-size: 11px; padding: 4px 9px; display: inline-flex; align-items: center; gap: 4px;">
                        <i class="fa-solid ${ico}"></i> ${nom}
                      </button>
                    `).join('')}
                </div>
              </div>

              <!-- 1. Color Estático en Sección -->
              ${secCfg.tipo === 'color' ? `
                <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 10px; background: rgba(0,0,0,0.2); padding: 10px; border-radius: 6px;">
                  <div style="display: flex; align-items: center; gap: 8px;">
                    <input type="color" id="cfg-sec-color-picker" value="${(secCfg.color || est.colores.bg_panel).slice(0, 7)}" style="width: 38px; height: 34px; border: none; border-radius: 6px; cursor: pointer; background: transparent;">
                    <input type="text" id="cfg-sec-color-hex" value="${secCfg.color || est.colores.bg_panel}" style="width: 85px; background: var(--bg-dark); border: 1px solid var(--border-color); color: #fff; border-radius: 5px; padding: 4px 6px; font-family: monospace; font-size: 11px; text-transform: uppercase;">
                  </div>
                  <div>
                    <label style="font-weight: 600; color: #fff; font-size: 11px; display: block; margin-bottom: 2px;">Opacidad / Transparencia: <span id="cfg-sec-alfa-val">${Math.round((secCfg.alfa !== undefined ? secCfg.alfa : 0.9) * 100)}%</span></label>
                    <input type="range" id="cfg-sec-alfa" min="0.1" max="1" step="0.05" value="${secCfg.alfa !== undefined ? secCfg.alfa : 0.9}" style="width: 100%; accent-color: var(--accent-purple);">
                  </div>
                </div>
              ` : ''}

              <!-- 2. Fotografía / Textura en Sección -->
              ${secCfg.tipo === 'imagen' ? `
                <div style="display: flex; flex-direction: column; gap: 8px; background: rgba(0,0,0,0.2); padding: 10px; border-radius: 6px;">
                  <div style="display: flex; gap: 8px; align-items: center; flex-wrap: wrap;">
                    <label class="tool-btn primary" style="cursor: pointer; padding: 5px 12px; font-size: 11px;">
                      <i class="fa-solid fa-upload"></i> Subir fotografía local
                      <input type="file" id="cfg-sec-archivo" accept="image/*" style="display: none;">
                    </label>
                    <input type="text" id="cfg-sec-img-url" value="${esc(secCfg.imagenUrl && !secCfg.imagenUrl.startsWith('data:') ? secCfg.imagenUrl : '')}" placeholder="https://ejemplo.com/textura.png" style="flex: 1; padding: 5px 8px; background: var(--bg-dark); border: 1px solid var(--border-color); color: #fff; border-radius: 6px; font-size: 11px;">
                    <button class="tool-btn" id="cfg-sec-aplicar-url" style="padding: 5px 10px;"><i class="fa-solid fa-check"></i></button>
                  </div>
                  ${secCfg.imagenUrl ? `
                    <div style="display: flex; gap: 10px; align-items: center;">
                      <label style="font-size: 11px; color: #fff;">Ajuste:</label>
                      <select id="cfg-sec-img-ajuste" style="padding: 4px 8px; background: var(--bg-panel); border: 1px solid var(--border-color); color: #fff; border-radius: 4px; font-size: 11px;">
                        <option value="cover" ${secCfg.imagenAjuste === 'cover' ? 'selected' : ''}>Cubrir (Cover)</option>
                        <option value="contain" ${secCfg.imagenAjuste === 'contain' ? 'selected' : ''}>Ajustar (Contain)</option>
                        <option value="repeat" ${secCfg.imagenAjuste === 'repeat' ? 'selected' : ''}>Repetir textura</option>
                      </select>
                    </div>
                  ` : ''}
                </div>
              ` : ''}

              <!-- 3. Movimiento / Animación en Sección -->
              ${secCfg.tipo === 'movimiento' ? `
                <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 8px; background: rgba(0,0,0,0.2); padding: 10px; border-radius: 6px;">
                  ${[
                    ['pulso_neon', 'Pulso de Resplandor Neón', 'fa-bolt', 'Efecto de respiración suave con resplandor neón'],
                    ['destello_borde', 'Destello RGB en Bordes', 'fa-wand-magic', 'Transición continua de colores en el borde'],
                    ['degradado_fluido', 'Degradado Líquido Fluido', 'fa-water', 'Fondo dinámico en movimiento continuo']
                  ].map(([mId, mNom, mIco, mDesc]) => {
                      const activo = secCfg.movimiento === mId;
                      return `
                        <div class="cfg-sec-mov-card" data-sec-mov="${mId}" style="background: ${activo ? 'rgba(203,166,247,0.2)' : 'rgba(0,0,0,0.3)'}; border: 1.5px solid ${activo ? 'var(--accent-purple)' : 'var(--border-color)'}; border-radius: 6px; padding: 8px; cursor: pointer; transition: all 0.2s ease;">
                          <div style="font-weight: 700; color: #fff; font-size: 11.5px; display: flex; align-items: center; gap: 6px; margin-bottom: 4px;">
                            <i class="fa-solid ${mIco}" style="color: var(--accent-purple);"></i> ${mNom}
                          </div>
                          <div style="font-size: 10px; color: var(--text-muted);">${mDesc}</div>
                        </div>
                      `;
                  }).join('')}
                </div>
              ` : ''}

              <!-- 4. Degradado en Sección -->
              ${secCfg.tipo === 'gradiente' ? `
                <div style="background: rgba(0,0,0,0.2); padding: 10px; border-radius: 6px;">
                  <label style="font-weight: 600; color: #fff; font-size: 11px; display: block; margin-bottom: 4px;">Degradado CSS para esta sección:</label>
                  <input type="text" id="cfg-sec-gradiente" value="${esc(secCfg.gradiente || 'linear-gradient(135deg, rgba(30,30,46,0.9) 0%, rgba(24,24,37,0.9) 100%)')}" placeholder="linear-gradient(...)" style="width: 100%; padding: 6px 10px; background: var(--bg-dark); border: 1px solid var(--border-color); color: #fff; border-radius: 6px; font-family: monospace; font-size: 11px; box-sizing: border-box;">
                </div>
              ` : ''}

              <!-- 5. Código CSS Propio en Sección -->
              ${secCfg.tipo === 'codigo' ? `
                <div style="display: flex; flex-direction: column; gap: 8px; background: rgba(0,0,0,0.2); padding: 10px; border-radius: 6px;">
                  <label style="font-weight: 600; color: #fff; font-size: 11px;">CSS personalizado para <code>${secActual.selector}</code>:</label>
                  <textarea id="cfg-sec-codigo-css" rows="4" style="width: 100%; box-sizing: border-box; background: #0b0c14; border: 1px solid var(--accent-blue); color: #cdd6f4; border-radius: 6px; padding: 8px; font-family: monospace; font-size: 11px;" placeholder="background: rgba(20, 20, 35, 0.8) !important;\nborder-left: 2px dashed #89b4fa !important;">${esc(secCfg.codigoCss || '')}</textarea>
                  <button class="tool-btn primary" id="cfg-sec-aplicar-codigo" style="align-self: flex-start; font-size: 11px; padding: 4px 12px;"><i class="fa-solid fa-play"></i> Aplicar CSS a Sección</button>
                </div>
              ` : ''}

              <!-- Ajustes de Desenfoque Glassmorphism y Borde (Comunes) -->
              <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 10px; border-top: 1px solid var(--border-color); padding-top: 8px;">
                <div>
                  <label style="font-weight: 600; color: #fff; font-size: 11px; display: block; margin-bottom: 2px;">Desenfoque Glassmorphism: <span id="cfg-sec-blur-val">${secCfg.blur || 0}px</span></label>
                  <input type="range" id="cfg-sec-blur" min="0" max="25" step="1" value="${secCfg.blur || 0}" style="width: 100%; accent-color: var(--accent-blue);">
                </div>
                <div>
                  <label style="font-weight: 600; color: #fff; font-size: 11px; display: block; margin-bottom: 2px;">Color de Borde / Resalte:</label>
                  <div style="display: flex; align-items: center; gap: 6px;">
                    <input type="color" id="cfg-sec-borde-picker" value="${(secCfg.bordeColor || est.colores.border_color).slice(0, 7)}" style="width: 32px; height: 30px; border: none; border-radius: 4px; cursor: pointer; background: transparent;">
                    <input type="text" id="cfg-sec-borde-hex" value="${secCfg.bordeColor || ''}" placeholder="Por defecto" style="flex: 1; background: var(--bg-dark); border: 1px solid var(--border-color); color: #fff; border-radius: 4px; padding: 4px 6px; font-family: monospace; font-size: 11px;">
                  </div>
                </div>
              </div>
            </div>
          </div>
        `;

        // Selector de sección
        const selSec = document.getElementById('cfg-sec-selector');
        if (selSec) {
            selSec.onchange = () => {
                this.seccionSeleccionada = selSec.value;
                this.initApariencia('secciones');
            };
        }

        // Tipo de fondo de sección
        container.querySelectorAll('[data-sec-tipo]').forEach(btn => {
            btn.onclick = () => {
                ap.setSeccion(secActual.id, 'tipo', btn.dataset.secTipo);
                this.initApariencia('secciones');
            };
        });

        // Restablecer sección
        const btnRest = document.getElementById('cfg-sec-restablecer');
        if (btnRest) {
            btnRest.onclick = () => {
                ap.restablecerSeccion(secActual.id);
                this.initApariencia('secciones');
            };
        }

        // Color y alfa
        const secColPick = document.getElementById('cfg-sec-color-picker');
        const secColHex = document.getElementById('cfg-sec-color-hex');
        if (secColPick && secColHex) {
            secColPick.oninput = () => {
                secColHex.value = secColPick.value.toUpperCase();
                ap.setSeccion(secActual.id, 'color', secColPick.value);
            };
            secColHex.onchange = () => {
                let v = secColHex.value.trim();
                if (!v.startsWith('#')) v = '#' + v;
                if (/^#[0-9A-Fa-f]{6}$/.test(v)) {
                    secColPick.value = v;
                    ap.setSeccion(secActual.id, 'color', v);
                }
            };
        }

        const rangeAlfa = document.getElementById('cfg-sec-alfa');
        const lblAlfa = document.getElementById('cfg-sec-alfa-val');
        if (rangeAlfa) {
            rangeAlfa.oninput = () => {
                const val = parseFloat(rangeAlfa.value);
                if (lblAlfa) lblAlfa.textContent = `${Math.round(val * 100)}%`;
                ap.setSeccion(secActual.id, 'alfa', val);
            };
        }

        // Movimiento de sección
        container.querySelectorAll('.cfg-sec-mov-card').forEach(card => {
            card.onclick = () => {
                ap.setSeccion(secActual.id, 'tipo', 'movimiento');
                ap.setSeccion(secActual.id, 'movimiento', card.dataset.secMov);
                this.initApariencia('secciones');
            };
        });

        // Gradiente de sección
        const inpSecGrad = document.getElementById('cfg-sec-gradiente');
        if (inpSecGrad) {
            inpSecGrad.onchange = () => {
                ap.setSeccion(secActual.id, 'gradiente', inpSecGrad.value.trim());
            };
        }

        // Imagen de sección
        const inpSecArch = document.getElementById('cfg-sec-archivo');
        if (inpSecArch) {
            inpSecArch.onchange = () => {
                const file = inpSecArch.files[0];
                if (!file) return;
                const reader = new FileReader();
                reader.onload = (ev) => {
                    ap.setSeccion(secActual.id, 'tipo', 'imagen');
                    ap.setSeccion(secActual.id, 'imagenUrl', ev.target.result);
                    this.initApariencia('secciones');
                };
                reader.readAsDataURL(file);
            };
        }

        const btnSecUrl = document.getElementById('cfg-sec-aplicar-url');
        const inpSecUrl = document.getElementById('cfg-sec-img-url');
        if (btnSecUrl && inpSecUrl) {
            btnSecUrl.onclick = () => {
                const val = inpSecUrl.value.trim();
                if (val) {
                    ap.setSeccion(secActual.id, 'tipo', 'imagen');
                    ap.setSeccion(secActual.id, 'imagenUrl', val);
                    this.initApariencia('secciones');
                }
            };
        }

        const selSecAjuste = document.getElementById('cfg-sec-img-ajuste');
        if (selSecAjuste) {
            selSecAjuste.onchange = () => {
                ap.setSeccion(secActual.id, 'imagenAjuste', selSecAjuste.value);
            };
        }

        // Código CSS de sección
        const txtSecCss = document.getElementById('cfg-sec-codigo-css');
        const btnSecCss = document.getElementById('cfg-sec-aplicar-codigo');
        if (txtSecCss && btnSecCss) {
            btnSecCss.onclick = () => {
                ap.setSeccion(secActual.id, 'tipo', 'codigo');
                ap.setSeccion(secActual.id, 'codigoCss', txtSecCss.value);
                this.initApariencia('secciones');
            };
        }

        // Blur de sección
        const rangeBlur = document.getElementById('cfg-sec-blur');
        const lblBlur = document.getElementById('cfg-sec-blur-val');
        if (rangeBlur) {
            rangeBlur.oninput = () => {
                const val = parseInt(rangeBlur.value, 10);
                if (lblBlur) lblBlur.textContent = `${val}px`;
                ap.setSeccion(secActual.id, 'blur', val);
            };
        }

        // Borde de sección
        const secBordePick = document.getElementById('cfg-sec-borde-picker');
        const secBordeHex = document.getElementById('cfg-sec-borde-hex');
        if (secBordePick && secBordeHex) {
            secBordePick.oninput = () => {
                secBordeHex.value = secBordePick.value.toUpperCase();
                ap.setSeccion(secActual.id, 'bordeColor', secBordePick.value);
            };
            secBordeHex.onchange = () => {
                const v = secBordeHex.value.trim();
                ap.setSeccion(secActual.id, 'bordeColor', v);
            };
        }
    }

    _renderSubTabEfectos(container, ap) {
        const est = ap.estado;

        container.innerHTML = `
          <div style="background: rgba(0,0,0,0.2); border: 1px solid var(--border-color); border-radius: 8px; padding: 14px; display: flex; flex-direction: column; gap: 14px;">
            <span style="font-weight: 700; color: #fff; font-size: 12px; display: flex; align-items: center; gap: 6px;">
              <i class="fa-solid fa-sliders" style="color: var(--accent-yellow);"></i> Densidad y Transparencias Globales
            </span>

            <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 14px;">
              <div>
                <label style="font-weight: 600; color: #fff; font-size: 11.5px; display: block; margin-bottom: 4px;">Opacidad Global de la Interfaz: <span id="ap-opacidad-val">${Math.round(est.opacidad * 100)}%</span></label>
                <input type="range" id="ap-opacidad-rng" min="0.35" max="1" step="0.01" value="${est.opacidad}" style="width: 100%; accent-color: var(--accent-purple);">
                <div style="font-size: 10.5px; color: var(--text-muted); margin-top: 4px;">Atajo rápido: <b>Ctrl+Alt+↑</b> / <b>Ctrl+Alt+↓</b></div>
              </div>

              <div>
                <label style="font-weight: 600; color: #fff; font-size: 11.5px; display: block; margin-bottom: 4px;">Desenfoque Global (Glassmorphism): <span id="ap-desenfoque-val">${est.desenfoque}px</span></label>
                <input type="range" id="ap-desenfoque-rng" min="0" max="30" step="1" value="${est.desenfoque}" style="width: 100%; accent-color: var(--accent-blue);">
                <div style="font-size: 10.5px; color: var(--text-muted); margin-top: 4px;">Suaviza las capas translúcidas para no perder nitidez</div>
              </div>

              <div>
                <label style="font-weight: 600; color: #fff; font-size: 11.5px; display: block; margin-bottom: 4px;">Densidad de Elementos:</label>
                <select id="ap-densidad-sel" style="width: 100%; padding: 6px 10px; background: var(--bg-panel); border: 1px solid var(--border-color); color: #fff; border-radius: 6px; font-size: 11.5px;">
                  <option value="compacta" ${est.densidad === 'compacta' ? 'selected' : ''}>Compacta (más espacio en pantalla)</option>
                  <option value="normal" ${est.densidad === 'normal' ? 'selected' : ''}>Normal (predeterminada)</option>
                  <option value="amplia" ${est.densidad === 'amplia' ? 'selected' : ''}>Amplia (más espacio táctil/visual)</option>
                </select>
              </div>
            </div>

            <!-- Respaldo, Exportación e Importación de Temas -->
            <div style="border-top: 1px solid var(--border-color); padding-top: 12px; margin-top: 6px;">
              <span style="font-weight: 700; color: #fff; font-size: 12px; display: flex; align-items: center; gap: 6px; margin-bottom: 8px;">
                <i class="fa-solid fa-file-export" style="color: var(--accent-blue);"></i> Respaldo y Compartir Temas
              </span>
              <div style="display: flex; gap: 8px; flex-wrap: wrap;">
                <button class="tool-btn primary" id="ap-btn-exportar" style="font-size: 11.5px; padding: 6px 12px;">
                  <i class="fa-solid fa-download"></i> Exportar Tema (JSON)
                </button>
                <label class="tool-btn" style="cursor: pointer; font-size: 11.5px; padding: 6px 12px; display: inline-flex; align-items: center; gap: 6px;">
                  <i class="fa-solid fa-file-import"></i> Importar Tema desde archivo
                  <input type="file" id="ap-file-importar" accept=".json" style="display: none;">
                </label>
                <button class="tool-btn" id="ap-btn-importar-texto" style="font-size: 11.5px; padding: 6px 12px;">
                  <i class="fa-solid fa-paste"></i> Pegar código JSON
                </button>
                <span style="flex: 1;"></span>
                <button class="tool-btn" id="ap-btn-restablecer-todo" style="background: rgba(243,139,168,0.15); color: var(--accent-red); border-color: rgba(243,139,168,0.4); font-size: 11.5px; padding: 6px 12px;">
                  <i class="fa-solid fa-rotate-left"></i> Restablecer Todo por Defecto
                </button>
              </div>
            </div>
          </div>
        `;

        // Controles de sliders y densidad
        const rngOp = document.getElementById('ap-opacidad-rng');
        const lblOp = document.getElementById('ap-opacidad-val');
        if (rngOp) {
            rngOp.oninput = () => {
                const val = parseFloat(rngOp.value);
                if (lblOp) lblOp.textContent = `${Math.round(val * 100)}%`;
                ap.set('opacidad', val);
            };
        }

        const rngDes = document.getElementById('ap-desenfoque-rng');
        const lblDes = document.getElementById('ap-desenfoque-val');
        if (rngDes) {
            rngDes.oninput = () => {
                const val = parseInt(rngDes.value, 10);
                if (lblDes) lblDes.textContent = `${val}px`;
                ap.set('desenfoque', val);
            };
        }

        const selDens = document.getElementById('ap-densidad-sel');
        if (selDens) {
            selDens.onchange = () => {
                ap.set('densidad', selDens.value);
            };
        }

        // Exportar JSON
        const btnExp = document.getElementById('ap-btn-exportar');
        if (btnExp) {
            btnExp.onclick = () => {
                const jsonStr = ap.exportarTema();
                const blob = new Blob([jsonStr], { type: 'application/json' });
                const url = URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = `prig-tema-${ap.estado.temaActivo || 'custom'}.json`;
                a.click();
                URL.revokeObjectURL(url);
            };
        }

        // Importar archivo JSON
        const fileImp = document.getElementById('ap-file-importar');
        if (fileImp) {
            fileImp.onchange = async () => {
                const file = fileImp.files[0];
                if (!file) return;
                try {
                    const text = await file.text();
                    const res = ap.importarTema(text);
                    if (res.exito) {
                        alert('¡Tema importado y aplicado con éxito!');
                        this.initApariencia('colores');
                    } else {
                        alert(`Error al importar tema: ${res.error}`);
                    }
                } catch (e) {
                    alert(`Error leyendo archivo: ${e.message}`);
                }
            };
        }

        // Importar pegando texto JSON
        const btnImpTexto = document.getElementById('ap-btn-importar-texto');
        if (btnImpTexto) {
            btnImpTexto.onclick = () => {
                const jsonStr = prompt('Pega aquí el código JSON del tema que deseas importar:');
                if (!jsonStr) return;
                const res = ap.importarTema(jsonStr);
                if (res.exito) {
                    alert('¡Tema importado y aplicado con éxito!');
                    this.initApariencia('colores');
                } else {
                    alert(`Error al importar tema: ${res.error}`);
                }
            };
        }

        // Restablecer todo
        const btnResetTodo = document.getElementById('ap-btn-restablecer-todo');
        if (btnResetTodo) {
            btnResetTodo.onclick = () => {
                if (!confirm('¿Restablecer toda la apariencia, colores y fondos a los valores de fábrica?')) return;
                ap.restablecerTodo();
                this.initApariencia('colores');
            };
        }
    }

    _renderSubTabSintaxis(container, ap) {
        const sm = window.sintaxisMgr || (window.SintaxisManager ? (window.sintaxisMgr = new window.SintaxisManager()) : null);
        if (!sm) {
            container.innerHTML = `<div style="padding: 20px; color: var(--text-muted); text-align: center;"><i class="fa-solid fa-spinner fa-spin"></i> Cargando motor de sintaxis...</div>`;
            return;
        }

        const est = sm.estado;
        const tokens = est.tokens || {};
        const glob = est.efectosGlobales || {};
        const presets = window.PRESETS_SINTAXIS_RARA || {};

        const listaTokens = [
            { key: 'keyword', label: 'Palabras Reservadas (Keywords)', desc: 'def, class, import, return, if, while, for, function, async, await', icon: 'fa-key' },
            { key: 'type', label: 'Tipos de Datos y Clases (Types)', desc: 'int, str, bool, list, dict, Promise, Any, CustomClass', icon: 'fa-cube' },
            { key: 'function', label: 'Funciones y Métodos (Functions)', desc: 'print(), len(), calculate(), render(), addEventListener()', icon: 'fa-code-branch' },
            { key: 'string', label: 'Cadenas de Texto (Strings)', desc: '"hola", \'código\', `template literal`, f"valor: {x}"', icon: 'fa-quote-right' },
            { key: 'number', label: 'Números y Literales (Numbers)', desc: '42, 3.1415, 0xFF, true, false, null, None', icon: 'fa-hashtag' },
            { key: 'comment', label: 'Comentarios y Documentación (Comments)', desc: '# explicación, // nota, /* bloque */, """docstring"""', icon: 'fa-comment-dots' },
            { key: 'operator', label: 'Operadores y Símbolos (Operators)', desc: '+, -, *, /, =>, ===, !=, &&, ||, &, |', icon: 'fa-equals' },
            { key: 'variable', label: 'Variables e Identificadores (Variables)', desc: 'mi_variable, usuario, elementos, item_id, index', icon: 'fa-i-cursor' }
        ];

        const opcionesEfectos = [
            { id: 'ninguno', label: 'Normal / Sin Efecto' },
            { id: 'glitch_rgb', label: '⚡ Fallo Glitch RGB Animado' },
            { id: 'arcoiris_animado', label: '🌈 Arcoíris Psicodélico Fluido' },
            { id: 'resplandor_neon', label: '💡 Resplandor Neón Pulsante' },
            { id: 'subrayado_onda', label: '〰️ Subrayado en Onda Neón' },
            { id: 'fuego_retro', label: '🔥 Fuego Retro Incandescente' },
            { id: 'fantasma_italica', label: '👻 Fantasma Holográfico Neón' }
        ];

        container.innerHTML = `
          <!-- 1. Galería de Presets de Sintaxis Bizarra & Abstracta -->
          <div style="background: rgba(0,0,0,0.2); border: 1px solid var(--border-color); border-radius: 8px; padding: 12px;">
            <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px;">
              <span style="font-weight: 700; color: #fff; font-size: 12px; display: flex; align-items: center; gap: 6px;">
                <i class="fa-solid fa-wand-magic-sparkles" style="color: var(--accent-purple);"></i> Presets de Sintaxis Rara & Arte Abstracto
              </span>
              <span style="font-size: 11px; color: var(--text-muted);">Aplica estéticas extremas de un solo clic</span>
            </div>
            <div style="display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 8px;">
              ${Object.entries(presets).map(([k, p]) => {
                  const activo = est.presetActivo === k;
                  const tok = p.tokens || {};
                  return `
                    <div class="ap-card-preset-sintaxis" data-preset="${k}" style="background: var(--bg-panel); border: 1.5px solid ${activo ? 'var(--accent-purple)' : 'var(--border-color)'}; border-radius: 8px; padding: 8px 10px; cursor: pointer; transition: all 0.2s ease; ${activo ? 'box-shadow: 0 0 10px rgba(203,166,247,0.3);' : ''}">
                      <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 5px;">
                        <span style="font-weight: 600; font-size: 11px; color: #fff; display: flex; align-items: center; gap: 5px;">
                          <i class="fa-solid ${p.icono || 'fa-code'}" style="color: ${tok.keyword ? tok.keyword.color : 'var(--accent-blue)'};"></i> ${p.nombre}
                        </span>
                        ${activo ? '<i class="fa-solid fa-circle-check" style="color: var(--accent-purple); font-size: 11px;"></i>' : ''}
                      </div>
                      <div style="font-size: 10px; color: var(--text-muted); margin-bottom: 6px; line-height: 1.3;">${p.desc}</div>
                      <div style="display: flex; gap: 4px; align-items: center;">
                        <span style="width: 12px; height: 12px; border-radius: 3px; background: ${tok.keyword ? tok.keyword.color : '#cba6f7'}; display: inline-block;" title="Keywords"></span>
                        <span style="width: 12px; height: 12px; border-radius: 3px; background: ${tok.function ? tok.function.color : '#89dceb'}; display: inline-block;" title="Functions"></span>
                        <span style="width: 12px; height: 12px; border-radius: 3px; background: ${tok.string ? tok.string.color : '#a6e3a1'}; display: inline-block;" title="Strings"></span>
                        <span style="width: 12px; height: 12px; border-radius: 3px; background: ${tok.number ? tok.number.color : '#fab387'}; display: inline-block;" title="Numbers"></span>
                        <span style="width: 12px; height: 12px; border-radius: 3px; background: ${tok.comment ? tok.comment.color : '#6c7086'}; display: inline-block;" title="Comments"></span>
                      </div>
                    </div>
                  `;
              }).join('')}
            </div>
          </div>

          <!-- 2. Previsualización de Código en Vivo -->
          <div style="background: rgba(0,0,0,0.25); border: 1px solid var(--border-color); border-radius: 8px; padding: 12px;">
            <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px;">
              <span style="font-weight: 700; color: #fff; font-size: 12px; display: flex; align-items: center; gap: 6px;">
                <i class="fa-solid fa-terminal" style="color: var(--accent-green);"></i> Previsualización en Vivo de Sintaxis y Efectos
              </span>
              <div style="display: flex; gap: 6px;">
                <button class="tool-btn primary" id="ap-tok-lang-py" style="font-size: 10px; padding: 3px 8px;">Python</button>
                <button class="tool-btn" id="ap-tok-lang-js" style="font-size: 10px; padding: 3px 8px;">JavaScript</button>
              </div>
            </div>
            <div id="prig-live-syntax-preview" style="background: ${ap.estado.colores.bg_editor || '#11111b'}; border: 1px solid var(--border-color); border-radius: 6px; padding: 12px 16px; font-family: 'Fira Code', 'Cascadia Code', Consolas, monospace; font-size: 12.5px; line-height: 1.7; overflow-x: auto; box-shadow: inset 0 2px 8px rgba(0,0,0,0.4);">
              <!-- Renderizado dinámico -->
            </div>
          </div>

          <!-- 3. Personalizador Detallado por Token de Sintaxis -->
          <div style="background: rgba(0,0,0,0.2); border: 1px solid var(--border-color); border-radius: 8px; padding: 12px;">
            <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 10px;">
              <span style="font-weight: 700; color: #fff; font-size: 12px; display: flex; align-items: center; gap: 6px;">
                <i class="fa-solid fa-pen-nib" style="color: var(--accent-yellow);"></i> Colores, Tipografía y Efectos por Token
              </span>
              <span style="font-size: 11px; color: var(--text-muted);">Personaliza cada categoría gramatical con efectos raros</span>
            </div>

            <div style="display: flex; flex-direction: column; gap: 8px;">
              ${listaTokens.map(tok => {
                  const cfg = tokens[tok.key] || { color: '#cdd6f4', fontStyle: '', efectoRaro: 'ninguno' };
                  const isBold = (cfg.fontStyle || '').includes('bold');
                  const isItalic = (cfg.fontStyle || '').includes('italic');
                  const isUnderline = (cfg.fontStyle || '').includes('underline');

                  return `
                    <div style="display: flex; align-items: center; justify-content: space-between; background: var(--bg-panel); border: 1px solid var(--border-color); border-radius: 6px; padding: 8px 12px; gap: 12px; flex-wrap: wrap;">
                      <div style="display: flex; align-items: center; gap: 8px; min-width: 220px; flex: 1;">
                        <i class="fa-solid ${tok.icon}" style="color: ${cfg.color}; font-size: 13px; width: 16px; text-align: center;"></i>
                        <div>
                          <div style="font-weight: 600; color: #fff; font-size: 11.5px;">${tok.label}</div>
                          <div style="font-size: 10px; color: var(--text-muted);">${tok.desc}</div>
                        </div>
                      </div>

                      <div style="display: flex; align-items: center; gap: 8px;">
                        <!-- Selector de Color -->
                        <div style="display: flex; align-items: center; gap: 4px; background: rgba(0,0,0,0.3); padding: 2px 6px; border-radius: 4px; border: 1px solid var(--border-color);">
                          <input type="color" class="ap-tok-color-picker" data-token="${tok.key}" value="${cfg.color || '#ffffff'}" style="width: 22px; height: 22px; border: none; background: transparent; cursor: pointer; border-radius: 3px; padding: 0;">
                          <input type="text" class="ap-tok-color-hex" data-token="${tok.key}" value="${cfg.color || '#ffffff'}" style="width: 65px; background: transparent; border: none; color: #fff; font-size: 11px; font-family: monospace;">
                        </div>

                        <!-- Estilos Tipográficos (B, I, U) -->
                        <div style="display: flex; gap: 2px; background: rgba(0,0,0,0.3); padding: 2px; border-radius: 4px; border: 1px solid var(--border-color);">
                          <button class="ap-tok-style-btn ${isBold ? 'active' : ''}" data-token="${tok.key}" data-style="bold" style="width: 24px; height: 24px; border: none; background: ${isBold ? 'var(--accent-blue)' : 'transparent'}; color: ${isBold ? '#111' : 'var(--text-muted)'}; border-radius: 3px; cursor: pointer; font-weight: bold; font-size: 11px;" title="Negrita">B</button>
                          <button class="ap-tok-style-btn ${isItalic ? 'active' : ''}" data-token="${tok.key}" data-style="italic" style="width: 24px; height: 24px; border: none; background: ${isItalic ? 'var(--accent-blue)' : 'transparent'}; color: ${isItalic ? '#111' : 'var(--text-muted)'}; border-radius: 3px; cursor: pointer; font-style: italic; font-size: 11px;" title="Cursiva">I</button>
                          <button class="ap-tok-style-btn ${isUnderline ? 'active' : ''}" data-token="${tok.key}" data-style="underline" style="width: 24px; height: 24px; border: none; background: ${isUnderline ? 'var(--accent-blue)' : 'transparent'}; color: ${isUnderline ? '#111' : 'var(--text-muted)'}; border-radius: 3px; cursor: pointer; text-decoration: underline; font-size: 11px;" title="Subrayado">U</button>
                        </div>

                        <!-- Selector de Efecto Raro Especial -->
                        <select class="ap-tok-efecto-sel" data-token="${tok.key}" style="padding: 4px 8px; background: rgba(0,0,0,0.4); border: 1px solid ${cfg.efectoRaro && cfg.efectoRaro !== 'ninguno' ? 'var(--accent-purple)' : 'var(--border-color)'}; color: #fff; border-radius: 4px; font-size: 11px; cursor: pointer; max-width: 200px;">
                          ${opcionesEfectos.map(ef => `<option value="${ef.id}" ${cfg.efectoRaro === ef.id ? 'selected' : ''}>${ef.label}</option>`).join('')}
                        </select>
                      </div>
                    </div>
                  `;
              }).join('')}
            </div>
          </div>

          <!-- 4. Efectos Globales del Editor & Motor de Código Libre -->
          <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 12px;">
            <!-- Efectos de Entorno -->
            <div style="background: rgba(0,0,0,0.2); border: 1px solid var(--border-color); border-radius: 8px; padding: 12px; display: flex; flex-direction: column; gap: 10px;">
              <span style="font-weight: 700; color: #fff; font-size: 12px; display: flex; align-items: center; gap: 6px;">
                <i class="fa-solid fa-tv" style="color: var(--accent-blue);"></i> Efectos Atmosféricos del Editor
              </span>

              <label style="display: flex; align-items: center; gap: 8px; font-size: 11.5px; color: #fff; cursor: pointer; background: var(--bg-panel); padding: 8px 10px; border-radius: 6px; border: 1px solid var(--border-color);">
                <input type="checkbox" id="ap-glob-scanlines" ${glob.lineasEscaneo ? 'checked' : ''} style="accent-color: var(--accent-purple);">
                <div>
                  <div style="font-weight: 600;">Líneas de Escaneo CRT Analógicas</div>
                  <div style="font-size: 10px; color: var(--text-muted);">Genera textura de monitor retro analógico sobre el código</div>
                </div>
              </label>

              <label style="display: flex; align-items: center; gap: 8px; font-size: 11.5px; color: #fff; cursor: pointer; background: var(--bg-panel); padding: 8px 10px; border-radius: 6px; border: 1px solid var(--border-color);">
                <input type="checkbox" id="ap-glob-cursor" ${glob.resplandorCursor ? 'checked' : ''} style="accent-color: var(--accent-blue);">
                <div>
                  <div style="font-weight: 600;">Cursor Neón con Resplandor Láser</div>
                  <div style="font-size: 10px; color: var(--text-muted);">Añade brillo pulsante y halo a la línea actual de edición</div>
                </div>
              </label>
            </div>

            <!-- Editor de Código CSS Libre para Monaco -->
            <div style="background: rgba(0,0,0,0.2); border: 1px solid var(--border-color); border-radius: 8px; padding: 12px; display: flex; flex-direction: column; gap: 8px;">
              <div style="display: flex; align-items: center; justify-content: space-between;">
                <span style="font-weight: 700; color: #fff; font-size: 12px; display: flex; align-items: center; gap: 6px;">
                  <i class="fa-solid fa-code" style="color: var(--accent-purple);"></i> CSS Personalizado para Monaco Editor
                </span>
                <span style="font-size: 10px; color: var(--text-muted);">Inyección directa en tiempo real</span>
              </div>
              <textarea id="ap-glob-css-input" rows="4" style="width: 100%; font-family: monospace; font-size: 11px; background: var(--bg-editor); border: 1px solid var(--border-color); color: var(--accent-green); border-radius: 6px; padding: 8px; resize: vertical;" placeholder="/* Escribe aquí reglas CSS personalizadas para Monaco Editor */&#10;.monaco-editor .view-line { letter-spacing: 0.5px; }">${glob.codigoCss || ''}</textarea>
              <div style="display: flex; gap: 6px; flex-wrap: wrap;">
                <button class="tool-btn primary" id="ap-btn-aplicar-css" style="font-size: 11px; padding: 4px 10px;">
                  <i class="fa-solid fa-bolt"></i> Ejecutar CSS
                </button>
                <button class="tool-btn" id="ap-btn-snippet-glitch" style="font-size: 10px; padding: 4px 8px;">
                  + Snippet Glitch
                </button>
                <button class="tool-btn" id="ap-btn-snippet-neon" style="font-size: 10px; padding: 4px 8px;">
                  + Snippet Aura Neón
                </button>
                <button class="tool-btn" id="ap-btn-snippet-glass" style="font-size: 10px; padding: 4px 8px;">
                  + Snippet Glassmorphism
                </button>
              </div>
            </div>
          </div>

          <!-- 5. Respaldo y Acciones de Sintaxis -->
          <div style="background: rgba(0,0,0,0.2); border: 1px solid var(--border-color); border-radius: 8px; padding: 12px; display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 8px;">
            <div style="display: flex; gap: 8px; flex-wrap: wrap;">
              <button class="tool-btn primary" id="ap-btn-exportar-sintaxis" style="font-size: 11px; padding: 6px 12px;">
                <i class="fa-solid fa-download"></i> Exportar Sintaxis (JSON)
              </button>
              <label class="tool-btn" style="cursor: pointer; font-size: 11px; padding: 6px 12px; display: inline-flex; align-items: center; gap: 6px;">
                <i class="fa-solid fa-file-import"></i> Importar Sintaxis
                <input type="file" id="ap-file-importar-sintaxis" accept=".json" style="display: none;">
              </label>
            </div>
            <button class="tool-btn" id="ap-btn-restablecer-sintaxis" style="background: rgba(243,139,168,0.15); color: var(--accent-red); border-color: rgba(243,139,168,0.4); font-size: 11px; padding: 6px 12px;">
              <i class="fa-solid fa-rotate-left"></i> Restablecer Sintaxis por Defecto
            </button>
          </div>
        `;

        // Función para renderizar el live preview
        let previewLang = 'py';
        const renderPreview = () => {
            const elPreview = document.getElementById('prig-live-syntax-preview');
            if (!elPreview) return;

            const t = sm.estado.tokens;
            const getTokStyle = (k) => {
                const cfg = t[k] || {};
                let style = `color: ${cfg.color || '#fff'};`;
                if ((cfg.fontStyle || '').includes('bold')) style += ' font-weight: bold;';
                if ((cfg.fontStyle || '').includes('italic')) style += ' font-style: italic;';
                if ((cfg.fontStyle || '').includes('underline')) style += ' text-decoration: underline;';
                return style;
            };

            const getTokClass = (k) => {
                const cfg = t[k] || {};
                return `token-${k} prig-tok-${k}`;
            };

            if (previewLang === 'py') {
                elPreview.innerHTML = `
                  <div><span class="${getTokClass('comment')}" style="${getTokStyle('comment')}"># Demostración en tiempo real de Sintaxis Personalizada & Efectos</span></div>
                  <div><span class="${getTokClass('keyword')}" style="${getTokStyle('keyword')}">from</span> <span class="${getTokClass('variable')}" style="${getTokStyle('variable')}">prig_engine</span> <span class="${getTokClass('keyword')}" style="${getTokStyle('keyword')}">import</span> <span class="${getTokClass('type')}" style="${getTokStyle('type')}">ReactorCuantico</span>, <span class="${getTokClass('type')}" style="${getTokStyle('type')}">List</span></div>
                  <div style="height: 6px;"></div>
                  <div><span class="${getTokClass('keyword')}" style="${getTokStyle('keyword')}">class</span> <span class="${getTokClass('type')}" style="${getTokStyle('type')}">GeneradorHolografico</span>:</div>
                  <div>&nbsp;&nbsp;&nbsp;&nbsp;<span class="${getTokClass('keyword')}" style="${getTokStyle('keyword')}">def</span> <span class="${getTokClass('function')}" style="${getTokStyle('function')}">__init__</span>(<span class="${getTokClass('variable')}" style="${getTokStyle('variable')}">self</span>, <span class="${getTokClass('variable')}" style="${getTokStyle('variable')}">frecuencia</span>: <span class="${getTokClass('type')}" style="${getTokStyle('type')}">float</span> = <span class="${getTokClass('number')}" style="${getTokStyle('number')}">432.0</span>):</div>
                  <div>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;<span class="${getTokClass('variable')}" style="${getTokStyle('variable')}">self</span>.<span class="${getTokClass('variable')}" style="${getTokStyle('variable')}">frecuencia</span> <span class="${getTokClass('operator')}" style="${getTokStyle('operator')}">=</span> <span class="${getTokClass('variable')}" style="${getTokStyle('variable')}">frecuencia</span></div>
                  <div>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;<span class="${getTokClass('variable')}" style="${getTokStyle('variable')}">self</span>.<span class="${getTokClass('variable')}" style="${getTokStyle('variable')}">activo</span> <span class="${getTokClass('operator')}" style="${getTokStyle('operator')}">=</span> <span class="${getTokClass('number')}" style="${getTokStyle('number')}">True</span></div>
                  <div style="height: 6px;"></div>
                  <div>&nbsp;&nbsp;&nbsp;&nbsp;<span class="${getTokClass('keyword')}" style="${getTokStyle('keyword')}">async def</span> <span class="${getTokClass('function')}" style="${getTokStyle('function')}">sintetizar_patron</span>(<span class="${getTokClass('variable')}" style="${getTokStyle('variable')}">self</span>, <span class="${getTokClass('variable')}" style="${getTokStyle('variable')}">iteraciones</span>: <span class="${getTokClass('type')}" style="${getTokStyle('type')}">int</span>) <span class="${getTokClass('operator')}" style="${getTokStyle('operator')}">-></span> <span class="${getTokClass('type')}" style="${getTokStyle('type')}">str</span>:</div>
                  <div>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;<span class="${getTokClass('comment')}" style="${getTokStyle('comment')}"># Compilando matriz de arte abstracto</span></div>
                  <div>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;<span class="${getTokClass('variable')}" style="${getTokStyle('variable')}">resultado</span> <span class="${getTokClass('operator')}" style="${getTokStyle('operator')}">=</span> <span class="${getTokClass('string')}" style="${getTokStyle('string')}">f"⚡ Sintaxis activa a {self.frecuencia} Hz"</span></div>
                  <div>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;<span class="${getTokClass('keyword')}" style="${getTokStyle('keyword')}">return</span> <span class="${getTokClass('function')}" style="${getTokStyle('function')}">str</span>(<span class="${getTokClass('variable')}" style="${getTokStyle('variable')}">resultado</span>)</div>
                `;
            } else {
                elPreview.innerHTML = `
                  <div><span class="${getTokClass('comment')}" style="${getTokStyle('comment')}">// Demostración en tiempo real de Sintaxis Personalizada & Efectos</span></div>
                  <div><span class="${getTokClass('keyword')}" style="${getTokStyle('keyword')}">import</span> { <span class="${getTokClass('type')}" style="${getTokStyle('type')}">MatrixEffect</span>, <span class="${getTokClass('type')}" style="${getTokStyle('type')}">CanvasEngine</span> } <span class="${getTokClass('keyword')}" style="${getTokStyle('keyword')}">from</span> <span class="${getTokClass('string')}" style="${getTokStyle('string')}">'@prig/core'</span>;</div>
                  <div style="height: 6px;"></div>
                  <div><span class="${getTokClass('keyword')}" style="${getTokStyle('keyword')}">export const</span> <span class="${getTokClass('function')}" style="${getTokStyle('function')}">iniciarReactor</span> <span class="${getTokClass('operator')}" style="${getTokStyle('operator')}">=</span> <span class="${getTokClass('keyword')}" style="${getTokStyle('keyword')}">async</span> (<span class="${getTokClass('variable')}" style="${getTokStyle('variable')}">potencia</span> <span class="${getTokClass('operator')}" style="${getTokStyle('operator')}">=</span> <span class="${getTokClass('number')}" style="${getTokStyle('number')}">100</span>) <span class="${getTokClass('operator')}" style="${getTokStyle('operator')}">=></span> {</div>
                  <div>&nbsp;&nbsp;&nbsp;&nbsp;<span class="${getTokClass('keyword')}" style="${getTokStyle('keyword')}">const</span> <span class="${getTokClass('variable')}" style="${getTokStyle('variable')}">estado</span> <span class="${getTokClass('operator')}" style="${getTokStyle('operator')}">=</span> { <span class="${getTokClass('variable')}" style="${getTokStyle('variable')}">nivel</span>: <span class="${getTokClass('number')}" style="${getTokStyle('number')}">99.8</span>, <span class="${getTokClass('variable')}" style="${getTokStyle('variable')}">activo</span>: <span class="${getTokClass('number')}" style="${getTokStyle('number')}">true</span> };</div>
                  <div>&nbsp;&nbsp;&nbsp;&nbsp;<span class="${getTokClass('function')}" style="${getTokStyle('function')}">console.log</span>(<span class="${getTokClass('string')}" style="${getTokStyle('string')}">\`🔥 Reactor listo con potencia: \${potencia}%\`</span>);</div>
                  <div>&nbsp;&nbsp;&nbsp;&nbsp;<span class="${getTokClass('keyword')}" style="${getTokStyle('keyword')}">return</span> <span class="${getTokClass('variable')}" style="${getTokStyle('variable')}">estado</span>;</div>
                  <div>};</div>
                `;
            }
        };

        renderPreview();

        // Botones de lenguaje para el preview
        const btnPy = document.getElementById('ap-tok-lang-py');
        const btnJs = document.getElementById('ap-tok-lang-js');
        if (btnPy && btnJs) {
            btnPy.onclick = () => {
                previewLang = 'py';
                btnPy.classList.add('primary');
                btnJs.classList.remove('primary');
                renderPreview();
            };
            btnJs.onclick = () => {
                previewLang = 'js';
                btnJs.classList.add('primary');
                btnPy.classList.remove('primary');
                renderPreview();
            };
        }

        // Selección de presets de sintaxis
        container.querySelectorAll('.ap-card-preset-sintaxis').forEach(card => {
            card.onclick = () => {
                const presetId = card.getAttribute('data-preset');
                sm.aplicarPreset(presetId);
                this.initApariencia('sintaxis');
            };
        });

        // Pickers de Color para tokens
        container.querySelectorAll('.ap-tok-color-picker').forEach(p => {
            p.oninput = () => {
                const tok = p.getAttribute('data-token');
                const val = p.value;
                const hexInput = container.querySelector(`.ap-tok-color-hex[data-token="${tok}"]`);
                if (hexInput) hexInput.value = val;
                sm.setToken(tok, 'color', val);
                renderPreview();
            };
        });

        container.querySelectorAll('.ap-tok-color-hex').forEach(h => {
            h.onchange = () => {
                const tok = h.getAttribute('data-token');
                let val = h.value.trim();
                if (!val.startsWith('#')) val = '#' + val;
                if (/^#[0-9A-F]{6}$/i.test(val) || /^#[0-9A-F]{3}$/i.test(val)) {
                    const picker = container.querySelector(`.ap-tok-color-picker[data-token="${tok}"]`);
                    if (picker) picker.value = val;
                    sm.setToken(tok, 'color', val);
                    renderPreview();
                }
            };
        });

        // Botones de estilo tipográfico (Bold, Italic, Underline)
        container.querySelectorAll('.ap-tok-style-btn').forEach(btn => {
            btn.onclick = () => {
                const tok = btn.getAttribute('data-token');
                const st = btn.getAttribute('data-style');
                let cur = (sm.estado.tokens[tok] && sm.estado.tokens[tok].fontStyle) || '';
                let parts = cur.split(' ').filter(Boolean);

                if (parts.includes(st)) {
                    parts = parts.filter(p => p !== st);
                } else {
                    parts.push(st);
                }

                const nuevoEstilo = parts.join(' ');
                sm.setToken(tok, 'fontStyle', nuevoEstilo);
                this.initApariencia('sintaxis');
            };
        });

        // Dropdowns de Efecto Raro Especial
        container.querySelectorAll('.ap-tok-efecto-sel').forEach(sel => {
            sel.onchange = () => {
                const tok = sel.getAttribute('data-token');
                const val = sel.value;
                sm.setToken(tok, 'efectoRaro', val);
                renderPreview();
            };
        });

        // Toggles globales (Scanlines y Cursor Glow)
        const chkScan = document.getElementById('ap-glob-scanlines');
        if (chkScan) {
            chkScan.onchange = () => {
                sm.setEfectoGlobal('lineasEscaneo', chkScan.checked);
            };
        }

        const chkCursor = document.getElementById('ap-glob-cursor');
        if (chkCursor) {
            chkCursor.onchange = () => {
                sm.setEfectoGlobal('resplandorCursor', chkCursor.checked);
            };
        }

        // Editor CSS y Snippets
        const txtCss = document.getElementById('ap-glob-css-input');
        const btnApplyCss = document.getElementById('ap-btn-aplicar-css');
        if (btnApplyCss && txtCss) {
            btnApplyCss.onclick = () => {
                sm.setEfectoGlobal('codigoCss', txtCss.value);
                alert('¡CSS personalizado inyectado con éxito en Monaco Editor!');
            };
        }

        const btnSnipGlitch = document.getElementById('ap-btn-snippet-glitch');
        if (btnSnipGlitch && txtCss) {
            btnSnipGlitch.onclick = () => {
                txtCss.value += `\n/* Efecto Glitch Aberrante */\n.monaco-editor .view-line {\n  animation: prigGlitchTexto 4s steps(2) infinite !important;\n}\n`;
            };
        }

        const btnSnipNeon = document.getElementById('ap-btn-snippet-neon');
        if (btnSnipNeon && txtCss) {
            btnSnipNeon.onclick = () => {
                txtCss.value += `\n/* Aura Neón Púrpura */\n.monaco-editor {\n  filter: drop-shadow(0 0 10px rgba(203, 166, 247, 0.45));\n}\n`;
            };
        }

        const btnSnipGlass = document.getElementById('ap-btn-snippet-glass');
        if (btnSnipGlass && txtCss) {
            btnSnipGlass.onclick = () => {
                txtCss.value += `\n/* Fondo Glassmorphism Monaco */\n.monaco-editor, .monaco-editor-background {\n  background: rgba(10, 5, 20, 0.75) !important;\n  backdrop-filter: blur(12px) !important;\n}\n`;
            };
        }

        // Exportar / Importar / Resetear Sintaxis
        const btnExpSint = document.getElementById('ap-btn-exportar-sintaxis');
        if (btnExpSint) {
            btnExpSint.onclick = () => {
                const jsonStr = sm.exportarJSON();
                const blob = new Blob([jsonStr], { type: 'application/json' });
                const url = URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = `prig-sintaxis-${sm.estado.presetActivo || 'custom'}.json`;
                a.click();
                URL.revokeObjectURL(url);
            };
        }

        const fileImpSint = document.getElementById('ap-file-importar-sintaxis');
        if (fileImpSint) {
            fileImpSint.onchange = async () => {
                const file = fileImpSint.files[0];
                if (!file) return;
                try {
                    const text = await file.text();
                    const res = sm.importarJSON(text);
                    if (res.exito) {
                        alert('¡Sintaxis y tokens importados con éxito!');
                        this.initApariencia('sintaxis');
                    } else {
                        alert(`Error al importar sintaxis: ${res.error}`);
                    }
                } catch (e) {
                    alert(`Error leyendo archivo: ${e.message}`);
                }
            };
        }

        const btnResetSint = document.getElementById('ap-btn-restablecer-sintaxis');
        if (btnResetSint) {
            btnResetSint.onclick = () => {
                if (!confirm('¿Restablecer todos los tokens de sintaxis a los valores por defecto?')) return;
                sm.restablecer();
                this.initApariencia('sintaxis');
            };
        }
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
