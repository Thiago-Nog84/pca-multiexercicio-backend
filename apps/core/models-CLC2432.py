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
    # MPPI não possui UASG — usa código próprio no PNCP
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
        ("CPPT", "CPPT — Coordenadoria de Patrimônio e Prestação de Contas"),
        ("CTI", "CTI — Coordenadoria de Tecnologia da Informação"),
        ("CAA", "CAA — Coordenadoria de Apoio Administrativo"),
        ("CRH", "CRH — Coordenadoria de Recursos Humanos"),
        ("GSI", "GSI — Gerência de Segurança Institucional"),
        ("CEAF", "CEAF — Centro de Estudos e Aperfeiçoamento Funcional"),
        ("CI", "CI — Coordenadoria de Infraestrutura"),
        ("CLC", "CLC — Coordenadoria de Licitações e Contratos"),
        ("CCF", "CCF — Coordenadoria de Contabilidade e Finanças"),
        ("APG", "APG — Assessoria de Planejamento e Gestão"),
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
    Ato PGJ 1414/2024: agente, equipe apoio, comissão.
    Ato PGJ 1381/2024: requisitante, área técnica, setor licitações, autoridade.
    Res. CNMP 283/2024: equipe de planejamento TI, equipe de gestão TI.
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
