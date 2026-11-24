import { useState } from "react";
import type { LlmCard, LlmEndpoint } from "../../types";
import { LlmCardTestControls } from "./LlmCardTestControls";
import { modelTestDisabled } from "./modelRuntimeChoices";
import { ModelRuntimeSetting } from "./ModelRuntimeSetting";
import { MtpSetting } from "./MtpSetting";
import { visibleEndpointUrl } from "./llmCardPresentation";
import { DeferredNumberInput } from "../shared/DeferredNumberInput";

type Settings = LlmCard["settings"];
const statusLabels: Record<LlmCard["testStatus"]["state"], string> = {
  passed: "接続でき、モデルの使用に問題がないことを確認しました。",
  failed: "接続またはモデルの使用に問題があります。",
  testing: "接続とモデルの基本動作を確認しています…",
  untested: "まだ動作確認していません。",
};

const providerLabels: Record<LlmEndpoint["provider"], string> = {
  ollama: "Ollama",
  lmstudio: "LM Studio",
  openai: "OpenAI互換",
  "scena-local": "SCENA",
};

const capabilitySources = {
  user: "手動上書き",
  "provider-api": "Provider API",
  catalog: "内蔵カタログ",
  "model-config": "モデル設定",
  unknown: "未確認",
} as const;
const structuredLabels = {
  constrained: "Schema制約（確認済み）",
  schema_validated: "Schema指定・応答検証済み",
  unsupported: "互換解析",
  unknown: "未確認（互換解析）",
} as const;

function StructuredOutputFacts({ card }: { card: LlmCard }) {
  const value = card.capabilities?.structuredOutput;
  const reasons = [value?.nonStreaming.reasonCode, value?.streaming.reasonCode].filter(Boolean).join(" / ");
  return (
    <>
      <div>
        <dt>Schema出力（通常）</dt>
        <dd>{structuredLabels[value?.nonStreaming.state ?? "unknown"]}</dd>
      </div>
      <div>
        <dt>Schema出力（stream）</dt>
        <dd>{structuredLabels[value?.streaming.state ?? "unknown"]}</dd>
      </div>
      {reasons && (
        <div>
          <dt>Schema診断</dt>
          <dd>{reasons}</dd>
        </div>
      )}
    </>
  );
}

function AdvancedSettings({ card, endpoint, settings, setSettings }: { card: LlmCard; endpoint?: LlmEndpoint; settings: Settings; setSettings: (value: Settings) => void }) {
  return (
    <details className="image-prompt-details llm-card-details">
      <summary>高度な設定</summary>
      <label>
        Context自動割当の上限
        <DeferredNumberInput min={256} max={1048576} placeholder="自動認識値を使用" value={settings.contextLimit ?? undefined} onCommit={(value) => setSettings({ ...settings, contextLimit: value ?? null })} />
      </label>
      <label>
        TTL（秒）
        <DeferredNumberInput
          min={0}
          max={86400}
          value={settings.ttlSeconds}
          onCommit={(value) => {
            if (value !== undefined) setSettings({ ...settings, ttlSeconds: value });
          }}
        />
      </label>
      <label>
        メモリガード
        <select value={settings.memoryGuard} onChange={(event) => setSettings({ ...settings, memoryGuard: event.target.value as Settings["memoryGuard"] })}>
          <option value="safe">Safe</option>
          <option value="balanced">Balanced</option>
          <option value="aggressive">Aggressive</option>
        </select>
      </label>
      <label className="checkbox-line">
        <input type="checkbox" checked={settings.thinking} onChange={(event) => setSettings({ ...settings, thinking: event.target.checked })} />
        Thinkingを有効にする
      </label>
      <fieldset className="llm-sampling-settings">
        <legend>生成のばらつき</legend>
        <p className="subtle">未指定の項目は、台本作成や発音提案など各機能の既定値を使います。</p>
        <label>
          Temperature
          <DeferredNumberInput min={0} max={2} step={0.05} placeholder="機能の既定値" value={settings.temperature ?? undefined} onCommit={(value) => setSettings({ ...settings, temperature: value ?? null })} />
        </label>
        <label>
          Top-p
          <DeferredNumberInput min={0} max={1} step={0.05} placeholder="モデルの既定値" value={settings.topP ?? undefined} onCommit={(value) => setSettings({ ...settings, topP: value ?? null })} />
        </label>
        {endpoint?.provider !== "openai" && (
          <>
            <label>
              Top-k
              <DeferredNumberInput min={0} max={1000} step={1} placeholder="モデルの既定値" value={settings.topK ?? undefined} onCommit={(value) => setSettings({ ...settings, topK: value ?? null })} />
            </label>
            <label>
              Min-p
              <DeferredNumberInput min={0} max={1} step={0.01} placeholder="モデルの既定値" value={settings.minP ?? undefined} onCommit={(value) => setSettings({ ...settings, minP: value ?? null })} />
            </label>
            <label>
              繰り返し抑制
              <DeferredNumberInput min={0} max={2} step={0.05} placeholder="モデルの既定値" value={settings.repetitionPenalty ?? undefined} onCommit={(value) => setSettings({ ...settings, repetitionPenalty: value ?? null })} />
            </label>
          </>
        )}
      </fieldset>
      {endpoint?.provider === "scena-local" && (
        <>
          <label className="checkbox-line">
            <input type="checkbox" checked={settings.trustRemoteCode} onChange={(event) => setSettings({ ...settings, trustRemoteCode: event.target.checked })} />
            モデル付属コードの実行を許可
          </label>
          <p className={`subtle${settings.trustRemoteCode ? " llm-remote-code-warning" : ""}`}>通常はオフを推奨します。独自構造のモデルを読み込むため、配布元がモデルに同梱したコードをMac上で実行します。信頼できるモデルでだけ有効にしてください。</p>
        </>
      )}
      <MtpSetting card={card} settings={settings} setSettings={setSettings} />
    </details>
  );
}

function CatalogFacts({ card }: { card: LlmCard }) {
  const catalog = card.capabilities?.catalog;
  if (!catalog) return null;
  return (
    <div>
      <dt>カタログ補完</dt>
      <dd title={catalog.sourceUrl}>
        {catalog.fields.map((field) => (field === "inputTokenLimit" ? "Context" : "出力上限")).join("・")}
        {`（公式資料 ${catalog.verifiedAt} 確認／接続保証ではありません）`}
      </dd>
    </div>
  );
}

function LlmTestSection({ card, onComplete }: { card: LlmCard; onComplete: () => void }) {
  const [reported, setReported] = useState<{ text: string; state: "passed" | "failed" | "testing"; checkedAt: number | null } | null>(null);
  const diagnostic = card.runtime?.job?.message;
  const persisted = { text: diagnostic && card.testStatus.state === "failed" ? diagnostic : statusLabels[card.testStatus.state], state: card.testStatus.state };
  const status = reported?.checkedAt === card.testStatus.checkedAt ? reported : persisted;
  return (
    <div className="llm-test-section" role="group" aria-labelledby="llm-test-heading">
      <div className="llm-detail-section-heading">
        <h3 id="llm-test-heading">動作確認</h3>
        <p className={`llm-test-status is-${status.state}`} role="status">
          {status.text}
        </p>
      </div>
      <LlmCardTestControls card={card} disabled={modelTestDisabled(card)} cardId={card.id} onStatus={(text, state) => setReported({ text, state, checkedAt: card.testStatus.checkedAt })} onComplete={onComplete} />
    </div>
  );
}

function FactValue({ value }: { value: number | null | undefined }) {
  return <>{value == null ? "未確認" : value.toLocaleString()}</>;
}

function GgufFacts({ card }: { card: LlmCard }) {
  if (card.localMetadata?.format !== "GGUF") return null;
  const backend = card.capabilities?.backend;
  return (
    <>
      <div>
        <dt>モデル最大Context</dt>
        <dd>
          <FactValue value={card.capabilities?.modelContextLimit ?? card.localMetadata.modelContextLimit} />
        </dd>
      </div>
      <div>
        <dt>今回の割当Context</dt>
        <dd>
          <FactValue value={card.capabilities?.runtimeContextLimit} />
        </dd>
      </div>
      <div>
        <dt>実行方式</dt>
        <dd>{backend === "cuda" ? "CUDA" : backend === "cpu" ? "CPU" : "未確認"}</dd>
      </div>
    </>
  );
}

function ProbeFact({ card }: { card: LlmCard }) {
  if (!card.lastProbe)
    return (
      <div>
        <dt>直近の接続診断</dt>
        <dd>未実施</dd>
      </div>
    );
  const state = card.lastProbe.state === "passed" ? "成功" : "失敗";
  return (
    <div>
      <dt>直近の接続診断</dt>
      <dd>
        {state}
        {card.lastProbe.errorCategory ? ` (${card.lastProbe.errorCategory})` : ""}
      </dd>
    </div>
  );
}

function ConnectionFacts({ card, endpoint, endpointUrl }: { card: LlmCard; endpoint?: LlmEndpoint; endpointUrl: string }) {
  return (
    <dl className="llm-connection-facts">
      <div>
        <dt>LLMモデル</dt>
        <dd title={card.modelId}>
          {card.modelId} ({endpoint ? providerLabels[endpoint.provider] : "LLM"})
        </dd>
      </div>
      {endpointUrl && (
        <div>
          <dt>接続先URL</dt>
          <dd title={endpointUrl}>{endpointUrl}</dd>
        </div>
      )}
      <div>
        <dt>自動認識したContext</dt>
        <dd>
          <FactValue value={card.capabilities?.inputTokenLimit} />
        </dd>
      </div>
      <GgufFacts card={card} />
      <div>
        <dt>出力上限</dt>
        <dd>
          <FactValue value={card.capabilities?.outputTokenLimit} />
        </dd>
      </div>
      <div>
        <dt>能力情報源</dt>
        <dd>{(card.capabilities && capabilitySources[card.capabilities.source]) || "未確認"}</dd>
      </div>
      <CatalogFacts card={card} />
      <StructuredOutputFacts card={card} />
      <ProbeFact card={card} />
    </dl>
  );
}

export function LlmCardDetails({ card, endpoint, displayName, setDisplayName, settings, setSettings, onTestComplete }: { card: LlmCard; endpoint?: LlmEndpoint; displayName: string; setDisplayName: (value: string) => void; settings: Settings; setSettings: (value: Settings) => void; onTestComplete: () => void }) {
  const endpointUrl = visibleEndpointUrl(endpoint);
  return (
    <div className="llm-card-dialog-details">
      <section className="llm-detail-section" aria-labelledby="llm-identity-heading">
        <h3 id="llm-identity-heading">モデルと接続</h3>
        <label className="dialog-form-field">
          表示名
          <input value={displayName} maxLength={160} onChange={(event) => setDisplayName(event.target.value)} />
        </label>
        <ConnectionFacts card={card} endpoint={endpoint} endpointUrl={endpointUrl} />
        {card.source !== "remote" && <ModelRuntimeSetting card={card} onRefresh={onTestComplete} />}
        <LlmTestSection card={card} onComplete={onTestComplete} />
      </section>
      <AdvancedSettings card={card} endpoint={endpoint} settings={settings} setSettings={setSettings} />
    </div>
  );
}
