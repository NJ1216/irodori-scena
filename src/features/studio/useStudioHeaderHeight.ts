import { useLayoutEffect, type RefObject } from "react";
import { observeResizeAfterLayout } from "../shared/observeResizeAfterLayout";

export function useStudioHeaderHeight(shell: RefObject<HTMLElement | null>, header: RefObject<HTMLDivElement | null>, enabled: boolean) {
  useLayoutEffect(() => {
    if (!enabled || !shell.current || !header.current) return;
    const update = () => {
      shell.current?.style.setProperty("--studio-header-height", `${Math.ceil(header.current?.getBoundingClientRect().height ?? 0)}px`);
    };
    update();
    return observeResizeAfterLayout(update, [header.current]);
  }, [enabled, header, shell]);
}
