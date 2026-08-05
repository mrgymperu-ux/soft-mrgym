/* Reconocimiento facial local para el panel de staff.
   Modo "webcam_1080p": la webcam del counter nunca se transmite, Human calcula
   el descriptor en este navegador. Modo "movil": el celular vinculado hace su
   propio reconocimiento (ver camara-remota.html); esta PC solo escucha los
   resultados por WebSocket para poder avisar al staff (p. ej. deuda vencida)
   y puede pedirle al celular que capture el rostro de un cliente puntual. */
(function () {
    "use strict";

    const MODELO_VERSION = "human-3.3.6-faceres";
    const UMBRAL_COINCIDENCIA = 0.55;
    const CAPTURAS_REGISTRO = 3;
    const CLAVE_ESTACION_ACTIVA = "mrgym_rf_estacion_activa";
    const CLAVE_EVENTO_RECONOCIDO = "mrgym_rf_evento";
    const MINUTOS_ESPERA_REGISTRO_MOVIL = 3;
    let modoDispositivo = "desactivado";
    let umbralRostro = 0.65;
    let anchoRostroMinimo = 120;
    let intervaloMs = 120;
    const CONFIG = {
        backend: "webgl",
        modelBasePath: "vendor/human/models/",
        cacheSensitivity: 0.01,
        filter: { enabled: false },
        face: {
            enabled: true,
            // La webcam del counter permanece vertical; evitar buscar rotaciones
            // reduce trabajo sin afectar el uso normal de frente.
            detector: { rotation: false, maxDetected: 1, minConfidence: 0.55 },
            mesh: { enabled: false },
            iris: { enabled: false },
            description: { enabled: true },
            antispoof: { enabled: false },
            liveness: { enabled: false },
            emotion: { enabled: false },
        },
        body: { enabled: false },
        hand: { enabled: false },
        object: { enabled: false },
        gesture: { enabled: false },
    };

    let human = null;
    let promesaMotor = null;
    let stream = null;
    let temporizador = null;
    let ejecutando = false;
    let modo = null;
    let objetivoClienteId = null;
    let descriptores = [];
    let capturas = [];
    let ultimaCaptura = 0;
    let ultimoCandidato = null;
    let repeticionesCandidato = 0;
    let intervaloActividadEstacion = null;
    let socketEscucha = null;
    let escuchandoMovil = false;
    let sondeoRegistroMovil = null;
    const ultimoIntentoPorCliente = new Map();

    const elemento = (id) => document.getElementById(id);
    const esEstacion = () => document.body?.dataset.rfEstacion === "true";

    function guardarActividadEstacion() {
        if (!esEstacion()) return;
        localStorage.setItem(CLAVE_ESTACION_ACTIVA, JSON.stringify({
            activa: true,
            actualizada_en: Date.now(),
        }));
    }

    function iniciarActividadEstacion() {
        if (!esEstacion()) return;
        guardarActividadEstacion();
        if (intervaloActividadEstacion) window.clearInterval(intervaloActividadEstacion);
        intervaloActividadEstacion = window.setInterval(guardarActividadEstacion, 2000);
    }

    function detenerActividadEstacion() {
        if (!esEstacion()) return;
        if (intervaloActividadEstacion) window.clearInterval(intervaloActividadEstacion);
        intervaloActividadEstacion = null;
        localStorage.removeItem(CLAVE_ESTACION_ACTIVA);
    }

    function publicarIngresoFacial(clienteId, nombre, mensaje) {
        localStorage.setItem(CLAVE_EVENTO_RECONOCIDO, JSON.stringify({
            id: `${Date.now()}-${clienteId}`,
            cliente_id: clienteId,
            nombre,
            mensaje,
            creado_en: Date.now(),
        }));
    }

    async function cargarModoDispositivo() {
        const config = await window.getConfiguracion();
        modoDispositivo = config.reconocimiento_facial_modo || "desactivado";
        umbralRostro = 0.65;
        anchoRostroMinimo = 120;
        intervaloMs = 120;
        CONFIG.face.detector.minConfidence = 0.55;
        return modoDispositivo;
    }

    function exigirModoActivo() {
        if (modoDispositivo === "desactivado") throw new Error("El reconocimiento facial está desactivado en Configuración");
    }

    function estado(mensaje, tipo = "") {
        const nodo = elemento("rf-status");
        if (!nodo) return;
        nodo.textContent = mensaje;
        nodo.className = `rf-status ${tipo}`.trim();
    }

    function marcarBoton(activo) {
        const boton = elemento("btn-reconocimiento-facial");
        if (!boton) return;
        boton.classList.toggle("activo", activo);
        boton.setAttribute("aria-pressed", String(activo));
        boton.setAttribute("aria-label", activo ? "Desactivar reconocimiento facial" : "Activar reconocimiento facial");
        boton.title = activo ? "Reconocimiento facial encendido" : "Reconocimiento facial apagado";
    }

    async function cargarMotor() {
        if (human) return human;
        if (promesaMotor) return promesaMotor;
        promesaMotor = (async () => {
            if (!window.Human || !window.Human.Human) throw new Error("No se pudo cargar el motor facial");
            estado("Preparando reconocimiento facial por primera vez...");
            const instancia = new window.Human.Human(CONFIG);
            await instancia.load();
            // Compila los modelos antes de abrir la webcam: la primera lectura
            // deja de pagar este costo y el reconocimiento se siente inmediato.
            await instancia.warmup({ warmup: "face" });
            human = instancia;
            return human;
        })().catch((error) => {
            human = null;
            promesaMotor = null;
            throw error;
        });
        return promesaMotor;
    }

    async function encenderCamara() {
        if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) throw new Error("Este navegador no permite usar la cámara");
        stream = await navigator.mediaDevices.getUserMedia({
            audio: false,
            video: { facingMode: "user", width: { ideal: 1280 }, height: { ideal: 720 } },
        });
        const video = elemento("rf-video");
        video.srcObject = stream;
        await video.play();
        elemento("rf-camera").style.display = "block";
        marcarBoton(true);
        iniciarActividadEstacion();
    }

    function apagarCamara() {
        if (temporizador) window.clearTimeout(temporizador);
        temporizador = null;
        ejecutando = false;
        if (stream) stream.getTracks().forEach((track) => track.stop());
        stream = null;
        const video = elemento("rf-video");
        if (video) video.srcObject = null;
        marcarBoton(false);
        detenerActividadEstacion();
    }

    // ---- Modo movil: la PC solo escucha resultados y puede pedir capturas ----

    function tokenMovilVinculado() {
        return localStorage.getItem("mrgym_camara_remota_token");
    }

    function conectarEscuchaMovil() {
        if (socketEscucha && (socketEscucha.readyState === WebSocket.OPEN || socketEscucha.readyState === WebSocket.CONNECTING)) return;
        const token = tokenMovilVinculado();
        if (!token) { estado("Enlaza primero el móvil de confianza desde Configuración", "error"); return; }
        const wsBase = API_BASE_URL.replace(/^http/, "ws");
        socketEscucha = new WebSocket(`${wsBase}/ws/camara-remota/${encodeURIComponent(token)}/pc`);
        socketEscucha.onopen = () => estado("Escuchando el celular vinculado...", "ok");
        socketEscucha.onclose = () => { if (escuchandoMovil) window.setTimeout(conectarEscuchaMovil, 2000); };
        socketEscucha.onmessage = (evento) => {
            let mensaje;
            try { mensaje = JSON.parse(evento.data); } catch (_) { return; }
            if (mensaje.tipo === "movil-conectado") estado("Celular conectado. Reconocimiento activo.", "ok");
            else if (mensaje.tipo === "movil-desconectado") estado("El celular vinculado se desconectó. Reconectando...", "error");
            else if (mensaje.tipo === "asistencia_resultado") {
                publicarIngresoFacial(mensaje.cliente_id, mensaje.nombre, mensaje.mensaje);
                if (mensaje.ok) { if (typeof window.showSuccess === "function") window.showSuccess(mensaje.mensaje); }
                else if (mensaje.cliente_id && typeof window.mostrarFichaParaAsistencia === "function") {
                    // Deuda vencida, membresia vencida, etc.: salta al cliente en
                    // la busqueda inteligente y avisa al counter con un parpadeo
                    // notorio (sin toast generico), ya que el celular esta
                    // desatendido en la entrada.
                    window.mostrarFichaParaAsistencia(mensaje.cliente_id);
                    document.getElementById("panel-clientes")?.scrollIntoView({ behavior: "smooth", block: "start" });
                    if (typeof window.alertarCounterFacial === "function") window.alertarCounterFacial();
                } else if (mensaje.cliente_id) {
                    // El counter no esta en Panel Principal (no existen las
                    // funciones de arriba en esta pagina): lo llevamos ahi
                    // para que vea la ficha completa y el aviso parpadeante.
                    window.location.href = `principal.html?rf_cliente=${encodeURIComponent(mensaje.cliente_id)}`;
                } else if (typeof window.showError === "function") {
                    window.showError(mensaje.mensaje);
                }
                const actualizaciones = [];
                if (typeof window.cargarUltimosIngresos === "function") actualizaciones.push(Promise.resolve().then(() => window.cargarUltimosIngresos()));
                if (typeof window.cargarDashboard === "function") actualizaciones.push(Promise.resolve().then(() => window.cargarDashboard()));
                if (actualizaciones.length) void Promise.allSettled(actualizaciones);
            } else if (mensaje.tipo === "registro_completo" || mensaje.tipo === "registro_error") {
                // El registro se confirma por sondeo (ver abrirRegistroFacialMovil);
                // esto solo sirve de aviso adicional si la estación queda abierta.
                if (mensaje.tipo === "registro_error" && typeof window.showError === "function") window.showError(mensaje.mensaje);
            }
        };
    }

    function desconectarEscuchaMovil() {
        escuchandoMovil = false;
        if (socketEscucha) { socketEscucha.onclose = null; socketEscucha.close(); }
        socketEscucha = null;
    }

    // Para que principal.html sepa si el modo movil sigue escuchando en
    // esta misma ventana (sin ventana emergente no hay heartbeat de
    // "estacion activa" que consultar).
    window.escuchandoMovilFacial = function () { return escuchandoMovil; };

    window.alternarReconocimientoFacial = async function () {
        if (esEstacion()) iniciarActividadEstacion();
        try {
            await cargarModoDispositivo();
            exigirModoActivo();
        } catch (error) {
            estado(error.message, "error");
            return;
        }

        if (modoDispositivo === "movil") {
            if (escuchandoMovil) {
                desconectarEscuchaMovil();
                apagarCamara();
                if (!esEstacion()) elemento("modal-reconocimiento-facial").classList.remove("active");
                return;
            }
            abrirModal("Reconocimiento facial (celular vinculado)");
            elemento("rf-camera").style.display = "none";
            estado("Conectando con el celular vinculado...");
            escuchandoMovil = true;
            marcarBoton(true);
            iniciarActividadEstacion();
            conectarEscuchaMovil();
            if (!esEstacion()) elemento("modal-reconocimiento-facial").classList.remove("active");
            return;
        }

        prepararGuiaSegmentada();
        if (stream || elemento("modal-reconocimiento-facial").classList.contains("active")) {
            if (!esEstacion() || stream) {
                window.cerrarReconocimientoFacial();
                return;
            }
        }
        modo = "reconocer";
        objetivoClienteId = null;
        ultimoCandidato = null;
        repeticionesCandidato = 0;
        actualizarProgresoCaptura(0);
        abrirModal("Reconocimiento facial");
        try {
            estado("Cargando cámara y rostros registrados...");
            const resultados = await Promise.all([
                window.apiFetch("/biometria-facial/descriptores"),
                cargarMotor(),
                encenderCamara(),
            ]);
            descriptores = resultados[0];
            if (!descriptores.length) {
                apagarCamara();
                estado("Aún no hay rostros registrados. Busca un cliente y usa Registrar rostro.");
                elemento("rf-ayuda").style.display = "none";
                return;
            }
            estado("Mira al frente y muévete ligeramente");
            ciclo();
            if (!esEstacion()) elemento("modal-reconocimiento-facial").classList.remove("active");
            estado("Reconocimiento activo en segundo plano", "ok");
        } catch (error) {
            apagarCamara();
            const denegado = error && (error.name === "NotAllowedError" || error.name === "PermissionDeniedError");
            estado(denegado ? "Permite el acceso a la webcam para continuar" : (error.message || "No se pudo iniciar la webcam"), "error");
        }
    };

    function abrirModal(titulo) {
        elemento("rf-titulo").textContent = titulo;
        elemento("modal-reconocimiento-facial").classList.add("active");
        elemento("rf-camera").style.display = "none";
        elemento("rf-ayuda").style.display = "block";
        estado("Preparando...");
    }

    function actualizarProgresoCaptura(cantidad) {
        const guia = elemento("rf-camera")?.querySelector(".rf-guide");
        if (!guia) return;
        const porcentaje = Math.min(100, Math.round((cantidad / CAPTURAS_REGISTRO) * 100));
        guia.style.setProperty("--rf-progreso", porcentaje);
        const trazo = guia.querySelector(".rf-guide-progress ellipse");
        if (trazo) trazo.style.strokeDashoffset = String(100 - porcentaje);
        guia.classList.toggle("completo", porcentaje === 100);
    }

    function prepararGuiaSegmentada() {
        document.querySelectorAll(".rf-guide-progress").forEach((svg) => {
            if (svg.childElementCount) return;
            const ovalo = document.createElementNS("http://www.w3.org/2000/svg", "ellipse");
            ovalo.setAttribute("cx", "160");
            ovalo.setAttribute("cy", "210");
            ovalo.setAttribute("rx", "151");
            ovalo.setAttribute("ry", "200");
            ovalo.setAttribute("pathLength", "100");
            svg.appendChild(ovalo);
        });
    }

    function validarRostro(resultado) {
        const caras = resultado.face || [];
        if (caras.length === 0) return { mensaje: "Coloca tu rostro dentro del óvalo" };
        const cara = caras[0];
        if (!cara.embedding || cara.embedding.length !== 1024) return { mensaje: "Acércate un poco a la cámara" };
        const confianza = Number(cara.faceScore || cara.score || cara.boxScore || 0);
        if (confianza < umbralRostro || !cara.box || cara.box[2] < anchoRostroMinimo) return { mensaje: "Acércate y mantén el rostro al frente" };
        return { cara };
    }

    function similitud(a, b) {
        return human.match.similarity(a, b, { order: 2, multiplier: 25, min: 0.2, max: 0.8 });
    }

    async function procesarReconocimiento(cara) {
        let mejor = null;
        let segundo = null;
        for (const item of descriptores) {
            const valorSimilitud = similitud(cara.embedding, item.descriptor);
            if (!mejor || valorSimilitud > mejor.similitud) {
                segundo = mejor;
                mejor = { item, similitud: valorSimilitud };
            } else if (!segundo || valorSimilitud > segundo.similitud) {
                segundo = { item, similitud: valorSimilitud };
            }
        }
        const margenSeguro = !mejor || !segundo || mejor.similitud - segundo.similitud >= 0.03;

        if (!mejor || mejor.similitud < UMBRAL_COINCIDENCIA || !margenSeguro) {
            ultimoCandidato = null;
            repeticionesCandidato = 0;
            estado("Rostro no reconocido. Intenta de nuevo.");
            return;
        }
        if (ultimoCandidato === mejor.item.cliente_id) repeticionesCandidato += 1;
        else {
            ultimoCandidato = mejor.item.cliente_id;
            repeticionesCandidato = 1;
        }
        if (repeticionesCandidato < 2) {
            estado("Verificando identidad...");
            return;
        }

        const clienteId = mejor.item.cliente_id;
        const nombre = mejor.item.nombre_completo;
        if (Date.now() - (ultimoIntentoPorCliente.get(clienteId) || 0) < 15000) return;
        ultimoIntentoPorCliente.set(clienteId, Date.now());
        ultimoCandidato = null;
        repeticionesCandidato = 0;
        try {
            const acceso = await window.apiFetch("/asistencias/reconocimiento-facial", {
                method: "POST",
                body: JSON.stringify({ cliente_id: clienteId }),
            });
            const mensaje = acceso.ya_registrada
                ? `${nombre}, tu ingreso ya estaba registrado.`
                : `Ingreso registrado correctamente. Bienvenido, ${nombre}.`;
            publicarIngresoFacial(clienteId, nombre, mensaje);
            estado("Reconocimiento activo en segundo plano", "ok");
            if (!acceso.ya_registrada && typeof window.showSuccess === "function") window.showSuccess(`Ingreso registrado: ${nombre}`);
            const actualizaciones = [];
            if (typeof window.cargarUltimosIngresos === "function") actualizaciones.push(Promise.resolve().then(() => window.cargarUltimosIngresos()));
            if (typeof window.cargarDashboard === "function") actualizaciones.push(Promise.resolve().then(() => window.cargarDashboard()));
            if (actualizaciones.length) void Promise.allSettled(actualizaciones);
        } catch (error) {
            const mensaje = error.message || "No se pudo autorizar el ingreso";
            if (typeof window.showError === "function") window.showError(`${nombre}: ${mensaje}`);
        }
    }

    function promedio(vectores) {
        const salida = new Array(1024).fill(0);
        vectores.forEach((vector) => vector.forEach((valor, i) => { salida[i] += valor; }));
        return salida.map((valor) => valor / vectores.length);
    }

    async function procesarRegistro(cara) {
        if (Date.now() - ultimaCaptura < 250) return;
        capturas.push(Array.from(cara.embedding));
        actualizarProgresoCaptura(capturas.length);
        ultimaCaptura = Date.now();
        if (capturas.length < CAPTURAS_REGISTRO) {
            estado(`Registrando rostro ${capturas.length} de ${CAPTURAS_REGISTRO}. Muévete ligeramente.`);
            return;
        }
        estado("Guardando registro facial...", "ok");
        apagarCamara();
        await window.apiFetch(`/clientes/${objetivoClienteId}/biometria-facial`, {
            method: "PUT",
            body: JSON.stringify({ descriptor: promedio(capturas), consentimiento: true, version_modelo: MODELO_VERSION }),
        });
        const clienteId = objetivoClienteId;
        window.cerrarReconocimientoFacial();
        if (typeof window.showSuccess === "function") window.showSuccess("Rostro registrado correctamente");
        window.dispatchEvent(new CustomEvent("mrgym:biometria-actualizada", { detail: { clienteId } }));
        if (typeof window.mostrarFichaParaAsistencia === "function") await window.mostrarFichaParaAsistencia(clienteId);
    }

    async function ciclo() {
        if (!stream || ejecutando) return;
        ejecutando = true;
        try {
            const resultado = await human.detect(elemento("rf-video"));
            const validacion = validarRostro(resultado);
            if (!validacion.cara) estado(validacion.mensaje);
            else if (modo === "reconocer") await procesarReconocimiento(validacion.cara);
            else if (modo === "registrar") await procesarRegistro(validacion.cara);
        } catch (error) {
            estado(error.message || "No se pudo analizar la imagen", "error");
        } finally {
            ejecutando = false;
            if (stream) temporizador = window.setTimeout(ciclo, intervaloMs);
        }
    }

    async function prepararCamara() {
        try {
            exigirModoActivo();
            estado("Iniciando cámara...");
            await Promise.all([cargarMotor(), encenderCamara()]);
            estado("Acomoda el rostro dentro del óvalo");
            ciclo();
        } catch (error) {
            apagarCamara();
            const denegado = error && (error.name === "NotAllowedError" || error.name === "PermissionDeniedError");
            estado(denegado ? "Permite el acceso a la webcam para continuar" : (error.message || "No se pudo iniciar la webcam"), "error");
            throw error;
        }
    }

    // ---- Registrar rostro de un cliente puntual desde el celular vinculado ----
    function detenerSondeoRegistroMovil() {
        if (sondeoRegistroMovil) { window.clearTimeout(sondeoRegistroMovil.temporizador); sondeoRegistroMovil = null; }
    }

    async function abrirRegistroFacialMovil(clienteId) {
        abrirModal("Registrar rostro del cliente");
        elemento("rf-camera").style.display = "none";
        estado("Enviando orden de captura al celular...");
        let antes;
        try {
            antes = await window.apiFetch(`/clientes/${clienteId}/biometria-facial`);
        } catch (error) {
            estado(error.message || "No se pudo consultar el estado facial del cliente", "error");
            return;
        }
        let armado;
        try {
            armado = await window.apiFetch("/camara-remota/armar-registro", {
                method: "POST",
                body: JSON.stringify({ cliente_id: clienteId }),
            });
        } catch (error) {
            estado(error.message || "El celular vinculado no está conectado ahora mismo", "error");
            return;
        }
        estado(`Muéstrale "CAPTURA FACIAL" en el celular a ${armado.cliente_nombre}. Esperando...`);
        const limite = Date.now() + MINUTOS_ESPERA_REGISTRO_MOVIL * 60 * 1000;
        const idSondeo = {};
        sondeoRegistroMovil = idSondeo;
        const revisar = async () => {
            if (sondeoRegistroMovil !== idSondeo) return; // se canceló (se cerró el modal)
            if (Date.now() > limite) {
                estado("No se detectó la captura a tiempo. Verifica el celular e inténtalo de nuevo.", "error");
                sondeoRegistroMovil = null;
                return;
            }
            try {
                const ahora = await window.apiFetch(`/clientes/${clienteId}/biometria-facial`);
                const cambio = ahora.registrada && (!antes.actualizado_en || ahora.actualizado_en !== antes.actualizado_en);
                if (cambio) {
                    sondeoRegistroMovil = null;
                    window.cerrarReconocimientoFacial();
                    if (typeof window.showSuccess === "function") window.showSuccess("Rostro registrado correctamente");
                    window.dispatchEvent(new CustomEvent("mrgym:biometria-actualizada", { detail: { clienteId } }));
                    if (typeof window.mostrarFichaParaAsistencia === "function") await window.mostrarFichaParaAsistencia(clienteId);
                    return;
                }
            } catch (_) { /* se reintenta en el siguiente sondeo */ }
            if (sondeoRegistroMovil === idSondeo) idSondeo.temporizador = window.setTimeout(revisar, 2000);
        };
        idSondeo.temporizador = window.setTimeout(revisar, 2000);
    }

    window.abrirRegistroFacial = async function (clienteId) {
        try {
            await cargarModoDispositivo();
            exigirModoActivo();
        } catch (error) {
            if (typeof window.showError === "function") window.showError(error.message);
            return;
        }
        if (modoDispositivo === "movil") {
            await abrirRegistroFacialMovil(clienteId);
            return;
        }
        prepararGuiaSegmentada();
        apagarCamara();
        modo = "registrar";
        objetivoClienteId = clienteId;
        capturas = [];
        ultimaCaptura = 0;
        ultimoCandidato = null;
        repeticionesCandidato = 0;
        abrirModal("Registrar rostro del cliente");
        elemento("rf-ayuda").style.display = "block";
        await prepararCamara();
    };

    window.iniciarRegistroFacial = async function () {
        await prepararCamara();
    };

    window.cerrarReconocimientoFacial = function () {
        detenerSondeoRegistroMovil();
        apagarCamara();
        const modal = elemento("modal-reconocimiento-facial");
        if (modal) modal.classList.remove("active");
        modo = null;
        objetivoClienteId = null;
        capturas = [];
    };

    window.addEventListener("pagehide", () => {
        desconectarEscuchaMovil();
        apagarCamara();
        detenerActividadEstacion();
    });

    // Aprovecha el tiempo ocioso después de cargar el panel. No abre la cámara
    // ni pide permisos; solo deja modelos y shaders listos para el primer clic.
    // En modo movil no hay nada que precargar (Human corre en el celular).
    const precargar = async () => {
        try {
            await cargarModoDispositivo();
            const activo = modoDispositivo !== "desactivado";
            const botonPrincipal = elemento("btn-reconocimiento-facial");
            if (botonPrincipal && !activo) botonPrincipal.style.display = "none";
            const botonRegistro = elemento("btn-registro-facial-cliente");
            if (botonRegistro && !activo) botonRegistro.style.display = "none";
            if (activo && modoDispositivo !== "movil") await cargarMotor();
        } catch (_) {}
    };
    if ("requestIdleCallback" in window) window.requestIdleCallback(precargar, { timeout: 4000 });
    else window.setTimeout(precargar, 2500);
})();
