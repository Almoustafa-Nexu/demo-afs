from odoo import models
from odoo.fields import Domain

GENERIC_CARD = 'website_sale.dynamic_filter_template_product_product_products_item'
PROMO_CARD = 'website_sale_discounted_products.dynamic_filter_template_product_product_promo'
WEBSHOP_FILTERS = (
    'website_sale_discounted_products.dynamic_filter_discounted_products',
    'website_sale_discounted_products.dynamic_filter_shop_products',
)


class WebsiteSnippetFilter(models.Model):
    _inherit = 'website.snippet.filter'

    # Odoo roept de twee filters aan via _get_products('discounted') en _get_products('shop')
    # (zie data/website_snippet_filter_data.xml), bij elk paginabezoek opnieuw. `domain` bevat
    # al Odoo's standaardregels: gepubliceerd, website, bedrijf en de categorie uit het blok.

    def _get_products_discounted(self, website, limit, domain, **kwargs):
        """Filter "Promoties": alleen producten die nu in promotie zijn."""
        promo_products = self.env['product.template']._get_promo_products()
        return self._search_products(
            Domain(domain) & Domain('id', 'in', promo_products.product_variant_id.ids), limit,
        )

    def _get_products_shop(self, website, limit, domain, **kwargs):
        """Filter "Shop": alle producten van de webshop, ook die in promotie."""
        return self._search_products(Domain(domain), limit)

    def _render(self, template_key, limit, *args, **kwargs):
        """Onze filters tonen altijd onze productkaart (percentage, Voorheen, Nu), ook in blokken
        die al op een pagina staan met Odoo's standaardkaart in hun instellingen."""
        if template_key == GENERIC_CARD and self._is_webshop_filter():
            template_key = PROMO_CARD
        return super()._render(template_key, limit, *args, **kwargs)

    def _prepare_sample(self, length=6, **options):
        """Geen voorbeeldproducten van Odoo (stoel, lamp...) in de editor: een leeg blok blijft leeg."""
        if self._is_webshop_filter():
            return []
        return super()._prepare_sample(length, **options)

    def _is_webshop_filter(self):
        """Is dit de filter "Promoties" of "Shop" van deze module?"""
        return len(self) == 1 and self.id in {
            self.env['ir.model.data']._xmlid_to_res_id(xmlid, raise_if_not_found=False)
            for xmlid in WEBSHOP_FILTERS
        }

    def _search_products(self, domain, limit):
        return self.env['product.product'].with_context(display_default_code=False).search(domain, limit=limit)
