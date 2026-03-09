<script lang="ts">
	import { AlertTriangle } from '@lucide/svelte';
	import { getFileIcon } from '$lib/components/MessageAttachments.svelte';
	import type { ChatMessageItemResource } from '$lib/types';

	interface Props {
		item: ChatMessageItemResource;
	}

	let { item }: Props = $props();

	let isError = $derived(item.resource.mimeType === 'application/vnd.nanobot.error+json');
	let modal = $state<HTMLDialogElement>();

	function openModal() {
		modal?.showModal();
	}

	function isTextType(mimeType: string): boolean {
		return (
			mimeType.startsWith('text/') ||
			mimeType.includes('json') ||
			mimeType.includes('xml') ||
			mimeType === 'application/javascript' ||
			mimeType === 'application/typescript'
		);
	}

	function isPdfType(mimeType: string): boolean {
		return mimeType === 'application/pdf';
	}

	function getResourceDisplayName(): string {
		// Use title or name if available, otherwise generate from MIME type
		if (item.resource.title) return item.resource.title;
		if (item.resource.name) return item.resource.name;

		// Generate friendly name from MIME type
		const mimeType = item.resource.mimeType;
		if (mimeType === 'application/json') return 'JSON Data';
		if (mimeType === 'application/xml') return 'XML Document';
		if (mimeType === 'application/pdf') return 'PDF Document';
		if (mimeType.startsWith('text/')) return 'Text Document';
		if (mimeType.startsWith('image/')) return 'Image';
		if (mimeType.includes('json')) return 'JSON Resource';
		if (mimeType.includes('html')) return 'HTML Document';
		if (mimeType.includes('csv')) return 'CSV Data';
		if (mimeType.includes('markdown')) return 'Markdown';

		// Fallback to MIME type
		return mimeType;
	}

	function formatFileSize(bytes?: number): string {
		if (!bytes) return '';
		if (bytes < 1024) return `${bytes} B`;
		if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
		return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
	}

	function getDecodedText(): string {
		if (!item.resource.blob) return '';
		try {
			// Unicode-safe base64 decoding
			const binaryString = atob(item.resource.blob);
			const bytes = Uint8Array.from(binaryString, (c) => c.charCodeAt(0));
			const str = new TextDecoder('utf-8').decode(bytes);
			try {
				return JSON.stringify(JSON.parse(str), null, 2);
			} catch {
				return str;
			}
		} catch {
			return 'Error decoding content';
		}
	}
</script>

{#if isError}
	<div class="mb-3 rounded-lg border border-error/20 bg-error/10 p-3">
		<div class="mb-2 flex items-center gap-2 text-sm">
			<AlertTriangle class="h-4 w-4 text-error" />
			<span class="font-medium text-error">Error</span>
		</div>
		{#if item.resource.text}
			<pre
				class="mt-2 rounded bg-base-100 p-2 text-xs break-all whitespace-pre-wrap text-error">{item
					.resource.text}</pre>
		{/if}
	</div>
{:else}
	<!-- Enhanced resource card -->
	<div class="card-compact card max-w-sm border border-base-200/50 shadow-md">
		<div class="card-body">
			<div class="flex items-start gap-3">
				<!-- Large icon -->
				<div class="flex-shrink-0">
					<div class="flex h-12 w-12 items-center justify-center rounded-xl bg-primary/10 text-2xl">
						{getFileIcon(item.resource.mimeType)}
					</div>
				</div>

				<!-- Content -->
				<div class="min-w-0 flex-1">
					<h4 class="truncate text-sm font-semibold text-base-content">
						{getResourceDisplayName()}
					</h4>

					<!-- Description if available -->
					{#if item.resource.description}
						<p
							class="mt-1 text-xs text-base-content/60"
							style="display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden;"
						>
							{item.resource.description}
						</p>
					{/if}

					<!-- Metadata row -->
					<div class="mt-2 flex items-center gap-2">
						<span class="badge badge-ghost badge-xs">{item.resource.mimeType}</span>
						{#if item.resource.size}
							<span class="text-xs text-base-content/50">
								{formatFileSize(item.resource.size)}
							</span>
						{/if}
					</div>
				</div>
			</div>

			<!-- Card actions -->
			<div class="mt-3 card-actions justify-end">
				<button type="button" class="btn btn-sm btn-primary" onclick={openModal}>
					View Content
				</button>
			</div>
		</div>
	</div>

	<!-- DaisyUI Dialog Modal -->
	<dialog bind:this={modal} class="modal modal-bottom sm:modal-middle">
		<div class="modal-box max-h-[80vh] max-w-4xl overflow-hidden">
			<div class="mb-4 flex items-center justify-between">
				<h3 class="flex items-center gap-3 text-lg font-bold">
					<div class="flex h-8 w-8 items-center justify-center rounded-lg bg-primary/10">
						<span class="text-xl">{getFileIcon(item.resource.mimeType)}</span>
					</div>
					<div>
						<div class="text-base-content">{getResourceDisplayName()}</div>
						{#if item.resource.description}
							<div class="text-sm font-normal text-base-content/60">
								{item.resource.description}
							</div>
						{/if}
					</div>
				</h3>
			</div>

			<div class="mb-4 flex items-center gap-2">
				<span class="badge badge-sm badge-primary">{item.resource.mimeType}</span>
				{#if item.resource.size}
					<span class="badge badge-ghost badge-sm">{formatFileSize(item.resource.size)}</span>
				{/if}
				{#if item.resource.annotations?.lastModified}
					<span class="text-xs text-base-content/50">
						Modified: {new Date(item.resource.annotations.lastModified).toLocaleDateString()}
					</span>
				{/if}
			</div>

			<div class="max-h-96 overflow-auto">
				{#if isTextType(item.resource.mimeType) && item.resource.blob}
					<div class="mockup-code">
						<pre><code>{getDecodedText()}</code></pre>
					</div>
				{:else if isPdfType(item.resource.mimeType) && item.resource.blob}
					<div class="w-full">
						<iframe
							src="data:application/pdf;base64,{item.resource.blob}"
							class="h-96 w-full rounded border border-base-300"
							title="PDF Viewer"
						></iframe>
					</div>
				{:else}
					<div class="py-8 text-center">
						<div class="mb-4 text-6xl">{getFileIcon(item.resource.mimeType)}</div>
						<p class="text-base-content/60">Preview not available for this resource type</p>
						{#if item.resource.blob}
							<p class="mt-2 text-sm text-base-content/40">
								Resource data is available but cannot be previewed
							</p>
						{:else}
							<p class="mt-2 text-sm text-base-content/40">No resource data available</p>
						{/if}
					</div>
				{/if}
			</div>

			<div class="modal-action">
				<form method="dialog">
					<button class="btn">Close</button>
				</form>
			</div>
		</div>
	</dialog>
{/if}
