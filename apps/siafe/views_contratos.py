"""
Views de integração SIAFE — Módulo: CONTRATOS E CONVÊNIOS

Endpoints de consulta e conciliação de contratos/convênios registrados
no SIAFE-PI com os contratos geridos no sistema do MPPI.
"""

from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated

from .client import SiafeClient
from .views import _exec


class ContratosUGView(APIView):
    """
    GET /api/siafe/contratos/<exercicio>/ug/<codigo_ug>/
    Lista todos os contratos de uma UG no exercício.
    Mesmo padrão de /nota-empenho/{exercicio}/{codigoUG}.
    """
    permission_classes = [IsAuthenticated]
    log_endpoint = "contratos_convenios"

    @_exec
    def get(self, request, exercicio, codigo_ug):
        return SiafeClient().contratos_por_ug(exercicio, codigo_ug)


class ContratoDetalheView(APIView):
    """
    GET /api/siafe/contratos/<exercicio>/<codigo_contrato>/
    Consulta um contrato no SIAFE pelo código.
    Usar para conciliar valores, datas e partes com o Contrato local.
    """
    permission_classes = [IsAuthenticated]
    log_endpoint = "contratos_convenios"

    @_exec
    def get(self, request, exercicio, codigo_contrato):
        return SiafeClient().contrato(exercicio, codigo_contrato)


class ContratosPaginadoView(APIView):
    """
    GET /api/siafe/contratos/<exercicio>/lista/
    Filtros opcionais via query string: ?codigoUG=926092&pagina=1&por_pagina=50
    Também aceita POST com body JSON para filtros avançados.
    """
    permission_classes = [IsAuthenticated]
    log_endpoint = "contratos_convenios"

    @_exec
    def get(self, request, exercicio):
        pagina = int(request.query_params.get("pagina", 1))
        por_pagina = int(request.query_params.get("por_pagina", 50))
        filtros = {}
        for campo in ("codigoUG", "credor", "numeroContrato", "dataInicio", "dataFim"):
            if request.query_params.get(campo):
                filtros[campo] = request.query_params[campo]
        return SiafeClient().contratos_paginado(exercicio, pagina, por_pagina, filtros)

    @_exec
    def post(self, request, exercicio):
        pagina = int(request.query_params.get("pagina", 1))
        por_pagina = int(request.query_params.get("por_pagina", 50))
        return SiafeClient().contratos_paginado(exercicio, pagina, por_pagina, request.data or {})


class ContratoConsultaView(APIView):
    """
    GET /api/siafe/contratos/<exercicio>/consulta/
      ?codigoContratante=250101&codigoContratado=CNPJ&numeroOriginal=15/2026/FPDC
    UGs MPPI: 250101 (PGJ), 250102 (FMMPPI), 250104 (FPDC).
    """
    permission_classes = [IsAuthenticated]
    log_endpoint = "contratos_convenios"

    @_exec
    def get(self, request, exercicio):
        filtros = {
            "codigoContratante": request.query_params.get("codigoContratante", ""),
            "codigoContratado": request.query_params.get("codigoContratado", ""),
            "numeroOriginal": request.query_params.get("numeroOriginal", ""),
        }
        if request.query_params.get("codigo"):
            filtros["codigo"] = request.query_params["codigo"]
        return SiafeClient().consultar_contrato(exercicio, filtros)


class ConvenioDetalheView(APIView):
    """
    GET /api/siafe/convenios/<exercicio>/<codigo_convenio>/
    """
    permission_classes = [IsAuthenticated]
    log_endpoint = "contratos_convenios"

    @_exec
    def get(self, request, exercicio, codigo_convenio):
        return SiafeClient().convenio(exercicio, codigo_convenio)


class ConveniosPaginadoView(APIView):
    """
    GET /api/siafe/convenios/<exercicio>/lista/
    Filtros opcionais via query string: ?codigoUG=926092&pagina=1&por_pagina=50
    """
    permission_classes = [IsAuthenticated]
    log_endpoint = "contratos_convenios"

    @_exec
    def get(self, request, exercicio):
        pagina = int(request.query_params.get("pagina", 1))
        por_pagina = int(request.query_params.get("por_pagina", 50))
        filtros = {}
        for campo in ("codigoUG", "credor", "numeroConvenio", "dataInicio", "dataFim"):
            if request.query_params.get(campo):
                filtros[campo] = request.query_params[campo]
        return SiafeClient().convenios_paginado(exercicio, pagina, por_pagina, filtros)

    @_exec
    def post(self, request, exercicio):
        pagina = int(request.query_params.get("pagina", 1))
        por_pagina = int(request.query_params.get("por_pagina", 50))
        return SiafeClient().convenios_paginado(exercicio, pagina, por_pagina, request.data or {})
