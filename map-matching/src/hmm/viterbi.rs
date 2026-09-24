//! Viterbi im Log-Raum mit Null-Zustand ("nicht auf dem RVN").
//!
//! Zustände je Schritt: die Kandidaten der Beobachtung plus ein Null-Zustand
//! (Index = Anzahl Kandidaten). Ein Übergang Kandidat -> Kandidat existiert nur,
//! wenn das RVN beide Positionen verbindet. Gibt es an einem Schritt keinen
//! einzigen solchen Übergang, ist das ein HMM-Bruch: die Folge läuft über den
//! Null-Zustand weiter und wird nie über die Lücke hinweg gematcht.

use serde::Serialize;

use super::transition::log_transition;
use crate::config::HmmConfig;
use crate::model::{Candidate, Observation};
use crate::network::routing::Router;

#[derive(Debug, Clone, Serialize)]
pub struct LatticeStep {
    pub candidates: Vec<Candidate>,
    /// Viterbi-Score je Zustand (letzter Eintrag = Null-Zustand).
    pub scores: Vec<f64>,
    /// Vorgänger je Zustand (letzter Eintrag = Null-Zustand).
    pub back: Vec<Option<usize>>,
}

#[derive(Debug, Clone, Default)]
pub struct ViterbiResult {
    /// Gewählter Kandidat je Beobachtung (None = Null-Zustand).
    pub path: Vec<Option<usize>>,
    /// Schritte, an denen kein Übergang Kandidat -> Kandidat möglich war.
    pub breaks: Vec<usize>,
    pub lattice: Option<Vec<LatticeStep>>,
}

pub fn viterbi(router: &mut Router, cfg: &HmmConfig, obs: &[Observation], cands: &[Vec<Candidate>], want_lattice: bool) -> ViterbiResult {
    let n = obs.len();
    if n == 0 {
        return ViterbiResult::default();
    }
    let null_e = cfg.null_log_emission;
    let sw = cfg.null_switch_penalty;
    let mut scores: Vec<Vec<f64>> = Vec::with_capacity(n);
    let mut back: Vec<Vec<Option<usize>>> = Vec::with_capacity(n);
    let mut breaks = Vec::new();

    let mut first: Vec<f64> = cands[0].iter().map(|c| c.log_emission).collect();
    first.push(null_e);
    scores.push(first);
    back.push(vec![None; cands[0].len() + 1]);

    for t in 1..n {
        let d_trace = (obs[t].trace_s - obs[t - 1].trace_s).max(0.0);
        let (prev_c, cur_c) = (&cands[t - 1], &cands[t]);
        let prev = &scores[t - 1];
        let prev_null = prev_c.len();
        let mut cur_scores = Vec::with_capacity(cur_c.len() + 1);
        let mut cur_back = Vec::with_capacity(cur_c.len() + 1);
        let mut any_link = false;
        for c in cur_c {
            // aus dem Null-Zustand
            let mut best = prev[prev_null] - sw;
            let mut arg = Some(prev_null);
            for (j, p) in prev_c.iter().enumerate() {
                if prev[j] == f64::NEG_INFINITY {
                    continue;
                }
                let tr = log_transition(router, cfg, p, c, d_trace);
                if tr > f64::NEG_INFINITY {
                    any_link = true;
                    let v = prev[j] + tr;
                    if v > best {
                        best = v;
                        arg = Some(j);
                    }
                }
            }
            cur_scores.push(best + c.log_emission);
            cur_back.push(arg);
        }
        // Null-Zustand: aus Null (ohne Strafe) oder aus einem Kandidaten (mit Strafe).
        let mut best_null = prev[prev_null];
        let mut arg_null = Some(prev_null);
        for j in 0..prev_null {
            let v = prev[j] - sw;
            if v > best_null {
                best_null = v;
                arg_null = Some(j);
            }
        }
        cur_scores.push(best_null + null_e);
        cur_back.push(arg_null);
        if !any_link && !prev_c.is_empty() && !cur_c.is_empty() {
            breaks.push(t);
        }
        scores.push(cur_scores);
        back.push(cur_back);
    }

    // Rückverfolgung
    let last = &scores[n - 1];
    let mut state = (0..last.len()).max_by(|&a, &b| last[a].total_cmp(&last[b]).then(b.cmp(&a))).unwrap_or(0);
    let mut path = vec![None; n];
    for t in (0..n).rev() {
        path[t] = (state < cands[t].len()).then_some(state);
        if t > 0 {
            state = back[t][state].unwrap_or(cands[t - 1].len());
        }
    }
    let lattice = want_lattice.then(|| {
        (0..n)
            .map(|t| LatticeStep { candidates: cands[t].clone(), scores: scores[t].clone(), back: back[t].clone() })
            .collect()
    });
    ViterbiResult { path, breaks, lattice }
}
