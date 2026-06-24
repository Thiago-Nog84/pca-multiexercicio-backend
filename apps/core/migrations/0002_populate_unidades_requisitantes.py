"""
Data migration: pré-popula as 13 UnidadeRequisitantes fixas do MPPI.
Fundamento: Ato PGJ 1381/2024, art. 7º, §1º.
"""

from django.db import migrations


UNIDADES = [
    ("CPPT", "Coordenadoria de Perícias e Pareceres Técnicos"),
    ("CTI",  "Coordenadoria de Tecnologia da Informação"),
    ("CAA",  "Coordenadoria de Apoio Administrativo"),
    ("CRH",  "Coordenadoria de Recursos Humanos"),
    ("GSI",  "Gerência de Segurança Institucional"),
    ("CEAF", "Centro de Estudos e Aperfeiçoamento Funcional"),
    ("CI",   "Coordenadoria de Infraestrutura"),
    ("CLC",  "Coordenadoria de Licitações e Contratos"),
    ("CCF",  "Coordenadoria de Contabilidade e Finanças"),
    ("APG",  "Assessoria de Planejamento e Gestão"),
    ("GAECO","Grupo de Atuação Especial Contra o Crime Organizado"),
    ("FPROCON", "Fundo de Proteção ao Consumidor"),
    ("CCS",  "Coordenadoria de Comunicação Social"),
]


def populate_unidades(apps, schema_editor):
    Orgao = apps.get_model("core", "Orgao")
    UnidadeRequisitante = apps.get_model("core", "UnidadeRequisitante")

    orgao = Orgao.objects.first()
    if orgao is None:
        # Sem órgão cadastrado ainda — unidades serão criadas manualmente
        return

    for sigla, nome in UNIDADES:
        UnidadeRequisitante.objects.get_or_create(
            orgao=orgao,
            sigla=sigla,
            defaults={"nome": nome},
        )


def despopulate_unidades(apps, schema_editor):
    UnidadeRequisitante = apps.get_model("core", "UnidadeRequisitante")
    UnidadeRequisitante.objects.filter(
        sigla__in=[s for s, _ in UNIDADES]
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(populate_unidades, despopulate_unidades),
    ]
