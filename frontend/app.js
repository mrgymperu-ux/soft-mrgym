document.addEventListener('DOMContentLoaded', function() {
    console.log('Soft-Gym cargado exitosamente');

    // Definimos la URL absoluta de tu servidor FastAPI
    const API_URL = 'http://localhost:8000/socios/';

    // Función para cargar la lista de socios
    async function cargarSocios() {
        try {
            // Cambiado a la URL absoluta del backend corriendo en el puerto 8000
            const response = await fetch(API_URL);
            const socios = await response.json();

            const sociosList = document.getElementById('socios-list');
            
            // Si el elemento existe en tu HTML/render, procedemos a llenarlo
            if (sociosList) {
                sociosList.innerHTML = ''; // Limpiamos para evitar duplicados
                socios.forEach(socio => {
                    const li = document.createElement('li');
                    // Usamos nombre y apellido que vienen desde tu FastAPI
                    li.textContent = `${socio.nombre} ${socio.apellido || ''} - ${socio.email || ''}`;
                    sociosList.appendChild(li);
                });
            } else {
                console.warn('No se encontró el contenedor #socios-list en el DOM.');
            }
        } catch (error) {
            console.error('Error al cargar la lista de socios:', error);
        }
    }

    // Llamamos a la función para cargar la lista de socios
    cargarSocios();
});
