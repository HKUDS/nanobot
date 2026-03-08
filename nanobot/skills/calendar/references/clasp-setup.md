# Setup with Clasp

Clasp is Google's official CLI for managing Apps Script projects.

## Install Clasp

```bash
npm install -g @google/clasp
```

## Login to Google

```bash
clasp login
```

This opens a browser for Google authentication.

## Create New Apps Script Project

```bash
# Create a new project
clasp create --title "Calendar API" --type webapp

# This creates:
# - .clasp.json (project config)
# - appsscript.json (manifest)
```

## Push Code to Google

```bash
# Copy calendar-api.gs to your project folder as Code.gs
cp references/calendar-api.gs Code.gs

# Push to Google Apps Script
clasp push
```

## Deploy as Web App

```bash
# Deploy
clasp deploy --description "Calendar API v1"

# Get deployment URL
clasp deployments
```

Or deploy via web:
1. Run `clasp open` to open in browser
2. Click **Deploy** → **New deployment**
3. Select type: **Web app**
4. Execute as: **Me**
5. Who has access: **Anyone**
6. Click **Deploy**
7. Copy the Web App URL

## Update Code

```bash
# After editing Code.gs locally
clasp push

# Redeploy
clasp deploy --description "Updated version"
```

## Project Structure

```
calendar-clasp/
├── .clasp.json       # Project ID (auto-generated)
├── appsscript.json   # Manifest
└── Code.gs           # Your code (copy from calendar-api.gs)
```

## appsscript.json

```json
{
  "timeZone": "Asia/Jerusalem",
  "dependencies": {},
  "exceptionLogging": "STACKDRIVER",
  "runtimeVersion": "V8",
  "webapp": {
    "executeAs": "USER_DEPLOYING",
    "access": "ANYONE"
  }
}
```

## Configuration

After deployment, update the AUTH_TOKEN in the code:

```javascript
const AUTH_TOKEN = 'your-secret-token-here';
```

Then push and redeploy.

## Useful Commands

```bash
clasp login          # Authenticate
clasp logout         # Sign out
clasp create         # New project
clasp clone <id>     # Clone existing project
clasp pull           # Download from Google
clasp push           # Upload to Google
clasp open           # Open in browser
clasp deploy         # Create deployment
clasp deployments    # List deployments
clasp undeploy <id>  # Remove deployment
clasp logs           # View execution logs
```

## Troubleshooting

### "Script API not enabled"
1. Go to https://script.google.com/home/usersettings
2. Enable "Google Apps Script API"

### "Permission denied"
- Make sure you deployed with "Anyone" access
- Check AUTH_TOKEN matches

### "Not found"
- Use the correct deployment URL (ends with /exec)
- Not the script URL
