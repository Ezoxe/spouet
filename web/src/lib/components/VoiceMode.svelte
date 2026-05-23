<script lang="ts">
    import { onDestroy } from 'svelte';
    import { fade, scale } from 'svelte/transition';
    import { Mic, MicOff, X, Volume2, VolumeX, Loader2 } from 'lucide-svelte';
    import {
        startRecorder,
        createTtsPlayer,
        isRecordingSupported,
        isSecureContextOk,
        isWebSpeechSttSupported,
        startWebSpeechStt,
        isTtsSupported,
        type Recorder,
        type TtsPlayer,
        type VoiceBus
    } from '$lib/voice';
    import { voice as voiceApi } from '$lib/api';
    import Logo from './Logo.svelte';

    interface Props {
        open: boolean;
        streaming: boolean;
        onclose: () => void;
        onsubmit: (text: string) => void;
        /** Bus poussé par le parent : `bus.token(delta)` / `bus.done()`. */
        bus?: VoiceBus;
        /** Langue de transcription (déduit la voix). */
        lang?: string;
    }

    let { open = $bindable(), streaming, onclose, onsubmit, bus, lang = 'fr' }: Props = $props();

    // Mode de capture déterminé au runtime.
    const canRecord = isRecordingSupported() && isSecureContextOk();
    const mode: 'recorder' | 'webspeech' | 'none' = canRecord
        ? 'recorder'
        : isWebSpeechSttSupported()
          ? 'webspeech'
          : 'none';
    const ttsOk = isTtsSupported() || mode === 'recorder';

    let listening = $state(false);
    let transcribing = $state(false);
    let muted = $state(false);
    let level = $state(0);
    let partial = $state('');
    let error = $state<string | null>(null);

    let rec: Recorder | null = null;
    let webrec: ReturnType<typeof startWebSpeechStt> = null;
    let tts: TtsPlayer | null = null;

    function ensureTts(): TtsPlayer {
        if (!tts) tts = createTtsPlayer({ lang: `${lang}-${lang.toUpperCase()}`, useBackend: true });
        return tts;
    }

    function humanizeMicError(e: unknown): string {
        const name = (e as { name?: string })?.name ?? '';
        if (name === 'NotAllowedError' || name === 'SecurityError')
            return 'Accès au micro refusé. Autorisez-le dans le navigateur.';
        if (name === 'NotFoundError') return 'Aucun micro détecté.';
        return e instanceof Error ? e.message : String(e);
    }

    async function startListening() {
        if (streaming || listening || transcribing) return;
        error = null;
        partial = '';

        if (mode === 'recorder') {
            try {
                rec = await startRecorder({
                    silenceMs: 1500,
                    onLevel: (l) => (level = l),
                    onSilence: () => void finishRecording()
                });
                listening = true;
            } catch (e) {
                error = humanizeMicError(e);
                listening = false;
            }
            return;
        }

        if (mode === 'webspeech') {
            let lastFinal = '';
            webrec = startWebSpeechStt({
                lang: `${lang}-${lang.toUpperCase()}`,
                onPartial: (t) => (partial = t),
                onFinal: (t) => (lastFinal = t),
                onError: (err) => {
                    error = err;
                    listening = false;
                },
                onEnd: () => {
                    listening = false;
                    const text = (lastFinal || partial).trim();
                    partial = '';
                    if (text) onsubmit(text);
                }
            });
            listening = !!webrec;
        }
    }

    async function finishRecording() {
        if (!rec || !listening) return;
        listening = false;
        level = 0;
        const r = rec;
        rec = null;
        const blob = await r.stop();
        if (!blob) return;
        transcribing = true;
        try {
            const text = await voiceApi.transcribe(blob, lang);
            if (text.trim()) onsubmit(text.trim());
            else error = 'Rien compris, réessayez.';
        } catch {
            error = 'Transcription échouée (moteur voix indisponible ?).';
        } finally {
            transcribing = false;
        }
    }

    function stopListening() {
        if (mode === 'recorder') void finishRecording();
        else webrec?.stop();
    }

    function toggleListen() {
        if (listening) stopListening();
        else void startListening();
    }

    function toggleMute() {
        muted = !muted;
        if (muted) tts?.cancel();
    }

    function close() {
        rec?.cancel();
        webrec?.abort();
        tts?.cancel();
        listening = false;
        transcribing = false;
        level = 0;
        onclose();
    }

    // Stream LLM -> TTS
    $effect(() => {
        if (!bus) return;
        const off = bus.subscribe({
            token: (delta) => {
                if (muted) return;
                ensureTts().speak(delta);
            },
            done: () => {
                if (muted) return;
                ensureTts().flush();
            }
        });
        return () => off();
    });

    onDestroy(() => {
        rec?.cancel();
        webrec?.abort();
        tts?.cancel();
    });

    function onKey(e: KeyboardEvent) {
        if (!open) return;
        if (e.key === 'Escape') {
            e.preventDefault();
            close();
            return;
        }
        const t = e.target as HTMLElement | null;
        const tag = t?.tagName;
        if (tag === 'INPUT' || tag === 'TEXTAREA' || t?.isContentEditable) return;
        if (e.code === 'Space' && !e.repeat) {
            e.preventDefault();
            toggleListen();
        }
    }
</script>

<svelte:window on:keydown={onKey} />

{#if open}
    <div
        in:fade={{ duration: 180 }}
        out:fade={{ duration: 140 }}
        class="fixed inset-0 z-50 flex flex-col items-center justify-center
               bg-[oklch(0.05_0.02_240/0.92)] backdrop-blur-2xl"
        role="dialog"
        aria-modal="true"
    >
        <button
            type="button"
            onclick={close}
            class="absolute right-5 top-5 grid h-9 w-9 place-items-center rounded-full
                   bg-white/5 text-neutral-300 hover:bg-white/10 hover:text-white"
            aria-label="Fermer le mode vocal"
        >
            <X size={16} />
        </button>

        <div in:scale={{ duration: 320, start: 0.8 }} class="relative">
            <span
                class="orb"
                class:listening
                class:speaking={streaming && !muted}
                style:opacity={listening ? 0.55 + level * 0.45 : undefined}
            ></span>
            <span class="relative z-10 grid place-items-center">
                <Logo size={140} glow animated />
            </span>
        </div>

        <p class="mt-10 max-w-xl px-6 text-center text-base text-neutral-200 min-h-[3rem]">
            {#if error}
                <span class="text-red-400">⚠ {error}</span>
            {:else if transcribing}
                <span class="text-cyan-300">Transcription…</span>
            {:else if listening}
                {partial || 'À l’écoute…'}
            {:else if streaming}
                <span class="text-cyan-300">Spouet répond…</span>
            {:else if mode === 'none'}
                <span class="text-amber-300">
                    Aucun moyen de capter le micro ici. Utilisez l’app ou un accès HTTPS.
                </span>
            {:else}
                Appuyez sur Espace ou sur le micro pour parler.
            {/if}
        </p>

        <div class="mt-8 flex items-center gap-4">
            <button
                type="button"
                onclick={toggleMute}
                disabled={!ttsOk}
                title={muted ? 'Réactiver la voix' : 'Couper la voix'}
                aria-label={muted ? 'Réactiver la voix' : 'Couper la voix'}
                class="grid h-12 w-12 place-items-center rounded-full
                       border border-white/10 bg-white/5 text-neutral-200
                       transition hover:bg-white/10 disabled:opacity-30"
            >
                {#if muted}
                    <VolumeX size={18} />
                {:else}
                    <Volume2 size={18} />
                {/if}
            </button>

            <button
                type="button"
                onclick={toggleListen}
                disabled={mode === 'none' || streaming || transcribing}
                aria-pressed={listening}
                aria-label={listening ? 'Arrêter l’écoute' : 'Commencer à parler'}
                class="grid h-16 w-16 place-items-center rounded-full text-white shadow-xl
                       transition-transform active:scale-95 disabled:opacity-40
                       {listening
                    ? 'bg-gradient-to-br from-rose-500 to-rose-700'
                    : 'bg-gradient-to-br from-cyan-500 to-cyan-700'}"
            >
                {#if transcribing}
                    <Loader2 size={22} class="animate-spin" />
                {:else if listening}
                    <MicOff size={22} />
                {:else}
                    <Mic size={22} />
                {/if}
            </button>

            <span class="grid h-12 w-12 place-items-center rounded-full text-[10px] text-neutral-500">
                Esc
            </span>
        </div>

        <p class="mt-6 text-[10px] uppercase tracking-widest text-neutral-600">
            Espace : parler · Esc : fermer
        </p>
    </div>
{/if}

<style>
    .orb {
        position: absolute;
        inset: -40px;
        border-radius: 9999px;
        background: radial-gradient(
            closest-side,
            oklch(0.7 0.18 210 / 0.45),
            oklch(0.55 0.18 210 / 0.15) 55%,
            transparent 75%
        );
        filter: blur(18px);
        animation: idle-pulse 4s ease-in-out infinite;
        pointer-events: none;
    }
    .orb.listening {
        background: radial-gradient(
            closest-side,
            oklch(0.7 0.22 20 / 0.55),
            oklch(0.55 0.2 20 / 0.2) 55%,
            transparent 75%
        );
        animation: listen-pulse 1.1s ease-in-out infinite;
    }
    .orb.speaking {
        background: radial-gradient(
            closest-side,
            oklch(0.78 0.2 200 / 0.6),
            oklch(0.6 0.18 210 / 0.2) 55%,
            transparent 75%
        );
        animation: speak-pulse 0.65s ease-in-out infinite;
    }
    @keyframes idle-pulse {
        0%,
        100% {
            transform: scale(1);
            opacity: 0.7;
        }
        50% {
            transform: scale(1.06);
            opacity: 1;
        }
    }
    @keyframes listen-pulse {
        0%,
        100% {
            transform: scale(0.95);
        }
        50% {
            transform: scale(1.18);
        }
    }
    @keyframes speak-pulse {
        0%,
        100% {
            transform: scale(1);
            opacity: 0.85;
        }
        50% {
            transform: scale(1.12);
            opacity: 1;
        }
    }
</style>
