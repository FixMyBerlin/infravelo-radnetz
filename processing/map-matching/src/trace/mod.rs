//! TILDA-Wege laden und zu Traces (Beobachtungsfolgen) aufbereiten.
//! Die TILDA-Topologie wird nirgends vorausgesetzt.

pub mod sample;

use std::sync::Arc;

use anyhow::Result;
use tracing::info;

use crate::config::{Config, TraceStrategy};
use crate::geom::Polyline;
use crate::io;
use crate::model::{AttrSchema, TildaWay, Trace};

/// Felder, die intern für das Matching benötigt werden (zusätzlich zu `transfer_attributes`).
const INTERNAL_FIELDS: [&str; 7] = ["tilda_id", "fuehr", "verkehrsri", "tilda_oneway", "tilda_category", "tilda_traffic_sign", "tilda_name"];

/// Lädt alle konfigurierten TILDA-Quellen. `keep` filtert Wege (z. B. `--clip`).
pub fn load_ways(cfg: &Config, schema: &AttrSchema, keep: impl Fn(&Polyline) -> bool) -> Result<Vec<TildaWay>> {
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
                });
            }
        }
        info!("TILDA {}: {} Wege geladen ({})", data_source, ways.len() - before, path.display());
    }
    Ok(ways)
}

/// Bildet Traces aus den Wegen gemäß `trace.strategy`.
pub fn build_traces(cfg: &Config, ways: &[TildaWay]) -> Vec<Trace> {
    match cfg.trace.strategy {
        TraceStrategy::Single => ways
            .iter()
            .enumerate()
            .map(|(i, w)| Trace { id: i as u32, ways: vec![w.idx], obs: sample::sample_way(w, 0.0, &cfg.trace) })
            .collect(),
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
