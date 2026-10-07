from datetime import date, datetime, time

from odoo import api, fields, models
from odoo.exceptions import ValidationError


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    def _verify_updated_quantity(self, order_line, product_id, new_qty, uom_id, **kwargs):
        """Winkelwagen in de personeelsshop: nooit meer dan de jaarlimiet van het product."""
        qty, warning = super()._verify_updated_quantity(order_line, product_id, new_qty, uom_id, **kwargs)
        template = self.env['product.product'].browse(product_id).product_tmpl_id
        allowed = self._afs_staff_allowed_qty(template, order_line)
        if allowed is None or qty <= allowed:
            return qty, warning
        return allowed, self._afs_staff_limit_message(template)

    def _check_cart_is_ready_to_be_paid(self):
        """Afrekenen: de limiet geldt ook voor wat al in de winkelwagen zat."""
        for line in self.order_line:
            allowed = self._afs_staff_allowed_qty(line.product_template_id, line)
            if allowed is not None and line.product_uom_qty > allowed:
                raise ValidationError(self._afs_staff_limit_message(line.product_template_id))
        return super()._check_cart_is_ready_to_be_paid()

    def _afs_staff_allowed_qty(self, template, order_line):
        """Hoeveel van dit product nog mag op deze regel; None als er geen limiet geldt."""
        limit = template.afs_staff_year_limit
        if not (limit and self.website_id.afs_staff_shop):
            return None
        other_lines = (self.order_line - order_line).filtered(lambda l: l.product_template_id == template)
        in_cart = sum(other_lines.mapped('product_uom_qty'))
        return max(limit - self._afs_staff_ordered_this_year(template) - in_cart, 0)

    def _afs_staff_ordered_this_year(self, template):
        """Wat de klant van deze winkelwagen dit jaar al bestelde in een personeelsshop."""
        return self._afs_staff_ordered_by(self.partner_id, template)

    @api.model
    def _afs_staff_ordered_by(self, partner, template):
        """Hoeveel stuks dit personeelslid dit kalenderjaar bestelde in een personeelsshop.

        Telt offertes en orders. Winkelwagens (concept) en geannuleerde orders tellen niet mee.
        """
        year_start = datetime.combine(date(fields.Date.today().year, 1, 1), time.min)
        lines = self.env['sale.order.line'].sudo().search([
            ('order_id.partner_id', '=', partner.id),
            ('order_id.website_id.afs_staff_shop', '=', True),
            ('order_id.state', 'in', ('sent', 'sale')),
            ('order_id.date_order', '>=', year_start),
            ('product_template_id', '=', template.id),
        ])
        return sum(lines.mapped('product_uom_qty'))

    def _afs_staff_limit_message(self, template):
        return self.env._(
            "Je mag van %(product)s maximaal %(limit)s stuks per jaar bestellen. "
            "Dit jaar bestelde je er al %(ordered)s.",
            product=template.name,
            limit=template.afs_staff_year_limit,
            ordered=int(self._afs_staff_ordered_this_year(template)),
        )