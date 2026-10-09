from collections import defaultdict

from odoo import fields, models
from odoo.http import request


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    afs_lot_pricing = fields.Boolean(
        string="Korting per partij doorrekenen",
        help="De apotheek betaalt de prijs van de partij die ze krijgt (inkoopprijs min korting): "
             "in de shop, in de winkelwagen en op de factuur (een regel per partij). "
             "Werkt samen met Waardering per partij-/serienummer en het vinkje op de prijslijst.",
    )

    def _afs_uses_lot_pricing(self):
        """Volgt de prijs van dit product de partij? Vinkje aan, waardering per partij en voorraad bijhouden."""
        product = self.sudo()
        return bool(product.afs_lot_pricing and product.lot_valuated and product.is_storable)

    def _afs_website_warehouse(self, website):
        """Magazijn van de webshop, anders het eerste magazijn van het bedrijf van de webshop."""
        website = website.sudo()
        return website.warehouse_id or self.env['stock.warehouse'].sudo().search(
            [('company_id', '=', website.company_id.id)], limit=1)

    def _afs_warehouse(self):
        """Magazijn waaruit geleverd wordt: dat van de bestelling, anders dat van de webshop,
        anders het eerste magazijn van het bedrijf."""
        Warehouse = self.env['stock.warehouse'].sudo()
        if warehouse_id := self.env.context.get('afs_warehouse_id'):
            return Warehouse.browse(warehouse_id)
        website = getattr(request, 'website', None) if request else None
        if website:
            return self._afs_website_warehouse(website)
        return Warehouse.search([('company_id', '=', self.env.company.id)], limit=1)

    def _afs_lot_rows(self, warehouse=None):
        """Vrije voorraad per partij in de voorraadlocatie van het magazijn, de oudste partij eerst.

        Wat de eigen orderregel (context afs_sale_line_id) al reserveerde, telt als vrij voor die regel.

        :return: lijst van (stock.lot, aantal in de eenheid van het product, kostprijs van de partij)
        """
        self.ensure_one()
        if not self._afs_uses_lot_pricing():
            return []
        warehouse = (warehouse or self._afs_warehouse()).sudo()
        stock_location = warehouse.lot_stock_id
        if not stock_location:
            return []

        free = defaultdict(float)
        first_in = {}
        for quant in self.env['stock.quant'].sudo().search([
            ('product_id', 'in', self.sudo().product_variant_ids.ids),
            ('location_id', 'child_of', stock_location.id),
            ('lot_id', '!=', False),
        ]):
            lot = quant.lot_id
            free[lot] += quant.quantity - quant.reserved_quantity
            if quant.in_date and (not first_in.get(lot) or quant.in_date < first_in[lot]):
                first_in[lot] = quant.in_date

        if line_id := self.env.context.get('afs_sale_line_id'):
            own = defaultdict(float)
            for move_line in self.env['stock.move.line'].sudo().search([
                ('move_id.sale_line_id', '=', line_id),
                ('state', 'not in', ('done', 'cancel')),
                ('lot_id', '!=', False),
                ('location_id', 'child_of', stock_location.id),
            ]):
                own[move_line.lot_id] += move_line.product_uom_id._compute_quantity(
                    move_line.quantity, move_line.product_id.uom_id)
            for lot, qty in own.items():
                if lot in free:
                    free[lot] += qty

        company = warehouse.company_id or self.env.company
        now = fields.Datetime.now()
        oldest_first = sorted(free, key=lambda lot: (first_in.get(lot) or now, lot.id))
        return [(lot, free[lot], lot.sudo().with_company(company).standard_price)
                for lot in oldest_first if free[lot] > 0]

    def _afs_lot_counter(self, website=None, pricelist=None):
        """Teller voor de webshop: hoeveel stuks er nog zijn aan welke prijs, de oudste partij eerst.
        Partijen na elkaar met dezelfde prijs worden samengeteld.

        Alleen met een prijslijst met "Korting per partij doorrekenen" (dus niet in de personeelsshop),
        en alleen als de prijs uit een regel op kostprijs of uit een actie komt.

        :return: lijst van dicts {'qty', 'price', 'lot' (eerste partij), 'lots' (alle partijen)}
        """
        self.ensure_one()
        if not self._afs_uses_lot_pricing():
            return []
        if pricelist is None and request and getattr(request, 'pricelist', None) is not None:
            pricelist = request.pricelist
        if not pricelist or not pricelist.sudo().afs_lot_pricing:
            return []
        pricelist = pricelist.sudo()
        website = (website or self.env['website'].get_current_website()).sudo()
        warehouse = self._afs_website_warehouse(website)
        product = self.sudo()
        variant = product.product_variant_id
        if not warehouse or not variant:
            return []
        date = fields.Datetime.now()
        rule = self.env['product.pricelist.item'].sudo().browse(pricelist._get_product_rule(variant, 1.0, date=date))
        if not rule._afs_lot_mode(variant):
            return []
        currency = pricelist.currency_id or website.currency_id

        # Zoals de shop prijzen toont: met of zonder btw (fiscale positie van de bezoeker), afgerond
        taxes = product_taxes = None
        if request and getattr(request, 'fiscal_position', None) is not None:
            product_taxes = variant.taxes_id._filter_taxes_by_company(website.company_id)
            if product_taxes:
                taxes = request.fiscal_position.map_tax(product_taxes)

        def shop_price(price):
            if taxes is not None:
                price = product._apply_taxes_to_price(price, currency, product_taxes, taxes, variant, website=website)
            return currency.round(price)

        groups = []
        for lot, qty, cost in product._afs_lot_rows(warehouse):
            price = shop_price(rule._afs_lot_unit_price(variant, cost, variant.uom_id, date, currency))
            if groups and currency.compare_amounts(groups[-1]['price'], price) == 0:
                groups[-1]['qty'] += qty
                groups[-1]['lots'].append(lot.name)
            else:
                groups.append({'qty': qty, 'price': price, 'lot': lot.name, 'lots': [lot.name]})
        return groups

    def _afs_lot_counter_rest(self, rows, shown=3):
        """Aantal stuks na de eerste `shown` lijnen van de teller."""
        return sum(row['qty'] for row in rows[shown:])
