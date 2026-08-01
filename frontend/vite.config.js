import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Configuración de Vite para React
// Para GitHub Pages usar: VITE_BASE=/CFDI-AES/ npm run build
export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000,
    open: true,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
  base: process.env.VITE_BASE || '/', // '/' para Docker/local, '/CFDI-AES/' para GitHub Pages
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

