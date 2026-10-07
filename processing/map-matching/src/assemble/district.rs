//! Bezirkszuordnung (zweistellige Bezirksnummer aus dem Feld `gem`).

use std::path::Path;

use anyhow::Result;
use geo::{BoundingRect, Contains, Coord, MultiPolygon, Point, Rect};

use crate::io;

pub struct Districts {
    items: Vec<(String, MultiPolygon<f64>, Rect<f64>)>,
}

impl Districts {
    pub fn load(path: &Path) -> Result<Districts> {
        let items = io::read_polygons(path, &["gem"])?
            .into_iter()
            .filter_map(|f| {
                let gem = f.fields[0].clone()?;
                let code = gem.chars().rev().take(2).collect::<Vec<_>>().into_iter().rev().collect::<String>();
                let bbox = f.geom.bounding_rect()?;
                Some((code, f.geom, bbox))
            })
            .collect();
        Ok(Districts { items })
    }

    pub fn empty() -> Districts {
        Districts { items: Vec::new() }
    }

    /// Bezirksnummer des Bezirks, der den Punkt enthält.
    pub fn lookup(&self, c: Coord<f64>) -> Option<&str> {
        let p = Point(c);
        self.items
            .iter()
            .find(|(_, g, r)| r.min().x <= c.x && c.x <= r.max().x && r.min().y <= c.y && c.y <= r.max().y && g.contains(&p))
            .map(|(code, _, _)| code.as_str())
    }
}
