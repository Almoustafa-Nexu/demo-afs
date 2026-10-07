from odoo.http import request

from odoo.addons.website_sale.controllers.main import WebsiteSale


class WebsiteSalePromotions(WebsiteSale):

    def _shop_lookup_products(self, options, post, search, website):
        """Producten in promotie uit de gewone shoplijst halen: die staan in het blok "Promoties"."""
        fuzzy_search_term, product_count, products = super()._shop_lookup_products(
            options, post, search, website,
        )
        if promo_products := request.env['product.template']._get_promo_products():
            products -= promo_products
            product_count = len(products)
        return fuzzy_search_term, product_count, products
