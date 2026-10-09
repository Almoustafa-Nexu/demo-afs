from odoo import models


class StockMove(models.Model):
    _inherit = 'stock.move'

    def _afs_auto_lot_name(self):
        """Partijnaam voor een ontvangst uit een inkoop, zodat je ze niet zelf hoeft in te typen.

        * Korting op de inkoopregel: LOT-P00045-20PROC (inkoopnummer en korting).
        * Geen korting (gewone voorraad): STOCK-P00045.

        Dezelfde inkoopregel geeft altijd dezelfde naam: een nalevering van die inkoop komt in dezelfde
        partij, aan dezelfde prijs. Staat het product twee keer op de inkoop, dan krijgt de tweede regel -2 erbij.
        """
        self.ensure_one()
        line = self.purchase_line_id
        if not line:
            return False
        name = line.order_id.name
        same_product = line.order_id.order_line.filtered(lambda l: l.product_id == line.product_id).sorted('id')
        position = same_product.ids.index(line.id) + 1
        if position > 1:
            name = '%s-%d' % (name, position)
        if line.discount > 0.0001:
            discount = ('%g' % round(line.discount, 2)).replace('.', ',')
            return 'LOT-%s-%sPROC' % (name, discount)
        return 'STOCK-%s' % name

    def _prepare_move_line_vals(self, quantity=None, reserved_quant=None):
        """Bij een ontvangst van de leverancier staat de partijnaam al ingevuld. Je kan ze nog aanpassen
        in Details, bv. naar het lotnummer van de fabrikant."""
        vals = super()._prepare_move_line_vals(quantity=quantity, reserved_quant=reserved_quant)
        if (not vals.get('lot_id') and not vals.get('lot_name')
                and self.product_id.tracking == 'lot'
                and self.location_id.usage == 'supplier'
                and self.picking_type_id.use_create_lots):
            if name := self._afs_auto_lot_name():
                vals['lot_name'] = name
        return vals
