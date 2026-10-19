from odoo import fields, models


class ResCompany(models.Model):
    _inherit = 'res.company'

    afs_purchase_vendor_only = fields.Boolean(
        string="Inkoop per leverancier",
        default=True,
        help="Op een inkoop kies je alleen producten met deze leverancier (product, tabblad Inkoop), en Leveren aan "
             "volgt het magazijn waaruit de producten naar de apotheken gaan.",
    )
