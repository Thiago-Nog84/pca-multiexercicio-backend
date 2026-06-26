# Generated manually — 2026-06-26

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('srp', '0009_ataregistroprecos_usa_lotes_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='ataregistroprecos',
            name='link_documento_mppi',
            field=models.URLField(
                blank=True,
                max_length=500,
                verbose_name='Link do documento (MPPI)',
                help_text=(
                    'URL do texto integral da ARP publicado no site do MPPI '
                    '(ex: https://www.mppi.mp.br/internet/wp-content/uploads/2025/12/ARP-54-2025_merged.pdf). '
                    'Exibido como botão \'Ver texto da ARP\' na página de detalhe.'
                ),
            ),
        ),
    ]
