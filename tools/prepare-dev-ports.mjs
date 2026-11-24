import { spawnSync } from "node:child_process";
import { createInterface } from "node:readline/promises";
import { stdin, stdout } from "node:process";
import ports from "./ports.json" with { type: "json" };

const PORTS = [ports.browser.vite, ports.browser.api];
const RELEASE_TIMEOUT_MS = 5_000;
const POLL_INTERVAL_MS = 100;

function listeningPids(port) {
  const result = spawnSync("lsof", ["-b", "-nP", `-iTCP:${port}`, "-sTCP:LISTEN", "-t"], {
    encoding: "utf8",
    timeout: 2_000,
  });

  if (result.error) {
    throw new Error(`lsof を実行できませんでした: ${result.error.message}`);
  }

  if (result.status !== 0 && result.status !== 1) {
    throw new Error(result.stderr.trim() || `lsof が終了コード ${result.status} で失敗しました。`);
  }

  return new Set(
    result.stdout
      .split("\n")
      .map((value) => Number.parseInt(value, 10))
      .filter(Number.isInteger),
  );
}

function occupiedPorts() {
  return PORTS.map((port) => ({ port, pids: listeningPids(port) })).filter(({ pids }) => pids.size > 0);
}

function describeOccupants(occupants) {
  for (const { port, pids } of occupants) {
    console.error(`${port} 番ポートを使用中の PID: ${[...pids].join(", ")}`);
  }
}

function sleep(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

async function askToStopExistingServers() {
  const terminal = createInterface({ input: stdin, output: stdout });
  try {
    const answer = await terminal.question("既存の開発サーバーを停止して起動しますか？ (y/N) ");
    return answer.trim().toLowerCase() === "y";
  } catch (error) {
    if (error?.code === "ABORT_ERR") {
      return false;
    }
    throw error;
  } finally {
    terminal.close();
  }
}

async function waitForPortsToBeReleased() {
  const deadline = Date.now() + RELEASE_TIMEOUT_MS;

  while (Date.now() < deadline) {
    if (occupiedPorts().length === 0) {
      return true;
    }
    await sleep(POLL_INTERVAL_MS);
  }

  return occupiedPorts().length === 0;
}

async function main() {
  let occupants;
  try {
    occupants = occupiedPorts();
  } catch (error) {
    console.error(`開発サーバーのポートを確認できませんでした: ${error.message}`);
    process.exitCode = 1;
    return;
  }

  if (occupants.length === 0) {
    return;
  }

  describeOccupants(occupants);

  if (!stdin.isTTY) {
    console.error("対話式端末ではないため、既存プロセスを停止せず起動を中止しました。");
    process.exitCode = 1;
    return;
  }

  if (!(await askToStopExistingServers())) {
    console.error("既存プロセスを停止しなかったため、開発サーバーの起動を中止しました。");
    process.exitCode = 1;
    return;
  }

  const pids = new Set(occupants.flatMap(({ pids }) => [...pids]));
  const stopFailures = [];
  for (const pid of pids) {
    try {
      process.kill(pid, "SIGTERM");
      console.error(`PID ${pid} に SIGTERM を送りました。`);
    } catch (error) {
      stopFailures.push(`PID ${pid}: ${error.message}`);
    }
  }
  if (stopFailures.length > 0) {
    console.error(`既存プロセスを停止できなかったため、起動を中止しました: ${stopFailures.join("; ")}`);
    process.exitCode = 1;
    return;
  }

  try {
    if (await waitForPortsToBeReleased()) {
      return;
    }
    console.error("既存プロセスの停止後もポートが解放されなかったため、起動を中止しました。");
    describeOccupants(occupiedPorts());
  } catch (error) {
    console.error(`ポートの解放を確認できなかったため、起動を中止しました: ${error.message}`);
  }

  process.exitCode = 1;
}

await main();
