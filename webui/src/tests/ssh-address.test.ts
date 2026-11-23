import { describe, expect, it } from "vitest";
import { parseSSHAddress } from "@/lib/ssh-address";

describe("SSH address import", () => {
  it.each(["team", "ubuntu@example.test", "user@2001:db8::1"])("keeps the address %s", (host) => {
    expect(parseSSHAddress(` ${host} `)).toEqual({ host });
  });
  it("imports quoted paths, a login user and port without running a command", () => {
    expect(parseSSHAddress('ssh -p 2222 -l ubuntu -i "~/.ssh/team key" -F ~/.ssh/work team')).toEqual({
      host: "ubuntu@team", port: 2222, identity_file: "~/.ssh/team key", ssh_config: "~/.ssh/work",
    });
  });
  it("supports attached option values and preserves Windows path separators", () => {
    expect(parseSSHAddress('ssh -p2222 -i "C:\\Users\\User Name\\.ssh\\id_ed25519" team')).toEqual({
      host: "team", port: 2222, identity_file: "C:\\Users\\User Name\\.ssh\\id_ed25519",
    });
    expect(() => parseSSHAddress("ssh -F'bad' host")).toThrow("invalid_ssh_command");
    expect(parseSSHAddress("ssh -i '/tmp/my key' team")).toEqual({ host: "team", identity_file: "/tmp/my key" });
  });
  it.each([
    "", "ssh -p", "ssh -p 0 team", "ssh -p 65536 team", "ssh -p 2.5 team",
    "ssh -p 22 -p 23 team", "ssh -i", 'ssh -i "unterminated team',
    "ssh -l root ubuntu@team", "ssh -l root", "ssh one two", "ssh team -p 22",
    "ssh -o StrictHostKeyChecking=no team", "ssh -J jump team", "ssh -A team",
    "ssh team whoami", "ssh team; whoami", "ssh team && whoami", "ssh team\nwhoami",
    "ssh -i $(touch) team", "ssh -i $HOME/key team", "https://team", "user@host;evil",
  ])("rejects ambiguous or unsupported input without silently discarding it: %s", (text) => {
    expect(() => parseSSHAddress(text)).toThrow("invalid_ssh_command");
  });
});
