<script lang="ts">
    import { Send, Loader2 } from 'lucide-svelte';

    interface Props {
        disabled?: boolean;
        placeholder?: string;
        onsend: (text: string) => void;
    }
    let { disabled = false, placeholder = 'Écrivez votre message…', onsend }: Props = $props();

    let text = $state('');
    let textarea: HTMLTextAreaElement | undefined = $state();

    function autoresize() {
        if (!textarea) return;
        textarea.style.height = 'auto';
        textarea.style.height = `${Math.min(textarea.scrollHeight, 220)}px`;
    }

    function submit(e?: Event) {
        e?.preventDefault();
        const t = text.trim();
        if (!t || disabled) return;
        onsend(t);
        text = '';
        autoresize();
    }

    function onKey(e: KeyboardEvent) {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            submit();
        }
    }

    const canSend = $derived(!disabled && text.trim().length > 0);
</script>

<form
    onsubmit={submit}
    class="border-t border-[var(--color-border-subtle)] bg-[color-mix(in_oklch,var(--color-bg-0)_85%,transparent)] p-3 backdrop-blur"
>
    <div class="mx-auto max-w-3xl">
        <div
            class="group flex items-end gap-2 rounded-2xl border border-[var(--color-border)]
                   bg-[var(--color-bg-1)] p-1.5 transition-all
                   focus-within:border-cyan-500/40 focus-within:shadow-[0_0_0_4px_oklch(0.55_0.18_210/0.08)]"
        >
            <textarea
                bind:this={textarea}
                bind:value={text}
                oninput={autoresize}
                onkeydown={onKey}
                rows="1"
                {placeholder}
                {disabled}
                class="max-h-[220px] flex-1 resize-none bg-transparent px-3 py-2 text-sm
                       leading-relaxed text-neutral-100 placeholder:text-neutral-600
                       focus:outline-none disabled:opacity-50"
            ></textarea>
            <button
                type="submit"
                disabled={!canSend}
                aria-label="Envoyer"
                class="grid h-9 w-9 place-items-center rounded-xl
                       bg-gradient-to-br from-cyan-500 to-cyan-700 text-white
                       shadow-[0_4px_16px_-4px_oklch(0.55_0.18_210/0.6)]
                       transition-all hover:scale-105 active:scale-95
                       disabled:opacity-30 disabled:hover:scale-100 disabled:shadow-none"
                title="Envoyer (⏎)"
            >
                {#if disabled}
                    <Loader2 size={16} class="animate-spin" />
                {:else}
                    <Send size={16} />
                {/if}
            </button>
        </div>
        <p class="mt-2 px-2 text-[10px] text-neutral-600">
            <kbd class="rounded bg-neutral-800 px-1 py-0.5">Entrée</kbd> envoyer ·
            <kbd class="rounded bg-neutral-800 px-1 py-0.5">Maj+Entrée</kbd> nouvelle ligne
        </p>
    </div>
</form>
