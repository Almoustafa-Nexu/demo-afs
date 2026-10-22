{
    'name': 'AFS - Korting per partij',
    'version': '19.0.1.17.3',
    'summary': 'De apotheek betaalt de prijs van de partij die ze krijgt.',
    'description': """
Korting per partij
==================
* Vinkje "Korting per partij doorrekenen" op het product (met Waardering per partij) en op de prijslijst
  (aan voor Apotheken AFS, uit voor Personeel).
* Shop: de prijs is die van de oudste partij. De partijen zijn stappen (normale prijs, dan bv. 20%, dan 40%):
  onder de prijs staat het doel van de apotheken samen ("Nog 100 stuks om het doel te bereiken, dan krijg je
  20% korting.") en de voorraad. Een webshopbestelling die AFS nog moet bevestigen, telt meteen mee.
  Daaronder de prijs per stap, in de volgorde van de inkoop (FIFO), met de stap van nu in het groen.
  Staat de prijs nog op de normale prijs maar komen er stappen met korting, dan krijgt het kaartje (shop en blok
  Promoties) de sticker "Actie, tot -40%" en staat het product in Lopende acties. Zonder partijen met korting is
  het niet in actie.
* Offerte, order en factuur: een regel per partij, aan de prijs van die partij (de oudste eerst). Wat niet in een
  partij past, staat voorlopig aan de normale prijs; bij een regel op kostprijs is dat de prijs van de leverancier
  zonder korting. Een actie is een maximum: een goedkopere partij blijft goedkoper. In de winkelwagen staat per
  partij een korte regel onder het product: "-45%  66 x 5,50 €" (en "voorverkoop" als ze nog niet binnen is).
* Ontvangst: de partijnaam staat al ingevuld (LOT-P00045-20PROC, zonder korting STOCK-P00045).
* Levering: elke orderregel krijgt de stuks uit haar eigen partij, zodat de factuur dezelfde prijs heeft als de
  order, ook als meer partijen tegelijk binnenkomen. Is die partij op, dan de oudste andere partij.
* Voorverkoop: vinkje "Voorverkoop in de webshop" op een inkoopofferte. Wat nog te koop is, staat als partij in de
  shop en telt mee als beschikbaar: ook zonder voorraad kan een apotheek bestellen, tot voorraad plus "Nog te koop".
  Bestellingen die erin passen, wachten op die inkoop in plaats van een nieuwe offerte te maken. Bovenaan de
  inkoopofferte staat welke bestellingen al stuks namen (offerte of bevestigd), met een link naar elke bestelling.
  Meer regels voor hetzelfde product zijn stappen in hun volgorde: eerst zonder korting, dan 20%, dan 40%.
  Rekenen bestellingen of offertes met een voorverkoop (haar stuks en haar prijs), dan kan ze niet geannuleerd
  worden, gaat het vinkje niet uit, gaat een regel niet weg of onder wat besteld is, en blijven prijs en korting
  van die regel vast. De melding zegt welke bestellingen het zijn en wat je moet doen, met een knop die ze opent.
  Verander je het aantal van een stap, dan blijven haar prijs en korting staan (Odoo zette ze terug naar die van
  de leverancier). Een voorverkoop wordt niet samengevoegd met een andere offerteaanvraag.
* Inkoop: een regel van een bevestigde inkoop verwijderen of een inkoop met een leveranciersfactuur annuleren
  weigert Odoo zelf. De melding zegt dan ook wat je wel kan doen, met een knop naar de inkoop of de factuur.
  Gewone inkopen bewerk je verder zoals altijd.
""",
    'author': 'Almoustafa Elhandouz (Nexu)',
    'category': 'Inventory/Inventory',
    'depends': ['sale_stock', 'stock_account', 'website_sale_stock', 'purchase_stock', 'website_sale_discounted_products'],
    'data': [
        'views/product_views.xml',
        'views/templates.xml',
        'views/purchase_views.xml',
        'views/sale_views.xml',
    ],
    'installable': True,
    'license': 'LGPL-3',
}
