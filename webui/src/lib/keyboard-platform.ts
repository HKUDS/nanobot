export function isApplePlatform(): boolean {
  if (typeof navigator === "undefined") return false;
  const { platform, userAgentData } = navigator as Navigator & { userAgentData?: { platform?: string } };
  return /mac|iphone|ipad|ipod/i.test(`${platform} ${userAgentData?.platform ?? ""}`);
}
