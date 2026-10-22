// 全局快捷键（T5-07）：显隐 / 穿透 / 按住说话。
//
// 快捷键在 Rust 侧注册；语音按键通过 eval 调用前端半双工入口，
// 保证"前端只表现、后端只决策"的边界不被破坏。

use std::sync::atomic::Ordering;

use tauri::{AppHandle, Manager};
use tauri_plugin_global_shortcut::{Code, GlobalShortcutExt, Modifiers, Shortcut, ShortcutState};

use crate::{tray::UiState, window};

pub fn setup(app: &AppHandle) -> Result<(), String> {
    let toggle = Shortcut::new(Some(Modifiers::CONTROL | Modifiers::SHIFT), Code::KeyM);
    app.global_shortcut()
        .on_shortcut(toggle, |app, _shortcut, event| {
            if event.state() == ShortcutState::Pressed {
                if let Some(window) = app.get_webview_window("pet") {
                    let visible = window.is_visible().unwrap_or(false);
                    if visible {
                        let _ = window.hide();
                    } else {
                        let _ = window.show();
                        let _ = window.set_focus();
                    }
                }
            }
        })
        .map_err(|err| err.to_string())?;

    let through = Shortcut::new(Some(Modifiers::CONTROL | Modifiers::SHIFT), Code::KeyT);
    app.global_shortcut()
        .on_shortcut(through, |app, _shortcut, event| {
            if event.state() != ShortcutState::Pressed {
                return;
            }
            let state = app.state::<UiState>();
            let value = !state.click_through.load(Ordering::SeqCst);
            state.click_through.store(value, Ordering::SeqCst);
            if let Some(window) = app.get_webview_window("pet") {
                let _ = window::apply_click_through(&window, value);
            }
        })
        .map_err(|err| err.to_string())?;

    let voice = Shortcut::new(Some(Modifiers::CONTROL | Modifiers::SHIFT), Code::Space);
    app.global_shortcut()
        .on_shortcut(voice, |app, _shortcut, event| {
            if let Some(window) = app.get_webview_window("pet") {
                match event.state() {
                    ShortcutState::Pressed => {
                        let _ = window.eval("window.mochi?.startVoiceFromShortcut?.();");
                    }
                    ShortcutState::Released => {
                        let _ = window.eval("window.mochi?.stopVoiceFromShortcut?.();");
                    }
                }
            }
        })
        .map_err(|err| err.to_string())?;
    Ok(())
}
