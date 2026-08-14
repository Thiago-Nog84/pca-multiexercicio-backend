"""
Filtros de template compartilhados pelo sistema PCA Multiexercício.

Criado em 2026-08-03 ao corrigir o filtro `floatformat:"2g"`, usado em ~55 pontos do
sistema (KPIs de dinheiro em quase todo dashboard) para tentar exibir valor monetário
com 2 casas decimais e separador de milhar. O argumento "2g" nunca foi um argumento
válido de `floatformat` (Django só aceita inteiro) — o filtro falhava silenciosamente
e devolvia o Decimal cru sem formatação (ex. "1234567.891" em vez de "1.234.567,89").
Ver docs/melhorias_visuais_congresso.md.
"""
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from django import template

register = template.Library()


@register.filter(name="brl")
def brl(value, decimals=2):
    """Formata um número no padrão monetário brasileiro (1.234.567,89), sem o prefixo 'R$'
    — o prefixo continua sendo escrito no template, como já era o padrão no sistema.
    Não depende de ativação de locale (funciona igual em qualquer contexto de request)."""
    if value is None or value == "":
        value = 0
    try:
        casas = int(decimals)
    except (TypeError, ValueError):
        casas = 2

    try:
        d = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return value

    quant = Decimal(1).scaleb(-casas) if casas > 0 else Decimal(1)
    d = d.quantize(quant, rounding=ROUND_HALF_UP)

    negativo = d < 0
    if negativo:
        d = -d

    texto = f"{d:.{casas}f}"
    inteiro, _, frac = texto.partition(".")

    grupos = []
    while len(inteiro) > 3:
        grupos.insert(0, inteiro[-3:])
        inteiro = inteiro[:-3]
    grupos.insert(0, inteiro)
    resultado = ".".join(grupos)
    if casas:
        resultado += "," + frac

    return ("-" + resultado) if negativo else resultado


@register.filter(name="qtd_br")
def qtd_br(value, casas_max=4):
    """Formata QUANTIDADE (não dinheiro) no padrão brasileiro: separador de milhar,
    vírgula decimal, mas SEM zeros à direita — 600,0000 vira "600", 0,4811 continua
    "0,4811". Existe porque alguns itens de ARP/PCA guardam quantidade fracionária de
    propósito (ex. lote/teto de valor rateado por item — ver [[project-pca-fracao-
    quantidades-pendente]]); arredondar sempre para inteiro esconderia esse dado."""
    if value is None or value == "":
        return "0"
    try:
        casas = int(casas_max)
    except (TypeError, ValueError):
        casas = 4

    try:
        d = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return value

    quant = Decimal(1).scaleb(-casas) if casas > 0 else Decimal(1)
    d = d.quantize(quant, rounding=ROUND_HALF_UP)

    negativo = d < 0
    if negativo:
        d = -d

    texto = f"{d:.{casas}f}"
    inteiro, _, frac = texto.partition(".")
    frac = frac.rstrip("0")

    grupos = []
    while len(inteiro) > 3:
        grupos.insert(0, inteiro[-3:])
        inteiro = inteiro[:-3]
    grupos.insert(0, inteiro)
    resultado = ".".join(grupos)
    if frac:
        resultado += "," + frac

    return ("-" + resultado) if negativo else resultado
