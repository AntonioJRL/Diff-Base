from odoo import models, fields, api, _
from odoo.exceptions import UserError
from odoo.tools import Markup
import logging

_logger = logging.getLogger(__name__)


class ProjectReclassifyWizard(models.TransientModel):
    _name = 'project.reclassify.wizard'
    _description = 'Asistente de Reclasificación con Merge de Tareas'

    project_id = fields.Many2one(
        'project.project', string='Nuevo Proyecto',
        help="Selecciona el proyecto al cual se moverán los registros seleccionados.")

    task_id = fields.Many2one(
        'project.task', string='Nueva Tarea',
        domain="[('project_id', '=', project_id)]",
        help="Selecciona la tarea destino (opcional).")

    analytic_distribution = fields.Json(
        string='Distribución Analítica',
        help="Nueva distribución analítica a asignar. Si se deja vacío, se mantendrá la actual.")

    analytic_precision = fields.Integer(
        store=False, default=2)

    # Campo para activar merge de tareas
    merge_tasks = fields.Boolean(
        string='Consolidar Tareas',
        default=False,
        help="Si está activo, después de reclasificar los documentos, "
             "fusionará las tareas origen en la tarea destino y las eliminará.")

    # --- LISTAS DE TRABAJO (Registros a procesar) ---

    # 1. Compras
    purchase_line_ids = fields.Many2many(
        'purchase.order.line', string='Líneas de Compra')

    # 2. Compensaciones
    compensation_line_ids = fields.Many2many(
        'compensation.line', string='Líneas de Compensación')

    # 3. Requisiciones
    requisition_line_ids = fields.Many2many(
        'requisition.order', string='Líneas de Requisición')

    # 4. Gastos
    expense_line_ids = fields.Many2many(
        'hr.expense', string='Gastos')

    # 5. Stock
    stock_move_ids = fields.Many2many(
        'stock.move', string='Movimientos de Stock')

    # 6. Apuntes Contables (Account Move Lines)
    move_line_ids = fields.Many2many(
        'account.move.line', string='Apuntes Contables')

    # 7. Líneas Analíticas (Timesheets / Costos)
    analytic_line_ids = fields.Many2many(
        'account.analytic.line', string='Líneas Analíticas')

    # 8. Tareas
    task_ids = fields.Many2many(
        'project.task', string='Tareas')

    @api.model
    def default_get(self, fields):
        res = super(ProjectReclassifyWizard, self).default_get(fields)
        active_model = self.env.context.get('active_model')
        active_ids = self.env.context.get('active_ids')

        if active_model and active_ids:
            records = self.env[active_model].browse(active_ids)

            # --- POPULAR LISTAS DE TRABAJO (Work Lists) ---

            # 1. Compras
            if active_model == 'purchase.order':
                all_lines = records.mapped('order_line')
                res['purchase_line_ids'] = [(6, 0, all_lines.ids)]
            elif active_model == 'purchase.order.line':
                res['purchase_line_ids'] = [(6, 0, active_ids)]

            # 2. Compensaciones
            elif active_model == 'compensation.request':
                all_lines = records.mapped('compensation_line_ids')
                res['compensation_line_ids'] = [(6, 0, all_lines.ids)]
            elif active_model == 'compensation.line':
                res['compensation_line_ids'] = [(6, 0, active_ids)]

            # 3. Requisiciones de Empleado
            elif active_model == 'employee.purchase.requisition':
                all_lines = records.mapped('requisition_order_ids')
                res['requisition_line_ids'] = [(6, 0, all_lines.ids)]
            elif active_model == 'requisition.order':
                res['requisition_line_ids'] = [(6, 0, active_ids)]

            # 4. Gastos
            elif active_model == 'hr.expense.sheet':
                all_lines = records.mapped('expense_line_ids')
                res['expense_line_ids'] = [(6, 0, all_lines.ids)]
            elif active_model == 'hr.expense':
                res['expense_line_ids'] = [(6, 0, active_ids)]

            # 5. Stock / Albaranes
            elif active_model == 'stock.picking':
                all_lines = records.mapped('move_ids')
                res['stock_move_ids'] = [(6, 0, all_lines.ids)]
            elif active_model == 'stock.move':
                res['stock_move_ids'] = [(6, 0, active_ids)]

            # 6. Asientos Contables (Account Move) -> Apuntes (Move Line)
            elif active_model == 'account.move':
                all_lines = records.mapped('line_ids')
                res['move_line_ids'] = [(6, 0, all_lines.ids)]
            elif active_model == 'account.move.line':
                res['move_line_ids'] = [(6, 0, active_ids)]

            # 7. Líneas Analíticas (Timesheets)
            elif active_model == 'account.analytic.line':
                res['analytic_line_ids'] = [(6, 0, active_ids)]

            # 8. Tareas
            elif active_model == 'project.task':
                res['task_ids'] = [(6, 0, active_ids)]

        return res

    @api.onchange('project_id')
    def _onchange_project_id(self):
        if self.project_id:
            self.task_id = False
            if not self.analytic_distribution and self.project_id.analytic_account_id:
                self.analytic_distribution = {
                    str(self.project_id.analytic_account_id.id): 100}

    def action_reclassify(self):
        """
        Ejecuta la reclasificación basada en las listas de trabajo pobladas en el wizard.
        """
        # 1. Tareas (solo si NO es merge)
        if self.task_ids and not self.merge_tasks:
            self._reclassify_tasks(self.task_ids)

        # 2. Compras
        if self.purchase_line_ids:
            self._reclassify_purchase_lines(self.purchase_line_ids)

        # 3. Compensaciones (Líneas)
        if self.compensation_line_ids:
            self._reclassify_compensation_lines(self.compensation_line_ids)

        # 4. Requisiciones
        if self.requisition_line_ids:
            self._reclassify_requisition_lines(self.requisition_line_ids)

        # 5. Gastos
        if self.expense_line_ids:
            self._reclassify_expenses(self.expense_line_ids)

        # 6. Stock Moves
        if self.stock_move_ids:
            self._reclassify_stock_moves(self.stock_move_ids)

        # 7. Apuntes Contables
        if self.move_line_ids:
            self._reclassify_account_move_lines(self.move_line_ids)

        # 8. Líneas Analíticas
        if self.analytic_line_ids:
            self._reclassify_analytic_lines(self.analytic_line_ids)

        # 9. Merge de tareas (al final, después de reclasificar documentos)
        if self.merge_tasks and self.task_id:
            self._merge_tasks_into_target()

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Reclasificación Completada'),
                'message': _('Los registros han sido reclasificados exitosamente.'),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.act_window_close'},
            }
        }

    # -------------------------------------------------------------------------
    # MÉTODO DE MERGE DE TAREAS
    # -------------------------------------------------------------------------

    def _merge_tasks_into_target(self):
        """
        Fusiona tareas origen en la tarea destino al final de la reclasificación.
        Solo se ejecuta si merge_tasks=True y hay una task_id destino.
        """
        if not self.task_id:
            raise UserError(_("Debe seleccionar una tarea destino para consolidar."))

        # Obtener tareas desde task_ids o desde contexto
        source_tasks = self.task_ids
        if not source_tasks:
            active_model = self.env.context.get('active_model')
            active_ids = self.env.context.get('active_ids', [])
            if active_model == 'project.task':
                source_tasks = self.env['project.task'].browse(active_ids)

        target_task = self.task_id

        # Filtrar: no fusionar la tarea destino consigo misma
        source_tasks = source_tasks - target_task

        if not source_tasks:
            return

        _logger.info("Iniciando merge de %d tareas en tarea destino: %s", len(source_tasks), target_task.name)

        source_task_ids = source_tasks.ids

        for task in source_tasks:
            # 1. Transferir timesheets (copiar a destino; los originales se eliminan con la tarea)
            for timesheet in task.timesheet_ids:
                timesheet.copy({
                    'task_id': target_task.id,
                    'project_id': target_task.project_id.id,
                })

            # 2. Transferir subtareas
            if task.child_ids:
                task.child_ids.write({'parent_id': target_task.id})

            # 3. Combinar tags
            new_tags = (task.tag_ids | target_task.tag_ids).ids
            if new_tags:
                target_task.write({'tag_ids': [(6, 0, new_tags)]})

            # 4. Suma de horas planificadas
            if task.allocated_hours:
                target_task.allocated_hours += task.allocated_hours

            # 5. Concatenar descripciones
            if task.description:
                current_desc = target_task.description or ''
                separator = '\n\n--- Fusionado desde: %s ---\n' % task.name
                target_task.description = current_desc + separator + task.description

            # 6. Mensaje en chatter
            msg = Markup(
                "<b>✅ Tarea fusionada:</b> %s<br/>"
                "<b>Proyecto origen:</b> %s<br/>"
                "<b>Responsables:</b> %s<br/>"
                "<b>Horas planificadas:</b> %.2f"
            ) % (
                task.name,
                task.project_id.name or 'N/A',
                ', '.join(task.user_ids.mapped('name')) or 'Ninguno',
                task.allocated_hours or 0.0
            )
            target_task.message_post(body=msg)

            _logger.info("Tarea %s fusionada en %s", task.name, target_task.name)

        # 7. REASIGNAR todos los registros con FK a task_id ANTES de eliminar las tareas.
        #    Esto evita errores de restricción de clave foránea (ej: compensation_line_task_id_fkey).
        self._reassign_task_dependencies(source_task_ids, target_task)

        # 8. Eliminar tareas origen
        task_names = ', '.join(source_tasks.mapped('name'))
        num_tasks = len(source_tasks)
        source_tasks.unlink()

        # 9. Mensaje final en tarea destino
        final_msg = Markup(
            "<b>🎯 Consolidación completada</b><br/>"
            "Se fusionaron %d tareas: %s"
        ) % (num_tasks, task_names)
        target_task.message_post(body=final_msg)

    def _reassign_task_dependencies(self, source_task_ids, target_task):
        """
        Reasigna todos los registros que tienen FK a las tareas origen hacia la tarea destino.
        Se ejecuta ANTES de unlink() para evitar errores de restricción de clave foránea en BD.
        """
        target_vals = {
            'task_id': target_task.id,
            'project_id': target_task.project_id.id,
        }

        # 1. Compensation Lines (required=True con FK en BD → causa el error)
        comp_lines = self.env['compensation.line'].sudo().search([
            ('task_id', 'in', source_task_ids)
        ])
        if comp_lines:
            comp_lines.write({
                'task_id': target_task.id,
                'project_id': target_task.project_id.id,
            })
            _logger.info("Reasignadas %d compensation.line a tarea %s", len(comp_lines), target_task.name)

        # 2. Líneas de Compra
        purchase_lines = self.env['purchase.order.line'].sudo().search([
            ('task_id', 'in', source_task_ids)
        ])
        if purchase_lines:
            purchase_lines.write(target_vals)
            _logger.info("Reasignadas %d purchase.order.line a tarea %s", len(purchase_lines), target_task.name)

        # 3. Stock Moves
        stock_moves = self.env['stock.move'].sudo().search([
            ('task_id', 'in', source_task_ids)
        ])
        if stock_moves:
            stock_moves.write(target_vals)
            _logger.info("Reasignados %d stock.move a tarea %s", len(stock_moves), target_task.name)

        # 4. Gastos
        expenses = self.env['hr.expense'].sudo().search([
            ('task_id', 'in', source_task_ids)
        ])
        if expenses:
            expenses.write(target_vals)
            _logger.info("Reasignados %d hr.expense a tarea %s", len(expenses), target_task.name)

        # 5. Líneas Analíticas / Timesheets que aún apunten a la tarea origen
        analytic_lines = self.env['account.analytic.line'].sudo().search([
            ('task_id', 'in', source_task_ids)
        ])
        if analytic_lines:
            analytic_lines.write(target_vals)
            _logger.info("Reasignadas %d account.analytic.line a tarea %s", len(analytic_lines), target_task.name)

        # 6. Requisiciones
        if 'requisition.order' in self.env:
            req_lines = self.env['requisition.order'].sudo().search([
                ('task_id', 'in', source_task_ids)
            ])
            if req_lines:
                req_lines.write(target_vals)
                _logger.info("Reasignadas %d requisition.order a tarea %s", len(req_lines), target_task.name)

    # -------------------------------------------------------------------------
    # HELPERS
    # -------------------------------------------------------------------------

    def _log_chatter(self, records):
        """Intenta dejar un mensaje en el chatter de los registros si soportan mail.thread"""
        msg = Markup("<b>%s</b><br/>%s: %s<br/>") % (
            _("Reclasificación"),
            _("Nuevo Proyecto"),
            self.project_id.name
        )

        if self.task_id:
            msg += Markup("%s: %s<br/>") % (_("Nueva Tarea"),
                                            self.task_id.name)

        if self.analytic_distribution:
            msg += Markup("%s: %s<br/>") % (_("Nueva Analítica"),
                                            _("Distribución Actualizada"))

        for record in records:
            if hasattr(record, 'message_post'):
                try:
                    record.message_post(body=msg)
                except Exception:
                    continue

    def _compute_new_distribution(self, current_dist):
        """
        Fusiona la distribución proporcionada por el usuario con la distribución actual basada en PLANES.
        """
        if not self.analytic_distribution:
            return current_dist or {}

        wizard_dist = self.analytic_distribution
        current_dist = current_dist or {}

        new_result = {}

        # Pre-fetch all involved accounts for plan checking
        wizard_account_ids = set()
        for key in wizard_dist.keys():
            parts = key.split(',')
            for p in parts:
                if p.isdigit():
                    wizard_account_ids.add(int(p))

        current_account_ids = set()
        for key in current_dist.keys():
            for p in key.split(','):
                if p.isdigit():
                    current_account_ids.add(int(p))

        all_accounts = self.env['account.analytic.account'].sudo().browse(
            list(current_account_ids | wizard_account_ids))
        plan_map = {acc.id: acc.plan_id.id for acc in all_accounts}

        wizard_accounts = self.env['account.analytic.account'].sudo().browse(
            list(wizard_account_ids))
        wizard_plans = {acc.plan_id.id for acc in wizard_accounts}

        def get_preserved_accounts(key_str):
            preserved = []
            for p in key_str.split(','):
                if p.isdigit():
                    aid = int(p)
                    if plan_map.get(aid) not in wizard_plans:
                        preserved.append(aid)
            return preserved

        for w_key, w_val in wizard_dist.items():
            w_accs = [int(x) for x in w_key.split(',') if x.isdigit()]
            w_pct = w_val

            for c_key, c_val in current_dist.items():
                preserved = get_preserved_accounts(c_key)
                combined = sorted(list(set(preserved + w_accs)))
                if not combined:
                    continue

                new_key = ",".join(str(x) for x in combined)
                new_pct = (c_val * w_pct) / 100.0
                new_result[new_key] = new_result.get(new_key, 0.0) + new_pct

        return {k: v for k, v in new_result.items() if v > 0.01}

    # -------------------------------------------------------------------------
    # LÓGICA ESPECÍFICA POR MODELO
    # -------------------------------------------------------------------------

    def _reclassify_tasks(self, tasks):
        """Reclasifica tareas (proyecto, tarea padre, analítica)"""
        vals = {}
        if self.project_id:
            vals['project_id'] = self.project_id.id
        if self.task_id:
            vals['parent_id'] = self.task_id.id

        if vals:
            tasks.write(vals)

        if self.analytic_distribution:
            # Extraer primera cuenta de distribución analítica
            first_account_id = None
            for key in self.analytic_distribution.keys():
                if ',' not in key and key.isdigit():
                    first_account_id = int(key)
                    break

            if first_account_id:
                for task in tasks:
                    # Actualizar timesheets de la tarea con la nueva cuenta analítica
                    if task.timesheet_ids:
                        task.timesheet_ids.write({'account_id': first_account_id})

        self._log_chatter(tasks)

    def _reclassify_purchase_lines(self, lines, skip_models=None):
        """Líneas de Compra: Proyecto, Tarea y Analítica + Cascada"""
        skip_models = skip_models or []
        skip_models.append('purchase.order.line')

        vals = {}
        if self.project_id:
            vals['project_id'] = self.project_id.id
        if self.task_id:
            vals['task_id'] = self.task_id.id

        if self.analytic_distribution:
            for line in lines:
                curr = dict(line.analytic_distribution or {})
                new_d = self._compute_new_distribution(curr)
                line.write({'analytic_distribution': new_d})

        if vals:
            lines.write(vals)

        # Sincronizar Cabecera
        unique_orders = lines.mapped('order_id')
        for order in unique_orders:
            valid_lines = order.order_line.filtered(
                lambda l: not l.display_type)
            if valid_lines:
                projects = valid_lines.mapped('project_id')
                tasks = valid_lines.mapped('task_id')

                header_vals = {}
                if len(projects) == 1:
                    header_vals['project_id'] = projects[0].id
                elif len(projects) > 1:
                    header_vals['project_id'] = False

                if len(tasks) == 1:
                    header_vals['task_order_id'] = tasks[0].id
                elif len(tasks) > 1:
                    header_vals['task_order_id'] = False

                if header_vals:
                    order.write(header_vals)

        self._log_chatter(unique_orders)

        # Cascada: Stock
        if 'stock.move' not in skip_models:
            moves = self.env['stock.move']
            if hasattr(lines, 'move_ids'):
                moves = lines.mapped('move_ids')
            else:
                moves = self.env['stock.move'].search([
                    ('purchase_line_id', 'in', lines.ids)])

            if moves:
                self._reclassify_stock_moves(moves, skip_models=skip_models)

        # Cascada: Facturas
        if 'account.move.line' not in skip_models:
            inv_lines = self.env['account.move.line'].search([
                ('purchase_line_id', 'in', lines.ids)
            ])
            if inv_lines:
                self._reclassify_account_move_lines(
                    inv_lines, skip_models=skip_models)

    def _reclassify_stock_moves(self, moves, skip_models=None):
        """Movimientos de Stock"""
        skip_models = skip_models or []
        skip_models.append('stock.move')

        vals = {}
        if self.project_id:
            vals['project_id'] = self.project_id.id
        if self.task_id:
            vals['task_id'] = self.task_id.id

        if vals:
            moves.write(vals)

        # Sincronizar Picking
        pickings = moves.mapped('picking_id')
        for picking in pickings:
            all_moves = picking.move_ids
            if all_moves:
                projects = all_moves.mapped('project_id')
                tasks = all_moves.mapped('task_id')

                header_vals = {}
                if len(projects) == 1:
                    header_vals['project_id'] = projects[0].id
                elif len(projects) > 1:
                    header_vals['project_id'] = False

                if len(tasks) == 1:
                    header_vals['task_id'] = tasks[0].id
                elif len(tasks) > 1:
                    header_vals['task_id'] = False

                if header_vals:
                    picking.write(header_vals)

    def _reclassify_analytic_lines(self, lines):
        """Hojas de Horas / Costos"""
        vals = {}
        if self.project_id:
            vals['project_id'] = self.project_id.id
        if self.task_id:
            vals['task_id'] = self.task_id.id

        if self.analytic_distribution:
            first_dist = self.analytic_distribution
            if first_dist:
                for key in first_dist.keys():
                    if ',' not in key and key.isdigit():
                        vals['account_id'] = int(key)
                        break

        if vals:
            lines.write(vals)

    def _reclassify_requisition_lines(self, lines):
        """Reclasifica Líneas de Requisición"""
        vals = {}
        if self.project_id:
            vals['project_id'] = self.project_id.id
        if self.task_id:
            vals['task_id'] = self.task_id.id

        if self.analytic_distribution:
            if 'analytic_distribution' in lines._fields:
                for line in lines:
                    curr = dict(line.analytic_distribution or {})
                    new_d = self._compute_new_distribution(curr)
                    line.write({'analytic_distribution': new_d})
            elif 'account_analytic_id' in lines._fields:
                first_dist = self.analytic_distribution
                if first_dist:
                    for key in first_dist.keys():
                        if ',' not in key and key.isdigit():
                            vals['account_analytic_id'] = int(key)
                            break

        if vals:
            lines.write(vals)

        unique_reqs = lines.mapped('requisition_id')
        self._log_chatter(unique_reqs)

    def _reclassify_account_move_lines(self, lines, skip_models=None):
        """Apuntes Contables"""
        skip_models = skip_models or []
        skip_models.append('account.move.line')

        if self.analytic_distribution:
            for line in lines:
                current_dist = dict(line.analytic_distribution or {})
                new_dist = self._compute_new_distribution(current_dist)
                line.write({'analytic_distribution': new_dist})
                line.invalidate_recordset(['analytic_distribution'])

                # Actualizar líneas analíticas vinculadas
                analytic_lines = self.env['account.analytic.line'].search([
                    ('move_line_id', '=', line.id)])

                if analytic_lines and len(new_dist) == 1:
                    key = list(new_dist.keys())[0]
                    if ',' not in key and key.isdigit():
                        analytic_lines.write({'account_id': int(key)})

        # Cascada: Purchase
        if 'purchase.order.line' not in skip_models:
            purchase_lines = lines.mapped('purchase_line_id')
            if purchase_lines:
                self._reclassify_purchase_lines(
                    purchase_lines, skip_models=skip_models)

        # Cascada: Expenses
        if 'hr.expense' not in skip_models and 'expense_id' in lines._fields:
            expenses = lines.mapped('expense_id')
            if expenses:
                self._reclassify_expenses(expenses, skip_models=skip_models)

    def _reclassify_compensation_lines(self, lines):
        """Líneas de Compensación"""
        vals = {}
        if self.project_id:
            vals['project_id'] = self.project_id.id
        if self.task_id:
            vals['task_id'] = self.task_id.id

        # Propagar a timesheets
        if vals or self.analytic_distribution:
            for line in lines:
                if not line.employee_id or not line.date:
                    continue

                domain = [
                    ('employee_id', '=', line.employee_id.id),
                    ('date', '=', line.date),
                ]
                if line.project_id:
                    domain.append(('project_id', '=', line.project_id.id))
                if line.task_id:
                    domain.append(('task_id', '=', line.task_id.id))

                timesheets = self.env['account.analytic.line'].search(domain)

                if timesheets:
                    ts_vals = vals.copy()
                    if self.analytic_distribution:
                        first_dist = self.analytic_distribution
                        if first_dist:
                            for key in first_dist.keys():
                                if ',' not in key and key.isdigit():
                                    ts_vals['account_id'] = int(key)
                                    break
                    if ts_vals:
                        timesheets.write(ts_vals)

        if vals:
            lines.write(vals)

        # Sincronizar Cabecera
        unique_reqs = lines.mapped('compensation_id')
        for req in unique_reqs:
            all_lines = req.compensation_line_ids
            if all_lines:
                projects = all_lines.mapped('project_id')
                header_vals = {}
                if len(projects) == 1:
                    header_vals['service'] = projects[0].id
                elif len(projects) > 1:
                    header_vals['service'] = False
                if header_vals:
                    req.write(header_vals)

        self._log_chatter(unique_reqs)

    def _reclassify_expenses(self, expenses, skip_models=None):
        """Gastos"""
        skip_models = skip_models or []
        skip_models.append('hr.expense')

        vals = {}
        if self.project_id:
            vals['project_id'] = self.project_id.id
        if self.task_id:
            vals['task_id'] = self.task_id.id

        if vals:
            expenses.sudo().write(vals)

        if self.analytic_distribution:
            for expense in expenses:
                current_dist = dict(expense.analytic_distribution or {})
                new_dist = self._compute_new_distribution(current_dist)
                expense.sudo().write({'analytic_distribution': new_dist})

        self._log_chatter(expenses)
        self._log_chatter(expenses.mapped('sheet_id'))

        # Cascada: Account Move Lines
        if 'account.move.line' not in skip_models:
            sheets = expenses.mapped('sheet_id')
            moves = sheets.account_move_ids
            move_lines = moves.line_ids.filtered(
                lambda l: l.expense_id in expenses)

            if move_lines:
                self._reclassify_account_move_lines(
                    move_lines, skip_models=skip_models)
