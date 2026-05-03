<script lang="ts">
    import { onMount } from 'svelte';
    import { goto } from '$app/navigation';
    import { auth, setToken, type MeOut } from '$lib/api';
    import { LogOut, RefreshCw, Copy } from 'lucide-svelte';

    let me: MeOut | null = $state(null);
    let newToken: string | null = $state(null);

    async function refresh() {
        me = await auth.me();
    }
    async function rotate() {
        if (!confirm('Régénérer le token ? L\'ancien sera invalidé immédiatement.')) return;
        const r = await auth.rotate();
        newToken = r.token;
        setToken(r.token);
    }
    function logout() {
        setToken(null);
        goto('/login');
    }
    function copyToken() {
        if (!newToken) return;
        navigator.clipboard.writeText(newToken);
    }
    onMount(refresh);
</script>

<header class="px-6 py-5 sm:px-8">
    <h1 class="text-2xl font-semibold tracking-tight">Paramètres</h1>
</header>

<div class="space-y-4 px-6 pb-6 sm:px-8">
    <section class="rounded-xl border border-neutral-800 bg-neutral-900/60 p-5">
        <h2 class="mb-3 text-sm font-medium uppercase tracking-wider text-neutral-400">Compte</h2>
        <p class="text-sm text-neutral-300">Email : <code>{me?.email ?? '…'}</code></p>
    </section>

    <section class="rounded-xl border border-neutral-800 bg-neutral-900/60 p-5">
        <h2 class="mb-3 text-sm font-medium uppercase tracking-wider text-neutral-400">Token API</h2>
        {#if newToken}
            <div class="mb-3 rounded-lg border border-amber-900/40 bg-amber-950/30 p-3">
                <p class="mb-2 text-xs text-amber-200">
                    Nouveau token (affiché une seule fois — copiez-le maintenant)
                </p>
                <div class="flex items-center gap-2">
                    <code class="flex-1 truncate rounded bg-neutral-950 px-3 py-2 font-mono text-xs"
                        >{newToken}</code
                    >
                    <button
                        type="button"
                        onclick={copyToken}
                        class="rounded p-2 hover:bg-neutral-800"
                        title="Copier"
                    >
                        <Copy size={14} />
                    </button>
                </div>
            </div>
        {/if}
        <button
            type="button"
            onclick={rotate}
            class="flex items-center gap-2 rounded-lg border border-neutral-700 px-3 py-1.5 text-sm
                   hover:bg-neutral-800"
        >
            <RefreshCw size={14} /> Régénérer le token
        </button>
    </section>

    <section class="rounded-xl border border-neutral-800 bg-neutral-900/60 p-5">
        <h2 class="mb-3 text-sm font-medium uppercase tracking-wider text-neutral-400">Session</h2>
        <button
            type="button"
            onclick={logout}
            class="flex items-center gap-2 rounded-lg border border-red-900/40 px-3 py-1.5 text-sm
                   text-red-300 hover:bg-red-950/40"
        >
            <LogOut size={14} /> Se déconnecter
        </button>
    </section>
</div>
