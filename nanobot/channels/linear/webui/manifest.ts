export function linearManifestUrl(
  publicBaseUrl: string,
  webhookPath: string,
  callbackPath: string,
): string {
  const manifest = {
    $schema: "https://linear.app/.well-known/oauth-app-manifest.schema.json",
    schemaVersion: "1.0.0",
    distribution: "private",
    display: {
      description: "Mention or delegate issues to nanobot as a native Linear agent.",
      iconUrl: "https://raw.githubusercontent.com/HKUDS/nanobot/main/images/nanobot_logo.png",
    },
    developer: { name: "nanobot" },
    oauth: {
      client_name: "nanobot Agent",
      client_uri: "https://github.com/HKUDS/nanobot",
      redirect_uris: [`${publicBaseUrl}${callbackPath}`],
      grant_types: ["authorization_code"],
    },
    webhook: {
      enabled: true,
      url: `${publicBaseUrl}${webhookPath}`,
      resourceTypes: [
        "AgentSessionEvent",
        "PermissionChange",
        "OAuthAuthorization",
      ],
    },
  };
  return `https://linear.app/settings/api/applications/new?${new URLSearchParams({
    manifest: JSON.stringify(manifest),
  })}`;
}
