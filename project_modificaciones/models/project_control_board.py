from markupsafe import Markup
from odoo import api, fields, models, _
from odoo.tools import drop_view_if_exists
from odoo.exceptions import UserError


class ProjectControlBoard(models.Model):
    _name = "project.control.board"
    _description = "Tablero Unificado de Proyectos"
    _auto = False
    _order = "priority desc, date_start desc, id desc"

    name = fields.Char(string="Nombre", readonly=True)
    source = fields.Selection(
        selection=[
            ("pending", "Sin OS"),
            ("sale", "Con OS"),
        ],
        string="Origen",
        readonly=True,
    )
    pending_id = fields.Many2one(
        "pending.service",
        string="Servicio Pendiente",
        readonly=True,
    )
    sale_id = fields.Many2one(
        "sale.order",
        string="Orden de Venta",
        readonly=True,
    )
    linked_pending_id = fields.Many2one(
        "pending.service",
        string="Servicio Pendiente Relacionado",
        compute="_compute_linked_documents",
        readonly=True
    )
    linked_sale_id = fields.Many2one(
        "sale.order",
        string="Orden de Venta Relacionada",
        compute="_compute_linked_documents",
        readonly=True
    )
    pending_origin_name = fields.Char(
        string="Nombre servicio pendiente origen",
        readonly=True,
    )
    invoice_move_id = fields.Many2one(
        "account.move",
        string="Factura representativa",
        readonly=True,
    )
    invoice_substate_id = fields.Many2one(
        "base.substate",
        string="Seguimiento factura",
        readonly=True,
    )
    cliente_id = fields.Many2one(
        "res.partner",
        string="Cliente",
        readonly=True,
    )
    disciplina_id = fields.Many2one(
        "license.disciplina",
        string="Disciplina",
        readonly=True,
    )
    supervisor_id = fields.Many2one(
        "hr.employee",
        string="Supervisor",
        readonly=True,
    )
    company_id = fields.Many2one(
        "res.company",
        string="Empresa",
        readonly=True,
    )
    currency_id = fields.Many2one(
        "res.currency",
        string="Moneda",
        readonly=True,
    )
    active = fields.Boolean(string="Archivado", readonly=False)

    date_start = fields.Datetime(string="Inicio", readonly=True)
    date_end = fields.Datetime(string="Fin", readonly=True)
    create_date = fields.Datetime(string="Fecha de Creación", readonly=True)
    date_end_actual = fields.Date(string="Fecha Actual", readonly=True)
    #delay_days = fields.Integer(string="Días de Retraso", readonly=True)
    dias_al_vencimiento = fields.Integer(string="Días Al Vencimiento", readonly=True)
    vencimiento_label = fields.Char(string="Estado de Vencimiento", readonly=True)
    total_amount = fields.Monetary(
        string="Monto Total",
        currency_field="currency_id",
        readonly=True,
    )
    invoice_count = fields.Integer(string="Facturas", readonly=True)
    qty_total = fields.Float(string="Cantidad Total", readonly=True)
    task_count = fields.Integer(string="Tareas", readonly=True)
    task_done_count = fields.Integer(string="Tareas Hechas", readonly=True)
    has_task = fields.Boolean(string="Tiene tareas", readonly=True)
    avance_planeado = fields.Float(string="Avance Planeado", readonly=True)
    avance = fields.Float(string="Avance Real", readonly=True)
    avance_facturado = fields.Float(string="Avance Facturado", readonly=True)
    priority = fields.Selection(
        selection=[
            ("0", "Normal"),
            ("1", "Media"),
            ("2", "Alta"),
            ("3", "Urgente"),
        ],
        string="Prioridad",
        readonly=True,
    )
    state = fields.Selection(
        selection=[
            ("draft", "Borrador"),
            ("pending", "Pendiente"),
            ("assigned", "Asignada"),
            ("canceled", "Cancelada"),
            ("sent", "Cotización enviada"),
            ("sale", "Venta confirmada"),
            ("done", "Hecha"),
            ("cancel", "Cancelada"),
        ],
        string="Estado",
        readonly=True,
    )
    pending_state = fields.Selection(
        selection=[
            ("draft", "Borrador"),
            ("pending", "Pendiente"),
            ("assigned", "Asignada"),
            ("canceled", "Cancelada"),
        ],
        string="Estado Pendiente",
        readonly=True,
    )
    sale_state = fields.Selection(
        selection=[
            ("draft", "Borrador"),
            ("sent", "Cotización enviada"),
            ("sale", "Venta confirmada"),
            ("done", "Hecha"),
            ("cancel", "Cancelada"),
        ],
        string="Estado Orden de Venta",
        readonly=True,
    )
    # MEJORA 2: 'no_date' añadido para OS sin commitment_date
    kanban_color = fields.Selection(
        selection=[
            ("green", "Verde"),
            ("amber", "Ámbar"),
            ("red", "Rojo"),
            ("no_date", "Sin fecha")
        ],
        string="Semáforo",
        readonly=True,
    )

    lifecycle_stage = fields.Selection(
        selection=[
            ("no_plan", "Sin planeación"),
            ("paused", "En pausa"),
            ("in_progress", "En marcha"),
            ("execution_done", "Completado (Ejecución)"),
            ("billing", "Proceso de cobro"),
            ("closed", "Cerrado"),
        ],
        string="Etapa unificada",
        readonly=False,
        group_expand="_read_group_lifecycle_stage",
    )

    def _today_mx_sql(self):
        return "(CURRENT_TIMESTAMP AT TIME ZONE 'America/Mexico_City')::date"

    @api.depends("pending_id", "pending_id.sale_order_id", "sale_id", "sale_id.pending_service_id")
    def _compute_linked_documents(self):
        for record in self:
            pending = record.pending_id
            sale = record.sale_id

            if not pending and sale and sale.pending_service_id:
                pending = sale.pending_service_id

            if not sale and pending and pending.sale_order_id:
                sale = pending.sale_order_id[:1]

            record.linked_pending_id = pending
            record.linked_sale_id = sale

    @api.model
    def _read_group_lifecycle_stage(self, stages, domain, order):
        return [
            "no_plan",
            "paused",
            "in_progress",
            "execution_done",
            "billing",
            "closed",
        ]

    def _stage_transition_map(self):
        sale_done_state = self._sale_execution_done_state()
        return {
            "pending": {
                "no_plan": "draft",
                "paused": "draft",
                "in_progress": "pending",
                "execution_done": "assigned",
                "billing": "assigned",
                "closed": "canceled",
            },
            "sale": {
                "no_plan": "draft",
                "paused": "sent",
                "in_progress": "sale",
                "execution_done": sale_done_state,
                "billing": sale_done_state,
                "closed": "cancel",
            },
        }

    def _sale_execution_done_state(self):
        sale_state_field = self.env["sale.order"]._fields["state"]
        valid_states = {
            value for value, _label in sale_state_field.selection
        }
        return "done" if "done" in valid_states else "sale"

    # MEJORA 4: Transiciones válidas para pending.service
    def _valid_pending_transitions(self):
        """
        Conjunto de pares (estado_actual, estado_destino) permitidos
        para pending.service. Evita retrocesos o saltos inválidos.
        """
        return {
            ("draft", "pending"),
            ("draft", "canceled"),
            ("pending", "assigned"),
            ("pending", "draft"),
            ("pending", "canceled"),
            ("assigned", "canceled"),
            ("assigned", "pending"),
            # Permitir quedarse en el mismo estado (no-op)
            ("draft", "draft"),
            ("pending", "pending"),
            ("assigned", "assigned"),
            ("canceled", "canceled"),
        }

    # MEJORA 4: Transiciones válidas para sale.order
    def _valid_sale_transitions(self):
        """
        Conjunto de pares (estado_actual, estado_destino) permitidos
        para sale.order desde el tablero.
        Nota: 'sale' -> 'draft' no está permitido por Odoo core.
        """
        done_state = self._sale_execution_done_state()
        transitions = {
            ("draft", "sent"),
            ("draft", "cancel"),
            ("sent", "sale"),
            ("sent", "draft"),
            ("sent", "cancel"),
            ("sale", "cancel"),
            # Permitir quedarse en el mismo estado (no-op)
            ("draft", "draft"),
            ("sent", "sent"),
            ("sale", "sale"),
            ("cancel", "cancel"),
        }
        if done_state == "done":
            transitions.update({
                ("sale", "done"),
                ("done", "done"),
            })
        return transitions

    def _sale_rental_filter_sql(self, alias="so"):
        if "is_rental_order" in self.env["sale.order"]._fields:
            return f"AND COALESCE({alias}.is_rental_order, FALSE) = FALSE"
        return ""

    def _pending_board_where_sql(self, pending_alias="p", sales_alias="ps"):
        clauses = [
            f"COALESCE({sales_alias}.sale_order_count, 0) = 0"
        ]

        cliente_obra_filter = self._partner_cliente_obra_condition_sql(
            pending_alias, "cliente_servicio"
        )
        if cliente_obra_filter:
            clauses.append(cliente_obra_filter)

        return " AND ".join(clauses)

    def _partner_cliente_obra_condition_sql(self, table_alias, partner_field):
        """
        Devuelve la condición SQL para limitar registros a partners
        marcados como cliente de obra.
        """
        if "cliente_obra" not in self.env["res.partner"]._fields:
            return ""

        return (
            f"EXISTS ("
            f"SELECT 1 FROM res_partner rp "
            f"WHERE rp.id = {table_alias}.{partner_field} "
            f"AND COALESCE(rp.cliente_obra, FALSE) = TRUE)"
        )


    def _sale_board_where_sql(self, alias="so"):
        clauses = []
        rental_filter = self._sale_rental_filter_sql(alias).strip()
        if rental_filter:
            clauses.append(rental_filter.removeprefix("AND ").strip())

        cliente_obra_filter = self._partner_cliente_obra_condition_sql(alias, "partner_id")
        if cliente_obra_filter:
            clauses.append(cliente_obra_filter)

        return "AND " + " AND ".join(clauses) if clauses else ""



    def _sale_invoice_where_sql(self, alias="am"):
        """
        Considera solo facturas y notas de crédito activas para el resumen
        de facturación del tablero.
        """
        return (
            f"{alias}.move_type IN ('out_invoice', 'out_refund') "
            f"AND {alias}.state != 'cancel'"
        )

    # MEJORA 3: Soporte opcional a date_start_execution en sale.order
    def _sale_date_start_sql(self, alias="so"):
        """
        Usa date_start_execution si existe en sale.order.
        Si no, hace fallback a date_order para mantener compatibilidad.
        """
        if "date_start_execution" in self.env["sale.order"]._fields:
            return f"COALESCE({alias}.date_start_execution, {alias}.date_order)"
        return f"{alias}.date_order"

    def _sale_active_sql(self, alias="so"):
        """
        Usa el campo active real de sale.order cuando existe.
        Si no existiera por alguna personalización, se asume activo.
        """
        if "active" in self.env["sale.order"]._fields:
            return f"COALESCE({alias}.active, TRUE)"
        return "TRUE"

    def _account_move_substate_sql(self, alias="am"):
        if "substate_id" in self.env["account.move"]._fields:
            return f"{alias}.substate_id"
        return "NULL::integer"

    def _sale_disciplina_sql(self, alias="so"):
        """
        Obtiene disciplina desde sale.order y, si no existe allí, usa una
        CTE ya agregada para evitar una subconsulta correlacionada por fila.
        """
        if "disciplina_id" in self.env["sale.order"]._fields:
            return f"{alias}.disciplina_id"
        if "disciplina_id" in self.env["sale.order.line"]._fields:
            return "sd.disciplina_id"
        return "NULL::integer"

    def _sale_disciplina_cte_sql(self):
        """
        CTE opcional para disciplina por orden.
        Solo se genera cuando el campo existe en sale.order.line.
        """
        if "disciplina_id" not in self.env["sale.order.line"]._fields:
            return """
                sale_disciplina AS (
                    SELECT
                        NULL::integer AS order_id,
                        NULL::integer AS disciplina_id
                    WHERE FALSE
                )
            """
        return """
                sale_disciplina AS (
                    SELECT DISTINCT ON (sol.order_id)
                        sol.order_id,
                        sol.disciplina_id
                    FROM sale_order_line sol
                    WHERE sol.disciplina_id IS NOT NULL
                    ORDER BY sol.order_id, sol.sequence, sol.id
                )
        """

    def _get_origin_record(self):
        self.ensure_one()
        return self.pending_id if self.source == "pending" else self.sale_id

    def _ensure_planning_ready_for_in_progress(self):
        self.ensure_one()

        if self.source == "pending" and self.pending_id:
            if not self.pending_id.date_start or not self.pending_id.date_end_plan:
                raise UserError(_(
                    "No se puede mover '%(name)s' a 'En marcha' porque falta capturar la planeación base. "
                    "Debes definir Inicio y Fin planeado en el servicio pendiente."
                ) % {
                    "name": self.pending_id.display_name,
                })
            return

        if self.source == "sale" and self.sale_id:
            start_field_name = "date_start_execution" if "date_start_execution" in self.sale_id._fields else "date_order"
            start_value = self.sale_id[start_field_name]
            end_value = self.sale_id.commitment_date

            if not start_value or not end_value:
                raise UserError(_(
                    "No se puede mover '%(name)s' a 'En marcha' porque falta capturar la planeación base. "
                    "Debes definir Inicio y Fin planeado en la orden de venta."
                ) % {
                    "name": self.sale_id.display_name,
                })
            return

        raise UserError(_(
            "El tablero no tiene un documento origen válido para validar la planeación."
        ))

    def _get_related_tasks(self):
        self.ensure_one()
        if self.source == "pending" and self.pending_id:
            tasks = self.env["project.task"].search(
                [("servicio_pendiente", "=", self.pending_id.id)]
            )
            line_tasks = self.pending_id.service_line_ids.mapped("task_id")
            return tasks | line_tasks

        if self.source == "sale" and self.sale_id:
            return self.env["project.task"].search(
                [("sale_line_id.order_id", "=", self.sale_id.id)]
            )
        return self.env["project.task"]

    def _get_related_updates(self):
        self.ensure_one()
        if self.source == "pending" and self.pending_id:
            return self.env["project.sub.update"].search(
                [("pending_service_id", "=", self.pending_id.id)]
            )
        if self.source == "sale" and self.sale_id:
            return self.env["project.sub.update"].search(
                [("sale_order_id", "=", self.sale_id.id)]
            )
        return self.env["project.sub.update"]

    def _recompute_origin_metrics(self):
        pending_records = self.filtered(
            lambda record: record.source == "pending" and record.pending_id
        ).mapped("pending_id")
        sale_records = self.filtered(
            lambda record: record.source == "sale" and record.sale_id
        ).mapped("sale_id")

        pending_count = 0
        sale_count = 0

        for pending in pending_records:
            if pending.service_line_ids:
                pending.service_line_ids._compute_total_avances()
            pending._compute_total()
            pending._compute_task_count()
            pending._compute_avance_planeado()
            pending._compute_avance_actual()
            pending._compute_task_done_count()
            pending._compute_avance_facturado()
            pending._compute_kanban_color()
            pending_count += 1

        for sale in sale_records:
            sale._compute_progress_indicators()
            sale._compute_sale_task_done_count()
            sale_count += 1

        return pending_count, sale_count

    def _task_progress_case_sql(self, task_alias="pt"):
        today_sql = self._today_mx_sql()
        return f"""
            CASE
                -- Sin fechas de planeación, no hay progreso planeado
                WHEN {task_alias}.planned_date_begin IS NULL
                     OR {task_alias}.date_deadline IS NULL
                THEN 0.0

                -- Si la fecha fin es inválida o igual al inicio,
                -- solo llega a 100 cuando ya se alcanzó o pasó esa fecha
                WHEN {task_alias}.date_deadline::date <= {task_alias}.planned_date_begin::date THEN
                    CASE
                        WHEN {today_sql} >= {task_alias}.date_deadline::date THEN 100.0
                        ELSE 0.0
                    END

                -- Aún no inicia
                WHEN {today_sql} <= {task_alias}.planned_date_begin::date
                THEN 0.0

                -- Ya venció el fin planeado
                WHEN {today_sql} >= {task_alias}.date_deadline::date
                THEN 100.0

                -- Fórmula pura de progreso planeado
                ELSE ROUND((
                    (
                        ({today_sql} - {task_alias}.planned_date_begin::date)::numeric
                        / NULLIF(
                            ({task_alias}.date_deadline::date - {task_alias}.planned_date_begin::date),
                            0
                        )
                    ) * 100.0
                )::numeric, 2)
            END
        """
    
    def _weighted_metric_sql(self, metric_expr="planned_pct"):
        """
        Promedio ponderado por costo:
            SUM(weight * metric) / SUM(weight)

        Si no hay costos válidos (> 0), hace fallback a promedio simple.
        """
        return f"""
            CASE
                WHEN SUM(CASE WHEN weight > 0 THEN weight ELSE 0 END) > 0 THEN
                    ROUND((
                        SUM(
                            CASE
                                WHEN weight > 0 THEN weight * {metric_expr}
                                ELSE 0
                            END
                        )
                        / NULLIF(SUM(CASE WHEN weight > 0 THEN weight ELSE 0 END), 0)
                    )::numeric, 2)
                ELSE
                    ROUND(AVG({metric_expr})::numeric, 2)
            END
        """

    def _pending_task_metrics_cte_sql(self):
        return f"""
                pending_task_metrics AS (
                    SELECT
                        service_id,
                        COUNT(*) AS task_count,
                        COUNT(*) FILTER (WHERE task_state = '1_done') AS task_done_count,
                        {self._weighted_metric_sql("planned_pct")} AS avance_planeado,
                        ROUND(AVG(real_pct)::numeric, 2) AS avance_real,
                        ROUND(AVG(fact_pct)::numeric, 2) AS avance_facturado
                    FROM (
                        SELECT DISTINCT ON (pl.service_id, pt.id)
                            pl.service_id,
                            pt.id AS task_id,
                            pt.state AS task_state,
                            COALESCE(psl.total, 0.0)::numeric AS weight,
                            {self._task_progress_case_sql("pt")} AS planned_pct,
                            COALESCE(pt.avance_actual, 0.0) AS real_pct,
                            COALESCE(pt.avance_facturado, 0.0) AS fact_pct
                        FROM pending_task_links pl
                        JOIN project_task pt
                            ON pt.id = pl.task_id
                        LEFT JOIN pending_service_line psl
                            ON psl.task_id = pt.id
                           AND psl.service_id = pl.service_id
                    ) pending_task_values
                    GROUP BY service_id
                )
        """

    def _pending_sales_cte_sql(self):
        """
        Cuenta cuántas órdenes de venta nacieron de cada servicio pendiente.
        Se usa para excluir del tablero los pendientes ya convertidos.
        """
        return """
                pending_sales AS (
                    SELECT
                        pending_service_id AS service_id,
                        COUNT(*) AS sale_order_count
                    FROM sale_order
                    WHERE pending_service_id IS NOT NULL
                    GROUP BY pending_service_id
                )
        """
    
    def _sale_task_metrics_cte_sql(self):
        return f"""
                sale_task_metrics AS (
                    SELECT
                        order_id,
                        COUNT(*) AS task_count,
                        COUNT(*) FILTER (WHERE task_state = '1_done') AS task_done_count,
                        {self._weighted_metric_sql("planned_pct")} AS avance_planeado,
                        ROUND(AVG(real_pct)::numeric, 2) AS avance_real,
                        ROUND(AVG(fact_pct)::numeric, 2) AS avance_facturado
                    FROM (
                        SELECT DISTINCT ON (sl.order_id, pt.id)
                            sl.order_id,
                            pt.id AS task_id,
                            pt.state AS task_state,
                            COALESCE(sol.price_subtotal, 0.0)::numeric AS weight,
                            {self._task_progress_case_sql("pt")} AS planned_pct,
                            COALESCE(pt.avance_actual, 0.0) AS real_pct,
                            COALESCE(pt.avance_facturado, 0.0) AS fact_pct
                        FROM sale_task_links sl
                        JOIN project_task pt
                            ON pt.id = sl.task_id
                        LEFT JOIN sale_order_line sol
                            ON sol.id = pt.sale_line_id
                    ) sale_task_values
                    GROUP BY order_id
                )
        """

    def _sale_invoice_summary_cte_sql(self):
        substate_sql = self._account_move_substate_sql("am")
        invoice_where_sql = self._sale_invoice_where_sql("am")
        return """
                sale_invoice_links AS (
                    SELECT DISTINCT
                        sol.order_id,
                        am.id AS move_id
                    FROM sale_order_line sol
                    JOIN sale_order_line_invoice_rel rel
                        ON rel.order_line_id = sol.id
                    JOIN account_move_line aml
                        ON aml.id = rel.invoice_line_id
                    JOIN account_move am
                        ON am.id = aml.move_id
                    WHERE """ + invoice_where_sql + """
                ),
                sale_invoice_summary AS (
                    SELECT DISTINCT ON (sil.order_id)
                        sil.order_id,
                        am.id AS invoice_move_id,
                        """ + substate_sql + """ AS invoice_substate_id,
                        COUNT(*) OVER (PARTITION BY sil.order_id) AS invoice_count
                    FROM sale_invoice_links sil
                    JOIN account_move am
                        ON am.id = sil.move_id
                    ORDER BY
                        sil.order_id,
                        CASE WHEN am.state = 'posted' THEN 0 ELSE 1 END,
                        COALESCE(am.invoice_date, am.date, am.create_date::date) DESC,
                        am.id DESC
                )
        """
    
    def _pending_board_select_sql(self):
        today_sql = self._today_mx_sql()
        return f"""
                SELECT
                    p.id AS id,
                    p.name AS name,
                    'pending'::varchar AS source,
                    p.id AS pending_id,
                    NULL::integer AS sale_id,
                    p.name AS pending_origin_name,
                    NULL::integer AS invoice_move_id,
                    NULL::integer AS invoice_substate_id,
                    p.cliente_servicio AS cliente_id,
                    p.disciplina_id AS disciplina_id,
                    p.supervisor_id AS supervisor_id,
                    p.company_id AS company_id,
                    rc.currency_id AS currency_id,
                    p.create_date AS create_date,
                    p.date_start AS date_start,
                    p.date_end_plan AS date_end,
                    p.active AS active,
                    {today_sql} AS date_end_actual,
                    CASE
                        WHEN p.date_end_plan IS NULL THEN NULL
                        WHEN COALESCE(ptm.avance_real, p.avance_actual, 0.0) >= 100.0 THEN NULL
                        ELSE (p.date_end_plan::date - {today_sql})
                    END AS dias_al_vencimiento,
                    CASE
                        WHEN p.date_end_plan IS NULL THEN 'Sin Planeación'
                        WHEN COALESCE(ptm.avance_real, p.avance_actual, 0.0) >= 100.0 THEN 'Completado'
                        WHEN p.date_end_plan::date > {today_sql} THEN CONCAT('Aun Falta: ', (p.date_end_plan::date - {today_sql}), ' dias')
                        WHEN p.date_end_plan::date = {today_sql} THEN 'Hoy: 0 dias'
                        ELSE CONCAT('Vencido: ', ABS(p.date_end_plan::date - {today_sql}), ' dias')
                    END AS vencimiento_label,
                    p.total AS total_amount,
                    0 AS invoice_count,
                    COALESCE(pq.qty_total, 0) AS qty_total,
                    COALESCE(ptm.task_count, 0) AS task_count,
                    COALESCE(ptm.task_done_count, p.task_done_count, 0) AS task_done_count,
                    (COALESCE(ptm.task_count, 0) > 0) AS has_task,
                    COALESCE(ptm.avance_planeado, 0.0) AS avance_planeado,
                    COALESCE(ptm.avance_real, p.avance_actual, 0.0) AS avance,
                    COALESCE(ptm.avance_facturado, p.avance_facturado, 0.0) AS avance_facturado,
                    p.priority AS priority,
                    p.state AS pending_state,
                    NULL::varchar AS sale_state,
                    p.state AS state,
                    CASE
                        WHEN p.date_end_plan IS NULL THEN 'no_date'
                        WHEN COALESCE(ptm.task_count, 0) = 0 THEN p.kanban_color
                        WHEN p.date_end_plan IS NOT NULL
                             AND p.date_end_plan::date < {today_sql}
                             AND COALESCE(ptm.avance_real, p.avance_actual, 0.0) < 100.0
                             AND p.state NOT IN ('canceled')
                        THEN
                            CASE
                                WHEN COALESCE(ptm.avance_real, p.avance_actual, 0.0) >= COALESCE(ptm.avance_planeado, 0.0) THEN 'green'
                                WHEN ABS(COALESCE(ptm.avance_real, p.avance_actual, 0.0) - COALESCE(ptm.avance_planeado, 0.0)) < 10.0 THEN 'amber'
                                ELSE 'red'
                            END
                        WHEN COALESCE(ptm.avance_real, p.avance_actual, 0.0) >= COALESCE(ptm.avance_planeado, 0.0) THEN 'green'
                        WHEN ABS(COALESCE(ptm.avance_real, p.avance_actual, 0.0) - COALESCE(ptm.avance_planeado, 0.0)) < 10.0 THEN 'amber'
                        ELSE 'red'
                    END AS kanban_color,
                    CASE
                        WHEN p.state = 'canceled' THEN 'closed'
                        WHEN p.date_start IS NULL OR p.date_end_plan IS NULL THEN 'no_plan'
                        WHEN COALESCE(ptm.avance_real, p.avance_actual, 0.0) >= 100.0 THEN 'execution_done'
                        WHEN p.state = 'assigned' THEN 'execution_done'
                        WHEN p.state = 'pending' THEN 'in_progress'
                        ELSE 'paused'
                    END AS lifecycle_stage
                FROM pending_service p
                LEFT JOIN res_company rc ON rc.id = p.company_id
                LEFT JOIN pending_qty pq ON pq.service_id = p.id
                LEFT JOIN pending_sales ps ON ps.service_id = p.id
                LEFT JOIN pending_task_metrics ptm ON ptm.service_id = p.id
                WHERE {self._pending_board_where_sql("p", "ps")}
        """

    def _sale_board_select_sql(self, sale_where_sql=""):
        disciplina_sql = self._sale_disciplina_sql("so")
        date_start_sql = self._sale_date_start_sql("so")
        sale_active_sql = self._sale_active_sql("so")
        today_sql = self._today_mx_sql()

        return f"""
                SELECT
                    (so.id + 1000000000) AS id,
                    so.name AS name,
                    'sale'::varchar AS source,
                    NULL::integer AS pending_id,
                    so.id AS sale_id,
                    psrc.name AS pending_origin_name,
                    sis.invoice_move_id AS invoice_move_id,
                    sis.invoice_substate_id AS invoice_substate_id,
                    so.partner_id AS cliente_id,
                    {disciplina_sql} AS disciplina_id,
                    so.supervisor_obra AS supervisor_id,
                    so.company_id AS company_id,
                    rc.currency_id AS currency_id,
                    so.create_date AS create_date,
                    {date_start_sql} AS date_start,
                    so.commitment_date AS date_end,
                    {sale_active_sql} AS active,
                    {today_sql} AS date_end_actual,
                    CASE
                        WHEN so.commitment_date IS NULL THEN NULL
                        WHEN COALESCE(stm.avance_real, so.avance_actual, 0.0) >= 100.0 THEN NULL
                        ELSE (so.commitment_date::date - {today_sql})
                    END AS dias_al_vencimiento,
                    CASE
                        WHEN so.commitment_date IS NULL THEN 'Sin Planeación'
                        WHEN COALESCE(stm.avance_real, so.avance_actual, 0.0) >= 100.0 THEN 'Completado'
                        WHEN so.commitment_date::date > {today_sql} THEN CONCAT('Aun Falta: ', (so.commitment_date::date - {today_sql}), ' dias')
                        WHEN so.commitment_date::date = {today_sql} THEN 'Hoy: 0 dias'
                        ELSE CONCAT('Vencido: ', ABS(so.commitment_date::date - {today_sql}), ' dias')
                    END AS vencimiento_label,
                    so.amount_untaxed AS total_amount,
                    COALESCE(sis.invoice_count, 0) AS invoice_count,
                    COALESCE(sq.qty_total, 0) AS qty_total,
                    COALESCE(stm.task_count, 0) AS task_count,
                    COALESCE(stm.task_done_count, so.task_done_count, 0) AS task_done_count,
                    (COALESCE(stm.task_count, 0) > 0) AS has_task,
                    COALESCE(stm.avance_planeado, 0.0) AS avance_planeado,
                    COALESCE(stm.avance_real, so.avance_actual, 0.0) AS avance,
                    COALESCE(stm.avance_facturado, so.avance_facturado, 0.0) AS avance_facturado,
                    so.priority AS priority,
                    NULL::varchar AS pending_state,
                    so.state AS sale_state,
                    so.state AS state,
                    CASE
                        WHEN so.commitment_date IS NULL THEN 'no_date'
                        WHEN COALESCE(stm.task_count, 0) = 0 THEN so.kanban_color_sale
                        WHEN so.commitment_date::date < {today_sql}
                             AND COALESCE(stm.avance_real, so.avance_actual, 0.0) < 100.0
                             AND so.state NOT IN ('cancel', 'done')
                        THEN
                            CASE
                                WHEN COALESCE(stm.avance_real, so.avance_actual, 0.0) >= COALESCE(stm.avance_planeado, 0.0) THEN 'green'
                                WHEN ABS(COALESCE(stm.avance_real, so.avance_actual, 0.0) - COALESCE(stm.avance_planeado, 0.0)) < 10.0 THEN 'amber'
                                ELSE 'red'
                            END
                        WHEN COALESCE(stm.avance_real, so.avance_actual, 0.0) >= COALESCE(stm.avance_planeado, 0.0) THEN 'green'
                        WHEN ABS(COALESCE(stm.avance_real, so.avance_actual, 0.0) - COALESCE(stm.avance_planeado, 0.0)) < 10.0 THEN 'amber'
                        ELSE 'red'
                    END AS kanban_color,
                    CASE
                        WHEN so.state = 'cancel' THEN 'closed'
                        WHEN sis.invoice_substate_id = 7 THEN 'billing'
                        WHEN so.state = 'done' THEN 'billing'
                        WHEN {date_start_sql} IS NULL OR so.commitment_date IS NULL THEN 'no_plan'
                        WHEN COALESCE(stm.avance_real, so.avance_actual, 0.0) >= 100.0 THEN 'execution_done'
                        WHEN so.state = 'sale' THEN 'in_progress'
                        ELSE 'paused'
                    END AS lifecycle_stage
                FROM sale_order so
                LEFT JOIN pending_service psrc ON psrc.id = so.pending_service_id
                LEFT JOIN res_company rc ON rc.id = so.company_id
                LEFT JOIN sale_qty sq ON sq.order_id = so.id
                LEFT JOIN sale_disciplina sd ON sd.order_id = so.id
                LEFT JOIN sale_task_metrics stm ON stm.order_id = so.id
                LEFT JOIN sale_invoice_summary sis ON sis.order_id = so.id
                WHERE 1 = 1
                {sale_where_sql}
        """

    def _board_view_sql(self):
        sale_where_sql = self._sale_board_where_sql("so")
        return f"""
            CREATE OR REPLACE VIEW {self._table} AS (
                WITH pending_qty AS (
                    SELECT
                        service_id,
                        SUM(quantity) AS qty_total
                    FROM pending_service_line
                    GROUP BY service_id
                ),
                {self._pending_sales_cte_sql().strip()},
                pending_task_links AS (
                    SELECT DISTINCT service_id, task_id
                    FROM (
                        SELECT
                            pt.servicio_pendiente AS service_id,
                            pt.id AS task_id
                        FROM project_task pt
                        WHERE pt.servicio_pendiente IS NOT NULL

                        UNION ALL

                        SELECT
                            sl.service_id AS service_id,
                            sl.task_id AS task_id
                        FROM pending_service_line sl
                        WHERE sl.task_id IS NOT NULL
                    ) pending_task_union
                ),
                sale_qty AS (
                    SELECT
                        order_id,
                        SUM(product_uom_qty) AS qty_total
                    FROM sale_order_line
                    WHERE display_type IS NULL
                    GROUP BY order_id
                ),
                {self._sale_disciplina_cte_sql().strip()},
                sale_task_links AS (
                    SELECT DISTINCT order_id, task_id
                    FROM (
                        SELECT
                            sol.order_id,
                            sol.task_id
                        FROM sale_order_line sol
                        WHERE sol.task_id IS NOT NULL

                        UNION ALL

                        SELECT
                            sol.order_id,
                            pt.id AS task_id
                        FROM project_task pt
                        JOIN sale_order_line sol ON sol.id = pt.sale_line_id
                        WHERE pt.sale_line_id IS NOT NULL
                    ) sale_task_union
                ),
                {self._pending_task_metrics_cte_sql().strip()}
                ,
                {self._sale_task_metrics_cte_sql().strip()}
                ,
                {self._sale_invoice_summary_cte_sql().strip()}
                {self._pending_board_select_sql()}

                UNION ALL

                {self._sale_board_select_sql(sale_where_sql)}
            )
        """

    def _selection_label(self, model_name, field_name, value):
        """
        Devuelve la etiqueta traducida de un valor en un campo selection.
        Usa fields_get para obtener los labels ya procesados por el ORM
        (respeta _() y las traducciones activas de la sesión).
        """
        selection = dict(
            self.env[model_name].fields_get([field_name])[field_name]['selection']
        )
        return selection.get(value, value)

    def write(self, vals):
        """
        Permite arrastrar tarjetas del Kanban actualizando el documento origen.

        MEJORA 4: Valida transiciones antes de aplicarlas y registra
        el cambio en el chatter del documento origen.
        """
        if "lifecycle_stage" not in vals:
            raise UserError(_(
                "En este tablero solo se puede cambiar la etapa arrastrando las tarjetas."
            ))

        target_stage = vals["lifecycle_stage"]
        transition_map = self._stage_transition_map()
        valid_pending = self._valid_pending_transitions()
        valid_sale = self._valid_sale_transitions()

        for record in self:
            if target_stage in ("in_progress", "execution_done"):
                record._ensure_planning_ready_for_in_progress()

            if record.source == "pending" and record.pending_id:
                state = transition_map["pending"].get(target_stage)
                if not state:
                    raise UserError(_(
                        "No hay una transición válida para este servicio pendiente."
                    ))

                current_state = record.pending_id.state
                if current_state == state:
                    continue  # Ya está en ese estado, sin cambios

                if (current_state, state) not in valid_pending:
                    raise UserError(_(
                        "No se puede cambiar el servicio '%(name)s' "
                        "de '%(from_state)s' a '%(to_state)s'."
                    ) % {
                        "name": record.pending_id.display_name,
                        "from_state": current_state,
                        "to_state": state,
                    })

                record.pending_id.write({"state": state})

                # MEJORA 6: Log en chatter del documento origen
                record.pending_id.message_post(
                    body=Markup(_(
                        "Etapa cambiada a <b>%(stage)s</b> (estado: <b>%(state)s</b>) "
                        "desde el Tablero de Proyectos."
                    )) % {
                        "stage": Markup.escape(self._selection_label(
                            'project.control.board', 'lifecycle_stage', target_stage
                        )),
                        "state": Markup.escape(self._selection_label(
                            'pending.service', 'state', state
                        )),
                    },
                    subtype_xmlid="mail.mt_note",
                )
                continue

            if record.source == "sale" and record.sale_id:
                state = transition_map["sale"].get(target_stage)
                if not state:
                    raise UserError(_(
                        "No hay una transición válida para esta orden de venta."
                    ))

                current_state = record.sale_id.state
                if current_state == state:
                    continue  # Ya está en ese estado, sin cambios

                if (current_state, state) not in valid_sale:
                    raise UserError(_(
                        "No se puede cambiar la orden '%(name)s' "
                        "de '%(from_state)s' a '%(to_state)s'."
                    ) % {
                        "name": record.sale_id.display_name,
                        "from_state": current_state,
                        "to_state": state,
                    })

                record.sale_id.write({"state": state})

                # MEJORA 6: Log en chatter del documento origen
                record.sale_id.message_post(
                    body=Markup(_(
                        "Etapa cambiada a <b>%(stage)s</b> (estado: <b>%(state)s</b>) "
                        "desde el Tablero de Proyectos."
                    )) % {
                        "stage": Markup.escape(self._selection_label(
                            'project.control.board', 'lifecycle_stage', target_stage
                        )),
                        "state": Markup.escape(self._selection_label(
                            'sale.order', 'state', state
                        )),
                    },
                    subtype_xmlid="mail.mt_note",
                )
                continue

            raise UserError(_(
                "El tablero no tiene un documento origen válido para actualizar."
            ))

        return True

    @api.model
    def init(self):
        drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute(self._board_view_sql())

    @api.model
    def _name_search(self, name='', args=None, operator='ilike', limit=100, name_get_uid=None):
        """
        Búsqueda por defecto del cuadro de búsqueda (sin chip de campo seleccionado).
        Busca simultáneamente en:
          - name               → nombre del propio registro
          - sale_id.pending_service_id → nombre del servicio pendiente vinculado a la OS
        """
        args = list(args or [])
        if name:
            domain = [
                '|',
                ('name', operator, name),
                ('pending_origin_name', operator, name),
            ]
            return self._search(domain + args, limit=limit, access_rights_uid=name_get_uid)
        return super()._name_search(name, args=args, operator=operator,
                                    limit=limit, name_get_uid=name_get_uid)

    def action_open_tasks(self):
        self.ensure_one()
        tasks = self._get_related_tasks()
        if len(tasks) == 1:
            return {
                "type": "ir.actions.act_window",
                "name": _("Tarea relacionada"),
                "res_model": "project.task",
                "res_id": tasks.id,
                "view_mode": "form",
                "target": "current",
            }
        return {
            "type": "ir.actions.act_window",
            "name": _("Tareas relacionadas"),
            "res_model": "project.task",
            "view_mode": "tree,form",
            "domain": [("id", "in", tasks.ids)],
            "context": {"create": False},
            "target": "current",
        }

    def action_open_updates(self):
        self.ensure_one()
        updates = self._get_related_updates()
        if len(updates) == 1:
            return {
                "type": "ir.actions.act_window",
                "name": _("Avance relacionado"),
                "res_model": "project.sub.update",
                "res_id": updates.id,
                "view_mode": "form",
                "target": "current",
            }
        return {
            "type": "ir.actions.act_window",
            "name": _("Avances relacionados"),
            "res_model": "project.sub.update",
            "view_mode": "tree,form",
            "domain": [("id", "in", updates.ids)],
            "context": {"create": False},
            "target": "current",
        }

    def action_open_invoice(self):
        self.ensure_one()
        if self.source == "sale" and self.sale_id:
            invoices = self.sale_id.invoice_ids.filtered(
                lambda inv: inv.move_type in ("out_invoice", "out_refund")
                and inv.state != "cancel"
            )
            if len(invoices) == 1:
                return {
                    "type": "ir.actions.act_window",
                    "name": invoices.display_name,
                    "res_model": "account.move",
                    "res_id": invoices.id,
                    "view_mode": "form",
                    "target": "current",
                }
            if invoices:
                return {
                    "type": "ir.actions.act_window",
                    "name": _("Facturas relacionadas"),
                    "res_model": "account.move",
                    "view_mode": "tree,form",
                    "domain": [("id", "in", invoices.ids)],
                    "context": {"default_move_type": "out_invoice"},
                    "target": "current",
                }

        if not self.invoice_move_id:
            return {"type": "ir.actions.act_window_close"}

        return {
            "type": "ir.actions.act_window",
            "name": self.invoice_move_id.display_name,
            "res_model": "account.move",
            "res_id": self.invoice_move_id.id,
            "view_mode": "form",
            "target": "current",
        }

    def action_recompute_metrics(self):
        pending_count, sale_count = self._recompute_origin_metrics()
        message = _(
            "Pendientes recalculados: %(pending)s. Órdenes recalculadas: %(sale)s."
        ) % {
            "pending": pending_count,
            "sale": sale_count,
        }
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Recálculo completado"),
                "message": message,
                "type": "success",
                "sticky": False,
                "next": {"type": "ir.actions.client", "tag": "soft_reload"},
            },
        }

    def action_refresh_board(self):
        return {"type": "ir.actions.client", "tag": "soft_reload"}

    def _toggle_origin_active(self, active_value):
        self.ensure_one()
        origin = self._get_origin_record()
        if not origin:
            raise UserError(_(
                "El tablero no tiene un documento origen válido para actualizar."
            ))

        if "active" not in origin._fields:
            raise UserError(_(
                "El documento origen '%(name)s' no permite archivado."
            ) % {"name": origin.display_name})

        if bool(origin.active) == bool(active_value):
            return origin

        origin.write({"active": active_value})
        action_label = _("archivado") if not active_value else _("restaurado")
        origin.message_post(
            body=Markup(_(
                "Registro <b>%(action)s</b> desde el Tablero de Proyectos."
            )) % {"action": Markup.escape(action_label)},
            subtype_xmlid="mail.mt_note",
        )
        return origin

    def action_archive(self):
        for record in self:
            record._toggle_origin_active(False)
        return self.action_refresh_board()

    def action_unarchive(self):
        for record in self:
            record._toggle_origin_active(True)
        return self.action_refresh_board()

    def action_open_origin(self):
        self.ensure_one()
        origin = self._get_origin_record()
        if not origin:
            return {"type": "ir.actions.act_window_close"}

        return {
            "type": "ir.actions.act_window",
            "name": origin.display_name,
            "res_model": origin._name,
            "res_id": origin.id,
            "view_mode": "form",
            "target": "current",
        }