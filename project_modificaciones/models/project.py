from odoo import api, fields, models, _
from odoo.exceptions import ValidationError
from datetime import datetime

class Project(models.Model):
    _inherit = 'project.project'

    # -------------------------------------------------------------------------
    # CAMPOS DE INTEGRACIÓN CON VENTAS (Sale Order)
    # -------------------------------------------------------------------------
    sale_line_id = fields.Many2one(
        'sale.order.line', 'Sales Order Item', copy=False,
        compute="_compute_sale_line_id", store=True, readonly=False, index='btree_not_null',
        domain="[('is_service', '=', True), ('is_expense', '=', False), ('state', 'in', ['sale', 'done']), ('order_partner_id', '=?', partner_id), '|', ('company_id', '=', False), ('company_id', '=', company_id)]",
        help="Sales order item that will be selected by default on the tasks and timesheets of this project,"
             " except if the employee set on the timesheets is explicitely linked to another sales order item on the project.\n"
             "It can be modified on each task and timesheet entry individually if necessary.")
    
    sale_order_id = fields.Many2one(
        string='Pedido de Venta', 
        related='sale_line_id.order_id', 
        help="Sales order to which the project is linked.", 
        store=True
    )

    state = fields.Selection(
        string="Estado de la venta",
        related="sale_order_id.state", 
        store=True
    )

    cliente = fields.Many2one(
        string="Cliente", 
        related='sale_line_id.order_id.partner_id'
    )
    
    invoiced = fields.Float(
        string="Facturado", 
        compute="_invoiced", 
        store=True
    )
    
    # Equipo de venta en revision
    team_id = fields.Many2one(
        string="Sales Team", 
        related="sale_order_id.team_id", 
        store=True
    )

    # -------------------------------------------------------------------------
    # CAMPOS NUEVOS (Coordinación y Obra)
    # -------------------------------------------------------------------------
    is_proyecto_obra = fields.Boolean(
        string="Proyecto Obra",
        default=False,
        store=True,
    )

    coordinador = fields.Many2one(
        "hr.employee",
        string="Coordinador",
        tracking=True,
    )

    supervisor = fields.Many2one(
        "hr.employee",
        string="Supervisor",
        tracking=True,
    )

    # -------------------------------------------------------------------------
    # RELACIÓN CON AVANCES (Project Sub Update / Creacion Avances)
    # -------------------------------------------------------------------------
    sub_update_ids = fields.One2many('project.sub.update', 'project_id')

    # -------------------------------------------------------------------------
    # CAMPOS COMPUTADOS (Financieros del Proyecto)
    # -------------------------------------------------------------------------
    sale_actual = fields.Float(string="Subtotal entregado", compute="_sale_actual", store=True)
    sale_total = fields.Float(string="Subtotal de la venta", compute="_sale_total", store=True)
    sale_missing = fields.Float(string="Subtotal faltante", compute="_sale_missing", store=True)
    
    sale_actual_text = fields.Char(string='Subtotal entregado (pesos)', compute='_sale_actual_text', store=True)
    sale_total_text = fields.Char(string='Subtotal de la venta (pesos)', compute='_sale_total_text', store=True)
    sale_missing_text = fields.Char(string='Subtotal faltante (pesos)', compute='_sale_missing_text', store=True)

    # -------------------------------------------------------------------------
    # MÉTODOS COMPUTADOS (Lógica mejorada con protección NewId)
    # -------------------------------------------------------------------------

    @api.depends('sale_line_id.qty_invoiced')
    def _invoiced(self):
        for u in self:
            # Solo realizar la búsqueda si el proyecto ya tiene un ID persistente
            if not isinstance(u.id, models.NewId):
                sale = u.env['project.task'].search([('project_id', '=', u.id)]).mapped('invoiced')
                u.invoiced = sum(sale)
            else:
                u.invoiced = 0.0 # Valor por defecto para registros nuevos
    
    @api.depends('sub_update_ids', 'sub_update_ids.unit_progress', 'sub_update_ids.task_id')
    def _sale_actual(self):
        for u in self:
            # Solo realizar la búsqueda si el proyecto ya tiene un ID persistente
            if not isinstance(u.id, models.NewId):
                # Nota: Mantenemos la lógica de búsqueda original del archivo inherit
                sale = u.env['project.update'].search([('project_id', '=', u.id)]).mapped('sale_current')
                u.sale_actual = sum(sale)
            else:
                u.sale_actual = 0.0 # Valor por defecto para registros nuevos
    
    @api.depends('sub_update_ids', 'sub_update_ids.unit_progress', 'sub_update_ids.task_id')
    def _sale_total(self):
        for u in self:
            # Solo realizar la búsqueda si el proyecto ya tiene un ID persistente
            if not isinstance(u.id, models.NewId):
                sale = u.env['project.task'].search([('project_id', '=', u.id)]).mapped('price_subtotal')
                u.sale_total = sum(sale)
            else:
                u.sale_total = 0.0 # Valor por defecto para registros nuevos
    
    @api.depends('sale_total', 'sale_actual') # Dependencia optimizada
    def _sale_missing(self):
        for u in self:
            u.sale_missing = u.sale_total - u.sale_actual
    
    # Métodos de texto optimizados (Dependen de los campos float, no recalculan todo)
    @api.depends('sale_actual') 
    def _sale_actual_text(self):
        for u in self:
            sale = "%.2f" % u.sale_actual
            value_len = sale.find('.')
            for i in range(value_len, 0, -1):
                sale = sale[:i] + ',' + sale[i:] if (value_len-i) % 3 == 0 and value_len != i else sale
            u.sale_actual_text = '$' + sale
    
    @api.depends('sale_total') 
    def _sale_total_text(self):
        for u in self:
            sale = "%.2f" % u.sale_total
            value_len = sale.find('.')
            for i in range(value_len, 0, -1):
                sale = sale[:i] + ',' + sale[i:] if (value_len-i) % 3 == 0 and value_len != i else sale
            u.sale_total_text = '$' + sale

    @api.depends('sale_missing') 
    def _sale_missing_text(self):
        for u in self:
            sale = "%.2f" % u.sale_missing
            value_len = sale.find('.')
            for i in range(value_len, 0, -1):
                sale = sale[:i] + ',' + sale[i:] if (value_len-i) % 3 == 0 and value_len != i else sale
            u.sale_missing_text = '$' + sale

    # -------------------------------------------------------------------------
    # ACCIONES Y CREACIÓN (Lógica nueva)
    # -------------------------------------------------------------------------

    def action_view_avances(self):
        return {
            'name': _("Avances de Proyecto"),
            'type': 'ir.actions.act_window',
            'res_model': 'project.sub.update', # Actualizado al nuevo modelo unificado
            'view_mode': 'list,form',
            'domain': [('project_id', '=', self.id)],
            'context': {
                'default_project_id': self.id,
            },
            'target': 'current',
        }

    @api.model_create_multi
    def create(self, vals_list):
        # 1. Crear proyectos
        projects = super(Project, self).create(vals_list)
        
        # 2. Asignar etapas por defecto si es proyecto de obra
        for project in projects:
            if project.is_proyecto_obra:
                # Buscar las etapas de Control de Obra
                stages = self.env['project.task.type'].search([
                    ('is_control_obra_stage', '=', True)
                ])
                if stages:
                    project.type_ids = [(6, 0, stages.ids)]
        
        return projects

    def action_open_profitability_dashboard(self):
        self.ensure_one()
        wizard = self.env['project.profitability.report'].create({
            'project_ids': [(6, 0, [self.id])],
            'filter_type': 'all'
        })
        return {
            'type': 'ir.actions.act_window',
            'name': _('Rentabilidad Avanzada'),
            'res_model': 'project.profitability.report',
            'res_id': wizard.id,
            'view_mode': 'form',
            'target': 'current',
        }