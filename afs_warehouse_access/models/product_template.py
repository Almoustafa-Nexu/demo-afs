from odoo import api, fields, models


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    afs_shop_allowed = fields.Boolean(
        string="Bestelbaar voor deze klant",
        compute='_compute_afs_shop_allowed',
        search='_search_afs_shop_allowed',
    )

    @api.depends_context('uid')
    def _compute_afs_shop_allowed(self):
        blocked = self._afs_blocked_for(self.env.user.partner_id)
        for template in self:
            template.afs_shop_allowed = template.id not in blocked.ids

    def _search_afs_shop_allowed(self, operator, value):
        """Zoeken op dit veld: Odoo 19 vraagt 'in' [True] (toegelaten) of 'in' [False] (geblokkeerd)."""
        if operator != 'in':
            return NotImplemented
        blocked = self._afs_blocked_for(self.env.user.partner_id)
        if True in value:
            return [('id', 'not in', blocked.ids)]
        return [('id', 'in', blocked.ids)]

    @api.model
    def _afs_blocked_for(self, partner):
        """Producten die alleen vanuit een magazijn naar de klant gaan dat niet voor hem openstaat.

        Kijkt naar de routes op het product, zoals "Levering vanuit Markgraven". Een route die ook
        vanuit een ander magazijn levert, zoals Aanvullen per order (MTO), blijft open.
        """
        closed = self.env['stock.warehouse']._afs_closed_for(partner)
        if not closed:
            return self.browse()
        routes = self.env['stock.route'].sudo().search([('product_selectable', '=', True)])
        closed_routes = routes.filtered(lambda route: _delivers_only_from(route, closed))
        return self.sudo().search([('route_ids', 'in', closed_routes.ids)])


def _delivers_only_from(route, warehouses):
    """Levert deze route alleen vanuit deze magazijnen aan klanten?"""
    to_customer = route.rule_ids.filtered(lambda rule: rule.location_dest_id.usage == 'customer')
    return bool(to_customer) and all(rule.location_src_id.warehouse_id in warehouses for rule in to_customer)