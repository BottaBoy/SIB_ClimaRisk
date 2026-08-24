# SIB Complete Analysis Runner

Script Python pour exécuter la pipeline d'analyse complète du risque cyclonique sur les infrastructures (eau + électricité) en Guadeloupe, Martinique et Saint-Barthélemy, avec support pour:

- 🎛️ **Configuration dynamique**: Ajuster `dynamic_max_tracks` pour contrôler la richesse de l'analyse
- 🧩 **Exécution shardée**: Découpage automatique des points CLIMADA selon un budget mémoire pour éviter les `MemoryError` sur les runs lourds
- 📊 **Multi-territoire**: Lancer les runs pour Guadeloupe, Martinique, Saint-Barthélemy, `both` (GUA+MTQ) ou `all` (GUA+MTQ+BLM)
- 📝 **Journalisation automatique**: Logs en markdown + JSONL pour suivi et audit
- 📁 **Manifeste de run**: Suivi détaillé par territoire / aléa / composant / shard dans `outputs/complete-analysis-runs/`
- 🚀 **Déploiement automatique**: Résultats déployés automatiquement sur le serveur web après succès
- ⏱️ **Tracking**: Suivi de la progression avec timestamps

## Prérequis

### Dépendances Python

Le script nécessite que l'environnement Python du projet soit configuré avec:

```bash
cd /home/ubuntu/sib-work
# Installer les dépendances (dans l'environnement Python du projet)
pip install -e .
```

Dépendances clés requises:
- `geopandas` - Lecture des données géospatiales (GeoJSON, GeoPackage, Shapefile)
- `shapely` - Opérations géométriques
- `climada` - Calcul des impacts cycloniques
- `rasterio` - Support rasters (WorldPop population data)

### Données d'exposition

Le script s'attend à trouver les données d'infrastructure aux emplacements standard:

```
/home/ubuntu/uploads/Infra_Elec_Guadeloupe/    # Lignes électriques
/home/ubuntu/uploads/Infra_Elec_Martinique/
/home/ubuntu/uploads/Infra_elec_Saint_Barthelemy/
/home/ubuntu/uploads/Infra_Eau_Guadeloupe/     # Réseaux d'eau
/home/ubuntu/uploads/Infra_Eau_Martinique/
/home/ubuntu/uploads/Infra_eau_Saint_Barthelemy/
/home/ubuntu/uploads/Population/                # Données population WorldPop
```

### Données aléa (Hazards)

Les données de hazard STORM/STORM_CMCC doivent exister selon la configuration dans `config.py`:

```
/home/ubuntu/sib-work/data/hazards/tc_hazard_guadeloupe.h5
/home/ubuntu/sib-work/data/hazards/tc_hazard_guadeloupe_CMCC.h5
/home/ubuntu/sib-work/data/hazards/tc_hazard_martinique.h5
/home/ubuntu/sib-work/data/hazards/tc_hazard_martinique_CMCC.h5
```

Notes Saint-Barthélemy:
- le runner complet accepte `--territories stb` pour un run dédié;
- `both` reste strictement `guadeloupe + martinique`;
- `all` ajoute Saint-Barthélemy au périmètre historique;
- le zonage AEP Saint-Barthélemy est `best-effort` et le zonage EU est explicitement `heuristic_topological_non_validated`;
- le bundle hydraulique attendu est `outputs/hydraulic_zoning/Zonage_V2/saint-barthelemy_water_systems_estimate.gpkg`.

Publication web scientifique:
- chaque territoire publie maintenant `web/data/<territory>-scientific-web-summary.json`
- ce payload est derive uniquement du `complete-analysis.json` publie
- il sert de source web prioritaire pour les chiffres scientifiques du site
- le contrat public V4 impose `complete_analysis.scientific_graph_inputs.scenarios == ["rp10", "rp50", "rp100", "rp1000"]`
- `build_scientific_web_summary.py` ne reconstruit plus jamais les inputs scientifiques en silence: un run V4 doit deja contenir `scientific_graph_inputs` strict avant publication
- pour un ancien run archive seulement, la reparation lourde reste disponible avec `--repair-legacy-scientific-inputs`
- la fin de run execute maintenant les phases bloquantes `scientific_publication` puis `graphs`; un run guadeloupe-only ne finit en `success` que si le complete-analysis, le scientific summary et les graphes sont complets
- `page-analysis` reste un adaptateur legacy optionnel; il ne definit plus la validite scientifique du run sauf si `--require-legacy-web` est explicitement passe
- les artefacts `wind-maps`, `landslide-maps`, `multi-hazard-proxy`, `page-analysis`, `network-states.geojson` restent necessaires pour les cartes et certains blocs legacy
- le detail exact de ce qui est deja rebascule ou non est documente dans `docs/note-backend-calculatoire.md`

## Utilisation

### Lancer un run complet (par défaut)

```bash
cd /home/ubuntu/sib-work
python3 scripts/run_complete_analysis.py
```

**Ce qui se passe:**
1. Lance l'analyse pour Guadeloupe (exposition → impacts → social impacts)
2. Lance l'analyse pour Martinique
3. Exporte les résultats JSON dans `web/data/`
4. Déploie automatiquement les résultats sur `sib.dev.elio.bottagisio.com`
5. Journalise tout dans `docs/Journalisation_Run_CompleteAnalysis.{md,jsonl}`
6. Écrit aussi un manifeste temps réel dans `outputs/complete-analysis-runs/latest-manifest.json`
7. **Durée estimée: 40-45 minutes**

### Budget mémoire et shards d'exposition

```bash
# Budget mémoire par composant CLIMADA (default: 6 GiB)
python3 scripts/run_complete_analysis.py --memory-budget-gb 6

# Forcer un cap explicite sur le nombre de points par shard
python3 scripts/run_complete_analysis.py --max-points-per-shard 6000

```

Par défaut, le runner complet active un profil `complete-analysis` strict:

- les points CLIMADA sont shardés automatiquement si nécessaire
- un échec d'un composant éligible `rain` ou `surge` fait échouer le territoire
- le suivi détaillé se fait via le manifeste de run plutôt qu'uniquement via les JSON finaux

### Reprendre un run interrompu

```bash
# Reprendre le dernier run connu via le manifeste latest-manifest.json
python3 scripts/run_complete_analysis.py --resume-run-id latest --no-deploy

# Reprendre un run précis
python3 scripts/run_complete_analysis.py --resume-run-id 20260415_101530 --no-deploy

# Reprendre avec un cap de shard plus agressif pour terminer un run OOM
python3 scripts/run_complete_analysis.py --resume-run-id latest --no-deploy --max-points-per-shard 1500
```

En mode reprise:

- les territoires déjà exportés avec succès sont sautés
- les shards déjà checkpointés sont rechargés au lieu d'être recalculés
- les plans de split déclenchés après `MemoryError` sont réutilisés
- les checkpoints sont stockés sous `outputs/complete-analysis-runs/<run_id>/territories/<territory>/checkpoints/`

Robustesse des interruptions:

- `SIGINT` et `SIGTERM` arrêtent proprement le run et marquent le manifeste comme interrompu
- `SIGHUP` est ignoré par défaut pour éviter qu'une simple déconnexion du terminal ne casse un calcul long
- si tu veux que `SIGHUP` reste fatal, lance le script avec `--abort-on-sighup`

### Reprise sûre recommandée

Pour éviter les erreurs de relance manuelle et les doublons de process, utilise le lanceur sûr:

```bash
cd /home/ubuntu/sib-work
python3 scripts/resume_complete_analysis_safe.py --run-id 20260611_075636
```

Ce lanceur:

- refuse de démarrer si un process du même `run_id` tourne déjà
- infère automatiquement le `max_points_per_shard` depuis les checkpoints existants
- lance le job en session détachée avec `PYTHONUNBUFFERED=1`
- écrit un `pidfile` dans `outputs/complete-analysis-runs/<run_id>/resume.pid`

Pour tuer ensuite ce run de façon ciblée:

```bash
kill $(cat /home/ubuntu/sib-work/outputs/complete-analysis-runs/20260611_075636/resume.pid)
```

### Babysitter robuste

Pour superviser un run précis en continu, avec relance automatique si le process disparaît ou si le manifeste bascule en échec:

```bash
cd /home/ubuntu/sib-work
backend/.venv/bin/python scripts/babysit_complete_analysis_run.py \
  --run-id 20260611_075636 \
  --poll-seconds 60 \
  --stale-after-minutes 20 \
  --silent-hang-after-minutes 30 \
  --restart-delay-seconds 30
```

Le babysitter:

- suit un seul `run_id`
- imprime des check-ups horodatés dans le terminal
- prend la main sur tout ancien babysitter encore vivant sur le même `run_id`
- relance toujours via `scripts/resume_complete_analysis_safe.py`
- réutilise les shards déjà calculés
- s'arrête dès que le run passe en `success`
- écrit et relit `outputs/complete-analysis-runs/<run_id>/resume.pid`
- peut aussi tuer et relancer un run qui reste silencieux trop longtemps, par défaut au bout de 30 minutes

Si tu préfères passer par VS Code, utilise la tâche `SIB: Babysit Complete Analysis Run`.

### Personnaliser `dynamic_max_tracks`

```bash
# Utiliser 1500 tracks au lieu des 1200 par défaut (plus riche, plus long)
python3 scripts/run_complete_analysis.py --dynamic-max-tracks 1500

# Utiliser 800 tracks (plus rapide, moins riche)
python3 scripts/run_complete_analysis.py --dynamic-max-tracks 800
```

**Note:** `dynamic_max_tracks` contrôle le nombre de traces de cyclones synthétiques utilisées dans le calcul d'impact. Plus élevé = résultats plus précis mais plus lent.

### Analyser un seul territoire

```bash
# Guadeloupe seulement
python3 scripts/run_complete_analysis.py --territories gua

# Martinique seulement
python3 scripts/run_complete_analysis.py --territories mar

# Saint-Barthélemy seulement
python3 scripts/run_complete_analysis.py --territories stb

# Périmètre historique inchangé
python3 scripts/run_complete_analysis.py --territories both

# Trois territoires explicites
python3 scripts/run_complete_analysis.py --territories all
```

### Tester sans déployer

```bash
# Lancer l'analyse complète mais NE PAS déployer les résultats
python3 scripts/run_complete_analysis.py --no-deploy

# Utile pour tester avant un déploiement en production
```

### Combiner les options

```bash
# Analyser Guadeloupe avec 1500 tracks, sans déployer
python3 scripts/run_complete_analysis.py --territories gua --dynamic-max-tracks 1500 --no-deploy

# Dry-run recommandé Saint-Barthélemy
python3 scripts/run_complete_analysis.py --territories stb --dynamic-max-tracks 150 --no-deploy

# Analyser les deux avec 800 tracks, avec déploiement
python3 scripts/run_complete_analysis.py --dynamic-max-tracks 800
```

## Sortie attendue

### Console (affichage en temps réel)

```
============================================================
SIB Complete Analysis Runner
Parameters: dynamic_max_tracks=1200, territories=['guadeloupe', 'martinique']
============================================================
[16:45:22] INFO: Starting analysis for GUADELOUPE...
[16:45:23] INFO: Loading exposure data...
[16:47:15] INFO: ✓ Loaded 3485 assets in 112.4s
[16:47:15] INFO: Computing disaggregation...
[16:47:18] INFO: ✓ Disaggregation complete - 800 sample points
[16:47:18] INFO: Computing impacts (dynamic_max_tracks=1200)...
[16:50:42] INFO: ✓ Impact computation complete in 204.3s
[16:50:42] INFO:   EAI STORM: 12,300,000 EUR
[16:50:42] INFO:   EAI STORM_CMCC: 13,100,000 EUR
[16:50:42] INFO: Exporting results...
[16:50:45] INFO: ✓ Results exported to guadeloupe-complete-analysis.json
[16:50:45] INFO: Starting analysis for MARTINIQUE...
...
[17:20:30] INFO: Deploying to sib.dev.elio.bottagisio.com...
[17:20:45] INFO: ✓ Deployment successful
============================================================
Run complete. Logs written to:
  /home/ubuntu/sib-work/docs/Journalisation_Run_CompleteAnalysis.md
  /home/ubuntu/sib-work/docs/Journalisation_Run_CompleteAnalysis.jsonl
============================================================
```

### Fichiers de journalisation

#### Markdown (`docs/Journalisation_Run_CompleteAnalysis.md`)

Format lisible pour humans:

```markdown
## Run [2026-04-13 16:45:22]
**Run ID**: `20260413_164522`

### Guadeloupe
- Assets loaded: 3485
- EAI: 12,300,000 EUR
- Status: ✓ Complete

### Martinique
- Assets loaded: 2145
- EAI: 8,700,000 EUR
- Status: ✓ Complete

**Total Duration**: 2145s (35.7m)
```

#### JSONL (`docs/Journalisation_Run_CompleteAnalysis.jsonl`)

Format structuré pour parsing automatisé:

```jsonl
{"timestamp":"2026-04-13T16:45:22Z","run_id":"20260413_164522","phase":"start","status":"initiated","dynamic_max_tracks":1200,"territories":["guadeloupe","martinique"]}
{"timestamp":"2026-04-13T16:47:15Z","run_id":"20260413_164522","phase":"load_exposure","territory":"guadeloupe","asset_count":3485,"duration_seconds":112,"status":"complete"}
{"timestamp":"2026-04-13T16:50:42Z","run_id":"20260413_164522","phase":"impacts","territory":"guadeloupe","eai_eur":12300000,"eai_cmcc_eur":13100000,"duration_seconds":204,"status":"complete"}
...
{"timestamp":"2026-04-13T17:20:45Z","run_id":"20260413_164522","phase":"complete","status":"success","duration_seconds":2145,"territories_completed":2,"total_assets":5630,"deployed":true}
```

## Résultats

### Fichiers générés

```
web/data/
├── guadeloupe-complete-analysis.json    # Résultat complet avec impacts
├── martinique-complete-analysis.json
├── guadeloupe-page1-analysis.json      # Dashboard data
├── martinique-page1-analysis.json
├── guadeloupe-network-states.geojson   # États des réseaux (S0-S3)
└── martinique-network-states.geojson
```

### Contenu des résultats JSON

Chaque fichier `{territory}-complete-analysis.json` contient:

```json
{
  "meta": {
    "title": "Guadeloupe Complete Water+Electric Cyclone Risk",
    "engine": "climada_with_interdependency_v1",
    "case_study_territory": "guadeloupe"
  },
  "exposure_summary": {
    "asset_count_original": 3485,
    "total_exposure_eur": 2500000000.00,
    "asset_type_counts": { "elec_bt_aerien": 120, "eau_reseau": 450, ... }
  },
  "portfolio_results": {
    "storm": {
      "eai_eur": 12300000.00,
      "eai_direct_eur": 8900000.00,
      "eai_indirect_eur": 3400000.00
    },
    "storm_cmcc": { ... },
    "social_impact_summary": {
      "storm": {
        "total_population_affected_any_network": 123456,
        "total_without_elec": 45000,
        "total_without_water_aep": 32000,
        ...
      }
    }
  },
  "territory_results": [
    {
      "territory_id": "cell-+16.20_-061.40",
      "population_total": 5000,
      "eai_storm_eur": 123400.50,
      "social_metrics": {
        "storm": {
          "population_with_degraded_elec": 2500,
          "population_without_elec": 500,
          "total_population_affected": 5000
        }
      }
    }
  ]
}
```

## Monitoring de la progression

Pendant l'exécution:

```bash
# Terminal 1: Lancer le run
cd /home/ubuntu/sib-work
python3 scripts/run_complete_analysis.py

# Terminal 2: Suivre le manifeste opérateur en temps réel
/home/ubuntu/sib-work/backend/.venv/bin/python scripts/monitor_run.py

# Terminal 3: Vérifier l'event log structuré
tail -f /home/ubuntu/sib-work/docs/Journalisation_Run_CompleteAnalysis.jsonl | jq .
```

Le manifeste temps réel principal est écrit dans:

```bash
/home/ubuntu/sib-work/outputs/complete-analysis-runs/latest-manifest.json
```

Chaque run garde aussi son propre manifeste versionné dans:

```bash
/home/ubuntu/sib-work/outputs/complete-analysis-runs/<run_id>/manifest.json
```

## Dépannage

### Erreur: "ModuleNotFoundError: No module named 'geopandas'"

**Solution:** Installer les dépendances du projet:

```bash
cd /home/ubuntu/sib-work
pip install -e .
# ou
pip install geopandas shapely climada rasterio
```

### Erreur: "File not found" pour données d'exposition

**Vérifier:** Les fichiers d'infrastructure existent aux emplacements attendus:

```bash
ls /home/ubuntu/uploads/Infra_Elec_Guadeloupe/*.geojson
ls /home/ubuntu/uploads/Infra_Eau_Guadeloupe/AEP/*.gpkg
```

### Le run est très lent

C'est normal! Les étapes principales:

- **Load exposure** (2-3 min): Lecture et normalization des données
- **Impact computation** (3-5 min par territoire): Édition CLIMADA large
- **Deployment** (1 min): Sync SSH vers serveur web

**Total: 40-50 minutes pour Gua+Mar est normal.**

Pour accélérer: utiliser `--dynamic-max-tracks 800` (moins de précision, ~30% plus rapide)

Si le run a déjà produit plusieurs shards avant interruption, préférer `--resume-run-id latest` plutôt qu'un redémarrage complet.

### Vérifier le déploiement

```bash
# Après un run avec déploiement
curl -kI https://sib.dev.elio.bottagisio.com/data/guadeloupe-complete-analysis.json

# Doit retourner:
# HTTP/1.1 200 OK
# Content-Type: application/json
```

## Intégration VS Code

Vous pouvez lancer directement depuis VS Code:

1. Ouvrir Terminal intégré: **Ctrl+`** (ou View → Terminal)
2. Taper: `python3 scripts/run_complete_analysis.py --dynamic-max-tracks 1200`
3. Observer la progression affichée
4. Les résultats seront déployés automatiquement après succès
5. Consulter les logs: `cat docs/Journalisation_Run_CompleteAnalysis.md`

Les tâches workspace incluent aussi désormais:

1. un lancement standard avec budget mémoire
2. un suivi via `scripts/monitor_run.py`
3. une reprise du dernier run via `--resume-run-id latest`

## Architecture interne

Le script orchestrait:

1. **RunLogger** - Gère la journalisation dual (markdown + JSONL)
2. **build_complete_exposure()** - Charge toutes les données infrastructure
3. **compute_impacts()** - Exécute CLIMADA + interdependency + social impacts
4. **deploy_results()** - Déploie vers le serveur web

Chaque étape est encapsulée avec gestion d'erreurs et logging détaillé.

## Pour plus d'infos

- Configuration: Voir `backend/app/config.py`
- Expositions: Voir `scripts/case_study_sources.py`
- Pipeline d'impacts: Voir `backend/app/risk_engine/`
