from __future__ import annotations

from typing import Literal

from pydantic import model_validator

from server.app_deps import Field
from server.modules.request_model import StrictRequestModel
from server.registry import deps


class ExportStartRequest(StrictRequestModel):
    mode: Literal["prepare", "bundle"] = "prepare"
    destination_dir: str | None = Field(default=None, max_length=8000, alias="destinationDir")
    layout: Literal["split", "joined"] = "split"
    formats: list[Literal["wav", "subtitle_txt", "script_txt", "srt", "lab"]] = Field(default_factory=list)
    naming: list[Literal["sequence", "cast", "text", "none"]] = Field(default_factory=lambda: ["sequence", "cast", "text"], min_length=3, max_length=3)
    script_delimiter: str = Field(default="\t", min_length=1, max_length=1, alias="scriptDelimiter")
    quote_dialogue: bool = Field(default=False, alias="quoteDialogue")
    subtitle_include_emoji: bool = Field(default=False, alias="subtitleIncludeEmoji")
    model_config = {"populate_by_name": True}

    @model_validator(mode="after")
    def validate_bundle(self) -> "ExportStartRequest":
        if self.mode == "prepare":
            return self
        if not self.destination_dir:
            raise ValueError("エクスポート先フォルダを指定してください。")
        if not self.formats:
            raise ValueError("出力形式を1つ以上選択してください。")
        if self.layout == "split" and all(item == "none" for item in self.naming):
            raise ValueError("分割ファイルの命名要素を1つ以上指定してください。")
        if "lab" in self.formats and (self.layout != "split" or "wav" not in self.formats):
            raise ValueError("口パクLABは発話行ごとの分割WAVと一緒にエクスポートしてください。")
        if self.script_delimiter in {'\n', '\r', '"'}:
            raise ValueError("台本の区切り文字に改行またはダブルクォートは使えません。")
        if self.subtitle_include_emoji and not deps.DEVELOPMENT_MODE_ENABLED:
            raise ValueError("絵文字を含む字幕TXTは開発版でのみエクスポートできます。")
        return self


deps.register(__name__, ["ExportStartRequest"])
