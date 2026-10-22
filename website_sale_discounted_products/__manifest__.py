{
    'name': "AFS - Webshop promoties",
    'summary': "Promoties met korting en aftelling; acties openen en sluiten in de webshop; "
               "shop met een blok per categorie; Lopende acties vult zich vanzelf",
    'version': '19.0.1.5.1',
    'category': 'Website/Website',
    'author': "Nexu",
    'depends': ['website_sale', 'website_sale_stock'],
    'data': [
        'data/ir_cron_data.xml',
        'data/website_snippet_filter_data.xml',
        'views/product_template_views.xml',
        'views/product_public_category_views.xml',
        'views/shop_templates.xml',
        'views/snippets.xml',
    ],
    'assets': {
        'web.assets_frontend': [
            'website_sale_discounted_products/static/src/js/promo_countdown.js',
            'website_sale_discounted_products/static/src/scss/shop_sections.scss',
            'website_sale_discounted_products/static/src/scss/product_page.scss',
        ],
    },
    'license': 'LGPL-3',
}
