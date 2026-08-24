# Note de contexte projet - sib-work

Derniere mise a jour: 2026-05-06

Cette note sert de contexte de demarrage pour les agents IA qui travaillent sur `/home/ubuntu/sib-work`.

## 1) Role du depot

- `sib-work` est le depot de travail principal du projet SIB.
- Le projet sert a produire, analyser et publier des resultats d'analyse des risques climatiques, avec un accent fort sur le risque cyclonique.
- Le cas d'usage principal concerne les infrastructures d'eau et d'electricite.
- Quand l'utilisateur mentionne simplement "SIB" dans cet espace de travail, il faut par defaut comprendre qu'il parle de ce depot: `/home/ubuntu/sib-work`.

## 2) Finalite metier

Le projet combine deux objectifs:

1. calculer des impacts multi-aleas sur des infrastructures critiques,
2. publier des artefacts web permettant d'explorer et de partager les resultats.

Les territoires les plus frequents sont:
- Guadeloupe
- Martinique

Les aleas et restitutions principales tournent autour de:
- vent cyclonique,
- pluie,
- submersion,
- agregations multi-aleas,
- et, selon les workflows, analyses de sensibilite.

## 3) Architecture generale

Les repertoires les plus importants sont:

- `backend/`: API FastAPI et moteur de calcul de risque.
- `backend/app/risk_engine/`: coeur scientifique et calculatoire.
- `scripts/`: orchestration des runs complets, rebuilds frontend, snapshots, deploys et analyses de sensibilite.
- `web/`: site statique et artefacts frontend servis au navigateur.
- `outputs/complete-analysis-runs/<run_id>/`: archives des runs complets et de leurs artefacts.
- `outputs/sensitivity-runs/<run_id>/`: archives des runs de sensibilite.
- `docs/`: notes d'architecture, de calcul et de procedure.
- `config/`: pieces de configuration systeme, nginx et systemd.

## 4) Convention scientifique

- La voie scientifique de reference est la voie CLIMADA native.
- Les fallbacks historiques peuvent exister pour audit, historique ou publication controlee, mais ils ne doivent pas etre reintroduits comme mode de production par defaut.
- En cas d'arbitrage, privilegier la validite scientifique et la tracabilite des resultats avant la commodite operatoire.

## 5) Objets de sortie importants

Les objets les plus structurants dans les discussions et les workflows sont:

- le `complete-analysis.json` par territoire,
- les artefacts frontend derives de ce resultat,
- les manifests de run,
- les journaux de run,
- les exports de sensibilite.

En pratique, un `run_id` identifie souvent l'unite de travail a suivre, auditer, republier ou comparer.

## 6) Flux operatoire courant

Le flux le plus courant est le suivant:

1. lancer ou reprendre un run complet,
2. regenerer si necessaire les artefacts frontend du territoire vise,
3. snapshotter les artefacts web valides dans l'archive du run,
4. deployer depuis l'archive du run,
5. verifier les artefacts, les manifests et les journaux associes.

Important:
- il faut distinguer clairement le calcul scientifique, le rebuild frontend, le snapshot/archive et le deploiement;
- pour une publication, il faut privilegier les artefacts archives du run plutot que l'etat mutable courant de `web/`.

## 7) Points d'attention pour les agents

- Les taches VS Code prefixees `SIB:` dans l'espace de travail `/home/ubuntu` pilotent souvent ce depot.
- Si une demande parle d'analyse, de run, d'artefacts ou de publication, identifier rapidement si l'action cible surtout `backend/`, `scripts/`, `web/` ou `outputs/`.
- Si la demande touche au site, a la publication ou au deploiement, lire aussi `/home/ubuntu/sib-work/DEPLOIEMENT.md`.
- Si la demande touche au moteur de calcul ou a la logique scientifique, la note de reference detaillee est `/home/ubuntu/sib-work/docs/note-backend-calculatoire.md`.
- Ne pas supposer qu'un deploiement est souhaite simplement parce qu'un artefact web a ete modifie.

## 8) Vocabulaire utile

- "complete analysis": pipeline complet de calcul et de publication par territoire.
- "frontend artefacts": JSON, GeoJSON et autres fichiers servis par `web/` ou archives sous `outputs/.../web/`.
- "publication": preparation puis deploiement d'un run archive vers le site.
- "sensitivity analysis": variantes de scenarios comparees a partir d'un pack de scenarios.

## 9) Domaines et cibles web a connaitre

- `sib.elio.dev`: vitrine publique.
- `app.sib.elio.dev`: application privee avec API.
- `sib.dev.elio.bottagisio.com`: alias de publication utilise pour certains deploys de runs archives.

Cette note doit rester concise. Son role est de fournir aux agents un contexte projet suffisant pour commencer a travailler sans que l'utilisateur doive reexpliquer le cadre general a chaque nouvelle conversation.