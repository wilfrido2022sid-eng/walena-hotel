from django.contrib import admin
from .models import Hotel, Usuario, TipoHabitacion, Habitacion, Huesped, Reserva, Servicio, ServicioReserva, Pago, Factura, FacturaDetalle, FacturaPago

@admin.register(Hotel)
class HotelAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'telefono', 'correo')

@admin.register(Usuario)
class UsuarioAdmin(admin.ModelAdmin):
    list_display = ('nombres', 'apellidos', 'correo', 'rol', 'activo')

@admin.register(TipoHabitacion)
class TipoHabitacionAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'capacidad', 'precio_base_noche', 'cargo_persona_extra')

@admin.register(Habitacion)
class HabitacionAdmin(admin.ModelAdmin):
    list_display = ('numero', 'piso', 'tipo', 'estado')

@admin.register(Huesped)
class HuespedAdmin(admin.ModelAdmin):
    list_display = ('numero_documento', 'nombres', 'apellidos', 'telefono')

@admin.register(Reserva)
class ReservaAdmin(admin.ModelAdmin):
    list_display = ('id', 'huesped', 'habitacion', 'fecha_entrada', 'fecha_salida', 'estado')

@admin.register(Servicio)
class ServicioAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'categoria', 
                    'precio')
    list_filter = ('categoria',)
    search_fields = ('nombre',) 
    ordering = ('categoria', 'nombre')

@admin.register(ServicioReserva)
class ServicioReservaAdmin(admin.ModelAdmin):
    list_display = ('reserva', 'servicio', 'cantidad', 'precio_unitario', 'subtotal')
    list_filter = ('servicio__categoria',)
    search_fields = ('reserva__id', 'servicio__nombre')
    readonly_fields = ('subtotal',)

@admin.register(Pago)
class PagoAdmin(admin.ModelAdmin):
    list_display = ('reserva', 'monto', 'metodo_pago')

@admin.register(Factura)
class FacturaAdmin(admin.ModelAdmin):
    list_display = ('numero', 'reserva', 'fecha_emision', 'total', 'email_enviado_at')
    readonly_fields = (
        'numero', 'fecha_emision', 'huesped_nombre', 'huesped_tipo_documento',
        'huesped_numero_documento', 'huesped_correo', 'habitacion_numero',
        'habitacion_nombre', 'habitacion_piso', 'fecha_entrada', 'fecha_salida',
        'noches_reservadas', 'noches_adicionales', 'noches_facturadas',
        'total_alojamiento', 'total_servicios', 'cargo_tardio', 'total_pagado',
        'total', 'saldo_final', 'email_enviado_at', 'reserva',
    )
    fields = readonly_fields
    ordering = ('-fecha_emision',)


@admin.register(FacturaDetalle)
class FacturaDetalleAdmin(admin.ModelAdmin):
    list_display = ('factura', 'tipo', 'descripcion', 'cantidad', 'subtotal')
    readonly_fields = ('factura', 'tipo', 'descripcion', 'cantidad', 'precio_unitario', 'subtotal')


@admin.register(FacturaPago)
class FacturaPagoAdmin(admin.ModelAdmin):
    list_display = ('factura', 'fecha_pago', 'metodo_pago', 'monto')
    readonly_fields = ('factura', 'pago_origen_id', 'fecha_pago', 'metodo_pago', 'monto')

