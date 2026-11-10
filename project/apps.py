from django.apps import AppConfig



class ProjectConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "project"

    def ready(self):
        import project.signals  # noqa
        # SECURITY : RBAC sur toutes les vues de facturation (lecture billing.view, écriture invoice.edit).
        from project.services.billing_permissions import apply_guards
        apply_guards()
        # PR24 — Active les signaux d'audit sécurité
        import project.services.security_audit  # noqa