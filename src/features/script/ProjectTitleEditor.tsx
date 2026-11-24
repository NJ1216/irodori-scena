/* eslint-disable react-hooks/set-state-in-effect -- This component synchronizes controlled drafts, imperative media, or stable lifecycle owners at explicit boundaries. */
import { useEffect, useRef, useState } from "react";
import { formatProjectPlaybackDuration } from "../shared/studio-utils";
import { observeResizeAfterLayout } from "../shared/observeResizeAfterLayout";

export function ProjectTitleEditor({ title, durationSeconds, onCommit }: { title: string; durationSeconds?: number; onCommit: (title: string) => void }) {
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(title);
  const titleFit = useRef<HTMLSpanElement | null>(null);
  const titleText = useRef<HTMLElement | null>(null);
  const titleMeasure = useRef<HTMLElement | null>(null);
  const [titleScale, setTitleScale] = useState(1);
  useEffect(() => {
    if (!editing) setValue(title);
  }, [title, editing]);
  useEffect(() => {
    if (editing || !titleFit.current || !titleMeasure.current) return;
    const updateScale = () => {
      const available = titleFit.current?.clientWidth ?? 0;
      const naturalWidth = titleMeasure.current?.getBoundingClientRect().width ?? 0;
      setTitleScale(available && naturalWidth ? Math.min(1, available / naturalWidth) : 1);
    };
    const frame = window.requestAnimationFrame(updateScale);
    const stopObserving = observeResizeAfterLayout(updateScale, [titleFit.current]);
    return () => {
      window.cancelAnimationFrame(frame);
      stopObserving();
    };
  }, [title, editing]);
  const commit = () => {
    const next = value.trim();
    setValue(next);
    setEditing(false);
    if (next !== title) onCommit(next);
  };
  const formattedDuration = durationSeconds === undefined ? undefined : formatProjectPlaybackDuration(durationSeconds);
  return (
    <div className={`script-title-editor ${formattedDuration ? "has-duration" : ""}`}>
      {editing ? (
        <div className="script-title-edit">
          <small>SCRIPT TITLE</small>
          <input
            autoFocus
            value={value}
            aria-label="台本タイトル"
            onChange={(event) => setValue(event.currentTarget.value)}
            onBlur={commit}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                event.preventDefault();
                event.currentTarget.blur();
              }
              if (event.key === "Escape") {
                event.preventDefault();
                setValue(title);
                setEditing(false);
              }
            }}
          />
        </div>
      ) : (
        <button className="script-title-display" title="クリックしてタイトルを編集" onClick={() => setEditing(true)}>
          <small>SCRIPT TITLE</small>
          <span ref={titleFit} className="script-title-fit">
            <strong ref={titleText} style={{ transform: `scaleX(${titleScale})` }}>
              {title}
            </strong>
          </span>
          <span ref={titleMeasure} className="script-title-measure" aria-hidden="true">
            {title}
          </span>
        </button>
      )}
      {formattedDuration && (
        <span className="script-title-duration" aria-label={`総合時間 ${formattedDuration}`}>
          <svg aria-hidden="true" viewBox="0 0 24 24" focusable="false">
            <circle cx="12" cy="13" r="8" />
            <path d="M12 9v4l3 2M9 2h6M12 5V2" />
          </svg>
          {formattedDuration}
        </span>
      )}
    </div>
  );
}
