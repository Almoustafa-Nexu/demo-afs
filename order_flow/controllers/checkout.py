from odoo.exceptions import ValidationError
from odoo.http import request, route

from odoo.addons.website_sale.controllers.main import WebsiteSale


class WebsiteSaleQuotation(WebsiteSale):
    """Afrekenen zonder betalen: de bestelling gaat als offerte naar AFS. Lukt dat niet, dan loopt alles zoals in Odoo."""

    @route()
    def shop_checkout(self, try_skip_step=None, **query_params):
        # Odoo eerst: dat kiest ook de levermethode. Valt er iets te kiezen, dan blijft de afrekenpagina.
        response = super().shop_checkout(try_skip_step=try_skip_step, **query_params)
        order = request.cart
        if self._has_choice_to_make(order) or not self._can_checkout_as_quotation(order):
            return response
        return self._checkout_as_quotation(order)

    @route()
    def shop_payment(self, **post):
        # Na Bevestigen op de afrekenpagina: geen betaalpagina maar meteen de offerte
        order = request.cart
        if not self._can_checkout_as_quotation(order):
            return super().shop_payment(**post)
        return self._checkout_as_quotation(order)

    def _has_choice_to_make(self, order):
        """Meer dan een levermethode, of afhalen in een apotheek: de klant kiest zelf."""
        if not order._has_deliverable_products():
            return False
        methods = order._get_delivery_methods()
        return len(methods) > 1 or any(m.delivery_type == 'in_store' for m in methods)

    def _can_checkout_as_quotation(self, order):
        if not order or request.env.user._is_public() or self._check_cart_and_addresses(order):
            return False
        try:
            order._check_cart_is_ready_to_be_paid()
        except ValidationError:
            return False
        return True

    def _checkout_as_quotation(self, order):
        order._recompute_cart()
        order.with_context(tracking_disable=True).action_quotation_sent()
        request.session['sale_last_order_id'] = order.id
        request.website.sale_reset()
        return request.redirect('/shop/confirmation')
