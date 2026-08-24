# Procedure de deploiement web (sans commit/push)

Ce document centralise la procedure operationnelle pour deployer les modifications du site.

## Perimetre

Cette procedure s'applique a toute modification de contenu web, notamment:
- `web/index.html`
- `web/data/*.json`
- `web/assets/*`
- tout autre fichier servi depuis `web/`

## Prerequis

- Les modifications sont presentes localement dans `/home/ubuntu/sib-work`.
- Les vhosts nginx public/prive servent depuis un **root partage**: `/var/www/sib.shared.elio.dev`.
- Domaine public attendu: `sib.elio.dev` (mode vitrine, sans API).
- Domaine prive attendu: `app.sib.elio.dev` (collaborateurs, avec API).

## Etapes standard

1. Verifier l'etat local:

```bash
git -C /home/ubuntu/sib-work status -sb
```

2. Deployer le contenu web (sans commit/push):

```bash
/home/ubuntu/sib-work/scripts/deploy_shared_web.sh
```

3. Verifier que le fichier deploie contient la modification attendue:

```bash
rg -n "mot-cle-attendu" /var/www/sib.shared.elio.dev/index.html
```

4. Verifier la reponse nginx - domaine public:

```bash
curl -kI --resolve sib.elio.dev:443:127.0.0.1 https://sib.elio.dev
```

Attendu: `200` sur la racine, et `404` sur `/api/*`.

5. Verifier la reponse nginx - domaine prive:

```bash
curl -kI --resolve app.sib.elio.dev:443:127.0.0.1 https://app.sib.elio.dev
curl -kI --resolve app.sib.elio.dev:443:127.0.0.1 https://app.sib.elio.dev/api/v1/health
```

Attendu: acces controle par la couche d'auth privee (Cloudflare Access / politique equivalente).

6. Informer l'utilisateur:
- deploiement fait (oui/non)
- cibles deployees: `sib.elio.dev` (public) et `app.sib.elio.dev` (prive)
- recommander un hard refresh navigateur (`Ctrl+F5` ou `Cmd+Shift+R`)

## Regle d'interaction attendue

Apres chaque modification du site, proposer systematiquement:

`Veux-tu que je fasse le deploiement maintenant (sans commit/push) ?`

Contraintes:
- ne pas faire de commit/push sauf demande explicite
- ne pas deployer automatiquement sans validation explicite utilisateur

## Note backend API (nouveau perimetre)

Le projet contient maintenant un backend FastAPI (templates systemd/nginx dans `config/systemd/` et `config/nginx/`).

Cette procedure reste orientee **deploiement web statique** uniquement.

Pour le backend, prevoir en plus:
- creation d'un environnement Python dedie (`backend/.venv`) avec dependances geospatiales/CLIMADA
- activation du service `sib-risk-api.service`
- activation du timer `sib-risk-cleanup.timer`
- verification de `GET /api/v1/health` (via le proxy nginx `/api/` ou directement en local)

## Process publication des runs SIB

Pour publier sur `https://sib.dev.elio.bottagisio.com` sans dependre de l'etat mutable de `web/`, la chaine attendue est maintenant:

1. Executer ou reprendre le run complet.
	- Tache recommandee: `SIB: Run Complete Analysis (...)`
	- Le run archive toujours le `complete-analysis.json` par territoire sous `outputs/complete-analysis-runs/<run_id>/territories/<territory>/web/...`

2. Rebuilder les artefacts frontend du territoire si necessaire.
	- Tache recommandee: `SIB: Rebuild Frontend Artefacts (Guadeloupe Only)`
	- Le rebuild frontend utilise un profil de publication plus leger que le run d'impact complet.
	- Pour Guadeloupe, le profil de publication force maintenant un proxy multi-aleas derive du `complete-analysis.json` et un `page-analysis` / `network-states` derives des `asset_results` du `complete-analysis.json`; les reruns CLIMADA frontend lourds ne sont plus un prerequis pour publier.
	- Les artefacts `multi-hazard-proxy` et `page-analysis` ecrivent maintenant `meta.publication_trace`, qui expose explicitement le `source_mode`, l'etat `fallback_active`, la raison de fallback et les run ids amont utiles au controle operateur.

3. Snapshotter les artefacts web valides dans l'archive du run.
	- Tache recommandee: `SIB: Snapshot Latest Run Web Artefacts (Guadeloupe Only)`
	- Cette etape valide que les fichiers `wind-maps`, `multi-hazard-proxy`, `page-analysis` et `network-states` ont bien ete reecrits avant publication.
	- Elle verifie aussi la presence de `meta.publication_trace` sur `multi-hazard-proxy` et `page-analysis`, puis archive un resume sous `territories.<territory>.archived_frontend_validation.publication_trace` dans le `manifest.json` du run.

4. Deployer depuis l'archive du run, pas depuis le `web/` de travail.
	- Tache recommandee: `SIB: Deploy Archived Latest Run (Guadeloupe Only -> sib.dev alias)`
	- Cette etape reconstruit un staging a partir du `web/` du repo + des fichiers archives du run (sans reutiliser le root live courant) puis synchronise vers `/var/www/sib.shared.elio.dev`.

5. Effectuer le controle manuel web et metadata/logs.
	- Ouvrir `page1`/`page2` et verifier le badge `Trace:` dans l'en-tete: il doit expliciter si la publication est en calcul natif, fallback complet ou trace mixte.
	- Dans le panneau `Analyse des aleas`, verifier que `Afficher le quadrillage des cartes` superpose bien la maille de publication sans modifier les valeurs.
	- Dans le `manifest.json` du run archive, controler `archived_frontend_validation.publication_trace` et `publication_fallback_present`.
	- Dans les logs du rebuild frontend, controler les lignes `fallback_proxy=true ...` et `fallback_page_analysis=true ...` quand le profil de publication fallback est attendu.

## Regle operatoire sib.dev

- `sib.dev.elio.bottagisio.com` est servi depuis `/var/www/sib.shared.elio.dev`.
- Pour republier un run precedent ou reprendre une publication interrompue, utiliser le couple `snapshot_run_web_artifacts.py` + `deploy_only.py --run-id ...`.
- Ne pas considerer `SIB: Deploy Only (...)` comme un mecanisme de reprise de run: cette tache copie simplement l'etat courant de `web/`.
- Le chemin operatoire robuste pour Guadeloupe est maintenant: `wind-maps` frais -> proxy fallback complet -> page-analysis fallback complet -> snapshot archive -> deploy archive.
- Le badge web `Trace:` et le bloc `archived_frontend_validation.publication_trace` du manifest sont les references operateur pour auditer la provenance de publication sans reouvrir tous les JSON un par un.
