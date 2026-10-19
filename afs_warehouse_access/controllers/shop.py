from werkzeug.exceptions import NotFound

from odoo.http import request, route

from odoo.addons.website_sale.controllers.main import WebsiteSale


class WebsiteSaleWarehouseAccess(WebsiteSale):

    @route()
    def product(self, product, category=None, pricelist=None, **kwargs):
        """Productpagina: een product uit een magazijn dat niet openstaat voor deze apotheek, bestaat voor haar
        niet, ook niet via de directe link. Interne gebruikers (AFS) zien alles."""
        if not request.env.user._is_internal() and not product.afs_shop_allowed:
            raise NotFound()
        return super().product(product, category=category, pricelist=pricelist, **kwargs)
