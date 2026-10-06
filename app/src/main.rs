//! treedit in a native window.
//!
//!     treedit-app --url URL     # show a running treedit server (what `treedit open` does)
//!     treedit-app [ROOT]        # start `treedit open --headless` itself; stop it when the window closes
//!                               # (TREEDIT_BIN overrides the treedit executable, default `treedit` on PATH)
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::net::{TcpListener, TcpStream};
use std::process::{exit, Child, Command};
use std::sync::Mutex;
use std::thread::sleep;
use std::time::{Duration, Instant};

use tauri::{Manager, RunEvent, WebviewUrl, WebviewWindowBuilder};

struct Server(Mutex<Option<Child>>);

fn free_port() -> u16 {
    TcpListener::bind("127.0.0.1:0")
        .and_then(|l| l.local_addr())
        .map(|a| a.port())
        .unwrap_or(8765)
}

fn start_server(bin: &str, root: &str, port: u16) -> Child {
    let mut child = Command::new(bin)
        .args(["open", root, "--headless", "-p", &port.to_string()])
        .env("TREEDIT_IN_APP", "1")
        .spawn()
        .unwrap_or_else(|e| {
            eprintln!("treedit-app: cannot start {bin}: {e}");
            exit(1)
        });
    let deadline = Instant::now() + Duration::from_secs(15);
    while TcpStream::connect(("127.0.0.1", port)).is_err() {
        if let Ok(Some(status)) = child.try_wait() {
            eprintln!("treedit-app: {bin} exited early ({status})");
            exit(status.code().unwrap_or(1));
        }
        if Instant::now() > deadline {
            let _ = child.kill();
            eprintln!("treedit-app: server did not come up on port {port}");
            exit(1);
        }
        sleep(Duration::from_millis(100));
    }
    child
}

fn main() {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let (url, child) = match args.as_slice() {
        [flag, url] if flag == "--url" => (url.clone(), None),
        _ => {
            let root = args.first().cloned().unwrap_or_else(|| ".".into());
            let bin = std::env::var("TREEDIT_BIN").unwrap_or_else(|_| "treedit".into());
            let port = free_port();
            let child = start_server(&bin, &root, port);
            (format!("http://127.0.0.1:{port}/"), Some(child))
        }
    };
    let url = url.parse().unwrap_or_else(|e| {
        eprintln!("treedit-app: bad url {url}: {e}");
        exit(2)
    });

    tauri::Builder::default()
        .manage(Server(Mutex::new(child)))
        .setup(move |app| {
            WebviewWindowBuilder::new(app, "main", WebviewUrl::External(url))
                .title("treedit")
                .icon(tauri::include_image!("icons/icon.png"))?
                .inner_size(1400.0, 900.0)
                .build()?;
            // when the server we started exits (Ctrl+W / Ctrl+Q in the page), close the window too
            let handle = app.handle().clone();
            std::thread::spawn(move || loop {
                sleep(Duration::from_millis(300));
                let state = handle.state::<Server>();
                let mut guard = state.0.lock().unwrap();
                let Some(child) = guard.as_mut() else { break };
                if !matches!(child.try_wait(), Ok(None)) {
                    guard.take();
                    drop(guard);
                    handle.exit(0);
                    break;
                }
            });
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building treedit-app")
        .run(|app, event| {
            if let RunEvent::Exit = event {
                if let Some(mut c) = app.state::<Server>().0.lock().unwrap().take() {
                    let _ = c.kill();
                    let _ = c.wait();
                }
            }
        });
}
