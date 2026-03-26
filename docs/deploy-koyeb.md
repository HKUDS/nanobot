# Deploying nanobot to Koyeb

This guide covers deploying nanobot to Koyeb using Git-based deployment.

## Prerequisites

1. **Koyeb Account**: Sign up at [koyeb.com](https://www.koyeb.com)
2. **Koyeb CLI**: Install the CLI tool:
   ```bash
   # macOS
   brew install koyeb-cli
   
   # Linux
   curl -fsSL https://koyeb.com/install | bash
   
   # Windows (PowerShell)
   iwr https://koyeb.com/install.ps1 -useb | iex
   ```

3. **Authenticate**: Login to Koyeb:
   ```bash
   koyeb login
   ```

## Quick Deploy (Recommended)

### Option 1: Using the Koyeb Control Panel

1. Go to [app.koyeb.com](https://app.koyeb.com)
2. Click **Create Service**
3. Select **Git** as the deployment method
4. Connect your GitHub account and select the `HKUDS/nanobot` repository
5. Choose the `koyeb` branch
6. Select **Dockerfile** as the builder
7. Configure the service:
   - **Instance type**: Nano (or larger for production)
   - **Region**: Choose your preferred region
   - **Port**: 18790
   - **Routes**: `/:18790`
8. Add environment variables for your API keys:
   - `OPENAI_API_KEY` (or your preferred provider)
   - `ANTHROPIC_API_KEY` (if using Claude)
9. Click **Deploy**

### Option 2: Using the Koyeb CLI

```bash
# Initialize and deploy
koyeb app init nanobot \
  --git \
  --git-branch koyeb \
  --git-builder dockerfile \
  --dockerfile Dockerfile \
  --ports 18790:http \
  --routes /:18790 \
  --env PORT=18790 \
  --instance-type nano \
  --region fra

# Add secrets (API keys)
koyeb secret create OPENAI_API_KEY --app nanobot
koyeb secret create ANTHROPIC_API_KEY --app nanobot
```

## Configuration Files

This project includes the following Koyeb-specific files:

| File | Purpose |
|------|---------|
| `.koyebignore` | Files excluded from deployment triggers |
| `Procfile` | Defines the start command for buildpack deployments |
| `koyeb.yaml` | Service configuration (optional, for reference) |
| `Dockerfile` | Container build instructions |
| `requirements.txt` | Python dependencies |

## Environment Variables

Configure these in the Koyeb control panel or via CLI:

| Variable | Description | Required |
|----------|-------------|----------|
| `PORT` | Gateway port (default: 18790) | Yes |
| `OPENAI_API_KEY` | OpenAI/OpenRouter API key | For OpenAI models |
| `ANTHROPIC_API_KEY` | Anthropic API key | For Claude models |
| `NANOBOT_CONFIG` | Custom config file path | Optional |

## Post-Deployment

### 1. Configure Your Assistant

After deployment, you need to configure nanobot:

```bash
# Access the container shell via Koyeb CLI
koyeb service exec <service-name> -- nanobot onboard --wizard
```

Or mount a persistent volume for configuration:

```bash
koyeb service update nanobot-gateway \
  --volume nanobot-config:/root/.nanobot
```

### 2. Enable Channels (Optional)

For Telegram, WhatsApp, or other channels:

1. Add channel credentials as secrets
2. Update the config via the onboard command
3. Restart the service

### 3. Monitor Your Service

```bash
# View logs
koyeb service logs nanobot-gateway

# Check service status
koyeb service get nanobot-gateway

# View deployment history
koyeb deployment list --app nanobot
```

## Scaling

### Scale to Zero (Cost Saving)

The `koyeb.yaml` configures scale-to-zero for development:

```yaml
scale:
  min: 0  # Scales down when idle
  max: 1
```

For production, consider:

```bash
koyeb service update nanobot-gateway \
  --scale min=1,max=3
```

### Change Instance Type

```bash
# Upgrade resources
koyeb service update nanobot-gateway \
  --instance-type micro  # or: performance, professional
```

## Troubleshooting

### Service Won't Start

1. Check logs: `koyeb service logs nanobot-gateway`
2. Verify API keys are set correctly
3. Ensure the config file exists at `~/.nanobot/config.json`

### Port Binding Issues

The application must bind to the `PORT` environment variable:

```bash
# Verify in logs
koyeb service logs nanobot-gateway | grep "port"
```

### Configuration Persistence

Use a volume for persistent configuration:

```bash
koyeb service update nanobot-gateway \
  --volume nanobot-data:/root/.nanobot
```

## Updating Your Deployment

### Automatic Deployment

By default, Koyeb auto-deploys on every push to the `koyeb` branch.

### Manual Redeployment

```bash
# Redeploy without rebuild
koyeb deployment create --app nanobot --no-rebuild

# Redeploy with rebuild
koyeb deployment create --app nanobot
```

### Rollback

```bash
# List deployments
koyeb deployment list --app nanobot

# Rollback to previous
koyeb deployment rollback --app nanobot
```

## Cost Optimization

1. **Scale to Zero**: Set `min: 0` for development environments
2. **Use Nano Instance**: Start with the smallest instance type
3. **Single Region**: Deploy to one region initially
4. **Monitor Usage**: Check the Koyeb dashboard for resource usage

## Security Best Practices

1. **Use Secrets**: Never commit API keys to git
   ```bash
   koyeb secret create API_KEY --app nanobot
   ```

2. **Private Repository**: Keep your fork private if it contains sensitive config

3. **Restrict Access**: Use Koyeb's private networking for production

4. **Regular Updates**: Keep dependencies updated for security patches

## Support

- **Koyeb Docs**: [www.koyeb.com/docs](https://www.koyeb.com/docs)
- **nanobot Issues**: [github.com/HKUDS/nanobot/issues](https://github.com/HKUDS/nanobot/issues)
- **Discord Community**: [discord.gg/MnCvHqpUGB](https://discord.gg/MnCvHqpUGB)
