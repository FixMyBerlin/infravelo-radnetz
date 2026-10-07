//! Übergangsmodell: Passt die Netzdistanz zwischen zwei Kandidaten zur
//! zurückgelegten Strecke entlang der Trace?

use crate::config::HmmConfig;
use crate::model::Candidate;
use crate::network::routing::Router;

/// log p(b | a) = -|d_route - d_trace| / beta, `-inf` wenn im RVN nicht erreichbar.
pub fn log_transition(router: &mut Router, cfg: &HmmConfig, a: &Candidate, b: &Candidate, d_trace: f64) -> f64 {
    let limit = d_trace * cfg.route_limit_factor + cfg.route_limit_extra_m;
    match router.distance(a.dir, a.s, b.dir, b.s, limit, cfg.backward_tolerance_m) {
        Some(d_route) => -(d_route - d_trace).abs() / cfg.beta_m,
        None => f64::NEG_INFINITY,
    }
}

/// Routing-Limit für einen Schritt (auch für die Pfadrekonstruktion).
pub fn route_limit(cfg: &HmmConfig, d_trace: f64) -> f64 {
    d_trace * cfg.route_limit_factor + cfg.route_limit_extra_m
}
