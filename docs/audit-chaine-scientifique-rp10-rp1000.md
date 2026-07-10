# Audit chaine scientifique RP10/RP50/RP100/RP1000

Date: 2026-07-08

Ce document resume les deux passes de verification faites apres la migration du contrat scientifique public vers `rp10`, `rp50`, `rp100`, `rp1000`.

## Objectif fonctionnel

La chaine publique/graphes doit etre une chaine scientifique unique:

- Scenarios publics stricts: `rp10`, `rp50`, `rp100`, `rp1000`.
- Scenarios interdits dans les outputs scientifiques publics: `annual`, `p99`, `event_max`.
- Services publics stricts: `eau_aep`, `eau_eu`, `elec`.
- Services interdits dans les outputs publics v4: `water_aep`, `water_eu`.
- Selection evenementielle demandee: `L_famille(event_global_RP*)`, donc les degats eau/elec sont lus dans les evenements globaux selectionnes sur la perte portefeuille globale, pas dans un RP propre a chaque famille.
- Aucun fallback de calcul, de source, ou de selection de source ne doit pouvoir alimenter les graphes de publication.

## Etat actuel du contrat

Le contrat central est dans `scripts/scientific_publication_contract.py`.

Valeurs attendues:

```python
SCIENTIFIC_SCENARIOS = ("rp10", "rp50", "rp100", "rp1000")
RETURN_PERIOD_BY_SCENARIO = {
    "rp10": 10,
    "rp50": 50,
    "rp100": 100,
    "rp1000": 1000,
}
EVENT_SELECTION_BASIS = "global_portfolio_loss"
PUBLIC_SERVICE_KEYS = ("eau_aep", "eau_eu", "elec")
```

Versions publiques attendues:

```python
scientific_web_summary_v4
scientific_web_contract_v4
```

## Passe de verification 1

### Resultat

La premiere passe a confirme que la chaine publication/graphes est globalement robuste apres migration, avec un point bloquant corrige pendant l'audit.

### Point bloquant trouve et corrige

`build_scientific_web_summary.py` enrichissait l'archive `complete-analysis` passee via `--complete-analysis-json`, mais le snapshot final de run relit aussi `web/data/<territory>-complete-analysis.json`.

Risque avant correction:

- l'archive pouvait contenir `scientific_graph_inputs` v4;
- le fichier mutable `web/data/*-complete-analysis.json` pouvait rester sans bloc v4;
- le snapshot final pouvait echouer ou rearchiver un complete-analysis sans contrat v4.

Correction:

- `build_scientific_web_summary.py` miroite maintenant `scientific_graph_inputs` vers `web/data/<territory>-complete-analysis.json` quand il travaille depuis une archive;
- un garde-fou refuse le miroir si les `run_id` source et mutable divergent;
- test ajoute: `test_build_scientific_web_summary_mirrors_v4_contract_to_mutable_web_complete_analysis`.

### Verifications passees

Commandes relancees:

```bash
./backend/.venv/bin/python -m py_compile \
  scripts/scientific_publication_contract.py \
  scripts/scientific_graph_postprocess.py \
  scripts/build_scientific_web_summary.py \
  scripts/generate_run_graphs.py \
  scripts/run_web_artifacts.py \
  scripts/rerun_case_studies_light.py \
  scripts/run_complete_analysis.py

./backend/.venv/bin/python -m pytest \
  tests/scripts/test_generate_run_graphs.py \
  tests/scripts/test_publication_contract.py \
  tests/scripts/test_scientific_web_summary.py \
  tests/scripts/test_scientific_publication_contract_v4.py \
  -q
```

Resultat: `48 passed`, avec seulement un warning tiers `FionaDeprecationWarning`.

## Passe de verification 2

### Ce qui est confirme solide

- `generate_run_graphs.py` charge les graphes d'impact/reseaux/sociaux depuis le contrat scientifique strict, pas depuis `page-analysis`.
- Les graphes de degats par scenario utilisent `SCIENTIFIC_SCENARIOS` et affichent `RP10/RP50/RP100/RP1000`.
- Les matrices reseau utilisent `rp10/rp50/rp100/rp1000` et les colonnes publiques `eau_aep/eau_eu/elec`.
- `scientific-web-summary` v4 republie `complete_analysis.scientific_graph_inputs` 1:1.
- `run_web_artifacts.py` bloque:
  - `fallback_active=true`;
  - fallback proxy amont;
  - source mode legacy interdit;
  - scenarios interdits dans `scientific_graph_inputs`;
  - service keys publics non canoniques;
  - mismatch entre summary v4 et complete-analysis;
  - mismatch entre summary reseau et `network-states.geojson`.
- Les graphes annuels FEC ne sont plus dans `GRAPH_TYPE_ORDER` et ne sont plus ajoutes automatiquement aux graphes de publication.

### Recherche statique legacy

Recherche relancee pendant la deuxieme passe:

```bash
rg -n "scientific_web_summary_v3|scientific_web_contract_v3|--page-analysis-json|page_analysis_path|proxy_breakdown_share_validation" \
  scripts tests docs
```

Resultat interprete:

- aucun usage runtime restant dans `scripts/`;
- `proxy_breakdown_share_validation` apparait seulement dans un test qui verifie son absence;
- la seule autre occurrence est ce document, comme trace d'audit.

### Nuances scientifiques importantes

Ces points ne bloquent pas les validations actuelles, mais doivent etre connus du prochain agent.

#### 1. Selection RP: directe puis mise a l'echelle portefeuille

Dans la chaine CLIMADA/impact runner, les PML publies sont derives des pertes evenementielles directes puis multiplies par un `dependency_scaler` pour representer le total portefeuille incluant l'effet indirect/dependance.

Consequence:

- le rang des evenements RP est equivalent si le scaler est constant par alea;
- le libelle `event_selection_basis = "global_portfolio_loss"` reste coherent au niveau portefeuille publie;
- techniquement, la selection est basee sur une perte evenementielle globale directe, puis mise a l'echelle totale.

Recommandation:

- ne pas renommer le contrat sans decision produit/scientifique, car l'utilisateur a explicitement demande `L_eau(event_global_RP100)`;
- si un futur agent veut une precision maximale, documenter dans la methode: "global direct event loss with portfolio dependency scaling".

#### 2. Post-process cible: outil de reparation, pas chaine nominale

`scripts/scientific_graph_postprocess.py` existe pour reparer des runs archives pre-v4.

Il reconstruit:

- les evenements `rp10/rp50/rp100/rp1000`;
- les breakdowns de degats par scenario;
- les tables d'etat/dommage necessaires au contrat.

Limite importante:

- pour certains etats reseau reconstruits, le post-process utilise une spatialisation basee sur le profil annuel direct par point, puis ajuste les totaux par classe/scenario;
- les totaux de degats par classe/scenario sont recalcules plus strictement par evenement et composant;
- la distribution spatiale fine des etats dans un ancien run repare peut donc etre moins robuste qu'un run futur qui produit directement les artefacts v4.

Conclusion:

- acceptable comme outil de secours pour anciens runs;
- ne doit pas devenir la chaine nominale permanente;
- pour un run 1500 tracks neuf, preferer la production native + validation v4.

#### 3. Page-analysis existe encore pour compatibilite web

`page-analysis` peut encore etre construit par `rerun_case_studies_light.py`.

Ce n'est pas un probleme tant que:

- `build_scientific_web_summary.py` ne le lit pas;
- `generate_run_graphs.py` ne le lit pas pour les graphes scientifiques;
- `run_web_artifacts.py` ne l'utilise pas comme source scientifique;
- les traces `fallback_active` restent bloquees.

La presence de `page-analysis` dans le repository n'est donc pas equivalente a son usage scientifique.

#### 4. Helpers annuels encore presents dans le code

`generate_run_graphs.py` contient encore des fonctions diagnostiques autour de FEC annuelle.

Etat actuel:

- elles ne sont plus dans `GRAPH_TYPE_ORDER`;
- elles ne sont plus ajoutees automatiquement;
- les tests de graphes publics passent sans elles.

Recommandation:

- les supprimer dans une future passe de nettoyage si l'objectif devient de reduire fortement la surface de code;
- ne pas le faire juste avant le run 1500 si cela risque de perturber des diagnostics non publics.

## Chaine full-track actuelle

Pour un run complete-analysis standard:

1. `run_complete_analysis.py` exporte `web/data/<territory>-complete-analysis.json` puis l'archive.
2. `rerun_case_studies_light.py` resout l'archive complete-analysis.
3. `build_scientific_web_summary.py` construit le summary v4 depuis cette archive.
4. Si le bloc `scientific_graph_inputs` manque ou est legacy, `scientific_graph_postprocess.py` est appele automatiquement.
5. Le bloc v4 est ecrit dans l'archive et miroir vers `web/data/<territory>-complete-analysis.json`.
6. `run_web_artifacts.py` valide la coherence v4 avant snapshot/publication.
7. `generate_run_graphs.py` consomme uniquement les sources scientifiques strictes pour les graphes d'impact/reseau/social.

Point a surveiller:

- si un agent lance `generate_run_graphs.py` avant la phase `build_scientific_web_summary`, il peut manquer `scientific_graph_inputs`;
- dans la chaine full-track normale, cette phase est maintenant integree avant le snapshot.

## Tests contractuels utiles

Tests a relancer avant un run de presentation:

```bash
./backend/.venv/bin/python -m pytest \
  tests/scripts/test_generate_run_graphs.py \
  tests/scripts/test_publication_contract.py \
  tests/scripts/test_scientific_web_summary.py \
  tests/scripts/test_scientific_publication_contract_v4.py \
  -q
```

Compilation rapide:

```bash
./backend/.venv/bin/python -m py_compile \
  scripts/scientific_publication_contract.py \
  scripts/scientific_graph_postprocess.py \
  scripts/build_scientific_web_summary.py \
  scripts/generate_run_graphs.py \
  scripts/run_web_artifacts.py \
  scripts/rerun_case_studies_light.py \
  scripts/run_complete_analysis.py
```

Recherche utile pour verifier les restes legacy:

```bash
rg -n "scientific_web_summary_v3|scientific_web_contract_v3|--page-analysis-json|page_analysis_path|proxy_breakdown_share_validation" \
  scripts tests
```

## Verdict pour le prochain agent

La chaine scientifique publique v4 est suffisamment robuste pour lancer un nouveau run full-track 1500, sous reserve de ne pas contourner la phase `build_scientific_web_summary`.

Ce qui est robuste:

- contrat centralise;
- scenarios publics stricts;
- cles reseau canoniques;
- validation fail-fast;
- absence de fallback dans la publication;
- graphes d'impact/reseau/social bases sur les artefacts scientifiques stricts;
- miroir archive/web-data corrige.

Ce qui reste a ameliorer plus tard:

- supprimer les helpers annuels diagnostiques restants si on veut reduire la surface legacy;
- rendre le post-process d'anciens runs plus exact spatialement si ces anciens runs doivent servir de reference finale;
- documenter plus explicitement dans les outputs publics que les RP famille sont `L_famille(event_global_RP*)`, pas des PML propres a chaque famille.
