# models/supervisor_area.py
from odoo import models, fields, api, _
from datetime import datetime
from odoo.exceptions import ValidationError

class SupervisorArea(models.Model):
    _name = 'supervisor.area'
    _description = 'Supervisor de Area'

    name = fields.Char(string='Nombre', required=True)
    cliente = fields.Many2one('res.partner', string='Cliente', required=True)

class Generator(models.Model):
    _name = 'license.generator'
    _description = 'Generadorista'

    name = fields.Char(string='Nombre del Generadorista', required=True)

class Disciplina(models.Model):
    _name = 'license.disciplina'
    _description = 'Disciplina'
    _sql_constraints = [
        ('name_unique', 'unique(name)', 'El nombre de la disciplina debe ser único.')
    ]

    name = fields.Char(string='Disciplina', required=True)
    sequence_id = fields.Many2one('ir.sequence', string='Secuencia', readonly=True)
    sequence_generated = fields.Boolean(string='Secuencia Generada', default=False, readonly=True)

    def generate_sequence(self):
        for disciplina in self:
            if not disciplina.sequence_id:
                prefix = disciplina.name[:3].upper()
                sequence_vals = {
                    'name': f'Secuencia para {disciplina.name}',
                    'code': f'PEND{prefix}',
                    'prefix': f'PEND{prefix}',
                    'suffix': '/%(year)s',  # Sufijo con el año actual
                    'padding': 4,
                    'company_id': False,
                }
                sequence = self.env['ir.sequence'].create(sequence_vals)
                disciplina.sequence_id = sequence
                disciplina.sequence_generated = True


    @api.constrains('name')
    def _check_name_length(self):
        for disciplina in self:
            if len(disciplina.name) < 3:
                raise ValidationError(_('El nombre de la disciplina debe tener al menos 3 caracteres.'))

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for record in records:
            prefix = record.name[:3].upper()
            sequence_vals = {
                'name': f'Secuencia para {record.name}',
                'code': f'PEND{prefix}',
                'prefix': f'PEND{prefix}',
                'suffix': '/%(year)s',  # Sufijo con el año actual
                'padding': 4,
                'company_id': False,
            }
            sequence = self.env['ir.sequence'].create(sequence_vals)
            record.sequence_id = sequence
            record.sequence_generated = True
        return records
        
class License(models.Model):
    _name = 'license.license'
    _description = 'Licencia'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(string='Nombre de la Licencia', required=True, tracking=True)
    date = fields.Date(string='Fecha', default=datetime.today(), tracking=True)
    supervisor_id = fields.Many2one('hr.employee', string='Supervisor', tracking=True)
    hours_reported = fields.Float(string='Horas Reportadas', tracking=True)
    pedido = fields.Text(string='Pedido', tracking=True)  # Nuevo campo
    pend = fields.Text(string='OR/Pendiente', tracking=True)  # Nuevo campo
    ot = fields.Char(string='OT', tracking=True)  # Nuevo campo
    disc = fields.Many2one('license.disciplina', string='Disciplina', tracking=True)
    notes = fields.Text(string='Notas', tracking=True)  # Nuevo campo
    state = fields.Selection([
        ('no_ent', 'No entregada'),
        ('ent', 'Entregada'),
        ('gen', 'Generadorista'),
        ('fact', 'Facturada'),
        ('canc', 'Cancelada'),
    ], string='Estado', default='no_ent', tracking=True)
    generator_id = fields.Many2one('license.generator', string='Generadorista', tracking=True)

    def action_print_report(self):
        # Verificar si hay múltiples registros seleccionados
        if len(self) > 1:
            # Si hay múltiples registros, generar el informe para cada uno
            for record in self:
                # Lógica para generar el informe para cada registro
                # Puedes usar un método auxiliar si es necesario
                record._generate_report()
            return {
                'type': 'ir.actions.act_window_close',
            }
        else:
            # Si solo hay un registro, generar el informe para ese registro
            self.ensure_one()
            # Lógica para generar el informe para el registro único
            self._generate_report()
            return {
                'type': 'ir.actions.act_window_close',
            }

    def _generate_report(self):
        # Lógica para generar el informe
        # Aquí puedes usar self.env.ref para referenciar el informe y luego llamar a report_action
        report_action = self.env.ref('project.action_print_license_report').report_action(self)
        return report_action