from odoo import fields, models


class ResCompany(models.Model):
    _inherit = 'res.company'

    afs_purchase_vendor_only = fields.Boolean(
        string="Inkoop per leverancier",
        default=True,
        help="De leverancier komt van het gekozen product (aanpasbaar), en Leveren aan "
             "volgt het magazijn waaruit de producten naar de apotheken gaan.",
    )
