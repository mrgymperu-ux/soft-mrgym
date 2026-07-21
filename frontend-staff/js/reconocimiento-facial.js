/* Reconocimiento facial local para el panel de staff.
   La webcam nunca se transmite: Human calcula el descriptor en este navegador. */
(function () {
    "use strict";

    const MODELO_VERSION = "human-3.3.6-faceres";
    const UMBRAL_COINCIDENCIA = 0.55;
    const CAPTURAS_REGISTRO = 5;
    let modoDispositivo = "desactivado";
    let umbralReal = 0.60;
    let umbralVivo = 0.60;
    let umbralRostro = 0.65;
    let anchoRostroMinimo = 120;
    let requiereParpadeo = true;
    let intervaloMs = 220;
    const CONFIG = {
        backend: "webgl",
        modelBasePath: "vendor/human/models/",
        cacheSensitivity: 0.01,
        filter: { enabled: true, equalization: true },
        face: {
            enabled: true,
            // La webcam del counter permanece vertical; evitar buscar rotaciones
            // reduce trabajo sin afectar el uso normal de frente.
            detector: { rotation: false, maxDetected: 2, minConfidence: 0.55 },
            mesh: { enabled: true },
            iris: { enabled: true },
            description: { enabled: true },
            antispoof: { enabled: true },
            liveness: { enabled: true },
            emotion: { enabled: false },
        },
        body: { enabled: false },
        hand: { enabled: false },
        object: { enabled: false },
        gesture: { enabled: true },
    };

    let human = null;
    let promesaMotor = null;
    let stream = null;
    let temporizador = null;
    let ejecutando = false;
    let modo = null;
    let objetivoClienteId = null;
    let descriptores = [];
    let parpadeoDetectado = false;
    let capturas = [];
    let ultimaCaptura = 0;
    let ultimoCandidato = null;
    let repeticionesCandidato = 0;
    let streamRemoto = null;
    let conexionRemota = null;
    let socketRemoto = null;
    let ofertaRemotaEnCurso = false;
    let candidatosRemotosPendientes = [];

    const elemento = (id) => document.getElementById(id);

    async function cargarModoDispositivo() {
        const config = await window.getConfiguracion();
        modoDispositivo = config.reconocimiento_facial_modo || "desactivado";
        if (modoDispositivo === "movil") {
            umbralReal = 0.45;
            umbralVivo = 0.45;
            umbralRostro = 0.55;
            anchoRostroMinimo = 85;
            requiereParpadeo = false;
            intervaloMs = 350;
            CONFIG.face.detector.minConfidence = 0.45;
            CONFIG.face.iris.enabled = false;
            CONFIG.gesture.enabled = false;
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
            ? { facingMode: "user", width: { ideal: 1920 }, height: { ideal: 1080 } }
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

    function apagarCamara() {
        if (temporizador) window.clearTimeout(temporizador);
        temporizador = null;
        ejecutando = false;
        if (stream && stream !== streamRemoto) stream.getTracks().forEach((track) => track.stop());
        stream = null;
        const video = elemento("rf-video");
        if (video) video.srcObject = null;
        marcarBoton(false);
    }

    function abrirModal(titulo) {
        elemento("rf-titulo").textContent = titulo;
        elemento("modal-reconocimiento-facial").classList.add("active");
        elemento("rf-camera").style.display = "none";
        elemento("rf-consentimiento").style.display = "none";
        elemento("rf-ayuda").style.display = "block";
        estado("Preparando...");
    }

    function reiniciarPruebaDeVida() {
        parpadeoDetectado = false;
        ultimoCandidato = null;
        repeticionesCandidato = 0;
        actualizarProgresoCaptura(0);
    }

    function actualizarProgresoCaptura(cantidad) {
        const guia = elemento("rf-camera")?.querySelector(".rf-guide");
        if (!guia) return;
        const porcentaje = Math.min(100, Math.round((cantidad / CAPTURAS_REGISTRO) * 100));
        guia.style.setProperty("--rf-progreso", porcentaje);
        const segmentos = guia.querySelectorAll(".rf-guide-progress line");
        const activos = Math.round(segmentos.length * porcentaje / 100);
        segmentos.forEach((segmento, indice) => segmento.classList.toggle("activo", indice < activos));
        guia.classList.toggle("completo", porcentaje === 100);
    }

    function prepararGuiaSegmentada() {
        document.querySelectorAll(".rf-guide-progress").forEach((svg) => {
            if (svg.childElementCount) return;
            const total = 188;
            for (let indice = 0; indice < total; indice += 1) {
                const linea = document.createElementNS("http://www.w3.org/2000/svg", "line");
                linea.setAttribute("x1", "160");
                linea.setAttribute("y1", "7");
                linea.setAttribute("x2", "160");
                linea.setAttribute("y2", "13");
                linea.setAttribute("transform", `rotate(${indice * 360 / total} 160 160)`);
                svg.appendChild(linea);
            }
        });
    }

    function huboParpadeo(resultado) {
        return (resultado.gesture || []).some((item) => String(item.gesture || "").toLowerCase().includes("blink"));
    }

    function validarRostro(resultado) {
        const caras = resultado.face || [];
        if (caras.length === 0) return { mensaje: "Coloca tu rostro dentro del óvalo" };
        if (caras.length > 1) return { mensaje: "Debe aparecer una sola persona" };
        const cara = caras[0];
        if (!cara.embedding || cara.embedding.length !== 1024) return { mensaje: "Acércate un poco a la cámara" };
        if ((cara.faceScore || 0) < umbralRostro || !cara.box || cara.box[2] < anchoRostroMinimo) return { mensaje: "Acércate y mantén el rostro al frente" };
        if (typeof cara.real === "number" && cara.real < umbralReal) return { mensaje: "No se detecta un rostro real" };
        if (typeof cara.live === "number" && cara.live < umbralVivo) return { mensaje: "Muévete ligeramente y parpadea" };
        return { cara };
    }

    function similitud(a, b) {
        return human.match.similarity(a, b, { order: 2, multiplier: 25, min: 0.2, max: 0.8 });
    }

    async function procesarReconocimiento(cara) {
        const candidatos = descriptores
            .map((item) => ({ ...item, similitud: similitud(cara.embedding, item.descriptor) }))
            .sort((a, b) => b.similitud - a.similitud);
        const mejor = candidatos[0];
        const segundo = candidatos[1];
        const margenSeguro = !segundo || mejor.similitud - segundo.similitud >= 0.03;

        if (!mejor || mejor.similitud < UMBRAL_COINCIDENCIA || !margenSeguro) {
            ultimoCandidato = null;
            repeticionesCandidato = 0;
            estado("Rostro no reconocido. Intenta de nuevo.");
            return;
        }
        if (ultimoCandidato === mejor.cliente_id) repeticionesCandidato += 1;
        else {
            ultimoCandidato = mejor.cliente_id;
            repeticionesCandidato = 1;
        }
        if (repeticionesCandidato < 2) {
            estado("Verificando identidad...");
            return;
        }

        const clienteId = mejor.cliente_id;
        const nombre = mejor.nombre_completo;
        avisarMovil(`Ingreso registrado correctamente. Bienvenido, ${nombre}.`);
        window.cerrarReconocimientoFacial();
        if (typeof window.showSuccess === "function") window.showSuccess(`Rostro reconocido: ${nombre}`);
        if (typeof window.mostrarFichaParaAsistencia === "function") await window.mostrarFichaParaAsistencia(clienteId);
    }

    function promedio(vectores) {
        const salida = new Array(1024).fill(0);
        vectores.forEach((vector) => vector.forEach((valor, i) => { salida[i] += valor; }));
        return salida.map((valor) => valor / vectores.length);
    }

    async function procesarRegistro(cara) {
        if (Date.now() - ultimaCaptura < 650) return;
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
            if (huboParpadeo(resultado)) parpadeoDetectado = true;
            const validacion = validarRostro(resultado);
            if (!validacion.cara) estado(validacion.mensaje);
            else if (requiereParpadeo && !parpadeoDetectado) estado("Parpadea una vez para comprobar que eres una persona");
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
            estado(modoDispositivo === "movil" ? "Preparando enlace QR para el móvil..." : "Iniciando webcam 1080p...");
            await Promise.all([cargarMotor(), encenderCamara()]);
            estado(requiereParpadeo ? "Mira al frente y parpadea una vez" : "Mira al frente y muévete ligeramente");
            ciclo();
        } catch (error) {
            apagarCamara();
            const denegado = error && (error.name === "NotAllowedError" || error.name === "PermissionDeniedError");
            estado(denegado ? "Permite el acceso a la webcam para continuar" : (error.message || "No se pudo iniciar la webcam"), "error");
        }
    }

    window.alternarReconocimientoFacial = async function () {
        prepararGuiaSegmentada();
        if (stream || elemento("modal-reconocimiento-facial").classList.contains("active")) {
            window.cerrarReconocimientoFacial();
            return;
        }
        modo = "reconocer";
        objetivoClienteId = null;
        reiniciarPruebaDeVida();
        abrirModal("Reconocimiento facial");
        try {
            await cargarModoDispositivo();
            exigirModoActivo();
            descriptores = await window.apiFetch("/biometria-facial/descriptores");
            if (!descriptores.length) {
                estado("Aún no hay rostros registrados. Busca un cliente y usa Registrar rostro.");
                elemento("rf-ayuda").style.display = "none";
                return;
            }
            await prepararCamara();
        } catch (error) {
            estado(error.message, "error");
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
        reiniciarPruebaDeVida();
        abrirModal("Registrar rostro del cliente");
        elemento("rf-consentimiento-check").checked = false;
        elemento("rf-consentimiento").style.display = "block";
        elemento("rf-ayuda").style.display = "none";
        estado("Confirma el consentimiento para comenzar");
    };

    window.iniciarRegistroFacial = async function () {
        if (!elemento("rf-consentimiento-check").checked) {
            estado("Debes confirmar la autorización del cliente", "error");
            return;
        }
        elemento("rf-consentimiento").style.display = "none";
        elemento("rf-ayuda").style.display = "block";
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
    });
    document.addEventListener("visibilitychange", () => {
        if (document.visibilityState === "hidden" && stream) window.cerrarReconocimientoFacial();
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
