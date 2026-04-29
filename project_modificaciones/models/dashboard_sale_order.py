from odoo import fields, models, api, _
from odoo.tools import format_amount
from datetime import datetime
import logging

_logger = logging.getLogger(__name__)


class DashboardSaleOrder(models.Model):
    _name = 'dashboard.sale.order'
    _description = 'Dashboard Para La Orden De Venta'

    sale_order_id = fields.Many2one(
        'sale.order', string='Orden de Venta', required=True)
    name = fields.Char(string='Nombre', compute='_compute_name')
    currency_id = fields.Many2one(
        'res.currency', default=lambda self: self.env.company.currency_id)

    # Métricas financieras
    total_revenue = fields.Monetary(
        string='Ingresos Totales', compute='_compute_financials')
    total_costs = fields.Monetary(
        string='Costos Totales', compute='_compute_financials')
    profit_margin = fields.Monetary(
        string='Margen de Ganancia', compute='_compute_financials')
    profitability_percentage = fields.Float(
        string='% Rentabilidad', compute='_compute_financials')
    total_invoiced = fields.Monetary(
        string='Facturado', compute='_compute_financials')
    total_x_invoiced = fields.Monetary(
        string='Por Facturar', compute='_compute_financials')
    total_entregado = fields.Monetary(
        string='Total Entregado', compute='_compute_financials')

    # Contenido del dashboard
    contenido = fields.Html(
        string='Contenido', compute='_compute_contenido', sanitize=False)

    ########## COMPRAS ##########
    purchase_count = fields.Integer(
        string='Órdenes de Compra', compute='_compute_purchase_count')
    purchase_total = fields.Monetary(
        string='Total Compras', compute='_compute_purchase_data')

    ########## GASTOS ##########
    expenses_count = fields.Integer(
        string='Gastos', compute='_compute_expenses_count')
    expenses_total = fields.Monetary(
        string='Total Gastos', compute='_compute_expenses_data')

    ########## LINEAS DE VENTA ##########
    sale_order_line_ids = fields.One2many('sale.order.line', related='sale_order_id.order_line',
                                          string='Líneas de Orden de Venta', readonly=True)
    lines_count = fields.Integer(
        string='Número de Líneas', compute='_compute_lines_count')
    lines_total = fields.Monetary(
        string='Total Líneas', compute='_compute_lines_data')

    ########## REQUISICIONES ##########
    requisition_count = fields.Integer(
        string='Requisiciones', compute='_compute_requisition_count')

    ########## MOVIMIENTOS ALMACEN ##########
    stock_move_count = fields.Integer(
        string='Movimientos Almacén', compute='_compute_stock_move_data')
    stock_move_cost = fields.Monetary(
        string='Costo Mov. Almacén', compute='_compute_stock_move_data')

    ########## AVANCES ##########
    avances_count = fields.Integer(
        string='Número de Avances', compute='_compute_avances_count')
    avances_progress = fields.Float(
        string='Progreso Total', compute='_compute_avances_data')

    def _compute_name(self):
        for wizard in self:
            sale_name = wizard.sale_order_id.display_name if wizard.sale_order_id else ''
            wizard.name = f"Dashboard {sale_name}" if sale_name else 'Dashboard'

    def _compute_contenido(self):
        for wizard in self:
            # Asegurarnos de que todos los campos computados se calculen primero

            wizard._compute_financials()
            wizard._compute_purchase_data()
            wizard._compute_expenses_data()
            wizard._compute_lines_data()
            wizard._compute_requisition_count()
            wizard._compute_stock_move_data()
            wizard._compute_avances_data()

            # Preparar datos de avances para la plantilla
            avances_data = []
            if (wizard.sale_order_id and
                    hasattr(wizard.sale_order_id, 'project_sub_updates')):
                for avance in wizard.sale_order_id.project_sub_updates:
                    avances_data.append({
                        'name': avance.name or 'N/A',
                        'producto': avance.producto.name if avance.producto else 'Sin producto',
                        'unit_progress': avance.unit_progress or 0,
                        'sale_current': avance.sale_current or 0,
                        'ct': avance.ct.name if avance.ct.name else 'Sin Centro Trabajo',
                        'actual_progress': avance.actual_progress or 0,
                        'date': avance.date or 'Sin fecha',
                    })

            # Preparar datos de las líneas de venta para la plantilla
            lines_data = []
            if wizard.sale_order_id:
                for line in wizard.sale_order_id.order_line:
                    lines_data.append({
                        'name': line.name,
                        'product_uom_qty': line.product_uom_qty,
                        # 'qty_avances_delivered': line.qty_avances_delivered,
                        'progress_percentage': line.progress_percentage,
                        'qty_delivered': line.qty_delivered,
                        'qty_invoiced': line.qty_invoiced,
                        'price_unit': line.price_unit,
                        'price_subtotal': line.price_subtotal,
                        'estado': line.state,
                    })

            values = {
                'sale_order': wizard.sale_order_id,
                'financials': {
                    'revenue': wizard.total_revenue,
                    'costs': wizard.total_costs,
                    'invoiced': wizard.total_invoiced,
                    'x_invoiced': wizard.total_x_invoiced,
                    'profit_margin': wizard.profit_margin,
                    'profitability_percentage': wizard.profitability_percentage,
                    'lines_list': lines_data,
                    'entregado': wizard.total_entregado,
                },
                'metrics': {
                    'purchase_count': wizard.purchase_count,
                    'purchase_total': wizard.purchase_total,
                    'expenses_count': wizard.expenses_count,
                    'expenses_total': wizard.expenses_total,
                    'lines_count': wizard.lines_count,
                    'lines_total': wizard.lines_total,
                    'requisition_count': wizard.requisition_count,
                    'stock_move_count': wizard.stock_move_count,
                    'stock_move_cost': wizard.stock_move_cost,
                    'avances_count': wizard.avances_count,
                    'avances_progress': wizard.avances_progress,
                    'avances_units_delivered': getattr(wizard, 'avances_units_delivered', 0),
                    'avances_units_missing': getattr(wizard, 'avances_units_missing', 0),
                    'avances_value_delivered': getattr(wizard, 'avances_value_delivered', 0),
                    'avances_value_expected': getattr(wizard, 'avances_value_expected', 0),
                },
                'format_monetary': lambda v: format_amount(self.env, v, wizard.currency_id),
                'format_percentage': lambda v: f"{v:.2f}%",
                'format_unit': lambda v: f"{v:.4f}",
                'format_unidad': lambda v: f"{v:.4f}",
                'current_date': datetime.now().strftime("%d/%m/%Y"),
                'avances_list': avances_data,  # Lista de avances para desglose
                'lines_list': lines_data,  # Nueva lista de lineas de venta

            }

            wizard.contenido = self.env['ir.qweb']._render(
                'project_modificaciones.sale_order_dashboard_template', values)

    def _compute_financials(self):
        for wizard in self:
            # Total Entregado
            wizard.total_entregado = sum(
                line.qty_delivered * line.price_unit for line in wizard.sale_order_line_ids)

            # Ingresos totales de la orden de venta
            wizard.total_revenue = wizard.sale_order_id.amount_untaxed if wizard.sale_order_id else 0.0

            # Costos totales (compras + gastos)
            wizard.total_costs = (wizard.purchase_total or 0) + \
                (wizard.expenses_total or 0)

            # Facturado: Suma de la cantidad facturada multiplicada por el precio unitario de cada línea.
            wizard.total_invoiced = sum(
                line.qty_invoiced * line.price_unit for line in wizard.sale_order_line_ids)

            # Por facturar: Suma de las unidades por entregar multiplicada por el precio unitario de cada línea.
            wizard.total_x_invoiced = sum(
                (line.qty_delivered - line.qty_invoiced) * line.price_unit for line in wizard.sale_order_line_ids)

            # Margen de ganancia
            wizard.profit_margin = wizard.total_entregado - wizard.total_costs

            # Porcentaje de rentabilidad
            if wizard.total_entregado > 0:
                wizard.profitability_percentage = (
                    wizard.profit_margin / wizard.total_entregado) * 100
            else:
                wizard.profitability_percentage = 0.0

    def _compute_purchase_count(self):
        for record in self:
            if record.sale_order_id:
                task_ids = self.env['project.task'].search(
                    [('sale_order_id', '=', record.sale_order_id.id)])
                purchase_order_lines = self.env['purchase.order.line'].search(
                    [('task_id', 'in', task_ids.ids)])
                purchase_order_ids = purchase_order_lines.mapped('order_id')
                record.purchase_count = len(purchase_order_ids)
            else:
                record.purchase_count = 0

    def _compute_purchase_data(self):
        for record in self:
            if record.sale_order_id:
                task_ids = self.env['project.task'].search(
                    [('sale_order_id', '=', record.sale_order_id.id)])
                purchase_order_lines = self.env['purchase.order.line'].search([
                    ('task_id', 'in', task_ids.ids),
                    ('order_id.state', 'in', ('purchase', 'done'))
                ])
                record.purchase_total = sum(
                    purchase_order_lines.mapped('price_subtotal'))
            else:
                record.purchase_total = 0.0

    def _compute_expenses_count(self):
        for record in self:
            if record.sale_order_id:
                task_ids = self.env['project.task'].search(
                    [('sale_order_id', '=', record.sale_order_id.id)])
                expenses = self.env['hr.expense'].search(
                    [('task_id', 'in', task_ids.ids)])
                record.expenses_count = len(expenses)
            else:
                record.expenses_count = 0

    def _compute_expenses_data(self):
        for record in self:
            if record.sale_order_id:
                task_ids = self.env['project.task'].search(
                    [('sale_order_id', '=', record.sale_order_id.id)])
                expenses = self.env['hr.expense'].search([
                    ('task_id', 'in', task_ids.ids),
                    ('state', 'in', ('approved', 'done'))
                ])
                record.expenses_total = sum(expenses.mapped('total_amount'))
            else:
                record.expenses_total = 0.0

    def _compute_lines_count(self):
        for record in self:
            record.lines_count = len(
                record.sale_order_id.order_line) if record.sale_order_id else 0

    def _compute_lines_data(self):
        for record in self:
            record.lines_total = record.sale_order_id.amount_untaxed if record.sale_order_id else 0.0

    def _compute_requisition_count(self):
        for record in self:
            count = 0
            if record.sale_order_id:
                # Buscar tareas relacionadas con la orden de venta
                task_ids = self.env['project.task'].search(
                    [('sale_order_id', '=', record.sale_order_id.id)])
                if task_ids:
                    count = self.env['employee.purchase.requisition'].search_count(
                        [('task_id', 'in', task_ids.ids)])
            record.requisition_count = count

    def _compute_stock_move_data(self):
        for record in self:
            count = 0
            cost = 0.0
            if record.sale_order_id:
                # Buscar tareas relacionadas con la orden de venta
                tasks = self.env['project.task'].search(
                    [('sale_order_id', '=', record.sale_order_id.id)])
                if tasks:
                    # Usamos los campos computados que ya agregamos a project.task
                    # Esto asume que stock_move_count y stock_move_cost existen en project.task
                    # Si no, tendríamos que recalcularlo aquí igual que en la tarea.
                    # Dado que ya lo implementamos en la tarea, podemos sumar.
                    count = sum(tasks.mapped('stock_move_count'))
                    cost = sum(tasks.mapped('stock_move_cost'))
            record.stock_move_count = count
            record.stock_move_cost = cost

    def _compute_avances_count(self):
        for record in self:
            if (record.sale_order_id and
                    hasattr(record.sale_order_id, 'project_sub_updates')):
                record.avances_count = len(
                    record.sale_order_id.project_sub_updates)
            else:
                record.avances_count = 0

    def _compute_avances_data(self):
        for record in self:
            # Inicializar variables
            total_units_delivered = 0.0
            total_value_delivered = 0.0
            total_valor_entregado = 0.0
            avances_count = 0

            # Verificar si la orden de venta existe y tiene avances
            if record.sale_order_id and hasattr(record.sale_order_id,
                                                'project_sub_updates') and record.sale_order_id.project_sub_updates:

                avances = record.sale_order_id.project_sub_updates

                for avance in avances:
                    # UNIDADES ENTREGADAS: Suma de los progresos de cada avance.
                    # total_units_delivered += avance.unit_progress or 0.0

                    # VALOR ENTREGADO: unit_progress * precio_unitario de la tarea
                    if avance.task_id and hasattr(avance.task_id, 'price_unit'):
                        total_value_delivered += (avance.unit_progress or 0.0) * \
                            (avance.task_id.price_unit or 0.0)

                    avances_count += 1

                # --- SECCIÓN DEL CÁLCULO DEL PORCENTAJE ---

                # Calcular el total de unidades esperadas de la orden de venta
                total_qty_expected = sum(
                    record.sale_order_id.order_line.mapped('product_uom_qty'))

                # Calcular el total de unidades entregadas de la orden de venta
                total_units_delivered = sum(
                    record.sale_order_id.order_line.mapped('qty_delivered'))

                # Obtener valor total de lo entregado
                for wizard in self:
                    total_valor_entregado = sum(
                        line.qty_delivered * line.price_unit for line in wizard.sale_order_line_ids
                    )

                # Calcular el progreso total basado en las unidades
                if total_qty_expected > 0:
                    record.avances_progress = (
                        total_units_delivered / total_qty_expected) * 100
                else:
                    record.avances_progress = 0.0

                # Almacenar métricas
                record.avances_units_delivered = total_units_delivered
                record.avances_units_missing = total_qty_expected - total_units_delivered
                record.avances_value_delivered = total_valor_entregado
                # Aquí se mantiene el total_value_expected de la orden de venta
                record.avances_value_expected = record.sale_order_id.amount_untaxed or 0.0
                record.avances_count = avances_count

            else:
                # Si no hay avances, todos los valores son cero
                record.avances_progress = 0.0
                record.avances_units_delivered = 0.0
                record.avances_units_missing = 0.0
                record.avances_value_delivered = 0.0
                record.avances_value_expected = 0.0
                record.avances_count = 0

    # Añadir estos campos al modelo
    avances_units_delivered = fields.Float(
        string='Unidades Entregadas', compute='_compute_avances_data')
    avances_units_missing = fields.Float(
        string='Unidades Faltantes', compute='_compute_avances_data')
    avances_value_delivered = fields.Monetary(
        string='Valor Entregado', compute='_compute_avances_data')
    avances_value_expected = fields.Monetary(
        string='Valor Esperado', compute='_compute_avances_data')

    # Acciones de navegación
    def action_view_purchase_orders(self):
        self.ensure_one()
        if self.sale_order_id:
            task_ids = self.env['project.task'].search(
                [('sale_order_id', '=', self.sale_order_id.id)])
            purchase_order_lines = self.env['purchase.order.line'].search(
                [('task_id', 'in', task_ids.ids)])
            # No sirve solo debemos obtener la lineas de orden de compra
            purchase_order_ids = purchase_order_lines.mapped('order_id')

            return {
                'type': 'ir.actions.act_window',
                'name': 'Órdenes de Compra Relacionadas',
                'res_model': 'purchase.order.line',
                'view_mode': 'tree,form',
                'domain': [('id', 'in', purchase_order_lines.ids)],
                'context': {'create': False},
            }
        return False

    def action_view_expenses_count(self):
        self.ensure_one()
        if self.sale_order_id:
            task_ids = self.env['project.task'].search(
                [('sale_order_id', '=', self.sale_order_id.id)])
            expenses = self.env['hr.expense'].search(
                [('task_id', 'in', task_ids.ids)])

            return {
                'type': 'ir.actions.act_window',
                'name': 'Gastos Relacionados',
                'res_model': 'hr.expense',
                'view_mode': 'tree,form',
                'domain': [('id', 'in', expenses.ids)],
                'context': {'create': False},
            }
        return False

    def action_view_sale_order_lines(self):
        self.ensure_one()
        if self.sale_order_id:
            return {
                'type': 'ir.actions.act_window',
                'name': 'Líneas de Orden de Venta',
                'res_model': 'sale.order.line',
                'view_mode': 'tree,form',
                'domain': [('order_id', '=', self.sale_order_id.id)],
                'context': {'create': False},
            }
        return False

    def action_view_requisitions(self):
        self.ensure_one()
        if self.sale_order_id:
            task_ids = self.env['project.task'].search(
                [('sale_order_id', '=', self.sale_order_id.id)])
            return {
                'type': 'ir.actions.act_window',
                'name': 'Requisiciones Relacionadas',
                'res_model': 'employee.purchase.requisition',
                'view_mode': 'tree,form',
                'domain': [('task_id', 'in', task_ids.ids)],
                'context': {'create': False},
            }
        return False

    def action_view_stock_moves(self):
        self.ensure_one()
        if self.sale_order_id:
            task_ids = self.env['project.task'].search(
                [('sale_order_id', '=', self.sale_order_id.id)])
            return {
                'type': 'ir.actions.act_window',
                'name': 'Movimientos de Almacén',
                'res_model': 'stock.move',
                'view_mode': 'tree,form',
                'domain': [('task_id', 'in', task_ids.ids), ('state', '=', 'done'), ('picking_type_id.code', '=', 'outgoing')],
                'context': {'create': False},
            }
        return False

    def action_view_avances_dashboard(self):
        self.ensure_one()
        if self.sale_order_id:
            return {
                'name': _('Avances'),
                'type': 'ir.actions.act_window',
                'res_model': 'project.sub.update',
                'view_mode': 'tree,form',
                'domain': [('sale_order_id', '=', self.sale_order_id.id)],
                'context': {'default_sale_order_id': self.sale_order_id.id, 'create': False},
            }
        return

    def action_view_avances_from_dashboard(self):
        """Abrir avances relacionados con la línea de venta"""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Avances de Línea',
            'res_model': 'project.sub.update',
            'view_mode': 'tree,form',
            'domain': [('sale_order_line_id', '=', self.id)],
            'context': {
                'default_sale_order_line_id': self.id,
                'search_default_sale_order_line_id': self.id
            },
            'target': 'current',
        }


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    def action_open_sale_dashboard(self):
        self.ensure_one()
        wizard = self.env['dashboard.sale.order'].create(
            {'sale_order_id': self.id})
        return {
            'type': 'ir.actions.act_window',
            'name': f"Dashboard - {self.display_name}",
            'res_model': 'dashboard.sale.order',
            'view_mode': 'form',
            'res_id': wizard.id,
            'target': 'current',
        }
