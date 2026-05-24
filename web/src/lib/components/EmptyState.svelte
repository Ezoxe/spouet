<script lang="ts">
    import type { Snippet } from 'svelte';

    interface Props {
        icon?: any;
        title: string;
        description?: string;
        action?: Snippet;
    }
    let { icon: Icon, title, description, action }: Props = $props();
</script>

<div class="flex flex-col items-center justify-center gap-4 py-16 text-center animate-fade-in-up">
    {#if Icon}
        <div class="es-icon">
            <Icon size={22} />
        </div>
    {/if}
    <div>
        <p class="text-sm font-medium text-neutral-200">{title}</p>
        {#if description}
            <p class="mx-auto mt-1.5 max-w-sm text-xs leading-relaxed text-neutral-500">
                {description}
            </p>
        {/if}
    </div>
    {#if action}{@render action()}{/if}
</div>

<style>
    .es-icon {
        position: relative;
        display: grid;
        place-items: center;
        height: 3.5rem;
        width: 3.5rem;
        border-radius: var(--radius-lg);
        color: var(--color-accent);
        background: linear-gradient(
            160deg,
            color-mix(in oklch, var(--color-accent) 14%, var(--color-bg-2)),
            var(--color-bg-1)
        );
        border: 1px solid color-mix(in oklch, var(--color-accent) 22%, transparent);
        box-shadow: 0 0 24px -8px color-mix(in oklch, var(--color-accent) 40%, transparent);
        animation: breathe 5s ease-in-out infinite;
    }
    .es-icon::before {
        content: '';
        position: absolute;
        inset: -40%;
        border-radius: 9999px;
        background: radial-gradient(
            closest-side,
            color-mix(in oklch, var(--color-accent) 22%, transparent),
            transparent 70%
        );
        filter: blur(10px);
        z-index: -1;
        pointer-events: none;
    }
</style>
