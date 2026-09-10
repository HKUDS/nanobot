import { useCallback, useEffect, useRef } from "react";
import { isCapabilitySection, type SettingsSectionKey } from "@/components/settings/contracts";

export function useSettingsScroll(activeSection: SettingsSectionKey, enabled: boolean,
  onSelect: (section: SettingsSectionKey, options?: { replace?: boolean }) => void,
  ready: boolean,
) {
  const container = useRef<HTMLDivElement>(null);
  const observed = useRef<SettingsSectionKey | null>(null);
  const initialized = useRef(false);
  const timer = useRef<ReturnType<typeof setTimeout>>();
  const scrollToSection = useCallback((section: SettingsSectionKey, smooth: boolean) => {
    const root = container.current;
    const key = isCapabilitySection(section) ? "capabilities" : section;
    const target = root?.querySelector<HTMLElement>(`[data-settings-anchor="${key}"]`);
    if (!root || !target) return;
    const top = root.scrollTop + target.getBoundingClientRect().top - root.getBoundingClientRect().top;
    root.scrollTo?.({ top, behavior: smooth && !window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "smooth" : "instant" });
  }, []);
  useEffect(() => {
    clearTimeout(timer.current);
    if (!enabled || !ready) { initialized.current = false; return; }
    if (observed.current === activeSection) { observed.current = null; return; }
    scrollToSection(activeSection, initialized.current);
    initialized.current = true;
  }, [activeSection, enabled, ready, scrollToSection]);
  useEffect(() => () => clearTimeout(timer.current), []);
  const onScroll = () => {
    if (!enabled) return;
    clearTimeout(timer.current);
    timer.current = setTimeout(() => {
      const root = container.current;
      if (!root || root.clientHeight === 0) return;
      const sections = [...root.querySelectorAll<HTMLElement>("[data-settings-anchor]")];
      const boundary = root.getBoundingClientRect().top + Math.min(100, root.clientHeight / 4);
      const current = sections.filter((node) => node.getBoundingClientRect().top <= boundary).at(-1) ?? sections[0];
      const key = current?.dataset.settingsAnchor as SettingsSectionKey | undefined;
      if (key && key !== (isCapabilitySection(activeSection) ? "capabilities" : activeSection)) {
        observed.current = key;
        onSelect(key, { replace: true });
      }
    }, 150);
  };
  const selectSection = (section: SettingsSectionKey) => {
    clearTimeout(timer.current);
    if (section === activeSection) scrollToSection(section, true);
    onSelect(section);
  };
  return { container, onScroll, selectSection };
}
