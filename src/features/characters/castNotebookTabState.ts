import { useEffect, useState, type RefObject } from "react";

export const castNotebookTabColors = ["rose", "mint", "lilac", "gold", "sky", "peach"];
export const castNotebookTabTextures = ["grain", "fibers", "grid", "flecks"];

export function useTabScrollEdges(tabsRef: RefObject<HTMLElement | null>, characterCount: number) {
  const [tabScrollEdges, setTabScrollEdges] = useState({ top: true, bottom: true });
  useEffect(() => {
    const tabs = tabsRef.current;
    if (!tabs) return;
    const updateEdges = () => {
      const maximum = Math.max(0, tabs.scrollHeight - tabs.clientHeight);
      setTabScrollEdges({ top: tabs.scrollTop <= 0, bottom: tabs.scrollTop >= maximum - 1 });
    };
    updateEdges();
    tabs.addEventListener("scroll", updateEdges, { passive: true });
    return () => tabs.removeEventListener("scroll", updateEdges);
  }, [tabsRef, characterCount]);
  return tabScrollEdges;
}
