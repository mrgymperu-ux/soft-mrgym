const API_BASE = ["localhost", "127.0.0.1"].includes(window.location.hostname)
    ? "http://localhost:8000"
    : window.location.origin;
function escapeHTML(valor) { return String(valor ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"})[c]); }
const SESSION_KEYS = { token: "mrgym_prof_token", nombre: "mrgym_prof_nombre" };

/* Slug del gimnasio: se lee de ?gym=slug en la URL */
function getSlug() {
    return new URLSearchParams(window.location.search).get("gym") || sessionStorage.getItem("mrgym_prof_slug") || null;
}

function guardarSesion(token, nombre, gimnasioId) {
    sessionStorage.setItem(SESSION_KEYS.token, token);
    sessionStorage.setItem(SESSION_KEYS.nombre, nombre);
    if (gimnasioId != null) sessionStorage.setItem("mrgym_prof_gimnasio_id", gimnasioId);
    const slug = getSlug();
    if (slug) sessionStorage.setItem("mrgym_prof_slug", slug);
}
function getToken() { return sessionStorage.getItem(SESSION_KEYS.token); }
function getNombre() { return sessionStorage.getItem(SESSION_KEYS.nombre); }

function cerrarSesion() {
    sessionStorage.removeItem(SESSION_KEYS.token);
    sessionStorage.removeItem(SESSION_KEYS.nombre);
    sessionStorage.removeItem("mrgym_prof_gimnasio_id");
    window.location.href = "login.html";
}

function requireAuth() {
    if (!getToken()) window.location.href = "login.html";
}

async function apiFetch(path, options = {}) {
    const headers = { "Content-Type": "application/json", ...(options.headers || {}) };
    const token = getToken();
    if (token) headers["Authorization"] = `Bearer ${token}`;
    let response;
    try {
        response = await fetch(`${API_BASE}${path}`, { ...options, headers });
    } catch {
        throw new Error("No se pudo conectar con el servidor");
    }
    if (response.status === 401) { cerrarSesion(); return; }
    const data = await response.json().catch(() => null);
    if (!response.ok) throw new Error(data?.detail || `Error ${response.status}`);
    return data;
}

async function loginProfesor(dni, codigo) {
    const slug = getSlug();
    const body = { dni, codigo_acceso: codigo };
    if (slug) body.slug = slug;
    const response = await fetch(`${API_BASE}/auth/login-profesor`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "No se pudo iniciar sesion");
    guardarSesion(data.access_token, data.nombre, data.gimnasio_id);
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
    if (!nombre) return "?";
    return nombre.trim().split(/\s+/).slice(0, 2).map(p => p[0]).join("").toUpperCase();
}

function formatFecha(fecha) {
    if (!fecha) return "—";
    const d = new Date(fecha + "T00:00:00");
    return d.toLocaleDateString("es-PE", { day: "2-digit", month: "short" });
}

function formatHora(fechaHora) {
    if (!fechaHora) return "—";
    return new Date(fechaHora).toLocaleTimeString("es-PE", { hour: "2-digit", minute: "2-digit" });
}
