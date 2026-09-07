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
