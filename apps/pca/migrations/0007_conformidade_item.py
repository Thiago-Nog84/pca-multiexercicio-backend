from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("pca", "0006_orcamento_planejado"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = []
