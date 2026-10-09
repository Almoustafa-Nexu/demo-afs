from odoo import fields, models


def _template(product):
    """product.product of product.template: geef het product.template."""
    return product.product_tmpl_id if product._name == 'product.product' else product


class ProductPricelist(models.Model):
    _inherit = 'product.pricelist'

    afs_lot_pricing = fields.Boolean(
        string="Korting per partij doorrekenen",
        help="Met deze prijslijst betaal je de prijs van de partij die je krijgt, voor producten met het vinkje "
             "Korting per partij doorrekenen: in de shop, in de winkelwagen en op de factuur. "
             "Aan voor de apotheken, uit voor het personeel.",
    )

    def _afs_normal_rule(self, product, quantity, date, on_cost=False):
        """De regel zonder datums (geen actie) die voor dit product geldt: de normale prijs, zoals na de actie
        (bv. "Partijprijs: 0 % korting op verkoopprijs"). Leeg = geen regel, dus de verkoopprijs.

        :param quantity: aantal in de eenheid van het product
        :param on_cost: alleen een regel op kostprijs (bv. "Alle producten: 0 % opslag op productkosten")
        """
        self.ensure_one()
        for rule in self._get_applicable_rules(product, date):
            if (not (rule.date_start or rule.date_end) and (not on_cost or rule._afs_on_cost())
                    and rule._is_applicable_for(product, quantity)):
                return rule
        return self.env['product.pricelist.item']


class ProductPricelistItem(models.Model):
    _inherit = 'product.pricelist.item'

    def _afs_on_cost(self):
        """Regel gebaseerd op de kostprijs (Formule of Percentage)."""
        return self.base == 'standard_price' and self.compute_price in ('formula', 'percentage')

    def _afs_lot_mode(self, product):
        """Hoe deze regel de korting per partij toepast:

        * 'kost':  regel op kostprijs (zoals 0 % opslag op productkosten): de kostprijs van de partij telt;
        * 'actie': regel met begin- of einddatum (een actie): de actieprijs is een maximum, een partij
                   die goedkoper is, blijft goedkoper;
        * False:   geen korting per partij (andere prijslijst, ander product, of een vaste prijs zonder datums).
        """
        if len(self) != 1 or not self.pricelist_id.afs_lot_pricing:
            return False
        if not _template(product)._afs_uses_lot_pricing():
            return False
        if self._afs_on_cost():
            return 'kost'
        if self.date_start or self.date_end:
            return 'actie'
        return False

    def _afs_lot_unit_price(self, product, lot_cost, uom, date, currency):
        """Prijs van een stuk uit een partij met kostprijs `lot_cost` (per eenheid van het product,
        in de munt van de kostprijs), volgens deze regel. None als de regel geen korting per partij doet."""
        mode = self._afs_lot_mode(product)
        if mode == 'kost':
            return self.with_context(afs_lot_cost=lot_cost)._compute_price(product, 1.0, uom, date, currency)
        if mode == 'actie':
            action_price = self.with_context(afs_lot_skip=True)._compute_price(product, 1.0, uom, date, currency)
            cost_rule = self.pricelist_id._afs_normal_rule(product, 1.0, date, on_cost=True)
            if cost_rule:
                lot_price = cost_rule.with_context(afs_lot_cost=lot_cost)._compute_price(product, 1.0, uom, date, currency)
            else:
                lot_price = self._afs_convert_cost(product, lot_cost, uom, date, currency)
            return min(action_price, lot_price)
        return None

    def _afs_convert_cost(self, product, cost, uom, date, currency):
        """Kostprijs (per eenheid van het product) omrekenen naar de eenheid `uom` en de munt `currency`."""
        price = product.uom_id._compute_price(cost, uom) if uom and uom != product.uom_id else cost
        cost_currency = product.cost_currency_id
        if cost_currency and currency and cost_currency != currency:
            price = cost_currency._convert(price, currency, self.env.company, date, round=False)
        return price

    def _afs_rest_price(self, product, quantity, uom, date, currency, **kwargs):
        """Prijs per stuk voor wat nog niet op voorraad ligt (meer besteld dan er vrij is, of geen voorraad).

        * Actie op kostprijs (regel op kostprijs met datums): de normale prijs, zoals na de actie.
        * Anders de prijs van de regel zelf: bij een actie met korting of vaste prijs de actieprijs,
          bij een regel op kostprijs zonder datums de kostprijs van het product.

        Het blijft een voorlopige prijs: de factuur volgt later de partij die geleverd wordt.
        """
        rule = self
        if self._afs_lot_mode(product) == 'kost' and (self.date_start or self.date_end):
            uom = uom or product.uom_id
            qty = quantity if uom == product.uom_id else \
                uom._compute_quantity(quantity, product.uom_id, raise_if_failure=False)
            rule = self.pricelist_id._afs_normal_rule(product, qty, date)
        return rule.with_context(afs_lot_skip=True)._compute_price(product, quantity, uom, date, currency, **kwargs)

    def _afs_fifo_price(self, product, quantity, uom, date, currency, **kwargs):
        """Gemiddelde prijs per stuk voor `quantity`, de oudste partij eerst (vrije voorraad).
        Wat er niet vrij ligt, telt aan _afs_rest_price."""
        rows = _template(product)._afs_lot_rows()
        if not rows:
            return self._afs_rest_price(product, quantity, uom or product.uom_id, date, currency, **kwargs)
        product_uom = product.uom_id
        uom = uom or product_uom
        qty = quantity or 1.0
        if uom != product_uom:
            qty = uom._compute_quantity(qty, product_uom, raise_if_failure=False)
        if qty <= 0:
            qty = 1.0
        rest, total = qty, 0.0
        for _lot, available, cost in rows:
            if rest <= 0:
                break
            take = min(available, rest)
            total += take * self._afs_lot_unit_price(product, cost, product_uom, date, currency)
            rest -= take
        if rest > 0:
            # Meer dan er vrij op voorraad ligt: de rest voorlopig aan de normale prijs
            total += rest * self._afs_rest_price(product, qty, product_uom, date, currency, **kwargs)
        unit_price = total / qty
        return product_uom._compute_price(unit_price, uom) if uom != product_uom else unit_price

    def _compute_price(self, product, quantity, uom, date, currency=None, **kwargs):
        context = self.env.context
        if not context.get('afs_lot_skip') and 'afs_lot_cost' not in context and self._afs_lot_mode(product):
            currency = currency or self.currency_id or self.env.company.currency_id
            # In een orderregel (winkelwagen, verkooporder): het gemiddelde voor het bestelde aantal, zodat de
            # order evenveel kost als de factuur per partij. Elders (productpagina, shop): de prijs van het
            # volgende stuk, ook als je het aantal verandert.
            qty = quantity if product.env.context.get('afs_order_line') else 1.0
            return self._afs_fifo_price(product, qty, uom, date, currency, **kwargs)
        return super()._compute_price(product, quantity, uom, date, currency=currency, **kwargs)

    def _compute_base_price(self, product, quantity, uom, date, currency, **kwargs):
        lot_cost = self.env.context.get('afs_lot_cost')
        if lot_cost is not None and (self.base or 'list_price') == 'standard_price':
            return self._afs_convert_cost(product, lot_cost, uom, date, currency)
        return super()._compute_base_price(product, quantity, uom, date, currency, **kwargs)
