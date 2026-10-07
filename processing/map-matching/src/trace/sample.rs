//! Beobachtungen entlang eines TILDA-Wegs erzeugen.

use crate::config::TraceConfig;
use crate::model::{Observation, TildaWay};

/// Punkte alle `sample_interval_m` plus immer Anfang und Ende des Wegs.
/// `offset` ist die Position des Wegs innerhalb der Trace.
pub fn sample_way(way: &TildaWay, offset: f64, cfg: &TraceConfig) -> Vec<Observation> {
    let len = way.line.length();
    let n = (len / cfg.sample_interval_m).ceil().max(1.0) as usize;
    let step = len / n as f64;
    (0..=n)
        .map(|i| {
            let s = if i == n { len } else { i as f64 * step };
            Observation {
                p: way.line.point_at(s),
                heading: way.line.heading_at(s, cfg.heading_window_m),
                way: way.idx,
                trace_s: offset + s,
            }
        })
        .collect()
}
