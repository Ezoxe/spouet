<script lang="ts">
    import { onMount } from 'svelte';
    import { goto } from '$app/navigation';
    import { conversations, type ConversationOut } from '$lib/api';
    import { Plus, MessageSquare } from 'lucide-svelte';

    let convs: ConversationOut[] = $state([]);

    async function refresh() {
        convs = await conversations.list();
    }

    async function newConv() {
        const c = await conversations.create({ title: 'Nouvelle conversation' });
        goto(`/chat/${c.id}`);
    }

    onMount(refresh);
</script>

<header class="flex items-center justify-between px-6 py-5 sm:px-8">
    <h1 class="text-2xl font-semibold tracking-tight">Conversations</h1>
    <button
        type="button"
        onclick={newConv}
        class="flex items-center gap-2 rounded-lg bg-cyan-600 px-3 py-1.5 text-sm font-medium
               text-white hover:bg-cyan-500"
    >
        <Plus size={14} /> Nouvelle
    </button>
</header>

<div class="grid gap-2 px-6 pb-6 sm:grid-cols-2 sm:px-8 lg:grid-cols-3">
    {#each convs as c (c.id)}
        <a
            href="/chat/{c.id}"
            class="group rounded-xl border border-neutral-800 bg-neutral-900/60 p-4 transition-all
                   hover:-translate-y-0.5 hover:border-neutral-700 hover:bg-neutral-900"
        >
            <div class="mb-2 flex items-center gap-2 text-neutral-400">
                <MessageSquare size={14} />
                <span class="text-xs">{new Date(c.updated_at).toLocaleString('fr-FR')}</span>
            </div>
            <h3 class="line-clamp-2 font-medium text-neutral-100">{c.title}</h3>
            {#if c.model_pref}
                <p class="mt-2 text-xs text-neutral-500">Modèle : {c.model_pref}</p>
            {/if}
        </a>
    {:else}
        <p class="col-span-full text-sm text-neutral-500">
            Aucune conversation. Cliquez sur "Nouvelle".
        </p>
    {/each}
</div>
