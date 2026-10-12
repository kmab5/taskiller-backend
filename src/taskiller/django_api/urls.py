from django.urls import path

from taskiller.django_api import analytics_views, execution_views, focus_views, portable_views, views, work_views

urlpatterns = [
    path("api/v1/auth/register", views.RegisterView.as_view()),
    path("api/v1/auth/login", views.LoginView.as_view()),
    path("api/v1/auth/refresh", views.RefreshView.as_view()),
    path("api/v1/auth/logout", views.LogoutView.as_view()),
    path("api/v1/auth/logout-all", views.LogoutAllView.as_view()),
    path("api/v1/auth/sessions", views.SessionsView.as_view()),
    path(
        "api/v1/auth/sessions/<uuid:sessionId>",
        views.SessionDetailView.as_view(),
    ),
    path(
        "api/v1/auth/email-verification/request",
        views.RequestEmailVerificationView.as_view(),
    ),
    path(
        "api/v1/auth/email-verification/confirm",
        views.ConfirmEmailVerificationView.as_view(),
    ),
    path(
        "api/v1/auth/password-reset/request",
        views.RequestPasswordResetView.as_view(),
    ),
    path(
        "api/v1/auth/password-reset/confirm",
        views.ConfirmPasswordResetView.as_view(),
    ),
    path("api/v1/me", views.MeView.as_view()),
    path("api/v1/me/preferences", views.PreferencesView.as_view()),
    path(
        "api/v1/me/export-requests",
        views.ExportRequestCreateView.as_view(),
    ),
    path(
        "api/v1/me/export-requests/<uuid:exportRequestId>",
        views.ExportRequestDetailView.as_view(),
    ),
    path(
        "api/v1/exports/<uuid:exportRequestId>/download",
        views.ExportDownloadView.as_view(),
    ),
    path("api/v1/portable-work/import", portable_views.PortableImportView.as_view()),
    path("api/v1/work-types", work_views.WorkTypesView.as_view()),
    path(
        "api/v1/work-types/<uuid:workTypeId>",
        work_views.WorkTypeDetailView.as_view(),
    ),
    path("api/v1/work-items", work_views.WorkItemsView.as_view()),
    path(
        "api/v1/work-items/<uuid:workItemId>",
        work_views.WorkItemDetailView.as_view(),
    ),
    path(
        "api/v1/work-items/<uuid:workItemId>/children",
        work_views.WorkItemChildrenView.as_view(),
    ),
    path(
        "api/v1/work-items/<uuid:workItemId>/tree",
        work_views.WorkItemTreeView.as_view(),
    ),
    path(
        "api/v1/work-items/<uuid:workItemId>/reorder",
        work_views.WorkItemReorderView.as_view(),
    ),
    path(
        "api/v1/projects/<uuid:projectId>/next-action",
        work_views.ProjectNextActionView.as_view(),
    ),
    path("api/v1/focus-plan-recommendations", focus_views.RecommendationsView.as_view()),
    path(
        "api/v1/focus-plan-recommendations/<uuid:recommendationId>",
        focus_views.RecommendationDetailView.as_view(),
    ),
    path("api/v1/focus-plans", focus_views.FocusPlansView.as_view()),
    path("api/v1/focus-plans/<uuid:focusPlanId>", focus_views.FocusPlanDetailView.as_view()),
    path("api/v1/execution-sessions", execution_views.ExecutionSessionsView.as_view()),
    path("api/v1/execution-sessions/active", execution_views.ActiveExecutionSessionView.as_view()),
    path(
        "api/v1/execution-sessions/<uuid:executionSessionId>",
        execution_views.ExecutionSessionDetailView.as_view(),
    ),
    path(
        "api/v1/execution-sessions/<uuid:executionSessionId>/events",
        execution_views.ExecutionSessionEventsView.as_view(),
    ),
    path(
        "api/v1/execution-sessions/<uuid:executionSessionId>/review",
        execution_views.ExecutionSessionReviewView.as_view(),
    ),
    path("api/v1/analytics/summary", analytics_views.AnalyticsSummaryView.as_view()),
    path("api/v1/analytics/work-types", analytics_views.WorkTypeAnalyticsView.as_view()),
    path(
        "api/v1/analytics/work-items/<uuid:workItemId>",
        analytics_views.WorkItemAnalyticsView.as_view(),
    ),
    path("api/v1/analytics/timeseries", analytics_views.AnalyticsTimeseriesView.as_view()),
    path("api/v1/analytics/focus-patterns", analytics_views.FocusPatternsView.as_view()),
]
