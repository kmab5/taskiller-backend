from drf_spectacular.extensions import OpenApiAuthenticationExtension


class TaskillerBearerScheme(OpenApiAuthenticationExtension):
    target_class = "taskiller.django_api.authentication.TaskillerBearerAuthentication"
    name = "bearerAuth"

    def get_security_definition(self, auto_schema: object) -> dict[str, str]:
        del auto_schema
        return {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT",
        }
