import { DialogFooter, DialogHeader } from "../shared/overlays";

export function DialogLayoutPreview() {
  return (
    <div className="styleguide-dialog-catalog">
      <div className="styleguide-dialog-stage">
        <section className="modal styleguide-dialog-sample" aria-label="基本ダイアログのプレビュー">
          <DialogHeader eyebrow="DIALOG SHELL" title="基本ダイアログ" description="タイトルを持つヘッダーと、キャンセル・確定操作を持つフッターを共通部品として利用します。" />
          <label>
            表示名
            <input defaultValue="一ノ瀬 葵" />
          </label>
          <DialogFooter>
            <button type="button" className="button-secondary">
              キャンセル
            </button>
            <button type="button" className="primary">
              保存する
            </button>
          </DialogFooter>
        </section>
      </div>

      <div className="styleguide-dialog-component-grid">
        <article className="styleguide-dialog-component">
          <p className="eyebrow">AI DIRECTION</p>
          <h3 className="ai-direction-step">
            <span>
              <span className="circle-number-glyph">1</span>
            </span>
            演出の対象を選択
          </h3>
          <p className="subtle">丸数字はAI演出ダイアログの手順見出しです。</p>
          <div className="styleguide-actions">
            <button type="button" className="button-ai">
              AI演出を反映
            </button>
            <button type="button" className="character-ai-assist-button ai-action-button">
              AIに相談
            </button>
          </div>
        </article>

        <article className="styleguide-dialog-component">
          <p className="eyebrow">CAST EDIT</p>
          <h3>キャスト編集のボイス枠</h3>
          <p className="subtle">淡い青紫の枠と、参照ボイスの操作です。</p>
          <div className="character-edit-voice-controls">
            <div className="audio-playback-bar">
              <button type="button" aria-label="再生">
                ▶
              </button>
              <input type="range" min="0" max="100" defaultValue="38" aria-label="再生位置" />
              <output>0:12</output>
            </div>
            <div className="character-edit-voice-actions">
              <button type="button" className="voice-action-button">
                WAVを指定
              </button>
              <button type="button" className="voice-action-button is-design">
                VoiceDesign
              </button>
            </div>
          </div>
        </article>

        <article className="styleguide-dialog-component">
          <p className="eyebrow">GENERATION STATUS</p>
          <h3>生成の段階表示</h3>
          <ol className="draft-generation-steps">
            <li className="is-complete">
              <span>
                <span className="circle-number-glyph">✓</span>
              </span>
              構成を作成
            </li>
            <li className="is-current">
              <span>
                <span className="circle-number-glyph">2</span>
              </span>
              台本を生成
            </li>
            <li>
              <span>
                <span className="circle-number-glyph">3</span>
              </span>
              結果を確認
            </li>
          </ol>
        </article>

        <article className="styleguide-dialog-component">
          <p className="eyebrow">DIALOG ACTIONS</p>
          <h3>操作ボタン</h3>
          <p className="subtle">通常、AI、静かな操作、破壊的操作を既存のボタンで確認します。</p>
          <div className="styleguide-actions">
            <button type="button" className="primary">
              保存する
            </button>
            <button type="button" className="button-secondary">
              キャンセル
            </button>
            <button type="button" className="button-ai">
              AIで生成
            </button>
            <button type="button" className="quiet-button">
              後で行う
            </button>
            <button type="button" className="button-danger">
              削除する
            </button>
          </div>
        </article>
      </div>
    </div>
  );
}
