import { CustomButtonCatalog } from "./CustomButtonCatalog";
import { Card, Section } from "./StyleGuideParts";

export function SurfacesSection() {
  return (
    <Section id="surfaces" title="ページ別の共通面" source="base.css / shell-and-draft.css">
      <div className="styleguide-grid">
        <Card>
          <p className="eyebrow">SCRIPT</p>
          <h3>台本</h3>
          <p>紙面・発話カード・テイク操作の基調です。</p>
          <button className="primary">台本を開く</button>
        </Card>
        <Card>
          <p className="eyebrow">AI DRAFT</p>
          <h3>AI台本</h3>
          <p>構成、進行状況、設定モーダルの面です。</p>
          <button className="secondary">下書きを確認</button>
        </Card>
        <Card>
          <p className="eyebrow">CAST</p>
          <h3>キャスト</h3>
          <p>ノート、参照ボイス、候補一覧の面です。</p>
          <button className="quiet-button">キャストを編集</button>
        </Card>
      </div>
    </Section>
  );
}

export function ControlsSection() {
  return (
    <Section id="controls" title="操作要素" source="primitives.css / script-actions.css">
      <div className="styleguide-grid styleguide-elements">
        <Card>
          <h3>ボタン</h3>
          <div className="styleguide-actions">
            <button className="primary">主要操作</button>
            <button className="secondary">補助操作</button>
            <button className="quiet-button">静かな操作</button>
            <button className="delete-line">削除</button>
            <button className="danger is-confirming">もう一度押して削除</button>
          </div>
        </Card>
        <Card>
          <h3>入力</h3>
          <label>
            テキスト
            <input defaultValue="発話行の本文" />
          </label>
          <label>
            説明
            <textarea defaultValue="相手の返答を受け、少し迷ってから話す。" />
          </label>
        </Card>
        <Card>
          <h3>生成アクション</h3>
          <div className="line-actions">
            <span className="generate-stack has-regenerate">
              <button className="regenerate-hover">↻ 上書き生成</button>
              <button className="generate">＋ 新規テイク</button>
            </span>
          </div>
        </Card>
      </div>
    </Section>
  );
}

export function CustomButtonsSection() {
  return (
    <Section id="custom-buttons" title="カスタムボタン" source="characters.css / notebook.css / script-actions.css">
      <p className="subtle">画面固有の役割を持つボタンを、実際と同じクラスと親要素の組み合わせで確認します。</p>
      <CustomButtonCatalog />
    </Section>
  );
}

export function InsertControlsSection() {
  return (
    <Section id="insert-controls" title="挿入コントロール" source="script-actions.css">
      <p className="subtle">シーンと発話行の挿入・追加、およびAIへの依頼は共通の挿入コントロールです。挿入位置はマウスオーバー直後に点線で示し、待機すると操作へ展開します。通常操作は白、AI操作だけをミント色で区別します。</p>
      <div className="styleguide-insert-controls">
        <Card>
          <h3>発話行</h3>
          <div className="insert-zone is-revealed">
            <div className="insert-actions">
              <button className="insert-action">＋ 発話行を挿入</button>
              <button className="insert-action insert-action-ai">✦ AIに依頼</button>
            </div>
          </div>
        </Card>
        <Card>
          <h3>シーン</h3>
          <div className="insert-zone is-revealed">
            <div className="insert-actions">
              <button className="insert-action">＋ シーンを挿入</button>
            </div>
          </div>
        </Card>
        <Card>
          <h3>追加</h3>
          <div className="insert-zone is-revealed">
            <div className="insert-actions">
              <button className="insert-action">＋ 発話行を追加</button>
              <button className="insert-action">＋ シーンを追加</button>
            </div>
          </div>
        </Card>
      </div>
    </Section>
  );
}
