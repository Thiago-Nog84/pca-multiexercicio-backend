"""
Módulo Contratos — Gestão de Contratos Administrativos
Lei 14.133/2021, arts. 89–107 | Ato PGJ 1415/2024 (serviços contínuos)

Cobre: Contrato, Aditivo, Apostilamento, OrdemFornecimento
Alertas de vigência: 90 / 60 / 30 dias antes do vencimento.
"""

from django.conf import settings
from django.db import models
from .models_empenho import Empenho  # noqa: F401 — re-exportado para acesso via contratos.models


class Contrato(models.Model):
    """
    Contrato administrativo celebrado pelo MPPI.
    Fundamento: arts. 89–107 NLLC.
    """

    TIPO = [
        ("fornecimento", "Fornecimento de Bens"),
        ("servico_continuo", "Serviço de Execução Continuada (Ato PGJ 1415/2024)"),
        ("servico_nao_continuo", "Serviço de Execução Não Continuada"),
        ("obra", "Obras e Serviços de Engenharia"),
        ("locacao", "Locação de Imóvel"),
        ("solucao_ti", "Solução de TIC (Res. CNMP 283/2024)"),
    ]

    STATUS = [
        ("vigente", "Vigente"),
        ("suspenso", "Suspenso"),
        ("rescindido", "Rescindido"),
        ("encerrado", "Encerrado"),
    ]

    # Identificação
    numero_contrato = models.CharField(max_length=30)
    numero_sei = models.CharField(
        max_length=30,
        blank=True,
        help_text="Processo SEI/MPPI (campo obrigatório para rastreabilidade institucional)",
    )
    numero_pncp = models.CharField(
        max_length=100,
        blank=True,
        help_text="Publicação no PNCP — condição de eficácia (art. 174 NLLC)",
    )
    tipo = models.CharField(max_length=25, choices=TIPO)
    objeto = models.TextField()

    # Partes
    orgao = models.ForeignKey(
        "core.Orgao",
        on_delete=models.PROTECT,
        related_name="contratos",
    )
    contratado_razao_social = models.CharField(max_length=255)
    contratado_cnpj_cpf = models.CharField(max_length=18)

    # Valores
    valor_inicial = models.DecimalField(max_digits=16, decimal_places=2)
    valor_atual = models.DecimalField(
        max_digits=16,
        decimal_places=2,
        help_text="Atualizado automaticamente após aditivos de valor",
    )
    saldo_disponivel = models.DecimalField(
        max_digits=16,
        decimal_places=2,
        help_text="Saldo restante após ordens de fornecimento / medições",
    )

    # Código automático SIAFE (número interno de 8 dígitos, ex: 26100674)
    # Usado para cruzar com codContrato das Notas de Empenho
    codigo_siafe = models.CharField(
        max_length=12,
        blank=True,
        db_index=True,
        help_text="Número automático do contrato no SIAFE-PI (ex: 26100674)",
    )

    # Execução orçamentária (sincronizado do SIAFE via atualizar_execucao_siafe)
    valor_empenhado = models.DecimalField(
        max_digits=16,
        decimal_places=2,
        default=0,
        help_text="Total empenhado no SIAFE vinculado a este contrato",
    )
    ultima_atualizacao_siafe = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Última sincronização com o SIAFE-PI",
    )

    # Vigência
    data_assinatura = models.DateField()
    data_inicio_vigencia = models.DateField()
    data_fim_vigencia = models.DateField()
    data_publicacao_pncp = models.DateTimeField(null=True, blank=True)

    # Unidade que originou a demanda
    unidade_requisitante = models.ForeignKey(
        "core.UnidadeRequisitante",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="contratos",
        help_text="Unidade/setor que originou a demanda do contrato",
    )

    # Vínculo com processo
    item_pca = models.ForeignKey(
        "pca.ItemPCA",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="contratos",
    )
    arp_origem = models.ForeignKey(
        "srp.AtaRegistroPrecos",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="contratos_decorrentes",
        help_text="Preenchido quando o contrato decorre de ARP própria",
    )
    arp_externa_origem = models.ForeignKey(
        "srp.ARPExterna",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="contratos_mppi",
        help_text="Preenchido quando o contrato decorre de carona em ARP de outro órgão",
    )

    # Fiscalização (Res. CNMP 283/2024 para TI; Ato PGJ 1414/2024 para demais)
    gestor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        on_delete=models.SET_NULL,
        related_name="contratos_geridos",
    )
    fiscal_tecnico = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="contratos_fiscalizados_tec",
    )
    fiscal_administrativo = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="contratos_fiscalizados_adm",
    )

    status = models.CharField(max_length=15, choices=STATUS, default="vigente")
    observacoes = models.TextField(blank=True)
    criado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        on_delete=models.SET_NULL,
        related_name="contratos_criados",
    )
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Contrato"
        ordering = ["-data_assinatura"]
        unique_together = ("orgao", "numero_contrato")

    def __str__(self):
        return f"Contrato {self.numero_contrato} — {self.contratado_razao_social[:40]}"

    @property
    def dias_para_vencimento(self):
        from datetime import date
        return (self.data_fim_vigencia - date.today()).days

    @property
    def alerta_vigencia(self):
        """Retorna nível de alerta: 'critico', 'atencao', 'aviso' ou None."""
        dias = self.dias_para_vencimento
        if self.status != "vigente":
            return None
        if dias <= 30:
            return "critico"
        if dias <= 60:
            return "atencao"
        if dias <= 90:
            return "aviso"
        return None


    @property
    def licitacao_origem(self):
        from apps.licitacao.models import ProcessoLicitatorio
        if self.arp_origem and self.arp_origem.licitacao_origem:
            return self.arp_origem.licitacao_origem
        if self.numero_pncp:
            prefixo = self.numero_pncp.split('-0000')[0] if '-0000' in self.numero_pncp else self.numero_pncp
            obj = ProcessoLicitatorio.objects.filter(numero_controle_pncp__icontains=prefixo).first()
            if obj:
                return obj
        if self.numero_sei and len(self.numero_sei) > 5:
            obj = ProcessoLicitatorio.objects.filter(processo_sei__icontains=self.numero_sei).first()
            if obj:
                return obj
        obj = ProcessoLicitatorio.objects.filter(numero_controle_pncp=f"LOCAL-CT-{self.id}").first()
        if obj:
            return obj
        if self.numero_contrato:
            obj = ProcessoLicitatorio.objects.filter(objeto__icontains=self.numero_contrato).first()
            if obj:
                return obj
        return None


class Aditivo(models.Model):
    """
    Termo Aditivo ao contrato.
    Fundamento: art. 124 NLLC.
    Limite acumulado: 25% para obras/serviços de engenharia, 50% para demais.
    """

    TIPO = [
        ("prazo", "Prorrogação de Prazo"),
        ("valor", "Acréscimo de Valor"),
        ("supressao", "Supressão de Valor"),
        ("prazo_valor", "Prazo e Valor"),
        ("objeto", "Alteração de Objeto"),
    ]

    contrato = models.ForeignKey(
        Contrato,
        on_delete=models.CASCADE,
        related_name="aditivos",
    )
    numero_aditivo = models.PositiveIntegerField()
    numero_sei = models.CharField(max_length=30, blank=True)
    tipo = models.CharField(max_length=15, choices=TIPO)
    fundamento_legal = models.CharField(
        max_length=100,
        default="art. 124 NLLC (Lei 14.133/2021)",
        help_text="Fundamento legal do aditivo",
    )
    data_assinatura = models.DateField()
    nova_data_fim_vigencia = models.DateField(
        null=True,
        blank=True,
        help_text="Preenchido quando o aditivo altera o prazo",
    )
    valor_acrescimo = models.DecimalField(
        max_digits=16,
        decimal_places=2,
        default=0,
        help_text="Positivo para acréscimo, negativo para supressão",
    )
    percentual_acrescimo = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0,
        help_text="Percentual sobre o valor inicial do contrato",
    )
    numero_pncp = models.CharField(max_length=100, blank=True)
    objeto_aditivo = models.TextField()
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Termo Aditivo"
        verbose_name_plural = "Termos Aditivos"
        ordering = ["numero_aditivo"]
        unique_together = ("contrato", "numero_aditivo")

    def __str__(self):
        return f"{self.numero_aditivo}º Aditivo — {self.contrato.numero_contrato}"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        # Atualiza valor atual e vigência do contrato
        contrato = self.contrato
        if self.valor_acrescimo:
            contrato.valor_atual += self.valor_acrescimo
            contrato.saldo_disponivel += self.valor_acrescimo
        if self.nova_data_fim_vigencia:
            contrato.data_fim_vigencia = self.nova_data_fim_vigencia
        contrato.save(update_fields=["valor_atual", "saldo_disponivel", "data_fim_vigencia"])


class Apostilamento(models.Model):
    """
    Apostilamento — alteração unilateral sem necessidade de aditivo.
    Fundamento: art. 136 NLLC (reajuste, atualização monetária, repactuação).
    """

    TIPO = [
        ("reajuste", "Reajuste por Índice"),
        ("repactuacao", "Repactuação (serviços contínuos)"),
        ("atualizacao_monetaria", "Atualização Monetária"),
        ("correcao_erro", "Correção de Erro Material"),
    ]

    contrato = models.ForeignKey(
        Contrato,
        on_delete=models.CASCADE,
        related_name="apostilamentos",
    )
    numero_apostilamento = models.PositiveIntegerField()
    numero_sei = models.CharField(max_length=30, blank=True)
    tipo = models.CharField(max_length=25, choices=TIPO)
    fundamento_legal = models.CharField(
        max_length=100,
        default="art. 136 NLLC (Lei 14.133/2021)",
    )
    data_apostilamento = models.DateField()
    indice_aplicado = models.CharField(
        max_length=20,
        blank=True,
        help_text="Ex: IPCA, INPC, IPC-A",
    )
    percentual_reajuste = models.DecimalField(
        max_digits=6, decimal_places=4, default=0
    )
    valor_anterior = models.DecimalField(max_digits=16, decimal_places=2)
    valor_novo = models.DecimalField(max_digits=16, decimal_places=2)
    descricao = models.TextField()
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Apostilamento"
        ordering = ["numero_apostilamento"]
        unique_together = ("contrato", "numero_apostilamento")

    def __str__(self):
        return f"{self.numero_apostilamento}º Apostilamento — {self.contrato.numero_contrato}"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        # Atualiza valor atual do contrato
        self.contrato.valor_atual = self.valor_novo
        self.contrato.save(update_fields=["valor_atual"])


class OrdemFornecimento(models.Model):
    """
    Ordem de fornecimento / serviço emitida no âmbito de um contrato.
    Debita o saldo disponível do contrato.
    """

    STATUS = [
        ("emitida", "Emitida"),
        ("em_execucao", "Em execução"),
        ("concluida", "Concluída"),
        ("cancelada", "Cancelada"),
    ]

    contrato = models.ForeignKey(
        Contrato,
        on_delete=models.CASCADE,
        related_name="ordens_fornecimento",
    )
    numero_ordem = models.CharField(max_length=30)
    numero_sei = models.CharField(max_length=30, blank=True)
    descricao = models.TextField()
    valor = models.DecimalField(max_digits=16, decimal_places=2)
    data_emissao = models.DateField()
    data_prazo_execucao = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=15, choices=STATUS, default="emitida")
    unidade_requisitante = models.ForeignKey(
        "core.UnidadeRequisitante",
        null=True,
        on_delete=models.SET_NULL,
        related_name="ordens_fornecimento",
    )
    criado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        on_delete=models.SET_NULL,
        related_name="ordens_criadas",
    )
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Ordem de Fornecimento / Serviço"
        verbose_name_plural = "Ordens de Fornecimento / Serviço"

    def __str__(self):
        return f"OF {self.numero_ordem} — {self.contrato.numero_contrato}"

    def save(self, *args, **kwargs):
        if not self.pk:
            # Debita saldo do contrato
            self.contrato.saldo_disponivel -= self.valor
            self.contrato.save(update_fields=["saldo_disponivel"])
        super().save(*args, **kwargs)
