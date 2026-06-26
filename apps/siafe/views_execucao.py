"""
Views de integração SIAFE — Módulos: EXECUÇÃO ORÇAMENTÁRIA e EXECUÇÃO FINANCEIRA

Execução Orçamentária: empenho, liquidação e reserva (estágios da despesa).
Execução Financeira:   ordens bancárias por credor (pagamentos efetivados).
"""

from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated

from .client import SiafeClient
from .views import _exec


# ============================================================
# EXECUÇÃO ORÇAMENTÁRIA — Liquidação e Reserva
# ============================================================

class NotasLiquidacaoPorUGView(APIView):
    """
    GET /api/siafe/exec-orcamentaria/<exercicio>/<codigo_ug>/liquidacoes/
    Notas de liquidação de uma UG — segundo estágio da despesa.
    Representa o reconhecimento da obrigação após entrega do bem/serviço.
    Cruzar com OrdemFornecimento do sistema para rastrear execução contratual.
    """
    permission_classes = [IsAuthenticated]
    log_endpoint = "exec_orcamentaria"

    @_exec
    def get(self, request, exercicio, codigo_ug):
        return SiafeClient().notas_liquidacao_por_ug(exercicio, codigo_ug)


class NotasLiquidacaoPaginadoView(APIView):
    """
    POST /api/siafe/exec-orcamentaria/<exercicio>/liquidacoes/lista/
    Listagem paginada de liquidações com filtros.
    Body: filtros opcionais (UG, credor, natureza, período).
    ?pagina=1&por_pagina=50
    """
    permission_classes = [IsAuthenticated]
    log_endpoint = "exec_orcamentaria"

    @_exec
    def post(self, request, exercicio):
        pagina = int(request.query_params.get("pagina", 1))
        por_pagina = int(request.query_params.get("por_pagina", 50))
        return SiafeClient().notas_liquidacao_paginado(exercicio, pagina, por_pagina, request.data or {})


class NotasReservaPorUGView(APIView):
    """
    GET /api/siafe/exec-orcamentaria/<exercicio>/<codigo_ug>/reservas/
    Notas de reserva orçamentária de uma UG.
    Reserva de dotação antes do empenho — permite validar disponibilidade
    antes de iniciar processo licitatório.
    """
    permission_classes = [IsAuthenticated]
    log_endpoint = "exec_orcamentaria"

    @_exec
    def get(self, request, exercicio, codigo_ug):
        return SiafeClient().notas_reserva_por_ug(exercicio, codigo_ug)


class DespesasTransacaoPaginadoView(APIView):
    """
    POST /api/siafe/exec-orcamentaria/<exercicio>/transacoes/
    Consulta transações de despesa com filtros por natureza, UG e período.
    Útil para relatórios de execução por categoria econômica.
    ?pagina=1&por_pagina=50
    """
    permission_classes = [IsAuthenticated]
    log_endpoint = "exec_orcamentaria"

    @_exec
    def post(self, request, exercicio):
        pagina = int(request.query_params.get("pagina", 1))
        por_pagina = int(request.query_params.get("por_pagina", 50))
        return SiafeClient().despesas_transacao_paginado(exercicio, pagina, por_pagina, request.data or {})


# ============================================================
# EXECUÇÃO FINANCEIRA — Ordens Bancárias por Credor
# ============================================================

class OBOrcamentariaPorCredorView(APIView):
    """
    GET /api/siafe/exec-financeira/<exercicio>/<codigo_credor>/ob-orcamentaria/
        ?data_inicio=YYYY-MM-DD&data_fim=YYYY-MM-DD  (data_fim opcional)

    Ordens Bancárias orçamentárias contabilizadas para um credor.
    Permite rastrear pagamentos efetivados para um fornecedor de contrato,
    conciliando com o saldo_disponivel do Contrato no sistema.
    """
    permission_classes = [IsAuthenticated]
    log_endpoint = "exec_financeira"

    @_exec
    def get(self, request, exercicio, codigo_credor):
        data_inicio = request.query_params.get("data_inicio", "")
        data_fim = request.query_params.get("data_fim") or None
        return SiafeClient().ob_orcamentaria_por_credor(exercicio, codigo_credor, data_inicio, data_fim)


class OBExtraOrcamentariaPorCredorView(APIView):
    """
    GET /api/siafe/exec-financeira/<exercicio>/<codigo_credor>/ob-extra/
        ?data_inicio=YYYY-MM-DD&data_fim=YYYY-MM-DD

    OBs extra-orçamentárias (retenções devolvidas, cauções) por credor.
    """
    permission_classes = [IsAuthenticated]
    log_endpoint = "exec_financeira"

    @_exec
    def get(self, request, exercicio, codigo_credor):
        data_inicio = request.query_params.get("data_inicio", "")
        data_fim = request.query_params.get("data_fim") or None
        return SiafeClient().ob_extra_orcamentaria_por_credor(exercicio, codigo_credor, data_inicio, data_fim)


class OBRetencaoPorCredorView(APIView):
    """
    GET /api/siafe/exec-financeira/<exercicio>/<codigo_credor>/ob-retencao/
        ?data_inicio=YYYY-MM-DD&data_fim=YYYY-MM-DD

    OBs de retenção (INSS, ISS, IR retido na fonte) por credor.
    Útil para conferência de obrigações tributárias nos contratos.
    """
    permission_classes = [IsAuthenticated]
    log_endpoint = "exec_financeira"

    @_exec
    def get(self, request, exercicio, codigo_credor):
        data_inicio = request.query_params.get("data_inicio", "")
        data_fim = request.query_params.get("data_fim") or None
        return SiafeClient().ob_retencao_por_credor(exercicio, codigo_credor, data_inicio, data_fim)
