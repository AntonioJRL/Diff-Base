from odoo import models, fields, api


class HrEmployeeInherited(models.AbstractModel):
    _inherit = 'hr.employee.base'

    supervisa = fields.Boolean(string="Marcar si este empleado es elegible para supervisar trabajos en sitio, con el fin de asignarle avances en control de obra", default=False)

# class HrEmployeeInherited(models.Model):
#     _inherit = 'hr.employee'

#     supervisa = fields.Boolean(string="Marcar si este empleado es elegible para supervisar trabajos en sitio, con el fin de asignarle avances en control de obra", default=False)
