from odoo import api, fields, models

class ProjectTags(models.Model):
    _inherit = 'project.tags'
    
    responsible_id = fields.Many2one('res.users', 'Responsable')
    partner_ids = fields.Many2many('res.partner', 'res_partner_project_tags_rel', 'project_tag_id', string='Clientes')
    
    project_count = fields.Integer(string='Cantidad de proyectos', compute='_project_count', default=0)
    label_project = fields.Char(string='Etiqueta proyectos', default='Proyectos', readonly=True)
    description = fields.Text('Descripción')
    
    def open_view_project_all(self):
        action = self.env['ir.actions.act_window'].with_context({'active_id': self.id})._for_xml_id('project.open_view_project_all')
        domain = [('tag_ids', 'like', self.id)]
        action['domain'] = domain
        return action

    def _project_count(self):
        for u in self:
            count = len(u.env['project.project'].search([('tag_ids', 'like', u.id)]))
            u.project_count = count
