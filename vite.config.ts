import { defineConfig, type Plugin, type UserConfig } from "vite";
import react from "@vitejs/plugin-react";
import ports from "./tools/ports.json" with { type: "json" };

const apiTarget = process.env.SCENA_API_TARGET ?? `http://127.0.0.1:${ports.browser.api}`;

const apiPrefixes = ["/api", "/media", "/global-media"];
const tauriEntryMarker = "scena-tauri";
export const viteWatchIgnores = ["**/.git/**", "**/.venv/**", "**/.uv-cache/**", "**/node_modules/**", "**/artifacts/**", "**/scena-data/**", "**/userproject/**", "**/src-tauri/target/**", "**/src-tauri/binaries/**", "**/src-tauri/resources/environment-manager/**", "**/native/scena-native/target/**"];

export function isApiRequest(path: string) {
  return apiPrefixes.some((prefix) => path === prefix || path.startsWith(`${prefix}/`) || path.startsWith(`${prefix}?`));
}

export function isMarkedTauriEntry(path: string) {
  const url = new URL(path, "http://127.0.0.1");
  return (url.pathname === "/" || url.pathname === "/index.html") && url.searchParams.get(tauriEntryMarker) === "1";
}

function browserNotice() {
  return '<!doctype html><html lang="ja"><meta charset="UTF-8"><title>irodori SCENA</title>' + "<body><p>5175番はTauri開発画面専用です。ブラウザ開発には <code>pnpm dev</code>（5173番）を使用してください。</p></body></html>";
}

function tauriBrowserGuard(): Plugin {
  return {
    name: "scena-tauri-browser-guard",
    configureServer(server) {
      server.middlewares.use((request, response, next) => {
        if (request.method === "GET" && request.url && ["/", "/index.html"].includes(new URL(request.url, "http://127.0.0.1").pathname) && !isMarkedTauriEntry(request.url)) {
          response.statusCode = 200;
          response.setHeader("Content-Type", "text/html; charset=utf-8");
          response.end(browserNotice());
          return;
        }
        if (!request.url || !isApiRequest(request.url)) return next();
        response.statusCode = 503;
        response.setHeader("Content-Type", "application/json; charset=utf-8");
        response.end(
          JSON.stringify({
            detail: "5175番はTauri開発画面専用です。ブラウザ開発にはpnpm dev（5173番）を使用してください。",
          }),
        );
      });
    },
  };
}

export function scenaViteConfig(mode: string): UserConfig {
  const tauriDevelopment = mode === "tauri";
  return {
    plugins: [react(), ...(tauriDevelopment ? [tauriBrowserGuard()] : [])],
    server: {
      host: "127.0.0.1",
      port: ports.browser.vite,
      strictPort: true,
      watch: { ignored: viteWatchIgnores },
      proxy: tauriDevelopment
        ? undefined
        : {
            "/api": apiTarget,
            "/media": apiTarget,
            "/global-media": apiTarget,
          },
    },
  };
}

export default defineConfig(({ mode }) => scenaViteConfig(mode));
