from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class PendingServiceMergeSelector(models.TransientModel):
    _name = 'pending.service.merge.selector'
    _description = 'Selector de Servicios para Fusión Directa'

    selected_service_ids = fields.Many2many(
        'pending.service',
        string='Servicios seleccionados',
        readonly=True,
    )
    servicio_o = fields.Many2one(
        'pending.service',
        string='Servicio Origen',
        required=True,
    )
    servicio_d = fields.Many2one(
        'pending.service',
        string='Servicio Destino',
        required=True,
    )
    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        active_ids = self.env.context.get('active_ids') or []
        if self.env.context.get('active_model') != 'pending.service':
            return res
        if len(active_ids) != 2:
            raise ValidationError(_('Debes seleccionar exactamente dos servicios pendientes.'))

        services = self.env['pending.service'].browse(active_ids).exists()
        if len(services) != 2:
            raise ValidationError(_('No se pudieron encontrar los dos servicios pendientes seleccionados.'))

        res['selected_service_ids'] = [(6, 0, services.ids)]
        res['servicio_o'] = services[0].id
        res['servicio_d'] = services[1].id
        return res

    @api.onchange('servicio_o')
    def _onchange_servicio_o(self):
        if self.servicio_o and self.servicio_o == self.servicio_d:
            other_service = self.selected_service_ids - self.servicio_o
            self.servicio_d = other_service[:1].id if other_service else False

    @api.onchange('servicio_d')
    def _onchange_servicio_d(self):
        if self.servicio_d and self.servicio_d == self.servicio_o:
            other_service = self.selected_service_ids - self.servicio_d
            self.servicio_o = other_service[:1].id if other_service else False

    def action_open_fusion_wizard(self):
        self.ensure_one()
        self._validate_selection()
        wizard = self.env['fusion.servicios.pendientes'].create({
            'servicio_o': self.servicio_o.id,
            'servicio_d': self.servicio_d.id,
            'proceso': 'fusion',
            'direct_merge_locked': True,
            'lineas_seleccion': self._prepare_fusion_line_commands(),
        })
        return self._action_open_fusion_wizard(wizard)

    def _prepare_fusion_line_commands(self):
        self.ensure_one()
        commands = []
        target_lines_by_product = {}
        for target_line in self.servicio_d.service_line_ids:
            target_lines_by_product.setdefault(target_line.product_id.id, self.env['pending.service.line'])
            target_lines_by_product[target_line.product_id.id] |= target_line

        target_product_ids = set(self.servicio_d.service_line_ids.mapped('product_id').ids)
        for line in self.servicio_o.service_line_ids.filtered(
            lambda item: item.quantity > 0 and item.product_id.id in target_product_ids
        ):
            candidate_lines = target_lines_by_product.get(
                line.product_id.id,
                self.env['pending.service.line'],
            )
            line_vals = {'linea_id': line.id}
            if len(candidate_lines) == 1:
                line_vals['linea_destino_id'] = candidate_lines.id
            commands.append((0, 0, line_vals))
        return commands

    def _action_open_fusion_wizard(self, wizard):
        return {
            'type': 'ir.actions.act_window',
            'name': _('Fusión directa'),
            'res_model': 'fusion.servicios.pendientes',
            'res_id': wizard.id,
            'view_mode': 'form',
            'view_id': self.env.ref(
                'project_modificaciones.fusion_servicios_pendientes_view_form'
            ).id,
            'target': 'new',
        }

    def _validate_selection(self):
        self.ensure_one()
        if len(self.selected_service_ids) != 2:
            raise ValidationError(_('Debes seleccionar exactamente dos servicios pendientes.'))
        if self.servicio_o not in self.selected_service_ids or self.servicio_d not in self.selected_service_ids:
            raise ValidationError(_('Origen y destino deben ser uno de los dos servicios seleccionados.'))
        if self.servicio_o == self.servicio_d:
            raise ValidationError(_('El servicio origen y destino no pueden ser el mismo.'))
        self.env['pending.merge.request']._check_no_active_request_for_services({
            'servicio_o': self.servicio_o.id,
            'servicio_d': self.servicio_d.id,
        })