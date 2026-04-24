from odoo import fields, models

class FusionServiciosPendientesLineas(models.TransientModel):
    _name = 'fusion.servicios.pendientes.linea'   # ← sin 's' al final
    _description = 'Línea de Fusión de Servicios Pendientes'

    wizard_id = fields.Many2one(
        'fusion.servicios.pendientes',
        string='Wizard',
        required=True,
        ondelete='cascade',
    )
    linea_id = fields.Many2one(
        'pending.service.line',
        string="Línea de Servicio",
        required=True,
    )
    nombre_linea = fields.Char(
        compute='_compute_nombre_linea',
        string='Línea',
    )
    partida_linea = fields.Integer(
        related='linea_id.partida',
        string="Partida",
    )
    producto_id = fields.Many2one(
        related='linea_id.product_id',
        string='Producto',
    )
    cantidad = fields.Float(
        related='linea_id.quantity',
        string='Cantidad',
    )
    total_linea = fields.Float(
        related='linea_id.total',
        string='Total',
    )
    task_id = fields.Many2one(
        related='linea_id.task_id',
        string="Tarea",
    )
    servicio_destino = fields.Many2one(
        'pending.service',
        string="Servicio Destino",
        help="Pendiente al que se moverá esta línea específica.",
    )
    linea_destino_id = fields.Many2one(
        'pending.service.line',
        string='Línea Destino',
        help='Línea existente del servicio destino que absorberá esta línea.',
    )

    def _compute_nombre_linea(self):
        for record in self:
            if record.linea_id:
                record.nombre_linea = record.linea_id.display_name
            else:
                record.nombre_linea = False
