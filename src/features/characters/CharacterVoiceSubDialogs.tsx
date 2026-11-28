import { DialogFooter, DialogHeader } from "../shared/overlays";
import { CharacterMemoField } from "./CharacterMemoField";
import { FieldError, FormError } from "../shared/InlineValidation";
import type { CharactersViewModel } from "./useCharactersViewModel";

export function WavImportDialog({ model }: { model: CharactersViewModel }) {
  const { busy, fileInput, importName, importProfile, referenceFile, setImportName, setImportProfile, setReferenceFile, setWavImportOpen, importWav, importValidation } = model;
  return (
    <div className="modal-backdrop">
      <form className="modal wav-import-modal" noValidate onSubmit={(event) => void importWav(event)}>
        <DialogHeader eyebrow="REFERENCE WAV" title="手元のWAVを登録" description="参照に使う音声とキャストの基本情報を登録します。" />
        <div className="wav-import-fields">
          <label className="file-picker">
            <input ref={fileInput} type="file" accept="audio/wav,.wav" data-validation-field="referenceFile" onChange={(event) => setReferenceFile(event.target.files?.[0] ?? null)} />
            <span>{referenceFile ? referenceFile.name : "WAVファイルを選択"}</span>
            <small>標準WAV・25 MBまで</small>
          </label>
          <FieldError message={importValidation.fieldError("referenceFile")} />
          <label className="wav-import-field">
            キャラクター名
            <input value={importName} data-validation-field="importName" aria-invalid={Boolean(importValidation.fieldError("importName")) || undefined} onChange={(event) => setImportName(event.target.value)} required />
            <FieldError message={importValidation.fieldError("importName")} />
          </label>
          <CharacterMemoField className="wav-import-field" validationField="importProfile" value={importProfile} onChange={setImportProfile} placeholder="性格や話し方など、声と一緒に残したい設定" />
        </div>
        <DialogFooter>
          <button type="button" onClick={() => setWavImportOpen(false)}>
            キャンセル
          </button>
          <button className="primary" disabled={busy === "import-reference"}>
            {busy === "import-reference" ? "登録中…" : "この声をキャストに登録"}
          </button>
        </DialogFooter>
      </form>
    </div>
  );
}

export function VoiceSuggestionDialog({ model }: { model: CharactersViewModel }) {
  const { connection, setVoiceSuggestionOpen, sourceKeywords, setSourceKeywords, suggestingVoice, suggestVoiceDesign, voiceSuggestionValidation } = model;
  return (
    <div className="modal-backdrop">
      <form className="modal voice-suggestion-modal" onSubmit={(event) => void suggestVoiceDesign(event)}>
        <DialogHeader eyebrow="VOICE DESIGN ASSIST" title="AIに声の設計を相談" description="声の指定、基準用台詞、普通・喜・怒・哀・楽の短い台詞を提案します。生成後も編集できます。" />
        <label>
          声のアイデア
          <textarea value={sourceKeywords} data-validation-field="sourceKeywords" aria-invalid={Boolean(voiceSuggestionValidation.fieldError("sourceKeywords")) || undefined} onChange={(event) => setSourceKeywords(event.target.value)} autoFocus />
          <FieldError message={voiceSuggestionValidation.fieldError("sourceKeywords")} />
        </label>
        <p className="connection-hint">接続先：{connection.model || "設定ページで選択してください"}</p>
        <DialogFooter leading={voiceSuggestionValidation.formError ? <FormError message={voiceSuggestionValidation.formError} /> : undefined}>
          <button type="button" disabled={suggestingVoice} onClick={() => setVoiceSuggestionOpen(false)}>
            キャンセル
          </button>
          <button className="primary ai-action-button" disabled={suggestingVoice}>
            {suggestingVoice ? "声を設計中…" : "声の設計を提案"}
          </button>
        </DialogFooter>
      </form>
    </div>
  );
}
