from odoo import fields, models, api,_
import logging

_logger = logging.getLogger(__name__)

class SaleOrder(models.Model):
    _inherit = 'sale.order'
    
    sproject_id = fields.Many2one('project.project', 'Proyecto', domain="[('sale_order_id.id', '=', id)]")
    
    # Este campo existía en ambos archivos. Se conserva este porque apunta al modelo correcto (project.sub.update)
    project_sub_updates = fields.One2many('project.sub.update', 'sale_order_id', string='Avances del Proyecto')

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
        tasks = self.env['project.task'].search([('sale_order_id', '=', self.id)])

        renamed_count = 0
        for task in tasks:
            # Solo renombrar si el nombre actual contiene el nombre del pendiente
            if self.pending_service_id and self.pending_service_id.name in task.name:
                old_name = task.name
                # Crear nuevo nombre con formato "Número Venta: Nombre Producto"
                # Buscar la línea de venta correspondiente
                sale_line = self.order_line.filtered(lambda l: l.product_id.name in task.name)
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
                    _logger.info(f"Tarea {task.id} renombrada: '{old_name}' -> '{new_name}'")

        if renamed_count > 0:
            _logger.info(f"Renombradas {renamed_count} tareas para la orden {self.name}")

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
