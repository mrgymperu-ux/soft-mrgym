/* api.js - Portal del alumno */
const API_BASE = "http://localhost:8000";

/* Slug del gimnasio: se lee de ?gym=slug en la URL */
function getSlug() {
    return new URLSearchParams(window.location.search).get("gym") || sessionStorage.getItem("alumno_slug") || null;
}

function getToken() { return sessionStorage.getItem("alumno_token"); }
function getNombre() { return sessionStorage.getItem("alumno_nombre"); }
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

async function apiFetch(path, options = {}) {
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
            if (!mostroLoading) {
                loadingTimer = setTimeout(() => {
                    mostroLoading = true;
                    _mostrarCargando();
                }, TIMEOUT_LOADING_MS);
            }

            const response = await fetch(`${API_BASE}${path}`, { ...options, headers });

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
                if (!mostroLoading) {
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
    formData.append(fieldName, file);
    let response;
    try {
        response = await fetch(`${API_BASE}${path}`, { method: "POST", headers, body: formData });
    } catch {
        throw new Error("No se pudo conectar con el servidor");
    }
    if (response.status === 401) { cerrarSesion(); return; }
    const data = await response.json().catch(() => null);
    if (!response.ok) throw new Error(data?.detail || `Error ${response.status}`);
    return data;
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

async function cambiarPasswordAlumno(nuevaPassword) {
    const data = await apiFetch("/portal-alumno/cambiar-password", {
        method: "PUT",
        body: JSON.stringify({ nueva_password: nuevaPassword }),
    });
    sessionStorage.setItem("alumno_cambiar_password", "0");
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
