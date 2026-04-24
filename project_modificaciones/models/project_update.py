from odoo import fields, models, api, _
from odoo.exceptions import ValidationError, UserError
from datetime import datetime
from markupsafe import Markup


class ProjectUpdate(models.Model):

    _inherit = "project.update"
    _order = 'date desc'

    # Se reemplaza la referencia original a 'project.sub.update' por la nueva lógica
    # pero manteniendo el nombre del campo para compatibilidad.
    sub_update_ids = fields.One2many(
        'project.sub.update', 'update_id', string="Creación De Avances")

    sale_order_id = fields.Many2one(
        'sale.order', string="Orden de Venta",
        compute='_compute_sale_order_id', store=True,
        help="Orden de Venta principal del grupo de avances."
    )

    sale_current = fields.Float(
        string='Avance del subtotal', compute='_sale_current', store=True, default=0.0)
    sale_actual = fields.Float(
        string='Subtotal entregado', compute='_sale_actual', store=True, default=0.0)
    sale_total = fields.Float(
        string='Subtotal de la venta', compute='_sale_total', store=True, default=0.0)
    sale_missing = fields.Float(
        string='Subtotal faltante', compute='_sale_missing', store=True, default=0.0)

    sale_current_text = fields.Char(
        string='Avance del subtotal (pesos)', compute='_sale_current_text', store=True)
    sale_actual_text = fields.Char(
        string='Subtotal entregado (pesos)', compute='_sale_actual_text', store=True)
    sale_total_text = fields.Char(
        string='Subtotal de la venta (pesos)', compute='_sale_total_text', store=True)
    sale_missing_text = fields.Char(
        string='Subtotal faltante (pesos)', compute='_sale_missing_text', store=True)

    # -------------------------------------------------------------------------
    # CAMPOS NUEVOS DE INHERIT (COPIADOS TAL CUAL)
    # -------------------------------------------------------------------------
    # Campo computado que mostrará la suma de los porcentajes de los avances asociados.
    progress_percentage = fields.Float(
        string="Porcentaje de Avance",
        compute="_compute_progress_percentage",
        store=True,
    )

    @api.depends('sub_update_ids.sale_order_id')
    def _compute_sale_order_id(self):
        for update in self:
            # Tomamos la primera SO encontrada en los avances
            sale_orders = update.sub_update_ids.mapped('sale_order_id')
            update.sale_order_id = sale_orders[0] if sale_orders else False

    # -------------------------------------------------------------------------
    # MÉTODOS COMPUTADOS (BASE + INHERIT)
    # -------------------------------------------------------------------------

    @api.depends('sub_update_ids.total_progress_percentage')
    def _compute_progress_percentage(self):
        """
        Calcula el porcentaje total de avance para esta actualización,
        sumando los porcentajes de todos los avances que contiene.
        """
        for update in self:
            # Suma los valores del campo 'total_progress_percentage' de todos
            # los registros en la lista 'sub_update_ids'.
            total_percentage = sum(
                update.sub_update_ids.mapped('total_progress_percentage'))
            update.progress_percentage = total_percentage

    @api.depends('sub_update_ids', 'sub_update_ids.unit_progress', 'sub_update_ids.task_id')
    def _sale_current(self):
        for u in self:
            # Nota: Referencia actualizada a project.sub.update
            sale = u.env['project.sub.update'].search(
                [('update_id.id', '=', u._origin.id)]).mapped('sale_current')
            u.sale_current = sum(sale)

    @api.depends('sub_update_ids', 'sub_update_ids.unit_progress', 'sub_update_ids.task_id')
    def _sale_actual(self):
        for u in self:
            sale = u.env['project.update'].search(
                [('project_id.id', '=', u.project_id.id), ('id', '<=', u._origin.id)]).mapped('sale_current')
            u.sale_actual = sum(sale)

    @api.depends('sub_update_ids', 'sub_update_ids.unit_progress', 'sub_update_ids.task_id')
    def _sale_total(self):
        for u in self:
            sale = u.env['project.task'].search(
                [('project_id.id', '=', u.project_id.id)]).mapped('price_subtotal')
            u.sale_total = sum(sale)

    @api.depends('sub_update_ids', 'sub_update_ids.unit_progress', 'sub_update_ids.task_id')
    def _sale_missing(self):
        for u in self:
            u.sale_missing = u.sale_total - u.sale_actual

    @api.depends('sub_update_ids', 'sub_update_ids.unit_progress', 'sub_update_ids.task_id')
    def _sale_current_text(self):
        for u in self:
            sale = "%.2f" % u.sale_current
            value_len = sale.find('.')
            for i in range(value_len, 0, -1):
                sale = sale[:i] + ',' + \
                    sale[i:] if (
                        value_len-i) % 3 == 0 and value_len != i else sale
            u.sale_current_text = '$' + sale

    @api.depends('sub_update_ids', 'sub_update_ids.unit_progress', 'sub_update_ids.task_id')
    def _sale_actual_text(self):
        for u in self:
            sale = "%.2f" % u.sale_actual
            value_len = sale.find('.')
            for i in range(value_len, 0, -1):
                sale = sale[:i] + ',' + \
                    sale[i:] if (
                        value_len-i) % 3 == 0 and value_len != i else sale
            u.sale_actual_text = '$' + sale

    @api.depends('sub_update_ids', 'sub_update_ids.unit_progress', 'sub_update_ids.task_id')
    def _sale_total_text(self):
        for u in self:
            sale = "% .2f" % u.sale_total
            value_len = sale.find('.')
            for i in range(value_len, 0, -1):
                sale = sale[:i] + ',' + \
                    sale[i:] if (
                        value_len-i) % 3 == 0 and value_len != i else sale
            u.sale_total_text = '$' + sale

    @api.depends('sub_update_ids', 'sub_update_ids.unit_progress', 'sub_update_ids.task_id')
    def _sale_missing_text(self):
        for u in self:
            sale = "% .2f" % u.sale_missing
            value_len = sale.find('.')
            for i in range(value_len, 0, -1):
                sale = sale[:i] + ',' + \
                    sale[i:] if (
                        value_len-i) % 3 == 0 and value_len != i else sale
            u.sale_missing_text = '$' + sale

    # -------------------------------------------------------------------------
    # MÉTODOS DE NEGOCIO DE INHERIT (COPIADOS TAL CUAL)
    # -------------------------------------------------------------------------

    def action_add_sub_updates(self):
        self.ensure_one()

        update = self.env["project.update"].search(
            [("project_id", "=", self.project_id.id)], order="create_date desc", limit=1
        )

        if not update:
            update = self.env["project.update"].create(
                {
                    "project_id": self.project_id.id,
                }
            )

        for sub in self.sub_update_ids:
            sub.update_id = update.id
            sub.project_id = self.project_id.id
            sub._compute_avances_estados()

            # Buscar tarea en base al nombre del producto
            if not sub.task_id and sub.producto:
                task = self.env["project.task"].search(
                    [
                        ("name", "=", sub.producto.name),
                        ("project_id", "=", sub.project_id.id),
                    ],
                    limit=1,
                )
                if task:
                    sub.task_id = task.id

        return {"type": "ir.actions.act_window_close"}

    def write(self, vals):
        if self.env.context.get('wizard_assigning'):
            return super().write(vals)

        # 1. VALIDACIÓN PREVIA (Tu lógica actual es correcta)
        # Esto asegura que no se cree un registro si faltan datos
        if "sub_update_ids" in vals:
            for command in vals.get('sub_update_ids'):
                if command[0] == 0:  # Solo al crear
                    values = command[2]

                    required_fields = {
                        'producto': 'Producto', 'date': 'Fecha',
                        'ct': 'CT (Centro de Trabajo)', 'planta': 'Planta',
                        'hora_inicio': 'Hora De Inicio', 'hora_termino': 'Hora De Termino',
                        'supervisorplanta': 'Supervisor Cliente', 'responsible_id': 'Supervisor Interno',
                        'licencia': 'Licencia/OM', 'unit_progress': 'Avance de Unidades',
                    }
                    missing_fields = [
                        f"- {label}" for field, label in required_fields.items() if not values.get(field)]
                    if missing_fields:
                        error_message = _("Para el nuevo trabajo a crear, por favor complete los siguientes campos obligatorios:\n\n%s") % (
                            "\n".join(missing_fields))
                        raise UserError(error_message)

                    hora_inicio = values.get('hora_inicio')
                    hora_termino = values.get('hora_termino')
                    if hora_inicio is not None and hora_termino is not None and hora_termino <= hora_inicio:
                        raise UserError(
                            _("¡Ups! La hora de término debe ser posterior a la hora de inicio."))

        # 2. LÓGICA DE IDENTIFICACIÓN (Se mantiene igual)
        existing_sub_ids = self.sub_update_ids.ids
        # Aquí se crean los registros 'creacion.avances' en estado 'draft'
        res = super().write(vals)
        new_sub_records_ids = set(
            self.sub_update_ids.ids) - set(existing_sub_ids)

        # 3. LÓGICA POST-GUARDADO (Procesar los nuevos avances)
        if new_sub_records_ids:
            # CAMBIO DE MODELO: creacion.avances -> project.sub.update
            new_subs = self.env['project.sub.update'].browse(
                list(new_sub_records_ids))

            for sub in new_subs:
                # 4. Asignar project_id (necesario para la lógica de la tarea)
                if not sub.project_id:
                    sub.project_id = self.project_id.id

                # 5. Asignar Tarea (task_id) - Esto es CRUCIAL
                # La 'sale_order_id' depende de esto (campo related)
                if not sub.task_id and sub.producto:
                    task = self.env["project.task"].search(
                        [
                            ("name", "=", sub.producto.name),
                            ("project_id", "=", sub.project_id.id),
                        ],
                        limit=1,
                    )
                    if task:
                        sub.task_id = task.id

                # 6. Llamar a la ACCIÓN de confirmar
                # Esta acción ya contiene la validación y la lógica
                # para pasar a 'confirmed' y luego a 'assigned'
                try:
                    # Esta función cambiará el estado a 'confirmed'
                    # y si tiene task_id, project_id y sale_order_id,
                    # lo pasará a 'assigned' automáticamente
                    sub.action_confirmado_avances()

                except (UserError, ValidationError) as e:
                    # SOFT FAIL: No bloqueamos el guardado.
                    # 1. Dejamos el avance en Borrador (ya está así por defecto/rollback interno de la llamada fallida).
                    # 2. Notificamos en el Chatter con formato amigable.

                    warning_msg = Markup(
                        """
                        <div class="alert alert-warning" role="alert">
                            <strong>⚠️ Alerta de Confirmación Automática</strong><br/>
                            El avance <b>%s</b> se ha creado exitosamente, pero permaneció en <b>Borrador</b>.<br/>
                            <small>%s</small>
                        </div>
                        """
                    ) % (sub.name, str(e))

                    self.message_post(body=warning_msg)
                    # No hacemos raise, permitimos que el flujo continúe.

        # NOTA: En tu archivo original aquí había un 'return res' que hacía inalcanzable
        # el código de abajo. Lo he quitado para que se ejecute tu lógica de enlace.

        # Tu lógica posterior para enlazar registros se mantiene igual
        if "sub_update_ids" in vals:
            for update in self:
                for sub in update.sub_update_ids:
                    if not sub.update_id:
                        sub.update_id = update.id
                    if not sub.project_id:
                        sub.project_id = update.project_id.id
                    sub._compute_avances_estados()
        return res