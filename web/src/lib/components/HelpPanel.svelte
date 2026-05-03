<script lang="ts">
    import { Info, ChevronDown } from 'lucide-svelte';
    import { slide } from 'svelte/transition';

    let {
        title,
        storageKey,
        defaultOpen = true,
        children
    }: {
        title: string;
        storageKey: string;
        defaultOpen?: boolean;
        children: import('svelte').Snippet;
    } = $props();

    function readInitial(): boolean {
        if (typeof localStorage === 'undefined') return defaultOpen;
        const v = localStorage.getItem(`spouet:help:${storageKey}`);
        if (v === null) return defaultOpen;
        return v === '1';
    }

    let open = $state(readInitial());

    function toggle() {
        open = !open;
        if (typeof localStorage !== 'undefined') {
            localStorage.setItem(`spouet:help:${storageKey}`, open ? '1' : '0');
        }
    }
</script>

<section
    class="mb-4 overflow-hidden rounded-xl border border-cyan-900/40 bg-cyan-950/20"
>
    <button
        type="button"
        onclick={toggle}
        class="flex w-full items-center justify-between gap-3 px-4 py-2.5 text-left
               text-sm text-cyan-100 hover:bg-cyan-900/20"
        aria-expanded={open}
    >
        <span class="flex items-center gap-2">
            <Info size={14} class="text-cyan-400" />
            <span class="font-medium">{title}</span>
        </span>
        <ChevronDown
            size={14}
            class="text-cyan-400 transition-transform {open ? 'rotate-180' : ''}"
        />
    </button>
    {#if open}
        <div
            transition:slide={{ duration: 180 }}
            class="border-t border-cyan-900/40 bg-cyan-950/10 px-4 py-3 text-sm
                   leading-relaxed text-neutral-300"
        >
            {@render children()}
        </div>
    {/if}
</section>
