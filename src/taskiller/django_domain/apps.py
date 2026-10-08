from django.apps import AppConfig


class TaskillerDomainConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "taskiller.django_domain"
    label = "django_domain"
    verbose_name = "Taskiller data (read-only bridge)"

    def ready(self) -> None:
        # Register drf-spectacular's custom bearer security scheme.
        from taskiller.django_api import schema  # noqa: F401
