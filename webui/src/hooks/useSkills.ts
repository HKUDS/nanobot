import { useEffect, useState } from "react";

import { fetchSkills } from "@/lib/api";
import { isSkillsPayload, SKILLS_CHANGED_EVENT, SKILLS_REFRESH_EVENT } from "@/lib/skill-events";
import type { SkillSummary } from "@/lib/types";

export function useSkills(getToken: () => string): SkillSummary[] {
  const [skills, setSkills] = useState<SkillSummary[]>([]);

  useEffect(() => {
    let cancelled = false;
    let payloadVersion = 0;
    let refreshing = false;
    const refresh = () => {
      if (cancelled || refreshing) return;
      refreshing = true;
      const version = payloadVersion;
      fetchSkills(getToken())
        .then(({ skills: nextSkills }) => {
          if (!cancelled && version === payloadVersion) setSkills(nextSkills);
        })
        .catch(() => {
          // Keep the last known list usable during transient refresh failures.
        })
        .finally(() => {
          refreshing = false;
        });
    };
    const onSkillsChanged = (event: Event) => {
      const payload = (event as CustomEvent<unknown>).detail;
      if (!cancelled && isSkillsPayload(payload)) {
        payloadVersion += 1;
        setSkills(payload.skills);
      }
    };

    refresh();
    window.addEventListener(SKILLS_CHANGED_EVENT, onSkillsChanged);
    window.addEventListener(SKILLS_REFRESH_EVENT, refresh);
    return () => {
      cancelled = true;
      window.removeEventListener(SKILLS_CHANGED_EVENT, onSkillsChanged);
      window.removeEventListener(SKILLS_REFRESH_EVENT, refresh);
    };
  }, [getToken]);

  return skills;
}
