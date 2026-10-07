//! Logging auf Konsole und in eine Datei unter `<output_dir>/logs/`.

use std::path::Path;

use tracing_appender::non_blocking::WorkerGuard;
use tracing_subscriber::layer::SubscriberExt;
use tracing_subscriber::util::SubscriberInitExt;
use tracing_subscriber::{EnvFilter, fmt};

/// Initialisiert das Logging. Level über `RUST_LOG` (Standard: info).
/// Der zurückgegebene Guard muss bis Programmende leben.
pub fn init(log_dir: &Path, command: &str) -> Option<WorkerGuard> {
    let filter = || EnvFilter::try_from_default_env().unwrap_or_else(|_| EnvFilter::new("info"));
    let console = fmt::layer().with_target(false).with_writer(std::io::stderr).with_filter(filter());
    let (file_layer, guard) = match std::fs::create_dir_all(log_dir) {
        Ok(()) => {
            let name = format!("{command}_{}.log", chrono::Local::now().format("%Y%m%d_%H%M%S"));
            let appender = tracing_appender::rolling::never(log_dir, name);
            let (writer, guard) = tracing_appender::non_blocking(appender);
            (Some(fmt::layer().with_ansi(false).with_target(true).with_writer(writer).with_filter(filter())), Some(guard))
        }
        Err(_) => (None, None),
    };
    tracing_subscriber::registry().with(console).with(file_layer).init();
    guard
}

use tracing_subscriber::Layer as _;
