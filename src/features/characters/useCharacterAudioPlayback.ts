import { useEffect, useRef, useState } from "react";
import { api } from "../../api";
import { apiFetch } from "../../api-runtime";
import type { Character } from "../../types";
import { audioEngine } from "../shared/audioEngine";
import type { DecodedAudioPlaybackControl } from "../shared/decodedAudioPlayer";

export function useCharacterAudioPlayback() {
  const activeCandidateAudio = useRef<DecodedAudioPlaybackControl | null>(null);
  const activeReferenceAudio = useRef<DecodedAudioPlaybackControl | null>(null);
  const activeReferenceSource = useRef<AudioBufferSourceNode | null>(null);
  const activeReferenceCharacterId = useRef<string | null>(null);
  const referencePlaybackToken = useRef(0);
  const [playingReferenceCharacterId, setPlayingReferenceCharacterId] = useState<string | null>(null);
  function beginCandidatePlayback(audio: DecodedAudioPlaybackControl) {
    if (activeCandidateAudio.current && activeCandidateAudio.current !== audio) {
      activeCandidateAudio.current.stop();
    }
    activeCandidateAudio.current = audio;
  }
  function endCandidatePlayback(audio: DecodedAudioPlaybackControl) {
    if (activeCandidateAudio.current === audio) activeCandidateAudio.current = null;
  }
  function beginReferencePlayback(audio: DecodedAudioPlaybackControl) {
    stopDecodedReferencePlayback();
    const previous = activeReferenceAudio.current;
    if (previous && previous !== audio) {
      previous.stop();
    }
    activeReferenceAudio.current = audio;
  }
  function endReferencePlayback(audio: DecodedAudioPlaybackControl) {
    if (activeReferenceAudio.current !== audio) return;
    activeReferenceAudio.current = null;
    activeReferenceCharacterId.current = null;
    setPlayingReferenceCharacterId(null);
  }
  function stopDecodedReferencePlayback() {
    referencePlaybackToken.current += 1;
    const source = activeReferenceSource.current;
    if (source) {
      activeReferenceSource.current = null;
      source.onended = null;
      try {
        source.stop();
      } catch {
        /* already ended */
      }
      audioEngine.setBufferPlaybackActive(false);
    }
    activeReferenceCharacterId.current = null;
    setPlayingReferenceCharacterId(null);
  }
  async function playReferenceAudio(character: Character) {
    if (activeReferenceCharacterId.current === character.id) {
      stopDecodedReferencePlayback();
      return;
    }
    activeReferenceAudio.current?.stop();
    stopDecodedReferencePlayback();
    const token = referencePlaybackToken.current;
    const separator = character.referenceAudioUrl.includes("?") ? "&" : "?";
    const url = `${character.referenceAudioUrl}${separator}v=${character.referenceVersion ?? 0}`;
    activeReferenceCharacterId.current = character.id;
    setPlayingReferenceCharacterId(character.id);
    try {
      // Fetch and decode before creating the source: the shared engine retires an idle output on the next
      // task, so a source prepared before a network wait would belong to a closed context.
      const response = await apiFetch(url, { cache: "force-cache" });
      if (!response.ok) throw new Error(`参照音声を読み込めませんでした (${response.status})`);
      const { buffer } = await audioEngine.decodeAudioData(await response.arrayBuffer());
      if (referencePlaybackToken.current !== token || activeReferenceCharacterId.current !== character.id) return;
      const { context, source } = await audioEngine.createBufferSource();
      if (referencePlaybackToken.current !== token || activeReferenceCharacterId.current !== character.id) return;
      source.buffer = buffer;
      activeReferenceSource.current = source;
      source.onended = () => {
        if (activeReferenceSource.current !== source) return;
        activeReferenceSource.current = null;
        activeReferenceCharacterId.current = null;
        setPlayingReferenceCharacterId(null);
        audioEngine.setBufferPlaybackActive(false);
      };
      audioEngine.setBufferPlaybackActive(true);
      source.start(context.currentTime + 0.02, 0);
    } catch {
      if (referencePlaybackToken.current === token) stopDecodedReferencePlayback();
    }
  }
  useEffect(
    () => () => {
      activeCandidateAudio.current?.stop();
      activeCandidateAudio.current = null;
      activeReferenceAudio.current?.stop();
      activeReferenceAudio.current = null;
      stopDecodedReferencePlayback();
      void api.clearCandidates().catch(() => undefined);
    },
    [],
  );
  return { activeCandidateAudio, activeReferenceAudio, playingReferenceCharacterId, beginCandidatePlayback, endCandidatePlayback, beginReferencePlayback, endReferencePlayback, playReferenceAudio };
}
