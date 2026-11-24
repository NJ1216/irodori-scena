# Windowsネイティブ開発

Windows版はWindows PC上のローカルcheckoutで直接開発・検証します。資格情報、モデル、runtime、ビルド成果物をGitへ追加しないでください。

WindowsのLLMはOllama、LM Studio、OpenAI互換の外部接続に加え、SCENAが管理するllama.cppとGGUFモデルを利用できます。macOS用のoMLX/MLXモデルとの相互読込みや移行は行いません。

## 開発環境

必要な構成はNode.js 24、pnpm 11、Rust MSVC stable、Visual Studio 2022 C++ Build Tools、Windows 11 SDK、uv、Python 3.13、Git for Windowsです。TTSの音声読込みにはFFmpeg共有DLLも必要です。

環境を新規構築する場合、`tools/windows-dev/setup-toolchain.ps1` を引数なしで実行すると導入計画だけを表示します。内容を確認したうえで、管理者PowerShellから `-Apply` を明示した場合に限って開発ツールを導入します。ドライバー、CUDA Toolkit、モデル、アプリの依存関係はこのスクリプトの対象外です。

checkout内では次を実行します。

```powershell
pnpm.cmd install --frozen-lockfile
uv sync --frozen
pnpm.cmd build:native
pnpm.cmd tauri dev
```

## DEVアプリの確認

準備済みcheckoutでは `Start-SCENA-DEV.cmd` をダブルクリックできます。既に同じcheckoutの開発版が動いていれば、そのプロセスを検証して再利用します。起動用コンソールはViteとAPIを監督するため、検証中は閉じないでください。

ユーザーへ画面確認を依頼する前に、同じWindowsデスクトップで次を実行します。

```powershell
pnpm.cmd verify:dev-app
```

成功条件は開発設定ID `com.irodori-scena.dev`、タイトル `irodori SCENA [DEV]`、可視ウィンドウ、Vite応答、アプリ所有API listenerに加え、ウィンドウがPer-Monitor V2 DPI awareであることです。結果には `GetDpiForWindow` のDPIと96 DPIを基準にしたscale factorも表示します。production版や別checkoutを代用しません。

高DPIディスプレイは、Windowsの「ディスプレイの解像度」でパネルの物理解像度（6Kパネルなら6K）を選び、UIの大きさは「拡大/縮小」の125%、150%、200%などで調整してください。3K信号をディスプレイ側またはWindows側で6Kへ最終拡大する構成のぼやけは、SCENAから補正できません。

## SCENA内蔵LLM

設定画面で実行基盤のCUDAまたはCPUを選び、固定版llama.cppを取得してからGGUFモデルを追加します。CUDA起動失敗時にCPU版は自動取得されません。CPUへ切り替える場合は利用者が明示的に選択します。

Hugging Faceから取得する場合はrepositoryを選んだ後、量子化、容量、分割数を確認してvariantを1つ選択します。PC内から選ぶ場合、元GGUFは移動・複製されないため、登録後も同じ場所に保持してください。

## Windows TTS

NVIDIA GPUでは固定環境のCUDA backendを使用し、CUDAデバイスがなければCPUを選びます。CPU実行時はPyTorchのスレッド数を物理コア数（`psutil.cpu_count(logical=False)`）に制限します。論理コア数の既定値より速く、出力は16bitの丸め誤差の範囲で同一です。モデルとCodecの精度やsampling条件はmacOS向け設定から暗黙に変更しません。FFmpeg共有DLLは別途導入し、PATHまたは `SCENA_FFMPEG_DIR` から解決します。

## Windows 11 x64 ローカル検証ビルド

Windows 11 x64では、最新版をfast-forwardで取り込んだ後に`pnpm.cmd tauri build`を1回実行すると、未署名のNSISインストーラーを作成できます。PowerShellでは実行ポリシーによる`pnpm.ps1`の拒否を避けるため、Windowsの手順では`pnpm.cmd`を使用します。コマンドは環境を先に検査し、前回のWindows生成物だけを削除してから各工程を実行します。成果物は`src-tauri/target/x86_64-pc-windows-msvc/release/bundle/nsis/`の現在バージョンに対応する`*-setup.exe` 1本です。同じコマンドを続けて実行しても前回版は残りません。生成途中のアプリ本体`.exe`をポータブル版として配布しません。MSI、MSIX、ARM64、自動更新は対象外です。

macOS側では`pnpm check:windows-build`が、Windows向けコマンド、NSIS設定、バージョン同期、sidecar同梱対象、GUI subsystem設定、古い成果物の整理契約を検査します。MSVC、PyInstaller、NSIS自体の成功はWindows実機で最終確認します。Windows固有の新しい障害を修正した場合は、同じ原因の契約テストまたはWindows専用テストを同じコミットへ追加します。

インストール時に「すべてのユーザー」（`C:\Program Files\irodori SCENA`）または「現在のユーザーのみ」（`%LOCALAPPDATA%\Programs\irodori SCENA`）を選択できます。初回は「すべてのユーザー」が既定で、以後は前回の方式を引き継ぎます。Tauriの`both`モードにより、登録先は選択に応じてHKLMまたはHKCUになります。インストール、更新、アンインストールでは必要に応じてUACが表示されますが、通常のアプリ起動は昇格を要求しません。

どちらの配置方式でもProgram FilesまたはPrograms配下に置くのは実行資材だけです。設定、LLM/TTSモデル、管理runtime、キャッシュは起動ユーザーの既存AppData領域に、API資格情報はWindows Credential Managerに保存され、複数ユーザー間で共有されません。通常のアンインストールでは、アプリ本体だけを削除して管理データを保持する選択が既定です。アプリ本体と現在のユーザーのSCENA管理データを完全に削除する場合は、確認画面でその選択に切り替えます。上書き更新と旧current-user版からの移行では確認を表示せず、管理データを保持します。任意の場所へ保存した`.scena`プロジェクト、外部音声、外部モデル、および開発版データは削除しません。

この成果物にはコード署名がないため、Windowsが未署名アプリの警告（SmartScreen）を表示する場合があります。GitHub Releasesで配布するインストーラーも同じく未署名です。
