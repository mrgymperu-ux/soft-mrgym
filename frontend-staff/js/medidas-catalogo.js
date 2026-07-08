/* ==================================================================
   medidas-catalogo.js - frontend-staff
   Catalogo unico de:
     1) CAMPOS_MEDIDAS   -> los ~33 datos crudos que el trainer puede
        tomar (checklist "que aparece en la tabla de Medidas").
     2) VALORES_CALCULADOS -> los ~28 valores importantes que se
        pueden mostrar, cada uno con la lista de CAMPOS_MEDIDAS que
        necesita para calcularse (checklist "que valores calculados
        quiero mostrar" -> al marcar uno, se marcan solas sus
        medidas obligatorias).
     3) Funciones de calculo (formulas estandar, documentadas).

   Se usa en:
     - gestion-medidas.html (checklist de configuracion)
     - clientes.html, tab Medidas (formulario + tabla + calculados)

   Todo en un solo archivo para que ambas pantallas usen EXACTAMENTE
   el mismo catalogo y las mismas formulas.
   ================================================================== */

const CAMPOS_MEDIDAS = [
    // Nota: Sexo y Fecha de nacimiento NO estan aqui: se toman
    // automaticamente del perfil del Cliente (Cliente.genero /
    // Cliente.fecha_nacimiento) y se inyectan al calcular, en vez de
    // pedirse de nuevo en cada toma.
    { clave: "estatura_cm", etiqueta: "Estatura", unidad: "cm", grupo: "Datos base", tipo: "num" },
    { clave: "peso_kg", etiqueta: "Peso", unidad: "kg", grupo: "Datos base", tipo: "num" },

    { clave: "cuello_cm", etiqueta: "Cuello", unidad: "cm", grupo: "Perimetros", tipo: "num" },
    { clave: "hombros_cm", etiqueta: "Hombros", unidad: "cm", grupo: "Perimetros", tipo: "num" },
    { clave: "pecho_cm", etiqueta: "Pecho", unidad: "cm", grupo: "Perimetros", tipo: "num" },
    { clave: "brazo_derecho_relajado_cm", etiqueta: "Brazo derecho relajado", unidad: "cm", grupo: "Perimetros", tipo: "num" },
    { clave: "brazo_izquierdo_relajado_cm", etiqueta: "Brazo izquierdo relajado", unidad: "cm", grupo: "Perimetros", tipo: "num" },
    { clave: "brazo_derecho_contraido_cm", etiqueta: "Brazo derecho contraído", unidad: "cm", grupo: "Perimetros", tipo: "num" },
    { clave: "brazo_izquierdo_contraido_cm", etiqueta: "Brazo izquierdo contraído", unidad: "cm", grupo: "Perimetros", tipo: "num" },
    { clave: "antebrazo_derecho_cm", etiqueta: "Antebrazo derecho", unidad: "cm", grupo: "Perimetros", tipo: "num" },
    { clave: "antebrazo_izquierdo_cm", etiqueta: "Antebrazo izquierdo", unidad: "cm", grupo: "Perimetros", tipo: "num" },
    { clave: "cintura_cm", etiqueta: "Cintura", unidad: "cm", grupo: "Perimetros", tipo: "num" },
    { clave: "abdomen_cm", etiqueta: "Abdomen", unidad: "cm", grupo: "Perimetros", tipo: "num" },
    { clave: "cadera_cm", etiqueta: "Cadera", unidad: "cm", grupo: "Perimetros", tipo: "num" },
    { clave: "muslo_derecho_cm", etiqueta: "Muslo derecho", unidad: "cm", grupo: "Perimetros", tipo: "num" },
    { clave: "muslo_izquierdo_cm", etiqueta: "Muslo izquierdo", unidad: "cm", grupo: "Perimetros", tipo: "num" },
    { clave: "pantorrilla_derecha_cm", etiqueta: "Pantorrilla derecha", unidad: "cm", grupo: "Perimetros", tipo: "num" },
    { clave: "pantorrilla_izquierda_cm", etiqueta: "Pantorrilla izquierda", unidad: "cm", grupo: "Perimetros", tipo: "num" },
    { clave: "muneca_derecha_cm", etiqueta: "Muñeca derecha", unidad: "cm", grupo: "Perimetros", tipo: "num" },
    { clave: "muneca_izquierda_cm", etiqueta: "Muñeca izquierda", unidad: "cm", grupo: "Perimetros", tipo: "num" },
    { clave: "tobillo_derecho_cm", etiqueta: "Tobillo derecho", unidad: "cm", grupo: "Perimetros", tipo: "num" },
    { clave: "tobillo_izquierdo_cm", etiqueta: "Tobillo izquierdo", unidad: "cm", grupo: "Perimetros", tipo: "num" },

    { clave: "presion_arterial", etiqueta: "Presión arterial", unidad: "mmHg", grupo: "Signos vitales / composicion", tipo: "texto" },
    { clave: "frecuencia_cardiaca_reposo", etiqueta: "Frecuencia cardíaca en reposo", unidad: "lpm", grupo: "Signos vitales / composicion", tipo: "num" },
    { clave: "saturacion_oxigeno", etiqueta: "Saturación de oxígeno", unidad: "%", grupo: "Signos vitales / composicion", tipo: "num" },
    { clave: "porcentaje_grasa_corporal", etiqueta: "Porcentaje de grasa corporal", unidad: "%", grupo: "Signos vitales / composicion", tipo: "num" },
    { clave: "masa_muscular_kg", etiqueta: "Masa muscular", unidad: "kg", grupo: "Signos vitales / composicion", tipo: "num" },
    { clave: "grasa_visceral_nivel", etiqueta: "Grasa visceral", unidad: "nivel", grupo: "Signos vitales / composicion", tipo: "num" },
    { clave: "agua_corporal_pct", etiqueta: "Agua corporal", unidad: "%", grupo: "Signos vitales / composicion", tipo: "num" },
    { clave: "masa_osea_kg", etiqueta: "Masa ósea", unidad: "kg", grupo: "Signos vitales / composicion", tipo: "num" },
    { clave: "edad_metabolica", etiqueta: "Edad metabólica", unidad: "años", grupo: "Signos vitales / composicion", tipo: "num" },
];

// Set por defecto si Configuracion.medidas_campos_visibles viene vacio:
// los datos base + los perimetros y signos vitales mas comunes.
const CAMPOS_MEDIDAS_DEFAULT = [
    "estatura_cm", "peso_kg",
    "cintura_cm", "cadera_cm", "cuello_cm", "pecho_cm",
    "brazo_derecho_relajado_cm", "muslo_derecho_cm",
    "porcentaje_grasa_corporal", "masa_muscular_kg",
];

// ------------------------------------------------------------------
// Valores calculados: cada uno declara "requiere" (claves de
// CAMPOS_MEDIDAS que son obligatorias para poder calcularlo) y
// opcionalmente "requiereHistorial" (necesita 2+ tomas) o
// "requiereExtra" (campos auxiliares del formulario que no son
// parte del checklist de medidas: objetivo, nivel de actividad,
// peso objetivo).
// ------------------------------------------------------------------
const VALORES_CALCULADOS = [
    { clave: "imc", etiqueta: "IMC", requiere: ["peso_kg", "estatura_cm"] },
    { clave: "peso_ideal", etiqueta: "Peso ideal", requiere: ["estatura_cm"] },
    { clave: "peso_objetivo", etiqueta: "Peso objetivo", requiere: [], requiereExtra: ["peso_objetivo_kg"] },
    { clave: "bmr", etiqueta: "Metabolismo basal (BMR)", requiere: ["peso_kg", "estatura_cm"] },
    { clave: "tdee", etiqueta: "Gasto energético diario (TDEE)", requiere: ["peso_kg", "estatura_cm"], requiereExtra: ["nivel_actividad"] },
    { clave: "grasa_estimada", etiqueta: "Porcentaje de grasa corporal (estimado, si no se mide)", requiere: ["cuello_cm", "cintura_cm", "estatura_cm"] },
    { clave: "masa_grasa", etiqueta: "Masa grasa", unidad: "kg", requiere: ["peso_kg"] },
    { clave: "masa_libre_grasa", etiqueta: "Masa libre de grasa", unidad: "kg", requiere: ["peso_kg"] },
    { clave: "indice_cintura_estatura", etiqueta: "Índice cintura-estatura", requiere: ["cintura_cm", "estatura_cm"] },
    { clave: "relacion_cintura_cadera", etiqueta: "Relación cintura-cadera", requiere: ["cintura_cm", "cadera_cm"] },
    { clave: "fc_maxima", etiqueta: "Frecuencia cardíaca máxima", unidad: "lpm", requiere: [] },
    { clave: "zonas_entrenamiento", etiqueta: "Zonas de entrenamiento (50–100%)", requiere: [] },
    { clave: "indice_complexion", etiqueta: "Índice de complexión corporal", requiere: ["estatura_cm", "muneca_derecha_cm"] },
    { clave: "variacion_peso", etiqueta: "Variación de peso", unidad: "%", requiere: ["peso_kg"], requiereHistorial: true },
    { clave: "variacion_grasa", etiqueta: "Variación de grasa corporal", unidad: "%", requiere: ["porcentaje_grasa_corporal"], requiereHistorial: true },
    { clave: "variacion_musculo", etiqueta: "Variación de masa muscular", unidad: "%", requiere: ["masa_muscular_kg"], requiereHistorial: true },
    { clave: "variacion_perimetros", etiqueta: "Variación de cada perímetro", unidad: "%", requiere: ["cintura_cm", "cadera_cm", "pecho_cm"], requiereHistorial: true },
    { clave: "simetria_brazos", etiqueta: "Simetría de brazos", unidad: "%", requiere: ["brazo_derecho_relajado_cm", "brazo_izquierdo_relajado_cm"] },
    { clave: "simetria_muslos", etiqueta: "Simetría de muslos", unidad: "%", requiere: ["muslo_derecho_cm", "muslo_izquierdo_cm"] },
    { clave: "simetria_pantorrillas", etiqueta: "Simetría de pantorrillas", unidad: "%", requiere: ["pantorrilla_derecha_cm", "pantorrilla_izquierda_cm"] },
    { clave: "riesgo_cardiovascular", etiqueta: "Riesgo cardiovascular", requiere: ["cintura_cm", "cadera_cm"] },
    { clave: "historial_evolucion", etiqueta: "Historial de evolución por fechas", requiere: ["peso_kg"], requiereHistorial: true },
    { clave: "progreso_meta", etiqueta: "Progreso total hacia la meta", unidad: "%", requiere: ["peso_kg"], requiereExtra: ["peso_objetivo_kg"], requiereHistorial: true },
    { clave: "tiempo_meta", etiqueta: "Tiempo estimado para alcanzar la meta", requiere: ["peso_kg"], requiereExtra: ["peso_objetivo_kg"], requiereHistorial: true },
    { clave: "recomendacion_calorias", etiqueta: "Recomendación de calorías (perder/mantener/ganar)", requiere: ["peso_kg", "estatura_cm"], requiereExtra: ["nivel_actividad", "objetivo_calorico"] },
    { clave: "recomendacion_proteinas", etiqueta: "Recomendación diaria de proteínas", unidad: "g", requiere: ["peso_kg"], requiereExtra: ["objetivo_calorico"] },
    { clave: "recomendacion_agua", etiqueta: "Recomendación diaria de agua", unidad: "L", requiere: ["peso_kg"] },
    { clave: "indice_progreso_general", etiqueta: "Índice de progreso físico general", unidad: "%", requiere: ["peso_kg", "porcentaje_grasa_corporal", "masa_muscular_kg"], requiereHistorial: true },
];

const VALORES_CALCULADOS_DEFAULT = ["imc", "peso_ideal", "bmr", "tdee", "indice_cintura_estatura", "relacion_cintura_cadera", "fc_maxima", "recomendacion_calorias", "recomendacion_agua"];

// ------------------------------------------------------------------
// Helpers
// ------------------------------------------------------------------
function calcularEdadDesde(fechaNacimientoStr, fechaReferencia) {
    if (!fechaNacimientoStr) return null;
    const nac = new Date(fechaNacimientoStr);
    const ref = fechaReferencia ? new Date(fechaReferencia) : new Date();
    let edad = ref.getFullYear() - nac.getFullYear();
    const m = ref.getMonth() - nac.getMonth();
    if (m < 0 || (m === 0 && ref.getDate() < nac.getDate())) edad--;
    return edad;
}

function _num(v) { return (v === null || v === undefined || v === "" || isNaN(v)) ? null : parseFloat(v); }

// Devuelve true si todos los "requiere" (y requireExtra) de un valor
// calculado tienen dato en `medida` (+ `extra`).
function tieneDatosSuficientes(valorDef, medida, extra) {
    extra = extra || {};
    for (const campo of (valorDef.requiere || [])) {
        if (medida[campo] === null || medida[campo] === undefined || medida[campo] === "") return false;
    }
    for (const campo of (valorDef.requiereExtra || [])) {
        if (extra[campo] === null || extra[campo] === undefined || extra[campo] === "") return false;
    }
    return true;
}

const FACTOR_ACTIVIDAD = { sedentario: 1.2, ligero: 1.375, moderado: 1.55, activo: 1.725, muy_activo: 1.9 };

/**
 * Calcula un valor especifico. `medida` es la toma mas reciente
 * (objeto plano con las claves de CAMPOS_MEDIDAS), `historial` es
 * el arreglo completo de tomas (ordenado de mas reciente a mas
 * antigua, incluye `medida` en la posicion 0), `extra` son los
 * campos auxiliares (peso_objetivo_kg, nivel_actividad, objetivo_calorico).
 * Devuelve { valor, texto } o null si faltan datos.
 */
function calcularValor(clave, medida, historial, extra) {
    extra = extra || {};
    historial = historial || [medida];
    const edad = calcularEdadDesde(medida.fecha_nacimiento, medida.fecha);
    const esHombre = (medida.sexo || "").toUpperCase().startsWith("M");

    const primera = historial[historial.length - 1];
    const anterior = historial.length > 1 ? historial[1] : null;

    switch (clave) {
        case "imc": {
            const p = _num(medida.peso_kg), e = _num(medida.estatura_cm);
            if (!p || !e) return null;
            const h = e / 100;
            const imc = p / (h * h);
            let cat = "Normal";
            if (imc < 18.5) cat = "Bajo peso"; else if (imc < 25) cat = "Normal"; else if (imc < 30) cat = "Sobrepeso"; else cat = "Obesidad";
            return { valor: imc, texto: `${imc.toFixed(1)} (${cat})` };
        }
        case "peso_ideal": {
            const e = _num(medida.estatura_cm);
            if (!e) return null;
            // Formula de Devine (kg), estatura en cm
            const alturaPulgadasSobre5pies = Math.max((e - 152.4) / 2.54, 0);
            const base = esHombre ? 50 : 45.5;
            const ideal = base + 2.3 * alturaPulgadasSobre5pies;
            return { valor: ideal, texto: `${ideal.toFixed(1)} kg` };
        }
        case "peso_objetivo": {
            const po = _num(extra.peso_objetivo_kg);
            if (!po) return null;
            return { valor: po, texto: `${po.toFixed(1)} kg` };
        }
        case "bmr": {
            const p = _num(medida.peso_kg), e = _num(medida.estatura_cm);
            if (!p || !e || edad === null) return null;
            // Mifflin-St Jeor
            const bmr = esHombre ? (10 * p + 6.25 * e - 5 * edad + 5) : (10 * p + 6.25 * e - 5 * edad - 161);
            return { valor: bmr, texto: `${Math.round(bmr)} kcal/día` };
        }
        case "tdee": {
            const bmrCalc = calcularValor("bmr", medida, historial, extra);
            if (!bmrCalc) return null;
            const factor = FACTOR_ACTIVIDAD[extra.nivel_actividad] || FACTOR_ACTIVIDAD.moderado;
            const tdee = bmrCalc.valor * factor;
            return { valor: tdee, texto: `${Math.round(tdee)} kcal/día` };
        }
        case "grasa_estimada": {
            // Metodo US Navy (cm)
            const cuello = _num(medida.cuello_cm), cintura = _num(medida.cintura_cm), e = _num(medida.estatura_cm);
            if (!cuello || !cintura || !e) return null;
            let pct;
            if (esHombre) {
                pct = 495 / (1.0324 - 0.19077 * Math.log10(cintura - cuello) + 0.15456 * Math.log10(e)) - 450;
            } else {
                const cadera = _num(medida.cadera_cm);
                if (!cadera) return null;
                pct = 495 / (1.29579 - 0.35004 * Math.log10(cintura + cadera - cuello) + 0.22100 * Math.log10(e)) - 450;
            }
            if (!isFinite(pct) || pct <= 0) return null;
            return { valor: pct, texto: `${pct.toFixed(1)} %` };
        }
        case "masa_grasa": {
            const p = _num(medida.peso_kg);
            const pctDirecto = _num(medida.porcentaje_grasa_corporal);
            const pct = pctDirecto !== null ? pctDirecto : (calcularValor("grasa_estimada", medida, historial, extra) || {}).valor;
            if (!p || pct === undefined || pct === null) return null;
            const masaGrasa = p * pct / 100;
            return { valor: masaGrasa, texto: `${masaGrasa.toFixed(1)} kg` };
        }
        case "masa_libre_grasa": {
            const p = _num(medida.peso_kg);
            const mg = calcularValor("masa_grasa", medida, historial, extra);
            if (!p || !mg) return null;
            const mlg = p - mg.valor;
            return { valor: mlg, texto: `${mlg.toFixed(1)} kg` };
        }
        case "indice_cintura_estatura": {
            const c = _num(medida.cintura_cm), e = _num(medida.estatura_cm);
            if (!c || !e) return null;
            const idx = c / e;
            const riesgo = idx < 0.5 ? "saludable" : (idx < 0.6 ? "riesgo moderado" : "riesgo alto");
            return { valor: idx, texto: `${idx.toFixed(2)} (${riesgo})` };
        }
        case "relacion_cintura_cadera": {
            const c = _num(medida.cintura_cm), cad = _num(medida.cadera_cm);
            if (!c || !cad) return null;
            const idx = c / cad;
            return { valor: idx, texto: idx.toFixed(2) };
        }
        case "fc_maxima": {
            if (edad === null) return null;
            const fcm = 220 - edad;
            return { valor: fcm, texto: `${fcm} lpm` };
        }
        case "zonas_entrenamiento": {
            const fcmCalc = calcularValor("fc_maxima", medida, historial, extra);
            if (!fcmCalc) return null;
            const fcm = fcmCalc.valor;
            const z = (a, b) => `${Math.round(fcm * a)}–${Math.round(fcm * b)} lpm`;
            return {
                valor: fcm,
                texto: `50-60%: ${z(0.5,0.6)} · 60-70%: ${z(0.6,0.7)} · 70-80%: ${z(0.7,0.8)} · 80-90%: ${z(0.8,0.9)} · 90-100%: ${z(0.9,1.0)}`,
            };
        }
        case "indice_complexion": {
            const e = _num(medida.estatura_cm), m = _num(medida.muneca_derecha_cm);
            if (!e || !m) return null;
            const idx = e / m;
            let cat;
            if (esHombre) cat = idx > 10.4 ? "Pequeña" : (idx >= 9.6 ? "Mediana" : "Grande");
            else cat = idx > 11.0 ? "Pequeña" : (idx >= 10.1 ? "Mediana" : "Grande");
            return { valor: idx, texto: `${idx.toFixed(1)} (${cat})` };
        }
        case "variacion_peso":
            return _variacionPct(medida.peso_kg, primera.peso_kg, anterior && anterior.peso_kg);
        case "variacion_grasa":
            return _variacionPct(medida.porcentaje_grasa_corporal, primera.porcentaje_grasa_corporal, anterior && anterior.porcentaje_grasa_corporal);
        case "variacion_musculo":
            return _variacionPct(medida.masa_muscular_kg, primera.masa_muscular_kg, anterior && anterior.masa_muscular_kg);
        case "variacion_perimetros": {
            const partes = [];
            [["cintura_cm","Cintura"],["cadera_cm","Cadera"],["pecho_cm","Pecho"]].forEach(([k,lbl]) => {
                const r = _variacionPct(medida[k], primera[k], anterior && anterior[k]);
                if (r) partes.push(`${lbl}: ${r.texto}`);
            });
            if (!partes.length) return null;
            return { valor: null, texto: partes.join(" · ") };
        }
        case "simetria_brazos":
            return _simetria(medida.brazo_derecho_relajado_cm, medida.brazo_izquierdo_relajado_cm);
        case "simetria_muslos":
            return _simetria(medida.muslo_derecho_cm, medida.muslo_izquierdo_cm);
        case "simetria_pantorrillas":
            return _simetria(medida.pantorrilla_derecha_cm, medida.pantorrilla_izquierda_cm);
        case "riesgo_cardiovascular": {
            const rcc = calcularValor("relacion_cintura_cadera", medida, historial, extra);
            if (!rcc) return null;
            const limite = esHombre ? 0.95 : 0.85;
            const nivel = rcc.valor < limite * 0.9 ? "Bajo" : (rcc.valor < limite ? "Moderado" : "Alto");
            return { valor: rcc.valor, texto: nivel };
        }
        case "historial_evolucion": {
            if (historial.length < 2) return null;
            return { valor: historial.length, texto: `${historial.length} tomas registradas (ver gráfico)` };
        }
        case "progreso_meta": {
            const objetivo = _num(extra.peso_objetivo_kg);
            const pInicial = _num(primera.peso_kg), pActual = _num(medida.peso_kg);
            if (!objetivo || !pInicial || !pActual || pInicial === objetivo) return null;
            const avance = (pInicial - pActual) / (pInicial - objetivo) * 100;
            return { valor: avance, texto: `${Math.max(0, Math.min(100, avance)).toFixed(0)} %` };
        }
        case "tiempo_meta": {
            const objetivo = _num(extra.peso_objetivo_kg);
            const pActual = _num(medida.peso_kg);
            if (!objetivo || !pActual || historial.length < 2) return null;
            const diasTranscurridos = (new Date(medida.fecha) - new Date(primera.fecha)) / (1000*3600*24);
            const cambioTotal = primera.peso_kg - pActual;
            if (diasTranscurridos <= 0 || cambioTotal === 0) return null;
            const ritmoDiario = cambioTotal / diasTranscurridos; // kg/dia
            const faltante = pActual - objetivo;
            if (ritmoDiario === 0 || (faltante > 0) !== (ritmoDiario > 0)) return { valor: null, texto: "Sin tendencia hacia la meta aún" };
            const diasRestantes = Math.abs(faltante / ritmoDiario);
            const semanas = Math.round(diasRestantes / 7);
            return { valor: diasRestantes, texto: `≈ ${semanas} semanas al ritmo actual` };
        }
        case "recomendacion_calorias": {
            const tdeeCalc = calcularValor("tdee", medida, historial, extra);
            if (!tdeeCalc) return null;
            const obj = extra.objetivo_calorico || "mantener";
            let cal = tdeeCalc.valor;
            if (obj === "perder") cal -= 500; else if (obj === "ganar") cal += 300;
            return { valor: cal, texto: `${Math.round(cal)} kcal/día (${obj})` };
        }
        case "recomendacion_proteinas": {
            const p = _num(medida.peso_kg);
            if (!p) return null;
            const obj = extra.objetivo_calorico || "mantener";
            const gPorKg = obj === "ganar" ? 2.0 : (obj === "perder" ? 2.2 : 1.6);
            const total = p * gPorKg;
            return { valor: total, texto: `${Math.round(total)} g/día` };
        }
        case "recomendacion_agua": {
            const p = _num(medida.peso_kg);
            if (!p) return null;
            const litros = p * 0.035;
            return { valor: litros, texto: `${litros.toFixed(1)} L/día` };
        }
        case "indice_progreso_general": {
            if (historial.length < 2) return null;
            const vp = _variacionPct(medida.peso_kg, primera.peso_kg);
            const vg = _variacionPct(medida.porcentaje_grasa_corporal, primera.porcentaje_grasa_corporal);
            const vm = _variacionPct(medida.masa_muscular_kg, primera.masa_muscular_kg);
            const partes = [vg ? -vg.valor : null, vm ? vm.valor : null].filter(v => v !== null);
            if (!partes.length) return null;
            const promedio = partes.reduce((a,b)=>a+b,0) / partes.length;
            const idx = Math.max(0, Math.min(100, 50 + promedio * 5));
            return { valor: idx, texto: `${idx.toFixed(0)} / 100` };
        }
        default:
            return null;
    }
}

function _variacionPct(actual, inicial, anteriorOpt) {
    actual = _num(actual); inicial = _num(inicial);
    if (actual === null || inicial === null || inicial === 0) return null;
    const pct = (actual - inicial) / inicial * 100;
    let extra = "";
    if (anteriorOpt !== undefined && anteriorOpt !== null) {
        const anteriorN = _num(anteriorOpt);
        if (anteriorN !== null && anteriorN !== 0) {
            const pctReciente = (actual - anteriorN) / anteriorN * 100;
            extra = ` (${pctReciente >= 0 ? "+" : ""}${pctReciente.toFixed(1)}% desde la toma anterior)`;
        }
    }
    return { valor: pct, texto: `${pct >= 0 ? "+" : ""}${pct.toFixed(1)}%${extra}` };
}

function _simetria(der, izq) {
    der = _num(der); izq = _num(izq);
    if (der === null || izq === null || (der === 0 && izq === 0)) return null;
    const mayor = Math.max(der, izq), menor = Math.min(der, izq);
    if (mayor === 0) return null;
    const pct = (menor / mayor) * 100;
    const lado = der > izq ? "derecho" : (izq > der ? "izquierdo" : "parejo");
    return { valor: pct, texto: `${pct.toFixed(1)}% ${pct >= 98 ? "(simétrico)" : `(predomina lado ${lado})`}` };
}
