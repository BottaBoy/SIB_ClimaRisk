# Journalisation_Run_GuaMar

Journal des reruns Guadeloupe / Martinique.

Le journal brut est stocke dans `docs/Journalisation_Run_GuaMar.jsonl`.
Les identifiants de tracks sont stockes compresses en `zlib+base64` dans le journal brut.
Le pourcentage de tracks communs correspond a `|A ∩ B| / |A|` entre le run courant et le run precedent du meme territoire et du meme alea.

| Date du run | ID de session | Territoire | Alea | dynamic_max_tracks | sum(event_frequency) | n_events | % tracks communs vs run precedent | wind_pml_50 | wind_pml_100 | Track IDs compacts |
|---|---|---|---|---:|---:|---:|---:|---:|---:|---|
| 2026-04-08T14:50:03+00:00 | 2 | martinique | STORM_CMCC | 1500 | 0.150000 | 1500 | 20.00 | 613229734.96 | 762271300.57 | 1500 ids | c4e0036e9c05 | STORM_CMCC_1006_1_1006_5, STORM_CMCC_1006_1_1006_8, STORM_CMCC_1009_1_1009_6, ..., STORM_CMCC_9998_9_9998_7, STORM_CMCC_9999_9_9999_6, STORM_CMCC_9999_9_9999_7 |
| 2026-04-08T14:50:03+00:00 | 2 | martinique | STORM | 1500 | 0.150000 | 1500 | 20.00 | 686963467.63 | 828437234.03 | 1500 ids | 8d7e75cc3519 | STORM_1000_1_1000_1, STORM_1006_1_1006_6, STORM_1008_1_1008_1, ..., STORM_9998_9_9998_10, STORM_9998_9_9998_4, STORM_9_0_9_2 |
| 2026-04-08T14:42:01+00:00 | 2 | guadeloupe | STORM_CMCC | 1500 | 0.150000 | 1500 | 20.00 | 527446263.21 | 680705760.46 | 1500 ids | 486081c4bd8c | STORM_CMCC_1003_1_1003_9, STORM_CMCC_1010_1_1010_8, STORM_CMCC_1013_1_1013_6, ..., STORM_CMCC_9984_9_9984_7, STORM_CMCC_9987_9_9987_5, STORM_CMCC_9987_9_9987_6 |
| 2026-04-08T14:42:01+00:00 | 2 | guadeloupe | STORM | 1500 | 0.150000 | 1500 | 20.00 | 508112697.89 | 663127650.33 | 1500 ids | b14d15885ad3 | STORM_1010_1_1010_6, STORM_101_0_101_0, STORM_1033_1_1033_6, ..., STORM_9979_9_9979_6, STORM_9988_9_9988_7, STORM_9998_9_9998_4 |
| 2026-04-08T14:14:41+00:00 | 1 | martinique | STORM_CMCC | 300 | 0.030000 | 300 | - | 577756201.35 | 695208530.77 | 300 ids | 9b6dacebd8d3 | STORM_CMCC_1013_1_1013_1, STORM_CMCC_1032_1_1032_17, STORM_CMCC_1046_1_1046_12, ..., STORM_CMCC_994_0_994_10, STORM_CMCC_9994_9_9994_3, STORM_CMCC_9999_9_9999_6 |
| 2026-04-08T14:14:41+00:00 | 1 | martinique | STORM | 300 | 0.030000 | 300 | - | 635891102.34 | 747385587.79 | 300 ids | 074c0f8524dc | STORM_1033_1_1033_4, STORM_1055_1_1055_4, STORM_1081_1_1081_0, ..., STORM_9945_9_9945_0, STORM_9958_9_9958_2, STORM_9988_9_9988_7 |
| 2026-04-08T13:54:39+00:00 | 1 | guadeloupe | STORM_CMCC | 300 | 0.030000 | 300 | - | 520993370.83 | 668145909.98 | 300 ids | 0df9a4a23672 | STORM_CMCC_1032_1_1032_12, STORM_CMCC_1041_1_1041_10, STORM_CMCC_1065_1_1065_8, ..., STORM_CMCC_9950_9_9950_2, STORM_CMCC_9975_9_9975_11, STORM_CMCC_9982_9_9982_3 |
| 2026-04-08T13:54:39+00:00 | 1 | guadeloupe | STORM | 300 | 0.030000 | 300 | - | 501129290.30 | 652829049.06 | 300 ids | 11f9bad3f879 | STORM_101_0_101_0, STORM_1077_1_1077_2, STORM_1079_1_1079_3, ..., STORM_995_0_995_8, STORM_9979_9_9979_6, STORM_9988_9_9988_7 |

Notes:
- `ID de session` est identique pour les quatre lignes produites par un meme rerun Guadeloupe + Martinique.
- La comparaison `% tracks communs vs run precedent` se fait avec le dernier run du meme territoire et du meme alea.
- `n_events` correspond au nombre de tracks uniques journalises pour le run courant.
- `Track IDs compacts` affiche `count | sha256[0:12] | preview` ; la liste complete est stockee dans le JSONL compressé.
