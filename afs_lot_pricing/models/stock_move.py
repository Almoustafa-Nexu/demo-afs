from collections import defaultdict

from odoo import models
from odoo.tools import float_compare


class StockMove(models.Model):
    _inherit = 'stock.move'

    def _afs_auto_lot_name(self):
        self.ensure_one()
        return self.purchase_line_id._afs_lot_name() if self.purchase_line_id else False

    def _afs_preferred_lot(self):
        """De partij van de orderregel: de partij waarvan de apotheek de prijs op haar order heeft. Een partij op
        voorraad, of de partij die binnenkwam met de voorverkoopregel. Leeg: geen voorkeur (de gewone volgorde)."""
        self.ensure_one()
        line = self.sale_line_id or self.move_dest_ids.sale_line_id[:1]
        if not line or self.product_id.tracking != 'lot':
            return self.env['stock.lot']
        if line.afs_lot_id:
            return line.afs_lot_id
        if line.afs_presale_line_id:
            return self.env['stock.move.line'].sudo().search([
                ('move_id.purchase_line_id', '=', line.afs_presale_line_id.id),
                ('lot_id', '!=', False), ('state', '=', 'done'),
            ], order='id', limit=1).lot_id
        return self.env['stock.lot']

    def _update_reserved_quantity(self, need, location_id, lot_id=None, package_id=None, owner_id=None, strict=True):
        """Levering aan een apotheek: eerst de stuks uit de partij van haar orderregel, zodat de factuur dezelfde
        prijs heeft als haar order. Komen meer partijen tegelijk binnen (stappen in één voorverkoop), dan krijgt
        zo elke bestelling haar eigen partij, ook als een latere bestelling eerst gereserveerd wordt. Is die partij
        op (bv. 29 ontvangen in plaats van 30), dan de rest in de gewone volgorde."""
        preferred = self._afs_preferred_lot() if not (lot_id or strict) else self.env['stock.lot']
        if not preferred:
            return super()._update_reserved_quantity(need, location_id, lot_id=lot_id, package_id=package_id,
                                                     owner_id=owner_id, strict=strict)
        taken = super()._update_reserved_quantity(need, location_id, lot_id=preferred, package_id=package_id,
                                                  owner_id=owner_id, strict=False)
        digits = self.env['decimal.precision'].precision_get('Product Unit')
        if float_compare(need - taken, 0.0, precision_digits=digits) > 0:
            taken += super()._update_reserved_quantity(need - taken, location_id, package_id=package_id,
                                                       owner_id=owner_id, strict=False)
        return taken

    def _prepare_move_line_vals(self, quantity=None, reserved_quant=None):
        """Bij een ontvangst van de leverancier staat de partijnaam al ingevuld (aan te passen in Details)."""
        vals = super()._prepare_move_line_vals(quantity=quantity, reserved_quant=reserved_quant)
        if (not vals.get('lot_id') and not vals.get('lot_name') and self.product_id.tracking == 'lot'
                and self.location_id.usage == 'supplier' and self.picking_type_id.use_create_lots):
            if name := self._afs_auto_lot_name():
                vals['lot_name'] = name
        return vals

    def _prepare_procurement_qty(self):
        """Voorverkoop: wat nog vrij is op een inkoopofferte in voorverkoop, telt als voorraad. Een bevestigde
        bestelling die erin past, maakt dus geen nieuwe inkoopofferte aan; alleen wat erbuiten valt."""
        consumed = self.env.context.get('consumed_from_stock_dict')
        if consumed is None:
            consumed = defaultdict(float)
        for move in self:
            warehouse = move.location_id.warehouse_id
            if (move.rule_id.procure_method != 'mts_else_mto' or not warehouse
                    or not move.location_id._child_of(warehouse.lot_stock_id)):
                continue
            key = (move.location_id, move.product_id.id)
            done_key = ('afs_presale',) + key  # per bevestiging maar een keer
            if done_key in consumed:
                continue
            consumed[done_key] = 1.0
            presale = move.product_id.product_tmpl_id._afs_presale(warehouse, quoted=0.0)
            free = sum(free for line, _todo, _ordered, free, _cost in presale if line.product_id == move.product_id)
            if free > 0:
                consumed[key] = consumed.get(key, 0.0) - free
        return super(StockMove, self.with_context(consumed_from_stock_dict=consumed))._prepare_procurement_qty()
