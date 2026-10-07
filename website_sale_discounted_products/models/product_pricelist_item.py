from odoo import api, fields, models


class ProductPricelistItem(models.Model):
    _inherit = 'product.pricelist.item'

    # Een actie aanmaken, wijzigen of verwijderen werkt meteen door in de webshop.
    # Een actie die afloopt (de tijd verstrijkt) vangt de geplande taak op.

    @api.model_create_multi
    def create(self, vals_list):
        items = super().create(vals_list)
        self.env['product.template']._sync_promo_availability()
        return items

    def write(self, vals):
        res = super().write(vals)
        self.env['product.template']._sync_promo_availability()
        return res

    def unlink(self):
        res = super().unlink()
        self.env['product.template']._sync_promo_availability()
        return res

    @api.model
    def _get_actions(self):
        """Alle acties: prijsregels met een begin- én einddatum, ook afgelopen of geplande.

        Een regel zonder datums (een vaste korting) is geen actie.
        """
        return self.sudo().search([
            ('pricelist_id.active', '=', True),
            ('date_start', '!=', False),
            ('date_end', '!=', False),
        ])

    @api.model
    def _get_running_actions(self):
        """Acties die nu lopen."""
        now = fields.Datetime.now()
        return self._get_actions().filtered(lambda item: item.date_start <= now <= item.date_end)

    def _get_product_templates(self):
        """Producten waarop deze prijsregels van toepassing zijn."""
        Template = self.env['product.template'].sudo()
        templates = Template.browse()
        for item in self:
            if item.applied_on == '0_product_variant':
                templates |= item.product_id.product_tmpl_id
            elif item.applied_on == '1_product':
                templates |= item.product_tmpl_id
            elif item.applied_on == '2_product_category':
                templates |= Template.search([('categ_id', 'child_of', item.categ_id.id)])
            else:  # '3_global': alle producten
                templates |= Template.search([('sale_ok', '=', True)])
        return templates