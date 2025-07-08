import geopandas as gpd
import os

def extract_streets_in_buffer(buffered_network_path, streets_detail_path, output_path):
    """
    Diese Funktion führt einen räumlichen Join zwischen einem gepufferten Vorrangnetz
    und detaillierten Straßenabschnitten durch. Es werden alle Straßenabschnitte
    identifiziert, die innerhalb des gepufferten Netzwerks liegen.

    Args:
        buffered_network_path (str): Dateipfad zum gepufferten Vorrangnetz (FlatGeobuf).
        streets_detail_path (str): Dateipfad zu den detaillierten Straßenabschnitten (FlatGeobuf).
        output_path (str): Dateipfad für die Ausgabedatei (FlatGeobuf).
    """
    # Eingabe: Buffered Vorrangnetz laden
    print("Lese das gepufferte Vorrangnetz ein ...")
    buffered_network = gpd.read_file(buffered_network_path)

    # Eingabe: Detailnetz der Straßenabschnitte laden
    print("Lese die detaillierten Straßenabschnitte ein ...")
    streets_detail = gpd.read_file(streets_detail_path)

    # Räumlicher Join: Finde alle Straßenabschnitte, die im Buffer liegen
    print("Führe räumlichen Join durch (Straßen im Buffer ermitteln) ...")
    streets_in_buffer = gpd.sjoin(streets_detail, buffered_network, how="inner", predicate="within")

    # Überflüssige Spalte aus dem Join entfernen
    streets_in_buffer = streets_in_buffer.drop(columns=['index_right'])


    # Ergebnis speichern
    print(f"Speichere {len(streets_in_buffer)} Straßenabschnitte nach {output_path} ...")
    streets_in_buffer.to_file(output_path, driver="FlatGeobuf")

    print("Fertig.")

def add_missing_radvorrangsnetz_segments(vorrangnetz_details_path, radvorrangsnetz_path, output_path_combined):
    """
    Identifiziert fehlende Segmente im Radvorrangsnetz, die in den Detail-Straßenabschnitten
    nicht enthalten sind, und kombiniert sie.

    Args:
        vorrangnetz_details_path (str): Pfad zu den extrahierten Detail-Straßenabschnitten.
        radvorrangsnetz_path (str): Pfad zur Originaldatei des Radvorrangsnetzes.
        output_path_combined (str): Pfad für die kombinierte Ausgabedatei.
    """
    print("Lade extrahierte Detail-Straßenabschnitte...")
    vorrangnetz_details = gpd.read_file(vorrangnetz_details_path)

    print("Lade das originale Radvorrangsnetz...")
    radvorrangsnetz = gpd.read_file(radvorrangsnetz_path)

    # Stelle sicher, dass beide GeoDataFrames das gleiche CRS haben
    if vorrangnetz_details.crs != radvorrangsnetz.crs:
        print("Transformiere CRS des Radvorrangsnetzes...")
        radvorrangsnetz = radvorrangsnetz.to_crs(vorrangnetz_details.crs)

    print("Identifiziere fehlende Segmente...")
    # Finde Segmente im Radvorrangsnetz, die sich nicht mit den Detail-Straßenabschnitten überschneiden
    joined = gpd.sjoin(radvorrangsnetz, vorrangnetz_details, how='left', predicate='intersects')
    missing_segments = joined[joined['index_right'].isnull()]

    # Entferne die überflüssigen Spalten aus dem Join
    missing_segments = missing_segments.drop(columns=['index_right'])
    # Behalte nur die Spalten des ursprünglichen Radvorrangsnetzes
    missing_segments = missing_segments[radvorrangsnetz.columns]


    if not missing_segments.empty:
        print(f"{len(missing_segments)} fehlende Segmente gefunden. Kombiniere Datensätze...")
        # Kombiniere die ursprünglichen Details mit den fehlenden Segmenten
        combined_gdf = gpd.pd.concat([vorrangnetz_details, missing_segments], ignore_index=True)

        print(f"Speichere den kombinierten Datensatz nach {output_path_combined}...")
        combined_gdf.to_file(output_path_combined, driver="FlatGeobuf")
    else:
        print("Keine fehlenden Segmente gefunden. Kopiere ursprünglichen Datensatz.")
        vorrangnetz_details.to_file(output_path_combined, driver="FlatGeobuf")

    print("Kombination der Datensätze abgeschlossen.")


def main():
    """
    Hauptfunktion des Skripts. Definiert die Dateipfade und ruft die
    Verarbeitungsfunktion auf.
    """
    # Basisverzeichnis bestimmen (ein Verzeichnis über dem Skript)
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    output_dir = os.path.join(base_dir, "output")
    data_dir = os.path.join(base_dir, "data")

    # Dateipfade für Eingabe- und Ausgabedateien definieren
    buffered_network_path = os.path.join(output_dir, "vorrangnetz_buffered.fgb")
    streets_detail_path = os.path.join(data_dir, "Berlin Straßenabschnitte Detailnetz.fgb")
    output_path = os.path.join(output_dir, "vorrangnetz_details.fgb")
    radvorrangsnetz_path = os.path.join(data_dir, "Berlin Radvorrangsnetz.fgb")
    output_path_combined = os.path.join(output_dir, "vorrangnetz_details_combined_rvn.fgb")

    extract_streets_in_buffer(buffered_network_path, streets_detail_path, output_path)
    add_missing_radvorrangsnetz_segments(output_path, radvorrangsnetz_path, output_path_combined)

if __name__ == "__main__":
    main()
