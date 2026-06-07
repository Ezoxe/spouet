<script lang="ts">
    import { onMount } from 'svelte';
    import { Wrench, Check, ChevronDown } from 'lucide-svelte';
    import { tools as toolsApi, type ToolOut } from '$lib/api';

    interface Props {
        selected: string[];
        onchange: (slugs: string[]) => void;
        disabled?: boolean;
    }
    let { selected = [], onchange, disabled = false }: Props = $props();

    let open = $state(false);
    let list: ToolOut[] = $state([]);
    let loaded = $state(false);

    async function ensureLoaded() {
        if (loaded) return;
        try {
            list = await toolsApi.list();
        } catch {
            list = [];
        }
        loaded = true;
    }

    function toggle(slug: string) {
        if (selected.includes(slug)) onchange(selected.filter((s) => s !== slug));
        else onchange([...selected, slug]);
    }

    function selectAll() {
        onchange([]);
    }

    onMount(() => {
        // précharge en arrière-plan, sans bloquer
        ensureLoaded();
    });

    const enabledList = $derived(list.filter((t) => t.enabled));
    const label = $derived.by(() => {
        if (selected.length === 0) return 'Tous tools';
        if (selected.length === 1) return selected[0];
        return `${selected.length} tools`;
    });
</script>

<div class="relative">
    <button
        type="button"
        {disabled}
        onclick={() => {
            open = !open;
            if (open) ensureLoaded();
        }}
        class="flex items-center gap-2 rounded-md border px-3 py-1.5 text-sm transition
               hover:border-cyan-500/50 disabled:opacity-50
               {selected.length > 0
                ? 'border-cyan-500/60 bg-cyan-500/10 text-cyan-300'
                : 'border-[var(--color-border)] bg-[var(--color-bg-1)]'}"
        title={selected.length > 0
            ? `Tools restreints à : ${selected.join(', ')}`
            : 'Tous les tools activés sont disponibles dans cette conversation'}
    >
        <Wrench size={14} class="text-cyan-400" />
        <span class="hidden text-xs text-neutral-500 sm:inline">Tools :</span>
        <span class="max-w-[120px] truncate {selected.length > 0 ? 'text-cyan-300' : 'text-neutral-200'}"
            >{label}</span
        >
        <ChevronDown size={14} class="text-neutral-500 transition-transform {open ? 'rotate-180' : ''}" />
    </button>

    {#if open}
        <div
            class="absolute right-0 top-full z-50 mt-2 w-64 rounded-md border border-[var(--color-border-subtle)]
                   bg-[var(--color-bg-1)] p-1 shadow-xl"
        >
            <button
                type="button"
                onclick={selectAll}
                class="flex w-full items-center justify-between rounded px-3 py-2 text-left text-sm
                       {selected.length === 0 ? 'bg-cyan-500/10 text-cyan-400' : 'text-neutral-300 hover:bg-neutral-800'}"
            >
                <span>Tous les tools activés</span>
                {#if selected.length === 0}<Check size={12} />{/if}
            </button>
            <div class="my-1 h-px bg-[var(--color-border-subtle)]"></div>
            {#if !loaded}
                <div class="px-3 py-2 text-xs text-neutral-500">Chargement…</div>
            {:else if enabledList.length === 0}
                <div class="px-3 py-2 text-xs text-neutral-500">Aucun tool actif</div>
            {:else}
                <ul class="max-h-72 overflow-y-auto">
                    {#each enabledList as t (t.id)}
                        {@const checked = selected.includes(t.slug)}
                        <li>
                            <button
                                type="button"
                                onclick={() => toggle(t.slug)}
                                class="flex w-full items-start gap-2 rounded px-3 py-2 text-left text-sm transition
                                       {checked ? 'bg-cyan-500/10' : 'hover:bg-neutral-800'}"
                            >
                                <span
                                    class="mt-0.5 grid h-3.5 w-3.5 shrink-0 place-items-center rounded border
                                           {checked ? 'border-cyan-500 bg-cyan-500' : 'border-neutral-600'}"
                                >
                                    {#if checked}<Check size={10} class="text-white" />{/if}
                                </span>
                                <span class="flex-1 min-w-0">
                                    <span class="block truncate text-neutral-200">{t.name}</span>
                                    <span class="block truncate font-mono text-[10px] text-neutral-500">
                                        {t.slug}
                                    </span>
                                </span>
                            </button>
                        </li>
                    {/each}
                </ul>
            {/if}
        </div>
        <button
            type="button"
            class="fixed inset-0 z-40 cursor-default"
            aria-label="Fermer"
            onclick={() => (open = false)}
        ></button>
    {/if}
</div>
