from collections import defaultdict

from odoo import api, fields, models

from .product_pricelist import _per_uom, source_label


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    def _create_invoices(self, grouped=False, final=False, date=None):
        moves = super()._create_invoices(grouped=grouped, final=final, date=date)
        moves._afs_split_lot_lines()
        return moves

    def action_quotation_sent(self):
        self._afs_split_per_lot(placing=True)
        return super().action_quotation_sent()

    def action_confirm(self):
        self._afs_split_per_lot(placing=True)
        return super().action_confirm()

    def action_update_prices(self):
        self._afs_split_per_lot()
        return super().action_update_prices()

    def _get_free_qty(self, product):
        """Winkelwagen: wat nog te koop is in de voorverkoop, telt mee als beschikbaar."""
        qty = super()._get_free_qty(product)
        template = product.product_tmpl_id
        warehouse = template._afs_website_warehouse(self.website_id) if self.website_id else self.warehouse_id
        return qty + template._afs_presale_free_qty(warehouse, product)

    def _afs_summary_rows(self, tax_included=False):
        """Overzicht in de webshop: (regel, partij of False) per rij; een regel met prijs per partij krijgt een rij
        per partij."""
        rows = []
        for line in self.website_order_line:
            rows += [(line, part) for part in line._afs_lot_breakdown(tax_included)] or [(line, False)]
        return rows

    def _afs_split_per_lot(self, products=None, placing=False):
        """Een orderregel per partij (de oudste eerst), met de echte prijs van die partij, zoals op de factuur.

        De winkelwagen blijft een regel per product, met de verdeling eronder. Bij het afrekenen of bevestigen
        (`placing`) wordt ze verdeeld; wat al verdeeld is, blijft dan zoals het is.
        """
        for order in self:
            cart = bool(order.website_id) and order.state == 'draft'
            if order.state not in ('draft', 'sent') or (cart and not placing):
                continue
            lines = order.order_line.filtered(
                lambda l: l._afs_can_split() and (products is None or l.product_id in products))
            for product in lines.product_id:
                group = lines.filtered(lambda l: l.product_id == product)
                if not (placing and all(group.mapped('afs_split'))):
                    order._afs_split_product(group, all_quoted=cart)

    def _afs_split_product(self, lines, all_quoted=False):
        """Verdeel de regels van een product opnieuw over de partijen: bestaande regels worden hergebruikt,
        wat te veel is, verdwijnt. Bestellingen die eerder binnenkwamen, krijgen de oudste stuks; bij het
        afrekenen (`all_quoted`) tellen alle bestellingen mee, zoals in de winkelwagen."""
        self.ensure_one()
        lines = lines.sorted(lambda l: (l.sequence, l.id))
        first, product = lines[0], lines[0].product_id
        total = sum(lines.mapped('product_uom_qty'))
        if product.uom_id.compare(total, 0) <= 0:
            return  # aantal 0 (of minder): de regel blijft zoals AFS ze zette
        date = first._get_order_date()
        rule = self.env['product.pricelist.item'].browse(
            self.pricelist_id._get_product_rule(product, quantity=total, uom=product.uom_id, date=date))
        if not rule._afs_lot_mode(product):
            return
        context = dict(first._get_product_price_context(), afs_sale_order_id=self.id)
        context.pop('afs_sale_line_id', None)
        if not all_quoted:
            context['afs_quoted_before'] = (self.date_order, self.id)
        parts = rule._afs_lot_parts(product.with_context(**context), total, date,
                                    self.currency_id or self.company_id.currency_id, show_discount=False)
        split = len(parts) > 1 or bool(parts[0]['source'])

        def line_vals(part):
            source = part['source']
            return {
                'product_uom_qty': part['qty'],
                'afs_split': split,
                'afs_lot_id': source.id if source and source._name == 'stock.lot' else False,
                'afs_presale_line_id': source.id if source and source._name == 'purchase.order.line' else False,
            }

        plan = [line_vals(part) for part in parts]
        current = [(l.product_uom_qty, l.afs_split, l.afs_lot_id.id, l.afs_presale_line_id.id) for l in lines]
        if current == [tuple(vals.values()) for vals in plan]:
            return  # niets veranderd
        keep = self.env['sale.order.line']
        for index, vals in enumerate(plan):
            if index < len(lines):
                line = lines[index]
                line.with_context(afs_no_split=True).write(vals)
            else:
                line = first.with_context(afs_no_split=True).copy(dict(vals, order_id=self.id))
            keep |= line
        (lines - keep).with_context(afs_no_split=True).unlink()
        keep._afs_reprice()


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    afs_split = fields.Boolean(string="Regel per partij", copy=False)
    afs_lot_id = fields.Many2one('stock.lot', string="Partij", copy=False, index='btree_not_null')
    afs_presale_line_id = fields.Many2one('purchase.order.line', string="Voorverkoop", copy=False,
                                          index='btree_not_null')

    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        if not self.env.context.get('afs_no_split'):
            lines.order_id._afs_split_per_lot(lines.product_id)
        return lines

    def write(self, vals):
        if self.env.context.get('afs_no_split') or not {'product_uom_qty', 'product_id', 'product_uom_id'} & set(vals):
            return super().write(vals)
        products = self.product_id
        res = super().write(vals)
        self.order_id._afs_split_per_lot(products | self.product_id)
        return res

    def unlink(self):
        if self.env.context.get('afs_no_split'):
            return super().unlink()
        groups = {(line.order_id, line.product_id) for line in self if line.afs_split}
        res = super().unlink()
        for order, product in groups:
            if order.exists():
                order._afs_split_per_lot(product)
        return res

    def _afs_waiting_qty(self):
        """Stuks van deze regel die nog naar de apotheek moeten (open leveringen), in de eenheid van het product."""
        self.ensure_one()
        moves = self.move_ids.filtered(
            lambda m: m.state not in ('done', 'cancel') and m.location_dest_id.usage == 'customer')
        return sum(moves.mapped('product_qty'))

    def _afs_claimed_qty(self):
        """Stuks van deze regel die nog met haar partij of voorverkoop rekenen, in de eenheid van het product: bij een
        bevestigde bestelling wat nog geleverd moet worden, bij een offerte het aantal."""
        self.ensure_one()
        if self.order_id.state == 'sale':
            return self._afs_waiting_qty()
        if self.order_id.state in ('draft', 'sent') and self.product_uom_id:
            return self.product_uom_id._compute_quantity(self.product_uom_qty, self.product_id.uom_id)
        return 0.0

    def _afs_can_split(self):
        """Mag deze regel per partij verdeeld worden? Prijs per partij, eenheid van het product, prijs niet
        met de hand aangepast."""
        self.ensure_one()
        return bool(self.product_id and not self.display_type and not self.is_downpayment and not self.combo_item_id
                    and self.product_uom_id == self.product_id.uom_id and not self._afs_has_manual_price()
                    and self.pricelist_item_id._afs_lot_mode(self.product_id))

    def _afs_is_split(self):
        return self.afs_split and self.pricelist_item_id._afs_lot_mode(self.product_id)

    def _afs_reprice(self):
        """Na het verdelen: prijsregel, prijs, korting en omschrijving opnieuw."""
        self.invalidate_recordset(['pricelist_item_id'])
        self.with_context(force_price_recomputation=True)._compute_price_unit()
        self._compute_discount()
        for line in self:
            line.name = line._afs_line_name()

    def _afs_line_name(self):
        name = self.with_context(lang=self.order_id._get_lang())._get_sale_order_line_multiline_description_sale()
        return '%s\n%s' % (name, source_label(self.afs_lot_id or self.afs_presale_line_id)) if self.afs_split else name

    def _get_product_price_context(self):
        """Voor de prijs per partij: het magazijn van de order en de regel zelf (wat ze al reserveerde, is vrij
        voor haar)."""
        res = super()._get_product_price_context()
        res['afs_order_line'] = True
        if self.order_id.warehouse_id:
            res['afs_warehouse_id'] = self.order_id.warehouse_id.id
        if isinstance(self._origin.id, int) and self._origin.id:
            res['afs_sale_line_id'] = self._origin.id
        return res

    def _get_pricelist_kwargs(self):
        """Een verdeelde regel kiest haar prijsregel (bv. een staffel) op het totaal van het product."""
        res = super()._get_pricelist_kwargs()
        if self.afs_split:
            group = self.order_id.order_line.filtered(lambda l: l.afs_split and l.product_id == self.product_id)
            res['quantity'] = sum(group.mapped('product_uom_qty')) or res['quantity']
        return res

    def _get_pricelist_price(self):
        if self._afs_is_split():
            return self._afs_split_price(show_discount=False)[0]
        return super()._get_pricelist_price()

    def _afs_split_price(self, show_discount):
        """Verdeelde regel: (prijs, korting %) van haar partij, voorverkoopregel of, zonder, de voorlopige prijs."""
        kwargs = self._get_pricelist_kwargs()
        currency = kwargs['currency'] or self.company_id.currency_id or self.env.company.currency_id
        source = (self.afs_lot_id or self.afs_presale_line_id).sudo()
        if source._name == 'stock.lot':
            cost = source.with_company(self.company_id).standard_price
        else:
            cost = source._get_stock_move_price_unit() if source else 0.0
        return self.pricelist_item_id._afs_part_price(self.product_id, source, cost, self.product_uom_qty,
                                                      kwargs['quantity'], kwargs['date'], currency, show_discount)

    def _afs_parts(self, show_discount):
        """Verdeling over de partijen van een regel die (nog) niet verdeeld is, zoals in de winkelwagen."""
        kwargs = self._get_pricelist_kwargs()
        currency = kwargs['currency'] or self.company_id.currency_id or self.env.company.currency_id
        qty = self.product_uom_id._compute_quantity(self.product_uom_qty or 1.0, self.product_id.uom_id)
        return self.pricelist_item_id._afs_lot_parts(self.product_id.with_context(**self._get_product_price_context()),
                                                     qty, kwargs['date'], currency, show_discount)

    # Korting van de partij zichtbaar (Verkoop > Configuratie > Instellingen > Kortingen)

    def _afs_show_lot_discount(self):
        """Kortingen staat aan en de prijs van deze regel gaat per partij."""
        self.ensure_one()
        rule = self.pricelist_item_id
        return bool(self.product_id and not self.display_type and not self.combo_item_id and rule
                    and rule._is_discount_feature_enabled() and rule._afs_lot_mode(self.product_id))

    def _afs_shown_line(self):
        """(prijs, korting %) met Kortingen aan. Een niet verdeelde regel uit een partij toont die partij; uit meer
        partijen het gemiddelde zonder korting, zodat het bedrag klopt met de verdeling eronder."""
        self.ensure_one()
        if self._afs_is_split():
            return self._afs_split_price(show_discount=True)
        parts = self._afs_parts(show_discount=True)
        if len(parts) == 1:
            price, discount = parts[0]['price'], parts[0]['discount']
        else:
            price, discount = sum(p['amount'] for p in parts) / sum(p['qty'] for p in parts), 0.0
        return _per_uom(self.product_id, price, self.product_uom_id), discount

    def _get_display_price_ignore_combo(self):
        if self._afs_show_lot_discount():
            return self._afs_shown_line()[0]
        return super()._get_display_price_ignore_combo()

    @api.depends('product_id', 'product_uom_id', 'product_uom_qty')
    def _compute_discount(self):
        super()._compute_discount()
        for line in self:
            if line.order_id.pricelist_id and line.product_uom_id and line._afs_show_lot_discount():
                line.discount = line.with_company(line.company_id)._afs_shown_line()[1]

    def _afs_lot_breakdown(self, tax_included=False):
        """Voor de webshop: per partij het aantal, de prijs, de korting, het bedrag en een korte noot voor de
        apotheek (voorverkoop, nog niet op voorraad)."""
        self.ensure_one()
        rule = self.pricelist_item_id
        if self.product_uom_id != self.product_id.uom_id or not rule._afs_lot_mode(self.product_id):
            return []
        if self._afs_is_split():
            parts = [{'source': self.afs_lot_id or self.afs_presale_line_id, 'qty': self.product_uom_qty,
                      'price': self.price_unit, 'discount': self.discount, 'amount': self.price_subtotal}]
        else:
            parts = self._afs_parts(rule._is_discount_feature_enabled())
            if len(parts) == 1 and not parts[0]['source']:
                return []  # geen partijen: gewoon de prijs van de regel
        display = 'total_included' if tax_included else 'total_excluded'
        for part in parts:
            source = part['source']
            part['note'] = ('voorverkoop' if source._name == 'purchase.order.line' else '') if source else \
                'nog niet op voorraad'
            for key in ('price', 'amount'):
                part[key] = self.tax_ids.compute_all(part[key], self.currency_id, 1, self.product_id,
                                                     self.order_partner_id)[display]
        return parts

    def _afs_has_manual_price(self):
        """Iemand paste de prijs met de hand aan: die prijs blijft dan gelden."""
        self.ensure_one()
        currency = self.currency_id or self.company_id.currency_id
        return bool(self.technical_price_unit) and \
            currency.compare_amounts(self.technical_price_unit, self.price_unit) != 0

    def _afs_net_delivered_per_lot(self):
        """Netto geleverd per partij (leveringen min retours), in de eenheid van het product.

        :return: ({partij: aantal}, partijen in de volgorde van levering)
        """
        self.ensure_one()
        qty, lots = defaultdict(float), []
        move_lines = self.move_ids.filtered(lambda m: m.state == 'done').move_line_ids
        for ml in move_lines.sorted(lambda ml: (ml.date or ml.create_date, ml.id)):
            to_customer, from_customer = ml.location_dest_id.usage == 'customer', ml.location_id.usage == 'customer'
            if not ml.lot_id or to_customer == from_customer:
                continue
            sign = 1 if to_customer else -1  # levering of retour
            qty[ml.lot_id] += sign * ml.product_uom_id._compute_quantity(ml.quantity, ml.product_id.uom_id)
            if ml.lot_id not in lots:
                lots.append(ml.lot_id)
        return qty, lots
