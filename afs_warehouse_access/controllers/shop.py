from werkzeug.exceptions import NotFound

from odoo.http import request, route

from odoo.addons.website_sale.controllers.main import WebsiteSale


class WebsiteSaleWarehouseAccess(WebsiteSale):

    @route()
    def product(self, product, category=None, pricelist=None, **kwargs):
        """Product uit een gesloten magazijn: bestaat niet voor deze apotheek, ook niet via de link. AFS ziet alles."""
        if not request.env.user._is_internal() and not product.afs_shop_allowed:
            raise NotFound()
        return super().product(product, category=category, pricelist=pricelist, **kwargs)
