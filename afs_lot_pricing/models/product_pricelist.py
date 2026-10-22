from odoo import fields, models
from odoo.tools import float_is_zero, float_round


def _template(product):
    return product.product_tmpl_id if product._name == 'product.product' else product


def _per_uom(product, price, uom):
    """Prijs per eenheid van het product omrekenen naar `uom`."""
    return product.uom_id._compute_price(price, uom) if uom and uom != product.uom_id else price


def _split_qty(product, quantity, uom):
    """Verdeel `quantity` over de partijen en de voorverkoop, de oudste eerst.
    :return: (aantal, [(partij of inkoopregel, aantal, kostprijs)], rest) in de eenheid van het product, of None"""
    rows = _template(product)._afs_shop_rows()
    if not rows:
        return None
    qty = quantity or 1.0
    if uom and uom != product.uom_id:
        qty = uom._compute_quantity(qty, product.uom_id, raise_if_failure=False)
    qty = qty if qty > 0 else 1.0
    parts, rest = [], qty
    for source, available, cost in rows:
        if rest <= 0:
            break
        take = min(available, rest)
        parts.append((source, take, cost))
        rest -= take
    return qty, parts, rest


def _vendor_cost(product, date):
    """Prijs van de leverancier zonder korting, per eenheid van het product en in de munt van de kostprijs; of None."""
    variant = (product if product._name == 'product.product' else product.product_variant_id).sudo()
    day = fields.Date.to_date(date) or fields.Date.context_today(variant)
    seller = variant._select_seller(quantity=None, date=day, uom_id=variant.uom_id)
    if not seller:
        return None
    price = seller.product_uom_id._compute_price(seller.price, variant.uom_id)
    currency = variant.cost_currency_id or variant.env.company.currency_id
    return seller.currency_id._convert(price, currency, variant.env.company, day, round=False)


LABEL_PREFIXES = ('Partij ', 'Voorverkoop: partij ', 'Nog niet op voorraad')


def source_label(source):
    """Laatste regel van de omschrijving: de partij, de voorverkoop of nog niet op voorraad."""
    if not source:
        return "Nog niet op voorraad (voorlopige prijs)"
    if source._name == 'purchase.order.line':
        return "Voorverkoop: partij %s" % source.sudo()._afs_lot_name()
    return "Partij %s" % source.sudo().name


def strip_source_label(name):
    """Omschrijving zonder de regel van source_label (de factuur zet er de geleverde partij onder)."""
    head, sep, last = (name or '').rpartition('\n')
    return head if sep and last.startswith(LABEL_PREFIXES) else name


def _source_purchase(source):
    """(inkoopprijs zonder korting, korting %) van de inkoop van een partij of voorverkoopregel, of (None, 0.0)."""
    line = source if not source or source._name == 'purchase.order.line' else source._afs_purchase_line()
    if not line or not 0 < (line.discount or 0.0) < 100:
        return None, 0.0
    return line._afs_gross_cost(), line.discount


def shown_base(env, base, net):
    """Prijs zonder korting op de cent; blijft er geen korting over, dan `net`."""
    precision = env['decimal.precision']
    rounded = float_round(base or 0.0, precision_digits=precision.precision_get('Product Price'))
    if rounded <= 0 or rounded <= net or float_is_zero((rounded - net) / rounded * 100,
                                                       precision_digits=precision.precision_get('Discount')):
        return net
    return rounded


def best_discount(env, base, net, qty, currency):
    """Korting met 2 decimalen van `base` naar `net` zodat `qty` stuks op de cent `qty` x `net` kosten; anders de
    dichtste, bij gelijkstand liever een cent te veel."""
    if not base or base <= net:
        return 0.0
    precision = env['decimal.precision']
    digits = precision.precision_get('Discount')
    price = float_round(base, precision_digits=precision.precision_get('Product Price'))
    qty = qty or 1.0
    exact = (base - net) / base * 100
    rounded = float_round(exact, precision_digits=digits)
    step = 10 ** -digits

    def gap(discount):
        return currency.round(price * qty * (1 - discount / 100)) - currency.round(net * qty)

    candidates = [d for d in (rounded, rounded - step, rounded + step) if 0 < d < 100] or [rounded]
    return min(candidates, key=lambda d: (abs(gap(d)), gap(d) < 0, abs(d - exact)))


class ProductPricelist(models.Model):
    _inherit = 'product.pricelist'

    afs_lot_pricing = fields.Boolean(
        string="Korting per partij doorrekenen",
        help="Met deze prijslijst betaal je de prijs van de partij die je krijgt (voor producten met hetzelfde "
             "vinkje): in de shop, in de winkelwagen en op de factuur. Aan voor de apotheken, uit voor het personeel.",
    )

    def _afs_normal_rule(self, product, quantity, date, on_cost=False):
        """De regel zonder datums (de prijs van na de actie); met on_cost alleen een regel op kostprijs."""
        self.ensure_one()
        for rule in self._get_applicable_rules(product, date):
            if (not (rule.date_start or rule.date_end) and (not on_cost or rule._afs_on_cost())
                    and rule._is_applicable_for(product, quantity)):
                return rule
        return self.env['product.pricelist.item']


class ProductPricelistItem(models.Model):
    _inherit = 'product.pricelist.item'

    def _afs_on_cost(self):
        return self.base == 'standard_price' and self.compute_price in ('formula', 'percentage')

    def _afs_lot_mode(self, product):
        """'kost' (regel op kostprijs: de kostprijs van de partij telt), 'actie' (regel met datums: de actieprijs is
        een maximum) of False (geen korting per partij)."""
        if len(self) != 1 or not self.pricelist_id.afs_lot_pricing or not _template(product)._afs_uses_lot_pricing():
            return False
        if self._afs_on_cost():
            return 'kost'
        return 'actie' if self.date_start or self.date_end else False

    def _afs_cost_price(self, product, cost, uom, date, currency):
        """Prijs voor kostprijs `cost` volgens de regel op kostprijs (bij een actie de normale regel op kostprijs,
        zonder die regel de kostprijs zelf)."""
        rule = self if self._afs_lot_mode(product) == 'kost' else self.pricelist_id._afs_normal_rule(
            product, 1.0, date, on_cost=True)
        if rule:
            return rule.with_context(afs_lot_cost=cost)._compute_price(product, 1.0, uom, date, currency)
        return self._afs_convert_cost(product, cost, uom, date, currency)

    def _afs_lot_unit_price(self, product, lot_cost, uom, date, currency):
        """Prijs van een stuk uit een partij met kostprijs `lot_cost`; None zonder korting per partij."""
        mode = self._afs_lot_mode(product)
        if mode == 'kost':
            return self._afs_cost_price(product, lot_cost, uom, date, currency)
        if mode == 'actie':
            action_price = self.with_context(afs_lot_skip=True)._compute_price(product, 1.0, uom, date, currency)
            return min(action_price, self._afs_cost_price(product, lot_cost, uom, date, currency))
        return None

    def _afs_lot_display(self, product, lot_cost, source, net_price, uom, date, currency):
        """Met Kortingen aan: (prijs zonder korting, korting %) voor een stuk dat `net_price` kost.
        Korting op de inkoop: die prijs en korting. Actie lager dan de partij: verkoopprijs (actie in %) of de prijs
        van de partij, met korting None (de aanroeper rekent ze uit). Anders de prijs zelf met 0 %."""
        if net_price is None or not self._afs_lot_mode(product):
            return net_price, 0.0
        gross, discount = _source_purchase(source)
        lot_price = self._afs_cost_price(product, lot_cost, uom, date, currency)
        capped = currency.compare_amounts(net_price, lot_price) < 0
        if capped and self._show_discount():
            base = self.with_context(afs_lot_skip=True)._compute_price_before_discount(
                product=product, quantity=1.0, uom=uom, date=date, currency=currency)
        elif gross is not None:
            base = self._afs_cost_price(product, gross, uom, date, currency)
        elif capped:
            base = lot_price
        else:
            return net_price, 0.0
        base = shown_base(self.env, base, net_price)
        if base == net_price:
            return net_price, 0.0
        if capped or currency.compare_amounts(base * (1 - discount / 100), net_price):
            return base, None
        return base, discount

    def _afs_fifo_price(self, product, quantity, uom, date, currency, **kwargs):
        """Gemiddelde prijs per stuk voor `quantity`: oudste partij eerst, dan de voorverkoop, de rest voorlopig."""
        split = _split_qty(product, quantity, uom)
        if not split:
            return self._afs_rest_price(product, quantity, uom or product.uom_id, date, currency, **kwargs)
        qty, parts, rest = split
        unit = product.uom_id
        total = sum(take * self._afs_lot_unit_price(product, cost, unit, date, currency) for _src, take, cost in parts)
        if rest > 0:
            total += rest * self._afs_rest_price(product, qty, unit, date, currency, **kwargs)
        return _per_uom(product, total / qty, uom)

    def _afs_part_price(self, product, source, cost, qty, total, date, currency, show_discount):
        """(prijs, korting %) per stuk voor `qty` stuks uit `source` (kostprijs `cost`), of zonder `source` de
        voorlopige prijs (`total` = alle stuks van het product). show_discount: prijs zonder korting plus korting."""
        unit = product.uom_id
        if source:
            price = self._afs_lot_unit_price(product, cost, unit, date, currency)
            if not show_discount:
                return price, 0.0
            base, discount = self._afs_lot_display(product, cost, source, price, unit, date, currency)
        elif not show_discount:
            return self._afs_rest_price(product, total, unit, date, currency), 0.0
        else:
            base, price = self._afs_rest_display(product, total, unit, date, currency)
            base, discount = shown_base(self.env, base, price), None
        if discount is None:
            discount = best_discount(self.env, base, price, qty, currency)
        return base, discount

    def _afs_lot_parts(self, product, quantity, date, currency, show_discount):
        """Verdeel `quantity` stuks over partijen, voorverkoop en de rest (voorlopige prijs), zoals de orderregels.
        :return: [{'source': partij, inkoopregel of False, 'qty', 'price', 'discount', 'amount'}]"""
        split = _split_qty(product, quantity, product.uom_id)
        if split:
            total, rows, rest = split
        else:
            total = rest = quantity if quantity > 0 else 1.0
            rows = []
        if rest > 0:
            rows = rows + [(False, rest, 0.0)]
        parts = []
        for source, qty, cost in rows:
            price, discount = self._afs_part_price(product, source, cost, qty, total, date, currency, show_discount)
            parts.append({'source': source, 'qty': qty, 'price': price, 'discount': discount,
                          'amount': currency.round(qty * price * (1 - discount / 100))})
        return parts

    def _afs_rest_rule(self, product, quantity, uom, date):
        """Regel voor wat niet uit een partij komt: bij een actie op kostprijs de normale regel, anders deze. Op
        kostprijs met de prijs van de leverancier zonder korting (de Kostprijs zakt na een partij met korting)."""
        rule = self
        if self._afs_lot_mode(product) == 'kost' and (self.date_start or self.date_end):
            uom = uom or product.uom_id
            qty = quantity if uom == product.uom_id else \
                uom._compute_quantity(quantity, product.uom_id, raise_if_failure=False)
            rule = self.pricelist_id._afs_normal_rule(product, qty, date)
        rule = rule.with_context(afs_lot_skip=True)
        cost = _vendor_cost(product, date) if rule._afs_on_cost() else None
        return rule if cost is None else rule.with_context(afs_lot_cost=cost)

    def _afs_rest_price(self, product, quantity, uom, date, currency, **kwargs):
        """Voorlopige prijs voor wat niet vrij op voorraad ligt (de factuur volgt later de partij)."""
        return self._afs_rest_rule(product, quantity, uom, date)._compute_price(product, quantity, uom, date, currency,
                                                                                **kwargs)

    def _afs_rest_display(self, product, quantity, uom, date, currency, **kwargs):
        """Met Kortingen aan: (prijs zonder korting, prijs) voor wat niet uit een partij komt, zoals Odoo het toont."""
        rule = self._afs_rest_rule(product, quantity, uom, date)
        price = rule._compute_price(product, quantity, uom, date, currency, **kwargs)
        if not rule._show_discount():
            return price, price
        base = rule._compute_price_before_discount(product=product, quantity=quantity, uom=uom, date=date,
                                                   currency=currency)
        return max(base, price), price

    def _afs_convert_cost(self, product, cost, uom, date, currency):
        """Kostprijs (per eenheid van het product) naar `uom` en `currency`."""
        price = _per_uom(product, cost, uom)
        if product.cost_currency_id and currency and product.cost_currency_id != currency:
            price = product.cost_currency_id._convert(price, currency, self.env.company, date, round=False)
        return price

    def _compute_price(self, product, quantity, uom, date, currency=None, **kwargs):
        context = self.env.context
        if not context.get('afs_lot_skip') and 'afs_lot_cost' not in context and self._afs_lot_mode(product):
            currency = currency or self.currency_id or self.env.company.currency_id
            # orderregel: het gemiddelde voor het bestelde aantal; elders (shop): de prijs van het volgende stuk
            qty = quantity if product.env.context.get('afs_order_line') else 1.0
            return self._afs_fifo_price(product, qty, uom, date, currency, **kwargs)
        return super()._compute_price(product, quantity, uom, date, currency=currency, **kwargs)

    def _compute_base_price(self, product, quantity, uom, date, currency, **kwargs):
        lot_cost = self.env.context.get('afs_lot_cost')
        if lot_cost is not None and (self.base or 'list_price') == 'standard_price':
            return self._afs_convert_cost(product, lot_cost, uom, date, currency)
        return super()._compute_base_price(product, quantity, uom, date, currency, **kwargs)
