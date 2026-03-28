# Deployment Guide

> How to deploy nanobot to staging and production using Docker + GitHub Actions.

## Architecture

```
GitHub (push to main)
  └─► CI (lint, test, typecheck)
       └─► build-push.yml → Docker image → GHCR
            └─► deploy-staging.yml (auto) → self-hosted runner → staging
                 └─► deploy-production.yml (manual, approved) → production
```

Both environments run on the same host as separate Docker Compose projects with
isolated networks, ports, and config directories.

| Property        | Staging                          | Production                       |
|-----------------|----------------------------------|----------------------------------|
| Compose project | `nanobot-staging`                | `nanobot-prod`                   |
| Port            | 18791                            | 18790                            |
| Config dir      | `~/.nanobot-staging/`            | `~/.nanobot/`                    |
| Memory limit    | 512 MB                           | 1 GB                             |
| Knowledge graph | networkx + JSON (in-process)     | networkx + JSON (in-process)     |
| Caddy domain    | `staging.nanobot.internal`       | `nanobot.internal`               |

## Prerequisites

### Self-Hosted GitHub Actions Runner

The CD workflows run on a `self-hosted` runner. Install on the target server:

```bash
# Create runner directory
mkdir -p ~/actions-runner && cd ~/actions-runner

# Download (check https://github.com/actions/runner/releases for latest)
curl -o actions-runner-linux-x64.tar.gz -L \
  https://github.com/actions/runner/releases/download/v2.321.0/actions-runner-linux-x64-2.321.0.tar.gz
tar xzf actions-runner-linux-x64.tar.gz

# Configure (get token from GitHub → Settings → Actions → Runners → New)
./config.sh --url https://github.com/cgajagon/nanobot --token <TOKEN>

# Install as a service
sudo ./svc.sh install
sudo ./svc.sh start
```

### GitHub Secrets

Configure these in **GitHub → Settings → Secrets and variables → Actions**:

| Secret             | Description                        | Example                          |
|--------------------|------------------------------------|----------------------------------|
| `DEPLOY_PATH`      | Absolute path to deploy/ directory | `/home/carlos/nanobot/deploy`    |

The `GITHUB_TOKEN` is automatically available for GHCR authentication.

### GitHub Environment

Create a **`production`** environment in **GitHub → Settings → Environments**:

- Add **required reviewers** (yourself or a team) for deployment approval
- Optionally set a **wait timer** for extra safety

## Configuration

### Production

```bash
# Config lives at ~/.nanobot/config.json (already exists from systemd era)
# Create .env from template:
cp deploy/production/.env.example deploy/production/.env

# Edit with your image tag:
# NANOBOT_IMAGE=ghcr.io/cgajagon/nanobot:latest
```

### Staging

```bash
# Create a separate config directory:
mkdir -p ~/.nanobot-staging
cp ~/.nanobot/config.json ~/.nanobot-staging/config.json

# Adjust staging config as needed (e.g., different channels, test tokens)

# Create .env:
cp deploy/staging/.env.example deploy/staging/.env
```

## Deployment Flow

### Automatic (Staging)

1. Push or merge to `main`
2. CI runs (lint, typecheck, tests)
3. `build-push.yml` builds Docker image and pushes to GHCR
4. `deploy-staging.yml` automatically deploys to staging
5. Verify at `staging.nanobot.internal` (over WireGuard)

### Manual (Production)

1. Go to **Actions → Deploy Production**
2. Click **Run workflow**
3. Enter the image tag (e.g., `sha-abc1234` or `latest`)
4. Wait for environment approval
5. Deployment runs with automatic rollback on failure

### CLI Deployment

For manual deployments outside GitHub Actions:

```bash
# Deploy to staging
bash deploy/deploy.sh --env staging --image ghcr.io/cgajagon/nanobot:sha-abc1234

# Deploy to production
bash deploy/deploy.sh --env production --image ghcr.io/cgajagon/nanobot:sha-abc1234

# Rollback production to previous image
bash deploy/deploy.sh --env production --rollback

# Dry run (show what would happen)
bash deploy/deploy.sh --env staging --image ghcr.io/cgajagon/nanobot:latest --dry-run
```

## Rollback

### Automatic Rollback

The deploy script automatically rolls back if health checks fail after deployment.
Previous image tags are saved in `deploy/<env>/.previous-image`.

### Manual Rollback

```bash
# Via deploy script
bash deploy/deploy.sh --env production --rollback

# Or manually
cd deploy/production
docker compose -p nanobot-prod down
NANOBOT_IMAGE=ghcr.io/cgajagon/nanobot:<previous-tag> docker compose -p nanobot-prod up -d
```

### Revert to Systemd (Emergency)

If Docker deployment is completely broken:

```bash
docker compose -p nanobot-prod -f deploy/production/docker-compose.yml down
systemctl --user enable --now nanobot-gateway
```

## Monitoring

All dashboards are accessible over WireGuard at `10.50.0.1`:

| Service    | URL                              |
|------------|----------------------------------|
| Grafana    | `grafana.internal`               |
| Prometheus | `prometheus.internal`            |
| nanobot    | `nanobot.internal`               |
| staging    | `staging.nanobot.internal`       |

### Health Endpoints

```bash
# Liveness (always 200 if process is running)
curl http://127.0.0.1:18790/health

# Readiness (200 when agent loop is active, 503 otherwise)
curl http://127.0.0.1:18790/ready
```

### Prometheus Integration

Add the scrape config from `deploy/prometheus-snippet.yml` to your Prometheus
configuration at `~/infra/monitoring/prometheus/prometheus.yml`.

### Caddy Integration

Add the reverse proxy config from `deploy/caddy-snippet.conf` to
`/etc/caddy/Caddyfile` and reload: `sudo systemctl reload caddy`.

## Migration from Systemd

To migrate the existing systemd-based deployment to Docker:

```bash
bash deploy/migrate-from-systemd.sh --image ghcr.io/cgajagon/nanobot:latest
```

This script:
1. Stops the `nanobot-gateway` systemd service
2. Deploys via Docker Compose (production)
3. Verifies health
4. Disables the systemd service (unit file preserved as fallback)

If anything goes wrong, it automatically reverts to systemd.

## Security Scanning

Automated scans run on every push, PR, and weekly:

- **pip-audit**: Python dependency vulnerabilities
- **Trivy**: Docker image + IaC config scanning
- **CodeQL**: Static analysis for Python
- **Dependabot**: Weekly dependency update PRs (pip, npm, GitHub Actions)
