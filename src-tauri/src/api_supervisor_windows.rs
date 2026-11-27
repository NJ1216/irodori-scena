//! Windows owns a private control listener; Python owns the API socket from bind to shutdown.
use crate::api_supervisor_common::{generate_token, health_response_ok};
use std::io::{self, Read, Write};
use std::net::{TcpListener, TcpStream};
use std::os::windows::process::CommandExt;
use std::path::Path;
use std::process::{Child, Command, Stdio};
use std::sync::atomic::{AtomicBool, Ordering};
use std::thread;
use std::time::{Duration, Instant};

pub type SupervisorError = io::Error;
const START_TIMEOUT: Duration = Duration::from_secs(20);
const CREATE_NO_WINDOW: u32 = 0x0800_0000;

fn hidden(command: &mut Command) -> &mut Command {
    command.creation_flags(CREATE_NO_WINDOW)
}

pub struct ApiProcess {
    child: Child,
    control: Option<TcpStream>,
    address: String,
    token: String,
}

pub fn start_sidecar(
    sidecar: &Path,
    data_root: &Path,
    uv: &Path,
    _omlx_launcher: &Path,
    _omlx_requirements: &Path,
    topology_json: &str,
    cancelled: &AtomicBool,
) -> Result<ApiProcess, SupervisorError> {
    validate_production_artifact(sidecar)?;
    validate_production_artifact(uv)?;
    let mut command = Command::new(sidecar);
    command
        .env("SCENA_DATA_ROOT", data_root)
        .env("SCENA_DEV_MODE", "0")
        .env("SCENA_UV_EXECUTABLE", uv);
    command.env("SCENA_ACCELERATOR_TOPOLOGY", topology_json);
    start(command, cancelled)
}

pub fn start_development_api(
    root: &Path,
    topology_json: &str,
    cancelled: &AtomicBool,
) -> Result<ApiProcess, SupervisorError> {
    let mut command = Command::new("uv");
    command
        .args(["run", "python", "-m", "server.sidecar"])
        .current_dir(root)
        .env("SCENA_DEV_MODE", "1");
    command.env("SCENA_ACCELERATOR_TOPOLOGY", topology_json);
    start(command, cancelled)
}

pub fn validate_production_artifact(path: &Path) -> Result<(), SupervisorError> {
    if path.is_file() {
        Ok(())
    } else {
        Err(io::Error::new(
            io::ErrorKind::NotFound,
            format!("required runtime is missing: {}", path.display()),
        ))
    }
}

fn start(mut command: Command, cancelled: &AtomicBool) -> Result<ApiProcess, SupervisorError> {
    let listener = TcpListener::bind("127.0.0.1:0")?;
    listener.set_nonblocking(true)?;
    let token = generate_token()?;
    command
        .env("SCENA_DESKTOP", "1")
        .env("SCENA_API_TOKEN", &token)
        .env("SCENA_PARENT_PID", std::process::id().to_string())
        .env("SCENA_CONTROL_ADDRESS", listener.local_addr()?.to_string())
        .stdin(Stdio::null())
        .stdout(Stdio::inherit())
        .stderr(Stdio::inherit());
    hidden(&mut command);
    let mut process = ApiProcess {
        child: command.spawn()?,
        control: None,
        address: String::new(),
        token,
    };
    let deadline = Instant::now() + START_TIMEOUT;
    let (control, port) = rendezvous(
        &listener,
        &mut process.child,
        &process.token,
        cancelled,
        deadline,
    )?;
    process.control = Some(control);
    process.address = format!("127.0.0.1:{port}");
    loop {
        check_startup(&mut process.child, cancelled, deadline)?;
        if healthy(&process.address, &process.token) {
            return Ok(process);
        }
        thread::sleep(Duration::from_millis(50));
    }
}

fn check_startup(child: &mut Child, cancelled: &AtomicBool, deadline: Instant) -> io::Result<()> {
    if cancelled.load(Ordering::Acquire) {
        return Err(io::Error::other("local API startup was cancelled"));
    }
    if child.try_wait()?.is_some() {
        return Err(io::Error::other("local API exited during startup"));
    }
    if Instant::now() >= deadline {
        return Err(io::Error::new(
            io::ErrorKind::TimedOut,
            "local API startup timed out",
        ));
    }
    Ok(())
}

fn rendezvous(
    listener: &TcpListener,
    child: &mut Child,
    token: &str,
    cancelled: &AtomicBool,
    deadline: Instant,
) -> io::Result<(TcpStream, u16)> {
    let mut pending: Vec<(TcpStream, Vec<u8>)> = Vec::new();
    loop {
        check_startup(child, cancelled, deadline)?;
        match listener.accept() {
            Ok((stream, _)) if pending.len() < 8 => {
                stream.set_nonblocking(true)?;
                pending.push((stream, Vec::new()));
            }
            Ok(_) => {}
            Err(error) if error.kind() == io::ErrorKind::WouldBlock => {}
            Err(error) => return Err(error),
        }
        let mut index = 0;
        while index < pending.len() {
            let (stream, buffer) = &mut pending[index];
            let mut chunk = [0_u8; 1024];
            let remove = match stream.read(&mut chunk) {
                Ok(0) => true,
                Ok(count) => {
                    buffer.extend_from_slice(&chunk[..count]);
                    if buffer.ends_with(b"\n") {
                        if let Some(port) = handshake_port(buffer, token) {
                            let (stream, _) = pending.swap_remove(index);
                            return Ok((stream, port));
                        }
                        true
                    } else {
                        buffer.len() >= 1024
                    }
                }
                Err(error) => error.kind() != io::ErrorKind::WouldBlock,
            };
            if remove {
                pending.swap_remove(index);
            } else {
                index += 1;
            }
        }
        thread::sleep(Duration::from_millis(10));
    }
}

fn handshake_port(bytes: &[u8], token: &str) -> Option<u16> {
    let value: serde_json::Value = serde_json::from_slice(bytes).ok()?;
    if value.get("token")?.as_str()? != token {
        return None;
    }
    let port = u16::try_from(value.get("port")?.as_u64()?).ok()?;
    (port != 0).then_some(port)
}

fn healthy(address: &str, token: &str) -> bool {
    let Ok(address) = address.parse() else {
        return false;
    };
    let Ok(mut stream) = TcpStream::connect_timeout(&address, Duration::from_millis(200)) else {
        return false;
    };
    let timeout = Some(Duration::from_millis(200));
    if stream.set_read_timeout(timeout).is_err() || stream.set_write_timeout(timeout).is_err() {
        return false;
    }
    let request = format!("GET /api/health HTTP/1.1\r\nHost: {address}\r\nAuthorization: Bearer {token}\r\nConnection: close\r\n\r\n");
    if stream.write_all(request.as_bytes()).is_err() {
        return false;
    }
    let mut response = Vec::new();
    if stream.read_to_end(&mut response).is_err() && response.is_empty() {
        return false;
    }
    health_response_ok(&String::from_utf8_lossy(&response))
}

impl ApiProcess {
    pub fn base_url(&self) -> String {
        format!("http://{}", self.address)
    }
    pub fn token(&self) -> &str {
        &self.token
    }
    pub fn stop(&mut self) -> Result<(), SupervisorError> {
        // EOF requests graceful Uvicorn shutdown, including its exit cleanup.
        self.control.take();
        let deadline = Instant::now() + Duration::from_secs(5);
        while Instant::now() < deadline {
            if self.child.try_wait()?.is_some() {
                return Ok(());
            }
            thread::sleep(Duration::from_millis(50));
        }
        // uv can supervise the actual Python process: stop only this owned tree.
        let mut command = Command::new("taskkill.exe");
        command
            .args(["/PID", &self.child.id().to_string(), "/T", "/F"])
            .stdout(Stdio::null())
            .stderr(Stdio::null());
        let status = hidden(&mut command).status()?;
        if !status.success() && self.child.try_wait()?.is_none() {
            return Err(io::Error::other("could not stop local API process tree"));
        }
        self.child.wait()?;
        Ok(())
    }
}

impl Drop for ApiProcess {
    fn drop(&mut self) {
        let _ = self.stop();
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn rejects_untrusted_or_invalid_port() {
        assert_eq!(
            handshake_port(br#"{"token":"secret","port":8787}"#, "secret"),
            Some(8787)
        );
        for message in [
            r#"{"token":"other","port":8787}"#,
            r#"{"token":"secret","port":0}"#,
            r#"{"token":"secret","port":65536}"#,
            "invalid",
        ] {
            assert_eq!(handshake_port(message.as_bytes(), "secret"), None);
        }
    }
}
