import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  preview: {
    allowedHosts: ['ai-hotel-frontend.onrender.com', 'ai-hotel-frontend-rgr1.onrender.com'],
  },
})
