from odoo import fields, models, api, _
from datetime import date as _date
from datetime import datetime
import logging

_logger = logging.getLogger(__name__)


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    # -------------------------------------------------------------------------
    # BASE SALE ORDER / CONTROL DE OBRA
    # Campos y comportamiento general de la OV dentro del modulo.
    # -------------------------------------------------------------------------
    sproject_id = fields.Many2one(
        'project.project', 'Proyecto', domain="[('sale_order_id.id', '=', id)]")

    # Este campo existía en ambos archivos. Se conserva este porque apunta al modelo correcto (project.sub.update)
    project_sub_updates = fields.One2many(
        'project.sub.update', 'sale_order_id', string='Avances del Proyecto')

    serv_assig = fields.Selection(
        [('assig', 'Con OS'),
         ('no_assig', 'Sin OS')],
        string='Estatus de servicio',
        required=True, tracking=True, default='no_assig')

    locked_positions = fields.Boolean(compute="_compute_locked_positions")

    @api.depends("state")
    def _compute_locked_positions(self):
        for record in self:
            record.locked_positions = record.state != "draft"

    def action_confirm(self):
        self.recompute_positions()
        return super().action_confirm()

    def action_quotation_send(self):
        self.recompute_positions()
        return super().action_quotation_send()

    def recompute_positions(self):
        """Recompute positions of all lines (including sections/notes) and update names with prefix"""
        for sale in self:
            if sale.locked_positions:
                continue
            # Modified: Do not filter by display_type, include all
            lines = sale.order_line
            lines = lines.sorted(key=lambda x: (x.sequence, x.id))
            for position, line in enumerate(lines, start=1):
                # Update position
                if line.position != position:
                    line.position = position

                # Update name with prefix P01, P02...
                prefix = f"P{position:02d} "
                if line.name:
                    import re
                    # Remove existing prefix if matched to avoid duplication P01 Name or [1] Name (handling legacy)
                    # Regex to remove both [N] and PNN styles at start
                    # r'^(\[\d+\]|P\d+)\s+'
                    current_name = re.sub(r'^(\[\d+\]|P\d+)\s+', '', line.name)
                    new_name = prefix + current_name
                    if line.name != new_name:
                        line.name = new_name

    origen_id = fields.Many2one(
        'sale.order.origen',
        string='Origen',
        help='Especificar área que emite la orden',
        required=False,
        tracking=True,
    )

    dest_id = fields.Many2one(
        'sale.order.destino',
        string='Destino',
        help='Especificar el uso que se le da a la orden',
        required=False,
        tracking=True,
    )

    incidencia = fields.Many2one(
        'sale.order.incidencia',
        string='Incidencia',
        tracking=True
    )

    name = fields.Char(
        string="Order Reference",
        required=True,
        copy=False,
        readonly=False,
        index="trigram",
        default=False,
    )

    pending_service_id = fields.Many2one(
        'pending.service',
        string="Servicio Pendiente",
        help="Servicio pendiente que originó esta orden de venta. Si está asignado, las tareas existentes del servicio se asociarán en lugar de crear nuevas."
    )

    # Smart button para servicio pendiente
    def action_view_pending_service(self):
        self.ensure_one()
        if not self.pending_service_id:
            return
        return {
            'type': 'ir.actions.act_window',
            'name': _('Servicio Pendiente'),
            'res_model': 'pending.service',
            'res_id': self.pending_service_id.id,
            'view_mode': 'form',
            'target': 'current',
        }

    # -------------------------------------------------------------------------
    # SUPERVISOR DE OBRA — Campo computado para mostrar en tarjeta Kanban
    # Lee el campo 'supervisor' del proyecto vinculado a la orden.
    # No modifica user_id ni ningún campo nativo de sale.order.
    # -------------------------------------------------------------------------
    supervisor_obra = fields.Many2one(
        'hr.employee',
        string='Supervisor de Obra',
        compute='_compute_supervisor_obra',
        store=True,
        help="Supervisor asignado al proyecto de obra vinculado a esta orden de venta.",
    )

    @api.depends('project_ids', 'project_ids.supervisor')
    def _compute_supervisor_obra(self):
        """Lee el supervisor del primer proyecto de obra vinculado a la orden."""
        for order in self:
            # project_ids es Many2many computado — tomamos el primero con supervisor
            project = order.project_ids.filtered(lambda p: p.supervisor)[:1]
            order.supervisor_obra = project.supervisor if project else False

    project_ids = fields.Many2many(
        "project.project",
        compute="_compute_project_ids",
        store=True,
        compute_sudo=True,
    )

    project_count = fields.Integer(
        string='Proyectos',
        compute='_compute_project_ids',
        store=True,
        compute_sudo=True,
    )

    # Método que extiende la confirmación de la orden de venta.
    def _action_confirm(self):
        """
        Solo inyectamos el nombre en el contexto para que _prepare_task_values lo use.
        Dejamos que Odoo estándar cree la tarea en el proyecto 'VENTAS OBRAS' (configuración del producto).
        """
        for order in self:
            # Poner nombre actual en el contexto (antes de que Odoo lo bloquee/formatee)
            order = order.with_context(task_name_from_context=order.name)
            super(SaleOrder, order)._action_confirm()

            # Después de confirmar, renombrar tareas que vengan de pendientes
            if order.pending_service_id:
                order._rename_tasks_from_pending()
        return True

    def _rename_tasks_from_pending(self):
        """Renombrar tareas que provienen de un servicio pendiente"""
        self.ensure_one()

        # Buscar todas las tareas relacionadas con esta orden de venta
        tasks = self.env['project.task'].search(
            [('sale_order_id', '=', self.id)])

        renamed_count = 0
        for task in tasks:
            # Solo renombrar si el nombre actual contiene el nombre del pendiente
            if self.pending_service_id and self.pending_service_id.name in task.name:
                old_name = task.name
                # Crear nuevo nombre con formato "Número Venta: Nombre Producto"
                # Buscar la línea de venta correspondiente
                sale_line = self.order_line.filtered(
                    lambda l: l.product_id.name in task.name)
                if sale_line:
                    new_name = f"{self.name}: {sale_line[0].name}"
                else:
                    # Si no encontramos la línea específica, usar el primer producto
                    new_name = f"{self.name}: {self.order_line[0].name if self.order_line else 'Producto'}"

                # Solo actualizar si hay cambio
                if new_name != old_name:
                    task.write({'name': new_name})
                    renamed_count += 1

                    # Log para debugging
                    _logger.info(
                        f"Tarea {task.id} renombrada: '{old_name}' -> '{new_name}'")

        if renamed_count > 0:
            _logger.info(
                f"Renombradas {renamed_count} tareas para la orden {self.name}")

    # Botón inteligente de proyecto (Dinámico)
    def action_view_project_ids(self):
        """
        Abre la vista de proyectos relacionados. 
        Si hay más de uno, muestra lista. Si hay uno, muestra formulario.
        Prioriza project_ids (calculado desde líneas) sobre project_id (cabecera).
        """
        self.ensure_one()

        # Recopilar todos los proyectos posibles (Cabecera + Tareas)
        projects = self.project_ids | self.project_id

        if not projects:
            return {
                'type': 'ir.actions.act_window_close'
            }

        if len(projects) > 1:
            return {
                "type": "ir.actions.act_window",
                "name": "Proyectos",
                "res_model": "project.project",
                "view_mode": "tree,form",
                "domain": [('id', 'in', projects.ids)],
                # Evitar crear proyectos sueltos desde aquí
                "context": {'create': False},
                "target": "current",
            }
        else:
            # Solo un proyecto, abrimos directo
            project = projects[0]
            return {
                "type": "ir.actions.act_window",
                "name": "Proyecto",
                "res_model": "project.project",
                "view_mode": "form",
                "res_id": project.id,
                "target": "current",
            }

    @api.depends('order_line.task_id.project_id', 'project_id')
    def _compute_project_ids(self):
        for order in self:
            projects = order.order_line.mapped("task_id.project_id")
            order.project_ids = projects

            # Logic merged from the old _compute_project_count
            # Correction: Count ALL unique projects (Lines + Header)
            all_projects = projects | order.project_id
            order.project_count = len(all_projects)

    # -------------------------------------------------------------------------
    # PROJECT CONTROL BOARD / KANBAN OPERATIVO
    # Todo lo siguiente alimenta semaforos, supervisor, etapas, fechas y
    # metricas consumidas por el tablero unificado y la vista kanban.
    # -------------------------------------------------------------------------
    priority = fields.Selection(
        selection=[
            ('0', 'Normal'),
            ('1', 'Media'),
            ('2', 'Alta'),
            ('3', 'Urgente'),
        ],
        string='Prioridad',
        default='0',
        tracking=True,
        help="Identifica órdenes críticas en la vista Kanban.",
    )

    # ---------------------------------------------------------------------------
    # Fechas calculadas (store=False — se recalculan en vivo cada carga)
    # Usan date_order (inicio) y commitment_date (fin planeado) que ya existen.
    # ---------------------------------------------------------------------------
    delay_days = fields.Integer(
        string='Días de Retraso',
        compute='_compute_sale_kanban_dates',
        store=False,
        help="Días transcurridos desde commitment_date hasta hoy (solo si hay retraso).",
    )

    date_end_actual = fields.Date(
        string='Fecha Actual (Estimada)',
        compute='_compute_sale_kanban_dates',
        store=False,
        help="Si hay retraso respecto a commitment_date muestra hoy; si no, muestra commitment_date.",
    )

    @api.depends('commitment_date', 'state', 'avance_actual')
    def _compute_sale_kanban_dates(self):
        today = _date.today()
        for rec in self:
            end_plan = rec.commitment_date.date() if isinstance(
                rec.commitment_date, datetime) else rec.commitment_date
            if not end_plan:
                rec.date_end_actual = today
                rec.delay_days = 0
                continue

            # Si tiene retraso pero ya está terminado (avance >= 100 o estado final), no suma días.
            if end_plan < today and rec.state not in ('cancel', 'done') and rec.avance_actual < 100.0:
                rec.delay_days = (today - end_plan).days
                rec.date_end_actual = today
            else:
                rec.delay_days = 0
                rec.date_end_actual = end_plan

    # ---------------------------------------------------------------------------
    # Avance planeado (store=False — depende de la fecha del día)
    # Calcula (hoy − date_order) / (commitment_date − date_order) × 100
    # ---------------------------------------------------------------------------
    avance_planeado = fields.Float(
        string='Avance Planeado (%)',
        compute='_compute_avance_planeado',
        store=False,
        digits=(5, 2),
        help="(Hoy − Fecha Inicio) / (Entrega Comprometida − Fecha Inicio) × 100",
    )

    # ---------------------------------------------------------------------------
    # Avance físico real (store=True — se recalcula cuando cambian los avances)
    # Usa project_sub_updates que ya existe en el modelo como One2many.
    # ---------------------------------------------------------------------------
    avance_actual = fields.Float(
        string='Avance Físico Real (%)',
        compute='_compute_progress_metrics',
        store=True,
        digits=(5, 2),
        help="Σ unit_progress / Σ quant_total × 100 de los avances vinculados.",
    )

    # ---------------------------------------------------------------------------
    # Avance facturado (store=True — facturas emitidas / monto total orden × 100)
    # Usa invoice_ids estándar de sale.order.
    # ---------------------------------------------------------------------------
    avance_facturado = fields.Float(
        string='Avance Facturado (%)',
        compute='_compute_progress_metrics',
        store=True,
        digits=(5, 2),
        help="Σ monto facturas publicadas / amount_total × 100.",
    )

    # ---------------------------------------------------------------------------
    # Semáforo Kanban (store=True — depende de avance_actual y fechas)
    # Verde: En tiempo · Ámbar: retraso < 10% · Rojo: retraso ≥ 10% o fecha vencida
    # ---------------------------------------------------------------------------
    kanban_color_sale = fields.Selection(
        selection=[
            ('green', 'Verde  — En tiempo o adelantado'),
            ('amber', 'Ámbar  — Retraso menor al 10%'),
            ('red',   'Rojo   — Retraso crítico o fecha vencida'),
        ],
        string='Semáforo',
        compute='_compute_progress_metrics',
        store=True,
        help="Verde: avance real ≥ planeado · Ámbar: brecha < 10% · Rojo: brecha ≥ 10% o fecha vencida.",
    )

    task_done_count = fields.Integer(
        string='Tareas Completadas',
        compute='_compute_sale_task_done_count',
        store=True,
        help="Cantidad de tareas en estado 'Done' de las líneas de esta orden.",
    )

    @api.depends('order_line.task_id', 'order_line.task_id.state')
    def _compute_sale_task_done_count(self):
        done_state = '1_done'
        for rec in self:
            tasks = rec.order_line.mapped('task_id')
            rec.task_done_count = len(tasks.filtered(
                lambda t: t.state == done_state))

    def _get_progress_metrics_values(self):
        today = fields.Date.today()
        from datetime import datetime

        values_by_order = {}
        for order in self:
            lines = order.order_line.filtered(lambda l: not l.display_type)
            total_qty = sum(lines.mapped('product_uom_qty'))
            updates = order.project_sub_updates
            total_prog = sum(updates.mapped('unit_progress')) if updates else 0.0

            if total_qty > 0:
                valor_fisico = float(total_prog * 100) / float(total_qty)
                avance_actual = round(valor_fisico, 2)
            else:
                avance_actual = 0.0

            start_date = order.date_order
            if start_date and hasattr(start_date, 'date'):
                start_date = start_date.date()

            end_date = order.commitment_date
            if end_date and isinstance(end_date, datetime):
                end_date = end_date.date()

            if start_date and end_date and start_date <= end_date:
                total_days = (end_date - start_date).days
                if total_days > 0:
                    days_passed = (today - start_date).days
                    if days_passed <= 0:
                        avance_planeado = 0.0
                    elif days_passed >= total_days:
                        avance_planeado = 100.0
                    else:
                        valor_planeado = float(
                            days_passed * 100) / float(total_days)
                        avance_planeado = round(valor_planeado, 2)
                else:
                    avance_planeado = 100.0 if today >= end_date else 0.0
            else:
                avance_planeado = 0.0

            if total_qty > 0:
                total_invoiced = sum(lines.mapped('qty_invoiced'))
                total_entregado = sum(lines.mapped('qty_delivered'))
                if total_entregado > 0:
                    fact_pct = float(total_invoiced * 100) / \
                        float(total_entregado)
                    avance_facturado = round(min(100.0, fact_pct), 2)
                else:
                    avance_facturado = 0.0
            else:
                avance_facturado = 0.0

            if order.state in ['done', 'cancel'] or avance_actual >= 100.0:
                kanban_color_sale = 'green'
            elif end_date and today > end_date:
                kanban_color_sale = 'red'
            else:
                diff = avance_planeado - avance_actual
                if diff <= 0:
                    kanban_color_sale = 'green'
                elif diff < 10.0:
                    kanban_color_sale = 'amber'
                else:
                    kanban_color_sale = 'red'

            values_by_order[order.id] = {
                'avance_planeado': avance_planeado,
                'avance_actual': avance_actual,
                'avance_facturado': avance_facturado,
                'kanban_color_sale': kanban_color_sale,
            }

        return values_by_order

    @api.depends('date_order', 'commitment_date')
    def _compute_avance_planeado(self):
        values_by_order = self._get_progress_metrics_values()
        for order in self:
            order.avance_planeado = values_by_order[order.id]['avance_planeado']

    @api.depends(
        'date_order',
        'commitment_date',
        'state',
        'order_line.product_uom_qty',
        'order_line.qty_invoiced',
        'order_line.qty_delivered',
        'project_sub_updates.unit_progress'
    )
    def _compute_progress_metrics(self):
        values_by_order = self._get_progress_metrics_values()
        for order in self:
            values = values_by_order[order.id]
            order.avance_actual = values['avance_actual']
            order.avance_facturado = values['avance_facturado']
            order.kanban_color_sale = values['kanban_color_sale']

            # Días de Retraso se calculan en _compute_sale_kanban_dates

class Origen(models.Model):
    _name = 'sale.order.origen'
    _description = 'Orígenes de órdenes de venta'
    _order = 'name asc'

    name = fields.Char(string='Nombre', required=True, translate=True)
    color = fields.Integer(string='Color Index')
    active = fields.Boolean(string='Activo', default=True)

    _sql_constraints = [
        ('name_uniq', 'unique (name)', 'El nombre del origen debe ser único!'),
    ]


class Destino(models.Model):
    _name = 'sale.order.destino'
    _description = 'Destinos de órdenes de venta'
    _order = 'name asc'

    name = fields.Char(string='Nombre', required=True, translate=True)
    color = fields.Integer(string='Color Index')
    active = fields.Boolean(string='Activo', default=True)

    _sql_constraints = [
        ('name_uniq', 'unique (name)', 'El nombre del destino debe ser único!'),
    ]


class Incidencia(models.Model):
    _name = 'sale.order.incidencia'
    _description = 'Incidencias en órdenes de venta'
    _order = 'name asc'

    name = fields.Char(string='Nombre', required=True, translate=True)
    color = fields.Integer(string='Color Index')
    active = fields.Boolean(string='Activo', default=True)

    _sql_constraints = [
        ('name_uniq', 'unique (name)', 'El nombre de la incidencia debe ser único!'),
    ]
