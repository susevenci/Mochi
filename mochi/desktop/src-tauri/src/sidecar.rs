// 边车托管（T5-02）：端口探测 + 随机 token + 健康探活 + 崩溃重启。
//
// 开发态直接拉起仓库里的 uvicorn；发布态拉起 Tauri resource 里的
// mochi-server.exe。前端通过 index.html?port=&token= 拿到本次启动参数。

use std::{
    env,
    io::{Read, Write},
    net::{SocketAddr, TcpListener, TcpStream},
    path::PathBuf,
    process::{Child, Command, Stdio},
    sync::{
        atomic::{AtomicBool, AtomicU8, Ordering},
        Arc, Mutex,
    },
    thread,
    time::{Duration, Instant},
};

use rand::RngCore;
use tauri::{path::BaseDirectory, AppHandle, Manager};

const MAX_RESTARTS: u8 = 3;
pub const HEALTH_TIMEOUT: Duration = Duration::from_secs(30);

#[derive(Clone)]
struct CommandSpec {
    program: PathBuf,
    args: Vec<String>,
    cwd: Option<PathBuf>,
    envs: Vec<(String, String)>,
    log_path: PathBuf,
}

impl CommandSpec {
    fn spawn(&self) -> Result<Child, String> {
        let mut command = Command::new(&self.program);
        command.args(&self.args).stdin(Stdio::null());
        match std::fs::OpenOptions::new()
            .create(true)
            .append(true)
            .open(&self.log_path)
        {
            Ok(file) => {
                command.stdout(Stdio::from(file.try_clone().map_err(|err| err.to_string())?));
                command.stderr(Stdio::from(file));
            }
            Err(_) => {
                command.stdout(Stdio::null()).stderr(Stdio::null());
            }
        }
        if let Some(cwd) = &self.cwd {
            command.current_dir(cwd);
        }
        for (key, value) in &self.envs {
            command.env(key, value);
        }
        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;
            command.creation_flags(0x0800_0000); // CREATE_NO_WINDOW
        }
        command.spawn().map_err(|err| format!("spawn failed: {err}"))
    }
}

pub struct BackendManager {
    pub port: u16,
    pub token: String,
    child: Arc<Mutex<Option<Child>>>,
    stopped: Arc<AtomicBool>,
    restarts: Arc<AtomicU8>,
    spec: CommandSpec,
}

impl BackendManager {
    pub fn start(app: AppHandle) -> Result<Self, String> {
        let port = free_port()?;
        let token = random_token();
        let spec = build_spec(&app, port, &token)?;
        let child = spec.spawn()?;
        let manager = Self {
            port,
            token,
            child: Arc::new(Mutex::new(Some(child))),
            stopped: Arc::new(AtomicBool::new(false)),
            restarts: Arc::new(AtomicU8::new(0)),
            spec,
        };
        manager.spawn_monitor();
        Ok(manager)
    }

    fn spawn_monitor(&self) {
        let child_slot = self.child.clone();
        let stopped = self.stopped.clone();
        let restarts = self.restarts.clone();
        let spec = self.spec.clone();
        thread::spawn(move || loop {
            thread::sleep(Duration::from_secs(2));
            if stopped.load(Ordering::SeqCst) {
                break;
            }
            let exited = {
                let mut guard = child_slot.lock().unwrap_or_else(|err| err.into_inner());
                match guard.as_mut() {
                    Some(child) => matches!(child.try_wait(), Ok(Some(_))),
                    None => true,
                }
            };
            if !exited {
                continue;
            }
            let count = restarts.load(Ordering::SeqCst);
            if count >= MAX_RESTARTS {
                eprintln!("[sidecar] 连续崩溃 {count} 次，停止重启");
                break;
            }
            eprintln!("[sidecar] 检测到退出，尝试重启 {}/{}", count + 1, MAX_RESTARTS);
            match spec.spawn() {
                Ok(child) => {
                    restarts.store(count + 1, Ordering::SeqCst);
                    let mut guard = child_slot.lock().unwrap_or_else(|err| err.into_inner());
                    *guard = Some(child);
                }
                Err(err) => {
                    eprintln!("[sidecar] 重启失败: {err}");
                    break;
                }
            }
        });
    }

    pub fn shutdown(&self) {
        self.stopped.store(true, Ordering::SeqCst);
        let request = format!(
            "POST /api/v1/sys/shutdown HTTP/1.1\r\nHost: 127.0.0.1\r\nX-Mochi-Token: {}\r\nContent-Length: 0\r\nConnection: close\r\n\r\n",
            self.token
        );
        if let Ok(mut stream) = TcpStream::connect_timeout(
            &SocketAddr::from(([127, 0, 0, 1], self.port)),
            Duration::from_millis(500),
        ) {
            let _ = stream.write_all(request.as_bytes());
            let _ = stream.flush();
        }
        let deadline = Instant::now() + Duration::from_secs(2);
        loop {
            let exited = {
                let mut guard = self.child.lock().unwrap_or_else(|err| err.into_inner());
                match guard.as_mut() {
                    Some(child) => matches!(child.try_wait(), Ok(Some(_))),
                    None => true,
                }
            };
            if exited || Instant::now() >= deadline {
                break;
            }
            thread::sleep(Duration::from_millis(100));
        }
        let mut guard = self.child.lock().unwrap_or_else(|err| err.into_inner());
        if let Some(child) = guard.as_mut() {
            let _ = child.kill();
            let _ = child.wait();
        }
        *guard = None;
    }
}

fn random_token() -> String {
    let mut bytes = [0u8; 16];
    rand::thread_rng().fill_bytes(&mut bytes);
    bytes.iter().map(|byte| format!("{byte:02x}")).collect()
}

fn free_port() -> Result<u16, String> {
    let listener = TcpListener::bind(("127.0.0.1", 0)).map_err(|err| err.to_string())?;
    let port = listener.local_addr().map_err(|err| err.to_string())?.port();
    drop(listener);
    Ok(port)
}

fn build_spec(app: &AppHandle, port: u16, token: &str) -> Result<CommandSpec, String> {
    let mut envs = vec![
        ("SERVER_PORT".to_string(), port.to_string()),
        ("SERVER_TOKEN".to_string(), token.to_string()),
        ("MOCHI_SIDECAR".to_string(), "1".to_string()),
        ("PYTHONUNBUFFERED".to_string(), "1".to_string()),
    ];
    if env::var("VOICE_ENABLED").is_ok() {
        envs.push(("VOICE_ENABLED".to_string(), env::var("VOICE_ENABLED").unwrap()));
    }

    let data_dir = app
        .path()
        .app_data_dir()
        .unwrap_or_else(|_| PathBuf::from("."));
    let log_dir = data_dir.join("logs");
    let _ = std::fs::create_dir_all(&log_dir);
    let log_path = log_dir.join("sidecar.log");

    let release_binary = app
        .path()
        .resolve("binaries/mochi-server.exe", BaseDirectory::Resource)
        .unwrap_or_else(|_| PathBuf::from("binaries/mochi-server.exe"));
    if release_binary.is_file() && env::var("MOCHI_DEV_SERVER").is_err() {
        return Ok(CommandSpec {
            program: release_binary,
            args: vec![],
            cwd: None,
            envs,
            log_path,
        });
    }

    // 开发态：优先使用仓库 .venv，回落到 PATH 上的 python
    let root = std::env::var("MOCHI_ROOT")
        .map(PathBuf::from)
        .ok()
        .or_else(find_repo_root)
        .ok_or_else(|| "MOCHI_ROOT 未设置且找不到仓库根目录".to_string())?;
    let python = env::var("MOCHI_PYTHON")
        .map(PathBuf::from)
        .unwrap_or_else(|_| {
            let candidate = root.join(".venv").join("python.exe");
            if candidate.is_file() {
                candidate
            } else {
                PathBuf::from("python")
            }
        });
    Ok(CommandSpec {
        program: python,
        args: vec![
            "-m".into(),
            "uvicorn".into(),
            "--app-dir".into(),
            "server".into(),
            "app.main:create_app".into(),
            "--factory".into(),
            "--host".into(),
            "127.0.0.1".into(),
            "--port".into(),
            port.to_string(),
        ],
        cwd: Some(root),
        envs,
        log_path,
    })
}

fn find_repo_root() -> Option<PathBuf> {
    let mut current = env::current_dir().ok()?;
    for _ in 0..6 {
        if current.join("server").join("app").join("main.py").is_file() {
            return Some(current);
        }
        current = current.parent()?.to_path_buf();
    }
    None
}

/// 简单 HTTP 健康探活：不引入额外 HTTP 依赖，只读第一行状态码。
pub fn wait_health(port: u16, timeout: Duration) -> bool {
    let deadline = Instant::now() + timeout;
    let request = b"GET /health HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n";
    while Instant::now() < deadline {
        if let Ok(mut stream) = TcpStream::connect_timeout(
            &SocketAddr::from(([127, 0, 0, 1], port)),
            Duration::from_millis(400),
        ) {
            let _ = stream.set_read_timeout(Some(Duration::from_millis(800)));
            if stream.write_all(request).is_ok() {
                let mut buffer = [0u8; 256];
                let mut text = String::new();
                if let Ok(size) = stream.read(&mut buffer) {
                    text.push_str(&String::from_utf8_lossy(&buffer[..size]));
                }
                if text.starts_with("HTTP/1.1 200") || text.starts_with("HTTP/1.0 200") {
                    return true;
                }
            }
        }
        thread::sleep(Duration::from_millis(250));
    }
    false
}

