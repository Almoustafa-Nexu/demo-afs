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
        """De categorie met het vinkje "Automatisch: producten in actie", voor deze website (of leeg)."""
        website = self.env['website'].get_current_website()
        return self.sudo().search([('afs_auto_promotions', '=', True)] + website.website_domain(), limit=1)

    @api.model
    def _afs_default_promotions_category(self):
        """Eenmalig, bij het bijwerken: het vinkje op de categorie "Lopende acties" zetten.
        Daarna beslis je zelf (een vinkje dat je later weghaalt, komt niet terug)."""
        params = self.env['ir.config_parameter'].sudo()
        key = 'website_sale_discounted_products.promotions_category_set'
        if params.get_param(key):
            return
        params.set_param(key, '1')
        if not self.search_count([('afs_auto_promotions', '=', True)]):
            self.search([('name', '=ilike', 'lopende acties')], limit=1).afs_auto_promotions = True
