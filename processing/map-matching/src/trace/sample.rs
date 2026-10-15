//! Beobachtungen entlang eines TILDA-Wegs erzeugen.

use crate::config::TraceConfig;
use crate::geom::reverse_heading;
use crate::model::{Observation, TildaWay};

/// Punkte alle `sample_interval_m` plus immer Anfang und Ende des Wegs.
/// `offset` ist die Position des Wegs innerhalb der Trace, `reversed` durchläuft ihn
/// gegen die Digitalisierungsrichtung (nur für Zweirichtungs-Wege).
pub fn sample_way(way: &TildaWay, offset: f64, reversed: bool, cfg: &TraceConfig) -> Vec<Observation> {
    let len = way.line.length();
    let n = (len / cfg.sample_interval_m).ceil().max(1.0) as usize;
    let step = len / n as f64;
    (0..=n)
        .map(|i| {
            let d = if i == n { len } else { i as f64 * step };
            let s = if reversed { len - d } else { d };
            let heading = way.line.heading_at(s, cfg.heading_window_m);
            Observation {
                p: way.line.point_at(s),
                heading: if reversed { reverse_heading(heading) } else { heading },
                way: way.idx,
                trace_s: offset + d,
            }
        })
        .collect()
}
