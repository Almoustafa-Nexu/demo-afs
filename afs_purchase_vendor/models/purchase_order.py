from odoo import api, fields, models


class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    # Onthoudt welke producten al op de inkoop stonden: alleen een nieuw gekozen product kiest de leverancier
    afs_seen_products = fields.Char(string="Producten gezien", store=False, copy=False)

    def _afs_enabled(self):
        return bool((self.company_id or self.env.company).afs_purchase_vendor_only)

    def _afs_product_lines(self):
        return self.order_line.filtered(lambda l: l.product_id and not l.display_type and l.product_id.type != 'service')

    def _afs_vendor_of_product(self, product):
        """De eerste leverancier van het product (tabblad Inkoop) die voor dit bedrijf geldt."""
        company = self.company_id or self.env.company
        sellers = product.sudo().seller_ids.filtered(
            lambda s: s.partner_id and (not s.company_id or s.company_id == company)
            and (not s.product_id or s.product_id == product))
        return sellers[:1].partner_id.commercial_partner_id

    # ---- De leverancier volgt het product ----

    @api.onchange('order_line')
    def _afs_onchange_order_line_vendor(self):
        """Nieuw product dat de leverancier bovenaan niet verkoopt: de leverancier van dat product komt bovenaan."""
        if not self._afs_enabled():
            return
        product_ids = set(self._afs_product_lines().product_id.ids)
        if self.afs_seen_products:
            seen = {int(i) for i in self.afs_seen_products.split(',') if i}
        else:
            seen = set(self._origin._afs_product_lines().product_id.ids) if self._origin else set()
        self.afs_seen_products = ',' + ','.join(str(i) for i in sorted(product_ids)) + ','
        vendor = self.partner_id.commercial_partner_id
        for line in self._afs_product_lines():
            if line.product_id.id in seen or (vendor and line._afs_sold_by(vendor)):
                continue
            if new_vendor := self._afs_vendor_of_product(line.product_id):
                self.partner_id = new_vendor
                break

    @api.onchange('partner_id')
    def _afs_onchange_partner_products(self):
        """Zelf een andere leverancier gekozen: mag, met een venster met de knop Accepteer (static/src/js)."""
        if not self._afs_enabled():
            return None
        vendor = self.partner_id.commercial_partner_id
        if not vendor:
            return None
        wrong = self._afs_product_lines().filtered(lambda l: not l.is_downpayment and not l._afs_sold_by(vendor))
        if not wrong:
            return None
        terug = self._afs_vendor_of_product(wrong[0].product_id)
        # Odoo geeft van een melding alleen titel, tekst en type door: de leverancier om naar terug te gaan zit in het type
        return {'warning': {
            'type': 'afs_accept:%s:%s' % (terug.id, terug.display_name) if terug else 'afs_accept',
            'title': self.env._("Andere leverancier dan op het product"),
            'message': self.env._(
                "%(vendor)s staat niet als leverancier op: %(products)s.\n\n"
                "Klik op Accepteer om %(vendor)s te houden, of op Weigeren om terug te gaan naar %(back)s. "
                "Wil je dat het product er voortaan bij hoort, zet %(vendor)s dan als leverancier op het product "
                "(tabblad Inkoop).",
                vendor=vendor.display_name,
                products=', '.join(wrong.product_id.mapped('display_name')),
                back=terug.display_name or self.env._("een lege leverancier"),
            ),
        }}

    # ---- Leveren aan volgt het product ----

    def _afs_follows_products(self):
        """Alleen een inkoop met de hand: geen brondocument, niets voor een order of aanvulregel."""
        self.ensure_one()
        return self._afs_enabled() and not self.origin and not (self.order_line.move_dest_ids or
                                                                self.order_line.orderpoint_id)

    def _afs_product_warehouse(self, product):
        """Magazijn waaruit dit product naar de klanten gaat (zijn route), zoals Odoo het kiest bij een bestelling."""
        company = self.company_id or self.env.company
        base = self._get_picking_type(company.id).warehouse_id
        customers = self.env.ref('stock.stock_location_customers', raise_if_not_found=False)
        if not (base and customers and product.is_storable):
            return self.env['stock.warehouse']
        rule = self.env['stock.rule'].sudo()._get_rule(product, customers, {'warehouse_id': base, 'company_id': company})
        return rule.location_src_id.warehouse_id

    def _afs_line_warehouses(self):
        """{magazijn: producten} van de productregels."""
        res = {}
        for line in self.order_line.filtered(lambda l: l.product_id and not l.display_type):
            if warehouse := self._afs_product_warehouse(line.product_id):
                res[warehouse] = res.get(warehouse, self.env['product.product']) | line.product_id
        return res

    @api.onchange('order_line')
    def _afs_onchange_order_line_deliver_to(self):
        if not self._afs_follows_products():
            return None
        per_warehouse = self._afs_line_warehouses()
        if len(per_warehouse) > 1:
            return {'warning': {
                'title': self.env._("Producten voor verschillende magazijnen"),
                'message': self.env._(
                    "Deze producten gaan naar de apotheken vanuit verschillende magazijnen: %(list)s.\n\n"
                    "Maak per magazijn een aparte inkoop, zodat alles binnenkomt waar het geleverd wordt.",
                    list='; '.join('%s: %s' % (warehouse.name, ', '.join(products.mapped('display_name')))
                                   for warehouse, products in per_warehouse.items()),
                ),
            }}
        if per_warehouse:
            warehouse = next(iter(per_warehouse))
            if warehouse.in_type_id and self.picking_type_id.warehouse_id != warehouse:
                self.picking_type_id = warehouse.in_type_id
        return None

    @api.onchange('picking_type_id')
    def _afs_onchange_deliver_to_warning(self):
        """Leveren aan met de hand naar een ander magazijn: waarschuwen."""
        if not self._afs_follows_products():
            return None
        per_warehouse = self._afs_line_warehouses()
        if len(per_warehouse) != 1:
            return None
        warehouse, products = next(iter(per_warehouse.items()))
        chosen = self.picking_type_id.warehouse_id
        if not chosen or chosen == warehouse:
            return None
        return {'warning': {
            'title': self.env._("Ander magazijn"),
            'message': self.env._(
                "%(products)s gaat naar de apotheken vanuit %(warehouse)s. Kies bij Leveren aan %(type)s, "
                "anders komt de inkoop binnen in %(chosen)s, dat dit product niet levert.",
                products=', '.join(products.mapped('display_name')),
                warehouse=warehouse.name,
                type=warehouse.in_type_id.display_name,
                chosen=chosen.name,
            ),
        }}


class PurchaseOrderLine(models.Model):
    _inherit = 'purchase.order.line'

    def _afs_sold_by(self, vendor):
        """Staat deze leverancier (of een contact ervan) op het product (tabblad Inkoop)?"""
        self.ensure_one()
        return any(s.partner_id.commercial_partner_id == vendor and (not s.product_id or s.product_id == self.product_id)
                   for s in self.product_id.sudo().seller_ids)
