# -*- coding: utf-8 -*-
from odoo import api, fields, models


class ControlCentroTrabajo(models.Model):
    _name = 'control.centro.trabajo'
    _description = 'Centro De Trabajo'

    name = fields.Char(string='Centro De Trabajo', required=True)
    cliente = fields.Many2one('res.partner', string='Contacto', required=True)