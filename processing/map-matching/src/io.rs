//! Geodaten lesen und schreiben (GDAL). Alle Daten werden in EPSG:25833 erwartet.

use std::path::Path;

use anyhow::{Context, Result, bail};
use gdal::spatial_ref::SpatialRef;
use gdal::vector::{Feature, FieldDefn, LayerAccess, LayerOptions, OGRFieldType, OGRwkbGeometryType, ToGdal};
use gdal::{Dataset, DriverManager};
use geo::{Geometry, LineString, MultiPolygon};
use tracing::{debug, warn};

pub const EPSG: u32 = 25833;

/// Ein gelesenes Linien-Feature: Feldwerte (in der angefragten Reihenfolge) und Linienteile.
#[derive(Debug, Clone)]
pub struct LineFeature {
    pub fields: Vec<Option<String>>,
    pub lines: Vec<LineString<f64>>,
}

/// Ein gelesenes Polygon-Feature.
#[derive(Debug, Clone)]
pub struct PolygonFeature {
    pub fields: Vec<Option<String>>,
    pub geom: MultiPolygon<f64>,
}

fn open(path: &Path) -> Result<Dataset> {
    Dataset::open(path).with_context(|| format!("Datei nicht lesbar: {}", path.display()))
}

fn check_crs<L: LayerAccess>(layer: &L, path: &Path) -> Result<()> {
    match layer.spatial_ref().and_then(|s| s.auth_code().ok()) {
        Some(code) if code as u32 == EPSG => Ok(()),
        Some(code) => bail!("{}: CRS EPSG:{code} statt EPSG:{EPSG}", path.display()),
        None => {
            warn!("{}: kein CRS erkennbar, nehme EPSG:{EPSG} an", path.display());
            Ok(())
        }
    }
}

fn field_indices<L: LayerAccess>(layer: &L, fields: &[&str], path: &Path) -> Vec<Option<usize>> {
    fields
        .iter()
        .map(|f| match layer.defn().field_index(f) {
            Ok(i) => Some(i),
            Err(_) => {
                debug!("{}: Feld '{f}' nicht vorhanden", path.display());
                None
            }
        })
        .collect()
}

fn read_fields(feature: &Feature, idx: &[Option<usize>]) -> Vec<Option<String>> {
    idx.iter()
        .map(|i| {
            i.and_then(|i| feature.field_as_string(i).ok().flatten())
                .map(|s| s.trim().to_string())
                .filter(|s| !s.is_empty())
        })
        .collect()
}

fn collect_lines(g: Geometry<f64>, out: &mut Vec<LineString<f64>>) {
    match g {
        Geometry::LineString(l) => out.push(l),
        Geometry::MultiLineString(m) => out.extend(m.0),
        Geometry::GeometryCollection(c) => c.0.into_iter().for_each(|g| collect_lines(g, out)),
        _ => {}
    }
}

/// Liest alle Linien-Features einer Datei. `layer = None` nimmt die erste Ebene.
pub fn read_lines(path: &Path, layer: Option<&str>, fields: &[&str]) -> Result<Vec<LineFeature>> {
    let ds = open(path)?;
    let mut lyr = match layer {
        Some(name) => ds.layer_by_name(name).with_context(|| format!("{}: Ebene '{name}' fehlt", path.display()))?,
        None => ds.layer(0)?,
    };
    check_crs(&lyr, path)?;
    let idx = field_indices(&lyr, fields, path);
    let mut out = Vec::with_capacity(lyr.feature_count() as usize);
    let mut skipped = 0usize;
    for feature in lyr.features() {
        let Some(g) = feature.geometry() else {
            skipped += 1;
            continue;
        };
        let mut lines = Vec::new();
        match g.to_geo() {
            Ok(geo) => collect_lines(geo, &mut lines),
            Err(_) => {
                skipped += 1;
                continue;
            }
        }
        lines.retain(|l| l.0.len() >= 2);
        if lines.is_empty() {
            skipped += 1;
            continue;
        }
        out.push(LineFeature { fields: read_fields(&feature, &idx), lines });
    }
    if skipped > 0 {
        warn!("{}: {skipped} Features ohne gültige Liniengeometrie übersprungen", path.display());
    }
    Ok(out)
}

/// Namen aller Ebenen einer Datei.
pub fn layer_names(path: &Path) -> Result<Vec<String>> {
    let ds = open(path)?;
    Ok(ds.layers().map(|l| l.name()).collect())
}

/// Liest alle (Multi-)Polygone der ersten Ebene.
pub fn read_polygons(path: &Path, fields: &[&str]) -> Result<Vec<PolygonFeature>> {
    let ds = open(path)?;
    let mut lyr = ds.layer(0)?;
    check_crs(&lyr, path)?;
    let idx = field_indices(&lyr, fields, path);
    let mut out = Vec::new();
    for feature in lyr.features() {
        let Some(g) = feature.geometry() else { continue };
        let geom = match g.to_geo()? {
            Geometry::Polygon(p) => MultiPolygon(vec![p]),
            Geometry::MultiPolygon(m) => m,
            _ => continue,
        };
        out.push(PolygonFeature { fields: read_fields(&feature, &idx), geom });
    }
    Ok(out)
}

/// Typ einer Ausgabespalte.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum FieldKind {
    Str,
    Int,
    Real,
}

/// Wert einer Ausgabespalte.
#[derive(Debug, Clone)]
pub enum Value {
    Str(Option<String>),
    Int(i64),
    Real(f64),
}

impl From<Option<&str>> for Value {
    fn from(v: Option<&str>) -> Value {
        Value::Str(v.map(str::to_string))
    }
}

impl From<String> for Value {
    fn from(v: String) -> Value {
        Value::Str(Some(v))
    }
}

impl From<&str> for Value {
    fn from(v: &str) -> Value {
        Value::Str(Some(v.to_string()))
    }
}

/// Schreibt Features als FlatGeobuf (überschreibt vorhandene Dateien).
pub fn write_fgb<I>(path: &Path, layer_name: &str, geom_type: GeomType, fields: &[(&str, FieldKind)], rows: I) -> Result<usize>
where
    I: IntoIterator<Item = (Geometry<f64>, Vec<Value>)>,
{
    if let Some(dir) = path.parent() {
        std::fs::create_dir_all(dir)?;
    }
    if path.exists() {
        std::fs::remove_file(path)?;
    }
    let driver = DriverManager::get_driver_by_name("FlatGeobuf")?;
    let mut ds = driver
        .create_vector_only(path)
        .with_context(|| format!("Datei nicht schreibbar: {}", path.display()))?;
    let srs = SpatialRef::from_epsg(EPSG)?;
    let layer = ds.create_layer(LayerOptions {
        name: layer_name,
        srs: Some(&srs),
        ty: geom_type.ogr(),
        options: None,
    })?;
    for (name, kind) in fields {
        let ty = match kind {
            FieldKind::Str => OGRFieldType::OFTString,
            FieldKind::Int => OGRFieldType::OFTInteger64,
            FieldKind::Real => OGRFieldType::OFTReal,
        };
        FieldDefn::new(name, ty)?.add_to_layer(&layer)?;
    }
    let mut n = 0;
    for (geom, values) in rows {
        let mut f = Feature::new(layer.defn())?;
        for (i, v) in values.iter().enumerate() {
            match v {
                Value::Str(Some(s)) => f.set_field_string(i, s)?,
                Value::Str(None) => f.set_field_null(i)?,
                Value::Int(x) => f.set_field_integer64(i, *x)?,
                Value::Real(x) if x.is_finite() => f.set_field_double(i, *x)?,
                Value::Real(_) => f.set_field_null(i)?,
            }
        }
        f.set_geometry(geom.to_gdal()?)?;
        f.create(&layer)?;
        n += 1;
    }
    drop(layer);
    ds.close()?;
    Ok(n)
}

#[derive(Debug, Clone, Copy)]
pub enum GeomType {
    Point,
    LineString,
}

impl GeomType {
    fn ogr(self) -> OGRwkbGeometryType::Type {
        match self {
            GeomType::Point => OGRwkbGeometryType::wkbPoint,
            GeomType::LineString => OGRwkbGeometryType::wkbLineString,
        }
    }
}
