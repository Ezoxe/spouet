<script lang="ts">
    import { onMount } from 'svelte';
    import { goto } from '$app/navigation';
    import { ApiError, auth, setToken, type MeOut } from '$lib/api';
    import { toast } from '$lib/toast.svelte';
    import { LogOut, RefreshCw, Copy } from 'lucide-svelte';
    import HelpPanel from '$lib/components/HelpPanel.svelte';

    let me: MeOut | null = $state(null);
    let newToken: string | null = $state(null);

    function isHandledAuthError(e: unknown): boolean {
        return e instanceof ApiError && e.status === 401;
    }

    async function refresh() {
        try {
            me = await auth.me();
        } catch (e) {
            if (!isHandledAuthError(e)) {
                toast.error('Impossible de charger le compte.');
                console.error(e);
            }
        }
    }
    async function rotate() {
        if (!confirm('Régénérer le token ? L\'ancien sera invalidé immédiatement.')) return;
        try {
            const r = await auth.rotate();
            newToken = r.token;
            setToken(r.token);
            toast.success('Nouveau token généré — copiez-le maintenant.');
        } catch (e) {
            if (!isHandledAuthError(e)) {
                toast.error('Échec de la régénération du token.');
                console.error(e);
            }
        }
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
    <p class="mt-1 text-xs text-neutral-500">Compte, token API, déconnexion.</p>
</header>

<div class="space-y-4 px-6 pb-6 sm:px-8">
    <HelpPanel title="À propos du token API" storageKey="settings" defaultOpen={false}>
        <ul class="ml-4 list-disc space-y-1">
            <li>
                Le token autorise l’app web/desktop, le node-agent et tout client à parler au
                backend. Il est haché en SHA-256 dans la DB — Spouet ne peut pas te le redonner s’il
                est perdu.
            </li>
            <li>
                Si tu rotes le token : copie-le immédiatement et reconfigure les agents
                (<code class="rounded bg-neutral-800 px-1">SPOUET_AGENT_TOKEN=...</code>).
            </li>
            <li>
                Pour créer un compte supplémentaire (multi-utilisateur), passer par la CLI
                <code class="rounded bg-neutral-800 px-1"
                    >spouet-admin create-token --email autre@local</code
                >.
            </li>
        </ul>
    </HelpPanel>
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
