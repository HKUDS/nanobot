import { logError } from "$lib/notify";
import {
	type InitializationResult,
	type ResourceContents,
	type Resources,
	UIPath,
} from "$lib/types";

interface JSONRPCRequest {
	jsonrpc: "2.0";
	id: string;
	method: string;
	params?: unknown;
}

interface JSONRPCResponse {
	jsonrpc: "2.0";
	id: string;
	result?: unknown;
	error?: {
		code: number;
		message: string;
		data?: unknown;
	};
}

interface StoredSession {
	sessionId: string;
	initializeResult?: InitializationResult;
}

// This is a simple MCP client that works for specifically how nanobot will reply. It makes
// certain assumptions about session support and non-SSE responses to POSTs.
export class SimpleClient {
	readonly #url: string;
	readonly #fetcher: typeof fetch;
	#sessionId?: string;
	#initializeResult?: InitializationResult;
	#initializationPromise?: Promise<void>;
	readonly #externalSession: boolean;
	#sseConnection?: EventSource;
	#sseSubscriptions = new Map<
		string,
		Set<(resource: ResourceContents) => void>
	>();

	constructor(opts?: {
		path?: string;
		baseUrl?: string;
		fetcher?: typeof fetch;
		workspaceId?: string;
		workspaceShared?: boolean;
		sessionId?: string;
	}) {
		const baseUrl = opts?.baseUrl || "";
		const path = opts?.path || UIPath;
		this.#url = `${baseUrl}${path}`;
		this.#fetcher = opts?.fetcher || fetch;
		if (opts?.workspaceId) {
			this.#url += `${this.#url.includes("?") ? "&" : "?"}workspace=${opts.workspaceId}`;
			if (opts.workspaceShared) {
				this.#url += `&shared=true`;
			}
		}

		// If sessionId provided in options, use it and mark as external
		if (opts?.sessionId) {
			this.#sessionId = opts.sessionId === "new" ? undefined : opts.sessionId;
			this.#externalSession = true;
		} else {
			// Load session data from localStorage
			const stored = this.#getStoredSession();
			if (stored) {
				this.#sessionId = stored.sessionId;
				this.#initializeResult = stored.initializeResult;
			}
			this.#externalSession = false;
		}
	}

	async deleteSession(): Promise<void> {
		try {
			if (!this.#sessionId) {
				return;
			}
			await this.#fetcher(this.#url, {
				method: "DELETE",
				headers: {
					"Mcp-Session-Id": this.#sessionId,
				},
			});
		} finally {
			this.#clearSession();
		}
	}

	#getStoredSession(): StoredSession | undefined {
		if (typeof window === "undefined" || typeof localStorage === "undefined") {
			return undefined;
		}
		const stored = localStorage.getItem(`mcp-session-${this.#url}`);
		if (!stored) {
			return undefined;
		}
		try {
			return JSON.parse(stored) as StoredSession;
		} catch (e) {
			console.error("[SimpleClient] Failed to parse stored session:", e);
			return undefined;
		}
	}

	#storeSession(sessionId: string, initializeResult?: InitializationResult) {
		if (typeof window === "undefined" || typeof localStorage === "undefined") {
			return;
		}
		const session: StoredSession = {
			sessionId,
			initializeResult,
		};
		localStorage.setItem(`mcp-session-${this.#url}`, JSON.stringify(session));
	}

	#clearSession() {
		if (typeof window === "undefined" || typeof localStorage === "undefined") {
			return;
		}
		localStorage.removeItem(`mcp-session-${this.#url}`);
		this.#sessionId = undefined;
		this.#initializeResult = undefined;
		// Close SSE connection if it's open
		if (this.#sseConnection) {
			this.#sseConnection.close();
			this.#sseConnection = undefined;
		}
		this.#sseSubscriptions.clear();
	}

	async getSessionDetails(): Promise<{
		id: string;
		initializeResult?: InitializationResult;
	}> {
		return {
			id: await this.#ensureSession(),
			initializeResult: this.#initializeResult,
		};
	}

	async #initialize(): Promise<void> {
		// If already initializing, wait for that to complete
		if (this.#initializationPromise) {
			return this.#initializationPromise;
		}

		this.#initializationPromise = (async () => {
			try {
				// Step 1: Send initialize request
				const initRequest: JSONRPCRequest = {
					jsonrpc: "2.0",
					id: crypto.randomUUID(),
					method: "initialize",
					params: {
						protocolVersion: "2024-11-05",
						capabilities: {},
						clientInfo: {
							name: "nanobot-ui",
							version: "0.0.1",
						},
					},
				};

				const initResp = await this.#fetcher(this.#url, {
					method: "POST",
					headers: {
						"Content-Type": "application/json",
					},
					body: JSON.stringify(initRequest),
				});

				if (!initResp.ok) {
					throw new Error(
						`Initialize failed: ${initResp.status} ${initResp.statusText}`,
					);
				}

				// Extract session ID from response header
				const sessionId = initResp.headers.get("Mcp-Session-Id");
				if (!sessionId) {
					throw new Error("No Mcp-Session-Id header in initialize response");
				}

				// Parse response to check for errors
				const initData = (await initResp.json()) as JSONRPCResponse;
				if (initData.error) {
					throw new Error(`Initialize error: ${initData.error}`);
				}

				// Store session ID and initialize result
				this.#sessionId = sessionId;
				this.#initializeResult = initData.result as InitializationResult;
				if (!this.#externalSession) {
					this.#storeSession(sessionId, this.#initializeResult);
				}

				// Step 2: Send initialized notification
				const initializedRequest: JSONRPCRequest = {
					jsonrpc: "2.0",
					id: crypto.randomUUID(),
					method: "notifications/initialized",
					params: {},
				};

				const initializedResp = await this.#fetcher(this.#url, {
					method: "POST",
					headers: {
						"Content-Type": "application/json",
						"Mcp-Session-Id": sessionId,
					},
					body: JSON.stringify(initializedRequest),
				});

				if (!initializedResp.ok) {
					throw new Error(
						`Initialized notification failed: ${initializedResp.status} ${initializedResp.statusText}`,
					);
				}
			} finally {
				this.#initializationPromise = undefined;
			}
		})();

		return this.#initializationPromise;
	}

	async #ensureSession(): Promise<string> {
		if (!this.#sessionId) {
			await this.#initialize();
		}
		if (!this.#sessionId) {
			throw new Error("Failed to establish session");
		}
		return this.#sessionId;
	}

	async reply(id: string | number, result: unknown): Promise<void> {
		const sessionId = await this.#ensureSession();

		const resp = await this.#fetcher(this.#url, {
			method: "POST",
			headers: {
				"Content-Type": "application/json",
				"Mcp-Session-Id": sessionId,
			},
			body: JSON.stringify({
				jsonrpc: "2.0",
				id,
				result,
			}),
		});

		// We expect a 204 No Content response or 202
		if (resp.status === 204 || resp.status === 202) {
			return;
		}

		if (!resp.ok) {
			const text = await resp.text();
			logError(`reply: ${resp.status}: ${resp.statusText}: ${text}`);
			throw new Error(text);
		}

		try {
			// check for a protocol error
			const data = (await resp.json()) as JSONRPCResponse;
			if (data.error) {
				logError(data.error);
				throw Error(`${data.error.message}: ${JSON.stringify(data.error)}`);
			}
		} catch (e) {
			// If it's already an Error, rethrow it
			if (e instanceof Error && e.message !== "Unexpected end of JSON input") {
				throw e;
			}
			// Otherwise ignore JSON parse errors
			console.debug("[SimpleClient] Error parsing JSON in reply:", e);
		}
	}

	async notify(method: string, params: unknown): Promise<void> {
		const sessionId = await this.#ensureSession();

		// Notifications don't have an id field per JSON-RPC spec
		const notification = {
			jsonrpc: "2.0" as const,
			method,
			params,
		};

		// Build query string for access logs
		const [basePath, existingQuery] = this.#url.split("?");
		const queryParams = new URLSearchParams(existingQuery || "");
		queryParams.set("method", method);
		const url = `${basePath}?${queryParams.toString()}`;

		const resp = await this.#fetcher(url, {
			method: "POST",
			headers: {
				"Content-Type": "application/json",
				"Mcp-Session-Id": sessionId,
			},
			body: JSON.stringify(notification),
		});

		// Notifications typically return 204 No Content or 202 Accepted
		if (resp.status === 204 || resp.status === 202) {
			return;
		}

		if (!resp.ok) {
			const text = await resp.text();
			logError(`notify: ${resp.status}: ${resp.statusText}: ${text}`);
			// Don't throw - notifications are fire-and-forget
		}
	}

	async exchange(
		method: string,
		params: unknown,
		opts?: { abort?: AbortController; requestId?: string },
	): Promise<{ result: unknown; requestId: string }> {
		const sessionId = await this.#ensureSession();

		const request: JSONRPCRequest = {
			jsonrpc: "2.0",
			id: opts?.requestId ?? crypto.randomUUID(),
			method,
			params,
		};

		// Build query string for access logs
		// Parse the URL to extract existing query params
		const [basePath, existingQuery] = this.#url.split("?");
		const queryParams = new URLSearchParams(existingQuery || "");

		queryParams.set("method", method);

		// If this is a tools/call, add the tool name to the query string
		if (
			method === "tools/call" &&
			params &&
			typeof params === "object" &&
			"name" in params
		) {
			queryParams.set("toolcallname", String(params.name));
		}

		const url = `${basePath}?${queryParams.toString()}`;

		const resp = await this.#fetcher(url, {
			method: "POST",
			headers: {
				"Content-Type": "application/json",
				"Mcp-Session-Id": sessionId,
			},
			signal: opts?.abort?.signal,
			body: JSON.stringify(request),
		});

		// Handle 404 - session expired or invalid
		if (resp.status === 404) {
			// If this is an external session, don't try to recreate it
			if (this.#externalSession) {
				throw new Error(
					"Session not found (404). External sessions cannot be recreated.",
				);
			}
			this.#clearSession();
			// Retry once with new session
			return this.exchange(method, params, { abort: opts?.abort, requestId: request.id });
		}

		if (!resp.ok) {
			const text = await resp.text();
			logError(`exchange: ${resp.status}: ${resp.statusText}: ${text}`);
			throw new Error(text);
		}

		const data = (await resp.json()) as JSONRPCResponse;
		if (data.error) {
			logError(data.error);
			throw new Error(`${data.error.message}: ${JSON.stringify(data.error)}`);
		}

		return { result: data.result, requestId: request.id };
	}

	async callMCPTool<T>(
		name: string,
		opts?: {
			payload?: unknown;
			progressToken?: string;
			async?: boolean;
			abort?: AbortController;
			requestId?: string;
		},
	): Promise<{ result: T; requestId: string }> {
		const { result, requestId } = await this.exchange(
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

		// If the result has a structuredResult field, use that, otherwise return the full response
		let finalResult: T;
		if (result && typeof result === "object" && "structuredContent" in result) {
			finalResult = (result as { structuredContent: T }).structuredContent;
		} else {
			finalResult = result as T;
		}

		return { result: finalResult, requestId };
	}

	async listResources<T extends Resources = Resources>(opts?: {
		prefix?: string | string[];
		abort?: AbortController;
	}): Promise<T> {
		const prefixes = opts?.prefix
			? Array.isArray(opts.prefix)
				? opts.prefix
				: [opts.prefix]
			: undefined;

		const { result } = await this.exchange(
			"resources/list",
			{
				...(prefixes && {
					_meta: {
						"ai.nanobot": {
							prefix: prefixes.length === 1 ? prefixes[0] : prefixes,
						},
					},
				}),
			},
			{ abort: opts?.abort },
		);

		const typedResult = result as T;

		if (prefixes) {
			return {
				...typedResult,
				resources: typedResult.resources.filter(({ uri }) =>
					prefixes.some((prefix) => uri.startsWith(prefix)),
				),
			};
		}

		return typedResult;
	}

	async readResource(
		uri: string,
		opts?: { abort?: AbortController },
	): Promise<{ contents: ResourceContents[] }> {
		const { result } = await this.exchange(
			"resources/read",
			{ uri },
			{ abort: opts?.abort },
		);
		return result as { contents: ResourceContents[] };
	}

	/**
	 * Ensure SSE connection is established
	 */
	async #ensureSSEConnection(): Promise<void> {
		if (
			this.#sseConnection &&
			this.#sseConnection.readyState !== EventSource.CLOSED
		) {
			return;
		}

		// Ensure we have a session before connecting
		await this.#ensureSession();

		// Build SSE URL
		const [basePath, existingQuery] = this.#url.split("?");
		const queryParams = new URLSearchParams(existingQuery || "");
		queryParams.set("stream", "true");
		const sseUrl = `${basePath}?${queryParams.toString()}`;

		// Create EventSource connection
		this.#sseConnection = new EventSource(sseUrl);

		// Handle incoming messages
		this.#sseConnection.onmessage = (event) => {
			try {
				const message = JSON.parse(event.data) as JSONRPCResponse & {
					method?: string;
					params?: { uri?: string };
				};

				// Check if this is a resource update notification
				if (
					message.method === "notifications/resources/updated" &&
					message.params?.uri
				) {
					const uri = message.params.uri;

					// Find all subscriptions that match this URI prefix
					for (const [prefix, callbacks] of this.#sseSubscriptions.entries()) {
						if (uri.startsWith(prefix)) {
							// Fetch the updated resource details
							this.#fetchResourceDetails(uri).then((resource) => {
								if (resource) {
									callbacks.forEach((callback) => callback(resource));
								}
							});
						}
					}
				}
			} catch (e) {
				console.error("[SimpleClient] Failed to parse SSE message:", e);
			}
		};

		this.#sseConnection.onerror = (error) => {
			console.error("[SimpleClient] SSE connection error:", error);
			// Connection will automatically try to reconnect
		};

		this.#sseConnection.onopen = () => {
			console.log("[SimpleClient] SSE connection established");
		};
	}

	/**
	 * Fetch resource details for a given URI
	 */
	async #fetchResourceDetails(uri: string): Promise<ResourceContents | null> {
		try {
			// Use resources/read to get the resource details
			const result = await this.readResource(uri);
			if (result.contents?.length) {
				return result.contents[0] as ResourceContents;
			}
		} catch (e) {
			logError(
				`[SimpleClient] Failed to fetch resource ${uri}: ${e instanceof Error ? e.message : String(e)}`,
			);
		}
		return null;
	}

	/**
	 * Watch for resource changes with a given prefix.
	 * Returns a cleanup function to stop watching.
	 *
	 * @param prefix - URI prefix to watch (e.g., 'workspace://')
	 * @param callback - Called when a resource changes with the updated resource
	 * @returns Cleanup function to stop watching
	 */
	watchResource(
		prefix: string,
		callback: (resource: ResourceContents) => void,
	): () => void {
		// Add callback to subscriptions
		if (!this.#sseSubscriptions.has(prefix)) {
			this.#sseSubscriptions.set(prefix, new Set());
		}
		this.#sseSubscriptions.get(prefix)!.add(callback);

		// Ensure SSE connection is established
		this.#ensureSSEConnection().then(async () => {
			// Subscribe to resource changes for this prefix
			try {
				await this.exchange("resources/subscribe", { uri: prefix });
				console.log(
					`[SimpleClient] Subscribed to resources with prefix: ${prefix}`,
				);
			} catch (e) {
				console.error(`[SimpleClient] Failed to subscribe to ${prefix}:`, e);
			}
		});

		// Return cleanup function
		return () => {
			const callbacks = this.#sseSubscriptions.get(prefix);
			if (callbacks) {
				callbacks.delete(callback);
				if (callbacks.size === 0) {
					this.#sseSubscriptions.delete(prefix);
					// Optionally unsubscribe from server
					this.exchange("resources/unsubscribe", { uri: prefix }).catch((e) => {
						console.error(
							`[SimpleClient] Failed to unsubscribe from ${prefix}:`,
							e,
						);
					});
				}
			}
			console.log(
				`[SimpleClient] Stopped watching resources with prefix: ${prefix}`,
			);

			// Close SSE connection if no more subscriptions
			if (this.#sseSubscriptions.size === 0 && this.#sseConnection) {
				this.#sseConnection.close();
				this.#sseConnection = undefined;
			}
		};
	}
}
