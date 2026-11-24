import { useState } from "react";
import { api } from "../../api";
import type { StudioController } from "../studio/useStudioController";
import { DialogFooter, DialogHeader, ModalBackdrop } from "../shared/overlays";
import { matchedCharacterId, parseScriptImport } from "./scriptImport";

function importIsReady(lineCount: number, characterCount: number, hasLeadingUnassignedLine: boolean, hasSpeakers: boolean, speakersAssigned: boolean, singleCharacterId: string) {
  if (!lineCount || !characterCount || hasLeadingUnassignedLine) return false;
  return hasSpeakers ? speakersAssigned : Boolean(singleCharacterId);
}

export function ScriptImportDialog({ model }: { model: StudioController }) {
  const { project, busy, setBusy, setNotice, editSession, scriptImportOpen, setScriptImportOpen } = model;
  const [source, setSource] = useState("");
  const [assignments, setAssignments] = useState<Record<string, string>>({});
  const [singleCharacterId, setSingleCharacterId] = useState("");
  if (!project || !scriptImportOpen) return null;
  const lines = parseScriptImport(source);
  const speakers = [...new Set(lines.flatMap((line) => (line.speaker ? [line.speaker] : [])))];
  const hasSpeakers = speakers.length > 0;
  const hasLeadingUnassignedLine = hasSpeakers && lines.some((line) => !line.speaker);
  const assignmentFor = (speaker: string) => assignments[speaker] ?? matchedCharacterId(speaker, project.characters);
  const speakersAssigned = speakers.every((speaker) => Boolean(assignmentFor(speaker)));
  const canImport = importIsReady(lines.length, project.characters.length, hasLeadingUnassignedLine, hasSpeakers, speakersAssigned, singleCharacterId);
  const close = () => setScriptImportOpen(false);
  async function submit() {
    if (!canImport) return;
    setBusy("import-script");
    try {
      const next = await editSession.requestProject(() =>
        api.importScript(
          lines.map((line) => ({
            character_id: line.speaker ? assignmentFor(line.speaker) : singleCharacterId,
            text: line.text,
          })),
        ),
      );
      if (!next) return;
      close();
      setNotice(`${lines.length}行を台本に読み込みました。`);
    } catch (error) {
      setNotice(`台本を読み込めませんでした: ${(error as Error).message}`);
    } finally {
      setBusy(null);
    }
  }
  return (
    <ModalBackdrop onClose={close} disabled={Boolean(busy)} fileDropPolicy="dismiss">
      <section className="modal script-import-modal" role="dialog" aria-modal="true" aria-label="台本読み込み">
        <DialogHeader
          eyebrow="SCRIPT IMPORT"
          title="台本を読み込む"
          description={
            <>
              台本を貼り付けると、1行ずつ発話行として追加します。話者なし行は直前のキャストを引き継ぎます。区切りには <code>|</code>、<code>:</code>、<code>;</code>、<code>,</code> と全角記号を使えます。2つ目以降の区切り記号は本文として扱います。
            </>
          }
        />
        <div className="dialog-form-fields script-import-fields">
          <label className="dialog-form-field">
            台本データ
            <textarea autoFocus value={source} onChange={(event) => setSource(event.target.value)} placeholder={"話者A「こんにちは。」\n話者B:やあ。\n\nまたは、台詞だけを1行ずつ入力"} />
          </label>
        </div>
        {source.trim() && <p className="script-import-count">{lines.length}行を検出しました</p>}
        {hasSpeakers ? (
          <section className="script-import-assignments" aria-label="台本上の名前とキャストの紐付け">
            <h3>台本上の名前とキャストを紐付け</h3>
            <p className="subtle">すべての台本上の名前を登録済みキャストへ割り当ててください。名前・姓・名・別名に一致した候補は自動選択されています。</p>
            {speakers.map((speaker) => (
              <label key={speaker}>
                <span>{speaker}</span>
                <select value={assignmentFor(speaker)} onChange={(event) => setAssignments((current) => ({ ...current, [speaker]: event.target.value }))}>
                  <option value="">キャストを選択</option>
                  {project.characters.map((character) => (
                    <option key={character.id} value={character.id}>
                      {character.name}
                    </option>
                  ))}
                </select>
              </label>
            ))}
          </section>
        ) : (
          source.trim() && (
            <label className="script-import-single-character">
              すべての台詞のキャスト
              <select value={singleCharacterId} onChange={(event) => setSingleCharacterId(event.target.value)}>
                <option value="">キャストを選択</option>
                {project.characters.map((character) => (
                  <option key={character.id} value={character.id}>
                    {character.name}
                  </option>
                ))}
              </select>
            </label>
          )
        )}
        {!project.characters.length && (
          <p className="script-import-error" role="alert">
            読み込む前にキャストを登録してください。
          </p>
        )}
        {hasLeadingUnassignedLine && (
          <p className="script-import-error" role="alert">
            最初の発話行にキャスト名を付けてください。
          </p>
        )}
        {hasSpeakers && speakers.some((speaker) => !assignmentFor(speaker)) && (
          <p className="script-import-error" role="alert">
            未割り当ての名前があります。
          </p>
        )}
        <DialogFooter>
          <button type="button" onClick={close} disabled={Boolean(busy)}>
            キャンセル
          </button>
          <button className="primary" disabled={!canImport || Boolean(busy)} onClick={() => void submit()}>
            {busy === "import-script" ? "読み込み中…" : "台本に読み込む"}
          </button>
        </DialogFooter>
      </section>
    </ModalBackdrop>
  );
}
