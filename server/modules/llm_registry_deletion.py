from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any
from server.app_deps import HTTPException, keyring
from server.registry import deps


def delete_llm_card_impl(card_id: str, runtime) -> dict[str, Any]:
    registry = runtime.read()
    card = next((item for item in registry["cards"] if item.get("id") == card_id), None)
    if card is None:
        raise HTTPException(status_code=404, detail="LLMモデルが見つかりません。")
    from server.modules.llm_runtime_binding import require_card_removable

    if card.get("source") in {"managed", "external"}:
        require_card_removable(card_id)
    source = card.get("source")
    mtp_supported = bool(deps.mtp_compatibility(card.get("localMetadata"))["supported"])
    mtp_deleted = False
    mtp_retained_reason = None
    if source == "managed":
        if mtp_supported and deps.mtp_download_active():
            raise HTTPException(
                status_code=409,
                detail="MTPダウンロード中です。カード内の「MTPダウンロードを取消」から停止後にモデルを削除してください。",
            )
        if deps.active_draft_job() or deps.active_export_job() or deps.llm_model_test_active(card_id):
            raise HTTPException(
                status_code=409,
                detail="実行中のLLM処理またはモデルテストを取消・完了してから管理モデルを削除してください。",
            )
        path_value = (card.get("localMetadata") or {}).get("path")
        if path_value:
            root = (deps.LOCAL_LLM_ROOT / "models").resolve()
            path = Path(str(path_value))
            try:
                canonical = path.resolve(strict=True)
                canonical.relative_to(root)
            except (OSError, ValueError) as error:
                raise HTTPException(status_code=422, detail="管理領域外のモデルファイルは削除できません。") from error
            if path.is_symlink() or canonical == root:
                raise HTTPException(status_code=422, detail="symlinkまたは管理領域自体は削除できません。")
            deps.unload_local_llm()
            shutil.rmtree(canonical)
            deps.rebuild_local_llm_discovery()
        if mtp_supported:
            reusable = [
                item
                for item in registry["cards"]
                if item.get("id") != card_id and deps.mtp_compatibility(item.get("localMetadata"))["supported"]
            ]
            if reusable:
                mtp_retained_reason = "同じMTP assistantを利用できる登録モデルが残っているため、MTP資産を保持しました。"
            else:
                had_asset = deps.mtp_asset_status()["diskBytes"] > 0
                deps.remove_mtp_asset()
                mtp_deleted = had_asset
    registry["cards"] = [item for item in registry["cards"] if item.get("id") != card_id]
    endpoint_id = card.get("endpointId")
    endpoint = next((item for item in registry["endpoints"] if item.get("id") == endpoint_id), None)
    remove_endpoint = bool(
        endpoint
        and endpoint.get("provider") != "scena-local"
        and not any(item.get("endpointId") == endpoint_id for item in registry["cards"])
    )
    if remove_endpoint:
        registry["endpoints"] = [item for item in registry["endpoints"] if item.get("id") != endpoint_id]
    if registry["defaultCardId"] == card_id:
        registry["defaultCardId"] = registry["cards"][0]["id"] if registry["cards"] else None
    runtime.write(registry)
    if remove_endpoint:
        try:
            keyring.delete_password(deps.KEYCHAIN_SERVICE, runtime.credential_account(str(endpoint_id)))
        except Exception:
            pass
    action = "deleted" if source == "managed" else "unregistered"
    return {
        "registry": runtime.public_registry(),
        "action": action,
        "source": source,
        "modelFilesDeleted": source == "managed",
        "mtpDeleted": mtp_deleted,
        "mtpRetainedReason": mtp_retained_reason,
    }
