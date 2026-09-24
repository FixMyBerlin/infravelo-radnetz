//! Emissionsmodell: Wie gut passt eine Beobachtung zu einer gerichteten RVN-Kante?

use crate::config::HmmConfig;
use crate::geom::{angle_diff, reverse_heading};
use crate::model::{Candidate, DirEdge, Observation, TildaWay};
use crate::network::Network;

/// Einzelterme der log-Emission (für Debug-Ausgaben).
#[derive(Debug, Clone, Copy, Default, serde::Serialize)]
pub struct EmissionTerms {
    pub distance: f64,
    pub heading: f64,
    pub side: f64,
    pub name: f64,
}

impl EmissionTerms {
    pub fn total(&self) -> f64 {
        self.distance + self.heading + self.side + self.name
    }
}

/// Prüft, ob für einen Weg der Seiten-Term gilt (Einrichtungs-RVA mit eigener Geometrie).
fn side_applies(way: &TildaWay) -> bool {
    way.oneway && &*way.data_source == "bikelanes"
}

/// log-Emission einer Beobachtung für eine gerichtete Kante.
/// `side_dir`: +1 links, -1 rechts der Fahrtrichtung der gerichteten Kante.
pub fn terms(cfg: &HmmConfig, way: &TildaWay, obs_heading: f64, dist: f64, edge_heading: f64, side_dir: f64, edge_name: &str) -> EmissionTerms {
    let z = dist / cfg.sigma_distance_m;
    let dtheta = angle_diff(obs_heading, edge_heading);
    let cos = dtheta.cos();
    // Zweirichtungs-Wege haben keine Fahrtrichtung: nur die Achse zählt.
    let heading = if way.oneway { cfg.heading_kappa * (cos - 1.0) } else { cfg.heading_kappa * (cos.abs() - 1.0) };
    let side = if side_applies(way) && dist >= cfg.side_min_distance_m && side_dir > 0.0 { -cfg.side_penalty } else { 0.0 };
    let name = if !way.name_norm.is_empty() && !edge_name.is_empty() && way.name_norm != edge_name {
        -cfg.name_mismatch_penalty
    } else {
        0.0
    };
    EmissionTerms { distance: -0.5 * z * z, heading, side, name }
}

/// Kandidaten (beide Richtungen jeder Kante im Radius), absteigend nach Emission, höchstens `max_candidates`.
pub fn candidates(net: &Network, cfg: &HmmConfig, way: &TildaWay, obs: &Observation) -> Vec<Candidate> {
    let hits = net.spatial.edges_within(&net.edges, obs.p, cfg.candidate_radius_m);
    let mut out = Vec::with_capacity(hits.len() * 2);
    for h in hits {
        let edge = &net.edges[h.edge as usize];
        for ri in 0..2u8 {
            let dir = DirEdge::new(h.edge, ri);
            let (s, heading, side_dir) = if ri == 0 {
                (h.proj.s, h.proj.heading, h.proj.side)
            } else {
                (edge.length() - h.proj.s, reverse_heading(h.proj.heading), -h.proj.side)
            };
            let t = terms(cfg, way, obs.heading, h.proj.dist, heading, side_dir, &edge.name_norm);
            out.push(Candidate { dir, s, dist: h.proj.dist, log_emission: t.total() });
        }
    }
    out.sort_by(|a, b| b.log_emission.total_cmp(&a.log_emission).then(a.dir.cmp(&b.dir)));
    out.truncate(cfg.max_candidates);
    out
}
