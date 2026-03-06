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
