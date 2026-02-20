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
- Le vhost nginx cible sert depuis: `/var/www/sib.dev.elio.bottagisio.com`.
- Le site public est protege par auth basic sur `sib.dev.elio.bottagisio.com`.

## Etapes standard

1. Verifier l'etat local:

```bash
git -C /home/ubuntu/sib-work status -sb
```

2. Deployer le contenu web (sans commit/push):

```bash
sudo mkdir -p /var/www/sib.dev.elio.bottagisio.com
sudo rsync -av --delete /home/ubuntu/sib-work/web/ /var/www/sib.dev.elio.bottagisio.com/
```

3. Verifier que le fichier deploie contient la modification attendue:

```bash
rg -n "mot-cle-attendu" /var/www/sib.dev.elio.bottagisio.com/index.html
```

4. Verifier la reponse nginx:

```bash
curl -kI --resolve sib.dev.elio.bottagisio.com:443:127.0.0.1 https://sib.dev.elio.bottagisio.com
```

Note: un `401` est normal sans credentials (auth basic active).

5. Verification optionnelle avec credentials (si disponibles):

```bash
curl -sk -u "<user>:<pass>" --resolve sib.dev.elio.bottagisio.com:443:127.0.0.1 https://sib.dev.elio.bottagisio.com | head
```

6. Informer l'utilisateur:
- deploiement fait (oui/non)
- cible deployee: `sib.dev.elio.bottagisio.com`
- recommander un hard refresh navigateur (`Ctrl+F5` ou `Cmd+Shift+R`)

## Regle d'interaction attendue

Apres chaque modification du site, proposer systematiquement:

`Veux-tu que je fasse le deploiement maintenant (sans commit/push) ?`

Contraintes:
- ne pas faire de commit/push sauf demande explicite
- ne pas deployer automatiquement sans validation explicite utilisateur
