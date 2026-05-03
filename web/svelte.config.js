import adapter from '@sveltejs/adapter-static';
import { vitePreprocess } from '@sveltejs/vite-plugin-svelte';

/** @type {import('@sveltejs/kit').Config} */
const config = {
    preprocess: vitePreprocess(),
    kit: {
        // Build statique pour réutilisation par Tauri (frontendDist)
        adapter: adapter({
            pages: 'build',
            assets: 'build',
            fallback: 'index.html', // SPA fallback (compatible Tauri + PWA)
            precompress: false,
            strict: false
        }),
        alias: {
            $lib: 'src/lib'
        }
    }
};

export default config;
