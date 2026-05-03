<script lang="ts">
    import { onMount } from 'svelte';
    import { jobs as jobsApi, type JobOut, type JobRunOut } from '$lib/api';
    import { Play, Trash2, Plus } from 'lucide-svelte';

    let list: JobOut[] = $state([]);
    let creating = $state(false);
    let form = $state({ name: '', cron: '0 * * * *', prompt: '', model_pref: '' });
    let runsByJob: Record<string, JobRunOut[]> = $state({});

    async function refresh() {
        list = await jobsApi.list();
        const all = await Promise.all(
            list.map(async (j) => [j.id, await jobsApi.runs(j.id).catch(() => [])] as const)
        );
        runsByJob = Object.fromEntries(all);
    }
    async function create() {
        await jobsApi.create({
            name: form.name,
            cron: form.cron,
            prompt: form.prompt,
            model_pref: form.model_pref || undefined
        });
        form = { name: '', cron: '0 * * * *', prompt: '', model_pref: '' };
        creating = false;
        await refresh();
    }
    async function del(id: string) {
        if (!confirm('Supprimer ce job ?')) return;
        await jobsApi.delete(id);
        await refresh();
    }
    async function run(id: string) {
        await jobsApi.run(id);
        setTimeout(refresh, 1500);
    }
    onMount(refresh);
</script>

<header class="flex items-center justify-between px-6 py-5 sm:px-8">
    <h1 class="text-2xl font-semibold tracking-tight">Tâches planifiées</h1>
    <button
        type="button"
        onclick={() => (creating = !creating)}
        class="flex items-center gap-2 rounded-lg bg-cyan-600 px-3 py-1.5 text-sm font-medium
               text-white hover:bg-cyan-500"
    >
        <Plus size={14} /> Nouvelle
    </button>
</header>

{#if creating}
    <form
        onsubmit={(e) => {
            e.preventDefault();
            create();
        }}
        class="mx-6 mb-4 grid gap-3 rounded-xl border border-neutral-800 bg-neutral-900 p-4 sm:mx-8"
    >
        <input
            placeholder="Nom"
            bind:value={form.name}
            required
            class="rounded-md border border-neutral-700 bg-neutral-950 px-3 py-2 text-sm"
        />
        <div class="grid grid-cols-2 gap-3">
            <input
                placeholder="Cron (ex: 0 * * * *)"
                bind:value={form.cron}
                required
                class="rounded-md border border-neutral-700 bg-neutral-950 px-3 py-2 font-mono text-sm"
            />
            <input
                placeholder="Modèle (optionnel)"
                bind:value={form.model_pref}
                class="rounded-md border border-neutral-700 bg-neutral-950 px-3 py-2 text-sm"
            />
        </div>
        <textarea
            placeholder="Prompt"
            bind:value={form.prompt}
            required
            rows="3"
            class="rounded-md border border-neutral-700 bg-neutral-950 px-3 py-2 text-sm"
        ></textarea>
        <button class="rounded-md bg-cyan-600 px-3 py-2 text-sm font-medium hover:bg-cyan-500"
            >Créer</button
        >
    </form>
{/if}

<div class="space-y-3 px-6 pb-6 sm:px-8">
    {#each list as j (j.id)}
        <article class="rounded-xl border border-neutral-800 bg-neutral-900/60 p-4">
            <div class="mb-2 flex items-center justify-between">
                <div>
                    <h3 class="font-medium">{j.name}</h3>
                    <p class="font-mono text-xs text-neutral-500">{j.cron}</p>
                </div>
                <div class="flex gap-1">
                    <button
                        type="button"
                        onclick={() => run(j.id)}
                        class="rounded p-1.5 text-neutral-400 hover:bg-emerald-950 hover:text-emerald-300"
                        title="Exécuter maintenant"
                    >
                        <Play size={14} />
                    </button>
                    <button
                        type="button"
                        onclick={() => del(j.id)}
                        class="rounded p-1.5 text-neutral-500 hover:bg-red-950 hover:text-red-300"
                    >
                        <Trash2 size={14} />
                    </button>
                </div>
            </div>
            <p class="mb-3 line-clamp-2 text-sm text-neutral-400">{j.prompt}</p>
            {#if runsByJob[j.id]?.length}
                <div class="mt-2 space-y-1 text-xs">
                    {#each runsByJob[j.id].slice(0, 3) as r}
                        <div class="flex justify-between text-neutral-500">
                            <span
                                class:text-emerald-400={r.status === 'ok'}
                                class:text-red-400={r.status === 'fail'}
                            >
                                {r.status}
                            </span>
                            <span>{new Date(r.created_at).toLocaleString('fr-FR')}</span>
                        </div>
                    {/each}
                </div>
            {/if}
        </article>
    {:else}
        <p class="text-sm text-neutral-500">Aucune tâche planifiée.</p>
    {/each}
</div>
