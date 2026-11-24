use std::collections::VecDeque;
use std::path::{Path, PathBuf};
use std::sync::Mutex;

use tauri::{AppHandle, Emitter, Manager};

pub const OPEN_FILES_EVENT: &str = "scena-open-files";

#[derive(Default)]
pub struct OpenFileQueue(Mutex<VecDeque<Vec<String>>>);

impl OpenFileQueue {
    pub fn enqueue(&self, paths: Vec<PathBuf>) -> bool {
        let request: Vec<String> = paths
            .into_iter()
            .filter(|path| supported(path))
            .map(|path| path.to_string_lossy().into_owned())
            .collect();
        if request.is_empty() {
            return false;
        }
        self.0
            .lock()
            .expect("open-file queue lock poisoned")
            .push_back(request);
        true
    }

    fn drain(&self) -> Vec<Vec<String>> {
        self.0
            .lock()
            .expect("open-file queue lock poisoned")
            .drain(..)
            .collect()
    }
}

fn supported(path: &Path) -> bool {
    matches!(
        path.extension()
            .and_then(|value| value.to_str())
            .map(str::to_ascii_lowercase)
            .as_deref(),
        Some("scena" | "scenacast")
    )
}

pub fn paths_from_args(args: impl IntoIterator<Item = String>, cwd: &Path) -> Vec<PathBuf> {
    args.into_iter()
        .skip(1)
        .map(PathBuf::from)
        .map(|path| {
            if path.is_absolute() {
                path
            } else {
                cwd.join(path)
            }
        })
        .filter(|path| supported(path))
        .collect()
}

#[cfg(target_os = "macos")]
pub fn paths_from_urls<'a>(urls: impl IntoIterator<Item = &'a tauri::Url>) -> Vec<PathBuf> {
    urls.into_iter()
        .filter_map(|url| url.to_file_path().ok())
        .filter(|path| supported(path))
        .collect()
}

pub fn enqueue_and_notify(app: &AppHandle, paths: Vec<PathBuf>) {
    if app.state::<OpenFileQueue>().enqueue(paths) {
        let _ = app.emit(OPEN_FILES_EVENT, ());
    }
}

#[tauri::command]
pub fn drain_open_file_requests(state: tauri::State<'_, OpenFileQueue>) -> Vec<Vec<String>> {
    state.drain()
}

#[cfg(test)]
mod tests {
    use super::{paths_from_args, OpenFileQueue};
    #[cfg(target_os = "macos")]
    use super::paths_from_urls;
    use std::path::PathBuf;

    #[test]
    fn arguments_keep_supported_paths_in_request_order() {
        let cwd = PathBuf::from("/tmp/作業 空間");
        let paths = paths_from_args(
            ["scena", "作品.SCENA", "/tmp/彩.scenacast", "note.txt"].map(str::to_owned),
            &cwd,
        );
        assert_eq!(
            paths,
            vec![cwd.join("作品.SCENA"), PathBuf::from("/tmp/彩.scenacast")]
        );
    }

    #[test]
    fn queue_preserves_request_boundaries_and_fifo_order() {
        let queue = OpenFileQueue::default();
        assert!(queue.enqueue(vec![
            PathBuf::from("一.scenacast"),
            PathBuf::from("二.SCENACAST")
        ]));
        assert!(queue.enqueue(vec![PathBuf::from("作品.scena")]));
        assert!(!queue.enqueue(vec![PathBuf::from("readme.txt")]));
        assert_eq!(
            queue.drain(),
            vec![vec!["一.scenacast", "二.SCENACAST"], vec!["作品.scena"]]
        );
        assert!(queue.drain().is_empty());
    }

    #[cfg(target_os = "macos")]
    #[test]
    fn macos_file_urls_decode_spaces_and_japanese_paths() {
        let urls = [
            tauri::Url::parse("file:///tmp/%E6%97%A5%E6%9C%AC%E8%AA%9E%20%E4%BD%9C%E5%93%81.scena")
                .unwrap(),
            tauri::Url::parse("https://example.invalid/not-a-file.scena").unwrap(),
            tauri::Url::parse("file:///tmp/readme.txt").unwrap(),
        ];
        assert_eq!(
            paths_from_urls(&urls),
            vec![PathBuf::from("/tmp/日本語 作品.scena")]
        );
    }
}
