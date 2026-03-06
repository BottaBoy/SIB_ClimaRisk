# Note interne - Parite Guadeloupe / Martinique

Regle de travail:
- Toute modification fonctionnelle appliquee a la page etude de cas Guadeloupe doit etre appliquee aussi a la page etude de cas Martinique.

Checklist minimale avant commit/deploiement:
- Verifier le rendu des deux pages (`#page1` et `#page2`) avec les memes composants (textes, tableaux, cartes, graphes, controles).
- Regenerer les artefacts data des deux territoires quand un script de calcul ou de transformation est modifie.
- Verifier la coherence des options UI communes (couches, filtres, transparence, unites, echelles).
- Verifier que les labels/metriques restent homogenes entre Guadeloupe et Martinique.
- Controler les deux domaines vitrine apres deploiement (`sib.dev` et `visu.sib.dev`).
