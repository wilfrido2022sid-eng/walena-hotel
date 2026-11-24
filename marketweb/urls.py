from django.contrib import admin
from django.urls import path
from marketweb import views

urlpatterns = [
    path('admin/', admin.site.urls),
    
    # ==========================================
    # 1. RUTA RAÍZ (Vista Principal del Cliente)
    # ==========================================
    path('', views.landing_page, name='landing_page'),
    path('habitaciones/', views.vista_habitaciones, name='habitaciones'),
    path('disponibilidad/', views.consulta_disponibilidad, name='disponibilidad'),

    # ==========================================
    # 2. ACCESO Y SEGURIDAD (Login del Personal)
    # ==========================================
    path('login/', views.iniciar_sesion, name='login'),
    path('logout/', views.cerrar_sesion, name='logout'),
    path('cambiar-clave/', views.cambiar_clave, name='cambiar_clave'),

    # Rutas para recuperación de contraseña (OTP)
    path('recuperar-clave/', views.recuperar_clave, name='recuperar_clave'),
    path('verificar-codigo/', views.verificar_codigo, name='verificar_codigo'),
    path('restablecer-clave/', views.restablecer_clave, name='restablecer_clave'),

    # ==========================================
    # 3. PANEL ADMINISTRATIVO (SysHSENA - Recepción/Gerencia)
    # ==========================================
    path('panel/', views.inicio, name='inicio'),

    path('reserva/crear/<int:habitacion_id>/', views.crear_reserva, name='crear_reserva'),
    
    # Operaciones y Procesos
    path('reservas/', views.listar_reservas, name='listar_reservas'),
    path('reservas/<int:reserva_id>/editar/', views.editar_reserva, name='editar_reserva'),
    path('reservas/<int:reserva_id>/cancelar/', views.cancelar_reserva, name='cancelar_reserva'),
    path('checkin/<int:reserva_id>/', views.registrar_checkin, name='checkin'),
    path('checkout/<int:reserva_id>/', views.registrar_checkout, name='checkout'),
    path('facturas/<int:factura_id>/', views.ver_factura_estancia, name='factura_estancia'),
    path('habitacion/liberar/<int:habitacion_id>/', views.cambiar_estado_habitacion, name='liberar_habitacion'),

    # Módulo CRUD Huéspedes
    path('huespedes/', views.listar_huespedes, name='listar_huespedes'),
    path('huesped/crear/', views.crear_huesped, name='crear_huesped'),
    path('huesped/editar/<int:huesped_id>/', views.editar_huesped, name='editar_huesped'),
    path('huesped/detalle/<int:huesped_id>/', views.detalle_huesped, name='detalle_huesped'),
    path('reservas/<int:reserva_id>/agregar_servicio/', views.agregar_servicio_reserva, name='agregar_servicio_reserva'),

    # Módulo CRUD Usuarios
    path('usuarios/', views.listar_usuarios, name='listar_usuarios'),
    path('usuarios/crear/', views.crear_usuario, name='crear_usuario'),
    path('usuarios/editar/<int:usuario_id>/', views.editar_usuario, name='editar_usuario'),
    path('usuarios/estado/<int:usuario_id>/', views.cambiar_estado_usuario, name='cambiar_estado_usuario'),
]


