from odoo import models
from odoo.fields import Domain


class Website(models.Model):
    _inherit = 'website'

    def sale_product_domain(self):
        """Shop, zoeken en categorieën: verberg producten uit een magazijn dat niet openstaat.

        Interne gebruikers (AFS) zien alles.
        """
        domain = super().sale_product_domain()
        if self.env.user._is_internal():
            return domain
        return Domain.AND([domain, [('afs_shop_allowed', '=', True)]])
