import { useCallback, useState } from "react";
import { preserveReferenceEditDraft } from "./characterReferenceDraft";
import { CastLoraMixSetting } from "../lora/CastLoraMixSetting";
import { avatarImageUrl } from "../shared/studio-utils";
import { DialogFooter, DialogHeader } from "../shared/overlays";
import type { CharactersViewModel } from "./useCharactersViewModel";

import { CharacterDetailFields, CharacterProfileFields } from "./CharacterProfileFields";
import { CharacterRelationFields, CharacterSpeechFields } from "./CharacterSpeechFields";
import { CharacterImagePromptEditor } from "./CharacterImagePromptEditor";
import { AudioPlaybackBar } from "./AudioPlaybackBar";
import { CharacterMemoField } from "./CharacterMemoField";
import { FieldError } from "../shared/InlineValidation";

function ReferenceChangeSetting({ model }: { model: CharactersViewModel }) {
  const { editing, busy, referenceInput, activeReferenceAudio, onUpdateReference, setEditing, beginReferenceVoiceDesign, beginReferencePlayback, endReferencePlayback, voiceDesignUnavailableReason } = model;
  const referenceKey = `${editing?.id}:${editing?.referenceAudioUrl}:${editing?.referenceVersion}`;
  const [referenceState, setReferenceState] = useState<{ key: string; state: "loading" | "ready" | "failed" }>({ key: "", state: "loading" });
  const onReferenceLoad = useCallback((state: "loading" | "ready" | "failed") => setReferenceState({ key: referenceKey, state }), [referenceKey]);
  if (!editing) return null;
  return (
    <>
      <input
        ref={referenceInput}
        className="reference-wav-file-input"
        type="file"
        accept=".wav,audio/wav"
        onChange={async (event) => {
          const file = event.currentTarget.files?.[0];
          event.currentTarget.value = "";
          if (!file) return;
          activeReferenceAudio.current?.stop();
          const updated = await onUpdateReference(editing, file);
          if (updated) setEditing((current) => preserveReferenceEditDraft(current, updated));
        }}
      />
      <section className="character-edit-voice" aria-label="ボイス">
        <span className="character-edit-voice-label type-field-label">ボイス</span>
        <div className="character-edit-voice-controls">
          <AudioPlaybackBar label="現在の参照ボイス" src={editing.referenceAudioUrl} version={editing.referenceVersion} onPlay={beginReferencePlayback} onEnded={endReferencePlayback} onPause={endReferencePlayback} onLoadState={onReferenceLoad} />
          <div className="character-edit-voice-actions">
            <button type="button" className="voice-action-button" disabled={busy === `reference-${editing.id}`} onClick={() => referenceInput.current?.click()}>
              {busy === `reference-${editing.id}` ? "変更中…" : "WAVファイルを指定"}
            </button>
            <span className="disabled-reason-control" tabIndex={voiceDesignUnavailableReason ? 0 : undefined}>
              <button type="button" className="voice-action-button is-design" aria-describedby={voiceDesignUnavailableReason ? "voice-design-regenerate-reason" : undefined} disabled={Boolean(busy) || Boolean(voiceDesignUnavailableReason)} onClick={() => beginReferenceVoiceDesign(editing)}>
                VoiceDesignで再生成
              </button>
              {voiceDesignUnavailableReason && (
                <span className="disabled-reason-tooltip" id="voice-design-regenerate-reason" role="tooltip">
                  {voiceDesignUnavailableReason}
                </span>
              )}
            </span>
          </div>
          <CastLoraMixSetting character={editing} referenceState={referenceState.key === referenceKey ? referenceState.state : "loading"} project={model.project} onPlay={beginReferencePlayback} onChange={(loraMix) => setEditing((current) => (current?.id === editing.id ? { ...current, loraMix } : current))} />
        </div>
      </section>
    </>
  );
}

export function CharacterEditDialog({ model }: { model: CharactersViewModel }) {
  const {
    busy,
    editing,
    setEditing,
    editProfile,
    setEditProfile,
    setAvatarSource,
    editAvatarChange,
    setEditAvatarChange,
    setProfileSuggestionOpen,
    setProfileSuggestionError,
    profileSuggestionFields,
    profileSuggestionRelations,
    avatarInput,
    suggestingProfile,
    editAvatarPreview,
    chooseAvatar,
    saveEdit,
    editValidation,
  } = model;
  return (
    <>
      {editing && (
        <div className="modal-backdrop">
          <form className="modal character-edit-modal" noValidate onSubmit={(event) => void saveEdit(event)}>
            <DialogHeader
              eyebrow="EDIT CAST"
              title="キャストの設定を編集"
              actions={
                <button
                  type="button"
                  className="character-ai-assist-button ai-action-button"
                  disabled={suggestingProfile}
                  onClick={() => {
                    setProfileSuggestionError("");
                    model.setProfileSuggestionMode("fill_missing");
                    model.setProfileSuggestionScope("all");
                    setProfileSuggestionOpen(true);
                  }}
                >
                  ✦ AIに設定を作ってもらう
                </button>
              }
            />
            {(profileSuggestionFields.size > 0 || profileSuggestionRelations.size > 0) && <p className="ai-suggestion-status">✦ 緑の項目はAIによる仮入力です。「変更を保存」で確定します。</p>}
            <input
              ref={avatarInput}
              className="avatar-file-input"
              type="file"
              accept="image/*"
              onChange={(event) => {
                chooseAvatar(event.currentTarget.files?.[0] ?? null);
                event.currentTarget.value = "";
              }}
            />
            <div className="avatar-setting">
              <div className={`avatar avatar-edit-preview`}>{editAvatarPreview ? <img src={avatarImageUrl(editAvatarPreview, editing.avatarVersion)} alt="現在のキャラクター画像" /> : editing.name.slice(0, 1)}</div>
              <div className="avatar-setting-content">
                <b>キャラクター画像</b>
                <small>未設定時は頭文字アイコンを使用します。</small>
                <div className="avatar-setting-actions">
                  <button type="button" className="secondary" data-validation-field="avatar" disabled={busy === `avatar-${editing.id}`} onClick={() => avatarInput.current?.click()}>
                    画像を選択
                  </button>
                  {editAvatarPreview && (
                    <button type="button" className="avatar-remove-button" disabled={busy === `avatar-${editing.id}`} onClick={() => setEditAvatarChange(null)}>
                      画像を解除
                    </button>
                  )}
                  {editAvatarChange === null && (
                    <button type="button" className="avatar-remove-button" onClick={() => setEditAvatarChange(undefined)}>
                      解除を取り消す
                    </button>
                  )}
                </div>
                <FieldError message={editValidation.fieldError("avatar")} />
              </div>
              <CharacterImagePromptEditor model={model} />
            </div>
            <ReferenceChangeSetting model={model} />
            <CharacterProfileFields model={model} />
            <CharacterSpeechFields model={model} />
            <CharacterRelationFields model={model} />
            <CharacterDetailFields model={model} />
            <section className="character-settings-section underlined-fields" aria-labelledby="character-memo-heading">
              <h2 id="character-memo-heading">自由メモ</h2>
              <CharacterMemoField label="上の項目に収まらない設定" validationField="editProfile" value={editProfile} onChange={setEditProfile} placeholder="上の項目に収まらない設定や、補足。" />
            </section>
            <DialogFooter>
              <button
                type="button"
                onClick={() => {
                  setAvatarSource(null);
                  setEditAvatarChange(undefined);
                  setEditing(null);
                }}
              >
                キャンセル
              </button>
              <button className="primary" disabled={busy === `edit-${editing.id}` || busy === `avatar-${editing.id}`}>
                {busy === `edit-${editing.id}` ? "保存中…" : busy === `avatar-${editing.id}` ? "画像を保存中…" : "変更を保存"}
              </button>
            </DialogFooter>
          </form>
        </div>
      )}
    </>
  );
}
