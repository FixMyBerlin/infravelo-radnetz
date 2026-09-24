//! R-Tree über alle Kantensegmente für die Kandidatensuche.

use geo::Coord;
use rstar::{AABB, PointDistance, RTree, RTreeObject};
use rustc_hash::FxHashMap;

use super::Edge;
use crate::geom::{Projection, project_segment};

#[derive(Debug, Clone)]
pub struct SegEntry {
    pub edge: u32,
    pub seg: u32,
    a: [f64; 2],
    b: [f64; 2],
}

impl RTreeObject for SegEntry {
    type Envelope = AABB<[f64; 2]>;

    fn envelope(&self) -> Self::Envelope {
        AABB::from_corners(self.a, self.b)
    }
}

impl PointDistance for SegEntry {
    fn distance_2(&self, p: &[f64; 2]) -> f64 {
        let (_, d, _) = project_segment(
            Coord { x: p[0], y: p[1] },
            Coord { x: self.a[0], y: self.a[1] },
            Coord { x: self.b[0], y: self.b[1] },
        );
        d * d
    }
}

#[derive(Debug)]
pub struct SpatialIndex {
    tree: RTree<SegEntry>,
}

/// Nächstgelegene Projektion eines Punkts auf eine Kante (Digitalisierungsrichtung).
#[derive(Debug, Clone, Copy)]
pub struct EdgeHit {
    pub edge: u32,
    pub proj: Projection,
}

impl SpatialIndex {
    pub fn build(edges: &[Edge]) -> SpatialIndex {
        let mut entries = Vec::new();
        for (i, e) in edges.iter().enumerate() {
            for (s, w) in e.line.coords.windows(2).enumerate() {
                entries.push(SegEntry { edge: i as u32, seg: s as u32, a: [w[0].x, w[0].y], b: [w[1].x, w[1].y] });
            }
        }
        SpatialIndex { tree: RTree::bulk_load(entries) }
    }

    /// Alle Kanten im Radius, je Kante die nächstgelegene Projektion, aufsteigend nach Abstand.
    pub fn edges_within(&self, edges: &[Edge], p: Coord<f64>, radius: f64) -> Vec<EdgeHit> {
        let mut best: FxHashMap<u32, EdgeHit> = FxHashMap::default();
        for entry in self.tree.locate_within_distance([p.x, p.y], radius * radius) {
            let proj = edges[entry.edge as usize].line.project_on_segment(p, entry.seg as usize);
            let hit = EdgeHit { edge: entry.edge, proj };
            best.entry(entry.edge)
                .and_modify(|h| {
                    if proj.dist < h.proj.dist {
                        *h = hit;
                    }
                })
                .or_insert(hit);
        }
        let mut hits: Vec<EdgeHit> = best.into_values().collect();
        hits.sort_by(|a, b| a.proj.dist.total_cmp(&b.proj.dist).then(a.edge.cmp(&b.edge)));
        hits
    }

    /// Kleinster Abstand zu einer Kante außer `exclude` (für den Topologie-Report).
    pub fn nearest_other(&self, edges: &[Edge], p: Coord<f64>, exclude: u32, radius: f64) -> Option<EdgeHit> {
        self.edges_within(edges, p, radius).into_iter().find(|h| h.edge != exclude)
    }
}
