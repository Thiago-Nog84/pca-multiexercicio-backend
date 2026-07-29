"""
Serviço: busca automática de quantidades por item de contrato via
dadosabertos.compras.gov.br — Módulo Contratos (12.1/12.2 do manual
"Manual do Usuário — API de Dados Abertos", Compras.gov.br, v2.0 – Fev/26).

Achado (2026-07-24): ao contrário do que a auditoria anterior concluiu
("NÃO existe API pública com quantidade por item de contrato"), essa
conclusão estava certa apenas para o PNCP e para a rota antiga e morta
`/modulo-contrato/1_consultarContrato` (singular). O manual oficial que
Thiago enviou revela a rota REAL, no plural: `/modulo-contratos/...`
(módulo 09 — CONTRATOS), que devolve exatamente `quantidadeItem`,
`valorUnitarioItem` e `valorTotalItem` por contrato + item.

Limitações confirmadas ao vivo:
  - Cobre só contratos com dataVigenciaInicial em 2026 em diante para o
    MPPI (código de órgão 94252 / UASG 926092). Contratos de 2025 (ex:
    71/2025/FPDC) simplesmente não aparecem — dado não retroagido.
  - O parâmetro `numeroContrato` da API usa o formato OFICIAL do SIASG
    (ex: "00036/2026"), que quase nunca bate com o `numero_contrato`
    salvo localmente (ex: "36/2026", "18/2026/PGJ", "28/2026 PGJ") —
    por isso o cruzamento é feito por número normalizado (removendo
    zeros à esquerda e sufixos de unidade) + CNPJ do fornecedor como
    confirmação, nunca só por string crua.
  - Contratos de serviço com posto de trabalho/diária (item sem
    codigo_item_compras_gov local, ex: 18/2026/PGJ) não têm como ser
    casados por código de item — ficam de fora do automático e
    continuam dependendo de OFFICIAL_CONTRACT_ITEMS.

Por segurança (dado usado em dashboard de conformidade), a função
`resolver_itens_para_contrato` só devolve um mapeamento quando TODOS os
itens retornados pela API foram identificados com certeza contra um
ItemARP local. Qualquer ambiguidade retorna None e o chamador cai no
fallback manual/heurístico existente — nunca adivinha.

------------------------------------------------------------------------
resolver_quantidade_por_valor_homologado (2026-07-28)
------------------------------------------------------------------------
Segunda fonte automática, complementar à acima, usando a API PÚBLICA DO
PNCP (pncp.gov.br, não dadosabertos.compras.gov.br) — cobre contratos de
QUALQUER ano (a limitação de "só 2026+" do Módulo Contratos acima não se
aplica aqui), incluindo os que o Módulo Contratos não alcança.

Lógica: numa ARP, o preço unitário de cada item é fixo no momento da
homologação (`valorUnitarioHomologado`, devolvido por
`GET /orgaos/{cnpj}/compras/{ano}/{compra}/itens/{numeroItem}/resultados`).
O `valor_inicial` de um contrato decorrente é sempre a soma
`Σ(quantidade_i × valorUnitarioHomologado_i)` dos itens que aquele MESMO
fornecedor (CNPJ) venceu na compra de origem. Portanto, filtrando os itens
pelo CNPJ do contrato e resolvendo a combinação de quantidades inteiras
que fecha com `valor_inicial`, é possível recuperar a distribuição por item
sem depender de leitura manual do PDF.

Validado ao vivo em 2026-07-28 contra o caso real do Edital 90016/2024
(compra 000032/2024, cnpj 05805924000189, 2 atas/2 contratos):
  - Contrato 71/2025 (valor_inicial R$2.454.986,00, fornecedor LIDER
    NOTEBOOKS): busca exaustiva no range [0,600]×[0,200] achou UMA ÚNICA
    combinação — 200 desktops (R$6.130,00) + 198 notebooks (R$6.207,00).
    Bate exatamente com `OFFICIAL_CONTRACT_ITEMS[("00027/2025",
    "71/2025/FPDC")]`, já confirmado por PDF real.
  - Contrato 68/2025 (valor_inicial R$115.480,00, fornecedor MICROSENS):
    só um item candidato (tablet, R$5.774,00) — solução trivial, 20
    unidades.

Por segurança, só aceita a solução se ela for MATEMATICAMENTE ÚNICA —
se mais de uma combinação de quantidades fechar o valor (preços
parecidos/múltiplos entre si permitem isso), devolve None e não arrisca.
Também recusa itens do tipo "lote de valor" (sem unidade física,
`quantidade_registrada == 1`) — nesses a equação de combinação não se
aplica. Ver `project_pca_erros_apis_contratos.md` (memória do projeto)
para o levantamento completo.

⚠️ LIMITAÇÃO DE DOMÍNIO — CADASTRO DE RESERVA (achado 2026-07-29):
`.../itens/{n}/resultados` devolve o resultado ORIGINAL da licitação, e
NÃO reflete substituição posterior do detentor da ata. Quando o vencedor
desiste da contratação e é convocado o próximo do CADASTRO DE RESERVA
(art. 82, §4º da Lei 14.133/2021 c/c Decreto 11.462/2023), o novo
detentor é registrado COM O PREÇO DELE, não com o preço do vencedor
original — mas o PNCP continua mostrando o vencedor original e o preço
original nesse endpoint.

Caso real: ARP 00004/2026 (lote 1 do pregão 90003/2026) — o PNCP mostra
MASTER FACILITIES / R$15.280.443,36; a detentora real hoje é a ALFA
GESTÃO, registrada a R$15.739.933,44 (valor correto no banco local).

Consequências práticas:
  - O filtro por CNPJ abaixo (`niFornecedor` == CNPJ do contrato) FALHA
    SEGURO nesses casos: o CNPJ do contrato (novo detentor) não bate com
    o do resultado (vencedor original), então a função devolve None e o
    chamador cai no fallback. É o comportamento desejado.
  - ⚠️ RISCO RESIDUAL: se o novo detentor TAMBÉM tiver vencido outro item
    da MESMA compra (acontece — a ALFA venceu o lote 3 da mesma compra),
    o filtro por CNPJ casa com o item ERRADO. Hoje isso é neutralizado
    porque itens de lote de valor são recusados, mas em uma compra com
    itens de unidade física a atribuição poderia sair errada. Antes de
    confiar no resultado, conferir se a ARP teve troca de detentor.
  - Corolário: divergência entre valor homologado no PNCP/planilha e o
    valor no banco NÃO significa necessariamente erro de cadastro —
    pode ser substituição legítima por cadastro de reserva.
"""

import os
import re
import time
from decimal import Decimal, InvalidOperation, ROUND_FLOOR

import requests

BASE_URL = "https://dadosabertos.compras.gov.br"
PNCP_BASE_URL = "https://pncp.gov.br/api/pncp/v1"
TIMEOUT = 20

# Log de diagnóstico por requisição (timestamp + tempo de resposta) — ligar
# com a variável de ambiente DEBUG_HTTP_PNCP=1. Serve pra achar, ao vivo,
# qual chamada específica está lenta/travando quando um comando que
# percorre muitos contratos/itens (ex: conciliar_dashboard_srp) parece
# travado. Desligado por padrão pra não poluir a saída normal dos comandos.
_DEBUG_HTTP = bool(os.environ.get("DEBUG_HTTP_PNCP"))


def _get_com_log(url, params=None, timeout=TIMEOUT):
    if not _DEBUG_HTTP:
        return requests.get(url, params=params, timeout=timeout)
    inicio = time.monotonic()
    print(f"  [http] GET {url} params={params} ...", flush=True)
    try:
        resp = requests.get(url, params=params, timeout=timeout)
        dt = time.monotonic() - inicio
        print(f"  [http] -> {resp.status_code} em {dt:.1f}s", flush=True)
        return resp
    except requests.RequestException as exc:
        dt = time.monotonic() - inicio
        print(f"  [http] -> ERRO ({exc.__class__.__name__}) após {dt:.1f}s: {exc}", flush=True)
        raise

# MPPI — confirmado ao vivo via /modulo-uasg/1_consultarUasg?codigoUasg=926092
MPPI_CODIGO_ORGAO = 94252
MPPI_CODIGO_UNIDADE_GESTORA = 926092

_cache_contratos_ano = {}
_cache_itens_contrato = {}
_cache_itens_compra_pncp = {}
_cache_resultados_item_pncp = {}


def _normalizar_numero(numero: str) -> str:
    """
    Extrai o núcleo "NN/AAAA" de um número de contrato e remove zeros à
    esquerda, para permitir comparar formatos divergentes:
      "00036/2026" (SIASG/dadosabertos) == "36/2026" (banco local)
      "28/2026 PGJ" (banco local, com sufixo) -> "28/2026"
    """
    if not numero:
        return ""
    m = re.search(r"(\d+)\s*[/\-]\s*(\d{4})", numero)
    if not m:
        return re.sub(r"\D", "", numero)
    num, ano = m.groups()
    return f"{int(num)}/{ano}"


def _buscar_contratos_ano(ano: int):
    """Busca (com cache em memória do processo) todos os contratos do MPPI
    com vigência inicial dentro do ano informado."""
    if ano in _cache_contratos_ano:
        return _cache_contratos_ano[ano]
    params = {
        "codigoOrgao": MPPI_CODIGO_ORGAO,
        "codigoUnidadeGestora": MPPI_CODIGO_UNIDADE_GESTORA,
        "dataVigenciaInicialMin": f"{ano}-01-01",
        "dataVigenciaInicialMax": f"{ano}-12-31",
        "pagina": 1,
        "tamanhoPagina": 200,
    }
    resultado = []
    try:
        resp = _get_com_log(f"{BASE_URL}/modulo-contratos/1_consultarContratos", params=params)
        resp.raise_for_status()
        resultado = resp.json().get("resultado", [])
    except (requests.RequestException, ValueError):
        resultado = []
    _cache_contratos_ano[ano] = resultado
    return resultado


def _buscar_itens_contrato_api(ano: int, numero_contrato_api: str):
    """Busca os itens de UM contrato específico (número exato conforme a
    própria API devolveu na listagem, não o número local)."""
    chave = (ano, numero_contrato_api)
    if chave in _cache_itens_contrato:
        return _cache_itens_contrato[chave]
    params = {
        "codigoOrgao": MPPI_CODIGO_ORGAO,
        "codigoUnidadeGestora": MPPI_CODIGO_UNIDADE_GESTORA,
        "numeroContrato": numero_contrato_api,
        "dataVigenciaInicialMin": f"{ano}-01-01",
        "dataVigenciaInicialMax": f"{ano}-12-31",
        "pagina": 1,
        "tamanhoPagina": 200,
    }
    itens = []
    try:
        resp = _get_com_log(f"{BASE_URL}/modulo-contratos/2_consultarContratosItem", params=params)
        resp.raise_for_status()
        itens = resp.json().get("resultado", [])
    except (requests.RequestException, ValueError):
        itens = []
    _cache_itens_contrato[chave] = itens
    return itens


def _parse_decimal(valor):
    if valor is None:
        return None
    try:
        return Decimal(str(valor))
    except InvalidOperation:
        return None


def resolver_itens_para_contrato(contrato):
    """
    Tenta resolver automaticamente {numero_item: quantidade} para um
    Contrato local via dadosabertos.compras.gov.br — Módulo Contratos.

    Retorna None (sem adivinhar) sempre que:
      - o contrato não tiver ARP de origem;
      - a data de assinatura/vigência não permitir determinar o ano;
      - não houver exatamente UM contrato candidato na API que bata
        pelo número normalizado E pelo CNPJ do fornecedor;
      - algum item devolvido pela API não puder ser casado com um
        ItemARP local via codigo_item_compras_gov (evita mapear
        errado — ex: itens de posto de trabalho/diária sem código).
    """
    arp = getattr(contrato, "arp_origem", None)
    if not arp:
        return None

    data_ref = contrato.data_assinatura or getattr(arp, "data_inicio_vigencia", None)
    if not data_ref:
        return None
    ano = data_ref.year

    numero_local_norm = _normalizar_numero(contrato.numero_contrato)
    if not numero_local_norm:
        return None

    candidatos_ano = _buscar_contratos_ano(ano)
    if not candidatos_ano:
        return None

    cnpj_local = (contrato.contratado_cnpj_cpf or "").strip()
    cnpj_local_digits = re.sub(r"\D", "", cnpj_local)

    candidatos = []
    for c in candidatos_ano:
        if c.get("contratoExcluido"):
            continue
        if _normalizar_numero(c.get("numeroContrato") or "") != numero_local_norm:
            continue
        cnpj_api_digits = re.sub(r"\D", "", str(c.get("niFornecedor") or ""))
        if cnpj_local_digits and cnpj_api_digits and cnpj_local_digits != cnpj_api_digits:
            continue
        candidatos.append(c)

    if len(candidatos) != 1:
        return None

    contrato_api = candidatos[0]
    numero_contrato_api = contrato_api.get("numeroContrato")
    itens_api = _buscar_itens_contrato_api(ano, numero_contrato_api)
    if not itens_api:
        return None

    itens_arp_por_codigo = {}
    for item_arp in arp.itens.all():
        if item_arp.codigo_item_compras_gov:
            itens_arp_por_codigo.setdefault(item_arp.codigo_item_compras_gov, []).append(item_arp)

    mapa = {}
    for item_api in itens_api:
        if item_api.get("contratoItemExcluido"):
            continue
        codigo_item = item_api.get("codigoItem")
        qtd_fisica = _parse_decimal(item_api.get("quantidadeItem"))
        valor_total_item = _parse_decimal(item_api.get("valorTotalItem"))
        if codigo_item is None or qtd_fisica is None:
            return None  # dado incompleto — não arrisca
        candidatos_item = itens_arp_por_codigo.get(codigo_item)
        if not candidatos_item or len(candidatos_item) != 1:
            return None  # não achou (ou achou mais de um) ItemARP para este código — não adivinha
        item_arp = candidatos_item[0]

        # ⚠️ Mesma heurística de apps/srp/views.py (ARPDetalheView): quando o
        # item da ARP foi registrado como "1 lote" (quantidade_registrada=1,
        # sem unidade física — o valor_unitario É o teto de valor do lote),
        # a quantidadeItem da API (ex: 24 "postos/mês") está em unidade
        # DIFERENTE da quantidade_registrada e não pode ser subtraída dela
        # diretamente. Nesse caso a quantidade "certa" pro ContratacaoDecorrente
        # é a fração de valor consumida do lote (valorTotalItem / valor_unitario
        # do lote), igual ao que o algoritmo de fallback já fazia manualmente.
        eh_lote_de_valor = (
            not (item_arp.unidade_fornecimento or "").strip()
            and abs(float(item_arp.quantidade_registrada) - 1.0) < 0.0001
        )
        if eh_lote_de_valor:
            if valor_total_item is None or not item_arp.valor_unitario:
                return None
            qtd = (valor_total_item / item_arp.valor_unitario).quantize(Decimal("0.0001"))
        else:
            qtd = qtd_fisica

        numero_item = item_arp.numero_item
        mapa[numero_item] = mapa.get(numero_item, Decimal("0")) + qtd

    if not mapa:
        return None

    return mapa


# ==========================================================================
# resolver_quantidade_por_valor_homologado — API PNCP (pncp.gov.br)
# ==========================================================================

def parse_numero_controle_pncp_ata(valor: str):
    """
    Extrai (cnpj, ano, sequencial_compra) de AtaRegistroPrecos.numero_controle_pncp_ata,
    formato "{cnpj}-{modalidade}-{compra}/{ano}-{ata}"
    (ex: "05805924000189-1-000032/2024-000001").

    Mesmo parsing já usado em AtaRegistroPrecos.link_documento_pncp_direto —
    duplicado aqui de propósito para não acoplar este serviço ao model.

    Função pública — também usada por outros comandos (ex:
    completar_itens_arp_pncp) que precisam falar com a mesma API PNCP.
    """
    if not valor:
        return None
    try:
        cnpj, _modalidade, compra_ano, _ata_seq = valor.strip().split("-")
        compra_seq, ano = compra_ano.split("/")
        return cnpj, int(ano), int(compra_seq)
    except (ValueError, TypeError):
        return None


def buscar_itens_compra_pncp(cnpj: str, ano: int, compra_seq: int):
    """
    GET /orgaos/{cnpj}/compras/{ano}/{compra}/itens — TODOS os itens da compra
    (com cache). Função pública — reaproveitada por completar_itens_arp_pncp.

    ⚠️ PAGINAÇÃO OBRIGATÓRIA (bug achado em 2026-07-28): sem os parâmetros
    `pagina`/`tamanhoPagina` este endpoint devolve silenciosamente só os
    **10 primeiros itens**, sem nenhum indicador de que há mais (a resposta
    é uma lista JSON crua, sem envelope com totalRegistros). Isso passou
    despercebido nos primeiros testes porque as compras usadas de exemplo
    tinham 3 e 8 itens. Descoberto ao rodar `completar_itens_arp_pncp` na
    ARP 00053/2025 (compra 000056/2025, material de higiene/limpeza): a ARP
    local tem os itens 24–28, mas a API só devolvia os itens 1–10, então o
    comando concluía "nenhum item homologado pra este CNPJ" — falso.
    Confirmado que o servidor honra `tamanhoPagina=50`.
    """
    chave = (cnpj, ano, compra_seq)
    if chave in _cache_itens_compra_pncp:
        return _cache_itens_compra_pncp[chave]

    itens = []
    tamanho_pagina = 50
    pagina = 1
    MAX_PAGINAS = 100  # trava de segurança contra loop infinito (5.000 itens)
    try:
        while pagina <= MAX_PAGINAS:
            resp = _get_com_log(
                f"{PNCP_BASE_URL}/orgaos/{cnpj}/compras/{ano}/{compra_seq}/itens",
                params={"pagina": pagina, "tamanhoPagina": tamanho_pagina},
            )
            resp.raise_for_status()
            pagina_itens = resp.json() or []
            if not isinstance(pagina_itens, list) or not pagina_itens:
                break
            itens.extend(pagina_itens)
            if len(pagina_itens) < tamanho_pagina:
                break  # última página
            pagina += 1
    except (requests.RequestException, ValueError):
        # Mantém o que já veio — melhor uma lista parcial do que estourar;
        # quem consome já trata lista vazia/incompleta com segurança.
        pass

    _cache_itens_compra_pncp[chave] = itens
    return itens


def buscar_resultados_item_pncp(cnpj: str, ano: int, compra_seq: int, numero_item: int):
    """
    GET .../itens/{numeroItem}/resultados — fornecedor(es) homologado(s) do
    item (com cache). Função pública — reaproveitada por completar_itens_arp_pncp.

    Também paginado (mesmo motivo de `buscar_itens_compra_pncp`). Aqui o
    normal é 1 resultado por item, mas em SRP pode haver vários fornecedores
    classificados (`ordemClassificacaoSrp`), então pede tamanhoPagina=50 de
    cara: no caso comum resolve em 1 request e só pagina se realmente vier
    página cheia.
    """
    chave = (cnpj, ano, compra_seq, numero_item)
    if chave in _cache_resultados_item_pncp:
        return _cache_resultados_item_pncp[chave]

    resultados = []
    tamanho_pagina = 50
    pagina = 1
    MAX_PAGINAS = 20
    try:
        while pagina <= MAX_PAGINAS:
            resp = _get_com_log(
                f"{PNCP_BASE_URL}/orgaos/{cnpj}/compras/{ano}/{compra_seq}/itens/{numero_item}/resultados",
                params={"pagina": pagina, "tamanhoPagina": tamanho_pagina},
            )
            resp.raise_for_status()
            pagina_res = resp.json() or []
            if not isinstance(pagina_res, list) or not pagina_res:
                break
            resultados.extend(pagina_res)
            if len(pagina_res) < tamanho_pagina:
                break
            pagina += 1
    except (requests.RequestException, ValueError):
        pass

    _cache_resultados_item_pncp[chave] = resultados
    return resultados


class _BuscaAbortada(Exception):
    """Sinaliza que o backtracking estourou o orçamento de nós (ver
    `_resolver_combinacao_unica`) e foi interrompido de propósito."""


def _resolver_combinacao_unica(candidatos, alvo, tolerancia=Decimal("0.01"), max_nos=200_000):
    """
    candidatos: lista de (numero_item, valor_unitario: Decimal, teto: int).
    alvo: Decimal — valor a fechar (valor_inicial do contrato).

    Busca por backtracking (com corte assim que uma 2ª solução aparece —
    não precisa enumerar tudo) todas as combinações de quantidades inteiras
    0..teto por item cuja soma ponderada bate com `alvo` dentro da
    tolerância. Só retorna mapeamento se a solução for ÚNICA.

    Orçamento de nós (adicionado após travamentos reais em contratos com
    vários itens de valor baixo/teto alto — ex: ARPs 00023/2025,
    00046/2025, 00011/2024 — onde a árvore de busca ficava grande demais e
    o comando parecia "travado", exigindo Ctrl+C):

      Se o backtracking visitar mais de `max_nos` nós sem terminar, aborta
      e retorna None (equivalente a "não deu pra determinar
      automaticamente" — mesma semântica de ambíguo/sem solução única, cai
      pro fallback de similaridade/valor já existente). Nunca mais trava
      indefinidamente — o pior caso agora é limitado no tempo.

      (Uma tentativa de reordenar `candidatos` por valor unitário
      decrescente antes de recursar, pra podar mais cedo, foi testada e
      descartada: em benchmark com dados sintéticos essa ordenação piorou
      o tempo em vários casos em vez de melhorar — não há uma ordem
      universalmente melhor para esse tipo de busca combinatória, então
      manter a ordem original dos candidatos é tão bom quanto qualquer
      heurística simples, e o orçamento de nós é quem garante o teto.)
    """
    solucoes = []
    nos_visitados = 0
    n = len(candidatos)

    def backtrack(idx, restante, escolha):
        nonlocal nos_visitados
        nos_visitados += 1
        if nos_visitados > max_nos:
            raise _BuscaAbortada()
        if len(solucoes) > 1:
            return
        if idx == n:
            if abs(restante) <= tolerancia:
                solucoes.append(dict(escolha))
            return

        numero_item, valor_unit, teto = candidatos[idx]
        if valor_unit <= 0 or teto <= 0:
            backtrack(idx + 1, restante, escolha)
            return

        # Limita a busca ao que ainda cabe no valor restante (+1 de folga
        # por causa da tolerância de centavos), nunca ultrapassando o teto.
        if restante > 0:
            limite_valor = int((restante / valor_unit).to_integral_value(rounding=ROUND_FLOOR)) + 1
        else:
            limite_valor = 0
        max_qtd = min(teto, max(limite_valor, 0))

        for qtd in range(0, max_qtd + 1):
            novo_restante = restante - (qtd * valor_unit)
            if novo_restante < -tolerancia:
                break
            escolha[numero_item] = Decimal(qtd)
            backtrack(idx + 1, novo_restante, escolha)
            del escolha[numero_item]
            if len(solucoes) > 1:
                return

    try:
        backtrack(0, alvo, {})
    except _BuscaAbortada:
        return None

    if len(solucoes) == 1:
        return {k: v for k, v in solucoes[0].items() if v > 0}
    return None


def resolver_quantidade_por_valor_homologado(contrato):
    """
    Tenta resolver automaticamente {numero_item: quantidade} para um
    Contrato local casando o CNPJ do fornecedor + preço unitário
    homologado na ARP de origem (via API pública do PNCP) contra o
    `valor_inicial` do contrato. Ver docstring do módulo para o
    equacionamento e o caso real validado.

    Retorna None (nunca adivinha) quando:
      - o contrato não tem `arp_origem`, ou a ARP não tem
        `numero_controle_pncp_ata` no formato esperado;
      - `valor_inicial` do contrato é vazio/zero;
      - a API do PNCP não devolve itens para a compra de origem;
      - nenhum item foi homologado para o CNPJ do fornecedor do contrato;
      - algum item candidato é um "lote de valor" (sem unidade física,
        `quantidade_registrada == 1`) — a equação de combinação não se
        aplica a esse caso;
      - a combinação de quantidades que fecha com `valor_inicial` não é
        ÚNICA (ambígua — preços parecidos/múltiplos permitem mais de uma
        combinação).
    """
    arp = getattr(contrato, "arp_origem", None)
    if not arp:
        return None

    parsed = parse_numero_controle_pncp_ata(getattr(arp, "numero_controle_pncp_ata", ""))
    if not parsed:
        return None
    cnpj, ano, compra_seq = parsed

    valor_alvo = contrato.valor_inicial
    if not valor_alvo or valor_alvo <= 0:
        return None

    cnpj_contrato_digits = re.sub(r"\D", "", contrato.contratado_cnpj_cpf or "")
    if not cnpj_contrato_digits:
        return None

    itens_compra = buscar_itens_compra_pncp(cnpj, ano, compra_seq)
    if not itens_compra:
        return None

    itens_arp_por_numero = {item.numero_item: item for item in arp.itens.all()}

    candidatos = []
    for item_compra in itens_compra:
        numero_item = item_compra.get("numeroItem")
        if numero_item is None:
            continue
        item_arp = itens_arp_por_numero.get(numero_item)
        if not item_arp:
            continue  # item da compra sem ItemARP local correspondente — não arrisca

        # "Lote de valor" (teto financeiro, sem unidade física): a equação de
        # combinação por quantidade inteira não se aplica — deixa pra outra
        # heurística (mesma detecção usada em resolver_itens_para_contrato /
        # ARPDetalheView).
        eh_lote_de_valor = (
            not (item_arp.unidade_fornecimento or "").strip()
            and abs(float(item_arp.quantidade_registrada) - 1.0) < 0.0001
        )
        if eh_lote_de_valor:
            return None

        resultados = buscar_resultados_item_pncp(cnpj, ano, compra_seq, numero_item)
        for resultado in resultados:
            if resultado.get("dataCancelamento") or resultado.get("motivoCancelamento"):
                continue
            cnpj_resultado_digits = re.sub(r"\D", "", str(resultado.get("niFornecedor") or ""))
            if not cnpj_resultado_digits or cnpj_resultado_digits != cnpj_contrato_digits:
                continue
            valor_unitario = _parse_decimal(resultado.get("valorUnitarioHomologado"))
            qtd_homologada = _parse_decimal(resultado.get("quantidadeHomologada"))
            if valor_unitario is None or valor_unitario <= 0 or qtd_homologada is None:
                continue
            teto = min(qtd_homologada, item_arp.quantidade_registrada)
            if teto <= 0:
                continue
            candidatos.append((item_arp.numero_item, valor_unitario, int(teto)))

    if not candidatos:
        return None

    return _resolver_combinacao_unica(candidatos, valor_alvo)
