import { chooseDirectory } from "../../api-runtime";
import { formatLabels, namingLabels, type Format, type Naming, type Settings } from "./exportSettings";

type Update = (patch: Partial<Settings>) => void;

function FormatFieldset({ settings, onToggle }: { settings: Settings; onToggle: (value: Format, checked: boolean) => void }) {
  return (
    <>
      <fieldset>
        <legend>出力形式</legend>
        {formatLabels
          .filter(([value]) => settings.layout === "split" || value !== "lab")
          .map(([value, label]) => (
            <label key={value}>
              <input type="checkbox" checked={settings.formats.includes(value)} onChange={(event) => onToggle(value, event.target.checked)} />
              {label}
            </label>
          ))}
      </fieldset>
      {!settings.formats.length && <p className="warning-text">出力形式を1つ以上選択してください。</p>}
    </>
  );
}

function LayoutFieldset({ settings, onSelect }: { settings: Settings; onSelect: (layout: Settings["layout"]) => void }) {
  return (
    <fieldset>
      <legend>ファイル構成</legend>
      <label>
        <input type="radio" checked={settings.layout === "joined"} onChange={() => onSelect("joined")} />
        1ファイルに連結
      </label>
      <label>
        <input type="radio" checked={settings.layout === "split"} onChange={() => onSelect("split")} />
        発話行ごとに分割
      </label>
    </fieldset>
  );
}

function NamingFieldset({ settings, previews, duplicate, update }: { settings: Settings; previews: string[]; duplicate: boolean; update: Update }) {
  return (
    <fieldset>
      <legend>ファイル名</legend>
      <div className="export-naming">
        {settings.naming.map((value, index) => (
          <select
            key={index}
            aria-label={`命名要素${index + 1}`}
            value={value}
            onChange={(event) =>
              update({
                naming: settings.naming.map((item, itemIndex) => (itemIndex === index ? (event.target.value as Naming) : item)),
              })
            }
          >
            {namingLabels.map(([option, label]) => (
              <option key={option} value={option}>
                {label}
              </option>
            ))}
          </select>
        ))}
      </div>
      <div className="export-name-preview">
        <span className="subtle">ファイル名のサンプル</span>
        {previews.length ? (
          <div className="export-name-preview-list">
            {previews.slice(0, 3).map((name, index) => (
              <div key={`${index}-${name}`}>{name}</div>
            ))}
          </div>
        ) : (
          <p className="subtle">対象行なし</p>
        )}
      </div>
      {settings.naming.every((item) => item === "none") && <p className="warning-text">命名要素を1つ以上指定してください。</p>}
      {duplicate && <p className="warning-text">正規化後に重複するファイル名があります。</p>}
    </fieldset>
  );
}

function SubtitleFieldset({ settings, update }: { settings: Settings; update: Update }) {
  return (
    <fieldset>
      <legend>字幕TXT（開発版）</legend>
      <label>
        <input type="checkbox" checked={settings.subtitleIncludeEmoji} onChange={(event) => update({ subtitleIncludeEmoji: event.target.checked })} />
        絵文字を含む発話行をそのまま出力する
      </label>
      <p className="subtle">学習モデル制作向け。通常の字幕TXTでは発話用絵文字を除去します。</p>
    </fieldset>
  );
}

function ScriptFieldset({ settings, update }: { settings: Settings; update: Update }) {
  return (
    <fieldset>
      <legend>台本TXT</legend>
      <label>
        区切り
        <select value={settings.scriptDelimiter} onChange={(event) => update({ scriptDelimiter: event.target.value })}>
          <option value="\t">タブ</option>
          <option value=",">カンマ</option>
          <option value=" ">半角スペース</option>
          <option value="|">|</option>
        </select>
      </label>
      <label>
        <input type="checkbox" checked={settings.quoteDialogue} onChange={(event) => update({ quoteDialogue: event.target.checked })} />
        セリフを「」で囲む
      </label>
    </fieldset>
  );
}

function DestinationField({ destinationDir, onChange }: { destinationDir: string; onChange: (value: string) => void }) {
  return (
    <label>
      保存先
      <div className="export-destination">
        <input readOnly value={destinationDir} placeholder="フォルダを選択" />
        <button type="button" className="secondary settings-inline-action" onClick={() => void chooseDirectory("エクスポート先を選択", destinationDir).then((value) => value && onChange(value))}>
          フォルダを選択
        </button>
      </div>
    </label>
  );
}

export function ExportSettingsForm({
  settings,
  previews,
  duplicate,
  destinationDir,
  error,
  update,
  onToggleFormat,
  onSelectLayout,
  onDestinationChange,
}: {
  settings: Settings;
  previews: string[];
  duplicate: boolean;
  destinationDir: string;
  error: string;
  update: Update;
  onToggleFormat: (value: Format, checked: boolean) => void;
  onSelectLayout: (layout: Settings["layout"]) => void;
  onDestinationChange: (value: string) => void;
}) {
  return (
    <div className="export-settings">
      <FormatFieldset settings={settings} onToggle={onToggleFormat} />
      <LayoutFieldset settings={settings} onSelect={onSelectLayout} />
      {settings.layout === "split" && <NamingFieldset settings={settings} previews={previews} duplicate={duplicate} update={update} />}
      {import.meta.env.DEV && settings.formats.includes("subtitle_txt") && <SubtitleFieldset settings={settings} update={update} />}
      {settings.formats.includes("script_txt") && <ScriptFieldset settings={settings} update={update} />}
      <DestinationField destinationDir={destinationDir} onChange={onDestinationChange} />
      {error && (
        <p className="warning-text" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}
