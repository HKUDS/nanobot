---
name: cli-app-hyperframes
description: >-
  Create, preview, and render HTML-native videos locally with HyperFrames.
---

# HyperFrames

Use this skill when the user asks nanobot to create a product video, launch video,
animated explainer, social clip, narrated motion graphic, website-to-video demo,
or any other lightweight video artifact.

If the user attached `@hyperframe` or `@hyperframes` in chat, treat HyperFrames
as the selected video engine for the current turn.

## Workflow

1. Create or reuse a project inside the workspace.
2. Author self-contained HTML/CSS/JS composition files and local assets.
3. Run HyperFrames with the `run_cli_app` tool, never through shell by default.
4. Validate or preview before rendering when the command is available.
5. Render to `.mp4`, `.webm`, or `.mov`, then reference the video with Markdown
   using a workspace-relative path, for example `![Product intro](intro.mp4)`.

## Commands

```bash
hyperframes --help
hyperframes init my-video --non-interactive --example blank
hyperframes preview
hyperframes render --output output.mp4
```

Prefer deterministic, local assets. Avoid remote CDNs unless the user explicitly
asks for them, because renders should be reproducible and work offline.
