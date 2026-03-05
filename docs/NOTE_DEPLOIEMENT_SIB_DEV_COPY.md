# Note operationnelle - Synchronisation `sib.dev` et `sib-copy`

Cette note sert de garde-fou avant tout deploiement web.

## Regle a respecter

Pour chaque nouvelle version (apres commit/push), le deploiement doit etre fait sur le **root partage**:

- `/var/www/sib.shared.elio.dev/`

Les deux vhosts ci-dessous lisent ce meme root:

- `sib.dev.elio.bottagisio.com`
- `sib-copy.dev.elio.bottagisio.com`

Donc un deploiement sur ce root met automatiquement a jour les deux sites.

## Commande de deploiement a utiliser

```bash
sudo rsync -av --delete /home/ubuntu/sib-work/web/ /var/www/sib.shared.elio.dev/
```

## Verification obligatoire apres deploiement

```bash
sudo curl -I -u eliosib:sibpass --resolve sib.dev.elio.bottagisio.com:443:127.0.0.1 https://sib.dev.elio.bottagisio.com
sudo curl -I -u eliosib:sibpass --resolve sib-copy.dev.elio.bottagisio.com:443:127.0.0.1 https://sib-copy.dev.elio.bottagisio.com
```

Attendu:

- code HTTP `200` sur les deux domaines
- meme `content-length` et meme `etag` (meme version servie)
