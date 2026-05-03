<script lang="ts">
    interface Props {
        h?: string;
        w?: string;
        rounded?: string;
    }
    let { h = 'h-4', w = 'w-full', rounded = 'rounded-md' }: Props = $props();
</script>

<div class="skeleton {h} {w} {rounded}"></div>
