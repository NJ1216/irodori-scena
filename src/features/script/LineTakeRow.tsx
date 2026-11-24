import type { DialogueLine, Take } from "../../types";
import { useDestructiveConfirmation } from "../shared/destructiveConfirmation";
import { lineTakeFileName } from "../shared/studio-utils";
import { LineTakePicker } from "./LineTakePicker";

function numberedTakeFileName(lineNumber: number | null, text: string) {
  return lineTakeFileName(lineNumber === null ? 0 : lineNumber, text);
}

function confirmationClass(confirming: boolean, applies = true) {
  return confirming && applies ? "is-confirming" : "";
}

export function LineTakeRow({
  line,
  take,
  lineNumber,
  selected,
  playing,
  busy,
  defaultSpeechRate,
  rewriteTargetLineIds,
  rewriteActionPersistent,
  onNotice,
  onDeleteTake,
  onSelectTake,
  onDelete,
  onPlay,
  onOpenRewriteAssistant,
}: {
  line: DialogueLine;
  take: Take | null | undefined;
  lineNumber: number | null;
  selected: boolean;
  playing: boolean;
  busy: boolean;
  defaultSpeechRate: number;
  rewriteTargetLineIds: string[];
  rewriteActionPersistent: boolean;
  onNotice: (message: string) => void;
  onDeleteTake: (take: Take) => Promise<void>;
  onSelectTake: (takeId: string) => void;
  onDelete: () => Promise<void>;
  onPlay: (url: string, lineId?: string) => void;
  onOpenRewriteAssistant: (lineIds: string[], sourceLineId: string) => void;
}) {
  const deleteConfirmationKey = `delete-line-${line.id}`;
  const confirmingDelete = useDestructiveConfirmation(deleteConfirmationKey);
  const confirmingBatchDelete = useDestructiveConfirmation("delete-selected-lines");
  const actionLineCount = rewriteActionPersistent ? rewriteTargetLineIds.length : 1;
  return (
    <div className="line-take-row">
      <LineTakePicker line={line} downloadFileName={numberedTakeFileName(lineNumber, line.text)} busy={busy} defaultSpeechRate={defaultSpeechRate} onNotice={onNotice} onDeleteTake={onDeleteTake} onSelectTake={onSelectTake} />
      <span
        className={`line-rewrite-action-slot${rewriteActionPersistent ? " is-visible" : ""}`}
        onPointerDown={(event) => {
          event.preventDefault();
          event.stopPropagation();
        }}
        onClick={(event) => event.stopPropagation()}
      >
        {rewriteTargetLineIds.length > 0 && (
          <button
            className="line-rewrite-action ai-action-button"
            type="button"
            disabled={busy}
            onPointerDown={(event) => {
              event.preventDefault();
              event.stopPropagation();
            }}
            onClick={(event) => {
              event.stopPropagation();
              onOpenRewriteAssistant(rewriteTargetLineIds, line.id);
            }}
          >
            ✦ 書き直す
          </button>
        )}
      </span>
      <span className={`line-transient-actions${take ? " has-playback" : ""}`}>
        {take && (
          <button className={playing ? "line-play-toggle is-playing" : "line-play-toggle"} aria-label={playing ? `${actionLineCount}行の再生を停止` : `${actionLineCount}行を台本順に再生`} aria-pressed={playing} onClick={() => onPlay(take.audioUrl, line.id)}>
            {playing ? "■" : "▶"}
          </button>
        )}
        <button
          className={`delete-line ${confirmationClass(confirmingDelete || (confirmingBatchDelete && selected))}`}
          data-preserve-line-selection="true"
          data-destructive-confirmation-key={selected && rewriteActionPersistent ? "delete-selected-lines" : deleteConfirmationKey}
          title="この発話行を削除"
          aria-label="この発話行を削除"
          disabled={busy}
          onClick={() => void onDelete()}
        >
          <svg className="trash-icon" viewBox="0 0 24 24" aria-hidden="true">
            <path d="M4 7h16M10 11v6m4-6v6M9 7l1-2h4l1 2m-9 0 1 13h10l1-13" />
          </svg>
        </button>
      </span>
    </div>
  );
}
