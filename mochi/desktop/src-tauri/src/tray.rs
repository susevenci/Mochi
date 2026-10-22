// 系统托盘（T5-04）：显示/隐藏、置顶、穿透、设置、退出。
//
// 关闭窗口不退出进程；只有托盘"退出"才结束边车。

use std::sync::atomic::{AtomicBool, Ordering};

use tauri::{
    menu::{MenuBuilder, MenuItemBuilder},
    tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent},
    App, AppHandle, Manager,
};

use crate::window;

#[derive(Default)]
pub struct UiState {
    pub always_on_top: AtomicBool,
    pub click_through: AtomicBool,
}

fn show_pet(app: &AppHandle) {
    if let Some(window) = app.get_webview_window("pet") {
        let _ = window.show();
        let _ = window.set_focus();
    }
}

fn hide_pet(app: &AppHandle) {
    if let Some(window) = app.get_webview_window("pet") {
        let _ = window.hide();
    }
}

fn toggle_top(app: &AppHandle) {
    let state = app.state::<UiState>();
    let value = !state.always_on_top.load(Ordering::SeqCst);
    state.always_on_top.store(value, Ordering::SeqCst);
    if let Some(window) = app.get_webview_window("pet") {
        let _ = window.set_always_on_top(value);
    }
}

fn toggle_through(app: &AppHandle) {
    let state = app.state::<UiState>();
    let value = !state.click_through.load(Ordering::SeqCst);
    state.click_through.store(value, Ordering::SeqCst);
    if let Some(window) = app.get_webview_window("pet") {
        let _ = window::apply_click_through(&window, value);
    }
}

pub fn setup(app: &mut App) -> tauri::Result<()> {
    app.manage(UiState::default());
    let show = MenuItemBuilder::with_id("show", "显示桌宠").build(app)?;
    let hide = MenuItemBuilder::with_id("hide", "隐藏桌宠").build(app)?;
    let top = MenuItemBuilder::with_id("top", "切换置顶").build(app)?;
    let through = MenuItemBuilder::with_id("through", "切换点击穿透（右下热区唤回）").build(app)?;
    let settings = MenuItemBuilder::with_id("settings", "设置…").build(app)?;
    let quit = MenuItemBuilder::with_id("quit", "退出 Mochi").build(app)?;
    let menu = MenuBuilder::new(app)
        .item(&show)
        .item(&hide)
        .separator()
        .item(&top)
        .item(&through)
        .separator()
        .item(&settings)
        .item(&quit)
        .build()?;

    let mut builder = TrayIconBuilder::new()
        .tooltip("Mochi · 桌面伙伴")
        .menu(&menu)
        .show_menu_on_left_click(false)
        .on_menu_event(|app, event| match event.id().as_ref() {
            "show" => show_pet(app),
            "hide" => hide_pet(app),
            "top" => toggle_top(app),
            "through" => toggle_through(app),
            "settings" => {
                show_pet(app);
                if let Some(window) = app.get_webview_window("pet") {
                    let _ = window.eval("window.mochi?.openSettings?.();");
                }
            }
            "quit" => app.exit(0),
            _ => {}
        })
        .on_tray_icon_event(|tray, event| {
            if let TrayIconEvent::Click {
                button: MouseButton::Left,
                button_state: MouseButtonState::Up,
                ..
            } = event
            {
                show_pet(tray.app_handle());
            }
        });
    if let Some(icon) = app.default_window_icon() {
        builder = builder.icon(icon.clone());
    }
    builder.build(app)?;
    Ok(())
}
