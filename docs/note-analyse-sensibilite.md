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

## Chaine `SIB: Run Sensitivity Analysis Default Pack V2`

La chaine V2 vise a relancer une analyse de sensibilite alignee avec la chaine `complete-analysis` courante, sans modifier retroactivement le run historique `outputs/sensitivity-runs/sensitivity_20260619_073544`.

Le pack V2 est defini dans `config/sensitivity/default-scenario-pack-v2.json`. Il reprend uniquement les scenarios du dernier run ayant montre une influence significative, avec la regle suivante:

- variation absolue `>= 3%` sur les impacts monetaires, ou
- variation absolue `>= 3 points` sur les etats reseau.

Exception explicite: `territory_grid_deg` est conserve meme si son influence etait faible dans `sensitivity_20260619_073544`, car il reste utile pour verifier la maille spatiale de resolution de la sante electrique.

Scenarios conserves ou ajoutes dans le pack V2:

- baseline `all-default`;
- courbes de vulnerabilite: `vulnerability_curves_profile-elec-flood-moderate`, `vulnerability_curves_profile-elec-flood-stress`, `vulnerability_curves_profile-elec-wind-underground-exposed`;
- pluie proxy: `runoff_coeff-0-1`, `runoff_coeff-0-5`;
- etats directs reseau: `direct_state_thresholds-10-20-40`, `direct_state_thresholds-10-15-50`;
- nombre de tracks hazard: `hazard_dynamic_max_tracks-50`, `hazard_dynamic_max_tracks-100`, `hazard_dynamic_max_tracks-800`, `hazard_dynamic_max_tracks-5000`;
- maille electrique: `territory_grid_deg-0-05`, `territory_grid_deg-0-1`.

Scenarios retires du default pack initial: `health_weights-*`, `dependency_state_thresholds-*`, `max_dist_inland_km-*`, `default_sampling_spacing_m-*`, `climada_max_points_per_feature-*`, le placeholder unsupported `vulnerability_curves_profile-manual-profile-required`, ainsi que les valeurs hazard tracks `500` et `1000`.

La baseline V2 et les scenarios non `hazard_dynamic_max_tracks` utilisent l'echantillon V1 exact:

`/home/ubuntu/sib-work/outputs/Échantillons Tracks_NA_Guadeloupe/sample_1500/manifest.json`

Les scenarios `hazard_dynamic_max_tracks` surchargent aussi `hazard_track_sample_manifest_path` vers le manifest V1 correspondant (`sample_0050`, `sample_0100`, `sample_0800`, `sample_5000`). Cette double surcharge est necessaire: changer seulement `hazard_dynamic_max_tracks` sans changer l'echantillon lu ne testerait pas vraiment le nombre de tracks.

Procedure recommandee:

1. Lancer la tache VS Code `SIB: Run Sensitivity Analysis Default Pack V2`.
2. Noter le `run_id` cree dans `outputs/sensitivity-runs/<run_id>/manifest.json`.
3. Lancer `SIB: Babysit Sensitivity Analysis Run` avec ce `run_id` si le run doit etre surveille/repris.
4. Generer les graphes filtres avec `SIB: Generate Sensitivity V2 Significant Graphs - Choose Run ID`.

La tache de graphes V2 ecrit dans `<run>/graphs-significant` et utilise `--significant-only --impact-significance-threshold-pct 3 --network-significance-threshold-pp 3 --disable-default-exclusions`. Les scenarios non complets sont exclus proprement des graphes et listes dans `sensitivity-graphs-summary.json`.

### Controle de coherence des scenarios configurés et executes

Controle effectue contre les packs de configuration et le run:

- pack initial `config/sensitivity/default-scenario-pack.json`: 23 scenarios declares, dont 22 supportes/testables; le placeholder `vulnerability_curves_profile-manual-profile-required` reste non supporte;
- pack dedie vulnerabilite `config/sensitivity/vulnerability-curve-scenario-pack.json`: 4 scenarios supportes, soit la baseline plus 3 variations de vulnerabilite;
- pack courant `config/sensitivity/default-scenario-pack-v2.json`: 14 scenarios supportes, tous lances par le run `outputs/sensitivity-runs/sensitivity_20260723_132922`;
- run `sensitivity_20260723_132922`: statut `success`, 14 scenarios complets, 0 echec, 0 skip.

Les 3 scenarios de variation de vulnerabilite ont bien ete ajoutes au pack V2 et executes:

- `vulnerability_curves_profile-elec-flood-moderate`;
- `vulnerability_curves_profile-elec-flood-stress`;
- `vulnerability_curves_profile-elec-wind-underground-exposed`.

Comptage consolide:

- **27 scenarios supportes/testables au total** dans les packs actuels, baseline incluse;
- **26 variations testables** hors baseline `all-default`;
- **14 scenarios dans le default pack V2** et dans le run `sensitivity_20260723_132922`, baseline incluse;
- **13 scenarios supportes restent testables mais sont volontairement evacues du default pack V2**, car le run de reference `sensitivity_20260619_073544` avait montre une influence faible ou nulle selon le seuil retenu.

Scenarios supportes mais non relances par le default pack V2:

- `health_weights-0-3-1-1-0`, `health_weights-0-3-0-5-5`;
- `dependency_state_thresholds-0-5-0-30-0-15`, `dependency_state_thresholds-0-90-0-75-0-55`;
- `max_dist_inland_km-200`, `max_dist_inland_km-1000`;
- `hazard_dynamic_max_tracks-500`, `hazard_dynamic_max_tracks-1000`;
- `default_sampling_spacing_m-50`, `default_sampling_spacing_m-250`;
- `climada_max_points_per_feature-100`, `climada_max_points_per_feature-500`, `climada_max_points_per_feature-1000`.

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

Le tableau ci-dessous ne conserve que les scenarios automatisables et supportes dans les packs de sensibilite actuels. Les hypotheses non encodees en scenario supporte sont retirees du tableau de campagne: elles restent des sujets d'audit ou d'expertise, mais ne font pas partie des 27 scenarios testables.

| Categorie | Scenario testable (`scenario_id`) | Parametre | Valeur / profil teste | Execution | Repris default pack V2 | Commentaire |
| --- | --- | --- | --- | --- | --- | --- |
| Reference | `all-default` | baseline | Parametres courants de la chaine `complete-analysis` | `full_rerun` | Oui | Reference du run V2 |
| Vulnerabilite | `vulnerability_curves_profile-elec-flood-moderate` | `vulnerability_curves_profile` | Courbes flood elec -> `F14.4`; autres mappings flood inchanges | `full_rerun` | Oui | Ajoute au V2; teste une reponse flood electrique moderee |
| Vulnerabilite | `vulnerability_curves_profile-elec-flood-stress` | `vulnerability_curves_profile` | Courbes flood elec -> `F17.5`; autres mappings flood inchanges | `full_rerun` | Oui | Ajoute au V2; stress test flood electrique |
| Vulnerabilite | `vulnerability_curves_profile-elec-wind-underground-exposed` | `vulnerability_curves_profile` | Elec souterrain vent: BT -> `W3.10`, HTA -> `W3.14` | `full_rerun` | Oui | Ajoute au V2; stress test proxy des cables souterrains |
| Vulnerabilite | `runoff_coeff-0-1` | `runoff_coeff` | `multi_hazard_rain_base_runoff_coeff = 0.1` | `full_rerun` | Oui | Conserve car variation significative observee |
| Vulnerabilite | `runoff_coeff-0-5` | `runoff_coeff` | `multi_hazard_rain_base_runoff_coeff = 0.5` | `full_rerun` | Oui | Conserve car variation significative observee |
| Systeme / interdependency | `direct_state_thresholds-10-20-40` | `direct_state_thresholds` | Seuils directs `10% / 20% / 40%` | `postprocess_rerun` | Oui | Conserve car variation d'etats reseau significative |
| Systeme / interdependency | `direct_state_thresholds-10-15-50` | `direct_state_thresholds` | Seuils directs `10% / 15% / 50%` | `postprocess_rerun` | Oui | Conserve car variation d'etats reseau significative |
| Numerique / proxy / publication | `hazard_dynamic_max_tracks-50` | `hazard_dynamic_max_tracks` | `50` tracks + manifest `sample_0050` | `full_rerun` | Oui | Ajoute au V2 avec echantillon coherent |
| Numerique / proxy / publication | `hazard_dynamic_max_tracks-100` | `hazard_dynamic_max_tracks` | `100` tracks + manifest `sample_0100` | `full_rerun` | Oui | Conserve dans le V2 avec echantillon coherent |
| Numerique / proxy / publication | `hazard_dynamic_max_tracks-800` | `hazard_dynamic_max_tracks` | `800` tracks + manifest `sample_0800` | `full_rerun` | Oui | Conserve dans le V2 avec echantillon coherent |
| Numerique / proxy / publication | `hazard_dynamic_max_tracks-5000` | `hazard_dynamic_max_tracks` | `5000` tracks + manifest `sample_5000` | `full_rerun` | Oui | Ajoute au V2 avec echantillon coherent |
| Systeme / interdependency | `territory_grid_deg-0-05` | `territory_grid_deg` | `0.05 deg` | `full_rerun` | Oui | Conserve par decision explicite malgre influence faible |
| Systeme / interdependency | `territory_grid_deg-0-1` | `territory_grid_deg` | `0.1 deg` | `full_rerun` | Oui | Conserve par decision explicite malgre influence faible |
| Systeme / interdependency | `health_weights-0-3-1-1-0` | `health_weights` | Poids sante `0.3 / 1.0 / 1.0` | `postprocess_rerun` | Non | Testable hors pack; evacue du V2 pour faible influence observee |
| Systeme / interdependency | `health_weights-0-3-0-5-5` | `health_weights` | Poids sante `0.3 / 0.5 / 5.0` | `postprocess_rerun` | Non | Testable hors pack; evacue du V2 pour faible influence observee |
| Systeme / interdependency | `dependency_state_thresholds-0-5-0-30-0-15` | `dependency_state_thresholds` | Seuils `health -> dependency_state`: `0.50 / 0.30 / 0.15` | `postprocess_rerun` | Non | Testable hors pack; evacue du V2 pour faible influence observee |
| Systeme / interdependency | `dependency_state_thresholds-0-90-0-75-0-55` | `dependency_state_thresholds` | Seuils `health -> dependency_state`: `0.90 / 0.75 / 0.55` | `postprocess_rerun` | Non | Testable hors pack; evacue du V2 pour faible influence observee |
| Physique alea | `max_dist_inland_km-200` | `max_dist_inland_km` | `hazard_rain_max_dist_inland_km = 200` | `full_rerun` | Non | Testable hors pack; evacue du V2 pour faible influence observee |
| Physique alea | `max_dist_inland_km-1000` | `max_dist_inland_km` | `hazard_rain_max_dist_inland_km = 1000` | `full_rerun` | Non | Testable hors pack; evacue du V2 pour faible influence observee |
| Numerique / proxy / publication | `hazard_dynamic_max_tracks-500` | `hazard_dynamic_max_tracks` | `500` tracks | `full_rerun` | Non | Testable hors pack; remplace dans V2 par la grille `50 / 100 / 800 / 5000` |
| Numerique / proxy / publication | `hazard_dynamic_max_tracks-1000` | `hazard_dynamic_max_tracks` | `1000` tracks | `full_rerun` | Non | Testable hors pack; remplace dans V2 par la grille `50 / 100 / 800 / 5000` |
| Numerique / proxy / publication | `default_sampling_spacing_m-50` | `default_sampling_spacing_m` | `sampling_spacing_m = 50 m` | `full_rerun` | Non | Testable hors pack; evacue du V2 pour faible influence observee |
| Numerique / proxy / publication | `default_sampling_spacing_m-250` | `default_sampling_spacing_m` | `sampling_spacing_m = 250 m` | `full_rerun` | Non | Testable hors pack; evacue du V2 pour faible influence observee |
| Numerique / proxy / publication | `climada_max_points_per_feature-100` | `climada_max_points_per_feature` | `100` points max par actif | `full_rerun` | Non | Testable hors pack; evacue du V2 pour faible influence observee |
| Numerique / proxy / publication | `climada_max_points_per_feature-500` | `climada_max_points_per_feature` | `500` points max par actif | `full_rerun` | Non | Testable hors pack; evacue du V2 pour faible influence observee |
| Numerique / proxy / publication | `climada_max_points_per_feature-1000` | `climada_max_points_per_feature` | `1000` points max par actif | `full_rerun` | Non | Testable hors pack; evacue du V2 pour faible influence observee |

Lecture actuelle:

- le default pack V2 relance les 14 lignes marquees `Oui`;
- les 13 lignes marquees `Non` restent techniquement supportees, mais ne sont plus dans la campagne par defaut;
- les anciens sujets non representes ici (`storm_env_pressure_hpa`, `hazard_rain_model`, DEM de submersion, `uplift_by_state`, valeurs economiques, parametres proxy front, etc.) ne sont pas des scenarios automatises retenus dans les packs actuels et sont donc retires de la matrice de sensibilite testable.

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
