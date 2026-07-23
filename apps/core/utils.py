"""
Helpers de apresentação compartilhados entre módulos (dashboards, relatórios).

`subtitulo_dominante` e `subtitulo_maior` implementam o princípio do cap. 7 de
*Storytelling com Dados* (Knaflic): o título de um gráfico deve carregar a
CONCLUSÃO do recorte, não só nomear o eixo. Ex.: "PGJ concentra 74% do valor
empenhado" em vez de "Por fonte de recurso". Calculado na view (barato, sem
tocar em Chart.js) e renderizado como subtítulo abaixo do título de cada card.
Ver docs/melhorias_visuais_storytelling.md (P4).
"""


def fmt_moeda_compacta(valor):
    """
    Formata valor monetário de forma enxuta, no mesmo estilo já usado nos
    rótulos dos gráficos (Chart.js): "R$ 1,6M" / "R$ 850k" / "R$ 42,00".
    """
    try:
        valor = float(valor or 0)
    except (TypeError, ValueError):
        return "R$ 0,00"

    sinal = "-" if valor < 0 else ""
    valor = abs(valor)

    if valor >= 1_000_000:
        return f"{sinal}R$ {valor / 1_000_000:.1f}M".replace(".", ",")
    if valor >= 1_000:
        return f"{sinal}R$ {valor / 1_000:.0f}k"
    return f"{sinal}R$ {valor:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")


def subtitulo_dominante(pares, sufixo="", capitalizar=True, minimo_pct=0):
    """
    Gera "{rótulo} concentra {pct}%{sufixo}" a partir do item de maior valor
    em `pares` (iterável de tuplas (rótulo, valor)). Usado para gráficos de
    DISTRIBUIÇÃO (status, fonte, unidade) onde "quem concentra o quê" é a
    história natural do recorte.

    `minimo_pct`: só retorna o subtítulo se a fatia dominante for >= esse
    percentual (evita afirmar "concentra 22%" quando a distribuição é
    equilibrada e a frase perde força).
    Retorna "" se não houver dados.
    """
    pares_validos = [(str(l), float(v)) for l, v in pares if v]
    if not pares_validos:
        return ""
    total = sum(v for _, v in pares_validos)
    if not total:
        return ""

    label, valor = max(pares_validos, key=lambda x: x[1])
    pct = round(valor / total * 100)
    if pct < minimo_pct:
        return ""
    if capitalizar:
        label = label[:1].upper() + label[1:]
    return f"{label} concentra {pct}%{sufixo}"


def subtitulo_maior(pares, prefixo="Maior", em_moeda=True, sufixo=""):
    """
    Gera "{prefixo}: {rótulo} — {valor formatado}" a partir do item de maior
    valor em `pares`. Usado para gráficos de RANKING/top-N (top ARPs, top
    itens, top favorecidos) onde não faz sentido falar em "concentração do
    total" — a história é "quem lidera".
    Retorna "" se não houver dados.
    """
    pares_validos = [(str(l), float(v)) for l, v in pares if v]
    if not pares_validos:
        return ""
    label, valor = max(pares_validos, key=lambda x: x[1])
    valor_fmt = fmt_moeda_compacta(valor) if em_moeda else str(round(valor))
    return f"{prefixo}: {label} — {valor_fmt}{sufixo}"
