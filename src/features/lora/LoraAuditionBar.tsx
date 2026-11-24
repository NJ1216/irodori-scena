import type { useLoraAudition } from "./useLoraAudition";
const time = (seconds: number) => `${Math.floor(seconds / 60)}:${String(Math.floor(seconds % 60)).padStart(2, "0")}`;
export function LoraAuditionBar({ audition, reason }: { audition: ReturnType<typeof useLoraAudition>; reason: string }) {
  return (
    <div>
      <span className="type-field-label">LoRA合成サンプル試聴</span>
      <div className="audio-playback-bar" aria-label="LoRA合成サンプル試聴">
        <button type="button" aria-label={audition.generating ? "試聴生成をキャンセル" : audition.playing ? "LoRA合成サンプルを停止" : "この配合で試聴"} disabled={Boolean(reason) && !audition.generating} title={reason || "この配合で試聴"} onClick={() => void audition.toggle()}>
          {audition.generating ? "×" : audition.playing ? "■" : "▶"}
        </button>
        <output>{audition.generating ? "生成中…" : `${time(audition.currentTime ?? 0)} / ${time(audition.duration ?? 0)}`}</output>
        <input aria-label="LoRA合成サンプルの再生位置" type="range" min="0" max={audition.duration || 0} step="0.01" value={Math.min(audition.currentTime || 0, audition.duration || 0)} disabled={!audition.duration || audition.generating} onChange={(event) => audition.seek(Number(event.currentTarget.value))} />
      </div>
    </div>
  );
}
