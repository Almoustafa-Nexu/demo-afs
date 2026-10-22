{
    'name': "AFS - Inkoop per leverancier",
    'summary': "Inkoop: leverancier komt van het product, Leveren aan volgt het magazijn van het product",
    'description': """
Minder fouten bij inkopen die je met de hand maakt:

* Kies je op een nieuwe inkoop een product, dan komt de leverancier van dat product vanzelf bovenaan.
  Je mag de leverancier aanpassen: staat het product er niet bij, dan krijg je een venster met de knop Accepteer.
* Leveren aan vult zich vanzelf in: de ontvangst van het magazijn waaruit de producten
  naar de apotheken gaan (hun route). Merkproduct MKG komt zo binnen in Markgraven.
  Inkopen die Odoo zelf maakt (vanuit een order of een aanvulregel) blijven zoals ze zijn.

Aan of uit: Inkoop > Configuratie > Instellingen > Inkoop per leverancier.
""",
    'version': '19.0.1.5.2',
    'category': 'Inventory/Purchase',
    'author': "Nexu",
    'depends': ['purchase_stock'],
    'data': [
        'views/purchase_order_views.xml',
        'views/res_config_settings_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'afs_purchase_vendor/static/src/js/afs_vendor_dialog.js',
            'afs_purchase_vendor/static/src/xml/afs_vendor_dialog.xml',
        ],
    },
    'license': 'LGPL-3',
}
