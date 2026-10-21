// S2：窗口形态（透明/置顶/拖拽/位置记忆）由 window.rs 提供命令，前端经 ShellAdapter 调用。
// 窗口以 visible=false 启动，前端模型加载完成后再 show_window，避免白闪（计划书 5.7.2）。
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod window;

use tauri::Manager;

fn main() {
    tauri::Builder::default()
        .invoke_handler(tauri::generate_handler![
            window::set_always_on_top,
            window::set_click_through,
            window::start_dragging,
            window::set_position,
            window::get_position,
            window::show_window,
            window::hide_window,
            window::minimize_to_tray,
            window::quit_app,
            window::set_autostart,
        ])
        .setup(|app| {
            if let Some(window) = app.get_webview_window("pet") {
                // 置顶是桌宠的默认形态；配置里已声明，这里兜底一次（防止系统重置）
                let _ = window.set_always_on_top(true);
            }
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running Mochi");
}
