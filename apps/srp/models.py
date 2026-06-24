"""
Módulo SRP — Sistema de Registro de Preços
Lei 14.133/2021, arts. 82–86 | Decreto Federal 11.462/2023
Decreto Estadual 21.938/2023 (subsidiário para o MPPI)

4 dimensões obrigatórias:
  1. ARPs originadas       — atas geradas pelo MPPI como órgão gerenciador
  2. Contratações          — pedidos de fornecimento decorrentes de ARP própria
  3. Caronas cedidas       — adesões de outros órgãos à ARP do MPPI
  4. Caronas recebidas     — ARPs de outros órgãos às quais o MPPI aderiu

REGRA CRÍTICA (Decreto 11.462/2023, art. 9º):
  O quantitativo total de adesões por item não pode ultrapassar 50% do
  quantitativo originalmente registrado. Violação gera nulidade contratual
  e exposição ao TCU. A validação é feita em AdesaoARP.save().
"""

from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class AtaRegistroPrecos(models.Model):
    """
    ARP originada pelo MPPI como órgão gerenciador.
    Fundamento: arts. 82–86 NLLC + Decreto 11.462/2023, art. 4º.
    """

    STATUS = [
        ("vigente", "Vigente"),
        ("suspensa", "Suspensa"),
        ("cancelada", "Cancelada"),
        ("encerrada", "Encerrada (vigência expirada)"),
    ]

    MODALIDADE_ORIGEM = [
        ("pregao_eletronico", "Pregão Eletrônico"),
        ("concorrencia", "Concorrência"),
        ("dispensa_srp", "Dispensa para SRP (art. 75, §7º NLLC)"),
    ]

    orgao_gerenciador = models.ForeignKey(
        "core.Orgao",
        on_delete=models.PROTECT,
        related_name="arps_gerenciadas",
    )
    numero_arp = models.CharField(
        max_length=30,
        help_text="Número sequencial da ARP no exercício (ex: 001/2027)",
    )
    numero_sei = models.CharField(
        max_length=30,
        blank=True,
        help_text="Número do processo SEI/MPPI (obrigatório para rastreabilidade)",
    )
    numero_pncp = models.CharField(
        max_length=100,
        blank=True,
        help_text="Identificador de publicação no PNCP (condição de eficácia — art. 174 NLLC)",
    )
    objeto = models.TextField()
    modalidade_origem = models.CharField(max_length=20, choices=MODALIDADE_ORIGEM)
    processo_licitatorio = models.CharField(
        max_length=30,
        blank=True,
        help_text="Número do processo licitatório que originou a ARP",
    )
    fornecedor_razao_social = models.CharField(max_length=255)
    fornecedor_cnpj_cpf = models.CharField(max_length=18)
    data_assinatura = models.DateField()
    data_inicio_vigencia = models.DateField()
    data_fim_vigencia = models.DateField(
        help_text="Máximo 12 meses da assinatura (Decreto 11.462/2023, art. 4º, §2º)",
    )
    data_publicacao_pncp = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=15, choices=STATUS, default="vigente")
    observacoes = models.TextField(blank=True)
    criado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        on_delete=models.SET_NULL,
        related_name="arps_criadas",
    )
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Ata de Registro de Preços"
        verbose_name_plural = "Atas de Registro de Preços"
        ordering = ["-data_inicio_vigencia"]
        unique_together = ("orgao_gerenciador", "numero_arp")

    def __str__(self):
        return f"ARP {self.numero_arp} — {self.fornecedor_razao_social[:40]}"

    @property
    def esta_vigente(self):
        from datetime import date
        return self.status == "vigente" and self.data_fim_vigencia >= date.today()


class ItemARP(models.Model):
    """
    Item registrado na ARP com quantidade, valor unitário e saldo disponível.
    O saldo é debitado automaticamente a cada ContratacaoDecorrente ou AdesaoARP.
    """

    arp = models.ForeignKey(
        AtaRegistroPrecos,
        on_delete=models.CASCADE,
        related_name="itens",
    )
    numero_item = models.PositiveIntegerField()
    codigo_catmat_catser = models.CharField(max_length=20, blank=True)
    descricao = models.TextField()
    unidade_fornecimento = models.CharField(max_length=30)
    quantidade_registrada = models.DecimalField(max_digits=14, decimal_places=4)
    valor_unitario = models.DecimalField(max_digits=14, decimal_places=2)

    # Saldo calculado — atualizado a cada contratação/adesão
    quantidade_contratada = models.DecimalField(
        max_digits=14, decimal_places=4, default=Decimal("0")
    )
    quantidade_cedida_carona = models.DecimalField(
        max_digits=14,
        decimal_places=4,
        default=Decimal("0"),
        help_text="Total cedido a órgãos aderentes via carona",
    )

    class Meta:
        verbose_name = "Item de ARP"
        ordering = ["numero_item"]
        unique_together = ("arp", "numero_item")

    def __str__(self):
        return f"Item {self.numero_item} — {self.descricao[:50]}"

    @property
    def quantidade_disponivel(self):
        return self.quantidade_registrada - self.quantidade_contratada - self.quantidade_cedida_carona

    @property
    def valor_total_registrado(self):
        return self.quantidade_registrada * self.valor_unitario

    @property
    def limite_carona_por_aderente(self):
        """
        50% do quantitativo por item por órgão aderente.
        Decreto 11.462/2023, art. 9º.
        """
        return self.quantidade_registrada * Decimal("0.5")


class ContratacaoDecorrente(models.Model):
    """
    Pedido de fornecimento emitido com base em ARP própria do MPPI.
    Cada contratação debita o saldo do ItemARP correspondente.
    Fundamento: Decreto 11.462/2023, art. 7º.
    """

    STATUS = [
        ("emitido", "Emitido"),
        ("em_execucao", "Em execução"),
        ("concluido", "Concluído"),
        ("cancelado", "Cancelado"),
    ]

    arp = models.ForeignKey(
        AtaRegistroPrecos,
        on_delete=models.PROTECT,
        related_name="contratacoes_decorrentes",
    )
    item_arp = models.ForeignKey(
        ItemARP,
        on_delete=models.PROTECT,
        related_name="contratacoes",
    )
    numero_pedido = models.CharField(max_length=30)
    numero_sei = models.CharField(max_length=30, blank=True)
    quantidade = models.DecimalField(max_digits=14, decimal_places=4)
    valor_unitario = models.DecimalField(max_digits=14, decimal_places=2)
    valor_total = models.DecimalField(max_digits=16, decimal_places=2)
    data_emissao = models.DateField()
    data_entrega_prevista = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=15, choices=STATUS, default="emitido")
    unidade_requisitante = models.ForeignKey(
        "core.UnidadeRequisitante",
        null=True,
        on_delete=models.SET_NULL,
        related_name="contratacoes_decorrentes",
    )
    observacoes = models.TextField(blank=True)
    criado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        on_delete=models.SET_NULL,
        related_name="contratacoes_decorrentes_criadas",
    )
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Contratação Decorrente de ARP"
        verbose_name_plural = "Contratações Decorrentes de ARP"

    def __str__(self):
        return f"Pedido {self.numero_pedido} — ARP {self.arp.numero_arp}"

    def save(self, *args, **kwargs):
        """Debita automaticamente o saldo do item ao salvar."""
        if not self.pk:
            # Nova contratação — debita saldo
            self.item_arp.quantidade_contratada += self.quantidade
            self.item_arp.save(update_fields=["quantidade_contratada"])
        super().save(*args, **kwargs)


class AdesaoARP(models.Model):
    """
    Carona CEDIDA: outro órgão aderiu à ARP do MPPI.
    Valida o limite de 50% do quantitativo por item por aderente.
    Fundamento: Decreto 11.462/2023, art. 9º.

    ATENÇÃO: violação do limite de 50% gera nulidade contratual
    e exposição ao TCU (Acórdão TCU 1507/2024).
    """

    STATUS = [
        ("solicitada", "Solicitada"),
        ("autorizada", "Autorizada"),
        ("recusada", "Recusada"),
        ("cancelada", "Cancelada"),
    ]

    arp = models.ForeignKey(
        AtaRegistroPrecos,
        on_delete=models.PROTECT,
        related_name="adesoes",
    )
    item_arp = models.ForeignKey(
        ItemARP,
        on_delete=models.PROTECT,
        related_name="adesoes",
    )
    orgao_aderente_nome = models.CharField(max_length=255)
    orgao_aderente_cnpj = models.CharField(max_length=18)
    quantidade_solicitada = models.DecimalField(max_digits=14, decimal_places=4)
    valor_unitario = models.DecimalField(max_digits=14, decimal_places=2)
    valor_total = models.DecimalField(max_digits=16, decimal_places=2)
    data_solicitacao = models.DateField()
    data_autorizacao = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=15, choices=STATUS, default="solicitada")
    numero_sei_autorizacao = models.CharField(max_length=30, blank=True)
    observacoes = models.TextField(blank=True)
    autorizado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="adesoes_autorizadas",
    )
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Adesão à ARP (Carona Cedida)"
        verbose_name_plural = "Adesões à ARP (Caronas Cedidas)"

    def __str__(self):
        return f"Carona — {self.orgao_aderente_nome[:40]} → ARP {self.arp.numero_arp}"

    def clean(self):
        """
        Valida o limite de 50% por item por órgão aderente.
        Decreto 11.462/2023, art. 9º.
        """
        limite = self.item_arp.limite_carona_por_aderente

        # Total já cedido a ESTE órgão neste item (excluindo o registro atual)
        total_ja_cedido = (
            AdesaoARP.objects.filter(
                item_arp=self.item_arp,
                orgao_aderente_cnpj=self.orgao_aderente_cnpj,
                status="autorizada",
            )
            .exclude(pk=self.pk)
            .aggregate(total=models.Sum("quantidade_solicitada"))["total"]
            or Decimal("0")
        )

        if total_ja_cedido + self.quantidade_solicitada > limite:
            raise ValidationError(
                f"Limite de 50% por item por aderente excedido "
                f"(Decreto 11.462/2023, art. 9º). "
                f"Limite: {limite} | Já cedido: {total_ja_cedido} | "
                f"Solicitado: {self.quantidade_solicitada}."
            )

    def save(self, *args, **kwargs):
        self.full_clean()
        if self.status == "autorizada" and not self.pk:
            self.item_arp.quantidade_cedida_carona += self.quantidade_solicitada
            self.item_arp.save(update_fields=["quantidade_cedida_carona"])
        super().save(*args, **kwargs)


class ARPExterna(models.Model):
    """
    Carona RECEBIDA: ARP de outro órgão à qual o MPPI aderiu.
    Fundamento: Decreto 11.462/2023, art. 10.
    """

    STATUS = [
        ("ativa", "Ativa"),
        ("encerrada", "Encerrada"),
        ("cancelada", "Cancelada"),
    ]

    orgao_gerenciador_nome = models.CharField(
        max_length=255,
        help_text="Nome do órgão que originou a ARP",
    )
    orgao_gerenciador_cnpj = models.CharField(max_length=18)
    numero_arp_origem = models.CharField(
        max_length=30,
        help_text="Número da ARP no órgão gerenciador",
    )
    numero_pncp_origem = models.CharField(
        max_length=100,
        blank=True,
        help_text="Identificador PNCP da ARP de origem",
    )
    objeto = models.TextField()
    fornecedor_razao_social = models.CharField(max_length=255)
    fornecedor_cnpj_cpf = models.CharField(max_length=18)
    data_inicio_vigencia = models.DateField()
    data_fim_vigencia = models.DateField()
    numero_sei_adesao = models.CharField(
        max_length=30,
        blank=True,
        help_text="Número do processo SEI/MPPI de adesão",
    )
    quantidade_autorizada = models.DecimalField(max_digits=14, decimal_places=4)
    valor_unitario = models.DecimalField(max_digits=14, decimal_places=2)
    valor_total_autorizado = models.DecimalField(max_digits=16, decimal_places=2)
    quantidade_utilizada = models.DecimalField(
        max_digits=14, decimal_places=4, default=Decimal("0")
    )
    status = models.CharField(max_length=15, choices=STATUS, default="ativa")
    unidade_beneficiaria = models.ForeignKey(
        "core.UnidadeRequisitante",
        null=True,
        on_delete=models.SET_NULL,
        related_name="arps_externas",
    )
    observacoes = models.TextField(blank=True)
    criado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        on_delete=models.SET_NULL,
        related_name="arps_externas_criadas",
    )
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "ARP Externa (Carona Recebida)"
        verbose_name_plural = "ARPs Externas (Caronas Recebidas)"
        ordering = ["-data_inicio_vigencia"]

    def __str__(self):
        return f"ARP {self.numero_arp_origem} — {self.orgao_gerenciador_nome[:40]}"

    @property
    def saldo_remanescente(self):
        return self.quantidade_autorizada - self.quantidade_utilizada

    @property
    def valor_utilizado(self):
        return self.quantidade_utilizada * self.valor_unitario
