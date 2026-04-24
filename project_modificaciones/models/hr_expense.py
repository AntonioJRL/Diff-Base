"""
Extensión de Gastos (hr.expense)
- Enlaza el gasto con una tarea de proyecto (`task_id`) para rastrear costos
  por tarea y alimentar dashboards.
"""
from odoo import fields, models, api


class HrExpense(models.Model):
    _inherit = 'hr.expense'

    # Enlace al proyecto relacionado al gasto
    project_id = fields.Many2one(
        'project.project', 
        string='Proyecto',
        tracking=True,
    )

    # Enlace opcional a la tarea relacionada al gasto
    task_id = fields.Many2one(
        'project.task', 
        string='Tarea',
        tracking=True,
    )

    # -------------------------------------------------------------------------
    # MÉTODO ONCHANGE: Auto-asignar Analítica desde el Proyecto/Tarea
    # -------------------------------------------------------------------------
    @api.onchange('task_id', 'project_id')
    def _onchange_set_analytic_distribution(self):
        """
        Al seleccionar una Tarea o Proyecto, busca si ese proyecto tiene una 
        Cuenta Analítica asociada y la pre-carga en la distribución al 100%.
        """
        for expense in self:
            # 1. Determinar el proyecto prioritario (Tarea > Proyecto directo)
            project = False
            if expense.task_id and expense.task_id.project_id:
                project = expense.task_id.project_id
                # NUEVO: Asignar proyecto si la tarea lo dicta
                expense.project_id = project
            elif expense.project_id:
                project = expense.project_id

            # 2. Si encontramos proyecto y tiene cuenta analítica...
            if project and project.analytic_account_id:
                # Odoo 17 requiere formato: {'id_str': porcentaje}
                analytic_account_id = str(project.analytic_account_id.id)

                # Asignamos la distribución (Sobrescribe si estaba vacía o si cambiamos de tarea)
                expense.analytic_distribution = {analytic_account_id: 100}