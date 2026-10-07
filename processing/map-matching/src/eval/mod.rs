//! Längengewichteter Vergleich eines Ergebnisses mit einem Referenzdatensatz.
//!
//! Beide Datensätze werden über lineare Referenzierung auf die RVN-Kante
//! `(element_nr, ri)` abgebildet (Digitalisierungsrichtung) und stückweise verglichen.

pub mod report;

use std::collections::BTreeMap;
use std::path::Path;

use anyhow::Result;
use rayon::prelude::*;
use rustc_hash::{FxHashMap, FxHashSet};
use serde::Serialize;
use tracing::{info, warn};

use crate::config::Config;
use crate::io;
use crate::network::Network;

pub const MISSING: &str = "<fehlt>";

/// Ein Teilsegment in linearer Referenz.
#[derive(Debug, Clone)]
pub struct LinSeg {
    pub edge: u32,
    pub ri: u8,
    pub from: f64,
    pub to: f64,
    /// Werte der ausgewerteten Attribute (Reihenfolge wie `eval.attributes`).
    pub attrs: Vec<Option<String>>,
    pub bezirk: Option<String>,
}

#[derive(Debug, Default, Clone, Serialize)]
pub struct LoadStats {
    pub features: usize,
    pub not_in_network: usize,
    pub not_projectable: usize,
}

/// Liest einen Datensatz (eine oder mehrere Ebenen) und bildet ihn auf das Netz ab.
pub fn load_linear(path: &Path, layers: &[String], net: &Network, attributes: &[String], max_proj: f64) -> Result<(Vec<LinSeg>, LoadStats)> {
    let mut fields: Vec<&str> = vec!["element_nr", "ri", "Bezirksnummer"];
    fields.extend(attributes.iter().map(String::as_str));
    let layer_list: Vec<Option<&str>> = if layers.is_empty() { vec![None] } else { layers.iter().map(|l| Some(l.as_str())).collect() };
    let mut feats = Vec::new();
    for l in layer_list {
        feats.extend(io::read_lines(path, l, &fields)?);
    }
    let stats_features = feats.len();
    // Jeder Teil eines mehrteiligen Features wird einzeln referenziert (sonst würde die
    // Hülle über alle Teile z. B. einen Kreuzungsweg über die ganze Kante ziehen).
    let results: Vec<Result<LinSeg, u8>> = feats
        .par_iter()
        .flat_map_iter(|f| f.lines.iter().map(move |part| (f, part)))
        .map(|(f, part)| {
            let Some(edges) = f.fields[0].as_ref().and_then(|e| net.by_element.get(e)) else {
                return Err(0);
            };
            let ri: u8 = f.fields[1].as_deref().and_then(|r| r.parse::<f64>().ok()).map(|r| r as u8).unwrap_or(0);
            // Bei mehrfach vergebener element_nr: die Kante, auf die das Teilstück am besten passt.
            let mut best: Option<(u32, f64, f64, f64)> = None;
            for &edge in edges {
                let line = &net.edges[edge as usize].line;
                let (mut lo, mut hi, mut dsum, mut n) = (f64::INFINITY, f64::NEG_INFINITY, 0.0, 0usize);
                for c in &part.0 {
                    let p = line.project(*c);
                    if p.dist <= max_proj {
                        lo = lo.min(p.s);
                        hi = hi.max(p.s);
                        dsum += p.dist;
                        n += 1;
                    }
                }
                if hi - lo > 1e-6 {
                    let mean = dsum / n as f64;
                    if best.is_none_or(|b| mean < b.3) {
                        best = Some((edge, lo, hi, mean));
                    }
                }
            }
            let Some((edge, lo, hi, _)) = best else {
                return Err(1);
            };
            Ok(LinSeg { edge, ri, from: lo, to: hi, attrs: f.fields[3..].to_vec(), bezirk: f.fields[2].clone() })
        })
        .collect();
    let mut stats = LoadStats { features: stats_features, ..Default::default() };
    let mut segs = Vec::with_capacity(results.len());
    for r in results {
        match r {
            Ok(s) => segs.push(s),
            Err(0) => stats.not_in_network += 1,
            Err(_) => stats.not_projectable += 1,
        }
    }
    if stats.not_in_network > 0 || stats.not_projectable > 0 {
        warn!(
            "{}: {} Teilstücke nicht im Netz, {} nicht projizierbar (von {} Features)",
            path.display(),
            stats.not_in_network,
            stats.not_projectable,
            stats.features
        );
    }
    Ok((segs, stats))
}

/// Manuelle Eingriffe des Altverfahrens (nur zur Einordnung der Abweichungen).
#[derive(Debug, Default)]
pub struct ManualLists {
    pub osm_ways: FxHashSet<String>,
    pub element_nrs: FxHashSet<String>,
}

impl ManualLists {
    pub fn load(cfg: &Config) -> ManualLists {
        let mut m = ManualLists::default();
        let read = |p: &Path| std::fs::read_to_string(p).unwrap_or_default();
        for p in &cfg.paths.manual_way_lists {
            for line in read(&cfg.resolve(p)).lines() {
                let t = line.trim();
                if !t.is_empty() && !t.starts_with('#') {
                    m.osm_ways.insert(t.split(|c: char| !c.is_ascii_digit()).next().unwrap_or("").to_string());
                }
            }
        }
        for p in &cfg.paths.manual_element_lists {
            for line in read(&cfg.resolve(p)).lines() {
                let t = line.trim();
                if !t.is_empty() && !t.starts_with('#') {
                    m.element_nrs.insert(t.split('|').next().unwrap_or("").trim().to_string());
                }
            }
        }
        m.osm_ways.remove("");
        m
    }

    fn touches(&self, tilda_id: Option<&str>) -> bool {
        tilda_id.is_some_and(|id| {
            id.split(';').any(|one| one.trim().strip_prefix("way/").and_then(|r| r.split('/').next()).is_some_and(|osm| self.osm_ways.contains(osm)))
        })
    }
}

/// Ein Stück, auf dem sich `fuehr` unterscheidet.
#[derive(Debug, Clone)]
pub struct Disagreement {
    pub edge: u32,
    pub ri: u8,
    pub from: f64,
    pub to: f64,
    pub ref_fuehr: String,
    pub cand_fuehr: String,
    pub ref_tilda_id: Option<String>,
    pub cand_tilda_id: Option<String>,
    pub manual: bool,
}

#[derive(Debug, Default, Clone, Serialize)]
pub struct AttrAgreement {
    pub attribute: String,
    pub agree_m: f64,
    pub compared_m: f64,
}

#[derive(Debug, Default, Clone, Serialize)]
pub struct DistrictStat {
    pub reference_m: f64,
    pub fuehr_agree_m: f64,
}

#[derive(Debug, Default, Clone, Serialize)]
pub struct EvalResult {
    pub reference_m: f64,
    pub candidate_m: f64,
    pub both_m: f64,
    /// Referenzlänge mit echter Radinfra-/Wege-Zuordnung (nicht "Keine Radinfrastruktur").
    pub reference_assigned_m: f64,
    pub fuehr_agree_m: f64,
    pub attributes: Vec<AttrAgreement>,
    pub confusion_fuehr: BTreeMap<String, BTreeMap<String, f64>>,
    pub districts: BTreeMap<String, DistrictStat>,
    pub dirs_reference: usize,
    pub dirs_candidate: usize,
    pub dirs_only_reference: usize,
    pub dirs_only_candidate: usize,
    pub disagreement_m: f64,
    pub disagreement_manual_m: f64,
    #[serde(skip)]
    pub disagreements: Vec<Disagreement>,
}

impl EvalResult {
    /// Haupt-KPI: Anteil der Referenzlänge mit identischem `fuehr`.
    pub fn fuehr_score(&self) -> f64 {
        pct(self.fuehr_agree_m, self.reference_m)
    }

    pub fn attr_score(&self, name: &str) -> f64 {
        self.attributes.iter().find(|a| a.attribute == name).map_or(f64::NAN, |a| pct(a.agree_m, a.compared_m))
    }
}

pub fn pct(a: f64, b: f64) -> f64 {
    if b > 0.0 { 100.0 * a / b } else { f64::NAN }
}

/// Werte gelten als gleich, wenn sie textgleich oder numerisch gleich sind (beide leer = gleich).
fn same_value(a: Option<&str>, b: Option<&str>) -> bool {
    match (a, b) {
        (None, None) => true,
        (Some(x), Some(y)) => {
            x == y || matches!((x.parse::<f64>(), y.parse::<f64>()), (Ok(p), Ok(q)) if (p - q).abs() < 1e-6)
        }
        _ => false,
    }
}

/// Vergleicht Kandidat mit Referenz. `no_infra` ist der fuehr-Wert für "keine Zuordnung".
pub fn compare(net: &Network, attributes: &[String], reference: &[LinSeg], candidate: &[LinSeg], manual: &ManualLists, no_infra: &str) -> EvalResult {
    let fuehr_idx = attributes.iter().position(|a| a == "fuehr");
    let tid_idx = attributes.iter().position(|a| a == "tilda_id");
    let mut groups: FxHashMap<(u32, u8), (Vec<&LinSeg>, Vec<&LinSeg>)> = FxHashMap::default();
    for s in reference {
        groups.entry((s.edge, s.ri)).or_default().0.push(s);
    }
    for s in candidate {
        groups.entry((s.edge, s.ri)).or_default().1.push(s);
    }
    let mut res = EvalResult {
        dirs_reference: groups.values().filter(|g| !g.0.is_empty()).count(),
        dirs_candidate: groups.values().filter(|g| !g.1.is_empty()).count(),
        dirs_only_reference: groups.values().filter(|g| !g.0.is_empty() && g.1.is_empty()).count(),
        dirs_only_candidate: groups.values().filter(|g| g.0.is_empty() && !g.1.is_empty()).count(),
        attributes: attributes.iter().map(|a| AttrAgreement { attribute: a.clone(), ..Default::default() }).collect(),
        ..Default::default()
    };
    let mut keys: Vec<_> = groups.keys().copied().collect();
    keys.sort_unstable();
    for key in keys {
        let (refs, cands) = &groups[&key];
        let element_manual = manual.element_nrs.contains(&net.edges[key.0 as usize].element_nr);
        let mut bps: Vec<f64> = refs.iter().chain(cands.iter()).flat_map(|s| [s.from, s.to]).collect();
        bps.sort_by(f64::total_cmp);
        bps.dedup_by(|a, b| (*a - *b).abs() < 1e-6);
        for w in bps.windows(2) {
            let (a, b) = (w[0], w[1]);
            let len = b - a;
            if len < 1e-6 {
                continue;
            }
            let mid = 0.5 * (a + b);
            let r = refs.iter().find(|s| s.from <= mid && mid <= s.to);
            let c = cands.iter().find(|s| s.from <= mid && mid <= s.to);
            let fuehr = |s: Option<&&LinSeg>| s.and_then(|s| fuehr_idx.and_then(|i| s.attrs[i].clone())).unwrap_or_else(|| MISSING.to_string());
            let (rf, cf) = (fuehr(r), fuehr(c));
            if let Some(r) = r {
                res.reference_m += len;
                if rf != no_infra {
                    res.reference_assigned_m += len;
                }
                let d = res.districts.entry(r.bezirk.clone().unwrap_or_else(|| MISSING.into())).or_default();
                d.reference_m += len;
                if rf == cf {
                    d.fuehr_agree_m += len;
                }
            }
            if c.is_some() {
                res.candidate_m += len;
            }
            if r.is_none() && c.is_none() {
                continue;
            }
            *res.confusion_fuehr.entry(rf.clone()).or_default().entry(cf.clone()).or_default() += len;
            if let (Some(r), Some(c)) = (r, c) {
                res.both_m += len;
                for (i, ag) in res.attributes.iter_mut().enumerate() {
                    ag.compared_m += len;
                    if same_value(r.attrs[i].as_deref(), c.attrs[i].as_deref()) {
                        ag.agree_m += len;
                    }
                }
            }
            if r.is_some() && rf == cf {
                res.fuehr_agree_m += len;
            } else if r.is_some() {
                let tid = |s: Option<&&LinSeg>| s.and_then(|s| tid_idx.and_then(|i| s.attrs[i].clone()));
                let (rt, ct) = (tid(r), tid(c));
                let is_manual = element_manual || manual.touches(rt.as_deref()) || manual.touches(ct.as_deref());
                res.disagreement_m += len;
                if is_manual {
                    res.disagreement_manual_m += len;
                }
                res.disagreements.push(Disagreement {
                    edge: key.0,
                    ri: key.1,
                    from: a,
                    to: b,
                    ref_fuehr: rf,
                    cand_fuehr: cf,
                    ref_tilda_id: rt,
                    cand_tilda_id: ct,
                    manual: is_manual,
                });
            }
        }
    }
    info!(
        "Evaluation: fuehr-Übereinstimmung {:.1} % der Referenzlänge ({:.1} km)",
        res.fuehr_score(),
        res.reference_m / 1000.0
    );
    res
}
