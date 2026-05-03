<script lang="ts">
    interface Props {
        online: boolean;
    }
    let { online }: Props = $props();
</script>

<span class="relative inline-flex h-2 w-2">
    {#if online}
        <span class="absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75 pulse-soft"></span>
        <span class="relative inline-flex h-2 w-2 rounded-full bg-emerald-400"></span>
    {:else}
        <span class="relative inline-flex h-2 w-2 rounded-full bg-neutral-600"></span>
    {/if}
</span>
