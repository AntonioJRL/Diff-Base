from odoo import models, fields, api, _
from odoo.exceptions import UserError

class PendingServiceWizard(models.TransientModel):
    _name = 'pending.service.wizard'
    _description = 'Asistente de Registro de Avance'

    service_id = fields.Many2one('pending.service', string='Servicio Origen', required=True, readonly=True)
    date = fields.Date(string='Fecha del Avance', default=fields.Date.context_today, required=True)
    
    # Cambiamos de Many2many a One2many con un modelo intermedio para permitir edición
    wizard_line_ids = fields.One2many('pending.service.wizard.line', 'wizard_id', string='Líneas a procesar')

    @api.model
    def default_get(self, fields_list):
        res = super(PendingServiceWizard, self).default_get(fields_list)
        active_id = self.env.context.get('active_id')
        if active_id:
            service = self.env['pending.service'].browse(active_id)
            res['service_id'] = service.id
            if service.date:
                res['date'] = service.date
            
            # Pre-cargar líneas creando registros en memoria (NewId) o lista de diccionarios
            lines_data = []
            for line in service.service_line_ids.filtered(lambda l: l.task_id):
                lines_data.append((0, 0, {
                    'service_line_id': line.id,
                    'partida': line.partida,
                    'product_id': line.product_id.id,
                    'task_id': line.task_id.id,
                    'quantity_original': line.quantity,
                    'quantity_available': line.quantity - line.total_avances,
                    'quantity_to_report': 0.0, # Por defecto 0 obligando al usuario a capturar
                }))
            res['wizard_line_ids'] = lines_data
        return res

    def action_confirm(self):
        self.ensure_one()
        service = self.service_id
        project = service.supervisor_id.proyecto_supervisor
        report_date = self.date
        
        # 1. Buscar o Crear Project Update
        update = self.env['project.update'].search([
            ('project_id', '=', project.id),
            ('date', '=', report_date)
        ], limit=1)
        
        if not update:
            update = self.env['project.update'].create({
                'project_id': project.id,
                'name': f"Avance {report_date.strftime('%d/%m/%Y')}",
                'status': 'on_track',
                'date': report_date,
            })
            
        count_created = 0
        
        # 2. Iterar sobre las líneas del WIZARD
        for w_line in self.wizard_line_ids:
            # Solo procesar si la cantidad a reportar es mayor a 0
            if w_line.quantity_to_report <= 0:
                continue

            # Validar no exceder la cantidad disponible
            if w_line.quantity_to_report > w_line.quantity_available + 0.0001:
                raise UserError(_("La cantidad a reportar (%s) para el producto %s excede la cantidad disponible (%s).") % (
                    w_line.quantity_to_report, w_line.product_id.name, w_line.quantity_available))

            # Verificar duplicados en ese update (usando la cantidad del reporte)
            # Nota: Si mandan 2 avances parciales de la misma tarea el mismo día con misma cantidad, esto lo bloquearía.
            # Quizás deberíamos relajar esto o validar mejor. 
            # Por ahora mantenemos la lógica pero con quantity_to_report.
            domain_exist = [
                ('update_id', '=', update.id),
                ('task_id', '=', w_line.task_id.id),
                ('producto', '=', w_line.product_id.id),
                ('unit_progress', '=', w_line.quantity_to_report),
            ]
            if self.env['project.sub.update'].search_count(domain_exist) > 0:
                continue

            vals = {
                'update_id': update.id,
                'project_id': project.id,
                'sale_order_id': w_line.task_id.sale_order_id.id, 
                'task_id': w_line.task_id.id,
                'date': report_date,
                'producto': w_line.product_id.id,
                'unit_progress': w_line.quantity_to_report, # Usamos la cantidad editada
                'responsible_id': service.supervisor_id.id,
                'supervisorplanta': service.supervisor_planta_id.id,
                'planta': service.planta_centro.id,
                'pending_service_id': service.id,
                'pending_service_line_id': w_line.service_line_id.id,
                'avances_state': 'draft',
                'notas': f"Generado desde {service.name}",
            }
            self.env['project.sub.update'].create(vals)
            count_created += 1
            
        if count_created == 0:
            raise UserError(_("Debe ingresar una cantidad mayor a 0 en al menos una línea para registrar un avance."))

        return {
            'type': 'ir.actions.act_window',
            'name': _('Reporte de Avance'),
            'res_model': 'project.update',
            'res_id': update.id,
            'view_mode': 'form',
            'target': 'current', 
        }

class PendingServiceWizardLine(models.TransientModel):
    _name = 'pending.service.wizard.line'
    _description = 'Línea de Asistente de Registro de Avance'

    wizard_id = fields.Many2one('pending.service.wizard', string='Wizard', ondelete='cascade')
    service_line_id = fields.Many2one('pending.service.line', string='Línea Original', required=True, readonly=True)
    
    partida = fields.Integer(string='Partida', readonly=True)
    task_id = fields.Many2one('project.task', string='Tarea', readonly=True)
    product_id = fields.Many2one('product.product', string='Producto', readonly=True)
    
    quantity_original = fields.Float(string='Cant. Total', readonly=True)
    quantity_available = fields.Float(string='Cant. Disponible', readonly=True)
    quantity_to_report = fields.Float(string='Cant. a Reportar', required=True)
