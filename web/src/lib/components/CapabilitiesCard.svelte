<script lang="ts">
    import type { NodeCapabilities } from '$lib/api';
    import { Cpu, AlertTriangle, ShieldCheck, Info } from 'lucide-svelte';

    let { caps, agentVersion = null }: { caps: NodeCapabilities | null; agentVersion?: string | null } = $props();

    const classLabel: Record<NodeCapabilities['compute_class'], string> = {
        cpu: 'CPU',
        cuda: 'CUDA',
        rocm: 'ROCm'
    };

    const classColor: Record<NodeCapabilities['compute_class'], string> = {
        cpu: 'bg-neutral-700 text-neutral-200',
        cuda: 'bg-emerald-900/50 text-emerald-300',
        rocm: 'bg-red-900/50 text-red-300'
    };

    const kindLabel: Record<NodeCapabilities['gpu_kind'], string> = {
        none: 'pas de GPU',
        igpu: 'iGPU (ignoré)',
        dgpu: 'GPU dédié'
    };
</script>

<section class="rounded-xl border border-neutral-800 bg-neutral-900/60 p-4">
    <div class="mb-3 flex items-center justify-between">
        <h2 class="flex items-center gap-2 text-xs font-medium uppercase tracking-wider text-neutral-400">
            <Cpu size={12} />
            Capabilities détectées
        </h2>
        {#if agentVersion}
            <span class="text-[10px] text-neutral-600">agent {agentVersion}</span>
        {/if}
    </div>

    {#if caps === null}
        <p class="text-xs text-neutral-500">
            Aucune capability remontée. L'agent est probablement à une version &lt; 0.3.0.
            Mets-le à jour pour avoir la détection GPU/iGPU complète.
        </p>
    {:else}
        <div class="grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
            <div>
                <dt class="text-xs text-neutral-500">Compute</dt>
                <dd class="mt-0.5">
                    <span class="rounded px-1.5 py-0.5 text-[10px] {classColor[caps.compute_class]}">
                        {classLabel[caps.compute_class]}
                    </span>
                </dd>
            </div>
            <div>
                <dt class="text-xs text-neutral-500">GPU</dt>
                <dd class="text-xs">{kindLabel[caps.gpu_kind]}</dd>
            </div>
            <div class="col-span-2">
                <dt class="text-xs text-neutral-500">Variante llama-server</dt>
                <dd class="font-mono text-xs">{caps.llama_variant}</dd>
            </div>
            <div class="col-span-2">
                <dt class="text-xs text-neutral-500">CPU</dt>
                <dd class="truncate text-xs" title={caps.cpu_model ?? '—'}>
                    {caps.cpu_model ?? '—'} · {caps.cpu_physical_cores} cœurs
                </dd>
            </div>
            {#if caps.gpu_model}
                <div class="col-span-2">
                    <dt class="text-xs text-neutral-500">GPU détecté</dt>
                    <dd class="truncate text-xs" title={caps.gpu_model}>
                        {caps.gpu_model}{caps.vram_total_mb ? ` · ${caps.vram_total_mb} MB` : ''}
                    </dd>
                </div>
            {/if}
            {#if caps.cpu_features.length > 0}
                <div class="col-span-2 sm:col-span-4">
                    <dt class="text-xs text-neutral-500">CPU features</dt>
                    <dd class="mt-1 flex flex-wrap gap-1">
                        {#each caps.cpu_features as f}
                            <span class="rounded bg-neutral-800 px-1.5 py-0.5 font-mono text-[10px] text-neutral-400">{f}</span>
                        {/each}
                    </dd>
                </div>
            {/if}
        </div>

        {#if caps.force_cpu}
            <div class="mt-3 flex items-start gap-2 rounded border border-amber-900/40 bg-amber-950/20 px-2.5 py-2 text-xs text-amber-300">
                <ShieldCheck size={14} class="mt-0.5 shrink-0" />
                <div>
                    <strong>SPOUET_FORCE_CPU activé.</strong> Détection GPU désactivée par configuration.
                </div>
            </div>
        {/if}

        {#if caps.warnings.length > 0}
            <div class="mt-3 space-y-1">
                {#each caps.warnings as w}
                    <div class="flex items-start gap-2 rounded border border-amber-900/40 bg-amber-950/20 px-2.5 py-1.5 text-xs text-amber-300">
                        <AlertTriangle size={12} class="mt-0.5 shrink-0" />
                        <span>{w}</span>
                    </div>
                {/each}
            </div>
        {/if}

        {#if caps.detection_notes.length > 0}
            <details class="mt-3 text-xs text-neutral-500">
                <summary class="flex cursor-pointer items-center gap-1.5 hover:text-neutral-300">
                    <Info size={11} /> Notes de détection ({caps.detection_notes.length})
                </summary>
                <ul class="mt-2 space-y-0.5 pl-4 font-mono text-[11px]">
                    {#each caps.detection_notes as n}
                        <li>• {n}</li>
                    {/each}
                </ul>
            </details>
        {/if}
    {/if}
</section>
