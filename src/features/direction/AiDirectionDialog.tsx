import type { LlmConnection, StudioProject } from "../../types";
import { DialogFooter, DialogHeader, ModalBackdrop } from "../shared/overlays";
import type { ProjectEditSession, ProjectOperation } from "../studio/projectEditSession";
import { AiDirectionProgressDialog } from "./AiDirectionProgressDialog";
import { EmojiSection, ModeSection, NumberRangesSection, RangeSection, TakeSection } from "./AiDirectionSections";
import { useAiDirectionForm } from "./useAiDirectionForm";

type Props = {
  project: StudioProject;
  projectSession: ProjectEditSession;
  connection: LlmConnection;
  onClose: () => void;
  onComplete: (project: StudioProject, lineIds: string[], takeMode: "replace" | "append" | "none", operation: ProjectOperation) => void;
  onNotice: (message: string) => void;
};

function EmptyDirectionDialog({ onClose }: { onClose: () => void }) {
  return (
    <ModalBackdrop onClose={onClose}>
      <section className="modal ai-direction-dialog" role="dialog" aria-modal="true" aria-label="AI演出">
        <DialogHeader title="AI演出" />
        <p>本文とキャストが設定された発話行がありません。</p>
        <DialogFooter>
          <button type="button" onClick={onClose}>
            閉じる
          </button>
        </DialogFooter>
      </section>
    </ModalBackdrop>
  );
}

export function AiDirectionDialog({ project, projectSession, connection, onClose, onComplete, onNotice }: Props) {
  const form = useAiDirectionForm({ project, projectSession, onClose, onComplete, onNotice });
  const { lines, selected, running, job } = form;
  if (!lines.length) return <EmptyDirectionDialog onClose={onClose} />;
  if (job) return <AiDirectionProgressDialog job={job} running={running} setJob={form.setJob} onClose={onClose} />;
  return (
    <ModalBackdrop onClose={running ? () => {} : onClose} disabled={Boolean(running)}>
      <section className="modal ai-direction-dialog" role="dialog" aria-modal="true" aria-label="AI演出">
        <DialogHeader eyebrow="AI DIRECTION" title="台本をまとめて演出する" />
        <>
          <p className="subtle ai-direction-intro">本文とキャストがある発話行だけを更新します。範囲外の直前・直後の行は、流れを読むための文脈としてだけ使います。</p>
          <div className="ai-direction-form">
            <RangeSection lines={lines} start={form.start} end={form.end} overwriteExisting={form.overwriteExisting} onStart={form.setStart} onEnd={form.setEnd} onToggleOverwrite={() => form.setOverwriteExisting((value) => !value)} />
            <ModeSection selected={selected} removed={form.removed} onToggle={form.toggleDirectionMode} />
            {selected.emoji && <EmojiSection allowed={form.allowed} setAllowed={form.setAllowed} targetCasts={form.targetCasts} castEmoji={form.castEmoji} setCastEmoji={form.setCastEmoji} />}
            {(selected.rate || selected.gap) && <NumberRangesSection step={3 + Number(selected.emoji)} selected={selected} ranges={form.ranges} error={form.rangeError} errorField={form.rangeErrorField} onChange={form.setRange} />}
            <TakeSection step={3 + Number(selected.emoji) + Number(selected.rate || selected.gap)} takeMode={form.takeMode} onChange={form.setTakeMode} />
          </div>
          <DialogFooter className="ai-direction-actions">
            <button type="button" className="button-secondary" onClick={onClose}>
              キャンセル
            </button>
            <button type="button" className="button-ai" disabled={!form.enabled || (form.emojiActive && !form.allowed.length) || !connection.model} onClick={() => void form.execute()}>
              AI演出を反映
            </button>
          </DialogFooter>
        </>
      </section>
    </ModalBackdrop>
  );
}
