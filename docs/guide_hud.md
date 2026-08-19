# Guide du HUD — de l'installation au premier affichage

## En résumé

Le HUD affiche un panneau de statistiques au-dessus du siège de chaque
joueur. Pour qu'un panneau apparaisse, **trois conditions** doivent être
réunies en même temps :

1. des **mains en base** pour les joueurs concernés (le HUD ne montre que ce
   qui a déjà été joué et importé) ;
2. une **table détectée** — une fenêtre de table de votre client de poker,
   ou la table de démonstration fournie ;
3. la case **« HUD activé »** cochée dans l'onglet HUD.

L'onglet HUD affiche en permanence, sous « Tables détectées », une ligne de
diagnostic qui dit laquelle de ces trois conditions manque.

---

## Étape 1 — importer des mains

Onglet **Import** :

1. « Détecter automatiquement » (ou « Ajouter un dossier… » si votre room
   n'est pas trouvée) ;
2. « Importer maintenant » ;
3. laisser **« Import automatique en temps réel »** coché — c'est ce qui
   alimente le HUD pendant que vous jouez.

Vérifiez la barre d'état en bas de la fenêtre : `Mains: 1234 · Joueurs: 87`.
Si le compteur est à zéro, aucun panneau ne pourra s'afficher.

> Pas encore d'historique sous la main ? Générez des mains de démonstration :
> `python tools/generate_demo_hands.py --hands 3000 --out demo/HandHistory_demo.txt`
> puis importez le dossier `demo`.

## Étape 2 — essayer sur la table de démonstration

Onglet **HUD** :

1. cocher **« HUD activé »** ;
2. cliquer sur **« Ouvrir une table de démonstration »**.

Une fausse table s'ouvre, reprenant le nom et le nombre de joueurs de la
dernière table réellement jouée, et les panneaux se posent dessus
immédiatement. C'est le moyen le plus rapide de vérifier que tout
fonctionne, sans ouvrir de client de poker.

Sur cette table, vous pouvez déjà :

- **déplacer un panneau** à la souris — la position est mémorisée pour cette
  table et ce siège (bouton « Réinitialiser les positions » pour repartir de
  zéro) ;
- **survoler un panneau** pour ouvrir le popup détaillé (préflop, flop,
  turn, river, global, et un tableau par position) ;
- **clic droit** sur un panneau : statistiques détaillées, note sur le
  joueur, masquer le panneau ;
- **survoler une statistique** pour lire son nom complet.

## Étape 3 — jouer

Ouvrez vos tables dans votre client habituel. Le HUD :

- détecte les fenêtres de table à leur titre, plusieurs tables en parallèle ;
- suit la fenêtre quand vous la déplacez ou la redimensionnez ;
- masque les panneaux d'une table réduite dans la barre des tâches ;
- se met à jour à chaque main importée (donc à la fin de chaque main).

Au démarrage du logiciel, les dernières tables jouées sont restaurées
automatiquement : le HUD est utilisable dès le lancement, sans attendre la
fin d'une main.

---

## Si aucun panneau ne s'affiche

| Message de diagnostic (onglet HUD) | Ce qu'il faut faire |
|---|---|
| « HUD désactivé » | Cocher « HUD activé ». |
| « Aucune main en base » | Importer vos historiques (onglet Import). |
| « Aucune table de poker détectée » | Ouvrir une table, ou cliquer sur « Ouvrir une table de démonstration ». Si votre table est ouverte mais non détectée, voir ci-dessous. |
| « Table détectée mais aucun joueur reconnu » | Aucune main n'a encore été jouée à cette table, ou le réglage « Mains minimum » est trop élevé (mettez-le à 0). |
| « N table(s) suivie(s), M panneau(x) affiché(s) » | Tout va bien : les panneaux sont là. S'ils sont hors écran, cliquez sur « Réinitialiser les positions des panneaux ». |

Autres points à vérifier :

- **La room écrit-elle ses historiques ?** Dans les options du client, la
  sauvegarde des historiques de mains doit être activée, sinon aucun fichier
  n'est créé et le HUD n'a rien à afficher.
- **Table non détectée** : la reconnaissance se fait sur le titre de la
  fenêtre. Les motifs sont dans `pokertracker/hud/table_tracker.py`
  (`ROOM_PATTERNS`) ; en ajouter un suffit pour prendre en charge un client
  dont les titres sortent de l'ordinaire.
- **Client lancé en administrateur** : si votre client de poker tourne en
  administrateur et pas PokerTracker, Windows empêche la superposition.
  Lancez les deux de la même façon.
- **Mode plein écran** : certaines tables en plein écran passent devant les
  fenêtres superposées. Utilisez le mode fenêtré.

---

## Régler ce que le HUD affiche

Tout se passe dans la moitié basse de l'onglet HUD.

- **Profil** : `Cash 6-max`, `Heads-up` ou `Tournois` sont fournis ;
  « Nouveau » crée le vôtre, « Enregistrer » le sauvegarde dans la base.
- **Panneaux** : un profil en contient plusieurs, dans l'ordre. Pour chaque
  joueur, **le premier panneau dont la condition est vraie est affiché**.
  C'est le HUD dynamique.
- **Condition d'affichage** : position occupée à la main suivante, nombre de
  joueurs, profondeur de tapis en bb, nombre de mains minimum.
- **Statistiques filtrées sur** : `all` (toutes les mains) ou `position` —
  dans ce cas, les statistiques ne comptent que les mains jouées à la
  position actuelle du joueur (l'échantillon affiché est donc plus petit :
  c'est normal).
- **Statistiques du panneau** : ligne d'affichage, libellé personnalisé,
  échantillon minimum (en dessous, la valeur est masquée) et seuils de
  coloration bas/haut.

Exemple fourni par défaut (profil `Cash 6-max`) :

| Panneau | Condition | Effet |
|---|---|---|
| Tapis court | tapis ≤ 25 bb | panneau resserré, orienté vol/défense |
| Défense des blindes | position SB ou BB | statistiques **filtrées sur la position** |
| Principal | toujours vrai | affichage standard |

## Argent réel uniquement

Par défaut, le HUD (comme le reste du logiciel) ne compte que les mains
jouées en **argent réel** : les tables en argent fictif sont reconnues et
écartées. Pour les inclure ponctuellement dans les rapports, cochez
« Inclure l'argent fictif » dans la barre de filtres de l'onglet concerné.

## Réglages généraux

- **Opacité** : transparence des panneaux (0,2 à 1).
- **Mains minimum pour afficher un joueur** : masque les inconnus.
- **Popup au survol** : sinon, le popup s'ouvre au clic droit.
