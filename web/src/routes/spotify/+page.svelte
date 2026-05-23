<script lang="ts">
    import { onMount, onDestroy } from 'svelte';
    import { spotify, type SpotifyStatus } from '$lib/api';
    import { toast } from '$lib/toast.svelte';
    import {
        Music,
        Play,
        Pause,
        SkipForward,
        SkipBack,
        Volume2,
        RefreshCw,
        LogOut,
        Search
    } from 'lucide-svelte';

    let status: SpotifyStatus | null = $state(null);
    let query = $state('');
    let volume = $state(50);
    let busy = $state(false);
    let poll: ReturnType<typeof setInterval> | null = null;

    async function refresh() {
        try {
            status = await spotify.status();
            if (status.playback?.volume != null) volume = status.playback.volume;
        } catch {
            status = null;
        }
    }

    async function connect() {
        try {
            const { url } = await spotify.login();
            window.open(url, '_blank', 'noopener');
            toast.info?.('Autorise Spotify dans le nouvel onglet, puis reviens ici.');
        } catch {
            toast.error('Connexion impossible — Spotify est-il configuré côté serveur ?');
        }
    }

    async function ctrl(action: string, opts: { query?: string; volume?: number } = {}) {
        busy = true;
        try {
            const r = await spotify.control(action, opts);
            if (!r.ok) toast.error(r.message || 'Action refusée.');
            else if (r.now_playing)
                toast.success(`▶ ${r.now_playing.name} — ${r.now_playing.artists}`);
            await refresh();
        } catch {
            toast.error('Action impossible.');
        } finally {
            busy = false;
        }
    }

    function playQuery() {
        const q = query.trim();
        if (!q) return;
        query = '';
        ctrl('play', { query: q });
    }

    async function disconnect() {
        if (!confirm('Déconnecter Spotify ?')) return;
        try {
            await spotify.disconnect();
            await refresh();
        } catch {
            toast.error('Déconnexion impossible.');
        }
    }

    onMount(() => {
        refresh();
        poll = setInterval(refresh, 8000);
    });
    onDestroy(() => {
        if (poll) clearInterval(poll);
    });
</script>

<header class="px-6 py-5 sm:px-8">
    <h1 class="flex items-center gap-2 text-2xl font-semibold tracking-tight">
        <Music size={22} class="text-emerald-400" /> Spotify
    </h1>
    <p class="mt-1 text-xs text-neutral-500">
        Lance et pilote ta musique — l'IA peut aussi le faire via le tool « spotify ».
    </p>
</header>

<div class="space-y-4 px-6 pb-10 sm:px-8">
    {#if status && !status.configured}
        <div class="rounded-xl border border-amber-900/40 bg-amber-950/20 p-5 text-sm text-amber-200">
            Spotify n'est pas configuré côté serveur. Renseigne
            <code class="rounded bg-neutral-800 px-1">SPOUET_SPOTIFY_CLIENT_ID</code>,
            <code class="rounded bg-neutral-800 px-1">SPOUET_SPOTIFY_CLIENT_SECRET</code> et
            <code class="rounded bg-neutral-800 px-1">SPOUET_SPOTIFY_REDIRECT_URI</code>
            (app créée sur developer.spotify.com), puis redémarre le backend.
        </div>
    {:else if status && !status.connected}
        <div class="rounded-xl border border-neutral-800 bg-neutral-900/60 p-6 text-center">
            <Music size={40} class="mx-auto mb-3 text-emerald-400/70" />
            <p class="mb-4 text-sm text-neutral-400">Connecte ton compte Spotify Premium.</p>
            <button
                type="button"
                onclick={connect}
                class="rounded-lg bg-emerald-600 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-500"
            >
                Connecter Spotify
            </button>
        </div>
    {:else if status && status.connected}
        <!-- Lecteur -->
        <section class="rounded-xl border border-neutral-800 bg-neutral-900/60 p-5">
            {#if status.playback?.track}
                <div class="mb-1 flex items-center justify-between gap-2">
                    <div class="min-w-0">
                        <p class="truncate text-base font-medium">{status.playback.track.name}</p>
                        <p class="truncate text-xs text-neutral-400">{status.playback.track.artists}</p>
                    </div>
                    <span class="shrink-0 text-[11px] text-neutral-500">
                        {status.playback.is_playing ? '▶ lecture' : '⏸ pause'}{status.playback.device
                            ? ` · ${status.playback.device}`
                            : ''}
                    </span>
                </div>
            {:else}
                <p class="mb-2 text-sm text-neutral-500">Rien en cours. Lance un titre ci-dessous.</p>
            {/if}

            <div class="mt-4 flex items-center justify-center gap-3">
                <button type="button" onclick={() => ctrl('previous')} disabled={busy} class="rounded-full p-2 text-neutral-300 hover:bg-white/10" aria-label="Précédent"><SkipBack size={20} /></button>
                <button type="button" onclick={() => ctrl('pause')} disabled={busy} class="rounded-full p-2 text-neutral-300 hover:bg-white/10" aria-label="Pause"><Pause size={20} /></button>
                <button type="button" onclick={() => ctrl('play')} disabled={busy} class="rounded-full bg-emerald-600 p-3 text-white hover:bg-emerald-500" aria-label="Lecture"><Play size={20} /></button>
                <button type="button" onclick={() => ctrl('next')} disabled={busy} class="rounded-full p-2 text-neutral-300 hover:bg-white/10" aria-label="Suivant"><SkipForward size={20} /></button>
            </div>

            <div class="mt-4 flex items-center gap-2">
                <Volume2 size={16} class="text-neutral-400" />
                <input
                    type="range"
                    min="0"
                    max="100"
                    bind:value={volume}
                    onchange={() => ctrl('volume', { volume })}
                    class="w-full accent-emerald-500"
                />
                <span class="w-8 text-right text-xs text-neutral-400">{volume}</span>
            </div>
        </section>

        <!-- Lancer un titre -->
        <section class="rounded-xl border border-neutral-800 bg-neutral-900/60 p-4">
            <form onsubmit={(e) => { e.preventDefault(); playQuery(); }} class="flex gap-2">
                <div class="relative flex-1">
                    <Search size={14} class="absolute left-3 top-1/2 -translate-y-1/2 text-neutral-500" />
                    <input
                        bind:value={query}
                        placeholder="Titre ou artiste à lancer…"
                        class="w-full rounded-lg border border-neutral-700 bg-neutral-950 py-2 pl-9 pr-3 text-sm focus:border-emerald-500/50 focus:outline-none"
                    />
                </div>
                <button type="submit" disabled={busy || !query.trim()} class="rounded-lg bg-emerald-600 px-4 py-2 text-sm text-white hover:bg-emerald-500 disabled:opacity-40">Lancer</button>
            </form>
            <p class="mt-2 text-[11px] text-neutral-600">
                Astuce : un appareil Spotify doit être ouvert (téléphone, ordi, enceinte).
            </p>
        </section>

        <div class="flex items-center gap-2">
            <button type="button" onclick={refresh} class="flex items-center gap-1.5 rounded-lg border border-neutral-700 px-3 py-1.5 text-xs hover:bg-neutral-800">
                <RefreshCw size={13} /> Rafraîchir
            </button>
            <button type="button" onclick={disconnect} class="flex items-center gap-1.5 rounded-lg border border-red-900/50 px-3 py-1.5 text-xs text-red-300 hover:bg-red-950/40">
                <LogOut size={13} /> Déconnecter
            </button>
        </div>
    {:else}
        <p class="text-sm text-neutral-500">Chargement…</p>
    {/if}
</div>
