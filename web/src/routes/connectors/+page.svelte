<script lang="ts">
    import { onMount } from 'svelte';
    import { fly } from 'svelte/transition';
    import {
        connectors as connectorsApi,
        type ConnectorOut
    } from '$lib/api';
    import EmptyState from '$lib/components/EmptyState.svelte';
    import StatusDot from '$lib/components/StatusDot.svelte';
    import { toast } from '$lib/toast';
    import {
        Plug,
        Plus,
        Play,
        Square,
        RefreshCw,
        Trash2,
        Settings,
        AlertCircle
    } from 'lucide-svelte';

    let items: ConnectorOut[] = $state([]);
    let loading = $state(true);
    let installPath = $state('');
    let installing = $state(false);

    async function load() {
        loading = true;
        try {
            items = await connectorsApi.list();
        } catch {
            toast.error('Impossible de charger les connectors');
        } finally {
            loading = false;
        }
    }

    async function install(e: Event) {
        e.preventDefault();
        if (!installPath.trim()) return;
        installing = true;
        try {
            const c = await connectorsApi.install(installPath.trim());
            toast.success(`${c.name} installé`);
            installPath = '';
            await load();
        } catch {
            toast.error("Échec de l'installation (vérifie le chemin et le manifest)");
        } finally {
            installing = false;
        }
    }

    async function start(c: ConnectorOut) {
        try {
            const r = await connectorsApi.start(c.id);
            if (r.error) toast.error(`Démarrage : ${r.error}`);
            else toast.success(`${c.name} démarré`);
            await load();
        } catch {
            toast.error('Démarrage échoué');
        }
    }

    async function stop(c: ConnectorOut) {
        try {
            await connectorsApi.stop(c.id);
            toast.info(`${c.name} arrêté`);
            await load();
        } catch {
            toast.error("Arrêt échoué");
        }
    }

    async function refresh(c: ConnectorOut) {
        try {
            await connectorsApi.refresh(c.id);
            await load();
        } catch {
            /* ignore */
        }
    }

    async function remove(c: ConnectorOut) {
        if (!confirm(`Supprimer le connector ${c.name} et toutes ses routes ?`)) return;
        try {
            await connectorsApi.delete(c.id);
            await load();
        } catch {
            toast.error('Suppression échouée');
        }
    }

    function statusStyle(status: string): { dot: string; label: string } {
        switch (status) {
            case 'running':
                return { dot: 'bg-emerald-400', label: 'en service' };
            case 'starting':
                return { dot: 'bg-cyan-400', label: 'démarrage…' };
            case 'crashed':
                return { dot: 'bg-red-400', label: 'crashé' };
            default:
                return { dot: 'bg-neutral-500', label: 'arrêté' };
        }
    }

    onMount(load);
</script>

<header
    class="flex items-center justify-between border-b border-[var(--color-border-subtle)]
           bg-[color-mix(in_oklch,var(--color-bg-0)_70%,transparent)] px-6 py-3 backdrop-blur sm:px-8"
>
    <div>
        <h1 class="flex items-center gap-2 text-lg font-medium">
            <Plug size={16} class="text-cyan-400" />
            Connectors persistants
        </h1>
        <p class="text-xs text-neutral-500">
            Bridges Discord, Telegram, IMAP, … chaque connector tourne dans son propre conteneur
            Docker auto-restart.
        </p>
    </div>
</header>

<div class="flex-1 overflow-y-auto px-4 py-6 sm:px-8">
    <div class="mx-auto max-w-5xl space-y-6">
        <section
            class="glass rounded-2xl border border-[var(--color-border)] p-5"
            in:fly={{ y: 6, duration: 180 }}
        >
            <h2 class="mb-3 flex items-center gap-2 text-sm font-medium text-neutral-200">
                <Plus size={14} class="text-cyan-400" />
                Installer un connector depuis un dossier serveur
            </h2>
            <form onsubmit={install} class="flex flex-col gap-2 sm:flex-row">
                <input
                    bind:value={installPath}
                    placeholder="/opt/spouet/connectors/registry/discord"
                    required
                    class="flex-1 rounded-md border border-[var(--color-border)] bg-[var(--color-bg-1)]
                           px-2 py-1.5 font-mono text-sm text-neutral-100 focus:border-cyan-500/50
                           focus:outline-none"
                />
                <button
                    type="submit"
                    disabled={installing}
                    class="rounded-lg bg-cyan-600 px-4 py-1.5 text-xs font-medium text-white
                           disabled:opacity-40 hover:bg-cyan-500"
                >
                    {installing ? 'Installation…' : 'Installer'}
                </button>
            </form>
            <p class="mt-2 text-xs text-neutral-500">
                Le dossier doit contenir un <code class="font-mono">manifest.yaml</code>. L'image
                Docker doit déjà être disponible localement (build ou pull manuel au préalable).
            </p>
        </section>

        {#if loading}
            <p class="text-xs text-neutral-500">Chargement…</p>
        {:else if items.length === 0}
            <EmptyState
                icon={Plug}
                title="Aucun connector installé"
                description="Installe le premier (ex: discord) pour permettre à l'IA d'être joignable depuis l'extérieur."
            />
        {:else}
            {#each items as c (c.id)}
                {@const s = statusStyle(c.status)}
                <article
                    class="rounded-2xl border border-[var(--color-border-subtle)]
                           bg-[var(--color-bg-1)]/40 p-5 shadow-sm"
                    in:fly={{ y: 6, duration: 180 }}
                >
                    <div class="flex items-start justify-between gap-3">
                        <div class="min-w-0">
                            <div class="flex items-center gap-2">
                                <h3 class="text-base font-medium text-neutral-100">{c.name}</h3>
                                <span class="font-mono text-[10px] text-neutral-500"
                                    >v{c.version}</span
                                >
                                <span class="flex items-center gap-1 text-[10px] text-neutral-400">
                                    <span class="h-1.5 w-1.5 rounded-full {s.dot}"></span>
                                    {s.label}
                                </span>
                            </div>
                            <p class="mt-1 text-xs text-neutral-400">{c.description}</p>
                            <p class="mt-1 font-mono text-[10px] text-neutral-600">
                                {c.image}
                            </p>
                            {#if c.last_error}
                                <p
                                    class="mt-2 flex items-start gap-1 rounded-md border
                                           border-red-900/50 bg-red-950/30 p-2 text-xs text-red-300"
                                >
                                    <AlertCircle size={12} class="mt-0.5 shrink-0" />
                                    <span class="font-mono">{c.last_error}</span>
                                </p>
                            {/if}
                        </div>
                        <div class="flex shrink-0 items-center gap-1">
                            {#if c.status === 'running' || c.status === 'starting'}
                                <button
                                    type="button"
                                    onclick={() => stop(c)}
                                    class="rounded-md border border-neutral-700 px-2 py-1 text-xs
                                           hover:bg-neutral-800"
                                    title="Arrêter"
                                >
                                    <Square size={12} />
                                </button>
                            {:else}
                                <button
                                    type="button"
                                    onclick={() => start(c)}
                                    class="rounded-md bg-emerald-600 px-2 py-1 text-xs text-white
                                           hover:bg-emerald-500"
                                    title="Démarrer"
                                >
                                    <Play size={12} />
                                </button>
                            {/if}
                            <button
                                type="button"
                                onclick={() => refresh(c)}
                                class="rounded-md p-1.5 text-neutral-400 hover:bg-white/5 hover:text-white"
                                title="Rafraîchir le statut"
                                aria-label="Rafraîchir"
                            >
                                <RefreshCw size={12} />
                            </button>
                            <a
                                href="/connectors/{c.id}"
                                class="rounded-md p-1.5 text-neutral-400 hover:bg-white/5 hover:text-white"
                                title="Configurer"
                                aria-label="Configurer"
                            >
                                <Settings size={12} />
                            </a>
                            <button
                                type="button"
                                onclick={() => remove(c)}
                                class="rounded-md p-1.5 text-neutral-500 hover:bg-red-500/10 hover:text-red-400"
                                title="Supprimer"
                                aria-label="Supprimer"
                            >
                                <Trash2 size={12} />
                            </button>
                        </div>
                    </div>

                    {#if Object.keys(c.secrets_required).length > 0}
                        <div
                            class="mt-3 rounded-md border border-[var(--color-border-subtle)]
                                   bg-neutral-950/40 p-2"
                        >
                            <p
                                class="mb-1 text-[10px] uppercase tracking-wider text-neutral-500"
                            >
                                Secrets requis
                            </p>
                            <div class="flex flex-wrap gap-1.5">
                                {#each Object.entries(c.secrets_required) as [env, ref]}
                                    <code
                                        class="rounded bg-neutral-800 px-1.5 py-0.5 font-mono text-[10px]
                                               text-neutral-300"
                                    >
                                        {env}={ref}
                                    </code>
                                {/each}
                            </div>
                        </div>
                    {/if}
                </article>
            {/each}
        {/if}
    </div>
</div>
