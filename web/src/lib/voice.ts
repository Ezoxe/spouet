/**
 * Voice : reconnaissance vocale (Web Speech API) + synthèse vocale (SpeechSynthesis).
 *
 * Fonctionne sur Chrome/Edge/Safari (et donc dans Tauri). Firefox n'a pas
 * la reconnaissance native, on dégrade proprement (`isSupported = false`).
 */

type SR = typeof window extends { SpeechRecognition: infer T } ? T : unknown;

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

export function isSttSupported(): boolean {
    return getSRClass() !== null;
}

export function isTtsSupported(): boolean {
    return typeof window !== 'undefined' && 'speechSynthesis' in window;
}

export interface SttOptions {
    lang?: string;
    onPartial?: (text: string) => void;
    onFinal?: (text: string) => void;
    onError?: (err: string) => void;
    onEnd?: () => void;
}

/** Lance une session de reconnaissance vocale en streaming. */
export function startStt(opts: SttOptions = {}): SpeechRecognitionLike | null {
    const Cls = getSRClass();
    if (!Cls) {
        opts.onError?.('SpeechRecognition non supporté par ce navigateur');
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

let currentVoice: SpeechSynthesisVoice | null = null;

/**
 * Sélectionne la meilleure voix disponible pour la langue demandée.
 *
 * Score : prefère les voix natural/neural/online, pénalise les voix
 * système Windows "Hortense/Paul" qui sonnent robotiques. À langue
 * équivalente, on retient la mieux notée.
 */
function pickVoice(lang: string): SpeechSynthesisVoice | null {
    if (!isTtsSupported()) return null;
    const all = window.speechSynthesis.getVoices();
    if (!all.length) return null;

    const baseLang = lang.split('-')[0].toLowerCase();

    // Voix manuellement préférée par l'utilisateur (localStorage)
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
        // Préférer les voix neuronales modernes
        if (/natural|neural|premium|enhanced|online|wavenet/.test(name)) bonus += 40;
        // Google online voices (Chrome) — très naturelles
        if (name.startsWith('google')) bonus += 35;
        // Microsoft "Online (Natural)" voices
        if (/microsoft .* online/.test(name)) bonus += 30;
        // Microsoft Denise (FR-FR) est plus fluide que Hortense/Paul
        if (name.includes('denise')) bonus += 15;
        if (name.includes('eloise')) bonus += 15;
        // Pénalise voix système basiques
        if (/hortense|paul desktop|microsoft (paul|julie|hortense)$/.test(name)) bonus -= 20;
        // Préférer les voix non-locales (online = synthèse cloud, meilleure qualité)
        if (!v.localService) bonus += 10;
        // Match exact langue + région
        if (v.lang.toLowerCase() === lang.toLowerCase()) bonus += 5;
        return langOk + bonus;
    }

    return [...all].sort((a, b) => score(b) - score(a))[0] ?? null;
}

/** Retourne la liste des voix disponibles classées par qualité estimée. */
export function listVoices(lang = 'fr-FR'): SpeechSynthesisVoice[] {
    if (!isTtsSupported()) return [];
    const all = window.speechSynthesis.getVoices();
    const baseLang = lang.split('-')[0].toLowerCase();
    return all.filter((v) => v.lang.toLowerCase().startsWith(baseLang));
}

/** Mémorise la voix choisie par l'utilisateur. */
export function setPreferredVoice(voiceURI: string | null): void {
    if (typeof localStorage === 'undefined') return;
    if (voiceURI) localStorage.setItem('spouet:tts_voice', voiceURI);
    else localStorage.removeItem('spouet:tts_voice');
    currentVoice = null;
}

/**
 * Parle un texte. Si `chunked` (défaut), découpe par phrase pour démarrer
 * la lecture dès les premiers tokens (utile pendant un stream).
 */
export interface TtsHandle {
    speak: (text: string) => void;
    flush: () => void;
    cancel: () => void;
    setLang: (lang: string) => void;
}

export function createTts(lang = 'fr-FR'): TtsHandle {
    let buf = '';
    let curLang = lang;

    function ensureVoice() {
        if (!currentVoice || currentVoice.lang !== curLang) {
            currentVoice = pickVoice(curLang);
        }
    }

    function emit(text: string) {
        if (!isTtsSupported() || !text.trim()) return;
        ensureVoice();
        const u = new SpeechSynthesisUtterance(text);
        u.lang = curLang;
        if (currentVoice) u.voice = currentVoice;
        // 1.05 = légèrement plus naturel, 0.95 sonne un peu monotone
        u.rate = 1.05;
        u.pitch = 1.0;
        u.volume = 1.0;
        window.speechSynthesis.speak(u);
    }

    function flushSentences() {
        // Découpe sur ponctuation forte ; garde le résidu dans buf
        const re = /([^.!?…\n]+[.!?…\n]+)/g;
        let m: RegExpExecArray | null;
        let lastIndex = 0;
        while ((m = re.exec(buf)) !== null) {
            emit(m[1].trim());
            lastIndex = m.index + m[0].length;
        }
        buf = buf.slice(lastIndex);
    }

    return {
        speak(text: string) {
            buf += text;
            flushSentences();
        },
        flush() {
            if (buf.trim()) emit(buf.trim());
            buf = '';
        },
        cancel() {
            if (isTtsSupported()) window.speechSynthesis.cancel();
            buf = '';
        },
        setLang(l: string) {
            curLang = l;
            currentVoice = null;
        }
    };
}

/**
 * Bus minimal pour pousser des deltas de stream vers les abonnés (typiquement
 * le composant VoiceMode). Permet d'émettre la même chaîne plusieurs fois
 * sans dépendre de la réactivité par diff.
 */
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

// Précharge les voix si possible (Chrome charge async)
if (typeof window !== 'undefined' && isTtsSupported()) {
    window.speechSynthesis.getVoices();
    window.speechSynthesis.onvoiceschanged = () => {
        currentVoice = null;
    };
}
