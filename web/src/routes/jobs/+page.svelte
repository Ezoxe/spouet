<script lang="ts">
    import { onMount } from 'svelte';
    import { jobs as jobsApi, type JobOut, type JobRunOut } from '$lib/api';
    import { Play, Trash2, Plus, Pause, Power } from 'lucide-svelte';
    import { toast } from '$lib/toast.svelte';
    import HelpPanel from '$lib/components/HelpPanel.svelte';

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
    async function toggleEnabled(j: JobOut) {
        try {
            await jobsApi.patch(j.id, { enabled: !j.enabled });
            await refresh();
        } catch {
            toast.error('Impossible de modifier la tâche');
        }
    }
    onMount(refresh);
</script>

<header class="flex items-center justify-between px-6 py-5 sm:px-8">
    <div>
        <h1 class="text-2xl font-semibold tracking-tight">Tâches planifiées</h1>
        <p class="mt-1 text-xs text-neutral-500">
            Prompts exécutés automatiquement à intervalle régulier (résumé quotidien, scrape de
            news, alertes…).
        </p>
    </div>
    <button
        type="button"
        onclick={() => (creating = !creating)}
        class="flex items-center gap-2 rounded-lg bg-cyan-600 px-3 py-1.5 text-sm font-medium
               text-white hover:bg-cyan-500"
    >
        <Plus size={14} /> Nouvelle
    </button>
</header>

<div class="px-6 sm:px-8">
    <HelpPanel title="Comment fonctionnent les tâches planifiées" storageKey="jobs">
        <p class="mb-2">
            Une tâche = un <strong>prompt + une expression cron</strong>. Celery Beat la déclenche
            automatiquement, Spouet crée une conversation jetable taggée
            <code class="rounded bg-neutral-800 px-1">[scheduled]</code>, exécute le prompt et
            archive le résultat.
        </p>
        <ul class="ml-4 list-disc space-y-1">
            <li>
                <strong>Cron</strong> : 5 champs UTC. Quelques exemples utiles :
                <code class="rounded bg-neutral-800 px-1">0 * * * *</code> = toutes les heures,
                <code class="rounded bg-neutral-800 px-1">0 8 * * *</code> = chaque jour à 8h UTC,
                <code class="rounded bg-neutral-800 px-1">*/15 * * * *</code> = toutes les 15 min.
            </li>
            <li>
                <strong>Modèle</strong> : laisse vide pour utiliser le premier modèle online.
                Renseigne un nom (ex. <code class="rounded bg-neutral-800 px-1">llama3.1:8b</code>)
                pour figer.
            </li>
            <li>
                Le bouton <Play size={11} class="-mb-0.5 inline" /> lance la tâche immédiatement,
                hors planning. Utile pour tester un prompt avant de partir en prod.
            </li>
            <li>
                Les 3 derniers runs sont visibles sous chaque tâche. Un run est notifié multi-device
                via WebSocket dès qu’il finit.
            </li>
        </ul>
    </HelpPanel>
</div>

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
                <div class="flex items-center gap-2">
                    <div>
                        <h3 class="font-medium">{j.name}</h3>
                        <p class="font-mono text-xs text-neutral-500">{j.cron}</p>
                    </div>
                    {#if !j.enabled}
                        <span class="rounded bg-neutral-800 px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-neutral-500">
                            en pause
                        </span>
                    {/if}
                </div>
                <div class="flex gap-1">
                    <button
                        type="button"
                        onclick={() => toggleEnabled(j)}
                        class="rounded p-1.5 text-neutral-400 hover:bg-neutral-800 hover:text-neutral-100"
                        title={j.enabled ? 'Mettre en pause' : 'Réactiver'}
                        aria-label={j.enabled ? 'Mettre en pause la tâche' : 'Réactiver la tâche'}
                    >
                        {#if j.enabled}
                            <Pause size={14} />
                        {:else}
                            <Power size={14} />
                        {/if}
                    </button>
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
