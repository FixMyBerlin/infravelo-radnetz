//! Topologie-Report des RVN: Stellen, an denen das Netz nicht topologisch korrekt ist.
//! An diesen Stellen existiert kein Übergang, das HMM matcht nicht darüber hinweg.

use geo::{Coord, Geometry, Point};
use rustc_hash::{FxHashMap, FxHashSet};
use serde::Serialize;
use tracing::info;

use super::Network;
use crate::geom::dist;
use crate::io::{FieldKind, Value};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, PartialOrd, Ord)]
pub enum IssueKind {
    /// Endpunkt liegt auf dem Inneren einer anderen Kante, ohne gemeinsamen Knoten.
    TJunctionWithoutNode,
    /// Endpunkt hat einen anderen Endpunkt/eine Kante in <= gap_report_m, ist aber nicht verbunden.
    Gap,
    /// Offenes Ende ohne Nachbarn (Sackgasse oder Netzrand) – kein Fehler, nur Hinweis.
    FreeEnd,
    /// Unterschiedliche Koordinaten für dieselbe VP-ID bzw. mehrere VP-IDs an einem Knoten.
    VpIdInconsistent,
    /// MultiLineString mit mehreren Teilen.
    Multipart,
}

impl IssueKind {
    pub fn label(self) -> &'static str {
        match self {
            IssueKind::TJunctionWithoutNode => "T-Stoß ohne Knoten",
            IssueKind::Gap => "Lücke",
            IssueKind::FreeEnd => "freies Ende",
            IssueKind::VpIdInconsistent => "VP-ID inkonsistent",
            IssueKind::Multipart => "Multipart",
        }
    }

    /// Echte Topologiefehler (verhindern Übergänge, die es geben müsste).
    pub fn is_error(self) -> bool {
        matches!(self, IssueKind::TJunctionWithoutNode | IssueKind::Gap)
    }
}

#[derive(Debug, Clone, Serialize)]
pub struct TopologyIssue {
    pub kind: IssueKind,
    #[serde(skip)]
    pub at: Coord<f64>,
    pub element_nr: String,
    pub other_element_nr: Option<String>,
    pub distance_m: f64,
    pub detail: String,
}

#[derive(Debug, Default, Clone, Serialize)]
pub struct TopologyReport {
    pub issues: Vec<TopologyIssue>,
    pub components: usize,
    pub largest_component_edges: usize,
    pub counts: Vec<(String, usize)>,
}

impl TopologyReport {
    pub fn errors(&self) -> usize {
        self.issues.iter().filter(|i| i.kind.is_error()).count()
    }

    pub fn fgb_fields() -> Vec<(&'static str, FieldKind)> {
        vec![
            ("typ", FieldKind::Str),
            ("fehler", FieldKind::Int),
            ("element_nr", FieldKind::Str),
            ("anderes_element_nr", FieldKind::Str),
            ("abstand_m", FieldKind::Real),
            ("detail", FieldKind::Str),
        ]
    }

    pub fn fgb_rows(&self) -> impl Iterator<Item = (Geometry<f64>, Vec<Value>)> + '_ {
        self.issues.iter().map(|i| {
            (
                Geometry::Point(Point(i.at)),
                vec![
                    i.kind.label().into(),
                    Value::Int(i.kind.is_error() as i64),
                    i.element_nr.as_str().into(),
                    i.other_element_nr.as_deref().into(),
                    Value::Real(i.distance_m),
                    i.detail.as_str().into(),
                ],
            )
        })
    }

    pub fn log_summary(&self) {
        info!(
            "Topologie: {} Komponenten (größte: {} Kanten), {} echte Fehler",
            self.components,
            self.largest_component_edges,
            self.errors()
        );
        for (k, n) in &self.counts {
            info!("  {k}: {n}");
        }
    }
}

pub fn analyze(net: &Network, tolerance: f64, gap_report_m: f64, multipart: usize) -> TopologyReport {
    let mut issues = Vec::new();
    // Endpunkte mit Grad 1: offen. Klassifikation nach nächstem Nachbarn.
    let mut endpoint_nodes: FxHashMap<u32, Vec<u32>> = FxHashMap::default();
    for (i, e) in net.edges.iter().enumerate() {
        endpoint_nodes.entry(e.from).or_default().push(i as u32);
        endpoint_nodes.entry(e.to).or_default().push(i as u32);
    }
    for (node, edges) in &endpoint_nodes {
        if edges.len() != 1 {
            continue;
        }
        let edge = edges[0];
        let at = net.nodes[*node as usize];
        let nearest_line = net.spatial.nearest_other(&net.edges, at, edge, gap_report_m);
        let nearest_node = net
            .nodes
            .iter()
            .enumerate()
            .filter(|(n, c)| *n as u32 != *node && (c.x - at.x).abs() <= gap_report_m && (c.y - at.y).abs() <= gap_report_m)
            .map(|(n, c)| (n, dist(*c, at)))
            .min_by(|a, b| a.1.total_cmp(&b.1));
        let (kind, other, d, detail) = match (nearest_line, nearest_node) {
            (Some(h), _) if h.proj.dist <= tolerance => (
                IssueKind::TJunctionWithoutNode,
                Some(h.edge),
                h.proj.dist,
                format!("Endpunkt liegt {:.1} m entlang der anderen Kante", h.proj.s),
            ),
            (Some(h), nn) => {
                let d = nn.map_or(h.proj.dist, |(_, d)| d.min(h.proj.dist));
                (IssueKind::Gap, Some(h.edge), d, "nächste Kante/Knoten nicht verbunden".to_string())
            }
            (None, Some((_, d))) => (IssueKind::Gap, None, d, "nächster Knoten nicht verbunden".to_string()),
            (None, None) => (IssueKind::FreeEnd, None, f64::NAN, String::new()),
        };
        issues.push(TopologyIssue {
            kind,
            at,
            element_nr: net.edges[edge as usize].element_nr.clone(),
            other_element_nr: other.map(|o| net.edges[o as usize].element_nr.clone()),
            distance_m: d,
            detail,
        });
    }

    // VP-ID-Konsistenz (nur Hinweis, die Knoten werden geometrisch gebildet).
    let mut vp_nodes: FxHashMap<&str, FxHashSet<u32>> = FxHashMap::default();
    for e in &net.edges {
        if let Some(v) = &e.beginnt_bei_vp {
            vp_nodes.entry(v).or_default().insert(e.from);
        }
        if let Some(v) = &e.endet_bei_vp {
            vp_nodes.entry(v).or_default().insert(e.to);
        }
    }
    let mut vp_list: Vec<_> = vp_nodes.into_iter().filter(|(_, n)| n.len() > 1).collect();
    vp_list.sort_by(|a, b| a.0.cmp(b.0));
    for (vp, nodes) in vp_list {
        let mut nodes: Vec<u32> = nodes.into_iter().collect();
        nodes.sort_unstable();
        let first = net.nodes[nodes[0] as usize];
        let spread = nodes.iter().map(|n| dist(net.nodes[*n as usize], first)).fold(0.0, f64::max);
        let edge = net.edges.iter().find(|e| e.beginnt_bei_vp.as_deref() == Some(vp) || e.endet_bei_vp.as_deref() == Some(vp));
        issues.push(TopologyIssue {
            kind: IssueKind::VpIdInconsistent,
            at: first,
            element_nr: edge.map(|e| e.element_nr.clone()).unwrap_or_default(),
            other_element_nr: None,
            distance_m: spread,
            detail: format!("VP {vp} an {} verschiedenen Knoten", nodes.len()),
        });
    }

    // Zusammenhangskomponenten (ungerichtet).
    let mut parent: Vec<u32> = (0..net.nodes.len() as u32).collect();
    fn find(p: &mut [u32], mut a: u32) -> u32 {
        while p[a as usize] != a {
            p[a as usize] = p[p[a as usize] as usize];
            a = p[a as usize];
        }
        a
    }
    for e in &net.edges {
        let (a, b) = (find(&mut parent, e.from), find(&mut parent, e.to));
        if a != b {
            parent[b as usize] = a;
        }
    }
    let mut comp_edges: FxHashMap<u32, usize> = FxHashMap::default();
    for e in &net.edges {
        *comp_edges.entry(find(&mut parent, e.from)).or_default() += 1;
    }

    let mut counts: FxHashMap<&'static str, usize> = FxHashMap::default();
    for i in &issues {
        *counts.entry(i.kind.label()).or_default() += 1;
    }
    if multipart > 0 {
        counts.insert(IssueKind::Multipart.label(), multipart);
    }
    let mut counts: Vec<(String, usize)> = counts.into_iter().map(|(k, v)| (k.to_string(), v)).collect();
    counts.sort();
    issues.sort_by(|a, b| a.kind.cmp(&b.kind).then(a.element_nr.cmp(&b.element_nr)));
    TopologyReport {
        issues,
        components: comp_edges.len(),
        largest_component_edges: comp_edges.values().copied().max().unwrap_or(0),
        counts,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::network::test_util::network;

    #[test]
    fn detects_t_junction_and_gap() {
        let net = network(&[
            &[(0.0, 0.0), (20.0, 0.0)],
            &[(10.0, 0.0), (10.0, 10.0)], // T-Stoß ohne Knoten
            &[(20.3, 0.0), (30.0, 0.0)],  // Lücke 0,3 m
        ]);
        let kinds: Vec<IssueKind> = net.topology.issues.iter().map(|i| i.kind).collect();
        assert!(kinds.contains(&IssueKind::TJunctionWithoutNode));
        assert!(kinds.contains(&IssueKind::Gap));
    }
}
