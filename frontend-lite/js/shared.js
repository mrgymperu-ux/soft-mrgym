// ========== CONFIGURACIÓN ==========
const STORAGE_KEYS = {
    clientes: 'gimnasio_clientes',
    membresias: 'gimnasio_membresias',
    productos: 'gimnasio_productos',
    ventas: 'gimnasio_ventas',
    progresos: 'gimnasio_progresos',
    retos: 'gimnasio_retos',
    planesNutricion: 'gimnasio_planes_nutricion',
    asistencias: 'gimnasio_asistencias',
    configuracion: 'gimnasio_configuracion'
};

let configuracion = {
    moneda: 'S/',
    nombreGimnasio: 'Mi Gimnasio',
    telefono: '',
    email: '',
    direccion: '',
    comisionTarjeta: 3.5,
    comisionQR: 2.0
};

// ========== UTILIDADES ==========
function getData(key) {
    const data = localStorage.getItem(key);
    return data ? JSON.parse(data) : [];
}

function saveData(key, data) {
    localStorage.setItem(key, JSON.stringify(data));
}

function generateId() {
    return Date.now() + Math.random();
}

function formatCurrency(amount) {
    return `${configuracion.moneda} ${amount.toFixed(2)}`;
}

function showAlert(message, type = 'info') {
    const div = document.createElement('div');
    div.className = `alert alert-${type}`;
    div.textContent = message;
    const main = document.querySelector('.main-content') || document.getElementById('app');
    if (main) {
        main.prepend(div);
        setTimeout(() => div.remove(), 5000);
    }
}

function showSuccess(message) { showAlert(message, 'success'); }
function showError(message) { showAlert(message, 'error'); }
function showInfo(message) { showAlert(message, 'info'); }

function getInitiales(nombre) {
    return nombre.split(' ').map(n => n[0]).join('').substring(0, 2).toUpperCase();
}

function cargarConfiguracionGlobal() {
    const configGuardada = localStorage.getItem(STORAGE_KEYS.configuracion);
    if (configGuardada) {
        configuracion = { ...configuracion, ...JSON.parse(configGuardada) };
    }
}

// ========== INICIALIZACIÓN DE DATOS DE EJEMPLO ==========
function initSampleDataIfEmpty() {
    if (getData(STORAGE_KEYS.clientes).length > 0) return;

    const clientes = [
        { id: generateId(), nombre: "Juan Pérez", dni: "12345678", telefono: "987654321", email: "juan@email.com", fecha_nacimiento: "1990-05-15", direccion: "Av. Principal 123", fecha_registro: new Date().toISOString(), activo: true },
        { id: generateId(), nombre: "María García", dni: "87654321", telefono: "912345678", email: "maria@email.com", fecha_nacimiento: "1995-08-20", direccion: "Jr. Las Flores 456", fecha_registro: new Date().toISOString(), activo: true },
        { id: generateId(), nombre: "Carlos López", dni: "45678912", telefono: "998877665", email: "carlos@email.com", fecha_nacimiento: "1988-03-10", direccion: "Av. Los Olivos 789", fecha_registro: new Date().toISOString(), activo: true },
        { id: generateId(), nombre: "Ana Martínez", dni: "78912345", telefono: "955443322", email: "ana@email.com", fecha_nacimiento: "1992-11-25", direccion: "Calle Sol 321", fecha_registro: new Date().toISOString(), activo: true },
        { id: generateId(), nombre: "Roberto Díaz", dni: "32165498", telefono: "933221100", email: "roberto@email.com", fecha_nacimiento: "1985-07-08", direccion: "Av. Primavera 654", fecha_registro: new Date().toISOString(), activo: true }
    ];
    saveData(STORAGE_KEYS.clientes, clientes);

    const membresias = [
        { id: generateId(), nombre: "Mensual Básica", descripcion: "Acceso ilimitado por 30 días", precio: 150.00, duracion_dias: 30, activo: true },
        { id: generateId(), nombre: "Trimestral", descripcion: "Acceso ilimitado por 3 meses", precio: 400.00, duracion_dias: 90, activo: true },
        { id: generateId(), nombre: "Anual Premium", descripcion: "Acceso ilimitado por 12 meses + descuentos", precio: 1500.00, duracion_dias: 365, activo: true },
        { id: generateId(), nombre: "Diaria", descripcion: "Acceso por un día", precio: 20.00, duracion_dias: 1, activo: true }
    ];
    saveData(STORAGE_KEYS.membresias, membresias);

    const productos = [
        { id: generateId(), nombre: "Proteína Whey 1kg", descripcion: "Proteína de suero de leche sabor chocolate", precio_compra: 80.00, precio_venta: 120.00, stock: 20, stock_minimo: 5, categoria: "Suplementos", activo: true, fecha_creacion: new Date().toISOString(), imagen: "🥛" },
        { id: generateId(), nombre: "Camiseta Deportiva", descripcion: "Camiseta dry-fit para entrenamiento", precio_compra: 25.00, precio_venta: 45.00, stock: 50, stock_minimo: 10, categoria: "Ropa", activo: true, fecha_creacion: new Date().toISOString(), imagen: "👕" },
        { id: generateId(), nombre: "Guantes de Gimnasio", descripcion: "Guantes con agarre antideslizante", precio_compra: 15.00, precio_venta: 30.00, stock: 30, stock_minimo: 8, categoria: "Accesorios", activo: true, fecha_creacion: new Date().toISOString(), imagen: "🧤" },
        { id: generateId(), nombre: "Shaker 600ml", descripcion: "Botella mezcladora para proteínas", precio_compra: 8.00, precio_venta: 15.00, stock: 40, stock_minimo: 10, categoria: "Accesorios", activo: true, fecha_creacion: new Date().toISOString(), imagen: "🥤" },
        { id: generateId(), nombre: "Creatina 300g", descripcion: "Monohidrato de creatina micronizada", precio_compra: 35.00, precio_venta: 55.00, stock: 15, stock_minimo: 5, categoria: "Suplementos", activo: true, fecha_creacion: new Date().toISOString(), imagen: "💊" }
    ];
    saveData(STORAGE_KEYS.productos, productos);

    // Asistencias de ejemplo (últimas 20 del día)
    const asistencias = [];
    const hoy = new Date();
    for (let i = 0; i < 20; i++) {
        const hora = new Date(hoy);
        hora.setHours(6 + Math.floor(i / 4), (i * 15) % 60, 0);
        asistencias.push({
            id: generateId(),
            cliente_id: clientes[i % clientes.length].id,
            fecha_hora_entrada: hora.toISOString(),
            fecha_hora_salida: i < 15 ? new Date(hora.getTime() + 90 * 60000).toISOString() : null
        });
    }
    saveData(STORAGE_KEYS.asistencias, asistencias);

    showInfo('Datos de ejemplo cargados correctamente');
}