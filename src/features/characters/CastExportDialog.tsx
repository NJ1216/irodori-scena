import { useEffect, useState } from "react";
import { api, chooseDirectory, defaultExportDirectory } from "../../api";
import { ApiError } from "../../api-error";
import type { Character } from "../../types";
import { DialogFooter, DialogHeader, ModalBackdrop } from "../shared/overlays";
import { avatarImageUrl } from "../shared/studio-utils";
import { ScaledDraftCastName } from "./CastNotebook";

export function CastExportDialog({ characters, onClose }: { characters: Character[]; onClose: () => void }) {
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [destination, setDestination] = useState("");
  const [busy, setBusy] = useState(false);
  const [collisions, setCollisions] = useState<string[]>([]);
  const [result, setResult] = useState<Awaited<ReturnType<typeof api.exportCasts>> | null>(null);
  useEffect(() => {
    let active = true;
    void defaultExportDirectory().then((value) => {
      if (active && value) setDestination(value);
    });
    return () => {
      active = false;
    };
  }, []);
  const toggleAll = () => setSelected(selected.size === characters.length ? new Set() : new Set(characters.map((item) => item.id)));
  async function chooseDestination() {
    const initial = destination || (await defaultExportDirectory());
    const value = await chooseDirectory("キャストの保存先を選択", initial);
    if (value) setDestination(value);
  }
  async function run(overwrite = false) {
    setBusy(true);
    try {
      setResult(await api.exportCasts([...selected], destination, overwrite));
      setCollisions([]);
    } catch (error) {
      if (error instanceof ApiError && error.status === 409 && error.code === "cast_export_conflict") {
        const files = (error.detail as { files?: unknown }).files;
        setCollisions(Array.isArray(files) ? files.filter((item): item is string => typeof item === "string") : []);
      } else throw error;
    } finally {
      setBusy(false);
    }
  }
  return (
    <ModalBackdrop onClose={onClose} disabled={busy}>
      <section className="modal cast-exchange-dialog" role="dialog" aria-modal="true" aria-label="キャストエクスポート">
        <DialogHeader eyebrow="CAST EXPORT" title={result ? "エクスポート結果" : "キャストをエクスポート"} description={result ? result.destinationDir : "選択したキャストを1人1ファイルで保存します。"} />
        {result ? (
          <div className="cast-exchange-results">
            {result.warnings?.map((warning) => (
              <p role="alert" className="warning-box" key={warning}>
                {warning}
              </p>
            ))}
            {result.results.map((item) => (
              <p key={item.castId}>{item.status === "exported" ? `✓ ${item.path}` : `× ${item.name ?? item.castId}: ${item.error}`}</p>
            ))}
          </div>
        ) : (
          <>
            {characters.some((character) => selected.has(character.id) && character.lora) && <p className="warning-box">LoRA設定は保持しますが、adapter本体はキャストファイルに含まれません。別の環境ではadapterを別途登録する必要があります。</p>}
            <div className="cast-exchange-toolbar">
              <button type="button" className="link-button" onClick={toggleAll}>
                {selected.size === characters.length && characters.length ? "すべて解除" : "すべて選択"}
              </button>
              <span>{selected.size} 人選択</span>
            </div>
            <div className="draft-cast-picker cast-export-picker" role="group" aria-label="エクスポートするキャスト">
              {characters.map((character) => {
                const thumbnail = character.avatarThumbnailUrl ?? character.avatarUrl;
                const active = selected.has(character.id);
                return (
                  <button
                    key={character.id}
                    type="button"
                    className={`draft-cast-picker-item${active ? " is-selected" : ""}`}
                    aria-pressed={active}
                    onClick={() =>
                      setSelected((current) => {
                        const next = new Set(current);
                        if (next.has(character.id)) next.delete(character.id);
                        else next.add(character.id);
                        return next;
                      })
                    }
                  >
                    <span className={`draft-cast-picker-avatar${thumbnail ? " has-image" : ""}`} aria-hidden="true">
                      {thumbnail ? <img src={avatarImageUrl(thumbnail, character.avatarVersion)} alt="" loading="lazy" decoding="async" /> : character.name.slice(0, 1)}
                    </span>
                    <ScaledDraftCastName name={character.name} />
                  </button>
                );
              })}
            </div>
            <label className="cast-exchange-destination-field">
              保存先
              <div className="export-destination">
                <input readOnly value={destination} placeholder="フォルダを選択" />
                <button type="button" className="secondary settings-inline-action" onClick={() => void chooseDestination()}>
                  フォルダを選択
                </button>
              </div>
            </label>
            {collisions.length > 0 && (
              <div className="warning-box">
                <b>次のファイルを上書きしますか？</b>
                {collisions.map((name) => (
                  <div key={name}>{name}</div>
                ))}
              </div>
            )}
          </>
        )}
        <DialogFooter>
          <button type="button" className="secondary" disabled={busy} onClick={onClose}>
            {result ? "閉じる" : "キャンセル"}
          </button>
          {!result && (
            <button type="button" disabled={busy || !selected.size || !destination} onClick={() => void run(collisions.length > 0)}>
              {collisions.length ? "まとめて上書き" : "エクスポート"}
            </button>
          )}
        </DialogFooter>
      </section>
    </ModalBackdrop>
  );
}
