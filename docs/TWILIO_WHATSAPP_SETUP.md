# Twilio WhatsApp Channel Setup

Connect nanobot to WhatsApp using the Twilio WhatsApp Business API. This is a pure-Python channel -- no external bridge processes needed.

## Prerequisites

*   A [Twilio account](https://www.twilio.com/try-twilio) (free trial works)
*   Python 3.11+
*   [ngrok](https://ngrok.com/) (for local testing)
*   nanobot installed from source or PyPI

## 1\. Install Dependencies

```
pip install nanobot-ai[twilio]
```

If installing from a source checkout:

```
cd nanobot
pip install -e ".[twilio]"
```

This pulls in the `twilio` SDK and `aiohttp` (used for the webhook server).

## 2\. Get Twilio Credentials

### Sandbox (testing)

1.  Log in to the [Twilio Console](https://console.twilio.com/)
2.  Go to **Messaging > Try it out > Send a WhatsApp message**
3.  Follow the on-screen instructions to join the sandbox (you'll send a message like `join <keyword>` from your phone to the sandbox number)
4.  Note the **Sandbox number** shown (e.g. `+14155238886`)

### Production

Use a Twilio-registered WhatsApp Business number. The setup below is the same -- just use your production number instead of the sandbox one.

### Credentials

From the Twilio Console dashboard, copy:

*   **Account SID** (starts with `AC`)
*   **Auth Token**

## 3\. Configure nanobot

If you haven't already, run onboarding to create the default config:

```
nanobot onboard
```

Edit `~/.nanobot/config.json` and set the `twilio_whatsapp` section:

```
{
  "channels": {
    "twilio_whatsapp": {
      "enabled": true,
      "account_sid": "ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
      "auth_token": "your_auth_token_here",
      "from_number": "whatsapp:+14155238886",
      "webhook_path": "/twilio/whatsapp",
      "validate_signature": false,
      "public_url": "",
      "allow_from": ["*"],
      "immediate_response": "",
      "group_policy": "open"
    }
  }
}
```

### Configuration Reference

| Field | Default | Description |
| --- | --- | --- |
| `enabled` | `false` | Enable or disable the channel |
| `account_sid` | `""` | Twilio Account SID |
| `auth_token` | `""` | Twilio Auth Token |
| `from_number` | `""` | Twilio WhatsApp number, must include prefix (e.g. `whatsapp:+14155238886`) |
| `webhook_path` | `"/twilio/whatsapp"` | URL path for the incoming webhook |
| `webhook_port` | `0` | Port for the webhook server. `0` uses the gateway port (default `18790`) |
| `validate_signature` | `false` | Validate the `X-Twilio-Signature` header on incoming requests |
| `public_url` | `""` | Public base URL (e.g. `https://abcd.ngrok-free.app`). Required for signature validation behind proxies/ngrok |
| `allow_from` | `[]` | List of allowed sender phone numbers without the `whatsapp:` prefix (e.g. `["+14155238886"]`), or `["*"]` to allow all |
| `immediate_response` | `""` | If set, the webhook immediately replies with this text (e.g. `"Thinking..."`) before the agent processes the message |
| `group_policy` | `"open"` | `"open"` responds to all messages; `"mention"` only responds when the bot is @mentioned |

> **Security note:** For production, set `validate_signature` to `true`, set `public_url` to your public-facing URL, and restrict `allow_from` to specific numbers instead of `["*"]`.

## 4\. Start ngrok

ngrok creates a public HTTPS tunnel to your local machine so Twilio can reach your webhook.

In a separate terminal:

```
ngrok http 18790
```

You'll see output like:

```
Forwarding  https://abcd1234.ngrok-free.app -> http://localhost:18790
```

Copy the `https://...ngrok-free.app` URL. This changes each time you restart ngrok (unless you're on a paid plan with a reserved domain).

## 5\. Configure the Twilio Webhook

### Sandbox

1.  Go to **Messaging > Try it out > Send a WhatsApp message** in the Twilio Console
2.  Scroll to **Sandbox Configuration**
3.  Set **When a message comes in** to:
4.  Set the method to **POST**
5.  Save

### Production

1.  Go to your WhatsApp Sender in the Twilio Console
2.  Set the webhook URL for incoming messages to your ngrok URL + `/twilio/whatsapp`

## 6\. Start nanobot

```
nanobot gateway --verbose
```

You should see:

```
Twilio WhatsApp webhook listening on :18790/twilio/whatsapp
```

## 7\. Test

1.  Open WhatsApp on your phone
2.  Send a message to the Twilio sandbox number (or your production number)
3.  The message flows through: **Your Phone -> Twilio -> ngrok -> nanobot -> Twilio API -> Your Phone**

### Verify the webhook is reachable

```
curl https://abcd1234.ngrok-free.app/health
```

Expected response:

```
{"status": "ok", "channel": "twilio_whatsapp"}
```

### Verify the channel is loaded

```
nanobot plugins list
```

Should show `twilio_whatsapp` as enabled.

## Troubleshooting

### Messages not arriving

*   Check the ngrok inspection UI at http://127.0.0.1:4040 to see if Twilio is sending requests
*   Verify the webhook URL in the Twilio Console matches your current ngrok URL
*   Check nanobot logs for errors (run with `--verbose`)

### 403 Invalid signature

*   Set `validate_signature` to `false` for local testing with ngrok. Signature validation can fail when the URL seen by your server doesn't exactly match the URL Twilio signed (common with tunnels and proxies)

### "Twilio SDK not installed"

*   Run `pip install nanobot-ai[twilio]` or `pip install twilio>=9.0.0`

### Messages not sending (outbound)

*   Verify `from_number` includes the `whatsapp:` prefix (e.g. `whatsapp:+14155238886`)
*   In sandbox mode, the recipient must have joined the sandbox first
*   Check that your Twilio account has sufficient balance

### Media not downloading

*   Media downloads use Basic Auth with your `account_sid` and `auth_token`. Verify these are correct
*   Check that the Twilio media URL is accessible (it expires after a while)

## Running with Docker

The project includes `Dockerfile.twilio` and `docker-compose.twilio.yml` — a slim, pure-Python setup with no Node.js.

### 1\. Configure nanobot

Create or edit `~/.nanobot/config.json` on your host machine with the Twilio settings (see [step 3](#3-configure-nanobot) above). The compose file mounts `~/.nanobot` into the container.

### 2\. Build and start

```
docker compose -f docker-compose.twilio.yml up -d --build
```

Check the logs:

```
docker compose -f docker-compose.twilio.yml logs -f
```

You should see:

```
Twilio WhatsApp webhook listening on :18790/twilio/whatsapp
```

### 3\. Start ngrok

In a separate terminal on the host:

```
ngrok http 18790
```

Then set the ngrok URL in the Twilio Console as described in [step 5](#5-configure-the-twilio-webhook).

## Architecture

```
                    HTTPS                  HTTP (localhost)
WhatsApp User  ---------->  Twilio  ---------->  ngrok  ---------->  nanobot
                                                                      |
                                                                   agent processes
                                                                      |
WhatsApp User  <----------  Twilio  <---------------------------------+
                    API                      Twilio REST API
```

*   **Inbound:** Twilio receives the WhatsApp message and POSTs it to your webhook. The channel parses the form data, downloads any media attachments, and publishes an `InboundMessage` to the message bus.
*   **Outbound:** The agent produces a response, which is sent back via the Twilio REST API (`messages.create`). Long messages are automatically split at the 1600-character Twilio limit.

```
https://abcd1234.ngrok-free.app/twilio/whatsapp
```