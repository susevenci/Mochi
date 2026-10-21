// 窗口形态与系统集成（计划书 5.7.3 的 S2 子集）。
//
// 只做"窗口操作"，不含任何业务逻辑：前端经 ShellAdapter 调用这些命令，
// 命令名与 frontend/src/shell/TauriAdapter.ts 一一对应。

use serde::Serialize;
use tauri::{AppHandle, PhysicalPosition, WebviewWindow};

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
#[tauri::command]
pub fn set_click_through(window: WebviewWindow, value: bool) -> Result<(), String> {
    window
        .set_ignore_cursor_events(value)
        .map_err(|err| err.to_string())
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

/// 开机自启由 S5 的 tauri-plugin-autostart 提供；S2 显式返回"未实现"，
/// 避免前端以为设置成功（比静默 no-op 更安全）。
#[tauri::command]
pub fn set_autostart(_value: bool) -> Result<(), String> {
    Err("autostart 尚未实现（计划：S5 接入 tauri-plugin-autostart）".into())
}
