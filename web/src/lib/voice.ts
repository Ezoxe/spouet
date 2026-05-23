/**
 * Voix Spouet — pipeline self-hosted (microservice voice-engine).
 *
 * STT : capture micro via MediaRecorder -> POST /api/voice/transcribe (Whisper).
 *       MediaRecorder fonctionne dans WebView2 (l'app Tauri), contrairement à
 *       l'ancienne Web Speech API qui n'y est pas implémentée.
 * TTS : POST /api/voice/speak (Piper) -> lecture séquentielle des WAV.
 *
 * Repli : si le backend voix est indisponible, on retombe sur la Web Speech API
 * du navigateur (SpeechSynthesis pour le TTS, webkitSpeechRecognition pour le STT
 * quand il existe).
 *
 * ⚠️ getUserMedia exige un contexte sécurisé : HTTPS (Caddy) ou `tauri://` (app
 * desktop). En HTTP simple sur le LAN, le navigateur bloque le micro.
 */

import { voice as voiceApi } from './api';

// ---------------------------------------------------------------------------
// Détection de support
// ---------------------------------------------------------------------------

export function isRecordingSupported(): boolean {
    return (
        typeof navigator !== 'undefined' &&
        !!navigator.mediaDevices?.getUserMedia &&
        typeof MediaRecorder !== 'undefined'
    );
}

export function isTtsSupported(): boolean {
    return typeof window !== 'undefined' && 'speechSynthesis' in window;
}

export function isSecureContextOk(): boolean {
    if (typeof window === 'undefined') return false;
    // Tauri expose __TAURI__ ; son origine custom est considérée sécurisée.
    if ((window as unknown as { __TAURI__?: unknown }).__TAURI__) return true;
    return window.isSecureContext === true;
}

function pickMimeType(): string {
    const candidates = [
        'audio/webm;codecs=opus',
        'audio/webm',
        'audio/ogg;codecs=opus',
        'audio/mp4'
    ];
    if (typeof MediaRecorder === 'undefined') return '';
    for (const c of candidates) {
        if (MediaRecorder.isTypeSupported(c)) return c;
    }
    return '';
}

// ---------------------------------------------------------------------------
// STT — enregistrement micro + VAD optionnel
// ---------------------------------------------------------------------------

export interface RecorderOptions {
    /** Niveau sonore (0..1) pour animer l'UI. */
    onLevel?: (level: number) => void;
    /** Appelé une fois qu'un silence prolongé est détecté après de la parole. */
    onSilence?: () => void;
    /** Durée de silence (ms) avant de déclencher onSilence. 0 = pas de VAD. */
    silenceMs?: number;
    /** Seuil RMS de détection de parole (0..1). */
    threshold?: number;
}

export interface Recorder {
    /** Arrête l'enregistrement et renvoie l'audio capturé (null si vide). */
    stop: () => Promise<Blob | null>;
    /** Arrête sans rien renvoyer (annulation). */
    cancel: () => void;
    readonly active: boolean;
}

/**
 * Démarre la capture micro. Lève si le micro est inaccessible (permission
 * refusée, contexte non sécurisé, pas de support).
 */
export async function startRecorder(opts: RecorderOptions = {}): Promise<Recorder> {
    if (!isRecordingSupported()) {
        throw new Error('Enregistrement audio non supporté par ce navigateur.');
    }
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    const mimeType = pickMimeType();
    const rec = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
    const chunks: BlobPart[] = [];
    rec.ondataavailable = (e) => {
        if (e.data && e.data.size > 0) chunks.push(e.data);
    };

    let active = true;
    let stopResolve: ((b: Blob | null) => void) | null = null;
    let cancelled = false;

    rec.onstop = () => {
        active = false;
        const blob = chunks.length ? new Blob(chunks, { type: mimeType || 'audio/webm' }) : null;
        teardownVad();
        stream.getTracks().forEach((t) => t.stop());
        stopResolve?.(cancelled ? null : blob);
    };

    // --- VAD léger via Web Audio (analyse RMS) ---
    let audioCtx: AudioContext | null = null;
    let rafId = 0;
    const threshold = opts.threshold ?? 0.018;
    const silenceMs = opts.silenceMs ?? 0;

    function teardownVad() {
        if (rafId) cancelAnimationFrame(rafId);
        rafId = 0;
        audioCtx?.close().catch(() => {});
        audioCtx = null;
    }

    if (opts.onLevel || silenceMs > 0) {
        try {
            const Ctx =
                window.AudioContext ||
                (window as unknown as { webkitAudioContext: typeof AudioContext })
                    .webkitAudioContext;
            audioCtx = new Ctx();
            const source = audioCtx.createMediaStreamSource(stream);
            const analyser = audioCtx.createAnalyser();
            analyser.fftSize = 512;
            source.connect(analyser);
            const data = new Uint8Array(analyser.frequencyBinCount);
            let speechSeen = false;
            let silenceStart = performance.now();
            let fired = false;

            const tick = () => {
                if (!active || !audioCtx) return;
                analyser.getByteTimeDomainData(data);
                let sum = 0;
                for (let i = 0; i < data.length; i++) {
                    const x = (data[i] - 128) / 128;
                    sum += x * x;
                }
                const rms = Math.sqrt(sum / data.length);
                opts.onLevel?.(Math.min(1, rms * 4));

                const now = performance.now();
                if (rms > threshold) {
                    speechSeen = true;
                    silenceStart = now;
                } else if (speechSeen && silenceMs > 0 && !fired && now - silenceStart > silenceMs) {
                    fired = true;
                    opts.onSilence?.();
                }
                rafId = requestAnimationFrame(tick);
            };
            rafId = requestAnimationFrame(tick);
        } catch {
            // VAD best-effort : on continue sans animation/auto-stop.
        }
    }

    rec.start();

    return {
        get active() {
            return active;
        },
        stop() {
            return new Promise<Blob | null>((resolve) => {
                if (!active) return resolve(null);
                stopResolve = resolve;
                if (rec.state !== 'inactive') rec.stop();
                else resolve(null);
            });
        },
        cancel() {
            cancelled = true;
            if (rec.state !== 'inactive') rec.stop();
            else {
                teardownVad();
                stream.getTracks().forEach((t) => t.stop());
            }
        }
    };
}

// ---------------------------------------------------------------------------
// STT — repli Web Speech (navigateur, hors WebView2)
// ---------------------------------------------------------------------------

interface SpeechRecognitionResultLike {
    isFinal: boolean;
    [index: number]: { transcript: string };
}
interface SpeechRecognitionEventLike {
    resultIndex: number;
    results: ArrayLike<SpeechRecognitionResultLike>;
}
interface SpeechRecognitionLike {
    lang: string;
    continuous: boolean;
    interimResults: boolean;
    start(): void;
    stop(): void;
    abort(): void;
    onresult: ((ev: SpeechRecognitionEventLike) => void) | null;
    onerror: ((ev: { error: string }) => void) | null;
    onend: (() => void) | null;
}

function getSRClass(): { new (): SpeechRecognitionLike } | null {
    if (typeof window === 'undefined') return null;
    const w = window as unknown as Record<string, unknown>;
    return (w.SpeechRecognition || w.webkitSpeechRecognition) as
        | { new (): SpeechRecognitionLike }
        | null;
}

export function isWebSpeechSttSupported(): boolean {
    return getSRClass() !== null;
}

export interface SttOptions {
    lang?: string;
    onPartial?: (text: string) => void;
    onFinal?: (text: string) => void;
    onError?: (err: string) => void;
    onEnd?: () => void;
}

export function startWebSpeechStt(opts: SttOptions = {}): SpeechRecognitionLike | null {
    const Cls = getSRClass();
    if (!Cls) {
        opts.onError?.('Reconnaissance vocale navigateur non supportée');
        return null;
    }
    const rec = new Cls();
    rec.lang = opts.lang ?? 'fr-FR';
    rec.continuous = true;
    rec.interimResults = true;
    let finalBuf = '';
    rec.onresult = (ev) => {
        let interim = '';
        for (let i = ev.resultIndex; i < ev.results.length; i++) {
            const r = ev.results[i];
            const t = r[0].transcript;
            if (r.isFinal) finalBuf += t;
            else interim += t;
        }
        if (interim) opts.onPartial?.(finalBuf + interim);
        if (finalBuf) opts.onFinal?.(finalBuf);
    };
    rec.onerror = (ev) => opts.onError?.(ev.error);
    rec.onend = () => opts.onEnd?.();
    try {
        rec.start();
    } catch (e) {
        opts.onError?.(String(e));
        return null;
    }
    return rec;
}

// ---------------------------------------------------------------------------
// TTS — sélection de voix pour le repli SpeechSynthesis
// ---------------------------------------------------------------------------

let currentVoice: SpeechSynthesisVoice | null = null;

function pickVoice(lang: string): SpeechSynthesisVoice | null {
    if (!isTtsSupported()) return null;
    const all = window.speechSynthesis.getVoices();
    if (!all.length) return null;
    const baseLang = lang.split('-')[0].toLowerCase();
    if (typeof localStorage !== 'undefined') {
        const wanted = localStorage.getItem('spouet:tts_voice');
        if (wanted) {
            const v = all.find((v) => v.voiceURI === wanted || v.name === wanted);
            if (v) return v;
        }
    }
    function score(v: SpeechSynthesisVoice): number {
        const name = v.name.toLowerCase();
        const langOk =
            v.lang.toLowerCase() === lang.toLowerCase()
                ? 100
                : v.lang.toLowerCase().startsWith(baseLang)
                  ? 50
                  : 0;
        if (langOk === 0) return -1;
        let bonus = 0;
        if (/natural|neural|premium|enhanced|online|wavenet/.test(name)) bonus += 40;
        if (name.startsWith('google')) bonus += 35;
        if (/microsoft .* online/.test(name)) bonus += 30;
        if (name.includes('denise') || name.includes('eloise')) bonus += 15;
        if (/hortense|paul desktop/.test(name)) bonus -= 20;
        if (!v.localService) bonus += 10;
        return langOk + bonus;
    }
    return [...all].sort((a, b) => score(b) - score(a))[0] ?? null;
}

export function listVoices(lang = 'fr-FR'): SpeechSynthesisVoice[] {
    if (!isTtsSupported()) return [];
    const baseLang = lang.split('-')[0].toLowerCase();
    return window.speechSynthesis.getVoices().filter((v) => v.lang.toLowerCase().startsWith(baseLang));
}

export function setPreferredVoice(voiceURI: string | null): void {
    if (typeof localStorage === 'undefined') return;
    if (voiceURI) localStorage.setItem('spouet:tts_voice', voiceURI);
    else localStorage.removeItem('spouet:tts_voice');
    currentVoice = null;
}

// ---------------------------------------------------------------------------
// TTS — lecteur à file d'attente (backend Piper, repli SpeechSynthesis)
// ---------------------------------------------------------------------------

export interface TtsPlayer {
    /** Ajoute du texte ; les phrases complètes sont synthétisées au fil de l'eau. */
    speak: (text: string) => void;
    /** Synthétise le résidu en attente (fin de stream). */
    flush: () => void;
    /** Stoppe la lecture et vide la file. */
    cancel: () => void;
    readonly speaking: boolean;
}

export interface TtsPlayerOptions {
    /** Nom de voix Piper (ex fr_FR-siwis-medium). */
    voice?: string;
    /** Langue pour le repli SpeechSynthesis. */
    lang?: string;
    /** Utiliser le backend Piper (sinon SpeechSynthesis direct). */
    useBackend?: boolean;
}

export function createTtsPlayer(opts: TtsPlayerOptions = {}): TtsPlayer {
    const lang = opts.lang ?? 'fr-FR';
    let useBackend = opts.useBackend ?? true;
    let buf = '';
    let cancelled = false;
    let pumping = false;
    let currentAudio: HTMLAudioElement | null = null;
    const queue: Array<{ text: string; blob: Promise<Blob | null> }> = [];

    async function synth(sentence: string): Promise<Blob | null> {
        try {
            return await voiceApi.speak(sentence, opts.voice);
        } catch {
            useBackend = false; // bascule sur le repli pour la suite
            return null;
        }
    }

    function playBlob(blob: Blob): Promise<void> {
        return new Promise((resolve) => {
            const url = URL.createObjectURL(blob);
            const audio = new Audio(url);
            currentAudio = audio;
            const done = () => {
                URL.revokeObjectURL(url);
                if (currentAudio === audio) currentAudio = null;
                resolve();
            };
            audio.onended = done;
            audio.onerror = done;
            audio.play().catch(done);
        });
    }

    function speakFallback(text: string): Promise<void> {
        return new Promise((resolve) => {
            if (!isTtsSupported() || !text.trim()) return resolve();
            if (!currentVoice || currentVoice.lang !== lang) currentVoice = pickVoice(lang);
            const u = new SpeechSynthesisUtterance(text);
            u.lang = lang;
            if (currentVoice) u.voice = currentVoice;
            u.rate = 1.05;
            u.onend = () => resolve();
            u.onerror = () => resolve();
            window.speechSynthesis.speak(u);
        });
    }

    async function pump() {
        if (pumping) return;
        pumping = true;
        while (queue.length && !cancelled) {
            const item = queue.shift()!;
            const blob = await item.blob;
            if (cancelled) break;
            if (blob) await playBlob(blob);
            else await speakFallback(item.text); // backend KO pour cette phrase
        }
        pumping = false;
    }

    function enqueue(sentence: string) {
        const s = sentence.trim();
        if (!s) return;
        if (useBackend) {
            queue.push({ text: s, blob: synth(s) }); // lance la synthèse tout de suite
            void pump();
        } else {
            queue.push({ text: s, blob: Promise.resolve(null) });
            void pump();
        }
    }

    function flushSentences() {
        const re = /([^.!?…\n]+[.!?…\n]+)/g;
        let m: RegExpExecArray | null;
        let lastIndex = 0;
        while ((m = re.exec(buf)) !== null) {
            enqueue(m[1]);
            lastIndex = m.index + m[0].length;
        }
        buf = buf.slice(lastIndex);
    }

    return {
        get speaking() {
            return pumping || queue.length > 0 || currentAudio !== null;
        },
        speak(text: string) {
            cancelled = false;
            buf += text;
            flushSentences();
        },
        flush() {
            if (buf.trim()) {
                enqueue(buf);
                buf = '';
            }
        },
        cancel() {
            cancelled = true;
            buf = '';
            queue.length = 0;
            if (currentAudio) {
                currentAudio.pause();
                currentAudio = null;
            }
            if (isTtsSupported()) window.speechSynthesis.cancel();
        }
    };
}

// ---------------------------------------------------------------------------
// Bus de stream -> TTS (inchangé : poussé par le chat pendant le streaming)
// ---------------------------------------------------------------------------

export interface VoiceBusListener {
    token?: (delta: string) => void;
    done?: () => void;
}

export interface VoiceBus {
    token: (delta: string) => void;
    done: () => void;
    subscribe: (l: VoiceBusListener) => () => void;
}

export function createVoiceBus(): VoiceBus {
    const listeners = new Set<VoiceBusListener>();
    return {
        token(delta) {
            for (const l of listeners) l.token?.(delta);
        },
        done() {
            for (const l of listeners) l.done?.();
        },
        subscribe(l) {
            listeners.add(l);
            return () => listeners.delete(l);
        }
    };
}

// Précharge les voix de repli (Chrome les charge en asynchrone).
if (typeof window !== 'undefined' && isTtsSupported()) {
    window.speechSynthesis.getVoices();
    window.speechSynthesis.onvoiceschanged = () => {
        currentVoice = null;
    };
}
