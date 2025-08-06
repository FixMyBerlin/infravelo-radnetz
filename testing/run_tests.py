"""
Hauptskript für die Qualitätssicherung der finalen Geodaten-Verarbeitungsergebnisse.

Führt automatisierte Tests auf den Ausgabedateien durch:
- Prüft spezifische Attribute bei definierten element_nr Werten
- Validiert sowohl aggregierte als auch snapping Ergebnisse
- Unterstützt sowohl Berlin-weite als auch Neukölln-beschränkte Verarbeitung

Input-Dateien:
- ./testing/test_cases.json: Test-Definitionen
- ./output/aggregated_rvn_final[_neukoelln].gpkg: Finale aggregierte Ergebnisse
- ./output/snapping_network_enriched[_neukoelln].fgb: Snapping-Ergebnisse

Output:
- Detaillierter Test-Bericht in der Konsole
- Exit Code 0 bei Erfolg, 1 bei Fehlern
"""

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Dict, List

import geopandas as gpd
import pandas as pd

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(levelname)s: %(message)s'
)
logger = logging.getLogger(__name__)


class TestResult:
    """Klasse zur Speicherung von Test-Ergebnissen"""
    
    def __init__(self, test_name: str, success: bool, message: str, details: Dict = None):
        self.test_name = test_name
        self.success = success
        self.message = message
        self.details = details or {}


class GeoDataTester:
    """Hauptklasse für die Geodaten-Tests"""
    
    def __init__(self, clip_neukoelln: bool = False):
        self.clip_neukoelln = clip_neukoelln
        self.suffix = "_neukoelln" if clip_neukoelln else ""
        self.results: List[TestResult] = []
        
        # Dateipfade definieren
        self.aggregated_file = Path(f"output/aggregated_rvn_final{self.suffix}.gpkg")
        self.snapping_file = Path(f"output/snapping_network_enriched{self.suffix}.fgb")
        self.test_cases_file = Path("testing/test_cases.json")
    
    def load_test_cases(self) -> Dict:
        """Lädt die Test-Definitionen aus der JSON-Datei"""
        try:
            with open(self.test_cases_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except FileNotFoundError:
            logger.error(f"Test-Cases Datei nicht gefunden: {self.test_cases_file}")
            sys.exit(1)
        except json.JSONDecodeError as e:
            logger.error(f"Fehler beim Parsen der Test-Cases: {e}")
            sys.exit(1)
    
    def load_geodata(self, file_path: Path) -> gpd.GeoDataFrame:
        """Lädt eine Geodaten-Datei"""
        if not file_path.exists():
            raise FileNotFoundError(f"Datei nicht gefunden: {file_path}")
        
        try:
            if file_path.suffix == '.gpkg':
                # Für GeoPackage nehmen wir den ersten Layer
                gdf = gpd.read_file(file_path)
            elif file_path.suffix == '.fgb':
                gdf = gpd.read_file(file_path)
            else:
                raise ValueError(f"Ununterstütztes Dateiformat: {file_path.suffix}")
            
            logger.info(f"Geodaten geladen: {file_path} ({len(gdf)} Features)")
            return gdf
        
        except Exception as e:
            raise RuntimeError(f"Fehler beim Laden von {file_path}: {e}")
    
    def validate_geometry(self, feature: pd.Series, geometry_reqs: Dict, test_name: str) -> TestResult:
        """Validiert die Geometrie-Anforderungen eines Features"""
        failed_reqs = []
        
        try:
            geometry = feature.geometry
            
            # Prüfe Mindestlänge
            if 'min_length_meters' in geometry_reqs:
                min_length = geometry_reqs['min_length_meters']
                
                # Berechne Länge der Geometrie
                if geometry.geom_type in ['LineString', 'MultiLineString']:
                    # Für genaue Längenberechnung in Metern sollten die Daten in einem metrischen CRS sein
                    actual_length = geometry.length
                    
                    if actual_length < min_length:
                        failed_reqs.append(
                            f"Länge zu kurz: {actual_length:.2f}m < {min_length}m"
                        )
                else:
                    failed_reqs.append(
                        f"Unerwarteter Geometrietyp für Längenmessung: {geometry.geom_type}"
                    )
            
            # Weitere Geometrie-Anforderungen können hier hinzugefügt werden
            # z.B. max_length_meters, min_area, etc.
            
        except Exception as e:
            failed_reqs.append(f"Fehler bei Geometrie-Validierung: {e}")
        
        # Erstelle Ergebnis
        element_nr = feature.get('element_nr', 'Unknown')
        
        if failed_reqs:
            return TestResult(
                test_name=test_name,
                success=False,
                message=f"Geometrie-Validierung fehlgeschlagen für element_nr: {element_nr}",
                details={
                    "element_nr": element_nr,
                    "failed_geometry_requirements": failed_reqs
                }
            )
        else:
            return TestResult(
                test_name=test_name,
                success=True,
                message=f"Geometrie-Anforderungen erfüllt für element_nr: {element_nr}",
                details={
                    "element_nr": element_nr
                }
            )
    
    def validate_attributes(self, feature: pd.Series, expected_attrs: Dict, test_name: str) -> TestResult:
        """Validiert die Attribute eines einzelnen Features"""
        failed_attrs = []
        null_attrs = []
        attribute_comparison = {}
        
        for attr_name, expected_value in expected_attrs.items():
            if attr_name not in feature.index:
                failed_attrs.append(f"Attribut '{attr_name}' existiert nicht")
                attribute_comparison[attr_name] = {
                    "expected": expected_value,
                    "actual": "MISSING",
                    "status": "❌ FEHLT"
                }
                continue
            
            actual_value = feature[attr_name]
            
            # Prüfe auf NULL-Werte
            if pd.isna(actual_value) or actual_value is None:
                null_attrs.append(f"'{attr_name}' ist NULL")
                attribute_comparison[attr_name] = {
                    "expected": expected_value,
                    "actual": "NULL",
                    "status": "❌ NULL"
                }
                continue
            
            # Typkonvertierung für Vergleich
            if isinstance(expected_value, bool):
                # Für boolean Werte verschiedene Repräsentationen akzeptieren
                if str(actual_value).lower() in ['true', '1', 'yes', 'ja']:
                    actual_value = True
                elif str(actual_value).lower() in ['false', '0', 'no', 'nein']:
                    actual_value = False
            elif isinstance(expected_value, (int, float)):
                try:
                    actual_value = type(expected_value)(actual_value)
                except (ValueError, TypeError):
                    pass
            
            # Vergleiche Werte
            if actual_value != expected_value:
                failed_attrs.append(
                    f"'{attr_name}': erwartet '{expected_value}', "
                    f"gefunden '{actual_value}' (Typ: {type(actual_value).__name__})"
                )
                attribute_comparison[attr_name] = {
                    "expected": expected_value,
                    "actual": actual_value,
                    "status": "❌ FALSCH"
                }
            else:
                attribute_comparison[attr_name] = {
                    "expected": expected_value,
                    "actual": actual_value,
                    "status": "✅ OK"
                }
        
        # Erstelle Ergebnis
        all_errors = null_attrs + failed_attrs
        element_nr = feature.get('element_nr', 'Unknown')
        
        if all_errors:
            return TestResult(
                test_name=test_name,
                success=False,
                message=f"Attribut-Validierung fehlgeschlagen für element_nr: {element_nr}",
                details={
                    "element_nr": element_nr,
                    "attribute_comparison": attribute_comparison,
                    "null_attributes": null_attrs,
                    "failed_attributes": failed_attrs
                }
            )
        else:
            return TestResult(
                test_name=test_name,
                success=True,
                message=f"Alle Attribute korrekt validiert für element_nr: {element_nr}",
                details={
                    "element_nr": element_nr,
                    "attribute_comparison": attribute_comparison
                }
            )
    
    def test_aggregated_data(self, test_cases: List[Dict]) -> List[TestResult]:
        """Führt Tests auf den aggregierten Daten durch"""
        logger.info("🧪 Starte Tests für aggregierte Daten...")
        results = []
        
        try:
            gdf = self.load_geodata(self.aggregated_file)
        except Exception as e:
            results.append(TestResult(
                test_name="Aggregated Data Load",
                success=False,
                message=str(e)
            ))
            return results
        
        for test_case in test_cases:
            test_name = test_case['name']
            element_nr = test_case['element_nr']
            expected_attrs = test_case['expected_attributes']
            
            logger.info(f"  🔍 {test_name} (element_nr: {element_nr})")
            
            # Finde Features mit der element_nr
            matching_features = gdf[gdf['element_nr'] == element_nr]
            
            if len(matching_features) == 0:
                results.append(TestResult(
                    test_name=test_name,
                    success=False,
                    message=f"Keine Features mit element_nr '{element_nr}' gefunden",
                    details={"element_nr": element_nr}
                ))
                continue
            
            # Teste alle gefundenen Features (normalerweise sollte nur eines da sein)
            for idx, feature in matching_features.iterrows():
                result = self.validate_attributes(feature, expected_attrs, f"{test_name}")
                results.append(result)
        
        return results
    
    def test_snapping_data(self, test_cases: List[Dict]) -> List[TestResult]:
        """Führt Tests auf den Snapping-Daten durch"""
        logger.info("🧪 Starte Tests für Snapping-Daten...")
        results = []
        
        try:
            gdf = self.load_geodata(self.snapping_file)
        except Exception as e:
            results.append(TestResult(
                test_name="Snapping Data Load",
                success=False,
                message=str(e)
            ))
            return results
        
        for test_case in test_cases:
            test_name = test_case['name']
            element_nr = test_case['element_nr']
            expected_attrs = test_case['expected_attributes']
            test_mode = test_case.get('test_mode', 'any_segment')
            geometry_reqs = test_case.get('geometry_requirements', {})
            
            logger.info(f"  🔍 {test_name} (element_nr: {element_nr}, Modus: {test_mode})")
            
            # Finde Features mit der element_nr
            matching_features = gdf[gdf['element_nr'] == element_nr]
            
            if len(matching_features) == 0:
                results.append(TestResult(
                    test_name=test_name,
                    success=False,
                    message=f"Keine Features mit element_nr '{element_nr}' gefunden",
                    details={"element_nr": element_nr}
                ))
                continue
            
            logger.info(f"    📊 Gefunden: {len(matching_features)} Segmente")
            
            if test_mode == 'any_segment':
                # Mindestens ein Segment muss alle Attribute haben
                segment_results = []
                geometry_results = []
                
                for idx, feature in matching_features.iterrows():
                    # Teste Attribute
                    attr_result = self.validate_attributes(
                        feature, expected_attrs, 
                        f"{test_name}"
                    )
                    segment_results.append(attr_result)
                    
                    # Teste Geometrie-Anforderungen (falls vorhanden)
                    if geometry_reqs:
                        geom_result = self.validate_geometry(
                            feature, geometry_reqs,
                            f"{test_name}"
                        )
                        geometry_results.append(geom_result)
                
                # Prüfe ob mindestens ein Segment erfolgreich war (Attribute)
                successful_attr_segments = [r for r in segment_results if r.success]
                
                # Prüfe ob mindestens ein Segment die Geometrie-Anforderungen erfüllt
                successful_geom_segments = []
                if geometry_reqs:
                    successful_geom_segments = [r for r in geometry_results if r.success]
                
                # Kombiniere Ergebnisse
                if successful_attr_segments and (not geometry_reqs or successful_geom_segments):
                    success_msg = f"Mindestens 1 von {len(matching_features)} Segmenten erfüllt die Anforderungen"
                    if geometry_reqs:
                        success_msg += " (Attribute + Geometrie)"
                    
                    results.append(TestResult(
                        test_name=test_name,
                        success=True,
                        message=success_msg
                    ))
                else:
                    # Sammle alle Fehlermeldungen
                    failed_messages = []
                    
                    if not successful_attr_segments:
                        attr_messages = [r.message for r in segment_results]
                        failed_messages.append(f"Attribute: {'; '.join(attr_messages)}")
                    
                    if geometry_reqs and not successful_geom_segments:
                        geom_messages = [r.message for r in geometry_results]
                        failed_messages.append(f"Geometrie: {'; '.join(geom_messages)}")
                    
                    results.append(TestResult(
                        test_name=test_name,
                        success=False,
                        message=f"Kein Segment erfüllt die Anforderungen für element_nr: {element_nr}",
                        details={
                            "element_nr": element_nr,
                            "failed_messages": failed_messages
                        }
                    ))
        
        return results
    
    def run_all_tests(self) -> bool:
        """Führt alle Tests durch und gibt True zurück wenn alle erfolgreich waren"""
        logger.info("🚀 Starte Qualitätssicherungstests...")
        
        if self.clip_neukoelln:
            logger.info("🌍 Teste Neukölln-Daten")
        else:
            logger.info("🌍 Teste Berlin-weite Daten")
        
        # Lade Test-Cases
        test_cases = self.load_test_cases()
        
        # Führe aggregierte Tests durch
        if 'aggregated_tests' in test_cases:
            aggregated_results = self.test_aggregated_data(test_cases['aggregated_tests'])
            self.results.extend(aggregated_results)
        
        # Führe Snapping-Tests durch
        if 'snapping_tests' in test_cases:
            snapping_results = self.test_snapping_data(test_cases['snapping_tests'])
            self.results.extend(snapping_results)
        
        # Berichte erstellen
        self.print_test_report()
        
        # Rückgabe ob alle Tests erfolgreich waren
        failed_tests = [r for r in self.results if not r.success]
        return len(failed_tests) == 0
    
    def print_test_report(self):
        """Druckt einen detaillierten Test-Bericht"""
        print("\n" + "=" * 80)
        print("🧪 QUALITÄTSSICHERUNG - TEST-BERICHT")
        print("=" * 80)
        
        successful_tests = [r for r in self.results if r.success]
        failed_tests = [r for r in self.results if not r.success]
        
        print(f"✅ Erfolgreich: {len(successful_tests)}")
        print(f"❌ Fehlgeschlagen: {len(failed_tests)}")
        print(f"📊 Gesamt: {len(self.results)}")
        print()
        
        if successful_tests:
            print("✅ ERFOLGREICHE TESTS:")
            for result in successful_tests:
                element_nr = result.details.get('element_nr', 'Unknown')
                print(f"   ✓ {result.test_name} (element_nr: {element_nr})")
            print()
        
        if failed_tests:
            print("❌ FEHLGESCHLAGENE TESTS:")
            for result in failed_tests:
                element_nr = result.details.get('element_nr', 'Unknown')
                print(f"   ✗ {result.test_name} (element_nr: {element_nr})")
                print(f"     {result.message}")
                
                # Zeige strukturierte Attribut-Vergleiche
                if 'attribute_comparison' in result.details:
                    print("     📋 ATTRIBUT-VERGLEICH:")
                    comparison = result.details['attribute_comparison']
                    
                    # Bestimme die maximale Breite für Formatierung
                    max_attr_len = max(len(attr) for attr in comparison.keys()) if comparison else 0
                    max_expected_len = max(len(str(data['expected'])) for data in comparison.values()) if comparison else 0
                    max_actual_len = max(len(str(data['actual'])) for data in comparison.values()) if comparison else 0
                    
                    # Header
                    print(f"     {'Attribut':<{max_attr_len}} | {'Erwartet':<{max_expected_len}} | {'Gefunden':<{max_actual_len}} | Status")
                    print(f"     {'-'*max_attr_len}-+-{'-'*max_expected_len}-+-{'-'*max_actual_len}-+--------")
                    
                    # Zeige zuerst fehlgeschlagene, dann erfolgreiche
                    failed_attrs = {k: v for k, v in comparison.items() if not v['status'].startswith('✅')}
                    success_attrs = {k: v for k, v in comparison.items() if v['status'].startswith('✅')}
                    
                    for attr_name, data in {**failed_attrs, **success_attrs}.items():
                        expected_str = str(data['expected'])
                        actual_str = str(data['actual'])
                        status = data['status']
                        
                        print(f"     {attr_name:<{max_attr_len}} | {expected_str:<{max_expected_len}} | {actual_str:<{max_actual_len}} | {status}")
                
                # Zeige Geometrie-Fehler
                if 'failed_geometry_requirements' in result.details and result.details['failed_geometry_requirements']:
                    print("     📐 GEOMETRIE-FEHLER:")
                    for geom_error in result.details['failed_geometry_requirements']:
                        print(f"       - {geom_error}")
                
                print()
        
        print("=" * 80)
        
        if failed_tests:
            print("❌ QUALITÄTSSICHERUNG FEHLGESCHLAGEN!")
        else:
            print("✅ QUALITÄTSSICHERUNG ERFOLGREICH!")
            print("   Alle Tests bestanden. Die Geodaten-Verarbeitung war erfolgreich.")
        
        print("=" * 80)


def main():
    """Hauptfunktion für die Kommandozeilen-Ausführung"""
    parser = argparse.ArgumentParser(
        description="Qualitätssicherungstests für infraVelo Radnetz Verarbeitungsergebnisse"
    )
    parser.add_argument(
        '--clip-neukoelln',
        action='store_true',
        help='Teste die Neukölln-beschränkten Ergebnisse'
    )
    
    args = parser.parse_args()
    
    # Wechsle ins Hauptverzeichnis des Projekts
    project_root = Path(__file__).parent.parent
    import os
    os.chdir(project_root)
    
    # Führe Tests durch
    tester = GeoDataTester(clip_neukoelln=args.clip_neukoelln)
    success = tester.run_all_tests()
    
    # Exit Code setzen
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
