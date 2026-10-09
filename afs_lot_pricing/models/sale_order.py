from collections import defaultdict

from odoo import models


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    def _create_invoices(self, grouped=False, final=False, date=None):
        moves = super()._create_invoices(grouped=grouped, final=final, date=date)
        moves._afs_split_lot_lines()
        return moves


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    def _get_product_price_context(self):
        """Voor de prijs per partij: uit welk magazijn de order levert, en welke regel het is
        (wat deze regel al reserveerde, telt voor haar als vrije voorraad)."""
        res = super()._get_product_price_context()
        res['afs_order_line'] = True
        if self.order_id.warehouse_id:
            res['afs_warehouse_id'] = self.order_id.warehouse_id.id
        if isinstance(self._origin.id, int) and self._origin.id:
            res['afs_sale_line_id'] = self._origin.id
        return res

    def _afs_has_manual_price(self):
        """True als iemand de prijs op de orderregel met de hand aanpaste: die prijs blijft dan gelden."""
        self.ensure_one()
        currency = self.currency_id or self.company_id.currency_id
        return bool(self.technical_price_unit) and currency.compare_amounts(self.technical_price_unit, self.price_unit) != 0

    def _afs_net_delivered_per_lot(self):
        """Netto geleverd per partij (leveringen min retours), in de eenheid van het product.

        :return: (dict {stock.lot: aantal}, lijst van partijen in leveringsvolgorde)
        """
        self.ensure_one()
        qty = defaultdict(float)
        lots = []
        move_lines = self.move_ids.filtered(lambda m: m.state == 'done').move_line_ids
        for ml in move_lines.sorted(lambda ml: (ml.date or ml.create_date, ml.id)):
            if not ml.lot_id:
                continue
            src, dest = ml.location_id.usage, ml.location_dest_id.usage
            if dest == 'customer' and src != 'customer':
                sign = 1  # levering
            elif src == 'customer' and dest != 'customer':
                sign = -1  # retour
            else:
                continue
            qty[ml.lot_id] += sign * ml.product_uom_id._compute_quantity(ml.quantity, ml.product_id.uom_id)
            if ml.lot_id not in lots:
                lots.append(ml.lot_id)
        return qty, lots
