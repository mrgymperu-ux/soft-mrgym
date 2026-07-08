// tests/frontend/LaSocios.spec.ts
describe('Prueba del Frontend', () => {
    beforeEach(async () => {
        jest.clearAllMocks();
    });

    it('should display the list of socios correctly', async () => {
        const response = await fetch('/api/socios');
        expect(response.status).toBe(200);

        const socios = await response.json();
        expect(socios.length).toBeGreaterThan(1);
        const liElements = document.querySelectorAll('li');
        for (let i = 0; i < liElements.length; i++) {
            const li = liElements[i];
            const content = li.textContent.trim();
            expect(content.startsWith(`${socios[i].nombre}`)).toBe(true);
        }
    });
});
