import { useLayoutEffect, useState, type RefObject } from "react";
import { notebookActionSpacerHeight } from "./cast-notebook-layout";

export function useNotebookActionSpacer(pageRef: RefObject<HTMLElement | null>, contentRef: RefObject<HTMLDivElement | null>, actionsRef: RefObject<HTMLDivElement | null>, activeCharacterId: string, activeSpread: number) {
  const [actionSpacerHeight, setActionSpacerHeight] = useState(0);
  useLayoutEffect(() => {
    const page = pageRef.current;
    const content = contentRef.current;
    const actions = actionsRef.current;
    if (!page || !content || !actions) return;
    const updateActionSpacer = () => {
      const pageStyle = getComputedStyle(page);
      const ruleHeight = Number.parseFloat(pageStyle.getPropertyValue("--cast-notebook-rule-height"));
      const contentEnd = content.getBoundingClientRect().bottom - page.getBoundingClientRect().top;
      const lastLineTop = page.clientHeight - Number.parseFloat(pageStyle.paddingBottom) - actions.offsetHeight;
      const nextSpacerHeight = notebookActionSpacerHeight({
        contentEnd,
        lastLineTop,
        ruleHeight,
      });
      setActionSpacerHeight((current) => (current === nextSpacerHeight ? current : nextSpacerHeight));
    };
    updateActionSpacer();
    const observer = new ResizeObserver(updateActionSpacer);
    observer.observe(page);
    observer.observe(content);
    observer.observe(actions);
    return () => observer.disconnect();
  }, [activeCharacterId, activeSpread, actionsRef, contentRef, pageRef]);
  return actionSpacerHeight;
}
