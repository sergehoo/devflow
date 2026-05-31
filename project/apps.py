from django.apps import AppConfig



class ProjectConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "project"

    def ready(self):
        import project.signals  # noqa
        # PR24 — Active les signaux d'audit sécurité
        import project.services.security_audit  # noqa