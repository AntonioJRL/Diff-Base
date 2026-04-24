from odoo import api, fields, models, _
from odoo.tools import format_amount
from odoo.tools.float_utils import float_round
from odoo.osv import expression
from datetime import date
from dateutil.relativedelta import relativedelta
import json
from collections import defaultdict
from odoo.tools import Markup


class ProjectProfitabilityReport(models.TransientModel):
    _name = 'project.profitability.report'
    _description = 'Reporte de Rentabilidad de Proyecto'

    def _default_project_ids(self):
        # Abierto desde un proyecto específico → usar ese proyecto
        if self.env.context.get('active_model') == 'project.project' and self.env.context.get('active_ids'):
            return self.env.context['active_ids']
        return []
        # Abierto desde el menú → cargar todos los proyectos de control de obra activos,
        # excluyendo proyectos auxiliares sin avances (OB ANDAMIOS, Ventas…)
        # return self.env['project.project'].sudo().search([
        #     ('is_proyecto_obra', '=', True),
        #     ('active', '=', True),
        #     ('name', 'not ilike', 'Ventas%'),
        #     ('name', '!=', 'OB ANDAMIOS'),
        # ])

    project_ids = fields.Many2many(
        'project.project',
        string='Proyectos',
        default=_default_project_ids,
        required=True,
        domain="[('is_proyecto_obra', '=', True)]",
        help="Proyectos a los cuales se les realizará la revisión de rentabilidad.",
    )

    name = fields.Char(string='Nombre', compute='_compute_nombre')

    @api.depends('project_ids')
    def _compute_nombre(self):
        """Calcula el nombre del reporte basado en los proyectos seleccionados."""
        for wizard in self:
            if not wizard.project_ids:
                wizard.name = 'Dashboard: Sin Proyecto'
            elif len(wizard.project_ids) == 1:
                wizard.name = f"Dashboard Proyecto: {wizard.project_ids.display_name}"
            else:
                names = wizard.project_ids.mapped('name')
                if len(names) > 3:
                    display_text = f"{', '.join(names[:3])} (+{len(names) - 3})"
                else:
                    display_text = ", ".join(names)
                wizard.name = f"Dashboard Proyectos: {display_text}"

    # ── Filtros Principales ──────────────────────────────────────────────────

    filter_type = fields.Selection([
        ('all', 'Todas las Tareas'),
        ('filter', 'Selección Manual'),
    ], string='Filtro de Tareas', default='all', required=True)

    task_ids = fields.Many2many(
        'project.task',
        string='Tareas Específicas',
        domain="[('project_id', 'in', project_ids)]",
    )

    task_state_filter = fields.Selection([
        ('all', 'Todas'),
        ('01_in_progress', 'En Proceso'),
        ('1_done', 'Hecho'),
        ('1_canceled', 'Cancelado'),
        ('04_waiting_normal', 'Esperando'),
        ('03_approved', 'Aprobado'),
        ('02_changes_requested', 'Cambios Solicitados'),
    ], string="Estado de Tareas", default='01_in_progress')

    include_archived = fields.Boolean(
        string="Incluir Tareas Archivadas", default=False)

    include_analytic_account = fields.Boolean(
        string="Incluir por Cuenta Analítica",
        default=False,
        help="Si está activo, busca también registros vinculados a la Cuenta Analítica del Proyecto.",
    )

    # ── Filtros de Fecha y Gráfico ───────────────────────────────────────────

    chart_type = fields.Selection([
        ('pie', 'Gráfico de Costos'),
        ('waterfall', 'Cascada de Rentabilidad'),
        ('line', 'Evolución Temporal'),
    ], string='Tipo de Gráfico', default='pie', required=True)

    date_filter_type = fields.Selection([
        ('none', 'Sin Filtro de Fecha'),
        ('today', 'Hoy'),
        ('this_month', 'Este Mes'),
        ('this_year', 'Este Año'),
        ('custom', 'Personalizado'),
    ], string='Periodo', default='this_year', required=True)

    date_from = fields.Date(string='Desde')
    date_to = fields.Date(string='Hasta')

    # ── Filtro de Ubicación ──────────────────────────────────────────────────

    ubicacion_ids = fields.Many2many(
        'project.ubicacion',
        string='Ubicaciones',
        help="Filtrar proyectos por su ubicación (sitio de trabajo).",
    )

    partner_filter_ids = fields.Many2many(
        'res.partner',
        string='Filtrar por Cliente',
        help="Filtro adicional para la búsqueda de proyectos por cliente.",
        domain="[('tipo_contacto','=','cliente')]"
    )

    date = fields.Date(default=fields.Date.context_today)
    currency_id = fields.Many2one(
        'res.currency', default=lambda self: self.env.company.currency_id)

    # ── Contenido HTML y SVG ─────────────────────────────────────────────────

    content = fields.Html(string='Contenido',
                          sanitize=False, compute='_compute_content', store=True)

    # FIX Problema 1: line_chart_svg generado dentro de _compute_content,
    # NO en un método propio con @api.depends separado.
    line_chart_svg = fields.Html(
        string='Gráfico de Línea',
        sanitize=False,
        compute='_compute_content',
        store=True,
    )

    # ── Flags de lazy-load de tablas de detalle ───────────────────────────────
    # FIX Problema 2: estos flags están en el @api.depends de _compute_content
    # pero NO en el de _compute_financials, por lo que activarlos solo re-renderiza
    # el HTML sin re-ejecutar las queries financieras pesadas.

    show_detail_purchases = fields.Boolean(
        string='Mostrar Compras',    default=False)
    show_detail_expenses = fields.Boolean(
        string='Mostrar Gastos',     default=False)
    show_detail_stock = fields.Boolean(
        string='Mostrar Stock',      default=False)
    show_detail_timesheets = fields.Boolean(
        string='Mostrar Horas',      default=False)

    # ── Métricas Agregadas (Compute → _compute_financials) ───────────────────

    timesheet_hours = fields.Float(
        string='Horas', compute='_compute_financials')
    timesheet_cost = fields.Monetary(
        string='Costo Horas', currency_field='currency_id', compute='_compute_financials')

    total_expenses = fields.Monetary(
        string='Total Gastos', compute='_compute_financials', currency_field='currency_id')
    total_purchases = fields.Monetary(
        string='Total Compras', compute='_compute_financials', currency_field='currency_id')
    total_stock_moves = fields.Monetary(
        string='Total Mov. Almacén', compute='_compute_financials', currency_field='currency_id')

    expected_income = fields.Monetary(
        string='Ingresos Esperados', compute='_compute_financials', currency_field='currency_id')
    invoiced_income = fields.Monetary(
        string='Facturado', compute='_compute_financials', currency_field='currency_id')
    to_invoice_income = fields.Monetary(
        string='Por Facturar', compute='_compute_financials', currency_field='currency_id')

    margin_total = fields.Monetary(
        string='Margen', compute='_compute_financials', currency_field='currency_id')
    profit_percentage = fields.Float(
        string='% Rentabilidad', compute='_compute_financials')

    # ── Márgenes por columna contable ─────────────────────────────────────────

    margin_billed = fields.Monetary(
        string='Margen Contabilizado', compute='_compute_financials', currency_field='currency_id')
    margin_billed_pct = fields.Float(
        string='% Margen Contabilizado', compute='_compute_financials')
    margin_to_bill = fields.Monetary(
        string='Margen Por Contabilizar', compute='_compute_financials', currency_field='currency_id')
    margin_to_bill_pct = fields.Float(
        string='% Margen Por Contabilizar', compute='_compute_financials')

    # ── KPIs de Conteo ───────────────────────────────────────────────────────

    task_count = fields.Integer(string='Tareas', compute='_compute_financials')
    avance_count = fields.Integer(
        string='Avances Físicos', compute='_compute_financials')
    sale_order_count = fields.Integer(
        string='Órdenes de Venta', compute='_compute_financials')
    purchase_count = fields.Integer(
        string='Órdenes de Compra', compute='_compute_financials')
    expense_count = fields.Integer(
        string='Gastos', compute='_compute_financials')
    requisition_count = fields.Integer(
        string='Requisiciones', compute='_compute_financials')
    stock_move_count = fields.Integer(
        string='Mov. Almacén', compute='_compute_financials')
    compensation_count = fields.Integer(
        string='Compensaciones', compute='_compute_financials')
    invoice_count = fields.Integer(
        string='Facturas de Cliente', compute='_compute_financials',
        help="Número de facturas de cliente (out_invoice) generadas a partir de las "
             "líneas de venta relacionadas al proyecto."
    )

    # ── Desglose contable por tipo de costo ───────────────────────────────────

    expenses_billed = fields.Monetary(
        string='Gastos Contabilizados', compute='_compute_financials',
        currency_field='currency_id',
        help="Gastos cuya hoja tiene un asiento contable confirmado (posted).")
    expenses_to_bill = fields.Monetary(
        string='Gastos Por Contabilizar', compute='_compute_financials',
        currency_field='currency_id',
        help="Gastos aprobados sin asiento contable confirmado todavía.")

    purchases_billed = fields.Monetary(
        string='Compras Facturadas (Proveedor)', compute='_compute_financials',
        currency_field='currency_id',
        help="Valor de las cantidades con vendor bill en estado posted (qty_invoiced).")
    purchases_to_bill = fields.Monetary(
        string='Compras Recibidas Sin Factura', compute='_compute_financials',
        currency_field='currency_id',
        help="Valor recibido pero sin vendor bill confirmado aún (qty_received − qty_invoiced).")

    timesheet_billed = fields.Monetary(
        string='Horas Contabilizadas', compute='_compute_financials',
        currency_field='currency_id',
        help="Costo de horas con asiento contable posted (ej. nómina validada).")
    timesheet_to_bill = fields.Monetary(
        string='Horas Sin Asiento', compute='_compute_financials',
        currency_field='currency_id',
        help="Costo de horas registradas sin asiento contable confirmado.")

    stock_billed = fields.Monetary(
        string='Materiales Contabilizados', compute='_compute_financials',
        currency_field='currency_id',
        help="Costo de movimientos de almacén con asiento de valoración posted.")
    stock_to_bill = fields.Monetary(
        string='Materiales Sin Asiento', compute='_compute_financials',
        currency_field='currency_id',
        help="Costo de movimientos done sin asiento de valoración confirmado.")

    purchase_committed = fields.Monetary(
        string='Costo Comprometido (Compras)', compute='_compute_financials',
        currency_field='currency_id')
    purchase_cost_incurred = fields.Monetary(
        string='Costo Incurrido (Compras)', compute='_compute_financials',
        currency_field='currency_id',
        help="Compras facturadas o recibidas.")

    # ── Producción desde Avances Físicos ────────────────────────────────────

    production_avances = fields.Monetary(
        string='Producción (Avances)', compute='_compute_financials',
        currency_field='currency_id',
        help="Suma de sale_current de avances confirmed/assigned vinculados a las tareas filtradas.")
    production_avances_billed = fields.Monetary(
        string='Producción Facturada', compute='_compute_financials',
        currency_field='currency_id',
        help="Avances con state='fact' → sale_current.")
    production_avances_to_bill = fields.Monetary(
        string='Producción No Facturada', compute='_compute_financials',
        currency_field='currency_id',
        help="Avances con state='no_fact' → sale_current.")

    # =========================================================================
    # SECCIÓN: ONCHANGE
    # =========================================================================
    # SECCIÓN: OVERRIDE WRITE — SYNC SERVER-SIDE
    # =========================================================================

    def write(self, vals):
        """
        Override write para sincronizar project_ids en el servidor cuando
        cambian partner_filter_ids o ubicacion_ids.
        Esto garantiza que _compute_financials y _compute_content vean
        los project_ids correctos tras un force_save en las cápsulas de
        cliente/ubicación — el @api.onchange solo corre en memoria del cliente.
        """
        res = super().write(vals)
        if 'partner_filter_ids' in vals or 'ubicacion_ids' in vals:
            for rec in self:
                rec._sync_projects_from_filters()
        return res

    def _sync_projects_from_filters(self):
        """
        Lógica centralizada: busca en el servidor los proyectos que coincidan
        con la ubicación y/o cliente seleccionados, y los asigna a project_ids.
        Si no hay ningún filtro activo, limpia project_ids.
        """
        if not self.ubicacion_ids and not self.partner_filter_ids:
            self.project_ids = [(5, 0, 0)]
            return

        base_domain = [
            ('is_proyecto_obra', '=', True),
            ('active', '=', True),
            ('name', 'not ilike', 'Ventas%'),
            ('name', '!=', 'OB ANDAMIOS'),
        ]

        filter_parts = []
        if self.ubicacion_ids:
            filter_parts.append(
                [('ubicacion', 'in', self.ubicacion_ids._origin.ids)])
        if self.partner_filter_ids:
            filter_parts.append(
                [('partner_id', 'in', self.partner_filter_ids._origin.ids)])

        if filter_parts:
            combined = expression.OR(filter_parts)
            domain = expression.AND([base_domain, combined])
        else:
            domain = base_domain

        projects = self.env['project.project'].sudo().search(domain)
        self.project_ids = [(6, 0, projects.ids)]

    # =========================================================================
    # SECCIÓN: ONCHANGE
    # =========================================================================

    @api.onchange('date_filter_type')
    def _onchange_date_filter_type(self):
        today = fields.Date.context_today(self)
        if self.date_filter_type == 'today':
            self.date_from = today
            self.date_to = today
        elif self.date_filter_type == 'this_month':
            self.date_from = today.replace(day=1)
            self.date_to = today + relativedelta(months=1, day=1, days=-1)
        elif self.date_filter_type == 'this_year':
            self.date_from = today.replace(day=1, month=1)
            self.date_to = today.replace(day=31, month=12)
        elif self.date_filter_type == 'none':
            self.date_from = False
            self.date_to = False

    @api.onchange('ubicacion_ids', 'partner_filter_ids')
    def _onchange_project_filters(self):
        """Sincroniza project_ids en memoria del cliente."""
        self._sync_projects_from_filters()
        # Lanzar recalculo encadenado va _onchange_project_ids

    @api.onchange(
        'filter_type', 'task_ids', 'task_state_filter',
        'date_filter_type', 'date_from', 'date_to',
        'include_archived', 'chart_type',
        'include_analytic_account',
        'partner_filter_ids', 'ubicacion_ids', 'project_ids',
    )
    def _onchange_filters(self):
        # Resetear lazy-load al cambiar filtros de datos
        self.show_detail_purchases = False
        self.show_detail_expenses = False
        self.show_detail_stock = False
        self.show_detail_timesheets = False
        # No llamar compute manualmente, Odoo lo hace por @api.depends

    @api.onchange('project_ids')
    def _onchange_project_ids(self):
        """Limpia las tareas seleccionadas si no pertenecen a los nuevos proyectos."""
        if self.project_ids:
            self.task_ids = self.task_ids.filtered(
                lambda t: t.project_id in self.project_ids)
        else:
            self.task_ids = False

    # =========================================================================
    # SECCIÓN: HELPERS GENÉRICOS
    # =========================================================================

    def _get_date_domain(self, date_field):
        """Genera el dominio de fechas para el campo especificado."""
        self.ensure_one()
        if self.date_filter_type == 'none':
            return []
        domain = []
        if self.date_from:
            domain.append((date_field, '>=', self.date_from))
        if self.date_to:
            domain.append((date_field, '<=', self.date_to))
        return domain

    def _convert_amount(self, amount, src_currency, target_currency, date=None):
        """Convierte un monto de una moneda origen a una destino en una fecha dada."""
        if not src_currency:
            src_currency = self.env.company.currency_id
        if src_currency == target_currency:
            return amount
        return src_currency._convert(
            amount, target_currency, self.env.company, date or fields.Date.context_today(self))

    def _check_date(self, date_value):
        """Verifica si una fecha cae dentro del rango de filtro activo."""
        if not date_value:
            return False
        if self.date_filter_type == 'none':
            return True
        d = date_value.date() if hasattr(date_value, 'date') else date_value
        if self.date_from and d < self.date_from:
            return False
        if self.date_to and d > self.date_to:
            return False
        return True

    # =========================================================================
    # SECCIÓN: HELPERS INTERNOS CENTRALIZADOS
    # =========================================================================

    def _get_filtered_projects(self):
        """
        Retorna los proyectos del wizard ya filtrados por ubicación y/o cliente.
        La lógica es OR: un proyecto se incluye si coincide con la ubicación
        seleccionada o con el cliente seleccionado (o con ambos).
        Si no hay ningún filtro activo, se devuelven todos los project_ids.
        """
        # IMPORTANTE: Usar _origin para extraer los IDs reales en BD,
        # ignorando los "NewId" generados por la memoria de los M2M en el wizard.
        projects = self.project_ids._origin
        ubicaciones = self.ubicacion_ids._origin
        partners = self.partner_filter_ids._origin

        if not ubicaciones and not partners:
            return projects
        return projects.filtered(
            lambda p: (ubicaciones and p.ubicacion in ubicaciones)
            or (partners and p.partner_id in partners)
        )

    def _has_task_state_filter(self):
        """
        FIX 2 / FIX 3 — Helper centralizado para detectar si hay un filtro de estado
        de tarea activo (distinto de 'all'), o selección manual de tareas.
        Cuando está activo, los dominios de proyecto se eliminan para que TODOS
        los registros pasen primero por el conjunto de tareas filtradas y no existan
        registros huérfanos de proyecto que eludan el filtro de estado/manual.
        """
        is_manual = (self.filter_type == 'filter' and bool(self.task_ids))
        is_state = bool(
            self.task_state_filter and self.task_state_filter != 'all')
        return is_manual or is_state

    def _build_analytic_domain(self, model_name, projects):
        """
        Construye el bloque de dominio para búsqueda por cuenta analítica (Odoo 17).
        Soporta campo legacy (analytic_account_id) y distribución JSON con índice GIN
        (analytic_distribution con operador 'in').
        """
        if not self.include_analytic_account or not projects:
            return []

        analytics = projects.mapped('analytic_account_id')
        if not analytics:
            return []

        model_fields = self.env[model_name]._fields
        analytic_criteria = []

        if 'analytic_account_id' in model_fields:
            analytic_criteria.append(
                [('analytic_account_id', 'in', analytics.ids)])

        if 'analytic_distribution' in model_fields:
            analytic_criteria.append(
                [('analytic_distribution', 'in', analytics.ids)])

        return expression.OR(analytic_criteria) if analytic_criteria else []

    def _get_purchase_linked_move_ids(self, move_ids):
        """
        Retorna el conjunto de IDs de stock.move vinculados a una línea de compra.
        """
        if not move_ids:
            return set()
        self.env.cr.execute(
            "SELECT id FROM stock_move WHERE id = ANY(%s) AND purchase_line_id IS NOT NULL",
            [move_ids],
        )
        return {row[0] for row in self.env.cr.fetchall()}

    def _filter_non_purchase_moves(self, moves):
        """
        Filtra un recordset de stock.move eliminando los vinculados a compras.
        Evita doble conteo entre el módulo de compras y el de almacén.
        """
        purchase_linked_ids = self._get_purchase_linked_move_ids(moves.ids)
        has_purchase_on_picking = 'purchase_id' in self.env['stock.picking']._fields
        return moves.filtered(
            lambda m: m.id not in purchase_linked_ids
            and not (has_purchase_on_picking and m.picking_id.purchase_id)
        )

    def _get_expense_amount_field(self):
        """
        Detecta qué campo de monto usar en hr.expense según la versión de Odoo.
        Centralizado para no repetir la detección dentro de bucles.
        """
        Expense = self.env['hr.expense']
        if 'untaxed_amount_currency' in Expense._fields:
            return 'untaxed_amount_currency'
        if 'untaxed_amount' in Expense._fields:
            return 'untaxed_amount'
        return None

    # ── Propiedades cacheadas de detección de versión ────────────────────────

    @property
    def _expense_has_project_field(self):
        """True si hr.expense tiene el campo project_id (Odoo 16+)."""
        return 'project_id' in self.env['hr.expense']._fields

    @property
    def _expense_amount_field(self):
        """Campo de monto sin impuestos en hr.expense según versión de Odoo."""
        Expense = self.env['hr.expense']
        if 'untaxed_amount_currency' in Expense._fields:
            return 'untaxed_amount_currency'
        if 'untaxed_amount' in Expense._fields:
            return 'untaxed_amount'
        return None

    @property
    def _expense_sheet_move_field(self):
        """Campo de asiento contable en hr.expense.sheet según versión de Odoo."""
        sheet_fields = self.env['hr.expense.sheet']._fields
        if 'account_move_id' in sheet_fields:
            return 'account_move_id'
        if 'account_move_ids' in sheet_fields:
            return 'account_move_ids'
        return 'move_id' if 'move_id' in sheet_fields else None

    @property
    def _requisition_date_field(self):
        """Campo de fecha en employee.purchase.requisition según versión."""
        fields_ = self.env['employee.purchase.requisition']._fields
        return 'date_start' if 'date_start' in fields_ else 'create_date'

    @property
    def _compensation_date_field(self):
        """Campo de fecha en compensation.line según versión."""
        return 'date' if 'date' in self.env['compensation.line']._fields else 'create_date'

    # ── Helper: facturas a partir de un recordset de sale.order.line ─────────

    def _get_related_invoices_from(self, sale_lines):
        """Obtiene facturas out_invoice a partir de líneas de venta ya obtenidas."""
        if not sale_lines:
            return self.env['account.move']
        all_invoices = sale_lines.mapped('order_id.invoice_ids')
        return all_invoices.filtered(lambda inv: inv.move_type == 'out_invoice')

    # =========================================================================
    # SECCIÓN: FUENTE DE VERDAD — TAREAS FILTRADAS
    # =========================================================================

    def _get_filtered_tasks(self):
        """
        Retorna el recordset de tareas basado en los filtros aplicados.
        FUENTE DE VERDAD para qué tareas se consideran en el análisis.
        Usa _get_filtered_projects() para que ubicacion_ids y partner_filter_ids
        se apliquen de forma consistente.
        """
        self.ensure_one()
        projects = self._get_filtered_projects()
        if not projects:
            return self.env['project.task']

        domain = [('project_id', 'in', projects.ids)]

        context = self.env.context.copy()
        if self.include_archived:
            context['active_test'] = False
            Task = self.env['project.task'].with_context(context)
        else:
            Task = self.env['project.task']

        if self.filter_type == 'filter' and self.task_ids:
            return self.task_ids._origin

        if self.task_state_filter == 'all':
            domain.append(('state', '!=', '1_canceled'))
        elif self.task_state_filter:
            domain.append(('state', '=', self.task_state_filter))

        # Filtro de periodo aplicado a los avances físicos y por extensión a las tareas vinculadas
        if self.date_filter_type != 'none':
            avance_dom = [('task_id.project_id', 'in', projects.ids)]
            if self.date_from:
                avance_dom.append(('date', '>=', self.date_from))
            if self.date_to:
                avance_dom.append(('date', '<=', self.date_to))

            advances = self.env['project.sub.update'].sudo().search(avance_dom)
            if advances:
                domain.append(('id', 'in', advances.mapped('task_id').ids))
            else:
                domain.append(('id', 'in', []))

        return Task.sudo().search(domain)

    # =========================================================================
    # SECCIÓN: LÓGICA DE VENTAS (INGRESOS)
    # =========================================================================

    def _get_sale_order_lines(self, all_tasks=None, projects=None):
        """
        Obtiene las líneas de venta relacionadas al proyecto.
        Acepta recordsets pre-calculados para evitar queries duplicadas.
        """
        self.ensure_one()
        if all_tasks is None:
            tasks = self._get_filtered_tasks()
            all_tasks = tasks | tasks.mapped('child_ids')
        if projects is None:
            projects = self._get_filtered_projects()

        # FIX 4 — Guardia defensiva: si no hay tareas ni proyectos, retornar vacío
        # para evitar que link_domain quede vacío y devuelva registros globales.
        if not all_tasks and not projects:
            return self.env['sale.order.line']

        final_domain = [('state', 'in', ['sale', 'done']),
                        ('display_type', '=', False)]

        if self.date_filter_type != 'none':
            if self.date_from:
                final_domain.append(
                    ('order_id.date_order', '>=', self.date_from))
            if self.date_to:
                final_domain.append(
                    ('order_id.date_order', '<=', self.date_to))

        # 1. Tarea
        domain_task = [('task_id', 'in', all_tasks.ids)]

        # 2. Proyecto — FIX 2: omitir cuando hay filtro de estado activo para no
        #    mezclar registros de proyecto que eludan el filtro de tareas.
        domain_project = []
        if projects and not self._has_task_state_filter():
            parts = [('order_id.project_id', 'in', projects.ids)]
            if 'project_id' in self.env['sale.order.line']._fields:
                parts.append(('project_id', 'in', projects.ids))
            domain_project = expression.OR([[p] for p in parts])

        # 3. Bloque Analítico
        domain_analytic = self._build_analytic_domain(
            'sale.order.line', projects)

        link_parts = [p for p in [domain_task,
                                  domain_project, domain_analytic] if p]

        # FIX 4 — Si no hay partes de vinculación, retornar vacío (nunca buscar global)
        if not link_parts:
            return self.env['sale.order.line']

        link_domain = expression.OR(link_parts)
        full_domain = expression.AND([final_domain, link_domain])

        return self.env['sale.order.line'].sudo().search(full_domain)

    def _get_sale_orders(self):
        """Retorna las órdenes de venta distintas derivadas de las líneas."""
        return self._get_sale_order_lines().mapped('order_id')

    def _get_related_invoices(self):
        """
        Obtiene las facturas de cliente (account.move, tipo out_invoice) vinculadas
        a las órdenes de venta derivadas de las líneas de venta filtradas.
        """
        self.ensure_one()
        sale_lines = self._get_sale_order_lines()
        if not sale_lines:
            return self.env['account.move']
        all_invoices = sale_lines.mapped('order_id.invoice_ids')
        return all_invoices.filtered(
            lambda inv: inv.move_type == 'out_invoice'
        )

    # =========================================================================
    # SECCIÓN: LÓGICA DE COMPRAS
    # =========================================================================

    def _get_purchase_order_lines(self, all_tasks=None, projects=None):
        """
        Obtiene líneas de compra comprometidas o realizadas.
        Acepta recordsets pre-calculados para evitar queries duplicadas.
        """
        self.ensure_one()
        if all_tasks is None:
            tasks = self._get_filtered_tasks()
            all_tasks = tasks | tasks.mapped('child_ids')
        if projects is None:
            projects = self._get_filtered_projects()

        # FIX 4 — Guardia defensiva
        if not all_tasks and not projects:
            return self.env['purchase.order.line']

        final_domain = [('order_id.state', 'in', ['purchase', 'done'])]

        if self.date_filter_type != 'none':
            if self.date_from:
                final_domain.append(
                    ('order_id.date_order', '>=', self.date_from))
            if self.date_to:
                final_domain.append(
                    ('order_id.date_order', '<=', self.date_to))

        # 1. Tarea
        domain_task = [('task_id', 'in', all_tasks.ids)]

        # 2. Proyecto — FIX 2: omitir cuando hay filtro de estado activo
        domain_project = []
        if projects and not self._has_task_state_filter():
            parts = [('order_id.project_id', 'in', projects.ids)]
            if 'project_id' in self.env['purchase.order.line']._fields:
                parts.append(('project_id', 'in', projects.ids))
            domain_project = expression.OR([[p] for p in parts])

        # 3. Bloque Analítico
        domain_analytic = self._build_analytic_domain(
            'purchase.order.line', projects)

        link_parts = [p for p in [domain_task,
                                  domain_project, domain_analytic] if p]

        # FIX 4 — Guardia: sin partes de vínculo → vacío
        if not link_parts:
            return self.env['purchase.order.line']

        link_domain = expression.OR(link_parts)
        full_domain = expression.AND([final_domain, link_domain])

        return self.env['purchase.order.line'].sudo().search(full_domain)

    def _get_purchase_orders(self):
        return self._get_purchase_order_lines().mapped('order_id')

    # =========================================================================
    # SECCIÓN: LÓGICA DE STOCK Y MOVIMIENTOS
    # =========================================================================

    def _get_stock_moves(self, all_tasks=None, projects=None):
        """Retorna los Movimientos de Almacén específicos vinculados al proyecto."""
        self.ensure_one()
        if all_tasks is None:
            tasks = self._get_filtered_tasks()
            all_tasks = tasks | tasks.mapped('child_ids')
        if projects is None:
            projects = self._get_filtered_projects()

        # FIX 4 — Guardia defensiva
        if not all_tasks and not projects:
            return self.env['stock.move']

        final_domain = [('state', '=', 'done')]

        if self.date_filter_type != 'none':
            if self.date_from:
                final_domain.append(('date', '>=', self.date_from))
            if self.date_to:
                final_domain.append(('date', '<=', self.date_to))

        # 1. Tarea
        domain_task = [('task_id', 'in', all_tasks.ids)]

        # 2. Proyecto — FIX 2: omitir cuando hay filtro de estado activo
        domain_project = []
        if projects and not self._has_task_state_filter():
            parts = [('picking_id.project_id', 'in', projects.ids)]
            if 'project_id' in self.env['stock.move']._fields:
                parts.append(('project_id', 'in', projects.ids))
            domain_project = expression.OR([[p] for p in parts])

        link_parts = [p for p in [domain_task, domain_project] if p]

        # FIX 4 — Guardia: sin partes de vínculo → vacío
        if not link_parts:
            return self.env['stock.move']

        link_domain = expression.OR(link_parts)
        full_domain = expression.AND([final_domain, link_domain])

        return self.env['stock.move'].sudo().search(full_domain)

    # =========================================================================
    # SECCIÓN: LÓGICA DE HOJAS DE HORAS (TIMESHEETS)
    # =========================================================================

    def _get_timesheets(self, all_tasks=None, projects=None):
        """
        Retorna las líneas analíticas (horas) asociadas al proyecto.
        Acepta recordsets pre-calculados para evitar queries duplicadas.
        """
        self.ensure_one()
        if all_tasks is None:
            tasks = self._get_filtered_tasks()
            all_tasks = tasks | tasks.mapped('child_ids')
        if projects is None:
            projects = self._get_filtered_projects()

        # FIX 5 — Guardia defensiva: si no hay proyectos, retornar vacío
        # para evitar que un domain=[] devuelva TODOS los timesheets del sistema.
        if not projects:
            return self.env['account.analytic.line']

        domain = [('project_id', 'in', projects.ids)]

        # FIX 2 — Si hay filtro de estado, forzar también el filtro por tareas
        # para que las horas de tareas en otros estados no se cuenten.
        if self.task_ids or self._has_task_state_filter():
            domain.append(('task_id', 'in', all_tasks.ids))

        if self.date_filter_type != 'none':
            if self.date_from:
                domain.append(('date', '>=', self.date_from))
            if self.date_to:
                domain.append(('date', '<=', self.date_to))

        return self.env['account.analytic.line'].sudo().search(domain)

    # =========================================================================
    # SECCIÓN: LÓGICA DE COMPENSACIONES
    # =========================================================================

    def _get_compensations(self, all_tasks=None, projects=None):
        """Obtiene líneas de compensación (nómina/extras) en estado Aplicado."""
        self.ensure_one()
        if all_tasks is None:
            tasks = self._get_filtered_tasks()
            all_tasks = tasks | tasks.mapped('child_ids')
        if projects is None:
            projects = self._get_filtered_projects()

        domain = [('compensation_id.state', '=', 'applied')]

        has_project = 'project_id' in self.env['compensation.line']._fields
        if has_project:
            # FIX 2/3 — Si hay filtro de estado, usar solo tareas
            if self._has_task_state_filter():
                domain.append(('task_id', 'in', all_tasks.ids))
            else:
                domain += ['|',
                           ('task_id', 'in', all_tasks.ids),
                           '&',
                           ('project_id', 'in', projects.ids),
                           ('task_id', '=', False)]
        else:
            domain.append(('task_id', 'in', all_tasks.ids))

        date_field = 'date' if 'date' in self.env['compensation.line']._fields else 'create_date'

        if self.date_filter_type != 'none':
            if self.date_from:
                domain.append((date_field, '>=', self.date_from))
            if self.date_to:
                domain.append((date_field, '<=', self.date_to))

        return self.env['compensation.line'].search(domain)

    # =========================================================================
    # HELPERS DE CONVERSIÓN MASIVA (Anti N+1)
    # =========================================================================

    def _convert_grouped_by_currency(self, records, amount_getter, date_getter, target_currency):
        """
        Convierte montos de un recordset agrupando por (currency_id, fecha) para minimizar
        llamadas a la API de tipos de cambio (evita el problema N+1).
        """
        groups = defaultdict(float)
        company = self.env.company

        for rec in records:
            amount = amount_getter(rec)
            if not amount:
                continue
            src_curr = rec.currency_id if rec.currency_id else self.env.company.currency_id
            doc_date = date_getter(rec) or fields.Date.context_today(self)
            if hasattr(doc_date, 'date'):
                doc_date = doc_date.date()
            groups[(src_curr.id, doc_date)] += amount

        currencies = {
            c.id: c for c in self.env['res.currency'].browse(
                list({cid for cid, _ in groups})
            )
        }

        total = 0.0
        for (cid, doc_date), amount in groups.items():
            src_curr = currencies.get(cid, target_currency)
            total += amount if src_curr == target_currency else src_curr._convert(
                amount, target_currency, company, doc_date)
        return total

    def _get_stock_valuation_bulk(self, stock_moves):
        """
        Búsqueda masiva de capas de valoración para un conjunto de movimientos.
        Evita acceder a move.stock_valuation_layer_ids dentro de un bucle (N+1).
        """
        if not stock_moves:
            return {}
        layers = self.env['stock.valuation.layer'].sudo().search([
            ('stock_move_id', 'in', stock_moves.ids)
        ])
        result = defaultdict(float)
        for layer in layers:
            result[layer.stock_move_id.id] += abs(layer.value)
        return result

    # =========================================================================
    # SECCIÓN: CÁLCULO DE RENTABILIDAD
    # =========================================================================

    def _get_profitability_data(self, projects, date_from, date_to,
                                _sols=None, _purchase_lines=None,
                                _stock_moves=None, _timesheets=None, _expenses=None):
        """
        Calcula la rentabilidad para un set de proyectos en un rango de fechas.
        Los parámetros opcionales _sols, _purchase_lines, _stock_moves,
        _timesheets y _expenses permiten reutilizar recordsets ya obtenidos
        para evitar queries duplicadas.
        """
        if not projects:
            z = 0.0
            return {
                'expected_income': z, 'invoiced_income': z, 'to_invoice_income': z,
                'total_expenses': z, 'expenses_billed': z, 'expenses_to_bill': z,
                'total_purchases': z, 'purchases_billed': z, 'purchases_to_bill': z,
                'purchase_incurred': z, 'purchase_committed': z,
                'total_stock_moves': z, 'stock_billed': z, 'stock_to_bill': z,
                'timesheet_cost': z, 'timesheet_billed': z, 'timesheet_to_bill': z,
                'margin_total': z, 'profit_percentage': z, 'total_costs': z,
                'margin_billed': z, 'margin_billed_pct': z,
                'margin_to_bill': z, 'margin_to_bill_pct': z,
            }

        target_currency = self.currency_id
        company_currency = self.env.company.currency_id
        company = self.env.company

        def convert(amount, src_curr, date):
            return self._convert_amount(amount, src_curr, target_currency, date)

        def get_date_domain(field_name):
            d_dom = []
            if date_from:
                d_dom.append((field_name, '>=', date_from))
            if date_to:
                d_dom.append((field_name, '<=', date_to))
            return d_dom

        # ── A. INGRESOS ──────────────────────────────────────────────────────
        sols = _sols if _sols is not None else self._get_sale_order_lines()

        expected = self._convert_grouped_by_currency(
            sols,
            amount_getter=lambda s: s.price_subtotal,
            date_getter=lambda s: s.order_id.date_order,
            target_currency=target_currency,
        )

        inv_domain = [('move_id.state', '=', 'posted')] + \
            get_date_domain('move_id.invoice_date')
        posted_lines = sols.mapped('invoice_lines').filtered_domain(inv_domain)
        invoiced = self._convert_grouped_by_currency(
            posted_lines,
            amount_getter=lambda l: l.price_subtotal,
            date_getter=lambda l: l.move_id.invoice_date,
            target_currency=target_currency,
        )

        to_invoice = 0.0
        to_inv_groups = defaultdict(float)
        for sol in sols:
            qty_to_inv = sol.qty_to_invoice
            if qty_to_inv > 0:
                src_curr_id = sol.currency_id.id
                doc_date = sol.order_id.date_order
                if hasattr(doc_date, 'date'):
                    doc_date = doc_date.date()
                to_inv_groups[(src_curr_id, doc_date)
                              ] += qty_to_inv * sol.price_unit

        currencies_cache = {
            c.id: c for c in self.env['res.currency'].browse(
                list({cid for cid, _ in to_inv_groups})
            )
        }
        for (cid, doc_date), amount in to_inv_groups.items():
            src_curr = currencies_cache.get(cid, target_currency)
            to_invoice += amount if src_curr == target_currency else src_curr._convert(
                amount, target_currency, company, doc_date)

        # ── B. GASTOS ─────────────────────────────────────────────────────────
        if _expenses is not None:
            expenses = _expenses
        else:
            tasks = self._get_filtered_tasks()
            all_tasks = tasks | tasks.mapped('child_ids')
            expense_domain = self._get_expense_domain(all_tasks)
            expenses = self.env['hr.expense'].sudo().search(expense_domain)

        _exp_amount_field = self._get_expense_amount_field()

        def _expense_amount(exp):
            if _exp_amount_field:
                return getattr(exp, _exp_amount_field, 0.0) or 0.0
            return getattr(exp, 'total_amount_currency', 0.0) or exp.total_amount

        sheet_model = self.env['hr.expense.sheet']
        sheet_fields = sheet_model._fields

        if 'account_move_id' in sheet_fields:
            expenses.mapped('sheet_id.account_move_id.state')
            exp_billed = expenses.filtered(
                lambda e: e.sheet_id.account_move_id
                and e.sheet_id.account_move_id.state == 'posted'
            )
        elif 'account_move_ids' in sheet_fields:
            expenses.mapped('sheet_id.account_move_ids.state')
            exp_billed = expenses.filtered(
                lambda e: any(
                    m.state == 'posted'
                    for m in e.sheet_id.account_move_ids
                )
            )
        elif 'move_id' in sheet_fields:
            expenses.mapped('sheet_id.move_id.state')
            exp_billed = expenses.filtered(
                lambda e: e.sheet_id.move_id
                and e.sheet_id.move_id.state == 'posted'
            )
        else:
            exp_billed = expenses.filtered(
                lambda e: e.sheet_id.state in ('post', 'done')
            )

        exp_to_bill = expenses - exp_billed

        exp_billed_total = self._convert_grouped_by_currency(
            exp_billed, _expense_amount, lambda e: e.date, target_currency)
        exp_to_bill_total = self._convert_grouped_by_currency(
            exp_to_bill, _expense_amount, lambda e: e.date, target_currency)
        total_expenses = exp_billed_total + exp_to_bill_total

        # ── C. COMPRAS ────────────────────────────────────────────────────────
        purchase_lines = _purchase_lines if _purchase_lines is not None else self._get_purchase_order_lines()

        p_billed_groups = defaultdict(float)
        p_to_bill_groups = defaultdict(float)
        p_total_groups = defaultdict(float)

        for pl in purchase_lines:
            qty_invoiced = pl.qty_invoiced or 0.0
            qty_received = pl.qty_received or 0.0
            qty_to_bill = max(0.0, qty_received - qty_invoiced)
            price = pl.price_unit or 0.0
            price_subtotal = pl.price_subtotal or 0.0

            date_doc = pl.order_id.date_order
            if hasattr(date_doc, 'date'):
                date_doc = date_doc.date()

            key = (pl.currency_id.id, date_doc)

            if qty_invoiced:
                p_billed_groups[key] += qty_invoiced * price
            if qty_to_bill:
                p_to_bill_groups[key] += qty_to_bill * price
            if price_subtotal:
                p_total_groups[key] += price_subtotal

        all_pur_cids = list({cid for cid, _ in
                             list(p_billed_groups) +
                             list(p_to_bill_groups) +
                             list(p_total_groups)})
        pur_currencies = {c.id: c
                          for c in self.env['res.currency'].browse(all_pur_cids)}

        def _conv_groups(groups):
            total = 0.0
            for (cid, doc_date), amount in groups.items():
                src = pur_currencies.get(cid, target_currency)
                total += (amount if src == target_currency
                          else src._convert(amount, target_currency, company, doc_date))
            return total

        p_billed = _conv_groups(p_billed_groups)
        p_to_bill_pur = _conv_groups(p_to_bill_groups)
        total_purchases = _conv_groups(p_total_groups)

        p_incurred = p_billed + p_to_bill_pur
        p_committed = total_purchases - p_incurred

        # ── D. STOCK ─────────────────────────────────────────────────────────
        stock_moves = _stock_moves if _stock_moves is not None else self._get_stock_moves()
        valid_moves = self._filter_non_purchase_moves(stock_moves)

        valid_moves.mapped('location_id.usage')
        valid_moves.mapped('location_dest_id.usage')

        layer_values = self._get_stock_valuation_bulk(valid_moves)

        moves_with_posted_account = set()
        if valid_moves:
            svl_model = self.env['stock.valuation.layer']
            svl_fields = svl_model._fields
            if 'account_move_id' in svl_fields:
                svl_posted = svl_model.sudo().search([
                    ('stock_move_id', 'in', valid_moves.ids),
                    ('account_move_id', '!=', False),
                    ('account_move_id.state', '=', 'posted'),
                ])
                moves_with_posted_account = set(
                    svl_posted.mapped('stock_move_id.id'))
            else:
                valuation_method = self.env.company.sudo().property_cost_method
                auto_accounting = (valuation_method in ('average', 'fifo'))
                if auto_accounting:
                    moves_with_posted_account = set(valid_moves.ids)

        stock_billed_out = defaultdict(float)
        stock_billed_in = defaultdict(float)
        stock_to_bill_out = defaultdict(float)
        stock_to_bill_in = defaultdict(float)

        for move in valid_moves:
            total_val = layer_values.get(move.id)
            if total_val is None:
                val_unit = move.price_unit or move.product_id.standard_price
                qty = move.quantity if move.state == 'done' else move.product_uom_qty
                total_val = val_unit * qty

            is_outgoing = (move.location_id.usage == 'internal'
                           and move.location_dest_id.usage != 'internal')
            is_return = (move.location_id.usage != 'internal'
                         and move.location_dest_id.usage == 'internal')

            doc_date = move.date
            if hasattr(doc_date, 'date'):
                doc_date = doc_date.date()

            has_accounting = move.id in moves_with_posted_account

            if is_outgoing:
                if has_accounting:
                    stock_billed_out[doc_date] += total_val
                else:
                    stock_to_bill_out[doc_date] += total_val
            elif is_return:
                if has_accounting:
                    stock_billed_in[doc_date] += total_val
                else:
                    stock_to_bill_in[doc_date] += total_val

        stock_billed_val = (
            sum(convert(v, company_currency, d)
                for d, v in stock_billed_out.items())
            - sum(convert(v, company_currency, d)
                  for d, v in stock_billed_in.items())
        )
        stock_to_bill_val = (
            sum(convert(v, company_currency, d)
                for d, v in stock_to_bill_out.items())
            - sum(convert(v, company_currency, d)
                  for d, v in stock_to_bill_in.items())
        )
        stock_cost = stock_billed_val + stock_to_bill_val

        # ── E. MANO DE OBRA ──────────────────────────────────────────────────
        timesheets = _timesheets if _timesheets is not None else self._get_timesheets()

        timesheet_cost = self._convert_grouped_by_currency(
            timesheets,
            amount_getter=lambda ts: abs(ts.amount),
            date_getter=lambda ts: ts.date,
            target_currency=target_currency,
        )
        ts_billed_cost = timesheet_cost
        ts_to_bill_cost = 0.0

        # ── TOTALES ──────────────────────────────────────────────────────────
        total_costs_real = total_expenses + total_purchases + stock_cost + timesheet_cost
        margin_total = invoiced - total_costs_real

        profit_percentage = 0.0
        if invoiced:
            profit_percentage = (margin_total / invoiced) * 100.0
        elif expected:
            profit_percentage = (margin_total / expected) * 100.0

        # ── MÁRGENES POR COLUMNA CONTABLE ─────────────────────────────────────
        # Margen Contabilizado: ingresos con asiento posted − costos con asiento posted
        total_billed_costs = (exp_billed_total + p_billed
                              + ts_billed_cost + stock_billed_val)
        margin_billed = invoiced - total_billed_costs
        margin_billed_pct = (margin_billed / invoiced *
                             100.0) if invoiced else 0.0

        # Margen Por Contabilizar: ingresos pendientes − costos pendientes de asiento
        total_to_bill_costs = (exp_to_bill_total + p_to_bill_pur
                               + ts_to_bill_cost + stock_to_bill_val)
        margin_to_bill = to_invoice - total_to_bill_costs
        margin_to_bill_pct = (margin_to_bill / to_invoice *
                              100.0) if to_invoice else 0.0

        return {
            # Ingresos
            'expected_income':   expected,
            'invoiced_income':   invoiced,
            'to_invoice_income': to_invoice,
            # Gastos
            'total_expenses':    total_expenses,
            'expenses_billed':   exp_billed_total,
            'expenses_to_bill':  exp_to_bill_total,
            # Compras
            'total_purchases':   total_purchases,
            'purchases_billed':  p_billed,
            'purchases_to_bill': p_to_bill_pur,
            'purchase_incurred': p_incurred,
            'purchase_committed': p_committed,
            # Stock
            'total_stock_moves': stock_cost,
            'stock_billed':      stock_billed_val,
            'stock_to_bill':     stock_to_bill_val,
            # Timesheets
            'timesheet_cost':    timesheet_cost,
            'timesheet_billed':  ts_billed_cost,
            'timesheet_to_bill': ts_to_bill_cost,
            # Totales
            'margin_total':      margin_total,
            'profit_percentage': profit_percentage,
            'total_costs':       total_costs_real,
            # Márgenes por columna contable
            'margin_billed':      margin_billed,
            'margin_billed_pct':  margin_billed_pct,
            'margin_to_bill':     margin_to_bill,
            'margin_to_bill_pct': margin_to_bill_pct,
        }

    # =========================================================================
    # SECCIÓN: COMPUTE FINANCIALS — queries pesadas (Fix Problemas 2 y 3)
    # @api.depends NO incluye chart_type ni show_detail_* para que el clic en
    # "Cargar detalles" o el cambio de tipo de gráfico NO re-ejecute las queries
    # financieras pesadas (Fix Problema 2).
    # =========================================================================

    @api.depends(
        'project_ids', 'filter_type', 'task_ids', 'task_state_filter',
        'date_filter_type', 'date_from', 'date_to', 'include_archived',
        'ubicacion_ids', 'partner_filter_ids',
        'include_analytic_account',
    )
    def _compute_financials(self):
        """
        Ejecuta todas las queries financieras UNA sola vez y asigna los campos
        monetarios, KPIs de conteo, avances físicos y requisiciones.
        NO renderiza HTML ni prepara datos de tablas de detalle.
        Se dispara solo cuando cambian filtros de datos — nunca por chart_type
        ni show_detail_* (Fix Problema 2).
        """
        for wizard in self:
            # — 1. Contexto base —
            tasks = wizard._get_filtered_tasks()
            all_tasks = tasks | tasks.mapped('child_ids')
            projects = wizard._get_filtered_projects()

            # — 2. Recordsets UNA sola vez — cada getter ejecuta 1 query
            sols = wizard._get_sale_order_lines(all_tasks, projects)
            purchase_lines = wizard._get_purchase_order_lines(
                all_tasks, projects)
            stock_moves = wizard._get_stock_moves(all_tasks, projects)
            timesheets = wizard._get_timesheets(all_tasks, projects)
            comp_lines = wizard._get_compensations(all_tasks, projects)
            exp_domain = wizard._get_expense_domain(all_tasks, projects)
            expenses = wizard.env['hr.expense'].sudo().search(exp_domain)

            # — 3. Rentabilidad — usa los recordsets ya obtenidos (0 queries nuevas)
            data = wizard._get_profitability_data(
                projects, wizard.date_from, wizard.date_to,
                _sols=sols, _purchase_lines=purchase_lines,
                _stock_moves=stock_moves, _timesheets=timesheets,
                _expenses=expenses,
            )

            wizard.expected_income = data['expected_income']
            wizard.invoiced_income = data['invoiced_income']
            wizard.to_invoice_income = data['to_invoice_income']
            wizard.total_expenses = data['total_expenses']
            wizard.expenses_billed = data['expenses_billed']
            wizard.expenses_to_bill = data['expenses_to_bill']
            wizard.total_purchases = data['total_purchases']
            wizard.purchases_billed = data['purchases_billed']
            wizard.purchases_to_bill = data['purchases_to_bill']
            wizard.purchase_cost_incurred = data['purchase_incurred']
            wizard.purchase_committed = data['purchase_committed']
            wizard.total_stock_moves = data['total_stock_moves']
            wizard.stock_billed = data['stock_billed']
            wizard.stock_to_bill = data['stock_to_bill']
            wizard.timesheet_cost = data['timesheet_cost']
            wizard.timesheet_billed = data['timesheet_billed']
            wizard.timesheet_to_bill = data['timesheet_to_bill']
            wizard.margin_total = data['margin_total']
            wizard.profit_percentage = data['profit_percentage']
            wizard.margin_billed = data['margin_billed']
            wizard.margin_billed_pct = data['margin_billed_pct']
            wizard.margin_to_bill = data['margin_to_bill']
            wizard.margin_to_bill_pct = data['margin_to_bill_pct']

            # — 4. Producción desde Avances Físicos —
            # NOTA: sale_current es computed no-stored → se acumula en Python (1 query)
            avance_domain = [
                ('task_id', 'in', all_tasks.ids),
                ('state', 'in', ['fact', 'no_fact']),
            ]
            if wizard.date_filter_type != 'none':
                if wizard.date_from:
                    avance_domain.append(('date', '>=', wizard.date_from))
                if wizard.date_to:
                    avance_domain.append(('date', '<=', wizard.date_to))

            avances_prod = wizard.env['project.sub.update'].sudo().search(
                avance_domain)
            av_by_state = {'fact': 0.0, 'no_fact': 0.0}
            for av in avances_prod:
                av_by_state[av.state] = av_by_state.get(
                    av.state, 0.0) + (av.sale_current or 0.0)
            wizard.production_avances_billed = av_by_state['fact']
            wizard.production_avances_to_bill = av_by_state['no_fact']
            wizard.production_avances = (
                wizard.production_avances_billed + wizard.production_avances_to_bill
            )

            # — 5. KPIs de conteo (reutiliza recordsets ya obtenidos) —
            wizard.task_count = len(tasks)
            wizard.sale_order_count = len(sols.mapped('order_id'))
            wizard.purchase_count = len(purchase_lines.mapped('order_id'))
            wizard.expense_count = len(expenses)
            wizard.stock_move_count = len(stock_moves)
            wizard.timesheet_hours = sum(timesheets.mapped('unit_amount'))
            wizard.compensation_count = len(
                comp_lines.mapped('compensation_id'))
            wizard.invoice_count = len(wizard._get_related_invoices_from(sols))

            avance_count_domain = [('task_id', 'in', all_tasks.ids)]
            if wizard.date_filter_type != 'none':
                if wizard.date_from:
                    avance_count_domain.append(
                        ('date', '>=', wizard.date_from))
                if wizard.date_to:
                    avance_count_domain.append(('date', '<=', wizard.date_to))
            wizard.avance_count = wizard.env['project.sub.update'].sudo(
            ).search_count(avance_count_domain)

            # — 6. Requisiciones —
            req_date_field = wizard._requisition_date_field
            req_line_domain = wizard._get_project_task_domain()
            req_line_domain += [('requisition_product_id.state',
                                 'not in', ['cancelled', 'new'])]
            if wizard.date_filter_type != 'none':
                if wizard.date_from:
                    req_line_domain.append(
                        ('requisition_product_id.' + req_date_field, '>=', wizard.date_from))
                if wizard.date_to:
                    req_line_domain.append(
                        ('requisition_product_id.' + req_date_field, '<=', wizard.date_to))
            req_lines = wizard.env['requisition.order'].search(req_line_domain)
            wizard.requisition_count = len(
                req_lines.mapped('requisition_product_id'))

    # =========================================================================
    # SECCIÓN: LÓGICA DE GASTOS (EXPENSES)
    # =========================================================================

    def _get_expense_domain(self, all_tasks, projects=None):
        """
        Construye el dominio para buscar gastos.
        Acepta projects pre-calculado para evitar queries duplicadas.
        """
        self.ensure_one()

        if projects is None:
            projects = self._get_filtered_projects()

        # FIX 4 — Guardia defensiva: sin tareas ni proyectos → dominio vacío
        if not all_tasks and not projects:
            return [('id', '=', False)]

        # 1. Tarea
        domain_task = [('task_id', 'in', all_tasks.ids)]

        # 2. Proyecto — FIX 2: omitir cuando hay filtro de estado activo
        domain_project = []
        if 'project_id' in self.env['hr.expense']._fields and not self._has_task_state_filter():
            domain_project = [('project_id', 'in', projects.ids)]

        # 3. Bloque Analítico
        domain_analytic = self._build_analytic_domain('hr.expense', projects)

        link_parts = [p for p in [domain_task,
                                  domain_project, domain_analytic] if p]

        # FIX 4 — Guardia: sin partes → dominio que no devuelve nada
        if not link_parts:
            return [('id', '=', False)]

        link_domain = expression.OR(link_parts)

        state_domain = [('sheet_id.state', 'in', ['approve', 'post', 'done'])]
        date_domain = self._get_date_domain('date')

        domain = expression.AND(
            [link_domain, state_domain] + ([date_domain] if date_domain else []))

        return domain

    # =========================================================================
    # SECCIÓN: COMPUTE CONTENT (orquestador limpio)
    # =========================================================================

    # =========================================================================
    # SECCIÓN: COMPUTE CONTENT — solo render HTML (Fix Problemas 1 y 2)
    # @api.depends incluye chart_type y show_detail_* pero NO ejecuta queries
    # financieras: lee los campos ya asignados por _compute_financials.
    # Cuando chart_type != 'line', line_chart_svg = Markup('') sin queries extra
    # (Fix Problema 1). Cuando show_detail_* = True, carga solo esa tabla
    # sin re-ejecutar el cálculo financiero completo (Fix Problema 2).
    # =========================================================================

    @api.depends(
        'project_ids', 'filter_type', 'task_ids', 'task_state_filter',
        'date_filter_type', 'date_from', 'date_to', 'include_archived',
        'ubicacion_ids', 'partner_filter_ids',
        'include_analytic_account', 'chart_type',
        'show_detail_purchases', 'show_detail_expenses',
        'show_detail_stock', 'show_detail_timesheets',
    )
    def _compute_content(self):
        """
        Solo renderiza el HTML del dashboard y genera el SVG si aplica.
        Lee los campos financieros ya calculados por _compute_financials — sin
        ejecutar las queries pesadas de nuevo.
        Las tablas de detalle solo se cargan cuando el flag correspondiente está activo.
        """
        for wizard in self:
            tasks = wizard._get_filtered_tasks()
            all_tasks = tasks | tasks.mapped('child_ids')
            projects = wizard._get_filtered_projects()

            # — Tablas de detalle: lazy loading real (Fix Problema 2) —
            # Cada tabla solo carga sus datos cuando el flag está activo.
            # Si el flag es False, la lista queda vacía y no se ejecutan queries.
            purchases_list = []
            if wizard.show_detail_purchases:
                pl = wizard._get_purchase_order_lines(all_tasks, projects)
                purchases_list = wizard._prepare_purchase_display_data(pl)

            expenses_list = []
            if wizard.show_detail_expenses:
                exp_domain = wizard._get_expense_domain(all_tasks, projects)
                exps = wizard.env['hr.expense'].sudo().search(exp_domain)
                expenses_list = wizard._prepare_expense_display_data(
                    all_tasks, expenses=exps)

            stock_moves_list = []
            if wizard.show_detail_stock:
                sm = wizard._get_stock_moves(all_tasks, projects)
                stock_moves_list = wizard._prepare_stock_display_data(sm)

            timesheets_list = []
            if wizard.show_detail_timesheets:
                ts = wizard._get_timesheets(all_tasks, projects)
                timesheets_list = wizard._prepare_timesheet_display_data(ts)

            # — SVG de línea: Fix Problema 1 —
            # Solo se generan las queries del SVG cuando chart_type == 'line'.
            # En cualquier otro tipo de gráfico, line_chart_svg = Markup('') sin queries.
            if wizard.chart_type == 'line':
                _sols = wizard._get_sale_order_lines(all_tasks, projects)
                _pur = wizard._get_purchase_order_lines(all_tasks, projects)
                _stock = wizard._get_stock_moves(all_tasks, projects)
                _ts = wizard._get_timesheets(all_tasks, projects)
                _exp = wizard.env['hr.expense'].sudo().search(
                    wizard._get_expense_domain(all_tasks, projects))
                line_svg = wizard._generate_line_chart_svg(
                    all_tasks, sols=_sols, timesheets=_ts,
                    expenses=_exp, purchase_lines=_pur, stock_moves=_stock,
                )
            else:
                line_svg = Markup('')

            wizard.line_chart_svg = line_svg

            # — Construir values leyendo campos financieros del wizard (0 queries pesadas) —
            values = {
                'wizard':           wizard,
                'purchases_list':   purchases_list,
                'expenses_list':    expenses_list,
                'stock_moves_list': stock_moves_list,
                'timesheets_list':  timesheets_list,
                'chart_data':       wizard._prepare_pie_chart_data(),
                'column_data':      wizard._prepare_waterfall_data(),
                'line_chart_svg':   line_svg,
                **wizard._compute_alerts(),
                'kpis': {
                    'purchase_committed': wizard.purchase_committed,
                    'purchase_incurred':  wizard.purchase_cost_incurred,
                },
                'profitability': {
                    'expected_income':            wizard.expected_income,
                    'invoiced_income':            wizard.invoiced_income,
                    'to_invoice_income':          wizard.to_invoice_income,
                    'total_expenses':             wizard.total_expenses,
                    'expenses_billed':            wizard.expenses_billed,
                    'expenses_to_bill':           wizard.expenses_to_bill,
                    'total_purchases':            wizard.total_purchases,
                    'purchases_billed':           wizard.purchases_billed,
                    'purchases_to_bill':          wizard.purchases_to_bill,
                    'purchase_incurred':          wizard.purchase_cost_incurred,
                    'purchase_committed':         wizard.purchase_committed,
                    'total_stock_moves':          wizard.total_stock_moves,
                    'stock_billed':               wizard.stock_billed,
                    'stock_to_bill':              wizard.stock_to_bill,
                    'timesheet_cost':             wizard.timesheet_cost,
                    'timesheet_billed':           wizard.timesheet_billed,
                    'timesheet_to_bill':          wizard.timesheet_to_bill,
                    'production_avances':         wizard.production_avances,
                    'production_avances_billed':  wizard.production_avances_billed,
                    'production_avances_to_bill': wizard.production_avances_to_bill,
                    'total_costs': (
                        wizard.total_expenses + wizard.total_purchases
                        + wizard.total_stock_moves + wizard.timesheet_cost
                    ),
                    'margin_total': (
                        wizard.production_avances
                        - wizard.total_expenses - wizard.total_purchases
                        - wizard.total_stock_moves - wizard.timesheet_cost
                    ),
                    'profit_percentage': (
                        (wizard.production_avances
                         - wizard.total_expenses - wizard.total_purchases
                         - wizard.total_stock_moves - wizard.timesheet_cost)
                        / wizard.production_avances * 100.0
                        if wizard.production_avances else 0.0
                    ),
                    # Márgenes por columna contable — basados en producción de avances
                    'margin_billed': (
                        wizard.production_avances_billed
                        - wizard.expenses_billed - wizard.purchases_billed
                        - wizard.timesheet_billed - wizard.stock_billed
                    ),
                    'margin_billed_pct': (
                        (wizard.production_avances_billed
                         - wizard.expenses_billed - wizard.purchases_billed
                         - wizard.timesheet_billed - wizard.stock_billed)
                        / wizard.production_avances_billed * 100.0
                        if wizard.production_avances_billed else 0.0
                    ),
                    'margin_to_bill': (
                        wizard.production_avances_to_bill
                        - wizard.expenses_to_bill - wizard.purchase_committed
                        - wizard.timesheet_to_bill - wizard.stock_to_bill
                    ),
                    'margin_to_bill_pct': (
                        (wizard.production_avances_to_bill
                         - wizard.expenses_to_bill - wizard.purchase_committed
                         - wizard.timesheet_to_bill - wizard.stock_to_bill)
                        / wizard.production_avances_to_bill * 100.0
                        if wizard.production_avances_to_bill else 0.0
                    ),
                },
                'format_monetary': lambda v: format_amount(
                    self.env, float_round(v, precision_digits=2), wizard.currency_id),
                'format_percentage': lambda v: f"{v:.2f}%",
            }

            wizard.content = self.env['ir.qweb']._render(
                'project_modificaciones.project_profitability_template', values)

    # — _compute_master: alias que llama a ambos en orden (compatibilidad) ────

    def _compute_master(self):
        """Alias de compatibilidad: ejecuta financials + content en orden."""
        self._compute_financials()
        self._compute_content()

    # — Aliases para compatibilidad con módulos externos/herencias ────────────

    def _compute_profitability(self):
        """Alias de _compute_financials — conservado por compatibilidad."""
        return self._compute_financials()

    def _compute_stats(self):
        """Alias de _compute_financials — conservado por compatibilidad."""
        return self._compute_financials()

    def _compute_all(self):
        """Alias de _compute_master — conservado por compatibilidad."""
        return self._compute_master()

    # =========================================================================
    # SECCIÓN: ACCIONES DE LAZY-LOAD
    # =========================================================================

    def action_load_all_details(self):
        """Activa todos los flags de detalle en un solo round-trip."""
        self.ensure_one()
        self.show_detail_purchases = True
        self.show_detail_expenses = True
        self.show_detail_stock = True
        self.show_detail_timesheets = True

    def action_load_detail_purchases(self):
        self.ensure_one()
        self.show_detail_purchases = True

    def action_load_detail_expenses(self):
        self.ensure_one()
        self.show_detail_expenses = True

    def action_load_detail_stock(self):
        self.ensure_one()
        self.show_detail_stock = True

    def action_load_detail_timesheets(self):
        self.ensure_one()
        self.show_detail_timesheets = True

    # ── Sub-métodos de preparación de datos para la vista ───────────────────

    def _prepare_stock_display_data(self, stock_moves=None):
        """Prepara la lista de movimientos de stock para la vista."""
        moves = (stock_moves if stock_moves is not None
                 else self._get_stock_moves()).sorted('date', reverse=True)
        valid_moves = self._filter_non_purchase_moves(moves)

        valid_moves.mapped('location_id.usage')
        valid_moves.mapped('location_dest_id.usage')
        valid_moves.mapped('product_id.display_name')
        valid_moves.mapped('task_id.name')
        valid_moves.mapped('picking_id.name')

        layer_values = self._get_stock_valuation_bulk(valid_moves)
        company_currency = self.env.company.currency_id
        target_currency = self.currency_id
        base_url = self.env['ir.config_parameter'].sudo(
        ).get_param('web.base.url')

        state_map = {
            'draft': 'Borrador', 'waiting': 'Esperando', 'confirmed': 'En espera',
            'assigned': 'Reservado', 'done': 'Hecho', 'cancel': 'Cancelado',
        }

        result = []
        for move in valid_moves:
            total_val = layer_values.get(move.id)
            if total_val is None:
                val_unit = move.price_unit or move.product_id.standard_price
                qty_fb = move.quantity if move.state == 'done' else move.product_uom_qty
                total_val = val_unit * qty_fb

            total_cost = self._convert_amount(
                total_val, company_currency, target_currency, move.date)

            is_outgoing = (move.location_id.usage == 'internal'
                           and move.location_dest_id.usage != 'internal')
            is_return = (move.location_id.usage != 'internal'
                         and move.location_dest_id.usage == 'internal')

            move_label = move.reference
            if is_return:
                total_cost = -total_cost
            elif not is_outgoing:
                total_cost = 0.0
                move_label = f"{move.reference} (Resguardo / Interno)"

            qty_display = move.quantity if move.state == 'done' else move.product_uom_qty
            unit_cost_display = abs(
                total_cost / qty_display) if qty_display else 0.0

            result.append({
                'product_name': move.product_id.display_name,
                'task_name': move.task_id.name or '-',
                'project_name': move.task_id.project_id.name or move.project_id.name,
                'date': move.date,
                'quantity': qty_display,
                'uom': move.product_uom.name,
                'reference': move_label,
                'picking': move.picking_id.name,
                'picking_url': f"{base_url}/web#id={move.id}&model=stock.move&view_type=form",
                'price_unit': unit_cost_display,
                'total_cost': total_cost,
                'state_label': state_map.get(move.state, move.state),
                'state_raw': move.state,
                'location_id': move.location_id.display_name,
                'location_dest_id': move.location_dest_id.display_name,
                'lot_name': ", ".join(move.move_line_ids.mapped('lot_id.name')) or "-",
            })
        return result

    def _prepare_purchase_display_data(self, purchase_lines=None):
        """Prepara la lista de líneas de compra para la vista."""
        target_currency = self.currency_id
        lines = (purchase_lines if purchase_lines is not None
                 else self._get_purchase_order_lines()).sorted('create_date', reverse=True)

        # Prefetch masivo — 1 query por relación, evita N+1
        lines.mapped('order_id.name')
        lines.mapped('order_id.date_order')
        lines.mapped('order_id.state')
        lines.mapped('partner_id.name')
        lines.mapped('product_id.display_name')
        lines.mapped('task_id.name')
        lines.mapped('task_id.project_id.name')
        if 'project_id' in self.env['purchase.order.line']._fields:
            lines.mapped('project_id.name')

        state_map = {
            'draft': 'Borrador', 'sent': 'Enviado', 'to approve': 'Por Aprobar',
            'purchase': 'Pedido Compra', 'done': 'Bloqueado', 'cancel': 'Cancelado',
        }

        return [
            {
                'order_name': line.order_id.name,
                'order_id': line.order_id.id,
                'project_name': line.task_id.project_id.name or line.project_id.name,
                'task_name': line.task_id.name or '-',
                'purchase_order_model': 'purchase.order',
                'date': line.order_id.date_order,
                'partner': line.partner_id.name,
                'product': line.product_id.display_name,
                'qty': line.product_qty,
                'price_unit': line.price_unit,
                'total': self._convert_amount(
                    line.price_subtotal, line.currency_id, target_currency, line.order_id.date_order),
                'currency': target_currency.symbol,
                'state': state_map.get(line.order_id.state, line.order_id.state),
                'state_raw': line.order_id.state,
            }
            for line in lines
        ]

    def _prepare_expense_display_data(self, all_tasks=None, expenses=None):
        """Prepara la lista de gastos para la vista."""
        target_currency = self.currency_id
        if expenses is None:
            if all_tasks is None:
                tasks = self._get_filtered_tasks()
                all_tasks = tasks | tasks.mapped('child_ids')
            exp_domain = self._get_expense_domain(all_tasks)
            expenses = self.env['hr.expense'].sudo().search(
                exp_domain, order='date desc')
        else:
            expenses = expenses.sorted('date', reverse=True)

        # Prefetch masivo para gastos — evita N+1
        expenses.mapped('employee_id.name')
        expenses.mapped('product_id.display_name')
        expenses.mapped('task_id.name')
        expenses.mapped('task_id.project_id.name')
        expenses.mapped('sheet_id.name')
        if self._expense_has_project_field:
            expenses.mapped('project_id.name')

        state_map = {
            'draft': 'Borrador', 'reported': 'Enviado', 'approved': 'Aprobado',
            'post': 'Publicado', 'done': 'Pagado', 'refused': 'Rechazado',
        }

        _amount_field = self._expense_amount_field
        _has_project_field = self._expense_has_project_field

        def get_amount(exp):
            if _amount_field:
                return getattr(exp, _amount_field, 0.0) or 0.0
            return getattr(exp, 'total_amount_currency', 0.0) or exp.total_amount

        return [
            {
                'name': exp.name,
                'employee': exp.employee_id.name,
                'project_name': (exp.task_id.project_id.name or exp.project_id.name)
                if _has_project_field else '-',
                'task_name': exp.task_id.name or '-',
                'date': exp.date,
                'product': exp.product_id.display_name,
                'total': self._convert_amount(get_amount(exp), exp.currency_id, target_currency, exp.date),
                'currency': target_currency.symbol,
                'state': state_map.get(exp.state, exp.state),
                'state_raw': exp.state,
                'sheet_name': exp.sheet_id.name,
                'exp_url': f"/web#id={exp.id}&model=hr.expense&view_type=form",
            }
            for exp in expenses
        ]

    def _prepare_timesheet_display_data(self, timesheets=None):
        """Prepara la lista de timesheets para la vista."""
        ts = (timesheets if timesheets is not None
              else self._get_timesheets()).sorted('date', reverse=True)
        ts.mapped('employee_id.name')
        ts.mapped('project_id.name')
        ts.mapped('task_id.name')

        return [
            {
                'employee': al.employee_id.name,
                'project_name': al.project_id.name,
                'date': al.date,
                'description': al.name,
                'task': al.task_id.name or '-',
                'total': -al.amount,
                'currency': al.currency_id.symbol,
                'state_label': 'Validado',
                'state_raw': 'validated',
                'ts_url': f"/web#id={al.id}&model=account.analytic.line&view_type=form",
            }
            for al in ts
        ]

    def _prepare_invoice_display_data(self):
        """
        Serializa las facturas de cliente relacionadas en dicts listos para
        el template QWeb del PDF.
        """
        self.ensure_one()
        invoices = self._get_related_invoices().sorted(
            key=lambda inv: inv.invoice_date or date.min,
            reverse=True,
        )
        if not invoices:
            return []

        invoices.mapped('partner_id.name')

        target_currency = self.currency_id

        state_label_map = {
            'draft':  'Borrador',
            'posted': 'Publicada',
            'cancel': 'Cancelada',
        }
        payment_state_label_map = {
            'not_paid':         'No Pagada',
            'in_payment':       'En Pago',
            'paid':             'Pagada',
            'partial':          'Pago Parcial',
            'reversed':         'Revertida',
            'invoicing_legacy': 'Pagada',
        }

        result = []
        for inv in invoices:
            inv_currency = inv.currency_id or self.env.company.currency_id
            inv_date = inv.invoice_date or fields.Date.context_today(self)

            def _conv(amount, _ic=inv_currency, _id=inv_date):
                return self._convert_amount(amount, _ic, target_currency, _id)

            raw_state = inv.state
            payment_state = getattr(
                inv, 'payment_state', 'not_paid') or 'not_paid'

            if raw_state == 'posted' and payment_state == 'paid':
                display_state = 'Pagada'
            elif raw_state == 'posted':
                display_state = payment_state_label_map.get(
                    payment_state, 'Publicada')
            else:
                display_state = state_label_map.get(raw_state, raw_state)

            result.append({
                'id':               inv.id,
                'name':             inv.name or '/',
                'partner':          inv.partner_id.name or '—',
                'invoice_date':     inv.invoice_date,
                'invoice_date_due': inv.invoice_date_due,
                'amount_untaxed':   _conv(inv.amount_untaxed),
                'amount_tax':       _conv(inv.amount_tax),
                'amount_total':     _conv(inv.amount_total),
                'amount_residual':  _conv(inv.amount_residual),
                'state':            raw_state,
                'payment_state':    payment_state,
                'state_label':      display_state,
            })

        return result

    def _prepare_pie_chart_data(self):
        """
        Calcula proporciones para el gráfico de torta de costos.
        Retorna 0% explícitamente cuando no hay costos.
        """
        total = (self.total_stock_moves + self.total_purchases
                 + self.timesheet_cost + self.total_expenses)

        if not total:
            return {'stock_pct': 0, 'purchases_pct': 0, 'timesheets_pct': 0,
                    'expenses_pct': 0, 'style': ''}

        p_stock = (self.total_stock_moves / total) * 100
        p_purchases = (self.total_purchases / total) * 100
        p_timesheets = (self.timesheet_cost / total) * 100
        p_expenses = (self.total_expenses / total) * 100

        c_stock = f"#dc3545 0% {p_stock:.2f}%"
        c_purch = f"#0d6efd {p_stock:.2f}% {p_stock + p_purchases:.2f}%"
        c_time = f"#fd7e14 {p_stock + p_purchases:.2f}% {p_stock + p_purchases + p_timesheets:.2f}%"
        c_exp = f"#6610f2 {p_stock + p_purchases + p_timesheets:.2f}% 100%"

        return {
            'stock_pct': p_stock,
            'purchases_pct': p_purchases,
            'timesheets_pct': p_timesheets,
            'expenses_pct': p_expenses,
            'style': (f"width:100%;height:100%;border-radius:50%;"
                      f"background:conic-gradient({c_stock},{c_purch},{c_time},{c_exp});"),
        }

    def _prepare_waterfall_data(self):
        """Prepara los datos para el gráfico de cascada de rentabilidad.
        Usa píxeles absolutos (base CHART_H=330px) en lugar de porcentajes
        para garantizar posicionamiento correcto en cualquier contexto flex.
        """
        if self.chart_type != 'waterfall':
            return []

        # altura del área de barras en px (debe coincidir con el CSS)
        CHART_H = 330
        VALUE_TOP_OFFSET = 22  # px sobre la barra para el label de valor

        rev = self.invoiced_income
        exp = -self.total_expenses
        pur_total = -self.total_purchases
        stk = -self.total_stock_moves
        tsh = -self.timesheet_cost
        final_margin = rev + exp + pur_total + stk + tsh

        steps = [
            {'label': 'Ingresos',     'val': rev,
                'color': '#198754', 'is_total': False},
            {'label': 'Gastos',       'val': exp,
                'color': '#6f42c1', 'is_total': False},
            {'label': 'Compras',      'val': pur_total,
                'color': '#0d6efd', 'is_total': False},
            {'label': 'Stock',        'val': stk,
                'color': '#dc3545', 'is_total': False},
            {'label': 'Mano de Obra', 'val': tsh,
                'color': '#fd7e14', 'is_total': False},
            {'label': 'Margen Final', 'val': final_margin,
                'color': '#20c997', 'is_total': True},
        ]

        running = 0.0
        peaks = [0.0]
        for step in steps:
            if step['label'] == 'Ingresos':
                running = step['val']
            elif step['is_total']:
                pass
            else:
                running += step['val']
            peaks.append(running)

        max_val = max(peaks)
        min_val = min(peaks)
        range_val = max_val - min_val if (max_val - min_val) != 0 else 1.0

        # Añadir margen superior e inferior
        max_val = max_val + (range_val * 0.1) if max_val > 0 else max_val
        min_val = min_val - (range_val * 0.1) if min_val < 0 else min_val

        total_range = max_val - min_val if (max_val - min_val) != 0 else 1.0

        def to_px(value):
            """Convierte un valor a píxeles desde el origen min_val."""
            return round(((value - min_val) / total_range) * CHART_H)

        def height_to_px(value):
            """Convierte un valor a píxeles absolutos de altura."""
            return round((abs(value) / total_range) * CHART_H)

        column_data = []
        current_y = 0.0

        for step in steps:
            val = step['val']
            if step['label'] == 'Ingresos':
                y_start, y_end, current_y = 0.0, val, val
            elif step['is_total']:
                y_start, y_end = 0.0, current_y
            else:
                y_start = current_y
                y_end = current_y + val
                current_y = y_end

            bottom_px = to_px(min(y_start, y_end))
            # mínimo 4px para barras muy pequeñas
            height_px = max(height_to_px(val), 4)
            value_top_px = -(VALUE_TOP_OFFSET)  # siempre encima de la barra

            column_data.append({
                'label':       step['label'],
                'amount':      val,
                'bottom_px':   bottom_px,
                'height_px':   height_px,
                'value_top_px': value_top_px,
                'color':       step['color'],
                'is_negative': val < 0,
                'chart_h':     CHART_H,
                'zero_px':     to_px(0),
            })

        return column_data

    def _compute_alerts(self):
        """Evalúa alertas de rentabilidad basadas en producción de avances físicos."""
        total_costs = (
            self.total_expenses + self.total_purchases
            + self.total_stock_moves + self.timesheet_cost
        )
        # Base de producción: avances físicos (igual que el dashboard y el PDF)
        base = self.production_avances or self.invoiced_income or 0.0
        margin = base - total_costs
        pct = (margin / base * 100.0) if base else 0.0

        alert_negative_profit = margin < 0
        alert_low_margin = (
            not alert_negative_profit
            and pct < 10.0
            and base > 0
        )
        return {
            'alert_negative_profit': alert_negative_profit,
            'alert_low_margin': alert_low_margin,
        }

    def _generate_line_chart_svg(self, all_tasks, sols=None, timesheets=None,
                                 expenses=None, purchase_lines=None, stock_moves=None):
        """
        Genera el SVG del gráfico de evolución temporal acumulada (S-Curve).
        Retorna Markup vacío si chart_type no es 'line' o no hay datos.
        Acepta recordsets pre-calculados para evitar queries duplicadas (Fix Problema 1).
        """
        if self.chart_type != 'line':
            return Markup('')

        target_currency = self.currency_id
        company_currency = self.env.company.currency_id

        # Usar los recordsets recibidos o calcularlos si no se pasaron
        if sols is None:
            sols = all_tasks.mapped('sale_line_id')
        if timesheets is None:
            timesheets = self._get_timesheets(all_tasks)
        if expenses is None:
            expense_domain = self._get_expense_domain(all_tasks)
            expenses = self.env['hr.expense'].sudo().search(expense_domain)
        if purchase_lines is None:
            purchase_lines = self._get_purchase_order_lines(all_tasks)
        moves = (stock_moves if stock_moves is not None
                 else self._get_stock_moves(all_tasks)).sorted('date', reverse=True)

        date_data = defaultdict(lambda: {'income': 0.0, 'cost': 0.0})

        inv_domain_line = (
            [('move_id.state', '=', 'posted'), ('sale_line_ids', 'in', sols.ids)]
            + self._get_date_domain('move_id.invoice_date')
        )
        for line in self.env['account.move.line'].search(inv_domain_line):
            if line.move_id.invoice_date:
                date_data[line.move_id.invoice_date]['income'] += self._convert_amount(
                    line.price_subtotal, line.currency_id, target_currency, line.move_id.invoice_date)

        for exp in expenses:
            if exp.date:
                date_data[exp.date]['cost'] += self._convert_amount(
                    exp.total_amount, exp.currency_id, target_currency, exp.date)

        for line in purchase_lines:
            d = line.date_order.date() if line.date_order else False
            if d:
                cost = line.product_qty * line.price_unit
                date_data[d]['cost'] += self._convert_amount(
                    cost, line.currency_id, target_currency, line.date_order)

        for move in moves:
            d = move.date.date() if move.date else False
            if d:
                qty = move.quantity if move.state == 'done' else move.product_uom_qty
                cost_native = (
                    move.price_unit or move.product_id.standard_price) * qty
                date_data[d]['cost'] += self._convert_amount(
                    cost_native, company_currency, target_currency, move.date)

        for al in timesheets:
            if al.date and self._check_date(al.date):
                date_data[al.date]['cost'] += self._convert_amount(
                    -al.amount, al.currency_id, target_currency, al.date)

        if not date_data:
            return Markup(
                '<div class="text-center p-5 text-muted">Sin datos para el rango seleccionado</div>')

        sorted_dates = sorted(date_data.keys())
        points = []
        cum_income = cum_cost = 0.0
        for d in sorted_dates:
            val = date_data[d]
            cum_income += val['income']
            cum_cost += val['cost']
            margin = cum_income - cum_cost
            points.append({
                'date_str': d.strftime('%d/%m'),
                'income': cum_income,
                'cost': cum_cost,
                'margin_pct': (margin / cum_income * 100.0) if cum_income else 0.0,
            })

        w, h, padding = 800, 380, 50
        max_val_chart = max(max(p['income'], p['cost'])
                            for p in points) * 1.1 or 1.0
        margins = [p['margin_pct'] for p in points]
        min_margin = min(min(margins), 0)
        max_margin = max(max(margins), 100)
        margin_range = max_margin - min_margin or 1.0

        def get_x(i):
            return padding + i * (w - 2 * padding) / (len(points) - 1 if len(points) > 1 else 1)

        def get_y(val):
            return h - padding - (val / max_val_chart) * (h - 2 * padding)

        def get_y_pct(pct):
            return h - padding - ((pct - min_margin) / margin_range) * (h - 2 * padding)

        pi_cmds, pc_cmds, pm_cmds = [], [], []
        income_pts = cost_pts = margin_pts = ''

        for i, p in enumerate(points):
            cx = get_x(i)
            cmd = "M" if i == 0 else "L"
            pi_cmds.append(f"{cmd} {cx:.1f},{get_y(p['income']):.1f}")
            pc_cmds.append(f"{cmd} {cx:.1f},{get_y(p['cost']):.1f}")
            pm_cmds.append(f"{cmd} {cx:.1f},{get_y_pct(p['margin_pct']):.1f}")

            income_pts += (
                f'<circle cx="{cx:.1f}" cy="{get_y(p["income"]):.1f}" r="4" '
                f'fill="#28a745" stroke="white" stroke-width="2">'
                f'<title>Ingresos {p["date_str"]}: {format_amount(self.env, p["income"], self.currency_id)}</title>'
                f'</circle>')
            cost_pts += (
                f'<circle cx="{cx:.1f}" cy="{get_y(p["cost"]):.1f}" r="4" '
                f'fill="#dc3545" stroke="white" stroke-width="2">'
                f'<title>Costos {p["date_str"]}: {format_amount(self.env, p["cost"], self.currency_id)}</title>'
                f'</circle>')
            margin_pts += (
                f'<circle cx="{cx:.1f}" cy="{get_y_pct(p["margin_pct"]):.1f}" r="4" '
                f'fill="#ffc107" stroke="white" stroke-width="2">'
                f'<title>Margen {p["date_str"]}: {p["margin_pct"]:.2f}%</title>'
                f'</circle>')

        pi_str = " ".join(pi_cmds)
        pc_str = " ".join(pc_cmds)
        pm_str = " ".join(pm_cmds)
        y_bot = h - padding
        pi_area = f"{pi_str} L {get_x(len(points)-1):.1f},{y_bot} L {get_x(0):.1f},{y_bot} Z"
        pc_area = f"{pc_str} L {get_x(len(points)-1):.1f},{y_bot} L {get_x(0):.1f},{y_bot} Z"

        y_ticks_svg = ''
        for i in range(5):
            pct = i / 4.0
            val = max_val_chart * pct
            yp = get_y(val)
            y_ticks_svg += (
                f'<line x1="{padding}" y1="{yp}" x2="{w-padding}" y2="{yp}" '
                f'stroke="#e9ecef" stroke-width="1" stroke-dasharray="4"/>'
                f'<text x="{padding-10}" y="{yp+4}" text-anchor="end" '
                f'font-size="10" fill="#6c757d" font-family="sans-serif">{int(val)}</text>')
            val_pct = min_margin + margin_range * pct
            yp_pct = get_y_pct(val_pct)
            y_ticks_svg += (
                f'<text x="{w-padding+10}" y="{yp_pct+4}" text-anchor="start" '
                f'font-size="10" fill="#ffc107" font-family="sans-serif">{int(val_pct)}%</text>')

        step = max(1, len(points) // 6) if len(points) > 12 else 1
        x_ticks_svg = ''.join(
            f'<text x="{get_x(i):.1f}" y="{h-padding+20}" text-anchor="middle" '
            f'font-size="10" fill="#6c757d" font-family="sans-serif">{points[i]["date_str"]}</text>'
            for i in range(0, len(points), step)
        )

        return Markup(f"""
        <svg viewBox="0 0 {w} {h}" xmlns="http://www.w3.org/2000/svg"
             style="width:100%;height:auto;max-height:400px;font-family:-apple-system,system-ui,BlinkMacSystemFont,'Segoe UI',Roboto,'Helvetica Neue',Arial,sans-serif;">
            <defs>
                <linearGradient id="gradIncome" x1="0%" y1="0%" x2="0%" y2="100%">
                    <stop offset="0%" style="stop-color:#28a745;stop-opacity:0.3"/>
                    <stop offset="100%" style="stop-color:#28a745;stop-opacity:0"/>
                </linearGradient>
                <linearGradient id="gradCost" x1="0%" y1="0%" x2="0%" y2="100%">
                    <stop offset="0%" style="stop-color:#dc3545;stop-opacity:0.3"/>
                    <stop offset="100%" style="stop-color:#dc3545;stop-opacity:0"/>
                </linearGradient>
                <filter id="shadow" x="-20%" y="-20%" width="140%" height="140%">
                    <feDropShadow dx="0" dy="1" stdDeviation="1" flood-color="#000000" flood-opacity="0.1"/>
                </filter>
            </defs>
            {y_ticks_svg}
            <line x1="{padding}" y1="{h-padding}" x2="{w-padding}" y2="{h-padding}" stroke="#dee2e6" stroke-width="1"/>
            <line x1="{padding}" y1="{padding}" x2="{padding}" y2="{h-padding}" stroke="#dee2e6" stroke-width="1"/>
            <path d="{pi_area}" fill="url(#gradIncome)"/>
            <path d="{pc_area}" fill="url(#gradCost)"/>
            <path d="{pi_str}" fill="none" stroke="#28a745" stroke-width="2.5" filter="url(#shadow)"/>
            <path d="{pc_str}" fill="none" stroke="#dc3545" stroke-width="2.5" filter="url(#shadow)"/>
            <path d="{pm_str}" fill="none" stroke="#ffc107" stroke-width="2.5" stroke-dasharray="5,5" filter="url(#shadow)"/>
            <g>{income_pts}{cost_pts}{margin_pts}</g>
            {x_ticks_svg}
            <g transform="translate({w-280},20)">
                <rect width="250" height="30" rx="5" fill="white" fill-opacity="0.8" stroke="#dee2e6"/>
                <circle cx="20" cy="15" r="4" fill="#28a745"/>
                <text x="30" y="19" font-size="11" fill="#333" font-weight="bold">Ingresos</text>
                <circle cx="90" cy="15" r="4" fill="#dc3545"/>
                <text x="100" y="19" font-size="11" fill="#333" font-weight="bold">Costos</text>
                <circle cx="150" cy="15" r="4" fill="#ffc107"/>
                <text x="160" y="19" font-size="11" fill="#333" font-weight="bold">Margen %</text>
            </g>
        </svg>""")

    # =========================================================================
    # SECCIÓN: ACCIONES DE VENTANA
    # =========================================================================

    def _get_project_task_domain(self, model_prefix=''):
        """
        Retorna dominio que incluye registros vinculados a tareas filtradas
        y registros del proyecto sin tarea (costos globales).

        FIX 3 — Cuando hay filtro de estado activo, se usa solo el dominio
        de tareas (all_tasks ya tiene el estado aplicado). Si se incluyera
        la rama project+task=False, registros globales del proyecto eludirían
        el filtro de estado.
        """
        tasks = self._get_filtered_tasks()
        all_tasks = tasks | tasks.mapped('child_ids')

        task_field = f'{model_prefix}task_id'
        project_field = f'{model_prefix}project_id'

        # FIX 3 — Solo usar la rama tarea cuando hay filtro de estado
        if self._has_task_state_filter():
            return [(task_field, 'in', all_tasks.ids)]

        if not self.task_ids and self.project_ids:
            return [
                '|',
                (task_field, 'in', all_tasks.ids),
                '&',
                (project_field, 'in', self.project_ids._origin.ids),
                (task_field, '=', False),
            ]
        return [(task_field, 'in', all_tasks.ids)]

    def _get_action_view_base(self, name, res_model, domain, view_id=False):
        res = {
            'name': name,
            'type': 'ir.actions.act_window',
            'res_model': res_model,
            'view_mode': 'tree,form',
            'domain': domain,
            'target': 'current',
        }
        if view_id:
            # En Odoo 17, 'views' asocia el modo con el ID del registro de vista
            res['views'] = [(view_id, 'tree'), (False, 'form')]
        return res

    def action_recalculate(self):
        """Recalcula el dashboard: financials primero, luego HTML (Fix Problema 3)."""
        self._compute_financials()
        self._compute_content()
        return True

    # ── Setters con recalculo automático ─────────────────────────────────────
    # Cada botón type="object" en la vista dispara un ciclo completo
    # save→recompute→reload, que actualiza el campo Html "content" en Odoo 17.

    def _set_and_recalculate(self):
        """Reset flags lazy-load y recalcula todo."""
        self.show_detail_purchases = False
        self.show_detail_expenses = False
        self.show_detail_stock = False
        self.show_detail_timesheets = False
        self._compute_financials()
        self._compute_content()
        return True

    def action_set_filter_type(self):
        self.filter_type = self.env.context.get('_v', self.filter_type)
        return self._set_and_recalculate()

    def action_set_task_state_filter(self):
        self.task_state_filter = self.env.context.get(
            '_v', self.task_state_filter)
        return self._set_and_recalculate()

    def action_set_chart_type(self):
        self.chart_type = self.env.context.get('_v', self.chart_type)
        return self._set_and_recalculate()

    def action_set_date_filter_type(self):
        new_type = self.env.context.get('_v', self.date_filter_type)
        self.date_filter_type = new_type
        today = fields.Date.context_today(self)
        if new_type == 'today':
            self.date_from = today
            self.date_to = today
        elif new_type == 'this_month':
            self.date_from = today.replace(day=1)
            self.date_to = today + relativedelta(months=1, day=1, days=-1)
        elif new_type == 'this_year':
            self.date_from = today.replace(day=1, month=1)
            self.date_to = today.replace(day=31, month=12)
        elif new_type == 'none':
            self.date_from = False
            self.date_to = False
        return self._set_and_recalculate()

    def action_view_tasks(self):
        self.ensure_one()
        tasks = self._get_filtered_tasks()
        return self._get_action_view_base('Tareas Filtradas', 'project.task',
                                          [('id', 'in', tasks.ids)])

    def action_view_avances(self):
        self.ensure_one()
        tasks = self._get_filtered_tasks()
        all_tasks = tasks | tasks.mapped('child_ids')
        domain = [('task_id', 'in', all_tasks.ids)]
        if self.date_filter_type != 'none':
            if self.date_from:
                domain.append(('date', '>=', self.date_from))
            if self.date_to:
                domain.append(('date', '<=', self.date_to))

        return self._get_action_view_base(
            'Avances Físicos',
            'project.sub.update',
            domain,
        )

    def action_view_sale_orders(self):
        self.ensure_one()
        view_id = self.env.ref(
            'project_modificaciones.view_sale_order_line_profitability_tree').id
        return self._get_action_view_base('Líneas de Venta', 'sale.order.line',
                                          [('id', 'in', self._get_sale_order_lines().ids)],
                                          view_id=view_id)

    def action_view_purchase_orders(self):
        self.ensure_one()
        view_id = self.env.ref(
            'project_modificaciones.view_purchase_order_line_profitability_tree').id
        return self._get_action_view_base('Líneas de Compra', 'purchase.order.line',
                                          [('id', 'in', self._get_purchase_order_lines().ids)],
                                          view_id=view_id)

    def action_view_timesheets(self):
        self.ensure_one()
        domain = self._get_project_task_domain() + self._get_date_domain('date')
        return self._get_action_view_base('Hojas de Horas', 'account.analytic.line', domain)

    def action_view_compensations(self):
        self.ensure_one()
        comp_domain = [('compensation_id.state', '=', 'applied')]

        if 'project_id' in self.env['compensation.line']._fields:
            comp_domain += self._get_project_task_domain()
        else:
            tasks = self._get_filtered_tasks()
            all_tasks = tasks | tasks.mapped('child_ids')
            comp_domain += [('task_id', 'in', all_tasks.ids)]

        date_field = 'date' if 'date' in self.env['compensation.line']._fields else 'create_date'
        comp_domain += self._get_date_domain(date_field)

        lines = self.env['compensation.line'].search(comp_domain)
        requests = lines.mapped('compensation_id')
        return self._get_action_view_base('Compensaciones', 'compensation.request',
                                          [('id', 'in', requests.ids)])

    def action_view_expenses(self):
        self.ensure_one()
        tasks = self._get_filtered_tasks()
        all_tasks = tasks | tasks.mapped('child_ids')
        domain = self._get_expense_domain(all_tasks)
        return self._get_action_view_base('Gastos', 'hr.expense', domain)

    def action_view_requisitions(self):
        self.ensure_one()
        line_domain = self._get_project_task_domain()
        line_domain += [('requisition_product_id.state',
                         'not in', ['cancelled', 'new'])]

        req_date_field = (
            'date_start'
            if 'date_start' in self.env['employee.purchase.requisition']._fields
            else 'create_date'
        )

        if self.date_filter_type != 'none':
            if self.date_from:
                line_domain.append(
                    ('requisition_product_id.' + req_date_field, '>=', self.date_from))
            if self.date_to:
                line_domain.append(
                    ('requisition_product_id.' + req_date_field, '<=', self.date_to))

        lines = self.env['requisition.order'].search(line_domain)
        return self._get_action_view_base('Líneas de Requisición', 'requisition.order',
                                          [('id', 'in', lines.ids)])

    def action_view_stock_moves(self):
        self.ensure_one()
        view_id = self.env.ref(
            'project_modificaciones.view_stock_move_profitability_tree').id
        moves = self._get_stock_moves()
        return self._get_action_view_base('Movimientos de Almacén', 'stock.move',
                                          [('id', 'in', moves.ids)],
                                          view_id=view_id)

    def action_view_invoices(self):
        self.ensure_one()
        invoices = self._get_related_invoices()
        return {
            'name': 'Facturas de Cliente',
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'view_mode': 'tree,form',
            'domain': [('id', 'in', invoices.ids)],
            'context': {'default_move_type': 'out_invoice'},
            'target': 'current',
        }

    def action_print_report(self):
        self.ensure_one()
        return self.env.ref(
            'project_modificaciones.action_report_project_profitability_pdf'
        ).report_action(self)


# =============================================================================
# MODELO: Proveedor de datos para el reporte PDF QWeb
# =============================================================================

class ProjectProfitabilityReportPDF(models.AbstractModel):
    _name = 'report.project_modificaciones.report_project_profitability_pdf'
    _description = 'Proveedor de Datos — Reporte PDF Rentabilidad'

    @api.model
    def _get_report_values(self, docids, data=None):
        docs = self.env['project.profitability.report'].browse(docids)
        wizard = docs[0] if docs else self.env['project.profitability.report']

        # ── Producción desde Avances Físicos (igual lógica que el dashboard) ──
        avances_billed = wizard.production_avances_billed
        avances_to_bill = wizard.production_avances_to_bill
        avances_total = wizard.production_avances

        _total_costs = (
            wizard.total_expenses
            + wizard.total_purchases
            + wizard.total_stock_moves
            + wizard.timesheet_cost
        )
        _margin_total = avances_total - _total_costs
        _profit_pct = (
            (_margin_total / avances_total * 100.0) if avances_total else 0.0
        )

        profitability = {
            # Ingresos OV (referencia)
            'expected_income':    wizard.expected_income,
            'invoiced_income':    wizard.invoiced_income,
            'to_invoice_income':  wizard.to_invoice_income,
            # Producción desde Avances Físicos
            'production_avances':          avances_total,
            'production_avances_billed':   avances_billed,
            'production_avances_to_bill':  avances_to_bill,
            # Costos
            'total_expenses':     wizard.total_expenses,
            'expenses_billed':    wizard.expenses_billed,
            'expenses_to_bill':   wizard.expenses_to_bill,
            'total_purchases':    wizard.total_purchases,
            'purchases_billed':   wizard.purchases_billed,
            'purchases_to_bill':  wizard.purchases_to_bill,
            'purchase_incurred':  wizard.purchase_cost_incurred,
            'purchase_committed': wizard.purchase_committed,
            'total_stock_moves':  wizard.total_stock_moves,
            'stock_billed':       wizard.stock_billed,
            'stock_to_bill':      wizard.stock_to_bill,
            'timesheet_cost':     wizard.timesheet_cost,
            'timesheet_billed':   wizard.timesheet_billed,
            'timesheet_to_bill':  wizard.timesheet_to_bill,
            # Totales — usa los campos compute del wizard como fuente de verdad
            'total_costs':        _total_costs,
            'margin_total':       _margin_total,
            'profit_percentage':  _profit_pct,
            # Márgenes por columna — usa los campos compute del wizard como fuente de verdad
            'margin_billed':      wizard.margin_billed,
            'margin_billed_pct':  wizard.margin_billed_pct,
            'margin_to_bill':     wizard.margin_to_bill,
            'margin_to_bill_pct': wizard.margin_to_bill_pct,
        }

        kpi_counts = {
            'tasks':         wizard.task_count,
            'avances':       wizard.avance_count,
            'sale_orders':   wizard.sale_order_count,
            'purchases':     wizard.purchase_count,
            'expenses':      wizard.expense_count,
            'stock_moves':   wizard.stock_move_count,
            'invoices':      wizard.invoice_count,
            'compensations': wizard.compensation_count,
        }

        filter_ubicaciones = ', '.join(
            wizard.ubicacion_ids.mapped('name')) if wizard.ubicacion_ids else ''
        filter_projects = ', '.join(
            wizard.project_ids.mapped('name')) if wizard.project_ids else 'Todos'

        period_labels = {
            'none':       'Sin filtro de fecha',
            'today':      'Hoy',
            'this_month': 'Este mes',
            'this_year':  'Este año',
            'custom':     f"{wizard.date_from or '?'} → {wizard.date_to or '?'}",
        }
        filter_period = period_labels.get(wizard.date_filter_type, '—')

        state_labels = {
            'all':                  'Todas (excl. Canceladas)',
            '01_in_progress':       'En Proceso',
            '1_done':               'Hecho',
            '1_canceled':           'Cancelado',
            '04_waiting_normal':    'Esperando',
            '03_approved':          'Aprobado',
            '02_changes_requested': 'Cambios Solicitados',
        }
        filter_task_state = state_labels.get(wizard.task_state_filter, '')

        alerts = wizard._compute_alerts()

        tasks_obj = wizard._get_filtered_tasks()
        all_tasks = tasks_obj | tasks_obj.mapped('child_ids')

        def fmt(amount, _wizard=wizard):
            return format_amount(
                _wizard.env,
                float_round(float(amount or 0.0), precision_digits=2),
                _wizard.currency_id,
            )

        return {
            'doc_ids':   docids,
            'doc_model': 'project.profitability.report',
            'docs':      docs,
            'report_date':  fields.Date.context_today(wizard),
            'company_name': wizard.env.company.name,
            'currency_name': wizard.currency_id.name,
            'filter_ubicaciones': filter_ubicaciones,
            'filter_projects':    filter_projects,
            'filter_period':      filter_period,
            'filter_task_state':  filter_task_state,
            'profitability':   profitability,
            'kpi_counts':      kpi_counts,
            'timesheet_hours': wizard.timesheet_hours,
            'alert_negative_profit': alerts.get('alert_negative_profit', False),
            'alert_low_margin':      alerts.get('alert_low_margin', False),
            'purchases_list':   wizard._prepare_purchase_display_data(),
            'expenses_list':    wizard._prepare_expense_display_data(all_tasks),
            'stock_moves_list': wizard._prepare_stock_display_data(),
            'invoices_list':    wizard._prepare_invoice_display_data(),
            'fmt': fmt,
        }