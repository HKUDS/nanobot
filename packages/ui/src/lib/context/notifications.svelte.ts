import { getContext, setContext } from 'svelte';
import type { NotificationStore } from '$lib/stores/notifications.svelte';

const NOTIFICATIONS_KEY = Symbol('notifications');

export function setNotificationContext(notifications: NotificationStore) {
	setContext(NOTIFICATIONS_KEY, notifications);
}

export function getNotificationContext(): NotificationStore {
	return getContext<NotificationStore>(NOTIFICATIONS_KEY);
}
