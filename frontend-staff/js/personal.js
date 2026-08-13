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
    ["sistema","SISTEMA"], ["configuracion","Configuración"],
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
            <div class="form-group"><label id="label-dni">DNI *</label><input type="text" id="u-dni"></div>
            <div class="form-group"><label id="label-celular">Celular *</label><input type="text" id="u-celular"></div>
        </div>
        <div class="form-group"><label id="label-fecha-nacimiento">Fecha de Nacimiento *</label><input type="date" id="u-fecha-nacimiento"></div>

        ${esStaffPage() ? `
        <div id="bloque-staff">
            <div class="form-group">
                <label>Username *</label>
                <input type="text" id="u-username" placeholder="ej: recepcion1">
                <small id="aviso-acceso-opcional" style="display:none;color:#636E72;">Déjalo vacío si por ahora no quieres darle acceso al software: se guardarán solo sus datos.</small>
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

<!-- Modal vista de accesos -->
<div id="modal-ver-acceso" class="modal">
    <div class="modal-content" style="max-width:560px;">
        <div class="modal-header">
            <h3 class="modal-title">Permisos y accesos</h3>
            <button class="modal-close" onclick="cerrarModalVerAcceso()">✕</button>
        </div>
        <div id="detalle-acceso-staff"></div>
        <div class="form-actions">
            <button class="btn btn-secondary" type="button" onclick="cerrarModalVerAcceso()">Cerrar</button>
        </div>
    </div>
</div>

<!-- Modal invitacion de acceso -->
<div id="modal-invitacion-staff" class="modal">
    <div class="modal-content" style="max-width:480px;">
        <div class="modal-header">
            <h3 class="modal-title">Invitar trabajador</h3>
            <button class="modal-close" onclick="cerrarModalInvitacion()">✕</button>
        </div>
        <p id="invitacion-staff-trabajador" style="margin:0 0 6px;color:#636E72;"></p>
        <p style="margin:0 0 16px;color:#636E72;font-size:.85em;">
            Le enviaremos un enlace seguro. El trabajador verá el usuario y los permisos que ya le asignaste, y creará su propia contraseña. El enlace vence en 72 horas.
        </p>
        <div class="form-group">
            <label>Correo del trabajador</label>
            <input type="email" id="invitacion-staff-email" placeholder="trabajador@correo.com">
        </div>
        <div style="display:flex;flex-wrap:wrap;gap:10px;">
            <button class="btn btn-secondary" type="button" onclick="invitarStaffPorCorreo()" style="flex:1 1 180px;">✉️ Enviar por correo</button>
            <button class="btn" type="button" onclick="invitarStaffPorWhatsApp()" style="flex:1 1 180px;background:#25D366;color:#fff;">💬 Enviar por WhatsApp</button>
        </div>
        <p id="invitacion-staff-telefono" style="margin:10px 0 0;color:#636E72;font-size:.78em;"></p>
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

function mostrandoOcultos() {
    const chk = document.getElementById("chk-mostrar-ocultos");
    return !!(chk && chk.checked);
}

function alternarOcultos() {
    cargarPersonal();
}

/**
 * Filas de la tabla. En la pagina de staff se unen dos fuentes:
 *   - las cuentas de acceso (/usuarios/)
 *   - el personal staff que todavia NO tiene cuenta (/empleados/),
 *     por ejemplo el registrado desde Planilla Staff.
 * Sin esa union, ese personal queda invisible aqui.
 */
function construirFilasPersonal() {
    if (!esStaffPage()) {
        return empleadosCache
            .filter(e => e.tipo === "profesor_de_sala")
            .map(e => ({
                tipo: "empleado", id: e.id, nombre: e.nombre_completo,
                puesto: e.puesto || "—", dni: e.dni || "—",
                acceso: '<span class="badge badge-success" style="font-size:0.65em;">Zona de Profesores</span>',
                activo: e.activo,
            }));
    }

    const filas = usuariosCache.map(u => {
        const empleado = u.empleado_id ? empleadosCache.find(e => e.id === u.empleado_id) : null;
        const permisoBadge = u.es_administrador
            ? '<span class="badge badge-info" style="font-size:0.65em;">Admin</span>'
            : `<span class="badge badge-warning" style="font-size:0.65em;">${(u.zonas_permitidas||"").split(",").filter(Boolean).length} zonas</span>`;
        return {
            tipo: "usuario", id: u.id, nombre: u.nombre_completo,
            puesto: empleado ? (empleado.puesto || "—") : "—",
            dni: empleado ? (empleado.dni || "—") : "—",
            acceso: `Software ${permisoBadge}`,
            activo: u.activo,
        };
    });

    const conCuenta = new Set(usuariosCache.map(u => u.empleado_id).filter(Boolean));
    empleadosCache
        .filter(e => e.tipo === "staff_fijo" && !conCuenta.has(e.id))
        .forEach(e => filas.push({
            tipo: "empleado", id: e.id, nombre: e.nombre_completo,
            puesto: e.puesto || "—", dni: e.dni || "—",
            acceso: '<span class="badge badge-warning" style="font-size:0.65em;">Sin acceso al software</span>',
            activo: e.activo,
        }));

    return filas;
}

async function cargarPersonal() {
    // Solo el administrador entra a esta pagina (ver initPersonal), asi
    // que siempre se pide tambien el personal oculto para poder listarlo.
    [empleadosCache, usuariosCache] = await Promise.all([
        apiFetch("/empleados/?incluir_inactivos=true"),
        apiFetch("/usuarios/"),
    ]);
    const tbody = document.getElementById("tabla-personal");

    const todas = construirFilasPersonal();
    const ocultas = todas.filter(f => !f.activo).length;
    const filas = mostrandoOcultos() ? todas : todas.filter(f => f.activo);

    const etiquetaOcultos = document.getElementById("etiqueta-ocultos");
    if (etiquetaOcultos) {
        etiquetaOcultos.textContent = ocultas ? `Mostrar ocultos (${ocultas})` : "Mostrar ocultos";
    }

    if (!filas.length) {
        tbody.innerHTML = `<tr class="empty-row"><td colspan="6">No hay ${esStaffPage() ? "staff" : "profesores"} ${mostrandoOcultos() ? "registrado" : "visible"}</td></tr>`;
        return;
    }

    tbody.innerHTML = filas.map(f => {
        const ref = `'${f.tipo}', ${f.id}`;
        const acciones = f.activo
            ? `<button class="btn btn-sm btn-secondary" onclick="abrirModalEditar(${ref})">Editar</button>
               ${esStaffPage() && f.tipo === "usuario"
                    ? `<button class="btn btn-sm" onclick="abrirModalInvitacion(${f.id})">Invitar</button>
                       <button class="btn btn-sm btn-secondary" onclick="abrirModalVerAcceso(${f.id})">Ver</button>`
                    : ""}
               ${esStaffPage() && f.tipo === "empleado"
                    ? `<button class="btn btn-sm btn-primary" onclick="abrirModalCrearAcceso(${f.id})">Crear acceso</button>`
                    : ""}
               <button class="btn btn-sm btn-secondary" onclick="ocultarPersonal(${ref}, true)">Ocultar</button>
               ${f.tipo === "empleado" ? `<button class="btn btn-sm btn-danger" onclick="eliminarPersonal(${f.id})">Eliminar</button>` : ""}`
            : `<button class="btn btn-sm btn-secondary" onclick="ocultarPersonal(${ref}, false)">Restaurar</button>
               ${f.tipo === "empleado" ? `<button class="btn btn-sm btn-danger" onclick="eliminarPersonal(${f.id})">Eliminar</button>` : ""}`;
        return `<tr${f.activo ? "" : ' style="opacity:.55;"'}>
        <td><strong>${escapeHTML(f.nombre)}</strong></td>
        <td>${escapeHTML(f.puesto)}</td>
        <td style="font-family:monospace;font-size:0.85em;">${escapeHTML(f.dni)}</td>
        <td>${f.acceso}</td>
        <td><span class="badge ${f.activo ? "badge-success" : "badge-error"}">${f.activo ? "Activo" : "Oculto"}</span></td>
        <td>${acciones}</td>
    </tr>`;
    }).join("");
}

/**
 * Ocultar no borra nada: el trabajador sale de los listados y de
 * Planilla, pierde el acceso al software y su historial de pagos se
 * conserva. Se puede restaurar con "Mostrar ocultos".
 */
async function ocultarPersonal(tipo, id, oculto) {
    const filas = construirFilasPersonal();
    const fila = filas.find(f => f.tipo === tipo && f.id === id);
    const nombre = fila ? fila.nombre : "este trabajador";
    const mensaje = oculto
        ? `¿Ocultar a ${nombre}?\n\nDejará de aparecer en Usuarios Staff y en Planilla, y si tiene cuenta perderá el acceso al software.\nNo se borra nada: su historial de pagos se conserva y puedes restaurarlo cuando quieras.`
        : `¿Restaurar a ${nombre}?\n\nVolverá a aparecer en los listados y recuperará su acceso al software si tenía cuenta.`;
    if (!(await confirmDialog(mensaje, oculto ? "Ocultar" : "Restaurar"))) return;

    try {
        const ruta = tipo === "usuario" ? `/usuarios/${id}/visibilidad` : `/empleados/${id}/visibilidad`;
        await apiFetch(ruta, { method: "PUT", body: JSON.stringify({ oculto }) });
        showSuccess(oculto ? "Trabajador ocultado" : "Trabajador restaurado");
        cargarPersonal();
    } catch (e) { showError(e.message); }
}

function abrirModalVerAcceso(usuarioId) {
    const usuario = usuariosCache.find(u => u.id === usuarioId);
    if (!usuario) { showError("No se encontró el trabajador"); return; }
    const empleado = usuario.empleado_id
        ? empleadosCache.find(e => e.id === usuario.empleado_id)
        : null;
    const zonas = (usuario.zonas_permitidas || "").split(",").map(z => z.trim()).filter(Boolean);
    const nombresZonas = usuario.es_administrador
        ? ["Todas las zonas del sistema"]
        : zonas.map(zona => (ZONAS_DISPONIBLES.find(([valor]) => valor === zona) || [zona, zona])[1]);
    const accesoRealEliminar = usuario.es_administrador || usuario.puede_eliminar;
    const accesoRealExportar = usuario.es_administrador || usuario.puede_exportar;
    const estado = usuario.activo
        ? '<span class="badge badge-success">Activo</span>'
        : '<span class="badge badge-error">Inactivo</span>';
    const pinCounter = usuario.pin_counter_configurado
        ? '<span class="badge badge-success">Counter: PIN configurado</span>'
        : '<span class="badge badge-warning">Counter: sin PIN</span>';
    const indicador = permitido => permitido
        ? '<span class="badge badge-success">Permitido</span>'
        : '<span class="badge badge-error">Sin permiso</span>';

    document.getElementById("detalle-acceso-staff").innerHTML = `
        <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:10px;margin-bottom:16px;">
            <div style="padding:12px;border:1px solid var(--color-borde);border-radius:10px;">
                <small style="color:var(--color-texto-secundario);">Trabajador</small>
                <div style="font-weight:600;margin-top:3px;">${escapeHTML(usuario.nombre_completo)}</div>
                <div style="font-size:.82em;color:var(--color-texto-secundario);">${escapeHTML((empleado && empleado.puesto) || "Sin puesto")}</div>
            </div>
            <div style="padding:12px;border:1px solid var(--color-borde);border-radius:10px;">
                <small style="color:var(--color-texto-secundario);">Ingreso al software</small>
                <div style="font-weight:600;margin-top:3px;">${escapeHTML(usuario.username)}</div>
                <div style="display:flex;gap:6px;flex-wrap:wrap;margin-top:5px;">${estado}${pinCounter}</div>
            </div>
        </div>
        <div style="display:flex;flex-direction:column;gap:8px;">
            <div style="display:flex;justify-content:space-between;gap:12px;align-items:center;padding:9px 0;border-bottom:1px solid var(--color-borde);">
                <span>Tipo de acceso</span>
                <strong>${usuario.es_administrador ? "Administrador · acceso total" : "Staff · acceso por zonas"}</strong>
            </div>
            <div style="display:flex;justify-content:space-between;gap:12px;align-items:center;padding:9px 0;border-bottom:1px solid var(--color-borde);">
                <span>Eliminar registros</span>${indicador(accesoRealEliminar)}
            </div>
            <div style="display:flex;justify-content:space-between;gap:12px;align-items:center;padding:9px 0;border-bottom:1px solid var(--color-borde);">
                <span>Exportar/importar datos</span>${indicador(accesoRealExportar)}
            </div>
        </div>
        <div style="margin-top:16px;">
            <strong style="font-size:.9em;">Zonas visibles al ingresar</strong>
            <div style="display:flex;flex-wrap:wrap;gap:6px;margin-top:8px;">
                ${(nombresZonas.length ? nombresZonas : ["Ninguna zona asignada"]).map(nombre =>
                    `<span class="badge ${nombresZonas.length ? "badge-info" : "badge-warning"}">${escapeHTML(nombre)}</span>`
                ).join("")}
            </div>
        </div>`;
    document.getElementById("modal-ver-acceso").classList.add("active");
}

function cerrarModalVerAcceso() {
    document.getElementById("modal-ver-acceso").classList.remove("active");
}

let invitacionStaffUsuarioId = null;

function datosTrabajadorInvitacion() {
    const usuario = usuariosCache.find(u => u.id === invitacionStaffUsuarioId);
    const empleado = usuario && usuario.empleado_id
        ? empleadosCache.find(e => e.id === usuario.empleado_id)
        : null;
    return { usuario, empleado };
}

function abrirModalInvitacion(usuarioId) {
    const usuario = usuariosCache.find(u => u.id === usuarioId);
    const empleado = usuario && usuario.empleado_id
        ? empleadosCache.find(e => e.id === usuario.empleado_id)
        : null;
    invitacionStaffUsuarioId = usuarioId;
    document.getElementById("invitacion-staff-trabajador").textContent =
        usuario ? `Trabajador: ${usuario.nombre_completo}` : "";
    document.getElementById("invitacion-staff-email").value = (empleado && empleado.email) || "";
    document.getElementById("invitacion-staff-telefono").textContent =
        empleado && empleado.telefono
            ? `WhatsApp: ${empleado.telefono}`
            : "Este trabajador no tiene celular registrado.";
    document.getElementById("modal-invitacion-staff").classList.add("active");
}

function cerrarModalInvitacion() {
    document.getElementById("modal-invitacion-staff").classList.remove("active");
    invitacionStaffUsuarioId = null;
}

async function generarInvitacionStaff(email, enviarCorreo) {
    return apiFetch(`/usuarios/${invitacionStaffUsuarioId}/invitacion-acceso`, {
        method: "POST",
        body: JSON.stringify({ email: email || null, enviar_correo: enviarCorreo }),
    });
}

function mensajeInvitacionStaff(nombre, enlace) {
    return `Hola ${nombre}, el gimnasio ya creó tu usuario y asignó tus permisos en Soft-Gym. Revisa tus accesos y crea tu contraseña personal desde este enlace (vence en 72 horas): ${enlace}`;
}

async function invitarStaffPorCorreo() {
    const email = document.getElementById("invitacion-staff-email").value.trim();
    if (!email) { showError("Escribe el correo del trabajador"); return; }
    try {
        const respuesta = await generarInvitacionStaff(email, true);
        if (respuesta.enviado) {
            showSuccess("Invitación enviada por correo");
        } else {
            const asunto = "Configura tu acceso a Soft-Gym";
            const cuerpo = mensajeInvitacionStaff(respuesta.nombre, respuesta.enlace);
            window.location.href = `mailto:${encodeURIComponent(email)}?subject=${encodeURIComponent(asunto)}&body=${encodeURIComponent(cuerpo)}`;
            showInfo("Abrimos tu correo con la invitación lista para enviar");
        }
        cerrarModalInvitacion();
    } catch (e) { showError(e.message); }
}

async function invitarStaffPorWhatsApp() {
    const { usuario, empleado } = datosTrabajadorInvitacion();
    if (!empleado || !empleado.telefono) {
        showError("Registra el celular del trabajador antes de invitarlo por WhatsApp");
        return;
    }
    const ventana = window.open("", "_blank");
    try {
        const respuesta = await generarInvitacionStaff(null, false);
        const url = linkWhatsApp(empleado.telefono, mensajeInvitacionStaff(usuario.nombre_completo, respuesta.enlace));
        if (ventana) ventana.location.href = url;
        else window.location.href = url;
        cerrarModalInvitacion();
    } catch (e) {
        if (ventana) ventana.close();
        showError(e.message);
    }
}

/**
 * Borrado definitivo de una ficha mal ingresada (un duplicado, por
 * ejemplo). El backend lo rechaza si el trabajador tiene cuenta de
 * acceso o historial; en ese caso queda ocultarlo.
 */
async function eliminarPersonal(empleadoId) {
    const empleado = empleadosCache.find(e => e.id === empleadoId);
    const nombre = empleado ? empleado.nombre_completo : "este trabajador";
    const mensaje = `¿Borrar definitivamente a ${nombre}?\n\nEsta acción NO se puede deshacer: su ficha desaparece del sistema.\nSi solo dejó de trabajar, usa "Ocultar" para conservar su historial.`;
    if (!(await confirmDialog(mensaje, "Borrar definitivamente"))) return;

    try {
        await apiFetch(`/empleados/${empleadoId}`, { method: "DELETE" });
        showSuccess("Trabajador eliminado");
        cargarPersonal();
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
        document.getElementById("u-es-admin").checked = false;
        document.getElementById("u-puede-eliminar").checked = false;
        document.getElementById("u-puede-exportar").checked = false;
        renderZonasChips("");
        onToggleAdmin();
        mostrarAvisoAccesoOpcional(false);
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

function llenarDatosEmpleado(empleado) {
    document.getElementById("u-nombre").value = empleado.nombre_completo;
    document.getElementById("u-dni").value = empleado.dni || "";
    document.getElementById("u-celular").value = empleado.telefono || "";
    document.getElementById("u-fecha-nacimiento").value = empleado.fecha_nacimiento || "";
    poblarSelectPuestos(empleado.puesto || null);
}

function abrirModalEditar(tipo, id) {
    limpiarFormulario();
    document.getElementById("modal-titulo").textContent = etiqueta().editarPersonal;

    if (esStaffPage() && tipo === "usuario") {
        const usuario = usuariosCache.find(u => u.id === id);
        const empleado = usuario.empleado_id ? empleadosCache.find(e => e.id === usuario.empleado_id) : null;
        editando = { usuario, empleado };

        document.getElementById("u-nombre").value = usuario.nombre_completo;
        document.getElementById("u-username").value = usuario.username;
        document.getElementById("u-es-admin").checked = !!usuario.es_administrador;
        document.getElementById("u-puede-eliminar").checked = !!usuario.puede_eliminar;
        document.getElementById("u-puede-exportar").checked = !!usuario.puede_exportar;
        renderZonasChips(usuario.zonas_permitidas);
        onToggleAdmin();
        if (empleado) llenarDatosEmpleado(empleado);
    } else if (esStaffPage()) {
        // Staff registrado en Planilla, todavia sin cuenta de acceso.
        const empleado = empleadosCache.find(e => e.id === id);
        editando = { empleado, usuario: null };
        llenarDatosEmpleado(empleado);
        mostrarAvisoAccesoOpcional(true);
    } else {
        const empleado = empleadosCache.find(e => e.id === id);
        editando = { empleado };
        llenarDatosEmpleado(empleado);
        document.getElementById("u-codigo-acceso").value = empleado.codigo_acceso || "";
    }

    document.getElementById("modal-usuario").classList.add("active");
}

/** Abre el modal para darle cuenta de software a un staff que ya existe. */
function abrirModalCrearAcceso(empleadoId) {
    const empleado = empleadosCache.find(e => e.id === empleadoId);
    if (!empleado) { showError("No se encontró el trabajador"); return; }
    limpiarFormulario();
    document.getElementById("modal-titulo").textContent = "Crear acceso al software";
    editando = { empleado, usuario: null };
    llenarDatosEmpleado(empleado);
    mostrarAvisoAccesoOpcional(true);
    document.getElementById("modal-usuario").classList.add("active");
    document.getElementById("u-username").focus();
}

/**
 * Modo "staff que ya existe": el trabajador ya esta registrado (por
 * ejemplo desde Planilla, que no pide DNI ni fecha), asi que esos
 * campos y el username dejan de ser obligatorios.
 */
function mostrarAvisoAccesoOpcional(visible) {
    const aviso = document.getElementById("aviso-acceso-opcional");
    if (aviso) aviso.style.display = visible ? "block" : "none";
    [["label-dni", "DNI"], ["label-celular", "Celular"], ["label-fecha-nacimiento", "Fecha de Nacimiento"]]
        .forEach(([id, texto]) => {
            const label = document.getElementById(id);
            if (label) label.textContent = visible ? texto : `${texto} *`;
        });
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

    // Al darle acceso a un staff que ya existe (creado en Planilla, que
    // no pide DNI ni fecha) solo se exige lo minimo: el resto se
    // completa cuando se tenga, sin bloquear la creacion del acceso.
    // Por lo mismo el username es opcional ahi: sin el se guardan solo
    // los datos del trabajador, sin darle acceso.
    const accesoOpcional = esStaffPage() && !!(editando && editando.empleado && !editando.usuario);

    if (!nombre || !puesto) {
        showError(`Completa nombre y ${etiqueta().singular.toLowerCase()}`);
        return;
    }
    if (!accesoOpcional && (!dni || !celular || !fechaNacimiento)) {
        showError(`Completa nombre, ${etiqueta().singular.toLowerCase()}, DNI, celular y fecha de nacimiento`);
        return;
    }

    // Validaciones previas para no dejar datos a medias
    let username = "", codigo = "";
    if (esStaffPage()) {
        username = document.getElementById("u-username").value.trim();
        if (!username && !accesoOpcional) { showError("El username es obligatorio"); return; }
    } else {
        codigo = document.getElementById("u-codigo-acceso").value.trim();
        if (!codigo) { showError("El código de acceso es obligatorio para profesores"); return; }
    }

    // Los campos vacios no se envian para no borrar lo que ya estaba.
    const datosEmpleado = { nombre_completo: nombre, tipo: PERSONAL_TIPO, puesto };
    if (dni) datosEmpleado.dni = dni;
    if (celular) datosEmpleado.telefono = celular;
    if (fechaNacimiento) datosEmpleado.fecha_nacimiento = fechaNacimiento;

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
            // Sin username (solo permitido en accesoOpcional) se guardan
            // unicamente los datos del trabajador, sin crearle cuenta.
            if (username) {
                const zonasSeleccionadas = Array.from(document.querySelectorAll("#zonas-chips input:checked")).map(c => c.value).join(",");
                const datosUsuario = {
                    nombre_completo: nombre, username, rol: "staff", empleado_id: empleadoId,
                    es_administrador: document.getElementById("u-es-admin").checked,
                    puede_eliminar: document.getElementById("u-puede-eliminar").checked,
                    puede_exportar: document.getElementById("u-puede-exportar").checked,
                    zonas_permitidas: zonasSeleccionadas,
                };
                if (editando && editando.usuario) {
                    await apiFetch(`/usuarios/${editando.usuario.id}`, { method: "PUT", body: JSON.stringify(datosUsuario) });
                } else {
                    await apiFetch("/usuarios/", { method: "POST", body: JSON.stringify(datosUsuario) });
                }
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
    // Zona exclusiva del administrador (el menu ya la oculta al resto y
    // el backend la protege; esto evita entrar por URL directa).
    if (!esAdministrador()) {
        const tbody = document.getElementById("tabla-personal");
        if (tbody) tbody.innerHTML = '<tr class="empty-row"><td colspan="6">Sección exclusiva del administrador</td></tr>';
        document.querySelectorAll(".header .btn").forEach(btn => { btn.style.display = "none"; });
        showError("Esta sección es solo para el administrador");
        setTimeout(() => { window.location.href = "principal.html"; }, 1500);
        return;
    }
    inyectarModalesPersonal();
    try {
        await cargarPuestos();
    } catch (e) {
        showError("No se pudo cargar el catálogo de " + etiqueta().plural.toLowerCase() + ": " + e.message);
    }
    cargarPersonal();
}
