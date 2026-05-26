import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Configuración de Vite para React + GitHub Pages
export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000, // Puerto local para desarrollo
    open: true, // Abre automáticamente el navegador al iniciar
  },
  base: '/CFDI-AES/', // 👈 Ruta base para GitHub Pages
  build: {
    outDir: 'dist', // Carpeta de salida del build
    sourcemap: false, // Desactiva mapas de código para producción
    minify: 'esbuild', // Minimiza JS/CSS para mejor rendimiento
  },
  resolve: {
    alias: {
      '@': '/src', // 👈 Atajo para importar desde src/
    },
  },
})

