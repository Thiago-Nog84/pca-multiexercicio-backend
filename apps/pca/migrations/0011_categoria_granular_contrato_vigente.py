import django.db.models.deletion
from django.db import migrations, models


CATEGORIAS_ITEM = [
    ("material", "Material de Consumo (CATMAT)"),
    ("material_permanente", "Material Permanente (CATMAT)"),
    ("servico", "Serviço (CATSER)"),
    ("servico_engenharia", "Serviço de Engenharia"),
    ("servico_terceirizado", "Serviço Terceirizado (dedicação exclusiva de mão de obra)"),
    ("obras", "Obras e Serviços de Engenharia"),
    ("solucao_ti", "Solução de TIC (Res. CNMP 283/2024)"),
    ("software", "Software"),
    ("treinamento", "Treinamento"),
    ("publicidade", "Publicidade (Dec. 21.813/2023)"),
]


class Migration(migrations.Migration):

    dependencies = [
        ("pca", "0010_itempca_pendente_validacao"),
        ("contratos", "0006_empenho"),
    ]

    operations = [
        migrations.AlterField(
            model_name="itempca",
            name="categoria",
            field=models.CharField(choices=CATEGORIAS_ITEM, max_length=20),
        ),
        migrations.AlterField(
            model_name="itemcatalogo",
            name="categoria",
            field=models.CharField(choices=CATEGORIAS_ITEM, max_length=20),
        ),
        migrations.AddField(
            model_name="itempca",
            name="contrato_vigente",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="itens_pca_atendidos",
                to="contratos.contrato",
                help_text=(
                    "Contrato vigente que já atende esta demanda (renovação, aditivo, "
                    "repactuação ou apostilamento), dispensando nova licitação. "
                    "Preenchido ao vincular pela busca de contratos vigentes no cadastro em grupo."
                ),
            ),
        ),
    ]
