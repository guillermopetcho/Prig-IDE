/**
 * ============================================================================
 * WEB WORKER: SIMULADOR DE FÍSICA DE RESORTES Y PARTÍCULAS OFFLOAD (PRIG IDE)
 * ============================================================================
 * Ejecuta cálculos de física de resortes (Hooke / Verlet / Spring-Damper),
 * trayectorias spline Bézier de flujo y cinemática orbital de drones fuera
 * del hilo principal (Main Thread), garantizando 60 FPS estables sin jank en Monaco.
 */

self.onmessage = function(e) {
    const data = e.data;
    if (!data || !data.tipo) return;

    switch (data.tipo) {
        case 'INIT':
            self.iniciarSimulador(data.payload || {});
            break;
        case 'STEP_PHYSICS':
            self.computarPasoFisica(data.payload || {});
            break;
        case 'RESET_IMPULSO':
            self.aplicarImpulso(data.payload || {});
            break;
    }
};

self.estado = {
    w: 1280,
    h: 720,
    springK: 0.055,
    springDamping: 0.80,
    currentX: 0,
    currentY: 0,
    vx: 0,
    vy: 0,
    targetX: 0,
    targetY: 0,
    impulsoX: 0,
    impulsoY: 0,
    anguloFlotacion: 0,
    drones: [],
    particulasRuta: []
};

self.iniciarSimulador = function(cfg) {
    self.estado.w = cfg.w || 1280;
    self.estado.h = cfg.h || 720;
    self.estado.springK = cfg.springK || 0.055;
    self.estado.springDamping = cfg.springDamping || 0.80;
    self.postMessage({ tipo: 'READY', ok: true });
};

self.aplicarImpulso = function(payload) {
    self.estado.impulsoX += (payload.ix || 0);
    self.estado.impulsoY += (payload.iy || 0);
};

self.computarPasoFisica = function(params) {
    const w = params.w || self.estado.w;
    const h = params.h || self.estado.h;
    const targetRealX = w * (params.xRatio || 0.88);
    const targetRealY = h * (params.yRatio || 0.88) + Math.sin(params.anguloFlotacion || 0) * 2.0;

    // 1. Integración de segundo orden Spring-Damper (Hooke + Fricción Viscosa)
    const fx = (targetRealX - self.estado.currentX) * self.estado.springK + self.estado.impulsoX;
    const fy = (targetRealY - self.estado.currentY) * self.estado.springK + self.estado.impulsoY;

    self.estado.vx = (self.estado.vx + fx) * self.estado.springDamping;
    self.estado.vy = (self.estado.vy + fy) * self.estado.springDamping;

    self.estado.currentX += self.estado.vx;
    self.estado.currentY += self.estado.vy;

    self.estado.impulsoX *= 0.70;
    self.estado.impulsoY *= 0.70;

    // 2. Cálculo orbital elástico de drones satélite
    const dronesCalculados = [];
    if (Array.isArray(params.drones)) {
        params.drones.forEach((drone, idx) => {
            const radObjetivo = drone.radio || 38;
            let radActual = drone.radioActual || radObjetivo;
            let vRad = drone.vRadio || 0;

            const fRad = (radObjetivo - radActual) * 0.08;
            vRad = (vRad + fRad) * 0.82;
            radActual += vRad;

            const angulo = (drone.angulo || 0) + (drone.velocidad || 0.02);
            const dx = self.estado.currentX + Math.cos(angulo + idx) * radActual;
            const dy = (self.estado.currentY - 30) + Math.sin(angulo * 1.5 + idx) * (radActual * 0.45);

            dronesCalculados.push({
                id: drone.id,
                angulo: angulo,
                radioActual: radActual,
                vRadio: vRad,
                x: dx,
                y: dy
            });
        });
    }

    // 3. Cálculo de partículas en splines Bézier de flujo de código
    const particulasCalculadas = [];
    if (Array.isArray(params.pasos) && params.pasos.length > 1 && Array.isArray(params.particulasRuta)) {
        const pasos = params.pasos;
        const numSegs = pasos.length - 1;

        params.particulasRuta.forEach(part => {
            let prog = part.progreso + (part.velocidad || 0.007);
            let seg = part.segmento || 0;
            if (prog > 1.0) {
                prog -= 1.0;
                seg = (seg + 1) % numSegs;
            }

            const p1 = pasos[seg];
            const p2 = pasos[seg + 1];
            if (p1 && p2) {
                const x1 = w * (p1.x_foco || 0.35);
                const y1 = h * (p1.y_foco || 0.35);
                const x2 = w * (p2.x_foco || 0.35);
                const y2 = h * (p2.y_foco || 0.35);
                const cpx1 = x1 + (x2 - x1) * 0.5;
                const cpy1 = y1;
                const cpx2 = x1 + (x2 - x1) * 0.5;
                const cpy2 = y2;

                const t = prog;
                const px = Math.pow(1-t, 3)*x1 + 3*Math.pow(1-t, 2)*t*cpx1 + 3*(1-t)*Math.pow(t, 2)*cpx2 + Math.pow(t, 3)*x2;
                const py = Math.pow(1-t, 3)*y1 + 3*Math.pow(1-t, 2)*t*cpy1 + 3*(1-t)*Math.pow(t, 2)*cpy2 + Math.pow(t, 3)*y2;

                particulasCalculadas.push({
                    progreso: prog,
                    segmento: seg,
                    velocidad: part.velocidad,
                    glifo: part.glifo,
                    px: px,
                    py: py
                });
            }
        });
    }

    self.postMessage({
        tipo: 'PHYSICS_RESULT',
        payload: {
            currentX: self.estado.currentX,
            currentY: self.estado.currentY,
            vx: self.estado.vx,
            vy: self.estado.vy,
            drones: dronesCalculados,
            particulasRuta: particulasCalculadas
        }
    });
};

