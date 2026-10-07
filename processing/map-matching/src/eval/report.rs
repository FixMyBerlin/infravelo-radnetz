//! Evaluationsbericht (Markdown + CSV + Abweichungs-Geodatei).

use std::fmt::Write as _;
use std::path::Path;

use anyhow::Result;
use geo::Geometry;

use super::{EvalResult, LoadStats, pct};
use crate::io::{self, FieldKind, GeomType, Value};
use crate::network::Network;

pub struct ReportMeta<'a> {
    pub title: &'a str,
    pub reference: &'a Path,
    pub candidate: &'a str,
    pub ref_stats: &'a LoadStats,
    pub note: &'a str,
}

fn km(m: f64) -> String {
    format!("{:.1} km", m / 1000.0)
}

pub fn markdown(res: &EvalResult, meta: &ReportMeta) -> String {
    let mut s = String::new();
    let _ = writeln!(s, "# {}\n", meta.title);
    let _ = writeln!(s, "- Referenz: `{}`", meta.reference.display());
    let _ = writeln!(s, "- Kandidat: `{}`", meta.candidate);
    let _ = writeln!(
        s,
        "- Referenz-Features: {} (nicht im Netz: {}, nicht projizierbar: {})",
        meta.ref_stats.features, meta.ref_stats.not_in_network, meta.ref_stats.not_projectable
    );
    if !meta.note.is_empty() {
        let _ = writeln!(s, "- Hinweis: {}", meta.note);
    }
    let _ = writeln!(s, "\n## Haupt-KPI\n");
    let _ = writeln!(s, "| Kennzahl | Wert |\n|---|---|");
    let _ = writeln!(s, "| **`fuehr`-Übereinstimmung (Anteil Referenzlänge)** | **{:.1} %** |", res.fuehr_score());
    let _ = writeln!(s, "| Referenzlänge | {} |", km(res.reference_m));
    let _ = writeln!(s, "| Kandidatenlänge | {} |", km(res.candidate_m));
    let _ = writeln!(s, "| Gemeinsam abgedeckte Länge | {} ({:.1} %) |", km(res.both_m), pct(res.both_m, res.reference_m));
    let _ = writeln!(
        s,
        "| Richtungen (element_nr, ri): Referenz / Kandidat / nur Ref. / nur Kand. | {} / {} / {} / {} |",
        res.dirs_reference, res.dirs_candidate, res.dirs_only_reference, res.dirs_only_candidate
    );
    let _ = writeln!(
        s,
        "| Abweichende `fuehr`-Länge | {} ({:.1} % der Referenz) |",
        km(res.disagreement_m),
        pct(res.disagreement_m, res.reference_m)
    );
    let _ = writeln!(
        s,
        "| davon an Stellen mit manuellen Eingriffen des Altverfahrens | {} ({:.1} % der Abweichungen) |",
        km(res.disagreement_manual_m),
        pct(res.disagreement_manual_m, res.disagreement_m)
    );
    let _ = writeln!(
        s,
        "| `fuehr`-Übereinstimmung ohne manuell beeinflusste Stellen | {:.1} % |",
        pct(res.fuehr_agree_m, res.reference_m - res.disagreement_manual_m)
    );

    let _ = writeln!(s, "\n## Attribut-Übereinstimmung (auf gemeinsam abgedeckter Länge)\n");
    let _ = writeln!(s, "| Attribut | Übereinstimmung | verglichene Länge |\n|---|---|---|");
    for a in &res.attributes {
        let _ = writeln!(s, "| `{}` | {:.1} % | {} |", a.attribute, pct(a.agree_m, a.compared_m), km(a.compared_m));
    }

    let _ = writeln!(s, "\n## `fuehr` je Bezirk\n");
    let _ = writeln!(s, "| Bezirk | Referenzlänge | Übereinstimmung |\n|---|---|---|");
    for (b, d) in &res.districts {
        let _ = writeln!(s, "| {b} | {} | {:.1} % |", km(d.reference_m), pct(d.fuehr_agree_m, d.reference_m));
    }

    let _ = writeln!(s, "\n## Größte Verwechslungen `fuehr` (Referenz → Kandidat)\n");
    let _ = writeln!(s, "| Referenz | Kandidat | Länge | Anteil Referenz |\n|---|---|---|---|");
    let mut pairs: Vec<(&String, &String, f64)> = res
        .confusion_fuehr
        .iter()
        .flat_map(|(r, m)| m.iter().map(move |(c, l)| (r, c, *l)))
        .filter(|(r, c, _)| r != c)
        .collect();
    pairs.sort_by(|a, b| b.2.total_cmp(&a.2));
    for (r, c, l) in pairs.iter().take(20) {
        let _ = writeln!(s, "| {r} | {c} | {} | {:.2} % |", km(*l), pct(*l, res.reference_m));
    }

    let _ = writeln!(s, "\n## Längenanteile `fuehr`\n");
    let _ = writeln!(s, "| fuehr | Referenz | Kandidat | übereinstimmend |\n|---|---|---|---|");
    let mut ref_tot: std::collections::BTreeMap<&String, f64> = Default::default();
    let mut cand_tot: std::collections::BTreeMap<&String, f64> = Default::default();
    for (r, m) in &res.confusion_fuehr {
        for (c, l) in m {
            *ref_tot.entry(r).or_default() += l;
            *cand_tot.entry(c).or_default() += l;
        }
    }
    let mut keys: Vec<&String> = ref_tot.keys().chain(cand_tot.keys()).copied().collect();
    keys.sort();
    keys.dedup();
    keys.sort_by(|a, b| ref_tot.get(b).unwrap_or(&0.0).total_cmp(ref_tot.get(a).unwrap_or(&0.0)));
    for k in keys {
        let same = res.confusion_fuehr.get(k).and_then(|m| m.get(k)).copied().unwrap_or(0.0);
        let _ = writeln!(
            s,
            "| {k} | {} | {} | {:.1} % |",
            km(*ref_tot.get(k).unwrap_or(&0.0)),
            km(*cand_tot.get(k).unwrap_or(&0.0)),
            pct(same, *ref_tot.get(k).unwrap_or(&0.0))
        );
    }
    s
}

/// Schreibt Bericht, CSV-Dateien und Abweichungs-Geodatei nach `dir`.
pub fn write_all(dir: &Path, net: &Network, res: &EvalResult, meta: &ReportMeta) -> Result<()> {
    std::fs::create_dir_all(dir)?;
    std::fs::write(dir.join("report.md"), markdown(res, meta))?;
    std::fs::write(dir.join("summary.json"), serde_json::to_string_pretty(res)?)?;

    let mut csv = String::from("attribut;uebereinstimmung_prozent;verglichen_m\n");
    for a in &res.attributes {
        let _ = writeln!(csv, "{};{:.2};{:.1}", a.attribute, pct(a.agree_m, a.compared_m), a.compared_m);
    }
    std::fs::write(dir.join("attributes.csv"), csv)?;

    let mut csv = String::from("bezirk;referenz_m;fuehr_uebereinstimmung_prozent\n");
    for (b, d) in &res.districts {
        let _ = writeln!(csv, "{b};{:.1};{:.2}", d.reference_m, pct(d.fuehr_agree_m, d.reference_m));
    }
    std::fs::write(dir.join("districts.csv"), csv)?;

    let mut csv = String::from("referenz_fuehr;kandidat_fuehr;laenge_m\n");
    for (r, m) in &res.confusion_fuehr {
        for (c, l) in m {
            let _ = writeln!(csv, "{r};{c};{l:.1}");
        }
    }
    std::fs::write(dir.join("confusion_fuehr.csv"), csv)?;

    let fields = [
        ("element_nr", FieldKind::Str),
        ("ri", FieldKind::Int),
        ("laenge_m", FieldKind::Real),
        ("ref_fuehr", FieldKind::Str),
        ("kand_fuehr", FieldKind::Str),
        ("ref_tilda_id", FieldKind::Str),
        ("kand_tilda_id", FieldKind::Str),
        ("manuell", FieldKind::Int),
    ];
    let rows = res.disagreements.iter().map(|d| {
        let e = &net.edges[d.edge as usize];
        (
            Geometry::LineString(e.line.substring(d.from, d.to)),
            vec![
                e.element_nr.as_str().into(),
                Value::Int(d.ri as i64),
                Value::Real(d.to - d.from),
                d.ref_fuehr.as_str().into(),
                d.cand_fuehr.as_str().into(),
                d.ref_tilda_id.as_deref().into(),
                d.cand_tilda_id.as_deref().into(),
                Value::Int(d.manual as i64),
            ],
        )
    });
    io::write_fgb(&dir.join("disagreements.fgb"), "abweichungen", GeomType::LineString, &fields, rows)?;
    Ok(())
}
