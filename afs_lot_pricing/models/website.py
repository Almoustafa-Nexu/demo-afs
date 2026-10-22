from odoo import models


class Website(models.Model):
    _inherit = 'website'

    def _get_product_available_qty(self, product, **kwargs):
        """Wat nog te koop is in de voorverkoop, telt mee als beschikbaar."""
        qty = super()._get_product_available_qty(product, **kwargs)
        template = product.product_tmpl_id
        return qty + template._afs_presale_free_qty(template._afs_website_warehouse(self), product)
