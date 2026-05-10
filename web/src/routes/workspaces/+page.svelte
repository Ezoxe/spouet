<script lang="ts">
    import { onMount } from 'svelte';
    import { goto } from '$app/navigation';
    import {
        workspaces as workspacesApi,
        nodes as nodesApi,
        type WorkspaceOut,
        type ModelAgg,
        type WorkerConfig
    } from '$lib/api';
    import { toast } from '$lib/toast.svelte';
    import { Plus, Trash2, LayoutPanelLeft, ChevronRight } from 'lucide-svelte';
    import EmptyState from '$lib/components/EmptyState.svelte';

    let items: WorkspaceOut[] = $state([]);
    let models: ModelAgg[] = $state([]);
    let loading = $state(true);

    // Modal création
    let showCreate = $state(false);
    let name = $state('');
    let managerModel = $state('');
    let workers: WorkerConfig[] = $state([{ title: 'Worker 1', model_pref: '' }]);
    let creating = $state(false);

    async function load() {
        loading = true;
        try {
            [items, models] = await Promise.all([
                workspacesApi.list(),
                nodesApi.models().catch(() => [] as ModelAgg[])
            ]);
            if (!managerModel && models.length > 0) managerModel = models[0].name;
        } finally {
            loading = false;
        }
    }

    async function createWorkspace() {
        if (!name.trim() || !managerModel) {
            toast.error('Nom et modèle manager obligatoires.');
            return;
        }
        creating = true;
        try {
            const ws = await workspacesApi.create({
                name: name.trim(),
                manager_model: managerModel,
                workers: workers.filter((w) => w.model_pref)
            });
            toast.info(`Workspace « ${ws.name} » créé.`);
            showCreate = false;
            name = '';
            workers = [{ title: 'Worker 1', model_pref: '' }];
            goto(`/workspace/${ws.id}`);
        } catch {
            toast.error('Impossible de créer le workspace.');
        } finally {
            creating = false;
        }
    }

    async function deleteWs(ws: WorkspaceOut) {
        if (!confirm(`Supprimer le workspace « ${ws.name} » et toutes ses conversations ?`)) return;
        try {
            await workspacesApi.delete(ws.id);
            items = items.filter((w) => w.id !== ws.id);
            toast.info('Workspace supprimé.');
        } catch {
            toast.error('Suppression impossible.');
        }
    }

    function addWorker() {
        workers = [...workers, { title: `Worker ${workers.length + 1}`, model_pref: managerModel }];
    }

    function removeWorker(i: number) {
        workers = workers.filter((_, idx) => idx !== i);
    }

    onMount(load);
</script>

<div class="flex flex-1 flex-col overflow-hidden">
    <header class="flex items-center justify-between border-b border-[var(--color-border-subtle)] px-6 py-4">
        <div>
            <h1 class="text-lg font-semibold">Workspaces multi-agents</h1>
            <p class="text-xs text-neutral-500">Orchestrez plusieurs agents en parallèle.</p>
        </div>
        <button
            type="button"
            onclick={() => (showCreate = true)}
            class="flex items-center gap-2 rounded-md bg-cyan-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-cyan-500"
        >
            <Plus size={14} />
            Nouveau workspace
        </button>
    </header>

    <div class="flex-1 overflow-y-auto p-6">
        {#if loading}
            <p class="text-sm text-neutral-500">Chargement…</p>
        {:else if items.length === 0}
            <EmptyState
                icon={LayoutPanelLeft}
                title="Aucun workspace"
                description="Créez un workspace pour orchestrer plusieurs agents LLM en parallèle."
            />
        {:else}
            <div class="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
                {#each items as ws (ws.id)}
                    {@const manager = ws.conversations.find((c) => c.workspace_role === 'manager')}
                    {@const workerCount = ws.conversations.filter((c) => c.workspace_role === 'worker').length}
                    <div class="group relative rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-1)] p-4 transition hover:border-cyan-500/40">
                        <a href="/workspace/{ws.id}" class="block">
                            <div class="mb-3 flex items-start justify-between gap-2">
                                <div class="min-w-0">
                                    <h2 class="truncate font-medium text-neutral-100">{ws.name}</h2>
                                    <p class="mt-0.5 text-xs text-neutral-500">
                                        {workerCount} worker{workerCount !== 1 ? 's' : ''}
                                        {#if manager?.model_pref}· {manager.model_pref}{/if}
                                    </p>
                                </div>
                                <ChevronRight size={16} class="mt-0.5 shrink-0 text-neutral-600 transition group-hover:text-cyan-400" />
                            </div>
                            <ul class="space-y-1">
                                {#each ws.conversations.slice(0, 4) as c}
                                    <li class="flex items-center gap-2 text-xs text-neutral-400">
                                        <span
                                            class="rounded px-1.5 py-0.5 text-[10px] font-medium
                                                   {c.workspace_role === 'manager'
                                                       ? 'bg-cyan-500/15 text-cyan-300'
                                                       : 'bg-neutral-700 text-neutral-400'}"
                                        >
                                            {c.workspace_role === 'manager' ? 'Manager' : 'Worker'}
                                        </span>
                                        <span class="truncate">{c.title}</span>
                                    </li>
                                {/each}
                                {#if ws.conversations.length > 4}
                                    <li class="text-xs text-neutral-600">+{ws.conversations.length - 4} autres…</li>
                                {/if}
                            </ul>
                        </a>
                        <button
                            type="button"
                            onclick={() => deleteWs(ws)}
                            class="absolute right-3 top-3 hidden rounded p-1 text-neutral-500 hover:bg-red-950 hover:text-red-300 group-hover:block"
                            title="Supprimer"
                            aria-label="Supprimer le workspace"
                        >
                            <Trash2 size={13} />
                        </button>
                    </div>
                {/each}
            </div>
        {/if}
    </div>
</div>

<!-- Modal création workspace -->
{#if showCreate}
    <div class="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm">
        <div class="w-full max-w-lg rounded-2xl border border-[var(--color-border)] bg-[var(--color-bg-1)] shadow-2xl">
            <div class="border-b border-[var(--color-border-subtle)] px-6 py-4">
                <h2 class="font-semibold">Nouveau workspace</h2>
            </div>
            <div class="space-y-4 p-6">
                <div>
                    <label for="ws-name" class="mb-1 block text-xs font-medium text-neutral-400">Nom</label>
                    <input
                        id="ws-name"
                        bind:value={name}
                        type="text"
                        placeholder="Mon workspace"
                        class="w-full rounded-md border border-[var(--color-border)] bg-[var(--color-bg-0)] px-3 py-2 text-sm focus:border-cyan-500/60 focus:outline-none"
                    />
                </div>
                <div>
                    <label for="ws-manager-model" class="mb-1 block text-xs font-medium text-neutral-400">Modèle du manager</label>
                    <select
                        id="ws-manager-model"
                        bind:value={managerModel}
                        class="w-full rounded-md border border-[var(--color-border)] bg-[var(--color-bg-0)] px-3 py-2 text-sm focus:border-cyan-500/60 focus:outline-none"
                    >
                        {#each models as m}
                            <option value={m.name}>{m.name}</option>
                        {/each}
                    </select>
                </div>

                <div>
                    <div class="mb-2 flex items-center justify-between">
                        <span class="text-xs font-medium text-neutral-400">Workers</span>
                        <button
                            type="button"
                            onclick={addWorker}
                            class="flex items-center gap-1 rounded px-2 py-1 text-xs text-cyan-400 hover:bg-cyan-500/10"
                        >
                            <Plus size={12} />
                            Ajouter
                        </button>
                    </div>
                    <div class="space-y-2">
                        {#each workers as w, i (i)}
                            <div class="flex items-center gap-2">
                                <input
                                    bind:value={w.title}
                                    type="text"
                                    placeholder="Titre du worker"
                                    class="min-w-0 flex-1 rounded-md border border-[var(--color-border)] bg-[var(--color-bg-0)] px-2 py-1.5 text-xs focus:border-cyan-500/60 focus:outline-none"
                                />
                                <select
                                    bind:value={w.model_pref}
                                    class="min-w-0 flex-1 rounded-md border border-[var(--color-border)] bg-[var(--color-bg-0)] px-2 py-1.5 text-xs focus:border-cyan-500/60 focus:outline-none"
                                >
                                    <option value="">— modèle —</option>
                                    {#each models as m}
                                        <option value={m.name}>{m.name}</option>
                                    {/each}
                                </select>
                                <button
                                    type="button"
                                    onclick={() => removeWorker(i)}
                                    class="shrink-0 rounded p-1 text-neutral-500 hover:text-red-400"
                                    aria-label="Supprimer ce worker"
                                >
                                    <Trash2 size={13} />
                                </button>
                            </div>
                        {/each}
                    </div>
                </div>
            </div>
            <div class="flex justify-end gap-2 border-t border-[var(--color-border-subtle)] px-6 py-4">
                <button
                    type="button"
                    onclick={() => (showCreate = false)}
                    class="rounded-md border border-[var(--color-border)] px-4 py-2 text-sm hover:bg-neutral-800"
                    >Annuler</button
                >
                <button
                    type="button"
                    onclick={createWorkspace}
                    disabled={creating}
                    class="rounded-md bg-cyan-600 px-4 py-2 text-sm font-medium text-white hover:bg-cyan-500 disabled:opacity-50"
                    >{creating ? 'Création…' : 'Créer'}</button
                >
            </div>
        </div>
    </div>
{/if}
