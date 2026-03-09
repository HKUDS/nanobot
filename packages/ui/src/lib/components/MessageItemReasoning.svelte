<script lang="ts">
	import { Lightbulb } from '@lucide/svelte';
	import type { ChatMessageItemReasoning } from '$lib/types';

	interface Props {
		item: ChatMessageItemReasoning;
	}

	let { item }: Props = $props();
</script>

<div class="mb-3 rounded-lg border-l-4 border-neutral bg-neutral/20 p-3">
	<div class="mb-2 flex items-center gap-2 text-sm">
		<Lightbulb class="h-4 w-4 text-neutral" />
		<span class="font-medium text-neutral">Reasoning</span>
	</div>
	{#if item.summary}
		{#each item.summary as summaryItem, index (index)}
			<p class="text-sm opacity-80">{summaryItem.text}</p>
		{/each}
	{/if}
</div>
