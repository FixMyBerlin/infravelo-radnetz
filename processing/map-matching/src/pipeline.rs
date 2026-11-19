//! Orchestrierung: Laden -> Traces -> HMM/Viterbi (parallel) -> Aufteilung -> Ausgabe.

use std::collections::BTreeMap;
use std::path::PathBuf;
use std::time::Instant;

use anyhow::{Context, Result, bail};
use geo::{BoundingRect, Contains, Coord, Geometry, MultiPolygon, Point, Rect};
use indicatif::{ParallelProgressIterator, ProgressBar, ProgressStyle};
use rayon::prelude::*;
use serde::Serialize;
use tracing::info;

use crate::assemble::district::Districts;
use crate::assemble::rules::RuleEngine;
use crate::assemble::{AssembleOutput, Assembler};
use crate::config::Config;
use crate::eval::LinSeg;
use crate::geom::{Polyline, angle_diff, reverse_heading};
use crate::hmm::{self, TraceMatch};
use crate::io::{self, FieldKind, GeomType, Value};
use crate::model::{AttrSchema, Interval, OutSegment, TildaWay, Trace};
use crate::network::Network;
use crate::trace;

/// Optionen eines Laufs (Gebietsfilter, Debug).
#[derive(Debug, Clone, Default)]
pub struct RunOptions {
    pub clip: Option<String>,
    /// Rechteck in EPSG:25833: minx, miny, maxx, maxy.
    pub bbox: Option<[f64; 4]>,
    pub debug: bool,
    /// Nur diese TILDA-IDs verarbeiten (Debug).
    pub tilda_ids: Vec<String>,
}

impl RunOptions {
    pub fn suffix(&self) -> String {
        match (&self.clip, &self.bbox) {
            (Some(c), _) => format!("_{c}"),
            (None, Some(_)) => "_bbox".into(),
            _ => String::new(),
        }
    }
}

/// Gebietsfilter für `--clip` / `--bbox`.
pub struct AreaFilter {
    polys: Vec<MultiPolygon<f64>>,
    rect: Rect<f64>,
}

impl AreaFilter {
    pub fn from_options(cfg: &Config, opts: &RunOptions) -> Result<Option<AreaFilter>> {
        if let Some(region) = &opts.clip {
            let rel = cfg
                .paths
                .clip_regions
                .get(region)
                .with_context(|| format!("Unbekannte Region '{region}' (bekannt: {:?})", cfg.paths.clip_regions.keys().collect::<Vec<_>>()))?;
            let polys: Vec<MultiPolygon<f64>> = io::read_polygons(&cfg.resolve(rel), &[])?.into_iter().map(|p| p.geom).collect();
            let rect = polys.iter().filter_map(|p| p.bounding_rect()).reduce(|a, b| {
                Rect::new(
                    Coord { x: a.min().x.min(b.min().x), y: a.min().y.min(b.min().y) },
                    Coord { x: a.max().x.max(b.max().x), y: a.max().y.max(b.max().y) },
                )
            });
            let Some(rect) = rect else { bail!("Region '{region}' enthält keine Polygone") };
            return Ok(Some(AreaFilter { polys, rect }));
        }
        if let Some([a, b, c, d]) = opts.bbox {
            let rect = Rect::new(Coord { x: a, y: b }, Coord { x: c, y: d });
            return Ok(Some(AreaFilter { polys: vec![MultiPolygon(vec![rect.to_polygon()])], rect }));
        }
        Ok(None)
    }

    /// Kante gehört zum Gebiet, wenn ihr Mittelpunkt darin liegt.
    pub fn keeps_edge(&self, line: &Polyline) -> bool {
        let mid = Point(line.point_at(line.length() / 2.0));
        self.polys.iter().any(|p| p.contains(&mid))
    }

    /// TILDA-Weg wird geladen, wenn seine Hülle das (um `margin` erweiterte) Gebiet schneidet.
    pub fn keeps_way(&self, line: &Polyline, margin: f64) -> bool {
        let (mut x0, mut y0, mut x1, mut y1) = (f64::MAX, f64::MAX, f64::MIN, f64::MIN);
        for c in &line.coords {
            x0 = x0.min(c.x);
            y0 = y0.min(c.y);
            x1 = x1.max(c.x);
            y1 = y1.max(c.y);
        }
        x1 >= self.rect.min().x - margin && x0 <= self.rect.max().x + margin && y1 >= self.rect.min().y - margin && y0 <= self.rect.max().y + margin
    }
}

/// Alle geladenen Eingangsdaten.
pub struct Prepared {
    pub net: Network,
    pub ways: Vec<TildaWay>,
    pub schema: AttrSchema,
    pub districts: Districts,
    pub suffix: String,
}

pub fn prepare(cfg: &Config, opts: &RunOptions) -> Result<Prepared> {
    let t = Instant::now();
    let area = AreaFilter::from_options(cfg, opts)?;
    let net = Network::load(cfg, &cfg.resolve(&cfg.paths.network), |l| area.as_ref().is_none_or(|a| a.keeps_edge(l)))?;
    net.topology.log_summary();
    let schema = AttrSchema::new(&cfg.assemble.transfer_attributes);
    let margin = cfg.hmm.candidate_radius_m * 2.0;
    let mut ways = trace::load_ways(cfg, &schema, |l| area.as_ref().is_none_or(|a| a.keeps_way(l, margin)))?;
    if !opts.tilda_ids.is_empty() {
        ways.retain(|w| opts.tilda_ids.iter().any(|id| w.tilda_id == *id || w.tilda_id.starts_with(&format!("{id}#"))));
        for (i, w) in ways.iter_mut().enumerate() {
            w.idx = i as u32;
        }
        if ways.is_empty() {
            bail!("Keine TILDA-Wege mit den IDs {:?} gefunden", opts.tilda_ids);
        }
    }
    let districts = Districts::load(&cfg.resolve(&cfg.paths.districts))?;
    info!("Daten geladen in {:.1} s: {} RVN-Kanten, {} TILDA-Wege", t.elapsed().as_secs_f64(), net.edges.len(), ways.len());
    Ok(Prepared { net, ways, schema, districts, suffix: opts.suffix() })
}

/// Nur Netz und Bezirke laden (für `eval` und `topology`).
pub fn prepare_network_only(cfg: &Config, opts: &RunOptions) -> Result<Prepared> {
    let area = AreaFilter::from_options(cfg, opts)?;
    let net = Network::load(cfg, &cfg.resolve(&cfg.paths.network), |l| area.as_ref().is_none_or(|a| a.keeps_edge(l)))?;
    net.topology.log_summary();
    let districts = Districts::load(&cfg.resolve(&cfg.paths.districts))?;
    Ok(Prepared { net, ways: Vec::new(), schema: AttrSchema::new(&cfg.assemble.transfer_attributes), districts, suffix: opts.suffix() })
}

/// Zusammenfassung eines Laufs (stats.json).
#[derive(Debug, Default, Serialize)]
pub struct RunStats {
    pub ways: usize,
    pub traces: usize,
    pub traces_with_candidates: usize,
    pub traces_matched: usize,
    pub observations: usize,
    pub observations_without_candidates: usize,
    pub observations_null_state: usize,
    pub hmm_breaks: usize,
    pub intervals: usize,
    pub segments: usize,
    pub segments_without_infra: usize,
    pub oneway_edges: usize,
    pub conflicts: usize,
    pub dijkstra_runs: u64,
    pub topology_errors: usize,
    pub length_by_fuehr_km: BTreeMap<String, f64>,
    pub timings_s: BTreeMap<String, f64>,
}

/// Ergebnis von Matching und Aufteilung (im Speicher).
pub struct MatchResult {
    pub traces: Vec<Trace>,
    pub matches: Vec<TraceMatch>,
    pub assembled: AssembleOutput,
    pub stats: RunStats,
}

fn progress(n: usize, msg: &'static str) -> ProgressBar {
    let pb = ProgressBar::new(n as u64);
    pb.set_style(ProgressStyle::with_template("{msg} [{bar:40}] {pos}/{len} ({eta})").unwrap().progress_chars("=> "));
    pb.set_message(msg);
    pb
}

/// Matching und Aufteilung mit einer (ggf. per Override geänderten) Konfiguration.
pub fn match_and_assemble(p: &Prepared, cfg: &Config, show_progress: bool) -> MatchResult {
    let mut stats = RunStats { ways: p.ways.len(), topology_errors: p.net.topology.errors(), ..Default::default() };
    let t = Instant::now();
    let traces = trace::build_traces(cfg, &p.ways);
    stats.timings_s.insert("traces".into(), t.elapsed().as_secs_f64());

    let t = Instant::now();
    let pb = if show_progress { progress(traces.len(), "HMM-Matching") } else { ProgressBar::hidden() };
    let matches: Vec<TraceMatch> = traces
        .par_iter()
        .progress_with(pb.clone())
        .map(|tr| hmm::match_trace(&p.net, &p.ways, &cfg.hmm, tr, false))
        .collect();
    pb.finish_and_clear();
    stats.timings_s.insert("hmm".into(), t.elapsed().as_secs_f64());

    let intervals: Vec<Interval> = matches.iter().flat_map(|m| m.intervals.iter().copied()).collect();
    let t = Instant::now();
    let rules = RuleEngine::new(&cfg.rules);
    let assembler = Assembler { net: &p.net, ways: &p.ways, schema: &p.schema, cfg: &cfg.assemble, rules: &rules };
    let assembled = assembler.run(&intervals);
    stats.timings_s.insert("aufteilung".into(), t.elapsed().as_secs_f64());

    stats.traces = traces.len();
    for m in &matches {
        let with_cands = m.states.iter().any(|s| s.n_candidates > 0);
        stats.traces_with_candidates += with_cands as usize;
        stats.traces_matched += (!m.intervals.is_empty()) as usize;
        stats.observations += m.states.len();
        stats.observations_without_candidates += m.states.iter().filter(|s| s.n_candidates == 0).count();
        stats.observations_null_state += m.states.iter().filter(|s| s.chosen.is_none() && s.n_candidates > 0).count();
        stats.hmm_breaks += m.breaks.len();
        stats.dijkstra_runs += m.dijkstra_runs;
    }
    stats.intervals = intervals.len();
    stats.segments = assembled.segments.len();
    stats.segments_without_infra = assembled.segments.iter().filter(|s| s.winner.is_none()).count();
    stats.oneway_edges = assembled.oneway_edges;
    stats.conflicts = assembled.conflicts.len();
    for s in &assembled.segments {
        let f = fuehr_of(p, cfg, s);
        *stats.length_by_fuehr_km.entry(f).or_default() += s.len() / 1000.0;
    }
    MatchResult { traces, matches, assembled, stats }
}

fn fuehr_of(p: &Prepared, cfg: &Config, s: &OutSegment) -> String {
    s.winner
        .and_then(|w| p.ways[w as usize].attr(&p.schema, "fuehr").map(str::to_string))
        .unwrap_or_else(|| cfg.assemble.no_infra_fuehr.clone())
}

/// Wandelt Ausgabesegmente in lineare Referenz für die Evaluation (ohne Dateiumweg).
pub fn to_linseg(p: &Prepared, cfg: &Config, segs: &[OutSegment], attributes: &[String]) -> Vec<LinSeg> {
    segs.iter()
        .map(|s| {
            let attrs = attributes
                .iter()
                .map(|a| {
                    if a == "fuehr" {
                        Some(fuehr_of(p, cfg, s))
                    } else {
                        s.winner.and_then(|w| p.ways[w as usize].attr(&p.schema, a).map(str::to_string))
                    }
                })
                .collect();
            let mid = p.net.edges[s.dir.edge as usize].line.point_at(0.5 * (s.from + s.to));
            LinSeg { edge: s.dir.edge, ri: s.dir.ri, from: s.from, to: s.to, attrs, bezirk: p.districts.lookup(mid).map(str::to_string) }
        })
        .collect()
}

/// Ausgabedatei des Laufs.
pub fn output_path(cfg: &Config, suffix: &str) -> PathBuf {
    cfg.output_dir().join(format!("network_enriched_hmm{suffix}.fgb"))
}

/// Übernommene Attribute, die von der Fahrtrichtung abhängen: `maxspeed:forward|backward` des Wegs ersetzt
/// den allgemeinen Wert (siehe `directional_maxspeed`).
const MAXSPEED: &str = "tilda_maxspeed";
const MAXSPEED_SOURCE: &str = "tilda_maxspeed_source";

/// `tilda_maxspeed` und `tilda_maxspeed_source` eines Teilsegments, wenn der gewinnende Weg für die
/// Fahrtrichtung `maxspeed:forward|backward` hat. Die Fahrtrichtung ist die Richtung der Kante
/// (`ri = 0`) bzw. ihre Gegenrichtung (`ri = 1`); sie gilt als `forward`, wenn sie am Teilsegment mit der
/// Linienrichtung des TILDA-Wegs übereinstimmt. Bei Zweirichtungswegen ist das nicht aus dem Matching
/// ablesbar, deshalb werden die Geometrien verglichen.
fn directional_maxspeed(way: &TildaWay, edge: &Polyline, s: &OutSegment) -> Option<(String, &'static str)> {
    if way.maxspeed_forward.is_none() && way.maxspeed_backward.is_none() {
        return None;
    }
    let mid = 0.5 * (s.from + s.to);
    let edge_heading = edge.heading_at(mid, 2.0);
    let travel = if s.dir.ri == 0 { edge_heading } else { reverse_heading(edge_heading) };
    let forward = angle_diff(travel, way.line.project(edge.point_at(mid)).heading) < std::f64::consts::FRAC_PI_2;
    if forward {
        way.maxspeed_forward.clone().map(|v| (v, "osm_maxspeed:forward"))
    } else {
        way.maxspeed_backward.clone().map(|v| (v, "osm_maxspeed:backward"))
    }
}

/// Schreibt die segmentierte Ausgabe (Ersatz für snapping_network_enriched.fgb).
pub fn write_output(p: &Prepared, cfg: &Config, segs: &[OutSegment], path: &std::path::Path) -> Result<usize> {
    let transfer = &cfg.assemble.transfer_attributes;
    let mut fields: Vec<(&str, FieldKind)> = vec![
        ("sfid", FieldKind::Int),
        ("element_nr", FieldKind::Str),
        ("beginnt_bei_vp", FieldKind::Str),
        ("endet_bei_vp", FieldKind::Str),
        ("Länge", FieldKind::Int),
        ("ri", FieldKind::Int),
        ("Bezirksnummer", FieldKind::Str),
        ("strassenname", FieldKind::Str),
    ];
    fields.extend(transfer.iter().map(|a| (a.as_str(), FieldKind::Str)));
    fields.extend([
        ("tilda_ids", FieldKind::Str),
        ("data_source", FieldKind::Str),
        ("edge_source", FieldKind::Str),
        ("hmm_konfidenz", FieldKind::Real),
        ("hmm_regel", FieldKind::Str),
        ("hmm_kandidaten", FieldKind::Int),
    ]);
    let mut order: Vec<&OutSegment> = segs.iter().collect();
    order.sort_by(|a, b| {
        let (ea, eb) = (&p.net.edges[a.dir.edge as usize], &p.net.edges[b.dir.edge as usize]);
        ea.element_nr.cmp(&eb.element_nr).then(a.dir.ri.cmp(&b.dir.ri)).then(a.from.total_cmp(&b.from))
    });
    let rows = order.into_iter().enumerate().map(|(i, s)| {
        let e = &p.net.edges[s.dir.edge as usize];
        let geom = e.line.substring(s.from, s.to);
        let mid = e.line.point_at(0.5 * (s.from + s.to));
        let way = s.winner.map(|w| &p.ways[w as usize]);
        let mut v: Vec<Value> = vec![
            Value::Int(i as i64 + 1),
            e.element_nr.as_str().into(),
            e.beginnt_bei_vp.as_deref().into(),
            e.endet_bei_vp.as_deref().into(),
            Value::Int(s.len().round() as i64),
            Value::Int(s.dir.ri as i64),
            p.districts.lookup(mid).into(),
            e.strassenname.as_deref().into(),
        ];
        let maxspeed = way.and_then(|w| directional_maxspeed(w, &e.line, s));
        for a in transfer {
            let val = match way {
                Some(_) if a == MAXSPEED && maxspeed.is_some() => maxspeed.as_ref().map(|m| m.0.clone()),
                Some(_) if a == MAXSPEED_SOURCE && maxspeed.is_some() => maxspeed.as_ref().map(|m| m.1.to_string()),
                Some(w) => w.attr(&p.schema, a).map(str::to_string),
                None if a == "fuehr" => Some(cfg.assemble.no_infra_fuehr.clone()),
                None => None,
            };
            v.push(Value::Str(val));
        }
        let ids: Vec<&str> = s.ways.iter().map(|w| p.ways[*w as usize].attr(&p.schema, "tilda_id").unwrap_or(&p.ways[*w as usize].tilda_id)).collect();
        v.push(Value::Str((!ids.is_empty()).then(|| ids.join(";"))));
        v.push(Value::Str(way.map(|w| w.data_source.to_string())));
        v.push(e.edge_source.as_deref().into());
        v.push(Value::Real(s.score));
        v.push(s.rule.as_str().into());
        v.push(Value::Int(s.n_candidates as i64));
        (Geometry::LineString(geom), v)
    });
    let n = io::write_fgb(path, "edges_enriched", GeomType::LineString, &fields, rows)?;
    info!("Ausgabe geschrieben: {} ({} Teilsegmente)", path.display(), n);
    Ok(n)
}

#[cfg(test)]
mod tests {
    use std::sync::Arc;

    use geo::Coord;

    use super::*;
    use crate::model::DirEdge;

    fn line(pts: &[(f64, f64)]) -> Polyline {
        Polyline::new(pts.iter().map(|&(x, y)| Coord { x, y }).collect())
    }

    fn way(pts: &[(f64, f64)], forward: Option<&str>, backward: Option<&str>) -> TildaWay {
        TildaWay {
            idx: 0,
            data_source: Arc::from("streets"),
            tilda_id: "way/1".into(),
            line: line(pts),
            attrs: vec![],
            oneway: false,
            dual_carriageway: false,
            fuehr: String::new(),
            category: String::new(),
            traffic_sign: String::new(),
            name_norm: String::new(),
            from_node: None,
            to_node: None,
            maxspeed_forward: forward.map(str::to_string),
            maxspeed_backward: backward.map(str::to_string),
        }
    }

    fn segment(ri: u8) -> OutSegment {
        OutSegment { dir: DirEdge::new(0, ri), from: 0.0, to: 100.0, winner: Some(0), ways: vec![0], rule: String::new(), score: 0.0, n_candidates: 1 }
    }

    #[test]
    fn directional_maxspeed_follows_travel_direction() {
        let edge = line(&[(0.0, 0.0), (100.0, 0.0)]);
        let way_same = way(&[(0.0, 2.0), (100.0, 2.0)], Some("30"), Some("50"));
        let way_reversed = way(&[(100.0, 2.0), (0.0, 2.0)], Some("30"), Some("50"));
        assert_eq!(directional_maxspeed(&way_same, &edge, &segment(0)), Some(("30".into(), "osm_maxspeed:forward")));
        assert_eq!(directional_maxspeed(&way_same, &edge, &segment(1)), Some(("50".into(), "osm_maxspeed:backward")));
        assert_eq!(directional_maxspeed(&way_reversed, &edge, &segment(0)), Some(("50".into(), "osm_maxspeed:backward")));
        assert_eq!(directional_maxspeed(&way_reversed, &edge, &segment(1)), Some(("30".into(), "osm_maxspeed:forward")));
    }

    #[test]
    fn directional_maxspeed_is_none_without_value_for_direction() {
        let edge = line(&[(0.0, 0.0), (100.0, 0.0)]);
        let only_forward = way(&[(0.0, 2.0), (100.0, 2.0)], Some("30"), None);
        assert!(directional_maxspeed(&only_forward, &edge, &segment(1)).is_none());
        assert!(directional_maxspeed(&way(&[(0.0, 2.0), (100.0, 2.0)], None, None), &edge, &segment(0)).is_none());
    }
}
