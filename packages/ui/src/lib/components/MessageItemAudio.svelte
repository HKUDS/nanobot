<script lang="ts">
	import type { ChatMessageItemAudio } from '$lib/types';

	interface Props {
		item: ChatMessageItemAudio;
	}

	let { item }: Props = $props();
</script>

<div class="mb-3 rounded-lg bg-base-200 p-3">
	<audio controls class="w-full">
		<source src="data:{item.mimeType};base64,{item.data}" type={item.mimeType} />
		Your browser does not support the audio element.
	</audio>
</div>
