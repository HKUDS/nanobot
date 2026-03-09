import type { ChatService } from '$lib/chat.svelte';

export interface Agent {
	id: string;
	name?: string;
	description?: string;
	icon?: string;
	iconDark?: string;
	starterMessages?: string[];
	current?: boolean;
}

export interface Agents {
	agents: Agent[];
}

export interface Chat {
	id: string;
	title: string;
	created: string;
	visibility?: 'public' | 'private';
	readonly?: boolean;
	workflowURIs?: string[];
}

export interface ChatMessage {
	id: string;
	created?: string;
	role: 'user' | 'assistant';
	items?: ChatMessageItem[];
	hasMore?: boolean;
}

export type ChatMessageItem = ToolOutputItem | ChatMessageItemToolCall | ChatMessageItemReasoning;

export type ToolOutputItem =
	| ChatMessageItemImage
	| ChatMessageItemAudio
	| ChatMessageItemText
	| ChatMessageItemResource
	| ChatMessageItemResourceLink;

export interface ChatMessageItemToolCall extends ChatMessageItemBase {
	type: 'tool';
	arguments?: string;
	callID?: string;
	name?: string;
	output?: {
		isError?: boolean;
		content?: ToolOutputItem[];
		structuredContent?: unknown;
	};
}

export interface ChatMessageItemImage extends ChatMessageItemBase {
	type: 'image';
	data: string;
	mimeType: string;
}

export interface ChatMessageItemAudio extends ChatMessageItemBase {
	type: 'audio';
	data: string;
	mimeType: string;
}

export interface ChatMessageItemText extends ChatMessageItemBase {
	type: 'text';
	text: string;
}

export interface ChatMessageItemResourceLink extends ChatMessageItemBase {
	type: 'resource_link';
	name?: string;
	description?: string;
	uri: string;
	mimeType?: string;
}

export interface ChatMessageItemReasoning extends ChatMessageItemBase {
	type: 'reasoning';
	summary?: {
		text: string;
	}[];
}

export interface ChatMessageItemResource extends ChatMessageItemBase {
	type: 'resource';
	resource: {
		uri: string;
		name?: string;
		description?: string;
		title?: string;
		mimeType: string;
		size?: number;
		text?: string;
		blob?: string;
		annotations?: {
			audience?: string[];
			priority?: number;
			lastModified?: string;
		};
		_meta?: { [key: string]: unknown };
	};
}

export interface ChatMessageItemBase {
	id: string;
	hasMore?: boolean;
	_meta?: { [key: string]: unknown };
	type:
		| 'text'
		| 'image'
		| 'audio'
		| 'toolCall'
		| 'resource'
		| 'resource_link'
		| 'tool'
		| 'reasoning';
}

export interface ChatRequest {
	id: string;
	threadId: string;
	message: string;
	agent?: string;
	attachments?: Attachment[];
}

export interface Attachment {
	name?: string;
	uri: string;
	mimeType?: string;
}

export interface ChatResult {
	message: ChatMessage;
}

export interface Event {
	id?: string | number;
	type:
		| 'message'
		| 'history-start'
		| 'history-end'
		| 'chat-in-progress'
		| 'chat-done'
		| 'error'
		| 'elicitation/create';
	message?: ChatMessage;
	data?: unknown;
	error?: string;
}

export interface Notification {
	id: string;
	type: 'success' | 'error' | 'warning' | 'info';
	title: string;
	message?: string;
	timestamp: Date;
	autoClose?: boolean;
	duration?: number; // milliseconds
}

export interface Prompts {
	prompts: Prompt[];
}

export interface Resources {
	resources: Resource[];
}

export interface ResourceContents {
	uri: string;
	mimeType?: string;
	text?: string;
	blob?: string;
	_meta?: { [key: string]: unknown };
}

export interface Resource extends BaseMetadata, Icons {
	uri: string;
	description?: string;
	mimeType?: string;
	annotations?: {
		audience?: string[];
		priority?: number;
		lastModified?: string;
	};
	size?: number;
	_meta?: { [key: string]: unknown };
}

export interface Icons {
	/**
	 * Optional set of sized icons that the client can display in a user interface.
	 *
	 * Clients that support rendering icons MUST support at least the following MIME types:
	 * - `image/png` - PNG images (safe, universal compatibility)
	 * - `image/jpeg` (and `image/jpg`) - JPEG images (safe, universal compatibility)
	 *
	 * Clients that support rendering icons SHOULD also support:
	 * - `image/svg+xml` - SVG images (scalable but requires security precautions)
	 * - `image/webp` - WebP images (modern, efficient format)
	 */
	icons?: Icon[];
}

export interface Icon {
	/**
	 * A standard URI pointing to an icon resource. May be an HTTP/HTTPS URL or a
	 * `data:` URI with Base64-encoded image data.
	 *
	 * Consumers SHOULD takes steps to ensure URLs serving icons are from the
	 * same domain as the client/server or a trusted domain.
	 *
	 * Consumers SHOULD take appropriate precautions when consuming SVGs as they can contain
	 * executable JavaScript.
	 *
	 * @format uri
	 */
	src: string;

	/**
	 * Optional MIME type override if the source MIME type is missing or generic.
	 * For example: `"image/png"`, `"image/jpeg"`, or `"image/svg+xml"`.
	 */
	mimeType?: string;

	/**
	 * Optional array of strings that specify sizes at which the icon can be used.
	 * Each string should be in WxH format (e.g., `"48x48"`, `"96x96"`) or `"any"` for scalable formats like SVG.
	 *
	 * If not provided, the client should assume that the icon can be used at any size.
	 */
	sizes?: string[];

	/**
	 * Optional specifier for the theme this icon is designed for. `light` indicates
	 * the icon is designed to be used with a light background, and `dark` indicates
	 * the icon is designed to be used with a dark background.
	 *
	 * If not provided, the client should assume the icon can be used with any theme.
	 */
	theme?: 'light' | 'dark';
}

export interface BaseMetadata {
	name: string;
	title?: string;
}

export interface Prompt extends BaseMetadata {
	description?: string;
	arguments?: PromptArgument[];
	_meta?: { [key: string]: unknown };
}

export interface PromptArgument extends BaseMetadata {
	description?: string;
	required?: boolean;
}

export interface Elicitation {
	id: string | number;
	message: string;
	requestedSchema: {
		type: 'object';
		properties: {
			[key: string]: PrimitiveSchemaDefinition;
		};
		required?: string[];
	};
	_meta?: { [key: string]: unknown };
}

export interface ElicitationResult {
	action: 'accept' | 'decline' | 'cancel';
	content?: { [key: string]: string | number | boolean };
}

export type PrimitiveSchemaDefinition = StringSchema | NumberSchema | BooleanSchema | EnumSchema;

export interface StringSchema {
	type: 'string';
	title?: string;
	description?: string;
	minLength?: number;
	maxLength?: number;
	format?: 'email' | 'uri' | 'date' | 'date-time';
}

export interface NumberSchema {
	type: 'number' | 'integer';
	title?: string;
	description?: string;
	minimum?: number;
	maximum?: number;
}

export interface BooleanSchema {
	type: 'boolean';
	title?: string;
	description?: string;
	default?: boolean;
}

export interface EnumSchema {
	type: 'string';
	title?: string;
	description?: string;
	enum: string[];
	enumNames?: string[]; // Display names for enum values
}

export const MessageMimeType = 'application/vnd.nanobot.chat.message+json';
export const HistoryMimeType = 'application/vnd.nanobot.chat.history+json';
export const ToolResultMimeType = 'application/vnd.nanobot.tool.result+json';

export interface UploadedFile {
	id: string;
	file: File;
	uri: string;
	mimeType?: string;
}

export interface UploadingFile {
	id: string;
	file: File;
	controller?: AbortController;
}

// Workspace types
export const SessionMimeType = 'application/vnd.nanobot.session+json';

// Forward declaration for WorkspaceClient
export type { SimpleClient } from './mcpclient';

export interface Workspace extends Icons {
	id: string;
	name: string;
	created: string;
	order?: number;
	color?: string;
}

export interface Session {
	id: string;
	title: string;
}

export interface SessionDetails {
	id: string;
	title?: string;
	createdAt: string;
	updatedAt?: string;
	workspaceId?: string;
	sessionWorkspaceId?: string;
}

export interface WorkspaceFile {
	name: string;
}

export interface WorkspaceClient {
	// Properties
	readonly id: string;
	readonly workspace: Workspace;
	readonly files: WorkspaceFile[];
	readonly sessions: Session[];
	readonly loading: boolean;

	readFile(path: string): Promise<Blob>;
	writeFile(path: string, data: Blob | string): Promise<void>;
	createFile(path: string, data: Blob | string): Promise<void>;
	deleteFile(path: string): Promise<void>;
	deleteSession(sessionId: string): Promise<void>;
	getSessionDetails(sessionId: string): Promise<SessionDetails>;
	getSession(sessionId: string): Promise<ChatService>;
	newSession(opts?: { editor?: boolean }): Promise<ChatService>;
}

export interface InitializationResult {
	capabilities?: {
		experimental?: {
			'ai.nanobot'?: {
				session?: {
					ui?: boolean;
					workspace?: {
						id?: string;
						baseUri?: string;
						base?: string;
						supported?: boolean;
					};
				};
			};
		};
	};
}

export const UIPath = '/mcp/ui';
export const ChatPath = '/mcp/chat';
