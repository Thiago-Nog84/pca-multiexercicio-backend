"""
Consulta ao catálogo oficial do Governo Federal (CATMAT / CATSER).

Fonte: https://dadosabertos.compras.gov.br (API pública, sem autenticação)

Para que serve
--------------
O catálogo interno do MPPI guarda códigos PDM (materiais) e CATSER (serviços).
Este serviço permite VALIDAR esses códigos contra a base oficial na hora da
curadoria — confirmando que o código existe, qual a descrição/classe oficial
e, no caso de PDM, quais itens específicos ele agrupa.

Descobertas relevantes (verificadas contra a API em 2026-07-21)
---------------------------------------------------------------
1. Um item CATMAT tem DOIS códigos: `codigoItem` (específico) e `codigoPdm`
   (o "padrão descritivo" que agrupa variações). Ex.: o item 463989
   ("AÇÚCAR, TIPO: CRISTAL, PRAZO VALIDADE MÍNIMO: 12 MESES") pertence ao
   PDM 19777 ("AÇÚCAR"), que agrupa 13 itens distintos.
   É por isso que o histórico do PCA (que grava codigoItem) não casava com o
   catálogo interno (que grava PDM) — são níveis diferentes, não erro de dado.
2. A API NÃO faz busca por descrição livre (`descricaoItem=ACUCAR` → 0
   resultados). Só busca por código ou navegação por grupo/classe.
3. `tamanhoPagina` deve ficar entre 10 e 500 — valores fora disso dão HTTP 400.
4. O endpoint de grupos de serviço (`3_consultarGrupoServico`) FUNCIONA.
   Não é necessário manter lista de grupos hardcoded como fallback.
5. Itens de serviço estão em `6_consultarItemServico` (o `5_` retorna 404).

Uso:
    from apps.pca.services.catalogo_gov import validar_codigo

    resultado = validar_codigo("19777")          # tenta PDM, item e CATSER
    resultado = validar_codigo("27502", "CATSER")
"""

import hashlib
import logging
import re
import time

import requests
from django.core.cache import cache

logger = logging.getLogger(__name__)

BASE_URL = "https://dadosabertos.compras.gov.br"
TIMEOUT = 20
CACHE_TTL = 60 * 60 * 24  # 24h — catálogo oficial é dado de referência estável
PAGINA_MIN = 10           # a API rejeita tamanhoPagina < 10 ou > 500
MAX_TENTATIVAS_429 = 4    # a API aplica rate limit e informa quantos segundos esperar


class CatalogoGovIndisponivel(Exception):
    """A API oficial não respondeu ou devolveu erro — trate como indisponibilidade."""


def _get(caminho, params=None):
    """GET com timeout, cache e erro tipado."""
    params = params or {}
    # Hash da assinatura: a chave crua tem caracteres (":" "/" espaços) que
    # quebram backends como o memcached.
    assinatura = f"{caminho}:{sorted(params.items())}".encode()
    chave = "catgov:" + hashlib.md5(assinatura).hexdigest()
    em_cache = cache.get(chave)
    if em_cache is not None:
        return em_cache

    url = f"{BASE_URL}/{caminho}"

    for tentativa in range(1, MAX_TENTATIVAS_429 + 1):
        try:
            resp = requests.get(url, params=params, timeout=TIMEOUT,
                                headers={"Accept": "application/json"})
        except requests.RequestException as e:
            logger.warning("Catálogo gov indisponível (%s): %s", caminho, e)
            raise CatalogoGovIndisponivel(str(e)) from e

        # A API aplica rate limit e diz quantos segundos esperar na mensagem:
        # {"statusCode":429,"message":"Rate limit is exceeded. Try again in 10 seconds."}
        if resp.status_code == 429:
            if tentativa == MAX_TENTATIVAS_429:
                raise CatalogoGovIndisponivel("rate limit excedido (HTTP 429)")
            espera = 2 * tentativa
            m = re.search(r"in (\d+) second", resp.text or "")
            if m:
                espera = int(m.group(1)) + 1
            logger.info("Rate limit da API oficial; aguardando %ss (tentativa %s)",
                        espera, tentativa)
            time.sleep(espera)
            continue
        break

    if resp.status_code == 404:
        return {"resultado": [], "totalRegistros": 0}
    if not resp.ok:
        logger.warning("Catálogo gov HTTP %s em %s: %s",
                       resp.status_code, caminho, resp.text[:200])
        raise CatalogoGovIndisponivel(f"HTTP {resp.status_code}")

    try:
        dados = resp.json()
    except ValueError as e:
        raise CatalogoGovIndisponivel("resposta não-JSON da API") from e

    cache.set(chave, dados, CACHE_TTL)
    return dados


# ---------------------------------------------------------------------------
# Consultas específicas
# ---------------------------------------------------------------------------

def consultar_item_material(codigo_item):
    """Item CATMAT específico pelo `codigoItem`. Retorna dict ou None."""
    dados = _get("modulo-material/4_consultarItemMaterial",
                 {"codigoItem": codigo_item})
    resultado = dados.get("resultado") or []
    return resultado[0] if resultado else None


def consultar_itens_por_pdm(codigo_pdm, limite=PAGINA_MIN):
    """
    Itens CATMAT que pertencem a um PDM (padrão descritivo).
    Retorna (lista_de_itens, total_de_registros).
    """
    dados = _get(
        "modulo-material/4_consultarItemMaterial",
        {"codigoPdm": codigo_pdm, "pagina": 1,
         "tamanhoPagina": max(limite, PAGINA_MIN)},
    )
    return dados.get("resultado") or [], dados.get("totalRegistros") or 0


def consultar_item_servico(codigo_servico):
    """Item CATSER pelo `codigoServico`. Retorna dict ou None."""
    dados = _get(
        "modulo-servico/6_consultarItemServico",
        {"codigoServico": codigo_servico, "pagina": 1, "tamanhoPagina": PAGINA_MIN},
    )
    resultado = dados.get("resultado") or []
    return resultado[0] if resultado else None


def listar_grupos(tipo="CATMAT"):
    """Grupos do catálogo. `tipo`: CATMAT ou CATSER."""
    if tipo.upper() == "CATSER":
        dados = _get("modulo-servico/3_consultarGrupoServico",
                     {"pagina": 1, "tamanhoPagina": 500})
        return [
            {"codigo": g.get("codigoGrupo"), "nome": g.get("nomeGrupo"),
             "divisao": g.get("nomeDivisao")}
            for g in (dados.get("resultado") or [])
        ]
    dados = _get("modulo-material/1_consultarGrupoMaterial")
    return [
        {"codigo": g.get("codigoGrupo"), "nome": g.get("nomeGrupo")}
        for g in (dados.get("resultado") or [])
        if g.get("statusGrupo") is not False
    ]


def listar_itens_do_grupo(codigo_grupo, tipo="CATMAT", pagina=1, tamanho=50):
    """Itens de um grupo — para navegação quando não se sabe o código."""
    tamanho = min(max(tamanho, PAGINA_MIN), 500)
    if tipo.upper() == "CATSER":
        caminho = "modulo-servico/6_consultarItemServico"
    else:
        caminho = "modulo-material/4_consultarItemMaterial"
    dados = _get(caminho, {"codigoGrupo": codigo_grupo,
                           "pagina": pagina, "tamanhoPagina": tamanho})
    return dados.get("resultado") or [], dados.get("totalRegistros") or 0


# ---------------------------------------------------------------------------
# Validação (o caso de uso principal da curadoria)
# ---------------------------------------------------------------------------

def validar_codigo(codigo, tipo=None):
    """
    Verifica se um código do catálogo interno existe na base oficial.

    Como o catálogo do MPPI mistura PDM (materiais) e CATSER (serviços) na
    mesma coluna, quando `tipo` não é informado tenta nesta ordem:
        1. PDM de material   (caso mais comum no nosso catálogo)
        2. Item CATMAT específico
        3. Item CATSER

    Retorna dict com:
        encontrado, nivel ('pdm'|'item_catmat'|'catser'), codigo,
        descricao, classe, grupo, itens_no_pdm (só para PDM), erro
    """
    codigo = str(codigo).strip()
    if not codigo.isdigit():
        return {"encontrado": False, "erro": "Código deve ser numérico.",
                "codigo": codigo}

    tipos = [tipo.upper()] if tipo else ["CATMAT", "CATSER"]

    try:
        if "CATMAT" in tipos:
            # 1. Como PDM (agrupador) — nível que o nosso catálogo usa
            itens, total = consultar_itens_por_pdm(codigo)
            if itens:
                primeiro = itens[0]
                return {
                    "encontrado": True,
                    "nivel": "pdm",
                    "tipo": "CATMAT",
                    "codigo": codigo,
                    "descricao": primeiro.get("nomePdm") or "",
                    "classe": primeiro.get("nomeClasse") or "",
                    "grupo": primeiro.get("nomeGrupo") or "",
                    "itens_no_pdm": total,
                    "exemplos": [
                        {"codigo_item": i.get("codigoItem"),
                         "descricao": i.get("descricaoItem")}
                        for i in itens[:5]
                    ],
                }

            # 2. Como item CATMAT específico
            item = consultar_item_material(codigo)
            if item:
                return {
                    "encontrado": True,
                    "nivel": "item_catmat",
                    "tipo": "CATMAT",
                    "codigo": codigo,
                    "descricao": item.get("descricaoItem") or "",
                    "classe": item.get("nomeClasse") or "",
                    "grupo": item.get("nomeGrupo") or "",
                    "codigo_pdm": item.get("codigoPdm"),
                    "nome_pdm": item.get("nomePdm"),
                }

        if "CATSER" in tipos:
            servico = consultar_item_servico(codigo)
            if servico:
                return {
                    "encontrado": True,
                    "nivel": "catser",
                    "tipo": "CATSER",
                    "codigo": codigo,
                    "descricao": (servico.get("nomeItemServico")
                                  or servico.get("descricaoItem")
                                  or servico.get("nomeClasse") or ""),
                    "classe": servico.get("nomeClasse") or "",
                    "grupo": servico.get("nomeGrupo") or "",
                    "divisao": servico.get("nomeDivisao") or "",
                }

    except CatalogoGovIndisponivel as e:
        return {"encontrado": None, "codigo": codigo,
                "erro": f"API oficial indisponível: {e}"}

    return {"encontrado": False, "codigo": codigo,
            "erro": "Código não encontrado no catálogo oficial."}
