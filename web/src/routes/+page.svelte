<script lang="ts">
    import { onMount } from 'svelte';
    import { fly } from 'svelte/transition';
    import { Server, Wrench, Clock, Cpu } from 'lucide-svelte';
    import {
        nodes as nodesApi,
        tools as toolsApi,
        jobs as jobsApi,
        type NodeOut,
        type ToolOut,
        type JobOut
    } from '$lib/api';
    import StatusDot from '$lib/components/StatusDot.svelte';
    import Skeleton from '$lib/components/Skeleton.svelte';
    import EmptyState from '$lib/components/EmptyState.svelte';

    let nodeList: NodeOut[] = $state([]);
    let toolList: ToolOut[] = $state([]);
    let jobList: JobOut[] = $state([]);
    let loaded = $state(false);

    onMount(async () => {
        [nodeList, toolList, jobList] = await Promise.all([
            nodesApi.list().catch(() => []),
            toolsApi.list().catch(() => []),
            jobsApi.list().catch(() => [])
        ]);
        loaded = true;
    });

    const onlineCount = $derived(nodeList.filter((n) => n.status === 'online').length);
    const totalModels = $derived(new Set(nodeList.flatMap((n) => n.models.map((m) => m.name))).size);
    const enabledTools = $derived(toolList.filter((t) => t.enabled).length);
    const activeJobs = $derived(jobList.filter((j) => j.enabled).length);

    const stats = $derived([
        { icon: Server, label: 'Nodes en ligne', val: `${onlineCount}/${nodeList.length}`, accent: 'cyan' },
        { icon: Cpu, label: 'Modèles disponibles', val: totalModels, accent: 'purple' },
        { icon: Wrench, label: 'Tools actifs', val: enabledTools, accent: 'emerald' },
        { icon: Clock, label: 'Tâches planifiées', val: activeJobs, accent: 'amber' }
    ]);
</script>

<header class="px-6 pt-6 pb-2 sm:px-8">
    <h1 class="text-2xl font-semibold tracking-tight">Tableau de bord</h1>
    <p class="mt-1 text-sm text-neutral-500">État global de votre cluster Spouet.</p>
</header>

<div class="grid gap-3 px-6 pt-4 sm:grid-cols-2 sm:px-8 lg:grid-cols-4">
    {#each stats as s, i}
        <article
            in:fly={{ y: 8, duration: 240, delay: i * 60 }}
            class="group relative overflow-hidden rounded-2xl border border-[var(--color-border-subtle)]
                   bg-gradient-to-br from-[var(--color-bg-1)] to-[var(--color-bg-0)]
                   p-5 transition-transform hover:-translate-y-0.5"
        >
            <div
                class="absolute -right-8 -top-8 h-24 w-24 rounded-full opacity-0 blur-2xl
                       transition-opacity group-hover:opacity-100"
                class:bg-cyan-500={s.accent === 'cyan'}
                class:bg-purple-500={s.accent === 'purple'}
                class:bg-emerald-500={s.accent === 'emerald'}
                class:bg-amber-500={s.accent === 'amber'}
            ></div>
            <div class="relative">
                <div class="mb-3 flex items-center gap-2 text-neutral-500">
                    <s.icon size={14} />
                    <span class="text-xs uppercase tracking-wider">{s.label}</span>
                </div>
                <div class="text-3xl font-light tracking-tight text-neutral-100">{s.val}</div>
            </div>
        </article>
    {/each}
</div>

<section class="px-6 pt-8 pb-6 sm:px-8">
    <h2 class="mb-3 text-xs font-medium uppercase tracking-wider text-neutral-500">Nodes</h2>

    {#if !loaded}
        <div class="grid gap-3 sm:grid-cols-2">
            {#each Array(2) as _}
                <div class="rounded-xl border border-neutral-800 bg-neutral-900/40 p-4">
                    <Skeleton h="h-4" w="w-1/3" />
                    <div class="mt-4 space-y-2">
                        <Skeleton h="h-3" />
                        <Skeleton h="h-3" w="w-3/4" />
                    </div>
                </div>
            {/each}
        </div>
    {:else if nodeList.length === 0}
        <EmptyState
            icon={Server}
            title="Aucun node enregistré"
            description="Démarrez un spouet-agent sur une machine Ollama et il apparaîtra ici."
        />
    {:else}
        <div class="grid gap-3 sm:grid-cols-2">
            {#each nodeList as n, i (n.id)}
                <article
                    in:fly={{ y: 6, duration: 220, delay: i * 40 }}
                    class="rounded-xl border border-[var(--color-border-subtle)] bg-[var(--color-bg-1)] p-4"
                >
                    <div class="mb-3 flex items-center justify-between">
                        <div class="flex items-center gap-2">
                            <StatusDot online={n.status === 'online'} />
                            <h3 class="font-medium">{n.name}</h3>
                        </div>
                        <span class="text-xs text-neutral-500">{n.host}:{n.port}</span>
                    </div>
                    <dl class="grid grid-cols-2 gap-2 text-sm">
                        <div>
                            <dt class="text-[10px] uppercase tracking-wider text-neutral-500">GPU</dt>
                            <dd class="truncate text-neutral-300">{n.gpu_model ?? '—'}</dd>
                        </div>
                        <div>
                            <dt class="text-[10px] uppercase tracking-wider text-neutral-500">VRAM</dt>
                            <dd class="text-neutral-300">
                                {n.vram_used_mb ?? '—'} / {n.vram_total_mb ?? '—'} MB
                            </dd>
                        </div>
                        <div>
                            <dt class="text-[10px] uppercase tracking-wider text-neutral-500">Modèles</dt>
                            <dd class="text-neutral-300">{n.models.length}</dd>
                        </div>
                        <div>
                            <dt class="text-[10px] uppercase tracking-wider text-neutral-500">Agent</dt>
                            <dd class="text-neutral-300">{n.agent_version ?? '—'}</dd>
                        </div>
                    </dl>
                </article>
            {/each}
        </div>
    {/if}
</section>
