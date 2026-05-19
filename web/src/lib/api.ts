import { goto } from '$app/navigation';
import { PUBLIC_API_BASE } from '$env/static/public';
import { toast } from './toast.svelte';

/**
 * Client API pour le backend Spouet.
 * Le token est stocké dans localStorage (côté client uniquement) — l'app est SPA.
 * PUBLIC_API_BASE : vide = chemins relatifs (nginx proxy), sinon URL complète du backend (ex. Tauri).
 */

const TOKEN_KEY = 'spouet:token';
const TOKEN_CREATED_KEY = 'spouet:token_created_at';
const TOKEN_EXPIRY_MS = 24 * 60 * 60 * 1000;
const BASE = (PUBLIC_API_BASE ?? '').replace(/\/$/, '');

export function getToken(): string | null {
    if (typeof localStorage === 'undefined') return null;
    return localStorage.getItem(TOKEN_KEY);
}

export function setToken(t: string | null): void {
    if (typeof localStorage === 'undefined') return;
    if (t === null) {
        localStorage.removeItem(TOKEN_KEY);
        localStorage.removeItem(TOKEN_CREATED_KEY);
    } else {
        localStorage.setItem(TOKEN_KEY, t);
        localStorage.setItem(TOKEN_CREATED_KEY, Date.now().toString());
    }
}

export function isTokenExpired(): boolean {
    if (typeof localStorage === 'undefined') return false;
    const created = localStorage.getItem(TOKEN_CREATED_KEY);
    if (!created) return false;
    return Date.now() - parseInt(created, 10) > TOKEN_EXPIRY_MS;
}

/**
 * Génère un UUID v4. Préfère `crypto.randomUUID()` quand disponible (HTTPS ou
 * localhost) ; sinon fallback `getRandomValues` ; en dernier recours, Math.random.
 *
 * Pourquoi : `crypto.randomUUID` n'existe que dans les "secure contexts". L'app
 * est souvent servie en HTTP simple sur le LAN — un appel direct lève
 * `TypeError: crypto.randomUUID is not a function` qui crashait silencieusement
 * `send()` dans la conversation (aucun message envoyé, aucun log backend).
 */
export function uuid(): string {
    const c: Crypto | undefined =
        typeof crypto !== 'undefined' ? (crypto as Crypto) : undefined;
    if (c?.randomUUID) return c.randomUUID();
    if (c?.getRandomValues) {
        const b = new Uint8Array(16);
        c.getRandomValues(b);
        b[6] = (b[6] & 0x0f) | 0x40;
        b[8] = (b[8] & 0x3f) | 0x80;
        const h = Array.from(b, (x) => x.toString(16).padStart(2, '0')).join('');
        return `${h.slice(0, 8)}-${h.slice(8, 12)}-${h.slice(12, 16)}-${h.slice(16, 20)}-${h.slice(20)}`;
    }
    // Fallback ultime — non cryptographique, suffisant comme clé de liste UI.
    return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
        const r = (Math.random() * 16) | 0;
        const v = c === 'x' ? r : (r & 0x3) | 0x8;
        return v.toString(16);
    });
}

export class ApiError extends Error {
    constructor(
        public status: number,
        public body: unknown,
        message: string
    ) {
        super(message);
    }
}

export async function api<T>(
    path: string,
    init: RequestInit & { json?: unknown } = {}
): Promise<T> {
    const token = getToken();
    const headers = new Headers(init.headers);
    if (token) headers.set('Authorization', `Bearer ${token}`);
    if (init.json !== undefined) {
        headers.set('Content-Type', 'application/json');
        init.body = JSON.stringify(init.json);
    }
    const res = await fetch(`${BASE}/api${path}`, { ...init, headers });
    if (!res.ok) {
        const body = await res.text();
        let parsed: unknown = body;
        try {
            parsed = JSON.parse(body);
        } catch {
            /* ignore */
        }
        if (res.status === 401) handleUnauthorized();
        throw new ApiError(res.status, parsed, `${res.status} ${res.statusText}`);
    }
    if (res.status === 204) return undefined as T;
    return (await res.json()) as T;
}

function handleUnauthorized(): void {
    if (typeof window === 'undefined') return;
    if (window.location.pathname === '/login') return;
    setToken(null);
    toast.error('Session expirée, reconnectez-vous.');
    goto('/login');
}

// ----------------------------------------------------------------------------
// SSE helper for streaming chat
// ----------------------------------------------------------------------------

export type SseEvent = { event: string; data: unknown };

/**
 * Stream SSE events depuis un POST. Le navigateur EventSource ne supporte que GET,
 * on utilise donc fetch + ReadableStream.
 */
export async function* streamSse(
    path: string,
    init: RequestInit & { json?: unknown } = {}
): AsyncIterable<SseEvent> {
    const token = getToken();
    const headers = new Headers(init.headers);
    headers.set('Accept', 'text/event-stream');
    if (token) headers.set('Authorization', `Bearer ${token}`);
    if (init.json !== undefined) {
        headers.set('Content-Type', 'application/json');
        init.body = JSON.stringify(init.json);
    }
    const res = await fetch(`${BASE}/api${path}`, { ...init, headers });
    if (!res.ok || !res.body) {
        if (res.status === 401) handleUnauthorized();
        throw new ApiError(res.status, null, `${res.status}`);
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buf = '';
    while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        let idx: number;
        while ((idx = buf.indexOf('\n\n')) !== -1) {
            const block = buf.slice(0, idx);
            buf = buf.slice(idx + 2);
            const ev = parseSseBlock(block);
            if (ev) yield ev;
        }
    }
}

function parseSseBlock(block: string): SseEvent | null {
    let event = 'message';
    const dataLines: string[] = [];
    for (const raw of block.split('\n')) {
        if (raw.startsWith(':')) continue;
        if (raw.startsWith('event: ')) event = raw.slice(7).trim();
        else if (raw.startsWith('data: ')) dataLines.push(raw.slice(6));
    }
    if (dataLines.length === 0) return null;
    const data = dataLines.join('\n');
    try {
        return { event, data: JSON.parse(data) };
    } catch {
        return { event, data };
    }
}

// ----------------------------------------------------------------------------
// Types & endpoints
// ----------------------------------------------------------------------------

export interface NodeCapabilities {
    compute_class: 'cpu' | 'cuda' | 'rocm';
    gpu_kind: 'none' | 'igpu' | 'dgpu';
    gpu_model: string | null;
    vram_total_mb: number | null;
    cpu_model: string | null;
    cpu_physical_cores: number;
    cpu_features: string[];
    llama_variant: string;
    force_cpu: boolean;
    warnings: string[];
    detection_notes: string[];
}

export interface NodeOut {
    id: string;
    name: string;
    host: string;
    port: number;
    agent_port: number | null;
    status: 'online' | 'offline';
    last_seen: string | null;
    vram_total_mb: number | null;
    vram_used_mb: number | null;
    ram_total_mb: number | null;
    ram_used_mb: number | null;
    disk_total_mb: number | null;
    disk_used_mb: number | null;
    gpu_model: string | null;
    agent_version: string | null;
    tags: string[];
    models: { name: string; supports_tools: boolean; size_bytes: number | null }[];
    // llama.cpp stats
    llama_running: boolean | null;
    llama_model_loaded: string | null;
    llama_n_ctx: number | null;
    llama_n_gpu_layers: number | null;
    llama_tps: number | null;
    llama_slots_active: number | null;
    llama_prompt_tokens_processed: number | null;
    llama_tokens_generated: number | null;
    capabilities: NodeCapabilities | null;
}

export interface LocalModelOut {
    name: string;
    path: string;
    size_bytes: number;
    parameter_size: string | null;
    quant: string | null;
    supports_tools: boolean;
}

export interface LlamaConfigPatch {
    n_ctx?: number;
    n_gpu_layers?: number;
    n_batch?: number;
    n_threads?: number;
    n_parallel?: number;
}

export interface ModelAgg {
    name: string;
    supports_tools: boolean;
    nodes: { id: string; name: string }[];
}

export interface MeOut {
    id: string;
    email: string;
    default_model?: string | null;
}

export interface ConversationOut {
    id: string;
    title: string;
    system_prompt: string | null;
    model_pref: string | null;
    archived: boolean;
    pinned: boolean;
    allowed_tool_slugs: string[];
    created_at: string;
    updated_at: string;
}

export interface ConversationPatch {
    title?: string;
    system_prompt?: string | null;
    model_pref?: string | null;
    allowed_tool_slugs?: string[];
    archived?: boolean;
    pinned?: boolean;
}

export interface MessageOut {
    id: string;
    role: 'user' | 'assistant' | 'tool' | 'system';
    content: string;
    model_used: string | null;
    tokens_in: number | null;
    tokens_out: number | null;
    latency_ms: number | null;
    ttft_ms?: number | null;
    finish_reason?: string | null;
    content_json?: Record<string, unknown> | null;
    created_at: string;
}

export interface ToolOut {
    id: string;
    slug: string;
    name: string;
    version: string;
    description: string;
    image: string;
    enabled: boolean;
    network_mode: string;
    timeout_s: number;
    requires_approval: boolean;
}

export interface JobOut {
    id: string;
    name: string;
    cron: string;
    prompt: string;
    tools_allowed: string[];
    model_pref: string | null;
    enabled: boolean;
    next_run_at: string | null;
    last_run_at: string | null;
}

export interface JobRunOut {
    id: string;
    job_id: string;
    status: string;
    output_text: string;
    error: string | null;
    tokens_total: number | null;
    started_at: string | null;
    finished_at: string | null;
    created_at: string;
}

export interface DocumentOut {
    id: string;
    title: string;
    source: string;
    mime: string;
    bytes: number;
    status: string;
    created_at: string;
}

export interface MemoryOut {
    id: string;
    key: string;
    value: string;
    score: number;
    pinned: boolean;
    created_at: string;
    last_used_at: string | null;
}

export const auth = {
    me: () => api<MeOut>('/auth/me'),
    patchMe: (json: { default_model?: string | null }) =>
        api<MeOut>('/auth/me', { method: 'PATCH', json }),
    tokenInfo: () => api<{ created_at: string | null; expires_at: string | null }>('/auth/token-info'),
    rotate: () => api<{ token: string }>('/auth/rotate', { method: 'POST' })
};

export interface DiagnosticComponent {
    ok: boolean;
    error: string | null;
    version?: string | null;
}

export interface DiagnosticsOut {
    status: 'ok' | 'degraded';
    version: string;
    components: {
        database: DiagnosticComponent;
        redis: DiagnosticComponent;
        docker: DiagnosticComponent;
    };
}

export const health = {
    ping: () => api<{ status: string; version: string; db: boolean }>('/health'),
    diagnostics: () => api<DiagnosticsOut>('/health/diagnostics')
};

export interface NodeProbeOut {
    reachable: boolean;
    error: string | null;
    models: string[];
}

export type MetricsRange = '1h' | '6h' | '24h' | '7d';

export interface MetricsPoint {
    time: string;
    cpu_pct: number | null;
    ram_used_mb: number | null;
    vram_used_mb: number | null;
    disk_used_mb: number | null;
    net_rx_kbps: number | null;
    net_tx_kbps: number | null;
    llama_tps: number | null;
    llama_slots_active: number | null;
    llama_running: boolean | null;
    llama_model_loaded: string | null;
    llama_queue_pending: number | null;
}

export interface NodeMetricsOut {
    node_id: string;
    range: MetricsRange;
    source: 'raw' | '1min';
    series: MetricsPoint[];
}

export interface ClusterAggregate {
    range: MetricsRange;
    nodes_online: number;
    nodes_total: number;
    total_tps_current: number;
    total_tokens_generated_window: number;
}

export const nodes = {
    list: () => api<NodeOut[]>('/nodes'),
    get: (id: string) => api<NodeOut>(`/nodes/${id}`),
    models: () => api<ModelAgg[]>('/nodes/models'),
    create: (json: { name: string; host: string; port?: number; tags?: string[] }) =>
        api<NodeOut>('/nodes', { method: 'POST', json }),
    probe: (json: { name: string; host: string; port?: number }) =>
        api<NodeProbeOut>('/nodes/probe', { method: 'POST', json }),
    delete: (id: string) => api<void>(`/nodes/${id}`, { method: 'DELETE' }),
    // llama.cpp management
    llamaConfig: (id: string) => api<Record<string, unknown>>(`/nodes/${id}/llama-config`),
    patchLlamaConfig: (id: string, json: LlamaConfigPatch) =>
        api<Record<string, unknown>>(`/nodes/${id}/llama-config`, { method: 'PATCH', json }),
    localModels: (id: string) => api<LocalModelOut[]>(`/nodes/${id}/local-models`),
    pullModel: (id: string, json: { hf_repo: string; filename: string; hf_token?: string }) =>
        api<Record<string, unknown>>(`/nodes/${id}/local-models/pull`, { method: 'POST', json }),
    pullStatus: (id: string) => api<Record<string, unknown>>(`/nodes/${id}/local-models/pull/status`),
    loadModel: (id: string, json: { filename: string }) =>
        api<Record<string, unknown>>(`/nodes/${id}/local-models/load`, { method: 'POST', json }),
    deleteLocalModel: (id: string, filename: string) =>
        api<void>(`/nodes/${id}/local-models/${encodeURIComponent(filename)}`, { method: 'DELETE' }),
    metrics: (id: string, range: MetricsRange = '1h') =>
        api<NodeMetricsOut>(`/nodes/${id}/metrics?range=${range}`),
    clusterAggregate: (range: MetricsRange = '24h') =>
        api<ClusterAggregate>(`/nodes/metrics/aggregate?range=${range}`),
    diag: (id: string) => api<Record<string, unknown>>(`/nodes/${id}/diag`)
};

export const conversations = {
    list: (q?: string) =>
        api<ConversationOut[]>(`/conversations${q ? `?q=${encodeURIComponent(q)}` : ''}`),
    get: (id: string) => api<ConversationOut>(`/conversations/${id}`),
    create: (json: { title?: string; model_pref?: string; system_prompt?: string }) =>
        api<ConversationOut>('/conversations', { method: 'POST', json }),
    patch: (id: string, json: ConversationPatch) =>
        api<ConversationOut>(`/conversations/${id}`, { method: 'PATCH', json }),
    clone: (id: string) =>
        api<ConversationOut>(`/conversations/${id}/clone`, { method: 'POST' }),
    delete: (id: string) => api<void>(`/conversations/${id}`, { method: 'DELETE' }),
    messages: (id: string) => api<MessageOut[]>(`/conversations/${id}/messages`),
    send: (id: string, json: { text: string; model?: string }) =>
        streamSse(`/conversations/${id}/messages`, { method: 'POST', json }),
    regenerate: (id: string, json: { model?: string } = {}) =>
        streamSse(`/conversations/${id}/regenerate`, { method: 'POST', json }),
    editMessage: (
        convId: string,
        msgId: string,
        json: { text: string; model?: string }
    ) => streamSse(`/conversations/${convId}/messages/${msgId}/edit`, { method: 'POST', json }),
    exportUrl: (id: string): string => `${BASE}/api/conversations/${id}/export`,
    export: async (id: string): Promise<{ blob: Blob; filename: string }> => {
        const token = getToken();
        const res = await fetch(`${BASE}/api/conversations/${id}/export`, {
            headers: token ? { Authorization: `Bearer ${token}` } : {}
        });
        if (!res.ok) throw new ApiError(res.status, await res.text(), `${res.status}`);
        const cd = res.headers.get('content-disposition') || '';
        const m = /filename="([^"]+)"/.exec(cd);
        const filename = m?.[1] ?? `conversation-${id}.md`;
        return { blob: await res.blob(), filename };
    }
};

export const tools = {
    list: () => api<ToolOut[]>('/tools'),
    patch: (id: string, json: { enabled?: boolean; requires_approval?: boolean }) =>
        api<ToolOut>(`/tools/${id}`, { method: 'PATCH', json }),
    decideApproval: (requestId: string, approved: boolean, note?: string) =>
        api<void>(`/tools/approvals/${requestId}`, { method: 'POST', json: { approved, note } })
};

export const jobs = {
    list: () => api<JobOut[]>('/jobs'),
    create: (json: { name: string; cron: string; prompt: string; model_pref?: string }) =>
        api<JobOut>('/jobs', { method: 'POST', json }),
    patch: (
        id: string,
        json: {
            name?: string;
            cron?: string;
            prompt?: string;
            tools_allowed?: string[];
            model_pref?: string | null;
            enabled?: boolean;
        }
    ) => api<JobOut>(`/jobs/${id}`, { method: 'PATCH', json }),
    delete: (id: string) => api<void>(`/jobs/${id}`, { method: 'DELETE' }),
    run: (id: string) => api<{ task_id: string }>(`/jobs/${id}/run`, { method: 'POST' }),
    runs: (id: string) => api<JobRunOut[]>(`/jobs/${id}/runs`)
};

export const rag = {
    list: () => api<DocumentOut[]>('/rag/documents'),
    upload: async (file: File): Promise<DocumentOut> => {
        const fd = new FormData();
        fd.append('file', file);
        const token = getToken();
        const res = await fetch(`${BASE}/api/rag/documents`, {
            method: 'POST',
            headers: token ? { Authorization: `Bearer ${token}` } : {},
            body: fd
        });
        if (!res.ok) throw new ApiError(res.status, await res.text(), `${res.status}`);
        return res.json();
    },
    delete: (id: string) => api<void>(`/rag/documents/${id}`, { method: 'DELETE' }),
    search: (q: string, k = 6) =>
        api<unknown[]>(`/rag/search?q=${encodeURIComponent(q)}&k=${k}`)
};

export const memory = {
    list: () => api<MemoryOut[]>('/memory'),
    upsert: (json: { key: string; value: string; pinned?: boolean }) =>
        api<MemoryOut>('/memory', { method: 'POST', json }),
    patch: (id: string, json: { pinned?: boolean; value?: string }) =>
        api<MemoryOut>(`/memory/${id}`, { method: 'PATCH', json }),
    delete: (id: string) => api<void>(`/memory/${id}`, { method: 'DELETE' })
};

// ----------------------------------------------------------------------------
// Coffre de secrets
// ----------------------------------------------------------------------------

export interface SecretOut {
    scope: string;
    key: string;
    description: string;
    preview: string;
    decryptable: boolean;
}

export const secrets = {
    list: (scope?: string) =>
        api<SecretOut[]>(scope ? `/secrets?scope=${encodeURIComponent(scope)}` : '/secrets'),
    upsert: (json: { scope: string; key: string; value: string; description?: string }) =>
        api<SecretOut>('/secrets', { method: 'PUT', json }),
    delete: (scope: string, key: string) =>
        api<void>(`/secrets/${encodeURIComponent(scope)}/${encodeURIComponent(key)}`, {
            method: 'DELETE'
        })
};

// ----------------------------------------------------------------------------
// Connectors persistants
// ----------------------------------------------------------------------------

export interface ConnectorOut {
    id: string;
    slug: string;
    name: string;
    version: string;
    description: string;
    image: string;
    enabled: boolean;
    status: 'stopped' | 'starting' | 'running' | 'crashed';
    container_id: string | null;
    last_error: string | null;
    inbound_kinds: string[];
    outbound_kinds: string[];
    secrets_required: Record<string, string>;
    config_schema: Record<string, unknown>;
    config: Record<string, unknown>;
    metadata?: Record<string, unknown>;
    invite_url?: string | null;
}

export interface ConnectorRouteOut {
    id: string;
    external_id: string;
    conversation_id: string;
    metadata: Record<string, unknown>;
    created_at: string;
    last_seen_at: string | null;
}

export interface ConnectorStartOut {
    state: string;
    container_id: string | null;
    error: string | null;
}

export interface DiscordQuickInstallIn {
    token: string;
    bot_persona?: string;
    default_model?: string;
    allowed_channels?: string[];
    respond_dm?: boolean;
    trigger_prefix?: string;
}

export const connectors = {
    list: () => api<ConnectorOut[]>('/connectors'),
    install: (path: string) =>
        api<ConnectorOut>('/connectors/install', { method: 'POST', json: { path } }),
    quickInstallDiscord: (json: DiscordQuickInstallIn) =>
        api<ConnectorOut>('/connectors/quick-install/discord', { method: 'POST', json }),
    patch: (id: string, json: { enabled?: boolean; config?: Record<string, unknown> }) =>
        api<ConnectorOut>(`/connectors/${id}`, { method: 'PATCH', json }),
    delete: (id: string) => api<void>(`/connectors/${id}`, { method: 'DELETE' }),
    start: (id: string) => api<ConnectorStartOut>(`/connectors/${id}/start`, { method: 'POST' }),
    stop: (id: string) => api<ConnectorStartOut>(`/connectors/${id}/stop`, { method: 'POST' }),
    refresh: (id: string) =>
        api<ConnectorStartOut>(`/connectors/${id}/refresh`, { method: 'POST' }),
    routes: (id: string) => api<ConnectorRouteOut[]>(`/connectors/${id}/routes`),
    logs: (id: string, tail = 200) =>
        api<{ logs: string }>(`/connectors/${id}/logs?tail=${tail}`)
};

// ----------------------------------------------------------------------------
// Workspaces multi-agents
// ----------------------------------------------------------------------------

export interface WorkerConfig {
    title: string;
    model_pref: string;
    system_prompt?: string | null;
    allowed_tool_slugs?: string[];
}

export interface WorkspaceCreate {
    name?: string;
    manager_model: string;
    manager_system_prompt?: string | null;
    workers?: WorkerConfig[];
}

export interface ConversationRef {
    id: string;
    title: string;
    workspace_role: string;
    model_pref: string | null;
    created_at: string;
}

export interface WorkspaceOut {
    id: string;
    name: string;
    conversations: ConversationRef[];
    created_at: string;
    updated_at: string;
}

// ----------------------------------------------------------------------------
// Prompt templates
// ----------------------------------------------------------------------------

export interface PromptTemplateOut {
    id: string;
    name: string;
    content: string;
    shortcut: string | null;
    created_at: string;
    updated_at: string;
}

export const promptTemplates = {
    list: () => api<PromptTemplateOut[]>('/prompt-templates'),
    create: (json: { name: string; content: string; shortcut?: string | null }) =>
        api<PromptTemplateOut>('/prompt-templates', { method: 'POST', json }),
    patch: (id: string, json: { name?: string; content?: string; shortcut?: string | null }) =>
        api<PromptTemplateOut>(`/prompt-templates/${id}`, { method: 'PATCH', json }),
    delete: (id: string) => api<void>(`/prompt-templates/${id}`, { method: 'DELETE' })
};

export const workspaces = {
    list: () => api<WorkspaceOut[]>('/workspaces'),
    get: (id: string) => api<WorkspaceOut>(`/workspaces/${id}`),
    create: (json: WorkspaceCreate) =>
        api<WorkspaceOut>('/workspaces', { method: 'POST', json }),
    delete: (id: string) => api<void>(`/workspaces/${id}`, { method: 'DELETE' }),
    stream: (id: string) => streamSse(`/workspaces/${id}/stream`)
};
