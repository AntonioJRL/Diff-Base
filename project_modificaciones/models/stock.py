from odoo import fields, models, api


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    project_id = fields.Many2one(
        'project.project', string='Proyecto', index=True, copy=False)
    task_id = fields.Many2one(
        'project.task', string='Tarea', index=True, copy=False)


class StockMove(models.Model):
    _inherit = 'stock.move'

    project_id = fields.Many2one(
        'project.project', string='Proyecto', index=True, copy=False)
    task_id = fields.Many2one(
        'project.task', string='Tarea', index=True, copy=False)

    importe = fields.Float(
        string="Importe",
        compute="_compute_import",
        store=True,
    )

    @api.depends('product_qty', 'price_unit')
    def _compute_import(self):
        for move in self:
            subtotal = move.product_qty * move.price_unit
            move.importe = subtotal
