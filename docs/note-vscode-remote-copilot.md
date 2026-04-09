# VS Code distant et Copilot entreprise

Cette note formalise la configuration recommandee pour travailler sur ce projet depuis `VS Code` en se connectant en `Remote - SSH` a un serveur comme `eliodev`, avec des contraintes reseau d'entreprise et sans droits admin sur le serveur distant.

## Point cle

- `Microsoft 365 Copilot` ne s'integre pas aujourd'hui comme assistant de code natif dans `VS Code` / `Remote - SSH` pour ce projet.
- Pour coder avec un assistant Copilot dans `VS Code`, il faut une licence `GitHub Copilot` distincte (`Business` ou `Enterprise`) plus les extensions `GitHub Copilot` et `GitHub Copilot Chat`.
- En revanche, `Microsoft 365 Agents Toolkit` permet de developper des agents, connecteurs et integrations autour de `Microsoft 365 Copilot`.

## Extensions a installer sur le poste local

Les recommandations du workspace sont versionnees dans `.vscode/extensions.json`.

Installation rapide avec le CLI `code` sur la machine locale:

```bash
code --install-extension ms-vscode-remote.remote-ssh
code --install-extension ms-python.python
code --install-extension ms-python.vscode-pylance
code --install-extension TeamsDevApp.ms-teams-vscode-extension
```

Si l'IT active ensuite `GitHub Copilot` pour ton compte:

```bash
code --install-extension GitHub.copilot
code --install-extension GitHub.copilot-chat
```

## Procedure recommandee

1. Se connecter au reseau de l'entreprise ou au `VPN Fortinet`.
2. Ouvrir `VS Code` sur le poste local, pas sur le serveur distant.
3. Installer l'extension `Remote - SSH`, puis se connecter a `eliodev` via `Remote-SSH: Connect to Host...`.
4. Une fois connecte, lancer sur le serveur distant:

```bash
bash /home/ubuntu/sib-work/scripts/check_vscode_remote_prereqs.sh
```

5. Si le serveur distant a un acces HTTPS sortant limite, relancer avec le test reseau optionnel:

```bash
bash /home/ubuntu/sib-work/scripts/check_vscode_remote_prereqs.sh --check-network
```

6. Laisser `VS Code` installer `VS Code Server` et les extensions au bon endroit. Les extensions s'installent automatiquement localement ou a distance selon leur nature.
7. Si `eliodev` n'a pas d'acces Internet sortant, definir sur la machine locale le reglage suivant dans `settings.json`:

```json
{
  "remote.SSH.localServerDownload": "always"
}
```

8. Si l'entreprise utilise un proxy, prevoir la configuration:
   - cote local dans les reglages `VS Code`
   - cote distant via les variables `HTTP_PROXY`, `HTTPS_PROXY` et `NO_PROXY` si l'extension ou le serveur distant doit sortir en HTTPS
9. Si l'objectif est de developper pour `Microsoft 365 Copilot`, ouvrir `Microsoft 365 Agents Toolkit` dans `VS Code` et se connecter avec le compte `Microsoft 365` d'entreprise.
10. Si l'objectif est d'avoir un assistant IA de code dans l'editeur sur le serveur distant, demander a l'IT une licence `GitHub Copilot Business` ou `GitHub Copilot Enterprise`.

## Ce qui fonctionne sans droits admin

- `Remote - SSH` fonctionne en pratique si le compte SSH peut ecrire dans son repertoire utilisateur.
- `VS Code Server` s'installe sous le profil utilisateur distant, typiquement dans `~/.vscode-server/`.
- Le script `scripts/check_vscode_remote_prereqs.sh` verifie les preconditions minimales sans exiger de privileges admin.

## Checklist de validation

- La connexion `Remote - SSH` ouvre bien le dossier de travail distant.
- Le serveur distant peut ecrire dans `~/.vscode-server/`.
- Les outils `bash`, `tar`, et `curl` ou `wget` sont disponibles.
- Une distribution Linux compatible `glibc` est detectee.
- L'icone `Microsoft 365 Agents Toolkit` apparait dans `VS Code` si cette extension est installee.
- Si `GitHub Copilot` est attribue plus tard, `GitHub Copilot Chat` et les suggestions inline fonctionnent dans une fenetre distante.

## Sources officielles

- GitHub Copilot quickstart: <https://docs.github.com/en/copilot/get-started/quickstart>
- VS Code `Remote - SSH`: <https://code.visualstudio.com/docs/remote/ssh>
- VS Code Server: <https://code.visualstudio.com/docs/remote/vscode-server>
- Microsoft 365 Agents Toolkit: <https://learn.microsoft.com/en-us/microsoftteams/platform/teams-sdk/teams/configuration/agents-toolkit>
- Installation de `Microsoft 365 Agents Toolkit`: <https://learn.microsoft.com/en-us/microsoftteams/platform/toolkit/install-agents-toolkit>
- Exemple de connecteur `Microsoft 365 Copilot`: <https://learn.microsoft.com/en-us/training/modules/build-your-first-microsoft-365-copilot-connector/>
