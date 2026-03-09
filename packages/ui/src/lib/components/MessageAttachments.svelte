<script module lang="ts">
	export function getFileIcon(type?: string) {
		if (type?.startsWith('image/')) {
			return '🖼️';
		} else if (type === 'application/pdf') {
			return '📄';
		} else if (type?.includes('text/') || type?.includes('json')) {
			return '📝';
		} else if (type?.includes('spreadsheet') || type?.includes('csv')) {
			return '📊';
		} else if (type?.includes('document')) {
			return '📋';
		}
		return '📎';
	}
</script>

<script lang="ts">
	import type { UploadingFile } from '$lib/types.js';
	import type { UploadedFile } from '$lib/types.js';
	import type { Resource } from '$lib/types.js';
	import { X } from '@lucide/svelte';

	interface Props {
		cancelUpload?: (fileId: string) => void;
		uploadingFiles?: UploadingFile[];
		uploadedFiles?: UploadedFile[];
		selectedResources?: Resource[];
		removeSelectedResource?: (resource: Resource) => void;
	}

	let {
		uploadingFiles = [],
		uploadedFiles = [],
		cancelUpload,
		removeSelectedResource,
		selectedResources = []
	}: Props = $props();
</script>

{#snippet item<T>(
	label: string,
	type: string,
	loading: boolean,
	name: string,
	id: T,
	onClick?: (id: T) => void
)}
	<div class="flex items-center gap-2 rounded-xl bg-base-200 px-3 py-2 text-sm">
		{#if loading}
			<span class="loading loading-xs loading-spinner"></span>
		{:else}
			<span>{getFileIcon(type)}</span>
		{/if}
		<span class="max-w-32 truncate">{name}</span>
		<button
			type="button"
			onclick={() => onClick?.(id)}
			class="btn h-5 w-5 rounded-full p-0 btn-ghost btn-xs"
			aria-label={label}
		>
			<X class="h-3 w-3" />
		</button>
	</div>
{/snippet}

{#if uploadedFiles.length > 0 || uploadingFiles.length > 0 || selectedResources.length > 0}
	<div class="flex flex-wrap gap-2">
		<!-- Uploading files with spinner -->
		{#each uploadingFiles as uploadingFile (uploadingFile.id)}
			{@render item(
				'Cancel upload',
				'',
				true,
				uploadingFile.file.name,
				uploadingFile.id,
				cancelUpload
			)}
		{/each}
		<!-- Uploaded files -->
		{#each uploadedFiles as uploadedFile (uploadedFile.id)}
			{@render item(
				'Remove file',
				uploadedFile.file.type,
				false,
				uploadedFile.file.name,
				uploadedFile.id,
				cancelUpload
			)}
		{/each}
		<!-- Selected resources -->
		{#each selectedResources as resource (resource.uri)}
			{@render item(
				'Remove resource',
				resource.mimeType || '',
				false,
				resource.title || resource.name,
				resource,
				removeSelectedResource
			)}
		{/each}
	</div>
{/if}
