from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    afs_purchase_vendor_only = fields.Boolean(related='company_id.afs_purchase_vendor_only', readonly=False)
