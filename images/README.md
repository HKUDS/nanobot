# README images

The root README uses these product images:

| File | Content |
|---|---|
| [nanobot_webui-source.png](./nanobot_webui-source.png) | Original, unedited new-topic screenshot |
| [nanobot_webui.png](./nanobot_webui.png) | The new-topic screenshot with an AI-generated presentation frame |
| [nanobot-workbench.png](./nanobot-workbench.png) | Three example conversations in the main-and-stack layout |
| [nanobot-context.png](./nanobot-context.png) | Example file edit with inline diff and per-round context usage |
| [nanobot-apps.png](./nanobot-apps.png) | The built-in MCP preset catalog and custom-server controls |
| [nanobot-automations.png](./nanobot-automations.png) | Example recurring tasks and the selected task's schedule |
| [nanobot_arch.png](./nanobot_arch.png) | Illustrated map of clients, gateway, agent core, models, tools, context, and programmatic entry points |

The four feature screenshots were captured from the built WebUI at
[`3f128505`](https://github.com/HKUDS/nanobot/commit/3f128505d0782fba089d1a7b07b7a65d3b2fc985)
through an isolated local gateway. Conversation text, file-edit events, usage
numbers, and paused schedules are demonstration data, not results of a live
model run. The MCP catalog comes from the application. These screenshots are
unedited browser captures.

For similar captures, use English, the light theme, and comfortable density.
The context screenshot uses **Settings → Appearance → File edit display → Diff**.
The Apps screenshot uses **Brand logos → Off**, which displays the application's
initials icons without depending on external image servers. Keep credentials,
personal history, and private workspace paths out of screenshots.

When updating the framed hero, retain the unedited source and check all labels,
icons, and controls against it. Use the image-generation prompt below with
`nanobot_webui-source.png` as the edit target. Keep functional screenshots as
browser captures so the guide continues to show the interface users can operate.

## Architecture illustration

The architecture illustration was generated with the built-in image-generation
tool, using the [original diagram](https://github.com/HKUDS/nanobot/blob/3f128505d0782fba089d1a7b07b7a65d3b2fc985/images/nanobot_arch.png)
as a visual reference. Its rounded pastel cards and line icons carry the same
visual style; its labels and connections describe the current architecture.
It is an explanatory illustration, not a screenshot.

The topology follows [Architecture](../docs/architecture.md): clients exchange
messages through the gateway, the agent core calls models and tools and uses
session, memory, and skill context, and the Python SDK and HTTP API call the
core directly. The bidirectional arrows summarize interactions rather than
individual events or execution order. Check these relationships against the
source before generating a replacement.

### Architecture prompt

```text
Use case: infographic-diagram
Asset type: the nanobot GitHub README architecture illustration, landscape, approximately 1800 × 1000.
Input image: the existing nanobot architecture graphic is the redesign target and visual reference. Retain its friendly pastel cards, softly rounded corners, slightly hand-drawn colored outlines, simple dark line icons, and broad readable arrows. Update its obsolete topology and labels using the exact specification below.
Design: a polished, calm technical illustration on an opaque warm-white background (#fcfbf8). Flat front-facing composition, no perspective, no 3D, no gradients, no heavy shadows, no title or footer inside the picture. Keep the understated illustrated character of the reference rather than generic flowchart software styling. Modest outer margins. Labels must remain sharp and comfortably readable when the complete image is displayed at 900 CSS pixels wide.

Seven cards, arranged as a balanced component map:
1. Tall pale-blue "Clients" card at the left, containing three vertically stacked dark line icons and the exact labels "WebUI", "Terminal", "Chat apps".
2. Soft-yellow "Gateway" card to its right at mid-height, with a speech/message line icon and secondary label "MessageBus".
3. Larger soft-peach "Agent core" card at the visual center, with a simple robot line icon and the exact secondary labels "AgentLoop" and "AgentRunner", on separate lines.
4. Small pale-rose "Models" card directly above Agent core, with a model/spark line icon and the label "Hosted / Local".
5. Soft-mint "Tools" card directly below Agent core, with simple folder, terminal, globe line icons and two short rows: "Files · Shell · Web" and "MCP · Cron · Subagents".
6. Tall lavender "Context" card on the far right, aligned with Agent core, containing three clear vertically arranged entries "Sessions", "Memory", "Skills" with matching simple dark outline icons. This recalls the reference's purple Context box.
7. Small pale-blue "Integrations" card below Gateway and left of Tools, containing "Python SDK" and "HTTP API" on separate lines and a small code-brackets icon.

Exactly six visible connections, each a single broad pastel stroke with an arrowhead at BOTH ends:
Clients <-> Gateway
Gateway <-> Agent core
Models <-> Agent core
Agent core <-> Tools
Agent core <-> Context
Integrations <-> Agent core
The Clients/Gateway/Agent core/Context path reads horizontally left to right. Models and Tools connect vertically to the Agent core above and below. Integrations connects diagonally or with a clean gentle bend to the lower-left edge of Agent core, using its own separated endpoint. Connect at card borders; leave enough space for arrowheads. No line may cross a card, label, icon, or another connection. Do not connect Models directly to Tools. Do not connect Integrations to Gateway. Add no other arrows or connections.
Use color to distinguish the groups while keeping text uniformly dark and high contrast. Typeset text accurately in a clean rounded sans-serif font. Keep component headings prominent and supporting labels sparse. No additional text, badges, legends, watermark, browser controls, tiny annotations, dotted background, technical grid, or emoji glyphs.
```

## Hero frame prompt

Generated with the built-in image-generation tool.

```text
Use case: compositing
Asset type: GitHub README product screenshot, landscape, about 1920 x 1152.
Input image: the supplied nanobot WebUI screenshot is the edit target and must remain faithful.
Primary request: turn this screenshot into a polished README presentation by adding a modest outer margin, smoothly rounded outside corners, a fine neutral border and a soft restrained shadow. Put it on a very subtle warm gray background with a slight soft peach glow near one outer corner, appropriate for nanobot's orange cat logo.
Composition: a flat front-facing screenshot, centered, occupying about 92% of canvas width. Preserve the entire screenshot and its aspect ratio. Keep margins modest so all UI text remains readable in a GitHub README.
Constraints: Preserve the existing app exactly, including white main canvas, pale sidebar, orange cat logo, typography, text, icons, proportions, whitespace and positions. The large headline must remain exactly "What should we work on?" on one line. Keep "New topic", "Search", "Apps", "Skills", "Automations", "No sessions yet.", "Settings", "Ask anything...", "Full Access", "codex", and "Select project" verbatim. Keep both top-right icons and the bottom-left status dot. Change only the framing and outside background. Do not redesign, invent controls, change models, crop the UI, add browser chrome, add titles or marketing text, use perspective, add objects, or add a watermark. All four outer corners should be clean, consistent, softly rounded.
```
