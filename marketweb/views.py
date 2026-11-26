from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.hashers import make_password, check_password
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import transaction
from django.db.models import Q, Case, When, Value, IntegerField, Max
from decimal import Decimal, InvalidOperation
import json
from datetime import datetime, time, date, timedelta
from .models import Hotel, Habitacion, Reserva, Huesped, Acompanante, Servicio, ServicioReserva, Pago, Factura, FacturaDetalle, FacturaPago, Usuario
from .decorators import requiere_rol
import random, string
from django.core.mail import EmailMultiAlternatives
from django.conf import settings
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from time import perf_counter
import logging
from email.mime.image import MIMEImage

OTP_EXPIRA_EN_MINUTOS = 5
OTP_MAX_INTENTOS = 5
logger = logging.getLogger(__name__)


def enviar_correo_html_con_logo(asunto, mensaje_plano, mensaje_html, destinatario):
    """Envía un correo HTML con el logo adjunto en línea para clientes de email."""
    correo = EmailMultiAlternatives(
        asunto,
        mensaje_plano,
        settings.DEFAULT_FROM_EMAIL,
        [destinatario],
    )
    correo.attach_alternative(mensaje_html, 'text/html')

    ruta_logo = settings.BASE_DIR / 'marketweb' / 'public' / 'img' / 'walena-logo2.jpg'
    if ruta_logo.is_file():
        imagen_logo = MIMEImage(ruta_logo.read_bytes(), _subtype='jpeg')
        imagen_logo.add_header('Content-ID', '<walena-logo>')
        imagen_logo.add_header('Content-Disposition', 'inline', filename='walena-logo2.jpg')
        correo.attach(imagen_logo)

    return correo.send(fail_silently=False)


def limpiar_estado_recuperacion(request):
    """Elimina de la sesión los datos temporales del flujo de recuperación."""
    claves = (
        'reset_usuario_id',
        'reset_codigo_otp',
        'reset_correo',
        'reset_intentos',
        'reset_codigo_verificado',
        'reset_codigo_creado_en',
    )
    for clave in claves:
        request.session.pop(clave, None)


def codigo_recuperacion_vencido(request):
    """Considera inválido un código sin fecha de creación o con más de 5 minutos."""
    creado_en_texto = request.session.get('reset_codigo_creado_en')
    creado_en = parse_datetime(creado_en_texto) if creado_en_texto else None
    if creado_en is None:
        return True
    if timezone.is_naive(creado_en):
        creado_en = timezone.make_aware(creado_en, timezone.get_current_timezone())
    return timezone.now() - creado_en >= timedelta(minutes=OTP_EXPIRA_EN_MINUTOS)


def _calcular_cuenta_checkout(reserva, momento_actual=None, bloquear=False):
    servicios_query = ServicioReserva.objects.filter(reserva=reserva).select_related('servicio')
    pagos_query = Pago.objects.filter(reserva=reserva).order_by('fecha_pago')
    if bloquear:
        servicios_query = servicios_query.select_for_update()
        pagos_query = pagos_query.select_for_update()
    servicios = list(servicios_query)
    pagos = list(pagos_query)
    total_servicios = sum((servicio.subtotal for servicio in servicios), Decimal('0.00'))
    total_pagos = sum((pago.monto for pago in pagos), Decimal('0.00'))
    momento_actual = momento_actual or timezone.localtime()
    if isinstance(momento_actual, time):
        momento_actual = timezone.make_aware(
            datetime.combine(timezone.localdate(), momento_actual),
            timezone.get_current_timezone(),
        )
    momento_actual = timezone.localtime(momento_actual)
    hotel = Hotel.objects.first()
    hora_salida = hotel.horario_checkout if hotel else time(12, 0)

    noches_reservadas = reserva.calcular_noches()
    noches_adicionales = max((momento_actual.date() - reserva.fecha_salida).days, 0)
    noches_facturadas = noches_reservadas + noches_adicionales
    tarifa_noche = reserva.calcular_alojamiento() / Decimal(noches_reservadas)
    total_alojamiento = tarifa_noche * Decimal(noches_facturadas)

    cargo_tardio = Decimal('0.00')
    # El recargo por salida tardía se evalúa únicamente el día de salida
    # reservado; antes de esa fecha nunca se cobra por la hora del reloj.
    if momento_actual.date() == reserva.fecha_salida and momento_actual.time() > hora_salida:
        hora_limite_30 = (datetime.combine(reserva.fecha_salida, hora_salida) + timedelta(minutes=30)).time()
        hora_limite_60 = (datetime.combine(reserva.fecha_salida, hora_salida) + timedelta(minutes=60)).time()
        if momento_actual.time() <= hora_limite_30:
            cargo_tardio = Decimal('30000.00')
        elif momento_actual.time() <= hora_limite_60:
            cargo_tardio = Decimal('60000.00')
        else:
            cargo_tardio = Decimal('160650.00') * Decimal(reserva.num_huespedes)

    total_general = total_alojamiento + total_servicios + cargo_tardio
    saldo_pendiente = max(Decimal('0.00'), total_general - total_pagos)
    contexto = {
        'reserva': reserva,
        'momento_calculo': momento_actual,
        'hora_salida_oficial': hora_salida,
        'noches_facturadas': noches_facturadas,
        'noches_adicionales': noches_adicionales,
        'servicios': servicios,
        'pagos': pagos,
        'total_alojamiento': f"{int(total_alojamiento):,}".replace(',', '.'),
        'total_servicios': f"{int(total_servicios):,}".replace(',', '.'),
        'cargo_tardio': cargo_tardio,
        'cargo_tardio_fmt': f"{int(cargo_tardio):,}".replace(',', '.'),
        'total_general': f"{int(total_general):,}".replace(',', '.'),
        'total_pagos': f"{int(total_pagos):,}".replace(',', '.'),
        'saldo_pendiente_num': saldo_pendiente,
        'saldo_pendiente_fmt': f"{int(saldo_pendiente):,}".replace(',', '.'),
    }
    calculos = {
        'total_alojamiento': total_alojamiento,
        'noches_facturadas': noches_facturadas,
        'total_servicios': total_servicios,
        'cargo_tardio': cargo_tardio,
        'total_general': total_general,
        'total_pagos': total_pagos,
        'saldo_pendiente': saldo_pendiente,
    }
    return contexto, calculos


def _contexto_factura(factura):
    detalles = list(factura.detalles.all())
    pagos = list(factura.pagos_registrados.all())
    for detalle in detalles:
        detalle.precio_unitario_fmt = f"{int(detalle.precio_unitario):,}".replace(',', '.')
        detalle.subtotal_fmt = f"{int(detalle.subtotal):,}".replace(',', '.')
    for pago in pagos:
        pago.monto_fmt = f"{int(pago.monto):,}".replace(',', '.')
        pago.metodo_pago_display = dict(Pago.METODOS).get(pago.metodo_pago, pago.metodo_pago)
    return {
        'factura': factura,
        'detalles_factura': detalles,
        'pagos_facturados': pagos,
        'noches': factura.noches_facturadas,
        'total_alojamiento_fmt': f"{int(factura.total_alojamiento):,}".replace(',', '.'),
        'total_servicios_fmt': f"{int(factura.total_servicios):,}".replace(',', '.'),
        'cargo_tardio_fmt': f"{int(factura.cargo_tardio):,}".replace(',', '.'),
        'total_pagado_fmt': f"{int(factura.total_pagado):,}".replace(',', '.'),
        'total_fmt': f"{int(factura.total):,}".replace(',', '.'),
        'saldo_final_fmt': f"{int(factura.saldo_final):,}".replace(',', '.'),
    }


def enviar_factura_al_huesped(factura):
    contexto = _contexto_factura(factura)
    if not factura.huesped_correo:
        raise ValueError('La factura no tiene un correo de destino registrado.')
    mensaje_plano = (
        f"Hola {factura.huesped_nombre}, aquí está el detalle de tu factura {factura.numero} "
        "por tu estancia en Hotel Walena. Puedes imprimir este correo desde tu bandeja."
    )
    mensaje_html = render_to_string('emails/email_factura_estancia.html', contexto)
    enviados = enviar_correo_html_con_logo(
        f"Factura de alojamiento {factura.numero} — Hotel Walena",
        mensaje_plano,
        mensaje_html,
        factura.huesped_correo,
    )
    if enviados != 1:
        raise RuntimeError('El servidor de correo no confirmó el envío de la factura.')
    return enviados


def _parse_cop(raw_value):
    """Lee pesos colombianos escritos con separador de miles (p. ej. 50.000)."""
    limpio = (raw_value or '').strip().replace('$', '').replace('COP', '').replace(' ', '')
    limpio = limpio.replace('.', '').replace(',', '')
    return Decimal(limpio or '0')


def _datos_acompanantes_post(request, total_huespedes):
    datos = []
    errores = []
    for indice in range(1, total_huespedes):
        prefijo = f'acomp_{indice}_'
        item = {
            'nombres': request.POST.get(prefijo + 'nombres', '').strip(),
            'tipo_documento': request.POST.get(prefijo + 'tipo_documento', 'CC').strip(),
            'numero_documento': request.POST.get(prefijo + 'numero_documento', '').strip(),
            'telefono': request.POST.get(prefijo + 'telefono', '').strip(),
            'correo': request.POST.get(prefijo + 'correo', '').strip(),
            'nacionalidad': request.POST.get(prefijo + 'nacionalidad', 'Colombiana').strip() or 'Colombiana',
            'es_menor': request.POST.get(prefijo + 'es_menor') == 'on',
        }
        if not all((item['nombres'], item['tipo_documento'], item['numero_documento'], item['telefono'])):
            errores.append(f'Completa nombre, documento y teléfono del acompañante {indice}.')
        datos.append(item)
    return datos, errores


@requiere_rol('ADMIN_GERENTE', 'RECEPCIONISTA')
def ver_factura_estancia(request, factura_id):
    factura = get_object_or_404(Factura.objects.select_related('reserva'), pk=factura_id)

    if request.method == 'POST':
        try:
            enviar_factura_al_huesped(factura)
            factura.email_enviado_at = timezone.now()
            factura.save(update_fields=['email_enviado_at'])
            messages.success(request, f"La factura {factura.numero} se envió a {factura.huesped_correo}.")
        except Exception:
            logger.exception('No se pudo enviar la factura %s al correo del huésped.', factura.numero)
            messages.error(request, 'No se pudo enviar el correo. Revisa el correo registrado y la conexión de envío; puedes intentarlo nuevamente.')
        return redirect('factura_estancia', factura_id=factura.id)

    return render(request, 'facturas/factura_estancia_imprimible.html', _contexto_factura(factura))


def _invalidar_sesion_desactualizada(request):
    """Cierra sesiones de cuentas inactivas o con una versión de seguridad anterior."""
    usuario_id = request.session.get('usuario_id')
    if usuario_id is None:
        return

    try:
        usuario_id = int(usuario_id)
    except (TypeError, ValueError):
        usuario_id = None

    usuario = Usuario.objects.filter(pk=usuario_id, activo=True).first() if usuario_id else None
    if usuario is None or request.session.get('usuario_version_sesion') != usuario.version_sesion:
        request.session.flush()
        messages.warning(request, "Tu sesión terminó por un cambio de seguridad. Inicia sesión nuevamente.")

# region LANDING PAGE (VISTA PÚBLICA DEL CLIENTE)


def landing_page(request):
    _invalidar_sesion_desactualizada(request)
    if 'usuario_id' in request.session:
        rol = request.session.get('usuario_rol')
        if rol in ('ADMIN_GERENTE', 'RECEPCIONISTA'):
            return redirect('inicio')
        if rol == 'CLIENTE':
            # Área privada del cliente pendiente; mientras tanto permanece en la web pública.
            return render(request, 'publico/inicio_publico.html')
    
    # Si es un cliente normal, le mostramos la página bonita
    return render(request, 'publico/inicio_publico.html')


def vista_habitaciones(request):
    habitaciones = Habitacion.objects.select_related('tipo').order_by('numero')
    return render(request, 'publico/catalogo_habitaciones.html', {'habitaciones': habitaciones})
#endregion


# region INICIAR_SESION (Login)


def iniciar_sesion(request):
    _invalidar_sesion_desactualizada(request)
    if 'usuario_id' in request.session:
        if request.session.get('usuario_rol') == 'CLIENTE':
            return redirect('landing_page')
        return redirect('inicio')
    if request.method == 'POST':
        identificador = request.POST.get('identificador', '').strip()
        clave_input = request.POST.get('contrasena', '').strip()
        usuario = Usuario.objects.filter(
            Q(correo__iexact=identificador) | 
            Q(nombres__iexact=identificador),
            activo=True
        ).first()
        if usuario and (check_password(clave_input, usuario.contrasena) or usuario.contrasena == clave_input):
            if usuario.contrasena == clave_input:
                usuario.contrasena = make_password(clave_input)
                usuario.save()
            request.session.cycle_key()
            request.session['usuario_id'] = usuario.id
            request.session['usuario_nombre'] = f"{usuario.nombres} {usuario.apellidos}"
            request.session['usuario_rol'] = usuario.rol
            request.session['usuario_version_sesion'] = usuario.version_sesion
            if usuario.rol == 'CLIENTE':
                return redirect('landing_page')
            return redirect('inicio')
        else:
            messages.error(request, "Credenciales incorrectas.")
    return render(request, 'acceso/login.html')
#endregion



# region RECUPERAR CONTRASEÑA


def recuperar_clave(request):
    if request.method == 'POST':
        # Cada solicitud inicia un flujo nuevo y deja inválido cualquier código previo.
        limpiar_estado_recuperacion(request)
        nombre_input = request.POST.get('nombres', '').strip()
        correo_input = request.POST.get('correo', '').strip().lower()
        
        usuario = Usuario.objects.filter(
            nombres__iexact=nombre_input, 
            correo__iexact=correo_input, 
            activo=True
        ).first()
        
        if usuario:
            codigo_otp = str(random.randint(100000, 999999))
            
            request.session['reset_usuario_id'] = usuario.id
            request.session['reset_codigo_otp'] = codigo_otp
            request.session['reset_correo'] = usuario.correo
            request.session['reset_intentos'] = 0
            request.session['reset_codigo_creado_en'] = timezone.now().isoformat()
            
            # Cargar la plantilla HTML del correo desde el archivo separado
            html_mensaje = render_to_string('emails/codigo_recuperacion.html', {
                'usuario': usuario,
                'codigo_otp': codigo_otp
            })
            
            mensaje_plano = f"Hola {usuario.nombres},\n\nTu código de verificación es: {codigo_otp}"
            
            inicio_envio = perf_counter()
            try:
                enviados = enviar_correo_html_con_logo(
                    'Código de Verificación — Hotel Walena',
                    mensaje_plano,
                    html_mensaje,
                    usuario.correo,
                )
                duracion_envio = perf_counter() - inicio_envio
                if enviados != 1:
                    limpiar_estado_recuperacion(request)
                    logger.error(
                        'Brevo no aceptó el correo OTP (send_mail devolvió %s; %.3f s).',
                        enviados,
                        duracion_envio,
                    )
                else:
                    # El plazo de uso empieza cuando el servidor SMTP acepta el mensaje.
                    request.session['reset_codigo_creado_en'] = timezone.now().isoformat()
                    logger.info('Envío SMTP del correo OTP aceptado en %.3f s.', duracion_envio)
            except Exception:
                duracion_envio = perf_counter() - inicio_envio
                limpiar_estado_recuperacion(request)
                logger.exception('Falló el envío SMTP del correo OTP después de %.3f s.', duracion_envio)

        messages.info(
            request,
            "Si los datos corresponden a una cuenta activa y el correo pudo enviarse, recibirás instrucciones. Si no llega en unos minutos, revisa spam o contacta con administración."
        )
        return redirect('verificar_codigo')

    return render(request, 'acceso/recuperar_contrasena.html')


def verificar_codigo(request):
    if 'reset_usuario_id' not in request.session or 'reset_codigo_otp' not in request.session:
        if request.method == 'POST':
            messages.error(request, "El código no es válido o venció. Solicita uno nuevo si necesitas continuar.")
        return render(request, 'acceso/verificar_codigo_recuperacion.html')

    if codigo_recuperacion_vencido(request):
        limpiar_estado_recuperacion(request)
        messages.error(request, "El código venció. Solicita uno nuevo para continuar.")
        return redirect('recuperar_clave')

    if request.method == 'POST':
        codigo_ingresado = request.POST.get('codigo_otp', '').strip()
        codigo_real = request.session.get('reset_codigo_otp')
        intentos = request.session.get('reset_intentos', 0)

        if codigo_ingresado == codigo_real:
            request.session['reset_codigo_verificado'] = True
            request.session.pop('reset_codigo_otp', None)
            return redirect('restablecer_clave')
        else:
            intentos += 1
            request.session['reset_intentos'] = intentos
            if intentos >= OTP_MAX_INTENTOS:
                limpiar_estado_recuperacion(request)
                messages.error(request, "Has superado el límite de 5 intentos fallidos. Solicita un nuevo código.")
                return redirect('recuperar_clave')
            
            mensajes_restantes = OTP_MAX_INTENTOS - intentos
            messages.error(request, f"Código incorrecto. Te quedan {mensajes_restantes} intento(s).")

    return render(request, 'acceso/verificar_codigo_recuperacion.html', {
        'correo': request.session.get('reset_correo')
    })


def restablecer_clave(request):
    if not request.session.get('reset_codigo_verificado'):
        return redirect('recuperar_clave')

    # La validación debe seguir vigente también al guardar la contraseña.
    if codigo_recuperacion_vencido(request):
        limpiar_estado_recuperacion(request)
        messages.error(request, "El código venció. Solicita uno nuevo para continuar.")
        return redirect('recuperar_clave')

    if request.method == 'POST':
        nueva_clave = request.POST.get('nueva_clave', '').strip()
        confirmar_clave = request.POST.get('confirmar_clave', '').strip()

        if nueva_clave != confirmar_clave:
            messages.error(request, "Las contraseñas escritas no coinciden.")
            return redirect('restablecer_clave')

        usuario_id = request.session.get('reset_usuario_id')
        usuario = get_object_or_404(Usuario, pk=usuario_id)

        if len(nueva_clave) < 6:
            messages.warning(request, "La nueva contraseña debe tener al menos 6 caracteres.")
            return redirect('restablecer_clave')

        usuario.contrasena = make_password(nueva_clave)
        usuario.version_sesion += 1
        usuario.save()

        # Enviar el correo de confirmación usando su propia plantilla HTML
        hora_cambio = datetime.now().strftime('%d/%m/%Y a las %I:%M %p')
        html_confirmacion = render_to_string('emails/aviso_contrasena_actualizada.html', {
            'usuario': usuario,
            'hora_cambio': hora_cambio
        })
        
        mensaje_plano_conf = f"Hola {usuario.nombres},\n\nTu contraseña ha sido actualizada con éxito el {hora_cambio}."

        try:
            enviar_correo_html_con_logo(
                'Seguridad: Contraseña Actualizada Con Éxito — Hotel Walena',
                mensaje_plano_conf,
                html_confirmacion,
                usuario.correo,
            )
        except Exception as e:
            print(f"Error enviando aviso: {e}")

        limpiar_estado_recuperacion(request)
        request.session.flush()

        messages.success(request, "¡Tu contraseña ha sido restablecida exitosamente! Ya puedes iniciar sesión.")
        return redirect('login')

    return render(request, 'acceso/restablecer_contrasena.html')
#endregion



# region CAMBIAR_CLAVE (Cambiar Clave)


@requiere_rol('ADMIN_GERENTE', 'RECEPCIONISTA')
def cambiar_clave(request):
    if 'usuario_id' not in request.session:
        return redirect('login')

    if request.method == 'POST':
        clave_actual = request.POST.get('clave_actual', '').strip()
        nueva_clave = request.POST.get('nueva_clave', '').strip()
        confirmar_clave = request.POST.get('confirmar_clave', '').strip()

        usuario_id = request.session['usuario_id']
        usuario = get_object_or_404(Usuario, pk=usuario_id)

        if not check_password(clave_actual, usuario.contrasena) and usuario.contrasena != clave_actual:
            messages.error(request, "La contraseña actual es incorrecta.")
            return redirect('cambiar_clave')

        if nueva_clave != confirmar_clave:
            messages.error(request, "Las contraseñas nuevas no coinciden.")
            return redirect('cambiar_clave')
            
        if len(nueva_clave) < 6:
            messages.warning(request, "La nueva contraseña debe tener al menos 6 caracteres.")
            return redirect('cambiar_clave')

        usuario.contrasena = make_password(nueva_clave)
        usuario.version_sesion += 1
        usuario.save()

        messages.success(request, "¡Tu contraseña ha sido actualizada con éxito!")
        request.session.flush()
        return redirect('login')

    return render(request, 'acceso/cambiar_contrasena.html')
#endregion



# region CERRAR_SESION (Cerrar Sesión)


def cerrar_sesion(request):
    if request.method != 'POST':
        return redirect('inicio')

    # Limpia cualquier mensaje acumulado antes de cerrar sesión
    list(messages.get_messages(request)) 
    
    # Destruye la sesión
    request.session.flush()
    
    # Agrega el único mensaje que debe mostrarse en el login
    messages.info(request, "Has cerrado sesión correctamente.")
    return redirect('login')
#endregion



# region INICIO


# Estados que bloquean una habitación en el calendario. El estado físico de
# Habitacion describe el momento actual y no sustituye este filtro por fechas.
ESTADOS_RESERVA_QUE_BLOQUEAN_FECHAS = ('CONFIRMADA', 'CHECKIN')
ESTADOS_FISICOS_QUE_BLOQUEAN_NUEVAS_RESERVAS = ('EN_ASEO', 'MANTENIMIENTO')


def _parsear_fecha_iso(valor):
    """Acepta únicamente fechas completas con el formato HTML YYYY-MM-DD."""
    if not isinstance(valor, str) or not valor:
        return None
    try:
        fecha = datetime.strptime(valor, '%Y-%m-%d').date()
    except ValueError:
        return None
    return fecha if fecha.isoformat() == valor else None


def _habitacion_admite_fechas(habitacion, fecha_entrada, fecha_salida, excluir_reserva_id=None):
    """Indica si la habitación puede reservarse para el intervalo [entrada, salida)."""
    if habitacion.estado in ESTADOS_FISICOS_QUE_BLOQUEAN_NUEVAS_RESERVAS:
        return False

    reservas = Reserva.objects.filter(
        habitacion_id=habitacion.pk,
        estado__in=ESTADOS_RESERVA_QUE_BLOQUEAN_FECHAS,
        fecha_entrada__lt=fecha_salida,
        fecha_salida__gt=fecha_entrada,
    )
    if excluir_reserva_id is not None:
        reservas = reservas.exclude(pk=excluir_reserva_id)
    return not reservas.exists()


@requiere_rol('ADMIN_GERENTE', 'RECEPCIONISTA')
def inicio(request):
    if 'usuario_id' not in request.session:
        return redirect('login')

    # Orden operativo: disponibles, ocupadas, en aseo y en mantenimiento.
    habitaciones = Habitacion.objects.annotate(
        orden_estado=Case(
            When(estado='DISPONIBLE', then=Value(1)),
            When(estado='OCUPADA', then=Value(2)),
            When(estado='EN_ASEO', then=Value(3)),
            When(estado='MANTENIMIENTO', then=Value(4)),
            default=Value(5),
            output_field=IntegerField(),
        )
    ).order_by('piso', 'numero')

    # Una habitación físicamente ocupada debe mostrar la estancia que ya hizo
    # check-in; una reserva confirmada futura no representa a su ocupante actual.
    for hab in habitaciones:
        if hab.estado == 'OCUPADA':
            hab.reserva_activa = Reserva.objects.filter(
                habitacion=hab, 
                estado='CHECKIN'
            ).order_by('-id').first()

    contexto = {
        'habitaciones': habitaciones,
        'total_habitaciones': habitaciones.count(),
        'disponibles': habitaciones.filter(estado='DISPONIBLE').count(),
        'ocupadas': habitaciones.filter(estado='OCUPADA').count(),
        'en_aseo': habitaciones.filter(estado='EN_ASEO').count(),
        'en_mantenimiento': habitaciones.filter(estado='MANTENIMIENTO').count(),
        'usuario_nombre': request.session.get('usuario_nombre'),
        'usuario_rol': request.session.get('usuario_rol'),
    }
    return render(request, 'recepcion/panel_recepcion.html', contexto)
#endregion



# region DISPONIBILIDAD


def consulta_disponibilidad(request):
    hoy = timezone.localdate()
    mañana = hoy + timedelta(days=1)
    hay_busqueda = 'fecha_entrada' in request.GET or 'fecha_salida' in request.GET
    f_entrada = request.GET.get('fecha_entrada', '') if hay_busqueda else hoy.isoformat()
    f_salida = request.GET.get('fecha_salida', '') if hay_busqueda else mañana.isoformat()
    
    # Nuevos captadores
    num_adultos_raw = request.GET.get('num_adultos', '1')
    num_ninos_raw = request.GET.get('num_ninos', '0')
    trae_mascota = request.GET.get('trae_mascota') == 'on'

    entrada = _parsear_fecha_iso(f_entrada)
    salida = _parsear_fecha_iso(f_salida)
    error_fechas = ''
    if entrada is None or salida is None:
        error_fechas = 'Ingresa una fecha de entrada y una fecha de salida válidas.'
    elif entrada < hoy:
        error_fechas = 'La fecha de entrada no puede estar en el pasado.'
    elif salida <= entrada:
        error_fechas = 'La fecha de salida debe ser posterior a la fecha de entrada.'
    cant_noches = (salida - entrada).days if not error_fechas else None

    try:
        num_adultos = int(num_adultos_raw)
        num_ninos = int(num_ninos_raw)
        ocupacion_valida = num_adultos >= 1 and num_ninos >= 0
    except (TypeError, ValueError):
        num_adultos, num_ninos, ocupacion_valida = 1, 0, False
    error_ocupacion = '' if ocupacion_valida else 'Ingresa al menos un adulto y una cantidad de niños igual o mayor que cero.'

    total_personas = num_adultos + num_ninos
    capacidad_maxima = Habitacion.objects.aggregate(maxima=Max('tipo__capacidad'))['maxima'] or 0
    if ocupacion_valida and total_personas > capacidad_maxima:
        ocupacion_valida = False
        error_ocupacion = f'El hotel no tiene habitaciones con capacidad para {total_personas} huéspedes. El máximo disponible es {capacidad_maxima}.'
    # El estado físico sólo bloquea aseo/mantenimiento. Disponible y Ocupada
    # se evalúan para las fechas solicitadas mediante las reservas activas.
    habitaciones_disponibles = Habitacion.objects.exclude(
        estado__in=ESTADOS_FISICOS_QUE_BLOQUEAN_NUEVAS_RESERVAS
    )

    if ocupacion_valida:
        # Filtra que la habitación tenga capacidad para el total del grupo
        habitaciones_disponibles = habitaciones_disponibles.filter(tipo__capacidad__gte=total_personas)

    if not error_fechas and ocupacion_valida:
        reservas_solapadas = Reserva.objects.filter(
            estado__in=ESTADOS_RESERVA_QUE_BLOQUEAN_FECHAS,
            fecha_entrada__lt=salida,
            fecha_salida__gt=entrada
        ).values_list('habitacion_id', flat=True)

        habitaciones_disponibles = habitaciones_disponibles.exclude(id__in=reservas_solapadas)
    else:
        # No mostrar habitaciones como disponibles ante fechas inválidas.
        habitaciones_disponibles = habitaciones_disponibles.none()

    return render(request, 'publico/disponibilidad.html', {
        'habitaciones': habitaciones_disponibles,
        'f_entrada': f_entrada,
        'f_salida': f_salida,
        'num_adultos': num_adultos,
        'num_ninos': num_ninos,
        'num_adultos_form': num_adultos_raw,
        'num_ninos_form': num_ninos_raw,
        'trae_mascota': trae_mascota,
        'hoy': hoy.strftime('%Y-%m-%d'),
        'cant_noches': cant_noches,
        'error_fechas': error_fechas,
        'error_ocupacion': error_ocupacion,
    })
#endregion



# region CREAR RESERVA


@requiere_rol('ADMIN_GERENTE', 'RECEPCIONISTA')
def crear_reserva(request, habitacion_id):
    if 'usuario_id' not in request.session:
        return redirect('login')

    habitacion = get_object_or_404(Habitacion, pk=habitacion_id)
    hoy = timezone.localdate()
    fuente = request.POST if request.method == 'POST' else request.GET
    envio_fechas = 'fecha_entrada' in fuente or 'fecha_salida' in fuente
    fecha_entrada_raw = fuente.get('fecha_entrada', '') if envio_fechas else hoy.isoformat()
    fecha_salida_raw = fuente.get('fecha_salida', '') if envio_fechas else (hoy + timedelta(days=1)).isoformat()
    cantidad_adultos_raw = fuente.get('num_adultos', '1')
    cantidad_ninos_raw = fuente.get('num_ninos', '0')

    d_entrada = _parsear_fecha_iso(fecha_entrada_raw)
    d_salida = _parsear_fecha_iso(fecha_salida_raw)
    error_fechas = ''
    if d_entrada is None or d_salida is None:
        error_fechas = 'Ingresa fechas válidas para la entrada y la salida.'
    elif d_entrada < hoy:
        error_fechas = 'La fecha de entrada no puede estar en el pasado.'
    elif d_salida <= d_entrada:
        error_fechas = 'La fecha de salida debe ser posterior a la fecha de entrada.'

    try:
        num_adultos = int(cantidad_adultos_raw)
        adultos_validos = True
    except (TypeError, ValueError):
        num_adultos, adultos_validos = 1, False
    try:
        num_ninos = int(cantidad_ninos_raw)
        ninos_validos = True
    except (TypeError, ValueError):
        num_ninos, ninos_validos = 0, False
    cantidades_validas = adultos_validos and ninos_validos
    resumen_valido = (
        not error_fechas and cantidades_validas
        and num_adultos >= 1 and num_ninos >= 0
        and num_adultos + num_ninos <= habitacion.tipo.capacidad
    )

    cant_noches = (d_salida - d_entrada).days if not error_fechas else None
    tarifa_base = habitacion.tipo.precio_base_noche
    recargo_extras = Decimal(max(num_adultos - 1, 0)) * habitacion.tipo.cargo_persona_extra
    tarifa_total_noche = tarifa_base + recargo_extras
    total_estancia = Decimal(cant_noches) * tarifa_total_noche if resumen_valido else Decimal('0.00')
    exige_abono_50 = bool(resumen_valido and (d_entrada - hoy).days >= 5)
    abono_sugerido_50 = total_estancia * Decimal('0.50') if exige_abono_50 else Decimal('0.00')
    trae_mascota_get = fuente.get('trae_mascota') in ('on', 'True')
    contexto_formulario = {
        'hoy': hoy,
        'habitacion': habitacion, 'f_entrada': fecha_entrada_raw, 'f_salida': fecha_salida_raw,
        'num_adultos': cantidad_adultos_raw, 'num_ninos': cantidad_ninos_raw,
        'num_extras': num_adultos - 1, 'cant_noches': cant_noches,
        'error_fechas': error_fechas, 'resumen_valido': resumen_valido,
        'trae_mascota': trae_mascota_get,
        'tarifa_total_noche_fmt': f"{int(tarifa_total_noche):,}".replace(',', '.'),
        'total_estancia_fmt': f"{int(total_estancia):,}".replace(',', '.'),
        'exige_abono_50': exige_abono_50, 'abono_sugerido_50': abono_sugerido_50,
        'abono_sugerido_50_fmt': f"{int(abono_sugerido_50):,}".replace(',', '.'),
        'galeria_habitacion': habitacion.rutas_imagenes,
        'form_data': request.POST if request.method == 'POST' else {},
        'form_data_json': request.POST.dict() if request.method == 'POST' else {},
    }

    if request.method == 'POST':
        if error_fechas:
            messages.error(request, error_fechas)
            return render(request, 'reservas/crear_reserva.html', contexto_formulario)
        if not cantidades_validas:
            messages.error(request, 'Ingresa una cantidad válida de adultos y niños.')
            return render(request, 'reservas/crear_reserva.html', contexto_formulario)
        if num_adultos < 1 or num_ninos < 0 or num_adultos + num_ninos > habitacion.tipo.capacidad:
            messages.error(request, f'La habitación admite hasta {habitacion.tipo.capacidad} huéspedes. Ajusta la ocupación.')
            return render(request, 'reservas/crear_reserva.html', contexto_formulario)

        numero_documento = request.POST.get('numero_documento', '').strip()
        nombres = request.POST.get('nombres', '').strip()
        apellidos = request.POST.get('apellidos', '').strip()
        if not all((numero_documento, nombres, apellidos, request.POST.get('telefono', '').strip(), request.POST.get('correo', '').strip())):
            messages.error(request, 'Completa los datos obligatorios del huésped principal.')
            return render(request, 'reservas/crear_reserva.html', contexto_formulario)

        datos_acompanantes, errores_acompanantes = _datos_acompanantes_post(request, num_adultos + num_ninos)
        documentos = [numero_documento] + [item['numero_documento'] for item in datos_acompanantes]
        if errores_acompanantes or len(set(documentos)) != len(documentos):
            for error in errores_acompanantes:
                messages.error(request, error)
            if len(set(documentos)) != len(documentos):
                messages.error(request, 'Cada persona debe tener un número de documento distinto.')
            return render(request, 'reservas/crear_reserva.html', contexto_formulario)

        try:
            monto_abono = _parse_cop(request.POST.get('monto_abono', '0'))
        except (InvalidOperation, ValueError):
            messages.error(request, 'El valor del abono no es válido.')
            return render(request, 'reservas/crear_reserva.html', contexto_formulario)
        if not monto_abono.is_finite() or monto_abono < 0 or monto_abono > total_estancia or (exige_abono_50 and monto_abono < abono_sugerido_50):
            messages.error(request, f'El abono debe ser al menos ${int(abono_sugerido_50):,} y no superar el total de la estancia.'.replace(',', '.'))
            return render(request, 'reservas/crear_reserva.html', contexto_formulario)
        metodo_pago_abono = request.POST.get('metodo_pago', 'TRANSFERENCIA')
        if monto_abono > 0 and metodo_pago_abono not in dict(Pago.METODOS):
            messages.error(request, 'Selecciona un método de pago válido.')
            return render(request, 'reservas/crear_reserva.html', contexto_formulario)

        if not _habitacion_admite_fechas(habitacion, d_entrada, d_salida):
            messages.error(request, 'La habitación ya no está disponible para esas fechas. Selecciona otras fechas o una habitación distinta.')
            return render(request, 'reservas/crear_reserva.html', contexto_formulario)

        with transaction.atomic():
            # Serialize reservations for this room so two simultaneous requests
            # cannot both pass the availability check.
            habitacion = Habitacion.objects.select_for_update().select_related('tipo').get(pk=habitacion.pk)
            if not _habitacion_admite_fechas(habitacion, d_entrada, d_salida):
                messages.error(request, 'La habitación ya fue reservada para esas fechas. Elige otra opción.')
                return render(request, 'reservas/crear_reserva.html', contexto_formulario)

            huesped, _ = Huesped.objects.update_or_create(
                numero_documento=numero_documento,
                defaults={
                    'tipo_documento': request.POST.get('tipo_documento', 'CC'),
                    'nombres': nombres,
                    'apellidos': apellidos,
                    'telefono': request.POST.get('telefono', '').strip(),
                    'correo': request.POST.get('correo', '').strip(),
                    'nacionalidad': request.POST.get('nacionalidad', 'Colombiana').strip() or 'Colombiana',
                }
            )
            total_huespedes = num_adultos + num_ninos
            reserva = Reserva.objects.create(
                huesped=huesped,
                habitacion=habitacion,
                fecha_entrada=d_entrada,
                fecha_salida=d_salida,
                num_huespedes=total_huespedes,
                num_adultos=num_adultos,
                num_ninos=num_ninos,
                trae_mascota=request.POST.get('trae_mascota') == 'on',
                notas=request.POST.get('notas', '').strip(),
                canal_reserva=request.POST.get('canal_reserva', 'PRESENCIAL'),
                estado='CONFIRMADA',
            )
            reserva.valor_total = reserva.calcular_alojamiento()
            reserva.save(update_fields=['valor_total'])

            for item in datos_acompanantes:
                Acompanante.objects.create(reserva=reserva, **item)

            if monto_abono > 0:
                Pago.objects.create(
                    reserva=reserva,
                    monto=monto_abono,
                    metodo_pago=metodo_pago_abono,
                )

        # A confirmed future stay blocks only its dates. Physical room status
        # changes to OCUPADA when reception records the check-in.
        messages.success(request, f'Reserva #{reserva.id} confirmada. La habitación figurará ocupada al registrar el check-in.')
        return redirect('inicio')

    return render(request, 'reservas/crear_reserva.html', contexto_formulario)
#endregion



# region CHECK-IN COMPLETO


@requiere_rol('ADMIN_GERENTE', 'RECEPCIONISTA')
def registrar_checkin(request, reserva_id):
    if 'usuario_id' not in request.session:
        return redirect('login')

    reserva = get_object_or_404(Reserva, pk=reserva_id)
    huesped = reserva.huesped

    # Solo se puede hacer check-in si la reserva está en estado CONFIRMADA
    if reserva.estado != 'CONFIRMADA':
        messages.warning(request, f"La reserva #{reserva.id} no está en estado 'CONFIRMADA'.")
        return redirect('listar_reservas')

    hoy_checkin = timezone.localdate()
    if not (reserva.fecha_entrada <= hoy_checkin < reserva.fecha_salida):
        messages.error(request, 'El check-in solo se puede registrar durante las fechas de la reserva.')
        return redirect('listar_reservas')

    if request.method == 'POST':
        form_data = request.POST
        campos = ['tipo_documento', 'numero_documento', 'nombres', 'apellidos', 'telefono']
        datos = {campo: request.POST.get(campo, '').strip() for campo in campos}
        if not all(datos.values()):
            messages.error(request, 'Completa todos los datos obligatorios del huésped principal.')
            return render(request, 'recepcion/checkin/registrar_checkin.html', {'reserva': reserva, 'huesped': huesped, 'habitacion': reserva.habitacion, 'form_data': form_data})
        try:
            adultos = int(request.POST.get('num_adultos', reserva.num_adultos))
            ninos = int(request.POST.get('num_ninos', reserva.num_ninos))
        except (TypeError, ValueError):
            adultos, ninos = 0, -1
        cantidad = adultos + ninos
        if adultos < 1 or ninos < 0 or cantidad > reserva.habitacion.tipo.capacidad:
            messages.error(request, f'La ocupación no es válida. Ingresa al menos un adulto y no superes los {reserva.habitacion.tipo.capacidad} huéspedes permitidos para esta habitación.')
            return render(request, 'recepcion/checkin/registrar_checkin.html', {'reserva': reserva, 'huesped': huesped, 'habitacion': reserva.habitacion, 'form_data': form_data})
        try:
            monto_anticipo = _parse_cop(request.POST.get('monto_anticipo', '0'))
            metodo_pago = request.POST.get('metodo_pago', 'EFECTIVO')
            if not monto_anticipo.is_finite() or monto_anticipo < 0 or monto_anticipo > Decimal('99999999.99'):
                raise ValueError
            datos_acompanantes, errores = _datos_acompanantes_post(request, cantidad)
            documentos = [datos['numero_documento']] + [a['numero_documento'] for a in datos_acompanantes]
            if errores or len(set(documentos)) != len(documentos):
                raise ValueError
            if monto_anticipo > 0 and metodo_pago not in dict(Pago.METODOS):
                raise ValueError
        except (ValueError, InvalidOperation):
            messages.error(request, 'Revisa el número de huéspedes, el monto y el método de pago.')
            return render(request, 'recepcion/checkin/registrar_checkin.html', {'reserva': reserva, 'huesped': huesped, 'habitacion': reserva.habitacion, 'form_data': form_data})

        with transaction.atomic():
            reserva = Reserva.objects.select_for_update().select_related('habitacion__tipo', 'huesped').get(pk=reserva_id)
            habitacion = Habitacion.objects.select_for_update().get(pk=reserva.habitacion_id)
            hoy_checkin = timezone.localdate()
            if (
                reserva.estado != 'CONFIRMADA'
                or not (reserva.fecha_entrada <= hoy_checkin < reserva.fecha_salida)
                or habitacion.estado != 'DISPONIBLE'
            ):
                messages.error(request, 'La reserva cambió de estado o la habitación no puede recibir huéspedes.')
                return redirect('listar_reservas')
            if not _habitacion_admite_fechas(
                habitacion, reserva.fecha_entrada, reserva.fecha_salida,
                excluir_reserva_id=reserva.pk,
            ):
                messages.error(request, 'No se puede iniciar el check-in: la habitación tiene otra estancia activa que se cruza con estas fechas.')
                return redirect('listar_reservas')
            huesped = reserva.huesped
            for campo, valor in datos.items(): setattr(huesped, campo, valor)
            huesped.correo = request.POST.get('correo', '').strip()
            huesped.nacionalidad = request.POST.get('nacionalidad', 'Colombiana').strip() or 'Colombiana'
            huesped.save()
            reserva.num_huespedes = cantidad
            reserva.num_adultos = adultos
            reserva.num_ninos = ninos
            reserva.valor_total = reserva.calcular_alojamiento()
            reserva.estado = 'CHECKIN'
            reserva.save(update_fields=['num_huespedes', 'num_adultos', 'num_ninos', 'valor_total', 'estado'])
            reserva.acompanantes.all().delete()
            for acompanante in datos_acompanantes:
                Acompanante.objects.create(reserva=reserva, **acompanante)
            if monto_anticipo > 0:
                Pago.objects.create(reserva=reserva, monto=monto_anticipo, metodo_pago=metodo_pago)
            habitacion.estado = 'OCUPADA'
            habitacion.save()

        messages.success(request, f"Check-in completado para la reserva #{reserva.id}. {habitacion.nombre_completo} ahora está ocupada.")
        return redirect('inicio')

    # Ajustado a 'checkin/form_checkin.html' (asegúrate de renombrar la carpeta en VS Code a 'checkin')
    return render(request, 'recepcion/checkin/registrar_checkin.html', {
        'reserva': reserva,
        'huesped': huesped,
        'habitacion': reserva.habitacion
    })
#endregion



# region ESTADO DE HABITACIÓN


@requiere_rol('ADMIN_GERENTE', 'RECEPCIONISTA')
def cambiar_estado_habitacion(request, habitacion_id):
    if request.method != 'POST':
        return redirect('inicio')

    estado_destino = request.POST.get('estado_destino')
    transiciones_permitidas = {
        'EN_ASEO': {'MANTENIMIENTO', 'DISPONIBLE'},
        'MANTENIMIENTO': {'EN_ASEO'},
    }

    with transaction.atomic():
        habitacion = get_object_or_404(Habitacion.objects.select_for_update(), pk=habitacion_id)
        if estado_destino not in transiciones_permitidas.get(habitacion.estado, set()):
            messages.warning(request, "La habitación no puede cambiar a ese estado desde su estado actual.")
            return redirect('inicio')

        # Evita que una limpieza deje libre una habitación mientras todavía
        # existe una estancia con huéspedes dentro.
        if estado_destino == 'DISPONIBLE' and Reserva.objects.filter(
            habitacion=habitacion, estado='CHECKIN'
        ).exists():
            messages.error(request, 'No se puede marcar disponible: hay una estancia que aún no ha terminado.')
            return redirect('inicio')

        habitacion.estado = estado_destino
        habitacion.save(update_fields=['estado', 'codigo_color'])

    mensajes_estado = {
        'MANTENIMIENTO': f"{habitacion.nombre_completo} pasó a mantenimiento según el reporte presencial.",
        'EN_ASEO': f"La reparación de {habitacion.nombre_completo} terminó; volvió a aseo.",
        'DISPONIBLE': f"{habitacion.nombre_completo} quedó disponible tras confirmar la limpieza.",
    }
    messages.success(request, mensajes_estado[estado_destino])
    return redirect('inicio')

#endregion

# region CHECK-OUT COMPLETO


@requiere_rol('ADMIN_GERENTE', 'RECEPCIONISTA')
def registrar_checkout(request, reserva_id):
    if 'usuario_id' not in request.session:
        return redirect('login')

    reserva = get_object_or_404(Reserva.objects.select_related('huesped', 'habitacion__tipo'), pk=reserva_id)
    if reserva.estado != 'CHECKIN':
        messages.warning(request, f"La reserva #{reserva.id} no se encuentra en estado 'CHECKIN'.")
        return redirect('listar_reservas')

    contexto, _ = _calcular_cuenta_checkout(reserva)
    if request.method == 'POST':
        try:
            monto_pago = Decimal(request.POST.get('monto_pago', '0').strip() or '0')
            if not monto_pago.is_finite() or monto_pago < 0:
                raise InvalidOperation
            if monto_pago > Decimal('99999999.99') or monto_pago != monto_pago.quantize(Decimal('0.01')):
                raise InvalidOperation
        except (InvalidOperation, ValueError):
            messages.error(request, 'Escribe un monto válido, entre $0 y $99.999.999,99, con máximo dos decimales.')
            return render(request, 'recepcion/cerrar_estancia.html', contexto)

        metodo_pago = request.POST.get('metodo_pago', 'EFECTIVO')
        if monto_pago > 0 and metodo_pago not in dict(Pago.METODOS):
            messages.error(request, 'Selecciona un método de pago válido.')
            return render(request, 'recepcion/cerrar_estancia.html', contexto)

        with transaction.atomic():
            reserva = Reserva.objects.select_for_update().select_related('huesped', 'habitacion__tipo').get(pk=reserva_id)
            if reserva.estado != 'CHECKIN':
                messages.warning(request, f"La reserva #{reserva.id} ya no está lista para check-out.")
                return redirect('listar_reservas')

            habitacion = Habitacion.objects.select_for_update().get(pk=reserva.habitacion_id)
            if habitacion.estado != 'OCUPADA':
                messages.error(request, 'No se puede cerrar la estancia: la habitación no figura como ocupada. Revisa su estado antes de continuar.')
                return redirect('listar_reservas')

            contexto, calculos = _calcular_cuenta_checkout(reserva, timezone.localtime(), bloquear=True)
            saldo_pendiente = calculos['saldo_pendiente']
            if monto_pago != saldo_pendiente:
                messages.error(request, 'Para completar el check-out, registra exactamente el saldo pendiente mostrado.')
                return render(request, 'recepcion/cerrar_estancia.html', contexto)
            if monto_pago > 0 and metodo_pago not in dict(Pago.METODOS):
                messages.error(request, 'Selecciona un método de pago válido.')
                return render(request, 'recepcion/cerrar_estancia.html', contexto)

            if monto_pago > 0:
                Pago.objects.create(reserva=reserva, monto=monto_pago, metodo_pago=metodo_pago)

            reserva.cargo_tardio = calculos['cargo_tardio']
            reserva.valor_total = calculos['total_general']
            reserva.estado = 'CHECKOUT'
            reserva.save(update_fields=['cargo_tardio', 'valor_total', 'estado'])

            habitacion.estado = 'EN_ASEO'
            habitacion.save(update_fields=['estado', 'codigo_color'])

            factura, _ = Factura.objects.update_or_create(
                reserva=reserva,
                defaults={
                    'numero': f'WAL-{reserva.id:06d}',
                    'huesped_nombre': f'{reserva.huesped.nombres} {reserva.huesped.apellidos}'.strip(),
                    'huesped_tipo_documento': reserva.huesped.tipo_documento,
                    'huesped_numero_documento': reserva.huesped.numero_documento,
                    'huesped_correo': reserva.huesped.correo,
                    'habitacion_numero': reserva.habitacion.numero,
                    'habitacion_nombre': reserva.habitacion.tipo.nombre,
                    'habitacion_piso': reserva.habitacion.piso,
                    'fecha_entrada': reserva.fecha_entrada,
                    'fecha_salida': reserva.fecha_salida,
                    'noches_reservadas': reserva.calcular_noches(),
                    'noches_adicionales': calculos['noches_facturadas'] - reserva.calcular_noches(),
                    'noches_facturadas': calculos['noches_facturadas'],
                    'total_alojamiento': calculos['total_alojamiento'],
                    'total_servicios': calculos['total_servicios'],
                    'cargo_tardio': calculos['cargo_tardio'],
                    'total_pagado': calculos['total_pagos'] + monto_pago,
                    'total': calculos['total_general'],
                    'saldo_final': max(Decimal('0.00'), calculos['total_general'] - calculos['total_pagos'] - monto_pago),
                    'email_enviado_at': None,
                },
            )

            FacturaDetalle.objects.filter(factura=factura).delete()
            FacturaPago.objects.filter(factura=factura).delete()
            detalles = []
            noches_facturadas = calculos['noches_facturadas']
            if calculos['total_alojamiento'] > 0:
                detalles.append(FacturaDetalle(
                    factura=factura,
                    tipo='ALOJAMIENTO',
                    descripcion=f"Alojamiento en {reserva.habitacion.tipo.nombre} #{reserva.habitacion.numero} — {noches_facturadas} noche(s)",
                    cantidad=noches_facturadas,
                    precio_unitario=calculos['total_alojamiento'] / Decimal(noches_facturadas),
                    subtotal=calculos['total_alojamiento'],
                ))
            detalles.extend(
                FacturaDetalle(
                    factura=factura,
                    tipo='SERVICIO',
                    descripcion=f"{consumo.servicio.nombre} (x{consumo.cantidad})",
                    cantidad=consumo.cantidad,
                    precio_unitario=consumo.precio_unitario,
                    subtotal=consumo.subtotal,
                )
                for consumo in contexto['servicios']
            )
            if calculos['cargo_tardio'] > 0:
                detalles.append(FacturaDetalle(
                    factura=factura,
                    tipo='RECARGO',
                    descripcion='Recargo por salida tardía',
                    cantidad=1,
                    precio_unitario=calculos['cargo_tardio'],
                    subtotal=calculos['cargo_tardio'],
                ))
            FacturaDetalle.objects.bulk_create(detalles)

            pagos_facturados = [
                FacturaPago(
                    factura=factura,
                    pago_origen_id=pago.id,
                    monto=pago.monto,
                    metodo_pago=pago.metodo_pago,
                    fecha_pago=pago.fecha_pago,
                )
                for pago in Pago.objects.filter(reserva=reserva).order_by('fecha_pago')
            ]
            FacturaPago.objects.bulk_create(pagos_facturados)

        try:
            enviar_factura_al_huesped(factura)
            factura.email_enviado_at = timezone.now()
            factura.save(update_fields=['email_enviado_at'])
            messages.success(request, f"Check-out completado. La factura {factura.numero} se envió a {reserva.huesped.correo}.")
        except Exception:
            logger.exception('No se pudo enviar la factura %s al correo del huésped.', factura.numero)
            messages.warning(request, 'Check-out completado, pero no se pudo enviar el correo. Puedes reintentarlo desde la factura.')

        return redirect('factura_estancia', factura_id=factura.id)

    return render(request, 'recepcion/cerrar_estancia.html', contexto)
#endregion



# region LISTADO DE RESERVAS


@requiere_rol('ADMIN_GERENTE', 'RECEPCIONISTA')
def listar_reservas(request):
    if 'usuario_id' not in request.session:
        return redirect('login')

    estado_filtro = request.GET.get('estado', '')
    busqueda = request.GET.get('q', '').strip()

    reservas = Reserva.objects.all().select_related('huesped', 'habitacion', 'factura').order_by('-id')

    if estado_filtro:
        reservas = reservas.filter(estado=estado_filtro)

    if busqueda:
        reservas = reservas.filter(
            Q(huesped__nombres__icontains=busqueda) |
            Q(huesped__apellidos__icontains=busqueda) |
            Q(huesped__numero_documento__icontains=busqueda) |
            Q(habitacion__numero__icontains=busqueda)
        )

    return render(request, 'recepcion/listado_reservas.html', {
        'reservas': reservas,
        'estado_filtro': estado_filtro,
        'busqueda': busqueda
    })


@requiere_rol('ADMIN_GERENTE', 'RECEPCIONISTA')
def editar_reserva(request, reserva_id):
    reserva = get_object_or_404(Reserva.objects.select_related('huesped', 'habitacion__tipo'), pk=reserva_id)
    if reserva.estado != 'CONFIRMADA':
        messages.error(request, 'Solo se pueden editar reservas pendientes de check-in.')
        return redirect('listar_reservas')
    hoy = timezone.localdate()
    formulario = request.POST if request.method == 'POST' else {}
    valores_acompanantes = {}
    if request.method == 'POST':
        valores_acompanantes = request.POST.dict()
    else:
        for indice, acompanante in enumerate(reserva.acompanantes.all(), start=1):
            prefijo = f'acomp_{indice}_'
            valores_acompanantes.update({
                prefijo + 'tipo_documento': acompanante.tipo_documento,
                prefijo + 'numero_documento': acompanante.numero_documento,
                prefijo + 'nombres': acompanante.nombres,
                prefijo + 'telefono': acompanante.telefono,
                prefijo + 'correo': acompanante.correo,
                prefijo + 'nacionalidad': acompanante.nacionalidad,
                prefijo + 'es_menor': 'on' if acompanante.es_menor else '',
            })

    def contexto_edicion(error_fechas=''):
        return {
            'reserva': reserva,
            'hoy': hoy,
            'fecha_entrada_form': formulario.get('fecha_entrada', reserva.fecha_entrada.isoformat()),
            'fecha_salida_form': formulario.get('fecha_salida', reserva.fecha_salida.isoformat()),
            'num_adultos_form': formulario.get('num_adultos', str(reserva.num_adultos)),
            'num_ninos_form': formulario.get('num_ninos', str(reserva.num_ninos)),
            'form_data': formulario,
            'form_data_json': valores_acompanantes,
            'error_fechas': error_fechas,
        }

    if request.method == 'POST':
        entrada = _parsear_fecha_iso(request.POST.get('fecha_entrada', ''))
        salida = _parsear_fecha_iso(request.POST.get('fecha_salida', ''))
        error_fechas = ''
        if entrada is None or salida is None:
            error_fechas = 'Ingresa fechas válidas para la entrada y la salida.'
        elif entrada < hoy:
            error_fechas = 'La fecha de entrada no puede estar en el pasado.'
        elif salida <= entrada:
            error_fechas = 'La fecha de salida debe ser posterior a la fecha de entrada.'
        if error_fechas:
            messages.error(request, error_fechas)
            return render(request, 'reservas/editar_reserva.html', contexto_edicion(error_fechas))

        try:
            adultos = int(request.POST.get('num_adultos', ''))
            ninos = int(request.POST.get('num_ninos', ''))
            total = adultos + ninos
            if adultos < 1 or ninos < 0 or total > reserva.habitacion.tipo.capacidad:
                raise ValueError
        except (TypeError, ValueError):
            messages.error(request, 'Revisa la cantidad de adultos y niños; debe ser válida y no superar la capacidad de la habitación.')
            return render(request, 'reservas/editar_reserva.html', contexto_edicion())
        if not _habitacion_admite_fechas(
            reserva.habitacion, entrada, salida, excluir_reserva_id=reserva.pk
        ):
            messages.error(request, 'La habitación no está disponible para esas fechas.')
            return render(request, 'reservas/editar_reserva.html', contexto_edicion())
        datos, errores = _datos_acompanantes_post(request, total)
        docs = [reserva.huesped.numero_documento] + [x['numero_documento'] for x in datos]
        if errores or len(set(docs)) != len(docs):
            messages.error(request, errores[0] if errores else 'Los documentos de los huéspedes deben ser distintos.')
            return render(request, 'reservas/editar_reserva.html', contexto_edicion())
        with transaction.atomic():
            r = Reserva.objects.select_for_update().select_related('habitacion__tipo').get(pk=reserva.pk)
            if r.estado != 'CONFIRMADA':
                messages.error(request, 'La reserva ya cambió de estado y no se puede editar.')
                return redirect('listar_reservas')
            # Lock the room row so reservation creation, check-in, and edits
            # serialize on the same resource before the final overlap check.
            habitacion_bloqueada = Habitacion.objects.select_for_update().select_related('tipo').get(pk=r.habitacion_id)
            if not _habitacion_admite_fechas(
                habitacion_bloqueada, entrada, salida, excluir_reserva_id=r.pk
            ):
                messages.error(request, 'La habitación dejó de estar disponible para esas fechas. No se guardaron los cambios; revisa las fechas e inténtalo de nuevo.')
                return render(request, 'reservas/editar_reserva.html', contexto_edicion())
            r.fecha_entrada, r.fecha_salida = entrada, salida
            r.num_adultos, r.num_ninos, r.num_huespedes = adultos, ninos, total
            r.valor_total = r.calcular_alojamiento()
            r.save(update_fields=['fecha_entrada','fecha_salida','num_adultos','num_ninos','num_huespedes','valor_total'])
            r.acompanantes.all().delete()
            for item in datos: Acompanante.objects.create(reserva=r, **item)
        messages.success(request, f'Reserva #{r.id} actualizada.')
        return redirect('listar_reservas')
    return render(request, 'reservas/editar_reserva.html', contexto_edicion())


@requiere_rol('ADMIN_GERENTE', 'RECEPCIONISTA')
def cancelar_reserva(request, reserva_id):
    if request.method != 'POST':
        return redirect('listar_reservas')
    with transaction.atomic():
        reserva = get_object_or_404(Reserva.objects.select_for_update(), pk=reserva_id)
        if reserva.estado != 'CONFIRMADA':
            messages.error(request, 'Solo se pueden cancelar reservas pendientes de check-in.')
        else:
            reserva.estado = 'CANCELADA'
            reserva.save(update_fields=['estado'])
            messages.success(request, f'Reserva #{reserva.id} cancelada; se conservó en el historial.')
    return redirect('listar_reservas')
#endregion



# region LISTADO DE HUÉSPEDES


@requiere_rol('ADMIN_GERENTE', 'RECEPCIONISTA')
def listar_huespedes(request):
    if 'usuario_id' not in request.session:
        return redirect('login')

    busqueda = request.GET.get('q', '').strip()
    huespedes = Huesped.objects.all().order_by('apellidos', 'nombres')

    if busqueda:
        huespedes = huespedes.filter(
            Q(nombres__icontains=busqueda) |
            Q(apellidos__icontains=busqueda) |
            Q(numero_documento__icontains=busqueda) |
            Q(correo__icontains=busqueda)
        )

    return render(request, 'huespedes/listado_huespedes.html', {
        'huespedes': huespedes,
        'busqueda': busqueda
    })
#endregion



# region MÓDULO HUÉSPEDES


@requiere_rol('ADMIN_GERENTE', 'RECEPCIONISTA')
def crear_huesped(request):
    if 'usuario_id' not in request.session:
        return redirect('login')

    if request.method == 'POST':
        num_doc = request.POST.get('numero_documento', '').strip()
        
        # Verificar si el documento ya existe
        if Huesped.objects.filter(numero_documento=num_doc).exists():
            messages.error(request, f"Ya existe un huésped registrado con el documento N° {num_doc}.")
            return render(request, 'huespedes/formulario_huesped.html', {'huesped': request.POST})

        Huesped.objects.create(
            tipo_documento=request.POST.get('tipo_documento'),
            numero_documento=num_doc,
            nombres=request.POST.get('nombres', '').strip(),
            apellidos=request.POST.get('apellidos', '').strip(),
            telefono=request.POST.get('telefono', '').strip(),
            correo=request.POST.get('correo', '').strip(),
            nacionalidad=request.POST.get('nacionalidad', 'Colombiana').strip(),
        )
        messages.success(request, "Huésped registrado correctamente.")
        return redirect('listar_huespedes')

    return render(request, 'huespedes/formulario_huesped.html')
#endregion



# region EDITAR HUÉSPEDES


@requiere_rol('ADMIN_GERENTE', 'RECEPCIONISTA')
def editar_huesped(request, huesped_id):
    if 'usuario_id' not in request.session:
        return redirect('login')

    huesped = get_object_or_404(Huesped, pk=huesped_id)

    if request.method == 'POST':
        num_doc = request.POST.get('numero_documento', '').strip()
        
        # Validar duplicados si cambia de documento
        if Huesped.objects.filter(numero_documento=num_doc).exclude(id=huesped.id).exists():
            messages.error(request, f"El documento N° {num_doc} pertenece a otro huésped.")
            return render(request, 'huespedes/formulario_huesped.html', {'huesped': huesped})

        huesped.tipo_documento = request.POST.get('tipo_documento')
        huesped.numero_documento = num_doc
        huesped.nombres = request.POST.get('nombres', '').strip()
        huesped.apellidos = request.POST.get('apellidos', '').strip()
        huesped.telefono = request.POST.get('telefono', '').strip()
        huesped.correo = request.POST.get('correo', '').strip()
        huesped.nacionalidad = request.POST.get('nacionalidad', 'Colombiana').strip()
        huesped.save()

        messages.success(request, f"Información del huésped {huesped.nombres} actualizada exitosamente.")
        return redirect('listar_huespedes')

    return render(request, 'huespedes/formulario_huesped.html', {'huesped': huesped})
#endregion



# region DETALLE HUÉSPEDES


@requiere_rol('ADMIN_GERENTE', 'RECEPCIONISTA')
def detalle_huesped(request, huesped_id):
    if 'usuario_id' not in request.session:
        return redirect('login')

    huesped = get_object_or_404(Huesped, pk=huesped_id)
    reservas = Reserva.objects.filter(huesped=huesped).select_related('habitacion').order_by('-id')

    return render(request, 'huespedes/detalle_huesped.html', {
        'huesped': huesped,
        'reservas': reservas
    })
#endregion



# region SERVICIOS A LA RESERVA


@requiere_rol('ADMIN_GERENTE', 'RECEPCIONISTA')
def agregar_servicio_reserva(request, reserva_id):
    reserva = get_object_or_404(Reserva, id=reserva_id)
    
    if request.method == 'POST':
        servicio_id = request.POST.get('servicio_id')
        cantidad = int(request.POST.get('cantidad', 1))
        
        if servicio_id and cantidad > 0:
            servicio = get_object_or_404(Servicio, id=servicio_id)
            
            # Compartir el bloqueo de la reserva con el check-out evita que un
            # consumo entre a la cuenta después de calcular el saldo final.
            with transaction.atomic():
                reserva = Reserva.objects.select_for_update().get(pk=reserva_id)
                if reserva.estado != 'CHECKIN':
                    messages.error(request, 'Solo se pueden cargar consumos a una estancia que siga en curso.')
                    return redirect('listar_reservas')
                ServicioReserva.objects.create(
                    reserva=reserva,
                    servicio=servicio,
                    cantidad=cantidad,
                    precio_unitario=servicio.precio # Toma el precio actual del catálogo
                )
            messages.success(request, f"Se agregó {cantidad}x {servicio.nombre} a la reserva #{reserva.id}.")
        else:
            messages.error(request, "Por favor selecciona un servicio y una cantidad válida.")
            
        # Redirige de vuelta a la página de inicio
        return redirect('inicio')

    # Si es GET, pasamos la lista de servicios disponibles al template
    servicios_disponibles = Servicio.objects.all().order_by('categoria', 'nombre')
    return render(request, 'reservas/agregar_servicio.html', {
        'reserva': reserva,
        'servicios': servicios_disponibles

        
    })
#endregion












# ----------------------------------------------------
# MÓDULO DE USUARIOS, ROLES Y PERMISOS (CRUD COMPLETO)
# ----------------------------------------------------


def _validar_datos_usuario(request, usuario_item=None):
    datos = {
        'nombres': request.POST.get('nombres', '').strip(),
        'apellidos': request.POST.get('apellidos', '').strip(),
        'correo': request.POST.get('correo', '').strip().lower(),
        'rol': request.POST.get('rol', '').strip(),
        'contrasena': request.POST.get('contrasena', '').strip(),
    }
    errores = []

    for campo in ('nombres', 'apellidos'):
        valor = datos[campo]
        etiqueta = 'Los nombres' if campo == 'nombres' else 'Los apellidos'
        if not valor:
            errores.append(f'{etiqueta} son obligatorios.')
        elif len(valor) > 80:
            errores.append(f'{etiqueta} no pueden superar 80 caracteres.')

    if not datos['correo']:
        errores.append('El correo electrónico es obligatorio.')
    elif len(datos['correo']) > 254:
        errores.append('El correo electrónico no puede superar 254 caracteres.')
    else:
        try:
            validate_email(datos['correo'])
        except ValidationError:
            errores.append('Escribe un correo electrónico válido.')
        else:
            correos_registrados = Usuario.objects.filter(correo__iexact=datos['correo'])
            if usuario_item:
                correos_registrados = correos_registrados.exclude(pk=usuario_item.pk)
            if correos_registrados.exists():
                errores.append('Ese correo electrónico ya está registrado.')

    roles_personal = {'ADMIN_GERENTE', 'RECEPCIONISTA'}
    if datos['rol'] not in roles_personal:
        errores.append('Selecciona un rol de personal válido.')

    if usuario_item is None and not datos['contrasena']:
        errores.append('La contraseña es obligatoria al crear una cuenta.')
    elif datos['contrasena'] and len(datos['contrasena']) < 6:
        errores.append('La contraseña debe tener al menos 6 caracteres.')
    elif len(datos['contrasena']) > 128:
        errores.append('La contraseña no puede superar 128 caracteres.')

    return datos, errores


@requiere_rol('ADMIN_GERENTE')
def listar_usuarios(request):
    busqueda = request.GET.get('q', '').strip()
    usuarios = Usuario.objects.all().order_by('-activo', 'apellidos')

    if busqueda:
        usuarios = usuarios.filter(
            Q(nombres__icontains=busqueda) |
            Q(apellidos__icontains=busqueda) |
            Q(correo__icontains=busqueda) |
            Q(rol__icontains=busqueda)
        )

    return render(request, 'usuarios/listado_usuarios.html', {
        'usuarios': usuarios,
        'busqueda': busqueda
    })


@requiere_rol('ADMIN_GERENTE')
def crear_usuario(request):
    if request.method == 'POST':
        datos, errores = _validar_datos_usuario(request)
        if errores:
            for error in errores:
                messages.error(request, error)
            return render(request, 'usuarios/formulario_usuario.html', {'datos': request.POST})
        
        Usuario.objects.create(
            nombres=datos['nombres'],
            apellidos=datos['apellidos'],
            correo=datos['correo'],
            contrasena=make_password(datos['contrasena']),
            rol=datos['rol'],
            activo=request.POST.get('activo') == 'on'
        )
        messages.success(request, "Usuario y credenciales creados exitosamente.")
        return redirect('listar_usuarios')

    return render(request, 'usuarios/formulario_usuario.html')


@requiere_rol('ADMIN_GERENTE')
def editar_usuario(request, usuario_id):
    usuario_item = get_object_or_404(Usuario, pk=usuario_id)

    if request.method == 'POST':
        datos, errores = _validar_datos_usuario(request, usuario_item)
        if errores:
            for error in errores:
                messages.error(request, error)
            return render(request, 'usuarios/formulario_usuario.html', {
                'usuario_item': usuario_item,
                'datos': request.POST,
            })

        usuario_item.nombres = datos['nombres']
        usuario_item.apellidos = datos['apellidos']
        usuario_item.correo = datos['correo']
        usuario_item.rol = datos['rol']
        usuario_item.activo = request.POST.get('activo') == 'on'

        if datos['contrasena']:
            usuario_item.contrasena = make_password(datos['contrasena'])
            usuario_item.version_sesion += 1

        usuario_item.save()
        if datos['contrasena'] and usuario_item.id == request.session.get('usuario_id'):
            request.session.flush()
            messages.success(request, "Tu contraseña se actualizó. Inicia sesión con la nueva contraseña.")
            return redirect('login')

        messages.success(request, f"Usuario {usuario_item.nombres} actualizado correctamente.")
        return redirect('listar_usuarios')

    return render(request, 'usuarios/formulario_usuario.html', {'usuario_item': usuario_item})


@requiere_rol('ADMIN_GERENTE')
def cambiar_estado_usuario(request, usuario_id):
    if request.method != 'POST':
        return redirect('listar_usuarios')

    usuario_item = get_object_or_404(Usuario, pk=usuario_id)
    
    # Evitar deshabilitarse a sí mismo
    if usuario_item.id == request.session.get('usuario_id'):
        messages.error(request, "No puedes desactivar tu propia cuenta mientras estás en sesión.")
        return redirect('listar_usuarios')

    usuario_item.activo = not usuario_item.activo
    usuario_item.save()
    
    estado_txt = "activado" if usuario_item.activo else "desactivado"
    messages.info(request, f"El usuario {usuario_item.nombres} ha sido {estado_txt}.")
    return redirect('listar_usuarios')

