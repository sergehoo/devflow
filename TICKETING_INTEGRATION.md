# DevFlow — Intégration du ticketing multi-applications

Les tickets arrivent par **trois canaux** : l'API des applications externes (§ 1–6), la **saisie manuelle** dans DevFlow (§ 8) et l'**e-mail** (§ 9). Les trois passent par le même service de création (`ticketing._create`) : référence unique `TCK-xxxxx`, SLA, routage, journal d'audit, notifications et webhooks sont identiques. DevFlow classe, route vers une équipe, suit le SLA et renvoie chaque changement par webhook signé.

```
Application (navigateur / mobile)
      │  widget « Signaler un problème » (aucun secret)
      ▼
Backend de l'application ──HMAC──► DevFlow /api/v1/integrations/tickets/
      ▲                                        │
      └────────── webhooks signés ◄────────────┘  (ticket.created, assigned, updated, …)
```

> **Règle d'or** : le secret d'intégration ne doit jamais se trouver dans un navigateur, une application mobile ou un dépôt de code. Les clients publics passent par le backend de l'application, qui signe les requêtes.

## 1. Créer une application

DevFlow › Support › Applications connectées › **Nouvelle application**. Cette action est réservée au rôle propriétaire du workspace (droit `ticket.admin`).

- **Identifiants** : l'identifiant `app_…` et le secret `dfs_…` sont affichés **une seule fois**. Le secret est stocké chiffré dans DevFlow (Fernet, clé `TICKETING_ENCRYPTION_KEY` ou, à défaut, dérivée de `SECRET_KEY`). L'écran ne montre ensuite que ses 4 derniers caractères. **Renouveler le secret** invalide immédiatement l'ancien.
- **Paramètres** : équipe par défaut, politique SLA, projet DevFlow associé, URL et événements du webhook, limites (requêtes par minute, tickets par jour, taille des pièces jointes) et durée de conservation des données du déclarant.

> **Production** : définissez `TICKETING_ENCRYPTION_KEY` (chaîne aléatoire longue). Sinon, une rotation de `SECRET_KEY` rendrait les secrets illisibles et obligerait à les renouveler.

## 2. Authentification

### Signature HMAC (recommandée)

| En-tête | Valeur |
|---|---|
| `X-DevFlow-App` | identifiant `app_…` |
| `X-DevFlow-Timestamp` | horodatage UNIX en secondes (fenêtre de ±5 min) |
| `X-DevFlow-Signature` | `sha256=` + HMAC-SHA256 hexadécimal du message ci-dessous |

```
message = "{timestamp}.{MÉTHODE}.{chemin}.{sha256_hex(corps brut)}"
ex. : 1794268000.POST./api/v1/integrations/tickets/.9f86d08…
```

- **Rejeu** : une même signature n'est acceptée qu'une fois. Pour réessayer, signez de nouveau avec un nouvel horodatage.
- **Chemin** : c'est le chemin seul, sans domaine ni paramètres de requête. Pour une requête GET, le corps est vide (`sha256("")`).

### Identifiants dédiés (serveur à serveur)

`Authorization: DevFlowApp app_…:dfs_…`, uniquement via HTTPS et depuis un backend.

Aucune session ni cookie n'est accepté sur l'API d'intégration. Une application **suspendue** ou **archivée** reçoit `401`.

## 3. API d'intégration (v1)

### Créer un ticket — `POST /api/v1/integrations/tickets/`

JSON, ou `multipart/form-data` avec les pièces jointes : champ `attachments`, 5 fichiers au maximum. En multipart, `reporter` et `metadata` sont du JSON sérialisé.

| Champ | Règle |
|---|---|
| `external_id` (obligatoire) | identifiant chez vous, `[A-Za-z0-9._:-]{1,120}`, unique par application |
| `title` (obligatoire) | 3 à 200 caractères |
| `description` | 20 000 caractères au maximum |
| `category` | `BUG` · `INCIDENT` · `QUESTION` · `FEATURE` · `ACCESS` · `OTHER` |
| `severity` | `CRITICAL` · `MAJOR` · `MINOR` · `TRIVIAL` (gravité technique ; la priorité opérationnelle P1–P4 est fixée par DevFlow) |
| `reporter` | `{ "id", "name", "email" }` : identité externe du déclarant |
| `environment`, `app_version` | 40 caractères au maximum |
| `url` | page concernée |
| `metadata` | contexte technique, 8 Ko au maximum |

Assainissement côté DevFlow :
- **`url`** : les paramètres sensibles (`token`, `code`, `session`, `key`…) et le fragment sont retirés.
- **`metadata`** : les clés sensibles (`password`, `token`, `secret`, `cookie`, `authorization`, `card`…) sont supprimées, la profondeur et les tailles sont bornées.

**Codes de réponse :**
- **`201 Created`** : ticket créé.
- **`200 OK`** avec `"duplicate": true` : même `external_id`, ou même `Idempotency-Key` déjà traités.
- **`422`** : `Idempotency-Key` réutilisée pour un autre `external_id`.
- **`429`** : débit, quota journalier ou anti-spam dépassé (20 tickets par heure et par déclarant).
- **`400`** : validation, ou type ou taille de fichier refusés.

Ajoutez `Idempotency-Key: <clé unique>` (120 caractères au maximum) pour rejouer sans risque de doublon.

```json
{ "reference": "TCK-00042", "external_id": "PAY-1001", "status": "QUALIFIED", "status_label": "Qualifié",
  "category": "BUG", "severity": "MAJOR", "priority": "P2", "assigned": false, "created_at": "…", "duplicate": false }
```

### Consulter — `GET /api/v1/integrations/tickets/{external_id}/`

Renvoie le statut et l'historique **public** :
- les commentaires publics, ceux d'un agent signés « Support » ;
- les événements publics ;
- les pièces jointes publiques.

Les notes et pièces jointes internes, l'équipe et l'agent ne sont jamais exposés.

### Lister — `GET /api/v1/integrations/tickets/?reporter_id=&status=&page=&page_size=`

Liste paginée des tickets de **votre** application uniquement.

### Ajouter des informations — `POST /api/v1/integrations/tickets/{external_id}/comments/`

```json
{ "body": "Toujours bloqué après mise à jour", "author": { "id": "u-42", "name": "Awa Koné" } }
```

Effets sur le statut :
- **En attente** : la réponse du déclarant fait repasser le ticket en **En cours**.
- **Résolu** : le ticket est **rouvert** (`ticket.reopened`).
- **Clôturé** ou **annulé** : `409`, il faut créer un nouveau ticket.

Un message identique envoyé deux fois en moins de 60 s renvoie `409`.

### Pièces jointes

Types acceptés : PNG, JPEG, GIF, WebP, PDF, texte, CSV, JSON, ZIP, MP4, WebM. La taille est limitée par la valeur `max_attachment_mb` de l'application.

La signature binaire doit correspondre au type déclaré. Les fichiers sont privés et servis après contrôle des droits (`nosniff`, `sandbox`).

## 4. Webhooks sortants

Événements :
- `ticket.created`
- `ticket.assigned`
- `ticket.updated`
- `ticket.commented` (réponses publiques uniquement)
- `ticket.resolved`
- `ticket.closed`
- `ticket.reopened`

```
POST https://votre-app/devflow/webhooks
X-DevFlow-Event: ticket.resolved
X-DevFlow-Event-Id: 3f0c…           ← clé d'idempotence : ignorez un identifiant déjà traité
X-DevFlow-Timestamp: 1794268000
X-DevFlow-Signature: sha256=hex(HMAC_SHA256(secret, "{timestamp}." + corps brut))
X-DevFlow-Delivery-Attempt: 1

{ "id": "3f0c…", "event": "ticket.resolved", "created_at": "…", "ticket": { …vue publique… } }
```

- **Accusé de réception** : répondez `2xx` en moins de 10 s. Les redirections ne sont pas suivies.
- **Nouvelles tentatives** : 1 min, 5 min, 30 min, 2 h puis 12 h. Après 6 tentatives, la livraison est **abandonnée** ; elle peut être relancée depuis DevFlow (Applications › Livraisons).
- **SSRF** : l'URL doit être en HTTPS. Les adresses privées, locales ou réservées sont refusées à l'enregistrement **et** à chaque envoi. `TICKET_WEBHOOK_ALLOW_PRIVATE=True` est réservé aux environnements de test.
- **Non bloquant** : l'envoi est planifié après validation de la transaction. Si le broker est indisponible, le balayage périodique (`retry_ticket_webhooks_task`, toutes les 10 min) reprend la livraison.

## 5. Exemples de proxy backend

### Node.js (Express)

```js
import crypto from "node:crypto";
const KEY = process.env.DEVFLOW_APP_KEY, SECRET = process.env.DEVFLOW_APP_SECRET, BASE = "https://flow.example.com";

async function devflow(method, path, body = "") {
  const ts = Math.floor(Date.now() / 1000).toString();
  const digest = crypto.createHash("sha256").update(body).digest("hex");
  const sig = crypto.createHmac("sha256", SECRET).update(`${ts}.${method}.${path}.${digest}`).digest("hex");
  return fetch(BASE + path, { method, body: body || undefined, headers: {
    "Content-Type": "application/json", "X-DevFlow-App": KEY, "X-DevFlow-Timestamp": ts, "X-DevFlow-Signature": `sha256=${sig}`,
  } });
}

// Route appelée par le widget : l'utilisateur est authentifié par VOTRE session.
app.post("/support/report", requireLogin, async (req, res) => {
  const payload = { ...req.body, reporter: { id: String(req.user.id), name: req.user.displayName } }; // identité contrôlée côté serveur
  const r = await devflow("POST", "/api/v1/integrations/tickets/", JSON.stringify(payload));
  res.status(r.status).json(await r.json());
});

// Webhook : vérifier la signature AVANT de parser.
app.post("/devflow/webhooks", express.raw({ type: "application/json" }), (req, res) => {
  const ts = req.get("X-DevFlow-Timestamp"), sig = req.get("X-DevFlow-Signature").replace("sha256=", "");
  const expected = crypto.createHmac("sha256", SECRET).update(`${ts}.`).update(req.body).digest("hex");
  if (!crypto.timingSafeEqual(Buffer.from(sig), Buffer.from(expected)) || Math.abs(Date.now() / 1000 - ts) > 300) return res.sendStatus(401);
  // dédoublonner sur X-DevFlow-Event-Id, puis traiter JSON.parse(req.body)
  res.sendStatus(204);
});
```

### Python

```python
import hashlib, hmac, json, time, requests

def devflow(method, path, payload=None):
    body = json.dumps(payload).encode() if payload is not None else b""
    ts = str(int(time.time()))
    msg = f"{ts}.{method}.{path}.{hashlib.sha256(body).hexdigest()}"
    sig = hmac.new(SECRET.encode(), msg.encode(), hashlib.sha256).hexdigest()
    return requests.request(method, BASE + path, data=body or None, timeout=10, headers={
        "Content-Type": "application/json", "X-DevFlow-App": KEY, "X-DevFlow-Timestamp": ts, "X-DevFlow-Signature": f"sha256={sig}"})
```

Pour un envoi multipart (pièces jointes), la signature porte sur le corps multipart **tel qu'il est envoyé**. Construisez d'abord le corps, puis signez-le.

## 6. Widget React « Signaler un problème »

Source : `frontend/src/widget/ReportProblemWidget.tsx` et `frontend/src/widget/context.ts`. Le composant est autonome : React uniquement, styles intégrés.

```tsx
<ReportProblemWidget
  submitUrl="/support/report"          // VOTRE backend (proxy signé)
  statusUrl="/support/tickets"         // GET /support/tickets/{external_id} → proxy GET DevFlow
  appVersion="2.4.1" environment="PRODUCTION"
  headers={{ "X-CSRFToken": csrf }}    // jeton de VOTRE session si nécessaire
/>
```

Fonctions :
- **Formulaire** : résumé, description, type et impact.
- **Pièces jointes** : 3 au maximum, 10 Mo chacune.
- **Capture d'écran** : uniquement sur clic de l'utilisateur ; l'écran est choisi par l'utilisateur, l'aperçu peut être retiré, et le flux est coupé aussitôt la capture faite.
- **Contexte technique** : désactivable, et limité à la page (origine et chemin, **sans** paramètres ni fragment), au navigateur, à la langue et à la taille d'écran.
- **Confirmation** : le numéro de ticket est affiché.
- **Consultation du statut**.
- **Idempotence** : l'en-tête `Idempotency-Key` est égal à `external_id`, donc un double clic ou un nouvel essai ne crée pas de doublon.

Le widget ne lit jamais les cookies, le stockage local ni les champs de saisie.

**Applications mobiles et clients non React** : même principe. L'application appelle son backend, qui signe la requête avec l'API ci-dessus.

## 7. Côté DevFlow

- **Routage** (Support › Routage & SLA) : la règle s'écrit application + catégorie + gravité → équipe, en option avec affectation automatique et priorité imposée. La première règle active applicable, par ordre croissant, l'emporte. Sinon le ticket va à l'équipe par défaut de l'application, sinon dans la **file non assignée**.
- **Affectation automatique** : elle désigne l'agent actif le moins chargé (tickets ouverts). Il doit être membre de l'équipe, ni inactif ni en congé, et détenir un droit sur les tickets.
- **Affectation manuelle** : elle vérifie les mêmes conditions. Un membre d'équipe peut *prendre* un ticket de son équipe ; affecter quelqu'un d'autre exige `ticket.assign`.
- **Workflow** : Nouveau → Qualifié → Assigné → En cours → En attente → Résolu → Clôturé, avec réouverture et annulation.
  - **Validation** : les transitions sont validées par Django.
  - **Annulation** : motif obligatoire, réservée aux gestionnaires, comme la qualification et la clôture.
  - **Réouverture** : un ticket Résolu repasse En cours ; un ticket Clôturé repasse Qualifié, sur décision d'un gestionnaire.
- **SLA** :
  - délais de première réponse et de résolution par priorité, en minutes ouvrées selon le calendrier de la politique (jours, heures, fuseau horaire) ;
  - le statut **En attente** met le SLA en pause et décale les échéances ;
  - alerte à X % du délai, dépassement, puis **escalade automatique** (responsables d'équipe, équipe d'escalade, propriétaire du workspace) ;
  - vérification toutes les 5 min (`check_ticket_slas_task`).
- **Tâches** : « Créer une tâche » crée une tâche dans le projet du ticket ou de l'application. Quand la tâche liée est **terminée**, le ticket passe en **Résolu**. La synchronisation est à sens unique, donc sans boucle.
- **Notifications** : notifications in-app poussées en temps réel (WebSocket `/ws/me/`, événement `ticket.changed` qui rafraîchit les listes) pour l'affectation, la réponse du déclarant, l'alerte et le dépassement de SLA, et l'escalade.
- **Droits (RBAC)** :

  | Rôle | Droits |
  |---|---|
  | Propriétaire | `ticket.*` : administration des applications, du routage et du SLA |
  | Chef de projet, Team lead | `ticket.view`, `ticket.manage`, `ticket.assign`, `ticket.create` |
  | Membre | tickets de ses équipes, qui lui sont affectés ou qu'il a créés (`ticket.view_assigned`, `ticket.work_assigned`, `ticket.create`) |
  | Client | aucun accès |

- **Conservation** : la purge quotidienne (`purge_ticket_personal_data_task`) anonymise le déclarant et le contexte technique des tickets clôturés au-delà de `retention_days`.
- **Traçabilité** : chaque action produit un `TicketEvent` (acteur, origine API / interface / système, valeurs avant et après).


## 8. Création manuelle (DevFlow)

- **Où** : bouton « Nouveau ticket » dans Ticket Center, la liste des tickets et la carte « Tickets » de la fiche projet (projet prérempli). La fiche du ticket s'ouvre après création.
- **API interne** (session + CSRF) : `POST /api/v1/tickets/` (JSON ou multipart, `attachments` ≤ 5 fichiers) ; `GET /api/v1/tickets/create-options/?workspace=` (applications actives, projets, équipes, droits) ; `GET /api/v1/tickets/agents/?team=` (agents affectables, `ticket.assign`).
- **Champs** : application source (obligatoire, active, du même workspace), titre, description, catégorie, gravité, priorité (imposable avec `ticket.manage`, sinon dérivée de la gravité), projet, équipe et responsable (avec `ticket.assign` ; responsable = membre actif de l'équipe ayant un droit ticket), déclarant facultatif (saisie pour un tiers).
- **Affectation** : sans équipe ni responsable, les règles de routage s'appliquent (y compris l'affectation automatique). Sinon l'affectation manuelle est journalisée (« Affectation à la création »).
- **Garde-fous** : `ticket.create` vérifié par Django, objets limités aux workspaces de l'utilisateur (aucune énumération inter-tenant), 30 créations / 10 min par utilisateur, mêmes contrôles de pièces jointes que l'API.
- **Source** : `MANUAL`, auteur conservé (`created_by`) ; le créateur peut suivre et compléter son ticket.

## 9. Canal e-mail

### Configuration (Support › Canaux e-mail, droit `ticket.admin`)

Une boîte = une adresse de support rattachée à une application (et éventuellement un projet), plusieurs boîtes par workspace.

- **Réception IMAP** : SSL/TLS (993) ou STARTTLS (143), certificat vérifié, relève toutes les 2 min (`poll_ticket_mailboxes_task`), 50 messages par passage.
- **Réception par webhook du fournisseur** : `POST /api/v1/integrations/mail/<inbound_key>/` avec le message brut (RFC 822) en corps, ou un champ de formulaire `email` / `body-mime`. Signature obligatoire :

  ```
  X-DevFlow-Timestamp: <epoch secondes>          (fenêtre ± 5 min, rejeu refusé)
  X-DevFlow-Signature: sha256=<hex HMAC-SHA256(secret, "<timestamp>." + corps brut)>
  ```

  Le secret est affiché une seule fois (création ou renouvellement).
- **Envoi SMTP** : SSL/TLS (465) ou STARTTLS (587). Sans SMTP propre, la messagerie DevFlow envoie avec « Répondre à » = adresse de la boîte.
- **Test de connexion** (IMAP + SMTP, sans envoi), relève immédiate, historique des messages, file des messages rejetés avec « Retraiter ».
- Identifiants chiffrés (Fernet, clé `TICKETING_ENCRYPTION_KEY`), jamais renvoyés au navigateur ni journalisés ; hôtes privés refusés (SSRF) sauf `TICKET_MAIL_ALLOW_PRIVATE_HOSTS=True` (serveur interne).

### Traitement

1. **Stockage durable d'abord** : le message brut est enregistré (dédupliqué par boîte + `Message-ID`) ; l'UID IMAP n'avance et le message n'est marqué lu qu'ensuite.
2. **Traitement asynchrone** (`process_ticket_email_task`, idempotent, transaction atomique, nouvel essai 1 min / 5 min / 30 min / 2 h puis abandon visible dans la file).
3. **Réponses automatiques ignorées** : `Auto-Submitted`, `Precedence: bulk/list`, listes de diffusion, rebonds, absences, expéditeurs `noreply` / `mailer-daemon`, messages émis par DevFlow (`X-DevFlow-Loop`, `Message-ID` connu).
4. **Anti-spam** : `X-Spam-Flag`, expéditeurs ou domaines bloqués, domaines autorisés (facultatif), 10 nouveaux tickets / h par expéditeur, 5 accusés / h par destinataire.
5. **Rattachement à un ticket** : jeton signé contenu dans les `Message-ID` envoyés par DevFlow, puis `In-Reply-To` / `References` connus de la boîte. La référence `[TCK-xxxxx]` dans l'objet **ne suffit jamais** : elle n'est acceptée que si l'expéditeur est le déclarant du ticket, sinon le message va en file de rejet.
6. **Autorisation** : le déclarant → commentaire **public** ; un agent DevFlow habilité → note **interne** ; tout autre expéditeur → rejeté. Une réponse à un ticket clôturé ouvre un nouveau ticket « Suite du ticket … ».
7. **Nouveau ticket** : objet → titre (préfixes Re/TR/Fwd retirés), corps texte (HTML converti en texte, signature retirée), pièces jointes filtrées (types autorisés, contenu vérifié, exécutables et HTML refusés, taille max de la boîte), routage et SLA, puis **accusé de réception** `[TCK-xxxxx] Objet`.

### Réponses depuis DevFlow

Sur un ticket e-mail, « Répondre par e-mail » envoie la réponse publique (et ses pièces jointes publiques) au déclarant depuis la boîte, dans le même fil (`In-Reply-To`, `References`). Les notes internes ne partent jamais par e-mail. Chaque envoi a un statut visible dans la fiche (En attente, Envoyé, Nouvel essai prévu, Non délivré) ; un échec définitif est journalisé et notifié à l'agent.

### Supervision

`last_sync_at`, `last_success_at`, dernière erreur (sans secret), échecs consécutifs avec relève espacée (2ⁿ min, 60 min max). Après 3 échecs, le propriétaire du workspace et le responsable de l'équipe par défaut sont notifiés ; une seconde notification signale le rétablissement. Balayage de reprise toutes les 10 min (`retry_ticket_emails_task`).

### Paramètres

| Variable | Défaut | Rôle |
|---|---|---|
| `TICKETING_ENCRYPTION_KEY` | `SECRET_KEY` | Chiffrement des secrets et jetons de conversation |
| `TICKET_MAIL_MAX_MB` | 25 | Taille maximale d'un e-mail entrant |
| `TICKET_MAIL_ALLOW_PRIVATE_HOSTS` | False | Autoriser un serveur IMAP / SMTP sur le réseau privé |
