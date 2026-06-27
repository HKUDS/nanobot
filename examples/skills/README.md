# Example Skills

This directory contains reference skills that ship with nanobot. They are **not loaded by default**.

Each subdirectory is a self-contained example you can use as a starting point for building your own skills.

## Available examples

- `weather/` — fetches current weather information.

## Using an example

The skills in this folder are for reference only. To enable one, copy it into your own skills directory:

```bash
cp -r examples/skills/weather ~/.nanobot/skills/weather
```

nanobot loads skills from your skills directory on startup, so the example becomes available the next time you run it.

Feel free to edit the copied skill to fit your needs, or use it as a template for new skills.
