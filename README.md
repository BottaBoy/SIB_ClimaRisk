# SIB Demo

Mini-site statique de demonstration pour valoriser une etude de risques climatiques, avec focus DOM-TOM autour de la Guadeloupe.

## Objectif
- Presenter rapidement la valeur d'une interface graphique interactive a partir d'analyses issues d'un notebook.
- Public cible: decideurs non techniques.
- Domaine vise: `https://sib.mc2-sarl.com`.

## Stack
- Frontend statique: `HTML + CSS + JS` (sans backend)
- Visualisations: `ECharts` + `Leaflet` (OpenStreetMap)
- Donnees: fichier JSON unique `web/data/sib-demo.json`

## Fonctionnalites principales
- KPI synthese (exposition, pertes attendues, indice de risque)
- Comparateur scenarios/horizons
- Carto interactive DOM-TOM:
  - points proportionnels (taille = exposition)
  - couleur = indice de risque
  - clic sur territoire = filtre global (KPI + comparateur + table + insights)
- Tableau territorial filtrable

## Structure
- `web/index.html`: interface complete (UI + logique JS)
- `web/data/sib-demo.json`: donnees mock (puis donnees reelles)
- `web/assets/`: medias statiques optionnels
- `scripts/validate-data.mjs`: validation du contrat JSON
- `scripts/notebook-json-template.md`: guide de mapping notebook -> JSON
- `config/nginx/sib.mc2-sarl.com`: vhost nginx

## Contrat de donnees
Le frontend charge `https://sib.mc2-sarl.com/data/sib-demo.json`.

Champs attendus:
- `meta.title` (string)
- `meta.updated_at` (date ISO string)
- `meta.source` (`mock` ou `notebook`)
- `meta.unit_currency` (string, ex: `MEUR`)
- `scenarios[]` avec `{ id, label, technical_label }`
- `horizons[]` (entiers, ex: `2030, 2050, 2100`)
- `geographies[]` avec:
  - `id` (string)
  - `label` (string)
  - `lat` (number, -90..90)
  - `lon` (number, -180..180)
- `records[]` avec:
  - `geography_id` (string, doit exister dans `geographies[].id`)
  - `geography_label` (string)
  - `scenario_id` (string)
  - `horizon` (number)
  - `exposure_meur` (number)
  - `expected_loss_meur` (number)
  - `risk_index` (number)
- `insight_notes[]` (strings)

## Validation des donnees
Depuis la racine du repo:

```bash
node scripts/validate-data.mjs
```

Ou avec un fichier explicite:

```bash
node scripts/validate-data.mjs web/data/sib-demo.json
```

## Execution locale (apercu)
Depuis `sib_demo/web`:

```bash
python3 -m http.server 8080
```

Puis ouvrir:
- `http://localhost:8080/`
- Le JSON est servi sur `http://localhost:8080/data/sib-demo.json`

## Deploiement web
Copier le contenu de `web/` vers `/var/www/sib.mc2-sarl.com/`.

```bash
sudo mkdir -p /var/www/sib.mc2-sarl.com
sudo rsync -av --delete web/ /var/www/sib.mc2-sarl.com/
```

## Deploiement nginx
1. Copier `config/nginx/sib.mc2-sarl.com` vers `/etc/nginx/sites-available/`.
2. Creer le symlink dans `/etc/nginx/sites-enabled/`.
3. Verifier et recharger nginx.

```bash
sudo cp config/nginx/sib.mc2-sarl.com /etc/nginx/sites-available/sib.mc2-sarl.com
sudo ln -s /etc/nginx/sites-available/sib.mc2-sarl.com /etc/nginx/sites-enabled/sib.mc2-sarl.com
sudo nginx -t
sudo systemctl reload nginx
```

## Certificat TLS
Si DNS deja propage:

```bash
sudo certbot --nginx -d sib.mc2-sarl.com
```

## Remplacer les donnees mock par celles du notebook
1. Exporter le JSON depuis le notebook selon `scripts/notebook-json-template.md`.
2. Remplacer `web/data/sib-demo.json`.
3. Revalider:

```bash
node scripts/validate-data.mjs web/data/sib-demo.json
```

4. Redeployer `web/`.
