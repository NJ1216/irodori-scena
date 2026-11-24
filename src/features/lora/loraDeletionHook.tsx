// Keep TSX so the DEV transform records custom-hook signatures for Fast Refresh.
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { loraApi } from "../../api-lora";
import type { LoraAsset } from "../../types/lora";
import { cancelDestructiveConfirmation, confirmDestructiveAction, pendingDestructiveConfirmationKey, useDestructiveConfirmation } from "../shared/destructiveConfirmation";
import { useLoraDialogAction } from "./loraDialogActionHook";

type Props = { selected: LoraAsset | undefined; onDeleted: (asset: LoraAsset) => void };
const DELETE_DETAIL = "アプリ内のLoRAファイルと関連する学習済み重みを削除します。元の外部フォルダは変更しません。この操作は取り消せません。他の保存プロジェクトは未確認です。";
function targetKey(assetId: string) {
  return `lora-delete:${assetId}`;
}
export function useLoraDeletion({ selected, onDeleted }: Props) {
  const key = targetKey(selected?.id ?? "");
  const pending = useDestructiveConfirmation(key);
  const armedTarget = useRef<LoraAsset | null>(null);
  const running = useRef(false);
  const mounted = useRef(true);
  const currentKey = useRef(key);
  const [errorKey, setErrorKey] = useState("");
  const { busy, error, perform } = useLoraDialogAction();
  useLayoutEffect(() => {
    currentKey.current = key;
  }, [key]);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      armedTarget.current = null;
      if (pendingDestructiveConfirmationKey() === key) cancelDestructiveConfirmation();
    };
  }, [key]);
  function cancel() {
    armedTarget.current = null;
    if (pendingDestructiveConfirmationKey() === key) cancelDestructiveConfirmation();
  }
  async function removeTarget(target: LoraAsset) {
    const usage = await loraApi.adapterUsage(target.id);
    if (usage.takeCount > 0 || usage.casts.length > 0) throw new Error("ほかのキャストまたはテイクで使用中のため削除できません。");
    const asset = await loraApi.deleteAdapter(target.id);
    if (mounted.current && currentKey.current === targetKey(target.id)) onDeleted(asset);
  }
  async function requestDelete() {
    if (running.current || !selected) return;
    const prompt = `「${selected.name}」を削除しますか？`;
    if (!confirmDestructiveAction(key, () => {}, prompt, "削除", prompt, DELETE_DETAIL)) {
      armedTarget.current = selected;
      return;
    }
    const target = armedTarget.current;
    armedTarget.current = null;
    if (!target || targetKey(target.id) !== key) return;
    running.current = true;
    setErrorKey(key);
    try {
      await perform(() => removeTarget(target));
    } finally {
      running.current = false;
    }
  }
  return { key, pending, busy, error: errorKey === key ? error : "", requestDelete, cancel };
}
