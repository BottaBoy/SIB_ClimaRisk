# Note - analyse de sensibilite

## Objet

Cette note recense les hypotheses, parametres et conventions presentes dans la chaine calculatoire de `sib-work` qui peuvent faire l'objet d'une analyse de sensibilite.

Le tableau final utilise les 4 familles suivantes:

1. `Physique alea`
   Ce bloc couvre la generation des aleas cycloniques eux-memes: vent, pluie, submersion, choix du modele pluie, DEM, etc.
2. `Vulnerabilite`
   Ce bloc couvre les courbes de vulnerabilite, leur parametrage et leur affectation aux differentes classes d'actifs.
3. `Systeme / interdependency`
   Ce bloc couvre la transformation des dommages directs en etats reseau, la sante des composants, la propagation elec -> eau, ainsi que les choix economiques avals qui pilotent l'impact systeme.
4. `Numerique / proxy / publication`
   Ce bloc couvre les reglages numeriques, les caps de sampling, les choix proxy des cas d'etude front et les conventions de publication qui ne relevent pas directement de la physique du modele.

Pour la lecture du tableau:

- `priorite` indique l'interet a inclure le parametre dans une premiere campagne de sensibilite.
- `robustesse` indique le niveau de confiance actuel dans l'hypothese ou le reglages (`Bonne`, `Moyenne`, `Faible`).

## 1. Exposition et desagregation

Les geometries sont echantillonnees en points en CRS metrique, puis reprojetees en WGS84. Le pas de sampling est `sampling_spacing_m` et il y a un cap `max_points_per_feature`. La valeur d'un actif est ensuite repartie uniformement entre les points echantillonnes. Voir `backend/app/risk_engine/exposure_to_climada.py:229`.

Les classes systeme sont inferees a partir de `exposure_category` et `asset_type`: `elec_aerien`, `elec_souterrain`, `eau_reseau`, `eau_ouvrage`, `habitation`. Voir `backend/app/risk_engine/exposure_to_climada.py:24`.

Les "territoires" utilises par la dependance ne sont pas des territoires administratifs, mais des mailles regulieres `0.2° x 0.2°` (`TERRITORY_GRID_DEG = 0.2`). Voir `backend/app/risk_engine/exposure_to_climada.py:11` et `backend/app/risk_engine/exposure_to_climada.py:50`.

## 2. Construction des aleas cyclone

Les hazards sont construits soit depuis des HDF5 pre-calcules, soit dynamiquement depuis `storm_ds` / `storm_ds_CMCC`. Le backend privilegie le mode dynamique. Voir `backend/app/config.py:50` et `backend/app/risk_engine/impact_runner.py:430`.

Les tracks sont filtres par bassin, par fenetre spatiale, puis eventuellement tronques a `dynamic_max_tracks`. Si trop de tracks restent, le code conserve les tracks les plus proches du centre de la fenetre. Voir `backend/app/risk_engine/hazard_loader.py:406`.

Les unites sont normalisees (`wind_unit_in`, `radius_unit_in`) et la pression environnementale est definie par `max(p_c + 5 hPa, env_pressure_hpa)`. Voir `backend/app/risk_engine/hazard_loader.py:424` et `backend/app/risk_engine/hazard_loader.py:455`.

Les frequences sont annualisees en divisant par `storm_years` (`10000` par defaut). Voir `backend/app/risk_engine/hazard_loader.py:103` et `backend/app/config.py:43`.

## 3. Alea vent

Le vent est construit via `TropCyclone.from_tracks(..., ignore_distance_to_coast=True)`. Voir `backend/app/risk_engine/hazard_loader.py:590`.

Le vent repose donc sur les tracks synthetiques STORM/STORM_CMCC, les choix d'unites, la pression environnementale reconstruite et la selection spatiale des tracks.

## 4. Alea pluie

La pluie est construite via `TCRain.from_tracks(..., model="R-CLIPER", ignore_distance_to_coast=True, max_dist_inland_km=2000)`. Voir `backend/app/risk_engine/climada_engine.py:544`.

La pluie est calculee sur les memes centroides que le vent, mais elle n'est pas convertie en un champ explicite de profondeur d'eau. L'intensite `TCRain.intensity` exploitee par le backend correspond a un **cumul evenementiel en mm**. Le dommage pluie passe ensuite par une courbe "pluie proxy" derivee des courbes profondeur-dommage. Voir `backend/app/risk_engine/impact_functions_multi_hazard.py`.

Le coefficient `runoff_coeff` n'est plus un scalaire unique: le backend applique maintenant un **profil par classe d'infrastructure** (`RUNOFF_COEFF_BY_INFRA_CLASS`) mis a l'echelle par le facteur global `multi_hazard_rain_base_runoff_coeff`. A la baseline, ce facteur global vaut `0.25` et restitue le profil expert par classe.

## 5. Alea submersion cotiere

La submersion est calculee via `TCSurgeBathtub.from_tc_winds(wind_hazard, DEM)`. Voir `backend/app/risk_engine/climada_engine.py:508`.

Il s'agit d'un modele de type `Bathtub`, donc d'une surcote simplifiee appuyee sur un DEM/topographie, et non d'un modele hydrodynamique complet.

Dans la chaine cartographique des cas d'etude, la submersion peut etre calculee sur une sous-grille plus fine, puis reagregee pour l'affichage. Voir `scripts/build_guadeloupe_wind_maps.py:820`.

## 6. Vulnerabilite vent

Les actifs sont relies a des courbes vent par `asset_type -> curve code`. Voir `backend/app/risk_engine/impact_functions.py:75`.

Une partie des actifs utilise des courbes D2, et `eau_eu_pr` conserve la courbe Eberenz. La courbe Eberenz est parametree par `v_thresh = 25.7` et `v_half = 59.6`. Voir `backend/app/risk_engine/impact_functions.py:15`.

Le mapping entre type d'actif et courbe appliquee est donc un choix methodologique structurant.

## 7. Vulnerabilite pluie et submersion

La submersion utilise directement les courbes D2 profondeur-dommage lues dans `F_Vuln_Depth`. Voir `backend/app/risk_engine/impact_functions_multi_hazard.py:82`.

La pluie utilise les memes courbes, mais transformees en `mm_proxy` a partir de la relation:

`equivalent_depth_m = runoff_coeff * rain_mm / 1000`

Le code implemente l'ecriture inverse:

`rain_mm = depth_m * 1000 / runoff_coeff`

afin de reconstruire des courbes `pluie proxy -> MDD`. Voir `backend/app/risk_engine/impact_functions_multi_hazard.py:213`.

Depuis le lot D, cette reconstruction se fait **par classe d'infrastructure**, et non plus avec un coefficient unique. La sensibilite `runoff_coeff` continue donc d'exister, mais comme facteur global qui dilate ou contracte tout le profil par classe.

Le mapping `asset_type -> flood curve` est defini ici: `backend/app/risk_engine/impact_functions_multi_hazard.py:16`.

## 8. Dommage direct

Les expositions sont affectees au centroid le plus proche, puis `ImpactCalc` calcule les dommages directs. Voir `backend/app/risk_engine/climada_engine.py:257`.

La combinaison multi-alea directe est additive, avec plafond a la valeur exposee du point:

`EAI_direct_total(point) = min(value_point, EAI_wind + EAI_rain + EAI_surge)`

Voir `backend/app/risk_engine/climada_engine.py:296`.

Point important: le `max_loss_by_point` utilise ensuite pour les etats reseau n'est pas extrait d'une distribution evenementielle complete par point, mais approxime par:

`max_loss_point(i) = eai_point(i) * (max_event_portfolio / sum_eai_points)`

Voir `backend/app/risk_engine/climada_engine.py:92`.

## 9. Systeme d'etats reseau

L'etat direct d'un point est calcule a partir du ratio:

`direct_ratio = direct_max_loss / value`

Les seuils actuels sont:

- `S0 -> S1 = 5%`
- `S1 -> S2 = 15%`
- `S2 -> S3 = 35%`

Voir `backend/app/risk_engine/interdependency.py:10` et `backend/app/risk_engine/interdependency.py:51`.

La sante d'un composant est ensuite calculee par:

`health = 1 - (0.3*L_S1 + 0.7*L_S2 + 1.0*L_S3) / L_total`

Voir `backend/app/risk_engine/interdependency.py:39`.

Dans le backend principal, `L_total`, `L_S1`, `L_S2` et `L_S3` sont ponderes par la valeur economique (`value_eur`) et non par les kilometres de reseau ou le niveau de service.

## 10. Transmission de defaillance elec -> eau

Toutes les classes eau sont aujourd'hui supposees dependantes de l'electricite. Voir `backend/app/risk_engine/interdependency.py:386`.

La sante electrique attribuee a un actif eau est resolue par la regle suivante:

- maille locale,
- sinon maille electrique la plus proche,
- sinon fallback global.

Voir `backend/app/risk_engine/interdependency.py:81`.

Cette sante est convertie en etat de dependance:

- `health < 0.75 -> S1`
- `health < 0.55 -> S2`
- `health < 0.35 -> S3`

Voir `backend/app/risk_engine/interdependency.py:61`.

L'indirect eau est ensuite calcule par:

`indirect_eai = direct_eai * uplift(state_dep)`

avec:

- `S0: 0%`
- `S1: 10%`
- `S2: 25%`
- `S3: 45%`

Voir `backend/app/risk_engine/interdependency.py:15` et `backend/app/risk_engine/interdependency.py:267`.

L'etat final eau est defini par `max(etat_direct, etat_dependance)`.

## 11. Agregats portefeuille

Apres propagation elec -> eau, le backend calcule un `dependency_scaler = EAI_total / EAI_direct`. Voir `backend/app/risk_engine/interdependency.py:378`.

Ce scaler est ensuite applique globalement a `max_event_loss`, `PML` et `TVaR` dans les sorties portefeuille. Voir `backend/app/risk_engine/impact_runner.py:503`.

Cela revient a approximer les indicateurs evenementiels indirects a partir d'un facteur derive de l'EAI.

## 12. Valorisation economique

Les valeurs reseau eau viennent du comparateur OFB par territoire. Voir `scripts/valuation_ofb.py:40`.

Les valeurs reseau electrique sont fixes par classe. Voir `scripts/valuation_ofb.py:70`.

Les ouvrages AEP ont des valeurs forfaitaires par type, avec une valeur par defaut `800000 EUR` si le type n'est pas reconnu. Voir `scripts/valuation_ofb.py:77`.

Ces valeurs agissent tres en aval, mais elles pilotent directement les pertes en euros et donc la priorisation des resultats.

## 13. Branche "cas d'etude front"

Les pages Guadeloupe/Martinique utilisent aussi un rerun leger qui n'est pas strictement la meme chaine que le backend API complet:

- `map-dynamic-max-tracks = 300`
- `proxy-dynamic-max-tracks = 100`
- `map-cell-deg = 0.02`
- `surge-native-cell-deg = 0.01`
- `proxy-spacing-m = 800`
- `proxy-max-points-total = 800`
- `proxy-max-points-per-feature = 8`

Voir `scripts/rerun_case_studies_light.py:63`.

Cette branche calcule des `component_ratios`, des `global_multipliers` et des `breakdown_shares`, puis les reutilise pour reallouer les pertes affichees dans les pages d'etude. Voir `scripts/build_guadeloupe_page1_data.py:930` et `scripts/build_guadeloupe_page1_data.py:1143`.

Ces parametres sont importants pour la publication web, mais ils ne doivent pas etre confondus avec les hypotheses scientifiques du moteur backend central.

## Tableau de sensibilite

| Categorie | parametre | valeur actuelle | role | priorite | robustesse | source | action recommandee |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Physique alea | `storm_env_pressure_hpa` | `1010.0 hPa` | plancher de pression environnementale pour reconstruire les tracks CLIMADA | Haute | Moyenne | `backend/app/config.py:54`; `backend/app/risk_engine/hazard_loader.py:339` | tester `1005/1010/1015` et mesurer l'effet sur vent et surge |
| Physique alea | marge `p_c + 5 hPa` | `+5 hPa` | evite une pression environnementale trop proche de la pression centrale | Haute | Faible | `backend/app/risk_engine/hazard_loader.py:455` | rendre la marge parametrique et expertiser sa justification |
| Physique alea | `hazard_rain_model` | `R-CLIPER` | modele pluie cyclonique applique aux tracks | Tres haute | Moyenne | `backend/app/config.py:58`; `backend/app/risk_engine/climada_engine.py:544` | comparer `R-CLIPER` et `TCR` |
| Physique alea | `max_dist_inland_km` | `2000 km` | extension inland du champ pluie | Moyenne | Moyenne | `backend/app/risk_engine/climada_engine.py:549` | tester `200/500/1000/2000` |
| Physique alea | `ignore_distance_to_coast` vent/pluie | `True` | ne coupe pas artificiellement l'alea au littoral | Moyenne | Moyenne | `backend/app/risk_engine/hazard_loader.py:598`; `backend/app/risk_engine/climada_engine.py:548` | tester `True/False` sur cas controles |
| Physique alea | source DEM/topo de surge | chemin configure courant | support spatial de la submersion | Tres haute | Faible | `backend/app/config.py:59`; `backend/app/risk_engine/climada_engine.py:503` | valider resolution, date, emprise et qualite du DEM |
| Physique alea | modele de submersion | `TCSurgeBathtub` | calcule une surcote simplifiee sur topographie | Tres haute | Faible | `backend/app/risk_engine/climada_engine.py:508` | conserver en screening V1 mais benchmarker contre un modele plus physique |
| Vulnerabilite | mapping `asset_type -> wind curve` | codes `W*` + `EBERENZ_2021_TC` | selection de la courbe vent par type d'actif | Tres haute | Moyenne | `backend/app/risk_engine/impact_functions.py:76` | revue expert rapide des correspondances |
| Vulnerabilite | `Eberenz.v_thresh` | `25.7 m/s` | seuil d'amorcage des dommages vent | Haute | Moyenne | `backend/app/risk_engine/impact_functions.py:15` | tester une plage litterature |
| Vulnerabilite | `Eberenz.v_half` | `59.6 m/s` | intensite de demi-dommage pour la courbe Eberenz | Haute | Moyenne | `backend/app/risk_engine/impact_functions.py:15` | tester une plage litterature |
| Vulnerabilite | mapping `asset_type -> flood curve` | codes `F*` | selection de la courbe pluie/submersion par type d'actif | Tres haute | Moyenne | `backend/app/risk_engine/impact_functions_multi_hazard.py:16` | revue expert rapide des affectations |
| Vulnerabilite | `runoff_coeff` | `0.25` unique | convertit la profondeur D2 en courbe pluie proxy en `mm_proxy` | Tres haute | Faible | `backend/app/risk_engine/impact_functions_multi_hazard.py:217` | sensibilite prioritaire et calage terrain |
| Vulnerabilite | transferabilite locale des courbes vent | hypothese implicite | suppose les courbes vent externes applicables au contexte local | Tres haute | Faible | `backend/app/risk_engine/impact_functions.py`; `docs/note-backend-calculatoire.md:117` | classer explicitement cette hypothese comme structurante |
| Vulnerabilite | transferabilite locale des courbes flood D2 | hypothese implicite | suppose les courbes profondeur-dommage applicables localement | Tres haute | Faible | `backend/app/risk_engine/impact_functions_multi_hazard.py:82` | revue expert + scenarios alternatifs |
| Systeme / interdependency | agregation multi-alea directe | `wind + rain + surge` avec cap | combine les dommages directs au point | Tres haute | Moyenne | `backend/app/risk_engine/climada_engine.py:296` | tester `additif`, `max`, et variantes prudentes |
| Systeme / interdependency | cap par point a la valeur exposee | `min(value_eur, ...)` | empeche une perte superieure a la valeur de l'actif | Haute | Bonne | `backend/app/risk_engine/climada_engine.py:322` | conserver comme garde-fou, seulement documenter |
| Systeme / interdependency | approximation `max_loss_by_point` | `eai_point * evt_max / sum_eai` | approxime le max loss par point pour les etats reseau | Tres haute | Faible | `backend/app/risk_engine/climada_engine.py:92` | priorite audit/correction |
| Systeme / interdependency | seuils d'etat directs | `5% / 15% / 35%` | convertit le ratio de dommage en `S0-S3` | Tres haute | Faible | `backend/app/risk_engine/interdependency.py:10` | expertiser rapidement |
| Systeme / interdependency | poids de sante `health` | `0.3 / 0.7 / 1.0` | convertit les masses en etat de sante systeme | Tres haute | Faible | `backend/app/risk_engine/interdependency.py:43` | tester des ponderations alternatives |
| Systeme / interdependency | base de ponderation `L_total` | `value_eur` | pese les etats par valeur economique et non par service ou longueur | Tres haute | Faible | `backend/app/risk_engine/interdependency.py:168`; `backend/app/risk_engine/interdependency.py:285` | comparer `valeur`, `km`, `service` |
| Systeme / interdependency | maille territoriale electrique | `0.2 deg` | support spatial local pour resoudre la sante elec | Haute | Faible | `backend/app/risk_engine/exposure_to_climada.py:11`; `backend/app/risk_engine/exposure_to_climada.py:50` | tester `0.05/0.1/0.2` |
| Systeme / interdependency | dependance eau -> elec | `all_water_assets_dependent = True` | suppose que tous les actifs eau dependent de l'electricite | Tres haute | Faible | `backend/app/risk_engine/interdependency.py:386` | requalifier en convention prudente ou affiner par type d'actif |
| Systeme / interdependency | regle de resolution sante elec | `local -> nearest -> global` | attribue une sante elec aux actifs eau | Haute | Faible | `backend/app/risk_engine/interdependency.py:81` | expertiser et ajouter un controle de distance max |
| Systeme / interdependency | seuils `health -> dependency_state` | `0.75 / 0.55 / 0.35` | convertit la sante elec en etat de dependance | Tres haute | Faible | `backend/app/risk_engine/interdependency.py:61` | expertiser rapidement |
| Systeme / interdependency | `uplift_by_state` | `0% / 10% / 25% / 45%` | calcule l'EAI indirect eau a partir de l'etat de dependance | Tres haute | Faible | `backend/app/risk_engine/interdependency.py:15`; `backend/app/risk_engine/interdependency.py:267` | priorite revue expert |
| Systeme / interdependency | regle d'etat final eau | `max(direct, dependency)` | fixe l'etat final eau apres dependance | Haute | Moyenne | `backend/app/risk_engine/interdependency.py:263` | tester des regles alternatives |
| Systeme / interdependency | `dependency_scaler` applique a `PML/max_event/TVaR` | `EAI_total / EAI_direct` | propage l'effet indirect aux metriques portefeuille | Tres haute | Faible | `backend/app/risk_engine/interdependency.py:378`; `backend/app/risk_engine/impact_runner.py:503` | priorite audit/correction |
| Systeme / interdependency | valorisation OFB eau | valeurs OFB par territoire | convertit les dommages relatifs en euros sur les reseaux eau | Tres haute | Moyenne | `scripts/valuation_ofb.py:40` | expertiser avec gestionnaires locaux |
| Systeme / interdependency | valorisation reseaux elec | valeurs fixes par classe | convertit les dommages relatifs en euros sur les reseaux elec | Haute | Moyenne | `scripts/valuation_ofb.py:70` | valider avec donnees locales |
| Systeme / interdependency | valeurs ouvrages AEP | `TRAIT/STPMP/CAP/CUV/default` | convertit les dommages relatifs en euros pour les ouvrages AEP | Haute | Faible | `scripts/valuation_ofb.py:77` | revoir les valeurs par defaut et tracer leur provenance |
| Numerique / proxy / publication | `sampling_spacing_m` backend | `100 m` | discretisation geometrique des expositions | Haute | Moyenne | `backend/app/config.py:44`; `backend/app/risk_engine/exposure_to_climada.py:232` | tester `50/100/250` |
| Numerique / proxy / publication | `climada_max_points_per_feature` | `300` | cap de sampling par actif | Haute | Moyenne | `backend/app/config.py:67`; `backend/app/risk_engine/exposure_to_climada.py:234` | tester `100/300/1000` |
| Numerique / proxy / publication | `climada_metric_crs` | `EPSG:3857` | CRS metrique utilise pour l'echantillonnage | Moyenne | Moyenne | `backend/app/config.py:66`; `backend/app/risk_engine/exposure_to_climada.py:248` | verifier un CRS local alternatif |
| Numerique / proxy / publication | `storm_years` | `10000` | annualisation probabiliste des frequences du catalogue synthetique | Haute | Bonne | `backend/app/config.py:43`; `backend/app/risk_engine/hazard_loader.py:103` | traiter comme convention probabiliste a garder fixe sauf changement de catalogue |
| Numerique / proxy / publication | `hazard_dynamic_max_tracks` | `1200` | cap numerique sur le nombre de tracks dynamiques | Moyenne | Bonne | `backend/app/config.py:55`; `backend/app/risk_engine/hazard_loader.py:406` | traiter comme reglage numerique et non comme hypothese scientifique |
| Numerique / proxy / publication | `spatial_padding_deg` | `4.0 deg` | definit la fenetre spatiale de chargement des tracks | Moyenne | Moyenne | `backend/app/risk_engine/hazard_loader.py:71`; `backend/app/risk_engine/hazard_loader.py:621` | tester `2/4/6` |
| Numerique / proxy / publication | densification petit echantillon de centroides | `threshold=50`, `step=0.01` | densifie artificiellement les petits jeux de points | Basse | Faible | `backend/app/risk_engine/hazard_loader.py:74`; `backend/app/risk_engine/hazard_loader.py:575` | classer explicitement comme convention numerique |
| Numerique / proxy / publication | `hazard_track_cache_max_entries` | `8` | gere cache et memoire, pas la physique | Basse | Bonne | `backend/app/config.py:56`; `backend/app/risk_engine/hazard_loader.py:73` | sortir de la sensibilite scientifique |
| Numerique / proxy / publication | selection source hazard | `dynamic parquet preferred`, `HDF5 fallback` | choisit la source des aleas | Moyenne | Moyenne | `backend/app/config.py:50`; `backend/app/config.py:51` | geler une source unique par campagne |
| Numerique / proxy / publication | `climada_top_events_count` | `20` | nombre d'evenements restitues en sortie | Basse | Bonne | `backend/app/config.py:68` | classer comme convention de restitution |
| Numerique / proxy / publication | `map_cell_deg` cas d'etude | `0.02 deg` | resolution des cartes web | Basse | Bonne | `scripts/rerun_case_studies_light.py:68` | convention de publication |
| Numerique / proxy / publication | `map_surge_native_cell_deg` cas d'etude | `0.01 deg` | resolution fine de submersion pour l'affichage | Basse | Bonne | `scripts/rerun_case_studies_light.py:70` | convention de publication |
| Numerique / proxy / publication | `map_dynamic_max_tracks` cas d'etude | `300` | cap tracks pour cartes front | Basse | Bonne | `scripts/rerun_case_studies_light.py:69` | convention de publication |
| Numerique / proxy / publication | `proxy_spacing_m` | `800 m` | sampling du proxy multi-alea des pages | Basse | Faible | `scripts/rerun_case_studies_light.py:63` | ne pas confondre avec la sensibilite du backend central |
| Numerique / proxy / publication | `proxy_max_points_total` | `800` | cap global du proxy front | Basse | Bonne | `scripts/rerun_case_studies_light.py:64` | convention de publication |
| Numerique / proxy / publication | `proxy_max_points_per_feature` | `8` | cap par actif du proxy front | Basse | Bonne | `scripts/rerun_case_studies_light.py:65` | convention de publication |
| Numerique / proxy / publication | `proxy_dynamic_max_tracks` | `100` | cap tracks pour le proxy front | Basse | Bonne | `scripts/rerun_case_studies_light.py:66` | convention de publication |
| Numerique / proxy / publication | `component_ratios` proxy | derives du rerun/proxy | repartition `wind/rain/surge` dans les pages web | Basse | Faible | `scripts/build_guadeloupe_page1_data.py:930` | traiter comme sortie proxy et non comme hypothese coeur |
| Numerique / proxy / publication | `breakdown_shares` proxy | derives du rerun/proxy | repartition des classes de dommages dans les pages web | Basse | Faible | `scripts/build_guadeloupe_page1_data.py:1143` | traiter comme sortie proxy et non comme hypothese coeur |
| Numerique / proxy / publication | `global_multipliers` proxy | derives du rerun/proxy | ajuste les pertes affichees dans les pages web | Basse | Faible | `scripts/build_guadeloupe_page1_data.py:1157` | traiter comme convention de publication |

## Lecture prioritaire proposee

Pour une premiere campagne de sensibilite, les parametres a traiter en priorite sont:

1. `runoff_coeff = 0.25`
2. les mappings `asset_type -> courbes` vent et flood
3. le choix du modele pluie (`R-CLIPER` vs `TCR`)
4. le DEM et le choix `TCSurgeBathtub`
5. l'approximation `max_loss_by_point`
6. les seuils d'etat `5/15/35`
7. les poids de `health`
8. les seuils `health -> dependency_state`
9. les `uplift_by_state`
10. l'hypothese `all_water_assets_dependent`
11. la resolution `local -> nearest -> global`
12. les valeurs economiques `EUR/km` et `EUR/unite`
13. `sampling_spacing_m` et `max_points_per_feature`
14. le scaling global `dependency_scaler` applique a `PML/max_event/TVaR`

## Point de methode

Il est recommande de separer les campagnes de sensibilite en 4 familles distinctes:

1. `Physique alea`
2. `Vulnerabilite`
3. `Systeme / interdependency`
4. `Numerique / proxy / publication`

Cette separation evite de melanger:

- les incertitudes scientifiques du modele,
- les conventions systeme de propagation et d'agregation,
- et les reglages numeriques ou de publication utilises pour alimenter le front.
