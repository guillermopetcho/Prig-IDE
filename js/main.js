/**
 * ============================================================================
 * PRIG IDE · JAVASCRIPT PRINCIPAL PARA GITHUB PAGES
 * Interacciones: Canvas de Partículas, Personaje ASCII en Vivo, Tabs Interactivos, Lightbox y Demos
 * ============================================================================
 */

(function () {
    'use strict';

    // 1. LIENZO DE FONDO CON CONSTELACIÓN DE PARTÍCULAS (60 FPS)
    function initBackgroundCanvas() {
        const canvas = document.getElementById('bg-canvas');
        if (!canvas) return;
        const ctx = canvas.getContext('2d');
        let w = canvas.width = window.innerWidth;
        let h = canvas.height = window.innerHeight;

        const numParticles = Math.min(80, Math.floor(w * 0.05));
        const particles = [];
        const mouse = { x: -1000, y: -1000, radius: 140 };

        for (let i = 0; i < numParticles; i++) {
            particles.push({
                x: Math.random() * w,
                y: Math.random() * h,
                vx: (Math.random() - 0.5) * 0.6,
                vy: (Math.random() - 0.5) * 0.6,
                radius: Math.random() * 2 + 1,
                color: ['#89b4fa', '#cba6f7', '#89dceb', '#a6e3a1'][Math.floor(Math.random() * 4)]
            });
        }

        window.addEventListener('resize', () => {
            w = canvas.width = window.innerWidth;
            h = canvas.height = window.innerHeight;
        });

        window.addEventListener('mousemove', (e) => {
            mouse.x = e.clientX;
            mouse.y = e.clientY;
        });

        function animate() {
            ctx.clearRect(0, 0, w, h);

            for (let i = 0; i < particles.length; i++) {
                const p = particles[i];
                p.x += p.vx;
                p.y += p.vy;

                if (p.x < 0 || p.x > w) p.vx *= -1;
                if (p.y < 0 || p.y > h) p.vy *= -1;

                const dx = mouse.x - p.x;
                const dy = mouse.y - p.y;
                const dist = Math.sqrt(dx * dx + dy * dy);
                if (dist < mouse.radius) {
                    const force = (mouse.radius - dist) / mouse.radius;
                    p.x -= (dx / dist) * force * 2;
                    p.y -= (dy / dist) * force * 2;
                }

                ctx.beginPath();
                ctx.arc(p.x, p.y, p.radius, 0, Math.PI * 2);
                ctx.fillStyle = p.color;
                ctx.globalAlpha = 0.45;
                ctx.fill();

                for (let j = i + 1; j < particles.length; j++) {
                    const p2 = particles[j];
                    const distP = Math.hypot(p.x - p2.x, p.y - p2.y);
                    if (distP < 115) {
                        ctx.beginPath();
                        ctx.moveTo(p.x, p.y);
                        ctx.lineTo(p2.x, p2.y);
                        ctx.strokeStyle = '#89b4fa';
                        ctx.globalAlpha = (1.0 - (distP / 115)) * 0.16;
                        ctx.lineWidth = 0.8;
                        ctx.stroke();
                    }
                }
            }

            requestAnimationFrame(animate);
        }

        animate();
    }

    // 2. SIMULADOR INTERACTIVO DE PERSONAJE ASCII EN HERO
    function initHeroCharacter() {
        const canvas = document.getElementById('hero-character-canvas');
        if (!canvas) return;
        const ctx = canvas.getContext('2d');
        const dpr = window.devicePixelRatio || 1;

        function resizeCanvas() {
            const rect = canvas.getBoundingClientRect();
            canvas.width = rect.width * dpr;
            canvas.height = rect.height * dpr;
            ctx.scale(dpr, dpr);
        }
        resizeCanvas();
        window.addEventListener('resize', resizeCanvas);

        const arteMecha = [
            "         /| ___________________ |\\",
            "       /  | [ TITAN MECHA 7B ] |  \\",
            "      |  / \\_________________/ \\  |",
            "      | |   (O)           (O)   | |",
            "      | |      \\___=___/       | |",
            "      |  \\     | :::: |      /  |",
            "     /    \\____|======|____/    \\",
            "    / /|     |  [CORE]  |     |\\ \\",
            "   | | |     |  SYNAPSE |     | | |",
            "   | | |_____|__________|_____| | |",
            "    \\ \\______/  /====\\  \\______/ /",
            "     \\_________/      \\_________/"
        ];

        let time = 0;
        let mousePos = { x: 180, y: 160 };

        canvas.addEventListener('mousemove', (e) => {
            const rect = canvas.getBoundingClientRect();
            mousePos.x = e.clientX - rect.left;
            mousePos.y = e.clientY - rect.top;
        });

        function renderCharacter() {
            const rect = canvas.getBoundingClientRect();
            const w = rect.width;
            const h = rect.height;

            ctx.clearRect(0, 0, w, h);
            time += 0.035;

            // Retícula de fondo cyber
            ctx.strokeStyle = 'rgba(137, 180, 250, 0.06)';
            ctx.lineWidth = 1;
            for (let x = 0; x < w; x += 24) {
                ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, h); ctx.stroke();
            }
            for (let y = 0; y < h; y += 24) {
                ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(w, y); ctx.stroke();
            }

            const flotacion = Math.sin(time) * 8;
            const charX = w * 0.5;
            const charY = h * 0.42 + flotacion;

            // Renderizar arte ASCII del robot
            ctx.font = 'bold 9px "Fira Code", monospace';
            ctx.textAlign = 'center';
            ctx.fillStyle = '#a6e3a1';
            ctx.shadowColor = 'rgba(166, 227, 161, 0.6)';
            ctx.shadowBlur = 8;

            const lineHeight = 12;
            const totalH = arteMecha.length * lineHeight;
            const startY = charY - totalH / 2;

            arteMecha.forEach((linea, idx) => {
                ctx.fillText(linea, charX, startY + idx * lineHeight);
            });

            ctx.shadowBlur = 0;

            // Puntero láser hacia el cursor
            ctx.strokeStyle = '#cba6f7';
            ctx.lineWidth = 1.2;
            ctx.setLineDash([4, 4]);
            ctx.lineDashOffset = -time * 20;
            ctx.beginPath();
            ctx.moveTo(charX, charY + 20);
            ctx.lineTo(mousePos.x, mousePos.y);
            ctx.stroke();
            ctx.setLineDash([]);

            // Puntero en cursor
            ctx.fillStyle = '#cba6f7';
            ctx.beginPath();
            ctx.arc(mousePos.x, mousePos.y, 4, 0, Math.PI * 2);
            ctx.fill();

            // Bocadillo de diálogo del modelo
            const bubbleY = 24;
            ctx.fillStyle = 'rgba(24, 24, 37, 0.9)';
            ctx.fillRect(w * 0.08, bubbleY, w * 0.84, 30);
            ctx.strokeStyle = '#cba6f7';
            ctx.lineWidth = 1;
            ctx.strokeRect(w * 0.08, bubbleY, w * 0.84, 30);

            ctx.font = 'bold 8.5px "Fira Code", monospace';
            ctx.fillStyle = '#cdd6f4';
            ctx.fillText('💬 7B DIRECTOR: "Analizando AST, CFG y telemetría en tiempo real."', charX, bubbleY + 19);

            requestAnimationFrame(renderCharacter);
        }

        renderCharacter();
    }

    // 3. TABS INTERACTIVOS PARA SHOWCASE DE 4 MODOS
    function initShowcaseTabs() {
        const tabs = document.querySelectorAll('.showcase-tab');
        const contents = document.querySelectorAll('.showcase-content');

        if (!tabs.length || !contents.length) return;

        tabs.forEach(tab => {
            tab.addEventListener('click', () => {
                const targetId = tab.dataset.tab;
                if (!targetId) return;

                tabs.forEach(t => t.classList.remove('active'));
                contents.forEach(c => c.classList.remove('active'));

                tab.classList.add('active');
                const targetContent = document.getElementById(targetId);
                if (targetContent) {
                    targetContent.classList.add('active');
                }
            });
        });
    }

    // 4. LIGHTBOX DE CAPTURAS
    function initLightbox() {
        const modal = document.getElementById('lightbox-modal');
        const modalImg = document.getElementById('lightbox-img');
        const closeBtn = document.getElementById('lightbox-close');

        if (!modal || !modalImg) return;

        document.querySelectorAll('.gallery-card').forEach(card => {
            card.addEventListener('click', () => {
                const img = card.querySelector('img');
                if (img) {
                    modalImg.src = img.src;
                    modal.classList.add('active');
                }
            });
        });

        if (closeBtn) {
            closeBtn.addEventListener('click', () => modal.classList.remove('active'));
        }

        modal.addEventListener('click', (e) => {
            if (e.target === modal) modal.classList.remove('active');
        });

        window.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && modal.classList.contains('active')) {
                modal.classList.remove('active');
            }
        });
    }

    // 5. COPIAR COMANDOS AL PORTAPAPELES
    function initCopyButtons() {
        document.querySelectorAll('.btn-copy').forEach(btn => {
            btn.addEventListener('click', () => {
                const cmd = btn.dataset.cmd;
                if (!cmd) return;
                navigator.clipboard.writeText(cmd).then(() => {
                    const originalText = btn.innerHTML;
                    btn.innerHTML = '<i class="fa-solid fa-check"></i> ¡Copiado!';
                    btn.style.background = '#a6e3a1';
                    btn.style.color = '#0b0d17';
                    setTimeout(() => {
                        btn.innerHTML = originalText;
                        btn.style.background = '';
                        btn.style.color = '';
                    }, 2000);
                });
            });
        });
    }

    // Inicializar todo al cargar el DOM
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => {
            initBackgroundCanvas();
            initHeroCharacter();
            initShowcaseTabs();
            initLightbox();
            initCopyButtons();
        });
    } else {
        initBackgroundCanvas();
        initHeroCharacter();
        initShowcaseTabs();
        initLightbox();
        initCopyButtons();
    }

})();
