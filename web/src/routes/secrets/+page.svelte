<script lang="ts">
    import { onMount } from 'svelte';
    import { fly } from 'svelte/transition';
    import { secrets as secretsApi, type SecretOut } from '$lib/api';
    import EmptyState from '$lib/components/EmptyState.svelte';
    import { toast } from '$lib/toast.svelte';
    import { KeyRound, Trash2, Plus, AlertTriangle } from 'lucide-svelte';

    let items: SecretOut[] = $state([]);
    let loading = $state(true);
    let creating = $state(false);

    let scope = $state('');
    let key = $state('');
    let value = $state('');
    let description = $state('');

    const SUGGESTED_SCOPES = [
        { value: 'global', label: 'global (constantes partagées)' },
        { value: 'connector:discord-bot', label: 'connector:discord-bot' },
        { value: 'tool:vaultwarden', label: 'tool:vaultwarden (legacy)' }
    ];

    async function load() {
        loading = true;
        try {
            items = await secretsApi.list();
        } catch {
            toast.error('Impossible de charger le coffre');
        } finally {
            loading = false;
        }
    }

    async function submit(e: Event) {
        e.preventDefault();
        if (!scope.trim() || !key.trim() || !value) return;
        creating = true;
        try {
            await secretsApi.upsert({
                scope: scope.trim(),
                key: key.trim(),
                value,
                description: description.trim()
            });
            toast.success(`Secret ${scope.trim()}/${key.trim()} enregistré`);
            scope = '';
            key = '';
            value = '';
            description = '';
            await load();
        } catch {
            toast.error("Échec de l'enregistrement");
        } finally {
            creating = false;
        }
    }

    async function remove(s: SecretOut) {
        if (!confirm(`Supprimer ${s.scope}/${s.key} ?`)) return;
        try {
            await secretsApi.delete(s.scope, s.key);
            await load();
        } catch {
            toast.error('Suppression échouée');
        }
    }

    const grouped = $derived.by(() => {
        const m = new Map<string, SecretOut[]>();
        for (const s of items) {
            const arr = m.get(s.scope) ?? [];
            arr.push(s);
            m.set(s.scope, arr);
        }
        return [...m.entries()].sort(([a], [b]) => a.localeCompare(b));
    });

    onMount(load);
</script>

<header
    class="flex items-center justify-between border-b border-[var(--color-border-subtle)]
           bg-[color-mix(in_oklch,var(--color-bg-0)_70%,transparent)] px-6 py-3 backdrop-blur sm:px-8"
>
    <div>
        <h1 class="flex items-center gap-2 text-lg font-medium">
            <KeyRound size={16} class="text-cyan-400" />
            Coffre de secrets
        </h1>
        <p class="text-xs text-neutral-500">
            Chiffrés Fernet (clé dérivée de SPOUET_SECRET_KEY). Les valeurs ne sont jamais
            réaffichées en clair.
        </p>
    </div>
</header>

<div class="flex-1 overflow-y-auto px-4 py-6 sm:px-8">
    <div class="mx-auto max-w-4xl space-y-8">
        <section
            class="glass rounded-2xl border border-[var(--color-border)] p-5"
            in:fly={{ y: 6, duration: 180 }}
        >
            <h2 class="mb-3 flex items-center gap-2 text-sm font-medium text-neutral-200">
                <Plus size={14} class="text-cyan-400" /> Ajouter / mettre à jour
            </h2>
            <form onsubmit={submit} class="grid gap-3 sm:grid-cols-2">
                <label class="flex flex-col gap-1 text-xs">
                    <span class="text-neutral-400">Scope</span>
                    <input
                        list="scope-suggestions"
                        bind:value={scope}
                        placeholder="connector:discord-bot"
                        required
                        class="rounded-md border border-[var(--color-border)] bg-[var(--color-bg-1)]
                               px-2 py-1.5 text-sm text-neutral-100 focus:border-cyan-500/50
                               focus:outline-none"
                    />
                    <datalist id="scope-suggestions">
                        {#each SUGGESTED_SCOPES as s}
                            <option value={s.value}>{s.label}</option>
                        {/each}
                    </datalist>
                </label>
                <label class="flex flex-col gap-1 text-xs">
                    <span class="text-neutral-400">Clé</span>
                    <input
                        bind:value={key}
                        placeholder="token / api_key / master_password"
                        required
                        class="rounded-md border border-[var(--color-border)] bg-[var(--color-bg-1)]
                               px-2 py-1.5 text-sm text-neutral-100 focus:border-cyan-500/50
                               focus:outline-none"
                    />
                </label>
                <label class="flex flex-col gap-1 text-xs sm:col-span-2">
                    <span class="text-neutral-400">Valeur (sera chiffrée)</span>
                    <input
                        bind:value
                        type="password"
                        autocomplete="new-password"
                        required
                        class="rounded-md border border-[var(--color-border)] bg-[var(--color-bg-1)]
                               px-2 py-1.5 font-mono text-sm text-neutral-100 focus:border-cyan-500/50
                               focus:outline-none"
                    />
                </label>
                <label class="flex flex-col gap-1 text-xs sm:col-span-2">
                    <span class="text-neutral-400">Description (optionnel)</span>
                    <input
                        bind:value={description}
                        placeholder="Token bot Discord (compte spouet#1234)"
                        class="rounded-md border border-[var(--color-border)] bg-[var(--color-bg-1)]
                               px-2 py-1.5 text-sm text-neutral-100 focus:border-cyan-500/50
                               focus:outline-none"
                    />
                </label>
                <div class="sm:col-span-2 flex justify-end">
                    <button
                        type="submit"
                        disabled={creating}
                        class="rounded-lg bg-cyan-600 px-4 py-1.5 text-xs font-medium text-white
                               disabled:opacity-40 hover:bg-cyan-500"
                    >
                        {creating ? 'Enregistrement…' : 'Enregistrer'}
                    </button>
                </div>
            </form>
        </section>

        {#if loading}
            <p class="text-xs text-neutral-500">Chargement…</p>
        {:else if items.length === 0}
            <EmptyState
                icon={KeyRound}
                title="Coffre vide"
                description="Ajoute un premier secret pour qu'un tool ou un connector puisse y accéder."
            />
        {:else}
            {#each grouped as [scopeName, group] (scopeName)}
                <section class="rounded-xl border border-[var(--color-border-subtle)] p-4">
                    <h3
                        class="mb-2 font-mono text-xs uppercase tracking-wider text-cyan-400"
                    >
                        {scopeName}
                    </h3>
                    <div class="space-y-2">
                        {#each group as s (s.scope + s.key)}
                            <div
                                class="flex items-center justify-between gap-3 rounded-lg
                                       border border-[var(--color-border-subtle)] bg-neutral-900/40
                                       px-3 py-2"
                            >
                                <div class="min-w-0 flex-1">
                                    <p class="font-mono text-sm text-neutral-100">
                                        {s.key}
                                        {#if !s.decryptable}
                                            <span
                                                class="ml-2 inline-flex items-center gap-1 text-amber-400"
                                                title="Impossible de déchiffrer (clé changée ?)"
                                            >
                                                <AlertTriangle size={12} />
                                            </span>
                                        {/if}
                                    </p>
                                    <p class="font-mono text-xs text-neutral-500">{s.preview}</p>
                                    {#if s.description}
                                        <p class="mt-0.5 text-xs text-neutral-400">
                                            {s.description}
                                        </p>
                                    {/if}
                                </div>
                                <button
                                    type="button"
                                    onclick={() => remove(s)}
                                    class="rounded p-1.5 text-neutral-500 hover:bg-red-500/10
                                           hover:text-red-400"
                                    title="Supprimer"
                                    aria-label="Supprimer"
                                >
                                    <Trash2 size={14} />
                                </button>
                            </div>
                        {/each}
                    </div>
                </section>
            {/each}
        {/if}
    </div>
</div>
