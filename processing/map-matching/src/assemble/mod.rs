//! Aufteilung der RVN-Kanten nach den gematchten Intervallen und Übernahme der
//! TILDA-Attribute. Ergebnis: je (element_nr, ri) eine lückenlose Folge von Teilsegmenten.

pub mod district;
pub mod rules;

use rayon::prelude::*;
use rustc_hash::FxHashMap;

use crate::config::AssembleConfig;
use crate::model::{AttrSchema, DirEdge, Interval, OutSegment, TildaWay};
use crate::network::Network;
use rules::RuleEngine;

const EPS: f64 = 1e-6;

/// Ein Stück, auf dem mehrere TILDA-Wege konkurrierten (Debug/QA).
#[derive(Debug, Clone)]
pub struct Conflict {
    pub dir: DirEdge,
    pub from: f64,
    pub to: f64,
    pub winner: u32,
    pub losers: Vec<u32>,
    pub rule: String,
}

#[derive(Debug, Default)]
pub struct AssembleOutput {
    pub segments: Vec<OutSegment>,
    pub conflicts: Vec<Conflict>,
    /// Kanten, für die wegen der Einbahn-Regel nur eine Richtung ausgegeben wird.
    pub oneway_edges: usize,
}

#[derive(Debug, Clone)]
struct Piece {
    from: f64,
    to: f64,
    winner: Option<u32>,
    score: f64,
    rule: String,
    n: u32,
    /// Beitrag je Weg (Länge) – für die Wahl des repräsentativen Wegs beim Verschmelzen.
    contrib: Vec<(u32, f64)>,
}

impl Piece {
    fn len(&self) -> f64 {
        self.to - self.from
    }
}

pub struct Assembler<'a> {
    pub net: &'a Network,
    pub ways: &'a [TildaWay],
    pub schema: &'a AttrSchema,
    pub cfg: &'a AssembleConfig,
    pub rules: &'a RuleEngine,
}

impl Assembler<'_> {
    pub fn run(&self, intervals: &[Interval]) -> AssembleOutput {
        let mut by_edge: Vec<Vec<Interval>> = vec![Vec::new(); self.net.edges.len()];
        for iv in intervals {
            by_edge[iv.dir.edge as usize].push(*iv);
        }
        let parts: Vec<(Vec<OutSegment>, Vec<Conflict>, bool)> = by_edge
            .par_iter()
            .enumerate()
            .map(|(e, ivs)| self.edge(e as u32, ivs))
            .collect();
        let mut out = AssembleOutput::default();
        for (segs, conflicts, oneway) in parts {
            out.segments.extend(segs);
            out.conflicts.extend(conflicts);
            out.oneway_edges += oneway as usize;
        }
        out
    }

    fn edge(&self, edge: u32, ivs: &[Interval]) -> (Vec<OutSegment>, Vec<Conflict>, bool) {
        let mut conflicts = Vec::new();
        let mut dirs: Vec<Vec<OutSegment>> = (0..2u8)
            .map(|ri| {
                let d = DirEdge::new(edge, ri);
                let own: Vec<&Interval> = ivs.iter().filter(|i| i.dir == d).collect();
                self.direction(d, &own, &mut conflicts)
            })
            .collect();
        // Einbahn-Regel: nur Einrichtungs-Mischverkehr in einer Richtung und nichts in der
        // Gegenrichtung -> Gegenrichtung entfällt (Einbahnstraße ohne Radverkehr in Gegenrichtung).
        let has = |segs: &[OutSegment]| segs.iter().any(|s| s.winner.is_some());
        let oneway_mixed = |segs: &[OutSegment]| {
            segs.iter().filter_map(|s| s.winner).all(|w| {
                let w = &self.ways[w as usize];
                w.oneway && !w.dual_carriageway && w.fuehr == self.cfg.mixed_traffic_fuehr
            })
        };
        let mut dropped = false;
        for (keep, drop) in [(0usize, 1usize), (1, 0)] {
            if has(&dirs[keep]) && !has(&dirs[drop]) && oneway_mixed(&dirs[keep]) {
                dirs[drop].clear();
                dropped = true;
                break;
            }
        }
        (dirs.concat(), conflicts, dropped)
    }

    /// Baut die Teilsegmente einer gerichteten Kante.
    fn direction(&self, dir: DirEdge, ivs: &[&Interval], conflicts: &mut Vec<Conflict>) -> Vec<OutSegment> {
        let len = self.net.dir_len(dir);
        let mut bps: Vec<f64> = vec![0.0, len];
        for iv in ivs {
            bps.push(iv.from.clamp(0.0, len));
            bps.push(iv.to.clamp(0.0, len));
        }
        bps.sort_by(f64::total_cmp);
        bps.dedup_by(|a, b| (*a - *b).abs() < EPS);

        let mut pieces: Vec<Piece> = Vec::with_capacity(bps.len());
        for w in bps.windows(2) {
            let (a, b) = (w[0], w[1]);
            if b - a < EPS {
                continue;
            }
            let mut cands: FxHashMap<u32, f64> = FxHashMap::default();
            for iv in ivs.iter().filter(|i| i.from <= a + EPS && i.to >= b - EPS) {
                let e = cands.entry(iv.way).or_insert(f64::NEG_INFINITY);
                *e = e.max(iv.score);
            }
            let mut cand_list: Vec<(u32, f64)> = cands.into_iter().collect();
            cand_list.sort_by_key(|c| c.0);
            let choice = self.rules.choose(&cand_list, self.ways);
            let piece = match choice {
                Some(c) => {
                    if cand_list.len() > 1 {
                        conflicts.push(Conflict {
                            dir,
                            from: a,
                            to: b,
                            winner: c.way,
                            losers: cand_list.iter().map(|x| x.0).filter(|w| *w != c.way).collect(),
                            rule: c.rule.clone(),
                        });
                    }
                    Piece { from: a, to: b, winner: Some(c.way), score: c.score, rule: c.rule, n: cand_list.len() as u32, contrib: vec![(c.way, b - a)] }
                }
                None => Piece { from: a, to: b, winner: None, score: f64::NAN, rule: "kein Match".into(), n: 0, contrib: vec![] },
            };
            pieces.push(piece);
        }
        merge_adjacent(&mut pieces, |p, q| p.winner == q.winner);
        self.fill_gaps(&mut pieces);
        merge_adjacent(&mut pieces, |p, q| p.winner == q.winner);
        absorb_small(&mut pieces, self.cfg.min_segment_length_m);
        merge_adjacent(&mut pieces, |p, q| self.attr_key(p.winner) == self.attr_key(q.winner));

        pieces
            .into_iter()
            .map(|p| {
                let mut ways: Vec<(u32, f64)> = p.contrib.clone();
                ways.sort_by(|a, b| b.1.total_cmp(&a.1).then(a.0.cmp(&b.0)));
                let winner = p.winner.map(|_| ways[0].0);
                let mut ids: Vec<u32> = ways.iter().map(|w| w.0).collect();
                ids.sort_unstable();
                OutSegment { dir, from: p.from, to: p.to, winner, ways: ids, rule: p.rule, score: p.score, n_candidates: p.n }
            })
            .collect()
    }

    /// Schließt kurze unbelegte Lücken zwischen gleichen Nachbarn und an Kantenenden.
    fn fill_gaps(&self, pieces: &mut [Piece]) {
        let n = pieces.len();
        for i in 0..n {
            if pieces[i].winner.is_some() {
                continue;
            }
            let len = pieces[i].len();
            let prev = (i > 0).then(|| pieces[i - 1].clone());
            let next = (i + 1 < n).then(|| pieces[i + 1].clone());
            let fill = match (&prev, &next) {
                (Some(p), Some(q)) if p.winner.is_some() && p.winner == q.winner && len <= self.cfg.gap_fill_m => Some(p.clone()),
                (None, Some(q)) if q.winner.is_some() && len <= self.cfg.end_fill_m => Some(q.clone()),
                (Some(p), None) if p.winner.is_some() && len <= self.cfg.end_fill_m => Some(p.clone()),
                _ => None,
            };
            if let Some(src) = fill {
                let piece = &mut pieces[i];
                piece.winner = src.winner;
                piece.score = src.score;
                piece.rule = format!("{} (Lücke geschlossen)", src.rule);
                piece.n = src.n;
                piece.contrib = vec![(src.winner.unwrap(), len)];
            }
        }
    }

    /// Schlüssel für das Verschmelzen: Werte der `merge_attributes` des Gewinners.
    fn attr_key(&self, winner: Option<u32>) -> Option<Vec<Option<String>>> {
        winner.map(|w| {
            let way = &self.ways[w as usize];
            self.cfg.merge_attributes.iter().map(|a| way.attr(self.schema, a).map(str::to_string)).collect()
        })
    }
}

/// Verschmilzt benachbarte Stücke, für die `same` gilt.
fn merge_adjacent(pieces: &mut Vec<Piece>, same: impl Fn(&Piece, &Piece) -> bool) {
    let mut out: Vec<Piece> = Vec::with_capacity(pieces.len());
    for p in pieces.drain(..) {
        if let Some(last) = out.last_mut()
            && same(last, &p)
        {
            join(last, p);
            continue;
        }
        out.push(p);
    }
    *pieces = out;
}

fn join(into: &mut Piece, p: Piece) {
    let (l1, l2) = (into.len(), p.len());
    if into.score.is_finite() && p.score.is_finite() {
        into.score = (into.score * l1 + p.score * l2) / (l1 + l2);
    } else if p.score.is_finite() {
        into.score = p.score;
    }
    into.to = p.to;
    into.n = into.n.max(p.n);
    if into.rule != p.rule && l2 > l1 {
        into.rule = p.rule;
    }
    for (w, l) in p.contrib {
        match into.contrib.iter_mut().find(|c| c.0 == w) {
            Some(c) => c.1 += l,
            None => into.contrib.push((w, l)),
        }
    }
}

/// Schlägt Stücke unter `min_len` dem längeren Nachbarn zu.
fn absorb_small(pieces: &mut Vec<Piece>, min_len: f64) {
    while pieces.len() > 1 {
        let Some((i, _)) = pieces
            .iter()
            .enumerate()
            .filter(|(_, p)| p.len() < min_len)
            .min_by(|a, b| a.1.len().total_cmp(&b.1.len()))
        else {
            break;
        };
        let target = match (i.checked_sub(1), (i + 1 < pieces.len()).then_some(i + 1)) {
            (Some(p), Some(n)) => {
                if pieces[p].len() >= pieces[n].len() { p } else { n }
            }
            (Some(p), None) => p,
            (None, Some(n)) => n,
            (None, None) => break,
        };
        let small = pieces.remove(i);
        let t = if target > i { target - 1 } else { target };
        let tp = &mut pieces[t];
        tp.from = tp.from.min(small.from);
        tp.to = tp.to.max(small.to);
        if let Some(w) = tp.winner {
            match tp.contrib.iter_mut().find(|c| c.0 == w) {
                Some(c) => c.1 += small.len(),
                None => tp.contrib.push((w, small.len())),
            }
        }
        // Nach dem Zuschlagen können gleiche Nachbarn entstehen.
        merge_adjacent(pieces, |p, q| p.winner == q.winner);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn piece(from: f64, to: f64, w: Option<u32>) -> Piece {
        Piece { from, to, winner: w, score: 0.0, rule: String::new(), n: 1, contrib: w.map(|w| vec![(w, to - from)]).unwrap_or_default() }
    }

    #[test]
    fn small_pieces_are_absorbed_and_coverage_is_complete() {
        let mut p = vec![piece(0.0, 40.0, Some(1)), piece(40.0, 41.5, Some(2)), piece(41.5, 100.0, Some(1))];
        absorb_small(&mut p, 3.0);
        assert_eq!(p.len(), 1);
        assert_eq!((p[0].from, p[0].to, p[0].winner), (0.0, 100.0, Some(1)));
    }
}
