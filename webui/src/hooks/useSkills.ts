import { useEffect, useState } from "react";

import { fetchSkills } from "@/lib/api";
import { isSkillsPayload, SKILLS_CHANGED_EVENT } from "@/lib/skill-events";
import type { SkillSummary } from "@/lib/types";

export function useSkills(getToken: () => string): SkillSummary[] {
  const [skills, setSkills] = useState<SkillSummary[]>([]);

  useEffect(() => {
    let cancelled = false;
    let payloadVersion = 0;
    const refresh = () => {
      const version = payloadVersion;
      fetchSkills(getToken())
        .then(({ skills: nextSkills }) => {
          if (!cancelled && version === payloadVersion) setSkills(nextSkills);
        })
        .catch(() => {
          if (!cancelled && version === payloadVersion) setSkills([]);
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
    return () => {
      cancelled = true;
      window.removeEventListener(SKILLS_CHANGED_EVENT, onSkillsChanged);
    };
  }, [getToken]);

  return skills;
}
