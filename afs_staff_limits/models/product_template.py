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
        """Productpagina in de personeelsshop: de limiet en hoeveel het personeelslid nog mag.

        Wat al in de winkelwagen zit, telt mee.
        :return: {'limit': 15, 'remaining': 3}, of None als er geen limiet geldt
        """
        self.ensure_one()
        limit = self.afs_staff_year_limit
        website = self.env['website'].get_current_website()
        if not (limit and website.afs_staff_shop) or self.env.user._is_public():
            return None
        ordered = self.env['sale.order']._afs_staff_ordered_by(self.env.user.partner_id, self)
        cart_lines = request.cart.order_line.filtered(lambda line: line.product_template_id == self)
        in_cart = sum(cart_lines.mapped('product_uom_qty'))
        return {'limit': limit, 'remaining': max(int(limit - ordered - in_cart), 0)}