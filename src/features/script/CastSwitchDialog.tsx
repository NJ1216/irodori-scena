import { useMemo, useState } from "react";
import type { StudioProject } from "../../types";
import { DialogFooter, DialogHeader, ModalBackdrop } from "../shared/overlays";
import { avatarImageUrl } from "../shared/studio-utils";
import { CharacterPicker } from "./CharacterPicker";

export function CastSwitchDialog({ project, busy, onClose, onApply }: { project: StudioProject; busy: boolean; onClose: () => void; onApply: (mappings: Array<{ fromCharacterId: string; toCharacterId: string }>) => Promise<void> }) {
  const usedIds = useMemo(() => Array.from(new Set(project.scenes.flatMap((scene) => scene.lines.map((line) => line.characterId)).filter(Boolean))), [project.scenes]);
  const [targets, setTargets] = useState<Record<string, string>>(Object.fromEntries(usedIds.map((id) => [id, id])));
  const mappings = usedIds.filter((id) => targets[id] && targets[id] !== id).map((id) => ({ fromCharacterId: id, toCharacterId: targets[id] }));
  return (
    <ModalBackdrop onClose={onClose}>
      <section className="modal cast-switch-dialog" role="dialog" aria-modal="true" aria-label="キャストの一括切り替え">
        <DialogHeader eyebrow="CAST SWITCH" title="キャストの一括切り替え" description="すべての変更を同時に適用します。交換や、複数キャストの統合も可能です。" />
        <div className="cast-switch-grid">
          {usedIds.map((sourceId) => {
            const source = project.characters.find((item) => item.id === sourceId);
            return (
              <div className="cast-switch-row" key={sourceId}>
                <span className="cast-switch-source">
                  <span className="cast-switch-avatar" aria-hidden="true">
                    {source?.avatarUrl ? <img src={avatarImageUrl(source.avatarUrl, source.avatarVersion)} alt="" /> : (source?.name ?? sourceId).slice(0, 1)}
                  </span>
                  <strong>{source?.name ?? sourceId}</strong>
                </span>
                <b>→</b>
                <CharacterPicker
                  characters={project.characters}
                  value={targets[sourceId]}
                  disabled={busy}
                  variant="field"
                  label={`${source?.name ?? sourceId}の切り替え先`}
                  onChange={(characterId) =>
                    setTargets((current) => ({
                      ...current,
                      [sourceId]: characterId,
                    }))
                  }
                />
              </div>
            );
          })}
        </div>
        <p className="subtle">変更行の旧テイクは残りますが、選択は解除されます。</p>
        <DialogFooter>
          <button type="button" disabled={busy} onClick={onClose}>
            キャンセル
          </button>
          <button type="button" className="primary" disabled={busy || mappings.length === 0} onClick={() => void onApply(mappings)}>
            {busy ? "切り替え中…" : "同時に切り替える"}
          </button>
        </DialogFooter>
      </section>
    </ModalBackdrop>
  );
}
