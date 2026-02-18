# Export notebook -> `sib-demo.json`

Ce guide décrit le mapping attendu pour produire `web/data/sib-demo.json` depuis le notebook `SIB_ClimatRisques7.ipynb`.

## 1) Structure cible
Le JSON final doit suivre ce schéma:

```json
{
  "meta": {
    "title": "SIB - Demo Climat Risques",
    "updated_at": "2026-02-14T00:00:00Z",
    "source": "notebook",
    "unit_currency": "MEUR"
  },
  "scenarios": [
    { "id": "optimiste", "label": "Optimiste", "technical_label": "SSP1-2.6" },
    { "id": "central", "label": "Central", "technical_label": "SSP2-4.5" },
    { "id": "stress", "label": "Stress", "technical_label": "SSP5-8.5" }
  ],
  "horizons": [2030, 2050, 2100],
  "geographies": [
    {
      "id": "gp-basse-terre",
      "label": "Guadeloupe - Basse-Terre",
      "lat": 16.001,
      "lon": -61.726
    }
  ],
  "records": [
    {
      "geography_id": "gp-basse-terre",
      "geography_label": "Guadeloupe - Basse-Terre",
      "scenario_id": "central",
      "horizon": 2050,
      "exposure_meur": 1200.4,
      "expected_loss_meur": 88.2,
      "risk_index": 63.5
    }
  ],
  "insight_notes": [
    "Texte court 1",
    "Texte court 2"
  ]
}
```

## 2) Mapping métier conseillé
- `geography_id`: identifiant stable, ASCII, sans espace (ex: `gp-basse-terre`).
- `geography_label`: libellé affiché dans la table (ex: `Guadeloupe - Basse-Terre`).
- `scenario_id`: `optimiste` / `central` / `stress`.
- `horizon`: entier (`2030`, `2050`, `2100`).
- `exposure_meur`: exposition en millions d'euros.
- `expected_loss_meur`: pertes attendues en millions d'euros.
- `risk_index`: score normalisé 0-100.
- `geographies[].lat/lon`: coordonnées (centroïdes métier) pour la carto Leaflet.

## 3) Règles de cohérence
- Chaque `records[].geography_id` doit exister dans `geographies[].id`.
- `lat` doit être dans `[-90, 90]`.
- `lon` doit être dans `[-180, 180]`.
- IDs géographiques uniques.

## 4) Exemple de pipeline pandas
Adapter les noms de colonnes à votre notebook.

```python
import json
from datetime import datetime, timezone

# Exemple de colonnes attendues
# df_result: ['zone_id', 'zone_label', 'scenario', 'horizon', 'exposure_meur', 'expected_loss_meur', 'risk_index']
# df_geo:    ['zone_id', 'zone_label', 'lat', 'lon']

scenario_mapping = {
    'Optimiste': ('optimiste', 'SSP1-2.6'),
    'Central': ('central', 'SSP2-4.5'),
    'Stress': ('stress', 'SSP5-8.5'),
}

records = []
for _, row in df_result.iterrows():
    scenario_id, _ = scenario_mapping[row['scenario']]
    records.append({
        'geography_id': str(row['zone_id']),
        'geography_label': str(row['zone_label']),
        'scenario_id': scenario_id,
        'horizon': int(row['horizon']),
        'exposure_meur': float(row['exposure_meur']),
        'expected_loss_meur': float(row['expected_loss_meur']),
        'risk_index': float(row['risk_index']),
    })

geographies = []
for _, row in df_geo.drop_duplicates(subset=['zone_id']).iterrows():
    geographies.append({
        'id': str(row['zone_id']),
        'label': str(row['zone_label']),
        'lat': float(row['lat']),
        'lon': float(row['lon']),
    })

payload = {
    'meta': {
        'title': 'SIB - Demo Climat Risques',
        'updated_at': datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        'source': 'notebook',
        'unit_currency': 'MEUR',
    },
    'scenarios': [
        {'id': 'optimiste', 'label': 'Optimiste', 'technical_label': 'SSP1-2.6'},
        {'id': 'central', 'label': 'Central', 'technical_label': 'SSP2-4.5'},
        {'id': 'stress', 'label': 'Stress', 'technical_label': 'SSP5-8.5'},
    ],
    'horizons': [2030, 2050, 2100],
    'geographies': geographies,
    'records': records,
    'insight_notes': [
        'Exporter ce JSON remplace directement les données mock de la maquette.',
        'Conserver des unités homogènes en M€ pour exposition et pertes.',
    ],
}

with open('sib-demo.json', 'w', encoding='utf-8') as f:
    json.dump(payload, f, ensure_ascii=False, indent=2)
```

## 5) Validation avant déploiement
Depuis la racine du repo `sib_demo`:

```bash
node scripts/validate-data.mjs /chemin/vers/sib-demo.json
```

## 6) Intégration au site
- Remplacer `web/data/sib-demo.json` par le JSON exporté.
- Redéployer le dossier `web/` vers `/var/www/sib.mc2-sarl.com/`.
