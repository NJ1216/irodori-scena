import { useEffect, useRef, useState } from "react";
import { DecodedAudioPlayer } from "../shared/decodedAudioPlayer";
import type { LoraInputRow } from "../../types/lora";

/** One lazy player avoids fetching/decoding every recording in large folders. */
export function useLoraInputPlayback() {
  const [activeId, setActiveId] = useState("");
  const [playing, setPlaying] = useState(false);
  const [error, setError] = useState("");
  const request = useRef(0);
  const [player] = useState(() => new DecodedAudioPlayer());
  useEffect(() => {
    player.setCallbacks({
      onPlay: () => setPlaying(true),
      onPause: () => setPlaying(false),
      onEnded: () => {
        setPlaying(false);
        setActiveId("");
      },
      onError: () => {
        setPlaying(false);
        setActiveId("");
        setError("音声を再生できませんでした。素材を取り込み直してください。");
      },
    });
    return () => {
      request.current += 1;
      player.dispose();
    };
  }, [player]);
  async function toggle(row: LoraInputRow) {
    if (!row.audioUrl) return;
    const next = ++request.current;
    player.stop();
    setPlaying(false);
    setError("");
    if (activeId === row.id) {
      setActiveId("");
      return;
    }
    setActiveId(row.id);
    if ((await player.setSource(row.audioUrl)) && request.current === next) await player.play();
  }
  return { activeId, playing, error, toggle };
}
