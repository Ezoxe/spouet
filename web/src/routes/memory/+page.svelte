<script lang="ts">
    import { onMount } from 'svelte';
    import { memory, type MemoryOut } from '$lib/api';
    import { Trash2, Plus, Pin, PinOff, Wand2 } from 'lucide-svelte';
    import HelpPanel from '$lib/components/HelpPanel.svelte';
    import MemoryWizard from '$lib/components/MemoryWizard.svelte';

    let list: MemoryOut[] = $state([]);
    let creating = $state(false);
    let wizardOpen = $state(false);
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
    async function togglePin(m: MemoryOut) {
        await memory.patch(m.id, { pinned: !m.pinned });
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
    <div class="flex items-center gap-2">
        <button
            type="button"
            onclick={() => (wizardOpen = true)}
            class="flex items-center gap-2 rounded-lg border border-cyan-500/30 bg-cyan-500/10
                   px-3 py-1.5 text-sm font-medium text-cyan-300 hover:bg-cyan-500/20"
            title="Onboarding : 6 questions pour personnaliser l'IA"
        >
            <Wand2 size={14} /> Onboarding
        </button>
        <button
            type="button"
            onclick={() => (creating = !creating)}
            class="flex items-center gap-2 rounded-lg bg-cyan-600 px-3 py-1.5 text-sm font-medium
                   text-white hover:bg-cyan-500"
        >
            <Plus size={14} /> Ajouter
        </button>
    </div>
</header>

<div class="px-6 sm:px-8">
    <HelpPanel title="À quoi sert la mémoire long-terme" storageKey="memory">
        <p class="mb-2">
            Deux niveaux pour ne jamais encombrer le contexte :
        </p>
        <ul class="mb-2 ml-4 list-disc space-y-1">
            <li>
                <strong>Épinglées</strong> (icône
                <Pin size={10} class="inline" />) : injectées <em>à chaque</em> conversation.
                Réservées aux ~6 faits identitaires (prénom, nom de l'IA, totem, ton…).
                L'<strong>Onboarding</strong> les remplit en 6 questions.
            </li>
            <li>
                <strong>Recall</strong> (les autres) : chargées <em>uniquement</em> si pertinentes
                (recherche vectorielle sur le dernier message). Tu peux en stocker autant que tu veux
                sans surcharge.
            </li>
        </ul>
        <p class="mb-2">
            Évite d'y mettre des secrets ou des données très volatiles — ce n'est ni chiffré ni
            horodaté finement. Pour les secrets API, utiliser plutôt la page
            <a class="underline hover:text-white" href="/secrets">Secrets</a>.
        </p>
    </HelpPanel>
</div>

{#if wizardOpen}
    <MemoryWizard
        existing={list}
        onclose={() => (wizardOpen = false)}
        onsaved={refresh}
    />
{/if}

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
        <article
            class="rounded-xl border p-4 {m.pinned
                ? 'border-cyan-500/40 bg-cyan-500/5'
                : 'border-neutral-800 bg-neutral-900/60'}"
        >
            <div class="mb-1 flex items-center justify-between">
                <div class="flex items-center gap-2">
                    {#if m.pinned}
                        <Pin size={11} class="text-cyan-400" />
                    {/if}
                    <p class="font-mono text-xs uppercase tracking-wider text-cyan-400">{m.key}</p>
                </div>
                <div class="flex items-center gap-1">
                    <button
                        type="button"
                        onclick={() => togglePin(m)}
                        class="rounded p-1 text-neutral-500 hover:bg-neutral-800 hover:text-cyan-300"
                        title={m.pinned
                            ? 'Désépingler (passera en recall sémantique)'
                            : 'Épingler (toujours injectée dans le contexte)'}
                        aria-label={m.pinned ? 'Désépingler' : 'Épingler'}
                    >
                        {#if m.pinned}
                            <PinOff size={12} />
                        {:else}
                            <Pin size={12} />
                        {/if}
                    </button>
                    <button
                        type="button"
                        onclick={() => del(m.id)}
                        class="rounded p-1 text-neutral-500 hover:bg-red-950 hover:text-red-300"
                        aria-label="Supprimer"
                    >
                        <Trash2 size={12} />
                    </button>
                </div>
            </div>
            <p class="text-sm text-neutral-200">{m.value}</p>
            {#if m.last_used_at}
                <p class="mt-2 text-xs text-neutral-500">
                    Utilisée : {new Date(m.last_used_at).toLocaleString('fr-FR')}
                </p>
            {/if}
        </article>
    {:else}
        <p class="text-sm text-neutral-500">
            Aucune mémoire. Lance l'<button
                type="button"
                class="underline hover:text-cyan-300"
                onclick={() => (wizardOpen = true)}>Onboarding</button
            > ou ajoute manuellement.
        </p>
    {/each}
</div>
