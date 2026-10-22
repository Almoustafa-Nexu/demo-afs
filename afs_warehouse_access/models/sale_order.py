from odoo import models
from odoo.exceptions import ValidationError


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    def _verify_updated_quantity(self, order_line, product_id, new_qty, uom_id, **kwargs):
        """Winkelwagen: een product uit een gesloten magazijn komt er niet in."""
        product = self.env['product.product'].browse(product_id)
        if self._afs_is_blocked(product.product_tmpl_id):
            return 0, self.env._("%(product)s is niet beschikbaar voor jouw apotheek.", product=product.name)
        return super()._verify_updated_quantity(order_line, product_id, new_qty, uom_id, **kwargs)

    def _check_cart_is_ready_to_be_paid(self):
        """Afrekenen: ook wat al in de winkelwagen zat, wordt tegengehouden."""
        blocked = self.order_line.product_template_id.filtered(self._afs_is_blocked)
        if blocked:
            raise ValidationError(self.env._(
                "%(products)s is niet beschikbaar voor jouw apotheek. Haal het uit je winkelwagen.",
                products=", ".join(blocked.mapped('name')),
            ))
        return super()._check_cart_is_ready_to_be_paid()

    def _afs_is_blocked(self, template):
        # AFS (interne gebruiker) mag alles
        if self.env.user._is_internal():
            return False
        return template in self.env['product.template']._afs_blocked_for(self.partner_id)
