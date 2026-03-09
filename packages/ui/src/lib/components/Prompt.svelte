<script lang="ts">
	import type { Attachment, ChatResult, Prompt, PromptArgument } from '$lib/types';

	interface Props {
		prompt: Prompt;
		onSend?: (message: string, attachments?: Attachment[]) => Promise<ChatResult | void>;
		onCancel?: () => void;
		open?: boolean;
	}

	let { prompt, onSend, onCancel, open: showDialog = false }: Props = $props();

	let formData = $state<{ [key: string]: string }>({});

	// Initialize form data when dialog opens
	$effect(() => {
		if (showDialog && prompt.arguments) {
			const newFormData: { [key: string]: string } = {};
			for (const arg of prompt.arguments) {
				newFormData[arg.name] = '';
			}
			formData = newFormData;
		} else if (showDialog) {
			executePrompt({});
		}
	});

	function handleClick() {
		if (prompt.arguments && prompt.arguments.length > 0) {
			showDialog = true;
		} else {
			executePrompt({});
		}
	}

	function handleKeyDown(event: KeyboardEvent) {
		if (event.key === 'Enter' || event.key === ' ') {
			event.preventDefault();
			handleClick();
		}
	}

	function executePrompt(args: { [key: string]: string }) {
		const promptMessage = JSON.stringify({
			type: 'prompt',
			payload: {
				promptName: prompt.name,
				params: args
			}
		});
		onSend?.(promptMessage);
		showDialog = false;
	}

	function handleAccept() {
		executePrompt(formData);
	}

	function handleCancel() {
		showDialog = false;
		onCancel?.();
	}

	function isRequired(arg: PromptArgument): boolean {
		return arg.required ?? false;
	}

	function validateForm(): boolean {
		if (!prompt.arguments) return true;

		for (const arg of prompt.arguments) {
			if (isRequired(arg) && (!formData[arg.name] || formData[arg.name].trim() === '')) {
				return false;
			}
		}
		return true;
	}
</script>

{#if !open}
	<div
		class="card cursor-pointer bg-base-100 shadow-md transition-shadow hover:shadow-lg"
		onclick={handleClick}
		onkeydown={handleKeyDown}
		role="button"
		tabindex="0"
	>
		<div class="card-body">
			<h3 class="card-title text-lg">
				{prompt.title || prompt.name}
			</h3>
			{#if prompt.description}
				<p class="text-sm text-base-content/70">{prompt.description}</p>
			{/if}
			{#if prompt.arguments && prompt.arguments.length > 0}
				<div class="badge badge-sm badge-primary">
					{prompt.arguments.length} argument{prompt.arguments.length === 1 ? '' : 's'}
				</div>
			{/if}
		</div>
	</div>
{/if}

{#if showDialog}
	<dialog class="modal-open modal">
		<div class="modal-box w-full max-w-2xl">
			<form method="dialog">
				<button
					class="btn absolute top-2 right-2 btn-circle btn-ghost btn-sm"
					onclick={handleCancel}
					>✕
				</button>
			</form>

			<h3 class="mb-4 text-lg font-bold">
				{prompt.title || prompt.name}
			</h3>

			{#if prompt.description}
				<div class="mb-6">
					<p class="text-base-content/80">{prompt.description}</p>
				</div>
			{/if}

			<form
				class="space-y-4"
				onsubmit={(e) => {
					e.preventDefault();
					handleAccept();
				}}
			>
				{#if prompt.arguments}
					{#each prompt.arguments as arg (arg.name)}
						<div class="form-control">
							<label class="label" for={arg.name}>
								<span class="label-text font-medium">
									{arg.title || arg.name}
									{#if isRequired(arg)}
										<span class="text-error">*</span>
									{/if}
								</span>
							</label>

							{#if arg.description}
								<div class="label">
									<span class="label-text-alt text-base-content/60">{arg.description}</span>
								</div>
							{/if}

							<input
								id={arg.name}
								type="text"
								bind:value={formData[arg.name]}
								class="input-bordered input w-full"
								required={isRequired(arg)}
								placeholder={arg.description || `Enter ${arg.name}`}
							/>
						</div>
					{/each}
				{/if}
			</form>

			<div class="modal-action">
				<button type="button" class="btn btn-ghost" onclick={handleCancel}>Cancel</button>
				<button
					type="button"
					class="btn btn-primary"
					disabled={!validateForm()}
					onclick={handleAccept}
				>
					Execute Prompt
				</button>
			</div>
		</div>

		<form method="dialog" class="modal-backdrop">
			<button onclick={handleCancel}>close</button>
		</form>
	</dialog>
{/if}
