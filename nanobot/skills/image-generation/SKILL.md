---
name: image-generation
description: Generate images and iteratively edit saved image artifacts.
---

# Image Generation

Use the `generate_image` tool when the user asks you to create, render, draw, design, generate, or edit an image.

If the `generate_image` tool is not available in the current tool list, tell the user that image generation is not enabled for this nanobot instance.

## When To Use

- Text-to-image: call `generate_image` with a concrete `prompt`.
- Image editing: pass the saved artifact path or user image path in `reference_images`.
- Iterative edits in the same conversation: prefer the most recent generated image artifact if the user says things like "make it brighter", "change the background", or "try another version".
- Ambiguous edits: ask a short clarifying question if multiple recent images could be the target.
- After generating images, call the `message` tool with the artifact paths in the `media` parameter to deliver them to the user.

## Prompt Rules

Write prompts with enough detail for image models:

- Subject and scene.
- Composition and camera or layout.
- Style, mood, lighting, and color palette.
- Text that must appear in the image, quoted exactly.
- Constraints such as "keep the same character", "preserve the logo", or "do not change the background".

## Artifact Rules

The tool stores generated images as persistent artifacts under nanobot's media directory and returns structured metadata:

- `id`: generated image id, such as `img_ab12cd34ef56`.
- `path`: local file path for internal follow-up edits.
- `mime`: image MIME type.
- `prompt`, `model`, and `source_images`: provenance for follow-up edits.

In normal user-facing replies, do not expose local filesystem paths. Keep the reply natural, for example "Done, I generated it." You may include the short image `id` when it helps the user refer to a specific image, but keep raw `path` internal unless the user explicitly asks for debug details or a local artifact reference. Never paste base64.

For follow-up edits, pass the prior artifact `path` to `reference_images`. If the user provides a new uploaded image, use that path as the reference instead.

Do not include internal replay markers such as `[Message Time: ...]`, `[image: /local/path]`, `generate_image(...)`, or `message(...)` in user-facing replies.

## Examples

Generate a new image:

```text
generate_image(
  prompt="A minimal app icon for nanobot: friendly robot head, rounded square, soft blue and white palette, clean vector style, no text",
  aspect_ratio="1:1",
  image_size="1K"
)
```

Edit the latest generated artifact:

```text
generate_image(
  prompt="Use the reference image. Keep the same robot and composition, but change the palette to warm orange and add a subtle sunrise background.",
  reference_images=["/home/user/.nanobot/media/generated/2026-05-08/img_ab12cd34ef56.png"],
  aspect_ratio="1:1",
  image_size="1K"
)
```
