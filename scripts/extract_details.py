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

    extract_streets_in_buffer(buffered_network_path, streets_detail_path, output_path)

if __name__ == "__main__":
    main()
