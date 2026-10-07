use std::path::PathBuf;

use anyhow::{Result, bail};
use clap::{Args, Parser, Subcommand};
use map_matching::config::Config;
use map_matching::pipeline::RunOptions;
use map_matching::{commands, logging};

/// HMM-/Viterbi-Map-Matching von TILDA-Wegen auf das Radvorrangsnetz.
#[derive(Parser)]
#[command(version, about)]
struct Cli {
    /// Konfigurationsdatei
    #[arg(long, global = true, default_value = concat!(env!("CARGO_MANIFEST_DIR"), "/config/default.toml"))]
    config: PathBuf,
    /// Konfigurationswert überschreiben, z. B. --set hmm.beta_m=6
    #[arg(long = "set", global = true)]
    set: Vec<String>,
    #[command(subcommand)]
    cmd: Cmd,
}

#[derive(Args, Clone, Default)]
struct Area {
    /// Regionaler Zuschnitt (neukoelln, norden, sueden)
    #[arg(long)]
    clip: Option<String>,
    /// Rechteck in EPSG:25833: minx,miny,maxx,maxy
    #[arg(long, value_delimiter = ',', num_args = 4)]
    bbox: Option<Vec<f64>>,
}

#[derive(Subcommand)]
enum Cmd {
    /// Matching + Aufteilung, schreibt network_enriched_hmm*.fgb
    Run {
        #[command(flatten)]
        area: Area,
        /// Debug-Layer (Beobachtungen, Intervalle, Konflikte, Brüche, Topologie) schreiben
        #[arg(long)]
        debug: bool,
        /// Nur diese TILDA-IDs verarbeiten
        #[arg(long = "tilda-id")]
        tilda_ids: Vec<String>,
        /// Direkt gegen beide Referenzen evaluieren
        #[arg(long)]
        eval: bool,
    },
    /// Vergleicht eine Ergebnisdatei mit der Referenz
    Eval {
        #[command(flatten)]
        area: Area,
        /// Ergebnisdatei (Standard: Ausgabe des letzten Laufs)
        #[arg(long)]
        candidate: Option<PathBuf>,
        /// Referenzdatei (Standard: paths.reference bzw. paths.reference_secondary)
        #[arg(long)]
        reference: Option<PathBuf>,
        /// Gegen die aggregierte Referenz (hinrichtung/gegenrichtung) vergleichen
        #[arg(long)]
        secondary: bool,
    },
    /// Topologie-Report des RVN
    Topology {
        #[command(flatten)]
        area: Area,
    },
    /// Viterbi-Gitter einzelner TILDA-Wege als JSON
    DebugTrace {
        #[arg(long = "tilda-id", required = true)]
        tilda_ids: Vec<String>,
    },
    /// Parametergitter gegen die Referenz durchrechnen
    Tune {
        #[command(flatten)]
        area: Area,
        /// TOML-Datei mit Abschnitt [grid]
        #[arg(long)]
        grid: PathBuf,
    },
}

fn options(area: &Area, debug: bool, tilda_ids: Vec<String>) -> Result<RunOptions> {
    if area.clip.is_some() && area.bbox.is_some() {
        bail!("--clip und --bbox schließen sich aus");
    }
    Ok(RunOptions {
        clip: area.clip.clone(),
        bbox: area.bbox.as_ref().map(|b| [b[0], b[1], b[2], b[3]]),
        debug,
        tilda_ids,
    })
}

fn main() -> Result<()> {
    let cli = Cli::parse();
    let cfg = Config::load(&cli.config, &cli.set)?;
    let name = match &cli.cmd {
        Cmd::Run { .. } => "run",
        Cmd::Eval { .. } => "eval",
        Cmd::Topology { .. } => "topology",
        Cmd::DebugTrace { .. } => "debug_trace",
        Cmd::Tune { .. } => "tune",
    };
    let _guard = logging::init(&cfg.output_dir().join("logs"), name);
    tracing::info!("Konfiguration: {} (Overrides: {:?})", cli.config.display(), cli.set);
    match cli.cmd {
        Cmd::Run { area, debug, tilda_ids, eval } => commands::run(&cfg, &options(&area, debug, tilda_ids)?, eval),
        Cmd::Eval { area, candidate, reference, secondary } => commands::eval_file(&cfg, &options(&area, false, vec![])?, candidate, reference, secondary),
        Cmd::Topology { area } => commands::topology(&cfg, &options(&area, false, vec![])?),
        Cmd::DebugTrace { tilda_ids } => commands::debug_trace(&cfg, &options(&Area::default(), true, tilda_ids)?),
        Cmd::Tune { area, grid } => commands::tune(&cfg, &options(&area, false, vec![])?, &grid),
    }
}
