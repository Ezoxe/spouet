<script lang="ts">
    import { onMount } from 'svelte';
    import { memory, type MemoryOut, type MemoryFileOut } from '$lib/api';
    import { toast } from '$lib/toast.svelte';
    import { Trash2, Plus, Pin, PinOff, Wand2, FileText, Pencil, Save, X, Eye } from 'lucide-svelte';
    import HelpPanel from '$lib/components/HelpPanel.svelte';
    import MemoryWizard from '$lib/components/MemoryWizard.svelte';

    // --- Fichiers mémoire (.md) ---
    let files: MemoryFileOut[] = $state([]);
    let editing: { name: string; content: string; isNew: boolean } | null = $state(null);
    let saving = $state(false);

    // --- Identité key/value (épinglés → persona) ---
    let list: MemoryOut[] = $state([]);
    let creating = $state(false);
    let wizardOpen = $state(false);
    let form = $state({ key: '', value: '' });

    async function refreshFiles() {
        files = await memory.listFiles().catch(() => []);
    }
    async function refresh() {
        list = await memory.list().catch(() => []);
    }

    async function newFile() {
        editing = { name: '', content: '# Titre\n\n', isNew: true };
    }
    async function openFile(name: string) {
        try {
            const f = await memory.readFile(name);
            editing = { name: f.name, content: f.content, isNew: false };
        } catch {
            toast.error('Lecture impossible');
        }
    }
    async function saveFile() {
        if (!editing) return;
        const name = editing.name.trim();
        if (!name) {
            toast.error('Donne un nom au fichier');
            return;
        }
        saving = true;
        try {
            await memory.writeFile(name, editing.content);
            toast.success('Mémoire enregistrée');
            editing = null;
            await refreshFiles();
        } catch {
            toast.error('Enregistrement impossible (nom/quota/taille ?)');
        } finally {
            saving = false;
        }
    }
    async function delFile(name: string) {
        if (!confirm(`Supprimer le fichier mémoire « ${name} » ?`)) return;
        try {
            await memory.deleteFile(name);
            await refreshFiles();
        } catch {
            toast.error('Suppression impossible');
        }
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

    function fmtDate(iso: string): string {
        return new Date(iso).toLocaleString('fr-FR', {
            day: '2-digit',
            month: 'short',
            hour: '2-digit',
            minute: '2-digit'
        });
    }

    onMount(() => {
        refreshFiles();
        refresh();
    });
</script>

<header class="flex items-center justify-between px-6 py-5 sm:px-8">
    <div>
        <h1 class="text-2xl font-semibold tracking-tight">Mémoire long-terme</h1>
        <p class="mt-1 text-xs text-neutral-500">
            Des fichiers Markdown que l'IA lit <em>à la demande</em> (et que tu peux éditer ici).
        </p>
    </div>
    <button
        type="button"
        onclick={newFile}
        class="flex items-center gap-2 rounded-lg bg-cyan-600 px-3 py-1.5 text-sm font-medium
               text-white hover:bg-cyan-500"
    >
        <Plus size={14} /> Nouveau fichier
    </button>
</header>

<div class="px-6 sm:px-8">
    <HelpPanel title="Comment marche la mémoire" storageKey="memory-md">
        <ul class="mb-2 ml-4 list-disc space-y-1">
            <li>
                <strong>Fichiers .md</strong> : chaque souvenir est un fichier Markdown. L'IA voit la
                <em>liste</em> (noms + descriptions) dans son contexte et <strong>lit/écrit</strong> un
                fichier seulement quand c'est utile (tools <code>memory_read</code> / <code>memory_write</code>).
                Contexte léger, pas de dump systématique.
            </li>
            <li>
                <strong>Identité (épinglée)</strong> plus bas : ~6 faits (prénom, nom de l'IA, ton…)
                injectés à <em>chaque</em> conversation pour la persona. L'<strong>Onboarding</strong> les remplit.
            </li>
        </ul>
        <p>
            Évite d'y mettre des secrets — ce n'est pas chiffré. Pour les clés API, utilise plutôt la
            page <a class="underline hover:text-white" href="/secrets">Secrets</a>.
        </p>
    </HelpPanel>
</div>

<!-- Éditeur de fichier .md -->
{#if editing}
    <div class="mx-6 mb-4 rounded-xl border border-cyan-500/30 bg-neutral-900 p-4 sm:mx-8">
        <div class="mb-3 flex items-center gap-2">
            <FileText size={15} class="text-cyan-400" />
            {#if editing.isNew}
                <input
                    placeholder="nom-du-fichier (ex: preferences, projet-x)"
                    bind:value={editing.name}
                    class="flex-1 rounded-md border border-neutral-700 bg-neutral-950 px-3 py-1.5 text-sm
                           focus:border-cyan-500/50 focus:outline-none"
                />
            {:else}
                <span class="flex-1 font-mono text-sm text-cyan-300">{editing.name}.md</span>
            {/if}
            <button
                type="button"
                onclick={() => (editing = null)}
                class="rounded p-1.5 text-neutral-400 hover:bg-neutral-800 hover:text-neutral-100"
                aria-label="Annuler"
            >
                <X size={15} />
            </button>
            <button
                type="button"
                onclick={saveFile}
                disabled={saving}
                class="flex items-center gap-1.5 rounded-md bg-cyan-600 px-3 py-1.5 text-sm font-medium
                       text-white hover:bg-cyan-500 disabled:opacity-50"
            >
                <Save size={14} /> Enregistrer
            </button>
        </div>
        <textarea
            bind:value={editing.content}
            rows="12"
            placeholder="# Titre&#10;&#10;Contenu Markdown du souvenir…"
            class="w-full rounded-md border border-neutral-700 bg-neutral-950 px-3 py-2 font-mono text-sm
                   leading-relaxed focus:border-cyan-500/50 focus:outline-none"
        ></textarea>
    </div>
{/if}

<!-- Liste des fichiers .md -->
<div class="px-6 pb-2 sm:px-8">
    {#if files.length === 0}
        <p class="rounded-xl border border-dashed border-neutral-800 px-4 py-6 text-center text-sm text-neutral-500">
            Aucun fichier mémoire. Crée-en un, ou laisse l'IA en créer pendant vos conversations.
        </p>
    {:else}
        <div class="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
            {#each files as f (f.name)}
                <article class="group flex flex-col rounded-xl border border-neutral-800 bg-neutral-900/60 p-4 transition hover:border-neutral-700">
                    <div class="mb-1 flex items-start justify-between gap-2">
                        <div class="flex min-w-0 items-center gap-1.5">
                            <FileText size={13} class="shrink-0 text-cyan-400" />
                            <span class="truncate font-mono text-xs text-cyan-300">{f.name}</span>
                        </div>
                        <div class="flex shrink-0 items-center gap-0.5 opacity-0 transition group-hover:opacity-100">
                            <button
                                type="button"
                                onclick={() => openFile(f.name)}
                                class="rounded p-1 text-neutral-500 hover:bg-neutral-800 hover:text-cyan-300"
                                title="Éditer"
                                aria-label="Éditer"
                            >
                                <Pencil size={12} />
                            </button>
                            <button
                                type="button"
                                onclick={() => delFile(f.name)}
                                class="rounded p-1 text-neutral-500 hover:bg-red-950 hover:text-red-300"
                                title="Supprimer"
                                aria-label="Supprimer"
                            >
                                <Trash2 size={12} />
                            </button>
                        </div>
                    </div>
                    <p class="font-medium text-sm text-neutral-200">{f.title}</p>
                    <p class="mt-0.5 line-clamp-2 text-xs text-neutral-500">{f.description}</p>
                    <button
                        type="button"
                        onclick={() => openFile(f.name)}
                        class="mt-3 inline-flex items-center gap-1 self-start text-[11px] text-neutral-500 hover:text-cyan-300"
                    >
                        <Eye size={11} /> ouvrir · {fmtDate(f.updated_at)}
                    </button>
                </article>
            {/each}
        </div>
    {/if}
</div>

<!-- Identité / réglages épinglés (persona) -->
<div class="mt-6 flex items-center justify-between border-t border-neutral-800 px-6 pt-5 sm:px-8">
    <div>
        <h2 class="text-sm font-semibold text-neutral-200">Identité &amp; réglages</h2>
        <p class="mt-0.5 text-xs text-neutral-500">
            Faits clé/valeur épinglés, injectés à chaque conversation pour personnaliser la persona.
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
            class="flex items-center gap-2 rounded-lg border border-neutral-700 px-3 py-1.5 text-sm
                   text-neutral-300 hover:bg-neutral-800"
        >
            <Plus size={14} /> Ajouter
        </button>
    </div>
</div>

{#if wizardOpen}
    <MemoryWizard existing={list} onclose={() => (wizardOpen = false)} onsaved={refresh} />
{/if}

{#if creating}
    <form
        onsubmit={(e) => {
            e.preventDefault();
            create();
        }}
        class="mx-6 my-4 grid gap-3 rounded-xl border border-neutral-800 bg-neutral-900 p-4 sm:mx-8"
    >
        <input
            placeholder="Clé (ex: prenom, langue)"
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
        <button class="rounded-md bg-cyan-600 px-3 py-2 text-sm font-medium hover:bg-cyan-500">
            Enregistrer
        </button>
    </form>
{/if}

<div class="space-y-2 px-6 pb-10 pt-4 sm:px-8">
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
                        title={m.pinned ? 'Désépingler' : 'Épingler (toujours injectée)'}
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
        </article>
    {:else}
        <p class="text-sm text-neutral-500">
            Aucun réglage d'identité. Lance l'<button
                type="button"
                class="underline hover:text-cyan-300"
                onclick={() => (wizardOpen = true)}>Onboarding</button
            >.
        </p>
    {/each}
</div>
