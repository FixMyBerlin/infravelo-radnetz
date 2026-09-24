//! Geometrie-Hilfen in metrischem CRS (EPSG:25833): Polylinie mit kumulierten
//! Längen, Projektion, Interpolation, Kurs und Teilstücke.

use geo::{Coord, LineString};

/// Polylinie mit vorberechneten kumulierten Längen.
#[derive(Debug, Clone)]
pub struct Polyline {
    pub coords: Vec<Coord<f64>>,
    /// `cum[i]` = Länge vom Anfang bis Stützpunkt i.
    pub cum: Vec<f64>,
}

/// Ergebnis einer Projektion eines Punkts auf eine Polylinie.
#[derive(Debug, Clone, Copy)]
pub struct Projection {
    /// Position entlang der Linie (m, ab Anfang).
    pub s: f64,
    /// Senkrechter Abstand (m).
    pub dist: f64,
    /// Vorzeichen der Seite: +1 links, -1 rechts (in Digitalisierungsrichtung), 0 auf der Linie.
    pub side: f64,
    /// Kurs der Linie am Projektionspunkt (Radiant, mathematisch: 0 = Osten, CCW).
    pub heading: f64,
    /// Index des Segments, auf das projiziert wurde.
    pub seg: usize,
}

impl Polyline {
    pub fn new(coords: Vec<Coord<f64>>) -> Polyline {
        let mut cum = Vec::with_capacity(coords.len());
        let mut acc = 0.0;
        cum.push(0.0);
        for w in coords.windows(2) {
            acc += dist(w[0], w[1]);
            cum.push(acc);
        }
        Polyline { coords, cum }
    }

    pub fn from_linestring(ls: &LineString<f64>) -> Polyline {
        let mut coords: Vec<Coord<f64>> = Vec::with_capacity(ls.0.len());
        for c in &ls.0 {
            if coords.last().is_none_or(|l| dist(*l, *c) > 0.0) {
                coords.push(*c);
            }
        }
        Polyline::new(coords)
    }

    pub fn length(&self) -> f64 {
        *self.cum.last().unwrap_or(&0.0)
    }

    pub fn start(&self) -> Coord<f64> {
        self.coords[0]
    }

    pub fn end(&self) -> Coord<f64> {
        *self.coords.last().unwrap()
    }

    pub fn segment_count(&self) -> usize {
        self.coords.len().saturating_sub(1)
    }

    /// Segmentindex, in dem Position `s` liegt.
    fn seg_at(&self, s: f64) -> usize {
        let n = self.segment_count();
        if n == 0 {
            return 0;
        }
        match self.cum.binary_search_by(|v| v.partial_cmp(&s).unwrap()) {
            Ok(i) => i.min(n - 1),
            Err(i) => (i.saturating_sub(1)).min(n - 1),
        }
    }

    pub fn point_at(&self, s: f64) -> Coord<f64> {
        if self.coords.len() == 1 {
            return self.coords[0];
        }
        let s = s.clamp(0.0, self.length());
        let i = self.seg_at(s);
        let (a, b) = (self.coords[i], self.coords[i + 1]);
        let seg_len = self.cum[i + 1] - self.cum[i];
        let t = if seg_len > 0.0 { (s - self.cum[i]) / seg_len } else { 0.0 };
        lerp(a, b, t)
    }

    /// Kurs (Radiant) zwischen den Punkten bei `s - window` und `s + window`.
    pub fn heading_at(&self, s: f64, window: f64) -> f64 {
        let len = self.length();
        let mut a = (s - window).max(0.0);
        let mut b = (s + window).min(len);
        if b - a < 1e-6 {
            a = (s - 0.5).max(0.0);
            b = (s + 0.5).min(len);
        }
        let (p, q) = (self.point_at(a), self.point_at(b));
        (q.y - p.y).atan2(q.x - p.x)
    }

    pub fn segment_heading(&self, seg: usize) -> f64 {
        let (a, b) = (self.coords[seg], self.coords[seg + 1]);
        (b.y - a.y).atan2(b.x - a.x)
    }

    /// Projektion auf ein einzelnes Segment.
    pub fn project_on_segment(&self, p: Coord<f64>, seg: usize) -> Projection {
        let (a, b) = (self.coords[seg], self.coords[seg + 1]);
        let (t, d, cross) = project_segment(p, a, b);
        let seg_len = self.cum[seg + 1] - self.cum[seg];
        Projection {
            s: self.cum[seg] + t * seg_len,
            dist: d,
            side: if cross > 1e-9 {
                1.0
            } else if cross < -1e-9 {
                -1.0
            } else {
                0.0
            },
            heading: (b.y - a.y).atan2(b.x - a.x),
            seg,
        }
    }

    /// Projektion auf die gesamte Linie (lineare Suche über alle Segmente).
    pub fn project(&self, p: Coord<f64>) -> Projection {
        let mut best: Option<Projection> = None;
        for seg in 0..self.segment_count() {
            let pr = self.project_on_segment(p, seg);
            if best.is_none_or(|b| pr.dist < b.dist) {
                best = Some(pr);
            }
        }
        best.unwrap_or(Projection { s: 0.0, dist: dist(p, self.coords[0]), side: 0.0, heading: 0.0, seg: 0 })
    }

    /// Teilstück zwischen den Positionen `a` und `b` (a < b) als LineString.
    pub fn substring(&self, a: f64, b: f64) -> LineString<f64> {
        let (a, b) = (a.clamp(0.0, self.length()), b.clamp(0.0, self.length()));
        let mut out = vec![self.point_at(a)];
        for i in 0..self.coords.len() {
            if self.cum[i] > a && self.cum[i] < b {
                out.push(self.coords[i]);
            }
        }
        out.push(self.point_at(b));
        LineString::from(out)
    }

    pub fn to_linestring(&self) -> LineString<f64> {
        LineString::from(self.coords.clone())
    }
}

pub fn dist(a: Coord<f64>, b: Coord<f64>) -> f64 {
    (a.x - b.x).hypot(a.y - b.y)
}

pub fn lerp(a: Coord<f64>, b: Coord<f64>, t: f64) -> Coord<f64> {
    Coord { x: a.x + (b.x - a.x) * t, y: a.y + (b.y - a.y) * t }
}

/// Projiziert `p` auf Segment `a-b`. Rückgabe: (t in [0,1], Abstand, Kreuzprodukt für die Seite).
pub fn project_segment(p: Coord<f64>, a: Coord<f64>, b: Coord<f64>) -> (f64, f64, f64) {
    let (dx, dy) = (b.x - a.x, b.y - a.y);
    let len2 = dx * dx + dy * dy;
    let t = if len2 > 0.0 { (((p.x - a.x) * dx + (p.y - a.y) * dy) / len2).clamp(0.0, 1.0) } else { 0.0 };
    let q = Coord { x: a.x + t * dx, y: a.y + t * dy };
    let cross = dx * (p.y - a.y) - dy * (p.x - a.x);
    (t, dist(p, q), cross)
}

/// Kleinster Winkel zwischen zwei Kursen (Radiant, 0..=PI).
pub fn angle_diff(a: f64, b: f64) -> f64 {
    let mut d = (a - b).rem_euclid(std::f64::consts::TAU);
    if d > std::f64::consts::PI {
        d = std::f64::consts::TAU - d;
    }
    d
}

pub fn reverse_heading(h: f64) -> f64 {
    let r = h + std::f64::consts::PI;
    if r > std::f64::consts::PI { r - std::f64::consts::TAU } else { r }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn line() -> Polyline {
        Polyline::new(vec![Coord { x: 0.0, y: 0.0 }, Coord { x: 10.0, y: 0.0 }, Coord { x: 10.0, y: 10.0 }])
    }

    #[test]
    fn projection_and_side() {
        let l = line();
        let p = l.project(Coord { x: 5.0, y: 2.0 });
        assert!((p.s - 5.0).abs() < 1e-9 && (p.dist - 2.0).abs() < 1e-9);
        assert_eq!(p.side, 1.0); // links der Digitalisierungsrichtung
        let q = l.project(Coord { x: 5.0, y: -2.0 });
        assert_eq!(q.side, -1.0);
    }

    #[test]
    fn substring_keeps_inner_vertices() {
        let l = line();
        let s = l.substring(5.0, 15.0);
        assert_eq!(s.0.len(), 3);
        assert!((s.0[1].x - 10.0).abs() < 1e-9 && (s.0[2].y - 5.0).abs() < 1e-9);
    }

    #[test]
    fn angle_diff_wraps() {
        assert!((angle_diff(3.1, -3.1) - (std::f64::consts::TAU - 6.2)).abs() < 1e-9);
    }
}
