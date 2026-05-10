<script lang="ts">
    import { onMount } from 'svelte';
    import { goto } from '$app/navigation';
    import { ApiError, auth, setToken, type MeOut, nodes as nodesApi, type ModelAgg } from '$lib/api';
    import { toast } from '$lib/toast.svelte';
    import { LogOut, RefreshCw, Copy, Sun, Moon, Monitor, Sparkles, Clock } from 'lucide-svelte';
    import HelpPanel from '$lib/components/HelpPanel.svelte';
    import { theme, setTheme, type Theme } from '$lib/theme';

    let me: MeOut | null = $state(null);
    let newToken: string | null = $state(null);
    let tokenExpiresAt: string | null = $state(null);
    let currentTheme: Theme = $state('light');
    let models: ModelAgg[] = $state([]);
    let defaultModel: string = $state('');

    const themeOptions: { value: Theme; label: string; icon: typeof Sun }[] = [
        { value: 'light', label: 'Clair', icon: Sun },
        { value: 'dark', label: 'Sombre', icon: Moon },
        { value: 'system', label: 'Système', icon: Monitor }
    ];

    function isHandledAuthError(e: unknown): boolean {
        return e instanceof ApiError && e.status === 401;
    }

    async function refresh() {
        try {
            me = await auth.me();
            const info = await auth.tokenInfo();
            tokenExpiresAt = info.expires_at;
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
    onMount(() => {
        refresh();
        const unsub = theme.subscribe((t) => (currentTheme = t));
        return unsub;
    });

    function pickTheme(t: Theme) {
        setTheme(t);
    }

    async function loadModels() {
        try {
            models = await nodesApi.models();
        } catch (e) {
            console.error('Failed to load models', e);
        }

        if (typeof localStorage !== 'undefined') {
            defaultModel = localStorage.getItem('spouet:default_model') || '';
        }
    }

    function saveDefaultModel() {
        if (typeof localStorage !== 'undefined') {
            localStorage.setItem('spouet:default_model', defaultModel);
            toast.success('Modèle par défaut enregistré');
        }
    }

    onMount(() => {
        loadModels();
    });
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
        <h2 class="mb-3 text-sm font-medium uppercase tracking-wider text-neutral-400">Apparence</h2>
        <p class="mb-3 text-xs text-neutral-500">
            Mode clair (crème) par défaut. Le mode sombre conserve l'ancien design « nuit ».
            « Système » suit la préférence de ton OS.
        </p>
        <div class="grid gap-2 sm:grid-cols-3">
            {#each themeOptions as opt (opt.value)}
                {@const Icon = opt.icon}
                <button
                    type="button"
                    onclick={() => pickTheme(opt.value)}
                    aria-pressed={currentTheme === opt.value}
                    class="flex items-center justify-center gap-2 rounded-lg border px-3 py-2
                           text-sm transition
                           {currentTheme === opt.value
                        ? 'border-cyan-500/60 bg-cyan-500/10 text-cyan-300'
                        : 'border-neutral-700 hover:bg-neutral-800'}"
                >
                    <Icon size={14} />
                    {opt.label}
                </button>
            {/each}
        </div>
    </section>

    <section class="rounded-xl border border-neutral-800 bg-neutral-900/60 p-5">
        <h2 class="mb-3 text-sm font-medium uppercase tracking-wider text-neutral-400">Préférences</h2>
        <p class="mb-3 text-xs text-neutral-500">
            Choisis le modèle de base utilisé par défaut lors des nouvelles conversations.
        </p>
        <div class="flex max-w-sm flex-col gap-2">
            <label class="flex flex-col gap-1 text-xs text-neutral-400">
                Modèle préféré
                <div class="relative">
                    <Sparkles size={14} class="absolute left-3 top-1/2 -translate-y-1/2 text-cyan-400" />
                    <select
                        bind:value={defaultModel}
                        onchange={saveDefaultModel}
                        class="w-full appearance-none rounded-md border border-neutral-700 bg-neutral-950 py-2 pl-9 pr-8 text-sm focus:border-cyan-500/50 focus:outline-none"
                    >
                        <option value="">Aucun (choix dynamique)</option>
                        {#each models as m}
                            <option value={m.name}>{m.name}</option>
                        {/each}
                    </select>
                </div>
            </label>
        </div>
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
        {#if tokenExpiresAt}
            <p class="mt-3 flex items-center gap-1.5 text-xs text-neutral-500">
                <Clock size={12} />
                Expire le {new Date(tokenExpiresAt).toLocaleString('fr-FR')}
            </p>
        {/if}
        <button
            type="button"
            onclick={rotate}
            class="mt-3 flex items-center gap-2 rounded-lg border border-neutral-700 px-3 py-1.5 text-sm
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
