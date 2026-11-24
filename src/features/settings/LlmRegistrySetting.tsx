import { isWindows } from "../shared/platform";
import { LlamaCppRuntimeSetting } from "./LlamaCppRuntimeSetting";
import { useState } from "react";
import { api } from "../../api";
import type { LlmCard, LlmEndpoint, LlmRegistry } from "../../types";
import { DialogFooter, DialogHeader, ModalBackdrop } from "../shared/overlays";
import { confirmDestructiveAction, useDestructiveConfirmation } from "../shared/destructiveConfirmation";
import { BuiltInLlmDialog } from "./BuiltInLlmDialog";
import { RemoteDialog } from "./RemoteLlmDialog";
import { LlmCardDetails } from "./LlmCardDetails";
import { ModelBoardCardFooter } from "./ModelBoardCardFooter";
import { modelRegistryCache } from "../shared/modelRegistryCache";
import { ModelSelectionPopover } from "./ModelSelectionPopover";
import { sortLlmModelCards } from "./modelCardOrder";
import { OmlxRuntimeSetting } from "./OmlxRuntimeSetting";
import { useSequentialPolling } from "../shared/useSequentialPolling";

const labels: Record<LlmEndpoint["provider"], string> = {
  ollama: "Ollama",
  lmstudio: "LM Studio",
  openai: "OpenAI互換",
  "scena-local": "SCENA",
};
const providerClasses: Record<LlmEndpoint["provider"], string> = {
  ollama: "is-ollama",
  lmstudio: "is-lmstudio",
  openai: "is-openai",
  "scena-local": "is-scena",
};

function CardDialog({ card, endpoint, isDefault, onClose, onRegistry, onMessage, onRefresh }: { card: LlmCard; endpoint?: LlmEndpoint; isDefault: boolean; onClose: () => void; onRegistry: (value: LlmRegistry) => void; onMessage: (value: string) => void; onRefresh: () => Promise<void> }) {
  const confirmationKey = `llm-card-removal:${card.id}`;
  const confirming = useDestructiveConfirmation(confirmationKey);
  const [confirmationMessage, setConfirmationMessage] = useState("");
  const [displayName, setDisplayName] = useState(card.displayName);
  const [settings, setSettings] = useState(card.settings);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState("");
  const removal = card.source === "managed" ? "SCENAが管理するモデルファイルもMacから削除します。この操作は元に戻せません。" : card.source === "external" ? "選んだフォルダの元ファイルは削除しません。" : "";
  const remove = async () => {
    const action = card.source === "managed" ? "削除" : "登録解除";
    const confirmation = removal || "このLLMの登録を解除します。";
    if (!confirmDestructiveAction(confirmationKey, setConfirmationMessage, confirmation, action)) return;
    try {
      const result = await api.deleteLlmCard(card.id);
      onRegistry(result.registry);
      onMessage(result.action === "deleted" ? "モデルと管理ファイルを削除しました。" : "LLMの登録を解除しました。");
      onClose();
    } catch (error) {
      onMessage(`削除できませんでした: ${(error as Error).message}`);
    }
  };
  const removalClass = `llm-removal-button ${card.source === "managed" ? "danger" : "secondary"}${confirming ? " is-confirming" : ""}`;
  const removalLabel = confirming ? (card.source === "managed" ? "もう一度押してモデルを削除" : "もう一度押して登録を解除") : card.source === "managed" ? "モデルを削除" : "登録を解除";
  const removeButton = (
    <button type="button" className={removalClass} data-destructive-confirmation-key={confirmationKey} title={removal || undefined} onClick={() => void remove()}>
      {removalLabel}
    </button>
  );
  const defaultButton = (
    <button type="button" className={`secondary llm-default-button${isDefault ? " is-active" : ""}`} disabled={isDefault} aria-pressed={isDefault} onClick={() => void api.setDefaultLlmCard(card.id).then(onRegistry)}>
      {isDefault ? "既定のLLM" : "既定にする"}
    </button>
  );
  const save = async () => {
    setSaving(true);
    setSaveError("");
    try {
      await api.updateLlmCard(card.id, { displayName: displayName.trim(), settings });
      await onRefresh();
      onClose();
    } catch (error) {
      setSaveError(`保存できませんでした: ${(error as Error).message}`);
    } finally {
      setSaving(false);
    }
  };
  return (
    <ModalBackdrop onClose={onClose}>
      <section className="modal llm-setting-dialog" role="dialog" aria-modal="true" aria-labelledby="llm-card-title">
        <DialogHeader title={card.displayName} titleId="llm-card-title" actions={defaultButton} />
        <LlmCardDetails card={card} endpoint={endpoint} displayName={displayName} setDisplayName={setDisplayName} settings={settings} setSettings={setSettings} onTestComplete={() => void onRefresh()} />
        {confirming && <p className="warning-text">{confirmationMessage}</p>}
        {saveError && (
          <p className="warning-text" role="alert">
            {saveError}
          </p>
        )}
        <DialogFooter leading={removeButton}>
          <button type="button" className="secondary" onClick={onClose}>
            閉じる
          </button>
          <button type="button" className="primary" disabled={saving || !displayName.trim()} onClick={() => void save()}>
            {saving ? "保存中…" : "保存"}
          </button>
        </DialogFooter>
      </section>
    </ModalBackdrop>
  );
}

function RuntimeBadge({ card }: { card: LlmCard }) {
  const job = card.runtime?.job;
  const verification = card.testStatus?.state ?? "untested";
  let label = verification === "passed" ? "使用可能" : verification === "failed" ? "動作確認失敗" : "動作未確認";
  if (verification === "testing" || (job && !["complete", "failed", "cancelled", "interrupted"].includes(job.state))) label = "動作確認中";
  return (
    <span className="subtle" title={job?.message}>
      {label}
    </span>
  );
}

function LlmCardContent({ card, endpoint, isDefault }: { card: LlmCard; endpoint?: LlmEndpoint; isDefault: boolean }) {
  const revision = card.localMetadata?.revision ? card.localMetadata.revision.slice(0, 12) : "version未取得";
  const size = card.localMetadata?.diskBytes == null ? "容量未取得" : `${(card.localMetadata.diskBytes / 1024 ** 3).toFixed(1)} GB`;
  return (
    <>
      <span className="model-card-heading">
        <strong>{card.displayName}</strong>
      </span>
      <span className="model-card-body llm-card-meta">{endpoint ? <span className={`model-card-tag ${providerClasses[endpoint.provider]}`}>{labels[endpoint.provider]}</span> : <span className="model-card-tag is-unknown">LLM</span>}</span>
      {card.source !== "remote" && <RuntimeBadge card={card} />}
      <ModelBoardCardFooter isDefault={isDefault} metadata={`${revision} · ${size}`} />
    </>
  );
}

function LlmModelSelector({ registry, message, onAccept, onMessage, onDialog, onDetails }: { registry: LlmRegistry | null; message: string; onAccept: (value: LlmRegistry) => void; onMessage: (value: string) => void; onDialog: (value: "built-in" | "remote") => void; onDetails: (id: string) => void }) {
  const cards = sortLlmModelCards(registry?.cards ?? [], registry?.endpoints ?? []);
  const defaultCard = cards.find((card) => card.id === registry?.defaultCardId);
  const endpoint = (card: LlmCard) => registry?.endpoints.find((item) => item.id === card.endpointId);
  const selectedContent = defaultCard ? (
    <LlmCardContent card={defaultCard} endpoint={endpoint(defaultCard)} isDefault />
  ) : (
    <span className="model-selection-empty">
      <strong>{registry ? (cards.length ? "LLMモデルを選択してください" : "LLMモデルがありません") : "LLMモデルを読み込んでいます…"}</strong>
      <span>展開してモデルを追加できます</span>
    </span>
  );
  const choose = async (id: string) => {
    try {
      onAccept(await api.setDefaultLlmCard(id));
      onMessage("");
      return true;
    } catch (error) {
      onMessage(`既定のLLMを切り替えられませんでした: ${(error as Error).message}`);
      return false;
    }
  };
  const additions = [
    <button key="built-in" type="button" className="llm-add-card model-add-card registry-add-card" onClick={() => onDialog("built-in")}>
      <strong>+ SCENA内蔵LLMにモデルを追加</strong>
      <span>Hugging Faceまたは{isWindows() ? "PC" : "Mac"}内のモデル</span>
    </button>,
    <button key="remote" type="button" className="llm-add-card model-add-card registry-add-card" onClick={() => onDialog("remote")}>
      <strong>+ 接続先を追加</strong>
      <span>Ollama・LM Studio・OpenAI互換</span>
    </button>,
  ];
  return (
    <ModelSelectionPopover
      label="LLMモデル"
      selectedId={registry?.defaultCardId ?? null}
      selectedContent={selectedContent}
      options={cards.map((card) => ({
        id: card.id,
        content: <LlmCardContent card={card} endpoint={endpoint(card)} isDefault={card.id === registry?.defaultCardId} />,
      }))}
      additions={additions}
      loading={!registry}
      error={message.startsWith("既定のLLM") ? message : undefined}
      onSelect={choose}
      onDetails={defaultCard ? () => onDetails(defaultCard.id) : undefined}
    />
  );
}

export function LlmRegistrySetting() {
  const [registry, setRegistry] = useState<LlmRegistry | null>(modelRegistryCache.llm());
  const [dialog, setDialog] = useState<"built-in" | "remote" | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [message, setMessage] = useState("");
  const accept = (value: LlmRegistry) => {
    modelRegistryCache.setLlm(value);
    setRegistry(value);
    window.dispatchEvent(new CustomEvent("scena-llm-registry", { detail: value }));
  };
  const refresh = async () => accept(await api.llmRegistry());
  useSequentialPolling({ enabled: true, intervalMs: 2000, poll: api.llmRegistry, onResult: accept, onError: (error) => setMessage((error as Error).message), errorPolicy: "retry" });
  const selectedCard = registry?.cards.find((item) => item.id === selected);
  return (
    <div className="llm-registry-setting">
      <div>
        <section className="llm-model-data-section" aria-label="LLMモデル設定">
          <LlmModelSelector registry={registry} message={message} onAccept={accept} onMessage={setMessage} onDialog={setDialog} onDetails={setSelected} />
        </section>
      </div>
      {message && (
        <p className="subtle" role="status">
          {message}
        </p>
      )}
      {dialog === "remote" && (
        <RemoteDialog
          onClose={() => setDialog(null)}
          onAdded={(value) => {
            accept(value);
            setMessage("LLMを追加しました。");
          }}
        />
      )}
      {dialog === "built-in" && (
        <BuiltInLlmDialog
          onClose={() => setDialog(null)}
          onAdded={async (name) => {
            await refresh();
            setDialog(null);
            setMessage(`${name}を追加しました。`);
          }}
        />
      )}
      {selectedCard && <CardDialog card={selectedCard} endpoint={registry?.endpoints.find((item) => item.id === selectedCard.endpointId)} isDefault={registry?.defaultCardId === selectedCard.id} onClose={() => setSelected(null)} onRegistry={accept} onMessage={setMessage} onRefresh={refresh} />}
    </div>
  );
}

export function LlmRuntimeManagementButton() {
  return isWindows() ? <LlamaCppRuntimeSetting compact /> : <OmlxRuntimeSetting compact />;
}
