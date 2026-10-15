//! Traces entlang der Topologie des TILDA-Routing-Netzes.
//!
//! Eine Trace ist eine zusammenhängende Strecke, wie ein Radfahrer sie fährt: Sie läuft
//! über gemeinsame Knoten (`from_node`/`to_node`) nur zu Kanten derselben Datenquelle
//! (Radweg bleibt Radweg, Fahrbahn bleibt Fahrbahn), nur in erlaubter Fahrtrichtung und
//! an Verzweigungen zur Kante mit der kleinsten Richtungsänderung (höchstens `max_turn_deg`).
//! Jede Kante gehört zu genau einer Trace.

use rustc_hash::FxHashMap;

use crate::config::TraceConfig;
use crate::geom::{angle_diff, reverse_heading};
use crate::model::TildaWay;

/// Ein Schritt einer Trace: Weg und Durchlaufrichtung.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Step {
    pub way: u32,
    pub reversed: bool,
}

struct Ends {
    start: u64,
    end: u64,
    /// Kurs beim Verlassen des Anfangs bzw. beim Ankommen am Ende (Digitalisierungsrichtung).
    h_start: f64,
    h_end: f64,
}

impl Ends {
    fn of(w: &TildaWay, cfg: &TraceConfig) -> Option<Ends> {
        let len = w.line.length();
        let win = cfg.end_heading_m.min(len);
        let (a, b) = (w.line.point_at(0.0), w.line.point_at(win));
        let (c, d) = (w.line.point_at(len - win), w.line.point_at(len));
        Some(Ends {
            start: w.from_node?,
            end: w.to_node?,
            h_start: (b.y - a.y).atan2(b.x - a.x),
            h_end: (d.y - c.y).atan2(d.x - c.x),
        })
    }

    /// Knoten und Kurs am Ausgang bzw. Eingang eines Schritts.
    fn exit(&self, reversed: bool) -> (u64, f64) {
        if reversed { (self.start, reverse_heading(self.h_start)) } else { (self.end, self.h_end) }
    }

    fn entry(&self, reversed: bool) -> (u64, f64) {
        if reversed { (self.end, reverse_heading(self.h_end)) } else { (self.start, self.h_start) }
    }
}

/// Bildet die Traces. Wege ohne Knoten-IDs bilden je eine eigene Trace.
pub fn build_chains(ways: &[TildaWay], cfg: &TraceConfig) -> Vec<Vec<Step>> {
    let ends: Vec<Option<Ends>> = ways.iter().map(|w| Ends::of(w, cfg)).collect();
    let mut at_node: FxHashMap<u64, Vec<u32>> = FxHashMap::default();
    for (i, e) in ends.iter().enumerate() {
        if let Some(e) = e {
            at_node.entry(e.start).or_default().push(i as u32);
            if e.end != e.start {
                at_node.entry(e.end).or_default().push(i as u32);
            }
        }
    }
    let max_turn = cfg.max_turn_deg.to_radians();
    let mut used = vec![false; ways.len()];

    // Beste unbenutzte Fortsetzung am Knoten `node` mit Kurs `h`, in (`forward`) oder gegen die Trace.
    let best = |used: &[bool], src: &TildaWay, node: u64, h: f64, forward: bool| -> Option<Step> {
        let mut found: Option<(f64, Step)> = None;
        for &j in at_node.get(&node)? {
            let (w, Some(e)) = (&ways[j as usize], &ends[j as usize]) else { continue };
            if used[j as usize] || w.data_source != src.data_source {
                continue;
            }
            for reversed in [false, true] {
                if reversed && w.oneway {
                    continue;
                }
                // vorwärts: der Schritt muss an `node` beginnen; rückwärts: dort enden.
                let (n, h2) = if forward { e.entry(reversed) } else { e.exit(reversed) };
                if n != node {
                    continue;
                }
                let turn = angle_diff(h, h2);
                if turn <= max_turn && found.is_none_or(|(t, _)| turn < t) {
                    found = Some((turn, Step { way: j, reversed }));
                }
            }
        }
        found.map(|(_, s)| s)
    };

    // Lange Kanten zuerst als Startpunkt (deterministisch).
    let mut order: Vec<u32> = (0..ways.len() as u32).collect();
    order.sort_by(|&a, &b| ways[b as usize].line.length().total_cmp(&ways[a as usize].line.length()).then(a.cmp(&b)));

    let mut chains = Vec::new();
    for seed in order {
        if used[seed as usize] {
            continue;
        }
        used[seed as usize] = true;
        let seed_step = Step { way: seed, reversed: false };
        let Some(seed_ends) = &ends[seed as usize] else {
            chains.push(vec![seed_step]);
            continue;
        };
        let src = &ways[seed as usize];
        let mut forward = vec![seed_step];
        let (mut node, mut h) = seed_ends.exit(false);
        while let Some(s) = best(&used, src, node, h, true) {
            used[s.way as usize] = true;
            forward.push(s);
            (node, h) = ends[s.way as usize].as_ref().unwrap().exit(s.reversed);
        }
        let mut backward = Vec::new();
        let (mut node, mut h) = seed_ends.entry(false);
        while let Some(s) = best(&used, src, node, h, false) {
            used[s.way as usize] = true;
            backward.push(s);
            (node, h) = ends[s.way as usize].as_ref().unwrap().entry(s.reversed);
        }
        backward.reverse();
        backward.extend(forward);
        chains.push(backward);
    }
    chains
}

#[cfg(test)]
mod tests {
    use std::sync::Arc;

    use geo::Coord;

    use super::*;
    use crate::config::TraceStrategy;
    use crate::geom::Polyline;

    fn way(idx: u32, pts: &[(f64, f64)], nodes: (u64, u64), oneway: bool, source: &str) -> TildaWay {
        TildaWay {
            idx,
            data_source: Arc::from(source),
            tilda_id: format!("way/{idx}"),
            line: Polyline::new(pts.iter().map(|&(x, y)| Coord { x, y }).collect()),
            attrs: vec![],
            oneway,
            dual_carriageway: false,
            fuehr: String::new(),
            category: String::new(),
            traffic_sign: String::new(),
            name_norm: String::new(),
            from_node: Some(nodes.0),
            to_node: Some(nodes.1),
        }
    }

    fn cfg() -> TraceConfig {
        TraceConfig { strategy: TraceStrategy::Topology, sample_interval_m: 5.0, heading_window_m: 2.0, max_turn_deg: 45.0, end_heading_m: 10.0 }
    }

    #[test]
    fn chains_straight_through_and_keeps_sources_apart() {
        // Radweg 0 -> 1 -> 2 geradeaus, an Knoten 1 zweigt ein Radweg nach Norden ab,
        // und eine Fahrbahn liegt auf derselben Linie.
        let ways = vec![
            way(0, &[(0.0, 0.0), (50.0, 0.0)], (0, 1), true, "bikelanes"),
            way(1, &[(50.0, 0.0), (100.0, 0.0)], (1, 2), true, "bikelanes"),
            way(2, &[(50.0, 0.0), (50.0, 50.0)], (1, 3), true, "bikelanes"),
            way(3, &[(0.0, 0.0), (100.0, 0.0)], (0, 2), false, "streets"),
        ];
        let chains = build_chains(&ways, &cfg());
        let ids: Vec<Vec<u32>> = chains.iter().map(|c| c.iter().map(|s| s.way).collect()).collect();
        assert!(ids.contains(&vec![0, 1]), "{ids:?}");
        assert!(ids.contains(&vec![2]), "{ids:?}");
        assert!(ids.contains(&vec![3]), "{ids:?}");
    }

    #[test]
    fn oneway_is_never_reversed_two_way_is() {
        // Zwei Einrichtungs-Wege stoßen gegeneinander: keine Verkettung.
        let ways = vec![
            way(0, &[(0.0, 0.0), (50.0, 0.0)], (0, 1), true, "bikelanes"),
            way(1, &[(100.0, 0.0), (50.0, 0.0)], (2, 1), true, "bikelanes"),
        ];
        assert_eq!(build_chains(&ways, &cfg()).len(), 2);
        // Als Zweirichtungs-Wege: eine Trace, der zweite rückwärts durchlaufen.
        let ways = vec![
            way(0, &[(0.0, 0.0), (60.0, 0.0)], (0, 1), false, "paths"),
            way(1, &[(100.0, 0.0), (60.0, 0.0)], (2, 1), false, "paths"),
        ];
        let chains = build_chains(&ways, &cfg());
        assert_eq!(chains, vec![vec![Step { way: 0, reversed: false }, Step { way: 1, reversed: true }]]);
    }
}
