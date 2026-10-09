from odoo import models


class PurchaseOrderLine(models.Model):
    _inherit = 'purchase.order.line'

    def write(self, vals):
        """Pas je de korting aan nadat de inkoop bevestigd is, dan volgt de voorgestelde partijnaam
        van de ontvangst mee (bv. STOCK-P00045 wordt LOT-P00045-20PROC). Een naam die je zelf typte, blijft."""
        if 'discount' not in vals:
            return super().write(vals)
        open_moves = self.move_ids.filtered(lambda m: m.state not in ('done', 'cancel'))
        old_names = {move: move._afs_auto_lot_name() for move in open_moves}
        res = super().write(vals)
        for move, old_name in old_names.items():
            new_name = move._afs_auto_lot_name()
            if old_name and new_name and new_name != old_name:
                proposed = move.move_line_ids.filtered(lambda ml: ml.lot_name == old_name and not ml.lot_id)
                proposed.write({'lot_name': new_name})
        return res
