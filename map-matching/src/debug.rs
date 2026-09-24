//! Debug-Ausgaben: Geodaten-Layer für QGIS und JSON-Dumps einzelner Traces.

use std::path::Path;

use anyhow::Result;
use geo::{Geometry, Point};
use rustc_hash::FxHashMap;
use serde_json::json;
use tracing::info;

use crate::config::Config;
use crate::hmm::TraceMatch;
use crate::io::{self, FieldKind, GeomType, Value};
use crate::model::Trace;
use crate::pipeline::{MatchResult, Prepared};

fn element(p: &Prepared, edge: u32) -> &str {
    &p.net.edges[edge as usize].element_nr
}

/// Schreibt alle Debug-Layer nach `<output_dir>/debug/`.
pub fn write_layers(p: &Prepared, r: &MatchResult, dir: &Path) -> Result<()> {
    std::fs::create_dir_all(dir)?;

    io::write_fgb(&dir.join("topology_report.fgb"), "topologie", GeomType::Point, &crate::network::topology::TopologyReport::fgb_fields(), p.net.topology.fgb_rows())?;

    let obs_fields = [
        ("trace_id", FieldKind::Int),
        ("tilda_id", FieldKind::Str),
        ("data_source", FieldKind::Str),
        ("obs", FieldKind::Int),
        ("kurs_grad", FieldKind::Real),
        ("element_nr", FieldKind::Str),
        ("ri", FieldKind::Int),
        ("s_m", FieldKind::Real),
        ("abstand_m", FieldKind::Real),
        ("log_emission", FieldKind::Real),
        ("kandidaten", FieldKind::Int),
        ("null_zustand", FieldKind::Int),
    ];
    let obs_rows = r.traces.iter().zip(&r.matches).flat_map(|(t, m)| {
        t.obs.iter().zip(&m.states).enumerate().map(move |(i, (o, st))| {
            let w = &p.ways[o.way as usize];
            let c = st.chosen;
            (
                Geometry::Point(Point(o.p)),
                vec![
                    Value::Int(t.id as i64),
                    w.tilda_id.as_str().into(),
                    (&*w.data_source).into(),
                    Value::Int(i as i64),
                    Value::Real(o.heading.to_degrees()),
                    c.map(|c| element(p, c.dir.edge)).into(),
                    c.map_or(Value::Str(None), |c| Value::Int(c.dir.ri as i64)),
                    Value::Real(c.map_or(f64::NAN, |c| c.s)),
                    Value::Real(c.map_or(f64::NAN, |c| c.dist)),
                    Value::Real(c.map_or(f64::NAN, |c| c.log_emission)),
                    Value::Int(st.n_candidates as i64),
                    Value::Int((c.is_none() && st.n_candidates > 0) as i64),
                ],
            )
        })
    });
    io::write_fgb(&dir.join("observations.fgb"), "beobachtungen", GeomType::Point, &obs_fields, obs_rows)?;

    let iv_fields = [
        ("element_nr", FieldKind::Str),
        ("ri", FieldKind::Int),
        ("von_m", FieldKind::Real),
        ("bis_m", FieldKind::Real),
        ("tilda_id", FieldKind::Str),
        ("data_source", FieldKind::Str),
        ("fuehr", FieldKind::Str),
        ("score", FieldKind::Real),
        ("n_obs", FieldKind::Int),
        ("gespiegelt", FieldKind::Int),
    ];
    let iv_rows = r.matches.iter().flat_map(|m| m.intervals.iter()).map(|iv| {
        let e = &p.net.edges[iv.dir.edge as usize];
        let w = &p.ways[iv.way as usize];
        (
            Geometry::LineString(e.line.substring(iv.from, iv.to)),
            vec![
                e.element_nr.as_str().into(),
                Value::Int(iv.dir.ri as i64),
                Value::Real(iv.from),
                Value::Real(iv.to),
                w.tilda_id.as_str().into(),
                (&*w.data_source).into(),
                w.fuehr.as_str().into(),
                Value::Real(iv.score),
                Value::Int(iv.n_obs as i64),
                Value::Int(iv.mirrored as i64),
            ],
        )
    });
    io::write_fgb(&dir.join("intervals_raw.fgb"), "intervalle", GeomType::LineString, &iv_fields, iv_rows)?;

    let cf_fields = [
        ("element_nr", FieldKind::Str),
        ("ri", FieldKind::Int),
        ("gewinner", FieldKind::Str),
        ("gewinner_fuehr", FieldKind::Str),
        ("verlierer", FieldKind::Str),
        ("regel", FieldKind::Str),
    ];
    let cf_rows = r.assembled.conflicts.iter().map(|c| {
        let e = &p.net.edges[c.dir.edge as usize];
        let w = &p.ways[c.winner as usize];
        let losers: Vec<String> = c.losers.iter().map(|l| format!("{} [{}]", p.ways[*l as usize].tilda_id, p.ways[*l as usize].fuehr)).collect();
        (
            Geometry::LineString(e.line.substring(c.from, c.to)),
            vec![
                e.element_nr.as_str().into(),
                Value::Int(c.dir.ri as i64),
                w.tilda_id.as_str().into(),
                w.fuehr.as_str().into(),
                losers.join("; ").into(),
                c.rule.as_str().into(),
            ],
        )
    });
    io::write_fgb(&dir.join("conflicts.fgb"), "konflikte", GeomType::LineString, &cf_fields, cf_rows)?;

    let br_fields = [("trace_id", FieldKind::Int), ("tilda_id", FieldKind::Str), ("obs", FieldKind::Int)];
    let br_rows = r.traces.iter().zip(&r.matches).flat_map(|(t, m)| {
        m.breaks.iter().map(move |&b| {
            let o = &t.obs[b];
            (
                Geometry::Point(Point(o.p)),
                vec![Value::Int(t.id as i64), p.ways[o.way as usize].tilda_id.as_str().into(), Value::Int(b as i64)],
            )
        })
    });
    io::write_fgb(&dir.join("breaks.fgb"), "brueche", GeomType::Point, &br_fields, br_rows)?;

    write_matched_ways(p, r, &dir.join("matched_tilda_ways.fgb"))?;
    info!("Debug-Layer geschrieben nach {}", dir.display());
    Ok(())
}

/// TILDA-Wege mit Match-Statistik (auch ohne `--debug` nützlich für die QA).
pub fn write_matched_ways(p: &Prepared, r: &MatchResult, path: &Path) -> Result<()> {
    let mut matched: FxHashMap<u32, (f64, u32)> = FxHashMap::default();
    for iv in r.matches.iter().flat_map(|m| m.intervals.iter()).filter(|i| !i.mirrored) {
        let e = matched.entry(iv.way).or_default();
        e.0 += iv.to - iv.from;
        e.1 += 1;
    }
    let mut won: FxHashMap<u32, f64> = FxHashMap::default();
    for s in &r.assembled.segments {
        if let Some(w) = s.winner {
            *won.entry(w).or_default() += s.len();
        }
    }
    let fields = [
        ("tilda_id", FieldKind::Str),
        ("data_source", FieldKind::Str),
        ("fuehr", FieldKind::Str),
        ("verkehrsri", FieldKind::Str),
        ("laenge_m", FieldKind::Real),
        ("gematcht_m", FieldKind::Real),
        ("gewonnen_m", FieldKind::Real),
        ("intervalle", FieldKind::Int),
    ];
    let rows = matched.iter().map(|(w, (len, n))| {
        let way = &p.ways[*w as usize];
        (
            Geometry::LineString(way.line.to_linestring()),
            vec![
                way.tilda_id.as_str().into(),
                (&*way.data_source).into(),
                way.fuehr.as_str().into(),
                (if way.oneway { "Einrichtungsverkehr" } else { "Zweirichtungsverkehr" }).into(),
                Value::Real(way.line.length()),
                Value::Real(*len),
                Value::Real(*won.get(w).unwrap_or(&0.0)),
                Value::Int(*n as i64),
            ],
        )
    });
    io::write_fgb(path, "gematchte_wege", GeomType::LineString, &fields, rows)?;
    Ok(())
}

/// Vollständiges Viterbi-Gitter einer Trace als JSON.
pub fn trace_json(p: &Prepared, cfg: &Config, t: &Trace, m: &TraceMatch) -> serde_json::Value {
    let steps: Vec<serde_json::Value> = m
        .lattice
        .as_deref()
        .unwrap_or_default()
        .iter()
        .enumerate()
        .map(|(i, st)| {
            let o = &t.obs[i];
            let cands: Vec<serde_json::Value> = st
                .candidates
                .iter()
                .enumerate()
                .map(|(j, c)| {
                    json!({
                        "element_nr": element(p, c.dir.edge), "ri": c.dir.ri, "s": c.s, "abstand": c.dist,
                        "log_emission": c.log_emission, "viterbi": st.scores[j], "vorgaenger": st.back[j],
                    })
                })
                .collect();
            json!({
                "obs": i, "x": o.p.x, "y": o.p.y, "kurs_grad": o.heading.to_degrees(), "trace_s": o.trace_s,
                "tilda_id": p.ways[o.way as usize].tilda_id,
                "kandidaten": cands,
                "null_zustand": { "viterbi": st.scores.last(), "vorgaenger": st.back.last() },
                "gewaehlt": m.states[i].chosen.map(|c| json!({"element_nr": element(p, c.dir.edge), "ri": c.dir.ri, "s": c.s})),
            })
        })
        .collect();
    let intervals: Vec<serde_json::Value> = m
        .intervals
        .iter()
        .map(|iv| json!({"element_nr": element(p, iv.dir.edge), "ri": iv.dir.ri, "von": iv.from, "bis": iv.to, "score": iv.score, "gespiegelt": iv.mirrored}))
        .collect();
    json!({
        "trace_id": t.id,
        "wege": t.ways.iter().map(|w| &p.ways[*w as usize].tilda_id).collect::<Vec<_>>(),
        "hmm": cfg.hmm,
        "brueche": m.breaks,
        "schritte": steps,
        "intervalle": intervals,
    })
}
