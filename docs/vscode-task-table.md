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

| Label | Groupe | Selection rapide | Role |
| --- | --- | --- | --- |
| `SIB: Rebuild Frontend Artefacts (Guadeloupe Only)` | `build` | `Ctrl+Shift+B` | Regenerer les artefacts frontend publication-safe pour la Guadeloupe |
| `SIB: Rebuild Frontend Artefacts (Both Territories)` | `build` | `Ctrl+Shift+B` | Regenerer les artefacts frontend pour Guadeloupe et Martinique |
| `SIB: Rebuild Frontend + Deploy (Guadeloupe Only)` | `build` | `Ctrl+Shift+B` | Rebuild frontend Guadeloupe puis deploie sur la racine partagee live |
| `SIB: Prepare Latest Run Publication (Guadeloupe Only)` | `build` | `Ctrl+Shift+B` | Rebuild publication-safe puis snapshotte les artefacts du dernier run Guadeloupe |
| `SIB: Snapshot Latest Run Web Artefacts` | `build` | `Ctrl+Shift+B` | Archive les artefacts web du dernier run pour les deux territoires |
| `SIB: Snapshot Latest Run Web Artefacts (Guadeloupe Only)` | `build` | `Ctrl+Shift+B` | Archive les artefacts web du dernier run uniquement pour la Guadeloupe |
| `SIB: Deploy Only (Live shared root)` | `build` | `Ctrl+Shift+B` | Deploie le contenu web actuel sur `sib.shared.elio.dev` |
| `SIB: Deploy Only (sib.dev alias -> shared root)` | `build` | `Ctrl+Shift+B` | Deploie le contenu web actuel via le label `sib.dev.elio.bottagisio.com` |
| `SIB: Deploy Only (Both labels, deduped)` | `build` | `Ctrl+Shift+B` | Deploie une seule fois vers les deux labels nginx dedoublonnes |
| `SIB: Deploy Archived Latest Run (sib.dev alias -> shared root)` | `build` | `Ctrl+Shift+B` | Deploie les artefacts archives du dernier run via l'alias `sib.dev` |
| `SIB: Deploy Archived Latest Run (Guadeloupe Only -> sib.dev alias)` | `build` | `Ctrl+Shift+B` | Deploie seulement les artefacts archives Guadeloupe du dernier run |

## Verification et journaux

| Label | Groupe | Selection rapide | Role |
| --- | --- | --- | --- |
| `SIB: View Run Logs (Markdown)` | `test` | `Ctrl+Shift+P` puis `Tasks: Run Task` | Affiche le journal Markdown des runs |
| `SIB: View Run Logs (JSONL - Pretty)` | `test` | `Ctrl+Shift+P` puis `Tasks: Run Task` | Affiche le journal JSONL des runs |
| `SIB: Check Latest Deployment` | `test` | `Ctrl+Shift+P` puis `Tasks: Run Task` | Compare les dates/meta des artefacts locaux et de ceux servis par nginx |

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