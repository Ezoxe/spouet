<script lang="ts">
    import { onMount } from 'svelte';
    import { Trash2, RefreshCw, Plus, Check, X, Loader2, Copy, ExternalLink } from 'lucide-svelte';
    import { nodes as nodesApi, ApiError, type NodeOut, type NodeProbeOut } from '$lib/api';
    import { toast } from '$lib/toast.svelte';
    import HelpPanel from '$lib/components/HelpPanel.svelte';

    function copy(text: string) {
        if (typeof navigator !== 'undefined' && navigator.clipboard) {
            navigator.clipboard.writeText(text).then(() => toast.info('Copié.'));
        }
    }

    const linuxSetup = `# 1. Exposer Ollama sur le réseau local
sudo systemctl edit ollama
# Coller dans l'éditeur :
#   [Service]
#   Environment="OLLAMA_HOST=0.0.0.0:11434"
sudo systemctl restart ollama

# 2. Ouvrir le port 11434 (selon ton firewall)
sudo ufw allow from <ip-serveur-spouet> to any port 11434 proto tcp`;

    const agentLinuxSetup = `# Sur la machine Ollama (Debian/Ubuntu)
sudo useradd -r -s /usr/sbin/nologin spouet || true
sudo mkdir -p /opt/spouet && sudo chown spouet:spouet /opt/spouet
sudo -u spouet git clone https://github.com/<ton-fork>/spouet.git /opt/spouet/repo
cd /opt/spouet/repo/node-agent
sudo -u spouet uv sync
sudo install -m 755 .venv/bin/spouet-agent /usr/local/bin/

# Config : /etc/spouet/agent.env
sudo mkdir -p /etc/spouet
sudo tee /etc/spouet/agent.env > /dev/null <<'EOF'
SPOUET_BACKEND=https://spouet.tonserveur.local
SPOUET_AGENT_TOKEN=<ton-token-spouet>
OLLAMA_URL=http://localhost:11434
HEARTBEAT_INTERVAL=10
EOF
sudo chmod 600 /etc/spouet/agent.env

sudo cp /opt/spouet/repo/node-agent/systemd/spouet-agent.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now spouet-agent
sudo journalctl -u spouet-agent -f   # pour vérifier`;

    const agentWindowsSetup = `# Sur la machine Ollama (Windows, en PowerShell admin)
choco install nssm uv -y    # ou installer manuellement depuis nssm.cc et astral.sh/uv
git clone https://github.com/<ton-fork>/spouet.git C:\\spouet
cd C:\\spouet\\node-agent\\nssm
.\\install.ps1 -Backend "https://spouet.tonserveur.local" -Token "<ton-token-spouet>"
# Le service "SpouetAgent" est démarré et configuré pour redémarrage auto.
# Logs : C:\\spouet\\node-agent\\agent.log`;

    let list: NodeOut[] = $state([]);
    let loading = $state(false);

    // Formulaire d'ajout
    let showForm = $state(false);
    let form = $state({ name: '', host: '', port: 11434, tags: '' });
    let probeState: { kind: 'idle' } | { kind: 'loading' } | { kind: 'done'; result: NodeProbeOut } =
        $state({ kind: 'idle' });
    let creating = $state(false);

    async function refresh() {
        loading = true;
        try {
            list = await nodesApi.list();
        } finally {
            loading = false;
        }
    }
    async function del(id: string, name: string) {
        if (!confirm(`Supprimer le node « ${name} » ?`)) return;
        await nodesApi.delete(id);
        await refresh();
    }

    function resetForm() {
        form = { name: '', host: '', port: 11434, tags: '' };
        probeState = { kind: 'idle' };
    }

    async function probe() {
        if (!form.host) {
            toast.error('Renseigne au moins l’adresse de la machine.');
            return;
        }
        probeState = { kind: 'loading' };
        try {
            const result = await nodesApi.probe({
                name: form.name || 'probe',
                host: form.host,
                port: form.port
            });
            probeState = { kind: 'done', result };
        } catch (e) {
            probeState = {
                kind: 'done',
                result: {
                    reachable: false,
                    error: e instanceof ApiError ? `HTTP ${e.status}` : 'erreur réseau',
                    models: []
                }
            };
        }
    }

    async function create() {
        if (!form.name || !form.host) {
            toast.error('Le nom et l’adresse sont obligatoires.');
            return;
        }
        creating = true;
        try {
            await nodesApi.create({
                name: form.name,
                host: form.host,
                port: form.port,
                tags: form.tags
                    .split(',')
                    .map((t) => t.trim())
                    .filter(Boolean)
            });
            toast.success(`Node « ${form.name} » ajouté.`);
            showForm = false;
            resetForm();
            await refresh();
        } catch (e) {
            const msg =
                e instanceof ApiError
                    ? typeof e.body === 'object' && e.body && 'detail' in e.body
                        ? String((e.body as { detail: unknown }).detail)
                        : `HTTP ${e.status}`
                    : 'Erreur inconnue';
            toast.error(`Échec : ${msg}`);
        } finally {
            creating = false;
        }
    }

    onMount(() => {
        refresh();
        const i = setInterval(refresh, 5000);
        return () => clearInterval(i);
    });
</script>

<header class="flex items-center justify-between px-6 py-5 sm:px-8">
    <div>
        <h1 class="text-2xl font-semibold tracking-tight">Nodes Ollama</h1>
        <p class="mt-1 text-xs text-neutral-500">
            Machines exécutant Ollama, sur lesquelles Spouet route les prompts.
        </p>
    </div>
    <div class="flex items-center gap-2">
        <button
            type="button"
            onclick={refresh}
            class="flex items-center gap-2 rounded-lg border border-neutral-700 px-3 py-1.5 text-sm
                   hover:bg-neutral-800"
        >
            <RefreshCw size={14} class={loading ? 'animate-spin' : ''} /> Rafraîchir
        </button>
        <button
            type="button"
            onclick={() => {
                showForm = !showForm;
                if (!showForm) resetForm();
            }}
            class="flex items-center gap-2 rounded-lg bg-cyan-600 px-3 py-1.5 text-sm font-medium
                   text-white hover:bg-cyan-500"
        >
            <Plus size={14} /> Ajouter un node
        </button>
    </div>
</header>

<div class="px-6 pb-6 sm:px-8">
    <HelpPanel title="À quoi sert cette page et comment configurer Ollama" storageKey="nodes">
        <p class="mb-2">
            Un <strong>node</strong> = une machine où tourne <code
                class="rounded bg-neutral-800 px-1 py-0.5 text-xs">ollama serve</code
            >. Spouet sélectionne automatiquement le node ayant le modèle demandé et la VRAM la
            plus libre. Tu peux ajouter autant de nodes que tu veux.
        </p>
        <p class="mb-3">Deux façons de raccrocher une machine :</p>

        <ol class="ml-4 list-decimal space-y-3 text-neutral-300">
            <li>
                <strong class="text-neutral-100">Mode direct (recommandé pour démarrer)</strong> —
                clique sur « Ajouter un node ». Le backend Spouet pingera <code
                    class="rounded bg-neutral-800 px-1 py-0.5 text-xs">/api/tags</code
                > toutes les 15 s pour suivre les modèles disponibles.
                <ul class="mt-1 ml-4 list-disc space-y-1 text-xs text-neutral-400">
                    <li>
                        Côté machine Ollama : exposer le service sur l’interface réseau, pas
                        seulement <code>localhost</code>. Sous Linux/macOS&nbsp;:
                        <code class="rounded bg-neutral-800 px-1 py-0.5"
                            >OLLAMA_HOST=0.0.0.0:11434 ollama serve</code
                        >. En service systemd&nbsp;:
                        <code class="rounded bg-neutral-800 px-1 py-0.5"
                            >sudo systemctl edit ollama</code
                        > puis ajouter <code class="rounded bg-neutral-800 px-1 py-0.5"
                            >Environment="OLLAMA_HOST=0.0.0.0:11434"</code
                        > sous <code>[Service]</code>.
                    </li>
                    <li>
                        Sous Windows : variable d’environnement
                        <code class="rounded bg-neutral-800 px-1 py-0.5">OLLAMA_HOST=0.0.0.0</code>
                        puis relancer Ollama.
                    </li>
                    <li>
                        Pare-feu : ouvrir le port <strong>11434</strong> en TCP entre le serveur
                        Spouet et la machine Ollama.
                    </li>
                    <li>
                        Test rapide depuis le serveur Spouet&nbsp;:
                        <code class="rounded bg-neutral-800 px-1 py-0.5"
                            >curl http://&lt;ip&gt;:11434/api/tags</code
                        > doit renvoyer du JSON.
                    </li>
                    <li>
                        Pas besoin que Ollama soit installé sur la même machine que le Docker
                        Spouet — c’est juste un appel HTTP.
                    </li>
                </ul>
            </li>
            <li>
                <strong class="text-neutral-100">Mode agent</strong> — installer le paquet
                <code class="rounded bg-neutral-800 px-1 py-0.5 text-xs">spouet-agent</code> sur la
                machine Ollama. Le node se déclare alors lui-même via heartbeats et remonte la VRAM
                temps réel (utile si le GPU est partagé avec d’autres apps).
            </li>
        </ol>
        <p class="mt-3 text-xs text-neutral-400">
            Statut : un node passe <span class="text-neutral-500">offline</span> si aucun signe de
            vie depuis 30 s. La suppression coupe le routing mais n’arrête pas Ollama côté
            machine cible.
        </p>
    </HelpPanel>

    <HelpPanel
        title="Configurer Ollama (mode direct, copier-coller)"
        storageKey="nodes-ollama-setup"
        defaultOpen={false}
    >
        <p class="mb-2">
            Sur la machine où tourne Ollama (Linux/Debian) — adapte selon ton firewall :
        </p>
        <div class="relative">
            <button
                type="button"
                onclick={() => copy(linuxSetup)}
                class="absolute right-2 top-2 flex items-center gap-1 rounded
                       border border-neutral-700 bg-neutral-900 px-2 py-1 text-[10px]
                       text-neutral-400 hover:text-neutral-200"
            >
                <Copy size={10} /> Copier
            </button>
            <pre
                class="overflow-x-auto rounded-md border border-neutral-800 bg-neutral-950 p-3
                       font-mono text-[11px] leading-relaxed text-neutral-300"><code
                    >{linuxSetup}</code
                ></pre>
        </div>
        <p class="mt-3 text-xs text-neutral-400">
            Sous <strong>Windows</strong> : ouvre les Variables d’environnement système, ajoute
            <code class="rounded bg-neutral-800 px-1">OLLAMA_HOST</code> = <code
                class="rounded bg-neutral-800 px-1">0.0.0.0</code
            >, redémarre Ollama. <strong>macOS</strong> :
            <code class="rounded bg-neutral-800 px-1"
                >launchctl setenv OLLAMA_HOST 0.0.0.0:11434</code
            > puis redémarrer le service.
        </p>
    </HelpPanel>

    <HelpPanel
        title="Déployer le node-agent (mode agent — VRAM temps réel)"
        storageKey="nodes-agent-setup"
        defaultOpen={false}
    >
        <p class="mb-3">
            L’agent envoie un heartbeat toutes les 10 s avec la VRAM utilisée en direct (utile si
            d’autres apps partagent le GPU). Sans agent, le mode direct fonctionne très bien : on
            connaît juste les modèles, pas la VRAM. Choisis selon ton besoin.
        </p>
        <p class="mb-1 text-xs uppercase tracking-wider text-neutral-400">
            1. Récupère un token API
        </p>
        <p class="mb-3 text-xs">
            Dans <a class="underline hover:text-white" href="/settings">Paramètres → Token API</a>,
            clique sur « Régénérer ». Note-le : il va servir à authentifier l’agent. Tu peux aussi
            créer un token dédié&nbsp;:
            <code class="rounded bg-neutral-800 px-1">
                spouet-admin create-token --email agent@local
            </code>.
        </p>

        <p class="mb-1 text-xs uppercase tracking-wider text-neutral-400">
            2a. Installation Linux (systemd)
        </p>
        <div class="relative mb-3">
            <button
                type="button"
                onclick={() => copy(agentLinuxSetup)}
                class="absolute right-2 top-2 flex items-center gap-1 rounded
                       border border-neutral-700 bg-neutral-900 px-2 py-1 text-[10px]
                       text-neutral-400 hover:text-neutral-200"
            >
                <Copy size={10} /> Copier
            </button>
            <pre
                class="overflow-x-auto rounded-md border border-neutral-800 bg-neutral-950 p-3
                       font-mono text-[11px] leading-relaxed text-neutral-300"><code
                    >{agentLinuxSetup}</code
                ></pre>
        </div>

        <p class="mb-1 text-xs uppercase tracking-wider text-neutral-400">
            2b. Installation Windows (NSSM)
        </p>
        <div class="relative mb-3">
            <button
                type="button"
                onclick={() => copy(agentWindowsSetup)}
                class="absolute right-2 top-2 flex items-center gap-1 rounded
                       border border-neutral-700 bg-neutral-900 px-2 py-1 text-[10px]
                       text-neutral-400 hover:text-neutral-200"
            >
                <Copy size={10} /> Copier
            </button>
            <pre
                class="overflow-x-auto rounded-md border border-neutral-800 bg-neutral-950 p-3
                       font-mono text-[11px] leading-relaxed text-neutral-300"><code
                    >{agentWindowsSetup}</code
                ></pre>
        </div>

        <p class="mb-1 text-xs uppercase tracking-wider text-neutral-400">3. Lancer en manuel</p>
        <p class="text-xs">
            Pour tester sans installer un service :
            <code class="rounded bg-neutral-800 px-1"
                >uv run spouet-agent run --backend &lt;url&gt; --token &lt;token&gt;</code
            >. Le node apparaîtra dans la liste après le premier heartbeat (≈ 10 s).
        </p>

        <p class="mt-3 text-xs uppercase tracking-wider text-neutral-400">Diagnostic rapide</p>
        <ul class="ml-4 list-disc space-y-1 text-xs">
            <li>
                <code class="rounded bg-neutral-800 px-1">[heartbeat] 401</code> → le token est
                mauvais ou révoqué. Régénère-le et relance le service.
            </li>
            <li>
                Le node reste <span class="text-neutral-500">offline</span> alors que l’agent dit «
                ok » → le <strong>--ollama-host</strong> envoyé n’est pas joignable depuis le
                backend. Forcer
                <code class="rounded bg-neutral-800 px-1">--ollama-host &lt;ip-routable&gt;</code>.
            </li>
            <li>
                <code class="rounded bg-neutral-800 px-1"
                    >[heartbeat] error: Cannot connect to host localhost:11434</code
                > → Ollama n’est pas lancé localement, ou écoute sur une autre interface.
            </li>
            <li>
                Les modèles n’apparaissent pas → vérifie
                <code class="rounded bg-neutral-800 px-1">curl localhost:11434/api/tags</code> sur
                la machine Ollama.
            </li>
        </ul>
    </HelpPanel>

    {#if showForm}
        <section
            class="mb-4 rounded-xl border border-neutral-800 bg-neutral-900/60 p-4"
        >
            <h2 class="mb-3 text-sm font-medium">Nouveau node (mode direct)</h2>
            <div class="grid gap-3 sm:grid-cols-4">
                <label class="flex flex-col gap-1 text-xs text-neutral-400">
                    Nom
                    <input
                        type="text"
                        bind:value={form.name}
                        placeholder="rtx-4090"
                        class="rounded-md border border-[var(--color-border)] bg-[var(--color-bg-1)]
                               px-2 py-1.5 text-sm text-neutral-200
                               focus:border-cyan-500/50 focus:outline-none"
                    />
                </label>
                <label class="flex flex-col gap-1 text-xs text-neutral-400 sm:col-span-2">
                    Adresse (IP ou hostname)
                    <input
                        type="text"
                        bind:value={form.host}
                        placeholder="192.168.1.42"
                        class="rounded-md border border-[var(--color-border)] bg-[var(--color-bg-1)]
                               px-2 py-1.5 text-sm text-neutral-200
                               focus:border-cyan-500/50 focus:outline-none"
                    />
                </label>
                <label class="flex flex-col gap-1 text-xs text-neutral-400">
                    Port
                    <input
                        type="number"
                        bind:value={form.port}
                        min="1"
                        max="65535"
                        class="rounded-md border border-[var(--color-border)] bg-[var(--color-bg-1)]
                               px-2 py-1.5 text-sm text-neutral-200
                               focus:border-cyan-500/50 focus:outline-none"
                    />
                </label>
                <label class="flex flex-col gap-1 text-xs text-neutral-400 sm:col-span-4">
                    Tags (séparés par des virgules, optionnel)
                    <input
                        type="text"
                        bind:value={form.tags}
                        placeholder="prod, fast, vision"
                        class="rounded-md border border-[var(--color-border)] bg-[var(--color-bg-1)]
                               px-2 py-1.5 text-sm text-neutral-200
                               focus:border-cyan-500/50 focus:outline-none"
                    />
                </label>
            </div>

            <div class="mt-3 flex flex-wrap items-center gap-2">
                <button
                    type="button"
                    onclick={probe}
                    disabled={probeState.kind === 'loading' || !form.host}
                    class="flex items-center gap-2 rounded-lg border border-neutral-700 px-3 py-1.5
                           text-sm hover:bg-neutral-800 disabled:opacity-50"
                >
                    {#if probeState.kind === 'loading'}
                        <Loader2 size={14} class="animate-spin" />
                    {/if}
                    Tester la connexion
                </button>
                <button
                    type="button"
                    onclick={create}
                    disabled={creating || !form.name || !form.host}
                    class="flex items-center gap-2 rounded-lg bg-cyan-600 px-3 py-1.5 text-sm
                           font-medium text-white hover:bg-cyan-500 disabled:opacity-50"
                >
                    {#if creating}
                        <Loader2 size={14} class="animate-spin" />
                    {/if}
                    Enregistrer
                </button>
                <button
                    type="button"
                    onclick={() => {
                        showForm = false;
                        resetForm();
                    }}
                    class="rounded-lg px-3 py-1.5 text-sm text-neutral-400 hover:bg-neutral-800"
                >
                    Annuler
                </button>
            </div>

            {#if probeState.kind === 'done'}
                <div
                    class="mt-3 rounded-lg border p-3 text-xs
                           {probeState.result.reachable
                        ? 'border-emerald-900/50 bg-emerald-950/30 text-emerald-200'
                        : 'border-red-900/50 bg-red-950/30 text-red-200'}"
                >
                    {#if probeState.result.reachable}
                        <p class="flex items-center gap-2">
                            <Check size={14} />
                            Connecté. {probeState.result.models.length} modèle(s) détecté(s){probeState
                                .result.models.length
                                ? ' :'
                                : '.'}
                        </p>
                        {#if probeState.result.models.length}
                            <p class="mt-1 font-mono">
                                {probeState.result.models.slice(0, 8).join(', ')}{probeState.result
                                    .models.length > 8
                                    ? '…'
                                    : ''}
                            </p>
                        {/if}
                    {:else}
                        <p class="flex items-center gap-2">
                            <X size={14} /> Injoignable : {probeState.result.error ?? 'inconnue'}
                        </p>
                        <p class="mt-1 text-neutral-400">
                            Vérifie que <code class="rounded bg-neutral-800 px-1">OLLAMA_HOST</code
                            >
                            est à <code class="rounded bg-neutral-800 px-1">0.0.0.0</code> côté
                            machine cible et que le pare-feu laisse passer le port.
                        </p>
                    {/if}
                </div>
            {/if}
        </section>
    {/if}

    <div class="space-y-3">
        {#each list as n (n.id)}
            <article class="rounded-xl border border-neutral-800 bg-neutral-900/60 p-4">
                <div class="mb-3 flex items-center justify-between">
                    <div class="flex items-center gap-3">
                        <span
                            class="h-2 w-2 rounded-full"
                            class:bg-emerald-400={n.status === 'online'}
                            class:bg-neutral-600={n.status !== 'online'}
                        ></span>
                        <a href="/nodes/{n.id}" class="font-medium hover:text-cyan-300 flex items-center gap-1">
                            {n.name} <ExternalLink size={11} class="text-neutral-600" />
                        </a>
                        <span class="text-xs text-neutral-500">{n.host}:{n.port}</span>
                        {#if n.agent_version === 'direct'}
                            <span
                                class="rounded bg-neutral-800 px-1.5 py-0.5 text-[10px] text-neutral-400"
                                title="Sans agent : Spouet ping directement Ollama"
                            >
                                direct
                            </span>
                        {:else if n.agent_version}
                            <span
                                class="rounded bg-cyan-900/40 px-1.5 py-0.5 text-[10px] text-cyan-300"
                                title="Le node-agent envoie des heartbeats"
                            >
                                agent {n.agent_version}
                            </span>
                        {/if}
                    </div>
                    <button
                        type="button"
                        onclick={() => del(n.id, n.name)}
                        class="rounded p-1.5 text-neutral-500 hover:bg-red-950 hover:text-red-300"
                        title="Supprimer ce node"
                        aria-label="Supprimer ce node"
                    >
                        <Trash2 size={14} />
                    </button>
                </div>
                <div class="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3 text-sm">
                    <div>
                        <dt class="text-xs text-neutral-500">GPU</dt>
                        <dd class="truncate max-w-[12ch]" title={n.gpu_model ?? '—'}>{n.gpu_model ?? '—'}</dd>
                    </div>
                    <div>
                        <dt class="text-xs text-neutral-500">VRAM</dt>
                        <dd>{n.vram_used_mb ?? '—'} / {n.vram_total_mb ?? '—'} MB</dd>
                    </div>
                    <div>
                        <dt class="text-xs text-neutral-500">RAM</dt>
                        <dd>{n.ram_used_mb ?? '—'} / {n.ram_total_mb ?? '—'} MB</dd>
                    </div>
                    <div>
                        <dt class="text-xs text-neutral-500">llama.cpp</dt>
                        <dd class="flex items-center gap-1.5">
                            <span class="h-1.5 w-1.5 rounded-full {n.llama_running ? 'bg-emerald-400' : 'bg-neutral-600'}"></span>
                            {#if n.llama_running && n.llama_tps != null}
                                {n.llama_tps.toFixed(1)} t/s
                            {:else}
                                {n.llama_running ? 'actif' : 'arrêté'}
                            {/if}
                        </dd>
                    </div>
                    <div>
                        <dt class="text-xs text-neutral-500">Modèle chargé</dt>
                        <dd class="truncate max-w-[14ch] text-xs" title={n.llama_model_loaded ?? '—'}>
                            {n.llama_model_loaded ?? '—'}
                        </dd>
                    </div>
                    <div>
                        <dt class="text-xs text-neutral-500">Modèles</dt>
                        <dd>{n.models.length}</dd>
                    </div>
                </div>
                {#if n.models.length}
                    <details class="mt-3">
                        <summary
                            class="cursor-pointer text-xs text-neutral-500 hover:text-neutral-300"
                        >
                            {n.models.length} modèles
                        </summary>
                        <ul class="mt-2 space-y-1 text-xs text-neutral-400">
                            {#each n.models as m}
                                <li class="flex items-center justify-between">
                                    <span class="font-mono">{m.name}</span>
                                    {#if m.supports_tools}
                                        <span
                                            class="rounded bg-cyan-900/40 px-1.5 py-0.5 text-[10px] text-cyan-300"
                                            >tools</span
                                        >
                                    {/if}
                                </li>
                            {/each}
                        </ul>
                    </details>
                {/if}
            </article>
        {:else}
            <p class="text-sm text-neutral-500">
                Aucun node enregistré. Clique sur « Ajouter un node » pour brancher ton premier
                serveur Ollama.
            </p>
        {/each}
    </div>
</div>
