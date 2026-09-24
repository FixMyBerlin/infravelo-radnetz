//! HMM-/Viterbi-basiertes Map-Matching von TILDA-Wegen auf das Radvorrangsnetz.
//!
//! Ablauf: RVN-Graph (strikte Topologie) -> TILDA-Traces -> HMM/Viterbi je Trace
//! (parallel) -> Intervalle je gerichteter Kante -> Regel-Engine & Aufteilung ->
//! segmentierte Ausgabe (Ersatz für `snapping_network_enriched.fgb`).

pub mod assemble;
pub mod commands;
pub mod config;
pub mod debug;
pub mod eval;
pub mod geom;
pub mod hmm;
pub mod io;
pub mod logging;
pub mod model;
pub mod network;
pub mod pipeline;
pub mod trace;
