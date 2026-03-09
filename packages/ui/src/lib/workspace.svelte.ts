import { SvelteDate, SvelteMap } from "svelte/reactivity";
import { ChatService } from "./chat.svelte";
import { SimpleClient } from "./mcpclient";
import type {
	Session,
	SessionDetails,
	Workspace,
	WorkspaceClient,
	WorkspaceFile,
} from "./types";

export class WorkspaceInstance implements WorkspaceClient {
	readonly #client: SimpleClient;
	readonly #workspaceId: string;
	readonly #service: WorkspaceService;
	readonly #chatCache = new SvelteMap<string, ChatService>();

	files = $state<WorkspaceFile[]>([]);
	sessions = $state<Session[]>([]);
	loading = $state<boolean>(false);

	constructor(
		workspaceId: string,
		service: WorkspaceService,
		client?: SimpleClient,
	) {
		this.#workspaceId = workspaceId;
		this.#service = service;
		this.#client =
			client ?? new SimpleClient({ workspaceId, workspaceShared: true });

		// Load resources asynchronously
		this.load();
	}

	get id(): string {
		return this.#workspaceId;
	}

	get workspace(): Workspace {
		return (
			this.#service.workspaces.find((w) => w.id === this.#workspaceId) ?? {
				id: this.#workspaceId,
				name: "Missing",
				created: new SvelteDate().toISOString(),
				order: 0,
				color: "",
				icons: [],
			}
		);
	}

	async getSessionDetails(sessionId: string): Promise<SessionDetails> {
		const uri = `session://${sessionId}`;
		const result = await this.#client.readResource(uri);

		if (!result.contents || result.contents.length === 0) {
			throw new Error(`Session not found: ${sessionId}`);
		}

		const content = result.contents[0];
		if (!content.text) {
			throw new Error(`Session has no content: ${sessionId}`);
		}

		return JSON.parse(content.text);
	}

	async newSession(opts?: { editor?: boolean }): Promise<ChatService> {
		const client = new SimpleClient({
			sessionId: "new",
			workspaceId: this.#workspaceId,
			workspaceShared: opts?.editor,
		});
		const { id: sessionId } = await client.getSessionDetails();
		return this.getSession(sessionId);
	}

	async load(): Promise<void> {
		this.loading = true;

		try {
			const result = await this.#client.listResources({
				prefix: ["workspace://", "session://"],
			});

			// Map workspace:// resources to File objects and sort
			this.files = result.resources
				.filter((r) => r.uri.startsWith("workspace://"))
				.map((r) => ({
					name: r.name.replace("workspace://", ""),
				}))
				.sort((a, b) => a.name.localeCompare(b.name));

			// Map session:// resources to Session objects
			this.sessions = result.resources
				.filter((r) => r.uri.startsWith("session://"))
				.map((r) => ({
					id: r.uri.replace("session://", ""),
					title: r.description || r.name,
				}));
		} finally {
			this.loading = false;
		}
	}

	async readFile(path: string): Promise<Blob> {
		const uri = `workspace://${path}`;
		const result = await this.#client.readResource(uri);

		if (!result.contents || result.contents.length === 0) {
			throw new Error(`File not found: ${path}`);
		}

		const content = result.contents[0];
		const mimeType = content.mimeType || "application/octet-stream";

		// Handle base64 blob
		if (content.blob) {
			const binaryString = atob(content.blob);
			const bytes = new Uint8Array(binaryString.length);
			for (let i = 0; i < binaryString.length; i++) {
				bytes[i] = binaryString.charCodeAt(i);
			}
			return new Blob([bytes], { type: mimeType });
		}

		// Handle text content
		if (content.text) {
			return new Blob([content.text], { type: mimeType });
		}

		// Empty file
		return new Blob([], { type: mimeType });
	}

	async writeFile(path: string, data: Blob | string): Promise<void> {
		// Convert data to base64
		let base64Data: string;

		if (typeof data === "string") {
			// Convert string to base64
			const encoder = new TextEncoder();
			const bytes = encoder.encode(data);
			base64Data = btoa(String.fromCharCode(...bytes));
		} else {
			// Convert Blob to base64
			const arrayBuffer = await data.arrayBuffer();
			const bytes = new Uint8Array(arrayBuffer);
			base64Data = btoa(String.fromCharCode(...bytes));
		}

		const uri = `workspace://${path}`;

		await this.#client.callMCPTool("uploadFile", {
			payload: {
				name: uri,
				blob: base64Data,
				mimeType: typeof data === "string" ? "text/plain" : data.type,
			},
		});

		// Update files list if not already present
		const exists = this.files.some((f) => f.name === path);
		if (!exists) {
			this.files = [...this.files, { name: path }].sort((a, b) =>
				a.name.localeCompare(b.name),
			);
		}
	}

	async createFile(path: string, data: Blob | string): Promise<void> {
		return this.writeFile(path, data);
	}

	async deleteFile(path: string): Promise<void> {
		const uri = `workspace://${path}`;

		await this.#client.callMCPTool("deleteFile", {
			payload: {
				uri,
			},
		});

		// Remove file(s) from list
		// Check if any file has this path as a directory prefix
		// (i.e., if removing the path prefix leaves a string starting with '/')
		const hasDescendants = this.files.some((f) => {
			if (f.name === path) return false; // Skip exact match
			if (!f.name.startsWith(path)) return false; // Must start with path
			const tail = f.name.slice(path.length);
			return tail.startsWith("/"); // Tail must start with /
		});

		if (hasDescendants) {
			// This is a directory - remove it and all descendants
			this.files = this.files.filter((f) => {
				if (f.name === path) return false;
				if (!f.name.startsWith(path)) return true;
				const tail = f.name.slice(path.length);
				return !tail.startsWith("/");
			});
		} else {
			// This is a single file - remove exact match only
			this.files = this.files.filter((f) => f.name !== path);
		}
	}

	async deleteSession(sessionId: string): Promise<void> {
		const uri = `session://${sessionId}`;

		await this.#client.callMCPTool("deleteFile", {
			payload: {
				uri,
			},
		});

		const chat = this.#chatCache.get(sessionId);
		if (chat) {
			chat.close();
			this.#chatCache.delete(sessionId);
		}

		this.sessions = this.sessions.filter((s) => s.id !== sessionId);
	}

	async getSession(sessionId: string): Promise<ChatService> {
		let chatInstance = this.#chatCache.get(sessionId);

		if (!chatInstance) {
			chatInstance = new ChatService({ chatId: sessionId });
			this.#chatCache.set(sessionId, chatInstance);
		}

		return chatInstance;
	}
}

export class WorkspaceService {
	#client: SimpleClient;
	#instanceCache = new SvelteMap<string, WorkspaceInstance>();

	workspaces = $state<Workspace[]>([]);

	constructor(client?: SimpleClient) {
		this.#client = client ?? new SimpleClient();
	}

	async load(): Promise<void> {
		const workspaceResources = await this.#client.listResources({
			prefix: "nanobot://workspaces/",
		});

		this.workspaces = workspaceResources.resources.map((resource) => ({
			id: resource.uri.replace("nanobot://workspaces/", ""),
			name: resource.name,
			created:
				(resource._meta?.created as string) ?? new SvelteDate().toISOString(),
			order: (resource._meta?.order as number) ?? 0,
			color: (resource._meta?.color as string) ?? "",
			icons: resource.icons,
		}));
	}

	async createWorkspace(
		workspace: Omit<Workspace, "id" | "created">,
	): Promise<Workspace> {
		const { result: created } = await this.#client.callMCPTool<Workspace>(
			"create_workspace",
			{
				payload: {
					name: workspace.name,
					order: workspace.order,
					color: workspace.color,
					icons: workspace.icons,
				},
			},
		);

		// Add to local state
		this.workspaces = [...this.workspaces, created];

		return created;
	}

	async updateWorkspace(
		workspace: Partial<Workspace> & Pick<Workspace, "id">,
	): Promise<Workspace> {
		const { result: updated } = await this.#client.callMCPTool<Workspace>(
			"update_workspace",
			{
				payload: {
					uri: `nanobot://workspaces/${workspace.id}`,
					name: workspace.name,
					order: workspace.order,
					color: workspace.color,
					icons: workspace.icons,
				},
			},
		);

		// Update local state
		this.workspaces = this.workspaces.map((w) =>
			w.id === updated.id ? updated : w,
		);

		return updated;
	}

	async deleteWorkspace(workspace: Workspace | string): Promise<void> {
		const id = typeof workspace === "string" ? workspace : workspace.id;

		await this.#client.callMCPTool<string>("delete_workspace", {
			payload: {
				uri: `nanobot://workspaces/${id}`,
			},
		});

		// Remove from local state
		this.workspaces = this.workspaces.filter((w) => w.id !== id);

		// Remove from instance cache
		this.#instanceCache.delete(id);
	}

	getWorkspace(id: string): WorkspaceClient {
		let instance = this.#instanceCache.get(id);

		if (!instance) {
			instance = new WorkspaceInstance(id, this);
			this.#instanceCache.set(id, instance);
		}

		return instance;
	}
}
