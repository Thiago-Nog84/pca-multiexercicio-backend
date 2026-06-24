from django.conf import settings
from django.db import models


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
    prazo_coleta_inicio = models.DateField(null=True, blank=True)
    prazo_coleta_fim = models.DateField(null=True, blank=True)
    prazo_consolidacao_fim = models.DateField(null=True, blank=True)
    prazo_aprovacao_fim = models.DateField(null=True, blank=True)
    data_aprovacao_pgj = models.DateField(null=True, blank=True)
    data_publicacao_pncp = models.DateTimeField(null=True, blank=True)
    pncp_sequencial = models.CharField(max_length=100, blank=True)
    aprovado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True,
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
    """

    STATUS = [
        ("rascunho", "Rascunho"),
        ("enviado", "Enviado ao setor de licitações"),
        ("aprovado", "Aprovado"),
        ("devolvido", "Devolvido para adequação"),
    ]

    pca = models.ForeignKey(PlanoContratacaoAnual, on_delete=models.CASCADE, related_name="dfds")
    unidade = models.ForeignKey("core.UnidadeRequisitante", on_delete=models.CASCADE)
    numero_sei = models.CharField(max_length=30, blank=True)
    numero_dfd = models.CharField(max_length=30, blank=True)
    descricao_objeto = models.TextField()
    justificativa = models.TextField()
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
    numero_item = models.PositiveIntegerField()
    categoria = models.CharField(max_length=20, choices=CATEGORIAS)
    codigo_catmat_catser = models.CharField(max_length=20, blank=True)
    unidade_fornecimento = models.CharField(max_length=30)
    quantidade_estimada = models.DecimalField(max_digits=14, decimal_places=4)
    descricao = models.TextField()
    tipo_contratacao = models.CharField(max_length=25, choices=TIPO_CONTRATACAO)
    valor_unitario_estimado = models.DecimalField(max_digits=14, decimal_places=2)
    valor_total_estimado = models.DecimalField(max_digits=16, decimal_places=2)
    data_vencimento_contrato_anterior = models.DateField(null=True, blank=True)
    data_pretendida_conclusao = models.DateField(null=True, blank=True)
    item_dependente = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="dependentes"
    )
    observacoes = models.TextField(blank=True)
    is_srp = models.BooleanField(default=False)
    justificativa_srp = models.TextField(blank=True)
    etp = models.ForeignKey(
        "planejamento.ETP", null=True, blank=True, on_delete=models.SET_NULL, related_name="itens_pca"
    )

    class Meta:
        verbose_name = "Item do PCA"
        ordering = ["numero_item"]

    def __str__(self):
        return f"Item {self.numero_item} — {self.descricao[:50]}"


class ConformidadeItem(models.Model):
    """
    Checklist de conformidade da fase de licitação/contratação e de execução
    contratual de um item do PCA.
    """

    FASE_LICITACAO_CONTRATACAO = [
        "termo_referencia_aprovado",
        "pesquisa_mercado",
        "pareceres_juridicos",
        "publicacao_edital",
        "atas_certame",
        "termo_homologacao",
        "termo_adjudicacao",
        "atos_autorizacao",
        "documentacao_fornecedor",
        "assinatura_contrato",
        "publicacao_contrato",
    ]

    FASE_EXECUCAO = [
        "documento_aceite",
        "justificativa_vantajosidade",
        "declaracao_conformidade",
        "pesquisa_precos",
        "mapa_comparativo",
        "certidoes_habilitacao",
        "margem_calculo",
        "parecer_orcamentario_financeiro",
        "parecer_juridico_execucao",
        "parecer_conint",
        "oficio_autorizacao_empenho",
        "atualizar_certidoes",
        "termo_aditivo_apostilamento",
        "publicacoes_execucao",
    ]

    item = models.OneToOneField(ItemPCA, on_delete=models.CASCADE, related_name="conformidade")

    # Fase 1 — Licitação e Contratação
    termo_referencia_aprovado = models.BooleanField(default=False)
    pesquisa_mercado = models.BooleanField(default=False)
    pareceres_juridicos = models.BooleanField(default=False)
    publicacao_edital = models.BooleanField(default=False)
    atas_certame = models.BooleanField(default=False)
    termo_homologacao = models.BooleanField(default=False)
    termo_adjudicacao = models.BooleanField(default=False)
    atos_autorizacao = models.BooleanField(default=False)
    documentacao_fornecedor = models.BooleanField(default=False)
    assinatura_contrato = models.BooleanField(default=False)
    publicacao_contrato = models.BooleanField(default=False)

    # Fase 2 — Execução Contratual
    documento_aceite = models.BooleanField(default=False)
    justificativa_vantajosidade = models.BooleanField(default=False)
    declaracao_conformidade = models.BooleanField(default=False)
    pesquisa_precos = models.BooleanField(default=False)
    mapa_comparativo = models.BooleanField(default=False)
    certidoes_habilitacao = models.BooleanField(default=False)
    margem_calculo = models.BooleanField(default=False)
    parecer_orcamentario_financeiro = models.BooleanField(default=False)
    parecer_juridico_execucao = models.BooleanField(default=False)
    parecer_conint = models.BooleanField(default=False)
    oficio_autorizacao_empenho = models.BooleanField(default=False)
    atualizar_certidoes = models.BooleanField(default=False)
    termo_aditivo_apostilamento = models.BooleanField(default=False)
    publicacoes_execucao = models.BooleanField(default=False)

    observacao = models.TextField(blank=True)
    avaliado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="conformidades_avaliadas"
    )
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Conformidade do Item"

    @property
    def percentual_conformidade(self):
        campos = self.FASE_LICITACAO_CONTRATACAO + self.FASE_EXECUCAO
        marcados = sum(1 for c in campos if getattr(self, c))
        return round((marcados / len(campos)) * 100)

    def __str__(self):
        return f"Conformidade — Item {self.item_id} ({self.percentual_conformidade}%)"
