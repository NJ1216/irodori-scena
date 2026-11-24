import { useLayoutEffect, useMemo, useRef, useState } from "react";
import { CustomScrollbar, type ScrollbarBoundary, type ScrollbarPlacement } from "./CustomScrollbar";

function SelectorScrollbar({ selector, label, placement, boundary = "window-chrome" }: { selector: string; label: string; placement: ScrollbarPlacement; boundary?: ScrollbarBoundary }) {
  const targetRef = useRef<HTMLElement | null>(null);
  const [target, setTarget] = useState<HTMLElement | null>(null);
  const resolvedTargetRef = useMemo(() => ({ current: target }), [target]);
  useLayoutEffect(() => {
    const resolve = () => {
      const matches = document.querySelectorAll<HTMLElement>(selector);
      const target = matches.item(matches.length - 1);
      if (target === targetRef.current) return;
      targetRef.current = target;
      setTarget(target);
    };
    resolve();
    const observer = new MutationObserver(resolve);
    observer.observe(document.body, { childList: true, subtree: true });
    return () => {
      observer.disconnect();
      targetRef.current = null;
    };
  }, [selector]);
  return target ? <CustomScrollbar targetRef={resolvedTargetRef} label={label} placement={placement} boundary={boundary} /> : null;
}

export function PrimaryScrollbars({ tab }: { tab: string }) {
  const pageScrollbars: Record<string, { selector: string; label: string }> = {
    characters: { selector: ".characters-page:not([hidden])", label: "キャストページ" },
    pronunciation: { selector: ".pronunciation-page:not([hidden])", label: "辞書ページ" },
    draft: { selector: ".draft-page:not([hidden])", label: "AI台本ページ" },
    settings: { selector: ".settings-page:not([hidden])", label: "設定ページ" },
  };
  const pageScrollbar = pageScrollbars[tab];
  return (
    <>
      {tab === "script" ? (
        <>
          <SelectorScrollbar selector=".workspace" label="台本" placement="viewport-end" />
          <SelectorScrollbar selector=".speaker-rail" label="台本のキャストレール" placement="outside-end" />
          <SelectorScrollbar selector=".script-canvas" label="台本キャンバス" placement="viewport-end" />
        </>
      ) : (
        pageScrollbar && <SelectorScrollbar selector={pageScrollbar.selector} label={pageScrollbar.label} placement="inset-end" />
      )}
      <SelectorScrollbar selector=".modal-backdrop > .modal" label="ダイアログ" placement="inset-end" boundary="dialog-chrome" />
    </>
  );
}
