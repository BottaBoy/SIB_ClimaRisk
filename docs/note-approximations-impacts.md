# Note - Étapes du calcul pouvant introduire des approximations sur les impacts

Date: 2026-04-08
Périmètre: chaîne `sib-work` (backend risk engine + scripts case study)
Objectif: identifier les points méthodologiques/numériques qui peuvent biaiser les impacts (EAI, RP50/RP100, événement max).

## 1) Ingestion et normalisation de l'exposition

### 1.1 Normalisation `asset_type`
- Où: `backend/app/risk_engine/exposure_ingest.py`
- Approximation potentielle: mapping de libellés hétérogènes vers une taxonomie restreinte.
- Risque: mauvaise courbe de vulnérabilité appliquée (sur/sous-estimation locale des dommages).

### 1.2 Inférence `infra_class`
- Où: `backend/app/risk_engine/exposure_to_climada.py:24-72`
- Approximation potentielle: règles heuristiques (`startswith`, sous-chaînes) pour classer les actifs.
- Risque: actifs mal classés (ex. réseau vs ouvrage), donc sensibilité aléa inadaptée.

## 2) Désagrégation spatiale des actifs

### 2.1 Sampling géométrique
- Où: `backend/app/risk_engine/exposure_to_climada.py:229-327`
- Paramètres clés: `spacing_m`, `max_points_per_feature`.
- Approximation potentielle: représentation simplifiée d'actifs linéaires/surfaciques par un nuage de points.
- Risque: perte d'information spatiale fine, sensibilité aux valeurs de pas/cap.

### 2.2 Partage uniforme de la valeur
- Où: `backend/app/risk_engine/exposure_to_climada.py:269`
- Approximation potentielle: `value_eur` réparti uniformément sur les points d'une géométrie.
- Risque: la valeur n'est pas forcément homogène le long d'un tronçon/réseau réel.

## 3) Construction dynamique des aléas cycloniques (tracks -> hazard)

### 3.1 Fenêtre spatiale autour des points
- Où: `backend/app/risk_engine/hazard_loader.py:162-208`, utilisée en `:621`
- Approximation potentielle: bbox des points + `spatial_padding_deg` (défaut 4°).
- Risque: sous-capture (padding trop faible) ou bruit inutile (padding trop grand).

### 3.2 Sélection des bassins
- Où: `backend/app/risk_engine/hazard_loader.py:211-238`
- Approximation potentielle: sélection par boîtes de couverture par bassin, sinon fallback "tous bassins".
- Risque: contamination par événements hors zone ou, inversement, exclusion d'événements pertinents.

### 3.3 Troncature du nombre de tracks
- Où: `backend/app/risk_engine/hazard_loader.py:335`, `:395-423`, `:610`
- Paramètre clé: `dynamic_max_tracks`.
- Approximation potentielle: limitation à N tracks (ranking par distance au centre de la fenêtre).
- Risque majeur: queue d'extrêmes mal échantillonnée, biais fort sur RP50/RP100 et événements rares.

### 3.4 Conversion d'unités vents/rayon
- Où: `backend/app/risk_engine/hazard_loader.py:241-307`
- Approximation potentielle: hypothèse d'unité d'entrée (`m/s`, `km/h`, `kn`; rayon `km/nm/m`).
- Risque: erreur systématique d'échelle si métadonnées source mal alignées.

### 3.5 Centroides d'aléa basés sur points d'exposition
- Où: `backend/app/risk_engine/hazard_loader.py:548-588`
- Approximation potentielle: champ d'aléa évalué aux centroides issus des points d'actifs (et légère densification si petit échantillon).
- Risque: dépendance de la physique calculée à l'échantillonnage d'exposition (et pas à une grille physique fixe).

## 4) Normalisation fréquentielle du catalogue synthétique

- Où: `backend/app/risk_engine/hazard_loader.py:103-122`, `backend/app/risk_engine/climada_engine.py:178-190`
- Approximation potentielle: fréquence des événements divisée par `storm_years` (10000 par défaut).
- Risque: si le nombre d'événements retenus est faible, la masse fréquentielle totale peut rester < seuil RP50/RP100.
- Effet observé typique: RP50/RP100 nuls malgré EAI et événement max non nuls.

## 5) Dommage direct vent

### 5.1 Mapping courbes vent par type d'actif
- Où: `backend/app/risk_engine/impact_functions.py` (via `resolve_tc_impact_func_id`), usage `impact_runner.py:428`
- Approximation potentielle: dépend fortement de la qualité du mapping `asset_type -> impf`.
- Risque: courbe non représentative des actifs locaux.

### 5.2 PML sur échantillon fini
- Où: `backend/app/risk_engine/climada_engine.py:103-125`, `:290`, `:345`
- Approximation potentielle: estimation PML basée sur tri pertes + fréquences disponibles.
- Risque: pour des queues faibles, RP élevés instables/sous-estimés.

## 6) Composantes pluie et submersion côtière

### 6.1 Pluie proxy
- Où: `backend/app/risk_engine/climada_engine.py:536-568`, `backend/app/risk_engine/impact_functions_multi_hazard.py:213-228`
- Approximation potentielle:
  - pluie construite à partir des tracks TC (modèle `R-CLIPER`/`TCR`),
  - courbes pluie construites par conversion profondeur->mm proxy avec coeff de base 0.25.
- Risque: dépendance forte aux hypothèses proxy (pas de modélisation hydrologique 2D explicite).

### 6.2 Submersion côtière "bathtub"
- Où: `backend/app/risk_engine/climada_engine.py:496-535`
- Approximation potentielle: modèle `TCSurgeBathtub` dépendant du DEM et simplifiant la dynamique.
- Risque: topographie/connexions hydrauliques simplifiées, erreurs locales de profondeur.
- Risque opérationnel: `MemoryError` possible sur grands runs, composante manquante ou remplacée en chaîne proxy.

## 7) Combinaison multi-aléa

- Où: `backend/app/risk_engine/climada_engine.py:296-349`, `:578-584`
- Approximation potentielle: somme composante par composante (wind+rain+surge), puis cap par point à la valeur de l'actif.
- Risque: ignore la dépendance temporelle fine entre aléas, peut sous/surestimer selon corrélations réelles.

## 8) Approximation `max_loss_by_point`

- Où: `backend/app/risk_engine/climada_engine.py:278`
- Approximation potentielle: max loss point approché à partir de `eai_exp` et de la perte max portefeuille (méthode interne d'approximation).
- Risque: distribution spatiale des pertes extrêmes simplifiée, impacte états réseau et dépendances.

## 9) Interdépendance électricité -> eau

- Où: `backend/app/risk_engine/interdependency.py:9-16`, `:39-68`, `:135-280`
- Approximation potentielle:
  - états discrets S0/S1/S2/S3 via seuils fixes,
  - uplift eau via coefficients fixes (`0.10/0.25/0.45`),
  - résolution de santé électrique (local, voisin le plus proche, global).
- Risque: forte sensibilité à des seuils/conventions non calibrés localement.

## 10) Couche proxy / publication case study

### 10.1 Ratios composantes par scénario
- Où: `scripts/case_study_proxy_utils.py:145-180`
- Approximation potentielle: ratios normalisés par scénario; fallback `rp50 -> rp100/annual` si ratio rp50 nul.
- Risque: l'affichage composante peut rester informatif mais non strictement équivalent à un run complet.

### 10.2 Fallback surge dans le proxy
- Où: `scripts/build_case_study_multi_hazard_proxy.py:436-460`
- Approximation potentielle: en cas de surge nul/échec en run léger, reconstitution depuis carte d'aléa + courbes.
- Risque: cohérence physique moindre qu'un calcul direct point-à-point complet.

## 11) Point critique observé sur les RP50/RP100 vent

Diagnostic reproduit en mode sans fallback moteur (`SIB_RISK_ALLOW_CLIMADA_FALLBACK=false`) avec:
- `dynamic_max_tracks=100`
- `multi_hazard_enabled=false`
- source aléa: `dynamic_parquet`

Résultat (fichier `outputs/diagnostics/no_fallback_wind_only_tracks100.json`):
- Guadeloupe: `wind_eai_sum > 0`, `wind_max_event > 0`, mais `wind_pml_50 = 0` et `wind_pml_100 = 0`.
- Martinique: même comportement.

Interprétation: ce pattern est cohérent avec un **échantillon de tracks trop court** pour alimenter les périodes de retour 50/100 ans (masse fréquentielle insuffisante dans la queue), et **pas** avec un vent nul.

## 12) Contrôles recommandés (priorité)

1. Stabiliser RP50/RP100:
- augmenter `dynamic_max_tracks` (>= 1000 pour les runs de référence),
- journaliser `sum(event_frequency)` et `n_events` par aléa/scénario.

2. Verrouiller la cohérence publication:
- publier uniquement des artefacts issus d'un run de référence complet,
- distinguer explicitement runs "light/proxy" vs "production".

3. Encadrer les approximations multi-aléas:
- tracer quand `surge`/`rain` est absent ou fallback,
- afficher un drapeau de qualité des résultats par scénario (full vs proxy).

4. Sensibilité structurée:
- lancer une campagne de sensibilité sur: `dynamic_max_tracks`, `spacing_m`, `max_points_per_feature`, `spatial_padding_deg`, seuils interdependency, coeff runoff/proxy pluie.

### 12.1 Pourquoi journaliser (noté) `sum(event_frequency)` et `n_events` ?

`sum(event_frequency)` correspond a la masse totale de frequence annuelle retenue apres filtrage et troncature du catalogue d'aléas. `n_events` est simplement le nombre d'evenements effectivement conserves pour un alea et un scenario donnes.

Utilite:
- verifier rapidement si la queue de distribution est suffisante pour calculer RP50/RP100;
- comparer deux reruns et voir s'ils utilisent le meme sous-ensemble de tracks;
- distinguer un vrai zero physique d'un zero provoque par un echantillonnage trop court ou un cap trop agressif;
- tracer la perte d'information quand `dynamic_max_tracks` change.

Consequences si on met cela en place:
- on n'ajoute pas de physique nouvelle, seulement de la traçabilite;
- les logs et les metadonnees gagnent quelques champs, mais le cout est negligeable;
- en contrepartie, on dispose d'un signal simple pour expliquer pourquoi RP50/RP100 bougent d'un rerun a l'autre ou tombent a zero;
- si `sum(event_frequency)` est trop faible ou si `n_events` chute nettement, il faut considerer le run comme sous-echantillonne pour les queues d'extremes, meme si EAI et evenement max restent non nuls.
