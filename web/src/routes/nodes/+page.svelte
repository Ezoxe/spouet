<script lang="ts">
    import { onMount } from 'svelte';
    import { Trash2, RefreshCw } from 'lucide-svelte';
    import { nodes as nodesApi, type NodeOut } from '$lib/api';

    let list: NodeOut[] = $state([]);
    let loading = $state(false);

    async function refresh() {
        loading = true;
        try {
            list = await nodesApi.list();
        } finally {
            loading = false;
        }
    }
    async function del(id: string) {
        if (!confirm('Supprimer ce node ?')) return;
        await nodesApi.delete(id);
        await refresh();
    }
    onMount(() => {
        refresh();
        const i = setInterval(refresh, 5000);
        return () => clearInterval(i);
    });
</script>

<header class="flex items-center justify-between px-6 py-5 sm:px-8">
    <h1 class="text-2xl font-semibold tracking-tight">Nodes Ollama</h1>
    <button
        type="button"
        onclick={refresh}
        class="flex items-center gap-2 rounded-lg border border-neutral-700 px-3 py-1.5 text-sm
               hover:bg-neutral-800"
    >
        <RefreshCw size={14} class={loading ? 'animate-spin' : ''} /> Rafraîchir
    </button>
</header>

<div class="space-y-3 px-6 pb-6 sm:px-8">
    {#each list as n (n.id)}
        <article class="rounded-xl border border-neutral-800 bg-neutral-900/60 p-4">
            <div class="mb-3 flex items-center justify-between">
                <div class="flex items-center gap-3">
                    <span
                        class="h-2 w-2 rounded-full"
                        class:bg-emerald-400={n.status === 'online'}
                        class:bg-neutral-600={n.status !== 'online'}
                    ></span>
                    <h3 class="font-medium">{n.name}</h3>
                    <span class="text-xs text-neutral-500">{n.host}:{n.port}</span>
                </div>
                <button
                    type="button"
                    onclick={() => del(n.id)}
                    class="rounded p-1.5 text-neutral-500 hover:bg-red-950 hover:text-red-300"
                >
                    <Trash2 size={14} />
                </button>
            </div>
            <div class="grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
                <div>
                    <dt class="text-xs text-neutral-500">GPU</dt>
                    <dd>{n.gpu_model ?? '—'}</dd>
                </div>
                <div>
                    <dt class="text-xs text-neutral-500">VRAM</dt>
                    <dd>{n.vram_used_mb ?? '—'} / {n.vram_total_mb ?? '—'} MB</dd>
                </div>
                <div>
                    <dt class="text-xs text-neutral-500">Modèles</dt>
                    <dd>{n.models.length}</dd>
                </div>
                <div>
                    <dt class="text-xs text-neutral-500">Agent</dt>
                    <dd>{n.agent_version ?? '—'}</dd>
                </div>
            </div>
            {#if n.models.length}
                <details class="mt-3">
                    <summary class="cursor-pointer text-xs text-neutral-500 hover:text-neutral-300">
                        {n.models.length} modèles
                    </summary>
                    <ul class="mt-2 space-y-1 text-xs text-neutral-400">
                        {#each n.models as m}
                            <li class="flex items-center justify-between">
                                <span class="font-mono">{m.name}</span>
                                {#if m.supports_tools}
                                    <span
                                        class="rounded bg-cyan-900/40 px-1.5 py-0.5 text-[10px] text-cyan-300"
                                        >tools</span
                                    >
                                {/if}
                            </li>
                        {/each}
                    </ul>
                </details>
            {/if}
        </article>
    {:else}
        <p class="text-sm text-neutral-500">Aucun node.</p>
    {/each}
</div>
