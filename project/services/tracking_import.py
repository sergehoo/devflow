"""
Import du classeur « Suivi Pôle Développement ».

Le classeur porte deux blocs de mêmes colonnes dans une feuille : les projets,
puis les tâches / activités. Ce module :

  * ``parse_workbook``   lit le fichier sans interpréter ce qui est ambigu ;
  * ``analyze``          rapproche chaque ligne des objets DevFlow existants et
                         propose une décision par élément ;
  * ``apply_import``     applique les décisions validées et trace chaque donnée
                         (``ProjectImportRecord``) ;
  * ``rollback_import``  annule logiquement un import.

Règles : aucun compte utilisateur n'est créé, aucune valeur ambiguë n'est
corrigée en silence (elle est conservée et signalée), et réimporter le même
fichier ne crée aucun doublon.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import unicodedata
from collections import Counter
from datetime import date, datetime

from django.db import transaction
from django.utils import timezone
from openpyxl import load_workbook
from openpyxl.utils.datetime import from_excel

from project import models as dm
from project.utils.workspaces import users_in_workspaces

KIND = "tracking_sheet"
SOURCE = "tracking_import"
PROJECTS, TASKS = "PROJECTS", "TASKS"
DEFAULT_CONTAINER = "Activités Pôle Développement"
CONTAINER_CATEGORY = "activites-courantes"
MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_ROWS = 5000

# Vocabulaire du classeur → clé normalisée.
STATUS_KEYS = {
    "en cours": "en_cours", "encours": "en_cours", "en-cours": "en_cours",
    "suspendu": "suspendu", "suspendue": "suspendu", "en pause": "suspendu",
    "realise": "realise", "realisee": "realise", "termine": "realise", "terminee": "realise",
    "annule": "annule", "annulee": "annule", "abandonne": "annule",
}
STATUS_LABELS = {"en_cours": "En cours", "suspendu": "suspendu", "realise": "réalisé", "annule": "Annulé"}
PROJECT_STATUS = {"en_cours": "IN_PROGRESS", "suspendu": "ON_HOLD", "realise": "DONE", "annule": "CANCELLED"}
# Task n'a pas de statut « en pause » : « suspendu » devient « bloquée ».
TASK_STATUS = {"en_cours": "IN_PROGRESS", "suspendu": "BLOCKED", "realise": "DONE", "annule": "CANCELLED"}

ALERT_KINDS = ("DECISION", "DEPENDENCY", "BLOCKER", "RISK", "ALERT")
ALERT_LABELS = {
    "DECISION": "Décision attendue", "DEPENDENCY": "Dépendance", "BLOCKER": "Blocage",
    "RISK": "Risque", "ALERT": "Alerte",
}

HEADERS = (
    ("company", ("entreprise",)),
    ("owner", ("porteur",)),
    ("contact", ("interlocuteur",)),
    ("done", ("actions menees", "action menee")),
    ("next", ("actions a venir", "action a venir")),
    ("alert", ("alerte",)),
    ("start", ("date de debut", "debut")),
    ("end", ("date de fin", "echeance")),
    ("progress", ("etat d avancement", "avancement")),
    ("status", ("statut",)),
    ("title", ("projet", "tache", "activite")),
)
FIELD_LABELS = {
    "company": "Entreprise", "title": "Intitulé", "owner": "Porteur", "contact": "Interlocuteur",
    "done": "Actions menées", "next": "Actions à venir", "alert": "Alerte / décision",
    "start": "Date de début", "end": "Date de fin prévue", "progress": "Avancement", "status": "Statut",
}


class TrackingImportError(Exception):
    """Erreur présentable à l'utilisateur (fichier illisible, décision invalide…)."""


# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------
def norm(text) -> str:
    """Minuscules, sans accents, espaces compactés."""
    text = unicodedata.normalize("NFKD", str(text if text is not None else ""))
    text = "".join(c for c in text if not unicodedata.combining(c)).replace("’", "'")
    return re.sub(r"\s+", " ", text).strip().casefold()


def key(text) -> str:
    """Clé de rapprochement : ``norm`` sans ponctuation."""
    return re.sub(r"[^a-z0-9]+", " ", norm(text)).strip()


def _text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _clip(text: str, size: int) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= size else text[: size - 1].rstrip() + "…"


_BULLET = re.compile(r"^\s*(?:[—–\-•·*►▪■]+|\d{1,2}\s*[.)](?!\d))\s*")


def split_items(text) -> list[str]:
    """
    Cellule multiligne → liste d'éléments. Les puces (—, -, •, « 1. ») sont
    retirées ; si la cellule en utilise, une ligne sans puce prolonge l'élément
    précédent.
    """
    lines = [line.strip() for line in str(text or "").replace("\r", "\n").split("\n")]
    lines = [line for line in lines if line]
    marked = [bool(_BULLET.match(line)) for line in lines]
    items: list[str] = []
    for line, is_marked in zip(lines, marked):
        body = _BULLET.sub("", line).strip() if is_marked else line
        if not body:
            continue
        if any(marked) and not is_marked and items:
            items[-1] = f"{items[-1]} {body}"
        else:
            items.append(re.sub(r"\s+", " ", body))
    return items


def split_people(text) -> list[str]:
    parts = re.split(r"[\n;,/]+|\s+et\s+", str(text or ""))
    seen, out = set(), []
    for part in parts:
        name = re.sub(r"\s+", " ", _BULLET.sub("", part)).strip(" .:-")
        if name and key(name) not in seen:
            seen.add(key(name))
            out.append(name)
    return out


def split_companies(text) -> list[str]:
    seen, out = set(), []
    for part in re.split(r"[\n;,/]+", str(text or "")):
        name = re.sub(r"\s+", " ", part).strip()
        if name and key(name) not in seen:
            seen.add(key(name))
            out.append(name)
    return out


_DATE = re.compile(r"(?<!\d)(\d{1,2})\s*[/.\-]\s*(\d{1,2})\s*[/.\-]\s*(\d{4}|\d{2})(?!\d)")
_ISO = re.compile(r"(?<!\d)(\d{4})-(\d{2})-(\d{2})(?!\d)")


def _serial_date(number):
    """Numéro de série Excel plausible (1955 → 2119) → date."""
    if 20000 <= number <= 80000:
        try:
            return from_excel(number).date()
        except Exception:
            return None
    return None


def parse_dates(value) -> dict:
    """
    Retourne ``{"dates": [iso…], "lines": [iso|None…], "invalid": [texte…]}``.
    Les dates texte sont lues jour/mois/année ; une année sur deux chiffres
    appartient aux années 2000. ``lines`` garde la position de chaque ligne de
    la cellule (alignement avec les « actions à venir »).
    """
    out = {"dates": [], "lines": [], "invalid": []}
    if value is None or value == "":
        return out
    if isinstance(value, (datetime, date)):
        day = value.date() if isinstance(value, datetime) else value
        out["dates"] = [day.isoformat()]
        out["lines"] = [day.isoformat()]
        return out
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        day = _serial_date(value)
        if day:
            out["dates"] = out["lines"] = [day.isoformat()]
        else:
            out["invalid"].append(_text(value))
        return out
    for line in str(value).replace("\r", "\n").split("\n"):
        line = line.strip()
        if not line:
            out["lines"].append(None)
            continue
        found = []
        for y, m, d in _ISO.findall(line):
            found.append((int(y), int(m), int(d)))
        if not found:
            for d, m, y in _DATE.findall(line):
                year = int(y) + 2000 if len(y) == 2 else int(y)
                found.append((year, int(m), int(d)))
        if not found and line.isdigit():
            day = _serial_date(int(line))
            if day:
                found.append((day.year, day.month, day.day))
        valid = []
        for year, month, day in found:
            try:
                valid.append(date(year, month, day).isoformat())
            except ValueError:
                pass
        if not valid:
            out["invalid"].append(line)
            out["lines"].append(None)
            continue
        out["dates"].extend(valid)
        out["lines"].append(valid[0])
    while out["lines"] and out["lines"][-1] is None:
        out["lines"].pop()
    return out


def parse_progress(value, number_format="General") -> dict:
    """
    Avancement → ``{"value": int|None, "ambiguity": {...}|None, "warning": str}``.

    Une valeur ambiguë n'est jamais convertie : ``1`` reste ``1`` (1 % ou
    100 % ?), la conversion n'est qu'une proposition à valider.
    """
    result = {"value": None, "ambiguity": None, "warning": ""}
    if value is None or str(value).strip() == "":
        return result
    # Vrai format pourcentage uniquement : « 0"%" » (signe littéral) n'en est pas un.
    percent_cell = "%" in re.sub(r'"[^"]*"|\\.', "", str(number_format or ""))
    if isinstance(value, str):
        match = re.fullmatch(r"\s*(\d+(?:[.,]\d+)?)\s*(%?)\s*", value)
        if not match:
            result["warning"] = f"Avancement illisible : « {value.strip()} »."
            return result
        number = float(match.group(1).replace(",", "."))
        if match.group(2):  # « 30 % » écrit en toutes lettres : sans ambiguïté
            if number <= 100:
                result["value"] = round(number)
            else:
                result["warning"] = f"Avancement hors limites : « {value.strip()} »."
            return result
        percent_cell = False
    elif isinstance(value, bool) or not isinstance(value, (int, float)):
        result["warning"] = f"Avancement illisible : « {value} »."
        return result
    else:
        number = float(value)

    shown = f"{number:g}".replace(".", ",")
    if number < 0 or number > 100:
        result["warning"] = f"Avancement hors limites : {shown}."
    elif number == 1:
        reason = ("la cellule est au format pourcentage, Excel affiche 100 %"
                  if percent_cell else "1 % ou 100 % ?")
        result["value"] = 1
        result["ambiguity"] = {
            "message": f"Avancement saisi « 1 » : {reason}.",
            "options": [{"value": 1, "label": "Conserver 1 %"}, {"value": 100, "label": "Appliquer 100 %"}],
            "default": 1, "suggestion": 100,
        }
    elif 0 < number < 1:
        proposed = round(number * 100)
        if percent_cell:  # 0,3 au format % : Excel affiche 30 %
            result["value"] = proposed
        else:
            result["ambiguity"] = {
                "message": f"Avancement saisi « {shown} » : fraction ({proposed} %) ou valeur en % ?",
                "options": [{"value": None, "label": "Ne pas renseigner"},
                            {"value": proposed, "label": f"Appliquer {proposed} %"}],
                "default": None, "suggestion": proposed,
            }
    elif percent_cell and number > 1:
        result["value"] = round(number)
        result["warning"] = (f"Avancement « {shown} » dans une cellule au format pourcentage "
                             f"(Excel affiche {round(number * 100)} %) : valeur {round(number)} % conservée.")
    else:
        result["value"] = round(number)
    return result


_DECISION = re.compile(r"\b(decision|decisions|arbitrage|validation|valider|validee?|accord|approbation|"
                       r"approuver|feu vert|signature)\b")
_DEPENDENCY = re.compile(r"\b(achat|acquisition|commande|livraison|fournisseur|materiel|capteur|capteurs|"
                         r"licence|licences|budget|paiement|devis|recrutement)\b")
_BLOCKER = re.compile(r"\b(en attente|attente|bloque|bloquee|blocage|bloquant|suspendu)\b")
_RISK = re.compile(r"\b(risque|risques|retard|derive|depassement|critique|urgent|urgence)\b")


def classify_alert(text) -> dict:
    """Classement déterministe (sans IA) d'une alerte / décision : simple proposition."""
    k = key(text)
    if _DECISION.search(k):
        kind, reason = "DECISION", "mention d'une décision ou validation attendue"
    elif _DEPENDENCY.search(k):
        kind, reason = "DEPENDENCY", "dépend d'un achat, d'une livraison ou d'un tiers"
    elif _BLOCKER.search(k):
        kind, reason = "BLOCKER", "élément en attente"
    elif _RISK.search(k):
        kind, reason = "RISK", "vocabulaire de risque ou de retard"
    else:
        kind, reason = "ALERT", "aucun mot-clé reconnu"
    severity = "MEDIUM"
    if re.search(r"\b(critique|urgent|urgence)\b", k):
        severity = "CRITICAL"
    elif kind == "BLOCKER" or re.search(r"\b(bloque|bloquee|blocage|bloquant)\b", k):
        severity = "HIGH"
    elif kind == "ALERT":
        severity = "LOW"
    return {"kind": kind, "severity": severity, "reason": reason}


# ---------------------------------------------------------------------------
# Lecture du classeur
# ---------------------------------------------------------------------------
def _header_columns(cells) -> dict:
    """Ligne d'en-tête → ``{champ: n° de colonne}`` (vide si ce n'en est pas une)."""
    cols: dict[str, int] = {}
    for cell in cells:
        if not isinstance(cell.value, str):
            continue
        k = key(cell.value)
        if not k or len(k) > 40:
            continue
        for field, prefixes in HEADERS:
            if field not in cols and any(k.startswith(p) for p in prefixes):
                cols[field] = cell.column
                break
    if len(cols) >= 5 and "title" in cols and ("status" in cols or "progress" in cols):
        return cols
    return {}


def _align(lines, dates, count):
    """Dates d'une cellule ↔ éléments d'« actions à venir » (par position, sinon par ordre)."""
    if count and len(lines) == count:
        return list(lines)
    if count and len(dates) == count:
        return list(dates)
    return [None] * count


def _parse_row(ws, r, cols, section) -> dict:
    cells = {field: ws.cell(row=r, column=c) for field, c in cols.items()}
    raw = {field: _text(cell.value) for field, cell in cells.items()}
    row_id = f"{'P' if section == PROJECTS else 'T'}{r}"
    warnings, ambiguities = [], []

    def warn(field, code, message):
        warnings.append({"row": row_id, "line": r, "field": field, "code": code, "message": message})

    title_items = split_items(raw.get("title", ""))
    title = " · ".join(title_items)
    if not title:
        warn("title", "missing_title", "Ligne sans intitulé : ignorée par défaut.")

    companies = split_companies(raw.get("company", ""))
    for name in companies:
        if " - " in name:
            warn("company", "ambiguous_company",
                 f"« {name} » : une seule entreprise ou deux ? Conservée telle quelle.")

    start = parse_dates(cells["start"].value) if "start" in cells else parse_dates(None)
    end = parse_dates(cells["end"].value) if "end" in cells else parse_dates(None)
    dates = {}
    for field, parsed, pick in (("start", start, min), ("end", end, max)):
        for bad in parsed["invalid"]:
            warn(field, "invalid_date", f"{FIELD_LABELS[field]} illisible : « {bad} » (texte conservé).")
        distinct = sorted(set(parsed["dates"]))
        if len(distinct) > 1:
            dates[field] = None
            ambiguities.append({
                "id": f"{row_id}:{field}", "row": row_id, "line": r, "field": field,
                "message": f"{FIELD_LABELS[field]} : {len(parsed['dates'])} dates dans la cellule.",
                "options": [{"value": None, "label": "Ne pas renseigner"}]
                + [{"value": d, "label": date.fromisoformat(d).strftime("%d/%m/%Y")} for d in distinct],
                "default": None, "suggestion": pick(distinct),
            })
        else:
            dates[field] = distinct[0] if distinct else None

    progress = parse_progress(cells["progress"].value if "progress" in cells else None,
                              cells["progress"].number_format if "progress" in cells else "")
    if progress["warning"]:
        warn("progress", "progress", progress["warning"])
    if progress["ambiguity"]:
        ambiguities.append({"id": f"{row_id}:progress", "row": row_id, "line": r, "field": "progress",
                            **progress["ambiguity"]})

    status_norm = key(raw.get("status", ""))
    status_key = STATUS_KEYS.get(status_norm)
    if status_norm and not status_key:
        warn("status", "unknown_status", f"Statut inconnu : « {raw['status'].strip()} » (à mapper).")

    next_texts = split_items(raw.get("next", ""))
    next_start = _align(start["lines"], start["dates"], len(next_texts))
    next_due = _align(end["lines"], end["dates"], len(next_texts))
    alerts = []
    for i, text in enumerate(split_items(raw.get("alert", ""))):
        alerts.append({"id": f"{row_id}:a{i}", "text": text, **classify_alert(text)})

    if dates["start"] and dates["end"] and dates["end"] < dates["start"]:
        warn("end", "date_order", "La date de fin précède la date de début.")
    if status_key == "realise" and progress["value"] is not None and progress["value"] < 100:
        warn("progress", "status_progress", f"Statut « réalisé » avec un avancement de {progress['value']} %.")
    if status_key == "en_cours" and progress["value"] == 100:
        warn("progress", "status_progress", "Avancement de 100 % avec un statut « En cours ».")

    return {
        "id": row_id, "section": section, "sheet": ws.title, "row": r, "raw": raw,
        "title": title, "title_multiline": len(title_items) > 1,
        "companies": companies,
        "owners": split_people(raw.get("owner", "")),
        "contacts": split_people(raw.get("contact", "")),
        "done": [{"id": f"{row_id}:d{i}", "text": t} for i, t in enumerate(split_items(raw.get("done", "")))],
        "next": [{"id": f"{row_id}:n{i}", "text": t, "start": next_start[i], "due": next_due[i]}
                 for i, t in enumerate(next_texts)],
        "alerts": alerts,
        "start": dates["start"], "end": dates["end"],
        "start_all": start["dates"], "end_all": end["dates"],
        "progress": progress["value"], "progress_raw": raw.get("progress", ""),
        "status_raw": raw.get("status", "").strip(), "status_norm": status_norm, "status_key": status_key,
        "warnings": warnings, "ambiguities": ambiguities,
    }


def parse_workbook(fileobj) -> dict:
    """Détecte les blocs (projets / tâches) de toutes les feuilles et lit leurs lignes."""
    try:
        workbook = load_workbook(fileobj, data_only=True)
    except Exception as exc:
        raise TrackingImportError("Fichier illisible : un classeur Excel (.xlsx) est attendu.") from exc
    sections, rows = [], []
    for ws in workbook.worksheets:
        if ws.max_row > MAX_ROWS:
            raise TrackingImportError(f"Feuille « {ws.title} » trop volumineuse ({ws.max_row} lignes).")
        headers = []
        for cells in ws.iter_rows():
            cols = _header_columns(cells)
            if cols:
                headers.append((cells[0].row, cols))
        for index, (header_row, cols) in enumerate(headers):
            last = headers[index + 1][0] - 1 if index + 1 < len(headers) else ws.max_row
            section = PROJECTS if key(ws.cell(row=header_row, column=cols["title"]).value).startswith("projet") else TASKS
            title = ""
            for r in range(header_row - 1, max(header_row - 4, 0), -1):
                value = ws.cell(row=r, column=1).value
                if isinstance(value, str) and value.strip() and not value.startswith("#"):
                    title = value.strip()
                    break
            found = []
            for r in range(header_row + 1, last + 1):
                values = {f: ws.cell(row=r, column=c).value for f, c in cols.items()}
                filled = [f for f, v in values.items() if v is not None and str(v).strip()]
                # Une ligne ne portant que la 1re colonne est un titre de bloc, pas une donnée.
                if not filled or filled == ["company"]:
                    continue
                found.append(_parse_row(ws, r, cols, section))
            sections.append({
                "kind": section, "sheet": ws.title, "title": title, "header_row": header_row,
                "first_row": found[0]["row"] if found else None, "last_row": found[-1]["row"] if found else None,
                "rows": len(found), "columns": sorted(cols, key=cols.get),
            })
            rows.extend(found)
    if not sections:
        raise TrackingImportError(
            "Aucun bloc « projets » ou « tâches » détecté : la ligne d'en-tête (ENTREPRISE, PROJET, "
            "PORTEUR, … STATUT) est introuvable.")
    return {"sections": sections, "rows": rows}


# ---------------------------------------------------------------------------
# Rapprochement avec l'existant
# ---------------------------------------------------------------------------
def _user_name(user) -> str:
    return user.get_full_name() or user.get_username()


def match_people(names, users) -> dict:
    """
    ``{clé: {"match": user|None, "candidates": [users]}}``. Rapprochement sûr =
    mêmes mots (ordre, casse et accents indifférents) et un seul utilisateur.
    """
    indexed = [(u, frozenset(key(_user_name(u)).split())) for u in users]
    out = {}
    for name in names:
        tokens = frozenset(key(name).split())
        exact = [u for u, t in indexed if t and t == tokens]
        candidates = [u for u, t in indexed if t and tokens and (
            t == tokens or len(t & tokens) >= 2 or (len(t & tokens) == 1 and (tokens <= t or t <= tokens)))]
        sure = exact[0] if len(exact) == 1 and len(tokens) >= 2 else None
        out[key(name)] = {"match": sure, "candidates": candidates[:5]}
    return out


def container_project(workspace):
    return (dm.Project.objects.filter(workspace=workspace, category__code=CONTAINER_CATEGORY)
            .order_by("is_archived", "id").first())


def _task_index(project_id) -> dict:
    """``{(parent_id, clé du titre): id}`` des tâches actives d'un projet."""
    index = {}
    for pk, parent_id, title in (dm.Task.objects.filter(project_id=project_id, is_archived=False)
                                 .values_list("id", "parent_id", "title")):
        index.setdefault((parent_id, key(title)), pk)
    return index


def _alert_match(project_id, task_id, item):
    k = key(_clip(item["text"], 180))
    if item["kind"] == "DECISION":
        qs = dm.MeetingDecision.objects.filter(projects__id=project_id, task_id=task_id, is_archived=False)
    else:
        qs = dm.Risk.objects.filter(project_id=project_id, task_id=task_id, is_archived=False)
    for pk, title in qs.values_list("id", "title"):
        if key(title)[: len(k)] == k or key(title) == k:
            return pk
    return None


def analyze(document_import) -> dict:
    """Analyse complète d'un fichier déjà téléversé (aucune écriture métier)."""
    workspace = document_import.workspace
    with document_import.file.open("rb") as handle:
        data = handle.read(MAX_FILE_BYTES + 1)
    if len(data) > MAX_FILE_BYTES:
        raise TrackingImportError("Fichier trop volumineux (10 Mo maximum).")
    parsed = parse_workbook(io.BytesIO(data))
    rows = parsed["rows"]

    projects = {key(name): (pk, name, archived) for pk, name, archived in
                dm.Project.objects.filter(workspace=workspace).values_list("id", "name", "is_archived")}
    container = container_project(workspace)
    task_indexes: dict[int, dict] = {}

    def tasks_of(project_id):
        if project_id not in task_indexes:
            task_indexes[project_id] = _task_index(project_id)
        return task_indexes[project_id]

    for row in rows:
        row["match"] = None
        parent_project = parent_task = None
        if not row["title"]:
            row["default"] = {"action": "skip", "target_id": None}
        elif row["section"] == PROJECTS:
            hit = projects.get(key(_clip(row["title"], 160)))
            if hit:
                row["match"] = {"id": hit[0], "name": hit[1], "archived": hit[2]}
                parent_project = hit[0]
            row["default"] = {"action": ("update" if hit[2] else "link") if hit else "create",
                              "target_id": hit[0] if hit else None}
        else:
            hit = tasks_of(container.pk).get((None, key(_clip(row["title"], 220)))) if container else None
            if hit:
                row["match"] = {"id": hit, "name": _clip(row["title"], 220), "archived": False}
                parent_project, parent_task = container.pk, hit
            row["default"] = {"action": "link" if hit else "create", "target_id": hit, "project_id": None}
        for item in row["next"]:
            hit = None
            if parent_project:
                hit = tasks_of(parent_project).get((parent_task, key(_clip(item["text"], 220))))
            item["match"] = {"id": hit} if hit else None
            item["default"] = {"action": "link" if hit else "create", "target_id": hit}
        for item in row["alerts"]:
            hit = _alert_match(parent_project, parent_task, item) if parent_project else None
            item["match"] = {"id": hit} if hit else None
            item["default"] = {"action": "link" if hit else "create", "target_id": hit,
                               "kind": item["kind"], "severity": item["severity"]}

    # Entreprises → étiquettes de type « entreprise »
    labels = {}
    for label in dm.Label.objects.filter(workspace=workspace).order_by("kind", "id"):
        labels.setdefault(key(label.name), label)
    companies: dict[str, dict] = {}
    for row in rows:
        for name in row["companies"]:
            entry = companies.setdefault(key(name), {"key": key(name), "name": name, "rows": [],
                                                     "ambiguous": " - " in name})
            entry["rows"].append(row["id"])
    for entry in companies.values():
        label = labels.get(entry["key"])
        entry["match"] = {"id": label.pk, "name": label.name, "kind": label.kind} if label else None
        entry["default"] = {"action": "link" if label else "create", "label_id": label.pk if label else None}

    # Personnes → utilisateurs existants (jamais de création de compte)
    people: dict[str, dict] = {}
    for row in rows:
        for role, names in (("PORTEUR", row["owners"]), ("INTERLOCUTEUR", row["contacts"])):
            for name in names:
                entry = people.setdefault(key(name), {"key": key(name), "name": name, "roles": [], "rows": []})
                if role not in entry["roles"]:
                    entry["roles"].append(role)
                if row["id"] not in entry["rows"]:
                    entry["rows"].append(row["id"])
    matches = match_people([p["name"] for p in people.values()], list(users_in_workspaces([workspace.pk])))
    for entry in people.values():
        found = matches[entry["key"]]
        user = found["match"]
        entry["match"] = {"id": user.pk, "name": _user_name(user)} if user else None
        entry["candidates"] = [{"id": u.pk, "name": _user_name(u)} for u in found["candidates"]]
        entry["unresolved"] = user is None and "PORTEUR" in entry["roles"]
        entry["default"] = {"user_id": user.pk if user else None}

    statuses: dict[str, dict] = {}
    for row in rows:
        if not row["status_norm"]:
            continue
        entry = statuses.setdefault(row["status_norm"], {
            "key": row["status_norm"], "raw": row["status_raw"], "known": row["status_key"], "rows": 0,
            "default": {"project": PROJECT_STATUS.get(row["status_key"]), "task": TASK_STATUS.get(row["status_key"])},
        })
        entry["rows"] += 1

    unresolved = [p["name"] for p in people.values() if p["unresolved"]]
    ambiguities = [a for row in rows for a in row.pop("ambiguities")]
    warnings = [w for row in rows for w in row["warnings"]]
    return {
        "kind": KIND, "version": 1,
        "analyzed_at": timezone.now().isoformat(),
        "sections": parsed["sections"], "rows": rows,
        "companies": list(companies.values()), "people": list(people.values()),
        "statuses": list(statuses.values()),
        "container": {"default": {
            "mode": "existing" if container else "create",
            "project_id": container.pk if container else None,
            "name": container.name if container else DEFAULT_CONTAINER,
        }},
        "ambiguities": ambiguities, "warnings": warnings,
        "stats": {
            "projects": sum(1 for r in rows if r["section"] == PROJECTS),
            "tasks": sum(1 for r in rows if r["section"] == TASKS),
            "actions_done": sum(len(r["done"]) for r in rows),
            "actions_next": sum(len(r["next"]) for r in rows),
            "alerts": sum(len(r["alerts"]) for r in rows),
            "companies": len(companies), "people": len(people),
            "unresolved_people": len(unresolved),
            "ambiguities": len(ambiguities), "warnings": len(warnings),
        },
        "unresolved_members": unresolved,
    }


def merge_decisions(analysis: dict, overrides: dict | None) -> dict:
    """Décisions par défaut de l'analyse, surchargées par celles de l'utilisateur."""
    overrides = overrides or {}

    def pick(group, ident, default):
        chosen = (overrides.get(group) or {}).get(ident)
        return {**default, **chosen} if isinstance(chosen, dict) else dict(default)

    ambiguities = {}
    for amb in analysis["ambiguities"]:
        value = (overrides.get("ambiguities") or {}).get(amb["id"], amb["default"])
        if value not in [option["value"] for option in amb["options"]]:
            raise TrackingImportError(f"Choix invalide pour « {amb['message']} ».")
        ambiguities[amb["id"]] = value
    container = {**analysis["container"]["default"], **(overrides.get("container") or {})}
    return {
        "companies": {c["key"]: pick("companies", c["key"], c["default"]) for c in analysis["companies"]},
        "people": {p["key"]: pick("people", p["key"], p["default"]) for p in analysis["people"]},
        "statuses": {s["key"]: pick("statuses", s["key"], s["default"]) for s in analysis["statuses"]},
        "rows": {r["id"]: pick("rows", r["id"], r["default"]) for r in analysis["rows"]},
        "items": {i["id"]: pick("items", i["id"], i["default"]) for r in analysis["rows"] for i in r["next"]},
        "alerts": {a["id"]: pick("alerts", a["id"], a["default"]) for r in analysis["rows"] for a in r["alerts"]},
        "ambiguities": ambiguities,
        "container": container,
        "done_as_tasks": bool(overrides.get("done_as_tasks", False)),
    }


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------
Action = dm.ProjectImportRecord.Action


def _source_key(*parts) -> str:
    return hashlib.sha1("|".join(str(p) for p in parts).encode("utf-8")).hexdigest()


class _Applier:
    def __init__(self, document_import, analysis, decisions, user):
        self.imp, self.ws, self.user = document_import, document_import.workspace, user
        self.analysis, self.dec = analysis, decisions
        self.records: list[dm.ProjectImportRecord] = []
        self.counts: dict[str, Counter] = {}
        self.assigned: Counter = Counter()
        self.users = {u.pk: u for u in users_in_workspaces([self.ws.pk])}
        self.people = {}
        for person in analysis["people"]:
            user_id = decisions["people"][person["key"]].get("user_id")
            if user_id and int(user_id) not in self.users:
                raise TrackingImportError(f"« {person['name']} » : utilisateur hors de l'espace de travail.")
            self.people[person["key"]] = self.users.get(int(user_id)) if user_id else None
        self.labels: dict[str, object] = {}
        self.task_indexes: dict[int, dict] = {}
        self._container = None
        self.meta = {"source": SOURCE, "import_id": document_import.pk}

    # -- utilitaires -------------------------------------------------------
    def rec(self, row, field, action, target=None, text="", index=0, previous=None, source_key=""):
        self.records.append(dm.ProjectImportRecord(
            document_import=self.imp, section=row["section"], row_number=row["row"], field=field,
            item_index=index, original_text=text, action=action,
            target_model=type(target).__name__ if target is not None else "",
            target_id=getattr(target, "pk", None), previous=previous or {}, source_key=source_key,
        ))
        self.counts.setdefault(field, Counter())[action.lower()] += 1

    def tasks_of(self, project_id):
        if project_id not in self.task_indexes:
            self.task_indexes[project_id] = _task_index(project_id)
        return self.task_indexes[project_id]

    def fail(self, row, message):
        raise TrackingImportError(f"Ligne {row['row']} ({row['sheet']}) : {message}")

    def values(self, row, kind):
        status = (self.dec["statuses"].get(row["status_norm"]) or {}).get(kind)
        choices = dm.Project.Status.values if kind == "project" else dm.Task.Status.values
        if status and status not in choices:
            self.fail(row, f"statut cible invalide « {status} ».")
        amb = self.dec["ambiguities"]
        return {
            "status": status or None,
            "progress": amb.get(f"{row['id']}:progress", row["progress"]),
            "start": amb.get(f"{row['id']}:start", row["start"]),
            "end": amb.get(f"{row['id']}:end", row["end"]),
        }

    def owners(self, row):
        return [u for u in (self.people.get(key(n)) for n in row["owners"]) if u]

    def container(self):
        if self._container is None:
            choice = self.dec["container"]
            if choice.get("mode") == "existing" and choice.get("project_id"):
                project = dm.Project.objects.filter(workspace=self.ws, pk=choice["project_id"]).first()
                if not project:
                    raise TrackingImportError("Projet d'accueil des activités introuvable dans cet espace.")
            else:
                name = _clip(choice.get("name") or DEFAULT_CONTAINER, 160)
                project = next((p for p in dm.Project.objects.filter(workspace=self.ws)
                                if key(p.name) == key(name)), None)
                if project is None:
                    category, _ = dm.ProjectCategory.objects.get_or_create(
                        code=CONTAINER_CATEGORY,
                        defaults={"name": "Activités courantes", "budget_type": "NONE", "affects_revenue": False},
                    )
                    project = dm.Project(
                        workspace=self.ws, name=name, category=category, owner=self.user,
                        status=dm.Project.Status.IN_PROGRESS,
                        description="Activités et tâches hors projet suivies par le pôle (import du suivi).",
                    )
                    project._skip_ai_trigger = True
                    project.save()
                    self.rec({"section": TASKS, "row": 0}, "container", Action.CREATED, project, project.name)
            if project.is_archived:
                dm.Project.objects.filter(pk=project.pk).update(is_archived=False, archived_at=None)
                self.rec({"section": TASKS, "row": 0}, "container", Action.UPDATED, project, project.name,
                         previous={"is_archived": True})
            self._container = project
        return self._container

    # -- lignes ------------------------------------------------------------
    def run(self):
        for company in self.analysis["companies"]:
            self.resolve_company(company)
        for row in self.analysis["rows"]:
            decision = self.dec["rows"][row["id"]]
            raw_text = json.dumps(row["raw"], ensure_ascii=False)
            field = "project" if row["section"] == PROJECTS else "task"
            if decision.get("action") == "skip" or not row["title"]:
                self.rec(row, field, Action.SKIPPED, text=raw_text)
                continue
            if row["section"] == PROJECTS:
                project, task = self.apply_project(row, decision, raw_text), None
            else:
                project, task = self.apply_task(row, decision, raw_text)
            self.apply_companies(row, project, task)
            self.apply_people(row, project, task)
            self.apply_done(row, project, task)
            self.apply_next(row, project, task)
            self.apply_alerts(row, project, task)
        dm.ProjectImportRecord.objects.bulk_create(self.records)

    def resolve_company(self, company):
        decision = self.dec["companies"][company["key"]]
        action = decision.get("action")
        label = None
        if action == "link":
            label = dm.Label.objects.filter(workspace=self.ws, pk=decision.get("label_id")).first()
            if not label:
                raise TrackingImportError(f"Entreprise « {company['name']} » : étiquette cible introuvable.")
        elif action == "create":
            label = next((l for l in dm.Label.objects.filter(workspace=self.ws)
                          if key(l.name) == company["key"]), None)
            if label is None:
                label = dm.Label.objects.create(workspace=self.ws, name=_clip(company["name"], 60),
                                                kind=dm.Label.Kind.COMPANY, color="#0EA5E9")
                self.rec({"section": "", "row": 0}, "company", Action.CREATED, label, company["name"])
        if label is not None and label.kind != dm.Label.Kind.COMPANY:
            previous = {"kind": label.kind}
            label.kind = dm.Label.Kind.COMPANY
            label.save(update_fields=["kind", "updated_at"])
            self.rec({"section": "", "row": 0}, "company", Action.UPDATED, label, company["name"], previous=previous)
        self.labels[company["key"]] = label

    def _update(self, row, field, obj, changes, raw_text):
        """Applique ``changes`` sur un objet existant en mémorisant les anciennes valeurs."""
        previous = {}
        for name, value in changes.items():
            old = getattr(obj, name)
            if value is not None and _text(old) != _text(value):
                previous[name] = old.isoformat() if isinstance(old, (date, datetime)) else old
                setattr(obj, name, date.fromisoformat(value) if name.endswith("_date") else value)
        if obj.is_archived:
            previous["is_archived"] = True
            obj.is_archived, obj.archived_at = False, None
        if previous:
            if field == "task":
                obj._skip_budget_refresh = True
            obj._skip_tracking_notification = True
            obj.save()
        self.rec(row, field, Action.UPDATED if previous else Action.LINKED, obj, raw_text, previous=previous)

    def apply_project(self, row, decision, raw_text):
        values, owners = self.values(row, "project"), self.owners(row)
        action = decision.get("action")
        project = None
        if action in ("update", "link"):
            project = dm.Project.objects.filter(workspace=self.ws, pk=decision.get("target_id")).first()
            if not project:
                self.fail(row, "projet à rattacher introuvable dans cet espace de travail.")
        elif action == "create":
            name = _clip(row["title"], 160)
            # Garde d'idempotence : le nom est unique par espace (archives comprises).
            project = next((p for p in dm.Project.objects.filter(workspace=self.ws) if key(p.name) == key(name)), None)
            if project is not None:
                action = "update" if project.is_archived else "link"
        else:
            self.fail(row, f"action inconnue « {action} ».")
        changes = {"status": values["status"], "progress_percent": values["progress"],
                   "start_date": values["start"], "target_date": values["end"]}
        if project is None:
            project = dm.Project(
                workspace=self.ws, name=_clip(row["title"], 160), owner=owners[0] if owners else None,
                status=values["status"] or dm.Project.Status.PLANNED, progress_percent=values["progress"] or 0,
                start_date=date.fromisoformat(values["start"]) if values["start"] else None,
                target_date=date.fromisoformat(values["end"]) if values["end"] else None,
                description=row["raw"].get("title", "").strip() if len(row["title"]) > 160 else "",
            )
            project._skip_ai_trigger = True  # pas de génération IA automatique à l'import
            project.save()
            self.rec(row, "project", Action.CREATED, project, raw_text)
        elif action == "update":
            if project.owner_id is None and owners:
                changes["owner_id"] = owners[0].pk
            self._update(row, "project", project, changes, raw_text)
        else:
            self.rec(row, "project", Action.LINKED, project, raw_text)
        return project

    def apply_task(self, row, decision, raw_text):
        values, owners = self.values(row, "task"), self.owners(row)
        action = decision.get("action")
        task = None
        if action in ("update", "link"):
            task = (dm.Task.objects.select_related("project")
                    .filter(workspace=self.ws, pk=decision.get("target_id")).first())
            if not task:
                self.fail(row, "tâche à rattacher introuvable dans cet espace de travail.")
            project = task.project
        elif action == "create":
            if decision.get("project_id"):
                project = dm.Project.objects.filter(workspace=self.ws, pk=decision["project_id"],
                                                    is_archived=False).first()
                if not project:
                    self.fail(row, "projet de rattachement introuvable dans cet espace de travail.")
            else:
                project = self.container()
            existing = self.tasks_of(project.pk).get((None, key(_clip(row["title"], 220))))
            if existing:
                task, action = dm.Task.objects.get(pk=existing), "link"
        else:
            self.fail(row, f"action inconnue « {action} ».")
        if task is None:
            task = self.create_task(
                project, _clip(row["title"], 220),
                description=row["raw"].get("title", "").strip() if row["title_multiline"] or len(row["title"]) > 220 else "",
                status=values["status"] or dm.Task.Status.TODO, progress=values["progress"] or 0,
                start=values["start"], due=values["end"], owners=owners,
            )
            self.rec(row, "task", Action.CREATED, task, raw_text)
        elif action == "update":
            self._update(row, "task", task, {
                "status": values["status"], "progress_percent": values["progress"],
                "start_date": values["start"], "due_date": values["end"]}, raw_text)
        else:
            self.rec(row, "task", Action.LINKED, task, raw_text)
        return project, task

    def create_task(self, project, title, *, description="", status, progress=0, start=None, due=None,
                    owners=(), parent=None):
        task = dm.Task(
            workspace=self.ws, project=project, parent=parent, title=title, description=description,
            status=status, progress_percent=progress, reporter=self.user,
            start_date=date.fromisoformat(start) if start else None,
            due_date=date.fromisoformat(due) if due else None,
        )
        task._skip_budget_refresh = True
        task.save()
        if owners:
            # Même état que Task.assign() (assignee + TaskAssignment) mais sans un
            # e-mail par tâche : les porteurs reçoivent une seule notification de synthèse.
            dm.Task.objects.filter(pk=task.pk).update(assignee=owners[0])
            task.assignee = owners[0]
            dm.TaskAssignment.objects.bulk_create(
                [dm.TaskAssignment(task=task, user=u, assigned_by=self.user) for u in owners])
            for owner in owners:
                self.assigned[owner.pk] += 1
        self.tasks_of(project.pk)[(parent.pk if parent else None, key(title))] = task.pk
        return task

    # -- éléments rattachés --------------------------------------------------
    def apply_companies(self, row, project, task):
        for name in row["companies"]:
            label = self.labels.get(key(name))
            if label is None:
                self.rec(row, "company", Action.SKIPPED, text=name)
                continue
            if task is not None:
                link, created = dm.TaskLabel.objects.get_or_create(task=task, label=label,
                                                                   defaults={"added_by": self.user})
            else:
                link, created = dm.ProjectLabel.objects.get_or_create(project=project, label=label)
            self.rec(row, "company", Action.CREATED if created else Action.LINKED, link, name)

    def apply_people(self, row, project, task):
        for index, name in enumerate(row["owners"]):
            user = self.people.get(key(name))
            if user is None:
                self.stakeholder(row, project, task, "PORTEUR", name, None, index)
            elif task is None:
                member, created = dm.ProjectMember.objects.get_or_create(
                    project=project, user=user, defaults={"role": "Porteur", "is_primary": index == 0})
                self.rec(row, "member", Action.CREATED if created else Action.LINKED, member, name, index)
                if created:
                    self.assigned[user.pk] += 1
            else:
                link, created = dm.TaskAssignment.objects.get_or_create(
                    task=task, user=user, defaults={"assigned_by": self.user})
                self.rec(row, "member", Action.CREATED if created else Action.LINKED, link, name, index)
        for index, name in enumerate(row["contacts"]):
            self.stakeholder(row, project, task, "INTERLOCUTEUR", name, self.people.get(key(name)), index)

    def stakeholder(self, row, project, task, role, name, user, index):
        existing = dm.ProjectStakeholder.objects.filter(project=project, task=task, role=role,
                                                        name_key=key(name)).first()
        if existing:
            self.rec(row, "stakeholder", Action.LINKED, existing, name, index)
            return
        item = dm.ProjectStakeholder.objects.create(
            workspace=self.ws, project=project, task=task, role=role, name=_clip(name, 160),
            name_key=key(name)[:160], user=user)
        self.rec(row, "stakeholder", Action.CREATED, item, name, index)

    def apply_done(self, row, project, task):
        for index, item in enumerate(row["done"]):
            sk = _source_key(self.ws.pk, project.pk, task.pk if task else "", "done", key(item["text"]))
            known = dm.ProjectImportRecord.objects.filter(
                source_key=sk, action=Action.CREATED, rolled_back_at__isnull=True,
                document_import__workspace=self.ws).values_list("target_id", flat=True)
            existing = dm.ActivityLog.objects.filter(pk__in=list(known)).first()
            if existing:
                self.rec(row, "action_done", Action.LINKED, existing, item["text"], index, source_key=sk)
                continue
            log = dm.ActivityLog.objects.create(
                workspace=self.ws, actor=self.user, project=project, task=task,
                activity_type=dm.ActivityLog.ActivityType.PROJECT_UPDATED,
                title=_clip(item["text"], 200), description=item["text"],
                metadata={**self.meta, "kind": "action_done", "sheet": row["sheet"], "row": row["row"]},
            )
            self.rec(row, "action_done", Action.CREATED, log, item["text"], index, source_key=sk)
            if self.dec["done_as_tasks"]:
                title = _clip(item["text"], 220)
                if (task.pk if task else None, key(title)) not in self.tasks_of(project.pk):
                    done = self.create_task(project, title, status=dm.Task.Status.DONE, progress=100, parent=task)
                    self.rec(row, "action_done_task", Action.CREATED, done, item["text"], index)

    def apply_next(self, row, project, task):
        owners = self.owners(row)
        for index, item in enumerate(row["next"]):
            decision = self.dec["items"][item["id"]]
            action = decision.get("action")
            if action == "skip":
                self.rec(row, "action_next", Action.SKIPPED, text=item["text"], index=index)
                continue
            if action == "link":
                target = dm.Task.objects.filter(workspace=self.ws, pk=decision.get("target_id")).first()
                if not target:
                    self.fail(row, f"tâche à rattacher introuvable pour « {_clip(item['text'], 60)} ».")
                self.rec(row, "action_next", Action.LINKED, target, item["text"], index)
                continue
            title = _clip(item["text"], 220)
            existing = self.tasks_of(project.pk).get((task.pk if task else None, key(title)))
            if existing:
                self.rec(row, "action_next", Action.LINKED, dm.Task(pk=existing), item["text"], index)
                continue
            created = self.create_task(
                project, title, description=item["text"] if len(item["text"]) > 220 else "",
                status=dm.Task.Status.TODO, start=item["start"], due=item["due"],
                owners=owners if len(owners) == 1 else (), parent=task,
            )
            self.rec(row, "action_next", Action.CREATED, created, item["text"], index)

    def apply_alerts(self, row, project, task):
        owners = self.owners(row)
        for index, item in enumerate(row["alerts"]):
            decision = self.dec["alerts"][item["id"]]
            action, kind = decision.get("action"), decision.get("kind") or item["kind"]
            severity = decision.get("severity") or item["severity"]
            if action == "skip":
                self.rec(row, "alert", Action.SKIPPED, text=item["text"], index=index)
                continue
            if kind not in ALERT_KINDS or severity not in dm.Risk.Severity.values:
                self.fail(row, "type ou niveau d'alerte invalide.")
            hit = _alert_match(project.pk, task.pk if task else None, {**item, "kind": kind})
            if hit:
                model = dm.MeetingDecision if kind == "DECISION" else dm.Risk
                self.rec(row, "alert", Action.LINKED, model(pk=hit), item["text"], index)
                continue
            if kind == "DECISION":
                target = dm.MeetingDecision(
                    workspace=self.ws, task=task, title=_clip(item["text"], 250), description=item["text"],
                    status=dm.MeetingDecision.Status.PENDING,
                    impact_summary=f"Importé du suivi ({row['sheet']}, ligne {row['row']}).",
                )
                target._skip_tracking_notification = True  # un seul récapitulatif par porteur en fin d'import
                target.save()
                target.projects.add(project)
            else:
                target = dm.Risk(
                    workspace=self.ws, project=project, task=task, title=_clip(item["text"], 180),
                    description=item["text"], severity=severity, category=kind,
                    owner=owners[0] if owners else None,
                )
                target._skip_tracking_notification = True
                target.save()
            self.rec(row, "alert", Action.CREATED, target, item["text"], index)


def apply_import(document_import, overrides, user) -> dict:
    """Applique un import analysé. Tout ou rien : une décision invalide annule l'ensemble."""
    payload = document_import.ai_payload or {}
    analysis = payload.get("analysis")
    if payload.get("kind") != KIND or not analysis:
        raise TrackingImportError("Cet import n'a pas été analysé.")
    if payload.get("applied_at") and not payload.get("rolled_back_at"):
        raise TrackingImportError("Cet import a déjà été appliqué : annulez-le avant de le rejouer.")
    decisions = merge_decisions(analysis, overrides)
    with transaction.atomic():
        applier = _Applier(document_import, analysis, decisions, user)
        applier.run()
        kept = [a["message"] for a in analysis["ambiguities"]
                if decisions["ambiguities"][a["id"]] == a["default"]]
        report = {
            "counts": {field: dict(counter) for field, counter in applier.counts.items()},
            "unresolved_members": [p["name"] for p in analysis["people"]
                                   if "PORTEUR" in p["roles"] and applier.people.get(p["key"]) is None],
            "ambiguities_kept": kept,
            "warnings": len(analysis["warnings"]),
            "records": len(applier.records),
        }
        payload.update({
            "decisions": decisions, "report": report,
            "applied_at": timezone.now().isoformat(),
            "applied_by": {"id": user.pk, "name": _user_name(user)},
            "rolled_back_at": None, "rolled_back_by": None,
        })
        document_import.ai_payload = payload
        document_import.status = dm.ProjectDocumentImport.ImportStatus.COMPLETED
        document_import.error_message = ""
        document_import.save(update_fields=["ai_payload", "status", "error_message", "updated_at"])
        for user_id, count in applier.assigned.items():
            if user_id != user.pk:
                dm.Notification.objects.create(
                    recipient=applier.users[user_id], workspace=applier.ws,
                    notification_type=dm.Notification.NotificationType.PROJECT,
                    title="Suivi Pôle Développement : éléments attribués",
                    body=f"{count} projet(s) ou tâche(s) vous ont été attribués lors de l'import du suivi.",
                    url="/pilotage/suivi", metadata={**applier.meta, "kind": "import_assignment"},
                )
    return report


_ARCHIVABLE = {"Project": dm.Project, "Task": dm.Task, "Risk": dm.Risk, "MeetingDecision": dm.MeetingDecision}
_DELETABLE = {
    "ActivityLog": dm.ActivityLog, "ProjectStakeholder": dm.ProjectStakeholder, "ProjectLabel": dm.ProjectLabel,
    "TaskLabel": dm.TaskLabel, "ProjectMember": dm.ProjectMember, "TaskAssignment": dm.TaskAssignment,
}
_UPDATABLE = {"Project": dm.Project, "Task": dm.Task, "Label": dm.Label}


def rollback_import(document_import, user) -> dict:
    """
    Annulation logique : les objets créés par l'import sont archivés (projets,
    tâches, risques, décisions) ou retirés (liens, historique importé), les
    objets mis à jour retrouvent leurs anciennes valeurs.
    """
    payload = document_import.ai_payload or {}
    if not payload.get("applied_at") or payload.get("rolled_back_at"):
        raise TrackingImportError("Aucun import appliqué à annuler.")
    now = timezone.now()
    summary: Counter = Counter()
    with transaction.atomic():
        records = list(document_import.records.filter(rolled_back_at__isnull=True).order_by("-id"))
        labels = []
        for record in records:
            if record.action == Action.CREATED and record.target_id:
                if record.target_model in _ARCHIVABLE:
                    summary["archived"] += _ARCHIVABLE[record.target_model].objects.filter(
                        pk=record.target_id, is_archived=False).update(is_archived=True, archived_at=now)
                elif record.target_model in _DELETABLE:
                    deleted, _ = _DELETABLE[record.target_model].objects.filter(pk=record.target_id).delete()
                    summary["removed"] += 1 if deleted else 0
                elif record.target_model == "Label":
                    labels.append(record.target_id)
            elif record.action == Action.UPDATED and record.target_id and record.previous:
                model = _UPDATABLE.get(record.target_model)
                if model:
                    values = dict(record.previous)
                    if values.get("is_archived"):
                        values["archived_at"] = now
                    summary["restored"] += model.objects.filter(pk=record.target_id).update(**values)
        for label_id in labels:  # une entreprise créée n'est retirée que si plus rien ne l'utilise
            label = dm.Label.objects.filter(pk=label_id).first()
            if label and not label.project_labels.exists() and not label.task_labels.exists():
                label.delete()
                summary["removed"] += 1
        document_import.records.filter(rolled_back_at__isnull=True).update(rolled_back_at=now)
        payload.update({"rolled_back_at": now.isoformat(), "rolled_back_by": {"id": user.pk, "name": _user_name(user)},
                        "rollback": dict(summary)})
        document_import.ai_payload = payload
        document_import.status = dm.ProjectDocumentImport.ImportStatus.UPLOADED
        document_import.save(update_fields=["ai_payload", "status", "updated_at"])
    return dict(summary)
