"""Public Meta lifecycle callbacks for Instagram Login."""

import logging

from django.core.exceptions import RequestDataTooBig
from django.http import (
    Http404,
    HttpRequest,
    HttpResponse,
    HttpResponseNotAllowed,
    JsonResponse,
    QueryDict,
)
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt

from apps.channels.meta_callbacks import (
    create_deletion_receipt,
    delete_connected_instagram_account,
    deployment_instagram_app_secret,
    parse_signed_request,
    receipt_for_code,
)

logger = logging.getLogger(__name__)

MAX_CALLBACK_BODY_BYTES = 16 * 1024


def _app_secret_or_404() -> str:
    secret = deployment_instagram_app_secret()
    if not secret:
        raise Http404
    return secret


def _signed_request(request: HttpRequest) -> str | None:
    """Read a small form-urlencoded callback body without trusting request.POST."""
    raw_length = request.META.get("CONTENT_LENGTH", "")
    try:
        if raw_length and int(raw_length) > MAX_CALLBACK_BODY_BYTES:
            return None
    except (TypeError, ValueError):
        return None
    try:
        raw = request.body
    except RequestDataTooBig:
        return None
    if len(raw) > MAX_CALLBACK_BODY_BYTES:
        return None
    try:
        form = QueryDict(raw.decode("utf-8"), encoding="utf-8")
    except UnicodeDecodeError:
        return None
    value = form.get("signed_request", "")
    return value if isinstance(value, str) and value else None


def _verified_user_id(request: HttpRequest) -> str | None:
    secret = _app_secret_or_404()
    signed = _signed_request(request)
    if not signed:
        return None
    payload = parse_signed_request(signed, app_secret=secret)
    return str(payload["user_id"]) if payload is not None else None


@csrf_exempt
def instagram_deauthorize(request: HttpRequest) -> HttpResponse:
    """Handle Meta deauthorization for a connected Instagram account."""
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    user_id = _verified_user_id(request)
    if user_id is None:
        return JsonResponse({"status": "invalid_request"}, status=403)

    deleted = delete_connected_instagram_account(user_id)
    logger.info("Processed Instagram deauthorize callback; deleted_connections=%s", deleted)
    return JsonResponse({"status": "ok"})


@csrf_exempt
def instagram_data_deletion(request: HttpRequest) -> HttpResponse:
    """Delete local data for the connected account named by Meta."""
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    user_id = _verified_user_id(request)
    if user_id is None:
        return JsonResponse({"status": "invalid_request"}, status=403)

    deleted = delete_connected_instagram_account(user_id)
    code, _receipt = create_deletion_receipt(deleted_connections=deleted)
    status_path = reverse("instagram_data_deletion_status", kwargs={"confirmation_code": code})
    status_url = request.build_absolute_uri(status_path)
    logger.info("Processed Instagram data-deletion callback; deleted_connections=%s", deleted)
    return JsonResponse({"url": status_url, "confirmation_code": code})


def instagram_data_deletion_status(request: HttpRequest, confirmation_code: str) -> HttpResponse:
    """Public capability URL returned to Meta after a completed deletion."""
    if request.method != "GET":
        return HttpResponseNotAllowed(["GET"])
    receipt = receipt_for_code(confirmation_code)
    if receipt is None:
        raise Http404
    return JsonResponse(
        {
            "status": "completed",
            "confirmation_code": confirmation_code,
            "completed_at": receipt.completed_at.isoformat(),
            "deleted_connections": receipt.deleted_connections,
        }
    )
