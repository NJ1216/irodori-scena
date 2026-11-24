import { useEffect, useState } from "react";
import { DecodedAudioPlayer, type DecodedAudioPlaybackControl } from "../shared/decodedAudioPlayer";

export type { DecodedAudioPlaybackControl } from "../shared/decodedAudioPlayer";

function formatTime(seconds: number) {
  const rounded = Math.max(0, Math.floor(seconds));
  return `${Math.floor(rounded / 60)}:${String(rounded % 60).padStart(2, "0")}`;
}

export function AudioPlaybackBar({
  src,
  version,
  label,
  onPlay,
  onPause,
  onEnded,
  compact = false,
  compactLabel,
  selected = false,
  onActivate,
  onLoadState,
}: {
  src: string;
  version?: string | number;
  label: string;
  onPlay?: (audio: DecodedAudioPlaybackControl) => void;
  onPause?: (audio: DecodedAudioPlaybackControl) => void;
  onEnded?: (audio: DecodedAudioPlaybackControl) => void;
  compact?: boolean;
  compactLabel?: string;
  selected?: boolean;
  onActivate?: () => void;
  onLoadState?: (state: "loading" | "ready" | "failed") => void;
}) {
  const [playing, setPlaying] = useState(false);
  const [duration, setDuration] = useState(0);
  const [currentTime, setCurrentTime] = useState(0);
  const [player] = useState(
    () =>
      new DecodedAudioPlayer({
        onDuration: setDuration,
        onTime: setCurrentTime,
      }),
  );
  useEffect(() => {
    player.setCallbacks({
      onDuration: setDuration,
      onTime: setCurrentTime,
      onPlay: (control) => {
        setPlaying(true);
        onPlay?.(control);
      },
      onPause: (control) => {
        setPlaying(false);
        onPause?.(control);
      },
      onEnded: (control) => {
        setPlaying(false);
        onEnded?.(control);
      },
      onError: () => {
        setPlaying(false);
        onPause?.(player);
      },
    });
  }, [onEnded, onPause, onPlay, player]);
  const separator = src.includes("?") ? "&" : "?";
  const resolvedSrc = version === undefined ? src : `${src}${separator}v=${version}`;
  useEffect(() => {
    let active = true;
    if (!src) {
      onLoadState?.("failed");
      void player.setSource("");
      return;
    }
    onLoadState?.("loading");
    void player.setSource(resolvedSrc).then((ready) => {
      if (active) onLoadState?.(ready ? "ready" : "failed");
    });
    return () => {
      active = false;
    };
  }, [player, resolvedSrc, src, onLoadState]);
  useEffect(() => () => player.dispose(), [player]);
  const toggle = () => {
    onActivate?.();
    player.toggle();
  };
  return (
    <div
      className={`audio-playback-bar${compact ? " is-compact" : ""}${selected ? " is-selected" : ""}`}
      aria-label={label}
      onContextMenu={(event) => {
        if (!(event.target instanceof HTMLInputElement) || event.target.type !== "range") return;
        event.preventDefault();
        player.seek(0);
        setCurrentTime(0);
      }}
    >
      <button type="button" aria-label={playing ? `${label}を停止` : `${label}を再生`} onClick={toggle}>
        {compactLabel ?? (playing ? "■" : "▶")}
      </button>
      {!compact && (
        <>
          <output>
            {formatTime(currentTime)} / {formatTime(duration)}
          </output>
          <input
            aria-label={`${label}の再生位置`}
            type="range"
            min="0"
            max={duration || 0}
            step="0.01"
            value={Math.min(currentTime, duration || 0)}
            onChange={(event) => {
              player.seek(Number(event.currentTarget.value));
            }}
          />
        </>
      )}
    </div>
  );
}
