import type { CharactersViewModel } from "./useCharactersViewModel";

export function CharacterImagePromptEditor({ model }: { model: CharactersViewModel }) {
  const { editImagePrompt, setEditImagePrompt, setImagePromptSuggestionOpen } = model;
  return (
    <div className="image-prompt-editor">
      <textarea value={editImagePrompt} onChange={(event) => setEditImagePrompt(event.target.value)} placeholder="画像生成用プロンプトメモ" />
      <button type="button" className="secondary ai-action-button" title="[注意] SCENAには画像生成機能はありません。画像生成サービスで使用するプロンプト文を作成します。" onClick={() => setImagePromptSuggestionOpen(true)}>
        画像生成用プロンプト文を作る
      </button>
    </div>
  );
}
