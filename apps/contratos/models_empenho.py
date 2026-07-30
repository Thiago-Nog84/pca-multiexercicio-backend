"""
Modelo Empenho — vinculação das notas de empenho SIAFE ao Contrato.

O SIAFE-PI usa a estrutura:
  Nota de Empenho (NE): número sequencial ex. 2025NE00099
  Natureza: Normal / Estimativo / Global
  Tipo: Ordinário / Reforço / Anulação
  Programa de trabalho: 00.0000.0000.0000.0000
  Elemento de despesa: 3.3.90.39 etc.
"""

from decimal import Decimal
from django.conf import settings
from django.db import models

# Importado abaixo para evitar circular imports
# from .models import Contrato


class Empenho(models.Model):
    """Nota de Empenho SIAFE vinculada a um Contrato."""

    NATUREZA = [
        ("ordinario", "Ordinário"),
        ("estimativo", "Estimativo"),
        ("global", "Global"),
    ]

    TIPO = [
        ("empenho", "Empenho"),
        ("reforco", "Reforço"),
        ("anulacao", "Anulação"),
    ]

    STATUS_LIQUIDACAO = [
        ("nao_liquidado", "Não Liquidado"),
        ("parcialmente", "Parcialmente Liquidado"),
        ("liquidado", "Liquidado"),
        ("pago", "Pago"),
    ]

    contrato = models.ForeignKey(
        "contratos.Contrato",
        on_delete=models.CASCADE,
        related_name="empenhos",
        help_text="Contrato ao qual este empenho está vinculado",
    )
    numero_empenho = models.CharField(
        max_length=30,
        help_text="Número da Nota de Empenho no SIAFE (ex: 2025NE00099)",
    )
    ano_exercicio = models.PositiveSmallIntegerField(default=2025)
    natureza = models.CharField(max_length=15, choices=NATUREZA, default="ordinario")
    tipo = models.CharField(max_length=10, choices=TIPO, default="empenho")

    # Valores
    valor_empenhado = models.DecimalField(max_digits=16, decimal_places=2, default=Decimal("0.00"))
    valor_liquidado = models.DecimalField(max_digits=16, decimal_places=2, default=Decimal("0.00"))
    valor_pago = models.DecimalField(max_digits=16, decimal_places=2, default=Decimal("0.00"))

    # Classificação orçamentária
    programa_trabalho = models.CharField(max_length=30, blank=True, help_text="PTRES / Programa de Trabalho SIAFE")
    elemento_despesa = models.CharField(max_length=20, blank=True, help_text="Elemento de despesa (ex: 3.3.90.39)")
    fonte_recurso = models.CharField(max_length=10, blank=True, help_text="Fonte/Destinação de Recurso (ex: 0100)")
    unidade_orcamentaria = models.CharField(max_length=10, blank=True, help_text="UO no SIAFE")

    # Beneficiário
    cnpj_favorecido = models.CharField(max_length=18, blank=True)
    nome_favorecido = models.CharField(max_length=255, blank=True)

    # Datas
    data_emissao = models.DateField(null=True, blank=True)
    data_liquidacao = models.DateField(null=True, blank=True)
    data_pagamento = models.DateField(null=True, blank=True)

    # Descrição / observação
    descricao = models.TextField(blank=True, help_text="Descrição do objeto no empenho SIAFE")

    # Status
    status_liquidacao = models.CharField(max_length=15, choices=STATUS_LIQUIDACAO, default="nao_liquidado")

    # Metadados de importação
    importado_siafe = models.BooleanField(default=False, help_text="Dados importados automaticamente do SIAFE")
    importado_em = models.DateTimeField(null=True, blank=True)

    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Empenho"
        verbose_name_plural = "Empenhos"
        ordering = ["-ano_exercicio", "-numero_empenho"]
        unique_together = ("contrato", "numero_empenho")

    def __str__(self):
        return f"{self.numero_empenho} — {self.contrato.numero_contrato} (R$ {self.valor_empenhado:,.2f})"

    @property
    def saldo_a_liquidar(self):
        return self.valor_empenhado - self.valor_liquidado

    @property
    def saldo_a_pagar(self):
        return self.valor_liquidado - self.valor_pago


class EmpenhoProduto(models.Model):
    """
    Item de produto/serviço do bloco `produtos[]` da Nota de Empenho (API SIAFE).

    Até 2026-07-30 esse bloco existia na API mas não era importado — ver
    docs/nota_empenho_fonte_de_verdade.md §2. Guarda quantidade, unidade e
    preço por item, o dado que faltava para resolver casos de quantidade
    fracionária em ContratacaoDecorrente sem depender de PDF do SEI (ver
    docs/fracao_quantidades_2026-07-29.md).

    Importado por `importar_empenhos_siafe`: a cada reimportação, os itens do
    empenho são substituídos (delete + recria), então este modelo sempre
    reflete o último payload do SIAFE — não acumula histórico próprio.
    """

    empenho = models.ForeignKey(
        "contratos.Empenho",
        on_delete=models.CASCADE,
        related_name="produtos",
        help_text="Nota de Empenho da qual este item faz parte",
    )
    ordem = models.PositiveSmallIntegerField(
        default=0, help_text="Posição do item dentro do bloco produtos[] da NE"
    )
    nome_produto = models.CharField(
        max_length=255, blank=True, help_text="nomeProdutoGenerico da API SIAFE"
    )
    descricao_produto = models.TextField(
        blank=True, help_text="descricaoProdutoGenerico da API SIAFE"
    )
    unidade_fornecimento = models.CharField(
        max_length=30, blank=True, help_text="unidadeFornecimentoGenerico da API SIAFE"
    )
    quantidade = models.DecimalField(max_digits=14, decimal_places=4, default=Decimal("0"))
    preco_unitario = models.DecimalField(max_digits=16, decimal_places=4, default=Decimal("0"))
    preco_total = models.DecimalField(max_digits=16, decimal_places=2, default=Decimal("0"))

    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Item da Nota de Empenho"
        verbose_name_plural = "Itens da Nota de Empenho"
        ordering = ["empenho", "ordem"]
        unique_together = ("empenho", "ordem")

    def __str__(self):
        return f"{self.empenho.numero_empenho} #{self.ordem} — {self.nome_produto[:40]} ({self.quantidade})"
