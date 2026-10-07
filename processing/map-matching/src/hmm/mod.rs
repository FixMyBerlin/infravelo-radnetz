//! HMM-Map-Matching einer Trace auf das RVN und Ableitung der Kantenintervalle.

pub mod emission;
pub mod transition;
pub mod viterbi;

use rustc_hash::FxHashMap;
use serde::Serialize;

use crate::config::HmmConfig;
use crate::model::{Candidate, DirEdge, Interval, TildaWay, Trace};
use crate::network::Network;
use crate::network::routing::Router;
use viterbi::{LatticeStep, viterbi};

/// Ergebnis für eine Beobachtung (für Debug-Ausgaben).
#[derive(Debug, Clone, Copy, Serialize)]
pub struct ObsState {
    pub chosen: Option<Candidate>,
    pub n_candidates: u32,
}

#[derive(Debug, Clone, Default)]
pub struct TraceMatch {
    pub trace_id: u32,
    pub intervals: Vec<Interval>,
    pub states: Vec<ObsState>,
    pub breaks: Vec<usize>,
    pub lattice: Option<Vec<LatticeStep>>,
    pub dijkstra_runs: u64,
}

/// Matcht eine Trace. `want_lattice` liefert das vollständige Viterbi-Gitter (debug-trace).
pub fn match_trace(net: &Network, ways: &[TildaWay], cfg: &HmmConfig, trace: &Trace, want_lattice: bool) -> TraceMatch {
    let cands: Vec<Vec<Candidate>> = trace
        .obs
        .iter()
        .map(|o| emission::candidates(net, cfg, &ways[o.way as usize], o))
        .collect();
    if cands.iter().all(Vec::is_empty) {
        return TraceMatch {
            trace_id: trace.id,
            states: cands.iter().map(|_| ObsState { chosen: None, n_candidates: 0 }).collect(),
            ..Default::default()
        };
    }
    let mut router = Router::new(net);
    let vit = viterbi(&mut router, cfg, &trace.obs, &cands, want_lattice);
    let states: Vec<ObsState> = vit
        .path
        .iter()
        .zip(&cands)
        .map(|(p, c)| ObsState { chosen: p.map(|i| c[i]), n_candidates: c.len() as u32 })
        .collect();
    let intervals = derive_intervals(net, ways, cfg, trace, &states, &mut router);
    let mut breaks = vit.breaks;
    breaks.extend(topology_breaks(cfg, trace, &states, &mut router));
    breaks.sort_unstable();
    breaks.dedup();
    TraceMatch {
        trace_id: trace.id,
        intervals,
        states,
        breaks,
        lattice: vit.lattice,
        dijkstra_runs: router.dijkstra_runs,
    }
}

/// HMM-Brüche im gewählten Pfad: Der Pfad wechselt über den Null-Zustand zwischen zwei
/// gematchten Positionen, die im RVN nicht verbunden sind (Topologie-Lücke).
fn topology_breaks(cfg: &HmmConfig, trace: &Trace, states: &[ObsState], router: &mut Router) -> Vec<usize> {
    let mut out = Vec::new();
    let mut last: Option<(usize, Candidate)> = None;
    for (t, st) in states.iter().enumerate() {
        let Some(c) = st.chosen else { continue };
        if let Some((i, a)) = last
            && t > i + 1
            && a.dir != c.dir
        {
            let d_trace = (trace.obs[t].trace_s - trace.obs[i].trace_s).max(0.0);
            let limit = transition::route_limit(cfg, d_trace);
            if router.distance(a.dir, a.s, c.dir, c.s, limit, cfg.backward_tolerance_m).is_none() {
                out.push(i + 1);
            }
        }
        last = Some((t, c));
    }
    out
}

/// Stück (in Fahrtrichtung) einer gerichteten Kante mit Güte.
#[derive(Debug, Clone, Copy)]
struct Piece {
    a: f64,
    b: f64,
    score: f64,
}

/// Wandelt den Viterbi-Pfad in Intervalle je (TILDA-Weg, gerichtete Kante) um.
/// Nur aufeinanderfolgende, gematchte Beobachtungen desselben Wegs erzeugen Intervalle;
/// dazwischen durchfahrene Kanten werden vollständig zugeordnet.
fn derive_intervals(net: &Network, ways: &[TildaWay], cfg: &HmmConfig, trace: &Trace, states: &[ObsState], router: &mut Router) -> Vec<Interval> {
    let mut pieces: FxHashMap<(u32, DirEdge), Vec<Piece>> = FxHashMap::default();
    let mut obs_count: FxHashMap<(u32, DirEdge), u32> = FxHashMap::default();
    for (o, st) in trace.obs.iter().zip(states) {
        if let Some(c) = st.chosen {
            *obs_count.entry((o.way, c.dir)).or_default() += 1;
        }
    }
    for t in 1..trace.obs.len() {
        let (o0, o1) = (&trace.obs[t - 1], &trace.obs[t]);
        let (Some(a), Some(b)) = (states[t - 1].chosen, states[t].chosen) else { continue };
        if o0.way != o1.way {
            continue;
        }
        let score = 0.5 * (a.log_emission + b.log_emission);
        let mut push = |d: DirEdge, x: f64, y: f64| {
            let (lo, hi) = if x <= y { (x, y) } else { (y, x) };
            if hi - lo > 1e-6 {
                pieces.entry((o0.way, d)).or_default().push(Piece { a: lo, b: hi, score });
            }
        };
        if a.dir == b.dir {
            push(a.dir, a.s, b.s);
        } else {
            push(a.dir, a.s, net.dir_len(a.dir));
            let limit = transition::route_limit(cfg, (o1.trace_s - o0.trace_s).max(0.0));
            for mid in router.intermediate(a.dir, b.dir, limit) {
                push(mid, 0.0, net.dir_len(mid));
            }
            push(b.dir, 0.0, b.s);
        }
    }

    let mut out = Vec::new();
    for ((way, dir), mut ps) in pieces {
        ps.sort_by(|x, y| x.a.total_cmp(&y.a));
        let n_obs = obs_count.get(&(way, dir)).copied().unwrap_or(0);
        let mut cur = ps[0];
        let mut acc = (cur.score * (cur.b - cur.a), cur.b - cur.a);
        let flush = |c: Piece, acc: (f64, f64), out: &mut Vec<Interval>| {
            let score = if acc.1 > 0.0 { acc.0 / acc.1 } else { c.score };
            let (f, t) = (net.to_base(dir, c.a), net.to_base(dir, c.b));
            let (from, to) = if f <= t { (f, t) } else { (t, f) };
            out.push(Interval { dir, from, to, way, score, n_obs, mirrored: false });
            if !ways[way as usize].oneway {
                out.push(Interval { dir: dir.reversed(), from, to, way, score, n_obs, mirrored: true });
            }
        };
        for p in ps.into_iter().skip(1) {
            if p.a <= cur.b + 1e-6 {
                cur.b = cur.b.max(p.b);
                acc.0 += p.score * (p.b - p.a);
                acc.1 += p.b - p.a;
            } else {
                flush(cur, acc, &mut out);
                cur = p;
                acc = (p.score * (p.b - p.a), p.b - p.a);
            }
        }
        flush(cur, acc, &mut out);
    }
    out.sort_by(|x, y| x.dir.cmp(&y.dir).then(x.from.total_cmp(&y.from)));
    out
}

#[cfg(test)]
mod tests {
    use std::sync::Arc;

    use geo::Coord;

    use super::*;
    use crate::config::{TraceConfig, TraceStrategy};
    use crate::geom::Polyline;
    use crate::network::test_util::network;
    use crate::trace::sample::sample_way;

    pub(crate) fn hmm_cfg() -> HmmConfig {
        HmmConfig {
            candidate_radius_m: 25.0,
            max_candidates: 8,
            sigma_distance_m: 7.0,
            heading_kappa: 3.0,
            side_penalty: 1.5,
            side_min_distance_m: 1.5,
            name_mismatch_penalty: 0.5,
            null_log_emission: -4.5,
            null_switch_penalty: 2.0,
            beta_m: 4.0,
            backward_tolerance_m: 3.0,
            route_limit_factor: 3.0,
            route_limit_extra_m: 40.0,
        }
    }

    fn way(idx: u32, pts: &[(f64, f64)], oneway: bool, source: &str) -> TildaWay {
        TildaWay {
            idx,
            data_source: Arc::from(source),
            tilda_id: format!("way/{idx}"),
            line: Polyline::new(pts.iter().map(|&(x, y)| Coord { x, y }).collect()),
            attrs: vec![],
            oneway,
            dual_carriageway: false,
            fuehr: "Radweg".into(),
            category: String::new(),
            traffic_sign: String::new(),
            name_norm: String::new(),
        }
    }

    fn trace_of(w: &TildaWay) -> Trace {
        let tc = TraceConfig { strategy: TraceStrategy::Single, sample_interval_m: 5.0, heading_window_m: 2.0 };
        Trace { id: 0, ways: vec![w.idx], obs: sample_way(w, 0.0, &tc) }
    }

    #[test]
    fn oneway_lane_right_of_edge_matches_forward_across_node() {
        // Zwei Kanten in Ost-Richtung, Radweg 3 m rechts (südlich), gleiche Richtung.
        let net = network(&[&[(0.0, 0.0), (50.0, 0.0)], &[(50.0, 0.0), (100.0, 0.0)]]);
        let w = way(0, &[(10.0, -3.0), (90.0, -3.0)], true, "bikelanes");
        let m = match_trace(&net, &[w.clone()], &hmm_cfg(), &trace_of(&w), false);
        assert!(m.intervals.iter().all(|i| i.dir.ri == 0));
        let cover: f64 = m.intervals.iter().map(|i| i.to - i.from).sum();
        assert!((cover - 80.0).abs() < 1.0, "Abdeckung {cover}");
    }

    #[test]
    fn two_way_path_is_mirrored() {
        let net = network(&[&[(0.0, 0.0), (50.0, 0.0)]]);
        let w = way(0, &[(40.0, 2.0), (10.0, 2.0)], false, "paths");
        let m = match_trace(&net, &[w.clone()], &hmm_cfg(), &trace_of(&w), false);
        assert!(m.intervals.iter().any(|i| i.dir.ri == 0));
        assert!(m.intervals.iter().any(|i| i.dir.ri == 1));
    }

    #[test]
    fn far_parallel_way_goes_to_null_state() {
        let net = network(&[&[(0.0, 0.0), (100.0, 0.0)]]);
        let w = way(0, &[(10.0, 22.0), (90.0, 22.0)], false, "streets");
        let m = match_trace(&net, &[w.clone()], &hmm_cfg(), &trace_of(&w), false);
        assert!(m.intervals.is_empty(), "{:?}", m.intervals);
    }

    #[test]
    fn no_matching_across_topology_gap() {
        let net = network(&[&[(0.0, 0.0), (50.0, 0.0)], &[(50.5, 0.0), (100.0, 0.0)]]);
        let w = way(0, &[(10.0, 1.0), (90.0, 1.0)], false, "streets");
        let m = match_trace(&net, &[w.clone()], &hmm_cfg(), &trace_of(&w), false);
        assert!(!m.breaks.is_empty());
        // Kein Intervall darf über die Lücke hinweg bis an beide Kantenenden reichen.
        for i in &m.intervals {
            let len = net.edges[i.dir.edge as usize].length();
            assert!(i.to - i.from < len + 1e-6);
        }
    }
}
