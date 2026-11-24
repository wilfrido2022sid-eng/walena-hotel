import django.db.models.deletion
from decimal import Decimal
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('marketweb', '0008_reiniciar_inventario_nueve_habitaciones'),
    ]

    operations = [
        migrations.DeleteModel(name='Factura'),
        migrations.RemoveField(
            model_name='huesped',
            name='es_extranjero',
        ),
        migrations.CreateModel(
            name='Factura',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('numero', models.CharField(max_length=30, unique=True)),
                ('fecha_emision', models.DateTimeField(auto_now_add=True)),
                ('total_alojamiento', models.DecimalField(decimal_places=2, default=Decimal('0.00'), max_digits=12)),
                ('total_servicios', models.DecimalField(decimal_places=2, default=Decimal('0.00'), max_digits=12)),
                ('cargo_tardio', models.DecimalField(decimal_places=2, default=Decimal('0.00'), max_digits=12)),
                ('total_pagado', models.DecimalField(decimal_places=2, default=Decimal('0.00'), max_digits=12)),
                ('total', models.DecimalField(decimal_places=2, default=Decimal('0.00'), max_digits=12)),
                ('email_enviado_at', models.DateTimeField(blank=True, null=True)),
                ('reserva', models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name='factura', to='marketweb.reserva')),
            ],
            options={
                'db_table': 'factura',
                'ordering': ['-fecha_emision'],
            },
        ),
    ]
