from django.db import migrations


INVENTARIO = [
    # numero, piso, tipo, capacidad de Booking
    ("1", 1, "Habitación Familiar Deluxe", 5),
    ("2", 1, "Habitación Familiar Superior", 5),
    ("3", 1, "Habitación Doble Deluxe", 3),
    ("4", 1, "Habitación Doble con vistas al jardín", 3),
    ("5", 1, "Habitación Doble Pequeña", 3),
    ("6", 2, "Habitación Doble Deluxe con balcón", 5),
    ("7", 2, "Habitación Triple de lujo", 5),
    ("8", 3, "Habitación Familiar Estándar", 9),
    ("9", 3, "Habitación Triple con vistas al jardín", 5),
]


def reiniciar_inventario(apps, schema_editor):
    Hotel = apps.get_model("marketweb", "Hotel")
    TipoHabitacion = apps.get_model("marketweb", "TipoHabitacion")
    Habitacion = apps.get_model("marketweb", "Habitacion")
    Reserva = apps.get_model("marketweb", "Reserva")

    # Mantener el rastro de incidencias que apunta a la antigua habitación 303:
    # esa fila se reutiliza como habitación 9. Solo se elimina el inventario extra
    # 301 y 302, que no tiene incidencias en la base revisada.
    habitaciones_actuales = list(Habitacion.objects.order_by("numero"))
    legado = {"101", "102", "103", "104", "201", "202", "203", "204", "301", "302", "303"}
    numeros_actuales = {habitacion.numero for habitacion in habitaciones_actuales}
    if habitaciones_actuales and numeros_actuales != legado:
        raise RuntimeError(
            "El inventario actual no coincide con las 11 habitaciones revisadas; "
            "se cancela el reinicio para no perder relaciones de otras tablas."
        )

    # La solicitud del proyecto es eliminar las reservas. Django aplica las
    # cascadas de pagos, consumos y acompañantes.
    Reserva.objects.all().delete()

    hotel = Hotel.objects.order_by("pk").first()
    if hotel is None:
        hotel = Hotel.objects.create(nombre="Hotel Walena S.A.S.")

    tipos = {}
    for numero, piso, nombre_tipo, capacidad in INVENTARIO:
        tipo = TipoHabitacion.objects.filter(nombre__iexact=nombre_tipo).order_by("pk").first()
        if tipo is None:
            tipo = TipoHabitacion.objects.create(nombre=nombre_tipo, capacidad=capacidad)
        else:
            tipo.nombre = nombre_tipo
            tipo.capacidad = capacidad
            tipo.save(update_fields=["nombre", "capacidad"])
        tipos[numero] = tipo

    if habitaciones_actuales:
        por_numero = {habitacion.numero: habitacion for habitacion in habitaciones_actuales}
        Habitacion.objects.filter(numero__in=["301", "302"]).delete()
        conservar = [por_numero[numero] for numero in legado if numero not in {"301", "302"}]
        for habitacion in conservar:
            habitacion.numero = f"tmp-{habitacion.pk}"
            habitacion.save(update_fields=["numero"])

        antiguo_a_nuevo = {
            "101": "1", "102": "2", "103": "3", "104": "4",
            "201": "5", "202": "6", "203": "7", "204": "8", "303": "9",
        }
        pisos = {numero: piso for numero, piso, _, _ in INVENTARIO}
        for antiguo, numero in antiguo_a_nuevo.items():
            habitacion = por_numero[antiguo]
            habitacion.numero = numero
            habitacion.piso = pisos[numero]
            habitacion.tipo = tipos[numero]
            habitacion.hotel = hotel
            habitacion.estado = "DISPONIBLE"
            habitacion.codigo_color = "#FFFFFF"
            habitacion.save(update_fields=["numero", "piso", "tipo", "hotel", "estado", "codigo_color"])
    else:
        for numero, piso, _, _ in INVENTARIO:
            Habitacion.objects.create(
                numero=numero,
                piso=piso,
                tipo=tipos[numero],
                hotel=hotel,
                estado="DISPONIBLE",
            )


class Migration(migrations.Migration):
    atomic = True

    dependencies = [
        ("marketweb", "0007_usuario_version_sesion"),
    ]

    operations = [
        migrations.RunPython(reiniciar_inventario, migrations.RunPython.noop),
    ]
