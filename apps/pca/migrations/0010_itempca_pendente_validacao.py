from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("pca", "0009_itempca_tipo_suspensao"),
    ]

    operations = [
        migrations.AlterField(
            model_name="itempca",
            name="status",
            field=models.CharField(
                choices=[
                    ("nao_iniciado", "Não Iniciado"),
                    ("pendente_validacao", "Pendente de Validação"),
                    ("iniciado", "Iniciado"),
                    ("em_diligencia", "Em Diligência"),
                    ("em_andamento", "Em Andamento"),
                    ("concluido", "Concluído"),
                    ("suspenso", "Suspenso"),
                ],
                default="nao_iniciado",
                max_length=20,
            ),
        ),
    ]
