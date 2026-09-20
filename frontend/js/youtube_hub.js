/**
 * YouTubeHub - Sección educativa de YouTube en Prig IDE.
 *
 * Permite explorar videos y clases magistrales de programación, algoritmos,
 * C++, Python, Machine Learning y System Design, reproducir cualquier enlace
 * o ID de YouTube, tomar notas persistentes en Markdown y analizar conceptos
 * con el modelo de lenguaje o crear desafíos interactivos en Prig.
 */
(function () {
    const $ = (id) => document.getElementById(id);
    const esc = (t) => String(t ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

    const VIDEOS_CURADOS = [
        {
            id: 'mEsle_RQk70',
            titulo: "Let's build GPT: from scratch, in code, spelled out",
            canal: 'Andrej Karpathy',
            categoria: 'ml',
            duracion: '1:56:00',
            nivel: 'Senior',
            descripcion: 'Implementación completa de un Transformer generativo autorregresivo (GPT) desde cero en PyTorch, explicando self-attention y capas lineales.'
        },
        {
            id: 'VMj-3S1tku0',
            titulo: 'Building micrograd: The spelled-out intro to neural networks and backprop',
            canal: 'Andrej Karpathy',
            categoria: 'ml',
            duracion: '2:25:00',
            nivel: 'Intermedio / Senior',
            descripcion: 'Construcción de un motor de autograd vectorial escalar y entrenamiento de una red neuronal multicapa paso a paso.'
        },
        {
            id: 'ZA-tUyM_y7s',
            titulo: 'MIT 6.006: Introduction to Algorithms - Peak Finding & Asymptotic Complexity',
            canal: 'MIT OpenCourseWare (Erik Demaine)',
            categoria: 'algoritmos',
            duracion: '50:00',
            nivel: 'Avanzado',
            descripcion: 'Fundamentos de análisis asintótico, cotas Big-O y búsqueda de picos 1D y 2D en tiempo logarítmico.'
        },
        {
            id: 'fNk_zzaMoSs',
            titulo: 'The essence of linear algebra: Vectors, spans, and basis',
            canal: '3Blue1Brown',
            categoria: 'ml',
            duracion: '10:00',
            nivel: 'Fundamentos',
            descripcion: 'Visualización geométrica rigurosa del álgebra lineal indispensable para machine learning y visión computacional.'
        },
        {
            id: 'aircAruvnKk',
            titulo: 'But what is a neural network? | Deep learning, chapter 1',
            canal: '3Blue1Brown',
            categoria: 'ml',
            duracion: '19:00',
            nivel: 'Fundamentos',
            descripcion: 'Explicación intuitiva de perceptrones multicapa, matrices de pesos, sesgos y propagación hacia adelante.'
        },
        {
            id: '18c3MTX0PK0',
            titulo: 'How C++ Works: Compilation, Linking and Executables',
            canal: 'The Cherno',
            categoria: 'cpp',
            duracion: '20:00',
            nivel: 'Intermedio',
            descripcion: 'Qué sucede internamente cuando el compilador g++ traduce unidades de traducción (.cpp) y las enlaza en un binario.'
        },
        {
            id: 'DTxHyVn0ODg',
            titulo: 'Pointers in C++: Raw pointers, Memory addresses and Lifetimes',
            canal: 'The Cherno',
            categoria: 'cpp',
            duracion: '16:00',
            nivel: 'Intermedio / Senior',
            descripcion: 'Gestión directa de direcciones de memoria, tipos de punteros void*, desreferenciación y mejores prácticas con RAII.'
        },
        {
            id: '8hly31xKli0',
            titulo: 'Algorithms and Data Structures for Beginners - Full Course',
            canal: 'NeetCode / freeCodeCamp',
            categoria: 'algoritmos',
            duracion: '5:20:00',
            nivel: 'Senior',
            descripcion: 'Estructuras de datos esenciales: Arrays, Listas Enlazadas, Árboles BST, Heaps, Grafos y Programación Dinámica.'
        },
        {
            id: 'i53Gi_K3o7I',
            titulo: 'System Design Interview: How to Scale a System to Millions of Users',
            canal: 'ByteByteGo',
            categoria: 'system_design',
            duracion: '16:00',
            nivel: 'Senior',
            descripcion: 'Arquitectura escalable: balanceadores de carga, CDN, particionado de bases de datos, caché con Redis y microservicios.'
        },
        {
            id: '5hP30Tqjtt4',
            titulo: '0/1 Knapsack Problem - Dynamic Programming Formulation',
            canal: 'Abdul Bari',
            categoria: 'algoritmos',
            duracion: '33:00',
            nivel: 'Avanzado',
            descripcion: 'Resolución analítica paso a paso del problema de la mochila con programación dinámica y recursión memoizada.'
        },
        {
            id: '4Z8pP4Xj_Yk',
            titulo: 'Python Data Structures and Algorithms Masterclass',
            canal: 'freeCodeCamp',
            categoria: 'python',
            duracion: '4:15:00',
            nivel: 'Intermedio / Senior',
            descripcion: 'Implementación de estructuras idiomáticas en Python 3: colas de prioridad, generadores, grafos y segment trees.'
        }
    ];

    const CATEGORIAS = [
        { id: 'todas', label: 'Todos los videos' },
        { id: 'algoritmos', label: 'Algoritmos y Estructuras' },
        { id: 'cpp', label: 'C++ Moderno' },
        { id: 'python', label: 'Python Senior' },
        { id: 'ml', label: 'Machine Learning & DL' },
        { id: 'system_design', label: 'System Design' }
    ];

    const estado = {
        vista: 'catalogo', // 'catalogo' | 'reproductor'
        filtroCategoria: 'todas',
        busqueda: '',
        videoActual: null,
        pestanaLateral: 'notas', // 'notas' | 'tutor'
        chatTutor: [],
        tutorCargando: false
    };

    function extraerVideoId(cadena) {
        if (!cadena) return null;
        const texto = cadena.trim();
        if (/^[a-zA-Z0-9_-]{11}$/.test(texto)) return texto;
        const m1 = texto.match(/(?:youtube\.com\/(?:[^\/]+\/.+\/|(?:v|e(?:mbed)?)\/|.*[?&]v=)|youtu\.be\/)([^"&?\/\s]{11})/i);
        return m1 ? m1[1] : null;
    }

    function inyectarEstilos() {
        if ($('youtube-hub-estilos')) return;
        const s = document.createElement('style');
        s.id = 'youtube-hub-estilos';
        s.textContent = `
            .yt-raiz { display:flex; flex-direction:column; height:100%; width:100%; background:var(--bg-dark, #11111b); color:var(--text-main, #cdd6f4); font-family:inherit; overflow:hidden; }
            .yt-barra { display:flex; align-items:center; gap:12px; padding:12px 18px; border-bottom:1px solid var(--border-color, rgba(255,255,255,0.08)); background:var(--bg-panel, #181825); flex-shrink:0; flex-wrap:wrap; }
            .yt-logo { display:flex; align-items:center; gap:8px; font-weight:700; font-size:14px; color:#fff; }
            .yt-logo i { color:#ff0000; font-size:18px; }
            .yt-campo-buscar { flex:1; min-width:240px; max-width:540px; background:var(--bg-dark, #11111b); border:1px solid var(--border-color, rgba(255,255,255,0.12)); border-radius:8px; padding:7px 12px; color:#fff; font-size:12px; outline:none; }
            .yt-campo-buscar:focus { border-color:#ff0000; }
            .yt-btn { display:inline-flex; align-items:center; gap:6px; background:rgba(255,255,255,0.06); border:1px solid var(--border-color, rgba(255,255,255,0.1)); border-radius:7px; padding:6px 12px; color:var(--text-main, #cdd6f4); font-size:11.5px; cursor:pointer; font-weight:600; text-decoration:none; transition:all 0.15s; }
            .yt-btn:hover { background:rgba(255,255,255,0.12); color:#fff; }
            .yt-btn.rojo { background:rgba(255,0,0,0.16); border-color:rgba(255,0,0,0.4); color:#ff5555; }
            .yt-btn.rojo:hover { background:#ff0000; color:#fff; }
            .yt-btn.azul { background:rgba(137,180,250,0.14); border-color:rgba(137,180,250,0.35); color:var(--accent-blue, #89b4fa); }
            .yt-btn.verde { background:rgba(166,227,161,0.14); border-color:rgba(166,227,161,0.35); color:var(--accent-green, #a6e3a1); }
            .yt-btn.morado { background:rgba(203,166,247,0.14); border-color:rgba(203,166,247,0.35); color:var(--accent-purple, #cba6f7); }

            .yt-chips { display:flex; gap:6px; padding:10px 18px; border-bottom:1px solid var(--border-color, rgba(255,255,255,0.06)); background:var(--bg-panel, #181825); overflow-x:auto; flex-shrink:0; scrollbar-width:none; }
            .yt-chip { padding:4px 10px; border-radius:20px; font-size:11px; background:rgba(255,255,255,0.05); color:var(--text-muted, #a6adc8); border:1px solid transparent; cursor:pointer; white-space:nowrap; }
            .yt-chip:hover { color:#fff; background:rgba(255,255,255,0.09); }
            .yt-chip.activo { background:rgba(255,0,0,0.15); border-color:rgba(255,0,0,0.4); color:#ff6666; font-weight:700; }

            .yt-cuerpo { flex:1; overflow-y:auto; padding:20px; }
            .yt-grid { display:grid; grid-template-columns:repeat(auto-fill, minmax(290px, 1fr)); gap:16px; }
            .yt-tarjeta { background:var(--bg-panel, #181825); border:1px solid var(--border-color, rgba(255,255,255,0.08)); border-radius:10px; overflow:hidden; display:flex; flex-direction:column; cursor:pointer; transition:transform 0.15s, border-color 0.15s, box-shadow 0.15s; }
            .yt-tarjeta:hover { transform:translateY(-2px); border-color:rgba(255,0,0,0.45); box-shadow:0 6px 18px rgba(0,0,0,0.4); }
            .yt-miniatura { position:relative; width:100%; aspect-ratio:16/9; background:#000; overflow:hidden; }
            .yt-miniatura img { width:100%; height:100%; object-fit:cover; display:block; }
            .yt-duracion { position:absolute; bottom:6px; right:6px; background:rgba(0,0,0,0.8); color:#fff; font-size:10px; padding:2px 5px; border-radius:4px; font-weight:600; }
            .yt-nivel { position:absolute; top:6px; left:6px; background:rgba(203,166,247,0.85); color:#111; font-size:9.5px; padding:2px 6px; border-radius:4px; font-weight:700; }
            .yt-tarjeta-info { padding:12px; display:flex; flex-direction:column; flex:1; gap:6px; }
            .yt-tarjeta-titulo { font-size:12.5px; font-weight:600; color:#fff; line-height:1.4; margin:0; display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; overflow:hidden; }
            .yt-tarjeta-canal { font-size:11px; color:var(--text-muted, #a6adc8); }
            .yt-tarjeta-desc { font-size:11px; color:var(--text-muted, #9399b2); line-height:1.35; margin:0; display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; overflow:hidden; }

            /* Reproductor */
            .yt-player-layout { display:grid; grid-template-columns:1fr 370px; height:100%; min-height:0; overflow:hidden; }
            @media (max-width: 900px) { .yt-player-layout { grid-template-columns:1fr; grid-template-rows:1fr 1fr; } }
            .yt-player-main { display:flex; flex-direction:column; height:100%; min-height:0; overflow-y:auto; padding:18px; gap:14px; }
            .yt-iframe-wrap { width:100%; aspect-ratio:16/9; background:#000; border-radius:10px; overflow:hidden; border:1px solid var(--border-color, rgba(255,255,255,0.1)); flex-shrink:0; }
            .yt-iframe-wrap iframe { width:100%; height:100%; border:none; display:block; }
            .yt-info-video { display:flex; flex-direction:column; gap:8px; }
            .yt-video-titulo { font-size:16px; font-weight:700; color:#fff; margin:0; }
            .yt-acciones-video { display:flex; gap:8px; flex-wrap:wrap; align-items:center; }

            /* Panel Lateral */
            .yt-lateral { border-left:1px solid var(--border-color, rgba(255,255,255,0.08)); background:var(--bg-panel, #181825); display:flex; flex-direction:column; height:100%; min-height:0; overflow:hidden; }
            .yt-lateral-tabs { display:flex; border-bottom:1px solid var(--border-color, rgba(255,255,255,0.08)); background:rgba(0,0,0,0.15); flex-shrink:0; }
            .yt-lateral-tab { flex:1; padding:10px; font-size:11.5px; font-weight:600; text-align:center; cursor:pointer; color:var(--text-muted, #a6adc8); border-bottom:2px solid transparent; }
            .yt-lateral-tab.activo { color:#fff; border-bottom-color:#ff0000; background:rgba(255,255,255,0.03); }
            .yt-lateral-cuerpo { flex:1; min-height:0; overflow-y:auto; padding:12px; display:flex; flex-direction:column; gap:10px; }
            .yt-textarea-nota { width:100%; flex:1; min-height:160px; background:var(--bg-dark, #11111b); border:1px solid var(--border-color, rgba(255,255,255,0.1)); border-radius:8px; padding:10px; color:#fff; font-family:'Fira Code', monospace; font-size:11.5px; line-height:1.5; resize:none; outline:none; }
            .yt-textarea-nota:focus { border-color:var(--accent-blue, #89b4fa); }
            .yt-chat-mensajes { flex:1; min-height:0; overflow-y:auto; display:flex; flex-direction:column; gap:8px; }
            .yt-chat-msg { padding:8px 12px; border-radius:8px; font-size:11.5px; line-height:1.45; }
            .yt-chat-msg.usuario { background:rgba(137,180,250,0.15); border:1px solid rgba(137,180,250,0.3); color:#89b4fa; align-self:flex-end; }
            .yt-chat-msg.tutor { background:rgba(255,255,255,0.05); border:1px solid var(--border-color, rgba(255,255,255,0.08)); color:#cdd6f4; align-self:flex-start; }
            .yt-chat-form { display:flex; gap:6px; margin-top:auto; flex-shrink:0; }
            .yt-chat-input { flex:1; background:var(--bg-dark, #11111b); border:1px solid var(--border-color, rgba(255,255,255,0.1)); border-radius:7px; padding:6px 10px; color:#fff; font-size:11.5px; outline:none; }
            .yt-chat-input:focus { border-color:#ff0000; }
        `;
        document.head.appendChild(s);
    }

    function pintar() {
        inyectarEstilos();
        const raiz = $('youtube-raiz');
        if (!raiz) return;

        if (estado.vista === 'reproductor' && estado.videoActual) {
            pintarReproductor(raiz);
        } else {
            pintarCatalogo(raiz);
        }
    }

    function pintarCatalogo(raiz) {
        const busq = estado.busqueda.toLowerCase().trim();
        const filtrados = VIDEOS_CURADOS.filter(v => {
            const coincideCat = estado.filtroCategoria === 'todas' || v.categoria === estado.filtroCategoria;
            const coincideTexto = !busq || v.titulo.toLowerCase().includes(busq) || v.canal.toLowerCase().includes(busq) || v.descripcion.toLowerCase().includes(busq);
            return coincideCat && coincideTexto;
        });

        raiz.innerHTML = `
            <div class="yt-raiz">
              <div class="yt-barra">
                <div class="yt-logo"><i class="fa-brands fa-youtube"></i> YouTube en Prig</div>
                <input id="yt-input-buscar" class="yt-campo-buscar" placeholder="Pega un enlace de YouTube (https://...) o busca por tema..." value="${esc(estado.busqueda)}">
                <button class="yt-btn rojo" id="yt-btn-cargar"><i class="fa-solid fa-play"></i> Reproducir</button>
              </div>

              <div class="yt-chips">
                ${CATEGORIAS.map(c => `
                  <button class="yt-chip ${estado.filtroCategoria === c.id ? 'activo' : ''}" data-cat="${c.id}">${esc(c.label)}</button>
                `).join('')}
              </div>

              <div class="yt-cuerpo">
                ${filtrados.length === 0 ? `
                  <div style="text-align:center; padding:40px; color:var(--text-muted);">
                    <i class="fa-brands fa-youtube" style="font-size:40px; opacity:0.3; margin-bottom:12px; display:block;"></i>
                    <p style="margin:0; font-size:13px;">No se encontraron videos con ese criterio.</p>
                    <p style="margin:6px 0 0; font-size:11.5px;">Puedes pegar directamente cualquier URL de video de YouTube arriba y pulsar <b>Reproducir</b>.</p>
                  </div>
                ` : `
                  <div class="yt-grid">
                    ${filtrados.map(v => `
                      <div class="yt-tarjeta" data-video-id="${esc(v.id)}">
                        <div class="yt-miniatura">
                          <img src="https://i.ytimg.com/vi/${esc(v.id)}/hqdefault.jpg" alt="${esc(v.titulo)}" loading="lazy">
                          <span class="yt-duracion">${esc(v.duracion)}</span>
                          <span class="yt-nivel">${esc(v.nivel)}</span>
                        </div>
                        <div class="yt-tarjeta-info">
                          <h3 class="yt-tarjeta-titulo">${esc(v.titulo)}</h3>
                          <div class="yt-tarjeta-canal"><i class="fa-solid fa-circle-check" style="color:#ff0000; font-size:10px;"></i> ${esc(v.canal)}</div>
                          <p class="yt-tarjeta-desc">${esc(v.descripcion)}</p>
                        </div>
                      </div>
                    `).join('')}
                  </div>
                `}
              </div>
            </div>
        `;

        const inp = $('yt-input-buscar');
        if (inp) {
            inp.oninput = () => { estado.busqueda = inp.value; };
            inp.onkeydown = (e) => {
                if (e.key === 'Enter') procesarEntradaOUrl(inp.value);
            };
        }

        const btnCargar = $('yt-btn-cargar');
        if (btnCargar && inp) {
            btnCargar.onclick = () => procesarEntradaOUrl(inp.value);
        }

        raiz.querySelectorAll('.yt-chip').forEach(ch => {
            ch.onclick = () => {
                estado.filtroCategoria = ch.dataset.cat;
                pintar();
            };
        });

        raiz.querySelectorAll('.yt-tarjeta').forEach(tar => {
            tar.onclick = () => {
                const vidId = tar.dataset.videoId;
                const encontrado = VIDEOS_CURADOS.find(v => v.id === vidId) || { id: vidId, titulo: 'Video de YouTube', canal: 'YouTube' };
                reproducir(encontrado);
            };
        });
    }

    function procesarEntradaOUrl(texto) {
        if (!texto || !texto.trim()) return;
        const vidId = extraerVideoId(texto);
        if (vidId) {
            const existente = VIDEOS_CURADOS.find(v => v.id === vidId);
            reproducir(existente || {
                id: vidId,
                titulo: `Video de YouTube (${vidId})`,
                canal: 'YouTube',
                descripcion: 'Video cargado mediante enlace directo.'
            });
        } else {
            estado.busqueda = texto.trim();
            pintar();
        }
    }

    function reproducir(video) {
        estado.videoActual = video;
        estado.vista = 'reproductor';
        pintar();
    }

    function pintarReproductor(raiz) {
        const v = estado.videoActual;
        const notaClave = `prig_yt_nota_${v.id}`;
        const notaGuardada = localStorage.getItem(notaClave) || '';

        raiz.innerHTML = `
            <div class="yt-raiz">
              <div class="yt-barra">
                <button class="yt-btn" id="yt-btn-volver"><i class="fa-solid fa-arrow-left"></i> Catálogo</button>
                <div class="yt-logo" style="margin-left:6px;"><i class="fa-brands fa-youtube"></i> ${esc(v.titulo)}</div>
                <div style="margin-left:auto; display:flex; gap:8px;">
                  <a class="yt-btn" href="https://www.youtube.com/watch?v=${esc(v.id)}" target="_blank" rel="noopener noreferrer"><i class="fa-solid fa-arrow-up-right-from-square"></i> Abrir en YouTube</a>
                </div>
              </div>

              <div class="yt-player-layout">
                <div class="yt-player-main">
                  <div class="yt-iframe-wrap">
                    <iframe src="https://www.youtube-nocookie.com/embed/${esc(v.id)}?autoplay=1&rel=0" allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture" allowfullscreen></iframe>
                  </div>

                  <div class="yt-info-video">
                    <h2 class="yt-video-titulo">${esc(v.titulo)}</h2>
                    <div style="font-size:12px; color:var(--text-muted);">Canal: <b>${esc(v.canal || 'YouTube')}</b> ${v.nivel ? `· Nivel: <span style="color:var(--accent-purple); font-weight:600;">${esc(v.nivel)}</span>` : ''}</div>
                    ${v.descripcion ? `<p style="margin:4px 0 0; font-size:12px; color:var(--text-muted); line-height:1.45;">${esc(v.descripcion)}</p>` : ''}

                    <div class="yt-acciones-video" style="margin-top:8px;">
                      <button class="yt-btn azul" id="yt-btn-crear-desafio"><i class="fa-solid fa-wand-magic-sparkles"></i> Crear desafío en Prig con este tema</button>
                      <button class="yt-btn morado" id="yt-btn-explicar-tema"><i class="fa-solid fa-brain"></i> Explicar conceptos con IA</button>
                    </div>
                  </div>
                </div>

                <div class="yt-lateral">
                  <div class="yt-lateral-tabs">
                    <div class="yt-lateral-tab ${estado.pestanaLateral === 'notas' ? 'activo' : ''}" data-tab="notas"><i class="fa-solid fa-pencil"></i> Notas</div>
                    <div class="yt-lateral-tab ${estado.pestanaLateral === 'tutor' ? 'activo' : ''}" data-tab="tutor"><i class="fa-solid fa-robot"></i> Asistente IA</div>
                  </div>

                  <div class="yt-lateral-cuerpo">
                    ${estado.pestanaLateral === 'notas' ? `
                      <div style="font-size:11px; color:var(--text-muted); display:flex; justify-content:space-between; align-items:center;">
                        <span>Apuntes de la clase (guardado automático)</span>
                        <button class="yt-btn verde" id="yt-btn-guardar-archivo" style="padding:3px 7px; font-size:10px;"><i class="fa-solid fa-file-export"></i> Exportar a archivo</button>
                      </div>
                      <textarea id="yt-nota" class="yt-textarea-nota" placeholder="Escribe aquí tus notas, timestamps y fórmulas mientras miras el video...">${esc(notaGuardada)}</textarea>
                    ` : `
                      <div class="yt-chat-mensajes" id="yt-chat-mensajes">
                        ${estado.chatTutor.length === 0 ? `
                          <div style="text-align:center; padding:20px; color:var(--text-muted); font-size:11.5px;">
                            <i class="fa-solid fa-graduation-cap" style="font-size:24px; opacity:0.4; margin-bottom:8px; display:block;"></i>
                            Haz preguntas sobre los conceptos del video, pide ejercicios prácticos o un resumen estructurado.
                          </div>
                        ` : estado.chatTutor.map(m => `
                          <div class="yt-chat-msg ${m.rol}">${esc(m.texto)}</div>
                        `).join('')}
                      </div>
                      <div class="yt-chat-form">
                        <input id="yt-chat-input" class="yt-chat-input" placeholder="Pregunta sobre este video..." ${estado.tutorCargando ? 'disabled' : ''}>
                        <button class="yt-btn rojo" id="yt-chat-enviar" ${estado.tutorCargando ? 'disabled' : ''}><i class="fa-solid fa-paper-plane"></i></button>
                      </div>
                    `}
                  </div>
                </div>
              </div>
            </div>
        `;

        $('yt-btn-volver').onclick = () => {
            estado.vista = 'catalogo';
            pintar();
        };

        raiz.querySelectorAll('.yt-lateral-tab').forEach(tb => {
            tb.onclick = () => {
                estado.pestanaLateral = tb.dataset.tab;
                pintar();
            };
        });

        const notaEl = $('yt-nota');
        if (notaEl) {
            notaEl.oninput = () => {
                localStorage.setItem(notaClave, notaEl.value);
            };
        }

        const btnExportar = $('yt-btn-guardar-archivo');
        if (btnExportar && notaEl) {
            btnExportar.onclick = async () => {
                const contenido = notaEl.value;
                if (!contenido.trim()) return alert('Escribe primero algunas notas para exportar.');
                const sugerido = `nota_${v.titulo.toLowerCase().replace(/[^a-z0-9]/g, '_').slice(0, 30)}.md`;
                const nombre = prompt('Nombre del archivo de notas:', sugerido);
                if (!nombre) return;
                try {
                    await window.prigFetchJson('/api/files/write', {
                        method: 'POST',
                        body: JSON.stringify({ path: nombre, content: `# Notas: ${v.titulo}\nCanal: ${v.canal}\nURL: https://www.youtube.com/watch?v=${v.id}\n\n${contenido}` })
                    });
                    alert(`Notas guardadas en el proyecto como: ${nombre}`);
                } catch (e) {
                    alert('Error guardando archivo: ' + e.message);
                }
            };
        }

        const btnDesafio = $('yt-btn-crear-desafio');
        if (btnDesafio) {
            btnDesafio.onclick = () => {
                if (window.Desafios) {
                    window.Desafios.abrir({ tema: v.titulo });
                }
            };
        }

        const btnExplicar = $('yt-btn-explicar-tema');
        if (btnExplicar) {
            btnExplicar.onclick = () => {
                estado.pestanaLateral = 'tutor';
                pintar();
                const pregunta = `Explica los conceptos clave, relevancia y mejores prácticas de: "${v.titulo}" (${v.descripcion || ''}).`;
                enviarPreguntaTutor(pregunta);
            };
        }

        const chatInput = $('yt-chat-input');
        const chatEnviar = $('yt-chat-enviar');
        if (chatInput && chatEnviar) {
            const enviar = () => {
                const t = chatInput.value.trim();
                if (!t || estado.tutorCargando) return;
                chatInput.value = '';
                enviarPreguntaTutor(t);
            };
            chatEnviar.onclick = enviar;
            chatInput.onkeydown = (e) => { if (e.key === 'Enter') enviar(); };
        }
    }

    async function enviarPreguntaTutor(pregunta) {
        const v = estado.videoActual;
        estado.chatTutor.push({ rol: 'usuario', texto: pregunta });
        const respItem = { rol: 'tutor', texto: 'Pensando…' };
        estado.chatTutor.push(respItem);
        estado.tutorCargando = true;
        pintar();

        try {
            const r = await window.prigFetchJson('/api/ai/chat', {
                method: 'POST',
                body: JSON.stringify({
                    prompt: `El usuario está viendo el video de YouTube educativo: "${v.titulo}" del canal "${v.canal}".\nConsulta del usuario: ${pregunta}`,
                    mode: 'tutor'
                })
            });
            respItem.texto = r && (r.response || r.texto || r.content) ? (r.response || r.texto || r.content) : 'Respuesta procesada correctamente.';
        } catch (e) {
            respItem.texto = `*Error al consultar al tutor: ${e.message}*`;
        } finally {
            estado.tutorCargando = false;
            pintar();
        }
    }

    function abrir(opciones = {}) {
        if (window.workArea) {
            window.workArea.abrirHerramienta('modal-youtube', 'YouTube', 'fa-brands fa-youtube');
        } else {
            const m = $('modal-youtube');
            if (m) m.style.display = 'flex';
        }
        if (opciones.videoId || opciones.url) {
            const id = extraerVideoId(opciones.videoId || opciones.url);
            if (id) {
                const vid = VIDEOS_CURADOS.find(x => x.id === id) || { id, titulo: 'Video de YouTube', canal: 'YouTube' };
                reproducir(vid);
                return;
            }
        }
        pintar();
    }

    document.addEventListener('prig:herramienta-abierta', (e) => {
        if (e.detail && e.detail.modalId === 'modal-youtube') {
            pintar();
        }
    });

    window.YouTubeHub = {
        abrir,
        reproducir,
        pintar,
        estado,
        VIDEOS_CURADOS
    };
})();
