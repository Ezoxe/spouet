<script lang="ts">
    import type { Snippet } from 'svelte';
    import type { Component } from 'svelte';

    interface Props {
        icon?: Component;
        title: string;
        description?: string;
        action?: Snippet;
    }
    let { icon: Icon, title, description, action }: Props = $props();
</script>

<div class="flex flex-col items-center justify-center gap-3 py-16 text-center">
    {#if Icon}
        <div
            class="grid h-12 w-12 place-items-center rounded-2xl border border-neutral-800
                   bg-neutral-900/60 text-neutral-500"
        >
            <Icon size={20} />
        </div>
    {/if}
    <div>
        <p class="text-sm font-medium text-neutral-300">{title}</p>
        {#if description}
            <p class="mt-1 max-w-sm text-xs text-neutral-500">{description}</p>
        {/if}
    </div>
    {#if action}{@render action()}{/if}
</div>
