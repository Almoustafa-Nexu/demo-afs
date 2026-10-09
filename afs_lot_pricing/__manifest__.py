{
    'name': 'AFS - Korting per partij',
    'version': '19.0.1.5.2',
    'summary': 'De apotheek betaalt de prijs van de partij die ze krijgt, met een teller in de webshop.',
    'description': """
Korting per partij (notulen: kortingen doorberekenen en partijgebonden voorraad)
================================================================================
* Op het product: vinkje "Korting per partij doorrekenen" (naast Waardering per partij).
* Op de prijslijst: hetzelfde vinkje. Aan voor Apotheken AFS, uit voor Personeel:
  het personeel betaalt dan gewoon de prijs uit zijn prijslijst.
* De prijs in de shop (Nu) is de prijs van het volgende stuk: de oudste partij eerst.
  In de winkelwagen rekent elke partij aan haar eigen prijs, dus kost de bestelling evenveel als de factuur.
* Een actie op kostprijs (Formule, Kostprijs, Opslag 0 %, met datums): tijdens de actie de prijs van de partij.
  Bestel je meer dan er vrij op voorraad ligt, dan staat de rest voorlopig aan de normale prijs (de prijs
  van na de actie, bv. de verkoopprijs); de factuur volgt later de partij die geleverd wordt.
* Een andere actie (korting of vaste prijs, met datums) is een maximumprijs: een partij die goedkoper is,
  blijft goedkoper.
* Na de levering krijgt de conceptfactuur een regel per geleverde partij, aan de prijs van die partij.
* Een creditfactuur na een retour volgt dezelfde partijen en prijzen.
* In de webshop toont de productpagina een teller: hoeveel stuks er nog zijn aan welke prijs.
* Bij een ontvangst uit een inkoop staat de partijnaam al ingevuld: LOT-P00045-20PROC met korting op de
  inkoopregel, STOCK-P00045 zonder korting. Je kan ze nog aanpassen in Details. Verander je de korting
  na het bevestigen van de inkoop, dan volgt de voorgestelde naam mee.
""",
    'author': 'Almoustafa Elhandouz (Nexu)',
    'category': 'Inventory/Inventory',
    'depends': ['sale_stock', 'stock_account', 'website_sale_stock', 'purchase_stock'],
    'data': [
        'views/product_views.xml',
        'views/templates.xml',
    ],
    'installable': True,
    'license': 'LGPL-3',
}
