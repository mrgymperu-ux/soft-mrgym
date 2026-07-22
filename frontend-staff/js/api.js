/* ==================================================================
   api.js - frontend-staff
   Comunicacion con el backend FastAPI para el panel de staff.
   ================================================================== */

// En desarrollo el frontend corre en :3000 y la API en :8000.
// En Render ambos se publican bajo el mismo dominio mediante nginx.
const API_BASE_URL = ["localhost", "127.0.0.1"].includes(window.location.hostname)
    ? "http://localhost:8000"
    : `${window.location.origin}/api`;

function escapeHTML(valor) {
    return String(valor ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"})[c]);
}

const SESSION_KEYS = {
    token: "mrgym_token",
    rol: "mrgym_rol",
    nombre: "mrgym_nombre",
};
let _syncVersionStaff = Number(sessionStorage.getItem("mrgym_sync_version") || 0);
const _operacionesEnCurso = new Map();
const _lecturasEnCurso = new Map();
const CACHE_LECTURA_PREFIX = "mrgym:lectura:v1:";
const CACHE_LECTURA_MAX_ENTRADAS = 24;
const CACHE_LECTURA_MAX_BYTES = 900000;

function _registrarVersionStaff(response) {
    const version = Number(response.headers.get("X-Sync-Version") || 0);
    if (!version) return;
    _syncVersionStaff = version;
    sessionStorage.setItem("mrgym_sync_version", String(version));
}

async function _consultarVersionStaff() {
    if (!getToken() || document.visibilityState === "hidden") return;
    try {
        const response = await fetch(`${API_BASE_URL}/sync-version`, { cache: "no-store" });
        if (!response.ok) return;
        const version = Number((await response.json()).version || 0);
        if (!_syncVersionStaff) {
            _syncVersionStaff = version;
            sessionStorage.setItem("mrgym_sync_version", String(version));
        } else if (version !== _syncVersionStaff) {
            _syncVersionStaff = version;
            sessionStorage.setItem("mrgym_sync_version", String(version));
            window.dispatchEvent(new CustomEvent("mrgym:datos-actualizados", { detail: { version } }));
        }
    } catch (_) {}
}

function guardarSesion(token, rol, nombre, permisos = {}) {
    sessionStorage.setItem(SESSION_KEYS.token, token);
    sessionStorage.setItem(SESSION_KEYS.rol, rol);
    sessionStorage.setItem(SESSION_KEYS.nombre, nombre);
    sessionStorage.setItem("mrgym_es_admin", permisos.es_administrador ? "1" : "0");
    sessionStorage.setItem("mrgym_es_superadmin", permisos.es_superadmin ? "1" : "0");
    sessionStorage.setItem("mrgym_puede_eliminar", permisos.puede_eliminar ? "1" : "0");
    sessionStorage.setItem("mrgym_puede_exportar", permisos.puede_exportar ? "1" : "0");
    sessionStorage.setItem("mrgym_zonas", permisos.zonas_permitidas || "");
    if (permisos.gimnasio_id != null) sessionStorage.setItem("mrgym_gimnasio_id", permisos.gimnasio_id);
    if (permisos.gimnasio_slug) sessionStorage.setItem("gimnasio_slug", permisos.gimnasio_slug);
}

function getToken() { return sessionStorage.getItem(SESSION_KEYS.token); }
function getRol() { return sessionStorage.getItem(SESSION_KEYS.rol); }
function getNombreUsuario() { return sessionStorage.getItem(SESSION_KEYS.nombre); }
function esAdministrador() { return sessionStorage.getItem("mrgym_es_admin") === "1"; }
function puedeEliminar() { return esAdministrador() || sessionStorage.getItem("mrgym_puede_eliminar") === "1"; }
function puedeExportar() { return esAdministrador() || sessionStorage.getItem("mrgym_puede_exportar") === "1"; }
function tieneAccesoZona(zona) {
    if (esAdministrador()) return true;
    const zonas = (sessionStorage.getItem("mrgym_zonas") || "").split(",").map(z => z.trim());
    return zonas.includes(zona);
}

function cerrarSesion() {
    limpiarCacheLectura();
    sessionStorage.removeItem(SESSION_KEYS.token);
    sessionStorage.removeItem(SESSION_KEYS.rol);
    sessionStorage.removeItem(SESSION_KEYS.nombre);
    sessionStorage.removeItem("mrgym_es_admin");
    sessionStorage.removeItem("mrgym_puede_eliminar");
    sessionStorage.removeItem("mrgym_puede_exportar");
    sessionStorage.removeItem("mrgym_zonas");
    sessionStorage.removeItem("mrgym_gimnasio_id");
    sessionStorage.removeItem("mrgym_moneda");
    window.location.href = "login.html";
}

function requireAuth() {
    if (!getToken()) window.location.href = "login.html";
}

async function apiFetch(path, options = {}) {
    const headers = { "Content-Type": "application/json", ...(options.headers || {}) };
    const token = getToken();
    if (token) headers["Authorization"] = `Bearer ${token}`;
    const metodo = String(options.method || "GET").toUpperCase();
    const huellaOperacion = metodo === "POST" ? `${path}|${options.body || ""}` : null;
    if (huellaOperacion && !headers["Idempotency-Key"]) {
        let pendiente = _operacionesEnCurso.get(huellaOperacion);
        if (!pendiente) {
            pendiente = { clave: crypto.randomUUID(), vence: Date.now() + 120000 };
            _operacionesEnCurso.set(huellaOperacion, pendiente);
        }
        headers["Idempotency-Key"] = pendiente.clave;
    }

    let response;
    try {
        response = await fetch(`${API_BASE_URL}${path}`, { ...options, headers });
    } catch (error) {
        throw new Error("No se pudo conectar con el servidor. Verifica que el backend este corriendo.");
    }

    _registrarVersionStaff(response);

    if (response.status === 401) { cerrarSesion(); throw new Error("Sesion expirada"); }

    let data = null;
    try { data = await response.json(); } catch {}

    // Una respuesta definitiva permite una operacion nueva. Ante error del
    // servidor se conserva la clave para que Reintentar no duplique el cobro.
    if (huellaOperacion && (response.ok || response.status < 500)) _operacionesEnCurso.delete(huellaOperacion);
    for (const [huella, pendiente] of _operacionesEnCurso) {
        if (pendiente.vence < Date.now()) _operacionesEnCurso.delete(huella);
    }

    if (!response.ok) {
        const mensaje = (data && data.detail) ? data.detail : `Error ${response.status}`;
        if (response.status === 402) {
            sessionStorage.setItem("mrgym_suscripcion_bloqueada", "1");
            const pagina = window.location.pathname.split("/").pop();
            if (pagina !== "configuracion.html") window.location.href = "configuracion.html?subscription=required";
        }
        throw new Error(typeof mensaje === "string" ? mensaje : JSON.stringify(mensaje));
    }
    if (!{"GET":1,"HEAD":1}[metodo]) invalidarCacheLectura(path);
    return data;
}

function _ambitoCacheLectura() {
    const gimnasioId = sessionStorage.getItem("mrgym_gimnasio_id") || "sin-gym";
    const rol = getRol() || "sin-rol";
    return `${gimnasioId}:${rol}`;
}

function _claveCacheLectura(path) {
    return `${CACHE_LECTURA_PREFIX}${_ambitoCacheLectura()}:${path}`;
}

function _leerCacheLectura(path, maxStaleMs) {
    try {
        const entrada = JSON.parse(sessionStorage.getItem(_claveCacheLectura(path)) || "null");
        if (!entrada || entrada.datos === undefined || !entrada.guardadoEn) return null;
        if (Date.now() - entrada.guardadoEn > maxStaleMs) return null;
        return entrada;
    } catch (_) { return null; }
}

function _depurarCacheLectura() {
    const entradas = [];
    for (let i = 0; i < sessionStorage.length; i++) {
        const clave = sessionStorage.key(i);
        if (!clave || !clave.startsWith(CACHE_LECTURA_PREFIX)) continue;
        try {
            const valor = JSON.parse(sessionStorage.getItem(clave) || "null");
            entradas.push({ clave, guardadoEn: Number(valor?.guardadoEn || 0) });
        } catch (_) {
            sessionStorage.removeItem(clave);
        }
    }
    entradas.sort((a, b) => b.guardadoEn - a.guardadoEn);
    entradas.slice(CACHE_LECTURA_MAX_ENTRADAS).forEach(({ clave }) => sessionStorage.removeItem(clave));
}

function _guardarCacheLectura(path, datos) {
    try {
        const serializado = JSON.stringify({
            datos,
            guardadoEn: Date.now(),
            version: _syncVersionStaff,
        });
        if (serializado.length > CACHE_LECTURA_MAX_BYTES) return;
        sessionStorage.setItem(_claveCacheLectura(path), serializado);
        _depurarCacheLectura();
    } catch (_) {
        _depurarCacheLectura();
    }
}

function limpiarCacheLectura() {
    const claves = [];
    for (let i = 0; i < sessionStorage.length; i++) {
        const clave = sessionStorage.key(i);
        if (clave?.startsWith(CACHE_LECTURA_PREFIX) || clave?.startsWith("mrgym:comercial:")) claves.push(clave);
    }
    claves.forEach(clave => sessionStorage.removeItem(clave));
    _lecturasEnCurso.clear();
}

function invalidarCacheLectura(path) {
    try { sessionStorage.removeItem(_claveCacheLectura(path)); } catch (_) {}
}

function _refrescarLectura(path, forzarNueva = false) {
    const clave = _claveCacheLectura(path);
    let peticion = _lecturasEnCurso.get(clave);
    if (peticion && !forzarNueva) return peticion;
    peticion = apiFetch(path).then(datos => {
        if (_lecturasEnCurso.get(clave) === peticion) _guardarCacheLectura(path, datos);
        return datos;
    }).finally(() => {
        if (_lecturasEnCurso.get(clave) === peticion) _lecturasEnCurso.delete(clave);
    });
    _lecturasEnCurso.set(clave, peticion);
    return peticion;
}

/**
 * Lectura stale-while-revalidate para pantallas informativas.
 * Nunca acepta metodos de escritura y nunca cambia el comportamiento de
 * apiFetch: cada operacion POST/PUT/PATCH/DELETE sigue yendo al servidor.
 */
async function apiFetchConCache(path, opciones = {}) {
    const forzar = opciones.forzar === true;
    const maxStaleMs = Number(opciones.maxStaleMs || 12 * 60 * 60 * 1000);
    const cache = forzar ? null : _leerCacheLectura(path, maxStaleMs);
    if (!cache) {
        const datos = await _refrescarLectura(path, forzar);
        return { datos, desdeCache: false, actualizando: Promise.resolve(datos) };
    }

    // La pantalla recibe la copia local ya; la red se resuelve aparte. Si
    // falla, se conserva la ultima version sin generar un error no controlado.
    const actualizando = _refrescarLectura(path).catch(() => cache.datos);
    return {
        datos: cache.datos,
        desdeCache: true,
        actualizando,
        version: cache.version || 0,
    };
}

async function apiUploadFile(path, file, fieldName = "foto") {
    // Subida de archivos: NO se fija Content-Type manualmente, el
    // navegador arma el boundary del multipart/form-data solo.
    const headers = {};
    const token = getToken();
    if (token) headers["Authorization"] = `Bearer ${token}`;

    const formData = new FormData();
    formData.append(fieldName, file);

    let response;
    try {
        response = await fetch(`${API_BASE_URL}${path}`, { method: "POST", headers, body: formData });
    } catch (error) {
        throw new Error("No se pudo conectar con el servidor. Verifica que el backend este corriendo.");
    }


    _registrarVersionStaff(response);

    if (response.status === 401) { cerrarSesion(); throw new Error("Sesion expirada"); }

    let data = null;
    try { data = await response.json(); } catch {}

    if (!response.ok) {
        const mensaje = (data && data.detail) ? data.detail : `Error ${response.status}`;
        throw new Error(typeof mensaje === "string" ? mensaje : JSON.stringify(mensaje));
    }
    return data;
}

function urlFoto(fotoUrl) {
    if (!fotoUrl) return null;
    return fotoUrl.startsWith("http") ? fotoUrl : `${API_BASE_URL}${fotoUrl}`;
}

setTimeout(_consultarVersionStaff, 100);
// Sincronizacion ligera para reflejar asistencias y ventas casi en tiempo real.
setInterval(_consultarVersionStaff, 5000);
document.addEventListener("visibilitychange", () => { if (document.visibilityState === "visible") _consultarVersionStaff(); });

function avatarHtml(nombre, fotoUrl, extraStyle = "") {
    const url = urlFoto(fotoUrl);
    if (url) {
        return `<div class="resultado-avatar" style="padding:0;overflow:hidden;${extraStyle}"><img src="${url}" alt="${nombre}" onerror="this.onerror=null;this.src='/alumno-generico.svg'" style="width:100%;height:100%;object-fit:cover;"></div>`;
    }
    return `<div class="resultado-avatar" style="padding:0;overflow:hidden;${extraStyle}"><img src="/alumno-generico.svg" alt="Imagen genérica de alumno" style="width:100%;height:100%;object-fit:cover;"></div>`;
}

async function login(username, password) {
    const response = await fetch(`${API_BASE_URL}/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password }),
    });
    const data = await response.json().catch(() => null);
    if (!data) throw new Error("El servidor respondió en un formato incorrecto. Recarga la página e intenta nuevamente.");
    if (!response.ok) throw new Error(data.detail || "No se pudo iniciar sesion");
    guardarSesion(data.access_token, data.rol, data.nombre, {
        es_administrador: data.es_administrador,
        es_superadmin: data.es_superadmin,
        puede_eliminar: data.puede_eliminar,
        puede_exportar: data.puede_exportar,
        zonas_permitidas: data.zonas_permitidas,
        gimnasio_id: data.gimnasio_id,
    });
    return data;
}

async function obtenerUsuariosCounter(dispositivoToken) {
    const response = await fetch(`${API_BASE_URL}/counter/usuarios?dispositivo_token=${encodeURIComponent(dispositivoToken)}`);
    const data = await response.json().catch(() => null);
    if (!data) throw new Error("El servidor respondió en un formato incorrecto");
    if (!response.ok) throw new Error(data.detail || "No se pudo abrir el Counter");
    return data;
}

async function loginCounter(dispositivoToken, usuarioId, pin) {
    const response = await fetch(`${API_BASE_URL}/counter/login`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ dispositivo_token: dispositivoToken, usuario_id: usuarioId, pin }),
    });
    const data = await response.json().catch(() => null);
    if (!data) throw new Error("El servidor respondió en un formato incorrecto");
    if (!response.ok) throw new Error(data.detail || "No se pudo iniciar el turno");
    guardarSesion(data.access_token, data.rol, data.nombre, data);
    return data;
}

async function apiDescargarArchivo(path, nombreArchivoSugerido) {
    // Descarga autenticada (window.open/location.href NO envian el
    // header Authorization, asi que un endpoint protegido devolveria
    // 401). Se pide el archivo por fetch con el token y se dispara
    // la descarga en el navegador a partir del blob recibido.
    const headers = {};
    const token = getToken();
    if (token) headers["Authorization"] = `Bearer ${token}`;

    let response;
    try {
        response = await fetch(`${API_BASE_URL}${path}`, { headers });
    } catch (error) {
        throw new Error("No se pudo conectar con el servidor. Verifica que el backend este corriendo.");
    }

    if (response.status === 401) { cerrarSesion(); throw new Error("Sesion expirada"); }

    if (!response.ok) {
        let mensaje = `Error ${response.status}`;
        try { const data = await response.json(); if (data && data.detail) mensaje = data.detail; } catch {}
        throw new Error(mensaje);
    }

    const blob = await response.blob();
    let nombre = nombreArchivoSugerido;
    const disposicion = response.headers.get("Content-Disposition");
    if (disposicion) {
        const match = disposicion.match(/filename=([^;]+)/);
        if (match) nombre = match[1].trim().replace(/"/g, "");
    }

    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = nombre || "descarga.csv";
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
}

async function apiAbrirPdfEnNuevaPestana(path) {
    // Abre un PDF autenticado en una pestana nueva (para recibos que
    // el staff quiere ver/imprimir antes de compartir por WhatsApp).
    const headers = {};
    const token = getToken();
    if (token) headers["Authorization"] = `Bearer ${token}`;

    let response;
    try {
        response = await fetch(`${API_BASE_URL}${path}`, { headers });
    } catch (error) {
        throw new Error("No se pudo conectar con el servidor. Verifica que el backend este corriendo.");
    }

    if (response.status === 401) { cerrarSesion(); throw new Error("Sesion expirada"); }
    if (!response.ok) {
        let mensaje = `Error ${response.status}`;
        try { const data = await response.json(); if (data && data.detail) mensaje = data.detail; } catch {}
        throw new Error(mensaje);
    }

    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    window.open(url, "_blank");
}

let configuracionCache = null;

async function getConfiguracion() {
    if (configuracionCache) return configuracionCache;
    const respuesta = await apiFetchConCache("/configuracion/");
    configuracionCache = respuesta.datos;
    if (configuracionCache?.moneda) sessionStorage.setItem("mrgym_moneda", configuracionCache.moneda);
    if (respuesta.desdeCache) {
        respuesta.actualizando.then(datos => {
            configuracionCache = datos;
            if (datos?.moneda) sessionStorage.setItem("mrgym_moneda", datos.moneda);
        });
    }
    return configuracionCache;
}

function formatCurrency(amount, simboloMoneda) {
    const simbolo = simboloMoneda || (configuracionCache ? configuracionCache.moneda : "S/");
    return `${simbolo} ${(Number(amount) || 0).toFixed(2)}`;
}

function getIniciales(nombreCompleto) {
    if (!nombreCompleto) return "??";
    return nombreCompleto.split(" ").filter(Boolean).map(p => p[0]).join("").substring(0, 2).toUpperCase();
}

function formatFechaHora(isoString) {
    if (!isoString) return "-";
    const horaMin = new Date(isoString).toLocaleTimeString("es-PE", { hour: "2-digit", minute: "2-digit", hourCycle: "h23" });
    return `${formatFecha(isoString)} ${horaMin}`;
}

function formatHora(isoString) {
    if (!isoString) return "-";
    return new Date(isoString).toLocaleTimeString("es-PE", { hour: "2-digit", minute: "2-digit", hourCycle: "h23" });
}

function fechaLocalISO(fecha = new Date()) {
    const d = fecha instanceof Date ? fecha : new Date(fecha);
    const anio = d.getFullYear();
    const mes = String(d.getMonth() + 1).padStart(2, "0");
    const dia = String(d.getDate()).padStart(2, "0");
    return `${anio}-${mes}-${dia}`;
}

function formatFecha(fecha) {
    if (!fecha) return "-";
    // Formato pedido: dd-mm-aa (dia-mes-anio de 2 digitos).
    // Si es una fecha "pura" (YYYY-MM-DD, sin hora), hay que parsearla
    // como fecha LOCAL: new Date("2026-06-01") la interpreta como
    // medianoche UTC, y al mostrarla en una zona horaria negativa
    // (Peru, UTC-5) se corre un dia hacia atras (muestra 31-05 en vez
    // de 01-06). Las fechas CON hora (fecha_registro, etc.) si vienen
    // con su offset y se dejan pasar por el camino normal.
    let d;
    if (typeof fecha === "string" && /^\d{4}-\d{2}-\d{2}$/.test(fecha)) {
        const [anio, mes, dia] = fecha.split("-").map(Number);
        d = new Date(anio, mes - 1, dia);
    } else {
        d = new Date(fecha);
    }
    const dd = String(d.getDate()).padStart(2, "0");
    const mm = String(d.getMonth() + 1).padStart(2, "0");
    const aa = String(d.getFullYear()).slice(-2);
    return `${dd}-${mm}-${aa}`;
}

function _mrgymToastContainer() {
    let cont = document.getElementById("mrgym-toast-container");
    if (!cont) {
        cont = document.createElement("div");
        cont.id = "mrgym-toast-container";
        cont.style.cssText = "position:fixed;top:16px;right:16px;z-index:9999;display:flex;flex-direction:column;gap:8px;max-width:380px;pointer-events:none;";
        document.body.appendChild(cont);
    }
    return cont;
}

// Avisos flotantes (no empujan el contenido de la pagina, a
// diferencia de insertarlos arriba del .main-content). Se apilan en
// una esquina fija y se auto-eliminan solos.
function showAlert(message, type = "info") {
    const div = document.createElement("div");
    div.className = `alert alert-${type}`;
    div.style.cssText = "margin:0;box-shadow:0 6px 18px rgba(0,0,0,0.16);pointer-events:auto;";
    div.textContent = message;
    _mrgymToastContainer().appendChild(div);
    setTimeout(() => div.remove(), 4000);
}

function showAlertHtml(html, type = "info", duracionMs = 12000) {
    const div = document.createElement("div");
    div.className = `alert alert-${type}`;
    div.style.cssText = "margin:0;box-shadow:0 6px 18px rgba(0,0,0,0.16);pointer-events:auto;";
    div.innerHTML = html;
    _mrgymToastContainer().appendChild(div);
    setTimeout(() => div.remove(), duracionMs);
}

function showSuccess(message) { showAlert(message, "success"); }
function showError(message) { showAlert(message, "error"); }
function showInfo(message) { showAlert(message, "info"); }

// ---- Confirmacion propia (reemplaza el confirm() nativo del
// navegador, que en Windows se ve como una ventana oscura ajena al
// resto del sistema). Se inyecta una sola vez y se reutiliza. ----
function _mrgymAsegurarModalConfirmacion() {
    if (document.getElementById("mrgym-confirm-modal")) return;
    const wrap = document.createElement("div");
    wrap.innerHTML = `
    <div id="mrgym-confirm-modal" class="modal">
        <div class="modal-content" style="max-width:400px;">
            <div class="modal-header">
                <h3 class="modal-title" id="mrgym-confirm-titulo">Confirmar</h3>
            </div>
            <p id="mrgym-confirm-mensaje" style="font-size:0.92em;color:var(--color-texto);white-space:pre-line;margin:0 0 4px;"></p>
            <div class="form-actions">
                <button class="btn btn-secondary" id="mrgym-confirm-cancelar">Cancelar</button>
                <button class="btn btn-danger" id="mrgym-confirm-aceptar">Confirmar</button>
            </div>
        </div>
    </div>`;
    document.body.appendChild(wrap.firstElementChild);
}

/**
 * Reemplazo de window.confirm(): devuelve una Promise<boolean>.
 * Uso: if (!(await confirmDialog("¿Eliminar esto?"))) return;
 */
function confirmDialog(mensaje, textoConfirmar = "Confirmar") {
    _mrgymAsegurarModalConfirmacion();
    return new Promise((resolve) => {
        const modal = document.getElementById("mrgym-confirm-modal");
        document.getElementById("mrgym-confirm-mensaje").textContent = mensaje;
        const btnAceptar = document.getElementById("mrgym-confirm-aceptar");
        const btnCancelar = document.getElementById("mrgym-confirm-cancelar");
        btnAceptar.textContent = textoConfirmar;
        const cerrar = (resultado) => {
            modal.classList.remove("active");
            btnAceptar.removeEventListener("click", onAceptar);
            btnCancelar.removeEventListener("click", onCancelar);
            modal.removeEventListener("click", onFondo);
            resolve(resultado);
        };
        const onAceptar = () => cerrar(true);
        const onCancelar = () => cerrar(false);
        const onFondo = (e) => { if (e.target === modal) cerrar(false); };
        btnAceptar.addEventListener("click", onAceptar);
        btnCancelar.addEventListener("click", onCancelar);
        modal.addEventListener("click", onFondo);
        modal.classList.add("active");
    });
}

function linkWhatsApp(telefono, mensaje) {
    if (!telefono) return null;
    const tel = telefono.replace(/\D/g, "");
    const telConCodigo = tel.length === 9 ? "51" + tel : tel; // asume Peru si es un celular de 9 digitos
    return `https://wa.me/${telConCodigo}?text=${encodeURIComponent(mensaje)}`;
}
