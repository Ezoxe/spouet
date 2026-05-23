<script lang="ts">
    import { onMount } from 'svelte';
    import {
        mail,
        type MailAccountOut,
        type MailMessageOut,
        type MailDraftOut,
        type MailAccountIn
    } from '$lib/api';
    import { toast } from '$lib/toast.svelte';
    import {
        RefreshCw,
        Plus,
        Trash2,
        Send,
        X,
        Mail,
        CheckCircle2,
        XCircle,
        ShieldAlert,
        Inbox,
        Pencil
    } from 'lucide-svelte';

    let accounts: MailAccountOut[] = $state([]);
    let messages: MailMessageOut[] = $state([]);
    let drafts: MailDraftOut[] = $state([]);
    let tab: 'drafts' | 'inbox' = $state('drafts');
    let loading = $state(false);
    let syncing = $state(false);
    let showAdd = $state(false);

    // Édition inline des brouillons : id -> {subject, body}
    let edits: Record<string, { subject: string; body: string }> = $state({});

    const emptyForm = (): MailAccountIn => ({
        name: '',
        email: '',
        imap_host: '',
        imap_port: 993,
        imap_ssl: true,
        smtp_host: '',
        smtp_port: 465,
        smtp_ssl: true,
        username: '',
        password: '',
        auto_classify: true,
        auto_trash_spam: false,
        spam_folder: 'Junk',
        auto_draft_replies: true,
        signature: ''
    });
    let form: MailAccountIn = $state(emptyForm());
    let preset = $state('gmail');

    const PRESETS: Record<string, Partial<MailAccountIn>> = {
        gmail: {
            imap_host: 'imap.gmail.com',
            imap_port: 993,
            imap_ssl: true,
            smtp_host: 'smtp.gmail.com',
            smtp_port: 465,
            smtp_ssl: true
        },
        outlook: {
            imap_host: 'outlook.office365.com',
            imap_port: 993,
            imap_ssl: true,
            smtp_host: 'smtp.office365.com',
            smtp_port: 587,
            smtp_ssl: false
        },
        icloud: {
            imap_host: 'imap.mail.me.com',
            imap_port: 993,
            imap_ssl: true,
            smtp_host: 'smtp.mail.me.com',
            smtp_port: 587,
            smtp_ssl: false
        },
        autre: {}
    };

    function applyPreset() {
        Object.assign(form, PRESETS[preset] ?? {});
    }

    const CLASS_STYLE: Record<string, string> = {
        spam: 'bg-red-500/15 text-red-300 ring-red-500/30',
        important: 'bg-amber-500/15 text-amber-300 ring-amber-500/30',
        newsletter: 'bg-sky-500/15 text-sky-300 ring-sky-500/30',
        notification: 'bg-violet-500/15 text-violet-300 ring-violet-500/30',
        normal: 'bg-neutral-500/15 text-neutral-300 ring-neutral-500/30'
    };

    async function loadAll() {
        loading = true;
        try {
            [accounts, drafts, messages] = await Promise.all([
                mail.accounts(),
                mail.drafts('pending'),
                mail.messages({ limit: 100 })
            ]);
        } catch {
            toast.error('Chargement des mails impossible.');
        } finally {
            loading = false;
        }
    }

    async function sync() {
        syncing = true;
        try {
            await mail.sync();
            toast.success('Synchronisation lancée — patientez quelques secondes.');
            setTimeout(loadAll, 4000);
        } catch {
            toast.error('Synchronisation impossible.');
        } finally {
            syncing = false;
        }
    }

    async function addAccount() {
        if (!form.email || !form.imap_host || !form.smtp_host || !form.password) {
            toast.error('Email, serveurs et mot de passe sont requis.');
            return;
        }
        if (!form.username) form.username = form.email;
        if (!form.name) form.name = form.email;
        try {
            await mail.createAccount({ ...form });
            toast.success('Boîte ajoutée.');
            showAdd = false;
            form = emptyForm();
            await loadAll();
        } catch {
            toast.error("Impossible d'ajouter la boîte.");
        }
    }

    async function testAccount(a: MailAccountOut) {
        toast.info?.('Test en cours…');
        try {
            const r = await mail.testAccount(a.id);
            if (r.imap_ok && r.smtp_ok) toast.success('IMAP et SMTP OK.');
            else toast.error(r.error || 'Échec de connexion.');
        } catch {
            toast.error('Test impossible.');
        }
    }

    async function toggleAccount(a: MailAccountOut) {
        try {
            await mail.patchAccount(a.id, { enabled: !a.enabled });
            await loadAll();
        } catch {
            toast.error('Modification impossible.');
        }
    }

    async function removeAccount(a: MailAccountOut) {
        if (!confirm(`Supprimer la boîte ${a.email} ? (les mails restent sur le serveur)`)) return;
        try {
            await mail.deleteAccount(a.id);
            await loadAll();
        } catch {
            toast.error('Suppression impossible.');
        }
    }

    function startEdit(d: MailDraftOut) {
        edits[d.id] = { subject: d.subject, body: d.body };
    }
    function cancelEdit(id: string) {
        delete edits[id];
        edits = { ...edits };
    }
    async function saveEdit(d: MailDraftOut) {
        const e = edits[d.id];
        if (!e) return;
        try {
            await mail.patchDraft(d.id, { subject: e.subject, body: e.body });
            cancelEdit(d.id);
            await loadAll();
            toast.success('Brouillon mis à jour.');
        } catch {
            toast.error('Mise à jour impossible.');
        }
    }

    async function sendDraft(d: MailDraftOut) {
        if (!confirm(`Envoyer cette réponse à ${d.to_addrs} ?`)) return;
        try {
            await mail.sendDraft(d.id);
            toast.success('Réponse envoyée.');
            await loadAll();
        } catch (e) {
            toast.error('Envoi échoué.');
        }
    }

    async function rejectDraft(d: MailDraftOut) {
        if (!confirm('Rejeter (supprimer) ce brouillon ?')) return;
        try {
            await mail.rejectDraft(d.id);
            await loadAll();
        } catch {
            toast.error('Action impossible.');
        }
    }

    function accountEmail(id: string): string {
        return accounts.find((a) => a.id === id)?.email ?? '';
    }

    onMount(loadAll);
</script>

<header class="flex flex-wrap items-center justify-between gap-3 px-6 py-5 sm:px-8">
    <div>
        <h1 class="text-2xl font-semibold tracking-tight">Mail</h1>
        <p class="mt-1 text-xs text-neutral-500">
            Tri automatique, surveillance et réponses validées avant envoi.
        </p>
    </div>
    <div class="flex items-center gap-2">
        <button
            type="button"
            onclick={sync}
            disabled={syncing || accounts.length === 0}
            class="flex items-center gap-1.5 rounded-lg border border-neutral-700 px-3 py-1.5 text-sm hover:bg-neutral-800 disabled:opacity-50"
        >
            <RefreshCw size={14} class={syncing ? 'animate-spin' : ''} /> Synchroniser
        </button>
        <button
            type="button"
            onclick={() => {
                form = emptyForm();
                applyPreset();
                showAdd = true;
            }}
            class="flex items-center gap-1.5 rounded-lg bg-cyan-600 px-3 py-1.5 text-sm text-white hover:bg-cyan-500"
        >
            <Plus size={14} /> Ajouter une boîte
        </button>
    </div>
</header>

<div class="space-y-4 px-6 pb-10 sm:px-8">
    <!-- Comptes -->
    <section class="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {#each accounts as a (a.id)}
            <div class="rounded-xl border border-neutral-800 bg-neutral-900/60 p-4">
                <div class="flex items-start justify-between gap-2">
                    <div class="min-w-0">
                        <p class="flex items-center gap-1.5 truncate text-sm font-medium">
                            <Mail size={14} class="shrink-0 text-cyan-400" />
                            {a.email}
                        </p>
                        <p class="mt-0.5 truncate text-[11px] text-neutral-500">
                            {a.imap_host} · {a.enabled ? 'actif' : 'désactivé'}
                        </p>
                    </div>
                </div>
                <div class="mt-2 flex flex-wrap gap-1 text-[10px]">
                    {#if a.auto_classify}<span class="rounded bg-neutral-800 px-1.5 py-0.5">tri IA</span>{/if}
                    {#if a.auto_trash_spam}<span class="rounded bg-red-950/60 px-1.5 py-0.5 text-red-300">spam→{a.spam_folder}</span>{/if}
                    {#if a.auto_draft_replies}<span class="rounded bg-cyan-950/60 px-1.5 py-0.5 text-cyan-300">réponses auto</span>{/if}
                </div>
                {#if a.last_error}
                    <p class="mt-2 break-words text-[10px] text-red-400/80">⚠ {a.last_error}</p>
                {:else if a.last_sync_at}
                    <p class="mt-2 text-[10px] text-neutral-600">
                        Sync : {new Date(a.last_sync_at).toLocaleString('fr-FR')}
                    </p>
                {/if}
                <div class="mt-3 flex items-center gap-1.5">
                    <button type="button" onclick={() => testAccount(a)} class="rounded border border-neutral-700 px-2 py-1 text-[11px] hover:bg-neutral-800">Tester</button>
                    <button type="button" onclick={() => toggleAccount(a)} class="rounded border border-neutral-700 px-2 py-1 text-[11px] hover:bg-neutral-800">{a.enabled ? 'Désactiver' : 'Activer'}</button>
                    <button type="button" onclick={() => removeAccount(a)} class="ml-auto rounded p-1 text-neutral-500 hover:bg-red-950 hover:text-red-300" aria-label="Supprimer"><Trash2 size={13} /></button>
                </div>
            </div>
        {/each}
        {#if accounts.length === 0 && !loading}
            <p class="text-sm text-neutral-500">Aucune boîte connectée. Cliquez « Ajouter une boîte ».</p>
        {/if}
    </section>

    <!-- Onglets -->
    <div class="flex gap-1 border-b border-neutral-800">
        <button
            type="button"
            onclick={() => (tab = 'drafts')}
            class="flex items-center gap-1.5 px-3 py-2 text-sm {tab === 'drafts' ? 'border-b-2 border-cyan-400 text-cyan-300' : 'text-neutral-400'}"
        >
            <ShieldAlert size={14} /> À valider
            {#if drafts.length}<span class="rounded-full bg-cyan-500/20 px-1.5 text-[10px] text-cyan-300">{drafts.length}</span>{/if}
        </button>
        <button
            type="button"
            onclick={() => (tab = 'inbox')}
            class="flex items-center gap-1.5 px-3 py-2 text-sm {tab === 'inbox' ? 'border-b-2 border-cyan-400 text-cyan-300' : 'text-neutral-400'}"
        >
            <Inbox size={14} /> Réception
        </button>
    </div>

    {#if tab === 'drafts'}
        <section class="space-y-3">
            {#each drafts as d (d.id)}
                <div class="rounded-xl border border-cyan-900/40 bg-neutral-900/60 p-4">
                    <div class="mb-2 flex flex-wrap items-center justify-between gap-2 text-xs text-neutral-400">
                        <span>À : <span class="text-neutral-200">{d.to_addrs}</span></span>
                        <span class="text-neutral-600">via {accountEmail(d.account_id)}</span>
                    </div>
                    {#if edits[d.id]}
                        <input
                            bind:value={edits[d.id].subject}
                            class="mb-2 w-full rounded border border-neutral-700 bg-neutral-950 px-2 py-1 text-sm focus:border-cyan-500/50 focus:outline-none"
                        />
                        <textarea
                            bind:value={edits[d.id].body}
                            rows="8"
                            class="w-full resize-y rounded border border-neutral-700 bg-neutral-950 px-2 py-1.5 text-sm focus:border-cyan-500/50 focus:outline-none"
                        ></textarea>
                        <div class="mt-2 flex gap-2">
                            <button type="button" onclick={() => saveEdit(d)} class="rounded bg-cyan-600 px-3 py-1 text-xs text-white hover:bg-cyan-500">Enregistrer</button>
                            <button type="button" onclick={() => cancelEdit(d.id)} class="rounded border border-neutral-700 px-3 py-1 text-xs hover:bg-neutral-800">Annuler</button>
                        </div>
                    {:else}
                        <p class="mb-1 text-sm font-medium">{d.subject}</p>
                        <p class="mb-3 whitespace-pre-wrap rounded bg-neutral-950/60 p-3 text-sm text-neutral-300">{d.body}</p>
                        <div class="flex flex-wrap gap-2">
                            <button type="button" onclick={() => sendDraft(d)} class="flex items-center gap-1.5 rounded bg-emerald-600 px-3 py-1.5 text-xs text-white hover:bg-emerald-500">
                                <Send size={13} /> Envoyer
                            </button>
                            <button type="button" onclick={() => startEdit(d)} class="flex items-center gap-1.5 rounded border border-neutral-700 px-3 py-1.5 text-xs hover:bg-neutral-800">
                                <Pencil size={13} /> Modifier
                            </button>
                            <button type="button" onclick={() => rejectDraft(d)} class="flex items-center gap-1.5 rounded border border-red-900/50 px-3 py-1.5 text-xs text-red-300 hover:bg-red-950/40">
                                <X size={13} /> Rejeter
                            </button>
                        </div>
                    {/if}
                </div>
            {/each}
            {#if drafts.length === 0 && !loading}
                <p class="py-8 text-center text-sm text-neutral-500">
                    Aucune réponse en attente de validation.
                </p>
            {/if}
        </section>
    {:else}
        <section class="space-y-1.5">
            {#each messages as m (m.id)}
                <div class="flex items-start gap-3 rounded-lg border border-neutral-800/60 bg-neutral-900/40 px-3 py-2">
                    <span class="mt-0.5 shrink-0 rounded px-1.5 py-0.5 text-[10px] uppercase ring-1 {CLASS_STYLE[m.classification ?? 'normal'] ?? CLASS_STYLE.normal}">
                        {m.classification ?? '—'}
                    </span>
                    <div class="min-w-0 flex-1">
                        <div class="flex items-center justify-between gap-2">
                            <p class="truncate text-sm">
                                <span class="font-medium">{m.from_name || m.from_addr}</span>
                                <span class="text-neutral-500"> — {m.subject || '(sans objet)'}</span>
                            </p>
                            {#if m.needs_reply}<span class="shrink-0 text-[10px] text-cyan-400">↩ à répondre</span>{/if}
                        </div>
                        {#if m.summary}<p class="truncate text-xs text-neutral-500">{m.summary}</p>{/if}
                        {#if m.action_taken === 'trashed'}<p class="text-[10px] text-red-400/70">déplacé vers le dossier spam</p>{/if}
                    </div>
                </div>
            {/each}
            {#if messages.length === 0 && !loading}
                <p class="py-8 text-center text-sm text-neutral-500">Aucun message analysé pour l'instant.</p>
            {/if}
        </section>
    {/if}
</div>

<!-- Modal ajout de boîte -->
{#if showAdd}
    <div class="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" role="dialog" aria-modal="true">
        <div class="max-h-[90vh] w-full max-w-lg overflow-y-auto rounded-xl border border-neutral-700 bg-neutral-900 p-5">
            <div class="mb-3 flex items-center justify-between">
                <h2 class="text-sm font-semibold uppercase tracking-wider text-neutral-300">Nouvelle boîte mail</h2>
                <button type="button" onclick={() => (showAdd = false)} aria-label="Fermer" class="rounded p-1 text-neutral-500 hover:bg-white/5"><X size={16} /></button>
            </div>

            <label class="mb-2 block text-xs text-neutral-400">
                Fournisseur
                <select bind:value={preset} onchange={applyPreset} class="mt-1 w-full rounded border border-neutral-700 bg-neutral-950 px-2 py-1.5 text-sm">
                    <option value="gmail">Gmail</option>
                    <option value="outlook">Outlook / Office 365</option>
                    <option value="icloud">iCloud</option>
                    <option value="autre">Autre (manuel)</option>
                </select>
            </label>

            {#if preset === 'gmail'}
                <p class="mb-2 rounded bg-amber-950/30 p-2 text-[11px] text-amber-200">
                    Gmail exige un « mot de passe d'application » (compte avec 2FA) — pas votre mot de passe habituel.
                </p>
            {/if}

            <div class="grid gap-2 sm:grid-cols-2">
                <label class="text-xs text-neutral-400">Adresse email
                    <input bind:value={form.email} type="email" placeholder="moi@exemple.fr" class="mt-1 w-full rounded border border-neutral-700 bg-neutral-950 px-2 py-1.5 text-sm" />
                </label>
                <label class="text-xs text-neutral-400">Mot de passe
                    <input bind:value={form.password} type="password" class="mt-1 w-full rounded border border-neutral-700 bg-neutral-950 px-2 py-1.5 text-sm" />
                </label>
                <label class="text-xs text-neutral-400">Serveur IMAP
                    <input bind:value={form.imap_host} class="mt-1 w-full rounded border border-neutral-700 bg-neutral-950 px-2 py-1.5 text-sm" />
                </label>
                <label class="text-xs text-neutral-400">Port IMAP
                    <input bind:value={form.imap_port} type="number" class="mt-1 w-full rounded border border-neutral-700 bg-neutral-950 px-2 py-1.5 text-sm" />
                </label>
                <label class="text-xs text-neutral-400">Serveur SMTP
                    <input bind:value={form.smtp_host} class="mt-1 w-full rounded border border-neutral-700 bg-neutral-950 px-2 py-1.5 text-sm" />
                </label>
                <label class="text-xs text-neutral-400">Port SMTP
                    <input bind:value={form.smtp_port} type="number" class="mt-1 w-full rounded border border-neutral-700 bg-neutral-950 px-2 py-1.5 text-sm" />
                </label>
            </div>

            <div class="mt-3 space-y-1.5 border-t border-neutral-800 pt-3">
                <label class="flex items-center gap-2 text-xs text-neutral-300">
                    <input type="checkbox" bind:checked={form.auto_classify} /> Trier automatiquement (spam, importance)
                </label>
                <label class="flex items-center gap-2 text-xs text-neutral-300">
                    <input type="checkbox" bind:checked={form.auto_trash_spam} /> Déplacer les spams vers
                    <input bind:value={form.spam_folder} class="w-24 rounded border border-neutral-700 bg-neutral-950 px-1.5 py-0.5 text-xs" />
                </label>
                <label class="flex items-center gap-2 text-xs text-neutral-300">
                    <input type="checkbox" bind:checked={form.auto_draft_replies} /> Préparer des réponses (validation requise)
                </label>
                <label class="block text-xs text-neutral-400">Signature
                    <textarea bind:value={form.signature} rows="2" class="mt-1 w-full resize-y rounded border border-neutral-700 bg-neutral-950 px-2 py-1.5 text-sm"></textarea>
                </label>
            </div>

            <div class="mt-4 flex justify-end gap-2">
                <button type="button" onclick={() => (showAdd = false)} class="rounded border border-neutral-700 px-3 py-1.5 text-sm hover:bg-neutral-800">Annuler</button>
                <button type="button" onclick={addAccount} class="rounded bg-cyan-600 px-3 py-1.5 text-sm text-white hover:bg-cyan-500">Ajouter</button>
            </div>
        </div>
    </div>
{/if}
