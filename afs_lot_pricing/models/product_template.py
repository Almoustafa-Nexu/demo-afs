from collections import defaultdict

from markupsafe import Markup

from odoo import fields, models
from odoo.fields import Domain
from odoo.http import request

OPEN_MOVE_STATES = ('confirmed', 'partially_available', 'waiting')


def _pieces(qty):
    """'5 stuks', '1 stuk'."""
    qty = round(qty, 2)
    return '%g %s' % (qty, 'stuk' if qty == 1 else 'stuks')


def _discount(normal_price, price):
    """Korting in hele procenten (minstens 1 zodra het een cent goedkoper is)."""
    return max(1, round(100 * (normal_price - price) / normal_price)) if normal_price - price >= 0.01 else 0


def order_item(order, pieces, status):
    """<li>S00279 – Apotheek Pasa – 86 stuks – offerte, nog niet bevestigd</li>, met een link naar de bestelling."""
    return Markup('<li><a href="/odoo/sales/%s" target="_blank">%s</a> – %s – %s – %s</li>') % (
        order.id, order.name, order.partner_id.commercial_partner_id.name, pieces, status)


def _request_pricelist(pricelist):
    if pricelist is None and request and getattr(request, 'pricelist', None) is not None:
        return request.pricelist
    return pricelist


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    afs_lot_pricing = fields.Boolean(
        string="Korting per partij doorrekenen",
        help="De apotheek betaalt de prijs van de partij die ze krijgt (inkoopprijs min korting): in de shop, in "
             "de winkelwagen en op de factuur (een regel per partij). Werkt samen met Waardering per partij- of "
             "serienummer en het vinkje op de prijslijst.",
    )

    def _afs_uses_lot_pricing(self):
        product = self.sudo()
        return bool(product.afs_lot_pricing and product.lot_valuated and product.is_storable)

    def _afs_search(self, model, domain):
        """Records van dit product (alle varianten), als sudo."""
        return self.env[model].sudo().search([('product_id', 'in', self.sudo().product_variant_ids.ids)] + domain)

    def _afs_website_warehouse(self, website):
        website = website.sudo()
        return website.warehouse_id or self.env['stock.warehouse'].sudo().search(
            [('company_id', '=', website.company_id.id)], limit=1)

    def _afs_warehouse(self):
        """Magazijn van de bestelling (context), anders van de webshop, anders het eerste van het bedrijf."""
        if warehouse_id := self.env.context.get('afs_warehouse_id'):
            return self.env['stock.warehouse'].sudo().browse(warehouse_id)
        if request and getattr(request, 'website', None):
            return self._afs_website_warehouse(request.website)
        return self.env['stock.warehouse'].sudo().search([('company_id', '=', self.env.company.id)], limit=1)

    # ---- Voorraad per partij en voorverkoop ----

    def _afs_lot_rows(self, warehouse=None):
        """Vrije voorraad per partij, de oudste eerst: [(partij, aantal, kostprijs)]."""
        return self._afs_lot_stock(warehouse)[0]

    def _afs_lot_stock(self, warehouse=None, quoted=0.0):
        """Vrije voorraad per partij, de oudste eerst. Offertes (`quoted` stuks) nemen eerst de oudste stuks; wat de
        eigen orderregel (context afs_sale_line_id) reserveerde, is voor haar vrij.

        :return: ([(partij, aantal, kostprijs)], wat er van `quoted` overblijft voor de voorverkoop)
        """
        self.ensure_one()
        if not self._afs_uses_lot_pricing():
            return [], quoted
        warehouse = (warehouse or self._afs_warehouse()).sudo()
        location = warehouse.lot_stock_id
        if not location:
            return [], quoted

        free, first_in = defaultdict(float), {}
        for quant in self._afs_search('stock.quant', [('location_id', 'child_of', location.id), ('lot_id', '!=', False)]):
            lot = quant.lot_id
            free[lot] += quant.quantity - quant.reserved_quantity
            if quant.in_date and (lot not in first_in or quant.in_date < first_in[lot]):
                first_in[lot] = quant.in_date
        now = fields.Datetime.now()
        lots = sorted(free, key=lambda lot: (first_in.get(lot) or now, lot.id))

        for lot in lots:
            taken = min(max(free[lot], 0.0), quoted)
            free[lot] -= taken + self.env.context.get('afs_taken', {}).get(lot.id, 0.0)
            quoted -= taken

        if line_id := self.env.context.get('afs_sale_line_id'):
            own = defaultdict(float)
            for move_line in self.env['stock.move.line'].sudo().search([
                ('move_id.sale_line_id', '=', line_id), ('state', 'not in', ('done', 'cancel')),
                ('lot_id', '!=', False), ('location_id', 'child_of', location.id),
            ]):
                own[move_line.lot_id] += move_line.quantity_product_uom
            for lot, qty in own.items():
                if lot in free:
                    free[lot] += qty

        company = warehouse.company_id or self.env.company
        rows = [(lot, free[lot], lot.sudo().with_company(company).standard_price) for lot in lots if free[lot] > 0]
        return rows, quoted

    def _afs_shop_rows(self, warehouse=None):
        """Wat een apotheek nog kan kopen, in de volgorde van levering: vrije partijen, dan de voorverkoop.
        :return: [(partij of inkoopregel, aantal, kostprijs)]"""
        self.ensure_one()
        warehouse = (warehouse or self._afs_warehouse()).sudo()
        rows, quoted_rest = self._afs_lot_stock(warehouse, self._afs_quoted_qty(warehouse))
        presale = self._afs_presale(warehouse, quoted=quoted_rest)
        return rows + [(line, free, cost) for line, _todo, _ordered, free, cost in presale if free > 0]

    def _afs_presale(self, warehouse, quoted=None):
        """Voorverkoop: regels van inkoopoffertes met Voorverkoop in de webshop die nog niet (helemaal) binnen zijn,
        als partij aan de prijs van de offerte. Wat bevestigde bestellingen en niet gedekte offertes (`quoted`, leeg =
        zelf berekenen) al namen, gaat eraf, de eerste inkoop eerst; regels op dezelfde datum in hun volgorde.

        :return: [(inkoopregel, nog te ontvangen, al besteld, nog vrij, kostprijs)]
        """
        self.ensure_one()
        if not self._afs_uses_lot_pricing():
            return []
        warehouse = warehouse.sudo()
        if not warehouse.lot_stock_id:
            return []
        lines = self._afs_search('purchase.order.line', [
            ('display_type', '=', False),
            ('order_id.afs_presale', '=', True),
            ('order_id.state', 'in', ('draft', 'sent', 'to approve', 'purchase')),
            ('order_id.picking_type_id.warehouse_id', '=', warehouse.id),
        ])
        if not lines:
            return []
        if quoted is None:
            quoted = self._afs_lot_stock(warehouse, self._afs_quoted_qty(warehouse))[1]
        waiting = self._afs_waiting_qty(warehouse.lot_stock_id) + quoted
        now = fields.Datetime.now()
        res = []
        for line in lines.sorted(lambda l: (l.date_planned or now, l.sequence, l.id)):
            if line.order_id.state == 'purchase':
                # bevestigd: wat nog binnenkomt (een geannuleerde nalevering telt niet)
                todo = sum(line._get_outgoing_incoming_moves()[1].filtered(lambda m: m.state != 'done').mapped('product_qty'))
            else:
                todo = line.product_uom_qty
            if line.product_id.uom_id.compare(todo, 0) <= 0:
                continue
            ordered = min(todo, waiting)
            waiting -= ordered
            res.append((line, todo, ordered, todo - ordered, line._get_stock_move_price_unit()))
        return res

    def _afs_presale_free_qty(self, warehouse, variant=None):
        """Nog te koop in de voorverkoop, eventueel van een variant."""
        self.ensure_one()
        if not warehouse:
            return 0.0
        return sum(free for line, _todo, _ordered, free, _cost in self.sudo()._afs_presale(warehouse.sudo())
                   if not variant or line.product_id == variant)

    def _afs_open_orders(self, warehouse):
        """Bestellingen die op dit product wachten: eerst bevestigde zonder voorraad, dan offertes (oudste eerst).
        :return: [(bestelling, stuks, bevestigd)]"""
        self.ensure_one()
        qty, confirmed = defaultdict(float), {}
        for line in self._afs_quoted_lines(warehouse):
            qty[line.order_id] += line.product_uom_id._compute_quantity(line.product_uom_qty, line.product_id.uom_id)
            confirmed[line.order_id] = False
        location = warehouse.lot_stock_id
        for move in self._afs_search('stock.move', [
            ('state', 'in', OPEN_MOVE_STATES), ('location_id', 'child_of', location.id), ('sale_line_id', '!=', False),
        ]):
            missing = move.product_qty - move.product_uom._compute_quantity(move.quantity, move.product_id.uom_id)
            if missing > 0 and not move.location_dest_id._child_of(location):
                order = move.sale_line_id.order_id
                qty[order] += missing
                confirmed[order] = True
        return sorted(((order, q, confirmed[order]) for order, q in qty.items() if q > 0),
                      key=lambda row: (not row[2], row[0].date_order, row[0].id))

    def _afs_presale_claims(self, warehouse):
        """Wie de voorverkoop al bestelde (een offerte neemt eerst de gewone voorraad, zoals in de shop).
        :return: [(inkoopregel, nog te ontvangen, [(bestelling of False, stuks, stuks in de bestelling, bevestigd)])]"""
        self.ensure_one()
        uom = self.uom_id
        stock = sum(qty for _lot, qty, _cost in self._afs_lot_rows(warehouse))
        queue = []
        for order, qty, confirmed in self._afs_open_orders(warehouse):
            rest = qty if confirmed else max(qty - stock, 0.0)
            stock -= qty - rest
            if uom.compare(rest, 0) > 0:
                queue.append([order, rest, qty, confirmed])
        res = []
        for line, todo, ordered, _free, _cost in self._afs_presale(warehouse):
            claims = []
            while uom.compare(ordered, 0) > 0:
                if not queue:
                    claims.append((False, ordered, ordered, True))  # andere leveringen uit de voorraad
                    break
                row = queue[0]
                taken = min(row[1], ordered)
                claims.append((row[0], taken, row[2], row[3]))
                ordered -= taken
                row[1] -= taken
                if uom.compare(row[1], 0) <= 0:
                    queue.pop(0)
            res.append((line, todo, claims))
        return res

    def _afs_waiting_qty(self, stock_location):
        """Bevestigde bestellingen uit deze locatie die nog op voorraad wachten, zonder de eigen orderregel."""
        own_line_id = self.env.context.get('afs_sale_line_id')
        waiting = 0.0
        for move in self._afs_search('stock.move', [
            ('state', 'in', OPEN_MOVE_STATES), ('location_id', 'child_of', stock_location.id),
        ]):
            if move.location_dest_id._child_of(stock_location) or (own_line_id and move.sale_line_id.id == own_line_id):
                continue
            reserved = move.product_uom._compute_quantity(move.quantity, move.product_id.uom_id)
            waiting += max(move.product_qty - reserved, 0.0)
        return waiting

    def _afs_holders(self, warehouse):
        """Wie de partijen van dit product in het magazijn vasthoudt: offertes (nog te bevestigen) en bevestigde
        orders (gereserveerd). :return: {bestelling: [stuks, bevestigd]}"""
        self.ensure_one()
        res = defaultdict(lambda: [0.0, False])
        for line in self._afs_quoted_lines(warehouse):
            res[line.order_id][0] += line.product_uom_id._compute_quantity(line.product_uom_qty, line.product_id.uom_id)
        for ml in self._afs_search('stock.move.line', [
            ('move_id.sale_line_id', '!=', False), ('state', 'not in', ('done', 'cancel')),
            ('lot_id', '!=', False), ('location_id', 'child_of', warehouse.lot_stock_id.id),
        ]):
            row = res[ml.move_id.sale_line_id.order_id]
            row[0] += ml.quantity_product_uom
            row[1] = True
        return res

    def _afs_buys_automatically(self, warehouse):
        """Koopt Odoo wat ontbreekt vanzelf in bij het bevestigen? Aanvullen op order (MTO) op het product, en Kopen
        op het product of het magazijn (Kopen om aan te vullen)."""
        routes = self.route_ids | self.categ_id.total_route_ids
        return (any(r.procure_method in ('make_to_order', 'mts_else_mto') for r in routes.rule_ids)
                and any(r.action == 'buy' for r in (routes | warehouse.route_ids).rule_ids))

    def _afs_quoted_lines(self, warehouse):
        """Orderregels van offertes die AFS nog moet bevestigen (zo komt een webshopbestelling binnen). Een negatief
        aantal geeft geen stuks vrij."""
        return self._afs_search('sale.order.line', [
            ('display_type', '=', False),
            ('order_id.state', '=', 'sent'),
            ('order_id.warehouse_id', '=', warehouse.id),
            ('product_uom_qty', '>', 0),
        ])

    def _afs_quoted_qty(self, warehouse):
        """Stuks in offertes uit dit magazijn, zonder de eigen orderregel of order (context). Met afs_quoted_before =
        (datum, id) alleen de bestellingen die eerder binnenkwamen."""
        context = self.env.context
        before = context.get('afs_quoted_before')

        def counts(line):
            order = line.order_id
            return (line.id != context.get('afs_sale_line_id') and order.id != context.get('afs_sale_order_id')
                    and (not before or (order.date_order, order.id) < before))

        return sum(line.product_uom_id._compute_quantity(line.product_uom_qty, line.product_id.uom_id)
                   for line in self._afs_quoted_lines(warehouse) if counts(line))

    # ---- Webshop: teller, doel en sticker ----

    def _afs_lot_counter(self, website=None, pricelist=None, taxed=True):
        """Nog te koop per prijs (oudste partij eerst, dan de voorverkoop); partijen na elkaar aan dezelfde prijs
        samen. Leeg zonder korting per partij. `taxed`: de prijs zoals de shop ze toont (met of zonder btw).

        :return: [{'qty', 'price', 'lot' (eerste partij), 'lots', 'presale', 'presale_qty'}]
        """
        self.ensure_one()
        if not self._afs_uses_lot_pricing():
            return []
        pricelist = _request_pricelist(pricelist)
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

        product_taxes = taxes = None  # btw zoals de shop (fiscale positie van de bezoeker)
        if taxed and request and getattr(request, 'fiscal_position', None) is not None:
            product_taxes = variant.taxes_id._filter_taxes_by_company(website.company_id)
            if product_taxes:
                taxes = request.fiscal_position.map_tax(product_taxes)

        groups = []
        for source, qty, cost in product._afs_shop_rows(warehouse):
            price = rule._afs_lot_unit_price(variant, cost, variant.uom_id, date, currency)
            if taxes is not None:
                price = product._apply_taxes_to_price(price, currency, product_taxes, taxes, variant, website=website)
            price = currency.round(price)
            presale = source._name == 'purchase.order.line'
            name = source._afs_lot_name() if presale else source.name
            if groups and currency.compare_amounts(groups[-1]['price'], price) == 0:
                group = groups[-1]
                group['qty'] += qty
                group['lots'].append(name)
            else:
                group = {'qty': qty, 'price': price, 'lot': name, 'lots': [name], 'presale': presale, 'presale_qty': 0.0}
                groups.append(group)
            if presale:
                group['presale_qty'] += qty
        return groups

    def _afs_lot_goal(self, website, normal_price, pricelist=None):
        """Productpagina: het doel van de apotheken samen ("Nog 100 stuks ..., dan krijg je 20% korting."), de
        voorraad en de stappen (partijen met dezelfde korting na elkaar zijn een stap), of None."""
        rows = self._afs_lot_counter(website, pricelist)
        if not rows:
            return None
        steps = []
        for row in rows:
            off = _discount(normal_price, row['price'])
            if steps and steps[-1]['discount'] == off:
                steps[-1]['qty'] += row['qty']
            else:
                steps.append({'discount': off, 'qty': row['qty'], 'price': row['price']})
        goal, nxt = 0.0, None
        for step in steps:
            if step['discount'] > steps[0]['discount']:
                nxt = step
                break
            goal += step['qty']
        presale = sum(row['presale_qty'] for row in rows)
        stock = sum(row['qty'] for row in rows) - presale
        return {
            'goal': _pieces(goal) if nxt else '',
            'few': goal <= 10,
            'discount': nxt['discount'] if nxt else 0,
            'stock': _pieces(stock) if stock >= 0.5 else '',
            'presale': _pieces(presale) if presale >= 0.5 else '',
            'steps': [{'label': '%d%% korting' % step['discount'] if step['discount'] else 'Normale prijs',
                       'qty': _pieces(step['qty']), 'price': step['price'], 'now': not index}
                      for index, step in enumerate(steps)] if len(steps) > 1 else [],
        }

    def _afs_lot_teaser(self, website, pricelist=None):
        """Shopkaartje aan de normale prijs met stappen naar korting: "tot −40%" voor de sticker Actie, anders None."""
        self.ensure_one()
        pricelist = _request_pricelist(pricelist)
        if not pricelist or not self._afs_uses_lot_pricing():
            return None
        if _discount(self.list_price, pricelist.sudo()._get_product_price(self.sudo().product_variant_id, 1.0)):
            return None
        rows = self._afs_lot_counter(website, pricelist, taxed=False)
        best = max((_discount(self.list_price, row['price']) for row in rows), default=0)
        return 'tot −%d%%' % best if best else None

    def _get_promo_products(self, pricelist=None):
        """In actie: ook producten aan de normale prijs met stappen naar korting (sticker Actie)."""
        products = super()._get_promo_products(pricelist)
        pricelist = pricelist or getattr(request, 'pricelist', False)
        if not pricelist:
            return products
        website = self.env['website'].get_current_website()
        others = self.sudo().search(Domain.AND([
            website.sale_product_domain(),
            [('is_published', '=', True), ('afs_lot_pricing', '=', True), ('id', 'not in', products.ids)],
        ]))
        return products | others.filtered(lambda t: t._afs_lot_teaser(website, pricelist))
