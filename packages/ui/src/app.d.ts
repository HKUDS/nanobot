// See https://svelte.dev/docs/kit/types#app.d.ts
// for information about these interfaces
import type { ChatService } from '$lib/chat.svelte';

declare global {
	namespace App {
		// interface Error {}
		// interface Locals {}
		interface PageData {
			chat?: ChatService;
		}
		// interface PageState {}
		// interface Platform {}
	}
}

export {};
