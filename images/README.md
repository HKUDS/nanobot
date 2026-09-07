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
| [nanobot_arch.png](./nanobot_arch.png) | Illustrated overview of chat, nanobot, and replies, supported by tools, memory, and skills |

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
as a visual reference. It preserves the rounded pastel panels, large line icons,
and broad arrows. This is a conceptual overview, not a component map or screenshot.

The main path is chat → nanobot → reply. Memory and skills supply context, and
tools let the agent take action. Keep labels short and leave implementation
details in the [architecture guide](../docs/architecture.md).

### Architecture prompt

```text
Use case: infographic-diagram
Asset type: a simple illustrated overview for the nanobot README.
Input image: the original nanobot diagram is the style reference and redesign target. Closely match its cheerful filled pastel cards, substantial rounded colored borders, large friendly dark outline icons, broad curved arrows, and very sparse large text. Preserve that original visual character, rather than producing a technical component map.

Create a wide, compact, beautifully balanced illustration on an opaque warm-white background, approximately 1800 × 960. Flat view, smooth large round corners, lightly illustrated edges, gentle pastel yellow / blue / peach / pink / purple, not a whiteboard sketch. Use large simple icons to carry the meaning. No headline, no caption, no legend.

The ONLY visible text in the entire image is these SIX labels, once each:
"Chat"
"nanobot"
"Reply"
"Tools"
"Memory"
"Skills"

Layout and meaning:
- A pastel blue card on the left: one large speech-bubble icon, with "Chat".
- A larger peach/orange card at the center: the friendly simple robot outline icon from the reference, with "nanobot".
- A pastel pink card on the right: one reply-bubble icon, with "Reply".
- Above the central nanobot card: a purple rounded group containing just TWO large inset tiles side by side, "Memory" under a database icon, and "Skills" under a gears icon. No heading on this group.
- Below the central nanobot card: a soft yellow card with a small row of two or three large outline icons suggesting a folder, a browser/globe, and a tool, with only "Tools" below.

Exactly four clean, substantial pastel arrows:
1. Chat -> nanobot, horizontally.
2. nanobot -> Reply, horizontally.
3. The shared purple Memory/Skills group -> nanobot, vertically downward.
4. nanobot <-> Tools, one short vertical connection with two arrowheads.

No crossed lines, no lines through cards, no loose arrows. Make the central flow immediately obvious. Fill the canvas well, with modest outside margins and clear spacing for the arrows. Give the three main cards similar generous visual weight; use simple and legible large labels that remain clear at 900px README width. The reference has filled pastel UI-like panels, not thin empty boxes: retain that quality.
Do not include any other text. In particular, no Gateway, API, SDK, class names, code names, implementation details, platform lists, explanatory sentences, bullets, or token labels. No emoji characters, tiny text, watermark, browser UI, technical grid, 3D perspective, or photorealistic objects.
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
