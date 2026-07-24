/* Reconocimiento facial local para el panel de staff.
   La webcam nunca se transmite: Human calcula el descriptor en este navegador. */
(function () {
    "use strict";

    const MODELO_VERSION = "human-3.3.6-faceres";
    const UMBRAL_COINCIDENCIA = 0.55;
    const CAPTURAS_REGISTRO = 3;
    const CLAVE_ESTACION_ACTIVA = "mrgym_rf_estacion_activa";
    const CLAVE_EVENTO_RECONOCIDO = "mrgym_rf_evento";
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
    let streamRemoto = null;
    let conexionRemota = null;
    let socketRemoto = null;
    let ofertaRemotaEnCurso = false;
    let candidatosRemotosPendientes = [];
    let intervaloActividadEstacion = null;
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
        if (modoDispositivo === "movil") {
            umbralRostro = 0.55;
            anchoRostroMinimo = 85;
            intervaloMs = 240;
            CONFIG.face.detector.minConfidence = 0.45;
        }
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
        if (modoDispositivo === "movil") return encenderCamaraRemota();
        if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) throw new Error("Este navegador no permite usar la cámara");
        if (!window.isSecureContext) throw new Error("En el móvil abre el sistema con HTTPS para permitir la cámara");
        const videoConfig = modoDispositivo === "webcam_1080p"
            ? { facingMode: "user", width: { ideal: 1280 }, height: { ideal: 720 } }
            : { facingMode: { ideal: "user" }, width: { ideal: 640 }, height: { ideal: 480 } };
        stream = await navigator.mediaDevices.getUserMedia({
            audio: false,
            video: videoConfig,
        });
        const video = elemento("rf-video");
        video.srcObject = stream;
        await video.play();
        elemento("rf-camera").style.display = "block";
        marcarBoton(true);
        iniciarActividadEstacion();
    }

    function panelQrRemoto() {
        let panel = elemento("rf-qr-remoto");
        if (panel) return panel;
        panel = document.createElement("div");
        panel.id = "rf-qr-remoto";
        panel.style.cssText = "position:absolute;z-index:7;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:12px;background:#080b0a;color:#fff;text-align:center;padding:24px";
        panel.innerHTML = '<h3 style="margin:0">Conecta la cámara frontal</h3><img id="rf-qr-imagen" alt="QR para cámara remota" style="width:min(72vw,300px);background:#fff;padding:10px;border-radius:14px"><p style="margin:0;max-width:420px">Escanea el QR con el móvil. No necesitas iniciar sesión.</p>';
        elemento("modal-reconocimiento-facial").querySelector(".modal-content").appendChild(panel);
        return panel;
    }

    async function crearOfertaRemota() {
        if (!conexionRemota || !socketRemoto || socketRemoto.readyState !== WebSocket.OPEN || ofertaRemotaEnCurso) return;
        ofertaRemotaEnCurso = true;
        try {
            const oferta = await conexionRemota.createOffer();
            await conexionRemota.setLocalDescription(oferta);
            socketRemoto.send(JSON.stringify({ tipo: "offer", sdp: conexionRemota.localDescription }));
        } finally { ofertaRemotaEnCurso = false; }
    }

    async function encenderCamaraRemota() {
        const video = elemento("rf-video");
        if (streamRemoto && conexionRemota?.connectionState === "connected") {
            stream = streamRemoto;
            video.srcObject = stream;
            await video.play();
            elemento("rf-camera").style.display = "block";
            marcarBoton(true);
            iniciarActividadEstacion();
            return;
        }
        const tokenRemoto = localStorage.getItem("mrgym_camara_remota_token");
        if (!tokenRemoto) throw new Error("Enlaza primero el móvil de confianza desde Configuración");
        estado("Conectando con el móvil de confianza...");
        conexionRemota = new RTCPeerConnection({ iceServers: [{ urls: "stun:stun.l.google.com:19302" }] });
        conexionRemota.addTransceiver("video", { direction: "recvonly" });
        conexionRemota.onicecandidate = (evento) => evento.candidate && socketRemoto?.send(JSON.stringify({ tipo: "candidate", candidate: evento.candidate }));
        const llegada = new Promise((resolve, reject) => {
            const limite = window.setTimeout(() => reject(new Error("El QR venció o el móvil no se conectó")), 180000);
            conexionRemota.ontrack = async (evento) => {
                window.clearTimeout(limite);
                streamRemoto = evento.streams[0];
                stream = streamRemoto;
                video.srcObject = stream;
                await video.play();
                elemento("rf-camera").style.display = "block";
                marcarBoton(true);
                iniciarActividadEstacion();
                resolve();
            };
        });
        const protocolo = location.protocol === "https:" ? "wss" : "ws";
        socketRemoto = new WebSocket(`${protocolo}://${location.host}/api/ws/camara-remota/${encodeURIComponent(tokenRemoto)}/pc`);
        socketRemoto.onmessage = async (evento) => {
            const mensaje = JSON.parse(evento.data);
            if (mensaje.tipo === "movil-conectado" || mensaje.tipo === "movil-listo") await crearOfertaRemota();
            else if (mensaje.tipo === "answer") {
                await conexionRemota.setRemoteDescription(mensaje.sdp);
                for (const candidato of candidatosRemotosPendientes) await conexionRemota.addIceCandidate(candidato);
                candidatosRemotosPendientes = [];
            } else if (mensaje.tipo === "candidate" && mensaje.candidate) {
                if (conexionRemota.remoteDescription) await conexionRemota.addIceCandidate(mensaje.candidate);
                else candidatosRemotosPendientes.push(mensaje.candidate);
            }
        };
        await llegada;
    }

    function avisarMovil(mensaje) {
        if (socketRemoto?.readyState === WebSocket.OPEN) socketRemoto.send(JSON.stringify({ tipo: "resultado", mensaje }));
    }

    function guiarMovil(mensaje, progreso = 0, tipo = "") {
        if (socketRemoto?.readyState !== WebSocket.OPEN) return;
        socketRemoto.send(JSON.stringify({
            tipo: "guia",
            mensaje,
            progreso: Math.max(0, Math.min(100, Math.round(progreso))),
            estado: tipo,
            modo,
        }));
    }

    function apagarCamara() {
        if (temporizador) window.clearTimeout(temporizador);
        temporizador = null;
        ejecutando = false;
        if (stream && stream !== streamRemoto) stream.getTracks().forEach((track) => track.stop());
        stream = null;
        const video = elemento("rf-video");
        if (video) video.srcObject = null;
        marcarBoton(false);
        detenerActividadEstacion();
    }

    function abrirModal(titulo) {
        elemento("rf-titulo").textContent = titulo;
        elemento("modal-reconocimiento-facial").classList.add("active");
        elemento("rf-camera").style.display = "none";
        elemento("rf-ayuda").style.display = "block";
        estado("Preparando...");
    }

    function reiniciarFlujoFacial() {
        ultimoCandidato = null;
        repeticionesCandidato = 0;
        actualizarProgresoCaptura(0);
        guiarMovil("Acomoda tu rostro dentro del óvalo", 0, "buscando");
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
        if ((cara.faceScore || 0) < umbralRostro || !cara.box || cara.box[2] < anchoRostroMinimo) return { mensaje: "Acércate y mantén el rostro al frente" };
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
            guiarMovil("Rostro no reconocido. Intenta nuevamente.", 0, "error");
            return;
        }
        if (ultimoCandidato === mejor.item.cliente_id) repeticionesCandidato += 1;
        else {
            ultimoCandidato = mejor.item.cliente_id;
            repeticionesCandidato = 1;
        }
        if (repeticionesCandidato < 2) {
            estado("Verificando identidad...");
            guiarMovil("Rostro alineado. Mantente quieto.", 60, "alineado");
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
            avisarMovil(mensaje);
            guiarMovil("Identidad confirmada", 100, "completo");
            publicarIngresoFacial(clienteId, nombre, mensaje);
            estado("Reconocimiento activo en segundo plano", "ok");
            if (!acceso.ya_registrada && typeof window.showSuccess === "function") window.showSuccess(`Ingreso registrado: ${nombre}`);
            const actualizaciones = [];
            if (typeof window.cargarUltimosIngresos === "function") actualizaciones.push(Promise.resolve().then(() => window.cargarUltimosIngresos()));
            if (typeof window.cargarDashboard === "function") actualizaciones.push(Promise.resolve().then(() => window.cargarDashboard()));
            if (actualizaciones.length) void Promise.allSettled(actualizaciones);
        } catch (error) {
            const mensaje = error.message || "No se pudo autorizar el ingreso";
            avisarMovil(`${nombre}: ${mensaje}`);
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
        const progreso = Math.round((capturas.length / CAPTURAS_REGISTRO) * 100);
        guiarMovil(
            capturas.length < CAPTURAS_REGISTRO
                ? `Capturando rostro ${capturas.length} de ${CAPTURAS_REGISTRO}`
                : "Rostro capturado correctamente",
            progreso,
            progreso === 100 ? "completo" : "capturando",
        );
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
            if (!validacion.cara) {
                estado(validacion.mensaje);
                guiarMovil(validacion.mensaje, 0, "buscando");
            } else if (modo === "reconocer") await procesarReconocimiento(validacion.cara);
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
            estado(modoDispositivo === "movil" ? "Preparando enlace con el móvil..." : "Iniciando cámara...");
            await Promise.all([cargarMotor(), encenderCamara()]);
            estado("Acomoda el rostro dentro del óvalo");
            guiarMovil("Acomoda tu rostro dentro del óvalo", 0, "buscando");
            ciclo();
        } catch (error) {
            apagarCamara();
            const denegado = error && (error.name === "NotAllowedError" || error.name === "PermissionDeniedError");
            estado(denegado ? "Permite el acceso a la webcam para continuar" : (error.message || "No se pudo iniciar la webcam"), "error");
            throw error;
        }
    }

    window.alternarReconocimientoFacial = async function () {
        prepararGuiaSegmentada();
        if (esEstacion()) iniciarActividadEstacion();
        if (stream || elemento("modal-reconocimiento-facial").classList.contains("active")) {
            if (!esEstacion() || stream) {
                window.cerrarReconocimientoFacial();
                return;
            }
        }
        modo = "reconocer";
        objetivoClienteId = null;
        reiniciarFlujoFacial();
        abrirModal("Reconocimiento facial");
        try {
            await cargarModoDispositivo();
            exigirModoActivo();
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

    window.abrirRegistroFacial = async function (clienteId) {
        prepararGuiaSegmentada();
        try {
            await cargarModoDispositivo();
            exigirModoActivo();
        } catch (error) {
            if (typeof window.showError === "function") window.showError(error.message);
            return;
        }
        apagarCamara();
        modo = "registrar";
        objetivoClienteId = clienteId;
        capturas = [];
        ultimaCaptura = 0;
        reiniciarFlujoFacial();
        abrirModal("Registrar rostro del cliente");
        elemento("rf-ayuda").style.display = "block";
        await prepararCamara();
    };

    window.iniciarRegistroFacial = async function () {
        await prepararCamara();
    };

    window.cerrarReconocimientoFacial = function () {
        apagarCamara();
        const modal = elemento("modal-reconocimiento-facial");
        if (modal) modal.classList.remove("active");
        modo = null;
        objetivoClienteId = null;
        capturas = [];
    };

    window.addEventListener("pagehide", () => {
        if (streamRemoto) streamRemoto.getTracks().forEach((track) => track.stop());
        conexionRemota?.close();
        socketRemoto?.close();
        streamRemoto = null;
        apagarCamara();
        detenerActividadEstacion();
    });

    // Aprovecha el tiempo ocioso después de cargar el panel. No abre la cámara
    // ni pide permisos; solo deja modelos y shaders listos para el primer clic.
    const precargar = async () => {
        try {
            await cargarModoDispositivo();
            const activo = modoDispositivo !== "desactivado";
            const botonPrincipal = elemento("btn-reconocimiento-facial");
            if (botonPrincipal && !activo) botonPrincipal.style.display = "none";
            const botonRegistro = elemento("btn-registro-facial-cliente");
            if (botonRegistro && !activo) botonRegistro.style.display = "none";
            if (activo) await cargarMotor();
        } catch (_) {}
    };
    if ("requestIdleCallback" in window) window.requestIdleCallback(precargar, { timeout: 4000 });
    else window.setTimeout(precargar, 2500);
})();
