import { useState } from "react";
import { api } from "../../api";
import type { LlmRegistry } from "../../types";
import { DialogFooter, DialogHeader, ModalBackdrop } from "../shared/overlays";
import { DropdownIndicator } from "../shared/DropdownIndicator";
import { isWindows } from "../shared/platform";

type Provider = "ollama" | "lmstudio" | "openai";
const defaults: Record<Provider, string> = {
  ollama: "http://127.0.0.1:11434/v1",
  lmstudio: "http://127.0.0.1:1234/v1",
  openai: "",
};

function ModelCombobox({ value, options, onChange }: { value: string; options: string[]; onChange: (value: string) => void }) {
  const [open, setOpen] = useState(false);
  return (
    <label
      className="dialog-form-field llm-model-combobox"
      onBlur={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget)) setOpen(false);
      }}
    >
      モデル
      <div>
        <input
          value={value}
          placeholder="候補から選択、またはモデル名を入力"
          role="combobox"
          aria-autocomplete="list"
          aria-expanded={open}
          aria-controls="remote-llm-model-options"
          onFocus={() => setOpen(true)}
          onChange={(event) => {
            onChange(event.target.value);
            setOpen(true);
          }}
        />
        <button type="button" aria-label="モデル候補を表示" aria-expanded={open} onMouseDown={(event) => event.preventDefault()} onClick={() => setOpen((current) => !current)}>
          <DropdownIndicator />
        </button>
        {open && (
          <div id="remote-llm-model-options" className="llm-model-combobox-menu" role="listbox">
            {options.map((option) => (
              <button
                key={option}
                type="button"
                role="option"
                aria-selected={value === option}
                onMouseDown={(event) => event.preventDefault()}
                onClick={() => {
                  onChange(option);
                  setOpen(false);
                }}
              >
                {option}
              </button>
            ))}
            {options.length === 0 && <p>候補はありません。入力したモデル名をそのまま使えます。</p>}
          </div>
        )}
      </div>
      <small>Ollama Cloudなど一覧にないモデル名も直接入力できます。</small>
    </label>
  );
}

function useRemoteLlmForm(onClose: () => void, onAdded: (value: LlmRegistry) => void) {
  const [provider, setProvider] = useState<Provider>("ollama");
  const [baseUrl, setBaseUrl] = useState(defaults.ollama);
  const [credential, setCredential] = useState("");
  const [keyEnabled, setKeyEnabled] = useState(false);
  const [models, setModels] = useState<string[]>([]);
  const [modelId, setModelId] = useState("");
  const [checked, setChecked] = useState(false);
  const [failed, setFailed] = useState(false);
  const [message, setMessage] = useState("");
  const inspect = async () => {
    setMessage("モデル一覧を取得しています…");
    setFailed(false);
    try {
      const result = await api.inspectRemoteLlmModels({
        provider,
        baseUrl,
        credential: keyEnabled ? credential : undefined,
      });
      setModels(result.models);
      setModelId((current) => current.trim() || result.models[0] || "");
      setChecked(true);
      setMessage(result.models.length ? `${result.models.length}件のモデルを確認しました。候補から選ぶか、モデル名を入力してください。` : "一覧は空でした。モデル名を直接入力できます。");
    } catch (error) {
      setModels([]);
      setChecked(true);
      setFailed(true);
      setMessage(`モデル一覧を取得できませんでした: ${(error as Error).message} モデル名を直接入力して追加できます。`);
    }
  };
  const add = async () => {
    try {
      const result = await api.createRemoteLlmSetting({
        provider,
        baseUrl,
        modelId,
        credential: keyEnabled ? credential : undefined,
      });
      onAdded(result.registry);
      onClose();
    } catch (error) {
      setMessage(`追加できませんでした: ${(error as Error).message}`);
    }
  };
  const changeProvider = (next: Provider) => {
    setProvider(next);
    setBaseUrl(defaults[next]);
    setModels([]);
    setModelId("");
    setChecked(false);
  };
  const changeBaseUrl = (value: string) => {
    setBaseUrl(value);
    setModels([]);
    setModelId("");
    setChecked(false);
  };
  const changeKeyEnabled = (value: boolean) => {
    setKeyEnabled(value);
    setChecked(false);
  };
  const changeCredential = (value: string) => {
    setCredential(value);
    setChecked(false);
  };
  return { provider, baseUrl, credential, keyEnabled, models, modelId, checked, failed, message, setModelId, inspect, add, changeProvider, changeBaseUrl, changeKeyEnabled, changeCredential };
}

export function RemoteDialog({ onClose, onAdded }: { onClose: () => void; onAdded: (value: LlmRegistry) => void }) {
  const form = useRemoteLlmForm(onClose, onAdded);
  return (
    <ModalBackdrop onClose={onClose}>
      <section className="modal llm-setting-dialog" role="dialog" aria-modal="true" aria-labelledby="remote-llm-title">
        <DialogHeader title="接続先からLLMを追加" titleId="remote-llm-title" description="接続を確認し、利用するモデルを1つ選ぶと新しいLLM設定が作られます。" />
        <div className="dialog-form-fields">
          <label className="dialog-form-field">
            種類
            <select value={form.provider} onChange={(event) => form.changeProvider(event.target.value as Provider)}>
              <option value="ollama">Ollama</option>
              <option value="lmstudio">LM Studio</option>
              <option value="openai">OpenAI互換</option>
            </select>
          </label>
          <label className="dialog-form-field">
            URL
            <input value={form.baseUrl} onChange={(event) => form.changeBaseUrl(event.target.value)} />
          </label>
          <label className="checkbox-line">
            <input type="checkbox" checked={form.keyEnabled} onChange={(event) => form.changeKeyEnabled(event.target.checked)} />
            API Keyを設定（任意）
          </label>
          {form.keyEnabled && (
            <label className="dialog-form-field">
              API Key
              <input type="password" autoComplete="new-password" value={form.credential} onChange={(event) => form.changeCredential(event.target.value)} />
              <small>{isWindows() ? "追加時にOSの資格情報ストアへ保存します。" : "追加時にmacOS Keychainへ保存します。"}</small>
            </label>
          )}
          <button type="button" className="secondary" disabled={!form.baseUrl.trim() || (form.keyEnabled && !form.credential.trim())} onClick={() => void form.inspect()}>
            モデルを確認
          </button>
          {form.checked && <ModelCombobox value={form.modelId} options={form.models} onChange={form.setModelId} />}
          {form.message && <p className={form.failed ? "warning-text" : "subtle"}>{form.message}</p>}
        </div>
        <DialogFooter>
          <button type="button" className="secondary" onClick={onClose}>
            キャンセル
          </button>
          <button type="button" className="primary" disabled={!form.checked || !form.modelId.trim()} onClick={() => void form.add()}>
            このモデルを追加
          </button>
        </DialogFooter>
      </section>
    </ModalBackdrop>
  );
}
