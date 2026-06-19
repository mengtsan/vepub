use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use tauri::{Manager, RunEvent};

#[cfg(target_os = "windows")]
use std::os::windows::process::CommandExt;

// ─── Windows Job Object ───────────────────────────────────────────────────────
// Holds a Win32 Job Object handle. When dropped (= Tauri exits), the OS kills
// every process assigned to the job, including the sidecar and llama-server.exe.

#[cfg(target_os = "windows")]
struct WinJob(windows::Win32::Foundation::HANDLE);

#[cfg(target_os = "windows")]
unsafe impl Send for WinJob {}
#[cfg(target_os = "windows")]
unsafe impl Sync for WinJob {}

#[cfg(target_os = "windows")]
impl Drop for WinJob {
    fn drop(&mut self) {
        unsafe { let _ = windows::Win32::Foundation::CloseHandle(self.0); }
    }
}

#[cfg(target_os = "windows")]
fn create_kill_on_close_job() -> Option<WinJob> {
    use windows::Win32::System::JobObjects::{
        CreateJobObjectW, JobObjectExtendedLimitInformation,
        SetInformationJobObject, JOBOBJECT_EXTENDED_LIMIT_INFORMATION,
        JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE,
    };
    unsafe {
        let job = CreateJobObjectW(None, None).ok()?;
        let mut info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION::default();
        info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
        SetInformationJobObject(
            job,
            JobObjectExtendedLimitInformation,
            &info as *const _ as *const core::ffi::c_void,
            std::mem::size_of::<JOBOBJECT_EXTENDED_LIMIT_INFORMATION>() as u32,
        )
        .ok()?;
        Some(WinJob(job))
    }
}

#[cfg(target_os = "windows")]
fn assign_to_job(job: &WinJob, child: &Child) -> bool {
    use std::os::windows::io::AsRawHandle;
    use windows::Win32::Foundation::HANDLE;
    use windows::Win32::System::JobObjects::AssignProcessToJobObject;
    let h = HANDLE(child.as_raw_handle() as *mut core::ffi::c_void);
    unsafe { AssignProcessToJobObject(job.0, h).is_ok() }
}

// ─── Managed state ───────────────────────────────────────────────────────────

struct BackendState {
    child: Mutex<Option<Child>>,
    #[cfg(target_os = "windows")]
    _job: Option<WinJob>,
}

// ─── Production-only sidecar launch ──────────────────────────────────────────
// In dev mode the backend is managed by `concurrently` (npm run dev),
// so we skip spawning it here entirely.

#[cfg(not(dev))]
fn find_sidecar_exe(app: &tauri::AppHandle) -> Option<PathBuf> {
    let res = app.path().resource_dir().ok()?;
    let exe = res.join("vepub-backend").join("vepub-backend.exe");
    if exe.exists() { Some(exe) } else { None }
}

#[cfg(not(dev))]
fn start_backend(app: &tauri::AppHandle) -> BackendState {
    #[cfg(target_os = "windows")]
    let job = create_kill_on_close_job();

    let child = match find_sidecar_exe(app) {
        Some(exe) => {
            println!("[vepub] sidecar: {:?}", exe);
            let mut cmd = Command::new(&exe);
            cmd.stdout(Stdio::null()).stderr(Stdio::null());
            #[cfg(target_os = "windows")]
            cmd.creation_flags(0x08000000 /* CREATE_NO_WINDOW */);

            match cmd.spawn() {
                Ok(child) => {
                    println!("[vepub] sidecar PID {}", child.id());
                    #[cfg(target_os = "windows")]
                    if let Some(ref j) = job {
                        if assign_to_job(j, &child) {
                            println!("[vepub] assigned to Job Object");
                        }
                    }
                    Some(child)
                }
                Err(e) => {
                    eprintln!("[vepub] sidecar spawn 失敗: {e}");
                    None
                }
            }
        }
        None => {
            eprintln!("[vepub] 找不到 sidecar，請先執行 PyInstaller 打包後端");
            None
        }
    };

    BackendState {
        child: Mutex::new(child),
        #[cfg(target_os = "windows")]
        _job: job,
    }
}

// ─── Entry point ─────────────────────────────────────────────────────────────

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .invoke_handler(tauri::generate_handler![])
        .setup(|app| {
            // Production only: spawn the sidecar.
            // Dev mode: backend is already running via `npm run dev`.
            #[cfg(not(dev))]
            {
                let state = start_backend(app.handle());
                app.manage(state);
            }
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while running tauri application");

    app.run(|handle, event| {
        if let RunEvent::Exit = event {
            #[cfg(not(dev))]
            if let Some(state) = handle.try_state::<BackendState>() {
                let mut lock = state.child.lock().unwrap();
                if let Some(mut child) = lock.take() {
                    println!("[vepub] kill sidecar PID {}…", child.id());
                    let _ = child.kill();
                    let _ = child.wait();
                }
                // _job drops here → OS kills entire process tree
            }
        }
    });
}
