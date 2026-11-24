import type { Character } from "../../types";

export type ImportedScriptLine = { speaker: string | null; text: string };

const normalize = (value: string) => value.replaceAll(/\s/g, "").toLocaleLowerCase("ja-JP");
const quotedSpeakerName = /^[^「」『』。．.!?！？…、，]+$/;

function parseLine(line: string): ImportedScriptLine | null {
  const trimmed = line.trim();
  if (!trimmed) return null;
  const delimiter = trimmed.match(/^([^|｜:：;；,，「『]+?)\s*[|｜:：;；,，]\s*(.+)$/);
  if (delimiter?.[1].trim() && delimiter[2].trim()) {
    return { speaker: delimiter[1].trim(), text: delimiter[2].trim() };
  }
  const quoted = trimmed.match(/^(.+?)\s*「(.*)」\s*$/) ?? trimmed.match(/^(.+?)\s*『(.*)』\s*$/);
  if (quoted?.[1].trim() && quotedSpeakerName.test(quoted[1].trim()) && quoted[2].trim()) {
    return { speaker: quoted[1].trim(), text: quoted[2].trim() };
  }
  return { speaker: null, text: trimmed };
}

export function parseScriptImport(text: string): ImportedScriptLine[] {
  let previousSpeaker: string | null = null;
  return text.split(/\r?\n/).flatMap((line) => {
    const parsed = parseLine(line);
    if (!parsed) return [];
    if (parsed.speaker) previousSpeaker = parsed.speaker;
    return [{ ...parsed, speaker: parsed.speaker ?? previousSpeaker }];
  });
}

function characterNames(character: Character): string[] {
  const details = character.profileDetails;
  return [character.name, details?.familyName ?? "", details?.givenName ?? "", ...(details?.aliases ?? [])].map(normalize).filter(Boolean);
}

export function matchedCharacterId(speaker: string, characters: Character[]) {
  const key = normalize(speaker);
  const matches = characters.filter((character) => characterNames(character).some((name) => name === key || name.includes(key) || key.includes(name)));
  return matches.length === 1 ? matches[0].id : "";
}
