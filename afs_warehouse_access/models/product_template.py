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
        # Odoo 19 zoekt met 'in' [True] (toegelaten) of 'in' [False] (geblokkeerd)
        if operator != 'in':
            return NotImplemented
        blocked = self._afs_blocked_for(self.env.user.partner_id)
        return [('id', 'not in' if True in value else 'in', blocked.ids)]

    @api.model
    def _afs_blocked_for(self, partner):
        """Producten waarvan de route alleen levert vanuit een magazijn dat niet openstaat voor deze klant.
        Een route die ook elders levert (bv. MTO) blijft open."""
        closed = self.env['stock.warehouse']._afs_closed_for(partner)
        if not closed:
            return self.browse()
        routes = self.env['stock.route'].sudo().search([('product_selectable', '=', True)])
        return self.sudo().search([('route_ids', 'in', routes.filtered(lambda r: _delivers_only_from(r, closed)).ids)])


def _delivers_only_from(route, warehouses):
    to_customer = route.rule_ids.filtered(lambda rule: rule.location_dest_id.usage == 'customer')
    return bool(to_customer) and all(rule.location_src_id.warehouse_id in warehouses for rule in to_customer)
