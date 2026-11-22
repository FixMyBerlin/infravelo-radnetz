//! TILDA-Wege laden und zu Traces (Beobachtungsfolgen) aufbereiten.
//! Die TILDA-Topologie wird nur bei `trace.strategy = "topology"` genutzt (siehe `chain`).

pub mod chain;
pub mod sample;

use std::sync::Arc;

use anyhow::Result;
use tracing::info;

use crate::config::{Config, TraceConfig, TraceStrategy};
use crate::geom::Polyline;
use crate::io;
use crate::model::{AttrSchema, Observation, TildaWay, Trace};

/// Felder, die intern für das Matching benötigt werden (zusätzlich zu `transfer_attributes`).
const INTERNAL_FIELDS: [&str; 11] = [
    "tilda_id",
    "fuehr",
    "verkehrsri",
    "tilda_oneway",
    "tilda_category",
    "tilda_traffic_sign",
    "tilda_name",
    "from_node",
    "to_node",
    "tilda_maxspeed_forward",
    "tilda_maxspeed_backward",
];

/// Lädt alle konfigurierten TILDA-Quellen. `keep` filtert Wege (z. B. `--clip`).
/// Mit `postgres.enabled` kommen sie aus der pgRouting-Tabelle `postgres.input_edges`.
pub fn load_ways(cfg: &Config, schema: &AttrSchema, keep: impl Fn(&Polyline) -> bool) -> Result<Vec<TildaWay>> {
    if cfg.postgres.enabled {
        return load_ways_pg(cfg, schema, keep);
    }
    let mut fields: Vec<&str> = INTERNAL_FIELDS.to_vec();
    fields.extend(schema.names.iter().map(String::as_str));
    let mut ways = Vec::new();
    for src in &cfg.paths.tilda {
        let path = cfg.resolve(&src.path);
        let data_source: Arc<str> = Arc::from(src.data_source.as_str());
        let raw = io::read_lines(&path, None, &fields)?;
        let before = ways.len();
        for f in raw {
            let internal = &f.fields[..INTERNAL_FIELDS.len()];
            let attrs = f.fields[INTERNAL_FIELDS.len()..].to_vec();
            let tilda_id = internal[0].clone().unwrap_or_else(|| format!("{}/ohne-id-{}", data_source, ways.len()));
            let nparts = f.lines.len();
            for (part, ls) in f.lines.iter().enumerate() {
                let line = Polyline::from_linestring(ls);
                if line.coords.len() < 2 || line.length() < 0.05 || !keep(&line) {
                    continue;
                }
                ways.push(TildaWay {
                    db_id: None,
                    idx: ways.len() as u32,
                    data_source: data_source.clone(),
                    tilda_id: if nparts > 1 { format!("{tilda_id}#{part}") } else { tilda_id.clone() },
                    line,
                    attrs: attrs.clone(),
                    oneway: internal[2].as_deref() == Some("Einrichtungsverkehr"),
                    dual_carriageway: internal[3].as_deref() == Some("yes_dual_carriageway"),
                    fuehr: internal[1].clone().unwrap_or_default(),
                    category: internal[4].clone().unwrap_or_default(),
                    traffic_sign: internal[5].clone().unwrap_or_default(),
                    name_norm: normalize_name(internal[6].as_deref().unwrap_or("")),
                    from_node: internal[7].as_deref().and_then(|v| v.parse().ok()),
                    to_node: internal[8].as_deref().and_then(|v| v.parse().ok()),
                    maxspeed_forward: internal[9].clone(),
                    maxspeed_backward: internal[10].clone(),
                });
            }
        }
        info!("TILDA {}: {} Wege geladen ({})", data_source, ways.len() - before, path.display());
    }
    Ok(ways)
}

/// Felder der pgRouting-Tabelle, die das Matching selbst braucht (Spalten der Schnittstelle).
const PG_INTERNAL: [(&str, &str); 12] = [
    ("input_ref", "_input_ref"),
    ("source::text", "_source"),
    ("target::text", "_target"),
    ("CASE WHEN reverse_cost < 0 THEN 'yes' ELSE 'no' END", "_oneway"),
    ("match_key", "_match_key"),
    // Fachattribute für Regeln und Sonderfälle (noch TILDA-spezifisch, aus attrs)
    ("attrs->>'fuehr'", "_fuehr"),
    ("attrs->>'tilda_oneway'", "_tilda_oneway"),
    ("attrs->>'tilda_category'", "_tilda_category"),
    ("attrs->>'tilda_traffic_sign'", "_tilda_traffic_sign"),
    ("id::text", "_id"),
    ("attrs->>'tilda_maxspeed_forward'", "_tilda_maxspeed_forward"),
    ("attrs->>'tilda_maxspeed_backward'", "_tilda_maxspeed_backward"),
];

fn sql_literal(s: &str) -> String {
    format!("'{}'", s.replace('\'', "''"))
}

fn sql_ident(s: &str) -> String {
    format!("\"{}\"", s.replace('"', "\"\""))
}

/// Lädt die Wege aus `postgres.input_edges`, je `paths.tilda[].data_source` die Zeilen mit
/// gleicher `trace_group`, in `id`-Reihenfolge. Topologie aus `source`/`target`,
/// Einrichtungswege aus `reverse_cost < 0`, Name aus `match_key` (bereits normalisiert),
/// übertragene Attribute aus `attrs`.
fn load_ways_pg(cfg: &Config, schema: &AttrSchema, keep: impl Fn(&Polyline) -> bool) -> Result<Vec<TildaWay>> {
    let table = &cfg.postgres.input_edges;
    let conninfo = cfg.postgres.conninfo()?;
    let mut select: Vec<String> = PG_INTERNAL.iter().map(|(expr, alias)| format!("{expr} AS {alias}")).collect();
    select.extend(schema.names.iter().map(|n| format!("attrs->>{} AS {}", sql_literal(n), sql_ident(n))));
    let mut fields: Vec<&str> = PG_INTERNAL.iter().map(|(_, alias)| *alias).collect();
    fields.extend(schema.names.iter().map(String::as_str));
    let mut ways = Vec::new();
    for src in &cfg.paths.tilda {
        let data_source: Arc<str> = Arc::from(src.data_source.as_str());
        let sql = format!(
            "SELECT {}, geom FROM {table} WHERE trace_group = {} ORDER BY id",
            select.join(", "),
            sql_literal(&src.data_source)
        );
        let raw = io::read_lines_sql(&conninfo, &sql, &fields)?;
        let before = ways.len();
        for f in raw {
            let internal = &f.fields[..PG_INTERNAL.len()];
            let attrs = f.fields[PG_INTERNAL.len()..].to_vec();
            let tilda_id = internal[0].clone().unwrap_or_else(|| format!("{}/ohne-id-{}", data_source, ways.len()));
            let [ls] = f.lines.as_slice() else {
                anyhow::bail!("{table}: Weg {tilda_id} ist kein einfacher LineString");
            };
            let line = Polyline::from_linestring(ls);
            if line.coords.len() < 2 || line.length() < 0.05 || !keep(&line) {
                continue;
            }
            ways.push(TildaWay {
                db_id: internal[9].as_deref().and_then(|v| v.parse().ok()),
                idx: ways.len() as u32,
                data_source: data_source.clone(),
                tilda_id,
                line,
                attrs,
                oneway: internal[3].as_deref() == Some("yes"),
                dual_carriageway: internal[6].as_deref() == Some("yes_dual_carriageway"),
                fuehr: internal[5].clone().unwrap_or_default(),
                category: internal[7].clone().unwrap_or_default(),
                traffic_sign: internal[8].clone().unwrap_or_default(),
                name_norm: internal[4].clone().unwrap_or_default(),
                from_node: internal[1].as_deref().and_then(|v| v.parse().ok()),
                to_node: internal[2].as_deref().and_then(|v| v.parse().ok()),
                maxspeed_forward: internal[10].clone(),
                maxspeed_backward: internal[11].clone(),
            });
        }
        info!("{table} ({}): {} Wege geladen", data_source, ways.len() - before);
    }
    if ways.is_empty() {
        anyhow::bail!("{table}: keine Wege für trace_group {:?}", cfg.paths.tilda.iter().map(|t| &t.data_source).collect::<Vec<_>>());
    }
    Ok(ways)
}

/// Bildet Traces aus den Wegen gemäß `trace.strategy`.
pub fn build_traces(cfg: &Config, ways: &[TildaWay]) -> Vec<Trace> {
    match cfg.trace.strategy {
        TraceStrategy::Single => ways
            .iter()
            .enumerate()
            .map(|(i, w)| Trace { id: i as u32, ways: vec![w.idx], kontext_ways: vec![], obs: sample::sample_way(w, 0.0, false, &cfg.trace) })
            .collect(),
        TraceStrategy::Topology => {
            let chains = chain::build_chains(ways, &cfg.trace);
            let joined = chains.iter().filter(|c| c.len() > 1).count();
            info!("Topologie-Traces: {} Wege -> {} Traces ({} aus mehreren Wegen)", ways.len(), chains.len(), joined);
            let topo = chain::Topologie::new(ways, &cfg.trace);
            let traces: Vec<Trace> = chains
                .into_iter()
                .enumerate()
                .map(|(i, steps)| {
                    let (vor, nach) = topo.kontext(&steps, cfg.trace.context_m, cfg.trace.context_alle_zweige);
                    topology_trace(i as u32, ways, &vor, &steps, &nach, &cfg.trace)
                })
                .collect();
            if cfg.trace.context_m > 0.0 {
                let mit = traces.iter().filter(|t| !t.kontext_ways.is_empty()).count();
                info!("Kontext: {mit} Traces mit Anlauf/Auslauf (bis {} m)", cfg.trace.context_m);
            }
            traces
        }
    }
}

/// Trace aus Anlauf (`vor`), eigenen Schritten und Auslauf (`nach`): Beobachtungen in Fahrtrichtung, die des
/// Kontexts markiert und auf `context_m` vor dem ersten bzw. nach dem letzten eigenen Weg gekürzt.
pub fn topology_trace(id: u32, ways: &[TildaWay], vor: &[chain::Step], steps: &[chain::Step], nach: &[chain::Step], cfg: &TraceConfig) -> Trace {
    // Tastet einen Schritt ab und schiebt `offset` um seine Länge weiter.
    fn sample(ways: &[TildaWay], s: &chain::Step, kontext: bool, offset: &mut f64, cfg: &TraceConfig, obs: &mut Vec<Observation>) {
        let w = &ways[s.way as usize];
        obs.extend(sample::sample_way(w, *offset, s.reversed, cfg).into_iter().map(|mut o| {
            o.kontext = kontext;
            o
        }));
        *offset += w.line.length();
    }
    let mut obs = Vec::new();
    let mut offset = 0.0;
    for s in vor {
        sample(ways, s, true, &mut offset, cfg, &mut obs);
    }
    let start = offset;
    for s in steps {
        sample(ways, s, false, &mut offset, cfg, &mut obs);
    }
    let end = offset;
    for s in nach {
        sample(ways, s, true, &mut offset, cfg, &mut obs);
    }
    obs.retain(|o| !o.kontext || (o.trace_s >= start - cfg.context_m - 1e-9 && o.trace_s <= end + cfg.context_m + 1e-9));
    Trace {
        id,
        ways: steps.iter().map(|s| s.way).collect(),
        kontext_ways: vor.iter().chain(nach).map(|s| s.way).collect(),
        obs,
    }
}

/// Normalisiert Straßennamen für den Vergleich (Kleinschreibung, "str." -> "straße", ohne Leerzeichen).
pub fn normalize_name(name: &str) -> String {
    let lower = name.trim().to_lowercase();
    let lower = lower.replace("str.", "straße").replace("strasse", "straße");
    lower.chars().filter(|c| !c.is_whitespace() && *c != '-').collect()
}

#[cfg(test)]
mod tests {
    use super::normalize_name;

    #[test]
    fn names_are_normalized() {
        assert_eq!(normalize_name("Karl-Marx-Str."), normalize_name("Karl-Marx-Straße"));
        assert_eq!(normalize_name(" Sonnenallee "), "sonnenallee");
    }
}
