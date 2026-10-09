from collections import defaultdict

from odoo import Command, fields, models


class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'

    afs_lot_id = fields.Many2one('stock.lot', string="Partij", copy=False, index='btree_not_null')


class AccountMove(models.Model):
    _inherit = 'account.move'

    def _afs_split_lot_lines(self):
        """Zet op een conceptfactuur (of creditfactuur) een regel per geleverde partij, aan de prijs van die partij.

        Alleen voor producten met "Korting per partij doorrekenen" en "Waardering per partij", en alleen als
        de prijs van de orderregel uit een prijslijst met hetzelfde vinkje komt (aan voor de apotheken, uit
        voor het personeel), via een regel op kostprijs of een actie. Met de hand aangepaste prijzen blijven.
        Welke partijen: wat netto geleverd is en nog niet per partij gefactureerd werd, oudste levering eerst.
        """
        for move in self.filtered(lambda m: m.state == 'draft' and m.move_type in ('out_invoice', 'out_refund')):
            lines = move.invoice_line_ids.filtered(
                lambda l: l.display_type == 'product' and l.product_id and l.quantity > 0 and not l.afs_lot_id
                and l.sale_line_ids)
            for line in lines:
                sale_line = line.sale_line_ids[:1]
                rule = sale_line.pricelist_item_id
                if rule._afs_lot_mode(line.product_id) and not sale_line._afs_has_manual_price():
                    move._afs_split_line(line, rule)

    def _afs_split_line(self, line, rule):
        """Verdeel een factuurregel over de partijen die nog te factureren (of te crediteren) zijn.

        De regel zelf wordt die van de eerste partij; de andere partijen krijgen een eigen regel. Staat er meer
        op de factuur dan er per partij openstaat, dan blijft dat deel een regel aan de prijs van de order.
        """
        self.ensure_one()
        refund = self.move_type == 'out_refund'
        product = line.product_id
        sale_line = line.sale_line_ids[:1]
        delivered, lots = sale_line._afs_net_delivered_per_lot()
        invoiced, invoiced_price = self._afs_invoiced_per_lot(sale_line, product)

        to_split = line.product_uom_id._compute_quantity(line.quantity, product.uom_id)
        parts = []
        for lot in lots:
            open_qty = invoiced[lot] - delivered[lot] if refund else delivered[lot] - invoiced[lot]
            if open_qty > 0 and to_split > 0:
                take = min(open_qty, to_split)
                parts.append((lot, take))
                to_split -= take
        if not parts:
            return

        uom = line.product_uom_id
        name = line.name or product.display_name
        order_date = sale_line._get_order_date()  # de prijs die gold bij het bestellen (ook een actie die intussen afliep)

        def lot_vals(lot, qty):
            if refund and lot in invoiced_price:
                price = invoiced_price[lot]  # creditfactuur: dezelfde prijs als waaraan die partij gefactureerd werd
            else:
                cost = lot.with_company(self.company_id).standard_price
                price = rule._afs_lot_unit_price(product, cost, uom, order_date, self.currency_id) if cost else None
                if price is None:
                    price = line.price_unit
            return {
                'quantity': product.uom_id._compute_quantity(qty, uom),
                'price_unit': price,
                'name': '%s\nPartij %s' % (name, lot.name),
                'afs_lot_id': lot.id,
            }

        common = {
            'product_id': product.id,
            'product_uom_id': uom.id,
            'tax_ids': [Command.set(line.tax_ids.ids)],
            'sale_line_ids': [Command.set(line.sale_line_ids.ids)],
            'account_id': line.account_id.id,
            'analytic_distribution': line.analytic_distribution,
            'sequence': line.sequence,
            'discount': 0.0,
        }
        (first_lot, first_qty), other_parts = parts[0], parts[1:]
        first_vals = lot_vals(first_lot, first_qty)
        new_lines = []
        if to_split > 0:
            new_lines.append(Command.create(dict(
                common, quantity=product.uom_id._compute_quantity(to_split, uom),
                price_unit=line.price_unit, discount=line.discount, name=name)))
        line.write(dict(first_vals, discount=0.0))
        new_lines += [Command.create(dict(common, **lot_vals(lot, qty))) for lot, qty in other_parts]
        if new_lines:
            self.write({'invoice_line_ids': new_lines})

    def _afs_invoiced_per_lot(self, sale_line, product):
        """Wat er van deze orderregel al per partij gefactureerd is, buiten deze factuur.

        :return: ({partij: aantal, facturen min creditfacturen, in de eenheid van het product},
                  {partij: gemiddelde prijs per stuk op de facturen})
        """
        qty = defaultdict(float)
        amount = defaultdict(float)
        count = defaultdict(float)
        for other in sale_line.invoice_lines:
            if other.move_id == self or other.move_id.state == 'cancel' or not other.afs_lot_id:
                continue
            lot = other.afs_lot_id
            lot_qty = other.product_uom_id._compute_quantity(other.quantity, product.uom_id)
            if other.move_id.move_type == 'out_refund':
                qty[lot] -= lot_qty
            else:
                qty[lot] += lot_qty
                amount[lot] += other.price_unit * other.quantity
                count[lot] += other.quantity
        return qty, {lot: amount[lot] / count[lot] for lot in count if count[lot]}
