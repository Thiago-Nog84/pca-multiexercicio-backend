from rest_framework.views import exception_handler
from rest_framework.response import Response
from rest_framework import status
from django.core.exceptions import ValidationError as DjangoValidationError
import logging

logger = logging.getLogger(__name__)


class DomainError(Exception):
    """Exceção base para regras de negócio da aplicação."""
    default_message = "Erro de negócio."
    default_code = "domain_error"
    status_code = status.HTTP_400_BAD_REQUEST

    def __init__(self, message=None, code=None, status_code=None):
        self.message = message or self.default_message
        self.code = code or self.default_code
        if status_code:
            self.status_code = status_code
        super().__init__(self.message)


class ResourceNotFoundError(DomainError):
    default_message = "Recurso não encontrado."
    default_code = "not_found"
    status_code = status.HTTP_404_NOT_FOUND


class ConcurrencyError(DomainError):
    default_message = "Conflito de concorrência ao atualizar recurso."
    default_code = "concurrency_conflict"
    status_code = status.HTTP_409_CONFLICT


class BusinessRuleViolationError(DomainError):
    default_message = "Violação de regra de negócio."
    default_code = "business_rule_violation"
    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY


def api_exception_handler(exc, context):
    """
    Handler customizado para DRF.
    Padroniza respostas de exceções de domínio e do Django ValidationError.
    """
    response = exception_handler(exc, context)

    if isinstance(exc, DomainError):
        return Response(
            {
                "detail": exc.message,
                "code": exc.code,
            },
            status=exc.status_code,
        )

    if isinstance(exc, DjangoValidationError):
        if hasattr(exc, "message_dict"):
            detail = exc.message_dict
        elif hasattr(exc, "messages"):
            detail = exc.messages
        else:
            detail = str(exc)
        return Response(
            {
                "detail": detail,
                "code": "validation_error",
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    if response is not None:
        if isinstance(response.data, dict) and "detail" not in response.data and "code" not in response.data:
            # Mantém formato consistente
            response.data = {
                "detail": response.data,
                "code": "error",
            }

    return response
