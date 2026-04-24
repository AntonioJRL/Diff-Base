from odoo import fields, models, api, _
from markupsafe import Markup
import logging

_logger = logging.getLogger(__name__)

class SaleLine(models.Model):
    _inherit = 'sale.order.line'

    # -------------------------------------------------------------------------
    # CAMPOS DE INTEGRACIÓN
    # -------------------------------------------------------------------------

    task_id = fields.Many2one(
        "project.task", "Tarea", domain="[('sale_line_id', '=', id)]", index=True
    )

    pending_line_id = fields.Many2one(
        'pending.service.line',
        string='Línea de Servicio Pendiente',
        help='Enlace a la línea original del servicio pendiente'
    )

    # -------------------------------------------------------------------------
    # LÓGICA DE POSICIONAMIENTO Y PARTIDAS
    # -------------------------------------------------------------------------

    position = fields.Integer(readonly=True, index=True, default=False)
    position_formatted = fields.Char(compute="_compute_position_formatted")

    @api.depends("position")
    def _compute_position_formatted(self):
        for record in self:
            record.position_formatted = record._format_position(record.position)

    @api.onchange("position", "product_id") 
    def _onchange_position_update_name(self):
        for line in self:
            if line.position and line.name:
                prefix = f"P{line.position:02d} "
                if not line.name.startswith(prefix):
                    import re
                    # Remove [N] or PNN prefix
                    line.name = re.sub(r'^(\[\d+\]|P\d+)\s+', '', line.name)
                    line.name = prefix + line.name

    def _add_next_position_on_new_line(self, vals_list):
        sale_ids = [line["order_id"] for line in vals_list if line.get("order_id")]
        if sale_ids:
            ids = tuple(set(sale_ids))
            self.flush_model()
            query = """
            SELECT order_id, max(position) FROM sale_order_line
            WHERE order_id in %s GROUP BY order_id;
            """
            self.env.cr.execute(query, (ids,))
            default_pos = {key: 1 for key in ids}
            existing_pos = {order_id: pos + 1 for order_id, pos in self.env.cr.fetchall()}
            sale_pos = {**default_pos, **existing_pos}
            for line in vals_list:
                line["position"] = sale_pos[line["order_id"]]
                sale_pos[line["order_id"]] += 1
                prefix = f"P{line['position']:02d} "
                name = line.get("name", "")
                if name:
                    import re
                    name = re.sub(r'^(\[\d+\]|P\d+)\s+', '', name)
                    line["name"] = prefix + name
        return vals_list

    @api.model
    def _format_position(self, position):
        if not position:
            return ""
        return str(position).zfill(3)

    # -------------------------------------------------------------------------
    # AVANCES Y PROGRESO (quant_progress es el maestro)
    # -------------------------------------------------------------------------

    avances_ids = fields.One2many(
        "project.sub.update", 
        "sale_order_line_id",
        string="Avances de la Línea",
    )

    @api.depends("task_id.quant_progress")
    def _compute_qty_delivered(self):
        """
        Sincronización maestra: Si hay una tarea vinculada, la cantidad entregada
        siempre es lo que dicte el quant_progress de la tarea (que ya suma 
        avances de obra y días de andamio).
        """
        for line in self:
            if line.task_id:
                line.qty_delivered = line.task_id.quant_progress
            else:
                # Si no hay tarea (ej. fletes, consumibles), usar lógica estándar de Odoo
                super(SaleLine, line)._compute_qty_delivered()
        return True

    progress_percentage = fields.Float(
        string="Progreso (%)",
        compute="_compute_progress_percentage",
        store=False,
    )

    @api.depends("qty_delivered", "product_uom_qty")
    def _compute_progress_percentage(self):
        for line in self:
            if line.product_uom_qty > 0:
                line.progress_percentage = (line.qty_delivered / line.product_uom_qty) * 100
            else:
                line.progress_percentage = 0.0

    # -------------------------------------------------------------------------
    # PROYECTO Y ASIGNACIÓN
    # -------------------------------------------------------------------------

    order_partner_id = fields.Many2one(
        related="order_id.partner_id",
        string="Cliente de la Orden",
        store=True,
    )

    project_line_id = fields.Many2one(
        "project.project",
        string="Proyecto",
        domain="[('is_proyecto_obra', '=', True), '|', ('partner_id', '=', False), ('partner_id', '=', order_partner_id)]",
    )

    def write(self, vals):
        res = super(SaleLine, self).write(vals)
        if "project_line_id" in vals:
            for line in self:
                if line.task_id and line.project_line_id:
                    old_project = line.task_id.project_id
                    new_project = line.project_line_id
                    if old_project.id != new_project.id:
                        line.task_id.sudo().write({'project_id': new_project.id})
                        # Limpieza de vinculación en el proyecto anterior si aplica
                        if old_project and old_project.sale_order_id.id == line.order_id.id:
                            other_tasks = self.env["project.task"].sudo().search_count([
                                ('project_id', '=', old_project.id),
                                ('sale_order_id', '=', line.order_id.id),
                                ('id', '!=', line.task_id.id),
                            ])
                            if other_tasks == 0:
                                old_project.sudo().write({'sale_order_id': False})
                        # Mensajes en chatter
                        line.task_id.message_post(body=Markup("🔄<b> Proyecto reasignado desde SOL. </b><br/>Anterior: %s | Nuevo: %s") % (old_project.name, new_project.name))
                        line.order_id.message_post(body=Markup("🔄<b> Proyecto de la tarea %s reasignado. </b>") % line.task_id.name)
        return res

    def _timesheet_service_generation(self):
        lines_with_pending = self.filtered(lambda l: l.pending_line_id and l.pending_line_id.task_id)
        for line in lines_with_pending:
            existing_task = line.pending_line_id.task_id
            existing_task.write({
                'sale_line_id': line.id,
                'partner_id': line.order_id.partner_id.id,
                'project_id': line.pending_line_id.service_id.supervisor_id.proyecto_supervisor.id,
            })
            line.write({'task_id': existing_task.id})
            existing_task.message_post(body=Markup(_("Tarea vinculada exitosamente desde Servicio Pendiente.")))
        
        other_lines = self - lines_with_pending
        if other_lines:
            super(SaleLine, other_lines)._timesheet_service_generation()
        
        # Garantizar proyecto correcto
        for line in self:
            if line.project_line_id:
                tasks = self.env['project.task'].search([('sale_line_id', '=', line.id)])
                tasks.filtered(lambda t: t.project_id != line.project_line_id).write({'project_id': line.project_line_id.id})
        return True

    # -------------------------------------------------------------------------
    # PARTIDAS
    # -------------------------------------------------------------------------

    partida = fields.Char(
        string="Partida",
        compute="_compute_partida",
        store=False,
        copy=False,
        readonly=True,
        default="P00",
    )

    @api.depends('order_id.order_line.sequence')
    def _compute_partida(self):
        for order in self.mapped('order_id'):
            lines = order.order_line.sorted(key=lambda l: (l.sequence, l.id))
            for i, line in enumerate(lines, 1):
                line.partida = f"P{i:02d}"

    @api.model_create_multi
    def create(self, vals_list):
        vals_list = self._add_next_position_on_new_line(vals_list)
        lines = super().create(vals_list)
        return lines

    def unlink(self):
        orders_to_recalculate = self.mapped("order_id")
        result = super().unlink()
        for order in orders_to_recalculate:
            order.recompute_positions()
        return result

    def _prepare_task_values(self, project=None):
        vals = super()._prepare_task_values(project=project)
        order_name_from_context = self.env.context.get("task_name_from_order")
        order_name = order_name_from_context or self.order_id.name
        vals["name"] = f"{order_name}: {self.name}"
        return vals
