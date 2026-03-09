<script lang="ts">
	import Message from './Message.svelte';
	import type { ChatMessage, ChatResult, Agent, Attachment, ResourceContents } from '$lib/types';
	import AgentHeader from '$lib/components/AgentHeader.svelte';

	interface Props {
		messages: ChatMessage[];
		onSend?: (message: string, attachments?: Attachment[]) => Promise<ChatResult | void>;
		isLoading?: boolean;
		agent?: Agent;
		onReadResource?: (uri: string) => Promise<{ contents: ResourceContents[] }>;
	}

	let { messages, onSend, isLoading = false, agent, onReadResource }: Props = $props();
	let messageGroups = $derived.by(() => {
		return messages.reduce((acc, message) => {
			if (message.role === 'user' || acc.length === 0) {
				acc.push([message]);
			} else {
				acc[acc.length - 1].push(message);
			}
			return acc;
		}, [] as ChatMessage[][]);
	});

	// Check if any messages have content (text items)
	let hasMessageContent = $derived(
		messageGroups[messageGroups.length - 1]?.some(
			(message) =>
				message.role === 'assistant' &&
				message.items &&
				message.items.some(
					(item) =>
						item.type === 'tool' ||
						(item.type === 'text' && item.text && item.text.trim().length > 0)
				)
		)
	);

	// Show loading indicator when loading and no content has been printed yet
	let showLoadingIndicator = $derived(isLoading && !hasMessageContent);
</script>

<div id="message-groups" class="flex flex-col space-y-4 pt-4">
	{#if messages.length === 0}
		<AgentHeader {agent} {onSend} />
	{:else}
		{@const lastIndex = messageGroups.length - 1}

		{#each messageGroups as messageGroup, i (messageGroup[0]?.id)}
			{@const isLast = i === lastIndex}

			<div
				id={`group-${messageGroup[0]?.id}`}
				class={{
					'min-h-[calc(100vh-2rem)]': isLast,
					contents: !isLast
				}}
				data-message-id={messageGroup[0]?.id}
			>
				{#each messageGroup as message, i (`${messageGroup[0]?.id}-${i}`)}
					<Message {message} {onSend} {onReadResource} />
				{/each}
				{#if isLast}
					{#if showLoadingIndicator}
						<div class="flex w-full items-start gap-3">
							<div class="flex min-w-0 flex-1 flex-col items-start">
								<div class="flex items-center justify-center p-8">
									<span class="loading loading-lg loading-spinner text-base-content/30"></span>
								</div>
							</div>
						</div>
					{/if}
					<div class="h-59"></div>
				{/if}
			</div>
		{/each}
	{/if}
</div>
