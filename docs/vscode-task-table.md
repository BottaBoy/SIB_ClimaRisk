# Taches VS Code SIB

Ce document resume les taches actuellement definies dans `/home/ubuntu/.vscode/tasks.json` pour le workspace ouvert sur `/home/ubuntu`.

## Raccourcis utiles

| Usage | Raccourci | Effet |
| --- | --- | --- |
| Selectionner n'importe quelle tache | `Ctrl+Shift+P` puis `Tasks: Run Task` | Ouvre le selecteur complet de taches VS Code |
| Selectionner une tache du groupe `build` | `Ctrl+Shift+B` | Ouvre le selecteur des build tasks, car aucune build task par defaut n'est definie |
| Relancer une tache de verification | `Ctrl+Shift+P` puis `Tasks: Run Test Task` ou `Tasks: Run Task` | Pratique pour les taches du groupe `test` |

## Analyse complete

| Label | Groupe | Selection rapide | Role |
| --- | --- | --- | --- |
| `SIB: Run Complete Analysis (Default)` | `build` | `Ctrl+Shift+B` | Lance l'analyse complete standard sur les deux territoires avec `dynamic_max_tracks=1200` |
| `SIB: Run Complete Analysis (Guadeloupe Only)` | `build` | `Ctrl+Shift+B` | Lance l'analyse complete uniquement sur la Guadeloupe |
| `SIB: Run Complete Analysis (Martinique Only)` | `build` | `Ctrl+Shift+B` | Lance l'analyse complete uniquement sur la Martinique |
| `SIB: Run Complete Analysis (No Deploy)` | `build` | `Ctrl+Shift+B` | Lance l'analyse complete sans phase de deploiement |
| `SIB: Resume Latest Complete Analysis (No Deploy)` | `build` | `Ctrl+Shift+B` | Reprend le dernier run complet archive sans deploy |
| `SIB: Run Complete Analysis (Fast: 800 tracks)` | `build` | `Ctrl+Shift+B` | Variante plus rapide avec `dynamic_max_tracks=800` |
| `SIB: Run Complete Analysis (Very Fast: 150 tracks)` | `build` | `Ctrl+Shift+B` | Variante tres rapide avec `dynamic_max_tracks=150` |
| `SIB: Run Complete Analysis (Rich: 1500 tracks)` | `build` | `Ctrl+Shift+B` | Variante plus riche avec `dynamic_max_tracks=1500` |
| `SIB: Monitor Complete Analysis Run` | `build` | `Ctrl+Shift+B` | Suit l'etat du manifest du run complet en cours |

## Frontend, publication et deploy

### Choix de la bonne tache

Cas 1. Publication standard du dernier run pour les deux territoires.

- Utiliser `SIB: Snapshot Latest Run Web Artefacts`.
- Puis utiliser `SIB: Deploy Archived Latest Run (sib.dev alias -> shared root)`.
- C'est le chemin recommande: on publie l'archive du dernier run, pas seulement l'etat courant de `web/`.
- Avant deploy, verifier sur la webapp le badge `Trace:` et le toggle `Afficher le quadrillage des cartes` sur `page1`/`page2`.
- Apres snapshot, verifier dans `outputs/complete-analysis-runs/<run_id>/manifest.json` le bloc `archived_frontend_validation.publication_trace`.

Cas 2. Publication d'un ancien run archive.

- Il n'y a pas de tache VS Code dediee pour saisir un `run_id` arbitraire.
- Utiliser la commande `cd /home/ubuntu/sib-work && /home/ubuntu/sib-work/backend/.venv/bin/python scripts/deploy_only.py --run-id <run_id> --vhost sib.dev.elio.bottagisio.com`.
- Si les artefacts frontend de ce run n'ont jamais ete snapshottes dans l'archive, les produire d'abord avec `scripts/snapshot_run_web_artifacts.py --run-id <run_id>`.

Cas 3. Publication Guadeloupe seule.

- Utiliser `SIB: Prepare Latest Run Publication (Guadeloupe Only)` pour rebuild + snapshot Guadeloupe.
- Puis utiliser `SIB: Deploy Archived Latest Run (Guadeloupe Only -> sib.dev alias)`.
- Ce chemin laisse les artefacts Martinique du live inchanges.
- Si le profil publication-safe active les fallbacks web, les logs du rebuild doivent contenir `fallback_proxy=true ...` et `fallback_page_analysis=true ...`.

| Label | Groupe | Selection rapide | Role |
| --- | --- | --- | --- |
| `SIB: Rebuild Frontend Artefacts (Guadeloupe Only)` | `build` | `Ctrl+Shift+B` | Regenerer les artefacts frontend publication-safe pour la Guadeloupe |
| `SIB: Rebuild Frontend Artefacts (Both Territories)` | `build` | `Ctrl+Shift+B` | Regenerer les artefacts frontend pour Guadeloupe et Martinique |
| `SIB: Rebuild Frontend + Deploy (Guadeloupe Only)` | `build` | `Ctrl+Shift+B` | Rebuild frontend Guadeloupe puis deploie sur la racine partagee live |
| `SIB: Prepare Latest Run Publication (Guadeloupe Only)` | `build` | `Ctrl+Shift+B` | Rebuild publication-safe puis snapshotte les artefacts du dernier run Guadeloupe |
| `SIB: Snapshot Latest Run Web Artefacts` | `build` | `Ctrl+Shift+B` | Archive les artefacts web du dernier run pour les deux territoires et controle `meta.publication_trace` |
| `SIB: Snapshot Latest Run Web Artefacts (Guadeloupe Only)` | `build` | `Ctrl+Shift+B` | Archive les artefacts web du dernier run uniquement pour la Guadeloupe et controle `meta.publication_trace` |
| `SIB: Deploy Only (Live shared root)` | `build` | `Ctrl+Shift+B` | Deploie le contenu web actuel sur `sib.shared.elio.dev` |
| `SIB: Deploy Only (Both labels, deduped)` | `build` | `Ctrl+Shift+B` | Deploie une seule fois vers les deux labels nginx dedoublonnes |
| `SIB: Deploy Archived Latest Run (sib.dev alias -> shared root)` | `build` | `Ctrl+Shift+B` | Deploie les artefacts archives du dernier run via l'alias `sib.dev` |
| `SIB: Deploy Archived Latest Run (Guadeloupe Only -> sib.dev alias)` | `build` | `Ctrl+Shift+B` | Deploie seulement les artefacts archives Guadeloupe du dernier run |

## Graphs

Les taches ci-dessous ciblent automatiquement le dernier run complet avec succes et ecrivent les sorties dans `outputs/Graphs/<run_id>/`.

| Label | Groupe | Selection rapide | Role |
| --- | --- | --- | --- |
| `SIB: Generate Run Graphs (Latest Success - HTML)` | `build` | `Ctrl+Shift+B` | Genere l'index HTML interactif des graphes du dernier run complet avec succes |
| `SIB: Export Run Graphs (Latest Success - PNG)` | `build` | `Ctrl+Shift+B` | Exporte en PNG le pack de graphes du dernier run complet avec succes |

## Verification et journaux

| Label | Groupe | Selection rapide | Role |
| --- | --- | --- | --- |
| `SIB: View Run Logs (Markdown)` | `test` | `Ctrl+Shift+P` puis `Tasks: Run Task` | Affiche le journal Markdown des runs |
| `SIB: View Run Logs (JSONL - Pretty)` | `test` | `Ctrl+Shift+P` puis `Tasks: Run Task` | Affiche le journal JSONL des runs |
| `SIB: Check Latest Deployment` | `test` | `Ctrl+Shift+P` puis `Tasks: Run Task` | Compare les dates/meta des artefacts locaux et de ceux servis par nginx |

Controle publication recommande:

- `manifest.json`: inspecter `territories.<territory>.archived_frontend_validation.publication_trace` et `publication_fallback_present`.
- Logs rebuild frontend: rechercher `fallback_proxy=true` et `fallback_page_analysis=true`.
- Web `page1`/`page2`: verifier le badge `Trace:` et le toggle `Afficher le quadrillage des cartes`.

## Sensibilite

| Label | Groupe | Selection rapide | Role |
| --- | --- | --- | --- |
| `SIB: Export Sensitivity Workbook` | `build` | `Ctrl+Shift+B` | Extrait le classeur Excel de sensibilite et regenere le pack de scenarios JSON |
| `SIB: List Sensitivity Scenarios` | `test` | `Ctrl+Shift+P` puis `Tasks: Run Task` | Liste les IDs de scenarios disponibles dans le pack par defaut |
| `SIB: Run Sensitivity Analysis (Default Pack)` | `build` | `Ctrl+Shift+B` | Lance toute la campagne Guadeloupe du pack de scenarios par defaut |
| `SIB: Run Sensitivity Analysis (Custom Scenario IDs)` | `build` | `Ctrl+Shift+B` | Lance seulement les scenarios saisis dans l'invite `sibSensitivityScenarioIds` |
| `SIB: Resume Latest Sensitivity Analysis` | `build` | `Ctrl+Shift+B` | Reprend le dernier parent run de sensibilite archive |
| `SIB: Monitor Sensitivity Analysis Run` | `build` | `Ctrl+Shift+B` | Suit l'avancement du parent manifest de sensibilite |

## Note pratique

Pour la tache `SIB: Run Sensitivity Analysis (Custom Scenario IDs)`, VS Code affiche une invite. Les IDs doivent etre saisis separes par des virgules, par exemple:

`runoff_coeff-0p15,territory_grid_deg-0p10`