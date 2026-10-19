from odoo import api, fields, models
from odoo.exceptions import ValidationError
from odoo.fields import Domain


class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    afs_vendor_id = fields.Many2one(
        'res.partner', string="Producten van", compute='_compute_afs_vendor_id',
        help="De leverancier waarvan je op deze inkoop producten kan kiezen. Leeg: alle producten "
             "(Inkoop per leverancier staat uit, of er is nog geen leverancier gekozen).",
    )

    @api.depends('partner_id', 'company_id', 'company_id.afs_purchase_vendor_only')
    def _compute_afs_vendor_id(self):
        for order in self:
            if order._afs_enabled():
                order.afs_vendor_id = order.partner_id.commercial_partner_id
            else:
                order.afs_vendor_id = False

    def _afs_enabled(self):
        return bool((self.company_id or self.env.company).afs_purchase_vendor_only)

    # ------------------------------------------------------------
    # Alleen producten van de leverancier
    # ------------------------------------------------------------

    def _afs_wrong_lines(self):
        """Regels met een product waar deze leverancier niet op staat (product, tabblad Inkoop).
        Diensten (bv. transportkosten) en aanbetalingen tellen niet mee."""
        self.ensure_one()
        vendor = self.partner_id.commercial_partner_id
        if not vendor:
            return self.env['purchase.order.line']
        return self.order_line.filtered(
            lambda line: line.product_id and not line.display_type and not line.is_downpayment
            and line.product_id.type != 'service' and not line._afs_sold_by(vendor)
        )

    def _afs_wrong_message(self, lines):
        vendor = self.partner_id.commercial_partner_id
        return self.env._(
            "%(vendor)s levert niet: %(products)s.\n\n"
            "Kies een product van %(vendor)s, of zet %(vendor)s als leverancier op het product (tabblad Inkoop). "
            "Uitzetten kan in Inkoop > Configuratie > Instellingen > Inkoop per leverancier.",
            vendor=vendor.display_name,
            products=', '.join(lines.product_id.mapped('display_name')),
        )

    def _afs_check_vendor_products(self):
        for order in self:
            if not order._afs_enabled() or order.state not in ('draft', 'sent', 'to approve'):
                continue
            wrong = order._afs_wrong_lines()
            if wrong:
                raise ValidationError(order._afs_wrong_message(wrong))

    @api.constrains('partner_id')
    def _afs_check_partner_products(self):
        self._afs_check_vendor_products()

    @api.onchange('partner_id')
    def _afs_onchange_partner_products(self):
        """Andere leverancier gekozen terwijl er al producten op staan: meteen melden."""
        if not self.afs_vendor_id:
            return None
        wrong = self._afs_wrong_lines()
        if wrong:
            return {'warning': {
                'title': self.env._("Producten van een andere leverancier"),
                'message': self._afs_wrong_message(wrong),
            }}
        return None

    def _get_product_catalog_domain(self):
        """Catalogus: ook daar alleen producten van de leverancier (en diensten)."""
        domain = super()._get_product_catalog_domain()
        if self.afs_vendor_id:
            domain &= Domain('type', '=', 'service') | Domain('seller_ids.partner_id', 'child_of', self.afs_vendor_id.id)
        return domain

    # ------------------------------------------------------------
    # Leveren aan volgt het product
    # ------------------------------------------------------------

    def _afs_follows_products(self):
        """Leveren aan volgt de producten alleen bij een inkoop die je met de hand maakt: geen brondocument en niets
        besteld voor een order of een aanvulregel. Een inkoop die Odoo zelf maakte, hoort bij een keten
        (bv. Markgraven bevoorraden via AFS): die blijft zoals ze is."""
        self.ensure_one()
        if not self._afs_enabled() or self.origin:
            return False
        lines = self.order_line
        return not lines.move_dest_ids and not lines.orderpoint_id

    def _afs_product_warehouse(self, product):
        """Magazijn waaruit dit product naar de klanten vertrekt (de route van het product), zoals Odoo het kiest
        bij een bestelling. Daar komt ook de inkoop binnen, net als bij een inkoop die Odoo zelf maakt."""
        company = self.company_id or self.env.company
        base = self._get_picking_type(company.id).warehouse_id
        customers = self.env.ref('stock.stock_location_customers', raise_if_not_found=False)
        if not (base and customers and product.is_storable):
            return self.env['stock.warehouse']
        rule = self.env['stock.rule'].sudo()._get_rule(product, customers, {'warehouse_id': base, 'company_id': company})
        return rule.location_src_id.warehouse_id

    def _afs_line_warehouses(self):
        """{magazijn: producten} voor de productregels van deze inkoop."""
        res = {}
        for line in self.order_line:
            if not line.product_id or line.display_type:
                continue
            warehouse = self._afs_product_warehouse(line.product_id)
            if warehouse:
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
        """Leveren aan met de hand op een ander magazijn gezet: waarschuwen."""
        if not self._afs_follows_products():
            return None
        per_warehouse = self._afs_line_warehouses()
        if len(per_warehouse) != 1:
            return None
        warehouse, products = next(iter(per_warehouse.items()))
        chosen = self.picking_type_id.warehouse_id
        if chosen and chosen != warehouse:
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
        return None


class PurchaseOrderLine(models.Model):
    _inherit = 'purchase.order.line'

    def _afs_sold_by(self, vendor):
        """Staat deze leverancier (of een contactpersoon ervan) als leverancier op het product (tabblad Inkoop)?"""
        self.ensure_one()
        product = self.product_id
        return any(
            seller.partner_id.commercial_partner_id == vendor and (not seller.product_id or seller.product_id == product)
            for seller in product.sudo().seller_ids
        )

    @api.constrains('product_id')
    def _afs_check_vendor_product(self):
        self.order_id._afs_check_vendor_products()
