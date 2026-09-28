# Modo frío: modelos en RAM sin calentar la computadora

Para modelos que **no caben en la GPU** (32–40B en una de 6 GB): viven en la RAM y la CPU hace
la mayor parte del cálculo. Sin control, la CPU de un portátil pasa de 50 a 90–97 °C en unos
20 segundos. El modo frío la mantiene cerca de la temperatura que elijas, a cambio de velocidad.

## Qué se midió

En un Intel Core i5-13420H (4 núcleos P, 4 núcleos E, turbo activo), con un modelo de
referencia solo en CPU (`qwen2.5-coder:7b`, 4,7 GB). Un 40B en 4 bits (~24 GB) mueve unas cinco
veces más datos por token: la velocidad se divide por cinco, pero **la temperatura es la misma**,
porque la CPU está igual de ocupada.

**1. Sobran núcleos.** Generar con un modelo en RAM está limitado por la velocidad de la
memoria, no por la CPU:

| Hilos | Velocidad |
|---|---|
| 8 (P+E) | 7,2 tok/s |
| 4 | 7,0 tok/s |
| 4 en núcleos E | 7,3 tok/s |
| 2 | 5,5 tok/s |

**2. El calor lo pone el turbo.** En todas esas configuraciones la CPU llegó a 90–97 °C, incluso
con 2 hilos: con pocos núcleos activos, el turbo los sube a su frecuencia máxima.

**3. La temperatura sigue a la potencia media.** Si el motor trabaja solo una parte de cada
ciclo de milisegundos, calienta como a esa fracción de potencia:

| 4 núcleos E | Velocidad | Pico | Temperatura estable |
|---|---|---|---|
| Sin control | 5,1 tok/s | 97 °C | 87 °C |
| Trabaja 50 % | 2,3 tok/s | 75 °C | 61 °C |
| Trabaja 33 % | 1,3 tok/s | 66 °C | 47 °C |

**4. Cómo repartir el trabajo.** A igual temperatura, congelar el motor entero rinde mucho más
que ponerle un tope de CPU por cgroup, y usar todos los núcleos con tope rinde menos todavía:

| Estrategia | Velocidad | Temperatura estable |
|---|---|---|
| **4 núcleos E, motor congelado 50 % de cada ciclo** | **2,3 tok/s** | **61 °C** |
| **4 núcleos E, motor congelado 67 % de cada ciclo** | **1,3 tok/s** | **47 °C** |
| 4 núcleos E, tope por cgroup al 50 % | 1,4 tok/s | 61 °C |
| 4 núcleos E, tope por cgroup al 33 % | 0,4 tok/s | 43 °C |
| 12 hilos (todos los núcleos), tope al 33 %, ciclo 100 ms | 1,1 tok/s | 58 °C |
| 12 hilos, tope al 33 %, ciclo 10 ms | 0,5 tok/s | 57 °C |
| 12 hilos, tope al 50 %, ciclo 10 ms | 0,5 tok/s | 64 °C |

El motor sincroniza sus hilos en cada capa. Con un tope por cgroup, el kernel frena a los hilos
por separado, y cuando frena a uno los demás se quedan girando mientras lo esperan: gastan el
tope sin avanzar. Cuantos más hilos, peor. Congelar el proceso entero detiene todos los hilos a
la vez y ese problema desaparece. Por eso se descartó «todos los núcleos a capacidad reducida».

**5. De extremo a extremo** (Prig real, controlador automático con objetivo 60 °C, 200 tokens):
1,66 tok/s; CPU con mediana de 53 °C y estable en 55 °C (frente a 87 °C sin control). Hubo picos
breves de hasta 75 °C: solo 6 de 131 segundos pasaron de 70 °C. Son las ráfagas de turbo en cada
fase de trabajo, y es lo que reduce la energía con permiso de administrador.

## Cómo funciona

- **Pausas por ciclos, sin root.** Prig congela (`SIGSTOP`) y reanuda (`SIGCONT`) el motor de los
  modelos que no caben enteros en la GPU, en ciclos de 50 ms. Las señales van por *pidfd*:
  apuntan a ese proceso exacto, así que si el motor termina y el sistema reutiliza su número para
  otro programa, a ese otro no le llega nada.
- **Núcleos de eficiencia.** Esos motores se fijan a los núcleos E y se piden 4 hilos (tantos
  como núcleos E), salvo que hayas fijado los hilos a mano en Configuración. La excepción es el
  [motor MoE](motor-moe.md): con Qwen3.6-35B-A3B y el turbo apagado, 4 hilos en los núcleos P
  rinden 24–30 tok/s y en los núcleos E, 14. Ese motor sigue en los núcleos P y el modo frío
  solo lo pausa por ciclos.
- **Controlador térmico.** Una vez por segundo, con el motor trabajando, lee la temperatura de
  la CPU y ajusta qué parte de cada ciclo trabaja: sin pausas lejos del objetivo, el mínimo (12 %)
  en el objetivo, con cambios en rampa (sube 3 % y baja 8 % por segundo como mucho). Tras un rato
  sin trabajar, la siguiente respuesta arranca al 30 % y sube poco a poco. En reposo no lee
  sensores.
- **Nunca queda congelado.** El motor se reanuda al quitarlo de la lista, al apagar el modo frío
  y al cerrar Prig. Si Prig se cae de golpe justo en una pausa, al volver a abrirlo reanuda
  cualquier motor suyo que haya quedado congelado.
- Solo toca el motor **de Prig**. Un Ollama del sistema o de otro programa no se toca. Los
  modelos que caben enteros en la GPU no pasan por aquí: los regula el modo suave.

## Energía con permiso de administrador (opcional)

Sin turbo, cada token cuesta menos calor, así que a la misma temperatura el modelo va más rápido.
Prig lo hace con un ayudante mínimo, `prig-energia`:

- se instala una vez en `/usr/local/libexec/` (propiedad de root) con su política de polkit;
- **cada uso pide la contraseña de administrador** (polkit la recuerda unos minutos);
- solo sabe tres cosas: apagar el turbo y pasar la CPU a ahorro con un tope de potencia (10–45 W),
  volver a como estaba, y mostrar el estado. Valida cada argumento;
- con `auto-cpufreq` se lo pide a él (`--turbo=never`, `--force=powersave`); si se escribiera
  el turbo por debajo, su demonio lo volvería a encender;
- guarda los valores originales para restaurarlos con «Volver a normal».

Se usa desde **Herramientas → Temperaturas → Modo frío**.
