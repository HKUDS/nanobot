# Calendar Skill - Setup Guide

## Prerequisites

- Google account
- Node.js installed
- `clasp` CLI tool

## 1. Install Clasp

```bash
npm install -g @google/clasp
clasp login
```

## 2. Create Apps Script Project

```bash
mkdir calendar-api && cd calendar-api
clasp create --title "Calendar API" --type webapp
```

## 3. Add the Code

Copy the code from [calendar-api.gs](references/calendar-api.gs) to `Code.gs`:

```javascript
// Key parts of the code:
const SECRET_TOKEN = 'your_secret_token_here';  // Change this!

function doGet(e) {
  // Handles: today, week, upcoming, range, create
  // See full code in references/calendar-api.gs
}
```

## 4. Deploy

```bash
# Push code
clasp push

# Deploy as web app
clasp deploy --description "v1"

# Get the URL
clasp deployments
```

**Important:** Set "Execute as: Me" and "Access: Anyone" in deployment settings.

## 5. Save Credentials

Note your:
- **URL:** `https://script.google.com/macros/s/XXX/exec`
- **Token:** The secret you set in the code

## 6. Test

```bash
URL="https://script.google.com/macros/s/XXX/exec"
TOKEN="your_secret_token"

# Test today's events
curl "$URL?action=today&token=$TOKEN"
```

## Update Existing Deployment

```bash
# Get deployment ID
clasp deployments

# Update
clasp deploy -i DEPLOYMENT_ID --description "v2"
```

## Troubleshooting

| Issue | Solution |
|-------|----------|
| 401 error | Check token matches |
| Redirect loop | Use `-L` with curl |
| No events | Check calendar permissions |
| Guests not invited | Ensure `sendInvites: true` in code |

## References

- [calendar-api.gs](references/calendar-api.gs) - The Apps Script code
- [clasp-setup.md](references/clasp-setup.md) - Detailed clasp guide
