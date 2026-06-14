<script lang="ts">
    import '../app.css';
    import { onMount } from 'svelte';
    import { goto } from '$app/navigation';
    import { page } from '$app/stores';
    import { fade } from 'svelte/transition';
    import { getToken, isTokenExpired, setToken } from '$lib/api';
    import { initTheme } from '$lib/theme';
    import { startDesktopAgent } from '$lib/realtime';
    import { toast } from '$lib/toast.svelte';
    import Sidebar from '$lib/components/Sidebar.svelte';
    import Toaster from '$lib/components/Toaster.svelte';
    import DownloadsOverlay from '$lib/components/DownloadsOverlay.svelte';

    let { children } = $props();
    let ready = $state(false);

    onMount(() => {
        initTheme();

        if (getToken() && isTokenExpired()) {
            setToken(null);
            toast.error('Session expirée (24h). Reconnectez-vous.');
            goto('/login');
            return;
        }

        if (!getToken() && $page.url.pathname !== '/login') {
            goto('/login');
            return;
        }

        const timer = setInterval(() => {
            if (getToken() && isTokenExpired()) {
                setToken(null);
                toast.error('Session expirée (24h). Reconnectez-vous.');
                goto('/login');
            }
        }, 60_000);

        // Agent de pilotage PC (app desktop, fenêtre main uniquement — idempotent).
        startDesktopAgent();

        ready = true;
        return () => clearInterval(timer);
    });

    const isLogin = $derived($page.url.pathname === '/login');
    const isCompanion = $derived($page.url.pathname === '/companion');
    // L'overlay (HUD de visuels) se rend en pleine page, sans sidebar ni chrome.
    const isBare = $derived(isCompanion || $page.url.pathname === '/overlay');
</script>

<Toaster />
<DownloadsOverlay />

{#if !ready && !isLogin && !isBare}
    <div class="grid min-h-screen place-items-center text-neutral-500" in:fade>…</div>
{:else if isLogin || isBare}
    {@render children?.()}
{:else}
    <div class="flex h-screen flex-col md:flex-row overflow-hidden">
        <Sidebar />
        <main class="flex min-w-0 flex-1 flex-col overflow-hidden">
            {#key $page.url.pathname}
                <!-- overflow-y-auto : repli scrollable pour les pages « document »
                     (tools, stats, settings…) qui ne gèrent pas leur propre scroll.
                     Sans ça, leur contenu était clippé (impossible de descendre à la
                     molette, surtout au zoom). Les pages à scroll interne (chat,
                     secrets, connectors) remplissent la hauteur → pas de double-scroll. -->
                <div class="flex min-h-0 flex-1 flex-col overflow-y-auto" in:fade={{ duration: 140 }}>
                    {@render children?.()}
                </div>
            {/key}
        </main>
    </div>
{/if}
