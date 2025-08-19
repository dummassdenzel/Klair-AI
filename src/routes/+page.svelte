<script>
	let files = [];
	let messages = [];
	let newMessage = '';

	function handleFileUpload(event) {
		files = [...files, ...event.target.files];
	}

	async function handleSendMessage() {
		if (!newMessage.trim()) return;

		messages = [...messages, { text: newMessage, sender: 'user' }];

		// Simulate AI response
		const aiResponse = `Echo: ${newMessage}`;
		newMessage = '';

		await new Promise(res => setTimeout(res, 500));

		messages = [...messages, { text: aiResponse, sender: 'ai' }];
	}
</script>

<div class="container mx-auto p-4 grid grid-cols-3 gap-4 h-screen">

	<!-- File Management Column -->
	<div class="col-span-1 bg-gray-100 p-4 rounded-lg flex flex-col">
		<h2 class="text-xl font-bold mb-4">Filebase</h2>
		
		<!-- File Upload -->
		<div class="mb-4">
			<label for="file-upload" class="block text-sm font-medium text-gray-700">Upload Files</label>
			<div class="mt-1 flex items-center">
				<input type="file" id="file-upload" multiple on:change={handleFileUpload} class="block w-full text-sm text-gray-500 file:mr-4 file:py-2 file:px-4 file:rounded-full file:border-0 file:text-sm file:font-semibold file:bg-violet-50 file:text-violet-700 hover:file:bg-violet-100"/>
			</div>
		</div>

		<!-- File List -->
		<div class="flex-grow overflow-y-auto">
			<h3 class="text-lg font-semibold mb-2">Uploaded Files</h3>
			<ul class="space-y-2">
				{#each files as file (file.name)}
					<li class="p-2 bg-white rounded-md shadow-sm text-sm">{file.name}</li>
				{:else}
					<p class="text-gray-500 text-sm">No files uploaded yet.</p>
				{/each}
			</ul>
		</div>
	</div>

	<!-- Chat Column -->
	<div class="col-span-2 bg-white p-4 rounded-lg flex flex-col h-full">
		<h1 class="text-2xl font-bold mb-4 text-center">Klair AI Assistant</h1>
		
		<!-- Message Display -->
		<div class="flex-grow mb-4 overflow-y-auto p-4 bg-gray-50 rounded-lg">
			{#each messages as message}
				<div class="chat {message.sender === 'user' ? 'chat-end' : 'chat-start'}">
					<div class="chat-bubble {message.sender === 'user' ? 'chat-bubble-primary' : ''}">
						{message.text}
					</div>
				</div>
			{/each}
		</div>

		<!-- Message Input -->
		<div class="flex">
			<input 
				type="text" 
				bind:value={newMessage} 
				on:keydown={(e) => e.key === 'Enter' && handleSendMessage()}
				placeholder="Type your message..." 
				class="input input-bordered w-full mr-2"
			/>
			<button on:click={handleSendMessage} class="btn btn-primary">Send</button>
		</div>
	</div>

</div>
<p>Visit <a href="https://svelte.dev/docs/kit">svelte.dev/docs/kit</a> to read the documentation</p>
