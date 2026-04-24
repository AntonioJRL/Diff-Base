# Manual de usuario

## Tablero de Proyectos

Este tablero sirve para ver, en una sola pantalla, el avance de los proyectos que vienen de:

- `Servicio Pendiente` cuando todavía no existe una orden de venta.
- `Orden de Venta` cuando ya existe una venta asociada al proyecto.

La idea principal es que el usuario pueda:

- identificar qué proyecto está en curso,
- ver si va a tiempo o con retraso,
- revisar cuánto lleva avanzado,
- entrar al documento origen,
- y cambiar de etapa arrastrando la tarjeta.

---

## 1. Qué ves en pantalla

### Vista Kanban

Es la vista principal del tablero. Cada tarjeta representa un proyecto o un servicio.

En cada tarjeta verás:

- Nombre del registro.
- Origen del registro:
  - `Sin OS` si viene de un servicio pendiente.
  - `Con OS` si viene de una orden de venta.
- Cliente.
- Disciplina.
- Supervisor.
- Fecha de inicio.
- Fecha de fin planeada.
- Monto.
- Cantidad de unidades.
- Avance planeado.
- Avance real.
- Avance facturado.
- Cantidad de tareas.
- Color de semáforo.

### Vista Lista

Sirve para revisar muchos registros al mismo tiempo y aplicar filtros.

### Vista Formulario

Muestra el detalle de una tarjeta y permite abrir el origen, tareas, avances y otras acciones.

---

## 2. Botones principales

### Abrir origen

Abre el documento real desde donde viene la tarjeta.

Úsalo para:

- revisar información completa,
- corregir datos,
- consultar el historial,
- y entrar al documento original.

### Tareas

Abre las tareas relacionadas con ese proyecto o servicio.

### Avances

Abre los avances relacionados al proyecto.

### Actualizar

Refresca el tablero para ver cambios recientes.

### Recalcular métricas

Recalcula los datos de avance, tareas y semáforo.

Úsalo cuando:

- se corrigieron cantidades,
- se agregaron avances,
- se cambiaron tareas,
- o el tablero no refleja todavía el dato esperado.

### Archivar / Desarchivar

Marca el registro como archivado o activo.

Importante:

- no se archiva solo la tarjeta,
- se archiva el documento origen.

---

## 3. Cómo mover un proyecto

Las tarjetas se mueven arrastrándolas entre etapas.

Eso significa que el usuario no debe escribir la etapa manualmente. Solo debe:

1. Tomar la tarjeta.
2. Arrastrarla a la columna deseada.
3. Soltarla.

El sistema valida si ese cambio es posible y luego actualiza el documento origen.

---

## 4. Qué significa cada color

### Semáforo

- `Verde`: va en tiempo o incluso adelantado.
- `Ámbar`: va con una diferencia ligera respecto a lo planeado.
- `Rojo`: hay retraso importante.
- `Sin fecha`: no existe fecha de compromiso, así que el sistema no puede calcular el semáforo.

### Prioridad

La prioridad ayuda a identificar qué tarjeta merece atención antes.

- `Normal`
- `Media`
- `Alta`
- `Urgente`

### Alertas por fecha

Si una orden de venta no tiene fecha compromiso, el tablero mostrará una advertencia.

En ese caso:

- no se calcula retraso,
- no se fuerza un semáforo falso,
- y se pide revisar la orden de venta.

---

## 5. Cómo interpretar los datos

### Avance planeado

Es lo que el proyecto debería llevar según las fechas.

### Avance real

Es lo que realmente lleva ejecutado el proyecto.

### Avance facturado

Es lo que ya se ha facturado respecto al avance del proyecto.

### Días de retraso

Solo aparece cuando el proyecto ya venció y todavía no alcanza el avance esperado.

### Tareas

Muestra cuántas tareas tiene el proyecto y cuántas ya están terminadas.

---

## 6. Casos comunes

### Caso 1: Servicio pendiente sin orden de venta

Vas a ver la tarjeta como `Sin OS`.

Esto significa que:

- aún no existe orden de venta,
- el seguimiento se hace desde el servicio pendiente,
- y la tarjeta sigue mostrando avance, tareas y semáforo.

### Caso 2: Orden de venta con fecha compromiso

La tarjeta mostrará datos completos y el semáforo se calcula normalmente.

### Caso 3: Orden de venta sin fecha compromiso

La tarjeta mostrará una alerta.

Esto no significa que esté mal el proyecto, sino que falta completar la fecha para poder medirlo correctamente.

### Caso 4: Proyecto terminado

Aunque hubiera habido retraso antes, si ya se completó el avance o el documento está en estado final, el tablero lo refleja como cerrado o resuelto.

### Caso 5: Sin tareas

Si todavía no hay tareas asociadas, el tablero igual muestra el registro, pero el detalle operativo será más limitado.

---

## 7. Filtros útiles

El buscador permite encontrar proyectos por:

- cliente,
- supervisor,
- disciplina,
- empresa,
- prioridad,
- tipo de origen,
- estado,
- semáforo,
- fechas,
- y facturación.

También puedes agrupar registros por:

- estado,
- etapa,
- tipo,
- empresa,
- prioridad,
- disciplina.

---

## 8. Recomendaciones de uso

- Revisa primero el semáforo si necesitas detectar urgencias.
- Usa `Abrir origen` para corregir la información base.
- Usa `Recalcular métricas` cuando el tablero no se haya actualizado después de cambios.
- Usa los filtros para enfocarte solo en lo que necesita atención.
- Arrastra tarjetas solo cuando quieras cambiar realmente el estado del proyecto.

---

## 9. Qué documento alimenta el tablero

Este tablero se llena automáticamente con información de dos tipos de documentos:

- `pending.service`
- `sale.order`

De forma resumida:

- el cliente, supervisor, disciplina, fechas y montos vienen del documento origen,
- las tareas y avances se toman de los registros relacionados,
- el semáforo se calcula con base en fechas y avance real.

---

## 10. Apéndice técnico corto

Si soporte necesita revisar el comportamiento del tablero, debe validar:

- la vista SQL del modelo `project.control.board`,
- los estados de `pending.service`,
- los estados de `sale.order`,
- la fecha compromiso de la orden de venta,
- y las tareas o avances vinculados.

Archivos relacionados:

- [Modelo](/c:/Odoo/odoo17/odoo/modulos/project_modificaciones/models/project_control_board.py)
- [Vista](/c:/Odoo/odoo17/odoo/modulos/project_modificaciones/views/project_control_board_views.xml)
