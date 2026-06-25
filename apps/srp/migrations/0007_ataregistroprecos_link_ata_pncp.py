from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("srp", "0006_contrato_item_arp"),
    ]

    operations = [
        migrations.AddField(
            model_name="ataregistroprecos",
            name="link_ata_pncp",
            field=models.URLField(
                blank=True,
                max_length=300,
                help_text="URL da ata no PNCP (ex: https://pncp.gov.br/app/atas/05805924000189/2024/16/1).",
            ),
        ),
    ]
