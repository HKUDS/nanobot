<script lang="ts">
	import { renderMarkdown } from '$lib/markdown';
	import type { ChatMessageItemText } from '$lib/types';

	interface Props {
		item: ChatMessageItemText;
		role: 'user' | 'assistant';
	}

	let { item, role }: Props = $props();

	const renderedContent = $derived(role === 'assistant' ? renderMarkdown(item.text) : item.text);
</script>

<div
	class={[
		'prose w-full max-w-none rounded-box p-2 text-base-content',
		{
			'mb-3': role === 'assistant',
			'p-4': role === 'assistant',
			'bg-base-200': role === 'user',
			'whitespace-pre-wrap': role === 'user'
		}
	]}
>
	{@html renderedContent}
</div>
