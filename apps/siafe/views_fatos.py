"""
Views de integração SIAFE — Módulo: FATOS DE CONTRATOS

Envio bidirecional: registra no SIAFE eventos que ocorrem nos contratos
geridos pelo sistema (reserva, aquisição, ordem de serviço, liquidação, etc.).

Fluxo típico de um contrato no sistema → SIAFE:
  1. ItemPCA aprovado    → fato_reserva_orcamentaria()
  2. Licitação homologada → (empenho criado externamente ou via SIAFE)
  3. Ordem de Fornecimento emitida → fato_aquisicao() ou fato_ordem_servico()
  4. Fiscal aprova entrega → fato_aprovacao_fiscal()
  5. Contrato encerrado  → fato_encerramento_aquisicao()
  6. Pagamento anulado   → fato_anulacao_np()
"""

from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework import status as drf_status

from .client import SiafeClient, SiafeAPIError
from .views import _exec, _log
import time


def _exec_post(log_endpoint: str):
    """Decorator para views POST com payload, reutilizando a lógica de log."""
    def decorator(view_func):
        def wrapper(self, request, *args, **kwargs):
            if not request.data:
                return Response(
                    {"erro": "Payload obrigatório no corpo da requisição."},
                    status=drf_status.HTTP_400_BAD_REQUEST,
                )
            t0 = time.monotonic()
            try:
                data = view_func(self, request, *args, **kwargs)
                elapsed = int((time.monotonic() - t0) * 1000)
                _log(log_endpoint, {**kwargs, "payload_keys": list(request.data.keys())},
                     True, 200, elapsed, request.user)
                return Response(data)
            except SiafeAPIError as exc:
                elapsed = int((time.monotonic() - t0) * 1000)
                _log(log_endpoint, kwargs, False, exc.status_code, elapsed, request.user, exc.detail)
                return Response(
                    {"erro": "Falha ao enviar fato ao SIAFE-PI.", "detalhe": exc.detail},
                    status=drf_status.HTTP_502_BAD_GATEWAY,
                )
            except Exception as exc:
                elapsed = int((time.monotonic() - t0) * 1000)
                _log(log_endpoint, kwargs, False, 0, elapsed, request.user, str(exc))
                return Response(
                    {"erro": "Erro interno ao enviar fato ao SIAFE-PI."},
                    status=drf_status.HTTP_500_INTERNAL_SERVER_ERROR,
                )
        return wrapper
    return decorator


class FatoReservaOrcamentariaView(APIView):
    """
    POST /api/siafe/fatos/<exercicio>/reserva-orcamentaria/
    Registra no SIAFE uma reserva orçamentária vinculada a contrato.
    Acionado ao aprovar um ItemPCA para garantir dotação antes da licitação.
    Body: { "reservaOrcamentaria": {...}, "contrato": {...} }
    """
    permission_classes = [IsAuthenticated]

    @_exec_post("fatos_contratos")
    def post(self, request, exercicio):
        return SiafeClient().fato_reserva_orcamentaria(exercicio, request.data)


class FatoAquisicaoView(APIView):
    """
    POST /api/siafe/fatos/<exercicio>/aquisicao/
    Registra aquisição de material/serviço vinculada a contrato no SIAFE.
    Acionado ao emitir uma OrdemFornecimento no módulo de contratos.
    """
    permission_classes = [IsAuthenticated]

    @_exec_post("fatos_contratos")
    def post(self, request, exercicio):
        return SiafeClient().fato_aquisicao(exercicio, request.data)


class FatoSolicitacaoConsumoView(APIView):
    """
    POST /api/siafe/fatos/<exercicio>/solicitacao-consumo/
    Registra solicitação de consumo de material no SIAFE.
    """
    permission_classes = [IsAuthenticated]

    @_exec_post("fatos_contratos")
    def post(self, request, exercicio):
        return SiafeClient().fato_solicitacao_consumo(exercicio, request.data)


class FatoOrdemServicoView(APIView):
    """
    POST /api/siafe/fatos/<exercicio>/ordem-servico/
    Contabiliza no SIAFE uma ordem de serviço emitida contra contrato.
    """
    permission_classes = [IsAuthenticated]

    @_exec_post("fatos_contratos")
    def post(self, request, exercicio):
        return SiafeClient().fato_ordem_servico(exercicio, request.data)


class FatoAprovacaoFiscalView(APIView):
    """
    POST /api/siafe/fatos/<exercicio>/aprovacao-fiscal/
    Registra aprovação do fiscal do contrato para fins de liquidação.
    Deve ser chamado quando o fiscal confirma entrega no sistema.
    """
    permission_classes = [IsAuthenticated]

    @_exec_post("fatos_contratos")
    def post(self, request, exercicio):
        return SiafeClient().fato_aprovacao_fiscal(exercicio, request.data)


class FatoEncerramentoAquisicaoView(APIView):
    """
    POST /api/siafe/fatos/<exercicio>/encerramento-aquisicao/
    Registra encerramento de aquisição (finalização/rescisão do contrato).
    """
    permission_classes = [IsAuthenticated]

    @_exec_post("fatos_contratos")
    def post(self, request, exercicio):
        return SiafeClient().fato_encerramento_aquisicao(exercicio, request.data)


class FatoAnulacaoNPView(APIView):
    """
    POST /api/siafe/fatos/<exercicio>/anulacao-np/
    Anula uma nota de pagamento vinculada a contrato no SIAFE.
    """
    permission_classes = [IsAuthenticated]

    @_exec_post("fatos_contratos")
    def post(self, request, exercicio):
        return SiafeClient().fato_anulacao_np(exercicio, request.data)
