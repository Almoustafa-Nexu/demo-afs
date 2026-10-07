from odoo.exceptions import ValidationError
from odoo.http import request, route

from odoo.addons.website_sale.controllers.main import WebsiteSale


class WebsiteSaleQuotation(WebsiteSale):
    """Afrekenen zonder betalen: de bestelling komt als offerte bij AFS.

    AFS kijkt de offerte na en bevestigt ze zelf; betalen gebeurt later, via de factuur.
    Kan het niet (geen account, adres of levermethode ontbreekt), dan loopt het
    afrekenen zoals standaard in Odoo.
    """

    @route()
    def shop_checkout(self, try_skip_step=None, **query_params):
        """Afrekenen in één klik: de offerte wordt meteen doorgestuurd.

        Valt er iets te kiezen (meer dan één levermethode, bv. afhalen in een apotheek in
        de personeelsshop), dan toont Odoo eerst de afrekenpagina. Na Bevestigen volgt
        dan shop_payment hieronder.
        """
        # Eerst Odoo zelf: dat kiest ook de levermethode
        response = super().shop_checkout(try_skip_step=try_skip_step, **query_params)
        order_sudo = request.cart
        if self._has_choice_to_make(order_sudo) or not self._can_checkout_as_quotation(order_sudo):
            return response
        return self._checkout_as_quotation(order_sudo)

    @route()
    def shop_payment(self, **post):
        """Na Bevestigen op de afrekenpagina: geen betaalpagina, maar meteen de offerte."""
        order_sudo = request.cart
        if not self._can_checkout_as_quotation(order_sudo):
            return super().shop_payment(**post)
        return self._checkout_as_quotation(order_sudo)

    def _has_choice_to_make(self, order_sudo):
        """De klant moet zelf kiezen op de afrekenpagina: er is meer dan één levermethode,
        of er is afhalen in een apotheek (dan kiest de klant de apotheek)."""
        if not order_sudo._has_deliverable_products():
            return False
        methods = order_sudo._get_delivery_methods()
        return len(methods) > 1 or any(m.delivery_type == 'in_store' for m in methods)

    def _can_checkout_as_quotation(self, order_sudo):
        """Ingelogde klant, geldige winkelwagen, adressen en levermethode in orde."""
        if not order_sudo or request.env.user._is_public() or self._check_cart_and_addresses(order_sudo):
            return False
        try:
            order_sudo._check_cart_is_ready_to_be_paid()
        except ValidationError:
            return False
        return True

    def _checkout_as_quotation(self, order_sudo):
        order_sudo._recompute_cart()
        order_sudo.with_context(tracking_disable=True).action_quotation_sent()
        request.session['sale_last_order_id'] = order_sudo.id
        request.website.sale_reset()
        return request.redirect('/shop/confirmation')