/* api.js - Portal del alumno */
const API_BASE = "http://localhost:8000";

/* Slug del gimnasio: se lee de ?gym=slug en la URL */
function getSlug() {
    return new URLSearchParams(window.location.search).get("gym") || sessionStorage.getItem("alumno_slug") || null;
}

function getToken() { return sessionStorage.getItem("alumno_token"); }
function getNombre() { return sessionStorage.getItem("alumno_nombre"); }

function guardarSesion(token, nombre, gimnasioId) {
    sessionStorage.setItem("alumno_token", token);
    sessionStorage.setItem("alumno_nombre", nombre);
    if (gimnasioId != null) sessionStorage.setItem("alumno_gimnasio_id", gimnasioId);
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
    if (!nombre) return "??";
    return nombre.split(" ").filter(Boolean).map(p => p[0]).join("").substring(0, 2).toUpperCase();
}

function formatFecha(iso) {
    if (!iso) return "—";
    return new Date(iso).toLocaleDateString("es-PE");
}
