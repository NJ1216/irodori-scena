# ビルドとデータ管理

## 対応環境

Apple Silicon搭載のmacOSとWindows 11 x64を対象とします。この節はMac版のビルドについて説明します。Windows版は[Windowsネイティブ開発](windows-development.md)を参照してください。Node.js 24以降、pnpm 11、Rust安定版とXcode Command Line Toolsが必要です。uvは0.12.5、Pythonは3.13.12、PyInstallerは6.22.2に固定しています。Pythonのビルド用依存関係も `uv.lock` で固定します。ホストのuvが別バージョンの場合、ビルド手順が一時環境にuv 0.12.5を準備して使用するため、グローバルのuvを変更する必要はありません。初回取得には通信が必要です。

READMEの手順でビルドしてください。`pnpm tauri build` はネイティブ拡張、API sidecar、環境管理用uv、フロントエンドを用意してarm64アプリを作ります。oMLXは必要になった時点で管理環境へインストールします。`pnpm exec tauri build` の直接実行は必要なファイルを準備しないため使用しません。

## 保存と削除

Mac リリースビルドでは、アプリ同梱物の監査と現在版 DMG の検証に成功した後、中間生成物の `bundle/macos/irodori SCENA.app` を削除します。検証済み DMG は `irodori SCENA_VERSION_AppleSilicon.dmg` に改名して残します（例：`irodori SCENA_26.9.29_AppleSilicon.dmg`）。同名ファイルが既にある場合は上書きせず停止します。監査・DMG 検証に失敗した場合や中間アプリが実行中の場合は、調査と安全な再確認のため削除しません。

製品用の設定・管理モデル等は`~/Library/Application Support/irodori-SCENA/`に保存します。開発時のデータはリポジトリの `scena-data/` に分離します。プロジェクトは利用者が選んだ場所に保存し、音声テイクを含みます。

モデルは設定画面から削除できます。Windowsの通常アンインストールでは、アプリ本体だけを削除し、管理データを保持する選択が既定です。現在のユーザーの設定、内蔵プロジェクト、管理モデル、キャッシュ、ログ、SCENA資格情報も完全に削除する場合は、確認画面でその選択に切り替えます。任意の場所へ保存・書き出した`.scena`プロジェクトやWAV、外部モデルは削除しません。macOSでは従来どおり、必要なプロジェクトをバックアップし、設定画面で認証情報を削除してからアプリを削除してください。

## 外部接続と制約

モデル・環境の初回取得にはネットワークが必要です。外部LLMを利用する機能は設定したサービスへ入力情報を送信し、そのサービスの料金・利用条件が適用されます。ローカルLLMを選ぶ場合もモデルの初回取得は別途必要です。

ベータ版では、OS・メモリ容量・モデルの組合せによって推論が利用できない場合があります。モデルの品質や対応機能は個別に異なります。重要なプロジェクトはバックアップして使用してください。

## 開発と検証

```bash
pnpm validate
```

明示的に全体検証を行うときの、手動CIと共通のコマンドです。通常の修正では対象ファイルを指定して関連テストだけを実行します。GitHub Actionsの検証は手動実行専用で、push・PRでは起動しません。`v`で始まるタグを公開したときだけ、Windows用インストーラーを作って下書きのリリースに添付する処理が動きます。PlaywrightのChromiumが必要です（`pnpm exec playwright install chromium`）。ビルドは既存の開発アプリと別checkoutで行ってください。

ブラウザ開発は `pnpm dev`、デスクトップ開発は `pnpm tauri dev` です。既に開発アプリが動いている場合は再起動せず、まず `pnpm verify:dev-app` で確認します。開発アプリの識別子は `com.irodori-scena.dev`、ウィンドウ名は `irodori SCENA [DEV]` です。
開発用ポートは、ブラウザがVite 5173／API 8787、PlaywrightがVite 5174／API 8788、TauriがVite 5175／APIは動的割当です。互いのサーバーを再利用しません。

## 公開準備コマンド

このリポジトリは、作者の開発リポジトリから公開対象のファイルだけを書き出したスナップショットです。開発履歴や内部資料は含みません。公開前の確認には次のコマンドを使います。

- `pnpm release:version`：公開メタデータから各言語のバージョンを同期。
- `pnpm release:licenses`：ロック済み依存のライセンス一覧・本文を生成。
- `pnpm release:check`：バージョンと生成物の入力・本文ハッシュを確認。
- `pnpm release:audit`：許可リストのファイルだけを個人情報検査。
## Rhubarb口パクLABアドオン

RhubarbはSCENA本体へ同梱せず、GitHub Releaseから任意取得するアドオンです。macOS arm64版とWindows x64版は、実行ファイル、`phonetic` recognizerに必要な`res/sphinx`、ライセンス、`BUILD-INFO.json`だけを含む最小アーカイブとして作成します。

固定したRhubarb v1.14.0ソースをApple Silicon向けにビルドした後、または公式Windows x64配布物を展開した後、次のように決定的なアーカイブとカタログ用JSONを生成します。

```sh
uv run python tools/release/package_rhubarb.py --root <distribution-root> --platform darwin-arm64 --commit 9b9573cd21b253c9ba58739bbd1aa0b50b991bff --output <outside-repository>/rhubarb-1.14.0-scena.1-macos-arm64.zip
```

成果物はGitへ追加しません。公開用SCENAリポジトリの手動Releaseへ両OS版をアップロードし、公開された資産とSHA-256が一致してから`server/catalogs/rhubarb-runtime.json`の`available`を有効にします。
