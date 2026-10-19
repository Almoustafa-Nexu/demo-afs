from odoo import models
from odoo.fields import Domain


class WebsiteSnippetFilter(models.Model):
    _inherit = 'website.snippet.filter'

    def _prepare_values(self, limit=None, search_domain=None, **options):
        """Productblokken (Producten, Promoties, Shop): dezelfde regel als de shop.

        Interne gebruikers (AFS) zien alles. Het blok stuurt "hide_variants" mee in de zoekregel (een teken voor
        Odoo, geen voorwaarde): dat blijft staan, Odoo haalt het er zelf uit.
        """
        if self.model_name == 'product.product' and not self.env.user._is_internal():
            search_domain = list(search_domain or [])
            signs = [item for item in search_domain if item == 'hide_variants']
            rules = [item for item in search_domain if item != 'hide_variants']
            search_domain = list(Domain(rules) & Domain('product_tmpl_id.afs_shop_allowed', '=', True)) + signs
        return super()._prepare_values(limit=limit, search_domain=search_domain, **options)
