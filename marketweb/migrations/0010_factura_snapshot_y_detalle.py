import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('marketweb', '0009_eliminar_comprobante_y_dato_tributario'),
    ]

    operations = [
        migrations.AddField(
            model_name='factura',
            name='huesped_nombre',
            field=models.CharField(default='', max_length=160),
        ),
        migrations.AddField(
            model_name='factura',
            name='huesped_tipo_documento',
            field=models.CharField(default='', max_length=20),
        ),
        migrations.AddField(
            model_name='factura',
            name='huesped_numero_documento',
            field=models.CharField(default='', max_length=30),
        ),
        migrations.AddField(
            model_name='factura',
            name='huesped_correo',
            field=models.EmailField(default='', max_length=254),
        ),
        migrations.AddField(
            model_name='factura',
            name='habitacion_numero',
            field=models.CharField(default='', max_length=10),
        ),
        migrations.AddField(
            model_name='factura',
            name='habitacion_nombre',
            field=models.CharField(default='', max_length=120),
        ),
        migrations.AddField(
            model_name='factura',
            name='habitacion_piso',
            field=models.PositiveSmallIntegerField(default=1),
        ),
        migrations.AddField(
            model_name='factura',
            name='fecha_entrada',
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='factura',
            name='fecha_salida',
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='factura',
            name='noches_reservadas',
            field=models.PositiveIntegerField(default=1),
        ),
        migrations.AddField(
            model_name='factura',
            name='noches_adicionales',
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name='factura',
            name='noches_facturadas',
            field=models.PositiveIntegerField(default=1),
        ),
        migrations.AddField(
            model_name='factura',
            name='saldo_final',
            field=models.DecimalField(decimal_places=2, default=0, max_digits=12),
        ),
        migrations.CreateModel(
            name='FacturaDetalle',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('tipo', models.CharField(choices=[('ALOJAMIENTO', 'Alojamiento'), ('SERVICIO', 'Servicio'), ('RECARGO', 'Recargo')], max_length=20)),
                ('descripcion', models.CharField(max_length=200)),
                ('cantidad', models.PositiveIntegerField(default=1)),
                ('precio_unitario', models.DecimalField(decimal_places=2, max_digits=12)),
                ('subtotal', models.DecimalField(decimal_places=2, max_digits=12)),
                ('factura', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='detalles', to='marketweb.factura')),
            ],
            options={
                'db_table': 'factura_detalle',
                'ordering': ['id'],
            },
        ),
        migrations.CreateModel(
            name='FacturaPago',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('pago_origen_id', models.PositiveIntegerField()),
                ('monto', models.DecimalField(decimal_places=2, max_digits=12)),
                ('metodo_pago', models.CharField(max_length=20)),
                ('fecha_pago', models.DateTimeField()),
                ('factura', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='pagos_registrados', to='marketweb.factura')),
            ],
            options={
                'db_table': 'factura_pago',
                'ordering': ['fecha_pago', 'id'],
            },
        ),
    ]
