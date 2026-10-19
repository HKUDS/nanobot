# WebUI components

## Browse the internal gallery

From `webui/`, run:

```sh
bun install --frozen-lockfile
bun run gallery
```

Open `http://127.0.0.1:5173/gallery.html`. The gallery uses the existing Vite development server and the actual application components. It needs no gateway, model provider, or API key. If another Vite server occupies the default port, use `bun run gallery --port 5174`.

The gallery opens in **Previews**, which lists components with working examples. **All source** includes the complete source inventory and marks entries as **Preview** or **Source only**. Source-only entries link to related previews when their direct imports or callers have examples. A bookmarked source-only entry opens the source index automatically.

Search by module name, exported name, path, or the bilingual example title. Categories separate foundation controls, shared views, conversation, settings, hosts, workbench, icons, and channel-owned interfaces. Each entry shows its source, exports, and direct references. The selected entry is kept in the URL, so it can be bookmarked or reloaded.

The inventory is read from the current checkout. **Refresh inventory** picks up added, removed, and changed source files. Counts are source-module counts: a module can export several components, and several modules can belong to one example family. Direct references include imports, literal dynamic imports, and re-exports, including type references; they exclude tests and the gallery. Indirect plugin registration is not a direct reference, so an empty reference list does not prove that a component is unused.

All foundation controls have live examples. Shared examples cover Markdown, code, math, messages, media, thinking/tool activity, file edits, and file references. Settings examples include the provider management dialog with its search and configuration flow, model controls, capability forms, channel credentials, usage charts, and automation controls. Conversation examples include the composer, prompt navigation, activity and error states. Shell examples include conversation dialogs, mentions, host status, icons, and pane layouts. These examples mount the product components with local data and caller-owned actions.

Change state selectors to inspect streaming, completion, disabled, missing-media, or error states where applicable. Dialog and disclosure examples preserve local drafts; their actions affect only the preview. Use the header to change theme and the language of the product components. Gallery explanations and code examples are development documentation.

Feature screens that own gateway requests, session state, or host connections are indexed with their source and callers. Exercise their complete workflows in the running WebUI. The gallery does not emulate those services.

Runtime adapters and presentation views have separate responsibilities. Adapters subscribe to clients, load data, enforce browser restrictions, and perform service actions. Their views receive display data and operation callbacks. Production screens and gallery examples mount the same views, including host menus, pairing, file/web previews, session tasks, automation results, version information, and notification preferences. Connected source entries link to the corresponding view examples.

Every channel registration has a preview. Channels with shared configuration forms use their production setup view; Linear, Feishu, Weixin, and WhatsApp use their channel-owned views, including authorization, verification, assistant management, and connection reset. The source inventory includes channel `webui/index.ts` registrations as well as `.tsx` components. Connected adapters link to the views they own.

Channel fixture fields, defaults, and requirements come from the Python channel setup contracts. Regenerate `src/dev/gallery/channel-fixtures.ts` with `python webui/src/dev/gallery/generate_channel_fixtures.py` from the repository root after changing those contracts; add `--check` to verify the snapshot. This developer command loads channel descriptors without starting a gateway. Running the gallery uses the committed snapshot and requires no Python process.

## Where components belong

| Location | Ownership | Examples |
| --- | --- | --- |
| `src/components/ui/` | Foundation controls and small presentation primitives shared across features | `Button`, `Input`, `ToggleButton`, dialog/menu/tooltip primitives, `StreamingLabelSheen` |
| `src/components/` | Shared content renderers and application-shell compositions | `MarkdownText`, `CodeBlock`, `ImageGallery`, `MessageBubble`, `Sidebar` |
| `src/components/thread/` | Conversation UI and its display models | Composer, viewport, prompt navigation, activity rows |
| `src/components/settings/shared/` | Reusable settings-specific compositions | Settings rows/groups, feature editors, provider controls |
| `src/components/settings/` | Settings feature screens and their controllers | Models, capabilities, channels, automations |
| `src/components/remote/` | Host selection and connection interfaces | Host switcher, pairing and remote connections |
| `src/components/workbench/` | Pane layout and its interaction model | `PaneWorkbench` |
| `src/components/icons/` | Product-specific icon vocabulary | `product-icons.tsx` |
| `nanobot/channels/<channel>/webui/` | Channel-owned screens, components, and translations | Feishu assistants, Linear setup, Weixin connection |

Supporting hooks and display-model helpers stay near the feature that owns them. Common theme tokens and reusable CSS treatments live in `src/globals.css`, `tailwind.config.js`, and the relevant `ui/` modules. The component inventory lists `.tsx` modules; pure `.ts` helpers remain discoverable through their callers and source imports.

`NanobotClient` adapts WebSocket frames into observations for its `ClientRunLedger`. The ledger owns each chat's message delivery, run identities, clocks, and completion records, and returns effects for the client to apply to its queues and subscribers. A dropped connection makes unconfirmed delivery unknown while durable runs remain unresolved. Wire completion still permits late final messages; canonical completion records suppress matching top-level turn events. `useNanobotStream` owns message projection and render batching, while `ThreadShell` adopts canonical history and confirms completion after the messages commit.

`onChat` provides live events to task and model observers. `useNanobotStream` uses `onTranscript` as the single transcript owner, receiving queued events once followed by live events.

## Choose an existing component

- Check the gallery and current callers before creating a control. Different labels, colors, or sizes usually call for an existing component's options. `Button` already has appearance and size variants; `Input` and `SearchInput` share the input implementation.
- Compose controls for a larger interaction. A settings row owns its layout, while the switch or text field supplies its own focus, disabled, and keyboard behavior.
- Extract a shared component when current callers need the same behavior. Keep feature-specific state and actions in the owning screen. A reusable animation should not import an entire message renderer, and a foundation control should not depend on a settings screen.
- Preserve meaningful differences. A one-shot action and an on/off switch have different interaction contracts even when their silhouettes look similar. Use `className` for local placement; put a shared appearance change in the component or token that owns it.
- Keep agent execution, sessions, tools, memory, and security policy in the Python gateway. UI components receive display data and caller-owned actions.

For example, a caller controls a shared switch:

```tsx
import { ToggleButton } from "@/components/ui/toggle-button";

<ToggleButton
  checked={enabled}
  onChange={setEnabled}
  label="Enable feature"
/>
```

The caller decides how to persist `enabled`; the switch implements the interaction and appearance.

## Maintain the gallery

The development entry is `gallery.html`; its UI and examples live in `src/dev/gallery/`. The Vite `componentGallery` plugin serves the source inventory only during development. The normal production build starts at `index.html` and excludes the gallery entry, inventory endpoint, and source-view data.

Add examples to the appropriate feature file in `src/dev/gallery/`. Each example names the source modules it actually renders, describes the useful options, and contains a small usage snippet. Mount the actual component and use local state for interactions. Supply fixture data through the component's existing props. When a reusable interface owns client subscriptions or service requests, separate its presentation view from the owning adapter and use that view in production and the gallery. Combine related modules into one example rather than exposing every implementation detail as a separate control. A coverage test checks that every foundation module has an example and that all example source paths exist.

Run the focused gallery and affected component tests, lint, and `bun run build`. The build type-checks the gallery source even though it does not bundle it. Inspect examples in light/dark themes and at narrow widths, exercise keyboard interaction, and verify the affected production screens through the gateway.
