from odoo import models, fields, api

class HrEmployeeInherit(models.Model):
    _inherit = 'hr.employee'

    apropador_tarea_obra = fields.Many2one(
        'hr.employee',
        string="Tarea de Obra",
        groups="hr.group_hr_user,base.group_user",
        help="Seleccione al usuario que sera aprobador de las tareas de este empleado.",
    ) 

    proyecto_supervisor = fields.Many2one(
        'project.project',
        string="Proyecto del Supervisor",
        groups="hr.group_hr_user,base.group_user",
        help="Proyecto de control de obra asignado al supervisor.",
        tracking=True,
        domain="[('is_proyecto_obra','=', True)]"
    )