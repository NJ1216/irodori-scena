import { LoraLibraryToolbar } from "../lora/LoraLibraryToolbar";
import { LoraAuditionBar } from "../lora/LoraAuditionBar";
import { useState } from "react";
import { LoraMixEditor } from "../lora/LoraMixEditor";
import type { LoraMix } from "../../types/project";
import { VoiceCandidateActionGroup } from "../characters/VoiceCandidateActionGroup";

export function CustomButtonCatalog() {
  const [mix, setMix] = useState<LoraMix>({ version: 1, baseWeight: 5000, entries: [{ assetId: "example", adapterHash: "a".repeat(64), baseModelRepo: "example", baseModelRevision: "example", weight: 5000 }] });
  return (
    <div className="styleguide-custom-buttons">
      <article className="styleguide-card styleguide-custom-button-wide">
        <h3>LoRA配合・試聴</h3>
        <LoraMixEditor
          value={mix}
          names={["ベース", "LoRAサンプル"]}
          onChange={setMix}
          actions={
            <button type="button" className="voice-action-button">
              LoRAを追加
            </button>
          }
        />
        <LoraAuditionBar audition={{ generating: false, playing: false, error: "", duration: 12, currentTime: 0, toggle: async () => {}, seek: () => {} }} reason="スタイルガイドのサンプルです" />
        <p className="styleguide-control-note">
          項目名はキャストの表示名と共通の
          type-field-label。追加ボタンはグラフの行末。各区画は最低10%。境界のドラッグ・矢印キーで調整。淡い黄色・ミント・ピンク・ラベンダー・ピーチの固定配色（--scena-lora-mix-base／1〜4）。％は濃い文字。区画下にBase・LoRA名。％のダブルクリック（Enter／F2でも可）で枠・背景のないインライン編集。Enter／blurで確定、Escapeで取消。詳細はツールチップ、割合指定・削除は右クリック。追加はダイアログ、試聴は再生バー。グラフ行は親幅いっぱい。高さは
          --scena-lora-mix-height。参照音声と試聴の再生バー幅は --scena-audio-playback-width で統一。
        </p>
      </article>
      <article className="styleguide-card styleguide-custom-button-wide">
        <h3>LoRA管理の操作</h3>
        <LoraLibraryToolbar canManage busy={false} pending={false} confirmationKey="styleguide-lora-delete" onEdit={() => {}} onContinue={() => {}} onRegister={() => {}} onDelete={() => {}} />
      </article>
      <article className="styleguide-card">
        <p className="eyebrow">ICON ACTIONS</p>
        <h3>閉じる</h3>
        <div className="avatar-original-heading">
          <div>
            <p className="subtle">アバター原寸表示</p>
          </div>
          <button type="button" aria-label="原画像を閉じる">
            <svg viewBox="0 0 16 16" aria-hidden="true">
              <path d="M3 3l10 10M13 3L3 13" />
            </svg>
          </button>
        </div>
      </article>

      <article className="styleguide-card">
        <p className="eyebrow">VOICE CANDIDATES</p>
        <h3>候補の生成・選択・消去</h3>
        <div className="styleguide-candidate-action-preview">
          <span className="type-label">喜の台詞</span>
          <VoiceCandidateActionGroup label="喜" />
        </div>
        <p className="styleguide-control-note">生成・参照・Clearを1つの外形にまとめた3分割アクション</p>
        <div className="voice-candidate-choices">
          <div className="voice-candidate-choice">
            <div className="audio-playback-bar is-compact is-selected">
              <button type="button" aria-label="候補Aを再生">
                A
              </button>
            </div>
          </div>
          <div className="voice-candidate-choice">
            <div className="audio-playback-bar is-compact">
              <button type="button" aria-label="候補Bを再生">
                B
              </button>
            </div>
          </div>
          <div className="voice-candidate-choice">
            <div className="audio-playback-bar is-compact">
              <button type="button" aria-label="候補Cを再生">
                C
              </button>
            </div>
          </div>
        </div>
      </article>

      <article className="styleguide-card styleguide-custom-button-wide">
        <p className="eyebrow">CAST ENTRY</p>
        <h3>キャストページの入口</h3>
        <div className="cast-action-buttons">
          <button type="button" className="cast-action-button voice">
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <path d="M4 17h6v-6H4zm10 2h6v-6h-6zM10 10h4V6h-4zM6 8l2-2m7 5 2-2M12 2v2m-1-1h2" />
            </svg>
            <b>声をつくる</b>
            <small>VOICE DESIGN</small>
          </button>
          <button type="button" className="cast-action-button wav">
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <circle cx="12" cy="7.5" r="3.25" />
              <path d="M4.5 21c.35-4.25 3.45-7 7.5-7s7.15 2.75 7.5 7" />
            </svg>
            <b>WAVを登録</b>
            <small>REFERENCE WAV</small>
          </button>
        </div>
      </article>

      <article className="styleguide-card">
        <p className="eyebrow">CAST UTILITIES</p>
        <h3>キャスト編集の補助操作</h3>
        <div className="styleguide-actions">
          <button type="button" className="character-ai-assist-button ai-action-button">
            ✦ AIに設定を作ってもらう
          </button>
          <button type="button" className="voice-action-button">
            WAVを指定
          </button>
          <button type="button" className="voice-action-button is-design">
            VoiceDesign
          </button>
          <button type="button" className="voice-action-button is-danger">
            LoRAを削除
          </button>
          <button type="button" className="avatar-remove-button">
            画像を削除
          </button>
        </div>
      </article>
    </div>
  );
}
