import { lazy, Suspense, useRef, useState } from "react";
import type { ReactNode } from "react";
import { createPortal } from "react-dom";
import metadata from "../../../release-metadata.json";
import { openExternal } from "../../api";

const authorUrl = "https://github.com/NJ1216";

function ExternalMetadataLink({ href, children }: { href: string; children: ReactNode }) {
  return (
    <a
      className="version-metadata-link"
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      onClick={(event) => {
        event.preventDefault();
        void openExternal(href);
      }}
    >
      {children}
    </a>
  );
}

const AboutDialog = lazy(() => import("./AboutDialog").then((module) => ({ default: module.AboutDialog })));
export function VersionMenu() {
  const [open, setOpen] = useState(false);
  const trigger = useRef<HTMLButtonElement>(null);
  return (
    <>
      <div className="main-window-footer-item main-window-version-menu">
        <button ref={trigger} type="button" className="main-window-version-trigger" aria-label="バージョン情報">
          <span aria-hidden="true">ⓘ</span>
        </button>
        <div className="main-window-footer-submenu main-window-version-submenu" aria-label="バージョン情報メニュー">
          <dl>
            <div>
              <dt>作者</dt>
              <dd>
                <ExternalMetadataLink href={authorUrl}>{metadata.author}</ExternalMetadataLink>
              </dd>
            </div>
            <div>
              <dt>本体 Version</dt>
              <dd>
                <ExternalMetadataLink href={metadata.repository}>v{metadata.version.replace("-beta", " beta")}</ExternalMetadataLink>
              </dd>
            </div>
          </dl>
          <button type="button" className="quiet-button version-license-link" onClick={() => setOpen(true)}>
            ライセンス情報 <span aria-hidden="true">›</span>
          </button>
        </div>
      </div>
      {open &&
        createPortal(
          <Suspense fallback={<span role="status">読み込み中…</span>}>
            <AboutDialog
              onClose={() => {
                setOpen(false);
                trigger.current?.focus();
              }}
            />
          </Suspense>,
          document.body,
        )}
    </>
  );
}
