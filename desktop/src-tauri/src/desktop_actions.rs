//! Actions bureau natives : énumérer écrans/apps, lancer une application, ouvrir
//! une URL, placer la fenêtre sur un écran donné (best-effort, Windows).
//!
//! Ces commandes sont invoquées par l'agent realtime du frontend en réponse aux
//! demandes `desktop_action` poussées par le backend. Le placement de fenêtre
//! d'apps tierces est best-effort : on retrouve la fenêtre par PID après
//! lancement, ce qui échoue pour les apps relancées via un launcher (PID
//! différent) — on renvoie alors `placed: false` pour que l'IA puisse le dire.

use serde::Serialize;
use tauri::{AppHandle, Manager, Runtime};

#[derive(Serialize, Clone)]
pub struct MonitorInfo {
    pub index: u32,
    pub name: String,
    pub x: i32,
    pub y: i32,
    pub width: u32,
    pub height: u32,
    pub primary: bool,
    pub scale: f64,
}

#[derive(Serialize, Clone)]
pub struct AppInfo {
    pub name: String,
    pub kind: String,
    pub target: String,
}

/// Liste les écrans, ordonnés (principal d'abord puis par position X). L'index
/// renvoyé est 1-based : 1 = écran principal — c'est ce que l'IA manipule.
fn ordered_monitors<R: Runtime>(app: &AppHandle<R>) -> Vec<MonitorInfo> {
    let win = match app.get_webview_window("main") {
        Some(w) => w,
        None => match app.webview_windows().into_values().next() {
            Some(w) => w,
            None => return Vec::new(),
        },
    };
    let primary_pos = win
        .primary_monitor()
        .ok()
        .flatten()
        .map(|m| (m.position().x, m.position().y));
    let monitors = match win.available_monitors() {
        Ok(m) => m,
        Err(_) => return Vec::new(),
    };
    let mut infos: Vec<MonitorInfo> = monitors
        .iter()
        .map(|m| {
            let pos = m.position();
            let size = m.size();
            MonitorInfo {
                index: 0,
                name: m.name().cloned().unwrap_or_default(),
                x: pos.x,
                y: pos.y,
                width: size.width,
                height: size.height,
                primary: primary_pos.map_or(false, |pp| pp == (pos.x, pos.y)),
                scale: m.scale_factor(),
            }
        })
        .collect();
    infos.sort_by(|a, b| b.primary.cmp(&a.primary).then(a.x.cmp(&b.x)));
    for (i, m) in infos.iter_mut().enumerate() {
        m.index = (i + 1) as u32;
    }
    infos
}

fn monitor_rect<R: Runtime>(app: &AppHandle<R>, idx: u32) -> Option<(i32, i32, i32, i32)> {
    ordered_monitors(app)
        .into_iter()
        .find(|m| m.index == idx)
        .map(|m| (m.x, m.y, m.width as i32, m.height as i32))
}

#[tauri::command]
pub fn list_monitors<R: Runtime>(app: AppHandle<R>) -> Result<Vec<MonitorInfo>, String> {
    Ok(ordered_monitors(&app))
}

#[tauri::command]
pub fn list_installed_apps() -> Result<Vec<AppInfo>, String> {
    #[cfg(target_os = "windows")]
    {
        Ok(win::scan_start_menu())
    }
    #[cfg(not(target_os = "windows"))]
    {
        Ok(Vec::new())
    }
}

#[tauri::command]
pub async fn launch_app<R: Runtime>(
    app: AppHandle<R>,
    app_ref: String,
    monitor: Option<u32>,
    mode: Option<String>,
) -> Result<serde_json::Value, String> {
    #[cfg(target_os = "windows")]
    {
        let found = match win::resolve_app(&app_ref) {
            Some(a) => a,
            None => {
                return Ok(serde_json::json!({
                    "status": "app_not_found",
                    "app": app_ref,
                }));
            }
        };
        let pid = win::shell_open(&found.target)?;
        let placed = maybe_place(&app, pid, monitor, mode.as_deref()).await;
        Ok(serde_json::json!({
            "status": "ok",
            "app": found.name,
            "target": found.target,
            "placed": placed,
        }))
    }
    #[cfg(not(target_os = "windows"))]
    {
        let _ = (&app, &app_ref, &monitor, &mode);
        Err("pilotage du PC disponible uniquement sous Windows".into())
    }
}

#[tauri::command]
pub async fn open_url<R: Runtime>(
    app: AppHandle<R>,
    url: String,
    monitor: Option<u32>,
) -> Result<serde_json::Value, String> {
    if !(url.starts_with("http://") || url.starts_with("https://")) {
        return Err("url http(s) requise".into());
    }
    #[cfg(target_os = "windows")]
    {
        let pid = win::shell_open(&url)?;
        let placed = maybe_place(&app, pid, monitor, None).await;
        Ok(serde_json::json!({ "status": "ok", "url": url, "placed": placed }))
    }
    #[cfg(not(target_os = "windows"))]
    {
        let _ = (&app, &monitor);
        Err("pilotage du PC disponible uniquement sous Windows".into())
    }
}

/// Place best-effort la fenêtre du PID sur l'écran demandé / la maximise.
/// Renvoie `Null` si aucun placement demandé, sinon `Bool` (réussi ?).
#[cfg(target_os = "windows")]
async fn maybe_place<R: Runtime>(
    app: &AppHandle<R>,
    pid: u32,
    monitor: Option<u32>,
    mode: Option<&str>,
) -> serde_json::Value {
    let wants_maximize = matches!(mode, Some("maximized") | Some("fullscreen"));
    if pid == 0 || (monitor.is_none() && !wants_maximize) {
        return serde_json::Value::Null;
    }
    let rect = monitor.and_then(|idx| monitor_rect(app, idx));
    let mode_s = mode.unwrap_or("normal").to_string();
    let ok = tauri::async_runtime::spawn_blocking(move || win::find_and_place(pid, rect, &mode_s))
        .await
        .unwrap_or(false);
    serde_json::Value::Bool(ok)
}

// ---------------------------------------------------------------------------
// Implémentation Windows (FFI win32)
// ---------------------------------------------------------------------------

#[cfg(target_os = "windows")]
mod win {
    use super::AppInfo;
    use std::collections::HashSet;
    use std::os::windows::ffi::OsStrExt;
    use std::path::{Path, PathBuf};
    use std::time::{Duration, Instant};

    use windows_sys::Win32::Foundation::{CloseHandle, HWND, LPARAM};
    use windows_sys::Win32::System::Threading::GetProcessId;
    use windows_sys::Win32::UI::Shell::{
        ShellExecuteExW, SEE_MASK_NOCLOSEPROCESS, SHELLEXECUTEINFOW,
    };
    use windows_sys::Win32::UI::WindowsAndMessaging::{
        EnumWindows, GetWindow, GetWindowThreadProcessId, IsWindowVisible, SetForegroundWindow,
        SetWindowPos, ShowWindow, GW_OWNER, SWP_FRAMECHANGED, SWP_NOACTIVATE, SWP_NOZORDER,
        SW_MAXIMIZE, SW_RESTORE,
    };

    fn to_wide(s: &str) -> Vec<u16> {
        std::ffi::OsStr::new(s)
            .encode_wide()
            .chain(std::iter::once(0))
            .collect()
    }

    /// Lance un fichier/URL via le shell (gère .lnk, .exe, URLs). Retourne le PID
    /// du process créé (0 si indisponible, ex. app déjà ouverte).
    pub fn shell_open(file: &str) -> Result<u32, String> {
        let verb_w = to_wide("open");
        let file_w = to_wide(file);
        unsafe {
            let mut info: SHELLEXECUTEINFOW = std::mem::zeroed();
            info.cbSize = std::mem::size_of::<SHELLEXECUTEINFOW>() as u32;
            info.fMask = SEE_MASK_NOCLOSEPROCESS;
            info.lpVerb = verb_w.as_ptr();
            info.lpFile = file_w.as_ptr();
            info.nShow = 1; // SW_SHOWNORMAL
            if ShellExecuteExW(&mut info) == 0 {
                return Err(format!("échec du lancement de « {file} »"));
            }
            if info.hProcess.is_null() {
                Ok(0)
            } else {
                let pid = GetProcessId(info.hProcess);
                CloseHandle(info.hProcess);
                Ok(pid)
            }
        }
    }

    struct FindState {
        pid: u32,
        hwnd: HWND,
    }

    unsafe extern "system" fn enum_proc(hwnd: HWND, lparam: LPARAM) -> i32 {
        let state = &mut *(lparam as *mut FindState);
        let mut wpid: u32 = 0;
        GetWindowThreadProcessId(hwnd, &mut wpid);
        // Fenêtre top-level, visible, sans propriétaire (= fenêtre principale).
        if wpid == state.pid && IsWindowVisible(hwnd) != 0 && GetWindow(hwnd, GW_OWNER).is_null() {
            state.hwnd = hwnd;
            return 0; // stop l'énumération
        }
        1 // continue
    }

    fn find_window(pid: u32, timeout: Duration) -> HWND {
        let start = Instant::now();
        loop {
            let mut state = FindState {
                pid,
                hwnd: std::ptr::null_mut(),
            };
            unsafe {
                EnumWindows(Some(enum_proc), &mut state as *mut FindState as LPARAM);
            }
            if !state.hwnd.is_null() {
                return state.hwnd;
            }
            if start.elapsed() > timeout {
                return std::ptr::null_mut();
            }
            std::thread::sleep(Duration::from_millis(200));
        }
    }

    /// Retrouve la fenêtre du PID puis la positionne / maximise. Best-effort.
    pub fn find_and_place(pid: u32, rect: Option<(i32, i32, i32, i32)>, mode: &str) -> bool {
        let hwnd = find_window(pid, Duration::from_secs(8));
        if hwnd.is_null() {
            return false;
        }
        let hwnd_top: HWND = std::ptr::null_mut(); // HWND_TOP == 0
        unsafe {
            ShowWindow(hwnd, SW_RESTORE);
            if let Some((x, y, w, h)) = rect {
                // On déplace sur l'écran cible (avec une marge) ; un éventuel
                // maximize ensuite s'appliquera à CET écran.
                SetWindowPos(
                    hwnd,
                    hwnd_top,
                    x + 40,
                    y + 40,
                    (w - 80).max(640),
                    (h - 80).max(480),
                    SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED,
                );
            }
            if mode == "maximized" || mode == "fullscreen" {
                ShowWindow(hwnd, SW_MAXIMIZE);
            }
            SetForegroundWindow(hwnd);
        }
        true
    }

    /// Scanne les menus Démarrer (machine + utilisateur) pour les raccourcis
    /// `.lnk`. Le nom affiché = nom du raccourci ; la cible = chemin du `.lnk`
    /// (lançable via le shell).
    pub fn scan_start_menu() -> Vec<AppInfo> {
        let mut roots: Vec<PathBuf> = Vec::new();
        if let Ok(pd) = std::env::var("ProgramData") {
            roots.push(
                PathBuf::from(pd)
                    .join("Microsoft")
                    .join("Windows")
                    .join("Start Menu")
                    .join("Programs"),
            );
        }
        if let Ok(ad) = std::env::var("AppData") {
            roots.push(
                PathBuf::from(ad)
                    .join("Microsoft")
                    .join("Windows")
                    .join("Start Menu")
                    .join("Programs"),
            );
        }
        let mut out: Vec<AppInfo> = Vec::new();
        for root in roots {
            collect_lnks(&root, &mut out, 0);
        }
        // Dédoublonne par nom (insensible à la casse), garde le premier.
        let mut seen: HashSet<String> = HashSet::new();
        out.retain(|a| seen.insert(a.name.to_lowercase()));
        out.sort_by(|a, b| a.name.to_lowercase().cmp(&b.name.to_lowercase()));
        out.truncate(500);
        out
    }

    fn collect_lnks(dir: &Path, out: &mut Vec<AppInfo>, depth: u32) {
        if depth > 5 {
            return;
        }
        let entries = match std::fs::read_dir(dir) {
            Ok(e) => e,
            Err(_) => return,
        };
        for entry in entries.flatten() {
            let path = entry.path();
            if path.is_dir() {
                collect_lnks(&path, out, depth + 1);
            } else if path
                .extension()
                .and_then(|x| x.to_str())
                .map_or(false, |x| x.eq_ignore_ascii_case("lnk"))
            {
                if let Some(stem) = path.file_stem().and_then(|s| s.to_str()) {
                    // Ignore les désinstalleurs et utilitaires bruyants.
                    let low = stem.to_lowercase();
                    if low.contains("uninstall") || low.contains("désinstall") {
                        continue;
                    }
                    out.push(AppInfo {
                        name: stem.to_string(),
                        kind: "shortcut".to_string(),
                        target: path.to_string_lossy().to_string(),
                    });
                }
            }
        }
    }

    /// Résout une référence floue (« curseforge ») vers une app détectée.
    pub fn resolve_app(app_ref: &str) -> Option<AppInfo> {
        let apps = scan_start_menu();
        let needle = app_ref.trim().to_lowercase();
        if needle.is_empty() {
            return None;
        }
        // Correspondance exacte d'abord.
        if let Some(a) = apps.iter().find(|a| a.name.to_lowercase() == needle) {
            return Some(a.clone());
        }
        // Sinon sous-chaîne dans un sens ou l'autre.
        apps.into_iter().find(|a| {
            let n = a.name.to_lowercase();
            n.contains(&needle) || needle.contains(&n)
        })
    }
}
