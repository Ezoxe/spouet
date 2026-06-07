<script lang="ts">
    import { onMount } from 'svelte';
    import { goto } from '$app/navigation';
    import { conversations, auth, type ConversationOut } from '$lib/api';
    import { toast } from '$lib/toast.svelte';
    import HelpPanel from '$lib/components/HelpPanel.svelte';
    import { Plus, MessageSquare, Trash2, Search, X, Tag } from 'lucide-svelte';

    let convs: ConversationOut[] = $state([]);
    let searchQuery = $state('');
    let activeTag: string | null = $state(null);
    let activeModel = $state('');
    let allTags: string[] = $state([]);
    let modelOptions: string[] = $state([]);
    let searchTimer: ReturnType<typeof setTimeout> | null = null;

    const hasFilters = $derived(!!searchQuery.trim() || !!activeTag || !!activeModel);

    async function refresh() {
        convs = await conversations.list(searchQuery.trim() || undefined, {
            tag: activeTag ?? undefined,
            model: activeModel || undefined
        });
    }

    // Facettes (tags + modèles distincts) calculées sur l'ensemble non filtré.
    async function loadFacets() {
        allTags = await conversations.tags().catch(() => []);
        const all = await conversations.list().catch(() => []);
        modelOptions = [...new Set(all.map((c) => c.model_pref).filter((m): m is string => !!m))].sort();
    }

    function onSearchInput() {
        if (searchTimer) clearTimeout(searchTimer);
        searchTimer = setTimeout(refresh, 180);
    }
    function toggleTag(t: string) {
        activeTag = activeTag === t ? null : t;
        refresh();
    }
    function clearFilters() {
        searchQuery = '';
        activeTag = null;
        activeModel = '';
        refresh();
    }

    async function newConv() {
        // Le backend remplit model_pref = user.default_model si on n'envoie rien.
        // localStorage sert juste de fallback offline / pré-migration.
        const payload: { title: string; model_pref?: string } = { title: 'Nouvelle conversation' };
        try {
            const me = await auth.me();
            if (me.default_model) payload.model_pref = me.default_model;
        } catch {
            const lm = typeof localStorage !== 'undefined' ? localStorage.getItem('spouet:default_model') : '';
            if (lm) payload.model_pref = lm;
        }
        const c = await conversations.create(payload);
        goto(`/chat/${c.id}`);
    }

    async function del(ev: Event, c: ConversationOut) {
        ev.preventDefault();
        ev.stopPropagation();
        if (!confirm(`Supprimer « ${c.title} » ?`)) return;
        try {
            await conversations.delete(c.id);
            await refresh();
            await loadFacets();
        } catch {
            toast.error('Suppression impossible');
        }
    }

    onMount(() => {
        loadFacets();
        refresh();
    });
</script>

<header class="flex items-center justify-between px-6 py-5 sm:px-8">
    <div>
        <h1 class="text-2xl font-semibold tracking-tight">Conversations</h1>
        <p class="mt-1 text-xs text-neutral-500">
            Tes échanges avec les modèles. Filtre par titre, tag ou modèle ; le titre et les tags
            sont générés automatiquement au fil de la discussion.
        </p>
    </div>
    <button
        type="button"
        onclick={newConv}
        class="flex items-center gap-2 rounded-lg border border-cyan-500/50 bg-[var(--color-bg-1)] px-3 py-1.5 text-sm font-medium
               text-[var(--color-accent)] hover:bg-[var(--color-bg-2)]"
    >
        <Plus size={14} /> Nouvelle
    </button>
</header>

<div class="flex flex-wrap items-center gap-2 px-6 pb-3 sm:px-8">
    <div class="relative min-w-[14rem] flex-1 sm:max-w-md">
        <Search size={14} class="absolute left-3 top-1/2 -translate-y-1/2 text-neutral-500" />
        <input
            type="search"
            placeholder="Rechercher dans titre + messages…"
            bind:value={searchQuery}
            oninput={onSearchInput}
            class="w-full rounded-lg border border-neutral-800 bg-neutral-900/60 py-2 pl-9 pr-9 text-sm
                   placeholder:text-neutral-600 focus:border-cyan-500/40 focus:outline-none"
        />
        {#if searchQuery}
            <button
                type="button"
                onclick={() => {
                    searchQuery = '';
                    refresh();
                }}
                class="absolute right-2 top-1/2 -translate-y-1/2 rounded p-1 text-neutral-500 hover:bg-neutral-800 hover:text-neutral-300"
                aria-label="Effacer la recherche"
            >
                <X size={12} />
            </button>
        {/if}
    </div>

    <select
        bind:value={activeModel}
        onchange={refresh}
        class="rounded-lg border border-neutral-800 bg-neutral-900/60 py-2 pl-3 pr-8 text-sm
               focus:border-cyan-500/40 focus:outline-none"
        title="Filtrer par modèle"
    >
        <option value="">Tous les modèles</option>
        {#each modelOptions as m}
            <option value={m}>{m}</option>
        {/each}
    </select>

    {#if hasFilters}
        <button
            type="button"
            onclick={clearFilters}
            class="flex items-center gap-1 rounded-lg border border-neutral-800 px-2.5 py-2 text-xs text-neutral-400 hover:bg-neutral-800 hover:text-neutral-200"
        >
            <X size={12} /> Effacer les filtres
        </button>
    {/if}
</div>

{#if allTags.length}
    <div class="flex flex-wrap items-center gap-1.5 px-6 pb-3 sm:px-8">
        <Tag size={13} class="text-neutral-500" />
        {#each allTags as t}
            <button
                type="button"
                onclick={() => toggleTag(t)}
                class="rounded-full border px-2.5 py-0.5 text-xs transition
                       {activeTag === t
                    ? 'border-cyan-500/60 bg-cyan-500/15 text-cyan-300'
                    : 'border-neutral-700 text-neutral-400 hover:bg-neutral-800 hover:text-neutral-200'}"
            >
                {t}
            </button>
        {/each}
    </div>
{/if}

<div class="px-6 pb-6 sm:px-8">
    <HelpPanel title="Comment ça marche" storageKey="chat-list" defaultOpen={false}>
        <ul class="ml-4 list-disc space-y-1">
            <li>
                Crée une conversation, choisis un modèle (haut-droite de la conversation), tape ton
                prompt.
            </li>
            <li>
                Le <strong>titre</strong> et les <strong>tags</strong> sont générés automatiquement après
                les premiers échanges — utilise-les pour filtrer ici.
            </li>
            <li>
                Spouet route automatiquement vers le node Ollama qui a le modèle et la VRAM
                disponible — tu peux le voir s’afficher en cyan en haut une fois la réponse lancée.
            </li>
            <li>
                Si le modèle supporte le tool calling, l’assistant peut appeler des
                <a class="underline hover:text-white" href="/tools">tools</a> sandboxés (web fetch,
                exécution Python, diagnostic réseau, etc.).
            </li>
        </ul>
    </HelpPanel>

    <div class="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
        {#each convs as c (c.id)}
            <div
                class="group relative rounded-xl border border-neutral-800 bg-neutral-900/60 transition-all
                       hover:-translate-y-0.5 hover:border-neutral-700 hover:bg-neutral-900"
            >
                <a href="/chat/{c.id}" class="block p-4">
                    <div class="mb-2 flex items-center gap-2 text-neutral-400">
                        <MessageSquare size={14} />
                        <span class="text-xs">{new Date(c.updated_at).toLocaleString('fr-FR')}</span>
                    </div>
                    <h3 class="line-clamp-2 pr-6 font-medium text-neutral-100">{c.title}</h3>
                    {#if c.model_pref}
                        <p class="mt-2 text-xs text-neutral-500">Modèle : {c.model_pref}</p>
                    {/if}
                </a>
                {#if c.tags?.length}
                    <div class="flex flex-wrap gap-1 px-4 pb-3">
                        {#each c.tags as t}
                            <button
                                type="button"
                                onclick={(e) => {
                                    e.preventDefault();
                                    e.stopPropagation();
                                    toggleTag(t);
                                }}
                                class="rounded-full px-2 py-0.5 text-[10px] transition
                                       {activeTag === t
                                    ? 'bg-cyan-500/20 text-cyan-300'
                                    : 'bg-neutral-800/70 text-neutral-400 hover:bg-neutral-700 hover:text-neutral-200'}"
                            >
                                {t}
                            </button>
                        {/each}
                    </div>
                {/if}
                <button
                    type="button"
                    onclick={(ev) => del(ev, c)}
                    class="absolute right-3 top-3 hidden rounded p-1.5 text-neutral-500
                           hover:bg-red-950 hover:text-red-300 group-hover:block"
                    title="Supprimer cette conversation"
                    aria-label="Supprimer cette conversation"
                >
                    <Trash2 size={14} />
                </button>
            </div>
        {:else}
            <p class="col-span-full text-sm text-neutral-500">
                {hasFilters
                    ? 'Aucune conversation ne correspond à ces filtres.'
                    : 'Aucune conversation. Clique sur « Nouvelle » pour démarrer.'}
            </p>
        {/each}
    </div>
</div>
