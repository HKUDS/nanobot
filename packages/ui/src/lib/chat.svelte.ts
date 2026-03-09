import { SvelteDate, SvelteSet } from "svelte/reactivity";
import { getNotificationContext } from "./context/notifications.svelte";
import { SimpleClient } from "./mcpclient";
import {
	ChatPath,
	UIPath,
	type Agent,
	type Agents,
	type Attachment,
	type Chat,
	type ChatMessage,
	type ChatRequest,
	type ChatResult,
	type Elicitation,
	type ElicitationResult,
	type Event,
	type Prompt,
	type Prompts,
	type Resource,
	type ResourceContents,
	type Resources,
	type ToolOutputItem,
	type UploadedFile,
	type UploadingFile,
} from "./types";

export interface CallToolResult {
	content?: ToolOutputItem[];
}

export class ChatAPI {
	private readonly baseUrl: string;
	private readonly mcpClient: SimpleClient;

	constructor(
		baseUrl: string = "",
		opts?: {
			fetcher?: typeof fetch;
			sessionId?: string;
		},
	) {
		this.baseUrl = baseUrl;
		this.mcpClient = new SimpleClient({
			baseUrl: baseUrl,
			path: UIPath,
			fetcher: opts?.fetcher,
			sessionId: opts?.sessionId,
		});
	}

	#getClient(sessionId?: string) {
		if (sessionId) {
			return new SimpleClient({
				baseUrl: this.baseUrl,
				path: ChatPath,
				sessionId,
			});
		}
		return this.mcpClient;
	}

	async reply(
		id: string | number,
		result: unknown,
		opts?: { sessionId?: string },
	) {
		// If sessionId is provided, create a new client instance with that session
		const client = this.#getClient(opts?.sessionId);
		await client.reply(id, result);
	}

	async exchange(
		method: string,
		params: unknown,
		opts?: { sessionId?: string },
	) {
		// If sessionId is provided, create a new client instance with that session
		const client = this.#getClient(opts?.sessionId);
		const { result } = await client.exchange(method, params);
		return result;
	}

	async callMCPTool<T>(
		name: string,
		opts?: {
			payload?: Record<string, unknown>;
			sessionId?: string;
			progressToken?: string;
			async?: boolean;
			abort?: AbortController;
			requestId?: string;
			parseResponse?: (data: CallToolResult) => T;
		},
	): Promise<{ result: T; requestId: string }> {
		// If sessionId is provided, create a new client instance with that session
		const client = this.#getClient(opts?.sessionId);

		try {
			// Get the raw result and requestId from exchange
			const { result, requestId } = await client.exchange(
				"tools/call",
				{
					name: name,
					arguments: opts?.payload || {},
					...(opts?.async && {
						_meta: {
							"ai.nanobot.async": true,
							progressToken: opts?.progressToken,
						},
					}),
				},
				{ abort: opts?.abort, requestId: opts?.requestId },
			);

			let finalResult: T;
			if (opts?.parseResponse) {
				finalResult = opts.parseResponse(result as CallToolResult);
			} else if (
				result &&
				typeof result === "object" &&
				"structuredContent" in result
			) {
				// Handle structured content
				finalResult = (result as { structuredContent: T }).structuredContent;
			} else {
				finalResult = result as T;
			}

			return { result: finalResult, requestId };
		} catch (error) {
			// Try to get notification context and show error
			try {
				const notifications = getNotificationContext();
				const message = error instanceof Error ? error.message : String(error);
				notifications.error("API Error", message);
			} catch {
				// If context is not available (e.g., during SSR), just log
				console.error("MCP Tool Error:", error);
			}
			throw error;
		}
	}

	async capabilities() {
		const client = this.#getClient();
		const { initializeResult } = await client.getSessionDetails();
		return (
			initializeResult?.capabilities?.experimental?.["ai.nanobot"]?.session ??
			{}
		);
	}

	async deleteThread(threadId: string): Promise<void> {
		const client = this.#getClient(threadId);
		return client.deleteSession();
	}

	async renameThread(threadId: string, title: string): Promise<Chat> {
		const { result } = await this.callMCPTool<Chat>("update_chat", {
			payload: {
				chatId: threadId,
				title: title,
			},
		});
		return result;
	}

	async listAgents(opts?: { sessionId?: string }): Promise<Agents> {
		const { result } = await this.callMCPTool<Agents>("list_agents", opts);
		return result;
	}

	async getThreads(): Promise<Chat[]> {
		const { result } = await this.callMCPTool<{
			chats: Chat[];
		}>("list_chats");
		return result.chats;
	}

	async createThread(): Promise<Chat> {
		const client = this.#getClient("new");
		const { id } = await client.getSessionDetails();
		return {
			id,
			title: "New Chat",
			created: new SvelteDate().toISOString(),
		};
	}

	async uploadFile(
		name: string,
		mimeType: string,
		blob: string,
		opts?: {
			sessionId?: string;
			abort?: AbortController;
		},
	): Promise<Attachment> {
		const { result } = await this.callMCPTool<Attachment>("uploadFile", {
			payload: {
				blob,
				mimeType,
				name,
			},
			sessionId: opts?.sessionId,
			abort: opts?.abort,
			parseResponse: (resp: CallToolResult) => {
				if (resp.content?.[0]?.type === "resource_link") {
					return {
						name: resp.content[0].name,
						uri: resp.content[0].uri,
						mimeType: mimeType,
					};
				}
				return {
					uri: "",
				};
			},
		});
		return result;
	}

	async sendMessage(
		request: ChatRequest,
		toolName: string,
		requestId: string,
	): Promise<{ result: ChatResult; requestId: string }> {
		await this.callMCPTool<CallToolResult>(toolName, {
			requestId,
			payload: {
				prompt: request.message,
				attachments: request.attachments?.map((a) => {
					return {
						name: a.name,
						url: a.uri,
						mimeType: a.mimeType,
					};
				}),
			},
			sessionId: request.threadId,
			progressToken: request.id,
			async: true,
		});
		const message: ChatMessage = {
			id: request.id,
			role: "user",
			created: now(),
			items: [
				{
					id: request.id + "_0",
					type: "text",
					text: request.message,
				},
				...buildFileAttachmentPreviewItems(request.id, request.attachments || []),
			],
		};
		return {
			result: { message },
			requestId,
		};
	}

	async readResource(
		uri: string,
		opts?: { sessionId?: string },
	): Promise<{ contents: ResourceContents[] }> {
		const client = this.#getClient(opts?.sessionId);
		return client.readResource(uri);
	}

	async cancelRequest(requestId: string, sessionId: string): Promise<void> {
		const client = this.#getClient(sessionId);
		await client.notify("notifications/cancelled", {
			requestId,
			reason: "User requested cancellation",
		});
	}

	subscribe(
		threadId: string,
		onEvent: (e: Event) => void,
		opts?: {
			events?: string[];
			batchInterval?: number;
		},
	): () => void {
		console.log("Subscribing to thread:", threadId);
		const eventSource = new EventSource(
			`${this.baseUrl}/api/events/${threadId}`,
		);

		// Batching setup
		const batchInterval = opts?.batchInterval ?? 200; // Default 200ms
		let eventBuffer: Event[] = [];
		let batchTimer: ReturnType<typeof setTimeout> | null = null;

		const flushBuffer = () => {
			if (eventBuffer.length === 0) return;

			// Process all buffered events at once
			const eventsToProcess = [...eventBuffer];
			eventBuffer = [];

			for (const event of eventsToProcess) {
				onEvent(event);
			}
		};

		const scheduleBatch = () => {
			if (batchTimer === null) {
				batchTimer = setTimeout(() => {
					flushBuffer();
					batchTimer = null;
				}, batchInterval);
			}
		};

		eventSource.onmessage = (e) => {
			const data = JSON.parse(e.data);
			eventBuffer.push({
				type: "message",
				message: data,
			});
			scheduleBatch();
		};

		for (const type of opts?.events ?? []) {
			eventSource.addEventListener(type, (e) => {
				const idInt = parseInt(e.lastEventId);
				const event: Event = {
					id: idInt || e.lastEventId,
					type: type as
						| "history-start"
						| "history-end"
						| "chat-in-progress"
						| "chat-done"
						| "elicitation/create"
						| "error",
					data: JSON.parse(e.data),
				};

				// Certain events should be processed immediately (not batched)
				if (
					type === "history-start" ||
					type === "history-end" ||
					type === "chat-done"
				) {
					// Flush any pending events first
					flushBuffer();
					if (batchTimer !== null) {
						clearTimeout(batchTimer);
						batchTimer = null;
					}
					// Then process this event immediately
					onEvent(event);
				} else {
					eventBuffer.push(event);
					scheduleBatch();
				}
			});
		}

		eventSource.onerror = (e) => {
			// Flush buffer before processing error
			flushBuffer();
			if (batchTimer !== null) {
				clearTimeout(batchTimer);
				batchTimer = null;
			}
			onEvent({ type: "error", error: String(e) });
			console.error("EventSource failed:", e);
			eventSource.close();
		};

		eventSource.onopen = () => {
			console.log("EventSource connected for thread:", threadId);
		};

		return () => {
			// Clean up: flush remaining events and clear timer
			flushBuffer();
			if (batchTimer !== null) {
				clearTimeout(batchTimer);
			}
			eventSource.close();
		};
	}
}

export function appendMessage(
	messages: ChatMessage[],
	newMessage: ChatMessage,
): ChatMessage[] {
	let found = false;
	if (newMessage.id) {
		messages = messages.map((oldMessage) => {
			if (oldMessage.id === newMessage.id) {
				found = true;
				return newMessage;
			}
			return oldMessage;
		});
	}
	if (!found) {
		messages = [...messages, newMessage];
	}
	return messages;
}

function attachmentPreviewName(attachment: Attachment): string | undefined {
	if (attachment.name) {
		return attachment.name;
	}

	if (!attachment.uri.startsWith("file:///")) {
		return undefined;
	}

	const rawPath = attachment.uri.replace(/^file:\/\/\//, "");
	let decodedPath = rawPath;
	try {
		decodedPath = decodeURIComponent(rawPath);
	} catch {
		// keep raw path if decode fails
	}
	return decodedPath.split("/").filter(Boolean).pop() || decodedPath;
}

function buildFileAttachmentPreviewItems(messageID: string, attachments: Attachment[]) {
	const seen = new SvelteSet<string>();
	return attachments
		.filter((attachment) => {
			const uri = attachment.uri || "";
			if (!uri.startsWith("file:///") || seen.has(uri)) {
				return false;
			}
			seen.add(uri);
			return true;
		})
		.map((attachment, index) => ({
			id: `${messageID}_attachment_${index}`,
			type: "resource_link" as const,
			uri: attachment.uri,
			name: attachmentPreviewName(attachment),
			mimeType: attachment.mimeType || "application/octet-stream",
		}));
}

// Default instance
export const defaultChatApi = new ChatAPI();

export class ChatService {
	messages: ChatMessage[];
	prompts: Prompt[];
	resources: Resource[];
	agent: Agent;
	agents: Agent[];
	selectedAgentId: string;
	elicitations: Elicitation[];
	isLoading: boolean;
	chatId: string;
	uploadedFiles: UploadedFile[];
	uploadingFiles: UploadingFile[];

	private api: ChatAPI;
	private closer = () => {};
	private history: ChatMessage[] | undefined;
	private onChatDone: (() => void)[] = [];
	private currentRequestId: string | undefined;

	constructor(opts?: { api?: ChatAPI; chatId?: string }) {
		this.api = opts?.api || defaultChatApi;
		this.messages = $state<ChatMessage[]>([]);
		this.history = $state<ChatMessage[]>();
		this.isLoading = $state(false);
		this.elicitations = $state<Elicitation[]>([]);
		this.prompts = $state<Prompt[]>([]);
		this.resources = $state<Resource[]>([]);
		this.chatId = $state("");
		this.agent = $state<Agent>({ id: "" });
		this.agents = $state<Agent[]>([]);
		this.selectedAgentId = $state("");
		this.uploadedFiles = $state([]);
		this.uploadingFiles = $state([]);
		this.setChatId(opts?.chatId);
	}

	close = () => {
		this.closer();
		this.setChatId("");
	};

	setChatId = async (chatId?: string) => {
		if (chatId === this.chatId) {
			return;
		}

		this.messages = [];
		this.prompts = [];
		this.resources = [];
		this.elicitations = [];
		this.history = undefined;
		this.isLoading = false;
		this.uploadedFiles = [];
		this.uploadingFiles = [];

		if (chatId) {
			this.chatId = chatId;
			this.subscribe(chatId);
		}

		this.listResources({ useDefaultSession: true }).then((r) => {
			if (r && r.resources) {
				this.resources = r.resources;
			}
		});

		this.listPrompts({ useDefaultSession: true }).then((prompts) => {
			if (prompts && prompts.prompts) {
				this.prompts = prompts.prompts;
			}
		});

		await this.reloadAgent({ useDefaultSession: true });
	};

	private reloadAgent = async (opts?: { useDefaultSession?: boolean }) => {
		const sessionId = opts?.useDefaultSession ? undefined : this.chatId;
		const agentsData = await this.api.listAgents({ sessionId });
		if (agentsData.agents?.length > 0) {
			this.agents = agentsData.agents;
			this.agent =
				agentsData.agents.find((a) => a.current) || agentsData.agents[0];

			// Only reset selectedAgentId if:
			// 1. It's not set yet (empty string), OR
			// 2. The currently selected agent is no longer in the agents list
			const isSelectedAgentStillAvailable = agentsData.agents.some(
				(a) => a.id === this.selectedAgentId,
			);

			if (!this.selectedAgentId || !isSelectedAgentStillAvailable) {
				this.selectedAgentId = this.agent.id || "";
			}
		}
	};

	selectAgent = (agentId: string) => {
		this.selectedAgentId = agentId;
		// Keep this.agent in sync with the selectedAgentId so the UI
		// (which may rely on chat.agent) reflects the newly selected agent.
		const selectedAgent = this.agents?.find((a) => a.id === agentId);
		if (selectedAgent) {
			this.agent = selectedAgent;
		}
	};

	listPrompts = async (opts?: { useDefaultSession?: boolean }) => {
		const sessionId = opts?.useDefaultSession ? undefined : this.chatId;
		return (await this.api.exchange(
			"prompts/list",
			{},
			{
				sessionId,
			},
		)) as Prompts;
	};

	listResources = async (opts?: { useDefaultSession?: boolean }) => {
		const sessionId = opts?.useDefaultSession ? undefined : this.chatId;
		return (await this.api.exchange(
			"resources/list",
			{},
			{
				sessionId,
			},
		)) as Resources;
	};

	private subscribe(chatId: string) {
		this.closer();
		if (!chatId) {
			return;
		}
		this.closer = this.api.subscribe(
			chatId,
			(event) => {
				if (event.type == "message" && event.message?.id) {
					if (this.history) {
						this.history = appendMessage(this.history, event.message);
					} else {
						this.messages = appendMessage(this.messages, event.message);
					}
				} else if (event.type == "history-start") {
					this.history = [];
				} else if (event.type == "history-end") {
					this.messages = this.history || [];
					this.history = undefined;
				} else if (event.type == "chat-in-progress") {
					this.isLoading = true;
				} else if (event.type == "chat-done") {
					this.isLoading = false;
					for (const waiting of this.onChatDone) {
						waiting();
					}
					this.onChatDone = [];
				} else if (event.type == "elicitation/create") {
					this.elicitations = [
						...this.elicitations,
						{
							id: event.id,
							...(event.data as object),
						} as Elicitation,
					];
				}
				console.debug("Received event:", event);
			},
			{
				events: [
					"history-start",
					"history-end",
					"chat-in-progress",
					"chat-done",
					"elicitation/create",
				],
			},
		);
	}

	replyToElicitation = async (
		elicitation: Elicitation,
		result: ElicitationResult,
	) => {
		await this.api.reply(elicitation.id, result, {
			sessionId: this.chatId,
		});
		this.elicitations = this.elicitations.filter(
			(e) => e.id !== elicitation.id,
		);
	};

	newChat = async () => {
		const thread = await this.api.createThread();
		await this.setChatId(thread.id);
	};

	sendMessage = async (message: string, attachments?: Attachment[]) => {
		if (!message.trim() || this.isLoading) return;

		this.isLoading = true;

		if (!this.chatId) {
			await this.newChat();
		}

		// Determine which tool to call based on selected or current agent
		const effectiveAgentId = this.selectedAgentId || this.agent?.id;
		if (!effectiveAgentId) {
			this.isLoading = false;
			throw new Error(
				"No agent selected or available for sending chat messages.",
			);
		}
		const toolName = `chat-with-${effectiveAgentId}`;

		try {
			// Store the request ID before the exchange so cancellation works immediately
			const requestId = crypto.randomUUID();
			this.currentRequestId = requestId;

			const { result } = await this.api.sendMessage(
				{
					id: crypto.randomUUID(),
					threadId: this.chatId,
					message: message,
					attachments: [...this.uploadedFiles, ...(attachments || [])],
				},
				toolName,
				requestId,
			);
			this.uploadedFiles = [];

			this.messages = appendMessage(this.messages, result.message);
			return new Promise<ChatResult | void>((resolve) => {
				this.onChatDone.push(() => {
					this.isLoading = false;
					this.currentRequestId = undefined;
					const i = this.messages.findIndex((m) => m.id === result.message.id);
					if (i !== -1 && i <= this.messages.length) {
						resolve({
							message: this.messages[i + 1],
						});
					} else {
						resolve();
					}
				});
			});
		} catch (error) {
			this.isLoading = false;
			this.currentRequestId = undefined;
			this.messages = appendMessage(this.messages, {
				id: crypto.randomUUID(),
				role: "assistant",
				created: now(),
				items: [
					{
						id: crypto.randomUUID(),
						type: "text",
						text: `Sorry, I couldn't send your message. Please try again. Error: ${error}`,
					},
				],
			});
		}
	};

	readResource = async (uri: string) => {
		return this.api.readResource(uri, { sessionId: this.chatId });
	};

	cancelChat = async () => {
		if (!this.currentRequestId || !this.chatId) return;

		const requestId = this.currentRequestId;
		this.currentRequestId = undefined;
		this.isLoading = false;

		// Fire all onChatDone callbacks
		for (const waiting of this.onChatDone) {
			waiting();
		}
		this.onChatDone = [];

		// Send the cancellation notification
		await this.api.cancelRequest(requestId, this.chatId);
	};

	cancelUpload = (fileId: string) => {
		this.uploadingFiles = this.uploadingFiles.filter((f) => {
			if (f.id !== fileId) {
				return true;
			}
			if (f.controller) {
				f.controller.abort();
			}
			return false;
		});

		// Delete the uploaded file from disk
		const uploaded = this.uploadedFiles.find((f) => f.id === fileId);
		if (uploaded?.uri) {
			this.api
				.callMCPTool("deleteFile", {
					payload: { uri: uploaded.uri },
					sessionId: this.chatId,
				})
				.catch((err) => console.error("Failed to delete uploaded file:", err));
		}

		this.uploadedFiles = this.uploadedFiles.filter((f) => f.id !== fileId);
	};

	uploadFile = async (
		file: File,
		opts?: {
			controller?: AbortController;
		},
	): Promise<Attachment> => {
		// Create thread if it doesn't exist
		if (!this.chatId) {
			const thread = await this.api.createThread();
			await this.setChatId(thread.id);
		}

		const fileId = crypto.randomUUID();
		const controller = opts?.controller || new AbortController();

		this.uploadingFiles.push({
			file,
			id: fileId,
			controller,
		});

		try {
			const result = await this.doUploadFile(file, controller);
			this.uploadedFiles.push({
				file,
				uri: result.uri,
				id: fileId,
				mimeType: result.mimeType,
			});
			return result;
		} finally {
			this.uploadingFiles = this.uploadingFiles.filter((f) => f.id !== fileId);
		}
	};

	private doUploadFile = async (
		file: File,
		controller: AbortController,
	): Promise<Attachment> => {
		// convert file to base64 string
		const reader = new FileReader();
		reader.readAsDataURL(file);
		await new Promise((resolve, reject) => {
			reader.onloadend = resolve;
			reader.onerror = reject;
		});
		const base64 = (reader.result as string).split(",")[1];

		if (!this.chatId) {
			throw new Error("Chat ID not set");
		}

		return await this.api.uploadFile(file.name, file.type, base64, {
			sessionId: this.chatId,
			abort: controller,
		});
	};
}

function now(): string {
	return new Date().toISOString();
}
