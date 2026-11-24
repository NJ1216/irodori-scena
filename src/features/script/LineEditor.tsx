import { useId } from "react";
import type { Character, DialogueLine, Take } from "../../types";
import { formatTakeSeconds, selectedTake } from "../shared/studio-utils";

import { CueMemberPicker } from "./CueMemberPicker";
import type { LineTextEditorElement } from "./EmojiTextArea";
import { LineStatusIcon } from "./LineStatusIcon";
import { LineTakeRow } from "./LineTakeRow";
import { useLineCardFocus } from "./useLineCardFocus";
import { LineCfgControls } from "./LineCfgControls";
import { normalizeTargetDuration } from "./targetDuration";
import type { LineSelectionModifiers } from "./linePointerSelection";
import { DeferredNumberInput } from "../shared/DeferredNumberInput";
import { adjustedLineGap } from "./lineGapBatch";
import { adjustedLineNumericValue, type BatchLineNumericField } from "./lineNumericBatch";
import { LineSeedMenu } from "./LineSeedMenu";
import type { LineSeedPatch } from "./lineSeedBatch";
import { LineContentRows } from "./LineContentRows";
import { takeSamplingPresentation } from "../shared/ttsSampling";

function TakeSamplingPill({ take }: { take: Take }) {
  const sampling = takeSamplingPresentation(take);
  return <span className={`quality-pill ${sampling.className}`}>{sampling.label}</span>;
}

function SpeechRateControl({
  line,
  defaultSpeechRate,
  onUpdate,
  onAdjustSelected,
  onSetSelected,
  onPreviewSelected,
}: {
  line: DialogueLine;
  defaultSpeechRate: number;
  onUpdate: (patch: Partial<DialogueLine>) => void;
  onUpdateSeed?: (patch: LineSeedPatch) => void;
  onAdjustSelected?: (field: BatchLineNumericField, directions: readonly (-1 | 1)[]) => void;
  onSetSelected?: (field: BatchLineNumericField, value: number | undefined) => void;
  onPreviewSelected?: (field: BatchLineNumericField, directions: readonly (-1 | 1)[] | null) => void;
}) {
  return (
    <label className="line-gap-control">
      <DeferredNumberInput
        className={line.speechRate === undefined ? "is-shared" : ""}
        min={0.5}
        max={2}
        step={0.05}
        value={line.speechRate}
        placeholder={defaultSpeechRate.toFixed(2)}
        aria-label="発話行ごとの話速"
        data-preserve-line-selection="true"
        onArrowStep={(direction, current) => {
          return adjustedLineNumericValue("speechRate", current, defaultSpeechRate, direction);
        }}
        onArrowCommit={onAdjustSelected ? (_value, directions) => onAdjustSelected("speechRate", directions) : undefined}
        onArrowPreview={onAdjustSelected ? (directions) => onPreviewSelected?.("speechRate", directions) : undefined}
        onPrimaryEnter={onSetSelected ? (value) => onSetSelected("speechRate", value) : undefined}
        onCommit={(value) => onUpdate({ speechRate: value })}
      />
    </label>
  );
}

function LineTimingControl({
  line,
  defaultSpeechRate,
  onUpdate,
  onAdjustSelected,
  onSetSelected,
  onPreviewSelected,
}: {
  line: DialogueLine;
  defaultSpeechRate: number;
  onUpdate: (patch: Partial<DialogueLine>) => void;
  onAdjustSelected?: (field: BatchLineNumericField, directions: readonly (-1 | 1)[]) => void;
  onSetSelected?: (field: BatchLineNumericField, value: number | undefined) => void;
  onPreviewSelected?: (field: BatchLineNumericField, directions: readonly (-1 | 1)[] | null) => void;
}) {
  const seconds = line.targetDurationSeconds !== undefined;
  return (
    <span className="line-timing-control">
      <button type="button" className={`line-timing-mode-toggle ${seconds ? "is-seconds" : ""}`} aria-label="話速と秒指定を切り替え" aria-pressed={seconds} onClick={() => onUpdate({ targetDurationSeconds: seconds ? undefined : 5 })}>
        <LineStatusIcon name="rate" tooltip={seconds ? "生成時の秒数を固定。クリックで話速指定へ切り替え" : "話速（空欄で共通設定）。クリックで秒指定へ切り替え"} />
      </button>
      {seconds ? (
        <label className="line-gap-control target-duration-control">
          <span className="line-number-with-unit">
            <DeferredNumberInput min={0.5} max={30} step={0.1} value={line.targetDurationSeconds} aria-label="生成時の秒数" onCommit={(value) => onUpdate({ targetDurationSeconds: value === undefined ? undefined : normalizeTargetDuration(value) })} />
            <small>秒</small>
          </span>
        </label>
      ) : (
        <SpeechRateControl line={line} defaultSpeechRate={defaultSpeechRate} onUpdate={onUpdate} onAdjustSelected={onAdjustSelected} onSetSelected={onSetSelected} onPreviewSelected={onPreviewSelected} />
      )}
    </span>
  );
}

function LineGapControl({
  gapLine,
  defaultGap,
  effectiveGapSeconds,
  onUpdate,
  onAdjustSelectedGaps,
  onSetSelectedGaps,
  onPreviewSelectedGaps,
}: {
  gapLine: DialogueLine;
  defaultGap: number;
  effectiveGapSeconds?: number;
  onUpdate: (patch: Partial<DialogueLine>) => void;
  onAdjustSelectedGaps?: (directions: readonly (-1 | 1)[]) => void;
  onSetSelectedGaps?: (value: number | undefined) => void;
  onPreviewSelectedGaps?: (directions: readonly (-1 | 1)[] | null) => void;
}) {
  const descriptionId = useId();
  const clamped = effectiveGapSeconds !== undefined;
  const configuredValue = gapLine.gapSeconds ?? "";
  return (
    <label className="line-gap-control">
      <LineStatusIcon name="gap" tooltip={clamped ? `設定値は保持されます。現在の選択テイクでの実効値は ${effectiveGapSeconds.toFixed(1)} 秒です。` : "発話間隔（空欄で共通設定）"} />
      <span className="line-number-with-unit">
        <DeferredNumberInput
          className={gapLine.gapSeconds === undefined ? "is-shared" : ""}
          min={-9999}
          max={9999}
          step={0.1}
          value={configuredValue === "" ? undefined : Number(configuredValue)}
          placeholder={defaultGap.toFixed(1)}
          aria-label="発話行ごとの発話間隔（秒）"
          data-preserve-line-selection="true"
          aria-describedby={clamped ? descriptionId : undefined}
          onArrowStep={(direction, current) => {
            const delta = direction * 0.1;
            return adjustedLineGap(current, defaultGap, delta);
          }}
          onArrowCommit={onAdjustSelectedGaps ? (_value, directions) => onAdjustSelectedGaps(directions) : undefined}
          onArrowPreview={onAdjustSelectedGaps ? onPreviewSelectedGaps : undefined}
          onPrimaryEnter={onSetSelectedGaps}
          onCommit={(value) => onUpdate({ gapSeconds: value })}
        />
        <small>秒</small>
      </span>
      {clamped && (
        <span id={descriptionId} className="visually-hidden">
          設定値を表示しています。現在の選択テイクでは間隔不足を避けるため実効値へ調整されます。
        </span>
      )}
    </label>
  );
}

function lineCardClassName({ line, take, grouped, cueHead, cueTail, focused, selected, playing, generating }: { line: DialogueLine; take: Take | null | undefined; grouped: boolean; cueHead: boolean; cueTail: boolean; focused: boolean; selected: boolean; playing: boolean; generating: boolean }) {
  const cueClasses = grouped ? `is-cue-member ${cueHead ? "is-cue-head" : "is-cue-tail"} ${cueTail ? "is-cue-end" : ""}` : "";
  return `line-card ${take ? "generated" : ""} ${cueClasses} ${focused ? "is-focused" : ""} ${selected ? "is-selected" : ""} ${playing ? "is-playing" : ""} ${generating ? "is-generating" : ""} ${line.enabled === false ? "is-disabled" : ""}`;
}

function LineStartOffsetControl({ line, onUpdate }: { line: DialogueLine; onUpdate: (patch: Partial<DialogueLine>) => void }) {
  return (
    <label className="line-gap-control" title="同時発話内の開始位置">
      <span>開始</span>
      <DeferredNumberInput min={0} max={9999} step={0.1} value={line.startOffsetSeconds ?? 0} aria-label="開始オフセット（秒）" onCommit={(value) => onUpdate({ startOffsetSeconds: value ?? 0 })} />秒
    </label>
  );
}

function LineGenerateActions({
  take,
  busy,
  cueHead,
  availableCueCharacters,
  onAddCueMember,
  onGenerate,
  onRegenerate,
}: {
  take: Take | null | undefined;
  busy: boolean;
  cueHead: boolean;
  availableCueCharacters: Character[];
  onAddCueMember: (characterId: string) => Promise<void>;
  onGenerate: () => Promise<unknown>;
  onRegenerate: () => Promise<unknown>;
}) {
  return (
    <div className="line-actions">
      {cueHead && availableCueCharacters.length > 0 && <CueMemberPicker characters={availableCueCharacters} disabled={busy} onChoose={onAddCueMember} />}
      <span className={`generate-stack${take ? " has-regenerate" : ""}`}>
        {take && (
          <button className="regenerate-hover" data-preserve-line-selection="true" disabled={busy} onClick={() => void onRegenerate()}>
            ↻ 上書き生成
          </button>
        )}
        <button className="generate" data-preserve-line-selection="true" disabled={busy} onClick={() => void onGenerate()}>
          {busy ? "生成中…" : take ? "＋ 新規テイク" : "● 生成"}
        </button>
      </span>
    </div>
  );
}

type LineEditorProps = {
  line: DialogueLine;
  previewLine?: DialogueLine;
  lineNumber: number | null;
  referenceNumber: number;
  characters: Character[];
  defaultGap: number;
  defaultSpeechRate: number;
  cfgDefaults: { textCfg: number; voiceCfg: number; captionCfg?: number };
  supportsRuntimeCfg: boolean;
  focused: boolean;
  selected: boolean;
  playing: boolean;
  generating: boolean;
  busy: boolean;
  captionSupported: boolean;
  onFocusLine: (modifiers?: LineSelectionModifiers) => void;
  onUpdate: (patch: Partial<DialogueLine>) => void;
  onUpdateSeed?: (patch: LineSeedPatch) => void;
  gapLine: DialogueLine;
  previewGapLine?: DialogueLine;
  onUpdateGap: (patch: Partial<DialogueLine>) => void;
  onAdjustSelectedGaps?: (directions: readonly (-1 | 1)[]) => void;
  onSetSelectedGaps?: (value: number | undefined) => void;
  onPreviewSelectedGaps?: (directions: readonly (-1 | 1)[] | null) => void;
  onAdjustSelectedNumericField?: (field: BatchLineNumericField, directions: readonly (-1 | 1)[]) => void;
  onSetSelectedNumericField?: (field: BatchLineNumericField, value: number | undefined) => void;
  onPreviewSelectedNumericField?: (field: BatchLineNumericField, directions: readonly (-1 | 1)[] | null) => void;
  effectiveGapSeconds?: number;
  onNotice: (message: string) => void;
  onCommitContent: (autoRender: boolean) => void;
  onTextFocus: (element: LineTextEditorElement) => void;
  onChangeCharacter: (characterId: string) => Promise<void>;
  onGenerate: () => Promise<unknown>;
  onGenerateWithSeed: (seed: number) => Promise<boolean>;
  onRegenerate: () => Promise<unknown>;
  onDeleteTake: (take: Take) => Promise<void>;
  onDelete: () => Promise<void>;
  onPlay: (url: string, lineId?: string) => void;
  onSelectTake: (takeId: string) => void;
  grouped: boolean;
  cueHead: boolean;
  cueTail: boolean;
  availableCueCharacters: Character[];
  isLastLine: boolean;
  onAddCueMember: (characterId: string) => Promise<void>;
  rewriteTargetLineIds: string[];
  rewriteActionPersistent: boolean;
  onOpenRewriteAssistant: (lineIds: string[], sourceLineId: string) => void;
};

function LineResultStatus({ line, take, generating, onUpdate, onGenerateWithSeed, onNotice }: Pick<LineEditorProps, "line" | "generating" | "onUpdate" | "onGenerateWithSeed" | "onNotice"> & { take: Take | null | undefined }) {
  return (
    <div className="line-result-status">
      <LineSeedMenu line={line} displayedSeed={take?.seed ?? line.manualSeed ?? line.fixedSeed!} generating={generating} onUpdate={onUpdate} onGenerateWithSeed={onGenerateWithSeed} onNotice={onNotice} />
      {take && (
        <>
          <span className="line-meta-item" aria-label={`音声の長さ ${formatTakeSeconds(take.durationSeconds)}`}>
            <LineStatusIcon name="audio" tooltip="音声の長さ" />
            {formatTakeSeconds(take.durationSeconds)}
          </span>
          <span className="line-meta-item" aria-label={`計算時間 ${formatTakeSeconds(take.generationSeconds)}`}>
            <LineStatusIcon name="compute" tooltip="計算時間" />
            {formatTakeSeconds(take.generationSeconds)}
          </span>
          <TakeSamplingPill take={take} />
        </>
      )}
    </div>
  );
}

export function LineEditor({
  line,
  previewLine,
  lineNumber,
  referenceNumber,
  characters,
  defaultGap,
  defaultSpeechRate,
  cfgDefaults,
  supportsRuntimeCfg,
  focused,
  selected,
  playing,
  generating,
  captionSupported,
  busy,
  onFocusLine,
  onNotice,
  onUpdate,
  onUpdateSeed,
  gapLine,
  previewGapLine,
  onUpdateGap,
  onAdjustSelectedGaps,
  onSetSelectedGaps,
  onPreviewSelectedGaps,
  onAdjustSelectedNumericField,
  onSetSelectedNumericField,
  onPreviewSelectedNumericField,
  effectiveGapSeconds,
  onCommitContent,
  onTextFocus,
  onChangeCharacter,
  onGenerate,
  onGenerateWithSeed,
  onRegenerate,
  onDeleteTake,
  onDelete,
  onPlay,
  onSelectTake,
  grouped,
  cueHead,
  cueTail,
  isLastLine,
  availableCueCharacters,
  onAddCueMember,
  rewriteTargetLineIds,
  rewriteActionPersistent,
  onOpenRewriteAssistant,
}: LineEditorProps) {
  const cardFocus = useLineCardFocus({ selected, rewriteActionPersistent, onFocusLine });
  const take = selectedTake(line);
  return (
    <article data-line-id={line.id} className={lineCardClassName({ line, take, grouped, cueHead, cueTail, focused, selected, playing, generating })} tabIndex={0} {...cardFocus}>
      <LineContentRows
        line={line}
        lineNumber={lineNumber}
        referenceNumber={referenceNumber}
        characters={characters}
        busy={busy}
        grouped={grouped}
        cueHead={cueHead}
        captionSupported={captionSupported}
        onUpdate={onUpdate}
        onCommitContent={onCommitContent}
        onTextFocus={onTextFocus}
        onNotice={onNotice}
        onChangeCharacter={onChangeCharacter}
      />
      <div className="line-meta">
        {grouped && <LineStartOffsetControl line={line} onUpdate={onUpdate} />}
        <LineTimingControl line={previewLine ?? line} defaultSpeechRate={defaultSpeechRate} onUpdate={onUpdate} onAdjustSelected={onAdjustSelectedNumericField} onSetSelected={onSetSelectedNumericField} onPreviewSelected={onPreviewSelectedNumericField} />
        {!isLastLine && (!grouped || cueTail) && (
          <LineGapControl gapLine={previewGapLine ?? gapLine} defaultGap={defaultGap} effectiveGapSeconds={effectiveGapSeconds} onUpdate={onUpdateGap} onAdjustSelectedGaps={onAdjustSelectedGaps} onSetSelectedGaps={onSetSelectedGaps} onPreviewSelectedGaps={onPreviewSelectedGaps} />
        )}
        {supportsRuntimeCfg && <LineCfgControls line={previewLine ?? line} defaults={cfgDefaults} focused={focused} onUpdate={onUpdate} onAdjustSelected={onAdjustSelectedNumericField} onSetSelected={onSetSelectedNumericField} onPreviewSelected={onPreviewSelectedNumericField} />}
        {(take || line.fixedSeed !== undefined || line.manualSeed !== undefined) && <LineResultStatus line={line} take={take} generating={generating} onUpdate={onUpdateSeed ?? onUpdate} onGenerateWithSeed={onGenerateWithSeed} onNotice={onNotice} />}
        <LineGenerateActions take={take} busy={busy} cueHead={cueHead} availableCueCharacters={availableCueCharacters} onAddCueMember={onAddCueMember} onGenerate={onGenerate} onRegenerate={onRegenerate} />
      </div>
      <LineTakeRow
        line={line}
        take={take}
        lineNumber={lineNumber}
        selected={selected}
        playing={playing}
        busy={busy}
        defaultSpeechRate={defaultSpeechRate}
        rewriteTargetLineIds={rewriteTargetLineIds}
        rewriteActionPersistent={rewriteActionPersistent}
        onNotice={onNotice}
        onDeleteTake={onDeleteTake}
        onSelectTake={onSelectTake}
        onDelete={onDelete}
        onPlay={onPlay}
        onOpenRewriteAssistant={onOpenRewriteAssistant}
      />
    </article>
  );
}
