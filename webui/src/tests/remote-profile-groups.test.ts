import { describe, expect, it } from "vitest";
import { groupRemoteProfiles, type RemoteProfile } from "@/lib/remote-instances";

const profile: RemoteProfile = { id: "one", name: "Team", host: "ubuntu@server", port: 22,
  ssh_config: "", identity_file: "", config_path: "/srv/bot/config.json", runtime_user: "", connected: false };

describe("remote instance grouping", () => {
  it("does not guess from names, addresses, or restart-scoped gateway IDs", () => {
    expect(groupRemoteProfiles([profile, { ...profile, id: "two" }], null)).toHaveLength(2);
    expect(groupRemoteProfiles([{ ...profile, gateway_id: "same" }, { ...profile, id: "two", gateway_id: "same" }], null)).toHaveLength(2);
  });
  it("keeps all grants but selects the current view before a connected or newer grant", () => {
    const old = { ...profile, instance_id: "instance" };
    const renewed = { ...old, id: "two", name: "auto-generated", connected: true };
    const groups = groupRemoteProfiles([old, renewed], "one");
    expect(groups).toHaveLength(1);
    expect(groups[0].connections).toEqual([old, renewed]);
    expect(groups[0].profile.id).toBe("one");
    expect(groupRemoteProfiles([old, renewed], null)[0].profile).toMatchObject({ id: "two", name: "Team" });
  });
  it("prefers a usable grant when none is selected and does not mutate the directory", () => {
    const items = [Object.freeze({ ...profile, instance_id: "same", authorized_until: 1 }),
      Object.freeze({ ...profile, id: "two", instance_id: "same", authorized_until: Date.now() / 1000 + 1000 })];
    expect(groupRemoteProfiles(items, null)[0].profile.id).toBe("two");
    expect(items[0].id).toBe("one");
  });
});
