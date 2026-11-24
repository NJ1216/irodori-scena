mod accelerator_topology;
#[cfg(not(windows))]
mod api_supervisor;
#[cfg(windows)]
#[path = "api_supervisor_windows.rs"]
mod api_supervisor;
mod open_files;

use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Condvar, Mutex};
use std::{fs::OpenOptions, io::Write};

use api_supervisor::ApiProcess;
use serde::Serialize;
use tauri::Manager;

enum ApiStartup {
    Starting,
    Ready(ApiProcess),
    Failed(String),
    Stopping,
}

struct ApiProcessShared {
    phase: Mutex<ApiStartup>,
    changed: Condvar,
    cancelled: AtomicBool,
}

#[derive(Clone)]
struct ApiProcessState(Arc<ApiProcessShared>);

impl ApiProcessState {
    fn new() -> Self {
        Self(Arc::new(ApiProcessShared {
            phase: Mutex::new(ApiStartup::Starting),
            changed: Condvar::new(),
            cancelled: AtomicBool::new(false),
        }))
    }

    fn finish_startup(&self, result: Result<ApiProcess, api_supervisor::SupervisorError>) {
        let mut phase = self
            .0
            .phase
            .lock()
            .expect("API process state lock poisoned");
        if self.0.cancelled.load(Ordering::Acquire) {
            if let Ok(mut process) = result {
                let _ = process.stop();
            }
            *phase = ApiStartup::Stopping;
        } else {
            *phase = match result {
                Ok(process) => ApiStartup::Ready(process),
                Err(error) => ApiStartup::Failed(error.to_string()),
            };
        }
        self.0.changed.notify_all();
    }

    fn connection(&self) -> Result<ApiConnection, String> {
        let mut phase = self
            .0
            .phase
            .lock()
            .map_err(|_| "API process state lock poisoned".to_owned())?;
        loop {
            match &*phase {
                ApiStartup::Starting => {
                    phase = self
                        .0
                        .changed
                        .wait(phase)
                        .map_err(|_| "API process state lock poisoned".to_owned())?;
                }
                ApiStartup::Ready(process) => {
                    return Ok(ApiConnection {
                        base_url: process.base_url(),
                        token: process.token().to_owned(),
                    });
                }
                ApiStartup::Failed(error) => {
                    return Err(format!("ローカルAPIを起動できませんでした: {error}"))
                }
                ApiStartup::Stopping => return Err("ローカルAPIを終了しています。".to_owned()),
            }
        }
    }

    fn stop(&self) {
        self.0.cancelled.store(true, Ordering::Release);
        let mut phase = self
            .0
            .phase
            .lock()
            .expect("API process state lock poisoned");
        if let ApiStartup::Ready(process) = &mut *phase {
            if let Err(error) = process.stop() {
                eprintln!("Failed to stop local FastAPI process: {error}");
            }
        }
        *phase = ApiStartup::Stopping;
        self.0.changed.notify_all();
    }
}

const RELEASE_DATA_DIRECTORY: &str = "irodori-SCENA";

fn release_data_root(default_app_data_root: PathBuf) -> PathBuf {
    // Keep user data independent from the bundle identifier. Tauri's default
    // path ends in that identifier, while its parent is Application Support.
    default_app_data_root.with_file_name(RELEASE_DATA_DIRECTORY)
}

fn sidecar_path(app: &tauri::App) -> Result<PathBuf, tauri::Error> {
    let resources = app.path().resource_dir()?;
    Ok(resources.join("scena-api-runtime").join(if cfg!(windows) {
        "scena-api.exe"
    } else {
        "scena-api"
    }))
}

fn omlx_bootstrap_paths(app: &tauri::App) -> Result<(PathBuf, PathBuf, PathBuf), tauri::Error> {
    let resources = app.path().resource_dir()?;
    Ok((
        resources
            .join("environment-manager")
            .join(if cfg!(windows) { "uv.exe" } else { "uv" }),
        resources.join("omlx-bootstrap").join("omlx-sidecar.py"),
        resources.join("omlx-bootstrap").join("requirements.txt"),
    ))
}

fn stop_api(app: &tauri::AppHandle) {
    app.state::<ApiProcessState>().stop();
}

fn focus_main_window(app: &tauri::AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.show();
        let _ = window.unminimize();
        let _ = window.set_focus();
    }
}

#[tauri::command]
async fn api_connection(state: tauri::State<'_, ApiProcessState>) -> Result<ApiConnection, String> {
    let state = state.inner().clone();
    tauri::async_runtime::spawn_blocking(move || state.connection())
        .await
        .map_err(|error| error.to_string())?
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct ApiConnection {
    base_url: String,
    token: String,
}

#[tauri::command]
fn accelerator_topology(
    state: tauri::State<'_, accelerator_topology::AcceleratorTopology>,
) -> accelerator_topology::AcceleratorTopology {
    state.inner().clone()
}

#[tauri::command]
fn installation_identity() -> Option<String> {
    #[cfg(windows)]
    {
        return std::env::current_exe()
            .ok()
            .and_then(|path| path.parent().map(|parent| parent.join(".scena-install-id")))
            .and_then(|path| std::fs::read_to_string(path).ok())
            .map(|value| value.trim().to_owned())
            .filter(|value| !value.is_empty());
    }
    #[cfg(not(windows))]
    None
}

async fn stream_response(url: &str, token: &str, destination: &PathBuf) -> Result<(), String> {
    let parsed = reqwest::Url::parse(url).map_err(|error| error.to_string())?;
    if parsed.scheme() != "http" || !matches!(parsed.host_str(), Some("127.0.0.1" | "localhost")) {
        return Err("保存元URLが正しくありません。".to_owned());
    }
    let partial = destination.with_extension(format!(
        "{}partial",
        destination
            .extension()
            .and_then(|value| value.to_str())
            .map(|value| format!("{value}."))
            .unwrap_or_default()
    ));
    let result = async {
        let client = reqwest::Client::new();
        let mut response = client
            .get(parsed)
            .bearer_auth(token)
            .send()
            .await
            .map_err(|error| error.to_string())?
            .error_for_status()
            .map_err(|error| error.to_string())?;
        let mut output = std::fs::File::create(&partial).map_err(|error| error.to_string())?;
        while let Some(chunk) = response.chunk().await.map_err(|error| error.to_string())? {
            output
                .write_all(&chunk)
                .map_err(|error| error.to_string())?;
        }
        output.sync_all().map_err(|error| error.to_string())?;
        std::fs::rename(&partial, destination).map_err(|error| error.to_string())
    }
    .await;
    if result.is_err() {
        let _ = std::fs::remove_file(partial);
    }
    result
}

fn download_file_name(file_name: &str, copy: usize) -> Result<String, String> {
    let supplied = PathBuf::from(file_name);
    if supplied.file_name().and_then(|value| value.to_str()) != Some(file_name)
        || supplied
            .extension()
            .and_then(|value| value.to_str())
            .map(str::to_ascii_lowercase)
            != Some("wav".to_owned())
    {
        return Err("保存ファイル名が正しくありません。".to_owned());
    }
    if copy == 1 {
        return Ok(file_name.to_owned());
    }
    let stem = supplied
        .file_stem()
        .and_then(|value| value.to_str())
        .ok_or_else(|| "保存ファイル名が正しくありません。".to_owned())?;
    Ok(format!("{stem} ({copy}).wav"))
}

#[tauri::command]
async fn stream_api_download(
    app: tauri::AppHandle,
    file_name: String,
    url: String,
    token: String,
) -> Result<String, String> {
    let downloads = app
        .path()
        .download_dir()
        .map_err(|error| format!("ダウンロードフォルダを開けません: {error}"))?;
    for copy in 1..10_000 {
        let candidate_name = download_file_name(&file_name, copy)?;
        let candidate = downloads.join(&candidate_name);
        match OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&candidate)
        {
            Ok(_) => {
                std::fs::remove_file(&candidate).map_err(|error| error.to_string())?;
                stream_response(&url, &token, &candidate).await?;
                return Ok(candidate_name);
            }
            Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => continue,
            Err(error) => return Err(error.to_string()),
        }
    }
    Err("同名のWAVが多すぎるため保存できませんでした。".to_owned())
}

fn validated_wav_source(path: &str) -> Result<PathBuf, String> {
    let supplied = PathBuf::from(path);
    if !supplied.is_absolute()
        || supplied
            .extension()
            .and_then(|value| value.to_str())
            .map(str::to_ascii_lowercase)
            != Some("wav".to_owned())
    {
        return Err("保存元には絶対パスのWAVファイルを指定してください。".to_owned());
    }
    let source = supplied
        .canonicalize()
        .map_err(|_| "保存元のWAVが見つかりません。".to_owned())?;
    if !source.is_file()
        || source
            .extension()
            .and_then(|value| value.to_str())
            .map(str::to_ascii_lowercase)
            != Some("wav".to_owned())
    {
        return Err("保存元のWAVが見つかりません。".to_owned());
    }
    Ok(source)
}

#[tauri::command]
fn copy_local_file(local_path: String, destination: String) -> Result<(), String> {
    let source = validated_wav_source(&local_path)?;
    let destination = PathBuf::from(destination);
    if !destination.is_absolute() {
        return Err("保存先が正しくありません。".to_owned());
    }
    std::fs::copy(source, destination).map_err(|error| error.to_string())?;
    Ok(())
}

pub fn run() {
    let topology = accelerator_topology::detect();
    let topology_json =
        serde_json::to_string(&topology).expect("accelerator topology must serialize");
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, argv, cwd| {
            open_files::enqueue_and_notify(
                app,
                open_files::paths_from_args(argv, &PathBuf::from(cwd)),
            );
            focus_main_window(app);
        }))
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_opener::init())
        .invoke_handler(tauri::generate_handler![
            api_connection,
            stream_api_download,
            copy_local_file,
            accelerator_topology,
            installation_identity,
            open_files::drain_open_file_requests
        ])
        .manage(ApiProcessState::new())
        .manage(open_files::OpenFileQueue::default())
        .manage(topology)
        .setup(move |app| {
            let initial_cwd = std::env::current_dir().unwrap_or_default();
            let initial_paths = open_files::paths_from_args(std::env::args(), &initial_cwd);
            open_files::enqueue_and_notify(app.handle(), initial_paths);
            let repository_root = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
                .parent()
                .expect("src-tauri has a repository parent")
                .to_owned();
            let production_paths = if cfg!(debug_assertions) {
                None
            } else {
                let data_root = release_data_root(
                    app.path()
                        .app_data_dir()
                        .map_err(|error| std::io::Error::other(error.to_string()))?,
                );
                let sidecar =
                    sidecar_path(app).map_err(|error| std::io::Error::other(error.to_string()))?;
                let (uv, omlx_launcher, omlx_requirements) = omlx_bootstrap_paths(app)
                    .map_err(|error| std::io::Error::other(error.to_string()))?;
                api_supervisor::validate_production_artifact(&sidecar)
                    .and_then(|_| api_supervisor::validate_production_artifact(&uv))
                    .map_err(|error| {
                        std::io::Error::other(format!("Local API startup failed: {error}"))
                    })?;
                Some((sidecar, data_root, uv, omlx_launcher, omlx_requirements))
            };
            let window = app
                .get_webview_window("main")
                .expect("main window must be configured");
            if let Err(error) = window.show() {
                stop_api(app.handle());
                return Err(error.into());
            }
            let state = app.state::<ApiProcessState>().inner().clone();
            std::thread::spawn(move || {
                let result = match production_paths {
                    Some((sidecar, data_root, uv, launcher, requirements)) => {
                        api_supervisor::start_sidecar(
                            &sidecar,
                            &data_root,
                            &uv,
                            &launcher,
                            &requirements,
                            &topology_json,
                            &state.0.cancelled,
                        )
                    }
                    None => api_supervisor::start_development_api(
                        &repository_root,
                        &topology_json,
                        &state.0.cancelled,
                    ),
                };
                state.finish_startup(result);
            });
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("failed to initialize irodori SCENA");
    let app_handle = app.handle().clone();
    app.run_return(|app, event| {
        #[cfg(target_os = "macos")]
        if let tauri::RunEvent::Opened { urls } = &event {
            let paths = open_files::paths_from_urls(urls);
            open_files::enqueue_and_notify(app, paths);
            focus_main_window(app);
        }
        if matches!(event, tauri::RunEvent::Exit) {
            stop_api(app);
        }
    });
    stop_api(&app_handle);
}

#[cfg(test)]
mod tests {
    #[cfg(not(windows))]
    use super::api_supervisor::SupervisorError;
    use super::{download_file_name, release_data_root, ApiProcessState};
    use std::path::PathBuf;

    #[test]
    fn release_data_directory_does_not_depend_on_the_bundle_identifier() {
        assert_eq!(
            release_data_root(PathBuf::from(
                "/Users/example/Library/Application Support/com.irodori-scena"
            )),
            PathBuf::from("/Users/example/Library/Application Support/irodori-SCENA")
        );
    }

    #[test]
    fn download_names_keep_wav_files_inside_the_download_directory() {
        assert_eq!(
            download_file_name("001_台詞.wav", 1).unwrap(),
            "001_台詞.wav"
        );
        assert_eq!(
            download_file_name("001_台詞.wav", 2).unwrap(),
            "001_台詞 (2).wav"
        );
        assert!(download_file_name("../outside.wav", 1).is_err());
        assert!(download_file_name("台詞.txt", 1).is_err());
    }

    #[test]
    fn connection_waits_for_a_terminal_startup_result() {
        let state = ApiProcessState::new();
        let worker_state = state.clone();
        std::thread::spawn(move || {
            #[cfg(windows)]
            let error = std::io::Error::other("local API startup was cancelled");
            #[cfg(not(windows))]
            let error = SupervisorError::Cancelled;
            worker_state.finish_startup(Err(error));
        });
        assert!(state
            .connection()
            .unwrap_err()
            .contains("local API startup was cancelled"));
    }
}
