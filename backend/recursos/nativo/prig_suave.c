/*
 * prig_suave.so — modo suave DENTRO del motor de los modelos (llama-server de Ollama).
 *
 * Se precarga (LD_PRELOAD) en el proceso del modelo mediante el envoltorio que Prig pone
 * en su propio Ollama (recursos/motor_suave.py). Hace dos cosas, medidas en el portátil
 * del usuario (i5-13420H + RTX 4050, qwen2.5-coder:7b):
 *
 *  1. ESPERA BLOQUEANTE. El hilo principal del motor pasaba ~90 % del tiempo dentro de
 *     cudaStreamSynchronize girando en el controlador (unas 800 llamadas por segundo).
 *     Esa «carga» hacía que auto-cpufreq encendiera el turbo: la CPU saltaba de 48 a 97 °C
 *     en segundos. Aquí cada espera se hace con un evento cudaEventBlockingSync: el hilo
 *     duerme hasta que la GPU termina. Con --poll 0 el motor pasa de 250 % a 5 % de CPU,
 *     la CPU media de 85,6 a 55 °C, y la velocidad no cambia (36,8 → 35,8 tok/s).
 *     cudaSetDeviceFlags no sirve: el motor nunca llama a cudaSetDevice (usa el 0).
 *
 *  2. DOSIFICACIÓN POR MILISEGUNDOS. Tras cada espera, si Prig lo pide, una pausa
 *     proporcional al trabajo hecho: con tramos de ~20 ms la GPU nunca arranca en frío,
 *     así que no hay golpes de potencia. Al 35 % consume 21 W muy estables (desviación
 *     1,4 W) en vez de 40 W, y sube +4 °C en 5 s en vez de +8. Tramos largos (400-800 ms)
 *     bajan un poco más la media pero cada arranque da picos de 50-60 W instantáneos.
 *     Pausar aquí dentro también frena la lectura del prompt y el razonamiento, cosa que
 *     cortando peticiones HTTP no se podía hacer.
 *
 * Archivo de control (lo escribe Prig): «fraccion tramo_s marca_de_tiempo». Si la marca
 * tiene más de 5 s (Prig cerrado o colgado), se trabaja a pleno: el motor nunca queda
 * frenado por un archivo viejo. Archivo de estado (lo escribe esto, cada segundo):
 * «pid ultima_actividad fraccion tramo esperas_por_segundo».
 *
 * libcudart la carga el motor en un ámbito local (dlopen), así que RTLD_NEXT no la ve:
 * las funciones reales se buscan pidiendo la biblioteca ya cargada por su nombre.
 */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

typedef int cudaError_t;
typedef void *cudaStream_t;
typedef void *cudaEvent_t;

#define EVENTO_BLOQUEANTE 0x01
#define EVENTO_SIN_TIEMPOS 0x02
#define CONTROL_CADUCA_S 5.0
#define PAUSA_MAXIMA_S 0.5

static void *real(const char *nombre) {
    static void *cudart = NULL;
    void *f = dlsym(RTLD_NEXT, nombre);
    if (f) return f;
    if (!cudart) {
        const char *libs[] = {"libcudart.so.13", "libcudart.so.12", "libcudart.so.11.0", "libcudart.so", NULL};
        for (int i = 0; libs[i] && !cudart; i++) cudart = dlopen(libs[i], RTLD_NOW | RTLD_NOLOAD);
    }
    return cudart ? dlsym(cudart, nombre) : NULL;
}

static double monotono(void) { struct timespec t; clock_gettime(CLOCK_MONOTONIC, &t); return t.tv_sec + t.tv_nsec * 1e-9; }
static double reloj(void) { struct timespec t; clock_gettime(CLOCK_REALTIME, &t); return t.tv_sec + t.tv_nsec * 1e-9; }

static double fraccion = 1.0, tramo = 0.02;
static double ultima_lectura = 0, ultimo_estado = 0, inicio_trabajo = 0, ultima_salida = 0;
static long esperas = 0;
static char ruta_control[512], ruta_estado[520];

static void rutas(void) {
    if (ruta_control[0]) return;
    const char *r = getenv("PRIG_SUAVE_CONTROL");
    if (!r || !*r) {
        const char *base = getenv("XDG_RUNTIME_DIR");
        snprintf(ruta_control, sizeof ruta_control, "%s/prig_suave", base && *base ? base : "/tmp");
    } else {
        snprintf(ruta_control, sizeof ruta_control, "%s", r);
    }
    snprintf(ruta_estado, sizeof ruta_estado, "%s.estado", ruta_control);
}

static void leer_control(double t) {
    if (t - ultima_lectura < 0.1) return;
    ultima_lectura = t;
    rutas();
    fraccion = 1.0;
    FILE *f = fopen(ruta_control, "r");
    if (!f) return;
    double d = 1.0, q = tramo, marca = 0;
    int n = fscanf(f, "%lf %lf %lf", &d, &q, &marca);
    fclose(f);
    if (n < 3 || reloj() - marca > CONTROL_CADUCA_S) return;       /* Prig no está al mando */
    if (d >= 0.05 && d <= 1.0) fraccion = d;
    if (q >= 0.002 && q <= 2.0) tramo = q;
}

static void escribir_estado(double t) {
    if (t - ultimo_estado < 1.0) return;
    double transcurrido = ultimo_estado > 0 ? t - ultimo_estado : 1.0;
    ultimo_estado = t;
    rutas();
    char tmp[540];
    snprintf(tmp, sizeof tmp, "%s.%d", ruta_estado, (int)getpid());
    FILE *f = fopen(tmp, "w");
    if (!f) return;
    fprintf(f, "%d %.3f %.3f %.4f %.0f\n", (int)getpid(), reloj(), fraccion, tramo, esperas / transcurrido);
    fclose(f);
    rename(tmp, ruta_estado);
    esperas = 0;
}

static __thread cudaEvent_t evento = NULL;

cudaError_t cudaStreamSynchronize(cudaStream_t s) {
    static cudaError_t (*sync)(cudaStream_t), (*crear)(cudaEvent_t *, unsigned), (*grabar)(cudaEvent_t, cudaStream_t), (*esperar)(cudaEvent_t);
    static int bloqueante = -1;
    if (!sync) {
        sync = real("cudaStreamSynchronize");
        crear = real("cudaEventCreateWithFlags");
        grabar = real("cudaEventRecord");
        esperar = real("cudaEventSynchronize");
        bloqueante = getenv("PRIG_SUAVE_GIRO") ? 0 : 1;
    }
    if (!sync) return 1;                                             /* cudaErrorInvalidValue */
    double entrada = monotono();
    if (entrada - ultima_salida > 0.25) inicio_trabajo = entrada;   /* venía de estar parado */
    cudaError_t r;
    if (bloqueante && crear && grabar && esperar) {
        if (!evento && crear(&evento, EVENTO_BLOQUEANTE | EVENTO_SIN_TIEMPOS) != 0) evento = NULL;
        r = (evento && grabar(evento, s) == 0) ? esperar(evento) : sync(s);
    } else {
        r = sync(s);
    }
    esperas++;
    double t = monotono();
    leer_control(t);
    if (fraccion < 0.999) {
        double trabajo = t - inicio_trabajo;
        if (trabajo >= tramo) {
            double pausa = trabajo * (1.0 - fraccion) / fraccion;
            if (pausa > PAUSA_MAXIMA_S) pausa = PAUSA_MAXIMA_S;
            struct timespec ts = { (time_t)pausa, (long)((pausa - (time_t)pausa) * 1e9) };
            nanosleep(&ts, NULL);
            inicio_trabajo = monotono();
        }
    } else {
        inicio_trabajo = t;
    }
    ultima_salida = monotono();
    escribir_estado(ultima_salida);
    return r;
}
