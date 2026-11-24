import { DialogLayoutPreview } from "./DialogLayoutPreview";
import { Card, Section } from "./StyleGuideParts";

export function FormsSection() {
  return (
    <Section id="forms" title="フォーム" source="primitives.css / characters.css / draft-and-settings.css">
      <p className="subtle">入力コントロールの共通スタイルです。ここで確認・編集したCSSは、本アプリの設定、キャスト編集、AI演出にも反映されます。</p>
      <div className="styleguide-form-grid">
        <Card>
          <h3>テキスト・複数行</h3>
          <label>
            発話
            <input defaultValue="雨、やっと上がったね。" />
          </label>
          <label>
            演技メモ
            <textarea defaultValue="少し安心した声で、相手を見上げる。" />
          </label>
        </Card>
        <Card>
          <div className="underlined-fields">
            <h3>アンダーライン入力</h3>
            <label>
              表示名
              <input defaultValue="佐倉 紗良" />
            </label>
            <label>
              人物像
              <textarea defaultValue="強気で負けず嫌い。困っている相手は放っておけない。" />
            </label>
          </div>
        </Card>
        <Card>
          <h3>プルダウン・コンボボックス</h3>
          <label>
            話者
            <select defaultValue="aoi">
              <option value="aoi">アオイ</option>
              <option value="riri">リリ</option>
              <option value="nagi">ナギ</option>
            </select>
          </label>
          <label>
            話し方
            <input list="styleguide-speaking-style" defaultValue="穏やか" />
            <datalist id="styleguide-speaking-style">
              <option value="穏やか" />
              <option value="明るく" />
              <option value="小声で" />
            </datalist>
          </label>
          <p className="styleguide-control-note">候補から選ぶか、直接入力できます。</p>
        </Card>
        <Card>
          <h3>チェック・選択</h3>
          <fieldset>
            <legend>生成設定</legend>
            <label className="styleguide-check">
              <input type="checkbox" defaultChecked /> 自動生成を有効にする
            </label>
            <label className="styleguide-check">
              <input type="checkbox" /> 既存テイクを上書きする
            </label>
          </fieldset>
          <fieldset>
            <legend>品質</legend>
            <label className="styleguide-check">
              <input type="radio" name="styleguide-quality" defaultChecked /> バランス
            </label>
            <label className="styleguide-check">
              <input type="radio" name="styleguide-quality" /> 高品質
            </label>
          </fieldset>
        </Card>
        <Card>
          <h3>数値・スライダー</h3>
          <label>
            話速
            <input type="number" min="0.5" max="2" step="0.05" defaultValue="0.95" />
          </label>
          <label>
            発話間隔
            <input className="range-control" type="range" min="0" max="5" defaultValue="2" />
          </label>
        </Card>
      </div>
    </Section>
  );
}

export function ModelsSection() {
  return (
    <Section id="models" title="モデル選択" source="draft-and-settings.css">
      <p className="subtle">
        通常、展開、未登録、選択エラーの共通状態です。カードは <code>--scena-model-card-aspect-ratio</code> による1.586:1比率で統一し、展開候補は <code>--scena-model-popover-card-width</code> でコンパクトに一覧します。詳細はタイトル右側の独立した操作です。
      </p>
      <div className="styleguide-model-selection-states">
        <Card>
          <h3>通常</h3>
          <div className="model-selection-control">
            <button type="button" className="model-selection-trigger model-board-card is-default">
              <span className="model-card-heading">
                <strong>Irodori-TTS v4.1 Small</strong>
              </span>
              <span className="model-card-body" />
              <span className="model-card-footer">
                <span className="model-card-badges">
                  <em>既定</em>
                </span>
                <small className="model-card-corner-meta">v4.1 · 3.3 GB</small>
              </span>
            </button>
            <button type="button" className="model-selection-details">
              詳細
            </button>
          </div>
        </Card>
        <Card>
          <h3>展開</h3>
          <div className="model-selection-popover styleguide-model-popover">
            <div className="model-selection-grid">
              <button type="button" className="model-selection-option model-board-card is-default">
                <span className="model-card-heading">
                  <strong>選択中のモデル</strong>
                </span>
              </button>
              <button type="button" className="model-add-card">
                <strong>+ モデルを追加</strong>
                <span>登録フローを開く</span>
              </button>
            </div>
          </div>
        </Card>
        <Card>
          <h3>未登録</h3>
          <button type="button" className="model-selection-trigger model-board-card is-default">
            <span className="model-selection-empty">
              <strong>モデルがありません</strong>
              <span>展開してモデルを追加できます</span>
            </span>
          </button>
        </Card>
        <Card>
          <h3>選択エラー</h3>
          <p className="warning-text model-selection-status" role="alert">
            モデルを切り替えられませんでした。現在の選択を維持します。
          </p>
        </Card>
      </div>
    </Section>
  );
}

export function DialogsSection() {
  return (
    <Section id="dialogs" title="ダイアログの構成要素" source="base.css / primitives.css / script-actions.css / characters.css / draft-and-settings.css">
      <p className="subtle">共通のバックドロップと基本枠に加え、AI演出の丸数字・AI操作、キャスト編集のボイス枠、生成段階、各ボタンを本アプリと同じクラスで確認します。</p>
      <DialogLayoutPreview />
    </Section>
  );
}
