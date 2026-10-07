//! Implementierung der CLI-Befehle.

use std::path::{Path, PathBuf};
use std::time::Instant;

use anyhow::{Context, Result, bail};
use tracing::{info, warn};

use crate::config::Config;
use crate::eval::report::{self, ReportMeta};
use crate::eval::{self, EvalResult, LinSeg, LoadStats, ManualLists};
use crate::hmm;
use crate::io::{self, GeomType};
use crate::pipeline::{self, Prepared, RunOptions};
use crate::trace;

/// `run`: vollständiger Lauf, optional mit Debug-Layern und direkter Evaluation.
pub fn run(cfg: &Config, opts: &RunOptions, evaluate: bool) -> Result<()> {
    let t0 = Instant::now();
    let p = pipeline::prepare(cfg, opts)?;
    let mut r = pipeline::match_and_assemble(&p, cfg, true);
    let out_dir = cfg.output_dir();
    let path = pipeline::output_path(cfg, &p.suffix);
    let t = Instant::now();
    pipeline::write_output(&p, cfg, &r.assembled.segments, &path)?;
    crate::debug::write_matched_ways(&p, &r, &out_dir.join(format!("matched_tilda_ways{}.fgb", p.suffix)))?;
    if opts.debug {
        crate::debug::write_layers(&p, &r, &out_dir.join(format!("debug{}", p.suffix)))?;
    }
    r.stats.timings_s.insert("schreiben".into(), t.elapsed().as_secs_f64());
    r.stats.timings_s.insert("gesamt".into(), t0.elapsed().as_secs_f64());
    log_stats(&r.stats);
    std::fs::write(out_dir.join(format!("stats{}.json", p.suffix)), serde_json::to_string_pretty(&r.stats)?)?;
    if evaluate {
        let cand = pipeline::to_linseg(&p, cfg, &r.assembled.segments, &cfg.eval.attributes);
        let label = path.display().to_string();
        evaluate_against(cfg, &p, &cand, &label, false)?;
        evaluate_against(cfg, &p, &cand, &label, true)?;
    }
    info!("Fertig in {:.1} s", t0.elapsed().as_secs_f64());
    Ok(())
}

fn log_stats(s: &pipeline::RunStats) {
    info!(
        "Traces: {} ({} mit Kandidaten, {} gematcht) | Beobachtungen: {} (ohne Kandidat: {}, Null-Zustand: {}) | HMM-Brüche: {}",
        s.traces, s.traces_with_candidates, s.traces_matched, s.observations, s.observations_without_candidates, s.observations_null_state, s.hmm_breaks
    );
    info!(
        "Intervalle: {} | Teilsegmente: {} (ohne Radinfra: {}) | Konflikte: {} | Einbahn-Kanten: {}",
        s.intervals, s.segments, s.segments_without_infra, s.conflicts, s.oneway_edges
    );
    for (f, km) in &s.length_by_fuehr_km {
        info!("  {f}: {km:.1} km");
    }
}

fn reference_layers(path: &Path, secondary: bool) -> Result<Vec<String>> {
    if secondary {
        let names = io::layer_names(path)?;
        let wanted: Vec<String> = names.into_iter().filter(|n| n == "hinrichtung" || n == "gegenrichtung").collect();
        if wanted.is_empty() {
            bail!("{}: Ebenen hinrichtung/gegenrichtung fehlen", path.display());
        }
        Ok(wanted)
    } else {
        Ok(Vec::new())
    }
}

/// Lädt die Referenz (primär oder sekundär) in linearer Referenz.
pub fn load_reference(cfg: &Config, p: &Prepared, secondary: bool, path: Option<&Path>) -> Result<(PathBuf, Vec<LinSeg>, LoadStats)> {
    let path = path.map(Path::to_path_buf).unwrap_or_else(|| {
        cfg.resolve(if secondary { &cfg.paths.reference_secondary } else { &cfg.paths.reference })
    });
    let layers = reference_layers(&path, secondary)?;
    let (segs, stats) = eval::load_linear(&path, &layers, &p.net, &cfg.eval.attributes, cfg.eval.max_projection_distance_m)?;
    Ok((path, segs, stats))
}

fn evaluate_against(cfg: &Config, p: &Prepared, cand: &[LinSeg], cand_label: &str, secondary: bool) -> Result<EvalResult> {
    let (ref_path, reference, stats) = load_reference(cfg, p, secondary, None)?;
    let manual = ManualLists::load(cfg);
    let res = eval::compare(&p.net, &cfg.eval.attributes, &reference, cand, &manual, &cfg.assemble.no_infra_fuehr);
    let name = if secondary { "sekundaer_aggregiert" } else { "primaer_snapping" };
    let dir = cfg.output_dir().join(format!("evaluation{}", p.suffix)).join(name);
    let title = if secondary {
        "Evaluation gegen aggregated_rvn_final (inkl. Konvertierung & Overrides des Altverfahrens)"
    } else {
        "Evaluation gegen snapping_network_enriched (gleiche Pipeline-Stufe)"
    };
    let note = "Die manuellen Listen (include/exclude/override/opposite_edge) werden im neuen Verfahren nicht verwendet.";
    let meta = ReportMeta { title, reference: &ref_path, candidate: cand_label, ref_stats: &stats, note };
    report::write_all(&dir, &p.net, &res, &meta)?;
    info!("Bericht: {}", dir.join("report.md").display());
    Ok(res)
}

/// `eval`: vergleicht eine vorhandene Ergebnisdatei mit der Referenz.
pub fn eval_file(cfg: &Config, opts: &RunOptions, candidate: Option<PathBuf>, reference: Option<PathBuf>, secondary: bool) -> Result<()> {
    let p = pipeline::prepare_network_only(cfg, opts)?;
    let cand_path = candidate.unwrap_or_else(|| pipeline::output_path(cfg, &p.suffix));
    let (cand, _) = eval::load_linear(&cand_path, &[], &p.net, &cfg.eval.attributes, cfg.eval.max_projection_distance_m)?;
    let (ref_path, reference, stats) = load_reference(cfg, &p, secondary, reference.as_deref())?;
    let manual = ManualLists::load(cfg);
    let res = eval::compare(&p.net, &cfg.eval.attributes, &reference, &cand, &manual, &cfg.assemble.no_infra_fuehr);
    let dir = cfg.output_dir().join(format!("evaluation{}", p.suffix)).join(if secondary { "sekundaer_aggregiert" } else { "primaer_snapping" });
    let label = cand_path.display().to_string();
    let meta = ReportMeta { title: "Evaluation", reference: &ref_path, candidate: &label, ref_stats: &stats, note: "" };
    report::write_all(&dir, &p.net, &res, &meta)?;
    println!("{}", report::markdown(&res, &meta));
    Ok(())
}

/// `topology`: nur den Topologie-Report des RVN erzeugen.
pub fn topology(cfg: &Config, opts: &RunOptions) -> Result<()> {
    let p = pipeline::prepare_network_only(cfg, opts)?;
    let dir = cfg.output_dir();
    let path = dir.join(format!("topology_report{}.fgb", p.suffix));
    io::write_fgb(&path, "topologie", GeomType::Point, &crate::network::topology::TopologyReport::fgb_fields(), p.net.topology.fgb_rows())?;
    std::fs::write(dir.join(format!("topology_report{}.json", p.suffix)), serde_json::to_string_pretty(&p.net.topology)?)?;
    info!("Topologie-Report: {}", path.display());
    Ok(())
}

/// `debug-trace`: vollständiges Viterbi-Gitter für einzelne TILDA-Wege.
pub fn debug_trace(cfg: &Config, opts: &RunOptions) -> Result<()> {
    if opts.tilda_ids.is_empty() {
        bail!("--tilda-id angeben");
    }
    let p = pipeline::prepare(cfg, opts)?;
    let traces = trace::build_traces(cfg, &p.ways);
    let dir = cfg.output_dir().join("debug");
    std::fs::create_dir_all(&dir)?;
    for t in &traces {
        let m = hmm::match_trace(&p.net, &p.ways, &cfg.hmm, t, true);
        let json = crate::debug::trace_json(&p, cfg, t, &m);
        let name = p.ways[t.ways[0] as usize].tilda_id.replace(['/', '#'], "_");
        let path = dir.join(format!("trace_{name}.json"));
        std::fs::write(&path, serde_json::to_string_pretty(&json)?)?;
        info!("Viterbi-Gitter: {} ({} Beobachtungen, {} Intervalle)", path.display(), t.obs.len(), m.intervals.len());
    }
    Ok(())
}

/// `tune`: Parametergitter (TOML: `[grid] "hmm.beta_m" = [2.0, 4.0]`) durchrechnen.
/// Daten und Referenz werden nur einmal geladen.
pub fn tune(cfg: &Config, opts: &RunOptions, grid_path: &Path) -> Result<()> {
    let text = std::fs::read_to_string(grid_path).with_context(|| format!("Grid nicht lesbar: {}", grid_path.display()))?;
    let v: toml::Table = toml::from_str(&text)?;
    let grid = v.get("grid").and_then(|g| g.as_table()).context("Abschnitt [grid] fehlt")?;
    let mut combos: Vec<Vec<String>> = vec![Vec::new()];
    for (key, vals) in grid {
        let vals = vals.as_array().with_context(|| format!("{key}: Liste erwartet"))?;
        combos = combos
            .into_iter()
            .flat_map(|c| {
                vals.iter().map(move |val| {
                    let mut c = c.clone();
                    c.push(format!("{key}={val}"));
                    c
                })
            })
            .collect();
    }
    info!("Tuning: {} Kombinationen", combos.len());
    let p = pipeline::prepare(cfg, opts)?;
    let (_, reference, _) = load_reference(cfg, &p, false, None)?;
    let manual = ManualLists::load(cfg);
    let mut rows = Vec::new();
    for (i, combo) in combos.iter().enumerate() {
        let c = match cfg.with_overrides(combo) {
            Ok(c) => c,
            Err(e) => {
                warn!("Kombination {combo:?} ungültig: {e}");
                continue;
            }
        };
        let t = Instant::now();
        let r = pipeline::match_and_assemble(&p, &c, false);
        let cand = pipeline::to_linseg(&p, &c, &r.assembled.segments, &c.eval.attributes);
        let res = eval::compare(&p.net, &c.eval.attributes, &reference, &cand, &manual, &c.assemble.no_infra_fuehr);
        info!(
            "[{}/{}] {:?}: fuehr {:.2} %, tilda_id {:.2} %, Abdeckung {:.1} % ({:.1} s)",
            i + 1,
            combos.len(),
            combo,
            res.fuehr_score(),
            res.attr_score("tilda_id"),
            eval::pct(res.both_m, res.reference_m),
            t.elapsed().as_secs_f64()
        );
        rows.push((combo.join(" "), res.fuehr_score(), res.attr_score("tilda_id"), eval::pct(res.both_m, res.reference_m)));
    }
    rows.sort_by(|a, b| b.1.total_cmp(&a.1));
    let mut csv = String::from("parameter;fuehr_prozent;tilda_id_prozent;abdeckung_prozent\n");
    for (c, f, t, a) in &rows {
        csv.push_str(&format!("{c};{f:.3};{t:.3};{a:.3}\n"));
    }
    let dir = cfg.output_dir().join("tuning");
    std::fs::create_dir_all(&dir)?;
    let path = dir.join(format!("tune{}_{}.csv", p.suffix, chrono::Local::now().format("%Y%m%d_%H%M%S")));
    std::fs::write(&path, csv)?;
    if let Some(best) = rows.first() {
        info!("Bestes Ergebnis: {} -> fuehr {:.2} %", best.0, best.1);
    }
    info!("Tuning-Ergebnis: {}", path.display());
    Ok(())
}
