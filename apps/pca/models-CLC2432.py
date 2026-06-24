from django.conf import settings
from django.db import models

# Base legal: Ato PGJ 1381/2024 + art. 12, VII, NLLC + art. 8º Decreto 21.872/2023


class PlanoContratacaoAnual(models.Model):
    """
    PCA do MPPI para um exercício fiscal.
    Fluxo de status baseado no Ato PGJ 1381/2024, arts. 10–12.
    """

    STATUS = [
        ("coleta", "Coleta de demandas (10–30 jul)"),
        ("consolidacao", "Consolidação CLC + APG (1–20 ago)"),
        ("aprovacao", "Aguardando aprovação PGJ"),
        ("aprovado", "Aprovado pelo PGJ"),
        ("publicado_pncp", "Publicado no PNCP"),
        ("revisao_out", "Em revisão (1–30 out)"),
        ("revisao_loa", "Em revisão pós-LOA"),
    ]

    orgao = models.ForeignKey("core.Orgao", on_delete=models.CASCADE)
    exercicio = models.PositiveIntegerField()
    status = models.CharField(max_length=20, choices=STATUS, default="coleta")
    # Datas do calendário (Ato PGJ 1381/2024)
    prazo_coleta_inicio = models.DateField(null=True, blank=True)  # 10 jul
    prazo_coleta_fim = models.DateField(null=True, blank=True)  # 30 jul
    prazo_consolidacao_fim = models.DateField(null=True, blank=True)  # 20 ago
    prazo_aprovacao_fim = models.DateField(null=True, blank=True)  # 30 ago
    data_aprovacao_pgj = models.DateField(null=True, blank=True)
    data_publicacao_pncp = models.DateTimeField(null=True, blank=True)
    pncp_sequencial = models.CharField(max_length=100, blank=True)
    aprovado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="pcas_aprovados",
    )
    observacoes_pgj = models.TextField(blank=True)
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("orgao", "exercicio")
        verbose_name = "Plano de Contratação Anual"
        ordering = ["-exercicio"]

    def __str__(self):
        return f"PCA {self.exercicio}"


class DocumentoFormalizacaoDemanda(models.Model):
    """
    DFD — Documento de Formalização de Demanda.
    Fundamenta a inclusão do item no PCA (Ato PGJ 1381/2024, art. 8º, I).
    Elaborado pela unidade requisitante; instrução no SEI.
    """

    STATUS = [
        ("rascunho", "Rascunho"),
        ("enviado", "Enviado ao setor de licitações"),
        ("aprovado", "Aprovado"),
        ("devolvido", "Devolvido para adequação"),
    ]

    pca = models.ForeignKey(PlanoContratacaoAnual, on_delete=models.CASCADE, related_name="dfds")
    unidade = models.ForeignKey("core.UnidadeRequisitante", on_delete=models.CASCADE)
    numero_sei = models.CharField(
        max_length=30, blank=True, help_text="Número do processo SEI/MPPI onde está autuado o DFD"
    )
    numero_dfd = models.CharField(max_length=30, blank=True)
    descricao_objeto = models.TextField()
    justificativa = models.TextField(help_text="Motivação da necessidade; base: art. 6º Ato PGJ 1381/2024")
    prazo_necessidade = models.DateField()
    grau_prioridade = models.CharField(
        max_length=10, choices=[("baixo", "Baixo"), ("medio", "Médio"), ("alto", "Alto")]
    )
    status = models.CharField(max_length=15, choices=STATUS, default="rascunho")
    requisitante = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="dfds_requisitados",
    )
    criado_em = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.numero_dfd or f"DFD #{self.pk}"


class ItemPCA(models.Model):
    """
    Item individual do PCA (Ato PGJ 1381/2024, art. 7º).
    Inclui todos os campos obrigatórios listados nos incisos I–XIII do art. 7º.
    """

    CATEGORIAS = [
        ("material", "Material (CATMAT)"),
        ("servico", "Serviço (CATSER)"),
        ("obras", "Obras e Serviços de Engenharia"),
        ("solucao_ti", "Solução de TIC (Res. CNMP 283/2024)"),
        ("publicidade", "Publicidade (Dec. 21.813/2023)"),
    ]

    TIPO_CONTRATACAO = [
        ("licitacao", "Licitação"),
        ("dispensa", "Contratação Direta — Dispensa"),
        ("inexigibilidade", "Contratação Direta — Inexigibilidade"),
        ("adesao_arp", "Adesão a ARP (Carona)"),
        ("renovacao_contrato", "Renovação de Contrato"),
        ("renovacao_arp", "Prorrogação de ARP"),
    ]

    dfd = models.ForeignKey(DocumentoFormalizacaoDemanda, on_delete=models.CASCADE, related_name="itens")
    numero_item = models.PositiveIntegerField(help_text="Inciso I — art. 7º Ato 1381/2024")
    # Inciso I: tipo e código do item
    categoria = models.CharField(max_length=20, choices=CATEGORIAS)
    codigo_catmat_catser = models.CharField(
        max_length=20, blank=True, help_text="§1º (segundo) art. 7º — nível de classe mínimo"
    )
    # Inciso II: unidade de fornecimento
    unidade_fornecimento = models.CharField(max_length=30)
    # Inciso III: quantidade
    quantidade_estimada = models.DecimalField(max_digits=14, decimal_places=4)
    # Inciso IV: descrição sucinta
    descricao = models.TextField()
    # Inciso V: justificativa (herdada do DFD)
    # Inciso VI: tipo de contratação
    tipo_contratacao = models.CharField(max_length=25, choices=TIPO_CONTRATACAO)
    # Inciso VII: estimativa preliminar de valor
    valor_unitario_estimado = models.DecimalField(max_digits=14, decimal_places=2)
    valor_total_estimado = models.DecimalField(max_digits=16, decimal_places=2)
    # Inciso VIII: grau de prioridade (herdado do DFD)
    # Inciso IX: data de vencimento do contrato anterior
    data_vencimento_contrato_anterior = models.DateField(null=True, blank=True)
    # Inciso X: data pretendida para conclusão
    data_pretendida_conclusao = models.DateField(null=True, blank=True)
    # Inciso XI: vinculação/dependência
    item_dependente = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="dependentes"
    )
    # Inciso XII: área requisitante e responsável (no DFD)
    # Inciso XIII: outras informações
    observacoes = models.TextField(blank=True)
    # SRP
    is_srp = models.BooleanField(default=False, help_text="Será contratado via SRP (art. 82 NLLC)")
    justificativa_srp = models.TextField(blank=True)
    # Rastreabilidade
    etp = models.ForeignKey(
        "planejamento.ETP", null=True, blank=True, on_delete=models.SET_NULL, related_name="itens_pca"
    )

    class Meta:
        verbose_name = "Item do PCA"
        ordering = ["numero_item"]

    def __str__(self):
        return f"Item {self.numero_item} — {self.descricao[:50]}"
