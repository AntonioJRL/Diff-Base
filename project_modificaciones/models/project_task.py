from odoo import fields, models, api, _
from markupsafe import Markup
from odoo.exceptions import ValidationError
import logging

_logger = logging.getLogger(__name__)


class Task(models.Model):
    _inherit = 'project.task'

    """
    sale_line_id = fields.Many2one(
        'sale.order.line',
        string='Sales Order Item',
        copy=False,
        compute="_compute_sale_line_id",
        store=True,
        readonly=False,
        index='btree_not_null',
        domain="[('is_service', '=', True), ('is_expense', '=', False), ('state', 'in', ['sale', 'done']), ('order_partner_id', '=?', partner_id), '|', ('company_id', '=', False), ('company_id', '=', company_id)]",
        help="Sales order line linked to this task. Used to synchronize progress with the sale order line."
    )"""



    project_id = fields.Many2one(tracking=True)

    state = fields.Selection(
        selection_add=[
            ("01_in_progress", "In Progress"),
            ("1_done", "Done"),
            ("04_waiting_normal", "Waiting"),
        ],
        ondelete={
            "04_waiting_normal": "set default",
            "01_in_progress": "set default",
            "1_done": "set default",
        },
    )

    sale_order_id = fields.Many2one(
        string="Sales Order",
        related="sale_line_id.order_id",
        help="Sales order to which the project is linked.",
    )

    delivered = fields.Float(
        string="Entregado", related="sale_line_id.qty_delivered")
    price_unit = fields.Float(
        string="Precio", related="sale_line_id.price_unit")
    total_pieces = fields.Float(
        string="Unidades (decimal)", related="sale_line_id.product_uom_qty"
    )
    price_subtotal = fields.Float(string="Subtotal", compute="_subtotal")
    qty_invoiced = fields.Float(
        string="Facturado (unidades)", related="sale_line_id.qty_invoiced", store=True
    )
    disc = fields.Many2one(
        string="Especialidad", related="sale_line_id.product_id.categ_id", store=True
    )
    invoiced = fields.Float(
        string="Facturado", compute="_invoiced", store=True)

    # ========== CAMPOS DE ANALYTICS_EXTRA (mod_task.py) ==========
    # Moneda de compañía (para mostrar totales)
    currency_id = fields.Many2one(
        "res.currency",
        related="company_id.currency_id",
        string="Moneda",
        store=True,
        readonly=True,
    )
    # Gastos asociados a la tarea
    expense_ids = fields.One2many("hr.expense", "task_id", string="Gastos")
    # Órdenes de compra asociadas a la tarea (legado)
    purchase_ids = fields.One2many(
        "purchase.order", "task_order_id", string="Compras")
    # Líneas de compra asociadas a la tarea (fuente de verdad)
    purchase_line_ids = fields.One2many(
        "purchase.order.line", "task_id", string="Líneas de compra"
    )
    # Requisiciones asociadas a la tarea
    requisition_ids = fields.One2many(
        "employee.purchase.requisition", "task_id", string="Requisiciones"
    )

    # Contadores rápidos
    expense_count = fields.Integer(string="Cant. Gastos", compute="_compute_counts")
    purchase_count = fields.Integer(
        string="Cant. Compras", compute="_compute_counts")
    requisition_count = fields.Integer(
        string="Cant. Requisiciones", compute="_compute_counts")
    stock_move_count = fields.Integer(
        string="Cant. Movimientos de Almacén", compute="_compute_counts")

    # Total de gastos aprobados (aprobado/posteado)
    expense_total_approved = fields.Monetary(
        string="Total gastos (aprobados)",
        compute="_compute_totals",
        currency_field="currency_id",
        store=False,
    )
    # Total de compras confirmadas (sin impuestos)
    purchase_total_approved = fields.Monetary(
        string="Total compras (confirmadas)",
        compute="_compute_totals",
        currency_field="currency_id",
        store=False,
    )
    # ========== FIN CAMPOS DE ANALYTICS_EXTRA ==========

    # ========== CAMPOS DE INTEGRACIÓN ALMACÉN ==========
    stock_move_ids = fields.One2many(
        'stock.move',
        'task_id',
        string='Movimientos de Almacén',
        domain="[('state', '=', 'done'), ('picking_type_id.code', '=', 'outgoing')]"
    )

    stock_move_cost = fields.Monetary(
        string="Costo Mov. Almacén",
        compute='_compute_stock_move_cost',
        currency_field='currency_id'
    )

    @api.depends('stock_move_ids', 'stock_move_ids.state', 'purchase_line_ids', 'purchase_line_ids.state')
    def _compute_stock_move_cost(self):
        for task in self:
            cost = 0.0

            # 1. Obtener cantidades movidas por producto (Solo Salidas/Outgoing y Done)
            moves = task.stock_move_ids.filtered(lambda m: m.state == 'done')

            # Map Product -> Total Qty Moved
            moved_qty_per_product = {}
            for move in moves:
                qty = move.quantity
                moved_qty_per_product[move.product_id.id] = moved_qty_per_product.get(move.product_id.id, 0.0) + qty

            # 2. Obtener cantidades compradas por producto (Solo Confirmadas)
            purchased_qty_per_product = {}
            purchase_lines = self.env['purchase.order.line'].search([
                ('task_id', '=', task.id),
                ('order_id.state', 'in', ['purchase', 'done'])
            ])
            for line in purchase_lines:
                purchased_qty_per_product[line.product_id.id] = purchased_qty_per_product.get(line.product_id.id, 0.0) + line.product_qty

            # 3. Lógica de Cobro Neto
            for product_id, moved_qty in moved_qty_per_product.items():
                purchased_qty = purchased_qty_per_product.get(product_id, 0.0)
                chargeable_qty = max(0.0, moved_qty - purchased_qty)
                if chargeable_qty > 0:
                    product = task.env['product.product'].browse(product_id)
                    cost += chargeable_qty * product.standard_price

            task.stock_move_cost = cost

    # ---------------------------------------------------------------------
    # Sync task progress with linked Sale Order Line
    # ---------------------------------------------------------------------
    def write(self, vals):
        """Override write to propagate task progress to the linked sale order line.
        If the task has a `sale_line_id` (Many2one to `sale.order.line`), we update the
        `qty_delivered` on that line based on the task's `quant_progress` (units completed).
        This ensures that any change in task progress (or linking a line) is reflected
        immediately on the sales order.
        """
        res = super(Task, self).write(vals)
        return res

    def action_link_sale_line(self):
        """Placeholder method for the "Vincular línea" button.
        Currently does nothing but returns True to avoid errors.
        You can replace it with a proper wizard later.
        """
        self.ensure_one()
        return True    # ========== FIN CAMPOS DE INTEGRACIÓN ALMACÉN ==========

    # Campos originales de control_obra
    # NOTA: Se cambia 'creacion.avances' por 'project.sub.update' para mantener la integridad con el paso anterior
    sub_update_ids = fields.One2many(
        "project.sub.update",
        "task_id",
        domain="[('project_id', '=', project_id), ('task_id.id', '=', id)]",
        string="Actualización de tareas",
    )
    sub_update = fields.Many2one(
        "project.sub.update", compute="_last_update", store=True)
    last_update = fields.Many2one(
        "project.update", related="sub_update.update_id", string="Última actualización"
    )
    sub_d_update = fields.Many2one(
        "project.sub.update",
        compute="_d_update",
        string="Última actualización de tarea",
        store=True,
    )
    last_d_update = fields.Many2one(
        "project.update",
        related="sub_d_update.update_id",
        string="Última actualización modificada",
    )
    last_update_date = fields.Datetime(
        related="last_d_update.write_date", string="Modificado por ult. vez"
    )

    quant_progress = fields.Float(
        string="Piezas/Servicio", compute="_units", store=True
    )
    progress = fields.Integer(
        compute="_progress", string="Progreso", store=True)
    progress_percentage = fields.Float(
        compute="_progress_percentage", string="Progreso porcentual", store=True
    )

    is_complete = fields.Boolean(
        string="Complete", compute="_is_complete", default=False, store=True
    )

    centro_trabajo = fields.Many2one(
        "control.centro.trabajo",
        string="Centro Trabajo",
        help="Centro de trabajo en donde se realizara el servicio.",
        tracking=True,
    )

    planta_trabajo = fields.Many2one(
        "control.planta",
        string="Planta",
        help="Planta de trabajo en donde se realizara el servicio.",
        tracking=True,
    )

    supervisor_interno = fields.Many2one(
        "hr.employee",
        string="Supervisor Interno",
        domain="[('supervisa', '=', True)]",
        help="Supervisor Del Trabajo Interno (AYASA)",
        tracking=True,
    )

    supervisor_cliente = fields.Many2one(
        "supervisor.area",
        string="Supervisor Cliente",
        help="Supervisor por parte del cliente al cual se le proporcionara el servicio.",
        tracking=True,
    )

    partida_relacionada = fields.Char(
        string="Partida",
        help="Partida relacionada con la tarea.",
        related="sale_line_id.partida",
        tracking=True,
    )

    # Campo para indicar que la tarea fue creada desde el modelo control de obra.
    is_control_obra = fields.Boolean(
        string="Tarea Control Obra",
        default=False,
        compute="_compute_is_control_obra",
        help="Indica que esta tarea es un servicio a realizar, relacionada a un proyecto de obra dentro del modulo Control Obra.",
        store=True,
    )

    # Campo auxiliar invisible para controlar el filtro
    project_domain_string = fields.Char(
        compute="_compute_project_domain_string",
        readonly=True,
        store=False
    )

    @api.depends('is_control_obra', 'company_id')
    def _compute_project_domain_string(self):
        for task in self:
            # 1. Lógica base (Activos + Compañía)
            domain = [('active', '=', True)]
            if task.company_id:
                domain += ['|', ('company_id', '=', False),
                           ('company_id', '=', task.company_id.id)]
            else:
                domain += ['|', ('company_id', '=', False),
                           ('company_id', '!=', False)]

            # 2. Tu lógica: Si es Control de Obra, filtramos
            if task.is_control_obra:
                domain.append(('is_proyecto_obra', '=', True))

            # 3. Convertimos la lista a string para que el XML la entienda
            task.project_domain_string = str(domain)

    # CAMPOS Y METODOS PARA EL FLUJO DE APROBACIÓN
    approval_state = fields.Selection(
        [
            ("draft", "Borrador"),
            ("to_approve", "En Aprobación"),
            ("approved", "Aprobado"),
            ("rejected", "Rechazada"),
        ],
        string="Estado de Aprobación",
        default="draft",
        copy=False,
    )

    approver_id = fields.Many2one(
        "res.users",
        string="Aprobador (Superintendente)",
        copy=False,
        tracking=True,
        readonly=True,
    )

    approval_activity_id = fields.Many2one(
        "mail.activity",
        string="Actividad de Aprobación",
        copy=False,
    )

    can_user_approve = fields.Boolean(
        string="Usuario actual puede aprobar",
        compute="_compute_can_user_approve",
    )

    # Dominios eliminados para evitar problemas con IDs inválidos

    piezas_pendientes = fields.Float(
        string="Piezas Pendientes",
        tracking=True,
    )

    producto_relacionado = fields.Many2one(
        'product.product',
        string="Producto Relacionado A la Tarea",
    )

    # -------------------------------------------------------------------------
    # MÉTODOS TRAIDOS TAL CUAL DE INHERIT_PROJECT_TASK.PY
    # -------------------------------------------------------------------------

    @api.depends("sale_line_id.qty_invoiced")
    def _invoiced(self):
        for u in self:
            u.invoiced = u.qty_invoiced * u.price_unit

    @api.model
    def _d_update(self):
        for u in self:
            # Cambio de modelo para consistencia
            u.sub_d_update = u.env["project.sub.update"].search(
                [("project_id.id", "=", u.project_id.id), ("task_id.id", "=", u.id)],
                limit=1,
            )

    @api.model
    def _check_to_recompute(self):
        return [id]

    @api.depends("sub_update_ids")
    def _last_update(self):
        for u in self:
            if not u.id:
                continue
            # Cambio de modelo para consistencia
            u.sub_update = u.env["project.sub.update"].search(
                [("project_id.id", "=", u.project_id.id), ("task_id.id", "=", u.id)],
                order="id desc",
                limit=1,
            )

    @api.depends(
        "sub_update_ids",
        "sub_update_ids.unit_progress",
        "sub_update_ids.avances_state",
        "project_id.update_ids"
    )
    def _units(self):
        for u in self:
            # Verifica si el registro está siendo creado (i.e., no tiene ID aún)
            if not u.id:
                continue

            # Sincronización Maestra: Sumamos todos los avances vinculados (sin filtrar por estado)
            u.quant_progress = sum(u.sub_update_ids.mapped("unit_progress"))

            # Empujar el cambio directamente a la línea de venta para asegurar consistencia
            if u.sale_line_id:
                u.sale_line_id.qty_delivered = u.quant_progress



    @api.depends(
        "sub_update_ids",
        "sub_update_ids.unit_progress",
        "project_id.update_ids",
        "quant_progress",  # Añadido: Dependencia sobre la cantidad avanzada
        "total_pieces",  # Añadido: Dependencia sobre el total esperado
    )
    def _progress(self):
        for u in self:
            progress = 0
            # Verificar que 'total_pieces' exista y sea mayor que cero
            if u.total_pieces and u.total_pieces > 0:
                # Calcular el porcentaje. Odoo maneja la división a float automáticamente.
                progress = (u.quant_progress / u.total_pieces) * 100

            # Asignación corregida:
            u.progress = min(100, int(progress))

    @api.depends(
        "sub_update_ids", "sub_update_ids.unit_progress", "project_id.update_ids"
    )
    def _progress_percentage(self):
        for u in self:
            # Verifica si el registro está siendo creado (i.e., no tiene ID aún)
            if not u.id:
                continue
            u.progress_percentage = u.progress / 100

    @api.depends(
        "sub_update_ids", "sub_update_ids.unit_progress", "project_id.update_ids"
    )
    def _subtotal(self):
        for u in self:
            if not u.id:
                continue
            subtotal = (
                u.env["sale.order.line"]
                .search([("id", "=", u.sale_line_id.id)])
                .mapped("price_subtotal")
            )
            if subtotal:
                u.price_subtotal = float(subtotal[0])
            else:
                u.price_subtotal = 0.0

    @api.depends("sub_update_ids", "sub_update_ids.unit_progress")
    def _is_complete(self):
        self._update_completion_state()

    def _update_completion_state(self):
        for task in self:
            # Solo aplicar validación estricta para tareas de CONTROL DE OBRA
            if not task.is_control_obra:
                continue

            # Respetar flujo de aprobación
            if task.approval_state in ["draft", "to_approve", "rejected"]:
                # Respetar el estado de aprobación - no cambiar stage_id
                continue

            if task.total_pieces == 0:
                continue

            if task.quant_progress == task.total_pieces:
                task.is_complete = True
                task.state = "1_done"
                task.stage_id = self.env.ref(
                    "project_modificaciones.project_task_type_obra_done", raise_if_not_found=False
                )
            elif task.quant_progress > 0:
                task.is_complete = False
                if task.approval_state == "approved":  # Solo si está aprobada
                    # Solo mover a "En Progreso" si estaba en "Pendientes" o "Listo" (re-abierta)
                    # Si el usuario la movió manualmente a otra etapa (ej. "Pausada"), no la forzamos.
                    stage_pending = self.env.ref(
                        "project_modificaciones.project_task_type_obra_pending",
                        raise_if_not_found=False,
                    )
                    stage_done = self.env.ref(
                        "project_modificaciones.project_task_type_obra_done",
                        raise_if_not_found=False,
                    )

                    if (
                        task.stage_id in [stage_pending, stage_done]
                        or not task.stage_id
                    ):
                        task.stage_id = self.env.ref(
                            "project_modificaciones.project_task_type_obra_progress",
                            raise_if_not_found=False,
                        )
                        task.state = "01_in_progress"
            else:
                task.is_complete = False
                if task.approval_state == "approved":  # Solo si está aprobada
                    # Si regresa a 0, mover a pendientes solo si estaba en progreso o listo
                    stage_progress = self.env.ref(
                        "project_modificaciones.project_task_type_obra_progress",
                        raise_if_not_found=False,
                    )
                    stage_done = self.env.ref(
                        "project_modificaciones.project_task_type_obra_done",
                        raise_if_not_found=False,
                    )

                    if task.stage_id in [stage_progress, stage_done]:
                        task.stage_id = self.env.ref(
                            "project_modificaciones.project_task_type_obra_pending",
                            raise_if_not_found=False,
                        )
                        task.state = (
                            "04_waiting_normal"  # Solo control obra usa este estado
                        )

    @api.model
    def update_task_status(self):
        tasks = self.env["project.task"].search(
            [("sale_order_id", "!=", False)])
        tasks._update_completion_state()

    """ REVISAR
    @api.constrains('sub_update_ids')
    def _check_unique_items(self):
        for record in self:
            item_ids = record.item_ids.mapped('update_id')
            if len(item_ids) != len(set(item_ids)):
                raise ValidationError('No se pueden agregar ítems duplicados.')
    """

    # -------------------------------------------------------------------------
    # MÉTODO AUXILIAR: Actualiza el JSON de distribución analítica
    # -------------------------------------------------------------------------
    def _get_updated_analytic_distribution(self, distribution, new_account_id, old_account_id=False):
        """
        Recibe la distribución actual (Dict) y reemplaza la cuenta analítica vieja por la nueva.
        Mantiene el porcentaje original.
        """
        if not new_account_id:
            return distribution or {}

        # Asegurar que distribution sea un diccionario modificable
        new_dist = dict(distribution or {})

        # En Odoo 17 las claves del JSON analítico son Strings
        str_new_id = str(new_account_id)
        str_old_id = str(old_account_id) if old_account_id else False

        # 1. Si existía la cuenta vieja, tomamos su porcentaje y la borramos
        percentage = 100.0
        if str_old_id and str_old_id in new_dist:
            percentage = new_dist.pop(str_old_id)

        # 2. Asignamos la nueva cuenta
        # Si ya existe la nueva (caso raro), sumamos el porcentaje para no duplicar claves
        new_dist[str_new_id] = new_dist.get(str_new_id, 0.0) + percentage

        return new_dist

    # -------------------------------------------------------------------------
    # MÉTODO WRITE: Lógica principal de cambio de proyecto
    # -------------------------------------------------------------------------
    def write(self, vals):
        # 1. Capturar estado previo
        old_state = {
            task.id: {
                'project_id': task.project_id,
                'analytic_account_id': task.analytic_account_id or task.project_id.analytic_account_id,
                'sale_order_id': task.sale_order_id
            } for task in self
        }

        # 2. Ejecutar write estándar
        res = super(Task, self).write(vals)

        # 3. Detectar si el cambio incluyó 'project_id'
        if "project_id" in vals:
            self._compute_is_control_obra()
            new_project_id = vals.get('project_id')
            new_project = self.env['project.project'].browse(
                new_project_id) if new_project_id else self.env['project.project']

            for task in self:
                prev_data = old_state.get(task.id)
                old_project = prev_data['project_id']
                old_analytic = prev_data['analytic_account_id']
                sale_order = prev_data['sale_order_id']

                # Solo procesamos si hay un cambio real de proyecto
                if old_project and new_project and old_project != new_project:

                    # === A) ACTUALIZAR CUENTA ANALÍTICA TAREA ===
                    new_analytic = new_project.analytic_account_id
                    if new_analytic and task.analytic_account_id != new_analytic:
                        task.write({'analytic_account_id': new_analytic.id})

                    # === B) MOVER AVANCES CON LOGICA DE PROJECT.UPDATE ===
                    if task.sub_update_ids:
                        # 0. Capturar los updates de origen para verificar limpieza posterior
                        source_updates = task.sub_update_ids.mapped(
                            'update_id')

                        # 1. Agrupar avances por fecha para procesar en lote
                        avances_by_date = {}
                        for avance in task.sub_update_ids:
                            # Usamos la fecha del avance o fallback a hoy
                            avance_date = avance.date or fields.Date.today()
                            if avance_date not in avances_by_date:
                                avances_by_date[avance_date] = self.env['project.sub.update']
                            avances_by_date[avance_date] |= avance

                        # 2. Iterar por cada grupo de fecha
                        for p_date, avances in avances_by_date.items():
                            # Buscar una actualización existente en el NUEVO PROYECTO con la misma fecha
                            # Asumimos que la comparación es por fecha (date)
                            existing_update = self.env['project.update'].search([
                                ('project_id', '=', new_project.id),
                                ('date', '=', p_date)
                            ], limit=1)

                            if not existing_update:
                                # Si no existe, la CREAMOS
                                # Intentamos preservar el nombre de la actualización original si es posible
                                original_update_name = _(
                                    'Actualización Transferida')
                                # Tomamos el nombre del update del primer avance si existe
                                if avances and (valid_update_id := avances[0].update_id):
                                    original_update_name = valid_update_id.name

                                try:
                                    existing_update = self.env['project.update'].create({
                                        'project_id': new_project.id,
                                        'name': original_update_name,
                                        'date': p_date,
                                        'user_id': self.env.user.id,
                                        # Status por defecto (ej. on_track) suele ser requerido o tener default
                                        'status': 'on_track'
                                    })
                                    _logger.info(
                                        "Creado nuevo Project Update %s en proyecto %s para fecha %s",
                                        existing_update.name, new_project.name, p_date
                                    )
                                except Exception as e:
                                    _logger.warning(
                                        "No se pudo crear project.update automático: %s. Los avances se moverán sin update_id.", str(e))
                                    existing_update = False

                            # 3. Mover los avances y asignarlos al update encontrado/creado
                            vals_avance = {'project_id': new_project.id}
                            if existing_update:
                                vals_avance['update_id'] = existing_update.id
                            else:
                                # CRÍTICO: Si no se pudo crear el update nuevo, DESVINCULAR del viejo
                                # para evitar que apunten a un update de otro proyecto.
                                vals_avance['update_id'] = False

                            avances.write(vals_avance)

                        # 4. Limpieza: Eliminar updates de origen que quedaron vacíos
                        for old_update in source_updates:
                            # Contamos si quedan avances vinculados
                            # Nota: update_id es el campo Many2one en project.sub.update hacia project.update
                            # Asumimos que existe un One2many en project.update o buscamos inversamente
                            # Normalmente no hay One2many por defecto de sub.update en project.update salvo personalizacion
                            # Buscamos count directo
                            count_remaining = self.env['project.sub.update'].search_count(
                                [('update_id', '=', old_update.id)])
                            if count_remaining == 0:
                                _logger.info(
                                    "Eliminando Project Update vacío tras mudanza: %s (ID: %s)", old_update.name, old_update.id)
                                old_update.sudo().unlink()

                    # === C) MOVER SUBTAREAS ===
                    child_tasks = self.search(
                        [('parent_id', '=', task.id), ('project_id', '=', old_project.id)])
                    if child_tasks:
                        child_tasks.write({'project_id': new_project.id})

                    # === D) ACTUALIZAR GASTOS (HR.EXPENSE) ===
                    # Verificamos si existe el campo y filtramos
                    if 'expense_ids' in self.env['project.task']._fields:
                        # 1. Separamos gastos: "Libres" vs "Bloqueados" (En reporte aprobado/posteado/pagado)
                        all_expenses = task.expense_ids.filtered(
                            lambda e: e.state not in ['done', 'refused'])

                        expenses_free = all_expenses.filtered(
                            lambda e: not e.sheet_id or e.sheet_id.state in ['draft', 'submit'])
                        expenses_locked = all_expenses - expenses_free

                        # CASO 1: Gastos Libres -> Usamos write estandard (con sudo)
                        if expenses_free:
                            vals_expense = {'project_id': new_project.id}
                            if new_analytic:
                                # Hay que iterar porque cada uno tiene su propia distribución
                                for expense in expenses_free:
                                    new_dist = self._get_updated_analytic_distribution(
                                        expense.analytic_distribution, new_analytic.id, old_analytic.id
                                    )
                                    expense.sudo().write({
                                        'project_id': new_project.id,
                                        'analytic_distribution': new_dist
                                    })
                            else:
                                expenses_free.sudo().write(vals_expense)

                        # CASO 2: Gastos Bloqueados -> Actualizamos Proyecto Y Analítica vía SQL
                        # Validamos primero si hay nueva analítica
                        if expenses_locked:
                            _logger.info(
                                "Forzando actualización de proyecto/analítica en %s gastos bloqueados", len(expenses_locked))

                            for exp in expenses_locked:
                                updates = "project_id = %s" % new_project.id

                                # Si hay nueva analítica, calculamos el JSON y lo inyectamos
                                if new_analytic:
                                    import json
                                    new_dist = self._get_updated_analytic_distribution(
                                        exp.analytic_distribution, new_analytic.id, old_analytic.id
                                    )
                                    # Convertimos dict a JSON string para SQL
                                    json_dist = json.dumps(new_dist)
                                    updates += ", analytic_distribution = '%s'" % json_dist

                                # Ejecución directa
                                self.env.cr.execute(f"""
                                    UPDATE hr_expense
                                    SET {updates}
                                    WHERE id = %s
                                """, (exp.id,))

                            # Invalidar caché
                            expenses_locked.invalidate_recordset(
                                ['project_id', 'analytic_distribution'])

                    # === E) ACTUALIZAR COMPRAS (PURCHASE.ORDER) ===
                    # 1. Buscar Órdenes de Compra vinculadas a esta tarea como cabecera
                    purchase_orders = self.env['purchase.order'].search([
                        ('task_order_id', '=', task.id),
                        ('state', '!=', 'cancel')
                    ])

                    if purchase_orders:
                        # Actualizar proyecto en cabecera
                        purchase_orders.write({'project_id': new_project.id})

                        # A) LÍNEAS DE COMPRA (Actualizar Proyecto y Analítica)
                        lines_to_update = purchase_orders.mapped('order_line').filtered(
                            lambda l: l.state != 'cancel'
                        )
                        if lines_to_update:
                            vals_line = {
                                'project_id': new_project.id,
                                # Asegurar que NO se pierda la tarea (Corrección solicitada)
                                'task_id': task.id
                            }
                            # Si hay analítica, forzamos actualización en TODAS las líneas de la orden
                            if new_analytic:
                                # Iteramos por si tienen distribuciones mixtas, aunque es pesado es seguro
                                for line in lines_to_update:
                                    _logger.info("DEBUG ANALYTIC: Old=%s, New=%s, Dist=%s",
                                                 old_analytic.id, new_analytic.id, line.analytic_distribution)
                                    dist = self._get_updated_analytic_distribution(
                                        line.analytic_distribution, new_analytic.id, old_analytic.id)
                                    _logger.info(
                                        "DEBUG ANALYTIC RESULT: %s", dist)

                                    line_vals = vals_line.copy()
                                    line_vals['analytic_distribution'] = dist
                                    line.write(line_vals)
                            else:
                                lines_to_update.write(vals_line)

                        # B) ALBARANES (STOCK PICKING)
                        pickings = purchase_orders.mapped('picking_ids').filtered(
                            lambda p: p.state != 'cancel'
                        )
                        if pickings:
                            # Propagar TAREA también
                            pickings.write({
                                'project_id': new_project.id,
                                'task_id': task.id  # Corrección solicitada
                            })

                            # C) MOVIMIENTOS DE STOCK (STOCK MOVE)
                            moves = pickings.mapped('move_ids').filtered(
                                lambda m: m.state != 'cancel'
                            )
                            if moves:
                                moves.write({
                                    'project_id': new_project.id,
                                    'task_id': task.id
                                })

                    # 2. Actualizar Distribución Analítica en líneas sueltas (linked directly)
                    # (Esto cubre líneas que NO son de las órdenes de arriba, si hubiera)
                    if 'purchase_line_ids' in self.env['project.task']._fields:
                        # Buscamos líneas que NO fueron actualizadas arriba
                        processed_orders = purchase_orders.ids if purchase_orders else []
                        purchase_lines = task.purchase_line_ids.filtered(
                            lambda l: l.state not in ['cancel', 'done'] and l.order_id.id not in processed_orders)

                        if purchase_lines:
                            _logger.info("Actualizando %s líneas de compra sueltas para tarea %s", len(
                                purchase_lines), task.name)
                            vals_line_loose = {'project_id': new_project.id}

                            if new_analytic:
                                for line in purchase_lines:
                                    _logger.info("DEBUG ANALYTIC LOOSE: Old=%s, New=%s, Dist=%s",
                                                 old_analytic.id if old_analytic else False, new_analytic.id, line.analytic_distribution)
                                    new_dist_line = self._get_updated_analytic_distribution(
                                        line.analytic_distribution, new_analytic.id, old_analytic.id
                                    )
                                    _logger.info(
                                        "DEBUG ANALYTIC LOOSE RESULT: %s", new_dist_line)

                                    curr_vals = vals_line_loose.copy()
                                    curr_vals['analytic_distribution'] = new_dist_line
                                    line.write(curr_vals)
                            else:
                                purchase_lines.write(vals_line_loose)

                    # === F) ACTUALIZAR TIMESHEETS ===
                    if 'timesheet_ids' in self.env['project.task']._fields:
                        timesheets_model = self.env['account.analytic.line']
                        if 'timesheet_invoice_id' in timesheets_model._fields:
                            timesheets = task.timesheet_ids.filtered(
                                lambda t: not t.timesheet_invoice_id)
                        else:
                            timesheets = task.timesheet_ids

                        if timesheets:
                            ts_vals = {'project_id': new_project.id}
                            if task.sale_line_id:
                                ts_vals['so_line'] = task.sale_line_id.id
                            timesheets.write(ts_vals)

                    # === G) ACTUALIZAR MOVIMIENTOS DE ALMACÉN (STOCK.MOVE) ===
                    # El usuario solicitó explícitamente que los movimientos de almacén también se muevan.
                    if 'stock_move_ids' in self.env['project.task']._fields:
                        moves_to_update = task.stock_move_ids.filtered(
                            lambda m: m.state not in ['cancel', 'done']
                        )
                        # También podríamos incluir los 'done' si se requiere historial,
                        # pero comúnmente solo se mueven los abiertos.
                        # Si el cliente quiere TODOS (historial incluido), quitamos el filtro de state.
                        # Asumiendo "que se muevan" implica reasignación total:
                        moves_to_update = task.stock_move_ids
                        if moves_to_update:
                            moves_to_update.write(
                                {'project_id': new_project.id})

                    # === H) RECALCULAR AVANCE (CRÍTICO - FUERZA BRUTA 2.0) ===
                    # 1. Limpieza agresiva de cache
                    # Aseguar que el search() vea los cambios de proyecto
                    self.env['project.sub.update'].invalidate_model()
                    task.invalidate_recordset()  # Invalidar TODO en la tarea

                    # 2. Recalcular Unidades (Numerador)
                    task._units()
                    current_quant = task.quant_progress

                    # 3. Obtener Total (Denominador) Fresco
                    total_qty = 0.0
                    if task.sale_line_id:
                        # Leer directamente de la BD saltando caché posible
                        linea = self.env['sale.order.line'].browse(
                            task.sale_line_id.id)
                        total_qty = linea.product_uom_qty

                    # 4. Calcular Porcentajes manualmente
                    new_progress = 0
                    new_pct = 0.0

                    if total_qty > 0 and current_quant > 0:
                        new_progress_float = (current_quant / total_qty) * 100
                        new_progress = min(100, int(new_progress_float))
                        new_pct = new_progress_float / 100.0  # Usamos float preciso

                    # 5. Escribir explícitamente los valores con SUDO
                    _logger.info("FORCE UPDATE FINAL: Task %s | Quant: %s | Total: %s | Calc Progress: %s",
                                 task.name, current_quant, total_qty, new_progress)

                    task.sudo().write({
                        'progress': new_progress,
                        'progress_percentage': new_pct
                    })

                    pass

                    # === I) ACTUALIZAR REQUISICIONES (EMPLOYEE.PURCHASE.REQUISITION) ===
                    # Si existen requisiciones vinculadas, las movemos al nuevo proyecto.
                    if 'requisition_ids' in self.env['project.task']._fields:
                        requisitions_to_move = task.requisition_ids.filtered(
                            # O mover todas si se prefiere historial completo:
                            lambda r: r.state not in ['cancel']
                        )

                        for req in requisitions_to_move:
                            # 1. Cabecera (Proyecto + Analítica)
                            req_vals = {}
                            if 'project_id' in self.env['employee.purchase.requisition']._fields:
                                req_vals['project_id'] = new_project.id

                            # Si tiene campo de distribución (algunos módulos lo tienen en cabecera)
                            if 'analytic_distribution' in self.env['employee.purchase.requisition']._fields and new_analytic:
                                # Hay que ver si se puede leer el actual, asumimos que sí
                                curr_dist = req.analytic_distribution if hasattr(
                                    req, 'analytic_distribution') else {}
                                req_vals['analytic_distribution'] = self._get_updated_analytic_distribution(
                                    curr_dist, new_analytic.id, old_analytic.id
                                )

                            if req_vals:
                                req.write(req_vals)

                            # 2. Líneas (requisition.order)
                            if hasattr(req, 'requisition_order_ids') and req.requisition_order_ids:
                                # Iteramos líneas para actualizar Proyecto + Analítica
                                lines_req = req.requisition_order_ids
                                if 'project_id' in self.env['requisition.order']._fields:
                                    lines_req.write(
                                        {'project_id': new_project.id})

                                # Actualizar distribución en líneas
                                if 'analytic_distribution' in self.env['requisition.order']._fields and new_analytic:
                                    for l_req in lines_req:
                                        dist_req = self._get_updated_analytic_distribution(
                                            l_req.analytic_distribution, new_analytic.id, old_analytic.id)
                                        l_req.write(
                                            {'analytic_distribution': dist_req})

                    # === J) ACTUALIZAR HOJAS DE HORAS / REGULARIZACIONES (ATTENDANCE.REGULARIZATION) ===
                    # Buscamos registros vinculados a esta tarea.
                    # Asumimos que el modelo es 'attendance.regularization' y tiene 'task_id'.
                    attendance_model = self.env.get(
                        'attendance.regularization')
                    if attendance_model is not None and 'task_id' in attendance_model._fields:
                        attendance_recs = attendance_model.search([
                            ('task_id', '=', task.id)
                        ])
                        if attendance_recs and 'project_id' in attendance_model._fields:
                            attendance_recs.write(
                                {'project_id': new_project.id})

                    # === L) ACTUALIZAR COMPENSACIONES (COMPENSATION.REQUEST / LINE) ===
                    # Buscamos de forma segura el modelo
                    comp_line_model = self.env.get('compensation.line')
                    if comp_line_model is not None and 'task_id' in comp_line_model._fields:
                        # 1. Buscar líneas de compensación vinculadas a esta tarea
                        comp_lines = comp_line_model.search(
                            [('task_id', '=', task.id)])

                        if comp_lines:
                            # Actualizar proyecto en las líneas
                            if 'project_id' in comp_line_model._fields:
                                comp_lines.write(
                                    {'project_id': new_project.id})

                            # 2. Verificar cabeceras (request) para actualizar 'service' si unique_project es True
                            # Obtenemos las cabeceras únicas afectadas
                            comp_requests = comp_lines.mapped(
                                'compensation_id')
                            for req in comp_requests:
                                # Verificamos existencia de campos en cabecera
                                if 'unique_project' in req._fields and 'service' in req._fields:
                                    if req.unique_project:
                                        # Si el proyecto único está activo, actualizamos la cabecera también
                                        # Nota: Esto asume que TODAS las líneas pertenecían al mismo proyecto anterior.
                                        if req.service != new_project:
                                            req.write(
                                                {'service': new_project.id})

                    # === K) ACTUALIZAR SALE ORDER (Lógica "Última Tarea") ===
                    if sale_order and sale_order.project_id == old_project:
                        # Buscamos si quedan tareas (ACTIVAS o ARCHIVADAS) de esta venta en el viejo proyecto
                        # Usamos active_test=False para encontrar tareas archivadas que podrían estar causando
                        # que la venta siga vinculada al proyecto viejo (y por eso salen duplicados en el smart button).
                        tasks_remaining_all = self.with_context(active_test=False).search_count([
                            ('project_id', '=', old_project.id),
                            ('sale_order_id', '=', sale_order.id)
                        ])

                        if tasks_remaining_all == 0:
                            _logger.info(
                                "Moviendo Orden de Venta %s al proyecto %s (Limpieza completa)", sale_order.name, new_project.name)
                            sale_order.sudo().write(
                                {'project_id': new_project.id})
                        else:
                            # Si quedan tareas (quizás archivadas), las movemos también para limpiar la casa?
                            # O solo movemos la cabecera forzadamente?
                            # Estrategia: Si solo quedan archivadas, movemos la cabecera y movemos las archivadas también.

                            active_tasks = self.search_count([
                                ('project_id', '=', old_project.id),
                                ('sale_order_id', '=', sale_order.id)
                            ])

                            if active_tasks == 0 and tasks_remaining_all > 0:
                                # Significa que solo quedan "Fantasmas" (archivadas).
                                # Las movemos todas al nuevo proyecto para sanear.
                                archived_tasks = self.with_context(active_test=False).search([
                                    ('project_id', '=', old_project.id),
                                    ('sale_order_id', '=', sale_order.id)
                                ])
                                _logger.info(
                                    "Moviendo %s tareas archivadas restantes de la SO %s al nuevo proyecto",
                                    len(archived_tasks), sale_order.name
                                )
                                archived_tasks.write(
                                    {'project_id': new_project.id})

                                # Y finalmente movemos la orden
                                sale_order.sudo().write(
                                    {'project_id': new_project.id})

        return res
        
    """
    def _clean_invalid_references(self):
        for task in self:
            # Solo procesar tareas que tengan ID (ya guardadas)
            if not task.id:
                continue

            for field_name, field in self._fields.items():
                if field.type == "many2one" and field.store:
                    try:
                        value = getattr(task, field_name)

                        # Fix for KeyError: 30 - forcefully clear stage_id 30
                        # This ID seems to exist but causes read errors (possibly access rules or corruption)
                        if value and value.id == 30:
                            _logger.warning(
                                "🧹 FORCE CLEANING problematic reference ID 30 in tarea %s (ID: %s): campo %s",
                                task.name,
                                task.id,
                                field_name,
                            )
                            task.with_context(skip_invalid_ref_check=True).write(
                                {field_name: False}
                            )
                            continue

                        # Verificar si el valor existe pero el registro relacionado no
                        if value and not value.exists():
                            _logger.warning(
                                "🧹 Limpiando referencia inválida en tarea %s (ID: %s): campo %s = %s",
                                task.name,
                                task.id,
                                field_name,
                                value.id if value else "False",
                            )
                            # Escribir solo si realmente cambiamos algo
                            task.with_context(skip_invalid_ref_check=True).write(
                                {field_name: False}
                            )
                    except Exception as e:
                        # Silenciar errores de acceso, pero loguearlos para debugging
                        _logger.debug(
                            "Error verificando campo %s en tarea %s: %s",
                            field_name,
                            task.id,
                            str(e),
                        )
    """

    def action_view_avances(self):
        return {
            "name": _("Avances de la Tarea"),
            "type": "ir.actions.act_window",
            "res_model": "project.sub.update",  # Referencia actualizada
            "view_mode": "list,form",
            "domain": [("task_id", "=", self.id)],
            "context": {
                "default_task_id": self.id,
                "default_project_id": self.project_id.id,
                "create": True,
                "delete": False,
            },
            "flags": {"creatable": True},
            "target": "current",
        }

    # ========== MÉTODOS DE ANALYTICS_EXTRA (mod_task.py) ==========
    def _compute_counts(self):
        for task in self:
            task.expense_count = len(task.expense_ids)
            # Contar las órdenes de compra únicas a través de las líneas
            task.purchase_count = len(
                task.purchase_line_ids.mapped("order_id"))
            task.requisition_count = len(task.requisition_ids)
            task.stock_move_count = len(task.stock_move_ids)

    def _compute_totals(self):
        # Suma totales aprobados de gastos y sin impuestos de compras confirmadas
        for task in self:
            # Optimización: Usar los campos One2many en vez de consultas search para evitar consultas masivas en BD.

            # Sumar gastos aprobados (post o done).
            approved_expenses = task.expense_ids.filtered(
                lambda e: e.sheet_id.state in ["post", "done"]
            )
            task.expense_total_approved = sum(
                approved_expenses.mapped("total_amount"))

            # Sumar compras confirmadas (purchase o done).
            confirmed_lines = task.purchase_line_ids.filtered(
                lambda l: l.order_id.state in ["purchase", "done"]
            )
            task.purchase_total_approved = sum(
                confirmed_lines.mapped("price_subtotal"))

    def action_view_expenses(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Gastos",
            "res_model": "hr.expense",
            "view_mode": "list,kanban,form",
            "domain": [("task_id", "=", self.id)],
            "context": {"default_task_id": self.id},
        }

    def action_view_purchases(self):
        self.ensure_one()
        # 1. Buscar las líneas de compra relacionadas con la tarea.
        purchase_lines = self.env["purchase.order.line"].search(
            [("task_id", "=", self.id)]
        )
        # 2. Obtener los IDs de las órdenes de compra únicas de esas líneas.
        purchase_orders = purchase_lines.mapped("order_id")
        # 3. Devolver la acción con el dominio de los IDs de las órdenes de compra.
        return {
            "type": "ir.actions.act_window",
            "name": "Órdenes de compra",
            "res_model": "purchase.order",
            "view_mode": "list,kanban,form",
            "domain": [("id", "in", purchase_orders.ids)],
            "context": {"default_task_order_id": self.id},
        }

    def action_view_requisitions(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Requisiciones",
            "res_model": "employee.purchase.requisition",
            "view_mode": "tree,form,kanban",
            "domain": [("task_id", "=", self.id)],
            "context": {"default_task_id": self.id, "default_project_id": self.project_id.id},
        }

    # ========== FIN MÉTODOS DE ANALYTICS_EXTRA ==========

    # Método que permite cambiar el centro de trabajo al seleccionar un cliente dentro de la tarea.
    @api.onchange("partner_id")
    def _onchange_partner_id(self):
        if self.partner_id:
            if self.partner_id.centro_trabajo:
                self.centro_trabajo = self.partner_id.centro_trabajo
            else:
                self.centro_trabajo = False

    @api.depends("project_id", "project_id.is_proyecto_obra")
    def _compute_is_control_obra(self):
        for control in self:
            control.is_control_obra = bool(control.project_id.is_proyecto_obra)

    @api.model
    def default_get(self, fields_list):
        # 1. Llamamos al metodo original para obtener los defaults estandar
        defaults = super(Task, self).default_get(fields_list)

        # 2. Revisamos si un proyecto viene por defecto en el contexto
        project_id = defaults.get("project_id") or self.env.context.get(
            "default_project_id"
        )

        if project_id:
            # 3. Si tenemos un ID de proyecto, se busca dentro de la Base de datos.
            project = self.env["project.project"].browse(project_id)

            # 4. Asigna el valor del campo is_proyecto_obra del proyecto como el valor por defecto de is_control_obra de la tarea.
            if project.is_proyecto_obra:
                defaults["is_control_obra"] = True
            else:
                defaults["is_control_obra"] = False
        # 5. Se devuelven todos los valores por defecto.
        return defaults

    @api.depends("approver_id")
    def _compute_can_user_approve(self):
        """Comprueba si el usuario actual es el aprobador asignado O tiene permiso global"""
        # Verificamos si el usuario pertenece al grupo de Aprobador Global
        is_global_approver = self.env.user.has_group(
            'project_modificaciones.permiso_global_aprobar_tarea')

        for task in self:
            if is_global_approver:
                task.can_user_approve = True
            elif task.approver_id:
                task.can_user_approve = (self.env.user == task.approver_id)
            else:
                task.can_user_approve = False

    # Dominios eliminados para evitar problemas con IDs inválidos

    @api.onchange("centro_trabajo")
    def _onchange_centro_trabajo(self):
        """
        Limpia los campos dependientes si el CT cambia.
        (Lógica movida de creacion.avances)
        """
        if (
            self.planta_trabajo
            and self.planta_trabajo.cliente != self.centro_trabajo.cliente
        ):
            self.planta_trabajo = False

        if (
            self.supervisor_cliente
            and self.supervisor_cliente.cliente != self.centro_trabajo.cliente
        ):
            self.supervisor_cliente = False

    @api.model_create_multi
    def create(self, vals_list):

        # Ajusta el nombre de la tarea.
        for vals in vals_list:
            # Verificamos si la tarea viene de una línea de venta
            if vals.get("sale_line_id"):
                # Buscamos la línea para obtener la partida
                line = self.env["sale.order.line"].browse(vals["sale_line_id"])

                # Si la orden de venta tiene un servicio pendiente, usar el nombre de la orden
                if line.order_id.pending_service_id:
                    # Reemplazar el nombre del pendiente por el nombre de la orden de venta
                    vals["name"] = f"{line.order_id.name}: {line.name}"
                elif line.partida:
                    original_name = vals.get("name", "")
                    # Evitamos duplicar si ya se agregó antes
                    if line.partida not in original_name:
                        vals["name"] = f"{original_name}-[{line.partida}]"

        # 1. Obtener etapa de borrador
        stage_draft = self.env.ref(
            "project_modificaciones.project_task_type_obra_draft", raise_if_not_found=False
        )

        # Obtenemos los IDs de proyecto para consultarlos todos de una sola vez
        project_ids = [v.get("project_id")
                       for v in vals_list if v.get("project_id")]

        # Creamos un mapa: {project_id: is_proyecto_obra}
        project_map = {
            p["id"]: p["is_proyecto_obra"]
            for p in self.env["project.project"]
            .browse(project_ids)
            .read(["is_proyecto_obra"])
        }

        for vals in vals_list:
            is_control_obra = vals.get("is_control_obra", None)

            if is_control_obra is None:
                project_id = vals.get("project_id")
                is_control_obra = project_map.get(project_id, False)
                vals["is_control_obra"] = is_control_obra

            if is_control_obra:
                # 1. Asignar valores por defecto
                vals.update({
                    "approval_state": "draft",
                    "stage_id": (stage_draft.id if stage_draft else vals.get("stage_id")),
                })

                # 2. Intentar calcular el aprobador.
                supervisor_interno_id = vals.get("supervisor_interno")

                # Solo entramos si hay un supervisor asignado
                if supervisor_interno_id:
                    supervisor = self.env["hr.employee"].sudo().browse(
                        supervisor_interno_id)
                    approver_user_id = False

                    # Prioridad 1: Aprobador de la tarea de obra (Campo personalizado)
                    if supervisor.apropador_tarea_obra:
                        approver_user_id = supervisor.apropador_tarea_obra.user_id.id

                    # Prioridad 2: Fallback (Solo si no se encontró en el paso 1)
                    if not approver_user_id:
                        approver_employee = supervisor.parent_id  # Gerente

                        if not approver_employee:
                            raise ValidationError(_(
                                "El supervisor %s no tiene configurado un 'Aprobador de Tarea Obra' ni un 'Líder directo'."
                            ) % supervisor.name)

                        if not approver_employee.user_id:
                            raise ValidationError(_(
                                "El Gerente %s del Supervisor %s no tiene usuario asociado."
                            ) % (approver_employee.name, supervisor.name))

                        approver_user_id = approver_employee.user_id.id

                    # Si todo está bien, se asigna el aprobador.
                    vals["approver_id"] = approver_user_id

        # 5. Crear tareas normalmente
        tasks = super(Task, self).create(vals_list)

        # 6. Re-asegurar la etapa de borrador
        for task in tasks:
            if task.is_control_obra and stage_draft and task.stage_id != stage_draft:
                task.sudo().write({"stage_id": stage_draft.id})

        return tasks

    def _create_approval_activity(self):
        """Crea la actividad de aprobación para el superintendente."""
        activity_type_per = self.env.ref(
            "project_modificaciones.aprobacion_mail_activity", raise_if_not_found=False
        )
        if not activity_type_per:
            # Fallback por si la actividad 'To Do' no existe
            activity_type_per = self.env.ref(
                "mail.mail_activity_data_todo", raise_if_not_found=False
            )

        for task in self:
            if task.approver_id and task.approval_state == "to_approve":
                activity = self.env["mail.activity"].create(
                    {
                        "res_model_id": self.env.ref("project.model_project_task").id,
                        "res_id": task.id,
                        "user_id": task.approver_id.id,
                        "activity_type_id": activity_type_per.id,
                        "summary": _("Aprobar Tarea de Obra: %s") % task.name,
                        "note": _(
                            "Por favor, revisa y aprueba esta tarea de obra (%s) creada por %s."
                        )
                        % (task.name, task.create_uid.name),
                    }
                )
                task.approval_activity_id = activity.id

    # Método que permite que la retroalimentación muestre la etiqueta del estado en vez de la clave interna.
    def _mark_approval_activity_done(self):
        """Marca la actividad de aprobación como hecha (aprobada o rechazada)."""
        for task in self:
            if task.approval_activity_id:
                # Obtenemos el diccionario de selecciones del campo
                selection_dict = dict(task._fields["approval_state"].selection)
                # Obtenemos la etiqueta (Label) basada en el estado actual
                state_label = (
                    selection_dict.get(
                        task.approval_state) or task.approval_state
                )
                task.approval_activity_id.action_feedback(
                    feedback=_("Decisión tomada: %s") % state_label
                )

    def action_send_for_approval(self):
        stage_to_approve = self.env.ref(
            "project_modificaciones.project_task_type_obra_to_approve", raise_if_not_found=False
        )

        for task in self:
            if task.parent_id and task.parent_id.approval_state == 'approved':
                stage_progress = self.env.ref(
                    "project_modificaciones.project_task_type_obra_progress", raise_if_not_found=False)
                task.with_context(tracking_disable=True).write({
                    "approval_state": "approved",
                    "state": "01_in_progress",
                    "stage_id": stage_progress.id if stage_progress else task.stage_id.id
                })
                task.message_post(
                    body=Markup(
                        "✅ <b>AUTO-APROBADA</b><br/>Heredada de Tarea Padre: %s") % task.parent_id.name,
                    message_type="notification",
                    subtype_xmlid="mail.mt_note",
                )
                continue

            if not task.supervisor_interno:
                raise ValidationError(
                    _("Debe especificar un Supervisor Interno."))

            supervisor = task.supervisor_interno.sudo()
            approver_user = False

            if supervisor.apropador_tarea_obra:
                approver_user = supervisor.apropador_tarea_obra.user_id

            if not approver_user:
                approver_employee = supervisor.parent_id
                if not approver_employee:
                    raise ValidationError(
                        _("El Supervisor Interno no tiene configurado un aprobador ni un líder directo."))
                if not approver_employee.user_id:
                    raise ValidationError(
                        _("El líder directo del supervisor no tiene un usuario asociado."))
                approver_user = approver_employee.user_id

            if not approver_user.partner_id:
                raise ValidationError(
                    _("El usuario aprobador (%s) no tiene un partner configurado.") % approver_user.name)

            vals = {
                "approval_state": "to_approve",
                "approver_id": approver_user.id,
            }
            if stage_to_approve:
                vals["stage_id"] = stage_to_approve.id

            task.with_context(tracking_disable=True).write(vals)
            task._create_approval_activity()

            msg = (
                Markup(
                    "⚠️ <b>SOLICITUD DE APROBACIÓN</b><br/>"
                    "El supervisor <b>%s</b> solicita revisión.<br/>"
                    "Aprobador asignado: <b>%s</b>"
                ) % (task.supervisor_interno.name, approver_user.name)
            )

            task.message_post(
                body=msg,
                subject="Aprobación Requerida",
                message_type="notification",
                subtype_xmlid="mail.mt_note",
                partner_ids=[approver_user.partner_id.id],
            )

    def action_approve(self):
        stage_approved = self.env.ref(
            "project_modificaciones.project_task_type_obra_approved", raise_if_not_found=False)
        stage_progress = self.env.ref(
            "project_modificaciones.project_task_type_obra_progress", raise_if_not_found=False)
        target_stage = stage_progress or stage_approved or self.env["project.task.type"]

        is_global = self.env.user.has_group(
            'project_modificaciones.permiso_global_aprobar_tarea')

        for task in self:
            if task.approval_state != "to_approve":
                continue
            if self.env.user != task.approver_id and not is_global:
                raise ValidationError(
                    _("Solo el aprobador asignado o un aprobador global pueden aprobar."))

            recipient_ids = []
            if task.supervisor_interno.user_id:
                recipient_ids.append(
                    task.supervisor_interno.user_id.partner_id.id)

            if task.approval_activity_id and task.approval_activity_id.create_uid:
                recipient_ids.append(
                    task.approval_activity_id.create_uid.partner_id.id)

            recipient_ids = list(set(recipient_ids))

            vals = {
                "approval_state": "approved",
                "state": "01_in_progress",
            }
            if target_stage:
                vals["stage_id"] = target_stage.id

            task.with_context(tracking_disable=True).write(vals)
            task._mark_approval_activity_done()

            task.message_post(
                body=Markup(
                    "✅ <b>TAREA APROBADA</b><br/>Autorizado por: %s") % self.env.user.name,
                message_type="notification",
                subtype_xmlid="mail.mt_note",
                partner_ids=recipient_ids,
            )

    def action_reject(self):
        is_global = self.env.user.has_group(
            'project_modificaciones.permiso_global_aprobar_tarea')
        for task in self:
            if task.approval_state != "to_approve":
                continue
            if self.env.user != task.approver_id and not is_global:
                raise ValidationError(
                    _("Solo el aprobador asignado (%s) o un aprobador global pueden rechazar.") % task.approver_id.name)

            return {
                "type": "ir.actions.act_window",
                "res_model": "wizard.rechazado.task",
                "view_mode": "form",
                "target": "new",
                "context": {"active_id": task.id},
            }

    def action_draft(self):
        is_global = self.env.user.has_group(
            'project_modificaciones.permiso_global_aprobar_tarea')
        stage_to_draft = self.env.ref(
            "project_modificaciones.project_task_type_obra_draft", raise_if_not_found=False)
        for task in self:
            if task.approval_state != "rejected":
                continue
            if self.env.user != task.approver_id and not is_global:
                raise ValidationError(
                    _("Solo el aprobador asignado (%s) o un aprobador global pueden regresar a borrador.") % task.approver_id.name)

            task.with_context(tracking_disable=True).write({
                "approval_state": "draft",
                "stage_id": stage_to_draft.id if stage_to_draft else task.stage_id.id,
            })

    def notify_rejection(self, motivo):
        for task in self:
            recipient_ids = []
            if task.supervisor_interno.user_id:
                recipient_ids.append(
                    task.supervisor_interno.user_id.partner_id.id)

            if task.approval_activity_id and task.approval_activity_id.create_uid:
                recipient_ids.append(
                    task.approval_activity_id.create_uid.partner_id.id)

            recipient_ids = list(set(recipient_ids))

            msg_body = (
                Markup(
                    "🛑 <b> TAREA RECHAZADA </b><br/>"
                    "<b> Motivo: </b>%s<br/>"
                    "Por favor corrige y vuelve a enviar la tarea a aprobación."
                )
                % motivo
            )

            task.message_post(
                body=msg_body,
                message_type="notification",
                subtype_xmlid="mail.mt_note",
                partner_ids=recipient_ids,
            )

    servicio_pendiente = fields.Many2one(
        'pending.service',
        string="Servicio Pendiente",
        ondelete="set null",
        help="Servicio pendiente relacionado con la tarea."
    )