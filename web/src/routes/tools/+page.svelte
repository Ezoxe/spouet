<script lang="ts">
    import { onMount } from 'svelte';
    import { tools as toolsApi, type ToolOut } from '$lib/api';
    import { toast } from '$lib/toast.svelte';
    import { Trash2 } from 'lucide-svelte';
    import HelpPanel from '$lib/components/HelpPanel.svelte';

    let list: ToolOut[] = $state([]);

    async function refresh() {
        list = await toolsApi.list();
    }
    async function toggle(t: ToolOut) {
        const updated = await toolsApi.patch(t.id, { enabled: !t.enabled });
        list = list.map((x) => (x.id === t.id ? updated : x));
    }
    async function uninstall(t: ToolOut) {
        if (!confirm(`Désinstaller le tool « ${t.name} » ? (l'image Docker n'est pas supprimée)`))
            return;
        try {
            await toolsApi.delete(t.id);
            list = list.filter((x) => x.id !== t.id);
        } catch {
            toast.error('Désinstallation impossible');
        }
    }
    onMount(refresh);
</script>

<header class="flex items-center justify-between px-6 py-5 sm:px-8">
    <div>
        <h1 class="text-2xl font-semibold tracking-tight">Tools</h1>
        <p class="mt-1 text-xs text-neutral-500">
            Capacités exécutables que les modèles peuvent appeler pendant une conversation
            (web fetch, exécution Python, lecture FS…).
        </p>
    </div>
</header>

<div class="px-6 pb-6 sm:px-8">
    <HelpPanel title="Comment fonctionnent les tools" storageKey="tools">
        <p class="mb-2">
            Chaque tool tourne dans un conteneur Docker <strong>jetable</strong> (un par appel)
            avec <code class="rounded bg-neutral-800 px-1">--read-only</code>,
            <code class="rounded bg-neutral-800 px-1">--cap-drop=ALL</code>, mémoire/CPU/timeout
            limités. Par défaut, pas de réseau (<code class="rounded bg-neutral-800 px-1"
                >network: none</code
            >).
        </p>
        <ul class="ml-4 list-disc space-y-1">
            <li>
                <strong>Activer / désactiver</strong> via le toggle de chaque carte. Désactivé = le
                modèle ne peut plus l’appeler.
            </li>
            <li>
                <strong>approval</strong> = chaque appel demande ta validation HITL avant
                exécution. Recommandé pour tout tool ayant accès au réseau.
            </li>
            <li>
                <strong>Installer un nouveau tool</strong> :
                <code class="rounded bg-neutral-800 px-1">
                    spouet-admin tools install ./tools/registry/&lt;slug&gt; --build
                </code> sur le serveur Spouet (Debian) — ça build l’image et insère la ligne en DB.
            </li>
            <li>
                Pour développer ton propre tool : créer un dossier dans
                <code class="rounded bg-neutral-800 px-1">tools/registry/&lt;slug&gt;</code>
                avec <code>manifest.yaml</code>, <code>Dockerfile</code>, <code>run.py</code>
                (lit JSON sur stdin, écrit JSON sur stdout). Voir <code>web-fetch</code> comme
                exemple.
            </li>
            <li>
                Seuls les modèles taggés <code class="rounded bg-cyan-900/40 px-1">tools</code> sur
                la page Nodes peuvent réellement les invoquer (Llama 3.1+, Qwen 2.5+, Mistral,
                etc.).
            </li>
        </ul>
    </HelpPanel>
</div>

<div class="grid gap-3 px-6 pb-6 sm:grid-cols-2 sm:px-8">
    {#each list as t (t.id)}
        <article class="rounded-xl border border-neutral-800 bg-neutral-900/60 p-4">
            <div class="mb-2 flex items-center justify-between">
                <div>
                    <h3 class="font-medium">{t.name}</h3>
                    <p class="font-mono text-xs text-neutral-500">{t.slug} · v{t.version}</p>
                </div>
                <label class="relative inline-flex cursor-pointer items-center">
                    <input
                        type="checkbox"
                        checked={t.enabled}
                        onchange={() => toggle(t)}
                        class="peer sr-only"
                    />
                    <div
                        class="h-5 w-9 rounded-full bg-neutral-700 transition peer-checked:bg-cyan-600"
                    ></div>
                    <div
                        class="absolute left-0.5 top-0.5 h-4 w-4 rounded-full bg-white transition
                               peer-checked:translate-x-4"
                    ></div>
                </label>
            </div>
            {#if t.description}
                <p class="mb-3 text-sm text-neutral-400">{t.description}</p>
            {/if}
            <div class="flex flex-wrap items-center gap-2 text-xs">
                <span class="rounded bg-neutral-800 px-2 py-0.5 text-neutral-400">
                    network: <span class="font-mono">{t.network_mode}</span>
                </span>
                <span class="rounded bg-neutral-800 px-2 py-0.5 text-neutral-400">
                    timeout: {t.timeout_s}s
                </span>
                {#if t.requires_approval}
                    <span class="rounded bg-amber-900/40 px-2 py-0.5 text-amber-300">approval</span>
                {/if}
                <button
                    type="button"
                    onclick={() => uninstall(t)}
                    class="ml-auto rounded p-1 text-neutral-500 hover:bg-red-950 hover:text-red-300"
                    title="Désinstaller le tool"
                    aria-label="Désinstaller le tool"
                >
                    <Trash2 size={13} />
                </button>
            </div>
        </article>
    {:else}
        <p class="col-span-full text-sm text-neutral-500">Aucun tool installé.</p>
    {/each}
</div>
