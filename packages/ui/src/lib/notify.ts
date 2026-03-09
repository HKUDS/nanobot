import { getNotificationContext } from '$lib/context/notifications.svelte';

export function logError(error: unknown) {
	try {
		const notifications = getNotificationContext();
		notifications.error('API Error', error?.toString());
	} catch {
		// If context is not available (e.g., during SSR), just log
		console.error('MCP Tool Error:', error);
	}
	console.error('Error:', error);
}
