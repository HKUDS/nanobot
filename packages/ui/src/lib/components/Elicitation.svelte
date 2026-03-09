<script lang="ts">
	interface Props {
		elicitation: Elicitation;
		open?: boolean;
		onresult?: (result: ElicitationResult) => void;
	}

	import type { Elicitation, ElicitationResult, PrimitiveSchemaDefinition } from '$lib/types';
	import { Copy, ChevronLeft, ChevronRight, SkipForward, Pencil } from '@lucide/svelte';
	import { SvelteSet, SvelteMap } from 'svelte/reactivity';

	const stepColors = [
		{ bg: 'bg-primary', text: 'text-primary-content', ring: 'ring-primary/30' },
		{ bg: 'bg-secondary', text: 'text-secondary-content', ring: 'ring-secondary/30' },
		{ bg: 'bg-accent', text: 'text-accent-content', ring: 'ring-accent/30' },
		{ bg: 'bg-info', text: 'text-info-content', ring: 'ring-info/30' }
	];

	let { elicitation, open = false, onresult }: Props = $props();

	let formData = $state<{ [key: string]: string | number | boolean }>({});
	let showCopiedTooltip = $state(false);

	// Question-specific types
	interface QuestionOptionData {
		label: string;
		description?: string;
	}
	interface QuestionData {
		question: string;
		header?: string;
		multiple?: boolean;
		options: QuestionOptionData[];
	}

	// Question-specific state
	let currentStep = $state(0);
	let reviewMode = $state(false);
	let selectedOptions = new SvelteMap<number, SvelteSet<string>>();
	let customAnswers = new SvelteMap<number, string>();
	let showCustomInput = new SvelteMap<number, boolean>();

	// Initialize form data with defaults
	$effect(() => {
		const newFormData: { [key: string]: string | number | boolean } = {};

		for (const [key, schema] of Object.entries(elicitation.requestedSchema.properties)) {
			if (schema.type === 'boolean' && schema.default !== undefined) {
				newFormData[key] = schema.default;
			} else if (
				schema.type === 'string' ||
				schema.type === 'number' ||
				schema.type === 'integer'
			) {
				newFormData[key] = schema.type === 'string' ? '' : 0;
			} else if ('enum' in schema && schema.enum) {
				newFormData[key] = (schema.enum as string[])[0] || '';
			}
		}

		formData = newFormData;
	});

	// Reset question state when elicitation changes
	$effect(() => {
		if (isQuestionElicitation()) {
			currentStep = 0;
			reviewMode = false;
			selectedOptions.clear();
			customAnswers.clear();
			showCustomInput.clear();
		}
	});

	function handleAccept() {
		onresult?.({
			action: 'accept',
			content: { ...formData }
		});
	}

	function handleDecline() {
		onresult?.({
			action: 'decline'
		});
	}

	function handleCancel() {
		onresult?.({
			action: 'cancel'
		});
	}

	function isRequired(key: string): boolean {
		return elicitation.requestedSchema.required?.includes(key) ?? false;
	}

	function getFieldTitle(key: string, schema: PrimitiveSchemaDefinition): string {
		return schema.title || key;
	}

	function validateForm(): boolean {
		if (!elicitation.requestedSchema.required) return true;

		for (const requiredField of elicitation.requestedSchema.required) {
			const value = formData[requiredField];
			if (value === undefined || value === '' || value === null) {
				return false;
			}
		}
		return true;
	}

	function isOAuthElicitation(): boolean {
		return Boolean(elicitation._meta?.['ai.nanobot.meta/oauth-url']);
	}

	function getOAuthUrl(): string {
		return elicitation._meta?.['ai.nanobot.meta/oauth-url'] as string;
	}

	function getServerName(): string {
		return (elicitation._meta?.['ai.nanobot.meta/server-name'] as string) || 'MCP Server';
	}

	function openOAuthLink() {
		const url = getOAuthUrl();
		window.open(url, '_blank');
		handleAccept();
	}

	async function copyToClipboard() {
		const url = getOAuthUrl();
		await navigator.clipboard.writeText(url);
		showCopiedTooltip = true;
		setTimeout(() => {
			showCopiedTooltip = false;
		}, 2000);
	}

	// Question elicitation functions
	function isQuestionElicitation(): boolean {
		return Boolean(elicitation._meta?.['ai.nanobot.meta/question']);
	}

	const questions: QuestionData[] = $derived.by(() => {
		const raw = elicitation._meta?.['ai.nanobot.meta/question'];
		if (!raw) return [];

		if (typeof raw === 'string') {
			try {
				const parsed = JSON.parse(raw);
				if (Array.isArray(parsed)) return parsed as QuestionData[];
				if (parsed && typeof parsed === 'object') return [parsed as QuestionData];
				return [];
			} catch {
				return [];
			}
		}

		if (Array.isArray(raw)) return raw as QuestionData[];
		if (raw && typeof raw === 'object') return [raw as QuestionData];
		return [];
	});

	function toggleOption(qIndex: number, label: string) {
		let current = selectedOptions.get(qIndex);
		if (!current) {
			current = new SvelteSet();
			selectedOptions.set(qIndex, current);
		}

		if (questions[qIndex].multiple) {
			if (current.has(label)) current.delete(label);
			else current.add(label);
		} else {
			current.clear();
			current.add(label);
			showCustomInput.set(qIndex, false);
			customAnswers.set(qIndex, '');
		}
	}

	function toggleCustomInput(qIndex: number) {
		const current = showCustomInput.get(qIndex) ?? false;
		showCustomInput.set(qIndex, !current);
		if (current) {
			customAnswers.set(qIndex, '');
		} else if (!questions[qIndex].multiple) {
			selectedOptions.set(qIndex, new SvelteSet());
		}
	}

	function updateCustomAnswer(qIndex: number, value: string) {
		customAnswers.set(qIndex, value);
	}

	function hasAnswer(qIndex: number): boolean {
		const selected = selectedOptions.get(qIndex);
		const custom = customAnswers.get(qIndex)?.trim();
		return (selected !== undefined && selected.size > 0) || !!custom;
	}

	function getAnswerSummary(qIndex: number): string {
		const selected = Array.from(selectedOptions.get(qIndex) ?? []);
		const custom = customAnswers.get(qIndex)?.trim();
		if (custom) selected.push(custom);
		return selected.length > 0 ? selected.join(', ') : '(skipped)';
	}

	function goToStep(step: number) {
		currentStep = step;
		reviewMode = false;
	}

	function nextStep() {
		if (currentStep < questions.length - 1) {
			currentStep++;
		} else {
			if (questions.length > 1) {
				reviewMode = true;
			} else {
				handleQuestionSubmit();
			}
		}
	}

	function prevStep() {
		if (currentStep > 0) currentStep--;
	}

	function handleQuestionSubmit() {
		const content: Record<string, string | number | boolean> = {};

		for (let i = 0; i < questions.length; i++) {
			const key = `q${i}`;
			const selected = Array.from(selectedOptions.get(i) ?? []);
			const custom = customAnswers.get(i)?.trim();
			if (custom) selected.push(custom);
			content[key] = JSON.stringify(selected);
		}

		onresult?.({ action: 'accept', content });
	}
</script>

{#if open && isQuestionElicitation()}
	<!-- Inline question UI -->
	{@const isSingle = questions.length === 1}

	<div class="flex w-full items-start gap-3 px-1">
		<div class="w-full rounded-box border border-base-300 p-4">
			{#if !isSingle && !reviewMode}
				<!-- Step indicators for multi-question -->
				<div class="mb-4 flex flex-wrap items-center gap-1.5">
					{#each questions as q, i}
						{@const color = stepColors[i % stepColors.length]}
						<button
							type="button"
							onclick={() => goToStep(i)}
							class="flex items-center justify-center rounded-full px-3 py-1 text-xs font-bold whitespace-nowrap transition-colors
								{i === currentStep
								? `${color.bg} ${color.text}`
								: hasAnswer(i)
									? 'bg-success/20 text-success ring-1 ring-success/30'
									: 'bg-base-200 text-base-content/40 hover:bg-base-300'}"
						>
							{q.header || q.question}
						</button>
					{/each}
				</div>
			{/if}

			{#if reviewMode}
				<!-- Review mode -->
				<p class="mb-3 text-sm font-medium text-base-content/70">Review your answers</p>
				<div class="space-y-1.5">
					{#each questions as q, i}
						<div class="flex items-start justify-between rounded-lg bg-base-200/60 px-3 py-2">
							<div class="min-w-0 flex-1">
								<div class="flex items-baseline gap-1.5">
									<span class="text-xs font-bold text-base-content/40">{i + 1}.</span>
									<span class="text-sm font-medium">{q.header || q.question}</span>
								</div>
								<p class="ml-4 text-sm {hasAnswer(i) ? 'text-base-content/70' : 'text-base-content/30 italic'}">
									{getAnswerSummary(i)}
								</p>
							</div>
							<button
								type="button"
								class="btn btn-ghost ml-2 btn-xs"
								onclick={() => goToStep(i)}
							>
								<Pencil class="h-3 w-3" />
							</button>
						</div>
					{/each}
				</div>

				<div class="mt-4 flex justify-end gap-2">
					<button type="button" class="btn btn-ghost btn-sm" onclick={handleDecline}>Cancel</button>
					<button type="button" class="btn btn-primary btn-sm" onclick={handleQuestionSubmit}>Submit</button>
				</div>
			{:else}
				<!-- Active question -->
				{@const q = questions[currentStep]}

				{#if isSingle && q.header}
					<div class="badge badge-neutral badge-sm mb-1">{q.header}</div>
				{/if}
				<p class="mb-2 text-sm font-medium">{q.question}</p>
				{#if q.multiple}
					<p class="mb-2 text-xs text-base-content/40">Select all that apply</p>
				{/if}

				<!-- Options -->
				<div class="space-y-1.5">
					{#each q.options as option (option.label)}
						{@const isSelected = selectedOptions.get(currentStep)?.has(option.label) ?? false}
						<button
							type="button"
							class="flex w-full cursor-pointer items-start gap-2.5 rounded-lg border p-2.5 text-left transition-colors
								{isSelected
								? 'border-primary bg-primary/10'
								: 'border-base-300 hover:border-base-content/20'}"
							onclick={() => toggleOption(currentStep, option.label)}
						>
							{#if q.multiple}
								<input
									type="checkbox"
									class="checkbox checkbox-primary checkbox-sm mt-0.5"
									checked={isSelected}
									tabindex={-1}
								/>
							{:else}
								<input
									type="radio"
									class="radio radio-primary radio-sm mt-0.5"
									checked={isSelected}
									tabindex={-1}
								/>
							{/if}
							<div class="min-w-0 flex-1">
								<span class="text-sm font-medium">{option.label}</span>
								{#if option.description}
									<p class="text-xs text-base-content/50">{option.description}</p>
								{/if}
							</div>
						</button>
					{/each}
				</div>

					<!-- Custom answer as styled option -->
				{@const isCustomSelected = showCustomInput.get(currentStep) ?? false}
				<div
					role="button"
					tabindex="0"
					class="flex w-full cursor-pointer items-start gap-2.5 rounded-lg border p-2.5 text-left transition-colors
						{isCustomSelected
						? 'border-primary bg-primary/10'
						: 'border-base-300 hover:border-base-content/20'}"
					onclick={() => toggleCustomInput(currentStep)}
					onkeydown={(e) => { if (e.key === 'Enter') toggleCustomInput(currentStep); }}
				>
					{#if q.multiple}
						<input
							type="checkbox"
							class="checkbox checkbox-primary checkbox-sm mt-0.5"
							checked={isCustomSelected}
							tabindex={-1}
						/>
					{:else}
						<input
							type="radio"
							class="radio radio-primary radio-sm mt-0.5"
							checked={isCustomSelected}
							tabindex={-1}
						/>
					{/if}
					<div class="min-w-0 flex-1">
						<span class="text-sm font-medium">Other (specify)</span>
						{#if isCustomSelected}
							<!-- svelte-ignore a11y_autofocus -->
							<textarea
								class="textarea textarea-bordered mt-1.5 w-full text-sm"
								placeholder="Type your answer..."
								rows={2}
								autofocus
								value={customAnswers.get(currentStep) ?? ''}
								onclick={(e) => e.stopPropagation()}
							oninput={(e) => updateCustomAnswer(currentStep, e.currentTarget.value)}
							></textarea>
						{/if}
					</div>
				</div>

				<!-- Navigation -->
				<div class="mt-3 flex items-center justify-between">
					<button
						type="button"
						class="btn btn-ghost btn-xs text-base-content/40"
						onclick={nextStep}
					>
						<SkipForward class="h-3 w-3" />
						Skip
					</button>
					<div class="flex gap-1.5">
						{#if !isSingle}
							<button
								type="button"
								class="btn btn-ghost btn-sm"
								disabled={currentStep === 0}
								onclick={prevStep}
							>
								<ChevronLeft class="h-4 w-4" />
								Back
							</button>
						{/if}
						{#if isSingle}
							<button
								type="button"
								class="btn btn-ghost btn-sm"
								onclick={handleDecline}
							>
								Cancel
							</button>
							<button
								type="button"
								class="btn btn-primary btn-sm"
								disabled={!hasAnswer(currentStep)}
								onclick={handleQuestionSubmit}
							>
								Submit
							</button>
						{:else if currentStep < questions.length - 1}
							<button
								type="button"
								class="btn btn-primary btn-sm"
								disabled={!hasAnswer(currentStep)}
								onclick={nextStep}
							>
								Next
								<ChevronRight class="h-4 w-4" />
							</button>
						{:else}
							<button
								type="button"
								class="btn btn-primary btn-sm"
								disabled={!hasAnswer(currentStep)}
								onclick={() => (reviewMode = true)}
							>
								Review
							</button>
						{/if}
					</div>
				</div>
			{/if}
		</div>
	</div>
{:else if open}
	<!-- Modal for OAuth and generic elicitations -->
	<dialog class="modal-open modal">
		<div class="modal-box w-full max-w-2xl">
			<form method="dialog">
				<button
					class="btn absolute top-2 right-2 btn-circle btn-ghost btn-sm"
					onclick={handleCancel}>✕</button
				>
			</form>

			{#if isOAuthElicitation()}
				<!-- OAuth Authentication Dialog -->
				<h3 class="mb-4 text-lg font-bold">Authentication Required</h3>

				<div class="mb-6">
					<p class="mb-4 text-base-content/80">
						The <strong>{getServerName()}</strong> server requires authentication to continue.
					</p>
					<p class="mb-4 text-base-content/80">Please click the link below to authenticate:</p>

					<div class="group relative mb-4 rounded-lg bg-base-200 p-4">
						<p class="pr-8 font-mono text-sm break-all text-base-content/90">{getOAuthUrl()}</p>
						<button
							type="button"
							class="btn absolute top-2 right-2 opacity-60 btn-ghost transition-opacity btn-xs hover:opacity-100"
							onclick={copyToClipboard}
							title="Copy to clipboard"
						>
							<Copy class="h-4 w-4" />
						</button>
						{#if showCopiedTooltip}
							<div
								class="absolute -top-8 right-2 rounded bg-success px-2 py-1 text-xs text-success-content shadow-lg transition-opacity duration-500 {showCopiedTooltip
									? 'opacity-100'
									: 'opacity-0'}"
							>
								Copied!
							</div>
						{/if}
					</div>
				</div>

				<div class="modal-action">
					<button type="button" class="btn btn-error" onclick={handleDecline}> Decline </button>
					<button type="button" class="btn btn-success" onclick={openOAuthLink}>
						Authenticate
					</button>
				</div>
			{:else}
				<!-- Generic Elicitation Form -->
				<h3 class="mb-4 text-lg font-bold">Information Request</h3>

				<div class="mb-6">
					<p class="whitespace-pre-wrap text-base-content/80">{elicitation.message}</p>
				</div>

				<form
					class="space-y-4"
					onsubmit={(e) => {
						e.preventDefault();
						handleAccept();
					}}
				>
					{#each Object.entries(elicitation.requestedSchema.properties) as [key, schema] (key)}
						<div class="form-control">
							<label class="label" for={key}>
								<span class="label-text font-medium">
									{getFieldTitle(key, schema)}
									{#if isRequired(key)}
										<span class="text-error">*</span>
									{/if}
								</span>
							</label>

							{#if schema.description}
								<div class="label">
									<span class="label-text-alt text-base-content/60">{schema.description}</span>
								</div>
							{/if}

							{#if schema.type === 'string' && 'enum' in schema}
								<!-- Enum/Select field -->
								<select
									id={key}
									bind:value={formData[key]}
									class="select-bordered select w-full"
									required={isRequired(key)}
								>
									{#each schema.enum as option, i (option)}
										<option value={option}>
											{schema.enumNames?.[i] || option}
										</option>
									{/each}
								</select>
							{:else if schema.type === 'boolean'}
								<!-- Boolean/Checkbox field -->
								<div class="form-control">
									<label class="label cursor-pointer justify-start gap-3">
										<input
											id={key}
											type="checkbox"
											checked={Boolean(formData[key])}
											onchange={(e) => (formData[key] = e.currentTarget.checked)}
											class="checkbox"
										/>
										<span class="label-text">Enable</span>
									</label>
								</div>
							{:else if schema.type === 'number' || schema.type === 'integer'}
								<!-- Number field -->
								<input
									id={key}
									type="number"
									bind:value={formData[key]}
									class="input-bordered input w-full"
									required={isRequired(key)}
									min={schema.minimum}
									max={schema.maximum}
									step={schema.type === 'integer' ? '1' : 'any'}
								/>
							{:else if schema.type === 'string'}
								<!-- String field -->
								{#if schema.format === 'email'}
									<input
										id={key}
										type="email"
										bind:value={formData[key]}
										class="input-bordered input w-full"
										required={isRequired(key)}
										minlength={schema.minLength}
										maxlength={schema.maxLength}
									/>
								{:else if schema.format === 'uri'}
									<input
										id={key}
										type="url"
										bind:value={formData[key]}
										class="input-bordered input w-full"
										required={isRequired(key)}
										minlength={schema.minLength}
										maxlength={schema.maxLength}
									/>
								{:else if schema.format === 'date'}
									<input
										id={key}
										type="date"
										bind:value={formData[key]}
										class="input-bordered input w-full"
										required={isRequired(key)}
									/>
								{:else if schema.format === 'date-time'}
									<input
										id={key}
										type="datetime-local"
										bind:value={formData[key]}
										class="input-bordered input w-full"
										required={isRequired(key)}
									/>
								{:else}
									<input
										id={key}
										type="text"
										bind:value={formData[key]}
										class="input-bordered input w-full"
										required={isRequired(key)}
										minlength={schema.minLength}
										maxlength={schema.maxLength}
									/>
								{/if}
							{/if}
						</div>
					{/each}
				</form>

				<div class="modal-action">
					<button type="button" class="btn btn-error" onclick={handleDecline}> Decline </button>
					<button
						type="button"
						class="btn btn-primary"
						disabled={!validateForm()}
						onclick={handleAccept}
					>
						Accept
					</button>
				</div>
			{/if}
		</div>
	</dialog>
{/if}
