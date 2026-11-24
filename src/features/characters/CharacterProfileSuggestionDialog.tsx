import type { CharactersViewModel } from "./useCharactersViewModel";
import { DialogFooter, DialogHeader, ModalBackdrop } from "../shared/overlays";

export function CharacterProfileSuggestionDialog({ model }: { model: CharactersViewModel }) {
  const {
    connection,
    editing,
    profileSuggestionOpen,
    setProfileSuggestionOpen,
    profileSuggestionIdea,
    setProfileSuggestionIdea,
    profileSuggestionMode,
    setProfileSuggestionMode,
    profileSuggestionScope,
    setProfileSuggestionScope,
    profileSuggestionError,
    profileSuggestionProgress,
    setProfileSuggestionError,
    suggestingProfile,
    suggestCharacterProfile,
    cancelCharacterProfileSuggestion,
  } = model;
  return (
    <>
      {profileSuggestionOpen && editing && (
        <ModalBackdrop onClose={() => setProfileSuggestionOpen(false)} disabled={suggestingProfile}>
          <form className="modal character-profile-suggestion-modal" onSubmit={(event) => void suggestCharacterProfile(event)}>
            <DialogHeader eyebrow="CAST PROFILE ASSIST" title="AIに設定を作ってもらう" description="表示名が空欄の場合は、生成された愛称の一つを表示名にも適用します。自由メモ、声、参照音声、画像は変更しません。AIが返せなかった項目も現在値のまま残ります。" />
            <div className="dialog-form-fields">
              <div className="dialog-form-field">
                <span>生成方法</span>
                <div className="choice-group" role="radiogroup" aria-label="生成方法">
                  <label className="choice-option">
                    <input disabled={suggestingProfile} type="radio" name="profile-suggestion-mode" checked={profileSuggestionMode === "fill_missing"} onChange={() => setProfileSuggestionMode("fill_missing")} />
                    <span>空欄のみ（推奨）</span>
                  </label>
                  <label className="choice-option">
                    <input disabled={suggestingProfile} type="radio" name="profile-suggestion-mode" checked={profileSuggestionMode === "replace_details"} onChange={() => setProfileSuggestionMode("replace_details")} />
                    <span>すべて</span>
                  </label>
                </div>
              </div>
              <div className="dialog-form-field">
                <span>生成範囲</span>
                <div className="choice-group" role="radiogroup" aria-label="生成範囲">
                  <label className="choice-option">
                    <input disabled={suggestingProfile} type="radio" name="profile-suggestion-scope" checked={profileSuggestionScope === "all"} onChange={() => setProfileSuggestionScope("all")} />
                    <span>すべて（自由メモ以外）</span>
                  </label>
                  <label className="choice-option">
                    <input disabled={suggestingProfile} type="radio" name="profile-suggestion-scope" checked={profileSuggestionScope === "profile"} onChange={() => setProfileSuggestionScope("profile")} />
                    <span>人間関係以外</span>
                  </label>
                  <label className="choice-option">
                    <input disabled={suggestingProfile} type="radio" name="profile-suggestion-scope" checked={profileSuggestionScope === "relations"} onChange={() => setProfileSuggestionScope("relations")} />
                    <span>人間関係のみ</span>
                  </label>
                </div>
              </div>
              <label className="dialog-form-field">
                キャラクター設定のアイディア（任意）
                <textarea
                  value={profileSuggestionIdea}
                  disabled={suggestingProfile}
                  onChange={(event) => {
                    setProfileSuggestionIdea(event.target.value);
                    setProfileSuggestionError("");
                  }}
                  placeholder="例：雨の日だけ開く古書店の店主。少し皮肉屋だが、本好きの客にはとても親切。幼なじみにはつい世話を焼く。"
                  autoFocus
                />
              </label>
              {profileSuggestionError && (
                <p className="character-profile-suggestion-error" role="alert">
                  {profileSuggestionError}
                </p>
              )}
              {suggestingProfile && profileSuggestionProgress && (
                <p className="connection-hint" role="status">
                  {profileSuggestionProgress}
                </p>
              )}
              <p className="connection-hint">接続先：{connection.model || "設定ページで選択してください"}</p>
            </div>
            <DialogFooter>
              <button type="button" className="button-secondary" onClick={() => (suggestingProfile ? void cancelCharacterProfileSuggestion() : setProfileSuggestionOpen(false))}>
                キャンセル
              </button>
              <button className="button-ai" disabled={suggestingProfile}>
                {suggestingProfile ? "設定を考え中…" : "設定を生成"}
              </button>
            </DialogFooter>
          </form>
        </ModalBackdrop>
      )}
    </>
  );
}
