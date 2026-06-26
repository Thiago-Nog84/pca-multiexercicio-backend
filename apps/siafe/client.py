"""
Cliente HTTP para a API do SIAFE-PI.
Documentação: https://tesouro.sefaz.pi.gov.br/siafe-api/swagger-ui.html

Autenticação:
  POST /auth  { "usuario": "...", "senha": "..." }
  → Bearer token usado em todos os demais endpoints.

O cliente gerencia o token automaticamente via Django cache
(TTL configurável em settings.SIAFE_TOKEN_TTL_SECONDS, padrão: 50 min).
"""

import logging
from typing import Any

import requests
from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)

BASE_URL = getattr(settings, "SIAFE_BASE_URL", "https://tesouro.sefaz.pi.gov.br/siafe-api")
CACHE_KEY = "siafe_bearer_token"
TOKEN_TTL = getattr(settings, "SIAFE_TOKEN_TTL_SECONDS", 3000)  # 50 min


class SiafeAPIError(Exception):
    """Exceção para erros retornados pela API do SIAFE."""

    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"SIAFE {status_code}: {detail}")


class SiafeClient:
    """
    Cliente reutilizável para a API REST do SIAFE-PI.

    Uso:
        client = SiafeClient()
        empenhos = client.nota_empenho_por_ug(exercicio=2025, codigo_ug="260001")
    """

    def __init__(self):
        self.base_url = BASE_URL.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})

    # ------------------------------------------------------------------
    # Autenticação
    # ------------------------------------------------------------------

    def _obter_token(self) -> str:
        """Retorna o Bearer token, buscando do cache ou autenticando novamente."""
        token = cache.get(CACHE_KEY)
        if token:
            return token

        usuario = getattr(settings, "SIAFE_USUARIO", "")
        senha = getattr(settings, "SIAFE_SENHA", "")

        if not usuario or not senha:
            raise SiafeAPIError(0, "Credenciais SIAFE não configuradas (SIAFE_USUARIO / SIAFE_SENHA).")

        resp = self.session.post(
            f"{self.base_url}/auth",
            json={"usuario": usuario, "senha": senha},
            timeout=15,
        )
        self._check_response(resp)

        # A API retorna o token na resposta — pode ser string direta ou JSON com campo token/access
        try:
            data = resp.json()
            token = (
                data.get("token")
                or data.get("access")
                or data.get("accessToken")
                or (data if isinstance(data, str) else None)
            )
        except Exception:
            token = resp.text.strip().strip('"')

        if not token:
            raise SiafeAPIError(200, "Token não encontrado na resposta de autenticação.")

        cache.set(CACHE_KEY, token, TOKEN_TTL)
        logger.info("SIAFE: novo token obtido e armazenado em cache.")
        return token

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self._obter_token()}"}

    def _check_response(self, resp: requests.Response) -> None:
        if resp.status_code == 401:
            cache.delete(CACHE_KEY)  # Token expirou — força nova autenticação
        if not resp.ok:
            try:
                detail = resp.json()
            except Exception:
                detail = resp.text[:300]
            raise SiafeAPIError(resp.status_code, str(detail))

    def _get(self, path: str, **params) -> Any:
        """GET autenticado. Retenta uma vez se o token expirou (401)."""
        url = f"{self.base_url}{path}"
        for tentativa in range(2):
            resp = self.session.get(url, headers=self._headers(), params=params or None, timeout=30)
            if resp.status_code == 401 and tentativa == 0:
                cache.delete(CACHE_KEY)
                continue
            self._check_response(resp)
            return resp.json()
        raise SiafeAPIError(401, "Falha de autenticação após retry.")

    def _post(self, path: str, body: dict) -> Any:
        url = f"{self.base_url}{path}"
        resp = self.session.post(url, headers=self._headers(), json=body, timeout=30)
        self._check_response(resp)
        return resp.json()

    # ------------------------------------------------------------------
    # Nota de Empenho
    # ------------------------------------------------------------------

    def nota_empenho_por_ug(self, exercicio: int, codigo_ug: str) -> list:
        """
        GET /nota-empenho/{exercicio}/{codigoUG}
        Lista todas as notas de empenho de uma UG no exercício.
        """
        return self._get(f"/nota-empenho/{exercicio}/{codigo_ug}")

    def nota_empenho_por_ug_mes(self, exercicio: int, codigo_ug: str, mes: int) -> list:
        """
        GET /nota-empenho/{exercicio}/{codigoUG}/{mes}
        Lista notas de empenho filtradas por mês.
        """
        return self._get(f"/nota-empenho/{exercicio}/{codigo_ug}/{mes}")

    def nota_empenho_paginado(self, exercicio: int, pagina: int = 1, total_por_pagina: int = 50) -> dict:
        """
        GET /nota-empenho/{exercicio}/{pagina}/{totalRegistroPagina}
        Listagem paginada de empenhos do exercício.
        """
        return self._get(f"/nota-empenho/{exercicio}/{pagina}/{total_por_pagina}")

    # ------------------------------------------------------------------
    # Saldo Orçamentário
    # ------------------------------------------------------------------

    def saldo_orcamentario_anual(self, exercicio: int, codigo_ug: str) -> dict:
        """
        GET /saldo-orcamentario/anual/{exercicio}/{codigoUG}
        Saldo orçamentário consolidado anual de uma UG.
        Usado para validar dotação antes de abrir licitação.
        """
        return self._get(f"/saldo-orcamentario/anual/{exercicio}/{codigo_ug}")

    def saldo_orcamentario_mensal(self, exercicio: int, mes: int) -> list:
        """
        GET /saldo-orcamentario/{exercicio}/{mes}
        Saldo orçamentário de todas as UGs no mês informado.
        """
        return self._get(f"/saldo-orcamentario/{exercicio}/{mes}")

    # ------------------------------------------------------------------
    # Estrutura Classificatória — Apoio Geral
    # ------------------------------------------------------------------

    def acoes(self, exercicio: int) -> list:
        """GET /apoio-geral/acao/{exercicio} — Ações de governo ativas."""
        return self._get(f"/apoio-geral/acao/{exercicio}")

    def acao(self, exercicio: int, codigo_acao: str) -> dict:
        """GET /apoio-geral/acao/{exercicio}/{codigoAcao}"""
        return self._get(f"/apoio-geral/acao/{exercicio}/{codigo_acao}")

    def naturezas_despesa(self, exercicio: int) -> list:
        """GET /apoio-geral/natureza-despesa-com-subitem/{exercicio}"""
        return self._get(f"/apoio-geral/natureza-despesa-com-subitem/{exercicio}")

    def elementos_despesa(self, exercicio: int) -> list:
        """GET /apoio-geral/elemento-despesa/{exercicio}"""
        return self._get(f"/apoio-geral/elemento-despesa/{exercicio}")

    def grupos_natureza_despesa(self, exercicio: int) -> list:
        """GET /apoio-geral/grupo-natureza-despesa/{exercicio}"""
        return self._get(f"/apoio-geral/grupo-natureza-despesa/{exercicio}")

    def programas(self, exercicio: int) -> list:
        """GET /apoio-geral/programa/{exercicio} — Programas orçamentários."""
        return self._get(f"/apoio-geral/programa/{exercicio}")

    def credores(self, exercicio: int, pagina: int = 1, total_por_pagina: int = 100) -> dict:
        """GET /apoio-geral/credor/{exercicio}/{pagina}/{totalRegistroPagina}"""
        return self._get(f"/apoio-geral/credor/{exercicio}/{pagina}/{total_por_pagina}")

    def credor(self, exercicio: int, codigo: str) -> dict:
        """GET /apoio-geral/credor/{exercicio}/{codigo}"""
        return self._get(f"/apoio-geral/credor/{exercicio}/{codigo}")

    def domicilios_bancarios(self, exercicio: int, codigo_ug: str) -> list:
        """GET /apoio-execucao/domicilio-bancario/{exercicio}/{codigoUG}"""
        return self._get(f"/apoio-execucao/domicilio-bancario/{exercicio}/{codigo_ug}")

    # ------------------------------------------------------------------
    # Saldo Contábil
    # ------------------------------------------------------------------

    def saldo_contabil_mensal(self, exercicio: int, mes: int, conta: str, codigo_ug: str) -> dict:
        """GET /saldo-contabil/{exercicio}/{mes}/{conta}/{codigoUG}"""
        return self._get(f"/saldo-contabil/{exercicio}/{mes}/{conta}/{codigo_ug}")

    def saldo_contabil_acumulado(self, exercicio: int, data: str, contas: str, codigo_ug: str) -> dict:
        """
        GET /saldo-contabil-acumulado/{exercicio}/{data}/{contas}/{codigoUG}
        data: formato YYYY-MM-DD
        contas: código(s) de conta contábil
        """
        return self._get(f"/saldo-contabil-acumulado/{exercicio}/{data}/{contas}/{codigo_ug}")

    # ------------------------------------------------------------------
    # Contratos e Convênios
    # ------------------------------------------------------------------

    def contrato(self, exercicio: int, codigo_contrato: str) -> dict:
        """
        GET /contrato/{exercicio}/{codigoContrato}
        Consulta um contrato SIAFE pelo código. Útil para conciliar com o
        Contrato do sistema e detectar divergências de valor ou prazo.
        """
        return self._get(f"/contrato/{exercicio}/{codigo_contrato}")

    def contratos_paginado(self, exercicio: int, pagina: int = 1, total_por_pagina: int = 50, filtros: dict = None) -> dict:
        """
        POST /contrato/{exercicio}/{pagina}/{totalRegistroPagina}
        Listagem paginada de contratos do exercício com filtros opcionais.
        """
        return self._post(f"/contrato/{exercicio}/{pagina}/{total_por_pagina}", filtros or {})

    def consultar_contrato(self, exercicio: int, filtros: dict) -> dict:
        """
        POST /contrato/consulta/{exercicio}
        Consulta por código do contrato ou número original.
        filtros: { "codigoContrato": "...", "numeroOriginal": "..." }
        """
        return self._post(f"/contrato/consulta/{exercicio}", filtros)

    def convenio(self, exercicio: int, codigo_convenio: str) -> dict:
        """
        GET /convenio/{exercicio}/{codigoConvenio}
        Consulta um convênio SIAFE pelo código.
        """
        return self._get(f"/convenio/{exercicio}/{codigo_convenio}")

    def convenios_paginado(self, exercicio: int, pagina: int = 1, total_por_pagina: int = 50, filtros: dict = None) -> dict:
        """
        POST /convenio/{exercicio}/{pagina}/{totalRegistroPagina}
        Listagem paginada de convênios do exercício.
        """
        return self._post(f"/convenio/{exercicio}/{pagina}/{total_por_pagina}", filtros or {})

    # ------------------------------------------------------------------
    # Execução Orçamentária — Liquidação e Reserva
    # ------------------------------------------------------------------

    def notas_liquidacao_por_ug(self, exercicio: int, codigo_ug: str) -> list:
        """
        GET /nota-liquidacao/{exercicio}/{codigoUG}
        Lista notas de liquidação de uma UG. Representa o segundo estágio
        da despesa (reconhecimento da obrigação após entrega do bem/serviço).
        Vincula-se diretamente a contratos e ordens de fornecimento.
        """
        return self._get(f"/nota-liquidacao/{exercicio}/{codigo_ug}")

    def notas_liquidacao_paginado(self, exercicio: int, pagina: int = 1, total_por_pagina: int = 50, filtros: dict = None) -> dict:
        """
        POST /nota-liquidacao/{exercicio}/{pagina}/{totalRegistroPagina}
        Listagem paginada de liquidações com filtros.
        """
        return self._post(f"/nota-liquidacao/{exercicio}/{pagina}/{total_por_pagina}", filtros or {})

    def notas_reserva_por_ug(self, exercicio: int, codigo_ug: str) -> list:
        """
        GET /nota-reserva/{exercicio}/{codigoUG}
        Lista notas de reserva orçamentária de uma UG.
        Reserva de dotação antes do empenho — usado para validar PCA.
        """
        return self._get(f"/nota-reserva/{exercicio}/{codigo_ug}")

    def despesas_transacao_paginado(self, exercicio: int, pagina: int = 1, total_por_pagina: int = 50, filtros: dict = None) -> dict:
        """
        POST /despesa-transacao/{exercicio}/{pagina}/{totalRegistroPagina}
        Consulta transações de despesa com filtros (natureza, UG, período).
        """
        return self._post(f"/despesa-transacao/{exercicio}/{pagina}/{total_por_pagina}", filtros or {})

    # ------------------------------------------------------------------
    # Execução Financeira — Ordens Bancárias por Credor
    # ------------------------------------------------------------------

    def ob_orcamentaria_por_credor(
        self, exercicio: int, codigo_credor: str,
        data_inicio: str, data_fim: str = None
    ) -> list:
        """
        GET /credor-ob-orcamentaria/{exercicio}/{codigoCredor}/{dataContInicio}[/{dataContFim}]
        Ordens Bancárias orçamentárias contabilizadas por credor e período.
        data_inicio / data_fim: formato YYYY-MM-DD
        Permite rastrear pagamentos efetivados para um fornecedor de contrato.
        """
        if data_fim:
            return self._get(f"/credor-ob-orcamentaria/{exercicio}/{codigo_credor}/{data_inicio}/{data_fim}")
        return self._get(f"/credor-ob-orcamentaria/{exercicio}/{codigo_credor}/{data_inicio}")

    def ob_extra_orcamentaria_por_credor(
        self, exercicio: int, codigo_credor: str,
        data_inicio: str, data_fim: str = None
    ) -> list:
        """
        GET /credor-ob-extra-orcamentaria/{exercicio}/{codigoCredor}/{dataContInicio}[/{dataContFim}]
        Ordens Bancárias extra-orçamentárias (retenções devolvidas, cauções).
        """
        if data_fim:
            return self._get(f"/credor-ob-extra-orcamentaria/{exercicio}/{codigo_credor}/{data_inicio}/{data_fim}")
        return self._get(f"/credor-ob-extra-orcamentaria/{exercicio}/{codigo_credor}/{data_inicio}")

    def ob_retencao_por_credor(
        self, exercicio: int, codigo_credor: str,
        data_inicio: str, data_fim: str = None
    ) -> list:
        """
        GET /credor-ob-retencao/{exercicio}/{codigoCredor}/{dataContInicio}[/{dataContFim}]
        Ordens Bancárias de retenção (INSS, ISS, IR) por credor.
        """
        if data_fim:
            return self._get(f"/credor-ob-retencao/{exercicio}/{codigo_credor}/{data_inicio}/{data_fim}")
        return self._get(f"/credor-ob-retencao/{exercicio}/{codigo_credor}/{data_inicio}")

    # ------------------------------------------------------------------
    # Fatos de Contratos — envio bidirecional ao SIAFE
    # ------------------------------------------------------------------

    def fato_reserva_orcamentaria(self, exercicio: int, payload: dict) -> dict:
        """
        POST /fatos-contratos/reserva-orcamentaria/{exercicio}
        Registra no SIAFE uma reserva orçamentária vinculada a contrato.
        Deve ser chamado ao aprovar um ItemPCA para garantir dotação.
        payload: { "reservaOrcamentaria": {...}, "contrato": {...} }
        """
        return self._post(f"/fatos-contratos/reserva-orcamentaria/{exercicio}", payload)

    def fato_aquisicao(self, exercicio: int, payload: dict) -> dict:
        """
        POST /fatos-contratos/aquisicao/{exercicio}
        Registra aquisição de material/serviço vinculada a contrato no SIAFE.
        Acionado ao criar uma Ordem de Fornecimento no sistema.
        """
        return self._post(f"/fatos-contratos/aquisicao/{exercicio}", payload)

    def fato_solicitacao_consumo(self, exercicio: int, payload: dict) -> dict:
        """
        POST /fatos-contratos/solicitacao-consumo/{exercicio}
        Registra solicitação de consumo de material no SIAFE.
        """
        return self._post(f"/fatos-contratos/solicitacao-consumo/{exercicio}", payload)

    def fato_ordem_servico(self, exercicio: int, payload: dict) -> dict:
        """
        POST /fatos-contratos/contabilizar-ordem-servico/{exercicio}
        Contabiliza no SIAFE uma ordem de serviço emitida contra contrato.
        """
        return self._post(f"/fatos-contratos/contabilizar-ordem-servico/{exercicio}", payload)

    def fato_aprovacao_fiscal(self, exercicio: int, payload: dict) -> dict:
        """
        POST /fatos-contratos/contabilizar-aprovacao-fiscal/{exercicio}
        Registra aprovação do fiscal do contrato para fins de liquidação.
        """
        return self._post(f"/fatos-contratos/contabilizar-aprovacao-fiscal/{exercicio}", payload)

    def fato_encerramento_aquisicao(self, exercicio: int, payload: dict) -> dict:
        """
        POST /fatos-contratos/encerramento-aquisicao/{exercicio}
        Registra o encerramento de uma aquisição (finalização do contrato).
        """
        return self._post(f"/fatos-contratos/encerramento-aquisicao/{exercicio}", payload)

    def fato_anulacao_np(self, exercicio: int, payload: dict) -> dict:
        """
        POST /fatos-contratos/anulacao-np/{exercicio}
        Anula uma nota de pagamento vinculada a contrato no SIAFE.
        """
        return self._post(f"/fatos-contratos/anulacao-np/{exercicio}", payload)

    # ------------------------------------------------------------------
    # Planejamento LOA
    # ------------------------------------------------------------------

    def consultar_meta_acao(self, exercicio: int, filtros: dict) -> dict:
        """
        POST /planejamento/acompanhamento/consulta/meta-acao/{exercicio}
        Consulta metas e ações do planejamento LOA por exercício.
        Permite cruzar os itens do PCA com as metas físicas aprovadas na LOA.
        filtros: { "codigoPrograma": "...", "codigoAcao": "...", ... }
        """
        return self._post(f"/planejamento/acompanhamento/consulta/meta-acao/{exercicio}", filtros)

    def proposta_despesa_loa(self, exercicio: int, payload: dict) -> dict:
        """
        POST /planejamento-ppa/proposta-despesa/{exercicio}
        Envia proposta de despesa ao planejamento LOA/PPA.
        """
        return self._post(f"/planejamento-ppa/proposta-despesa/{exercicio}", payload)

    def definir_limite_orcamento(self, exercicio: int, payload: dict) -> dict:
        """
        POST /planejamento-ppa/definicao-limite-orcamento/{exercicio}
        Define limites de orçamento por UG para o exercício.
        """
        return self._post(f"/planejamento-ppa/definicao-limite-orcamento/{exercicio}", payload)
