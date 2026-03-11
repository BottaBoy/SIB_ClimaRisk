# Journalisation privee du trafic `visu`

Ce document decrit la configuration de journalisation dediee a:
`https://visu.sib.dev.elio.bottagisio.com`

## Objectif

- stocker un log JSONL dedie dans `sib-work`:
  `/home/ubuntu/sib-work/logs/visu-traffic.log`
- reconnaitre les visiteurs recurrents via la cle `visitor_ip + user_agent`
- garder le fichier hors webroot public (`/var/www/sib.shared.elio.dev`)

## Champs journalises

Chaque ligne est un objet JSON avec:

- `time`
- `host`
- `request`
- `status`
- `remote_addr`
- `cf_connecting_ip`
- `visitor_ip` (fallback sur `remote_addr` si `CF-Connecting-IP` absent)
- `user_agent`
- `referer`

## Script de consultation

Script: `/home/ubuntu/sib-work/scripts/visu_traffic.sh`

Exemples:

```bash
/home/ubuntu/sib-work/scripts/visu_traffic.sh tail 40
/home/ubuntu/sib-work/scripts/visu_traffic.sh top 20
/home/ubuntu/sib-work/scripts/visu_traffic.sh find --ip 203.0.113.10
/home/ubuntu/sib-work/scripts/visu_traffic.sh split 127.0.0.1
/home/ubuntu/sib-work/scripts/visu_traffic.sh table 200 127.0.0.1
/home/ubuntu/sib-work/scripts/visu_traffic.sh table-geo 200 127.0.0.1
```

Variable optionnelle:

```bash
VISU_TRAFFIC_LOG_FILE=/chemin/autre.log /home/ubuntu/sib-work/scripts/visu_traffic.sh top
```

Sorties utiles:

- tableau TSV: `/home/ubuntu/sib-work/logs/visu-connections-table.tsv`
- logs separes:
  - `/home/ubuntu/sib-work/logs/visu-traffic-my-ip.log`
  - `/home/ubuntu/sib-work/logs/visu-traffic-other-ip.log`
- cache geo (si `table-geo`): `/home/ubuntu/sib-work/logs/visu-geo-cache.tsv`

`table-geo` utilise une requete en ligne (ipapi.co) et peut retourner `N/A` si la resolution echoue.

## Rotation

La rotation dediee est geree par:
`/etc/logrotate.d/visu-traffic`

- frequence quotidienne
- retention 365 jours
- compression active

## Permissions

Sans ACL systeme (`setfacl` absent), la strategie retenue est:

- dossier `logs/`: `710 ubuntu:www-data`
- fichier `visu-traffic.log`: `620 ubuntu:www-data`

Effet:

- `ubuntu` peut lire/consulter le log
- `www-data` (Nginx) peut ecrire mais ne peut pas lire le contenu
