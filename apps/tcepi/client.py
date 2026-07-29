"""
Cliente HTTP para a API do Portal da Cidadania (TCE-PI).
Documentação: https://sistemas.tce.pi.gov.br/api/portaldacidadania/docs/

Diferente do SIAFE, esta API é PÚBLICA — não exige autenticação nem
credenciais. É a fonte de dados do órgão de CONTROLE EXTERNO (Tribunal de
Contas), portanto independente tanto do SIAFE (execução orçamentária do
Poder Executivo) quanto do PNCP/dadosabertos (divulgação de compras) — serve
como uma TERCEIRA fonte para cruzar e validar dados do sistema.

`idUnidadeGestora` do MPPI (confirmado ao vivo em 2026-07-29, bate com os
códigos já usados no SIAFE): ver `CODIGOS_UG_MPPI` abaixo.

Convenção dos parâmetros da API (conforme docs):
  - "Órgãos" do Estado usam os endpoints com prefixo /estado/ e
    idUnidadeGestora é o código de 6 dígitos da Unidade Gestora estadual.
  - "Municípios" usam os mesmos endpoints sem o prefixo /estado/ — não é o
    caso do MPPI, mas os métodos abaixo cobrem ambos onde aplicável.
"""

import logging
from typing import Any, Optional

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

BASE_URL = getattr(
    settings, "TCEPI_BASE_URL", "https://sistemas.tce.pi.gov.br/api/portaldacidadania"
)

# idUnidadeGestora do MPPI no TCE-PI — idênticos aos códigos de Unidade
# Gestora já usados na integração SIAFE (ver apps/siafe/client.py e
# apps/contratos/management/commands/importar_contratos_siafe_api.py) E às
# chaves de Contrato.UNIDADE_ORCAMENTARIA (pgj/fmmp/fepdc) em
# apps/contratos/models.py — usar as MESMAS chaves nos dois lugares.
CODIGOS_UG_MPPI = {
    "pgj": "250101",    # Procuradoria-Geral de Justiça
    "fmmp": "250102",   # Fundo Especial do Ministério Público (FUNDMPE no TCE)
    "fepdc": "250104",  # Fundo de Proteção e Defesa do Consumidor (FPDC no TCE)
}


class TcePiAPIError(Exception):
    """Exceção para erros retornados pela API do Portal da Cidadania."""

    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"TCE-PI {status_code}: {detail}")


class TcePiClient:
    """
    Cliente reutilizável para a API pública do Portal da Cidadania (TCE-PI).
    Sem autenticação — só um requests.Session simples com timeout e retry
    leve em caso de erro de rede.

    Uso:
        client = TcePiClient()
        despesas = client.despesas_orgao_por_elemento("250101", 2026)
        credores = client.credores_orgao_lista_completa("250101", 2026)
    """

    def __init__(self):
        self.base_url = BASE_URL.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({"Accept": "application/json"})

    # ------------------------------------------------------------------
    # Núcleo HTTP
    # ------------------------------------------------------------------

    def _get(self, path: str, params: Optional[dict] = None, timeout: int = 30) -> Any:
        url = f"{self.base_url}{path}"
        try:
            resp = self.session.get(url, params=params or None, timeout=timeout)
        except requests.RequestException as exc:
            raise TcePiAPIError(0, f"Erro de rede: {exc}") from exc

        if not resp.ok:
            try:
                detail = resp.json()
            except Exception:
                detail = resp.text[:300]
            raise TcePiAPIError(resp.status_code, str(detail))

        if not resp.text.strip():
            return []
        return resp.json()

    def _get_paginado(
        self, path: str, params: Optional[dict] = None,
        campo_lista: str = None, qtde_por_pagina: int = 100, max_paginas: int = 200,
    ) -> list:
        """
        Percorre um endpoint paginado (parâmetros `pagina`/`qtdePorPagina`)
        até a página vir vazia ou menor que `qtde_por_pagina`, concatenando
        os resultados. `campo_lista` é o nome do campo de lista dentro do
        JSON de resposta quando o payload é um objeto (ex: {"credores": [...]})
        — se None, assume que a resposta já é uma lista direta.
        """
        resultado = []
        pagina = 1
        params = dict(params or {})
        while pagina <= max_paginas:
            params["pagina"] = pagina
            params["qtdePorPagina"] = qtde_por_pagina
            resp = self._get(path, params=params)
            lote = resp.get(campo_lista, []) if campo_lista and isinstance(resp, dict) else resp
            if not lote:
                break
            resultado.extend(lote)
            if len(lote) < qtde_por_pagina:
                break
            pagina += 1
        return resultado

    # ------------------------------------------------------------------
    # Órgãos
    # ------------------------------------------------------------------

    def orgaos_lista(self, exercicio: int) -> list:
        """GET /orgaos/lista/{exercicio} — todos os órgãos estaduais do exercício (id/nome/sigla)."""
        return self._get(f"/orgaos/lista/{exercicio}")

    def orgao_receita_despesa(self, id_unidade_gestora: str, exercicio: int) -> dict:
        """
        GET /{idUnidadeGestora}/{exercicio}
        Consolidado de receita (prevista/arrecadada) e despesa (empenhada/
        liquidada/paga) do órgão no exercício — visão de alto nível.
        """
        return self._get(f"/{id_unidade_gestora}/{exercicio}")

    # ------------------------------------------------------------------
    # Despesas — execução orçamentária (cruzar com SIAFE/Contrato)
    # ------------------------------------------------------------------

    def despesas_orgao(self, id_unidade_gestora: str) -> list:
        """GET /despesas/estado/{idUnidadeGestora}?  — despesas do órgão por exercício (todos os anos disponíveis)."""
        return self._get(f"/despesas/estado/{id_unidade_gestora}")

    def despesas_orgao_por_elemento(self, id_unidade_gestora: str, exercicio: int) -> list:
        """GET /despesas/estado/{id}/{exercicio}/porElemento — empenhada/liquidada/paga por elemento de despesa."""
        return self._get(f"/despesas/estado/{id_unidade_gestora}/{exercicio}/porElemento")

    def despesas_orgao_por_funcao(self, id_unidade_gestora: str, exercicio: int) -> list:
        """GET /despesas/estado/{id}/{exercicio}/porFuncao — valor pago por função de governo."""
        return self._get(f"/despesas/estado/{id_unidade_gestora}/{exercicio}/porFuncao")

    def despesas_orgao_por_natureza(self, id_unidade_gestora: str, exercicio: int) -> list:
        """GET /despesas/estado/{id}/{exercicio}/porNatureza — valor pago por categoria econômica."""
        return self._get(f"/despesas/estado/{id_unidade_gestora}/{exercicio}/porNatureza")

    def despesas_orgao_lista_por_funcao(self, id_unidade_gestora: str, exercicio: int) -> list:
        """GET /despesas/estado/{id}/{exercicio}/lista/porFuncao — lista detalhada por função."""
        return self._get(f"/despesas/estado/{id_unidade_gestora}/{exercicio}/lista/porFuncao")

    def despesas_orgao_lista_por_natureza(self, id_unidade_gestora: str, exercicio: int) -> list:
        """GET /despesas/estado/{id}/{exercicio}/lista/porNatureza — lista detalhada por natureza."""
        return self._get(f"/despesas/estado/{id_unidade_gestora}/{exercicio}/lista/porNatureza")

    def maiores_despesas_orgao_por_elemento(self, id_unidade_gestora: str, exercicio: int) -> list:
        """GET /despesas/estado/{id}/{exercicio}/maiores/porElemento — ranking dos maiores elementos de despesa."""
        return self._get(f"/despesas/estado/{id_unidade_gestora}/{exercicio}/maiores/porElemento")

    def despesas_total_municipios(self) -> Any:
        """GET /despesas/total — total agregado de despesas de todos os municípios (referência de contexto)."""
        return self._get("/despesas/total")

    # ------------------------------------------------------------------
    # Credores — cruzar CNPJ/valor contra Contrato/fornecedor local
    # ------------------------------------------------------------------

    def credores_orgao_lista(
        self, id_unidade_gestora: str, exercicio: int,
        pagina: int = 1, qtde_por_pagina: int = 100, tipo_credor: Optional[str] = None,
    ) -> list:
        """
        GET /credores/estado/{id}/{exercicio}/lista
        Uma página de credores do órgão no exercício (CNPJ/CPF, nome,
        empenhado/liquidado/pago). tipoCredor: "F" pessoa física, "J" jurídica.
        """
        params = {"pagina": pagina, "qtdePorPagina": qtde_por_pagina}
        if tipo_credor:
            params["tipoCredor"] = tipo_credor
        return self._get(f"/credores/estado/{id_unidade_gestora}/{exercicio}/lista", params=params)

    def credores_orgao_lista_completa(
        self, id_unidade_gestora: str, exercicio: int, tipo_credor: Optional[str] = None,
    ) -> list:
        """Percorre todas as páginas de credores_orgao_lista e concatena o resultado."""
        params = {"tipoCredor": tipo_credor} if tipo_credor else {}
        return self._get_paginado(
            f"/credores/estado/{id_unidade_gestora}/{exercicio}/lista",
            params=params, qtde_por_pagina=100,
        )

    def maiores_credores_orgao(self, id_unidade_gestora: str, exercicio: int) -> list:
        """GET /credores/estado/{id}/{exercicio} — ranking dos maiores credores do órgão no exercício."""
        return self._get(f"/credores/estado/{id_unidade_gestora}/{exercicio}")

    def quantidade_credores_orgao(self, id_unidade_gestora: str, exercicio: int) -> Any:
        """GET /credores/estado/{id}/{exercicio}/quantidade — total de credores distintos no exercício."""
        return self._get(f"/credores/estado/{id_unidade_gestora}/{exercicio}/quantidade")

    def tipos_credor(self) -> Any:
        """GET /credores/tipos — valores possíveis de tipoCredor."""
        return self._get("/credores/tipos")

    # ------------------------------------------------------------------
    # Licitações — enriquecer ProcessoLicitatorio / detectar faltantes
    # ------------------------------------------------------------------

    def licitacoes_orgao(self, id_unidade_gestora: str) -> list:
        """GET /licitacoes/{idUnidadeGestora} — licitações do órgão, agregadas por data (previsto/link)."""
        return self._get(f"/licitacoes/{id_unidade_gestora}")

    def licitacoes_orgao_data(
        self, id_unidade_gestora: str, data: str, esfera: int = 2,
        pagina: int = 1, qtde_por_pagina: int = 100,
        campo_ordenacao: Optional[str] = None, asc_desc: int = 0,
    ) -> list:
        """
        GET /licitacoes/{id}/{esfera}/{data}
        Detalhe das licitações de uma data específica (AAAAMMDD).
        esfera: 1=Municipal, 2=Estadual (MPPI é sempre 2).
        Traz objeto, modalidade, regime, tipo, unidadeOrcamentaria, mural
        (link Sistema Licitações Web) e idLicitacaoWeb.
        """
        params = {"pagina": pagina, "qtdePorPagina": qtde_por_pagina, "ascDesc": asc_desc}
        if campo_ordenacao:
            params["campoOrdenacao"] = campo_ordenacao
        return self._get(f"/licitacoes/{id_unidade_gestora}/{esfera}/{data}", params=params)

    def licitacoes_estado(self) -> list:
        """GET /licitacoes/estado — licitações de TODOS os órgãos estaduais, agregadas por data."""
        return self._get("/licitacoes/estado")

    # ------------------------------------------------------------------
    # Documentos — índice de documentos enviados ao TCE
    # ------------------------------------------------------------------

    def documentos_orgao(
        self, id_unidade_gestora: str, pagina: int = 1, qtde_por_pagina: int = 100,
        campo_filtro: Optional[str] = None, valor_filtro: Optional[str] = None,
    ) -> list:
        """GET /documentos/{idUnidadeGestora} — documentos enviados pelo órgão (nome/observações/data/link)."""
        params = {"pagina": pagina, "qtdePorPagina": qtde_por_pagina}
        if campo_filtro:
            params["campoFiltro"] = campo_filtro
            params["valorFiltro"] = valor_filtro
        return self._get(f"/documentos/{id_unidade_gestora}", params=params)

    def documentos_orgao_digitalizados(self, id_unidade_gestora: str) -> list:
        """GET /documentos/{id}/digitalizados — documentos digitalizados pelo TCE (acervo antigo/físico)."""
        return self._get(f"/documentos/{id_unidade_gestora}/digitalizados")

    def documentos_estaduais(
        self, pagina: int = 1, qtde_por_pagina: int = 100,
        campo_filtro: Optional[str] = None, valor_filtro: Optional[str] = None,
    ) -> list:
        """GET /documentos/estado — documentos estaduais em geral (não filtrado por órgão)."""
        params = {"pagina": pagina, "qtdePorPagina": qtde_por_pagina}
        if campo_filtro:
            params["campoFiltro"] = campo_filtro
            params["valorFiltro"] = valor_filtro
        return self._get("/documentos/estado", params=params)

    def quantidade_documentos_orgao(
        self, id_unidade_gestora: str,
        campo_filtro: Optional[str] = None, valor_filtro: Optional[str] = None,
    ) -> Any:
        """GET /documentos/{id}/quantidadeTotal — total de documentos do órgão (respeita filtros opcionais)."""
        params = {}
        if campo_filtro:
            params["campoFiltro"] = campo_filtro
            params["valorFiltro"] = valor_filtro
        return self._get(f"/documentos/{id_unidade_gestora}/quantidadeTotal", params=params)
