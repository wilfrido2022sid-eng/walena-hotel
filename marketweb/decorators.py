from django.shortcuts import redirect
from django.contrib import messages
from functools import wraps
from .models import Usuario

def requiere_rol(*roles_permitidos):
    """
    Decorador para restringir el acceso a vistas según el rol del usuario en sesión.
    Ejemplo: @requiere_rol('ADMIN_GERENTE')
    """
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):
            usuario_id_original = request.session.get('usuario_id')
            try:
                usuario_id = int(usuario_id_original) if usuario_id_original is not None else None
            except (TypeError, ValueError):
                usuario_id = None

            usuario = None
            if usuario_id is not None:
                usuario = Usuario.objects.filter(pk=usuario_id, activo=True).first()

            if usuario is None:
                if usuario_id_original is not None:
                    request.session.flush()
                messages.warning(request, "Debes iniciar sesión para acceder.")
                return redirect('login')

            version_sesion = request.session.get('usuario_version_sesion')
            if version_sesion != usuario.version_sesion:
                request.session.flush()
                messages.warning(request, "Tu sesión terminó por un cambio de seguridad. Inicia sesión nuevamente.")
                return redirect('login')
            
            # Refrescar los datos desde la base para que cambios de rol o de
            # estado de la cuenta se apliquen en la siguiente solicitud.
            request.session['usuario_rol'] = usuario.rol
            request.session['usuario_nombre'] = f"{usuario.nombres} {usuario.apellidos}"
            if usuario.rol not in roles_permitidos:
                messages.error(request, "No tienes permisos suficientes para acceder a esta sección.")
                return redirect('landing_page')
                
            return view_func(request, *args, **kwargs)
        return _wrapped_view
    return decorator
