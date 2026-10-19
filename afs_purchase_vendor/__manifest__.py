{
    'name': "AFS - Inkoop per leverancier",
    'summary': "Inkoop: alleen producten van de leverancier, Leveren aan volgt het magazijn van het product",
    'description': """
Minder fouten bij inkopen die je met de hand maakt:

* Op een inkoop kies je alleen producten met deze leverancier (product, tabblad Inkoop),
  ook in de Catalogus. Staat er toch een ander product op (of wijzig je de leverancier),
  dan meldt Odoo dat bij het opslaan.
* Leveren aan vult zich vanzelf in: de ontvangst van het magazijn waaruit de producten
  naar de apotheken gaan (hun route). Merkproduct MKG komt zo binnen in Markgraven.
  Inkopen die Odoo zelf maakt (vanuit een order of een aanvulregel) blijven zoals ze zijn.

Aan of uit: Inkoop > Configuratie > Instellingen > Inkoop per leverancier.
""",
    'version': '19.0.1.0.0',
    'category': 'Inventory/Purchase',
    'author': "Nexu",
    'depends': ['purchase_stock'],
    'data': [
        'views/purchase_order_views.xml',
        'views/res_config_settings_views.xml',
    ],
    'license': 'LGPL-3',
}
