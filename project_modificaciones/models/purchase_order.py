"""
Extensión de Compras (purchase.order)
- Enlaza la orden de compra con una tarea de proyecto (`task_id`).
- Expone totales agregados de cantidades solicitadas, recibidas y facturadas
  para toda la orden (útiles para KPIs/estadísticas en vistas).
"""
from odoo import fields, models, api
from odoo.exceptions import ValidationError


class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    project_id = fields.Many2one(
        'project.project',
        string='Proyecto',
        help='Proyecto vinculado a la orden de compra',
        tracking=True,
    )

    task_order_id = fields.Many2one(
        'project.task',
        string='Tarea',
        help='Tarea a la que se le viculara la compra.',
        domain="project_id and [('project_id', '=', project_id), ('state', 'not in', ['1_canceled'])] or [('state', 'not in', ['1_canceled'])]",
        tracking=True,
    )

    @api.onchange('project_id')
    def _onchange_project_id_propagation(self):
        """
        Si cambia la cabecera, NO propagamos a todas las líneas existentes.
        El usuario requiere que sea solo pre-llenado para nuevas líneas (gestionado por contexto en XML).
        """
        pass

    @api.onchange('task_order_id')
    def _onchange_task_id(self):
        """
        Si cambia la tarea de cabecera, NO propagamos a líneas existentes.
        Solo asignamos el proyecto de cabecera si falta, por comodidad.
        """
        if self.task_order_id:
            # 1. Asignar proyecto si hace falta en la cabecera
            if self.task_order_id.project_id:
                self.project_id = self.task_order_id.project_id

    # @api.onchange('order_line')
    # def _onchange_line_projects(self):
    #     """
    #     DESACTIVADO: El usuario no quiere que la cabecera cambie automáticamente
    #     basado en las líneas, ya que esto puede causar ciclos de actualización
    #     o comportamientos confusos.
    #     """
    #     pass

    # Totales agregados (toda la orden) de cantidades pedidas/recibidas/facturadas
    qty_ordered_total = fields.Float(
        string='Cantidad',
        compute='_compute_qty_totals',
        digits='Product Unit of Measure',
        store=False,
    )
    qty_received_total = fields.Float(
        string='Total Recibido',
        compute='_compute_qty_totals',
        digits='Product Unit of Measure',
        store=False,
    )
    qty_invoiced_total = fields.Float(
        string='Facturado',
        compute='_compute_qty_totals',
        digits='Product Unit of Measure',
        store=False,
    )

    # Alias simple de total recibido para compatibilidad en vistas
    qty_received = fields.Float(
        string='Cant. Recibida',
        compute='_compute_qty_totals',
        digits='Product Unit of Measure',
        store=False,
    )

    @api.depends(
        'order_line.product_qty',
        'order_line.qty_received',
        'order_line.qty_invoiced',
        'order_line.display_type',
    )
    def _compute_qty_totals(self):
        # Suma cantidades a nivel de orden, ignorando líneas de visualización/separadores
        for order in self:
            total_ordered = 0.0
            total_received = 0.0
            total_invoiced = 0.0
            for line in order.order_line:
                if getattr(line, 'display_type', False):
                    continue
                total_ordered += getattr(line, 'product_qty', 0.0)
                total_received += getattr(line, 'qty_received', 0.0)
                total_invoiced += getattr(line, 'qty_invoiced', 0.0)
            order.qty_ordered_total = total_ordered
            order.qty_received_total = total_received
            order.qty_invoiced_total = total_invoiced
            order.qty_received = total_received

            order.qty_received = total_received

    # -------------------------------------------------------------------------
    # INTEGRACIÓN CON INVENTARIO (STOCK)
    # -------------------------------------------------------------------------
    def _prepare_picking(self):
        """
        Sobreescribimos para pasar el proyecto y tarea al Albarán (Stock Picking).
        """
        res = super(PurchaseOrder, self)._prepare_picking()
        if self.project_id:
            res['project_id'] = self.project_id.id
        if self.task_order_id:
            res['task_id'] = self.task_order_id.id
        return res


class PurchaseOrderLine(models.Model):
    _inherit = 'purchase.order.line'

    project_id = fields.Many2one(
        'project.project',
        string='Proyecto',
        store=True,
        readonly=False,
    )

    # Tarea asociada a la línea de compra (aparece en la lista de productos)
    task_id = fields.Many2one(
        'project.task',
        string='Tarea',
        domain="project_id and [('project_id', '=', project_id), ('state', 'not in', ['1_canceled'])] or [('state', 'not in', ['1_canceled'])]",
        readonly=False,
    )

    @api.onchange('task_id')
    def _onchange_task_id(self):
        if self.task_id and self.task_id.project_id:
            self.project_id = self.task_id.project_id

    # 1. Rellena los datos al crear la línea - DEFAULT GET para UI
    @api.model
    def default_get(self, fields_list):
        defaults = super().default_get(fields_list)
        # En teoría Odoo lo hace automático con default_*, pero reforzamos
        if 'project_id' in fields_list and not defaults.get('project_id') and self.env.context.get('default_project_id'):
            defaults['project_id'] = self.env.context.get('default_project_id')
        if 'task_id' in fields_list and not defaults.get('task_id') and self.env.context.get('default_task_id'):
            defaults['task_id'] = self.env.context.get('default_task_id')
        return defaults

    # 1. Rellena los datos al SALVAR (backend)
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            # Si no vienen el proyecto/tarea, intentamos tomarlos de la orden
            if 'order_id' in vals:
                order = self.env['purchase.order'].browse(vals['order_id'])
                if order:
                    if 'project_id' not in vals and order.project_id:
                        vals['project_id'] = order.project_id.id
                    if 'task_id' not in vals and order.task_order_id:
                        # OJO: Solo asignamos si la tarea del padre pertenece al mismo proyecto (por coherencia)
                        # o si decidimos confiar en el padre.
                        vals['task_id'] = order.task_order_id.id
        return super().create(vals_list)

    # Evita que guarden datos incoherentes
    @api.constrains('project_id', 'task_id')
    def _check_project_task_consistency(self):
        for record in self:
            # Validación A: Coherencia Interna (Tarea debe ser del Proyecto de la línea)
            if record.project_id and record.task_id:
                if record.task_id.project_id != record.project_id:
                    raise ValidationError(
                        "La tarea seleccionada no pertenece al proyecto indicado en la línea.")

            # Validación B: Coherencia con Cabecera ELIMINADA para permitir flexibilidad

    # -------------------------------------------------------------------------
    # MÉTODO ONCHANGE: Auto-asignar Analítica en la Línea de Compra
    # -------------------------------------------------------------------------
    @api.onchange('product_id', 'task_id', 'project_id')
    def _onchange_set_analytic_from_project(self):
        """
        Al definir producto o cambiar la tarea/proyecto, asigna la 
        Cuenta Analítica del proyecto a la línea.
        """
        for line in self:
            # Si ya tiene una distribución manual compleja, tratamos de no borrarla agresivamente
            # Pero si está vacía o el usuario acaba de cambiar la tarea, aplicamos la del proyecto.

            # 1. Identificar el proyecto origen
            project = line.project_id
            if line.task_id and line.task_id.project_id:
                project = line.task_id.project_id

            # 2. Validar cuenta analítica
            if project and project.analytic_account_id:
                analytic_id = str(project.analytic_account_id.id)

                # Opción A: Imponer siempre la del proyecto (Más seguro para Control de Obra)
                line.analytic_distribution = {analytic_id: 100}

    # -------------------------------------------------------------------------
    # INTEGRACIÓN CON INVENTARIO (STOCK MOVES)
    # -------------------------------------------------------------------------
    def _prepare_stock_moves(self, picking):
        """
        Sobreescribimos para pasar el proyecto y tarea de la LÍNEA de compra
        a la LÍNEA de movimiento de stock (Stock Move).
        """
        res = super(PurchaseOrderLine, self)._prepare_stock_moves(picking)

        # res es una lista de diccionarios (generalmente uno por línea, pero puede haber desglose)
        for val in res:

            pass
            
        for val in res:
            if val.get('purchase_line_id'):
                line = self.browse(val['purchase_line_id'])
                if line.project_id:
                    val['project_id'] = line.project_id.id
                if line.task_id:
                    val['task_id'] = line.task_id.id

        return res
