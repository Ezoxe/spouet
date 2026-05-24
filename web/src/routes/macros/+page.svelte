<script lang="ts">
    import { onMount } from 'svelte';
    import { fly, fade } from 'svelte/transition';
    import {
        desktop,
        ApiError,
        type MacroOut,
        type MacroStep,
        type DesktopCapabilities
    } from '$lib/api';
    import { toast } from '$lib/toast.svelte';
    import { Plus, Play, Trash2, Pencil, Save, X, MonitorPlay, Wifi, WifiOff } from 'lucide-svelte';

    let macros: MacroOut[] = $state([]);
    let caps: DesktopCapabilities | null = $state(null);
    let showForm = $state(false);
    let form: { id?: string; name: string; description: string; steps: MacroStep[] } = $state({
        name: '',
        description: '',
        steps: []
    });
    let busy = $state(false);

    async function refresh() {
        [macros, caps] = await Promise.all([
            desktop.macros().catch(() => []),
            desktop.capabilities().catch(() => null)
        ]);
    }
    onMount(refresh);

    function newMacro() {
        form = { name: '', description: '', steps: [{ action: 'launch_app', app: '' }] };
        showForm = true;
    }
    function editMacro(m: MacroOut) {
        form = {
            id: m.id,
            name: m.name,
            description: m.description,
            steps: m.steps.map((s) => ({ ...s }))
        };
        showForm = true;
    }
    function addStep() {
        form.steps = [...form.steps, { action: 'launch_app', app: '' }];
    }
    function removeStep(i: number) {
        form.steps = form.steps.filter((_, j) => j !== i);
    }

    async function save() {
        if (!form.name.trim() || form.steps.length === 0) {
            toast.error('Un nom et au moins une étape sont requis');
            return;
        }
        busy = true;
        try {
            const payload = {
                name: form.name.trim(),
                description: form.description.trim(),
                steps: form.steps
            };
            if (form.id) await desktop.patchMacro(form.id, payload);
            else await desktop.createMacro(payload);
            showForm = false;
            await refresh();
            toast.success('Macro enregistrée');
        } catch (e) {
            const detail =
                e instanceof ApiError && e.body && typeof e.body === 'object'
                    ? JSON.stringify((e.body as { detail?: unknown }).detail ?? e.body)
                    : '';
            toast.error(`Enregistrement impossible. ${detail}`);
        } finally {
            busy = false;
        }
    }

    async function run(m: MacroOut) {
        try {
            const r = await desktop.runMacro(m.id);
            toast.success(`« ${m.name} » lancée (${r.status})`);
        } catch (e) {
            if (e instanceof ApiError && e.status === 409) {
                toast.error("L'app Windows Spouet n'est pas connectée.");
            } else {
                toast.error('Échec du lancement');
            }
        }
    }

    async function del(m: MacroOut) {
        if (!confirm(`Supprimer la macro « ${m.name} » ?`)) return;
        try {
            await desktop.deleteMacro(m.id);
            await refresh();
        } catch {
            toast.error('Suppression impossible');
        }
    }

    function stepSummary(s: MacroStep): string {
        const where = s.monitor ? ` → écran ${s.monitor}${s.mode ? ` (${s.mode})` : ''}` : '';
        if (s.action === 'launch_app') return `Lancer ${s.app || '?'}${where}`;
        if (s.action === 'open_url') return `Ouvrir ${s.url || '?'}${where}`;
        return s.action;
    }
</script>

<header class="flex items-center justify-between px-6 py-5 sm:px-8">
    <div>
        <h1 class="text-2xl font-semibold tracking-tight">Macros PC</h1>
        <p class="mt-1 text-xs text-neutral-500">
            Séquences d'actions bureau (« soirée Minecraft » : lancer CurseForge, ouvrir YouTube sur
            le 2ᵉ écran…). Exécutées par l'app Windows. L'IA peut aussi les créer en conversation.
        </p>
    </div>
    <button
        type="button"
        onclick={newMacro}
        class="flex items-center gap-1.5 rounded-lg bg-cyan-600 px-3 py-2 text-sm font-medium
               text-white hover:bg-cyan-500"
    >
        <Plus size={16} /> Nouvelle macro
    </button>
</header>

<div class="flex-1 overflow-y-auto px-6 pb-8 sm:px-8">
    <!-- État du client desktop -->
    <div
        class="mb-5 flex items-center gap-2 rounded-lg border px-3 py-2 text-xs
               {caps?.connected
            ? 'border-emerald-900/50 bg-emerald-950/30 text-emerald-200'
            : 'border-neutral-800 bg-neutral-900/40 text-neutral-400'}"
    >
        {#if caps?.connected}
            <Wifi size={14} />
            <span
                >App Windows connectée — {caps.monitors.length} écran(s), {caps.apps.length} application(s)
                détectée(s).</span
            >
        {:else}
            <WifiOff size={14} />
            <span>App Windows non connectée. Ouvre Spouet sur ton PC pour lancer des macros.</span>
        {/if}
    </div>

    {#if macros.length === 0}
        <div class="grid place-items-center py-16 text-center text-neutral-600" in:fade>
            <MonitorPlay size={40} class="mb-3 opacity-40" />
            <p class="text-sm">Aucune macro pour l'instant.</p>
            <p class="mt-1 text-xs">
                Crée-en une, ou dis simplement à Spouet « ce soir, soirée Minecraft ».
            </p>
        </div>
    {:else}
        <div class="grid gap-3 sm:grid-cols-2">
            {#each macros as m (m.id)}
                <div
                    in:fly={{ y: 6, duration: 160 }}
                    class="rounded-xl border border-[var(--color-border-subtle)] bg-[var(--color-bg-1)] p-4"
                >
                    <div class="flex items-start justify-between gap-2">
                        <div class="min-w-0">
                            <h3 class="truncate font-medium">{m.name}</h3>
                            {#if m.description}
                                <p class="mt-0.5 text-xs text-neutral-500">{m.description}</p>
                            {/if}
                        </div>
                        <div class="flex shrink-0 gap-1">
                            <button
                                type="button"
                                onclick={() => run(m)}
                                class="rounded-md p-1.5 text-cyan-300 hover:bg-cyan-950/50"
                                title="Lancer"
                                aria-label="Lancer"><Play size={15} /></button
                            >
                            <button
                                type="button"
                                onclick={() => editMacro(m)}
                                class="rounded-md p-1.5 text-neutral-400 hover:bg-white/5"
                                title="Modifier"
                                aria-label="Modifier"><Pencil size={15} /></button
                            >
                            <button
                                type="button"
                                onclick={() => del(m)}
                                class="rounded-md p-1.5 text-neutral-400 hover:bg-red-950 hover:text-red-300"
                                title="Supprimer"
                                aria-label="Supprimer"><Trash2 size={15} /></button
                            >
                        </div>
                    </div>
                    <ol class="mt-3 space-y-1 text-xs text-neutral-400">
                        {#each m.steps as s, i}
                            <li class="flex gap-2">
                                <span class="text-neutral-600">{i + 1}.</span>
                                <span>{stepSummary(s)}</span>
                            </li>
                        {/each}
                    </ol>
                </div>
            {/each}
        </div>
    {/if}
</div>

{#if showForm}
    <div
        class="fixed inset-0 z-50 grid place-items-center bg-black/60 p-4 backdrop-blur-sm"
        in:fade={{ duration: 120 }}
    >
        <div
            class="w-full max-w-lg rounded-2xl border border-[var(--color-border-subtle)]
                   bg-[var(--color-bg-1)] p-5 shadow-2xl"
            in:fly={{ y: 10, duration: 180 }}
        >
            <div class="mb-4 flex items-center justify-between">
                <h2 class="text-lg font-semibold">{form.id ? 'Modifier' : 'Nouvelle'} macro</h2>
                <button
                    type="button"
                    onclick={() => (showForm = false)}
                    class="rounded p-1 text-neutral-500 hover:text-neutral-200"
                    aria-label="Fermer"><X size={18} /></button
                >
            </div>

            <label class="mb-3 block">
                <span class="mb-1 block text-xs text-neutral-400">Nom</span>
                <input
                    bind:value={form.name}
                    placeholder="soirée Minecraft"
                    class="w-full rounded-lg border border-[var(--color-border-subtle)] bg-[var(--color-bg-2)]
                           px-3 py-2 text-sm focus:border-cyan-500/40 focus:outline-none"
                />
            </label>
            <label class="mb-3 block">
                <span class="mb-1 block text-xs text-neutral-400">Description (optionnel)</span>
                <input
                    bind:value={form.description}
                    class="w-full rounded-lg border border-[var(--color-border-subtle)] bg-[var(--color-bg-2)]
                           px-3 py-2 text-sm focus:border-cyan-500/40 focus:outline-none"
                />
            </label>

            <div class="mb-2 flex items-center justify-between">
                <span class="text-xs text-neutral-400">Étapes</span>
                <button
                    type="button"
                    onclick={addStep}
                    class="flex items-center gap-1 rounded-md px-2 py-1 text-xs text-cyan-300 hover:bg-cyan-950/40"
                    ><Plus size={12} /> Ajouter</button
                >
            </div>

            <div class="max-h-64 space-y-2 overflow-y-auto pr-1">
                {#each form.steps as step, i (i)}
                    <div
                        class="rounded-lg border border-[var(--color-border-subtle)] bg-[var(--color-bg-2)] p-2.5"
                    >
                        <div class="flex items-center gap-2">
                            <select
                                bind:value={step.action}
                                class="rounded bg-[var(--color-bg-1)] px-2 py-1 text-xs focus:outline-none"
                            >
                                <option value="launch_app">Lancer une app</option>
                                <option value="open_url">Ouvrir une URL</option>
                            </select>
                            {#if step.action === 'launch_app'}
                                <input
                                    bind:value={step.app}
                                    placeholder="CurseForge"
                                    class="min-w-0 flex-1 rounded bg-[var(--color-bg-1)] px-2 py-1 text-xs focus:outline-none"
                                />
                            {:else}
                                <input
                                    bind:value={step.url}
                                    placeholder="https://youtube.com"
                                    class="min-w-0 flex-1 rounded bg-[var(--color-bg-1)] px-2 py-1 text-xs focus:outline-none"
                                />
                            {/if}
                            <button
                                type="button"
                                onclick={() => removeStep(i)}
                                class="rounded p-1 text-neutral-500 hover:text-red-300"
                                aria-label="Retirer l'étape"><Trash2 size={13} /></button
                            >
                        </div>
                        <div class="mt-2 flex items-center gap-2 text-[11px] text-neutral-500">
                            <span>Écran</span>
                            <input
                                type="number"
                                min="1"
                                bind:value={step.monitor}
                                placeholder="—"
                                class="w-14 rounded bg-[var(--color-bg-1)] px-2 py-1 text-xs focus:outline-none"
                            />
                            <select
                                bind:value={step.mode}
                                class="rounded bg-[var(--color-bg-1)] px-2 py-1 text-xs focus:outline-none"
                            >
                                <option value={undefined}>fenêtré</option>
                                <option value="maximized">maximisé</option>
                                <option value="fullscreen">plein écran</option>
                            </select>
                        </div>
                    </div>
                {/each}
            </div>

            <div class="mt-5 flex justify-end gap-2">
                <button
                    type="button"
                    onclick={() => (showForm = false)}
                    class="rounded-lg border border-neutral-700 px-3 py-2 text-sm hover:bg-neutral-800"
                    >Annuler</button
                >
                <button
                    type="button"
                    onclick={save}
                    disabled={busy}
                    class="flex items-center gap-1.5 rounded-lg bg-cyan-600 px-3 py-2 text-sm font-medium
                           text-white hover:bg-cyan-500 disabled:opacity-50"
                >
                    <Save size={15} /> Enregistrer
                </button>
            </div>
        </div>
    </div>
{/if}
