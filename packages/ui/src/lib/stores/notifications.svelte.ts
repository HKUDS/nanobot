import type { Notification } from '$lib/types';
import { SvelteDate } from 'svelte/reactivity';

export class NotificationStore {
	notifications = $state<Notification[]>([]);

	add(notification: Omit<Notification, 'id' | 'timestamp'>): string {
		const id = crypto.randomUUID();
		const newNotification: Notification = {
			...notification,
			id,
			timestamp: new SvelteDate(),
			autoClose:
				typeof notification.autoClose === 'boolean'
					? notification.autoClose
					: notification.type !== 'error',
			duration: notification.duration || (notification.type === 'error' ? 0 : 5000) // errors don't auto-close
		};

		this.notifications.push(newNotification);

		// Auto-dismiss if configured
		if (newNotification.autoClose && newNotification.duration && newNotification.duration > 0) {
			setTimeout(() => {
				this.remove(id);
			}, newNotification.duration);
		}

		return id;
	}

	remove(id: string): void {
		this.notifications = this.notifications.filter((n) => n.id !== id);
	}

	clear(): void {
		this.notifications = [];
	}

	// Convenience methods
	success(title: string, message?: string, duration?: number): string {
		return this.add({ type: 'success', title, message, duration });
	}

	error(title: string, message?: string): string {
		return this.add({ type: 'error', title, message, autoClose: false });
	}

	warning(title: string, message?: string, duration?: number): string {
		return this.add({ type: 'warning', title, message, duration });
	}

	info(title: string, message?: string, duration?: number): string {
		return this.add({ type: 'info', title, message, duration });
	}
}
