<script lang="ts">
    import { onMount } from 'svelte';
    import { tools as toolsApi, type ToolOut } from '$lib/api';

    let list: ToolOut[] = $state([]);

    async function refresh() {
        list = await toolsApi.list();
    }
    async function toggle(t: ToolOut) {
        const updated = await toolsApi.patch(t.id, { enabled: !t.enabled });
        list = list.map((x) => (x.id === t.id ? updated : x));
    }
    onMount(refresh);
</script>

<header class="flex items-center justify-between px-6 py-5 sm:px-8">
    <h1 class="text-2xl font-semibold tracking-tight">Tools</h1>
    <span class="text-xs text-neutral-500">
        Installer via : <code class="rounded bg-neutral-800 px-1.5 py-0.5"
            >spouet-admin tools install ./tools/registry/&lt;slug&gt; --build</code
        >
    </span>
</header>

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
            <div class="flex flex-wrap gap-2 text-xs">
                <span class="rounded bg-neutral-800 px-2 py-0.5 text-neutral-400">
                    network: <span class="font-mono">{t.network_mode}</span>
                </span>
                <span class="rounded bg-neutral-800 px-2 py-0.5 text-neutral-400">
                    timeout: {t.timeout_s}s
                </span>
                {#if t.requires_approval}
                    <span class="rounded bg-amber-900/40 px-2 py-0.5 text-amber-300">approval</span>
                {/if}
            </div>
        </article>
    {:else}
        <p class="col-span-full text-sm text-neutral-500">Aucun tool installé.</p>
    {/each}
</div>
