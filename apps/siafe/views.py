"""
Views REST para a integração com o SIAFE-PI.

Todos os endpoints exigem autenticação JWT (IsAuthenticated).
As consultas são registradas em SiafeLogConsulta para auditoria.
"""

import time
import logging

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .client import SiafeClient, SiafeAPIError
from .models import SiafeLogConsulta

logger = logging.getLogger(__name__)


def _log(endpoint: str, parametros: dict, sucesso: bool, status_http: int,
         tempo_ms: int, usuario, erro: str = ""):
    SiafeLogConsulta.objects.create(
        endpoint=endpoint,
        parametros=parametros,
        sucesso=sucesso,
        status_http=status_http,
        tempo_resposta_ms=tempo_ms,
        consultado_por=usuario if usuario.is_authenticated else None,
        erro_detalhe=erro,
    )


def _exec(view_func):
    """Decorator interno: executa a consulta ao SIAFE, registra log e trata erros."""
    def wrapper(self, request, *args, **kwargs):
        t0 = time.monotonic()
        try:
            data = view_func(self, request, *args, **kwargs)
            elapsed = int((time.monotonic() - t0) * 1000)
            _log(
                endpoint=getattr(self, "log_endpoint", "outro"),
                parametros=dict(kwargs),
                sucesso=True,
                status_http=200,
                tempo_ms=elapsed,
                usuario=request.user,
            )
            return Response(data)
        except SiafeAPIError as exc:
            elapsed = int((time.monotonic() - t0) * 1000)
            _log(
                endpoint=getattr(self, "log_endpoint", "outro"),
                parametros=dict(kwargs),
                sucesso=False,
                status_http=exc.status_code,
                tempo_ms=elapsed,
                usuario=request.user,
                erro=exc.detail,
            )
            logger.warning("SIAFE error [%s]: %s", exc.status_code, exc.detail)
            return Response(
                {"erro": "Falha na consulta ao SIAFE-PI.", "detalhe": exc.detail},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        except Exception as exc:
            elapsed = int((time.monotonic() - t0) * 1000)
            _log(
                endpoint=getattr(self, "log_endpoint", "outro"),
                parametros=dict(kwargs),
                sucesso=False,
                status_http=0,
                tempo_ms=elapsed,
                usuario=request.user,
                erro=str(exc),
            )
            logger.exception("Erro inesperado ao consultar SIAFE")
            return Response(
                {"erro": "Erro interno ao consultar o SIAFE-PI."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
    return wrapper


# ---------------------------------------------------------------------------
# Nota de Empenho
# ---------------------------------------------------------------------------

class NotaEmpenhoPorUGView(APIView):
    """
    GET /api/siafe/nota-empenho/<exercicio>/<codigo_ug>/
    Lista todas as notas de empenho de uma UG no exercício.
    """
    permission_classes = [IsAuthenticated]
    log_endpoint = "nota_empenho"

    @_exec
    def get(self, request, exercicio, codigo_ug):
        return SiafeClient().nota_empenho_por_ug(exercicio, codigo_ug)


class NotaEmpenhoPorUGMesView(APIView):
    """
    GET /api/siafe/nota-empenho/<exercicio>/<codigo_ug>/<mes>/
    Notas de empenho filtradas por mês (1–12).
    """
    permission_classes = [IsAuthenticated]
    log_endpoint = "nota_empenho"

    @_exec
    def get(self, request, exercicio, codigo_ug, mes):
        return SiafeClient().nota_empenho_por_ug_mes(exercicio, codigo_ug, mes)


class NotaEmpenhoPaginadoView(APIView):
    """
    GET /api/siafe/nota-empenho/<exercicio>/paginado/?pagina=1&por_pagina=50
    Listagem paginada de empenhos do exercício.
    """
    permission_classes = [IsAuthenticated]
    log_endpoint = "nota_empenho"

    @_exec
    def get(self, request, exercicio):
        pagina = int(request.query_params.get("pagina", 1))
        por_pagina = int(request.query_params.get("por_pagina", 50))
        return SiafeClient().nota_empenho_paginado(exercicio, pagina, por_pagina)


# ---------------------------------------------------------------------------
# Saldo Orçamentário
# ---------------------------------------------------------------------------

class SaldoOrcamentarioAnualView(APIView):
    """
    GET /api/siafe/saldo-orcamentario/<exercicio>/<codigo_ug>/
    Saldo orçamentário consolidado anual — usado para validar dotação antes de licitação.
    """
    permission_classes = [IsAuthenticated]
    log_endpoint = "saldo_orcamentario"

    @_exec
    def get(self, request, exercicio, codigo_ug):
        return SiafeClient().saldo_orcamentario_anual(exercicio, codigo_ug)


class SaldoOrcamentarioMensalView(APIView):
    """
    GET /api/siafe/saldo-orcamentario/<exercicio>/mensal/<mes>/
    Saldo de todas as UGs no mês informado.
    """
    permission_classes = [IsAuthenticated]
    log_endpoint = "saldo_orcamentario"

    @_exec
    def get(self, request, exercicio, mes):
        return SiafeClient().saldo_orcamentario_mensal(exercicio, mes)


# ---------------------------------------------------------------------------
# Estrutura Classificatória
# ---------------------------------------------------------------------------

class AcoesView(APIView):
    """
    GET /api/siafe/estrutura/<exercicio>/acoes/
    Ações de governo ativas — para popular seletores no PCA.
    """
    permission_classes = [IsAuthenticated]
    log_endpoint = "acoes"

    @_exec
    def get(self, request, exercicio):
        return SiafeClient().acoes(exercicio)


class NaturezasDespesaView(APIView):
    """
    GET /api/siafe/estrutura/<exercicio>/naturezas-despesa/
    Naturezas de despesa com subitem.
    """
    permission_classes = [IsAuthenticated]
    log_endpoint = "natureza_despesa"

    @_exec
    def get(self, request, exercicio):
        return SiafeClient().naturezas_despesa(exercicio)


class ElementosDespesaView(APIView):
    """
    GET /api/siafe/estrutura/<exercicio>/elementos-despesa/
    """
    permission_classes = [IsAuthenticated]
    log_endpoint = "natureza_despesa"

    @_exec
    def get(self, request, exercicio):
        return SiafeClient().elementos_despesa(exercicio)


class ProgramasView(APIView):
    """
    GET /api/siafe/estrutura/<exercicio>/programas/
    Programas orçamentários do exercício.
    """
    permission_classes = [IsAuthenticated]
    log_endpoint = "programas"

    @_exec
    def get(self, request, exercicio):
        return SiafeClient().programas(exercicio)


# ---------------------------------------------------------------------------
# Credores
# ---------------------------------------------------------------------------

class CredoresView(APIView):
    """
    GET /api/siafe/credores/<exercicio>/?pagina=1&por_pagina=100
    """
    permission_classes = [IsAuthenticated]
    log_endpoint = "credores"

    @_exec
    def get(self, request, exercicio):
        pagina = int(request.query_params.get("pagina", 1))
        por_pagina = int(request.query_params.get("por_pagina", 100))
        return SiafeClient().credores(exercicio, pagina, por_pagina)


class CredorDetalheView(APIView):
    """
    GET /api/siafe/credores/<exercicio>/<codigo>/
    """
    permission_classes = [IsAuthenticated]
    log_endpoint = "credores"

    @_exec
    def get(self, request, exercicio, codigo):
        return SiafeClient().credor(exercicio, codigo)


# ---------------------------------------------------------------------------
# Saldo Contábil
# ---------------------------------------------------------------------------

class SaldoContabilMensalView(APIView):
    """
    GET /api/siafe/saldo-contabil/<exercicio>/<mes>/<conta>/<codigo_ug>/
    """
    permission_classes = [IsAuthenticated]
    log_endpoint = "saldo_contabil"

    @_exec
    def get(self, request, exercicio, mes, conta, codigo_ug):
        return SiafeClient().saldo_contabil_mensal(exercicio, mes, conta, codigo_ug)
