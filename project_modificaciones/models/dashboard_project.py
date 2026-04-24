from odoo import models, _

class ProjectProject(models.Model):
    """
    Extiende la rentabilidad del proyecto en Odoo 17 para centralizar
    costos en las tareas, eliminando duplicados analíticos.
    """
    _inherit = 'project.project'

    def _get_profitability_labels(self):
        labels = super()._get_profitability_labels()
        labels['expenses'] = _('Gastos')
        labels['purchase'] = _('Compras')
        return labels

    def _get_profitability_sequence_per_invoice_type(self):
        sequence = super()._get_profitability_sequence_per_invoice_type()
        sequence['expenses'] = 10
        sequence['purchase'] = 20
        return sequence

    def _get_profitability_items(self, with_action=True):
        profitability = super()._get_profitability_items(with_action)
        if not self:
            return profitability

        costs = profitability.get('costs', {})
        if 'data' in costs:
            # --- 1. LIMPIEZA DE DATOS ANALÍTICOS ESTÁNDAR ---
            new_data = []
            for item in costs['data']:
                item_id = item.get('id', '')
                if 'purchase' in item_id or item_id == 'expenses':
                    # Restamos valores para evitar duplicidad con el cálculo manual posterior
                    costs['total']['billed'] -= item.get('billed', 0.0)
                    costs['total']['to_bill'] -= item.get('to_bill', 0.0)
                else:
                    new_data.append(item)
            costs['data'] = new_data

        # --- 2. CÁLCULO PERSONALIZADO BASADO EN TAREAS ---
        for project in self:
            tasks = project.task_ids
            if not tasks:
                continue

            Expense = self.env['hr.expense']
            POLine = self.env['purchase.order.line']
            AccountMoveLine = self.env['account.move.line']

            # Gastos (Expenses) vinculados a tareas
            expenses = Expense.search([
                ('task_id', 'in', tasks.ids),
                ('sheet_id.state', 'in', ['approve', 'post', 'done'])
            ])

            exp_total = 0.0
            exp_billed = 0.0
            for exp in expenses:
                amount = exp.company_currency_id._convert(
                    exp.total_amount, project.currency_id, project.company_id
                )
                exp_total += amount
                if exp.sheet_id.state in ('post', 'done'):
                    exp_billed += amount

            # Compras (Purchases) vinculadas a tareas
            purchases = POLine.search([
                ('task_id', 'in', tasks.ids),
                ('order_id.state', 'in', ('purchase', 'done')),
            ])

            pur_total = 0.0
            for pol in purchases:
                pur_total += pol.currency_id._convert(
                    pol.price_subtotal, project.currency_id, project.company_id
                )

            # Facturado de Compras (Account Moves)
            vendor_lines = AccountMoveLine.search([
                ('purchase_line_id.task_id', 'in', tasks.ids),
                ('move_id.state', '=', 'posted'),
                ('move_id.move_type', 'in', ('in_invoice', 'in_refund')),
            ])

            pur_billed = 0.0
            for line in vendor_lines:
                currency = line.move_id.currency_id or project.currency_id
                sign = -1 if line.move_id.move_type == 'in_refund' else 1
                amt = currency._convert(
                    line.price_subtotal, project.currency_id, project.company_id
                )
                pur_billed += (amt * sign)

            # --- 3. INYECCIÓN DE ITEMS AL DASHBOARD ---
            items = []
            if exp_total:
                items.append({
                    'id': 'expenses',
                    'sequence': 10,
                    'billed': -exp_billed,
                    'to_bill': -(max(exp_total - exp_billed, 0.0)),
                    'action': {'type': 'object', 'name': 'action_view_project_expenses'},
                })

            if pur_total:
                items.append({
                    'id': 'purchase',
                    'sequence': 20,
                    'billed': -pur_billed,
                    'to_bill': -(max(pur_total - pur_billed, 0.0)),
                    'action': {'type': 'object', 'name': 'action_view_project_purchases'},
                })

            if items:
                costs['data'].extend(items)
                for it in items:
                    costs['total']['billed'] += it['billed']
                    costs['total']['to_bill'] += it['to_bill']

        return profitability

    # --- ACCIONES DE NAVEGACIÓN ---

    def action_view_project_expenses(self):
        self.ensure_one()
        return {
            'name': _('Gastos del Proyecto'),
            'type': 'ir.actions.act_window',
            'res_model': 'hr.expense',
            'view_mode': 'tree,form',
            'domain': [('task_id', 'in', self.task_ids.ids)],
            'context': {'create': False},
        }

    def action_view_project_purchases(self):
        self.ensure_one()
        return {
            'name': _('Compras del Proyecto'),
            'type': 'ir.actions.act_window',
            'res_model': 'purchase.order.line',
            'view_mode': 'tree,form',
            'domain': [('task_id', 'in', self.task_ids.ids), ('state', 'in', ['purchase', 'done'])],
            'context': {'create': False},
        }