# Generated manually on 2026-06-25

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('pca', '0003_refactor_itempca_tipo_modalidade'),
    ]

    operations = [
        migrations.AddField(
            model_name='itempca',
            name='numero_lote_pca',
            field=models.CharField(
                blank=True,
                max_length=20,
                help_text=(
                    'Número do lote ao qual este item pertence na licitação/ARP. '
                    'Deve espelhar o numero_lote do ItemARP correspondente. '
                    'Itens com o mesmo numero_lote_pca são tratados como unidade '
                    'para fins de PCA e exibição no dashboard.'
                ),
            ),
        ),
    ]
