//! RVN-Netz als gerichteter Graph. Knoten entstehen geometrisch aus Endpunkten,
//! die innerhalb der numerischen Toleranz übereinstimmen – es wird nichts repariert.

pub mod routing;
pub mod spatial;
pub mod topology;

use std::path::Path;

use anyhow::{Result, bail};
use geo::Coord;
use rustc_hash::FxHashMap;
use tracing::{info, warn};

use crate::config::Config;
use crate::geom::Polyline;
use crate::io;
use crate::model::DirEdge;
use spatial::SpatialIndex;
use topology::TopologyReport;

/// Eine (ungerichtete) RVN-Kante mit Detailnetz-Attributen.
#[derive(Debug, Clone)]
pub struct Edge {
    pub element_nr: String,
    pub beginnt_bei_vp: Option<String>,
    pub endet_bei_vp: Option<String>,
    pub strassenname: Option<String>,
    pub verkehrsrichtung: Option<String>,
    pub edge_source: Option<String>,
    /// Normalisierter Straßenname für den Namens-Term der Emission.
    pub name_norm: String,
    pub line: Polyline,
    pub from: u32,
    pub to: u32,
}

impl Edge {
    pub fn length(&self) -> f64 {
        self.line.length()
    }
}

#[derive(Debug)]
pub struct Network {
    pub edges: Vec<Edge>,
    pub nodes: Vec<Coord<f64>>,
    /// Ausgehende gerichtete Kanten je Knoten.
    pub out: Vec<Vec<DirEdge>>,
    /// Kanten je element_nr (einige element_nr sind im RVN mehrfach vergeben).
    pub by_element: FxHashMap<String, Vec<u32>>,
    pub spatial: SpatialIndex,
    pub topology: TopologyReport,
}

const NETWORK_FIELDS: [&str; 6] = ["element_nr", "beginnt_bei_vp", "endet_bei_vp", "strassenname", "verkehrsrichtung", "edge_source"];

impl Network {
    /// Lädt das RVN und baut Graph, räumlichen Index und Topologie-Report.
    /// `keep` filtert Kanten (z. B. für `--clip`).
    pub fn load(cfg: &Config, path: &Path, keep: impl Fn(&Polyline) -> bool) -> Result<Network> {
        let raw = io::read_lines(path, None, &NETWORK_FIELDS)?;
        let mut edges = Vec::with_capacity(raw.len());
        let mut multipart = 0usize;
        for f in raw {
            let Some(element_nr) = f.fields[0].clone() else {
                warn!("RVN-Feature ohne element_nr übersprungen");
                continue;
            };
            if f.lines.len() > 1 {
                // Nicht zusammenhängende MultiLineStrings sind ein Topologiefehler: jeder Teil
                // bleibt eine eigene Kante; der Report weist sie aus.
                multipart += 1;
            }
            for line in &f.lines {
                let line = Polyline::from_linestring(line);
                if line.coords.len() < 2 || !keep(&line) {
                    continue;
                }
                edges.push(Edge {
                    element_nr: element_nr.clone(),
                    beginnt_bei_vp: f.fields[1].clone(),
                    endet_bei_vp: f.fields[2].clone(),
                    strassenname: f.fields[3].clone(),
                    verkehrsrichtung: f.fields[4].clone(),
                    edge_source: f.fields[5].clone(),
                    name_norm: crate::trace::normalize_name(f.fields[3].as_deref().unwrap_or("")),
                    line,
                    from: 0,
                    to: 0,
                });
            }
        }
        if edges.is_empty() {
            bail!("RVN enthält nach dem Filtern keine Kanten: {}", path.display());
        }
        let net = Network::build(edges, cfg.network.node_tolerance_m, cfg.network.gap_report_m, multipart);
        info!(
            "RVN geladen: {} Kanten, {} Knoten, {} Komponenten, {} Topologie-Auffälligkeiten",
            net.edges.len(),
            net.nodes.len(),
            net.topology.components,
            net.topology.issues.len()
        );
        Ok(net)
    }

    /// Baut den Graphen aus bereits geladenen Kanten (auch für Tests).
    pub fn build(mut edges: Vec<Edge>, tolerance: f64, gap_report_m: f64, multipart: usize) -> Network {
        let endpoints: Vec<Coord<f64>> = edges.iter().flat_map(|e| [e.line.start(), e.line.end()]).collect();
        let (node_of, nodes) = cluster_points(&endpoints, tolerance);
        for (i, e) in edges.iter_mut().enumerate() {
            e.from = node_of[2 * i];
            e.to = node_of[2 * i + 1];
        }
        let mut out = vec![Vec::new(); nodes.len()];
        for (i, e) in edges.iter().enumerate() {
            let i = i as u32;
            out[e.from as usize].push(DirEdge::new(i, 0));
            out[e.to as usize].push(DirEdge::new(i, 1));
        }
        let mut by_element: FxHashMap<String, Vec<u32>> = FxHashMap::default();
        for (i, e) in edges.iter().enumerate() {
            by_element.entry(e.element_nr.clone()).or_default().push(i as u32);
        }
        let duplicated = by_element.values().filter(|v| v.len() > 1).count();
        if duplicated > 0 {
            warn!("{duplicated} element_nr sind im RVN mehrfach vergeben (werden als getrennte Kanten geführt)");
        }
        let spatial = SpatialIndex::build(&edges);
        let mut net = Network { edges, nodes, out, by_element, spatial, topology: TopologyReport::default() };
        net.topology = topology::analyze(&net, tolerance, gap_report_m, multipart);
        net
    }

    pub fn dir_len(&self, d: DirEdge) -> f64 {
        self.edges[d.edge as usize].length()
    }

    /// Startknoten einer gerichteten Kante.
    pub fn dir_from(&self, d: DirEdge) -> u32 {
        let e = &self.edges[d.edge as usize];
        if d.ri == 0 { e.from } else { e.to }
    }

    /// Endknoten einer gerichteten Kante.
    pub fn dir_to(&self, d: DirEdge) -> u32 {
        let e = &self.edges[d.edge as usize];
        if d.ri == 0 { e.to } else { e.from }
    }

    /// Umrechnung einer Position in Fahrtrichtung in eine Position in Digitalisierungsrichtung.
    pub fn to_base(&self, d: DirEdge, s: f64) -> f64 {
        if d.ri == 0 { s } else { self.dir_len(d) - s }
    }

    /// Anzahl Kanten, die an einem Knoten enden oder beginnen.
    pub fn degree(&self, node: u32) -> usize {
        self.out[node as usize].len()
    }
}

/// Fasst Punkte zusammen, die (transitiv) höchstens `tol` voneinander entfernt sind.
/// Rückgabe: Knotenindex je Punkt und Knotenkoordinaten (erster Punkt des Clusters).
pub fn cluster_points(points: &[Coord<f64>], tol: f64) -> (Vec<u32>, Vec<Coord<f64>>) {
    let cell = tol.max(1e-6);
    let key = |c: Coord<f64>| ((c.x / cell).floor() as i64, (c.y / cell).floor() as i64);
    let mut grid: FxHashMap<(i64, i64), Vec<usize>> = FxHashMap::default();
    for (i, p) in points.iter().enumerate() {
        grid.entry(key(*p)).or_default().push(i);
    }
    let mut parent: Vec<usize> = (0..points.len()).collect();
    fn find(p: &mut [usize], mut a: usize) -> usize {
        while p[a] != a {
            p[a] = p[p[a]];
            a = p[a];
        }
        a
    }
    for (i, p) in points.iter().enumerate() {
        let (kx, ky) = key(*p);
        for dx in -1..=1 {
            for dy in -1..=1 {
                if let Some(list) = grid.get(&(kx + dx, ky + dy)) {
                    for &j in list {
                        if j > i && crate::geom::dist(*p, points[j]) <= tol {
                            let (a, b) = (find(&mut parent, i), find(&mut parent, j));
                            if a != b {
                                parent[b] = a;
                            }
                        }
                    }
                }
            }
        }
    }
    let mut node_of = vec![0u32; points.len()];
    let mut root_node: FxHashMap<usize, u32> = FxHashMap::default();
    let mut nodes = Vec::new();
    for i in 0..points.len() {
        let r = find(&mut parent, i);
        let n = *root_node.entry(r).or_insert_with(|| {
            nodes.push(points[r]);
            (nodes.len() - 1) as u32
        });
        node_of[i] = n;
    }
    (node_of, nodes)
}

#[cfg(test)]
pub(crate) mod test_util {
    use super::*;

    /// Baut ein Testnetz aus Polylinien (element_nr = "e{i}").
    pub fn network(lines: &[&[(f64, f64)]]) -> Network {
        let edges = lines
            .iter()
            .enumerate()
            .map(|(i, l)| Edge {
                element_nr: format!("e{i}"),
                beginnt_bei_vp: None,
                endet_bei_vp: None,
                strassenname: Some("Teststraße".into()),
                verkehrsrichtung: None,
                edge_source: None,
                name_norm: "teststraße".into(),
                line: Polyline::new(l.iter().map(|&(x, y)| Coord { x, y }).collect()),
                from: 0,
                to: 0,
            })
            .collect();
        Network::build(edges, 0.01, 10.0, 0)
    }
}

#[cfg(test)]
mod tests {
    use super::test_util::network;

    #[test]
    fn nodes_are_merged_within_tolerance_only() {
        let net = network(&[&[(0.0, 0.0), (10.0, 0.0)], &[(10.004, 0.0), (20.0, 0.0)], &[(20.5, 0.0), (30.0, 0.0)]]);
        assert_eq!(net.edges[0].to, net.edges[1].from);
        assert_ne!(net.edges[1].to, net.edges[2].from);
        assert_eq!(net.topology.components, 2);
    }
}
