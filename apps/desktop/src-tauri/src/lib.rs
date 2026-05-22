use std::process::{Command, Child, Stdio};
use std::sync::Mutex;
use tauri::{Builder, Manager, RunEvent};
use std::path::PathBuf;

#[cfg(target_os = "windows")]
use std::os::windows::process::CommandExt;

// 儲存 Python 背景進程的 State
struct BackendState {
    child: Mutex<Option<Child>>,
}

// 啟動背景 Python 後端服務
fn start_backend() -> Option<Child> {
    // 預設尋找本地 .venv 的 Python 解譯器
    let mut python_path = PathBuf::from("backend/.venv/Scripts/python.exe");
    if !python_path.exists() {
        // 備用：若找不到，尋找類 Unix 或系統全域 python
        python_path = PathBuf::from("backend/.venv/bin/python");
        if !python_path.exists() {
            python_path = PathBuf::from("python");
        }
    }

    let main_py = PathBuf::from("backend/main.py");
    if !main_py.exists() {
        eprintln!("找不到 backend/main.py，無法啟動背景後端");
        return None;
    }

    println!("正在啟動 Python 後端：{:?} {:?}", python_path, main_py);

    let mut cmd = Command::new(python_path);
    cmd.arg(main_py)
       .stdout(Stdio::piped())
       .stderr(Stdio::piped());

    // 在 Windows 上隱藏黑色命令提示字元視窗
    #[cfg(target_os = "windows")]
    {
        const CREATE_NO_WINDOW: u32 = 0x08000000;
        cmd.creation_flags(CREATE_NO_WINDOW);
    }

    match cmd.spawn() {
        Ok(child) => {
            println!("Python 後端啟動成功，PID: {}", child.id());
            Some(child)
        }
        Err(e) => {
            eprintln!("啟動 Python 後端失敗: {}", e);
            None
        }
    }
}

// Learn more about Tauri commands at https://tauri.app/develop/calling-rust/
#[tauri::command]
fn greet(name: &str) -> String {
    format!("Hello, {}! You've been greeted from Rust!", name)
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .invoke_handler(tauri::generate_handler![greet])
        .setup(|app| {
            // 在 Tauri 啟動時自動跑起 FastAPI 後端
            let child = start_backend();
            app.manage(BackendState {
                child: Mutex::new(child),
            });
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while running tauri application");

    app.run(|app_handle, event| match event {
        RunEvent::Exit => {
            // 當桌面程式關閉時，安全釋放並 Kill 掉 Python 進程，避免殘留
            if let Some(state) = app_handle.try_state::<BackendState>() {
                let mut lock = state.child.lock().unwrap();
                if let Some(mut child) = lock.take() {
                    println!("正在終止 Python 後端進程 (PID: {})...", child.id());
                    let _ = child.kill();
                }
            }
        }
        _ => {}
    });
}
