use serde::Serialize;
use std::env;
use std::ffi::OsString;
use std::fs::{self, OpenOptions};
use std::io::{Read, Write};
use std::net::{SocketAddr, TcpListener, TcpStream};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::time::{Duration, Instant};
use tauri::menu::{MenuBuilder, SubmenuBuilder};
use tauri::{AppHandle, Manager, RunEvent, State, WindowEvent};

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct DesktopCoreStatus {
    api_url: String,
    core_status: String,
    database_path: String,
    worker_status: String,
    version: String,
    error: Option<String>,
}

struct DesktopInner {
    api_base_url: String,
    core_status: String,
    database_path: PathBuf,
    elephant_home: PathBuf,
    herd_dir: PathBuf,
    repo_root: PathBuf,
    child: Option<Child>,
    error: Option<String>,
}

struct DesktopState {
    inner: Mutex<DesktopInner>,
}

impl DesktopState {
    fn status(&self) -> DesktopCoreStatus {
        let inner = self.inner.lock().expect("desktop state poisoned");
        status_from_inner(&inner)
    }
}

fn status_from_inner(inner: &DesktopInner) -> DesktopCoreStatus {
    DesktopCoreStatus {
        api_url: inner.api_base_url.clone(),
        core_status: inner.core_status.clone(),
        database_path: inner.database_path.display().to_string(),
        worker_status: if inner.child.is_some() {
            "managed".into()
        } else {
            "stopped".into()
        },
        version: env!("CARGO_PKG_VERSION").into(),
        error: inner.error.clone(),
    }
}

fn home_dir() -> Option<PathBuf> {
    env::var_os("HOME").map(PathBuf::from)
}

fn resolve_python_root(resource_dir: Option<PathBuf>) -> PathBuf {
    if let Some(resource_dir) = resource_dir {
        let bundled_python_root = resource_dir.join("python");
        if bundled_python_root.join("apps").join("api").exists()
            && bundled_python_root.join("packages").exists()
        {
            return bundled_python_root;
        }
    }
    if let Some(root) = env::var_os("ELEPHANT_DESKTOP_REPO_ROOT").map(PathBuf::from) {
        return root;
    }
    if let Ok(current) = env::current_dir() {
        if current.join("pyproject.toml").exists() {
            return current;
        }
        if current.ends_with("apps/desktop") {
            if let Some(root) = current.parent().and_then(Path::parent) {
                return root.to_path_buf();
            }
        }
    }
    env::current_exe()
        .ok()
        .and_then(|path| path.parent().map(Path::to_path_buf))
        .unwrap_or_else(|| PathBuf::from("."))
}

fn resolve_data_paths(app_data_dir: PathBuf) -> Result<(PathBuf, PathBuf, PathBuf), String> {
    let legacy_home = home_dir().map(|home| home.join(".elephant"));
    let legacy_database = legacy_home
        .as_ref()
        .map(|home| home.join("herd").join("elephant.sqlite3"));
    if legacy_database.as_ref().is_some_and(|path| path.exists()) {
        let elephant_home = legacy_home.expect("legacy database has a home");
        let herd_dir = elephant_home.join("herd");
        return Ok((
            elephant_home,
            herd_dir.clone(),
            herd_dir.join("elephant.sqlite3"),
        ));
    }

    let elephant_home = app_data_dir;
    let herd_dir = elephant_home.join("herd");
    fs::create_dir_all(&herd_dir)
        .map_err(|error| format!("could not create app data dir: {error}"))?;
    Ok((
        elephant_home,
        herd_dir.clone(),
        herd_dir.join("elephant.sqlite3"),
    ))
}

fn free_loopback_port() -> Result<u16, String> {
    let listener = TcpListener::bind("127.0.0.1:0")
        .map_err(|error| format!("could not bind loopback probe: {error}"))?;
    let port = listener
        .local_addr()
        .map_err(|error| format!("could not read loopback probe port: {error}"))?
        .port();
    drop(listener);
    Ok(port)
}

fn local_http_ok(port: u16, path: &str) -> bool {
    let address: SocketAddr = match format!("127.0.0.1:{port}").parse() {
        Ok(value) => value,
        Err(_) => return false,
    };
    let mut stream = match TcpStream::connect_timeout(&address, Duration::from_millis(160)) {
        Ok(value) => value,
        Err(_) => return false,
    };
    let _ = stream.set_read_timeout(Some(Duration::from_millis(350)));
    let request = format!("GET {path} HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n");
    if stream.write_all(request.as_bytes()).is_err() {
        return false;
    }
    let mut response = String::new();
    if stream.read_to_string(&mut response).is_err() {
        return false;
    }
    response.starts_with("HTTP/1.1 200") || response.starts_with("HTTP/1.0 200")
}

fn local_http_post(api_base_url: &str, path: &str, body: &str) -> bool {
    let Some(port_text) = api_base_url.strip_prefix("http://127.0.0.1:") else {
        return false;
    };
    let Ok(port) = port_text.parse::<u16>() else {
        return false;
    };
    let address: SocketAddr = match format!("127.0.0.1:{port}").parse() {
        Ok(value) => value,
        Err(_) => return false,
    };
    let mut stream = match TcpStream::connect_timeout(&address, Duration::from_millis(220)) {
        Ok(value) => value,
        Err(_) => return false,
    };
    let _ = stream.set_read_timeout(Some(Duration::from_millis(600)));
    let request = format!(
        "POST {path} HTTP/1.1\r\nHost: 127.0.0.1\r\nAccept: application/json\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",
        body.as_bytes().len()
    );
    if stream.write_all(request.as_bytes()).is_err() {
        return false;
    }
    let mut response = String::new();
    if stream.read_to_string(&mut response).is_err() {
        return false;
    }
    response.starts_with("HTTP/1.1 200") || response.starts_with("HTTP/1.0 200")
}

fn wait_for_core(port: u16) -> Result<(), String> {
    let deadline = Instant::now() + Duration::from_secs(35);
    let mut health_ready = false;
    while Instant::now() < deadline {
        if !health_ready {
            health_ready = local_http_ok(port, "/healthz");
        }
        if health_ready && local_http_ok(port, "/v1/internal/dashboard/overview") {
            return Ok(());
        }
        std::thread::sleep(Duration::from_millis(250));
    }
    Err("local API did not become ready in time".into())
}

fn stop_core(inner: &mut DesktopInner) {
    if let Some(mut child) = inner.child.take() {
        let _ = child.kill();
        let _ = child.wait();
    }
    inner.core_status = "stopped".into();
}

fn python_module_path(root: &Path) -> Result<OsString, String> {
    let mut paths = vec![root.to_path_buf()];
    if let Some(existing) = env::var_os("PYTHONPATH") {
        paths.extend(env::split_paths(&existing));
    }
    env::join_paths(paths).map_err(|error| format!("could not build PYTHONPATH: {error}"))
}

fn start_core(inner: &mut DesktopInner) -> Result<(), String> {
    if inner.child.is_some() {
        return Ok(());
    }
    let port = free_loopback_port()?;
    let api_url = format!("http://127.0.0.1:{port}");
    inner.api_base_url = api_url;
    inner.core_status = "starting".into();
    inner.error = None;

    let python = env::var("ELEPHANT_DESKTOP_PYTHON").unwrap_or_else(|_| "python3".into());
    let python_path = python_module_path(&inner.repo_root)?;
    let log_path = inner.herd_dir.join("desktop-core.log");
    let mut log_file = OpenOptions::new()
        .create(true)
        .append(true)
        .open(&log_path)
        .map_err(|error| format!("could not open core log: {error}"))?;
    let log_error = log_file
        .try_clone()
        .map_err(|error| format!("could not prepare core log: {error}"))?;
    let _ = writeln!(log_file, "\n--- Elephant desktop core launch ---");
    let child = Command::new(python)
        .arg("-m")
        .arg("apps.api")
        .arg("--host")
        .arg("127.0.0.1")
        .arg("--port")
        .arg(port.to_string())
        .arg("--database")
        .arg(&inner.database_path)
        .current_dir(&inner.repo_root)
        .env("ELEPHANT_HOME", &inner.elephant_home)
        .env("ELEPHANT_HERD_DIR", &inner.herd_dir)
        .env("PYTHONPATH", python_path)
        .stdout(Stdio::from(log_file))
        .stderr(Stdio::from(log_error))
        .spawn()
        .map_err(|error| {
            format!(
                "could not launch python core: {error}; see {}",
                log_path.display()
            )
        })?;
    inner.child = Some(child);

    match wait_for_core(port) {
        Ok(()) => {
            inner.core_status = "ready".into();
            Ok(())
        }
        Err(error) => {
            if let Some(mut child) = inner.child.take() {
                let _ = child.kill();
                let _ = child.wait();
            }
            inner.core_status = "error".into();
            inner.error = Some(error.clone());
            Err(error)
        }
    }
}

#[tauri::command]
fn desktop_api_base_url(state: State<'_, DesktopState>) -> String {
    state.status().api_url
}

#[tauri::command]
fn desktop_core_status(state: State<'_, DesktopState>) -> DesktopCoreStatus {
    state.status()
}

#[tauri::command]
fn desktop_restart_core(
    _app: AppHandle,
    state: State<'_, DesktopState>,
) -> Result<DesktopCoreStatus, String> {
    let mut inner = state
        .inner
        .lock()
        .map_err(|_| "desktop state poisoned".to_string())?;
    stop_core(&mut inner);
    if let Err(error) = start_core(&mut inner) {
        inner.error = Some(error.clone());
        return Err(error);
    }
    Ok(status_from_inner(&inner))
}

#[tauri::command]
fn desktop_pick_source_paths() -> Result<Vec<String>, String> {
    #[cfg(target_os = "macos")]
    {
        let script = r#"
set outputPaths to {}
try
  set chosenFolders to choose folder with prompt "Choose source folders for Elephant" with multiple selections allowed
  repeat with itemRef in chosenFolders
    set end of outputPaths to POSIX path of itemRef
  end repeat
on error number -128
  try
    set chosenFiles to choose file with prompt "Choose source files for Elephant" with multiple selections allowed
    repeat with itemRef in chosenFiles
      set end of outputPaths to POSIX path of itemRef
    end repeat
  on error number -128
  end try
end try
set AppleScript's text item delimiters to linefeed
return outputPaths as text
"#;
        let output = Command::new("osascript")
            .arg("-e")
            .arg(script)
            .output()
            .map_err(|error| format!("could not open macOS picker: {error}"))?;
        if !output.status.success() {
            return Ok(Vec::new());
        }
        let text = String::from_utf8_lossy(&output.stdout);
        Ok(text
            .lines()
            .map(str::trim)
            .filter(|line| !line.is_empty())
            .map(str::to_string)
            .collect())
    }
    #[cfg(not(target_os = "macos"))]
    {
        Ok(Vec::new())
    }
}

#[tauri::command]
fn desktop_reveal_path(path: String) -> Result<(), String> {
    #[cfg(target_os = "macos")]
    {
        Command::new("open")
            .arg("-R")
            .arg(path)
            .status()
            .map_err(|error| format!("could not reveal path: {error}"))?;
        return Ok(());
    }
    #[cfg(not(target_os = "macos"))]
    {
        let _ = path;
        Ok(())
    }
}

fn show_main_window(app: &AppHandle, route: Option<&str>) {
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.show();
        let _ = window.set_focus();
        if let Some(route) = route {
            let script = format!("window.location.hash = '#{}';", route);
            let _ = window.eval(script);
        }
    }
}

fn stop_managed_core(app: &AppHandle) {
    let state = app.state::<DesktopState>();
    let Ok(mut inner) = state.inner.lock() else {
        return;
    };
    stop_core(&mut inner);
}

fn install_menu(app: &AppHandle) -> tauri::Result<()> {
    let elephant_menu = SubmenuBuilder::new(app, "Elephant")
        .text("open_elephant", "Open Elephant")
        .text("new_wake", "New Wake")
        .text("run_reflect", "Run Reflect")
        .text("import_source", "Import Source")
        .separator()
        .text("quit_elephant", "Quit Elephant")
        .build()?;
    let menu = MenuBuilder::new(app).item(&elephant_menu).build()?;
    app.set_menu(menu)?;
    app.on_menu_event(|app, event| match event.id().as_ref() {
        "open_elephant" => show_main_window(app, None),
        "new_wake" => show_main_window(app, Some("/wake")),
        "import_source" => show_main_window(app, Some("/sources")),
        "run_reflect" => {
            show_main_window(app, Some("/reflect"));
            let api_base_url = app.state::<DesktopState>().status().api_url;
            std::thread::spawn(move || {
                let _ = local_http_post(
                    &api_base_url,
                    "/v1/internal/reflect/run",
                    r#"{"trigger":"manual","features":"dream,diary"}"#,
                );
            });
        }
        "quit_elephant" => {
            stop_managed_core(app);
            app.exit(0);
        }
        _ => {}
    });
    Ok(())
}

fn main() {
    tauri::Builder::default()
        .setup(|app| {
            let app_data_dir = app
                .path()
                .app_data_dir()
                .map_err(|error| format!("could not resolve app data dir: {error}"))?;
            let resource_dir = app.path().resource_dir().ok();
            let (elephant_home, herd_dir, database_path) = resolve_data_paths(app_data_dir)?;
            let repo_root = resolve_python_root(resource_dir);
            app.manage(DesktopState {
                inner: Mutex::new(DesktopInner {
                    api_base_url: String::new(),
                    core_status: "stopped".into(),
                    database_path,
                    elephant_home,
                    herd_dir,
                    repo_root,
                    child: None,
                    error: None,
                }),
            });
            let state = app.state::<DesktopState>();
            {
                let mut inner = state
                    .inner
                    .lock()
                    .map_err(|_| "desktop state poisoned".to_string())?;
                if let Err(error) = start_core(&mut inner) {
                    inner.error = Some(error);
                }
            }
            install_menu(app.handle()).map_err(|error| error.to_string())?;

            if let Some(window) = app.get_webview_window("main") {
                let window_for_event = window.clone();
                window.on_window_event(move |event| {
                    if let WindowEvent::CloseRequested { api, .. } = event {
                        api.prevent_close();
                        let _ = window_for_event.hide();
                    }
                });
            }
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            desktop_api_base_url,
            desktop_core_status,
            desktop_restart_core,
            desktop_pick_source_paths,
            desktop_reveal_path
        ])
        .build(tauri::generate_context!())
        .expect("error while building Elephant Desktop")
        .run(|app_handle, event| {
            if matches!(event, RunEvent::ExitRequested { .. } | RunEvent::Exit) {
                stop_managed_core(app_handle);
            }
        });
}
