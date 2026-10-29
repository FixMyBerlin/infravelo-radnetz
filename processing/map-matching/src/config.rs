//! Konfiguration (TOML) inkl. CLI-Overrides der Form `abschnitt.schluessel=wert`.

use std::collections::BTreeMap;
use std::path::{Path, PathBuf};

use anyhow::{Context, Result, anyhow, bail};
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct Config {
    pub paths: PathsConfig,
    pub network: NetworkConfig,
    pub trace: TraceConfig,
    pub hmm: HmmConfig,
    pub assemble: AssembleConfig,
    pub rules: RulesConfig,
    pub eval: EvalConfig,
    /// Verzeichnis, gegen das `paths.root` aufgelöst wird (nicht Teil der TOML-Datei).
    #[serde(skip)]
    pub base_dir: PathBuf,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct PathsConfig {
    pub root: PathBuf,
    pub network: PathBuf,
    pub districts: PathBuf,
    pub output_dir: PathBuf,
    pub reference: PathBuf,
    pub reference_secondary: PathBuf,
    #[serde(default)]
    pub manual_way_lists: Vec<PathBuf>,
    #[serde(default)]
    pub manual_element_lists: Vec<PathBuf>,
    pub tilda: Vec<TildaSourceConfig>,
    #[serde(default)]
    pub clip_regions: BTreeMap<String, PathBuf>,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct TildaSourceConfig {
    pub data_source: String,
    pub path: PathBuf,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct NetworkConfig {
    pub node_tolerance_m: f64,
    pub gap_report_m: f64,
}

#[derive(Debug, Clone, Copy, Deserialize, Serialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum TraceStrategy {
    /// Jeder TILDA-Weg bildet eine eigene Trace.
    Single,
    /// Traces folgen der Topologie des TILDA-Routing-Netzes (`from_node`/`to_node`):
    /// Kanten derselben Datenquelle in erlaubter Fahrtrichtung, an Knoten möglichst geradeaus.
    Topology,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct TraceConfig {
    pub strategy: TraceStrategy,
    pub sample_interval_m: f64,
    pub heading_window_m: f64,
    /// `topology`: maximale Richtungsänderung an einem Knoten (Grad).
    #[serde(default = "default_max_turn_deg")]
    pub max_turn_deg: f64,
    /// `topology`: Länge, über die der Kurs an Kantenenden bestimmt wird (m).
    #[serde(default = "default_end_heading_m")]
    pub end_heading_m: f64,
}

fn default_max_turn_deg() -> f64 {
    45.0
}

fn default_end_heading_m() -> f64 {
    10.0
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct HmmConfig {
    pub candidate_radius_m: f64,
    pub max_candidates: usize,
    pub sigma_distance_m: f64,
    pub heading_kappa: f64,
    pub side_penalty: f64,
    pub side_min_distance_m: f64,
    pub name_mismatch_penalty: f64,
    pub null_log_emission: f64,
    pub null_switch_penalty: f64,
    pub beta_m: f64,
    pub backward_tolerance_m: f64,
    pub route_limit_factor: f64,
    pub route_limit_extra_m: f64,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct AssembleConfig {
    pub min_segment_length_m: f64,
    pub gap_fill_m: f64,
    pub end_fill_m: f64,
    pub no_infra_fuehr: String,
    pub mixed_traffic_fuehr: String,
    pub merge_attributes: Vec<String>,
    pub transfer_attributes: Vec<String>,
}

#[derive(Debug, Clone, Default, Deserialize, Serialize)]
pub struct Predicate {
    pub data_source: Option<Vec<String>>,
    pub fuehr: Option<Vec<String>>,
    pub category_prefix: Option<Vec<String>>,
    pub traffic_sign_any: Option<Vec<String>>,
    pub traffic_sign_none: Option<Vec<String>>,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct PreferRule {
    pub name: String,
    pub winner: Predicate,
    pub loser: Predicate,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct TierRule {
    pub name: String,
    pub rank: u32,
    pub when: Predicate,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct RulesConfig {
    #[serde(default)]
    pub prefer: Vec<PreferRule>,
    pub tiers: Vec<TierRule>,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct EvalConfig {
    pub attributes: Vec<String>,
    pub max_projection_distance_m: f64,
}

impl Config {
    /// Lädt die TOML-Datei, übernimmt die Pfade des Netzes `[netze.<netz>]` (falls angegeben)
    /// und wendet danach die Overrides (`a.b=wert`) an.
    pub fn load(path: &Path, netz: Option<&str>, overrides: &[String]) -> Result<Config> {
        let text = std::fs::read_to_string(path)
            .with_context(|| format!("Konfiguration nicht lesbar: {}", path.display()))?;
        let mut value: toml::Value = toml::from_str(&text)
            .with_context(|| format!("Konfiguration fehlerhaft: {}", path.display()))?;
        apply_netz(&mut value, netz)?;
        for ov in overrides {
            apply_override(&mut value, ov)?;
        }
        let mut cfg: Config = value
            .try_into()
            .context("Konfiguration passt nicht zum erwarteten Schema")?;
        let dir = path.parent().filter(|p| !p.as_os_str().is_empty()).unwrap_or(Path::new("."));
        cfg.base_dir = dir.canonicalize().unwrap_or_else(|_| dir.to_path_buf());
        cfg.validate()?;
        Ok(cfg)
    }

    /// Wendet Overrides auf eine bereits geladene Konfiguration an (für das Tuning).
    pub fn with_overrides(&self, overrides: &[String]) -> Result<Config> {
        let mut value = toml::Value::try_from(self)?;
        for ov in overrides {
            apply_override(&mut value, ov)?;
        }
        let mut cfg: Config = value.try_into()?;
        cfg.base_dir = self.base_dir.clone();
        cfg.validate()?;
        Ok(cfg)
    }

    /// Absoluter Pfad relativ zu `paths.root`.
    pub fn resolve(&self, rel: &Path) -> PathBuf {
        if rel.is_absolute() {
            return rel.to_path_buf();
        }
        let root = self.base_dir.join(&self.paths.root);
        root.canonicalize().unwrap_or(root).join(rel)
    }

    pub fn output_dir(&self) -> PathBuf {
        self.resolve(&self.paths.output_dir)
    }

    fn validate(&self) -> Result<()> {
        let h = &self.hmm;
        if h.sigma_distance_m <= 0.0 || h.beta_m <= 0.0 || h.candidate_radius_m <= 0.0 {
            bail!("hmm.sigma_distance_m, hmm.beta_m und hmm.candidate_radius_m müssen > 0 sein");
        }
        if h.max_candidates == 0 {
            bail!("hmm.max_candidates muss >= 1 sein");
        }
        if self.trace.sample_interval_m <= 0.0 {
            bail!("trace.sample_interval_m muss > 0 sein");
        }
        if self.rules.tiers.is_empty() {
            bail!("rules.tiers darf nicht leer sein");
        }
        Ok(())
    }
}

/// Ersetzt Werte in `[paths]` durch die des gewählten Netzes `[netze.<netz>]` und entfernt
/// `[netze]` aus dem Baum. Ohne Netz bleibt `[paths]` unverändert.
fn apply_netz(root: &mut toml::Value, netz: Option<&str>) -> Result<()> {
    let table = root.as_table_mut().ok_or_else(|| anyhow!("Konfiguration ist keine Tabelle"))?;
    let netze = match table.remove("netze") {
        Some(toml::Value::Table(t)) => t,
        Some(_) => bail!("[netze] muss eine Tabelle sein"),
        None => toml::Table::new(),
    };
    let Some(netz) = netz else {
        return Ok(());
    };
    let selected = netze
        .get(netz)
        .and_then(|v| v.as_table())
        .ok_or_else(|| anyhow!("Unbekanntes Netz '{netz}' (verfügbar: {})", netze.keys().cloned().collect::<Vec<_>>().join(", ")))?;
    let paths = table
        .get_mut("paths")
        .and_then(|v| v.as_table_mut())
        .ok_or_else(|| anyhow!("Abschnitt [paths] fehlt"))?;
    for (key, v) in selected {
        if !paths.contains_key(key) {
            bail!("[netze.{netz}]: unbekannter Schlüssel '{key}' (erlaubt sind Schlüssel aus [paths])");
        }
        paths.insert(key.clone(), v.clone());
    }
    Ok(())
}

/// Setzt `a.b.c=wert` in einem TOML-Baum. Der Wert wird als TOML-Literal
/// interpretiert (Zahl, Bool, String in Anführungszeichen, Array); schlägt das
/// fehl, wird er als String übernommen.
fn apply_override(root: &mut toml::Value, ov: &str) -> Result<()> {
    let (key, raw) = ov
        .split_once('=')
        .ok_or_else(|| anyhow!("Override '{ov}' hat nicht die Form schluessel=wert"))?;
    let parsed: toml::Value = toml::from_str::<toml::Table>(&format!("v = {raw}"))
        .ok()
        .and_then(|mut t| t.remove("v"))
        .unwrap_or_else(|| toml::Value::String(raw.to_string()));
    let parts: Vec<&str> = key.trim().split('.').collect();
    let mut cur = root;
    for (i, part) in parts.iter().enumerate() {
        let table = cur
            .as_table_mut()
            .ok_or_else(|| anyhow!("Override '{ov}': '{part}' liegt nicht in einer Tabelle"))?;
        if i + 1 == parts.len() {
            if !table.contains_key(*part) {
                bail!("Override '{ov}': unbekannter Schlüssel '{key}'");
            }
            table.insert((*part).to_string(), parsed);
            return Ok(());
        }
        cur = table
            .get_mut(*part)
            .ok_or_else(|| anyhow!("Override '{ov}': unbekannter Abschnitt '{part}'"))?;
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn override_sets_number_and_rejects_unknown_key() {
        let mut v: toml::Value = toml::from_str("[hmm]\nbeta_m = 4.0\n").unwrap();
        apply_override(&mut v, "hmm.beta_m=6.5").unwrap();
        assert_eq!(v["hmm"]["beta_m"].as_float(), Some(6.5));
        assert!(apply_override(&mut v, "hmm.unbekannt=1").is_err());
    }

    #[test]
    fn netz_replaces_paths_and_rejects_unknown() {
        let text = "[paths]\nnetwork = \"rvn.fgb\"\noutput_dir = \"out\"\n[netze.rvn]\n[netze.ren]\nnetwork = \"ren.fgb\"\n";
        let mut v: toml::Value = toml::from_str(text).unwrap();
        apply_netz(&mut v, Some("ren")).unwrap();
        assert_eq!(v["paths"]["network"].as_str(), Some("ren.fgb"));
        assert_eq!(v["paths"]["output_dir"].as_str(), Some("out"));
        assert!(v.get("netze").is_none());

        let mut v: toml::Value = toml::from_str(text).unwrap();
        apply_netz(&mut v, Some("rvn")).unwrap();
        assert_eq!(v["paths"]["network"].as_str(), Some("rvn.fgb"));

        let mut v: toml::Value = toml::from_str(text).unwrap();
        assert!(apply_netz(&mut v, Some("unbekannt")).is_err());
        let mut v: toml::Value = toml::from_str("[paths]\nnetwork = \"a\"\n[netze.x]\nfalsch = 1\n").unwrap();
        assert!(apply_netz(&mut v, Some("x")).is_err());
    }

    #[test]
    fn default_config_has_both_netze() {
        let path = Path::new(concat!(env!("CARGO_MANIFEST_DIR"), "/config/default.toml"));
        let standard = Config::load(path, None, &[]).unwrap();
        let rvn = Config::load(path, Some("rvn"), &[]).unwrap();
        let ren = Config::load(path, Some("ren"), &[]).unwrap();
        assert_eq!(rvn.paths.network, standard.paths.network);
        assert_eq!(rvn.paths.output_dir, standard.paths.output_dir);
        assert_eq!(ren.paths.network, PathBuf::from("output/ren/ren_netz_details_combined.fgb"));
        assert_eq!(ren.paths.output_dir, PathBuf::from("output/map-matching-ren"));
        assert_eq!(ren.paths.tilda.len(), standard.paths.tilda.len());
        assert!(ren.paths.tilda.iter().all(|t| t.path.starts_with("output/TILDA-routing-ren")));
        // --set wirkt nach der Netzauswahl
        let set = Config::load(path, Some("ren"), &["paths.output_dir=\"x\"".into()]).unwrap();
        assert_eq!(set.paths.output_dir, PathBuf::from("x"));
    }
}
