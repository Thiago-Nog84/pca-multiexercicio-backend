"""
ComprasnetContratosClient
=========================
Cliente HTTP para a API pública e autenticada do Comprasnet Contratos.
Documentação: https://contratos.comprasnet.gov.br/api/docs

Endpoints públicos (sem auth):
    GET /api/contrato/ug/{uasg}              → contratos ativos da UG
    GET /api/contrato/inativo/ug/{uasg}      → contratos inativos da UG
    GET /api/contrato/{id}/itens             → itens do contrato
    GET /api/contrato/{id}/empenhos          → empenhos do contrato
    GET /api/contrato/{id}/historico         → histórico do contrato

Endpoints v1 autenticados (JWT):
    POST /api/v1/auth/login                                      → obtém token
    GET  /api/v1/empenho/pdm/{pdm}/ug/{uasg}/ano/{ano}          → empenhos por PDM
    GET  /api/v1/empenho/codigoservico/{cod}/ug/{uasg}/ano/{ano} → empenhos por CATSER
    GET  /api/v1/empenho/ano/{ano}/ug/{uasg}                     → todos os empenhos da UG no ano
    GET  /api/v1/empenho/ug/{uasg}                               → todos os empenhos ativos
    POST /api/v1/comprasnet/compras/impedimentos                 → verifica vínculos ARP/contrato/empenho
    GET  /api/v1/contrato/ug/{uasg}                              → versão v1 com mais campos
    GET  /api/v1/contrato/{id}/itens                             → itens v1

Autenticação:
    O token JWT é obtido via POST /api/v1/auth/login com CPF e senha de usuário
    SISG/Comprasnet. As credenciais são configuradas em settings.py via variáveis
    de ambiente COMPRASNET_CONTRATOS_CPF e COMPRASNET_CONTRATOS_SENHA.

    O token é armazenado em memória e reutilizado enquanto válido. Em caso de
    erro 401, o cliente reautentica automaticamente (uma tentativa).

Exemplo de uso:
    from apps.srp.services.comprasnet_contratos import ComprasnetContratosClient

    client = ComprasnetContratosClient()
    contratos = client.get_contratos_ug("926092")
    for c in contratos:
        itens = client.get_contrato_itens(c["id"])

    # Com autenticação (requer credenciais no .env)
    empenhos = client.get_empenhos_pdm(pdm="614404", uasg="926092", ano=2026)
"""

import logging
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

BASE_URL = "https://contratos.comprasnet.gov.br"
TIMEOUT = 30


class ComprasnetContratosError(Exception):
    """Erro genérico da API Comprasnet Contratos."""
    pass


class ComprasnetContratosAuthError(ComprasnetContratosError):
    """Credenciais inválidas ou ausentes."""
    pass


class ComprasnetContratosClient:
    """
    Cliente para a API do Comprasnet Contratos.

    Instanciar com credenciais explícitas ou ler de settings:
        client = ComprasnetContratosClient()                   # usa settings
        client = ComprasnetContratosClient(cpf="...", senha="...")
    """

    def __init__(self, cpf: str = None, senha: str = None):
        self.cpf = cpf or getattr(settings, "COMPRASNET_CONTRATOS_CPF", "")
        self.senha = senha or getattr(settings, "COMPRASNET_CONTRATOS_SENHA", "")
        self._token: str | None = None
        self._token_expiry: datetime | None = None
        self._session = requests.Session()
        self._session.headers.update({
            "Accept": "application/json",
            "Content-Type": "application/json",
        })

    # ------------------------------------------------------------------
    # Autenticação
    # ------------------------------------------------------------------

    def authenticate(self) -> str:
        """
        Autentica via POST /api/v1/auth/login.
        Retorna o token JWT e o armazena internamente.
        """
        if not self.cpf or not self.senha:
            raise ComprasnetContratosAuthError(
                "Credenciais não configuradas. "
                "Defina COMPRASNET_CONTRATOS_CPF e COMPRASNET_CONTRATOS_SENHA no .env, "
                "ou passe cpf= e senha= ao instanciar o cliente."
            )

        url = f"{BASE_URL}/api/v1/auth/login"
        try:
            resp = self._session.post(
                url,
                json={"username": self.cpf, "password": self.senha},
                timeout=TIMEOUT,
            )
            resp.raise_for_status()
        except requests.HTTPError as exc:
            if exc.response is not None and exc.response.status_code == 401:
                raise ComprasnetContratosAuthError(
                    "Credenciais inválidas para a API Comprasnet Contratos."
                ) from exc
            raise ComprasnetContratosError(f"Erro HTTP ao autenticar: {exc}") from exc
        except requests.RequestException as exc:
            raise ComprasnetContratosError(f"Erro de conexão ao autenticar: {exc}") from exc

        data = resp.json()
        token = data.get("token") or data.get("access") or data.get("access_token") or ""
        if not token:
            raise ComprasnetContratosAuthError(
                f"Token não encontrado na resposta de login: {list(data.keys())}"
            )

        self._token = token
        self._session.headers["Authorization"] = f"Bearer {token}"
        logger.info("Autenticado no Comprasnet Contratos com sucesso.")
        return token

    def _ensure_authenticated(self):
        """Garante que há um token válido, autenticando se necessário."""
        if not self._token:
            self.authenticate()

    # ------------------------------------------------------------------
    # HTTP helpers
    # ------------------------------------------------------------------

    def _get(self, path: str, auth: bool = False, retry_auth: bool = True, **params) -> list | dict:
        """
        Faz GET em `path`. Se `auth=True`, inclui JWT e tenta reautenticar em 401.
        Parâmetros de query são passados como kwargs.
        """
        if auth:
            self._ensure_authenticated()

        url = f"{BASE_URL}{path}"
        try:
            resp = self._session.get(url, params=params or None, timeout=TIMEOUT)
        except requests.RequestException as exc:
            raise ComprasnetContratosError(f"Erro de conexão em {path}: {exc}") from exc

        if resp.status_code == 401 and auth and retry_auth:
            logger.warning("Token expirado, reautenticando...")
            self._token = None
            self.authenticate()
            return self._get(path, auth=auth, retry_auth=False, **params)

        if not resp.ok:
            raise ComprasnetContratosError(
                f"Erro HTTP {resp.status_code} em {path}: {resp.text[:200]}"
            )

        if not resp.content:
            return []

        try:
            return resp.json()
        except Exception:
            return []

    def _post(self, path: str, payload: dict, retry_auth: bool = True) -> list | dict:
        """POST autenticado."""
        self._ensure_authenticated()
        url = f"{BASE_URL}{path}"
        try:
            resp = self._session.post(url, json=payload, timeout=TIMEOUT)
        except requests.RequestException as exc:
            raise ComprasnetContratosError(f"Erro de conexão em {path}: {exc}") from exc

        if resp.status_code == 401 and retry_auth:
            self._token = None
            self.authenticate()
            return self._post(path, payload, retry_auth=False)

        if not resp.ok:
            raise ComprasnetContratosError(
                f"Erro HTTP {resp.status_code} em {path}: {resp.text[:200]}"
            )

        return resp.json() if resp.content else {}

    # ------------------------------------------------------------------
    # Endpoints públicos
    # ------------------------------------------------------------------

    def get_contratos_ug(self, uasg: str, ativos: bool = True) -> list[dict]:
        """
        Retorna contratos de uma UG.
        GET /api/contrato/ug/{uasg}         → ativos
        GET /api/contrato/inativo/ug/{uasg} → inativos
        """
        if ativos:
            path = f"/api/contrato/ug/{uasg}"
        else:
            path = f"/api/contrato/inativo/ug/{uasg}"
        result = self._get(path)
        return result if isinstance(result, list) else []

    def get_contrato_by_id(self, contrato_id: int) -> dict:
        """GET /api/contrato/id/{contrato_id}"""
        result = self._get(f"/api/contrato/id/{contrato_id}")
        return result if isinstance(result, dict) else {}

    def get_contrato_itens(self, contrato_id: int) -> list[dict]:
        """GET /api/contrato/{id}/itens"""
        result = self._get(f"/api/contrato/{contrato_id}/itens")
        return result if isinstance(result, list) else []

    def get_contrato_empenhos(self, contrato_id: int) -> list[dict]:
        """GET /api/contrato/{id}/empenhos"""
        result = self._get(f"/api/contrato/{contrato_id}/empenhos")
        return result if isinstance(result, list) else []

    def get_contrato_historico(self, contrato_id: int) -> list[dict]:
        """GET /api/contrato/{id}/historico"""
        result = self._get(f"/api/contrato/{contrato_id}/historico")
        return result if isinstance(result, list) else []

    def get_contrato_por_uasg_numero(self, uasg: str, numero_contrato: str) -> dict:
        """GET /api/contrato/ugorigem/{uasg}/numeroano/{numero}"""
        result = self._get(f"/api/contrato/ugorigem/{uasg}/numeroano/{numero_contrato}")
        return result if isinstance(result, dict) else {}

    # ------------------------------------------------------------------
    # Endpoints v1 autenticados
    # ------------------------------------------------------------------

    def get_contratos_ug_v1(self, uasg: str) -> list[dict]:
        """GET /api/v1/contrato/ug/{uasg} — versão autenticada com mais campos."""
        result = self._get(f"/api/v1/contrato/ug/{uasg}", auth=True)
        return result if isinstance(result, list) else []

    def get_empenhos_pdm(self, pdm: str, uasg: str, ano: int) -> list[dict]:
        """
        GET /api/v1/empenho/pdm/{pdm}/ug/{uasg}/ano/{ano}
        Retorna empenhos de material por código PDM/CATMAT e UG no ano.
        Requer autenticação JWT.
        """
        result = self._get(f"/api/v1/empenho/pdm/{pdm}/ug/{uasg}/ano/{ano}", auth=True)
        return result if isinstance(result, list) else []

    def get_empenhos_servico(self, codigo: str, uasg: str, ano: int) -> list[dict]:
        """
        GET /api/v1/empenho/codigoservico/{codigo}/ug/{uasg}/ano/{ano}
        Retorna empenhos de serviço por código CATSER e UG no ano.
        Requer autenticação JWT.
        """
        result = self._get(f"/api/v1/empenho/codigoservico/{codigo}/ug/{uasg}/ano/{ano}", auth=True)
        return result if isinstance(result, list) else []

    def get_empenhos_ug_ano(self, uasg: str, ano: int) -> list[dict]:
        """
        GET /api/v1/empenho/ano/{ano}/ug/{uasg}
        Retorna todos os empenhos de uma UG em um ano.
        Requer autenticação JWT.
        """
        result = self._get(f"/api/v1/empenho/ano/{ano}/ug/{uasg}", auth=True)
        return result if isinstance(result, list) else []

    def get_empenhos_ug(self, uasg: str) -> list[dict]:
        """
        GET /api/v1/empenho/ug/{uasg}
        Retorna todos os empenhos ativos de uma UG.
        Requer autenticação JWT.
        """
        result = self._get(f"/api/v1/empenho/ug/{uasg}", auth=True)
        return result if isinstance(result, list) else []

    def check_impedimentos(self, itens_compra: list[dict]) -> dict:
        """
        POST /api/v1/comprasnet/compras/impedimentos
        Verifica se itens de uma compra estão vinculados a Atas, Contratos e/ou Empenhos.
        Requer autenticação JWT.

        Payload esperado:
            [{"numero_item": 1, "id_compra": "12345", ...}]
        """
        return self._post("/api/v1/comprasnet/compras/impedimentos", itens_compra)

    # ------------------------------------------------------------------
    # Utilitários de parse
    # ------------------------------------------------------------------

    @staticmethod
    def parse_decimal(valor) -> Decimal:
        """Converte string monetária brasileira (ex: '1.234,56') para Decimal."""
        if valor is None:
            return Decimal("0")
        s = str(valor).replace(".", "").replace(",", ".").strip()
        try:
            return Decimal(s)
        except InvalidOperation:
            return Decimal("0")

    @staticmethod
    def parse_date(valor) -> date | None:
        """Converte string de data para date."""
        if not valor:
            return None
        s = str(valor)
        for fmt in ["%Y-%m-%d", "%d/%m/%Y", "%Y-%m-%dT%H:%M:%S"]:
            try:
                return datetime.strptime(s[:len(fmt)], fmt).date()
            except ValueError:
                continue
        return None
