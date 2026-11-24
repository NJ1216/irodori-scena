import type { Character } from "../../types";
import { avatarImageUrl } from "../shared/studio-utils";
import type { ScriptAssistantGroup, ScriptAssistantRow } from "./scriptAssistantTypes";

type PreviewSpeech = Pick<ScriptAssistantRow, "characterId" | "characterName" | "text" | "stageDirection" | "speechRate" | "gapSeconds" | "proposalCueId">;

function SpeakerAvatar({ character, name }: { character?: Character; name: string }) {
  const thumbnail = character?.avatarThumbnailUrl ?? character?.avatarUrl;
  return (
    <span className={`script-assistant-speaker-avatar${thumbnail ? " has-image" : ""}`} aria-hidden="true">
      {thumbnail ? <img src={avatarImageUrl(thumbnail, character?.avatarVersion)} alt="" /> : name.slice(0, 1)}
    </span>
  );
}

function SpeechCard({ caption, speech, character, proposed = false }: { caption?: string; speech: PreviewSpeech; character?: Character; proposed?: boolean }) {
  return (
    <span className={`script-assistant-speech-card ${proposed ? "is-proposed" : "is-original"}`}>
      {caption && <span className="script-assistant-side-caption">{caption}</span>}
      <span className="script-assistant-speaker">
        <SpeakerAvatar character={character} name={speech.characterName} />
        <b>{speech.characterName || "話者未設定"}</b>
      </span>
      <span className="script-assistant-dialogue">{speech.text}</span>
      {speech.stageDirection && (
        <span className="script-assistant-stage-direction">
          <b>ト書き</b>
          <span>{speech.stageDirection}</span>
        </span>
      )}
      {proposed && (
        <span className="script-assistant-speech-meta">
          {speech.speechRate != null && <span>話速 {speech.speechRate.toFixed(2)}倍</span>}
          <span>{speech.gapSeconds == null ? "同時発話" : `間 ${speech.gapSeconds.toFixed(1)}秒`}</span>
          {speech.proposalCueId && <span>同時発話グループ</span>}
        </span>
      )}
    </span>
  );
}

function ProposalRow({ group, rowIndex, checked, characters, onChange }: { group: ScriptAssistantGroup; rowIndex: number; checked: boolean; characters: Map<string, Character>; onChange: (checked: boolean) => void }) {
  const row = group.rows[rowIndex];
  const original = row.originalLineId ? group.originalRows.find((item) => item.id === row.originalLineId) : group.originalRows[rowIndex];
  return (
    <label className={`script-assistant-proposal-row${checked ? " is-selected" : ""}`}>
      <input type="checkbox" aria-label={`${row.characterName || "発話行"}の提案を採用`} checked={checked} onChange={(event) => onChange(event.currentTarget.checked)} />
      <span className={`script-assistant-comparison${original ? "" : " is-insert"}`}>
        {original && <SpeechCard caption="書き直し前" speech={original} character={characters.get(original.characterId)} />}
        <span className="script-assistant-arrow" aria-hidden="true">
          →
        </span>
        <SpeechCard caption="提案" speech={row} character={characters.get(row.characterId)} proposed />
      </span>
    </label>
  );
}

function AtomicComparison({ group, characters }: { group: ScriptAssistantGroup; characters: Map<string, Character> }) {
  return (
    <div className="script-assistant-atomic-comparison">
      <section className="script-assistant-atomic-column" aria-label="書き直し前">
        <h4>書き直し前</h4>
        {group.originalRows.map((row) => (
          <SpeechCard key={row.id} speech={row} character={characters.get(row.characterId)} />
        ))}
      </section>
      <span className="script-assistant-arrow" aria-hidden="true">
        →
      </span>
      <section className="script-assistant-atomic-column is-proposed" aria-label="提案">
        <h4>提案</h4>
        {group.rows.map((row) => (
          <SpeechCard key={row.id} speech={row} character={characters.get(row.characterId)} proposed />
        ))}
      </section>
    </div>
  );
}

export function ScriptAssistantPreview({
  groups,
  characters: characterList,
  acceptedRows,
  acceptedGroups,
  onRowsChange,
  onGroupsChange,
}: {
  groups: ScriptAssistantGroup[];
  characters: Character[];
  acceptedRows: Set<string>;
  acceptedGroups: Set<string>;
  onRowsChange: (next: Set<string>) => void;
  onGroupsChange: (next: Set<string>) => void;
}) {
  const characters = new Map(characterList.map((character) => [character.id, character]));
  return (
    <div className="script-assistant-preview">
      {groups.map((group) => (
        <section className="script-assistant-preview-group" key={group.id}>
          <div className="script-assistant-preview-heading">
            <div>
              <b>{group.sceneTitle || "無題のシーン"}</b>
              <small>{group.rows.length} 行の提案</small>
            </div>
            {group.atomic && (
              <label className="checkbox-row">
                <input
                  type="checkbox"
                  checked={acceptedGroups.has(group.id)}
                  onChange={(event) => {
                    const next = new Set(acceptedGroups);
                    if (event.currentTarget.checked) next.add(group.id);
                    else next.delete(group.id);
                    onGroupsChange(next);
                  }}
                />
                この提案全体を採用
              </label>
            )}
          </div>
          {group.warnings.map((warning) => (
            <p className="script-assistant-warning" key={warning}>
              {warning}
            </p>
          ))}
          {group.atomic ? (
            <AtomicComparison group={group} characters={characters} />
          ) : (
            group.rows.map((row, index) => (
              <ProposalRow
                key={row.id}
                group={group}
                rowIndex={index}
                characters={characters}
                checked={acceptedRows.has(row.id)}
                onChange={(checked) => {
                  const next = new Set(acceptedRows);
                  if (checked) next.add(row.id);
                  else next.delete(row.id);
                  onRowsChange(next);
                }}
              />
            ))
          )}
        </section>
      ))}
    </div>
  );
}
