"""
DevFlow — Crée la facture détaillée pour le module de gestion des
Timesheets Portuaires (Odoo + SI Portuaire), total 80 000 000 FCFA.

Usage :
    docker compose exec web python manage.py seed_invoice_port_80m \\
        --workspace-id 1 \\
        [--client-id 12] \\
        [--project-id 7] \\
        [--user-id 1] \\
        [--issue] \\
        [--currency XAF]

Si --workspace-id n'est pas fourni, on prend le premier workspace
auquel l'utilisateur --user-id (ou superuser par défaut) a accès.

La facture est créée en DRAFT par défaut ; --issue la passe en ISSUED
(génère le numéro FAC-AAAA-NNNN).

Total HT  = 80 000 000 FCFA
TVA       = 0 % (configurable via --tax-rate)
Total TTC = 80 000 000 FCFA
"""

from __future__ import annotations

from decimal import Decimal
from datetime import date, timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction


# ════════════════════════════════════════════════════════════════════
# DÉFINITION DES 11 LIGNES (= 80 000 000 FCFA)
# ════════════════════════════════════════════════════════════════════
LINES = [
    {
        "label": "Étude détaillée, cadrage et spécifications fonctionnelles",
        "description": (
            "Réalisation des ateliers métiers avec les parties prenantes, analyse "
            "approfondie des processus opérationnels, recueil et formalisation des "
            "besoins, rédaction des spécifications fonctionnelles détaillées, "
            "modélisation des processus (workflows), définition des règles de "
            "gestion, validation du périmètre fonctionnel et élaboration du "
            "planning détaillé du projet."
        ),
        "unit_price": Decimal("2000000"),
    },
    {
        "label": "Conception technique et architecture Odoo",
        "description": (
            "Conception de l'architecture technique de la solution basée sur Odoo, "
            "définition du modèle de données, structuration des modules, conception "
            "des workflows métier, architecture des interfaces, sécurité, gestion "
            "des droits, interfaçage avec le SI portuaire, choix des composants "
            "techniques, préparation des environnements de développement, test et "
            "production."
        ),
        "unit_price": Decimal("3000000"),
    },
    {
        "label": "Développement de programmation cale & équipe Cale",
        "description": (
            "Développement du module métier permettant la gestion des cales et des "
            "équipes de manutention. Cette prestation comprend la création des "
            "modèles de données, l'affectation des équipes aux cales, la planification "
            "des shifts, le suivi des responsables, la gestion des ressources "
            "mobilisées, le calcul des performances par cale ainsi que les contrôles "
            "de cohérence et les workflows associés."
        ),
        "unit_price": Decimal("8000000"),
    },
    {
        "label": "Module Gestion des Timesheets",
        "description": (
            "Développement du module central de gestion des feuilles de temps "
            "portuaires permettant la création, la saisie, la modification, le suivi "
            "et la validation des Timesheets. Le module prend en charge les "
            "informations relatives aux navires, escales, shifts, équipes, cales, "
            "grues, tonnage traité, nombre de dockers, unités manutentionnées, "
            "calcul automatique des durées, états d'avancement, historique des "
            "modifications et workflow complet de validation."
        ),
        "unit_price": Decimal("12000000"),
    },
    {
        "label": "Module Gestion des Temps perdus",
        "description": (
            "Développement du module dédié à l'enregistrement, la qualification, la "
            "catégorisation et l'analyse des temps perdus impactant les opérations "
            "de manutention. Il permet l'identification des causes (techniques, "
            "opérationnelles, administratives, environnementales ou sécuritaires), "
            "le calcul automatique des durées d'arrêt, le rattachement aux équipes, "
            "grues ou cales concernées, ainsi que la production d'indicateurs "
            "statistiques et d'analyses destinés au pilotage de la performance "
            "opérationnelle."
        ),
        "unit_price": Decimal("4000000"),
    },
    {
        "label": "Workflow de validation multi-niveaux",
        "description": (
            "Développement et paramétrage du processus de validation des Timesheets "
            "selon une chaîne hiérarchique configurable. Cette prestation comprend "
            "la définition des différents statuts (Brouillon, Soumis, Validé, "
            "Rejeté, Clôturé), la gestion des droits par profil, les notifications "
            "automatiques, la traçabilité des actions, les commentaires de "
            "validation, les demandes de correction, les historiques de validation "
            "ainsi que les règles de contrôle garantissant la fiabilité des données "
            "avant leur exploitation."
        ),
        "unit_price": Decimal("7000000"),
    },
    {
        "label": "Reporting avancé & KPI décisionnels",
        "description": (
            "Conception et développement d'un système complet de reporting "
            "décisionnel permettant la génération de tableaux de bord interactifs, "
            "d'indicateurs de performance (KPI), de graphiques dynamiques, de "
            "tableaux croisés, de statistiques consolidées et de rapports "
            "analytiques. Cette prestation comprend également les filtres "
            "multicritères, les exports PDF et Excel, les indicateurs de "
            "productivité, le suivi des temps perdus, les analyses par navire, "
            "escale, cale, équipe et grue ainsi que les tableaux de bord destinés "
            "au pilotage stratégique de la Direction."
        ),
        "unit_price": Decimal("5000000"),
    },
    {
        "label": "Intégration API avec le SI Portuaire",
        "description": (
            "Développement du connecteur sécurisé entre le module Odoo et le "
            "Système d'Information Portuaire (SI Portuaire). Cette prestation "
            "comprend l'analyse des interfaces existantes, le développement des "
            "services d'intégration REST, l'authentification sécurisée, la "
            "synchronisation automatique des données (navires, escales, postes à "
            "quai, horaires, statuts, mouvements), la gestion des erreurs, la "
            "journalisation des échanges, les mécanismes de reprise automatique "
            "ainsi que les tests d'interopérabilité avec le système tiers."
        ),
        "unit_price": Decimal("4000000"),
    },
    {
        "label": "Formation des utilisateurs",
        "description": (
            "Organisation et animation des sessions de formation destinées aux "
            "différentes catégories d'utilisateurs (administrateurs, superviseurs, "
            "agents de saisie, chefs d'équipe et direction). Cette prestation "
            "comprend la préparation des supports pédagogiques, les démonstrations "
            "pratiques, les exercices sur cas réels, le transfert de compétences, "
            "les sessions de questions-réponses, l'assistance au démarrage ainsi "
            "que l'évaluation des acquis afin de garantir une prise en main "
            "efficace de la solution."
        ),
        "unit_price": Decimal("2000000"),
    },
    {
        "label": "Documentation complète et guide d'utilisation",
        "description": (
            "Élaboration de l'ensemble de la documentation fonctionnelle et "
            "technique du projet. Cette prestation comprend la rédaction du guide "
            "utilisateur, du guide administrateur, du guide d'installation et de "
            "déploiement, de la documentation technique du module, des procédures "
            "d'exploitation, des guides de maintenance, des procédures de "
            "sauvegarde et restauration, des manuels de configuration ainsi que de "
            "toute la documentation nécessaire à l'exploitation et à la "
            "pérennisation de la solution."
        ),
        "unit_price": Decimal("1500000"),
    },
    {
        "label": "Tests, recette, assurance qualité & sécurité",
        "description": (
            "Réalisation de l'ensemble des activités de validation garantissant la "
            "conformité, la qualité et la sécurité de la solution. Cette prestation "
            "comprend les tests unitaires, les tests d'intégration, les tests "
            "fonctionnels, les tests de performance, les tests de sécurité, les "
            "contrôles des droits d'accès, les tests de charge, la correction des "
            "anomalies détectées, l'accompagnement à la recette utilisateur (UAT), "
            "la production des rapports de tests, la validation finale de la "
            "solution ainsi que la préparation de la mise en production "
            "conformément aux bonnes pratiques qualité et cybersécurité."
        ),
        # Delta calculé pour atteindre exactement 80 000 000 FCFA HT :
        #   80 000 000 - (2 + 3 + 8 + 12 + 4 + 7 + 5 + 4 + 2 + 1.5) M
        # = 80 000 000 - 48 500 000 = 31 500 000 FCFA
        "unit_price": Decimal("31500000"),
    },
]


class Command(BaseCommand):
    help = "Crée la facture détaillée Timesheets Portuaires (total 80 M FCFA)."

    def add_arguments(self, parser):
        parser.add_argument("--workspace-id", type=int, default=None,
                            help="ID du workspace cible (sinon : premier accessible)")
        parser.add_argument("--client-id", type=int, default=None,
                            help="ID du client de facturation (optionnel)")
        parser.add_argument("--client-name", type=str, default=None,
                            help="Nom du client à créer si --client-id absent")
        parser.add_argument("--project-id", type=int, default=None,
                            help="ID du projet (optionnel — facture libre sinon)")
        parser.add_argument("--user-id", type=int, default=None,
                            help="ID de l'utilisateur émetteur (sinon premier superuser)")
        parser.add_argument("--currency", type=str, default="XAF",
                            help="Devise (default XAF — FCFA Afrique Centrale)")
        parser.add_argument("--tax-rate", type=str, default="0",
                            help="Taux de TVA en %% (default 0)")
        parser.add_argument("--title", type=str,
                            default="Solution Timesheets Portuaires — Odoo & SI Portuaire",
                            help="Titre/objet de la facture")
        parser.add_argument("--issue", action="store_true",
                            help="Émettre immédiatement (DRAFT → ISSUED)")
        parser.add_argument("--due-days", type=int, default=30,
                            help="Délai de paiement en jours (default 30)")

    def handle(self, *args, **opts):
        from django.contrib.auth import get_user_model
        from project import models as dm
        from project.utils.workspaces import get_user_workspace_ids

        User = get_user_model()

        # ─── 1. Utilisateur émetteur ──────────────────────────────
        user = None
        if opts["user_id"]:
            user = User.objects.filter(pk=opts["user_id"]).first()
            if not user:
                raise CommandError(f"Utilisateur #{opts['user_id']} introuvable.")
        else:
            user = User.objects.filter(is_superuser=True).order_by("id").first()
            if not user:
                user = User.objects.filter(is_active=True).order_by("id").first()
        if not user:
            raise CommandError("Aucun utilisateur disponible.")
        self.stdout.write(f"[i] Émetteur : {user.username} (#{user.pk})")

        # ─── 2. Workspace cible ───────────────────────────────────
        ws = None
        if opts["workspace_id"]:
            ws = dm.Workspace.objects.filter(pk=opts["workspace_id"]).first()
            if not ws:
                raise CommandError(
                    f"Workspace #{opts['workspace_id']} introuvable."
                )
        else:
            ws_ids = list(get_user_workspace_ids(user))
            if not ws_ids:
                raise CommandError(
                    f"Aucun workspace accessible pour {user.username}."
                )
            ws = dm.Workspace.objects.filter(pk__in=ws_ids).order_by("id").first()
        self.stdout.write(f"[i] Workspace : {ws.name} (#{ws.pk})")

        # ─── 3. Client de facturation (optionnel) ─────────────────
        client = None
        if opts["client_id"]:
            client = dm.InvoiceClient.objects.filter(
                pk=opts["client_id"], workspace=ws,
            ).first()
            if not client:
                raise CommandError(
                    f"InvoiceClient #{opts['client_id']} introuvable "
                    f"dans le workspace {ws.name}."
                )
        elif opts["client_name"]:
            client, created = dm.InvoiceClient.objects.get_or_create(
                workspace=ws, name=opts["client_name"][:180],
            )
            self.stdout.write(
                f"[i] Client {'créé' if created else 'existant'} : "
                f"{client.name} (#{client.pk})"
            )
        if client:
            self.stdout.write(f"[i] Destinataire : {client.name} (#{client.pk})")
        else:
            self.stdout.write("[i] Destinataire : (aucun client renseigné)")

        # ─── 4. Projet (optionnel) ────────────────────────────────
        project = None
        if opts["project_id"]:
            project = dm.Project.objects.filter(
                pk=opts["project_id"], workspace=ws,
            ).first()
            if not project:
                raise CommandError(
                    f"Projet #{opts['project_id']} introuvable "
                    f"dans le workspace {ws.name}."
                )
            self.stdout.write(f"[i] Projet : {project.name} (#{project.pk})")
        else:
            self.stdout.write("[i] Projet : (facture libre, hors projet)")

        # ─── 5. Création atomique ─────────────────────────────────
        try:
            tax_rate = Decimal(opts["tax_rate"])
        except Exception:
            raise CommandError(f"--tax-rate invalide : {opts['tax_rate']}")

        issue_date = date.today()
        due_date = issue_date + timedelta(days=int(opts["due_days"]))

        with transaction.atomic():
            invoice = dm.Invoice.objects.create(
                workspace=ws,
                project=project,
                client=client,
                title=opts["title"][:200],
                notes=(
                    "Solution complète pour la gestion des Timesheets Portuaires :\n"
                    "module Odoo dédié + intégration au SI Portuaire.\n\n"
                    "Réglement par virement bancaire sous "
                    f"{opts['due_days']} jours à compter de la date d'émission.\n"
                    "Toute facture impayée donnera lieu à des pénalités de retard "
                    "selon les CGV en vigueur."
                ),
                currency=opts["currency"][:10],
                tax_rate=tax_rate,
                issue_date=issue_date,
                due_date=due_date,
                billing_mode=dm.Invoice.BillingMode.FIXED,
                status=dm.Invoice.Status.DRAFT,
                issued_by=user,
            )
            self.stdout.write(
                f"[+] Facture DRAFT créée : #{invoice.pk}"
            )

            # Lignes
            total_ht = Decimal("0")
            for pos, raw in enumerate(LINES, start=1):
                line = dm.InvoiceLine.objects.create(
                    invoice=invoice,
                    line_type=dm.InvoiceLine.LineType.SERVICE,
                    label=raw["label"][:240],
                    description=raw["description"][:5000],
                    quantity=Decimal("1"),
                    unit_price=raw["unit_price"],
                    position=pos,
                )
                total_ht += line.total_amount
                self.stdout.write(
                    f"    {pos:2d}. {raw['label'][:60]:<60s} "
                    f"{raw['unit_price']:>15,.0f} {opts['currency']}"
                    .replace(",", " ")
                )

            invoice.recompute_totals(save=True)
            invoice.refresh_from_db()

        # ─── 6. Validation total ─────────────────────────────────
        expected = Decimal("80000000")
        if invoice.subtotal_ht != expected:
            self.stdout.write(self.style.WARNING(
                f"[!] Sous-total HT = {invoice.subtotal_ht} ; "
                f"attendu = {expected}"
            ))
        else:
            self.stdout.write(self.style.SUCCESS(
                f"[OK] Sous-total HT = {invoice.subtotal_ht} {invoice.currency} "
                f"(80 millions exactement)."
            ))

        self.stdout.write("")
        self.stdout.write("─" * 70)
        self.stdout.write(
            f"  Sous-total HT  : {invoice.subtotal_ht:>20,.2f} {invoice.currency}"
            .replace(",", " ")
        )
        self.stdout.write(
            f"  TVA ({invoice.tax_rate:>5}%)   : {invoice.tax_amount:>20,.2f} "
            f"{invoice.currency}".replace(",", " ")
        )
        self.stdout.write(
            f"  Total TTC      : {invoice.total_ttc:>20,.2f} {invoice.currency}"
            .replace(",", " ")
        )
        self.stdout.write("─" * 70)

        # ─── 7. Émission éventuelle ──────────────────────────────
        if opts["issue"]:
            invoice.status = dm.Invoice.Status.ISSUED
            invoice.number = invoice.number or dm.Invoice.generate_number(ws)
            invoice.save(update_fields=["status", "number", "updated_at"])
            self.stdout.write(self.style.SUCCESS(
                f"[OK] Facture émise sous le numéro {invoice.number}."
            ))
        else:
            self.stdout.write(
                f"[i] Facture en DRAFT (utiliser --issue pour l'émettre)."
            )

        # ─── 8. URL de consultation ──────────────────────────────
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(
            f"[OK] Facture #{invoice.pk} prête. Consulte : "
            f"/billing/invoices/{invoice.pk}/"
        ))
