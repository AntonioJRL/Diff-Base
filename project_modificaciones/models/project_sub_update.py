from odoo import fields, models, api, _
from datetime import datetime, date
from odoo.exceptions import ValidationError, UserError
from markupsafe import Markup
import logging

_logger = logging.getLogger(__name__)

class ProjectSubUpdate(models.Model):
    _name = 'project.sub.update'
    _description = 'Avances fisicos y operativos'
    _order = 'date desc'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    # Integracion de Campos que vienen de Project Modificaciones (project sub update)
    state = fields.Selection([
        ('no_fact', 'No facturado'),
        ('fact', 'Facturado'),
        ('inc', 'Incobrable'),
    ], string= 'Estatus Factura', copy=False, default='no_fact', tracking=True)

    incidencia = fields.Many2one(
        'sale.order.incidencia',
        string="Incidencia",
        related='sale_order_id.incidencia'
    )
    ####################################################################

    # Campo para el nombre que se mostrara en la lista de busqueda
    display_name = fields.Char(
        string="Nombre a mostrar",
        compute="_compute_display_name",
        store=True,
    )

    @api.depends("name", "date")
    def _compute_display_name(self):
        for record in self:
            if record.name and record.date:
                formatted_date = record.date.strftime("%d/%m/%Y")
                record.display_name = f"{record.name} - {formatted_date}"
            else:
                record.display_name = record.name or "Nuevo Avance"

    # Metodo para buscar con la nueva logica
    @api.model
    def _name_search(
        self, name, args=None, operator="ilike", limit=100, name_get_uid=None, order=None
    ):
        args = args or []
        domain = []
        if name:
            domain = ["|", ("name", operator, name),
                      ("display_name", operator, name)]

        return self._search(domain + args, limit=limit, access_rights_uid=name_get_uid, order=order)

    # Campo para manejo de los estados del avance.
    avances_state = fields.Selection(
        [
            ("draft", "Borrador"),
            ("confirmed", "Confirmado"),
            ("assigned", "Asignado"),
        ],
        string="Estado del Avance",
        copy=False,
        default="draft",
        tracking=True,
        compute="_compute_avances_estados",
        store=True,
    )

    @api.depends("sale_order_id", "project_id", "task_id")
    def _compute_avances_estados(self):
        for record in self:
            # Para registros nuevos, siempre draft
            if not record.id:
                record.avances_state = "draft"
                continue

            # Si ya tiene un estado manualmente asignado y no es draft, respetarlo
            if record.avances_state in ["confirmed", "assigned"]:
                # Solo cambiar a assigned si está confirmed y tiene los datos completos
                if (
                    record.avances_state == "confirmed"
                    and record.project_id
                    and record.task_id
                    and record.sale_order_id
                ):
                    record.avances_state = "assigned"
                # Mantener el estado actual en otros casos
                continue

            # Lógica automática SOLO si está en draft
            if record.avances_state == "draft":
                if record.project_id and record.task_id and record.sale_order_id:
                    # Permanece en draft para permitir confirmación manual
                    record.avances_state = "draft"
                else:
                    record.avances_state = "draft"

    # Método opcional para confirmar utilizando un button desde la vista
    def action_confirmado_avances(self):
        for record in self:
            if record.avances_state == "draft":

                # Validación del estado de la tarea asociada antes de confirmar el avance.
                if record.task_id and record.task_id.is_control_obra:
                    # Si la tarea NO está aprobada, lanzamos alerta bloqueante
                    if record.task_id.approval_state != "approved":
                        raise ValidationError(
                            _(
                                "⛔ NO SE PUEDE CONFIRMAR EL AVANCE, ESTA PENDIENTE DE AUTORIZAR LA ACTIVIDAD\n\n"
                                "La tarea asociada (%s) se encuentra en estado (%s).\n"
                                "El flujo requiere que el Superintendente revise los (Datos Generales) de la tarea "
                                "y la APRUEBE antes de que usted pueda confirmar avances sobre ella."
                            )
                            % (
                                record.task_id.name,
                                dict(
                                    record.task_id._fields["approval_state"].selection
                                ).get(record.task_id.approval_state),
                            )
                        )

                # 1. Validación de campos requeridos
                record._validate_required_fields()

                # 2. Cambiar a estado confirmed
                vals = {"avances_state": "confirmed"}

                # 3. Si tiene todos los datos, pasar automáticamente a assigned
                if record.project_id and record.task_id and record.sale_order_id:
                    vals["avances_state"] = "assigned"
                    record.message_post(
                        body=_(
                            "El avance ha sido confirmado y asignado automáticamente."
                        )
                    )
                else:
                    record.message_post(
                        body=_("El avance ha sido confirmado manualmente.")
                    )

                # Aplicar los cambios
                record.write(vals)

                # 4. Refrescar vista del usuario para evitar duplicados OWL
                return {"type": "ir.actions.client", "tag": "reload"}
            else:
                raise UserError(
                    _("El avance solo puede ser confirmado desde el estado 'Borrador'.")
                )


    # Método para las validaciones
    def _validate_required_fields(self):
        """Validación que se ejecuta al confirmar el avance"""
        required_fields = {
            "producto": "Producto",
            "date": "Fecha",
            "ct": "CT (Centro de Trabajo)",
            "planta": "Planta",
            "hora_inicio": "Hora De Inicio",
            "hora_termino": "Hora De Termino",
            "supervisorplanta": "Supervisor Cliente",
            "responsible_id": "Supervisor Interno",
            "licencia": "Licencia/OM",
        }

        missing_fields = []
        for field_name, field_label in required_fields.items():
            if not getattr(self, field_name):
                missing_fields.append(f"- {field_label}")

        if missing_fields:
            error_message = _(
                "Antes de confirmar el avance, por favor complete los siguientes campos obligatorios:\n\n%s"
            ) % ("\n".join(missing_fields))
            raise ValidationError(error_message)

        # Validación de avance de unidades no sean negativas
        if self.unit_progress < 0:
            raise ValidationError(
                _("El avance de unidades no puede ser un valor negativo.")
            )

        # Validación de lógica de horas (Funciona para Datetime y Float)
        if self.hora_inicio and self.hora_termino:
            if self.hora_termino <= self.hora_inicio:
                raise ValidationError(
                    _("La hora de término debe ser posterior a la hora de inicio.")
                )

    # Método opcional para revertir a borrador utilizando un button desde la vista
    def action_revert_avances_to_draft(self):
        self.ensure_one()
        if self.avances_state in ("confirmed", "assigned"):
            self.avances_state = "draft"
            self.message_post(
                body=_("El avance ha sido revertido a 'Borrador'."))
        else:
            raise UserError(
                _("El avance no puede ser revertido a borrador desde el estado actual.")
            )

    # Indenficador para los avances
    name = fields.Char(
        string="ID Avance",
        copy=False,
        default=lambda self: _("Nuevo"),
        readonly=True,
        index=True,
        tracking=True,
    )

    # Método para crear y asignar la estructura al identificador
    @api.model_create_multi
    def create(self, vals_list):
        now = fields.Datetime.context_timestamp(self, fields.Datetime.now())
        date_str = now.strftime("%y%m%d%H%M%S")
        for vals in vals_list:
            if vals.get("name", "Nuevo") == "Nuevo":
                vals["name"] = f"{date_str}"  # vals["name"] = f"AV/{date_str}"

        records = super().create(vals_list)
        # Llama a la lógica de creación de tareas después de crear los registros
        records._try_create_preliminary_task()

        return records

    # Se ejecuta cada vez que se actualiza un registro.
    def write(self, vals):
        # Primero, ejecuta la escritura normal
        res = super().write(vals)
        # Después de guardar, intenta crear la tarea PEND por si se acaban de rellenar los campos 'producto' o 'ct'.
        self._try_create_preliminary_task()
        return res

    def _try_create_preliminary_task(self):
        # Busca el proyecto PEND una sola vez para el conjunto de registros.
        proyecto_pendiente = self.env["project.project"].search(
            [("name", "ilike", "VENTAS 2026")], limit=1
        )
        if not proyecto_pendiente:
            return  # Si no existe el proyecto PEND, no hacemos nada.

        # Itera sobre los avances (sea en creación o actualización)
        for record in self:
            # Condiciones para crear la tarea:
            # 1. Es preliminar (sin SO).
            # 2. Tiene producto y CT.
            # 3. Aún no tiene una tarea asignada.
            if (
                record.is_avance_preliminar
                and record.producto
                and record.ct
                and not record.task_id
            ):

                # Asigna el proyecto PEND si no lo tiene
                if not record.project_id:
                    record.project_id = proyecto_pendiente

                # Construye el nombre de la tarea y busca si ya existe
                nombre_tarea = (
                    f"{record.name or 'SOV'}-{record.producto.name}-{record.ct.name}"
                )
                tarea_existente = self.env["project.task"].search(
                    [
                        ("project_id", "=", proyecto_pendiente.id),
                        ("name", "=", nombre_tarea),
                    ],
                    limit=1,
                )

                if tarea_existente:
                    record.task_id = tarea_existente.id
                else:
                    _logger.info(
                        f"Creando tarea preliminar vía write/create: {nombre_tarea}"
                    )

                    supervisor_id = (
                        record.responsible_id.id if record.responsible_id else False
                    )

                    if not supervisor_id:
                        raise UserError(
                            _(
                                f"El avance {record.name} no tiene un Supervisor Interno asignado."
                                "Por ende no se puede crear la tarea preliminar."
                            )
                        )

                    nueva_tarea = self.env["project.task"].create(
                        {
                            "name": nombre_tarea,
                            "project_id": proyecto_pendiente.id,
                            "partner_id": record.cliente.id,
                            "is_control_obra": True,
                            "description": f"Creada automáticamente desde el avance {record.name}. Cliente: {record.cliente.name}.",
                            "supervisor_interno": supervisor_id,
                            "supervisor_cliente": record.supervisorplanta.id,
                            "centro_trabajo": record.ct.id,
                            "planta_trabajo": record.planta.id,
                        }
                    )
                    record.task_id = nueva_tarea.id

                    # Registrar mensaje en el Chatter de la tarea (Ocupamos el Markup para poder renderizar el mensaje en HTML
                    nueva_tarea.message_post(
                        body=Markup(
                            """
                            <div style="font-family: Arial, sans-serif; line-height: 1.6; text-align: justify;">
                                <b>📋 TAREA CREADA AUTOMÁTICAMENTE DESDE EL AVANCE</b><br/>
                                <span style="margin-left: 20px;">• Avance: %s</span><br/>
                                <span style="margin-left: 20px;">• Producto: %s</span><br/>
                                <span style="margin-left: 20px;">• Centro de Trabajo: %s</span><br/>
                                <span style="margin-left: 20px;">• Cliente: %s</span><br/>
                                <span style="margin-left: 20px;">• Proyecto: %s</span><br/>
                                <span style="margin-left: 20px;">• Fecha creación: %s</span><br/>
                                <span style="margin-left: 20px;">• Creado por: %s</span>
                            </div>
                        """
                        )
                        % (
                            record.name,
                            record.producto.name,
                            record.ct.name,
                            record.cliente.name if record.cliente else "N/A",
                            record.project_id.name,
                            fields.Datetime.now().strftime("%d/%m/%Y %H:%M"),
                            self.env.user.name,
                        ),
                        subject="Creación automática desde avance",
                        subtype_id=self.env.ref("mail.mt_note").id,
                    )
                    _logger.info(
                        f"Tarea preliminar creada: {nueva_tarea.name} para el avance {record.name}"
                    )

    # Método migracion compras, gastos, etc.
    def _migrate_related_records(self, old_task_id, new_task_id):
        if not old_task_id:
            return

        # 1. Migración (hr.expense)
        expenses_to_migrate = self.env["hr.expense"].search(
            [("task_id", "=", old_task_id)]
        )
        if expenses_to_migrate:
            expenses_to_migrate.write({"task_id": new_task_id})
            _logger.info(f"Migrado {old_task_id} para {new_task_id}")
            _logger.info(
                f"Migrado: {len(expenses_to_migrate)} expenses from Task ID {old_task_id} to Task ID {new_task_id}."
            )

        # 2. Migración (purchase.order)
        purchases_lines_to_migrate = self.env["purchase.order.line"].search(
            [("task_id", "=", old_task_id)]
        )
        if purchases_lines_to_migrate:
            # Se obtiene la nueva tarea para poder obtener el proyecto
            new_task = self.env["project.task"].browse(new_task_id)
            # Se preparan los valores: Tarea + Proyecto Nuevos
            vals = {
                "task_id": new_task_id,
                "project_id": new_task.project_id.id
            }
            purchases_lines_to_migrate.write(vals)
            _logger.info(
                f"Migrado {len(purchases_lines_to_migrate)} purchases from Task ID{old_task_id} to Task ID {new_task_id}."
            )

        """
        # 3. Migración (account.analytic.line) - Hojas de Horas
        timesheets_to_migrate = self.env['account.analytic.line'].search([('task_id', '=', old_task_id)])
        if timesheets_to_migrate:
            # Necesitamos obtener el project_id de la nueva tarea para asignarlo también
            new_task = self.env['project.task'].browse(new_task_id)
            timesheets_to_migrate.write({
                'task_id': new_task_id,
                'project_id': new_task.project_id.id
            })
            _logger.info(
                f"Migrado: {len(timesheets_to_migrate)} timesheets from Task ID {old_task_id} to Task ID {new_task_id}.")
        """
        """
        # 4. Migración - Compensaciones (Hojas de Horas)
        compensations_to_migrate = self.env['compensation.line'].search([('task_id', '=', old_task_id)])
        if compensations_to_migrate:
            # Necesitamos obtener el project_id de la nueva tarea para asignarlo también
            new_task = self.env['project.task'].browse(new_task_id)
            compensations_to_migrate.write({
                'task_id': new_task_id,
                'project_id': new_task.project_id.id
            })
            _logger.info(
                f"Migrado: {len(compensations_to_migrate)} compensations from Task ID {old_task_id} to Task ID {new_task_id}.")
        """

    # Campo para saber quien creo el avance.
    created_by = fields.Many2one(
        comodel_name="res.users",
        string="Capturado Por",
        default=lambda self: self.env.user,
        readonly=True,
        tracking=2,
    )

    pending_service_id = fields.Many2one(
        "pending.service",
        string="Servicio Pendiente",
        help="Servicio de origen que generó este avance.",
        tracking=True,
    )

    pending_service_line_id = fields.Many2one(
        "pending.service.line",
        string="Línea de Servicio Pendiente",
        help="Línea específica del servicio que generó este avance.",
        tracking=True,
    )

    is_avance_preliminar = fields.Boolean(
        string="Avance Preliminar",
        tracking=True,
        help="Indica si el avance esta sin ser asignado a una orden de venta",
        compute="_compute_avances_preliminar",
        store=True,
    )

    @api.depends("sale_order_id")
    def _compute_avances_preliminar(self):
        for record in self:
            record.is_avance_preliminar = not record.sale_order_id

    is_transferible = fields.Boolean(
        string="Transferible",
        compute="_compute_avances_transferible",
        store=True,
        help="Indica si el avance puede ser transferido a un proyecto con orden de venta",
    )

    @api.depends("avances_state", "is_avance_preliminar", "project_id")
    def _compute_avances_transferible(self):
        for record in self:
            record.is_transferible = (
                record.avances_state == "confirmed"
                and record.is_avance_preliminar
                and record.project_id
                and "PEND" in record.project_id.name
            )

    # Bandera para asignar avance a un proyecto desde la edicion del avance
    asignar_avance = fields.Boolean(
        string="Asignar Avance",
        default=False,
    )

    # Metodo para cambiar el estado
    def toggle_asignar_avance(self):
        for record in self:
            record.asignar_avance = not record.asignar_avance
            return True

    sale_order_line_id = fields.Many2one(
        "sale.order.line",
        string="Línea de Venta",
        related="task_id.sale_line_id",
        store=True,
    )

    partida_linea = fields.Char(
        related="sale_order_line_id.partida", string="Partida")

    ############################################################
    # SECCION PRINCIPAL DEL FORMATO DEL AVANCE: DATOS INTERNOS #
    ############################################################

    # Campo que hacer referencia con la orden de venta relacionada al proyecto.
    sale_order_id = fields.Many2one(
        "sale.order",
        string="Orden De Venta",
        related="task_id.sale_order_id",  # project_id.reinvoiced_sale_order_id
        help="Orden De Venta Relacionada Al Trabajo",
        tracking=True,
        store=True,
    )
    # Campo que hace referencia a las especialidades de la orden de venta.
    especialidad = fields.Many2many(
        "crm.tag",
        string="Especialidad",
        compute="_compute_especialidad",
        store=True,
        readonly=False,
    )
    
    @api.depends('sale_order_id.tag_ids')
    def _compute_especialidad(self):
        for record in self:
            record.especialidad = record.sale_order_id.tag_ids

    # Campo para mostrar a que proyecto se encuentra enlazado el avance.
    project_id = fields.Many2one(
        "project.project",
        string="Proyecto",
        domain="[('is_proyecto_obra', '=', True)]",
        help="Proyecto a cual el avance esta asignado.",
        tracking=True,
    )

    # Método para rellenar el campo project_id en base a la actualización.
    @api.onchange("update_id")
    def _onchange_update_id(self):
        if self.update_id and self.update_id.project_id:
            self.project_id = self.update_id.project_id

    # Método para manejar la transicion de los proyectos
    @api.onchange("project_id")
    def _onchange_project_id(self):
        """Cuando se cambia el proyecto, resetear la tarea si viene de PEND"""
        for record in self:
            if record.project_id and record.task_id:
                # Si el proyecto anterior era PEND y el nuevo no, resetear la tarea
                old_project = (
                    self.env["project.project"].browse(
                        self._origin.project_id.id)
                    if self._origin
                    else False
                )
                if (
                    old_project
                    and "PEND" in old_project.name
                    and "PEND" not in record.project_id.name
                ):
                    record.task_id = False

    # Campo para visualizar a que actufalización se asigno el avance.
    update_id = fields.Many2one(
        "project.update",
        string="Actualización",
        ondelete="cascade",
        help="Actualización a cual el avance esta asignado.",
        tracking=True,
    )

    # Campo para obtener la última actualización del proyecto al cual se asignara el avance
    ultima_actualizacion = fields.Char(
        string="Ultima Actualización",
        compute="_ultima_actualizacion",
        store=False,
    )

    @api.depends("project_id")
    def _ultima_actualizacion(self):
        for record in self:
            # Buscar el último registro de 'project_update' para el proyecto
            last_update = self.env["project.update"].search(
                [("project_id", "=", record.project_id.id)],
                order="create_date desc",
                limit=1,
            )

            if last_update:
                record.ultima_actualizacion = last_update.name
            else:
                record.ultima_actualizacion = "No hay actualizaciones previas."

    # Campo para visualizar con qué tarea se agregó el avance.
    task_id = fields.Many2one(
        "project.task",
        string="Tarea",
        help="Tarea Del Proyecto (Aqui Vera La Tarea En La Cual El Avance Estara Relacionado)",
        tracking=True,
        domain="[('project_id', '=', project_id), ('state', 'not in', ['1_canceled', '1_done']), ('approval_state', 'in',['draft','approved'])]",
    )

    # Campo visualizar el cliente.
    cliente_project = fields.Many2one(
        "res.partner",
        string="Cliente",
        # related="sale_order_id.partner_id",
        compute="_cliente_avance",
        help="Cliente Al Cual Se Le Va A Proveer El Trabajo",
        tracking=True,
        store=True,
    )
    # Método para obtener el cliente de manera automatica.
    @api.depends('sale_order_id.partner_id', 'task_id.partner_id')
    def _cliente_avance(self):
        for record in self:
            # Logica de cascada
            opcion_1 = record.sale_order_id.partner_id # Lo obtiene directamente de la orden de venta.
            opcion_2 = record.task_id.partner_id # Lo obtiene directamnete de la tarea sirve para pendientes.

            record.cliente_project = opcion_1 or opcion_2
    # Notas
    notas = fields.Char(
        string="Notas",
        help="Comentarios Pertinentes",
    )
    ############################################################
    #                SECCION DATOS DEL PRODUCTO                #
    ############################################################
    # Campo con relación al producto.
    producto = fields.Many2one(
        "product.product",
        string="Producto",
        help="Producto/Servicio A Trabajar",
        tracking=True,
        domain="[('sale_ok', '=', True),('type', '=', 'service')]",
    )

    # Campo relacionado con la especialidad del producto.
    especialidad_producto = fields.Many2one(
        string="Especialidad del Servicio",
        related="producto.categ_id",
        help="Especialidad Del Producto",
        tracking=True,
    )

    # Campo relacionado a la unidad de medida del producto.
    unidad_medida = fields.Many2one(
        string="Unidad",
        related="producto.uom_id",
        help="Unidad En La Que Se Mide Producto Ejemplo: Lote, Pza.",
        tracking=True,
    )

    # Campo relacionado al precio por unidad del producto.
    precio_unidad = fields.Float(
        related="producto.list_price",
        string="Precio Unitario",
        help="Precio Unitario Del Producto (Este Precio Es Sin IVA)",
        tracking=True,
    )

    ############################################################
    #               DATOS GENERALES DEL TRABAJO                #
    ############################################################
    # Campo que hace referencia al nombre de la orden de venta que a la vez es el nombre del proyecto.
    oc_pedido = fields.Char(
        string="OC/Pedido",
        related="project_id.name",
        help="Orden De Venta (Este Campo Depende Directamente De Tener Una Orden De Venta)",
        tracking=True,
    )
    # Campo fecha que hace referencia a la fecha de reporte del avance
    date = fields.Date(
        string="Fecha",
        help="Fecha En Que Se Realizo El Trabajo",
        tracking=True,
    )

    # Método para obtener la fecha del día y agregar el campo Date
    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        res["date"] = date.today()
        return res

    # Campo que hace referencia al centro de trabajo del avance.
    ct = fields.Many2one(
        "control.centro.trabajo",
        string="CT",
        help="Centro De Trabajo Donde Se Esta Realizando El Servicio",
        tracking=True,
    )

    # Campo que se ocupa para poder guardar el cliente del ct (Centro de Trabajo) Utilizado para Metodos No Impacta en la vista.
    cliente = fields.Many2one(
        "res.partner",
        string="Cliente del Centro De Trabajo",
        compute="_compute_cliente",
        store=True,
        tracking=True,
    )

    # Metodo para sacar el cliente de ct y asignarlo al campo cliente.
    @api.depends("ct")
    def _compute_cliente(self):
        for record in self:
            if record.ct and record.ct.cliente and record.ct.cliente.exists():
                record.cliente = record.ct.cliente
            else:
                record.cliente = False

    # Metodo para validación de Cliente CT corresponda con Cliente Planta, Area, Supervisor Cliente
    planta_domain = fields.Char(compute="_compute_domains", store=False)
    supervisor_domain = fields.Char(compute="_compute_domains", store=False)

    # Metodo para asignar los dominios a los campos, planta y supervisor cliente
    @api.depends("ct.cliente")
    def _compute_domains(self):
        for record in self:
            try:
                # Primero verificamos si existe el cliente, usando .exists() para proteger contra registros borrados
                if record.ct and record.ct.cliente and record.ct.cliente.exists():
                    cliente_id = record.ct.cliente.id
                    # Verificar que el ID sea válido (entero positivo)
                    if isinstance(cliente_id, int) and cliente_id > 0:
                        # Dominio para Planta: Se usa el campo 'cliente' que asume que existe en el modelo 'planta.avance'
                        planta_domain_list = [("cliente", "=", cliente_id)]

                        # Dominio para Supervisor: Se usa el campo 'cliente' en el modelo supervisor.area
                        supervisor_domain_list = [
                            ("cliente", "=", cliente_id),
                            #("tipo_contacto", "=", "supervisor"),
                        ]

                        planta_domain_str = str(planta_domain_list)
                        supervisor_domain_str = str(supervisor_domain_list)
                    else:
                        # ID inválido, usar dominio vacío
                        planta_domain_str = str([("id", "=", False)])
                        supervisor_domain_str = str([("id", "=", False)])
                else:
                    planta_domain_str = str([("id", "=", False)])
                    supervisor_domain_str = str([("id", "=", False)])

                record.planta_domain = planta_domain_str
                record.supervisor_domain = supervisor_domain_str

            except Exception as e:
                # Si hay cualquier error, usar dominio vacío para evitar crashes
                _logger.warning(f"Error calculando dominios para record {record.id}: {e}")
                record.planta_domain = str([("id", "=", False)])
                record.supervisor_domain = str([("id", "=", False)])

            # Limpieza de campos si no coinciden
            # CORREGIDO: Verificación segura de existencia
            cliente_ct_id = record.ct.cliente.id if (record.ct and record.ct.cliente and record.ct.cliente.exists()) else False
            
            # Chequeo Planta
            if record.planta:
                 # Si no existe el cliente en CT o la planta no corresponde, limpiar
                 if not cliente_ct_id or (record.planta.cliente and record.planta.cliente.id != cliente_ct_id):
                      record.planta = False

            # Validación correcta para el supervisor
            # CORREGIDO: Verificación segura de existencia
            if record.supervisorplanta:
                # Si no tenemos cliente valido, o el supervisor no tiene padre valido, o no coinciden
                if not cliente_ct_id:
                     record.supervisorplanta = False
                elif not record.supervisorplanta.cliente or not record.supervisorplanta.cliente.exists():
                     # El supervisor tiene un padre borrado o no tiene padre
                     record.supervisorplanta = False
                elif record.supervisorplanta.cliente.id != cliente_ct_id:
                     # El padre existe pero no es el cliente actual
                     record.supervisorplanta = False

    # Campo para ?.
    or_rfq = fields.Char(
        string="OR/RFQ",
        help="Cotizaciónes",
        tracking=True,
    )

    # Campo para agregar el número de cotización del avance o servicio a realizar/reportar.
    no_cotizacion = fields.Char(
        string="No. Cotización",
        tracking=True,
    )

    # Campo que muestra la especialidad del trabajo que se esta haciendo.
    especialidad_trabajo = fields.Many2one(
        string="Especialidad De Trabajo",
        related="task_id.disc",
        help="Especialidad Del Trabajo (Este Dependera Directamente De La Etiquetas En La Orden De Venta)",
        tracking=True,
    )

    ############################################################
    #            DESCRIPCIÓN DETALLADA DEL TRABAJO             #
    ############################################################
    # Campo que describe la planta donde se realizo el trabajo del avance presentado.
    planta = fields.Many2one(
        "control.planta",
        string="Planta",
        help="Planta en la que se realiza el trabajo.",
        tracking=True,
    )

    # Campo para asignar el area exacta donde se realizo el servicio o se esta realizando.
    area_equipo = fields.Char(
        string="Area Trabajo Y/O Tag. Equipo",
        help="Area Y/O equipo donde se realiza el trabajo.",
        tracking=True,
    )

    # Campo con la hora de inicio reportada de la realizacion del trabajo/servicio que reporta el avance
    hora_inicio = fields.Datetime(
        string="Hora De Inicio",
        help="Hora Inicio Del Trabajo",
        tracking=True,
    )

    # Campo con la hora de termino reportada de la realizacion del trabajo/servicio que reporta el avance
    hora_termino = fields.Datetime(
        string="Hora De Termino",
        help="Hora Termino Del Trabajo",
        tracking=True,
    )

    # Campo para asignar el responsable de supervisar el servicio por parte del cliente.
    supervisorplanta = fields.Many2one(
        "supervisor.area",
        string="Supervisor Cliente",
        help="Supervisor Del Trabajo Por Parte Del Cliente",
        tracking=True,
    )

    # Campo para asignar el responsable del servicio a realizar por parte interna (AYASA).
    responsible_id = fields.Many2one(
        "hr.employee",
        string="Supervisor Interno",
        domain="[('supervisa', '=', True)]",
        help="Supervisor Del Trabajo Interno (AYASA)",
        tracking=True,
    )

    licencia = fields.Many2one(
        'license.license',
        string="Licencia/OM",
        help="Licencia Proporcionado Por El Cliente/Planta Para Poder Realizar El Trabajo",
        tracking=True,
    )

    ############################################################
    #                      AVANCES ACTUAL                      #
    ############################################################
    # Avance Actual
    unit_progress = fields.Float(string="Avance de Unidades", default=0.00)
    actual_progress_percentage = fields.Float(
        compute="_actual_progress_percentage", string="Avance Porcentual", default=0.00
    )
    virtual_quant_progress = fields.Float(
        string="Unidades Entregadas (virtual)",
        compute="_virtual_quant_progress",
        store=True,
        default=0.0,
    )
    missing_quant = fields.Float(
        string="Unidades Faltantes", compute="_missing_quant")

    # Avance del Servicio
    # CHANGE: quant_total now computed to support fallback to piezas_pendientes
    quant_total = fields.Float(
        string="Unidades a Entregar",
        compute="_compute_quant_total",
        store=True
    )
    sale_current = fields.Float(
        string="Avance Del Subtotal", compute="_sale_current", store=True
    )
    virtual_total_progress = fields.Integer(
        string="Progreso Total (virtual)", compute="_virtual_total_progress", default=0
    )

    # Campo para manejar el costo del avance antes de ser asignado a un proyecto.
    costo_avance = fields.Float(
        string="Costo Del Avance",
        tracking=True,
        help="Costo Total Del Avance (Este Costo Es Representado Por El Valor Unitario Del Producto X El Total De Unidades Entregadas)",
        compute="compute_costo_avance",
        store=True,
    )

    # Metodo para calcular el valor del avance antes de ser asignado a un proyecto/orden de venta
    @api.depends("pending_service_line_id.price_unit", "unit_progress", "task_id")
    def compute_costo_avance(self):
        for record in self:
            price = 0.0
            # 1. Si ya tiene linea asignada, usar su precio
            if record.pending_service_line_id:
                price = record.pending_service_line_id.price_unit
            # 2. Si no, buscar la linea por medio de la tarea
            elif record.task_id:
                line = self.env['pending.service.line'].search([
                    ('task_id', '=', record.task_id.id)
                ], limit=1)
                if line:
                    price = line.price_unit
                    # Opcional: Auto-vincular para el futuro
                    # record.pending_service_line_id = line.id

            record.costo_avance = price * record.unit_progress
            
    currency_id = fields.Many2one(
        "res.currency",
        string="Moneda",
        # Relaciona la moneda con la de la orden de venta, o usa la de la compañía por defecto
        related="sale_order_id.currency_id",
        store=True,
        help="La moneda del avance, tomada de la orden de venta.",
    )

    costo_avance_formateado = fields.Char(
        compute="_compute_costo_formateado",
        string="Costo Del Avance Formateado",
        store=True,
    )

    # Metodo para el formateado del campo costo avance
    @api.depends("costo_avance")
    def _compute_costo_formateado(self):
        for record in self:
            record.costo_avance_formateado = "${:,.2f}".format(
                record.costo_avance)

    bitacorapmv = fields.Boolean(
        string="Bitacora PMV",
        default=False,
        help="Indica si este avance cuenta con bitacora",
    )
    om = fields.Char(string="# OM")
    # numlic = fields.Char(string="#Bitacora/Lic.", store=True, size=20)
    # numlic = fields.Many2one("control.licencias",string="#Bitacora/Lic.", size=20)
    cot = fields.Char(string="#Cot/Presupuesto", store=True)
    estimado = fields.Boolean(
        string="Estimado",
        default=False,
        help="Indica si este avance ya ha sido estimado",
    )
    avanceparc = fields.Char(string="Avance Parcial")
    datefact = fields.Date(string="Fecha De Factura", store=True)
    factura = fields.Many2one(
        "account.move",
        string="Factura",
        domain="[('state', '=', 'posted'), ('move_type', '=', 'out_invoice')]",
    )
    sale_total = fields.Float(
        string="Subtotal De La Venta", compute="_sale_total", store=True
    )
    sale_actual = fields.Float(
        string="Subtotal Entregado", compute="_sale_actual", store=True
    )
    sale_missing = fields.Float(
        string="Subtotal Faltante", compute="_sale_missing", store=True
    )

    proj = fields.Many2one(related="update_id.project_id")
    projid = fields.Integer(related="proj.id", string="ID Del Proyecto")
    projname = fields.Char(
        related="proj.name",
        string="Nombre Del Proyecto",
    )
    prev_progress = fields.Integer(
        related="task_id.progress",
        string="Current Progress",
    )
    quant_progress = fields.Float(
        string="Unidades Entregadas", compute="_quant_progress", store=True, default=0.0
    )
    actual_progress = fields.Float(
        compute="_actual_progress", string="Avance", default=0.00, store=True
    )
    total_progress = fields.Integer(
        string="Progreso Total", compute="_total_progress", store=True, default=0
    )
    total_progress_percentage = fields.Float(
        compute="_total_progress_percentage")

    # Text
    sale_current_text = fields.Char(
        string="Avance Del subtotal (pesos)", compute="_sale_current_text", store=True
    )
    sale_actual_text = fields.Char(
        string="Subtotal Entregado (pesos)", compute="_sale_actual_text", store=True
    )
    sale_total_text = fields.Char(
        string="Subtotal De La Venta (pesos)", compute="_sale_total_text", store=True
    )
    sale_missing_text = fields.Char(
        string="Subtotal Faltante (pesos)", compute="_sale_missing_text", store=True
    )

    task_name = fields.Char(related="task_id.name",
                            string="Nombre De La Tarea")
    domain = fields.Char(string="Dominio", compute="_dom")
    color = fields.Integer(related="update_id.color", string="Color")
    estado = fields.Selection(
        related="update_id.status", string="Estado Tarea")

    invoiced = fields.Float(
        string="Facturado", related="task_id.invoiced", store=True)
    is_invoiced = fields.Boolean(
        string="¿Avance Facturado?",
        default=False,
        help="Indica si este avance ya ha sido facturado",
    )
    cotizacion = fields.Char(string="# Cotización")

    @api.onchange("factura")
    def _onchange_factura(self):
        if self.factura:
            self.datefact = self.factura.invoice_date

    def action_mark_invoiced(self):
        for record in self:
            record.is_invoiced = True
            record.state = "fact"

    def action_mark_not_invoiced(self):
        for record in self:
            record.is_invoiced = False
            record.state = "no_fact"

    def action_mark_incobrable(self):
        for record in self:
            record.is_invoiced = False
            record.state = "inc"

    @api.depends("unit_progress")
    def _project_id(self):
        for u in self:
            u.project_id = u.env["project.project"].search(
                [("id", "=", u.projid)], limit=1
            )

    @api.model
    def _chosen_tasks(self):
        for u in self:
            tasks = (
                u.env["project.sub.update"]
                .search([("update_id.id", "=", u.update_id.id)])
                .mapped("task_id.id")
            )
            chosen = ""
            for i in tasks:
                chosen = chosen + str(i) + " "
            return chosen.split()

    @api.depends("unit_progress", "task_id")
    def _quant_progress(self):
        for u in self:
            progress = u.task_id.quant_progress
            u.quant_progress = progress

    @api.depends("task_id.total_pieces", "task_id.piezas_pendientes")
    def _compute_quant_total(self):
        """
        Calcula el total de unidades a entregar.
        Si hay una línea de venta asociada (total_pieces > 0), usa esa.
        Si no, usa piezas_pendientes como fallback idealmente para tareas preliminares.
        """
        for u in self:
            # Si tiene pieces por sale order line, prioridad 1
            if u.task_id.total_pieces:
                 u.quant_total = u.task_id.total_pieces
            # Si no, usa piezas_pendientes (creado para tareas sin SO aun)
            elif u.task_id.piezas_pendientes:
                 u.quant_total = u.task_id.piezas_pendientes
            else:
                 u.quant_total = 0.0

    @api.depends("unit_progress", "quant_total")
    def _actual_progress(self):
        for u in self:
            if u.quant_total > 0:
                progress = (u.unit_progress / u.quant_total) * 100
            else:
                progress = 0
            u.actual_progress = progress

    @api.depends("unit_progress", "task_id", "quant_total", "virtual_quant_progress")
    def _total_progress(self):
        for u in self:
            if u.quant_total > 0:
                progress = (u.virtual_quant_progress / u.quant_total) * 100
            else:
                progress = 0
            u.total_progress = int(progress)

    @api.depends("unit_progress", "task_id")
    def _actual_progress_percentage(self):
        for u in self:
            u.actual_progress_percentage = u.actual_progress / 100

    @api.depends("unit_progress", "task_id")
    def _total_progress_percentage(self):
        for u in self:
            u.total_progress_percentage = u.virtual_total_progress / 100

    @api.depends("unit_progress", "task_id")
    def _virtual_quant_progress(self):
        for u in self:
            # Ensure we have valid integers for search to avoid NewId errors
            project_id = u.project_id.id if isinstance(
                u.project_id.id, int) else False
            task_id = u.task_id.id if isinstance(u.task_id.id, int) else False

            if not project_id or not task_id:
                # If project or task are not yet saved (NewId), we assume no other saved advances exist
                u.virtual_quant_progress = u.unit_progress
                continue

            if not u.id or not isinstance(u.id, int):
                if not u._origin.id or not isinstance(u._origin.id, int):
                    progress = u.task_id.quant_progress + u.unit_progress
                else:
                    self_total = (
                        u.env["project.sub.update"]
                        .search(
                            [
                                ("project_id", "=", project_id),
                                ("task_id", "=", task_id),
                                ("id", "<", u._origin.id),
                            ]
                        )
                        .mapped("unit_progress")
                    )
                    progress = sum(self_total) + u.unit_progress
            else:
                self_total = (
                    u.env["project.sub.update"]
                    .search(
                        [
                            ("project_id", "=", project_id),
                            ("task_id", "=", task_id),
                            ("id", "<=", u.id),
                        ]
                    )
                    .mapped("unit_progress")
                )
                progress = sum(self_total)
            u.virtual_quant_progress = progress

    @api.depends("unit_progress", "quant_total", "virtual_quant_progress")
    def _virtual_total_progress(self):
        for u in self:
            if u.quant_total > 0:
                progress = (u.virtual_quant_progress / u.quant_total) * 100
            else:
                progress = 0
            u.virtual_total_progress = int(progress)

    @api.depends("unit_progress", "task_id", "quant_total", "virtual_quant_progress")
    def _missing_quant(self):
        for u in self:
            u.missing_quant = u.quant_total - u.virtual_quant_progress

    def _get_price_for_calculation(self):
        """Este metodo ayuda para obtener el valor unitario del producto en diferentes entornos"""
        self.ensure_one()
        # 1. Si la tarea tiene precio unitario (viene de SO), úsalo
        if self.task_id.price_unit:
            return self.task_id.price_unit
        # 2. Si no, usa el precio definido en la linea del pendiente relacionado al avance.
        if self.pending_service_line_id:
            return self.pending_service_line_id.price_unit
        # 3. Si no, usa el precio de lista del producto.
        if self.precio_unidad:
            return self.precio_unidad
        return 0.0

    @api.depends("unit_progress", "task_id", "precio_unidad")
    def _sale_current(self):
        for u in self:
            price = u._get_price_for_calculation()
            u.sale_current = u.unit_progress * price

        return {"type": "ir.actions.client", "tag": "soft_reload"}


    @api.depends("virtual_quant_progress", "task_id", "precio_unidad")
    def _sale_actual(self):
        for u in self:
            price = u._get_price_for_calculation()
            u.sale_actual = u.virtual_quant_progress * price

    # Campo A Modificar
    @api.depends("quant_total", "task_id", "precio_unidad")
    def _sale_total(self):
        for u in self:
            price = u._get_price_for_calculation()
            u.sale_total = u.quant_total * price

    @api.depends("sale_total", "sale_actual")
    def _sale_missing(self):
        for u in self:
            u.sale_missing = u.sale_total - u.sale_actual

    @api.depends("sale_current")
    def _sale_current_text(self):
        for u in self:
            sale = "%.2f" % u.sale_current
            value_len = sale.find(".")
            for i in range(value_len, 0, -1):
                sale = (
                    sale[:i] + "," + sale[i:]
                    if (value_len - i) % 3 == 0 and value_len != i
                    else sale
                )
            u.sale_current_text = "$" + sale

    @api.depends("sale_actual")
    def _sale_actual_text(self):
        for u in self:
            sale = "%.2f" % u.sale_actual
            value_len = sale.find(".")
            for i in range(value_len, 0, -1):
                sale = (
                    sale[:i] + "," + sale[i:]
                    if (value_len - i) % 3 == 0 and value_len != i
                    else sale
                )
            u.sale_actual_text = "$" + sale

    @api.depends("sale_total")
    def _sale_total_text(self):
        for u in self:
            sale = "% .2f" % u.sale_total
            value_len = sale.find(".")
            for i in range(value_len, 0, -1):
                sale = (
                    sale[:i] + "," + sale[i:]
                    if (value_len - i) % 3 == 0 and value_len != i
                    else sale
                )
            u.sale_total_text = "$" + sale

    @api.depends("sale_missing")
    def _sale_missing_text(self):
        for u in self:
            sale = "% .2f" % u.sale_missing
            value_len = sale.find(".")
            for i in range(value_len, 0, -1):
                sale = (
                    sale[:i] + "," + sale[i:]
                    if (value_len - i) % 3 == 0 and value_len != i
                    else sale
                )
            u.sale_missing_text = "$" + sale

    @api.onchange("task_id", "unit_progress")
    def _task_domain(self):
        tasks = [0 for c in range(len(self.update_id.sub_update_ids))]
        task_ids = ""
        i = 0
        for u in self.update_id.sub_update_ids:
            tasks[i] = u.task_id.id
            task_ids = task_ids + str(u.task_id.id) + " "
            i = i + 1
        domain = [
            ("project_id.id", "=", self.project_id.id),
            ("is_complete", "=", False),
            ("id", "not in", tasks),
        ]
        return {"domain": {"task_id": domain}}

    @api.depends("task_id")
    def _dom(self):
        tasks = [0 for c in range(len(self.update_id.sub_update_ids))]
        task_ids = ""
        i = 0
        for u in self.update_id.sub_update_ids:
            tasks[i] = u.task_id.id
            task_ids = task_ids + str(u.task_id.id) + " "
            i = i + 1
        domain = str(tasks)
        self.domain = domain

    # Este metodo de validación fue modificado.
    @api.constrains("quant_progress", "task_id")
    def _update_units(self):
        for u in self:
            if u.task_id and u.task_id.total_pieces > 0:
                other_sub_updates = self.env["project.sub.update"].search(
                    [
                        ("task_id", "=", u.task_id.id),
                        (
                            "id",
                            "!=",
                            u.id,
                        ),  # Excluye el registro actual para no doble-contar su valor
                    ]
                )
                sum_of_other_advances = sum(
                    other_sub_updates.mapped("unit_progress"))
                # Calcular el nuevo progreso total acumulado para la tarea
                new_total_task_progress = sum_of_other_advances + u.unit_progress
                # Realizar la validación
                if new_total_task_progress > u.task_id.total_pieces:
                    raise ValidationError(
                        "El progreso acumulado de la tarea sobrepasa el número de unidades pedidas."
                    )

    @api.constrains("unit_progress")
    def _check_units(self):
        for u in self:
            if u.task_id:
                if u.unit_progress < 0:
                    raise ValidationError("Cantidad inválida de unidades")

    """
    @api.constrains("item_ids")
    def _check_unique_items(self):
        for u in self:
            item_ids = u.item_ids.mapped("item_id")
            if len(item_ids) != len(set(item_ids)):
                raise ValidationError("No se pueden agregar ítems duplicados.")

    @api.constrains("sub_update_ids.task_id")
    def _check_unique_task_id(self):
        for u in self:
            task_ids = u.sub_update_ids.mapped("task_id")
            if len(task_ids) != len(set(task_ids)):
                raise ValidationError("No se pueden agregar tareas duplicadas.")
    """

    @api.model
    def update_sale_totals(self):
        sub_updates = self.search([])
        for sub_update in sub_updates:
            if sub_update.task_id:
                sub_update.sale_total = (
                    sub_update.task_id.total_pieces * sub_update.task_id.price_unit
                )
                sub_update.sale_current = (
                    sub_update.unit_progress * sub_update.task_id.price_unit
                )

    # Pruebas
    def action_unlink_from_update(self):
        """
        Desvincula un avance de su actualización y proyecto, regresándolo
        al estado 'Confirmado' para que pueda ser reasignado.
        Cuando se llama desde un botón en una línea, 'self' es solo ese registro.
        """
        self.ensure_one()  # Aseguramos que solo se ejecute para un registro a la vez

        # Verificación de seguridad
        if self.avances_state != "assigned":
            raise UserError(
                _("Solo se pueden desvincular avances que ya han sido asignados.")
            )

        original_update_name = self.update_id.name if self.update_id else "N/A"
        original_task_name = self.task_id.name if self.task_id else "N/A"

        _logger.info(f"Iniciando desvinculación para el avance: {self.name}")

        # Limpiar los campos de vinculación y regresar el estado
        self.write(
            {
                "update_id": False,
                "project_id": False,
                "task_id": False,
                "avances_state": "confirmed",
            }
        )

        # Registrar en el chatter para trazabilidad
        msg = _(
            "Avance desvinculado de la Actualización '%s' y Tarea '%s'. Ahora está disponible para ser reasignado."
        ) % (original_update_name, original_task_name)
        self.message_post(body=msg)

        _logger.info(f"Avance {self.name} desvinculado exitosamente.")

        # Simplemente retorna True, la vista se refrescará automáticamente
        return True

    # Método nuevo que permite asignar un producto si creamos el trabajo (Avance) desde la actualización del proyecto
    @api.onchange("task_id")
    def _onchange_task_project_update_set_product(self):
        """
        Rellena el producto del avance basado en la tarea seleccionada.
        Prioridad: 
        1. Línea de Venta (sale_line_id)
        2. Campo personalizado (producto_relacionado)
        3. Campo nativo de tarea si existiera (product_id)
        """
        for record in self:
            if not record.task_id:
                record.producto = False
                continue
            # 1. Intentar obtener de la línea de venta (Sale Order Line)
            if record.task_id.sale_line_id and record.task_id.sale_line_id.product_id:
                record.producto = record.task_id.sale_line_id.product_id

            # 2. Si no hay venta, intentar obtener del campo personalizado 'producto_relacionado' en la tarea
            elif hasattr(record.task_id, 'producto_relacionado') and record.task_id.producto_relacionado:
                record.producto = record.task_id.producto_relacionado

            # 3. Fallback: Intentar obtener de un campo nativo 'product_id' si la tarea lo tiene
            elif hasattr(record.task_id, 'product_id') and record.task_id.product_id:
                record.producto = record.task_id.product_id

            else:
                record.producto = False

    @api.onchange("update_id", "task_id")
    def _onchange_project_link(self):
        """Rellenamos el campo project_id basado en el avance general (update_id) o la tarea (task_id)

        Prioridad:
        1. Si existe task_id, usa su proyecto.
        2. Si no hay task_id pero si update_id, usa el proyecto del avance general.
        """

        if self.task_id:
            # Prioridad 1.
            self.project_id = self.task_id.project_id

        elif self.update_id and self.update_id.project_id:
            # Prioridad 2.
            self.project_id = self.update_id.project_id

        else:
            # Si no se tiene ninguno de los dos campos, se borra el proyecto actual
            self.project_id = False

    # Metódo que al duplicar no se pasen ciertos parametros si no que se actualicen
    def copy(self, default=None):
        """
        Anula el método copy para resetear campos clave y garantizar
        que el avance duplicado se trate como uno nuevo y en borrador.
        """
        if default is None:
            default = {}

        # 1. Forzar el estado a 'draft' (borrador)
        default["avances_state"] = "draft"

        # 2. Usar la fecha actual, no la fecha de la copia
        default["date"] = fields.Datetime.now()

        # 3. Limpiar referencias que deben ser únicas o no asignadas
        default["update_id"] = False
        default["asignar_avance"] = (
            False  # Si este es un campo booleano de estado/asignación
        )

        # Opcional: Si el nombre del avance tiene un contador, resetéalo o límpialo.
        # default['name'] = "Copia de Avance" # Puedes poner un nombre temporal

        return super(ProjectSubUpdate, self).copy(default)

    # Método para rellenar campos en base a la tarea
    @api.onchange("task_id")
    def _onchange_task_project(self):
        if self.task_id:
            self.ct = self.task_id.centro_trabajo
            self.planta = self.task_id.planta_trabajo
            self.responsible_id = self.task_id.supervisor_interno
            self.supervisorplanta = self.task_id.supervisor_cliente
        else:
            self.ct = False
            self.planta = False
            self.responsible_id = False
            self.supervisorplanta = False

    # -------------------------------------------------------------------------
    # CAMPOS LEGACY DEL MODELO ORIGINAL (PROJECT_SUB_UPDATE)
    # Se mantienen al final para evitar errores de campos faltantes en base de datos.
    # -------------------------------------------------------------------------
    
    analitica = fields.Many2one(string="Analitica", related='project_id.analytic_account_id')
    
    serv_assig = fields.Selection(
        string='Estatus de servicio',
        selection=[('assig', 'Con OS'), ('no_assig', 'Sin OS')],
        compute='_compute_serv_assig_computed',
        store=True,
    )

    @api.depends('sale_order_id.serv_assig')
    def _compute_serv_assig_computed(self):
        for record in self:
            record.serv_assig = record.sale_order_id.serv_assig
            
    # Mantenemos este campo para retrocompatibilidad, aunque B usa 'especialidad_trabajo'
    disciplina = fields.Many2one(string="Especialidad", related='task_id.disc', store=True)
    
    # Campo legacy de area (texto) por si había datos viejos, aunque B usa 'planta' y 'area_equipo'
    area = fields.Char(string='Area', store=True)

    # Campo legacy de licencias (texto) por si había datos viejos, B usa el Many2one 'licencia'
    numlic = fields.Char(string='#Bitacora/Lic.', store=True)


    # 1. Campo computado para contar (y controlar visibilidad)
    pending_service_count = fields.Integer(
        string="Contador Pendientes",
        compute="_compute_pending_service_count"
    )

    @api.depends("pending_service_id")
    def _compute_pending_service_count(self):
        for record in self:
            # Si hay un ID relacionado es 1, si no es 0
            record.pending_service_count = 1 if record.pending_service_id else 0

    # 2. Acción al presionar el botón
    def action_view_pending_service(self):
        self.ensure_one()
        if not self.pending_service_id:
            return

        return {
            "name": _("Servicio Pendiente Origen"),
            "type": "ir.actions.act_window",
            "res_model": "pending.service",
            "view_mode": "form",
            "res_id": self.pending_service_id.id,
            "target": "current",
        }
