from odoo import models
from odoo.fields import Domain


class WebsiteSnippetFilter(models.Model):
    _inherit = 'website.snippet.filter'

    def _prepare_values(self, limit=None, search_domain=None, **options):
        """Productblokken (Producten, Promoties, Shop): dezelfde regel als de shop.

        Interne gebruikers (AFS) zien alles.
        """
        if self.model_name == 'product.product' and not self.env.user._is_internal():
            allowed = Domain('product_tmpl_id.afs_shop_allowed', '=', True)
            search_domain = Domain(search_domain or []) & allowed
        return super()._prepare_values(limit=limit, search_domain=search_domain, **options)
