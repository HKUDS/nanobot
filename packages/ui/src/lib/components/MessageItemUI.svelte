<script lang="ts">
	import type { Attachment, ChatResult, ChatMessageItemResource } from '$lib/types';
	import React from 'react';
	import ReactDOM from 'react-dom/client';
	import {
		UIResourceRenderer,
		basicComponentLibrary,
		remoteButtonDefinition,
		remoteTextDefinition,
		remoteCardDefinition,
		remoteImageDefinition,
		remoteStackDefinition,
		type UIActionResult
	} from '@mcp-ui/client';
	import { onMount } from 'svelte';

	interface Props {
		item: ChatMessageItemResource;
		onSend?: (message: string, attachments?: Attachment[]) => Promise<ChatResult | void>;
		style?: Record<string, string>;
	}

	let { item, onSend, style = {} }: Props = $props();
	let container: HTMLDivElement;
	const iFrameRef = $state(React.createRef<HTMLIFrameElement>());

	$effect(() => {
		if (iFrameRef.current) {
			// iFrameRef.current.classList.add('mx-auto');
			// console.log('Iframe ref:', iFrameRef.current);
		}
	});

	async function onUIAction(e: UIActionResult) {
		console.log('UI Action', e);
		switch (e.type) {
			case 'intent':
				if (
					e.payload.intent === 'link' &&
					e.payload.params?.url &&
					typeof e.payload.params.url === 'string'
				) {
					window.open(e.payload.params.url, '_blank');
				} else {
					console.log('UI Action:', e);
					onSend?.(JSON.stringify(e));
				}
				break;
			case 'tool':
				console.log('UI Action:', e);
				if (onSend) {
					const reply = await onSend(JSON.stringify(e));
					if (reply) {
						for (const item of reply.message?.items || []) {
							if (item.type === 'tool' && item.output) {
								console.log('Tool output:', $state.snapshot(item.output));
								return $state.snapshot(item.output);
							}
						}
					}
				}
				break;
			case 'prompt':
			case 'notify':
				console.log('UI Action:', e);
				onSend?.(JSON.stringify(e));
				break;
			case 'link':
				window.open(e.payload.url, '_blank');
				break;
		}
	}

	onMount(() => {
		const root = ReactDOM.createRoot(container);
		root.render(
			React.createElement(UIResourceRenderer, {
				onUIAction,
				resource: $state.snapshot(item.resource),
				remoteDomProps: {
					library: basicComponentLibrary,
					remoteElements: [
						remoteButtonDefinition,
						remoteTextDefinition,
						remoteCardDefinition,
						remoteImageDefinition,
						remoteStackDefinition
					]
				},
				htmlProps: {
					style: {
						...style
					},
					autoResizeIframe: true,
					iframeProps: {
						ref: iFrameRef
					}
				}
			})
		);
	});
</script>

<div bind:this={container} class="contents"></div>
