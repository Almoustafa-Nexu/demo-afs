{
    'name': 'AFS - Huisstijl webshop',
    'version': '19.0.1.3.4',
    'summary': 'Groene AFS-huisstijl voor de webshop: menu, titelbanner, productkaartjes, knoppen en footer.',
    'description': """
Huisstijl webshop
=================
Alleen opmaak (SCSS), geen inhoud: de webshop krijgt de stijl van afscv.be.

* Lettertype Poppins, groen #6ba342 voor knoppen, links en accenten.
* Menu: hoofdletters, groene lijn boven het actieve menu-item en bij hover.
* Titel van de shop ("Alle producten") en van een categorie: groene banner met witte tekst.
* Categorietabs, zoekbalk en sorteerknop in dezelfde stijl.
* Productkaartjes: wit, ronde hoeken, schaduw, groene productnaam. Ronde sticker op de foto: het
  kortingspercentage, of "Actie, tot -40%" als de prijs nog normaal is maar er stappen naar korting komen.
* Productpagina: rustig prijsblok, het doel van de apotheken, de voorraad en de prijs per stap.
* Winkelwagen: per partij een korte regel met een groen kortingslabel.
* Footer: lichtgroen verloop, pijltjes voor de links, zwarte balk onderaan.

De hoofdkleur van het thema zet je zelf: Website > Bewerken > Thema > Kleuren, eerste kleur #6ba342.
""",
    'author': 'Almoustafa Elhandouz (Nexu)',
    'category': 'Website/Website',
    'depends': ['website_sale'],
    'assets': {
        'web.assets_frontend': [
            'afs_website_style/static/src/scss/afs_style.scss',
        ],
    },
    'installable': True,
    'license': 'LGPL-3',
}
