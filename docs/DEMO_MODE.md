# Modo de demostración seguro

## Riesgo verificado en producción

`GET /api/auth/demo` publica, a propósito, el correo y la contraseña de las tres cuentas demo, incluida la del
**Administrador**, y el servidor restablece esa contraseña en cada arranque. El 22 de noviembre de 2026, con esa cuenta
`GET /api/admin/users` devolvía el nombre y el correo descifrados de las cuentas reales del equipo. Además, cualquier
visitante podía cambiar roles, desactivar cuentas o marcar baches como reparados.

## Comportamiento con `DEMO_READ_ONLY=true` (valor por defecto)

| Acción con una cuenta demo | Antes | Ahora |
|---|---|---|
| Ver paneles, cola de mantenimiento, duplicados, búsqueda | Permitido | Permitido |
| Escanear, analizar fotos, publicar avisos, sus propios recorridos | Permitido | Permitido |
| Cambiar roles o el acceso de una cuenta | Permitido | 403 |
| Cambiar el estado de un bache (administración u operación) | Permitido | 403 |
| Fusionar duplicados | — | 403 |
| Ver el correo de cuentas reales | Visible | Enmascarado (`s•••@g•••.com`) |
| Ver nombre y lugares de recorridos de cuentas reales | Visible | «Oculto en la demostración» |

Las cuentas propias con rol Administrador u Operario conservan todos sus permisos. Para probar la gestión completa,
un administrador real asigna el rol a una cuenta registrada.

## Implementación

- `app/demo_policy.py`: `DemoPolicy` calcula al iniciar los identificadores de las cuentas demo (por el hash de su
  correo, sin descifrar nada) y expone `restricts(session)` y `mask_email`. La dependencia `forbid_demo_writes`
  protege los endpoints que cambian datos compartidos.
- `GET /api/me` incluye `isDemo` y `readOnly` para que la interfaz desactive esos controles y lo explique.
- `DEMO_READ_ONLY=false` vuelve al comportamiento anterior. La configuración de pruebas lo usa para seguir probando
  las escrituras con las cuentas demo.

## Pruebas

`tests/test_demo_policy.py` comprueba el enmascarado, las respuestas 403 de las cinco escrituras protegidas, que el
estado del bache no cambie, que la lectura siga disponible y que una cuenta real promovida conserve el acceso completo.
