from odoo import models


class StockRule(models.Model):
    _inherit = 'stock.rule'

    def _make_po_get_domain(self, company_id, values, partner):
        """Automatische aanvullingen komen nooit op een inkoopofferte in voorverkoop."""
        return super()._make_po_get_domain(company_id, values, partner) + (('afs_presale', '=', False),)
