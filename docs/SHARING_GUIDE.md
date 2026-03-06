# Guide de partage externe

## Etat actuel (deja en place)

- Domaine public actif: `https://visu.sib.dev.elio.bottagisio.com`
  - acces sans mot de passe
  - mode vitrine force (pas de runs utilisateur)
  - `/api/*` bloque (`404`)
- Domaine prive actif: `https://sib.dev.elio.bottagisio.com`
  - auth basic active
  - API active (`/api/v1/*`)
  - limite de debit appliquee cote nginx

Les deux domaines servent le meme artefact web deploye dans:
`/var/www/sib.shared.elio.dev`

## Partage immediat

Pour montrer ton travail publiquement, partage simplement:

`https://visu.sib.dev.elio.bottagisio.com`

## Bascule finale vers `sib.elio.dev` / `app.sib.elio.dev`

1. Configurer DNS:
   - `sib.elio.dev` -> IP serveur
   - `app.sib.elio.dev` -> IP serveur (ou proxy Cloudflare)
2. Activer les vhosts:
   - `/etc/nginx/sites-available/sib.elio.dev`
   - `/etc/nginx/sites-available/app.sib.elio.dev`
3. Emettre certificats:
   - `sudo certbot --nginx -d sib.elio.dev -d app.sib.elio.dev`
4. Activer les liens `sites-enabled`, tester puis recharger nginx.
5. Mettre en place Cloudflare Access sur `app.sib.elio.dev` (liste blanche e-mails nominative).

## Verification minimale apres bascule

- Public:
  - `https://sib.elio.dev` -> `200`
  - `https://sib.elio.dev/api/v1/health` -> `404`
- Prive:
  - `https://app.sib.elio.dev` -> acces controle
  - `https://app.sib.elio.dev/api/v1/health` -> `200` pour utilisateur autorise
