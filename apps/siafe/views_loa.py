"""
Views de integração SIAFE — Módulo: PLANEJAMENTO LOA

Permite cruzar o PCA com as metas físicas e dotações aprovadas na LOA,
e enviar propostas de despesa para o planejamento.

Fluxo PCA → LOA:
  - Na revisão pós-LOA (status "revisao_loa"), consultar meta-ação para
    verificar se cada ItemPCA tem dotação aprovada.
  - Ajustar itens sem cobertura antes de publicar no PNCP.
"""

from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework import status as drf_status

from .client import SiafeClient, SiafeAPIError
from .views import _exec, _log, _exec as _exec_get
import time


class MetaAcaoConsultaView(APIView):
    """
    POST /api/siafe/loa/<exercicio>/meta-acao/
    Consulta metas e ações do planejamento LOA.
    Body: { "codigoPrograma": "...", "codigoAcao": "...", "codigoUG": "..." }

    Usar na etapa "revisao_loa" do PCA para validar se cada ItemPCA
    tem meta física aprovada na LOA do exercício.
    """
    permission_classes = [IsAuthenticated]
    log_endpoint = "planejamento_loa"

    def post(self, request, exercicio):
        if not request.data:
            return Response(
                {"erro": "Informe ao menos um filtro (codigoPrograma, codigoAcao ou codigoUG)."},
                status=drf_status.HTTP_400_BAD_REQUEST,
            )
        t0 = time.monotonic()
        try:
            data = SiafeClient().consultar_meta_acao(exercicio, request.data)
            elapsed = int((time.monotonic() - t0) * 1000)
            _log("planejamento_loa", {"exercicio": exercicio, **request.data},
                 True, 200, elapsed, request.user)
            return Response(data)
        except SiafeAPIError as exc:
            elapsed = int((time.monotonic() - t0) * 1000)
            _log("planejamento_loa", {"exercicio": exercicio}, False, exc.status_code,
                 elapsed, request.user, exc.detail)
            return Response(
                {"erro": "Falha ao consultar planejamento LOA.", "detalhe": exc.detail},
                status=drf_status.HTTP_502_BAD_GATEWAY,
            )
        except Exception as exc:
            elapsed = int((time.monotonic() - t0) * 1000)
            _log("planejamento_loa", {"exercicio": exercicio}, False, 0,
                 elapsed, request.user, str(exc))
            return Response(
                {"erro": "Erro interno ao consultar LOA."},
                status=drf_status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class PropostaDespesaLOAView(APIView):
    """
    POST /api/siafe/loa/<exercicio>/proposta-despesa/
    Envia proposta de despesa ao planejamento LOA/PPA.
    Body: estrutura da proposta conforme modelo SIAFE.
    """
    permission_classes = [IsAuthenticated]
    log_endpoint = "planejamento_loa"

    def post(self, request, exercicio):
        if not request.data:
            return Response(
                {"erro": "Payload da proposta de despesa é obrigatório."},
                status=drf_status.HTTP_400_BAD_REQUEST,
            )
        t0 = time.monotonic()
        try:
            data = SiafeClient().proposta_despesa_loa(exercicio, request.data)
            elapsed = int((time.monotonic() - t0) * 1000)
            _log("planejamento_loa", {"exercicio": exercicio}, True, 200, elapsed, request.user)
            return Response(data)
        except SiafeAPIError as exc:
            elapsed = int((time.monotonic() - t0) * 1000)
            _log("planejamento_loa", {"exercicio": exercicio}, False, exc.status_code,
                 elapsed, request.user, exc.detail)
            return Response(
                {"erro": "Falha ao enviar proposta de despesa.", "detalhe": exc.detail},
                status=drf_status.HTTP_502_BAD_GATEWAY,
            )
        except Exception as exc:
            elapsed = int((time.monotonic() - t0) * 1000)
            _log("planejamento_loa", {"exercicio": exercicio}, False, 0,
                 elapsed, request.user, str(exc))
            return Response(
                {"erro": "Erro interno ao enviar proposta."},
                status=drf_status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
