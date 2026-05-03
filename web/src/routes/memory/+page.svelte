<script lang="ts">
    import { onMount } from 'svelte';
    import { memory, type MemoryOut } from '$lib/api';
    import { Trash2, Plus } from 'lucide-svelte';
    import HelpPanel from '$lib/components/HelpPanel.svelte';

    let list: MemoryOut[] = $state([]);
    let creating = $state(false);
    let form = $state({ key: '', value: '' });

    async function refresh() {
        list = await memory.list();
    }
    async function create() {
        await memory.upsert(form);
        form = { key: '', value: '' };
        creating = false;
        await refresh();
    }
    async function del(id: string) {
        if (!confirm('Supprimer cette mémoire ?')) return;
        await memory.delete(id);
        await refresh();
    }
    onMount(refresh);
</script>

<header class="flex items-center justify-between px-6 py-5 sm:px-8">
    <div>
        <h1 class="text-2xl font-semibold tracking-tight">Mémoire long-terme</h1>
        <p class="mt-1 text-xs text-neutral-500">
            Faits clé/valeur que les modèles voient automatiquement à chaque conversation.
        </p>
    </div>
    <button
        type="button"
        onclick={() => (creating = !creating)}
        class="flex items-center gap-2 rounded-lg bg-cyan-600 px-3 py-1.5 text-sm font-medium
               text-white hover:bg-cyan-500"
    >
        <Plus size={14} /> Ajouter
    </button>
</header>

<div class="px-6 sm:px-8">
    <HelpPanel title="À quoi sert la mémoire long-terme" storageKey="memory">
        <p class="mb-2">
            Contrairement aux <a href="/docs" class="underline hover:text-white">documents</a>
            (vectoriels, recherchés à la demande), la mémoire est <strong>injectée
            systématiquement</strong> dans le contexte des conversations. Idéal pour les préférences
            stables.
        </p>
        <ul class="ml-4 list-disc space-y-1">
            <li>
                Exemples : <code class="rounded bg-neutral-800 px-1">prenom</code> = Maxime,
                <code class="rounded bg-neutral-800 px-1">langue</code> = français,
                <code class="rounded bg-neutral-800 px-1">ton</code> = direct, sans politesse
                superflue.
            </li>
            <li>
                Évite d’y mettre des secrets ou des données qui changent souvent — ce n’est ni
                chiffré ni horodaté finement.
            </li>
            <li>
                Pour les secrets API, utiliser plutôt la page
                <a class="underline hover:text-white" href="/secrets">Secrets</a>.
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
            placeholder="Clé (ex: nom, langue préférée)"
            bind:value={form.key}
            required
            class="rounded-md border border-neutral-700 bg-neutral-950 px-3 py-2 text-sm"
        />
        <textarea
            placeholder="Valeur"
            bind:value={form.value}
            required
            rows="2"
            class="rounded-md border border-neutral-700 bg-neutral-950 px-3 py-2 text-sm"
        ></textarea>
        <button class="rounded-md bg-cyan-600 px-3 py-2 text-sm font-medium hover:bg-cyan-500"
            >Enregistrer</button
        >
    </form>
{/if}

<div class="space-y-2 px-6 pb-6 sm:px-8">
    {#each list as m (m.id)}
        <article class="rounded-xl border border-neutral-800 bg-neutral-900/60 p-4">
            <div class="mb-1 flex items-center justify-between">
                <p class="font-mono text-xs uppercase tracking-wider text-cyan-400">{m.key}</p>
                <button
                    type="button"
                    onclick={() => del(m.id)}
                    class="rounded p-1 text-neutral-500 hover:bg-red-950 hover:text-red-300"
                >
                    <Trash2 size={12} />
                </button>
            </div>
            <p class="text-sm text-neutral-200">{m.value}</p>
            {#if m.last_used_at}
                <p class="mt-2 text-xs text-neutral-500">
                    Utilisée : {new Date(m.last_used_at).toLocaleString('fr-FR')}
                </p>
            {/if}
        </article>
    {:else}
        <p class="text-sm text-neutral-500">Aucune mémoire. Stockez les faits importants.</p>
    {/each}
</div>
