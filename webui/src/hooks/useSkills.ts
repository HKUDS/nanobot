import { useEffect, useState } from "react";

import { fetchSkills } from "@/lib/api";
import { isSkillsPayload, SKILLS_CHANGED_EVENT, SKILLS_REFRESH_EVENT } from "@/lib/skill-events";
import type { SkillSummary } from "@/lib/types";

type SkillsState =
  | { status: "loading" | "error"; skills: null }
  | { status: "ready"; skills: SkillSummary[] };

const EMPTY_SKILLS: SkillSummary[] = [];

export function useSkills(getToken: () => string) {
  const [state, setState] = useState<SkillsState>({ status: "loading", skills: null });

  useEffect(() => {
    let cancelled = false;
    let payloadVersion = 0;
    let refreshing = false;
    let refreshQueued = false;
    const refresh = () => {
      if (cancelled) return;
      if (refreshing) {
        // The in-flight response may predate installation. Keep one trailing refresh.
        refreshQueued = true;
        return;
      }
      refreshing = true;
      refreshQueued = false;
      setState((current) => current.skills === null ? { status: "loading", skills: null } : current);
      const version = payloadVersion;
      fetchSkills(getToken())
        .then(({ skills: nextSkills }) => {
          if (!cancelled && version === payloadVersion) setState({ status: "ready", skills: nextSkills });
        })
        .catch(() => {
          if (!cancelled && version === payloadVersion) {
            setState((current) => current.skills === null ? { status: "error", skills: null } : current);
          }
        })
        .finally(() => {
          refreshing = false;
          if (refreshQueued) refresh();
        });
    };
    const onSkillsChanged = (event: Event) => {
      const payload = (event as CustomEvent<unknown>).detail;
      if (!cancelled && isSkillsPayload(payload)) {
        payloadVersion += 1;
        setState({ status: "ready", skills: payload.skills });
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

  return {
    skills: state.skills ?? EMPTY_SKILLS,
    loading: state.status === "loading",
    error: state.status === "error",
  };
}
