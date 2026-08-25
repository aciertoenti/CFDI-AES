# Tarea: Cambiar contraseña sin depender de correo

## Contexto
La autenticación actual del proyecto acepta RFC/usuario y contraseña, pero el flujo de recuperación de contraseña estaba condicionado a enviar un correo electrónico. En desarrollo todavía no registramos correo para todos los usuarios, por lo que se bloqueaba el cambio de contraseña si no existía un email real.

## Objetivo
Permitir que un usuario autenticado cambie su contraseña usando su sesión actual, sin necesidad de que tenga un correo registrado o de enviar un enlace por email.

## Alcance
- Añadir un endpoint protegido por JWT para cambiar contraseña.
- Validar la contraseña actual antes de actualizar.
- Mantener la validación mínima de longitud de 8 caracteres.
- Exponer el soporte en el API Gateway.
- Agregar UI en la app autenticada para actualizar contraseña desde el panel.
- Mantener el flujo de recuperación por correo para producción, sin romper compatibilidad.

## Archivos afectados
- backend/microservices/auth_usuarios/main.py
- backend/microservices/auth_usuarios/auth_utils.py
- backend/microservices/auth_usuarios/test_auth_utils.py
- backend/api_gateway/main.py
- frontend/src/shared/hooks/useAuth.js
- frontend/src/App.jsx
- frontend/src/shared/layout/AppShell.jsx

## Criterios de aceptación
- [x] Un usuario autenticado puede cambiar la contraseña sin enviar correo.
- [x] La contraseña actual debe coincidir antes de cambiarla.
- [x] La nueva contraseña debe tener al menos 8 caracteres.
- [x] El flujo sigue funcionando en el gateway y en la UI.
- [x] La documentación de la tarea queda registrada en el repositorio.

## Notas de implementación
- El endpoint público de recuperación por email se mantiene intacto para escenarios reales de producción.
- El cambio directo de contraseña se realiza con el token JWT del usuario autenticado.
- Cuando aún no existe correo para un usuario en desarrollo, el sistema usa un placeholder seguro para evitar fallos de integración.
