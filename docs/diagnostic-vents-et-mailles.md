# Diagnostic vents et mailles (auto-genere)

- Genere le: 2026-03-04 13:09 UTC
- Unite vent normalisee: m/s
- Regeneration: `python scripts/build_wind_speed_comparison_doc.py` (met a jour automatiquement tableaux et mailles).

## Comparaison vitesses max - Bassin NA complet

| Indicateur | STORM | STORM_CMCC | Delta (CMCC-STORM) |
|---|---:|---:|---:|
| Nombre d annees actives (>=1 passage dans la zone) | 10 000 | 10 000 | 0 |
| Nombre de cyclones/evenements (max par track) | 107 063 | 123 536 | 16 473 |
| Moyenne des vitesses max annuelles (m/s) | 59,95 | 62,98 | 3,03 |
| Moyenne des vitesses max par cyclone/evenement (m/s) | 34,67 | 37,25 | 2,58 |
| P95 des vitesses max annuelles (m/s) | 72,10 | 76,10 | 4,00 |
| P95 des vitesses max par cyclone/evenement (m/s) | 63,40 | 64,90 | 1,50 |
| Max des vitesses max annuelles (m/s) | 83,50 | 84,80 | 1,30 |
| Max des vitesses max par cyclone/evenement (m/s) | 83,50 | 84,80 | 1,30 |
## Comparaison vitesses max - Zone Guadeloupe
- BBox: lat [15.5, 16.95625] ; lon [-62.48125, -60.66875]
- Note: le nombre d annees correspond aux annees actives avec au moins un passage dans la zone.

| Indicateur | STORM | STORM_CMCC | Delta (CMCC-STORM) |
|---|---:|---:|---:|
| Nombre d annees actives (>=1 passage dans la zone) | 2 655 | 2 887 | 232 |
| Nombre de cyclones/evenements (max par track) | 3 126 | 3 401 | 275 |
| Moyenne des vitesses max annuelles (m/s) | 37,25 | 36,00 | -1,26 |
| Moyenne des vitesses max par cyclone/evenement (m/s) | 35,91 | 34,86 | -1,05 |
| P95 des vitesses max annuelles (m/s) | 58,30 | 59,77 | 1,47 |
| P95 des vitesses max par cyclone/evenement (m/s) | 57,30 | 58,80 | 1,50 |
| Max des vitesses max annuelles (m/s) | 67,80 | 69,60 | 1,80 |
| Max des vitesses max par cyclone/evenement (m/s) | 67,80 | 69,60 | 1,80 |
## Comparaison vitesses max - Zone Martinique
- BBox: lat [14.3, 15.1] ; lon [-61.4, -60.7]
- Note: le nombre d annees correspond aux annees actives avec au moins un passage dans la zone.

| Indicateur | STORM | STORM_CMCC | Delta (CMCC-STORM) |
|---|---:|---:|---:|
| Nombre d annees actives (>=1 passage dans la zone) | 1 466 | 1 502 | 36 |
| Nombre de cyclones/evenements (max par track) | 1 596 | 1 639 | 43 |
| Moyenne des vitesses max annuelles (m/s) | 34,46 | 33,78 | -0,68 |
| Moyenne des vitesses max par cyclone/evenement (m/s) | 34,00 | 33,15 | -0,84 |
| P95 des vitesses max annuelles (m/s) | 57,18 | 56,19 | -0,98 |
| P95 des vitesses max par cyclone/evenement (m/s) | 56,80 | 55,40 | -1,40 |
| Max des vitesses max annuelles (m/s) | 73,70 | 71,00 | -2,70 |
| Max des vitesses max par cyclone/evenement (m/s) | 73,70 | 71,00 | -2,70 |

## Impacts (resume auto)

| Indicateur impact | STORM | STORM_CMCC | Delta (CMCC-STORM) |
|---|---:|---:|---:|
| EAI total (€) | 92 757 235,20 | 90 442 218,25 | -2 315 016,95 |
| Perte evenement max (€) | 3 182 416 789,58 | 3 377 071 008,69 | 194 654 219,11 |
| HS direct S3 annuel (%) | 0,00 | 0,00 | 0,00 |
| HS indirect S3 annuel (%) | 0,00 | 0,00 | 0,00 |
| HS direct S3 evt max (%) | 94,83 | 94,83 | 0,00 |
| HS indirect S3 evt max (%) | 0,00 | 0,00 | 0,00 |

| Reseau | STORM EAI (€) | STORM evt max (€) | STORM_CMCC EAI (€) | STORM_CMCC evt max (€) |
|---|---:|---:|---:|---:|
| Eau AEP | 17 652 957,66 | 785 789 467,15 | 17 241 941,96 | 834 957 869,44 |
| Eau EU | 5 380 452,53 | 242 539 724,99 | 5 239 186,90 | 255 728 690,42 |
| Elec BT souterrain | 8 031 266,82 | 248 294 468,19 | 7 818 954,57 | 263 396 495,95 |
| Elec BT aerien | 10 637 862,53 | 323 219 321,83 | 10 382 543,02 | 347 849 661,63 |
| Elec HTA souterrain | 17 501 293,17 | 532 424 260,53 | 17 062 187,53 | 571 843 235,74 |
| Elec HTA aerien | 2 602 562,51 | 78 091 867,26 | 2 543 720,92 | 84 842 359,81 |

## Mailles utilisees

| Couche | Valeur |
|---|---|
| Maille hazard (impact CLIMADA) | 0,020 deg (lat) x 0,020 deg (lon), 6808 centroids |
| BBox hazard (impact CLIMADA) | lat [15,500, 16,960], lon [-62,480, -60,660] |
| Maille carte vents moyenne (web) | 0,020 deg |
| Maille points d exposition (sampling) | 100 m (pas nominal), max 300 points/feature |
