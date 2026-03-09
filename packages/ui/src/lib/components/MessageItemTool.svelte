<script lang="ts">
	import { Eye, Settings } from '@lucide/svelte';
	import { renderMarkdown } from '$lib/markdown';
	import type { Attachment, ChatResult, ChatMessageItemToolCall, ToolOutputItem } from '$lib/types';
	import '@mcp-ui/client/ui-resource-renderer.wc.js';
	import MessageItemUI from '$lib/components/MessageItemUI.svelte';
	import { isUIResource } from '@mcp-ui/client';

	interface Props {
		item: ChatMessageItemToolCall;
		onSend?: (message: string, attachments?: Attachment[]) => Promise<ChatResult | void>;
	}

	let { item, onSend }: Props = $props();
	let imagePreviewModal = $state<HTMLDialogElement>();
	let selectedImagePreview = $state<{
		data: string;
		mimeType: string;
		index: number;
	} | null>(null);
	let singleUIResource = $derived(
		item.output?.content &&
			item.output?.content?.filter((i) => {
				return isUIResource(i) && !i.resource?._meta?.['ai.nanobo.meta/workspace'];
			}).length === 1
	);

	function parseToolInput(input: string) {
		try {
			const parsed = JSON.parse(input);
			if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
				return { success: true, data: parsed };
			}
		} catch {
			// JSON parsing failed, fall back to string display
		}
		return { success: false, data: input };
	}

	function getStyle(
		item: ToolOutputItem,
		singleUIResource: boolean = false
	): Record<string, string> {
		if (singleUIResource) {
			return {};
		}
		if (isUIResource(item) && item.resource._meta?.['mcpui.dev/ui-preferred-frame-size']) {
			const coords = item.resource._meta['mcpui.dev/ui-preferred-frame-size'];
			if (Array.isArray(coords) && coords[0] && coords[1]) {
				return {
					width: `${coords[0]}`,
					height: `${coords[1]}`
				};
			} else if (
				coords &&
				typeof coords === 'object' &&
				'height' in coords &&
				'width' in coords
			) {
				return {
					width: `${coords.width}`,
					height: `${coords.height}`
				};
			}
		}
		return {
			width: '300px',
			height: '400px'
		};
	}

	function parseToolOutput(output: string) {
		try {
			const parsed = JSON.parse(output);
			const formattedJson = JSON.stringify(parsed, null, 2);
			const highlightedJson = renderMarkdown('```json\n' + formattedJson + '\n```');
			return { success: true, data: highlightedJson };
		} catch {
			// JSON parsing failed, fall back to string display
		}
		return { success: false, data: output };
	}

	function openImagePreview(item: ToolOutputItem, index: number) {
		if (item.type !== 'image') {
			return;
		}

		selectedImagePreview = {
			data: item.data,
			mimeType: item.mimeType || 'image/png',
			index,
		};
		imagePreviewModal?.showModal();
	}
</script>

<div
	class="text collapse mt-3 mb-2 w-full border border-base-100 bg-base-100 hover:collapse-arrow hover:border-base-300"
>
	<input type="checkbox" />
	<div class="collapse-title">
		<div class="flex items-center gap-2">
			{#if item.output}
				<Settings class="h-4 w-4 text-primary/60" />
			{:else}
				<span class="loading loading-xs loading-spinner"></span>
			{/if}
			<span class="text-sm font-medium text-primary/60">Tool call: {item.name}</span>
		</div>
	</div>
	<div class="collapse-content">
		<div class="space-y-3 pt-2">
			{#if item.arguments}
				<div class="grid">
					<div class="mb-1 text-xs font-medium text-base-content/70">Input:</div>
					{#if parseToolInput(item.arguments).success}
						<div class="overflow-x-auto rounded bg-base-200 p-3">
							<table class="table w-full table-zebra table-xs">
								<thead>
									<tr>
										<th class="text-xs">Key</th>
										<th class="text-xs">Value</th>
									</tr>
								</thead>
								<tbody>
									{#each Object.entries(parseToolInput(item.arguments).data) as [key, value] (key)}
										<tr>
											<td class="font-mono text-xs">{key}</td>
											<td class="font-mono text-xs break-all">
												{typeof value === 'object' ? JSON.stringify(value) : String(value)}
											</td>
										</tr>
									{/each}
									{#if Object.keys(parseToolInput(item.arguments).data).length === 0}
										<tr>
											<td class="font-mono text-xs">No arguments</td>
										</tr>
									{/if}
								</tbody>
							</table>
						</div>
					{:else}
						<div class="overflow-x-auto rounded bg-base-200 p-3 font-mono text-sm">
							{item.arguments}
						</div>
					{/if}
				</div>
			{/if}
			{#if item.output}
				<div class="flex flex-col">
					<div class="mb-1 text-xs font-medium text-base-content/70">Output:</div>
					{#if item.output.isError}
						<div class="alert alert-error">
							<span>Tool execution failed</span>
						</div>
					{/if}
					{#if item.output.structuredContent}
						<div
							class="prose overflow-x-auto rounded border border-success/20 bg-success/10 p-3 prose-invert"
						>
							{@html parseToolOutput(JSON.stringify(item.output.structuredContent)).data}
						</div>
					{/if}
					{#if item.output.content}
						<!-- Render tool output content items -->
						{#each item.output.content as contentItem, i (i)}
							<div
								class="prose overflow-x-auto rounded border border-success/20 bg-success/10 p-3 prose-invert"
							>
								{#if contentItem.type === 'image' && contentItem.data}
									<div class="mb-2 flex justify-end">
										<button
											type="button"
											class="btn btn-xs btn-ghost"
											onclick={() => openImagePreview(contentItem, i)}
										>
											<Eye class="h-3.5 w-3.5" />
											Preview
										</button>
									</div>
								{/if}
								{#if contentItem.type === 'text' && 'text' in contentItem && parseToolOutput(contentItem.text).success}
									<!-- JSON Syntax Highlighted Display -->
									{@html parseToolOutput(contentItem.text).data}
								{:else if contentItem.type === 'text' && 'text' in contentItem && contentItem.text}
									{@html renderMarkdown(contentItem.text)}
								{:else}
									{@html parseToolOutput(JSON.stringify(contentItem)).data}
								{/if}
							</div>
						{/each}
					{/if}
				</div>
			{:else}
				<div class="flex items-center gap-2 text-xs text-base-content/50 italic">
					<span class="loading loading-xs loading-spinner"></span>
					Running...
				</div>
			{/if}
		</div>
	</div>
</div>

<div class="flex w-full flex-wrap items-start justify-start gap-2 p-2">
	{#if item.output && item.output.content}
		{#each item.output.content as contentItem, i (i)}
			{#if contentItem.type === 'resource' && contentItem.resource && isUIResource(contentItem) && !contentItem.resource._meta?.['ai.nanobot.meta/workspace']}
				<MessageItemUI
					item={contentItem}
					{onSend}
					style={getStyle(contentItem, singleUIResource)}
				/>
			{/if}
			{#if contentItem.type === 'image' && !contentItem._meta?.['ai.nanobot.meta/skip-truncation']}
				<img
					src="data:{contentItem.mimeType};base64,{contentItem.data}"
					alt="Tool output"
					class="max-w-full rounded"
				/>
			{/if}
		{/each}
	{/if}
</div>

<dialog bind:this={imagePreviewModal} class="modal modal-bottom sm:modal-middle">
	<div class="modal-box max-h-[85vh] max-w-5xl overflow-auto">
		<div class="mb-4 flex items-center justify-between">
			<h3 class="text-lg font-semibold">
				{#if selectedImagePreview}
					Tool output image {selectedImagePreview.index + 1}
				{:else}
					Tool output image
				{/if}
			</h3>
		</div>
		{#if selectedImagePreview}
			<img
				src="data:{selectedImagePreview.mimeType};base64,{selectedImagePreview.data}"
				alt="Tool output preview"
				class="h-auto max-w-full rounded"
			/>
		{/if}
		<div class="modal-action">
			<form method="dialog">
				<button class="btn">Close</button>
			</form>
		</div>
	</div>
</dialog>
