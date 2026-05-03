use tauri::{
    menu::{Menu, MenuItem},
    tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent},
    AppHandle, Manager, Runtime,
};
use tauri_plugin_global_shortcut::{Code, GlobalShortcutExt, Modifiers, Shortcut, ShortcutState};
use tauri_plugin_notification::NotificationExt;

#[tauri::command]
fn focus_main<R: Runtime>(app: AppHandle<R>) {
    show_main(&app);
}

#[tauri::command]
fn toggle_companion_cmd<R: Runtime>(app: AppHandle<R>) {
    toggle_companion(&app);
}

#[tauri::command]
fn notify<R: Runtime>(app: AppHandle<R>, title: String, body: String) -> Result<(), String> {
    app.notification()
        .builder()
        .title(title)
        .body(body)
        .show()
        .map_err(|e| e.to_string())
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_notification::init())
        .plugin(
            tauri_plugin_global_shortcut::Builder::new()
                .with_handler(|app, shortcut, event| {
                    if event.state() == ShortcutState::Pressed
                        && shortcut.matches(Modifiers::CONTROL, Code::Space)
                    {
                        toggle_companion(app);
                    }
                })
                .build(),
        )
        .setup(|app| {
            // Hotkey global Ctrl+Space → toggle compagnon
            let shortcut = Shortcut::new(Some(Modifiers::CONTROL), Code::Space);
            app.global_shortcut().register(shortcut)?;

            // Tray icon avec menu
            let show = MenuItem::with_id(app, "show", "Ouvrir Spouet", true, None::<&str>)?;
            let companion = MenuItem::with_id(
                app,
                "companion",
                "Compagnon (Ctrl+Espace)",
                true,
                None::<&str>,
            )?;
            let quit = MenuItem::with_id(app, "quit", "Quitter", true, None::<&str>)?;
            let menu = Menu::with_items(app, &[&show, &companion, &quit])?;

            let _ = TrayIconBuilder::with_id("spouet-tray")
                .menu(&menu)
                .show_menu_on_left_click(false)
                .on_menu_event(|app, event| match event.id.as_ref() {
                    "show" => show_main(app),
                    "companion" => toggle_companion(app),
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
                        show_main(tray.app_handle());
                    }
                })
                .build(app)?;

            Ok(())
        })
        .invoke_handler(tauri::generate_handler![focus_main, toggle_companion_cmd, notify])
        .run(tauri::generate_context!())
        .expect("erreur au démarrage de Spouet");
}

fn show_main<R: Runtime>(app: &AppHandle<R>) {
    if let Some(w) = app.get_webview_window("main") {
        let _ = w.show();
        let _ = w.unminimize();
        let _ = w.set_focus();
    }
}

fn toggle_companion<R: Runtime>(app: &AppHandle<R>) {
    if let Some(w) = app.get_webview_window("companion") {
        match w.is_visible() {
            Ok(true) => {
                let _ = w.hide();
            }
            _ => {
                let _ = w.show();
                let _ = w.set_focus();
            }
        }
    }
}
