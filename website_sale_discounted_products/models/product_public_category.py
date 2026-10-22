from odoo import api, fields, models


class ProductPublicCategory(models.Model):
    _inherit = 'product.public.category'

    afs_auto_promotions = fields.Boolean(
        string="Automatisch: producten in actie",
        help="Deze categorie vult zich vanzelf met de producten die nu korting hebben (de lopende acties), "
             "in plaats van de producten die je er zelf in zet. Ze staat bovenaan de shop.",
    )

    @api.model
    def _afs_promotions_category(self):
        """De categorie met het vinkje Automatisch: producten in actie, voor deze website (of leeg)."""
        website = self.env['website'].get_current_website()
        return self.sudo().search([('afs_auto_promotions', '=', True)] + website.website_domain(), limit=1)
