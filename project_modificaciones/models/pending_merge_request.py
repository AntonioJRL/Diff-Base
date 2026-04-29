from odoo import api, fields, models, _
from odoo.exceptions import AccessError, ValidationError


class PendingMergeRequest(models.Model):
    _name = 'pending.merge.request'
    _description = 'Solicitud de Operación de Servicios Pendientes'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'create_date desc'

    name = fields.Char(
        string='Referencia',
        default=lambda self: _('Nueva Solicitud'),
        readonly=True,
        copy=False,
        tracking=True,
    )
    state = fields.Selection(
        selection=[
            ('draft', 'Borrador'),
            ('submitted', 'En aprobación'),
            ('approved', 'Ejecutada'),
            ('rejected', 'Rechazada'),
        ],
        string='Estado',
        default='draft',
        required=True,
        tracking=True,
    )
    servicio_o = fields.Many2one(
        'pending.service',
        string='Servicio Origen',
        required=True,
        tracking=True,
    )
    servicio_d = fields.Many2one(
        'pending.service',
        string='Servicio Destino',
        tracking=True,
    )
    proceso = fields.Selection(
        selection=[
            ('reasignacion', 'Reasignación'),
            ('fusion', 'Fusión'),
        ],
        string='Tipo de Proceso',
        default='fusion',
        required=True,
        tracking=True,
        help=(
            "Indica si se realizará una reasignación o una fusión entre servicios pendientes. \n"
            "Reasignación: se usa cuando solo se desea mover una o varias partidas a otro pendiente. \n"
            "Fusión: se usa cuando se desea integrar un pendiente completo dentro de otro, "
            "conservando el seguimiento de sus partidas, tareas y avances relacionados."
        )
    )
    modo_reasignacion = fields.Selection(
        selection=[
            ('todo', 'Todo'),
            ('por_linea', 'Por Línea'),
        ],
        string='Modo de Reasignación',
        default='todo',
        required=True,
        tracking=True,
        help=(
            "Indica en qué modo se ejecutará la reasignación solicitada. \n"
            "Todo: Todas las partidas del servicio serán reasignadas a un único servicio pendiente destino. \n"
            "Por Línea: Cada partida podrá ser reasignada a un servicio pendiente destino diferente."
        )
    )
    request_reason = fields.Text(
        string='Motivo de la Solicitud',
        tracking=True,
        required=True,
        help=(
            "Describe el motivo por el cual se está solicitando esta operación. \n"
            "Esta información ayuda a justificar y dar seguimiento a la solicitud."
        )
    )
    total_lineas_origen = fields.Integer(
        string='Líneas Origen',
        compute='_compute_transfer_summary',
    )
    total_lineas_transferibles = fields.Integer(
        string='Líneas Transferibles',
        compute='_compute_transfer_summary',
    )
    total_lineas_compatibles = fields.Integer(
        string='Líneas Compatibles',
        compute='_compute_transfer_summary',
    )
    requester_id = fields.Many2one(
        'res.users',
        string='Solicitante',
        default=lambda self: self.env.user,
        readonly=True,
        tracking=True,
    )
    approver_id = fields.Many2one(
        'res.users',
        string='Aprobador',
        readonly=True,
        tracking=True,
    )
    notify_user_id = fields.Many2one(
        'res.users',
        string='Usuario a Notificar',
        default=lambda self: self._default_notify_user(),
        tracking=True,
    )
    approved_date = fields.Datetime(
        string='Fecha de Aprobación',
        readonly=True,
    )
    rejected_date = fields.Datetime(
        string='Fecha de Rechazo',
        readonly=True,
    )
    rejection_reason = fields.Text(
        string='Motivo de Rechazo',
        tracking=True,
    )

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        active_id = self.env.context.get('active_id')
        if self.env.context.get('active_model') == 'pending.service' and active_id:
            res.setdefault('servicio_o', active_id)
        return res

    @api.model
    def _default_notify_user(self):
        return self._get_merge_approver_users(limit=1)

    @api.model
    def _get_merge_approver_users(self, limit=None):
        approver_group = self.env.ref(
            'project_modificaciones.group_pending_service_merge_approver',
            raise_if_not_found=False,
        )
        if not approver_group:
            return self.env['res.users']
        return self.env['res.users'].search([
            ('groups_id', 'in', approver_group.id),
            ('share', '=', False),
            ('active', '=', True),
        ], limit=limit)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            self._check_protected_values(vals)
            self._check_no_active_request_for_services(vals)
            vals['requester_id'] = self.env.user.id
            if vals.get('name', _('Nueva Solicitud')) == _('Nueva Solicitud'):
                vals['name'] = self.env['ir.sequence'].next_by_code('pending.merge.request') or _('Nueva Solicitud')
        return super().create(vals_list)

    def write(self, vals):
        is_approver = self.env.user.has_group('project_modificaciones.group_pending_service_merge_approver')
        if not is_approver:
            editable_requests = self.filtered(lambda request: request.state == 'draft')
            if len(editable_requests) != len(self):
                raise AccessError(_('Solo puedes modificar solicitudes en borrador.'))
            if vals.get('state') and vals['state'] not in ('draft', 'submitted'):
                raise AccessError(_('No tienes permisos para cambiar la solicitud a ese estado.'))
        self._check_protected_values(vals)
        should_check_duplicates = (
            {'servicio_o', 'servicio_d'}.intersection(vals)
            and vals.get('state') not in ('approved', 'rejected')
        )
        if should_check_duplicates:
            for request in self:
                check_vals = {
                    'servicio_o': vals.get('servicio_o', request.servicio_o.id),
                    'servicio_d': vals.get('servicio_d', request.servicio_d.id),
                }
                request._check_no_active_request_for_services(check_vals)
        return super().write(vals)

    def _active_request_states(self):
        return ['draft', 'submitted']

    def _check_no_active_request_for_services(self, vals):
        service_ids = [
            service_id
            for service_id in (vals.get('servicio_o'), vals.get('servicio_d'))
            if service_id
        ]
        if not service_ids:
            return

        domain = [
            ('state', 'in', self._active_request_states()),
            '|',
            ('servicio_o', 'in', service_ids),
            ('servicio_d', 'in', service_ids),
        ]
        if self.ids:
            domain.append(('id', 'not in', self.ids))

        blocking_request = self.sudo().search(domain, limit=1)
        if not blocking_request:
            return

        service_names = ', '.join(
            self.env['pending.service'].browse(service_ids).mapped('display_name')
        )
        raise ValidationError(_(
            "No se puede crear o modificar la solicitud porque el pendiente %(services)s "
            "ya participa en la solicitud %(request)s con estado '%(state)s'. "
            "Solo se puede generar una nueva solicitud cuando la anterior fue rechazada, "
            "cancelada por rechazo o ya terminó su ejecución."
        ) % {
            'services': service_names,
            'request': blocking_request.display_name,
            'state': dict(blocking_request._fields['state'].selection).get(
                blocking_request.state, blocking_request.state
            ),
        })

    @api.depends('servicio_o.service_line_ids', 'servicio_o.service_line_ids.quantity', 'servicio_o.service_line_ids.product_id', 'servicio_d.service_line_ids.product_id')
    def _compute_transfer_summary(self):
        for request in self:
            origin_lines = request.servicio_o.service_line_ids if request.servicio_o else self.env['pending.service.line']
            transferable_lines = origin_lines.filtered(lambda line: line.quantity > 0)
            target_product_ids = set(request.servicio_d.service_line_ids.mapped('product_id').ids) if request.servicio_d else set()
            compatible_lines = transferable_lines.filtered(lambda line: line.product_id.id in target_product_ids)
            request.total_lineas_origen = len(origin_lines)
            request.total_lineas_transferibles = len(transferable_lines)
            request.total_lineas_compatibles = len(compatible_lines)

    def action_submit(self):
        for request in self:
            if request.state != 'draft':
                continue
            request._validate_request_basic()
            request._check_no_active_request_for_services({
                'servicio_o': request.servicio_o.id,
                'servicio_d': request.servicio_d.id,
            })
            request.write({'state': 'submitted'})
            request._schedule_merge_activity()
            request.message_post(body=_('Solicitud enviada a aprobación.'))
        return True

    def action_approve(self):
        self._check_approver()
        action = False
        for request in self:
            if request.state != 'submitted':
                raise ValidationError(_('Solo se pueden aprobar solicitudes en aprobación.'))
            wizard = request._create_fusion_wizard()
            action = wizard._action_open_from_request()
        return action or True

    def _mark_approved_after_wizard_execution(self):
        self._check_approver()
        for request in self:
            if request.state != 'submitted':
                raise ValidationError(_('Solo se pueden ejecutar solicitudes en aprobación.'))
            request.write({
                'state': 'approved',
                'approver_id': self.env.user.id,
                'approved_date': fields.Datetime.now(),
            })
            request._close_merge_activities(_('Solicitud revisada y proceso ejecutado.'))
            request.message_post(body=_('Solicitud aprobada y proceso ejecutado.'))
        return True

    def action_reject(self):
        self._check_approver()
        for request in self:
            if request.state not in ('draft', 'submitted'):
                raise ValidationError(_('Solo se pueden rechazar solicitudes en borrador o en aprobación.'))
            request.write({
                'state': 'rejected',
                'approver_id': self.env.user.id,
                'rejected_date': fields.Datetime.now(),
            })
            request._close_merge_activities(_('Solicitud revisada y rechazada.'))
            request.message_post(body=_('Solicitud rechazada.'))
        return True

    def _check_approver(self):
        if not self.env.user.has_group('project_modificaciones.group_pending_service_merge_approver'):
            raise AccessError(_('No tienes permisos para aprobar o rechazar solicitudes de fusión.'))

    def _check_protected_values(self, vals):
        protected_state = vals.get('state') in ('approved', 'rejected')
        protected_fields = {'approver_id', 'approved_date', 'rejected_date'}
        if (protected_state or protected_fields.intersection(vals)) and not self.env.user.has_group(
            'project_modificaciones.group_pending_service_merge_approver'
        ):
            raise AccessError(_('No tienes permisos para aprobar o rechazar solicitudes de fusión.'))

    def _validate_request_basic(self):
        for request in self:
            if not request.servicio_o:
                raise ValidationError(_('Debes seleccionar un servicio origen.'))
            if not request.servicio_d:
                raise ValidationError(_('Debes seleccionar un servicio destino.'))
            if not request.request_reason:
                raise ValidationError(_('Debes indicar el motivo de la solicitud.'))
            if request.notify_user_id and not request.notify_user_id.has_group('project_modificaciones.group_pending_service_merge_approver'):
                raise ValidationError(_('El usuario a notificar debe pertenecer al grupo Aprobador/Fusionador de Servicios Pendientes.'))
            if request.servicio_o == request.servicio_d:
                raise ValidationError(_('El servicio destino no puede ser el mismo que el origen.'))
            transferable_lines = request._get_transferable_origin_lines(strict_process=False)
            if not transferable_lines:
                raise ValidationError(_('El servicio origen no tiene líneas con cantidad para traspasar.'))
            if request.proceso == 'fusion':
                target_product_ids = set(request.servicio_d.service_line_ids.mapped('product_id').ids)
                compatible_lines = transferable_lines.filtered(lambda line: line.product_id.id in target_product_ids)
                if not compatible_lines:
                    raise ValidationError(_(
                        'No hay líneas compatibles para fusionar: el destino debe tener al menos una línea con el mismo producto que el origen.'
                    ))

    def _schedule_merge_activity(self):
        self.ensure_one()
        activity_type = self.env.ref('mail.mail_activity_data_todo', raise_if_not_found=False)
        if not activity_type:
            return
        notify_users = self._get_merge_approver_users()
        if not notify_users:
            return
        note = _(
            'Revisar la solicitud %(request)s para %(operation)s %(origin)s hacia %(target)s.<br/><br/>'
            '<b>Motivo:</b> %(reason)s'
        ) % {
            'request': self.display_name,
            'operation': dict(self._fields['proceso'].selection).get(self.proceso, self.proceso).lower(),
            'origin': self.servicio_o.display_name,
            'target': self.servicio_d.display_name,
            'reason': self.request_reason or '-',
        }
        for user in notify_users:
            self.activity_schedule(
                activity_type_id=activity_type.id,
                user_id=user.id,
                summary=_('Solicitud de operación pendiente'),
                note=note,
            )

    def _close_merge_activities(self, feedback):
        activity_type = self.env.ref('mail.mail_activity_data_todo', raise_if_not_found=False)
        if not activity_type:
            return False
        summaries = {
            _('Solicitud de operación pendiente'),
            _('Solicitud de fusión pendiente'),
        }
        for request in self:
            activities = request.activity_ids.filtered(
                lambda activity: (
                    activity.activity_type_id == activity_type
                    and activity.summary in summaries
                )
            )
            if activities:
                activities.action_feedback(feedback=feedback)
        return True

    def _prepare_wizard_vals(self):
        self.ensure_one()
        return {
            'proceso': self.proceso,
            'modo_reasignacion': self.modo_reasignacion,
            'servicio_o': self.servicio_o.id,
            'servicio_d': self.servicio_d.id,
            'lineas_seleccion': [],
        }

    def _prepare_wizard_line_commands(self):
        self.ensure_one()
        if self.proceso == 'fusion':
            commands = []
            target_lines_by_product = {}
            for target_line in self.servicio_d.service_line_ids:
                target_lines_by_product.setdefault(target_line.product_id.id, self.env['pending.service.line'])
                target_lines_by_product[target_line.product_id.id] |= target_line

            for line in self._get_transferable_origin_lines():
                candidate_lines = target_lines_by_product.get(
                    line.product_id.id,
                    self.env['pending.service.line'],
                )
                line_vals = {'linea_id': line.id}
                if len(candidate_lines) == 1:
                    line_vals['linea_destino_id'] = candidate_lines.id
                commands.append((0, 0, line_vals))
            return commands
        if self.modo_reasignacion == 'por_linea':
            return [
                (0, 0, {
                    'linea_id': line.id,
                    'servicio_destino': self.servicio_d.id,
                })
                for line in self._get_transferable_origin_lines()
            ]
        return []

    def _create_fusion_wizard(self):
        self.ensure_one()
        data = self._prepare_wizard_vals()
        data['lineas_seleccion'] = self._prepare_wizard_line_commands()
        data['pending_merge_request_id'] = self.id
        return self.env['fusion.servicios.pendientes'].with_context(
            active_model='pending.service',
            active_id=self.servicio_o.id,
        ).create(data)

    def _get_transferable_origin_lines(self, strict_process=True):
        self.ensure_one()
        lines = self.servicio_o.service_line_ids.filtered(lambda line: line.quantity > 0)
        if strict_process and self.proceso == 'fusion' and self.servicio_d:
            target_product_ids = set(self.servicio_d.service_line_ids.mapped('product_id').ids)
            lines = lines.filtered(lambda line: line.product_id.id in target_product_ids)
        return lines
