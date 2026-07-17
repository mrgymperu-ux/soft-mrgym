/* ==================================================================
   personal.js - frontend-staff
   Componente compartido para las paginas de Personal:
   usuarios-staff.html y usuarios-profesores.html.

   Inyecta por JS los modales de Nuevo/Editar Personal y de Gestion
   de Puestos/Especialidades (catalogo editable, tabla puestos del
   backend). Cada pagina llama a initPersonal("staff_fijo") o
   initPersonal("profesor_de_sala").

   Catalogo de puestos:
     - GET  /puestos/?tipo=X&solo_activos=true   -> opciones del select
     - GET  /puestos/?tipo=X&solo_activos=false  -> checklist de gestion
     - PUT  /puestos/{id} {activo}               -> mostrar/ocultar opcion
     - POST /puestos/                            -> agregar nuevo
   Desmarcar un puesto NO borra el dato de los empleados que ya lo
   tenian (Empleado.puesto es texto libre, no FK).
   ================================================================== */

let PERSONAL_TIPO = "staff_fijo"; // tipo de la pagina actual
let editando = null;              // { usuario, empleado } o null
let empleadosCache = [];
let usuariosCache = [];
let puestosCache = [];            // TODOS los puestos del tipo (activos e inactivos)

const ETIQUETAS = {
    staff_fijo: { singular: "Puesto", plural: "Puestos", nuevoPersonal: "Nuevo Staff", editarPersonal: "Editar Staff" },
    profesor_de_sala: { singular: "Especialidad", plural: "Especialidades", nuevoPersonal: "Nuevo Profesor", editarPersonal: "Editar Profesor" },
};

const ZONAS_DISPONIBLES = [
    ["clientes","Clientes"], ["membresias","Membresías"], ["productos","Productos"],
    ["ventas","Ventas"], ["venta_rapida","Venta Rápida"], ["asistencias","Asistencias"],
    ["agenda","Agenda"], ["entrenamientos","Rutinas"],
    ["nutricion","Nutrición"], ["retos","Retos"], ["planilla","Planilla"], ["pagos","Pagos"],
    ["configuracion","Configuración"],
];

function etiqueta() { return ETIQUETAS[PERSONAL_TIPO]; }
function esStaffPage() { return PERSONAL_TIPO === "staff_fijo"; }

// ==================================================================
// INYECCION DE MODALES
// ==================================================================

function inyectarModalesPersonal() {
    const et = etiqueta();
    const contenedor = document.createElement("div");
    contenedor.innerHTML = `
<!-- Modal personal -->
<div id="modal-usuario" class="modal">
    <div class="modal-content">
        <div class="modal-header">
            <h3 class="modal-title" id="modal-titulo">${et.nuevoPersonal}</h3>
            <button class="modal-close" onclick="cerrarModal()">✕</button>
        </div>

        <div class="form-group"><label>Nombre completo *</label><input type="text" id="u-nombre"></div>

        <div class="form-group">
            <label id="label-puesto">${et.singular} *</label>
            <select id="u-puesto-select" onchange="onPuestoSelectChange()"></select>
            <input type="text" id="u-puesto-nuevo" placeholder="Escribe ${esStaffPage() ? "el nuevo puesto" : "la nueva especialidad"}..." style="display:none;margin-top:6px;">
        </div>

        <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;">
            <div class="form-group"><label>DNI *</label><input type="text" id="u-dni"></div>
            <div class="form-group"><label>Celular *</label><input type="text" id="u-celular"></div>
        </div>
        <div class="form-group"><label>Fecha de Nacimiento *</label><input type="date" id="u-fecha-nacimiento"></div>

        ${esStaffPage() ? `
        <div id="bloque-staff">
            <div class="form-group"><label>Username *</label><input type="text" id="u-username" placeholder="ej: recepcion1"></div>
            <div class="form-group">
                <label id="label-pass">Contraseña *</label>
                <input type="password" id="u-password" placeholder="••••••••">
                <small id="hint-pass" style="color:#636E72;display:none;">Dejar en blanco para no cambiar la contraseña.</small>
            </div>
            <div class="form-group" style="border-top:1px solid var(--color-borde);padding-top:14px;">
                <label style="display:flex;align-items:center;gap:8px;cursor:pointer;"><input type="checkbox" id="u-es-admin" onchange="onToggleAdmin()" style="width:auto;"> Administrador (acceso total, incluye Usuarios y Metas/Comisiones)</label>
                <label style="display:flex;align-items:center;gap:8px;cursor:pointer;margin-top:8px;"><input type="checkbox" id="u-puede-eliminar" style="width:auto;"> Puede eliminar registros (clientes, membresías, productos)</label>
                <label style="display:flex;align-items:center;gap:8px;cursor:pointer;margin-top:8px;"><input type="checkbox" id="u-puede-exportar" style="width:auto;"> Puede exportar/importar datos (CSV con info de todos los clientes)</label>
            </div>
            <div class="form-group" id="zonas-wrap">
                <label>Zonas permitidas (solo aplica si NO es administrador)</label>
                <div id="zonas-chips" style="display:flex;flex-wrap:wrap;gap:6px;"></div>
            </div>
        </div>` : `
        <div id="bloque-profesor">
            <div class="form-group">
                <label>Código de acceso (Zona de Profesores) *</label>
                <input type="text" id="u-codigo-acceso" maxlength="10" placeholder="ej: 1234">
                <small style="color:#636E72;">El profesor entra con su DNI + este código. No tiene acceso al software de staff.</small>
            </div>
        </div>`}

        <div class="form-actions">
            <button class="btn btn-secondary" onclick="cerrarModal()">Cancelar</button>
            <button class="btn btn-primary" onclick="guardarPersonal()">Guardar</button>
        </div>
    </div>
</div>

<!-- Modal gestion de puestos/especialidades -->
<div id="modal-puestos" class="modal">
    <div class="modal-content" style="max-width:480px;">
        <div class="modal-header">
            <h3 class="modal-title">${et.plural} disponibles</h3>
            <button class="modal-close" onclick="cerrarModalPuestos()">✕</button>
        </div>
        <p style="font-size:0.82em;color:#636E72;margin:0 0 12px;">
            Desmarcar ${esStaffPage() ? "un puesto" : "una especialidad"} hace que ya no aparezca como opción al registrar personal nuevo,
            pero no borra el dato de quienes ya lo tenían asignado.
        </p>
        <div id="lista-puestos" style="display:flex;flex-direction:column;gap:4px;max-height:320px;overflow-y:auto;"></div>
        <div style="display:flex;gap:8px;margin-top:14px;border-top:1px solid var(--color-borde);padding-top:14px;">
            <input type="text" id="nuevo-puesto-nombre" placeholder="${esStaffPage() ? "Nuevo puesto..." : "Nueva especialidad..."}" style="flex:1;" onkeydown="if(event.key==='Enter')agregarPuesto()">
            <button class="btn btn-primary" onclick="agregarPuesto()">+ Agregar</button>
        </div>
    </div>
</div>`;
    while (contenedor.firstChild) document.body.appendChild(contenedor.firstChild);
}

// ==================================================================
// CATALOGO DE PUESTOS / ESPECIALIDADES
// ==================================================================

async function cargarPuestos() {
    puestosCache = await apiFetch(`/puestos/?tipo=${PERSONAL_TIPO}&solo_activos=false`);
}

function puestosActivos() {
    return puestosCache.filter(p => p.activo);
}

function poblarSelectPuestos(puestoActual) {
    // Opciones: puestos activos del catalogo + el puesto actual del
    // empleado editado aunque este inactivo o no exista en el
    // catalogo (para no perderlo al editar) + "Crear Nuevo".
    const nombres = puestosActivos().map(p => p.nombre);
    if (puestoActual && !nombres.includes(puestoActual)) nombres.unshift(puestoActual);
    document.getElementById("u-puesto-select").innerHTML =
        nombres.map(n => `<option value="${n}">${n}</option>`).join("") +
        `<option value="__nuevo__">+ Crear Nuevo</option>`;
    document.getElementById("u-puesto-select").value = puestoActual || (nombres[0] || "__nuevo__");
    onPuestoSelectChange();
}

function onPuestoSelectChange() {
    const esNuevo = document.getElementById("u-puesto-select").value === "__nuevo__";
    document.getElementById("u-puesto-nuevo").style.display = esNuevo ? "block" : "none";
}

function puestoSeleccionado() {
    const sel = document.getElementById("u-puesto-select").value;
    return sel === "__nuevo__" ? document.getElementById("u-puesto-nuevo").value.trim() : sel;
}

// ---- Modal de gestion ----

function abrirModalPuestos() {
    renderListaPuestos();
    document.getElementById("nuevo-puesto-nombre").value = "";
    document.getElementById("modal-puestos").classList.add("active");
}

function cerrarModalPuestos() {
    document.getElementById("modal-puestos").classList.remove("active");
}

function renderListaPuestos() {
    const cont = document.getElementById("lista-puestos");
    if (!puestosCache.length) {
        cont.innerHTML = `<p style="color:#636E72;font-size:0.85em;margin:0;">No hay ${etiqueta().plural.toLowerCase()} registrados aún.</p>`;
        return;
    }
    cont.innerHTML = puestosCache.map(p => `
        <label style="display:flex;align-items:center;gap:8px;cursor:pointer;padding:6px 8px;border-radius:8px;background:var(--color-fondo);${p.activo ? "" : "opacity:0.55;"}">
            <input type="checkbox" ${p.activo ? "checked" : ""} onchange="togglePuestoActivo(${p.id}, this.checked)" style="width:auto;margin:0;">
            <span>${p.nombre}</span>
            ${p.activo ? "" : '<span style="font-size:0.72em;color:#636E72;margin-left:auto;">oculto</span>'}
        </label>
    `).join("");
}

async function togglePuestoActivo(puestoId, activo) {
    try {
        const actualizado = await apiFetch(`/puestos/${puestoId}`, { method: "PUT", body: JSON.stringify({ activo }) });
        const indice = puestosCache.findIndex(p => p.id === puestoId);
        if (indice >= 0) puestosCache[indice] = actualizado;
        renderListaPuestos();
    } catch (e) {
        showError(e.message);
        renderListaPuestos(); // revierte el checkbox al estado real
    }
}

async function agregarPuesto() {
    const nombre = document.getElementById("nuevo-puesto-nombre").value.trim();
    if (!nombre) { showError(`Escribe el nombre ${esStaffPage() ? "del puesto" : "de la especialidad"}`); return; }
    try {
        await apiFetch("/puestos/", { method: "POST", body: JSON.stringify({ nombre, tipo: PERSONAL_TIPO }) });
        document.getElementById("nuevo-puesto-nombre").value = "";
        await cargarPuestos();
        renderListaPuestos();
        showSuccess(`${etiqueta().singular} agregado`);
    } catch (e) { showError(e.message); }
}

// ==================================================================
// TABLA DE PERSONAL
// ==================================================================

function renderZonasChips(zonasActivas) {
    if (!esStaffPage()) return;
    const activas = (zonasActivas || "").split(",").map(z => z.trim());
    document.getElementById("zonas-chips").innerHTML = ZONAS_DISPONIBLES.map(([valor, texto]) => `
        <label style="display:flex;align-items:center;gap:4px;font-size:0.78em;background:var(--color-fondo);padding:5px 9px;border-radius:14px;cursor:pointer;">
            <input type="checkbox" value="${valor}" ${activas.includes(valor) ? "checked" : ""} style="width:auto;margin:0;"> ${texto}
        </label>
    `).join("");
}

function onToggleAdmin() {
    if (!esStaffPage()) return;
    const esAdmin = document.getElementById("u-es-admin").checked;
    document.getElementById("zonas-wrap").style.opacity = esAdmin ? "0.4" : "1";
    document.getElementById("zonas-wrap").style.pointerEvents = esAdmin ? "none" : "auto";
}

async function cargarPersonal() {
    if (!esAdministrador()) {
        const btn = document.querySelector(".header .btn-primary");
        if (btn) btn.style.display = "none";
        const btnPuestos = document.getElementById("btn-gestionar-puestos");
        if (btnPuestos) btnPuestos.style.display = "none";
    }

    [empleadosCache, usuariosCache] = await Promise.all([apiFetch("/empleados/"), apiFetch("/usuarios/")]);
    const tbody = document.getElementById("tabla-personal");

    let filas;
    if (esStaffPage()) {
        filas = usuariosCache.map(u => {
            const empleado = u.empleado_id ? empleadosCache.find(e => e.id === u.empleado_id) : null;
            const permisoBadge = u.es_administrador
                ? '<span class="badge badge-info" style="font-size:0.65em;">Admin</span>'
                : `<span class="badge badge-warning" style="font-size:0.65em;">${(u.zonas_permitidas||"").split(",").filter(Boolean).length} zonas</span>`;
            return { nombre: u.nombre_completo, puesto: empleado ? (empleado.puesto || "—") : "—", dni: empleado ? (empleado.dni || "—") : "—",
                acceso: `Software ${permisoBadge}`, activo: u.activo, id: u.id };
        });
    } else {
        filas = empleadosCache.filter(e => e.tipo === "profesor_de_sala").map(e => ({
            nombre: e.nombre_completo, puesto: e.puesto || "—", dni: e.dni || "—",
            acceso: '<span class="badge badge-success" style="font-size:0.65em;">Zona de Profesores</span>', activo: e.activo, id: e.id,
        }));
    }

    if (!filas.length) {
        tbody.innerHTML = `<tr class="empty-row"><td colspan="6">No hay ${esStaffPage() ? "staff" : "profesores"} registrados</td></tr>`;
        return;
    }

    tbody.innerHTML = filas.map(f => `<tr>
        <td><strong>${f.nombre}</strong></td>
        <td>${f.puesto}</td>
        <td style="font-family:monospace;font-size:0.85em;">${f.dni}</td>
        <td>${f.acceso}</td>
        <td><span class="badge ${f.activo ? "badge-success" : "badge-error"}">${f.activo ? "Activo" : "Inactivo"}</span></td>
        <td>
            ${esAdministrador()
                ? `<button class="btn btn-sm btn-secondary" onclick="abrirModalEditar(${f.id})">✏️ Editar</button>
                   ${esStaffPage() ? `<button class="btn btn-sm" onclick="configurarPinCounter(${f.id})">PIN Counter</button>` : ""}`
                : '<span style="color:#636E72;font-size:0.8em;">Solo lectura</span>'}
        </td>
    </tr>`).join("");
}

async function configurarPinCounter(usuarioId) {
    const pin = prompt("Nuevo PIN de 6 digitos para este trabajador:");
    if (pin === null) return;
    if (!/^\d{6}$/.test(pin)) { showError("El PIN debe tener exactamente 6 digitos"); return; }
    try {
        await apiFetch(`/usuarios/${usuarioId}/pin-counter`, { method: "PUT", body: JSON.stringify({ pin }) });
        showSuccess("PIN Counter actualizado");
    } catch (e) { showError(e.message); }
}

// ==================================================================
// MODAL NUEVO / EDITAR PERSONAL
// ==================================================================

function limpiarFormulario() {
    document.getElementById("u-nombre").value = "";
    document.getElementById("u-dni").value = "";
    document.getElementById("u-celular").value = "";
    document.getElementById("u-fecha-nacimiento").value = "";
    if (esStaffPage()) {
        document.getElementById("u-username").value = "";
        document.getElementById("u-password").value = "";
        document.getElementById("u-es-admin").checked = false;
        document.getElementById("u-puede-eliminar").checked = false;
        document.getElementById("u-puede-exportar").checked = false;
        document.getElementById("label-pass").textContent = "Contraseña *";
        document.getElementById("hint-pass").style.display = "none";
        document.getElementById("u-password").placeholder = "••••••••";
        renderZonasChips("");
        onToggleAdmin();
    } else {
        document.getElementById("u-codigo-acceso").value = "";
    }
    document.getElementById("u-puesto-nuevo").value = "";
    poblarSelectPuestos(null);
}

function abrirModalNuevo() {
    editando = null;
    document.getElementById("modal-titulo").textContent = etiqueta().nuevoPersonal;
    limpiarFormulario();
    document.getElementById("modal-usuario").classList.add("active");
}

function abrirModalEditar(id) {
    limpiarFormulario();
    document.getElementById("modal-titulo").textContent = etiqueta().editarPersonal;

    if (esStaffPage()) {
        const usuario = usuariosCache.find(u => u.id === id);
        const empleado = usuario.empleado_id ? empleadosCache.find(e => e.id === usuario.empleado_id) : null;
        editando = { usuario, empleado };

        document.getElementById("u-nombre").value = usuario.nombre_completo;
        document.getElementById("u-username").value = usuario.username;
        document.getElementById("u-password").placeholder = "Dejar en blanco para no cambiar";
        document.getElementById("hint-pass").style.display = "block";
        document.getElementById("u-es-admin").checked = !!usuario.es_administrador;
        document.getElementById("u-puede-eliminar").checked = !!usuario.puede_eliminar;
        document.getElementById("u-puede-exportar").checked = !!usuario.puede_exportar;
        renderZonasChips(usuario.zonas_permitidas);
        onToggleAdmin();
        if (empleado) {
            document.getElementById("u-dni").value = empleado.dni || "";
            document.getElementById("u-celular").value = empleado.telefono || "";
            document.getElementById("u-fecha-nacimiento").value = empleado.fecha_nacimiento || "";
            poblarSelectPuestos(empleado.puesto || null);
        }
    } else {
        const empleado = empleadosCache.find(e => e.id === id);
        editando = { empleado };

        document.getElementById("u-nombre").value = empleado.nombre_completo;
        document.getElementById("u-dni").value = empleado.dni || "";
        document.getElementById("u-celular").value = empleado.telefono || "";
        document.getElementById("u-fecha-nacimiento").value = empleado.fecha_nacimiento || "";
        document.getElementById("u-codigo-acceso").value = empleado.codigo_acceso || "";
        poblarSelectPuestos(empleado.puesto || null);
    }

    document.getElementById("modal-usuario").classList.add("active");
}

function cerrarModal() {
    document.getElementById("modal-usuario").classList.remove("active");
    editando = null;
}

async function guardarPersonal() {
    const nombre = document.getElementById("u-nombre").value.trim();
    const dni = document.getElementById("u-dni").value.trim();
    const celular = document.getElementById("u-celular").value.trim();
    const fechaNacimiento = document.getElementById("u-fecha-nacimiento").value;
    const puesto = puestoSeleccionado();
    const esPuestoNuevo = document.getElementById("u-puesto-select").value === "__nuevo__";

    if (!nombre || !dni || !celular || !fechaNacimiento || !puesto) {
        showError(`Completa nombre, ${etiqueta().singular.toLowerCase()}, DNI, celular y fecha de nacimiento`);
        return;
    }

    // Validaciones previas para no dejar datos a medias
    let username = "", pass = "", codigo = "";
    if (esStaffPage()) {
        username = document.getElementById("u-username").value.trim();
        pass = document.getElementById("u-password").value;
        if (!username) { showError("El username es obligatorio"); return; }
        if (!editando && !pass) { showError("La contraseña es obligatoria para nuevo personal"); return; }
    } else {
        codigo = document.getElementById("u-codigo-acceso").value.trim();
        if (!codigo) { showError("El código de acceso es obligatorio para profesores"); return; }
    }

    const datosEmpleado = {
        nombre_completo: nombre, tipo: PERSONAL_TIPO, telefono: celular, dni,
        fecha_nacimiento: fechaNacimiento, puesto,
    };

    try {
        // Si el puesto es nuevo, tambien se registra en el catalogo
        // (el backend deduplica y reactiva si ya existia inactivo).
        if (esPuestoNuevo) {
            await apiFetch("/puestos/", { method: "POST", body: JSON.stringify({ nombre: puesto, tipo: PERSONAL_TIPO }) });
            await cargarPuestos();
        }

        let empleadoId;
        if (editando && editando.empleado) {
            await apiFetch(`/empleados/${editando.empleado.id}`, { method: "PUT", body: JSON.stringify(datosEmpleado) });
            empleadoId = editando.empleado.id;
        } else {
            const nuevoEmpleado = await apiFetch("/empleados/", { method: "POST", body: JSON.stringify(datosEmpleado) });
            empleadoId = nuevoEmpleado.id;
        }

        if (esStaffPage()) {
            const zonasSeleccionadas = Array.from(document.querySelectorAll("#zonas-chips input:checked")).map(c => c.value).join(",");
            const datosUsuario = {
                nombre_completo: nombre, username, rol: "staff", empleado_id: empleadoId,
                es_administrador: document.getElementById("u-es-admin").checked,
                puede_eliminar: document.getElementById("u-puede-eliminar").checked,
                puede_exportar: document.getElementById("u-puede-exportar").checked,
                zonas_permitidas: zonasSeleccionadas,
            };
            if (pass) datosUsuario.password = pass;

            if (editando && editando.usuario) {
                await apiFetch(`/usuarios/${editando.usuario.id}`, { method: "PUT", body: JSON.stringify(datosUsuario) });
            } else {
                datosUsuario.password = pass;
                await apiFetch("/usuarios/", { method: "POST", body: JSON.stringify(datosUsuario) });
            }
        } else {
            await apiFetch(`/empleados/${empleadoId}`, { method: "PUT", body: JSON.stringify({ codigo_acceso: codigo }) });
        }

        showSuccess("Personal guardado correctamente");
        cerrarModal();
        cargarPersonal();
    } catch (e) { showError(e.message); }
}

// ==================================================================
// INICIALIZACION
// ==================================================================

async function initPersonal(tipo) {
    PERSONAL_TIPO = tipo;
    inyectarModalesPersonal();
    try {
        await cargarPuestos();
    } catch (e) {
        showError("No se pudo cargar el catálogo de " + etiqueta().plural.toLowerCase() + ": " + e.message);
    }
    cargarPersonal();
}
