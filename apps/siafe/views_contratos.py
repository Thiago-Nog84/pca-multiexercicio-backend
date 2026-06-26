"""
Views de integração SIAFE — Módulo: CONTRATOS E CONVÊNIOS

Endpoints de consulta e conciliação de contratos/convênios registrados
no SIAFE-PI com os contratos geridos no sistema do MPPI.
"""

from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated

from .client import SiafeClient
from .views import _exec


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
    POST /api/siafe/contratos/<exercicio>/lista/
    Body JSON com filtros opcionais (codigoUG, credor, período).
    Retorna lista paginada. Parâmetros de paginação via query string:
      ?pagina=1&por_pagina=50
    """
    permission_classes = [IsAuthenticated]
    log_endpoint = "contratos_convenios"

    @_exec
    def post(self, request, exercicio):
        pagina = int(request.query_params.get("pagina", 1))
        por_pagina = int(request.query_params.get("por_pagina", 50))
        return SiafeClient().contratos_paginado(exercicio, pagina, por_pagina, request.data or {})


class ContratoConsultaView(APIView):
    """
    POST /api/siafe/contratos/<exercicio>/consulta/
    Body: { "codigoContrato": "...", "numeroOriginal": "..." }
    Consulta por código ou número original do contrato.
    """
    permission_classes = [IsAuthenticated]
    log_endpoint = "contratos_convenios"

    @_exec
    def post(self, request, exercicio):
        return SiafeClient().consultar_contrato(exercicio, request.data)


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
    POST /api/siafe/convenios/<exercicio>/lista/
    Listagem paginada de convênios. ?pagina=1&por_pagina=50
    """
    permission_classes = [IsAuthenticated]
    log_endpoint = "contratos_convenios"

    @_exec
    def post(self, request, exercicio):
        pagina = int(request.query_params.get("pagina", 1))
        por_pagina = int(request.query_params.get("por_pagina", 50))
        return SiafeClient().convenios_paginado(exercicio, pagina, por_pagina, request.data or {})
