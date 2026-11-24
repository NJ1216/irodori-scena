import { useEffect, useRef, useState } from "react";
import type { DialogueLine } from "../../types";

type ContentPatch = Pick<DialogueLine, "text" | "stageDirection" | "pronunciations">;

/** Keeps keystrokes row-local while ProjectEditSession retains the matching save overlay. */
export function useLineContentDraft(line: DialogueLine, onUpdate: (patch: Partial<DialogueLine>) => void, onCommit: (autoRender: boolean) => void) {
  const [draft, setDraft] = useState<ContentPatch>(() => ({ text: line.text, stageDirection: line.stageDirection, pronunciations: line.pronunciations }));
  const dirty = useRef(false);
  const lineId = useRef(line.id);

  useEffect(() => {
    if (lineId.current !== line.id) {
      lineId.current = line.id;
      dirty.current = false;
    }
    if (!dirty.current) setDraft({ text: line.text, stageDirection: line.stageDirection, pronunciations: line.pronunciations });
  }, [line.id, line.pronunciations, line.stageDirection, line.text]);

  const update = (patch: Partial<ContentPatch>) => {
    dirty.current = true;
    setDraft((current) => ({ ...current, ...patch }));
    onUpdate(patch);
  };
  const commit = (autoRender: boolean) => {
    onCommit(autoRender);
    dirty.current = false;
  };
  return { draft, update, commit };
}
