import { useState } from "react";
import type { Character, DialogueLine } from "../../types";
import { CharacterPicker } from "./CharacterPicker";
import { EmojiTextArea, type LineTextEditorElement } from "./EmojiTextArea";
import { useLineContentDraft } from "./useLineContentDraft";

function LineEnabledButton({ line, lineNumber, referenceNumber, onUpdate }: { line: DialogueLine; lineNumber: number | null; referenceNumber: number; onUpdate: (patch: Partial<DialogueLine>) => void }) {
  const enabled = line.enabled !== false;
  return (
    <button
      type="button"
      className="line-number"
      aria-pressed={enabled}
      aria-label={`発話行 ${referenceNumber} を${enabled ? "無効" : "有効"}にする`}
      title={enabled ? "無効化" : "有効化"}
      onClick={(event) => {
        event.stopPropagation();
        onUpdate({ enabled: !enabled });
      }}
    >
      <span className={`circle-number-glyph${lineNumber !== null && lineNumber >= 100 && lineNumber <= 999 ? " is-three-digits" : ""}`}>{lineNumber ?? "—"}</span>
    </button>
  );
}

function CaptionCompatibilityWarning({ supported, direction }: { supported: boolean; direction: string }) {
  if (supported || !direction.trim()) return null;
  return <p className="warning-text">選択中の音声モデルではト書き・演技指示は音声へ適用されません。内容は保持したまま生成できます。</p>;
}

export function LineContentRows({
  line,
  lineNumber,
  referenceNumber,
  characters,
  busy,
  grouped,
  cueHead,
  captionSupported,
  onUpdate,
  onCommitContent,
  onTextFocus,
  onNotice,
  onChangeCharacter,
}: {
  line: DialogueLine;
  lineNumber: number | null;
  referenceNumber: number;
  characters: Character[];
  busy: boolean;
  grouped: boolean;
  cueHead: boolean;
  captionSupported: boolean;
  onUpdate: (patch: Partial<DialogueLine>) => void;
  onCommitContent: (autoRender: boolean) => void;
  onTextFocus: (element: LineTextEditorElement) => void;
  onNotice: (message: string) => void;
  onChangeCharacter: (characterId: string) => Promise<void>;
}) {
  const [directionOpen, setDirectionOpen] = useState(false);
  const content = useLineContentDraft(line, onUpdate, onCommitContent);
  return (
    <>
      <div className="line-main">
        {(!grouped || cueHead) && <LineEnabledButton line={line} lineNumber={lineNumber} referenceNumber={referenceNumber} onUpdate={onUpdate} />}
        {grouped && !cueHead && <span className="cue-line-indent" aria-hidden="true" />}
        <CharacterPicker characters={characters} value={line.characterId} disabled={busy} onChange={(characterId) => void onChangeCharacter(characterId)} />
        <EmojiTextArea value={content.draft.text} pronunciations={content.draft.pronunciations} onTextFocus={onTextFocus} onCommit={() => content.commit(true)} onNotice={onNotice} onChange={(text, pronunciations) => content.update({ text, pronunciations })} />
        <button className="direction-toggle" title="ト書きを表示" onClick={() => setDirectionOpen(!directionOpen)}>
          🎬{directionOpen ? " ▾" : " ▸"}
        </button>
      </div>
      {directionOpen && <textarea className="direction-input" value={content.draft.stageDirection} placeholder="ト書き（TTSへ渡す、直接的で短い演技指示）" onChange={(event) => content.update({ stageDirection: event.target.value })} onBlur={() => content.commit(false)} />}
      <CaptionCompatibilityWarning supported={captionSupported} direction={content.draft.stageDirection} />
    </>
  );
}
