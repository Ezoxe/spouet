<script lang="ts">
    import { onMount } from 'svelte';
    import { page } from '$app/stores';
    import {
        nodes as nodesApi,
        type NodeOut,
        type LocalModelOut,
        ApiError
    } from '$lib/api';
    import { toast } from '$lib/toast.svelte';
    import { downloads } from '$lib/downloads.svelte';
    import {
        Download, Play, Trash2, Settings, Loader2, ChevronLeft, HardDrive, Cpu, MemoryStick, Zap, Activity
    } from 'lucide-svelte';
    import { goto } from '$app/navigation';
    import CapabilitiesCard from '$lib/components/CapabilitiesCard.svelte';
    import TimeSeriesChart, { type Series } from '$lib/components/TimeSeriesChart.svelte';
    import type { MetricsRange, NodeMetricsOut } from '$lib/api';

    const nodeId = $derived($page.params.id);

    let node: NodeOut | null = $state(null);
    let localModels: LocalModelOut[] = $state([]);
    let loading = $state(true);
    let modelsLoading = $state(false);
    let pullStatus: Record<string, unknown> | null = $state(null);

    // Formulaire pull
    let showPullForm = $state(false);
    let pullForm = $state({ hf_repo: '', filename: '' });
    let pulling = $state(false);

    // Formulaire config llama
    let showConfig = $state(false);
    let configForm = $state({ n_ctx: 8192, n_gpu_layers: -1, n_batch: 512, n_parallel: 1 });
    let configSaving = $state(false);

    // Modèle à charger
    let loadingModel: string | null = $state(null);

    // Génération d'images (sur le node)
    let imageStatus: Record<string, unknown> | null = $state(null);
    let imageModelInput = $state('');
    let imagePulling = $state(false);
    let imagePullStatus: Record<string, unknown> | null = $state(null);
    let imageLoading = $state(false);
    let imageModelsList = $state<{ repo: string; size_bytes: number; active: boolean }[]>([]);

    // Historique
    let histRange: MetricsRange = $state('1h');
    let histData: NodeMetricsOut | null = $state(null);
    let histLoading = $state(false);

    // Copie de diag
    let copyingDiag = $state(false);
    async function copyDiag(): Promise<void> {
        if (!nodeId) return;
        copyingDiag = true;
        try {
            const diag = await nodesApi.diag(nodeId);
            await navigator.clipboard.writeText(JSON.stringify(diag, null, 2));
            toast.success('Diag copié dans le presse-papier.');
        } catch (e) {
            toast.error('Échec de la copie du diag.');
        } finally {
            copyingDiag = false;
        }
    }

    async function loadHistory(range: MetricsRange, silent = false): Promise<void> {
        if (!nodeId) return;
        if (!silent) histLoading = true;
        histRange = range;
        try {
            histData = await nodesApi.metrics(nodeId, range);
        } catch {
            if (!silent) histData = null;
        } finally {
            if (!silent) histLoading = false;
        }
    }

    // Un graphique INDÉPENDANT par métrique (échelle propre, plus lisible qu'un
    // gros multi-séries). RAM/VRAM bornées au total matériel (échelle réaliste).
    interface MetricChart extends Series {}

    // Parse défensif : un timestamp sans fuseau (ancien backend) est interprété
    // comme UTC, pas comme heure locale, pour éviter tout décalage horaire.
    function parseTime(s: string): number {
        return /([zZ]|[+-]\d\d:?\d\d)$/.test(s) ? Date.parse(s) : Date.parse(s + 'Z');
    }

    // Fraîcheur : âge (s) du point le plus récent, pour signaler des données figées.
    const dataAgeS = $derived.by(() => {
        if (!histData || histData.series.length === 0) return null;
        const last = histData.series[histData.series.length - 1];
        return Math.round((Date.now() - parseTime(last.time)) / 1000);
    });

    const metricCharts = $derived.by<MetricChart[]>(() => {
        if (!histData) return [];
        const pts = histData.series.map((p) => ({ time: parseTime(p.time), p }));
        const mk = (
            label: string,
            color: string,
            unit: string,
            precision: number,
            get: (p: (typeof pts)[number]['p']) => number | null,
            min?: number,
            max?: number
        ): MetricChart => ({
            label,
            color,
            unit,
            precision,
            min,
            max,
            points: pts.map(({ time, p }) => ({ time, value: get(p) }))
        });
        const ramMax = node?.ram_total_mb ?? undefined;
        const vramMax = node?.vram_total_mb ?? undefined;
        const charts: MetricChart[] = [
            mk('CPU', 'rgb(96 165 250)', ' %', 0, (p) => p.cpu_pct, 0, 100),
            mk('RAM', 'rgb(168 85 247)', ' MB', 0, (p) => p.ram_used_mb, 0, ramMax)
        ];
        if (vramMax) charts.push(mk('VRAM', 'rgb(34 211 238)', ' MB', 0, (p) => p.vram_used_mb, 0, vramMax));
        charts.push(
            mk('Débit (tok/s)', 'rgb(16 185 129)', '', 1, (p) => p.llama_tps, 0),
            mk('Slots actifs', 'rgb(251 191 36)', '', 0, (p) => p.llama_slots_active, 0),
            mk('Réseau ↓', 'rgb(244 114 182)', ' kbps', 0, (p) => p.net_rx_kbps, 0)
        );
        return charts;
    });

    function lastVal(c: MetricChart): string {
        for (let i = c.points.length - 1; i >= 0; i--) {
            const v = c.points[i].value;
            if (v != null) return v.toFixed(c.precision ?? 0) + (c.unit ?? '');
        }
        return '—';
    }

    function fmtSize(bytes: number): string {
        if (bytes >= 1e9) return (bytes / 1e9).toFixed(1) + ' GB';
        if (bytes >= 1e6) return (bytes / 1e6).toFixed(0) + ' MB';
        return bytes + ' B';
    }

    async function loadNode() {
        if (!nodeId) return;
        try {
            node = await nodesApi.get(nodeId);
            if (node) {
                if (node.llama_n_ctx) {
                    configForm.n_ctx = node.llama_n_ctx;
                    configForm.n_gpu_layers = node.llama_n_gpu_layers ?? -1;
                }
            }
        } catch (e) {
            // 404 si le node a été supprimé entre deux ticks
            if (e instanceof ApiError && e.status === 404) {
                node = null;
            }
        } finally {
            loading = false;
        }
    }

    async function loadLocalModels() {
        if (!nodeId || !node?.agent_port) return;
        modelsLoading = true;
        try {
            localModels = await nodesApi.localModels(nodeId);
        } catch {
            /* agent pas encore disponible */
        } finally {
            modelsLoading = false;
        }
    }

    async function startPull() {
        if (!nodeId || !pullForm.hf_repo || !pullForm.filename) {
            toast.error('Renseigne le repo HuggingFace et le nom du fichier.');
            return;
        }
        const id = nodeId;
        const filename = pullForm.filename;
        pulling = true;
        try {
            await nodesApi.pullModel(id, pullForm);
            toast.success('Téléchargement démarré…');
            showPullForm = false;
            downloads.track({
                key: `gguf-${id}-${filename}`,
                label: filename,
                sublabel: node?.name ? `GGUF · ${node.name}` : 'GGUF',
                poll: async () => {
                    const st = await nodesApi.pullStatus(id);
                    pullStatus = st;
                    const status =
                        st?.status === 'done' ? 'done' : st?.status === 'error' ? 'error' : 'downloading';
                    if (status === 'done') {
                        await loadLocalModels();
                        pullStatus = null;
                    }
                    if (status === 'error') pullStatus = null;
                    return {
                        status,
                        percent: null,
                        detail: status === 'error' ? String(st?.error ?? 'échec') : undefined
                    };
                }
            });
        } catch (e) {
            toast.error(e instanceof ApiError ? `Erreur ${e.status}` : 'Erreur inconnue');
        } finally {
            pulling = false;
        }
    }

    async function loadModel(filename: string) {
        if (!nodeId) return;
        loadingModel = filename;
        try {
            await nodesApi.loadModel(nodeId, { filename });
            toast.success(`Chargement de ${filename} en cours…`);
            await loadNode();
        } catch (e) {
            toast.error(e instanceof ApiError ? `Erreur ${e.status}` : 'Erreur');
        } finally {
            loadingModel = null;
        }
    }

    async function loadImageStatus() {
        if (!nodeId || !node?.image_enabled) return;
        try {
            imageStatus = await nodesApi.imageStatus(nodeId);
        } catch {
            /* node image pas encore prêt */
        }
        loadImageModels();
    }

    async function loadImageModels() {
        if (!nodeId || !node?.image_enabled) return;
        try {
            imageModelsList = await nodesApi.imageModels(nodeId);
        } catch {
            imageModelsList = [];
        }
    }

    async function activateModel(repo: string) {
        if (!nodeId) return;
        imageLoading = true;
        try {
            await nodesApi.imageLoad(nodeId, { model: repo });
            toast.success(`Activation de ${repo}…`);
            setTimeout(loadImageStatus, 1500);
        } catch (e) {
            toast.error(e instanceof ApiError ? `Erreur ${e.status}` : 'Erreur');
        } finally {
            imageLoading = false;
        }
    }

    async function deleteImageModel(repo: string) {
        if (!nodeId || !confirm(`Supprimer le modèle d'images « ${repo} » du node ?`)) return;
        try {
            await nodesApi.imageDeleteModel(nodeId, repo);
            toast.success('Modèle supprimé.');
            await loadImageModels();
        } catch (e) {
            toast.error(e instanceof ApiError ? `Erreur ${e.status}` : 'Suppression impossible');
        }
    }

    async function startImagePull() {
        const model = imageModelInput.trim();
        if (!nodeId || !model) {
            toast.error('Indique le repo HuggingFace du modèle (ex. stabilityai/sdxl-turbo).');
            return;
        }
        const id = nodeId;
        imagePulling = true;
        try {
            await nodesApi.imagePull(id, { model });
            toast.success('Téléchargement du modèle d’images démarré…');
            downloads.track({
                key: `img-${id}-${model}`,
                label: model,
                sublabel: node?.name ? `Image · ${node.name}` : 'Image',
                poll: async () => {
                    const st = await nodesApi.imagePullStatus(id);
                    imagePullStatus = st;
                    const status =
                        st?.status === 'done' ? 'done' : st?.status === 'error' ? 'error' : 'downloading';
                    if (status === 'done') {
                        await loadImageStatus();
                        imagePullStatus = null;
                    }
                    if (status === 'error') imagePullStatus = null;
                    const dl = typeof st?.downloaded_mb === 'number' ? st.downloaded_mb : null;
                    const tot = typeof st?.total_mb === 'number' ? st.total_mb : null;
                    return {
                        status,
                        percent: typeof st?.percent === 'number' ? st.percent : null,
                        detail:
                            status === 'error'
                                ? String(st?.error ?? 'échec')
                                : dl != null
                                  ? `${dl >= 1000 ? (dl / 1000).toFixed(1) + ' GB' : dl + ' MB'}${tot ? ' / ' + (tot >= 1000 ? (tot / 1000).toFixed(1) + ' GB' : tot + ' MB') : ''}`
                                  : undefined
                    };
                }
            });
        } catch (e) {
            toast.error(e instanceof ApiError ? `Erreur ${e.status}` : 'Erreur inconnue');
        } finally {
            imagePulling = false;
        }
    }

    async function loadImageModel() {
        const model = imageModelInput.trim() || undefined;
        if (!nodeId) return;
        imageLoading = true;
        try {
            await nodesApi.imageLoad(nodeId, { model });
            toast.success('Chargement du modèle d’images en cours…');
            setTimeout(loadImageStatus, 1500);
        } catch (e) {
            toast.error(e instanceof ApiError ? `Erreur ${e.status}` : 'Erreur');
        } finally {
            imageLoading = false;
        }
    }

    async function deleteModel(filename: string) {
        if (!nodeId || !confirm(`Supprimer ${filename} ?`)) return;
        try {
            await nodesApi.deleteLocalModel(nodeId, filename);
            toast.success('Modèle supprimé.');
            await loadLocalModels();
        } catch (e) {
            toast.error(e instanceof ApiError ? `Erreur ${e.status}` : 'Erreur');
        }
    }

    async function saveConfig() {
        if (!nodeId) return;
        configSaving = true;
        try {
            await nodesApi.patchLlamaConfig(nodeId, configForm);
            toast.success('Redémarrage llama-server en cours…');
            showConfig = false;
        } catch (e) {
            toast.error(e instanceof ApiError ? `Erreur ${e.status}` : 'Erreur');
        } finally {
            configSaving = false;
        }
    }

    onMount(() => {
        loadNode().then(() => {
            loadLocalModels();
            loadImageStatus();
        });
        loadHistory('1h');
        // Node (stats instantanées) toutes les 3s ; métriques (graphiques) en
        // direct toutes les 5s, en silencieux pour ne pas faire clignoter l'UI.
        const i = setInterval(() => { loadNode(); }, 3000);
        const h = setInterval(() => { loadHistory(histRange, true); }, 5000);
        return () => {
            clearInterval(i);
            clearInterval(h);
        };
    });
</script>

<header class="flex items-center gap-3 px-6 py-3 sm:px-8">
    <button type="button" onclick={() => goto('/nodes')} class="rounded p-1 hover:bg-neutral-800">
        <ChevronLeft size={18} />
    </button>
    <div class="min-w-0 flex items-center gap-2">
        {#if node}
            <span
                class="h-2 w-2 rounded-full flex-shrink-0"
                class:bg-emerald-400={node.status === 'online'}
                class:bg-neutral-600={node.status !== 'online'}
                title={node.status}
            ></span>
        {/if}
        <h1 class="text-lg font-semibold tracking-tight truncate">
            {node?.name ?? '…'}
        </h1>
        <span class="text-xs text-neutral-500">{node?.host}:{node?.port}</span>
    </div>
    {#if node}
        <div class="ml-auto flex items-center gap-1.5">
            {#if node.agent_port}
                <button
                    type="button"
                    onclick={() => (showConfig = !showConfig)}
                    class="flex items-center gap-1.5 rounded border border-neutral-700 px-2 py-1 text-xs text-neutral-400 hover:bg-neutral-800"
                >
                    <Settings size={12} /> Paramètres
                </button>
            {/if}
            <button
                type="button"
                onclick={copyDiag}
                disabled={copyingDiag}
                class="rounded border border-neutral-700 px-2 py-1 text-xs text-neutral-400 hover:bg-neutral-800 disabled:opacity-50"
                title="Copier un diagnostic complet pour bug report"
            >
                {copyingDiag ? 'Copie…' : 'Diag'}
            </button>
        </div>
    {/if}
</header>

<div class="min-h-0 flex-1 space-y-3 overflow-y-auto px-6 pb-6 sm:px-8">

    <!-- KPI strip : matériel condensé -->
    {#if node}
        <section class="rounded-xl border border-neutral-800 bg-neutral-900/60 px-4 py-2.5">
            <div class="grid grid-cols-2 gap-x-4 gap-y-1 text-xs sm:grid-cols-4">
                <div class="flex items-center gap-2 min-w-0">
                    <Cpu size={13} class="shrink-0 text-neutral-500" />
                    <span class="text-neutral-500">GPU</span>
                    <span class="ml-auto truncate font-mono text-neutral-200" title={node.gpu_model ?? '—'}>{node.gpu_model ?? '—'}</span>
                </div>
                <div class="flex items-center gap-2">
                    <Zap size={13} class="shrink-0 text-neutral-500" />
                    <span class="text-neutral-500">VRAM</span>
                    <span class="ml-auto font-mono tabular-nums text-neutral-200">{node.vram_used_mb ?? '—'} / {node.vram_total_mb ?? '—'} MB</span>
                </div>
                <div class="flex items-center gap-2">
                    <MemoryStick size={13} class="shrink-0 text-neutral-500" />
                    <span class="text-neutral-500">RAM</span>
                    <span class="ml-auto font-mono tabular-nums text-neutral-200">{node.ram_used_mb ?? '—'} / {node.ram_total_mb ?? '—'} MB</span>
                </div>
                <div class="flex items-center gap-2">
                    <HardDrive size={13} class="shrink-0 text-neutral-500" />
                    <span class="text-neutral-500">Disque</span>
                    <span class="ml-auto font-mono tabular-nums text-neutral-200">{node.disk_used_mb ? Math.round(node.disk_used_mb / 1024) : '—'} / {node.disk_total_mb ? Math.round(node.disk_total_mb / 1024) : '—'} GB</span>
                </div>
            </div>
        </section>

        <!-- Capabilities (compute_class, gpu_kind, llama_variant, warnings) -->
        <CapabilitiesCard caps={node.capabilities} agentVersion={node.agent_version} />

        <!-- Métriques : un petit graphique indépendant par élément, rafraîchi en direct -->
        <section class="rounded-xl border border-neutral-800 bg-neutral-900/60 p-4">
            <div class="mb-3 flex items-center justify-between">
                <h2 class="flex items-center gap-2 text-xs font-medium uppercase tracking-wider text-neutral-400">
                    <Activity size={12} />
                    Métriques
                    {#if dataAgeS != null && dataAgeS <= 30}
                        <span class="flex items-center gap-1.5 text-[10px] normal-case text-emerald-400">
                            <span class="h-1.5 w-1.5 rounded-full bg-emerald-400 animate-pulse"></span>
                            live · il y a {dataAgeS}s
                        </span>
                    {:else if dataAgeS != null}
                        <span class="flex items-center gap-1.5 text-[10px] normal-case text-amber-400" title="Le node n'envoie plus de heartbeat — vérifie l'agent (journalctl -u spouet-agent -f)">
                            <span class="h-1.5 w-1.5 rounded-full bg-amber-400"></span>
                            figé · dernière donnée il y a {dataAgeS > 3600 ? Math.round(dataAgeS / 3600) + 'h' : Math.round(dataAgeS / 60) + 'min'}
                        </span>
                    {/if}
                    {#if histData?.source === '1min'}
                        <span class="rounded bg-neutral-800 px-1 py-0.5 font-mono text-[9px] text-neutral-500">1-min</span>
                    {/if}
                </h2>
                <div class="flex gap-1">
                    {#each (['1h','6h','24h','7d'] as MetricsRange[]) as r}
                        <button
                            type="button"
                            onclick={() => loadHistory(r)}
                            class="rounded border px-2 py-0.5 text-xs transition {histRange === r ? 'border-cyan-500 bg-cyan-500/10 text-cyan-300' : 'border-neutral-700 text-neutral-400 hover:bg-neutral-800'}"
                        >{r}</button>
                    {/each}
                </div>
            </div>
            {#if histLoading && !histData}
                <div class="rounded border border-neutral-800 bg-neutral-900/40 px-3 py-8 text-center text-xs text-neutral-500">
                    Chargement…
                </div>
            {:else if metricCharts.length === 0}
                <div class="rounded border border-neutral-800 bg-neutral-900/40 px-3 py-8 text-center text-xs text-neutral-500">
                    Aucune donnée sur cette plage.
                </div>
            {:else}
                <div class="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
                    {#each metricCharts as c (c.label)}
                        <div class="rounded-lg border border-neutral-800 bg-neutral-950/50 p-2.5">
                            <div class="mb-1 flex items-baseline justify-between">
                                <span class="text-[10px] uppercase tracking-wider text-neutral-500">{c.label}</span>
                                <span class="font-mono text-sm tabular-nums text-neutral-200">{lastVal(c)}</span>
                            </div>
                            <TimeSeriesChart
                                series={[c]}
                                height={90}
                                showLegend={false}
                                timeFormat={histRange === '7d' ? 'date' : 'hh:mm'}
                            />
                        </div>
                    {/each}
                </div>
            {/if}
        </section>

        <!-- Stats llama.cpp : bandeau dense -->
        <section class="rounded-xl border border-neutral-800 bg-neutral-900/60 px-4 py-3">
            <div class="mb-2 flex items-center justify-between">
                <h2 class="text-xs font-medium uppercase tracking-wider text-neutral-400">llama.cpp</h2>
                <div class="flex items-center gap-2 text-xs">
                    <span class="h-1.5 w-1.5 rounded-full {node.llama_running ? 'bg-emerald-400' : 'bg-neutral-600'}"></span>
                    <span class="text-neutral-400">{node.llama_running ? 'actif' : 'arrêté'}</span>
                    {#if node.llama_model_loaded}
                        <span class="mx-1 text-neutral-700">·</span>
                        <span class="truncate font-mono text-[11px] text-neutral-300" title={node.llama_model_loaded}>{node.llama_model_loaded}</span>
                    {/if}
                </div>
            </div>

            <div class="grid grid-cols-3 gap-x-4 gap-y-1 text-xs sm:grid-cols-6">
                <div class="flex justify-between gap-2">
                    <span class="text-neutral-500">TPS</span>
                    <span class="font-mono tabular-nums">{node.llama_tps != null ? node.llama_tps.toFixed(1) : '—'}</span>
                </div>
                <div class="flex justify-between gap-2">
                    <span class="text-neutral-500">n_ctx</span>
                    <span class="font-mono tabular-nums">{node.llama_n_ctx ?? '—'}</span>
                </div>
                <div class="flex justify-between gap-2">
                    <span class="text-neutral-500">GPU lyr</span>
                    <span class="font-mono tabular-nums">{node.llama_n_gpu_layers ?? '—'}</span>
                </div>
                <div class="flex justify-between gap-2">
                    <span class="text-neutral-500">Slots</span>
                    <span class="font-mono tabular-nums">{node.llama_slots_active ?? '—'}</span>
                </div>
                <div class="flex justify-between gap-2">
                    <span class="text-neutral-500">Tok gen</span>
                    <span class="font-mono tabular-nums">{node.llama_tokens_generated?.toLocaleString() ?? '—'}</span>
                </div>
                <div class="flex justify-between gap-2">
                    <span class="text-neutral-500">Tok prompt</span>
                    <span class="font-mono tabular-nums">{node.llama_prompt_tokens_processed?.toLocaleString() ?? '—'}</span>
                </div>
            </div>

            {#if !node.llama_running}
                <p class="mt-2 rounded border border-neutral-800 bg-neutral-950/50 px-2.5 py-1.5 text-[11px] text-neutral-500">
                    llama-server n'est pas démarré sur ce node (aucun modèle GGUF chargé) — les
                    statistiques restent vides. Charge un modèle dans « Modèles GGUF locaux » ci-dessous
                    pour le rendre actif.
                </p>
            {/if}

            {#if showConfig}
                <div class="mt-4 border-t border-neutral-800 pt-4">
                    <h3 class="mb-3 text-xs font-medium text-neutral-400">Modifier les paramètres (redémarre llama-server)</h3>
                    <div class="grid grid-cols-2 gap-3 sm:grid-cols-4">
                        <label class="flex flex-col gap-1 text-xs text-neutral-400">
                            Contexte (n_ctx)
                            <input type="number" bind:value={configForm.n_ctx} min="512" step="512"
                                class="rounded border border-neutral-700 bg-neutral-950 px-2 py-1.5 text-sm text-neutral-200 focus:border-cyan-500/50 focus:outline-none" />
                        </label>
                        <label class="flex flex-col gap-1 text-xs text-neutral-400">
                            Couches GPU (n_gpu_layers)
                            <input type="number" bind:value={configForm.n_gpu_layers} min="-1"
                                class="rounded border border-neutral-700 bg-neutral-950 px-2 py-1.5 text-sm text-neutral-200 focus:border-cyan-500/50 focus:outline-none" />
                        </label>
                        <label class="flex flex-col gap-1 text-xs text-neutral-400">
                            Batch size
                            <input type="number" bind:value={configForm.n_batch} min="32" step="32"
                                class="rounded border border-neutral-700 bg-neutral-950 px-2 py-1.5 text-sm text-neutral-200 focus:border-cyan-500/50 focus:outline-none" />
                        </label>
                        <label class="flex flex-col gap-1 text-xs text-neutral-400">
                            Slots parallèles
                            <input type="number" bind:value={configForm.n_parallel} min="1" max="16"
                                class="rounded border border-neutral-700 bg-neutral-950 px-2 py-1.5 text-sm text-neutral-200 focus:border-cyan-500/50 focus:outline-none" />
                        </label>
                    </div>
                    <div class="mt-3 flex gap-2">
                        <button
                            type="button"
                            onclick={saveConfig}
                            disabled={configSaving}
                            class="flex items-center gap-2 rounded-lg bg-cyan-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-cyan-500 disabled:opacity-50"
                        >
                            {#if configSaving}<Loader2 size={14} class="animate-spin" />{/if}
                            Appliquer
                        </button>
                        <button
                            type="button"
                            onclick={() => (showConfig = false)}
                            class="rounded-lg px-3 py-1.5 text-sm text-neutral-400 hover:bg-neutral-800"
                        >
                            Annuler
                        </button>
                    </div>
                    <p class="mt-2 text-xs text-neutral-600">-1 pour n_gpu_layers = tout mettre sur GPU.</p>
                </div>
            {/if}
        </section>
    {/if}

    <!-- Modèles locaux -->
    <section class="rounded-xl border border-neutral-800 bg-neutral-900/60 p-4">
        <div class="flex items-center justify-between mb-3">
            <h2 class="text-xs font-medium uppercase tracking-wider text-neutral-400">
                Modèles GGUF locaux
                {#if modelsLoading}<Loader2 size={12} class="ml-2 animate-spin inline" />{/if}
            </h2>
            {#if node?.agent_port}
                <button
                    type="button"
                    onclick={() => (showPullForm = !showPullForm)}
                    class="flex items-center gap-1.5 rounded-lg bg-cyan-600 px-2.5 py-1 text-xs font-medium text-white hover:bg-cyan-500"
                >
                    <Download size={12} /> Installer un modèle
                </button>
            {:else}
                <p class="text-xs text-neutral-600">Agent v0.2+ requis pour gérer les modèles</p>
            {/if}
        </div>

        {#if showPullForm}
            <div class="mb-4 rounded-lg border border-neutral-700 bg-neutral-950 p-3">
                <p class="mb-2 text-xs text-neutral-400">
                    Télécharge un fichier GGUF depuis <a href="https://huggingface.co" target="_blank" class="underline">Hugging Face</a>.
                </p>
                <div class="grid gap-2 sm:grid-cols-2">
                    <label class="flex flex-col gap-1 text-xs text-neutral-500">
                        Repo HuggingFace
                        <input
                            type="text"
                            bind:value={pullForm.hf_repo}
                            placeholder="bartowski/Meta-Llama-3.1-8B-Instruct-GGUF"
                            class="rounded border border-neutral-700 bg-neutral-900 px-2 py-1.5 text-xs text-neutral-200 focus:border-cyan-500/50 focus:outline-none"
                        />
                    </label>
                    <label class="flex flex-col gap-1 text-xs text-neutral-500">
                        Nom du fichier GGUF
                        <input
                            type="text"
                            bind:value={pullForm.filename}
                            placeholder="Meta-Llama-3.1-8B-Instruct-Q4_K_M.gguf"
                            class="rounded border border-neutral-700 bg-neutral-900 px-2 py-1.5 text-xs text-neutral-200 focus:border-cyan-500/50 focus:outline-none"
                        />
                    </label>
                </div>
                <div class="mt-2 flex gap-2">
                    <button
                        type="button"
                        onclick={startPull}
                        disabled={pulling}
                        class="flex items-center gap-1.5 rounded bg-cyan-600 px-2.5 py-1 text-xs font-medium text-white hover:bg-cyan-500 disabled:opacity-50"
                    >
                        {#if pulling}<Loader2 size={12} class="animate-spin" />{/if}
                        Télécharger
                    </button>
                    <button
                        type="button"
                        onclick={() => (showPullForm = false)}
                        class="rounded px-2.5 py-1 text-xs text-neutral-400 hover:bg-neutral-800"
                    >
                        Annuler
                    </button>
                </div>
            </div>
        {/if}

        {#if pullStatus}
            <div class="mb-3 rounded border border-cyan-900/40 bg-cyan-950/20 px-3 py-2 text-xs text-cyan-300">
                Téléchargement en cours : {pullStatus.filename as string}…
            </div>
        {/if}

        {#if localModels.length > 0}
            <ul class="space-y-2">
                {#each localModels as m}
                    <li class="flex items-center justify-between rounded-lg border border-neutral-800 bg-neutral-950 px-3 py-2">
                        <div class="min-w-0">
                            <p class="truncate font-mono text-xs">{m.name}</p>
                            <p class="text-xs text-neutral-500">
                                {fmtSize(m.size_bytes)}
                                {#if m.quant}<span class="ml-2 text-neutral-600">{m.quant}</span>{/if}
                                {#if m.parameter_size}<span class="ml-2 text-neutral-600">{m.parameter_size}</span>{/if}
                                {#if m.supports_tools}
                                    <span class="ml-2 rounded bg-cyan-900/40 px-1 py-0.5 text-[10px] text-cyan-300">tools</span>
                                {/if}
                                {#if node?.llama_model_loaded === m.name}
                                    <span class="ml-2 rounded bg-emerald-900/40 px-1 py-0.5 text-[10px] text-emerald-300">chargé</span>
                                {/if}
                            </p>
                        </div>
                        <div class="flex items-center gap-1.5 ml-3">
                            {#if node?.llama_model_loaded !== m.name}
                                <button
                                    type="button"
                                    onclick={() => loadModel(m.name)}
                                    disabled={loadingModel === m.name}
                                    class="flex items-center gap-1 rounded border border-neutral-700 px-2 py-1 text-xs hover:bg-neutral-800 disabled:opacity-50"
                                    title="Charger ce modèle"
                                >
                                    {#if loadingModel === m.name}
                                        <Loader2 size={11} class="animate-spin" />
                                    {:else}
                                        <Play size={11} />
                                    {/if}
                                </button>
                            {/if}
                            <button
                                type="button"
                                onclick={() => deleteModel(m.name)}
                                class="rounded border border-neutral-800 p-1 text-neutral-500 hover:bg-red-950 hover:text-red-300"
                                title="Supprimer"
                            >
                                <Trash2 size={11} />
                            </button>
                        </div>
                    </li>
                {/each}
            </ul>
        {:else if !modelsLoading}
            <p class="text-xs text-neutral-600">
                {node?.agent_port ? 'Aucun modèle GGUF installé.' : 'Installe spouet-agent ≥ 0.2.0 sur ce node pour gérer les modèles depuis l\'interface.'}
            </p>
        {/if}
    </section>

    <!-- Génération d'images (sur le node) -->
    <section class="rounded-xl border border-neutral-800 bg-neutral-900/60 p-4">
        <h2 class="mb-3 text-xs font-medium uppercase tracking-wider text-neutral-400">
            Génération d'images
        </h2>
        {#if node?.image_enabled}
            <div class="mb-3 flex flex-wrap items-center gap-2 text-xs">
                <span class="rounded bg-emerald-900/40 px-2 py-0.5 text-[10px] text-emerald-300">
                    activée
                </span>
                {#if imageStatus}
                    <span class="text-neutral-500">device : {imageStatus.device as string}</span>
                    {#if imageStatus.model}
                        <span class="text-neutral-400">modèle actif : <span class="font-mono">{imageStatus.model as string}</span></span>
                    {/if}
                    {#if imageStatus.ready}
                        <span class="rounded bg-emerald-900/40 px-1 py-0.5 text-[10px] text-emerald-300">prêt</span>
                    {/if}
                {:else if node.image_model}
                    <span class="text-neutral-400">modèle : <span class="font-mono">{node.image_model}</span></span>
                {/if}
            </div>

            <div class="rounded-lg border border-neutral-700 bg-neutral-950 p-3">
                <p class="mb-2 text-xs text-neutral-400">
                    Télécharge / active un modèle de diffusion depuis
                    <a href="https://huggingface.co" target="_blank" class="underline">Hugging Face</a>
                    (ex. <span class="font-mono">stabilityai/sdxl-turbo</span>,
                    <span class="font-mono">stabilityai/sd-turbo</span>). Vide = modèle par défaut du node.
                </p>
                <div class="flex flex-wrap gap-2">
                    <input
                        type="text"
                        bind:value={imageModelInput}
                        placeholder="stabilityai/sdxl-turbo"
                        class="min-w-0 flex-1 rounded border border-neutral-700 bg-neutral-900 px-2 py-1.5 text-xs text-neutral-200 focus:border-cyan-500/50 focus:outline-none"
                    />
                    <button
                        type="button"
                        onclick={startImagePull}
                        disabled={imagePulling}
                        class="flex items-center gap-1.5 rounded bg-cyan-600 px-2.5 py-1 text-xs font-medium text-white hover:bg-cyan-500 disabled:opacity-50"
                    >
                        {#if imagePulling}<Loader2 size={12} class="animate-spin" />{:else}<Download size={12} />{/if}
                        Télécharger
                    </button>
                    <button
                        type="button"
                        onclick={loadImageModel}
                        disabled={imageLoading}
                        class="flex items-center gap-1.5 rounded border border-neutral-700 px-2.5 py-1 text-xs hover:bg-neutral-800 disabled:opacity-50"
                        title="Mettre ce modèle en mémoire (le rendre actif)"
                    >
                        {#if imageLoading}<Loader2 size={12} class="animate-spin" />{:else}<Play size={12} />{/if}
                        Activer
                    </button>
                </div>
                {#if imagePullStatus}
                    {@const pct = typeof imagePullStatus.percent === 'number' ? imagePullStatus.percent : null}
                    {@const dl = typeof imagePullStatus.downloaded_mb === 'number' ? imagePullStatus.downloaded_mb : null}
                    {@const tot = typeof imagePullStatus.total_mb === 'number' ? imagePullStatus.total_mb : null}
                    <div class="mt-3">
                        <div class="mb-1 flex items-center justify-between text-xs text-cyan-300">
                            <span class="flex items-center gap-1.5">
                                <Loader2 size={11} class="animate-spin" />
                                Téléchargement : <span class="font-mono">{imagePullStatus.model as string}</span>
                            </span>
                            <span class="font-mono tabular-nums text-neutral-400">
                                {#if dl != null}{dl >= 1000 ? (dl / 1000).toFixed(1) + ' GB' : dl + ' MB'}{#if tot}&nbsp;/&nbsp;{tot >= 1000 ? (tot / 1000).toFixed(1) + ' GB' : tot + ' MB'}{/if}{/if}
                                {#if pct != null}&nbsp;· {pct.toFixed(0)} %{/if}
                            </span>
                        </div>
                        <div class="h-1.5 w-full overflow-hidden rounded-full bg-neutral-800">
                            {#if pct != null}
                                <div class="h-full rounded-full bg-cyan-500 transition-all duration-300" style:width={`${Math.max(2, Math.min(100, pct))}%`}></div>
                            {:else}
                                <div class="dl-bar h-full w-1/3 rounded-full bg-cyan-500"></div>
                            {/if}
                        </div>
                    </div>
                {/if}
            </div>

            <!-- Modèles d'images téléchargés sur le node -->
            <div class="mt-3">
                <p class="mb-1.5 text-[10px] uppercase tracking-wider text-neutral-500">
                    Modèles téléchargés ({imageModelsList.length})
                </p>
                {#if imageModelsList.length === 0}
                    <p class="text-xs text-neutral-600">Aucun modèle d'images en cache sur ce node.</p>
                {:else}
                    <ul class="space-y-1.5">
                        {#each imageModelsList as m (m.repo)}
                            <li class="flex items-center justify-between gap-2 rounded-lg border border-neutral-800 bg-neutral-950 px-3 py-2">
                                <div class="min-w-0">
                                    <p class="truncate font-mono text-xs">{m.repo}</p>
                                    <p class="text-[11px] text-neutral-500">
                                        {fmtSize(m.size_bytes)}
                                        {#if m.active}
                                            <span class="ml-2 rounded bg-emerald-900/40 px-1 py-0.5 text-[10px] text-emerald-300">actif</span>
                                        {/if}
                                    </p>
                                </div>
                                <div class="ml-2 flex items-center gap-1.5">
                                    {#if !m.active}
                                        <button
                                            type="button"
                                            onclick={() => activateModel(m.repo)}
                                            disabled={imageLoading}
                                            class="flex items-center gap-1 rounded border border-neutral-700 px-2 py-1 text-xs hover:bg-neutral-800 disabled:opacity-50"
                                            title="Activer ce modèle"
                                        >
                                            <Play size={11} />
                                        </button>
                                    {/if}
                                    <button
                                        type="button"
                                        onclick={() => deleteImageModel(m.repo)}
                                        class="rounded border border-neutral-800 p-1 text-neutral-500 hover:bg-red-950 hover:text-red-300"
                                        title="Supprimer du node (libère l'espace)"
                                    >
                                        <Trash2 size={11} />
                                    </button>
                                </div>
                            </li>
                        {/each}
                    </ul>
                {/if}
            </div>
        {:else}
            <p class="text-xs text-neutral-600">
                Ce node n'expose pas la génération d'images. Mets à jour le node-agent
                (<span class="font-mono">bash install.sh</span>) — la génération d'images
                est incluse par défaut. Pour la désactiver :
                <span class="font-mono">--no-images</span>.
            </p>
        {/if}
    </section>

    <!-- Modèles Ollama/llama.cpp déclarés (depuis heartbeat) -->
    {#if node?.models && node.models.length > 0}
        <section class="rounded-xl border border-neutral-800 bg-neutral-900/60 p-4">
            <h2 class="mb-3 text-xs font-medium uppercase tracking-wider text-neutral-400">Modèles déclarés (heartbeat)</h2>
            <ul class="space-y-1">
                {#each node.models as m}
                    <li class="flex items-center justify-between text-xs">
                        <span class="font-mono">{m.name}</span>
                        {#if m.supports_tools}
                            <span class="rounded bg-cyan-900/40 px-1.5 py-0.5 text-[10px] text-cyan-300">tools</span>
                        {/if}
                    </li>
                {/each}
            </ul>
        </section>
    {/if}
</div>

<style>
    /* Barre de progression indéterminée (téléchargement sans % connu). */
    .dl-bar {
        animation: dl-slide 1.3s ease-in-out infinite;
    }
    @keyframes dl-slide {
        0% { margin-left: 0; }
        50% { margin-left: 66%; }
        100% { margin-left: 0; }
    }
</style>
