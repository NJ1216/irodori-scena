import { useEffect, useState } from "react";
import { loraApi } from "../../api-lora";
import type { LoraAsset, LoraStatus } from "../../types/lora";
export function useMixLibrary() {
  const [assets, setAssets] = useState<LoraAsset[]>([]);
  const [runtime, setRuntime] = useState<LoraStatus | null>(null);
  const [error, setError] = useState("");
  const [loaded, setLoaded] = useState(false);
  const [selectedId, setSelectedId] = useState("");
  useEffect(() => {
    let active = true;
    void Promise.all([loraApi.adapters(true), loraApi.status()])
      .then(([next, status]) => {
        if (active) {
          setAssets(next);
          setRuntime(status);
          setLoaded(true);
        }
      })
      .catch((cause) => {
        if (active) setError(String(cause));
      });
    return () => {
      active = false;
    };
  }, []);
  const selected = assets.find((asset) => asset.id === selectedId);
  return { assets, runtime, error, loaded, selectedId, setSelectedId, selected };
}
