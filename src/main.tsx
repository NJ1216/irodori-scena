import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import { isWindows, preventWindowsWebViewShortcutDefault } from "./features/shared/platform";
import "./styles.css";
import { detectStartupTopology } from "./acceleratorTopology";
import { detectInstallationIdentity } from "./installationIdentity";

document.documentElement.dataset.platform = isWindows() ? "windows" : "macos";
window.addEventListener("keydown", preventWindowsWebViewShortcutDefault, true);

void Promise.all([detectStartupTopology(), detectInstallationIdentity()]).then(() => {
  createRoot(document.getElementById("root")!).render(
    <StrictMode>
      <App />
    </StrictMode>,
  );
});
