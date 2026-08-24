# Diagnostic vents et mailles (auto-genere)

- Genere le: 2026-06-23 14:27 UTC
- Unite vent normalisee: km/h
- Regeneration: `python scripts/build_wind_speed_comparison_doc.py` (met a jour automatiquement tableaux et mailles).
- Verification mailles `complete analysis`: lecture des payloads publies `guadeloupe-complete-analysis.json` et `martinique-complete-analysis.json`.

## Comparaison vitesses max - Bassin NA complet

| Indicateur | STORM | STORM_CMCC | Delta (CMCC-STORM) |
|---|---:|---:|---:|
| Nombre d annees actives (>=1 passage dans la zone) | 10 000 | 10 000 | 0 |
| Nombre de cyclones/evenements (max par track) | 107 063 | 123 536 | 16 473 |
| Moyenne des vitesses max annuelles (km/h) | 215,81 | 226,73 | 10,93 |
| Moyenne des vitesses max par cyclone/evenement (km/h) | 124,82 | 134,11 | 9,29 |
| Vitesse max annuelle - temps de retour 100 ans (km/h) | 273,24 | 284,40 | 11,16 |
| Vitesse max par cyclone/evenement - temps de retour 100 ans (km/h) | 252,36 | 262,44 | 10,08 |
| Vitesse max annuelle - temps de retour 1000 ans (km/h) | 284,40 | 291,96 | 7,56 |
| Vitesse max par cyclone/evenement - temps de retour 1000 ans (km/h) | 272,88 | 283,68 | 10,80 |
| Max des vitesses max annuelles (km/h) | 300,61 | 305,28 | 4,67 |
| Max des vitesses max par cyclone/evenement (km/h) | 300,61 | 305,28 | 4,67 |

## Comparaison vitesses max - Bassin SI complet

| Indicateur | STORM | STORM_CMCC | Delta (CMCC-STORM) |
|---|---:|---:|---:|
| Nombre d annees actives (>=1 passage dans la zone) | 7 984 | 10 000 | 2 016 |
| Nombre de cyclones/evenements (max par track) | 98 114 | 104 080 | 5 966 |
| Moyenne des vitesses max annuelles (km/h) | 188,74 | 200,87 | 12,14 |
| Moyenne des vitesses max par cyclone/evenement (km/h) | 121,97 | 136,19 | 14,22 |
| Vitesse max annuelle - temps de retour 100 ans (km/h) | 252,36 | 269,28 | 16,92 |
| Vitesse max par cyclone/evenement - temps de retour 100 ans (km/h) | 218,16 | 234,72 | 16,56 |
| Vitesse max annuelle - temps de retour 1000 ans (km/h) | 267,49 | 285,48 | 17,99 |
| Vitesse max par cyclone/evenement - temps de retour 1000 ans (km/h) | 250,52 | 268,56 | 18,04 |
| Max des vitesses max annuelles (km/h) | 275,76 | 306,72 | 30,96 |
| Max des vitesses max par cyclone/evenement (km/h) | 275,76 | 306,72 | 30,96 |

## Comparaison vitesses max - Bassin SP complet

| Indicateur | STORM | STORM_CMCC | Delta (CMCC-STORM) |
|---|---:|---:|---:|
| Nombre d annees actives (>=1 passage dans la zone) | 10 000 | 9 999 | -1 |
| Nombre de cyclones/evenements (max par track) | 93 266 | 94 091 | 825 |
| Moyenne des vitesses max annuelles (km/h) | 180,76 | 206,21 | 25,45 |
| Moyenne des vitesses max par cyclone/evenement (km/h) | 120,19 | 137,50 | 17,31 |
| Vitesse max annuelle - temps de retour 100 ans (km/h) | 255,60 | 280,08 | 24,48 |
| Vitesse max par cyclone/evenement - temps de retour 100 ans (km/h) | 223,56 | 249,84 | 26,28 |
| Vitesse max annuelle - temps de retour 1000 ans (km/h) | 277,92 | 300,96 | 23,04 |
| Vitesse max par cyclone/evenement - temps de retour 1000 ans (km/h) | 256,32 | 280,80 | 24,48 |
| Max des vitesses max annuelles (km/h) | 315,36 | 354,60 | 39,24 |
| Max des vitesses max par cyclone/evenement (km/h) | 315,36 | 354,60 | 39,24 |

## Comparaison vitesses max - Zone Guadeloupe
- BBox: lat [15.5, 16.95625] ; lon [-62.48125, -60.66875]
- Note: le nombre d annees correspond aux annees actives avec au moins un passage dans la zone.

| Indicateur | STORM | STORM_CMCC | Delta (CMCC-STORM) |
|---|---:|---:|---:|
| Nombre d annees actives (>=1 passage dans la zone) | 2 655 | 2 887 | 232 |
| Nombre de cyclones/evenements (max par track) | 3 126 | 3 401 | 275 |
| Moyenne des vitesses max annuelles (km/h) | 134,11 | 129,59 | -4,52 |
| Moyenne des vitesses max par cyclone/evenement (km/h) | 129,29 | 125,49 | -3,80 |
| Vitesse max annuelle - temps de retour 100 ans (km/h) | 229,49 | 234,77 | 5,28 |
| Vitesse max par cyclone/evenement - temps de retour 100 ans (km/h) | 228,15 | 234,00 | 5,85 |
| Vitesse max annuelle - temps de retour 1000 ans (km/h) | 241,20 | 243,36 | 2,16 |
| Vitesse max par cyclone/evenement - temps de retour 1000 ans (km/h) | 241,16 | 243,07 | 1,92 |
| Max des vitesses max annuelles (km/h) | 244,08 | 250,56 | 6,48 |
| Max des vitesses max par cyclone/evenement (km/h) | 244,08 | 250,56 | 6,48 |

## Comparaison vitesses max - Zone Martinique
- BBox: lat [14.3, 15.1] ; lon [-61.4, -60.7]
- Note: le nombre d annees correspond aux annees actives avec au moins un passage dans la zone.

| Indicateur | STORM | STORM_CMCC | Delta (CMCC-STORM) |
|---|---:|---:|---:|
| Nombre d annees actives (>=1 passage dans la zone) | 1 466 | 1 502 | 36 |
| Nombre de cyclones/evenements (max par track) | 1 596 | 1 639 | 43 |
| Moyenne des vitesses max annuelles (km/h) | 124,07 | 121,62 | -2,46 |
| Moyenne des vitesses max par cyclone/evenement (km/h) | 122,38 | 119,34 | -3,04 |
| Vitesse max annuelle - temps de retour 100 ans (km/h) | 234,49 | 227,15 | -7,34 |
| Vitesse max par cyclone/evenement - temps de retour 100 ans (km/h) | 231,97 | 226,08 | -5,89 |
| Vitesse max annuelle - temps de retour 1000 ans (km/h) | 255,06 | 250,38 | -4,68 |
| Vitesse max par cyclone/evenement - temps de retour 1000 ans (km/h) | 254,40 | 249,83 | -4,57 |
| Max des vitesses max annuelles (km/h) | 265,32 | 255,60 | -9,72 |
| Max des vitesses max par cyclone/evenement (km/h) | 265,32 | 255,60 | -9,72 |

## Mailles utilisees

| Couche | Valeur |
|---|---|
| Hazard vent dans `complete analysis` | Pas de grille reguliere fixe: chargement dynamique STORM/STORM_CMCC sur points d exposition (`hazard_source=dynamic_parquet`) |
| Points hazard/exposition dans `complete analysis` | Guadeloupe: 290 545 points ; Martinique: 325 765 points |
| Maille d agregation territoriale dans `complete analysis` | 0,200 deg (meme valeur dans les payloads Guadeloupe et Martinique) |
| Maille points d exposition dans `complete analysis` | 100 m (pas nominal), max 300 points/feature |
| Maille cartes vents web Guadeloupe / Martinique | Guadeloupe: 0,020 deg ; Martinique: 0,020 deg (restitution web, hors `complete analysis`) |
| Maille aleas pluie web Guadeloupe / Martinique | Guadeloupe: 0,020 deg ; Martinique: 0,020 deg (meme maille de publication que le vent dans les artefacts actuels) |
| Maille aleas surge web Guadeloupe / Martinique | Guadeloupe: 0,020 deg ; Martinique: 0,020 deg (pas de sous-maille differente publiee actuellement) |
| Maille aleas landslide web Guadeloupe / Martinique | Guadeloupe: 0,020 deg ; Martinique: 0,020 deg (meme maille de publication que le vent dans les artefacts actuels) |
| Maille cartes vents bassin NA / SI / SP | 0,050 deg (`scripts/build_basin_wind_maps.py`, restitution web, hors `complete analysis`) |
| Maille dependance elec -> eau | 0,100 deg (`fixed_grid_0p1deg`, aggregation native des etats elec avant projection sur l eau) |

## Autres mailles ou pas reperes dans le projet

| Element | Valeur |
|---|---|
| Grille population / social impacts | 0,200 deg (meme logique que la maille territoriale `complete analysis`) |
| Petit cas `hazard_loader.py` | 0,010 deg (maille utilitaire de sous-echantillonnage, pas une maille de publication courante) |
| Fenetre spatiale du loader | 4,000 deg de padding (ce n est pas une maille, mais une fenetre de chargement autour des expositions) |

## Population totale par territoire (WorldPop 2020)

- Source: rasters WorldPop sous `/home/ubuntu/uploads/Population`
- Methode: somme des valeurs du raster de population par territoire, hors `NoData`

| Territoire | Population totale |
|---|---:|
| Guadeloupe | 408 604 |
| Martinique | 358 164 |
| Saint-Barthelemy | 10 405 |
| Saint-Martin | 33 134 |
| Saint-Pierre-et-Miquelon | 5 851 |
| La Reunion | 856 724 |
| Mayotte | 279 657 |
| Nouvelle-Caledonie | 283 701 |
| Guyane | 803 199 |
