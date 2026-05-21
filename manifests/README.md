# winget Manifests for nanobot

This directory contains winget manifest files for publishing [nanobot](https://github.com/HKUDS/nanobot) to the [Windows Package Manager (winget)](https://learn.microsoft.com/en-us/windows/package-manager/).

## How to submit

1. Fork [microsoft/winget-pkgs](https://github.com/microsoft/winget-pkgs)
2. Copy the manifests from `manifests/h/HKUDS/nanobot/<version>/` into `manifests/h/HKUDS/nanobot/<version>/` in your fork
3. Create a pull request against `microsoft/winget-pkgs`

## Manifest structure

Winget v1.9.0 requires a three-file structure per version:

| File | ManifestType | Purpose |
|------|-------------|---------|
| `HKUDS.nanobot.yaml` | `version` | Thin version pointer |
| `HKUDS.nanobot.installer.yaml` | `installer` | Installer URLs and SHA256 hashes |
| `HKUDS.nanobot.locale.en-US.yaml` | `defaultLocale` | Package metadata and description |

## Current status

The manifest uses the Python/PyPI installer approach. Before submitting:
- Update `PackageVersion` in all three files with the actual release version
- Generate SHA256 hashes for the PyPI wheel and update `InstallerSha256`
- Test locally with `winget install --manifest manifests/h/HKUDS/nanobot/<version>/`

## Prerequisites for Windows users

- Python >= 3.11 (or [uv](https://github.com/astral-sh/uv))
- Node.js >= 18 (only needed for WhatsApp channel)

## Alternative install methods

```powershell
# Via uv (recommended)
uv tool install nanobot-ai

# Via pip
pip install nanobot-ai

# Via winget (once published)
winget install HKUDS.nanobot
```
