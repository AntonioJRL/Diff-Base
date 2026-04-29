from odoo import fields, models, api, _
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)


class AsignarAvancesProjectWizard(models.TransientModel):
    _name = 'asignar.avances.project.wizard'
    _description = 'Wizard para gestión de avances de proyecto con dos pasos'

    # --- CAMPOS DEL WIZARD ---
    state = fields.Selection([('selection', 'Selección'), ('confirmation', 'Confirmación')], string='Estado',
                             default='selection', readonly=True)
    project_id = fields.Many2one('project.project', string='Proyecto',
                                 default=lambda self: self._get_default_project_id(), readonly=True)
    update_id = fields.Many2one('project.update', string='Actualización',
                                default=lambda self: self._get_default_update_id(), readonly=True)
    project_partner_id = fields.Many2one('res.partner', string='Cliente', domain="[('id', 'in', allowed_partner_ids)]")
    allowed_partner_ids = fields.Many2many(
        'res.partner',
        string='Clientes Permitidos',
        compute='_compute_allowed_partner_ids'
    )

    @api.depends('project_id')
    def _compute_allowed_partner_ids(self):
        for wizard in self:
            if wizard.project_id:
                # Obtiene todos los clientes de las SO de las tareas del proyecto
                partner_ids = self.env['project.task'].search([
                    ('project_id', '=', wizard.project_id.id)
                ]).mapped('sale_line_id.order_id.partner_id').ids

                wizard.allowed_partner_ids = [(6, 0, partner_ids)]
            else:
                wizard.allowed_partner_ids = False

    available_sale_order_ids = fields.Many2many('sale.order', compute='_compute_available_sale_order_ids')
    sale_order_id = fields.Many2one('sale.order', string='Guía: Pedido de Venta', required=True,
                                    domain="[('id', 'in', available_sale_order_ids),('order_line.task_id.is_complete', '=', False)]")
    sub_update_id = fields.Many2many('project.sub.update', string='Avances Disponibles',
                                     domain="[('avances_state', '=', 'confirmed'), ('producto', 'in', available_product_ids)]")
    available_product_ids = fields.Many2many('product.product', compute='_compute_available_product_ids')
    avances_a_confirmar_ids = fields.Many2many('project.sub.update', 'wizard_avances_confirm_rel',
                                               string="Resumen de Avances a Asignar", readonly=True)

    # --- MÉTODOS POR DEFECTO Y COMPUTADOS ---
    @api.model
    def _get_default_project_id(self):
        if self.env.context.get('active_model') == 'project.update' and self.env.context.get('active_id'):
            return self.env['project.update'].browse(self.env.context.get('active_id')).project_id.id
        return self.env.context.get('default_project_id', False)

    @api.model
    def _get_default_update_id(self):
        return self.env.context.get('default_update_id')

    @api.depends('project_id', 'sale_order_id')
    def _compute_available_product_ids(self):
        for wizard in self:
            # 1. Si no hay proyecto o no hay orden de venta, no hay productos disponibles.
            if not wizard.project_id or not wizard.sale_order_id:
                wizard.available_product_ids = False
                continue

            # 2. Buscar tareas que pertenezcan al proyecto Y estén relacionadas con la SO seleccionada
            tasks = self.env['project.task'].search([
                ('project_id', '=', wizard.project_id.id),
                ('sale_line_id.order_id', '=', wizard.sale_order_id.id)  # Filtro por la SO seleccionada
            ])

            # 3. Mapear los productos de las líneas de venta de esas tareas
            product_ids = tasks.mapped('sale_line_id.product_id').ids

            # 4. Asignar los IDs de los productos al campo
            if product_ids:
                wizard.available_product_ids = [(6, 0, product_ids)]
            else:
                wizard.available_product_ids = False

    @api.depends('project_id', 'project_partner_id')
    def _compute_available_sale_order_ids(self):
        for wizard in self:
            # 1. Condición de existencia: No hagas nada si no hay proyecto O cliente
            if not wizard.project_id or not wizard.project_partner_id:
                wizard.available_sale_order_ids = False
                continue

            # 2. Lógica para buscar tareas relacionadas con el proyecto
            tasks = self.env['project.task'].search([('project_id', '=', wizard.project_id.id)])

            # 3. Lógica para filtrar las Órdenes de Venta.
            #    Asumo que las Órdenes de Venta se encuentran por el nombre de la tarea (convención " - ").
            sale_order_names = {p.strip() for t in tasks if t.name and ' - ' in t.name for p in t.name.split(' - ', 1)
                                if p.strip()}

            if sale_order_names:
                # 4. FILTRAR POR NOMBRE Y POR CLIENTE SELECCIONADO
                sale_orders = self.env['sale.order'].search([
                    ('name', 'in', list(sale_order_names)),
                    ('partner_id', '=', wizard.project_partner_id.id)  # ¡Filtro clave!
                ])
                wizard.available_sale_order_ids = [(6, 0, sale_orders.ids)]
            else:
                wizard.available_sale_order_ids = False

    # --- ACCIONES DEL WIZARD ---
    def action_prepare_assignment(self):
        self.ensure_one()
        if not self.sub_update_id:
            raise UserError(_("Por favor, seleccione al menos un avance."))

        avances_validos = self.env['project.sub.update']
        avances_invalidos_msg = []
        for avance in self.sub_update_id:
            
            # Si por alguna razón el avance tiene una tarea NO aprobada, no dejar asignar
            if avance.task_id and avance.task_id.is_control_obra and avance.task_id.approval_state != 'approved':
                 raise UserError(_(
                    "El avance '%s' está vinculado a una tarea NO aprobada (%s). "
                    "No se puede asignar a una Orden de Venta hasta que la tarea origen sea regularizada."
                 ) % (avance.name, avance.task_id.name))
            
            task = self._find_task_by_direct_relations(avance.producto) or self._find_task_by_internal_reference(
                avance.producto)
            if task:
                avances_validos |= avance
            else:
                avances_invalidos_msg.append(f"● {avance.display_name} (Producto: {avance.producto.name or 'N/A'})")

        if avances_invalidos_msg:
            raise UserError(
                _("Error de Validación: No se encontró una tarea correspondiente para los siguientes avances:\n%s") % '\n'.join(
                    avances_invalidos_msg))

        self.write({'avances_a_confirmar_ids': [(6, 0, avances_validos.ids)], 'state': 'confirmation'})
        return {'type': 'ir.actions.act_window', 'res_model': self._name, 'res_id': self.id, 'view_mode': 'form',
                'target': 'new'}

    def action_back_to_selection(self):
        self.ensure_one()
        self.write({'state': 'selection', 'avances_a_confirmar_ids': [(5, 0, 0)]})
        return {'type': 'ir.actions.act_window', 'res_model': self._name, 'res_id': self.id, 'view_mode': 'form',
                'target': 'new'}

    def action_confirm_assignment(self):
        self.ensure_one()
        _logger.info(f"Confirmando asignación para {len(self.avances_a_confirmar_ids)} avances.")

        old_pend_tasks = self.env['project.task']
        
        # 1. Creamos un conjunto para guardar las tareas que fueron tocadas
        affected_tasks = self.env['project.task'] 

        for avance in self.avances_a_confirmar_ids:
            old_task = avance.task_id
            task = self._find_task_by_direct_relations(avance.producto) or self._find_task_by_internal_reference(
                avance.producto)

            if task:
                # 2. Agregamos la tarea destino a la lista de afectadas
                affected_tasks |= task 

                # IDs nuevos para nuevo destino de las hojas de horas
                new_project_id = self.project_id.id
                new_task_id = task.id

                avance.write({
                    'project_id': self.project_id.id,
                    'task_id': task.id,
                    'update_id': self.update_id.id,
                    'avances_state': 'assigned',
                    'sale_order_id': self.sale_order_id.id
                })

                # Logica para migrar gastos, compras.
                if old_task and old_task.id != task.id and 'PEND' in old_task.project_id.name:
                    _logger.info(f"Migrando datos de la tarea PEND '{old_task.name}' a '{task.name}'.")
                    avance._migrate_related_records(old_task.id, task.id)
                    old_pend_tasks |= old_task
        
        # 3. Guardamos los cambios en Base de Datos antes de recalcular
        # Esto es CRUCIAL para que el .search() dentro de la tarea encuentre los nuevos avances
        self.env.flush_all() 

        # 4. Forzamos el recálculo de los totales en todas las tareas afectadas
        for t in affected_tasks:
            t._units()             # Recalcula piezas entregadas (suma total)
            t._progress()          # Recalcula porcentaje de avance
            t._is_complete()       # Verifica si se completó la tarea

        if self.avances_a_confirmar_ids:
            # Usamos with_context para pasar la señal y desactivar la lógica del 'write' de project.update
            self.update_id.with_context(wizard_assigning=True).write({
                'sub_update_ids': [(4, avance.id) for avance in self.avances_a_confirmar_ids]
            })

        # Forzamos la actualización del caché para asegurar que el search_count sea correcto
        self.avances_a_confirmar_ids.flush_recordset()

        # Revisamos y eliminamos las tareas PEND que hayan quedado vacías
        for pend_task in old_pend_tasks:
            if not self.env['project.sub.update'].search_count([('task_id', '=', pend_task.id)]):
                _logger.info(
                    f"La tarea PEND '{pend_task.name}' (ID: {pend_task.id}) ha quedado vacía y será eliminada.")
                pend_task.unlink()

        return {'type': 'ir.actions.act_window_close'}

    # --- MÉTODOS DE BÚSQUEDA ---
    def _find_task_by_direct_relations(self, product):
        tasks = self.env['project.task'].search([
            ('project_id', '=', self.project_id.id),
            ('sale_line_id.order_id', '=', self.sale_order_id.id),
            ('sale_line_id.product_id', '=', product.id)], limit=1)
        if tasks: return tasks
        tasks = self.env['project.task'].search([
            ('project_id', '=', self.project_id.id),
            ('sale_line_id.product_id', '=', product.id)], limit=1)
        return tasks

    def _find_task_by_internal_reference(self, product):
        if product.default_code:
            return self.env['project.task'].search([
                ('project_id', '=', self.project_id.id),
                ('name', 'ilike', product.default_code)], limit=1)
        return False