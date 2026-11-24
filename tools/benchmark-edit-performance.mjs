import { performance } from "node:perf_hooks";

const sizes = [100, 1_000, 5_000];
const iterations = 240;

function fixture(lineCount, sceneCount = 5) {
  const linesPerScene = Math.ceil(lineCount / sceneCount);
  return {
    version: 1,
    revision: 7,
    id: `benchmark-${lineCount}`,
    title: "固定性能fixture",
    characters: [],
    candidates: [],
    settings: { speechRate: 1.2, steps: 16, textCfg: 3, voiceCfg: 5, seed: 1, quality: "fast", llmBaseUrl: "", llmModel: "" },
    scenes: Array.from({ length: sceneCount }, (_, sceneIndex) => ({
      id: `scene-${sceneIndex}`,
      title: `Scene ${sceneIndex}`,
      lines: Array.from({ length: Math.min(linesPerScene, lineCount - sceneIndex * linesPerScene) }, (_, localIndex) => {
        const index = sceneIndex * linesPerScene + localIndex;
        return {
          id: `line-${index}`,
          characterId: "cast-1",
          text: `固定発話 ${index}`,
          stageDirection: "静かに",
          pronunciations: [],
          takes: Array.from({ length: 8 }, (_, takeIndex) => ({ id: `take-${index}-${takeIndex}`, audioUrl: `/media/takes/${index}-${takeIndex}.wav`, seed: takeIndex, quality: "fast", stageDirection: "静かに", durationSeconds: 1.2, createdAt: takeIndex })),
          selectedTakeId: null,
        };
      }),
    })),
  };
}

function legacyInput(project, lineId, text) {
  const next = { ...project, scenes: project.scenes.map((scene) => ({ ...scene, lines: scene.lines.map((line) => (line.id === lineId ? { ...line, text } : line)) })) };
  // React consumers formerly walked the newly published scene tree.
  let checksum = 0;
  for (const scene of next.scenes) for (const line of scene.lines) checksum += line.text.length;
  return checksum;
}

function draftInput(drafts, lineId, text) {
  drafts.set(lineId, { ...(drafts.get(lineId) ?? {}), text });
  return text.length;
}

function percentile(values, fraction) {
  return [...values].sort((left, right) => left - right)[Math.floor((values.length - 1) * fraction)];
}

function measure(action) {
  const started = performance.now();
  action();
  return performance.now() - started;
}

console.log("lines\tlegacy-input-p95-ms\tdraft-input-p95-ms\timprovement\tput-bytes\tpatch-bytes\tpayload-reduction");
for (const lineCount of sizes) {
  const project = fixture(lineCount);
  const drafts = new Map();
  const legacy = [],
    draft = [];
  for (let index = 0; index < iterations; index += 1) {
    const text = `編集中 ${index}`;
    const pair = index % 2 ? [draft, legacy] : [legacy, draft];
    for (const samples of pair) samples.push(samples === legacy ? measure(() => legacyInput(project, "line-0", text)) : measure(() => draftInput(drafts, "line-0", text)));
  }
  const legacyP95 = percentile(legacy, 0.95),
    draftP95 = percentile(draft, 0.95);
  const putBytes = Buffer.byteLength(JSON.stringify({ project, baseRevision: project.revision }));
  const patchBytes = Buffer.byteLength(JSON.stringify({ baseRevision: project.revision, changes: { text: "確定した発話", pronunciations: [] } }));
  console.log(`${lineCount}\t${legacyP95.toFixed(4)}\t${draftP95.toFixed(4)}\t${((1 - draftP95 / legacyP95) * 100).toFixed(1)}%\t${putBytes}\t${patchBytes}\t${((1 - patchBytes / putBytes) * 100).toFixed(1)}%`);
}
