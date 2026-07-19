/* api.js - Portal del alumno */
const API_BASE = ["localhost", "127.0.0.1"].includes(window.location.hostname)
    ? "http://localhost:8000"
    : `${window.location.origin}/api`;

/* Slug del gimnasio: se lee de ?gym=slug en la URL */
function getSlug() {
    return new URLSearchParams(window.location.search).get("gym") || sessionStorage.getItem("alumno_slug") || null;
}

function getToken() { return sessionStorage.getItem("alumno_token"); }
function getNombre() { return sessionStorage.getItem("alumno_nombre"); }
function escapeHTML(valor) { return String(valor ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"})[c]); }
function debeCambiarPassword() { return sessionStorage.getItem("alumno_cambiar_password") === "1"; }

function guardarSesion(token, nombre, gimnasioId, cambiarPassword = false) {
    sessionStorage.setItem("alumno_token", token);
    sessionStorage.setItem("alumno_nombre", nombre);
    if (gimnasioId != null) sessionStorage.setItem("alumno_gimnasio_id", gimnasioId);
    sessionStorage.setItem("alumno_cambiar_password", cambiarPassword ? "1" : "0");
    const slug = getSlug();
    if (slug) sessionStorage.setItem("alumno_slug", slug);
}

function cerrarSesion() {
    sessionStorage.clear();
    window.location.href = "login.html";
}

function requireAuth() {
    if (!getToken()) window.location.href = "login.html";
}

/* ================================================================
   PANTALLA DE CARGA (cold start de Render)
   Si la API tarda mas de 3 segundos, muestra un overlay amigable.
   Reintenta automaticamente hasta 3 veces.
   ================================================================ */
let _loadingOverlay = null;
let _loadingCount = 0;

function _mostrarCargando() {
    _loadingCount++;
    if (_loadingOverlay) return; // ya visible
    _loadingOverlay = document.createElement("div");
    _loadingOverlay.id = "loading-overlay";
    _loadingOverlay.innerHTML = `
        <div style="display:flex;flex-direction:column;align-items:center;gap:16px;">
            <div class="loading-spinner"></div>
            <div style="font-weight:600;font-size:1.05em;">Conectando con el servidor...</div>
            <div style="font-size:0.82em;color:#B0B0B0;">Esto puede tardar unos segundos</div>
        </div>
    `;
    _loadingOverlay.style.cssText = `
        position:fixed;top:0;left:0;right:0;bottom:0;z-index:9999;
        background:rgba(255,255,255,0.96);
        display:flex;align-items:center;justify-content:center;
        text-align:center;color:#333;
        font-family:-apple-system,BlinkMacSystemFont,"Inter",sans-serif;
    `;
    // Agregar spinner CSS si no existe
    if (!document.getElementById("loading-spinner-style")) {
        const style = document.createElement("style");
        style.id = "loading-spinner-style";
        style.textContent = `
            .loading-spinner {
                width:40px;height:40px;border-radius:50%;
                border:3px solid #E5E7EB;border-top-color:#7566B8;
                animation:spin-loading 0.8s linear infinite;
            }
            @keyframes spin-loading { to { transform:rotate(360deg); } }
        `;
        document.head.appendChild(style);
    }
    document.body.appendChild(_loadingOverlay);
}

function _ocultarCargando() {
    _loadingCount = Math.max(0, _loadingCount - 1);
    if (_loadingCount === 0 && _loadingOverlay) {
        _loadingOverlay.remove();
        _loadingOverlay = null;
    }
}

const _PORTAL_CACHE_PATHS = [
    "/portal-alumno/resumen",
    "/portal-alumno/mi-rutina",
    "/portal-alumno/ejercicios-completados",
    "/portal-alumno/agenda",
    "/portal-alumno/salas",
    "/portal-alumno/mi-nutricion",
    "/portal-alumno/mi-progreso",
    "/portal-alumno/progreso-entrenamiento",
    "/portal-alumno/retos",
];
const _revalidacionesPortal = new Map();
let _syncVersionPortal = Number(sessionStorage.getItem("alumno_sync_version") || 0);
let _precargaPortalProgramada = false;

function _cacheKeyPortal(path) {
    const sesion = (getToken() || "anonimo").slice(-12);
    return `alumno_cache:${sesion}:${path}`;
}

function _leerCachePortal(path) {
    try {
        const valor = sessionStorage.getItem(_cacheKeyPortal(path));
        return valor ? JSON.parse(valor) : null;
    } catch (_) { return null; }
}

function _precargarImagenesPortal(data) {
    const pendientes = [data];
    const urls = new Set();
    while (pendientes.length && urls.size < 80) {
        const valor = pendientes.pop();
        if (!valor) continue;
        if (Array.isArray(valor)) { pendientes.push(...valor); continue; }
        if (typeof valor !== "object") continue;
        Object.entries(valor).forEach(([clave, contenido]) => {
            if (typeof contenido === "string" && /(?:foto|imagen|logo)_url$/i.test(clave) && contenido) urls.add(urlFoto(contenido));
            else if (contenido && typeof contenido === "object") pendientes.push(contenido);
        });
    }
    urls.forEach(url => { const imagen = new Image(); imagen.decoding = "async"; imagen.src = url; });
}

function _guardarCachePortal(path, data, notificar = false) {
    const anterior = _leerCachePortal(path);
    const cambio = !anterior || JSON.stringify(anterior.data) !== JSON.stringify(data);
    try {
        sessionStorage.setItem(_cacheKeyPortal(path), JSON.stringify({ data, actualizado: Date.now() }));
    } catch (_) {}
    _precargarImagenesPortal(data);
    if (notificar && cambio) window.dispatchEvent(new CustomEvent("mrgym:cache-update", { detail: { path, data } }));
    return cambio;
}

function invalidarCachePortal() {
    const prefijo = `alumno_cache:${(getToken() || "anonimo").slice(-12)}:`;
    Object.keys(sessionStorage).filter(clave => clave.startsWith(prefijo)).forEach(clave => sessionStorage.removeItem(clave));
    sessionStorage.removeItem("alumno_cache_precarga");
}

async function _revalidarPortal(path, notificar = true) {
    if (_revalidacionesPortal.has(path)) return _revalidacionesPortal.get(path);
    const tarea = _apiFetchRed(path, { _silencioso: true })
        .then(data => { if (data !== undefined) _guardarCachePortal(path, data, notificar); return data; })
        .catch(() => null)
        .finally(() => _revalidacionesPortal.delete(path));
    _revalidacionesPortal.set(path, tarea);
    return tarea;
}

async function precargarPortalAlumno(forzar = false) {
    if (!getToken() || /login\.html$/.test(window.location.pathname)) return;
    const ultima = Number(sessionStorage.getItem("alumno_cache_precarga") || 0);
    if (!forzar && Date.now() - ultima < 60000) return;
    sessionStorage.setItem("alumno_cache_precarga", String(Date.now()));
    const pendientes = _PORTAL_CACHE_PATHS.filter(path => {
        if (forzar) return true;
        const cache = _leerCachePortal(path);
        return !cache || Date.now() - Number(cache.actualizado || 0) > 30000;
    });
    await Promise.allSettled(pendientes.map(path => _revalidarPortal(path, false)));
    if (pendientes.length) window.dispatchEvent(new CustomEvent("mrgym:cache-refresh"));
}

function _programarPrecargaPortal() {
    if (_precargaPortalProgramada) return;
    _precargaPortalProgramada = true;
    setTimeout(() => precargarPortalAlumno(), 250);
}

function escucharActualizacionesPortal(paths, callback) {
    const permitidos = new Set(paths);
    let temporizador = null;
    window.addEventListener("mrgym:cache-update", evento => {
        if (!permitidos.has(evento.detail?.path)) return;
        clearTimeout(temporizador);
        temporizador = setTimeout(callback, 40);
    });
    window.addEventListener("mrgym:cache-refresh", () => {
        clearTimeout(temporizador);
        temporizador = setTimeout(callback, 40);
    });
}

async function _consultarVersionPortal() {
    if (!getToken() || document.visibilityState === "hidden") return;
    try {
        const response = await fetch(`${API_BASE}/sync-version`, { cache: "no-store" });
        if (!response.ok) return;
        const version = Number((await response.json()).version || 0);
        if (!_syncVersionPortal) {
            _syncVersionPortal = version;
            sessionStorage.setItem("alumno_sync_version", String(version));
            return;
        }
        if (version !== _syncVersionPortal) {
            _syncVersionPortal = version;
            sessionStorage.setItem("alumno_sync_version", String(version));
            invalidarCachePortal();
            await precargarPortalAlumno(true);
        }
    } catch (_) {}
}

async function apiFetch(path, options = {}) {
    const metodo = String(options.method || "GET").toUpperCase();
    const cacheable = metodo === "GET" && _PORTAL_CACHE_PATHS.includes(path);
    if (cacheable) {
        const cache = _leerCachePortal(path);
        if (cache) {
            if (Date.now() - Number(cache.actualizado || 0) > 5000) _revalidarPortal(path, true);
            _programarPrecargaPortal();
            return cache.data;
        }
    }
    const data = await _apiFetchRed(path, options);
    if (cacheable && data !== undefined) _guardarCachePortal(path, data, false);
    if (cacheable) _programarPrecargaPortal();
    if (metodo !== "GET") invalidarCachePortal();
    return data;
}

async function _apiFetchRed(path, options = {}) {
    const { _silencioso = false, ...fetchOptions } = options;
    const headers = { "Content-Type": "application/json", ...(options.headers || {}) };
    const token = getToken();
    if (token) headers["Authorization"] = `Bearer ${token}`;

    const MAX_REINTENTOS = 3;
    const TIMEOUT_LOADING_MS = 3000; // mostrar overlay si tarda mas de 3s
    let loadingTimer = null;
    let mostroLoading = false;

    for (let intento = 1; intento <= MAX_REINTENTOS; intento++) {
        try {
            // Timer para mostrar overlay si tarda
            if (!_silencioso && !mostroLoading) {
                loadingTimer = setTimeout(() => {
                    mostroLoading = true;
                    _mostrarCargando();
                }, TIMEOUT_LOADING_MS);
            }

            const response = await fetch(`${API_BASE}${path}`, { ...fetchOptions, headers });

            const version = Number(response.headers.get("X-Sync-Version") || 0);
            if (version) {
                _syncVersionPortal = version;
                sessionStorage.setItem("alumno_sync_version", String(version));
            }

            if (loadingTimer) clearTimeout(loadingTimer);

            if (response.status === 401) {
                if (mostroLoading) _ocultarCargando();
                cerrarSesion();
                return;
            }
            const data = await response.json().catch(() => null);
            if (!response.ok) {
                if (mostroLoading) _ocultarCargando();
                throw new Error(data?.detail || `Error ${response.status}`);
            }

            if (mostroLoading) _ocultarCargando();
            return data;
        } catch (err) {
            if (loadingTimer) clearTimeout(loadingTimer);

            // Si es un error de red (cold start), reintentar
            if (intento < MAX_REINTENTOS && (err.message === "Failed to fetch" || err.message === "No se pudo conectar con el servidor" || err.name === "TypeError")) {
                if (!_silencioso && !mostroLoading) {
                    mostroLoading = true;
                    _mostrarCargando();
                }
                // Esperar antes de reintentar (2s, 4s)
                await new Promise(r => setTimeout(r, intento * 2000));
                continue;
            }
            if (mostroLoading) _ocultarCargando();
            throw err;
        }
    }
}

async function apiUploadFile(path, file, fieldName = "foto") {
    const headers = {};
    const token = getToken();
    if (token) headers["Authorization"] = `Bearer ${token}`;
    const formData = new FormData();
    const archivoOptimizado = await optimizarFotoPortal(file);
    formData.append(fieldName, archivoOptimizado);
    let response;
    try {
        response = await fetch(`${API_BASE}${path}`, { method: "POST", headers, body: formData });
    } catch {
        throw new Error("No se pudo conectar con el servidor");
    }
    if (response.status === 401) { cerrarSesion(); return; }
    const data = await response.json().catch(() => null);
    if (!response.ok) throw new Error(data?.detail || `Error ${response.status}`);
    const version = Number(response.headers.get("X-Sync-Version") || 0);
    if (version) {
        _syncVersionPortal = version;
        sessionStorage.setItem("alumno_sync_version", String(version));
    }
    invalidarCachePortal();
    return data;
}

async function optimizarFotoPortal(file) {
    if (!file?.type?.startsWith("image/") || file.size < 600 * 1024 || typeof createImageBitmap !== "function") return file;
    try {
        const bitmap = await createImageBitmap(file, { resizeWidth: 1280, resizeQuality: "high" });
        const canvas = document.createElement("canvas");
        canvas.width = bitmap.width;
        canvas.height = bitmap.height;
        const ctx = canvas.getContext("2d", { alpha: false });
        ctx.drawImage(bitmap, 0, 0);
        bitmap.close();
        const blob = await new Promise(resolve => canvas.toBlob(resolve, "image/webp", 0.74));
        canvas.width = canvas.height = 1;
        return blob ? new File([blob], "foto-optimizada.webp", { type: "image/webp" }) : file;
    } catch (_) {
        return file;
    }
}

function urlFoto(fotoUrl) {
    if (!fotoUrl) return null;
    return fotoUrl.startsWith("http") ? fotoUrl : `${API_BASE}${fotoUrl}`;
}

async function loginAlumno(dni, codigo) {
    const slug = getSlug();
    const body = { dni, codigo_acceso: codigo };
    if (slug) body.slug = slug;
    const response = await fetch(`${API_BASE}/auth/login-alumno`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "DNI o codigo incorrecto");
    guardarSesion(data.access_token, data.nombre, data.gimnasio_id, data.debe_cambiar_password);
    return data;
}

async function iniciarLoginAlumno(dni) {
    const slug = getSlug();
    const body = { dni };
    if (slug) body.slug = slug;
    const response = await fetch(`${API_BASE}/auth/iniciar-alumno`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "No se pudo iniciar el acceso");
    if (data.access_token) guardarSesion(data.access_token, data.nombre, data.gimnasio_id, data.debe_cambiar_password);
    return data;
}

async function cambiarPasswordAlumno(nuevaPassword) {
    const data = await apiFetch("/portal-alumno/cambiar-password", {
        method: "PUT",
        body: JSON.stringify({ nueva_password: nuevaPassword }),
    });
    if (data.access_token) guardarSesion(data.access_token, data.nombre, data.gimnasio_id, false);
    else sessionStorage.setItem("alumno_cambiar_password", "0");
    return data;
}

async function fetchInfoGym() {
    const slug = getSlug();
    if (!slug) return null;
    try {
        const r = await fetch(`${API_BASE}/gym/${slug}`);
        if (!r.ok) return null;
        return await r.json();
    } catch { return null; }
}

function getIniciales(nombre) {
    if (!nombre) return "??";
    return nombre.split(" ").filter(Boolean).map(p => p[0]).join("").substring(0, 2).toUpperCase();
}

function formatFecha(iso) {
    if (!iso) return "—";
    return new Date(iso).toLocaleDateString("es-PE");
}

function aplicarTemaPortal() {
    const oscuro = localStorage.getItem("alumno_tema") === "oscuro";
    document.documentElement.dataset.tema = oscuro ? "oscuro" : "claro";
    return oscuro;
}

function alternarTemaPortal() {
    const oscuro = document.documentElement.dataset.tema !== "oscuro";
    localStorage.setItem("alumno_tema", oscuro ? "oscuro" : "claro");
    aplicarTemaPortal();
    return oscuro;
}

aplicarTemaPortal();

function aplicarBloqueoPagoVencido(resumen) {
    const vencido = !!resumen?.pago_vencido;
    document.body.classList.toggle("pago-vencido", vencido);
    document.querySelectorAll('.nav-bottom a:not([href="mi-perfil.html"])').forEach(enlace => {
        enlace.classList.toggle("bloqueado-pago", vencido);
        enlace.setAttribute("aria-disabled", vencido ? "true" : "false");
    });
    if (!vencido) {
        document.querySelector(".aviso-pago-vencido")?.remove();
        return false;
    }

    const archivoActual = window.location.pathname.split("/").pop() || "mi-perfil.html";
    if (archivoActual !== "mi-perfil.html") {
        window.location.replace("mi-perfil.html?pago=vencido");
        return true;
    }
    const pagina = document.querySelector(".page");
    if (pagina && !document.querySelector(".aviso-pago-vencido")) {
        const aviso = document.createElement("div");
        aviso.className = "aviso-pago-vencido";
        aviso.innerHTML = "<strong>Tienes un pago vencido.</strong><span>Regulariza tu saldo para volver a acceder a los demás módulos.</span>";
        pagina.prepend(aviso);
    }
    return true;
}

async function intentarAsistenciaAutomatica(resumen) {
    if (!resumen || resumen.asistencia_hoy || resumen.pago_vencido || !resumen.sin_pagos_pendientes || !resumen.asistencia_ubicacion_configurada) return;
    if (!navigator.geolocation) return;
    const ultimoIntento = Number(sessionStorage.getItem("alumno_auto_asistencia_intento") || 0);
    if (Date.now() - ultimoIntento < 60 * 1000) return;
    try {
        const posicion = await obtenerUbicacionPrecisa({ tiempoMaximo: 25000, precisionObjetivo: 80 });
        sessionStorage.setItem("alumno_auto_asistencia_intento", String(Date.now()));
        try {
            const resultado = await apiFetch("/portal-alumno/marcar-asistencia", {
                method: "POST",
                body: JSON.stringify({
                    latitud: posicion.coords.latitude,
                    longitud: posicion.coords.longitude,
                    precision_metros: posicion.coords.accuracy,
                }),
            });
            if (!resultado?.registrada) return;
            resumen.asistencia_hoy = true;
            _guardarCachePortal("/portal-alumno/resumen", resumen, true);
            window.dispatchEvent(new CustomEvent("mrgym:asistencia-automatica", { detail: resultado }));
            const aviso = document.createElement("div");
            aviso.className = "asistencia-auto-toast";
            aviso.textContent = "✓ Asistencia marcada automáticamente";
            document.body.appendChild(aviso);
            setTimeout(() => aviso.remove(), 3500);
        } catch (_) {
            // Si esta fuera de la geocerca, no se registra ni se interrumpe el acceso de lectura.
        }
    } catch (_) {
        // La lectura puede mejorar al moverse cerca de una ventana; se permite reintentar pronto.
        sessionStorage.setItem("alumno_auto_asistencia_intento", String(Date.now()));
    }
}

/** Conserva la mejor lectura mientras el GPS del celular gana precision. */
function obtenerUbicacionPrecisa({ tiempoMaximo = 25000, precisionObjetivo = 80 } = {}) {
    return new Promise((resolve, reject) => {
        if (!navigator.geolocation) {
            reject(new Error("Este celular no permite comprobar tu ubicacion"));
            return;
        }
        let mejorPosicion = null;
        let finalizado = false;
        let vigilancia = null;
        let temporizador = null;

        const terminar = (posicion, error) => {
            if (finalizado) return;
            finalizado = true;
            if (temporizador) clearTimeout(temporizador);
            if (vigilancia != null) navigator.geolocation.clearWatch(vigilancia);
            if (posicion) resolve(posicion);
            else reject(error || new Error("No se pudo obtener tu ubicacion"));
        };

        temporizador = setTimeout(() => {
            if (mejorPosicion) terminar(mejorPosicion);
            else terminar(null, Object.assign(new Error("La ubicacion tardo demasiado"), { code: 3 }));
        }, tiempoMaximo);

        vigilancia = navigator.geolocation.watchPosition(posicion => {
            const precision = Number(posicion.coords.accuracy);
            if (!mejorPosicion || precision < Number(mejorPosicion.coords.accuracy)) mejorPosicion = posicion;
            if (precision <= precisionObjetivo) terminar(posicion);
        }, error => {
            if (error?.code === 1) terminar(null, error);
        }, { enableHighAccuracy: true, timeout: tiempoMaximo, maximumAge: 0 });
    });
}

let _modalPermisoUbicacionVisible = false;

function mostrarPrimerPermisoUbicacion(resumen) {
    if (_modalPermisoUbicacionVisible || document.getElementById("modal-permiso-ubicacion") || sessionStorage.getItem("alumno_permiso_ubicacion_pospuesto") === "1") return;
    _modalPermisoUbicacionVisible = true;
    const modal = document.createElement("div");
    modal.id = "modal-permiso-ubicacion";
    modal.style.cssText = "position:fixed;inset:0;z-index:12000;background:rgba(15,23,42,.6);display:flex;align-items:center;justify-content:center;padding:20px";
    modal.innerHTML = `<div style="width:min(420px,100%);background:var(--card-bg,#fff);color:var(--text-color,#263238);border-radius:16px;padding:24px;box-shadow:0 20px 55px rgba(0,0,0,.25);font-family:inherit">
        <h2 style="font-size:1.15rem;margin:0 0 10px">Activa tu ubicación</h2>
        <p style="font-size:.92rem;line-height:1.45;margin:0 0 18px">La usaremos únicamente para marcar tu asistencia automáticamente cuando estés dentro del gimnasio. Después de permitirla no tendrás que pulsar ningún botón.</p>
        <div style="display:flex;gap:10px;justify-content:flex-end">
            <button type="button" data-accion="despues" style="border:0;background:#e5e7eb;color:#374151;padding:10px 14px;cursor:pointer">Ahora no</button>
            <button type="button" data-accion="permitir" style="border:0;background:#218c5b;color:#fff;padding:10px 16px;font-weight:700;cursor:pointer">Permitir ubicación</button>
        </div>
    </div>`;
    const cerrar = () => { modal.remove(); _modalPermisoUbicacionVisible = false; };
    modal.querySelector('[data-accion="despues"]').addEventListener("click", () => {
        sessionStorage.setItem("alumno_permiso_ubicacion_pospuesto", "1");
        cerrar();
    });
    modal.querySelector('[data-accion="permitir"]').addEventListener("click", () => {
        sessionStorage.removeItem("alumno_permiso_ubicacion_pospuesto");
        cerrar();
        intentarAsistenciaAutomatica(resumen);
    });
    document.body.appendChild(modal);
}

async function gestionarAsistenciaAutomatica(resumen) {
    if (!resumen || resumen.asistencia_hoy || resumen.pago_vencido || !resumen.sin_pagos_pendientes || !resumen.asistencia_ubicacion_configurada) return;
    if (!navigator.geolocation) return;
    if (!navigator.permissions?.query) {
        intentarAsistenciaAutomatica(resumen);
        return;
    }
    try {
        const permiso = await navigator.permissions.query({ name: "geolocation" });
        if (permiso.state === "granted") intentarAsistenciaAutomatica(resumen);
        else if (permiso.state === "prompt") mostrarPrimerPermisoUbicacion(resumen);
    } catch (_) {
        intentarAsistenciaAutomatica(resumen);
    }
}

async function inicializarAccesoPortal() {
    if (!getToken() || /login\.html$/.test(window.location.pathname)) return;
    try {
        const resumen = await _apiFetchRed("/portal-alumno/resumen", { cache: "no-store", _silencioso: true });
        if (!resumen) return;
        _guardarCachePortal("/portal-alumno/resumen", resumen, false);
        if (aplicarBloqueoPagoVencido(resumen)) return;
        gestionarAsistenciaAutomatica(resumen);
    } catch (_) {}
}

setTimeout(inicializarAccesoPortal, 0);
window.addEventListener("mrgym:cache-update", evento => {
    if (evento.detail?.path !== "/portal-alumno/resumen" || !evento.detail.data) return;
    if (!aplicarBloqueoPagoVencido(evento.detail.data)) gestionarAsistenciaAutomatica(evento.detail.data);
});
setInterval(inicializarAccesoPortal, 60 * 1000);
setTimeout(_consultarVersionPortal, 80);
setInterval(_consultarVersionPortal, 15000);
document.addEventListener("visibilitychange", () => { if (document.visibilityState === "visible") _consultarVersionPortal(); });
