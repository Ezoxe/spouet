<script lang="ts">
    import { onMount } from 'svelte';
    import { rag, type DocumentOut } from '$lib/api';
    import { Trash2, Upload, FileText } from 'lucide-svelte';
    import HelpPanel from '$lib/components/HelpPanel.svelte';

    let list: DocumentOut[] = $state([]);
    let uploading = $state(false);

    async function refresh() {
        list = await rag.list();
    }
    async function onFile(e: Event) {
        const input = e.target as HTMLInputElement;
        const file = input.files?.[0];
        if (!file) return;
        uploading = true;
        try {
            await rag.upload(file);
            await refresh();
        } finally {
            uploading = false;
            input.value = '';
        }
    }
    async function del(id: string) {
        if (!confirm('Supprimer ce document ?')) return;
        await rag.delete(id);
        await refresh();
    }
    function fmt(b: number) {
        if (b < 1024) return `${b} B`;
        if (b < 1024 * 1024) return `${(b / 1024).toFixed(1)} KB`;
        return `${(b / 1024 / 1024).toFixed(1)} MB`;
    }
    onMount(refresh);
</script>

<header class="flex items-center justify-between px-6 py-5 sm:px-8">
    <div>
        <h1 class="text-2xl font-semibold tracking-tight">Documents (RAG)</h1>
        <p class="mt-1 text-xs text-neutral-500">
            Base de connaissances vectorielle interrogée automatiquement par les modèles.
        </p>
    </div>
    <label
        class="flex cursor-pointer items-center gap-2 rounded-lg bg-cyan-600 px-3 py-1.5 text-sm
               font-medium text-white hover:bg-cyan-500"
        class:opacity-50={uploading}
    >
        <Upload size={14} />
        {uploading ? 'Upload…' : 'Importer'}
        <input type="file" accept=".pdf,.txt,.md" hidden onchange={onFile} disabled={uploading} />
    </label>
</header>

<div class="px-6 sm:px-8">
    <HelpPanel title="Comment fonctionne le RAG" storageKey="docs">
        <p class="mb-2">
            À l’upload, Spouet découpe ton fichier en chunks, les embed avec
            <code class="rounded bg-neutral-800 px-1">nomic-embed-text</code> (via un node Ollama
            qui héberge le modèle), et stocke les vecteurs dans PGVector.
        </p>
        <ul class="ml-4 list-disc space-y-1">
            <li>
                Formats supportés : <code class="rounded bg-neutral-800 px-1">.pdf</code>,
                <code class="rounded bg-neutral-800 px-1">.md</code>,
                <code class="rounded bg-neutral-800 px-1">.txt</code>.
            </li>
            <li>
                Statut <span class="text-amber-400">processing</span> = ingestion en cours côté
                worker Celery,
                <span class="text-emerald-400">ready</span> = prêt à être recherché,
                <span class="text-red-400">failed</span> = consulter les logs backend.
            </li>
            <li>
                <strong>Prérequis</strong> : au moins un node Ollama doit avoir
                <code class="rounded bg-neutral-800 px-1">nomic-embed-text</code> installé
                (<code class="rounded bg-neutral-800 px-1">ollama pull nomic-embed-text</code>),
                sans quoi l’ingestion échoue.
            </li>
            <li>
                Les modèles ne « voient » pas tes documents tant que tu ne les actives pas via la
                conversation : ils sont récupérés à la demande par similarité avec la question.
            </li>
        </ul>
    </HelpPanel>
</div>

<div class="space-y-2 px-6 pb-6 sm:px-8">
    {#each list as d (d.id)}
        <article
            class="flex items-center gap-3 rounded-xl border border-neutral-800 bg-neutral-900/60 p-3"
        >
            <FileText size={20} class="shrink-0 text-neutral-500" />
            <div class="min-w-0 flex-1">
                <p class="truncate font-medium text-neutral-100">{d.title}</p>
                <p class="text-xs text-neutral-500">
                    {d.mime} · {fmt(d.bytes)} ·
                    <span
                        class:text-emerald-400={d.status === 'ready'}
                        class:text-amber-400={d.status === 'processing'}
                        class:text-red-400={d.status === 'failed'}
                    >
                        {d.status}
                    </span>
                </p>
            </div>
            <button
                type="button"
                onclick={() => del(d.id)}
                class="rounded p-1.5 text-neutral-500 hover:bg-red-950 hover:text-red-300"
            >
                <Trash2 size={14} />
            </button>
        </article>
    {:else}
        <p class="text-sm text-neutral-500">
            Aucun document. Importer un PDF, MD ou TXT pour le rendre interrogeable.
        </p>
    {/each}
</div>
