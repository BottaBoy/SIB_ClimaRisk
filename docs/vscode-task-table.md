# Taches VS Code SIB

Ce document resume les taches actuellement definies dans [tasks.json](/home/ubuntu/.vscode/tasks.json) pour le workspace VS Code ouvert sur [home/ubuntu](/home/ubuntu). Les commandes ciblees executent ensuite les scripts du depot [sib-work](/home/ubuntu/sib-work).

## Raccourcis utiles

| Usage | Raccourci | Effet |
| --- | --- | --- |
| Lancer une tache du groupe `build` | `Ctrl+Shift+B` | Ouvre le selecteur des build tasks du depot |
| Lancer n'importe quelle tache | `Ctrl+Shift+P` puis `Tasks: Run Task` | Ouvre le selecteur complet des taches |
| Relancer la derniere tache | `Ctrl+Shift+P` puis `Tasks: Rerun Last Task` | Relance rapidement la derniere tache executee |

## Analyse complete

| Label | Groupe | Selection rapide | Role |
| --- | --- | --- | --- |
| `SIB: Resume Latest Complete Analysis (No Deploy)` | `build` | `Ctrl+Shift+B` | Reprend le dernier run complet archive sans deploy, avec `dynamic_max_tracks=1200` et `memory_budget_gb=6` |
| `SIB: Run Complete Analysis (Guadeloupe Only)` | `build` | `Ctrl+Shift+B` | Lance la chaine complete uniquement pour la Guadeloupe avec `dynamic_max_tracks=1200` |
| `SIB: Run Complete Analysis (Martinique Only)` | `build` | `Ctrl+Shift+B` | Lance la chaine complete uniquement pour la Martinique avec `dynamic_max_tracks=1200` |
| `SIB: Run Complete Analysis (No Deploy)` | `build` | `Ctrl+Shift+B` | Lance la chaine complete sur les deux territoires sans deploy avec `dynamic_max_tracks=1200` |
| `SIB: Run Complete Analysis (Fast: 800 tracks)` | `build` | `Ctrl+Shift+B` | Variante plus rapide avec `dynamic_max_tracks=800` |
| `SIB: Run Complete Analysis (Very Fast: 150 tracks)` | `build` | `Ctrl+Shift+B` | Variante de validation rapide avec `dynamic_max_tracks=150` et `--no-deploy` |
| `SIB: Run Complete Analysis (Rich: 1500 tracks)` | `build` | `Ctrl+Shift+B` | Variante plus riche avec `dynamic_max_tracks=1500` |
| `SIB: Monitor Complete Analysis Run` | `build` | `Ctrl+Shift+B` | Suit l'etat du manifest du run complet en cours |
| `SIB: Run Complete Analysis (Full Tracks: Guadeloupe + Martinique, No Deploy)` | `build` | `Ctrl+Shift+B` | Lance la chaine complete Guadeloupe + Martinique sans deploy avec `--dynamic-max-tracks 0`, donc sans cap sur les tracks dynamiques |

Notes d'audit:

- La tache `Full Tracks: Guadeloupe + Martinique` existe bien dans [tasks.json](/home/ubuntu/.vscode/tasks.json#L139).
- Elle est coherente avec le contrat runtime actuel: `--dynamic-max-tracks 0` signifie bien `full tracks` pour la chaine complete, tout en gardant `--no-deploy` par securite operateur.

La tache `SIB: Run Complete Analysis (Default)` a ete retiree du workspace racine. Elle ne doit plus etre utilisee.

## Analyse comparative des aleas

| Label | Groupe | Selection rapide | Role |
| --- | --- | --- | --- |
| `SIB: Run Hazard Comparison (300 tracks)` | `build` | `Ctrl+Shift+B` | Lance la chaine comparative hazard-only avec `dynamic_max_tracks=300` |
| `SIB: Run Hazard Comparison (1500 tracks)` | `build` | `Ctrl+Shift+B` | Lance la chaine comparative hazard-only avec `dynamic_max_tracks=1500` |
| `SIB: Run Hazard Comparison (Full Tracks)` | `build` | `Ctrl+Shift+B` | Lance la chaine comparative hazard-only avec `--dynamic-max-tracks 0`, donc sans cap de tracks |
| `SIB: Monitor Hazard Comparison Run` | `build` | `Ctrl+Shift+B` | Suit `outputs/hazard-comparison-runs/latest-manifest.json` et affiche la progression du run comparatif en cours |
| `SIB: Babysit Hazard Comparison Run` | `build` | `Ctrl+Shift+B` | Suit le run hazard-comparison et le relance si besoin via `tmux`, avec la session `babysit-hazard-comparison-<run_id>` |

Notes d'audit:

- Les trois taches de lancement demandees existent bien dans [tasks.json](/home/ubuntu/.vscode/tasks.json#L157).
- La tache de monitoring existe egalement dans [tasks.json](/home/ubuntu/.vscode/tasks.json#L247).
- Depuis l'audit du 2026-05-22, `300`, `1500` et `0` representent bien trois regimes numeriques differents sur la chaine comparative. Le bug legacy qui sous-comptait les cyclones sur `track_id` seul a ete corrige.
- Le point de lecture operateur apres un run comparatif reste `outputs/hazard-comparison-runs/<run_id>/comparison-exports/index.html`.

Ordre d'utilisation pour un run comparatif et ses graphes:

1. Lancer une seule tache de comparaison parmi `SIB: Run Hazard Comparison (300 tracks)`, `SIB: Run Hazard Comparison (1500 tracks)` ou `SIB: Run Hazard Comparison (Full Tracks)`.
2. Lancer `SIB: Monitor Hazard Comparison Run` si vous voulez suivre le run sans ouvrir le manifest genere a la main.
3. Il n'y a pas de seconde tache VS Code a lancer pour les graphes de ce run comparatif: la meme commande execute les phases 5 et 6 et genere automatiquement les PNG, les JSON de graphes, les CSV et le rapport HTML.

Ou sont generes les graphes comparatifs:

- Rapport HTML: `outputs/hazard-comparison-runs/<run_id>/comparison-exports/index.html`
- PNG: `outputs/hazard-comparison-runs/<run_id>/comparison-exports/charts/*.png`
- Payloads JSON: `outputs/hazard-comparison-runs/<run_id>/comparison-exports/charts/*.json`
- Tables CSV: `outputs/hazard-comparison-runs/<run_id>/comparison-exports/tables/*.csv`

Attention: `outputs/hazard-comparison-runs/latest-manifest.json` est un fichier genere et reecrit pendant le run. Si vous l'ouvrez puis essayez de l'enregistrer pendant qu'une comparaison tourne, VS Code peut afficher `Failed to save 'latest-manifest.json': The content of the file is newer...`. Cela ne bloque pas le run lui-meme; il faut simplement eviter d'editer ce manifest et preferer la tache `SIB: Monitor Hazard Comparison Run`.

Attention: les taches `SIB: Generate Run Graphs (Latest Success - HTML)` et `SIB: Export Run Graphs (Latest Success - PNG)` documentees plus bas concernent les runs de la chaine complete, pas la chaine comparative hazard-only.

## Frontend, snapshot et deploy

| Label | Groupe | Selection rapide | Role |
| --- | --- | --- | --- |
| `SIB: Rebuild Frontend Artefacts (Guadeloupe Only)` | `none` | `Tasks: Run Task` | Regenere `web/data` pour la Guadeloupe a partir des payloads locaux de complete-analysis. La tache cree une nouvelle session frontend `guamar_session_<timestamp>` et un `case_study_run_id` de territoire. |
| `SIB: Rebuild Frontend Artefacts (Guadeloupe + Martinique)` | `none` | `Tasks: Run Task` | Regenere `web/data` pour les deux territoires avec les caps frontend habituels (`proxy=100`, `map=300`) et le cap `page_component_light` resolu depuis les complete-analysis locaux. |
| `SIB: Rebuild Frontend Artefacts (Selected Run)` | `none` | `Tasks: Run Task` | Regenere `web/data` a partir des `complete-analysis.json` archives du `run_id` saisi, puis snapshotte automatiquement les artefacts reconstruits dans ce meme run. Accepte un `run_id` exact, `latest` ou `latest-success`. |
| `SIB: Snapshot Latest Run Web Artefacts` | `none` | `Tasks: Run Task` | Valide l'etat courant de `web/data`, puis le copie dans l'archive du dernier run complete-analysis resolu par `latest` sous `outputs/complete-analysis-runs/<run_id>/territories/.../web/`. |
| `SIB: Snapshot Latest Run Web Artefacts (Guadeloupe Only)` | `none` | `Tasks: Run Task` | Meme operation, limitee a la Guadeloupe. Utile pour rattacher un rebuild frontend local a l'archive d'un run precis sans toucher l'autre territoire. |
| `SIB: Snapshot Run Web Artefacts (Selected Run)` | `none` | `Tasks: Run Task` | Meme validation et archivage, mais pour le `run_id` saisi dans l'invite. Accepte un `run_id` exact, `latest` ou `latest-published`. |
| `SIB: Deploy Only (sib.shared.elio.dev)` | `none` | `Tasks: Run Task` | Deploie l'etat web courant vers `sib.shared.elio.dev` |
| `SIB: Deploy Only (Both Servers)` | `none` | `Tasks: Run Task` | Deploie l'etat web courant vers les deux serveurs configures |
| `SIB: Deploy Archived Latest Run (sib.dev.elio.bottagisio.com)` | `none` | `Tasks: Run Task` | Deploie les artefacts archives du dernier run publie vers l'alias `sib.dev.elio.bottagisio.com` |
| `SIB: Deploy Archived Latest Run (Guadeloupe Only -> sib.dev.elio.bottagisio.com)` | `none` | `Tasks: Run Task` | Deploie uniquement les artefacts archives Guadeloupe du dernier run publie |

Enchainement recommande apres un rebuild frontend local:

1. Lancez une tache `Rebuild Frontend Artefacts ...` pour regenerer l'etat courant de `web/data`.
2. Lancez ensuite `SIB: Snapshot Latest Run Web Artefacts` ou `SIB: Snapshot Run Web Artefacts (Selected Run)` pour figer cet etat courant dans l'archive du run complete-analysis cible.
3. Lancez enfin une tache `Deploy Archived ...` si vous voulez deployer cette archive figee, reproductible, et rattachee au `run_id` de complete-analysis.

Cas particulier utile pour reparer un run archive exploitable par les graphes:

1. Lancez `SIB: Rebuild Frontend Artefacts (Selected Run)`.
2. Saisissez le `run_id` exact du run a reparer, ou `latest` / `latest-success`.
3. La tache rebuild les artefacts frontend depuis le `complete-analysis.json` archive de ce run, puis les snapshotte automatiquement dans l'archive du meme run.
4. Une fois termine, les taches `Generate/Export Run Graphs (Selected Run)` peuvent reutiliser ce run sans fallback vers `web/data`.

Ce que signifie "snapshotter" ici:

- Le script ne fait pas une simple copie aveugle. Il verifie les fichiers requis du territoire, la presence d'un `case_study_run_id` coherent, les timestamps, les `publication_trace`, et les contrats GeoJSON avant d'archiver.
- Le snapshot rattache donc un rebuild frontend recent a un `complete_analysis_run_id` archive. C'est ce lien qui permet ensuite aux taches de graphes ou de deploy archives de travailler sur un run stable.
- Si un run etait `partial` uniquement parce que le rebuild frontend n'etait pas archive correctement, le snapshot peut aussi remettre a jour le manifest et requalifier la partie `frontend_artifacts` en `complete`.

Semantique des identifiants apres un rebuild frontend:

- `complete_analysis_run_id` designe le run source de la chaine complete, par exemple `20260527_160919`.
- `session_run_id` designe la session de rebuild frontend courante, par exemple `guamar_session_20260528T081450Z`.
- `case_study_run_id` designe le rerun frontend d'un territoire, par exemple `guadeloupe_case_20260528T082203Z`.
- Le journal [docs/Journalisation_Run_GuaMar.md](/home/ubuntu/sib-work/docs/Journalisation_Run_GuaMar.md) affiche l'`ID de session`, donc `guamar_session_*`, pas le `complete_analysis_run_id`.

## Graphs de la chaine complete

| Label | Groupe | Selection rapide | Role |
| --- | --- | --- | --- |
| `SIB: List Complete Analysis Runs` | `test` | `Tasks: Run Task` | Liste les `run_id`, statuts (`success`, `partial`, `failed`) et indicateurs d'archivage pour choisir explicitement un run source avant export |
| `SIB: Generate Run Graphs (Latest Success - HTML)` | `build` | `Ctrl+Shift+B` | Genere l'index HTML et regenere aussi les sorties PNG associees (`png/`, `charts/`, `maps/`, `tables/`) pour le dernier run complet avec succes |
| `SIB: Export Run Graphs (Latest Success - PNG)` | `build` | `Ctrl+Shift+B` | Exporte uniquement les sorties PNG du dernier run complet avec succes, y compris les anciens assets Vincennes maintenant integres a la meme tache |
| `SIB: Generate Run Graphs (Selected Run - HTML)` | `build` | `Ctrl+Shift+B` | Genere l'index HTML et les sorties PNG pour le `run_id` saisi dans l'invite. Accepte un `run_id` exact, `latest` ou `latest-success`. |
| `SIB: Export Run Graphs (Selected Run - PNG)` | `build` | `Ctrl+Shift+B` | Exporte uniquement les sorties PNG pour le `run_id` saisi dans l'invite. La tache echoue explicitement si le run choisi n'expose pas tous les artefacts frontend archives requis. |
| `SIB: Export Validation Layout Graphs (Selected Run - Guadeloupe)` | `build` | `Ctrl+Shift+B` | Exporte uniquement le sous-ensemble Vincennes utile a la revue de layout pour la Guadeloupe vers `outputs/Graphs/Validation graphs`, avec le profil reduit `validation_layout`. |

Custom id exemple : all-default,hazard_dynamic_max_tracks-100,default_sampling_spacing_m-50,default_sampling_spacing_m-250,climada_max_points_per_feature-100,climada_max_points_per_feature-1000

Ces taches ne s'appliquent pas aux runs de comparaison d'aleas. Pour ces derniers, les graphes sont deja produits pendant le run comparatif lui-meme.

Choisir le run depuis VS Code:

1. Lancez `SIB: List Complete Analysis Runs` pour voir les `run_id` et leur statut (`success`, `partial`, `failed`).
2. Lancez ensuite une tache `Selected Run` et saisissez soit un `run_id` exact, soit `latest`, soit `latest-success`.

Notes operateur:

- `latest-success` ignore les runs `partial`. Si un run recent a termine les impacts mais a rate l'archivage frontend complet, les taches `Latest Success` reviendront donc au dernier run avec `status=success`.
- Les taches de graphes n'utilisent plus `current-web` et n'ont plus de fallback vers `web/data`. Si un run choisi n'expose pas les JSON/frontend archives attendus, la tache echoue explicitement.
- Les anciens assets Vincennes sont maintenant regenes par les memes taches standard que le reste des graphes PNG. Il n'y a plus de tache dediee separee.
- Si VS Code affiche `Failed to save 'latest-manifest.json': The content of the file is newer...`, cela vient d'un buffer editeur plus ancien que le manifest reecrit par la chaine. Ce n'est pas un echec du script de graphes.
- Si VS Code affiche `Failed to save '.../etc/nginx/sites-available/...': permission denied`, cela vient d'une tentative de sauvegarde editeur sur un fichier systeme distant sans droits d'ecriture. Ce n'est pas emis par les scripts de graphes SIB.

## Verification et journaux

| Label | Groupe | Selection rapide | Role |
| --- | --- | --- | --- |
| `SIB: View Run Logs (Markdown)` | `test` | `Tasks: Run Task` | Affiche le journal Markdown des runs |
| `SIB: View Run Logs (JSONL - Pretty)` | `test` | `Tasks: Run Task` | Affiche le journal JSONL des runs |
| `SIB: Check Latest Deployment` | `test` | `Tasks: Run Task` | Compare les dates et metadonnees des artefacts locaux et de ceux servis par nginx |

## Sensibilite

| Label | Groupe | Selection rapide | Role |
| --- | --- | --- | --- |
| `SIB: Export Sensitivity Workbook` | `build` | `Ctrl+Shift+B` | Extrait le classeur Excel de sensibilite et regenere le pack de scenarios JSON |
| `SIB: List Sensitivity Scenarios` | `test` | `Tasks: Run Task` | Liste les IDs de scenarios disponibles dans le pack par defaut |
| `SIB: Run Sensitivity Analysis (Default Pack)` | `build` | `Ctrl+Shift+B` | Lance toute la campagne du pack de scenarios par defaut |
| `SIB: Run Sensitivity Analysis (Custom Scenario IDs)` | `build` | `Ctrl+Shift+B` | Lance seulement les scenarios saisis dans l'invite `sibSensitivityScenarioIds` |
| `SIB: Resume Latest Sensitivity Analysis` | `build` | `Ctrl+Shift+B` | Reprend le dernier parent run de sensibilite archive |
| `SIB: Monitor Sensitivity Analysis Run` | `build` | `Ctrl+Shift+B` | Suit l'avancement du parent manifest de sensibilite |
| `SIB: Babysit Sensitivity Analysis Run` | `build` | `Ctrl+Shift+B` | Suit le parent sensitivity, attend les child complete-analysis actifs si besoin, puis relance via `tmux` avec `babysit-sensitivity-<run_id>` |

Commandes de suivi utiles pour les babysitters:

- `tmux attach -t babysit-<run_id>` pour `SIB: Babysit Complete Analysis Run`
- `tmux attach -t babysit-hazard-comparison-<run_id>` pour `SIB: Babysit Hazard Comparison Run`
- `tmux attach -t babysit-sensitivity-<run_id>` pour `SIB: Babysit Sensitivity Analysis Run`

## Points de vigilance

- Cette table documente les taches actuellement presentes dans [tasks.json](/home/ubuntu/.vscode/tasks.json), qui est la source de verite visible dans le workspace VS Code courant.
- Les taches `hazard comparison` utilisent maintenant des catalogues et un loader year-aware. Le sens de `full tracks` a donc ete securise: `0` signifie vraiment absence de cap, et `300` / `1500` restent des caps partiels reels.
