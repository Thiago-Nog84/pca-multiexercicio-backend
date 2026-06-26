from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("pca", "0008_alter_itemcatalogo_options_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="itempca",
            name="tipo_suspensao",
            field=models.CharField(
                blank=True,
                choices=[("total", "Total"), ("parcial", "Parcial")],
                help_text="Preenchido quando status=suspenso: total ou parcial",
                max_length=10,
                null=True,
            ),
        ),
    ]
