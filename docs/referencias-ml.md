# Referencias de Machine Learning

Libros, papers, formularios (cheat sheets), apuntes y documentación de los modelos de machine learning, ordenados por familia de modelo. Solo enlaces oficiales y gratuitos; los que son de pago llevan la marca 💲. Se consultan desde Prig en **Biblioteca → 🔗 REFERENCIAS ML**, y el chat de cualquier sección las cita cuando la pregunta trata de su tema.

Generado desde `frontend/data/referencias_ml.json` (387 referencias). Para agregar una: añadirla al JSON (con `arxiv` si es de arXiv) y correr `python backend/referencias_ml.py --completar --verificar --markdown`.

## Índice

- [Fundamentos y teoría del aprendizaje](#fundamentos-y-teoria-del-aprendizaje) (19)
- [Matemáticas para ML (álgebra, cálculo, probabilidad)](#matematicas-para-ml-algebra-calculo-probabilidad) (15)
- [Optimización](#optimizacion) (18)
- [Regresión lineal, regularización y GLM](#regresion-lineal-regularizacion-y-glm) (9)
- [Modelos probabilísticos y bayesianos](#modelos-probabilisticos-y-bayesianos) (18)
- [SVM y métodos de kernel](#svm-y-metodos-de-kernel) (8)
- [Árboles de decisión y ensembles](#arboles-de-decision-y-ensembles) (14)
- [Clustering, reducción de dimensión y anomalías](#clustering-reduccion-de-dimension-y-anomalias) (17)
- [Redes neuronales y entrenamiento profundo](#redes-neuronales-y-entrenamiento-profundo) (27)
- [Redes convolucionales y visión por computadora](#redes-convolucionales-y-vision-por-computadora) (27)
- [Redes recurrentes y modelos de secuencia](#redes-recurrentes-y-modelos-de-secuencia) (15)
- [Procesamiento de lenguaje y embeddings](#procesamiento-de-lenguaje-y-embeddings) (13)
- [Transformers y modelos de lenguaje (LLM)](#transformers-y-modelos-de-lenguaje-llm) (46)
- [Modelos generativos (VAE, GAN, flujos, difusión)](#modelos-generativos-vae-gan-flujos-difusion) (28)
- [Aprendizaje por refuerzo](#aprendizaje-por-refuerzo) (28)
- [Redes neuronales sobre grafos](#redes-neuronales-sobre-grafos) (15)
- [Series temporales y pronóstico](#series-temporales-y-pronostico) (16)
- [Sistemas de recomendación](#sistemas-de-recomendacion) (11)
- [Interpretabilidad, explicabilidad y causalidad](#interpretabilidad-explicabilidad-y-causalidad) (17)
- [Práctica: evaluación, datos y MLOps](#practica-evaluacion-datos-y-mlops) (26)

## Fundamentos y teoría del aprendizaje

### Libro

- **[Pattern Recognition and Machine Learning](https://www.microsoft.com/en-us/research/publication/pattern-recognition-machine-learning/)** · Christopher M. Bishop (2006) · [PDF](https://www.microsoft.com/en-us/research/uploads/prod/2006/01/Bishop-Pattern-Recognition-and-Machine-Learning-2006.pdf) — Clásico del enfoque probabilístico y bayesiano del ML. PDF gratuito publicado por Microsoft Research.
- **[The Elements of Statistical Learning (2nd ed.)](https://hastie.su.domains/ElemStatLearn/)** · Trevor Hastie, Robert Tibshirani, Jerome Friedman (2009) — El texto de referencia del aprendizaje estadístico: modelos lineales, regularización, árboles, boosting, SVM, clustering. PDF oficial gratuito.
- **[Understanding Machine Learning: From Theory to Algorithms](https://www.cs.huji.ac.il/~shais/UnderstandingMachineLearning/understanding-machine-learning-theory-algorithms.pdf)** · Shai Shalev-Shwartz, Shai Ben-David (2014) — Teoría del aprendizaje (PAC, dimensión VC) conectada con algoritmos. PDF gratuito de los autores.
- **[A Course in Machine Learning](http://ciml.info/)** · Hal Daumé III (2017) — Introducción clara y breve a los algoritmos clásicos. Gratuito.
- **[Foundations of Machine Learning (2nd ed.)](https://cs.nyu.edu/~mohri/mlbook/)** · Mehryar Mohri, Afshin Rostamizadeh, Ameet Talwalkar (2018) — Teoría del aprendizaje con rigor: complejidad de Rademacher, boosting, kernels. Edición en acceso abierto.
- **[Patterns, Predictions, and Actions: A Story about Machine Learning](https://mlstory.org/)** · Moritz Hardt, Benjamin Recht (2022) · [PDF](https://mlstory.org/pdf/patterns.pdf) — Curso moderno de posgrado: predicción, generalización, datasets, causalidad y decisión.
- **[Probabilistic Machine Learning: An Introduction](https://probml.github.io/pml-book/book1.html)** · Kevin P. Murphy (2022) — Primer tomo de Murphy: fundamentos, modelos lineales, redes y métodos no paramétricos. Borrador en PDF gratuito.
- **[An Introduction to Statistical Learning (with Applications in R / Python)](https://www.statlearning.com/)** · Gareth James, Daniela Witten, Trevor Hastie, Robert Tibshirani et al. (2023) — La versión introductoria de ESL, con laboratorios en R y en Python. PDFs oficiales gratuitos.

### Paper

- **[A theory of the learnable](https://doi.org/10.1145/1968.1972)** 💲 · Leslie G. Valiant (1984) — El origen del aprendizaje PAC.
- **[Neural Networks and the Bias/Variance Dilemma](https://doi.org/10.1162/neco.1992.4.1.1)** 💲 · Stuart Geman, Elie Bienenstock, René Doursat (1992) — El análisis clásico del compromiso sesgo-varianza.
- **[No free lunch theorems for optimization](https://doi.org/10.1109/4235.585893)** 💲 · David H. Wolpert, William G. Macready (1997) — Ningún algoritmo es mejor en promedio sobre todos los problemas.
- **[Understanding deep learning requires rethinking generalization](https://arxiv.org/abs/1611.03530)** · Chiyuan Zhang, Samy Bengio, Moritz Hardt, Benjamin Recht et al. (2016) · [PDF](https://arxiv.org/pdf/1611.03530) — Las redes profundas memorizan etiquetas aleatorias: la teoría clásica no explica su generalización.
- **[Reconciling modern machine learning practice and the bias-variance trade-off](https://arxiv.org/abs/1812.11118)** · Mikhail Belkin, Daniel Hsu, Siyuan Ma, Soumik Mandal (2018) · [PDF](https://arxiv.org/pdf/1812.11118) — Doble descenso: el error vuelve a bajar pasado el umbral de interpolación.
- **[Deep Double Descent: Where Bigger Models and More Data Hurt](https://arxiv.org/abs/1912.02292)** · Preetum Nakkiran, Gal Kaplun, Yamini Bansal, Tristan Yang et al. (2019) · [PDF](https://arxiv.org/pdf/1912.02292)

### Survey / tutorial académico

- **[Statistical Learning Theory: Models, Concepts, and Results](https://arxiv.org/abs/0810.4752)** · Ulrike von Luxburg, Bernhard Schoelkopf (2008) · [PDF](https://arxiv.org/pdf/0810.4752) — Panorama de la teoría estadística del aprendizaje (von Luxburg y Schölkopf).

### Formulario / cheat sheet

- **[Stanford CS229 y CS230: hojas de fórmulas en PDF (varios idiomas, incluido español)](https://github.com/afshinea/stanford-cs-229-machine-learning)** · Afshine Amidi, Shervine Amidi (2019) — Repositorio con los PDF de todas las hojas de CS229 y sus traducciones (es/ incluido).

### Apuntes de curso

- **[CS229 Lecture Notes (Machine Learning)](https://cs229.stanford.edu/main_notes.pdf)** · Andrew Ng, Tengyu Ma (2023) — Apuntes completos del curso CS229 de Stanford: aprendizaje supervisado, no supervisado, teoría y refuerzo.

### Curso en línea

- **[Machine Learning Crash Course](https://developers.google.com/machine-learning/crash-course)** · Google (2024) — Curso práctico de Google con ejercicios interactivos.

### Artículo divulgativo

- **[Statistical Modeling: The Two Cultures](https://doi.org/10.1214/ss/1009213726)** · Leo Breiman (2001) — El ensayo que contrapone modelado de datos y modelado algorítmico.

## Matemáticas para ML (álgebra, cálculo, probabilidad)

### Libro

- **[Information Theory, Inference, and Learning Algorithms](https://www.inference.org.uk/itila/book.html)** · David J. C. MacKay (2003) — Teoría de la información, inferencia bayesiana y redes neuronales. PDF gratuito del autor.
- **[Introduction to Applied Linear Algebra: Vectors, Matrices, and Least Squares](https://web.stanford.edu/~boyd/vmls/)** · Stephen Boyd, Lieven Vandenberghe (2018) · [PDF](https://web.stanford.edu/~boyd/vmls/vmls.pdf) — Álgebra lineal aplicada hasta mínimos cuadrados y ajuste de modelos. PDF gratuito.
- **[Introduction to Probability (2nd ed.)](http://probabilitybook.net/)** · Joseph K. Blitzstein, Jessica Hwang (2019) — El libro de Stat 110 de Harvard; PDF gratuito en la página del curso.
- **[OpenIntro Statistics (4th ed.)](https://www.openintro.org/book/os/)** · David Diez, Mine Çetinkaya-Rundel, Christopher Barr (2019) — Estadística introductoria en acceso abierto.
- **[Mathematics for Machine Learning](https://mml-book.github.io/)** · Marc Peter Deisenroth, A. Aldo Faisal, Cheng Soon Ong (2020) · [PDF](https://mml-book.github.io/book/mml-book.pdf) — Álgebra lineal, cálculo vectorial, probabilidad y optimización aplicadas a regresión, PCA, GMM y SVM. PDF gratuito.
- **[Linear Algebra Done Right (4th ed.)](https://linear.axler.net/)** · Sheldon Axler (2024) — Álgebra lineal centrada en operadores. Edición en acceso abierto.

### Paper

- **[The Matrix Calculus You Need For Deep Learning](https://arxiv.org/abs/1802.01528)** · Terence Parr, Jeremy Howard (2018) · [PDF](https://arxiv.org/pdf/1802.01528) — Cálculo matricial explicado paso a paso para entender backpropagation.

### Formulario / cheat sheet

- **[The Matrix Cookbook](https://www.math.uwaterloo.ca/~hwolkowi/matrixcookbook.pdf)** · Kaare Brandt Petersen, Michael Syskind Pedersen (2012) — Formulario de identidades, derivadas e inversas de matrices: la referencia rápida del álgebra matricial.
- **[Probability Cheatsheet (Stat 110)](https://github.com/wzchen/probability_cheatsheet)** · William Chen, Joseph K. Blitzstein (2015) — Diez páginas con todas las fórmulas de probabilidad de Stat 110.
- **[CS229 Refresher: Linear Algebra and Calculus](https://stanford.edu/~shervine/teaching/cs-229/refresher-algebra-calculus)** · Afshine Amidi, Shervine Amidi (2018) — Repaso condensado de álgebra lineal y cálculo matricial.
- **[CS229 Refresher: Probabilities and Statistics](https://stanford.edu/~shervine/teaching/cs-229/refresher-probabilities-statistics)** · Afshine Amidi, Shervine Amidi (2018) — Repaso condensado de probabilidad y estadística para CS229 (también en español).

### Apuntes de curso

- **[Review of Probability Theory (CS229)](https://cs229.stanford.edu/section/cs229-prob.pdf)** · Arian Maleki, Tom Do (2011) — Repaso de probabilidad del curso CS229.
- **[Linear Algebra Review and Reference (CS229)](https://cs229.stanford.edu/section/cs229-linalg.pdf)** · Zico Kolter, Chuong Do (2015) — Repaso de álgebra lineal del curso CS229.

### Artículo divulgativo

- **[Visual Information Theory](https://colah.github.io/posts/2015-09-Visual-Information/)** · Christopher Olah (2015) — Entropía, entropía cruzada y divergencia KL con diagramas.
- **[Seeing Theory: A visual introduction to probability and statistics](https://seeing-theory.brown.edu/)** · Daniel Kunin, Jingru Guo, Tyler Dae Devlin, Daniel Xiang (2018) — Probabilidad y estadística con visualizaciones interactivas.

## Optimización

### Libro

- **[Convex Optimization](https://web.stanford.edu/~boyd/cvxbook/)** · Stephen Boyd, Lieven Vandenberghe (2004) · [PDF](https://web.stanford.edu/~boyd/cvxbook/bv_cvxbook.pdf) — El texto de referencia de optimización convexa. PDF gratuito.
- **[Algorithms for Optimization](https://algorithmsbook.com/optimization/)** · Mykel J. Kochenderfer, Tim A. Wheeler (2019) — Algoritmos de optimización con código en Julia. PDF gratuito.

### Paper

- **[A Stochastic Approximation Method](https://doi.org/10.1214/aoms/1177729586)** · Herbert Robbins, Sutton Monro (1951) — El origen del descenso de gradiente estocástico.
- **[On the limited memory BFGS method for large scale optimization](https://doi.org/10.1007/BF01589116)** 💲 · Dong C. Liu, Jorge Nocedal (1989)
- **[Adaptive Subgradient Methods for Online Learning and Stochastic Optimization](https://jmlr.org/papers/v12/duchi11a.html)** · John Duchi, Elad Hazan, Yoram Singer (2011) — AdaGrad: pasos adaptativos por coordenada.
- **[Practical recommendations for gradient-based training of deep architectures](https://arxiv.org/abs/1206.5533)** · Yoshua Bengio (2012) · [PDF](https://arxiv.org/pdf/1206.5533) — Recomendaciones prácticas de Bengio para entrenar redes profundas.
- **[On the importance of initialization and momentum in deep learning](https://proceedings.mlr.press/v28/sutskever13.html)** · Ilya Sutskever, James Martens, George Dahl, Geoffrey Hinton (2013)
- **[Adam: A Method for Stochastic Optimization](https://arxiv.org/abs/1412.6980)** · Diederik P. Kingma, Jimmy Ba (2014) · [PDF](https://arxiv.org/pdf/1412.6980) — El optimizador Adam: momentos adaptativos de primer y segundo orden.
- **[Cyclical Learning Rates for Training Neural Networks](https://arxiv.org/abs/1506.01186)** · Leslie N. Smith (2015) · [PDF](https://arxiv.org/pdf/1506.01186)
- **[SGDR: Stochastic Gradient Descent with Warm Restarts](https://arxiv.org/abs/1608.03983)** · Ilya Loshchilov, Frank Hutter (2016) · [PDF](https://arxiv.org/pdf/1608.03983)
- **[Accurate, Large Minibatch SGD: Training ImageNet in 1 Hour](https://arxiv.org/abs/1706.02677)** · Priya Goyal, Piotr Dollár, Ross Girshick, Pieter Noordhuis et al. (2017) · [PDF](https://arxiv.org/pdf/1706.02677)
- **[Decoupled Weight Decay Regularization](https://arxiv.org/abs/1711.05101)** · Ilya Loshchilov, Frank Hutter (2017) · [PDF](https://arxiv.org/pdf/1711.05101) — AdamW: separa el decaimiento de pesos del paso adaptativo.
- **[Visualizing the Loss Landscape of Neural Nets](https://arxiv.org/abs/1712.09913)** · Hao Li, Zheng Xu, Gavin Taylor, Christoph Studer et al. (2017) · [PDF](https://arxiv.org/pdf/1712.09913)
- **[Sharpness-Aware Minimization for Efficiently Improving Generalization](https://arxiv.org/abs/2010.01412)** · Pierre Foret, Ariel Kleiner, Hossein Mobahi, Behnam Neyshabur (2020) · [PDF](https://arxiv.org/pdf/2010.01412)
- **[Symbolic Discovery of Optimization Algorithms](https://arxiv.org/abs/2302.06675)** · Xiangning Chen, Chen Liang, Da Huang, Esteban Real et al. (2023) · [PDF](https://arxiv.org/pdf/2302.06675) — El optimizador Lion, encontrado por búsqueda de programas.

### Survey / tutorial académico

- **[An overview of gradient descent optimization algorithms](https://arxiv.org/abs/1609.04747)** · Sebastian Ruder (2016) · [PDF](https://arxiv.org/pdf/1609.04747) — Resumen de las variantes de descenso de gradiente (Ruder).
- **[Optimization Methods for Large-Scale Machine Learning](https://arxiv.org/abs/1606.04838)** · Léon Bottou, Frank E. Curtis, Jorge Nocedal (2016) · [PDF](https://arxiv.org/pdf/1606.04838) — Revisión de Bottou, Curtis y Nocedal sobre SGD y sus variantes para ML a gran escala.

### Artículo divulgativo

- **[Why Momentum Really Works](https://distill.pub/2017/momentum/)** · Gabriel Goh (2017) — Explicación interactiva de por qué y cuándo acelera el momentum.

## Regresión lineal, regularización y GLM

### Paper

- **[The Regression Analysis of Binary Sequences](https://doi.org/10.1111/j.2517-6161.1958.tb00292.x)** 💲 · David R. Cox (1958) — Origen de la regresión logística.
- **[Ridge Regression: Biased Estimation for Nonorthogonal Problems](https://doi.org/10.1080/00401706.1970.10488634)** 💲 · Arthur E. Hoerl, Robert W. Kennard (1970) — La regresión ridge para problemas mal condicionados.
- **[Generalized Linear Models](https://doi.org/10.2307/2344614)** 💲 · John A. Nelder, Robert W. M. Wedderburn (1972) — El paper que define los modelos lineales generalizados.
- **[Regression Shrinkage and Selection Via the Lasso](https://doi.org/10.1111/j.2517-6161.1996.tb02080.x)** 💲 · Robert Tibshirani (1996) — El paper del Lasso: regularización L1 que produce modelos dispersos.
- **[Least Angle Regression](https://arxiv.org/abs/math/0406456)** · Bradley Efron, Trevor Hastie, Iain Johnstone, Robert Tibshirani (2004) · [PDF](https://arxiv.org/pdf/math/0406456) — LARS: el camino completo de soluciones del Lasso.
- **[Regularization and Variable Selection via the Elastic Net](https://doi.org/10.1111/j.1467-9868.2005.00503.x)** 💲 · Hui Zou, Trevor Hastie (2005) — Elastic Net: combina L1 y L2.
- **[Regularization Paths for Generalized Linear Models via Coordinate Descent](https://www.jstatsoft.org/article/view/v033i01)** · Jerome Friedman, Trevor Hastie, Rob Tibshirani (2010) — glmnet: descenso por coordenadas para GLM regularizados.

### Formulario / cheat sheet

- **[CS229 Cheatsheet: Supervised Learning](https://stanford.edu/~shervine/teaching/cs-229/cheatsheet-supervised-learning)** · Afshine Amidi, Shervine Amidi (2018) — Hoja de fórmulas de aprendizaje supervisado: modelos lineales, GLM, SVM, generativos, árboles y teoría.
- **[CS229 Hoja de referencia: Aprendizaje supervisado (español)](https://stanford.edu/~shervine/l/es/teaching/cs-229/hoja-referencia-aprendizaje-supervisado)** · Afshine Amidi, Shervine Amidi (2018) — La hoja de fórmulas de aprendizaje supervisado traducida al español.

## Modelos probabilísticos y bayesianos

### Libro

- **[Gaussian Processes for Machine Learning](https://gaussianprocess.org/gpml/)** · Carl Edward Rasmussen, Christopher K. I. Williams (2006) · [PDF](https://gaussianprocess.org/gpml/chapters/RW.pdf) — El libro de referencia de procesos gaussianos. PDF gratuito.
- **[Bayesian Reasoning and Machine Learning](http://web4.cs.ucl.ac.uk/staff/D.Barber/pmwiki/pmwiki.php?n=Brml.HomePage)** · David Barber (2012) — Modelos gráficos y razonamiento bayesiano aplicado al ML. Versión en línea gratuita.
- **[Bayesian Data Analysis (3rd ed.)](http://www.stat.columbia.edu/~gelman/book/BDA3.pdf)** · Andrew Gelman, John B. Carlin, Hal S. Stern, David B. Dunson et al. (2013) — La referencia del análisis bayesiano aplicado. PDF gratuito para uso no comercial.
- **[Probabilistic Programming and Bayesian Methods for Hackers](https://camdavidsonpilon.github.io/Probabilistic-Programming-and-Bayesian-Methods-for-Hackers/)** · Cameron Davidson-Pilon (2015) — Métodos bayesianos desde la programación, con cuadernos ejecutables.
- **[Probabilistic Machine Learning: Advanced Topics](https://probml.github.io/pml-book/book2.html)** · Kevin P. Murphy (2023) — Segundo tomo: inferencia, modelos generativos, causalidad y decisión.

### Paper

- **[A New Approach to Linear Filtering and Prediction Problems](https://doi.org/10.1115/1.3662552)** 💲 · Rudolf E. Kalman (1960) — El filtro de Kalman.
- **[Maximum Likelihood from Incomplete Data via the EM Algorithm](https://doi.org/10.1111/j.2517-6161.1977.tb01600.x)** 💲 · Arthur P. Dempster, Nan M. Laird, Donald B. Rubin (1977) — El algoritmo EM.
- **[A tutorial on hidden Markov models and selected applications in speech recognition](https://doi.org/10.1109/5.18626)** 💲 · Lawrence R. Rabiner (1989) — El tutorial clásico de modelos ocultos de Markov.
- **[A comparison of event models for Naive Bayes text classification](https://cdn.aaai.org/Workshops/1998/WS-98-05/WS98-05-007.pdf)** · Andrew McCallum, Kamal Nigam (1998) — Naive Bayes multinomial frente a Bernoulli para texto.
- **[Latent Dirichlet Allocation](https://www.jmlr.org/papers/v3/blei03a.html)** · David M. Blei, Andrew Y. Ng, Michael I. Jordan (2003) — LDA: modelos de tópicos bayesianos.
- **[The Optimality of Naive Bayes](https://cdn.aaai.org/FLAIRS/2004/Flairs04-097.pdf)** · Harry Zhang (2004) — Por qué Naive Bayes funciona aunque sus supuestos no se cumplan.
- **[The No-U-Turn Sampler: Adaptively Setting Path Lengths in Hamiltonian Monte Carlo](https://arxiv.org/abs/1111.4246)** · Matthew D. Hoffman, Andrew Gelman (2011) · [PDF](https://arxiv.org/pdf/1111.4246)
- **[Stan: A Probabilistic Programming Language](https://www.jstatsoft.org/article/view/v076i01)** · Bob Carpenter, Andrew Gelman, et al. (2017)

### Survey / tutorial académico

- **[MCMC using Hamiltonian dynamics](https://arxiv.org/abs/1206.1901)** · Radford M. Neal (2012) · [PDF](https://arxiv.org/pdf/1206.1901) — Neal: Monte Carlo hamiltoniano explicado.
- **[Variational Inference: A Review for Statisticians](https://arxiv.org/abs/1601.00670)** · David M. Blei, Alp Kucukelbir, Jon D. McAuliffe (2016) · [PDF](https://arxiv.org/pdf/1601.00670) — Revisión de Blei et al. de la inferencia variacional.
- **[A Conceptual Introduction to Hamiltonian Monte Carlo](https://arxiv.org/abs/1701.02434)** · Michael Betancourt (2017) · [PDF](https://arxiv.org/pdf/1701.02434) — Betancourt: la intuición geométrica del HMC.

### Documentación oficial

- **[PyMC Documentation](https://www.pymc.io/)** · PyMC Developers (2024)
- **[Stan User's Guide](https://mc-stan.org/docs/stan-users-guide/)** · Stan Development Team (2024)

## SVM y métodos de kernel

### Paper

- **[Nearest neighbor pattern classification](https://doi.org/10.1109/TIT.1967.1053964)** 💲 · Thomas M. Cover, Peter E. Hart (1967) — El análisis clásico del clasificador de vecino más cercano.
- **[A training algorithm for optimal margin classifiers](https://doi.org/10.1145/130385.130401)** 💲 · Bernhard E. Boser, Isabelle M. Guyon, Vladimir N. Vapnik (1992) — Introduce el truco del kernel en los clasificadores de margen máximo.
- **[Support-vector networks](https://doi.org/10.1007/BF00994018)** 💲 · Corinna Cortes, Vladimir Vapnik (1995) — El paper de las SVM de margen suave.
- **[Nonlinear Component Analysis as a Kernel Eigenvalue Problem](https://doi.org/10.1162/089976698300017467)** 💲 · Bernhard Schölkopf, Alexander Smola, Klaus-Robert Müller (1998) — Kernel PCA.
- **[Sequential Minimal Optimization: A Fast Algorithm for Training Support Vector Machines](https://www.microsoft.com/en-us/research/publication/sequential-minimal-optimization-a-fast-algorithm-for-training-support-vector-machines/)** · John C. Platt (1998) — SMO: el algoritmo con que se entrenan las SVM.
- **[Estimating the Support of a High-Dimensional Distribution](https://doi.org/10.1162/089976601750264965)** 💲 · Bernhard Schölkopf, John C. Platt, John Shawe-Taylor, Alex J. Smola et al. (2001) — One-class SVM para detección de novedades.
- **[LIBSVM: A Library for Support Vector Machines](https://www.csie.ntu.edu.tw/~cjlin/papers/libsvm.pdf)** · Chih-Chung Chang, Chih-Jen Lin (2011) — La librería que usa scikit-learn por dentro para SVC.

### Survey / tutorial académico

- **[A Tutorial on Support Vector Machines for Pattern Recognition](https://www.microsoft.com/en-us/research/publication/a-tutorial-on-support-vector-machines-for-pattern-recognition/)** · Christopher J. C. Burges (1998) — El tutorial clásico de SVM.

## Árboles de decisión y ensembles

### Paper

- **[Induction of decision trees](https://doi.org/10.1007/BF00116251)** 💲 · J. Ross Quinlan (1986) — ID3.
- **[Bagging Predictors](https://doi.org/10.1007/BF00058655)** 💲 · Leo Breiman (1996) — Bagging: promediar modelos entrenados con bootstrap.
- **[A Decision-Theoretic Generalization of On-Line Learning and an Application to Boosting](https://doi.org/10.1006/jcss.1997.1504)** 💲 · Yoav Freund, Robert E. Schapire (1997) — AdaBoost.
- **[Greedy function approximation: A gradient boosting machine](https://projecteuclid.org/journals/annals-of-statistics/volume-29/issue-5/Greedy-function-approximation-A-gradient-boosting-machine/10.1214/aos/1013203451.full)** · Jerome H. Friedman (2001) — El paper del gradient boosting.
- **[Random Forests](https://doi.org/10.1023/A:1010933404324)** · Leo Breiman (2001) · [PDF](https://www.stat.berkeley.edu/~breiman/randomforest2001.pdf) — El paper de Random Forest.
- **[Extremely randomized trees](https://doi.org/10.1007/s10994-006-6226-1)** 💲 · Pierre Geurts, Damien Ernst, Louis Wehenkel (2006)
- **[XGBoost: A Scalable Tree Boosting System](https://arxiv.org/abs/1603.02754)** · Tianqi Chen, Carlos Guestrin (2016) · [PDF](https://arxiv.org/pdf/1603.02754) — XGBoost: boosting de árboles regularizado y escalable.
- **[CatBoost: unbiased boosting with categorical features](https://arxiv.org/abs/1706.09516)** · Liudmila Prokhorenkova, Gleb Gusev, Aleksandr Vorobev, Anna Veronika Dorogush et al. (2017) · [PDF](https://arxiv.org/pdf/1706.09516)
- **[LightGBM: A Highly Efficient Gradient Boosting Decision Tree](https://papers.nips.cc/paper_files/paper/2017/hash/6449f44a102fde848669bdd9eb6b76fa-Abstract.html)** · Guolin Ke, et al. (2017) — LightGBM: histogramas, GOSS y EFB.
- **[Why do tree-based models still outperform deep learning on tabular data?](https://arxiv.org/abs/2207.08815)** · Léo Grinsztajn, Edouard Oyallon, Gaël Varoquaux (2022) · [PDF](https://arxiv.org/pdf/2207.08815) — Comparación sistemática árboles vs. redes en datos tabulares.

### Documentación oficial

- **[LightGBM Documentation](https://lightgbm.readthedocs.io/)** · Microsoft (2024)
- **[XGBoost Documentation](https://xgboost.readthedocs.io/)** · XGBoost Developers (2024)
- **[scikit-learn: Decision Trees](https://scikit-learn.org/stable/modules/tree.html)** · scikit-learn developers (2024)
- **[scikit-learn: Ensembles (gradient boosting, random forests, bagging, voting, stacking)](https://scikit-learn.org/stable/modules/ensemble.html)** · scikit-learn developers (2024)

## Clustering, reducción de dimensión y anomalías

### Paper

- **[Least squares quantization in PCM](https://doi.org/10.1109/TIT.1982.1056489)** 💲 · Stuart P. Lloyd (1982) — El algoritmo de Lloyd (k-means).
- **[A Density-Based Algorithm for Discovering Clusters in Large Spatial Databases with Noise](https://cdn.aaai.org/KDD/1996/KDD96-037.pdf)** · Martin Ester, Hans-Peter Kriegel, Jörg Sander, Xiaowei Xu (1996) — DBSCAN.
- **[Learning the parts of objects by non-negative matrix factorization](https://doi.org/10.1038/44565)** 💲 · Daniel D. Lee, H. Sebastian Seung (1999)
- **[Independent component analysis: algorithms and applications](https://doi.org/10.1016/S0893-6080(00)00026-5)** 💲 · Aapo Hyvärinen, Erkki Oja (2000)
- **[LOF: identifying density-based local outliers](https://doi.org/10.1145/342009.335388)** 💲 · Markus M. Breunig, Hans-Peter Kriegel, Raymond T. Ng, Jörg Sander (2000)
- **[k-means++: The Advantages of Careful Seeding](https://theory.stanford.edu/~sergei/papers/kMeansPP-soda.pdf)** · David Arthur, Sergei Vassilvitskii (2007) — La inicialización k-means++.
- **[Isolation Forest](https://doi.org/10.1109/ICDM.2008.17)** 💲 · Fei Tony Liu, Kai Ming Ting, Zhi-Hua Zhou (2008)
- **[Visualizing Data using t-SNE](https://www.jmlr.org/papers/v9/vandermaaten08a.html)** · Laurens van der Maaten, Geoffrey Hinton (2008) — t-SNE.
- **[hdbscan: Hierarchical density based clustering](https://doi.org/10.21105/joss.00205)** · Leland McInnes, John Healy, Steve Astels (2017)
- **[UMAP: Uniform Manifold Approximation and Projection for Dimension Reduction](https://arxiv.org/abs/1802.03426)** · Leland McInnes, John Healy, James Melville (2018) · [PDF](https://arxiv.org/pdf/1802.03426)

### Survey / tutorial académico

- **[A Tutorial on Spectral Clustering](https://arxiv.org/abs/0711.0189)** · Ulrike von Luxburg (2007) · [PDF](https://arxiv.org/pdf/0711.0189) — El tutorial de von Luxburg sobre clustering espectral.
- **[A Tutorial on Principal Component Analysis](https://arxiv.org/abs/1404.1100)** · Jonathon Shlens (2014) · [PDF](https://arxiv.org/pdf/1404.1100) — Shlens: PCA explicado desde cero.
- **[Deep Learning for Anomaly Detection: A Survey](https://arxiv.org/abs/1901.03407)** · Raghavendra Chalapathy, Sanjay Chawla (2019) · [PDF](https://arxiv.org/pdf/1901.03407)

### Formulario / cheat sheet

- **[CS229 Cheatsheet: Unsupervised Learning](https://stanford.edu/~shervine/teaching/cs-229/cheatsheet-unsupervised-learning)** · Afshine Amidi, Shervine Amidi (2018) — Hoja de fórmulas: EM, k-means, clustering jerárquico, métricas, PCA e ICA.

### Artículo divulgativo

- **[How to Use t-SNE Effectively](https://distill.pub/2016/misread-tsne/)** · Martin Wattenberg, Fernanda Viégas, Ian Johnson (2016) — Cómo leer (y no malinterpretar) un gráfico t-SNE.

### Documentación oficial

- **[UMAP Documentation](https://umap-learn.readthedocs.io/)** · Leland McInnes (2024)
- **[scikit-learn: Clustering](https://scikit-learn.org/stable/modules/clustering.html)** · scikit-learn developers (2024) — Guía comparada de todos los algoritmos de clustering de scikit-learn.

## Redes neuronales y entrenamiento profundo

### Libro

- **[Neural Networks and Deep Learning](http://neuralnetworksanddeeplearning.com/)** · Michael Nielsen (2015) — Introducción paso a paso a las redes y a backpropagation. Gratuito.
- **[Deep Learning](https://www.deeplearningbook.org/)** · Ian Goodfellow, Yoshua Bengio, Aaron Courville (2016) — El libro de referencia de deep learning. Versión HTML completa gratuita.
- **[Dive into Deep Learning](https://d2l.ai/)** · Aston Zhang, Zachary C. Lipton, Mu Li, Alexander J. Smola (2023) — Deep learning interactivo con código en PyTorch, JAX y TensorFlow.
- **[Understanding Deep Learning](https://udlbook.github.io/udlbook/)** · Simon J. D. Prince (2023) — Deep learning moderno con figuras excelentes y cuadernos. PDF gratuito.
- **[Deep Learning: Foundations and Concepts](https://www.bishopbook.com/)** · Christopher M. Bishop, Hugh Bishop (2024) — Versión en línea gratuita del libro de Bishop y Bishop.

### Paper

- **[The perceptron: A probabilistic model for information storage and organization in the brain](https://doi.org/10.1037/h0042519)** 💲 · Frank Rosenblatt (1958) — El perceptrón.
- **[Learning representations by back-propagating errors](https://doi.org/10.1038/323533a0)** 💲 · David E. Rumelhart, Geoffrey E. Hinton, Ronald J. Williams (1986) — El paper que popularizó backpropagation.
- **[Multilayer feedforward networks are universal approximators](https://doi.org/10.1016/0893-6080(89)90020-8)** 💲 · Kurt Hornik, Maxwell Stinchcombe, Halbert White (1989) — Teorema de aproximación universal.
- **[Efficient BackProp](http://yann.lecun.com/exdb/publis/pdf/lecun-98b.pdf)** · Yann LeCun, Léon Bottou, Genevieve B. Orr, Klaus-Robert Müller (1998) — Trucos prácticos para entrenar redes.
- **[Reducing the Dimensionality of Data with Neural Networks](https://doi.org/10.1126/science.1127647)** 💲 · Geoffrey E. Hinton, Ruslan R. Salakhutdinov (2006)
- **[Understanding the difficulty of training deep feedforward neural networks](https://proceedings.mlr.press/v9/glorot10a.html)** · Xavier Glorot, Yoshua Bengio (2010) — Inicialización de Xavier/Glorot.
- **[Dropout: A Simple Way to Prevent Neural Networks from Overfitting](https://jmlr.org/papers/v15/srivastava14a.html)** · Nitish Srivastava, Geoffrey Hinton, Alex Krizhevsky, Ilya Sutskever et al. (2014) — Dropout.
- **[Batch Normalization: Accelerating Deep Network Training by Reducing Internal Covariate Shift](https://arxiv.org/abs/1502.03167)** · Sergey Ioffe, Christian Szegedy (2015) · [PDF](https://arxiv.org/pdf/1502.03167)
- **[Deep learning](https://doi.org/10.1038/nature14539)** 💲 · Yann LeCun, Yoshua Bengio, Geoffrey Hinton (2015) — La revisión de Nature de los tres pioneros.
- **[Delving Deep into Rectifiers: Surpassing Human-Level Performance on ImageNet Classification](https://arxiv.org/abs/1502.01852)** · Kaiming He, Xiangyu Zhang, Shaoqing Ren, Jian Sun (2015) · [PDF](https://arxiv.org/pdf/1502.01852) — Inicialización de He y PReLU.
- **[Distilling the Knowledge in a Neural Network](https://arxiv.org/abs/1503.02531)** · Geoffrey Hinton, Oriol Vinyals, Jeff Dean (2015) · [PDF](https://arxiv.org/pdf/1503.02531) — Destilación de conocimiento.
- **[Gaussian Error Linear Units (GELUs)](https://arxiv.org/abs/1606.08415)** · Dan Hendrycks, Kevin Gimpel (2016) · [PDF](https://arxiv.org/pdf/1606.08415)
- **[Layer Normalization](https://arxiv.org/abs/1607.06450)** · Jimmy Lei Ba, Jamie Ryan Kiros, Geoffrey E. Hinton (2016) · [PDF](https://arxiv.org/pdf/1607.06450)
- **[The Lottery Ticket Hypothesis: Finding Sparse, Trainable Neural Networks](https://arxiv.org/abs/1803.03635)** · Jonathan Frankle, Michael Carbin (2018) · [PDF](https://arxiv.org/pdf/1803.03635)
- **[Alice's Adventures in a Differentiable Wonderland -- Volume I, A Tour of the Land](https://arxiv.org/abs/2404.17625)** · Simone Scardapane (2024) · [PDF](https://arxiv.org/pdf/2404.17625) — Libro introductorio de Scardapane sobre redes diferenciables, publicado en arXiv.

### Formulario / cheat sheet

- **[CS229 Cheatsheet: Deep Learning](https://stanford.edu/~shervine/teaching/cs-229/cheatsheet-deep-learning)** · Afshine Amidi, Shervine Amidi (2018) — Hoja de fórmulas de deep learning.
- **[CS230 Cheatsheet: Deep Learning Tips and Tricks](https://stanford.edu/~shervine/teaching/cs-230/cheatsheet-deep-learning-tips-and-tricks)** · Afshine Amidi, Shervine Amidi (2019) — Trucos de entrenamiento: inicialización, normalización, regularización, ajuste.

### Artículo divulgativo

- **[Calculus on Computational Graphs: Backpropagation](https://colah.github.io/posts/2015-08-Backprop/)** · Christopher Olah (2015) — Backpropagation como regla de la cadena sobre un grafo.
- **[A Recipe for Training Neural Networks](https://karpathy.github.io/2019/04/25/recipe/)** · Andrej Karpathy (2019) — Proceso ordenado para entrenar y depurar redes.

### Documentación oficial

- **[Keras Developer Guides](https://keras.io/guides/)** · Keras team (2024)
- **[PyTorch Documentation](https://docs.pytorch.org/docs/stable/index.html)** · PyTorch Contributors (2024)
- **[TensorFlow Guide](https://www.tensorflow.org/guide)** · Google (2024)

## Redes convolucionales y visión por computadora

### Paper

- **[Gradient-Based Learning Applied to Document Recognition](http://yann.lecun.com/exdb/publis/pdf/lecun-98.pdf)** · Yann LeCun, Léon Bottou, Yoshua Bengio, Patrick Haffner (1998) — LeNet-5: las CNN entrenadas con gradiente.
- **[ImageNet Classification with Deep Convolutional Neural Networks](https://papers.nips.cc/paper_files/paper/2012/hash/c399862d3b9d6b76c8436e924a68c45b-Abstract.html)** · Alex Krizhevsky, Ilya Sutskever, Geoffrey E. Hinton (2012) — AlexNet.
- **[Rich feature hierarchies for accurate object detection and semantic segmentation](https://arxiv.org/abs/1311.2524)** · Ross Girshick, Jeff Donahue, Trevor Darrell, Jitendra Malik (2013) · [PDF](https://arxiv.org/pdf/1311.2524)
- **[Visualizing and Understanding Convolutional Networks](https://arxiv.org/abs/1311.2901)** · Matthew D Zeiler, Rob Fergus (2013) · [PDF](https://arxiv.org/pdf/1311.2901)
- **[Fully Convolutional Networks for Semantic Segmentation](https://arxiv.org/abs/1411.4038)** · Jonathan Long, Evan Shelhamer, Trevor Darrell (2014) · [PDF](https://arxiv.org/pdf/1411.4038)
- **[Going Deeper with Convolutions](https://arxiv.org/abs/1409.4842)** · Christian Szegedy, Wei Liu, Yangqing Jia, Pierre Sermanet et al. (2014) · [PDF](https://arxiv.org/pdf/1409.4842)
- **[Very Deep Convolutional Networks for Large-Scale Image Recognition](https://arxiv.org/abs/1409.1556)** · Karen Simonyan, Andrew Zisserman (2014) · [PDF](https://arxiv.org/pdf/1409.1556)
- **[Deep Residual Learning for Image Recognition](https://arxiv.org/abs/1512.03385)** · Kaiming He, Xiangyu Zhang, Shaoqing Ren, Jian Sun (2015) · [PDF](https://arxiv.org/pdf/1512.03385) — ResNet: conexiones residuales.
- **[Faster R-CNN: Towards Real-Time Object Detection with Region Proposal Networks](https://arxiv.org/abs/1506.01497)** · Shaoqing Ren, Kaiming He, Ross Girshick, Jian Sun (2015) · [PDF](https://arxiv.org/pdf/1506.01497)
- **[Rethinking the Inception Architecture for Computer Vision](https://arxiv.org/abs/1512.00567)** · Christian Szegedy, Vincent Vanhoucke, Sergey Ioffe, Jonathon Shlens et al. (2015) · [PDF](https://arxiv.org/pdf/1512.00567)
- **[SSD: Single Shot MultiBox Detector](https://arxiv.org/abs/1512.02325)** · Wei Liu, Dragomir Anguelov, Dumitru Erhan, Christian Szegedy et al. (2015) · [PDF](https://arxiv.org/pdf/1512.02325)
- **[U-Net: Convolutional Networks for Biomedical Image Segmentation](https://arxiv.org/abs/1505.04597)** · Olaf Ronneberger, Philipp Fischer, Thomas Brox (2015) · [PDF](https://arxiv.org/pdf/1505.04597)
- **[You Only Look Once: Unified, Real-Time Object Detection](https://arxiv.org/abs/1506.02640)** · Joseph Redmon, Santosh Divvala, Ross Girshick, Ali Farhadi (2015) · [PDF](https://arxiv.org/pdf/1506.02640)
- **[Densely Connected Convolutional Networks](https://arxiv.org/abs/1608.06993)** · Gao Huang, Zhuang Liu, Laurens van der Maaten, Kilian Q. Weinberger (2016) · [PDF](https://arxiv.org/pdf/1608.06993)
- **[Mask R-CNN](https://arxiv.org/abs/1703.06870)** · Kaiming He, Georgia Gkioxari, Piotr Dollár, Ross Girshick (2017) · [PDF](https://arxiv.org/pdf/1703.06870)
- **[MobileNets: Efficient Convolutional Neural Networks for Mobile Vision Applications](https://arxiv.org/abs/1704.04861)** · Andrew G. Howard, Menglong Zhu, Bo Chen, Dmitry Kalenichenko et al. (2017) · [PDF](https://arxiv.org/pdf/1704.04861)
- **[EfficientNet: Rethinking Model Scaling for Convolutional Neural Networks](https://arxiv.org/abs/1905.11946)** · Mingxing Tan, Quoc V. Le (2019) · [PDF](https://arxiv.org/pdf/1905.11946)
- **[Momentum Contrast for Unsupervised Visual Representation Learning](https://arxiv.org/abs/1911.05722)** · Kaiming He, Haoqi Fan, Yuxin Wu, Saining Xie et al. (2019) · [PDF](https://arxiv.org/pdf/1911.05722)
- **[A Simple Framework for Contrastive Learning of Visual Representations](https://arxiv.org/abs/2002.05709)** · Ting Chen, Simon Kornblith, Mohammad Norouzi, Geoffrey Hinton (2020) · [PDF](https://arxiv.org/pdf/2002.05709)
- **[An Image is Worth 16x16 Words: Transformers for Image Recognition at Scale](https://arxiv.org/abs/2010.11929)** · Alexey Dosovitskiy, Lucas Beyer, Alexander Kolesnikov, Dirk Weissenborn et al. (2020) · [PDF](https://arxiv.org/pdf/2010.11929)
- **[End-to-End Object Detection with Transformers](https://arxiv.org/abs/2005.12872)** · Nicolas Carion, Francisco Massa, Gabriel Synnaeve, Nicolas Usunier et al. (2020) · [PDF](https://arxiv.org/pdf/2005.12872)
- **[Swin Transformer: Hierarchical Vision Transformer using Shifted Windows](https://arxiv.org/abs/2103.14030)** · Ze Liu, Yutong Lin, Yue Cao, Han Hu et al. (2021) · [PDF](https://arxiv.org/pdf/2103.14030)
- **[A ConvNet for the 2020s](https://arxiv.org/abs/2201.03545)** · Zhuang Liu, Hanzi Mao, Chao-Yuan Wu, Christoph Feichtenhofer et al. (2022) · [PDF](https://arxiv.org/pdf/2201.03545)
- **[Segment Anything](https://arxiv.org/abs/2304.02643)** · Alexander Kirillov, Eric Mintun, Nikhila Ravi, Hanzi Mao et al. (2023) · [PDF](https://arxiv.org/pdf/2304.02643)

### Formulario / cheat sheet

- **[CS230 Cheatsheet: Convolutional Neural Networks](https://stanford.edu/~shervine/teaching/cs-230/cheatsheet-convolutional-neural-networks)** · Afshine Amidi, Shervine Amidi (2019) — Hoja de fórmulas de CNN: capas, dimensiones, detección de objetos y reconocimiento facial.

### Apuntes de curso

- **[CS231n: Deep Learning for Computer Vision — Course Notes](https://cs231n.github.io/)** · Andrej Karpathy, Fei-Fei Li, Justin Johnson, et al. (2024) — Apuntes del curso de visión de Stanford.

### Artículo divulgativo

- **[Feature Visualization](https://distill.pub/2017/feature-visualization/)** · Chris Olah, Alexander Mordvintsev, Ludwig Schubert (2017) — Qué detectan las neuronas de una CNN.

## Redes recurrentes y modelos de secuencia

### Paper

- **[Learning long-term dependencies with gradient descent is difficult](https://doi.org/10.1109/72.279181)** 💲 · Yoshua Bengio, Patrice Simard, Paolo Frasconi (1994)
- **[Long Short-Term Memory](https://doi.org/10.1162/neco.1997.9.8.1735)** · Sepp Hochreiter, Jürgen Schmidhuber (1997) · [PDF](https://www.bioinf.jku.at/publications/older/2604.pdf) — La LSTM.
- **[On the difficulty of training Recurrent Neural Networks](https://arxiv.org/abs/1211.5063)** · Razvan Pascanu, Tomas Mikolov, Yoshua Bengio (2012) · [PDF](https://arxiv.org/pdf/1211.5063)
- **[Generating Sequences With Recurrent Neural Networks](https://arxiv.org/abs/1308.0850)** · Alex Graves (2013) · [PDF](https://arxiv.org/pdf/1308.0850)
- **[Empirical Evaluation of Gated Recurrent Neural Networks on Sequence Modeling](https://arxiv.org/abs/1412.3555)** · Junyoung Chung, Caglar Gulcehre, KyungHyun Cho, Yoshua Bengio (2014) · [PDF](https://arxiv.org/pdf/1412.3555)
- **[Learning Phrase Representations using RNN Encoder-Decoder for Statistical Machine Translation](https://arxiv.org/abs/1406.1078)** · Kyunghyun Cho, Bart van Merrienboer, Caglar Gulcehre, Dzmitry Bahdanau et al. (2014) · [PDF](https://arxiv.org/pdf/1406.1078)
- **[Neural Machine Translation by Jointly Learning to Align and Translate](https://arxiv.org/abs/1409.0473)** · Dzmitry Bahdanau, Kyunghyun Cho, Yoshua Bengio (2014) · [PDF](https://arxiv.org/pdf/1409.0473) — La atención de Bahdanau.
- **[Sequence to Sequence Learning with Neural Networks](https://arxiv.org/abs/1409.3215)** · Ilya Sutskever, Oriol Vinyals, Quoc V. Le (2014) · [PDF](https://arxiv.org/pdf/1409.3215)
- **[Effective Approaches to Attention-based Neural Machine Translation](https://arxiv.org/abs/1508.04025)** · Minh-Thang Luong, Hieu Pham, Christopher D. Manning (2015) · [PDF](https://arxiv.org/pdf/1508.04025)
- **[WaveNet: A Generative Model for Raw Audio](https://arxiv.org/abs/1609.03499)** · Aaron van den Oord, Sander Dieleman, Heiga Zen, Karen Simonyan et al. (2016) · [PDF](https://arxiv.org/pdf/1609.03499)
- **[An Empirical Evaluation of Generic Convolutional and Recurrent Networks for Sequence Modeling](https://arxiv.org/abs/1803.01271)** · Shaojie Bai, J. Zico Kolter, Vladlen Koltun (2018) · [PDF](https://arxiv.org/pdf/1803.01271)

### Formulario / cheat sheet

- **[CS230 Cheatsheet: Recurrent Neural Networks](https://stanford.edu/~shervine/teaching/cs-230/cheatsheet-recurrent-neural-networks)** · Afshine Amidi, Shervine Amidi (2019) — Hoja de fórmulas de RNN, LSTM, GRU, embeddings y atención.

### Artículo divulgativo

- **[The Unreasonable Effectiveness of Recurrent Neural Networks](https://karpathy.github.io/2015/05/21/rnn-effectiveness/)** · Andrej Karpathy (2015)
- **[Understanding LSTM Networks](https://colah.github.io/posts/2015-08-Understanding-LSTMs/)** · Christopher Olah (2015) — La explicación visual más citada de las LSTM.
- **[Attention? Attention!](https://lilianweng.github.io/posts/2018-06-24-attention/)** · Lilian Weng (2018) — Recorrido por los mecanismos de atención.

## Procesamiento de lenguaje y embeddings

### Libro

- **[Introduction to Information Retrieval](https://nlp.stanford.edu/IR-book/)** · Christopher D. Manning, Prabhakar Raghavan, Hinrich Schütze (2008) — Recuperación de información (base de buscadores y RAG). Gratuito.
- **[Speech and Language Processing (3rd ed. draft)](https://web.stanford.edu/~jurafsky/slp3/)** · Daniel Jurafsky, James H. Martin (2024) — El texto de referencia de NLP, borrador gratuito actualizado.

### Paper

- **[A Neural Probabilistic Language Model](https://www.jmlr.org/papers/v3/bengio03a.html)** · Yoshua Bengio, Réjean Ducharme, Pascal Vincent, Christian Jauvin (2003) — El primer modelo de lenguaje neuronal con embeddings.
- **[Distributed Representations of Words and Phrases and their Compositionality](https://arxiv.org/abs/1310.4546)** · Tomas Mikolov, Ilya Sutskever, Kai Chen, Greg Corrado et al. (2013) · [PDF](https://arxiv.org/pdf/1310.4546)
- **[Efficient Estimation of Word Representations in Vector Space](https://arxiv.org/abs/1301.3781)** · Tomas Mikolov, Kai Chen, Greg Corrado, Jeffrey Dean (2013) · [PDF](https://arxiv.org/pdf/1301.3781)
- **[GloVe: Global Vectors for Word Representation](https://nlp.stanford.edu/pubs/glove.pdf)** · Jeffrey Pennington, Richard Socher, Christopher D. Manning (2014) — GloVe.
- **[Neural Machine Translation of Rare Words with Subword Units](https://arxiv.org/abs/1508.07909)** · Rico Sennrich, Barry Haddow, Alexandra Birch (2015) · [PDF](https://arxiv.org/pdf/1508.07909) — Byte-Pair Encoding para tokenizar.
- **[Enriching Word Vectors with Subword Information](https://arxiv.org/abs/1607.04606)** · Piotr Bojanowski, Edouard Grave, Armand Joulin, Tomas Mikolov (2016) · [PDF](https://arxiv.org/pdf/1607.04606)
- **[Deep contextualized word representations](https://arxiv.org/abs/1802.05365)** · Matthew E. Peters, Mark Neumann, Mohit Iyyer, Matt Gardner et al. (2018) · [PDF](https://arxiv.org/pdf/1802.05365)
- **[SentencePiece: A simple and language independent subword tokenizer and detokenizer for Neural Text Processing](https://arxiv.org/abs/1808.06226)** · Taku Kudo, John Richardson (2018) · [PDF](https://arxiv.org/pdf/1808.06226)
- **[Sentence-BERT: Sentence Embeddings using Siamese BERT-Networks](https://arxiv.org/abs/1908.10084)** · Nils Reimers, Iryna Gurevych (2019) · [PDF](https://arxiv.org/pdf/1908.10084)

### Curso en línea

- **[Hugging Face LLM Course (NLP Course)](https://huggingface.co/learn/llm-course)** · Hugging Face (2024) — Curso oficial de Hugging Face sobre transformers y LLM.

### Artículo divulgativo

- **[The Illustrated Word2vec](https://jalammar.github.io/illustrated-word2vec/)** · Jay Alammar (2019)

## Transformers y modelos de lenguaje (LLM)

### Paper

- **[Attention Is All You Need](https://arxiv.org/abs/1706.03762)** · Ashish Vaswani, Noam Shazeer, Niki Parmar, Jakob Uszkoreit et al. (2017) · [PDF](https://arxiv.org/pdf/1706.03762) — El Transformer.
- **[Deep reinforcement learning from human preferences](https://arxiv.org/abs/1706.03741)** · Paul Christiano, Jan Leike, Tom B. Brown, Miljan Martic et al. (2017) · [PDF](https://arxiv.org/pdf/1706.03741)
- **[Outrageously Large Neural Networks: The Sparsely-Gated Mixture-of-Experts Layer](https://arxiv.org/abs/1701.06538)** · Noam Shazeer, Azalia Mirhoseini, Krzysztof Maziarz, Andy Davis et al. (2017) · [PDF](https://arxiv.org/pdf/1701.06538)
- **[BERT: Pre-training of Deep Bidirectional Transformers for Language Understanding](https://arxiv.org/abs/1810.04805)** · Jacob Devlin, Ming-Wei Chang, Kenton Lee, Kristina Toutanova (2018) · [PDF](https://arxiv.org/pdf/1810.04805)
- **[Improving Language Understanding by Generative Pre-Training](https://cdn.openai.com/research-covers/language-unsupervised/language_understanding_paper.pdf)** · Alec Radford, Karthik Narasimhan, Tim Salimans, Ilya Sutskever (2018) — GPT-1.
- **[DistilBERT, a distilled version of BERT: smaller, faster, cheaper and lighter](https://arxiv.org/abs/1910.01108)** · Victor Sanh, Lysandre Debut, Julien Chaumond, Thomas Wolf (2019) · [PDF](https://arxiv.org/pdf/1910.01108)
- **[Exploring the Limits of Transfer Learning with a Unified Text-to-Text Transformer](https://arxiv.org/abs/1910.10683)** · Colin Raffel, Noam Shazeer, Adam Roberts, Katherine Lee et al. (2019) · [PDF](https://arxiv.org/pdf/1910.10683)
- **[Fast Transformer Decoding: One Write-Head is All You Need](https://arxiv.org/abs/1911.02150)** · Noam Shazeer (2019) · [PDF](https://arxiv.org/pdf/1911.02150)
- **[Language Models are Unsupervised Multitask Learners](https://cdn.openai.com/better-language-models/language_models_are_unsupervised_multitask_learners.pdf)** · Alec Radford, Jeffrey Wu, Rewon Child, David Luan et al. (2019) — GPT-2.
- **[RoBERTa: A Robustly Optimized BERT Pretraining Approach](https://arxiv.org/abs/1907.11692)** · Yinhan Liu, Myle Ott, Naman Goyal, Jingfei Du et al. (2019) · [PDF](https://arxiv.org/pdf/1907.11692)
- **[Transformer-XL: Attentive Language Models Beyond a Fixed-Length Context](https://arxiv.org/abs/1901.02860)** · Zihang Dai, Zhilin Yang, Yiming Yang, Jaime Carbonell et al. (2019) · [PDF](https://arxiv.org/pdf/1901.02860)
- **[ELECTRA: Pre-training Text Encoders as Discriminators Rather Than Generators](https://arxiv.org/abs/2003.10555)** · Kevin Clark, Minh-Thang Luong, Quoc V. Le, Christopher D. Manning (2020) · [PDF](https://arxiv.org/pdf/2003.10555)
- **[Language Models are Few-Shot Learners](https://arxiv.org/abs/2005.14165)** · Tom B. Brown, Benjamin Mann, Nick Ryder, Melanie Subbiah et al. (2020) · [PDF](https://arxiv.org/pdf/2005.14165) — GPT-3.
- **[Longformer: The Long-Document Transformer](https://arxiv.org/abs/2004.05150)** · Iz Beltagy, Matthew E. Peters, Arman Cohan (2020) · [PDF](https://arxiv.org/pdf/2004.05150)
- **[Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks](https://arxiv.org/abs/2005.11401)** · Patrick Lewis, Ethan Perez, Aleksandra Piktus, Fabio Petroni et al. (2020) · [PDF](https://arxiv.org/pdf/2005.11401)
- **[Scaling Laws for Neural Language Models](https://arxiv.org/abs/2001.08361)** · Jared Kaplan, Sam McCandlish, Tom Henighan, Tom B. Brown et al. (2020) · [PDF](https://arxiv.org/pdf/2001.08361)
- **[Learning Transferable Visual Models From Natural Language Supervision](https://arxiv.org/abs/2103.00020)** · Alec Radford, Jong Wook Kim, Chris Hallacy, Aditya Ramesh et al. (2021) · [PDF](https://arxiv.org/pdf/2103.00020)
- **[LoRA: Low-Rank Adaptation of Large Language Models](https://arxiv.org/abs/2106.09685)** · Edward J. Hu, Yelong Shen, Phillip Wallis, Zeyuan Allen-Zhu et al. (2021) · [PDF](https://arxiv.org/pdf/2106.09685)
- **[RoFormer: Enhanced Transformer with Rotary Position Embedding](https://arxiv.org/abs/2104.09864)** · Jianlin Su, Yu Lu, Shengfeng Pan, Ahmed Murtadha et al. (2021) · [PDF](https://arxiv.org/pdf/2104.09864)
- **[Switch Transformers: Scaling to Trillion Parameter Models with Simple and Efficient Sparsity](https://arxiv.org/abs/2101.03961)** · William Fedus, Barret Zoph, Noam Shazeer (2021) · [PDF](https://arxiv.org/pdf/2101.03961)
- **[Train Short, Test Long: Attention with Linear Biases Enables Input Length Extrapolation](https://arxiv.org/abs/2108.12409)** · Ofir Press, Noah A. Smith, Mike Lewis (2021) · [PDF](https://arxiv.org/pdf/2108.12409)
- **[Chain-of-Thought Prompting Elicits Reasoning in Large Language Models](https://arxiv.org/abs/2201.11903)** · Jason Wei, Xuezhi Wang, Dale Schuurmans, Maarten Bosma et al. (2022) · [PDF](https://arxiv.org/pdf/2201.11903)
- **[Constitutional AI: Harmlessness from AI Feedback](https://arxiv.org/abs/2212.08073)** · Yuntao Bai, Saurav Kadavath, Sandipan Kundu, Amanda Askell et al. (2022) · [PDF](https://arxiv.org/pdf/2212.08073)
- **[Fast Inference from Transformers via Speculative Decoding](https://arxiv.org/abs/2211.17192)** · Yaniv Leviathan, Matan Kalman, Yossi Matias (2022) · [PDF](https://arxiv.org/pdf/2211.17192)
- **[FlashAttention: Fast and Memory-Efficient Exact Attention with IO-Awareness](https://arxiv.org/abs/2205.14135)** · Tri Dao, Daniel Y. Fu, Stefano Ermon, Atri Rudra et al. (2022) · [PDF](https://arxiv.org/pdf/2205.14135)
- **[GPTQ: Accurate Post-Training Quantization for Generative Pre-trained Transformers](https://arxiv.org/abs/2210.17323)** · Elias Frantar, Saleh Ashkboos, Torsten Hoefler, Dan Alistarh (2022) · [PDF](https://arxiv.org/pdf/2210.17323)
- **[LLM.int8(): 8-bit Matrix Multiplication for Transformers at Scale](https://arxiv.org/abs/2208.07339)** · Tim Dettmers, Mike Lewis, Younes Belkada, Luke Zettlemoyer (2022) · [PDF](https://arxiv.org/pdf/2208.07339)
- **[ReAct: Synergizing Reasoning and Acting in Language Models](https://arxiv.org/abs/2210.03629)** · Shunyu Yao, Jeffrey Zhao, Dian Yu, Nan Du et al. (2022) · [PDF](https://arxiv.org/pdf/2210.03629)
- **[Training Compute-Optimal Large Language Models](https://arxiv.org/abs/2203.15556)** · Jordan Hoffmann, Sebastian Borgeaud, Arthur Mensch, Elena Buchatskaya et al. (2022) · [PDF](https://arxiv.org/pdf/2203.15556)
- **[Training language models to follow instructions with human feedback](https://arxiv.org/abs/2203.02155)** · Long Ouyang, Jeff Wu, Xu Jiang, Diogo Almeida et al. (2022) · [PDF](https://arxiv.org/pdf/2203.02155)
- **[Direct Preference Optimization: Your Language Model is Secretly a Reward Model](https://arxiv.org/abs/2305.18290)** · Rafael Rafailov, Archit Sharma, Eric Mitchell, Stefano Ermon et al. (2023) · [PDF](https://arxiv.org/pdf/2305.18290)
- **[GQA: Training Generalized Multi-Query Transformer Models from Multi-Head Checkpoints](https://arxiv.org/abs/2305.13245)** · Joshua Ainslie, James Lee-Thorp, Michiel de Jong, Yury Zemlyanskiy et al. (2023) · [PDF](https://arxiv.org/pdf/2305.13245)
- **[LLaMA: Open and Efficient Foundation Language Models](https://arxiv.org/abs/2302.13971)** · Hugo Touvron, Thibaut Lavril, Gautier Izacard, Xavier Martinet et al. (2023) · [PDF](https://arxiv.org/pdf/2302.13971)
- **[Llama 2: Open Foundation and Fine-Tuned Chat Models](https://arxiv.org/abs/2307.09288)** · Hugo Touvron, Louis Martin, Kevin Stone, Peter Albert et al. (2023) · [PDF](https://arxiv.org/pdf/2307.09288)
- **[Mamba: Linear-Time Sequence Modeling with Selective State Spaces](https://arxiv.org/abs/2312.00752)** · Albert Gu, Tri Dao (2023) · [PDF](https://arxiv.org/pdf/2312.00752)
- **[Mistral 7B](https://arxiv.org/abs/2310.06825)** · Albert Q. Jiang, Alexandre Sablayrolles, Arthur Mensch, Chris Bamford et al. (2023) · [PDF](https://arxiv.org/pdf/2310.06825)
- **[QLoRA: Efficient Finetuning of Quantized LLMs](https://arxiv.org/abs/2305.14314)** · Tim Dettmers, Artidoro Pagnoni, Ari Holtzman, Luke Zettlemoyer (2023) · [PDF](https://arxiv.org/pdf/2305.14314)
- **[Toolformer: Language Models Can Teach Themselves to Use Tools](https://arxiv.org/abs/2302.04761)** · Timo Schick, Jane Dwivedi-Yu, Roberto Dessì, Roberta Raileanu et al. (2023) · [PDF](https://arxiv.org/pdf/2302.04761)
- **[Mixtral of Experts](https://arxiv.org/abs/2401.04088)** · Albert Q. Jiang, Alexandre Sablayrolles, Antoine Roux, Arthur Mensch et al. (2024) · [PDF](https://arxiv.org/pdf/2401.04088)

### Survey / tutorial académico

- **[Formal Algorithms for Transformers](https://arxiv.org/abs/2207.09238)** · Mary Phuong, Marcus Hutter (2022) · [PDF](https://arxiv.org/pdf/2207.09238) — Los algoritmos del Transformer en pseudocódigo preciso (DeepMind).
- **[A Survey of Large Language Models](https://arxiv.org/abs/2303.18223)** · Wayne Xin Zhao, Kun Zhou, Junyi Li, Tianyi Tang et al. (2023) · [PDF](https://arxiv.org/pdf/2303.18223)

### Artículo divulgativo

- **[The Illustrated BERT, ELMo, and co.](https://jalammar.github.io/illustrated-bert/)** · Jay Alammar (2018)
- **[The Illustrated Transformer](https://jalammar.github.io/illustrated-transformer/)** · Jay Alammar (2018) — El Transformer explicado con diagramas.
- **[A Mathematical Framework for Transformer Circuits](https://transformer-circuits.pub/2021/framework/index.html)** · Nelson Elhage, Neel Nanda, Catherine Olsson, et al. (2021)
- **[The Annotated Transformer](https://nlp.seas.harvard.edu/annotated-transformer/)** · Alexander Rush, Austin Huang, Suraj Subramanian, et al. (2022) — El paper del Transformer implementado línea por línea en PyTorch.

### Documentación oficial

- **[Hugging Face Transformers Documentation](https://huggingface.co/docs/transformers/index)** · Hugging Face (2024)

## Modelos generativos (VAE, GAN, flujos, difusión)

### Paper

- **[Auto-Encoding Variational Bayes](https://arxiv.org/abs/1312.6114)** · Diederik P Kingma, Max Welling (2013) · [PDF](https://arxiv.org/pdf/1312.6114) — El VAE.
- **[Conditional Generative Adversarial Nets](https://arxiv.org/abs/1411.1784)** · Mehdi Mirza, Simon Osindero (2014) · [PDF](https://arxiv.org/pdf/1411.1784)
- **[Generative Adversarial Networks](https://arxiv.org/abs/1406.2661)** · Ian J. Goodfellow, Jean Pouget-Abadie, Mehdi Mirza, Bing Xu et al. (2014) · [PDF](https://arxiv.org/pdf/1406.2661) — Las GAN.
- **[NICE: Non-linear Independent Components Estimation](https://arxiv.org/abs/1410.8516)** · Laurent Dinh, David Krueger, Yoshua Bengio (2014) · [PDF](https://arxiv.org/pdf/1410.8516)
- **[Deep Unsupervised Learning using Nonequilibrium Thermodynamics](https://arxiv.org/abs/1503.03585)** · Jascha Sohl-Dickstein, Eric A. Weiss, Niru Maheswaranathan, Surya Ganguli (2015) · [PDF](https://arxiv.org/pdf/1503.03585) — El origen de los modelos de difusión.
- **[Unsupervised Representation Learning with Deep Convolutional Generative Adversarial Networks](https://arxiv.org/abs/1511.06434)** · Alec Radford, Luke Metz, Soumith Chintala (2015) · [PDF](https://arxiv.org/pdf/1511.06434)
- **[Conditional Image Generation with PixelCNN Decoders](https://arxiv.org/abs/1606.05328)** · Aaron van den Oord, Nal Kalchbrenner, Oriol Vinyals, Lasse Espeholt et al. (2016) · [PDF](https://arxiv.org/pdf/1606.05328)
- **[Density estimation using Real NVP](https://arxiv.org/abs/1605.08803)** · Laurent Dinh, Jascha Sohl-Dickstein, Samy Bengio (2016) · [PDF](https://arxiv.org/pdf/1605.08803)
- **[Image-to-Image Translation with Conditional Adversarial Networks](https://arxiv.org/abs/1611.07004)** · Phillip Isola, Jun-Yan Zhu, Tinghui Zhou, Alexei A. Efros (2016) · [PDF](https://arxiv.org/pdf/1611.07004)
- **[Improved Training of Wasserstein GANs](https://arxiv.org/abs/1704.00028)** · Ishaan Gulrajani, Faruk Ahmed, Martin Arjovsky, Vincent Dumoulin et al. (2017) · [PDF](https://arxiv.org/pdf/1704.00028)
- **[Neural Discrete Representation Learning](https://arxiv.org/abs/1711.00937)** · Aaron van den Oord, Oriol Vinyals, Koray Kavukcuoglu (2017) · [PDF](https://arxiv.org/pdf/1711.00937)
- **[Unpaired Image-to-Image Translation using Cycle-Consistent Adversarial Networks](https://arxiv.org/abs/1703.10593)** · Jun-Yan Zhu, Taesung Park, Phillip Isola, Alexei A. Efros (2017) · [PDF](https://arxiv.org/pdf/1703.10593)
- **[Wasserstein GAN](https://arxiv.org/abs/1701.07875)** · Martin Arjovsky, Soumith Chintala, Léon Bottou (2017) · [PDF](https://arxiv.org/pdf/1701.07875)
- **[A Style-Based Generator Architecture for Generative Adversarial Networks](https://arxiv.org/abs/1812.04948)** · Tero Karras, Samuli Laine, Timo Aila (2018) · [PDF](https://arxiv.org/pdf/1812.04948)
- **[Glow: Generative Flow with Invertible 1x1 Convolutions](https://arxiv.org/abs/1807.03039)** · Diederik P. Kingma, Prafulla Dhariwal (2018) · [PDF](https://arxiv.org/pdf/1807.03039)
- **[Generative Modeling by Estimating Gradients of the Data Distribution](https://arxiv.org/abs/1907.05600)** · Yang Song, Stefano Ermon (2019) · [PDF](https://arxiv.org/pdf/1907.05600)
- **[Denoising Diffusion Implicit Models](https://arxiv.org/abs/2010.02502)** · Jiaming Song, Chenlin Meng, Stefano Ermon (2020) · [PDF](https://arxiv.org/pdf/2010.02502)
- **[Denoising Diffusion Probabilistic Models](https://arxiv.org/abs/2006.11239)** · Jonathan Ho, Ajay Jain, Pieter Abbeel (2020) · [PDF](https://arxiv.org/pdf/2006.11239) — DDPM.
- **[Score-Based Generative Modeling through Stochastic Differential Equations](https://arxiv.org/abs/2011.13456)** · Yang Song, Jascha Sohl-Dickstein, Diederik P. Kingma, Abhishek Kumar et al. (2020) · [PDF](https://arxiv.org/pdf/2011.13456)
- **[High-Resolution Image Synthesis with Latent Diffusion Models](https://arxiv.org/abs/2112.10752)** · Robin Rombach, Andreas Blattmann, Dominik Lorenz, Patrick Esser et al. (2021) · [PDF](https://arxiv.org/pdf/2112.10752)
- **[Improved Denoising Diffusion Probabilistic Models](https://arxiv.org/abs/2102.09672)** · Alex Nichol, Prafulla Dhariwal (2021) · [PDF](https://arxiv.org/pdf/2102.09672)
- **[Classifier-Free Diffusion Guidance](https://arxiv.org/abs/2207.12598)** · Jonathan Ho, Tim Salimans (2022) · [PDF](https://arxiv.org/pdf/2207.12598)
- **[Hierarchical Text-Conditional Image Generation with CLIP Latents](https://arxiv.org/abs/2204.06125)** · Aditya Ramesh, Prafulla Dhariwal, Alex Nichol, Casey Chu et al. (2022) · [PDF](https://arxiv.org/pdf/2204.06125)

### Survey / tutorial académico

- **[NIPS 2016 Tutorial: Generative Adversarial Networks](https://arxiv.org/abs/1701.00160)** · Ian Goodfellow (2016) · [PDF](https://arxiv.org/pdf/1701.00160) — Tutorial de Goodfellow sobre GAN.
- **[An Introduction to Variational Autoencoders](https://arxiv.org/abs/1906.02691)** · Diederik P. Kingma, Max Welling (2019) · [PDF](https://arxiv.org/pdf/1906.02691) — Introducción de Kingma y Welling a los VAE.
- **[Normalizing Flows for Probabilistic Modeling and Inference](https://arxiv.org/abs/1912.02762)** · George Papamakarios, Eric Nalisnick, Danilo Jimenez Rezende, Shakir Mohamed et al. (2019) · [PDF](https://arxiv.org/pdf/1912.02762)
- **[Understanding Diffusion Models: A Unified Perspective](https://arxiv.org/abs/2208.11970)** · Calvin Luo (2022) · [PDF](https://arxiv.org/pdf/2208.11970) — Luo: VAE, difusión y score matching en un solo marco.

### Artículo divulgativo

- **[What are Diffusion Models?](https://lilianweng.github.io/posts/2021-07-11-diffusion-models/)** · Lilian Weng (2021) — Las matemáticas de la difusión, en orden.

## Aprendizaje por refuerzo

### Libro

- **[Reinforcement Learning: An Introduction (2nd ed.)](http://incompleteideas.net/book/the-book-2nd.html)** · Richard S. Sutton, Andrew G. Barto (2018) · [PDF](http://incompleteideas.net/book/RLbook2020.pdf) — El libro de referencia del aprendizaje por refuerzo. PDF gratuito de los autores.
- **[Algorithms for Decision Making](https://algorithmsbook.com/)** · Mykel J. Kochenderfer, Tim A. Wheeler, Kyle H. Wray (2022) — Decisión bajo incertidumbre: MDP, POMDP, RL. PDF gratuito.

### Paper

- **[Q-learning](https://doi.org/10.1007/BF00992698)** 💲 · Christopher J. C. H. Watkins, Peter Dayan (1992) — Q-learning.
- **[Simple statistical gradient-following algorithms for connectionist reinforcement learning](https://doi.org/10.1007/BF00992696)** 💲 · Ronald J. Williams (1992) — REINFORCE.
- **[Policy Gradient Methods for Reinforcement Learning with Function Approximation](https://papers.nips.cc/paper_files/paper/1999/hash/464d828b85b0bed98e80ade0a5c43b0f-Abstract.html)** · Richard S. Sutton, David McAllester, Satinder Singh, Yishay Mansour (1999)
- **[Playing Atari with Deep Reinforcement Learning](https://arxiv.org/abs/1312.5602)** · Volodymyr Mnih, Koray Kavukcuoglu, David Silver, Alex Graves et al. (2013) · [PDF](https://arxiv.org/pdf/1312.5602) — DQN.
- **[Continuous control with deep reinforcement learning](https://arxiv.org/abs/1509.02971)** · Timothy P. Lillicrap, Jonathan J. Hunt, Alexander Pritzel, Nicolas Heess et al. (2015) · [PDF](https://arxiv.org/pdf/1509.02971)
- **[Deep Reinforcement Learning with Double Q-learning](https://arxiv.org/abs/1509.06461)** · Hado van Hasselt, Arthur Guez, David Silver (2015) · [PDF](https://arxiv.org/pdf/1509.06461)
- **[Dueling Network Architectures for Deep Reinforcement Learning](https://arxiv.org/abs/1511.06581)** · Ziyu Wang, Tom Schaul, Matteo Hessel, Hado van Hasselt et al. (2015) · [PDF](https://arxiv.org/pdf/1511.06581)
- **[High-Dimensional Continuous Control Using Generalized Advantage Estimation](https://arxiv.org/abs/1506.02438)** · John Schulman, Philipp Moritz, Sergey Levine, Michael Jordan et al. (2015) · [PDF](https://arxiv.org/pdf/1506.02438)
- **[Prioritized Experience Replay](https://arxiv.org/abs/1511.05952)** · Tom Schaul, John Quan, Ioannis Antonoglou, David Silver (2015) · [PDF](https://arxiv.org/pdf/1511.05952)
- **[Trust Region Policy Optimization](https://arxiv.org/abs/1502.05477)** · John Schulman, Sergey Levine, Philipp Moritz, Michael I. Jordan et al. (2015) · [PDF](https://arxiv.org/pdf/1502.05477)
- **[Asynchronous Methods for Deep Reinforcement Learning](https://arxiv.org/abs/1602.01783)** · Volodymyr Mnih, Adrià Puigdomènech Badia, Mehdi Mirza, Alex Graves et al. (2016) · [PDF](https://arxiv.org/pdf/1602.01783)
- **[Mastering the game of Go with deep neural networks and tree search](https://doi.org/10.1038/nature16961)** 💲 · David Silver, et al. (2016)
- **[Mastering Chess and Shogi by Self-Play with a General Reinforcement Learning Algorithm](https://arxiv.org/abs/1712.01815)** · David Silver, Thomas Hubert, Julian Schrittwieser, Ioannis Antonoglou et al. (2017) · [PDF](https://arxiv.org/pdf/1712.01815)
- **[Proximal Policy Optimization Algorithms](https://arxiv.org/abs/1707.06347)** · John Schulman, Filip Wolski, Prafulla Dhariwal, Alec Radford et al. (2017) · [PDF](https://arxiv.org/pdf/1707.06347) — PPO.
- **[Rainbow: Combining Improvements in Deep Reinforcement Learning](https://arxiv.org/abs/1710.02298)** · Matteo Hessel, Joseph Modayil, Hado van Hasselt, Tom Schaul et al. (2017) · [PDF](https://arxiv.org/pdf/1710.02298)
- **[Addressing Function Approximation Error in Actor-Critic Methods](https://arxiv.org/abs/1802.09477)** · Scott Fujimoto, Herke van Hoof, David Meger (2018) · [PDF](https://arxiv.org/pdf/1802.09477)
- **[Soft Actor-Critic: Off-Policy Maximum Entropy Deep Reinforcement Learning with a Stochastic Actor](https://arxiv.org/abs/1801.01290)** · Tuomas Haarnoja, Aurick Zhou, Pieter Abbeel, Sergey Levine (2018) · [PDF](https://arxiv.org/pdf/1801.01290)
- **[Mastering Atari, Go, Chess and Shogi by Planning with a Learned Model](https://arxiv.org/abs/1911.08265)** · Julian Schrittwieser, Ioannis Antonoglou, Thomas Hubert, Karen Simonyan et al. (2019) · [PDF](https://arxiv.org/pdf/1911.08265)
- **[Offline Reinforcement Learning: Tutorial, Review, and Perspectives on Open Problems](https://arxiv.org/abs/2005.01643)** · Sergey Levine, Aviral Kumar, George Tucker, Justin Fu (2020) · [PDF](https://arxiv.org/pdf/2005.01643)
- **[Decision Transformer: Reinforcement Learning via Sequence Modeling](https://arxiv.org/abs/2106.01345)** · Lili Chen, Kevin Lu, Aravind Rajeswaran, Kimin Lee et al. (2021) · [PDF](https://arxiv.org/pdf/2106.01345)

### Survey / tutorial académico

- **[A Brief Survey of Deep Reinforcement Learning](https://arxiv.org/abs/1708.05866)** · Kai Arulkumaran, Marc Peter Deisenroth, Miles Brundage, Anil Anthony Bharath (2017) · [PDF](https://arxiv.org/pdf/1708.05866)

### Formulario / cheat sheet

- **[CS221 Cheatsheet: States-based models (search, MDPs, games)](https://stanford.edu/~shervine/teaching/cs-221/cheatsheet-states-models)** · Afshine Amidi, Shervine Amidi (2019) — Hoja de fórmulas de búsqueda, MDP y juegos.

### Curso en línea

- **[Spinning Up in Deep RL](https://spinningup.openai.com/)** · Joshua Achiam, OpenAI (2018) — Introducción de OpenAI al RL profundo con implementaciones de referencia.

### Artículo divulgativo

- **[Policy Gradient Algorithms](https://lilianweng.github.io/posts/2018-04-08-policy-gradient/)** · Lilian Weng (2018)

### Documentación oficial

- **[Gymnasium Documentation](https://gymnasium.farama.org/)** · Farama Foundation (2024)
- **[Stable-Baselines3 Documentation](https://stable-baselines3.readthedocs.io/)** · DLR-RM (2024)

## Redes neuronales sobre grafos

### Libro

- **[Graph Representation Learning](https://www.cs.mcgill.ca/~wlh/grl_book/)** · William L. Hamilton (2020) — Libro sobre aprendizaje de representaciones en grafos. Borrador en PDF gratuito.

### Paper

- **[The Graph Neural Network Model](https://doi.org/10.1109/TNN.2008.2005605)** 💲 · Franco Scarselli, Marco Gori, Ah Chung Tsoi, Markus Hagenbuchner et al. (2009) — El modelo original de red neuronal sobre grafos.
- **[DeepWalk: Online Learning of Social Representations](https://arxiv.org/abs/1403.6652)** · Bryan Perozzi, Rami Al-Rfou, Steven Skiena (2014) · [PDF](https://arxiv.org/pdf/1403.6652)
- **[Convolutional Neural Networks on Graphs with Fast Localized Spectral Filtering](https://arxiv.org/abs/1606.09375)** · Michaël Defferrard, Xavier Bresson, Pierre Vandergheynst (2016) · [PDF](https://arxiv.org/pdf/1606.09375)
- **[Semi-Supervised Classification with Graph Convolutional Networks](https://arxiv.org/abs/1609.02907)** · Thomas N. Kipf, Max Welling (2016) · [PDF](https://arxiv.org/pdf/1609.02907) — GCN.
- **[node2vec: Scalable Feature Learning for Networks](https://arxiv.org/abs/1607.00653)** · Aditya Grover, Jure Leskovec (2016) · [PDF](https://arxiv.org/pdf/1607.00653)
- **[Graph Attention Networks](https://arxiv.org/abs/1710.10903)** · Petar Veličković, Guillem Cucurull, Arantxa Casanova, Adriana Romero et al. (2017) · [PDF](https://arxiv.org/pdf/1710.10903)
- **[Inductive Representation Learning on Large Graphs](https://arxiv.org/abs/1706.02216)** · William L. Hamilton, Rex Ying, Jure Leskovec (2017) · [PDF](https://arxiv.org/pdf/1706.02216)
- **[Neural Message Passing for Quantum Chemistry](https://arxiv.org/abs/1704.01212)** · Justin Gilmer, Samuel S. Schoenholz, Patrick F. Riley, Oriol Vinyals et al. (2017) · [PDF](https://arxiv.org/pdf/1704.01212)
- **[How Powerful are Graph Neural Networks?](https://arxiv.org/abs/1810.00826)** · Keyulu Xu, Weihua Hu, Jure Leskovec, Stefanie Jegelka (2018) · [PDF](https://arxiv.org/pdf/1810.00826)
- **[Relational inductive biases, deep learning, and graph networks](https://arxiv.org/abs/1806.01261)** · Peter W. Battaglia, Jessica B. Hamrick, Victor Bapst, Alvaro Sanchez-Gonzalez et al. (2018) · [PDF](https://arxiv.org/pdf/1806.01261)

### Survey / tutorial académico

- **[A Comprehensive Survey on Graph Neural Networks](https://arxiv.org/abs/1901.00596)** · Zonghan Wu, Shirui Pan, Fengwen Chen, Guodong Long et al. (2019) · [PDF](https://arxiv.org/pdf/1901.00596)
- **[Geometric Deep Learning: Grids, Groups, Graphs, Geodesics, and Gauges](https://arxiv.org/abs/2104.13478)** · Michael M. Bronstein, Joan Bruna, Taco Cohen, Petar Veličković (2021) · [PDF](https://arxiv.org/pdf/2104.13478)

### Artículo divulgativo

- **[A Gentle Introduction to Graph Neural Networks](https://distill.pub/2021/gnn-intro/)** · Benjamin Sanchez-Lengeling, Emily Reif, Adam Pearce, Alexander B. Wiltschko (2021) — Introducción interactiva a las GNN.

### Documentación oficial

- **[PyTorch Geometric Documentation](https://pytorch-geometric.readthedocs.io/)** · PyG Team (2024)

## Series temporales y pronóstico

### Libro

- **[Forecasting: Principles and Practice (3rd ed.)](https://otexts.com/fpp3/)** · Rob J. Hyndman, George Athanasopoulos (2021) — El libro de referencia de pronóstico, gratuito en línea.

### Paper

- **[Automatic Time Series Forecasting: The forecast Package for R](https://www.jstatsoft.org/article/view/v027i03)** · Rob J. Hyndman, Yeasmin Khandakar (2008)
- **[DeepAR: Probabilistic Forecasting with Autoregressive Recurrent Networks](https://arxiv.org/abs/1704.04110)** · David Salinas, Valentin Flunkert, Jan Gasthaus (2017) · [PDF](https://arxiv.org/pdf/1704.04110)
- **[Forecasting at Scale](https://doi.org/10.1080/00031305.2017.1380080)** 💲 · Sean J. Taylor, Benjamin Letham (2017) — Prophet.
- **[N-BEATS: Neural basis expansion analysis for interpretable time series forecasting](https://arxiv.org/abs/1905.10437)** · Boris N. Oreshkin, Dmitri Carpov, Nicolas Chapados, Yoshua Bengio (2019) · [PDF](https://arxiv.org/pdf/1905.10437)
- **[Temporal Fusion Transformers for Interpretable Multi-horizon Time Series Forecasting](https://arxiv.org/abs/1912.09363)** · Bryan Lim, Sercan O. Arik, Nicolas Loeff, Tomas Pfister (2019) · [PDF](https://arxiv.org/pdf/1912.09363)
- **[Informer: Beyond Efficient Transformer for Long Sequence Time-Series Forecasting](https://arxiv.org/abs/2012.07436)** · Haoyi Zhou, Shanghang Zhang, Jieqi Peng, Shuai Zhang et al. (2020) · [PDF](https://arxiv.org/pdf/2012.07436)
- **[Autoformer: Decomposition Transformers with Auto-Correlation for Long-Term Series Forecasting](https://arxiv.org/abs/2106.13008)** · Haixu Wu, Jiehui Xu, Jianmin Wang, Mingsheng Long (2021) · [PDF](https://arxiv.org/pdf/2106.13008)
- **[A Time Series is Worth 64 Words: Long-term Forecasting with Transformers](https://arxiv.org/abs/2211.14730)** · Yuqi Nie, Nam H. Nguyen, Phanwadee Sinthong, Jayant Kalagnanam (2022) · [PDF](https://arxiv.org/pdf/2211.14730)
- **[Are Transformers Effective for Time Series Forecasting?](https://arxiv.org/abs/2205.13504)** · Ailing Zeng, Muxi Chen, Lei Zhang, Qiang Xu (2022) · [PDF](https://arxiv.org/pdf/2205.13504)
- **[A decoder-only foundation model for time-series forecasting](https://arxiv.org/abs/2310.10688)** · Abhimanyu Das, Weihao Kong, Rajat Sen, Yichen Zhou (2023) · [PDF](https://arxiv.org/pdf/2310.10688)
- **[Chronos: Learning the Language of Time Series](https://arxiv.org/abs/2403.07815)** · Abdul Fatir Ansari, Lorenzo Stella, Caner Turkmen, Xiyuan Zhang et al. (2024) · [PDF](https://arxiv.org/pdf/2403.07815)

### Survey / tutorial académico

- **[Time Series Forecasting With Deep Learning: A Survey](https://arxiv.org/abs/2004.13408)** · Bryan Lim, Stefan Zohren (2020) · [PDF](https://arxiv.org/pdf/2004.13408)

### Documentación oficial

- **[Prophet Documentation](https://facebook.github.io/prophet/)** · Meta (2024)
- **[sktime Documentation](https://www.sktime.net/en/stable/)** · sktime developers (2024)
- **[statsmodels: Time Series Analysis](https://www.statsmodels.org/stable/tsa.html)** · statsmodels developers (2024)

## Sistemas de recomendación

### Paper

- **[Collaborative Filtering for Implicit Feedback Datasets](https://doi.org/10.1109/ICDM.2008.22)** 💲 · Yifan Hu, Yehuda Koren, Chris Volinsky (2008)
- **[Matrix Factorization Techniques for Recommender Systems](https://doi.org/10.1109/MC.2009.263)** 💲 · Yehuda Koren, Robert Bell, Chris Volinsky (2009)
- **[Factorization Machines](https://doi.org/10.1109/ICDM.2010.127)** 💲 · Steffen Rendle (2010)
- **[BPR: Bayesian Personalized Ranking from Implicit Feedback](https://arxiv.org/abs/1205.2618)** · Steffen Rendle, Christoph Freudenthaler, Zeno Gantner, Lars Schmidt-Thieme (2012) · [PDF](https://arxiv.org/pdf/1205.2618)
- **[Session-based Recommendations with Recurrent Neural Networks](https://arxiv.org/abs/1511.06939)** · Balázs Hidasi, Alexandros Karatzoglou, Linas Baltrunas, Domonkos Tikk (2015) · [PDF](https://arxiv.org/pdf/1511.06939)
- **[Deep Neural Networks for YouTube Recommendations](https://doi.org/10.1145/2959100.2959190)** 💲 · Paul Covington, Jay Adams, Emre Sargin (2016)
- **[Wide & Deep Learning for Recommender Systems](https://arxiv.org/abs/1606.07792)** · Heng-Tze Cheng, Levent Koc, Jeremiah Harmsen, Tal Shaked et al. (2016) · [PDF](https://arxiv.org/pdf/1606.07792)
- **[DeepFM: A Factorization-Machine based Neural Network for CTR Prediction](https://arxiv.org/abs/1703.04247)** · Huifeng Guo, Ruiming Tang, Yunming Ye, Zhenguo Li et al. (2017) · [PDF](https://arxiv.org/pdf/1703.04247)
- **[Neural Collaborative Filtering](https://arxiv.org/abs/1708.05031)** · Xiangnan He, Lizi Liao, Hanwang Zhang, Liqiang Nie et al. (2017) · [PDF](https://arxiv.org/pdf/1708.05031)
- **[Self-Attentive Sequential Recommendation](https://arxiv.org/abs/1808.09781)** · Wang-Cheng Kang, Julian McAuley (2018) · [PDF](https://arxiv.org/pdf/1808.09781)
- **[BERT4Rec: Sequential Recommendation with Bidirectional Encoder Representations from Transformer](https://arxiv.org/abs/1904.06690)** · Fei Sun, Jun Liu, Jian Wu, Changhua Pei et al. (2019) · [PDF](https://arxiv.org/pdf/1904.06690)

## Interpretabilidad, explicabilidad y causalidad

### Libro

- **[Fairness and Machine Learning: Limitations and Opportunities](https://fairmlbook.org/)** · Solon Barocas, Moritz Hardt, Arvind Narayanan (2023) — Equidad en ML. Gratuito en línea.
- **[Causal Inference: What If](https://miguelhernan.org/whatifbook)** · Miguel A. Hernán, James M. Robins (2024) — Inferencia causal para datos observacionales. PDF gratuito.
- **[Interpretable Machine Learning](https://christophm.github.io/interpretable-ml-book/)** · Christoph Molnar (2024) — Guía de métodos de interpretabilidad (PDP, SHAP, LIME...). Gratuito en línea.

### Paper

- **[Causal inference in statistics: An overview](https://doi.org/10.1214/09-SS057)** · Judea Pearl (2009) — Panorama de Pearl sobre causalidad.
- **[Deep Inside Convolutional Networks: Visualising Image Classification Models and Saliency Maps](https://arxiv.org/abs/1312.6034)** · Karen Simonyan, Andrea Vedaldi, Andrew Zisserman (2013) · [PDF](https://arxiv.org/pdf/1312.6034)
- **["Why Should I Trust You?": Explaining the Predictions of Any Classifier](https://arxiv.org/abs/1602.04938)** · Marco Tulio Ribeiro, Sameer Singh, Carlos Guestrin (2016) · [PDF](https://arxiv.org/pdf/1602.04938) — LIME.
- **[Grad-CAM: Visual Explanations from Deep Networks via Gradient-based Localization](https://arxiv.org/abs/1610.02391)** · Ramprasaath R. Selvaraju, Michael Cogswell, Abhishek Das, Ramakrishna Vedantam et al. (2016) · [PDF](https://arxiv.org/pdf/1610.02391)
- **[The Mythos of Model Interpretability](https://arxiv.org/abs/1606.03490)** · Zachary C. Lipton (2016) · [PDF](https://arxiv.org/pdf/1606.03490)
- **[A Unified Approach to Interpreting Model Predictions](https://arxiv.org/abs/1705.07874)** · Scott Lundberg, Su-In Lee (2017) · [PDF](https://arxiv.org/pdf/1705.07874) — SHAP.
- **[Axiomatic Attribution for Deep Networks](https://arxiv.org/abs/1703.01365)** · Mukund Sundararajan, Ankur Taly, Qiqi Yan (2017) · [PDF](https://arxiv.org/pdf/1703.01365)
- **[Counterfactual Explanations without Opening the Black Box: Automated Decisions and the GDPR](https://arxiv.org/abs/1711.00399)** · Sandra Wachter, Brent Mittelstadt, Chris Russell (2017) · [PDF](https://arxiv.org/pdf/1711.00399)
- **[Towards A Rigorous Science of Interpretable Machine Learning](https://arxiv.org/abs/1702.08608)** · Finale Doshi-Velez, Been Kim (2017) · [PDF](https://arxiv.org/pdf/1702.08608)
- **[Consistent Individualized Feature Attribution for Tree Ensembles](https://arxiv.org/abs/1802.03888)** · Scott M. Lundberg, Gabriel G. Erion, Su-In Lee (2018) · [PDF](https://arxiv.org/pdf/1802.03888)
- **[Towards Causal Representation Learning](https://arxiv.org/abs/2102.11107)** · Bernhard Schölkopf, Francesco Locatello, Stefan Bauer, Nan Rosemary Ke et al. (2021) · [PDF](https://arxiv.org/pdf/2102.11107)

### Survey / tutorial académico

- **[A Survey on Bias and Fairness in Machine Learning](https://arxiv.org/abs/1908.09635)** · Ninareh Mehrabi, Fred Morstatter, Nripsuta Saxena, Kristina Lerman et al. (2019) · [PDF](https://arxiv.org/pdf/1908.09635)

### Artículo divulgativo

- **[Zoom In: An Introduction to Circuits](https://distill.pub/2020/circuits/zoom-in/)** · Chris Olah, Nick Cammarata, Ludwig Schubert, et al. (2020)

### Documentación oficial

- **[SHAP Documentation](https://shap.readthedocs.io/)** · Scott Lundberg (2024)

## Práctica: evaluación, datos y MLOps

### Libro

- **[Feature Engineering and Selection: A Practical Approach for Predictive Models](https://bookdown.org/max/FES/)** · Max Kuhn, Kjell Johnson (2019) — Ingeniería y selección de variables. Gratuito en línea.
- **[Mining of Massive Datasets (3rd ed.)](http://www.mmds.org/)** · Jure Leskovec, Anand Rajaraman, Jeffrey D. Ullman (2020) — Algoritmos para datos masivos: similitud (LSH), streams, recomendación, clustering. PDF gratuito.
- **[Think Stats (3rd ed.)](https://greenteapress.com/wp/think-stats-3e/)** · Allen B. Downey (2024) — Estadística con Python. Gratuito.

### Paper

- **[An introduction to ROC analysis](https://doi.org/10.1016/j.patrec.2005.10.010)** 💲 · Tom Fawcett (2006)
- **[The relationship between Precision-Recall and ROC curves](https://doi.org/10.1145/1143844.1143874)** 💲 · Jesse Davis, Mark Goadrich (2006)
- **[SMOTE: Synthetic Minority Over-sampling Technique](https://arxiv.org/abs/1106.1813)** · N. V. Chawla, K. W. Bowyer, L. O. Hall, W. P. Kegelmeyer (2011) · [PDF](https://arxiv.org/pdf/1106.1813)
- **[Scikit-learn: Machine Learning in Python](https://www.jmlr.org/papers/v12/pedregosa11a.html)** · Fabian Pedregosa, et al. (2011)
- **[A Few Useful Things to Know about Machine Learning](https://doi.org/10.1145/2347736.2347755)** 💲 · Pedro Domingos (2012) — Doce lecciones prácticas del ML.
- **[Leakage in data mining: Formulation, detection, and avoidance](https://doi.org/10.1145/2382577.2382579)** 💲 · Shachar Kaufman, Saharon Rosset, Claudia Perlich, Ori Stitelman (2012)
- **[Practical Bayesian Optimization of Machine Learning Algorithms](https://arxiv.org/abs/1206.2944)** · Jasper Snoek, Hugo Larochelle, Ryan P. Adams (2012) · [PDF](https://arxiv.org/pdf/1206.2944)
- **[Random Search for Hyper-Parameter Optimization](https://www.jmlr.org/papers/v13/bergstra12a.html)** · James Bergstra, Yoshua Bengio (2012)
- **[Hidden Technical Debt in Machine Learning Systems](https://papers.nips.cc/paper_files/paper/2015/hash/86df7dcfd896fcaf2674f757a2463eba-Abstract.html)** · D. Sculley, et al. (2015)
- **[Hyperband: A Novel Bandit-Based Approach to Hyperparameter Optimization](https://arxiv.org/abs/1603.06560)** · Lisha Li, Kevin Jamieson, Giulia DeSalvo, Afshin Rostamizadeh et al. (2016) · [PDF](https://arxiv.org/pdf/1603.06560)
- **[Datasheets for Datasets](https://arxiv.org/abs/1803.09010)** · Timnit Gebru, Jamie Morgenstern, Briana Vecchione, Jennifer Wortman Vaughan et al. (2018) · [PDF](https://arxiv.org/pdf/1803.09010)
- **[Model Cards for Model Reporting](https://arxiv.org/abs/1810.03993)** · Margaret Mitchell, Simone Wu, Andrew Zaldivar, Parker Barnes et al. (2018) · [PDF](https://arxiv.org/pdf/1810.03993)
- **[Optuna: A Next-generation Hyperparameter Optimization Framework](https://arxiv.org/abs/1907.10902)** · Takuya Akiba, Shotaro Sano, Toshihiko Yanase, Takeru Ohta et al. (2019) · [PDF](https://arxiv.org/pdf/1907.10902)
- **[PyTorch: An Imperative Style, High-Performance Deep Learning Library](https://arxiv.org/abs/1912.01703)** · Adam Paszke, Sam Gross, Francisco Massa, Adam Lerer et al. (2019) · [PDF](https://arxiv.org/pdf/1912.01703)

### Formulario / cheat sheet

- **[CS229 Cheatsheet: Machine Learning Tips and Tricks](https://stanford.edu/~shervine/teaching/cs-229/cheatsheet-machine-learning-tips-and-tricks)** · Afshine Amidi, Shervine Amidi (2018) — Hoja de fórmulas de métricas, selección de modelos y diagnóstico.
- **[Machine Learning Glossary](https://developers.google.com/machine-learning/glossary)** · Google (2024) — Glosario de términos de ML con definiciones breves.
- **[scikit-learn: Choosing the right estimator (mapa)](https://scikit-learn.org/stable/machine_learning_map.html)** · scikit-learn developers (2024) — Diagrama para elegir el algoritmo según el problema y los datos.

### Artículo divulgativo

- **[Rules of Machine Learning: Best Practices for ML Engineering](https://developers.google.com/machine-learning/guides/rules-of-ml)** · Martin Zinkevich (2017)
- **[Deep Learning Tuning Playbook](https://github.com/google-research/tuning_playbook)** · Varun Godbole, George E. Dahl, Justin Gilmer, Christopher J. Shallue et al. (2023) — Guía de Google para ajustar hiperparámetros de redes.

### Documentación oficial

- **[MLflow Documentation](https://mlflow.org/docs/latest/index.html)** · MLflow (2024)
- **[imbalanced-learn Documentation](https://imbalanced-learn.org/stable/)** · imbalanced-learn developers (2024)
- **[scikit-learn User Guide](https://scikit-learn.org/stable/user_guide.html)** · scikit-learn developers (2024) — La guía de usuario completa de scikit-learn, con la teoría de cada estimador.
- **[scikit-learn: Model evaluation (metrics and scoring)](https://scikit-learn.org/stable/modules/model_evaluation.html)** · scikit-learn developers (2024)
