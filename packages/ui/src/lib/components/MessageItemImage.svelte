<script lang="ts">
	import type { ChatMessageItemImage } from '$lib/types';

	interface Props {
		item: ChatMessageItemImage;
	}

	let { item }: Props = $props();
</script>

<div class="mb-3 rounded-lg bg-base-200 p-3">
	<img src="data:{item.mimeType};base64,{item.data}" alt="" class="max-w-full rounded" />
</div>
