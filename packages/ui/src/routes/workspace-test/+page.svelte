<script lang="ts">
  import '$lib/../app.css';
  import {WorkspaceService, type WorkspaceInstance} from '$lib/workspace.svelte';
  import {onMount} from 'svelte';
  import {
    AlertCircle,
    RefreshCw,
    Plus,
    Edit,
    Trash2,
    X,
    Save,
    FileText,
    Download,
    MessageSquare,
    Info,
    List
  } from '@lucide/svelte';
  import type {SessionDetails} from "$lib/types";
  import type {ChatService} from '$lib/chat.svelte';
  import ThreadFromChat from "$lib/components/ThreadFromChat.svelte";

  const workspaceService = new WorkspaceService();

  let loading = $state(false);
  let error = $state<string | null>(null);
  let newWorkspaceName = $state('');
  let newWorkspaceColor = $state('#3b82f6');
  let newWorkspaceOrder = $state(0);

  // Edit mode state
  let editingWorkspaceId = $state<string | null>(null);
  let editName = $state('');
  let editColor = $state('');
  let editOrder = $state(0);

  // File operations state
  let selectedWorkspace = $state<WorkspaceInstance | null>(null);
  let newFileName = $state('');
  let newFileContent = $state('');
  let editingFilePath = $state<string | null>(null);
  let editFileContent = $state('');
  let fileReadContent = $state<{ path: string; content: string; mimeType: string } | null>(null);

  // Session info state
  let sessionInfo = $state<SessionDetails | null>(null);

  // Active session state
  let activeSession = $state<ChatService | null>(null);

  onMount(() => {
    loadWorkspaces();
  });

  async function loadWorkspaces() {
    loading = true;
    error = null;
    try {
      await workspaceService.load();
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
    } finally {
      loading = false;
    }
  }

  async function createWorkspace() {
    if (!newWorkspaceName.trim()) {
      error = 'Workspace name is required';
      return;
    }

    loading = true;
    error = null;
    try {
      await workspaceService.createWorkspace({
        name: newWorkspaceName,
        color: newWorkspaceColor,
        order: newWorkspaceOrder
      });

      // Reset form
      newWorkspaceName = '';
      newWorkspaceColor = '#3b82f6';
      newWorkspaceOrder = 0;
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
    } finally {
      loading = false;
    }
  }

  function startEdit(workspaceId: string) {
    const workspace = workspaceService.workspaces.find(w => w.id === workspaceId);
    if (workspace) {
      editingWorkspaceId = workspaceId;
      editName = workspace.name;
      editColor = workspace.color || '#3b82f6';
      editOrder = workspace.order || 0;
    }
  }

  function cancelEdit() {
    editingWorkspaceId = null;
    editName = '';
    editColor = '';
    editOrder = 0;
  }

  async function saveEdit(workspaceId: string) {
    if (!editName.trim()) {
      error = 'Workspace name is required';
      return;
    }

    const workspace = workspaceService.workspaces.find((w) => w.id === workspaceId);
    if (!workspace) {
      error = 'Workspace not found';
      return;
    }

    loading = true;
    error = null;
    try {
      await workspaceService.updateWorkspace({
        ...workspace,
        name: editName,
        color: editColor,
        order: editOrder
      });
      cancelEdit();
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
    } finally {
      loading = false;
    }
  }

  async function deleteWorkspace(workspaceId: string) {
    if (!confirm('Are you sure you want to delete this workspace?')) {
      return;
    }

    loading = true;
    error = null;
    try {
      await workspaceService.deleteWorkspace(workspaceId);
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
    } finally {
      loading = false;
    }
  }

  // File Operations
  function selectWorkspace(workspaceId: string) {
    selectedWorkspace = workspaceService.getWorkspace(workspaceId) as WorkspaceInstance;
    fileReadContent = null;
    editingFilePath = null;
    sessionInfo = null;

    // Scroll to file operations section after a brief delay
    setTimeout(() => {
      document.getElementById('file-operations')?.scrollIntoView({
        behavior: 'smooth',
        block: 'start'
      });
    }, 100);
  }

  async function createFile() {
    if (!selectedWorkspace || !newFileName.trim()) {
      error = 'Workspace and filename are required';
      return;
    }

    loading = true;
    error = null;
    try {
      await selectedWorkspace.createFile(newFileName, newFileContent);
      newFileName = '';
      newFileContent = '';
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
    } finally {
      loading = false;
    }
  }

  async function readFile(path: string) {
    if (!selectedWorkspace) return;

    loading = true;
    error = null;
    try {
      const blob = await selectedWorkspace.readFile(path);
      const content = await blob.text();
      fileReadContent = {
        path,
        content,
        mimeType: blob.type
      };
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
    } finally {
      loading = false;
    }
  }

  function startEditFile(path: string) {
    editingFilePath = path;
    // Load current content if available
    if (fileReadContent && fileReadContent.path === path) {
      editFileContent = fileReadContent.content;
    } else {
      editFileContent = '';
    }
  }

  async function updateFile(path: string) {
    if (!selectedWorkspace) return;

    loading = true;
    error = null;
    try {
      await selectedWorkspace.writeFile(path, editFileContent);
      editingFilePath = null;
      editFileContent = '';
      // Refresh the file content if it was being viewed
      if (fileReadContent && fileReadContent.path === path) {
        await readFile(path);
      }
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
    } finally {
      loading = false;
    }
  }

  function cancelEditFile() {
    editingFilePath = null;
    editFileContent = '';
  }

  async function deleteFile(path: string) {
    if (!selectedWorkspace) return;
    if (!confirm(`Are you sure you want to delete ${path}?`)) {
      return;
    }

    loading = true;
    error = null;
    try {
      await selectedWorkspace.deleteFile(path);
      // Clear read content if the deleted file was being viewed
      if (fileReadContent && fileReadContent.path === path) {
        fileReadContent = null;
      }
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
    } finally {
      loading = false;
    }
  }

  async function refreshFiles() {
    if (!selectedWorkspace) return;

    loading = true;
    error = null;
    try {
      await selectedWorkspace.load();
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
    } finally {
      loading = false;
    }
  }

  async function readSessionInfo(sessionId: string) {
    if (!selectedWorkspace) return;

    loading = true;
    error = null;
    try {
      sessionInfo = await selectedWorkspace.getSessionDetails(sessionId);
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
    } finally {
      loading = false;
    }
  }

  async function deleteSession(sessionId: string) {
    if (!selectedWorkspace) return;
    if (!confirm('Are you sure you want to delete this session? This action cannot be undone.')) {
      return;
    }

    loading = true;
    error = null;
    try {
      await selectedWorkspace.deleteSession(sessionId);

      // Clear session info if the deleted session was being viewed
      if (sessionInfo && sessionInfo.id === sessionId) {
        sessionInfo = null;
      }

      // Clear active session if it was deleted
      if (activeSession && activeSession.chatId === sessionId) {
        activeSession = null;
      }
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
    } finally {
      loading = false;
    }
  }

  async function createNewSession() {
    if (!selectedWorkspace) return;

    loading = true;
    error = null;
    try {
      activeSession = await selectedWorkspace.newSession({ editor: false });
      await refreshFiles(); // Refresh to show the new session
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
    } finally {
      loading = false;
    }
  }

  async function selectSession(sessionId: string) {
    if (!selectedWorkspace) return;

    loading = true;
    error = null;
    try {
      activeSession = await selectedWorkspace.getSession(sessionId);
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
    } finally {
      loading = false;
    }
  }
</script>

<svelte:head>
    <title>Workspace Test - Nanobot</title>
</svelte:head>

<div class="size-full flex">
    <!-- Left Panel - Workspace Management -->
    <div class="h-full overflow-auto p-8 {activeSession ? 'w-1/2 border-r border-base-300' : 'flex-1 mx-auto max-w-6xl'}">
        <h1 class="text-3xl font-bold mb-6">Workspace Management Test</h1>

        {#if error}
            <div class="alert alert-error mb-4">
                <AlertCircle class="h-6 w-6"/>
                <span>{error}</span>
            </div>
        {/if}

        <!-- Create Workspace Form -->
        <div class="card bg-base-200 shadow-xl mb-8">
            <div class="card-body">
                <h2 class="card-title">Create New Workspace</h2>
                <div class="form-control">
                    <label class="label" for="name">
                        <span class="label-text">Workspace Name</span>
                    </label>
                    <input
                            id="name"
                            type="text"
                            placeholder="Enter workspace name"
                            class="input input-bordered w-full"
                            bind:value={newWorkspaceName}
                    />
                </div>

                <div class="grid grid-cols-2 gap-4">
                    <div class="form-control">
                        <label class="label" for="color">
                            <span class="label-text">Color</span>
                        </label>
                        <input
                                id="color"
                                type="color"
                                class="input input-bordered w-full h-12"
                                bind:value={newWorkspaceColor}
                        />
                    </div>

                    <div class="form-control">
                        <label class="label" for="order">
                            <span class="label-text">Order</span>
                        </label>
                        <input
                                id="order"
                                type="number"
                                placeholder="0"
                                class="input input-bordered w-full"
                                bind:value={newWorkspaceOrder}
                        />
                    </div>
                </div>

                <div class="card-actions justify-end mt-4">
                    <button class="btn btn-primary" onclick={createWorkspace} disabled={loading}>
                        {#if loading}
                            <span class="loading loading-spinner"></span>
                        {:else}
                            <Plus class="h-5 w-5"/>
                        {/if}
                        Create Workspace
                    </button>
                </div>
            </div>
        </div>

        <!-- Workspace List -->
        <div class="flex justify-between items-center mb-4">
            <h2 class="text-2xl font-bold">Workspaces ({workspaceService.workspaces.length})</h2>
            <button class="btn btn-sm btn-outline" onclick={loadWorkspaces} disabled={loading}>
                {#if loading}
                    <span class="loading loading-spinner loading-sm"></span>
                {:else}
                    <RefreshCw class="h-4 w-4"/>
                {/if}
                Reload
            </button>
        </div>

        {#if loading && workspaceService.workspaces.length === 0}
            <div class="flex justify-center items-center p-12">
                <span class="loading loading-spinner loading-lg"></span>
            </div>
        {:else if workspaceService.workspaces.length === 0}
            <div class="alert alert-info">
                <AlertCircle class="h-6 w-6"/>
                <span>No workspaces found. Create one above!</span>
            </div>
        {:else}
            <div class="grid gap-4">
                {#each workspaceService.workspaces as workspace (workspace.id)}
                    <div class="card bg-base-100 shadow-xl border-l-4"
                         style="border-left-color: {workspace.color || '#3b82f6'}">
                        <div class="card-body">
                            {#if editingWorkspaceId === workspace.id}
                                <!-- Edit Mode -->
                                <div class="form-control">
                                    <label class="label">
                                        <span class="label-text">Name</span>
                                    </label>
                                    <input
                                            type="text"
                                            class="input input-bordered"
                                            bind:value={editName}
                                    />
                                </div>

                                <div class="grid grid-cols-2 gap-4">
                                    <div class="form-control">
                                        <label class="label">
                                            <span class="label-text">Color</span>
                                        </label>
                                        <input
                                                type="color"
                                                class="input input-bordered h-12"
                                                bind:value={editColor}
                                        />
                                    </div>

                                    <div class="form-control">
                                        <label class="label">
                                            <span class="label-text">Order</span>
                                        </label>
                                        <input
                                                type="number"
                                                class="input input-bordered"
                                                bind:value={editOrder}
                                        />
                                    </div>
                                </div>

                                <div class="card-actions justify-end mt-4">
                                    <button class="btn btn-ghost btn-sm" onclick={cancelEdit}>
                                        <X class="h-4 w-4"/>
                                        Cancel
                                    </button>
                                    <button class="btn btn-primary btn-sm" onclick={() => saveEdit(workspace.id)}
                                            disabled={loading}>
                                        <Save class="h-4 w-4"/>
                                        Save
                                    </button>
                                </div>
                            {:else}
                                <!-- View Mode -->
                                <div class="flex justify-between items-start">
                                    <div>
                                        <h3 class="card-title">{workspace.name}</h3>
                                        <div class="text-sm opacity-70 mt-2">
                                            <p><strong>ID:</strong> {workspace.id}</p>
                                            <p><strong>Order:</strong> {workspace.order || 0}</p>
                                            <p><strong>Created:</strong> {new Date(workspace.created).toLocaleString()}
                                            </p>
                                            {#if workspace.icons && workspace.icons.length > 0}
                                                <p><strong>Icons:</strong> {workspace.icons.length}</p>
                                            {/if}
                                        </div>
                                    </div>

                                    <div class="flex gap-2">
                                        <button
                                                class="btn btn-sm btn-outline btn-info"
                                                onclick={() => selectWorkspace(workspace.id)}
                                                disabled={loading}
                                        >
                                            <List class="h-4 w-4"/>
                                            Details
                                        </button>
                                        <button
                                                class="btn btn-sm btn-outline btn-primary"
                                                onclick={() => startEdit(workspace.id)}
                                                disabled={loading}
                                        >
                                            <Edit class="h-4 w-4"/>
                                            Edit
                                        </button>
                                        <button
                                                class="btn btn-sm btn-outline btn-error"
                                                onclick={() => deleteWorkspace(workspace.id)}
                                                disabled={loading}
                                        >
                                            <Trash2 class="h-4 w-4"/>
                                            Delete
                                        </button>
                                    </div>
                                </div>
                            {/if}
                        </div>
                    </div>
                {/each}
            </div>
        {/if}

        <!-- File Operations Section -->
        {#if selectedWorkspace}
            <div class="divider mt-12 mb-8"></div>

            <div id="file-operations" class="mb-8">
                <div class="flex justify-between items-center mb-4">
                    <div>
                        <h2 class="text-2xl font-bold">File Operations</h2>
                        <p class="text-sm opacity-70">Workspace: <strong>{selectedWorkspace.workspace.name}</strong></p>
                    </div>
                    <button class="btn btn-sm btn-ghost" onclick={() => {
					selectedWorkspace = null;
					sessionInfo = null;
				}}>
                        <X class="h-4 w-4"/>
                        Close
                    </button>
                </div>

                <!-- Create File Form -->
                <div class="card bg-base-200 shadow-xl mb-6">
                    <div class="card-body">
                        <h3 class="card-title text-lg">Create New File</h3>
                        <div class="form-control">
                            <label class="label" for="filename">
                                <span class="label-text">File Path</span>
                            </label>
                            <input
                                    id="filename"
                                    type="text"
                                    placeholder="e.g., notes.txt or docs/readme.md"
                                    class="input input-bordered w-full"
                                    bind:value={newFileName}
                            />
                        </div>

                        <div class="form-control">
                            <label class="label" for="filecontent">
                                <span class="label-text">Content</span>
                            </label>
                            <textarea
                                    id="filecontent"
                                    placeholder="Enter file content"
                                    class="textarea textarea-bordered w-full h-32"
                                    bind:value={newFileContent}
                            ></textarea>
                        </div>

                        <div class="card-actions justify-end mt-4">
                            <button class="btn btn-primary btn-sm" onclick={createFile} disabled={loading}>
                                {#if loading}
                                    <span class="loading loading-spinner loading-sm"></span>
                                {:else}
                                    <Plus class="h-4 w-4"/>
                                {/if}
                                Create File
                            </button>
                        </div>
                    </div>
                </div>

                <!-- Sessions List -->
                <div class="card bg-base-200 shadow-xl mb-6">
                    <div class="card-body">
                        <div class="flex justify-between items-center mb-2">
                            <h3 class="card-title text-lg">Sessions ({selectedWorkspace.sessions.length})</h3>
                            <div class="flex gap-2">
                                <button class="btn btn-sm btn-primary" onclick={createNewSession} disabled={loading}>
                                    {#if loading}
                                        <span class="loading loading-spinner loading-sm"></span>
                                    {:else}
                                        <Plus class="h-4 w-4"/>
                                    {/if}
                                    New Session
                                </button>
                                <button class="btn btn-sm btn-outline" onclick={refreshFiles} disabled={loading}>
                                    {#if loading}
                                        <span class="loading loading-spinner loading-sm"></span>
                                    {:else}
                                        <RefreshCw class="h-4 w-4"/>
                                    {/if}
                                    Refresh
                                </button>
                            </div>
                        </div>

                        {#if selectedWorkspace.sessions.length === 0}
                            <div class="text-sm opacity-70">No sessions found in this workspace. Create one above!</div>
                        {:else}
                            <div class="grid gap-2">
                                {#each selectedWorkspace.sessions as session (session.id)}
                                    <div class="flex items-start gap-3 p-3 bg-base-100 rounded-lg {activeSession?.chatId === session.id ? 'ring-2 ring-primary' : ''}">
                                        <MessageSquare class="h-5 w-5 opacity-70 shrink-0 mt-0.5"/>
                                        <div class="flex-1 min-w-0">
                                            <div class="font-semibold break-words">{session.title}</div>
                                            <div class="text-xs opacity-70 truncate">ID: {session.id}</div>
                                        </div>
                                        <div class="flex gap-1 shrink-0">
                                            <button
                                                    class="btn btn-sm btn-ghost btn-circle"
                                                    onclick={() => selectSession(session.id)}
                                                    disabled={loading}
                                                    title="Open session"
                                            >
                                                <MessageSquare class="h-4 w-4"/>
                                            </button>
                                            <button
                                                    class="btn btn-sm btn-ghost btn-circle"
                                                    onclick={() => readSessionInfo(session.id)}
                                                    disabled={loading}
                                                    title="Show session info"
                                            >
                                                <Info class="h-4 w-4"/>
                                            </button>
                                            <button
                                                    class="btn btn-sm btn-ghost btn-circle text-error"
                                                    onclick={() => deleteSession(session.id)}
                                                    disabled={loading}
                                                    title="Delete session"
                                            >
                                                <Trash2 class="h-4 w-4"/>
                                            </button>
                                        </div>
                                    </div>
                                {/each}
                            </div>
                        {/if}
                    </div>
                </div>

                <!-- Session Info Display -->
                {#if sessionInfo}
                    <div class="card bg-base-300 shadow-xl mb-6">
                        <div class="card-body">
                            <div class="flex justify-between items-start mb-4">
                                <div>
                                    <h3 class="card-title">Session Information</h3>
                                    <p class="text-sm opacity-70">
                                        <strong>Title:</strong> {sessionInfo.title}
                                    </p>
                                </div>
                                <button class="btn btn-sm btn-ghost" onclick={() => sessionInfo = null}>
                                    <X class="h-4 w-4"/>
                                </button>
                            </div>
                            <div class="bg-base-100 p-4 rounded-lg space-y-2 text-sm">
                                <div><strong>ID:</strong> {sessionInfo.id}</div>
                                <div><strong>Created:</strong> {new Date(sessionInfo.createdAt).toLocaleString()}</div>
                                <div><strong>Updated:</strong> {new Date(sessionInfo.updatedAt ?? '').toLocaleString()}</div>
                                {#if sessionInfo.workspaceId}
                                    <div><strong>Workspace ID:</strong> {sessionInfo.workspaceId}</div>
                                {/if}
                                {#if sessionInfo.sessionWorkspaceId}
                                    <div><strong>Session Workspace ID:</strong> {sessionInfo.sessionWorkspaceId}</div>
                                {/if}
                            </div>
                            <div class="card-actions justify-end mt-4">
                                <button
                                        class="btn btn-error btn-sm"
                                        onclick={() => sessionInfo?.id && deleteSession(sessionInfo.id)}
                                        disabled={loading}
                                >
                                    <Trash2 class="h-4 w-4"/>
                                    Delete Session
                                </button>
                            </div>
                        </div>
                    </div>
                {/if}

                <!-- Files List -->
                <div class="flex justify-between items-center mb-4">
                    <h3 class="text-xl font-bold">
                        Files ({selectedWorkspace.files.length})
                    </h3>
                    <button class="btn btn-sm btn-outline" onclick={refreshFiles} disabled={loading}>
                        {#if loading}
                            <span class="loading loading-spinner loading-sm"></span>
                        {:else}
                            <RefreshCw class="h-4 w-4"/>
                        {/if}
                        Refresh
                    </button>
                </div>

                {#if selectedWorkspace.loading}
                    <div class="flex justify-center items-center p-12">
                        <span class="loading loading-spinner loading-lg"></span>
                    </div>
                {:else if selectedWorkspace.files.length === 0}
                    <div class="alert alert-info">
                        <AlertCircle class="h-6 w-6"/>
                        <span>No files found in this workspace. Create one above!</span>
                    </div>
                {:else}
                    <div class="grid gap-4">
                        {#each selectedWorkspace.files as file (file.name)}
                            <div class="card bg-base-100 shadow-xl">
                                <div class="card-body">
                                    {#if editingFilePath === file.name}
                                        <!-- Edit Mode -->
                                        <div class="form-control">
                                            <label class="label">
                                                <span class="label-text">Editing: <strong>{file.name}</strong></span>
                                            </label>
                                            <textarea
                                                    class="textarea textarea-bordered w-full h-40"
                                                    bind:value={editFileContent}
                                            ></textarea>
                                        </div>

                                        <div class="card-actions justify-end mt-4">
                                            <button class="btn btn-ghost btn-sm" onclick={cancelEditFile}>
                                                <X class="h-4 w-4"/>
                                                Cancel
                                            </button>
                                            <button class="btn btn-primary btn-sm" onclick={() => updateFile(file.name)}
                                                    disabled={loading}>
                                                <Save class="h-4 w-4"/>
                                                Save
                                            </button>
                                        </div>
                                    {:else}
                                        <!-- View Mode -->
                                        <div class="flex justify-between items-start">
                                            <div class="flex-1">
                                                <h4 class="font-semibold text-lg flex items-center gap-2">
                                                    <FileText class="h-5 w-5"/>
                                                    {file.name}
                                                </h4>
                                            </div>

                                            <div class="flex gap-2">
                                                <button
                                                        class="btn btn-sm btn-outline"
                                                        onclick={() => readFile(file.name)}
                                                        disabled={loading}
                                                >
                                                    <Download class="h-4 w-4"/>
                                                    Read
                                                </button>
                                                <button
                                                        class="btn btn-sm btn-outline btn-primary"
                                                        onclick={() => startEditFile(file.name)}
                                                        disabled={loading}
                                                >
                                                    <Edit class="h-4 w-4"/>
                                                    Edit
                                                </button>
                                                <button
                                                        class="btn btn-sm btn-outline btn-error"
                                                        onclick={() => deleteFile(file.name)}
                                                        disabled={loading}
                                                >
                                                    <Trash2 class="h-4 w-4"/>
                                                    Delete
                                                </button>
                                            </div>
                                        </div>
                                    {/if}
                                </div>
                            </div>
                        {/each}
                    </div>
                {/if}

                <!-- File Content Display -->
                {#if fileReadContent}
                    <div class="card bg-base-300 shadow-xl mt-6">
                        <div class="card-body">
                            <div class="flex justify-between items-start mb-4">
                                <div>
                                    <h3 class="card-title">File Content</h3>
                                    <p class="text-sm opacity-70">
                                        <strong>Path:</strong> {fileReadContent.path}
                                        <br/>
                                        <strong>MIME Type:</strong> {fileReadContent.mimeType}
                                    </p>
                                </div>
                                <button class="btn btn-sm btn-ghost" onclick={() => fileReadContent = null}>
                                    <X class="h-4 w-4"/>
                                </button>
                            </div>
                            <pre class="bg-base-100 p-4 rounded-lg overflow-x-auto text-sm"><code>{fileReadContent.content}</code></pre>
                        </div>
                    </div>
                {/if}
            </div>
        {/if}
    </div>

    <!-- Right Panel - Thread Component -->
    {#if activeSession}
        <div class="w-1/2 h-full flex flex-col">
            <ThreadFromChat chat={activeSession} />
        </div>
    {/if}
</div>

<style>
    :global(body) {
        min-height: 100vh;
        overflow-y: auto;
    }

    :global(html) {
        overflow-y: auto;
    }
</style>
