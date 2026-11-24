import { LoraAuditionBar } from "./LoraAuditionBar";
import type { Character, StudioProject } from "../../types";
import type { LoraAsset, LoraStatus } from "../../types/lora";
import type { LoraMix } from "../../types/project";
import type { DecodedAudioPlaybackControl } from "../shared/decodedAudioPlayer";
import { effectiveMix, editableMix } from "./loraMix";
import { LoraMixEditor } from "./LoraMixEditor";
import { useMixLibrary } from "./useMixLibrary";
import { MixLibraryActions } from "./MixLibraryActions";
import { useLoraAudition } from "./useLoraAudition";

export function CastLoraMixSetting({ character, project, onChange, onPlay, referenceState = "ready" }: { character: Character; referenceState?: "loading" | "ready" | "failed"; project: StudioProject; onChange: (mix: LoraMix) => void; onPlay: (control: DecodedAudioPlaybackControl) => void }) {
  const mix = editableMix(effectiveMix(character));
  const library = useMixLibrary();
  const { assets, runtime, error, loaded } = library;
  const audition = useLoraAudition({ character, mix, project, onPlay });
  const reason = auditionReason(character, mix, assets, loaded, runtime, referenceState);
  const names = ["ベース", ...mix.entries.map((entry) => assets.find((asset) => asset.id === entry.assetId)?.name ?? "未登録LoRA")];
  return (
    <section className="cast-lora-setting" aria-label="LoRA配合">
      <span className="type-field-label">LoRA配合</span>
      <LoraMixEditor value={mix} names={names} onChange={onChange} actions={<MixLibraryActions library={library} mix={mix} onChange={onChange} />} />
      <LoraAuditionBar audition={audition} reason={reason} />
      {(audition.error || error) && (
        <p role="alert" className="warning-text">
          {audition.error || error}
        </p>
      )}
    </section>
  );
}

function auditionReason(character: Character, mix: LoraMix, assets: LoraAsset[], loaded: boolean, runtime: LoraStatus | null, referenceState: "loading" | "ready" | "failed") {
  if (!character.referenceAudioUrl) return "参照音声がありません。";
  if (referenceState === "failed") return "参照音声が欠損しているか、読み込めません。WAVを指定し直してください。";
  if (referenceState === "loading") return "参照音声を確認中です。";
  if (!loaded) return "LoRAと音声エンジンを確認中です。";
  if (!runtime?.generationSupported) return runtime?.generationReason || "この音声エンジンでは試聴できません。";
  for (const entry of mix.entries.filter((item) => item.weight > 0)) {
    const asset = assets.find((item) => item.id === entry.assetId);
    if (!asset || asset.archived) return "配合中のLoRAが見つからないか削除済みです。登録を戻すか配合から外してください。";
    if (asset.adapterHash !== entry.adapterHash || asset.baseModelRepo !== entry.baseModelRepo || asset.baseModelRevision !== entry.baseModelRevision) return "保存したLoRAと登録が一致しません。配合から外して追加し直してください。";
  }
  return "";
}
