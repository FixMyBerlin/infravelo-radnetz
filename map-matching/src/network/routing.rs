//! Kürzeste Wege auf dem gerichteten RVN-Graphen mit Distanzlimit und Cache.
//! Ein Router gehört genau einer Trace (kein Sperren nötig, rayon-freundlich).

use std::cmp::Ordering;
use std::collections::BinaryHeap;

use rustc_hash::FxHashMap;

use super::Network;
use crate::model::DirEdge;

#[derive(Debug, Clone, Copy)]
struct NodeLabel {
    dist: f64,
    /// Gerichtete Kante, über die der Knoten erreicht wurde (None am Startknoten).
    via: Option<DirEdge>,
}

#[derive(Debug)]
struct Tree {
    limit: f64,
    labels: FxHashMap<u32, NodeLabel>,
}

#[derive(PartialEq)]
struct HeapItem(f64, u32);

impl Eq for HeapItem {}

impl Ord for HeapItem {
    fn cmp(&self, other: &Self) -> Ordering {
        other.0.total_cmp(&self.0).then_with(|| self.1.cmp(&other.1))
    }
}

impl PartialOrd for HeapItem {
    fn partial_cmp(&self, other: &Self) -> Option<Ordering> {
        Some(self.cmp(other))
    }
}

pub struct Router<'a> {
    net: &'a Network,
    /// Schlüssel: (Startknoten, Kante, über die der Startknoten erreicht wurde).
    cache: FxHashMap<(u32, u32), Tree>,
    pub dijkstra_runs: u64,
}

impl<'a> Router<'a> {
    pub fn new(net: &'a Network) -> Router<'a> {
        Router { net, cache: FxHashMap::default(), dijkstra_runs: 0 }
    }

    /// Kürzeste-Wege-Baum ab dem Endknoten von `from` (ohne Wenden auf `from`).
    fn tree(&mut self, from: DirEdge, limit: f64) -> &Tree {
        let key = (self.net.dir_to(from), from.edge);
        let fresh = self.cache.get(&key).is_none_or(|t| t.limit < limit);
        if fresh {
            self.dijkstra_runs += 1;
            let tree = dijkstra(self.net, key.0, from.edge, limit);
            self.cache.insert(key, tree);
        }
        &self.cache[&key]
    }

    /// Netzdistanz von Position `sa` auf `a` zu Position `sb` auf `b` (beide in Fahrtrichtung).
    /// `None`, wenn nicht innerhalb von `limit` erreichbar. Wenden auf derselben Kante ist verboten.
    pub fn distance(&mut self, a: DirEdge, sa: f64, b: DirEdge, sb: f64, limit: f64, backward_tol: f64) -> Option<f64> {
        if a == b && sb >= sa - backward_tol {
            return Some((sb - sa).max(0.0));
        }
        if a.edge == b.edge && a.ri != b.ri {
            return None;
        }
        let rest = self.net.dir_len(a) - sa;
        if rest + sb > limit {
            return None;
        }
        let dst = self.net.dir_from(b);
        let tree = self.tree(a, limit - rest - sb);
        let d = tree.labels.get(&dst)?.dist;
        let total = rest + d + sb;
        (total <= limit).then_some(total)
    }

    /// Gerichtete Kanten, die zwischen `a` und `b` vollständig durchfahren werden.
    pub fn intermediate(&mut self, a: DirEdge, b: DirEdge, limit: f64) -> Vec<DirEdge> {
        if a.edge == b.edge {
            return Vec::new();
        }
        let net = self.net;
        let dst = net.dir_from(b);
        let tree = self.tree(a, limit);
        let mut path = Vec::new();
        let mut node = dst;
        while let Some(label) = tree.labels.get(&node) {
            match label.via {
                Some(d) => {
                    path.push(d);
                    node = net.dir_from(d);
                }
                None => break,
            }
            if path.len() > 10_000 {
                break;
            }
        }
        path.reverse();
        path
    }
}

/// Dijkstra über Knoten; Wenden (dieselbe Kante zurück) ist verboten, auch am Start (`in_edge`).
fn dijkstra(net: &Network, src: u32, in_edge: u32, limit: f64) -> Tree {
    let mut labels: FxHashMap<u32, NodeLabel> = FxHashMap::default();
    let mut heap = BinaryHeap::new();
    labels.insert(src, NodeLabel { dist: 0.0, via: None });
    heap.push(HeapItem(0.0, src));
    while let Some(HeapItem(d, node)) = heap.pop() {
        let Some(label) = labels.get(&node).copied() else { continue };
        if d > label.dist {
            continue;
        }
        let came_by = label.via.map_or(in_edge, |v| v.edge);
        for &de in &net.out[node as usize] {
            if de.edge == came_by {
                continue;
            }
            let nd = d + net.dir_len(de);
            if nd > limit {
                continue;
            }
            let to = net.dir_to(de);
            if labels.get(&to).is_none_or(|l| nd < l.dist) {
                labels.insert(to, NodeLabel { dist: nd, via: Some(de) });
                heap.push(HeapItem(nd, to));
            }
        }
    }
    Tree { limit, labels }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::network::test_util::network;

    #[test]
    fn distance_over_node_and_no_u_turn() {
        let net = network(&[&[(0.0, 0.0), (10.0, 0.0)], &[(10.0, 0.0), (20.0, 0.0)]]);
        let mut r = Router::new(&net);
        let a = DirEdge::new(0, 0);
        let b = DirEdge::new(1, 0);
        assert!((r.distance(a, 8.0, b, 3.0, 50.0, 1.0).unwrap() - 5.0).abs() < 1e-9);
        assert!(r.distance(a, 8.0, a.reversed(), 1.0, 50.0, 1.0).is_none());
        assert!(r.distance(b, 3.0, a, 8.0, 50.0, 1.0).is_none());
    }

    #[test]
    fn topology_gap_blocks_transition() {
        let net = network(&[&[(0.0, 0.0), (10.0, 0.0)], &[(10.3, 0.0), (20.0, 0.0)]]);
        let mut r = Router::new(&net);
        assert!(r.distance(DirEdge::new(0, 0), 9.0, DirEdge::new(1, 0), 1.0, 50.0, 1.0).is_none());
    }
}
