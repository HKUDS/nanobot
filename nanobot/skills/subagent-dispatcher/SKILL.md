---
name: subagent dispatcher
description: dispatch a specific sub-agent to complete a particular specialized task.
---

# Subagent Dispatcher

Standardizes the subagent calling process to ensure the correct model and parameters are selected according to the task type.

## Usage Scenarios

When a subagent needs to be called, for example:
- **Vision Tasks**: Image recognition, image analysis.
- **Image Generation**: Generating images.
- **Complex Tasks**: Time-consuming tasks requiring independent processing.
- **Special Tasks**: Tasks requiring specific model capabilities.

## Call Flow

### Step 1: Check Configuration

Read the model configuration to identify available models and their roles:

```bash
# View configuration file
cat /root/.nanobot/config.json
```

**Key Fields:**
- `model`: Model name (e.g., `zai/glm-4.6v`)
- `role`: Model role (e.g., `vision`, `image-generation`, `default`)
- `description`: Model description

**Common Role Types:**
- `vision` - Vision model (Image recognition)
- `image-generation` - Image generation model
- `default` - Default text model

### Step 2: Select Subagent and Parameters

Use the `spawn` tool to call a subagent based on the task type:

**Vision Task (Image Recognition):**
```python
spawn(
    task="Analyze this image...",
    model="zai/glm-4.6v",  # Vision model
    media=["/path/to/image.jpg"]  # Array of image paths
)
```

**Image Generation Task:**
```python
spawn(
    task="Generate a...",
    model="zai/cogView-4-250304"  # Image generation model
)
```

**General Complex Task:**
```python
spawn(
    task="Process this complex task..."
    # No need to specify model, uses default model
)
```

**Parameter Selection Rules:**
- Vision tasks → Must specify `model` (role=vision) and `media`.
- Image generation → Must specify `model` (role=image-generation).
- General tasks → Can omit `model`; uses the default model.

### Step 3: Notify User

After calling the subagent, explicitly inform the user:

```
Vision subagent started, using zai/glm-4.6v model to analyze the image.
```

**Notification content should include:**
- Task type (Vision/Image Generation/General Task)
- Model name used
- Current status (Started/Running/Waiting)

## Examples

### Example 1: Image Recognition
```
User: Analyze this image
[Image]

Execution:
1. Check config → Found zai/glm-4.6v (role: vision)
2. spawn(task="Analyze image...", model="zai/glm-4.6v", media=["/path/to/image.jpg"])
3. Notify user: Vision subagent started, using zai/glm-4.6v model to analyze the image.
```

### Example 2: Generate Image
```
User: Generate a picture of a cat

Execution:
1. Check config → Found zai/cogView-4-250304 (role: image-generation)
2. spawn(task="Generate a picture of a cat", model="zai/cogView-4-250304")
3. Notify user: Image generation subagent started, using zai/cogView-4-250304 model to generate the image.
```

## Notes

- ⚠️ Vision tasks **must** specify the `model` parameter; otherwise, the default text model will be used, leading to API errors.
- ⚠️ The `media` parameter requires an array of image paths.
- ✅ General tasks can omit the `model` parameter to use the default model.
- ✅ Always confirm the model role and usage in the configuration file before calling.