import logging

from odoo import api, fields, models
from odoo.fields import Domain
from odoo.http import request

from odoo.addons.website_sale.models.website import PRICELIST_SESSION_CACHE_KEY

_logger = logging.getLogger(__name__)


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    promo_only = fields.Boolean(
        string="Alleen tijdens acties",
        help="Aangevinkt: het product staat alleen in de webshop zolang er een actie loopt.\n"
             "Niet aangevinkt: het product staat altijd in de webshop, maar is buiten een actie "
             "alleen bestelbaar uit voorraad.",
    )
    promo_running = fields.Boolean(string="Actie liep bij de laatste controle", copy=False)

    # ------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------

    @api.model_create_multi
    def create(self, vals_list):
        products = super().create(vals_list)
        if any(vals.get('promo_only') for vals in vals_list):
            self._sync_promo_availability()
        return products

    def write(self, vals):
        res = super().write(vals)
        if 'promo_only' in vals:
            self._sync_promo_availability()
        return res

    # ------------------------------------------------------------
    # Promoties tonen: webshop en blokken
    # ------------------------------------------------------------

    def _get_promo_products(self, pricelist=None):
        """Gepubliceerde producten die nu goedkoper zijn dan hun verkoopprijs. Een andere module kan er
        producten bij zetten (Korting per partij: stappen naar korting, nog aan de normale prijs).

        Alleen producten die de shop aan deze bezoeker mag tonen (dezelfde regel als de shop,
        sale_product_domain). Zo werkt ook AFS - Magazijntoegang hier.

        :param pricelist: standaard de prijslijst van de bezoeker
        :return: product.template (sudo), in de volgorde van de webshop
        """
        pricelist = pricelist or getattr(request, 'pricelist', False)
        if not pricelist:
            return self.sudo().browse()
        website = self.env['website'].get_current_website()
        variants = self.sudo().search(Domain.AND([
            website.sale_product_domain(),
            [('is_published', '=', True)],
        ])).product_variant_id
        prices = pricelist._get_products_price(variants, quantity=1.0)
        return variants.filtered(
            lambda v: v.list_price and prices.get(v.id, v.list_price) < v.list_price - 0.01
        ).product_tmpl_id

    def _get_promotions_preview(self, limit=4):
        """Echte promoproducten, met kortingspercentage, voor het voorbeeld van het blok "Promoties"."""
        try:
            pricelist = self._get_preview_pricelist()
            products = self._get_promo_products(pricelist)
            prices = pricelist._get_products_price(products.product_variant_id, quantity=1.0)
        except Exception:
            # Het voorbeeld mag het blokkenpaneel van de editor nooit laten crashen
            _logger.exception("Voorbeeld van het blok Promoties kon niet geladen worden")
            return []
        preview = []
        for product in products:
            discount = round(100 * (product.list_price - prices[product.product_variant_id.id]) / product.list_price) \
                if product.list_price else 0
            if discount > 0:  # in actie maar nu niet goedkoper: niet in het voorbeeld
                preview.append({'product': product, 'discount': discount})
        return preview[:limit]

    def _get_shop_preview(self, limit=4):
        """Echte producten, zonder promoties, voor het voorbeeld van het blok "Shop"."""
        try:
            website = self.env['website'].get_current_website()
            return [{'product': product} for product in self.search(website.sale_product_domain(), limit=limit)]
        except Exception:
             _logger.exception("Voorbeeld van het blok Shop kon niet geladen worden")
             return []

    def _get_preview_pricelist(self):
        """Prijslijst voor de voorbeelden in het venster "Blok invoegen".

        Dat venster draait in de backend, zonder request.pricelist. Dan nemen we de prijslijst
        die de website voor deze gebruiker onthoudt, zodat het voorbeeld dezelfde producten
        toont als het blok zelf.
        """
        Pricelist = self.env['product.pricelist'].sudo()
        if not request:
            return Pricelist
        if pricelist := getattr(request, 'pricelist', False):
            return pricelist
        if pricelist := Pricelist.browse(request.session.get(PRICELIST_SESSION_CACHE_KEY)).exists():
            return pricelist
        available = self.env['website'].get_current_website().get_pricelist_available()
        own = self.env.user.partner_id.property_product_pricelist
        return own if own in available else available[:1]

    # ------------------------------------------------------------
    # Acties: bestelbaar zonder voorraad zolang de actie loopt
    # ------------------------------------------------------------

    @api.model
    def _sync_promo_availability(self):
        """Acties openen en sluiten in de webshop.

        Begint een actie, dan is het product ook zonder voorraad bestelbaar (die bestellingen bundelt AFS
        in één inkooporder per leverancier). Eindigt ze, dan weer alleen uit voorraad. Alleen op die twee
        momenten: wat je ertussen zelf instelt (Ook verkopen indien niet op voorraad), blijft staan.
        "Alleen tijdens acties": het product staat alleen in de webshop zolang de actie loopt.

        Draait na elke wijziging van een actie, en elke 15 minuten voor acties die beginnen of aflopen.
        """
        in_action = self.env['product.pricelist.item']._get_running_actions()._get_product_templates()
        products = self.sudo().search([('sale_ok', '=', True)])
        running = self.sudo().search([('promo_running', '=', True)])
        started = (products & in_action).filtered('is_storable') - running
        ended = running - in_action
        started.write({'allow_out_of_stock_order': True, 'promo_running': True})
        ended.write({'allow_out_of_stock_order': False, 'promo_running': False})
        _switch(products.filtered('promo_only'), 'is_published', on=in_action)


def _switch(records, field, on):
    """Zet `field` aan voor de records die in `on` zitten en uit voor de rest.

    Schrijft alleen wat echt verandert.
    """
    turn_on = records & on
    (turn_on - turn_on.filtered(field)).write({field: True})
    (records - turn_on).filtered(field).write({field: False})