{
    'name': 'Modificaciones de Project',
    'version': '17.1.4',
    'author': 'Mauricio, Antonio J.',
    'depends': ['base', 'sale', 'hr', 'project', 'sale_project', 'purchase', 'hr_expense', 'sale_purchase', 'hr_timesheet', 'employee_purchase_requisition', 'stock','web'],
    'license': 'AGPL-3',
    'data': [
        # 1. Security (Groups first, then Access Rights, then Rules)
        'security/ir.model.access.xml',
        'security/project_security.xml',
        'security/ir.model.access.csv',
        "data/security_project_task_type_rule.xml",
        "data/aprobacion_mail_activity_data.xml",

        # 2. Data (Reference data used in views)
        "data/project_task_type_data.xml",

        # 3. Views (Independent / Configuration)
        'views/project_tags_views.xml',
        "views/res_partner_views.xml",
        "views/control_centro_trabajo_views.xml",
        "views/control_planta_views.xml",
        "wizard/project_sub_update_reclassify_wizard_views.xml",
        "wizard/project_reclassify_wizard_views.xml",
        "views/project_profitability_report_pdf.xml",
        "views/project_profitability_report_views.xml",

        # 3.1 Wizards (Must be before views that reference them via actions)
        "views/wizard_rechazado_task_views.xml",
        "views/asignar_avances_project_wizard_views.xml",
        "wizard/pending_service_wizard.xml",

        # 4. Views (Main Models & Actions)
        # These define actions that might be used in menus later
        'views/project_sub_update_views.xml',
        'views/supervisor_area_views.xml',
        'views/pending_services.xml',
        'views/pending_service_report.xml',
        'views/project_task_extra_views.xml',
        'views/extra_project_update_views.xml',
        'views/project_extra_views.xml',
        'views/sale_order_ex.xml',
        'views/sale_config_settings_views.xml',
        "views/purchase_order_views.xml",
        "views/hr_expense_views.xml",
        "views/mod_task_views.xml",
        "views/sale_order_line_views.xml",
        "views/dashboard_sale_order_views.xml",
        "views/dashboard_task_views.xml",
        "views/hr_employee_views.xml",

        # 6. Reports
        'report/report_license_templates.xml',

        # 7. Menus (Must be last as they reference actions defined above)
        'views/menu_actions.xml',
    ],
    "assets": {
        "web.assets_backend": [
            "project_modificaciones/static/src/css/style.css",
            'project_modificaciones/static/src/css/header.css',
            'project_modificaciones/static/src/scss/project_profitability.scss',
            'project_modificaciones/static/src/fields/one2manysearch/one2manysearch.js',
            'project_modificaciones/static/src/fields/one2manysearch/one2manysearch_template.xml',
        ],
    },

    
    'category': 'Technical',
    'license': 'AGPL-3',
    'installable': True,
    'auto_install': False,
    'application': True,
}
