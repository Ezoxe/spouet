<script lang="ts">
    import { Send, Loader2, FileText, Check, X } from 'lucide-svelte';
    import { onMount, tick } from 'svelte';
    import { promptTemplates, type PromptTemplateOut } from '$lib/api';

    interface Props {
        disabled?: boolean;
        /** Génération en cours : seul cet état affiche le spinner d'envoi.
         *  `disabled` peut être vrai sans `busy` (ex. aucun modèle sélectionné)
         *  → on ne montre PAS de spinner qui tournerait pour rien. */
        busy?: boolean;
        placeholder?: string;
        onsend: (text: string) => void;
        onready?: (api: { focus: () => void }) => void;
    }
    let {
        disabled = false,
        busy = false,
        placeholder = 'Écrivez votre message…',
        onsend,
        onready
    }: Props = $props();

    let text = $state('');
    let textarea: HTMLTextAreaElement | undefined = $state();
    let templatesOpen = $state(false);
    let templates: PromptTemplateOut[] = $state([]);
    let templatesLoaded = $state(false);
    let lastSent = $state('');

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
        lastSent = t;
        text = '';
        autoresize();
    }

    function focus() {
        textarea?.focus();
    }

    function onKey(e: KeyboardEvent) {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            submit();
            return;
        }
        // ↑ sur composer vide → rappel du dernier prompt envoyé
        if (e.key === 'ArrowUp' && text.length === 0 && lastSent) {
            e.preventDefault();
            text = lastSent;
            tick().then(() => {
                autoresize();
                if (textarea) {
                    textarea.selectionStart = textarea.value.length;
                    textarea.selectionEnd = textarea.value.length;
                }
            });
        }
    }

    async function ensureTemplatesLoaded() {
        if (templatesLoaded) return;
        try {
            templates = await promptTemplates.list();
        } catch {
            templates = [];
        }
        templatesLoaded = true;
    }

    async function insertTemplate(t: PromptTemplateOut) {
        // Insère le contenu à la position du curseur (ou en fin)
        if (!textarea) {
            text = (text ? text + '\n\n' : '') + t.content;
        } else {
            const start = textarea.selectionStart ?? text.length;
            const end = textarea.selectionEnd ?? text.length;
            text = text.slice(0, start) + t.content + text.slice(end);
            await tick();
            const pos = start + t.content.length;
            textarea.selectionStart = pos;
            textarea.selectionEnd = pos;
        }
        templatesOpen = false;
        await tick();
        autoresize();
        focus();
    }

    async function saveAsTemplate() {
        const t = text.trim();
        if (!t) return;
        const name = prompt('Nom du template ?');
        if (!name) return;
        try {
            const created = await promptTemplates.create({ name, content: t });
            templates = [...templates, created].sort((a, b) => a.name.localeCompare(b.name));
        } catch {
            // toast déjà géré côté api ? on reste silencieux ici
        }
    }

    const canSend = $derived(!disabled && text.trim().length > 0);

    onMount(() => {
        // pré-chargement non-bloquant
        ensureTemplatesLoaded();
        onready?.({ focus });
    });
</script>

<form
    onsubmit={submit}
    class="border-t border-[var(--color-border-subtle)] bg-[color-mix(in_oklch,var(--color-bg-0)_85%,transparent)] p-3 backdrop-blur"
>
    <div class="mx-auto max-w-3xl">
        <div class="composer-shell group flex items-end gap-2 p-1.5">
            <div class="relative">
                <button
                    type="button"
                    onclick={() => {
                        templatesOpen = !templatesOpen;
                        if (templatesOpen) ensureTemplatesLoaded();
                    }}
                    title="Insérer un template (prompt enregistré)"
                    aria-label="Insérer un template"
                    class="grid h-9 w-9 place-items-center rounded-xl text-neutral-400 transition hover:bg-neutral-800 hover:text-cyan-300"
                >
                    <FileText size={16} />
                </button>
                {#if templatesOpen}
                    <div
                        class="absolute bottom-full left-0 z-50 mb-2 w-72 rounded-md border border-[var(--color-border-subtle)]
                               bg-[var(--color-bg-1)] p-1 shadow-xl"
                    >
                        <div class="flex items-center justify-between px-2 py-1.5">
                            <span class="text-[10px] font-medium uppercase tracking-wider text-neutral-500">Templates</span>
                            <a
                                href="/templates"
                                onclick={() => (templatesOpen = false)}
                                class="text-[10px] text-cyan-400 hover:underline"
                            >
                                Gérer
                            </a>
                        </div>
                        <div class="my-0.5 h-px bg-[var(--color-border-subtle)]"></div>
                        {#if !templatesLoaded}
                            <div class="px-3 py-2 text-xs text-neutral-500">Chargement…</div>
                        {:else if templates.length === 0}
                            <div class="px-3 py-2 text-xs text-neutral-500">
                                Aucun template. <a href="/templates" class="text-cyan-400 hover:underline" onclick={() => (templatesOpen = false)}>En créer un</a>.
                            </div>
                        {:else}
                            <ul class="max-h-72 overflow-y-auto">
                                {#each templates as t (t.id)}
                                    <li>
                                        <button
                                            type="button"
                                            onclick={() => insertTemplate(t)}
                                            class="w-full rounded px-3 py-2 text-left text-sm text-neutral-200 hover:bg-neutral-800"
                                        >
                                            <div class="truncate font-medium">{t.name}</div>
                                            <div class="truncate text-[10px] text-neutral-500">
                                                {t.shortcut ?? ''}{t.shortcut ? ' · ' : ''}{t.content.slice(0, 80)}…
                                            </div>
                                        </button>
                                    </li>
                                {/each}
                            </ul>
                        {/if}
                        {#if text.trim().length > 0}
                            <div class="my-0.5 h-px bg-[var(--color-border-subtle)]"></div>
                            <button
                                type="button"
                                onclick={saveAsTemplate}
                                class="flex w-full items-center gap-2 rounded px-3 py-2 text-left text-xs text-neutral-300 hover:bg-neutral-800"
                            >
                                <Check size={12} /> Enregistrer le texte courant…
                            </button>
                        {/if}
                    </div>
                    <button
                        type="button"
                        class="fixed inset-0 z-40 cursor-default"
                        aria-label="Fermer"
                        onclick={() => (templatesOpen = false)}
                    ></button>
                {/if}
            </div>
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
                {#if busy}
                    <Loader2 size={16} class="animate-spin" />
                {:else}
                    <Send size={16} />
                {/if}
            </button>
        </div>
        <p class="mt-2 px-2 text-[10px] text-neutral-600">
            <kbd class="rounded bg-neutral-800 px-1 py-0.5">Entrée</kbd> envoyer ·
            <kbd class="rounded bg-neutral-800 px-1 py-0.5">Maj+Entrée</kbd> nouvelle ligne ·
            <kbd class="rounded bg-neutral-800 px-1 py-0.5">↑</kbd> rappeler le dernier prompt
        </p>
    </div>
</form>

<style>
    /* Coque de saisie : anneau conique iridescent + halo qui s'allument au focus. */
    .composer-shell {
        position: relative;
        border-radius: 1rem;
        border: 1px solid var(--color-border);
        background: var(--color-bg-1);
        transition:
            border-color 0.2s ease,
            box-shadow 0.3s ease;
    }
    .composer-shell::before {
        content: '';
        position: absolute;
        inset: -1.5px;
        border-radius: inherit;
        padding: 1.5px;
        background: conic-gradient(
            from 0deg,
            oklch(0.72 0.18 210),
            oklch(0.76 0.16 285),
            oklch(0.74 0.15 165),
            oklch(0.78 0.17 320),
            oklch(0.72 0.18 210)
        );
        -webkit-mask:
            linear-gradient(#000 0 0) content-box,
            linear-gradient(#000 0 0);
        mask:
            linear-gradient(#000 0 0) content-box,
            linear-gradient(#000 0 0);
        -webkit-mask-composite: xor;
        mask-composite: exclude;
        opacity: 0;
        transition: opacity 0.35s ease;
        pointer-events: none;
    }
    .composer-shell:focus-within {
        border-color: transparent;
        box-shadow:
            0 0 0 4px color-mix(in oklch, var(--color-accent) 9%, transparent),
            0 10px 34px -14px color-mix(in oklch, var(--color-accent) 40%, transparent);
    }
    .composer-shell:focus-within::before {
        opacity: 0.75;
        animation: orb-spin 5s linear infinite;
    }
</style>
