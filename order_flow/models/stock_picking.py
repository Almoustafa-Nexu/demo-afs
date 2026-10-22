from odoo import models


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    def _action_done(self):
        res = super()._action_done()
        self._create_draft_invoices()
        return res

    def _create_draft_invoices(self):
        """Na een levering of ontvangst staat de conceptfactuur klaar, met wat echt geleverd of ontvangen is.
        Een retour geeft een concept-creditfactuur. Als sudo: ook een magazijngebruiker zonder rechten op
        Verkoop, Inkoop of Facturatie kan zo bevestigen."""
        pickings = self.sudo()
        for order in pickings.sale_id.filtered(lambda o: o.invoice_status == 'to invoice'):
            order.with_context(tracking_disable=True, raise_if_nothing_to_invoice=False)._create_invoices(final=True)
        for order in pickings.purchase_id.filtered(lambda o: o.invoice_status == 'to invoice'):
            order.with_context(tracking_disable=True).action_create_invoice()
