import { StepHeading } from "../shared/StepHeading";
import { useId, type Dispatch, type SetStateAction } from "react";
import type { Character, LlmConnection } from "../../types";
import { ScaledDraftCastName } from "../characters/CastNotebook";
import { ResettableRangeInput } from "../shared/ResettableRangeInput";
import { avatarImageUrl } from "../shared/studio-utils";
import { llmPresets, type DraftCastSettings, type DraftComposerState } from "../studio/types";
import { DraftPerformanceSettings } from "./DraftPerformanceSettings";
import { draftCastSettingsFor } from "./draftCastSettings";

type SetComposer = Dispatch<SetStateAction<DraftComposerState>>;

export function DraftCastPicker({ characters, selectedIds, onToggle }: { characters: Character[]; selectedIds: string[]; onToggle: (id: string) => void }) {
  return (
    <>
      <StepHeading number={1}>参加キャスト</StepHeading>
      {characters.length ? (
        <div className="draft-cast-picker" role="group" aria-label="参加キャスト">
          {characters.map((character) => {
            const selected = selectedIds.includes(character.id);
            return (
              <button key={character.id} type="button" className={`draft-cast-picker-item${selected ? " is-selected" : ""}`} aria-pressed={selected} onClick={() => onToggle(character.id)}>
                <span className={`draft-cast-picker-avatar${character.avatarUrl ? " has-image" : ""}`}>{character.avatarUrl ? <img src={avatarImageUrl(character.avatarUrl, character.avatarVersion)} alt="" /> : character.name.slice(0, 1)}</span>
                <ScaledDraftCastName name={character.name} />
              </button>
            );
          })}
        </div>
      ) : (
        <div className="empty-state">先に話者管理からキャラクターを登録してください。</div>
      )}
    </>
  );
}

const options: { label: string; checked: (value: DraftCastSettings) => boolean; patch: (checked: boolean) => Partial<DraftCastSettings> }[] = [
  { label: "表情EMOJIを使う", checked: (value) => value.emojiExpressions, patch: (checked) => ({ emojiExpressions: checked }) },
  { label: "フィラーを多めに入れる", checked: (value) => value.fillerRichness, patch: (checked) => ({ fillerRichness: checked }) },
  { label: "メインキャスト", checked: (value) => value.appearancePriority === "main", patch: (checked) => ({ appearancePriority: checked ? "main" : "standard" }) },
  { label: "サブキャスト", checked: (value) => value.appearancePriority === "supporting", patch: (checked) => ({ appearancePriority: checked ? "supporting" : "standard" }) },
];

export function CastSettingsTable({ characters, settings, onChange, showPriority = true }: { characters: Character[]; settings: Record<string, DraftCastSettings>; onChange: (characterId: string, patch: Partial<DraftCastSettings>) => void; showPriority?: boolean }) {
  return (
    <div className="draft-cast-settings-table-wrap">
      <table className="draft-cast-settings-table">
        <thead>
          <tr>
            <th scope="col">キャスト</th>
            {characters.map((character) => (
              <th scope="col" key={character.id}>
                <span className="draft-cast-settings-avatar">{character.avatarUrl ? <img src={avatarImageUrl(character.avatarUrl, character.avatarVersion)} alt="" /> : character.name.slice(0, 1)}</span>
                <ScaledDraftCastName name={character.name} />
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {(showPriority ? options : options.slice(0, 2)).map((option) => (
            <tr key={option.label}>
              <th scope="row">{option.label}</th>
              {characters.map((character) => {
                const value = draftCastSettingsFor(settings, character.id);
                return (
                  <td key={character.id}>
                    <input className="control-checkbox" type="checkbox" aria-label={`${character.name}：${option.label}`} checked={option.checked(value)} onChange={(event) => onChange(character.id, option.patch(event.target.checked))} />
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function DraftCastSettingsTable({ characters, composer, onChange }: { characters: Character[]; composer: DraftComposerState; onChange: SetComposer }) {
  const update = (characterId: string, patch: Partial<DraftCastSettings>) => onChange((current) => ({ ...current, castSettings: { ...current.castSettings, [characterId]: { ...draftCastSettingsFor(current.castSettings, characterId), ...patch } } }));
  return (
    <>
      <StepHeading number={2}>キャスト設定</StepHeading>
      <CastSettingsTable characters={characters} settings={composer.castSettings} onChange={update} />
    </>
  );
}

export function DraftContentFields({
  composer,
  connection,
  generating,
  suggestingTheme,
  onChange,
  onSuggestTheme,
  onGenerate,
}: {
  composer: DraftComposerState;
  connection: LlmConnection;
  generating: boolean;
  suggestingTheme: boolean;
  onChange: SetComposer;
  onSuggestTheme: (mode: "random" | "detail") => void;
  onGenerate: () => void;
}) {
  const { selectedIds, minutes, theme, performance, simultaneousCues, overlappingSpeech } = composer;
  const themeId = useId();
  return (
    <>
      <StepHeading number={3}>生成目標数</StepHeading>
      <label>
        だいたいの総尺
        <span className="duration-slider">
          <ResettableRangeInput className="range-control" min={1} max={60} step={1} value={minutes} initialValue={3} onValueChange={(value) => onChange((current) => ({ ...current, minutes: value }))} aria-label="だいたいの総尺（分）" />
          <output>{minutes}分</output>
        </span>
      </label>
      <StepHeading number={4}>台本内容</StepHeading>
      <div className="draft-theme-field">
        <div className="draft-theme-field-heading">
          <label htmlFor={themeId}>テーマ／状況</label>
          <div className="draft-theme-actions">
            <button type="button" className="button-ai draft-theme-action" disabled={generating || suggestingTheme} onClick={() => onSuggestTheme("random")}>
              ✦ おまかせ台本
            </button>
            <button type="button" className="button-ai draft-theme-action" disabled={generating || suggestingTheme || !theme.trim()} onClick={() => onSuggestTheme("detail")}>
              ✦ アイディアを広げる
            </button>
          </div>
        </div>
        <textarea
          id={themeId}
          value={theme}
          onChange={(event) => {
            const value = event.target.value;
            onChange((current) => ({ ...current, theme: value }));
          }}
        />
      </div>
      {theme.trim() && (
        <>
          <DraftPerformanceSettings
            performance={performance}
            simultaneousCues={simultaneousCues}
            simultaneousCuesDisabled={selectedIds.length < 2}
            overlappingSpeech={overlappingSpeech}
            onPerformanceChange={(value) => onChange((current) => ({ ...current, performance: value }))}
            onSimultaneousCues={(value) => onChange((current) => ({ ...current, simultaneousCues: value }))}
            onOverlappingSpeech={(value) => onChange((current) => ({ ...current, overlappingSpeech: value }))}
          />
          <StepHeading number={6}>台本生成</StepHeading>
          <div className="draft-submit">
            <div>
              <p className="eyebrow">READY TO WRITE</p>
              <b>{connection.model ? `${llmPresets[connection.provider].label} · ${connection.model}` : "設定ページでLLMモデルを選択してください"}</b>
              <small>生成後、台本へ自動で追加されます。</small>
            </div>
            <button className="primary ai-action-button" disabled={generating || suggestingTheme} onClick={onGenerate}>
              {generating ? "台本を生成中…" : "✦ 台本案を生成する"}
            </button>
          </div>
        </>
      )}
    </>
  );
}
