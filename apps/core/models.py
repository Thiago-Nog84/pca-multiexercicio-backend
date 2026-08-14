from django.conf import settings
from django.db import models


class Orgao(models.Model):
    """
    Representa o MPPI e seus fundos (FPROCON, etc.).
    O MPPI é órgão do MP estadual — não integra o Executivo.
    """

    nome = models.CharField(max_length=255, default="Ministério Público do Estado do Piauí")
    sigla = models.CharField(max_length=20, default="MPPI")
    cnpj = models.CharField(max_length=18, unique=True)
    pncp_codigo_orgao = models.CharField(max_length=50, blank=True)
    uf = models.CharField(max_length=2, default="PI")
    esfera = models.CharField(max_length=20, default="estadual_mp")
    ativo = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Órgão"

    def __str__(self):
        return self.sigla


class UnidadeRequisitante(models.Model):
    """
    Unidades requisitantes do MPPI conforme Ato PGJ 1381/2024, art. 7º, §1º.
    """

    UNIDADES_FIXAS = [
        ("CPPT", "CPPT — Coordenadoria de Perícias e Pareceres Técnicos"),
        ("CTI", "CTI — Coordenadoria de Tecnologia da Informação"),
        ("CAA", "CAA — Coordenadoria de Apoio Administrativo"),
        ("CRH", "CRH — Coordenadoria de Recursos Humanos"),
        ("GSI", "GSI — Gerência de Segurança Institucional"),
        ("CEAF", "CEAF — Centro de Estudos e Aperfeiçoamento Funcional"),
        ("CI", "CI — Coordenadoria de Infraestrutura"),
        ("CLC", "CLC — Coordenadoria de Licitações e Contratos"),
        ("CCF", "CCF — Coordenadoria de Contabilidade e Finanças"),
        ("APG", "APG — Assessoria de Planejamento e Gestão"),
        ("CONINT", "CONINT — Controle Interno"),
        ("GAECO", "GAECO — Grupo de Atuação Especial Contra o Crime Organizado"),
        ("FPROCON", "FPROCON — Fundo de Proteção ao Consumidor"),
        ("CCS", "CCS — Coordenadoria de Comunicação Social"),
    ]

    orgao = models.ForeignKey(Orgao, on_delete=models.CASCADE, related_name="unidades")
    sigla = models.CharField(max_length=20, choices=UNIDADES_FIXAS)
    nome = models.CharField(max_length=255)
    responsavel = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        on_delete=models.SET_NULL,
        related_name="unidades_responsavel",
    )
    ativo = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Unidade Requisitante"

    def __str__(self):
        return self.sigla


class Perfil(models.Model):
    """
    Perfis de acesso conforme os normativos do MPPI.
    """

    PERFIS = [
        ("requisitante", "Requisitante (art. 7º Ato PGJ 1381/2024)"),
        ("area_tecnica", "Área Técnica"),
        ("apg", "APG — Assessoria de Planejamento e Gestão"),
        ("assessor_compras", "Assessor de Compras / Agente de Contratação"),
        ("equipe_apoio", "Equipe de Apoio (Ato PGJ 1414/2024)"),
        ("comissao", "Membro de Comissão de Contratação"),
        ("appl", "APPL — Assessoria para Pareceres em Processos Licitatórios"),
        ("gestor_contrato", "Gestor de Contrato"),
        ("fiscal_adm", "Fiscal Administrativo"),
        ("fiscal_tecnico", "Fiscal Técnico"),
        ("fiscal_requisitante", "Fiscal Requisitante (TI — Res. CNMP 283/2024)"),
        ("int_requisitante_ti", "Integrante Requisitante TI (Res. CNMP 283/2024)"),
        ("int_tecnico_ti", "Integrante Técnico TI (Res. CNMP 283/2024)"),
        ("int_administrativo_ti", "Integrante Administrativo TI (Res. CNMP 283/2024)"),
        ("autoridade", "Autoridade Competente (PGJ ou delegado)"),
        ("auditor", "Auditor Interno"),
    ]

    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    orgao = models.ForeignKey(Orgao, on_delete=models.CASCADE)
    perfil = models.CharField(max_length=30, choices=PERFIS)
    unidade = models.ForeignKey(UnidadeRequisitante, null=True, blank=True, on_delete=models.SET_NULL)
    ativo = models.BooleanField(default=True)

    class Meta:
        unique_together = ("usuario", "orgao", "perfil")
        verbose_name = "Perfil de Acesso"

    def __str__(self):
        return f"{self.usuario} — {self.perfil}"


class Notificacao(models.Model):
    """
    Aviso in-app publicado para os usuários do sistema.

    Pode ser geral (unidade_destino vazia) ou dirigido a uma unidade
    requisitante específica. A "exclusão" é lógica (ativa=False), para
    preservar o histórico de leitura em NotificacaoLida.
    """

    TIPOS = [
        ("info", "Informativo"),
        ("alerta", "Alerta"),
        ("prazo", "Prazo"),
        ("sucesso", "Sucesso"),
    ]

    # Classe de contexto do Bootstrap por tipo — usada nos templates.
    CSS_POR_TIPO = {
        "info": "primary",
        "alerta": "warning",
        "prazo": "danger",
        "sucesso": "success",
    }

    ICONE_POR_TIPO = {
        "info": "bi-info-circle",
        "alerta": "bi-exclamation-triangle",
        "prazo": "bi-alarm",
        "sucesso": "bi-check-circle",
    }

    titulo = models.CharField(max_length=120)
    mensagem = models.TextField(max_length=500)
    tipo = models.CharField(max_length=15, choices=TIPOS, default="info")
    unidade_destino = models.ForeignKey(
        UnidadeRequisitante,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="notificacoes",
        help_text="Deixe em branco para enviar a todos os usuários.",
    )
    url_destino = models.CharField(
        max_length=300,
        blank=True,
        help_text="Link opcional para a tela relacionada (ex: /contratos/vencimentos/).",
    )
    autor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="notificacoes_criadas",
    )
    ativa = models.BooleanField(default=True)
    criada_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Notificação"
        verbose_name_plural = "Notificações"
        ordering = ("-criada_em",)
        indexes = [models.Index(fields=["ativa", "-criada_em"])]

    def __str__(self):
        return self.titulo

    @property
    def css_contexto(self):
        return self.CSS_POR_TIPO.get(self.tipo, "secondary")

    @property
    def icone(self):
        return self.ICONE_POR_TIPO.get(self.tipo, "bi-bell")

    @classmethod
    def visiveis_para(cls, user):
        """
        Notificações ativas que o usuário deve ver: as gerais mais as
        dirigidas a qualquer unidade em que ele tenha Perfil ativo.
        """
        if not user.is_authenticated:
            return cls.objects.none()

        unidades = Perfil.objects.filter(usuario=user, ativo=True).values_list(
            "unidade_id", flat=True
        )
        unidades = [u for u in unidades if u is not None]

        qs = cls.objects.filter(ativa=True)
        if user.is_superuser:
            return qs
        return qs.filter(
            models.Q(unidade_destino__isnull=True) | models.Q(unidade_destino_id__in=unidades)
        )


class NotificacaoLida(models.Model):
    """Marca de leitura de uma notificação por um usuário."""

    notificacao = models.ForeignKey(
        Notificacao, on_delete=models.CASCADE, related_name="leituras"
    )
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notificacoes_lidas"
    )
    lida_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("notificacao", "usuario")
        verbose_name = "Leitura de Notificação"
        verbose_name_plural = "Leituras de Notificações"

    def __str__(self):
        return f"{self.usuario} leu {self.notificacao_id}"
