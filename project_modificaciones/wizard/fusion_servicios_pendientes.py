from odoo import models, api, fields, _
from odoo.exceptions import ValidationError
from markupsafe import Markup
from urllib.parse import quote


class FusionServiciosPendientes(models.TransientModel):
    _name = 'fusion.servicios.pendientes'
    _description = 'Fusión de Servicios Pendientes'

    pending_merge_request_id = fields.Many2one(
        'pending.merge.request',
        string='Solicitud de Operación',
        readonly=True,
    )
    from_merge_request = fields.Boolean(
        string='Desde Solicitud',
        compute='_compute_from_merge_request',
    )
    direct_merge_locked = fields.Boolean(
        string='Fusión Directa Bloqueada',
    )
    operation_locked = fields.Boolean(
        string='Operación Bloqueada',
        compute='_compute_operation_locked',
    )
    proceso = fields.Selection(
        selection=[
            ('reasignacion', 'Reasignacion'),
            ('fusion', 'Fusion'),
        ],
        string='Proceso',
        default='reasignacion',
        required=True,
    )

    modo_reasignacion = fields.Selection(
        selection=[
            ('todo', 'Mover todas las líneas a un destino'),
            ('por_linea', 'Asignar destino línea por línea'),
        ],
        string="Modo de Reasignación",
        default='todo',
        required=True,
    )

    # Origen 
    servicio_o = fields.Many2one(
        'pending.service',
        string="Servicio P. Origen",
        required=True,
    )
    cliente_o = fields.Many2one(
        'res.partner',       
        related='servicio_o.cliente_servicio', 
        string="Cliente Origen")
    
    planta_o = fields.Many2one(
        'control.planta',    
        related='servicio_o.planta_centro',    
        string="Planta Origen")
    
    disciplina_o = fields.Many2one(
        'license.disciplina',
        related='servicio_o.disciplina_id',    
        string="Disciplina Origen")
    
    supervisor_o = fields.Many2one(
        'hr.employee',       
        related='servicio_o.supervisor_id',    
        string="Supervisor I. Origen")
    
    fp_inicio_o = fields.Datetime(
        related='servicio_o.date_start',    
        string="Fecha Inicio")
    
    fp_fin_o = fields.Datetime(
        related='servicio_o.date_end_plan', 
        string="Fecha Fin")
    
    linea_servicio_o = fields.One2many(
        'pending.service.line', 
        related='servicio_o.service_line_ids', 
        string="Líneas Servicio Origen")
    
    # Destino único (modo 'todo')
    servicio_d = fields.Many2one(
        'pending.service',
        string="Servicio P. Destino",
        required=False,
    )
    cliente_d = fields.Many2one(
        'res.partner',       
        related='servicio_d.cliente_servicio', 
        string="Cliente Destino")
    
    planta_d = fields.Many2one(
        'control.planta',    
        related='servicio_d.planta_centro',    
        string="Planta Destino")
    
    disciplina_d = fields.Many2one(
        'license.disciplina',
        related='servicio_d.disciplina_id',    
        string="Disciplina Destino")
    
    supervisor_d = fields.Many2one(
        'hr.employee',       
        related='servicio_d.supervisor_id',    
        string="Supervisor I. Destino")
    
    fp_inicio_d = fields.Datetime(
        related='servicio_d.date_start',    
        string="Fecha Inicio")
    
    fp_fin_d = fields.Datetime(
        related='servicio_d.date_end_plan', 
        string="Fecha Fin")
    
    linea_servicio_d = fields.One2many(
        'pending.service.line', 
        related='servicio_d.service_line_ids', 
        string="Líneas Servicio Destino")

    # Líneas con destino individual (modo 'por_linea')
    lineas_seleccion = fields.One2many(
        'fusion.servicios.pendientes.linea',   # ← nombre sin 's', consistente con el modelo
        'wizard_id',
        string="Líneas con Destino Individual",
    )
    total_lineas_origen = fields.Integer(
        compute='_compute_resumen_fusion',
        string='Líneas Origen',
    )
    total_lineas_a_mover = fields.Integer(
        compute='_compute_resumen_fusion',
        string='Líneas a Mover',
    )
    total_tareas_afectadas = fields.Integer(
        compute='_compute_resumen_fusion',
        string='Tareas Afectadas',
    )
    total_avances_afectados = fields.Integer(
        compute='_compute_resumen_fusion',
        string='Avances Afectados',
    )
    total_destinos = fields.Integer(
        compute='_compute_resumen_fusion',
        string='Destinos',
    )
    mensaje_validacion = fields.Html(
        compute='_compute_estado_visual',
        sanitize=False,
        string='Estado de Validación',
    )

    @api.depends('pending_merge_request_id')
    def _compute_from_merge_request(self):
        for record in self:
            record.from_merge_request = bool(record.pending_merge_request_id)

    @api.depends('pending_merge_request_id', 'direct_merge_locked')
    def _compute_operation_locked(self):
        for record in self:
            record.operation_locked = bool(record.pending_merge_request_id or record.direct_merge_locked)

    def write(self, vals):
        locked_fields = {'proceso', 'modo_reasignacion', 'servicio_o', 'servicio_d'}
        if locked_fields.intersection(vals):
            for wizard in self.filtered(lambda item: item.pending_merge_request_id or item.direct_merge_locked):
                request = wizard.pending_merge_request_id
                for field_name in locked_fields.intersection(vals):
                    new_value = vals[field_name]
                    allowed_value = request[field_name] if request else wizard[field_name]
                    if hasattr(allowed_value, 'id'):
                        allowed_value = allowed_value.id
                    if new_value != allowed_value:
                        raise ValidationError(_(
                            "No puedes modificar proceso, origen ni destino porque esta operación ya fue definida."
                        ))
        return super().write(vals)

    # Toma el valor del cotexto pasado por el button para asignar el valor del servicio origen por defecto.
    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        active_id = self.env.context.get('active_id')
        if self.env.context.get('active_model') == 'pending.service' and active_id:
            res['servicio_o'] = active_id
        return res

    def _action_open_from_request(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Revisar y ejecutar fusión'),
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'view_id': self.env.ref(
                'project_modificaciones.fusion_servicios_pendientes_view_form'
            ).id,
            'target': 'new',
        }

    # Poblar líneas al cambiar origen o modo 
    @api.onchange('proceso', 'servicio_o', 'servicio_d', 'modo_reasignacion')
    def _onchange_poblar_lineas_seleccion(self):
        if self.proceso == 'fusion' and self.servicio_o:
            lineas_destino_actuales = {
                linea.linea_id.id: linea.linea_destino_id.id
                for linea in self.lineas_seleccion
                if linea.linea_id and linea.linea_destino_id and linea.linea_destino_id.service_id == self.servicio_d
            }
            self.lineas_seleccion = [(5, 0, 0)] + [
                (0, 0, {
                    'linea_id': linea.id,
                    'linea_destino_id': lineas_destino_actuales.get(linea.id),
                })
                for linea in self.servicio_o.service_line_ids
            ]
        elif self.modo_reasignacion == 'por_linea' and self.servicio_o:
            destinos_actuales = {
                linea.linea_id.id: linea.servicio_destino.id
                for linea in self.lineas_seleccion
                if linea.linea_id
            }
            self.lineas_seleccion = [(5, 0, 0)] + [
                (0, 0, {
                    'linea_id': linea.id,
                    'servicio_destino': destinos_actuales.get(linea.id),
                })
                for linea in self.servicio_o.service_line_ids
            ]
        elif self.modo_reasignacion == 'todo':
            self.lineas_seleccion = [(5, 0, 0)]

    # Pre-validación visual
    is_fusionable = fields.Boolean(compute="_compute_is_fusionable")

    @api.depends(
        'proceso', 'servicio_o', 'servicio_d', 'modo_reasignacion',
        'servicio_o.state', 'servicio_o.sale_order_id', 'servicio_o.service_line_ids',
        'servicio_d.state', 'servicio_d.sale_order_id',
        'lineas_seleccion', 'lineas_seleccion.linea_id', 'lineas_seleccion.servicio_destino', 'lineas_seleccion.linea_destino_id',
        'lineas_seleccion.servicio_destino.state', 'lineas_seleccion.servicio_destino.sale_order_id',
    )
    def _compute_is_fusionable(self):
        for record in self:
            record.is_fusionable = not bool(record._obtener_errores_validacion())

    @api.depends(
        'proceso', 'servicio_o', 'servicio_d', 'modo_reasignacion',
        'servicio_o.service_line_ids', 'servicio_o.service_line_ids.task_id',
        'lineas_seleccion', 'lineas_seleccion.linea_id', 'lineas_seleccion.servicio_destino', 'lineas_seleccion.linea_destino_id',
    )
    def _compute_resumen_fusion(self):
        for record in self:
            lineas_origen = record.servicio_o.service_line_ids if record.servicio_o else self.env['pending.service.line']
            if record.proceso == 'fusion':
                lineas_a_mover = record.lineas_seleccion.filtered(
                    lambda l: l.linea_destino_id and l.linea_id
                ).mapped('linea_id')
            else:
                lineas_a_mover = record.lineas_seleccion.filtered(
                    lambda l: l.servicio_destino and l.linea_id
                ).mapped('linea_id') if record.modo_reasignacion == 'por_linea' else lineas_origen
            record.total_lineas_origen = len(lineas_origen)
            record.total_lineas_a_mover = len(lineas_a_mover)
            record.total_tareas_afectadas = len(lineas_a_mover.mapped('task_id').filtered(lambda t: t))
            if record.servicio_o and (record.modo_reasignacion == 'por_linea' or record.proceso == 'fusion'):
                record.total_avances_afectados = self.env['project.sub.update'].search_count([
                    ('pending_service_id', '=', record.servicio_o.id),
                    ('pending_service_line_id', 'in', lineas_a_mover.ids),
                ]) if lineas_a_mover else 0
            else:
                record.total_avances_afectados = self.env['project.sub.update'].search_count([
                    ('pending_service_id', '=', record.servicio_o.id)
                ]) if record.servicio_o else 0

            if record.proceso == 'fusion':
                destinos = record.lineas_seleccion.mapped('linea_destino_id.service_id').filtered(lambda d: d)
                record.total_destinos = len(destinos)
            elif record.modo_reasignacion == 'todo':
                record.total_destinos = 1 if record.servicio_d else 0
            else:
                destinos = record.lineas_seleccion.mapped('servicio_destino').filtered(lambda d: d)
                record.total_destinos = len(destinos)

    @api.depends(
        'proceso', 'servicio_o', 'servicio_d', 'modo_reasignacion',
        'servicio_o.state', 'servicio_o.sale_order_id', 'servicio_o.service_line_ids',
        'servicio_d.state', 'servicio_d.sale_order_id',
        'lineas_seleccion', 'lineas_seleccion.linea_id', 'lineas_seleccion.servicio_destino', 'lineas_seleccion.linea_destino_id',
        'lineas_seleccion.servicio_destino.state', 'lineas_seleccion.servicio_destino.sale_order_id',
    )
    def _compute_estado_visual(self):
        for record in self:
            errores = record._obtener_errores_validacion()
            if errores:
                record.mensaje_validacion = (
                    "<b>No es posible ejecutar la fusión todavía.</b><ul>%s</ul>" %
                    "".join("<li>%s</li>" % error for error in errores)
                )
            else:
                record.mensaje_validacion = (
                    "<b>Configuración lista.</b><br/>"
                    "La fusión puede ejecutarse con las reglas actuales."
                )

    def _obtener_errores_validacion(self):
        self.ensure_one()
        errores = []
        origen = self.servicio_o

        if not origen:
            errores.append("Debes seleccionar un servicio origen.")
            return errores

        estados_bloqueantes = ('assigned', 'canceled')
        if origen.state in estados_bloqueantes:
            errores.append(
                "El servicio origen '%s' está en estado '%s'." % (origen.display_name, origen.state)
            )
        if origen.sale_order_id:
            errores.append(
                "El servicio origen '%s' ya tiene una orden de venta asociada." % origen.display_name
            )
        if not origen.service_line_ids:
            errores.append(
                "El servicio origen '%s' no tiene líneas de servicio para mover." % origen.display_name
            )

        if self.proceso == 'fusion':
            if not self.servicio_d:
                errores.append("Debes seleccionar un servicio destino para la fusion.")
            else:
                errores.extend(self._validar_destino(self.servicio_d))
            if not self.lineas_seleccion:
                errores.append("No hay líneas cargadas para fusionar.")
            else:
                lineas_a_fusionar = self.lineas_seleccion.filtered(lambda l: l.linea_destino_id)
                if not lineas_a_fusionar:
                    errores.append(
                        "Debes seleccionar al menos una línea destino para fusionar. "
                        "El wizard la preselecciona cuando encuentra una única línea compatible por producto; "
                        "si hay varias opciones, el fusionador debe elegirla manualmente."
                    )
                lineas_invalidas = self.lineas_seleccion.filtered(
                    lambda l: not l.linea_id or l.linea_id.service_id != origen
                )
                if lineas_invalidas:
                    errores.append("Existen líneas que no pertenecen al servicio origen seleccionado.")
                for seleccion in lineas_a_fusionar:
                    errores.extend(self._validar_linea_destino_fusion(seleccion))
        elif self.modo_reasignacion == 'todo':
            if not self.servicio_d:
                errores.append("Debes seleccionar un servicio destino.")
            else:
                errores.extend(self._validar_destino(self.servicio_d))
        elif self.modo_reasignacion == 'por_linea':
            if not self.lineas_seleccion:
                errores.append("No hay líneas cargadas para distribuir.")
            else:
                lineas_con_destino = self.lineas_seleccion.filtered(lambda l: l.servicio_destino)
                if not lineas_con_destino:
                    errores.append("Debes asignar destino al menos a una línea para continuar.")

                lineas_invalidas = self.lineas_seleccion.filtered(
                    lambda l: not l.linea_id or l.linea_id.service_id != origen
                )
                if lineas_invalidas:
                    errores.append("Existen líneas que no pertenecen al servicio origen seleccionado.")

                for destino in lineas_con_destino.mapped('servicio_destino').filtered(lambda d: d):
                    errores.extend(self._validar_destino(destino))

        return list(dict.fromkeys(errores))

    def _validar_destino(self, destino):
        self.ensure_one()
        errores = []
        origen = self.servicio_o
        estados_bloqueantes = ('assigned', 'canceled')

        if not destino:
            return errores
        if origen and destino == origen:
            errores.append(
                "El servicio destino '%s' no puede ser el mismo que el origen." % destino.display_name
            )
        if destino.state in estados_bloqueantes:
            errores.append(
                "El servicio destino '%s' está en estado '%s'." % (destino.display_name, destino.state)
            )
        if destino.sale_order_id:
            errores.append(
                "El servicio destino '%s' ya tiene una orden de venta asociada." % destino.display_name
            )
        if destino.supervisor_id and not destino.supervisor_id.proyecto_supervisor:
            errores.append(
                "El supervisor del servicio destino '%s' no tiene proyecto asignado." % destino.display_name
            )
        return errores

    def _validar_linea_destino_fusion(self, seleccion):
        self.ensure_one()
        errores = []
        linea_origen = seleccion.linea_id
        linea_destino = seleccion.linea_destino_id

        if not linea_destino:
            return errores
        if self.servicio_d and linea_destino.service_id != self.servicio_d:
            errores.append(
                "La línea destino '%s' no pertenece al servicio destino seleccionado." % linea_destino.display_name
            )
        if linea_origen and linea_destino.product_id != linea_origen.product_id:
            errores.append(
                "La línea destino '%s' no coincide en producto con la línea origen '%s'."
                % (linea_destino.display_name, linea_origen.display_name)
            )
        if linea_destino.service_id == self.servicio_o:
            errores.append(
                "La línea destino '%s' no puede pertenecer al mismo servicio origen." % linea_destino.display_name
            )
        if linea_origen and linea_origen.task_id and linea_origen.task_id.sale_line_id:
            errores.append(
                "La tarea origen '%s' está ligada a una línea de venta y no puede fusionarse automáticamente."
                % linea_origen.task_id.display_name
            )
        if linea_destino and linea_destino.task_id and linea_destino.task_id.sale_line_id:
            errores.append(
                "La tarea destino '%s' está ligada a una línea de venta y no puede absorber otra tarea automáticamente."
                % linea_destino.task_id.display_name
            )
        return errores

    # Validación final. No debe ejecutarse como constraint al abrir el wizard,
    # porque el fusionador aún puede necesitar elegir líneas destino.
    def _validaciones_pre_fusion(self):
        for record in self:
            errores = record._obtener_errores_validacion()
            if errores:
                raise ValidationError("\n".join("• %s" % error for error in errores))

    # Acción principal 
    def fusionar_servicios(self):
        self.ensure_one()
        self._validaciones_pre_fusion()
        request = self.pending_merge_request_id
        if request:
            if request.state != 'submitted':
                raise ValidationError(
                    _("La solicitud vinculada debe estar en aprobación para ejecutar el proceso.")
                )
            request._check_approver()
            if (
                self.proceso != request.proceso
                or self.modo_reasignacion != request.modo_reasignacion
                or self.servicio_o != request.servicio_o
                or self.servicio_d != request.servicio_d
            ):
                raise ValidationError(_(
                    "El proceso, origen y destino deben coincidir con la solicitud aprobada."
                ))
        mensaje_exito = False

        if self.proceso == 'fusion':
            resumen = self._fusionar_lineas()
            self._registrar_chatter_fusion(resumen)
            mensaje_exito = self._mensaje_exito_fusion_resumen(resumen)
            self._create_operation_logs(resumen)
        elif self.modo_reasignacion == 'todo':
            if not self.servicio_d:
                raise ValidationError(
                "En modo 'todo' debes seleccionar un servicio destino."
                )
            detalle_fusion = self._mover_lineas_al_destino()
            self._registrar_chatter(detalle_fusion)
            mensaje_exito = self._mensaje_exito_reasignacion_todo(detalle_fusion)
            self._create_operation_logs(detalle_fusion)

        elif self.modo_reasignacion == 'por_linea':
            resumen = self._mover_lineas_por_destino()
            self._registrar_chatter_por_linea(resumen)
            mensaje_exito = self._mensaje_exito_reasignacion_por_linea(resumen)
            self._create_operation_logs(resumen)

        self._archivar_origen()
        if request:
            request._mark_approved_after_wizard_execution()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Proceso completado'),
                'message': mensaje_exito or self._mensaje_exito_fusion(),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.act_window_close'},
            }
        }

    def _create_operation_logs(self, operation_result):
        self.ensure_one()
        if not operation_result:
            return False

        entries = []
        if self.proceso == 'fusion' or self.modo_reasignacion == 'por_linea':
            entries = operation_result.items()
        elif self.modo_reasignacion == 'todo':
            entries = [(self.servicio_d, operation_result)]

        request = self.pending_merge_request_id
        log_model = self.env['pending.service.operation.log']
        for destino, info in entries:
            if not destino:
                continue
            log_model.create({
                'operation_type': self.proceso,
                'reassignment_mode': self.modo_reasignacion if self.proceso == 'reasignacion' else False,
                'origin_id': self.servicio_o.id,
                'destination_id': destino.id,
                'request_id': request.id if request else False,
                'user_id': self.env.user.id,
                'line_count': info.get('cantidad', 0),
                'note': self._operation_log_note(info),
            })
        return True

    def _operation_log_note(self, info):
        self.ensure_one()
        if self.proceso == 'fusion':
            return '\n\n'.join(
                "Origen: %(origen)s\Destino: %(destino)s\nResultado: %(resultado)s" % {
                    'origen': item.get('origen'),
                    'destino': item.get('destino_original') or item.get('destino'),
                    'resultado': item.get('destino_resultado') or item.get('destino'),
                }
                for item in info.get('fusiones', [])
            )
        lineas = info.get('lineas')
        if lineas:
            return '\n'.join(self._descripcion_linea(linea) for linea in lineas)
        return False

    def _fusionar_lineas(self):
        self.ensure_one()
        resumen = {}
        origen = self.servicio_o
        lineas_a_fusionar = self.lineas_seleccion.filtered(lambda l: l.linea_destino_id)
        if not lineas_a_fusionar:
            raise ValidationError("Debes seleccionar al menos una línea destino para fusionar.")

        for seleccion in lineas_a_fusionar:
            errores = self._validar_linea_destino_fusion(seleccion)
            if errores:
                raise ValidationError("\n".join("• %s" % error for error in errores))

            linea_origen = seleccion.linea_id
            linea_destino = seleccion.linea_destino_id
            destino = linea_destino.service_id
            cantidad_origen = linea_origen.quantity
            descripcion_origen = self._descripcion_linea(linea_origen)
            descripcion_destino_original = self._descripcion_linea(linea_destino)
            avances_linea = self.env['project.sub.update'].search([
                ('pending_service_line_id', '=', linea_origen.id),
            ])

            linea_destino.write({'quantity': linea_destino.quantity + cantidad_origen})

            fusion_tarea_info = self._fusionar_tarea_en_destino(
                tarea_origen=linea_origen.task_id,
                tarea_destino=linea_destino.task_id,
                linea_destino=linea_destino,
                destino=destino,
            )
            tarea_final = fusion_tarea_info['target_task']

            vals_avance = {
                'pending_service_id': destino.id,
                'pending_service_line_id': linea_destino.id,
            }
            if tarea_final:
                vals_avance['task_id'] = tarea_final.id
                vals_avance['project_id'] = tarea_final.project_id.id
            if avances_linea:
                avances_linea.write(vals_avance)

            linea_origen.unlink()

            if destino not in resumen:
                resumen[destino] = {
                    'cantidad': 0,
                    'fusiones': [],
                }
            resumen[destino]['cantidad'] += 1
            resumen[destino]['fusiones'].append({
                'origen': descripcion_origen,
                'destino_original': descripcion_destino_original,
                'destino_resultado': self._descripcion_linea(linea_destino),
                'destino': "%s -> %s" % (
                    descripcion_destino_original,
                    self._descripcion_linea(linea_destino),
                ),
                'detalle_tarea': fusion_tarea_info.get('detalle_tarea'),
            })

        return resumen

    def _fusionar_tarea_en_destino(self, tarea_origen, tarea_destino, linea_destino, destino):
        self.ensure_one()
        if not tarea_origen and not tarea_destino:
            return {
                'target_task': False,
                'detalle_tarea': False,
            }

        if tarea_origen and not tarea_destino:
            self._reasignar_tareas(tarea_origen, destino)
            tarea_origen.write({'piezas_pendientes': linea_destino.quantity})
            linea_destino.task_id = tarea_origen.id
            return {
                'target_task': tarea_origen,
                'detalle_tarea': "La línea destino no tenía tarea; se reutilizó la tarea origen.",
            }

        if not tarea_origen and tarea_destino:
            if not tarea_destino.sale_order_id:
                tarea_destino.write({'piezas_pendientes': linea_destino.quantity})
            return {
                'target_task': tarea_destino,
                'detalle_tarea': "La línea origen no tenía tarea; se conservó la tarea destino.",
            }

        if tarea_origen == tarea_destino:
            if not tarea_destino.sale_order_id:
                tarea_destino.write({'piezas_pendientes': linea_destino.quantity})
            return {
                'target_task': tarea_destino,
                'detalle_tarea': "Origen y destino ya compartían la misma tarea.",
            }

        merge_result = tarea_origen.merge_into_task(
            target_task=tarea_destino,
            pending_service=destino,
            pending_service_line=linea_destino,
        )

        if not tarea_destino.sale_order_id:
            tarea_destino.write({'piezas_pendientes': linea_destino.quantity})

        tarea_destino.message_post(
            body=Markup(
                "<b>Fusión de tarea aplicada</b><br/>"
                "La tarea <b>%s</b> fue integrada en esta tarea desde el servicio <b>%s</b>."
            ) % (tarea_origen.display_name, self.servicio_o.display_name),
            message_type='comment',
            subtype_xmlid='mail.mt_note',
        )
        vals_origen = {'servicio_pendiente': False}
        if 'active' in tarea_origen._fields:
            vals_origen['active'] = False
        tarea_origen.write(vals_origen)
        tarea_origen.message_post(
            body=Markup(
                "<b>Tarea absorbida por fusión</b><br/>"
                "Esta tarea fue integrada en <b>%s</b> dentro del servicio <b>%s</b>."
            ) % (tarea_destino.display_name, destino.display_name),
            message_type='comment',
            subtype_xmlid='mail.mt_note',
        )
        moved = merge_result.get('moved', {})
        detalle_tarea = (
            "Tarea final: %s. Avances: %s, Gastos: %s, Compras: %s, Horas: %s, "
            "Mov. almacén: %s, Requisiciones: %s, Regularizaciones: %s, Compensaciones: %s."
        ) % (
            tarea_destino.display_name,
            moved.get('avances', 0),
            moved.get('gastos', 0),
            moved.get('compras', 0),
            moved.get('horas', 0),
            moved.get('mov_almacen', 0),
            moved.get('requisiciones', 0),
            moved.get('regularizaciones', 0),
            moved.get('compensaciones', 0),
        )
        return {
            'target_task': tarea_destino,
            'detalle_tarea': detalle_tarea,
        }

    # Mover líneas en modo todo
    def _mover_lineas_al_destino(self):
        self.ensure_one()
        origen  = self.servicio_o
        destino = self.servicio_d
        lineas  = origen.service_line_ids

        if not lineas:
            raise ValidationError(
                "El servicio origen '%s' no tiene líneas de servicio." % origen.name
            )

        cantidad = len(lineas)
        tareas   = lineas.mapped('task_id').filtered(lambda t: t)
        avances  = self.env['project.sub.update'].search([('pending_service_id', '=', origen.id)])

        lineas.write({'service_id': destino.id})
        self._reasignar_tareas(tareas, destino)
        self._reasignar_avances(avances, destino)
        return {
            'cantidad': cantidad,
            'lineas': lineas,
        }

    # Modo por línea
    def _mover_lineas_por_destino(self):
        self.ensure_one()
        origen  = self.servicio_o
        resumen = {}

        if not self.lineas_seleccion:
            raise ValidationError("No hay líneas cargadas para distribuir.")

        lineas_a_mover = self.lineas_seleccion.filtered(lambda l: l.servicio_destino)
        if not lineas_a_mover:
            raise ValidationError("Debes asignar destino al menos a una línea para continuar.")

        # Agrupar por destino
        grupos = {}
        for sel in lineas_a_mover:
            if not sel.linea_id or sel.linea_id.service_id != origen:
                raise ValidationError(
                    "La línea '%s' no pertenece al servicio origen actual."
                    % (sel.nombre_linea or sel.linea_id.display_name)
                )
            errores_destino = self._validar_destino(sel.servicio_destino)
            if errores_destino:
                raise ValidationError("\n".join("• %s" % error for error in errores_destino))
            grupos.setdefault(sel.servicio_destino, self.env['pending.service.line'])
            grupos[sel.servicio_destino] |= sel.linea_id

        for destino, lineas in grupos.items():
            tareas = lineas.mapped('task_id').filtered(lambda t: t)
            lineas.write({'service_id': destino.id})
            self._reasignar_tareas(tareas, destino)
            self._reasignar_avances_por_lineas(lineas, destino)
            if destino not in resumen:
                resumen[destino] = {
                    'cantidad': 0,
                    'lineas': self.env['pending.service.line'],
                }
            resumen[destino]['cantidad'] += len(lineas)
            resumen[destino]['lineas'] |= lineas

        return resumen

    # Reasignaciones 
    def _reasignar_tareas(self, tareas, destino):
        self.ensure_one()
        if tareas:
            proyecto_destino = destino.supervisor_id.proyecto_supervisor
            proyectos_actuales = tareas.mapped('project_id').filtered(lambda p: p)
            if not proyecto_destino and proyectos_actuales:
                raise ValidationError(
                    "El servicio destino '%s' no tiene un proyecto asignado en el supervisor. "
                    "No es posible reasignar tareas a un servicio con proyecto indefinido."
                    % destino.display_name
                )

            for tarea in tareas:
                vals_tarea = {'servicio_pendiente': destino.id}
                if proyecto_destino and tarea.project_id and tarea.project_id.id != proyecto_destino.id:
                    vals_tarea['project_id'] = proyecto_destino.id

                ajuste_fechas = self._preparar_fechas_tarea_para_destino(tarea, destino)
                vals_tarea.update(ajuste_fechas['vals'])
                tarea.write(vals_tarea)
                if ajuste_fechas['hubo_ajuste']:
                    self._registrar_ajuste_fechas_tarea(
                        tarea=tarea,
                        destino=destino,
                        fecha_inicio_original=ajuste_fechas['fecha_inicio_original'],
                        fecha_fin_original=ajuste_fechas['fecha_fin_original'],
                        fecha_inicio_nueva=ajuste_fechas['fecha_inicio_nueva'],
                        fecha_fin_nueva=ajuste_fechas['fecha_fin_nueva'],
                    )

    def _preparar_fechas_tarea_para_destino(self, tarea, destino):
        self.ensure_one()
        vals = {}
        pending_start = destino.date_start
        pending_end = destino.date_end_plan

        task_start = tarea.planned_date_begin
        task_end = tarea.date_deadline

        if pending_start and task_start and task_start < pending_start:
            vals['planned_date_begin'] = pending_start
        if pending_end and task_end and task_end > pending_end:
            vals['date_deadline'] = pending_end

        nuevo_inicio = vals.get('planned_date_begin', task_start)
        nuevo_fin = vals.get('date_deadline', task_end)

        if pending_start and pending_end:
            if nuevo_inicio and nuevo_fin and nuevo_inicio > nuevo_fin:
                vals['planned_date_begin'] = pending_start
                vals['date_deadline'] = pending_end
            elif not nuevo_inicio and nuevo_fin and nuevo_fin < pending_start:
                vals['planned_date_begin'] = pending_start
                vals['date_deadline'] = pending_end
            elif nuevo_inicio and not nuevo_fin and nuevo_inicio > pending_end:
                vals['planned_date_begin'] = pending_start
                vals['date_deadline'] = pending_end

        return {
            'vals': vals,
            'hubo_ajuste': bool(vals),
            'fecha_inicio_original': task_start,
            'fecha_fin_original': task_end,
            'fecha_inicio_nueva': vals.get('planned_date_begin', task_start),
            'fecha_fin_nueva': vals.get('date_deadline', task_end),
        }

    def _registrar_ajuste_fechas_tarea(self, tarea, destino, fecha_inicio_original,
                                       fecha_fin_original, fecha_inicio_nueva,
                                       fecha_fin_nueva):
        self.ensure_one()
        mensaje = Markup(
            "<b>Ajuste automático de fechas por reasignación</b><br/>"
            "Tarea: <b>%s</b><br/>"
            "Servicio destino: <b>%s</b><br/>"
            "Inicio: <b>%s</b> → <b>%s</b><br/>"
            "Fin: <b>%s</b> → <b>%s</b><br/>"
            "<i>Las fechas se normalizaron para respetar el rango del servicio pendiente destino.</i>"
        ) % (
            tarea.display_name,
            destino.display_name,
            fields.Datetime.to_string(fecha_inicio_original) or '-',
            fields.Datetime.to_string(fecha_inicio_nueva) or '-',
            fields.Datetime.to_string(fecha_fin_original) or '-',
            fields.Datetime.to_string(fecha_fin_nueva) or '-',
        )
        tarea.message_post(
            body=mensaje,
            message_type='comment',
            subtype_xmlid='mail.mt_note',
        )
        destino.message_post(
            body=mensaje,
            message_type='comment',
            subtype_xmlid='mail.mt_note',
        )

    def _reasignar_avances(self, avances, destino):
        self.ensure_one()
        if avances:
            avances.write({'pending_service_id': destino.id})

    def _reasignar_avances_por_lineas(self, lineas, destino):
        self.ensure_one()
        if not lineas:
            return

        avances = self.env['project.sub.update'].search([
            ('pending_service_line_id', 'in', lineas.ids),
        ])
        if not avances:
            return

        avances.write({'pending_service_id': destino.id})

        for linea in lineas.filtered(lambda item: item.task_id):
            avances_linea = avances.filtered(lambda avance: avance.pending_service_line_id == linea)
            if not avances_linea:
                continue

            vals_avance = {'task_id': linea.task_id.id}
            if linea.task_id.project_id:
                vals_avance['project_id'] = linea.task_id.project_id.id
            avances_linea.write(vals_avance)

    # Chatter modo todo
    def _registrar_chatter(self, detalle_fusion):
        self.ensure_one()
        origen  = self.servicio_o
        destino = self.servicio_d
        usuario = self.env.user.name
        cantidad_lineas = detalle_fusion['cantidad']
        detalle_lineas = self._formatear_detalle_lineas(detalle_fusion['lineas'])
        origen_link = self._link_a_registro(origen, "Ver servicio origen")
        destino_link = self._link_a_registro(destino, "Ver servicio destino")

        origen.message_post(
            body=Markup(
                "<b>🔀 Reasignación ejecutada (modo: todas las líneas)</b><br/>"
                "Líneas transferidas a <b>%s</b>: <b>%d</b><br/>"
                "%s<br/>"
                "Detalle de líneas:<br/><ul>%s</ul>"
                "Ejecutado por: <b>%s</b><br/>"
                "<i>Este registro será archivado automáticamente.</i>"
            ) % (destino.name, cantidad_lineas, destino_link, detalle_lineas, usuario),
            message_type='comment', subtype_xmlid='mail.mt_note',
        )
        destino.message_post(
            body=Markup(
                "<b>🔀 Reasignación recibida (modo: todas las líneas)</b><br/>"
                "Líneas recibidas de <b>%s</b>: <b>%d</b><br/>"
                "%s<br/>"
                "Detalle de líneas:<br/><ul>%s</ul>"
                "Ejecutado por: <b>%s</b>"
            ) % (origen.name, cantidad_lineas, origen_link, detalle_lineas, usuario),
            message_type='comment', subtype_xmlid='mail.mt_note',
        )

    # Chatter modo por línea
    def _registrar_chatter_por_linea(self, resumen):
        self.ensure_one()
        origen  = self.servicio_o
        usuario = self.env.user.name
        origen_link = self._link_a_registro(origen, "Ver servicio origen")

        detalle = Markup("").join(
            Markup("<li>%s<br/><b>%s</b>: %d línea(s)<ul>%s</ul></li>") % (
                self._link_a_registro(dest, "Ver servicio destino"),
                dest.name,
                info['cantidad'],
                self._formatear_detalle_lineas(info['lineas']),
            )
            for dest, info in resumen.items()
        )
        origen.message_post(
            body=Markup(
                "<b>🔀 Reasignación ejecutada (modo: por línea)</b><br/>"
                "Destino(s) relacionados desde este origen.<br/>"
                "Líneas distribuidas a:<br/><ul>%s</ul>"
                "Ejecutado por: <b>%s</b><br/>"
                "<i>Este registro será archivado automáticamente.</i>"
            ) % (detalle, usuario),
            message_type='comment', subtype_xmlid='mail.mt_note',
        )
        for destino, info in resumen.items():
            destino.message_post(
                body=Markup(
                    "<b>🔀 Reasignación recibida (modo: por línea)</b><br/>"
                    "Líneas recibidas de <b>%s</b>: <b>%d</b><br/>"
                    "%s<br/>"
                    "Detalle de líneas:<br/><ul>%s</ul>"
                    "Ejecutado por: <b>%s</b>"
                ) % (
                    origen.name,
                    info['cantidad'],
                    origen_link,
                    self._formatear_detalle_lineas(info['lineas']),
                    usuario,
                ),
                message_type='comment', subtype_xmlid='mail.mt_note',
            )

    def _registrar_chatter_fusion(self, resumen):
        self.ensure_one()
        origen = self.servicio_o
        usuario = self.env.user.name
        origen_link = self._link_a_registro(origen, "Ver servicio origen")

        detalle = Markup("").join(
            Markup("<li>%s<br/><b>%s</b>: %d fusion(es)<ul>%s</ul></li>") % (
                self._link_a_registro(destino, "Ver servicio destino"),
                destino.display_name,
                info['cantidad'],
                Markup("").join(
                    Markup("<li>%s <b>se integró en</b> %s%s</li>") % (
                        fusion['origen'],
                        fusion['destino'],
                        Markup("<br/><i>%s</i>" % fusion['detalle_tarea']) if fusion.get('detalle_tarea') else Markup(""),
                    )
                    for fusion in info['fusiones']
                ),
            )
            for destino, info in resumen.items()
        )

        origen.message_post(
            body=Markup(
                "<b>🔀 Fusión ejecutada</b><br/>"
                "Destino(s) relacionados desde este origen.<br/>"
                "Líneas integradas en destino:<br/><ul>%s</ul>"
                "Ejecutado por: <b>%s</b><br/>"
                "<i>El origen se archivará sólo si quedó sin líneas.</i>"
            ) % (detalle, usuario),
            message_type='comment', subtype_xmlid='mail.mt_note',
        )

        for destino, info in resumen.items():
            detalle_destino = Markup("").join(
                Markup("<li>%s <b>se integró en</b> %s%s</li>") % (
                    fusion['origen'],
                    fusion['destino'],
                    Markup("<br/><i>%s</i>" % fusion['detalle_tarea']) if fusion.get('detalle_tarea') else Markup(""),
                )
                for fusion in info['fusiones']
            )
            destino.message_post(
                body=Markup(
                    "<b>🔀 Fusión recibida</b><br/>"
                    "%s<br/>"
                    "Líneas absorbidas:<br/><ul>%s</ul>"
                    "Ejecutado por: <b>%s</b>"
                ) % (origen_link, detalle_destino, usuario),
                message_type='comment', subtype_xmlid='mail.mt_note',
            )

    # Archivar origen 
    def _archivar_origen(self):
        self.ensure_one()
        if not self.servicio_o.service_line_ids:
            self.servicio_o.write({'active': False})

    def _formatear_detalle_lineas(self, lineas):
        self.ensure_one()
        return Markup("").join(
            Markup("<li>%s</li>") % self._descripcion_linea(linea)
            for linea in lineas
        )

    def _descripcion_linea(self, linea):
        self.ensure_one()
        partes = []
        if linea.partida:
            partes.append("Partida %s" % linea.partida)
        if linea.product_id:
            partes.append(linea.product_id.display_name)
        if linea.quantity:
            partes.append("Cantidad: %s" % linea.quantity)
        return " - ".join(partes) or linea.display_name

    def _link_a_registro(self, record, etiqueta=None):
        self.ensure_one()
        if not record:
            return Markup("")
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
        nombre = etiqueta or record.display_name
        url = "%s/web#id=%s&model=%s&view_type=form" % (
            base_url,
            record.id,
            quote(record._name),
        )
        return Markup('<a href="%s" target="_blank">%s</a>') % (url, nombre)

    def _mensaje_exito_fusion(self):
        self.ensure_one()
        if self.proceso == 'fusion':
            origen_archivado = not self.servicio_o.active
            return _(
                "Se fusionaron %(lineas)s línea(s) en %(destinos)s destino(s). %(estado_origen)s"
            ) % {
                'lineas': self.total_lineas_a_mover,
                'destinos': self.total_destinos,
                'estado_origen': _(
                    "El origen fue archivado."
                ) if origen_archivado else _(
                    "El origen conserva líneas no fusionadas y permanece activo."
                ),
            }
        if self.modo_reasignacion == 'todo':
            return _(
                "Se movieron %(lineas)s línea(s) al servicio %(destino)s. El origen fue archivado."
            ) % {
                'lineas': self.total_lineas_origen,
                'destino': self.servicio_d.display_name,
            }
        lineas_movidas = len(self.lineas_seleccion.filtered(lambda l: l.servicio_destino))
        origen_archivado = not self.servicio_o.active
        return _(
            "Se distribuyeron %(lineas)s línea(s) entre %(destinos)s destino(s). %(estado_origen)s"
        ) % {
            'lineas': lineas_movidas,
            'destinos': self.total_destinos,
            'estado_origen': _(
                "El origen fue archivado."
            ) if origen_archivado else _(
                "El origen conserva líneas sin mover y permanece activo."
            ),
        }

    def _mensaje_exito_fusion_resumen(self, resumen):
        self.ensure_one()
        lineas_fusionadas = sum(info['cantidad'] for info in resumen.values())
        origen_archivado = not self.servicio_o.service_line_ids
        return _(
            "Se fusionaron %(lineas)s línea(s) en %(destinos)s destino(s). %(estado_origen)s"
        ) % {
            'lineas': lineas_fusionadas,
            'destinos': len(resumen),
            'estado_origen': _(
                "El origen fue archivado."
            ) if origen_archivado else _(
                "El origen conserva líneas no fusionadas y permanece activo."
            ),
        }

    def _mensaje_exito_reasignacion_todo(self, detalle_fusion):
        self.ensure_one()
        return _(
            "Se reasignaron %(lineas)s línea(s) al servicio %(destino)s."
        ) % {
            'lineas': detalle_fusion['cantidad'],
            'destino': self.servicio_d.display_name,
        }

    def _mensaje_exito_reasignacion_por_linea(self, resumen):
        self.ensure_one()
        lineas_movidas = sum(info['cantidad'] for info in resumen.values())
        return _(
            "Se reasignaron %(lineas)s línea(s) entre %(destinos)s destino(s)."
        ) % {
            'lineas': lineas_movidas,
            'destinos': len(resumen),
        }