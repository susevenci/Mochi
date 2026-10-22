// 窗口形态与系统集成（计划书 5.7.3 的 S2 子集）。
//
// 只做"窗口操作"，不含任何业务逻辑：前端经 ShellAdapter 调用这些命令，
// 命令名与 frontend/src/shell/TauriAdapter.ts 一一对应。

use std::sync::atomic::{AtomicBool, Ordering};
#[cfg(windows)]
use std::thread;
#[cfg(windows)]
use std::time::Duration;

use serde::Serialize;
use tauri::{AppHandle, PhysicalPosition, WebviewWindow};
use tauri_plugin_autostart::ManagerExt;

#[cfg(windows)]
use windows_sys::Win32::Foundation::POINT;
#[cfg(windows)]
use windows_sys::Win32::UI::WindowsAndMessaging::{GetCursorPos, GetWindowRect};

static HOT_ZONE_ACTIVE: AtomicBool = AtomicBool::new(false);

/// 窗口几何：物理像素 + DPI 缩放 + 所在显示器名（计划书 9.2.3 的"显示器标识 + 坐标"）。
#[derive(Debug, Serialize)]
pub struct WindowGeometry {
    pub x: i32,
    pub y: i32,
    pub scale: f64,
    pub display: Option<String>,
}

#[tauri::command]
pub fn set_always_on_top(window: WebviewWindow, value: bool) -> Result<(), String> {
    window.set_always_on_top(value).map_err(|err| err.to_string())
}

/// 点击穿透：开启后鼠标事件落到下层窗口（S5 会配合热区唤回）。
/// 点击穿透 + 右下热区：穿透时轮询全局光标，进入右下 90px 就临时恢复交互。
pub fn apply_click_through(window: &WebviewWindow, value: bool) -> Result<(), String> {
    if value {
        window
            .set_ignore_cursor_events(true)
            .map_err(|err| err.to_string())?;
        #[cfg(windows)]
        start_hot_zone(window.clone());
        Ok(())
    } else {
        HOT_ZONE_ACTIVE.store(false, Ordering::SeqCst);
        window
            .set_ignore_cursor_events(false)
            .map_err(|err| err.to_string())
    }
}

#[tauri::command]
pub fn set_click_through(window: WebviewWindow, value: bool) -> Result<(), String> {
    apply_click_through(&window, value)
}

#[cfg(windows)]
fn start_hot_zone(window: WebviewWindow) {
    if HOT_ZONE_ACTIVE.swap(true, Ordering::SeqCst) {
        return;
    }
    let hwnd = match window.hwnd() {
        Ok(hwnd) => hwnd.0 as isize,
        Err(_) => {
            HOT_ZONE_ACTIVE.store(false, Ordering::SeqCst);
            return;
        }
    };
    thread::spawn(move || {
        let mut interactive = false;
        while HOT_ZONE_ACTIVE.load(Ordering::SeqCst) {
            unsafe {
                let mut point = POINT { x: 0, y: 0 };
                let mut rect = windows_sys::Win32::Foundation::RECT {
                    left: 0,
                    top: 0,
                    right: 0,
                    bottom: 0,
                };
                if GetCursorPos(&mut point) != 0 && GetWindowRect(hwnd as *mut core::ffi::c_void, &mut rect) != 0 {
                    let hot = point.x >= rect.right - 90
                        && point.x <= rect.right
                        && point.y >= rect.bottom - 90
                        && point.y <= rect.bottom;
                    if hot != interactive {
                        let _ = window.set_ignore_cursor_events(!hot);
                        interactive = hot;
                    }
                }
            }
            thread::sleep(Duration::from_millis(100));
        }
    });
}

/// 拖拽移动窗口：必须在鼠标左键按下时调用（前端 pointerdown → 超过阈值后触发）。
#[tauri::command]
pub fn start_dragging(window: WebviewWindow) -> Result<(), String> {
    window.start_dragging().map_err(|err| err.to_string())
}

#[tauri::command]
pub fn set_position(window: WebviewWindow, x: i32, y: i32) -> Result<(), String> {
    // 前端存的是 ``outer_position()`` 给的物理像素，而 Windows 下的定位接口在这个
    // Tauri/winit 组合上会再除一次 DPI 比例（实测 scale=1.5 时 400 → 267）。
    // 这里先乘回去，保证“存什么、回到什么”。
    let scale = window.scale_factor().map_err(|err| err.to_string())?;
    let physical = PhysicalPosition::new(
        (f64::from(x) * scale).round() as i32,
        (f64::from(y) * scale).round() as i32,
    );
    window
        .set_position(physical)
        .map_err(|err| err.to_string())
}

#[tauri::command]
pub fn get_position(window: WebviewWindow) -> Result<WindowGeometry, String> {
    let position = window.outer_position().map_err(|err| err.to_string())?;
    let scale = window.scale_factor().map_err(|err| err.to_string())?;
    let display = window
        .current_monitor()
        .ok()
        .flatten()
        .and_then(|monitor| monitor.name().cloned());
    Ok(WindowGeometry {
        x: position.x,
        y: position.y,
        scale,
        display,
    })
}

#[tauri::command]
pub fn show_window(window: WebviewWindow) -> Result<(), String> {
    window.show().map_err(|err| err.to_string())?;
    window.set_focus().map_err(|err| err.to_string())
}

#[tauri::command]
pub fn hide_window(window: WebviewWindow) -> Result<(), String> {
    window.hide().map_err(|err| err.to_string())
}

/// S2 没有托盘：最小化即隐藏窗口（S5 换成真正的托盘常驻）。
#[tauri::command]
pub fn minimize_to_tray(window: WebviewWindow) -> Result<(), String> {
    window.hide().map_err(|err| err.to_string())
}

#[tauri::command]
pub fn quit_app(app: AppHandle) {
    app.exit(0);
}

#[tauri::command]
pub fn set_autostart(app: AppHandle, value: bool) -> Result<(), String> {
    let manager = app.autolaunch();
    if value {
        manager.enable().map_err(|err| err.to_string())
    } else {
        manager.disable().map_err(|err| err.to_string())
    }
}

#[tauri::command]
pub fn get_autostart(app: AppHandle) -> Result<bool, String> {
    app.autolaunch().is_enabled().map_err(|err| err.to_string())
}
