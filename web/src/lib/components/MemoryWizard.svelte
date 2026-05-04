<script lang="ts">
    /**
     * Onboarding mémoire : pose 6 questions, écrit chaque réponse comme une
     * memory `pinned=true` (clé fixe). Ces memories sont injectées
     * systématiquement dans le system prompt par la persona — donc volume
     * limité à ~6 lignes pour ne pas encombrer le contexte.
     *
     * Les questions sont skippables individuellement (la mémoire correspondante
     * est alors laissée intacte si elle existait, ou pas créée).
     */
    import { fade, fly } from 'svelte/transition';
    import { memory, type MemoryOut } from '$lib/api';
    import { toast } from '$lib/toast.svelte';
    import { ArrowRight, Check, X, SkipForward } from 'lucide-svelte';

    interface Props {
        existing: MemoryOut[];
        onclose: () => void;
        onsaved: () => void;
    }
    let { existing, onclose, onsaved }: Props = $props();

    type Question = {
        key: string;
        title: string;
        help: string;
        placeholder: string;
        defaultValue?: string;
        maxLength: number;
    };

    const QUESTIONS: Question[] = [
        {
            key: 'prenom',
            title: 'Comment dois-je vous appeler ?',
            help: 'Prénom ou pseudo. Servira à personnaliser les réponses.',
            placeholder: 'Maxime',
            maxLength: 60
        },
        {
            key: 'ia_nom',
            title: 'Quel nom voulez-vous me donner ?',
            help: 'Par défaut « Spouet ». Vous pouvez me renommer comme vous voulez.',
            placeholder: 'Spouet',
            defaultValue: 'Spouet',
            maxLength: 60
        },
        {
            key: 'ia_emoji_totem',
            title: 'Quel émoji est mon totem ?',
            help: 'Je terminerai chacune de mes réponses par cet émoji. Laissez vide pour aucun.',
            placeholder: '🦊',
            maxLength: 8
        },
        {
            key: 'langue',
            title: 'Quelle langue préférez-vous ?',
            help: 'Français par défaut. Indiquez autre chose si besoin.',
            placeholder: 'français',
            defaultValue: 'français',
            maxLength: 40
        },
        {
            key: 'ton',
            title: 'Quel ton dois-je adopter ?',
            help: 'Ex : direct, amical, formel, technique, sans politesse superflue…',
            placeholder: 'direct, sans politesse superflue',
            maxLength: 120
        },
        {
            key: 'role_utilisateur',
            title: 'En une phrase, votre rôle ou contexte ?',
            help: 'Ex : « dev backend Python ». Permet d\'adapter les explications.',
            placeholder: 'dev backend qui apprend la stack web',
            maxLength: 160
        }
    ];

    let step = $state(0);
    let answers: Record<string, string> = $state({});
    let saving = $state(false);

    // Pré-remplir avec les memories existantes
    $effect(() => {
        for (const q of QUESTIONS) {
            const found = existing.find((m) => m.key === q.key);
            if (found) answers[q.key] = found.value;
            else if (q.defaultValue && answers[q.key] === undefined)
                answers[q.key] = q.defaultValue;
        }
    });

    const current = $derived(QUESTIONS[step]);
    const isLast = $derived(step === QUESTIONS.length - 1);
    const progress = $derived(Math.round(((step + 1) / QUESTIONS.length) * 100));

    function next() {
        if (isLast) {
            void finish();
        } else {
            step += 1;
        }
    }

    function skip() {
        // Vide la réponse → on n'écrit rien pour cette clé.
        answers[current.key] = '';
        next();
    }

    async function finish() {
        saving = true;
        try {
            for (const q of QUESTIONS) {
                const v = (answers[q.key] ?? '').trim();
                if (!v) continue;
                await memory.upsert({ key: q.key, value: v, pinned: true });
            }
            toast.success('Profil mémorisé.');
            onsaved();
            onclose();
        } catch (e) {
            console.error(e);
            toast.error('Échec de l\'enregistrement.');
        } finally {
            saving = false;
        }
    }
</script>

<div
    class="fixed inset-0 z-50 grid place-items-center bg-black/50 p-4 backdrop-blur-sm"
    in:fade={{ duration: 150 }}
    out:fade={{ duration: 100 }}
    role="dialog"
    aria-modal="true"
    aria-labelledby="wizard-title"
>
    <div
        class="relative w-full max-w-lg rounded-2xl border border-[var(--color-border)]
               bg-[var(--color-bg-1)] p-6 shadow-2xl"
        in:fly={{ y: 12, duration: 200 }}
    >
        <button
            type="button"
            onclick={onclose}
            class="absolute right-4 top-4 rounded p-1 text-neutral-500 hover:bg-neutral-800 hover:text-neutral-200"
            aria-label="Fermer"
        >
            <X size={16} />
        </button>

        <!-- Barre de progression -->
        <div class="mb-1 flex items-center justify-between text-xs text-neutral-500">
            <span>Question {step + 1} sur {QUESTIONS.length}</span>
            <span>{progress}%</span>
        </div>
        <div class="mb-6 h-1 overflow-hidden rounded-full bg-neutral-800">
            <div
                class="h-full bg-cyan-500 transition-all"
                style="width: {progress}%"
            ></div>
        </div>

        {#key step}
            <div in:fly={{ x: 20, duration: 180 }}>
                <h2 id="wizard-title" class="mb-2 text-lg font-semibold">
                    {current.title}
                </h2>
                <p class="mb-4 text-xs text-neutral-500">{current.help}</p>

                <input
                    type="text"
                    bind:value={answers[current.key]}
                    placeholder={current.placeholder}
                    maxlength={current.maxLength}
                    class="w-full rounded-md border border-neutral-700 bg-neutral-950 px-3 py-2
                           text-sm focus:border-cyan-500/60 focus:outline-none"
                    onkeydown={(e) => {
                        if (e.key === 'Enter') {
                            e.preventDefault();
                            next();
                        }
                    }}
                />
                <p class="mt-1 text-right text-[10px] text-neutral-600">
                    {(answers[current.key] ?? '').length}/{current.maxLength}
                </p>
            </div>
        {/key}

        <div class="mt-6 flex items-center justify-between gap-2">
            <button
                type="button"
                onclick={skip}
                class="flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs text-neutral-500 hover:bg-neutral-800"
            >
                <SkipForward size={12} /> Passer
            </button>

            <div class="flex items-center gap-2">
                {#if step > 0}
                    <button
                        type="button"
                        onclick={() => (step -= 1)}
                        class="rounded-md border border-neutral-700 px-3 py-1.5 text-xs hover:bg-neutral-800"
                    >
                        Précédent
                    </button>
                {/if}
                <button
                    type="button"
                    onclick={next}
                    disabled={saving}
                    class="flex items-center gap-1.5 rounded-md bg-cyan-600 px-3 py-1.5 text-xs
                           font-medium text-white hover:bg-cyan-500 disabled:opacity-50"
                >
                    {#if isLast}
                        <Check size={12} /> Terminer
                    {:else}
                        Suivant <ArrowRight size={12} />
                    {/if}
                </button>
            </div>
        </div>

        <p class="mt-5 border-t border-neutral-800 pt-3 text-[11px] leading-relaxed text-neutral-600">
            Les réponses sont stockées en mémoire <strong>épinglée</strong> (max ~6 entrées,
            ~50 tokens) et injectées dans le contexte de chaque conversation. Le reste des
            mémoires utilise un recall sémantique : seules les pertinentes sont chargées.
        </p>
    </div>
</div>
