# Complete Analysis: postprocess reseaux PML-light

## Contexte

Les runs `complete analysis` calculent deja les impacts directs CLIMADA et les PML portefeuille pour `storm` et `storm_cmcc`. Le postprocess strict `scientific_graph_postprocess.py` reconstruit ensuite les graphes reseaux en repassant sur des evenements RP point par point. Cette reconstruction scientific V4 est utile pour audit/publication stricte, mais elle est lourde, fragile, et peut etre tuee par SIGKILL sur des runs echantillonnes Guadeloupe/Martinique alors que les impacts principaux sont deja disponibles.

La chaine standard produit donc un bloc approxime et robuste: `pml_network_graph_inputs`, avec `schema_version = "pml_network_graph_inputs_v1"`. Le mode strict reste disponible via `scientific_graph_postprocess.py`, mais il n'est plus le chemin par defaut pour obtenir des graphes exploitables.

## Contrat

Scenarios publics obligatoires:

- `rp10`
- `rp50`
- `rp100`
- `rp1000`

Hazards obligatoires:

- `storm`
- `storm_cmcc`

Le bloc `pml_network_graph_inputs` est archive dans le complete-analysis et alimente les graphes via le resolver commun:

1. `scientific_graph_inputs` strict V4 si present et complet.
2. `pml_network_graph_inputs` si le strict est absent ou legacy.

Les runs echantillonnes continuent a utiliser `track_sample_manifest` comme source de verite des tracks archives.

## Calibration PML

Pour chaque hazard et scenario, le PML cible est lu dans `portfolio_results`:

- `rp10 -> pml_10_eur`
- `rp50 -> pml_50_eur`
- `rp100 -> pml_100_eur`
- `rp1000 -> pml_1000_eur`

La distribution point par point part des pertes directes annuelles deja calculees. Pour chaque classe d'infrastructure, on calcule:

```text
class_share[c] = annual_direct_loss[c] / sum(annual_direct_loss)
class_target_pml[c] = PML[h,s] * class_share[c]
```

Si aucune perte annuelle exploitable n'existe pour une classe presente, la part d'exposition sert de fallback. La perte d'un point est bornee par sa valeur exposee. Un rescale global final force la somme des pertes vers le PML cible, sous contrainte de capacite.

Les ratios de composantes `wind/rain/surge/landslide` utilisent les breakdowns deja disponibles quand ils existent; sinon le prior annuel direct est conserve. Aucun recalcul CLIMADA `save_mat=True` n'est lance dans cette chaine.

## Etats Reseaux Et Causes

Pour chaque point reseau:

```text
direct_damage_ratio = direct_loss / exposed_value
direct_state = S0/S1/S2/S3
dependency_state = etat induit par dysfonctionnement electrique
blocking_state = etat induit par ouvrage bloquant
final_state = max(direct_state, dependency_state, blocking_state)
```

La cause dominante suit l'ordre:

- `none` si `final_state == S0`
- `direct_damage` si le dommage direct atteint l'etat final
- `blocking_ouvrage` si l'ouvrage bloquant atteint l'etat final
- `electric_dependency` sinon

Les sorties GeoJSON reseau publient les colonnes:

- `state_rp10_storm`, `state_rp50_storm`, `state_rp100_storm`, `state_rp1000_storm`
- memes colonnes pour `storm_cmcc`
- `cause_rp10_storm`, etc., avec `direct_damage`, `electric_dependency`, `blocking_ouvrage`, `none`

Les matrices lisent `state_damage_tables[scenario][network_class][hazard]` avec:

- `direct_damage_eur`
- `dysfunction_eur`
- `blocking_ouvrage_eur`
- `indirect_damage_eur = dysfunction_eur + blocking_ouvrage_eur`
- `total_damage_eur`

## Limite Assumee

Cette chaine n'est pas une reconstruction exacte d'evenements RP point par point. Elle est une approximation operationnelle calibree sur les PML portefeuille, choisie pour garantir que les runs complete-analysis produisent des outputs graphes de bout en bout. Pour une publication stricte ou un audit d'evenements precis, utiliser explicitement `scientific_graph_postprocess.py`.

## Points D'Integration

- `backend/app/risk_engine/impact_runner.py` produit `pml_network_graph_inputs` pendant le calcul des impacts.
- `backend/app/risk_engine/analysis_export.py` publie ce bloc au niveau top-level du complete-analysis.
- `scripts/run_complete_analysis.py` valide la presence du bloc PML-light et saute le postprocess strict par defaut.
- `scripts/build_scientific_web_summary.py` accepte strict V4 ou PML-light et republie un contrat graphes coherent.
- `scripts/generate_run_graphs.py` utilise le meme ordre de resolution.
- `scripts/build_guadeloupe_page1_data.py` publie les colonnes RP10/RP50/RP100/RP1000 et les causes dans `network_states.geojson`.

## Contrat Post-Run Frontend Et Graphes

Le rebuild frontend doit produire et archiver, avant la generation des graphes:

- `{territory}-multi-hazard-proxy.json`
- `{territory}-{page_suffix}-analysis.json`
- `{territory}-network-states.geojson`
- `{territory}-scientific-web-summary.json`

Le proxy multi-alea doit exposer tous les scenarios utilises par la page d'analyse:

- `annual`
- `rp10`
- `rp50`
- `rp100`
- `rp1000`
- `event_max`
- `top10`
- `top5`

La page d'analyse est construite avant le summary scientifique, car le summary doit republier les distributions reseaux et sociales depuis le `network-states.geojson` archive. Si le rebuild frontend echoue ou si le snapshot archive est incomplet, `run_complete_analysis.py` ne lance plus les phases `scientific_publication` et `graphs` pour un run normal: le run doit echouer explicitement plutot que produire un pack graphes partiel.
