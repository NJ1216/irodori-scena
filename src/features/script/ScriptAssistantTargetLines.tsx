import { useState } from "react";
import type { DialogueLine, StudioProject } from "../../types";
import { numberedScriptLines } from "./scriptLineNumbers";
import { cueLineIds } from "./dialogueCues";
import { formatTargetLineNumbers, targetLineNumberRanges } from "./scriptAssistantTargetLineNumbers";

export type AssistantTargetLine = {
  line: DialogueLine;
  lineNumber: number | null;
};

export function ScriptAssistantTargetLines({ lines, project, originalIds, onChange }: { lines: AssistantTargetLine[]; project: StudioProject; originalIds: string[]; onChange: (ids: string[]) => void }) {
  const all = project.scenes.flatMap((scene) => scene.lines.map((line) => ({ scene, line })));
  const numbers = new Map(numberedScriptLines(project).map((item) => [item.lineId, item.number ?? item.referenceNumber]));
  const first = lines[0]?.line.id ?? all[0]?.line.id ?? "";
  const last = lines.at(-1)?.line.id ?? first;
  const [editing, setEditing] = useState(false);
  const [start, setStart] = useState(first);
  const [end, setEnd] = useState(last);
  const original = new Set(originalIds);
  const changed = lines.length !== original.size || lines.some(({ line }) => !original.has(line.id));
  const apply = () => {
    const startIndex = all.findIndex(({ line }) => line.id === start);
    const endIndex = all.findIndex(({ line }) => line.id === end);
    if (startIndex < 0 || endIndex < 0) return;
    const selected = new Set(all.slice(Math.min(startIndex, endIndex), Math.max(startIndex, endIndex) + 1).flatMap(({ line }) => cueLineIds(project, line.id)));
    onChange(all.filter(({ line }) => selected.has(line.id)).map(({ line }) => line.id));
    setEditing(false);
  };
  const begin = () => {
    setStart(first);
    setEnd(last);
    setEditing(true);
  };
  return (
    <section className="script-assistant-step" aria-labelledby="script-assistant-target-lines-heading">
      <div id="script-assistant-target-lines-heading">
        <h3 className="draft-step-heading script-assistant-step-heading">
          <span aria-hidden="true">
            <span className="circle-number-glyph">1</span>
          </span>
          対象の行
        </h3>
      </div>
      <div className="script-assistant-target-toolbar">
        <p className="script-assistant-target-lines" aria-label={`書き直し対象 ${lines.length}行: ${formatTargetLineNumbers(lines)}`}>
          {targetLineNumberRanges(lines).map(([start, end], index) => (
            <span key={start} className="script-assistant-target-range">
              {index > 0 && <span className="script-assistant-target-separator">、</span>}
              <span className="script-assistant-target-number">{start}</span>
              {end !== start && (
                <>
                  <span>〜</span>
                  <span className="script-assistant-target-number">{end}</span>
                </>
              )}
            </span>
          ))}
        </p>
        <button type="button" className="secondary" onClick={begin}>
          編集
        </button>
        {changed && (
          <button type="button" className="secondary" onClick={() => onChange(originalIds)}>
            元の選択に戻す
          </button>
        )}
      </div>
      {editing && (
        <div className="script-assistant-range-editor">
          {(["開始", "終了"] as const).map((label) => (
            <label key={label}>
              {label}
              <select aria-label={`${label}行`} value={label === "開始" ? start : end} onChange={(event) => (label === "開始" ? setStart : setEnd)(event.target.value)}>
                {all.map(({ scene, line }) => (
                  <option key={line.id} value={line.id}>
                    {scene.title} · {numbers.get(line.id)}行 · {line.text || "（本文なし）"}
                  </option>
                ))}
              </select>
            </label>
          ))}
          <div className="script-assistant-range-actions">
            <button type="button" className="secondary" onClick={() => setEditing(false)}>
              キャンセル
            </button>
            <button type="button" className="primary" onClick={apply}>
              適用
            </button>
          </div>
        </div>
      )}
    </section>
  );
}
