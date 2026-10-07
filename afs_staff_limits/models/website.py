from odoo import fields, models


class Website(models.Model):
    _inherit = 'website'

    afs_staff_shop = fields.Boolean(
        string="Personeelsshop",
        help="Aangevinkt: in deze webshop gelden de limieten per personeelslid "
             "(veld Max. per personeelslid per jaar op het product).",
    )
