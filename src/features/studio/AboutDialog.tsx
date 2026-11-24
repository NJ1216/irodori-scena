import { useEffect, useRef, useState } from "react";
import metadata from "../../../release-metadata.json";
import { openExternal } from "../../api";
import { DialogFooter, DialogHeader, ModalBackdrop } from "../shared/overlays";
import { LicenseBrowser } from "./LicenseBrowser";
import { loadLicenseNotices, type Notices } from "./licenseNotices";

export function AboutDialog({ onClose }: { onClose: () => void }) {
  const [notices, setNotices] = useState<Notices | null>(null);
  const [error, setError] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const dialog = useRef<HTMLElement>(null);
  useEffect(() => {
    dialog.current?.focus();
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    void loadLicenseNotices(controller.signal)
      .then((value) => {
        if (!controller.signal.aborted) setNotices(value);
      })
      .catch(() => {
        if (!controller.signal.aborted) setError(true);
      });
    return () => controller.abort();
  }, [attempt]);
  const trapFocus = (event: React.KeyboardEvent<HTMLElement>) => {
    if (event.key !== "Tab") return;
    const elements = Array.from(event.currentTarget.querySelectorAll<HTMLElement>('button, input, a[href], [tabindex="0"]')).filter((element) => element.getClientRects().length > 0 && !element.matches(":disabled"));
    const first = elements[0],
      last = elements.at(-1);
    if (event.shiftKey && (document.activeElement === first || document.activeElement === dialog.current)) {
      event.preventDefault();
      last?.focus();
    } else if (!event.shiftKey && (document.activeElement === last || document.activeElement === dialog.current)) {
      event.preventDefault();
      first?.focus();
    }
  };
  return (
    <ModalBackdrop onClose={onClose}>
      <section ref={dialog} tabIndex={-1} className="modal about-dialog" role="dialog" aria-modal="true" aria-labelledby="about-title" onKeyDown={trapFocus}>
        <DialogHeader title="ライセンス情報" description="本体と使用ライブラリのライセンス・著作権表記を確認できます。" titleId="about-title" />
        {notices ? (
          <LicenseBrowser notices={notices} />
        ) : (
          <div className="license-load-state">
            {error ? (
              <>
                <p role="alert">ライセンス情報を読み込めませんでした。</p>
                <button
                  type="button"
                  className="secondary"
                  onClick={() => {
                    setError(false);
                    setAttempt(attempt + 1);
                  }}
                >
                  再読み込み
                </button>
              </>
            ) : (
              <p className="subtle" role="status">
                ライセンス情報を読み込み中…
              </p>
            )}
          </div>
        )}
        <DialogFooter
          leading={
            <button type="button" className="quiet-button" onClick={() => void openExternal(`${metadata.repository}/blob/v${metadata.version}/THIRD_PARTY_NOTICES.md`)}>
              GitHubで表記を確認
            </button>
          }
        >
          <button type="button" className="secondary" onClick={onClose}>
            閉じる
          </button>
        </DialogFooter>
      </section>
    </ModalBackdrop>
  );
}
