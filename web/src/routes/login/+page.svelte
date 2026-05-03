<script lang="ts">
    import { goto } from '$app/navigation';
    import { fly } from 'svelte/transition';
    import { Loader2, KeyRound } from 'lucide-svelte';
    import { auth, setToken } from '$lib/api';
    import Logo from '$lib/components/Logo.svelte';

    let token = $state('');
    let loading = $state(false);
    let error = $state<string | null>(null);

    async function submit(e: SubmitEvent) {
        e.preventDefault();
        if (!token.trim()) return;
        loading = true;
        error = null;
        setToken(token.trim());
        try {
            await auth.me();
            goto('/');
        } catch (e: unknown) {
            setToken(null);
            error = 'Token invalide.';
            console.error(e);
        } finally {
            loading = false;
        }
    }
</script>

<div class="grid min-h-screen place-items-center p-4">
    <form
        onsubmit={submit}
        class="glass w-full max-w-sm space-y-5 rounded-2xl p-8 shadow-2xl"
        in:fly={{ y: 12, duration: 320 }}
    >
        <div class="flex flex-col items-center gap-3 text-center">
            <Logo size={56} glow animated />
            <div>
                <h1 class="text-xl font-semibold tracking-tight">Bienvenue sur Spouet</h1>
                <p class="mt-1 text-xs text-neutral-400">Connectez-vous avec votre token API</p>
            </div>
        </div>

        <label class="block">
            <span class="mb-1.5 flex items-center gap-1.5 text-xs text-neutral-400">
                <KeyRound size={12} /> Token
            </span>
            <input
                type="password"
                bind:value={token}
                autocomplete="off"
                spellcheck="false"
                required
                class="w-full rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-1)]
                       px-3 py-2.5 font-mono text-sm focus:border-cyan-500/50 focus:outline-none
                       focus:ring-2 focus:ring-cyan-500/20"
            />
        </label>

        {#if error}
            <p
                in:fly={{ y: -4, duration: 160 }}
                class="rounded-md border border-red-900/40 bg-red-950/30 px-3 py-2 text-xs text-red-300"
            >
                {error}
            </p>
        {/if}

        <button
            type="submit"
            disabled={loading}
            class="flex w-full items-center justify-center gap-2 rounded-lg
                   bg-gradient-to-br from-cyan-500 to-cyan-700 px-3 py-2.5 text-sm
                   font-medium text-white shadow-[0_8px_24px_-8px_oklch(0.55_0.18_210/0.6)]
                   transition-all hover:scale-[1.01] active:scale-[0.99]
                   disabled:opacity-50 disabled:hover:scale-100"
        >
            {#if loading}
                <Loader2 size={14} class="animate-spin" /> Vérification…
            {:else}
                Se connecter
            {/if}
        </button>

        <p class="text-center text-[10px] text-neutral-600">
            Générer un token : <code class="rounded bg-neutral-800 px-1 py-0.5"
                >spouet-admin create-token --email vous@local</code
            >
        </p>
    </form>
</div>
