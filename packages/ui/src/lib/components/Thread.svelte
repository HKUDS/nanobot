<script lang="ts">
import { ChevronDown, Upload } from "@lucide/svelte";
import Elicitation from "$lib/components/Elicitation.svelte";
import Prompt from "$lib/components/Prompt.svelte";
import type {
	Agent,
	Attachment,
	ChatMessage,
	ChatResult,
	ElicitationResult,
	Elicitation as ElicitationType,
	Prompt as PromptType,
	Resource,
	ResourceContents,
	UploadedFile,
	UploadingFile,
} from "$lib/types";
import MessageInput from "./MessageInput.svelte";
import Messages from "./Messages.svelte";

interface Props {
	messages: ChatMessage[];
	prompts: PromptType[];
	resources: Resource[];
	elicitations?: ElicitationType[];
	onElicitationResult?: (
		elicitation: ElicitationType,
		result: ElicitationResult,
	) => void;
	onSendMessage?: (
		message: string,
		attachments?: Attachment[],
	) => Promise<ChatResult | void>;
	onFileUpload?: (
		file: File,
		opts?: { controller?: AbortController },
	) => Promise<Attachment>;
	cancelUpload?: (fileId: string) => void;
	uploadingFiles?: UploadingFile[];
	uploadedFiles?: UploadedFile[];
	isLoading?: boolean;
	agent?: Agent;
	agents?: Agent[];
	selectedAgentId?: string;
	onAgentChange?: (agentId: string) => void;
	onCancel?: () => void;
	onReadResource?: (uri: string) => Promise<{ contents: ResourceContents[] }>;
}

const {
	// Do not use _chat variable anywhere except these assignments
	messages,
	prompts,
	resources,
	onSendMessage,
	onFileUpload,
	cancelUpload,
	uploadingFiles,
	uploadedFiles,
	elicitations,
	onElicitationResult,
	agent,
	agents = [],
	selectedAgentId = "",
	onAgentChange,
	isLoading,
	onCancel,
	onReadResource,
}: Props = $props();

let messagesContainer: HTMLElement;
let showScrollButton = $state(false);
let previousLastMessageId = $state<string | null>(null);
const hasMessages = $derived(messages && messages.length > 0);
let selectedPrompt = $state<string | undefined>();

// Split elicitations: question type renders inline, others render as modal
const questionElicitation = $derived(
	elicitations?.find((e) => e._meta?.["ai.nanobot.meta/question"]) ?? null,
);
const modalElicitation = $derived(
	elicitations?.find((e) => !e._meta?.["ai.nanobot.meta/question"]) ?? null,
);

// Watch for changes to the last message ID and scroll to bottom
$effect(() => {
	if (!messagesContainer) return;

	// Make this reactive to changes in messages
	void messages.length;

	const lastDiv = messagesContainer.querySelector(
		"#message-groups > :last-child",
	);
	const currentLastMessageId = lastDiv?.getAttribute("data-message-id");

	if (currentLastMessageId && currentLastMessageId !== previousLastMessageId) {
		// Wait for DOM update, then scroll to bottom
		setTimeout(() => {
			scrollToBottom();
		}, 10);
		previousLastMessageId = currentLastMessageId;
	}
});

function handleScroll() {
	if (!messagesContainer) return;

	const { scrollTop, scrollHeight, clientHeight } = messagesContainer;
	const isNearBottom = scrollTop + clientHeight >= scrollHeight - 10; // 10px threshold
	showScrollButton = !isNearBottom;
}

function scrollToBottom() {
	if (messagesContainer) {
		messagesContainer.scrollTo({
			top: messagesContainer.scrollHeight,
			behavior: "smooth",
		});
	}
}

// Drag-and-drop file upload
let isDragging = $state(false);
let dragCounter = 0;

function handleDragEnter(e: DragEvent) {
	e.preventDefault();
	dragCounter++;
	if (e.dataTransfer?.types.includes('Files')) {
		isDragging = true;
	}
}

function handleDragLeave(e: DragEvent) {
	e.preventDefault();
	dragCounter--;
	if (dragCounter === 0) {
		isDragging = false;
	}
}

function handleDragOver(e: DragEvent) {
	e.preventDefault();
}

async function handleDrop(e: DragEvent) {
	e.preventDefault();
	dragCounter = 0;
	isDragging = false;

	if (!onFileUpload || !e.dataTransfer?.files.length) return;

	for (const file of e.dataTransfer.files) {
		onFileUpload(file);
	}
}
</script>

<div
	class="flex h-dvh w-full flex-col md:relative peer-[.workspace]:md:w-1/4"
	ondragenter={handleDragEnter}
	ondragleave={handleDragLeave}
	ondragover={handleDragOver}
	ondrop={handleDrop}
>
	<!-- Drag-and-drop overlay -->
	{#if isDragging}
		<div
			class="pointer-events-none absolute inset-0 z-50 flex items-center justify-center bg-base-300/60 backdrop-blur-sm"
		>
			<div
				class="flex flex-col items-center gap-3 rounded-2xl border-2 border-dashed border-primary bg-base-100/90 px-10 py-8 shadow-xl"
			>
				<Upload class="size-10 text-primary" />
				<p class="text-lg font-semibold text-base-content">Drop files to upload</p>
			</div>
		</div>
	{/if}

	<!-- Messages area - full height scrollable with bottom padding for floating input -->
	<div class="w-full overflow-y-auto" bind:this={messagesContainer} onscroll={handleScroll}>
		<div class="mx-auto max-w-4xl">
			<!-- Prompts section - show when prompts available and no messages -->
			{#if prompts && prompts.length > 0}
				<div class="mb-6">
					<div class="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
						{#each prompts as prompt (prompt.name)}
							{#if selectedPrompt === prompt.name}
								<Prompt
									{prompt}
									onSend={async (m) => {
										selectedPrompt = undefined;
										if (onSendMessage) {
											return await onSendMessage(m);
										}
									}}
									onCancel={() => (selectedPrompt = undefined)}
									open
								/>
							{/if}
						{/each}
					</div>
				</div>
			{/if}

			<Messages {messages} onSend={onSendMessage} {isLoading} {agent} {onReadResource} />
		</div>
	</div>

	<!-- Message input - centered when no messages, bottom when messages exist -->
	<div
		class="absolute right-0 bottom-0 left-0 flex flex-col transition-all duration-500 ease-in-out {hasMessages
			? 'bg-base-100/80 backdrop-blur-sm'
			: 'md:-translate-y-1/2 [@media(min-height:900px)]:md:top-1/2 [@media(min-height:900px)]:md:bottom-auto'}"
	>
		<!-- Scroll to bottom button -->
		{#if showScrollButton && hasMessages}
			<button
				class="btn mx-auto btn-circle border-base-300 bg-base-100 shadow-lg btn-md active:translate-y-0.5"
				onclick={scrollToBottom}
				aria-label="Scroll to bottom"
			>
				<ChevronDown class="size-5" />
			</button>
		{/if}
		<div class="mx-auto w-full max-w-4xl">
			{#if questionElicitation}
				{#key questionElicitation.id}
					<Elicitation
						elicitation={questionElicitation}
						open
						onresult={(result) => {
							onElicitationResult?.(questionElicitation, result);
						}}
					/>
				{/key}
			{/if}
			<MessageInput
				placeholder={`Type your message...${prompts && prompts.length > 0 ? ' or / for prompts' : ''}`}
				onSend={onSendMessage}
				{resources}
				{messages}
				{agents}
				{selectedAgentId}
				{onAgentChange}
				onPrompt={(p) => (selectedPrompt = p)}
				{onFileUpload}
				disabled={isLoading}
				{prompts}
				{cancelUpload}
				{uploadingFiles}
				{uploadedFiles}
				{onCancel}
			/>
		</div>
	</div>

	<!-- Modal elicitations (OAuth, generic form) -->
	{#if modalElicitation}
		{#key modalElicitation.id}
			<Elicitation
				elicitation={modalElicitation}
				open
				onresult={(result) => {
					onElicitationResult?.(modalElicitation, result);
				}}
			/>
		{/key}
	{/if}
</div>
