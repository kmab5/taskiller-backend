"""Authenticated portable bulk import API."""

from __future__ import annotations

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from taskiller.django_api.portable_import import import_portable_document
from taskiller.django_api.work_service import require_idempotency_key


class PortableImportView(APIView):
    permission_classes = (IsAuthenticated,)

    @extend_schema(
        operation_id="importPortableWork",
        tags=["Work"],
        request=OpenApiTypes.OBJECT,
        responses={201: OpenApiTypes.OBJECT},
    )
    def post(self, request: Request) -> Response:
        key = require_idempotency_key(request.headers.get("Idempotency-Key"))
        result = import_portable_document(request.auth.user.id, request.data, key)
        return Response(result, status=201)
