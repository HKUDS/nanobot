# Alexa Skill for Nanobot

Alexa Custom Skill that routes voice commands to your Nanobot instance. Uses a
catch-all intent with `AMAZON.SearchQuery` to capture free-form speech and
forward it to the agent.

## Prerequisites

- [ASK CLI](https://developer.amazon.com/docs/smapi/quick-start-alexa-skills-kit-command-line-interface.html) installed and configured
- A Nanobot instance accessible over HTTPS
- Alexa channel enabled in your Nanobot config

## Nanobot Configuration

```yaml
channels:
  alexa:
    enabled: true
    port: 8443
    endpoint_path: /alexa
    verify_signatures: true
    launch_message: "Hi, I'm nanobot. What can I help you with?"
```

Your reverse proxy must forward `/alexa` to the Nanobot Alexa channel port (default 8443).

## Deploy

```bash
# Deploy with your endpoint URL
./deploy.sh https://your-domain.com

# With a different locale
./deploy.sh https://your-domain.com en-US

# With a custom invocation name (must be lowercase, at least two words)
./deploy.sh https://your-domain.com en-GB my assistant
```

The script will:
1. Create a new skill or update an existing one named "Nanobot"
2. Upload the interaction model with ~150 carrier phrase samples
3. Build the language model
4. Enable the skill for testing on your account

## Test

```bash
# Via ASK CLI simulation
ask smapi simulate-skill \
  -s <skill-id> \
  --device-locale en-GB \
  --input-content "ask nano bot how are you"

# Or just talk to your Alexa device
# "Alexa, open nano bot"
# "What's the weather in Dublin?"
```

## Skill Structure

```
skill-package/
├── skill.json                              # Skill manifest (endpoint, metadata)
└── interactionModels/
    └── custom/
        └── en-GB.json                      # Interaction model (intents, slots, samples)
```

## How It Works

1. User says "Alexa, ask nano bot [something]" or opens the skill and speaks
2. Alexa matches the utterance to `CatchAllIntent` via carrier phrase samples
3. The utterance text is sent as an HTTPS POST to your Nanobot endpoint
4. Nanobot processes the request and returns a spoken response within ~7.5 seconds
5. If the utterance doesn't match any carrier phrase, `AMAZON.FallbackIntent`
   triggers a `Dialog.ElicitSlot` directive to re-prompt and capture the input

## Limitations

- **Response timeout**: Alexa enforces an 8-second response limit. Complex agent
  queries that take longer will return "I'm still thinking about that."
- **Carrier phrases**: `AMAZON.SearchQuery` requires at least one word before the
  slot. The model includes ~150 common English sentence starters, but unusual
  phrasings may still miss. The FallbackIntent elicitation handles these cases.
- **No conversation memory**: Each Alexa request is independent. The agent sees
  each utterance in isolation (no multi-turn context within an Alexa session).
