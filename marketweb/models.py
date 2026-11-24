from django.db import models
from pathlib import Path
from decimal import Decimal
from datetime import datetime, time, date

# 1. Tabla: hotel
class Hotel(models.Model):
    nombre = models.CharField(max_length=100, default="Hotel Walena S.A.S.")
    direccion = models.CharField(max_length=200, default="Calle 15 # 14B - 205, Riohacha, La Guajira")
    telefono = models.CharField(max_length=20, default="+57 312 833 5638")
    correo = models.EmailField(default="reservashotelwalena@gmail.com")
    horario_checkin = models.TimeField(default="14:00")
    horario_checkout = models.TimeField(default="12:00")

    class Meta:
        db_table = 'hotel'

    def __str__(self):
        return self.nombre





# 2. Tabla: usuario
class Usuario(models.Model):
    ROLES = [
        ('ADMIN_GERENTE', 'Admin-Gerente'),
        ('RECEPCIONISTA', 'Recepcionista'),
        ('CLIENTE', 'Cliente'),
    ]
    nombres = models.CharField(max_length=80)
    apellidos = models.CharField(max_length=80)
    correo = models.EmailField(unique=True)
    contrasena = models.CharField(max_length=255)
    rol = models.CharField(max_length=20, choices=ROLES, default='RECEPCIONISTA')
    activo = models.BooleanField(default=True)
    version_sesion = models.PositiveIntegerField(default=1)

    class Meta:
        db_table = 'usuario'

    def __str__(self):
        return f"{self.nombres} {self.apellidos} ({self.rol})"






# 3. Tabla: tipo_habitacion
class TipoHabitacion(models.Model):
    nombre = models.CharField(max_length=50) 
    capacidad = models.IntegerField(default=4)
    # Tarifa base para 1 sola persona (Ej: $160.650)
    precio_base_noche = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('160650.00'))
    # Cargo que se suma a partir de la segunda persona (Ej: $59.500)
    cargo_persona_extra = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('59500.00'))
    descripcion = models.TextField(blank=True, null=True)

    def precio_base_formateado(self):
        return f"{int(self.precio_base_noche):,}".replace(",", ".")

    def cargo_extra_formateado(self):
        return f"{int(self.cargo_persona_extra):,}".replace(",", ".")

    class Meta:
        db_table = 'tipo_habitacion'

    def __str__(self):
        return f"{self.nombre} (Capacidad: {self.capacidad} personas)"







# 4. Tabla: habitacion
class Habitacion(models.Model):
    ESTADOS = [
        ('DISPONIBLE', 'Disponible'),
        ('OCUPADA', 'Ocupada'),
        ('EN_ASEO', 'En Aseo'),
        ('MANTENIMIENTO', 'En Mantenimiento'),
    ]
    numero = models.CharField(max_length=10, unique=True)
    piso = models.IntegerField(default=1)
    tipo = models.ForeignKey(TipoHabitacion, on_delete=models.CASCADE, related_name='habitaciones')
    hotel = models.ForeignKey(Hotel, on_delete=models.CASCADE, related_name='habitaciones')
    estado = models.CharField(max_length=20, choices=ESTADOS, default='DISPONIBLE')
    codigo_color = models.CharField(max_length=10, default='#FFFFFF') # Blanco (#FFFFFF), Azul (#1E88E5), Anaranjado (#FFB74D)
    

    class Meta:
        db_table = 'habitacion'

    def save(self, *args, **kwargs):
        # Asignación automática de códigos de color institucionales
        if self.estado == 'DISPONIBLE':
            self.codigo_color = '#FFFFFF'
        elif self.estado == 'OCUPADA':
            self.codigo_color = '#1E88E5'
        elif self.estado == 'EN_ASEO':
            self.codigo_color = '#FFB74D'
        elif self.estado == 'MANTENIMIENTO':
            self.codigo_color = '#DC3545'
        super().save(*args, **kwargs)

    def ruta_imagen(self):
        imagenes = self.rutas_imagenes
        return imagenes[0] if imagenes else "img/walena_logo.png"

    @property
    def rutas_imagenes(self):
        """Static gallery images stored in one numbered folder per room."""
        carpeta = Path(__file__).resolve().parent / "public" / "img" / "habitaciones" / str(self.numero)
        if not carpeta.is_dir():
            return []
        return [
            f"img/habitaciones/{self.numero}/{archivo.name}"
            for archivo in sorted(carpeta.iterdir())
            if archivo.is_file() and archivo.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp", ".avif"}
        ]

    @property
    def nombre_completo(self):
        return f"{self.tipo.nombre} #{self.numero}"

    def __str__(self):
        return f"{self.nombre_completo} (Piso {self.piso})"


# 5. Tabla: huesped
class Huesped(models.Model):
    TIPOS_DOC = [
        ('CC', 'Cédula de Ciudadanía'),
        ('CE', 'Cédula de Extranjería'),
        ('PASAPORTE', 'Pasaporte'),
        ('TI', 'Tarjeta de Identidad'),
    ]
    tipo_documento = models.CharField(max_length=20, choices=TIPOS_DOC, default='CC')
    numero_documento = models.CharField(max_length=30, unique=True)
    nombres = models.CharField(max_length=80)
    apellidos = models.CharField(max_length=80)
    telefono = models.CharField(max_length=20)
    correo = models.EmailField()
    nacionalidad = models.CharField(max_length=50, default='Colombiana')

    class Meta:
        db_table = 'huesped'

    def __str__(self):
        return f"{self.nombres} {self.apellidos} - {self.numero_documento}"




# 6. Tabla: reserva
class Reserva(models.Model):
    ESTADOS_RESERVA = [
        ('PENDIENTE', 'Pendiente Pago'),
        ('CONFIRMADA', 'Confirmada'),
        ('CHECKIN', 'Huésped en Casa'),
        ('CHECKOUT', 'Completada / Check-out'),
        ('CANCELADA', 'Cancelada'),
    ]
    CANALES = [
        ('DIRECTA', 'Directa / WhatsApp'),
        ('WEB', 'Sitio Web Walena'),
        ('BOOKING', 'Booking.com'),
        ('EXPEDIA', 'Expedia'),
        ('PRESENCIAL', 'Presencial'),
    ]
    huesped = models.ForeignKey('Huesped', on_delete=models.PROTECT, related_name='reservas')
    habitacion = models.ForeignKey('Habitacion', on_delete=models.PROTECT, related_name='reservas')
    fecha_entrada = models.DateField()
    fecha_salida = models.DateField()
    
    # --- NUEVOS CAMPOS AÑADIDOS ---
    num_huespedes = models.IntegerField(default=1) # Capacidad total (adultos + niños)
    num_adultos = models.IntegerField(default=1)
    num_ninos = models.IntegerField(default=0)
    trae_mascota = models.BooleanField(default=False)
    notas = models.TextField(blank=True, null=True)
    # ------------------------------

    canal_reserva = models.CharField(max_length=20, choices=CANALES, default='PRESENCIAL')
    estado = models.CharField(max_length=20, choices=ESTADOS_RESERVA, default='PENDIENTE')
    valor_total = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    cargo_tardio = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    fecha_creacion = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'reserva'

    def calcular_noches(self):
        noches = (self.fecha_salida - self.fecha_entrada).days
        return noches if noches > 0 else 1

    def calcular_alojamiento(self):
        tarifa_base = self.habitacion.tipo.precio_base_noche
        recargo_extras = Decimal('0.00')
        # Los niños NO pagan, solo se suma el cargo a partir del segundo adulto
        if self.num_adultos > 1:
            cantidad_extras = self.num_adultos - 1
            cargo_extra = self.habitacion.tipo.cargo_persona_extra
            recargo_extras = Decimal(cantidad_extras) * cargo_extra
            
        tarifa_total_noche = tarifa_base + recargo_extras
        return Decimal(self.calcular_noches()) * tarifa_total_noche

    def __str__(self): 
        return f"Reserva #{self.id} - Hab: {self.habitacion.numero} ({self.huesped.nombres})"





# 7. Tabla: servicio (Catálogo de minibar y lavandería)
class Servicio(models.Model):
    CATEGORIAS = [
        ('LAVANDERIA', 'Servicio de Lavandería'),
        ('MINIBAR', 'Consumo de Minibar'),
    ]
    nombre = models.CharField(max_length=100)
    categoria = models.CharField(max_length=20, choices=CATEGORIAS, default='MINIBAR')
    precio = models.DecimalField(max_digits=10, decimal_places=2)
    class Meta:
        db_table = 'servicio'
    def __str__(self):
        return f"{self.nombre} (${self.precio})"


# 8. Tabla: servicio_reserva
class ServicioReserva(models.Model):
    reserva = models.ForeignKey(Reserva, on_delete=models.CASCADE, related_name='servicios')
    servicio = models.ForeignKey(Servicio, on_delete=models.CASCADE)
    cantidad = models.IntegerField(default=1)
    precio_unitario = models.DecimalField(max_digits=10, decimal_places=2)
    subtotal = models.DecimalField(max_digits=10, decimal_places=2)
    def save(self, *args, **kwargs):
        self.subtotal = Decimal(self.cantidad) * Decimal(self.precio_unitario)
        super().save(*args, **kwargs)
    def subtotal_formateado(self):
        return f"{int(self.subtotal):,}".replace(",", ".")
    def __str__(self):
        return f"{self.cantidad} x {self.servicio.nombre} (${self.subtotal})"
    class Meta:
        db_table = 'servicio_reserva'


# 9. Tabla: pago
class Pago(models.Model):
    METODOS = [
        ('EFECTIVO', 'Efectivo'),
        ('TRANSFERENCIA', 'Transferencia Bancaria'),
        ('DATAFONO', 'Datáfono'),
        ('LINK_PAGO', 'Link de Pago'),
        ('NEQUI', 'Nequi'),
        ('DAVIPLATA', 'Daviplata'),
    ]
    reserva = models.ForeignKey(Reserva, on_delete=models.CASCADE, related_name='pagos')
    monto = models.DecimalField(max_digits=10, decimal_places=2)
    metodo_pago = models.CharField(max_length=20, choices=METODOS)
    fecha_pago = models.DateTimeField(auto_now_add=True)
    def monto_formateado(self):
        return f"{int(self.monto):,}".replace(",", ".")
    class Meta:
        db_table = 'pago'


# 10. Factura interna de alojamiento, sin integración tributaria externa.
class Factura(models.Model):
    reserva = models.OneToOneField(Reserva, on_delete=models.PROTECT, related_name='factura')
    numero = models.CharField(max_length=30, unique=True)
    fecha_emision = models.DateTimeField(auto_now_add=True)
    huesped_nombre = models.CharField(max_length=160, default='')
    huesped_tipo_documento = models.CharField(max_length=20, default='')
    huesped_numero_documento = models.CharField(max_length=30, default='')
    huesped_correo = models.EmailField(default='')
    habitacion_numero = models.CharField(max_length=10, default='')
    habitacion_nombre = models.CharField(max_length=120, default='')
    habitacion_piso = models.PositiveSmallIntegerField(default=1)
    fecha_entrada = models.DateField(null=True, blank=True)
    fecha_salida = models.DateField(null=True, blank=True)
    noches_reservadas = models.PositiveIntegerField(default=1)
    noches_adicionales = models.PositiveIntegerField(default=0)
    noches_facturadas = models.PositiveIntegerField(default=1)
    total_alojamiento = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    total_servicios = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    cargo_tardio = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    total_pagado = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    total = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    saldo_final = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    email_enviado_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'factura'
        ordering = ['-fecha_emision']

    def __str__(self):
        return f"Factura {self.numero} — Reserva #{self.reserva_id}"


class FacturaDetalle(models.Model):
    TIPOS = [
        ('ALOJAMIENTO', 'Alojamiento'),
        ('SERVICIO', 'Servicio'),
        ('RECARGO', 'Recargo'),
    ]
    factura = models.ForeignKey(Factura, on_delete=models.CASCADE, related_name='detalles')
    tipo = models.CharField(max_length=20, choices=TIPOS)
    descripcion = models.CharField(max_length=200)
    cantidad = models.PositiveIntegerField(default=1)
    precio_unitario = models.DecimalField(max_digits=12, decimal_places=2)
    subtotal = models.DecimalField(max_digits=12, decimal_places=2)

    class Meta:
        db_table = 'factura_detalle'
        ordering = ['id']


class FacturaPago(models.Model):
    factura = models.ForeignKey(Factura, on_delete=models.CASCADE, related_name='pagos_registrados')
    pago_origen_id = models.PositiveIntegerField()
    monto = models.DecimalField(max_digits=12, decimal_places=2)
    metodo_pago = models.CharField(max_length=20)
    fecha_pago = models.DateTimeField()

    class Meta:
        db_table = 'factura_pago'
        ordering = ['fecha_pago', 'id']


# 11. NUEVA TABLA: acompañante (Cumplimiento Regla RN13)
class Acompanante(models.Model):
    TIPOS_DOC = [
        ('CC', 'Cédula de Ciudadanía'),
        ('CE', 'Cédula de Extranjería'),
        ('PASAPORTE', 'Pasaporte'),
        ('TI', 'Tarjeta de Identidad'),
        ('RC', 'Registro Civil (Menor)'),
    ]
    reserva = models.ForeignKey(Reserva, on_delete=models.CASCADE, related_name='acompanantes')
    tipo_documento = models.CharField(max_length=20, choices=TIPOS_DOC, default='CC')
    numero_documento = models.CharField(max_length=30)
    nombres = models.CharField(max_length=150)
    telefono = models.CharField(max_length=20, blank=True, default='')
    correo = models.EmailField(blank=True, default='')
    nacionalidad = models.CharField(max_length=50, blank=True, default='Colombiana')
    es_menor = models.BooleanField(default=False)

    class Meta:
        db_table = 'acompanante'

    def __str__(self):
        return f"{self.nombres} - Reserva #{self.reserva.id}"
