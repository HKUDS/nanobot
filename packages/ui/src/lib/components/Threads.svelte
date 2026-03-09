<script lang="ts">
	import { goto } from '$app/navigation';
	import { MoreVertical, Edit, Trash2, X, Check } from '@lucide/svelte';
	import type { Chat } from '$lib/types';
	import { resolve } from '$app/paths';

	interface Props {
		threads: Chat[];
		onRename: (threadId: string, newTitle: string) => void;
		onDelete: (threadId: string) => void;
		isLoading?: boolean;
		onThreadClick?: () => void;
	}

	let { threads, onRename, onDelete, isLoading = false, onThreadClick }: Props = $props();

	let editingThreadId = $state<string | null>(null);
	let editTitle = $state('');

	function navigateToThread(threadId: string) {
		goto(resolve(`/c/${threadId}`));
		onThreadClick?.();
	}

	function formatTime(timestamp: string): string {
		const now = new Date();
		const diff = now.getTime() - new Date(timestamp).getTime();
		const minutes = Math.floor(diff / (1000 * 60));
		const hours = Math.floor(diff / (1000 * 60 * 60));
		const days = Math.floor(diff / (1000 * 60 * 60 * 24));

		if (minutes < 1) return 'now';
		if (minutes < 60) return `${minutes}m`;
		if (hours < 24) return `${hours}h`;
		return `${days}d`;
	}

	function startRename(threadId: string, currentTitle: string) {
		editingThreadId = threadId;
		editTitle = currentTitle || '';
	}

	function saveRename() {
		if (editingThreadId && editTitle.trim()) {
			onRename(editingThreadId, editTitle.trim());
			editingThreadId = null;
			editTitle = '';
		}
	}

	function cancelRename() {
		editingThreadId = null;
		editTitle = '';
	}

	function handleDelete(threadId: string) {
		onDelete(threadId);
	}

	function handleKeydown(e: KeyboardEvent) {
		if (e.key === 'Enter') {
			saveRename();
		} else if (e.key === 'Escape') {
			cancelRename();
		}
	}
</script>

<div class="flex h-full flex-col">
	<!-- Header -->
	<div class="flex-shrink-0 p-2">
		<h2 class="font-semibold text-base-content/60">Conversations</h2>
	</div>

	<!-- Thread list -->
	<div class="flex-1 overflow-y-auto">
		{#if isLoading}
			<!-- Skeleton UI when loading -->
			{#each Array(5).fill(null) as _, index (index)}
				<div class="flex items-center border-b border-base-200 p-3">
					<div class="flex-1">
						<div class="flex items-center justify-between gap-2">
							<div class="flex min-w-0 flex-1 items-center gap-2">
								<div class="h-5 w-48 skeleton"></div>
							</div>
							<div class="h-4 w-8 skeleton"></div>
						</div>
					</div>
					<div class="w-8"></div>
					<!-- Space for the menu button -->
				</div>
			{/each}
		{:else}
			{#each threads as thread (thread.id)}
				<div class="group flex items-center border-b border-base-200 hover:bg-base-100">
					<!-- Thread title area (clickable) -->
					<button
						class="flex-1 truncate p-3 text-left transition-colors focus:outline-none"
						onclick={() => navigateToThread(thread.id)}
					>
						<div class="flex items-center justify-between gap-2">
							<div class="flex min-w-0 flex-1 items-center gap-2">
								{#if editingThreadId === thread.id}
									<input
										type="text"
										bind:value={editTitle}
										onkeydown={handleKeydown}
										class="input input-sm min-w-0 flex-1"
										onclick={(e) => e.stopPropagation()}
										onfocus={(e) => (e.target as HTMLInputElement).select()}
									/>
								{:else}
									<h3 class="truncate text-sm font-medium">{thread.title || 'Untitled'}</h3>
								{/if}
							</div>
							{#if editingThreadId !== thread.id}
								<span class="flex-shrink-0 text-xs text-base-content/50">
									{formatTime(thread.created)}
								</span>
							{/if}
						</div>
					</button>

					<!-- Save/Cancel buttons for editing -->
					{#if editingThreadId === thread.id}
						<div class="flex items-center gap-1 px-2">
							<button
								class="btn btn-ghost btn-xs"
								onclick={cancelRename}
								aria-label="Cancel editing"
							>
								<X class="h-3 w-3" />
							</button>
							<button
								class="btn text-success btn-ghost btn-xs hover:bg-success/20"
								onclick={saveRename}
								aria-label="Save changes"
							>
								<Check class="h-3 w-3" />
							</button>
						</div>
					{/if}

					{#if editingThreadId !== thread.id}
						<!-- Dropdown menu - only show on hover -->
						<div class="dropdown dropdown-end opacity-0 transition-opacity group-hover:opacity-100">
							<div tabindex="0" role="button" class="btn btn-square btn-ghost btn-sm">
								<MoreVertical class="h-4 w-4" />
							</div>
							<ul
								class="dropdown-content menu z-[1] w-32 rounded-box border bg-base-100 p-2 shadow"
							>
								<li>
									<button onclick={() => startRename(thread.id, thread.title)} class="text-sm">
										<Edit class="h-4 w-4" />
										Rename
									</button>
								</li>
								<li>
									<button onclick={() => handleDelete(thread.id)} class="text-sm text-error">
										<Trash2 class="h-4 w-4" />
										Delete
									</button>
								</li>
							</ul>
						</div>
					{/if}
				</div>
			{/each}
		{/if}
	</div>
</div>
