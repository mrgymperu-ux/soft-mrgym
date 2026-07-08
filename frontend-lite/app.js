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

// ========== ESTADO GLOBAL ==========
let configuracion = {
    moneda: 'S/',
    nombreGimnasio: 'Mi Gimnasio',
    telefono: '',
    email: '',
    direccion: '',
    comisionTarjeta: 3.5,
    comisionQR: 2.0
};

let clienteActual = null;

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
    document.querySelector('.main-content').prepend(div);
    setTimeout(() => div.remove(), 5000);
}

function showSuccess(message) {
    showAlert(message, 'success');
}

function showError(message) {
    showAlert(message, 'error');
}

function showInfo(message) {
    showAlert(message, 'info');
}

// ========== CONFIGURACIÓN ==========
function cargarConfiguracion() {
    const configGuardada = localStorage.getItem(STORAGE_KEYS.configuracion);
    if (configGuardada) {
        configuracion = { ...configuracion, ...JSON.parse(configGuardada) };
    }
    
    document.getElementById('config-moneda').value = configuracion.moneda;
    document.getElementById('config-nombre-gimnasio').value = configuracion.nombreGimnasio;
    document.getElementById('config-telefono').value = configuracion.telefono;
    document.getElementById('config-email').value = configuracion.email;
    document.getElementById('config-direccion').value = configuracion.direccion;
    document.getElementById('config-comision-tarjeta').value = configuracion.comisionTarjeta;
    document.getElementById('config-comision-qr').value = configuracion.comisionQR;
    
    actualizarMonedaEnUI();
}

function guardarConfiguracion() {
    configuracion = {
        moneda: document.getElementById('config-moneda').value,
        nombreGimnasio: document.getElementById('config-nombre-gimnasio').value,
        telefono: document.getElementById('config-telefono').value,
        email: document.getElementById('config-email').value,
        direccion: document.getElementById('config-direccion').value,
        comisionTarjeta: parseFloat(document.getElementById('config-comision-tarjeta').value) || 0,
        comisionQR: parseFloat(document.getElementById('config-comision-qr').value) || 0
    };
    
    saveData(STORAGE_KEYS.configuracion, configuracion);
    actualizarMonedaEnUI();
    showSuccess('Configuración guardada correctamente');
}

function actualizarMonedaEnUI() {
    document.getElementById('moneda-simbolo').textContent = configuracion.moneda;
}

function openConfiguracionRapida() {
    showSection('configuracion', document.querySelectorAll('.nav-item')[5]);
}

// ========== EXPORTAR/IMPORTAR ==========
function exportarDatos() {
    const datos = {
        clientes: getData(STORAGE_KEYS.clientes),
        membresias: getData(STORAGE_KEYS.membresias),
        productos: getData(STORAGE_KEYS.productos),
        ventas: getData(STORAGE_KEYS.ventas),
        progresos: getData(STORAGE_KEYS.progresos),
        retos: getData(STORAGE_KEYS.retos),
        planesNutricion: getData(STORAGE_KEYS.planesNutricion),
        asistencias: getData(STORAGE_KEYS.asistencias),
        configuracion: configuracion,
        fechaExportacion: new Date().toISOString()
    };
    
    const blob = new Blob([JSON.stringify(datos, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `backup-gimnasio-${new Date().toISOString().split('T')[0]}.json`;
    a.click();
    URL.revokeObjectURL(url);
    
    showSuccess('Datos exportados correctamente');
}

function importarDatos(event) {
    const file = event.target.files[0];
    if (!file) return;
    
    const reader = new FileReader();
    reader.onload = function(e) {
        try {
            const datos = JSON.parse(e.target.result);
            
            if (confirm('¿Estás seguro? Esto reemplazará todos los datos actuales.')) {
                saveData(STORAGE_KEYS.clientes, datos.clientes || []);
                saveData(STORAGE_KEYS.membresias, datos.membresias || []);
                saveData(STORAGE_KEYS.productos, datos.productos || []);
                saveData(STORAGE_KEYS.ventas, datos.ventas || []);
                saveData(STORAGE_KEYS.progresos, datos.progresos || []);
                saveData(STORAGE_KEYS.retos, datos.retos || []);
                saveData(STORAGE_KEYS.planesNutricion, datos.planesNutricion || []);
                saveData(STORAGE_KEYS.asistencias, datos.asistencias || []);
                
                if (datos.configuracion) {
                    configuracion = datos.configuracion;
                    saveData(STORAGE_KEYS.configuracion, configuracion);
                    cargarConfiguracion();
                }
                
                showSuccess('Datos importados correctamente');
                location.reload();
            }
        } catch (error) {
            showError('Error al importar datos. Archivo inválido.');
        }
    };
    reader.readAsText(file);
}

function limpiarDatos() {
    if (confirm('¿Estás seguro? Esto eliminará TODOS los datos permanentemente.')) {
        if (confirm('¿Realmente estás seguro? Esta acción no se puede deshacer.')) {
            localStorage.clear();
            showInfo('Datos eliminados. Recargando...');
            setTimeout(() => location.reload(), 1500);
        }
    }
}

// ========== NAVEGACIÓN ==========
function showSection(sectionId, element) {
    document.querySelectorAll('.section').forEach(section => {
        section.classList.remove('active');
    });
    
    document.querySelectorAll('.nav-item').forEach(item => {
        item.classList.remove('active');
    });
    
    document.getElementById(sectionId).classList.add('active');
    
    if (element) {
        element.classList.add('active');
    }
    
    const titles = {
        dashboard: { title: 'Dashboard', subtitle: 'Resumen general del gimnasio' },
        asistencias: { title: 'Asistencias', subtitle: 'Control de acceso' },
        clientes: { title: 'Clientes', subtitle: 'Gestión de alumnos' },
        'cliente-detalle': { title: 'Detalle Cliente', subtitle: 'Información del alumno' },
        membresias: { title: 'Membresías', subtitle: 'Planes y precios' },
        productos: { title: 'Productos', subtitle: 'Inventario' },
        ventas: { title: 'Ventas', subtitle: 'Punto de venta' },
        'venta-rapida': { title: 'Venta Rápida', subtitle: 'Venta express de productos' },
        progreso: { title: 'Progreso', subtitle: 'Seguimiento de alumnos' },
        agenda: { title: 'Agenda', subtitle: 'Calendario y eventos' },
        entrenamientos: { title: 'Entrenamientos', subtitle: 'Planes de ejercicio' },
        retos: { title: 'Retos', subtitle: 'Desafíos y metas' },
        nutricion: { title: 'Nutrición', subtitle: 'Planes de alimentación' },
        configuracion: { title: 'Configuración', subtitle: 'Ajustes del sistema' }
    };
    
    if (titles[sectionId]) {
        document.getElementById('page-title').textContent = titles[sectionId].title;
        document.getElementById('page-subtitle').textContent = titles[sectionId].subtitle;
    }
    
    switch(sectionId) {
        case 'dashboard':
            loadDashboard();
            break;
        case 'asistencias':
            loadAsistencias();
            break;
        case 'clientes':
            loadClientes();
            break;
        case 'membresias':
            loadMembresias();
            break;
        case 'productos':
            loadProductos();
            break;
        case 'ventas':
            loadVentas();
            loadClientesSelect();
            loadProductosSelect();
            break;
        case 'venta-rapida':
            loadVentaRapida();
            break;
        case 'progreso':
            loadProgreso();
            loadClientesSelectProgreso();
            break;
        case 'retos':
            loadRetos();
            break;
        case 'nutricion':
            loadNutricion();
            break;
    }
}

// ========== MODALES ==========
function showModal(modalId) {
    document.getElementById(modalId).classList.add('active');
}

function closeModal(modalId) {
    document.getElementById(modalId).classList.remove('active');
}

window.onclick = function(event) {
    if (event.target.classList.contains('modal')) {
        event.target.classList.remove('active');
    }
}

// ========== DASHBOARD ==========
function loadDashboard() {
    const clientes = getData(STORAGE_KEYS.clientes);
    const productos = getData(STORAGE_KEYS.productos);
    const ventas = getData(STORAGE_KEYS.ventas);
    
    const totalClientes = clientes.length;
    const productosBajoStock = productos.filter(p => p.stock <= p.stock_minimo).length;
    
    const inicioMes = new Date();
    inicioMes.setDate(1);
    inicioMes.setHours(0, 0, 0, 0);
    
    const ingresosMes = ventas
        .filter(v => new Date(v.fecha_venta) >= inicioMes)
        .reduce((sum, v) => sum + v.total, 0);
    
    document.getElementById('total-clientes').textContent = totalClientes;
    document.getElementById('membresias-activas').textContent = '0';
    document.getElementById('ingresos-mes').textContent = formatCurrency(ingresosMes);
    document.getElementById('productos-bajo-stock').textContent = productosBajoStock;
    
    loadVentasRecientes();
}

function loadVentasRecientes() {
    const ventas = getData(STORAGE_KEYS.ventas);
    const clientes = getData(STORAGE_KEYS.clientes);
    const tbody = document.getElementById('ventas-recientes');
    
    if (ventas.length === 0) {
        tbody.innerHTML = '<tr><td colspan="5" style="text-align: center; padding: 40px; color: #636E72;">No hay ventas registradas</td></tr>';
        return;
    }
    
    const ventasRecientes = ventas.sort((a, b) => new Date(b.fecha_venta) - new Date(a.fecha_venta)).slice(0, 5);
    
    tbody.innerHTML = ventasRecientes.map(venta => {
        const cliente = clientes.find(c => c.id == venta.cliente_id);
        return `
            <tr>
                <td>${venta.id}</td>
                <td>${new Date(venta.fecha_venta).toLocaleDateString()}</td>
                <td>${cliente ? cliente.nombre : 'Sin cliente'}</td>
                <td>${formatCurrency(venta.total)}</td>
                <td>${venta.metodo_pago || '-'}</td>
            </tr>
        `;
    }).join('');
}

// ========== ASISTENCIAS (NUEVA FUNCIÓN) ==========
function loadAsistencias() {
    const asistencias = getData(STORAGE_KEYS.asistencias);
    const clientes = getData(STORAGE_KEYS.clientes);
    
    // Últimos 20 ingresos
    const ultimosIngresos = asistencias
        .sort((a, b) => new Date(b.fecha_hora_entrada) - new Date(a.fecha_hora_entrada))
        .slice(0, 20);
    
    const tbodyUltimos = document.getElementById('ultimos-ingresos');
    
    if (ultimosIngresos.length === 0) {
        tbodyUltimos.innerHTML = '<tr><td colspan="5" style="text-align: center; padding: 40px; color: #636E72;">No hay ingresos registrados</td></tr>';
    } else {
        tbodyUltimos.innerHTML = ultimosIngresos.map(asistencia => {
            const cliente = clientes.find(c => c.id == asistencia.cliente_id);
            return `
                <tr>
                    <td>${new Date(asistencia.fecha_hora_entrada).toLocaleTimeString()}</td>
                    <td><strong>${cliente ? cliente.nombre : 'Desconocido'}</strong></td>
                    <td>${cliente ? cliente.dni || '-' : '-'}</td>
                    <td>${cliente ? 'Membresía Activa' : '-'}</td>
                    <td><span class="badge badge-success">Activo</span></td>
                </tr>
            `;
        }).join('');
    }
    
    // Asistencias de hoy
    const hoy = new Date();
    hoy.setHours(0, 0, 0, 0);
    
    const asistenciasHoy = asistencias
        .filter(a => new Date(a.fecha_hora_entrada) >= hoy)
        .sort((a, b) => new Date(b.fecha_hora_entrada) - new Date(a.fecha_hora_entrada));
    
    const tbodyHoy = document.getElementById('asistencias-hoy');
    
    if (asistenciasHoy.length === 0) {
        tbodyHoy.innerHTML = '<tr><td colspan="4" style="text-align: center; padding: 40px; color: #636E72;">No hay asistencias hoy</td></tr>';
    } else {
        tbodyHoy.innerHTML = asistenciasHoy.map(asistencia => {
            const cliente = clientes.find(c => c.id == asistencia.cliente_id);
            const duracion = asistencia.fecha_hora_salida ? 
                Math.round((new Date(asistencia.fecha_hora_salida) - new Date(asistencia.fecha_hora_entrada)) / 60000) + ' min' : 
                'En curso';
            
            return `
                <tr>
                    <td>${new Date(asistencia.fecha_hora_entrada).toLocaleTimeString()}</td>
                    <td>${asistencia.fecha_hora_salida ? new Date(asistencia.fecha_hora_salida).toLocaleTimeString() : '-'}</td>
                    <td><strong>${cliente ? cliente.nombre : 'Desconocido'}</strong></td>
                    <td>${duracion}</td>
                </tr>
            `;
        }).join('');
    }
}

function showAsistenciaTab(tabName, element) {
    document.querySelectorAll('.asistencia-tab-content').forEach(tab => {
        tab.style.display = 'none';
    });
    
    document.querySelectorAll('#asistencias .tab').forEach(tab => {
        tab.classList.remove('active');
    });
    
    document.getElementById('asistencia-tab-' + tabName).style.display = 'block';
    element.classList.add('active');
}

function registrarEntrada() {
    const clientes = getData(STORAGE_KEYS.clientes);
    
    if (clientes.length === 0) {
        showError('No hay clientes registrados');
        return;
    }
    
    const clienteId = prompt('Ingrese el ID del cliente:');
    if (!clienteId) return;
    
    const cliente = clientes.find(c => c.id == clienteId);
    if (!cliente) {
        showError('Cliente no encontrado');
        return;
    }
    
    const asistencia = {
        id: generateId(),
        cliente_id: clienteId,
        fecha_hora_entrada: new Date().toISOString(),
        fecha_hora_salida: null
    };
    
    const asistencias = getData(STORAGE_KEYS.asistencias);
    asistencias.push(asistencia);
    saveData(STORAGE_KEYS.asistencias, asistencias);
    
    showSuccess(`Entrada registrada para ${cliente.nombre}`);
    loadAsistencias();
}

// ========== CLIENTES ==========
function loadClientes() {
    const clientes = getData(STORAGE_KEYS.clientes);
    const tbody = document.getElementById('clientes-table');
    
    if (clientes.length === 0) {
        tbody.innerHTML = '<tr><td colspan="6" style="text-align: center; padding: 40px; color: #636E72;">No hay clientes registrados</td></tr>';
        return;
    }
    
    tbody.innerHTML = clientes.map(cliente => `
        <tr>
            <td>${cliente.id}</td>
            <td><strong>${cliente.nombre}</strong></td>
            <td>${cliente.dni || '-'}</td>
            <td>${cliente.telefono || '-'}</td>
            <td>${cliente.email || '-'}</td>
            <td>
                <button class="btn btn-sm btn-primary" onclick="verCliente(${cliente.id})">👁️ Ver</button>
                <button class="btn btn-sm btn-danger" onclick="deleteCliente(${cliente.id})">🗑️</button>
            </td>
        </tr>
    `).join('');
}

function buscarCliente() {
    const searchTerm = document.getElementById('buscar-cliente').value.toLowerCase();
    const clientes = getData(STORAGE_KEYS.clientes);
    
    const filtered = clientes.filter(c => 
        c.nombre.toLowerCase().includes(searchTerm) ||
        (c.dni && c.dni.includes(searchTerm)) ||
        (c.email && c.email.toLowerCase().includes(searchTerm))
    );
    
    const tbody = document.getElementById('clientes-table');
    
    if (filtered.length === 0) {
        tbody.innerHTML = '<tr><td colspan="6" style="text-align: center; padding: 40px; color: #636E72;">No se encontraron clientes</td></tr>';
        return;
    }
    
    tbody.innerHTML = filtered.map(cliente => `
        <tr>
            <td>${cliente.id}</td>
            <td><strong>${cliente.nombre}</strong></td>
            <td>${cliente.dni || '-'}</td>
            <td>${cliente.telefono || '-'}</td>
            <td>${cliente.email || '-'}</td>
            <td>
                <button class="btn btn-sm btn-primary" onclick="verCliente(${cliente.id})">👁️ Ver</button>
                <button class="btn btn-sm btn-danger" onclick="deleteCliente(${cliente.id})">🗑️</button>
            </td>
        </tr>
    `).join('');
}

function verCliente(id) {
    const clientes = getData(STORAGE_KEYS.clientes);
    clienteActual = clientes.find(c => c.id === id);
    
    if (!clienteActual) return;
    
    const iniciales = clienteActual.nombre.split(' ').map(n => n[0]).join('').substring(0, 2).toUpperCase();
    document.getElementById('cliente-avatar-inicial').textContent = iniciales;
    document.getElementById('cliente-nombre-detalle').textContent = clienteActual.nombre;
    document.getElementById('cliente-email-detalle').textContent = clienteActual.email || 'Sin email';
    document.getElementById('cliente-dni-detalle').textContent = clienteActual.dni || 'No registrado';
    document.getElementById('cliente-nombre-tab').textContent = clienteActual.nombre.split(' ')[0] || '';
    document.getElementById('cliente-apellidos').textContent = clienteActual.nombre.split(' ').slice(1).join(' ') || '';
    document.getElementById('cliente-email-tab').textContent = clienteActual.email || 'No registrado';
    document.getElementById('cliente-telefono-tab').textContent = clienteActual.telefono || 'No registrado';
    document.getElementById('cliente-direccion-tab').textContent = clienteActual.direccion || 'No registrada';
    
    if (clienteActual.fecha_nacimiento) {
        const edad = new Date().getFullYear() - new Date(clienteActual.fecha_nacimiento).getFullYear();
        document.getElementById('cliente-edad').textContent = edad;
    } else {
        document.getElementById('cliente-edad').textContent = 'No registrada';
    }
    
    const ventas = getData(STORAGE_KEYS.ventas);
    const progresos = getData(STORAGE_KEYS.progresos);
    
    document.getElementById('cliente-membresias').textContent = '0';
    document.getElementById('cliente-ventas').textContent = ventas.filter(v => v.cliente_id == id).length;
    document.getElementById('cliente-progresos').textContent = progresos.filter(p => p.cliente_id == id).length;
    
    showSection('cliente-detalle', null);
}

function showClienteTab(tabName, element) {
    document.querySelectorAll('.cliente-tab-content').forEach(tab => {
        tab.style.display = 'none';
    });
    
    document.querySelectorAll('.tab').forEach(tab => {
        tab.classList.remove('active');
    });
    
    document.getElementById('cliente-tab-' + tabName).style.display = 'block';
    element.classList.add('active');
}

document.getElementById('form-cliente').addEventListener('submit', async (e) => {
    e.preventDefault();
    
    const cliente = {
        id: generateId(),
        nombre: document.getElementById('cliente-nombre').value,
        dni: document.getElementById('cliente-dni').value,
        telefono: document.getElementById('cliente-telefono').value,
        email: document.getElementById('cliente-email').value,
        fecha_nacimiento: document.getElementById('cliente-nacimiento').value || null,
        direccion: document.getElementById('cliente-direccion').value,
        fecha_registro: new Date().toISOString(),
        activo: true
    };
    
    const clientes = getData(STORAGE_KEYS.clientes);
    clientes.push(cliente);
    saveData(STORAGE_KEYS.clientes, clientes);
    
    showSuccess('Cliente creado correctamente');
    closeModal('cliente-modal');
    document.getElementById('form-cliente').reset();
    loadClientes();
    loadDashboard();
});

function deleteCliente(id) {
    if (!confirm('¿Estás seguro de eliminar este cliente?')) return;
    
    let clientes = getData(STORAGE_KEYS.clientes);
    clientes = clientes.filter(c => c.id !== id);
    saveData(STORAGE_KEYS.clientes, clientes);
    
    showSuccess('Cliente eliminado correctamente');
    loadClientes();
    loadDashboard();
}

// ========== MEMBRESÍAS ==========
function loadMembresias() {
    const membresias = getData(STORAGE_KEYS.membresias);
    const tbody = document.getElementById('membresias-table');
    
    if (membresias.length === 0) {
        tbody.innerHTML = '<tr><td colspan="6" style="text-align: center; padding: 40px; color: #636E72;">No hay membresías registradas</td></tr>';
        return;
    }
    
    tbody.innerHTML = membresias.map(membresia => `
        <tr>
            <td>${membresia.id}</td>
            <td><strong>${membresia.nombre}</strong></td>
            <td>${membresia.descripcion || '-'}</td>
            <td>${formatCurrency(membresia.precio)}</td>
            <td>${membresia.duracion_dias} días</td>
            <td>
                <button class="btn btn-sm btn-danger" onclick="deleteMembresia(${membresia.id})">🗑️</button>
            </td>
        </tr>
    `).join('');
}

document.getElementById('form-membresia').addEventListener('submit', async (e) => {
    e.preventDefault();
    
    const membresia = {
        id: generateId(),
        nombre: document.getElementById('membresia-nombre').value,
        descripcion: document.getElementById('membresia-descripcion').value,
        precio: parseFloat(document.getElementById('membresia-precio').value),
        duracion_dias: parseInt(document.getElementById('membresia-duracion').value),
        activo: true
    };
    
    const membresias = getData(STORAGE_KEYS.membresias);
    membresias.push(membresia);
    saveData(STORAGE_KEYS.membresias, membresias);
    
    showSuccess('Membresía creada correctamente');
    closeModal('membresia-modal');
    document.getElementById('form-membresia').reset();
    loadMembresias();
});

function deleteMembresia(id) {
    if (!confirm('¿Estás seguro de eliminar esta membresía?')) return;
    
    let membresias = getData(STORAGE_KEYS.membresias);
    membresias = membresias.filter(m => m.id !== id);
    saveData(STORAGE_KEYS.membresias, membresias);
    
    showSuccess('Membresía eliminada correctamente');
    loadMembresias();
}

// ========== PRODUCTOS ==========
function loadProductos() {
    const productos = getData(STORAGE_KEYS.productos);
    const tbody = document.getElementById('productos-table');
    
    if (productos.length === 0) {
        tbody.innerHTML = '<tr><td colspan="6" style="text-align: center; padding: 40px; color: #636E72;">No hay productos registrados</td></tr>';
        return;
    }
    
    tbody.innerHTML = productos.map(producto => {
        const stockClass = producto.stock <= producto.stock_minimo ? 'style="color: #E17055; font-weight: bold;"' : '';
        return `
            <tr>
                <td>${producto.id}</td>
                <td><strong>${producto.nombre}</strong></td>
                <td>${producto.categoria || '-'}</td>
                <td>${formatCurrency(producto.precio_venta)}</td>
                <td ${stockClass}>${producto.stock} ${producto.stock <= producto.stock_minimo ? '⚠️' : ''}</td>
                <td>
                    <button class="btn btn-sm btn-danger" onclick="deleteProducto(${producto.id})">🗑️</button>
                </td>
            </tr>
        `;
    }).join('');
}

document.getElementById('form-producto').addEventListener('submit', async (e) => {
    e.preventDefault();
    
    const producto = {
        id: generateId(),
        nombre: document.getElementById('producto-nombre').value,
        descripcion: document.getElementById('producto-descripcion').value,
        precio_compra: parseFloat(document.getElementById('producto-precio-compra').value) || null,
        precio_venta: parseFloat(document.getElementById('producto-precio-venta').value),
        stock: parseInt(document.getElementById('producto-stock').value),
        stock_minimo: parseInt(document.getElementById('producto-stock-minimo').value),
        categoria: document.getElementById('producto-categoria').value,
        activo: true,
        fecha_creacion: new Date().toISOString()
    };
    
    const productos = getData(STORAGE_KEYS.productos);
    productos.push(producto);
    saveData(STORAGE_KEYS.productos, productos);
    
    showSuccess('Producto creado correctamente');
    closeModal('producto-modal');
    document.getElementById('form-producto').reset();
    loadProductos();
    loadDashboard();
});

function deleteProducto(id) {
    if (!confirm('¿Estás seguro de eliminar este producto?')) return;
    
    let productos = getData(STORAGE_KEYS.productos);
    productos = productos.filter(p => p.id !== id);
    saveData(STORAGE_KEYS.productos, productos);
    
    showSuccess('Producto eliminado correctamente');
    loadProductos();
    loadDashboard();
}

// ========== VENTAS ==========
function loadVentas() {
    const ventas = getData(STORAGE_KEYS.ventas);
    const clientes = getData(STORAGE_KEYS.clientes);
    const tbody = document.getElementById('ventas-table');
    
    if (ventas.length === 0) {
        tbody.innerHTML = '<tr><td colspan="5" style="text-align: center; padding: 40px; color: #636E72;">No hay ventas registradas</td></tr>';
        return;
    }
    
    const ventasOrdenadas = ventas.sort((a, b) => new Date(b.fecha_venta) - new Date(a.fecha_venta));
    
    tbody.innerHTML = ventasOrdenadas.map(venta => {
        const cliente = clientes.find(c => c.id == venta.cliente_id);
        return `
            <tr>
                <td>${venta.id}</td>
                <td>${new Date(venta.fecha_venta).toLocaleDateString()}</td>
                <td>${cliente ? cliente.nombre : 'Sin cliente'}</td>
                <td><strong>${formatCurrency(venta.total)}</strong></td>
                <td>${venta.metodo_pago || '-'}</td>
            </tr>
        `;
    }).join('');
}

function loadClientesSelect() {
    const clientes = getData(STORAGE_KEYS.clientes);
    const select = document.getElementById('venta-cliente');
    select.innerHTML = '<option value="">Sin cliente</option>';
    
    clientes.forEach(cliente => {
        select.innerHTML += `<option value="${cliente.id}">${cliente.nombre}</option>`;
    });
}

function loadProductosSelect() {
    const productos = getData(STORAGE_KEYS.productos);
    const container = document.getElementById('productos-venta');
    container.innerHTML = '';
    
    if (productos.length === 0) {
        container.innerHTML = '<p style="color: #636E72; text-align: center; padding: 20px;">No hay productos disponibles</p>';
        return;
    }
    
    productos.forEach(producto => {
        const div = document.createElement('div');
        div.className = 'producto-venta-item';
        div.innerHTML = `
            <select class="producto-select" data-producto-id="${producto.id}">
                <option value="">Seleccionar producto</option>
                <option value="${producto.id}">${producto.nombre} (Stock: ${producto.stock}) - ${formatCurrency(producto.precio_venta)}</option>
            </select>
            <input type="number" class="cantidad-input" placeholder="Cantidad" min="1" value="1">
            <input type="number" class="precio-input" placeholder="Precio" step="0.01" value="${producto.precio_venta}">
            <button type="button" class="btn-remove" onclick="this.parentElement.remove()">❌</button>
        `;
        container.appendChild(div);
    });
}

function agregarProductoVenta() {
    const container = document.getElementById('productos-venta');
    const div = document.createElement('div');
    div.className = 'producto-venta-item';
    div.innerHTML = `
        <input type="text" class="producto-nombre" placeholder="Nombre del producto">
        <input type="number" class="cantidad-input" placeholder="Cantidad" min="1" value="1">
        <input type="number" class="precio-input" placeholder="Precio" step="0.01">
        <button type="button" class="btn-remove" onclick="this.parentElement.remove()">❌</button>
    `;
    container.appendChild(div);
}

document.getElementById('productos-venta').addEventListener('input', calcularTotalVenta);

function calcularTotalVenta() {
    const items = document.querySelectorAll('.producto-venta-item');
    let total = 0;
    
    items.forEach(item => {
        const cantidad = parseFloat(item.querySelector('.cantidad-input').value) || 0;
        const precio = parseFloat(item.querySelector('.precio-input').value) || 0;
        total += cantidad * precio;
    });
    
    document.getElementById('venta-total').textContent = total.toFixed(2);
}

document.getElementById('form-venta').addEventListener('submit', async (e) => {
    e.preventDefault();
    
    const items = document.querySelectorAll('.producto-venta-item');
    const detalles = [];
    let total = 0;
    
    for (const item of items) {
        const select = item.querySelector('.producto-select');
        const productoId = select.value;
        const cantidad = parseInt(item.querySelector('.cantidad-input').value);
        const precio = parseFloat(item.querySelector('.precio-input').value);
        
        if (productoId && cantidad && precio) {
            const subtotal = cantidad * precio;
            total += subtotal;
            detalles.push({
                producto_id: productoId,
                cantidad: cantidad,
                precio_unitario: precio,
                subtotal: subtotal
            });
        }
    }
    
    if (detalles.length === 0) {
        showError('Debe agregar al menos un producto');
        return;
    }
    
    // Aplicar comisión si es tarjeta o QR
    const metodoPago = document.getElementById('venta-metodo-pago').value;
    if (metodoPago === 'tarjeta') {
        total = total * (1 + configuracion.comisionTarjeta / 100);
    } else if (metodoPago === 'qr') {
        total = total * (1 + configuracion.comisionQR / 100);
    }
    
    let productos = getData(STORAGE_KEYS.productos);
    for (const detalle of detalles) {
        const producto = productos.find(p => p.id == detalle.producto_id);
        if (producto) {
            producto.stock -= detalle.cantidad;
        }
    }
    saveData(STORAGE_KEYS.productos, productos);
    
    const venta = {
        id: generateId(),
        cliente_id: document.getElementById('venta-cliente').value || null,
        fecha_venta: new Date().toISOString(),
        total: total,
        metodo_pago: metodoPago,
        notas: '',
        detalles: detalles
    };
    
    const ventas = getData(STORAGE_KEYS.ventas);
    ventas.push(venta);
    saveData(STORAGE_KEYS.ventas, ventas);
    
    showSuccess('Venta registrada correctamente');
    closeModal('venta-modal');
    document.getElementById('form-venta').reset();
    document.getElementById('productos-venta').innerHTML = '';
    loadVentas();
    loadDashboard();
});

// ========== VENTA RÁPIDA (NUEVA FUNCIÓN) ==========
function loadVentaRapida() {
    const productos = getData(STORAGE_KEYS.productos);
    const grid = document.getElementById('productos-venta-rapida');
    
    if (productos.length === 0) {
        grid.innerHTML = '<p style="text-align: center; padding: 40px; color: #636E72;">No hay productos disponibles</p>';
        return;
    }
    
    grid.innerHTML = productos.map(producto => `
        <div class="grid-card" onclick="ventaRapida(${producto.id})">
            <div class="grid-card-image">📦</div>
            <div class="grid-card-content">
                <div class="grid-card-title">${producto.nombre}</div>
                <div class="grid-card-subtitle">${producto.categoria || 'Sin categoría'}</div>
                <div class="grid-card-footer">
                    <span class="grid-card-meta">Stock: ${producto.stock}</span>
                    <span class="grid-card-badge">${formatCurrency(producto.precio_venta)}</span>
                </div>
            </div>
        </div>
    `).join('');
}

function ventaRapida(productoId) {
    const producto = getData(STORAGE_KEYS.productos).find(p => p.id == productoId);
    if (!producto) return;
    
    const cantidad = prompt(`¿Cuántas unidades de ${producto.nombre}?\nStock disponible: ${producto.stock}`, '1');
    if (!cantidad || isNaN(cantidad)) return;
    
    const cantidadNum = parseInt(cantidad);
    if (cantidadNum > producto.stock) {
        showError('Stock insuficiente');
        return;
    }
    
    const metodoPago = prompt('Método de pago:\n1. Efectivo\n2. Tarjeta\n3. QR', '1');
    if (!metodoPago) return;
    
    let metodo = 'efectivo';
    if (metodoPago === '2') metodo = 'tarjeta';
    else if (metodoPago === '3') metodo = 'qr';
    
    const total = producto.precio_venta * cantidadNum;
    
    // Aplicar comisión
    let totalConComision = total;
    if (metodo === 'tarjeta') {
        totalConComision = total * (1 + configuracion.comisionTarjeta / 100);
    } else if (metodo === 'qr') {
        totalConComision = total * (1 + configuracion.comisionQR / 100);
    }
    
    // Actualizar stock
    let productos = getData(STORAGE_KEYS.productos);
    const prodIndex = productos.findIndex(p => p.id == productoId);
    if (prodIndex !== -1) {
        productos[prodIndex].stock -= cantidadNum;
        saveData(STORAGE_KEYS.productos, productos);
    }
    
    // Registrar venta
    const venta = {
        id: generateId(),
        cliente_id: null,
        fecha_venta: new Date().toISOString(),
        total: totalConComision,
        metodo_pago: metodo,
        notas: 'Venta rápida',
        detalles: [{
            producto_id: productoId,
            cantidad: cantidadNum,
            precio_unitario: producto.precio_venta,
            subtotal: total
        }]
    };
    
    const ventas = getData(STORAGE_KEYS.ventas);
    ventas.push(venta);
    saveData(STORAGE_KEYS.ventas, ventas);
    
    showSuccess(`Venta rápida registrada: ${cantidadNum}x ${producto.nombre} - ${formatCurrency(totalConComision)}`);
    loadVentaRapida();
    loadDashboard();
}

// ========== PROGRESO ==========
function loadProgreso() {
    const progresos = getData(STORAGE_KEYS.progresos);
    const clientes = getData(STORAGE_KEYS.clientes);
    const tbody = document.getElementById('progreso-table');
    
    if (progresos.length === 0) {
        tbody.innerHTML = '<tr><td colspan="7" style="text-align: center; padding: 40px; color: #636E72;">No hay registros de progreso</td></tr>';
        return;
    }
    
    const progresosOrdenados = progresos.sort((a, b) => new Date(b.fecha) - new Date(a.fecha));
    
    tbody.innerHTML = progresosOrdenados.map(progreso => {
        const cliente = clientes.find(c => c.id == progreso.cliente_id);
        return `
            <tr>
                <td>${progreso.id}</td>
                <td><strong>${cliente ? cliente.nombre : 'N/A'}</strong></td>
                <td>${new Date(progreso.fecha).toLocaleDateString()}</td>
                <td>${progreso.peso ? progreso.peso + ' kg' : '-'}</td>
                <td>${progreso.porcentaje_grasa ? progreso.porcentaje_grasa + '%' : '-'}</td>
                <td>${progreso.porcentaje_musculo ? progreso.porcentaje_musculo + '%' : '-'}</td>
                <td>
                    <button class="btn btn-sm btn-secondary" onclick="verProgreso(${progreso.id})">👁️ Ver</button>
                </td>
            </tr>
        `;
    }).join('');
}

function loadClientesSelectProgreso() {
    const clientes = getData(STORAGE_KEYS.clientes);
    const select = document.getElementById('progreso-cliente');
    select.innerHTML = '<option value="">Seleccionar cliente</option>';
    
    clientes.forEach(cliente => {
        select.innerHTML += `<option value="${cliente.id}">${cliente.nombre}</option>`;
    });
}

document.getElementById('form-progreso').addEventListener('submit', async (e) => {
    e.preventDefault();
    
    const progreso = {
        id: generateId(),
        cliente_id: parseInt(document.getElementById('progreso-cliente').value),
        fecha: new Date().toISOString(),
        peso: parseFloat(document.getElementById('progreso-peso').value) || null,
        altura: parseFloat(document.getElementById('progreso-altura').value) || null,
        porcentaje_grasa: parseFloat(document.getElementById('progreso-grasa').value) || null,
        porcentaje_musculo: parseFloat(document.getElementById('progreso-musculo').value) || null,
        notas: document.getElementById('progreso-notas').value
    };
    
    const progresos = getData(STORAGE_KEYS.progresos);
    progresos.push(progreso);
    saveData(STORAGE_KEYS.progresos, progresos);
    
    showSuccess('Progreso registrado correctamente');
    closeModal('progreso-modal');
    document.getElementById('form-progreso').reset();
    loadProgreso();
});

function verProgreso(id) {
    const progresos = getData(STORAGE_KEYS.progresos);
    const progreso = progresos.find(p => p.id === id);
    
    if (!progreso) return;
    
    const clientes = getData(STORAGE_KEYS.clientes);
    const cliente = clientes.find(c => c.id == progreso.cliente_id);
    
    const info = `
        Cliente: ${cliente ? cliente.nombre : 'N/A'}
        Fecha: ${new Date(progreso.fecha).toLocaleDateString()}
        Peso: ${progreso.peso ? progreso.peso + ' kg' : 'No registrado'}
        Altura: ${progreso.altura ? progreso.altura + ' cm' : 'No registrada'}
        % Grasa: ${progreso.porcentaje_grasa ? progreso.porcentaje_grasa + '%' : 'No registrado'}
        % Músculo: ${progreso.porcentaje_musculo ? progreso.porcentaje_musculo + '%' : 'No registrado'}
        Notas: ${progreso.notas || 'Sin notas'}
    `;
    
    alert(info);
}

// ========== RETOS ==========
function loadRetos() {
    const retos = getData(STORAGE_KEYS.retos);
    const grid = document.getElementById('retos-grid');
    
    if (retos.length === 0) {
        const retosEjemplo = [
            { id: generateId(), titulo: 'Perder 5kg en 60 días', descripcion: 'Reto de pérdida de peso', imagen: '🏃', participantes: 56, duracion: '60 días', dificultad: 'Intermedio' },
            { id: generateId(), titulo: '2x calistenia por semana', descripcion: 'Mejora tu fuerza corporal', imagen: '💪', participantes: 23, duracion: '30 días', dificultad: 'Principiante' },
            { id: generateId(), titulo: '3x boxeo por semana', descripcion: 'Cardio intenso', imagen: '🥊', participantes: 34, duracion: '45 días', dificultad: 'Avanzado' },
            { id: generateId(), titulo: 'Desarrollar los brazos', descripcion: 'Rutina de bíceps y tríceps', imagen: '💪', participantes: 15, duracion: '30 días', dificultad: 'Intermedio' }
        ];
        saveData(STORAGE_KEYS.retos, retosEjemplo);
        
        grid.innerHTML = retosEjemplo.map(reto => `
            <div class="grid-card">
                <div class="grid-card-image">${reto.imagen}</div>
                <div class="grid-card-content">
                    <div class="grid-card-title">${reto.titulo}</div>
                    <div class="grid-card-subtitle">${reto.descripcion}</div>
                    <div class="grid-card-footer">
                        <span class="grid-card-meta">${reto.participantes} participantes</span>
                        <span class="grid-card-badge">${reto.dificultad}</span>
                    </div>
                </div>
            </div>
        `).join('');
    } else {
        grid.innerHTML = retos.map(reto => `
            <div class="grid-card">
                <div class="grid-card-image">${reto.imagen || '🏆'}</div>
                <div class="grid-card-content">
                    <div class="grid-card-title">${reto.titulo}</div>
                    <div class="grid-card-subtitle">${reto.descripcion}</div>
                    <div class="grid-card-footer">
                        <span class="grid-card-meta">${reto.participantes || 0} participantes</span>
                        <span class="grid-card-badge">${reto.dificultad || 'General'}</span>
                    </div>
                </div>
            </div>
        `).join('');
    }
}

// ========== NUTRICIÓN ==========
function loadNutricion() {
    const planes = getData(STORAGE_KEYS.planesNutricion);
    const grid = document.getElementById('nutricion-grid');
    
    if (planes.length === 0) {
        const planesEjemplo = [
            { id: generateId(), titulo: 'Ganar peso', descripcion: 'Plan alto en calorías', calorias: 823, imagen: '🥗', comidas: 4 },
            { id: generateId(), titulo: 'Perder peso', descripcion: 'Plan bajo en calorías', calorias: 1500, imagen: '🥗', comidas: 5 },
            { id: generateId(), titulo: 'Mantenimiento', descripcion: 'Plan balanceado', calorias: 2000, imagen: '🥗', comidas: 4 }
        ];
        saveData(STORAGE_KEYS.planesNutricion, planesEjemplo);
        
        grid.innerHTML = planesEjemplo.map(plan => `
            <div class="grid-card">
                <div class="grid-card-image">${plan.imagen}</div>
                <div class="grid-card-content">
                    <div class="grid-card-title">${plan.titulo}</div>
                    <div class="grid-card-subtitle">${plan.descripcion}</div>
                    <div class="grid-card-footer">
                        <span class="grid-card-meta">${plan.calorias} kcal</span>
                        <span class="grid-card-badge">${plan.comidas} comidas</span>
                    </div>
                </div>
            </div>
        `).join('');
    } else {
        grid.innerHTML = planes.map(plan => `
            <div class="grid-card">
                <div class="grid-card-image">${plan.imagen || '🥗'}</div>
                <div class="grid-card-content">
                    <div class="grid-card-title">${plan.titulo}</div>
                    <div class="grid-card-subtitle">${plan.descripcion}</div>
                    <div class="grid-card-footer">
                        <span class="grid-card-meta">${plan.calorias || 0} kcal</span>
                        <span class="grid-card-badge">${plan.comidas || 0} comidas</span>
                    </div>
                </div>
            </div>
        `).join('');
    }
}

// ========== INICIALIZACIÓN ==========
document.addEventListener('DOMContentLoaded', () => {
    cargarConfiguracion();
    
    if (getData(STORAGE_KEYS.clientes).length === 0) {
        initSampleData();
    }
    
    loadDashboard();
});

function initSampleData() {
    const clientes = [
        { id: generateId(), nombre: "Juan Pérez", dni: "12345678", telefono: "987654321", email: "juan@email.com", fecha_nacimiento: "1990-05-15", direccion: "", fecha_registro: new Date().toISOString(), activo: true },
        { id: generateId(), nombre: "María García", dni: "87654321", telefono: "912345678", email: "maria@email.com", fecha_nacimiento: "1995-08-20", direccion: "", fecha_registro: new Date().toISOString(), activo: true },
        { id: generateId(), nombre: "Carlos López", dni: "45678912", telefono: "998877665", email: "carlos@email.com", fecha_nacimiento: "1988-03-10", direccion: "", fecha_registro: new Date().toISOString(), activo: true },
        { id: generateId(), nombre: "Ana Martínez", dni: "78912345", telefono: "955443322", email: "ana@email.com", fecha_nacimiento: "1992-11-25", direccion: "", fecha_registro: new Date().toISOString(), activo: true },
        { id: generateId(), nombre: "Roberto Díaz", dni: "32165498", telefono: "933221100", email: "roberto@email.com", fecha_nacimiento: "1985-07-08", direccion: "", fecha_registro: new Date().toISOString(), activo: true }
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
        { id: generateId(), nombre: "Proteína Whey 1kg", descripcion: "Proteína de suero de leche sabor chocolate", precio_compra: 80.00, precio_venta: 120.00, stock: 20, stock_minimo: 5, categoria: "Suplementos", activo: true, fecha_creacion: new Date().toISOString() },
        { id: generateId(), nombre: "Camiseta Deportiva", descripcion: "Camiseta dry-fit para entrenamiento", precio_compra: 25.00, precio_venta: 45.00, stock: 50, stock_minimo: 10, categoria: "Ropa", activo: true, fecha_creacion: new Date().toISOString() },
        { id: generateId(), nombre: "Guantes de Gimnasio", descripcion: "Guantes con agarre antideslizante", precio_compra: 15.00, precio_venta: 30.00, stock: 30, stock_minimo: 8, categoria: "Accesorios", activo: true, fecha_creacion: new Date().toISOString() },
        { id: generateId(), nombre: "Shaker 600ml", descripcion: "Botella mezcladora para proteínas", precio_compra: 8.00, precio_venta: 15.00, stock: 40, stock_minimo: 10, categoria: "Accesorios", activo: true, fecha_creacion: new Date().toISOString() },
        { id: generateId(), nombre: "Creatina 300g", descripcion: "Monohidrato de creatina micronizada", precio_compra: 35.00, precio_venta: 55.00, stock: 15, stock_minimo: 5, categoria: "Suplementos", activo: true, fecha_creacion: new Date().toISOString() }
    ];
    saveData(STORAGE_KEYS.productos, productos);
    
    showInfo('Datos de ejemplo cargados correctamente');
}