# Déploiement Dokploy — Ticketing multicanal (API, manuel, e-mail)

Procédure de mise en production du ticketing et de son durcissement.
Toutes les commandes s'exécutent **sur le serveur Dokploy**, dans les conteneurs
(`docker exec …`), jamais avec le Python de l'hôte.

> Règles : aucune migration de production sans autorisation explicite ; aucune
> valeur de secret dans Git, dans un ticket ou dans une conversation.

## 1. Périmètre

| Élément | Détail |
|---|---|
| Migration | `project.0055_ticketing_channels` (commit `7f78cf2`, déjà sur `main`) |
| Version de durcissement | isolation du fil public, e-mails bruts, cache partagé, clé de chiffrement, chaîne IA — **aucune nouvelle migration** |
| Services à redéployer | `devflowweb`, `devflowcelery`, `devflowbeat` (même image) |
| Dépendances | inchangées (`cryptography`, `redis`, `hiredis`, `celery`, `anthropic` déjà dans `requirements.txt`) |

`0055` est purement additive : 3 colonnes sur `project_ticket` (`source`,
`created_by_id`, `mailbox_id`), 2 tables (`TicketMailbox`, `TicketEmailMessage`),
index et contraintes. Pas de réécriture de table, pas de migration de données.

## 2. Vérifications avant déploiement (lecture seule)

```bash
docker exec devflowweb python manage.py showmigrations project | tail -4
```

```bash
docker exec devflowweb python manage.py migrate --plan
```

- `[X] 0055_ticketing_channels` : le schéma est à jour, passer directement au §5.
- `[ ] 0055_ticketing_channels` : la migration reste à appliquer (§5). Si le
  commit déployé est `7f78cf2` ou plus récent, les pages Tickets répondent en
  erreur 500 d'ici là (le conteneur web **ne lance pas** `migrate` au démarrage).

```bash
docker ps --format '{{.Names}}\t{{.Status}}' | grep -E 'devflow(web|celery|beat|db)|redis'
```

## 3. Variables d'environnement (Dokploy → Environment)

Les trois services lisent le même `.env` : une seule saisie suffit.

| Variable | Rôle | Obligatoire |
|---|---|---|
| `TICKETING_ENCRYPTION_KEY` | Clé de chiffrement des secrets du ticketing (applications, IMAP, SMTP, webhooks) et des jetons de conversation | **Oui** |
| `TICKETING_ENCRYPTION_KEYS_OLD` | Anciennes clés, séparées par des virgules, acceptées en lecture pendant une rotation | Non (vide) |
| `REDIS_URL` | Déjà fourni par `docker-compose.yml` ; sert aussi au cache partagé (base Redis n° 1) | Déjà en place |
| `CACHE_URL` | Remplace l'emplacement du cache (ex. Redis dédié) | Non |
| `AI_FALLBACK_CHAIN` | Ordre des fournisseurs IA, défaut `deepseek,openai,anthropic,local` | Non |
| `DEEPSEEK_API_KEY`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY` | Un fournisseur sans clé est ignoré ; aucune clé ⇒ heuristiques | Au moins une recommandée |
| `FLOWER_USER`, `FLOWER_PASSWORD` | Sans elles, Flower démarre avec les identifiants par défaut du dépôt | **Oui** |
| `TICKET_MAX_ATTACHMENT_MB`, `TICKET_MAIL_MAX_MB` | Limites (défaut 20 et 25 Mo) | Non |

### Générer `TICKETING_ENCRYPTION_KEY`

Sur le serveur, dans un terminal privé :

```bash
openssl rand -base64 48
```

Coller la valeur directement dans l'environnement Dokploy, la conserver dans le
coffre de mots de passe de l'équipe, ne la copier nulle part ailleurs.

Comportement :

- sans cette variable, la clé est dérivée de `SECRET_KEY` (état actuel de la
  production) : changer `SECRET_KEY` rendrait tous les secrets illisibles ;
- l'introduire ne casse rien : les secrets et jetons de conversation existants
  restent lisibles (repli sur la clé dérivée de `SECRET_KEY`), les nouveaux sont
  chiffrés avec la clé dédiée ;
- **rotation** : placer l'ancienne valeur dans `TICKETING_ENCRYPTION_KEYS_OLD`,
  la nouvelle dans `TICKETING_ENCRYPTION_KEY`, redéployer, rechiffrer (§7), puis
  retirer l'ancienne une fois les conversations e-mail en cours closes.

Réseau sortant requis pour le canal e-mail : 993/143 (IMAP), 465/587 (SMTP).

## 4. Sauvegarde PostgreSQL (obligatoire avant toute migration)

Aucune sauvegarde automatique n'est définie dans `docker-compose.yml`.

```bash
mkdir -p /root/backups && docker exec devflowdb sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > /root/backups/devflow_$(date +%F_%H%M).dump
```

Contrôler que l'archive est lisible et non vide :

```bash
ls -lh /root/backups/ | tail -3
```

```bash
docker exec -i devflowdb pg_restore -l < "$(ls -t /root/backups/devflow_*.dump | head -1)" | grep -c 'TABLE DATA'
```

Copier l'archive hors du serveur. Les fichiers (`media_volume`, MinIO) ne sont
pas touchés par cette version.

## 5. Déploiement

1. Renseigner les variables du §3 dans Dokploy.
2. Sauvegarde du §4.
3. Déployer `main` (Dokploy → Deploy). L'image reconstruit le frontend et installe
   les dépendances.
4. Migration, **sur autorisation explicite uniquement**, immédiatement après le
   démarrage du nouveau conteneur :

```bash
docker exec -it devflowweb python manage.py migrate
```

5. Redémarrer les workers pour qu'ils chargent le nouveau code et les variables :

```bash
docker restart devflowcelery devflowbeat
```

Ordre « code puis migration » : avec l'ancien code sur le nouveau schéma, la
création de tickets échouerait (colonne `source` obligatoire, inconnue de
l'ancien code). Entre les étapes 3 et 4, seules les pages Tickets sont en erreur.

## 6. Contrôles après déploiement

```bash
docker exec devflowweb python manage.py showmigrations project | tail -3
```

```bash
docker exec devflowweb python manage.py ticketing_reencrypt_secrets --dry-run
```

Attendu : `N secret(s) lisible(s), 0 illisible(s).` (lecture seule).

```bash
docker exec devflowweb python manage.py shell -c "from django.conf import settings; print(settings.CACHES['default']['BACKEND'])"
```

Attendu : `django.core.cache.backends.redis.RedisCache`.

```bash
docker exec devflowcelery celery -A ProjectFlow.celery:app inspect ping
```

```bash
docker logs --tail 40 devflowbeat
```

Puis, dans l'application : liste `/app/tickets`, création manuelle d'un ticket,
« Tester la connexion » d'une boîte e-mail, envoi d'un e-mail de test et réponse
de l'agent.

## 7. Rechiffrement des secrets (optionnel, modifie des données)

À lancer seulement une fois la version validée, sur autorisation explicite :

```bash
docker exec devflowweb python manage.py ticketing_reencrypt_secrets
```

La commande est idempotente et n'affiche aucune valeur. Tant qu'elle n'a pas été
lancée, un retour à la version précédente reste immédiat.

## 8. Retour arrière

### Application

Dokploy → redéployer le commit précédent, puis :

```bash
docker restart devflowcelery devflowbeat
```

- Cette version n'ajoute aucune migration : revenir au commit `8c0ffda` ne
  demande aucune action en base.
- Si le rechiffrement du §7 a été exécuté, l'ancienne version (qui ignore
  `TICKETING_ENCRYPTION_KEY`) ne lirait plus les secrets. Avant de revenir en
  arrière : déplacer la valeur de `TICKETING_ENCRYPTION_KEY` dans
  `TICKETING_ENCRYPTION_KEYS_OLD`, vider `TICKETING_ENCRYPTION_KEY`, redéployer,
  relancer la commande du §7 (rechiffre avec la clé dérivée de `SECRET_KEY`).

### Base de données

Uniquement pour annuler `0055` (retour au commit `8cf2daa`), sur autorisation
explicite. Arrêter d'abord les traitements de fond :

```bash
docker stop devflowcelery devflowbeat
```

Option A — migration inverse, à lancer **avant** de redéployer l'ancien commit
(seul le code actuel sait l'annuler). Elle supprime les boîtes e-mail, le journal
des e-mails et les colonnes `source`, `created_by`, `mailbox` ; les tickets sont
conservés :

```bash
docker exec -it devflowweb python manage.py migrate project 0054
```

Option B — restauration complète de la sauvegarde du §4 (perd tout ce qui a été
écrit depuis), conteneur web arrêté (`docker stop devflowweb`) :

```bash
docker exec -i devflowdb sh -c 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists --no-owner' < /root/backups/devflow_AAAA-MM-JJ_HHMM.dump
```

Redéployer ensuite le commit correspondant au schéma restauré.

## 9. Supervision

| Signal | Où le voir | Action |
|---|---|---|
| `unreadable secret … (TICKETING_ENCRYPTION_KEY ?)` | `docker logs devflowweb` | Clé modifiée ou absente : restaurer la valeur ou la placer dans `…_KEYS_OLD` |
| Boîte en échec (3 relèves consécutives) | Notification aux administrateurs support, page Canaux e-mail | Vérifier identifiants IMAP, pare-feu |
| E-mails `DEAD` / `REJECTED` | Page Canaux e-mail → historique | Retraiter depuis l'interface |
| Webhooks `DEAD` | Applications → livraisons | Relance manuelle après correction côté client |
| File Celery | Flower, `celery inspect active` | Relèves toutes les 2 min, reprises toutes les 10 min |
| Redis indisponible | 500 sur les actions limitées en débit, relèves sautées | Redis porte désormais broker, Channels **et** cache |

## 10. Points d'attention connus

- PostgreSQL est publié sur le port hôte `5438` : le filtrer au pare-feu ou
  retirer la publication.
- La protection anti-rejeu HMAC, les quotas d'application et les verrous de
  relève reposaient sur un cache par processus ; ils sont effectifs entre
  workers uniquement avec le cache Redis (§6).
- Pas de limitation spécifique des échecs d'authentification de l'API
  d'intégration (secrets aléatoires de 256 bits) ; à ajouter au niveau du proxy
  si nécessaire.
