import { useId } from "react";
import type { Character, StudioProject } from "../../types";
import { CastSettingsTable } from "../draft/DraftComposerForm";
import { PerformanceSettingsFields } from "../draft/DraftPerformanceSettings";
import type { DraftCastSettings, DraftPerformanceSettings, LineAssistantTarget } from "../studio/types";
import { StepHeading as SharedStepHeading } from "../shared/StepHeading";
import { ScriptAssistantCastPicker } from "./ScriptAssistantCastPicker";
import { type AssistantTargetLine, ScriptAssistantTargetLines } from "./ScriptAssistantTargetLines";

export type RewriteMode = "paraphrase" | "rewrite" | "cast-compose";
export type TargetKind = "lines" | "minutes";

type SettingsProps = {
  target: LineAssistantTarget;
  project: StudioProject;
  onTargetLineIds: (ids: string[]) => void;
  targetLines: AssistantTargetLine[];
  characters: Character[];
  operation: string;
  rewriteMode: RewriteMode;
  onRewriteMode: (value: RewriteMode) => void;
  characterIds: string[];
  onCharacterIds: (value: string[]) => void;
  requiredSpeakerIds: string[];
  fixedCount: boolean;
  targetLineCount: number;
  targetKind: TargetKind;
  onTargetKind: (value: TargetKind) => void;
  lineCount: string;
  onLineCount: (value: string) => void;
  minutes: string;
  onMinutes: (value: string) => void;
  instruction: string;
  onInstruction: (value: string) => void;
  castSettings: Record<string, DraftCastSettings>;
  onCastSetting: (id: string, patch: Partial<DraftCastSettings>) => void;
  simultaneousCues: boolean;
  onSimultaneousCues: (value: boolean) => void;
  overlappingSpeech: boolean;
  onOverlappingSpeech: (value: boolean) => void;
  performance: DraftPerformanceSettings;
  onPerformance: (value: DraftPerformanceSettings) => void;
  sparse: boolean;
  busy: boolean;
  onRefine: () => void;
  onSuggestRandom: () => void;
  onGenerate: () => void;
};

function StepHeading({ number, children }: { number: number; children: string }) {
  return (
    <SharedStepHeading number={number} level="h3" className="draft-step-heading script-assistant-step-heading">
      {children}
    </SharedStepHeading>
  );
}

function GenerationTargetFields({ fixedCount, targetLineCount, targetKind, onTargetKind, lineCount, onLineCount, minutes, onMinutes }: Pick<SettingsProps, "fixedCount" | "targetLineCount" | "targetKind" | "onTargetKind" | "lineCount" | "onLineCount" | "minutes" | "onMinutes">) {
  return (
    <div className="script-assistant-target">
      <label>
        生成目標
        <select value={fixedCount ? "lines" : targetKind} disabled={fixedCount} onChange={(event) => onTargetKind(event.currentTarget.value as TargetKind)}>
          <option value="lines">発話行数</option>
          <option value="minutes">分</option>
        </select>
      </label>
      {fixedCount || targetKind === "lines" ? (
        <span className="script-assistant-unit-input">
          <input aria-label="行数" type="number" min={1} max={fixedCount ? 1000 : 100} value={fixedCount ? targetLineCount : lineCount} disabled={fixedCount} onChange={(event) => onLineCount(event.currentTarget.value)} />
          <span aria-hidden="true">行</span>
        </span>
      ) : (
        <span className="script-assistant-unit-input">
          <input aria-label="分" type="number" min={0.5} max={30} step={0.5} value={minutes} onChange={(event) => onMinutes(event.currentTarget.value)} />
          <span aria-hidden="true">分</span>
        </span>
      )}
    </div>
  );
}

function RewriteModeStep({ rewriteMode, onRewriteMode }: Pick<SettingsProps, "rewriteMode" | "onRewriteMode">) {
  return (
    <section className="script-assistant-step" aria-labelledby="script-assistant-mode-heading">
      <div id="script-assistant-mode-heading">
        <StepHeading number={2}>書き直し方式</StepHeading>
      </div>
      <fieldset className="script-assistant-mode">
        <legend className="visually-hidden">書き直し方式</legend>
        <div className="script-assistant-mode-choice">
          <label>
            <input type="radio" checked={rewriteMode === "paraphrase"} onChange={() => onRewriteMode("paraphrase")} />
            同じ内容の言い換え
          </label>
          <p>内容と行数を保ち、表現とリズムを変えます</p>
        </div>
        <div className="script-assistant-mode-choice">
          <label>
            <input type="radio" checked={rewriteMode === "rewrite"} onChange={() => onRewriteMode("rewrite")} />
            完全に書き直す
          </label>
          <p>前後のつながりだけ守り、会話の運びから組み直します</p>
        </div>
        <div className="script-assistant-mode-choice">
          <label>
            <input type="radio" checked={rewriteMode === "cast-compose"} onChange={() => onRewriteMode("cast-compose")} />
            キャスト構成
          </label>
          <p>話者と行数を保ち、キャスト設定から外れたセリフを整えます</p>
        </div>
      </fieldset>
    </section>
  );
}

function CastStep({
  characters,
  characterIds,
  onCharacterIds,
  requiredSpeakerIds,
  operation,
  busy,
  castSettings,
  onCastSetting,
  sparse,
  number,
  showSettings = true,
}: Pick<SettingsProps, "characters" | "characterIds" | "onCharacterIds" | "requiredSpeakerIds" | "operation" | "busy" | "castSettings" | "onCastSetting" | "sparse"> & { number: number; showSettings?: boolean }) {
  const selected = characters.filter((character) => characterIds.includes(character.id));
  return (
    <section className="script-assistant-step" aria-labelledby="script-assistant-casts-heading">
      <div id="script-assistant-casts-heading">
        <StepHeading number={number}>対象キャスト</StepHeading>
      </div>
      <fieldset className="script-assistant-casts">
        <legend className="visually-hidden">生成対象キャスト</legend>
        <ScriptAssistantCastPicker characters={characters} selectedIds={characterIds} requiredIds={operation === "paraphrase" ? requiredSpeakerIds : []} busy={busy} onChange={onCharacterIds} />
        {operation === "cast-compose" && <p className="script-assistant-cast-help">選択行に登場するキャストから、プロフィールとの整合を確認する対象を選びます</p>}
      </fieldset>
      {showSettings && operation !== "cast-compose" && selected.length > 0 && <CastSettingsTable characters={selected} settings={castSettings} onChange={onCastSetting} showPriority={operation === "insert" || (operation === "rewrite" && !sparse)} />}
    </section>
  );
}

function ContentStep({
  target,
  rewriteMode,
  operation,
  instruction,
  onInstruction,
  simultaneousCues,
  onSimultaneousCues,
  sparse,
  busy,
  onRefine,
  onSuggestRandom,
  number,
}: Pick<SettingsProps, "target" | "rewriteMode" | "operation" | "instruction" | "onInstruction" | "simultaneousCues" | "onSimultaneousCues" | "sparse" | "busy" | "onRefine" | "onSuggestRandom"> & { number: number }) {
  const placeholder = target.kind === "insert" ? "空欄なら前後の文脈に自然につながるよう提案します。" : rewriteMode === "paraphrase" ? "空欄でも内容と行数を保ち、別の表現に言い換えます。" : "空欄でも前後のつながりを守り、会話の運びから組み直します。";
  const instructionId = useId();
  return (
    <section className="script-assistant-step" aria-labelledby="script-assistant-content-heading">
      <div id="script-assistant-content-heading">
        <StepHeading number={number}>{target.kind === "rewrite" ? "内容と演出" : "台本内容"}</StepHeading>
      </div>
      <div className="script-assistant-step-body">
        <div className="line-assistant-instruction">
          <div className="script-assistant-content-heading">
            <label htmlFor={instructionId}>{target.kind === "insert" ? "テーマ／状況" : "どのように／どんなテーマで"}</label>
            {target.kind === "insert" && (
              <span className="draft-theme-actions">
                <button type="button" className="button-ai draft-theme-action" disabled={busy} onClick={onSuggestRandom}>
                  ✦ おまかせ台本
                </button>
                <button type="button" className="button-ai draft-theme-action" disabled={busy || !instruction.trim()} onClick={onRefine}>
                  ✦ アイディアを広げる
                </button>
              </span>
            )}
          </div>
          <textarea id={instructionId} autoFocus value={instruction} onChange={(event) => onInstruction(event.currentTarget.value)} placeholder={placeholder} />
        </div>
        <div className="script-assistant-options">
          {target.kind === "rewrite" && operation !== "paraphrase" && !sparse && (
            <label className="checkbox-row">
              <input type="checkbox" checked={simultaneousCues} onChange={(event) => onSimultaneousCues(event.currentTarget.checked)} />
              同時発話の提案を許可
            </label>
          )}
        </div>
        {target.kind === "rewrite" && (
          <button className="secondary ai-action-button line-refine" disabled={busy || !instruction.trim()} onClick={onRefine}>
            ✦ AIに要望を校正してもらう
          </button>
        )}
      </div>
    </section>
  );
}

function InsertSettings(props: SettingsProps) {
  const selected = props.characters.filter((character) => props.characterIds.includes(character.id));
  if (!props.characterIds.length) return <CastStep {...props} number={1} showSettings={false} />;
  return (
    <>
      <CastStep {...props} number={1} showSettings={false} />
      <section className="script-assistant-step">
        <StepHeading number={2}>キャスト設定</StepHeading>
        <CastSettingsTable characters={selected} settings={props.castSettings} onChange={props.onCastSetting} />
      </section>
      <section className="script-assistant-step" aria-labelledby="script-assistant-generation-heading">
        <div id="script-assistant-generation-heading">
          <StepHeading number={3}>生成目標数</StepHeading>
        </div>
        <div className="script-assistant-step-body">
          <GenerationTargetFields {...props} />
        </div>
      </section>
      <ContentStep {...props} number={4} />
      <section className="script-assistant-step">
        <StepHeading number={5}>詳細設定</StepHeading>
        <PerformanceSettingsFields
          performance={props.performance}
          simultaneousCues={props.simultaneousCues}
          simultaneousCuesDisabled={props.characterIds.length < 2}
          overlappingSpeech={props.overlappingSpeech}
          onPerformanceChange={props.onPerformance}
          onSimultaneousCues={props.onSimultaneousCues}
          onOverlappingSpeech={props.onOverlappingSpeech}
        />
      </section>
      <section className="script-assistant-step">
        <StepHeading number={6}>台本生成</StepHeading>
        <div className="draft-submit script-assistant-submit">
          <div>
            <p className="eyebrow">READY TO WRITE</p>
            <b>前後の文脈につながる発話行を提案します</b>
            <small>生成後、内容を確認してから台本へ適用できます。</small>
          </div>
          <button className="primary ai-action-button" disabled={props.busy} onClick={props.onGenerate}>
            ✦ 提案を生成
          </button>
        </div>
      </section>
    </>
  );
}

export function ScriptAssistantSettings(props: SettingsProps) {
  const { target, project, targetLines, onTargetLineIds, operation, rewriteMode, characterIds } = props;
  const castStep = target.kind === "rewrite" ? 3 : 1;
  const hasGenerationTarget = operation === "insert" || rewriteMode === "rewrite";
  const showFollowing = target.kind !== "insert" || characterIds.length > 0;
  return (
    <div className="line-assistant-fields">
      {target.kind === "insert" ? (
        <InsertSettings {...props} />
      ) : (
        <>
          {target.kind === "rewrite" && <ScriptAssistantTargetLines lines={targetLines} project={project} originalIds={target.lineIds} onChange={onTargetLineIds} />}
          {target.kind === "rewrite" && <RewriteModeStep rewriteMode={rewriteMode} onRewriteMode={props.onRewriteMode} />}
          <CastStep {...props} number={castStep} />
          {showFollowing && hasGenerationTarget && (
            <section className="script-assistant-step" aria-labelledby="script-assistant-generation-heading">
              <div id="script-assistant-generation-heading">
                <StepHeading number={castStep + 1}>生成目標数</StepHeading>
              </div>
              <div className="script-assistant-step-body">
                <GenerationTargetFields {...props} />
              </div>
            </section>
          )}
          {showFollowing && operation !== "cast-compose" && <ContentStep {...props} number={castStep + (hasGenerationTarget ? 2 : 1)} />}
        </>
      )}
    </div>
  );
}
