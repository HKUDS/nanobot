<script lang="ts">
	import '$lib/../app.css';
	import { ChatService } from '$lib/chat.svelte';
	import { onDestroy, onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { resolve } from '$app/paths';
	import ThreadFromChat from "$lib/components/ThreadFromChat.svelte";

	const chat = new ChatService();
	let doClose = true;

	$effect(() => {
		if (chat.chatId) {
			doClose = false;
			page.data.chat = chat;
			goto(resolve(`/c/${chat.chatId}`));
		}
	});

	onMount(() => {
		if (window.location.search.includes('new')) {
			chat.newChat();
		}
	});

	onDestroy(() => {
		if (doClose) {
			chat.close();
		}
	});
</script>

<svelte:head>
	{#if chat.agent?.name}
		<title>{chat.agent.name}</title>
	{:else}
		<title>Nanobot</title>
	{/if}
</svelte:head>

<ThreadFromChat {chat} />
