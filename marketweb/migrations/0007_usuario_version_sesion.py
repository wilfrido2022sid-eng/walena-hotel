from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('marketweb', '0006_alter_habitacion_estado'),
    ]

    operations = [
        migrations.AddField(
            model_name='usuario',
            name='version_sesion',
            field=models.PositiveIntegerField(default=1),
        ),
    ]
