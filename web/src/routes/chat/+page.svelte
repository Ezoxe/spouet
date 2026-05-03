<script lang="ts">
    import { onMount } from 'svelte';
    import { goto } from '$app/navigation';
    import { conversations, type ConversationOut } from '$lib/api';
    import { toast } from '$lib/toast.svelte';
    import HelpPanel from '$lib/components/HelpPanel.svelte';
    import { Plus, MessageSquare, Trash2 } from 'lucide-svelte';

    let convs: ConversationOut[] = $state([]);

    async function refresh() {
        convs = await conversations.list();
    }

    async function newConv() {
        const c = await conversations.create({ title: 'Nouvelle conversation' });
        goto(`/chat/${c.id}`);
    }

    async function del(ev: Event, c: ConversationOut) {
        ev.preventDefault();
        ev.stopPropagation();
        if (!confirm(`Supprimer « ${c.title} » ?`)) return;
        try {
            await conversations.delete(c.id);
            await refresh();
        } catch {
            toast.error('Suppression impossible');
        }
    }

    onMount(refresh);
</script>

<header class="flex items-center justify-between px-6 py-5 sm:px-8">
    <div>
        <h1 class="text-2xl font-semibold tracking-tight">Conversations</h1>
        <p class="mt-1 text-xs text-neutral-500">
            Tes échanges avec les modèles. Chaque conversation garde son historique et peut être
            reprise à tout moment.
        </p>
    </div>
    <button
        type="button"
        onclick={newConv}
        class="flex items-center gap-2 rounded-lg bg-cyan-600 px-3 py-1.5 text-sm font-medium
               text-white hover:bg-cyan-500"
    >
        <Plus size={14} /> Nouvelle
    </button>
</header>

<div class="px-6 pb-6 sm:px-8">
    <HelpPanel title="Comment ça marche" storageKey="chat-list" defaultOpen={false}>
        <ul class="ml-4 list-disc space-y-1">
            <li>
                Crée une conversation, choisis un modèle (haut-droite de la conversation), tape ton
                prompt.
            </li>
            <li>
                Spouet route automatiquement vers le node Ollama qui a le modèle et la VRAM
                disponible — tu peux le voir s’afficher en cyan en haut une fois la réponse lancée.
            </li>
            <li>
                Si le modèle supporte le tool calling, l’assistant peut appeler des
                <a class="underline hover:text-white" href="/tools">tools</a> sandboxés (web fetch,
                exécution Python, lecture de fichiers, etc.).
            </li>
            <li>
                Le bouton micro (haut-droite) ouvre le mode vocal : transcription + lecture
                synthétique en streaming.
            </li>
            <li>
                Les conversations apparaissent aussi dans la barre latérale (les 12 plus récentes,
                avec une icône poubelle au survol).
            </li>
        </ul>
    </HelpPanel>

    <div class="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
        {#each convs as c (c.id)}
            <div class="group relative">
                <a
                    href="/chat/{c.id}"
                    class="block rounded-xl border border-neutral-800 bg-neutral-900/60 p-4 transition-all
                           hover:-translate-y-0.5 hover:border-neutral-700 hover:bg-neutral-900"
                >
                    <div class="mb-2 flex items-center gap-2 text-neutral-400">
                        <MessageSquare size={14} />
                        <span class="text-xs">{new Date(c.updated_at).toLocaleString('fr-FR')}</span>
                    </div>
                    <h3 class="line-clamp-2 pr-6 font-medium text-neutral-100">{c.title}</h3>
                    {#if c.model_pref}
                        <p class="mt-2 text-xs text-neutral-500">Modèle : {c.model_pref}</p>
                    {/if}
                </a>
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
                Aucune conversation. Clique sur « Nouvelle » pour démarrer.
            </p>
        {/each}
    </div>
</div>
