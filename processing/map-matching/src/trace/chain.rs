//! Traces entlang der Topologie des TILDA-Routing-Netzes.
//!
//! Eine Trace ist eine zusammenhängende Strecke, wie ein Radfahrer sie fährt: Sie läuft
//! über gemeinsame Knoten (`from_node`/`to_node`) nur zu Kanten derselben Datenquelle
//! (Radweg bleibt Radweg, Fahrbahn bleibt Fahrbahn), nur in erlaubter Fahrtrichtung und
//! an Verzweigungen zur Kante mit der kleinsten Richtungsänderung (höchstens `max_turn_deg`).
//! Jede Kante gehört zu genau einer Trace (ihrer Eigentümer-Trace). Optional bekommt jede Trace Kontext
//! (`Topologie::kontext`): Anlauf und Auslauf aus benachbarten Wegen anderer Traces, die nur das Matching stützen.

use rustc_hash::{FxHashMap, FxHashSet};

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

/// Knoten und Endkurse aller Wege, für die Verkettung und den Kontext einer Trace.
pub struct Topologie<'a> {
    ways: &'a [TildaWay],
    ends: Vec<Option<Ends>>,
    at_node: FxHashMap<u64, Vec<u32>>,
    max_turn: f64,
    knick_ohne_abzweig: bool,
}

impl<'a> Topologie<'a> {
    pub fn new(ways: &'a [TildaWay], cfg: &TraceConfig) -> Self {
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
        Topologie { ways, ends, at_node, max_turn: cfg.max_turn_deg.to_radians(), knick_ohne_abzweig: cfg.knick_ohne_abzweig }
    }

    /// Alle möglichen Fortsetzungen am Knoten `node` mit Kurs `h`, in (`forward`) oder gegen die Trace: gleiche
    /// Datenquelle wie `src`, erlaubte Richtung, nicht ausgeschlossen (`skip`). Ergebnis: (Richtungsänderung, Schritt).
    fn options(&self, skip: &dyn Fn(u32) -> bool, src: &TildaWay, node: u64, h: f64, forward: bool) -> Vec<(f64, Step)> {
        let mut out = Vec::new();
        let Some(list) = self.at_node.get(&node) else { return out };
        for &j in list {
            let (w, Some(e)) = (&self.ways[j as usize], &self.ends[j as usize]) else { continue };
            if skip(j) || w.data_source != src.data_source {
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
                out.push((angle_diff(h, h2), Step { way: j, reversed }));
            }
        }
        out
    }

    /// Beste Fortsetzung: kleinste Richtungsänderung, höchstens `max_turn_deg`.
    fn best(&self, skip: &dyn Fn(u32) -> bool, src: &TildaWay, node: u64, h: f64, forward: bool) -> Option<Step> {
        let mut found: Option<(f64, Step)> = None;
        for (turn, s) in self.options(skip, src, node, h, forward) {
            if turn <= self.max_turn && found.is_none_or(|(t, _)| turn < t) {
                found = Some((turn, s));
            }
        }
        found.map(|(_, s)| s)
    }

    /// Fortsetzung beim Verketten: wie `best`; mit `knick_ohne_abzweig` an einem Knick (außer dem ankommenden Weg
    /// `von` genau eine Fortsetzung, vergebene Wege mitgezählt) diese auch über `max_turn_deg` hinaus, wenn sie frei ist.
    fn weiter(&self, skip: &dyn Fn(u32) -> bool, src: &TildaWay, node: u64, h: f64, forward: bool, von: u32) -> Option<Step> {
        let s = self.best(skip, src, node, h, forward);
        if s.is_some() || !self.knick_ohne_abzweig {
            return s;
        }
        match self.options(&|j| j == von, src, node, h, forward).as_slice() {
            [(_, s)] if !skip(s.way) => Some(*s),
            _ => None,
        }
    }

    /// Kontext einer Trace: Anlauf vor ihrem ersten und Auslauf nach ihrem letzten Schritt aus benachbarten Wegen
    /// (auch solchen anderer Traces), nach denselben Regeln wie die Verkettung, je Seite bis mindestens
    /// `context_m` Meter (ganze Wege; gekürzt wird beim Abtasten). Mit `alle_zweige` bekommt eine Trace, die an
    /// einem Knoten mit genau einem ankommenden Weg beginnt, diesen als Anlauf auch über `max_turn_deg` hinaus.
    /// Ergebnis: (Anlauf in Fahrtrichtung, Auslauf in Fahrtrichtung).
    pub fn kontext(&self, chain: &[Step], context_m: f64, alle_zweige: bool) -> (Vec<Step>, Vec<Step>) {
        let (Some(first), Some(last)) = (chain.first(), chain.last()) else { return (Vec::new(), Vec::new()) };
        if context_m <= 0.0 {
            return (Vec::new(), Vec::new());
        }
        let src = &self.ways[first.way as usize];
        let mut taken: FxHashSet<u32> = chain.iter().map(|s| s.way).collect();
        let mut vor = Vec::new();
        if let Some(e) = &self.ends[first.way as usize] {
            let (mut node, mut h) = e.entry(first.reversed);
            let mut len = 0.0;
            while len < context_m {
                let skip = |j: u32| taken.contains(&j);
                let mut s = self.best(&skip, src, node, h, false);
                if s.is_none() && alle_zweige && vor.is_empty() {
                    let opts = self.options(&skip, src, node, h, false);
                    if opts.len() == 1 {
                        s = Some(opts[0].1);
                    }
                }
                let Some(s) = s else { break };
                taken.insert(s.way);
                vor.push(s);
                len += self.ways[s.way as usize].line.length();
                (node, h) = self.ends[s.way as usize].as_ref().unwrap().entry(s.reversed);
            }
        }
        vor.reverse();
        let mut nach = Vec::new();
        if let Some(e) = &self.ends[last.way as usize] {
            let (mut node, mut h) = e.exit(last.reversed);
            let mut len = 0.0;
            while len < context_m {
                let skip = |j: u32| taken.contains(&j);
                let Some(s) = self.best(&skip, src, node, h, true) else { break };
                taken.insert(s.way);
                nach.push(s);
                len += self.ways[s.way as usize].line.length();
                (node, h) = self.ends[s.way as usize].as_ref().unwrap().exit(s.reversed);
            }
        }
        (vor, nach)
    }
}

/// Bildet die Traces. Wege ohne Knoten-IDs bilden je eine eigene Trace.
pub fn build_chains(ways: &[TildaWay], cfg: &TraceConfig) -> Vec<Vec<Step>> {
    let topo = Topologie::new(ways, cfg);
    let mut used = vec![false; ways.len()];

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
        let Some(seed_ends) = &topo.ends[seed as usize] else {
            chains.push(vec![seed_step]);
            continue;
        };
        let src = &ways[seed as usize];
        let mut forward = vec![seed_step];
        let (mut node, mut h) = seed_ends.exit(false);
        let mut von = seed;
        while let Some(s) = topo.weiter(&|j| used[j as usize], src, node, h, true, von) {
            used[s.way as usize] = true;
            forward.push(s);
            von = s.way;
            (node, h) = topo.ends[s.way as usize].as_ref().unwrap().exit(s.reversed);
        }
        let mut backward = Vec::new();
        let (mut node, mut h) = seed_ends.entry(false);
        let mut von = seed;
        while let Some(s) = topo.weiter(&|j| used[j as usize], src, node, h, false, von) {
            used[s.way as usize] = true;
            backward.push(s);
            von = s.way;
            (node, h) = topo.ends[s.way as usize].as_ref().unwrap().entry(s.reversed);
        }
        backward.reverse();
        backward.extend(forward);
        chains.push(backward);
    }
    chains
}

/// Strategie `kreuzungen`: Abschnitte und Übergänge an Verzweigungen. Ergebnis: (Abschnitte, Übergänge).
/// - Abschnitte verketten Wege nur an Knoten mit genau zwei Wegen derselben Datenquelle (gleich welcher Winkel) und
///   enden an jeder Verzweigung, Zusammenführung und an Enden.
/// - Je Knoten mit mehr als zwei Wegen entsteht für jedes Paar (ankommender Abschnitt, abgehender Abschnitt) in
///   erlaubter Richtung eine Übergangs-Trace aus beiden, je Seite auf `kreuzung_m` gekürzt (ganze Wege, 0 = ganz).
///   Zwischen zwei Zweirichtungs-Abschnitten nur eine Richtung, die Spiegelung liefert die andere.
pub fn build_kreuzungen(ways: &[TildaWay], cfg: &TraceConfig) -> (Vec<Vec<Step>>, Vec<Vec<Step>>) {
    let topo = Topologie::new(ways, cfg);
    let grad = |node: u64, src: &TildaWay| {
        topo.at_node.get(&node).map_or(0, |l| l.iter().filter(|&&j| ways[j as usize].data_source == src.data_source).count())
    };
    let mut used = vec![false; ways.len()];
    let mut order: Vec<u32> = (0..ways.len() as u32).collect();
    order.sort_by(|&a, &b| ways[b as usize].line.length().total_cmp(&ways[a as usize].line.length()).then(a.cmp(&b)));

    let mut abschnitte: Vec<Vec<Step>> = Vec::new();
    for seed in order {
        if used[seed as usize] {
            continue;
        }
        used[seed as usize] = true;
        let seed_step = Step { way: seed, reversed: false };
        let Some(seed_ends) = &topo.ends[seed as usize] else {
            abschnitte.push(vec![seed_step]);
            continue;
        };
        let src = &ways[seed as usize];
        let mut forward = vec![seed_step];
        let (mut node, mut h) = seed_ends.exit(false);
        while grad(node, src) == 2 {
            let opts = topo.options(&|j| used[j as usize], src, node, h, true);
            let [(_, s)] = opts.as_slice() else { break };
            let s = *s;
            used[s.way as usize] = true;
            forward.push(s);
            (node, h) = topo.ends[s.way as usize].as_ref().unwrap().exit(s.reversed);
        }
        let mut backward = Vec::new();
        let (mut node, mut h) = seed_ends.entry(false);
        while grad(node, src) == 2 {
            let opts = topo.options(&|j| used[j as usize], src, node, h, false);
            let [(_, s)] = opts.as_slice() else { break };
            let s = *s;
            used[s.way as usize] = true;
            backward.push(s);
            (node, h) = topo.ends[s.way as usize].as_ref().unwrap().entry(s.reversed);
        }
        backward.reverse();
        backward.extend(forward);
        abschnitte.push(backward);
    }

    // Je Knoten die Abschnitte, die dort enden oder beginnen: (Abschnitt, Durchlauf hinein, Durchlauf hinaus).
    let umgekehrt = |steps: &[Step]| -> Vec<Step> { steps.iter().rev().map(|s| Step { way: s.way, reversed: !s.reversed }).collect() };
    type Anschluss = (usize, Option<Vec<Step>>, Option<Vec<Step>>);
    let mut am_knoten: FxHashMap<u64, Vec<Anschluss>> = FxHashMap::default();
    for (k, steps) in abschnitte.iter().enumerate() {
        let (Some(first), Some(last)) = (steps.first(), steps.last()) else { continue };
        let (Some(e0), Some(e1)) = (&topo.ends[first.way as usize], &topo.ends[last.way as usize]) else { continue };
        let zurueck = steps.iter().all(|s| !ways[s.way as usize].oneway).then(|| umgekehrt(steps));
        am_knoten.entry(e1.exit(last.reversed).0).or_default().push((k, Some(steps.clone()), zurueck.clone()));
        am_knoten.entry(e0.entry(first.reversed).0).or_default().push((k, zurueck, Some(steps.clone())));
    }
    // ganze Wege bis mindestens `m` Meter vom Knoten: hinein vom Ende her, hinaus vom Anfang
    let kopf = |steps: &[Step], m: f64| -> Vec<Step> {
        let mut out = Vec::new();
        let mut len = 0.0;
        for s in steps {
            out.push(*s);
            len += ways[s.way as usize].line.length();
            if m > 0.0 && len >= m {
                break;
            }
        }
        out
    };
    let schwanz = |steps: &[Step], m: f64| -> Vec<Step> {
        let mut out = kopf(&steps.iter().rev().copied().collect::<Vec<_>>(), m);
        out.reverse();
        out
    };
    let mut knoten: Vec<(u64, Vec<Anschluss>)> = am_knoten.into_iter().collect();
    knoten.sort_by_key(|(n, _)| *n);
    let mut uebergaenge = Vec::new();
    for (node, liste) in &knoten {
        for (i, (ka, a_hinein, a_hinaus)) in liste.iter().enumerate() {
            for (j, (kb, b_hinein, b_hinaus)) in liste.iter().enumerate() {
                if i == j || ka == kb {
                    continue;
                }
                let (Some(hinein), Some(hinaus)) = (a_hinein, b_hinaus) else { continue };
                let src = &ways[hinein[0].way as usize];
                if ways[hinaus[0].way as usize].data_source != src.data_source || grad(*node, src) < 3 {
                    continue;
                }
                // Zwei Zweirichtungs-Abschnitte: b -> a ist die Spiegelung von a -> b.
                if a_hinaus.is_some() && b_hinein.is_some() && j < i {
                    continue;
                }
                let mut t = schwanz(hinein, cfg.kreuzung_m);
                t.extend(kopf(hinaus, cfg.kreuzung_m));
                uebergaenge.push(t);
            }
        }
    }
    (abschnitte, uebergaenge)
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
            db_id: None,
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
            maxspeed_forward: None,
            maxspeed_backward: None,
            from_node: Some(nodes.0),
            to_node: Some(nodes.1),
        }
    }

    fn cfg() -> TraceConfig {
        TraceConfig { strategy: TraceStrategy::Topology, sample_interval_m: 5.0, heading_window_m: 2.0, max_turn_deg: 45.0, end_heading_m: 10.0, context_m: 0.0, context_alle_zweige: false, knick_ohne_abzweig: false, kreuzung_m: 0.0 }
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

    #[test]
    fn kreuzungen_abschnitte_und_uebergaenge() {
        // Knick um 90 Grad ohne Abzweigung: ein Abschnitt, kein Übergang.
        let knick = vec![
            way(0, &[(0.0, 0.0), (50.0, 0.0)], (0, 1), false, "strassen"),
            way(1, &[(50.0, 0.0), (50.0, 50.0)], (1, 2), false, "strassen"),
        ];
        let (a, u) = build_kreuzungen(&knick, &cfg());
        assert_eq!((a.len(), u.len()), (1, 0));
        // T-Kreuzung aus Zweirichtungs-Wegen: drei Abschnitte, drei Übergänge (die Gegenrichtungen spiegelt das HMM).
        let t = vec![
            way(0, &[(0.0, 0.0), (50.0, 0.0)], (0, 1), false, "strassen"),
            way(1, &[(50.0, 0.0), (100.0, 0.0)], (1, 2), false, "strassen"),
            way(2, &[(50.0, 0.0), (50.0, 50.0)], (1, 3), false, "strassen"),
        ];
        let (a, u) = build_kreuzungen(&t, &cfg());
        assert_eq!((a.len(), u.len()), (3, 3));
        assert!(u.iter().all(|s| s.len() == 2));
        // Einbahn hinein (0) und hinaus (1), Zweirichtung (2): 0 -> 1, 0 -> 2, 2 -> 1.
        let t = vec![
            way(0, &[(0.0, 0.0), (50.0, 0.0)], (0, 1), true, "strassen"),
            way(1, &[(50.0, 0.0), (100.0, 0.0)], (1, 2), true, "strassen"),
            way(2, &[(50.0, 0.0), (50.0, 50.0)], (1, 3), false, "strassen"),
        ];
        let (_, u) = build_kreuzungen(&t, &cfg());
        let mut paare: Vec<(u32, u32)> = u.iter().map(|s| (s[0].way, s[1].way)).collect();
        paare.sort_unstable();
        assert_eq!(paare, vec![(0, 1), (0, 2), (2, 1)]);
    }

    #[test]
    fn knick_ohne_abzweig_folgt_auch_ueber_den_winkel() {
        // Knick um 90 Grad, am Knoten keine weitere Fortsetzung: nur mit knick_ohne_abzweig eine Trace.
        let knick = vec![
            way(0, &[(0.0, 0.0), (60.0, 0.0)], (0, 1), true, "strassen"),
            way(1, &[(60.0, 0.0), (60.0, 50.0)], (1, 2), true, "strassen"),
        ];
        assert_eq!(build_chains(&knick, &cfg()).len(), 2);
        let mit = TraceConfig { knick_ohne_abzweig: true, ..cfg() };
        assert_eq!(build_chains(&knick, &mit).len(), 1);
        // Abzweigung: zwei Fortsetzungen um je 90 Grad, der Winkel entscheidet weiter (keine Verkettung).
        let abzweig = vec![
            way(0, &[(0.0, 0.0), (60.0, 0.0)], (0, 1), true, "strassen"),
            way(1, &[(60.0, 0.0), (60.0, 50.0)], (1, 2), true, "strassen"),
            way(2, &[(60.0, 0.0), (60.0, -50.0)], (1, 3), true, "strassen"),
        ];
        assert_eq!(build_chains(&abzweig, &mit).len(), 3);
    }

    fn kfg(context_m: f64, alle_zweige: bool) -> TraceConfig {
        TraceConfig { context_m, context_alle_zweige: alle_zweige, ..cfg() }
    }

    // Gabelung: A (0..50) geradeaus weiter nach B, an Knoten 1 zweigt C um 45 Grad ab.
    fn gabel() -> Vec<TildaWay> {
        vec![
            way(0, &[(0.0, 0.0), (50.0, 0.0)], (0, 1), true, "bikelanes"),
            way(1, &[(50.0, 0.0), (100.0, 0.0)], (1, 2), true, "bikelanes"),
            way(2, &[(50.0, 0.0), (85.0, 35.0)], (1, 3), true, "bikelanes"),
        ]
    }

    #[test]
    fn side_branch_gets_approach_context_from_other_trace() {
        let ways = gabel();
        let chains = build_chains(&ways, &cfg());
        let ids: Vec<Vec<u32>> = chains.iter().map(|c| c.iter().map(|s| s.way).collect()).collect();
        assert!(ids.contains(&vec![0, 1]) && ids.contains(&vec![2]), "{ids:?}");
        let topo = Topologie::new(&ways, &kfg(100.0, false));
        let (vor, nach) = topo.kontext(&[Step { way: 2, reversed: false }], 100.0, false);
        assert_eq!(vor, vec![Step { way: 0, reversed: false }]);
        assert!(nach.is_empty());
        // Die Trace A-B bekommt keinen Kontext (nichts davor oder danach).
        let (vor, nach) = topo.kontext(&chains.iter().find(|c| c.len() == 2).unwrap().clone(), 100.0, false);
        assert!(vor.is_empty() && nach.is_empty(), "{vor:?} {nach:?}");
    }

    #[test]
    fn context_off_gives_todays_traces() {
        let ways = gabel();
        // Verkettung unabhängig von context_m
        assert_eq!(build_chains(&ways, &cfg()), build_chains(&ways, &kfg(75.0, true)));
        let topo = Topologie::new(&ways, &cfg());
        let steps = [Step { way: 2, reversed: false }];
        let (vor, nach) = topo.kontext(&steps, 0.0, true);
        assert!(vor.is_empty() && nach.is_empty());
        // Beobachtungen wie bisher: nur die eigenen Wege, keine markiert
        let t = crate::trace::topology_trace(0, &ways, &vor, &steps, &nach, &cfg());
        let alt = crate::trace::sample::sample_way(&ways[2], 0.0, false, &cfg());
        assert_eq!(t.obs.len(), alt.len());
        assert!(t.obs.iter().zip(&alt).all(|(a, b)| a.p == b.p && a.trace_s == b.trace_s && !a.kontext));
        assert!(t.kontext_ways.is_empty());
    }

    #[test]
    fn context_is_cut_at_context_m() {
        // Anlauf aus drei Wegen zu je 30 m, dann die eigene Trace (Weg 3).
        let ways = vec![
            way(0, &[(0.0, 0.0), (30.0, 0.0)], (0, 1), true, "bikelanes"),
            way(1, &[(30.0, 0.0), (60.0, 0.0)], (1, 2), true, "bikelanes"),
            way(2, &[(60.0, 0.0), (90.0, 0.0)], (2, 3), true, "bikelanes"),
            way(3, &[(90.0, 0.0), (140.0, 0.0)], (3, 4), true, "bikelanes"),
        ];
        let c = kfg(40.0, false);
        let topo = Topologie::new(&ways, &c);
        let steps = [Step { way: 3, reversed: false }];
        let (vor, nach) = topo.kontext(&steps, 40.0, false);
        // ganze Wege bis mindestens 40 m: zwei Wege (60 m)
        assert_eq!(vor, vec![Step { way: 1, reversed: false }, Step { way: 2, reversed: false }]);
        assert!(nach.is_empty());
        let t = crate::trace::topology_trace(0, &ways, &vor, &steps, &nach, &c);
        let start = t.obs.iter().find(|o| !o.kontext).unwrap().trace_s;
        let erster = t.obs.first().unwrap();
        assert!(erster.kontext && start - erster.trace_s <= 40.0 + 1e-6, "{} {}", start, erster.trace_s);
        assert!(t.obs.iter().filter(|o| o.kontext).all(|o| o.way == 1 || o.way == 2));
        assert_eq!(t.ways, vec![3]);
    }

    #[test]
    fn all_branches_get_approach_beyond_max_turn() {
        // C zweigt rechtwinklig ab (über max_turn_deg): nur mit context_alle_zweige bekommt C den Zulauf A.
        let ways = vec![
            way(0, &[(0.0, 0.0), (50.0, 0.0)], (0, 1), true, "bikelanes"),
            way(1, &[(50.0, 0.0), (100.0, 0.0)], (1, 2), true, "bikelanes"),
            way(2, &[(50.0, 0.0), (50.0, 50.0)], (1, 3), true, "bikelanes"),
        ];
        let topo = Topologie::new(&ways, &cfg());
        let steps = [Step { way: 2, reversed: false }];
        assert!(topo.kontext(&steps, 75.0, false).0.is_empty());
        assert_eq!(topo.kontext(&steps, 75.0, true).0, vec![Step { way: 0, reversed: false }]);
    }
}
