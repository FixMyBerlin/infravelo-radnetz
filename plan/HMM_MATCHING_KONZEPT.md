# Hidden Markov Model (HMM) basiertes Map-Matching für das Radvorrangsnetz

## Übersicht

Dieses Dokument beschreibt einen alternativen Ansatz zur aktuellen Matching/Snapping-Methodik basierend auf Hidden Markov Models (HMM). Das Ziel ist, die Notwendigkeit manueller Inklusionen (`include_ways.txt`) und Exklusionen (`exclude_ways.txt`) drastisch zu reduzieren.

---

## 1. Analyse der aktuellen Probleme

### 1.1 Aktuelle Methodik (Greedy Local Matching)

Die aktuelle Pipeline besteht aus drei Hauptschritten:

```
TILDA-Daten → Matching → Snapping → Aggregation → Finale Daten
```

**Matching (start_matching.py):**
- Buffer-basierte räumliche Suche (15-35m)
- Mindestens 70% des Weges muss im Buffer liegen
- Filterung nach Kategorien und Orthogonalität

**Snapping (start_snapping.py):**
- Segmentierung des Zielnetzes in 2.5m Abschnitte
- Kandidatensuche pro Segment im 33m Buffer
- Lokale Prioritätsberechnung pro Segment:
  - Verkehrszeichen-Priorität (+5)
  - Kategorie-Priorität (+1 bis +35)
  - Straßennamen-Match (+15/-20)
  - Winkel-Priorität (-100 bis +20)
  - Distanz-Priorität (0 bis +15)
  - Überlappung (-13 bis +10)
  - Richtungskompatibilität (-110 bis +15)

### 1.2 Identifizierte Schwächen

| Problem | Beschreibung | Auswirkung |
|---------|--------------|------------|
| **Lokale Entscheidungen** | Jedes Segment wird isoliert betrachtet | Inkonsistente Zuordnungen entlang eines Weges |
| **Schwierige Prioritätsbalance** | 8+ Faktoren müssen gegeneinander abgewogen werden | Suboptimale Gewichtung führt zu Fehlzuordnungen |
| **Fehlende Kontextinformation** | Vorherige/nachfolgende Segmente unberücksichtigt | "Sprünge" zwischen parallelen Wegen |
| **Keine globale Optimierung** | Greedy-Auswahl des lokalen Optimums | Global suboptimale Pfade |
| **Manuelle Listen** | 693 Exklusionen, 428 Inklusionen | Wartungsaufwand, keine Skalierbarkeit |

---

## 2. HMM-basierter Ansatz: Theoretischer Hintergrund

### 2.1 Warum HMM für Map-Matching?

Hidden Markov Models sind der De-facto-Standard für Map-Matching in der Literatur (vgl. Newson & Krumm 2009). Sie modellieren:

- **Versteckte Zustände (Hidden States):** Die "wahren" Straßenkanten, auf denen sich die Infrastruktur befindet
- **Beobachtungen (Observations):** Die gemessenen TILDA-Punkte/Geometrien
- **Übergangswahrscheinlichkeiten:** Wie wahrscheinlich ist es, von einer Kante zur nächsten zu wechseln?
- **Emissionswahrscheinlichkeiten:** Wie wahrscheinlich ist eine Beobachtung gegeben eine bestimmte Kante?

### 2.2 Viterbi-Algorithmus

Der Viterbi-Algorithmus findet den **wahrscheinlichsten Pfad** durch die versteckten Zustände:

```
Optimaler Pfad = argmax P(Zustände | Beobachtungen)
                        ∏ P(Beobachtung_t | Zustand_t) · P(Zustand_t | Zustand_{t-1})
```

**Vorteile gegenüber Greedy:**
- Globale Optimierung statt lokaler Entscheidungen
- Konsistente Zuordnungen entlang zusammenhängender Wege
- Natürliche Modellierung von Netzwerk-Topologie

---

## 3. Konkreter HMM-Ansatz für das Radvorrangsnetz

### 3.1 Modellierung

```
┌─────────────────────────────────────────────────────────────────┐
│                    HMM für RVN-Matching                         │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  Versteckte Zustände (Hidden States):                          │
│  ─────────────────────────────────────                         │
│  • Jede Kante im Radvorrangsnetz (element_nr + ri)             │
│  • Zusätzlich: NULL-Zustand ("keine Zuordnung")                │
│                                                                 │
│  Beobachtungen (Observations):                                  │
│  ───────────────────────────────                                │
│  • TILDA-Punkte entlang eines OSM-Weges                        │
│  • Sequenz von Punkten, nicht einzelne Punkte                  │
│                                                                 │
│  Emissionswahrscheinlichkeit P(obs | state):                   │
│  ─────────────────────────────────────────────                  │
│  • Distanz TILDA-Punkt ↔ RVN-Kante                             │
│  • Winkelabweichung                                             │
│  • Attribut-Kompatibilität                                      │
│                                                                 │
│  Übergangswahrscheinlichkeit P(state_t | state_{t-1}):         │
│  ──────────────────────────────────────────────────             │
│  • Netzwerk-Konnektivität (sind Kanten verbunden?)             │
│  • Kürzeste-Pfad-Distanz vs. Luftlinie                         │
│  • "Routing-Kompatibilität"                                     │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 3.2 Emissionswahrscheinlichkeit (Beobachtungs-Modell)

Die Wahrscheinlichkeit, dass ein TILDA-Punkt `p` zur RVN-Kante `e` gehört:

```python
def emission_probability(tilda_point, rvn_edge):
    """
    Berechnet P(tilda_point | rvn_edge)
    
    Kombiniert mehrere Faktoren mit Gauß-Verteilung:
    - Räumliche Distanz
    - Winkelabweichung  
    - Attribut-Kompatibilität
    """
    # 1. Räumliche Distanz (Gaußsch mit σ = 15m)
    distance = tilda_point.geometry.distance(rvn_edge.geometry)
    p_distance = exp(-distance² / (2 * σ_distance²))
    
    # 2. Winkelabweichung (Gaußsch mit σ = 20°)
    angle_diff = calculate_angle_difference(tilda_point, rvn_edge)
    p_angle = exp(-angle_diff² / (2 * σ_angle²))
    
    # 3. Attribut-Kompatibilität (kategorisch)
    p_attr = calculate_attribute_compatibility(tilda_point, rvn_edge)
    
    # Kombinierte Emission (gewichtetes Produkt)
    return p_distance * p_angle * p_attr
```

### 3.3 Übergangswahrscheinlichkeit (Transitions-Modell)

Die Wahrscheinlichkeit, von Kante `e_i` zu Kante `e_j` zu wechseln:

```python
def transition_probability(edge_i, edge_j, tilda_segment_length):
    """
    Berechnet P(edge_j | edge_i)
    
    Basiert auf:
    - Netzwerk-Konnektivität
    - Routing-Differenz (kürzester Pfad vs. Luftlinie)
    """
    # 1. Direkte Konnektivität prüfen
    if edges_are_connected(edge_i, edge_j):
        connectivity_bonus = 1.0
    else:
        # Kürzester Pfad im Netz berechnen
        network_distance = shortest_path_distance(edge_i, edge_j)
        euclidean_distance = edge_i.centroid.distance(edge_j.centroid)
        
        # Routing-Differenz bestrafen
        if network_distance == inf:
            return 0.0  # Nicht erreichbar
        
        diff = abs(network_distance - euclidean_distance)
        connectivity_bonus = exp(-diff / β)
    
    # 2. Segment-Längen-Kompatibilität
    expected_distance = tilda_segment_length
    actual_distance = network_distance_between(edge_i, edge_j)
    length_prob = exp(-abs(expected_distance - actual_distance) / γ)
    
    return connectivity_bonus * length_prob
```

### 3.4 Viterbi-Algorithmus (Pseudocode)

```python
def hmm_map_matching(tilda_way, rvn_network, emission_model, transition_model):
    """
    Findet den optimalen Pfad durch das RVN für einen TILDA-Weg.
    
    Args:
        tilda_way: TILDA-Weg mit Sequenz von Punkten/Segmenten
        rvn_network: Radvorrangsnetz als Graph
        emission_model: Funktion für P(observation | state)
        transition_model: Funktion für P(state_t | state_{t-1})
    
    Returns:
        List[RvnEdge]: Optimale Sequenz von RVN-Kanten
    """
    
    # Sampling: TILDA-Weg in gleichmäßige Punkte aufteilen
    observations = sample_points_along_way(tilda_way, interval=5.0)  # alle 5m
    n_obs = len(observations)
    
    # Kandidaten pro Beobachtung finden (im 50m Radius)
    candidates = []
    for obs in observations:
        nearby_edges = rvn_network.query_radius(obs, radius=50)
        candidates.append(nearby_edges if nearby_edges else [NULL_STATE])
    
    # Initialisierung (t=0)
    V = [{} for _ in range(n_obs)]  # Viterbi-Wahrscheinlichkeiten
    B = [{} for _ in range(n_obs)]  # Backpointer für Pfadrekonstruktion
    
    for state in candidates[0]:
        V[0][state] = log(emission_model(observations[0], state))
        B[0][state] = None
    
    # Rekursion (t=1 bis n_obs-1)
    for t in range(1, n_obs):
        for state_curr in candidates[t]:
            max_prob = -inf
            best_prev = None
            
            for state_prev in candidates[t-1]:
                # Viterbi-Rekursion in Log-Space
                prob = (V[t-1][state_prev] + 
                       log(transition_model(state_prev, state_curr, observations[t-1:t+1])) +
                       log(emission_model(observations[t], state_curr)))
                
                if prob > max_prob:
                    max_prob = prob
                    best_prev = state_prev
            
            V[t][state_curr] = max_prob
            B[t][state_curr] = best_prev
    
    # Terminierung: Finde beste End-Zustand
    best_final_state = max(candidates[-1], key=lambda s: V[-1].get(s, -inf))
    
    # Pfad-Rekonstruktion (Backtracking)
    path = [best_final_state]
    for t in range(n_obs - 1, 0, -1):
        path.append(B[t][path[-1]])
    
    return list(reversed(path))
```

---

## 4. Architektur-Änderungen

### 4.1 Neue Pipeline-Struktur

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        NEUE PIPELINE (HMM-basiert)                       │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────┐  │
│  │  1. TILDA   │    │  2. HMM     │    │  3. Attrib- │    │  4.Aggre│  │
│  │  Vorbereit. │ → │  Matching   │ → │  Übertragung│ → │  gation │  │
│  └─────────────┘    └─────────────┘    └─────────────┘    └─────────┘  │
│                                                                         │
│  Schritt 1: Unverändert (process_tilda_data.sh)                        │
│                                                                         │
│  Schritt 2: NEU - hmm_matching.py                                      │
│    • Graph-Aufbau des RVN                                              │
│    • Pro TILDA-Weg: Viterbi-Algorithmus                                │
│    • Ausgabe: matched_ways_hmm.fgb mit zugeordneten element_nr         │
│                                                                         │
│  Schritt 3: Vereinfacht - attribute_transfer.py                        │
│    • Keine Kandidatensuche mehr nötig                                  │
│    • Direkte Attributübertragung basierend auf HMM-Match               │
│    • Richtungsbestimmung (ri) aus Matching-Ergebnis                    │
│                                                                         │
│  Schritt 4: Unverändert (start_aggregation.py)                         │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### 4.2 Neue Module

```
processing/
├── hmm/
│   ├── __init__.py
│   ├── graph.py           # RVN-Graph-Aufbau mit NetworkX
│   ├── emission.py        # Emissionswahrscheinlichkeiten
│   ├── transition.py      # Übergangswahrscheinlichkeiten
│   ├── viterbi.py         # Viterbi-Algorithmus
│   └── config.py          # HMM-Parameter (σ, β, γ)
├── start_hmm_matching.py  # Neuer Haupteinstiegspunkt
├── start_attribute_transfer.py  # Vereinfachtes Snapping
└── ... (bestehende Module)
```

---

## 5. Detaillierter Pseudocode

### 5.1 Graph-Aufbau (graph.py)

```python
import networkx as nx
from shapely.geometry import Point

class RvnGraph:
    """
    Graphrepräsentation des Radvorrangsnetzes.
    Knoten = Verbindungspunkte (beginnt_bei_vp, endet_bei_vp)
    Kanten = RVN-Segmente (element_nr + ri)
    """
    
    def __init__(self):
        self.G = nx.DiGraph()  # Gerichteter Graph für Einrichtungsverkehr
        self.edge_index = {}   # Räumlicher Index für Kantensuche
        
    def build_from_gdf(self, rvn_gdf):
        """
        Baut Graph aus GeoDataFrame auf.
        """
        for idx, row in rvn_gdf.iterrows():
            element_nr = row['element_nr']
            start_vp = row['beginnt_bei_vp']
            end_vp = row['endet_bei_vp']
            geometry = row['geometry']
            
            # Knoten hinzufügen mit Koordinaten
            if start_vp not in self.G:
                start_point = Point(geometry.coords[0])
                self.G.add_node(start_vp, pos=start_point)
            if end_vp not in self.G:
                end_point = Point(geometry.coords[-1])
                self.G.add_node(end_vp, pos=end_point)
            
            # Kante hinzufügen (für ri=0)
            edge_id = (element_nr, 0)
            self.G.add_edge(start_vp, end_vp, 
                          edge_id=edge_id,
                          geometry=geometry,
                          length=geometry.length,
                          strassenname=row.get('strassenname', ''))
            
            # Rückkante (für ri=1) falls Zweirichtungsverkehr
            edge_id_reverse = (element_nr, 1)
            self.G.add_edge(end_vp, start_vp,
                          edge_id=edge_id_reverse,
                          geometry=geometry.reverse(),
                          length=geometry.length,
                          strassenname=row.get('strassenname', ''))
        
        # Räumlichen Index aufbauen
        self._build_spatial_index()
    
    def _build_spatial_index(self):
        """Baut STRtree für schnelle Kandidatensuche."""
        from shapely.strtree import STRtree
        
        geometries = []
        edge_ids = []
        for u, v, data in self.G.edges(data=True):
            geometries.append(data['geometry'])
            edge_ids.append(data['edge_id'])
        
        self.spatial_tree = STRtree(geometries)
        self.spatial_edge_ids = edge_ids
    
    def get_candidates(self, point, radius=50):
        """
        Findet alle Kanten im Radius um einen Punkt.
        """
        buffer = point.buffer(radius)
        candidate_indices = self.spatial_tree.query(buffer)
        
        candidates = []
        for idx in candidate_indices:
            edge_id = self.spatial_edge_ids[idx]
            # Hole Kantenattribute
            for u, v, data in self.G.edges(data=True):
                if data['edge_id'] == edge_id:
                    candidates.append({
                        'edge_id': edge_id,
                        'geometry': data['geometry'],
                        'start_node': u,
                        'end_node': v,
                        'length': data['length'],
                        'strassenname': data['strassenname']
                    })
                    break
        
        return candidates
    
    def shortest_path_distance(self, edge_id_1, edge_id_2):
        """
        Berechnet kürzeste Pfaddistanz zwischen zwei Kanten.
        """
        # Finde End-Knoten von edge_1 und Start-Knoten von edge_2
        end_node_1 = None
        start_node_2 = None
        
        for u, v, data in self.G.edges(data=True):
            if data['edge_id'] == edge_id_1:
                end_node_1 = v
            if data['edge_id'] == edge_id_2:
                start_node_2 = u
        
        if end_node_1 is None or start_node_2 is None:
            return float('inf')
        
        try:
            path_length = nx.shortest_path_length(
                self.G, end_node_1, start_node_2, weight='length'
            )
            return path_length
        except nx.NetworkXNoPath:
            return float('inf')
```

### 5.2 Emissionsmodell (emission.py)

```python
import numpy as np
from shapely.geometry import Point

class EmissionModel:
    """
    Berechnet Emissionswahrscheinlichkeiten P(observation | state).
    """
    
    def __init__(self, sigma_distance=15.0, sigma_angle=20.0):
        self.sigma_distance = sigma_distance
        self.sigma_angle = sigma_angle
    
    def probability(self, observation, candidate, tilda_attributes=None):
        """
        Berechnet kombinierte Emissionswahrscheinlichkeit.
        
        Args:
            observation: dict mit 'point', 'angle', 'attributes'
            candidate: dict mit 'geometry', 'strassenname', etc.
            tilda_attributes: Optionale TILDA-Attribute für Kompatibilitätsprüfung
        """
        obs_point = observation['point']
        obs_angle = observation.get('angle', None)
        
        # 1. Distanz-Komponente (Gauß)
        distance = obs_point.distance(candidate['geometry'])
        p_distance = self._gaussian(distance, 0, self.sigma_distance)
        
        # 2. Winkel-Komponente (falls verfügbar)
        if obs_angle is not None:
            candidate_angle = self._calculate_edge_angle(candidate['geometry'], obs_point)
            angle_diff = self._angle_difference(obs_angle, candidate_angle)
            p_angle = self._gaussian(angle_diff, 0, self.sigma_angle)
        else:
            p_angle = 1.0  # Neutral wenn kein Winkel
        
        # 3. Attribut-Kompatibilität
        p_attr = self._attribute_compatibility(observation, candidate, tilda_attributes)
        
        # Kombiniere (Log-Space für numerische Stabilität)
        log_prob = (np.log(p_distance + 1e-10) + 
                   np.log(p_angle + 1e-10) + 
                   np.log(p_attr + 1e-10))
        
        return np.exp(log_prob)
    
    def _gaussian(self, x, mu, sigma):
        """Standard Gauß-Verteilung."""
        return np.exp(-0.5 * ((x - mu) / sigma) ** 2)
    
    def _angle_difference(self, angle1, angle2):
        """Kleinste Winkeldifferenz (0-180°)."""
        diff = abs(angle1 - angle2) % 360
        return min(diff, 360 - diff)
    
    def _calculate_edge_angle(self, geometry, reference_point):
        """Berechnet Tangentenwinkel am nächsten Punkt."""
        # Projektion auf Linie
        projected_distance = geometry.project(reference_point)
        
        # Punkte vor und nach für Tangente
        delta = 1.0  # 1 Meter
        p1 = geometry.interpolate(max(0, projected_distance - delta))
        p2 = geometry.interpolate(min(geometry.length, projected_distance + delta))
        
        dx = p2.x - p1.x
        dy = p2.y - p1.y
        angle = np.degrees(np.arctan2(dy, dx))
        return angle % 360
    
    def _attribute_compatibility(self, observation, candidate, tilda_attributes):
        """
        Bewertet Attribut-Kompatibilität.
        
        Faktoren:
        - Straßennamen-Match
        - Kategoriekompatibilität
        - Verkehrszeichen-Match
        """
        score = 1.0
        
        if tilda_attributes is None:
            return score
        
        # Straßennamen-Vergleich
        tilda_name = tilda_attributes.get('tilda_name', '').lower().strip()
        rvn_name = candidate.get('strassenname', '').lower().strip()
        
        if tilda_name and rvn_name:
            if tilda_name == rvn_name:
                score *= 2.0  # Bonus für Match
            elif tilda_name != rvn_name:
                score *= 0.3  # Penalty für Mismatch
        
        # Kategorie-Bonus (Radinfrastruktur bevorzugen)
        category = tilda_attributes.get('tilda_category', '')
        if category:
            if category.startswith('cycleway'):
                score *= 1.5
            elif category.startswith('footAndCycleway'):
                score *= 1.4
            elif category.startswith('bicycleRoad'):
                score *= 1.3
        
        return score
```

### 5.3 Übergangsmodell (transition.py)

```python
import numpy as np

class TransitionModel:
    """
    Berechnet Übergangswahrscheinlichkeiten P(state_t | state_{t-1}).
    """
    
    def __init__(self, beta=30.0, gamma=10.0):
        self.beta = beta   # Routing-Differenz-Parameter
        self.gamma = gamma  # Längen-Differenz-Parameter
    
    def probability(self, state_prev, state_curr, rvn_graph, 
                   obs_prev, obs_curr):
        """
        Berechnet Übergangswahrscheinlichkeit.
        
        Args:
            state_prev: Vorherige Kante (edge_id)
            state_curr: Aktuelle Kante (edge_id)
            rvn_graph: RvnGraph-Instanz für Routing
            obs_prev: Vorherige Beobachtung (Point)
            obs_curr: Aktuelle Beobachtung (Point)
        """
        # Sonderfall: NULL-Zustand
        if state_prev is None or state_curr is None:
            return 0.1  # Niedrige aber nicht null Wahrscheinlichkeit
        
        # Gleiche Kante: Hohe Wahrscheinlichkeit
        if state_prev == state_curr:
            return 0.9
        
        # 1. Berechne Distanzen
        # Luftlinie zwischen Beobachtungen
        euclidean_dist = obs_prev.distance(obs_curr)
        
        # Kürzester Pfad im Netz
        network_dist = rvn_graph.shortest_path_distance(state_prev, state_curr)
        
        if network_dist == float('inf'):
            # Nicht verbunden im Netz
            return 1e-6  # Sehr kleine Wahrscheinlichkeit
        
        # 2. Routing-Differenz
        routing_diff = abs(network_dist - euclidean_dist)
        p_routing = np.exp(-routing_diff / self.beta)
        
        # 3. Konsistenz-Prüfung
        # Wenn network_dist >> euclidean_dist: Unwahrscheinlicher Umweg
        if network_dist > euclidean_dist * 3:
            p_routing *= 0.1
        
        return p_routing
```

### 5.4 Viterbi-Algorithmus (viterbi.py)

```python
import numpy as np
from collections import defaultdict

class ViterbiMatcher:
    """
    Implementiert den Viterbi-Algorithmus für Map-Matching.
    """
    
    def __init__(self, rvn_graph, emission_model, transition_model,
                 candidate_radius=50.0, min_candidates=1):
        self.graph = rvn_graph
        self.emission = emission_model
        self.transition = transition_model
        self.candidate_radius = candidate_radius
        self.min_candidates = min_candidates
    
    def match(self, tilda_way, sample_interval=5.0):
        """
        Führt HMM Map-Matching für einen TILDA-Weg durch.
        
        Args:
            tilda_way: GeoDataFrame-Row mit geometry und Attributen
            sample_interval: Abstand zwischen Sampling-Punkten in Metern
        
        Returns:
            List[Tuple]: Liste von (element_nr, ri) für jeden Sample-Punkt
        """
        # 1. Sampling des TILDA-Wegs
        observations = self._sample_way(tilda_way, sample_interval)
        n_obs = len(observations)
        
        if n_obs == 0:
            return []
        
        tilda_attributes = self._extract_tilda_attributes(tilda_way)
        
        # 2. Kandidaten pro Beobachtung finden
        candidates = []
        for obs in observations:
            nearby = self.graph.get_candidates(obs['point'], self.candidate_radius)
            if not nearby:
                nearby = [None]  # NULL-Zustand
            candidates.append(nearby)
        
        # 3. Viterbi-Initialisierung (t=0)
        V = [defaultdict(lambda: -np.inf) for _ in range(n_obs)]
        B = [defaultdict(lambda: None) for _ in range(n_obs)]
        
        for cand in candidates[0]:
            edge_id = cand['edge_id'] if cand else None
            if cand:
                emission_prob = self.emission.probability(
                    observations[0], cand, tilda_attributes
                )
            else:
                emission_prob = 0.01  # Geringe Wahrscheinlichkeit für NULL
            
            V[0][edge_id] = np.log(emission_prob + 1e-10)
            B[0][edge_id] = None
        
        # 4. Viterbi-Rekursion (t=1 bis n_obs-1)
        for t in range(1, n_obs):
            for cand_curr in candidates[t]:
                edge_id_curr = cand_curr['edge_id'] if cand_curr else None
                
                # Emissionswahrscheinlichkeit
                if cand_curr:
                    emission_prob = self.emission.probability(
                        observations[t], cand_curr, tilda_attributes
                    )
                else:
                    emission_prob = 0.01
                
                log_emission = np.log(emission_prob + 1e-10)
                
                # Finde besten Vorgänger
                max_prob = -np.inf
                best_prev = None
                
                for cand_prev in candidates[t-1]:
                    edge_id_prev = cand_prev['edge_id'] if cand_prev else None
                    
                    # Übergangswahrscheinlichkeit
                    trans_prob = self.transition.probability(
                        edge_id_prev, edge_id_curr,
                        self.graph,
                        observations[t-1]['point'],
                        observations[t]['point']
                    )
                    
                    log_trans = np.log(trans_prob + 1e-10)
                    
                    # Viterbi-Rekursion
                    prob = V[t-1][edge_id_prev] + log_trans + log_emission
                    
                    if prob > max_prob:
                        max_prob = prob
                        best_prev = edge_id_prev
                
                V[t][edge_id_curr] = max_prob
                B[t][edge_id_curr] = best_prev
        
        # 5. Terminierung und Backtracking
        # Finde besten End-Zustand
        best_final = max(
            [c['edge_id'] if c else None for c in candidates[-1]],
            key=lambda e: V[-1].get(e, -np.inf)
        )
        
        # Pfad rekonstruieren
        path = [best_final]
        for t in range(n_obs - 1, 0, -1):
            path.append(B[t][path[-1]])
        
        path = list(reversed(path))
        
        # 6. Post-Processing: NULL-Zustände behandeln
        path = self._smooth_path(path, observations)
        
        return path
    
    def _sample_way(self, tilda_way, interval):
        """Sampelt Punkte entlang eines Weges."""
        geometry = tilda_way.geometry
        length = geometry.length
        
        observations = []
        distance = 0.0
        
        while distance <= length:
            point = geometry.interpolate(distance)
            
            # Berechne lokalen Winkel
            delta = min(1.0, length - distance, distance)
            if delta > 0:
                p1 = geometry.interpolate(max(0, distance - delta))
                p2 = geometry.interpolate(min(length, distance + delta))
                angle = np.degrees(np.arctan2(p2.y - p1.y, p2.x - p1.x)) % 360
            else:
                angle = 0
            
            observations.append({
                'point': point,
                'angle': angle,
                'distance_along': distance
            })
            
            distance += interval
        
        return observations
    
    def _extract_tilda_attributes(self, tilda_way):
        """Extrahiert relevante TILDA-Attribute."""
        return {
            'tilda_name': tilda_way.get('tilda_name', ''),
            'tilda_category': tilda_way.get('tilda_category', ''),
            'tilda_traffic_sign': tilda_way.get('tilda_traffic_sign', ''),
            'verkehrsri': tilda_way.get('verkehrsri', 'Zweirichtungsverkehr')
        }
    
    def _smooth_path(self, path, observations):
        """
        Glättet den Pfad durch Interpolation von NULL-Zuständen.
        """
        smoothed = path.copy()
        
        # Finde NULL-Sequenzen und interpoliere
        i = 0
        while i < len(smoothed):
            if smoothed[i] is None:
                # Finde Start und Ende der NULL-Sequenz
                start = i - 1 if i > 0 else 0
                end = i
                while end < len(smoothed) and smoothed[end] is None:
                    end += 1
                
                # Interpoliere mit vorherigem/nächstem Wert
                prev_val = smoothed[start] if start >= 0 and smoothed[start] else None
                next_val = smoothed[end] if end < len(smoothed) else None
                
                fill_val = prev_val or next_val
                for j in range(i, end):
                    smoothed[j] = fill_val
                
                i = end
            else:
                i += 1
        
        return smoothed
```

### 5.5 Hauptskript (start_hmm_matching.py)

```python
#!/usr/bin/env python3
"""
start_hmm_matching.py
--------------------------------------------------------------------
HMM-basiertes Map-Matching von TILDA-Wegen auf das Radvorrangsnetz.

INPUT:
- output/TILDA-translated/TILDA Bikelanes Translated.fgb
- output/rvn/Berlin Vorrangnetz_with_element_nr.fgb

OUTPUT:
- output/matched/matched_tilda_ways_hmm.fgb
"""

import geopandas as gpd
import logging
from pathlib import Path
from tqdm import tqdm

from hmm.graph import RvnGraph
from hmm.emission import EmissionModel
from hmm.transition import TransitionModel
from hmm.viterbi import ViterbiMatcher
from helpers.globals import DEFAULT_CRS

def main():
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)
    
    # 1. Daten laden
    logger.info("Lade RVN-Daten...")
    rvn_gdf = gpd.read_file('./output/rvn/Berlin Vorrangnetz_with_element_nr.fgb')
    rvn_gdf = rvn_gdf.to_crs(f'EPSG:{DEFAULT_CRS}')
    
    logger.info("Lade TILDA-Daten...")
    tilda_gdf = gpd.read_file('./output/TILDA-translated/TILDA Bikelanes Translated.fgb')
    tilda_gdf = tilda_gdf.to_crs(f'EPSG:{DEFAULT_CRS}')
    
    # 2. Graph aufbauen
    logger.info("Baue RVN-Graph auf...")
    rvn_graph = RvnGraph()
    rvn_graph.build_from_gdf(rvn_gdf)
    logger.info(f"Graph: {rvn_graph.G.number_of_nodes()} Knoten, "
               f"{rvn_graph.G.number_of_edges()} Kanten")
    
    # 3. HMM-Modelle initialisieren
    emission_model = EmissionModel(sigma_distance=15.0, sigma_angle=20.0)
    transition_model = TransitionModel(beta=30.0, gamma=10.0)
    
    matcher = ViterbiMatcher(
        rvn_graph, emission_model, transition_model,
        candidate_radius=50.0
    )
    
    # 4. Matching durchführen
    logger.info(f"Starte HMM-Matching für {len(tilda_gdf)} TILDA-Wege...")
    
    results = []
    for idx, tilda_way in tqdm(tilda_gdf.iterrows(), total=len(tilda_gdf)):
        path = matcher.match(tilda_way)
        
        if path:
            # Konvertiere Pfad zu Zuordnungen
            # Aggregiere aufeinanderfolgende gleiche Kanten
            current_edge = None
            segments = []
            
            for edge_id in path:
                if edge_id != current_edge:
                    if current_edge is not None:
                        segments.append(current_edge)
                    current_edge = edge_id
            
            if current_edge is not None:
                segments.append(current_edge)
            
            # Speichere Ergebnis
            for element_nr, ri in segments:
                results.append({
                    'tilda_id': tilda_way.get('tilda_id', f'way_{idx}'),
                    'element_nr': element_nr,
                    'ri': ri,
                    'geometry': tilda_way.geometry,
                    # Alle TILDA-Attribute übernehmen
                    **{k: v for k, v in tilda_way.items() 
                       if k.startswith('tilda_') or k in ['fuehr', 'breite', 'ofm']}
                })
    
    # 5. Ergebnisse speichern
    result_gdf = gpd.GeoDataFrame(results, crs=f'EPSG:{DEFAULT_CRS}')
    output_path = Path('./output/matched/matched_tilda_ways_hmm.fgb')
    output_path.parent.mkdir(parents=True, exist_ok=True)
    result_gdf.to_file(output_path, driver='FlatGeobuf')
    
    logger.info(f"HMM-Matching abgeschlossen. {len(result_gdf)} Zuordnungen gespeichert.")
    
    # 6. Statistiken
    matched_ways = result_gdf['tilda_id'].nunique()
    matched_edges = result_gdf['element_nr'].nunique()
    logger.info(f"Statistik: {matched_ways} TILDA-Wege → {matched_edges} RVN-Kanten")

if __name__ == '__main__':
    main()
```

---

## 6. Vergleich: Aktuelle vs. HMM-Methodik

### 6.1 Funktionale Unterschiede

| Aspekt | Aktuelle Methodik | HMM-Methodik |
|--------|-------------------|--------------|
| **Entscheidungsebene** | Lokal (pro 2.5m Segment) | Global (gesamter TILDA-Weg) |
| **Optimierung** | Greedy (lokales Maximum) | Viterbi (globales Maximum) |
| **Kontextnutzung** | Keine | Vorherige/nächste Beobachtungen |
| **Netzwerktopologie** | Ignoriert | Explizit modelliert |
| **Parameteranzahl** | 8+ Prioritätswerte | 3-4 Modellparameter |
| **Manuelle Listen** | ~1100 Einträge | Idealerweise ~0 |

### 6.2 Komplexitätsvergleich

```
Aktuelle Methodik:
──────────────────
  Zeitkomplexität: O(S × C × A)
    S = Anzahl Segmente (~100k)
    C = Kandidaten pro Segment (~10)
    A = Attributberechnungen (~8)
  
  → Gesamtkomplexität: O(S × C × A) ≈ O(8M Operationen)

HMM-Methodik:
─────────────
  Zeitkomplexität: O(W × P × C²)
    W = Anzahl TILDA-Wege (~20k)
    P = Punkte pro Weg (~50)
    C = Kandidaten pro Punkt (~10)
  
  → Gesamtkomplexität: O(W × P × C²) ≈ O(100M Operationen)
  
  ABER: Parallelisierbar pro Weg!
```

### 6.3 Wartbarkeitsvergleich

| Metrik | Aktuelle Methodik | HMM-Methodik |
|--------|-------------------|--------------|
| **Codezeilen (geschätzt)** | ~3500 LOC | ~1500 LOC |
| **Anzahl Konfigurationsparameter** | 30+ | 5-8 |
| **Anzahl Sonderfälle im Code** | Viele (Kreisverkehre, etc.) | Wenige (im Modell kodiert) |
| **Debugging-Schwierigkeit** | Hoch (viele Interaktionen) | Mittel (Wahrscheinlichkeiten inspizierbar) |
| **Erweiterbarkeit** | Aufwändig | Modular (neue Faktoren = neue Emissionen) |

---

## 7. Implementierungsplan

### Phase 1: Proof of Concept (2-3 Wochen)

1. **Graph-Modul implementieren**
   - NetworkX-basierter RVN-Graph
   - Räumlicher Index mit STRtree
   - Unit-Tests für Routing

2. **Einfaches HMM implementieren**
   - Nur Distanz-basierte Emission
   - Konnektivitäts-basierte Transition
   - Viterbi ohne Optimierungen

3. **Evaluation auf Testgebiet**
   - Neukölln als Testgebiet
   - Vergleich mit aktueller Methodik
   - Metriken: Precision, Recall, F1

### Phase 2: Vollständige Implementierung (3-4 Wochen)

4. **Emission verfeinern**
   - Winkel-Komponente hinzufügen
   - Attribut-Kompatibilität
   - Parameter-Tuning

5. **Transition verfeinern**
   - Routing-Differenz-Berechnung
   - Längen-Konsistenz

6. **Performance-Optimierung**
   - Multiprocessing pro TILDA-Weg
   - Caching von Routing-Ergebnissen
   - Batch-Verarbeitung

### Phase 3: Integration (1-2 Wochen)

7. **Pipeline-Integration**
   - Neuer Einstiegspunkt `start_hmm_matching.py`
   - Anpassung der Aggregation
   - Kompatibilität mit Inspector

8. **Dokumentation**
   - README aktualisieren
   - Parameter-Dokumentation
   - Evaluationsbericht

---

## 8. Risiken und Mitigationsstrategien

| Risiko | Wahrscheinlichkeit | Auswirkung | Mitigation |
|--------|-------------------|------------|------------|
| **Performance unzureichend** | Mittel | Hoch | Parallelisierung, Caching, Beam-Search statt voller Viterbi |
| **Genauigkeit schlechter** | Niedrig | Hoch | Umfangreiches Tuning, Hybrid-Ansatz möglich |
| **Graph-Aufbau komplex** | Mittel | Mittel | Bestehende VP-Relationen nutzen |
| **Debugging schwierig** | Mittel | Mittel | Ausführliches Logging, Visualisierung der Wahrscheinlichkeiten |

---

## 9. Fazit und Empfehlung

### Empfehlung: **Ja zur HMM-Implementierung**

**Argumente dafür:**
- Prinzipiell überlegener Ansatz (global statt lokal)
- Etabliertes Verfahren in der Literatur
- Deutlich weniger Sonderfälle im Code
- Perspektive: Eliminierung manueller Listen

**Vorbedingung:**
- Proof of Concept auf Testgebiet Neukölln vor vollständiger Migration
- Parallele Verfügbarkeit beider Methoden während Übergangsphase

**Erwarteter Aufwand:**
- 6-9 Wochen für vollständige Implementierung
- Zusätzlich 2-3 Wochen für Tuning und Evaluation

---

## Referenzen

1. Newson, P., & Krumm, J. (2009). *Hidden Markov Map Matching Through Noise and Sparseness*. ACM SIGSPATIAL GIS.
2. Lou, Y., Zhang, C., Zheng, Y., Xie, X., Wang, W., & Huang, Y. (2009). *Map-matching for low-sampling-rate GPS trajectories*. ACM SIGSPATIAL GIS.
3. Quddus, M. A., Ochieng, W. Y., & Noland, R. B. (2007). *Current map-matching algorithms for transport applications: State-of-the art and future research directions*. Transportation Research Part C.
