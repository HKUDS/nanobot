<script lang="ts">
	import { Library } from '@lucide/svelte';
	import { getFileIcon } from '$lib/components/MessageAttachments.svelte';
	import type { Resource, ChatMessage } from '$lib/types';

	interface Props {
		disabled?: boolean;
		resources?: Resource[];
		selectedResources: Resource[];
		toggleResource: (resource: Resource) => void;
		messages?: ChatMessage[];
	}

	let {
		disabled = false,
		resources = [],
		messages = [],
		toggleResource,
		selectedResources
	}: Props = $props();

	// No need for dropdown state with DaisyUI dropdown

	// Extract embedded resources from messages and combine with resources prop
	let allResources = $derived.by(() => {
		const embeddedResources: Resource[] = [];

		for (const message of messages || []) {
			if (message.role !== 'assistant') continue;

			for (const item of message.items || []) {
				if (item.type !== 'tool') continue;

				for (const content of item.output?.content || []) {
					if (content.type === 'resource') {
						embeddedResources.push({
							uri: content.resource.uri,
							name:
								content.resource.name ||
								content.resource.uri.split('/').pop() ||
								content.resource.uri,
							description: content.resource.description,
							title: content.resource.title,
							mimeType: content.resource.mimeType,
							size: content.resource.size,
							annotations: content.resource.annotations,
							_meta: content.resource._meta
						});
					} else if (content.type === 'resource_link') {
						embeddedResources.push({
							uri: content.uri,
							name: content.name || content.uri.split('/').pop() || content.uri,
							title: content.name || content.uri.split('/').pop() || content.uri,
							description: content.description
						});
					}
				}
			}
		}

		// Remove duplicates based on URI and combine with existing resources
		return [...resources, ...embeddedResources].filter(
			(resource, index, self) =>
				index === self.findIndex((r) => r.uri === resource.uri) &&
				!resource.uri.startsWith('ui:') &&
				!resource.uri.startsWith('chat:')
		);
	});

	// No need for click handler with DaisyUI dropdown
</script>

<!-- Resources dropdown using DaisyUI -->
{#if allResources.length > 0}
	<div class="dropdown dropdown-end dropdown-top">
		<button
			class="btn h-9 w-9 rounded-full p-0 btn-ghost btn-sm"
			{disabled}
			aria-label="Select resources"
			onclick={(e) => e.preventDefault()}
		>
			<Library class="h-4 w-4" />
		</button>
		<ul
			class="dropdown-content menu z-50 max-h-[50vh] w-64 overflow-y-auto rounded-box border border-base-300 bg-base-100 p-2 shadow-lg"
		>
			<li class="menu-title">
				<span>Available Resources</span>
			</li>
			{#each allResources as resource (resource.uri)}
				<li>
					<button
						type="button"
						class="flex items-center space-x-2 {selectedResources.some(
							(r) => r.uri === resource.uri
						)
							? 'active'
							: ''}"
						onclick={() => toggleResource(resource)}
					>
						<span class="text-base">{getFileIcon(resource.mimeType)}</span>
						<span class="flex-1 overflow-hidden">
							<span class="block truncate text-sm font-medium">
								{resource.title || resource.name}
							</span>
							{#if resource.description}
								<span class="block truncate text-xs opacity-60">
									{resource.description}
								</span>
							{/if}
						</span>
						{#if selectedResources.some((r) => r.uri === resource.uri)}
							<span class="inline-block h-2 w-2 rounded-full bg-primary"></span>
						{/if}
					</button>
				</li>
			{/each}
		</ul>
	</div>
{/if}
