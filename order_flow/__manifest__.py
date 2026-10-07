{
    'name': "AFS - Bestelflow",
    'summary': "Afrekenen als offerte; conceptfacturen na levering en ontvangst",
    'version': '19.0.1.1.0',
    'category': 'Sales/Sales',
    'author': "Nexu",
    'depends': ['website_sale', 'sale_stock', 'purchase_stock'],
    'data': [
        'views/sale_order_views.xml',
        'views/website_sale_templates.xml',
    ],
    'license': 'LGPL-3',
}