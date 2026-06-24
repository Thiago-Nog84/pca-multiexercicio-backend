from decimal import Decimal

from django.db import models

# Base legal: arts. 82–86 NLLC
# Decreto Federal 11.462/2023 (aplicado por opção — Ato PGJ 1382/2024)
# Decreto Estadual 21.938/2023 (subsidiário)
# MJR 86/2025 — orientação interna do MPPI para caronas
# MJR 95/2025 — orientação interna do MPPI para prorrogação de ARP
# POP Contratação Direta — Adesão ARP (procedimento operacional padrão do MPPI)


class AtaRegistroPrecos(models.Model):
    STATUS = [
        ("vigente", "Vigente"),
        ("suspensa", "Suspensa"),
        ("cancelada", "Cancelada"),
        ("encerrada", "Encerrada"),
    ]

    orgao_gerenciador = models.ForeignKey(
        "core.Orgao", on_delete=models.CASCADE, related_name="arps_gerenciadas"
    )
    processo_licitatorio = models.ForeignKey(
        "licitacao.ProcessoLicitatorio", null=True, blank=True, on_delete=models.SET_NULL, related_name="arps"
    )
    numero_ata = models.CharField(max_length=30)
    ano = models.PositiveSmallIntegerField()
    objeto = models.TextField()
    fornecedor_cnpj = models.CharField(max_length=18)
    fornecedor_razao = models.CharField(max_length=255)
    data_assinatura = models.DateField()
    data_vigencia_inicio = models.DateField()
    data_vigencia_fim = models.DateField()
    # Prorrogação — MJR 95/2025 define os critérios internos do MPPI
    prorrogada = models.BooleanField(default=False)
    data_prorrogacao = models.DateField(null=True, blank=True)
    fundamento_prorrogacao = models.TextField(
        blank=True, help_text="Critérios do MJR 95/2025 e art. 12 Dec. 11.462/2023"
    )
    numero_sei = models.CharField(max_length=30, blank=True)
    status = models.CharField(max_length=15, choices=STATUS, default="vigente")
    pncp_id = models.CharField(max_length=100, blank=True)
    publicada_pncp = models.BooleanField(default=False)
    data_publicacao_pncp = models.DateTimeField(null=True, blank=True)
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("orgao_gerenciador", "numero_ata", "ano")
        verbose_name = "Ata de Registro de Preços"

    def __str__(self):
        return f"ARP {self.numero_ata}/{self.ano}"

    @property
    def dias_para_vencimento(self):
        from django.utils import timezone

        return (self.data_vigencia_fim - timezone.now().date()).days

    @property
    def valor_total_registrado(self):
        from django.db.models import F, Sum

        return self.itens.aggregate(total=Sum(F("preco_unitario") * F("quantidade_registrada")))[
            "total"
        ] or Decimal("0")

    @property
    def saldo_disponivel(self):
        consumido = self.contratacoes_decorrentes.filter(status__in=["ativa", "encerrada"]).aggregate(
            total=models.Sum("valor_total")
        )["total"] or Decimal("0")
        return self.valor_total_registrado - consumido


class ItemARP(models.Model):
    ata = models.ForeignKey(AtaRegistroPrecos, on_delete=models.CASCADE, related_name="itens")
    numero_item = models.PositiveIntegerField()
    codigo_catmat_catser = models.CharField(max_length=20, blank=True)
    descricao = models.TextField()
    unidade_medida = models.CharField(max_length=30)
    quantidade_registrada = models.DecimalField(max_digits=14, decimal_places=4)
    preco_unitario = models.DecimalField(max_digits=14, decimal_places=2)

    @property
    def quantidade_consumida(self):
        from django.db.models import Sum

        return ItemContratacaoDecorrente.objects.filter(
            item_arp=self, contratacao__status__in=["ativa", "encerrada"]
        ).aggregate(total=Sum("quantidade"))["total"] or Decimal("0")

    @property
    def saldo_quantidade(self):
        return self.quantidade_registrada - self.quantidade_consumida

    @property
    def percentual_consumido(self):
        if self.quantidade_registrada == 0:
            return 0
        return float(self.quantidade_consumida / self.quantidade_registrada * 100)


class ContratacaoDecorrente(models.Model):
    """Pedido de fornecimento emitido com base em ARP do MPPI."""

    STATUS = [("ativa", "Ativa"), ("encerrada", "Encerrada"), ("cancelada", "Cancelada")]

    ata = models.ForeignKey(AtaRegistroPrecos, on_delete=models.CASCADE, related_name="contratacoes_decorrentes")
    unidade_requisitante = models.ForeignKey("core.UnidadeRequisitante", on_delete=models.CASCADE)
    numero_pedido = models.CharField(max_length=30)
    numero_sei = models.CharField(max_length=30, blank=True)
    data_emissao = models.DateField()
    data_entrega_prevista = models.DateField(null=True, blank=True)
    valor_total = models.DecimalField(max_digits=16, decimal_places=2)
    status = models.CharField(max_length=15, choices=STATUS, default="ativa")
    observacoes = models.TextField(blank=True)
    contrato = models.ForeignKey(
        "contratos.Contrato", null=True, blank=True, on_delete=models.SET_NULL, related_name="contratacoes_srp"
    )


class ItemContratacaoDecorrente(models.Model):
    contratacao = models.ForeignKey(ContratacaoDecorrente, on_delete=models.CASCADE, related_name="itens")
    item_arp = models.ForeignKey(ItemARP, on_delete=models.CASCADE, related_name="contratacoes")
    quantidade = models.DecimalField(max_digits=14, decimal_places=4)
    preco_unitario = models.DecimalField(max_digits=14, decimal_places=2)

    def clean(self):
        from django.core.exceptions import ValidationError

        if self.quantidade > self.item_arp.saldo_quantidade:
            raise ValidationError(
                f"Quantidade ({self.quantidade}) supera o saldo disponível na ARP "
                f"({self.item_arp.saldo_quantidade} {self.item_arp.unidade_medida})."
            )


class AdesaoARP(models.Model):
    """
    Carona — adesão de órgão não participante à ARP do MPPI.
    Critérios internos: MJR 86/2025 + POP Adesão ARP do MPPI.
    Decreto Federal 11.462/2023, arts. 28–32 (aplicado por opção).
    Decreto Estadual 21.938/2023 (subsidiário).
    Limite: 50% do quantitativo de cada item por órgão aderente.
    """

    STATUS = [
        ("solicitada", "Solicitada"),
        ("autorizada", "Autorizada pelo MPPI"),
        ("recusada", "Recusada"),
        ("cancelada", "Cancelada"),
    ]

    ata = models.ForeignKey(AtaRegistroPrecos, on_delete=models.CASCADE, related_name="adesoes")
    orgao_aderente_nome = models.CharField(max_length=255)
    orgao_aderente_cnpj = models.CharField(max_length=18)
    orgao_aderente_esfera = models.CharField(max_length=30)
    numero_sei_adesao = models.CharField(
        max_length=30, blank=True, help_text="Processo SEI/MPPI da solicitação de carona"
    )
    data_solicitacao = models.DateField()
    data_autorizacao = models.DateField(null=True, blank=True)
    # Exigida pelo MJR 86/2025 e art. 28, §1º, Dec. 11.462/2023
    justificativa_vantajosidade = models.TextField(
        help_text="Obrigatória — MJR 86/2025 e art. 28 §1º Dec. 11.462/2023"
    )
    mjr_86_observado = models.BooleanField(default=False, help_text="Confirmação de observância do MJR 86/2025")
    status = models.CharField(max_length=15, choices=STATUS, default="solicitada")
    publicada_pncp = models.BooleanField(default=False)


class ItemAdesaoARP(models.Model):
    adesao = models.ForeignKey(AdesaoARP, on_delete=models.CASCADE, related_name="itens")
    item_arp = models.ForeignKey(ItemARP, on_delete=models.CASCADE, related_name="adesoes")
    quantidade_solicitada = models.DecimalField(max_digits=14, decimal_places=4)
    quantidade_autorizada = models.DecimalField(max_digits=14, decimal_places=4, null=True, blank=True)

    @property
    def limite_legal(self):
        """50% do quantitativo registrado — Dec. 11.462/2023, art. 29 / MJR 86/2025."""
        return self.item_arp.quantidade_registrada * Decimal("0.5")

    def clean(self):
        from django.core.exceptions import ValidationError

        if self.quantidade_solicitada > self.limite_legal:
            raise ValidationError(
                f"Quantidade ({self.quantidade_solicitada}) supera o limite legal de 50% "
                f"({self.limite_legal} {self.item_arp.unidade_medida}) — "
                f"Dec. 11.462/2023, art. 29 / MJR 86/2025."
            )


class ARPExterna(models.Model):
    """
    Carona recebida — ARP de outro órgão à qual o MPPI aderiu.
    Procedimento: POP Adesão ARP do MPPI.
    """

    orgao_gerenciador_nome = models.CharField(max_length=255)
    orgao_gerenciador_cnpj = models.CharField(max_length=18)
    numero_ata_externa = models.CharField(max_length=30)
    ano_ata_externa = models.PositiveSmallIntegerField()
    objeto = models.TextField()
    fornecedor_cnpj = models.CharField(max_length=18)
    fornecedor_razao = models.CharField(max_length=255)
    numero_sei_adesao_mppi = models.CharField(max_length=30, blank=True, help_text="Processo SEI/MPPI da adesão")
    data_adesao = models.DateField()
    data_vigencia_fim = models.DateField()
    quantidade_autorizada = models.DecimalField(max_digits=14, decimal_places=4)
    valor_autorizado = models.DecimalField(max_digits=16, decimal_places=2)
    quantidade_utilizada = models.DecimalField(max_digits=14, decimal_places=4, default=0)
    valor_utilizado = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    pncp_ata_externa_id = models.CharField(max_length=100, blank=True)
    observacoes = models.TextField(blank=True)

    @property
    def saldo_quantidade(self):
        return self.quantidade_autorizada - self.quantidade_utilizada

    @property
    def saldo_valor(self):
        return self.valor_autorizado - self.valor_utilizado

    class Meta:
        verbose_name = "ARP Externa (Carona Recebida)"
