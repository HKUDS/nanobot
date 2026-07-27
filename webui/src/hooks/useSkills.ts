import { useEffect, useState } from "react";

import { fetchSkills } from "@/lib/api";
import { isSkillsPayload, SKILLS_CHANGED_EVENT } from "@/lib/skill-events";
import type { SkillSummary } from "@/lib/types";

export function useSkills(token: string): SkillSummary[] {
  const [skills, setSkills] = useState<SkillSummary[]>([]);

  useEffect(() => {
    let cancelled = false;
    const refresh = () => {
      fetchSkills(token)
        .then(({ skills: nextSkills }) => !cancelled && setSkills(nextSkills))
        .catch(() => !cancelled && setSkills([]));
    };
    const onSkillsChanged = (event: Event) => {
      const payload = (event as CustomEvent<unknown>).detail;
      if (!cancelled && isSkillsPayload(payload)) setSkills(payload.skills);
    };

    refresh();
    window.addEventListener(SKILLS_CHANGED_EVENT, onSkillsChanged);
    return () => {
      cancelled = true;
      window.removeEventListener(SKILLS_CHANGED_EVENT, onSkillsChanged);
    };
  }, [token]);

  return skills;
}
