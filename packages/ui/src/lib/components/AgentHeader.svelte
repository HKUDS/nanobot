<script lang="ts">
	import type { Agent, Attachment, ChatResult } from '$lib/types';
	import { onMount } from 'svelte';

	interface Props {
		onSend?: (message: string, attachments?: Attachment[]) => Promise<ChatResult | void>;
		agent?: Agent;
	}

	let { onSend, agent }: Props = $props();

	let imgRef = $state<HTMLImageElement>();

	onMount(() => {
		const target = document.documentElement;
		const observer = new MutationObserver((mutations) => {
			for (const mutation of mutations) {
				if (mutation.type === 'attributes' && mutation.attributeName === 'data-theme') {
					updateLogo();
				}
			}
		});

		observer.observe(target, {
			attributes: true,
			attributeFilter: ['data-theme']
		});
	});

	function updateLogo() {
		const isDark = document.documentElement.getAttribute('data-theme') === 'black';
		const url = isDark ? agent?.iconDark || agent?.icon : agent?.icon;
		if (url && imgRef) {
			imgRef.src = url;
		}
	}

	$effect(() => {
		if (imgRef) {
			updateLogo();
		}
	});
</script>

<div class="flex flex-col items-center p-8 pt-20">
	{#if agent?.name}
		<!-- Agent Icon -->
		{#if agent.icon}
			<div class="mb-6">
				<img bind:this={imgRef} src={agent.icon} alt={agent.name} class="h-16" />
			</div>
			<!-- Agent Description -->
			<div class="mb-8 text-center">
				<p class="max-w-md text-base-content/70">{agent.description || ''}</p>
			</div>
		{:else}
			<div class="mb-6">
				<div class="flex h-20 w-20 items-center justify-center rounded-full bg-primary/20">
					<svg
						class="h-10 w-10 text-primary"
						viewBox="0 0 20 20"
						xmlns="http://www.w3.org/2000/svg"
					>
						<path
							fill-rule="evenodd"
							d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-6-3a2 2 0 11-4 0 2 2 0 014 0zm-2 4a5 5 0 00-4.546 2.916A5.986 5.986 0 0010 16a5.986 5.986 0 004.546-2.084A5 5 0 0010 11z"
							clip-rule="evenodd"
						></path>
					</svg>
				</div>
			</div>

			<!-- Agent Description -->
			<div class="mb-8 text-center">
				<h2 class="mb-2 text-2xl font-semibold text-base-content">{agent.name}</h2>
				<p class="max-w-md text-base-content/70">{agent.description || ''}</p>
			</div>
		{/if}
	{/if}

	<!-- Starter Messages -->
	{#if agent}
		<div
			class={[
				'grid w-full max-w-2xl grid-cols-1 gap-3',
				{
					'grid-cols-2': agent.starterMessages?.length === 2,
					'grid-cols-3': agent.starterMessages?.length ?? 0 > 2
				}
			]}
		>
			{#each agent.starterMessages || [] as message (message)}
				<button
					class="card-compact card cursor-pointer bg-base-200 shadow-sm transition-colors hover:bg-base-300"
					onclick={() => onSend?.(message)}
				>
					<span class="card-body text-sm">{message}</span>
				</button>
			{/each}
		</div>
	{/if}
</div>
