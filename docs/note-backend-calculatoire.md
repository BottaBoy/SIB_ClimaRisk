# Note detaillee - Backend calculatoire des risques cycloniques (CLIMADA)

Derniere mise a jour: 2026-07-06

## 1) Objectif
Cette note explique:
- comment le backend calcule les impacts STORM et STORM_CMCC avec CLIMADA,
- comment la dependance electricite -> eau est appliquee (post-traitement prudent),
- quels champs sont produits dans le JSON final,
- comment les fichiers Python interagissent.

Perimetre territorial courant du lot "complete analysis":
- `guadeloupe` (alias CLI `gua`)
- `martinique` (alias CLI `mar`, `mq`, `mtq`)
- `saint-barthelemy` (alias CLI `stb`, `blm`, `saintbarth`)

Contrat runtime/web fige pour Saint-Barthélemy:
- cle runtime/web: `saint-barthelemy`
- id comparatif partage: `saint_barthelemy`
- code population: `BLM`
- bassin d'aléa: `NA`
- page web statique: `#page7`
- artefacts web: `web/data/saint-barthelemy-*.json`

Hypotheses Saint-Barthélemy figees:
- reference SIG effective: `EPSG:32620` (la mention `EPSG:3620` est traitee comme un typo documentaire)
- courbes de vulnerabilite: reutilisation stricte des types d'infrastructure equivalents Guadeloupe
- valorisation: profil Guadeloupe majore de `+50%`
- zonage AEP: `best_effort_attribute_plus_topology`
- zonage EU: `heuristic_topological_non_validated`
- aucune STEP exploitable n'est disponible dans les donnees source fournies

Le moteur par defaut est maintenant **CLIMADA complet** (`engine=climada_with_interdependency_v1`).
La voie scientifique de production est maintenant **fail-closed**:
- `compute_impacts(...)` rejette `impact_engine_mode=fallback`
- `compute_impacts(...)` rejette `SIB_RISK_ALLOW_CLIMADA_FALLBACK=true`
- `compute_impacts(...)` rejette le fallback HDF5 pre-calcule

Des helpers legacy de fallback peuvent encore exister dans le repo pour audit / historique, mais ils ne constituent plus un mode de production autorise.

---

## 2) Architecture et flux de calcul

```mermaid
flowchart TD
  A[web/index.html + web/assets/app.js] -->|POST /api/v1/runs| B[backend/app/main.py]
  B --> C[backend/app/job_runner.py]
  C --> D[backend/app/risk_engine/pipeline.py]

  D --> E[exposure_ingest.py]
  D --> F[exposure_disaggregation.py]
  D --> G[impact_runner.py]
  D --> H[analysis_export.py]

  G --> I[exposure_to_climada.py]
  G --> J[climada_engine.py]
  G --> K[interdependency.py]
  J --> L[hazard_loader.py]
  J --> M[impact_functions.py]
  L --> N[(tc_hazard_guadeloupe.h5)]
  L --> O[(tc_hazard_guadeloupe_CMCC.h5)]

  H --> P[result.json + territory_results.csv + graphs.json + top_events.csv]
```

### Role des modules
- `exposure_ingest.py`: normalise les expositions utilisateur (CSV/XLSX/GeoJSON/GPKG/dessin).
- `exposure_disaggregation.py`: calcule un resume geometrique (utilise aussi pour pilotage du sampling).
- `exposure_to_climada.py`: convertit les geometries en points CLIMADA (CRS metrique -> WGS84), conserve la valeur totale.
- `climada_engine.py`: charge hazards STORM/STORM_CMCC, applique ImpactCalc CLIMADA, extrait EAI direct / evenements / PML / TVaR.
- `interdependency.py`: applique la propagation elec->eau et calcule la sante `health`.
- `impact_runner.py`: orchestre le tout, produit `territory_results`, `portfolio_results`, `graphs`, `notes`, `meta.modeling`.
- `analysis_export.py`: assemble le payload API et exporte les artefacts CSV/JSON.

### 2.1 Mailles spatiales utilisées par les briques principales

Le tableau ci-dessous recense les principales mailles spatiales et pas d'echantillonnage utilises par le code. Certaines lignes ne correspondent pas a une grille fixe, mais a une fenetre spatiale, a un pas d'echantillonnage ou a une resolution de publication.

| Nom element du code | Description rapide | Maille geographique | Notes |
|---|---|---|---|
| `exposure_to_climada.py` | Echantillonnage des geometries exposees en points CLIMADA et repartition de la valeur des actifs sur ces points. | Pas de grille fixe; `sampling_spacing_m` pilote l'echantillonnage des lignes/polygones. Regroupement territorial secondaire via `TERRITORY_GRID_DEG = 0.2°`. | Une maille plus fine est possible pour des etudes locales, mais elle augmente surtout le nombre de points, donc le temps CPU/RAM. |
| `hazard_loader.py` | Chargement des tracks dans une fenetre spatiale autour des expositions et cap sur le nombre de tracks gardes. | Fenetre spatiale avec `DEFAULT_SPATIAL_PADDING_DEG = 4.0°`; petit-cas avec `DEFAULT_SMALL_SAMPLE_GRID_STEP_DEG = 0.01°`. | Resserer la fenetre accelere le calcul, mais augmente le risque de rater des tracks proches de la zone etudiee. |
| `climada_engine.py` / `TropCyclone`, `TCRain`, `TCSurgeBathtub` | Construction des hazards CLIMADA vent, pluie et submersion a partir des tracks. | Pas de grille fixe propre au moteur; la resolution est celle des centroides/hazards en entree. | Une maille plus fine depend surtout de la source des tracks et du nombre de centroides disponibles. |
| `impact_runner.py` | Agregation de `health` et de la dependance elec -> eau par zone territoriale. | `TERRITORY_GRID_DEG = 0.2°`. | Une maille plus fine est faisable pour une etude locale, mais la dependance devient plus bruiante et plus couteuse. |
| `mean_wind_mps`, `rp50_wind_mps`, `rp100_wind_mps`, `event_max_wind_mps` | Statistiques de cellule pour la couche aléas vent; la meme logique existe pour la pluie (`*_rain_mmph`) et la submersion (`*_surge_m`). | Même maille que la couche d'aléa correspondante: `0.02°` sur Guadeloupe/Martinique, `0.05°` sur les cartes bassin NA/SI. | Ces valeurs sont des statistiques de restitution sur cellule, pas des mailles physiques supplémentaires. Une maille plus fine est possible si l'on accepte plus de calcul et des sorties plus volumineuses. |
| `scripts/build_guadeloupe_wind_maps.py` | Couche aléas vent pour Guadeloupe/Martinique. | Grille de publication `cell_deg = 0.02°`; submersion interne sur `surge_native_cell_deg = 0.01°`. | On dispose déjà d'une sous-maille plus fine pour le surge. Descendre encore est possible, mais le gain devient marginal et le cout monte vite. |
| `scripts/build_guadeloupe_wind_maps.py` | Couche aléas pluie pour Guadeloupe/Martinique. | Grille de publication `0.02°`, même maille que le vent. | Une maille plus fine peut aider si l'on veut zoomer un littoral ou un relief local, mais le bénéfice dépend surtout de la qualité du modèle pluie. |
| `scripts/build_guadeloupe_wind_maps.py` | Couche aléas surge pour Guadeloupe/Martinique. | Calcul natif sur `0.01°`, puis réagrégation en `0.02°` pour l'affichage web. | C'est déjà la maille la plus fine du pipeline courant. La descendre plus bas n'apporterait qu'un gain limité sans nouvelle validation topo/bathy. |
| `scripts/build_basin_wind_maps.py` | Cartes bassin NA/SI (`mean`, `rp50`, `rp100`, `event_max`) pour STORM et STORM_CMCC. | Grille `0.05°`. | Une maille plus fine est possible, mais elle augmente rapidement le volume de sortie et le temps de traitement sur de grands bassins. |
| `scripts/build_na_wind_leaflet_overlays.py` / `scripts/build_basin_wind_leaflet_overlays.py` | Rasterisation et rendu Leaflet des couches d'aléa a partir des cellules calculees. | Même maille que le JSON source (`0.02°` ou `0.05°` selon le jeu). | Une maille plus fine ici ne change pas la physique; elle améliore surtout la lisibilité visuelle, au prix d'un rendu plus lourd. |
| `scripts/build_case_study_multi_hazard_proxy.py` / `scripts/build_guadeloupe_page1_data.py` | Tables et graphiques de restitution page 1/page 2 construits a partir des cellules d'aléa et du proxy multi-aléas. | Pas de nouvelle maille physique; agrégation sur la grille d'aléa correspondante. | On ne gagne en précision que si les grilles amont sont elles-mêmes plus fines et validées. |

### 2.1.1 Nombre de zones de zonage hydraulique et electrique par territoire

Convention de comptage retenue pour eviter les ambiguïtés:
- `zone_uid`: nombre de zones hydrauliques logiques distinctes dans la couche `hydraulic_zones` des GPKG de `outputs/hydraulic_zoning/Zonage_V2`
- `zone_component_key`: nombre de composantes hydrauliques effectivement publiees; une meme zone logique peut etre decoupee en plusieurs polygones
- `elec_grid_0p1deg`: nombre de mailles de zonage electrique publiees dans `web/data/*-network-states.geojson`

| Territoire | Zones hydrauliques distinctes (`zone_uid`) | dont AEP | dont EU | Composantes hydrauliques publiees (`zone_component_key`) | Zonages electriques publies (`elec_grid_0p1deg`) |
|---|---:|---:|---:|---:|---:|
| Guadeloupe | 147 | 47 | 100 | 305 | 40 |
| Martinique | 436 | 343 | 93 | 807 | 20 |
| Saint-Barthelemy | 30 | 24 | 6 | 30 | 2 |

Lecture rapide:
- le zonage hydraulique est beaucoup plus fin que le zonage electrique publie, surtout en Martinique;
- en Guadeloupe et en Martinique, plusieurs zones hydrauliques sont multi-parties, d'ou un nombre de `zone_component_key` superieur au nombre de `zone_uid`;
- a Saint-Barthelemy, dans le bundle courant, chaque zone hydraulique publiee correspond a une seule composante.

### 2.2 Tracks dynamiques: plafond de catalogue et cap conseille

Les chiffres ci-dessous viennent du chargement dynamique STORM/STORM_CMCC sur la fenetre de publication page 5, c'est-a-dire la bbox NA avec le padding spatial du loader. Ils comptent des instances synthetiques distinctes de cyclone, donc une identite physique de type `(Year, track_id)`, avant tout cap `dynamic_max_tracks`.

| Territoire | STORM tracks disponibles | STORM_CMCC tracks disponibles | Plafond reel de sélection | Commentaire |
|---|---:|---:|---:|---|
| Guadeloupe | 23 151 | 24 208 | 23 151 / 24 208 | Au-dessus de ces valeurs, le code ne peut plus enrichir le catalogue car la source est déjà entièrement selectionnee sur cette fenetre. |
| Martinique | 21 288 | 22 292 | 21 288 / 22 292 | Meme lecture: le cap utile est le nombre de tracks effectivement présents dans la zone. |

| Contexte | `dynamic_max_tracks` conseille | Temps de run indicatif | Pourquoi ce choix |
|---|---:|---:|---|
| Runs fixes de demonstration Guadeloupe / Martinique | 1 200 | ~10-20 min par territoire | Compromis deja utilise dans les pages de demo (`page1/page2`) pour garder des RP50/RP100 plus stables sans exploser le temps de calcul. |
| Runs "light" page 5 pour les utilisateurs | 300 | ~3-6 min par territoire | Compromis interactif deja retenu pour la carte d'aléas; assez léger pour l'UX, mais encore sous-échantillonné pour la queue des extremums. |

En pratique:
- `300` est le bon ordre de grandeur pour une visualisation rapide et fluide.
- `1 200` est le bon ordre de grandeur pour les runs de demonstration fixes.
- Si l'on cherche une convergence plus forte des RP50/RP100, il faut monter encore le cap, mais le temps de calcul augmente vite et le gain devient de plus en plus marginal.

### 2.3 Analyse comparative des aléas

La chaine comparative hazard-only (lots 2 a 6) n'utilise pas la meme fenetre spatiale que les cartes page 5 historiques. Elle construit une grille comparative par territoire sur `territory_grid_deg = 0.2°`, puis charge les tracks dynamiques dans la fenetre territoriale elargie par `DEFAULT_SPATIAL_PADDING_DEG = 4.0°`.

Audit du 2026-05-22: la premiere version de cette section etait incorrecte. Elle sous-comptait massivement les cyclones en groupant les catalogues comparatifs sur `track_id` seul. Or, dans STORM / STORM_CMCC, le meme `track_id` se repete d'annee en annee a l'interieur d'un bloc synthetique. L'identite physique correcte d'un cyclone est donc au minimum `(Year, track_id)`. Le loader comparatif et la preparation des catalogues ont ete corriges pour utiliser cette identite year-aware.

Les chiffres ci-dessous ont ete re-estimes le 2026-05-22 avec la meme logique que le runner comparatif, mais avec cette identite year-aware correcte (`load_storm_hazards_from_parquet_for_points(..., build_hazards=False, max_tracks=0)`). Ils correspondent donc au nombre de cyclones synthetiques reellement retenus par territoire avant construction des hazards, en mode `full tracks`.

| Territoire | Bassin | Points grille comparative | STORM full tracks | STORM_CMCC full tracks | Lecture operationnelle |
|---|---|---:|---:|---:|---|
| Guadeloupe | NA | 30 | 21 846 | 22 832 | `300` et `1 500` restent deux sous-echantillons tres partiels de la fenetre comparative. |
| Martinique | NA | 20 | 21 530 | 22 599 | Meme lecture: l'ecart de temps entre `300` et `1 500` est attendu. |
| Guyane | NA | 550 | 6 023 | 6 432 | Le cap reste tres loin du `full tracks`. |
| Saint-Barthelemy | NA | 6 | 18 931 | 20 070 | Le perimetre est petit, mais la fenetre dynamique elargie reste tres chargee. |
| Saint-Martin | NA | 6 | 18 736 | 19 863 | Meme lecture que Saint-Barthelemy. |
| Saint-Pierre-et-Miquelon | NA | 16 | 6 011 | 7 407 | `300` et `1 500` restent des caps numeriques reels. |
| La Reunion | SI | 20 | 15 571 | 17 257 | `300` ne couvre qu'une petite fraction du catalogue utile. |
| Mayotte | SI | 12 | 3 779 | 5 706 | `300` et `1 500` restent distincts et physiquement non equivalentes au full. |
| Nouvelle-Caledonie | SP | 1 846 | 40 227 | 39 112 | C'est le cas comparatif le plus charge du perimetre actuel. |

Consequences pratiques pour les nouvelles taches de comparaison:
- L'ancienne conclusion "`300` suffit deja" etait fausse car elle reposait sur le sous-comptage legacy de `track_id`.
- `dynamic_max_tracks = 300`, `1500` et `0` (`full tracks`, donc sans cap) representent bien trois regimes numeriques differents sur le perimetre comparatif actuel.
- Pour Guadeloupe, `300` represente environ 1,4 % du full STORM et `1 500` environ 6,9 %; pour Martinique on est du meme ordre de grandeur.
- L'ecart de temps de calcul observe entre un run comparatif `300` et `1 500` sur Guadeloupe/Martinique est donc cohérent avec le volume de tracks reellement traite.
- Pour la sortie operateur, le point de lecture a ouvrir apres chaque run comparatif est `outputs/hazard-comparison-runs/<run_id>/comparison-exports/index.html`.
- Le mode `full tracks` de la chaine comparative est declenche explicitement par `--dynamic-max-tracks 0`.

---

## 3) Exposition

Le backend accepte:
- `input_mode=file`: CSV, XLSX, GeoJSON, GPKG,
- `input_mode=drawn_geojson`: expositions dessinees.

Categories supportees:
- `habitation`
- `ouvrage_eau`
- `ouvrage_electrique`

Aliases principaux:
- `electric`, `electricity`, `power` -> `ouvrage_electrique`
- `water`, `water_network` -> `ouvrage_eau`

---

### 3.0 Inventaire detaille des infrastructures eau et electricite utilisees pour l'exposition

Le tableau ci-dessous documente les couches eau et electricite actuellement mobilisables pour l'exposition Guadeloupe / Martinique. Les valeurs ont ete relues directement dans les couches source disponibles dans `uploads/Infra_Eau_*` et `uploads/Infra_Elec_*` et doivent etre lues comme un inventaire technique de travail, pas comme un inventaire patrimonial certifie gestionnaire par gestionnaire.

| Territoire | Famille infra | Sous-type / role | Source principale | Unite de comptage | Quantite | Longueur / capacite / stockage | Detail technique | Champs source mobilises | Limites |
|---|---|---|---|---|---:|---|---|---|---|
| Guadeloupe | AEP reseaux | canalisations | `AEP/cana_aep.gpkg` couche `canalisationaep240925` | troncons + km | 31 942 | ~3 151.8 km geometriques; `conduite_longrecol` cumule ~3 154.1 km | Materiaux dominants: `FI` ~1 570.6 km, `PVC` ~473.0 km, `AC` ~153.2 km, `FD` ~144.7 km, `PEHD` ~104.4 km, `FG` ~75.1 km, `PVC_BO` ~51.2 km; diametre interieur moyen variable selon materiau | `conduite_materiau`, `conduite_diametreint`, `conduite_diametrenominal`, `conduite_longrecol`, `pelem_zonehydraulique` | `FI` / `FD` / `FG` sont des codes metier locaux; la doc ne fournit pas ici de table de decodage officielle complete |
| Guadeloupe | AEP ouvrages | reservoirs / cuves | `AEP/ouvrage_aep.gpkg` couche `ouvrages` | ouvrages | 202 | stockage cumule `ovrg_cuv_vol` ~153 501 | Type ouvrage `CUV`; diametre cuve moyen `ovrg_cuv_diam` ~14.0; `ovrg_cuv_type` quasi non renseigne | `ovrg_type`, `ovrg_cuv_type`, `ovrg_cuv_vol`, `ovrg_cuv_diam` | L'unite de `ovrg_cuv_vol` n'est pas re-explicitee dans la couche; elle est conservee telle quelle dans la note |
| Guadeloupe | AEP ouvrages | captages / forages / sources | `AEP/ouvrage_aep.gpkg` couche `ouvrages` | ouvrages | 68 | somme `ovrg_capfor_cap_qresv` ~216 | Sous-types: `SOURCE` 28, `DRAIN` 18, `FOR` 17, `AUT` 3, `CAP` 2 | `ovrg_type`, `ovrg_capfor_type`, `ovrg_capfor_cap_qresv` | La signification physique exacte de `ovrg_capfor_cap_qresv` doit etre verifiee dans le dictionnaire RAEPA source avant toute lecture contractuelle |
| Guadeloupe | AEP ouvrages | usines / traitement potable | `AEP/ouvrage_aep.gpkg` couche `ouvrages` | ouvrages | 40 | `up_caph` cumule ~10 092; `up_capj` cumule ~226 750 | Filieres / codes: `TRAIT` 37, `DESINF` 2, `AUT` 1 | `ovrg_type`, `up_caph`, `up_capj`, `up_filetyp`, `up_traitdesc` | Les unites de `up_caph` et `up_capj` ne sont pas re-documentees dans la couche; elles sont gardees brutes |
| Guadeloupe | AEP ouvrages | stations de pompage / surpression | `AEP/ouvrage_aep.gpkg` couche `ouvrages` | ouvrages | 119 | pas de capacite cumulee robuste exploitee | Types: `SURP` 86, `PMP` 27, `NA` 4, `AUT` 1, `INC` 1 | `ovrg_type`, `pmp_typ`, `pmp_abcap` | Categorie utile pour l'exposition AEP, mais la couche ne fournit pas ici une capacite homogenisable simple |
| Guadeloupe | EU reseaux | canalisations | `EU/cana_eu.gpkg` | troncons + km | 13 795 | ~819.2 km geometriques | Materiaux codes: `AA` ~320.0 km, `AX` ~284.1 km, `INC` ~58.4 km, `AZ` ~53.5 km, `AV` ~30.9 km, `AMC` ~13.0 km, `INOX` ~12.9 km; `PVC` ~5.0 km, `PEHD` ~2.4 km | `conduite_materiau`, `conduite_longrecol`, `conduite_diametrenominal`, `pelem_secteur` | Les codes materiaux EU (`AA`, `AX`, `AZ`, etc.) ne sont pas traduits en libelles explicites dans la source actuelle |
| Guadeloupe | EU ouvrages | postes de refoulement | `EU/pr.gpkg` couche `eu_pr` | ouvrages | 348 | baches `stpmp_bachevol` cumulees ~2 096.0; pompes cumulees ~554 | Materiaux de refoulement / reference: `INOX` 66, `AM` 48, `AX` 48, `AZ` 43, `AA` 37; 58 enregistrements sans materiau de reference; nombreuses dimensions et volumes de bache disponibles | `stpmp_capacitepompes`, `stpmp_pompenombre`, `stpmp_ref_mat`, `stpmp_ref_diam`, `stpmp_ref_long`, `stpmp_bachevol`, `stpmp_type` | `stpmp_capacitepompes` est heterogene et peu normalisable en une unite unique dans cette note |
| Guadeloupe | EU ouvrages | STEP / STEU | `EU/step.gpkg` couche `eu_stepn` | ouvrages | 142 | `step_traitdebitref` cumule ~4 538; `step_traitcapq` cumule ~33 438; `step_traitcapdbo` cumule ~13 371 | Tres forte richesse de champs process, pompage, baches et materiaux; `step_systeme` est souvent vide (`NA` 129) mais quelques systemes nommes restent presents | `step_traitdebitref`, `step_traitcapq`, `step_traitcapdbo`, `step_systeme`, `step_pmpebcapacite`, `step_pmpetcapacite`, `step_pmpebbccaracmat`, `step_pmpetbccaracmat` | Les unites ne sont pas re-rappelees dans tous les champs; la lecture doit rester prudente sans dictionnaire source complet |
| Martinique | AEP reseaux | canalisations CACEM | `AEP/Réseaux/cacem_aep_cana.shp` | troncons + km | 9 008 | ~1 039.5 km geometriques | Materiaux explicites: `Fonte` ~447.6 km, `PVC MO` ~308.2 km, `PVC` ~148.9 km, `Fonte ductile` ~33.1 km, `Polyethylène HD` ~31.0 km, `PE` ~18.5 km, `PE bandes bleues` ~7.9 km; diametre moyen renseigne | `materiau`, `diametre`, `longeur`, `type_resea`, `sect_dis`, `ville` | Nomenclature gestionnaire locale; certains materiaux restent saisis comme `Inconnu` |
| Martinique | AEP reseaux | canalisations CAESM | `AEP/Réseaux/caesm_aep_cana.shp` | troncons + km | 12 581 | ~1 376.5 km geometriques | Longueur importante mais pas de ventilation materiau exploitable dans la couche lue ici (`NA` majoritaire) | `materiau`, `diametre`, `longeur`, `type_resea`, `sect_dis` | La couche parait beaucoup moins renseignee sur le materiau que CACEM |
| Martinique | AEP reseaux | canalisations CAP Nord | `AEP/Réseaux/capnord_aep_cana.shp` | troncons + km | 27 145 | ~950.7 km geometriques | Meme lecture que CAESM: ventilation materiau non exploitable proprement dans l'etat courant | `materiau`, `diametre`, `longeur`, `type_resea`, `sect_dis` | Le champ `materiau` n'est pas suffisamment renseigne pour un tableau par materiau fiable |
| Martinique | AEP ouvrages | UPEP / traitement potable | `AEP/Usines/UPEP_2017.shp` | ouvrages | 27 | `Q_REG_M3J` cumule ~155 449 | Exploitants: `SMDS` 13, `SME` 9, `ODYSSI` 4, `CTM` 1 | `UPEP`, `Q_REG_M3J`, `EXPL`, `BENEF` | La couche est exploitable pour les capacites de production, mais ne detaille pas ici finement les filieres de traitement |
| Martinique | AEP ouvrages | captages / forages | `AEP/Forages/AEP_CAPTAGES_FORAGES_2024.shp` | ouvrages | 6 | `prlv2017m3` disponible ponctuellement dans la couche source mais pas homogenise ici | Tous les points visibles dans l'extrait courant sont de type `Forage` | `CAPTAGE`, `TYPE`, `QP_EXPLOIT`, `prlv2017m3`, `UPEP` | L'echantillon present dans le workspace est tres reduit; pas de couche dediee reservoirs/cuves AEP clairement separee pour la Martinique |
| Martinique | AEP ouvrages | reservoirs / stockage | pas de couche dediee separee clairement exploitable dans `AEP` | ouvrages | n/a | non disponible dans les couches source actuelles utilisees ici | Les noms de reservoirs apparaissent dans certains libelles de zonage, mais pas comme une couche patrimoniale de stockage autonome directement reutilisee pour l'exposition | n/a | Ne pas deduire un nombre de reservoirs a partir des seuls noms de zones ou des secteurs AEP |
| Martinique | EU reseaux | canalisations | `Assainissement/Reseaux/*.shp` | troncons + km | n/a | CACEM ~386.1 km; CAESM ~305.1 km; SCISM ~180.7 km; SEA ~77.0 km | Les couches EU reseaux portent surtout des longueurs (`LONGCALC`, `LONGUEUR`); pas de ventilation materiau fiable dans l'etat courant | `LONGCALC`, `LONGUEUR` et attributs de reseau par gestionnaire | Le detail `PVC / fonte / PEHD` n'est pas proprement disponible sur ces couches EU Martinique |
| Martinique | EU ouvrages | postes de refoulement | `Assainissement/Poste de refoulement/Postes de refoulement_2024.shp` | ouvrages | 480 | `capacite_1` cumulee ~65 446 | Tranches capacitaires documentees: `< 2000 eH` 53, `2000 - 10 000 eH` 28; exploitants principaux `SME` 212, `Odyssi` 83, `SEA` 59 | `poste`, `steu`, `capacite_1`, `tranche ca`, `exploitant`, `cd_steu` | Le champ de type est partiellement renseigne (`A1`, `A2`, sinon vide) |
| Martinique | EU ouvrages | STEP / STEU communales | `Assainissement/STEP/steu_communales.shp` | ouvrages | 109 | `capacite E` cumulee ~361 281 | Types dominants: `Boues activées` 79, `Biodisques` 7, puis `Filtres plantes de vegetaux`, `Culture fixee`, `Oxyfix`, `Micro station`, `SBR`, `Membranes`; filieres boues renseignees | `station`, `code_steu`, `capacite E`, `type_sta`, `boues`, `exploitant` | Les STEP privees restent hors du tableau principal pour eviter de melanger patrimoine public et installations isolees |
| Guadeloupe | Elec reseaux | BT aerien | `lignes-basse-tension-bt-aerien-gua.geojson` | troncons + km | 30 319 | ~3 063.9 km geometriques | Reseau basse tension aerien; tous les troncons visibles sont `En exploitation` | `statut`, `geometry` | La couche ne porte pas ici de materiau, section de conducteur, tension fine ou date de pose |
| Guadeloupe | Elec reseaux | BT souterrain | `lignes-basse-tension-bt-souterrain-gua.geojson` | troncons + km | 33 085 | ~1 616.5 km geometriques | Reseau basse tension souterrain; tous les troncons visibles sont `En exploitation` | `statut`, `geometry` | Pas de detail cable (section, isolation, materiau) dans la couche exploitee |
| Guadeloupe | Elec reseaux | HTA aerien | `lignes-haute-tension-hta-aerien-gua.geojson` | troncons + km | 1 819 | ~529.8 km geometriques | Reseau HTA aerien; statut unique `En exploitation` | `id`, `statut`, `geometry` | La classe distingue bien HTA / aerien mais sans niveau de tension plus fin ni type de support |
| Guadeloupe | Elec reseaux | HTA souterrain | `lignes-haute-tension-hta-souterrain-gua.geojson` | troncons + km | 7 766 | ~1 956.8 km geometriques | Reseau HTA souterrain; statut unique `En exploitation` | `id`, `statut`, `geometry` | Pas de detail cable ni de typologie technique supplementaire dans le GeoJSON courant |
| Martinique | Elec reseaux | BT aerien | `lignes-basse-tension-bt-aerien-martinique.geojson` | troncons + km | 27 071 | ~2 427.7 km geometriques | Reseau basse tension aerien; tous les troncons visibles sont `En exploitation` | `statut`, `geometry` | La couche ne porte pas de materiau ni de section de conducteur |
| Martinique | Elec reseaux | BT souterrain | `e_troncon_cable_bt_me_position_me_position-martinique.geojson` | troncons + km | 21 512 | ~838.4 km geometriques | Reseau basse tension souterrain; tous les troncons visibles sont `En exploitation` | `statut`, `geometry` | Pas de detail cable exploitable au-dela de `BT souterrain` |
| Martinique | Elec reseaux | HTA aerien | `lignes-haute-tension-hta-aerien-martinique.geojson` | troncons + km | 2 665 | ~560.8 km geometriques | Reseau HTA aerien; statut unique `En exploitation` | `id`, `statut`, `geometry` | Pas de ventilation par tension nominale, type de pylone ou conducteur |
| Martinique | Elec reseaux | HTA souterrain | `lignes-haute-tension-hta-souterrain-martinique.geojson` | troncons + km | 4 877 | ~1 343.2 km geometriques | Reseau HTA souterrain; statut unique `En exploitation` | `id`, `statut`, `geometry` | La couche permet un lineaire fiable, mais pas un detail technique type cuivre / alu / section |

Points de lecture utiles:
- les longueurs de reseau ci-dessus sont prioritairement lues sur la geometrie reprojetee (`EPSG:5490`), puis comparees aux champs longueur natifs quand ils existent;
- pour la Guadeloupe AEP, les longueurs geometriques et `conduite_longrecol` sont coherentes a quelques km pres, ce qui rend le lineaire global lisible;
- pour la Guadeloupe EU et une partie de l'AEP Martinique, les materiaux sont parfois codes ou partiellement renseignes; il faut donc eviter toute sur-interpretation sans dictionnaire gestionnaire;
- pour l'electricite, les couches actuellement integrees sont essentiellement des lineaires de reseau `BT/HTA` et `aerien/souterrain`; elles sont robustes pour les km lineaires, mais pauvres en attributs techniques fins;
- les capacites de traitement, de pompage et de stockage sont volontairement laissees dans les unites source quand la couche ne redonne pas une unite documentaire parfaitement explicite;
- la Martinique dispose d'une bonne couche UPEP et de couches PR / STEP exploitables, mais pas d'une couche reservoirs AEP autonome clairement mobilisee dans la chaine d'exposition actuelle.

---

### 3.1 Conversion exposition -> CLIMADA

Fichier: `backend/app/risk_engine/exposure_to_climada.py`

Principe:
1. chaque geometrie est convertie en objet shapely,
2. projection en CRS metrique (`SIB_RISK_CLIMADA_METRIC_CRS`, defaut `EPSG:3857`),
3. echantillonnage en points:
   - point/multipoint: points existants,
   - ligne/multiligne: interpolation selon `sampling_spacing_m`,
   - polygone/multipolygone: grille interne (avec cap),
4. reprojection WGS84,
5. repartition de la valeur de l’actif sur les points echantillonnes.

Parametres runtime:
- `sampling_spacing_m` (depuis le run),
- `SIB_RISK_CLIMADA_MAX_POINTS_PER_FEATURE` (defaut `300`) pour controler cout CPU/memoire.

Le mapping metier est conserve par point:
- `feature_id`, `territory_id`, `infra_class`, `asset_type`, `exposure_category`.

---

## 4) Aléas

Fichier: `backend/app/risk_engine/climada_engine.py`

### 4.1 Construction des aléas et calcul direct CLIMADA
1. chargement des hazards via `hazard_loader.py`:
   - STORM: `tc_hazard_guadeloupe.h5`
   - STORM_CMCC: `tc_hazard_guadeloupe_CMCC.h5`
2. normalisation de frequence:
   - `hazard.frequency = hazard.frequency / storm_years` (`storm_years=10000` par defaut)
3. creation d'un profil multicourbe tropical cyclone via `impact_functions.py`:
   - courbe Eberenz Caraibes (`Eberenz_2021_TC`) conservee comme courbe par defaut,
   - courbes D2 (vulnerabilite uniquement) chargees depuis `data/tc_vulnerability_curves_sib_v1.json`,
   - mapping explicite `asset_type -> impf_TC` applique dans `exposure_to_climada.py`.
4. calcul CLIMADA:
   - `ImpactCalc(exposures, impfset, hazard).impact(save_mat=True, assign_centroids=False)`

### 4.2 Sorties directes par alea
- `eai_direct_by_point` (EAI direct par point d’exposition),
- `max_loss_by_point` (perte max evenementielle par point, extraite de `imp_mat.max(axis=0)`),
- `at_event_loss` (perte portfolio par evenement),
- `aai_agg_eur`,
- `max_event_loss_eur` (champ public historique, desormais interprete comme une perte de queue de type percentile 99),
- `raw_max_event_loss_eur` (max evenement brut conserve pour QA / audit),
- `pml_eur` pour RP 10/20/50/100/200,
- `tvar_95_eur`,
- `top_events` (top N, defaut 20).

### 4.3 Tableau des courbes de vulnerabilite appliquees (vent + pluie/submersion)

| Type d'infrastructure (asset_type) | Courbe vent (windstorm) | Courbe pluie/submersion (depth) | Provenance geographique principale | Justification (resume) |
|---|---|---|---|---|
| `elec_bt_aerien` | `W3.10` | `F6.2` | Mexique + D2 inondation | Courbe reseau electrique aerien |
| `elec_hta_aerien` | `W3.14` | `F6.2` | Mexique + D2 inondation | Courbe reseau electrique aerien HTA |
| `elec_bt_souterrain` | `W16.1` | `F6.1` | Global + D2 inondation | Option prudente non nulle pour reseau enterre |
| `elec_hta_souterrain` | `W16.1` | `F6.1` | Global + D2 inondation | Option prudente non nulle pour reseau enterre |
| `eau_aep_cana` | `W16.1` | `F19.3` | Global + D2 inondation | Reseau eau lineaire |
| `eau_eu_cana` | `W19.1` | `F19.3` | Global + D2 inondation | Reseau EU lineaire |
| `eau_eu_pr` | `EBERENZ_2021_TC` | `F20.3` | Caraibes + D2 inondation | Choix utilisateur conserve pour PR |
| `eau_eu_step` | `W21.2` | `F18.4` | Philippines + D2 inondation | Ouvrage eau exterieur sensible |
| `eau_aep_ouvrage_trait` | `W21.2` | `F14.4` | Philippines + D2 inondation | Ouvrage eau exterieur sensible |
| `eau_aep_ouvrage_stpmp` | `W21.4` | `F17.4` | Philippines + D2 inondation | Ouvrage eau exterieur sensible |
| `eau_aep_ouvrage_cap` | `W21.10` | `F15.1` | Philippines + D2 inondation | Ouvrage eau exterieur sensible |
| `eau_aep_ouvrage_cuv` | `W21.5` | `F13.1` | Philippines + D2 inondation | Ouvrage eau exterieur sensible |
| `eau_aep_ouvrage_ouveb` | `W21.5` | `F13.1` | Philippines + D2 inondation | Ouvrage eau exterieur sensible |
| `eau_aep_ouvrage_na` | `W21.5` | `F14.4` | Philippines + D2 inondation | Valeur de repli ouvrage AEP |

Notes:
- courbe depth de repli globale: `F17.5`,
- mise a jour specifique: `eau_aep_cana` utilise desormais `F19.3` pour les futurs reruns pluie / submersion cotiere,
- l'endpoint `GET /api/v1/vulnerability/curves` expose le profil actif pour audit/visualisation admin.

---

## 5) Impacts

### 5.1 Regles metier 4 etats + health

### 5.1.1 Etats S0/S1/S2/S3
S0 Opérationnel, S1 Dégradé, S2 Critique, S3 Hors service

Le ratio de dommage direct est:

```text
DR_max = max_event_loss_asset / value_asset
```

Classification:
- `S0`: `DR_max < 0.05`
- `S1`: `0.05 <= DR_max < 0.15`
- `S2`: `0.15 <= DR_max < 0.35`
- `S3`: `DR_max >= 0.35`

### 5.1.2 Sante `health`

```text
health = 1 - (0.3*L_S1 + 0.7*L_S2 + 1.0*L_S3) / L_total
```

Avec:
- `L_total`: poids total (ici somme des valeurs des actifs/points du composant),
- `L_S1`, `L_S2`, `L_S3`: poids dans chaque etat.

Important:
- dans le moteur backend CLIMADA (mode par defaut), `L_*` n'est pas une longueur geometrique en km;
- le poids est la **valeur economique** (`value_eur`) re-agrégée par etat.

La formule `health` est calculee pour tous les composants presents dans `component_health` (elec, eau, habitation, etc.).
En revanche, la propagation de dependance utilise **uniquement** la sante electrique pour ajuster les actifs eau.

### 5.1.3 Reponse directe: "comment est calculee la longueur dans chaque etat ?"

Dans le backend API principal (`interdependency.py`), ce n'est pas une longueur physique mais un poids de valeur:

1. Chaque actif est echantillonne en `n` points (si ligne: pas cible `sampling_spacing_m`, typiquement 100 m):

```text
n_ligne = min(max_points_per_feature, ceil(longueur_m / spacing_m) + 1)
```

### 5.1.4 Couverture population et categorie "non desservie"

Le backend social impact distingue explicitement deux notions:

- etat de service `S0/S1/S2/S3` pour la population couverte par un service,
- population `uncovered` (non desservie) quand un service n'est pas couvert sur une cellule.

Contrat actuel:

- la base sociale est cellulaire (`cell_service_state_from_native_climada_0p2deg`),
- l'electricite est agregee par `territory_id` (cellule 0.2 deg),
- l'eau utilise `zone_component_key` comme unite de service pour l'interdependance et la publication hydraulique,
- la couverture eau est marquee `covered=true` des qu'un service eau est present sur la cellule (presence hydraulique/service), meme sans actif electrique local,
- lors de l'agregation sociale, une population non couverte n'est pas forcee en `S3`: elle est comptabilisee dans `uncovered`.

Implications:

- `S3` signifie "service couvert mais hors service",
- `uncovered` signifie "service non desservi" (hors calcul S0-S3),
- les metriques `total_without_water_aep` / `total_without_water_eu` ne comptent pas les non desservis; elles comptent uniquement les populations couvertes classees `S3`.

Exemple de payload public:

- `portfolio_results.social_impact_population_state_distribution.<hazard>.<service>.uncovered`
- `portfolio_results.social_impact_population_state_distribution.<hazard>.<service>.covered_population`
- `portfolio_results.social_impact_population_state_distribution.<hazard>.<service>.coverage_rate`

Cette categorie "population non desservie" existe donc deja dans le contrat JSON, distincte des etats reseau.
2. La valeur de l'actif est repartie uniformement:

```text
value_point = value_feature / n
```
3. Les buckets de sante sont agreges par etat:

```text
L_total = somme(value_point)
L_S1 = somme(value_point des points en S1)
L_S2 = somme(value_point des points en S2)
L_S3 = somme(value_point des points en S3)
```

Donc, dans l'API backend:
- `L_*` est une masse de valeur exposee par etat (pas un km).
- si `value = longueur_km * cout_km` pour une classe lineaire, `L_*` reste proportionnel a la longueur, mais l'unite reste un poids de valeur.

Note historique sur le fallback (`impact_runner.py`):
- des helpers legacy existent encore pour audit / historique;
- ils ne sont plus un mode de calcul scientifique autorise par l'entree de production `compute_impacts(...)`;
- la documentation ci-dessus decrit donc la voie CLIMADA de production et non un mode degrade executable.

### 5.1.4 Annexe - longueur impactee apres desagregation (hors moteur API principal)

Cette methode n'est pas utilisee dans le backend API principal; c'est une methode annexe pour des tableaux cartes/scripts d'etude.

Principe:
1. calculer `len_km(feature)` pour chaque ligne;
2. distribuer `len_point = len_km(feature) / n_points_feature`;
3. sommer `len_point` par etat pour obtenir `L_km_S0..S3`.

Equivalent pratique deja utilise dans `scripts/build_guadeloupe_page1_data.py`:

```text
weights_km(point) = value_point / value_per_km(classe_lineaire)
```

Puis:

```text
L_km_Sj = somme(weights_km(point) des points en Sj)
```

Cette conversion doit rester reservee aux classes lineaires, et exclure les ouvrages ponctuels (PR/STEP/AEP ouvrages).

---

### 5.2 Propagation elec -> eau (post-traitement prudent)

Fichier: `backend/app/risk_engine/interdependency.py`

Hypothese prudente:
- **tous les actifs eau sont dependants de l’electricite**.

#### 5.2.1 Comment la "partie elec qui alimente la partie eau" est decidee actuellement

Le modele actuel n'utilise pas encore un graphe electrique explicite (poste source -> depart -> pompe/ouvrage eau).
La dependance est donc calculee avec une regle spatiale robuste et traçable:

1. L'exposition est echantillonnee en points (lignes/polygones -> points).
2. Chaque point est affecte a une **maille territoriale** (`territory_id`) via ses coordonnees:
   - fonction ` _territory_for_coords(...) ` dans `exposure_to_climada.py`,
   - maille fixe de `0.2 deg` (`TERRITORY_GRID_DEG = 0.2`).
3. Pour un alea donne (STORM ou STORM_CMCC), on calcule d'abord les etats directs des points elec (`S0..S3`).
4. On calcule ensuite `health_elec` par maille territoriale avec la formule:
   - `health = 1 - (0.3*L_S1 + 0.7*L_S2 + 1.0*L_S3)/L_total`
5. Chaque point eau prend la sante elec de sa maille:
   - si la maille n'a pas de points elec, on prend la sante de la maille electrique la plus proche;
   - et en dernier recours (aucune maille elec disponible), fallback global.
6. Cette sante elec est transformee en etat de dependance (`S0..S3`), puis appliquee aux points eau:
   - etat final eau = `max(etat_direct_eau, etat_dependance_elec)`,
   - uplift de perte indirecte: `S0:+0%`, `S1:+10%`, `S2:+25%`, `S3:+45%`.

Conclusion importante:
- aujourd'hui, la dependance est **spatiale par maille** (maille locale puis maille elec la plus proche), pas encore "electrique topologique" (pas de rattachement pompe->depart HTA/BT identifie dans les donnees source).
- c'est volontairement prudent pour eviter de sous-estimer les pertes eau.

Algorithme:
1. calcul de `health_elec(territoire, alea)` a partir des actifs electriques,
2. conversion en etat de dependance:
   - `health < 0.75` -> au moins `S1`
   - `health < 0.55` -> au moins `S2`
   - `health < 0.35` -> `S3`
3. pour les actifs eau uniquement, uplift d’EAI indirect:
   - `S0: +0%`, `S1: +10%`, `S2: +25%`, `S3: +45%`
4. pour les actifs non-eau (dont elec), `EAI_indirect = 0`.
5. garde-fou par actif/point: `EAI_total <= exposure_eur`.

Formules:

```text
si actif_eau:
  EAI_indirect(i,h) = EAI_direct(i,h) * uplift(state_dep(t,h))
sinon:
  EAI_indirect(i,h) = 0

EAI_total(i,h) = min(exposure_eur(i), EAI_direct(i,h) + EAI_indirect(i,h))
```

#### 5.2.2 Pourquoi on peut observer des ratios d'etats tres proches (voire identiques) entre STORM et STORM_CMCC

Ce n'est pas forcement une erreur de calcul. Dans les sorties actuelles Guadeloupe/Martinique:

1. Les etats sont discrets (4 classes) avec seuils fixes (`5%`, `15%`, `35%`).
   - si deux aleas donnent des ratios de dommage differents mais du meme cote d'un seuil, l'etat reste identique.
2. En scenario annuel, beaucoup d'actifs restent sous `5%` pour les deux aleas:
   - resultat: `S0` pour STORM et STORM_CMCC, donc memes pourcentages d'etats.
3. En scenarios severes (RP1000, evenement max), beaucoup d'actifs depassent `35%` dans les deux aleas:
   - resultat: saturation en `S3`, donc memes ratios d'etats.
4. Pour l'eau, l'etat final est aussi pilote par la dependance elec (`max(direct, dep)`):
   - quand la sante elec est deja tres basse dans les deux aleas, l'eau passe dans le meme etat final meme si les montants en euros restent differents.
5. Les tableaux d'etats peuvent etre ponderes par un poids agregé (souvent valeur exposee dans le backend API, ou longueur proxy dans certains scripts front):
   - de petites differences locales peuvent ne pas changer la repartition agregée.

Point de verification:
- on observe bien des differences sur certains cas (ex. scenario RP100 pour plusieurs classes elec), et les `damage_eur` STORM vs STORM_CMCC sont differents.
- donc le moteur ne "copie" pas les resultats, mais la discretisation en 4 classes peut lisser la difference physique.

---

### 5.3 Aggregation territoriale et portfolio

#### 5.3.1 Territoires
Le backend agrège par maille territoriale (`territory_id`) et produit:
- `eai_storm_direct_eur`, `eai_storm_indirect_eur`, `eai_storm_eur`
- `eai_cmcc_direct_eur`, `eai_cmcc_indirect_eur`, `eai_cmcc_eur`
- `risk_index_storm`, `risk_index_cmcc`

`risk_index_*` est conserve pour compatibilite front:

```text
risk_index = clamp((EAI_total / exposure_eur) * 1000, 0, 100)
```

Interpretation:
- c'est un indice relatif sans unite (pas une perte en euros, pas une probabilite);
- `EAI_total / exposure_eur` mesure la "pression de risque annualisee" rapportee a l'exposition;
- le facteur `*1000` augmente la lisibilite numerique pour l'UI;
- `clamp(0,100)` borne l'indice pour eviter des valeurs extrêmes en affichage.

#### 5.3.2 Portfolio
Pour chaque alea:
- `eai_eur`, `aai_agg_eur`, `percentile_99_loss_eur`
- `eai_direct_eur`, `eai_indirect_eur`
- `pml_10_eur`, `pml_20_eur`, `pml_50_eur`, `pml_100_eur`, `pml_200_eur`, `pml_1000_eur`
- `tvar_95_eur`

Autres blocs:
- `portfolio_results.component_health`
- `portfolio_results.interdependency`
- `portfolio_results.event_summary` (`storm_top_events`, `storm_cmcc_top_events`)

Signification detaillee des variables portfolio:
- `eai_eur`: perte annuelle moyenne totale (direct + indirect) du portefeuille.
- `aai_agg_eur`: meme ordre de grandeur que `eai_eur` dans le payload de sortie actuel (champ garde pour compatibilite).
- `eai_direct_eur`: part directe calculee par alea.
- `eai_indirect_eur`: part additionnelle due a la dependance elec -> eau.
- `percentile_99_loss_eur`: headline public de perte evenementielle de queue pour l'alea.
- `pml_10/20/50/100/200/1000_eur`: pertes de reference par periode de retour.
- pour les graphes de comparaison backend/front, la comparaison synthétique privilegie desormais `annual_eai` + `pml_1000`; `percentile_99_loss_eur` reste expose pour compatibilite, audit et diagnostics.
- `tvar_95_eur`: moyenne des pertes dans la queue de distribution au-dela du quantile 95%.
- `delta.eai_eur`: ecart absolu STORM_CMCC - STORM.
- `delta.eai_pct`: ecart relatif STORM_CMCC vs STORM en pourcentage.
- `component_health`: sante par composant (inclut `health`, `L_total`, `L_S1`, `L_S2`, `L_S3`, `asset_count`).
- `interdependency`: hypothese de dependance, seuils d'etat, uplift, metriques de resolution de sante elec.
- `event_summary`: liste des evenements les plus dommageables par alea.

Note compatibilite:
- certains helpers d'audit ou archives historiques peuvent encore exposer `max_event_loss_eur` comme alias du meme headline public
- le max brut monotone par evenement est conserve separement dans les metriques directes internes via `raw_max_event_loss_eur`

---

### 5.4 Contrat de sortie JSON (compatibilite + extensions)

Le payload conserve la structure historique pour le front:
- `meta`, `exposure_summary`, `territory_results`, `portfolio_results`, `graphs`, `notes`.

Extensions actuelles (additives):
- `meta.engine` identifie le moteur effectif (attendu en production: `climada_with_interdependency_v1`).
- `meta.modeling` explicite les choix de modelisation (storm_years, hazard_source, dependency_mode, scenario_mode, sampling, etc.).
- `asset_results` fournit le detail par actif en plus de `territory_results`.
- `portfolio_results` expose les composantes direct/indirect et les blocs `component_health`, `interdependency`, `event_summary`.

Politique de compatibilite:
- pas de rupture de schema sur les cles top-level principales;
- ajouts principalement en nouveaux champs, pour conserver la compatibilite front existante.

Artefacts telechargeables:
- `territory_results.csv`: export tabulaire des resultats territoriaux.
- `graphs.json`: export des series graphiques backend.
- `top_events.csv`: export des evenements dominants (si `event_summary` present).

---

### 5.5 Graphiques backend (`graphs`)

Le backend conserve les memes cles pour le front:
- `graphs.storm.wind_year_hist`
- `graphs.storm.wind_track_hist`
- `graphs.storm.annual_fec`
- `graphs.storm.lifetime_fec`
- idem `storm_cmcc`
- `graphs.comparison.side_by_side`

Les valeurs sont maintenant derivees des pertes CLIMADA (distribution evenementielle + PML), puis ajustees par le facteur indirect elec->eau.

Conventions actuelles de publication:
- `annual_fec` s'aligne sur la base de periodes de retour `10/20/50/100/200/1000` ans,
- `graphs.comparison.side_by_side` compare `annual_eai` et `pml_1000`,
- `percentile_99_loss_eur` reste disponible dans le payload portefeuille mais n'est plus la metrique privilegiee pour la vue de comparaison synthétique.

---

### 5.6 Parametrage runtime important

Variables d’environnement:
- `SIB_RISK_IMPACT_ENGINE_MODE`: `climada` (defaut) ou `auto`; `fallback` est rejete par l'entree de production
- `SIB_RISK_ALLOW_CLIMADA_FALLBACK`: doit rester `false` en production
- `SIB_RISK_HAZARD_FALLBACK_TO_PRECOMPUTED`: doit rester `false` en production scientifique
- `SIB_RISK_CLIMADA_METRIC_CRS`: ex. `EPSG:3857`
- `SIB_RISK_CLIMADA_MAX_POINTS_PER_FEATURE`: cap sampling
- `SIB_RISK_CLIMADA_TOP_EVENTS_COUNT`: top evenements exportes
- `SIB_RISK_STORM_CONVERT_10MIN_TO_1MIN`: conversion des vents soutenus STORM de la convention moyenne 10 minutes vers l'equivalent 1 minute (defaut: `true`)

Endpoint sante:
- `GET /api/v1/health` retourne un etat minimal de service (`status`, `app`, `now_utc`, `version`)
- les choix de modelisation et de garde-fous sont visibles dans les payloads de run (`meta`, `meta.modeling`), pas dans l'endpoint sante

---

## 6) Annexes et complements

### 6.1 Valorisation monetaire prudente (dossiers reseaux + exceptions)

La valorisation eau n'est plus uniformement basee sur la moyenne observee par territoire dans le comparateur OFB.
Depuis la mise a jour de mai 2026, les classes EU utilisent un profil partage derive des dossiers gestionnaires transmis pour la Guadeloupe, puis applique par defaut a la Martinique et aux territoires futurs tant qu'aucun override explicite n'est fourni.
La granularite runtime reste celle des classes metier (`eau_eu_cana`, `eau_eu_pr`, `eau_eu_step`, `eau_aep_cana`, `eau_aep_ouvrage_*`) : les tableaux par diametre, debit ou capacite sont donc agregees en valeurs representatives de classe.

| Portee | Type d'actif | Regle de valorisation appliquee | Valeur initiale retenue | Valeur active | Source / hypothese | Nombre de points prix utilises |
|---|---|---|---|---|---|---|
| Guadeloupe | AEP canalisations | EUR par km, exception temporaire conservee | 280 000 EUR/km | 776 386 EUR/km | Valeur OFB Guadeloupe conservee tant que le dossier AEP n'est pas transcrit proprement | 24 |
| Martinique | AEP canalisations | EUR par km, exception temporaire conservee | 280 000 EUR/km | 653 445 EUR/km | Valeur OFB Martinique conservee tant que le dossier AEP n'est pas transcrit proprement | 16 |
| Saint-Barthélemy | AEP canalisations | profil Guadeloupe majore +50% | 280 000 EUR/km | 1 164 579 EUR/km | Reutilisation de la valeur active Guadeloupe avec majoration insulaire de cout | 24 |
| Profil partage Guadeloupe applique a Guadeloupe, Martinique et fallback | EU canalisations | EUR par km, moyenne de classe | 340 000 EUR/km | 957 143 EUR/km | Moyenne des 7 points prix documentes dans le dossier EU (3 DN gravitaires + 4 DN refoulement), convertie de EUR/ml en EUR/km | 7 |
| Profil partage Guadeloupe applique a Guadeloupe, Martinique et fallback | EU postes de refoulement (PR) | valeur fixe representative par unite | 900 000 EUR | 397 636 EUR | Moyenne des 11 tranches capacitaires documentees dans le dossier EU | 11 |
| Profil partage Guadeloupe applique a Guadeloupe, Martinique et fallback | EU stations d'epuration (STEP) | valeur fixe representative par unite | 6 000 000 EUR | 8 785 714 EUR | Moyenne de 14 cellules du tableau EUR/EH du dossier EU, converties en valeur unitaire via des milieux de bandes representatifs (2 500 / 7 500 / 17 500 / 30 000 EH) | 14 |
| Saint-Barthélemy | EU canalisations | profil partage Guadeloupe majore +50% | 510 000 EUR/km | 1 435 714,5 EUR/km | Reutilisation du profil EU partage avec majoration insulaire de cout | 7 |
| Saint-Barthélemy | EU postes de refoulement (PR) | profil partage Guadeloupe majore +50% | 1 350 000 EUR | 596 454 EUR | Reutilisation du profil EU partage avec majoration insulaire de cout | 11 |
| Saint-Barthélemy | EU stations d'epuration (STEP) | profil partage Guadeloupe majore +50% | 9 000 000 EUR | 13 178 571 EUR | Reutilisation du profil EU partage avec majoration insulaire de cout | 14 |
| Guadeloupe + Martinique | Elec BT aerien | EUR par km | 180 000 EUR/km | 167 060 EUR/km | D3 (ICF 2002, EU + Norvege + Suisse), overhead power line single 220kV | n/a |
| Guadeloupe + Martinique | Elec BT souterrain | EUR par km | 320 000 EUR/km | 1 336 480 EUR/km | D3 (ICF 2002, EU + Norvege + Suisse), derive de 1 994,39 EUR/m * (167 060 / 249 299) * 1000 | n/a |
| Guadeloupe + Martinique | Elec HTA aerien | EUR par km | 260 000 EUR/km | 249 299 EUR/km | D3 (ICF 2002, EU + Norvege + Suisse), overhead power line single 380kV | n/a |
| Guadeloupe + Martinique | Elec HTA souterrain | EUR par km | 520 000 EUR/km | 1 994 390 EUR/km | D3 (ICF 2002, EU + Norvege + Suisse), 1 994,39 EUR/m * 1000 | n/a |
| Saint-Barthélemy | Elec BT aerien | profil Guadeloupe/Martinique majore +50% | 270 000 EUR/km | 250 590 EUR/km | Reutilisation du profil electrique partage avec majoration insulaire de cout | n/a |
| Saint-Barthélemy | Elec BT souterrain | profil Guadeloupe/Martinique majore +50% | 480 000 EUR/km | 2 004 720 EUR/km | Reutilisation du profil electrique partage avec majoration insulaire de cout | n/a |
| Saint-Barthélemy | Elec HTA aerien | profil Guadeloupe/Martinique majore +50% | 390 000 EUR/km | 373 948,5 EUR/km | Reutilisation du profil electrique partage avec majoration insulaire de cout | n/a |
| Saint-Barthélemy | Elec HTA souterrain | profil Guadeloupe/Martinique majore +50% | 780 000 EUR/km | 2 991 585 EUR/km | Reutilisation du profil electrique partage avec majoration insulaire de cout | n/a |
| Guadeloupe + Martinique | AEP ouvrages (`ovrg_type`) | valeur fixe par type, exception temporaire conservee | `TRAIT=3.5M`, `STPMP=1.2M`, `CAP=1.0M`, `CUV=0.5M`, autres=`0.8M` EUR | inchange | Hypothese interne SIB, maintenue tant que les tableaux AEP exploitables ne sont pas disponibles | n/a |
| Saint-Barthélemy | AEP ouvrages (`ovrg_type`) | profil Guadeloupe/Martinique majore +50% | `TRAIT=5.25M`, `STPMP=1.8M`, `CAP=1.5M`, `CUV=0.75M`, autres=`1.2M` EUR | inchange | Hypothese interne SIB, reprise avec majoration insulaire de cout | n/a |

Pour Saint-Barthélemy, les classes EU, electriques et les ouvrages AEP reutilisent les memes profils avec un multiplicateur `1.5` applique dans `scripts/valuation_ofb.py`.

Choix de modelisation:
- les valeurs EU sont agregees au niveau classe car les scripts de preparation actuels ne valorisent pas encore segment par segment selon un champ `diametre`, `debit`, `capacite_eh` ou `type_traitement`;
- le fallback multi-territoire reste Guadeloupe, ce qui signifie qu'un territoire futur sans profil explicite reutilise le profil partage Guadeloupe pour l'EU et la valeur AEP Guadeloupe par defaut;
- les metadonnees publiees conservent les cles historiques `new_values` et `nb_prix_compares`, mais elles decrivent maintenant un mix dossier gestionnaire + exceptions documentees.

Infrastructures presentes dans l'etude mais non couvertes numeriquement par les dossiers exploitables dans l'etat:
- `eau_aep_cana` : presente dans l'etude, mais le markdown AEP courant ne restitue pas les tableaux numeriques de DN; la valeur OFB existante est donc maintenue temporairement;
- `eau_aep_ouvrage_trait`, `eau_aep_ouvrage_stpmp`, `eau_aep_ouvrage_cap`, `eau_aep_ouvrage_cuv`, `eau_aep_ouvrage_ouveb`, `eau_aep_ouvrage_na` : presentes dans l'etude, mais sans table numerique exploitable dans le markdown AEP courant; les hypotheses internes SIB par `ovrg_type` sont conservees;
- `elec_bt_aerien`, `elec_bt_souterrain`, `elec_hta_aerien`, `elec_hta_souterrain` : presentes dans l'etude mais hors perimetre des dossiers reseaux eau; les valeurs D3 sont conservees;
- les rubriques AEP mentionnees dans le dossier markdown sans valeurs exploitables a ce stade sont: canalisations par DN, reservoirs, rehabilitation, compteurs, stabilisateurs et organes de regulation.

Details techniques:
- lineaires EU agregees: les 7 prix unitaires du dossier EU sont moyens au niveau classe puis convertis en EUR/km;
- PR: les 11 tranches documentees sont moyennes au niveau classe pour conserver un seul `value_eur` par actif dans le runtime actuel;
- STEP: les couts EUR/EH sont convertis en valeurs unitaires de reference par bande, puis moyens au niveau classe pour respecter le contrat runtime existant.
- lineaires: `value_eur = max(5000, longueur_km * cout_km)`
- ouvrages ponctuels: valeur fixe par type d’ouvrage.

---

### 6.2 Scripts de preparation des donnees Guadeloupe

- `scripts/build_guadeloupe_complete_analysis.py`
  - construit la reference complete eau+electricite et lance le backend de calcul.
- `scripts/build_guadeloupe_wind_maps.py`
  - calcule les cartes d'aleas web Guadeloupe/Martinique:
    - vent natif CLIMADA via `TropCyclone.from_tracks(...)`,
    - pluie native CLIMADA via `TCRain.from_tracks(...)`,
    - submersion cotiere native CLIMADA via `TCSurgeBathtub.from_tc_winds(...)`,
    - clipping final par masque administratif ADM0.
- `scripts/build_guadeloupe_water_infra_map.py`
  - construit la couche web de toutes les infrastructures d’eau.
- `scripts/rebuild_tc_hazard_na.py`
  - reconstruit les hazards TC STORM/STORM_CMCC (bassin NA) avec les centroids Guadeloupe.

---

### 6.3 Note de mise a jour visuelle cartes NA (2026-03-11)

Une mise a jour a ete appliquee sur le rendu des cartes d'alea NA pour supprimer les bandes visuelles (lignes blanches / mailles minimales apparentes) dans les exports cartographiques et overlays web.

Portee de la mise a jour:
- remplissage visuel des mailles vides en mode `nearest` lors du rendu (`scripts/build_na_wind_leaflet_overlays.py`), limite a une distance locale de mailles pour eviter de recouvrir les zones hors donnees,
- nouveau script d'export statique NA (`scripts/render_na_wind_static_maps.py`) pour produire les 6 cartes sans basemap et les 6 cartes basemap alpha50.

Important:
- cette mise a jour est strictement **visuelle**;
- aucun changement n'est applique au pipeline de calcul d'impact CLIMADA;
- aucun changement des fichiers hazard utilises pour les calculs (`*.h5`) ni des resultats d'impact (`portfolio_results`, `territory_results`).

---

### 6.4 Limites connues

- La propagation elec->eau est prudente et non basee sur un graphe electrique explicite poste-source -> equipement.
- Le couplage indirect est applique en multiplicateur d’EAI direct (pas encore simulation dynamique multi-etapes par evenement).
- Le cap de points par geometrie (`max_points_per_feature`) est necessaire pour maitriser le cout calculatoire.

---

### 6.5 Sources STORM completes

- STORM present climate (all basins):  
  https://data.4tu.nl/articles/dataset/STORM_IBTrACS_present_climate_synthetic_tropical_cyclone_tracks/12706085
- STORM CMCC:  
  https://data.4tu.nl/datasets/98900e17-8e01-4d70-b3b6-ca1a1da2f194/2

---

### 6.6 Comparatif runs de reference (mise a jour du 18 mars 2026)

Runs relances:
- `guadeloupe-complete-analysis.json` (avant: 6 mars 2026, apres: 19 mars 2026),
- `martinique-complete-analysis.json` (avant: 6 mars 2026, apres: 19 mars 2026).

Constat backend:
- moteur avant/apres: `climada_with_interdependency_v1` (identique),
- courbe d'impact avant: `Eberenz_2021_TC`,
- courbe d'impact apres: `sib_tc_multicurve_v1`,
- points d'exposition inchanges (meme maillage): Guadeloupe `329 087`, Martinique `403 040`.

Comparatif portefeuille:

| Territoire | Indicateur | Avant | Apres | Delta | Delta % |
|---|---|---:|---:|---:|---:|
| Guadeloupe | Exposition totale (EUR) | 6 897 242 082.83 | 10 724 270 292.36 | +3 827 028 209.53 | +55.49% |
| Guadeloupe | EAI STORM (EUR) | 173 053 024.90 | 45 658 339.84 | -127 394 685.06 | -73.62% |
| Guadeloupe | EAI STORM_CMCC (EUR) | 168 786 513.42 | 45 000 203.36 | -123 786 310.06 | -73.34% |
| Guadeloupe | PML100 STORM (EUR) | 3 105 623 211.08 | 652 391 930.03 | -2 453 231 281.05 | -78.99% |
| Guadeloupe | PML100 STORM_CMCC (EUR) | 3 178 330 265.72 | 666 187 625.37 | -2 512 142 640.35 | -79.04% |
| Martinique | Exposition totale (EUR) | 6 920 334 413.21 | 9 700 592 279.76 | +2 780 257 866.55 | +40.18% |
| Martinique | EAI STORM (EUR) | 183 234 379.13 | 62 421 784.11 | -120 812 595.02 | -65.93% |
| Martinique | EAI STORM_CMCC (EUR) | 158 602 734.52 | 57 548 784.82 | -101 053 949.70 | -63.72% |
| Martinique | PML100 STORM (EUR) | 3 370 891 097.00 | 822 440 899.41 | -2 548 450 197.59 | -75.60% |
| Martinique | PML100 STORM_CMCC (EUR) | 3 047 373 432.97 | 763 538 222.03 | -2 283 835 210.94 | -74.94% |

Verification page Donnee utilisateur (`/api/v1/runs`):
- run test: `jr_20260318_000313_aeb0e3`,
- `meta.engine = climada_with_interdependency_v1`,
- `meta.impact_function = sib_tc_multicurve_v1`,
- `meta.modeling.impact_function_profile = sib_tc_multicurve_v1`.

---

### 6.7 Extension multi-aleas cycloniques (mise a jour du 20 mars 2026)

#### 6.7.1 Perimetre V1 implemente
Le moteur CLIMADA backend conserve les deux scenarios historiques:
- `storm`
- `storm_cmcc`

Chaque scenario peut maintenant agreger jusqu'a trois composantes d'alea direct:
- `wind` (TropCyclone, existant)
- `rain` (TCRain, modele `R-CLIPER`)
- `surge` (TCSurgeBathtub)

Le contrat top-level reste compatible (`storm` / `storm_cmcc` inchanges) et des champs additifs ont ete ajoutes pour la decomposition des composantes.

#### 6.7.2 Source de donnees TC et generation des composantes
Objectif retenu: generer pluie et submersion a partir des memes donnees cycloniques que le vent (STORM/STORM_CMCC).

Implementation:
1. si possible, construction dynamique des hazards a partir des datasets parquet STORM/STORM_CMCC,
2. generation du vent par `TropCyclone.from_tracks(...)`,
3. generation de la pluie par `TCRain.from_tracks(..., model="R-CLIPER")`,
4. generation de la submersion par `TCSurgeBathtub.from_tc_winds(wind_hazard, topo_path)`.

#### 6.7.2 bis Topographie de submersion et priorite Copernicus
Le backend ne pointe plus en priorite vers un unique raster historique pour la submersion. La resolution effective du `topo_path` est centralisee dans `backend/app/config.py::resolve_surge_topo_path_for_territory(...)` et suit l'ordre suivant:
1. override explicite par territoire via `SIB_RISK_HAZARD_SURGE_TOPO_PATH_GUADELOUPE`, `..._MARTINIQUE` ou `..._SAINT_BARTHELEMY`;
2. DEM Copernicus GLO-30 par defaut:
   - `/home/ubuntu/uploads/DEM_Topo/Topo/Copernicus GLO-30 Digital Elevation Model/Guadeloupe_COP30.tif`
   - `/home/ubuntu/uploads/DEM_Topo/Topo/Copernicus GLO-30 Digital Elevation Model/Martinique_COP30.tif`
   - `/home/ubuntu/uploads/DEM_Topo/Topo/Copernicus GLO-30 Digital Elevation Model/SaintBarthelemy_COP30.tif`
3. anciens rasters legacy par territoire (`Guadeloupe.tif`, `Martinique.tif`) si les Copernicus ne sont pas disponibles;
4. chemin generique `hazard_surge_topo_path` en dernier recours.

Implication operationnelle:
- les runs complets et les reconstructions frontend Guadeloupe/Martinique utilisent donc par defaut les nouveaux DEM Copernicus GLO-30 des qu'ils existent sur le poste;
- Saint-Barthélemy suit la meme logique, avec `SaintBarthelemy_COP30.tif` comme cible prioritaire;
- `scripts/build_guadeloupe_complete_analysis.py`, `scripts/build_guadeloupe_wind_maps.py` et `scripts/rerun_case_studies_light.py` propagent ensuite ce chemin resolu vers la chaine `TCSurgeBathtub`;
- si un override par territoire est fourni, il remplace explicitement le choix Copernicus sans fallback silencieux vers un autre raster.

Important:
- la composante pluie necessite les tracks dynamiques;
- la production scientifique n'autorise plus de fallback HDF5 pre-calcule pour contourner cette contrainte;
- la submersion bathtub peut rester calculable via l'aléa vent + DEM.
- dans la chaine dynamique STORM/STORM_CMCC, les vents soutenus sont convertis de la convention moyenne 10 minutes vers l'equivalent 1 minute via le facteur `1 / 0.88`, afin d'aligner l'aléa vent sur la convention attendue par CLIMADA et par la courbe Eberenz.

En langage naturel, la chaine backend est la suivante:
- on part des points d'exposition effectivement echantillonnes par CLIMADA;
- on recupere uniquement les tracks STORM/STORM_CMCC utiles autour de ces points;
- ces tracks servent d'abord a produire un aléa vent `TropCyclone`;
- a partir de ce meme socle, on derive:
  - un champ de pluie `TCRain`,
  - une submersion cotiere `TCSurgeBathtub`.

Autrement dit, pluie et submersion ne sont pas lues depuis une source exogene independante: elles sont calculees a partir des memes cyclones synthetiques STORM que le vent.

Extrait du chargement dynamique STORM -> tracks -> vent:

```python
centroids = _build_centroids_from_points(coords)
tracks_storm = _get_or_build_tracks(...)
tracks_cmcc = _get_or_build_tracks(...)

storm = _build_hazard_from_tracks(tracks_storm, centroids)
storm_cmcc = _build_hazard_from_tracks(tracks_cmcc, centroids)
```

Puis:

```python
return TropCyclone.from_tracks(
    tracks,
    centroids=centroids,
    ignore_distance_to_coast=True,
)
```

Implementation de reference:
- `backend/app/risk_engine/hazard_loader.py`

##### 6.7.2.1 Comment la pluie est calculee
La pluie n'est pas une simple recoloration de la carte de vent. Dans le backend, elle est derivee des tracks tropicaux eux-memes via `TCRain.from_tracks(...)`.

Extrait:

```python
rain_hazard = TCRain.from_tracks(
    tracks,
    centroids=wind_hazard.centroids,
    model=requested_rain_model,
    ignore_distance_to_coast=True,
    max_dist_inland_km=2000,
)
```

Interpretation:
- `tracks`: trajectoires STORM/STORM_CMCC deja filtrees sur la zone utile;
- `centroids=wind_hazard.centroids`: la pluie est calculee sur la meme maille spatiale que le vent;
- `model="R-CLIPER"`: on utilise le modele pluie retenu en V1;
- `ignore_distance_to_coast=True`: on ne coupe pas artificiellement la pluie au trait de cote;
- `max_dist_inland_km=2000`: on autorise une propagation inland suffisamment large pour les petites iles.

Limite acceptee pour le climat futur en V1:
- dans l'etat actuel, cette composante pluie futur derive surtout du signal porte par les tracks et par `R-CLIPER`;
- elle ne represente pas explicitement l'amplification thermodynamique de l'humidite atmospherique sous rechauffement;
- on conserve donc cette estimation comme **premiere approche de screening**, mais elle ne doit pas etre interpretee comme une modelisation pluie-climat futur de reference;
- pour une version ulterieure, il est recommande d'utiliser une modelisation pluie dediee au climat futur, distincte de cette approximation pilotee par les tracks.

Important pour l'interpretation:
- voir de la pluie sur la carte ne signifie pas automatiquement qu'il y aura des degats importants;
- les degats pluie dependent ensuite de la conversion `pluie -> hauteur proxy`, puis de la courbe profondeur-dommage de l'actif;
- avec des coefficients de ruissellement modestes, la composante pluie peut rester visible en aléa mais faible en dommage.

Lecture metier plus detaillee:
- `TCRain.from_tracks(...)` ne fait pas un modele hydraulique complet de ruissellement ou d'accumulation sur le terrain;
- il estime une intensite de pluie locale directement a partir du cyclone synthetique, de sa trajectoire et de ses caracteristiques;
- cette intensite est ensuite comparee a une courbe de vulnerabilite profondeur-dommage, mais sur un axe pluie-equivalent;
- l'intensite `TCRain` manipulee pour les cartes et la vulnerabilite correspond a un **cumul evenementiel en mm**, pas a un debit `mm/h`;
- le passage profondeur -> pluie proxy est realise via un **profil par classe d'infrastructure** (`RUNOFF_COEFF_BY_INFRA_CLASS`) mis a l'echelle par le facteur global `multi_hazard_rain_base_runoff_coeff` autour de la reference `0.25`;
- la table `RUNOFF_COEFF_BY_INFRA_CLASS` n'est plus seulement documentaire: elle est maintenant utilisee pour construire des courbes pluie distinctes selon la classe d'actif;
- il n'y a donc pas de "descente de crue" dynamique ni de routage hydrologique dans cette V1.

##### 6.7.2.2 Comment la submersion cotiere est calculee
La submersion cotiere n'est pas construite directement depuis les tracks. Elle est derivee du hazard vent deja calcule:

```python
surge_hazard = TCSurgeBathtub.from_tc_winds(wind_hazard, str(prepared_topo))
surge_hazard = _normalize_frequency_on_copy(surge_hazard, storm_years)
```

Interpretation:
- `wind_hazard`: champ de vent cyclonique calcule a partir des tracks STORM;
- `prepared_topo`: DEM/bathymetrie local(e), converti(e) au besoin en GeoTIFF temporaire EPSG:4326;
- `TCSurgeBathtub` superpose une elevation d'eau simplifiee sur la topographie locale.

Avant cela, le backend securise le DEM:

```python
prepared_topo = _prepare_topo_raster_with_crs(Path(surge_topo_path))
if prepared_topo != Path(surge_topo_path):
    notes.append(
        f"{hazard_key}: DEM had no CRS; converted to temporary EPSG:4326 GeoTIFF ({prepared_topo})."
    )
```

Cela garantit que `TCSurgeBathtub` travaille sur une topographie georeferencee coherentement.

##### 6.7.2.3 Difference entre couches cartographiques et calcul des dommages
Pour Guadeloupe/Martinique, les cartes page 1 / page 2 restent des couches de visualisation agregees sur une grille web, mais les trois composantes `wind / rain / surge` sont maintenant calculees sur la meme chaine native CLIMADA.

Le script dedie `scripts/build_guadeloupe_wind_maps.py` applique des choix distincts selon la composante:
- **vent**: generation native CLIMADA `tracks -> TropCyclone.from_tracks(...)` sur la grille reguliere de la bbox du territoire;
- **pluie**: generation native CLIMADA `tracks -> TCRain.from_tracks(...)` sur la meme grille reguliere, avec frequences renormalisees avant extraction des niveaux de retour et sortie en `mm` cumules par evenement;
- **submersion**: generation native CLIMADA `tracks -> TropCyclone -> TCSurgeBathtub` sur une **sous-grille reguliere plus fine** (`0.01°` en V1 finale), puis reaggregation vers la grille cartographique `0.02°`.

Extrait du script cartographique:

```python
full_grid_cells, target_cells = _build_grid_cells(
    territory_geom=territory_geom,
    lat_min=lat_min,
    lat_max=lat_max,
    lon_min=lon_min,
    lon_max=lon_max,
    cell_deg=args.cell_deg,
)
ordered_point_coords = [
    (float(cell_info["grid_lat"]), float(cell_info["grid_lon"]))
    for _, cell_info in sorted(full_grid_cells.items())
]
native_rain_components, native_rain_meta = _build_native_rain_maps(
    point_coords=ordered_point_coords,
    dynamic_max_tracks=dynamic_max_tracks,
)
native_surge_components, native_surge_meta = _build_native_surge_maps(
    lat_min=lat_min,
    lat_max=lat_max,
    lon_min=lon_min,
    lon_max=lon_max,
    output_cell_deg=args.cell_deg,
    surge_native_cell_deg=float(args.surge_native_cell_deg),
    target_cells=target_cells,
    topo_path=topo_path,
    dynamic_max_tracks=dynamic_max_tracks,
)
```

La sous-grille fine de submersion sert a capturer les franges littorales basses que des centres de mailles `0.05°` rataient souvent. Dans la fonction de submersion:

```python
surge_hazard = TCSurgeBathtub.from_tc_winds(wind_hazard, str(prepared_topo))
surge_stats = _summarize_hazard_by_coord(surge_hazard)
out[hazard_key] = _aggregate_subgrid_stats_to_target_cells(
    subgrid_stats=surge_stats,
    target_cells=target_cells,
    lat_min=lat_min,
    lon_min=lon_min,
    output_cell_deg=output_cell_deg,
)
```

Le choix de l'aggregation par `max` sur les sous-mailles n'est **pas** une deviation du calcul CLIMADA de la submersion elle-meme:
- la hauteur d'eau est bien calculee par `TCSurgeBathtub` sur chaque sous-maille;
- seul le passage de la sous-grille fine vers la maille d'affichage web `0.05°` fait une reduction cartographique.

Le clipping territorial ne repose plus sur le bord de la bbox ni uniquement sur le DEM. La carte utilise en priorite le masque administratif fourni dans:
- `/home/ubuntu/uploads/DEM_Topo/Limites Pays/geoBoundariesCGAZ_ADM0.geojson`

Le script y selectionne la geometrie `shapeGroup = FRA` qui intersecte la bbox du territoire, puis conserve uniquement les cellules de carte qui intersectent cette emprise. Pour l'affichage, chaque cellule est ancree sur le `representative_point()` de sa partie terrestre, ce qui evite de placer les marqueurs de submersion au large alors que la cellule est bien cotiere.

Le dommage est calcule dans le backend avec la chaine complete:

```text
tracks STORM -> TropCyclone / TCRain / TCSurgeBathtub
             -> intensite par centroides CLIMADA
             -> courbes de vulnerabilite
             -> dommage direct
             -> propagation indirecte elec -> eau
```

Depuis la correction du 24 mars 2026, la carte de submersion des cas d'etude:
- n'utilise plus la distance au bord de la bbox,
- n'utilise plus le proxy de distance-cote maison,
- s'appuie sur `TCSurgeBathtub` de bout en bout,
- n'affiche que les cellules qui intersectent effectivement le territoire cible.

##### 6.7.2.4 Comment les vitesses de vent pour `rp50`, `rp100` et `event_max` sont selectionnees
La logique vent est construite cellule par cellule, a partir du catalogue synthetique des tracks STORM / STORM_CMCC.

Pour une cellule `i`:
1. on collecte toutes les intensites `wind_max` qui tombent dans cette cellule sur l'ensemble du catalogue;
2. on regroupe ensuite par annee synthetique et on conserve, pour chaque annee, le maximum de vent de la cellule;
3. on obtient ainsi une serie annuelle de maxima `annual_series_i`;
4. `rp50_wind_mps(i)` est calcule comme le quantile 98% de cette serie;
5. `rp100_wind_mps(i)` est calcule comme le quantile 99% de cette serie;
6. `event_max_wind_mps(i)` est le maximum de cette serie annuelle.

Pseudo-code simplifie:

```python
annual_series_i = max_wind_per_year_for_cell(i)
rp50 = np.quantile(annual_series_i, 0.98)
rp100 = np.quantile(annual_series_i, 0.99)
event_max = np.max(annual_series_i)
```

Deux consequences importantes:
- `mean_wind_mps` et les niveaux de retour ne viennent pas du meme estimateur statistique;
- au niveau d'une zone, les tableaux affichent ensuite une moyenne spatiale de cellules, donc l'interpretation doit toujours se faire avec l'agregation en tete.

##### 6.7.2.5 Comment "evenement le plus fort" est calcule pour le vent (par maille)
La logique "event_max" vent est calculee **par maille**.

Pour une maille `i`:
- on prend la serie des maxima annuels de vent pour cette maille (issue des tracks STORM/STORM_CMCC),
- puis `event_max_wind_mps(i) = max(serie_annuelle_i)`.

Ensuite, les tableaux front peuvent afficher deux indicateurs differents:
- `Vent - Evenement le plus fort`: **moyenne spatiale** des `event_max_wind_mps(i)` sur toutes les mailles de la zone/bassin;
- `Vent - Maximum absolu`: **maximum spatial** des `event_max_wind_mps(i)` sur la zone/bassin.

Consequences d'interpretation:
- il est possible que la moyenne "evenement le plus fort" d'une petite zone (ex. Guadeloupe) soit superieure a la moyenne d'un grand bassin (NA), car la moyenne du grand bassin inclut beaucoup de mailles faiblement exposees;
- en revanche, le "maximum absolu" du bassin complet reste generalement plus eleve que celui d'une sous-zone locale.

#### 6.7.3 Choix Bathtub vs GeoClaw
Choix acté pour V1 production:
- **Bathtub (TCSurgeBathtub)**

Raison:
- cout de calcul nettement plus faible,
- deploiement plus simple dans le backend existant,
- compatible avec un usage "screening" Guadeloupe/Martinique.

GeoClaw est garde pour un futur benchmark localise (zones cotières critiques), mais non active en V1 API.

#### 6.7.4 DEM et donnees topo/bathymetrie
DEM V1 configure:
- `/home/ubuntu/uploads/DEM_Topo/MNT_FACADE_ANTS_HOMONIM_PBMA/DONNEES/MNT_ANTS100m_HOMONIM_WGS84_PBMA_ZNEG.asc`

Ce DEM est suffisant pour la V1 Guadeloupe/Martinique.
Si le raster source ne contient pas de CRS (cas possible des `.asc`), le backend convertit automatiquement vers un GeoTIFF temporaire EPSG:4326 avant calcul bathtub.
Le fichier Guyane volumineux (>4GB) n'est pas requis pour ce perimetre V1.

#### 6.7.5 Courbes inondation/proxy pluie
Le tableau de reference consolide des courbes de vulnerabilite (vent + pluie/submersion) est maintenant centralise en **section 4.3**.

Source depth:
- `/home/ubuntu/uploads/Vulnerability/Table_D2_Hazard_Fragility_and_Vulnerability_Curves_V1.1.0.xlsx` (feuille `F_Vuln_Depth`)
- implementation: `backend/app/risk_engine/impact_functions_multi_hazard.py`

Dans le code courant, la pluie-proxy est construite en deux etapes:
1. on part de la courbe profondeur-dommage `Fxx.x` de la table D2;
2. on projette son axe profondeur `depth_m` vers un axe pluie equivalente `mm_proxy` avec un coefficient de ruissellement dependant de la classe d'infrastructure.

Concretement, dans `backend/app/risk_engine/impact_functions_multi_hazard.py`:

```python
runoff_coeff = class_coeff * (base_coeff / 0.25)
rain_intensity_mm = (curve["depth_m"] * 1000.0) / runoff_coeff
```

Lecture naturelle:
- la courbe d'origine dit "si l'eau atteint telle profondeur, le dommage est tel";
- le backend reconstruit une courbe equivalente "si la pluie proxy cumulee par evenement atteint telle intensite, le dommage est tel";
- on ne repasse donc pas une deuxieme fois la meme conversion pendant le calcul des dommages.

Le parametre de sensibilite `multi_hazard_rain_base_runoff_coeff` reste actif, mais il agit maintenant comme **facteur global de mise a l'echelle** du profil par classe autour de la baseline `0.25`. A la baseline, on retrouve donc les coefficients experts (`0.10`, `0.30`, `0.25`, `0.35`, `0.20` selon la classe), et les scenarios de sensibilite `0.1` / `0.5` dilatent ou contractent ce profil complet.

Cette conversion permet d'utiliser le meme socle `F_Vuln_Depth` pour:
- la submersion cotiere (`m`),
- la pluie proxy (`mm_proxy`).

Important:
- `TCRain.from_tracks(...)` fournit ici un **cumul de pluie par evenement en mm** au niveau du centroid;
- la conversion `depth -> pluie proxy` sert seulement a brancher cette intensite sur les courbes de vulnerabilite;
- il ne s'agit pas d'un modele hydrologique de crue, de stockage ou de redescente du niveau d'eau.

#### 6.7.5 bis Mouvements de terrain probabilistes
Les rasters landslide fournis dans `/home/ubuntu/uploads/Landslide` sont des sorties de modele probabiliste, pas des evenements historiques observes. Ils codent une classe ordinale d'aléa:
- `0` et `1` = probabilite nulle de mouvement de terrain,
- `2`, `3`, `4` et `5` = probabilites croissantes.

Pour la V1 SIB, le mapping de dommage retenu est:
- `0/1 -> 0%`,
- `2 -> 25%`,
- `3 -> 50%`,
- `4 -> 75%`,
- `5 -> 100%`.

Le branchement backend natif s'appuie sur CLIMADA Petals `Landslide.from_prob` dans un sous-ensemble spatial restreint autour de l'exposition pour garder les tests rapides.

Scenarios actifs:
- `LS_GuaMar_Precipitation_ClimatActuel` -> `STORM`,
- `LS_GuaMar_Precipitation_ClimatSSP585` -> `STORM_CMCC`,
- `LS_GuaMar_Eathquake` -> `STORM` et `STORM_CMCC` sans sensibilité climat.

La version actuelle n'active que la Guadeloupe et la Martinique. Les rasters Reunion sont prets pour plus tard mais restent hors perimetre.

Choix de courbe de vulnerabilite:
- la courbe de reference est l'**hypothèse 5 paliers**;
- la courbe de comparaison est la **proxy D2**, exposee depuis la feuille `L_Categorical` du classeur `Table_D2_Hazard_Fragility_and_Vulnerability_Curves_V1.1.0.xlsx`;
- les feuilles `E_*` du classeur restent un fallback documentaire possible, mais elles ne sont pas utilisees par defaut dans la V1.

L'API backend expose ces courbes via:
- `GET /api/v1/vulnerability/curves?hazard_component=landslide`

Sur l'interface:
- la page 5 affiche un sous-bloc dedie aux mouvements de terrain;
- le repertoire des courbes de vulnerabilite reste separe du bloc vent / submersion / pluie;
- la page 3 publique reste inchangée et ne charge pas landslide.

#### 6.7.6 Regle d'agregation multi-aleas directe
La combinaison directe appliquee est additive avec plafond par point. Le plafonnement est applique avant la classification d'etat et avant l'agregation des tableaux:

```text
EAI_direct_total(point) = min(value_point,
                              EAI_wind(point) + EAI_rain(point) + EAI_surge(point) + EAI_landslide(point))

MaxLoss_total(point) = min(value_point,
                           MaxLoss_wind(point) + MaxLoss_rain(point) + MaxLoss_surge(point) + MaxLoss_landslide(point))
```

Puis la propagation elec -> eau (indirect) s'applique sur ce direct total, sans rupture de schema des sorties historiques.

#### 6.7.7 Sorties JSON ajoutees (additives)
Dans `portfolio_results.storm` et `portfolio_results.storm_cmcc`:
- `components_direct_eai_eur`
- `components_direct_percentile_99_loss_eur`

Dans `meta`:
- `hazard_components` (liste des composantes actives)

Dans `meta.modeling`:
- `multi_hazard_enabled_requested`
- `multi_hazard_enabled_effective`
- `multi_hazard_components_by_hazard`
- `multi_hazard_rain_model`
- `multi_hazard_surge_topo_path`
- `multi_hazard_flood_curve_file`

Dans le proxy multi-aleas (`web/data/*-multi-hazard-proxy.json`):
- `landslide_sources`

Dans le meta racine des JSON page 1 / page 2:
- `hazard_components = ["wind", "rain", "surge", "landslide"]`

Dans les JSON page 1 / page 2 (`web/data/*-page*-analysis.json`):
- `impact.component_order = ["wind", "rain", "surge", "landslide"]`
- `impact.state_damage_tables[*].storm.damage_components_eur`
- `impact.state_damage_tables[*].storm_cmcc.damage_components_eur`
- `impact.damage_breakdown_by_scenario[*].storm[*].damage_components_eur`
- `impact.damage_breakdown_by_scenario[*].storm_cmcc[*].damage_components_eur`

#### 6.7.8 Choix UI actes
Pour la page Guadeloupe/Martinique:
- les cartes sont renommees `Cartes des aleas`
- les deux cartes `STORM` / `STORM_CMCC` sont conservees
- un seul aléa est selectionnable a la fois (`Storm (vent)`, `Pluie`, `Inondations cotieres`)
- les deux graphes de comparaison sous la carte sont dynamiques selon l'aléa selectionne (titres + axes + unites)
- le bloc impact utilise un seul tableau pilote par menu deroulant (`annual`, `rp50`, `rp100`, `event_max`)
- les tableaux page 1 / page 2 affichent maintenant les dommages landslide en colonne dédiée
- les graphes de degats sont regroupes en vues generales eau/electricite par scenario

Pour la page 5:
- les cartes de courbes sont organisees par infrastructure
- chaque infrastructure affiche 3 mini-graphes (`vent`, `submersion cotiere`, `pluie`)
- un sous-bloc supplementaire affiche les courbes de mouvements de terrain, avec la reference `hypothèse 5 paliers` et la `proxy D2`
- l'endpoint backend supporte `GET /api/v1/vulnerability/curves?hazard_component=wind|rain|surge|landslide`

#### 6.7.9 Variables runtime ajoutees
- `SIB_RISK_MULTI_HAZARD_ENABLED`
- `SIB_RISK_HAZARD_RAIN_MODEL`
- `SIB_RISK_HAZARD_SURGE_TOPO_PATH`
- `SIB_RISK_HAZARD_SURGE_TOPO_PATH_GUADELOUPE`
- `SIB_RISK_HAZARD_SURGE_TOPO_PATH_MARTINIQUE`
- `SIB_RISK_D2_FLOOD_CURVE_FILE`
- `SIB_RISK_LANDSLIDE_ROOT`
- `SIB_RISK_LANDSLIDE_PRECIP_CURRENT_PATH`
- `SIB_RISK_LANDSLIDE_PRECIP_SSP585_PATH`
- `SIB_RISK_LANDSLIDE_EARTHQUAKE_PATH`
- `SIB_RISK_LANDSLIDE_CORR_FACT`
- `SIB_RISK_LANDSLIDE_N_YEARS`
- `SIB_RISK_LANDSLIDE_DIST`

#### 6.7.10 Lien avec evolutions futures (glissements / inondations pluviales)
Le modele pluie (`TCRain`) est conserve comme socle commun pour:
- futurs modeles de mouvements de terrain,
- futurs modeles d'inondation pluviale plus physiques.

La V1 actuelle fournit donc une base operationnelle multi-aleas tout en preservant la compatibilite des sorties API existantes.

#### 6.7.11 Strategie de rerun legere pour Guadeloupe / Martinique
Pour finaliser les cas d'etude sans relancer un pipeline multi-aleas complet trop couteux sur toutes les geometries, la strategie retenue est la suivante:
- generation des cartes d'aleas (`wind`, `rain`, `surge`) par script dedie,
- generation d'un proxy multi-aleas echantillonne par territoire (`web/data/*-multi-hazard-proxy.json`),
- regeneration des JSON page 1 / page 2 a partir:
  - du calcul vent complet,
  - d'un multiplicateur global multi-aleas par scenario,
  - d'une decomposition par composante (`wind` / `rain` / `surge`) issue du proxy,
  - d'un reequilibrage des classes de dommages qui preserve la structure vent du scenario courant et y injecte la part non-vent du proxy.

Cette strategie est implementee dans:
- `scripts/build_case_study_multi_hazard_proxy.py`
- `scripts/rerun_case_studies_light.py`

Pour la partie cartes d'aleas, le rerun leger fixe explicitement:
- `--map-dynamic-max-tracks 300`
- `--map-cell-deg 0.02`
- `--map-surge-native-cell-deg 0.01`

Pour la partie proxy multi-aleas, la V1 finale retient:
- `--proxy-dynamic-max-tracks 100` (valeur par defaut de `scripts/rerun_case_studies_light.py` au 26 mars 2026)

Interpretation pratique:
- le bloc cartes est plus exigeant spatialement et conserve `300` tracks pour stabiliser les champs cartographiques (`wind/rain/surge`);
- le bloc proxy est echantillonne sur un sous-ensemble de points d'exposition et utilise `100` tracks par defaut pour garder un rerun leger robuste en cout CPU/RAM.
- un override manuel reste possible (`--proxy-dynamic-max-tracks N`) pour une campagne plus lourde.

Les sorties visibles page 1 / page 2 et page 3 sont volontairement limitees a:
- `annual`
- `rp50`
- `rp100`
- `event_max`

Le scenario `rp1000` n'est plus expose dans les cartes et tableaux du front.
Le calcul public de la page 3 reste volontairement limite a `wind`, `rain` et `surge`:
le bloc landslide n'y est pas active faute de couverture complete sur toute l'emprise STORM.

Objectif:
- garder une chaine native CLIMADA pour `TropCyclone`, `TCRain` et `TCSurgeBathtub`,
- conserver un cout calculatoire raisonnable pour Guadeloupe/Martinique,
- capter les cellules littorales basses dans la carte de submersion sans basculer vers un modele externe.

Objectif:
- obtenir des reruns Guadeloupe / Martinique robustes et repetables,
- conserver des sorties front coherentes (cartes, tableaux, barres empilees, etats reseaux),
- reserver le calcul multi-aleas complet a l'API backend page 3 pour les donnees utilisateur.

#### 6.7.12 Mecanisme de coherence inter-artefacts (`case_study_run_id`)
Le rerun leger impose une coherence stricte entre:
- `web/data/{territory}-wind-maps.json`
- `web/data/{territory}-multi-hazard-proxy.json`
- `web/data/{territory}-page1-analysis.json` (ou `page2` pour Martinique, `page7` pour Saint-Barthélemy)

Principe:
1. `scripts/rerun_case_studies_light.py` genere un `run_id` unique (`{territory}_case_YYYYMMDDTHHMMSSZ`).
2. Le meme `run_id` est passe a chaque script via `--case-study-run-id`.
3. Chaque artefact ecrit `meta.case_study_run_id`.
4. Le rerun verifie ensuite l'alignement des trois artefacts (`_assert_case_study_coherence`) et echoue si mismatch.

Effet:
- les tableaux/cartes/graphs affiches proviennent obligatoirement du meme lot de calcul.
- on evite les incoherences de type \"cartes d'un run + tableaux d'un run precedent\".

#### 6.7.12 bis Traceabilite de publication (`meta.publication_trace`)
Les deux artefacts web les plus sensibles aux fallbacks de publication exposent maintenant un bloc structure `meta.publication_trace`:
- `web/data/{territory}-multi-hazard-proxy.json`
- `web/data/{territory}-page1-analysis.json` / `page2-analysis.json` / `page7-analysis.json`

Ce bloc ne change pas la physique du calcul. Il sert a documenter la provenance de publication et contient au minimum:
- `artifact_kind`
- `source_mode`
- `fallback_active`
- `fallback_reason`
- les run ids / timestamps amont utiles (`complete_analysis_*`, `wind_map_*`, `multi_hazard_proxy_*` selon l'artefact)

Interpretation:
- `source_mode=lightweight_sampled_climada_proxy` signifie que le proxy multi-aleas provient du rerun leger natif.
- `source_mode=complete_analysis_component_ratios` signifie que le proxy multi-aleas a ete synthetise depuis le `complete-analysis.json`.
- `source_mode=case_study_page_analysis` signifie que la page-analysis provient du rerun leger natif.
- `source_mode=complete_analysis_asset_fallback` signifie que la page-analysis / les etats reseaux ont ete reconstruits depuis les `asset_results` du `complete-analysis.json`.

Controle associe:
- `scripts/run_web_artifacts.py` exige maintenant ce bloc sur `multi-hazard-proxy` et `page-analysis` au moment du snapshot archive.
- le snapshot verifie aussi la coherence proxy <-> page-analysis (etat fallback et `source_mode` amont), puis resume le resultat sous `archived_frontend_validation.publication_trace` dans le manifest du run.
- le frontend web surfacera ce resume dans le badge `Trace:` de l'en-tete, pour ne pas obliger l'operateur a relire les JSON bruts.

#### 6.7.12 ter Visualisation de la maille web
Les cartes d'aleas `page1` / `page2` utilisent deja `meta.grid_cell_deg` et la bbox de publication pour reconstruire la grille Leaflet.
Le toggle `Afficher le quadrillage des cartes` ne modifie pas les valeurs des cellules:
- il ajoute seulement une couche vectorielle de quadrillage au-dessus des rectangles d'alea,
- il reutilise la meme maille que les cellules publiees (`0.02 deg` pour Guadeloupe/Martinique dans le profil courant),
- il sert a auditer visuellement la resolution de publication et a expliciter que la carte est une restitution par mailles, pas un champ continu.

#### 6.7.12 quater Publication scientifique canonique du site web
Depuis le lot de bascule web scientifique, le site publie un payload intermediaire dedie:
- `web/data/{territory}-scientific-web-summary.json`

Ce payload est derive exclusivement du:
- `web/data/{territory}-complete-analysis.json`

Objectif:
- separer strictement les chiffres scientifiques publies des artefacts visuels legers,
- garder un contrat frontend stable,
- eviter que `app.js` recalcule ou recompose des chiffres monetaires / sociaux a partir du proxy leger.

Artefacts toujours presents cote web:
- `*-complete-analysis.json`: source scientifique canonique complete du run publie
- `*-scientific-web-summary.json`: projection web scientifique stable, derivee du `complete-analysis`
- `*-wind-maps.json`, `*-landslide-maps.json`, `*-multi-hazard-proxy.json`: artefacts visuels/cartographiques
- `*-page*-analysis.json`: artefact legacy de page, encore utilise pour certains blocs non totalement rebases
- `*-network-states.geojson`, `*-water-infra.geojson`: couches cartographiques

Sections des pages etude de cas deja cablees sur la chaine scientifique (`complete-analysis` -> `scientific-web-summary`):
- tableau d'impacts portefeuille / pertes monetaires dans le bloc impact:
  - totaux `annual`, `rp50`, `rp100`, `p99`
- tableau de conclusion monetaire:
  - totaux `annual`, `rp50`, `rp100`, `p99`
- tableaux / graphiques sociaux quand la donnee scientifique est disponible dans le contrat courant
- camemberts d'etats reseaux quand la donnee scientifique est disponible dans le contrat courant
- meta de tracabilite du run web scientifique:
  - `run_id`
  - `scientific_source=true`
  - `schema_version`

Dans l'etat actuel du contrat scientifique web (`scientific_web_summary_v1`), les disponibilites sont les suivantes:
- monetaire portefeuille:
  - `annual`, `rp50`, `rp100`, `p99` publies scientifiquement
- tableaux monetaires par classe reseau:
  - `annual` publie scientifiquement
  - `rp50`, `rp100`, `p99` non encore publies scientifiquement par classe
- impacts sociaux:
  - `p99` / worst-case publie scientifiquement
  - `annual`, `rp50`, `rp100` non encore exposes scientifiquement dans le payload web
- etats reseaux:
  - `p99` / worst-case publie scientifiquement
  - `annual`, `rp50`, `rp100` non encore exposes scientifiquement dans le payload web

Sections qui ne sont pas encore totalement cablees sur le `complete-analysis` publie et restent sur la chaine visuelle / legacy:
- tableau `Comparaison aleas`:
  - source `wind-maps.json` / `landslide-maps.json`
  - il reste un indicateur cartographique, pas un resultat portefeuille
- cartes d'aleas:
  - source `wind-maps.json` / `landslide-maps.json`
- cartes d'infrastructures d'eau et d'electricite:
  - source `water-infra.geojson`
- carte d'etat des reseaux:
  - source `network-states.geojson`
- blocs intro / etude de cas de la page d'accueil:
  - ils reposent encore principalement sur `page-analysis` et sur les couches cartographiques associees
- tableaux detail par classe pour `rp50`, `rp100`, `p99`:
  - faute d'un export scientifique par classe/scenario dans le contrat web actuel
- pie charts d'etats reseaux et tableaux sociaux pour `annual`, `rp50`, `rp100`:
  - faute d'un export scientifique scenario-par-scenario dans le contrat web actuel

Consequence pratique:
- un chiffre affiche comme perte portefeuille globale est maintenant attendu depuis la chaine scientifique.
- un chiffre affiche comme intensite d'aléa physique ou comme restitution cartographique peut encore venir des artefacts visuels.
- tant que le `complete-analysis` n'exporte pas davantage de detail par classe/scenario, certaines vues detaillees doivent rester partielles ou legacy.

Validation de publication:
- `scripts/run_web_artifacts.py` valide maintenant aussi l'alignement strict entre:
  - `complete-analysis`
  - `scientific-web-summary`
- les totaux `annual`, `rp50`, `rp100`, `p99` du payload web scientifique doivent correspondre exactement aux champs canoniques du `complete-analysis`.

#### 6.7.13 Contraintes operationnelles memoire/ressources et recommandations
Constats operationnels (runs Guadeloupe/Martinique):
- la generation native dynamique (`storm_ds`/`storm_ds_CMCC` -> tracks -> hazards) est le poste dominant en RAM/CPU.
- le cout augmente surtout avec:
  - `dynamic_max_tracks`,
  - densite spatiale (nombre de points / maille),
  - multi-aleas actifs (`wind + rain + surge`).

Garde-fous techniques actuels:
- cap tracks dynamique (`dynamic_max_tracks`) par etape.
- cache tracks backend borne via `SIB_RISK_TRACK_CACHE_MAX_ENTRIES` (defaut `8`, `0` pour desactiver le cache).
- caps de sampling exposition (`SIB_RISK_CLIMADA_MAX_POINTS_PER_FEATURE`, options proxy `max-points-*`).

Recommandations d'execution:
- pour operation courante front: conserver les defauts du rerun leger (`map=300`, `proxy=100`).
- pour debug memoire: diminuer temporairement `dynamic_max_tracks` ou fixer `SIB_RISK_TRACK_CACHE_MAX_ENTRIES=0`.
- pour campagnes de recalcul lourdes: executer territoire par territoire et verifier l'alignement `case_study_run_id` apres chaque lot.
