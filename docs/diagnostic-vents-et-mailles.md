# Diagnostic vents et mailles (auto-genere)

- Genere le: 2026-03-05 11:33 UTC
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
| EAI total (€) | 131 380 076,47 | 128 137 990,62 | -3 242 085,85 |
| Perte evenement max (€) | 4 875 886 816,28 | 5 172 572 047,43 | 296 685 231,15 |
| HS direct S3 annuel (%) | 0,00 | 0,00 | 0,00 |
| HS indirect S3 annuel (%) | 0,00 | 0,00 | 0,00 |
| HS direct S3 evt max (%) | 94,76 | 94,76 | 0,00 |
| HS indirect S3 evt max (%) | 0,00 | 0,00 | 0,00 |

### Tableau des impacts annuels (moyenne)

| Reseau | STORM S0/S1/S2/S3 (%) | STORM EAI (€) | STORM_CMCC S0/S1/S2/S3 (%) | STORM_CMCC EAI (€) |
|---|---:|---:|---:|---:|
| Eau AEP | S0 100,00 / S1 0,00 / S2 0,00 / S3 0,00 | 46 979 543,35 | S0 100,00 / S1 0,00 / S2 0,00 / S3 0,00 | 45 887 934,63 |
| Eau EU | S0 100,00 / S1 0,00 / S2 0,00 / S3 0,00 | 12 362 110,97 | S0 100,00 / S1 0,00 / S2 0,00 / S3 0,00 | 12 037 573,74 |
| Elec BT souterrain | S0 100,00 / S1 0,00 / S2 0,00 / S3 0,00 | 8 031 266,82 | S0 100,00 / S1 0,00 / S2 0,00 / S3 0,00 | 7 818 954,57 |
| Elec BT aerien | S0 100,00 / S1 0,00 / S2 0,00 / S3 0,00 | 10 637 862,53 | S0 100,00 / S1 0,00 / S2 0,00 / S3 0,00 | 10 382 543,02 |
| Elec HTA souterrain | S0 100,00 / S1 0,00 / S2 0,00 / S3 0,00 | 17 501 293,17 | S0 100,00 / S1 0,00 / S2 0,00 / S3 0,00 | 17 062 187,53 |
| Elec HTA aerien | S0 100,00 / S1 0,00 / S2 0,00 / S3 0,00 | 2 602 562,51 | S0 100,00 / S1 0,00 / S2 0,00 / S3 0,00 | 2 543 720,92 |

### Tableau des impacts causes par les evenements a temps de retour 100 ans

| Reseau | STORM S0/S1/S2/S3 (%) | STORM RP100 (€) | STORM_CMCC S0/S1/S2/S3 (%) | STORM_CMCC RP100 (€) |
|---|---:|---:|---:|---:|
| Eau AEP | S0 0,00 / S1 0,00 / S2 0,00 / S3 100,00 | 1 228 532 360,82 | S0 0,00 / S1 0,00 / S2 0,00 / S3 100,00 | 1 273 451 627,58 |
| Eau EU | S0 0,00 / S1 0,00 / S2 0,00 / S3 100,00 | 328 778 747,94 | S0 0,00 / S1 0,00 / S2 0,00 / S3 100,00 | 338 762 224,56 |
| Elec BT souterrain | S0 21,61 / S1 0,00 / S2 45,67 / S3 32,73 | 147 616 245,81 | S0 21,61 / S1 0,00 / S2 0,00 / S3 78,39 | 151 873 178,89 |
| Elec BT aerien | S0 0,94 / S1 0,00 / S2 99,06 / S3 0,00 | 190 725 990,39 | S0 0,94 / S1 0,00 / S2 38,73 / S3 60,34 | 196 736 672,02 |
| Elec HTA souterrain | S0 9,86 / S1 0,00 / S2 90,14 / S3 0,00 | 314 043 383,85 | S0 9,86 / S1 0,00 / S2 49,63 / S3 40,51 | 322 156 636,51 |
| Elec HTA aerien | S0 1,21 / S1 0,00 / S2 98,79 / S3 0,00 | 45 981 990,36 | S0 1,21 / S1 0,00 / S2 65,71 / S3 33,08 | 47 456 759,58 |

### Tableau des impacts causes par les evenements a temps de retour 1000 ans

| Reseau | STORM S0/S1/S2/S3 (%) | STORM RP1000 (€) | STORM_CMCC S0/S1/S2/S3 (%) | STORM_CMCC RP1000 (€) |
|---|---:|---:|---:|---:|
| Eau AEP | S0 0,00 / S1 0,00 / S2 0,00 / S3 100,00 | 1 868 717 196,22 | S0 0,00 / S1 0,00 / S2 0,00 / S3 100,00 | 1 825 198 561,87 |
| Eau EU | S0 0,00 / S1 0,00 / S2 0,00 / S3 100,00 | 492 592 583,42 | S0 0,00 / S1 0,00 / S2 0,00 / S3 100,00 | 480 065 236,64 |
| Elec BT souterrain | S0 21,61 / S1 0,00 / S2 0,00 / S3 78,39 | 220 241 718,16 | S0 21,61 / S1 0,00 / S2 0,00 / S3 78,39 | 215 088 846,02 |
| Elec BT aerien | S0 0,94 / S1 0,00 / S2 0,00 / S3 99,06 | 286 581 015,93 | S0 0,94 / S1 0,00 / S2 0,00 / S3 99,06 | 283 293 550,57 |
| Elec HTA souterrain | S0 9,86 / S1 0,00 / S2 0,00 / S3 90,14 | 471 406 568,85 | S0 9,86 / S1 0,00 / S2 0,00 / S3 90,14 | 464 392 744,84 |
| Elec HTA aerien | S0 1,21 / S1 0,00 / S2 0,00 / S3 98,79 | 69 642 191,73 | S0 1,21 / S1 0,00 / S2 0,00 / S3 98,79 | 69 289 012,99 |

### Tableau des impacts causes par l'evenement le plus fort

| Reseau | STORM S0/S1/S2/S3 (%) | STORM evt max (€) | STORM_CMCC S0/S1/S2/S3 (%) | STORM_CMCC evt max (€) |
|---|---:|---:|---:|---:|
| Eau AEP | S0 0,00 / S1 0,00 / S2 0,00 / S3 100,00 | 2 091 033 545,10 | S0 0,00 / S1 0,00 / S2 0,00 / S3 100,00 | 2 221 937 638,99 |
| Eau EU | S0 0,00 / S1 0,00 / S2 0,00 / S3 100,00 | 557 228 108,10 | S0 0,00 / S1 0,00 / S2 0,00 / S3 100,00 | 587 553 716,31 |
| Elec BT souterrain | S0 21,61 / S1 0,00 / S2 0,00 / S3 78,39 | 248 294 468,19 | S0 21,61 / S1 0,00 / S2 0,00 / S3 78,39 | 263 396 495,95 |
| Elec BT aerien | S0 0,94 / S1 0,00 / S2 0,00 / S3 99,06 | 323 219 321,83 | S0 0,94 / S1 0,00 / S2 0,00 / S3 99,06 | 347 849 661,63 |
| Elec HTA souterrain | S0 9,86 / S1 0,00 / S2 0,00 / S3 90,14 | 532 424 260,53 | S0 9,86 / S1 0,00 / S2 0,00 / S3 90,14 | 571 843 235,74 |
| Elec HTA aerien | S0 1,21 / S1 0,00 / S2 0,00 / S3 98,79 | 78 091 867,26 | S0 1,21 / S1 0,00 / S2 0,00 / S3 98,79 | 84 842 359,81 |

### Tableau legacy (EAI / evenement max)

| Reseau | STORM EAI (€) | STORM evt max (€) | STORM_CMCC EAI (€) | STORM_CMCC evt max (€) |
|---|---:|---:|---:|---:|
| Eau AEP | 46 979 543,35 | 2 091 033 545,10 | 45 887 934,63 | 2 221 937 638,99 |
| Eau EU | 12 362 110,97 | 557 228 108,10 | 12 037 573,74 | 587 553 716,31 |
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
