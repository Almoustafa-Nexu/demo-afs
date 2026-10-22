from odoo import fields, models
from odoo.http import request


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    afs_staff_year_limit = fields.Integer(
        string="Max. per personeelslid per jaar",
        help="Hoeveel stuks één personeelslid per kalenderjaar mag bestellen in de personeelsshop. "
             "0: geen limiet.",
    )

    def _afs_staff_limit_info(self):
        """Productpagina: {'limit', 'remaining'} (de winkelwagen telt mee), of None zonder limiet."""
        self.ensure_one()
        limit = self.afs_staff_year_limit
        if not (limit and self.env['website'].get_current_website().afs_staff_shop) or self.env.user._is_public():
            return None
        ordered = self.env['sale.order']._afs_staff_ordered_by(self.env.user.partner_id, self)
        in_cart = sum(request.cart.order_line.filtered(lambda l: l.product_template_id == self).mapped('product_uom_qty'))
        return {'limit': limit, 'remaining': max(int(limit - ordered - in_cart), 0)}
