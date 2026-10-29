#!/bin/bash
# execute_processing.sh
# 
# Dieses Script führt den gesamten infraVelo Radnetz Verarbeitungsprozess aus.
# Es sichert finale Dateien vom vorherigen Lauf in output-last-run/
#
# Verarbeitungsschritte:
# 1.+2. HMM-Map-Matching (Rust, map-matching/)
# 3. Schutzstreifen-Konvertierung
# 4. Finale Aggregation
#
# Dateiverwaltung:
# - Finale Dateien (snapping_converted_bikelanes*, aggregated_rvn_final*) werden in output-last-run/ gesichert
# - Temporäre Dateien werden vor dem entsprechenden Verarbeitungsschritt gelöscht
# - Zwischendateien bleiben zwischen Schritten erhalten (für --start-step Funktionalität)
#
# Verwendung: ./execute_processing.sh [--netz rvn|ren] [--clip <region>] [--start-step <1-4>] [--clean-cache]
# 
# Argumente:
#   --netz rvn|ren      Zielnetz: rvn = Radvorrangnetz (Standard), ren = REN+ (alle Netzquellen
#                       gemeinsam). Bei ren tragen alle Ausgaben den Zusatz _ren, das Matching
#                       schreibt nach output/map-matching-ren/. Vorher ./process_radnetz.sh --netz ren
#                       und scripts/prepare_tilda_routing.py --netz ren.
#   --clip <region>     Regionaler Zuschnitt: neukoelln, norden oder sueden
#   --start-step <1-4>  Startet die Verarbeitung ab dem angegebenen Schritt
#                       1-2: HMM-Map-Matching
#                       3: Schutzstreifen-Konvertierung
#                       4: Finale Aggregation
#   --clean-cache       Vollständige Bereinigung aller Cache-Dateien vor der Verarbeitung
# 
# Voraussetzung: Python venv ist bereits erstellt und requirements.txt wurde installiert
#               TILDA Daten sind bereits prozessiert (./process_tilda_data.sh)

set -e  # Script bei Fehlern beenden

# Alle Pfade sind relativ zu processing/
cd "$(dirname "$0")"
# Virtuelles Environment liegt im Projekt-Root
VENV="$(cd .. && pwd)/.venv"

# Array für Backup-Dateien
declare -a BACKUP_FILES=()

# Funktion zum Erstellen von Backups
create_backup() {
    local file="$1"
    if [ -f "$file" ]; then
        mv "$file" "${file}.backup"
        BACKUP_FILES+=("$file")
        echo "    ↪ Backup erstellt: $(basename "$file")" >&2
    fi
}

# Funktion zum Löschen erfolgreicher Backups
cleanup_backups() {
    for file in "${BACKUP_FILES[@]}"; do
        rm -f "${file}.backup"
    done
    BACKUP_FILES=()
}

# Funktion zur Wiederherstellung bei Fehler
restore_backups() {
    echo "" >&2
    echo "⚠️  Fehler erkannt - stelle Backup-Dateien wieder her..." >&2
    for file in "${BACKUP_FILES[@]}"; do
        if [ -f "${file}.backup" ]; then
            mv "${file}.backup" "$file"
            echo "  ✅ Wiederhergestellt: $(basename "$file")" >&2
        fi
    done
    BACKUP_FILES=()
    echo "💾 Backup-Dateien wurden wiederhergestellt." >&2
}

# Trap für Fehlerbehandlung
trap 'restore_backups' ERR EXIT

# Help-Funktion
show_help() {
    cat << EOF
Verwendung: $0 [OPTIONEN]

Führt den infraVelo Radnetz Verarbeitungsprozess aus.

OPTIONEN:
  --netz rvn|ren       Zielnetz: rvn = Radvorrangnetz (Standard), ren = REN+ (alle Netzquellen gemeinsam)
  --clip <region>      Regionale Verarbeitung: neukoelln, norden oder sueden
  --start-step <1-4>   Startet ab angegebenem Schritt:
                       1 = OSM-Wege Matching
                       2 = Snapping und Attribut-Übernahme
                       3 = Schutzstreifen-Konvertierung
                       4 = Finale Aggregation
  --clean-cache        Vollständige Cache-Bereinigung vor Verarbeitung
  --help, -h           Zeigt diese Hilfe an

BEISPIELE:
  $0 --clip neukoelln                   # Nur Bezirk Neukölln
  $0 --clip norden --start-step 2       # Norden ab Schritt 2
  $0 --netz ren                         # REN+ statt Radvorrangnetz

EOF
    exit 0
}

# Zeiterfassung initialisieren
SCRIPT_START_TIME=$(date +%s)

# Funktion zur Berechnung und Anzeige der verstrichenen Zeit
show_elapsed_time() {
    local start_time=$1
    local step_name=$2
    local end_time=$(date +%s)
    local elapsed=$((end_time - start_time))
    local minutes=$((elapsed / 60))
    local seconds=$((elapsed % 60))
    
    if [ $minutes -gt 0 ]; then
        echo "⏱️  $step_name dauerte: ${minutes}m ${seconds}s"
    else
        echo "⏱️  $step_name dauerte: ${seconds}s"
    fi
}

# Funktion zur Anzeige der Gesamtzeit
show_total_time() {
    local start_time=$1
    local end_time=$(date +%s)
    local total_elapsed=$((end_time - start_time))
    local total_minutes=$((total_elapsed / 60))
    local total_seconds=$((total_elapsed % 60))
    
    echo ""
    echo "⏱️  =========================================="
    if [ $total_minutes -gt 0 ]; then
        echo "⏱️  Gesamte Verarbeitungszeit: ${total_minutes}m ${total_seconds}s"
    else
        echo "⏱️  Gesamte Verarbeitungszeit: ${total_seconds}s"
    fi
    echo "⏱️  =========================================="
}

# CLI-Argumente verarbeiten
NETZ="rvn"
CLIP_REGION=""
START_STEP=1
CLEAN_CACHE=""

# Verarbeite alle Argumente
while [[ $# -gt 0 ]]; do
    case $1 in
        --help|-h)
            show_help
            ;;
        --netz)
            NETZ="$2"
            shift 2
            ;;
        --clip)
            CLIP_REGION="$2"
            shift 2
            ;;
        --start-step)
            START_STEP="$2"
            shift 2
            ;;
        --clean-cache)
            CLEAN_CACHE="--clean-cache"
            shift
            ;;
        *)
            echo "❌ Unbekanntes Argument: $1"
            echo "Verwendung: $0 --help für weitere Informationen"
            exit 1
            ;;
    esac
done

# Validiere START_STEP
if [[ ! "$START_STEP" =~ ^[1-4]$ ]]; then
    echo "❌ Ungültiger Schritt: $START_STEP. Erlaubt sind: 1-4"
    exit 1
fi

# Validiere NETZ
if [[ ! "$NETZ" =~ ^(rvn|ren)$ ]]; then
    echo "❌ Ungültiges Netz: $NETZ. Erlaubt sind: rvn, ren"
    exit 1
fi

# Validiere CLIP_REGION
if [[ -n "$CLIP_REGION" ]]; then
    if [[ ! "$CLIP_REGION" =~ ^(neukoelln|norden|sueden)$ ]]; then
        echo "❌ Ungültige Region: $CLIP_REGION. Erlaubt sind: neukoelln, norden, sueden"
        exit 1
    fi
fi

# Prüfe ob .venv existiert
if [ ! -d "$VENV" ]; then
    echo "❌ Fehler: .venv Verzeichnis im Projekt-Root nicht gefunden!"
    echo "Bitte erstelle zuerst im Projekt-Root die virtuelle Umgebung mit:"
    echo "python3 -m venv .venv"
    echo "source .venv/bin/activate"
    echo "pip install -r requirements.txt"
    exit 1
fi

# Aktiviere virtuelles Environment automatisch
echo "🔧 Aktiviere virtuelles Environment..."
source "$VENV/bin/activate"

# Log-Verzeichnis und Datei erstellen
LOG_DIR="output/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/execute_processing_$(date +%Y%m%d_%H%M%S).log"

# Funktion zum Loggen mit tee
exec > >(tee -a "$LOG_FILE") 2>&1

echo "📝 Log-Datei: $LOG_FILE"
echo ""

echo "🛤️  Zielnetz: $NETZ"
if [[ -n "$CLIP_REGION" ]]; then
    echo "🌍 Verarbeitung wird auf Region $CLIP_REGION beschränkt."
else
    echo "🌍 Vollständige Verarbeitung für ganz Berlin."
fi

echo "🚀 Starte infraVelo Radnetz Verarbeitungsprozess ab Schritt $START_STEP..."

# Sichere finale Ausgabedateien von vorherigem Lauf in output-last-run
echo "💾 Sichere finale Dateien von vorherigem Lauf..."
# Dateizusatz: _ren für das REN+ (das Radvorrangnetz behält die bisherigen Namen), dann die Region
if [[ "$NETZ" == "ren" ]]; then
    NETZ_SUFFIX="_ren"
    MM_OUT_DIR="output/map-matching-ren"
else
    NETZ_SUFFIX=""
    MM_OUT_DIR="output/map-matching"
fi
if [[ -n "$CLIP_REGION" ]]; then
    CLIP_SUFFIX="_${CLIP_REGION}"
else
    CLIP_SUFFIX=""
fi
SUFFIX="${NETZ_SUFFIX}${CLIP_SUFFIX}"

BASE_OUT_DIR="output"
mkdir -p "$BASE_OUT_DIR"

# Zusätzliche Cache-Bereinigung falls --clean-cache gesetzt ist
if [[ -n "$CLEAN_CACHE" ]]; then
    echo "🧹 Vollständige Cache-Bereinigung aktiviert..."
    echo "  - Lösche alle Zwischendateien aus output/"
    
    # Bereinige alle Zwischendateien
    for dir in "output"; do
        if [ -d "$dir" ]; then
            echo "    Bereinige $dir/..."
            rm -rf $dir/matching/ $dir/matched/ $dir/snapping/ 2>/dev/null || true
            rm -f $dir/snapping_network_enriched*.fgb 2>/dev/null || true
            rm -f $dir/snapping_converted_bikelanes*.fgb 2>/dev/null || true
            rm -f $dir/aggregated_rvn_final*.gpkg 2>/dev/null || true
            rm -f $dir/aggregated_rvn_final*.fgb 2>/dev/null || true
        fi
    done
    
    # Recreate necessary directories
    mkdir -p ${BASE_OUT_DIR}/matching ${BASE_OUT_DIR}/matched ${BASE_OUT_DIR}/snapping
    echo "  ✅ Cache vollständig bereinigt und Verzeichnisse neu erstellt"
fi

# Verschiebe finale Dateien (falls vorhanden)
for f in "snapping_converted_bikelanes${SUFFIX}.fgb" \
                 "snapping_converted_bikelanes${SUFFIX}.geojson" \
                 "aggregated_rvn_final${SUFFIX}.gpkg" \
                 "aggregated_rvn_final${SUFFIX}.fgb" \
                 "aggregated_rvn_final${SUFFIX}.geojson"; do
    if [ -f "${BASE_OUT_DIR}/$f" ]; then
        echo "  - Sichere $f"
        mv "${BASE_OUT_DIR}/$f" output-last-run/ || true
    fi
done

echo "✅ Finale Dateien erfolgreich gesichert."
echo ""

echo "🔄 Starte Verarbeitungsprozess..."

# Schritt 1+2: HMM-Map-Matching (Rust)
if [[ $START_STEP -le 2 ]]; then
    echo "🧭 Schritt 1-2/4: HMM-Map-Matching (Rust, map-matching/)..."
    STEP1_START=$(date +%s)

    if ! command -v cargo >/dev/null 2>&1; then
        echo "❌ Fehler: cargo (Rust) nicht gefunden"
        exit 1
    fi

    create_backup "${BASE_OUT_DIR}/snapping_network_enriched${SUFFIX}.fgb"

    MM_ARGS=(--netz "$NETZ" run)
    if [[ -n "$CLIP_REGION" ]]; then
        MM_ARGS+=(--clip "$CLIP_REGION")
    fi
    (cd map-matching && cargo run --release --quiet -- "${MM_ARGS[@]}")
    if [ $? -ne 0 ]; then
        echo "❌ Fehler in Schritt 1-2: map-matching"
        exit 1
    fi

    # Ergebnis für die Python-Folgeschritte bereitstellen
    cp "${MM_OUT_DIR}/network_enriched_hmm${CLIP_SUFFIX}.fgb" "${BASE_OUT_DIR}/snapping_network_enriched${SUFFIX}.fgb"

    cleanup_backups
    show_elapsed_time $STEP1_START "Schritt 1-2"
    echo "✅ Schritt 1-2 abgeschlossen."
    echo ""
else
    echo "⏭️  Überspringe Schritt 1-2 (HMM-Map-Matching)"
    echo ""
fi

# Schritt 3: Schutzstreifen-Konvertierung
if [[ $START_STEP -le 3 ]]; then
    echo "🚲 Schritt 3/4: Schutzstreifen-Konvertierung..."
    STEP3_START=$(date +%s)
    
    # Erstelle Backups statt Dateien zu löschen
    echo "  💾 Erstelle Backups der vorhandenen Dateien..."
    create_backup "${BASE_OUT_DIR}/snapping_converted_bikelanes${SUFFIX}.fgb"
    
    CONVERSION_ARGS=(--input "./output/snapping_network_enriched${SUFFIX}.fgb" --output "./output/snapping_converted_bikelanes${SUFFIX}.fgb")
    if [[ -n "$CLIP_REGION" ]]; then
        CONVERSION_ARGS+=(--clip "$CLIP_REGION")
    fi
    "$VENV/bin/python" start_bikelane_conversion.py "${CONVERSION_ARGS[@]}"
    if [ $? -ne 0 ]; then
        echo "❌ Fehler in Schritt 3: start_bikelane_conversion.py"
        exit 1
    fi
    
    # Lösche Backups nach erfolgreichem Abschluss
    cleanup_backups
    show_elapsed_time $STEP3_START "Schritt 3"
    echo "✅ Schritt 3 abgeschlossen."
    echo ""
else
    echo "⏭️  Überspringe Schritt 3 (Schutzstreifen-Konvertierung)"
    echo ""
fi

# Schritt 4: Finale Aggregation
if [[ $START_STEP -le 4 ]]; then
    echo "🎯 Schritt 4/4: Finale Aggregation..."
    STEP4_START=$(date +%s)
    
    # Erstelle Backups statt Dateien zu löschen
    echo "  💾 Erstelle Backups der vorhandenen Dateien..."
    create_backup "${BASE_OUT_DIR}/aggregated_rvn_final${SUFFIX}.gpkg"
    create_backup "${BASE_OUT_DIR}/aggregated_rvn_final${SUFFIX}.fgb"
    
    # start_aggregation.py hängt die Region selbst an den Ausgabenamen an
    AGGREGATION_ARGS=(--input "./output/snapping_converted_bikelanes${SUFFIX}.fgb" --output "./output/aggregated_rvn_final${NETZ_SUFFIX}.gpkg")
    if [[ -n "$CLIP_REGION" ]]; then
        AGGREGATION_ARGS+=(--clip "$CLIP_REGION")
    fi
    "$VENV/bin/python" start_aggregation.py "${AGGREGATION_ARGS[@]}"
    if [ $? -ne 0 ]; then
        echo "❌ Fehler in Schritt 4: start_aggregation.py"
        exit 1
    fi
    
    # Lösche Backups nach erfolgreichem Abschluss
    cleanup_backups
    show_elapsed_time $STEP4_START "Schritt 4"
    echo "✅ Schritt 4 abgeschlossen."
    echo ""
else
    echo "⏭️  Überspringe Schritt 4 (Finale Aggregation)"
    echo ""
fi

# Deaktiviere Fehler-Trap bei erfolgreichem Abschluss
trap - ERR EXIT

echo "🎉 Verarbeitungsprozess erfolgreich abgeschlossen!"

# Gesamtzeit anzeigen
show_total_time $SCRIPT_START_TIME

echo ""
echo "📁 Ausgabedateien verfügbar in:"
echo "   - output/aggregated_rvn_final${SUFFIX}.gpkg"
echo "   - output/snapping_converted_bikelanes${SUFFIX}.fgb"
echo "   - ${MM_OUT_DIR}/ (Ergebnisse und Reports des Map-Matchings)"
echo "   - output-last-run/ (gesicherte Dateien vom vorherigen Lauf)"
echo ""
echo "🔍 Für QA-Zwecke:"
echo "   - Verwende den Inspector: cd inspector && npm run dev"
echo "   - Oder öffne das QGIS Projekt: QGIS QA Processing.qgz"
echo "   - Führe die Validierung durch: ./run_validation.sh [--clip neukoelln|norden|sueden]"
