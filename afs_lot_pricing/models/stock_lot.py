from odoo import models


class StockLot(models.Model):
    _inherit = 'stock.lot'

    def _afs_purchase_line(self):
        """De inkoopregel waarmee deze partij binnenkwam (de eerste ontvangst), of leeg."""
        self.ensure_one()
        move_line = self.env['stock.move.line'].sudo().search([
            ('lot_id', '=', self.id), ('state', '=', 'done'), ('move_id.purchase_line_id', '!=', False),
        ], order='date, id', limit=1)
        return move_line.move_id.purchase_line_id
