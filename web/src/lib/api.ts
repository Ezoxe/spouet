/**
 * Client API pour le backend Spouet.
 * Le token est stocké dans localStorage (côté client uniquement) — l'app est SPA.
 */

const TOKEN_KEY = 'spouet:token';

export function getToken(): string | null {
    if (typeof localStorage === 'undefined') return null;
    return localStorage.getItem(TOKEN_KEY);
}

export function setToken(t: string | null): void {
    if (typeof localStorage === 'undefined') return;
    if (t === null) localStorage.removeItem(TOKEN_KEY);
    else localStorage.setItem(TOKEN_KEY, t);
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
    const res = await fetch(`/api${path}`, { ...init, headers });
    if (!res.ok) {
        const body = await res.text();
        let parsed: unknown = body;
        try {
            parsed = JSON.parse(body);
        } catch {
            /* ignore */
        }
        throw new ApiError(res.status, parsed, `${res.status} ${res.statusText}`);
    }
    if (res.status === 204) return undefined as T;
    return (await res.json()) as T;
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
    const res = await fetch(`/api${path}`, { ...init, headers });
    if (!res.ok || !res.body) throw new ApiError(res.status, null, `${res.status}`);

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

export interface NodeOut {
    id: string;
    name: string;
    host: string;
    port: number;
    status: 'online' | 'offline';
    last_seen: string | null;
    vram_total_mb: number | null;
    vram_used_mb: number | null;
    gpu_model: string | null;
    agent_version: string | null;
    tags: string[];
    models: { name: string; supports_tools: boolean; size_bytes: number | null }[];
}

export interface ModelAgg {
    name: string;
    supports_tools: boolean;
    nodes: { id: string; name: string }[];
}

export interface MeOut {
    id: string;
    email: string;
}

export interface ConversationOut {
    id: string;
    title: string;
    system_prompt: string | null;
    model_pref: string | null;
    archived: boolean;
    created_at: string;
    updated_at: string;
}

export interface MessageOut {
    id: string;
    role: 'user' | 'assistant' | 'tool' | 'system';
    content: string;
    model_used: string | null;
    tokens_in: number | null;
    tokens_out: number | null;
    latency_ms: number | null;
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
    created_at: string;
    last_used_at: string | null;
}

export const auth = {
    me: () => api<MeOut>('/auth/me'),
    rotate: () => api<{ token: string }>('/auth/rotate', { method: 'POST' })
};

export const nodes = {
    list: () => api<NodeOut[]>('/nodes'),
    models: () => api<ModelAgg[]>('/nodes/models'),
    delete: (id: string) => api<void>(`/nodes/${id}`, { method: 'DELETE' })
};

export const conversations = {
    list: () => api<ConversationOut[]>('/conversations'),
    get: (id: string) => api<ConversationOut>(`/conversations/${id}`),
    create: (json: { title?: string; model_pref?: string; system_prompt?: string }) =>
        api<ConversationOut>('/conversations', { method: 'POST', json }),
    messages: (id: string) => api<MessageOut[]>(`/conversations/${id}/messages`),
    send: (id: string, json: { text: string; model?: string }) =>
        streamSse(`/conversations/${id}/messages`, { method: 'POST', json })
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
        const res = await fetch('/api/rag/documents', {
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
    upsert: (json: { key: string; value: string }) =>
        api<MemoryOut>('/memory', { method: 'POST', json }),
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

export const connectors = {
    list: () => api<ConnectorOut[]>('/connectors'),
    install: (path: string) =>
        api<ConnectorOut>('/connectors/install', { method: 'POST', json: { path } }),
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
