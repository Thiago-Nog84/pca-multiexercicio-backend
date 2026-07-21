import random
import string
from datetime import timedelta

from django.conf import settings
from django.db import models

# ---------------------------------------------------------------------------
# Classificação de continuidade — Ato PGJ 1.415/2024
# Compartilhada por ItemCatalogo e ItemPCA.
# ---------------------------------------------------------------------------
CLASSIFICACAO_CONTINUIDADE = [
    ("continuo_fornecimento", "Fornecimento contínuo (Art. 3º — Ato PGJ 1.415/2024)"),
    ("continuo_servico",      "Serviço contínuo (Art. 4º — Ato PGJ 1.415/2024)"),
    ("continuo_servico_mdo",  "Serviço contínuo c/ ded. exclusiva de MO (Art. 4º §1º — Ato PGJ 1.415/2024)"),
    ("eventual",              "Eventual / pontual"),
]

# ---------------------------------------------------------------------------
# Categoria do item — granularidade inspirada na "Classe" do sistema de
# referência (separa Material de Consumo de Material Permanente, e trata
# Serviço de Engenharia / Terceirizado / Treinamento / Software como classes
# próprias, o que importa para a classificação orçamentária).
# Compartilhada por ItemPCA e ItemCatalogo.
# ---------------------------------------------------------------------------
CATEGORIAS_ITEM = [
    ("material",              "Material de Consumo (CATMAT)"),
    ("material_permanente",   "Material Permanente (CATMAT)"),
    ("servico",                "Serviço (CATSER)"),
    ("servico_engenharia",     "Serviço de Engenharia"),
    ("servico_terceirizado",   "Serviço Terceirizado (dedicação exclusiva de mão de obra)"),
    ("obras",                  "Obras e Serviços de Engenharia"),
    ("solucao_ti",             "Solução de TIC (Res. CNMP 283/2024)"),
    ("software",               "Software"),
    ("treinamento",            "Treinamento"),
    ("publicidade",            "Publicidade (Dec. 21.813/2023)"),
]


class PlanoContratacaoAnual(models.Model):
    """
    PCA do MPPI para um exercício fiscal.
    Fluxo de status baseado no Ato PGJ 1381/2024, arts. 10-12.
    """

    STATUS = [
        ("coleta", "Coleta de demandas (10-30 jul)"),
        ("consolidacao", "Consolidação CLC + APG (1-20 ago)"),
        ("aprovacao", "Aguardando aprovação PGJ"),
        ("aprovado", "Aprovado pelo PGJ"),
        ("publicado_pncp", "Publicado no PNCP"),
        ("revisao_out", "Em revisão (1-30 out)"),
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
        ("suspensa", "Suspensa"),
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

    Cada item representa uma demanda de contratação de uma unidade requisitante.
    O código PCA é gerado automaticamente no formato PCA-XXXX-AAAA ao salvar.
    """

    CATEGORIAS = CATEGORIAS_ITEM

    # Tipo da demanda: o QUE é (natureza da contratação)
    TIPO_DEMANDA = [
        ("nova", "Nova Contratação"),
        ("renovacao", "Renovação de Contrato"),
        ("aditivo", "Termo Aditivo"),
        ("apostilamento", "Apostilamento"),
        ("repactuacao", "Repactuação"),
        ("indeterminado", "Indeterminado"),
    ]

    # Modalidade: COMO será feita (instrumento legal)
    MODALIDADE = [
        ("pregao_eletronico", "Pregão Eletrônico"),
        ("concorrencia", "Concorrência"),
        ("concurso", "Concurso"),
        ("dispensa", "Contratação Direta — Dispensa (art. 75 NLLC)"),
        ("inexigibilidade", "Contratação Direta — Inexigibilidade (art. 74 NLLC)"),
        ("arp_propria", "ARP Própria (MPPI como gerenciador)"),
        ("arp_carona", "ARP Carona (adesão a ARP de outro órgão)"),
    ]

    NORMATIVO = [
        ("14133_2021", "Lei 14.133/2021 (NLLC)"),
        ("8666_1993", "Lei 8.666/1993 (transitório)"),
    ]

    # Unidade Orçamentária — diferente do setor requisitante
    UNIDADE_ORCAMENTARIA = [
        ("pgj", "PGJ — Procuradoria-Geral de Justiça"),
        ("fmmp", "FMMP — Fundo de Modernização do Ministério Público"),
        ("fepdc", "FEPDC — Fundo Estadual de Proteção e Defesa do Consumidor"),
    ]

    STATUS = [
        ("nao_iniciado", "Não Iniciado"),
        ("pendente_validacao", "Pendente de Validação"),
        ("iniciado", "Iniciado"),
        ("em_diligencia", "Em Diligência"),
        ("em_andamento", "Em Andamento"),
        ("concluido", "Concluído"),
        ("suspenso", "Suspenso"),
    ]

    # Identificação
    codigo_pca = models.CharField(
        max_length=20,
        blank=True,
        unique=True,
        help_text="Gerado automaticamente no formato PCA-XXXX-AAAA",
    )
    dfd = models.ForeignKey(DocumentoFormalizacaoDemanda, on_delete=models.CASCADE, related_name="itens")
    numero_item = models.PositiveIntegerField()

    # Suspensão
    TIPO_SUSPENSAO = [
        ("total", "Total"),
        ("parcial", "Parcial"),
    ]
    tipo_suspensao = models.CharField(
        max_length=10,
        choices=TIPO_SUSPENSAO,
        blank=True,
        null=True,
        help_text="Preenchido quando status=suspenso: total ou parcial",
    )

    # Suspensão parcial (Pai/Filha)
    item_pai = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="itens_filhos",
        help_text="Preenchido apenas em suspensões parciais — aponta para o item original (pai)",
    )

    # Objeto
    categoria = models.CharField(max_length=20, choices=CATEGORIAS)
    codigo_catmat_catser = models.CharField(max_length=20, blank=True)
    descricao = models.TextField()
    unidade_fornecimento = models.CharField(max_length=30)
    quantidade_estimada = models.DecimalField(max_digits=14, decimal_places=4)
    valor_unitario_estimado = models.DecimalField(max_digits=14, decimal_places=2)
    valor_total_estimado = models.DecimalField(max_digits=16, decimal_places=2)

    # Execução financeira
    valor_empenhado = models.DecimalField(
        max_digits=16,
        decimal_places=2,
        default=0,
        help_text="Valor efetivamente empenhado — atualizado conforme execução orçamentária",
    )

    # Tipo e modalidade (separados — natureza vs. instrumento legal)
    tipo_demanda = models.CharField(max_length=20, choices=TIPO_DEMANDA, default="nova")
    modalidade = models.CharField(max_length=20, choices=MODALIDADE, default="pregao_eletronico")
    normativo = models.CharField(
        max_length=15,
        choices=NORMATIVO,
        default="14133_2021",
        help_text="Normativo regente da contratação",
    )
    unidade_orcamentaria = models.CharField(
        max_length=10,
        choices=UNIDADE_ORCAMENTARIA,
        default="pgj",
        help_text="Unidade orçamentária responsável pelo recurso (PGJ, FMMP ou FEPDC)",
    )

    # Prazos
    data_vencimento_contrato_anterior = models.DateField(null=True, blank=True)
    data_pretendida_conclusao = models.DateField(null=True, blank=True)

    # Datas de acompanhamento do processo
    data_envio_pgea = models.DateField(
        null=True, blank=True,
        help_text="Data de encaminhamento ao fluxo administrativo (PGEA)",
    )
    data_finalizacao_licitacao = models.DateField(
        null=True, blank=True,
        help_text="Data efetiva de finalização do certame licitatório",
    )
    data_conclusao_efetiva = models.DateField(
        null=True, blank=True,
        help_text="Data de conclusão com contrato assinado",
    )

    # Status e rastreabilidade
    status = models.CharField(max_length=20, choices=STATUS, default="nao_iniciado")
    observacoes = models.TextField(blank=True)

    # SRP
    is_srp = models.BooleanField(default=False)
    justificativa_srp = models.TextField(blank=True)
    numero_lote_pca = models.CharField(
        max_length=20,
        blank=True,
        help_text=(
            "Número do lote ao qual este item pertence na licitação/ARP. "
            "Deve espelhar o numero_lote do ItemARP correspondente. "
            "Itens com o mesmo numero_lote_pca são tratados como unidade "
            "para fins de PCA e exibição no dashboard."
        ),
    )

    # Catálogo e continuidade (Ato PGJ 1.415/2024)
    item_catalogo = models.ForeignKey(
        "ItemCatalogo",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="itens_pca",
        help_text=(
            "Item do catálogo institucional que originou esta demanda. "
            "Pré-preenche descrição, categoria e classificação de continuidade."
        ),
    )
    classificacao_continuidade = models.CharField(
        max_length=30,
        choices=CLASSIFICACAO_CONTINUIDADE,
        default="eventual",
        help_text="Classificação conforme Ato PGJ 1.415/2024",
    )

    # Linhagem multiexercício
    origem_item = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="renovacoes",
        help_text=(
            "Item do exercício anterior que originou esta renovação/continuidade. "
            "Permite rastrear a evolução da despesa ao longo dos anos."
        ),
    )

    # Planejamento
    etp = models.ForeignKey(
        "planejamento.ETP", null=True, blank=True, on_delete=models.SET_NULL, related_name="itens_pca"
    )

    # Atendimento por contrato vigente (alternativa à ARP para tipo_demanda
    # renovacao/aditivo/apostilamento/repactuacao) — evita nova licitação
    # quando um contrato já em vigor cobre a demanda.
    contrato_vigente = models.ForeignKey(
        "contratos.Contrato",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="itens_pca_atendidos",
        help_text=(
            "Contrato vigente que já atende esta demanda (renovação, aditivo, "
            "repactuação ou apostilamento), dispensando nova licitação. "
            "Preenchido ao vincular pela busca de contratos vigentes no cadastro em grupo."
        ),
    )

    class Meta:
        verbose_name = "Item do PCA"
        ordering = ["numero_item"]

    def __str__(self):
        codigo = self.codigo_pca or f"Item {self.numero_item}"
        return f"{codigo} — {self.descricao[:50]}"

    @property
    def data_inicio_prevista(self):
        """
        Calcula automaticamente a data de início prevista com base no tipo
        de demanda, modalidade e data de conclusão.

        Regras (Tutorial PCA-MPPI, pág. 14):
          - Nova + Pregão/Concorrência/Concurso → conclusão − 150 dias
          - Nova + Dispensa/Inexigibilidade      → conclusão − 90 dias
          - Demais (Renovação, Aditivo, etc.)    → conclusão − 120 dias
        """
        if not self.data_pretendida_conclusao:
            return None

        modalidades_licitacao = {"pregao_eletronico", "concorrencia", "concurso"}
        modalidades_diretas = {"dispensa", "inexigibilidade"}

        if self.tipo_demanda == "nova" and self.modalidade in modalidades_licitacao:
            return self.data_pretendida_conclusao - timedelta(days=150)
        elif self.tipo_demanda == "nova" and self.modalidade in modalidades_diretas:
            return self.data_pretendida_conclusao - timedelta(days=90)
        else:
            return self.data_pretendida_conclusao - timedelta(days=120)

    @property
    def percentual_executado(self):
        """Percentual do valor empenhado em relação ao valor total estimado."""
        if not self.valor_total_estimado:
            return 0
        return round((self.valor_empenhado / self.valor_total_estimado) * 100, 1)

    @property
    def is_filho(self):
        """Indica se este item é resultado de uma suspensão parcial."""
        return self.item_pai_id is not None

    def _gerar_codigo_pca(self):
        """Gera código único no formato PCA-XXXX-AAAA."""
        exercicio = self.dfd.pca.exercicio
        while True:
            sufixo = ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))
            codigo = f"PCA-{sufixo}-{exercicio}"
            if not ItemPCA.objects.filter(codigo_pca=codigo).exists():
                return codigo

    def save(self, *args, **kwargs):
        if not self.codigo_pca:
            self.codigo_pca = self._gerar_codigo_pca()
        super().save(*args, **kwargs)


class ItemCatalogo(models.Model):
    """
    Catálogo institucional de itens de contratação do MPPI.

    Serve como biblioteca de referência para agilizar o cadastro de DFDs,
    pré-preenchendo campos e sinalizando a classificação de continuidade
    conforme o Ato PGJ 1.415/2024.

    Itens com classificação 'continuo_*' são automaticamente propostos para
    renovação no planejamento do exercício seguinte.
    """

    CATEGORIAS = CATEGORIAS_ITEM

    MODALIDADES_SUGERIDAS = [
        ("pregao_eletronico", "Pregão Eletrônico"),
        ("concorrencia",      "Concorrência"),
        ("dispensa",          "Contratação Direta — Dispensa"),
        ("inexigibilidade",   "Contratação Direta — Inexigibilidade"),
    ]

    codigo_catalogo = models.CharField(
        max_length=20,
        unique=True,
        help_text="Código no formato CONT-FORN-001, CONT-SERV-001, CONT-MDO-001",
    )
    descricao_padrao = models.CharField(max_length=300)
    categoria = models.CharField(max_length=20, choices=CATEGORIAS)
    classificacao = models.CharField(
        max_length=30,
        choices=CLASSIFICACAO_CONTINUIDADE,
        default="eventual",
        db_index=True,
    )
    base_normativa = models.CharField(
        max_length=150,
        blank=True,
        help_text="Ex: Art. 3, I — Ato PGJ 1.415/2024",
    )
    codigo_catmat_catser = models.CharField(max_length=20, blank=True)
    descricao_detalhada = models.TextField(
        blank=True,
        help_text="Especificação completa do item (catálogo interno 2027).",
    )
    grupo = models.CharField(
        max_length=100,
        blank=True,
        db_index=True,
        help_text="Grupo do catálogo interno (ex: Copa e Cozinha, Informática - Equipamentos).",
    )
    valor_referencia = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Valor unitário de referência do catálogo interno.",
    )
    unidade_medida_padrao = models.CharField(max_length=30, blank=True)
    modalidade_sugerida = models.CharField(
        max_length=20,
        choices=MODALIDADES_SUGERIDAS,
        blank=True,
    )
    ativo = models.BooleanField(default=True)
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Item do Catalogo"
        verbose_name_plural = "Catalogo de Itens"
        ordering = ["classificacao", "descricao_padrao"]

    def __str__(self):
        return f"{self.codigo_catalogo} — {self.descricao_padrao[:60]}"

    @property
    def is_continuo(self):
        return self.classificacao.startswith("continuo_")


# ---------------------------------------------------------------------------
# Orçamento Planejado por Unidade Orçamentária
# Registra o teto orçamentário aprovado por setor/exercício, segregado
# por unidade orçamentária (PGJ, FMMP, FEPDC).
# ---------------------------------------------------------------------------

class OrcamentoPlanejado(models.Model):
    """
    Teto orçamentário de um setor requisitante para um determinado exercício,
    segregado por unidade orçamentária (PGJ, FMMP e FEPDC).

    A 'trava_ativa' impede que o setor cadastre novas demandas que
    ultrapassem o limite aprovado.
    """

    pca = models.ForeignKey(
        PlanoContratacaoAnual,
        on_delete=models.CASCADE,
        related_name="orcamentos",
        verbose_name="PCA",
    )
    unidade = models.ForeignKey(
        "core.UnidadeRequisitante",
        on_delete=models.CASCADE,
        related_name="orcamentos",
        verbose_name="Setor requisitante",
    )
    valor_pgj = models.DecimalField(
        max_digits=16, decimal_places=2, default=0,
        verbose_name="Teto PGJ",
        help_text="Valor aprovado com recursos da Procuradoria-Geral de Justica",
    )
    valor_fmmp = models.DecimalField(
        max_digits=16, decimal_places=2, default=0,
        verbose_name="Teto FMMP",
        help_text="Valor aprovado com recursos do FMMP",
    )
    valor_fepdc = models.DecimalField(
        max_digits=16, decimal_places=2, default=0,
        verbose_name="Teto FEPDC",
        help_text="Valor aprovado com recursos do FEPDC",
    )
    trava_ativa = models.BooleanField(
        default=False,
        verbose_name="Trava ativa",
        help_text="Quando ativa, bloqueia demandas que ultrapassem o teto aprovado",
    )
    atualizado_em = models.DateTimeField(auto_now=True)
    atualizado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="orcamentos_atualizados",
    )

    class Meta:
        unique_together = ("pca", "unidade")
        verbose_name = "Orcamento Planejado"
        verbose_name_plural = "Orcamentos Planejados"
        ordering = ["pca", "unidade"]

    def __str__(self):
        return f"Orcamento {self.unidade.sigla} — PCA {self.pca.exercicio}"

    @property
    def valor_total(self):
        return self.valor_pgj + self.valor_fmmp + self.valor_fepdc

    def valor_comprometido(self):
        """Soma dos valores estimados dos ItemPCA ativos do setor neste PCA."""
        from django.db.models import Sum
        total = (
            ItemPCA.objects
            .filter(dfd__pca=self.pca, dfd__unidade=self.unidade)
            .exclude(status="suspenso")
            .aggregate(s=Sum("valor_total_estimado"))["s"]
        ) or 0
        return total

    def saldo_disponivel(self):
        return self.valor_total - self.valor_comprometido()

    def percentual_comprometido(self):
        if not self.valor_total:
            return 0
        return round((self.valor_comprometido() / self.valor_total) * 100, 1)


# ---------------------------------------------------------------------------
# Conformidade do Item PCA
# Checklist de documentos exigidos para a instrucao processual.
# ---------------------------------------------------------------------------

class ConformidadeItem(models.Model):
    """
    Checklist de conformidade documental de um ItemPCA.
    Registra quais documentos obrigatorios foram juntados ao processo.
    """

    item = models.OneToOneField(
        ItemPCA,
        on_delete=models.CASCADE,
        related_name="conformidade",
    )

    # Planejamento
    termo_referencia_aprovado   = models.BooleanField(default=False)
    pesquisa_mercado            = models.BooleanField(default=False)
    pareceres_juridicos         = models.BooleanField(default=False)
    mapa_comparativo            = models.BooleanField(default=False)
    margem_calculo              = models.BooleanField(default=False)
    pesquisa_precos             = models.BooleanField(default=False)

    # Licitacao
    publicacao_edital           = models.BooleanField(default=False)
    atas_certame                = models.BooleanField(default=False)
    termo_homologacao           = models.BooleanField(default=False)
    termo_adjudicacao           = models.BooleanField(default=False)
    justificativa_vantajosidade = models.BooleanField(default=False)

    # Habilitacao e contrato
    documentacao_fornecedor     = models.BooleanField(default=False)
    certidoes_habilitacao       = models.BooleanField(default=False)
    assinatura_contrato         = models.BooleanField(default=False)
    publicacao_contrato         = models.BooleanField(default=False)
    declaracao_conformidade     = models.BooleanField(default=False)
    atos_autorizacao            = models.BooleanField(default=False)
    oficio_autorizacao_empenho  = models.BooleanField(default=False)

    # Execucao
    parecer_orcamentario_financeiro = models.BooleanField(default=False)
    parecer_juridico_execucao       = models.BooleanField(default=False)
    parecer_conint                  = models.BooleanField(default=False)
    documento_aceite                = models.BooleanField(default=False)
    atualizar_certidoes             = models.BooleanField(default=False)
    termo_aditivo_apostilamento     = models.BooleanField(default=False)
    publicacoes_execucao            = models.BooleanField(default=False)

    observacao = models.TextField(blank=True)

    avaliado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="conformidades_avaliadas",
    )
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Conformidade do Item"
        verbose_name_plural = "Conformidade dos Itens"

    def __str__(self):
        return f"Conformidade — {self.item}"

    @property
    def percentual_conformidade(self):
        campos = [
            self.termo_referencia_aprovado, self.pesquisa_mercado,
            self.pareceres_juridicos, self.mapa_comparativo,
            self.margem_calculo, self.pesquisa_precos,
            self.publicacao_edital, self.atas_certame,
            self.termo_homologacao, self.termo_adjudicacao,
            self.justificativa_vantajosidade, self.documentacao_fornecedor,
            self.certidoes_habilitacao, self.assinatura_contrato,
            self.publicacao_contrato, self.declaracao_conformidade,
            self.atos_autorizacao, self.oficio_autorizacao_empenho,
            self.parecer_orcamentario_financeiro, self.parecer_juridico_execucao,
            self.parecer_conint, self.documento_aceite,
            self.atualizar_certidoes, self.termo_aditivo_apostilamento,
            self.publicacoes_execucao,
        ]
        marcados = sum(1 for c in campos if c)
        return round(marcados / len(campos) * 100)


class HistoricoFasePCA(models.Model):
    """
    Trilha de auditoria das mudanças de fase do PCA (workflow do
    Ato PGJ 1381/2024, arts. 10-12). Cada avanço/recuo de status feito
    pelo painel de fases gera um registro imutável: quem, quando,
    de onde para onde e justificativa.
    """

    pca = models.ForeignKey(
        PlanoContratacaoAnual,
        on_delete=models.CASCADE,
        related_name="historico_fases",
    )
    de_status = models.CharField(max_length=20, choices=PlanoContratacaoAnual.STATUS)
    para_status = models.CharField(max_length=20, choices=PlanoContratacaoAnual.STATUS)
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        on_delete=models.SET_NULL,
        related_name="mudancas_fase_pca",
    )
    observacao = models.TextField(
        blank=True,
        help_text="Justificativa da mudança de fase (obrigatória ao recuar)",
    )
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Histórico de Fase do PCA"
        verbose_name_plural = "Históricos de Fase do PCA"
        ordering = ["-criado_em"]

    def __str__(self):
        return f"PCA {self.pca.exercicio}: {self.de_status} → {self.para_status}"
