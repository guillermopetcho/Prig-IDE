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
    const md = (t) => (typeof marked !== 'undefined' ? (typeof DOMPurify !== 'undefined' ? DOMPurify.sanitize(marked.parse(String(t || ''))) : marked.parse(String(t || ''))) : esc(t));

const VIDEOS_CURADOS = [
        {
                "id": "nLRL_NcnK-4",
                "titulo": "Harvard CS50P – Introduction to Programming with Python",
                "canal": "freeCodeCamp / Harvard (David J. Malan)",
                "categoria": "python",
                "duracion": "15:56:00",
                "nivel": "Principiante / Universidad",
                "idioma": "en",
                "descripcion": "El curso universitario completo de Harvard sobre Python: funciones, variables, bucles, excepciones, librerías, pruebas unitarias con pytest, POO y expresiones regulares.",
                "universidad": "Harvard",
                "playlist": "PLhQjrBD2T3817j24-GogXmWAmO55JDXv7"
        },
        {
                "id": "rfscVS0vtbw",
                "titulo": "Aprende Python – Curso Completo de Python desde Cero",
                "canal": "freeCodeCamp Español (Estefania)",
                "categoria": "python",
                "duracion": "4:26:00",
                "nivel": "Principiante",
                "idioma": "es",
                "descripcion": "Fundamentos exhaustivos de Python 3 en español: tipos de datos, listas, tuplas, diccionarios, bucles for/while, funciones y proyectos prácticos paso a paso."
        },
        {
                "id": "_uQrJ0TkZlc",
                "titulo": "Python Full Course for Beginners",
                "canal": "Programming with Mosh",
                "categoria": "python",
                "duracion": "6:14:07",
                "nivel": "Principiante / Intermedio",
                "idioma": "en",
                "descripcion": "Formación práctica en Python: control de flujo, estructuras de datos nativas, programación orientada a objetos, manejo de excepciones y automatización."
        },
        {
                "id": "XKHEtdqhLK8",
                "titulo": "Python Full Course for free (12 Horas Completas)",
                "canal": "Bro Code",
                "categoria": "python",
                "duracion": "12:00:00",
                "nivel": "Principiante / Intermedio",
                "idioma": "en",
                "descripcion": "Guía enciclopédica de 12 horas: sintaxis, POO, multithreading, decoradores, generadores, interfaces gráficas con Tkinter y sockets de red."
        },
        {
                "id": "nKPbfIU442g",
                "titulo": "Curso de PYTHON desde CERO (Completo)",
                "canal": "Soy Dalto",
                "categoria": "python",
                "duracion": "8:06:30",
                "nivel": "Principiante / Intermedio",
                "idioma": "es",
                "descripcion": "Curso intensivo de 8 horas desde nivel cero hasta conceptos avanzados: lambdas, modularización, archivos y programación orientada a objetos en español."
        },
        {
                "id": "chPhlsHoEPo",
                "titulo": "Curso Python para Principiantes",
                "canal": "Fazt Code",
                "categoria": "python",
                "duracion": "3:55:00",
                "nivel": "Principiante",
                "idioma": "es",
                "descripcion": "Tutorial integral paso a paso de Python para crear aplicaciones, scripts de automatización y backend estructurado."
        },
        {
                "id": "ZDa-Z5JzLYM",
                "titulo": "Python OOP Masterclass: Classes, Inheritance & Dunders",
                "canal": "Corey Schafer",
                "categoria": "python",
                "duracion": "45:00",
                "nivel": "Intermedio / Senior",
                "idioma": "en",
                "descripcion": "Explicación magistral sobre programación orientada a objetos: métodos de clase, estáticos, herencia, métodos mágicos dunder y property decorators."
        },
        {
                "id": "am_hzAG0dWI",
                "titulo": "Python Data Structures and Algorithms Masterclass",
                "canal": "freeCodeCamp / Jovian",
                "categoria": "python",
                "duracion": "1:33",
                "nivel": "Intermedio / Senior",
                "idioma": "en",
                "descripcion": "Implementación de algoritmos y estructuras de datos en Python: árboles binarios de búsqueda, grafos, Dijkstra y programación dinámica."
        },
        {
                "id": "8jLOx1hD3_o",
                "titulo": "C++ Programming Course – Beginner to Advanced (C++20)",
                "canal": "freeCodeCamp (Daniel Gakwaya)",
                "categoria": "cpp",
                "duracion": "31:20:00",
                "nivel": "Principiante / Senior",
                "idioma": "en",
                "descripcion": "El curso definitivo de C++ moderno (C++20) de 31 horas: punteros, gestión del heap, RAII, conceptos (concepts), templates y la STL completa."
        },
        {
                "id": "vLnPwxZdW4Y",
                "titulo": "C++ Tutorial for Beginners – Full Course",
                "canal": "freeCodeCamp (Mike Dane)",
                "categoria": "cpp",
                "duracion": "4:01:00",
                "nivel": "Principiante",
                "idioma": "en",
                "descripcion": "Fundamentos sólidos de C++: tipos primitivos, condicionales, punteros, direcciones de memoria, constructores y clases."
        },
        {
                "id": "-TkoO8Z07hI",
                "titulo": "C++ Full Course for free (6 Horas)",
                "canal": "Bro Code",
                "categoria": "cpp",
                "duracion": "6:00:00",
                "nivel": "Principiante / Intermedio",
                "idioma": "en",
                "descripcion": "Sintaxis de C++ moderno, arrays, desreferenciación de punteros, paso por referencia const &, constructores y sobrecarga de operadores."
        },
        {
                "id": "SfGuIVzE_Os",
                "titulo": "How C++ Works: Compilation, Linking and Executables",
                "canal": "The Cherno",
                "categoria": "cpp",
                "duracion": "21:00",
                "nivel": "Intermedio / Senior",
                "idioma": "en",
                "descripcion": "Arquitectura interna de C++: preprocesador, generación de código máquina .obj y enlazado estático/dinámico de ejecutables."
        },
        {
                "id": "DTxHyVn0ODg",
                "titulo": "Pointers in C++: Memory Addresses & Lifetimes",
                "canal": "The Cherno",
                "categoria": "cpp",
                "duracion": "16:00",
                "nivel": "Intermedio / Senior",
                "idioma": "en",
                "descripcion": "El modelo de memoria en C++: direcciones de memoria, desreferenciación, punteros void*, punteros inteligentes y ciclo de vida en el heap."
        },
        {
                "id": "18c3MTX0PK0",
                "titulo": "Welcome to C++ Series / C++ Philosophy and Architecture",
                "canal": "The Cherno",
                "categoria": "cpp",
                "duracion": "7:05",
                "nivel": "Fundamentos",
                "idioma": "en",
                "descripcion": "Por qué C++ es el estándar en motores gráficos, sistemas operativos y motores de inferencia de Inteligencia Artificial."
        },
        {
                "id": "yBHfWx6_oXQ",
                "titulo": "Curso Completo de C++ para Principiantes",
                "canal": "ATL Academy",
                "categoria": "cpp",
                "duracion": "3:30:00",
                "nivel": "Principiante",
                "idioma": "es",
                "descripcion": "Fundamentos de C++ en español: algoritmos, memoria, estructuras de control, funciones y programación orientada a objetos con ejercicios."
        },
        {
                "id": "8mAITcNt710",
                "titulo": "Harvard CS50 – Full Computer Science Course (C & Algoritmos)",
                "canal": "freeCodeCamp / Harvard (David J. Malan)",
                "categoria": "cpp",
                "duracion": "24:51:37",
                "nivel": "Intermedio / Senior",
                "idioma": "en",
                "descripcion": "Arquitectura de bajo nivel en C: gestión manual de memoria (malloc/free), punteros, segmentación de memoria y estructuras de datos complejas.",
                "universidad": "Harvard",
                "playlist": "PLhQjrBD2T380F_inVRXMIHCqLaNUd7bN4"
        },
        {
                "id": "UzxYlbK2c7E",
                "titulo": "Stanford CS229: Machine Learning Course",
                "canal": "Stanford University (Prof. Andrew Ng)",
                "categoria": "ml",
                "duracion": "20 Clases (~25 Horas)",
                "nivel": "Senior / Avanzado",
                "idioma": "en",
                "descripcion": "El curso universitario de referencia de Stanford: formulación matemática de aprendizaje supervisado, gradiente descendente, ecuaciones normales, SVM, kernels y teoría de aprendizaje.",
                "universidad": "Stanford",
                "playlist": "PLoROMvodv4rMiGQp3WXShtMGgzqpfVfbU"
        },
        {
                "id": "i_LwzRVP7bg",
                "titulo": "Machine Learning for Everybody – Full Course",
                "canal": "freeCodeCamp (Kylie Ying)",
                "categoria": "ml",
                "duracion": "3:53:00",
                "nivel": "Principiante / Intermedio",
                "idioma": "en",
                "descripcion": "Data Science y ML práctico con Python y Scikit-Learn: regresión lineal/logística, KNN, naive bayes, árboles de decisión y métricas de validación."
        },
        {
                "id": "NWONeJKn6kc",
                "titulo": "Machine Learning Course for Beginners – Complete End-to-End",
                "canal": "freeCodeCamp (Ayush Singh)",
                "categoria": "ml",
                "duracion": "9:52:00",
                "nivel": "Intermedio / Senior",
                "idioma": "en",
                "descripcion": "Curso integral de 10 horas: álgebra matricial, feature engineering, Decision Trees, Random Forest, Gradient Boosting y reducción con PCA."
        },
        {
                "id": "vVg7WrelMeA",
                "titulo": "Machine Learning From Scratch in Python with NumPy",
                "canal": "Patrick Loeber",
                "categoria": "ml",
                "duracion": "8:12",
                "nivel": "Senior",
                "idioma": "en",
                "descripcion": "Construcción pura de algoritmos desde cero en Python y NumPy sin Scikit-Learn: Linear/Logistic Regression, KNN, Naive Bayes, SVM, Árboles y PCA."
        },
        {
                "id": "GwIo3gDZCVQ",
                "titulo": "Machine Learning Full Course (10 Horas)",
                "canal": "Edureka",
                "categoria": "ml",
                "duracion": "9:38:32",
                "nivel": "Intermedio",
                "idioma": "en",
                "descripcion": "Guía práctica de algoritmos de clasificación, clustering K-Means, aprendizaje supervisado y pipelines de datos con Python."
        },
        {
                "id": "fNk_zzaMoSs",
                "titulo": "The Essence of Linear Algebra: Vectors, Spans, Basis & Transformations",
                "canal": "3Blue1Brown (Grant Sanderson)",
                "categoria": "matematicas",
                "duracion": "10:00",
                "nivel": "Fundamentos",
                "idioma": "en",
                "descripcion": "Geometría e intuición visual del álgebra lineal: transformaciones lineales, determinantes, producto escalar, autovalores y autovectores.",
                "playlist": "PLZHQObOWTQDPD3MizzM2xVFitgF8hE_ab"
        },
        {
                "id": "nLmhmB6NzcM",
                "titulo": "0/1 Knapsack Problem – Dynamic Programming Formulation",
                "canal": "Abdul Bari",
                "categoria": "algoritmos",
                "duracion": "28:24",
                "nivel": "Avanzado",
                "idioma": "en",
                "descripcion": "Optimización algorítmica clásica: programación dinámica matricial bottom-up y resolución analítica paso a paso."
        },
        {
                "id": "UZZD9d9YqnQ",
                "titulo": "MIT 6.S191: Introduction to Deep Learning",
                "canal": "MIT OpenCourseWare (Dr. Alexander Amini)",
                "categoria": "dl",
                "duracion": "10 Clases (~12 Horas)",
                "nivel": "Avanzado / Senior",
                "idioma": "en",
                "descripcion": "El curso oficial de Deep Learning del MIT: perceptrones, backpropagation multivariable, optimizadores estocásticos (SGD/Adam) y representaciones latentes.",
                "universidad": "MIT",
                "playlist": "PLtBw6njQRU-rwp5__7C0oIVt26ZgjG9NI"
        },
        {
                "id": "kCc8FmEb1nY",
                "titulo": "Let's build GPT: from scratch, in code, spelled out",
                "canal": "Andrej Karpathy",
                "categoria": "dl",
                "duracion": "1:56:20",
                "nivel": "Senior",
                "idioma": "en",
                "descripcion": "Construcción completa de un Transformer autorregresivo (estilo GPT-2) en PyTorch desde cero, explicando self-attention multi-head y skip connections."
        },
        {
                "id": "VMj-3S1tku0",
                "titulo": "Building micrograd: Neural networks and backpropagation from scratch",
                "canal": "Andrej Karpathy",
                "categoria": "dl",
                "duracion": "2:25:00",
                "nivel": "Senior",
                "idioma": "en",
                "descripcion": "Creación paso a paso de un motor de autograd escalar en Python y entrenamiento de una red neuronal multicapa sin librerías externas."
        },
        {
                "id": "kCc8FmEb1nY",
                "titulo": "Building makemore: Language Modeling from Bigram to Multilayer Perceptron",
                "canal": "Andrej Karpathy",
                "categoria": "dl",
                "duracion": "1:57:00",
                "nivel": "Senior",
                "idioma": "en",
                "descripcion": "Modelado de lenguaje desde bigramas estadísticos hasta redes neuronales densas (Bengio et al. 2003) con embeddings y función Negative Log-Likelihood."
        },
        {
                "id": "zduSFxRajkE",
                "titulo": "Let's build the GPT Tokenizer (BPE)",
                "canal": "Andrej Karpathy",
                "categoria": "dl",
                "duracion": "2:13:35",
                "nivel": "Senior",
                "idioma": "en",
                "descripcion": "Implementación del algoritmo Byte Pair Encoding (BPE) a nivel de bytes UTF-8 para tokenización en modelos de lenguaje como GPT-2 y GPT-4."
        },
        {
                "id": "Z_ikDlimN6A",
                "titulo": "PyTorch for Deep Learning & Machine Learning – Full Course",
                "canal": "freeCodeCamp (Daniel Bourke)",
                "categoria": "dl",
                "duracion": "26:15:00",
                "nivel": "Intermedio / Senior",
                "idioma": "en",
                "descripcion": "La formación de PyTorch más completa: tensores, visión computacional con CNNs, Transfer Learning, model deployment y tracking experimental."
        },
        {
                "id": "c36lUUr864M",
                "titulo": "Deep Learning With PyTorch – Full Course",
                "canal": "Patrick Loeber",
                "categoria": "dl",
                "duracion": "4:35:42",
                "nivel": "Intermedio / Senior",
                "idioma": "en",
                "descripcion": "Flujo de trabajo profesional en PyTorch: cálculo de gradientes con autograd, DataLoader/Dataset personalizados, CNNs y redes recurrentes."
        },
        {
                "id": "tPYj3fFJGjk",
                "titulo": "TensorFlow 2.0 Complete Course – Neural Networks for Beginners",
                "canal": "freeCodeCamp (Tech With Tim)",
                "categoria": "dl",
                "duracion": "6:52:00",
                "nivel": "Principiante / Intermedio",
                "idioma": "en",
                "descripcion": "Ecosistema TensorFlow 2 y Keras: construcción de modelos convolucionales (Conv2D), procesamiento de lenguaje natural y redes recurrentes."
        },
        {
                "id": "vT1JzLTH4G4",
                "titulo": "Stanford CS231n: Convolutional Neural Networks for Visual Recognition",
                "canal": "Stanford University (Fei-Fei Li & Andrej Karpathy)",
                "categoria": "dl",
                "duracion": "57:57",
                "nivel": "Senior / Avanzado",
                "idioma": "en",
                "descripcion": "El curso clásico de Stanford sobre visión computacional: capas convolucionales, pooling, normalización, AlexNet, VGG y ResNet.",
                "universidad": "Stanford",
                "playlist": "PL3FW7Lu3i5JvHM8ljYj-zLfQRF3EO8sYv"
        },
        {
                "id": "fVYxOy505_4",
                "titulo": "Stanford CS224N: Natural Language Processing with Deep Learning",
                "canal": "Stanford University (Prof. Christopher Manning)",
                "categoria": "dl",
                "duracion": "2:30",
                "nivel": "Senior / Avanzado",
                "idioma": "en",
                "descripcion": "Representación semántica vectorial (Word2Vec, GloVe), redes secuenciales recurrentes, atención y arquitecturas de Transformers para NLP.",
                "universidad": "Stanford",
                "playlist": "PLoROMvodv4rOSH4v6133s9LFPRHjEmbmJ"
        },
        {
                "id": "8SF_h3xF3cE",
                "titulo": "Practical Deep Learning for Coders (Lesson 1)",
                "canal": "fast.ai (Jeremy Howard)",
                "categoria": "dl",
                "duracion": "1:22:56",
                "nivel": "Intermedio / Senior",
                "idioma": "en",
                "descripcion": "Metodología top-down de fast.ai: entrenar modelos de visión y NLP con estado del arte en pocas líneas de código antes de descender a las matemáticas."
        },
        {
                "id": "aircAruvnKk",
                "titulo": "But what is a neural network? | Deep learning, chapter 1",
                "canal": "3Blue1Brown (Grant Sanderson)",
                "categoria": "dl",
                "duracion": "19:00",
                "nivel": "Fundamentos",
                "idioma": "en",
                "descripcion": "La mejor explicación visual de cómo una red neuronal clasifica patrones mediante combinaciones lineales, pesos, sesgos y activaciones.",
                "playlist": "PLZHQObOWTQDNU6R1_67000Dx_ZCJB-3pi"
        },
        {
                "id": "iX_on3VxZzk",
                "titulo": "Tu primera red neuronal en Python y Tensorflow",
                "canal": "Ringa Tech",
                "categoria": "dl",
                "duracion": "16:25",
                "nivel": "Principiante",
                "idioma": "es",
                "descripcion": "Tutorial práctico en español creando y entrenando una red neuronal en Python usando TensorFlow/Keras para conversión de grados Celsius a Fahrenheit."
        },
        {
                "id": "MRIv2IwFTPg",
                "titulo": "¿Qué es una Red Neuronal? La Neurona y el Perceptrón",
                "canal": "DotCSV (Carlos Santana)",
                "categoria": "dl",
                "duracion": "13:00",
                "nivel": "Fundamentos",
                "idioma": "es",
                "descripcion": "Explicación didáctica y rigurosa en español de la neurona artificial, entradas, pesos sinápticos, sesgo y funciones de activación."
        },
        {
                "id": "8hly31xKli0",
                "titulo": "Algorithms and Data Structures for Beginners – Full Course",
                "canal": "NeetCode / freeCodeCamp",
                "categoria": "algoritmos",
                "duracion": "5:20:00",
                "nivel": "Senior",
                "idioma": "en",
                "descripcion": "Estructuras de datos esenciales: Arrays estáticos y dinámicos, Listas enlazadas, Árboles BST, Heaps, Grafos y QuickSort."
        },
        {
                "id": "ZA-tUyM_y7s",
                "titulo": "MIT 6.006: Introduction to Algorithms – Peak Finding & Complexity",
                "canal": "MIT OpenCourseWare (Erik Demaine)",
                "categoria": "algoritmos",
                "duracion": "50:00",
                "nivel": "Avanzado / Universidad",
                "idioma": "en",
                "descripcion": "Fundamentos de análisis asintótico, cotas Big-O y búsqueda de picos en tiempo logarítmico con división y conquista.",
                "universidad": "MIT",
                "playlist": "PLUl4u3cNGP61Oq3tWYp6V_F-5jb5L2iHb"
        },
        {
                "id": "i53Gi_K3o7I",
                "titulo": "System Design Interview: How to Scale a System to Millions of Users",
                "canal": "ByteByteGo (Alex Xu)",
                "categoria": "system_design",
                "duracion": "16:00",
                "nivel": "Senior",
                "idioma": "en",
                "descripcion": "Arquitectura escalable: balanceadores de carga, CDN, particionado de bases de datos, colas asíncronas y caché con Redis."
        },
        {
                "id": "k6U-i4gXkLM",
                "titulo": "MIT 6.0001: Introduction to Computer Science and Programming in Python",
                "canal": "MIT OpenCourseWare (Dr. Ana Bell & John Guttag)",
                "universidad": "MIT",
                "categoria": "python",
                "playlist": "PLUl4u3cNGP63WbdFxL8giv4yhgdMGaZNA",
                "duracion": "12 Clases (~12 Horas)",
                "nivel": "Principiante / Universidad",
                "idioma": "en",
                "descripcion": "El curso troncal oficial de ciencias de la computación del MIT: descomposición computacional, abstracción, funciones, tuplas, listas, diccionarios, algoritmos de búsqueda y orientación a objetos."
        },
        {
                "id": "C1lhuz6pZC0",
                "titulo": "MIT 6.0002: Introduction to Computational Thinking and Data Science",
                "canal": "MIT OpenCourseWare (Prof. John Guttag & Eric Grimson)",
                "universidad": "MIT",
                "categoria": "python",
                "playlist": "PLUl4u3cNGP619EG1wp0kT-7rDE_wKMaW-",
                "duracion": "40:57",
                "nivel": "Intermedio / Universidad",
                "idioma": "en",
                "descripcion": "La continuación del MIT en Python orientada a ciencia de datos: optimización de mochilas y grafos, pensamiento estocástico, simulaciones de Monte Carlo, modelado estadístico y clustering de datos."
        },
        {
                "id": "8DvywoWv6fI",
                "titulo": "Python for Everybody (PY4E) – Full University Course",
                "canal": "Univ. of Michigan (Dr. Charles Severance / freeCodeCamp)",
                "universidad": "Univ. of Michigan",
                "categoria": "python",
                "playlist": "PLlRFEj9H3Oj7Bp8-DfGpfWx4ahuPBvee",
                "duracion": "13:40:10",
                "nivel": "Principiante / Intermedio",
                "idioma": "en",
                "descripcion": "La prestigiosa formación universitaria de la Universidad de Michigan: sintaxis moderna de Python 3, estructuras de datos nativas, regex, sockets de red, web scraping y bases de datos relacionales SQL."
        },
        {
                "id": "WbzNRTTrX0g",
                "titulo": "Harvard CS50AI: Introduction to Artificial Intelligence with Python",
                "canal": "Harvard University (Brian Yu & David J. Malan)",
                "universidad": "Harvard",
                "categoria": "python",
                "playlist": "PL_mM4cC3R5MXs9J4smEUhKfRrqMNqgQeK",
                "duracion": "12 Horas",
                "nivel": "Intermedio / Universidad",
                "idioma": "en",
                "descripcion": "El curso de inteligencia artificial con Python de Harvard: algoritmos de búsqueda (Minimax, A*), representación de conocimiento, probabilidad bayesiana, optimización, aprendizaje automático y redes neuronales."
        },
        {
                "id": "kMzH3tfP6f8",
                "titulo": "Stanford CS106B: Programming Abstractions in C++",
                "canal": "Stanford University (Julie Zelenski)",
                "universidad": "Stanford",
                "categoria": "cpp",
                "playlist": "PLFE6E58F856038C69",
                "duracion": "43:03",
                "nivel": "Intermedio / Universidad",
                "idioma": "en",
                "descripcion": "Curso emblemático de Stanford en C++: recursión profunda, backtracking, punteros y gestión dinámica de memoria en el heap, plantillas (templates), algoritmos de ordenamiento y estructuras de datos abstractas."
        },
        {
                "id": "9mZw6Rwz1vg",
                "titulo": "Modern C++ for Computer Vision and Robotics (C++17/C++20)",
                "canal": "Univ. of Bonn (Prof. Cyrill Stachniss & Ignacio Vizzo)",
                "universidad": "Univ. of Bonn",
                "categoria": "cpp",
                "playlist": "PLgnQpQtFTOGRM59sr3nSL8BmeMZR9GCIA",
                "duracion": "1:02:55",
                "nivel": "Intermedio / Senior",
                "idioma": "en",
                "descripcion": "Formación de vanguardia de la Universidad de Bonn: C++ moderno (C++17/C++20), CMake, gestión de memoria RAII, smart pointers, lambdas, polimorfismo y librerías de alto rendimiento para visión y robótica."
        },
        {
                "id": "PjST2n7abAY",
                "titulo": "CMU 15-445/645: Database Systems (Modern C++20 Bustub)",
                "canal": "Carnegie Mellon University (Prof. Andy Pavlo)",
                "universidad": "CMU",
                "categoria": "cpp",
                "playlist": "PLSE8ODhjZXjaKScG3l0nuOiDTT31UknW1",
                "duracion": "1:23:29",
                "nivel": "Senior / Universidad",
                "idioma": "en",
                "descripcion": "El legendario curso de arquitectura de sistemas de CMU: diseño e implementación en C++20 de un motor de bases de datos relacionales completo (buffer pool, B+ Trees, índices concurrentes y query execution)."
        },
        {
                "id": "V1tINV2-9p4",
                "titulo": "Stanford CS149: Parallel Computing & Systems (C++, Multicore & GPUs)",
                "canal": "Stanford University (Prof. Kayvon Fatahalian)",
                "universidad": "Stanford",
                "categoria": "cpp",
                "playlist": "PLo6lM83QnS3S5dE-Qe7V1P7XpB_6tqW8D",
                "duracion": "1:12:22",
                "nivel": "Senior / Universidad",
                "idioma": "en",
                "descripcion": "Arquitectura y optimización de software de alto rendimiento en Stanford: paralelismo a nivel de hilos e instrucciones en C++, coherencia de caché, OpenMP, shaders y programación de GPUs con CUDA."
        },
        {
                "id": "86xWVb4XIyE",
                "titulo": "The Essence of C++ & Architecture of Modern Software",
                "canal": "The University of Edinburgh (Bjarne Stroustrup)",
                "universidad": "Univ. of Edinburgh",
                "categoria": "cpp",
                "duracion": "1:39:11",
                "nivel": "Senior / Arquitectura",
                "idioma": "en",
                "descripcion": "Clase magistral dictada en la Universidad de Edimburgo por Bjarne Stroustrup, el creador de C++: filosofía del lenguaje, diseño de tipos, abstracción de costo cero (zero-overhead) y evolución de los estándares ISO."
        },
        {
                "id": "Cx5Z-OslNWE",
                "titulo": "MIT 18.065: Matrix Methods in Data Analysis, Signal Processing & ML",
                "canal": "MIT OpenCourseWare (Prof. Gilbert Strang)",
                "universidad": "MIT",
                "categoria": "ml",
                "playlist": "PLUl4u3cNGP63oMNUHXqIUcrkS2PivhN3k",
                "duracion": "36 Clases (~30 Horas)",
                "nivel": "Fundamentos / Universidad",
                "idioma": "en",
                "descripcion": "La cumbre pedagógica de Gilbert Strang en el MIT: álgebra lineal aplicada al aprendizaje automático, descomposición en valores singulares (SVD), análisis de componentes principales (PCA) y optimización convexa."
        },
        {
                "id": "wqpIohLjsAY",
                "titulo": "Cornell CS4780: Machine Learning for Intelligent Systems",
                "canal": "Cornell University (Prof. Kilian Weinberger)",
                "universidad": "Cornell",
                "categoria": "ml",
                "playlist": "PLl8OlHZGYOQ7bkVbuS1t8hPXG5N42wgK6",
                "duracion": "51:00",
                "nivel": "Intermedio / Senior",
                "idioma": "en",
                "descripcion": "Uno de los cursos universitarios más elogiados del mundo: fundamentos rigurosos de SVM, kernel trick, árboles de decisión, boosting, bagging, deep learning y teoría de generalización estadística."
        },
        {
                "id": "mbyG85GZ0PI",
                "titulo": "Caltech CS156: Learning From Data",
                "canal": "Caltech (Prof. Yaser Abu-Mostafa)",
                "universidad": "Caltech",
                "categoria": "ml",
                "playlist": "PLD63A284B76153189",
                "duracion": "18 Clases (~20 Horas)",
                "nivel": "Fundamentos / Universidad",
                "idioma": "en",
                "descripcion": "El curso universitario canónico de Caltech sobre la teoría matemática del aprendizaje automático: dimensión VC, dilema sesgo-varianza, regularización, teoría de validación y límites de generalización."
        },
        {
                "id": "0xaLT4Svzgo",
                "titulo": "MIT 6.036: Introduction to Machine Learning",
                "canal": "MIT OpenCourseWare (Prof. Tamara Broderick)",
                "universidad": "MIT",
                "categoria": "ml",
                "playlist": "PLUl4u3cNGP60eZ_1i3f49hC5q9G_o-pS_",
                "duracion": "1:20:57",
                "nivel": "Intermedio / Universidad",
                "idioma": "en",
                "descripcion": "El curso troncal de pregrado en Machine Learning del MIT: clasificadores lineales, funciones de pérdida, descenso de gradiente estocástico, regresión logística, redes neuronales y algoritmos de clustering."
        },
        {
                "id": "JAB_plj2rbA",
                "titulo": "Stanford CS224W: Machine Learning with Graphs",
                "canal": "Stanford University (Prof. Jure Leskovec)",
                "universidad": "Stanford",
                "categoria": "ml",
                "playlist": "PLoROMvodv4rPLKxIpqhZXsQWmThkJYXV9",
                "duracion": "11:55",
                "nivel": "Avanzado / Senior",
                "idioma": "en",
                "descripcion": "El curso de vanguardia de Stanford sobre grafos y aprendizaje relacional: embeddings de nodos (Node2Vec, DeepWalk), Graph Neural Networks (GCN, GraphSAGE, GAT) y aplicaciones biomédicas y de redes."
        },
        {
                "id": "TjZBTDzGeGg",
                "titulo": "MIT 6.034: Artificial Intelligence",
                "canal": "MIT OpenCourseWare (Prof. Patrick Winston)",
                "universidad": "MIT",
                "categoria": "ml",
                "playlist": "PLUl4u3cNGP63gFHB6xb-kVBiQHYe_4hSi",
                "duracion": "24 Clases (~23 Horas)",
                "nivel": "Fundamentos / Universidad",
                "idioma": "en",
                "descripcion": "Un clásico atemporal del MIT por Patrick Winston: razonamiento simbólico, búsqueda en árboles, propagación de restricciones, redes semánticas, máquinas de vectores de soporte e inferencia."
        },
        {
                "id": "_NLHFoVNlbg",
                "titulo": "Stanford CS230: Deep Learning",
                "canal": "Stanford University (Prof. Andrew Ng)",
                "universidad": "Stanford",
                "categoria": "dl",
                "playlist": "PLoROMvodv4rNRRGdS0rBbXOUGA0wjdh1X",
                "duracion": "1:00:17",
                "nivel": "Intermedio / Avanzado",
                "idioma": "en",
                "descripcion": "La formación aplicada de Deep Learning de Stanford dictada por Andrew Ng: arquitecturas de redes neuronales, hiperparámetros, optimización, visión computacional con CNNs y procesamiento secuencial."
        },
        {
                "id": "SQ3fZ1sAqXI",
                "titulo": "Stanford CS336: Language Modeling from Scratch",
                "canal": "Stanford University (Prof. Percy Liang & Tatsunori Hashimoto)",
                "universidad": "Stanford",
                "categoria": "dl",
                "playlist": "PLoROMvodv4rMqXOcazWaTUHhq-yembLCV",
                "duracion": "1:18:59",
                "nivel": "Senior / Cutting-Edge",
                "idioma": "en",
                "descripcion": "El curso más moderno y técnico de Stanford para construir Modelos de Lenguaje (LLMs) desde cero: tokenización BPE, implementación de Transformers en PyTorch, paralelismo en GPUs, scaling laws y post-entrenamiento (RLHF)."
        },
        {
                "id": "bHSDPgZYie0",
                "titulo": "Stanford CS25: Transformers United",
                "canal": "Stanford Online (CS25 Seminar)",
                "universidad": "Stanford",
                "categoria": "dl",
                "playlist": "PLoROMvodv4rNiJRchCzutFw5ItR_Z27CM",
                "duracion": "1:16:46",
                "nivel": "Senior / Estado del Arte",
                "idioma": "en",
                "descripcion": "El seminario de posgrado de Stanford con los creadores e investigadores más destacados de la IA generativa: mecanismos de atención, modelos autorregresivos, modelos multimodales, inferencia eficiente y agentes."
        },
        {
                "id": "bkVCAk9Nsss",
                "titulo": "Stanford CS330: Deep Multi-Task and Meta-Learning",
                "canal": "Stanford University (Prof. Chelsea Finn)",
                "universidad": "Stanford",
                "categoria": "dl",
                "playlist": "PLoROMvodv4rNjRoawgt72BBNwL2V7doGI",
                "duracion": "1:11:58",
                "nivel": "Senior / Investigación",
                "idioma": "en",
                "descripcion": "Curso de posgrado de Stanford enfocado en meta-aprendizaje (aprender a aprender): Few-Shot Learning, MAML (Model-Agnostic Meta-Learning), aprendizaje multitarea y adaptación rápida en visión y robótica."
        },
        {
                "id": "WsvFL-LjA6U",
                "titulo": "Stanford CS234: Reinforcement Learning",
                "canal": "Stanford University (Prof. Emma Brunskill)",
                "universidad": "Stanford",
                "categoria": "dl",
                "playlist": "PLoROMvodv4rOSOPzutgyCTapiGlY2Nd8u",
                "duracion": "1:19:08",
                "nivel": "Avanzado / Senior",
                "idioma": "en",
                "descripcion": "El curso avanzado de Stanford sobre aprendizaje por refuerzo: procesos de decisión de Markov (MDP), programación dinámica, Q-learning, aproximación de funciones con deep learning y búsqueda de políticas."
        },
        {
                "id": "K_Dh0Sxujuc",
                "titulo": "Stanford CS224U: Natural Language Understanding",
                "canal": "Stanford University (Prof. Christopher Potts)",
                "universidad": "Stanford",
                "categoria": "dl",
                "playlist": "PLoROMvodv4rOwvldxftJTmoR3kRcWkJBp",
                "duracion": "1:13:52",
                "nivel": "Avanzado / Senior",
                "idioma": "en",
                "descripcion": "Semántica computacional y comprensión de lenguaje natural en Stanford: modelos de espacio vectorial, análisis de sentimientos, extracción de relaciones, fine-tuning y evaluación rigurosa de LLMs."
        },
        {
                "id": "2pWv7GOvuf0",
                "titulo": "Reinforcement Learning Course by David Silver",
                "canal": "Google DeepMind / UCL (Prof. David Silver)",
                "universidad": "UCL / DeepMind",
                "categoria": "dl",
                "playlist": "PLqYmG7hTraZDM-OYHWgPebj2MfCFzFObQ",
                "duracion": "10 Clases (~15 Horas)",
                "nivel": "Senior / Fundamentos de RL",
                "idioma": "en",
                "descripcion": "El curso fundamental por excelencia impartido por David Silver (creador de AlphaGo en DeepMind): MDPs, métodos Monte Carlo, Temporal Difference Learning, Policy Gradients y Deep Q-Networks."
        },
        {
                "id": "7R52wiUgxZI",
                "titulo": "DeepMind x UCL: Deep Learning Lecture Series",
                "canal": "Google DeepMind & UCL (DeepMind Research Team)",
                "universidad": "UCL / DeepMind",
                "categoria": "dl",
                "playlist": "PLqYmG7hTX2B-0L1V_mN1bO8D98r94a0S2",
                "duracion": "1:25:18",
                "nivel": "Intermedio / Senior",
                "idioma": "en",
                "descripcion": "Serie conjunta de 12 clases magistrales entre DeepMind y University College London: redes neuronales profundas, optimización de segundo orden, visión computacional avanzada, atención y modelos generativos."
        },
        {
                "id": "JHrlF10v2Og",
                "titulo": "UC Berkeley CS285: Deep Reinforcement Learning",
                "canal": "UC Berkeley RAIL (Prof. Sergey Levine)",
                "universidad": "UC Berkeley",
                "categoria": "dl",
                "playlist": "PL_iWQOsE6TfURIIhCrlt-wj9ByIVpbfGc",
                "duracion": "10:16",
                "nivel": "Senior / Doctorado",
                "idioma": "en",
                "descripcion": "El curso de referencia mundial en Deep RL de Berkeley: clonación conductual, policy gradients analíticos, Actor-Critic, model-based RL, meta-RL y algoritmos fuera de política (SAC, TD3)."
        },
        {
                "id": "tFR6Likf4VI",
                "titulo": "UC Berkeley CS294: Deep Unsupervised Learning",
                "canal": "UC Berkeley (Prof. Pieter Abbeel)",
                "universidad": "UC Berkeley",
                "categoria": "dl",
                "playlist": "PL_iJu012NOxdq9-y-vRk4O6_z42xZ29Vj",
                "duracion": "14 Clases (~18 Horas)",
                "nivel": "Senior / Cutting-Edge",
                "idioma": "en",
                "descripcion": "Modelos generativos y aprendizaje no supervisado de vanguardia en Berkeley: modelos autorregresivos (PixelCNN), Variational Autoencoders (VAEs), Normalizing Flows, GANs y Diffusion Models."
        },
        {
                "id": "SGZ6BttHMPw",
                "titulo": "Neural Networks and Deep Learning Class",
                "canal": "Université de Sherbrooke (Prof. Hugo Larochelle)",
                "universidad": "U. de Sherbrooke",
                "categoria": "dl",
                "playlist": "PL6Xpj9I5qXYEcOhn7TqghAJ6NAPrNmUBH",
                "duracion": "10 Módulos",
                "nivel": "Avanzado / Matemáticas",
                "idioma": "en",
                "descripcion": "Formulación matemática rigurosa de redes neuronales: capas densas, funciones de activación, entrenamiento multivariable por retropropagación, RBMs, autoencoders y regularización."
        },
        {
                "id": "1L0TKZQcUtA",
                "titulo": "MIT 6.S094: Deep Learning for Self-Driving Cars",
                "canal": "MIT (Dr. Lex Fridman)",
                "universidad": "MIT",
                "categoria": "dl",
                "playlist": "PLrAXtmErZgOeiKm4sgNOknGvNjby9efdf",
                "duracion": "1:31:29",
                "nivel": "Intermedio / Avanzado",
                "idioma": "en",
                "descripcion": "Curso insignia del MIT aplicando Deep Learning a vehículos autónomos: visión por computadora en tiempo real, redes convolucionales, localización y sistemas de percepción con redes neuronales."
        },
        {
                "id": "J7DzL2_Na80",
                "titulo": "MIT 18.06: Linear Algebra – Full University Course",
                "canal": "MIT OpenCourseWare (Prof. Gilbert Strang)",
                "universidad": "MIT",
                "categoria": "matematicas",
                "playlist": "PLE7DDD91010BC51F8",
                "duracion": "39:49",
                "nivel": "Universidad",
                "idioma": "en",
                "descripcion": "La legendaria cátedra universitaria de álgebra lineal del MIT impartida por Gilbert Strang: geometría de ecuaciones lineales, eliminación gaussiana, espacios vectoriales, ortogonalidad, determinantes, autovalores, autovectores y descomposición en valores singulares (SVD)."
        },
        {
                "id": "WUvTyaaNkzM",
                "titulo": "3Blue1Brown: Essence of Calculus",
                "canal": "3Blue1Brown (Grant Sanderson)",
                "categoria": "matematicas",
                "playlist": "PLZHQObOWTQDMsr9K-rj53DwVRMYO3t5Yr",
                "duracion": "12 Capítulos (~3.5 Horas)",
                "nivel": "Principiante / Intermedio",
                "idioma": "en",
                "descripcion": "Explicación visual e intuitiva del cálculo diferencial e integral: la paradoja de la derivada, regla de la cadena y producto, funciones exponenciales, integrales y el Teorema Fundamental del Cálculo, series de Taylor y límites."
        },
        {
                "id": "KbB0FjPg0mw",
                "titulo": "Harvard Stat 110: Introduction to Probability",
                "canal": "Harvard University (Prof. Joseph Blitzstein)",
                "universidad": "Harvard",
                "categoria": "matematicas",
                "playlist": "PL2SOU6wwxB0uwwH80KTQ6ht66KWxbzTIo",
                "duracion": "34 Clases (~32 Horas)",
                "nivel": "Intermedio / Universidad",
                "idioma": "en",
                "descripcion": "El prestigioso curso de probabilidad de la Universidad de Harvard: espacios muestrales, probabilidad condicional, regla de Bayes, variables aleatorias discretas y continuas, esperanza matemática, varianza, distribuciones conjuntas, cadenas de Markov y Teorema del Límite Central."
        },
        {
                "id": "L3LMbpZIKhQ",
                "titulo": "MIT 6.042J: Mathematics for Computer Science",
                "canal": "MIT OpenCourseWare (Prof. Tom Leighton & Marten van Dijk)",
                "universidad": "MIT",
                "categoria": "matematicas",
                "playlist": "PLB7540DEDD482705B",
                "duracion": "44:09",
                "nivel": "Universidad",
                "idioma": "en",
                "descripcion": "Fundamentos matemáticos indispensables para ciencias de la computación del MIT: métodos de demostración, lógica proposicional y de predicados, teoría de grafos, relaciones de recurrencia, aritmética modular y teoría de conteo para análisis de algoritmos."
        },
        {
                "id": "7K1sB05pE0A",
                "titulo": "MIT 18.01: Single Variable Calculus",
                "canal": "MIT OpenCourseWare (Prof. David Jerison)",
                "universidad": "MIT",
                "categoria": "matematicas",
                "playlist": "PL590CCC2BC5AF3EF8",
                "duracion": "51:33",
                "nivel": "Universidad",
                "idioma": "en",
                "descripcion": "Cálculo diferencial e integral de una variable del MIT: límites y continuidad, diferenciación analítica y geométrica, aproximaciones lineales, optimización, teorema del valor medio, integración de Riemann y cálculo fundamental."
        },
        {
                "id": "PxCxlsl_YwY",
                "titulo": "MIT 18.02: Multivariable Calculus",
                "canal": "MIT OpenCourseWare (Prof. Denis Auroux)",
                "universidad": "MIT",
                "categoria": "matematicas",
                "playlist": "PL4C4C8A7D06566F38",
                "duracion": "35 Clases (~35 Horas)",
                "nivel": "Universidad",
                "idioma": "en",
                "descripcion": "Cálculo multivariable indispensable para Machine Learning y física: vectores y matrices en 3D, derivadas parciales, gradiente y matriz jacobiana, multiplicadores de Lagrange, integrales dobles y triples, y teoremas de Green, Stokes y Divergencia."
        },
        {
                "id": "XDhJ8lVGbl8",
                "titulo": "MIT 18.03: Differential Equations",
                "canal": "MIT OpenCourseWare (Prof. Arthur Mattuck)",
                "universidad": "MIT",
                "categoria": "matematicas",
                "playlist": "PLB5173151D835F531",
                "duracion": "33 Clases (~33 Horas)",
                "nivel": "Universidad",
                "idioma": "en",
                "descripcion": "Ecuaciones diferenciales ordinarias (EDO) del MIT: campos de direcciones, ecuaciones de primer orden separables y lineales, osciladores armónicos de segundo orden, transformada de Laplace, convolución y sistemas lineales con matrices."
        },
        {
                "id": "0oBJN8F616U",
                "titulo": "MIT 18.085: Computational Science and Engineering I",
                "canal": "MIT OpenCourseWare (Prof. Gilbert Strang)",
                "universidad": "MIT",
                "categoria": "matematicas",
                "playlist": "PLE7DDD91010BC53F8",
                "duracion": "49:32",
                "nivel": "Avanzado / Universidad",
                "idioma": "en",
                "descripcion": "Matemáticas aplicadas e ingeniería computacional de Strang: diferencias finitas, matrices simétricas definidas positivas, métodos de elementos finitos, transformada rápida de Fourier (FFT) y algoritmos numéricos de álgebra matricial."
        },
        {
                "id": "VPZD_aij8H0",
                "titulo": "MIT 18.650: Statistics for Applications",
                "canal": "MIT OpenCourseWare (Prof. Philippe Rigollet)",
                "universidad": "MIT",
                "categoria": "matematicas",
                "duracion": "24 Clases (~22 Horas)",
                "nivel": "Avanzado / Universidad",
                "idioma": "en",
                "descripcion": "Estadística matemática rigurosa para Machine Learning y ciencia de datos del MIT: estimación por máxima verosimilitud (MLE), intervalos de confianza, test de hipótesis estadísticas, modelos lineales generalizados, bondad de ajuste y PCA."
        },
        {
                "id": "2MuDZIAzBMY",
                "titulo": "Stanford CS109: Probability for Computer Scientists",
                "canal": "Stanford Online (Prof. Chris Piech)",
                "universidad": "Stanford",
                "categoria": "matematicas",
                "playlist": "PLoROMvodv4rOpr_A7B9SriE_iZmkanvUg",
                "duracion": "28 Clases (~26 Horas)",
                "nivel": "Intermedio / Universidad",
                "idioma": "en",
                "descripcion": "Probabilidad diseñada especialmente para programadores y científicos de la computación: axiomas de probabilidad, conteo combinatorio, variables aleatorias discretas y continuas, inferencia bayesiana, estimación de parámetros para algoritmos y Machine Learning."
        },
        {
                "id": "kV1ru-Inzl4",
                "titulo": "Stanford EE364A: Convex Optimization I",
                "canal": "Stanford Online (Prof. Stephen Boyd)",
                "universidad": "Stanford",
                "categoria": "matematicas",
                "duracion": "1:18:27",
                "nivel": "Avanzado / Universidad",
                "idioma": "en",
                "descripcion": "La referencia mundial en optimización convexa de Stephen Boyd: conjuntos convexos, funciones convexas, problemas de optimización lineal y cuadrática, dualidad de Lagrange, condiciones KKT y métodos de punto interior para aprendizaje automático."
        },
        {
                "id": "AqDxrj8K480",
                "titulo": "Oxford 1st Year Mathematics: Introductory Calculus",
                "canal": "Oxford Mathematics",
                "universidad": "Oxford",
                "categoria": "matematicas",
                "playlist": "PL4d5ZtfQonW0A4VHeiY0gSkX1QEraaacE",
                "duracion": "Clase Magistral (~1 Hora)",
                "nivel": "Universidad",
                "idioma": "en",
                "descripcion": "Clase magistral universitaria de primer año en la Universidad de Oxford: rigor matemático de límites, derivadas, cálculo analítico y fundamentos del análisis matemático universitario."
        },
        {
                "id": "MieZJ0bxv7k",
                "titulo": "Oxford 1st Year Mathematics: Linear Algebra 1",
                "canal": "Oxford Mathematics (Prof. Andy Wathen)",
                "universidad": "Oxford",
                "categoria": "matematicas",
                "playlist": "PL4d5ZtfQonW0A4VHeiY0gSkX1QEraaacE",
                "duracion": "51:36",
                "nivel": "Universidad",
                "idioma": "en",
                "descripcion": "Cátedra formal de la Universidad de Oxford sobre álgebra lineal: reducción de sistemas lineales a formas triangulares, matrices escalonadas reducidas por filas y bases de espacios vectoriales."
        },
        {
                "id": "k0zKoTvngUY",
                "titulo": "Mathematics for Machine Learning: Linear Algebra",
                "canal": "Imperial College London / Coursera (Dr. Sam Cooper & David Dye)",
                "universidad": "Imperial College London",
                "categoria": "matematicas",
                "playlist": "PLiiljHvN6z1_o1ztXTKWPrShrMrBLo5P3",
                "duracion": "3:50:40",
                "nivel": "Intermedio / Universidad",
                "idioma": "en",
                "descripcion": "El álgebra lineal que todo ingeniero de Machine Learning necesita: operaciones con matrices, transformaciones lineales, determinantes, autovalores, autovectores y su aplicación práctica al algoritmo PageRank de Google."
        },
        {
                "id": "u5DM0ljvljI",
                "titulo": "Mathematics for Machine Learning: Multivariate Calculus",
                "canal": "Imperial College London / Coursera (Dr. Sam Cooper)",
                "universidad": "Imperial College London",
                "categoria": "matematicas",
                "playlist": "PLiiljHvN6z193BBzS0Ln8NnqQmzimTW23",
                "duracion": "1:50",
                "nivel": "Intermedio / Universidad",
                "idioma": "en",
                "descripcion": "Cálculo multivariable aplicado al entrenamiento de redes neuronales: cálculo de gradientes multidimensionales, derivadas direccionales, aproximación de funciones, regresión no lineal y descenso de gradiente."
        },
        {
                "id": "p_di4Zn4wz4",
                "titulo": "3Blue1Brown: Differential Equations & Dynamical Systems",
                "canal": "3Blue1Brown (Grant Sanderson)",
                "categoria": "matematicas",
                "playlist": "PLZHQObOWTQDNPOjrT6KVlfJuKtYTftqHs",
                "duracion": "5 Capítulos (~2 Horas)",
                "nivel": "Intermedio",
                "idioma": "en",
                "descripcion": "Comprender las ecuaciones diferenciales desde una perspectiva visual: péndulos no lineales, el plano de fases, series de Fourier en física y cómo las computadoras simulan sistemas dinámicos continuos."
        },
        {
                "id": "qBigTkBLU6g",
                "titulo": "StatQuest: Statistics Fundamentals Clearly Explained",
                "canal": "StatQuest with Josh Starmer",
                "categoria": "matematicas",
                "playlist": "PLblh5JKnVLUL4svJmxvEpjP-3PSpG5n-F",
                "duracion": "3:42",
                "nivel": "Principiante / Intermedio",
                "idioma": "en",
                "descripcion": "Las ideas clave de la estadística explicadas paso a paso sin jerga innecesaria: distribución normal, desviación estándar, p-values, intervalos de confianza, test t de Student y regresión lineal."
        },
        {
                "id": "JnTa9XtvmfI",
                "titulo": "Linear Algebra – Full College Course",
                "canal": "freeCodeCamp (Dr. Jim Hefferon)",
                "categoria": "matematicas",
                "duracion": "20:00:00",
                "nivel": "Principiante / Universidad",
                "idioma": "en",
                "descripcion": "Un curso universitario completo de 20 horas de álgebra lineal: sistemas lineales, geometría vectorial, espacios de Hilbert, transformaciones lineales, ortogonalidad, determinantes y formas canónicas."
        },
        {
                "id": "HfACrKJ_Y2w",
                "titulo": "Calculus 1 – Full College Course",
                "canal": "freeCodeCamp (Dr. Linda Green)",
                "categoria": "matematicas",
                "duracion": "11:53:48",
                "nivel": "Principiante / Universidad",
                "idioma": "en",
                "descripcion": "Cálculo 1 universitario exhaustivo de 12 horas: límites infinitos, definición épsilon-delta, derivadas de funciones trigonométricas y exponenciales, regla de la cadena, optimización y sumas de Riemann."
        },
        {
                "id": "7gigNsz4Oe8",
                "titulo": "Calculus 2 – Full College Course",
                "canal": "freeCodeCamp (Dr. Linda Green)",
                "categoria": "matematicas",
                "duracion": "6:52:53",
                "nivel": "Intermedio / Universidad",
                "idioma": "en",
                "descripcion": "Cálculo integral universitario avanzado: técnicas de integración por partes, sustitución trigonométrica, fracciones parciales, integrales impropias, series infinitas de potencias y series de Taylor."
        },
        {
                "id": "xxpc-HPKN28",
                "titulo": "Statistics – A Full University Course on Data Science Basics",
                "canal": "freeCodeCamp.org",
                "categoria": "matematicas",
                "duracion": "8:15:04",
                "nivel": "Principiante / Intermedio",
                "idioma": "en",
                "descripcion": "Formación universitaria de 8 horas en estadística para ciencia de datos: recolección de datos, estadística descriptiva, probabilidad básica, distribuciones binomial y normal, test de hipótesis y regresión bivariada."
        },
        {
                "id": "LwCRRUa8yTU",
                "titulo": "College Algebra – Full Course",
                "canal": "freeCodeCamp.org",
                "categoria": "matematicas",
                "duracion": "6:43:47",
                "nivel": "Principiante",
                "idioma": "en",
                "descripcion": "Repaso exhaustivo de álgebra superior: operaciones con polinomios, factorización, ecuaciones cuadráticas, funciones racionales, logaritmos, exponentes y sistemas no lineales."
        },
        {
                "id": "G9JxuWk7BDA",
                "titulo": "Discrete Mathematics Course for Beginners",
                "canal": "freeCodeCamp.org",
                "categoria": "matematicas",
                "duracion": "9:05:36",
                "nivel": "Principiante / Intermedio",
                "idioma": "en",
                "descripcion": "Matemáticas discretas para ciencias computacionales: teoría de conjuntos, lógica proposicional, tablas de verdad, relaciones de equivalencia, funciones y algoritmos de grafos."
        },
        {
                "id": "tyDKR4FG3Yw",
                "titulo": "Discrete Math I – Entire Course (Rosen)",
                "canal": "Kimberly Brehm",
                "categoria": "matematicas",
                "duracion": "10:20",
                "nivel": "Principiante / Universidad",
                "idioma": "en",
                "descripcion": "El aclamado curso universitario de matemáticas discretas basado en el libro de Kenneth Rosen: lógica, reglas de inferencia, teoría de conjuntos, inducción matemática y combinatoria."
        },
        {
                "id": "Ro4HeaD41m0",
                "titulo": "Curso Completo de Matrices y Álgebra Lineal",
                "canal": "Matemáticas profe Alex",
                "categoria": "matematicas",
                "playlist": "PLeySRPnY35dG2sJk4Z42Z8G7Z4zV9g1aM",
                "duracion": "40+ Videos (~8 Horas)",
                "nivel": "Principiante / Intermedio",
                "idioma": "es",
                "descripcion": "Curso completo paso a paso en español: suma y multiplicación de matrices, matriz inversa por método de Gauss-Jordan y adjunta, determinantes por cofactores y regla de Cramer."
        },
        {
                "id": "vnzkcGD2qD4",
                "titulo": "OpenFING: Cálculo Diferencial e Integral en Una Variable (CDIVV)",
                "canal": "OpenFING (Facultad de Ingeniería, UdelaR)",
                "universidad": "UdelaR",
                "categoria": "matematicas",
                "playlist": "PLD6R49T-tN5z8fJdY55a15qO3j22650vA",
                "duracion": "40 Clases (~40 Horas)",
                "nivel": "Universidad",
                "idioma": "es",
                "descripcion": "Cátedra universitaria completa de Cálculo en una variable de la Universidad de la República (Uruguay): axioma de completitud de los reales, sucesiones, límites, funciones continuas, cálculo diferencial e integral de Riemann."
        },
        {
                "id": "TLh_6G7i4_w",
                "titulo": "Derivadas y Cálculo desde Cero – Clase Magistral",
                "canal": "El Traductor de Ingeniería (Damián Pedraza)",
                "categoria": "matematicas",
                "duracion": "47:23",
                "nivel": "Principiante / Intermedio",
                "idioma": "es",
                "descripcion": "Explicación conceptual profunda y sin fórmulas de memoria: la verdadera definición de la derivada, la recta tangente, la tasa instantánea de cambio y las reglas de derivación demostradas de forma lógica."
        },
        {
                "id": "B5oxL1AQpLo",
                "titulo": "100 Derivadas Resueltas desde Cero – Curso Completo",
                "canal": "Matemáticas con Juan",
                "categoria": "matematicas",
                "duracion": "5:08:37",
                "nivel": "Principiante / Intermedio",
                "idioma": "es",
                "descripcion": "Taller integral práctico de cálculo diferencial: 100 derivadas explicadas minuciosamente de menor a mayor complejidad, aplicando reglas de potencias, productos, cocientes y regla de la cadena."
        },
        {
                "id": "eI4an8aSsgw",
                "titulo": "Precalculus Course – Full College Course",
                "canal": "freeCodeCamp (Dr. Linda Green)",
                "categoria": "matematicas",
                "duracion": "5:22:02",
                "nivel": "Principiante / Intermedio",
                "idioma": "en",
                "descripcion": "Fundamentos matemáticos para cálculo y computación: trigonometría, círculo unitario, identidades trigonométricas, funciones inversas, exponenciales y logaritmos."
        },
        {
                "id": "L6YqHxYHa7A",
                "titulo": "MIT 6.S081: Operating System Engineering (xv6 RISC-V)",
                "canal": "MIT PDOS (Prof. Frans Kaashoek & Robert Morris)",
                "universidad": "MIT",
                "categoria": "arquitectura_so",
                "playlist": "PL2zRqk16zX5xP9V3eY71Q_sM5Z-mN4o-1",
                "duracion": "24 Clases (~26 Horas)",
                "nivel": "Avanzado / Universidad",
                "idioma": "en",
                "descripcion": "El curso troncal de ingeniería de sistemas operativos del MIT basado en xv6 sobre arquitectura RISC-V: llamadas al sistema, aislamiento de memoria, tablas de páginas multinivel, traps, interrupciones hardware, bloqueos con semáforos y sistemas de archivos con journaling."
        },
        {
                "id": "pPzVV2kkGHc",
                "titulo": "UC Berkeley CS162: Operating Systems and System Programming",
                "canal": "UC Berkeley (Prof. John Kubiatowicz)",
                "universidad": "UC Berkeley",
                "categoria": "arquitectura_so",
                "duracion": "1:23:03",
                "nivel": "Avanzado / Universidad",
                "idioma": "en",
                "descripcion": "Cátedra universitaria de Berkeley sobre sistemas operativos: procesos e hilos, primitivas de sincronización (mutex, semáforos, variables de condición), algoritmos de planificación de CPU, memoria virtual y paginación, entrada/salida y sistemas de archivos."
        },
        {
                "id": "BIpPTqHK-Lc",
                "titulo": "Computer Architecture & Digital Design – Masterclass",
                "canal": "ETH Zürich / CMU (Prof. Onur Mutlu)",
                "universidad": "ETH Zürich",
                "categoria": "arquitectura_so",
                "duracion": "35 Clases (~40 Horas)",
                "nivel": "Universidad / Exhaustivo",
                "idioma": "en",
                "descripcion": "La referencia mundial en arquitectura de computadoras del Prof. Onur Mutlu: diseño de procesadores, ejecución fuera de orden (Out-of-Order Execution), predicción de saltos, jerarquías y coherencia de memoria caché, GPUs y computación en memoria (PIM)."
        },
        {
                "id": "9DWlqtsNGV0",
                "titulo": "MIT 6.004: Computation Structures – From Gates to Processors",
                "canal": "MIT OpenCourseWare (Prof. Chris Terman & Steve Ward)",
                "universidad": "MIT",
                "categoria": "arquitectura_so",
                "playlist": "PLUl4u3cNGP62WVs95MNq3dQBqY2vGOtQ2",
                "duracion": "25 Clases (~26 Horas)",
                "nivel": "Universidad",
                "idioma": "en",
                "descripcion": "El puente de ingeniería del MIT entre circuitos digitales y software: compuertas CMOS, diseño de ALUs, datapath de procesadores RISC-V, pipelining, memoria virtual y diseño del núcleo de sistemas operativos."
        },
        {
                "id": "3LVeEjsn8Ts",
                "titulo": "A New Golden Age for Computer Architecture (ACM Turing Lecture)",
                "canal": "ACM (John Hennessy & David Patterson)",
                "universidad": "UC Berkeley",
                "categoria": "arquitectura_so",
                "duracion": "1:45:00",
                "nivel": "Conferencia Magistral",
                "idioma": "en",
                "descripcion": "La conferencia magistral de los galardonados con el Premio Turing John Hennessy (Stanford) y David Patterson (Berkeley): el fin de la ley de Moore y la escala de Dennard, el auge de RISC-V y las arquitecturas específicas de dominio (DSAs) para aceleración de IA."
        },
        {
                "id": "9PPrrSyubG0",
                "titulo": "Building an 8-bit Breadboard Computer from Scratch",
                "canal": "Ben Eater",
                "categoria": "arquitectura_so",
                "playlist": "PLUOaI24LpvQN2Y53vWepO2LMabKPIplar",
                "duracion": "15:23",
                "nivel": "Principiante / Intermedio",
                "idioma": "en",
                "descripcion": "Construcción paso a paso de una computadora programable de 8 bits en protoboards: módulo de reloj con 555, registros A/B, bus de datos, ALU con sumadores, memoria RAM, microcódigo EEPROM y decodificador de instrucciones."
        },
        {
                "id": "mXw9ruZaxzQ",
                "titulo": "Operating Systems – Full University Course",
                "canal": "Neso Academy",
                "categoria": "arquitectura_so",
                "playlist": "PLBlnK6fEyqRiVpkKlSXDRA-G9x0H_n1gG",
                "duracion": "77 Lecciones (~15 Horas)",
                "nivel": "Principiante / Intermedio",
                "idioma": "en",
                "descripcion": "Cátedra enciclopédica de sistemas operativos: gestión de procesos, bloque de control de procesos (PCB), planificación de CPU (FCFS, SJF, Round Robin), concurrencia, interbloqueos (Deadlocks), algoritmo del banquero y memoria virtual."
        },
        {
                "id": "Ol8D69VKX2k",
                "titulo": "Computer Organization and Architecture (COA) – Full Course",
                "canal": "Neso Academy",
                "categoria": "arquitectura_so",
                "playlist": "PLBlnK6fEyqRj8D3G3P71c7xYn4gS1wZlD",
                "duracion": "7:01",
                "nivel": "Principiante / Intermedio",
                "idioma": "en",
                "descripcion": "Organización y microarquitectura de computadoras: ciclo de instrucción fetch-decode-execute, modos de direccionamiento, arquitecturas RISC vs CISC, pipelines con resolución de riesgos (hazards) y mapas de memoria caché."
        },
        {
                "id": "ov7byCtRhjM",
                "titulo": "Operating Systems: The 4 Pillars (Three Easy Pieces / OSTEP)",
                "canal": "Prof. Remzi Arpaci-Dusseau (UW-Madison)",
                "universidad": "Univ. of Wisconsin",
                "categoria": "arquitectura_so",
                "duracion": "15:00",
                "nivel": "Intermedio / Universidad",
                "idioma": "en",
                "descripcion": "Los 4 pilares fundamentales de los sistemas operativos por el autor de OSTEP: virtualización de CPU (procesos y scheduling), virtualización de memoria (páginas y TLBs), concurrencia (locks y semáforos) y persistencia (archivos y discos)."
        },
        {
                "id": "QZwneRb-zqA",
                "titulo": "Exploring How Computers Work – From Logic to CPU",
                "canal": "Sebastian Lague",
                "categoria": "arquitectura_so",
                "playlist": "PLFt_AvWsXl0dPhqDfL1CNnOvGYgFP9b3J",
                "duracion": "18:12",
                "nivel": "Principiante / Intermedio",
                "idioma": "en",
                "descripcion": "Construcción visual e intuitiva de una computadora en software: cómo las compuertas lógicas forman sumadores, cómo los biestables (latches) almacenan memoria y cómo una CPU lee instrucciones para ejecutar programas completos."
        },
        {
                "id": "FZGugFqdr60",
                "titulo": "The Central Processing Unit (CPU) – Microarchitecture",
                "canal": "CrashCourse (Carrie Anne Philbin)",
                "categoria": "arquitectura_so",
                "playlist": "PL1mtdjDVOoOqJzeaJAV15Tq0tZ1vKj7ZV",
                "duracion": "11:38",
                "nivel": "Principiante",
                "idioma": "en",
                "descripcion": "Cómo funciona un procesador por dentro: la unidad aritmético-lógica (ALU), registros de control, buses internos de datos y el ciclo de reloj de instrucciones."
        },
        {
                "id": "26QPDBe-NB8",
                "titulo": "Operating Systems – Evolution & Architecture",
                "canal": "CrashCourse (Carrie Anne Philbin)",
                "categoria": "arquitectura_so",
                "playlist": "PL1mtdjDVOoOqJzeaJAV15Tq0tZ1vKj7ZV",
                "duracion": "13:00",
                "nivel": "Principiante",
                "idioma": "en",
                "descripcion": "La arquitectura de los sistemas operativos: el kernel como intermediario entre hardware y software, multiprocesamiento, controladores de dispositivos y sistemas de archivos."
        },
        {
                "id": "yK1uBHPdp30",
                "titulo": "Operating Systems Course for Beginners",
                "canal": "freeCodeCamp.org",
                "categoria": "arquitectura_so",
                "duracion": "24:51:56",
                "nivel": "Principiante",
                "idioma": "en",
                "descripcion": "Fundamentos de sistemas operativos para programadores: espacio de usuario vs espacio de kernel, llamadas al sistema (syscalls), controladores, memoria compartida y seguridad de procesos."
        },
        {
                "id": "ROjZy1WbCIA",
                "titulo": "Linux Operating System – Crash Course for Beginners",
                "canal": "freeCodeCamp.org",
                "categoria": "arquitectura_so",
                "duracion": "2:47:56",
                "nivel": "Principiante",
                "idioma": "en",
                "descripcion": "El sistema operativo Linux a fondo: arquitectura del kernel Linux, jerarquía de archivos FHS, permisos POSIX, gestión de procesos en segundo plano y comandos del sistema."
        },
        {
                "id": "gfmRrPjnEw4",
                "titulo": "Assembly Language Programming with ARM",
                "canal": "freeCodeCamp.org",
                "categoria": "arquitectura_so",
                "duracion": "2:29:32",
                "nivel": "Intermedio",
                "idioma": "en",
                "descripcion": "Programación en lenguaje ensamblador de bajo nivel para arquitectura ARM: registros de CPU, instrucciones de carga y almacenamiento (load/store), saltos condicionales y manejo de la pila."
        },
        {
                "id": "fsuroRYmagw",
                "titulo": "¿Cómo Funciona un Sistema Operativo por Dentro?",
                "canal": "BettaTech",
                "categoria": "arquitectura_so",
                "duracion": "8:37",
                "nivel": "Principiante / Intermedio",
                "idioma": "es",
                "descripcion": "Explicación técnica y didáctica en español: qué sucede desde que enciendes el ordenador hasta que carga el kernel, cómo interactúan la BIOS/UEFI, los drivers, la CPU y la memoria RAM."
        }
];

    const CATEGORIAS = [
        { id: 'todas', label: 'Todos los cursos' },
        { id: 'universidades', label: '🎓 Universidades (MIT, Stanford, etc.)' },
        { id: 'arquitectura_so', label: '💻 Arquitectura & Sistemas Operativos' },
        { id: 'matematicas', label: '📐 Matemáticas (Álgebra, Cálculo, Probabilidad)' },
        { id: 'python', label: 'Python' },
        { id: 'cpp', label: 'C++ Moderno' },
        { id: 'ml', label: 'Machine Learning' },
        { id: 'dl', label: 'Deep Learning' },
        { id: 'algoritmos', label: 'Algoritmos y Estructuras' },
        { id: 'system_design', label: 'System Design' }
    ];

    // Palabras registradas para el motor de búsqueda en tiempo real
    const PALABRAS_REGISTRADAS_DEF = [
        {
            slug: 'deep_learning',
            palabra: 'Deep Learning',
            emoji: '🧠',
            color: '#8b5cf6',
            desc: 'Redes neuronales, PyTorch, Transformers, LLMs y visión artificial',
            tags: ['Deep Learning', 'PyTorch', 'Transformers', 'IA', 'Redes Neuronales']
        },
        {
            slug: 'machine_learning',
            palabra: 'Machine Learning',
            emoji: '🤖',
            color: '#3b82f6',
            desc: 'Modelos predictivos, Scikit-Learn, algoritmos y estadística aplicada',
            tags: ['Machine Learning', 'Scikit-Learn', 'Data Science', 'Python', 'Algoritmos']
        },
        {
            slug: 'python',
            palabra: 'Python',
            emoji: '🐍',
            color: '#10b981',
            desc: 'Fundamentos, POO, scripts, backend y proyectos completos paso a paso',
            tags: ['Python', 'Programación', 'POO', 'Backend', 'Principiantes']
        },
        {
            slug: 'cpp',
            palabra: 'C++',
            emoji: '⚡',
            color: '#f59e0b',
            desc: 'C++ moderno (C++17/20), punteros, STL, algoritmos y sistemas de alto rendimiento',
            tags: ['C++', 'Sistemas', 'Estructuras de Datos', 'Algoritmos', 'Modern C++']
        }
    ];

    function leerCursosPersonalizados() {
        try {
            const raw = localStorage.getItem('prig_yt_cursos_personalizados');
            return raw ? JSON.parse(raw) : [];
        } catch (e) {
            return [];
        }
    }

    function guardarCursoEnCatalogo(video) {
        if (!video || !video.id) return false;
        const custom = leerCursosPersonalizados();
        const existe = custom.some(c => c.id === video.id);
        if (!existe) {
            const nuevo = {
                id: video.id,
                titulo: video.titulo || 'Video de YouTube',
                canal: video.canal || 'YouTube',
                duracion: video.duracion || 'Video',
                descripcion: video.descripcion || '',
                miniatura: video.miniatura || '',
                playlist: video.playlist || (video.es_playlist ? video.id : ''),
                categoria: 'personalizado',
                nivel: video.es_playlist ? 'Playlist / Curso' : 'Curso YouTube',
                idioma: 'AUTO',
                esPersonalizado: true
            };
            custom.unshift(nuevo);
            try {
                localStorage.setItem('prig_yt_cursos_personalizados', JSON.stringify(custom));
            } catch (e) { console.error('Error guardando curso personalizado:', e); }
            if (!VIDEOS_CURADOS.some(v => v.id === nuevo.id)) {
                VIDEOS_CURADOS.unshift(nuevo);
            }
            return true;
        }
        return false;
    }

    function inicializarCursosPersonalizados() {
        const guardados = leerCursosPersonalizados();
        guardados.forEach(c => {
            if (!VIDEOS_CURADOS.some(v => v.id === c.id)) {
                VIDEOS_CURADOS.unshift(c);
            }
        });
    }

    // Historial de Búsquedas Recientes
    function leerHistorialBusquedas() {
        try {
            const raw = localStorage.getItem('prig_yt_historial_busquedas');
            return raw ? JSON.parse(raw) : [];
        } catch (e) {
            return [];
        }
    }

    function agregarAHistorial(termino) {
        if (!termino || !termino.trim()) return;
        const q = termino.trim();
        let lista = leerHistorialBusquedas().filter(item => item.toLowerCase() !== q.toLowerCase());
        lista.unshift(q);
        lista = lista.slice(0, 6);
        try {
            localStorage.setItem('prig_yt_historial_busquedas', JSON.stringify(lista));
        } catch (e) { }
    }

    function limpiarHistorialBusquedas() {
        try {
            localStorage.removeItem('prig_yt_historial_busquedas');
        } catch (e) { }
    }

    const estado = {
        vista: 'catalogo', // 'catalogo' | 'reproductor'
        modoCatalogo: 'catalogo', // 'catalogo' | 'busqueda_yt'
        filtroCategoria: 'todas',
        filtroProgreso: 'todos', // 'todos' | 'en_progreso' | 'completados' | 'sin_iniciar'
        busqueda: '',
        ocultarTexto: localStorage.getItem('prig_yt_ocultar_texto') === 'true',
        ocultarTextoPlayer: localStorage.getItem('prig_yt_ocultar_texto_player') === 'true',
        videoActual: null,
        pestanaLateral: 'traduccion', // 'traduccion' | 'notas' | 'objetivos' | 'resumen' | 'tutor'
        subpestanaNotas: 'fotogramas', // 'fotogramas' | 'marcas' | 'cuaderno'
        subpestanaTraduccion: 'transcripcion', // 'transcripcion' | 'guardadas'
        idiomaSubtitulos: localStorage.getItem('prig_yt_sub_lang') || 'es', // 'es' | 'en' | 'none'
        modoVistaTraduccion: 'traduccion', // 'traduccion' | 'bilingue'
        filtroTextoTraduccion: '',
        transcripcion: { cargando: false, error: null, datos: null, videoId: null, idioma: 'es' },
        fotogramaFormAbierto: false,
        fotogramaTemporal: null,
        lightboxImg: null,
        explicacionFotogramaCargando: false,
        explicacionFotogramaError: null,
        chatTutor: [],
        tutorCargando: false,
        analisisCargando: false,
        analisisMensaje: '',
        desafioCreando: false,
        desafioMensaje: '',
        mostrarInputTextoExtra: false,
        textoExtra: '',

        // Motor de búsqueda YouTube en tiempo real & Facetas
        palabraRegistradaActiva: null, // 'deep_learning' | 'machine_learning' | 'python' | 'cpp' | null
        resultadosBusquedaYt: [],
        infoPalabraRegistrada: null,
        busquedaYtCargando: false,
        busquedaYtError: null,
        filtroTipoYt: 'todos', // 'todos' | 'video' | 'playlist'
        filtroIdiomaYt: 'todos', // 'todos' | 'es' | 'en'
        filtroDuracionYt: 'todas', // 'todas' | 'cortos' | 'clases' | 'cursos' | 'playlists'
        ordenYt: 'educativo', // 'educativo' | 'duracion' | 'vistas'
        sugerenciasActivas: [],
        sugerenciasAbiertas: false,
        servidorEmbed: localStorage.getItem('prig_yt_embed_server') || 'www.youtube.com' // 'www.youtube.com' | 'www.youtube-nocookie.com'
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

    // ==================== GESTIÓN DE FOTOGRAMAS Y NOTAS VISUALES ====================
    function leerFotogramas(videoId) {
        try {
            const raw = localStorage.getItem(`prig_yt_fotogramas_${videoId}`);
            const arr = raw ? JSON.parse(raw) : [];
            return Array.isArray(arr) ? arr : [];
        } catch (e) {
            return [];
        }
    }

    function sincronizarIndiceFotogramas(videoId, fotogramas) {
        try {
            const raw = localStorage.getItem('prig_yt_indice_fotogramas');
            const indice = raw ? JSON.parse(raw) : {};
            const video = VIDEOS_CURADOS.find(v => v.id === videoId) || (estado.videoActual && estado.videoActual.id === videoId ? estado.videoActual : { id: videoId, titulo: 'Video de YouTube' });
            Object.keys(indice).forEach(k => {
                if (indice[k] && indice[k].videoId === videoId) delete indice[k];
            });
            (fotogramas || []).forEach(f => {
                indice[f.id] = {
                    id: f.id,
                    videoId: videoId,
                    videoTitulo: video.titulo || 'Video de YouTube',
                    canal: video.canal || 'YouTube',
                    minuto: f.minuto,
                    segundos: f.segundos,
                    titulo: f.titulo || 'Nota visual',
                    explicacion: f.explicacion || '',
                    imagenUrl: f.imagenUrl || (videoId && !String(videoId).startsWith('pl_') ? `https://i.ytimg.com/vi/${videoId}/0.jpg` : ''),
                    fecha: f.fecha || Date.now()
                };
            });
            localStorage.setItem('prig_yt_indice_fotogramas', JSON.stringify(indice));
        } catch (e) {
            console.error('Error sincronizando índice de fotogramas:', e);
        }
    }

    function guardarFotogramas(videoId, fotogramas) {
        try {
            localStorage.setItem(`prig_yt_fotogramas_${videoId}`, JSON.stringify(fotogramas));
            sincronizarIndiceFotogramas(videoId, fotogramas);
        } catch (e) {
            console.error('Error guardando fotogramas:', e);
        }
    }

    function generarSvgPoster(videoId, playlistId, titulo = '') {
        const esPlaylist = Boolean(playlistId && (!videoId || String(videoId).startsWith('pl_')));
        const cleanTitle = (titulo || (esPlaylist ? 'Playlist de YouTube' : 'Video de YouTube'))
            .replace(/[<>&"']/g, '')
            .slice(0, 48);
        const sub = esPlaylist ? 'Lista de reproducción' : 'Clase Magistral Prig';
        const color1 = esPlaylist ? '#cba6f7' : '#ff4444';
        const color2 = esPlaylist ? '#89b4fa' : '#b31b1b';
        const icono = esPlaylist
            ? '<path d="M4 6h16M4 12h16M4 18h10" stroke="white" stroke-width="2.2" stroke-linecap="round"/>'
            : '<polygon points="8,5 19,12 8,19" fill="white"/>';

        const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 480 270" width="100%" height="100%">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="#14141e"/>
      <stop offset="100%" stop-color="#1e1e2e"/>
    </linearGradient>
    <linearGradient id="acc" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="${color1}"/>
      <stop offset="100%" stop-color="${color2}"/>
    </linearGradient>
  </defs>
  <rect width="480" height="270" fill="url(#bg)"/>
  <circle cx="430" cy="50" r="90" fill="url(#acc)" opacity="0.08"/>
  <circle cx="50" cy="220" r="110" fill="url(#acc)" opacity="0.06"/>
  <g transform="translate(240, 105)">
    <rect x="-36" y="-26" width="72" height="52" rx="14" fill="url(#acc)"/>
    <g transform="translate(-12, -12)">${icono}</g>
  </g>
  <text x="240" y="172" fill="#ffffff" font-family="-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,sans-serif" font-size="14.5" font-weight="700" text-anchor="middle">${cleanTitle}</text>
  <text x="240" y="196" fill="#a6adc8" font-family="-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,sans-serif" font-size="11.5" text-anchor="middle">${sub}</text>
</svg>`;
        return 'data:image/svg+xml;utf8,' + encodeURIComponent(svg);
    }

    function resolverVideoIdDePlaylist(playlistId) {
        if (!playlistId) return null;
        const encontrado = VIDEOS_CURADOS.find(c => c.playlist === playlistId && c.id && !c.id.startsWith('pl_'));
        return encontrado ? encontrado.id : null;
    }

    function generarUrlMiniatura(videoId, playlistId) {
        if (videoId && !String(videoId).startsWith('pl_')) {
            return `https://i.ytimg.com/vi/${videoId}/hqdefault.jpg`;
        }
        if (playlistId) {
            const vid = resolverVideoIdDePlaylist(playlistId);
            if (vid) return `https://i.ytimg.com/vi/${vid}/hqdefault.jpg`;
            return generarSvgPoster(videoId, playlistId, 'Playlist');
        }
        return generarSvgPoster(videoId, playlistId, 'Video');
    }

    window.prigYtImgFallback = function (img, videoId, playlistId, titulo) {
        if (!img) return;
        const src = img.src || '';
        const vid = (videoId && !String(videoId).startsWith('pl_')) ? videoId : resolverVideoIdDePlaylist(playlistId);

        if (vid && src.includes('hqdefault.jpg')) {
            img.src = `https://i.ytimg.com/vi/${vid}/mqdefault.jpg`;
        } else if (vid && (src.includes('mqdefault.jpg') || src.includes('maxresdefault.jpg'))) {
            // El fotograma inicial (0.jpg) de YouTube
            img.src = `https://i.ytimg.com/vi/${vid}/0.jpg`;
        } else {
            img.onerror = null;
            img.src = generarSvgPoster(videoId, playlistId, titulo || img.alt || '');
        }
    };

    function obtenerKeyframeUrl(videoId, opcion = 'hqdefault') {
        if (!videoId) return '';
        if (String(videoId).startsWith('pl_')) return generarSvgPoster(videoId, '', 'Playlist');
        return `https://img.youtube.com/vi/${videoId}/${opcion}.jpg`;
    }

    function obtenerTodasLasNotas() {
        const resultado = [];
        try {
            const rawIdx = localStorage.getItem('prig_yt_indice_fotogramas');
            if (rawIdx) {
                const idx = JSON.parse(rawIdx);
                Object.values(idx).forEach(f => {
                    resultado.push({
                        tipo: 'fotograma',
                        id: f.id,
                        videoId: f.videoId,
                        videoTitulo: f.videoTitulo,
                        canal: f.canal || 'YouTube',
                        minuto: f.minuto,
                        segundos: f.segundos,
                        titulo: f.titulo,
                        texto: f.explicacion,
                        imagenUrl: f.imagenUrl,
                        fecha: f.fecha
                    });
                });
            }
        } catch (e) { /* continuar */ }

        try {
            for (let i = 0; i < localStorage.length; i++) {
                const key = localStorage.key(i);
                if (key && key.startsWith('prig_yt_marcas_')) {
                    const videoId = key.replace('prig_yt_marcas_', '');
                    const raw = localStorage.getItem(key);
                    const marcas = raw ? JSON.parse(raw) : [];
                    const vid = VIDEOS_CURADOS.find(v => v.id === videoId) || { id: videoId, titulo: 'Video de YouTube', canal: 'YouTube' };
                    if (Array.isArray(marcas)) {
                        marcas.forEach(m => {
                            resultado.push({
                                tipo: 'marca',
                                id: m.id || `${videoId}_${m.segundos}`,
                                videoId: videoId,
                                videoTitulo: vid.titulo,
                                canal: vid.canal || 'YouTube',
                                minuto: m.minuto,
                                segundos: m.segundos,
                                titulo: `Marca en ${m.minuto}`,
                                texto: m.texto,
                                imagenUrl: obtenerKeyframeUrl(videoId, 'hqdefault'),
                                fecha: m.fecha || null
                            });
                        });
                    }
                }
            }
        } catch (e) { /* continuar */ }

        try {
            for (let i = 0; i < localStorage.length; i++) {
                const key = localStorage.key(i);
                if (key && key.startsWith('prig_yt_nota_')) {
                    const videoId = key.replace('prig_yt_nota_', '');
                    const texto = localStorage.getItem(key);
                    if (texto && texto.trim()) {
                        const vid = VIDEOS_CURADOS.find(v => v.id === videoId) || { id: videoId, titulo: 'Video de YouTube', canal: 'YouTube' };
                        resultado.push({
                            tipo: 'cuaderno',
                            id: `cuaderno_${videoId}`,
                            videoId: videoId,
                            videoTitulo: vid.titulo,
                            canal: vid.canal || 'YouTube',
                            minuto: '00:00',
                            segundos: 0,
                            titulo: `Apuntes de ${vid.titulo}`,
                            texto: texto.slice(0, 280),
                            imagenUrl: obtenerKeyframeUrl(videoId, 'hqdefault'),
                            fecha: null
                        });
                    }
                }
            }
        } catch (e) { /* continuar */ }

        return resultado.sort((a, b) => (b.fecha || 0) - (a.fecha || 0));
    }

    async function solicitarExplicacionFotograma(minuto, titulo, notaActual) {
        const v = estado.videoActual;
        if (!v) return;
        estado.explicacionFotogramaCargando = true;
        estado.explicacionFotogramaError = null;
        pintar();

        const prompt = `Estoy estudiando la clase de programación/ML: "${v.titulo}" (${v.canal || 'YouTube'}).\n` +
            `Timestamp del fotograma: ${minuto || '00:00'}.\n` +
            `Concepto / Diapositiva: "${titulo || 'Tema principal de este momento'}".\n` +
            (notaActual ? `Notas previas del estudiante: "${notaActual}".\n` : '') +
            `Por favor, genera una explicación técnica, concisa y didáctica (en español):\n` +
            `1. Explica los fundamentos teóricos o prácticos que se muestran en este punto.\n` +
            `2. Si involucra fórmulas o matemáticas, represéntalas en notación clara o LaTeX.\n` +
            `3. Si involucra código o arquitectura, proporciona un snippet breve y limpio.\n` +
            `4. Concluye con un tip práctico de optimización o advertencia.`;

        try {
            const resp = await window.prigFetchJson('/api/ai/chat', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    messages: [
                        { role: 'system', content: 'Eres un profesor universitario de ciencias de la computación, arquitectura de sistemas y machine learning. Explicas diapositivas y fotogramas técnicos con máxima claridad.' },
                        { role: 'user', content: prompt }
                    ],
                    tutor: 'modelo_explicar',
                    stream: false
                })
            });

            const textoGen = (resp && (resp.response || resp.texto || resp.message || resp.content)) || '';
            if (estado.fotogramaTemporal) {
                const prev = (estado.fotogramaTemporal.explicacion || '').trim();
                estado.fotogramaTemporal.explicacion = prev ? `${prev}\n\n${textoGen.trim()}` : textoGen.trim();
            }
        } catch (e) {
            console.error('Error generando explicación con IA:', e);
            estado.explicacionFotogramaError = e.message;
        } finally {
            estado.explicacionFotogramaCargando = false;
            pintar();
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

    // ==================== GESTIÓN DE EXPLICACIONES GUARDADAS Y TRANSCRIPCIÓN ====================
    function leerExplicaciones(videoId) {
        if (!videoId) return [];
        try {
            const raw = localStorage.getItem(`prig_yt_explicaciones_${videoId}`);
            const arr = raw ? JSON.parse(raw) : [];
            return Array.isArray(arr) ? arr : [];
        } catch (e) {
            return [];
        }
    }

    function guardarExplicaciones(videoId, lista) {
        if (!videoId) return;
        try {
            localStorage.setItem(`prig_yt_explicaciones_${videoId}`, JSON.stringify(lista || []));
        } catch (e) {
            console.error('Error guardando explicaciones:', e);
        }
    }

    function agregarExplicacionGuardada(videoId, explicacion) {
        if (!videoId || !explicacion || !explicacion.texto) return null;
        const lista = leerExplicaciones(videoId);
        const nueva = {
            id: 'exp_' + Date.now() + '_' + Math.random().toString(36).substr(2, 4),
            videoId: videoId,
            texto: explicacion.texto.trim(),
            intervalo: explicacion.intervalo || '00:00',
            startSegundos: Math.max(0, Math.floor(Number(explicacion.startSegundos) || 0)),
            endSegundos: Math.max(0, Math.floor(Number(explicacion.endSegundos) || 0)),
            fecha: new Date().toLocaleDateString() + ' ' + new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
            color: 'amarillo'
        };
        lista.unshift(nueva);
        guardarExplicaciones(videoId, lista);
        return nueva;
    }

    function eliminarExplicacionGuardada(videoId, id) {
        if (!videoId || !id) return;
        let lista = leerExplicaciones(videoId).filter(item => item.id !== id);
        guardarExplicaciones(videoId, lista);
    }

    async function cargarTranscripcion(videoId, idioma = 'es') {
        if (!videoId) return;
        if (estado.transcripcion.videoId === videoId &&
            estado.transcripcion.idioma === idioma &&
            estado.transcripcion.datos) {
            return;
        }

        estado.transcripcion = {
            cargando: true,
            error: null,
            datos: null,
            videoId: videoId,
            idioma: idioma
        };
        pintar();

        try {
            const resp = await fetch(`/api/youtube/transcripcion?video_id=${encodeURIComponent(videoId)}&idioma=${encodeURIComponent(idioma)}`);
            const data = await resp.json();
            if (data.ok && data.segmentos) {
                estado.transcripcion = {
                    cargando: false,
                    error: null,
                    datos: data,
                    videoId: videoId,
                    idioma: idioma
                };
            } else {
                estado.transcripcion = {
                    cargando: false,
                    error: data.error || 'No se pudieron extraer subtítulos para este video.',
                    datos: null,
                    videoId: videoId,
                    idioma: idioma
                };
            }
        } catch (e) {
            estado.transcripcion = {
                cargando: false,
                error: 'Error conectando con el servicio de transcripción: ' + (e.message || e),
                datos: null,
                videoId: videoId,
                idioma: idioma
            };
        }
        pintar();
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

    function obtenerServidorEmbed() {
        return estado.servidorEmbed || localStorage.getItem('prig_yt_embed_server') || 'www.youtube.com';
    }

    function construirEmbedUrl(video, startSegundos = 0, idiomaSub = null) {
        if (!video) return '';
        const servidor = obtenerServidorEmbed();
        const esSoloPlaylist = String(video.id || '').startsWith('pl_') || (!video.id && video.playlist);
        const originParam = window.location && window.location.origin ? `&origin=${encodeURIComponent(window.location.origin)}` : '';

        const idioma = idiomaSub !== null ? idiomaSub : (estado.idiomaSubtitulos || 'es');
        const ccParam = (idioma && idioma !== 'none') ? `&cc_load_policy=1&cc_lang_pref=${idioma}&hl=${idioma}` : '';

        if (esSoloPlaylist) {
            return `https://${servidor}/embed/videoseries?list=${encodeURIComponent(video.playlist)}&autoplay=1${ccParam}${originParam}`;
        }

        const startParam = Number(startSegundos) > 0 ? `&start=${Math.floor(startSegundos)}` : '';
        return `https://${servidor}/embed/${encodeURIComponent(video.id)}?enablejsapi=1&autoplay=1&rel=0${ccParam}${startParam}${originParam}`;
    }

    async function abrirEnNavegadorExterno(url) {
        if (!url) return;
        try {
            const resp = await fetch('/api/youtube/abrir_externo', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ url: url })
            });
            if (resp.ok) {
                const data = await resp.json();
                if (data && data.ok) {
                    return true;
                }
            }
        } catch (e) {
            console.warn('[YouTubeHub] Falló apertura por backend:', e);
        }
        window.open(url, '_blank', 'noopener,noreferrer');
        return true;
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
            const nuevaSrc = construirEmbedUrl(v, segundos);
            if (forzarRecarga) {
                iframe.src = nuevaSrc;
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
                    iframe.src = nuevaSrc;
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

    function extraerPlaylistId(cadena) {
        if (!cadena) return null;
        const texto = cadena.trim();
        if (/^PL[a-zA-Z0-9_-]{16,40}$/.test(texto)) return texto;
        const m = texto.match(/[?&]list=([a-zA-Z0-9_-]+)/i);
        return m ? m[1] : null;
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
            const modeloActivo = (window.aiChatMgr && window.aiChatMgr.modelSelect && window.aiChatMgr.modelSelect.value) ? window.aiChatMgr.modelSelect.value : undefined;
            const r = await window.prigFetchJson('/api/youtube/analizar', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
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
                    modo: modo,
                    modelo: modeloActivo
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

            /* Selector de Modos (Catálogo Curado vs Buscador YouTube) */
            .yt-modo-selector { display:flex; gap:4px; background:rgba(0,0,0,0.35); padding:3px; border-radius:8px; border:1px solid rgba(255,255,255,0.08); flex-shrink:0; }
            .yt-modo-tab { display:inline-flex; align-items:center; gap:6px; padding:4px 11px; border-radius:6px; font-size:11px; font-weight:700; color:var(--text-muted, #a6adc8); background:transparent; border:none; cursor:pointer; transition:all 0.15s; }
            .yt-modo-tab:hover { color:#fff; background:rgba(255,255,255,0.08); }
            .yt-modo-tab.activo { background:#ff0000; color:#fff; box-shadow:0 2px 8px rgba(255,0,0,0.35); }

            /* Barra de Palabras Registradas */
            .yt-palabras-barra { display:flex; align-items:center; gap:8px; padding:7px 16px; background:rgba(0,0,0,0.25); border-bottom:1px solid rgba(255,255,255,0.06); flex-wrap:wrap; flex-shrink:0; }
            .yt-palabras-label { font-size:10.5px; font-weight:700; color:var(--text-muted, #a6adc8); display:flex; align-items:center; gap:5px; text-transform:uppercase; letter-spacing:0.4px; }
            .yt-palabras-items { display:flex; gap:6px; flex-wrap:wrap; }
            .yt-pill-palabra { display:inline-flex; align-items:center; gap:5px; padding:4px 11px; border-radius:16px; font-size:11px; font-weight:700; cursor:pointer; background:rgba(255,255,255,0.05); color:#cdd6f4; border:1px solid rgba(255,255,255,0.1); transition:all 0.2s cubic-bezier(0.4, 0, 0.2, 1); user-select:none; }
            .yt-pill-palabra:hover { transform:translateY(-1px); box-shadow:0 3px 10px rgba(0,0,0,0.3); border-color:rgba(255,255,255,0.25); color:#fff; }
            .yt-pill-palabra.deep_learning:hover, .yt-pill-palabra.deep_learning.activa { background:rgba(139,92,246,0.25); border-color:#8b5cf6; color:#c4b5fd; box-shadow:0 0 12px rgba(139,92,246,0.35); }
            .yt-pill-palabra.machine_learning:hover, .yt-pill-palabra.machine_learning.activa { background:rgba(59,130,246,0.25); border-color:#3b82f6; color:#93c5fd; box-shadow:0 0 12px rgba(59,130,246,0.35); }
            .yt-pill-palabra.python:hover, .yt-pill-palabra.python.activa { background:rgba(16,185,129,0.25); border-color:#10b981; color:#6ee7b7; box-shadow:0 0 12px rgba(16,185,129,0.35); }
            .yt-pill-palabra.cpp:hover, .yt-pill-palabra.cpp.activa { background:rgba(245,158,11,0.25); border-color:#f59e0b; color:#fcd34d; box-shadow:0 0 12px rgba(245,158,11,0.35); }

            /* Banner de Palabra Registrada Activa */
            .yt-banner-palabra { display:flex; align-items:center; justify-content:space-between; gap:12px; padding:10px 14px; border-radius:8px; margin-bottom:14px; background:rgba(255,255,255,0.035); border:1px solid rgba(255,255,255,0.1); flex-wrap:wrap; }
            .yt-banner-palabra-info { display:flex; align-items:center; gap:10px; }
            .yt-banner-palabra-icono { font-size:24px; }
            .yt-banner-palabra-titulo { font-size:13px; font-weight:700; color:#fff; margin:0 0 2px; }
            .yt-banner-palabra-desc { font-size:11px; color:var(--text-muted, #a6adc8); margin:0; }
            .yt-banner-tags { display:flex; gap:4px; flex-wrap:wrap; }
            .yt-banner-tag { font-size:9.5px; padding:2px 6px; border-radius:4px; background:rgba(255,255,255,0.08); color:var(--text-muted, #a6adc8); }

            /* Tarjetas de búsqueda en tiempo real */
            .yt-tarjeta.es-busqueda-live { border-color:rgba(255,255,255,0.12); }
            .yt-tarjeta.es-busqueda-live:hover { border-color:rgba(255,0,0,0.5); }
            .yt-btn-guardar-catalogo { background:rgba(255,255,255,0.06); border:1px solid rgba(255,255,255,0.12); color:#cdd6f4; border-radius:5px; padding:3px 8px; font-size:10.5px; font-weight:600; cursor:pointer; transition:all 0.15s; display:inline-flex; align-items:center; gap:4px; }
            .yt-btn-guardar-catalogo:hover { background:rgba(16,185,129,0.25); color:#10b981; border-color:#10b981; }
            .yt-btn-guardar-catalogo.guardado { background:rgba(16,185,129,0.2); color:#10b981; border-color:rgba(16,185,129,0.4); cursor:default; }
            .yt-tag-live { font-size:9px; font-weight:700; color:#ff5555; background:rgba(255,0,0,0.18); border:1px solid rgba(255,0,0,0.35); border-radius:4px; padding:1px 5px; text-transform:uppercase; letter-spacing:0.3px; }
            .yt-badge-search-count { font-size:11px; font-weight:700; color:#89b4fa; background:rgba(137,180,250,0.15); border:1px solid rgba(137,180,250,0.3); border-radius:12px; padding:2px 8px; }
            .yt-search-select { background:var(--bg-dark, #11111b); border:1px solid var(--border-color, rgba(255,255,255,0.14)); border-radius:7px; padding:5px 8px; color:#fff; font-size:11.5px; outline:none; }
            .yt-search-select:focus { border-color:#ff0000; }

            /* Contenedor con Autocompletado Flotante */
            .yt-search-container { position:relative; flex:1; min-width:220px; max-width:540px; display:flex; align-items:center; }
            .yt-search-container .yt-campo-buscar { width:100%; max-width:100%; }
            .yt-sugerencias-dropdown { position:absolute; top:calc(100% + 5px); left:0; right:0; background:var(--bg-panel, #181825); border:1px solid var(--border-color, rgba(255,255,255,0.18)); border-radius:8px; box-shadow:0 10px 28px rgba(0,0,0,0.65); z-index:99999; max-height:260px; overflow-y:auto; display:flex; flex-direction:column; padding:4px 0; backdrop-filter:blur(6px); }
            .yt-sug-item { display:flex; align-items:center; gap:9px; padding:8px 12px; font-size:11.5px; color:#cdd6f4; cursor:pointer; transition:background 0.12s; }
            .yt-sug-item:hover, .yt-sug-item.activo { background:rgba(255,255,255,0.09); color:#fff; }
            .yt-sug-item i { color:var(--text-muted, #a6adc8); font-size:10px; }

            /* Barra de Facetas y Filtros Avanzados */
            .yt-facetas-barra { display:flex; align-items:center; justify-content:space-between; gap:10px; padding:7px 16px; background:rgba(0,0,0,0.18); border-bottom:1px solid rgba(255,255,255,0.06); flex-wrap:wrap; font-size:11px; flex-shrink:0; }
            .yt-facetas-grupo { display:flex; align-items:center; gap:6px; flex-wrap:wrap; }
            .yt-faceta-label { font-size:10.5px; font-weight:700; color:var(--text-muted, #a6adc8); display:inline-flex; align-items:center; gap:4px; }
            .yt-faceta-select { background:var(--bg-dark, #11111b); border:1px solid var(--border-color, rgba(255,255,255,0.12)); border-radius:6px; padding:4px 8px; color:#cdd6f4; font-size:11px; outline:none; }
            .yt-faceta-select:focus { border-color:#ff0000; }
            
            /* Historial de búsquedas recientes */
            .yt-historial-barra { display:flex; align-items:center; gap:6px; flex-wrap:wrap; }
            .yt-chip-historial { display:inline-flex; align-items:center; gap:4px; font-size:10px; background:rgba(255,255,255,0.04); border:1px solid rgba(255,255,255,0.08); border-radius:12px; padding:2px 8px; color:var(--text-muted, #a6adc8); cursor:pointer; transition:all 0.15s; }
            .yt-chip-historial:hover { background:rgba(255,255,255,0.1); color:#fff; }

            /* Badge de Canal de Autoridad Educativa */
            .yt-badge-canal-top { display:inline-flex; align-items:center; gap:3px; font-size:9.5px; font-weight:700; color:#a6e3a1; background:rgba(166,227,161,0.14); border:1px solid rgba(166,227,161,0.3); border-radius:4px; padding:1px 5px; }

            /* Sección de Búsqueda Federada Híbrida */
            .yt-seccion-separador { display:flex; align-items:center; justify-content:space-between; margin:16px 0 10px; padding-bottom:6px; border-bottom:1px solid rgba(255,255,255,0.08); flex-wrap:wrap; gap:8px; }
            .yt-seccion-titulo { font-size:12.5px; font-weight:700; color:#fff; display:flex; align-items:center; gap:6px; margin:0; }

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
            .yt-miniatura { position:relative; width:100%; aspect-ratio:16/9; background:#11111b; overflow:hidden; display:flex; align-items:center; justify-content:center; }
            .yt-miniatura img { width:100%; height:100%; object-fit:cover; display:block; }
            .yt-miniatura-playlist-badge { position:absolute; top:6px; left:6px; background:rgba(203,166,247,0.95); color:#111; font-size:9.5px; padding:2px 6px; border-radius:4px; font-weight:700; z-index:2; display:flex; align-items:center; gap:4px; box-shadow:0 2px 6px rgba(0,0,0,0.4); }
            .yt-playlist-stack { position:absolute; top:0; right:0; bottom:0; width:34px; background:rgba(0,0,0,0.65); backdrop-filter:blur(3px); display:flex; flex-direction:column; align-items:center; justify-content:center; gap:3px; border-left:1px solid rgba(255,255,255,0.15); z-index:2; color:#fff; font-size:10px; font-weight:700; }
            .yt-playlist-stack i { font-size:12px; color:var(--accent-purple, #cba6f7); }
            .yt-duracion { position:absolute; bottom:6px; right:6px; background:rgba(0,0,0,0.82); color:#fff; font-size:10px; padding:2px 5px; border-radius:4px; font-weight:600; z-index:2; }
            .yt-tarjeta.es-playlist .yt-duracion { right:38px; }
            .yt-nivel { position:absolute; top:6px; left:6px; background:rgba(203,166,247,0.9); color:#111; font-size:9.5px; padding:2px 6px; border-radius:4px; font-weight:700; z-index:2; }
            .yt-idioma { position:absolute; top:6px; right:6px; background:rgba(0,0,0,0.75); color:#fff; font-size:9.5px; padding:2px 5px; border-radius:4px; font-weight:700; text-transform:uppercase; border:1px solid rgba(255,255,255,0.15); z-index:2; }
            .yt-tarjeta.es-playlist .yt-idioma { right:38px; }
            
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
            .yt-tag-uni { display:inline-flex; align-items:center; gap:4px; font-size:9.5px; font-weight:700; color:#a6e3a1; background:rgba(166,227,161,0.12); border:1px solid rgba(166,227,161,0.3); border-radius:4px; padding:1px 6px; }
            .yt-tag-playlist { display:inline-flex; align-items:center; gap:4px; font-size:9.5px; font-weight:700; color:#89b4fa; background:rgba(137,180,250,0.12); border:1px solid rgba(137,180,250,0.3); border-radius:4px; padding:1px 6px; text-decoration:none; transition:all 0.15s; }
            .yt-tag-playlist:hover { background:rgba(137,180,250,0.25); color:#cdd6f4; border-color:#89b4fa; }
            .yt-tarjeta-titulo { font-size:12px; font-weight:600; color:#fff; line-height:1.35; margin:0; display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; overflow:hidden; }
            .yt-tarjeta-canal { font-size:11px; color:var(--text-muted, #a6adc8); }
            .yt-tarjeta-desc { font-size:10.5px; color:var(--text-muted, #9399b2); line-height:1.35; margin:0; display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; overflow:hidden; }
            .yt-modo-compacto .yt-tarjeta-desc { display:none !important; }

            /* Reproductor */
            .yt-player-layout { display:grid; grid-template-columns:1fr 390px; height:100%; min-height:0; overflow:hidden; }
            @media (max-width: 950px) { .yt-player-layout { grid-template-columns:1fr; grid-template-rows:1fr 1fr; } }
            .yt-player-main { display:flex; flex-direction:column; height:100%; min-height:0; overflow-y:auto; padding:16px; gap:12px; }
            .yt-player-aux-bar { display:flex; align-items:center; justify-content:space-between; gap:8px; padding:6px 10px; background:rgba(0,0,0,0.35); border:1px solid rgba(255,255,255,0.08); border-radius:8px; flex-shrink:0; font-size:11px; flex-wrap:wrap; }
            .yt-player-aux-left { display:flex; align-items:center; gap:8px; }
            .yt-player-aux-right { display:flex; align-items:center; gap:6px; flex-wrap:wrap; }
            .yt-aviso-embed { display:flex; align-items:flex-start; gap:8px; padding:8px 12px; background:rgba(137,180,250,0.08); border:1px solid rgba(137,180,250,0.22); border-radius:8px; font-size:11px; color:#cdd6f4; line-height:1.45; }
            .yt-aviso-embed i { color:#89b4fa; font-size:13px; margin-top:2px; flex-shrink:0; }
            .yt-btn-link { background:transparent; border:none; color:#89b4fa; text-decoration:underline; cursor:pointer; padding:0; font-size:inherit; font-weight:600; }
            .yt-btn-link:hover { color:#b4befe; }
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

            /* Subpestañas en Notas */
            .yt-subtabs-notas { display:flex; gap:4px; border-bottom:1px solid rgba(255,255,255,0.08); padding-bottom:6px; margin-bottom:4px; }
            .yt-subtab-btn { flex:1; background:rgba(255,255,255,0.04); border:1px solid rgba(255,255,255,0.08); border-radius:6px; padding:5px 6px; font-size:10.5px; font-weight:700; color:var(--text-muted, #a6adc8); cursor:pointer; transition:all 0.15s; display:flex; align-items:center; justify-content:center; gap:5px; white-space:nowrap; }
            .yt-subtab-btn:hover { background:rgba(255,255,255,0.08); color:#fff; }
            .yt-subtab-btn.activo { background:rgba(137,180,250,0.18); border-color:var(--accent-blue, #89b4fa); color:#89b4fa; }

            /* Barra de acción y formulario de Fotogramas */
            .yt-fotograma-barra { display:flex; justify-content:space-between; align-items:center; gap:6px; }
            .yt-fotograma-form { background:rgba(0,0,0,0.28); border:1px solid var(--border-color, rgba(255,255,255,0.12)); border-radius:8px; padding:10px; display:flex; flex-direction:column; gap:8px; animation:ytFadeIn 0.2s ease-out; }
            @keyframes ytFadeIn { from { opacity:0; transform:translateY(-4px); } to { opacity:1; transform:translateY(0); } }

            .yt-fotograma-preview-wrap { position:relative; width:100%; border-radius:6px; overflow:hidden; background:rgba(0,0,0,0.4); border:1px dashed rgba(255,255,255,0.2); display:flex; flex-direction:column; align-items:center; justify-content:center; min-height:100px; }
            .yt-fotograma-preview-img { width:100%; max-height:160px; object-fit:contain; display:block; background:#000; }
            .yt-fotograma-placeholder { padding:12px; text-align:center; color:var(--text-muted, #a6adc8); font-size:11px; display:flex; flex-direction:column; align-items:center; gap:6px; }
            .yt-fotograma-placeholder i { font-size:20px; color:var(--accent-blue, #89b4fa); opacity:0.7; }
            .yt-fotograma-thumb-bar { display:flex; gap:4px; flex-wrap:wrap; margin-top:2px; }
            .yt-btn-thumb-opt { background:rgba(255,255,255,0.05); border:1px solid rgba(255,255,255,0.1); border-radius:4px; color:var(--text-muted, #a6adc8); font-size:9.5px; padding:2px 6px; cursor:pointer; transition:all 0.15s; }
            .yt-btn-thumb-opt:hover { color:#fff; background:rgba(255,255,255,0.15); border-color:#89b4fa; }
            .yt-btn-thumb-opt.activo { background:rgba(137,180,250,0.25); color:#89b4fa; border-color:#89b4fa; font-weight:700; }

            /* Lista de Tarjetas de Fotogramas */
            .yt-fotogramas-lista { display:flex; flex-direction:column; gap:8px; }
            .yt-fotograma-card { background:rgba(255,255,255,0.035); border:1px solid var(--border-color, rgba(255,255,255,0.08)); border-radius:8px; overflow:hidden; display:flex; flex-direction:column; transition:all 0.15s; }
            .yt-fotograma-card:hover { border-color:rgba(137,180,250,0.3); background:rgba(255,255,255,0.05); }
            .yt-fotograma-card-header { display:flex; align-items:center; justify-content:space-between; gap:6px; padding:7px 9px; background:rgba(0,0,0,0.18); border-bottom:1px solid rgba(255,255,255,0.04); }
            .yt-fotograma-card-titulo { font-size:11.5px; font-weight:700; color:#fff; flex:1; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
            .yt-fotograma-card-body { padding:8px 9px; display:flex; gap:9px; align-items:flex-start; }
            .yt-fotograma-thumb-click { position:relative; width:92px; height:58px; flex-shrink:0; border-radius:5px; overflow:hidden; cursor:pointer; border:1px solid rgba(255,255,255,0.1); background:#000; }
            .yt-fotograma-thumb-click img { width:100%; height:100%; object-fit:cover; transition:transform 0.2s; }
            .yt-fotograma-thumb-click:hover img { transform:scale(1.06); }
            .yt-fotograma-zoom-badge { position:absolute; bottom:2px; right:2px; background:rgba(0,0,0,0.7); color:#fff; font-size:9px; padding:1px 4px; border-radius:3px; opacity:0.85; }
            .yt-fotograma-info { flex:1; min-width:0; display:flex; flex-direction:column; gap:4px; font-size:11px; color:#cdd6f4; line-height:1.4; }
            .yt-fotograma-explicacion { white-space:pre-wrap; max-height:120px; overflow-y:auto; word-break:break-word; }
            .yt-fotograma-footer { display:flex; justify-content:space-between; align-items:center; gap:6px; padding:5px 9px; background:rgba(0,0,0,0.12); font-size:10px; color:var(--text-muted, #a6adc8); border-top:1px solid rgba(255,255,255,0.03); }

            /* Lightbox zoom modal */
            .yt-lightbox-overlay { position:absolute; inset:0; background:rgba(0,0,0,0.88); backdrop-filter:blur(4px); z-index:9999; display:flex; align-items:center; justify-content:center; padding:20px; animation:ytFadeIn 0.2s ease-out; }
            .yt-lightbox-box { max-width:92%; max-height:92%; background:var(--bg-panel, #181825); border:1px solid rgba(255,255,255,0.15); border-radius:10px; overflow:hidden; display:flex; flex-direction:column; box-shadow:0 15px 35px rgba(0,0,0,0.6); }
            .yt-lightbox-top { display:flex; align-items:center; justify-content:space-between; padding:8px 12px; background:rgba(0,0,0,0.3); border-bottom:1px solid rgba(255,255,255,0.08); color:#fff; font-size:12px; font-weight:700; gap:8px; }
            .yt-lightbox-img { max-width:100%; max-height:72vh; object-fit:contain; background:#000; display:block; }
            .yt-lightbox-bottom { padding:10px 14px; font-size:11.5px; color:#cdd6f4; background:rgba(0,0,0,0.25); max-height:120px; overflow-y:auto; line-height:1.4; white-space:pre-wrap; }

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

    let timeoutSugerencias = null;

    function solicitarSugerencias(texto) {
        clearTimeout(timeoutSugerencias);
        if (!texto || texto.trim().length < 2) {
            estado.sugerenciasActivas = [];
            estado.sugerenciasAbiertas = false;
            pintarSugerenciasDropdown();
            return;
        }
        timeoutSugerencias = setTimeout(async () => {
            try {
                const r = await fetch(`/api/youtube/sugerencias?q=${encodeURIComponent(texto.trim())}&limite=7`);
                if (r.ok) {
                    const d = await r.json();
                    estado.sugerenciasActivas = d.sugerencias || [];
                    estado.sugerenciasAbiertas = estado.sugerenciasActivas.length > 0;
                    pintarSugerenciasDropdown();
                }
            } catch (e) { }
        }, 200);
    }

    function pintarSugerenciasDropdown() {
        const box = $('yt-sugerencias-box');
        if (!box) return;
        if (!estado.sugerenciasAbiertas || !estado.sugerenciasActivas.length) {
            box.style.display = 'none';
            box.innerHTML = '';
            return;
        }
        box.innerHTML = estado.sugerenciasActivas.map((sug, idx) => `
            <div class="yt-sug-item" data-sug="${esc(sug)}" data-idx="${idx}">
              <i class="fa-solid fa-magnifying-glass"></i>
              <span>${esc(sug)}</span>
            </div>
        `).join('');
        box.style.display = 'flex';

        box.querySelectorAll('.yt-sug-item').forEach(it => {
            it.onclick = () => {
                const sug = it.dataset.sug;
                const inp = $('yt-input-buscar');
                if (inp) inp.value = sug;
                estado.busqueda = sug;
                estado.sugerenciasAbiertas = false;
                box.style.display = 'none';
                ejecutarBusquedaYt(sug);
            };
        });
    }

    async function ejecutarBusquedaYt(termino, tipo = null, palabraSlug = null) {
        if (!termino || !termino.trim()) return;
        const q = termino.trim();
        estado.busqueda = q;
        estado.modoCatalogo = 'busqueda_yt';
        estado.palabraRegistradaActiva = palabraSlug;
        if (tipo) estado.filtroTipoYt = tipo;
        estado.busquedaYtCargando = true;
        estado.busquedaYtError = null;
        estado.sugerenciasAbiertas = false;
        agregarAHistorial(q);
        pintar();

        try {
            const params = new URLSearchParams({
                q: q,
                tipo: estado.filtroTipoYt || 'todos',
                idioma: estado.filtroIdiomaYt || 'todos',
                duracion_filtro: estado.filtroDuracionYt || 'todas',
                orden: estado.ordenYt || 'educativo',
                filtro_educativo: 'true'
            });
            const url = `/api/youtube/buscar?${params.toString()}`;
            const resp = await fetch(url);
            if (!resp.ok) {
                const err = await resp.json().catch(() => ({}));
                throw new Error(err.detail || `Error en servidor HTTP ${resp.status}`);
            }
            const data = await resp.json();
            estado.resultadosBusquedaYt = data.resultados || [];
            estado.infoPalabraRegistrada = data.palabra_registrada || null;
            if (data.error && (!estado.resultadosBusquedaYt || estado.resultadosBusquedaYt.length === 0)) {
                estado.busquedaYtError = data.error;
            }
        } catch (err) {
            console.error('Error buscando cursos en YouTube:', err);
            estado.busquedaYtError = err.message || 'No se pudo conectar con el motor de búsqueda de YouTube.';
            estado.resultadosBusquedaYt = [];
        } finally {
            estado.busquedaYtCargando = false;
            pintar();
        }
    }

    function pintarCatalogo(raiz) {
        const busq = estado.busqueda.toLowerCase().trim();
        const todosProgreso = leerProgresoTodos();
        const historial = leerHistorialBusquedas();

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

        // Filtrado del catálogo local
        const filtrados = VIDEOS_CURADOS.filter(v => {
            const p = todosProgreso[v.id] || {};
            const esComp = p.estado === 'completado' || p.porcentaje >= 100;
            const esEnProg = p.estado === 'en_progreso' || (p.porcentaje && p.porcentaje > 0 && !esComp);
            const esSinIni = !esComp && !esEnProg;

            if (estado.filtroProgreso === 'completados' && !esComp) return false;
            if (estado.filtroProgreso === 'en_progreso' && !esEnProg) return false;
            if (estado.filtroProgreso === 'sin_iniciar' && !esSinIni) return false;

            const coincideCat = estado.filtroCategoria === 'todas' || (estado.filtroCategoria === 'universidades' ? Boolean(v.universidad) : v.categoria === estado.filtroCategoria);
            const coincideTexto = !busq || v.titulo.toLowerCase().includes(busq) || v.canal.toLowerCase().includes(busq) || (v.descripcion && v.descripcion.toLowerCase().includes(busq));
            return coincideCat && coincideTexto;
        });

        // Coincidencias de búsqueda híbrida federada (catálogo curado que coincida con la consulta actual)
        const tokensBusq = busq.split(/\s+/).filter(Boolean);
        const coincidenciasCuradas = (estado.modoCatalogo === 'busqueda_yt' && tokensBusq.length > 0) ? VIDEOS_CURADOS.filter(c => {
            const target = `${c.titulo || ''} ${c.canal || ''} ${c.descripcion || ''} ${c.universidad || ''} ${c.categoria || ''}`.toLowerCase();
            return tokensBusq.every(tok => target.includes(tok));
        }) : [];

        // Metadata de palabra registrada activa si existe
        const metaPalabra = estado.palabraRegistradaActiva ? (PALABRAS_REGISTRADAS_DEF.find(p => p.slug === estado.palabraRegistradaActiva) || estado.infoPalabraRegistrada) : null;

        raiz.innerHTML = `
            <div class="yt-raiz ${estado.ocultarTexto ? 'yt-modo-compacto' : ''}">
              <!-- Barra Superior Principal -->
              <div class="yt-barra">
                <div class="yt-logo"><i class="fa-brands fa-youtube"></i> YouTube en Prig</div>

                <!-- Selector de Modos -->
                <div class="yt-modo-selector">
                  <button class="yt-modo-tab ${estado.modoCatalogo === 'catalogo' ? 'activo' : ''}" id="yt-tab-modo-catalogo" title="Cursos universitarios y canales de élite curados">
                    <i class="fa-solid fa-graduation-cap"></i> Catálogo Curado (${VIDEOS_CURADOS.length})
                  </button>
                  <button class="yt-modo-tab ${estado.modoCatalogo === 'busqueda_yt' ? 'activo' : ''}" id="yt-tab-modo-busqueda" title="Motor de búsqueda en vivo en YouTube">
                    <i class="fa-solid fa-magnifying-glass"></i> Buscador YouTube <span class="yt-tag-live">Live</span>
                  </button>
                </div>

                <!-- Input de Búsqueda con Autocompletado Flotante -->
                <div class="yt-search-container">
                  <input id="yt-input-buscar" class="yt-campo-buscar" placeholder="${estado.modoCatalogo === 'busqueda_yt' ? 'Buscar cursos, temas o playlists en YouTube...' : 'Pega un enlace de YouTube (https://...) o busca por tema...'}" value="${esc(estado.busqueda)}" autocomplete="off">
                  <div id="yt-sugerencias-box" class="yt-sugerencias-dropdown" style="display:none;"></div>
                </div>

                ${estado.modoCatalogo === 'busqueda_yt' ? `
                  <button class="yt-btn rojo" id="yt-btn-buscar-yt"><i class="fa-solid fa-magnifying-glass"></i> Buscar</button>
                ` : `
                  <button class="yt-btn rojo" id="yt-btn-cargar"><i class="fa-solid fa-play"></i> Reproducir</button>
                  <button class="yt-btn" id="yt-btn-buscar-en-yt" title="Explorar cursos de este tema en YouTube en vivo"><i class="fa-brands fa-youtube"></i> Buscar en YouTube</button>
                `}

                <button class="yt-btn ${estado.ocultarTexto ? 'azul' : ''}" id="yt-btn-toggle-texto" title="Ocultar o mostrar descripciones de los videos"><i class="fa-solid ${estado.ocultarTexto ? 'fa-eye' : 'fa-eye-slash'}"></i> ${estado.ocultarTexto ? 'Mostrar descripciones' : 'Ocultar texto'}</button>
              </div>

              <!-- Barra de Palabras Registradas de Alta Demanda -->
              <div class="yt-palabras-barra">
                <div class="yt-palabras-label"><i class="fa-solid fa-fire" style="color:#f59e0b;"></i> Palabras Clave:</div>
                <div class="yt-palabras-items">
                  ${PALABRAS_REGISTRADAS_DEF.map(p => `
                    <button class="yt-pill-palabra ${p.slug} ${estado.palabraRegistradaActiva === p.slug ? 'activa' : ''}" data-slug="${p.slug}" data-palabra="${p.palabra}" title="${p.desc}">
                      <span>${p.emoji}</span>
                      <span>${p.palabra}</span>
                    </button>
                  `).join('')}
                </div>
              </div>

              ${estado.modoCatalogo === 'busqueda_yt' ? `
                <!-- Barra de Facetas, Filtros Avanzados e Historial -->
                <div class="yt-facetas-barra">
                  <div class="yt-facetas-grupo">
                    <span class="yt-faceta-label"><i class="fa-solid fa-sliders"></i> Filtros:</span>
                    
                    <select id="yt-filtro-tipo" class="yt-faceta-select" title="Tipo de resultado">
                      <option value="todos" ${estado.filtroTipoYt === 'todos' ? 'selected' : ''}>Todos (Videos y Listas)</option>
                      <option value="video" ${estado.filtroTipoYt === 'video' ? 'selected' : ''}>Solo Cursos / Videos</option>
                      <option value="playlist" ${estado.filtroTipoYt === 'playlist' ? 'selected' : ''}>Solo Playlists</option>
                    </select>

                    <select id="yt-filtro-duracion" class="yt-faceta-select" title="Duración del contenido">
                      <option value="todas" ${estado.filtroDuracionYt === 'todas' ? 'selected' : ''}>⏱ Cualquier duración</option>
                      <option value="cortos" ${estado.filtroDuracionYt === 'cortos' ? 'selected' : ''}>⚡ Cortos (&lt; 30 min)</option>
                      <option value="clases" ${estado.filtroDuracionYt === 'clases' ? 'selected' : ''}>📖 Clases (30m - 2h)</option>
                      <option value="cursos" ${estado.filtroDuracionYt === 'cursos' ? 'selected' : ''}>🎓 Cursos (+ 2h)</option>
                      <option value="playlists" ${estado.filtroDuracionYt === 'playlists' ? 'selected' : ''}>📚 Listas / Playlists</option>
                    </select>

                    <select id="yt-filtro-idioma" class="yt-faceta-select" title="Idioma preferido">
                      <option value="todos" ${estado.filtroIdiomaYt === 'todos' ? 'selected' : ''}>🌐 Idioma: Todos</option>
                      <option value="es" ${estado.filtroIdiomaYt === 'es' ? 'selected' : ''}>🇪🇸 Español</option>
                      <option value="en" ${estado.filtroIdiomaYt === 'en' ? 'selected' : ''}>🇬🇧 Inglés</option>
                    </select>

                    <select id="yt-orden" class="yt-faceta-select" title="Criterio de ordenamiento">
                      <option value="educativo" ${estado.ordenYt === 'educativo' ? 'selected' : ''}>⭐ Más didáctico (Score IA)</option>
                      <option value="duracion" ${estado.ordenYt === 'duracion' ? 'selected' : ''}>⏳ Mayor duración</option>
                      <option value="vistas" ${estado.ordenYt === 'vistas' ? 'selected' : ''}>🔥 Más vistos</option>
                    </select>
                  </div>

                  ${historial.length ? `
                    <div class="yt-historial-barra">
                      <span class="yt-faceta-label" style="opacity:0.75;"><i class="fa-solid fa-clock-rotate-left"></i> Recientes:</span>
                      ${historial.map(h => `
                        <span class="yt-chip-historial" data-hist="${esc(h)}">${esc(h)}</span>
                      `).join('')}
                      <button id="yt-btn-limpiar-historial" style="background:transparent; border:none; color:var(--text-muted); cursor:pointer; font-size:10px; padding:2px 4px;" title="Limpiar historial"><i class="fa-solid fa-xmark"></i></button>
                    </div>
                  ` : ''}
                </div>
              ` : `
                <!-- Barra de Categorías del Catálogo Curado -->
                <div class="yt-chips">
                  ${CATEGORIAS.map(c => `
                    <button class="yt-chip ${estado.filtroCategoria === c.id ? 'activo' : ''}" data-cat="${c.id}">${esc(c.label)}</button>
                  `).join('')}
                </div>
              `}

              <!-- Cuerpo Principal -->
              <div class="yt-cuerpo">
                ${estado.modoCatalogo === 'catalogo' ? `
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
                      <p style="margin:6px 0 12px; font-size:11.5px;">¿Quieres buscar cursos de "${esc(estado.busqueda)}" en YouTube en tiempo real?</p>
                      <button class="yt-btn rojo" id="yt-btn-buscar-en-vivo-vacio"><i class="fa-solid fa-magnifying-glass"></i> Buscar en YouTube Live</button>
                    </div>
                  ` : `
                    <div class="yt-grid">
                      ${filtrados.map(v => {
                          const prog = todosProgreso[v.id] || { estado: 'sin_iniciar', porcentaje: 0, ultimoMinuto: '00:00' };
                          const esComp = prog.estado === 'completado' || prog.porcentaje >= 100;
                          const esProg = !esComp && (prog.estado === 'en_progreso' || prog.porcentaje > 0);

                          return `
                            <div class="yt-tarjeta ${v.playlist ? 'es-playlist' : ''}" data-video-id="${esc(v.id)}">
                              <div class="yt-miniatura">
                                <img src="${generarUrlMiniatura(v.id, v.playlist)}" alt="${esc(v.titulo)}" loading="lazy" onerror="window.prigYtImgFallback(this, '${esc(v.id)}', '${esc(v.playlist || '')}', '${esc(v.titulo)}')">
                                ${v.playlist ? `
                                  <span class="yt-miniatura-playlist-badge"><i class="fa-solid fa-layer-group"></i> Playlist</span>
                                  <div class="yt-playlist-stack" title="Lista de reproducción"><i class="fa-solid fa-list-ol"></i></div>
                                ` : ''}
                                <span class="yt-duracion">${esc(v.duracion)}</span>
                                ${!v.playlist ? `<span class="yt-nivel">${esc(v.nivel)}</span>` : ''}
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
                                ${(v.universidad || v.playlist) ? `
                                  <div style="display:flex; align-items:center; gap:6px; flex-wrap:wrap; margin-bottom:2px;">
                                    ${v.universidad ? `<span class="yt-tag-uni" title="${esc(v.universidad)}"><i class="fa-solid fa-graduation-cap"></i> ${esc(v.universidad)}</span>` : ''}
                                    ${v.playlist ? `<a class="yt-tag-playlist" href="https://www.youtube.com/playlist?list=${esc(v.playlist)}" target="_blank" rel="noopener noreferrer" title="Ver playlist oficial en YouTube" onclick="event.stopPropagation();"><i class="fa-solid fa-list-ol"></i> Playlist</a>` : ''}
                                  </div>
                                ` : ''}
                                <h3 class="yt-tarjeta-titulo">${esc(v.titulo)}</h3>
                                <div class="yt-tarjeta-canal"><i class="fa-solid fa-circle-check" style="color:#ff0000; font-size:10px;"></i> ${esc(v.canal)}</div>
                                <p class="yt-tarjeta-desc">${esc(v.descripcion || '')}</p>
                              </div>
                            </div>
                          `;
                      }).join('')}
                    </div>
                  `}
                ` : `
                  <!-- Modo Buscador YouTube en Tiempo Real & Federado -->
                  ${metaPalabra ? `
                    <div class="yt-banner-palabra" style="border-left: 4px solid ${metaPalabra.color || '#ff0000'};">
                      <div class="yt-banner-palabra-info">
                        <div class="yt-banner-palabra-icono">${metaPalabra.emoji || '🔥'}</div>
                        <div>
                          <h3 class="yt-banner-palabra-titulo">${esc(metaPalabra.palabra)} · Motor de Búsqueda Didáctico</h3>
                          <p class="yt-banner-palabra-desc">${esc(metaPalabra.desc || metaPalabra.descripcion || '')}</p>
                        </div>
                      </div>
                      ${metaPalabra.tags ? `
                        <div class="yt-banner-tags">
                          ${metaPalabra.tags.map(t => `<span class="yt-banner-tag">#${esc(t)}</span>`).join('')}
                        </div>
                      ` : ''}
                    </div>
                  ` : ''}

                  ${estado.busquedaYtCargando ? `
                    <div class="yt-loading-box">
                      <i class="fa-solid fa-circle-notch yt-loading-spinner"></i>
                      <p style="margin:0; font-weight:600; color:#fff;">Explorando cursos con YouTube InnerTube para "${esc(estado.busqueda)}"...</p>
                      <span style="font-size:11.5px; color:var(--text-muted);">Aplicando ranking pedagógico, canales de élite y filtros de duración</span>
                    </div>
                  ` : estado.busquedaYtError ? `
                    <div style="text-align:center; padding:30px; background:rgba(255,0,0,0.06); border:1px solid rgba(255,0,0,0.25); border-radius:10px; margin:20px 0;">
                      <i class="fa-solid fa-triangle-exclamation" style="font-size:32px; color:#ff5555; margin-bottom:10px; display:block;"></i>
                      <p style="color:#ff8888; font-weight:600; margin:0 0 6px;">${esc(estado.busquedaYtError)}</p>
                      <button class="yt-btn rojo" id="yt-btn-reintentar-busqueda" style="margin-top:8px;"><i class="fa-solid fa-rotate-right"></i> Reintentar</button>
                      <button class="yt-btn yt-btn-volver-catalogo" data-action="volver-catalogo" style="margin-top:8px; margin-left:8px;"><i class="fa-solid fa-book"></i> Ver Catálogo Curado</button>
                    </div>
                  ` : (estado.resultadosBusquedaYt.length === 0 && coincidenciasCuradas.length === 0) ? `
                    <div style="text-align:center; padding:40px; color:var(--text-muted);">
                      <i class="fa-brands fa-youtube" style="font-size:44px; opacity:0.3; margin-bottom:12px; display:block;"></i>
                      <p style="margin:0; font-size:13.5px; color:#fff; font-weight:600;">No se encontraron resultados para "${esc(estado.busqueda)}".</p>
                      <p style="margin:6px 0 16px; font-size:11.5px;">Prueba seleccionando una de las palabras clave registradas o cambiando los filtros.</p>
                      <button class="yt-btn yt-btn-volver-catalogo" data-action="volver-catalogo"><i class="fa-solid fa-arrow-left"></i> Volver al Catálogo Curado</button>
                    </div>
                  ` : `
                    <!-- 1. Sección Superior: Búsqueda Federada - Cursos Curados Verificados en Prig -->
                    ${coincidenciasCuradas.length > 0 ? `
                      <div class="yt-seccion-separador">
                        <h4 class="yt-seccion-titulo"><i class="fa-solid fa-graduation-cap" style="color:var(--accent-green, #a6e3a1);"></i> Cursos Oficiales Verificados en Prig (${coincidenciasCuradas.length})</h4>
                        <span style="font-size:11px; color:var(--text-muted);">Cursos universitarios con seguimiento y desafíos didácticos</span>
                      </div>
                      <div class="yt-grid" style="margin-bottom:24px;">
                        ${coincidenciasCuradas.map(v => {
                            const prog = todosProgreso[v.id] || { estado: 'sin_iniciar', porcentaje: 0, ultimoMinuto: '00:00' };
                            const esComp = prog.estado === 'completado' || prog.porcentaje >= 100;
                            const esProg = !esComp && (prog.estado === 'en_progreso' || prog.porcentaje > 0);

                            return `
                              <div class="yt-tarjeta ${v.playlist ? 'es-playlist' : ''}" data-video-id="${esc(v.id)}">
                                <div class="yt-miniatura">
                                  <img src="${generarUrlMiniatura(v.id, v.playlist)}" alt="${esc(v.titulo)}" loading="lazy" onerror="window.prigYtImgFallback(this, '${esc(v.id)}', '${esc(v.playlist || '')}', '${esc(v.titulo)}')">
                                  ${v.playlist ? `
                                    <span class="yt-miniatura-playlist-badge"><i class="fa-solid fa-layer-group"></i> Playlist</span>
                                    <div class="yt-playlist-stack" title="Lista de reproducción"><i class="fa-solid fa-list-ol"></i></div>
                                  ` : ''}
                                  <span class="yt-duracion">${esc(v.duracion)}</span>
                                  <span class="yt-nivel" style="background:#10b981; color:#fff;"><i class="fa-solid fa-circle-check"></i> Verificado</span>
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
                                  <div style="display:flex; align-items:center; gap:6px; flex-wrap:wrap; margin-bottom:2px;">
                                    ${v.universidad ? `<span class="yt-tag-uni" title="${esc(v.universidad)}"><i class="fa-solid fa-graduation-cap"></i> ${esc(v.universidad)}</span>` : ''}
                                    ${v.playlist ? `<a class="yt-tag-playlist" href="https://www.youtube.com/playlist?list=${esc(v.playlist)}" target="_blank" rel="noopener noreferrer" title="Ver playlist oficial en YouTube" onclick="event.stopPropagation();"><i class="fa-solid fa-list-ol"></i> Playlist</a>` : ''}
                                  </div>
                                  <h3 class="yt-tarjeta-titulo">${esc(v.titulo)}</h3>
                                  <div class="yt-tarjeta-canal"><i class="fa-solid fa-circle-check" style="color:#ff0000; font-size:10px;"></i> ${esc(v.canal)}</div>
                                  <p class="yt-tarjeta-desc">${esc(v.descripcion || '')}</p>

                                  <div style="display:flex; justify-content:space-between; align-items:center; margin-top:auto; padding-top:6px; border-top:1px solid rgba(255,255,255,0.06); gap:6px;">
                                    <button class="yt-btn rojo btn-reproducir-card" style="font-size:10.5px; padding:3px 9px;" data-video-id="${esc(v.id)}">
                                      <i class="fa-solid fa-play"></i> Reproducir
                                    </button>
                                    <button class="yt-btn-guardar-catalogo guardado" data-video-id="${esc(v.id)}" title="En tu catálogo permanente">
                                      <i class="fa-solid fa-check"></i> En Catálogo
                                    </button>
                                  </div>
                                </div>
                              </div>
                            `;
                        }).join('')}
                      </div>
                    ` : ''}

                    <!-- 2. Sección Inferior: Descubrimientos en Vivo desde YouTube -->
                    ${estado.resultadosBusquedaYt.length > 0 ? `
                      <div class="yt-seccion-separador">
                        <div style="display:flex; align-items:center; gap:8px;">
                          <h4 class="yt-seccion-titulo"><i class="fa-brands fa-youtube" style="color:#ff0000;"></i> Resultados en Vivo de YouTube (${estado.resultadosBusquedaYt.length})</h4>
                          <span class="yt-badge-search-count">${estado.resultadosBusquedaYt.length} cursos</span>
                        </div>
                        <button class="yt-btn yt-btn-volver-catalogo" data-action="volver-catalogo"><i class="fa-solid fa-arrow-left"></i> Volver a Catálogo Curado (${VIDEOS_CURADOS.length})</button>
                      </div>

                      <div class="yt-grid">
                        ${estado.resultadosBusquedaYt.map(v => {
                            const yaGuardado = VIDEOS_CURADOS.some(c => c.id === v.id);
                            return `
                              <div class="yt-tarjeta es-busqueda-live ${v.es_playlist ? 'es-playlist' : ''}" data-video-id="${esc(v.id)}" data-es-playlist="${v.es_playlist ? '1' : '0'}">
                                <div class="yt-miniatura">
                                  <img src="${esc(v.miniatura || generarUrlMiniatura(v.id, v.es_playlist ? v.id : ''))}" alt="${esc(v.titulo)}" loading="lazy" onerror="window.prigYtImgFallback(this, '${esc(v.id)}', '${esc(v.es_playlist ? v.id : '')}', '${esc(v.titulo)}')">
                                  ${v.es_playlist ? `
                                    <span class="yt-miniatura-playlist-badge"><i class="fa-solid fa-layer-group"></i> Playlist</span>
                                    <div class="yt-playlist-stack" title="Lista de reproducción"><i class="fa-solid fa-list-ol"></i></div>
                                  ` : ''}
                                  <span class="yt-duracion">${esc(v.duracion)}</span>
                                  <span class="yt-nivel" style="background:#ff0000; color:#fff;"><i class="fa-brands fa-youtube"></i> En Vivo</span>
                                  ${v.idioma ? `<span class="yt-idioma">${esc(v.idioma)}</span>` : ''}
                                </div>

                                <div class="yt-tarjeta-info">
                                  <div style="display:flex; align-items:center; justify-content:space-between; gap:6px; margin-bottom:2px; flex-wrap:wrap;">
                                    <div style="display:flex; align-items:center; gap:5px;">
                                      <div class="yt-tarjeta-canal"><i class="fa-solid fa-circle-check" style="color:#ff0000; font-size:10px;"></i> ${esc(v.canal)}</div>
                                      ${v.es_canal_verificado ? `<span class="yt-badge-canal-top" title="Canal de alta autoridad pedagógica"><i class="fa-solid fa-shield-halved"></i> Top</span>` : ''}
                                    </div>
                                    ${v.vistas ? `<span style="font-size:10px; color:var(--text-muted);">${esc(v.vistas)}</span>` : ''}
                                  </div>
                                  <h3 class="yt-tarjeta-titulo" title="${esc(v.titulo)}">${esc(v.titulo)}</h3>
                                  <p class="yt-tarjeta-desc">${esc(v.descripcion || '')}</p>
                                  
                                  <div style="display:flex; justify-content:space-between; align-items:center; margin-top:auto; padding-top:6px; border-top:1px solid rgba(255,255,255,0.06); gap:6px;">
                                    <button class="yt-btn rojo btn-reproducir-card" style="font-size:10.5px; padding:3px 9px;" data-video-id="${esc(v.id)}">
                                      <i class="fa-solid fa-play"></i> Reproducir
                                    </button>
                                    <button class="yt-btn-guardar-catalogo ${yaGuardado ? 'guardado' : ''}" data-video-id="${esc(v.id)}" title="${yaGuardado ? 'Ya en tu catálogo' : 'Guardar en mi catálogo permanente'}">
                                      <i class="fa-solid ${yaGuardado ? 'fa-check' : 'fa-bookmark'}"></i> ${yaGuardado ? 'Guardado' : 'Guardar'}
                                    </button>
                                  </div>
                                </div>
                              </div>
                            `;
                        }).join('')}
                      </div>
                    ` : ''}
                  `}
                `}
              </div>
            </div>
        `;

        // Eventos de Input, Autocompletado y Búsqueda
        const inp = $('yt-input-buscar');
        if (inp) {
            inp.oninput = () => {
                estado.busqueda = inp.value;
                solicitarSugerencias(inp.value);
            };
            inp.onfocus = () => {
                if (estado.busqueda && estado.busqueda.trim().length >= 2) {
                    solicitarSugerencias(estado.busqueda);
                }
            };
            inp.onkeydown = (e) => {
                if (e.key === 'Enter') {
                    estado.sugerenciasAbiertas = false;
                    const box = $('yt-sugerencias-box');
                    if (box) box.style.display = 'none';
                    if (estado.modoCatalogo === 'busqueda_yt') {
                        ejecutarBusquedaYt(inp.value);
                    } else {
                        procesarEntradaOUrl(inp.value);
                    }
                } else if (e.key === 'Escape') {
                    estado.sugerenciasAbiertas = false;
                    const box = $('yt-sugerencias-box');
                    if (box) box.style.display = 'none';
                }
            };
        }

        // Selectores de Facetas
        const selectTipo = $('yt-filtro-tipo');
        if (selectTipo) {
            selectTipo.onchange = () => {
                estado.filtroTipoYt = selectTipo.value;
                if (estado.busqueda) ejecutarBusquedaYt(estado.busqueda, estado.filtroTipoYt, estado.palabraRegistradaActiva);
            };
        }

        const selectDuracion = $('yt-filtro-duracion');
        if (selectDuracion) {
            selectDuracion.onchange = () => {
                estado.filtroDuracionYt = selectDuracion.value;
                if (estado.busqueda) ejecutarBusquedaYt(estado.busqueda, estado.filtroTipoYt, estado.palabraRegistradaActiva);
            };
        }

        const selectIdioma = $('yt-filtro-idioma');
        if (selectIdioma) {
            selectIdioma.onchange = () => {
                estado.filtroIdiomaYt = selectIdioma.value;
                if (estado.busqueda) ejecutarBusquedaYt(estado.busqueda, estado.filtroTipoYt, estado.palabraRegistradaActiva);
            };
        }

        const selectOrden = $('yt-orden');
        if (selectOrden) {
            selectOrden.onchange = () => {
                estado.ordenYt = selectOrden.value;
                if (estado.busqueda) ejecutarBusquedaYt(estado.busqueda, estado.filtroTipoYt, estado.palabraRegistradaActiva);
            };
        }

        // Historial Reciente Chips
        raiz.querySelectorAll('.yt-chip-historial').forEach(ch => {
            ch.onclick = () => {
                const h = ch.dataset.hist;
                if (inp) inp.value = h;
                ejecutarBusquedaYt(h);
            };
        });

        const btnLimpiarHist = $('yt-btn-limpiar-historial');
        if (btnLimpiarHist) {
            btnLimpiarHist.onclick = () => {
                limpiarHistorialBusquedas();
                pintar();
            };
        }

        // Botón Buscar en Vivo
        const btnBuscarYt = $('yt-btn-buscar-yt');
        if (btnBuscarYt && inp) {
            btnBuscarYt.onclick = () => ejecutarBusquedaYt(inp.value);
        }

        const btnBuscarEnYt = $('yt-btn-buscar-en-yt');
        if (btnBuscarEnYt && inp) {
            btnBuscarEnYt.onclick = () => ejecutarBusquedaYt(inp.value || 'Machine Learning');
        }

        const btnBuscarVacio = $('yt-btn-buscar-en-vivo-vacio');
        if (btnBuscarVacio) {
            btnBuscarVacio.onclick = () => ejecutarBusquedaYt(estado.busqueda || 'Python');
        }

        const btnReintentar = $('yt-btn-reintentar-busqueda');
        if (btnReintentar) {
            btnReintentar.onclick = () => ejecutarBusquedaYt(estado.busqueda, estado.filtroTipoYt, estado.palabraRegistradaActiva);
        }

        // Botones Volver a Catálogo
        raiz.querySelectorAll('.yt-btn-volver-catalogo, [data-action="volver-catalogo"], #yt-btn-volver-catalogo').forEach(btn => {
            btn.onclick = () => {
                estado.modoCatalogo = 'catalogo';
                estado.palabraRegistradaActiva = null;
                pintar();
            };
        });

        // Tabs de Modos (Catálogo Curado vs Buscador YouTube)
        const tabCat = $('yt-tab-modo-catalogo');
        if (tabCat) {
            tabCat.onclick = () => {
                estado.modoCatalogo = 'catalogo';
                estado.palabraRegistradaActiva = null;
                pintar();
            };
        }

        const tabBusq = $('yt-tab-modo-busqueda');
        if (tabBusq) {
            tabBusq.onclick = () => {
                estado.modoCatalogo = 'busqueda_yt';
                if (!estado.resultadosBusquedaYt || estado.resultadosBusquedaYt.length === 0) {
                    ejecutarBusquedaYt(estado.busqueda || 'Deep Learning', 'todos', 'deep_learning');
                } else {
                    pintar();
                }
            };
        }

        // Pills de Palabras Registradas ("Deep Learning", "Machine Learning", "Python", "C++")
        raiz.querySelectorAll('.yt-pill-palabra').forEach(pill => {
            pill.onclick = () => {
                const slug = pill.dataset.slug;
                const palabra = pill.dataset.palabra;
                ejecutarBusquedaYt(palabra, estado.filtroTipoYt || 'todos', slug);
            };
        });

        const btnCargar = $('yt-btn-cargar');
        if (btnCargar && inp) {
            btnCargar.onclick = () => {
                const val = (inp.value || '').trim();
                if (!val) {
                    if (filtrados && filtrados.length > 0) {
                        reproducir(filtrados[0]);
                        return;
                    }
                    inp.focus();
                    if (window.layoutMgr && window.layoutMgr.mensajeEstado) {
                        window.layoutMgr.mensajeEstado('Escribe un tema o pega un enlace de YouTube', 2000);
                    }
                    return;
                }
                procesarEntradaOUrl(val);
            };
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

        // Botón Guardar en Catálogo desde resultados de búsqueda
        raiz.querySelectorAll('.yt-btn-guardar-catalogo').forEach(btn => {
            btn.onclick = (e) => {
                e.stopPropagation();
                const vidId = btn.dataset.videoId;
                const item = (estado.resultadosBusquedaYt || []).find(x => x.id === vidId);
                if (item) {
                    guardarCursoEnCatalogo(item);
                    btn.classList.add('guardado');
                    btn.innerHTML = '<i class="fa-solid fa-check"></i> Guardado';
                    btn.title = 'Ya en tu catálogo permanente';
                }
            };
        });

        // Click en tarjetas de catálogo local
        raiz.querySelectorAll('.yt-tarjeta:not(.es-busqueda-live)').forEach(tar => {
            tar.onclick = (e) => {
                if (e.target.closest('.yt-btn-quick-check')) return;
                const vidId = tar.dataset.videoId;
                const encontrado = VIDEOS_CURADOS.find(v => v.id === vidId) || { id: vidId, titulo: 'Video de YouTube', canal: 'YouTube' };
                reproducir(encontrado);
            };
        });

        // Click en tarjetas de búsqueda en vivo
        raiz.querySelectorAll('.yt-tarjeta.es-busqueda-live').forEach(tar => {
            tar.onclick = (e) => {
                if (e.target.closest('.yt-btn-guardar-catalogo')) return;
                const vidId = tar.dataset.videoId;
                const item = (estado.resultadosBusquedaYt || []).find(x => x.id === vidId);
                if (item) {
                    reproducir({
                        id: item.id,
                        playlist: item.es_playlist ? item.id : '',
                        titulo: item.titulo,
                        canal: item.canal,
                        duracion: item.duracion,
                        descripcion: item.descripcion,
                        miniatura: item.miniatura
                    });
                }
            };
        });

        // Click directo en botones "Reproducir" de tarjetas
        raiz.querySelectorAll('.btn-reproducir-card').forEach(btn => {
            btn.onclick = (e) => {
                e.stopPropagation();
                const vidId = btn.dataset.videoId;
                const item = (estado.resultadosBusquedaYt || []).find(x => x.id === vidId) || VIDEOS_CURADOS.find(x => x.id === vidId);
                if (item) {
                    reproducir({
                        id: item.id,
                        playlist: item.playlist || (item.es_playlist ? item.id : ''),
                        titulo: item.titulo,
                        canal: item.canal,
                        duracion: item.duracion,
                        descripcion: item.descripcion,
                        miniatura: item.miniatura
                    });
                }
            };
        });
    }

    function procesarEntradaOUrl(texto) {
        if (!texto || !texto.trim()) return;
        const textoLimpio = texto.trim();
        const vidId = extraerVideoId(textoLimpio);
        if (vidId) {
            const plId = extraerPlaylistId(textoLimpio);
            const existente = VIDEOS_CURADOS.find(v => v.id === vidId);
            reproducir(existente || {
                id: vidId,
                playlist: plId || '',
                titulo: `Video de YouTube (${vidId})`,
                canal: 'YouTube',
                descripcion: 'Video cargado mediante enlace directo.'
            });
            return;
        }
        const plId = extraerPlaylistId(textoLimpio);
        if (plId) {
            const existente = VIDEOS_CURADOS.find(v => v.playlist === plId);
            if (existente) {
                reproducir(existente);
                return;
            }
            reproducir({
                id: 'pl_' + plId,
                playlist: plId,
                titulo: `Playlist de YouTube (${plId})`,
                canal: 'YouTube Playlist',
                duracion: 'Lista de reproducción',
                nivel: 'Curso / Playlist',
                descripcion: 'Lista de reproducción de YouTube cargada directamente.'
            });
            return;
        }

        // Si no es un enlace o ID de YouTube, buscar en tiempo real en YouTube
        ejecutarBusquedaYt(textoLimpio, estado.filtroTipoYt || 'todos');
    }

    function reproducir(video) {
        estado.videoActual = video;
        estado.vista = 'reproductor';
        if (video && video.id && !String(video.id).startsWith('pl_')) {
            cargarTranscripcion(video.id, estado.idiomaSubtitulos || 'es');
        }
        pintar();
    }

    function renderTextoConResaltados(texto, explicaciones, startSeg, endSeg) {
        if (!texto) return '';
        if (!explicaciones || !explicaciones.length) return esc(texto);

        // Buscar explicaciones que coincidan con este intervalo o texto
        const relevantes = explicaciones.filter(exp => {
            if (!exp || !exp.texto) return false;
            const t = exp.texto.trim();
            if (t.length >= 2 && texto.includes(t)) return true;
            if (exp.startSegundos !== undefined && exp.endSegundos !== undefined) {
                const traslape = Math.max(0, Math.min(endSeg, exp.endSegundos) - Math.max(startSeg, exp.startSegundos));
                return traslape > 0;
            }
            return false;
        });

        if (relevantes.length === 0) {
            return esc(texto);
        }

        // Si hay una coincidencia completa de todo el párrafo
        const totalMatch = relevantes.find(exp => exp.texto.trim() === texto.trim());
        if (totalMatch) {
            return `<mark class="yt-resaltado-amarillo" data-exp-id="${esc(totalMatch.id)}" title="Explicación guardada [${esc(totalMatch.intervalo)}]">${esc(texto)}</mark>`;
        }

        // Reemplazar subcadenas específicas ordenadas por longitud descendente
        let htmlSalida = esc(texto);
        const subcadenas = relevantes
            .map(e => ({ exp: e, txt: e.texto.trim() }))
            .filter(item => item.txt.length >= 2)
            .sort((a, b) => b.txt.length - a.txt.length);

        for (const item of subcadenas) {
            const textoBuscar = esc(item.txt);
            if (htmlSalida.includes(textoBuscar)) {
                const reemplazo = `<mark class="yt-resaltado-amarillo" data-exp-id="${esc(item.exp.id)}" title="Explicación guardada [${esc(item.exp.intervalo)}]">${textoBuscar}</mark>`;
                htmlSalida = htmlSalida.split(textoBuscar).join(reemplazo);
            }
        }

        return htmlSalida;
    }

    function pintarReproductor(raiz) {
        const v = estado.videoActual;
        const prog = obtenerProgreso(v.id);
        const marcas = leerMarcasVideo(v.id);
        const fotogramas = leerFotogramas(v.id);
        const explicaciones = leerExplicaciones(v.id);
        const notaClave = `prig_yt_nota_${v.id}`;
        const notaGuardada = localStorage.getItem(notaClave) || '';
        const marcasDetectadas = extraerTimestampsDeTexto(notaGuardada);
        const objetivos = leerObjetivos(v.id);
        const resumen = leerResumen(v.id);
        const superadosObj = objetivos.filter(o => o.superado).length;
        const transDatos = (estado.transcripcion && estado.transcripcion.datos) || null;
        const segmentosTranscripcion = (transDatos && transDatos.segmentos) ? transDatos.segmentos : [];

        if (v && v.id && !String(v.id).startsWith('pl_')) {
            if (estado.transcripcion.videoId !== v.id && !estado.transcripcion.cargando) {
                setTimeout(() => {
                    cargarTranscripcion(v.id, estado.idiomaSubtitulos || 'es');
                }, 20);
            }
        }

        const esSoloPlaylist = String(v.id || '').startsWith('pl_') || (!v.id && v.playlist);
        const enlaceExterno = esSoloPlaylist
            ? `https://www.youtube.com/playlist?list=${esc(v.playlist)}`
            : `https://www.youtube.com/watch?v=${esc(v.id)}${v.playlist ? `&list=${esc(v.playlist)}` : ''}`;
        const servidorActual = obtenerServidorEmbed();
        const iframeSrc = construirEmbedUrl(v, prog.segundos);

        raiz.innerHTML = `
          <div class="yt-raiz">
            <div class="yt-header">
              <div class="yt-header-left">
                <button class="yt-btn yt-btn-volver-catalogo" id="yt-btn-volver" title="Volver al catálogo de cursos"><i class="fa-solid fa-arrow-left"></i> Catálogo</button>
                <div class="yt-logo-badge" style="font-size:13px; font-weight:700;"><i class="fa-brands fa-youtube"></i> ${esc(v.titulo)}</div>
                ${v.universidad ? `<span class="yt-tag-uni"><i class="fa-solid fa-graduation-cap"></i> ${esc(v.universidad)}</span>` : ''}
                ${v.playlist ? `<span class="yt-tag-playlist"><i class="fa-solid fa-list-ol"></i> Playlist</span>` : ''}
              </div>
              <div class="yt-header-right">
                <button class="yt-btn ${estado.ocultarTextoPlayer ? 'azul' : ''}" id="yt-btn-toggle-detalles" title="Ocultar o mostrar texto descriptivo del video (Modo Cine)"><i class="fa-solid ${estado.ocultarTextoPlayer ? 'fa-eye' : 'fa-eye-slash'}"></i> ${estado.ocultarTextoPlayer ? 'Mostrar texto' : 'Modo Cine'}</button>
                <button class="yt-btn rojo" id="yt-btn-abrir-externo-header" title="Abrir video en el navegador web del sistema (Chrome, Firefox, etc.)"><i class="fa-solid fa-arrow-up-right-from-square"></i> Abrir en Navegador</button>
                <a class="yt-btn" href="${enlaceExterno}" target="_blank" rel="noopener noreferrer" title="Enlace directo a YouTube"><i class="fa-brands fa-youtube"></i> Ver en YouTube</a>
              </div>
            </div>

            <div class="yt-player-layout">
              <div class="yt-player-main">
                <div class="yt-player-aux-bar">
                  <div class="yt-player-aux-left">
                    <span style="color:var(--text-muted); font-size:10.5px;"><i class="fa-solid fa-server"></i> Servidor:</span>
                    <button class="yt-btn" id="yt-btn-cambiar-servidor" style="padding:2px 7px; font-size:10.5px;" title="Alternar entre servidor estándar de YouTube y youtube-nocookie">
                      ${servidorActual === 'www.youtube.com' ? 'youtube.com (Estándar)' : 'youtube-nocookie.com (Privado)'}
                    </button>
                    <span style="color:var(--text-muted); font-size:10.5px; margin-left:6px;"><i class="fa-solid fa-language"></i> Subtítulos:</span>
                    <select id="yt-select-idioma-subtitulos" class="yt-select-idioma" title="Forzar idioma de subtítulos en el reproductor de YouTube y traducción lateral" style="background:#181825; color:#cdd6f4; border:1px solid rgba(255,255,255,0.15); border-radius:4px; font-size:10.5px; padding:2px 4px; outline:none; cursor:pointer;">
                      <option value="es" ${estado.idiomaSubtitulos === 'es' ? 'selected' : ''}>Español (traducción)</option>
                      <option value="en" ${estado.idiomaSubtitulos === 'en' ? 'selected' : ''}>English (original)</option>
                      <option value="none" ${estado.idiomaSubtitulos === 'none' ? 'selected' : ''}>Desactivados</option>
                    </select>
                  </div>
                  <div class="yt-player-aux-right">
                    <button class="yt-btn azul" id="yt-btn-copiar-enlace" style="padding:2px 8px; font-size:10.5px;" title="Copiar enlace del video al portapapeles">
                      <i class="fa-regular fa-copy"></i> Copiar enlace
                    </button>
                    <button class="yt-btn rojo" id="yt-btn-abrir-externo" style="padding:2px 8px; font-size:10.5px;" title="Abrir directamente en tu navegador predeterminado del sistema (Chrome, Firefox, etc.)">
                      <i class="fa-solid fa-arrow-up-right-from-square"></i> Abrir en Navegador
                    </button>
                  </div>
                </div>

                <div class="yt-iframe-wrap">
                  <iframe id="yt-iframe-player" src="${iframeSrc}" allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share" referrerpolicy="strict-origin-when-cross-origin" allowfullscreen></iframe>
                </div>

                <div class="yt-aviso-embed">
                  <i class="fa-solid fa-circle-info"></i>
                  <div style="flex:1;">
                    ¿El reproductor integrado muestra "No disponible" o faltan códecs en tu entorno? Puedes <button class="yt-btn-link" id="yt-btn-abrir-externo-link">abrirlo en tu navegador predeterminado</button> o alternar el servidor. Tus notas, progreso e IA seguirán activos aquí en Prig.
                  </div>
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
                    <div style="font-size:11.5px; color:var(--text-muted); display:flex; flex-wrap:wrap; gap:8px; align-items:center;">
                      <span>Canal: <b>${esc(v.canal || 'YouTube')}</b></span>
                      ${v.universidad ? `<span class="yt-tag-uni" style="font-size:10.5px;"><i class="fa-solid fa-graduation-cap"></i> ${esc(v.universidad)}</span>` : ''}
                      ${v.nivel ? `<span>· Nivel: <span style="color:var(--accent-purple); font-weight:600;">${esc(v.nivel)}</span></span>` : ''}
                      ${v.playlist ? `<a class="yt-tag-playlist" style="font-size:10.5px;" href="https://www.youtube.com/playlist?list=${esc(v.playlist)}" target="_blank" rel="noopener noreferrer"><i class="fa-solid fa-list-ol"></i> Playlist del curso oficial</a>` : ''}
                    </div>
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
                    <div class="yt-lateral-tab ${estado.pestanaLateral === 'traduccion' ? 'activo' : ''}" data-tab="traduccion" title="Traducción y explicación del video">
                      <i class="fa-solid fa-language"></i> Traducción
                      ${explicaciones.length > 0 ? `<span class="yt-badge-guardadas-tab" title="${explicaciones.length} explicaciones guardadas">${explicaciones.length}</span>` : ''}
                    </div>
                    <div class="yt-lateral-tab ${estado.pestanaLateral === 'notas' ? 'activo' : ''}" data-tab="notas"><i class="fa-solid fa-pencil"></i> Notas (${fotogramas.length + marcas.length})</div>
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
                    ` : estado.pestanaLateral === 'traduccion' ? `
                      <!-- Pestaña: Traducción y Explicación del Video -->
                      <div class="yt-subtabs-notas">
                        <button class="yt-subtab-btn ${estado.subpestanaTraduccion === 'transcripcion' ? 'activo' : ''}" data-subtab-trad="transcripcion" title="Transcripción del video explicada y traducida">
                          <i class="fa-solid fa-align-left"></i> Transcripción (${segmentosTranscripcion.length})
                        </button>
                        <button class="yt-subtab-btn ${estado.subpestanaTraduccion === 'guardadas' ? 'activo' : ''}" data-subtab-trad="guardadas" title="Explicaciones guardadas con intervalos de minutos">
                          <i class="fa-solid fa-bookmark" style="color:#f9e2af;"></i> Guardadas (${explicaciones.length})
                        </button>
                      </div>

                      ${estado.subpestanaTraduccion === 'guardadas' ? `
                        <!-- Vista: Explicaciones Guardadas e Intervalos de Minutos -->
                        <div style="display:flex; justify-content:space-between; align-items:center; margin:6px 0 8px;">
                          <span style="font-weight:700; font-size:11.5px; color:#fff;">
                            <i class="fa-solid fa-highlighter" style="color:#f9e2af;"></i> Explicaciones Destacadas (${explicaciones.length})
                          </span>
                          ${explicaciones.length > 0 ? `
                            <button class="yt-btn" id="yt-btn-exportar-explicaciones" style="padding:2px 7px; font-size:10px;" title="Copiar todas las explicaciones al cuaderno de notas">
                              <i class="fa-solid fa-file-import"></i> Al Cuaderno
                            </button>
                          ` : ''}
                        </div>

                        ${explicaciones.length === 0 ? `
                          <div style="text-align:center; padding:25px 12px; color:var(--text-muted); font-size:11px; display:flex; flex-direction:column; align-items:center; gap:8px;">
                            <i class="fa-regular fa-bookmark" style="font-size:30px; opacity:0.35; color:#f9e2af;"></i>
                            <p style="margin:0; line-height:1.45;">No tienes explicaciones guardadas todavía.<br>En la pestaña <b>Transcripción</b>, selecciona cualquier texto con el ratón y haz <b>clic derecho</b> para <b>resaltarlo en amarillo</b> y guardar el intervalo exacto de minutos para verlo después.</p>
                          </div>
                        ` : `
                          <div class="yt-explicaciones-lista">
                            ${explicaciones.map(exp => `
                              <div class="yt-exp-guardada-card" data-exp-id="${esc(exp.id)}">
                                <div class="yt-exp-cabecera">
                                  <button class="yt-exp-intervalo yt-btn-reproducir-intervalo" data-segundos="${exp.startSegundos}" data-end="${exp.endSegundos}" title="Saltar al minuto ${esc(exp.intervalo)} y ver en video">
                                    <i class="fa-solid fa-play" style="font-size:8px;"></i> ${esc(exp.intervalo)}
                                  </button>
                                  <span style="font-size:9.5px; color:var(--text-muted);">${esc(exp.fecha || '')}</span>
                                  <div style="display:flex; gap:3px;">
                                    <button class="yt-marca-btn" data-accion="copiar-exp" data-id="${esc(exp.id)}" title="Copiar texto de la explicación"><i class="fa-regular fa-copy"></i></button>
                                    <button class="yt-marca-btn" data-accion="cuaderno-exp" data-id="${esc(exp.id)}" title="Insertar en el cuaderno de notas"><i class="fa-solid fa-book-bookmark"></i></button>
                                    <button class="yt-marca-btn eliminar" data-accion="eliminar-exp" data-id="${esc(exp.id)}" title="Eliminar explicación guardada"><i class="fa-regular fa-trash-can"></i></button>
                                  </div>
                                </div>
                                <div class="yt-exp-texto">
                                  "${esc(exp.texto)}"
                                </div>
                                <div class="yt-exp-acciones">
                                  <button class="yt-btn azul yt-btn-reproducir-intervalo" data-segundos="${exp.startSegundos}" data-end="${exp.endSegundos}" style="padding:2px 8px; font-size:10px;">
                                    <i class="fa-solid fa-play"></i> Reproducir intervalo (${esc(exp.intervalo)})
                                  </button>
                                </div>
                              </div>
                            `).join('')}
                          </div>
                        `}
                      ` : `
                        <!-- Vista: Transcripción / Explicación Traducida con Resaltador -->
                        <div class="yt-trad-toolbar">
                          <div class="yt-trad-controles-fila">
                            <div class="yt-trad-modo-btns">
                              <button class="yt-trad-modo-btn ${estado.modoVistaTraduccion === 'traduccion' ? 'activo' : ''}" data-modo-trad="traduccion" title="Ver solo la traducción en español"><i class="fa-solid fa-language"></i> Español</button>
                              <button class="yt-trad-modo-btn ${estado.modoVistaTraduccion === 'bilingue' ? 'activo' : ''}" data-modo-trad="bilingue" title="Ver traducción y texto original en inglés"><i class="fa-solid fa-globe"></i> Bilingüe</button>
                            </div>
                            <button class="yt-btn" id="yt-btn-recargar-transcripcion" style="padding:2px 7px; font-size:10.5px;" title="Volver a cargar subtítulos y traducción"><i class="fa-solid fa-rotate-right"></i> Recargar</button>
                          </div>
                          <div>
                            <input type="text" id="yt-input-buscar-transcripcion" class="yt-trad-search-input" placeholder="Buscar concepto o palabra en la explicación..." value="${esc(estado.filtroTextoTraduccion || '')}">
                          </div>
                        </div>

                        ${estado.transcripcion.cargando ? `
                          <div class="yt-loading-box" style="margin-top:10px;">
                            <i class="fa-solid fa-circle-notch yt-loading-spinner" style="color:var(--accent-blue, #89b4fa);"></i>
                            <div style="font-weight:700; color:#fff;">Cargando explicación y traducción...</div>
                            <div style="font-size:11px; color:var(--text-muted);">Extrayendo subtítulos oficiales y generando traducción en español...</div>
                          </div>
                        ` : estado.transcripcion.error ? `
                          <div style="text-align:center; padding:20px 10px; color:var(--text-muted); font-size:11px; display:flex; flex-direction:column; align-items:center; gap:8px;">
                            <i class="fa-solid fa-circle-exclamation" style="font-size:26px; opacity:0.4; color:var(--accent-peach, #fab387);"></i>
                            <div style="color:#fff; font-weight:600;">No se pudo extraer la transcripción automática</div>
                            <p style="margin:0; line-height:1.4;">${esc(estado.transcripcion.error)}</p>
                            <div style="display:flex; gap:6px; margin-top:4px;">
                              <button class="yt-btn azul" id="yt-btn-reintentar-transcripcion"><i class="fa-solid fa-rotate-right"></i> Reintentar</button>
                              <button class="yt-btn" id="yt-btn-pegar-extra-trans"><i class="fa-solid fa-file-pen"></i> Pegar texto manual</button>
                            </div>
                          </div>
                        ` : segmentosTranscripcion.length === 0 ? `
                          <div style="text-align:center; padding:25px 12px; color:var(--text-muted); font-size:11px; display:flex; flex-direction:column; align-items:center; gap:8px;">
                            <i class="fa-solid fa-align-left" style="font-size:28px; opacity:0.35; color:var(--accent-blue);"></i>
                            <p style="margin:0; line-height:1.4;">No hay subtítulos disponibles en este momento para este video.</p>
                            <button class="yt-btn azul" id="yt-btn-reintentar-transcripcion"><i class="fa-solid fa-rotate-right"></i> Cargar transcripción</button>
                          </div>
                        ` : (() => {
                          const filtro = (estado.filtroTextoTraduccion || '').toLowerCase().trim();
                          const segmentosFiltrados = filtro
                            ? segmentosTranscripcion.filter(s => (s.texto && s.texto.toLowerCase().includes(filtro)) || (s.texto_original && s.texto_original.toLowerCase().includes(filtro)))
                            : segmentosTranscripcion;

                          if (segmentosFiltrados.length === 0) {
                            return `
                              <div style="text-align:center; padding:20px; color:var(--text-muted); font-size:11px;">
                                No se encontraron explicaciones que coincidan con "<b>${esc(estado.filtroTextoTraduccion)}</b>".
                              </div>
                            `;
                          }

                          return `
                            <div style="font-size:10px; color:var(--text-muted); display:flex; align-items:center; gap:5px; margin:4px 0 2px;">
                              <i class="fa-solid fa-highlighter" style="color:#f9e2af;"></i>
                              <span>Selecciona texto y haz <b>clic derecho</b> para <b>resaltar en amarillo</b> y guardar el intervalo.</span>
                            </div>

                            <div class="yt-transcripcion-cuerpo" id="yt-transcripcion-cuerpo">
                              ${segmentosFiltrados.map(seg => `
                                <div class="yt-bloque-transcripcion" data-start="${seg.start}" data-end="${seg.end}" data-intervalo="${esc(seg.intervalo)}">
                                  <div class="yt-bloque-transcripcion-header">
                                    <button class="yt-segmento-timestamp" data-segundos="${seg.start}" title="Saltar al inicio de esta explicación (${esc(seg.intervalo)})">
                                      <i class="fa-solid fa-play" style="font-size:8px;"></i> ${esc(seg.intervalo)}
                                    </button>
                                    <button class="yt-marca-btn" data-accion="guardar-bloque" data-start="${seg.start}" data-end="${seg.end}" data-intervalo="${esc(seg.intervalo)}" title="Resaltar y guardar todo este párrafo de explicación">
                                      <i class="fa-regular fa-bookmark"></i>
                                    </button>
                                  </div>
                                  <div class="yt-segmento-texto" data-intervalo="${esc(seg.intervalo)}" data-start="${seg.start}" data-end="${seg.end}">
                                    ${renderTextoConResaltados(seg.texto, explicaciones, seg.start, seg.end)}
                                  </div>
                                  ${estado.modoVistaTraduccion === 'bilingue' && seg.texto_original ? `
                                    <div class="yt-segmento-original" title="Texto original">${esc(seg.texto_original)}</div>
                                  ` : ''}
                                </div>
                              `).join('')}
                            </div>
                          `;
                        })()}
                      `}
                    ` : estado.pestanaLateral === 'notas' ? `
                      <!-- Barra de Subpestañas de Notas -->
                      <div class="yt-subtabs-notas">
                        <button class="yt-subtab-btn ${estado.subpestanaNotas === 'fotogramas' ? 'activo' : ''}" data-subtab="fotogramas" title="Notas visuales con capturas del video y explicaciones"><i class="fa-solid fa-camera"></i> Fotogramas (${fotogramas.length})</button>
                        <button class="yt-subtab-btn ${estado.subpestanaNotas === 'marcas' ? 'activo' : ''}" data-subtab="marcas" title="Notaciones y saltos por minuto"><i class="fa-solid fa-stopwatch"></i> Marcas (${marcas.length})</button>
                        <button class="yt-subtab-btn ${estado.subpestanaNotas === 'cuaderno' ? 'activo' : ''}" data-subtab="cuaderno" title="Cuaderno libre en Markdown"><i class="fa-solid fa-book-open"></i> Cuaderno</button>
                      </div>

                      ${estado.subpestanaNotas === 'fotogramas' ? `
                        <!-- Subpestaña: Fotogramas con Notas y Explicación -->
                        <div class="yt-fotograma-barra">
                          <span style="font-size:11px; font-weight:700; color:#fff;"><i class="fa-solid fa-camera" style="color:var(--accent-blue, #89b4fa);"></i> Notas Visuales (${fotogramas.length})</span>
                          <button class="yt-btn azul" id="yt-btn-toggle-form-foto" style="padding:3px 9px; font-size:10.5px;">
                            <i class="fa-solid ${estado.fotogramaFormAbierto ? 'fa-xmark' : 'fa-plus'}"></i> ${estado.fotogramaFormAbierto ? 'Cerrar captura' : 'Añadir Fotograma'}
                          </button>
                        </div>

                        ${estado.fotogramaFormAbierto ? `
                          <div class="yt-fotograma-form">
                            <div style="font-size:10.5px; font-weight:700; color:#fff; display:flex; justify-content:space-between; align-items:center;">
                              <span><i class="fa-solid fa-image" style="color:var(--accent-blue);"></i> Captura del momento</span>
                              <span style="font-size:10px; color:var(--text-muted);">Pega con <b>Ctrl+V</b> en cualquier parte</span>
                            </div>

                            <div class="yt-fotograma-preview-wrap" id="yt-fotograma-dropzone">
                              ${(estado.fotogramaTemporal && estado.fotogramaTemporal.imagenUrl) ? `
                                <img src="${esc(estado.fotogramaTemporal.imagenUrl)}" class="yt-fotograma-preview-img" alt="Fotograma a guardar">
                              ` : `
                                <div class="yt-fotograma-placeholder">
                                  <i class="fa-solid fa-camera-retro"></i>
                                  <span>Pega captura con <b>Ctrl+V</b> o elige un keyframe abajo</span>
                                </div>
                              `}
                            </div>

                            <div class="yt-fotograma-thumb-bar">
                              <span style="font-size:9.5px; color:var(--text-muted); align-self:center;">Keyframe YT:</span>
                              <button type="button" class="yt-btn-thumb-opt" data-keyframe="hqdefault">Portada</button>
                              <button type="button" class="yt-btn-thumb-opt" data-keyframe="1">25%</button>
                              <button type="button" class="yt-btn-thumb-opt" data-keyframe="2">50%</button>
                              <button type="button" class="yt-btn-thumb-opt" data-keyframe="3">75%</button>
                              <button type="button" class="yt-btn-thumb-opt" id="yt-btn-trigger-upload"><i class="fa-solid fa-upload"></i> Subir recorte</button>
                              <input type="file" id="yt-file-upload-fotograma" accept="image/*" style="display:none;">
                            </div>

                            <div style="display:flex; gap:6px; margin-top:2px;">
                              <input id="yt-input-foto-min" class="yt-input-min" placeholder="MM:SS" value="${esc((estado.fotogramaTemporal && estado.fotogramaTemporal.minuto) || (prog.ultimoMinuto !== '00:00' ? prog.ultimoMinuto : '00:00'))}" title="Minuto exacto del video (ej. 05:20)">
                              <input id="yt-input-foto-titulo" class="yt-input-txt" placeholder="Concepto o tema del fotograma..." value="${esc((estado.fotogramaTemporal && estado.fotogramaTemporal.titulo) || '')}">
                            </div>

                            <div style="display:flex; justify-content:space-between; align-items:center; margin-top:2px;">
                              <span style="font-size:10px; color:var(--text-muted); font-weight:600;">Explicación y fórmulas del concepto:</span>
                              <button type="button" class="yt-btn morado" id="yt-btn-ia-explicar-foto" style="padding:2px 7px; font-size:10px;" ${estado.explicacionFotogramaCargando ? 'disabled' : ''}>
                                <i class="fa-solid ${estado.explicacionFotogramaCargando ? 'fa-spinner fa-spin' : 'fa-wand-magic-sparkles'}"></i> ${estado.explicacionFotogramaCargando ? 'Explicando...' : 'Explicar con IA'}
                              </button>
                            </div>

                            ${estado.explicacionFotogramaError ? `
                              <div style="font-size:10px; color:var(--accent-red);">${esc(estado.explicacionFotogramaError)}</div>
                            ` : ''}

                            <textarea id="yt-textarea-foto-exp" class="yt-input-txt" style="min-height:75px; resize:vertical; font-family:'Fira Code',monospace;" placeholder="Anota la fórmula, concepto teórico o fragmento de código mostrado en la pantalla...">${esc((estado.fotogramaTemporal && estado.fotogramaTemporal.explicacion) || '')}</textarea>

                            <div style="display:flex; gap:6px; justify-content:flex-end; margin-top:2px;">
                              <button type="button" class="yt-btn" id="yt-btn-cancelar-foto">Cancelar</button>
                              <button type="button" class="yt-btn verde" id="yt-btn-guardar-foto"><i class="fa-solid fa-check"></i> Guardar Nota Visual</button>
                            </div>
                          </div>
                        ` : ''}

                        <div class="yt-fotogramas-lista">
                          ${fotogramas.length === 0 && !estado.fotogramaFormAbierto ? `
                            <div style="text-align:center; padding:18px 10px; color:var(--text-muted); font-size:11px; display:flex; flex-direction:column; align-items:center; gap:8px;">
                              <i class="fa-solid fa-camera" style="font-size:26px; opacity:0.35; color:var(--accent-blue);"></i>
                              <p style="margin:0; line-height:1.4;">No hay notas visuales aún. Haz clic en <b>Añadir Fotograma</b> para vincular diapositivas, capturas de código o fórmulas con su explicación técnica.</p>
                            </div>
                          ` : fotogramas.map(f => `
                            <div class="yt-fotograma-card" data-id="${esc(f.id)}">
                              <div class="yt-fotograma-card-header">
                                <button class="yt-timestamp-btn" data-segundos="${f.segundos}" title="Saltar el reproductor a ${esc(f.minuto)}">
                                  <i class="fa-solid fa-play" style="font-size:9px;"></i> ${esc(f.minuto)}
                                </button>
                                <span class="yt-fotograma-card-titulo" title="${esc(f.titulo)}">${esc(f.titulo)}</span>
                                <div style="display:flex; gap:2px;">
                                  <button class="yt-marca-btn" data-accion="insertar-cuaderno" data-id="${esc(f.id)}" title="Insertar en el cuaderno de notas"><i class="fa-regular fa-copy"></i></button>
                                  <button class="yt-marca-btn eliminar" data-accion="eliminar-fotograma" data-id="${esc(f.id)}" title="Eliminar fotograma"><i class="fa-regular fa-trash-can"></i></button>
                                </div>
                              </div>

                              <div class="yt-fotograma-card-body">
                                ${f.imagenUrl ? `
                                  <div class="yt-fotograma-thumb-click" data-accion="ampliar" data-id="${esc(f.id)}" title="Clic para ver captura ampliada">
                                    <img src="${esc(f.imagenUrl)}" alt="${esc(f.titulo)}">
                                    <span class="yt-fotograma-zoom-badge"><i class="fa-solid fa-magnifying-glass-plus"></i></span>
                                  </div>
                                ` : ''}
                                <div class="yt-fotograma-info">
                                  <div class="yt-fotograma-explicacion">${md(f.explicacion || '')}</div>
                                </div>
                              </div>
                            </div>
                          `).join('')}
                        </div>
                      ` : estado.subpestanaNotas === 'marcas' ? `
                        <!-- Subpestaña: Notaciones por Minuto -->
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
                      ` : `
                        <!-- Subpestaña: Cuaderno de Notas Markdown Libre -->
                        <div style="font-size:11px; color:var(--text-muted); display:flex; justify-content:space-between; align-items:center; margin-top:2px;">
                          <span style="font-weight:600; color:#fff;"><i class="fa-solid fa-book-open"></i> Cuaderno de Apuntes</span>
                          <div style="display:flex; gap:4px;">
                            <button class="yt-btn" id="yt-btn-insertar-timestamp" style="padding:2px 7px; font-size:10px;" title="Insertar marca [MM:SS] en el cursor"><i class="fa-regular fa-clock"></i> + [Minuto]</button>
                            <button class="yt-btn verde" id="yt-btn-guardar-archivo" style="padding:2px 7px; font-size:10px;" title="Exportar apuntes y timestamps a un archivo .md en el proyecto"><i class="fa-solid fa-file-export"></i> Exportar</button>
                          </div>
                        </div>

                        ${marcasDetectadas.length > 0 ? `
                          <div class="yt-chips-detectados">
                            <span>Saltos en apuntes:</span>
                            ${marcasDetectadas.map(mdItem => `
                              <button class="yt-chip-seek" data-segundos="${mdItem.segundos}" title="Saltar al minuto ${mdItem.minuto}">▶ ${mdItem.minuto}</button>
                            `).join('')}
                          </div>
                        ` : ''}

                        <textarea id="yt-nota" class="yt-textarea-nota" placeholder="Escribe aquí tus fórmulas, conceptos clave, código y marcas como [12:34] para saltar directamente...">${esc(notaGuardada)}</textarea>
                      `}
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
                          <div class="yt-chat-msg ${m.rol}">${m.rol === 'tutor' && typeof marked !== 'undefined' ? marked.parse(m.texto) : esc(m.texto)}</div>
                        `).join('')}
                      </div>
                      <div class="yt-chat-form">
                        <input id="yt-chat-input" class="yt-chat-input" placeholder="Pregunta sobre este video..." ${estado.tutorCargando ? 'disabled' : ''}>
                        <button class="yt-btn rojo" id="yt-chat-enviar" ${estado.tutorCargando ? 'disabled' : ''}><i class="fa-solid fa-paper-plane"></i></button>
                      </div>
                    `}
                  </div>
                </div>
              ${estado.lightboxImg ? `
                <div class="yt-lightbox-overlay" id="yt-lightbox-overlay">
                  <div class="yt-lightbox-box">
                    <div class="yt-lightbox-top">
                      <span><i class="fa-regular fa-clock" style="color:var(--accent-blue);"></i> ${esc(estado.lightboxImg.minuto || '00:00')} — ${esc(estado.lightboxImg.titulo || 'Fotograma')}</span>
                      <button class="yt-marca-btn" id="yt-btn-cerrar-lightbox" style="font-size:14px;"><i class="fa-solid fa-xmark"></i></button>
                    </div>
                    <img src="${esc(estado.lightboxImg.imagenUrl)}" class="yt-lightbox-img" alt="Fotograma ampliado">
                    ${estado.lightboxImg.explicacion ? `
                      <div class="yt-lightbox-bottom">
                        ${md(estado.lightboxImg.explicacion)}
                      </div>
                    ` : ''}
                  </div>
                </div>
              ` : ''}
              </div>
            </div>
        `;

        const btnVolver = $('yt-btn-volver') || $('yt-btn-volver-catalogo');
        if (btnVolver) {
            btnVolver.onclick = () => {
                estado.vista = 'catalogo';
                pintar();
            };
        }
        raiz.querySelectorAll('#yt-btn-volver, #yt-btn-volver-catalogo, .yt-btn-volver-catalogo').forEach(b => {
            b.onclick = () => {
                estado.vista = 'catalogo';
                pintar();
            };
        });

        const btnToggleDetalles = $('yt-btn-toggle-detalles');
        if (btnToggleDetalles) {
            btnToggleDetalles.onclick = () => {
                estado.ocultarTextoPlayer = !estado.ocultarTextoPlayer;
                localStorage.setItem('prig_yt_ocultar_texto_player', estado.ocultarTextoPlayer);
                pintar();
            };
        }

        // Abrir en navegador externo (Chrome/Firefox del SO)
        const abrirExternoHandler = (e) => {
            if (e) e.preventDefault();
            abrirEnNavegadorExterno(enlaceExterno);
        };
        const btnAbrirExtHeader = $('yt-btn-abrir-externo-header');
        if (btnAbrirExtHeader) btnAbrirExtHeader.onclick = abrirExternoHandler;
        const btnAbrirExt = $('yt-btn-abrir-externo');
        if (btnAbrirExt) btnAbrirExt.onclick = abrirExternoHandler;
        const btnAbrirExtLink = $('yt-btn-abrir-externo-link');
        if (btnAbrirExtLink) btnAbrirExtLink.onclick = abrirExternoHandler;

        // Alternar servidor de embed (youtube.com vs youtube-nocookie.com)
        const btnCambiarServidor = $('yt-btn-cambiar-servidor');
        if (btnCambiarServidor) {
            btnCambiarServidor.onclick = () => {
                estado.servidorEmbed = (estado.servidorEmbed === 'www.youtube.com')
                    ? 'www.youtube-nocookie.com'
                    : 'www.youtube.com';
                localStorage.setItem('prig_yt_embed_server', estado.servidorEmbed);
                pintar();
            };
        }

        // Copiar enlace al portapapeles
        const btnCopiarEnlace = $('yt-btn-copiar-enlace');
        if (btnCopiarEnlace) {
            btnCopiarEnlace.onclick = () => {
                navigator.clipboard.writeText(enlaceExterno).then(() => {
                    const original = btnCopiarEnlace.innerHTML;
                    btnCopiarEnlace.innerHTML = '<i class="fa-solid fa-check"></i> ¡Copiado!';
                    setTimeout(() => { btnCopiarEnlace.innerHTML = original; }, 1500);
                }).catch(() => {
                    prompt('Copia este enlace:', enlaceExterno);
                });
            };
        }

        // Interceptar enlaces directos a YouTube dentro del reproductor para abrirlos externamente si es necesario
        raiz.querySelectorAll('a[href^="https://www.youtube.com"], a[href^="https://youtu.be"]').forEach(a => {
            a.addEventListener('click', (e) => {
                e.preventDefault();
                abrirEnNavegadorExterno(a.href);
            });
        });

        raiz.querySelectorAll('.yt-lateral-tab').forEach(tb => {
            tb.onclick = () => {
                estado.pestanaLateral = tb.dataset.tab;
                pintar();
            };
        });

        // Selector de idioma de subtítulos en el reproductor integrado
        const selectIdiomaSub = $('yt-select-idioma-subtitulos');
        if (selectIdiomaSub) {
            selectIdiomaSub.onchange = () => {
                const nuevoIdioma = selectIdiomaSub.value;
                estado.idiomaSubtitulos = nuevoIdioma;
                localStorage.setItem('prig_yt_idioma_subtitulos', nuevoIdioma);
                const iframe = $('yt-iframe-player');
                const pr = obtenerProgreso(v.id);
                if (iframe) {
                    iframe.src = construirEmbedUrl(v, pr.segundos, nuevoIdioma);
                }
                if (nuevoIdioma !== 'none') {
                    cargarTranscripcion(v.id, nuevoIdioma);
                } else {
                    pintar();
                }
            };
        }

        // Subpestañas dentro de Traducción (Transcripción vs Explicaciones Guardadas)
        raiz.querySelectorAll('[data-subtab-trad]').forEach(btn => {
            btn.onclick = () => {
                estado.subpestanaTraduccion = btn.dataset.subtabTrad;
                pintar();
            };
        });

        // Alternar modo de visualización: Solo traducción vs Bilingüe
        raiz.querySelectorAll('[data-modo-trad]').forEach(btn => {
            btn.onclick = () => {
                estado.modoVistaTraduccion = btn.dataset.modoTrad;
                pintar();
            };
        });

        // Filtro de búsqueda en la transcripción
        const inputBuscarTrans = $('yt-input-buscar-transcripcion');
        if (inputBuscarTrans) {
            inputBuscarTrans.oninput = () => {
                estado.filtroTextoTraduccion = inputBuscarTrans.value;
                const f = (inputBuscarTrans.value || '').toLowerCase().trim();
                const bloques = raiz.querySelectorAll('.yt-bloque-transcripcion');
                bloques.forEach(b => {
                    const txt = b.textContent.toLowerCase();
                    b.style.display = (!f || txt.includes(f)) ? '' : 'none';
                });
            };
        }

        // Recargar o reintentar transcripción
        const btnRecargarTrans = $('yt-btn-recargar-transcripcion');
        if (btnRecargarTrans) {
            btnRecargarTrans.onclick = () => {
                cargarTranscripcion(v.id, estado.idiomaSubtitulos || 'es');
            };
        }
        const btnReintentarTrans = $('yt-btn-reintentar-transcripcion');
        if (btnReintentarTrans) {
            btnReintentarTrans.onclick = () => {
                cargarTranscripcion(v.id, estado.idiomaSubtitulos || 'es');
            };
        }
        const btnPegarExtraTrans = $('yt-btn-pegar-extra-trans');
        if (btnPegarExtraTrans) {
            btnPegarExtraTrans.onclick = () => {
                estado.mostrarInputTextoExtra = true;
                pintar();
                const ta = $('yt-textarea-extra');
                if (ta) ta.focus();
            };
        }

        // Guardar bloque completo de transcripción como explicación
        raiz.querySelectorAll('[data-accion="guardar-bloque"]').forEach(btn => {
            btn.onclick = () => {
                const start = Number(btn.dataset.start) || 0;
                const end = Number(btn.dataset.end) || 0;
                const intervalo = btn.dataset.intervalo || `${formatearSegundos(start)} - ${formatearSegundos(end)}`;
                const bloque = btn.closest('.yt-bloque-transcripcion');
                const textoEl = bloque ? bloque.querySelector('.yt-segmento-texto') : null;
                const texto = textoEl ? textoEl.textContent.trim() : '';
                if (texto) {
                    agregarExplicacionGuardada(v.id, {
                        texto,
                        intervalo,
                        startSegundos: start,
                        endSegundos: end
                    });
                    pintar();
                }
            };
        });

        // Menú contextual con clic derecho y selección flotante para resaltar en amarillo
        const cuerpoTrans = $('yt-transcripcion-cuerpo');
        if (cuerpoTrans) {
            const limpiarMenusFlotantes = () => {
                document.querySelectorAll('.yt-context-menu-flotante, .yt-seleccion-flotante').forEach(el => el.remove());
            };
            document.removeEventListener('click', limpiarMenusFlotantes);
            document.addEventListener('click', limpiarMenusFlotantes);

            cuerpoTrans.oncontextmenu = (e) => {
                e.preventDefault();
                limpiarMenusFlotantes();

                const sel = window.getSelection();
                let txtSel = sel ? sel.toString().trim() : '';
                const bloque = e.target.closest('.yt-bloque-transcripcion');
                const start = bloque ? Number(bloque.dataset.start || 0) : 0;
                const end = bloque ? Number(bloque.dataset.end || 0) : 0;
                const intervalo = bloque ? (bloque.dataset.intervalo || `${formatearSegundos(start)} - ${formatearSegundos(end)}`) : '00:00';

                if (!txtSel && bloque) {
                    const textoEl = bloque.querySelector('.yt-segmento-texto');
                    txtSel = textoEl ? textoEl.textContent.trim() : '';
                }

                if (!txtSel) return;

                const menu = document.createElement('div');
                menu.className = 'yt-context-menu-flotante';
                menu.style.left = `${Math.min(e.clientX, window.innerWidth - 260)}px`;
                menu.style.top = `${Math.min(e.clientY, window.innerHeight - 160)}px`;

                menu.innerHTML = `
                  <button class="yt-context-item resaltar" id="yt-ctx-guardar-amarillo">
                    <i class="fa-solid fa-highlighter"></i> Resaltar en amarillo y guardar [${esc(intervalo)}]
                  </button>
                  <button class="yt-context-item" id="yt-ctx-saltar-min">
                    <i class="fa-solid fa-play"></i> Saltar a este minuto (${esc(intervalo.split('-')[0].trim())})
                  </button>
                  <button class="yt-context-item" id="yt-ctx-copiar-txt">
                    <i class="fa-regular fa-copy"></i> Copiar texto
                  </button>
                `;
                document.body.appendChild(menu);

                const btnGuardarCtx = menu.querySelector('#yt-ctx-guardar-amarillo');
                if (btnGuardarCtx) {
                    btnGuardarCtx.onclick = (evt) => {
                        evt.stopPropagation();
                        agregarExplicacionGuardada(v.id, {
                            texto: txtSel,
                            intervalo: intervalo,
                            startSegundos: start,
                            endSegundos: end
                        });
                        limpiarMenusFlotantes();
                        pintar();
                    };
                }

                const btnSaltarCtx = menu.querySelector('#yt-ctx-saltar-min');
                if (btnSaltarCtx) {
                    btnSaltarCtx.onclick = (evt) => {
                        evt.stopPropagation();
                        saltarAMinuto(start, false);
                        limpiarMenusFlotantes();
                    };
                }

                const btnCopiarCtx = menu.querySelector('#yt-ctx-copiar-txt');
                if (btnCopiarCtx) {
                    btnCopiarCtx.onclick = (evt) => {
                        evt.stopPropagation();
                        navigator.clipboard.writeText(txtSel);
                        limpiarMenusFlotantes();
                    };
                }
            };

            cuerpoTrans.onmouseup = () => {
                setTimeout(() => {
                    const sel = window.getSelection();
                    if (!sel || sel.isCollapsed) return;
                    const txt = sel.toString().trim();
                    if (txt.length < 2) return;

                    limpiarMenusFlotantes();

                    const range = sel.getRangeAt(0);
                    const rect = range.getBoundingClientRect();
                    const bloque = (range.commonAncestorContainer.nodeType === 3
                        ? range.commonAncestorContainer.parentElement
                        : range.commonAncestorContainer).closest('.yt-bloque-transcripcion');

                    const start = bloque ? Number(bloque.dataset.start || 0) : 0;
                    const end = bloque ? Number(bloque.dataset.end || 0) : 0;
                    const intervalo = bloque ? (bloque.dataset.intervalo || `${formatearSegundos(start)} - ${formatearSegundos(end)}`) : '00:00';

                    const pildora = document.createElement('div');
                    pildora.className = 'yt-seleccion-flotante';
                    pildora.style.left = `${Math.max(10, Math.min(rect.left + (rect.width / 2) - 80, window.innerWidth - 180))}px`;
                    pildora.style.top = `${Math.max(10, rect.top - 36)}px`;
                    pildora.innerHTML = `<i class="fa-solid fa-highlighter"></i> Resaltar y Guardar`;

                    pildora.onclick = (evt) => {
                        evt.stopPropagation();
                        agregarExplicacionGuardada(v.id, {
                            texto: txt,
                            intervalo: intervalo,
                            startSegundos: start,
                            endSegundos: end
                        });
                        limpiarMenusFlotantes();
                        sel.removeAllRanges();
                        pintar();
                    };

                    document.body.appendChild(pildora);
                }, 15);
            };
        }

        // Acciones en tarjetas de explicaciones guardadas
        raiz.querySelectorAll('[data-accion="copiar-exp"]').forEach(btn => {
            btn.onclick = (e) => {
                e.stopPropagation();
                const exp = explicaciones.find(x => x.id === btn.dataset.id);
                if (exp) {
                    navigator.clipboard.writeText(`[${exp.intervalo}] ${exp.texto}`);
                    const orig = btn.innerHTML;
                    btn.innerHTML = '<i class="fa-solid fa-check"></i>';
                    setTimeout(() => { btn.innerHTML = orig; }, 1200);
                }
            };
        });

        raiz.querySelectorAll('[data-accion="cuaderno-exp"]').forEach(btn => {
            btn.onclick = (e) => {
                e.stopPropagation();
                const exp = explicaciones.find(x => x.id === btn.dataset.id);
                if (exp) {
                    const mdIns = `\n\n> **[${exp.intervalo}]** ${exp.texto}\n`;
                    const prev = localStorage.getItem(notaClave) || '';
                    localStorage.setItem(notaClave, (prev + mdIns).trim());
                    estado.pestanaLateral = 'notas';
                    estado.subpestanaNotas = 'cuaderno';
                    pintar();
                    alert('¡Explicación insertada en tu cuaderno de notas!');
                }
            };
        });

        raiz.querySelectorAll('[data-accion="eliminar-exp"]').forEach(btn => {
            btn.onclick = (e) => {
                e.stopPropagation();
                eliminarExplicacionGuardada(v.id, btn.dataset.id);
                pintar();
            };
        });

        const btnExpCuadernoAll = $('yt-btn-exportar-explicaciones');
        if (btnExpCuadernoAll && explicaciones.length > 0) {
            btnExpCuadernoAll.onclick = () => {
                let mdBloque = `\n\n## ⭐️ Explicaciones Destacadas (${v.titulo})\n`;
                explicaciones.forEach(exp => {
                    mdBloque += `\n- **[${exp.intervalo}]**: "${exp.texto}"\n`;
                });
                const prev = localStorage.getItem(notaClave) || '';
                localStorage.setItem(notaClave, (prev + mdBloque).trim());
                estado.pestanaLateral = 'notas';
                estado.subpestanaNotas = 'cuaderno';
                pintar();
                alert('¡Todas las explicaciones guardadas se transfirieron a tu cuaderno de notas!');
            };
        }

        // Clic en botones de reproducir intervalo (en tarjetas o header)
        raiz.querySelectorAll('.yt-btn-reproducir-intervalo').forEach(btn => {
            btn.onclick = (e) => {
                e.stopPropagation();
                const seg = Number(btn.dataset.segundos) || 0;
                saltarAMinuto(seg, false);
                estado.subpestanaTraduccion = 'transcripcion';
                pintar();
                setTimeout(() => {
                    const bloque = document.querySelector(`.yt-bloque-transcripcion[data-start="${seg}"]`);
                    if (bloque) {
                        bloque.scrollIntoView({ behavior: 'smooth', block: 'center' });
                        bloque.classList.add('activo');
                        setTimeout(() => bloque.classList.remove('activo'), 2500);
                    }
                }, 50);
            };
        });

        // Clic en marcas amarillas ya existentes dentro de la transcripción
        raiz.querySelectorAll('.yt-resaltado-amarillo').forEach(mark => {
            mark.onclick = (e) => {
                e.stopPropagation();
                const expId = mark.dataset.expId;
                const exp = explicaciones.find(x => x.id === expId);
                if (exp && exp.startSegundos !== undefined) {
                    saltarAMinuto(exp.startSegundos, false);
                    mark.classList.add('pulsar');
                    setTimeout(() => mark.classList.remove('pulsar'), 2000);
                }
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

        // Subpestañas de Notas
        raiz.querySelectorAll('.yt-subtab-btn').forEach(sb => {
            sb.onclick = () => {
                estado.subpestanaNotas = sb.dataset.subtab;
                pintar();
            };
        });

        // Formulario y acciones de Fotogramas
        const btnToggleFoto = $('yt-btn-toggle-form-foto');
        if (btnToggleFoto) {
            btnToggleFoto.onclick = () => {
                estado.fotogramaFormAbierto = !estado.fotogramaFormAbierto;
                if (estado.fotogramaFormAbierto && !estado.fotogramaTemporal) {
                    const pr = obtenerProgreso(v.id);
                    estado.fotogramaTemporal = {
                        minuto: pr.ultimoMinuto || '00:00',
                        segundos: pr.segundos || 0,
                        imagenUrl: obtenerKeyframeUrl(v.id, 'hqdefault'),
                        titulo: '',
                        explicacion: ''
                    };
                }
                pintar();
            };
        }

        raiz.querySelectorAll('.yt-btn-thumb-opt[data-keyframe]').forEach(btn => {
            btn.onclick = () => {
                estado.fotogramaTemporal = estado.fotogramaTemporal || {};
                estado.fotogramaTemporal.imagenUrl = obtenerKeyframeUrl(v.id, btn.dataset.keyframe);
                pintar();
            };
        });

        const btnTriggerUpload = $('yt-btn-trigger-upload');
        const fileUploadFotograma = $('yt-file-upload-fotograma');
        if (btnTriggerUpload && fileUploadFotograma) {
            btnTriggerUpload.onclick = () => fileUploadFotograma.click();
            fileUploadFotograma.onchange = (e) => {
                const f = e.target.files && e.target.files[0];
                if (f) {
                    const reader = new FileReader();
                    reader.onload = (evt) => {
                        estado.fotogramaTemporal = estado.fotogramaTemporal || {};
                        estado.fotogramaTemporal.imagenUrl = evt.target.result;
                        pintar();
                    };
                    reader.readAsDataURL(f);
                }
            };
        }

        const btnIaExplicarFoto = $('yt-btn-ia-explicar-foto');
        if (btnIaExplicarFoto) {
            btnIaExplicarFoto.onclick = () => {
                const min = $('yt-input-foto-min') ? $('yt-input-foto-min').value.trim() : '00:00';
                const tit = $('yt-input-foto-titulo') ? $('yt-input-foto-titulo').value.trim() : '';
                const exp = $('yt-textarea-foto-exp') ? $('yt-textarea-foto-exp').value.trim() : '';
                estado.fotogramaTemporal = estado.fotogramaTemporal || {};
                estado.fotogramaTemporal.minuto = min;
                estado.fotogramaTemporal.titulo = tit;
                estado.fotogramaTemporal.explicacion = exp;
                solicitarExplicacionFotograma(min, tit, exp);
            };
        }

        const inputFotoMin = $('yt-input-foto-min');
        if (inputFotoMin) inputFotoMin.oninput = () => { if (estado.fotogramaTemporal) estado.fotogramaTemporal.minuto = inputFotoMin.value; };
        const inputFotoTit = $('yt-input-foto-titulo');
        if (inputFotoTit) inputFotoTit.oninput = () => { if (estado.fotogramaTemporal) estado.fotogramaTemporal.titulo = inputFotoTit.value; };
        const textareaFotoExp = $('yt-textarea-foto-exp');
        if (textareaFotoExp) textareaFotoExp.oninput = () => { if (estado.fotogramaTemporal) estado.fotogramaTemporal.explicacion = textareaFotoExp.value; };

        const btnCancelFoto = $('yt-btn-cancelar-foto');
        if (btnCancelFoto) {
            btnCancelFoto.onclick = () => {
                estado.fotogramaFormAbierto = false;
                estado.fotogramaTemporal = null;
                pintar();
            };
        }

        const btnGuardarFoto = $('yt-btn-guardar-foto');
        if (btnGuardarFoto) {
            btnGuardarFoto.onclick = () => {
                const minStr = (inputFotoMin ? inputFotoMin.value.trim() : '') || '00:00';
                const tit = (inputFotoTit ? inputFotoTit.value.trim() : '') || 'Momento clave';
                const exp = (textareaFotoExp ? textareaFotoExp.value.trim() : '');
                const img = (estado.fotogramaTemporal && estado.fotogramaTemporal.imagenUrl) || obtenerKeyframeUrl(v.id, 'hqdefault');
                const seg = parsearTimestamp(minStr);
                const lista = leerFotogramas(v.id);
                lista.push({
                    id: 'f_' + Date.now() + '_' + Math.floor(Math.random() * 1000),
                    minuto: formatearSegundos(seg),
                    segundos: seg,
                    titulo: tit,
                    explicacion: exp,
                    imagenUrl: img,
                    fecha: Date.now()
                });
                lista.sort((a, b) => a.segundos - b.segundos);
                guardarFotogramas(v.id, lista);
                estado.fotogramaFormAbierto = false;
                estado.fotogramaTemporal = null;
                pintar();
            };
        }

        // Clic en fotogramas para ampliar
        raiz.querySelectorAll('[data-accion="ampliar"]').forEach(thumb => {
            thumb.onclick = () => {
                const item = fotogramas.find(x => x.id === thumb.dataset.id);
                if (item) {
                    estado.lightboxImg = item;
                    pintar();
                }
            };
        });

        // Insertar fotograma en cuaderno
        raiz.querySelectorAll('[data-accion="insertar-cuaderno"]').forEach(btn => {
            btn.onclick = () => {
                const item = fotogramas.find(x => x.id === btn.dataset.id);
                if (item) {
                    let mdBloque = `\n\n### 📸 [${item.minuto}] ${item.titulo}\n`;
                    if (item.imagenUrl) mdBloque += `![${item.titulo}](${item.imagenUrl})\n`;
                    if (item.explicacion) mdBloque += `\n> ${item.explicacion.replace(/\n/g, '\n> ')}\n`;
                    const prev = localStorage.getItem(notaClave) || '';
                    localStorage.setItem(notaClave, (prev + mdBloque).trim());
                    estado.subpestanaNotas = 'cuaderno';
                    pintar();
                    alert('¡Fotograma insertado en tu cuaderno de notas!');
                }
            };
        });

        // Eliminar fotograma
        raiz.querySelectorAll('[data-accion="eliminar-fotograma"]').forEach(btn => {
            btn.onclick = () => {
                const lista = leerFotogramas(v.id).filter(x => x.id !== btn.dataset.id);
                guardarFotogramas(v.id, lista);
                pintar();
            };
        });

        // Cerrar lightbox
        const btnCerrarLb = $('yt-btn-cerrar-lightbox');
        if (btnCerrarLb) btnCerrarLb.onclick = () => { estado.lightboxImg = null; pintar(); };
        const overlayLb = $('yt-lightbox-overlay');
        if (overlayLb) {
            overlayLb.onclick = (e) => {
                if (e.target === overlayLb) {
                    estado.lightboxImg = null;
                    pintar();
                }
            };
        }

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
                const fotogramasActuales = leerFotogramas(v.id);

                if (!contenido.trim() && marcasActuales.length === 0 && fotogramasActuales.length === 0) {
                    return alert('Escribe algunos apuntes o añade fotogramas / marcas antes de exportar.');
                }

                let cuerpoMd = `# Apuntes de Estudio: ${v.titulo}\n\n`;
                cuerpoMd += `- **Canal**: ${v.canal || 'YouTube'}\n`;
                cuerpoMd += `- **URL**: https://www.youtube.com/watch?v=${v.id}\n`;
                cuerpoMd += `- **Avance**: ${progActual.porcentaje}% (${progActual.estado === 'completado' ? 'Completado' : 'En progreso'})\n`;
                cuerpoMd += `- **Última posición**: ${progActual.ultimoMinuto || '00:00'}\n\n`;

                if (fotogramasActuales.length > 0) {
                    cuerpoMd += `## 📸 Fotogramas y Notas Visuales\n\n`;
                    fotogramasActuales.forEach(f => {
                        cuerpoMd += `### [${f.minuto}](https://www.youtube.com/watch?v=${v.id}&t=${f.segundos}s) — ${f.titulo}\n\n`;
                        if (f.imagenUrl) cuerpoMd += `![${f.titulo}](${f.imagenUrl})\n\n`;
                        if (f.explicacion) cuerpoMd += `${f.explicacion}\n\n`;
                    });
                }

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
                        headers: { 'Content-Type': 'application/json' },
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

    function actualizarStreamingTutor(texto) {
        const contenedor = $('yt-chat-mensajes');
        if (!contenedor) return;
        const msgs = contenedor.querySelectorAll('.yt-chat-msg.tutor');
        if (msgs.length > 0) {
            const ultimo = msgs[msgs.length - 1];
            if (typeof marked !== 'undefined') {
                ultimo.innerHTML = marked.parse(texto);
            } else {
                ultimo.textContent = texto;
            }
            contenedor.scrollTop = contenedor.scrollHeight;
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
            const modeloActivo = (window.aiChatMgr && window.aiChatMgr.modelSelect && window.aiChatMgr.modelSelect.value) ? window.aiChatMgr.modelSelect.value : undefined;
            const res = await fetch('/api/ai/chat', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    prompt: `El usuario está viendo el video de YouTube educativo: "${v.titulo}" del canal "${v.canal}".\nConsulta del alumno: ${pregunta}`,
                    model: modeloActivo,
                    mode: 'tutor'
                })
            });

            if (!res.ok) {
                const errDetail = await window.prigErrorDetail(res);
                throw new Error(errDetail);
            }

            const reader = res.body.getReader();
            const decoder = new TextDecoder('utf-8');
            let acumulado = '';
            respItem.texto = '';

            while (true) {
                const { done, value } = await reader.read();
                if (done) break;
                acumulado += decoder.decode(value, { stream: true });
                respItem.texto = acumulado;
                actualizarStreamingTutor(acumulado);
            }

            if (!respItem.texto.trim()) {
                respItem.texto = 'No se recibió respuesta del modelo.';
                actualizarStreamingTutor(respItem.texto);
            }
        } catch (e) {
            respItem.texto = `*Error al consultar al tutor: ${e.message}*`;
            actualizarStreamingTutor(respItem.texto);
        } finally {
            estado.tutorCargando = false;
            pintar();
        }
    }

    function abrir(opciones = {}) {
        inicializarCursosPersonalizados();
        if (window.workArea) {
            window.workArea.abrirHerramienta('modal-youtube', 'YouTube', 'fa-brands fa-youtube');
        } else {
            const m = $('modal-youtube');
            if (m) m.style.display = 'flex';
        }
        if (opciones.busqueda) {
            ejecutarBusquedaYt(opciones.busqueda, opciones.tipo || 'todos', opciones.slug || null);
            return;
        }
        if (opciones.videoId || opciones.url || opciones.id) {
            const id = extraerVideoId(opciones.videoId || opciones.url || opciones.id);
            if (id) {
                const vid = VIDEOS_CURADOS.find(x => x.id === id) || { id, titulo: 'Video de YouTube', canal: 'YouTube' };
                reproducir(vid);
                if (opciones.tab) {
                    estado.pestanaLateral = opciones.tab;
                    if (opciones.subtab) estado.subpestanaNotas = opciones.subtab;
                }
                if (opciones.segundos != null) {
                    setTimeout(() => saltarAMinuto(opciones.segundos, false), 450);
                }
                pintar();
                return;
            }
        }
        if (opciones.tab) {
            estado.pestanaLateral = opciones.tab;
            if (opciones.subtab) estado.subpestanaNotas = opciones.subtab;
        }
        pintar();
        cargarCursosJson();
    }

    async function cargarCursosJson() {
        inicializarCursosPersonalizados();
        try {
            const r = await fetch('/static/data/cursos_youtube.json');
            if (r.ok) {
                const lista = await r.json();
                if (Array.isArray(lista)) {
                    let nuevo = false;
                    lista.forEach(c => {
                        const existente = VIDEOS_CURADOS.find(v => v.id === c.id);
                        if (!existente) {
                            VIDEOS_CURADOS.push(c);
                            nuevo = true;
                        } else {
                            if (c.universidad && !existente.universidad) { existente.universidad = c.universidad; nuevo = true; }
                            if (c.playlist && !existente.playlist) { existente.playlist = c.playlist; nuevo = true; }
                        }
                    });
                    if (nuevo && estado.vista === 'catalogo') pintar();
                }
            }
        } catch (e) { /* usa lista interna */ }
    }

    function configurarPasteGlobal() {
        window.addEventListener('paste', (e) => {
            const modalYt = $('modal-youtube');
            if (!modalYt || modalYt.style.display === 'none') return;
            if (estado.vista !== 'reproductor' || estado.pestanaLateral !== 'notas' || estado.subpestanaNotas !== 'fotogramas') return;
            const items = (e.clipboardData || (e.originalEvent && e.originalEvent.clipboardData) || {}).items;
            if (!items) return;
            for (let i = 0; i < items.length; i++) {
                const item = items[i];
                if (item.kind === 'file' && item.type.indexOf('image/') !== -1) {
                    const blob = item.getAsFile();
                    const reader = new FileReader();
                    reader.onload = (event) => {
                        const v = estado.videoActual;
                        const prog = v ? obtenerProgreso(v.id) : { ultimoMinuto: '00:00', segundos: 0 };
                        estado.fotogramaFormAbierto = true;
                        estado.fotogramaTemporal = estado.fotogramaTemporal || {
                            minuto: prog.ultimoMinuto || '00:00',
                            segundos: prog.segundos || 0,
                            titulo: '',
                            explicacion: ''
                        };
                        estado.fotogramaTemporal.imagenUrl = event.target.result;
                        pintar();
                    };
                    reader.readAsDataURL(blob);
                    e.preventDefault();
                    break;
                }
            }
        });
    }

    document.addEventListener('prig:herramienta-abierta', (e) => {
        if (e.detail && e.detail.modalId === 'modal-youtube') {
            pintar();
            cargarCursosJson();
        }
    });

    function configurarClickFueraSugerencias() {
        document.addEventListener('click', (e) => {
            if (!e.target.closest('.yt-search-container')) {
                if (estado.sugerenciasAbiertas) {
                    estado.sugerenciasAbiertas = false;
                    const box = $('yt-sugerencias-box');
                    if (box) box.style.display = 'none';
                }
            }
        });
    }

    configurarPasteGlobal();
    configurarClickFueraSugerencias();
    inicializarCursosPersonalizados();

    window.YouTubeHub = {
        abrir,
        reproducir,
        buscar: ejecutarBusquedaYt,
        saltarAMinuto,
        pintar,
        obtenerTodasLasNotas,
        leerFotogramas,
        guardarFotogramas,
        guardarCursoEnCatalogo,
        estado,
        VIDEOS_CURADOS,
        PALABRAS_REGISTRADAS_DEF
    };
})();
