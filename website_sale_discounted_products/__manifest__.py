{
    'name': "AFS - Webshop promoties",
    'summary': "Promoties met korting en aftelling; acties openen en sluiten in de webshop",
    'version': '19.0.1.2.0',
    'category': 'Website/Website',
    'author': "Nexu",
    'depends': ['website_sale', 'website_sale_stock'],
    'data': [
        'data/ir_cron_data.xml',
        'data/website_snippet_filter_data.xml',
        'views/product_template_views.xml',
        'views/shop_templates.xml',
        'views/snippets.xml',
    ],
    'assets': {
        'web.assets_frontend': [
            'website_sale_discounted_products/static/src/js/promo_countdown.js',
        ],
    },
    'license': 'LGPL-3',
}
