//! Kerntypen, die zwischen den Verarbeitungsschritten ausgetauscht werden.

use std::sync::Arc;

use geo::Coord;
use rustc_hash::FxHashMap;
use serde::Serialize;

use crate::geom::Polyline;

/// Gerichtete RVN-Kante: `ri = 0` Digitalisierungsrichtung, `ri = 1` Gegenrichtung.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, PartialOrd, Ord, Serialize)]
pub struct DirEdge {
    pub edge: u32,
    pub ri: u8,
}

impl DirEdge {
    pub fn new(edge: u32, ri: u8) -> DirEdge {
        DirEdge { edge, ri }
    }

    pub fn reversed(self) -> DirEdge {
        DirEdge { edge: self.edge, ri: 1 - self.ri }
    }
}

/// Schema der übernommenen Attribute (Name -> Spaltenindex in `TildaWay::attrs`).
#[derive(Debug, Clone)]
pub struct AttrSchema {
    pub names: Vec<String>,
    index: FxHashMap<String, usize>,
}

impl AttrSchema {
    pub fn new(names: &[String]) -> AttrSchema {
        let index = names.iter().enumerate().map(|(i, n)| (n.clone(), i)).collect();
        AttrSchema { names: names.to_vec(), index }
    }

    pub fn idx(&self, name: &str) -> Option<usize> {
        self.index.get(name).copied()
    }
}

/// Ein TILDA-Weg (ein OSM-Way bzw. eine TILDA-Teilgeometrie) mit Attributen.
#[derive(Debug, Clone)]
pub struct TildaWay {
    pub idx: u32,
    pub data_source: Arc<str>,
    pub tilda_id: String,
    pub line: Polyline,
    /// Werte in der Reihenfolge von `AttrSchema::names`.
    pub attrs: Vec<Option<String>>,
    /// `verkehrsri == Einrichtungsverkehr`: gilt nur in Digitalisierungsrichtung.
    pub oneway: bool,
    /// `tilda_oneway == yes_dual_carriageway`.
    pub dual_carriageway: bool,
    pub fuehr: String,
    pub category: String,
    pub traffic_sign: String,
    /// Normalisierter Straßenname (leer, wenn unbekannt).
    pub name_norm: String,
}

impl TildaWay {
    pub fn attr<'a>(&'a self, schema: &AttrSchema, name: &str) -> Option<&'a str> {
        schema.idx(name).and_then(|i| self.attrs[i].as_deref())
    }
}

/// Eine Beobachtung entlang einer Trace.
#[derive(Debug, Clone, Copy, Serialize)]
pub struct Observation {
    #[serde(skip)]
    pub p: Coord<f64>,
    /// Kurs in Richtung der Trace (Radiant).
    pub heading: f64,
    /// Index des TILDA-Wegs.
    pub way: u32,
    /// Position entlang der gesamten Trace (m).
    pub trace_s: f64,
}

/// Eine Trace: Folge von Beobachtungen über einen oder mehrere TILDA-Wege.
#[derive(Debug, Clone)]
pub struct Trace {
    pub id: u32,
    pub ways: Vec<u32>,
    pub obs: Vec<Observation>,
}

/// Ein Kandidat (Zustand) für eine Beobachtung.
#[derive(Debug, Clone, Copy, Serialize)]
pub struct Candidate {
    pub dir: DirEdge,
    /// Position entlang der gerichteten Kante (m, in Fahrtrichtung).
    pub s: f64,
    pub dist: f64,
    pub log_emission: f64,
}

/// Einem TILDA-Weg zugeordnetes Stück einer gerichteten Kante.
/// Positionen `from < to` beziehen sich immer auf die Digitalisierungsrichtung der Kante.
#[derive(Debug, Clone, Copy, Serialize)]
pub struct Interval {
    pub dir: DirEdge,
    pub from: f64,
    pub to: f64,
    pub way: u32,
    /// Mittlere log-Emission der beteiligten Beobachtungen (Güte des Matches).
    pub score: f64,
    pub n_obs: u32,
    /// true, wenn das Intervall aus einem Zweirichtungs-Weg gespiegelt wurde.
    pub mirrored: bool,
}

/// Ein Teilsegment der Ausgabe.
#[derive(Debug, Clone)]
pub struct OutSegment {
    pub dir: DirEdge,
    pub from: f64,
    pub to: f64,
    /// Gewinnender TILDA-Weg (None = keine Radinfrastruktur).
    pub winner: Option<u32>,
    /// Alle TILDA-Wege, die zu diesem (verschmolzenen) Teilsegment beigetragen haben.
    pub ways: Vec<u32>,
    pub rule: String,
    pub score: f64,
    /// Anzahl konkurrierender TILDA-Wege auf dem Stück.
    pub n_candidates: u32,
}

impl OutSegment {
    pub fn len(&self) -> f64 {
        self.to - self.from
    }
}
