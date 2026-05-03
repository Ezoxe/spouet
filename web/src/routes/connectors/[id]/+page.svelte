<script lang="ts">
    import { onMount } from 'svelte';
    import { page } from '$app/stores';
    import { goto } from '$app/navigation';
    import {
        connectors as connectorsApi,
        type ConnectorOut,
        type ConnectorRouteOut
    } from '$lib/api';
    import { toast } from '$lib/toast.svelte';
    import { Plug, ArrowLeft, Save, RefreshCw } from 'lucide-svelte';

    const id = $derived($page.params.id);
    let conn: ConnectorOut | null = $state(null);
    let routes: ConnectorRouteOut[] = $state([]);
    let logs = $state('');
    let configText = $state('');
    let saving = $state(false);

    async function load() {
        try {
            const list = await connectorsApi.list();
            conn = list.find((c) => c.id === id) ?? null;
            if (!conn) return;
            configText = JSON.stringify(conn.config, null, 2);
            const [r, l] = await Promise.all([
                connectorsApi.routes(id).catch(() => []),
                connectorsApi.logs(id, 200).catch(() => ({ logs: '' }))
            ]);
            routes = r;
            logs = l.logs;
        } catch {
            toast.error('Chargement échoué');
        }
    }

    async function save() {
        if (!conn) return;
        saving = true;
        try {
            const parsed = JSON.parse(configText);
            const updated = await connectorsApi.patch(conn.id, { config: parsed });
            conn = updated;
            configText = JSON.stringify(updated.config, null, 2);
            toast.success('Configuration enregistrée');
        } catch (e) {
            const msg = e instanceof Error ? e.message : 'Erreur inconnue';
            toast.error(`Échec : ${msg}`);
        } finally {
            saving = false;
        }
    }

    async function toggle() {
        if (!conn) return;
        try {
            const updated = await connectorsApi.patch(conn.id, { enabled: !conn.enabled });
            conn = updated;
            toast.success(updated.enabled ? 'Activé' : 'Désactivé');
        } catch {
            toast.error('Échec');
        }
    }

    async function reloadLogs() {
        if (!conn) return;
        const l = await connectorsApi.logs(conn.id, 400).catch(() => ({ logs: '' }));
        logs = l.logs;
    }

    onMount(load);
</script>

<header
    class="flex items-center justify-between border-b border-[var(--color-border-subtle)]
           bg-[color-mix(in_oklch,var(--color-bg-0)_70%,transparent)] px-6 py-3 backdrop-blur sm:px-8"
>
    <div class="flex items-center gap-3">
        <button
            type="button"
            onclick={() => goto('/connectors')}
            class="rounded-md p-1.5 text-neutral-400 hover:bg-white/5 hover:text-white"
            aria-label="Retour"
        >
            <ArrowLeft size={14} />
        </button>
        <div>
            <h1 class="flex items-center gap-2 text-lg font-medium">
                <Plug size={16} class="text-cyan-400" />
                {conn?.name ?? '…'}
            </h1>
            <p class="text-xs text-neutral-500">
                Status : <span class="text-neutral-300">{conn?.status ?? '—'}</span>
            </p>
        </div>
    </div>
    {#if conn}
        <button
            type="button"
            onclick={toggle}
            class="rounded-md border border-neutral-700 px-3 py-1.5 text-xs hover:bg-neutral-800"
        >
            {conn.enabled ? 'Désactiver' : 'Activer'}
        </button>
    {/if}
</header>

<div class="flex-1 overflow-y-auto px-4 py-6 sm:px-8">
    <div class="mx-auto grid max-w-5xl gap-6 lg:grid-cols-2">
        <section class="rounded-2xl border border-[var(--color-border-subtle)] p-5">
            <h2 class="mb-3 text-sm font-medium text-neutral-200">Configuration</h2>
            <textarea
                bind:value={configText}
                rows="14"
                class="w-full rounded-md border border-[var(--color-border)] bg-[var(--color-bg-1)]
                       p-3 font-mono text-xs text-neutral-100 focus:border-cyan-500/50 focus:outline-none"
            ></textarea>
            <div class="mt-2 flex items-center justify-between">
                <p class="text-xs text-neutral-500">
                    Validé contre <code class="font-mono">config_schema</code> du manifest.
                </p>
                <button
                    type="button"
                    onclick={save}
                    disabled={saving}
                    class="flex items-center gap-1 rounded-md bg-cyan-600 px-3 py-1.5 text-xs
                           font-medium text-white disabled:opacity-40 hover:bg-cyan-500"
                >
                    <Save size={12} />
                    {saving ? 'Enregistrement…' : 'Enregistrer'}
                </button>
            </div>
        </section>

        <section class="rounded-2xl border border-[var(--color-border-subtle)] p-5">
            <h2 class="mb-3 text-sm font-medium text-neutral-200">Schéma attendu</h2>
            <pre
                class="max-h-[20rem] overflow-auto rounded-md bg-neutral-950/60 p-3
                       font-mono text-xs text-neutral-300">{JSON.stringify(
                    conn?.config_schema ?? {},
                    null,
                    2
                )}</pre>
        </section>

        <section class="rounded-2xl border border-[var(--color-border-subtle)] p-5 lg:col-span-2">
            <div class="mb-3 flex items-center justify-between">
                <h2 class="text-sm font-medium text-neutral-200">
                    Routes ({routes.length})
                </h2>
            </div>
            {#if routes.length === 0}
                <p class="text-xs text-neutral-500">
                    Aucun message reçu pour l'instant. Une route est créée automatiquement à la
                    première interaction.
                </p>
            {:else}
                <ul class="divide-y divide-[var(--color-border-subtle)] text-sm">
                    {#each routes as r (r.id)}
                        <li class="flex items-center justify-between py-2">
                            <div>
                                <p class="font-mono text-xs text-neutral-200">{r.external_id}</p>
                                <p class="text-[11px] text-neutral-500">
                                    créé {new Date(r.created_at).toLocaleString()}
                                </p>
                            </div>
                            <a
                                href="/chat/{r.conversation_id}"
                                class="rounded-md border border-neutral-700 px-2 py-1 text-xs
                                       hover:bg-neutral-800"
                            >
                                Ouvrir la conv
                            </a>
                        </li>
                    {/each}
                </ul>
            {/if}
        </section>

        <section class="rounded-2xl border border-[var(--color-border-subtle)] p-5 lg:col-span-2">
            <div class="mb-3 flex items-center justify-between">
                <h2 class="text-sm font-medium text-neutral-200">Logs (200 dernières lignes)</h2>
                <button
                    type="button"
                    onclick={reloadLogs}
                    class="flex items-center gap-1 rounded-md border border-neutral-700 px-2 py-1
                           text-xs hover:bg-neutral-800"
                >
                    <RefreshCw size={12} /> Rafraîchir
                </button>
            </div>
            <pre
                class="max-h-[24rem] overflow-auto rounded-md bg-neutral-950/80 p-3
                       font-mono text-[11px] text-neutral-300">{logs ||
                    '(aucun log)'}</pre>
        </section>
    </div>
</div>
