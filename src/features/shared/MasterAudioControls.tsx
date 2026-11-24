import { useEffect, useRef, useState, type CSSProperties } from "react";
import { audioEngine, MASTER_MAX_DB, MASTER_MIN_DB, type MasterVolumeDb, type StereoLevel } from "./audioEngine";
import { adjustMasterVolume, formatMasterVolume, masterVolumeAngle, stepMasterVolume } from "./masterVolumeScale";

const emptyLevel: StereoLevel = { left: -60, right: -60, leftSamplePeak: -60, rightSamplePeak: -60, leftPeak: -60, rightPeak: -60, active: false };
const METER_RANGE_DB = MASTER_MAX_DB - MASTER_MIN_DB;
const meterPercent = (value: number) => `${((Math.max(MASTER_MIN_DB, Math.min(MASTER_MAX_DB, value)) - MASTER_MIN_DB) / METER_RANGE_DB) * 100}%`;
const zeroPercent = meterPercent(0);

function StereoMeter({ level }: { level: StereoLevel }) {
  return (
    <div className={`master-stereo-meter${level.active ? " is-active" : ""}`} aria-label="マスター L/R レベル">
      <span className="master-meter-box">
        {(["L", "R"] as const).map((label, index) => {
          const value = index ? level.right : level.left;
          const peak = index ? level.rightPeak : level.leftPeak;
          return (
            <span className="master-meter-track" key={label} role="meter" aria-label={`${label}チャンネル`} aria-valuemin={MASTER_MIN_DB} aria-valuemax={MASTER_MAX_DB} aria-valuenow={Math.round(value)}>
              <i style={{ width: meterPercent(Math.min(0, value)) }} />
              <em className={peak > 0 ? "is-clipping" : ""} style={{ left: zeroPercent }} />
              <b className={peak > 0 ? "is-clipped" : ""} style={{ left: meterPercent(peak) }} />
            </span>
          );
        })}
      </span>
    </div>
  );
}

function VolumeKnob({ value, onChange }: { value: MasterVolumeDb; onChange: (value: MasterVolumeDb) => void }) {
  const knob = useRef<HTMLButtonElement>(null);
  const dragging = useRef<{ pointerId: number; y: number; value: MasterVolumeDb } | null>(null);
  const current = useRef({ value, onChange });
  useEffect(() => {
    current.current = { value, onChange };
  }, [value, onChange]);
  const finite = value ?? MASTER_MIN_DB;
  const angle = masterVolumeAngle(value);
  const step = (direction: -1 | 1) => onChange(stepMasterVolume(value, direction));
  useEffect(() => {
    const target = knob.current;
    if (!target) return;
    const wheel = (event: WheelEvent) => {
      if (event.deltaY === 0) return;
      event.preventDefault();
      const next = stepMasterVolume(current.current.value, event.deltaY < 0 ? 1 : -1);
      current.current.value = next;
      current.current.onChange(next);
    };
    target.addEventListener("wheel", wheel, { passive: false });
    return () => target.removeEventListener("wheel", wheel);
  }, []);
  return (
    <div className="master-volume-control">
      <button
        type="button"
        ref={knob}
        role="slider"
        className="master-volume-knob"
        aria-label="マスターボリューム"
        aria-valuemin={MASTER_MIN_DB}
        aria-valuemax={MASTER_MAX_DB}
        aria-valuenow={finite}
        aria-valuetext={formatMasterVolume(value)}
        style={{ "--master-knob-angle": `${angle}deg` } as CSSProperties}
        onPointerDown={(event) => {
          if (event.button !== 0) return;
          event.currentTarget.setPointerCapture(event.pointerId);
          dragging.current = { pointerId: event.pointerId, y: event.clientY, value };
        }}
        onPointerMove={(event) => {
          if (!dragging.current || dragging.current.pointerId !== event.pointerId) return;
          if (!(event.buttons & 1)) {
            dragging.current = null;
            return;
          }
          onChange(adjustMasterVolume(dragging.current.value, Math.round((dragging.current.y - event.clientY) / 2)));
        }}
        onPointerUp={(event) => {
          if (dragging.current?.pointerId === event.pointerId) dragging.current = null;
        }}
        onPointerCancel={(event) => {
          if (dragging.current?.pointerId === event.pointerId) dragging.current = null;
        }}
        onLostPointerCapture={(event) => {
          if (dragging.current?.pointerId === event.pointerId) dragging.current = null;
        }}
        onKeyDown={(event) => {
          if (["ArrowUp", "ArrowRight", "ArrowDown", "ArrowLeft", "Home", "End"].includes(event.key)) event.preventDefault();
          if (event.key === "ArrowUp" || event.key === "ArrowRight") step(1);
          if (event.key === "ArrowDown" || event.key === "ArrowLeft") step(-1);
          if (event.key === "Home") onChange(null);
          if (event.key === "End") onChange(MASTER_MAX_DB);
        }}
        onContextMenu={(event) => {
          event.preventDefault();
          onChange(0);
        }}
      >
        <i aria-hidden="true" />
      </button>
      <output aria-live="polite">{formatMasterVolume(value)}</output>
    </div>
  );
}

export function MasterAudioControls() {
  const [volume, setVolume] = useState(audioEngine.getVolume());
  const [level, setLevel] = useState(emptyLevel);
  useEffect(() => audioEngine.subscribeVolume(setVolume), []);
  useEffect(() => audioEngine.subscribeLevels(setLevel), []);
  return (
    <section className="master-audio-controls" aria-label="マスター音声">
      <StereoMeter level={level} />
      <VolumeKnob value={volume} onChange={(next) => audioEngine.setVolume(next)} />
    </section>
  );
}
