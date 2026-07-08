/* ==================================================================
   tema.js - frontend-staff
   Paletas de colores + modo claro/oscuro para personalizar la
   apariencia del sistema. Tonos deliberadamente suaves/desaturados
   (nada de colores neon o muy saturados). El tema es una preferencia
   GLOBAL del gimnasio (se guarda en Configuracion, igual que el
   nombre del gimnasio o la moneda), asi que se ve igual para todo
   el staff.

   En modo oscuro, los fondos/tarjetas/bordes se tiñen con un 5% del
   color primario de la paleta elegida (en vez de un gris neutro
   plano), para que el oscuro se sienta parte de la paleta.

   Se aplica en 2 pasos para evitar parpadeos:
   1) Sincrono, apenas carga la pagina: pinta con lo ultimo conocido
      (cacheado en localStorage).
   2) Asincrono: si hay sesion activa, confirma contra /configuracion/
      (fuente de verdad) y actualiza el cache si cambio.
   ================================================================== */

const PALETAS_TEMA = {
    lavanda: { nombre: "Lavanda", primario: "#7566B8", primarioOscuro: "#5C4E9C", sidebar: "#211B33", sidebarHover: "#2C2544" },
    azul: { nombre: "Azul acero", primario: "#4E7096", primarioOscuro: "#3C5878", sidebar: "#182430", sidebarHover: "#21303E" },
    salvia: { nombre: "Verde salvia", primario: "#5F7F63", primarioOscuro: "#4A6750", sidebar: "#1B241D", sidebarHover: "#253128" },
    terracota: { nombre: "Terracota", primario: "#AD7645", primarioOscuro: "#8C5D33", sidebar: "#2A2013", sidebarHover: "#382B1C" },
    rosa: { nombre: "Rosa empolvado", primario: "#AD6E7C", primarioOscuro: "#8C5462", sidebar: "#291B1F", sidebarHover: "#37262B" },
    vino: { nombre: "Vino", primario: "#7C4155", primarioOscuro: "#623242", sidebar: "#201014", sidebarHover: "#2C171D" },
    grafito: { nombre: "Grafito", primario: "#6E7378", primarioOscuro: "#565A5E", sidebar: "#1B1D1F", sidebarHover: "#26282B" },
};

// Bases NEUTRAS (sin teñir) de cada modo. En oscuro, estas bases se
// mezclan con un 5% del color primario de la paleta activa (ver
// mezclarColor/computarColoresModo) antes de aplicarse.
const BASE_CLARO = { fondo: "#F5F6FA", texto: "#2D3436", textoSecundario: "#636E72", borde: "#E5E7EB", blanco: "#FFFFFF", input: "#FFFFFF", hoverFila: "#FAFAFC" };
const BASE_OSCURO = { fondo: "#17181C", texto: "#EDEEF0", textoSecundario: "#A0A6AD", borde: "#4A4D57", blanco: "#26282F", input: "#33353E", hoverFila: "#2E3038" };

const TEMA_POR_DEFECTO = "lavanda";
const MODO_POR_DEFECTO = "claro";
const TEMA_STORAGE_KEY = "mrgym_tema";
const MODO_STORAGE_KEY = "mrgym_modo";
const TINTE_OSCURO = 0.05; // 5% del color primario mezclado en las superficies oscuras

function _hexARgb(hex) {
    const limpio = hex.replace("#", "");
    return [0, 2, 4].map(i => parseInt(limpio.substr(i, 2), 16));
}

function _rgbAHex(rgb) {
    return "#" + rgb.map(v => Math.max(0, Math.min(255, Math.round(v))).toString(16).padStart(2, "0")).join("");
}

function mezclarColor(hexBase, hexTinte, porcentaje) {
    const base = _hexARgb(hexBase);
    const tinte = _hexARgb(hexTinte);
    return _rgbAHex(base.map((b, i) => b * (1 - porcentaje) + tinte[i] * porcentaje));
}

function aplicarTema(nombreClave) {
    localStorage.setItem(TEMA_STORAGE_KEY, nombreClave);
    _aplicarTodo(nombreClave, localStorage.getItem(MODO_STORAGE_KEY) || MODO_POR_DEFECTO);
}

function aplicarModo(nombreModo) {
    localStorage.setItem(MODO_STORAGE_KEY, nombreModo);
    _aplicarTodo(localStorage.getItem(TEMA_STORAGE_KEY) || TEMA_POR_DEFECTO, nombreModo);
}

function _aplicarTodo(nombreTema, nombreModo) {
    const paleta = PALETAS_TEMA[nombreTema] || PALETAS_TEMA[TEMA_POR_DEFECTO];
    const raiz = document.documentElement.style;

    raiz.setProperty("--color-primario", paleta.primario);
    raiz.setProperty("--color-primario-oscuro", paleta.primarioOscuro);
    raiz.setProperty("--color-sidebar", paleta.sidebar);
    raiz.setProperty("--color-sidebar-hover", paleta.sidebarHover);

    const esOscuro = nombreModo === "oscuro";
    const base = esOscuro ? BASE_OSCURO : BASE_CLARO;
    const tintar = (hex) => (esOscuro ? mezclarColor(hex, paleta.primario, TINTE_OSCURO) : hex);

    // Tinte suave del primario para fondos de seleccion (ej. badge de
    // cliente en venta rapida): contrasta bien en claro y en oscuro.
    raiz.setProperty("--color-primario-tinte", mezclarColor(
        esOscuro ? tintar(base.blanco) : base.blanco,
        paleta.primario,
        esOscuro ? 0.20 : 0.10
    ));
    raiz.setProperty("--color-primario-tinte-texto", esOscuro ? base.texto : paleta.primarioOscuro);

    raiz.setProperty("--color-fondo", tintar(base.fondo));
    raiz.setProperty("--color-blanco", tintar(base.blanco));
    raiz.setProperty("--color-input", tintar(base.input));
    raiz.setProperty("--color-borde", tintar(base.borde));
    raiz.setProperty("--color-hover-fila", tintar(base.hoverFila));
    // El texto se deja neutro (sin tinte) para no perder contraste/legibilidad.
    raiz.setProperty("--color-texto", base.texto);
    raiz.setProperty("--color-texto-secundario", base.textoSecundario);

    document.documentElement.setAttribute("data-modo", nombreModo);
    document.documentElement.style.colorScheme = esOscuro ? "dark" : "light";
}

// Paso 1: pintar de inmediato con lo ultimo guardado localmente
// (este script se carga en <head>, antes de que se pinte el body).
_aplicarTodo(
    localStorage.getItem(TEMA_STORAGE_KEY) || TEMA_POR_DEFECTO,
    localStorage.getItem(MODO_STORAGE_KEY) || MODO_POR_DEFECTO
);

// Paso 2: confirmar contra el backend en cuanto haya sesion activa.
// Se usa fetch crudo (no apiFetch) porque api.js puede no estar
// cargado todavia en este punto.
(function sincronizarTemaConBackend() {
    const token = sessionStorage.getItem("mrgym_token");
    if (!token) return;
    fetch("http://localhost:8000/configuracion/", { headers: { "Authorization": `Bearer ${token}` } })
        .then(res => (res.ok ? res.json() : null))
        .then(config => {
            if (!config) return;
            const temaCambio = config.tema && config.tema !== localStorage.getItem(TEMA_STORAGE_KEY);
            const modoCambio = config.modo_tema && config.modo_tema !== localStorage.getItem(MODO_STORAGE_KEY);
            if (temaCambio) localStorage.setItem(TEMA_STORAGE_KEY, config.tema);
            if (modoCambio) localStorage.setItem(MODO_STORAGE_KEY, config.modo_tema);
            if (temaCambio || modoCambio) {
                _aplicarTodo(
                    localStorage.getItem(TEMA_STORAGE_KEY) || TEMA_POR_DEFECTO,
                    localStorage.getItem(MODO_STORAGE_KEY) || MODO_POR_DEFECTO
                );
            }
        })
        .catch(() => {/* silencioso: si falla, se queda con el tema en cache */});
})();
