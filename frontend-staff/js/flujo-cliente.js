/* ==================================================================
   flujo-cliente.js - frontend-staff
   Flujo compartido "Nuevo Cliente -> Asignar Membresia -> Cobro y
   Contrato", pensado para llamarse desde cualquier pagina que ya
   tenga cargado api.js (usa apiFetch, apiDescargarArchivo,
   linkWhatsApp, formatCurrency, getConfiguracion, avatarHtml, etc).
   Los modales se inyectan una sola vez en <body> la primera vez que
   se necesitan.
   ================================================================== */

let _fcClienteCreado = null;
let _fcOnTerminar = null;
let _fcPlanesCache = [];
let _fcVendedoresCache = [];
let _fcClienteActivo = null; // {id, nombre}
let _fcUltimoCm = null; // ClienteMembresia recien creada
let _fcClienteEditandoId = null; // si no es null, el modal 'Nuevo Cliente' edita este cliente en vez de crear uno

function _fcInyectarModales() {
    if (document.getElementById("modal-fc-cliente")) return;

    const wrap = document.createElement("div");
    wrap.innerHTML = `
    <div id="modal-fc-cliente" class="modal">
        <div class="modal-content">
            <div class="modal-header">
                <h3 class="modal-title">Nuevo Cliente</h3>
                <button class="modal-close" onclick="cerrarModalFc('modal-fc-cliente')">✕</button>
            </div>
            <div class="form-row"><label>Nombre *</label><input type="text" id="fc-nombre" placeholder="Juan"></div>
            <div class="form-row"><label>Apellidos</label><input type="text" id="fc-apellidos" placeholder="Perez Garcia"></div>
            <div class="form-row"><label>DNI</label><input type="text" id="fc-dni" placeholder="12345678"></div>
            <div class="form-row"><label>Genero</label>
                <select id="fc-genero">
                    <option value="">-- Seleccionar --</option>
                    <option value="Masculino">Masculino</option>
                    <option value="Femenino">Femenino</option>
                    <option value="Otro">Otro</option>
                </select>
            </div>
            <div class="form-row"><label>Direccion</label><input type="text" id="fc-direccion"></div>
            <div class="form-row"><label>Celular</label><input type="text" id="fc-telefono" placeholder="987654321"></div>
            <div class="form-row"><label>Email</label><input type="email" id="fc-email" placeholder="juan@email.com"></div>
            <div class="form-row"><label>Fecha de Nacimiento</label><input type="date" id="fc-nacimiento"></div>
            <div class="form-row arriba">
                <label>Foto</label>
                <div style="display:flex;align-items:center;gap:10px;flex:1;">
                    <div id="fc-foto-preview" style="width:40px;height:40px;flex-shrink:0;"></div>
                    <button type="button" class="btn btn-secondary btn-sm" onclick="document.getElementById('fc-foto').click()">Seleccionar foto</button>
                    <span id="fc-foto-nombre" style="font-size:0.78em;color:var(--color-texto-secundario);"></span>
                    <input type="file" id="fc-foto" accept="image/jpeg,image/png,image/webp" style="display:none;" onchange="_fcPrevisualizarFoto(this)">
                </div>
            </div>
            <div class="form-actions">
                <button class="btn btn-secondary" onclick="cerrarModalFc('modal-fc-cliente')">Cancelar</button>
                <button class="btn btn-primary" onclick="_fcGuardarClienteYMembresia()">Guardar y Membresia</button>
            </div>
        </div>
    </div>

    <div id="modal-fc-membresia" class="modal">
        <div class="modal-content">
            <div class="modal-header">
                <h3 class="modal-title">Asignar Membresia</h3>
                <button class="modal-close" onclick="cerrarModalFc('modal-fc-membresia')">✕</button>
            </div>
            <p style="font-size:0.85em;color:var(--color-texto-secundario);margin-top:-6px;">Cliente: <strong id="fc-am-cliente-nombre"></strong></p>
            <div class="form-row"><label>Plan *</label><select id="fc-am-plan" onchange="_fcOnPlanChange()" style="min-width:0;width:100%;max-width:100%;font-size:.82em;padding:8px 10px;"><option value="">Seleccionar...</option></select></div>
            <div class="form-row"><label>Monto total</label><input type="text" id="fc-am-monto-total" disabled></div>
            <div class="form-row"><label>Congelamiento</label><input type="text" id="fc-am-congelamiento" disabled></div>
            <div class="form-row"><label>Condicion de pago</label><input type="text" id="fc-am-condicion" disabled></div>
            <div class="form-row"><label>Fecha de inicio</label><input type="date" id="fc-am-inicio" onchange="_fcRecalcularFin()"></div>
            <div class="form-row"><label>Fecha de fin</label><input type="date" id="fc-am-fin"></div>
            <div class="form-row"><label>Vendedor *</label><select id="fc-am-vendedor"></select></div>
            <div class="form-row"><label>Monto a pagar ahora *</label><input type="number" id="fc-am-monto-ahora" step="0.01" min="0" oninput="_fcRecalcularSaldo()"></div>
            <div class="form-row"><label>Forma de pago *</label>
                <select id="fc-am-metodo">
                    <option value="efectivo">Efectivo</option>
                    <option value="tarjeta">Tarjeta</option>
                    <option value="qr">Yape / Plin / QR</option>
                </select>
            </div>
            <div class="form-row" id="fc-am-saldo-row" style="display:none;"><label>Saldo pendiente</label><input type="text" id="fc-am-saldo" disabled></div>
            <div class="form-row" id="fc-am-fecha-saldo-row" style="display:none;"><label>Fecha de pago del saldo</label><input type="date" id="fc-am-fecha-saldo"></div>
            <div class="form-actions">
                <button class="btn btn-secondary" onclick="cerrarModalFc('modal-fc-membresia')">Cancelar</button>
                <button class="btn btn-primary" onclick="_fcAsignarMembresia()">Asignar</button>
            </div>
        </div>
    </div>

    <div id="modal-fc-cobro" class="modal">
        <div class="modal-content">
            <div class="modal-header">
                <h3 class="modal-title">Cobro y Contrato</h3>
                <button class="modal-close" onclick="_fcCerrarCobro()">✕</button>
            </div>
            <div id="fc-cobro-resumen" style="font-size:0.9em;margin-bottom:16px;"></div>
            <div style="display:flex;flex-direction:column;gap:10px;">
                <button class="btn btn-secondary" onclick="_fcDescargarRecibo()">📄 Descargar recibo</button>
                <button class="btn btn-secondary" onclick="_fcDescargarContrato()">📜 Descargar contrato</button>
                <button class="btn btn-success" onclick="_fcEnviarWhatsApp()">💬 Enviar por WhatsApp</button>
            </div>
            <p style="font-size:0.75em;color:var(--color-texto-secundario);margin-top:14px;">El contrato se descarga a tu carpeta de Descargas; WhatsApp se abre en otra pestaña con el mensaje listo, solo falta que adjuntes el archivo.</p>
            <div class="form-actions">
                <button class="btn btn-primary" onclick="_fcCerrarCobro()">Cerrar</button>
            </div>
        </div>
    </div>
    `;
    document.body.appendChild(wrap);
}

function cerrarModalFc(id) {
    document.getElementById(id).classList.remove("active");
}

let _fcFotoSeleccionada = null;

function _fcPrevisualizarFoto(input) {
    _fcFotoSeleccionada = input.files && input.files[0] ? input.files[0] : null;
    document.getElementById("fc-foto-nombre").textContent = _fcFotoSeleccionada ? _fcFotoSeleccionada.name : "";
    const wrap = document.getElementById("fc-foto-preview");
    if (_fcFotoSeleccionada) {
        const url = URL.createObjectURL(_fcFotoSeleccionada);
        wrap.innerHTML = `<div class="resultado-avatar" style="width:40px;height:40px;padding:0;overflow:hidden;"><img src="${url}" style="width:100%;height:100%;object-fit:cover;"></div>`;
    } else {
        wrap.innerHTML = "";
    }
}

/**
 * Abre el flujo completo: Nuevo Cliente -> Asignar Membresia -> Cobro/Contrato.
 * onTerminar(cliente) se llama cuando el flujo se cierra (con el
 * cliente ya creado), para que la pagina que llamo pueda refrescarse.
 */
function abrirModalClienteNuevo(onTerminar) {
    _fcInyectarModales();
    _fcOnTerminar = onTerminar || null;
    _fcFotoSeleccionada = null;
    _fcClienteEditandoId = null;
    document.querySelector("#modal-fc-cliente .modal-title").textContent = "Nuevo Cliente";
    document.querySelector('#modal-fc-cliente button[onclick="_fcGuardarClienteYMembresia()"]').textContent = "Guardar y Membresia";
    ["nombre", "apellidos", "dni", "telefono", "email", "nacimiento", "direccion", "genero"].forEach((f) => {
        const el = document.getElementById(`fc-${f}`);
        if (el) el.value = "";
    });
    document.getElementById("fc-foto").value = "";
    document.getElementById("fc-foto-preview").innerHTML = "";
    document.getElementById("fc-foto-nombre").textContent = "";
    document.getElementById("modal-fc-cliente").classList.add("active");
}

/**
 * Variante de reingreso: un cliente YA EXISTE (por ejemplo, se
 * importo directo a la tabla de Clientes con datos incompletos) y
 * solo le faltan algunos campos. Abre el MISMO formulario pero
 * precargado con sus datos actuales; al guardar hace PUT en vez de
 * POST, y despues sigue igual hacia 'Asignar Membresia'.
 */
function abrirModalClienteCompletar(cliente, onTerminar) {
    _fcInyectarModales();
    _fcOnTerminar = onTerminar || null;
    _fcFotoSeleccionada = null;
    _fcClienteEditandoId = cliente.id;
    document.querySelector("#modal-fc-cliente .modal-title").textContent = "Actualizar Datos";
    document.querySelector('#modal-fc-cliente button[onclick="_fcGuardarClienteYMembresia()"]').textContent = "Guardar y asignar membresía";
    document.getElementById("fc-nombre").value = cliente.nombre || "";
    document.getElementById("fc-apellidos").value = cliente.apellidos || "";
    document.getElementById("fc-dni").value = cliente.dni || "";
    document.getElementById("fc-genero").value = cliente.genero || "";
    document.getElementById("fc-direccion").value = cliente.direccion || "";
    document.getElementById("fc-telefono").value = cliente.telefono || "";
    document.getElementById("fc-email").value = cliente.email || "";
    document.getElementById("fc-nacimiento").value = cliente.fecha_nacimiento || "";
    document.getElementById("fc-foto").value = "";
    document.getElementById("fc-foto-preview").innerHTML = cliente.foto_url
        ? avatarHtml(`${cliente.nombre} ${cliente.apellidos || ""}`, cliente.foto_url, "width:40px;height:40px;")
        : "";
    document.getElementById("fc-foto-nombre").textContent = "";
    document.getElementById("modal-fc-cliente").classList.add("active");
}

async function _fcGuardarClienteYMembresia() {
    const datos = {
        nombre: document.getElementById("fc-nombre").value.trim(),
        apellidos: document.getElementById("fc-apellidos").value.trim() || null,
        dni: document.getElementById("fc-dni").value.trim() || null,
        telefono: document.getElementById("fc-telefono").value.trim() || null,
        email: document.getElementById("fc-email").value.trim() || null,
        fecha_nacimiento: document.getElementById("fc-nacimiento").value || null,
        direccion: document.getElementById("fc-direccion").value.trim() || null,
        genero: document.getElementById("fc-genero").value || null,
    };
    if (!datos.nombre) { showError("El nombre es obligatorio"); return; }
    const editandoId = _fcClienteEditandoId;
    try {
        let cliente = editandoId
            ? await apiFetch(`/clientes/${editandoId}`, { method: "PUT", body: JSON.stringify(datos) })
            : await apiFetch("/clientes/", { method: "POST", body: JSON.stringify(datos) });
        if (_fcFotoSeleccionada) {
            cliente = await apiUploadFile(`/clientes/${cliente.id}/foto`, _fcFotoSeleccionada);
        }
        _fcClienteCreado = cliente;
        _fcClienteEditandoId = null;
        showSuccess(editandoId ? "Datos del cliente actualizados" : "Cliente creado");
        cerrarModalFc("modal-fc-cliente");
        await abrirAsignarMembresiaPara(cliente.id, `${cliente.nombre} ${cliente.apellidos || ""}`.trim(), _fcOnTerminar);
    } catch (e) { showError(e.message); }
}

/**
 * Abre solo el paso de "Asignar Membresia" para un cliente que ya
 * existe (se puede llamar de forma independiente, no solo
 * encadenado desde crear cliente nuevo).
 */
async function abrirAsignarMembresiaPara(clienteId, nombreCliente, onTerminar) {
    _fcInyectarModales();
    if (onTerminar !== undefined) _fcOnTerminar = onTerminar;
    _fcClienteActivo = { id: clienteId, nombre: nombreCliente };

    const config = await getConfiguracion();
    _fcMoneda = config.moneda;
    [_fcPlanesCache, _fcVendedoresCache] = await Promise.all([
        apiFetch("/membresias/"),
        apiFetch("/vendedores-membresia/"),
    ]);

    document.getElementById("fc-am-cliente-nombre").textContent = nombreCliente;
    document.getElementById("fc-am-plan").innerHTML = '<option value="">Seleccionar...</option>' +
        _fcPlanesCache.map((p) => `<option value="${p.id}">${p.nombre} — ${formatCurrency(p.precio, config.moneda)}${p.permite_invitado ? ` · invitado ${p.dias_invitado}d` : ""}</option>`).join("");
    const vendedorActual = getNombreUsuario();
    document.getElementById("fc-am-vendedor").innerHTML = _fcVendedoresCache
        .map((v) => `<option value="${v.id}"${v.nombre === vendedorActual ? " selected" : ""}>${escapeHTML(v.nombre)}</option>`).join("");
    document.getElementById("fc-am-monto-total").value = "";
    document.getElementById("fc-am-congelamiento").value = "";
    document.getElementById("fc-am-condicion").value = "";
    document.getElementById("fc-am-inicio").value = fechaLocalISO();
    document.getElementById("fc-am-fin").value = "";
    document.getElementById("fc-am-monto-ahora").value = "";
    document.getElementById("fc-am-metodo").value = "efectivo";
    document.getElementById("fc-am-saldo-row").style.display = "none";
    document.getElementById("fc-am-fecha-saldo-row").style.display = "none";

    document.getElementById("modal-fc-membresia").classList.add("active");
}

let _fcMoneda = "S/";

function _fcOnPlanChange() {
    const sel = document.getElementById("fc-am-plan");
    const plan = _fcPlanesCache.find((p) => String(p.id) === sel.value);
    if (!plan) return;

    document.getElementById("fc-am-monto-total").value = formatCurrency(plan.precio, _fcMoneda);
    document.getElementById("fc-am-congelamiento").value = plan.permite_congelamiento ? "Permite congelamiento" : "No permite congelamiento";

    const permiteFraccionado = !!(plan.fracciones_pago_deuda || plan.monto_inicial);
    document.getElementById("fc-am-condicion").value = permiteFraccionado
        ? `Se puede pagar en partes${plan.fracciones_pago_deuda ? " (hasta " + plan.fracciones_pago_deuda + " cuotas)" : ""}`
        : "Debe pagarse el monto completo";

    document.getElementById("fc-am-monto-ahora").value = permiteFraccionado && plan.monto_inicial ? plan.monto_inicial : plan.precio;
    document.getElementById("fc-am-monto-ahora").readOnly = !permiteFraccionado;

    _fcRecalcularFin();
    _fcRecalcularSaldo();
}

function _fcRecalcularFin() {
    const sel = document.getElementById("fc-am-plan");
    const plan = _fcPlanesCache.find((p) => String(p.id) === sel.value);
    const inicio = document.getElementById("fc-am-inicio").value;
    if (!plan || !inicio) return;
    const fecha = new Date(inicio + "T00:00:00");
    fecha.setDate(fecha.getDate() + (plan.duracion_dias || 0));
    document.getElementById("fc-am-fin").value = fechaLocalISO(fecha);
}

function _fcRecalcularSaldo() {
    const sel = document.getElementById("fc-am-plan");
    const plan = _fcPlanesCache.find((p) => String(p.id) === sel.value);
    if (!plan) return;
    const montoAhora = parseFloat(document.getElementById("fc-am-monto-ahora").value) || 0;
    const saldo = Math.max(plan.precio - montoAhora, 0);
    const filaSaldo = document.getElementById("fc-am-saldo-row");
    const filaFecha = document.getElementById("fc-am-fecha-saldo-row");
    if (saldo > 0.009) {
        filaSaldo.style.display = "flex";
        filaFecha.style.display = "flex";
        document.getElementById("fc-am-saldo").value = formatCurrency(saldo, _fcMoneda);
    } else {
        filaSaldo.style.display = "none";
        filaFecha.style.display = "none";
    }
}

async function _fcAsignarMembresia() {
    const planId = parseInt(document.getElementById("fc-am-plan").value);
    if (!planId) { showError("Selecciona un plan"); return; }
    const montoAhora = parseFloat(document.getElementById("fc-am-monto-ahora").value);
    if (isNaN(montoAhora) || montoAhora < 0) { showError("Ingresa el monto a pagar ahora"); return; }

    const fechaSaldoRow = document.getElementById("fc-am-fecha-saldo-row");
    const fechaSaldo = fechaSaldoRow.style.display !== "none" ? document.getElementById("fc-am-fecha-saldo").value || null : null;

    try {
        const cm = await apiFetch(`/clientes/${_fcClienteActivo.id}/membresias`, {
            method: "POST",
            body: JSON.stringify({
                cliente_id: _fcClienteActivo.id,
                membresia_id: planId,
                fecha_inicio: document.getElementById("fc-am-inicio").value || null,
                fecha_fin: document.getElementById("fc-am-fin").value || null,
                monto_pagado: montoAhora,
                metodo_pago: document.getElementById("fc-am-metodo").value,
                fecha_pago_saldo: fechaSaldo,
                vendido_por_id: parseInt(document.getElementById("fc-am-vendedor").value),
            }),
        });
        _fcUltimoCm = cm;
        const planAsignado = _fcPlanesCache.find((plan) => plan.id === planId);
        if (planAsignado && Number(planAsignado.duracion_dias || 0) >= 30) {
            _fcAbrirPortalWhatsAppAutomatico();
        }
        showSuccess("Membresia asignada");
        cerrarModalFc("modal-fc-membresia");
        _fcAbrirCobro();
    } catch (e) { showError(e.message); }
}

async function _fcAbrirPortalWhatsAppAutomatico() {
    if (!_fcClienteActivo || !_fcClienteActivo.telefono) return;
    let slug = sessionStorage.getItem("gimnasio_slug") || "";
    if (!slug) {
        try {
            const gimnasio = await apiFetch("/gym-actual/");
            slug = gimnasio && gimnasio.slug ? gimnasio.slug : "";
            if (slug) sessionStorage.setItem("gimnasio_slug", slug);
        } catch (_) { return; }
    }
    if (!slug) return;
    const portal = `${window.location.origin}/alumno/login.html?gym=${encodeURIComponent(slug)}`;
    const mensaje = `Hola ${_fcClienteActivo.nombre || ""}, este es tu acceso al portal de alumnos:\n\n${portal}\n\nIngresa con tu DNI. En tu primer acceso crearás tu contraseña.`;
    const enlace = linkWhatsApp(_fcClienteActivo.telefono, mensaje);
    if (enlace) window.open(enlace, "_blank", "noopener,noreferrer");
}

function _fcAbrirCobro() {
    const plan = _fcPlanesCache.find((p) => p.id === _fcUltimoCm.membresia_id);
    const saldo = Math.max((plan ? plan.precio : 0) - (_fcUltimoCm.monto_pagado || 0), 0);
    const metodoPago = { efectivo: "Efectivo", tarjeta: "Tarjeta", qr: "Yape / Plin / QR" }[_fcUltimoCm.metodo_pago] || "Efectivo";
    document.getElementById("fc-cobro-resumen").innerHTML = `
        <p style="margin:0 0 6px;"><strong>Cliente:</strong> ${_fcClienteActivo.nombre}</p>
        <p style="margin:0 0 6px;"><strong>Plan:</strong> ${plan ? plan.nombre : "—"}</p>
        <p style="margin:0 0 6px;"><strong>Pagado ahora:</strong> ${formatCurrency(_fcUltimoCm.monto_pagado, _fcMoneda)}</p>
        <p style="margin:0 0 6px;"><strong>Forma de pago:</strong> ${metodoPago}</p>
        ${saldo > 0.009 ? `<p style="margin:0;color:var(--color-error);"><strong>Saldo pendiente:</strong> ${formatCurrency(saldo, _fcMoneda)}${_fcUltimoCm.fecha_pago_saldo ? " · a cobrar el " + formatFecha(_fcUltimoCm.fecha_pago_saldo) : ""}</p>` : ""}
    `;
    document.getElementById("modal-fc-cobro").classList.add("active");
}

async function _fcDescargarRecibo() {
    try { await apiDescargarArchivo(`/clientes/${_fcClienteActivo.id}/membresias/${_fcUltimoCm.id}/recibo.pdf`, `recibo_${_fcClienteActivo.id}.pdf`); }
    catch (e) { showError(e.message); }
}

async function _fcDescargarContrato() {
    try { await apiDescargarArchivo(`/clientes/${_fcClienteActivo.id}/membresias/${_fcUltimoCm.id}/contrato.pdf`, `contrato_${_fcClienteActivo.id}.pdf`); }
    catch (e) { showError(e.message); }
}

async function _fcEnviarWhatsApp() {
    try {
        const cliente = await apiFetch(`/clientes/${_fcClienteActivo.id}`);
        await _fcDescargarContrato();
        if (cliente.telefono) {
            const mensaje = `Hola ${cliente.nombre}! Te comparto tu contrato de matricula adjunto (revisa tu carpeta de Descargas).`;
            const url = linkWhatsApp(cliente.telefono, mensaje);
            if (url) window.open(url, "_blank");
        } else {
            showInfo("Este cliente no tiene telefono registrado; no se pudo abrir WhatsApp.");
        }
    } catch (e) { showError(e.message); }
}

function _fcCerrarCobro() {
    cerrarModalFc("modal-fc-cobro");
    const cliente = _fcClienteCreado || _fcClienteActivo;
    _fcClienteCreado = null;
    if (typeof _fcOnTerminar === "function") _fcOnTerminar(cliente);
}
