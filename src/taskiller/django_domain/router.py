class ExistingTaskillerSchemaRouter:
    """Prevent Django migrations from ever altering Alembic-owned Taskiller tables."""

    app_label = "django_domain"

    def allow_migrate(
        self,
        db: str,
        app_label: str,
        model_name: str | None = None,
        **hints: object,
    ) -> bool | None:
        del db, model_name, hints
        if app_label == self.app_label:
            return False
        return None
