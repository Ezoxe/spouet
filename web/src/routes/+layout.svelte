<script lang="ts">
    import '../app.css';
    import { onMount } from 'svelte';
    import { goto } from '$app/navigation';
    import { page } from '$app/stores';
    import { fade } from 'svelte/transition';
    import { getToken } from '$lib/api';
    import { initTheme } from '$lib/theme';
    import Sidebar from '$lib/components/Sidebar.svelte';
    import Toaster from '$lib/components/Toaster.svelte';

    let { children } = $props();
    let ready = $state(false);

    onMount(() => {
        initTheme();
        if (!getToken() && $page.url.pathname !== '/login') {
            goto('/login');
            return;
        }
        ready = true;
    });

    const isLogin = $derived($page.url.pathname === '/login');
    const isCompanion = $derived($page.url.pathname === '/companion');
</script>

<Toaster />

{#if !ready && !isLogin}
    <div class="grid min-h-screen place-items-center text-neutral-500" in:fade>…</div>
{:else if isLogin || isCompanion}
    {@render children?.()}
{:else}
    <div class="flex h-screen overflow-hidden">
        <Sidebar />
        <main class="flex min-w-0 flex-1 flex-col overflow-hidden">
            {#key $page.url.pathname}
                <div class="flex min-h-0 flex-1 flex-col" in:fade={{ duration: 140 }}>
                    {@render children?.()}
                </div>
            {/key}
        </main>
    </div>
{/if}
