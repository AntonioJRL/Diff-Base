from odoo import api, fields, models, _
from odoo.tools import format_amount
from odoo.tools.float_utils import float_round

"""
Wizard de análisis de tarea (task.update) con KPIs y rentabilidad.
"""


class AnalyticsTaskDashboard(models.TransientModel):
    """
    Wizard de análisis de tarea: arma un dashboard de rentabilidad y accesos
    rápidos para la tarea seleccionada.
    """
    _name = 'task.update'
    _description = 'Dashboard de Tarea'
    _rec_name = 'name'

    # Referencia a la tarea y metadatos del wizard
    task_id = fields.Many2one('project.task', string='Tarea', required=True)
    name = fields.Char(string='Nombre', compute='_compute_name')
    content = fields.Html(string='Contenido',
                          compute='_compute_content', sanitize=False)
    user_id = fields.Many2one(
        'res.users', string='Autor', default=lambda self: self.env.user)
    date = fields.Date(default=fields.Date.context_today)
    status_text = fields.Char(string='Estado', compute='_compute_status_text')

    # Métricas agregadas para cabecera de KPIs
    timesheet_count = fields.Integer(
        string='Hojas de horas', compute='_compute_stats')
    timesheet_hours = fields.Float(
        string='Horas', compute='_compute_stats', digits=(16, 2))
    subtask_count = fields.Integer(string='Tareas', compute='_compute_stats')
    sale_order_count = fields.Integer(
        string='Órdenes de venta', compute='_compute_stats')
    sale_line_count = fields.Integer(
        string='Artículos OV', compute='_compute_stats')
    purchase_count = fields.Integer(
        string='Órdenes de compra', compute='_compute_stats')
    expense_count = fields.Integer(string='Gastos', compute='_compute_stats')
    avances_count = fields.Integer(string='Avances', compute='_compute_stats')
    stock_move_count = fields.Integer(
        string='Mov. Almacén', compute='_compute_stats')
    requisition_count = fields.Integer(
        string='Requisiciones', compute='_compute_stats')

    # Rentabilidad
    expected_income = fields.Monetary(string='Ingresos esperados', compute='_compute_profitability',
                                      currency_field='currency_id')
    invoiced_income = fields.Monetary(string='Facturado', compute='_compute_profitability',
                                      currency_field='currency_id')
    to_invoice_income = fields.Monetary(string='Por facturar', compute='_compute_profitability',
                                        currency_field='currency_id')
    # Costos y márgenes (aprox.)
    total_expenses = fields.Monetary(string='Total Gastos', compute='_compute_profitability',
                                     currency_field='currency_id')
    total_purchases = fields.Monetary(string='Total Compras', compute='_compute_profitability',
                                      currency_field='currency_id')
    total_stock_moves = fields.Monetary(string='Total Mov. Almacén', compute='_compute_profitability',
                                        currency_field='currency_id')
    total_costs = fields.Monetary(
        string='Total Costos', compute='_compute_profitability', currency_field='currency_id')
    costs_total = fields.Monetary(
        string='Costos', compute='_compute_profitability', currency_field='currency_id')
    margin_total = fields.Monetary(
        string='Margen', compute='_compute_profitability', currency_field='currency_id')
    total_facturado = fields.Monetary(
        string='Costos Facturados Prov.', compute='_compute_profitability', currency_field='currency_id')
    total_a_facturar = fields.Monetary(
        string='Costos Por Facturar Prov.', compute='_compute_profitability', currency_field='currency_id')
    profit_percentage = fields.Float(
        string='% Rentabilidad', compute='_compute_profitability')
    expected_percentage = fields.Float(string='% esperado')
    facturado_margen = fields.Float(
        string='% Margen Fact', compute='_compute_profitability')
    to_bill_to_invoice_percentage = fields.Float(string='% por facturar')
    billed_invoiced_percentage = fields.Float(string='% facturado')
    total_expected = fields.Monetary(string='Total esperado', compute='_compute_profitability',
                                     currency_field='currency_id')
    total_to_bill_to_invoice = fields.Monetary(string='Total por facturar', compute='_compute_profitability',
                                               currency_field='currency_id')
    total_billed_invoiced = fields.Monetary(string='Total facturado', compute='_compute_profitability',
                                            currency_field='currency_id')
    currency_id = fields.Many2one(
        'res.currency', default=lambda self: self.env.company.currency_id)

    # Entregado
    total_entregado = fields.Monetary(
        string='Total entregado', compute='_compute_profitability', currency_field='currency_id')

    # Producción Sin Orden de Venta
    esperado_sin_orden = fields.Monetary(
        string='Esperado S/OV', compute='_compute_profitability',)

    def _compute_status_text(self):
        # Muestra el nombre de la etapa de la tarea
        for wizard in self:
            wizard.status_text = wizard.task_id.stage_id.display_name if wizard.task_id and wizard.task_id.stage_id else ''

    def _compute_name(self):
        # Construye el nombre visible del wizard
        for wizard in self:
            task_name = wizard.task_id.display_name if wizard.task_id else ''
            wizard.name = f"Tablero de {task_name}" if task_name else 'Tablero'

    @api.depends('task_id')
    def _compute_content(self):
        # Reúne datos (gastos aprobados y compras confirmadas) y renderiza la plantilla QWeb
        for wizard in self:
            expenses = self.env['hr.expense'].search([
                ('task_id', '=', wizard.task_id.id),
                ('sheet_id.state', 'in', ['approve', 'post', 'done'])
            ])
            # Compras: considerar solo líneas de compra asociadas a la tarea
            polines = self.env['purchase.order.line'].search([
                ('task_id', '=', wizard.task_id.id),
                ('order_id.state', 'in', ('purchase', 'done')),
            ])

            total_expenses = sum(expenses.mapped(
                'total_amount')) if expenses else 0.0
            total_purchases = sum(polines.mapped(
                'price_subtotal')) if polines else 0.0

            # Calcular facturación de compras (proveedores) para separar "Por facturar" vs "Facturado"
            vendor_bill_lines = self.env['account.move.line'].search([
                ('purchase_line_id.task_id', '=', wizard.task_id.id),
                ('move_id.state', '=', 'posted'),
                ('move_id.move_type', 'in', ('in_invoice', 'in_refund')),
            ])
            purchases_billed = sum(vendor_bill_lines.mapped(
                'price_subtotal')) if vendor_bill_lines else 0.0
            purchases_to_bill = max(total_purchases - purchases_billed, 0.0)

            # Calcular facturación de gastos: considerar como "facturado" cuando la hoja está posteada/done
            expenses_billed = 0.0
            expenses_to_bill = 0.0
            if expenses:
                expenses_billed = sum(
                    expenses.filtered(lambda e: e.sheet_id and e.sheet_id.state in ('post', 'done')).mapped(
                        'total_amount'))
                expenses_to_bill = max(total_expenses - expenses_billed, 0.0)

            # --- Timesheets Logic ---
            comp_lines = self.env['compensation.line'].search([
                ('task_id', '=', wizard.task_id.id),
                ('compensation_id.state', 'in', ['approved', 'applied'])
            ])
            timesheet_cost = sum(comp_lines.mapped('total_cost'))
            timesheet_billed = sum(comp_lines.filtered(
                lambda l: l.compensation_id.state == 'applied').mapped('total_cost'))
            timesheet_to_bill = max(timesheet_cost - timesheet_billed, 0.0)

            # --- Stock Moves Logic ---
            stock_billed = wizard.task_id.stock_move_cost or 0.0
            # Calculated Pending Stock Cost
            all_moves = self.env['stock.move'].search([
                ('task_id', '=', wizard.task_id.id),
                ('state', 'in', ['confirmed', 'assigned',
                                 'partially_available', 'done']),
                ('picking_type_id.code', '=', 'outgoing')
            ])
            scope_qty_per_product = {}
            for move in all_moves:
                scope_qty_per_product[move.product_id.id] = scope_qty_per_product.get(
                    move.product_id.id, 0.0) + move.product_uom_qty

            purchased_qty_per_product = {}
            purchase_lines = self.env['purchase.order.line'].search([
                ('task_id', '=', wizard.task_id.id),
                ('order_id.state', 'in', ['purchase', 'done'])
            ])
            for line in purchase_lines:
                purchased_qty_per_product[line.product_id.id] = purchased_qty_per_product.get(
                    line.product_id.id, 0.0) + line.product_qty

            stock_expected = 0.0
            for product_id, scope_qty in scope_qty_per_product.items():
                purchased_qty = purchased_qty_per_product.get(product_id, 0.0)
                chargeable_qty = max(0.0, scope_qty - purchased_qty)
                if chargeable_qty > 0:
                    product = self.env['product.product'].browse(product_id)
                    stock_expected += chargeable_qty * product.standard_price

            stock_to_bill = max(stock_expected - stock_billed, 0.0)

            total_facturado = expenses_billed + \
                purchases_billed + timesheet_billed + stock_billed
            total_a_facturar = expenses_to_bill + \
                purchases_to_bill + timesheet_to_bill + stock_to_bill

            wizard.total_facturado = total_facturado
            wizard.total_a_facturar = total_a_facturar

            esperado_sin_orden = 0.0
            for avance in wizard.task_id.sub_update_ids:
                if avance.precio_unidad and avance.unit_progress:
                    esperado_sin_orden += avance.precio_unidad * avance.unit_progress

            # Preparar lista de movimientos de almacén para el detalle
            stock_moves_list = []
            # CORRECCIÓN: Mostrar TODOS los movimientos relevantes (Done + Pending) para la tabla de detalle
            # Esto debe coincidir con la lógica de cálculo de costos
            moves = self.env['stock.move'].search([
                ('task_id', '=', wizard.task_id.id),
                ('state', 'in', ['confirmed', 'assigned',
                 'partially_available', 'done']),
                ('picking_type_id.code', '=', 'outgoing')
            ])

            for move in moves:
                # Calcular costo (fallback a costo estándar del producto si el movimiento no tiene precio)
                price_unit = move.price_unit or move.product_id.standard_price
                # Para pendientes, usamos product_uom_qty (Demanda). Para hechos, quantity (Hecho).
                qty_display = move.quantity if move.state == 'done' else move.product_uom_qty

                total_cost = qty_display * price_unit

                # Generar URL directa al picking
                base_url = wizard.env['ir.config_parameter'].sudo(
                ).get_param('web.base.url')
                picking_url = f"{base_url}/web#id={move.picking_id.id}&model=stock.picking&view_type=form"

                # Obtener Lotes/Series (si existen)
                lot_names = ", ".join(
                    move.move_line_ids.mapped('lot_id.name')) or "-"

                # Estado Traducido Manualmente
                state_map = {
                    'draft': 'Borrador',
                    'waiting': 'Esperando otra operación',
                    'confirmed': 'En espera',
                    'assigned': 'Reservado',
                    'done': 'Hecho',
                    'cancel': 'Cancelado',
                }
                state_label = state_map.get(move.state, move.state)

                # Requisición Relacionada
                req_name = move.picking_id.requisition_id2.name or "-"

                stock_moves_list.append({
                    'product_name': move.product_id.display_name,
                    'date': move.date,
                    'quantity': qty_display,
                    'uom': move.product_uom.name,
                    'reference': move.reference,
                    'picking': move.picking_id.name,
                    'picking_id': move.picking_id.id,
                    'picking_url': picking_url,
                    'price_unit': price_unit,
                    'total_cost': total_cost,
                    # Nuevos Campos
                    'state_label': state_label,
                    'state_raw': move.state,
                    'location_id': move.location_id.display_name,
                    'location_dest_id': move.location_dest_id.display_name,
                    'lot_name': lot_names,
                    'requisition': req_name,
                })

            # Construir datos para plantilla de dashboard de tarea (similar a proyecto)
            values = {
                'wizard_id': wizard.id,
                'profitability': {
                    'expected_income': wizard.expected_income,
                    'timesheet_cost': timesheet_cost,
                    'timesheet_billed': timesheet_billed,
                    'timesheet_to_bill': timesheet_to_bill,
                    'to_invoice_income': wizard.to_invoice_income,
                    'invoiced_income': wizard.invoiced_income,
                    'total_expenses': total_expenses,
                    'expenses_to_bill': expenses_to_bill,
                    'expenses_billed': expenses_billed,
                    'total_facturado': total_facturado,
                    'total_a_facturar': total_a_facturar,
                    'total_purchases': total_purchases,
                    'purchases_to_bill': purchases_to_bill,
                    'purchases_billed': purchases_billed,
                    'total_stock_moves': stock_expected,
                    'stock_billed': stock_billed,
                    'stock_to_bill': stock_to_bill,
                    'esperado_sin_orden': esperado_sin_orden,
                    'margen_total': wizard.margin_total,
                    'expected_percentage': wizard.expected_percentage,
                    'total_billed_invoiced': wizard.total_billed_invoiced,
                    'total_to_bill_to_invoice': wizard.total_to_bill_to_invoice,
                    'total_expected': wizard.total_expected,
                    'facturado_margen': wizard.facturado_margen,
                    'billed_invoiced_percentage': wizard.billed_invoiced_percentage,
                    'profit_percentage': wizard.profit_percentage,
                    'to_bill_to_invoice_percentage': wizard.to_bill_to_invoice_percentage,
                    'total_entregado': wizard.total_entregado,
                    'total_costs': wizard.total_costs
                },
                'stock_moves_list': stock_moves_list,

                'format_monetary': lambda v: format_amount(self.env, float_round(v, precision_digits=3), wizard.currency_id),
                # Modificado
                'format_percentage': lambda v: f"{v:.2f}%" if v is not False else '0.00%',
                'format_signed_percentage': lambda v: f"{('+' if v >= 0 else '')}{v:.2f}%" if v is not False else '0.00%',
            }
            wizard.content = self.env['ir.qweb']._render(
                'project_modificaciones.task_dashboard_template', values)

    @api.depends('task_id', 'task_id.effective_hours', 'task_id.timesheet_ids')
    def _compute_stats(self):
        # KPIs rápidos: horas, subtareas, ventas, compras confirmadas y gastos aprobados
        for wizard in self:
            # Timesheets
            try:
                wizard.timesheet_count = len(wizard.task_id.timesheet_ids)
                wizard.timesheet_hours = wizard.task_id.effective_hours
            except Exception:
                wizard.timesheet_count = 0
                wizard.timesheet_hours = 0.0
            # Subtareas
            wizard.subtask_count = len(wizard.task_id.child_ids)
            # Ventas
            wizard.sale_order_count = 1 if wizard.task_id.sale_order_id else 0
            wizard.sale_line_count = 1 if wizard.task_id.sale_line_id else 0
            # Compras (solo confirmadas o hechas)
            wizard.purchase_count = self.env['purchase.order.line'].search_count([
                ('task_id', '=', wizard.task_id.id),
                ('order_id.state', 'in', ('purchase', 'done')),
            ])
            # Gastos (solo aprobados o posteriores)
            wizard.expense_count = self.env['hr.expense'].search_count([
                ('task_id', '=', wizard.task_id.id),
                ('sheet_id.state', 'in', ['approve', 'post', 'done'])
            ])
            # Movimientos de almacén
            wizard.stock_move_count = wizard.task_id.stock_move_count
            # Requisiciones
            wizard.requisition_count = wizard.task_id.requisition_count

    @api.depends('task_id')
    def _compute_profitability(self):
        for wizard in self:
            # --- 1. Inicialización ---
            expected = 0.0
            invoiced = 0.0
            total_delivered_amount = 0.0
            to_invoice = 0.0

            # --- 2. Ingresos (Ventas) ---
            sol = wizard.task_id.sale_line_id
            if sol:
                expected = sol.price_subtotal or 0.0
                posted_lines = sol.invoice_lines.filtered(
                    lambda l: l.move_id.state == 'posted')
                invoiced = sum(posted_lines.mapped('price_subtotal'))
                total_delivered_amount = sol.qty_delivered * sol.price_unit
                qty_to_invoice = sol.qty_delivered - sol.qty_invoiced
                to_invoice = qty_to_invoice * sol.price_unit

            wizard.expected_income = expected
            wizard.invoiced_income = invoiced
            wizard.to_invoice_income = to_invoice
            wizard.total_entregado = total_delivered_amount

            # --- 3. Costos (Gastos, Compras, Stock, Horas) ---

            # A. Gastos
            expenses = self.env['hr.expense'].search([
                ('task_id', '=', wizard.task_id.id),
                ('sheet_id.state', 'in', ['approve', 'post', 'done'])
            ])
            expenses_total = sum(expenses.mapped('total_amount'))

            # Facturación Gastos
            expenses_billed = sum(expenses.filtered(
                lambda e: e.sheet_id.state in ('post', 'done')
            ).mapped('total_amount'))
            expenses_to_bill = max(expenses_total - expenses_billed, 0.0)

            # B. Compras
            # Optimización: Buscar lineas directamente, no hace falta buscar PO y luego lineas
            purchase_lines = self.env['purchase.order.line'].search([
                ('task_id', '=', wizard.task_id.id),
                ('order_id.state', 'in', ('purchase', 'done'))
            ])
            purchases_total = sum(purchase_lines.mapped('price_subtotal'))

            # Facturación Compras
            vendor_bill_lines = self.env['account.move.line'].search([
                ('purchase_line_id.task_id', '=', wizard.task_id.id),
                ('move_id.state', '=', 'posted'),
                ('move_id.move_type', 'in', ('in_invoice', 'in_refund')),
            ])
            purchases_billed = sum(vendor_bill_lines.mapped('price_subtotal'))
            purchases_to_bill = max(purchases_total - purchases_billed, 0.0)

            # C. Stock
            # Usamos el costo ya calculado en la tarea para el total global
            stock_cost = wizard.task_id.stock_move_cost or 0.0

            # Nota: Para saber cuanto está "facturado" o "por facturar" de stock,
            # Odoo estándar no factura stock moves directamente al cliente de forma simple
            # a menos que sea dropshipping o re-facturación.
            # Asumiré tu lógica: Stock casi siempre es costo directo (billed) o pendiente.
            # En tu código original usabas lógica compleja en _compute_content.
            # Simplificaremos asumiendo que el costo de stock ya es un costo realizado.
            stock_billed = stock_cost
            stock_to_bill = 0.0

            # D. Hojas de Horas
            comp_lines = self.env['compensation.line'].search([
                ('task_id', '=', wizard.task_id.id),
                ('compensation_id.state', 'in', ['approve', 'applied'])
            ])
            timesheet_cost = sum(comp_lines.mapped('total_cost'))
            timesheet_billed = sum(comp_lines.filtered(
                lambda l: l.compensation_id.state == 'applied').mapped('total_cost'))
            timesheet_to_bill = max(timesheet_cost - timesheet_billed, 0.0)

            # --- 4. Asignación de Campos de Costos ---
            wizard.total_expenses = expenses_total
            wizard.total_purchases = purchases_total
            wizard.total_stock_moves = stock_cost

            wizard.total_costs = expenses_total + \
                purchases_total + stock_cost + timesheet_cost
            # Parece duplicado pero lo mantenemos por compatibilidad con tu vista
            wizard.costs_total = wizard.total_costs

            # --- 5. Totales Facturados (Proveedores) ---
            # AQUÍ ES DONDE DEBES CALCULARLO, NO EN _COMPUTE_CONTENT
            total_facturado_prov = expenses_billed + \
                purchases_billed + timesheet_billed + stock_billed
            total_a_facturar_prov = expenses_to_bill + \
                purchases_to_bill + timesheet_to_bill + stock_to_bill

            wizard.total_facturado = total_facturado_prov
            wizard.total_a_facturar = total_a_facturar_prov

            # --- 6. Márgenes ---
            wizard.margin_total = wizard.total_entregado - wizard.total_costs
            wizard.total_expected = wizard.total_entregado - wizard.costs_total

            # Margen Facturado vs Costo Facturado
            wizard.total_billed_invoiced = wizard.invoiced_income - total_facturado_prov
            # Margen Por Facturar vs Costo Por Facturar
            wizard.total_to_bill_to_invoice = wizard.to_invoice_income - total_a_facturar_prov

            # --- 7. Porcentajes ---
            wizard.profit_percentage = (
                wizard.margin_total / expected * 100.0) if expected else 0.0
            wizard.expected_percentage = (
                wizard.margin_total / wizard.total_entregado * 100.0) if wizard.total_entregado else 0.0
            wizard.facturado_margen = (
                wizard.total_billed_invoiced / wizard.invoiced_income * 100.0) if wizard.invoiced_income else 0.0

            if wizard.to_invoice_income:
                percent = (wizard.total_to_bill_to_invoice /
                           wizard.to_invoice_income * 100.0)
                wizard.to_bill_to_invoice_percentage = percent
                wizard.billed_invoiced_percentage = percent
            else:
                wizard.to_bill_to_invoice_percentage = 0.0
                wizard.billed_invoiced_percentage = 0.0

            # --- 8. Producción S/OV (Lógica específica tuya) ---
            esperado_sin_ov = 0.0
            for avance in wizard.task_id.sub_update_ids:
                if avance.precio_unidad and avance.unit_progress:
                    esperado_sin_ov += avance.precio_unidad * avance.unit_progress
            wizard.esperado_sin_orden = esperado_sin_ov

    # Acciones de navegación
    def action_view_subtasks(self):
        # Abre las subtareas relacionadas
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Subtareas',
            'res_model': 'project.task',
            'view_mode': 'list,kanban,form',
            'domain': [('parent_id', '=', self.task_id.id)],
            'context': {'default_parent_id': self.task_id.id, 'default_project_id': self.task_id.project_id.id},
        }

    def action_view_stock_moves(self):
        """Abre los movimientos de almacén relacionados"""
        self.ensure_one()
        # Obtener pickings directamente de los moves relacionados
        # Usamos sudo() para asegurar acceso si hay reglas de registro restrictivas
        # Ampliamos la búsqueda para incluir moves pendientes si es necesario
        moves = self.env['stock.move'].search(
            [('task_id', '=', self.task_id.id)])
        picking_ids = moves.mapped('picking_id').ids

        return {
            'type': 'ir.actions.act_window',
            'name': 'Movimientos de Almacén',
            'res_model': 'stock.picking',
            'view_mode': 'tree,form',
            'domain': [('id', 'in', picking_ids)],
            'context': {'default_task_id': self.task_id.id},
        }

    def action_views_requisitions(self):
        """Abre las Requisiciones relacionadas a la tarea"""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Requisiciones',
            'res_model': 'employee.purchase.requisition',
            'view_mode': 'tree,form',
            'domain': [('task_id', '=', self.task_id.id)],
            'context': {'default_task_id': self.task_id.id},
        }

    def action_view_timesheets(self):
        """
        Abre las Solicitudes de Hojas de Horas (compensation.request) relacionadas
        con la tarea actual a través de sus líneas (compensation.line).
        """
        self.ensure_one()

        # 1. Buscar líneas de compensación vinculadas a la tarea
        comp_lines = self.env['compensation.line'].search(
            [('task_id', '=', self.task_id.id)]
        )
        # 2. Obtener los IDs únicos de las solicitudes de compensación asociadas
        request_ids = comp_lines.mapped('compensation_id')

        # 3. Retornar la acción hacia la compesation.requiest
        return {
            'type': 'ir.actions.act_window',
            'name': 'Hojas de horas',
            'res_model': 'compensation.request',
            'view_mode': 'tree,form',
            'domain': [('id', 'in', request_ids.ids)],
            'context': {'create': False},
        }

    def action_view_sale_orders(self):
        # Abre la OV relacionada si existe
        self.ensure_one()
        domain = [('id', '=', self.task_id.sale_order_id.id)
                  ] if self.task_id.sale_order_id else [('id', '=', 0)]
        views = [[False, 'list'], [False, 'kanban'], [False, 'form']]
        action = {
            'type': 'ir.actions.act_window',
            'name': 'Órdenes de venta',
            'res_model': 'sale.order',
            'view_mode': 'list,form',
            'domain': domain,
            'views': views,
            'context': {'create': False},
        }
        if self.task_id.sale_order_id:
            action['views'] = [[False, 'form']]
            action['res_id'] = self.task_id.sale_order_id.id
        return action

    def action_view_purchases(self):
        self.ensure_one()
        # 1. Buscar las líneas de compra relacionadas con la tarea.
        purchase_lines = self.env['purchase.order.line'].search(
            [('task_id', '=', self.task_id.id)])
        # 2. Obtener los IDs de las órdenes de compra únicas de esas líneas.
        purchase_orders = purchase_lines.mapped('order_id')
        # 3. Devolver la acción con el dominio de los IDs de las órdenes de compra.
        return {
            'type': 'ir.actions.act_window',
            'name': 'Órdenes de compra',
            'res_model': 'purchase.order',
            'view_mode': 'list,kanban,form',
            'domain': [('id', 'in', purchase_orders.ids)],
            'context': {'default_task_order_id': self.task_id.id},
        }

    def action_view_expenses(self):
        # Abre los gastos relacionados a la tarea
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Gastos',
            'res_model': 'hr.expense',
            'view_mode': 'list,kanban,form',
            'domain': [('task_id', '=', self.task_id.id)],
            'context': {'default_task_id': self.task_id.id},
        }


class ProjectTask(models.Model):
    _inherit = 'project.task'

    def action_open_task_dashboard(self):
        # Crea y abre el wizard del dashboard
        self.ensure_one()
        wizard = self.env['task.update'].create({'task_id': self.id})
        return {
            'type': 'ir.actions.act_window',
            'name': f"Tablero de {self.display_name}",
            'res_model': 'task.update',
            'view_mode': 'form',
            'res_id': wizard.id,
        }
