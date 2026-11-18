//! Orchestrierung: Laden -> Traces -> HMM/Viterbi (parallel) -> Aufteilung -> Ausgabe.

use std::collections::BTreeMap;
use std::path::PathBuf;
use std::time::Instant;

use anyhow::{Context, Result, bail};
use geo::{BoundingRect, Contains, Coord, Geometry, MultiPolygon, Point, Rect};
use indicatif::{ParallelProgressIterator, ProgressBar, ProgressStyle};
use rayon::prelude::*;
use rustc_hash::FxHashMap;
use serde::Serialize;
use tracing::info;

use crate::assemble::district::Districts;
use crate::assemble::rules::RuleEngine;
use crate::assemble::{AssembleOutput, Assembler};
use crate::config::Config;
use crate::eval::LinSeg;
use crate::geom::Polyline;
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
    let (traces, matches, mut stats) = match_traces(p, cfg, show_progress);
    let intervals: Vec<Interval> = matches.iter().flat_map(|m| m.intervals.iter().copied()).collect();
    let assembled = assemble_intervals(p, cfg, &intervals, &mut stats);
    MatchResult { traces, matches, assembled, stats }
}

/// Nur das Matching (Traces, HMM, Kennzahlen), ohne Aufteilung.
pub fn match_traces(p: &Prepared, cfg: &Config, show_progress: bool) -> (Vec<Trace>, Vec<TraceMatch>, RunStats) {
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

    stats.traces = traces.len();
    for (tr, m) in traces.iter().zip(&matches) {
        // nur eigene Beobachtungen (ohne Kontext anderer Traces)
        let own: Vec<_> = tr.obs.iter().zip(&m.states).filter(|(o, _)| !o.kontext).map(|(_, s)| s).collect();
        let with_cands = own.iter().any(|s| s.n_candidates > 0);
        stats.traces_with_candidates += with_cands as usize;
        stats.traces_matched += (!m.intervals.is_empty()) as usize;
        stats.observations += own.len();
        stats.observations_without_candidates += own.iter().filter(|s| s.n_candidates == 0).count();
        stats.observations_null_state += own.iter().filter(|s| s.chosen.is_none() && s.n_candidates > 0).count();
        stats.hmm_breaks += m.breaks.len();
        stats.dijkstra_runs += m.dijkstra_runs;
    }
    (traces, matches, stats)
}

/// Stufe 7 (fachlich): Intervalle je gerichteter Referenzkante zu Teilsegmenten zusammenführen
/// (Regel-Engine, Lücken, kurze Stücke, Einbahn-Regel). Füllt die zugehörigen Kennzahlen.
pub fn assemble_intervals(p: &Prepared, cfg: &Config, intervals: &[Interval], stats: &mut RunStats) -> AssembleOutput {
    let t = Instant::now();
    let rules = RuleEngine::new(&cfg.rules);
    let assembler = Assembler { net: &p.net, ways: &p.ways, schema: &p.schema, cfg: &cfg.assemble, rules: &rules };
    let assembled = assembler.run(intervals);
    stats.timings_s.insert("aufteilung".into(), t.elapsed().as_secs_f64());
    stats.intervals = intervals.len();
    stats.segments = assembled.segments.len();
    stats.segments_without_infra = assembled.segments.iter().filter(|s| s.winner.is_none()).count();
    stats.oneway_edges = assembled.oneway_edges;
    stats.conflicts = assembled.conflicts.len();
    for s in &assembled.segments {
        let f = fuehr_of(p, cfg, s);
        *stats.length_by_fuehr_km.entry(f).or_default() += s.len() / 1000.0;
    }
    assembled
}

const INTERVAL_FIELDS: [(&str, FieldKind); 13] = [
    ("ord", FieldKind::Int),
    ("ref_id", FieldKind::Int),
    ("element_nr", FieldKind::Str),
    ("ri", FieldKind::Int),
    // Positionen und Güte als Text in kürzester exakter Darstellung: GDAL schreibt Gleitkommazahlen
    // nur mit 15 Stellen, das verschiebt einzelne Schnittpunkte. Danach in double precision umgewandelt.
    ("from_m", FieldKind::Str),
    ("to_m", FieldKind::Str),
    ("input_id", FieldKind::Int),
    ("input_ref", FieldKind::Str),
    ("trace_group", FieldKind::Str),
    ("trace_id", FieldKind::Int),
    ("score", FieldKind::Str),
    ("n_obs", FieldKind::Int),
    ("mirrored", FieldKind::Int),
];

/// Zwischenergebnis nach Stufe 6 nach PostGIS (`postgres.intervals`): je Intervall die
/// Referenzkante (`ref_id` = id in `postgres.reference_edges`) und Richtung `ri`, die Lage
/// `from_m`/`to_m` in Digitalisierungsrichtung der Referenzkante, der Eingangsweg (`input_id` =
/// id in `postgres.input_edges`) sowie Güte, Beobachtungen und ob das Intervall von einem
/// Zweirichtungsweg gespiegelt wurde. Die Geometrie ist das Stück der Referenzkante.
pub fn write_intervals_pg(p: &Prepared, cfg: &Config, matches: &[TraceMatch]) -> Result<usize> {
    let (schema, table) = cfg.postgres.intervals_table()?;
    let mut ord = 0i64;
    let rows = matches.iter().flat_map(|m| m.intervals.iter().map(move |iv| (m.trace_id, iv))).map(|(trace_id, iv)| {
        let e = &p.net.edges[iv.dir.edge as usize];
        let w = &p.ways[iv.way as usize];
        ord += 1;
        (
            Geometry::LineString(e.line.substring(iv.from, iv.to)),
            vec![
                Value::Int(ord),
                e.db_id.map_or(Value::Str(None), Value::Int),
                e.element_nr.as_str().into(),
                Value::Int(iv.dir.ri as i64),
                Value::Str(Some(iv.from.to_string())),
                Value::Str(Some(iv.to.to_string())),
                w.db_id.map_or(Value::Str(None), Value::Int),
                w.tilda_id.as_str().into(),
                (&*w.data_source).into(),
                Value::Int(trace_id as i64),
                Value::Str(Some(if iv.score.is_finite() { iv.score.to_string() } else { "NaN".into() })),
                Value::Int(iv.n_obs as i64),
                Value::Int(iv.mirrored as i64),
            ],
        )
    });
    let alter = format!(
        "ALTER TABLE {schema}.{table} ALTER COLUMN from_m TYPE double precision USING from_m::double precision, \
         ALTER COLUMN to_m TYPE double precision USING to_m::double precision, \
         ALTER COLUMN score TYPE double precision USING score::double precision"
    );
    let index = format!("CREATE INDEX ON {schema}.{table} (ref_id, ri)");
    let n = io::write_pg(&cfg.postgres.conninfo()?, schema, table, GeomType::LineString, &INTERVAL_FIELDS, rows, &[alter, index])?;
    info!("{n} Intervalle nach {schema}.{table} geschrieben");
    Ok(n)
}

/// Schreibt die Traces nach `<postgres.intervals>_traces`: je Weg einer Trace eine Zeile mit Position in der Trace,
/// Zahl der Beobachtungen, davon gematcht (nicht Null-Zustand), HMM-Brüche auf dem Weg und Geometrie des Wegs.
/// Kontext-Wege (Anlauf/Auslauf aus anderen Traces) stehen zusätzlich mit `kontext` = 1 darin (seq -1 = Anlauf,
/// n_wege und folgende = Auslauf); ihre Beobachtungen zählen nur dort.
pub fn write_traces_pg(p: &Prepared, cfg: &Config, traces: &[Trace], matches: &[TraceMatch]) -> Result<usize> {
    let (schema, table) = cfg.postgres.intervals_table()?;
    let table = format!("{table}_traces");
    let fields = [
        ("trace_id", FieldKind::Int),
        ("seq", FieldKind::Int),
        ("n_wege", FieldKind::Int),
        ("input_id", FieldKind::Int),
        ("input_ref", FieldKind::Str),
        ("n_obs", FieldKind::Int),
        ("n_gematcht", FieldKind::Int),
        ("n_brueche", FieldKind::Int),
        ("kontext", FieldKind::Int),
    ];
    let rows = traces.iter().zip(matches).flat_map(|(t, m)| {
        let mut obs: FxHashMap<(u32, bool), (i64, i64, i64)> = FxHashMap::default();
        for (i, (o, st)) in t.obs.iter().zip(&m.states).enumerate() {
            let e = obs.entry((o.way, o.kontext)).or_default();
            e.0 += 1;
            if st.chosen.is_some() {
                e.1 += 1;
            }
            if m.breaks.contains(&i) {
                e.2 += 1;
            }
        }
        // eigene Wege, dann Kontext-Wege (Anlauf seq -1, Auslauf ab n_wege)
        let first_own = t.obs.iter().position(|o| !o.kontext);
        let kontext = t.kontext_ways.iter().map(move |&w| {
            let anlauf = first_own.is_some_and(|f| t.obs[..f].iter().any(|o| o.way == w));
            (if anlauf { -1 } else { t.ways.len() as i64 }, w, true)
        });
        let own = t.ways.iter().enumerate().map(|(seq, &w)| (seq as i64, w, false));
        own.collect::<Vec<_>>().into_iter().chain(kontext).map(move |(seq, w, k)| {
            let way = &p.ways[w as usize];
            let (n, g, b) = obs.get(&(w, k)).copied().unwrap_or_default();
            (
                Geometry::LineString(way.line.to_linestring()),
                vec![
                    Value::Int(t.id as i64),
                    Value::Int(seq),
                    Value::Int(t.ways.len() as i64),
                    way.db_id.map_or(Value::Str(None), Value::Int),
                    way.tilda_id.as_str().into(),
                    Value::Int(n),
                    Value::Int(g),
                    Value::Int(b),
                    Value::Int(k as i64),
                ],
            )
        })
    });
    let index = format!("CREATE INDEX ON {schema}.{table} (input_id)");
    let n = io::write_pg(&cfg.postgres.conninfo()?, schema, &table, GeomType::LineString, &fields, rows, &[index])?;
    info!("{n} Trace-Wege nach {schema}.{table} geschrieben");
    Ok(n)
}

/// Schreibt die Verbindungsstücke des Viterbi-Pfads an Knoten des Eingangsnetzes (`TraceMatch::stubs`) nach
/// `<postgres.intervals>_stubs`: Kante, Richtung, Abschnitt, Weg davor und danach.
pub fn write_stubs_pg(p: &Prepared, cfg: &Config, matches: &[TraceMatch]) -> Result<usize> {
    let (schema, table) = cfg.postgres.intervals_table()?;
    let table = format!("{table}_stubs");
    let fields = [
        ("trace_id", FieldKind::Int),
        ("ref_id", FieldKind::Int),
        ("element_nr", FieldKind::Str),
        ("ri", FieldKind::Int),
        ("from_m", FieldKind::Real),
        ("to_m", FieldKind::Real),
        ("input_von", FieldKind::Int),
        ("input_nach", FieldKind::Int),
    ];
    let rows = matches.iter().flat_map(|m| m.stubs.iter().map(move |st| (m.trace_id, st))).map(|(trace_id, st)| {
        let e = &p.net.edges[st.dir.edge as usize];
        let id = |w: u32| p.ways[w as usize].db_id.map_or(Value::Str(None), Value::Int);
        (
            Geometry::LineString(e.line.substring(st.from, st.to)),
            vec![
                Value::Int(trace_id as i64),
                e.db_id.map_or(Value::Str(None), Value::Int),
                e.element_nr.as_str().into(),
                Value::Int(st.dir.ri as i64),
                Value::Real(st.from),
                Value::Real(st.to),
                id(st.way_from),
                id(st.way_to),
            ],
        )
    });
    let n = io::write_pg(&cfg.postgres.conninfo()?, schema, &table, GeomType::LineString, &fields, rows, &[])?;
    info!("{n} Verbindungsstücke nach {schema}.{table} geschrieben");
    Ok(n)
}

/// Liest die Intervalle aus `postgres.intervals` und ordnet sie über `ref_id`/`input_id` den
/// geladenen Kanten und Wegen zu. Intervalle ohne passende Kante oder Weg (z. B. außerhalb von
/// `--clip`) entfallen und werden gezählt.
pub fn read_intervals_pg(p: &Prepared, cfg: &Config) -> Result<Vec<Interval>> {
    use rustc_hash::FxHashMap;
    let edge_of: FxHashMap<i64, u32> = p.net.edges.iter().enumerate().filter_map(|(i, e)| e.db_id.map(|id| (id, i as u32))).collect();
    let way_of: FxHashMap<i64, u32> = p.ways.iter().filter_map(|w| w.db_id.map(|id| (id, w.idx))).collect();
    if edge_of.is_empty() || way_of.is_empty() {
        bail!("assemble braucht Referenz- und Eingangsnetz aus PostGIS (--pg)");
    }
    let table = &cfg.postgres.intervals;
    let fields = ["ref_id", "ri", "from_m", "to_m", "input_id", "score", "n_obs", "mirrored"];
    let sql = format!(
        "SELECT ref_id::text AS ref_id, ri::text AS ri, from_m::text AS from_m, to_m::text AS to_m, input_id::text AS input_id, \
         score::text AS score, n_obs::text AS n_obs, mirrored::text AS mirrored FROM {table} ORDER BY ord"
    );
    let rows = io::read_rows_sql(&cfg.postgres.conninfo()?, &sql, &fields)?;
    let (mut out, mut skipped) = (Vec::with_capacity(rows.len()), 0usize);
    for r in &rows {
        let num = |i: usize| r[i].as_deref().and_then(|v| v.parse::<f64>().ok());
        let int = |i: usize| r[i].as_deref().and_then(|v| v.parse::<i64>().ok());
        let (Some(edge), Some(way)) = (int(0).and_then(|id| edge_of.get(&id)), int(4).and_then(|id| way_of.get(&id))) else {
            skipped += 1;
            continue;
        };
        out.push(Interval {
            dir: crate::model::DirEdge::new(*edge, int(1).unwrap_or(0) as u8),
            from: num(2).unwrap_or(0.0),
            to: num(3).unwrap_or(0.0),
            way: *way,
            score: num(5).unwrap_or(f64::NAN),
            n_obs: int(6).unwrap_or(0) as u32,
            mirrored: int(7) == Some(1),
        });
    }
    info!("{} Intervalle aus {table} gelesen ({skipped} ohne passende Kante oder Weg)", out.len());
    Ok(out)
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
        for a in transfer {
            let val = match way {
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
