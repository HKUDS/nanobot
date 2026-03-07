#!/usr/bin/env bash
# Deploy the Nanobot Alexa skill using the ASK CLI.
#
# Prerequisites:
#   - ASK CLI installed: npm install -g ask-cli
#   - ASK CLI configured: ask configure
#
# Usage:
#   ./deploy.sh https://your-nanobot-domain.com
#   ./deploy.sh https://your-nanobot-domain.com en-US    # optional locale override
#   ./deploy.sh https://your-nanobot-domain.com en-US my-custom-bot  # optional invocation name

set -euo pipefail

ENDPOINT_URL="${1:?Usage: $0 <endpoint-url> [locale] [invocation-name]}"
LOCALE="${2:-en-GB}"
INVOCATION_NAME="${3:-nano bot}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SKILL_PKG="$SCRIPT_DIR/skill-package"

# Validate endpoint URL
if [[ ! "$ENDPOINT_URL" =~ ^https:// ]]; then
    echo "Error: Endpoint URL must use HTTPS (Alexa requirement)." >&2
    exit 1
fi

# Ensure the endpoint path is included
if [[ ! "$ENDPOINT_URL" =~ /alexa$ ]]; then
    ENDPOINT_URL="${ENDPOINT_URL%/}/alexa"
fi

echo "==> Deploying Nanobot Alexa skill"
echo "    Endpoint: $ENDPOINT_URL"
echo "    Locale:   $LOCALE"
echo "    Invocation: \"$INVOCATION_NAME\""
echo ""

# --- Prepare skill.json with the actual endpoint ---
SKILL_JSON=$(cat "$SKILL_PKG/skill.json")
SKILL_JSON=$(echo "$SKILL_JSON" | python3 -c "
import json, sys
d = json.load(sys.stdin)
d['manifest']['apis']['custom']['endpoint']['uri'] = '$ENDPOINT_URL'
# Update locale key if not en-GB
if '$LOCALE' != 'en-GB':
    pub = d['manifest']['publishingInformation']['locales']
    pub['$LOCALE'] = pub.pop('en-GB', pub.get('$LOCALE', {}))
    priv = d['manifest']['privacyAndCompliance']['locales']
    priv['$LOCALE'] = priv.pop('en-GB', priv.get('$LOCALE', {}))
json.dump(d, sys.stdout, indent=2)
")

# --- Prepare interaction model with invocation name and locale ---
MODEL_FILE="$SKILL_PKG/interactionModels/custom/en-GB.json"
MODEL_JSON=$(cat "$MODEL_FILE")
MODEL_JSON=$(echo "$MODEL_JSON" | python3 -c "
import json, sys
d = json.load(sys.stdin)
d['interactionModel']['languageModel']['invocationName'] = '$INVOCATION_NAME'
json.dump(d, sys.stdout, indent=2)
")

# --- Check if skill already exists ---
SKILL_NAME=$(echo "$SKILL_JSON" | python3 -c "
import json, sys
d = json.load(sys.stdin)
locales = d['manifest']['publishingInformation']['locales']
print(next(iter(locales.values()))['name'])
")

echo "==> Checking for existing skill named \"$SKILL_NAME\"..."
EXISTING_SKILL_ID=$(ask smapi list-skills-for-vendor 2>/dev/null | python3 -c "
import json, sys
d = json.load(sys.stdin)
for s in d.get('skills', []):
    for name in s.get('nameByLocale', {}).values():
        if name == '$SKILL_NAME':
            print(s['skillId'])
            sys.exit(0)
print('')
" 2>/dev/null || echo "")

if [ -n "$EXISTING_SKILL_ID" ]; then
    echo "    Found existing skill: $EXISTING_SKILL_ID"
    echo "==> Updating skill manifest..."
    echo "$SKILL_JSON" | ask smapi update-skill-manifest \
        -s "$EXISTING_SKILL_ID" \
        -g development \
        --manifest "$(echo "$SKILL_JSON" | python3 -c 'import json,sys; print(json.dumps(json.load(sys.stdin)["manifest"]))')"
    SKILL_ID="$EXISTING_SKILL_ID"
else
    echo "    No existing skill found. Creating new skill..."
    CREATE_RESULT=$(echo "$SKILL_JSON" | ask smapi create-skill-for-vendor \
        --manifest "$(echo "$SKILL_JSON" | python3 -c 'import json,sys; print(json.dumps(json.load(sys.stdin)["manifest"]))')" 2>&1)
    SKILL_ID=$(echo "$CREATE_RESULT" | python3 -c "import json,sys; print(json.load(sys.stdin)['skillId'])")
    echo "    Created skill: $SKILL_ID"

    # Wait for skill creation to complete
    echo "==> Waiting for skill creation..."
    for i in $(seq 1 30); do
        STATUS=$(ask smapi get-skill-status -s "$SKILL_ID" 2>&1 | python3 -c "
import json, sys
d = json.load(sys.stdin)
m = d.get('manifest', {})
print(m.get('lastUpdateRequest', {}).get('status', 'UNKNOWN'))
" 2>/dev/null || echo "UNKNOWN")
        if [ "$STATUS" = "SUCCEEDED" ] || [ "$STATUS" = "UNKNOWN" ]; then
            break
        fi
        sleep 2
    done
fi

# --- Update interaction model ---
echo "==> Updating interaction model for $LOCALE..."
ask smapi set-interaction-model \
    -s "$SKILL_ID" \
    -g development \
    -l "$LOCALE" \
    --interaction-model "$MODEL_JSON"

# --- Wait for build ---
echo "==> Waiting for model build..."
for i in $(seq 1 60); do
    BUILD_STATUS=$(ask smapi get-skill-status \
        -s "$SKILL_ID" \
        --resource interactionModel 2>&1 | python3 -c "
import json, sys
d = json.load(sys.stdin)
for locale, info in d.get('interactionModel', {}).items():
    status = info.get('lastUpdateRequest', {}).get('status', 'UNKNOWN')
    print(status)
    break
" 2>/dev/null || echo "UNKNOWN")

    if [ "$BUILD_STATUS" = "SUCCEEDED" ]; then
        echo "    Build succeeded!"
        break
    elif [ "$BUILD_STATUS" = "FAILED" ]; then
        echo "    Build FAILED. Check errors:"
        ask smapi get-skill-status -s "$SKILL_ID" --resource interactionModel 2>&1
        exit 1
    fi
    sleep 3
done

# --- Enable skill for testing ---
echo "==> Enabling skill for testing..."
ask smapi set-skill-enablement -s "$SKILL_ID" -g development 2>/dev/null || true

echo ""
echo "==> Deployment complete!"
echo "    Skill ID: $SKILL_ID"
echo "    Endpoint: $ENDPOINT_URL"
echo "    Invocation: \"Alexa, open $INVOCATION_NAME\""
echo ""
echo "    Test with: ask smapi simulate-skill -s $SKILL_ID --device-locale $LOCALE --input-content \"ask $INVOCATION_NAME how are you\""
