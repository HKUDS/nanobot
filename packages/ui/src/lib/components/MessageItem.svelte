<script lang="ts">
	import type { Attachment, ChatResult, ChatMessageItem, ResourceContents } from '$lib/types';
	import MessageItemText from './MessageItemText.svelte';
	import MessageItemImage from './MessageItemImage.svelte';
	import MessageItemAudio from './MessageItemAudio.svelte';
	import MessageItemResourceLink from './MessageItemResourceLink.svelte';
	import MessageItemResource from './MessageItemResource.svelte';
	import MessageItemReasoning from './MessageItemReasoning.svelte';
	import MessageItemTool from './MessageItemTool.svelte';

	interface Props {
		item: ChatMessageItem;
		role: 'user' | 'assistant';
		onSend?: (message: string, attachments?: Attachment[]) => Promise<ChatResult | void>;
		onReadResource?: (uri: string) => Promise<{ contents: ResourceContents[] }>;
	}

	let { item, role, onSend, onReadResource }: Props = $props();
</script>

{#if item.type === 'text'}
	<MessageItemText {item} {role} />
{:else if item.type === 'image'}
	<MessageItemImage {item} />
{:else if item.type === 'audio'}
	<MessageItemAudio {item} />
{:else if item.type === 'resource_link'}
	<MessageItemResourceLink {item} {onReadResource} />
{:else if item.type === 'resource'}
	<MessageItemResource {item} />
{:else if item.type === 'reasoning'}
	<MessageItemReasoning {item} />
{:else if item.type === 'tool'}
	<MessageItemTool {item} {onSend} />
{/if}
