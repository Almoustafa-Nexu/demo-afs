from odoo import fields, models


class StockWarehouse(models.Model):
    _inherit = 'stock.warehouse'

    afs_partner_ids = fields.Many2many(
        'res.partner', 'afs_warehouse_partner_rel', 'warehouse_id', 'partner_id',
        string="Enkel voor deze apotheken",
        domain=[('is_company', '=', True)],
        help="Leeg: elke apotheek mag bestellen wat vanuit dit magazijn geleverd wordt.\n"
             "Ingevuld: alleen deze apotheken zien die producten in de webshop en kunnen ze bestellen.",
    )

    def _afs_closed_for(self, partner):
        """Magazijnen die niet openstaan voor deze klant (of voor de apotheek waar hij bij hoort)."""
        pharmacy = partner.commercial_partner_id
        return self.sudo().search([('afs_partner_ids', '!=', False)]).filtered(
            lambda warehouse: pharmacy not in warehouse.afs_partner_ids
        )
