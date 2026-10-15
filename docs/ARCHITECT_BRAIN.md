# ARCHITECT_BRAIN — mémoire architecturale de Hivora

*Créé le 29/09/2026, à la suite du découpage de `AppService` ; mis à jour le même jour après le découpage de `apps/api.py`, puis le 12/10/2026 (état des lieux après les lots K et R : §7, §13), puis le 14/10/2026 (règles de la distribution, M12-0 à M12-4b : §11, §14, §15).*

Ce document garde **pourquoi** le code est organisé ainsi, et les règles qui empêchent de retomber dans les travers corrigés. Il complète :

- `CLAUDE.md` : règles non négociables (sécurité, budgets, stack) ;
- `docs/vision-prd-architecture.md` : référence produit et architecture cible ;
- `docs/PROGRESS.md` : historique daté de chaque étape.

En cas de contradiction, `CLAUDE.md` l'emporte, puis le document de référence, puis celui-ci. Toute contradiction se signale avant de coder.

---

## 0. Contexte : le découpage de `AppService` (29/09/2026)

### Point de départ

**Rapport Graphify** du 28/09 (commit `f91b3df`) : 3 160 nœuds, 8 621 liens, aucun cycle d'import détecté.

| Constat | Détail |
|---|---|
| `AppService` | 4e nœud le plus connecté (57 liens) ; seul vrai « god object » du backend |
| `apps/service.py` | 1 038 lignes, une classe de 45 méthodes, 12 dépendances injectées, 11 types |
| Autres services trop gros | `apps/api.py` (647), `vpn/service.py` (492), `hostfw/service.py` (356), `topology-view.tsx` (~540) |
| Écarts aux règles | mutations VPN / pare-feu / listes de jeux hors `jobs` ; `Runtime` utilisé comme annuaire de services, avec un cycle caché par imports différés ; états globaux de module |

### Étapes réalisées

| Étape | Commit | Contenu | `service.py` | Classe `AppService` |
|---|---|---|---|---|
| départ | — | — | 1 038 | ~770 |
| 1 | `29ccdb6` | `apps/core.py` : `store_secrets`, `queue_revision` (duplication supprimée) | 1 007 | ~740 |
| 2 | `0cfecb9` | `apps/custom_images.py` : `CustomImages` | 953 | 697 |
| 3 | `4790752` | `apps/adoption.py` : `Adoption` | 874 | 654 |
| 4 | `e1e6263` | `apps/compose_edit.py` : `ComposeEdit` (+ requêtes partagées dans `core`) | 767 | 598 |
| 5a | `1c4e4fc` | `AppPlanner` dans `core.py` (compilation partagée) | 593 | 471 |
| 5b | `705031f` | `apps/revisions.py` : `Revisions` | 412 | 320 |
| 6 | `76aae69` | `apps/lifecycle.py` : `Deployer` + `Lifecycle` (deux classes pour rester sous 10 dépendances) | 315 | 236 |

À chaque étape : 208 tests backend, `mypy` strict, `ruff`, parcours e2e, tous verts, **sans aucune modification de test ni de route**.

### Graphe obtenu (sans cycle)

```
core  ←  custom_images
core  ←  adoption
core  ←  compose_edit ←─┐
core  ←  revisions ─────┤→ custom_images
core  ←  lifecycle
service (façade AppService) → tous
```

### Problèmes rencontrés et leur leçon

| Problème | Leçon devenue règle |
|---|---|
| Un sous-module avait besoin d'un type défini dans `service.py` (`DeployRequest`, `PortConflictError`, `DeployPlan`…) : import circulaire | Les types et erreurs partagés vivent dans le module racine (`core`), jamais dans la façade (§4) |
| `mypy` strict refuse les réexports implicites | Réexport explicite `from x import Y as Y` dans la façade (§10) |
| Des tests modifient l'intérieur de l'objet (`rt.apps.registry = …`, `rt.apps._inspected.clear()`) | Avant de déplacer un attribut, chercher qui le lit **et qui l'écrit** ; garder une propriété avec setter qui pointe sur le même objet (§10) |
| Dépendance cachée : `remove()` → `vpns_reaching()` → `current_settings()` | Tracer les appels de chaque méthode déplacée avant de choisir sa destination ; une lecture partagée va dans le socle (§5) |
| Deux fois, une commande de tests « ciblés » a affiché `no tests ran` (fichier inexistant, liste mal formée) | Un résultat de tests sans nombre de tests passés ne vaut rien (§10) |
| `core.py` a grossi à 340 lignes en recevant `AppPlanner` | Un socle a aussi un seuil ; le dépasser déclenche une extraction dédiée (§7, §12) |
| Crash « database is locked » (28/09) : transaction SQLite ouverte pendant un `docker exec` WireGuard | Jamais d'I/O externe (Docker, réseau, sous-processus) dans une transaction d'écriture (§9) |

### Suite : le découpage de `apps/api.py` (29/09/2026)

`apps/api.py` (647 lignes, 27 routes, 30 modèles) est devenu le paquet `apps/api/`, **un fichier de routes par sous-service** :

| Étape | Commit | Contenu | `__init__.py` |
|---|---|---|---|
| 1 | `324d38b` | paquet `apps/api/` + `common.py` (modèles et conversions partagés, réexportés pour `pyapps` et `backups`) | 563 |
| 2 | `13ecbec` | `adoption.py`, `lifecycle.py` (2 routeurs), `compose_edit.py` | 486 |
| 3 | `0af93c8` | `deploy.py` (2 routeurs + `POST ""` enregistré par le parent) | 390 |
| 4 | `465971b` | `revisions.py` (2 routeurs ; contournement `ZoneIn`) | 262 |
| 5 | `e283b3f` | `queries.py` (`GET ""` enregistré par le parent) | 56 |

Préalable (`4ca33ed`) : `frontend/lib/api/openapi.json` n'était plus à jour depuis le lot I (3 routes pare-feu absentes), régénéré avant tout.

À chaque étape : **ordre des 27 routes identique** (méthode, chemin, nom comparés ligne à ligne), **schéma OpenAPI identique octet par octet et en contenu**, 208 tests, `mypy`, `ruff`, e2e.

Leçons ajoutées :

| Problème | Leçon devenue règle |
|---|---|
| Les routes d'un même sous-domaine sont réparties dans l'ordre public (`zone` entre les actions et la suppression, `/plan` avant l'adoption…) | L'ordre d'enregistrement est l'ordre de recherche de FastAPI : on le garde, avec **plusieurs routeurs par fichier** s'il le faut, jamais en réordonnant (§10) |
| FastAPI refuse une route au chemin vide (`""`) dans un routeur inclus sans préfixe | La fonction vit dans son fichier, le routeur parent l'enregistre à son rang (`router.post("")(deploy.deploy)`) |
| Deux modèles `ZoneIn` (apps, zones) : FastAPI nomme alors leur schéma d'après le module ; déplacer la classe renommait le schéma public | Vérifier l'unicité des noms de modèles déplacés ; en cas de doublon, `__module__` fixé **dans le corps de la classe** (après la création, c'est trop tard) ou renommage dans un commit séparé qui change le contrat |
| `openapi.json` versionné était périmé : la comparaison au schéma versionné aurait masqué un écart | Comparer aussi au schéma exporté depuis `HEAD` (copie de travail propre) ; régénérer le fichier versionné dès qu'une route change (§10) |
| Un échec e2e isolé n'a pas pu être expliqué : seule la dernière ligne de sortie était gardée | Conserver la sortie complète de l'e2e dans un fichier ; un échec non expliqué se signale, ne s'efface pas en relançant (§10) |

### Bilan des deux découpages (29/09/2026, commit `8986592`)

Rapport complet : `.report/architecture-apres-decoupage-2026-09-29.md` (local, non versionné).

| | Rapport initial (28/09, `f91b3df`) | Après les découpages |
|---|---|---|
| Graphe Graphify | 3 160 nœuds, 8 621 liens, 216 communautés, aucun cycle | 3 403 nœuds, 9 219 liens, 261 communautés, aucun cycle détecté |
| `apps/service.py` | 1 038 lignes, classe ~770, 45 méthodes, 12 dépendances | 315 lignes, classe 236 (façade de relais) |
| Logique métier des apps | une classe | 7 fichiers de 97 à 340 lignes, 10 dépendances au plus par classe |
| `apps/api.py` | 647 lignes, 27 routes, 30 modèles | 8 fichiers de 35 à 225 lignes (`__init__.py` : 56) |
| Duplication (secrets, séquence révision → job) | 2 à 3 copies | une seule (`store_secrets`, `queue_revision`) |
| Contrat API et tests | — | inchangés à chaque étape (OpenAPI octet par octet, ordre des routes, 208 tests, aucun test modifié) |

**God Objects** : `AppService` et `apps/api.py` ne le sont plus. `AppService` garde 62 liens dans Graphify (57 au départ), parce qu'une façade reste reliée à chaque sous-service et à chaque relais ; ce chiffre ne baissera qu'avec l'étape 7. Aucun nouveau God Object.

**Écarts restants aux règles de ce document**, vérifiés dans le code : détaillés au §4 (dépendances), §7 (tailles et priorités) et §8 (`Runtime`, états globaux). S'y ajoutent les **routes non fines** (§1.5) :

- 13 routes lisent la base directement : `GET /apps`, `/apps/{id}`, `/compose`, `/revisions`, `/settings` (`apps/api`), `GET /apps/{id}/backups`, `GET /jobs`, `/jobs/{id}`, `GET /audit` ;
- 9 routes y écrivent directement, ce qui est plus grave : `DELETE /audit`, `DELETE /jobs`, les 6 routes d'édition de `/topology` (nœuds, liens, disposition), `DELETE /zones/{slug}`.

---

## 1. Principes fondamentaux d'architecture

1. **Docker = vérité de l'état réel, SQLite = vérité de l'intention.** L'état d'exécution vit en mémoire, alimenté par Docker ; rien d'exécutable n'est persisté.
2. **Monolithe modulaire.** Un processus, des modules aux frontières explicites, un graphe de dépendances **orienté et sans cycle**.
3. **Seuls `docker_gateway` et `compose_runner` touchent le socket Docker.** Tout le reste passe par eux.
4. **Toute mutation passe par `jobs`**, avec un verrou par application. Une mutation hors job est une dette déclarée, jamais un choix silencieux.
5. **Routes HTTP fines, logique dans des services testables sans Docker réel** (gateway et compose factices).
6. **Façades stables, intérieurs libres.** Un module expose une surface publique stable. Son intérieur peut être redécoupé sans toucher aux appelants (principe démontré par le découpage de `AppService`).
7. **Chaque classe reçoit ce qu'elle utilise, rien de plus.** Pas de conteneur global passé partout.
8. **Le code déplacé reste identique.** Un refactoring de structure ne change aucun comportement ; un changement de comportement est un commit séparé.
9. **Simple par défaut, le plus court chemin qui fonctionne.** Pas d'abstraction à une seule implémentation, pas d'échafaudage « pour plus tard ».

## 2. Ce qui a conduit `AppService` à devenir un God Object

1. **Le point d'entrée évident.** « Tout ce qui concerne une app » était un critère trop large. Chaque fonction (adoption, images libres, compose manuel, montée de version, restauration, zones, VPN) s'est ajoutée à la classe existante, parce que c'était le chemin le plus court sur le moment.
2. **L'accès gratuit aux dépendances.** Avec 12 dépendances déjà injectées, ajouter une méthode ne coûtait rien : tout était déjà là. Le coût d'une nouvelle responsabilité était invisible.
3. **Des types définis au mauvais endroit.** `DeployRequest`, `PortConflictError`, `DeployPlan` vivaient dans `service.py`. Tout nouveau code qui en avait besoin importait `service`, ce qui renforçait l'attraction.
4. **La duplication plutôt que l'extraction.** Le chiffrement des secrets et la séquence « services → révision → job » ont été copiés (`deploy`, `update`, `apply_compose`), faute d'un endroit neutre où les mettre.
5. **Des méthodes privées devenues du code partagé.** `_plan`, `_entry_of`, `_template_version` étaient privées de nom, mais utilisées par plusieurs sous-domaines. La classe ne pouvait plus être découpée sans les sortir d'abord.
6. **Des modules externes branchés sur la classe entière.** `vpn`, `games`, `topology`, `pyapps`, `backups`, `tasks` et `realtime` appellent `rt.apps.*`. Chaque nouvel appelant rendait la surface plus difficile à réduire.
7. **Aucun seuil de taille, aucune alerte.** Rien ne signalait le passage de 500, puis 800, puis 1 000 lignes.

## 3. Règles pour éviter un nouveau God Object

1. **Une classe = un sous-domaine nommable en quelques mots** (« adoption de stacks existantes », « révisions »). Si la description contient « et » plus d'une fois, c'est deux classes.
2. **Seuils durs** (§7). Les dépasser impose une extraction dans le même lot ou le suivant, notée dans `PROGRESS.md`.
3. **Une nouvelle fonction ne s'ajoute pas à une façade.** Elle crée ou rejoint un sous-module ; la façade reçoit au plus un relais d'une ligne.
4. **Types et erreurs partagés dans le socle du module** (`apps/core.py`), dès leur création.
5. **Pas de duplication tolérée entre deux méthodes d'un même module.** La deuxième occurrence déclenche l'extraction vers le socle.
6. **Méthode privée utilisée par deux sous-domaines = code partagé.** Elle sort de la classe et devient publique dans le socle.
7. **Un constructeur à plus de 8 dépendances est un signal d'alerte** ; au-delà de 10, découpage obligatoire (`AppService` en avait 12).

## 4. Règles de dépendance entre modules

1. **Le graphe est orienté et sans cycle, y compris en tenant compte des imports différés.** Un import dans une fonction, dans `__post_init__` ou sous `TYPE_CHECKING` pour contourner un cycle **est** un cycle.
   - *Dette constatée le 12/10* (relevé Graphify, vérifiée dans le code) : `sites/servers.py` fait `from hivora.sites import httpd, nginx`, donc importe le paquet `sites`, dont `__init__.py` importe `core`, qui importe `servers` : cycle `sites/__init__` → `core` → `servers` → `sites/__init__` (introduit le 09/10, `eabaf31`, profils de serveur web). Python le tolère (sous-modules résolus à la volée), la règle non. **Réglé le 12/10** : `servers.py` importe les sous-modules eux-mêmes (`import hivora.sites.httpd as httpd`, idem `nginx`), sans passer par le paquet ; Graphify : « None detected ».
2. **Au sein d'un module découpé** : `core` ← sous-modules ← façade.
   - `core` n'importe aucun sous-module ni la façade.
   - Un sous-module importe `core` et, si besoin, un autre sous-module, sans jamais créer de boucle (exemple : `revisions` → `custom_images`, `compose_edit`).
   - Aucun sous-module n'importe la façade.
3. **Entre modules** : respecter le graphe de la section 6 du document de référence.
   - `zones` ne dépend pas de `apps`.
   - Seuls `docker_gateway` et `compose_runner` accèdent au socket Docker.
4. **Passer par le service, pas par les tables.** Un module lit les données d'un autre module par son service (ou une fonction publique du socle), pas en important ses modèles SQLAlchemy.
   - *Dette connue* : `topology`, `vpn`, `pyapps` et `backups` lisent `apps.models` directement.
5. **Pas d'utilitaire emprunté à un module métier.**
   - Un outil générique vit dans `core` (Hivora) ou dans le socle du module.
   - *Réglé le 01/10 (lot S0)* : les outils fichiers partagés (`confined`, `ensure_dir`, `remove_tree`, `tree_size`, `empty_dir`, `receive_upload`, erreurs d'archive) vivent dans `core/fs`, qui n'importe aucun module métier ; `apps`, `games` et `pyapps` l'importent directement (`apps/files.py` supprimé).
   - *Dette connue* : nom privé `analyze._Zip` importé par `pyapps/service.py` (§9.11), correction prévue dans un lot séparé.
6. **Une vue ne déclenche pas d'action.** Un calcul de lecture (topologie, tableau de bord) n'exécute aucune commande hôte ni aucune mutation.
   - *Dette connue* : `topology` appelle `hostfw.listening()`.
7. **Réexports explicites seulement** (`from x import Y as Y`), placés dans la façade pour préserver les imports existants. À terme, les appelants importent directement depuis le module qui définit le symbole.

## 5. Critères pour créer un nouveau module

On crée un module (ou un sous-module) quand **au moins deux** de ces critères sont vrais :

1. Un sous-domaine métier nommable, avec ses propres types ou erreurs.
2. Un ensemble de méthodes qui s'appellent entre elles plus qu'elles n'appellent le reste de la classe.
3. Un sous-ensemble cohérent de dépendances (exemple : `CustomImages` n'a besoin que de `sessions`, `catalog`, `clock`, `registry`).
4. Une taille qui dépasse ou approche les seuils (§7).
5. Du code aujourd'hui dupliqué, ou partagé par deux sous-domaines (→ socle).

Où placer quoi :

- **Code partagé par plusieurs sous-modules** : dans le socle (`core`). S'il a un état (dépendances), une classe dédiée (`AppPlanner`) ; sinon, des fonctions.
- **Lecture partagée** (`current_settings`, `vpns_reaching`) : dans le socle, jamais dans le sous-module d'écriture. Sinon on crée une dépendance entre sous-modules frères.
- **Un fichier par sous-domaine**, nommé par ce qu'il fait (`revisions.py`, `adoption.py`), pas par un motif technique (`helpers.py`, `utils.py`, `manager.py`).
- **Côté routes, le même découpage que côté services** : `apps/api/<sous-domaine>.py` n'appelle que le sous-service du même nom ; les modèles de réponse partagés vont dans `apps/api/common.py`, et `__init__.py` ne fait qu'assembler les routeurs dans l'ordre public.

## 6. Critères pour refuser un refactoring

On refuse, ou on reporte, un refactoring quand :

1. **Il change un comportement en même temps qu'une structure.** On sépare en deux commits.
2. **Il modifie des tests existants pour les faire passer.** Un refactoring de structure passe avec les tests tels quels ; sinon, le comportement a changé.
3. **Il change la surface publique** (routes, schéma OpenAPI, signatures utilisées par d'autres modules) sans demande explicite.
4. **Il introduit une abstraction à une seule implémentation**, une interface « pour plus tard », ou une couche de relais qui n'enlève rien de la classe d'origine.
5. **Il crée un cycle, même masqué** (import différé, `TYPE_CHECKING`, passage de l'objet parent en paramètre).
6. **Le gain n'est pas mesurable** : ni lignes retirées de la classe visée, ni duplication supprimée, ni dépendance cassée.
7. **Le code visé n'a pas de tests** couvrant les chemins déplacés. On écrit d'abord le test, dans un commit séparé.
8. **La branche n'est pas verte au départ.** On ne refactore pas sur une base rouge.

## 7. Règles de couplage maximal

| Mesure | Seuil d'alerte | Seuil bloquant |
|---|---|---|
| Lignes d'un fichier de service backend | 400 | 600 |
| Lignes d'une classe | 300 | 500 |
| Dépendances injectées dans un constructeur | 8 | 10 |
| Méthodes publiques d'une classe (hors relais de façade) | 15 | 25 |
| Modules Hivora importés par un module (sortant) | 6 | 9 |
| Lignes d'un composant React | 300 | 500 |
| Lignes d'un socle (`core.py` d'un module) | 300 | 450 |

**Seuil d'alerte** : l'extraction est notée dans `PROGRESS.md` comme étape suivante.

**Seuil bloquant** : aucune nouvelle fonction ne s'ajoute à ce fichier avant son découpage.

Situation au 29/09/2026 (commit `e283b3f`, après les deux découpages) :

| Fichier | Taille | Niveau |
|---|---|---|
| `features/topology/topology-view.tsx` | 541 lignes | **bloquant** (composant React > 500) |
| `vpn/service.py` | 491 lignes | alerte |
| `templates/schema.py` | 496 lignes | alerte ; modèles déclaratifs du format `hivora/v1`, moins risqué qu'un service, à surveiller |
| `auth/service.py` | 424 lignes | alerte |
| `features/firewall/firewall-panel.tsx` | 372 lignes | alerte (composant React > 300) |
| `docker_gateway/local.py` | 370 lignes | sous le seuil ; à surveiller (adaptateur unique du socket) |
| `apps/core.py` | 340 lignes | alerte (socle > 300) ; sortir `AppPlanner` dans `apps/planner.py` |
| `features/deploy/generated-form.tsx` | 343 lignes | alerte (composant React > 300) |
| `features/activity/host-charts.tsx` | 321 lignes | alerte (composant React > 300) |
| `apps/service.py` | 315 lignes, classe 236 | **résolu** (1 038 → 315) ; reste une façade de relais |
| `apps/api/` | 8 fichiers, 35 à 225 lignes | **résolu** (647 → 56 pour `__init__.py`) |
| `hostfw/service.py` | 355 lignes | sous les seuils |

Situation au 07/10/2026 (lot M8-a ; mesures de `wc -l`, classes par `ast`) :

| Fichier | Taille | Niveau |
|---|---|---|
| `features/topology/topology-view.tsx` | 236 lignes | **résolu** en M9-b2 (541 avant) : `inspector.tsx` 181, `toolbar.tsx` 128, `pending-panel.tsx` 34, `connect.ts` 39 (règles de connexion, fonction pure), `export.ts` 29 ; couvert par `e2e/topology.spec.ts` (M9-b1) |
| `templates/schema.py` | 496 lignes | alerte (inchangé) |
| `vpn/service.py` | 355 lignes, classe `VpnTools` 269, 9 méthodes publiques | **résolu** en M11-b (504 avant, classe 365) : `vpn/addressing.py` 100 (`VpnApp`, adresses, routes du client, pur), `vpn/acl.py` 58 (droits, activité, vue d'un client, champs reçus, pur), `vpn/apply.py` 62 (sous-réseaux lus dans Docker, fichiers écrits, application par exec) ; couvert par `e2e/vpn.spec.ts` |
| `auth/service.py` | 236 lignes, classe `AuthService` 181, 13 méthodes publiques | **résolu** en M11-b (424 avant, classe 313, 20 méthodes publiques) : `auth/users.py` 122 (`UserAdmin`, administration des comptes, 7 méthodes, `rt.auth.users`), `auth/totp.py` 67 (`TotpGuard` : codes acceptés une fois, codes de secours), `auth/passwords.py` 36 (règles, pur), `auth/sessions.py` 41 (jeton, CSRF, révocation) ; `ratelimit.py` inchangé |
| `features/firewall/firewall-panel.tsx` | 372 lignes | alerte (inchangé) |
| `apps/core.py` | 116 lignes | **résolu** en M9-a (358 avant) : `AppPlanner`, `DeployPlan`, `AppSettings`, `SitePorts` et `services_from` dans `apps/planner.py` (260 lignes, sous les seuils) |
| `features/deploy/generated-form.tsx` | 343 lignes | alerte (inchangé) |
| `features/activity/host-charts.tsx` | 321 lignes | alerte (inchangé) |
| `sites/files.py` | 301 lignes | sous le seuil ; fonctions pures et service `SiteFiles` (75 lignes) à séparer s'il grossit |
| `sites/hosting.py` | 295 lignes, classe `SiteHosting` 235, 10 méthodes publiques | **résolu** (417 et 306 au 07/10, avant M8-a) : vérifications de port dans `sites/port_check.py`, types et vue dans `sites/views.py` |

Situation au 12/10/2026 (après les lots K et R ; `wc -l`, classes par `ast`) :

| Fichier | Taille | Niveau |
|---|---|---|
| `features/topology/topology-view.tsx` | 347 lignes | **alerte** (composant React > 300) : 236 après M9-b2, regrossi avec les sites dans la topologie, la sélection groupée et l'aimantation (08–09/10) ; extraire la sélection et l'aimantation (la logique pure est déjà dans `snap.ts`) |
| `features/deploy/generated-form.tsx` | 345 lignes | alerte (inchangé) |
| `features/activity/host-charts.tsx` | 321 lignes | alerte (inchangé) |
| `features/firewall/ports.tsx` | 316 lignes | alerte (nouveau : découpage de la page Pare-feu du 09/10) |
| `features/firewall/firewall-panel.tsx` | 53 lignes | **résolu** (372 avant) : la page Pare-feu découpée en sous-pages (`host`, `overview`, `ports`, `connections`, `blocked`, `fail2ban`, `routes`, `static-routes`) |
| `templates/schema.py` | 496 lignes | alerte (inchangé) |
| `hostfw/service.py` | 367 lignes | sous le seuil (400), à surveiller : les fonctions ajoutées depuis (connexions, blocage, routes) vivent dans leurs propres fichiers |
| `hostfw/` (lots K et R) | `blocking.py` 195, `static_routes.py` 179, `routing.py` 194 (pur), `blocklist.py` 52 (pur), `connections.py` 199 | sous les seuils ; `Blocking` et `StaticRoutes` : dépendances explicites (5 à 7), verrou d'instance, aucune I/O dans une transaction, mutations par `jobs` |
| `docker_gateway/local.py` | 370 lignes, classe 183 | sous le seuil (inchangé) |
| `vpn/service.py` | 353 lignes, classe `VpnTools` 269 | sous les seuils (inchangé depuis M11-b) |
| `sites/hosting.py` | 310 lignes, classe `SiteHosting` 247, 11 méthodes publiques | sous les seuils |
| `apps/revisions.py` | 305 lignes, classe `Revisions` 234 | sous les seuils |

Aucun fichier au seuil bloquant. Dette constatée ce jour-là et réglée le même jour : le cycle d'import du module `sites` (§4.1).

`AppService` (`apps/service.py`, 245 lignes, classe 171) : **résolu** en M10-a pour le seuil bloquant des dépendances injectées (13 → 9 : `registry`, inutilisé, retiré ; `secret_settings` et `public_address`, utilisés par le seul planificateur, et `gateway`, par les seuls gestionnaires de jobs, posés par `Runtime` comme `site_ports`) et 34 → 17 méthodes publiques (alerte à 15 : 12 sont des relais que seuls les tests appellent encore). **Relais résolus** en M11-c2 : 124 lignes de classe, 6 méthodes publiques et la propriété `registry` (lue par la route d'inspection d'image). Les 10 relais réservés aux tests sont supprimés, ainsi que le setter de `registry` et `_inspected` ; `get` et `decrypt_secrets` restent, car `apps/handlers.py` et `backups/service.py` les appellent en production.

Accès inter-modules du module `sites` (§9.9) : **résolu** en M8-a. `sites` lit les apps par `apps.queries` (`hosting_app`, `hosting_app_id`, `volume_source`) et `apps.core.latest_revision`, marque un hôte par `Application.mark_hosting()`, lit les jobs par `jobs.queries` (`get_job`, `last_job`) ; il ne fait plus de requête sur les tables `application`, `service` ni `job`.

Accès inter-modules aux tables d'`apps` (§9.9) : **résolu** en M11-c1. `topology` lit les apps et leur modèle par `apps.queries.apps_with_template` et leur dernière révision par `apps.core.latest_revision` ; `vpn` (`follow_deploys`) et `pyapps` trouvent une app par `apps.queries.app_id_by_slug` ; `backups` ne fait qu'importer le type `Application`. Restent hors d'`apps` : `topology` lit la table `zone` (comme `apps.revisions`), et `apps` joint `template_version` (6 requêtes, lien qu'il porte lui-même) ; `setting` (`db`) est une table d'infrastructure partagée.

Priorités techniques (bilan du 29/09) :

- **PRIORITÉ 1 : routes fines.**
  - Remonter dans les services les accès SQL des 13 routes de lecture et des 9 routes d'écriture listées au §0 : `apps/api/queries.py`, `apps/api/revisions.py`, `topology/api.py`, `audit/api.py`, `jobs/api.py`, `zones/api.py`, `backups/api.py`.
  - Déplacement pur, contrat OpenAPI identique.
- **PRIORITÉ 2 : assainir `vpn`, puis `hostfw`.**
  - Mutations par `jobs`, avec le verrou de l'app.
  - Dépendances explicites à la place de `Runtime`. *`vpn` : fait le 07/10 (lot M10-b5) ; `hostfw` : fait le 07/10 (lot M10-b6).*
  - Plus de lecture directe de `apps.models`.
  - Verrou d'instance à la place de `_LOCK`. *`vpn` : fait le 07/10 (lot M10-b5) : `VpnTools._lock`, une seule instance par Hivora.*
  - ~~Découpage de `vpn/service.py` (491 lignes) : socle `addressing` / `acl` purs, application par exec à part.~~ fait le 07/10 (lot M11-b).
- **PRIORITÉ 3 : sortir `Runtime` des services métier restants** (~~`topology`~~ fait le 07/10, lot M10-b1 ; ~~`tasks`~~ fait le 07/10, lot M10-b2 ; ~~`pyapps`~~ fait le 07/10, lot M10-b3 ; ~~`games.engine`~~ fait le 07/10, lot M10-b4). Cela supprime les 4 cycles masqués de `runtime.py` (§8.2).

Second rang :

1. ~~`topology-view.tsx` (seuil bloquant) : extraire le panneau d'inspection, le gestionnaire de liens et l'export.~~ fait le 07/10 (lots M9-b1 et M9-b2) : 541 → 236 lignes.
2. ~~`AppPlanner` dans `apps/planner.py` : `core.py` repasse sous 300 lignes.~~ fait le 07/10 (lot M9-a) : `core.py` 116 lignes, `planner.py` 260.
3. ~~Étape 7 de `AppService` : brancher les appelants sur les sous-services, puis supprimer les relais ; c'est ce qui fera baisser ses liens dans Graphify (§13).~~ fait le 07/10 (lot M10-a) : 13 → 9 dépendances, 34 → 17 méthodes publiques ; restent 12 relais appelés par les tests seuls.
4. ~~`core/fs` pour `confined`, `tree_size`, `remove_tree` et `receive_upload` (§4.5)~~ fait le 01/10 (lot S0) ; reste `_Zip` à rendre public (§9.11).
5. Topologie branchée sur l'état du pare-feu en cache (§4.6).
6. `ZoneIn` renommé (ex. `AppZoneIn`) pour supprimer le contournement de `__module__` ; commit séparé, le contrat OpenAPI change.
7. ~~Cycle d'import `sites/__init__` → `core` → `servers` (§4.1, constaté le 12/10).~~ réglé le 12/10.
8. `topology-view.tsx` repassé sous 300 lignes (situation au 12/10).
9. Mutations hors `jobs` restantes : règles UFW, bannissements fail2ban, réglages des jails, listes de joueurs (les blocages et les routes statiques, eux, passent par `jobs`).

## 8. Règles concernant `Runtime` et les services transverses

1. **`Runtime` est la racine de composition, pas un annuaire.** Son rôle est de construire les services (`build`), de les démarrer et de les arrêter. Il ne doit pas être passé aux services métier.
2. **Aucun nouveau service ne reçoit `Runtime`.** Il reçoit ses dépendances explicites, comme `AppService`, `AppPlanner`, `CustomImages`, `Adoption`, `ComposeEdit`, `Revisions`, `Deployer`, `Lifecycle`.
   - *Dette connue* (vérifiée le 29/09, mise à jour le 07/10) : aucun service métier ne reçoit plus `Runtime` (seul `realtime` le reçoit encore, toléré, voir point 3). Ne le reçoivent plus : `topology` (lot M10-b1 : `GraphBuilder`, construit par sa route), `tasks` (lot M10-b2 : `TaskTools`, construit une fois par `Runtime`, qui l'importe désormais en tête), `pyapps` (lot M10-b3 : `PythonProjects`, construit par sa route) `games.engine` (lot M10-b4 : `GameTools`, construit par sa route) `vpn` (lot M10-b5 : `VpnTools`, construit une fois par `Runtime`, qui l'importe désormais en tête) et `hostfw` (lot M10-b6 : `HostFirewall`, construit par `Runtime.build` au lieu de `__post_init__`, importé en tête). `runtime.py` n'importe plus en différé que `realtime.console` (`ConsoleManager(self)`), un adaptateur de sortie toléré (point 3) : 1 cycle masqué, contre 4 au 29/09. À corriger module par module, en commençant par ceux qui n'utilisent que 2 ou 3 attributs.
3. **Exception tolérée : les adaptateurs de sortie** (`realtime/ws`, `realtime/console`, `realtime/logs`, routes FastAPI via `RuntimeDep`). Ils sont en bordure du système et ne sont importés par aucun service.
4. **Services transverses** (`core.events.EventBus`, `core.clock`, `core.redact`, `crypto`, `audit`) :
   - ils ne dépendent d'aucun module métier ;
   - le bus sert au découplage (audit, temps réel) : un module publie un événement plutôt que d'appeler l'audit ou le WebSocket ;
   - `clock` est toujours injecté, jamais `datetime.now()` direct dans un service, pour que les tests puissent figer le temps.
5. **Pas d'état global de module pour du nouveau code.**
   - Un verrou, un cache, un registre appartiennent à une instance de service.
   - *Plus de dette connue* depuis le 07/10 : `vpn._LOCK` remplacé par un verrou d'instance (lot M10-b5) ; `state._adopted` porté par `StateStore` (lot M10-c1) ; `templates._detected_arch` porté par `Catalog` (lot M10-c2).
   - *Correction du 29/09* : `auth._totp_used`, listé ici auparavant, est un attribut d'instance (`self._totp_used`), pas un état global.
6. **Un service transverse qui grossit se découpe comme un module métier.** Il n'a pas de statut spécial.

## 9. Anti-patterns interdits

1. **God Object** : une classe qui sert de point d'entrée à plusieurs sous-domaines (§3).
2. **Service locator** : passer `Runtime`, `app.state` ou un conteneur global à un service métier.
3. **Cycle masqué** : import différé ou `TYPE_CHECKING` pour contourner une dépendance circulaire.
4. **Types partagés dans la façade** : un type ou une erreur utilisé par plusieurs fichiers, défini dans le fichier de la façade.
5. **Relais privés** : une méthode `_x` de façade qui ne fait qu'appeler un sous-module, alors qu'aucun appelant externe n'en a besoin. On appelle le sous-module directement.
6. **Duplication de séquences transactionnelles** : deux copies de « écrire, mettre en file, réveiller, publier ».
7. **I/O externe dans une transaction d'écriture** : `docker exec`, appel réseau, sous-processus pendant qu'une transaction SQLite est ouverte (cause du crash « database is locked » du 28/09).
8. **Mutation hors `jobs`** sans dette déclarée dans `PROGRESS.md`.
9. **Lecture des tables d'un autre module** au lieu de son service.
10. **Vue qui agit** : un calcul d'affichage qui déclenche une commande hôte ou une mutation.
11. **Nom privé importé d'un autre fichier** (`from x import _Y`).
12. **Utilitaire générique rangé dans un module métier** et importé par d'autres modules métier.
13. **Refactoring qui modifie les tests** pour passer.
14. **Formatage global non demandé** : reformater tout un fichier avec un outil qui n'est pas celui du projet. Le 28/09, Prettier a réécrit 546 lignes pour une modification de 14 ; changement annulé puis refait à la main.

## 10. Workflow obligatoire pour tout futur refactoring

**A. Avant de toucher au code** (rien n'est modifié à ce stade) :

1. **Mesurer** : taille du fichier et de la classe (`ast`), liens du nœud dans Graphify, dépendances sortantes.
2. **Inventorier les méthodes concernées**, et pour chacune :
   - qui l'appelle (`grep` dans `src/` **et** `tests/`) ;
   - ce qu'elle appelle (méthodes internes, attributs, types).
3. **Chercher ce qui touche l'intérieur de l'objet** : les tests qui assignent un attribut (`x.attr = …`), qui vident un cache, ou qui remplacent une méthode (`monkeypatch.setattr`).
4. **Identifier les types et erreurs** qui devront suivre, et qui les importe.
5. **Repérer les dépendances cachées** : une méthode déplacée qui appelle une méthode d'un autre sous-domaine.
6. **Écrire la stratégie et les risques**. S'il existe plusieurs options (exemple : 5a option A ou B), comparer avantages, inconvénients, couplage, tests, étapes suivantes et objectif final, puis recommander.
7. **Attendre la validation.**

**B. Pendant** :

1. **Déplacer le code tel quel.** Seules les références changent (`self.get` → `get_app`, etc.). Aucune « amélioration au passage ».
2. **Façade inchangée** : mêmes méthodes publiques, mêmes signatures, relais d'une ligne.
3. **Attributs lus ou écrits de l'extérieur** : propriété avec setter qui pointe sur le **même objet** (pas une copie).
4. **Types déplacés** : réexport explicite `Y as Y` dans l'ancien fichier.
5. **Prérequis de dépendance** (un type ou une requête à sortir d'abord) : le faire dans l'étape, en l'expliquant, ou dans un commit préparatoire (5a avant 5b).
6. **Une étape = un sous-module = un commit.**
7. **Routes déplacées** : garder l'ordre d'enregistrement exact (plusieurs routeurs par fichier si besoin, route au chemin vide enregistrée par le routeur parent), les noms de fonctions (`operationId`) et les tags ; vérifier l'unicité des noms de modèles déplacés.

**C. Vérifications, toutes obligatoires, en lisant les nombres** :

1. `ruff check` et `ruff format --check`.
2. `mypy` en mode strict.
3. **Tests ciblés** sur les fichiers concernés. Vérifier que le nombre de tests passés est > 0 ; `no tests ran` est un échec de la commande, pas un succès.
4. `pytest` complet (référence au 12/10 : 498 passés ; 208 au 29/09).
5. Parcours e2e Playwright, **sortie complète conservée** ; un échec non expliqué est signalé, même si la relance passe.
6. **Aucun cycle** : le nouveau fichier n'importe ni la façade ni un module qui l'importe.
7. **Diff relu** : aucun code dupliqué, aucun import mort, aucune logique modifiée.
8. **API** : exporter le schéma OpenAPI et le comparer **octet par octet et en contenu** (opérations, schémas, ordre des chemins) au schéma versionné, lui-même vérifié à jour par rapport à `HEAD`. Routes déplacées : comparer aussi l'ordre des routes (méthode, chemin, nom).

**D. Après** :

1. Note datée dans `docs/PROGRESS.md` : contenu, décisions, tailles avant/après, tests, étape suivante.
2. Revue finale dédiée (changement fonctionnel, duplication, cycle, code mort, compatibilité), avec réponse « COMMIT OK » ou « CORRECTIONS NÉCESSAIRES ».
3. Commit préfixé `refactor(<module>): …`, contenant **uniquement** les fichiers de l'étape et la note.
4. Pousser seulement après accord explicite ; afficher le hash et `git status`.

## 11. Workflow obligatoire pour toute nouvelle feature

1. **Relire** `CLAUDE.md` (sécurité, budgets, hors périmètre) et le document de référence. Signaler toute contradiction avant de coder.
2. **Situer la feature** : quel module, quel sous-module ? Nouveau sous-module si les critères du §5 sont remplis.
3. **Vérifier les seuils** (§7) du fichier d'accueil. S'il est au seuil bloquant, on découpe d'abord.
4. **Définir les types et erreurs** dans le socle s'ils seront partagés.
5. **Mutation = job.** Toute action qui modifie l'état passe par `jobs` et le verrou de l'app. Aucune I/O externe dans une transaction.
6. **Injection explicite** des dépendances ; jamais `Runtime` dans un service métier.
7. **Sécurité** : secrets jamais en clair (logs, audit, `inputs`) ; route avec rôle minimal déclaré ; action hôte seulement via l'agent et ses commandes fixes.
8. **i18n FR et EN**, aucune chaîne en dur ; option avancée d'abord dans le mode avancé.
9. **Tests** : au moins un test qui échoue si la logique casse (parseur, branche, chemin de sécurité). Pour un bug, un test de non-régression qui reproduit le bug sur l'ancien code.
10. **Vérifications** : `ruff`, `mypy`, `pytest` complet, e2e, budget bundle (`npm run check:bundle`, < 520 Ko gzip par page).
11. **`docs/PROGRESS.md`** dans le même commit ; et, pour un lot fonctionnel (un changement visible par l'utilisateur ou l'administrateur), **une ligne dans `CHANGELOG.md`**, section `[Non publié]`, en français.
12. **`graphify update .`**, puis vérifier que le nœud modifié ne gagne pas de liens anormalement (§13).

## 12. Signaux d'alerte : un module devient dangereux

1. **Il franchit un seuil du §7.**
2. **Son nombre de liens dans Graphify augmente à chaque feature**, ou il entre dans les « God Nodes » du rapport (hors utilitaires légitimes comme `useI18n`, `api`, `cn`, `Button`).
3. **Il importe plus de modules qu'avant**, surtout des modules métier sans rapport.
4. **On y ajoute une méthode privée utilisée par une autre partie du module.**
5. **Deux méthodes y contiennent la même séquence.**
6. **Il définit des types importés par d'autres fichiers** alors qu'il n'est pas le socle.
7. **Des tests commencent à modifier son intérieur** (attributs, caches, `monkeypatch` de ses méthodes) : sa surface publique ne suffit plus pour le tester.
8. **Il reçoit `Runtime`**, ou un import différé apparaît pour l'atteindre.
9. **Il contient du `sleep`, un verrou global ou un cache au niveau du module.**
10. **Il appelle Docker, le réseau ou un sous-processus dans une transaction.**
11. **Sa cohésion dans Graphify baisse** (communauté < 0,10 avec beaucoup de nœuds) : il regroupe des choses sans lien.
12. **Une modification simple oblige à toucher plus de 3 fichiers sans rapport.**

## 13. Utiliser Graphify pour surveiller l'architecture

Le graphe est dans `graphify-out/` (non versionné, reconstruit par un hook git à chaque commit).

- **Fraîcheur** : l'en-tête de `graphify-out/GRAPH_REPORT.md` indique le commit de construction. Le comparer à `git rev-parse HEAD`. Sinon, lancer `graphify update .` (analyse syntaxique seulement, sans coût).
- **Questions ciblées** (préférer à la lecture de fichiers entiers) :
  - `graphify query "<question>"` : sous-graphe pertinent ;
  - `graphify path "<A>" "<B>"` : comment deux éléments sont reliés (détecter une dépendance indésirable) ;
  - `graphify explain "<concept>"` : vue ciblée d'un concept.
- **Revue d'ensemble** (avant un gros lot, ou toutes les ~10 features) : lire `GRAPH_REPORT.md` et relever :
  - **God Nodes** : comparer le nombre de liens avec le relevé précédent (`AppService` : 57 au 28/09 ; 62 au 29/09, commit `e283b3f`). Une hausse sur un service métier est un signal (§12). *Cas particulier* : une façade de relais garde beaucoup de liens (un par sous-service et par relais) même quand elle ne contient plus de logique ; sa baisse viendra de la suppression des relais (étape 7), pas de nouveaux découpages.
  - **Import Cycles** : doit rester « None detected ». Attention : Graphify ne voit pas les cycles masqués par imports différés ; les chercher à la main (`grep` des imports dans les fonctions et sous `TYPE_CHECKING`).
  - **Communautés à faible cohésion** avec beaucoup de nœuds : candidates au découpage.
  - **Connexions surprenantes** entre modules censés être indépendants.
- **Relevé de référence** : noter dans `PROGRESS.md` les chiffres clés (nœuds, liens, top 10 des God Nodes) à chaque revue, pour comparer dans le temps. Relevé du 29/09 (`e283b3f`) : 3 402 nœuds, 9 206 liens ; God Nodes métier : `AppService` (62), `ValidationError` (57), `EventBus` (42). **Dernier relevé (12/10, `b8639f5`)** : 4 443 nœuds, 14 295 liens, 221 communautés. Top 10 des God Nodes : la section « Réseau et applications » de `docs/PROGRESS.md` (362, référence documentaire, pas du couplage de code), puis des utilitaires légitimes (`useI18n` 208, `admin` 117 et `wait_job` 111 des tests, `api` 114, `cn` 96, `react` 84) et les erreurs et le bus transverses (`EventBus` 92, `ValidationError` 92, `ConflictError` 83) ; plus aucun service métier, `AppService` compris. **Import Cycles : 1 détecté** (`sites`, §4.1), réglé le même jour : « None detected » (relevé suivant, 4 416 nœuds, 14 377 liens).
- **Mesures complémentaires** hors Graphify : taille des fichiers et classes (script `ast`), dépendances sortantes par module (analyse des imports `hivora.*`).

## 14. Checklist architecture avant chaque gros commit

À exécuter et cocher ; un seul « non » bloque le commit.

**Structure**
- [ ] Aucun fichier touché ne dépasse un seuil bloquant du §7 (ou son découpage est dans ce commit).
- [ ] Aucune nouvelle dépendance vers `Runtime` dans un service métier.
- [ ] Aucun cycle, y compris masqué (imports différés, `TYPE_CHECKING`).
- [ ] Aucun nouveau type ou erreur partagé défini dans une façade.
- [ ] Aucune duplication de séquence transactionnelle.
- [ ] Aucun nom privé importé d'un autre fichier.
- [ ] Aucun nouvel état global de module.

**Comportement**
- [ ] Toute mutation passe par `jobs`, ou la dette est notée dans `PROGRESS.md`.
- [ ] Aucune I/O externe dans une transaction d'écriture.
- [ ] Refactoring : aucun test modifié, aucune route modifiée.
- [ ] Sécurité : secrets hors logs, audit et `inputs` ; rôle minimal sur chaque route ; règles de `CLAUDE.md` respectées.

**Vérifications (nombres lus, pas supposés)**
- [ ] `ruff check` et `ruff format --check` : OK.
- [ ] `mypy` strict : « no issues found ».
- [ ] Tests ciblés : nombre de tests passés > 0.
- [ ] `pytest` complet : tous verts (498 au 12/10, jamais moins sans raison notée).
- [ ] e2e Playwright : vert (sortie complète gardée ; tout échec non expliqué est signalé).
- [ ] Routes touchées : ordre des routes et schéma OpenAPI identiques (octet par octet et en contenu), ou changement de contrat explicitement validé.
- [ ] Frontend touché : `npm run check:bundle` sous 520 Ko gzip par page.

**Traçabilité**
- [ ] Note datée dans `docs/PROGRESS.md` (contenu, décisions, tailles, tests, suite).
- [ ] Lot fonctionnel : une ligne dans `CHANGELOG.md`, section `[Non publié]`.
- [ ] Le commit ne contient que les fichiers prévus (`git diff --cached --name-only` relu).
- [ ] `graphify update .` lancé ; aucune hausse anormale de liens sur un service métier.

## 15. Distribution et installation (M12, décidé le 14/10/2026)

Décisions D1 à D10 : `CLAUDE.md` (« Distribution ») et le document de référence (« Installation », « VPN d'administration », « Distribution et versions »). Règles d'architecture qui en découlent :

1. **Le script d'installation ne contient aucune logique métier.** Il prépare l'hôte (Docker, dossiers, `install.env`) et lance le conteneur ; tout le reste passe par `python -m hivora bootstrap` dans le conteneur, qui construit les services comme `Runtime.build` et agit par eux (migrations, secrets, jobs). Jamais d'écriture directe dans `hivora.db`, `wg0.conf` ou les dossiers des apps depuis le shell.
2. **Le bootstrap est idempotent** : relancé, il ne recrée ni l'admin, ni la zone Administration, ni l'app WireGuard, ni le client `admin` s'ils existent. Un test le vérifie (deux lancements, un seul de chaque). Pour le VPN d'administration, c'est la mise en conformité au démarrage du serveur qui porte cette règle (point 13).
3. **Une commande en ligne est une bordure, comme une route** : elle reçoit `Runtime` (adaptateur de sortie toléré, §8.3), appelle des services aux dépendances explicites, ne contient pas de logique testable ailleurs.
4. **Sources de vérité de la distribution** : le tag git pour la version ; `install.env` pour les options de lancement du conteneur `hivora` (Hivora le lit, ne l'écrit pas) ; les GitHub Releases pour la version disponible, état d'exécution gardé en mémoire (cache), seul le réglage « vérifier » va en base.
5. **Lectures de santé et de version** (`system/status`, `system/releases`) : sous-modules de `system`, lecture seule (§4.6), dépendances injectées, aucun état global ; un contrôle coûteux (`PRAGMA quick_check`) seulement à la demande.
6. **Une seule source de version** (M12-1) : `version` de `backend/pyproject.toml`. `hivora.__version__` la lit dans les métadonnées du paquet installé (`importlib.metadata`), jamais écrite en dur ; `frontend/package.json` la recopie. `.github/scripts/release-check.sh` refuse un tag qui diffère de l'une ou de l'autre, ou sans section dans `CHANGELOG.md`. En développement, changer la version demande `uv sync` (fait par `uv run`) pour mettre à jour les métadonnées.
7. **Publier, c'est `release.yml` seulement** (tag `v*` sur un commit de `main`) : image multi-arch, tags `vX.Y.Z`, `X.Y`, `latest` (une pré-release `-rc.N` n'a que son propre tag), labels OCI, GitHub Release. `image.yml` ne fait plus que vérifier les budgets.
8. **Aucune migration sans moyen de revenir** (M12-2) : au démarrage, `schema_state` (lecture seule) ; base plus récente que le code (`newer`) : refus (`SchemaTooNewError`), rien n'est écrit ; base en retard (`behind`) : `system/panel_backup.backup_panel` (base par `VACUUM INTO`, `secret.key`, `install.env`, 0600, 5 archives gardées dans `backups/_hivora/`) **avant** `upgrade_to_head`. Une base neuve ou à jour ne déclenche rien. Aucune restauration automatique : elle reste un geste manuel documenté.
9. **Le compte initial ne passe jamais par `admin` / `admin` avec l'installeur** (M12-3) : `python -m hivora bootstrap` tourne **avant** le serveur, dans un conteneur jetable (même image, mêmes montages, sans le socket Docker) ; il appelle `prepare_database` (la même fonction que `Runtime.build` : une seule séquence refus, sauvegarde, migration) et `AuthService.ensure_initial_admin(password)`. Les cas particuliers (sécuriser `admin` / `admin`, `reset-admin-password`) vivent dans `auth/initial.py`, pas dans `AuthService` (13 méthodes publiques, alerte à 15). Le mot de passe ne sort que sur la sortie `CLÉ=valeur` de la commande ; le réglage `auth.initial_password` dit à `first_start` que `admin` / `admin` ne vaut plus, sans hachage Argon2 à chaque `/system/health`. Les actions qui demandent la file de jobs (VPN, M12-5) ne pourront pas tourner ainsi : elles passeront par le serveur en marche.
10. **L'installeur** (`deploy/install.sh`, M12-4) : tout en fonctions, `main "$@"` en dernière ligne (un téléchargement coupé n'exécute rien) ; `run()` pour chaque commande qui change quelque chose (affichée seulement avec `--dry-run`) ; `install.env` lu ligne à ligne par `sed`, **jamais exécuté** (ni `.`, ni `eval` d'une valeur), chaque valeur vérifiée par un motif avant usage ; priorité ligne de commande > `install.env` > détection ; version portée par le script (`SCRIPT_VERSION`, posée par `release.yml`), pas d'appel à l'API GitHub ; ordre : vérifications → pull → sauvegarde (`backup-self` dans l'ancien conteneur) → retrait → bootstrap (conteneur jetable) → démarrage → « healthy » → écriture d'`install.env` (seulement après un succès) → résumé ; jamais de restauration automatique, mais la commande pour revenir en arrière en cas d'échec. Tests : faux `docker`, `ss`, `ip`, `id` en tête du `PATH` (`test_install_script.py`), et `--data` / `--srv` toujours passés (un essai sans eux a écrit dans `/opt/hivora` de la VM, voir PROGRESS M12-4) ; `shellcheck` en CI. **Modes VPN** (M12-5b) : l'installeur crée seulement le réseau `hivora-zone-administration` (sous-réseau et plage fixes, étiquette de réseau de zone) et lance le panel dessus à `PANEL_IP` ; tout le reste (zone, app WireGuard, client, `admin.conf`) est fait par le serveur (point 13), l'installeur attend `admin.conf` et l'affiche par `python -m hivora admin-vpn`. Les constantes d'adressage sont recopiées dans le script : un test exige qu'elles soient égales à celles de `vpn/admin.py`. Un réseau du même nom avec une autre plage est refusé, jamais recréé (des apps y sont branchées).
11. **TOTP obligatoire en mode public** (M12-4b) : une seule règle, `auth.totp.setup_required(access, totp_enabled)`, appelée par `web.deps.require` (ordre : mot de passe à changer, puis TOTP, puis rôle ; `require(role, totp=False)` = `TotpSetup`, seulement pour `totp/enroll` et `totp/confirm`) et par le WebSocket (à la connexion et à chaque revalidation, `4403`). Le mode vient de `Settings.access` (variable `HIVORA_ACCESS`, valeurs fixes, inconnue = refus de démarrer), jamais stocké. OpenAPI inchangé : le frontend réagit au code `totp_setup_required` (sonde `GET /auth/sessions` dans `app-shell` quand `totp_enabled` est faux, renvoi global dans `api()`), pas à un champ de `/auth/me`. Les commandes de secours sur la machine (`reset-admin-password`, `reset-totp`) vivent dans `auth/initial.py` et `system/bootstrap.py`, pas dans `AuthService`.
12. **Hivora ne touche pas à son propre conteneur** avant l'exception M13 (conteneur `hivora-updater`, retour arrière automatique), à valider dans `CLAUDE.md` avant tout code.
13. **VPN d'administration** (M12-5a) : `vpn/admin.py` (`AdminVpn`, construit par `Runtime`, dépendances explicites : réglages, sessions, `AppService`, `VpnTools`, file de jobs, adresse publique, horloge). Il tourne **dans le serveur**, en tâche de fond après le démarrage des jobs (le déploiement de WireGuard est un job, et `VpnTools` garde son verrou dans le processus : une commande séparée écrirait `wg0.conf` en concurrence). Mise en conformité à chaque démarrage, seulement en mode `vpn` ou `vpn+lan`, sans jamais faire échouer le démarrage : zone Administration en réseau partagé (redéploiement de ses apps), app « Admin VPN » (déploiement attendu), client `admin`, `admin.conf` ; état persistant dans le réglage `vpn.admin` (`app_id`, `client_id`, `initialized_at`), relu après le déploiement (SQLite réutilise les identifiants supprimés : un ancien `client_id` ne doit pas survivre à une nouvelle app). Gardes dans les routes (bordure), pas dans `AppService` ni `VpnTools` : `apps` ne dépend pas de `vpn`. Constantes d'adressage (`ADMIN_ZONE_SUBNET`, `ADMIN_ZONE_RANGE`, `PANEL_IP`, `ADMIN_VPN_SUBNET`) dans `vpn/admin.py`, à recopier à l'identique dans l'installeur (M12-5b, un test comparera). Secours : `rescue-admin` pose `vpn.admin_rescue` (commande sans Docker, comme `reset-totp`), consommé par le serveur au démarrage suivant.
