from odoo import models, fields, api, _
from odoo.exceptions import UserError
from odoo.tools import Markup
import logging

_logger = logging.getLogger(__name__)


class ProjectSubUpdateReclassifyWizard(models.TransientModel):
    _name = 'project.sub.update.reclassify.wizard'
    _description = 'Asistente de Reasignación de Avances'

    project_id = fields.Many2one(
        'project.project', string='Nuevo Proyecto', required=True,
        help="Selecciona el proyecto al cual se moverán los avances.")

    task_id = fields.Many2one(
        'project.task', string='Nueva Tarea',
        domain="[('project_id', '=', project_id)]",
        help="Selecciona la tarea destino (opcional).")

    update_id = fields.Many2one(
        'project.update', string='Actualización',
        domain="[('project_id', '=', project_id)]",
        help="Selecciona la actualización del proyecto (opcional).")

    project_sub_update_ids = fields.Many2many(
        'project.sub.update', string='Avances',
        help="Avances a reclasificar.")

    # Estado Actual (Solo lectura, para referencia visual si aplica)
    current_project_id = fields.Many2one(
        'project.project', string='Proyecto Actual (Referencia)', readonly=True,
        help="Muestra el proyecto del primer registro seleccionado.")

    @api.model
    def default_get(self, fields):
        res = super(ProjectSubUpdateReclassifyWizard, self).default_get(fields)
        active_model = self.env.context.get('active_model')
        active_ids = self.env.context.get('active_ids')

        # Si se abre desde la vista de lista (binding)
        # Si se abre desde la vista de lista (binding)
        if active_model == 'project.sub.update' and active_ids:
            res['project_sub_update_ids'] = [(6, 0, active_ids)]

            # Intentar pre-llenar datos actuales
            records = self.env['project.sub.update'].browse(active_ids)
            if records:
                first = records[0]
                if first.project_id:
                    res['current_project_id'] = first.project_id.id

        return res

    @api.onchange('project_id')
    def _onchange_project_id(self):
        if self.project_id:
            self.task_id = False
            self.update_id = False

    def action_reclassify(self):
        """
        Ejecuta la reclasificación de los avances seleccionados.
        """
        records_to_process = self.project_sub_update_ids

        if not records_to_process:
            raise UserError(
                _("No has seleccionado ningún avance para reasignar."))

        # Preparar valores
        vals = {'project_id': self.project_id.id}

        if self.task_id:
            vals['task_id'] = self.task_id.id

        if self.update_id:
            vals['update_id'] = self.update_id.id
        else:
            # Si no se selecciona update_id, debemos limpiar el anterior si el proyecto cambió
            # Para evitar inconsistencias (update del proyecto A en registro del proyecto B)

            # Separamos en dos grupos: los que se mueven de proyecto y los que no
            # (Aunque normalmente reclasificación implica mover, podría ser mismo proyecto dif tarea)
            pass

        # Ejecución
        # 1. Limpieza de Update ID si cambia el proyecto y no se especificó uno nuevo
        if not self.update_id:
            for record in records_to_process:
                if record.project_id != self.project_id:
                    record.write({'update_id': False})

        # 2. Escritura masiva principal
        records_to_process.write(vals)

        # 3. Log en chatter
        self._log_chatter(records_to_process)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Reasignación Completada'),
                'message': _('%s avances han sido reasignados exitosamente.') % len(records_to_process),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.act_window_close'},
            }
        }

    def _log_chatter(self, records):
        """Deja un mensaje en el chatter de los registros."""
        msg = Markup("<b>%s</b><br/>%s: %s<br/>") % (
            _("Reasignación de Avance"),
            _("Nuevo Proyecto"),
            self.project_id.name
        )

        if self.task_id:
            msg += Markup("%s: %s<br/>") % (_("Nueva Tarea"),
                                            self.task_id.name)

        if self.update_id:
            msg += Markup("%s: %s<br/>") % (_("Nueva Actualización"),
                                            self.update_id.name)

        for record in records:
            if hasattr(record, 'message_post'):
                try:
                    record.message_post(body=msg)
                except Exception:
                    continue
