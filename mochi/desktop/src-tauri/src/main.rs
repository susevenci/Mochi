// S0 骨架：仅创建窗口。窗口形态（透明/置顶/穿透/拖拽）见 tauri.conf.json 与 S5 的 window.rs。
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    tauri::Builder::default()
        .run(tauri::generate_context!())
        .expect("error while running Mochi");
}
