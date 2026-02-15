#!/bin/bash
set -e

CONFIG_DIR="/root/.nanobot"
CONFIG_FILE="$CONFIG_DIR/config.json"

mkdir -p "$CONFIG_DIR"

# Only generate config if it doesn't exist or FORCE_CONFIG is set
if [ ! -f "$CONFIG_FILE" ] || [ "$FORCE_CONFIG" = "true" ]; then
    echo "Generating config.json from environment variables..."
    
    # Build providers section
    PROVIDERS="{}"
    
    # Custom/Self-hosted OpenAI-compatible API (like vLLM, OneAPI, NewAPI, etc.)
    if [ -n "$CUSTOM_API_KEY" ]; then
        CUSTOM='{"apiKey": ""}'
        CUSTOM=$(echo "$CUSTOM" | jq --arg key "$CUSTOM_API_KEY" '.apiKey = $key')
        if [ -n "$CUSTOM_API_BASE" ]; then
            CUSTOM=$(echo "$CUSTOM" | jq --arg base "$CUSTOM_API_BASE" '.apiBase = $base')
        fi
        PROVIDERS=$(echo "$PROVIDERS" | jq --argjson custom "$CUSTOM" '. + {"vllm": $custom}')
    fi
    
    if [ -n "$OPENROUTER_API_KEY" ]; then
        OPENROUTER='{"apiKey": ""}'
        OPENROUTER=$(echo "$OPENROUTER" | jq --arg key "$OPENROUTER_API_KEY" '.apiKey = $key')
        if [ -n "$OPENROUTER_API_BASE" ]; then
            OPENROUTER=$(echo "$OPENROUTER" | jq --arg base "$OPENROUTER_API_BASE" '.apiBase = $base')
        fi
        PROVIDERS=$(echo "$PROVIDERS" | jq --argjson or "$OPENROUTER" '. + {"openrouter": $or}')
    fi
    
    if [ -n "$ANTHROPIC_API_KEY" ]; then
        ANTHROPIC='{"apiKey": ""}'
        ANTHROPIC=$(echo "$ANTHROPIC" | jq --arg key "$ANTHROPIC_API_KEY" '.apiKey = $key')
        if [ -n "$ANTHROPIC_API_BASE" ]; then
            ANTHROPIC=$(echo "$ANTHROPIC" | jq --arg base "$ANTHROPIC_API_BASE" '.apiBase = $base')
        fi
        PROVIDERS=$(echo "$PROVIDERS" | jq --argjson an "$ANTHROPIC" '. + {"anthropic": $an}')
    fi
    
    if [ -n "$OPENAI_API_KEY" ]; then
        OPENAI='{"apiKey": ""}'
        OPENAI=$(echo "$OPENAI" | jq --arg key "$OPENAI_API_KEY" '.apiKey = $key')
        if [ -n "$OPENAI_API_BASE" ]; then
            OPENAI=$(echo "$OPENAI" | jq --arg base "$OPENAI_API_BASE" '.apiBase = $base')
        fi
        PROVIDERS=$(echo "$PROVIDERS" | jq --argjson oa "$OPENAI" '. + {"openai": $oa}')
    fi
    
    if [ -n "$DEEPSEEK_API_KEY" ]; then
        DEEPSEEK='{"apiKey": ""}'
        DEEPSEEK=$(echo "$DEEPSEEK" | jq --arg key "$DEEPSEEK_API_KEY" '.apiKey = $key')
        if [ -n "$DEEPSEEK_API_BASE" ]; then
            DEEPSEEK=$(echo "$DEEPSEEK" | jq --arg base "$DEEPSEEK_API_BASE" '.apiBase = $base')
        fi
        PROVIDERS=$(echo "$PROVIDERS" | jq --argjson ds "$DEEPSEEK" '. + {"deepseek": $ds}')
    fi
    
    if [ -n "$GEMINI_API_KEY" ]; then
        GEMINI='{"apiKey": ""}'
        GEMINI=$(echo "$GEMINI" | jq --arg key "$GEMINI_API_KEY" '.apiKey = $key')
        if [ -n "$GEMINI_API_BASE" ]; then
            GEMINI=$(echo "$GEMINI" | jq --arg base "$GEMINI_API_BASE" '.apiBase = $base')
        fi
        PROVIDERS=$(echo "$PROVIDERS" | jq --argjson gm "$GEMINI" '. + {"gemini": $gm}')
    fi
    
    if [ -n "$DASHSCOPE_API_KEY" ]; then
        DASHSCOPE='{"apiKey": ""}'
        DASHSCOPE=$(echo "$DASHSCOPE" | jq --arg key "$DASHSCOPE_API_KEY" '.apiKey = $key')
        if [ -n "$DASHSCOPE_API_BASE" ]; then
            DASHSCOPE=$(echo "$DASHSCOPE" | jq --arg base "$DASHSCOPE_API_BASE" '.apiBase = $base')
        fi
        PROVIDERS=$(echo "$PROVIDERS" | jq --argjson dsh "$DASHSCOPE" '. + {"dashscope": $dsh}')
    fi
    
    if [ -n "$GROQ_API_KEY" ]; then
        GROQ='{"apiKey": ""}'
        GROQ=$(echo "$GROQ" | jq --arg key "$GROQ_API_KEY" '.apiKey = $key')
        if [ -n "$GROQ_API_BASE" ]; then
            GROQ=$(echo "$GROQ" | jq --arg base "$GROQ_API_BASE" '.apiBase = $base')
        fi
        PROVIDERS=$(echo "$PROVIDERS" | jq --argjson gr "$GROQ" '. + {"groq": $gr}')
    fi

    # Build channels section
    CHANNELS="{}"
    
    # Telegram
    if [ -n "$TELEGRAM_BOT_TOKEN" ]; then
        TELEGRAM='{"enabled": true}'
        TELEGRAM=$(echo "$TELEGRAM" | jq --arg token "$TELEGRAM_BOT_TOKEN" '. + {"token": $token}')
        if [ -n "$TELEGRAM_ALLOW_FROM" ]; then
            TELEGRAM=$(echo "$TELEGRAM" | jq --argjson users "$TELEGRAM_ALLOW_FROM" '. + {"allowFrom": $users}')
        else
            TELEGRAM=$(echo "$TELEGRAM" | jq '. + {"allowFrom": []}')
        fi
        CHANNELS=$(echo "$CHANNELS" | jq --argjson tg "$TELEGRAM" '. + {"telegram": $tg}')
    fi
    
    # Discord
    if [ -n "$DISCORD_BOT_TOKEN" ]; then
        DISCORD='{"enabled": true}'
        DISCORD=$(echo "$DISCORD" | jq --arg token "$DISCORD_BOT_TOKEN" '. + {"token": $token}')
        if [ -n "$DISCORD_ALLOW_FROM" ]; then
            DISCORD=$(echo "$DISCORD" | jq --argjson users "$DISCORD_ALLOW_FROM" '. + {"allowFrom": $users}')
        else
            DISCORD=$(echo "$DISCORD" | jq '. + {"allowFrom": []}')
        fi
        CHANNELS=$(echo "$CHANNELS" | jq --argjson dc "$DISCORD" '. + {"discord": $dc}')
    fi
    
    # Feishu
    if [ -n "$FEISHU_APP_ID" ] && [ -n "$FEISHU_APP_SECRET" ]; then
        FEISHU='{"enabled": true}'
        FEISHU=$(echo "$FEISHU" | jq --arg id "$FEISHU_APP_ID" --arg secret "$FEISHU_APP_SECRET" '. + {"appId": $id, "appSecret": $secret}')
        if [ -n "$FEISHU_ALLOW_FROM" ]; then
            FEISHU=$(echo "$FEISHU" | jq --argjson users "$FEISHU_ALLOW_FROM" '. + {"allowFrom": $users}')
        fi
        CHANNELS=$(echo "$CHANNELS" | jq --argjson fs "$FEISHU" '. + {"feishu": $fs}')
    fi
    
    # DingTalk
    if [ -n "$DINGTALK_CLIENT_ID" ] && [ -n "$DINGTALK_CLIENT_SECRET" ]; then
        DINGTALK='{"enabled": true}'
        DINGTALK=$(echo "$DINGTALK" | jq --arg id "$DINGTALK_CLIENT_ID" --arg secret "$DINGTALK_CLIENT_SECRET" '. + {"clientId": $id, "clientSecret": $secret}')
        if [ -n "$DINGTALK_ALLOW_FROM" ]; then
            DINGTALK=$(echo "$DINGTALK" | jq --argjson users "$DINGTALK_ALLOW_FROM" '. + {"allowFrom": $users}')
        fi
        CHANNELS=$(echo "$CHANNELS" | jq --argjson dt "$DINGTALK" '. + {"dingtalk": $dt}')
    fi

    # Build agents section
    AGENTS='{"defaults": {}}'
    if [ -n "$DEFAULT_MODEL" ]; then
        AGENTS=$(echo "$AGENTS" | jq --arg model "$DEFAULT_MODEL" '.defaults.model = $model')
    fi

    # Build final config
    CONFIG=$(jq -n \
        --argjson providers "$PROVIDERS" \
        --argjson channels "$CHANNELS" \
        --argjson agents "$AGENTS" \
        '{"providers": $providers, "channels": $channels, "agents": $agents}')
    
    echo "$CONFIG" > "$CONFIG_FILE"
    echo "Config generated at $CONFIG_FILE"
    echo "Generated config:"
    cat "$CONFIG_FILE" | jq .
else
    echo "Using existing config at $CONFIG_FILE"
fi

# Execute the command
exec "$@"
