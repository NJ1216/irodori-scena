import { useLayoutEffect, useState } from "react";
import type { LlmConnection, TtsProjectSelection } from "../../types";
import { LlmModelHintDialog } from "./LlmModelHintDialog";
import { LlmRegistrySetting, LlmRuntimeManagementButton } from "./LlmRegistrySetting";
import { TtsRegistrySetting } from "./TtsRegistrySetting";
import { RhubarbSetting } from "./RhubarbSetting";

export function SettingsView({
  connection,
  isScratch,
  onChange,
  onTtsSelectionChange,
  focusLlmHeading = false,
  onHeadingFocused,
}: {
  connection: LlmConnection;
  isScratch: boolean;
  onChange: (connection: LlmConnection) => void;
  onTtsSelectionChange: (selection: TtsProjectSelection) => void;
  focusLlmHeading?: boolean;
  onHeadingFocused?: () => void;
}) {
  const [hintOpen, setHintOpen] = useState(false);
  useLayoutEffect(() => {
    if (!focusLlmHeading) return;
    const heading = document.getElementById("llm-settings-heading");
    heading?.scrollIntoView({ block: "center" });
    heading?.focus();
    onHeadingFocused?.();
  }, [focusLlmHeading, onHeadingFocused]);
  return (
    <section className="page settings-page">
      <div className="page-heading accent-heading">
        <p className="eyebrow type-eyebrow">SETTINGS</p>
        <h1 className="type-display">設定</h1>
        <p className="type-body">AI機能は既定のLLMモデルを共用し、音声モデルの実行環境はSCENAが自動管理します。</p>
      </div>
      <div className="settings-panels">
        <section className="panel settings-panel">
          <TtsRegistrySetting isScratch={isScratch} onSelectionChanged={onTtsSelectionChange} onLegacyEngine={(engineDir) => onChange({ ...connection, engineDir, engineDirVerified: true })} />
        </section>
        <section className="panel settings-panel" aria-labelledby="llm-settings-heading">
          <div className="settings-panel-intro">
            <div className="settings-card-title-row">
              <span className="settings-title-cluster">
                <h2 id="llm-settings-heading" tabIndex={-1}>
                  LLM設定
                </h2>
                <LlmRuntimeManagementButton />
              </span>
              <button type="button" className="quiet-button llm-hint-link" onClick={() => setHintOpen(true)}>
                使い方のヒント
              </button>
            </div>
            <p className="subtle">AI機能で使う既定のモデルです。外部接続は内蔵LLM実行基盤の影響を受けません。</p>
          </div>
          <LlmRegistrySetting />
          {hintOpen && <LlmModelHintDialog onClose={() => setHintOpen(false)} />}
        </section>
        <section className="panel settings-panel" aria-labelledby="rhubarb-settings-heading">
          <RhubarbSetting />
        </section>
      </div>
    </section>
  );
}
