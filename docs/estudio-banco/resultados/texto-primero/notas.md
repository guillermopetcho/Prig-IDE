# T7 corta — notas de análisis (se completan con cada respuesta)

## Prig, modo general
- ind_15 (delete_item, instancia global) · 138 s (incluye arranque) · 8 consultas · hechos 1256 car.
  Encuentra la llamada exacta (app.py:450 `book_service.delete_item(req.id)`) pero no nombra la función (delete_book)
  e inventa la ruta («DELETE /api/books/<id> o similar»; es POST /api/books/delete). Los hechos ya traían
  «delete_book (app.py:450 …)»: los ignoró y rehízo la búsqueda (8 consultas). → PARCIAL (E7: incorrecta, «nadie la llama").
- ind_16 (radiografia, fábrica) · 17,7 s · 0 consultas · hechos 1576 car.
  Los hechos traían los 2 llamadores que faltaban (`recursos_gestor().radiografia(fresca=True)`); el modelo los vio y los
  DESCARTÓ inventando que la pregunta pedía solo llamadas internas de la clase. 2 de 4 → PARCIAL (igual que E7, pero
  ahora con la información delante).
- f46b5c0819d3 (impacto historial) · 110 s · 8 consultas (incl. leer_archivo) · hechos 2707 car.
  GET /api/inicio (lambda) + GET /api/progreso/historial (pasada como argumento) + POST /api/progreso/analisis; descarta
  bien el homónimo mon.historial. Falta GET /api/progreso/resumen (2 saltos: progreso.resumen pasado a _desafio). 3/4 →
  PARCIAL alta (E7: 3/4 con otro faltante). Los llamadores por texto son de un solo nivel.
- a84a7fe1bad7 (config truncar) · 14,4 s · 0 consultas · hechos 822 car.
  _ajustes (bien: la lectora real, la sacó de «as literal text … in IndiceSemantico._ajustes») + ConfigModelos._leer
  (MAL: esa línea define el valor por defecto, no lo lee); omite embeber y estado, que los hechos traían bajo lee_config.
  Se quedó con las apariciones literales y descartó los hechos del grafo. → PARCIAL (E7: parcial). Los hechos sacaron
  la respuesta que faltaba pero metieron un falso positivo: «aparece como texto» no distingue leer, escribir y definir.
- 29b468d8a2cb (impacto rebind_workspace) · 26,9 s · 0 consultas · hechos 471 car.
  POST /api/workspace/open y /browse exactas (de los hechos: «endpoints reached through the graph»), más el impacto
  indirecto bien explicado. → CORRECTA (E7: parcial, nombró las funciones sin las rutas). Modo de falla ARREGLADO.
- 12bb842411c5 (impacto cleanup_all_processes) · 39,5 s · 0 consultas · hechos 565 car.
  Lo directo bien: POST /api/app/shutdown exacta (E7 la inventó: /api/shutdown) y los otros llamadores reales (lifespan,
  main.py:171 shutdown_prig, verificado). En el impacto «indirecto» INVENTA rutas: /api/chat, /api/chat/inline,
  /api/chat/workflow (no existen; la real es /api/ai/chat), y muestra «código inferido» con un `async` que no está.
  → PARCIAL (E7: incorrecta). La ruta pedida quedó arreglada por los hechos; lo que agrega por su cuenta sigue inventado.
- 0b5f93c17f28 (recorrido modelos_borrar_parciales → librerias_disponibles) · 20,8 s · 0 consultas · hechos 924 car.
  Vuelve a NEGAR el camino (que el grafo tiene: de ahí salió la pregunta; P.camino lo encuentra). Nombra las dos piezas
  (_carpeta_modelos_servidor() y que estado llama a librerias_disponibles) sin unirlas, y no consulta nada.
  → INCORRECTA (E7: incorrecta). Los hechos miran cada nombre por separado: no traen el camino entre dos símbolos.
  ARREGLO: si la pregunta nombra dos símbolos, sumar P.camino entre ellos a los hechos.
- d408dee5873f (recorrido recursos_ritmo → ControladorFrio) · 20,1 s · 0 consultas · hechos 1082 car.
  Niega el camino (recursos_ritmo → gobernador() → Gobernador.__init__ → ControladorFrio) aunque dice que ControladorFrio
  «se inicia en Gobernador.__init__». Matiz: el camino solo se recorre la primera vez (cuando se crea el gobernador),
  así que en régimen estable tiene algo de razón, pero niega un camino real. → INCORRECTA (E7: incorrecta). Mismo arreglo
  que el anterior (camino entre los dos símbolos en los hechos).
- ind_27 (diseño: expertos calientes) · 35,1 s · 0 consultas · hechos 0 (la pregunta no nombra código).
  Los 3 puntos de la rúbrica con el código literal que trajo componer (calientes_para, asegurar); constantes y líneas
  verificadas (370, 250, 68,65, 56; l.295, 202, 914-919). La secuencia de reintentos, algo simplificada (prueba con y sin
  MTP, con n y n-8). → CORRECTA (E7: agotada con 28 consultas en modo unidad). El contexto literal del modo general evitó
  el bucle de consultas.
- 1f14bd2a14dd (entorno KAGGLE_API_TOKEN) · 20,8 s · 1 consulta · hechos 1331 car.
  credenciales (kaggle_lector.py:89), verificado. → CORRECTA (E7: agotada vacía, bucle de texto). El bucle de E7 fue
  azaroso: una corrida no prueba que el tope lo evite; sí que la pregunta se responde bien.
- 02bd1db0d170 (llamadores escribir_manifiesto) · 18,3 s · 0 consultas · hechos 370 car.
  Hub._crear y Hub.editar_manifiesto (l.151 y 222, exactas). → CORRECTA (E7: salida degenerada «...» tras 17 consultas).
- 8caebf27e7ba (control: constante MESETA_S) · 14,7 s. 20.0, bien; la línea mal (dice 22; es 60). → CORRECTA (E7: correcta).

Criterio, igual que en E7: un impacto con todos los endpoints del grafo más otros reales, al que le falta uno de dos
saltos, cuenta como correcto (así se juzgó f46b5c0819d3 en E7). Corrijo f46b5c0819d3 general → CORRECTA (3/4, como E7).

### Resumen del modo general (11 preguntas de falla + 1 control, 476 s, sin agotadas ni vacías)
- correctas 5/11: 29b468 (rutas), ind_27 (diseño, sin bucle), 1f14bd (entorno), 02bd1d (llamadores), f46b5c (impacto 3/4)
- parciales 4/11: ind_15 (encuentra la línea, sin el nombre), ind_16 (descarta los llamadores externos), a84a7f (un falso
  positivo), 12bb84 (núcleo bien, rutas indirectas inventadas)
- incorrectas 2/11: 0b5f93 y d408de (niegan caminos que existen)
- control: correcto
- En E7, esas 11: 1 correcta, 3 parciales, 7 incorrectas (casi todas en modo unidad, sin los cambios de hoy).

## Prig, modo unidad
(en modo unidad los hechos van dentro de la pregunta: el evento del banco no informa su tamaño, por eso «0»)
- ind_15 · 30,9 s · 1 consulta (P.ficha) · unidad «backend: book_service» vigente.
  «delete_book en backend/app.py:450 (res = book_service.delete_item(req.id))», tomado de los hechos («Project Bank … posible
  llamador por texto»). → CORRECTA (E7 unidad: incorrecta 3 de 3; hoy en general: parcial, porque ignoró esos hechos).
- ind_16 · 42,3 s · 1 consulta (P.llamadores, que ahora suma lo de texto).
  Los 4 reales (maquina, estado_vivo, recursos_servidor_aplicar y _num_gpus por la fábrica) + calibrar, que es FALSO
  POSITIVO (calibracion.py:535 `Maquina(maq.radiografia, …)` es un atributo de otro objeto: ruido de la búsqueda por texto,
  patrón «pasada como valor»). → CORRECTA con 1 falso positivo (E7: parcial; hoy en general: parcial, descartó los
  externos).
- f46b5c0819d3 · 84,9 s · 7 consultas · fue a MODO GENERAL aun con «unidad» forzado: «la pregunta reparte su peso entre
  unidades (la mejor tiene 29 %)» (por diseño: sin unidad dominante no se fuerza ninguna). Es una segunda muestra del
  general: esta vez 4/4 (inicio, historial, resumen por dos saltos, analisis). → CORRECTA. Ruido del muestreo: la misma
  pregunta, 3/4 y 4/4.
- a84a7fe1bad7 (config truncar) · 19,3 s · 1 consulta: P.hechos(r="lee_config") (la herramienta correcta; en E7 usó
  P.llamadores y recibió []). embeber y estado (lo del grafo); omite _ajustes, la lectora real, que venía en los hechos como
  texto literal. → PARCIAL (2/3). Los dos modos fallan en direcciones opuestas: el general se quedó con el texto literal
  (_ajustes + un falso _leer) y el de unidad con el grafo (embeber, estado). La respuesta completa es la unión → los
  hechos tienen que presentar mejor la lectura directa de una clave (e.get("clave")) frente a sus consumidores.
- 29b468d8a2cb (impacto rebind_workspace) · 31,3 s · 2 consultas. Las dos rutas exactas → CORRECTA (E7: parcial).
  Razonamiento confuso: primero «la única vía es browse», después agrega open «que el grafo no resolvió» (falso: lo
  resolvió). Eco del código P al principio del texto (como en E7).
- 12bb842411c5 (impacto cleanup_all_processes) · 23,2 s · 1 consulta (P.impacto). POST /api/app/shutdown exacta, lifespan
  y main.py shutdown_prig (reales), y dice explícitamente que no hay otros endpoints. → CORRECTA, sin invenciones
  (E7: incorrecta; hoy en general: parcial, inventó rutas indirectas).
- 0b5f93c17f28 · 30,8 s · 0 consultas · fue a MODO GENERAL («reparte su peso», la mejor 27 %). Vuelve a NEGAR el camino, con
  una afirmación falsa explícita («no llama a ninguna función del módulo servidor»: llama _carpeta_modelos_servidor →
  recursos_srv.estado). → INCORRECTA. Dos muestras, el mismo error: es sistemático, no ruido.
- d408dee5873f · 62,7 s · 6 consultas · fue a MODO GENERAL («reparte su peso», la mejor 24 %). Vuelve a negar el camino,
  aunque muestra el código exacto donde Gobernador.__init__ crea ControladorFrio (termico.py:365): razona en régimen estable
  (el gobernador ya existe) y no ve que la primera llamada a gobernador() lo crea. → INCORRECTA (con el matiz de antes).
  Las dos de recorrido unen dos partes del proyecto: nunca caen en una sola unidad; el arreglo tiene que ir en los hechos
  (camino entre los dos símbolos), no en el modo.
- ind_27 (diseño: expertos calientes) · 93,4 s · 5 consultas (2 P.ficha, 3 ver_simbolo) · unidad «backend/ai_engine:
  motor_moe, web_search_engine» vigente. Sin bucle (E7 en unidad: 28 consultas, agotada). Fórmula de calientes_para exacta,
  automático frente a fijo bien, Motor.asegurar l.892 bien. PERO da como «orden exacto» una secuencia de reintentos que no
  es la del código: dice (n, MTP) → (n, sin MTP) → (n-8, MTP) → (n-8, sin MTP) → (0, sin MTP); el código hace
  (n₁, MTP) → (n₁-8, MTP) → (n₂, sin MTP) → (n₂-8, sin MTP) → (0, sin MTP), y n₂ se RECALCULA sin MTP (caben más, no «el
  mismo número»). Inventa la ruta del registro («/var/log/prig.log»; es ~/.prig_moe.log, REGISTRO l.39).
  → PARCIAL alta: la rúbrica está, pero afirma como exacto un detalle falso de lo que se pregunta (mismo criterio que
  12bb general). El general la contestó mejor: secuencia incompleta pero sin nada falso.
- 1f14bd2a14dd (entorno KAGGLE_API_TOKEN) · 12,7 s · 0 consultas · unidad «backend: kaggle_colecciones, kaggle_lector».
  credenciales() l.89, la única lectora (grep: solo kaggle_lector.py:89-90). → CORRECTA (E7: agotada vacía).
- 02bd1db0d170 (llamadores escribir_manifiesto) · 18,1 s · 1 consulta (P.llamadores) · unidad «backend/hub: enlaces,
  formato». Hub._crear l.151 y Hub.editar_manifiesto l.222 (grep: son los dos únicos). → CORRECTA (E7: salida «...»).
- 8caebf27e7ba (control MESETA_S) · 13,4 s · 0 consultas · fue a MODO GENERAL: «repartida entre unidades (la mejor tiene
  57 %)». Pasa el mínimo de cuota (35 %) pero no la segunda regla de elegir_unidad (la mejor ≥ 1,5 × la segunda):
  [CORREGIDO tras medirlo sin modelo: termico.py está en UNA sola unidad. La causa: MESETA_S no está en la tabla de símbolos (las constantes no se indexan) y no suma los 3 puntos de un nombre; las palabras de la ruta «recursos», «termico», «backend» cuentan como identificadores y reparten: 5,36 contra 4,0, menos de 1,5×.] Valor 20.0 bien; línea mal
  otra vez (dice 39; es 60). → CORRECTA (el valor), con la línea mal en las dos corridas.

### Resumen de la corrida «unidad» (11 de falla + control, 463 s, sin agotadas ni vacías)
- 4 de 12 se respondieron en modo general aunque se pidió unidad (f46b, 0b5f, d408 y el control): el enrutador no fuerza
  una unidad si la pregunta no tiene una dominante. Las dos de recorrido, por naturaleza, nunca la tienen.
- correctas 7/11: ind_15, ind_16 (+1 falso positivo de la herramienta), f46b (en general, 4/4), 29b4, 12bb, 1f14, 02bd
- parciales 2/11: a84a (el grafo sin la lectora literal), ind_27 (orden de reintentos falso)
- incorrectas 2/11: 0b5f, d408 (en general: niegan el camino; 4 de 4 muestras entre las dos corridas)
- control: correcto (en general)
- Solo las 8 que de verdad se respondieron en unidad: unidad 6 C / 2 P / 0 I; las mismas 8 en la corrida general:
  4 C / 4 P / 0 I. Diferencias: ind_15, ind_16 y 12bb a favor de unidad; ind_27 a favor de general.

## E8, modo general (5 preguntas «¿tiene algún error?», 300 s, sin agotadas ni vacías)
Errores inyectados (diff contra la copia limpia): B2 particion_proyecto.py:97 `a = n + 1` (debía ser `n`: la línea del
corte no queda en ninguna pieza); B3 file_manager.py:40 `abs_path.startswith(root)` (acepta /ws-otro si la raíz es /ws);
B6 job_exporter.py:93 `ajustes.get("max_chunks_tokens")` (la clave buena, max_chunk_tokens, la escriben
sondeo_libro.py:516, explorador.js:476/559 y la misma función en l.170: el ajuste por libro se ignora siempre);
B7 banco_proyecto.py:712-713 sin try/finally ni close (la conexión queda abierta; con una excepción, además, la
transacción queda abierta con su cerrojo hasta que la recoja el GC → «database is locked» en los otros hilos).
- E8a_B2 · 178,2 s (incluye arranque) · 4 consultas (consola: copia la función, intenta importarla, la «simula» con un
  caso propio) · hechos 326 car. NO LO DETECTA: prueba el bucle de los hijos, no el corte por líneas, y presenta como
  error que el código entre dos métodos queda en la pieza del método siguiente (es la cobertura contigua por diseño, sin
  pérdida; a lo sumo una etiqueta imprecisa) → FALSO POSITIVO en lugar del error real.
- E8a_B3 · 22,5 s · 0 consultas · hechos 509 car. LO DETECTA: l.40 exacta, caso /home/usuario/workspace_malicioso/…,
  impacto (leer/escribir/borrar fuera del workspace), las otras raíces afectadas, arreglo correcto (== root o
  startswith(root + os.sep)).
- E8a_B6 · 46,4 s · 0 consultas · hechos 1079 car. NO LO DETECTA y la salida es DEGENERADA: «el error está en la línea
  159 … Espera … esto es correcto» seis veces, y cierra «no hay un error de programación obvio». Nunca mira la l.93.
- E8a_B7 · 28,5 s · 0 consultas · hechos 1813 car. NO LO DETECTA: «no tiene ningún error», inventa un «finally implícito
  del contextmanager», dice Flask (es FastAPI) y lo compara con KnowledgeBase.conectar, que tampoco cierra (ese es un
  patrón real del proyecto: sqlite3 como context manager confirma, no cierra).
- E8a_C2 (control) · 24,5 s · 0 consultas · hechos 1149 car. «No tiene errores» → CORRECTO, sin falso positivo. Pero
  afirma que «las rutas con .. quedan bloqueadas», falso EN ESTA COPIA: resolve delega en is_path_allowed, que tiene B3
  (/ws/../ws-otro/x → /ws-otro/x pasa). Describe is_path_allowed como «comienza con» sin ver el agujero.
- Resumen general: 1 de 4 errores (B3), 1 falso positivo (B2), control limpio. Los tres que no ve se ven en el texto de la
  función misma (n+1, «chunks», falta close): son fallas de lectura atenta con think=False, no de contexto.

## E8, modo unidad
- E8a_B2 · 389,8 s (arranque + lectura al vuelo de la unidad 64, 11K tokens: T5 funcionó, «forzado: … no tiene lectura
  guardada; se lee ahora», y guardó el estado nuevo, 252 MB) · 8 consultas (3 P.leer + 5 «simulaciones» escritas como
  comentarios). NO LO DETECTA: llega a mirar el bucle de corte por líneas («¿qué pasa si el primer trozo alcanza el
  tope?») y lo abandona; repite el falso positivo del general (el código suelto queda en la pieza del primer hijo) y
  agrega una pérdida «entre m1 y m2» que no existe (cur = fin+1 y la pieza siguiente empieza ahí). → FALSO POSITIVO.
  La consola no puede importar el proyecto (lista blanca de módulos, E5): no puede ejecutar la función con un caso, solo
  reescribirla; ninguno de los dos modos eligió el caso que la rompe (un tramo sin hijos más grande que el tope).
- E8a_B3 · 63,8 s (incluye leer al vuelo «backend: file_manager, ide_servicios», vencida) · 0 consultas. NO LO DETECTA y
  afirma lo contrario con seguridad: «el caso /workspace vs /workspace2 está protegido porque startswith se aplica sobre la
  ruta ya normalizada» (falso: "/workspace2".startswith("/workspace") es True). Ve el rastro del cambio (el except
  ValueError de commonpath «aunque en el código actual no se usa commonpath») y lo justifica. → NO DETECTA, con una
  afirmación de seguridad falsa. El general lo encontró (22,5 s, 0 consultas): primera diferencia a favor del general.
- E8a_B6 · 146,3 s (incluye leer al vuelo la unidad 67, 14K tokens) · 3 consultas (P.codigo de la función, P.lineas
  139-206, anotar rechazado: memoria apagada, no escribió nada). NO LO DETECTA: mismo patrón degenerado que el general
  («Espera, revisemos mejor… esto está bien» ×3) y termina en un FALSO POSITIVO: el literal 120 de la l.117 (umbral de
  texto por página para detectar PDF escaneados) «debería ser min_chars» (umbral de largo de fragmento: otro concepto; su
  caso supone fragmento = página). La l.93 le llegó: P.codigo devuelve hasta 6.000 caracteres (el «2000» de la sonda es
  la vista previa del evento, resultado[:2000]; el modelo ve hasta MAX_SALIDA = 6000).
- E8a_B7 · 72,7 s (incluye leer al vuelo las 3 unidades vencidas de banco_proyecto: la elegida, «backend: banco_proyecto»)
  · 0 consultas. NO LO DETECTA: «no hay error»; dice que el commit corre «al salir del bloque with … por return/excepción»
  (falso: con excepción no corre) y que entrega «el cursor» (es la conexión); no menciona que nunca se cierra.
- E8a_C2 (control) · 14,4 s · 0 consultas · «lectura guardada de la unidad»: la que T5 leyó y guardó en B3 (el caché
  funciona entre preguntas). «No tiene errores» → CORRECTO, sin falso positivo; igual que el general, afirma que no hay
  huecos «por rutas relativas maliciosas» (falso en esta copia por B3).

### Resumen de E8 (los 4 errores que ningún test detecta + 1 control; 300 s general, 687 s unidad con 4 lecturas al vuelo)
| | B2 n+1 | B3 startswith | B6 clave | B7 sin close | C2 control |
|---|---|---|---|---|---|
| general | no (falso positivo) | SÍ (l.40, caso, arreglo) | no (salida degenerada) | no | limpio |
| unidad  | no (falso positivo) | no («está protegido», falso) | no (falso positivo + degenerada) | no | limpio |
- Detecta: general 1 de 4, unidad 0 de 4. Falsos positivos: general 1, unidad 2. Ninguno de los dos sirve hoy para
  «revisar código» con think=False: los 3 errores que ninguno ve están en el texto de la función que tenía delante.
- T5 en uso real: 4 unidades vencidas leídas al vuelo (motivo «forzado: … se lee ahora») y reaprovechadas (C2 restauró
  la de B3). Sin errores.

## Segunda tanda (T7: «si el resultado es dudoso»): las que difirieron, otra muestra de cada modo + general con los
## hechos al final (gf: arnés, sonda.py «hechos_al_final»; el sistema congelado no cambia)
Posición medida sin modelo (ind_15): hoy el general pone los hechos en la posición 0 y el paquete del banco (21.083 car.)
los separa de la pregunta; con «al final» quedan pegados a la pregunta, como en unidad.
- ind_15·g2 (general, 2.ª muestra) · 55,7 s · 3 consultas (P.hechos ×2, leer_archivo). delete_book, app.py:446-450,
  POST /api/books/delete (verificado l.445). → CORRECTA. La 1.ª muestra fue PARCIAL: en ind_15 la diferencia entre modos
  era, al menos en parte, ruido del muestreo.
- ind_15·gf (general, hechos al final) · 32,6 s · 3 consultas. delete_book + la ruta exacta + el código, y descarta en
  forma explícita el homónimo file_mgr.delete_item (app.py:3090, FileManager) que traían los hechos. → CORRECTA (la más
  precisa de las tres).
- ind_15·u2 (unidad, 2.ª muestra) · 7,0 s · 0 consultas. «delete_book en backend/app.py (línea 450)». → CORRECTA (mínima).
- ind_16·g2 (general, 2.ª muestra) · 21,6 s · 0 consultas. Los 4 reales (Gestor.maquina l.55, Gestor.estado_vivo l.150,
  recursos_servidor_aplicar app.py:5387, _num_gpus app.py:5631; verificados con grep y la función que los contiene), sin
  falsos positivos; el encuadre es raro («aunque no llaman directamente… sí invocan a través del gestor») pero los lista.
  → CORRECTA. La 1.ª muestra (PARCIAL, descartó los externos) no se repite: como en ind_15, era sobre todo ruido.
- ind_16·gf (general, hechos al final) · 60,9 s · 4 consultas (P.llamadores y luego verifica cada «sin resolver»). Los 4
  reales, y descarta en forma explícita el falso positivo calibracion.py:535 (maq.radiografia, atributo de Maquina) y el
  homónimo detector.radiografia. → CORRECTA (la más precisa de todas las de ind_16: la de unidad de la 1.ª corrida incluyó
  ese falso positivo). Con los hechos pegados a la pregunta, el modelo VERIFICA lo «sin resolver» (como pide el
  encabezado de los hechos: «confirm with the console when it matters»).
- ind_16·u2 (unidad, 2.ª muestra) · 44,4 s · 1 consulta (P.llamadores). Los 4 reales + calibrar (calibracion.py:535,
  «pasa maq.radiografia como atributo/valor»): el MISMO falso positivo que la 1.ª muestra → CORRECTA con 1 falso positivo.
  Es sistemático: lo produce el patrón «como valor» de los llamadores por texto y el modo unidad repite la herramienta
  sin verificar; el general con hechos al final lo verificó y lo descartó.
- 12bb·g2 (general, 2.ª muestra) · 57,6 s · 4 consultas (P.grep, P.leer main.py). POST /api/app/shutdown (app.py:3121-3125)
  como único endpoint HTTP, lifespan (83-93) y main.py:171; cita bien test_shutdown_cleanup.py:115. «Todos los endpoints
  se ven afectados indirectamente» se refiere al apagado del servidor (lifespan) y lo explica. Sin rutas inventadas.
  → CORRECTA. La 1.ª muestra (PARCIAL: inventó /api/chat…) no se repite.
- 12bb·gf (general, hechos al final) · 19,9 s · 0 consultas. POST /api/app/shutdown como único endpoint directo; lifespan
  explicado como ciclo de vida, «no es un endpoint». Sin invenciones. → CORRECTA.
- 12bb·u2 (unidad, 2.ª muestra) · 19,7 s · 1 consulta (P.impacto). Lo mismo, conciso. → CORRECTA (con el eco del código
  «P.impacto(...)» pegado al principio del texto, como en E7).
- ind_27·g2 (general, 2.ª muestra) · 37,0 s · 0 consultas. Fórmula y constantes bien (370, 250, 68,65, 56; base_mb l.202,
  calientes_para 295-301). PERO «el mismo n con MTP desactivado» (falso: n se recalcula), un bloque de código presentado
  como «l. 915-923» que es una simplificación inventada (`intentos = [(n, con_mtp), (n-8, con_mtp), (0, False)]`), «reduce
  8 capas» (son 8 expertos por capa) y no menciona el modo manual. → PARCIAL alta (mismo criterio que ind_27 unidad de la
  1.ª corrida).
- ind_27·u2 (unidad, 2.ª muestra) · 124,7 s · 4 consultas. La secuencia EXACTA del código (n₁ con MTP, n₁-8 con MTP,
  n₂ sin MTP, n₂-8 sin MTP, 0 sin MTP) con el código literal, automático frente a manual, qué pasa con 0 calientes (no se
  ponen AIPC_MOE_HOT_* : verificado l.851), el plazo de 240 s (ESPERA_ARRANQUE_S, l.739) y el RuntimeError literal con
  {REGISTRO}. «MAX_CALIENTES no especificado en el código visto» (es 56: lo dice honestamente). → CORRECTA (la mejor de
  ind_27). Con dos muestras, ind_27 queda 1-1 en los dos modos: la «ventaja del general» de la 1.ª corrida también era ruido.
- a84a·gf (general, hechos al final) · 32,0 s · 0 consultas. Por primera vez las TRES lectoras (_ajustes l.92, la directa;
  embeber l.101 y estado l.265, que consumen lo que devuelve), pero lista también ConfigModelos._leer (l.290: define el
  valor por defecto) y ConfigModelos.fijar_embeddings (l.389: ESCRIBE; la misma respuesta dice «asigna… para guardar») y
  cierra «las 5 funciones que acceden directamente a la clave». → PARCIAL alta (recall completo, 2 que no leen). Es el
  problema ya visto: los hechos no distinguen leer, escribir y definir.
- 29b4·gf · 37,4 s · 2 consultas (P.llamadores, P.api). Las dos rutas exactas, los llamadores con su línea (2878, 2887),
  rebind_workspace l.281, los 6 servicios que reinstancia y los consumidores del frontend (verificados con grep). → CORRECTA.
- 02bd·gf · 18,6 s · 1 consulta. Hub._crear l.151 y Hub.editar_manifiesto l.222. → CORRECTA.
- Las 3 de control de «al final» (a84a, 29b4, 02bd) no empeoran: 29b4 y 02bd igual que antes, a84a mejora en recall.
- E8a_B3·g2 (general) · 46,5 s · 0 consultas. DETECTA: startswith, caso /home/user/mi_proyecto_externo/…, arreglo correcto;
  dice l.39 (es 40) y redacta al revés uno de los dos casos («el malicioso es prefijo del permitido»), con el ejemplo bien.
- E8a_B3·u2 (unidad, lectura guardada por T5) · 21,7 s · 0 consultas. DETECTA: caso /workspace_malicioso, arreglo
  correcto (y la excepción de la raíz «/»); dice l.37 (es 40).
- E8a_B3·g3 (general) · 28,2 s. DETECTA, l.39, caso y arreglo correctos.
- E8a_B3·u3 (unidad) · 18,4 s. DETECTA, l.39, cita la función literal, los tres casos (raíz, dentro, hermano) bien.
- B3 con tres muestras: general 3 de 3, unidad 2 de 3. El «está protegido» de la 1.ª corrida en unidad no es
  sistemático, pero es el riesgo real: a veces un «no hay error» falso y seguro. Las líneas, casi siempre corridas en 1.

## Comprobaciones sin modelo (sistema congelado, después de las corridas)
- P.camino (consola) encuentra los DOS recorridos que el modelo negó 4 de 4 veces:
  modelos_borrar_parciales (app.py:5876) → _carpeta_modelos_servidor (app.py:5863) → estado (servidor.py:123) →
  librerias_disponibles (servidor.py:72); recursos_ritmo (app.py:5420) → gobernador (termico.py:711) →
  Gobernador.__init__ (termico.py:341) → ControladorFrio (frio.py:257). Ponerlo en los hechos les da la respuesta exacta.
- Enrutador del control: la mejor unidad 5,36 puntos, la segunda 4,0 (< 1,5×) → general. MESETA_S no es símbolo del
  banco; identificadores_nombrados devuelve {recursos, termico, backend, MESETA_S}: las palabras de la ruta suman.
  Los recorridos y f46b: la mejor 24-29 %, repartidos de verdad (dos puntas en unidades distintas).
- B6 en el banco de la copia E8: `JobExporter.preparar lee_config max_chunks_tokens (job_exporter.py:93)` y, aparte,
  `SondeoLibro.recomendar lee_config max_chunk_tokens (sondeo_libro.py:550)`. El banco solo registra lecturas (no hay
  «escribe_config»). Regla barata: una clave leída en un solo lugar que difiere en una letra de otra más usada → hecho
  «¿clave mal escrita?».
- Registro del motor (~/.prig_moe.log), E8a_B2 en unidad: lectura al vuelo de la unidad (ba4333c5, 17.125 tokens, 28,4 s,
  guardada) y 7 restauraciones (una por ronda de consultas); a las 23:06:45 la conversación pasó el contexto de 32K y el
  motor se reinició en 64K (24 → 16 calientes por capa); en la ronda final, otra LECTURA DESDE CERO de un prefijo de
  16.484 tokens (26,3 s) guardada como estado nuevo (d466f7dc, 246 MB): 641 tokens menos = las definiciones de las
  herramientas. La «última ronda sin herramientas» (chat_eventos, Implementación de lo medido) cambia el prefijo guardado de
  la unidad: relee la unidad y guarda un estado que casi nunca se reaprovecha. Pasa solo cuando se agotan las 8 consultas
  (en T7: 1 vez de 19 respuestas en modo unidad). Arreglo: en la última ronda mantener las definiciones y forzar la respuesta de
  otro modo (tool_choice "none" si el servidor lo respeta, o ignorar una llamada que llegue igual).
- Estados nuevos que dejó T7: 5 (1,30 GB), todos de la copia E8 (4 lecturas al vuelo + el de la ronda final de B2): son
  del estudio, para la limpieza de T8.

## Re-medición tras implementar las 5 propuestas (10/10/2026, sistema 68a29512…)
- ind_15 g1 (60 s, 3 consultas): delete_book (en el código citado) app.py:450 y descarta file_mgr.delete_item; dice
  «DELETE /api/books/delete» con el código `@app.post` delante → C (detalle mal: el método). u1 (15 s, P.llamadores):
  delete_book l.450, los demás son tests → C. g2 (48 s): delete_book, POST /api/books/delete, descarta file_mgr → C.
  u2 (15 s): delete_book l.450 → C. ind_15: 4 de 4.
- ind_16 g1 (29 s, 0 consultas): maquina, estado_vivo, recursos_servidor_aplicar; OMITE _num_gpus (estaba en los hechos)
  y dice «la única llamada externa» → P (3 de 4). u1 (40 s, P.llamadores): los 4, SIN el falso positivo calibrar → C.
  g2 (47 s, 2 consultas): los 4 y descarta detector.radiografia → C. u2 (24 s): los 4, sin falso positivo → C.
  ind_16: general 1 de 2, unidad 2 de 2 (y el falso positivo sistemático de unidad desapareció).
- 12bb g1 (77 s, 5 consultas), u1 (23 s, P.impacto), g2 (49 s), u2 (82 s, 5 consultas): las 4 dan POST /api/app/shutdown
  como único endpoint HTTP, lifespan y shutdown_prig como no-endpoints, sin rutas inventadas («ningún frontend lo invoca»:
  verificado con grep) → 4 C.
- a84a g1 (26 s), g2 (25 s), u2 (18 s, P.hechos): embeber y estado como lectoras, y _ajustes como la que la lee de
  ConfigModelos.embeddings() (l.371, verificado) para ellas → la cadena completa y bien, sin falsos positivos → C (la
  directa, nombrada como intermediaria). u1 (13 s): las tres como lectoras, explicadas → C. Ya no aparecen _leer (define)
  ni fijar_embeddings (escribe). a84a: 4 de 4 (antes: P en todas las muestras de los dos modos).
- 0b5f g1 (29 s): el camino de los hechos, con cada salto explicado → C. u1 (fue a general, 27 %), g2, u2 (general): NIEGAN
  el camino aunque está en los hechos; u1 llega a decir que el camino del banco «es imposible y contradice el código
  literal». Ninguna consulta. El camino es real pero sutil: `borrar_parciales(_carpeta_modelos_servidor())` (la llamada va
  en un argumento), `recursos_srv.estado().get(...)` en medio de una expresión y `librerias_disponibles()` dentro de un
  diccionario literal: el modelo lee el código, no ve esas llamadas y le cree a su lectura antes que al hecho. 1 de 4.
- d408 g1, u1, g2, u2 (todas en general; 17-20 s, 0 consultas): el camino exacto de los hechos; g1 agrega el matiz de que
  ControladorFrio se crea una sola vez (composición) → 4 C (antes 0 de 4).
- Por qué 0b5f sí y d408 no: en d408 cada salto es una llamada visible (gobernador(), Gobernador(...), ControladorFrio(...));
  en 0b5f dos llamadas están escondidas (en un argumento, en un diccionario literal) y el modelo «verifica» leyendo y no
  las ve. Arreglo: cada salto del camino con la línea de la llamada.
- control g1 (14 s), u1 (fue a general, 12 s): 20.0 bien; la línea mal (35 y 20; es 60) → C (como siempre).
- E8 B6 g1 (46 s), u1 (86 s, 4 consultas: P.lineas 90-100 y P.grep de las dos claves), g2 (26 s), u2 (76 s): las 4 lo
  DETECTAN: l.93, `max_chunks_tokens` por `max_chunk_tokens`, el ajuste por libro se ignora siempre, caso concreto
  ({"ajustes": {"max_chunk_tokens": 300}} → se usa 500) y el arreglo; u2 cita el aviso de los hechos. (Antes: 0 de 2.)
  El segundo ver_simbolo idéntico de u1/u2 recibió el aviso de consulta repetida (143 car.): funciona.
- Tanda corta de recorridos con el camino CON LA LÍNEA de cada llamada (sistema ceaa9911…): 0b5f l1, l2, l3 NIEGAN (l3:
  «una relación falsa en el banco»; l2 atribuye app.py:5865, que está dentro de _carpeta_modelos_servidor, a otro
  endpoint); l4 se contradice: «no pasa» y después da los intermedios correctos → P. d408 l1, l2 → C (con el código).
  0b5f queda en 1 de 8 + 1 parcial con los hechos, con o sin líneas: el modelo considera «borrar parciales» y «librerías
  disponibles» flujos sin relación y confunde «llama directamente» con «la ejecución pasa por». No es falta de
  información: el sesgo semántico gana a la evidencia (con think=False). d408: 6 de 6.

## Modo auto (el que queda por defecto), con los hechos de constantes y el camino redactado sin ambigüedad (10/10, 2f2520f6…)
- ind_15·a (unidad, 29 s): delete_book l.450, los demás son tests → C. ind_16·a (unidad, 42 s): los 4 → C.
  f46b·a (general, 29 %; 64 s): /api/inicio, /api/progreso/historial, /api/progreso/analisis; otra vez sin
  /api/progreso/resumen (dos saltos) → C (3 de 4, criterio de E7). a84a·a (unidad, 13 s): las tres lectoras → C.
- 29b4·a (unidad, 21 s): las dos rutas → C. 12bb·a (unidad, 103 s): solo POST /api/app/shutdown; lifespan y
  shutdown_prig como no-endpoints → C. 0b5f·a (general, 36 s): NIEGA otra vez, con la redacción nueva → I.
  d408·a (general, 20 s): el camino con el código → C.
- ind_27·a (unidad, 23 s): fórmula, automático/manual y la secuencia simplificada (n, n-8, 0) sin nada falso → C (como el
  general de la 1.ª corrida de T7). 1f14·a (unidad, 13 s): credenciales l.89 → C, pero EN INGLÉS (también en T7, unidad:
  2 de 2; la guía pide el idioma de la pregunta). 02bd·a (unidad, 15 s) → C.
- Constantes (las tres fueron a general por el enrutador): control MESETA_S → 20.0 en termico.py:60; MARGEN_MB → 250 en
  la línea 53; MAX_CALIENTES → 56 en motor_moe.py:42. 3 de 3 con la LÍNEA EXACTA (antes: la línea mal en todas).
- 0b5f con la redacción nueva («when the first one runs, execution reaches the last one…; to deny it, quote the line»):
  a (auto→general) I; r1 I; r2 C (verificó con la consola: «llamada en la línea 5878… 5865… 141»); r3 I → 1 de 4. Sin
  cambio: 0b5f queda en 2 de 13 desde que los hechos traen el camino. Límite del modelo con think=False.
- E8 en auto (las cuatro a unidad, lecturas guardadas): B2 «no hay errores» → no detecta (sin falso positivo); B3 l.40,
  caso y arreglo → detecta; B6 l.93 → detecta; B7 «nunca la cierra… fuga de conexiones… try/finally» → DETECTA (primera
  vez en todo el estudio; una muestra). 3 de 4 sin falsos positivos (T7: general 1, unidad 0).
- Idioma (recordatorio «(Responde en castellano.)» pegado a la pregunta en modo unidad; sistema 895e3ecc…): 1f14 i1, i2,
  i3 en castellano y correctas (antes 2 de 2 en inglés); ind_15 y 02bd, correctas.

## «Corrige los fallos» (10/10, sistema 9da66efa…): código del medio en el camino, endpoints a 3 llamadas por texto,
## fábricas con tipo de retorno, enrutador (constantes y palabras de la ruta)
- 0b5f m1 (general, 47 s): el camino completo y explicado («la función se ejecuta porque estado la invoca en su línea
  141») → C, sin consultar. m2 (30 s): «no hay llamadas directas ni transitivas» y a continuación el camino correcto con
  sus tres llamadas → P (se contradice).
- f46b a1 (AHORA va a unidad, 99 s): los 4 endpoints reales (analisis POST, inicio, resumen por dos saltos, historial)
  + «GET /api/progreso/analisis» (existe, l.6396, pero llama a analisis_guardado, no a historial) → C* (4 de 4 y 1 falso).
- control a1 (AHORA va a unidad «motor_suave, ritmo, termico», 10 s): 20.0, línea 60 → C.
- d408 m1 (general, 30 s) → C. f46b a2 (unidad, 115 s): los 4 exactos, sin falsos → C. 0b5f m3 (30 s): el camino con
  las tres líneas → C. cte_margen a1 (AHORA a unidad, 8 s): 250, línea 53 → C. 0b5f t1 (think=True, 80 s, 1.988 tokens con
  el razonamiento): las dos intermedias con una tabla de llamadas y líneas → C.
- 0b5f con el código del medio: 2 C + 1 P de 3 sin razonar (antes, 2 de 13); con razonamiento, 1 de 1.
- E8 B2 a1 (auto → unidad, sin razonar, 166 s): simula un tramo de 10 líneas con tope 3 en la consola, ve los huecos y lo
  DETECTA: l.96-97, «se pierde la línea n que causó el desborde», el tramo final (fin+1, fin) inválido y el arreglo
  (a = n). Primera detección de B2 en el estudio.
- E8 B2 t1, t2 (think=True; con razonamiento el modo unidad no se usa: «modo unidad no disponible: con razonamiento»):
  VACÍAS, 4.096 tokens cada una: el razonamiento se comió el tope de la respuesta. Falla de la app con «Pensar» y banco
  → TOPE_RESPUESTA_BANCO_PENSANDO = 16.384 (app.py; el motor reserva ese espacio al elegir el contexto).
- E8 B2 sin razonar, en unidad: a2 (78 s, 3 consultas) DETECTA (tokens [2, 2, 2] con tope 3: «la línea 1 se pierde»);
  a3 (134 s) cae en el bucle «Espera, creo que el error está en la línea 96…» hasta el tope (14.805 car.) → no. Con a1:
  2 de 3. (T7: 0 en los dos modos.)
- B2 t3, t4 con razonamiento: VACÍAS otra vez con 4.096 tokens: el tope del chat no llegaba al motor, porque la
  configuración del usuario fija num_predict = 4096 y chat_eventos solo usaba el suyo si la configuración no fijaba
  ninguno → con think, el tope del chat manda si es mayor (ai_engine_class.chat_eventos).
- B2 con razonamiento y el tope arreglado: t5 (135 s, 3.545 tokens) INVENTA un error («línea 104: actual = []»; es None,
  l.103) → falso positivo; t6 razona 16.384 tokens (485 s) y sale VACÍA. El razonamiento no sirve para revisar con este
  modelo: no se activa solo. (Para el recorrido sí ayudó: 0b5f t1, C.)

## Regresión final del modo por defecto (auto, sistema 0d8e6643…, con todos los arreglos)
- Prig, las 11 de falla: ind_15 C (unidad), ind_16 C (los 4), f46b C (unidad; los 4 endpoints exactos, 8 consultas,
  176 s), a84a P (unidad; embeber y estado, sin _ajustes: en unidad, 3 de 4 hoy), 29b4 C, 12bb C, 0b5f C (general),
  d408 C, ind_27 C (secuencia simplificada sin nada falso), 1f14 C (en castellano), 02bd C → 10 de 11. Control C (unidad,
  línea 60). 0b5f z2 (general): «no pasa por ninguna intermedia de forma directa» y luego el camino completo → P.
- 0b5f con el código del medio: m1 C, m2 P, m3 C, z C, z2 P → 3 C y 2 P de 5, ninguna lo niega (antes 2 C de 13).
  Lo que queda es la primera frase («no pasa… de forma directa») antes del camino correcto.
- E8 en auto (todas a unidad): B3 C (13 s), B6 C (60 s), B7 C (121 s; ahora con el caso de la excepción y rollback +
  close en finally), B2 z1/z2/z3 NO (falsos positivos: solapamiento de símbolos l.121, código suelto etiquetado con el
  primer hijo, líneas finales sin el nombre del padre). B2 hoy, en unidad: 2 de 6 (lo encuentra cuando simula el corte
  por líneas en la consola). El corte de bucles no se disparó (ningún bucle).
- 0b5f con «indirectly, through the functions in the middle, which is what such a question asks for» (sistema
  ab44233c…): w1 (verifica con 7 consultas), w2, w3 → 3 de 3 C.

## «Sigue corrigiendo»: P.cargar (ejecutar la función real en la consola) y E8a completo (12 + 2), sistema 09435f01…
Verdad (diff contra la copia limpia): B1 progreso.py:165 `else 0` (debía ser 1: la racha arranca en 0 tras un corte);
B4 termico.py:327 `return max(picos)` sin `if picos else None` (ValueError sin lecturas); B5 ritmo.py:82
`.get("activa")` por "activo" (siempre False); B8 runner.py: falta `process.kill()` al vencer el tiempo (communicate
espera para siempre). C1-C4 sin cambios (C2 depende de is_path_allowed, que en esta copia tiene B3).
- E8a completo (auto, con P.cargar disponible pero sin pista; 09435f01): B1 C (la racha de un día da 0: «seguidos = 1»;
  un «error 2» que es la misma idea reformulada), B2 1 de 3 (k2 sí, simulando; k y k3: falso positivo del código entre
  símbolos; NINGUNA usó P.cargar), B3 C, B4 C (max de vacío → ValueError, arreglo correcto), B5 C, B6 C, B7 C (cierra
  después del yield: sin finally, incompleto, pero lo detecta), B8 NO («se llama a communicate() para vaciar los
  buffers»: lo da por correcto). Controles: C1, C2, C3 limpios; C4 (Ritmo.marcar) señala el error real de Ritmo.activo
  del mismo archivo (B5): no es un falso positivo. 6 de 8 + B2 a veces (T7: 1 de 4 en los cuatro difíciles).
- Arreglos: pista «RUN it with a case» con P.cargar y lo que hay que sustituir (solo funciones de primer nivel que
  pasan la revisión de la consola y cuyos ayudantes se sustituyen fácil: en E8a, B1 y B2); trampa conocida de
  TimeoutExpired sin kill (0 avisos en la copia limpia, solo B8 en la E8); clave mal escrita contando cadenas del mismo
  lenguaje (0 en la limpia; B5 y B6 en la E8); llamadores sin el texto de las cadenas (los reales, idénticos).
- Validación final (f005dd92…), Prig en auto: ind_15 C, ind_16 C (los 4), f46b C (4 endpoints; nombra /api/flujos para
  descartarlo como homónimo de FlowStore), 02bd C, 12bb C, a84a P (unidad: P.hechos(r="lee_config", o="truncar") →
  embeber y estado, y responde con eso; 2 de las últimas 2 en unidad). Causa: el grafo no ve `e.get("truncar")` con
  `e = config().embeddings()`. Arreglo sin tocar el banco (cambiar el extractor obligaría a reindexar): P.hechos de
  lee_config/lee_entorno suma las lecturas literales de la clave, marcadas «texto».
- E8 (validación): B8 C — con la trampa en los hechos («communicate() sin kill() en el except TimeoutExpired»), por
  primera vez; C1 limpio; B5 C; B2 C — USÓ P.cargar (2 veces) y lo vio ejecutando: «tope=30 → (1, 30) y (32, 60),
  saltándose la línea 31»; C2 señala B3 (real, en is_path_allowed, que resolve usa); B1 C (P.cargar 7 veces, tabla de
  casos; el arreglo que propone deja el 0 tras un corte: incompleto); C3 señala un caso borde real (un JSON válido que no
  es un objeto rompe perfil: datos.items()), en inglés al principio.
- Validación E8, las últimas 8 (PROVISIONAL, auditar al retomar): C4 se contradice (abre «tiene un error en la l.89» y
  cierra «no hay error en marcar»); B3 NO (unidad: «startswith es seguro», la respuesta peligrosa de T7 otra vez); B7
  dudosa (habla del commit sin try/except, no del close que falta); B6 C; B4 NO (afirma «devuelve None si no hay datos»:
  esa guarda no existe en esta copia); B2 v2 C (sin P.cargar: a = n, acumulado = t); B8 v2 C (l.270, kill antes de
  communicate); B2 v3 dudosa (describe piezas 1-1 y 3-3 pero dice que el error son los nombres). Las fallas de B3 y B4
  esta vez, y la detección de B4 la anterior: ruido entre corridas; falta medirlo con más de una muestra.

## Retomado (10/10, 17:15): auditoría a mano de las 8 últimas de la validación
- C4 (control): arranca afirmando un error inexistente en marcar, relee y concluye «no hay error» → control limpio en la
  conclusión, con un arranque falso. B7: ve que con una excepción no hay rollback (parte de B7), no que la conexión nunca
  se cierra; afirmaciones confusas («Cannot commit…») → P. B6 C. B2 v2 C. B8 v2 C.
- B3 (unidad, 0 consultas): «startswith es seguro» → NO. B3 en unidad, todas las muestras: 5 de 7.
- B4 (general): cita textualmente `return max(picos) if picos else None`, que es la versión LIMPIA: el banco de la copia
  E8 tiene `return max(picos)` (l.327) y ningún fragmento contiene la limpia → el modelo citó de memoria el código
  idiomático y razonó sobre su cita → NO.
- B2 v3: falso positivo (los nombres de las piezas); su propio ejemplo muestra (1-1) y (3-3), el hueco, y no lo ve → NO.
  B2 en la validación: 2 de 3.
- Arreglo: en una pregunta de revisión, el código literal de la función (≤ 60 líneas, con números) va en los hechos,
  pegado a la pregunta, con la indicación de citar eso y no de memoria.
- a84a en unidad con P.hechos + lecturas literales (sistema 6909b7d4): r1, r2, r3 → las tres lectoras (_ajustes l.92,
  embeber l.101, estado l.265), sin _leer ni fijar_embeddings → 3 de 3 C (antes 3 de 5, con las 2 últimas P). Las tres
  consultaron P.hechos(r="lee_config", o="truncar").
- Línea base de B3/B4 (sin el código literal; 6909b7d4): B3 unidad 3 de 3; B4 general 0 de 3 (una cita la versión limpia
  inventada; dos citan bien `return max(picos)` y no ven que los dos picos pueden ser None).
- Con el código literal + la trampa «max() de una lista filtrada» (2ffa6dcf; 0 avisos en las 2147 funciones de la copia
  limpia y en las 71 del repositorio externo; en la E8, solo B4 y B8): B4 3 de 3 (default=None); B3 unidad 2 de 3 (c3:
  «sólido»); C1 y C4 limpios; B7 unidad NO («no tiene ningún error»); B1 C (else 1, el arreglo correcto).
- Trampas nuevas: @contextmanager con el yield fuera de try/finally (y sin close) y `ruta.startswith(raiz)` como prueba
  de pertenencia (por partes del nombre: «database_url» no cuenta). En las 2147 funciones de la copia limpia: 1 aviso,
  catalogo_github.py:1159 `path.startswith(ruta_sub)` — un error latente REAL del proyecto («ejercicios» también deja
  pasar «ejercicios_avanzados/…»), no inyectado; en el repositorio externo: 0; en la E8: B3, B4, B7, B8 (y el mismo real).
- Con las trampas de contextmanager y rutas (f58e0c3d): B3 unidad 3 de 3; B7 unidad 3 de 3 (arreglo try/finally/close);
  C2 señala B3 (real, en la función que resolve usa); C3 limpio.

## «Corrige todo» (10/10, 17:45–): empujón a ejecutar, respaldo sin razonar, idioma, catalogo_github, limpieza
- catalogo_github.py: `_dentro_de(ruta, carpeta)` en las dos líneas con `path.startswith(ruta_sub)` (1159 y 1207).
- Empujón: si la pregunta es de revisión sobre una función ejecutable (sugiere_ejecutar) y respondió sin P.cargar, se le
  pide una vez EJECUTALA. Respaldo: con «Pensar», si el razonamiento termina sin texto, se responde sin razonar.
- Medición (454a7999): B2 e1 C (P.cargar; a = n, acumulado = t), C3 unidad limpio Y EN CASTELLANO desde la primera
  línea, B2 e2 C (P.cargar: «11 líneas, tope 10 → 1-10 y 12-11: la línea 11 se pierde»).
- Limpieza (confirmada: «la limpieza de T8: borrar los estados que solo usa el estudio»): de 109 estados (29,5 GB),
  20 solo de bancos del estudio (4,99 GB) y 1 sin ningún banco (d466f7dc, 0,25 GB, el de la ronda final de B2 en T7);
  88 compartidos con el banco real de Prig (24,27 GB) quedan. ~/.cache/prig-estudio (377 MB) no se toca.
- Resto de la medición: B1 C (P.cargar 5 veces, seguidos = 1); B2 e3 NO (P.cargar 3, falso positivo de los nombres),
  C1 limpio (una cuenta mal en el ejemplo), B2 e4 NO (P.cargar 1, casos que no pasan por el corte; abrió en inglés);
  B2 con «Pensar» (606 s, 14.243 tokens) C. B2 con el empujón: 2 de 4, las 4 ejecutaron.
- Limpieza hecha: 42 archivos (21 .bin + sus .calientes.json), 5,24 GB; 88 estados quedan; 9 lecturas del banco real ya
  no tenían archivo antes (ninguna borrada hoy).
