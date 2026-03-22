---
name: vpn
description: Connect to OpenVPN environments via command line. Manages profiles, starts connections in tmux, and prompts user for OTP.
metadata: {"nanobot":{"emoji":"🔐","os":["darwin","linux"],"requires":{"bins":["openvpn","tmux"]}}}
---

# VPN Skill

Connect to OpenVPN environments from nanobot. Uses tmux to run openvpn in an interactive session so the user can enter OTP codes.

## Configuration

VPN profiles are stored in `~/.openvpn/`. Each `.ovpn` file is a named environment.

### Setup profiles

```bash
# Create profile directory
mkdir -p ~/.openvpn

# Copy your .ovpn files and name them by environment
cp /path/to/profile.ovpn ~/.openvpn/work.ovpn
cp /path/to/another.ovpn ~/.openvpn/staging.ovpn
chmod 600 ~/.openvpn/*.ovpn
```

### Optional: credentials file (username + password, NOT OTP)

To skip username/password prompts (OTP still asked interactively):

```bash
# ~/.openvpn/work.auth — line 1: username, line 2: password
echo -e "myuser\nmypassword" > ~/.openvpn/work.auth
chmod 600 ~/.openvpn/work.auth
```

## Commands

### List available VPN profiles

```bash
{baseDir}/scripts/vpn.sh list
```

### Connect to a VPN environment

```bash
{baseDir}/scripts/vpn.sh connect <profile_name>
```

This will:
1. Start openvpn in a tmux session named `vpn-<profile>`
2. If a `.auth` file exists, auto-fill username/password
3. **Prompt the user for OTP code** via a message
4. Print monitoring instructions

### Check VPN status

```bash
{baseDir}/scripts/vpn.sh status [profile_name]
```

Shows whether the VPN is connected, waiting for OTP, or disconnected.

### Disconnect

```bash
{baseDir}/scripts/vpn.sh disconnect <profile_name>
```

### Send OTP code

After the user provides the OTP code:

```bash
{baseDir}/scripts/vpn.sh otp <profile_name> <otp_code>
```

## Typical workflow

1. User says: "connect to work VPN"
2. Run: `{baseDir}/scripts/vpn.sh connect work`
3. Ask user: "Please enter your OTP code"
4. User replies: "123456"
5. Run: `{baseDir}/scripts/vpn.sh otp work 123456`
6. Run: `{baseDir}/scripts/vpn.sh status work` to confirm connected

## Monitoring

```bash
# Attach to VPN tmux session to see logs
tmux -S /tmp/nanobot-vpn.sock attach -t vpn-work

# Detach: Ctrl+b d
```

## Notes

- openvpn requires `sudo`. The script uses `sudo` automatically.
- OTP is entered interactively via tmux send-keys — this avoids storing OTP anywhere.
- Profiles with `static-challenge` in the .ovpn file will prompt OTP separately.
- Profiles without `static-challenge` may need password+OTP concatenated — the script detects this.
