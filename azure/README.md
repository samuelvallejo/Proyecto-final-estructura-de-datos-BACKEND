# Despliegue independiente de BacheScan en Azure

Esta preparación usa Azure for Students y despliega una instalación **nueva**, con base de datos vacía. Los usuarios se registran de nuevo en la dirección de Azure. La instalación existente de Vercel/Railway sigue siendo independiente.

## Arquitectura revisable

`azuredeploy.json` define 11 recursos (10 activos cuando `buildImageInAzure=false`) en un grupo nuevo `rg-bachescan-ai`:

| Recurso | Configuración |
| --- | --- |
| Azure Container Apps | Consumption, 0.5 vCPU, 1 GiB, entre 0 y 1 réplicas; HTTPS público, puerto interno 3001 |
| Entorno de Container Apps | Perfil Consumption, red virtual propia; sin GPU, perfil dedicado o endpoint privado de ACA |
| Azure Container Registry | Standard, imágenes privadas, autenticación por identidad; sin usuario administrador |
| ACR Task Run opcional | Deshabilitado por defecto: esta suscripción devuelve TasksOperationsNotAllowed |
| PostgreSQL Flexible Server | PostgreSQL 17, Burstable B1ms, 32 GiB, respaldo de 7 días, sin alta disponibilidad o crecimiento automático |
| Base `bachescan` | Creada vacía; Alembic aplica las migraciones al arrancar el contenedor |
| Red virtual | Subred de contenedores y subred delegada a PostgreSQL |
| Zona DNS privada y vínculo | Permiten resolver el servidor PostgreSQL dentro de la red |
| Identidad administrada y rol | AcrPull únicamente sobre el registro de este despliegue |

El frontend TypeScript y la API Python se sirven en **el mismo origen HTTPS**. El Dockerfile fija el commit del frontend `fcb5e0f3d3ca97ca319ce19857f56b808b721bcb`, ejecuta `npm ci` y compila `dist`. El backend conserva YOLO con `models/best.pt` y CPU; no descarga otro detector. Se ejecuta como usuario sin privilegios. El acceso a PostgreSQL es privado y usa TLS. Contraseñas y clave Fernet son parámetros `secureString` y secretos de Container Apps, nunca salidas ni archivos públicos.

`STATIC_ROOT` activa el servicio estático opcional. Las rutas API conservan sus sesiones y permisos. La web incluye las cabeceras para permitir cámara/GPS del mismo origen y bloquear inclusión en otros sitios. No se necesita modificar `VITE_API_URL`, guardar tokens en el frontend o conceder a Azure acceso de escritura a GitHub: El workflow revisado lee el código público y sube la imagen al registro privado mediante una identidad federada de la rama de Azure.

## Costes y autorización

Se debe revisar y autorizar el consumo de crédito **antes de crear los recursos**. La oferta de estudiante publicada incluye, para clientes elegibles, un registro Standard durante 12 meses y PostgreSQL B1ms hasta 750 horas/mes con 32 GiB de datos y respaldo. Container Apps incluye 180000 vCPU-segundos, 360000 GiB-segundos y 2 millones de solicitudes al mes por suscripción. Con 0.5 vCPU/1 GiB equivalen a unas 100 horas activas mensuales si las cuotas no se comparten con otras aplicaciones.

La red/DNS, compilaciones, transferencia y uso superior a las cuotas pueden consumir crédito. Al alcanzar 0 réplicas no se factura cómputo de la aplicación, pero los demás recursos pueden tener cargos. La elegibilidad y el crédito restante se comprueban en la cuenta; esto **no es una garantía de coste cero ni un límite duro de gasto**. No se cambia la suscripción a pago por uso. No hay apagado automático de PostgreSQL o del registro. Tras terminar las cuotas gratuitas deben revisarse los cargos antes de seguir usando los recursos.

Referencias oficiales consultadas el 29 de octubre de 2026:

- [Azure for Students: servicios y cuotas](https://azure.microsoft.com/en-us/free/students/)
- [Facturación de Container Apps](https://learn.microsoft.com/en-us/azure/container-apps/billing)
- [Precios de Azure Container Registry](https://azure.microsoft.com/en-us/pricing/details/container-registry/)
- [Compilar ACR Tasks desde una plantilla ARM](https://learn.microsoft.com/en-us/azure/container-registry/container-registry-task-run-template)
- [Desplegar una plantilla desde el portal](https://learn.microsoft.com/en-us/azure/azure-resource-manager/templates/deploy-portal)

## Publicación desde el portal

1. Revisar el código y publicar esta rama del backend. Seleccionar su SHA completo, no un identificador mutable, para la compilación real.
2. Crear una sola vez las credenciales locales con `python azure/new_parameters.py --backend-ref SHA`. Por defecto se guardan en el perfil del usuario, dentro de `.bachescan-azure/parameters.private.json`, fuera de OneDrive y Git. No sobrescribir ese archivo al actualizar una instalación.
3. Azure Portal → buscar **Template Deployment (implementar mediante plantillas personalizadas)** → **Cree su propia plantilla en el editor** → **Cargar archivo**, seleccionar `azure/azuredeploy.json` y guardar el borrador.
4. Seleccionar la suscripción autorizada, grupo nuevo `rg-bachescan-ai`, región admitida (West US, `westus`, confirmada en la política de esta suscripción) y prefijo `bachescanai`.
5. Tras la autorización del usuario, introducir la contraseña nueva y la clave Fernet en los campos seguros del formulario, y fijar backendRef al SHA publicado. No copiarlos a un repositorio, URL o documento público. La plantilla no tiene credenciales predeterminadas y no se puede usar sin configurar esos campos.
6. **Revisar y crear**, comprobar permisos y validación, resolver restricciones de región/cuotas si aparecen y crear únicamente los recursos aprobados. Azure puede requerir registrar los proveedores Microsoft.App, Microsoft.ContainerRegistry, Microsoft.DBforPostgreSQL, Microsoft.Network y Microsoft.ManagedIdentity.
7. Esperar a que la compilación de GitHub Actions y el despliegue finalicen; abrir la salida `applicationUrl`. Comprobar `/api/health`, registro/inicio de sesión, detector con `best.pt`, mapas y grafos. El primer acceso después de un escalado a cero puede tardar por el arranque del modelo.

La plantilla ARM todavía necesita la validación de la suscripción y una compilación real en ACR. Una validación local de JSON o pruebas del servicio estático no confirman por sí solas un despliegue correcto.

## Actualizaciones y protección de datos

Conservar `databasePassword` y `dataEncryptionKey`, nombres del servidor y grupo existentes. Cambiar el SHA de backend, el SHA de frontend e `imageTag` cuando corresponda, y ejecutar la plantilla en modo **Incremental**. No usar el modo Complete. Cambiar o perder la clave impide descifrar los datos ya guardados. No se transfieren registros desde Railway en esta instalación.

Pruebas locales: `python -m pytest tests/test_web.py -q`. Comprueban index, API JSON, prioridad de rutas, caché de assets y worker, cabeceras y archivos ausentes. El Dockerfile requiere una compilación Linux en ACR o Docker; no se ha instalado Docker en el PC para esta preparación.

## Compilación alternativa para esta suscripción

La primera ejecución confirmó que `ACR Tasks` devuelve `TasksOperationsNotAllowed`. Se conserva el registro privado y se prepara `.github/workflows/azure-image.yml`, que compila en un runner Linux de GitHub y sube la imagen a ese registro. `azure/github-build-identity.json` define tres recursos adicionales: identidad `bachescanai-build`, federación OIDC limitada exactamente al repositorio y rama `codex/azure-deployment`, y rol **AcrPush solo en el registro**. Estos permisos nuevos requieren autorización del usuario antes de crearlos.

Configurar las variables de Actions `AZURE_BUILD_CLIENT_ID`, `AZURE_TENANT_ID` y `AZURE_SUBSCRIPTION_ID` con las salidas de esa plantilla. Son identificadores, no contraseñas. La contraseña PostgreSQL y la clave Fernet no se envían a GitHub. El token OIDC es temporal, no se crea una contraseña de cliente y la identidad no tiene permiso para consultar o cambiar la base de datos ni desplegar otras aplicaciones. Actions usa versiones fijadas por SHA, `contents: read`, `id-token: write` y no mantiene credenciales de checkout.

La imagen resultante se etiqueta `azure-SHA_DEL_COMMIT_DEL_BACKEND`. Tras un workflow correcto, usar ese valor en `imageTag`, mantener `buildImageInAzure=false` y volver a aplicar `azuredeploy.json` en modo Incremental con los secretos existentes. La tarea de ACR opcional no se ejecuta. Los recursos ya creados se reutilizan.
