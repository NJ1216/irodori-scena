const simultaneousRequest = /(?:同時|動時)\s*発話|同時に|一斉に|声(?:を|が)?\s*(?:重ね|重な)/u;
const simultaneousNegation = /(?:同時|動時)\s*発話.{0,8}(?:なし|不要|禁止|しない|避け)/u;

export function explicitlyRequestsSimultaneousSpeech(instruction: string) {
  return simultaneousRequest.test(instruction) && !simultaneousNegation.test(instruction);
}

export function minimumLinesForSimultaneousSpeech(instruction: string) {
  return /掛け声|合図|きっかけ/u.test(instruction) ? 3 : 2;
}
