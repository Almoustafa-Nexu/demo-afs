from odoo import models


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    def _action_done(self):
        res = super()._action_done()
        self._create_draft_invoices()
        return res

    def _create_draft_invoices(self):
        """Na een levering of ontvangst meteen de conceptfactuur klaarzetten.

        Op de factuur komt wat echt geleverd of ontvangen is (30 besteld, 29 ontvangen:
        29 gefactureerd). Een retour geeft een concept-creditfactuur. AFS kijkt na en bevestigt.

        Loopt als systeem (sudo): zo kan ook een magazijngebruiker van een apotheek, zonder
        rechten op Verkoop, Inkoop of Facturatie, een levering of ontvangst bevestigen.
        """
        pickings = self.sudo()
        # Apotheek: factuur, of creditfactuur na een retour
        for order in pickings.sale_id.filtered(lambda o: o.invoice_status == 'to invoice'):
            order.with_context(
                tracking_disable=True, raise_if_nothing_to_invoice=False,
            )._create_invoices(final=True)
        # Leverancier: leveranciersfactuur, of creditfactuur na een retour
        for order in pickings.purchase_id.filtered(lambda o: o.invoice_status == 'to invoice'):
            order.with_context(tracking_disable=True).action_create_invoice()
