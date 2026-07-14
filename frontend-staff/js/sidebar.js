/* ==================================================================
   sidebar.js - frontend-staff
   Genera e inyecta el sidebar de navegacion en cada pagina.
   ================================================================== */

const NAV_ITEMS = [
    {
        seccion: "Principal",
        items: [
            { href: "principal.html", icono: "📊", texto: "Panel de Control", zona: null },
            { href: "clientes.html", icono: "👥", texto: "Clientes", zona: "clientes" },
            { href: "pagos.html",     icono: "💳", texto: "Pagos",    zona: "pagos" },
            { href: "asistencias.html", icono: "✅", texto: "Asistencias", zona: "asistencias" },
            { href: "movimientos.html", icono: "🔁", texto: "Movimientos", zona: null },
        ],
    },
    {
        seccion: "Gestion",
        items: [
            { href: "gestion-medidas.html", icono: "📏", texto: "Medidas", zona: "medidas" },
            { href: "membresias.html", icono: "🎫", texto: "Membresias", zona: "membresias" },
            { href: "productos.html", icono: "📦", texto: "Productos", zona: "productos" },
            { href: "ventas.html", icono: "💰", texto: "Ventas", zona: "ventas" },
            { href: "venta-rapida.html", icono: "⚡", texto: "Venta Rapida", zona: "venta_rapida" },
        ],
    },
    {
        seccion: "Seguimiento",
        items: [
            { href: "agenda.html", icono: "📅", texto: "Agenda", zona: "agenda" },
            { href: "entrenamientos.html", icono: "💪", texto: "Rutinas", zona: "entrenamientos" },
            { href: "nutricion.html", icono: "🥗", texto: "Nutricion", zona: "nutricion" },
            { href: "retos.html", icono: "🏆", texto: "Retos", zona: "retos" },
        ],
    },
    {
        seccion: "Personal",
        items: [
            { href: "planilla-staff.html", icono: "🧾", texto: "Planilla Staff", zona: "planilla" },
            { href: "planilla-profesores.html", icono: "🏫", texto: "Planilla Profesores", zona: "planilla" },
            { href: "usuarios-staff.html", icono: "🔑", texto: "Usuarios Staff", zona: "usuarios", soloAdmin: true },
            { href: "usuarios-profesores.html", icono: "🎓", texto: "Usuarios Profesores", zona: "usuarios", soloAdmin: true },
        ],
    },
    {
        seccion: "Sistema",
        items: [
            { href: "resumen.html",   icono: "📈", texto: "Resumen", zona: null },
            { href: "ingresos.html",  icono: "💰", texto: "Ingresos", zona: null },
            { href: "egresos.html",   icono: "📤", texto: "Egresos",  zona: null },
            { href: "reportes.html", icono: "📊", texto: "Reportes", zona: null, soloExportar: true },
            { href: "metas.html", icono: "🎯", texto: "Metas y Comisiones", zona: "metas", soloAdmin: true },
            { href: "configuracion.html", icono: "⚙️", texto: "Configuracion", zona: "configuracion" },
            { href: "superadmin.html", icono: "🛡️", texto: "Super Admin", zona: null, soloSuperadmin: true },
        ],
    },
];

const PAGINAS_SOLO_STAFF = [
    "clientes.html", "membresias.html", "productos.html", "ventas.html",
    "venta-rapida.html", "planilla-staff.html", "planilla-profesores.html",
    "usuarios-staff.html", "usuarios-profesores.html", "pagos.html",
    "configuracion.html", "metas.html", "reportes.html",
];

function renderSidebar() {
    const contenedor = document.getElementById("sidebar-container");
    if (!contenedor) return;

    const paginaActual = window.location.pathname.split("/").pop() || "principal.html";
    const rol = getRol();
    const nombre = getNombreUsuario();
    const esAdmin = esAdministrador();
    const colapsado = localStorage.getItem("mrgym_sidebar_colapsado") === "1";

    // "Principal" queda siempre visible (no es acordeon); el resto
    // de secciones son acordeon: solo una puede estar abierta a la
    // vez. Se abre automaticamente la que contiene la pagina actual.
    const seccionesHtml = NAV_ITEMS.map((seccion, indice) => {
        const itemsVisibles = seccion.items.filter((item) => {
            if (rol === "profesor" && PAGINAS_SOLO_STAFF.includes(item.href)) return false;
            if (item.soloAdmin && !esAdmin) return false;
            if (item.soloSuperadmin && sessionStorage.getItem("mrgym_es_superadmin") !== "1") return false;
            if (item.soloExportar && !(typeof puedeExportar === "function" && puedeExportar())) return false;
            if (rol === "staff" && item.zona && !esAdmin && !tieneAccesoZona(item.zona)) return false;
            return true;
        });
        if (!itemsVisibles.length) return "";

        const esAcordeon = seccion.seccion !== "Principal";
        const contieneActiva = itemsVisibles.some((item) => item.href === paginaActual);
        const abierta = !esAcordeon || contieneActiva;

        const itemsHtml = itemsVisibles.map((item) => {
            const activa = item.href === paginaActual ? "active" : "";
            return '<a href="' + item.href + '" class="nav-item ' + activa + '">' +
                '<span class="nav-item-icon">' + item.icono + '</span>' +
                '<span class="nav-item-text">' + item.texto + '</span>' +
                '</a>';
        }).join("");

        const claseAbierta = abierta ? "abierta" : "";
        const claseAcordeon = esAcordeon ? "acordeon" : "";
        const onclickAttr = esAcordeon ? ' onclick="toggleSeccionSidebar(' + indice + ')"' : "";
        const chevron = esAcordeon ? '<span class="nav-section-chevron">›</span>' : "";

        return '<div class="nav-section ' + claseAcordeon + ' ' + claseAbierta + '" data-indice="' + indice + '">' +
            '<div class="nav-section-title"' + onclickAttr + '>' +
            '<span>' + seccion.seccion + '</span>' + chevron +
            '</div>' +
            '<div class="nav-section-body"><div class="nav-section-body-inner">' + itemsHtml + '</div></div>' +
            '</div>';
    }).join("");

    contenedor.innerHTML =
        '<aside class="sidebar' + (colapsado ? ' colapsado' : '') + '">' +
        '<div class="sidebar-header">' +
        '<div class="logo"><span class="logo-brand-icon">🏋️</span><span class="logo-text">Soft-Gym</span></div>' +
        '<button class="btn-toggle-sidebar" onclick="toggleSidebarColapsado()" title="' + (colapsado ? "Expandir menu" : "Minimizar menu") + '">◀</button>' +
        '<button class="btn-logout-movil" onclick="cerrarSesion()" title="Cerrar sesion">Salir</button>' +
        '</div>' +
        '<nav class="sidebar-nav">' + seccionesHtml + '</nav>' +
        '<div class="sidebar-footer">' +
        '<div class="usuario-actual">' +
        '<div class="usuario-avatar">' + getIniciales(nombre) + '</div>' +
        '<div class="usuario-info-mini">' +
        '<div class="usuario-nombre-mini">' + (nombre || "") + '</div>' +
        '<div class="usuario-rol-mini">' + (rol || "") + '</div>' +
        '</div></div>' +
        '<button class="btn-logout" onclick="cerrarSesion()" title="Cerrar sesion">🚪 <span class="btn-logout-text">Cerrar sesion</span></button>' +
        '</div></aside>';

    cargarMarcaSidebar();
}

async function cargarMarcaSidebar() {
    try {
        const [gimnasio, configuracion] = await Promise.all([
            apiFetch("/gym-actual/"),
            apiFetch("/configuracion/"),
        ]);
        const marca = document.querySelector("#sidebar-container .logo");
        const texto = document.querySelector("#sidebar-container .logo-text");
        const icono = document.querySelector("#sidebar-container .logo-brand-icon");
        const nombreMarca = String(configuracion.nombre_gimnasio ?? gimnasio.nombre ?? "").trim();
        if (texto) texto.textContent = nombreMarca;
        if (marca) marca.classList.toggle("sin-nombre", !nombreMarca);
        if (icono && gimnasio.logo_url) {
            icono.innerHTML = '<img src="' + API_BASE_URL + gimnasio.logo_url + '" alt="Logo">';
        }
    } catch (_) {
        // El menu sigue siendo operativo con la marca por defecto.
    }
}

function toggleSidebarColapsado() {
    const aside = document.querySelector("#sidebar-container .sidebar");
    if (!aside) return;
    const yaColapsado = aside.classList.toggle("colapsado");
    localStorage.setItem("mrgym_sidebar_colapsado", yaColapsado ? "1" : "0");
    const btn = aside.querySelector(".btn-toggle-sidebar");
    if (btn) btn.title = yaColapsado ? "Expandir menu" : "Minimizar menu";
}

function toggleSeccionSidebar(indice) {
    const secciones = document.querySelectorAll("#sidebar-container .nav-section.acordeon");
    secciones.forEach((el) => {
        const esEsta = el.dataset.indice === String(indice);
        if (esEsta) {
            el.classList.toggle("abierta");
        } else {
            el.classList.remove("abierta");
        }
    });
}

document.addEventListener("DOMContentLoaded", () => {
    requireAuth();
    renderSidebar();
});
