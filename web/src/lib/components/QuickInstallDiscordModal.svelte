<script lang="ts">
    import { connectors as connectorsApi, type ConnectorOut } from '$lib/api';
    import { toast } from '$lib/toast.svelte';
    import { X, Loader2, ExternalLink, CheckCircle2 } from 'lucide-svelte';

    let { open = $bindable(false), onInstalled }: {
        open?: boolean;
        onInstalled?: (c: ConnectorOut) => void;
    } = $props();

    let token = $state('');
    let bot_persona = $state(
        "Tu es l'assistant Spouet relayé via Discord. Réponds en français, de manière concise. Tu peux appeler des tools spouet-* pour obtenir des stats des nodes du cluster."
    );
    let default_model = $state('');
    let respond_dm = $state(true);
    let installing = $state(false);
    let result: ConnectorOut | null = $state(null);

    async function submit(e: Event) {
        e.preventDefault();
        if (!token.trim() || installing) return;
        installing = true;
        try {
            result = await connectorsApi.quickInstallDiscord({
                token: token.trim(),
                bot_persona,
                default_model: default_model || undefined,
                respond_dm
            });
            toast.success('Connector Discord installé. Bot en train de se connecter…');
            onInstalled?.(result);
        } catch (e) {
            toast.error("Échec de l'installation Discord");
        } finally {
            installing = false;
        }
    }

    function reset() {
        token = '';
        result = null;
        open = false;
    }
</script>

{#if open}
    <div
        role="dialog"
        aria-modal="true"
        class="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4 backdrop-blur-sm"
        onclick={(e) => {
            if (e.target === e.currentTarget) reset();
        }}
    >
        <div class="w-full max-w-md rounded-xl border border-neutral-800 bg-neutral-950 p-5 shadow-xl">
            <header class="mb-4 flex items-center justify-between">
                <h2 class="text-base font-semibold">Installer Discord</h2>
                <button
                    type="button"
                    onclick={reset}
                    class="rounded p-1 text-neutral-500 hover:bg-neutral-800 hover:text-neutral-200"
                ><X size={16} /></button>
            </header>

            {#if result === null}
                <form class="space-y-3" onsubmit={submit}>
                    <p class="rounded border border-neutral-800 bg-neutral-900/60 p-2.5 text-xs text-neutral-400">
                        Récupère un token bot sur
                        <a
                            href="https://discord.com/developers/applications"
                            target="_blank"
                            rel="noopener"
                            class="text-cyan-400 underline"
                        >discord.com/developers</a>
                        (New Application → Bot → Reset Token). Active l'intent
                        <span class="font-mono">Message Content</span>.
                    </p>

                    <label class="block">
                        <span class="text-xs text-neutral-400">Token bot Discord</span>
                        <input
                            type="password"
                            bind:value={token}
                            required
                            minlength="20"
                            placeholder="MTIzNDU2Nzg5..."
                            class="mt-1 w-full rounded border border-neutral-700 bg-neutral-900 px-2 py-1.5 font-mono text-xs text-neutral-200 focus:border-cyan-500/50 focus:outline-none"
                        />
                    </label>

                    <label class="block">
                        <span class="text-xs text-neutral-400">Persona (system prompt)</span>
                        <textarea
                            bind:value={bot_persona}
                            rows="4"
                            class="mt-1 w-full rounded border border-neutral-700 bg-neutral-900 px-2 py-1.5 text-xs text-neutral-200 focus:border-cyan-500/50 focus:outline-none"
                        ></textarea>
                    </label>

                    <label class="block">
                        <span class="text-xs text-neutral-400">
                            Modèle par défaut (optionnel)
                        </span>
                        <input
                            type="text"
                            bind:value={default_model}
                            placeholder="qwen2.5:14b"
                            class="mt-1 w-full rounded border border-neutral-700 bg-neutral-900 px-2 py-1.5 font-mono text-xs text-neutral-200 focus:border-cyan-500/50 focus:outline-none"
                        />
                    </label>

                    <label class="flex items-center gap-2 text-xs text-neutral-400">
                        <input type="checkbox" bind:checked={respond_dm} />
                        Répondre aux messages privés
                    </label>

                    <div class="flex justify-end gap-2 pt-2">
                        <button
                            type="button"
                            onclick={reset}
                            class="rounded px-3 py-1.5 text-sm text-neutral-400 hover:bg-neutral-800"
                        >Annuler</button>
                        <button
                            type="submit"
                            disabled={installing || !token.trim()}
                            class="flex items-center gap-2 rounded-lg bg-cyan-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-cyan-500 disabled:opacity-50"
                        >
                            {#if installing}<Loader2 size={14} class="animate-spin" />{/if}
                            Installer
                        </button>
                    </div>
                </form>
            {:else}
                <div class="space-y-3">
                    <div class="flex items-start gap-2 rounded border border-emerald-900/40 bg-emerald-950/20 px-3 py-2 text-xs text-emerald-300">
                        <CheckCircle2 size={14} class="mt-0.5 shrink-0" />
                        <div>
                            Bot installé ! Statut actuel :
                            <span class="font-mono">{result.status}</span>.
                            Les 5 tools <code>spouet-*</code> sont auto-activés sur les conversations Discord.
                        </div>
                    </div>

                    {#if result.invite_url}
                        <a
                            href={result.invite_url}
                            target="_blank"
                            rel="noopener"
                            class="flex items-center justify-center gap-2 rounded-lg bg-cyan-600 px-3 py-2 text-sm font-medium text-white hover:bg-cyan-500"
                        >
                            <ExternalLink size={14} />
                            Inviter le bot sur un serveur
                        </a>
                    {:else}
                        <p class="text-xs text-neutral-500">
                            En attente du handshake Discord (le bot doit se connecter pour
                            que l'URL d'invitation soit générée).
                            <strong>Rafraîchis la page</strong> dans quelques secondes.
                        </p>
                    {/if}

                    <button
                        type="button"
                        onclick={reset}
                        class="w-full rounded px-3 py-1.5 text-sm text-neutral-400 hover:bg-neutral-800"
                    >Fermer</button>
                </div>
            {/if}
        </div>
    </div>
{/if}
