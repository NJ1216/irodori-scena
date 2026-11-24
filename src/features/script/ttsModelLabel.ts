const modelLabels: Record<string, string> = {
  "2e0c55428ce97268a507f1feeb2478f8d9148e8b": "v4 Large",
  "2b28324dc263ed5e6638b3cf3dd94c82ead07b4b": "v4.1 Small",
  ccc78f5d480b6e51b69b2d5042a14c4da04fea6e: "v4.1 Small MF",
  "4c92c7ee2bb15c19a97cf4e86d24fd6bf33b0135": "v4 Small",
  e863a3a93e652e09afeff3e84823a206a0a60314: "v3 VoiceDesign",
  "236c1e56591279fc24e3c1bf6609fc06e48dde28": "v3 Base",
};

export function ttsModelLabel(revision?: string | null) {
  if (!revision) return null;
  return modelLabels[revision] ?? `revision ${revision.slice(0, 8)}`;
}
