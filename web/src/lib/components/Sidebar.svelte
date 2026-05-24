<script lang="ts">
    import { page } from '$app/stores';
    import { goto } from '$app/navigation';
    import { onMount } from 'svelte';
    import { fly } from 'svelte/transition';
    import {
        Activity,
        MessageSquare,
        Wrench,
        Clock,
        FileText,
        Brain,
        Settings,
        Plus,
        Server,
        Plug,
        KeyRound,
        Trash2,
        Menu,
        LayoutPanelLeft,
        Search,
        X,
        BookOpen,
        Pin,
        PinOff,
        Mail,
        Music,
        MonitorPlay
    } from 'lucide-svelte';
    import { conversations, type ConversationOut } from '$lib/api';
    import { toast } from '$lib/toast.svelte';
    import Logo from './Logo.svelte';

    let convs: ConversationOut[] = $state([]);
    let isOpen = $state(false);
    let searchQuery = $state('');
    let searchTimer: ReturnType<typeof setTimeout> | null = null;

    const items = [
        { href: '/', label: 'Tableau de bord', icon: Activity },
        { href: '/chat', label: 'Conversations', icon: MessageSquare },
        { href: '/workspaces', label: 'Workspaces', icon: LayoutPanelLeft },
        { href: '/nodes', label: 'Nodes', icon: Server },
        { href: '/tools', label: 'Tools', icon: Wrench },
        { href: '/templates', label: 'Templates', icon: BookOpen },
        { href: '/connectors', label: 'Connectors', icon: Plug },
        { href: '/mail', label: 'Mail', icon: Mail },
        { href: '/spotify', label: 'Spotify', icon: Music },
        { href: '/macros', label: 'Macros PC', icon: MonitorPlay },
        { href: '/jobs', label: 'Tâches', icon: Clock },
        { href: '/docs', label: 'Documents', icon: FileText },
        { href: '/memory', label: 'Mémoire', icon: Brain },
        { href: '/secrets', label: 'Secrets', icon: KeyRound },
        { href: '/stats', label: 'Statistiques', icon: Activity },
        { href: '/settings', label: 'Paramètres', icon: Settings }
    ];

    async function refreshConvs() {
        try {
            convs = await conversations.list(searchQuery.trim() || undefined);
        } catch {
            convs = [];
        }
    }

    function onSearchInput() {
        if (searchTimer) clearTimeout(searchTimer);
        searchTimer = setTimeout(refreshConvs, 180);
    }
    function clearSearch() {
        searchQuery = '';
        refreshConvs();
    }

    async function newConversation() {
        try {
            const c = await conversations.create({ title: 'Nouvelle conversation' });
            await refreshConvs();
            goto(`/chat/${c.id}`);
        } catch {
            toast.error('Impossible de créer la conversation');
        }
    }

    async function deleteConversation(ev: Event, c: ConversationOut) {
        ev.preventDefault();
        ev.stopPropagation();
        if (!confirm(`Supprimer la conversation « ${c.title} » ?`)) return;
        try {
            await conversations.delete(c.id);
            await refreshConvs();
            if ($page.url.pathname === `/chat/${c.id}`) goto('/chat');
        } catch {
            toast.error('Suppression impossible');
        }
    }

    async function togglePin(ev: Event, c: ConversationOut) {
        ev.preventDefault();
        ev.stopPropagation();
        try {
            await conversations.patch(c.id, { pinned: !c.pinned });
            await refreshConvs();
        } catch {
            toast.error('Impossible d\'épingler la conversation');
        }
    }

    function isActive(href: string): boolean {
        if (href === '/') return $page.url.pathname === '/';
        // /workspaces couvre aussi /workspace/[id]
        if (href === '/workspaces') {
            return (
                $page.url.pathname === '/workspaces' ||
                $page.url.pathname.startsWith('/workspaces/') ||
                $page.url.pathname.startsWith('/workspace/')
            );
        }
        return $page.url.pathname === href || $page.url.pathname.startsWith(href + '/');
    }

    onMount(refreshConvs);
</script>


<!-- Mobile header & toggle -->
<div class="md:hidden flex w-full shrink-0 items-center justify-between px-4 py-3 border-b border-[var(--color-border-subtle)] bg-[var(--color-bg-1)] z-50 relative">
    <div class="flex items-center gap-2">
        <Logo size={24} glow />
        <span class="font-semibold text-sm">Spouet</span>
    </div>
    <button id="toggle-menu-btn" aria-label="Toggle menu" onclick={() => {isOpen = !isOpen}} class="p-2 rounded text-neutral-400 hover:text-white focus:outline-none z-50 relative pointer-events-auto">
        <Menu size={24} />
    </button>
</div>

<!-- Backdrop for mobile -->
{#if isOpen}
    <button
        type="button"
        class="fixed inset-0 z-40 bg-black/50 backdrop-blur-sm md:hidden"
        onclick={() => isOpen = false}
        aria-label="Fermer le menu"
    ></button>
{/if}

<aside
    class="{isOpen ? 'translate-x-0' : '-translate-x-full'} md:translate-x-0
           fixed inset-y-0 left-0 z-50 flex w-64 shrink-0 flex-col border-r border-[var(--color-border-subtle)]
           bg-[color-mix(in_oklch,var(--color-bg-1)_85%,transparent)] backdrop-blur-md transition-transform duration-200 ease-in-out md:static md:flex"
>
    <div class="flex items-center gap-2.5 px-4 py-4">
        <div
            class="grid h-9 w-9 place-items-center rounded-xl bg-gradient-to-br from-cyan-500/15
                   to-cyan-700/5 p-1 shadow-[inset_0_0_0_1px_oklch(0.55_0.18_210/0.25)]"
        >
            <Logo size={28} glow />
        </div>
        <div>
            <p class="text-base font-semibold tracking-tight leading-none">Spouet</p>
            <p class="mt-0.5 text-[10px] uppercase tracking-wider text-neutral-500">v0.1</p>
        </div>
    </div>

    <nav class="flex-1 space-y-0.5 overflow-y-auto px-2">
        {#each items as it}
            {@const active = isActive(it.href)}
            <a
                href={it.href}
                onclick={() => isOpen = false}
                class="group relative flex items-center gap-3 rounded-lg px-3 py-2 text-sm
                       {active ? 'text-white' : 'text-neutral-400 hover:bg-white/5 hover:text-neutral-100'}"
            >
                {#if active}
                    <span
                        class="absolute inset-0 rounded-lg bg-gradient-to-r from-cyan-500/15
                               to-transparent ring-1 ring-cyan-500/20"
                    ></span>
                    <span
                        class="absolute left-0 top-1/2 h-5 w-0.5 -translate-y-1/2 rounded-r-full
                               bg-cyan-400"
                    ></span>
                {/if}
                <it.icon
                    size={16}
                    class="relative {active ? 'text-cyan-300' : 'text-neutral-500 group-hover:text-neutral-300'}"
                />
                <span class="relative">{it.label}</span>
            </a>
        {/each}

        <div class="mt-4 px-3">
            <div class="mb-2 flex items-center justify-between">
                <span class="text-[10px] font-medium uppercase tracking-wider text-neutral-500"
                    >Récent</span
                >
                <button
                    type="button"
                    onclick={newConversation}
                    class="rounded p-1 text-neutral-400 hover:bg-white/5 hover:text-white"
                    title="Nouvelle conversation"
                    aria-label="Nouvelle conversation"
                >
                    <Plus size={14} />
                </button>
            </div>
            <div class="relative mb-1.5">
                <Search size={11} class="absolute left-2 top-1/2 -translate-y-1/2 text-neutral-500" />
                <input
                    type="search"
                    placeholder="Rechercher…"
                    bind:value={searchQuery}
                    oninput={onSearchInput}
                    class="w-full rounded-md border border-[var(--color-border-subtle)] bg-[var(--color-bg-1)]
                           pl-6 pr-6 py-1 text-xs placeholder:text-neutral-600
                           focus:border-cyan-500/40 focus:outline-none"
                />
                {#if searchQuery}
                    <button
                        type="button"
                        onclick={clearSearch}
                        class="absolute right-1.5 top-1/2 -translate-y-1/2 text-neutral-500 hover:text-neutral-300"
                        aria-label="Effacer"
                    >
                        <X size={10} />
                    </button>
                {/if}
            </div>
            <div class="space-y-0.5">
                {#each convs.slice(0, 12) as c (c.id)}
                    {@const active = $page.url.pathname === `/chat/${c.id}`}
                    <div
                        in:fly={{ x: -8, duration: 180 }}
                        class="group/conv flex items-center gap-1 rounded-md
                               {active ? 'bg-white/5' : 'hover:bg-white/5'}"
                    >
                        <a
                            href="/chat/{c.id}"
                            class="flex min-w-0 flex-1 items-center gap-1.5 truncate px-2 py-1.5 text-xs
                                   {active ? 'text-white' : 'text-neutral-400 group-hover/conv:text-white'}"
                        >
                            {#if c.pinned}
                                <Pin size={10} class="shrink-0 text-cyan-400" />
                            {/if}
                            <span class="truncate">{c.title}</span>
                        </a>
                        <button
                            type="button"
                            onclick={(ev) => togglePin(ev, c)}
                            class="hidden rounded p-1 text-neutral-500
                                   hover:bg-white/10 hover:text-cyan-300 group-hover/conv:block"
                            title={c.pinned ? 'Désépingler' : 'Épingler'}
                            aria-label={c.pinned ? 'Désépingler la conversation' : 'Épingler la conversation'}
                        >
                            {#if c.pinned}
                                <PinOff size={11} />
                            {:else}
                                <Pin size={11} />
                            {/if}
                        </button>
                        <button
                            type="button"
                            onclick={(ev) => deleteConversation(ev, c)}
                            class="mr-1 hidden rounded p-1 text-neutral-500
                                   hover:bg-red-950 hover:text-red-300 group-hover/conv:block"
                            title="Supprimer"
                            aria-label="Supprimer la conversation"
                        >
                            <Trash2 size={11} />
                        </button>
                    </div>
                {/each}
            </div>
        </div>
    </nav>

    <div
        class="border-t border-[var(--color-border-subtle)] px-4 py-3 text-[10px] text-neutral-600"
    >
        <kbd class="rounded bg-neutral-800 px-1.5 py-0.5 font-mono text-[10px] text-neutral-300"
            >Ctrl</kbd
        >
        +
        <kbd class="rounded bg-neutral-800 px-1.5 py-0.5 font-mono text-[10px] text-neutral-300"
            >Espace</kbd
        > pour le compagnon
    </div>
</aside>
