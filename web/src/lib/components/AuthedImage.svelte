<script lang="ts">
    import { onDestroy } from 'svelte';
    import { authedImage } from '$lib/api';

    let {
        path,
        alt = '',
        class: klass = ''
    }: { path: string; alt?: string; class?: string } = $props();

    let src: string | null = $state(null);
    let objectUrl: string | null = null;
    let failed = $state(false);

    function revoke() {
        if (objectUrl) {
            URL.revokeObjectURL(objectUrl);
            objectUrl = null;
        }
    }

    // (Re)charge le blob quand le chemin change.
    $effect(() => {
        const p = path;
        revoke();
        src = null;
        failed = false;
        if (!p) return;
        authedImage(p)
            .then((u) => {
                objectUrl = u;
                src = u;
            })
            .catch(() => {
                failed = true;
            });
    });

    onDestroy(revoke);
</script>

{#if src}
    <img {src} {alt} class={klass} />
{:else if failed}
    <div class="grid h-full w-full place-items-center text-[10px] text-neutral-600">indisponible</div>
{:else}
    <div class="h-full w-full animate-pulse bg-neutral-800/50"></div>
{/if}
