use crate::api_supervisor_common::{generate_token, health_response_ok};
use std::fmt;
use std::io::{self, Read, Write};
use std::net::{TcpListener, TcpStream};
use std::os::fd::AsRawFd;
use std::path::Path;
use std::process::{Child, Command, Stdio};
use std::sync::atomic::{AtomicBool, Ordering};
use std::thread;
use std::time::{Duration, Instant};

const HEALTH_PATH: &str = "/api/health";
const HEALTH_TIMEOUT: Duration = Duration::from_secs(20);
const RETRY_DELAY: Duration = Duration::from_millis(100);
const SHUTDOWN_TIMEOUT: Duration = Duration::from_secs(5);

#[derive(Debug)]
pub enum SupervisorError {
    PortUnavailable(io::Error),
    Spawn(io::Error),
    ProcessExited(Option<i32>),
    HealthTimedOut,
    Cancelled,
    Io(io::Error),
}

impl fmt::Display for SupervisorError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::PortUnavailable(e) => write!(f, "could not reserve a local API port ({e})"),
            Self::Spawn(e) => write!(f, "could not start the local FastAPI process ({e})"),
            Self::ProcessExited(code) => write!(
                f,
                "FastAPI exited before becoming healthy (exit code {})",
                code.map_or_else(|| "unknown".into(), |v| v.to_string())
            ),
            Self::HealthTimedOut => write!(
                f,
                "FastAPI did not answer GET {HEALTH_PATH} within {} seconds",
                HEALTH_TIMEOUT.as_secs()
            ),
            Self::Cancelled => write!(f, "local API startup was cancelled"),
            Self::Io(e) => write!(f, "local API supervision failed ({e})"),
        }
    }
}
impl std::error::Error for SupervisorError {}

pub struct ApiProcess {
    child: Option<Child>,
    address: String,
    token: String,
}

#[cfg(test)]
fn port(address: &str) -> String {
    address
        .rsplit(':')
        .next()
        .expect("address has a port")
        .to_owned()
}

pub fn start_sidecar(
    sidecar: &Path,
    data_root: &Path,
    uv: &Path,
    omlx_launcher: &Path,
    omlx_requirements: &Path,
    topology_json: &str,
    cancelled: &AtomicBool,
) -> Result<ApiProcess, SupervisorError> {
    validate_production_artifact(sidecar)?;
    validate_production_artifact(uv)?;
    let listener = reserve_api_listener()?;
    let address = listener
        .local_addr()
        .map_err(SupervisorError::Io)?
        .to_string();
    let mut command = Command::new(sidecar);
    command
        .args(["--fd", &listener.as_raw_fd().to_string()])
        .env("SCENA_DATA_ROOT", data_root)
        .env("SCENA_DEV_MODE", "0")
        .env("SCENA_UV_EXECUTABLE", uv)
        .env("SCENA_OMLX_LAUNCHER", omlx_launcher)
        .env("SCENA_OMLX_REQUIREMENTS", omlx_requirements)
        .env("SCENA_ACCELERATOR_TOPOLOGY", topology_json)
        .stdin(Stdio::null())
        .stdout(Stdio::inherit())
        .stderr(Stdio::inherit());
    start_api_process(command, listener, address, cancelled)
}

pub fn start_development_api(
    root: &Path,
    topology_json: &str,
    cancelled: &AtomicBool,
) -> Result<ApiProcess, SupervisorError> {
    let listener = reserve_api_listener()?;
    let address = listener
        .local_addr()
        .map_err(SupervisorError::Io)?
        .to_string();
    start_api_process(
        development_command(root, listener.as_raw_fd(), topology_json),
        listener,
        address,
        cancelled,
    )
}

fn development_command(root: &Path, fd: i32, topology_json: &str) -> Command {
    let mut command = Command::new("uv");
    command
        .args(["run", "uvicorn", "server.app:app", "--fd", &fd.to_string()])
        .current_dir(root)
        .env("SCENA_DEV_MODE", "1")
        .env("SCENA_ACCELERATOR_TOPOLOGY", topology_json)
        .stdin(Stdio::null())
        .stdout(Stdio::inherit())
        .stderr(Stdio::inherit());
    command
}

fn start_api_process(
    mut command: Command,
    listener: TcpListener,
    address: String,
    cancelled: &AtomicBool,
) -> Result<ApiProcess, SupervisorError> {
    let token = generate_token().map_err(SupervisorError::Io)?;
    command
        .env("SCENA_DESKTOP", "1")
        .env("SCENA_API_TOKEN", &token)
        .env("SCENA_PARENT_PID", std::process::id().to_string());
    let child = command.spawn().map_err(SupervisorError::Spawn)?;
    drop(listener);
    let mut process = ApiProcess {
        child: Some(child),
        address,
        token,
    };
    if let Err(error) = wait_for_health(
        process.child.as_mut().unwrap(),
        &process.address,
        &process.token,
        HEALTH_TIMEOUT,
        cancelled,
    ) {
        let _ = process.stop();
        return Err(error);
    }
    Ok(process)
}

fn reserve_api_listener() -> Result<TcpListener, SupervisorError> {
    let listener = TcpListener::bind("127.0.0.1:0").map_err(SupervisorError::PortUnavailable)?;
    let fd = listener.as_raw_fd();
    let flags = unsafe { libc::fcntl(fd, libc::F_GETFD) };
    if flags < 0 || unsafe { libc::fcntl(fd, libc::F_SETFD, flags & !libc::FD_CLOEXEC) } < 0 {
        return Err(SupervisorError::Io(io::Error::last_os_error()));
    }
    Ok(listener)
}

pub fn validate_production_artifact(path: &Path) -> Result<(), SupervisorError> {
    if !path.is_file() {
        return Err(SupervisorError::Io(io::Error::new(
            io::ErrorKind::NotFound,
            format!("required runtime is missing: {}", path.display()),
        )));
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        if path
            .metadata()
            .map_err(SupervisorError::Io)?
            .permissions()
            .mode()
            & 0o111
            == 0
        {
            return Err(SupervisorError::Io(io::Error::new(
                io::ErrorKind::PermissionDenied,
                format!("runtime is not executable: {}", path.display()),
            )));
        }
    }
    Ok(())
}

fn wait_for_health(
    child: &mut Child,
    address: &str,
    token: &str,
    timeout: Duration,
    cancelled: &AtomicBool,
) -> Result<(), SupervisorError> {
    let deadline = Instant::now() + timeout;
    loop {
        if cancelled.load(Ordering::Acquire) {
            return Err(SupervisorError::Cancelled);
        }
        if health_check(address, token).unwrap_or(false) {
            return Ok(());
        }
        if let Some(status) = child.try_wait().map_err(SupervisorError::Io)? {
            return Err(SupervisorError::ProcessExited(status.code()));
        }
        if Instant::now() >= deadline {
            return Err(SupervisorError::HealthTimedOut);
        }
        thread::sleep(RETRY_DELAY);
    }
}

fn health_check(address: &str, token: &str) -> io::Result<bool> {
    let mut stream =
        TcpStream::connect_timeout(&address.parse().expect("valid address"), RETRY_DELAY)?;
    stream.set_read_timeout(Some(RETRY_DELAY))?;
    stream.set_write_timeout(Some(RETRY_DELAY))?;
    stream.write_all(
        format!("GET {HEALTH_PATH} HTTP/1.1\r\nHost: {address}\r\nAuthorization: Bearer {token}\r\nConnection: close\r\n\r\n")
            .as_bytes(),
    )?;
    let mut response = String::new();
    stream.read_to_string(&mut response)?;
    Ok(health_response_ok(&response))
}

impl ApiProcess {
    pub fn base_url(&self) -> String {
        format!("http://{}", self.address)
    }
    pub fn token(&self) -> &str {
        &self.token
    }
    pub fn stop(&mut self) -> Result<(), SupervisorError> {
        self.stop_with_timeout(SHUTDOWN_TIMEOUT)
    }
    fn stop_with_timeout(&mut self, timeout: Duration) -> Result<(), SupervisorError> {
        let Some(child) = self.child.as_mut() else {
            return Ok(());
        };
        if child.try_wait().map_err(SupervisorError::Io)?.is_some() {
            return Ok(());
        }
        let pid = child.id() as i32;
        signal_process(pid, libc::SIGTERM)?;
        let deadline = Instant::now() + timeout;
        while Instant::now() < deadline {
            if child.try_wait().map_err(SupervisorError::Io)?.is_some() {
                return Ok(());
            }
            thread::sleep(Duration::from_millis(50));
        }
        signal_process(pid, libc::SIGKILL)?;
        child.wait().map_err(SupervisorError::Io)?;
        Ok(())
    }
}

impl Drop for ApiProcess {
    fn drop(&mut self) {
        let _ = self.stop();
    }
}

fn signal_process(pid: i32, signal: i32) -> Result<(), SupervisorError> {
    if unsafe { libc::kill(pid, signal) } == 0 {
        return Ok(());
    }
    let error = io::Error::last_os_error();
    if error.raw_os_error() == Some(libc::ESRCH) {
        Ok(())
    } else {
        Err(SupervisorError::Io(error))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn reserves_ephemeral_port() {
        let listener = reserve_api_listener().unwrap();
        assert_ne!(port(&listener.local_addr().unwrap().to_string()), "0");
    }
    #[test]
    fn development_command_has_no_reload() {
        let debug = format!(
            "{:?}",
            development_command(Path::new("/tmp/scena"), 42, r#"{"kind":"apple"}"#),
        );
        assert!(
            debug.contains("server.app:app")
                && debug.contains("42")
                && debug.contains("SCENA_DEV_MODE=\"1\"")
                && debug.contains("SCENA_ACCELERATOR_TOPOLOGY=\"{\\\"kind\\\":\\\"apple\\\"}\"")
                && !debug.contains("--reload")
        );
    }
    #[test]
    fn early_exit_is_reported() {
        let mut child = Command::new("sh").arg("-c").arg("exit 7").spawn().unwrap();
        assert!(matches!(
            wait_for_health(
                &mut child,
                "127.0.0.1:9",
                "token",
                Duration::from_secs(1),
                &AtomicBool::new(false),
            )
            .unwrap_err(),
            SupervisorError::ProcessExited(Some(7))
        ));
    }
    #[test]
    fn startup_wait_can_be_cancelled() {
        let cancelled = AtomicBool::new(true);
        let mut child = shell("sleep 5");
        assert!(matches!(
            wait_for_health(
                &mut child,
                "127.0.0.1:9",
                "token",
                Duration::from_secs(1),
                &cancelled,
            )
            .unwrap_err(),
            SupervisorError::Cancelled
        ));
        child.kill().unwrap();
        child.wait().unwrap();
    }
    fn shell(script: &str) -> Child {
        let mut command = Command::new("sh");
        command.arg("-c").arg(script);
        command.spawn().unwrap()
    }
    #[test]
    fn graceful_stop_terminates_child() {
        let mut process = ApiProcess {
            child: Some(shell("trap 'exit 0' TERM; while true; do sleep 1; done")),
            address: "127.0.0.1:9".into(),
            token: "token".into(),
        };
        process.stop().unwrap();
        assert!(process
            .child
            .as_mut()
            .unwrap()
            .try_wait()
            .unwrap()
            .is_some());
    }
    #[test]
    fn stop_forces_child_that_ignores_term() {
        let mut process = ApiProcess {
            child: Some(shell("trap '' TERM; while true; do sleep 1; done")),
            address: "127.0.0.1:9".into(),
            token: "token".into(),
        };
        process
            .stop_with_timeout(Duration::from_millis(100))
            .unwrap();
        assert!(process
            .child
            .as_mut()
            .unwrap()
            .try_wait()
            .unwrap()
            .is_some());
    }
}
