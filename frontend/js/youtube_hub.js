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
        // ==================== PYTHON ====================
        {
            id: 'nLRL_NcnK-4',
            titulo: 'Harvard CS50P – Introduction to Programming with Python',
            canal: 'freeCodeCamp / Harvard (David J. Malan)',
            categoria: 'python',
            duracion: '15:56:00',
            nivel: 'Principiante / Intermedio',
            idioma: 'EN',
            descripcion: 'El curso universitario completo de Harvard sobre Python: funciones, bucles, excepciones, librerías, pruebas unitarias con pytest, POO y expresiones regulares.'
        },
        {
            id: 'rfscVS0vtbw',
            titulo: 'Aprende Python – Curso Completo de Python desde Cero',
            canal: 'freeCodeCamp Español (Estefania)',
            categoria: 'python',
            duracion: '4:26:00',
            nivel: 'Principiante',
            idioma: 'ES',
            descripcion: 'Fundamentos exhaustivos de Python 3 en español: tipos de datos, listas, tuplas, diccionarios, bucles for/while, funciones y proyectos prácticos.'
        },
        {
            id: '_uDW4ayzTQg',
            titulo: 'Python Full Course for Beginners',
            canal: 'Programming with Mosh',
            categoria: 'python',
            duracion: '6:14:00',
            nivel: 'Principiante / Intermedio',
            idioma: 'EN',
            descripcion: 'Formación práctica en Python: control de flujo, estructuras de datos nativas, programación orientada a objetos, manejo de excepciones y automatización.'
        },
        {
            id: 'XKHEtdqhLK8',
            titulo: 'Python Full Course for free (12 Horas Completas)',
            canal: 'Bro Code',
            categoria: 'python',
            duracion: '12:00:00',
            nivel: 'Principiante / Intermedio',
            idioma: 'EN',
            descripcion: 'Guía enciclopédica de 12 horas: sintaxis, POO, multithreading, decoradores, generadores, interfaces gráficas con Tkinter y sockets de red.'
        },
        {
            id: 'eWRuo9TUUTY',
            titulo: 'Curso de PYTHON desde CERO (Completo)',
            canal: 'Soy Dalto',
            categoria: 'python',
            duracion: '8:05:00',
            nivel: 'Principiante / Intermedio',
            idioma: 'ES',
            descripcion: 'Curso intensivo de 8 horas desde nivel cero hasta conceptos avanzados: lambdas, modularización, archivos y programación orientada a objetos en español.'
        },
        {
            id: 'chPhlsHoEPo',
            titulo: 'Curso Python para Principiantes',
            canal: 'Fazt Code',
            categoria: 'python',
            duracion: '3:55:00',
            nivel: 'Principiante',
            idioma: 'ES',
            descripcion: 'Tutorial integral paso a paso de Python para crear aplicaciones, scripts de automatización y backend estructurado.'
        },
        {
            id: 'ZDa-Z5JzLYM',
            titulo: 'Python OOP Masterclass: Classes, Inheritance & Dunders',
            canal: 'Corey Schafer',
            categoria: 'python',
            duracion: '45:00',
            nivel: 'Intermedio / Senior',
            idioma: 'EN',
            descripcion: 'Explicación magistral sobre programación orientada a objetos: métodos de clase, estáticos, herencia, métodos mágicos dunder y property decorators.'
        },
        {
            id: '4Z8pP4Xj_Yk',
            titulo: 'Python Data Structures and Algorithms Masterclass',
            canal: 'freeCodeCamp / Jovian',
            categoria: 'python',
            duracion: '4:15:00',
            nivel: 'Intermedio / Senior',
            idioma: 'EN',
            descripcion: 'Implementación de algoritmos y estructuras de datos en Python: árboles binarios de búsqueda, grafos, Dijkstra y programación dinámica.'
        },

        // ==================== C++ ====================
        {
            id: '8jLOx1hD3_o',
            titulo: 'C++ Programming Course – Beginner to Advanced (C++20)',
            canal: 'freeCodeCamp (Daniel Gakwaya)',
            categoria: 'cpp',
            duracion: '31:20:00',
            nivel: 'Principiante / Senior',
            idioma: 'EN',
            descripcion: 'El curso definitivo de C++ moderno (C++20) de 31 horas: punteros, gestión del heap, RAII, conceptos (concepts), templates y la STL completa.'
        },
        {
            id: 'vLnPwxZdW4Y',
            titulo: 'C++ Tutorial for Beginners – Full Course',
            canal: 'freeCodeCamp (Mike Dane)',
            categoria: 'cpp',
            duracion: '4:01:00',
            nivel: 'Principiante',
            idioma: 'EN',
            descripcion: 'Fundamentos sólidos de C++: tipos primitivos, condicionales, punteros, direcciones de memoria, constructores y clases.'
        },
        {
            id: '-TkoO8Z07hI',
            titulo: 'C++ Full Course for free (6 Horas)',
            canal: 'Bro Code',
            categoria: 'cpp',
            duracion: '6:00:00',
            nivel: 'Principiante / Intermedio',
            idioma: 'EN',
            descripcion: 'Sintaxis de C++ moderno, arrays, desreferenciación de punteros, paso por referencia const &, constructores y sobrecarga de operadores.'
        },
        {
            id: 'SfGuIVzE_Os',
            titulo: 'How C++ Works: Compilation, Linking and Executables',
            canal: 'The Cherno',
            categoria: 'cpp',
            duracion: '21:00',
            nivel: 'Intermedio / Senior',
            idioma: 'EN',
            descripcion: 'Arquitectura interna de C++: preprocesador, generación de código máquina .obj y enlazado estático/dinámico de ejecutables.'
        },
        {
            id: 'DTxHyVn0ODg',
            titulo: 'Pointers in C++: Memory Addresses & Lifetimes',
            canal: 'The Cherno',
            categoria: 'cpp',
            duracion: '16:00',
            nivel: 'Intermedio / Senior',
            idioma: 'EN',
            descripcion: 'El modelo de memoria en C++: direcciones de memoria, desreferenciación, punteros void*, punteros inteligentes y ciclo de vida en el heap.'
        },
        {
            id: 'W9gT9F-vSS8',
            titulo: 'Welcome to C++ Series / C++ Philosophy and Architecture',
            canal: 'The Cherno',
            categoria: 'cpp',
            duracion: '15:00',
            nivel: 'Fundamentos',
            idioma: 'EN',
            descripcion: 'Por qué C++ es el estándar en motores gráficos, sistemas operativos y motores de inferencia de Inteligencia Artificial.'
        },
        {
            id: 'yBHfWx6_oXQ',
            titulo: 'Curso Completo de C++ para Principiantes',
            canal: 'ATL Academy',
            categoria: 'cpp',
            duracion: '3:30:00',
            nivel: 'Principiante',
            idioma: 'ES',
            descripcion: 'Fundamentos de C++ en español: algoritmos, memoria, estructuras de control, funciones y programación orientada a objetos con ejercicios.'
        },
        {
            id: '8jOULp9E5-0',
            titulo: 'Harvard CS50 – Full Computer Science Course (C & Algoritmos)',
            canal: 'freeCodeCamp / Harvard (David J. Malan)',
            categoria: 'cpp',
            duracion: '25:00:00',
            nivel: 'Intermedio / Senior',
            idioma: 'EN',
            descripcion: 'Arquitectura de bajo nivel en C: gestión manual de memoria (malloc/free), punteros, segmentación de memoria y estructuras de datos complejas.'
        },

        // ==================== MACHINE LEARNING ====================
        {
            id: 'UzxYlbK2c7E',
            titulo: 'Stanford CS229: Machine Learning Course (Lecture 1)',
            canal: 'Stanford University (Andrew Ng)',
            categoria: 'ml',
            duracion: '1:18:00',
            nivel: 'Senior / Avanzado',
            idioma: 'EN',
            descripcion: 'El curso universitario de referencia de Stanford: formulación matemática de aprendizaje supervisado, gradiente descendente y ecuaciones normales.'
        },
        {
            id: 'i_LwzRVP7bg',
            titulo: 'Machine Learning for Everybody – Full Course',
            canal: 'freeCodeCamp (Kylie Ying)',
            categoria: 'ml',
            duracion: '3:53:00',
            nivel: 'Principiante / Intermedio',
            idioma: 'EN',
            descripcion: 'Data Science y ML práctico con Python y Scikit-Learn: regresión lineal/logística, KNN, naive bayes, árboles de decisión y métricas de validación.'
        },
        {
            id: 'NWONeJKn6kc',
            titulo: 'Machine Learning Course for Beginners – Complete End-to-End',
            canal: 'freeCodeCamp (Ayush Singh)',
            categoria: 'ml',
            duracion: '9:52:00',
            nivel: 'Intermedio / Senior',
            idioma: 'EN',
            descripcion: 'Curso integral de 10 horas: álgebra matricial, feature engineering, Decision Trees, Random Forest, Gradient Boosting y reducción con PCA.'
        },
        {
            id: 'QezIU-8U-D0',
            titulo: 'Machine Learning From Scratch in Python with NumPy',
            canal: 'Patrick Loeber',
            categoria: 'ml',
            duracion: '5:10:00',
            nivel: 'Senior',
            idioma: 'EN',
            descripcion: 'Construcción pura de algoritmos desde cero en Python y NumPy sin Scikit-Learn: Linear/Logistic Regression, KNN, Naive Bayes, SVM, Árboles y PCA.'
        },
        {
            id: 'ukzFI9xg-M9',
            titulo: 'Machine Learning Full Course (10 Horas)',
            canal: 'Edureka',
            categoria: 'ml',
            duracion: '10:15:00',
            nivel: 'Intermedio',
            idioma: 'EN',
            descripcion: 'Guía práctica de algoritmos de clasificación, clustering K-Means, aprendizaje supervisado y pipelines de datos con Python.'
        },
        {
            id: 'fNk_zzaMoSs',
            titulo: 'The Essence of Linear Algebra: Vectors, Spans, Basis & Transformations',
            canal: '3Blue1Brown (Grant Sanderson)',
            categoria: 'ml',
            duracion: '10:00',
            nivel: 'Fundamentos',
            idioma: 'EN',
            descripcion: 'Geometría e intuición visual del álgebra lineal: transformaciones lineales, determinantes, producto escalar, autovalores y autovectores.'
        },

        // ==================== DEEP LEARNING ====================
        {
            id: 'UZZD9d9YqnQ',
            titulo: 'MIT 6.S191: Introduction to Deep Learning (Lecture 1)',
            canal: 'MIT OpenCourseWare (Alexander Amini)',
            categoria: 'dl',
            duracion: '54:00',
            nivel: 'Avanzado / Senior',
            idioma: 'EN',
            descripcion: 'El curso oficial de Deep Learning del MIT: perceptrones, backpropagation multivariable, optimizadores estocásticos (SGD/Adam) y representaciones latentes.'
        },
        {
            id: 'mEsle_RQk70',
            titulo: "Let's build GPT: from scratch, in code, spelled out",
            canal: 'Andrej Karpathy',
            categoria: 'dl',
            duracion: '1:56:00',
            nivel: 'Senior',
            idioma: 'EN',
            descripcion: 'Construcción completa de un Transformer autorregresivo (estilo GPT-2) en PyTorch desde cero, explicando self-attention multi-head y skip connections.'
        },
        {
            id: 'VMj-3S1tku0',
            titulo: 'Building micrograd: Neural networks and backpropagation from scratch',
            canal: 'Andrej Karpathy',
            categoria: 'dl',
            duracion: '2:25:00',
            nivel: 'Senior',
            idioma: 'EN',
            descripcion: 'Creación paso a paso de un motor de autograd escalar en Python y entrenamiento de una red neuronal multicapa sin librerías externas.'
        },
        {
            id: 'kCc8FmEb1nY',
            titulo: 'Building makemore: Language Modeling from Bigram to Multilayer Perceptron',
            canal: 'Andrej Karpathy',
            categoria: 'dl',
            duracion: '1:57:00',
            nivel: 'Senior',
            idioma: 'EN',
            descripcion: 'Modelado de lenguaje desde bigramas estadísticos hasta redes neuronales densas (Bengio et al. 2003) con embeddings y función Negative Log-Likelihood.'
        },
        {
            id: 'pAU216bjVQ4',
            titulo: "Let's build the GPT Tokenizer (BPE)",
            canal: 'Andrej Karpathy',
            categoria: 'dl',
            duracion: '2:13:00',
            nivel: 'Senior',
            idioma: 'EN',
            descripcion: 'Implementación del algoritmo Byte Pair Encoding (BPE) a nivel de bytes UTF-8 para tokenización en modelos de lenguaje como GPT-2 y GPT-4.'
        },
        {
            id: 'Z_ikDlimN6A',
            titulo: 'PyTorch for Deep Learning & Machine Learning – Full Course',
            canal: 'freeCodeCamp (Daniel Bourke)',
            categoria: 'dl',
            duracion: '26:15:00',
            nivel: 'Intermedio / Senior',
            idioma: 'EN',
            descripcion: 'La formación de PyTorch más completa: tensores, visión computacional con CNNs, Transfer Learning, model deployment y tracking experimental.'
        },
        {
            id: 'c36lUUrRlzs',
            titulo: 'Deep Learning With PyTorch – Full Course',
            canal: 'Patrick Loeber',
            categoria: 'dl',
            duracion: '4:36:00',
            nivel: 'Intermedio / Senior',
            idioma: 'EN',
            descripcion: 'Flujo de trabajo profesional en PyTorch: cálculo de gradientes con autograd, DataLoader/Dataset personalizados, CNNs y redes recurrentes.'
        },
        {
            id: 'tPYj3fFJGjk',
            titulo: 'TensorFlow 2.0 Complete Course – Neural Networks for Beginners',
            canal: 'freeCodeCamp (Tech With Tim)',
            categoria: 'dl',
            duracion: '6:52:00',
            nivel: 'Principiante / Intermedio',
            idioma: 'EN',
            descripcion: 'Ecosistema TensorFlow 2 y Keras: construcción de modelos convolucionales (Conv2D), procesamiento de lenguaje natural y redes recurrentes.'
        },
        {
            id: 'vT1JzLTH4y4',
            titulo: 'Stanford CS231n: Convolutional Neural Networks for Visual Recognition',
            canal: 'Stanford (Fei-Fei Li & Andrej Karpathy)',
            categoria: 'dl',
            duracion: '1:04:00',
            nivel: 'Senior / Avanzado',
            idioma: 'EN',
            descripcion: 'El curso clásico de Stanford sobre visión computacional: capas convolucionales, pooling, normalización, AlexNet, VGG y ResNet.'
        },
        {
            id: '8rXD5-xhemo',
            titulo: 'Stanford CS224N: Natural Language Processing with Deep Learning',
            canal: 'Stanford (Christopher Manning)',
            categoria: 'dl',
            duracion: '1:21:00',
            nivel: 'Senior / Avanzado',
            idioma: 'EN',
            descripcion: 'Representación semántica vectorial (Word2Vec, GloVe), redes secuenciales recurrentes, atención y arquitecturas de Transformers para NLP.'
        },
        {
            id: '8SF_h8NW6dc',
            titulo: 'Practical Deep Learning for Coders (Lesson 1)',
            canal: 'fast.ai (Jeremy Howard)',
            categoria: 'dl',
            duracion: '1:25:00',
            nivel: 'Intermedio / Senior',
            idioma: 'EN',
            descripcion: 'Metodología top-down de fast.ai: entrenar modelos de visión y NLP con estado del arte en pocas líneas de código antes de descender a las matemáticas.'
        },
        {
            id: 'aircAruvnKk',
            titulo: 'But what is a neural network? | Deep learning, chapter 1',
            canal: '3Blue1Brown (Grant Sanderson)',
            categoria: 'dl',
            duracion: '19:00',
            nivel: 'Fundamentos',
            idioma: 'EN',
            descripcion: 'La mejor explicación visual de cómo una red neuronal clasifica patrones mediante combinaciones lineales, pesos, sesgos y activaciones.'
        },
        {
            id: 'kYJjZ35p3Yg',
            titulo: 'Tu primera red neuronal en Python y Tensorflow',
            canal: 'Ringa Tech',
            categoria: 'dl',
            duracion: '21:00',
            nivel: 'Principiante',
            idioma: 'ES',
            descripcion: 'Tutorial práctico en español creando y entrenando una red neuronal en Python usando TensorFlow/Keras para conversión de grados Celsius a Fahrenheit.'
        },
        {
            id: 'MRIv2IwFTPg',
            titulo: '¿Qué es una Red Neuronal? La Neurona y el Perceptrón',
            canal: 'DotCSV (Carlos Santana)',
            categoria: 'dl',
            duracion: '13:00',
            nivel: 'Fundamentos',
            idioma: 'ES',
            descripcion: 'Explicación didáctica y rigurosa en español de la neurona artificial, entradas, pesos sinápticos, sesgo y funciones de activación.'
        },

        // ==================== ALGORITMOS & SYSTEM DESIGN ====================
        {
            id: '8hly31xKli0',
            titulo: 'Algorithms and Data Structures for Beginners – Full Course',
            canal: 'NeetCode / freeCodeCamp',
            categoria: 'algoritmos',
            duracion: '5:20:00',
            nivel: 'Senior',
            idioma: 'EN',
            descripcion: 'Estructuras de datos esenciales: Arrays estáticos y dinámicos, Listas enlazadas, Árboles BST, Heaps, Grafos y QuickSort.'
        },
        {
            id: 'ZA-tUyM_y7s',
            titulo: 'MIT 6.006: Introduction to Algorithms – Peak Finding & Complexity',
            canal: 'MIT OpenCourseWare (Erik Demaine)',
            categoria: 'algoritmos',
            duracion: '50:00',
            nivel: 'Avanzado',
            idioma: 'EN',
            descripcion: 'Fundamentos de análisis asintótico, cotas Big-O y búsqueda de picos en tiempo logarítmico con división y conquista.'
        },
        {
            id: '5hP30Tqjtt4',
            titulo: '0/1 Knapsack Problem – Dynamic Programming Formulation',
            canal: 'Abdul Bari',
            categoria: 'algoritmos',
            duracion: '33:00',
            nivel: 'Avanzado',
            idioma: 'EN',
            descripcion: 'Optimización algorítmica clásica: programación dinámica matricial bottom-up y resolución analítica paso a paso.'
        },
        {
            id: 'i53Gi_K3o7I',
            titulo: 'System Design Interview: How to Scale a System to Millions of Users',
            canal: 'ByteByteGo (Alex Xu)',
            categoria: 'system_design',
            duracion: '16:00',
            nivel: 'Senior',
            idioma: 'EN',
            descripcion: 'Arquitectura escalable: balanceadores de carga, CDN, particionado de bases de datos, colas asíncronas y caché con Redis.'
        }
    ];

    const CATEGORIAS = [
        { id: 'todas', label: 'Todos los cursos' },
        { id: 'python', label: 'Python' },
        { id: 'cpp', label: 'C++ Moderno' },
        { id: 'ml', label: 'Machine Learning' },
        { id: 'dl', label: 'Deep Learning' },
        { id: 'algoritmos', label: 'Algoritmos y Estructuras' },
        { id: 'system_design', label: 'System Design' }
    ];

    const estado = {
        vista: 'catalogo', // 'catalogo' | 'reproductor'
        filtroCategoria: 'todas',
        filtroProgreso: 'todos', // 'todos' | 'en_progreso' | 'completados' | 'sin_iniciar'
        busqueda: '',
        ocultarTexto: localStorage.getItem('prig_yt_ocultar_texto') === 'true',
        ocultarTextoPlayer: localStorage.getItem('prig_yt_ocultar_texto_player') === 'true',
        videoActual: null,
        pestanaLateral: 'notas', // 'notas' | 'objetivos' | 'resumen' | 'tutor'
        chatTutor: [],
        tutorCargando: false,
        analisisCargando: false,
        analisisMensaje: '',
        desafioCreando: false,
        desafioMensaje: '',
        mostrarInputTextoExtra: false,
        textoExtra: ''
    };

    // ==================== GESTIÓN DE PROGRESO Y PERSISTENCIA ====================
    function leerProgresoTodos() {
        try {
            const raw = localStorage.getItem('prig_yt_progreso');
            return raw ? JSON.parse(raw) : {};
        } catch (e) {
            return {};
        }
    }

    function guardarProgresoTodos(obj) {
        try {
            localStorage.setItem('prig_yt_progreso', JSON.stringify(obj));
        } catch (e) {
            console.error('Error guardando progreso:', e);
        }
    }

    function obtenerProgreso(videoId) {
        const todos = leerProgresoTodos();
        return todos[videoId] || {
            estado: 'sin_iniciar', // 'sin_iniciar' | 'en_progreso' | 'completado'
            porcentaje: 0,
            ultimoMinuto: '00:00',
            segundos: 0,
            actualizado: null
        };
    }

    function guardarProgreso(videoId, cambios) {
        const todos = leerProgresoTodos();
        const actual = todos[videoId] || {
            estado: 'sin_iniciar',
            porcentaje: 0,
            ultimoMinuto: '00:00',
            segundos: 0
        };
        const nuevo = { ...actual, ...cambios, actualizado: Date.now() };

        if (nuevo.porcentaje >= 100 || nuevo.estado === 'completado') {
            nuevo.porcentaje = 100;
            nuevo.estado = 'completado';
        } else if (nuevo.porcentaje > 0 || (nuevo.segundos && nuevo.segundos > 0)) {
            nuevo.estado = 'en_progreso';
        } else {
            nuevo.estado = 'sin_iniciar';
            nuevo.porcentaje = 0;
        }

        todos[videoId] = nuevo;
        guardarProgresoTodos(todos);
        return nuevo;
    }

    function alternarCompletado(videoId) {
        const p = obtenerProgreso(videoId);
        if (p.estado === 'completado') {
            return guardarProgreso(videoId, { estado: 'en_progreso', porcentaje: 50 });
        } else {
            return guardarProgreso(videoId, { estado: 'completado', porcentaje: 100 });
        }
    }

    // ==================== GESTIÓN DE NOTAS CON MARCAS DE TIEMPO ====================
    function leerMarcasVideo(videoId) {
        try {
            const raw = localStorage.getItem(`prig_yt_marcas_${videoId}`);
            const arr = raw ? JSON.parse(raw) : [];
            return Array.isArray(arr) ? arr : [];
        } catch (e) {
            return [];
        }
    }

    function guardarMarcasVideo(videoId, marcas) {
        try {
            localStorage.setItem(`prig_yt_marcas_${videoId}`, JSON.stringify(marcas));
        } catch (e) {
            console.error('Error guardando marcas:', e);
        }
    }

    function formatearSegundos(s) {
        s = Math.max(0, Math.floor(Number(s) || 0));
        const h = Math.floor(s / 3600);
        const m = Math.floor((s % 3600) / 60);
        const sec = s % 60;
        if (h > 0) {
            return `${h}:${String(m).padStart(2, '0')}:${String(sec).padStart(2, '0')}`;
        }
        return `${String(m).padStart(2, '0')}:${String(sec).padStart(2, '0')}`;
    }

    function parsearTimestamp(ts) {
        if (!ts) return 0;
        const limpio = String(ts).replace(/[\[\]\(\)\s]/g, '').trim();
        const partes = limpio.split(':').map(x => parseInt(x, 10));
        if (partes.some(isNaN)) return 0;
        if (partes.length === 3) {
            return partes[0] * 3600 + partes[1] * 60 + partes[2];
        } else if (partes.length === 2) {
            return partes[0] * 60 + partes[1];
        } else if (partes.length === 1) {
            return partes[0];
        }
        return 0;
    }

    function extraerTimestampsDeTexto(texto) {
        if (!texto) return [];
        const regex = /(?:\[\s*)?(\b(?:\d{1,2}:)?\d{1,2}:\d{2}\b)(?:\s*\])?/g;
        const unicos = new Set();
        let m;
        while ((m = regex.exec(texto)) !== null) {
            unicos.add(m[1]);
        }
        return Array.from(unicos).map(ts => ({
            minuto: ts,
            segundos: parsearTimestamp(ts)
        })).sort((a, b) => a.segundos - b.segundos);
    }

    function saltarAMinuto(segundos, forzarRecarga = false) {
        const v = estado.videoActual;
        if (!v) return;
        segundos = Math.max(0, Math.floor(Number(segundos) || 0));
        const minStr = formatearSegundos(segundos);

        // Actualizar progreso persistente del video
        const progActual = obtenerProgreso(v.id);
        guardarProgreso(v.id, {
            ultimoMinuto: minStr,
            segundos: segundos,
            porcentaje: Math.max(progActual.porcentaje, 5)
        });

        const iframe = $('yt-iframe-player');
        if (iframe) {
            if (forzarRecarga) {
                iframe.src = `https://www.youtube-nocookie.com/embed/${v.id}?enablejsapi=1&autoplay=1&start=${segundos}&rel=0`;
            } else {
                try {
                    iframe.contentWindow.postMessage(JSON.stringify({
                        event: 'command',
                        func: 'seekTo',
                        args: [segundos, true]
                    }), '*');
                    iframe.contentWindow.postMessage(JSON.stringify({
                        event: 'command',
                        func: 'playVideo',
                        args: []
                    }), '*');
                } catch (e) {
                    iframe.src = `https://www.youtube-nocookie.com/embed/${v.id}?enablejsapi=1&autoplay=1&start=${segundos}&rel=0`;
                }
            }
        }

        // Feedback en la interfaz
        const ind = $('yt-progreso-ultimo-min');
        if (ind) ind.textContent = minStr;
        const badgeCur = $('yt-minuto-activo-badge');
        if (badgeCur) badgeCur.textContent = `Reproduciendo en: ${minStr}`;
    }

    function extraerVideoId(cadena) {
        if (!cadena) return null;
        const texto = cadena.trim();
        if (/^[a-zA-Z0-9_-]{11}$/.test(texto)) return texto;
        const m1 = texto.match(/(?:youtube\.com\/(?:[^\/]+\/.+\/|(?:v|e(?:mbed)?)\/|.*[?&]v=)|youtu\.be\/)([^"&?\/\s]{11})/i);
        return m1 ? m1[1] : null;
    }

    // ==================== GESTIÓN DE OBJETIVOS DIDÁCTICOS Y RESÚMENES ====================
    function leerObjetivos(videoId) {
        try {
            const raw = localStorage.getItem(`prig_yt_objetivos_${videoId}`);
            const arr = raw ? JSON.parse(raw) : [];
            return Array.isArray(arr) ? arr : [];
        } catch (e) {
            return [];
        }
    }

    function guardarObjetivos(videoId, objs) {
        try {
            localStorage.setItem(`prig_yt_objetivos_${videoId}`, JSON.stringify(objs));
        } catch (e) {
            console.error('Error guardando objetivos:', e);
        }
    }

    function leerResumen(videoId) {
        try {
            const raw = localStorage.getItem(`prig_yt_resumen_${videoId}`);
            return raw ? JSON.parse(raw) : null;
        } catch (e) {
            return null;
        }
    }

    function guardarResumen(videoId, res) {
        try {
            localStorage.setItem(`prig_yt_resumen_${videoId}`, JSON.stringify(res));
        } catch (e) {
            console.error('Error guardando resumen:', e);
        }
    }

    function alternarObjetivoSuperado(videoId, objetivoId, forzarEstado = null) {
        const lista = leerObjetivos(videoId);
        let modificado = false;
        lista.forEach(o => {
            if (o.id === objetivoId) {
                o.superado = forzarEstado !== null ? forzarEstado : !o.superado;
                modificado = true;
            }
        });
        if (modificado) {
            guardarObjetivos(videoId, lista);
            // Sincronizar porcentaje con el progreso global del curso
            const superados = lista.filter(o => o.superado).length;
            const pct = lista.length > 0 ? Math.round((superados / lista.length) * 100) : 0;
            guardarProgreso(videoId, {
                porcentaje: pct,
                estado: pct >= 100 ? 'completado' : (pct > 0 ? 'en_progreso' : 'sin_iniciar')
            });
        }
        return lista;
    }

    async function consumirStreamNdjson(res, alProgreso) {
        if (!res.ok) {
            let errDetail = 'Error en la comunicación con el servidor.';
            try {
                const j = await res.json();
                errDetail = j.detail || j.message || errDetail;
            } catch (_) {
                errDetail = await res.text();
            }
            throw new Error(errDetail);
        }
        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        let resultadoFinal = null;

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });
            const lineas = buffer.split('\n');
            buffer = lineas.pop();
            for (const l of lineas) {
                if (!l.trim()) continue;
                try {
                    const ev = JSON.parse(l);
                    if (ev.tipo === 'error') throw new Error(ev.mensaje);
                    if (ev.tipo === 'fin') resultadoFinal = ev.resultado;
                    else if (alProgreso) alProgreso(ev);
                } catch (err) {
                    if (err.message && err.message.startsWith('Error')) throw err;
                }
            }
        }
        return resultadoFinal;
    }

    async function solicitarAnalisisIA(v, modo = 'ambos') {
        if (estado.analisisCargando) return;
        estado.analisisCargando = true;
        estado.analisisMensaje = modo === 'resumen'
            ? 'Analizando video y sintetizando resumen técnico...'
            : (modo === 'objetivos' ? 'Dividiendo la clase en objetivos de aprendizaje con timestamps...' : 'Analizando clase con IA...');
        pintar();

        try {
            const notaActual = localStorage.getItem(`prig_yt_nota_${v.id}`) || '';
            const r = await window.prigFetchJson('/api/youtube/analizar', {
                method: 'POST',
                body: JSON.stringify({
                    video_id: v.id,
                    titulo: v.titulo,
                    canal: v.canal || 'YouTube',
                    duracion: v.duracion || '',
                    descripcion: v.descripcion || '',
                    categoria: v.categoria || '',
                    nivel: v.nivel ? v.nivel.toLowerCase().split('/')[0].trim() : 'intermedio',
                    texto_usuario: estado.textoExtra || '',
                    notas_usuario: notaActual,
                    modo: modo
                })
            });

            if (r) {
                if (r.resumen) {
                    guardarResumen(v.id, r.resumen);
                }
                if (r.objetivos && Array.isArray(r.objetivos)) {
                    // Conservar estados previos de superado si ya existían
                    const previos = leerObjetivos(v.id);
                    const superadosSet = new Set(previos.filter(p => p.superado).map(p => p.id));
                    r.objetivos.forEach(o => {
                        if (superadosSet.has(o.id)) o.superado = true;
                    });
                    guardarObjetivos(v.id, r.objetivos);
                }
            }
        } catch (e) {
            alert('Error al analizar con IA: ' + e.message);
        } finally {
            estado.analisisCargando = false;
            estado.analisisMensaje = '';
            pintar();
        }
    }

    async function solicitarCrearDesafio(v, obj = null) {
        if (estado.desafioCreando) return;
        estado.desafioCreando = true;
        estado.desafioMensaje = 'El modelo está generando tu desafío interactivo con pruebas unitarias y verificación de código...';
        pintar();

        try {
            const esCpp = v.categoria === 'cpp' || (v.titulo && v.titulo.toLowerCase().includes('c++'));
            const lenguaje = esCpp ? 'cpp' : 'python';
            const temaTitulo = obj ? obj.titulo : v.titulo;
            const objDesc = obj ? obj.descripcion : (v.descripcion || '');
            const conceptos = obj ? obj.conceptos : [v.categoria || 'programación'];
            const nivel = (obj && obj.dificultad) ? obj.dificultad : (v.nivel ? v.nivel.toLowerCase().split('/')[0].trim() : 'intermedio');

            const res = await fetch('/api/youtube/crear-desafio', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    video_id: v.id,
                    titulo_video: v.titulo,
                    objetivo_id: obj ? obj.id : 'global',
                    objetivo_titulo: temaTitulo,
                    objetivo_descripcion: objDesc,
                    conceptos: conceptos,
                    nivel: nivel,
                    lenguaje: lenguaje
                })
            });

            const desafio = await consumirStreamNdjson(res, (ev) => {
                if (ev.tipo === 'progreso' && ev.mensaje) {
                    estado.desafioMensaje = ev.mensaje;
                    const elMsg = $('yt-desafio-mensaje-stream');
                    if (elMsg) elMsg.textContent = ev.mensaje;
                }
            });

            if (desafio && desafio.id) {
                if (obj) {
                    alternarObjetivoSuperado(v.id, obj.id, true);
                }
                if (window.Desafios) {
                    window.Desafios.abrir({ id: desafio.id });
                } else {
                    alert(`¡Desafío creado exitosamente! Código: ${desafio.id}. Puedes abrirlo en la sección Desafíos.`);
                }
            } else {
                alert('Desafío creado. Puedes encontrarlo en la sección Desafíos.');
            }
        } catch (e) {
            alert('Error creando desafío: ' + e.message);
        } finally {
            estado.desafioCreando = false;
            estado.desafioMensaje = '';
            pintar();
        }
    }


    function inyectarEstilos() {
        if ($('youtube-hub-estilos')) return;
        const s = document.createElement('style');
        s.id = 'youtube-hub-estilos';
        s.textContent = `
            .yt-raiz { display:flex; flex-direction:column; height:100%; width:100%; background:var(--bg-dark, #11111b); color:var(--text-main, #cdd6f4); font-family:inherit; overflow:hidden; }
            .yt-barra { display:flex; align-items:center; gap:10px; padding:10px 16px; border-bottom:1px solid var(--border-color, rgba(255,255,255,0.08)); background:var(--bg-panel, #181825); flex-shrink:0; flex-wrap:wrap; }
            .yt-logo { display:flex; align-items:center; gap:8px; font-weight:700; font-size:13.5px; color:#fff; }
            .yt-logo i { color:#ff0000; font-size:17px; }
            .yt-campo-buscar { flex:1; min-width:220px; max-width:500px; background:var(--bg-dark, #11111b); border:1px solid var(--border-color, rgba(255,255,255,0.12)); border-radius:8px; padding:6px 12px; color:#fff; font-size:12px; outline:none; }
            .yt-campo-buscar:focus { border-color:#ff0000; }
            .yt-btn { display:inline-flex; align-items:center; gap:6px; background:rgba(255,255,255,0.06); border:1px solid var(--border-color, rgba(255,255,255,0.1)); border-radius:7px; padding:5px 11px; color:var(--text-main, #cdd6f4); font-size:11.5px; cursor:pointer; font-weight:600; text-decoration:none; transition:all 0.15s; user-select:none; }
            .yt-btn:hover { background:rgba(255,255,255,0.12); color:#fff; }
            .yt-btn.rojo { background:rgba(255,0,0,0.16); border-color:rgba(255,0,0,0.4); color:#ff5555; }
            .yt-btn.rojo:hover { background:#ff0000; color:#fff; }
            .yt-btn.azul { background:rgba(137,180,250,0.14); border-color:rgba(137,180,250,0.35); color:var(--accent-blue, #89b4fa); }
            .yt-btn.azul:hover { background:rgba(137,180,250,0.25); color:#fff; }
            .yt-btn.verde { background:rgba(16,185,129,0.16); border-color:rgba(16,185,129,0.4); color:#10b981; }
            .yt-btn.verde:hover { background:#10b981; color:#fff; }
            .yt-btn.morado { background:rgba(203,166,247,0.14); border-color:rgba(203,166,247,0.35); color:var(--accent-purple, #cba6f7); }

            .yt-chips { display:flex; gap:6px; padding:8px 16px; border-bottom:1px solid var(--border-color, rgba(255,255,255,0.06)); background:var(--bg-panel, #181825); overflow-x:auto; flex-shrink:0; scrollbar-width:none; }
            .yt-chip { padding:3px 10px; border-radius:20px; font-size:11px; background:rgba(255,255,255,0.05); color:var(--text-muted, #a6adc8); border:1px solid transparent; cursor:pointer; white-space:nowrap; }
            .yt-chip:hover { color:#fff; background:rgba(255,255,255,0.09); }
            .yt-chip.activo { background:rgba(255,0,0,0.15); border-color:rgba(255,0,0,0.4); color:#ff6666; font-weight:700; }

            .yt-cuerpo { flex:1; overflow-y:auto; padding:16px 20px; }
            
            /* Resumen de avance en catálogo */
            .yt-resumen-progreso { display:flex; align-items:center; justify-content:space-between; background:rgba(255,255,255,0.03); border:1px solid var(--border-color, rgba(255,255,255,0.08)); border-radius:8px; padding:8px 14px; margin-bottom:14px; font-size:12px; gap:10px; flex-wrap:wrap; }
            .yt-pills-filtro { display:flex; gap:6px; flex-wrap:wrap; }
            .yt-pill-progreso { font-size:11px; padding:3px 9px; border-radius:12px; background:rgba(255,255,255,0.06); color:var(--text-muted, #a6adc8); border:1px solid transparent; cursor:pointer; transition:all 0.15s; }
            .yt-pill-progreso:hover { color:#fff; background:rgba(255,255,255,0.12); }
            .yt-pill-progreso.activo { background:rgba(16,185,129,0.2); border-color:rgba(16,185,129,0.5); color:#10b981; font-weight:700; }

            .yt-grid { display:grid; grid-template-columns:repeat(auto-fill, minmax(285px, 1fr)); gap:16px; }
            .yt-modo-compacto .yt-grid { grid-template-columns:repeat(auto-fill, minmax(250px, 1fr)); gap:12px; }
            .yt-tarjeta { background:var(--bg-panel, #181825); border:1px solid var(--border-color, rgba(255,255,255,0.08)); border-radius:10px; overflow:hidden; display:flex; flex-direction:column; cursor:pointer; transition:transform 0.15s, border-color 0.15s, box-shadow 0.15s; position:relative; }
            .yt-tarjeta:hover { transform:translateY(-2px); border-color:rgba(255,0,0,0.45); box-shadow:0 6px 18px rgba(0,0,0,0.4); }
            .yt-miniatura { position:relative; width:100%; aspect-ratio:16/9; background:#000; overflow:hidden; }
            .yt-miniatura img { width:100%; height:100%; object-fit:cover; display:block; }
            .yt-duracion { position:absolute; bottom:6px; right:6px; background:rgba(0,0,0,0.82); color:#fff; font-size:10px; padding:2px 5px; border-radius:4px; font-weight:600; z-index:2; }
            .yt-nivel { position:absolute; top:6px; left:6px; background:rgba(203,166,247,0.9); color:#111; font-size:9.5px; padding:2px 6px; border-radius:4px; font-weight:700; z-index:2; }
            .yt-idioma { position:absolute; top:6px; right:6px; background:rgba(0,0,0,0.75); color:#fff; font-size:9.5px; padding:2px 5px; border-radius:4px; font-weight:700; text-transform:uppercase; border:1px solid rgba(255,255,255,0.15); z-index:2; }
            
            /* Progreso en tarjeta */
            .yt-tarjeta-progreso-barra { width:100%; height:4px; background:rgba(255,255,255,0.08); position:relative; }
            .yt-tarjeta-progreso-fill { height:100%; background:#3b82f6; transition:width 0.25s ease; }
            .yt-tarjeta-progreso-fill.completado { background:#10b981; }

            .yt-badge-estado { position:absolute; bottom:6px; left:6px; font-size:9.5px; padding:2px 6px; border-radius:4px; font-weight:700; display:inline-flex; align-items:center; gap:4px; z-index:2; }
            .yt-badge-estado.completado { background:rgba(16,185,129,0.92); color:#fff; box-shadow:0 2px 6px rgba(0,0,0,0.3); }
            .yt-badge-estado.en-progreso { background:rgba(59,130,246,0.92); color:#fff; box-shadow:0 2px 6px rgba(0,0,0,0.3); }

            .yt-btn-quick-check { position:absolute; top:6px; right:36px; width:22px; height:22px; border-radius:4px; background:rgba(0,0,0,0.75); border:1px solid rgba(255,255,255,0.25); color:#a6adc8; display:flex; align-items:center; justify-content:center; font-size:10px; cursor:pointer; transition:all 0.15s; z-index:3; }
            .yt-btn-quick-check:hover { background:rgba(16,185,129,0.35); color:#10b981; border-color:#10b981; transform:scale(1.1); }
            .yt-btn-quick-check.activo { background:#10b981; color:#fff; border-color:#10b981; }

            .yt-tarjeta-info { padding:10px 12px; display:flex; flex-direction:column; flex:1; gap:5px; }
            .yt-tarjeta-titulo { font-size:12px; font-weight:600; color:#fff; line-height:1.35; margin:0; display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; overflow:hidden; }
            .yt-tarjeta-canal { font-size:11px; color:var(--text-muted, #a6adc8); }
            .yt-tarjeta-desc { font-size:10.5px; color:var(--text-muted, #9399b2); line-height:1.35; margin:0; display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; overflow:hidden; }
            .yt-modo-compacto .yt-tarjeta-desc { display:none !important; }

            /* Reproductor */
            .yt-player-layout { display:grid; grid-template-columns:1fr 390px; height:100%; min-height:0; overflow:hidden; }
            @media (max-width: 950px) { .yt-player-layout { grid-template-columns:1fr; grid-template-rows:1fr 1fr; } }
            .yt-player-main { display:flex; flex-direction:column; height:100%; min-height:0; overflow-y:auto; padding:16px; gap:12px; }
            .yt-iframe-wrap { width:100%; aspect-ratio:16/9; background:#000; border-radius:10px; overflow:hidden; border:1px solid var(--border-color, rgba(255,255,255,0.1)); flex-shrink:0; }
            .yt-iframe-wrap iframe { width:100%; height:100%; border:none; display:block; }
            
            /* Caja de avance en reproductor */
            .yt-progreso-caja { background:rgba(255,255,255,0.035); border:1px solid var(--border-color, rgba(255,255,255,0.08)); border-radius:8px; padding:9px 12px; display:flex; flex-direction:column; gap:6px; flex-shrink:0; }
            .yt-progreso-fila { display:flex; align-items:center; justify-content:space-between; flex-wrap:wrap; gap:8px; }
            .yt-prog-badge { font-size:10.5px; font-weight:700; padding:2px 8px; border-radius:10px; }
            .yt-prog-badge.completado { background:rgba(16,185,129,0.2); color:#10b981; border:1px solid rgba(16,185,129,0.4); }
            .yt-prog-badge.en_progreso { background:rgba(59,130,246,0.2); color:#89b4fa; border:1px solid rgba(59,130,246,0.4); }
            .yt-prog-badge.sin_iniciar { background:rgba(255,255,255,0.08); color:var(--text-muted, #a6adc8); }
            .yt-quick-pct-btns { display:flex; gap:4px; }
            .yt-btn-pct { background:rgba(255,255,255,0.06); border:1px solid rgba(255,255,255,0.1); border-radius:4px; color:var(--text-muted, #a6adc8); font-size:10px; padding:2px 5px; cursor:pointer; transition:all 0.15s; }
            .yt-btn-pct:hover { color:#fff; background:rgba(255,255,255,0.15); }

            .yt-info-video { display:flex; flex-direction:column; gap:6px; }
            .yt-info-video.oculto { display:none !important; }
            .yt-video-titulo { font-size:15px; font-weight:700; color:#fff; margin:0; }
            .yt-acciones-video { display:flex; gap:8px; flex-wrap:wrap; align-items:center; }

            /* Panel Lateral */
            .yt-lateral { border-left:1px solid var(--border-color, rgba(255,255,255,0.08)); background:var(--bg-panel, #181825); display:flex; flex-direction:column; height:100%; min-height:0; overflow:hidden; }
            .yt-lateral-tabs { display:flex; border-bottom:1px solid var(--border-color, rgba(255,255,255,0.08)); background:rgba(0,0,0,0.18); flex-shrink:0; overflow-x:auto; scrollbar-width:none; }
            .yt-lateral-tab { flex:1; min-width:68px; padding:9px 4px; font-size:10.5px; font-weight:700; text-align:center; cursor:pointer; color:var(--text-muted, #a6adc8); border-bottom:2px solid transparent; white-space:nowrap; transition:all 0.15s; }
            .yt-lateral-tab:hover { color:#fff; background:rgba(255,255,255,0.04); }
            .yt-lateral-tab.activo { color:#fff; border-bottom-color:#ff0000; background:rgba(255,255,255,0.05); }
            .yt-lateral-cuerpo { flex:1; min-height:0; overflow-y:auto; padding:12px; display:flex; flex-direction:column; gap:8px; }

            /* Notaciones por minuto */
            .yt-marcas-seccion { display:flex; flex-direction:column; gap:8px; background:rgba(0,0,0,0.22); border:1px solid var(--border-color, rgba(255,255,255,0.08)); border-radius:8px; padding:10px; }
            .yt-marca-input-fila { display:flex; gap:6px; align-items:center; }
            .yt-input-min { width:78px; background:var(--bg-dark, #11111b); border:1px solid var(--border-color, rgba(255,255,255,0.14)); border-radius:6px; padding:5px 8px; color:#fff; font-size:11.5px; font-weight:700; text-align:center; outline:none; font-family:'Fira Code', monospace; }
            .yt-input-min:focus { border-color:var(--accent-blue, #89b4fa); }
            .yt-input-txt { flex:1; background:var(--bg-dark, #11111b); border:1px solid var(--border-color, rgba(255,255,255,0.14)); border-radius:6px; padding:5px 10px; color:#fff; font-size:11.5px; outline:none; }
            .yt-input-txt:focus { border-color:var(--accent-blue, #89b4fa); }
            .yt-marcas-lista { display:flex; flex-direction:column; gap:5px; max-height:160px; overflow-y:auto; padding-right:2px; }
            .yt-marca-item { display:flex; align-items:center; gap:8px; background:rgba(255,255,255,0.04); border:1px solid rgba(255,255,255,0.06); border-radius:6px; padding:5px 8px; transition:all 0.15s; }
            .yt-marca-item:hover { background:rgba(255,255,255,0.08); border-color:rgba(137,180,250,0.3); }
            .yt-timestamp-btn { display:inline-flex; align-items:center; gap:4px; background:rgba(137,180,250,0.16); border:1px solid rgba(137,180,250,0.35); color:#89b4fa; padding:2px 7px; border-radius:4px; font-size:10.5px; font-weight:700; cursor:pointer; transition:all 0.15s; font-family:'Fira Code', monospace; white-space:nowrap; }
            .yt-timestamp-btn:hover { background:#89b4fa; color:#11111b; transform:scale(1.02); }
            .yt-marca-texto { flex:1; font-size:11px; color:#cdd6f4; line-height:1.35; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
            .yt-marca-btn { background:transparent; border:none; color:var(--text-muted, #a6adc8); cursor:pointer; padding:3px 5px; border-radius:4px; font-size:11px; transition:color 0.15s; }
            .yt-marca-btn:hover { color:#fff; background:rgba(255,255,255,0.08); }
            .yt-marca-btn.eliminar:hover { color:#ff5555; }

            .yt-chips-detectados { display:flex; gap:4px; flex-wrap:wrap; align-items:center; padding:2px 0 6px; font-size:10px; color:var(--text-muted, #a6adc8); }
            .yt-chip-seek { background:rgba(255,255,255,0.06); border:1px solid rgba(255,255,255,0.1); border-radius:4px; color:#89b4fa; padding:2px 6px; font-size:10px; font-family:'Fira Code', monospace; cursor:pointer; font-weight:600; }
            .yt-chip-seek:hover { background:rgba(137,180,250,0.2); color:#fff; }

            .yt-textarea-nota { width:100%; flex:1; min-height:140px; background:var(--bg-dark, #11111b); border:1px solid var(--border-color, rgba(255,255,255,0.1)); border-radius:8px; padding:10px; color:#fff; font-family:'Fira Code', monospace; font-size:11.5px; line-height:1.5; resize:none; outline:none; }
            .yt-textarea-nota:focus { border-color:var(--accent-blue, #89b4fa); }

            /* Estilos de Objetivos Didácticos */
            .yt-objetivos-contenedor { display:flex; flex-direction:column; gap:10px; }
            .yt-objetivo-tarjeta { background:rgba(255,255,255,0.035); border:1px solid var(--border-color, rgba(255,255,255,0.08)); border-radius:8px; padding:10px 12px; display:flex; flex-direction:column; gap:6px; transition:border-color 0.15s, background 0.15s; }
            .yt-objetivo-tarjeta:hover { border-color:rgba(137,180,250,0.35); background:rgba(255,255,255,0.05); }
            .yt-objetivo-tarjeta.superado { border-color:rgba(16,185,129,0.35); background:rgba(16,185,129,0.04); }
            .yt-obj-header { display:flex; align-items:center; gap:8px; justify-content:space-between; }
            .yt-obj-titulo { font-size:12px; font-weight:700; color:#fff; flex:1; line-height:1.3; }
            .yt-badge-dificultad { font-size:9px; padding:2px 6px; border-radius:4px; font-weight:700; text-transform:uppercase; letter-spacing:0.3px; }
            .yt-badge-dificultad.principiante { background:rgba(166,227,161,0.18); color:#a6e3a1; border:1px solid rgba(166,227,161,0.35); }
            .yt-badge-dificultad.intermedio { background:rgba(137,180,250,0.18); color:#89b4fa; border:1px solid rgba(137,180,250,0.35); }
            .yt-badge-dificultad.avanzado, .yt-badge-dificultad.senior { background:rgba(203,166,247,0.18); color:#cba6f7; border:1px solid rgba(203,166,247,0.35); }
            .yt-obj-desc { font-size:11px; color:var(--text-muted, #a6adc8); line-height:1.4; margin:0; }
            .yt-obj-footer { display:flex; align-items:center; justify-content:space-between; margin-top:4px; gap:8px; flex-wrap:wrap; }

            /* Estilos de Resumen IA */
            .yt-resumen-contenedor { display:flex; flex-direction:column; gap:12px; }
            .yt-resumen-caja { background:rgba(255,255,255,0.035); border:1px solid var(--border-color, rgba(255,255,255,0.08)); border-radius:8px; padding:12px; display:flex; flex-direction:column; gap:8px; }
            .yt-resumen-subtitulo { font-size:11.5px; font-weight:700; color:#fff; display:flex; align-items:center; gap:6px; }
            .yt-resumen-texto { font-size:11.5px; color:#cdd6f4; line-height:1.45; margin:0; }
            .yt-puntos-clave-lista { list-style:none; padding:0; margin:0; display:flex; flex-direction:column; gap:5px; }
            .yt-punto-clave-item { font-size:11px; color:#cdd6f4; line-height:1.4; display:flex; align-items:flex-start; gap:6px; }
            .yt-punto-clave-item i { color:var(--accent-green, #10b981); margin-top:2px; font-size:10px; flex-shrink:0; }
            .yt-snippet-box { background:var(--bg-dark, #11111b); border:1px solid rgba(255,255,255,0.1); border-radius:6px; padding:8px 10px; position:relative; overflow-x:auto; }
            .yt-snippet-code { font-family:'Fira Code', monospace; font-size:11px; color:#89b4fa; margin:0; white-space:pre-wrap; }
            .yt-glosario-card { background:rgba(255,255,255,0.025); border:1px solid rgba(255,255,255,0.06); border-radius:6px; padding:7px 10px; font-size:11px; }

            /* Caja para pegar texto extra / transcripción */
            .yt-texto-extra-caja { background:rgba(0,0,0,0.3); border:1px dashed var(--border-color, rgba(255,255,255,0.15)); border-radius:7px; padding:8px 10px; display:flex; flex-direction:column; gap:6px; }
            .yt-textarea-extra { width:100%; min-height:70px; background:var(--bg-dark, #11111b); border:1px solid var(--border-color, rgba(255,255,255,0.1)); border-radius:6px; padding:6px 8px; color:#fff; font-size:11px; outline:none; resize:vertical; font-family:inherit; }

            /* Carga y Spinners */
            .yt-loading-box { text-align:center; padding:26px 16px; color:var(--text-muted); font-size:12px; display:flex; flex-direction:column; align-items:center; gap:10px; }
            .yt-loading-spinner { font-size:24px; color:var(--accent-blue, #89b4fa); animation:ytSpin 1s linear infinite; }
            @keyframes ytSpin { 100% { transform:rotate(360deg); } }

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
        const todosProgreso = leerProgresoTodos();

        // Conteo global de avances
        let totalCompletados = 0;
        let totalEnProgreso = 0;
        let totalSinIniciar = 0;

        VIDEOS_CURADOS.forEach(v => {
            const p = todosProgreso[v.id] || {};
            if (p.estado === 'completado' || p.porcentaje >= 100) totalCompletados++;
            else if (p.estado === 'en_progreso' || (p.porcentaje && p.porcentaje > 0)) totalEnProgreso++;
            else totalSinIniciar++;
        });

        const filtrados = VIDEOS_CURADOS.filter(v => {
            const p = todosProgreso[v.id] || {};
            const esComp = p.estado === 'completado' || p.porcentaje >= 100;
            const esEnProg = p.estado === 'en_progreso' || (p.porcentaje && p.porcentaje > 0 && !esComp);
            const esSinIni = !esComp && !esEnProg;

            if (estado.filtroProgreso === 'completados' && !esComp) return false;
            if (estado.filtroProgreso === 'en_progreso' && !esEnProg) return false;
            if (estado.filtroProgreso === 'sin_iniciar' && !esSinIni) return false;

            const coincideCat = estado.filtroCategoria === 'todas' || v.categoria === estado.filtroCategoria;
            const coincideTexto = !busq || v.titulo.toLowerCase().includes(busq) || v.canal.toLowerCase().includes(busq) || (v.descripcion && v.descripcion.toLowerCase().includes(busq));
            return coincideCat && coincideTexto;
        });

        raiz.innerHTML = `
            <div class="yt-raiz ${estado.ocultarTexto ? 'yt-modo-compacto' : ''}">
              <div class="yt-barra">
                <div class="yt-logo"><i class="fa-brands fa-youtube"></i> YouTube en Prig</div>
                <input id="yt-input-buscar" class="yt-campo-buscar" placeholder="Pega un enlace de YouTube (https://...) o busca por tema..." value="${esc(estado.busqueda)}">
                <button class="yt-btn rojo" id="yt-btn-cargar"><i class="fa-solid fa-play"></i> Reproducir</button>
                <button class="yt-btn ${estado.ocultarTexto ? 'azul' : ''}" id="yt-btn-toggle-texto" title="Ocultar o mostrar descripciones de los videos"><i class="fa-solid ${estado.ocultarTexto ? 'fa-eye' : 'fa-eye-slash'}"></i> ${estado.ocultarTexto ? 'Mostrar descripciones' : 'Ocultar texto de videos'}</button>
              </div>

              <div class="yt-chips">
                ${CATEGORIAS.map(c => `
                  <button class="yt-chip ${estado.filtroCategoria === c.id ? 'activo' : ''}" data-cat="${c.id}">${esc(c.label)}</button>
                `).join('')}
              </div>

              <div class="yt-cuerpo">
                <!-- Resumen y Filtro de Avance del Estudiante -->
                <div class="yt-resumen-progreso">
                  <div style="display:flex; align-items:center; gap:8px;">
                    <i class="fa-solid fa-graduation-cap" style="color:var(--accent-green, #a6e3a1); font-size:15px;"></i>
                    <span style="font-weight:700; color:#fff;">Tu avance:</span>
                    <span style="color:var(--text-muted); font-size:11.5px;"><b>${totalCompletados}</b> completados · <b>${totalEnProgreso}</b> en curso · <b>${totalSinIniciar}</b> pendientes</span>
                  </div>
                  <div class="yt-pills-filtro">
                    <button class="yt-pill-progreso ${estado.filtroProgreso === 'todos' ? 'activo' : ''}" data-prog="todos">Todos (${VIDEOS_CURADOS.length})</button>
                    <button class="yt-pill-progreso ${estado.filtroProgreso === 'en_progreso' ? 'activo' : ''}" data-prog="en_progreso">🟡 En curso (${totalEnProgreso})</button>
                    <button class="yt-pill-progreso ${estado.filtroProgreso === 'completados' ? 'activo' : ''}" data-prog="completados">🟢 Completados (${totalCompletados})</button>
                    <button class="yt-pill-progreso ${estado.filtroProgreso === 'sin_iniciar' ? 'activo' : ''}" data-prog="sin_iniciar">⚪ Pendientes (${totalSinIniciar})</button>
                  </div>
                </div>

                ${filtrados.length === 0 ? `
                  <div style="text-align:center; padding:40px; color:var(--text-muted);">
                    <i class="fa-brands fa-youtube" style="font-size:40px; opacity:0.3; margin-bottom:12px; display:block;"></i>
                    <p style="margin:0; font-size:13px;">No se encontraron videos con ese criterio de filtro.</p>
                    <p style="margin:6px 0 0; font-size:11.5px;">Puedes cambiar el filtro de avance, categoría o pegar una URL de YouTube arriba.</p>
                  </div>
                ` : `
                  <div class="yt-grid">
                    ${filtrados.map(v => {
                        const prog = todosProgreso[v.id] || { estado: 'sin_iniciar', porcentaje: 0, ultimoMinuto: '00:00' };
                        const esComp = prog.estado === 'completado' || prog.porcentaje >= 100;
                        const esProg = !esComp && (prog.estado === 'en_progreso' || prog.porcentaje > 0);

                        return `
                          <div class="yt-tarjeta" data-video-id="${esc(v.id)}">
                            <div class="yt-miniatura">
                              <img src="https://i.ytimg.com/vi/${esc(v.id)}/hqdefault.jpg" alt="${esc(v.titulo)}" loading="lazy">
                              <span class="yt-duracion">${esc(v.duracion)}</span>
                              <span class="yt-nivel">${esc(v.nivel)}</span>
                              <span class="yt-idioma">${esc(v.idioma || 'EN')}</span>
                              
                              <button class="yt-btn-quick-check ${esComp ? 'activo' : ''}" title="${esComp ? 'Completado (clic para desmarcar)' : 'Marcar como completado'}" data-video-id="${esc(v.id)}">
                                <i class="fa-solid fa-check"></i>
                              </button>

                              ${esComp ? `
                                <span class="yt-badge-estado completado"><i class="fa-solid fa-circle-check"></i> Completado</span>
                              ` : esProg ? `
                                <span class="yt-badge-estado en-progreso"><i class="fa-solid fa-clock-rotate-left"></i> ${prog.porcentaje}% (${prog.ultimoMinuto || '00:00'})</span>
                              ` : ''}
                            </div>
                            
                            <div class="yt-tarjeta-progreso-barra">
                              <div class="yt-tarjeta-progreso-fill ${esComp ? 'completado' : ''}" style="width:${prog.porcentaje || 0}%;"></div>
                            </div>

                            <div class="yt-tarjeta-info">
                              <h3 class="yt-tarjeta-titulo">${esc(v.titulo)}</h3>
                              <div class="yt-tarjeta-canal"><i class="fa-solid fa-circle-check" style="color:#ff0000; font-size:10px;"></i> ${esc(v.canal)}</div>
                              <p class="yt-tarjeta-desc">${esc(v.descripcion || '')}</p>
                            </div>
                          </div>
                        `;
                    }).join('')}
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

        const btnToggleTexto = $('yt-btn-toggle-texto');
        if (btnToggleTexto) {
            btnToggleTexto.onclick = () => {
                estado.ocultarTexto = !estado.ocultarTexto;
                localStorage.setItem('prig_yt_ocultar_texto', estado.ocultarTexto);
                pintar();
            };
        }

        raiz.querySelectorAll('.yt-chip').forEach(ch => {
            ch.onclick = () => {
                estado.filtroCategoria = ch.dataset.cat;
                pintar();
            };
        });

        raiz.querySelectorAll('.yt-pill-progreso').forEach(pl => {
            pl.onclick = () => {
                estado.filtroProgreso = pl.dataset.prog;
                pintar();
            };
        });

        raiz.querySelectorAll('.yt-btn-quick-check').forEach(btn => {
            btn.onclick = (e) => {
                e.stopPropagation();
                const vidId = btn.dataset.videoId;
                alternarCompletado(vidId);
                pintar();
            };
        });

        raiz.querySelectorAll('.yt-tarjeta').forEach(tar => {
            tar.onclick = (e) => {
                if (e.target.closest('.yt-btn-quick-check')) return;
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
        const prog = obtenerProgreso(v.id);
        const marcas = leerMarcasVideo(v.id);
        const notaClave = `prig_yt_nota_${v.id}`;
        const notaGuardada = localStorage.getItem(notaClave) || '';
        const marcasDetectadas = extraerTimestampsDeTexto(notaGuardada);
        const objetivos = leerObjetivos(v.id);
        const resumen = leerResumen(v.id);
        const superadosObj = objetivos.filter(o => o.superado).length;

        raiz.innerHTML = `
            <div class="yt-raiz">
              <div class="yt-barra">
                <button class="yt-btn" id="yt-btn-volver"><i class="fa-solid fa-arrow-left"></i> Catálogo</button>
                <div class="yt-logo" style="margin-left:6px;"><i class="fa-brands fa-youtube"></i> ${esc(v.titulo)}</div>
                <div style="margin-left:auto; display:flex; gap:8px;">
                  <button class="yt-btn ${estado.ocultarTextoPlayer ? 'azul' : ''}" id="yt-btn-toggle-detalles" title="Ocultar o mostrar texto descriptivo del video">
                    <i class="fa-solid ${estado.ocultarTextoPlayer ? 'fa-eye' : 'fa-eye-slash'}"></i> ${estado.ocultarTextoPlayer ? 'Mostrar texto' : 'Quitar texto (Modo Cine)'}
                  </button>
                  <a class="yt-btn" href="https://www.youtube.com/watch?v=${esc(v.id)}" target="_blank" rel="noopener noreferrer"><i class="fa-solid fa-arrow-up-right-from-square"></i> Abrir en YouTube</a>
                </div>
              </div>

              <div class="yt-player-layout">
                <div class="yt-player-main">
                  <div class="yt-iframe-wrap">
                    <iframe id="yt-iframe-player" src="https://www.youtube-nocookie.com/embed/${esc(v.id)}?enablejsapi=1&autoplay=1&rel=0${prog.segundos > 0 ? `&start=${prog.segundos}` : ''}" allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture" allowfullscreen></iframe>
                  </div>

                  <!-- Control de Avance del Curso -->
                  <div class="yt-progreso-caja">
                    <div class="yt-progreso-fila">
                      <div style="display:flex; align-items:center; gap:8px;">
                        <i class="fa-solid fa-graduation-cap" style="color:var(--accent-green, #a6e3a1); font-size:14px;"></i>
                        <span style="font-weight:700; font-size:12px; color:#fff;">Avance del curso:</span>
                        <span id="yt-badge-progreso-texto" class="yt-prog-badge ${prog.estado}">
                          ${prog.estado === 'completado' ? '¡Completado! 🎉' : (prog.porcentaje > 0 ? `En progreso (${prog.porcentaje}%)` : 'Sin iniciar')}
                        </span>
                      </div>
                      <div style="display:flex; align-items:center; gap:8px; margin-left:auto;">
                        ${prog.segundos > 0 ? `
                          <button class="yt-btn azul" id="yt-btn-reanudar-min" style="padding:3px 8px; font-size:11px;" title="Reanudar video en el último minuto visto">
                            <i class="fa-solid fa-clock-rotate-left"></i> Reanudar en <b id="yt-progreso-ultimo-min">${prog.ultimoMinuto}</b>
                          </button>
                        ` : ''}
                        <button class="yt-btn ${prog.estado === 'completado' ? 'verde' : ''}" id="yt-btn-toggle-completado" style="padding:3px 10px; font-size:11px;">
                          <i class="fa-solid fa-circle-check"></i> ${prog.estado === 'completado' ? 'Completado ✓' : 'Marcar completado'}
                        </button>
                      </div>
                    </div>

                    <div style="display:flex; align-items:center; gap:10px; margin-top:2px;">
                      <input type="range" id="yt-slider-progreso" min="0" max="100" step="5" value="${prog.porcentaje || 0}" style="flex:1; accent-color:#10b981; cursor:pointer;">
                      <span id="yt-slider-valor" style="font-size:12px; font-weight:700; width:45px; text-align:right; color:var(--accent-green, #a6e3a1);">${prog.porcentaje || 0}%</span>
                      <div class="yt-quick-pct-btns">
                        <button class="yt-btn-pct" data-pct="0">0%</button>
                        <button class="yt-btn-pct" data-pct="25">25%</button>
                        <button class="yt-btn-pct" data-pct="50">50%</button>
                        <button class="yt-btn-pct" data-pct="75">75%</button>
                        <button class="yt-btn-pct" data-pct="100">100%</button>
                      </div>
                    </div>
                  </div>

                  <!-- Información y Texto del Video (Se puede ocultar a pedido del usuario) -->
                  <div class="yt-info-video ${estado.ocultarTextoPlayer ? 'oculto' : ''}" id="yt-seccion-info-video">
                    <h2 class="yt-video-titulo">${esc(v.titulo)}</h2>
                    <div style="font-size:11.5px; color:var(--text-muted);">Canal: <b>${esc(v.canal || 'YouTube')}</b> ${v.nivel ? `· Nivel: <span style="color:var(--accent-purple); font-weight:600;">${esc(v.nivel)}</span>` : ''}</div>
                    ${v.descripcion ? `<p style="margin:4px 0 0; font-size:11.5px; color:var(--text-muted); line-height:1.45;">${esc(v.descripcion)}</p>` : ''}

                    <div class="yt-acciones-video" style="margin-top:6px;">
                      <button class="yt-btn azul" id="yt-btn-ir-objetivos" title="Ver o generar objetivos pedagógicos"><i class="fa-solid fa-bullseye"></i> Objetivos didácticos ${objetivos.length > 0 ? `(${superadosObj}/${objetivos.length})` : ''}</button>
                      <button class="yt-btn verde" id="yt-btn-ir-resumen" title="Ver resumen técnico y snippets"><i class="fa-solid fa-file-lines"></i> Resumen & Cheat-Sheet ${resumen ? '✓' : ''}</button>
                      <button class="yt-btn morado" id="yt-btn-crear-desafio-video" title="Generar un desafío interactivo de código evaluado por Prig con este video"><i class="fa-solid fa-wand-magic-sparkles"></i> Crear desafío en Prig</button>
                      <button class="yt-btn" id="yt-btn-toggle-input-extra" title="Agregar texto o transcripción adicional para el análisis de IA"><i class="fa-solid fa-file-pen"></i> ${estado.mostrarInputTextoExtra ? 'Ocultar transcripción extra' : 'Pegar texto/transcripción'}</button>
                    </div>

                    ${estado.mostrarInputTextoExtra ? `
                      <div class="yt-texto-extra-caja" style="margin-top:8px;">
                        <div style="font-size:11px; color:#fff; display:flex; justify-content:space-between; align-items:center;">
                          <span><i class="fa-solid fa-align-left"></i> Texto o Transcripción Adicional del Video:</span>
                          <span style="font-size:10px; color:var(--text-muted);">Se añadirá al contexto del modelo al generar resúmenes u objetivos</span>
                        </div>
                        <textarea id="yt-textarea-extra" class="yt-textarea-extra" placeholder="Pega aquí la transcripción de YouTube, notas del autor o snippets que desees que el modelo considere...">${esc(estado.textoExtra || '')}</textarea>
                      </div>
                    ` : ''}
                  </div>
                </div>

                <div class="yt-lateral">
                  <div class="yt-lateral-tabs">
                    <div class="yt-lateral-tab ${estado.pestanaLateral === 'notas' ? 'activo' : ''}" data-tab="notas"><i class="fa-solid fa-pencil"></i> Notas (${marcas.length})</div>
                    <div class="yt-lateral-tab ${estado.pestanaLateral === 'objetivos' ? 'activo' : ''}" data-tab="objetivos"><i class="fa-solid fa-bullseye"></i> Objetivos ${objetivos.length > 0 ? `(${superadosObj}/${objetivos.length})` : ''}</div>
                    <div class="yt-lateral-tab ${estado.pestanaLateral === 'resumen' ? 'activo' : ''}" data-tab="resumen"><i class="fa-solid fa-file-lines"></i> Resumen IA ${resumen ? '✓' : ''}</div>
                    <div class="yt-lateral-tab ${estado.pestanaLateral === 'tutor' ? 'activo' : ''}" data-tab="tutor"><i class="fa-solid fa-robot"></i> Asistente IA</div>
                  </div>

                  <div class="yt-lateral-cuerpo">
                    ${estado.analisisCargando ? `
                      <div class="yt-loading-box">
                        <i class="fa-solid fa-circle-notch yt-loading-spinner"></i>
                        <div style="font-weight:700; color:#fff;">Analizando clase con IA...</div>
                        <div style="font-size:11px; color:var(--text-muted);">${esc(estado.analisisMensaje)}</div>
                      </div>
                    ` : estado.desafioCreando ? `
                      <div class="yt-loading-box">
                        <i class="fa-solid fa-wand-magic-sparkles yt-loading-spinner" style="color:var(--accent-purple, #cba6f7);"></i>
                        <div style="font-weight:700; color:#fff;">Creando desafío interactivo...</div>
                        <div id="yt-desafio-mensaje-stream" style="font-size:11px; color:var(--text-muted);">${esc(estado.desafioMensaje)}</div>
                      </div>
                    ` : estado.pestanaLateral === 'notas' ? `
                      <!-- Sección 1: Notaciones por Minuto -->
                      <div class="yt-marcas-seccion">
                        <div style="display:flex; justify-content:space-between; align-items:center; font-size:11px;">
                          <span style="font-weight:700; color:#fff;"><i class="fa-solid fa-stopwatch" style="color:var(--accent-blue, #89b4fa);"></i> Notaciones por minuto (${marcas.length})</span>
                          <span id="yt-minuto-activo-badge" style="font-size:10px; color:var(--text-muted);">Clic en ▶ para saltar al min</span>
                        </div>

                        <div class="yt-marca-input-fila">
                          <input id="yt-input-marca-min" class="yt-input-min" placeholder="MM:SS" value="${prog.ultimoMinuto !== '00:00' ? prog.ultimoMinuto : '00:00'}" title="Minuto del video (ej. 05:20 o 1:15:30)">
                          <input id="yt-input-marca-txt" class="yt-input-txt" placeholder="¿Qué ocurre en este minuto?..." title="Nota del minuto">
                          <button class="yt-btn azul" id="yt-btn-agregar-marca" style="padding:5px 9px;" title="Agregar anotación en este minuto"><i class="fa-solid fa-plus"></i></button>
                        </div>

                        <div class="yt-marcas-lista" id="yt-marcas-lista">
                          ${marcas.length === 0 ? `
                            <div style="text-align:center; padding:12px; color:var(--text-muted); font-size:11px; font-style:italic;">
                              Sin notaciones por minuto. Escribe un minuto arriba (ej: 04:30) y una nota para saltar a ese punto clave cuando estudies.
                            </div>
                          ` : marcas.map(m => `
                            <div class="yt-marca-item" data-id="${esc(m.id)}">
                              <button class="yt-timestamp-btn" data-segundos="${m.segundos}" title="Saltar el reproductor al minuto ${esc(m.minuto)}">
                                <i class="fa-solid fa-play" style="font-size:9px;"></i> ${esc(m.minuto)}
                              </button>
                              <span class="yt-marca-texto" title="${esc(m.texto)}">${esc(m.texto)}</span>
                              <div style="display:flex; gap:2px;">
                                <button class="yt-marca-btn" data-accion="recargar" data-segundos="${m.segundos}" title="Forzar salto / recarga en min ${esc(m.minuto)}"><i class="fa-solid fa-rotate-right"></i></button>
                                <button class="yt-marca-btn" data-accion="copiar" data-id="${esc(m.id)}" title="Copiar al cuaderno de notas"><i class="fa-regular fa-copy"></i></button>
                                <button class="yt-marca-btn eliminar" data-accion="eliminar" data-id="${esc(m.id)}" title="Eliminar anotación"><i class="fa-regular fa-trash-can"></i></button>
                              </div>
                            </div>
                          `).join('')}
                        </div>
                      </div>

                      <!-- Sección 2: Cuaderno de Notas Markdown Libre -->
                      <div style="font-size:11px; color:var(--text-muted); display:flex; justify-content:space-between; align-items:center; margin-top:4px;">
                        <span style="font-weight:600; color:#fff;"><i class="fa-solid fa-book-open"></i> Cuaderno de Apuntes</span>
                        <div style="display:flex; gap:4px;">
                          <button class="yt-btn" id="yt-btn-insertar-timestamp" style="padding:2px 7px; font-size:10px;" title="Insertar marca [MM:SS] en el cursor"><i class="fa-regular fa-clock"></i> + [Minuto]</button>
                          <button class="yt-btn verde" id="yt-btn-guardar-archivo" style="padding:2px 7px; font-size:10px;" title="Exportar apuntes y timestamps a un archivo .md en el proyecto"><i class="fa-solid fa-file-export"></i> Exportar</button>
                        </div>
                      </div>

                      ${marcasDetectadas.length > 0 ? `
                        <div class="yt-chips-detectados">
                          <span>Saltos en apuntes:</span>
                          ${marcasDetectadas.map(md => `
                            <button class="yt-chip-seek" data-segundos="${md.segundos}" title="Saltar al minuto ${md.minuto}">▶ ${md.minuto}</button>
                          `).join('')}
                        </div>
                      ` : ''}

                      <textarea id="yt-nota" class="yt-textarea-nota" placeholder="Escribe aquí tus fórmulas, conceptos clave, código y marcas como [12:34] para saltar directamente...">${esc(notaGuardada)}</textarea>
                    ` : estado.pestanaLateral === 'objetivos' ? `
                      <!-- Pestaña de Objetivos Didácticos -->
                      <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:4px;">
                        <span style="font-weight:700; font-size:12px; color:#fff;"><i class="fa-solid fa-bullseye" style="color:var(--accent-blue, #89b4fa);"></i> Objetivos de la Clase</span>
                        <button class="yt-btn azul" id="yt-btn-generar-objetivos" style="padding:2px 8px; font-size:10.5px;" title="Analizar video y dividir en objetivos didácticos">
                          <i class="fa-solid fa-wand-magic-sparkles"></i> ${objetivos.length > 0 ? 'Regenerar' : 'Generar con IA'}
                        </button>
                      </div>

                      ${objetivos.length === 0 ? `
                        <div style="text-align:center; padding:30px 14px; color:var(--text-muted); font-size:11.5px; display:flex; flex-direction:column; align-items:center; gap:10px;">
                          <i class="fa-solid fa-list-check" style="font-size:32px; opacity:0.35; color:var(--accent-blue);"></i>
                          <p style="margin:0; line-height:1.4;">Divide esta clase en 3 a 6 hitos didácticos con timestamps exactos, dificultad y criterios de evaluación.</p>
                          <button class="yt-btn azul" id="yt-btn-generar-objetivos-vacio" style="margin-top:4px;">
                            <i class="fa-solid fa-wand-magic-sparkles"></i> Analizar video y generar objetivos
                          </button>
                        </div>
                      ` : `
                        <div class="yt-objetivos-contenedor">
                          <div style="font-size:11px; color:var(--text-muted); margin-bottom:2px;">
                            Completados: <b style="color:var(--accent-green);">${superadosObj}</b> de <b>${objetivos.length}</b> (${objetivos.length > 0 ? Math.round((superadosObj / objetivos.length) * 100) : 0}%)
                          </div>
                          ${objetivos.map(o => `
                            <div class="yt-objetivo-tarjeta ${o.superado ? 'superado' : ''}" data-id="${esc(o.id)}">
                              <div class="yt-obj-header">
                                <input type="checkbox" class="yt-check-objetivo" data-id="${esc(o.id)}" ${o.superado ? 'checked' : ''} title="Marcar objetivo como completado" style="cursor:pointer; accent-color:#10b981; width:15px; height:15px; margin:0;">
                                <span class="yt-obj-titulo" style="${o.superado ? 'text-decoration:line-through; color:var(--text-muted);' : ''}">${o.numero ? `${o.numero}. ` : ''}${esc(o.titulo)}</span>
                                <span class="yt-badge-dificultad ${esc((o.dificultad || 'intermedio').toLowerCase())}">${esc(o.dificultad || 'Intermedio')}</span>
                              </div>
                              <p class="yt-obj-desc">${esc(o.descripcion)}</p>
                              ${o.criterio_evaluacion ? `
                                <div style="font-size:10.5px; color:#a6adc8; display:flex; align-items:flex-start; gap:5px;">
                                  <i class="fa-solid fa-check-double" style="color:#10b981; margin-top:2px; font-size:10px;"></i>
                                  <span>${esc(o.criterio_evaluacion)}</span>
                                </div>
                              ` : ''}
                              <div class="yt-obj-footer">
                                ${o.inicio_timestamp ? `
                                  <button class="yt-timestamp-btn" data-segundos="${o.inicio_segundos || parsearTimestamp(o.inicio_timestamp)}" title="Saltar al inicio de este objetivo en el video">
                                    <i class="fa-solid fa-play" style="font-size:9px;"></i> ${esc(o.inicio_timestamp)}
                                  </button>
                                ` : '<span></span>'}
                                <button class="yt-btn morado yt-btn-crear-desafio-obj" data-id="${esc(o.id)}" style="padding:2px 7px; font-size:10.5px;" title="Generar un desafío interactivo de código evaluado por Prig enfocado en este objetivo">
                                  <i class="fa-solid fa-code"></i> Crear desafío
                                </button>
                              </div>
                            </div>
                          `).join('')}
                        </div>
                      `}
                    ` : estado.pestanaLateral === 'resumen' ? `
                      <!-- Pestaña de Resumen y Cheat-Sheet -->
                      <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:4px;">
                        <span style="font-weight:700; font-size:12px; color:#fff;"><i class="fa-solid fa-file-lines" style="color:var(--accent-green, #a6e3a1);"></i> Resumen & Cheat-Sheet</span>
                        <div style="display:flex; gap:4px;">
                          <button class="yt-btn verde" id="yt-btn-generar-resumen" style="padding:2px 8px; font-size:10.5px;" title="Analizar video y sintetizar resumen técnico con IA">
                            <i class="fa-solid fa-wand-magic-sparkles"></i> ${resumen ? 'Regenerar' : 'Generar con IA'}
                          </button>
                          ${resumen ? `
                            <button class="yt-btn" id="yt-btn-inyectar-resumen" style="padding:2px 7px; font-size:10.5px;" title="Copiar este resumen al cuaderno de apuntes"><i class="fa-solid fa-file-import"></i> Al cuaderno</button>
                            <button class="yt-btn" id="yt-btn-exportar-resumen" style="padding:2px 7px; font-size:10.5px;" title="Descargar como archivo Markdown"><i class="fa-solid fa-file-arrow-down"></i> .md</button>
                          ` : ''}
                        </div>
                      </div>

                      ${!resumen ? `
                        <div style="text-align:center; padding:30px 14px; color:var(--text-muted); font-size:11.5px; display:flex; flex-direction:column; align-items:center; gap:10px;">
                          <i class="fa-solid fa-file-circle-check" style="font-size:32px; opacity:0.35; color:var(--accent-green);"></i>
                          <p style="margin:0; line-height:1.4;">Genera un resumen técnico ejecutivo, puntos clave, glosario y snippets de código listos para usar a partir del contenido de este video.</p>
                          <button class="yt-btn verde" id="yt-btn-generar-resumen-vacio" style="margin-top:4px;">
                            <i class="fa-solid fa-wand-magic-sparkles"></i> Generar Resumen Técnico con IA
                          </button>
                        </div>
                      ` : `
                        <div class="yt-resumen-contenedor">
                          <!-- Resumen Ejecutivo -->
                          <div class="yt-resumen-caja">
                            <div class="yt-resumen-subtitulo"><i class="fa-solid fa-compass" style="color:#89b4fa;"></i> Resumen Ejecutivo</div>
                            <p class="yt-resumen-texto">${esc(resumen.resumen_ejecutivo || '')}</p>
                          </div>

                          <!-- Puntos Clave -->
                          ${resumen.puntos_clave && resumen.puntos_clave.length > 0 ? `
                            <div class="yt-resumen-caja">
                              <div class="yt-resumen-subtitulo"><i class="fa-solid fa-list-check" style="color:#a6e3a1;"></i> Puntos Clave & Conceptos</div>
                              <ul class="yt-puntos-clave-lista">
                                ${resumen.puntos_clave.map(pt => `
                                  <li class="yt-punto-clave-item"><i class="fa-solid fa-check"></i> <span>${esc(pt)}</span></li>
                                `).join('')}
                              </ul>
                            </div>
                          ` : ''}

                          <!-- Snippets de Código -->
                          ${resumen.snippets_codigo && resumen.snippets_codigo.length > 0 ? `
                            <div class="yt-resumen-caja">
                              <div class="yt-resumen-subtitulo"><i class="fa-solid fa-code" style="color:#cba6f7;"></i> Snippets & Ejemplos de Código</div>
                              ${resumen.snippets_codigo.map((sn, idx) => `
                                <div style="display:flex; flex-direction:column; gap:4px; margin-bottom:6px;">
                                  <div style="display:flex; justify-content:space-between; align-items:center; font-size:10.5px;">
                                    <span style="font-weight:700; color:#cdd6f4;">${esc(sn.titulo || `Snippet #${idx + 1}`)}</span>
                                    <button class="yt-btn-copiar-snippet yt-btn" data-code="${esc(sn.codigo)}" style="padding:1px 6px; font-size:9.5px;"><i class="fa-regular fa-copy"></i> Copiar</button>
                                  </div>
                                  <div class="yt-snippet-box">
                                    <pre class="yt-snippet-code"><code>${esc(sn.codigo)}</code></pre>
                                  </div>
                                  ${sn.explicacion ? `<span style="font-size:10px; color:var(--text-muted);">${esc(sn.explicacion)}</span>` : ''}
                                </div>
                              `).join('')}
                            </div>
                          ` : ''}

                          <!-- Glosario -->
                          ${resumen.glosario && resumen.glosario.length > 0 ? `
                            <div class="yt-resumen-caja">
                              <div class="yt-resumen-subtitulo"><i class="fa-solid fa-spell-check" style="color:#f9e2af;"></i> Glosario de Términos</div>
                              <div style="display:flex; flex-direction:column; gap:5px;">
                                ${resumen.glosario.map(g => `
                                  <div class="yt-glosario-card">
                                    <b style="color:#fff;">${esc(g.termino)}:</b> <span style="color:#cdd6f4;">${esc(g.definicion)}</span>
                                  </div>
                                `).join('')}
                              </div>
                            </div>
                          ` : ''}

                          <!-- Conclusiones -->
                          ${resumen.conclusiones ? `
                            <div class="yt-resumen-caja">
                              <div class="yt-resumen-subtitulo"><i class="fa-solid fa-lightbulb" style="color:#fab387;"></i> Conclusión / Siguiente Paso</div>
                              <p class="yt-resumen-texto">${esc(resumen.conclusiones)}</p>
                            </div>
                          ` : ''}
                        </div>
                      `}
                    ` : `
                      <!-- Pestaña Asistente IA -->
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

        const btnToggleDetalles = $('yt-btn-toggle-detalles');
        if (btnToggleDetalles) {
            btnToggleDetalles.onclick = () => {
                estado.ocultarTextoPlayer = !estado.ocultarTextoPlayer;
                localStorage.setItem('prig_yt_ocultar_texto_player', estado.ocultarTextoPlayer);
                pintar();
            };
        }

        raiz.querySelectorAll('.yt-lateral-tab').forEach(tb => {
            tb.onclick = () => {
                estado.pestanaLateral = tb.dataset.tab;
                pintar();
            };
        });

        // Botones de acción del video
        const btnIrObjetivos = $('yt-btn-ir-objetivos');
        if (btnIrObjetivos) {
            btnIrObjetivos.onclick = () => {
                estado.pestanaLateral = 'objetivos';
                pintar();
                if (objetivos.length === 0 && !estado.analisisCargando) {
                    solicitarAnalisisIA(v, 'objetivos');
                }
            };
        }

        const btnIrResumen = $('yt-btn-ir-resumen');
        if (btnIrResumen) {
            btnIrResumen.onclick = () => {
                estado.pestanaLateral = 'resumen';
                pintar();
                if (!resumen && !estado.analisisCargando) {
                    solicitarAnalisisIA(v, 'resumen');
                }
            };
        }

        const btnCrearDesafioVideo = $('yt-btn-crear-desafio-video');
        if (btnCrearDesafioVideo) {
            btnCrearDesafioVideo.onclick = () => {
                solicitarCrearDesafio(v, null);
            };
        }

        const btnToggleInputExtra = $('yt-btn-toggle-input-extra');
        if (btnToggleInputExtra) {
            btnToggleInputExtra.onclick = () => {
                estado.mostrarInputTextoExtra = !estado.mostrarInputTextoExtra;
                pintar();
            };
        }

        const textareaExtra = $('yt-textarea-extra');
        if (textareaExtra) {
            textareaExtra.oninput = () => {
                estado.textoExtra = textareaExtra.value;
            };
        }

        // Acciones pestaña Objetivos
        const btnGenObj = $('yt-btn-generar-objetivos');
        if (btnGenObj) btnGenObj.onclick = () => solicitarAnalisisIA(v, 'objetivos');
        const btnGenObjVacio = $('yt-btn-generar-objetivos-vacio');
        if (btnGenObjVacio) btnGenObjVacio.onclick = () => solicitarAnalisisIA(v, 'objetivos');

        raiz.querySelectorAll('.yt-check-objetivo').forEach(chk => {
            chk.onchange = () => {
                alternarObjetivoSuperado(v.id, chk.dataset.id, chk.checked);
                pintar();
            };
        });

        raiz.querySelectorAll('.yt-btn-crear-desafio-obj').forEach(btn => {
            btn.onclick = () => {
                const obj = objetivos.find(o => o.id === btn.dataset.id);
                if (obj) solicitarCrearDesafio(v, obj);
            };
        });

        // Acciones pestaña Resumen
        const btnGenRes = $('yt-btn-generar-resumen');
        if (btnGenRes) btnGenRes.onclick = () => solicitarAnalisisIA(v, 'resumen');
        const btnGenResVacio = $('yt-btn-generar-resumen-vacio');
        if (btnGenResVacio) btnGenResVacio.onclick = () => solicitarAnalisisIA(v, 'resumen');

        raiz.querySelectorAll('.yt-btn-copiar-snippet').forEach(btn => {
            btn.onclick = (e) => {
                e.stopPropagation();
                const code = btn.getAttribute('data-code') || '';
                navigator.clipboard.writeText(code).then(() => {
                    const original = btn.innerHTML;
                    btn.innerHTML = '<i class="fa-solid fa-check"></i> ¡Copiado!';
                    setTimeout(() => { btn.innerHTML = original; }, 1500);
                }).catch(() => {
                    alert('No se pudo copiar automáticamente.');
                });
            };
        });

        const btnInyectarResumen = $('yt-btn-inyectar-resumen');
        if (btnInyectarResumen && resumen) {
            btnInyectarResumen.onclick = () => {
                let texto = `\n\n## 💡 Resumen IA\n${resumen.resumen_ejecutivo || ''}\n`;
                if (resumen.puntos_clave && resumen.puntos_clave.length) {
                    texto += `\n### Puntos Clave:\n` + resumen.puntos_clave.map(p => `- ${p}`).join('\n') + `\n`;
                }
                if (resumen.snippets_codigo && resumen.snippets_codigo.length) {
                    texto += `\n### Snippets:\n` + resumen.snippets_codigo.map(s => `\`\`\`${s.lenguaje || ''}\n${s.codigo}\n\`\`\``).join('\n\n') + `\n`;
                }
                const actual = localStorage.getItem(notaClave) || '';
                localStorage.setItem(notaClave, (actual + texto).trim());
                alert('¡Resumen inyectado en el cuaderno de apuntes (pestaña Notas)!');
            };
        }

        const btnExportarResumen = $('yt-btn-exportar-resumen');
        if (btnExportarResumen && resumen) {
            btnExportarResumen.onclick = async () => {
                let md = `# Resumen y Cheat-Sheet: ${v.titulo}\n\n`;
                md += `- **Canal**: ${v.canal || 'YouTube'}\n`;
                md += `- **URL**: https://www.youtube.com/watch?v=${v.id}\n\n`;
                md += `## 🧭 Resumen Ejecutivo\n${resumen.resumen_ejecutivo || ''}\n\n`;
                if (resumen.puntos_clave && resumen.puntos_clave.length) {
                    md += `## 📌 Puntos Clave\n` + resumen.puntos_clave.map(p => `- ${p}`).join('\n') + `\n\n`;
                }
                if (resumen.snippets_codigo && resumen.snippets_codigo.length) {
                    md += `## 💻 Snippets de Código\n`;
                    resumen.snippets_codigo.forEach(s => {
                        md += `### ${s.titulo || 'Snippet'}\n\`\`\`${s.lenguaje || ''}\n${s.codigo}\n\`\`\`\n${s.explicacion ? `${s.explicacion}\n\n` : '\n'}`;
                    });
                }
                if (resumen.glosario && resumen.glosario.length) {
                    md += `## 📖 Glosario\n` + resumen.glosario.map(g => `- **${g.termino}**: ${g.definicion}`).join('\n') + `\n\n`;
                }
                if (resumen.conclusiones) {
                    md += `## 💡 Conclusión\n${resumen.conclusiones}\n\n`;
                }

                const sugerido = `resumen_${v.titulo.toLowerCase().replace(/[^a-z0-9]/g, '_').slice(0, 30)}.md`;
                const nombre = prompt('Guardar resumen en el proyecto como:', sugerido);
                if (!nombre) return;
                try {
                    await window.prigFetchJson('/api/files/write', {
                        method: 'POST',
                        body: JSON.stringify({ path: nombre, content: md })
                    });
                    alert(`Resumen guardado como: ${nombre}`);
                } catch (e) {
                    alert('Error guardando archivo: ' + e.message);
                }
            };
        }

        // Controles de Progreso del Curso en Reproductor
        const btnToggleCompletado = $('yt-btn-toggle-completado');
        if (btnToggleCompletado) {
            btnToggleCompletado.onclick = () => {
                alternarCompletado(v.id);
                pintar();
            };
        }

        const sliderProgreso = $('yt-slider-progreso');
        const sliderValor = $('yt-slider-valor');
        if (sliderProgreso) {
            sliderProgreso.oninput = () => {
                const val = parseInt(sliderProgreso.value, 10);
                if (sliderValor) sliderValor.textContent = `${val}%`;
            };
            sliderProgreso.onchange = () => {
                const val = parseInt(sliderProgreso.value, 10);
                guardarProgreso(v.id, { porcentaje: val });
                pintar();
            };
        }

        raiz.querySelectorAll('.yt-btn-pct').forEach(b => {
            b.onclick = () => {
                const pct = parseInt(b.dataset.pct, 10);
                guardarProgreso(v.id, { porcentaje: pct });
                pintar();
            };
        });

        const btnReanudar = $('yt-btn-reanudar-min');
        if (btnReanudar && prog.segundos > 0) {
            btnReanudar.onclick = () => {
                saltarAMinuto(prog.segundos, false);
            };
        }

        // Acciones de Notaciones con Timestamp
        const inputMarcaMin = $('yt-input-marca-min');
        const inputMarcaTxt = $('yt-input-marca-txt');
        const btnAgregarMarca = $('yt-btn-agregar-marca');

        const guardarNuevaMarca = () => {
            if (!inputMarcaMin || !inputMarcaTxt) return;
            const minStr = inputMarcaMin.value.trim() || '00:00';
            const txt = inputMarcaTxt.value.trim();
            if (!txt) {
                inputMarcaTxt.focus();
                return;
            }
            const seg = parsearTimestamp(minStr);
            const formateado = formatearSegundos(seg);
            const lista = leerMarcasVideo(v.id);
            lista.push({
                id: 'm_' + Date.now() + '_' + Math.floor(Math.random() * 1000),
                minuto: formateado,
                segundos: seg,
                texto: txt,
                fecha: Date.now()
            });
            lista.sort((a, b) => a.segundos - b.segundos);
            guardarMarcasVideo(v.id, lista);
            inputMarcaTxt.value = '';
            pintar();
        };

        if (btnAgregarMarca) btnAgregarMarca.onclick = guardarNuevaMarca;
        if (inputMarcaTxt) {
            inputMarcaTxt.onkeydown = (e) => {
                if (e.key === 'Enter') guardarNuevaMarca();
            };
        }

        // Clics en botones de marcas por minuto
        raiz.querySelectorAll('.yt-timestamp-btn').forEach(tb => {
            tb.onclick = () => {
                const s = parseInt(tb.dataset.segundos, 10);
                saltarAMinuto(s, false);
            };
        });

        raiz.querySelectorAll('.yt-chip-seek').forEach(cb => {
            cb.onclick = () => {
                const s = parseInt(cb.dataset.segundos, 10);
                saltarAMinuto(s, false);
            };
        });

        raiz.querySelectorAll('.yt-marca-btn').forEach(mb => {
            mb.onclick = () => {
                const accion = mb.dataset.accion;
                const id = mb.dataset.id;
                const s = parseInt(mb.dataset.segundos, 10);

                if (accion === 'recargar') {
                    saltarAMinuto(s, true);
                } else if (accion === 'eliminar') {
                    const lista = leerMarcasVideo(v.id).filter(m => m.id !== id);
                    guardarMarcasVideo(v.id, lista);
                    pintar();
                } else if (accion === 'copiar') {
                    const lista = leerMarcasVideo(v.id);
                    const item = lista.find(m => m.id === id);
                    if (item && notaEl) {
                        const insertar = `\n- [${item.minuto}] ${item.texto}\n`;
                        notaEl.value = (notaEl.value || '') + insertar;
                        localStorage.setItem(notaClave, notaEl.value);
                        pintar();
                    }
                }
            };
        });

        // Cuaderno de Notas Markdown
        const notaEl = $('yt-nota');
        if (notaEl) {
            notaEl.oninput = () => {
                localStorage.setItem(notaClave, notaEl.value);
            };
        }

        const btnInsertarTs = $('yt-btn-insertar-timestamp');
        if (btnInsertarTs && notaEl) {
            btnInsertarTs.onclick = () => {
                const p = obtenerProgreso(v.id);
                const stamp = prompt('Minuto para la marca (ej: 05:20 o 1:12:00):', p.ultimoMinuto || '00:00');
                if (!stamp) return;
                const seg = parsearTimestamp(stamp);
                const tag = `[${formatearSegundos(seg)}] `;
                const inicio = notaEl.selectionStart || notaEl.value.length;
                const fin = notaEl.selectionEnd || notaEl.value.length;
                notaEl.value = notaEl.value.substring(0, inicio) + tag + notaEl.value.substring(fin);
                notaEl.selectionStart = notaEl.selectionEnd = inicio + tag.length;
                notaEl.focus();
                localStorage.setItem(notaClave, notaEl.value);
                pintar();
            };
        }

        // Exportar a Archivo de Proyecto
        const btnExportar = $('yt-btn-guardar-archivo');
        if (btnExportar && notaEl) {
            btnExportar.onclick = async () => {
                const contenido = notaEl.value;
                const marcasActuales = leerMarcasVideo(v.id);
                const progActual = obtenerProgreso(v.id);

                if (!contenido.trim() && marcasActuales.length === 0) {
                    return alert('Escribe algunos apuntes o añade notas por minuto antes de exportar.');
                }

                let cuerpoMd = `# Apuntes de Estudio: ${v.titulo}\n\n`;
                cuerpoMd += `- **Canal**: ${v.canal || 'YouTube'}\n`;
                cuerpoMd += `- **URL**: https://www.youtube.com/watch?v=${v.id}\n`;
                cuerpoMd += `- **Avance**: ${progActual.porcentaje}% (${progActual.estado === 'completado' ? 'Completado' : 'En progreso'})\n`;
                cuerpoMd += `- **Última posición**: ${progActual.ultimoMinuto || '00:00'}\n\n`;

                if (marcasActuales.length > 0) {
                    cuerpoMd += `## ⏱️ Notaciones y Momentos Clave\n\n`;
                    marcasActuales.forEach(m => {
                        cuerpoMd += `- [${m.minuto}](https://www.youtube.com/watch?v=${v.id}&t=${m.segundos}s) — ${m.texto}\n`;
                    });
                    cuerpoMd += `\n`;
                }

                if (contenido.trim()) {
                    cuerpoMd += `## 📝 Cuaderno de Notas\n\n${contenido}\n`;
                }

                const sugerido = `notas_${v.titulo.toLowerCase().replace(/[^a-z0-9]/g, '_').slice(0, 30)}.md`;
                const nombre = prompt('Nombre del archivo de notas en tu proyecto:', sugerido);
                if (!nombre) return;
                try {
                    await window.prigFetchJson('/api/files/write', {
                        method: 'POST',
                        body: JSON.stringify({ path: nombre, content: cuerpoMd })
                    });
                    alert(`Notas guardadas en el proyecto como: ${nombre}`);
                } catch (e) {
                    alert('Error guardando archivo: ' + e.message);
                }
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
        cargarCursosJson();
    }

    async function cargarCursosJson() {
        try {
            const r = await fetch('/static/data/cursos_youtube.json');
            if (r.ok) {
                const lista = await r.json();
                if (Array.isArray(lista)) {
                    let nuevo = false;
                    lista.forEach(c => {
                        if (!VIDEOS_CURADOS.some(v => v.id === c.id)) {
                            VIDEOS_CURADOS.push(c);
                            nuevo = true;
                        }
                    });
                    if (nuevo && estado.vista === 'catalogo') pintar();
                }
            }
        } catch (e) { /* usa lista interna */ }
    }

    document.addEventListener('prig:herramienta-abierta', (e) => {
        if (e.detail && e.detail.modalId === 'modal-youtube') {
            pintar();
            cargarCursosJson();
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
