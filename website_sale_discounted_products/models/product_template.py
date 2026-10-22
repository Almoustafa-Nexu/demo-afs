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

    # ---- Promoties tonen ----

    def _get_promo_products(self, pricelist=None):
        """Gepubliceerde producten die de shop deze bezoeker toont en die nu goedkoper zijn dan hun verkoopprijs
        (standaard volgens de prijslijst van de bezoeker). Korting per partij voegt er producten aan toe."""
        pricelist = pricelist or getattr(request, 'pricelist', False)
        if not pricelist:
            return self.sudo().browse()
        website = self.env['website'].get_current_website()
        variants = self.sudo().search(Domain.AND([
            website.sale_product_domain(), [('is_published', '=', True)],
        ])).product_variant_id
        prices = pricelist._get_products_price(variants, quantity=1.0)
        return variants.filtered(
            lambda v: v.list_price and prices.get(v.id, v.list_price) < v.list_price - 0.01
        ).product_tmpl_id

    def _get_promotions_preview(self, limit=4):
        """Voorbeeld van het blok Promoties (venster Blok invoegen): echte promoproducten met hun korting."""
        try:
            pricelist = self._get_preview_pricelist()
            products = self._get_promo_products(pricelist)
            prices = pricelist._get_products_price(products.product_variant_id, quantity=1.0)
        except Exception:
            # het voorbeeld mag de editor nooit laten crashen
            _logger.exception("Voorbeeld van het blok Promoties kon niet geladen worden")
            return []
        preview = []
        for product in products:
            price = prices[product.product_variant_id.id]
            discount = round(100 * (product.list_price - price) / product.list_price) if product.list_price else 0
            if discount > 0:
                preview.append({'product': product, 'discount': discount})
        return preview[:limit]

    def _get_shop_preview(self, limit=4):
        """Voorbeeld van het blok Shop: echte producten."""
        try:
            website = self.env['website'].get_current_website()
            return [{'product': product} for product in self.search(website.sale_product_domain(), limit=limit)]
        except Exception:
            _logger.exception("Voorbeeld van het blok Shop kon niet geladen worden")
            return []

    def _get_preview_pricelist(self):
        """Het venster Blok invoegen draait zonder request.pricelist: neem de prijslijst die de website onthoudt."""
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

    # ---- Acties openen en sluiten ----

    @api.model
    def _sync_promo_availability(self):
        """Begint een actie: bestelbaar zonder voorraad. Eindigt ze: weer alleen uit voorraad. Alleen op die twee
        momenten, dus wat je ertussen zelf instelt blijft. Alleen tijdens acties: gepubliceerd zolang de actie loopt.
        Draait na elke wijziging van een actie en elke 15 minuten."""
        in_action = self.env['product.pricelist.item']._get_running_actions()._get_product_templates()
        products = self.sudo().search([('sale_ok', '=', True)])
        running = self.sudo().search([('promo_running', '=', True)])
        started = (products & in_action).filtered('is_storable') - running
        ended = running - in_action
        started.write({'allow_out_of_stock_order': True, 'promo_running': True})
        ended.write({'allow_out_of_stock_order': False, 'promo_running': False})
        promo_only = products.filtered('promo_only')
        publish = promo_only & in_action
        (publish - publish.filtered('is_published')).write({'is_published': True})
        (promo_only - publish).filtered('is_published').write({'is_published': False})
