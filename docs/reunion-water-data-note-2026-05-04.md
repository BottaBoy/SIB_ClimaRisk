# Note Reunion - donnees eau recues, comparaison Guadeloupe, valorisation

Date: 2026-05-04

## 1. Resume executif

- Les donnees EU Reunion sont nombreuses et globalement suffisantes pour construire une premiere base SIB sur l'assainissement: reseaux lineaires, postes de refoulement, STEP, et de nombreuses couches techniques de detail.
- Le principal manque par rapport a la Guadeloupe concerne l'AEP. Je n'ai identifie ni couche explicite de captages/forages, ni reservoirs/cuves, ni stations de pompage AEP, ni usines de traitement. Le seul reseau AEP apparent (`AC_Reseau_Existant_Reunion.shp`) semble etre un reseau principal/adduction ancien et tres incomplet pour une analyse SIB complete.
- Les couches EU sont heterogenes et partiellement redondantes: `ass_arc`/`ass_noeud` (CISE 2020), `sp_*`/`tb_*` (base EU janvier 2024), `PR_974.shp` (2018, plus ancien). Une harmonisation et un dedoublonnage seront necessaires avant integration.
- Cote qualite spatiale, j'ai corrige le CRS manquant de `AC_Reseau_Existant_Reunion.shp` en `EPSG:2975`. Pour `PR_974.shp`, le CRS global est correct, mais un point est hors Reunion (`OBJECTID=41`, `Beau Rivage`) et un enregistrement source est marque comme supprime. J'ai donc produit une copie preparee `uploads/Docs Reunion/sib_prepared/PR_974_filtered.gpkg` (220 points exploitables) et isole l'anomalie dans `uploads/Docs Reunion/sib_prepared/PR_974_outliers.geojson`.

## 2. Corrections CRS et QA appliquees

| Element | Diagnostic | Action appliquee | Resultat |
|---|---|---|---|
| `AC_Reseau_Existant_Reunion.shp` | Couche sans `.prj`, mais coordonnees clairement en RGR92 / UTM 40S | Ajout du fichier `AC_Reseau_Existant_Reunion.prj` en `EPSG:2975` | GDAL reconnait maintenant correctement `EPSG:2975` |
| `PR_974.shp` | Le CRS de la couche est deja `EPSG:2975`, mais un point (`OBJECTID=41`, `Beau Rivage`) a une ordonnee aberrante `15294801.8039` et se projette hors Reunion | Pas de reprojection globale. Creation d'une copie analytique filtree et extraction de l'anomalie a part | `PR_974_filtered.gpkg` contient 220 points valides; `PR_974_outliers.geojson` contient l'anomalie; 1 enregistrement source marque supprime reste non exploitable automatiquement |

## 3. Inventaire logique des fichiers recus

Lecture: la colonne "Inclusion recommandee" indique si la couche merite d'etre integree directement dans une V1 SIB, gardee pour raffinement, ou simplement archivee comme source de controle.

| Fichier | Type d'infrastructure concerne | Inclusion recommandee |
|---|---|---|
| `AC_Reseau_Existant_Reunion.shp` | AEP reseau principal / adduction existante (19 lignes, 2014) | Oui - essentiel mais incomplet |
| `EU_CISE_2020_11.zip` | Archive du lot CISE 2020 contenant `ass_arc` et `ass_noeud` | Non - archive doublon |
| `PR_974.shp` | EU postes de refoulement (couche 2018 de sensibilite / repere) | Oui - utile mais secondaire face aux couches 2024 |
| `STEP_rejets.gpkg` | EU points de rejet des STEP | Non - utile pour contexte environnemental, pas prioritaire pour l'exposition d'actifs |
| `STEP_stations.gpkg` | EU stations de traitement / STEU / STEP (16 points) | Oui - essentiel |
| `ass_arc.shp` | EU reseau principal / arcs de collecte CISE 2020 (8393 lignes) | Oui - essentiel |
| `ass_noeud.shp` | EU noeuds du reseau CISE 2020 (regards, postes, dessableurs, STEP, etc.) | Oui - utile pour raffinement et controle |
| `bdd eu janvier 2024.7z` | Archive du lot detaille `sp_*` / `tb_*` | Non - archive doublon |
| `francetransfert-148083899.zip` | Archive de zonage PPR approuve | Non - hors perimetre infrastructure |
| `francetransfert-40893135.zip` | Archive conteneur regroupant AC, CISE 2020, PR, STEP et la base EU 2024 | Non - archive doublon |
| `points_rejets_mayotte_20230302.geojson` | Points de rejet Mayotte | Non - hors territoire Reunion |
| `ppr_approuvePolygon.shp` | Zonage PPR / couche reglementaire d'alea | Non - ce n'est pas une infrastructure |
| `sp_eu_REUSE.shp` | EU / REUSE lineaire (reutilisation d'eaux usees) | Oui - utile, mais optionnel au regard du perimetre SIB actuel |
| `sp_eu_anti_belier.shp` | Equipements anti-belier EU | Non - secondaire exploitation |
| `sp_eu_autonomegroupe_boite_branchement.shp` | EU non collectif / boites de branchement | Non - secondaire exploitation |
| `sp_eu_autonomegroupe_canalisation.shp` | EU non collectif / canalisations locales | Oui - utile mais a confiance plus faible |
| `sp_eu_autonomegroupe_epandage.shp` | EU non collectif / zones d'epandage | Non - secondaire pour SIB actuel |
| `sp_eu_autonomegroupe_ouvrage.shp` | EU non collectif / ouvrages divers | Non - utile seulement si une regle de valorisation est definie |
| `sp_eu_autonomegroupe_regard.shp` | EU non collectif / regards | Non - secondaire exploitation |
| `sp_eu_autosurveillance.shp` | EU points d'autosurveillance | Non - secondaire exploitation |
| `sp_eu_clapet.shp` | EU clapets | Non - secondaire exploitation |
| `sp_eu_collectif_boite_branchement.shp` | EU collectif / boites de branchement | Non - secondaire exploitation |
| `sp_eu_collectif_canalisation.shp` | EU collectif / canalisations detaillees (22931 lignes) | Oui - essentiel |
| `sp_eu_collectif_regard.shp` | EU collectif / regards | Non - secondaire exploitation |
| `sp_eu_cone.shp` | EU equipements type cone | Non - secondaire exploitation |
| `sp_eu_coude.shp` | EU pieces type coude | Non - secondaire exploitation |
| `sp_eu_dessableur.shp` | EU dessableurs | Oui - utile, mais non essentiel en V1 |
| `sp_eu_plaque_pleine.shp` | EU equipements plaque pleine | Non - secondaire exploitation |
| `sp_eu_poste_refoulement.shp` | EU postes de refoulement detailles (106 points, base 2024) | Oui - essentiel |
| `sp_eu_regard_chasse.shp` | EU regard de chasse | Non - secondaire exploitation |
| `sp_eu_te.shp` | EU tees / tees de curage | Non - secondaire exploitation |
| `sp_eu_vanne.shp` | EU vannes | Non - secondaire exploitation |
| `sp_eu_ventouse.shp` | EU ventouses | Non - secondaire exploitation |
| `sp_eu_vidange.shp` | EU vidanges | Non - secondaire exploitation |
| `tb_eu_autonomegroupe_boite_branchement.shp` | EU non collectif / boites de branchement, sous-ensemble local | Non - secondaire / sous-ensemble local |
| `tb_eu_autonomegroupe_canalisation.shp` | EU non collectif / canalisations, sous-ensemble local | Oui - utile mais sous-ensemble local |
| `tb_eu_autonomegroupe_epandage.shp` | EU non collectif / epandage, sous-ensemble local | Non - secondaire |
| `tb_eu_autonomegroupe_regard.shp` | EU non collectif / regards, sous-ensemble local | Non - secondaire |
| `tb_eu_collectif_boite_branchement.shp` | EU collectif / boites de branchement, sous-ensemble local | Non - secondaire |
| `tb_eu_collectif_canalisation.shp` | EU collectif / canalisations, sous-ensemble local | Oui - utile mais sous-ensemble local |
| `tb_eu_collectif_regard.shp` | EU collectif / regards, sous-ensemble local | Non - secondaire |
| `tb_eu_poste_refoulement.shp` | EU postes de refoulement, sous-ensemble local | Oui - utile mais sous-ensemble local |

## 4. Comparaison Reunion vs Guadeloupe (territoire de reference "complet")

Reference Guadeloupe utilisee par SIB aujourd'hui:

- AEP lineaire: `AEP/cana_aep.gpkg`, couche `canalisationaep240925`, 31 942 objets.
- AEP ouvrages: `AEP/ouvrage_aep.gpkg`, couche `ouvrages`, 440 objets. Types dominants: `CUV`, `STPMP`, `CAP`, `TRAIT`, `OUVEB`.
- EU lineaire: `EU/cana_eu.gpkg`, couche `conduites`, 13 795 objets.
- EU postes de refoulement: `EU/pr.gpkg`, couche `eu_pr`, 348 objets.
- EU STEP: `EU/step.gpkg`, couche `eu_stepn`, 142 objets.

### 4.1 Tableau de parite eau

| Classe SIB attendue | Guadeloupe "complete" | Reunion disponible | Diagnostic |
|---|---|---|---|
| AEP canalisations | Oui, couche lineaire dense et sectorisee | Partiel: `AC_Reseau_Existant_Reunion.shp` (19 lignes), probablement reseau principal / adduction seulement | Donnee essentielle encore incomplete. Il faut une couche AEP de distribution plus complete |
| AEP ouvrages | Oui, 440 ouvrages avec typologie exploitable (`CUV`, `STPMP`, `CAP`, `TRAIT`, etc.) | Aucune couche explicite identifiee dans le lot Reunion | Manque majeur. A ajouter prioritairement |
| EU canalisations | Oui | Oui, avec plusieurs niveaux de detail (`ass_arc`, `sp_eu_collectif_canalisation`, `tb_*`, plus autonome) | Disponible, mais harmonisation / dedoublonnage necessaires |
| EU postes de refoulement | Oui | Oui (`sp_eu_poste_refoulement`, `tb_eu_poste_refoulement`, `PR_974`) | Disponible, mais les sources sont heterogenes et partiellement redondantes |
| EU STEP | Oui | Oui (`STEP_stations.gpkg`) | Disponible |
| EU noeuds / details techniques | Partiellement implicite dans les couches de reference | Oui, en abondance (`ass_noeud`, regards, vannes, clapets, dessableurs, etc.) | Reunion est plus riche que la Guadeloupe sur ce niveau de detail, mais SIB n'en a pas besoin en V1 |
| Points de rejet / couches environnementales | Non centrales pour la valorisation SIB | Oui (`STEP_rejets.gpkg`) | Utiles pour contexte, pas prioritaires pour la base d'actifs |

### 4.2 Conclusion de completude

Sur l'eau, la Reunion n'est pas encore au niveau de completude Guadeloupe pour SIB, non pas a cause de l'assainissement, mais a cause de l'AEP.

Donnees a ajouter explicitement pour atteindre une parite raisonnable:

1. Une couche AEP lineaire complete (reseau de distribution et non seulement tronc principal / adduction).
2. Une couche d'ouvrages AEP avec une typologie claire: captages/forages, reservoirs/cuves, stations de pompage, usines de traitement.
3. Si possible, les identifiants de secteurs / zones hydrauliques / systemes AEP, pour permettre une chaine comparable a la Guadeloupe.
4. Un schema de dedoublonnage ou d'arbitrage entre `ass_arc` / `sp_*` / `tb_*` / `PR_974`, sinon les comptages et valeurs seront sur-estimes.

### 4.3 Note rapide hors perimetre eau

Dans `uploads/ElecInfra`, un controle rapide montre deja pour la Reunion des couches `BT aerien`, `BT souterrain` et `HTA souterrain`. Je n'ai pas vu de couche `HTA aerien` dans le listing courant; il faut donc confirmer son existence avant de viser une parite inter-secteurs complete eau + electricite.

## 5. Estimation de la valeur monetaire des infrastructures Reunion

Important: les valeurs eau actuellement codees dans `scripts/valuation_ofb.py` n'existent que pour la Guadeloupe et la Martinique. En l'etat, le moteur SIB appliquerait une logique de repli Guadeloupe hors de ces deux territoires. Les valeurs ci-dessous doivent donc etre lues comme des proxies provisoires, pas comme des valeurs Reunion validees localement.

Valeurs SIB existantes mobilisables aujourd'hui:

- AEP canalisations: `776 386 EUR/km` (proxy Guadeloupe)
- EU canalisations: `791 691 EUR/km` (proxy Guadeloupe)
- EU postes de refoulement: `523 211 EUR/unite` (proxy Guadeloupe)
- EU STEP: `7 777 800 EUR/unite` (proxy Guadeloupe)
- AEP ouvrages par type: `TRAIT=3.5 M`, `STPMP=1.2 M`, `CAP=1.0 M`, `CUV=0.5 M`, autres `0.8 M` EUR

| Infrastructure / couche Reunion | Regle de valorisation mobilisable | Valeur unitaire candidate | Niveau de confiance | Commentaire |
|---|---|---|---|---|
| `AC_Reseau_Existant_Reunion.shp` | AEP canalisations | `776 386 EUR/km` | Faible a moyenne | Le type AEP lineaire est plausible, mais la couche semble partielle et proche d'un reseau principal/adduction plutot que d'un reseau complet |
| `ass_arc.shp` | EU canalisations | `791 691 EUR/km` | Moyenne | Bonne identification comme reseau EU principal, mais version 2020 a arbitrer face aux couches 2024 |
| `sp_eu_collectif_canalisation.shp` | EU canalisations | `791 691 EUR/km` | Moyenne a elevee | Typologie explicite et couche detaillee, probablement la meilleure base lineaire EU actuellement recue |
| `tb_eu_collectif_canalisation.shp` | EU canalisations | `791 691 EUR/km` | Moyenne | Valorisable, mais seulement comme sous-ensemble local |
| `sp_eu_autonomegroupe_canalisation.shp` | EU canalisations (proxy) | `791 691 EUR/km` | Faible | Valorisation possible par analogie, mais la couche semble relever d'un sous-systeme autonome / local non cible explicitement par les regles SIB actuelles |
| `tb_eu_autonomegroupe_canalisation.shp` | EU canalisations (proxy) | `791 691 EUR/km` | Faible | Meme reserve que ci-dessus, avec en plus un perimetre local |
| `sp_eu_poste_refoulement.shp` | EU postes de refoulement | `523 211 EUR/unite` | Elevee | Typologie explicite, couche detaillee et recente |
| `tb_eu_poste_refoulement.shp` | EU postes de refoulement | `523 211 EUR/unite` | Moyenne | Valorisable, mais seulement comme sous-ensemble local |
| `PR_974_filtered.gpkg` | EU postes de refoulement | `523 211 EUR/unite` | Faible a moyenne | La typologie est explicite, mais la source est plus ancienne, heterogene et comporte une anomalie spatiale extraite a part |
| `STEP_stations.gpkg` | EU STEP / STEU | `7 777 800 EUR/unite` | Moyenne a elevee | La couche identifie clairement des STEU/STEP avec metadonnees riches (nature, capacite, filiere) |
| `STEP_rejets.gpkg` | Aucune regle directe SIB actuelle | n/a | n/a | Point de rejet, utile pour contexte mais pas pour une valorisation d'actif sous les regles actuelles |
| `ass_noeud.shp` | Pas de regle directe SIB actuelle | n/a | n/a | Peut servir a reconstituer ou controler des actifs PR/STEP/ouvrages, mais pas a valoriser directement en l'etat |
| `sp_eu_dessableur.shp` | Pas de regle directe SIB actuelle | n/a | n/a | Type d'ouvrage identifiable, mais aucune valeur par unite n'est codee aujourd'hui |
| `sp_eu_REUSE.shp` | Pas de regle directe SIB actuelle | n/a | n/a | Reseau potentiellement important, mais hors classes de valorisation SIB actuelles |

### 5.1 Ce qui manque pour une valorisation Reunion plus robuste

1. Des valeurs OFB ou locales Reunion pour l'eau, au minimum par classe `AEP cana`, `EU cana`, `PR`, `STEP`.
2. Une couche AEP ouvrages Reunion typable selon une nomenclature proche de `CAP`, `CUV`, `STPMP`, `TRAIT`.
3. Une regle explicite pour les sous-systemes EU autonomes et, si souhaitable, pour certains ouvrages EU secondaires (`dessableur`, `REUSE`, etc.).
4. Un dedoublonnage des sources EU avant valorisation, sinon une meme infrastructure pourrait etre comptee plusieurs fois.
