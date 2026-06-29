from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('srp', '0010_ataregistroprecos_link_documento_mppi'),
    ]

    operations = [
        migrations.AlterField(
            model_name='itemarp',
            name='unidade_fornecimento',
            field=models.CharField(blank=True, max_length=30),
        ),
    ]
