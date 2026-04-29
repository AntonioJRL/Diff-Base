from odoo import models, fields, api, _
from datetime import datetime
from markupsafe import Markup
from odoo.exceptions import ValidationError


import logging
_logger = logging.getLogger(__name__)


class PendingService(models.Model):
    _name = 'pending.service'
    _description = 'Servicio Pendiente'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(
        string="Nombre",
        required=True, copy=False, readonly=True,
        index='trigram',
        default=lambda self: _('New'))
    order_number = fields.Char(string='Número de Orden', tracking=True)
    state = fields.Selection([
        ('draft', 'Borrador'),
        ('pending', 'Pendiente'),
        ('assigned', 'Asignada'),
        ('canceled', 'Cancelada'),
    ], string='Estado', default='draft', tracking=True)
    supervisor_id = fields.Many2one(
        'hr.employee', string='Supervisor', tracking=True)
    disciplina_id = fields.Many2one(
        'license.disciplina', string='Disciplina', required=True, tracking=True)
    service_line_ids = fields.One2many(
        'pending.service.line', 'service_id', string='Líneas de Servicio')
    total = fields.Float(string='Total', compute='_compute_total', store=True, tracking=True)
    date = fields.Date(string='Fecha', default=datetime.today(), tracking=True)
    license_ids = fields.Many2many(
        'license.license', string='Licencias', tracking=True)

    ot_number = fields.Char(string='OT', tracking=True)
    planta = fields.Char(string='Planta (Texto)', tracking=True)
    supervisor_planta_id = fields.Many2one(
        'supervisor.area', string='Supervisor de Planta', tracking=True)
    manage_via_or = fields.Boolean(
        string='Gestionar mediante OR', default=False, tracking=True)
    descripcion_servicio = fields.Text(
        string='Descripción del Servicio', tracking=True)  # Nuevo campo
    active = fields.Boolean(string='Activo', default=True,
                            tracking=True)  # Para archivar

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                if 'disciplina_id' in vals:
                    disciplina = self.env['license.disciplina'].browse(
                        vals['disciplina_id'])
                    sequence = disciplina.sequence_id

                    # Generar base PEND...
                    if sequence:
                        base_name = sequence.next_by_id()
                    else:
                        base_name = _('New')

                    # Extraer el prefijo del cliente
                    cliente_id = vals.get('cliente_servicio')
                    prefix = 'INN' # Default
                    if cliente_id:
                        cliente = self.env['res.partner'].browse(cliente_id)
                        if getattr(cliente, 'ref', False):
                            # Tomar primeras 3 letras de la Referencia, ignorando espacios y convirtiendo a mayúsculas
                            prefix = ''.join(e for e in cliente.ref if e.isalnum())[:3].upper()
                        elif getattr(cliente, 'name', False):
                            # Fallback al nombre si no hay referencia
                            prefix = ''.join(e for e in cliente.name if e.isalnum())[:3].upper()

                    # Si el nombre base no es 'New', concatenarlo
                    if base_name != _('New'):
                        vals['name'] = f"{prefix}{base_name}"
                    else:
                        vals['name'] = base_name

                else:
                    vals['name'] = _('New')
        return super(PendingService, self).create(vals_list)

    def write(self, vals):
        # Lógica de consolidación de cambios en líneas para el chatter
        line_changes_summary = []
        
        if 'service_line_ids' in vals:
            # Diccionario de etiquetas para el rastreo
            labels = {
                'product_id': _('Producto'),
                'quantity': _('Cantidad'),
                'price_unit': _('Precio Unitario'),
            }

            for command in vals['service_line_ids']:
                # command[0] -> 0: Create, 1: Update, 2: Delete
                if command[0] == 0:  # NUEVA LÍNEA
                    l_vals = command[2]
                    prod_id = l_vals.get('product_id')
                    prod_name = self.env['product.product'].browse(prod_id).display_name if prod_id else _('N/A')
                    qty = l_vals.get('quantity', 0)
                    price = l_vals.get('price_unit', 0)
                    line_changes_summary.append(Markup("<li><b>%s:</b> %s (%s x %s)</li>") % (_("Nueva línea"), prod_name, qty, price))

                elif command[0] == 1:  # ACTUALIZACIÓN
                    line_id = command[1]
                    l_vals = command[2]
                    line = self.env['pending.service.line'].browse(line_id)
                    
                    sub_msgs = []
                    for field, label in labels.items():
                        if field in l_vals:
                            old_val = line[field]
                            new_val_raw = l_vals[field]
                            
                            if field == 'product_id':
                                new_val = self.env['product.product'].browse(new_val_raw)
                                if old_val.id != new_val.id:
                                    sub_msgs.append(_("Producto: %s → %s") % (old_val.display_name or _('N/A'), new_val.display_name or _('N/A')))
                            elif old_val != new_val_raw:
                                sub_msgs.append(_("%s: %s → %s") % (label, old_val, new_val_raw))
                    
                    if sub_msgs:
                        line_changes_summary.append(Markup("<li><b>%s (Partida %s):</b> %s</li>") % (_("Modificación"), line.partida, ", ".join(sub_msgs)))

                elif command[0] == 2:  # ELIMINACIÓN
                    line_id = command[1]
                    line = self.env['pending.service.line'].browse(line_id)
                    line_changes_summary.append(Markup("<li><b>%s:</b> %s (Partida %s)</li>") % (_("Línea eliminada"), line.product_id.display_name or _('N/A'), line.partida))

        # Ejecutar escritura normal
        res = super(PendingService, self).write(vals)

        # Publicar mensaje consolidado si hay cambios
        if line_changes_summary:
            msg = Markup("<b>%s:</b><ul>%s</ul>") % (_("Resumen de cambios en líneas"), Markup().join(line_changes_summary))
            self.message_post(body=msg)

        return res

    @api.depends('service_line_ids.total')
    def _compute_total(self):
        for service in self:
            service.total = sum(service.service_line_ids.mapped('total'))

    def action_set_to_pending(self):
        for record in self:
            if record.state == 'draft':
                record.state = 'pending'
            else:
                raise ValidationError(
                    _("El servicio debe estar en estado 'Borrador' para pasar a 'Pendiente'."))

    def action_assign(self):
        self.write({'state': 'assigned'})

    def action_cancel(self):
        self.write({'state': 'canceled'})

    def action_set_to_draft(self):
        self.write({'state': 'draft'})

    def toggle_active(self):
        for record in self:
            record.active = not record.active

    def unlink(self):
        # Eliminar las líneas de servicio asociadas antes de eliminar el servicio pendiente
        self.service_line_ids.unlink()
        return super(PendingService, self).unlink()

    # Control de Obra
    cliente_servicio = fields.Many2one(
        'res.partner', string="Cliente", help="Cliente al que se realizara el servicio.", required=True, tracking=True)

    # centro_trabajo = fields.Many2one('control.centro.trabajo', string="Centro Trabajo", help="Centro De Trabajo Donde Se Esta Realizando El Servicio", tracking=True)

    planta_centro = fields.Many2one(
        'control.planta', string="Planta", help="Planta donde se realizara el servicio.", tracking=True)

    task_count = fields.Integer(
        string='Cantidad de Tareas', compute='_compute_task_count')

    sale_order_count = fields.Integer(
        string='Órdenes de Venta', compute='_compute_sale_order_count')

    scaffolding_count = fields.Integer(
        string='Andamios', compute='_compute_scaffolding_count')

    @api.depends('name','state')
    def _compute_scaffolding_count(self):
        for record in self:
            # Buscar andamios relacionados a este servicio pendiente
            if 'scaffolding.installation' in self.env:
                record.scaffolding_count = self.env['scaffolding.installation'].search_count([
                    ('pendiente', '=', record.id)
                ])
            else:
                record.scaffolding_count = 0

    def action_view_scaffoldings(self):
        self.ensure_one()
        if 'scaffolding.installation' not in self.env:
            return

        domain = [('pendiente', '=', self.id)]

        return {
            'type': 'ir.actions.act_window',
            'name': _('Andamios Relacionados'),
            'res_model': 'scaffolding.installation',
            'view_mode': 'tree,form',
            'domain': domain,
            'context': {'default_pendiente': self.id},
        }


    @api.depends('task_ids', 'service_line_ids.task_id')
    def _compute_task_count(self):
        for record in self:
            # Extraemos IDs de tareas vinculadas en las líneas
            line_tasks = record.service_line_ids.mapped('task_id').ids
            # Extraemos IDs de tareas vinculadas directamente
            direct_tasks = record.task_ids.ids

            # Unimos ambos sets de IDs para evitar duplicados
            all_task_ids = list(set(line_tasks + direct_tasks))
            record.task_count = len(all_task_ids)

    @api.depends()
    def _compute_sale_order_count(self):
        for record in self:
            record.sale_order_count = self.env['sale.order'].search_count([
                ('pending_service_id', '=', record.id)
            ])

    def action_create_project_update(self):
        """
        Generar o actualizar un reporte de 'Project Update' (Avance Físico)
        con las líneas de este servicio pendiente.
        """
        self.ensure_one()

        if not self.supervisor_id.proyecto_supervisor:
            raise ValidationError(
                _("El supervisor no tiene un proyecto asignado."))

        return {
            'type': 'ir.actions.act_window',
            'name': _('Registrar Avance'),
            'res_model': 'pending.service.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_service_id': self.id,
                'default_date': self.date or fields.Date.context_today(self),
                'active_id': self.id,
            }
        }

    def action_create_tasks(self):
        for record in self:
            # 1. VALIDACIÓN PREVIA
            if not record.supervisor_id or not record.supervisor_id.proyecto_supervisor:
                raise ValidationError(
                    _("El supervisor no tiene un proyecto asignado en su ficha de empleado."))

            project = record.supervisor_id.proyecto_supervisor
            created_tasks = self.env['project.task']

            # 2. PROCESO DE CREACIÓN
            for line in record.service_line_ids:
                # Si ya tiene tarea, saltar
                if line.task_id:
                    continue

                user_id = record.supervisor_id.user_id.id if record.supervisor_id.user_id else False

                # Crear la tarea
                task = self.env['project.task'].create({
                    'name': f"P{line.partida:02d} {record.name} - {line.product_id.display_name}",
                    'project_id': project.id,
                    'description': record.descripcion_servicio or '',
                    'user_ids': [(4, user_id)] if user_id else False,
                    'planta_trabajo': record.planta_centro.id,
                    'piezas_pendientes': line.quantity,
                    'supervisor_interno': record.supervisor_id.id,
                    'supervisor_cliente': record.supervisor_planta_id.id,
                    'partner_id': record.cliente_servicio.id,
                    'producto_relacionado': line.product_id.id,
                    'servicio_pendiente': record.id,
                    'planned_date_begin': record.date_start, #LOGICA UNIFICADA
                    'date_deadline': record.date_end_plan, #LOGICA UNIFICADA
                })
                
                # Link task to line persistently
                line.task_id = task.id
                created_tasks |= task 

            # 3. NOTIFICACIÓN UI (Sin historial en chatter)
            if created_tasks:
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': _('Tareas Tareas Creadas'),
                        'message': _('Se han generado %s tareas correctamente en el proyecto %s.') % (len(created_tasks), project.name),
                        'type': 'success',
                        'sticky': False,
                        'next': {'type': 'ir.actions.client', 'tag': 'soft_reload'},
                    }
                }
        return True

    # Acción para el Smart Button
    def action_view_tasks(self):
        self.ensure_one()
        # Recolectamos todos los IDs de tareas vinculadas en las líneas
        task_ids_from_lines = self.service_line_ids.mapped('task_id').ids

        # El dominio busca:
        # 1. Tareas que tengan este registro en su campo 'servicio_pendiente'
        # 2. Tareas cuyos IDs estén en las líneas de este servicio
        domain = [
            '|',
            ('servicio_pendiente', '=', self.id),
            ('id', 'in', task_ids_from_lines)
        ]

        return {
            'name': _('Tareas del Servicio'),
            'type': 'ir.actions.act_window',
            'res_model': 'project.task',
            'view_mode': 'tree,form',
            'domain': domain,
            'context': {
                # Esto vincula automáticamente tareas nuevas a este servicio
                'default_servicio_pendiente': self.id,
                'default_partner_id': self.cliente_servicio.id,
            },
            'help': _("""
                <p class="o_view_nocontent_smiling_face">
                    No hay tareas asociadas a este servicio.
                </p>
            """),
        }

    # Acción para el Smart Button del proyecto
    def action_view_project(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Proyecto'),
            'res_model': 'project.project',
            'res_id': self.supervisor_id.proyecto_supervisor.id,
            'view_mode': 'form',
            'target': 'current',
        }

    # Acción para el Smart Button de órdenes de venta
    def action_view_sale_orders(self):
        self.ensure_one()
        sale_orders = self.env['sale.order'].search(
            [('pending_service_id', '=', self.id)])
        if len(sale_orders) == 1:
            return {
                'type': 'ir.actions.act_window',
                'name': _('Orden de Venta'),
                'res_model': 'sale.order',
                'res_id': sale_orders.id,
                'view_mode': 'form',
                'target': 'current',
            }
        else:
            return {
                'type': 'ir.actions.act_window',
                'name': _('Órdenes de Venta'),
                'res_model': 'sale.order',
                'view_mode': 'tree,form',
                'domain': [('pending_service_id', '=', self.id)],
                'context': {'default_pending_service_id': self.id},
            }

    def action_create_sale_order(self):
        for record in self:
            if not record.cliente_servicio:
                raise ValidationError(
                    _("Debe seleccionar un Cliente para generar la Orden de Venta."))

            if not record.supervisor_id.proyecto_supervisor:
                raise ValidationError(
                    _("El supervisor no tiene un proyecto asignado."))

            # 1. Crear la Orden de Venta (Cabecera)
            sale_order_vals = {
                'partner_id': record.cliente_servicio.id,
                'analytic_account_id': record.supervisor_id.proyecto_supervisor.analytic_account_id.id,
                'origin': record.name,
                # Forzamos el proyecto en la orden si tienes campos personalizados
                'project_id': record.supervisor_id.proyecto_supervisor.id,
                'fecha_pedido': record.date_start, # LOGICA UNIFICADA
                'commitment_date': record.date_end_plan, # LOGICA UNIFICADA
            }
            # Solo asignar pending_service_id si hay tareas creadas
            if record.task_count > 0:
                sale_order_vals['pending_service_id'] = record.id

            sale_order = self.env['sale.order'].create(sale_order_vals)

            # 2. Crear las líneas de la Orden de Venta
            for line in record.service_line_ids:
                sol = self.env['sale.order.line'].create({
                    'order_id': sale_order.id,
                    'product_id': line.product_id.id,
                    'product_uom_qty': line.quantity,
                    # 'price_unit': line.price_unit,
                    # Fix: Use pricelist price
                    'price_unit': sale_order.pricelist_id._get_product_price(line.product_id, line.quantity) if sale_order.pricelist_id else line.price_unit,
                    'name': f"P{line.partida:02d} {line.product_id.get_product_multiline_description_sale()}",
                    'pending_line_id': line.id,
                })

                # Las tareas existentes se asignarán automáticamente al confirmar la orden

            # 4. Mensaje de éxito con Markup
            msg = Markup(_(
                "<div style='background-color: #e9f7ef; border: 1px solid #28a745; padding: 10px;'>"
                "   <p><b>✅ Orden de Venta %s generada</b></p>"
                "   <p>Se han creado las tareas vinculadas en el proyecto del supervisor.</p>"
                "</div>"
            )) % sale_order.name
            record.message_post(body=msg)

            record.write({'state': 'assigned'})

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'sale.order',
            'res_id': sale_order.id,
            'view_mode': 'form',
            'target': 'current',
        }

    # Actualizar valores del campos total_avances
    def action_update_progress(self):
        """
        Recalcula total_avances.
        1. Busca los avances (project.sub.update) de la tarea asignada.
        2. Vincula esos avances a la línea para futuros cálculos.
        3. Suma el progreso.
        """
        messages = []
        for record in self:
            for line in record.service_line_ids:
                if line.task_id:
                    # Buscamos todos los avances que pertenezcan a esa tarea
                    avances = self.env['project.sub.update'].search([
                        ('task_id', '=', line.task_id.id)
                    ])

                    if avances:
                        # Vinculamos y re-calculamos
                        avances.write({'pending_service_line_id': line.id})
                        total_calculado = sum(avances.mapped('unit_progress'))
                        messages.append(_("Línea %s: OK. Total: %s (De %s registros)") % (
                            line.partida, total_calculado, len(avances)))
                    else:
                        messages.append(_("Línea %s: Tarea %s sin avances registrados.") % (
                            line.partida, line.task_id.name))
                else:
                    messages.append(
                        _("Línea %s: No tiene tarea asignada.") % line.partida)

        # Force recompute of stored field
        self.service_line_ids._compute_total_avances()

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Recálculo Completado'),
                'message': "\n".join(messages),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'soft_reload'},
            }
        }

    avances_pend = fields.One2many(
        'project.sub.update',
        'pending_service_id',
        string="Avances Relacionado"
    )

    task_ids = fields.One2many(
        'project.task',
        'servicio_pendiente',
        string="Tarea Relacionada",
        help="Tarea relacionada con el pendiente."
    )

    ###Logica Fusión de Pendientes##############################
    operation_origin_log_ids = fields.One2many(
        'pending.service.operation.log',
        'origin_id',
        string='Operaciones como Origen',
    )
    operation_destination_log_ids = fields.One2many(
        'pending.service.operation.log',
        'destination_id',
        string='Operaciones como Destino',
    )
    operation_origin_count = fields.Integer(
        string='Operaciones como Origen',
        compute='_compute_operation_counts',
    )
    operation_destination_count = fields.Integer(
        string='Operaciones como Destino',
        compute='_compute_operation_counts',
    )
    active_merge_request_count = fields.Integer(
        string='Solicitudes de Operación Activas',
        compute='_compute_active_merge_requests',
    )
    has_active_merge_request = fields.Boolean(
        string='Tiene Solicitud de Operación Activa',
        compute='_compute_active_merge_requests',
    )

    def _compute_operation_counts(self):
        log_model = self.env['pending.service.operation.log'].sudo()
        for service in self:
            service.operation_origin_count = log_model.search_count([('origin_id', '=', service.id)])
            service.operation_destination_count = log_model.search_count([('destination_id', '=', service.id)])

    def _compute_active_merge_requests(self):
        request_model = self.env['pending.merge.request'].sudo()
        active_states = request_model._active_request_states()
        for service in self:
            count = request_model.search_count([
                ('state', 'in', active_states),
                '|',
                ('servicio_o', '=', service.id),
                ('servicio_d', '=', service.id),
            ])
            service.active_merge_request_count = count
            service.has_active_merge_request = bool(count)
    ############################################################

    ###Logica Vista Unificada###################################
    date_start = fields.Datetime(
        string='Inicio',
        tracking=True,
        help="Fecha de inicio pactada en el contrato.",
    )

    date_end_plan = fields.Datetime(
        string='Fin Plan',
        tracking=True,
        help="Fecha de entrega pactada en el contrato (Fecha Plan).",
    )

    date_end_actual = fields.Date(
        string='Fecha Actual (Estimada)',
        compute='_compute_dates',
        store=False,
        help="Si hay retraso se recalcula esta fecha. Si supera Fin Plan se resalta en rojo.",
    )

    def action_sync_company_from_disciplina(self):
        """Recalcula la empresa histórica desde la disciplina."""
        if not self:
            return True

        pending_ids = self.filtered(lambda rec: rec.disciplina_id).ids
        if not pending_ids:
            return True

        # Forzamos el valor almacenado de company_id a partir de la disciplina.
        self.flush_model(['disciplina_id'])
        self.env.cr.execute(
            """
            UPDATE pending_service AS p
               SET company_id = d.company_id
              FROM license_disciplina AS d
             WHERE p.id = ANY(%s)
               AND p.disciplina_id = d.id
            """,
            [pending_ids],
        )
        self.invalidate_recordset(['company_id'])
        return True

    @api.constrains('date_start', 'date_end_plan')
    def _validar_planeacion(self):
        for rec in self:
            inicio = rec.date_start
            fin = rec.date_end_plan

            if inicio and fin and inicio > fin:
                raise ValidationError(_(
                    "La fecha de inicio no puede ser mayor a la fecha fin.\n\n"
                    "La fecha fin no puede ser menor que la fecha de inicio.\n\n"
                    "Fecha Inicio: %s\n"
                    "Fecha Fin: %s"
                ) % (
                    inicio.strftime('%d/%m/%Y'),
                    fin.strftime('%d/%m/%Y')
                ))
            if inicio == fin:
                raise ValidationError(_(
                    "Tanto la fecha de inicio como de fin en la planeación no pueden ser iguales.\n\n"
                    "Fecha Inicio: %s\n"
                    "Fecha Final: %s"
                ) % (
                    inicio.strftime('%d/%m/%Y'),
                    fin.strftime('%d/%m/%Y')
                ))

    delay_days = fields.Integer(
        string='Días de Retraso',
        compute='_compute_dates',
        store=False,
        help="Días de retraso respecto a la Fecha Plan. Se recalcula en vivo cada vez que se carga el registro.",
    )

    scaffolding_count = fields.Integer(
        compute='_compute_scaffolding_count')

    def _compute_scaffolding_count(self):
        for rec in self:
            if 'scaffolding.installation' in self.env:
                rec.scaffolding_count = self.env['scaffolding.installation'].search_count(
                    [('pendiente', '=', rec.id)])
            else:
                rec.scaffolding_count = 0

    # FIX: depends solo con los campos que REALMENTE usa el método.
    # Antes tenía avance_actual y avance_planeado (computed store=True),
    # lo que causaba que Odoo difiriera el cálculo y dejara delay_days = 0.
    @api.depends('date_end_plan', 'state', 'avance_actual')
    def _compute_dates(self):
        today = fields.Date.context_today(self)
        for rec in self:
            end_plan = getattr(rec, 'date_end_plan', False)
            if end_plan and hasattr(end_plan, 'date'):
                end_plan = end_plan.date()

            if end_plan and end_plan < today and rec.state not in ('canceled') and rec.avance_actual < 100.0:
                rec.delay_days = (today - end_plan).days
            else:
                rec.delay_days = 0
            rec.date_end_actual = today

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
        help="Usa el widget 'priority' en la vista Kanban para identificar servicios críticos.",
    )

    avance_planeado = fields.Float(
        string='Avance Planeado (%)',
        compute='_compute_avance_planeado',
        store=False,
        digits=(5, 2),
        help="Calculado como (hoy − Inicio) / (Fin Plan − Inicio) × 100. Se recalcula en vivo.",
    )

    @api.depends('date_start', 'date_end_plan')
    def _compute_avance_planeado(self):
        today = date.today()
        for rec in self:
            start_date = getattr(rec, 'date_start', False)
            if start_date and hasattr(start_date, 'date'):
                start_date = start_date.date()

            end_date = getattr(rec, 'date_end_plan', False)
            if end_date and hasattr(end_date, 'date'):
                end_date = end_date.date()

            if not start_date or not end_date:
                rec.avance_planeado = 0.0
                continue
            total_days = (end_date - start_date).days
            if total_days <= 0:
                rec.avance_planeado = 100.0
                continue
            elapsed = (today - start_date).days
            rec.avance_planeado = max(
                0.0, min(100.0, (elapsed / total_days) * 100))

    avance_actual = fields.Float(
        string='Avance Físico Real (%)',
        compute='_compute_avance_actual',
        store=True,
        digits=(5, 2),
        help="Calculado como Σ(total_avances) / Σ(quantity) × 100 de las líneas de servicio.",
    )

    @api.depends('service_line_ids.total_avances', 'service_line_ids.quantity')
    def _compute_avance_actual(self):
        for rec in self:
            total_qty = sum(rec.service_line_ids.mapped('quantity'))
            total_avances = sum(rec.service_line_ids.mapped('total_avances'))
            if total_qty > 0:
                rec.avance_actual = min(
                    100.0, (total_avances / total_qty) * 100)
            else:
                rec.avance_actual = 0.0

    kanban_color = fields.Selection(
        selection=[
            ('green', 'Verde  — En tiempo o adelantado'),
            ('amber', 'Ámbar  — Retraso menor al 10 %'),
            ('red',   'Rojo   — Retraso crítico o fecha vencida'),
        ],
        string='Color Kanban (Semáforo)',
        compute='_compute_kanban_color',
        store=True,
        help="Verde: actual ≥ planeado. Ámbar: retraso < 10%. Rojo: retraso ≥ 10% o fecha vencida.",
    )

    @api.depends('avance_actual', 'avance_planeado', 'date_end_plan')
    def _compute_kanban_color(self):
        today = date.today()

        for rec in self:
            actual = rec.avance_actual or 0.0
            plan = rec.avance_planeado or 0.0

            # Normalizar fecha
            end_plan = rec.date_end_plan
            if end_plan and hasattr(end_plan, 'date'):
                end_plan = end_plan.date()

            # 🔴 Fecha vencida sin completar
            if end_plan and end_plan < today and actual < 100.0:
                rec.kanban_color = 'red'
                continue

            # Desviación = real - planeado
            desviacion = actual - plan

            if desviacion >= 0:
                rec.kanban_color = 'green'
            elif abs(desviacion) < 10:
                rec.kanban_color = 'amber'
            else:
                rec.kanban_color = 'red'

    task_done_count = fields.Integer(
        string='Tareas Completadas',
        compute='_compute_task_done_count',
        store=True,
        help="Cantidad de tareas en estado 'Done' vinculadas a este servicio.",
    )

    @api.depends('task_ids', 'task_ids.state', 'service_line_ids.task_id', 'service_line_ids.task_id.state')
    def _compute_task_done_count(self):
        done_state = '1_done'
        for rec in self:
            line_tasks = rec.service_line_ids.mapped('task_id')
            direct_tasks = rec.task_ids
            all_tasks = line_tasks | direct_tasks
            rec.task_done_count = len(all_tasks.filtered(
                lambda t: t.state == done_state))

    avance_facturado = fields.Float(
        string='Avance Facturado (%)',
        compute='_compute_avance_facturado',
        store=True,
        digits=(5, 2),
        help="Calculado como Σ(invoiced) / total × 100 a partir de las tareas vinculadas.",
    )

    @api.depends(
        'service_line_ids.task_id',
        'service_line_ids.task_id.qty_invoiced',
        'service_line_ids.task_id.quant_progress',
        'service_line_ids.quantity'
    )
    def _compute_avance_facturado(self):
        """ Avance facturado basado estrictamente en piezas """
        for rec in self:
            # 1. Obtenemos el total de piezas de las líneas de servicio
            # total_qty = sum(rec.service_line_ids.mapped('quantity'))
            # if total_qty <= 0:
            # rec.avance_facturado = 0.0
            # continue

            # 2. Obtenemos todas las tareas vinculadas
            all_tasks = rec.service_line_ids.mapped('task_id') | rec.task_ids

            # 3. Sumamos las piezas facturadas desde las tareas (qty_invoiced)
            total_invoiced = sum(
                task.qty_invoiced for task in all_tasks if task.qty_invoiced)

            total_entre = sum(
                task.quant_progress for task in all_tasks if task.quant_progress)
            if total_entre <= 0:
                rec.avance_facturado = 0.0
                continue

            # 4. Calculamos el porcentaje idéntico a tareas (ej. 2 * 100 / 12 = 16.666)
            fact_pct = float(total_invoiced * 100) / float(total_entre)
            rec.avance_facturado = round(min(100.0, fact_pct), 2)

    sale_order_id = fields.One2many(
        'sale.order',
        'pending_service_id',
        string="Órden de Venta",
        help="Órden de venta relacionada al servicio pendiente."
    )

    company_id = fields.Many2one(
        'res.company',
        string="Empresa",
        related='disciplina_id.company_id',
        store=True,
        readonly=True,
        index=True,
        help="La empresa se toma desde la disciplina para heredarla automáticamente en el servicio.",
    )
    ############################################################


class PendingServiceLine(models.Model):
    _name = 'pending.service.line'
    _description = 'Línea de Servicio Pendiente'
    _order = 'sequence, id'

    ####Logica de Fusión de Servicios Pendientes##################################################################
    _rec_name = 'name'

    name = fields.Char(
        string="Nombre",
        compute='_compute_name',
        store=True,
    )
    # Calcula y guarda el valor del campo real name de cada línea.
    @api.depends('partida', 'service_id', 'service_id.name', 'product_id', 'product_id.display_name', 'quantity')
    def _compute_name(self):
        for line in self:
            partes = []
            if line.partida:
                partes.append(f"P{line.partida:02d}")
            if line.service_id:
                partes.append(line.service_id.display_name)
            if line.product_id:
                partes.append(line.product_id.display_name)
            if line.quantity:
                partes.append(f"Qty {line.quantity}")
            line.name = " - ".join(partes) or f"Línea {line.id or ''}".strip()

    # Devuelve cómo se muestra el registro al en una lista desplegables Many2one
    def name_get(self):
        result = []
        for line in self:
            partes = []
            if line.partida:
                partes.append("P%s" % line.partida)
            if line.service_id:
                partes.append(line.service_id.display_name)
            if line.product_id:
                partes.append(line.product_id.display_name)
            if line.quantity:
                partes.append("Qty %s" % line.quantity)
            nombre = " - ".join(partes) or ("Línea %s" % line.id)
            result.append((line.id, nombre))
        return result
    
    def _sync_task_pending_pieces(self):
        for line in self:
            if line.task_id:
                line.task_id.write({
                    'piezas_pendientes': line.quantity,
                })

    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        lines._sync_task_pending_pieces()
        return lines

    def write(self, vals):
        res = super().write(vals)

        if 'quantity' in vals or 'task_id' in vals:
            self._sync_task_pending_pieces()

        return res
    ###########################################################################################################


    sequence = fields.Integer(string='Secuencia', default=10)
    partida = fields.Integer(
        string='Partida', compute='_compute_partida', store=True)

    @api.depends('sequence', 'service_id.service_line_ids')
    def _compute_partida(self):
        for service in self.mapped('service_id'):
            # Sort by sequence only to avoid NewId comparison error
            # Python sort is stable, so original insertion order is preserved for ties
            lines = service.service_line_ids.sorted(key=lambda l: l.sequence)
            for i, line in enumerate(lines, 1):
                old_partida = line.partida
                line.partida = i

                # If part of a reorder (not new creation) and has task, rename it
                if old_partida != i and line.task_id:
                    # Reconstruct name: P{02d} ServiceName - ProductDisplayName
                    new_name = f"P{i:02d} {line.service_id.name} - {line.product_id.display_name}"
                    # Only write if different to avoid excess writes
                    if line.task_id.name != new_name:
                        line.task_id.name = new_name

    service_id = fields.Many2one(
        'pending.service', string='Servicio Pendiente', required=True)
    product_id = fields.Many2one(
        'product.product', string='Producto', required=True)
    quantity = fields.Float(string='Cantidad', required=True)
    price_unit = fields.Float(
        string='Precio Unitario', compute='_compute_price_unit', inverse='_inverse_price_unit', store=True)
    total = fields.Float(string='Total', compute='_compute_total', store=True)

    # Campo para la tarea asociada (se setea cuando se crea la tarea)
    task_id = fields.Many2one(
        'project.task', string='Tarea Asociada', copy=False)
        
    precio_estimado = fields.Boolean(
        string='¿Precio Estimado?', default=False,
        help="Indica si el precio unitario ingresado es una estimación en lugar de un valor cotizado en sistema."
    )

    # Total de avances físicos asociados a la tarea
    sub_update_ids = fields.One2many(
        'project.sub.update', 'pending_service_line_id', string='Avances Físicos')

    total_avances = fields.Float(
        string='Total Avances', compute='_compute_total_avances', store=True)

    @api.depends('sub_update_ids.unit_progress', 'sub_update_ids.avances_state')
    def _compute_total_avances(self):
        for line in self:
            # Sumamos solo los avances que no estén en borrador (opcional, según lógica de negocio)
            # Si se desea sumar todo, quitar el filtro de state.
            avances = line.sub_update_ids
            line.total_avances = sum(avances.mapped('unit_progress'))

    @api.depends('product_id')
    def _compute_price_unit(self):
        for line in self:
            if not line.precio_estimado: # Si no está marcado como estimado temporal
                if line.product_id:
                    # Use lst_price to get the variant's specific price (including extra charges)
                    line.price_unit = line.product_id.lst_price
                else:
                    line.price_unit = 0.0

    def _inverse_price_unit(self):
        for line in self:
            if line.product_id:
                line.price_unit = line.price_unit

    def action_open_task(self):
        self.ensure_one()
        if self.task_id:
            return {
                'type': 'ir.actions.act_window',
                'res_model': 'project.task',
                'res_id': self.task_id.id,
                'view_mode': 'form',
                'target': 'current',
            }

    @api.depends('quantity', 'price_unit')
    def _compute_total(self):
        for line in self:
            line.total = line.quantity * line.price_unit
