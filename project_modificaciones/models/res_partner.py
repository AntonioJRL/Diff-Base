import random
from odoo import api, fields, models


class ResPartner(models.Model):
    _inherit = 'res.partner'

    def _get_color(self):
        return random.randint(1, 11)

    project_tag_id = fields.Many2many('project.tags', 'Especialidad')
    color = fields.Integer(string='Color', default=_get_color)

    centro_trabajo = fields.One2many(
        'control.centro.trabajo',
        'cliente',
        string="Centro de Trabajo"
    )

    tipo_contacto = fields.Selection(
        [
            ('cliente', 'Cliente'),
            ('supervisor', 'Supervisor')
        ],
        string="Tipo de Contacto",
        # tracking=True removed to prevent UndefinedColumn error during update
    )

    # Método que permite cambiar la estructura del nommbre del Contacto Persona De (EMPRESA, NOMBRE CONTACTO) A (NOMBRE CONTACTO)
    @api.depends('is_company', 'name', 'parent_id.name')
    def _compute_display_name(self):
        """Override para mostrar solo el nombre del contacto cuando es persona con empresa"""
        for partner in self:
            if not partner.is_company and partner.parent_id:
                # Persona con empresa: mostrar solo el nombre
                partner.display_name = partner.name
            else:
                # Empresa o contacto sin padre: comportamiento normal
                super(ResPartner, partner)._compute_display_name()

    cliente_obra = fields.Boolean(
        string="Cliente Obra",
        default=False,
        help="Marque esta casilla para indicar que este cliente es un cliente de obra."
    )
