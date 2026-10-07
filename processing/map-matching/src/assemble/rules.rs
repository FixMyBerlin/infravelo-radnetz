//! Fachliche Regel-Engine: Welcher TILDA-Weg bekommt ein Kantenstück?
//! Die Regeln stehen in der Konfiguration und lassen sich ohne Codeänderung verfeinern.

use crate::config::{Predicate, PreferRule, RulesConfig, TierRule};
use crate::model::TildaWay;

#[derive(Debug, Clone)]
pub struct RuleEngine {
    prefer: Vec<PreferRule>,
    tiers: Vec<TierRule>,
}

/// Ergebnis einer Auswahl.
#[derive(Debug, Clone, PartialEq)]
pub struct Choice {
    pub way: u32,
    pub score: f64,
    /// Welche Regel entschieden hat (für Debug/QA).
    pub rule: String,
}

impl RuleEngine {
    pub fn new(cfg: &RulesConfig) -> RuleEngine {
        let mut tiers = cfg.tiers.clone();
        tiers.sort_by_key(|t| t.rank);
        RuleEngine { prefer: cfg.prefer.clone(), tiers }
    }

    /// Rang und Name des ersten passenden Tiers (nicht passend: letzter Rang + 1).
    pub fn tier(&self, way: &TildaWay) -> (u32, &str) {
        self.tiers
            .iter()
            .find(|t| matches(&t.when, way))
            .map(|t| (t.rank, t.name.as_str()))
            .unwrap_or((u32::MAX, "ohne Tier"))
    }

    /// Wählt aus konkurrierenden (Weg, Güte)-Paaren den Gewinner.
    pub fn choose(&self, cands: &[(u32, f64)], ways: &[TildaWay]) -> Option<Choice> {
        if cands.is_empty() {
            return None;
        }
        if cands.len() == 1 {
            return Some(Choice { way: cands[0].0, score: cands[0].1, rule: "einziger Kandidat".into() });
        }
        let mut set: Vec<(u32, f64)> = cands.to_vec();
        let mut rule: Option<String> = None;
        for p in &self.prefer {
            let has_winner = set.iter().any(|(w, _)| matches(&p.winner, &ways[*w as usize]));
            let has_loser = set.iter().any(|(w, _)| matches(&p.loser, &ways[*w as usize]) && !matches(&p.winner, &ways[*w as usize]));
            if has_winner && has_loser {
                set.retain(|(w, _)| {
                    let way = &ways[*w as usize];
                    !(matches(&p.loser, way) && !matches(&p.winner, way))
                });
                rule = Some(format!("Vorrang: {}", p.name));
            }
        }
        let ranked: Vec<(u32, f64, u32, &str)> = set
            .iter()
            .map(|&(w, s)| {
                let (r, n) = self.tier(&ways[w as usize]);
                (w, s, r, n)
            })
            .collect();
        let best_rank = ranked.iter().map(|r| r.2).min()?;
        let distinct_ranks = ranked.iter().any(|r| r.2 != best_rank);
        let best = ranked
            .iter()
            .filter(|r| r.2 == best_rank)
            .max_by(|a, b| a.1.total_cmp(&b.1).then(b.0.cmp(&a.0)))?;
        let rule = rule.unwrap_or_else(|| {
            if distinct_ranks { format!("Rang: {}", best.3) } else { format!("HMM-Güte ({})", best.3) }
        });
        Some(Choice { way: best.0, score: best.1, rule })
    }
}

/// Prüft ein Prädikat (alle gesetzten Felder UND-verknüpft).
pub fn matches(p: &Predicate, way: &TildaWay) -> bool {
    if let Some(ds) = &p.data_source
        && !ds.iter().any(|d| d == &*way.data_source)
    {
        return false;
    }
    if let Some(f) = &p.fuehr
        && !f.iter().any(|v| v == &way.fuehr)
    {
        return false;
    }
    if let Some(c) = &p.category_prefix
        && !c.iter().any(|v| way.category.starts_with(v.as_str()))
    {
        return false;
    }
    if let Some(signs) = &p.traffic_sign_any
        && !signs.iter().any(|s| has_traffic_sign(&way.traffic_sign, s))
    {
        return false;
    }
    if let Some(signs) = &p.traffic_sign_none
        && signs.iter().any(|s| has_traffic_sign(&way.traffic_sign, s))
    {
        return false;
    }
    true
}

/// Prüft, ob ein OSM-`traffic_sign`-Wert (z. B. "DE:237,1022-10") ein Zeichen enthält.
/// "244" passt auch auf "244.1" (Unterzeichen), nicht aber auf "2440".
pub fn has_traffic_sign(value: &str, sign: &str) -> bool {
    value
        .split([',', ';'])
        .map(|t| t.trim().trim_start_matches("DE:"))
        .any(|t| t == sign || (t.starts_with(sign) && t[sign.len()..].starts_with(['.', '['])))
}

#[cfg(test)]
mod tests {
    use std::sync::Arc;

    use geo::Coord;

    use super::*;
    use crate::geom::Polyline;

    fn way(idx: u32, source: &str, fuehr: &str, sign: &str) -> TildaWay {
        TildaWay {
            idx,
            data_source: Arc::from(source),
            tilda_id: format!("way/{idx}"),
            line: Polyline::new(vec![Coord { x: 0.0, y: 0.0 }, Coord { x: 1.0, y: 0.0 }]),
            attrs: vec![],
            oneway: true,
            dual_carriageway: false,
            fuehr: fuehr.into(),
            category: String::new(),
            traffic_sign: sign.into(),
            name_norm: String::new(),
        }
    }

    fn engine() -> RuleEngine {
        let text = std::fs::read_to_string(concat!(env!("CARGO_MANIFEST_DIR"), "/config/default.toml")).unwrap();
        let v: toml::Value = toml::from_str(&text).unwrap();
        let rules: RulesConfig = v["rules"].clone().try_into().unwrap();
        RuleEngine::new(&rules)
    }

    #[test]
    fn rva_beats_mixed_traffic_beats_paths() {
        let e = engine();
        let ways = vec![
            way(0, "paths", "Sonstige Wege (Gehwege, Wege durch Grünflächen, Plätze)", ""),
            way(1, "streets", "Mischverkehr mit motorisiertem Verkehr", ""),
            way(2, "bikelanes", "Schutzstreifen", ""),
        ];
        assert_eq!(e.choose(&[(0, 0.0), (1, -1.0), (2, -5.0)], &ways).unwrap().way, 2);
        assert_eq!(e.choose(&[(0, 0.0), (1, -3.0)], &ways).unwrap().way, 1);
    }

    #[test]
    fn bus_lane_beats_unsigned_sidewalk_cycleway_only() {
        let e = engine();
        let ways = vec![
            way(0, "bikelanes", "Radweg", "none"),
            way(1, "bikelanes", "Bussonderfahrstreifen mit Radverkehr frei (Z245 mit Z1022‐10)", "DE:245,1022-10"),
            way(2, "bikelanes", "Radweg", "DE:237"),
        ];
        let c = e.choose(&[(0, 0.0), (1, -2.0)], &ways).unwrap();
        assert_eq!(c.way, 1);
        assert!(c.rule.starts_with("Vorrang"));
        // beschilderter Radweg: kein Vorrang, HMM-Güte entscheidet
        assert_eq!(e.choose(&[(2, 0.0), (1, -2.0)], &ways).unwrap().way, 2);
    }

    #[test]
    fn traffic_sign_parsing() {
        assert!(has_traffic_sign("DE:237", "237"));
        assert!(has_traffic_sign("DE:239,1022-10", "1022-10"));
        assert!(has_traffic_sign("DE:244.1,1020-30", "244"));
        assert!(!has_traffic_sign("DE:2370", "237"));
        assert!(!has_traffic_sign("none", "237"));
    }
}
