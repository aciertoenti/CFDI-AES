import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Configuración para desarrollo local y despliegue en GitHub Pages
export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000, // Puerto local para desarrollo
  },
  base: '/CFDI-AES/', // 👈 Ruta base para GitHub Pages
  build: {
    outDir: 'dist', // Carpeta de salida del build
  },
})

