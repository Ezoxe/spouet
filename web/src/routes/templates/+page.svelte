<script lang="ts">
    import { onMount } from 'svelte';
    import { promptTemplates, type PromptTemplateOut } from '$lib/api';
    import { toast } from '$lib/toast.svelte';
    import HelpPanel from '$lib/components/HelpPanel.svelte';
    import { Plus, Trash2, Save, FileText } from 'lucide-svelte';

    let list: PromptTemplateOut[] = $state([]);
    let editing: { id: string | null; name: string; shortcut: string; content: string } = $state({
        id: null,
        name: '',
        shortcut: '',
        content: ''
    });

    async function refresh() {
        try {
            list = await promptTemplates.list();
        } catch {
            list = [];
        }
    }

    function startCreate() {
        editing = { id: null, name: '', shortcut: '', content: '' };
    }
    function pick(t: PromptTemplateOut) {
        editing = {
            id: t.id,
            name: t.name,
            shortcut: t.shortcut ?? '',
            content: t.content
        };
    }

    async function save() {
        if (!editing.name.trim() || !editing.content.trim()) {
            toast.error('Nom et contenu requis');
            return;
        }
        try {
            const payload = {
                name: editing.name.trim(),
                content: editing.content,
                shortcut: editing.shortcut.trim() || null
            };
            if (editing.id) {
                await promptTemplates.patch(editing.id, payload);
            } else {
                const created = await promptTemplates.create(payload);
                editing.id = created.id;
            }
            await refresh();
            toast.success('Template enregistré');
        } catch (e) {
            console.error(e);
            toast.error('Échec de l\'enregistrement');
        }
    }

    async function del(t: PromptTemplateOut) {
        if (!confirm(`Supprimer le template « ${t.name} » ?`)) return;
        try {
            await promptTemplates.delete(t.id);
            if (editing.id === t.id) startCreate();
            await refresh();
        } catch {
            toast.error('Suppression impossible');
        }
    }

    onMount(refresh);
</script>

<header class="flex items-center justify-between px-6 py-5 sm:px-8">
    <div>
        <h1 class="text-2xl font-semibold tracking-tight">Templates de prompts</h1>
        <p class="mt-1 text-xs text-neutral-500">
            Bouts de texte réutilisables, accessibles depuis le composer de chaque conversation.
        </p>
    </div>
    <button
        type="button"
        onclick={startCreate}
        class="flex items-center gap-2 rounded-lg border border-cyan-500/50 bg-[var(--color-bg-1)] px-3 py-1.5 text-sm font-medium
               text-[var(--color-accent)] hover:bg-[var(--color-bg-2)]"
    >
        <Plus size={14} /> Nouveau
    </button>
</header>

<div class="px-6 pb-3 sm:px-8">
    <HelpPanel title="À propos des templates" storageKey="templates" defaultOpen={false}>
        <ul class="ml-4 list-disc space-y-1">
            <li>Clique « Nouveau », remplis nom + contenu, puis enregistre.</li>
            <li>
                Le champ <strong>raccourci</strong> (optionnel) — ex. <code>/résumé</code> — sert à
                identifier rapidement le template dans le composer.
            </li>
            <li>
                Dans une conversation, le bouton <FileText size={12} class="inline" /> à gauche du composer
                ouvre la liste des templates ; cliquer en insère le contenu.
            </li>
        </ul>
    </HelpPanel>
</div>

<div class="grid gap-3 px-6 pb-6 sm:grid-cols-2 sm:px-8">
    <section class="rounded-xl border border-neutral-800 bg-neutral-900/60 p-4">
        <h2 class="mb-3 text-sm font-medium uppercase tracking-wider text-neutral-400">
            {editing.id ? 'Éditer' : 'Nouveau template'}
        </h2>
        <div class="space-y-2">
            <label class="block text-xs text-neutral-400">
                Nom
                <input
                    type="text"
                    bind:value={editing.name}
                    placeholder="Résumé pro"
                    class="mt-1 w-full rounded-md border border-neutral-700 bg-neutral-950 px-2 py-1.5 text-sm focus:border-cyan-500/40 focus:outline-none"
                />
            </label>
            <label class="block text-xs text-neutral-400">
                Raccourci (optionnel)
                <input
                    type="text"
                    bind:value={editing.shortcut}
                    placeholder="/résumé"
                    class="mt-1 w-full rounded-md border border-neutral-700 bg-neutral-950 px-2 py-1.5 text-sm focus:border-cyan-500/40 focus:outline-none"
                />
            </label>
            <label class="block text-xs text-neutral-400">
                Contenu
                <textarea
                    bind:value={editing.content}
                    rows="10"
                    placeholder="Résume le texte ci-dessous en 5 puces…"
                    class="mt-1 w-full rounded-md border border-neutral-700 bg-neutral-950 px-2 py-1.5 text-sm focus:border-cyan-500/40 focus:outline-none"
                ></textarea>
            </label>
            <button
                type="button"
                onclick={save}
                class="flex items-center gap-2 rounded-lg bg-cyan-600 px-3 py-1.5 text-sm text-white hover:bg-cyan-500"
            >
                <Save size={14} /> Enregistrer
            </button>
        </div>
    </section>

    <section class="rounded-xl border border-neutral-800 bg-neutral-900/60 p-4">
        <h2 class="mb-3 text-sm font-medium uppercase tracking-wider text-neutral-400">
            Mes templates ({list.length})
        </h2>
        <div class="space-y-1.5">
            {#each list as t (t.id)}
                <div
                    class="group flex items-center gap-2 rounded-md border border-transparent
                           {editing.id === t.id ? 'border-cyan-500/40 bg-cyan-500/5' : 'hover:border-neutral-700 hover:bg-neutral-900'}"
                >
                    <button
                        type="button"
                        onclick={() => pick(t)}
                        class="min-w-0 flex-1 px-3 py-2 text-left"
                    >
                        <div class="truncate text-sm text-neutral-100">{t.name}</div>
                        <div class="truncate text-xs text-neutral-500">
                            {t.shortcut ?? ''}{t.shortcut ? ' · ' : ''}{t.content.slice(0, 60)}…
                        </div>
                    </button>
                    <button
                        type="button"
                        onclick={() => del(t)}
                        class="mr-2 hidden rounded p-1.5 text-neutral-500 hover:bg-red-950 hover:text-red-300 group-hover:block"
                        aria-label="Supprimer"
                    >
                        <Trash2 size={12} />
                    </button>
                </div>
            {:else}
                <p class="text-xs text-neutral-500">Aucun template — clique « Nouveau » à droite.</p>
            {/each}
        </div>
    </section>
</div>
