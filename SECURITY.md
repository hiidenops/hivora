# Politique de sécurité

## Signaler une vulnérabilité

Signalez les problèmes de sécurité **en privé**, par GitHub :
[signaler une vulnérabilité](https://github.com/hiidenops/hivora/security/advisories/new)
(onglet Security → *Report a vulnerability*). N'ouvrez pas d'issue publique.

Indiquez ce que vous avez trouvé, comment le reproduire, et la version (Paramètres → Mises à
jour, ou `docker inspect hivora`). La réponse vous parviendra dans l'avis lui-même.

## Versions prises en charge

Les correctifs vont dans la dernière version. Avant la 1.0, mettez à jour vers la dernière
version pour les obtenir (voir [docs/updating.md](docs/updating.md)).

## À savoir quand on fait tourner Hivora

- Hivora pilote Docker sur sa machine, ce qui revient à un accès root : protégez le panel
  comme un compte administrateur (double authentification, VPN d'administration plutôt que
  le mode Internet).
- Docker contourne UFW : un port publié par Docker n'est pas filtré par le pare-feu de l'hôte.
