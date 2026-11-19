from .action_views import urlpatterns as action_patterns
from .auth_views import urlpatterns as auth_patterns
from .read_views import urlpatterns as read_patterns

urlpatterns = [*auth_patterns, *read_patterns, *action_patterns]
