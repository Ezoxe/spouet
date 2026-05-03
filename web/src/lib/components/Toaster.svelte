<script lang="ts">
    import { fly } from 'svelte/transition';
    import { quintOut } from 'svelte/easing';
    import { CheckCircle2, AlertCircle, Info, AlertTriangle, X } from 'lucide-svelte';
    import { toast } from '$lib/toast';

    const ICONS = {
        success: CheckCircle2,
        error: AlertCircle,
        info: Info,
        warning: AlertTriangle
    } as const;

    const STYLES = {
        success: 'border-emerald-900/50 bg-emerald-950/40 text-emerald-100',
        error: 'border-red-900/50 bg-red-950/40 text-red-100',
        info: 'border-cyan-900/50 bg-cyan-950/40 text-cyan-100',
        warning: 'border-amber-900/50 bg-amber-950/40 text-amber-100'
    } as const;
</script>

<div class="pointer-events-none fixed bottom-4 right-4 z-50 flex w-full max-w-sm flex-col gap-2">
    {#each toast.all as t (t.id)}
        {@const Icon = ICONS[t.kind]}
        <div
            class="pointer-events-auto flex items-start gap-3 rounded-xl border px-4 py-3 shadow-lg
                   backdrop-blur-md {STYLES[t.kind]}"
            in:fly={{ x: 24, duration: 220, easing: quintOut }}
            out:fly={{ x: 24, duration: 180 }}
        >
            <Icon size={16} class="mt-0.5 shrink-0" />
            <p class="flex-1 text-sm">{t.message}</p>
            <button
                type="button"
                onclick={() => toast.dismiss(t.id)}
                class="text-current/60 hover:text-current"
            >
                <X size={14} />
            </button>
        </div>
    {/each}
</div>
