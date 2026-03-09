<script lang="ts">
	import { slide } from 'svelte/transition';
	import { X, CheckCircle, AlertCircle, AlertTriangle, Info, Copy } from '@lucide/svelte';
	import type { Notification } from '$lib/types';
	import { getNotificationContext } from '$lib/context/notifications.svelte';

	let copiedTooltipId = $state<string | null>(null);
	const notifications = getNotificationContext();

	function getNotificationClasses(type: Notification['type']): string {
		const baseClasses = 'alert shadow-lg border';

		switch (type) {
			case 'success':
				return `${baseClasses} alert-success`;
			case 'error':
				return `${baseClasses} alert-error`;
			case 'warning':
				return `${baseClasses} alert-warning`;
			case 'info':
				return `${baseClasses} alert-info`;
			default:
				return `${baseClasses}`;
		}
	}

	function handleClose(id: string) {
		notifications.remove(id);
	}

	async function copyNotificationContent(notification: Notification) {
		const content = notification.message
			? `${notification.title}\n${notification.message}`
			: notification.title;
		await navigator.clipboard.writeText(content);
		copiedTooltipId = notification.id;
		setTimeout(() => {
			copiedTooltipId = null;
		}, 2000);
	}
</script>

<!-- Notification container -->
<div class="fixed right-4 bottom-4 z-50 flex w-80 flex-col gap-3">
	{#each notifications.notifications as notification (notification.id)}
		<div
			class="{getNotificationClasses(notification.type)} group relative"
			in:slide={{ duration: 300 }}
			out:slide={{ duration: 200 }}
		>
			<div class="flex items-start gap-3">
				<!-- Notification icon -->
				<div class="flex-shrink-0">
					{#if notification.type === 'success'}
						<CheckCircle class="h-5 w-5" />
					{:else if notification.type === 'error'}
						<AlertCircle class="h-5 w-5" />
					{:else if notification.type === 'warning'}
						<AlertTriangle class="h-5 w-5" />
					{:else}
						<Info class="h-5 w-5" />
					{/if}
				</div>

				<!-- Notification content -->
				<div class="min-w-0 flex-1">
					<div class="text-sm font-medium break-all">
						{notification.title}
					</div>
					{#if notification.message}
						<div class="mt-1 text-xs break-all opacity-80">
							{notification.message}
						</div>
					{/if}
				</div>
			</div>

			<!-- Floating buttons -->
			<div
				class="absolute top-1 right-1 flex gap-1 rounded p-1 opacity-0 backdrop-blur-sm transition-opacity group-hover:opacity-100"
			>
				<!-- Copy button -->
				<button
					type="button"
					class="btn btn-ghost btn-xs"
					onclick={() => copyNotificationContent(notification)}
					title="Copy notification"
				>
					<Copy class="h-3 w-3" />
				</button>

				<!-- Close button -->
				<button
					class="btn btn-ghost btn-xs"
					onclick={() => handleClose(notification.id)}
					aria-label="Close notification"
				>
					<X class="h-3 w-3" />
				</button>
			</div>

			<!-- Copy tooltip -->
			{#if copiedTooltipId === notification.id}
				<div
					class="absolute -top-8 right-1 rounded bg-success px-2 py-1 text-xs text-success-content opacity-100 shadow-lg transition-opacity duration-500"
				>
					Copied!
				</div>
			{/if}
		</div>

		<!-- Progress bar for auto-dismiss notifications -->
		{#if notification.autoClose && notification.duration && notification.duration > 0}
			<div class="mt-2 h-1 overflow-hidden rounded bg-black/10">
				<div
					class="h-full animate-pulse bg-current opacity-60"
					style="animation: shrink {notification.duration}ms linear forwards;"
				></div>
			</div>
		{/if}
	{/each}
</div>

<style>
	@keyframes shrink {
		from {
			width: 100%;
		}
		to {
			width: 0%;
		}
	}
</style>
