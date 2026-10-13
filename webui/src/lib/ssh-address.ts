/** Import connection fields, never execute a pasted command or shell syntax. */
export interface SSHAddress {
  host: string;
  port?: number;
  identity_file?: string;
  ssh_config?: string;
}

export function parseSSHAddress(input: string): SSHAddress {
  const text = input.trim();
  const invalid = () => new Error("invalid_ssh_command");
  const validHost = (host: string) => /^[a-zA-Z0-9][a-zA-Z0-9._:@-]{0,252}$/.test(host);
  if (!/^ssh\s/.test(text)) {
    if (!validHost(text)) throw invalid();
    return { host: text };
  }
  // A deliberately small grammar: quoted paths (including Windows paths),
  // a destination and -p/-i/-F/-l. No expansions, remote commands or flags
  // that change trust, forwarding, or execute a local ProxyCommand.
  if (/[;$`|&<>]/.test(text) || [...text].some((char) => char.charCodeAt(0) < 32 && char !== "\t")) throw invalid();
  const token = /\s*(?:"([^"]*)"|'([^']*)'|([^\s"']+))(?:\s+|$)/gy;
  const words: string[] = [];
  while (token.lastIndex < text.length) {
    const match = token.exec(text);
    if (!match) throw invalid();
    words.push(match[1] ?? match[2] ?? match[3]);
  }
  words.shift(); // ssh
  const result: SSHAddress = { host: "" };
  const seen = new Set<string>();
  let user = "";
  for (let index = 0; index < words.length; index++) {
    const word = words[index];
    if (!word.startsWith("-")) {
      if (result.host || !validHost(word)) throw invalid();
      result.host = word;
      continue;
    }
    // Options after the destination are a remote command in ssh, not options.
    if (result.host) throw invalid();
    const flag = word.slice(0, 2);
    if (!["-p", "-i", "-F", "-l"].includes(flag) || seen.has(flag)) throw invalid();
    seen.add(flag);
    const value = word.length > 2 ? word.slice(2) : words[++index];
    if (!value || value.startsWith("-") || value.length > 2048) throw invalid();
    if (flag === "-p") {
      if (!/^\d+$/.test(value) || Number(value) < 1 || Number(value) > 65535) throw invalid();
      result.port = Number(value);
    } else if (flag === "-i") result.identity_file = value;
    else if (flag === "-F") result.ssh_config = value;
    else {
      if (!/^[a-zA-Z0-9_][a-zA-Z0-9._-]*$/.test(value)) throw invalid();
      user = value;
    }
  }
  if (!result.host || (user && result.host.includes("@"))) throw invalid();
  if (user) result.host = `${user}@${result.host}`;
  if (!validHost(result.host)) throw invalid();
  return result;
}
