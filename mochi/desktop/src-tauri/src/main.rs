// S5：边车托管、托盘、全局快捷键、单实例。
// 窗口以 visible=false 启动；边车健康后导航到 index.html?port=&token=，
// 前端拿到本次启动的动态端口与随机 token（S5-09）。
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod shortcuts;
mod sidecar;
mod tray;
mod window;

use std::io;
use tauri::{Manager, RunEvent};
use tauri_plugin_autostart::MacosLauncher;

fn main() {
    let app = tauri::Builder::default()
        // single-instance 必须是第一个插件；二次启动聚焦已有窗口
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            if let Some(window) = app.get_webview_window("pet") {
                let _ = window.show();
                let _ = window.set_focus();
            }
        }))
        .plugin(tauri_plugin_autostart::init(
            MacosLauncher::LaunchAgent,
            None,
        ))
        .plugin(tauri_plugin_global_shortcut::Builder::new().build())
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
            window::get_autostart,
        ])
        .setup(|app| {
            let manager = sidecar::BackendManager::start(app.handle().clone())
                .map_err(|err| io::Error::new(io::ErrorKind::Other, err))?;
            let port = manager.port;
            let token = manager.token.clone();
            app.manage(manager);
            tray::setup(app)?;
            if let Some(window) = app.get_webview_window("pet") {
                let hidden = window.clone();
                window.on_window_event(move |event| {
                    if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                        api.prevent_close();
                        let _ = hidden.hide();
                    }
                });
            }
            shortcuts::setup(app.handle())
                .map_err(|err| io::Error::new(io::ErrorKind::Other, err))?;

            let handle = app.handle().clone();
            std::thread::spawn(move || {
                let ready = sidecar::wait_health(port, sidecar::HEALTH_TIMEOUT);
                eprintln!("[sidecar] ready={ready} port={port}");
                if let Some(window) = handle.get_webview_window("pet") {
                    // 无论是否就绪都导航：前端会用正确端口持续重连，
                    // 边车重启后无需再次导航。
                    let js = format!(
                        "window.location.replace('index.html?port={port}&token={token}');"
                    );
                    let _ = window.eval(&js);
                }
            });
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building Mochi");

    app.run(|handle, event| {
        if let RunEvent::Exit = event {
            if let Some(manager) = handle.try_state::<sidecar::BackendManager>() {
                manager.shutdown();
            }
        }
    });
}
