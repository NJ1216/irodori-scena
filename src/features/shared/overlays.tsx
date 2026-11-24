/* eslint-disable react-hooks/refs -- This component synchronizes controlled drafts, imperative media, or stable lifecycle owners at explicit boundaries. */
import { useEffect, useLayoutEffect, useRef, type ReactNode } from "react";
import { registerModalFileDrop } from "./modalFileDrop";

let nextModalLayer = 100;
const mountedModalLayers = new Set<number>();

export function DialogHeader({ title, eyebrow, description, titleId, actions, children, className = "" }: { title: ReactNode; eyebrow?: ReactNode; description?: ReactNode; titleId?: string; actions?: ReactNode; children?: ReactNode; className?: string }) {
  return (
    <>
      <header className={`dialog-header${className ? ` ${className}` : ""}`}>
        <div className="dialog-header-copy">
          {eyebrow ? <p className="eyebrow">{eyebrow}</p> : null}
          <h2 id={titleId}>{title}</h2>
        </div>
        {actions ? <div className="dialog-header-actions">{actions}</div> : null}
        {children}
      </header>
      {description ? (
        <div className="dialog-intro">
          <p className="subtle">{description}</p>
        </div>
      ) : null}
    </>
  );
}

export function DialogFooter({ children, leading, className = "" }: { children: ReactNode; leading?: ReactNode; className?: string }) {
  return (
    <footer className={`dialog-footer modal-actions${leading ? " has-leading" : ""}${className ? ` ${className}` : ""}`}>
      {leading ? <div className="dialog-footer-leading">{leading}</div> : null}
      {children}
    </footer>
  );
}

export function ModalBackdrop({ children, onClose, disabled = false, fileDropPolicy = "block" }: { children: ReactNode; onClose: () => void; disabled?: boolean; fileDropPolicy?: "dismiss" | "block" }) {
  const layer = useRef<number | null>(null);
  if (layer.current === null) layer.current = nextModalLayer++;
  const layerValue = layer.current;
  useEffect(() => {
    mountedModalLayers.add(layerValue);
    const unregisterFileDrop = registerModalFileDrop(layerValue, { policy: disabled ? "block" : fileDropPolicy, dismiss: onClose });
    return () => {
      mountedModalLayers.delete(layerValue);
      unregisterFileDrop();
    };
  }, [disabled, fileDropPolicy, layerValue, onClose]);
  useEffect(() => {
    const cancelWithEscape = (event: KeyboardEvent) => {
      if (event.key !== "Escape" || disabled || layerValue !== Math.max(...mountedModalLayers)) return;
      event.preventDefault();
      onClose();
    };
    window.addEventListener("keydown", cancelWithEscape);
    return () => window.removeEventListener("keydown", cancelWithEscape);
  }, [disabled, layerValue, onClose]);
  return (
    <div
      className="modal-backdrop"
      data-dismiss-disabled={disabled ? "true" : undefined}
      style={{ zIndex: layerValue }}
      onMouseDown={(event) => {
        if (!disabled && event.target === event.currentTarget) onClose();
      }}
    >
      {children}
    </div>
  );
}

export function OverlayDismissal() {
  useEffect(() => {
    const closeTopmostDialog = () => {
      const overlays = Array.from(document.querySelectorAll<HTMLElement>(".modal-backdrop"));
      const overlay = overlays.reduce<HTMLElement | null>((topmost, candidate) => {
        if (!topmost) return candidate;
        const topmostLayer = Number.parseInt(window.getComputedStyle(topmost).zIndex, 10) || 0;
        const candidateLayer = Number.parseInt(window.getComputedStyle(candidate).zIndex, 10) || 0;
        return candidateLayer >= topmostLayer ? candidate : topmost;
      }, null);
      if (!overlay) return;
      if (overlay.dataset.dismissDisabled === "true") return;
      const cancel = Array.from(overlay.querySelectorAll<HTMLButtonElement>("button")).find((button) => ["キャンセル", "閉じる", "やめる"].includes(button.textContent?.trim() ?? ""));
      if (!cancel) return;
      cancel.click();
    };
    const closeWithBackdrop = (event: MouseEvent) => {
      if (event.target instanceof HTMLElement && event.target.classList.contains("modal-backdrop")) closeTopmostDialog();
    };
    const closeWithEscape = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      closeTopmostDialog();
    };
    document.addEventListener("mousedown", closeWithBackdrop);
    window.addEventListener("keydown", closeWithEscape);
    return () => {
      document.removeEventListener("mousedown", closeWithBackdrop);
      window.removeEventListener("keydown", closeWithEscape);
    };
  }, []);
  return null;
}

export function CastTerminology() {
  useLayoutEffect(() => {
    const normalize = (root: Node) => {
      const textNodes = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
      let textNode: Text | null;
      while ((textNode = textNodes.nextNode() as Text | null)) {
        if (textNode.nodeValue?.includes("話者")) {
          textNode.nodeValue = textNode.nodeValue.replaceAll("話者", "キャスト");
        }
      }
      const elements = root instanceof Element ? [root, ...root.querySelectorAll("*")] : [];
      for (const element of elements) {
        for (const attribute of ["aria-label", "title", "placeholder"]) {
          const value = element.getAttribute(attribute);
          if (value?.includes("話者")) {
            element.setAttribute(attribute, value.replaceAll("話者", "キャスト"));
          }
        }
      }
    };
    normalize(document.body);
    const observer = new MutationObserver(() => normalize(document.body));
    observer.observe(document.body, {
      childList: true,
      characterData: true,
      subtree: true,
    });
    return () => observer.disconnect();
  }, []);
  return null;
}

export function NoticeText({ text }: { text: string }) {
  return (
    <span className="notice-message">
      <span className="notice-screen-reader-text">{text}</span>
      <span className="notice-characters" aria-hidden="true">
        {Array.from(text).map((character, index) => (
          <span className="notice-character" key={`${index}-${character}`} style={{ animationDelay: `${index * 24}ms` }} onAnimationEnd={(event) => event.currentTarget.classList.add("is-settled")}>
            {character === " " ? "\u00a0" : character}
          </span>
        ))}
      </span>
    </span>
  );
}
