import { sveltekit } from '@sveltejs/kit/vite';
import tailwindcss from '@tailwindcss/vite';
import { SvelteKitPWA } from '@vite-pwa/sveltekit';
import { defineConfig } from 'vite';

export default defineConfig({
    plugins: [
        tailwindcss(),
        sveltekit(),
        SvelteKitPWA({
            registerType: 'autoUpdate',
            manifest: {
                name: 'Spouet',
                short_name: 'Spouet',
                description: 'Plateforme self-hosted d\'orchestration multi-nodes Ollama',
                theme_color: '#0a0a0a',
                background_color: '#0a0a0a',
                display: 'standalone',
                start_url: '/',
                icons: [
                    {
                        src: '/icon-192.png',
                        sizes: '192x192',
                        type: 'image/png'
                    },
                    {
                        src: '/icon-512.png',
                        sizes: '512x512',
                        type: 'image/png'
                    }
                ]
            },
            workbox: {
                globPatterns: ['**/*.{js,css,html,svg,png,ico,woff,woff2}']
            },
            devOptions: { enabled: false }
        })
    ],
    server: {
        port: 5173,
        proxy: {
            '/api': { target: 'http://localhost:8000', changeOrigin: true },
            '/sse': { target: 'http://localhost:8000', changeOrigin: true, ws: false },
            '/ws': { target: 'ws://localhost:8000', ws: true, changeOrigin: true }
        }
    }
});
