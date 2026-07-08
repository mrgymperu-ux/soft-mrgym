describe('Prueba del Backend', () => {
    it('should return an array of socios', async () => {
        const response = await fetch('/api/socios');
        expect(response.status).toBe(200);
    });
});