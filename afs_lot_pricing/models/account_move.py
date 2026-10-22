from collections import defaultdict

from odoo import Command, fields, models

from .product_pricelist import best_discount, strip_source_label


class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'

    afs_lot_id = fields.Many2one('stock.lot', string="Partij", copy=False, index='btree_not_null')


class AccountMove(models.Model):
    _inherit = 'account.move'

    def _afs_split_lot_lines(self):
        """Concept(credit)factuur: een regel per geleverde partij aan haar prijs, als de prijs per partij gaat en
        niet met de hand aangepast werd."""
        for move in self.filtered(lambda m: m.state == 'draft' and m.move_type in ('out_invoice', 'out_refund')):
            for line in move.invoice_line_ids.filtered(lambda l: l.display_type == 'product' and l.product_id
                                                       and l.quantity > 0 and not l.afs_lot_id and l.sale_line_ids):
                sale_line = line.sale_line_ids[:1]
                rule = sale_line.pricelist_item_id
                if rule._afs_lot_mode(line.product_id) and not sale_line._afs_has_manual_price():
                    move._afs_split_line(line, rule)

    def _afs_split_line(self, line, rule):
        """Verdeel een factuurregel over de partijen die nog te factureren (of crediteren) zijn, oudste levering
        eerst; wat er meer op staat, blijft aan de prijs van de order."""
        self.ensure_one()
        refund = self.move_type == 'out_refund'
        product, uom = line.product_id, line.product_uom_id
        sale_line = line.sale_line_ids[:1]
        delivered, lots = sale_line._afs_net_delivered_per_lot()
        invoiced, invoiced_price = self._afs_invoiced_per_lot(sale_line, product)

        to_split = uom._compute_quantity(line.quantity, product.uom_id)
        parts = []
        for lot in lots:
            open_qty = invoiced[lot] - delivered[lot] if refund else delivered[lot] - invoiced[lot]
            if open_qty > 0 and to_split > 0:
                take = min(open_qty, to_split)
                parts.append((lot, take))
                to_split -= take
        if not parts:
            return

        # de factuur noemt de geleverde partij, niet die van de orderregel
        name = strip_source_label(line.name) or product.display_name
        order_date = sale_line._get_order_date()  # de prijs van bij het bestellen, ook als de actie intussen afliep
        show_discount = rule._is_discount_feature_enabled()

        def lot_vals(lot, qty):
            line_qty = product.uom_id._compute_quantity(qty, uom)
            if refund and lot in invoiced_price:
                price, discount = invoiced_price[lot]  # dezelfde prijs en korting als op de factuur
            else:
                cost = lot.with_company(self.company_id).standard_price
                price = rule._afs_lot_unit_price(product, cost, uom, order_date, self.currency_id) if cost else None
                discount = 0.0
                if price is None:
                    price, discount = line.price_unit, line.discount
                elif show_discount:  # Kortingen aan: prijs zonder korting en de korting van de partij
                    net = price
                    price, discount = rule._afs_lot_display(product, cost, lot, net, uom, order_date, self.currency_id)
                    if discount is None:
                        discount = best_discount(self.env, price, net, line_qty, self.currency_id)
            return {'quantity': line_qty, 'price_unit': price, 'discount': discount,
                    'name': '%s\nPartij %s' % (name, lot.name), 'afs_lot_id': lot.id}

        common = {
            'product_id': product.id,
            'product_uom_id': uom.id,
            'tax_ids': [Command.set(line.tax_ids.ids)],
            'sale_line_ids': [Command.set(line.sale_line_ids.ids)],
            'account_id': line.account_id.id,
            'analytic_distribution': line.analytic_distribution,
            'sequence': line.sequence,
        }
        new_lines = []
        if to_split > 0:
            new_lines.append(Command.create(dict(common, quantity=product.uom_id._compute_quantity(to_split, uom),
                                                 price_unit=line.price_unit, discount=line.discount, name=name)))
        line.write(lot_vals(*parts[0]))
        new_lines += [Command.create(dict(common, **lot_vals(lot, qty))) for lot, qty in parts[1:]]
        if new_lines:
            self.write({'invoice_line_ids': new_lines})

    def _afs_invoiced_per_lot(self, sale_line, product):
        """Al gefactureerd per partij voor deze orderregel, buiten deze factuur.
        :return: ({partij: facturen min creditfacturen}, {partij: (gemiddelde prijs, korting %)})"""
        qty, base, net, count = (defaultdict(float) for _i in range(4))
        for other in sale_line.invoice_lines:
            lot = other.afs_lot_id
            if not lot or other.move_id == self or other.move_id.state == 'cancel':
                continue
            lot_qty = other.product_uom_id._compute_quantity(other.quantity, product.uom_id)
            if other.move_id.move_type == 'out_refund':
                qty[lot] -= lot_qty
                continue
            qty[lot] += lot_qty
            base[lot] += other.price_unit * other.quantity
            net[lot] += other.price_unit * (1 - (other.discount or 0.0) / 100) * other.quantity
            count[lot] += other.quantity
        prices = {lot: (base[lot] / count[lot], (1 - net[lot] / base[lot]) * 100)
                  for lot in count if count[lot] and base[lot]}
        return qty, prices
