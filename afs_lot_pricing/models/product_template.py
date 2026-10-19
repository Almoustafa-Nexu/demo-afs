from collections import defaultdict

from odoo import fields, models
from odoo.fields import Domain
from odoo.http import request


def _pieces(qty):
    """5 stuks, 1 stuk."""
    qty = round(qty, 2)
    return '%g %s' % (qty, 'stuk' if qty == 1 else 'stuks')


def _discount(normal_price, price):
    """Korting in hele procenten t.o.v. de normale prijs (minstens 1 zodra het een cent goedkoper is)."""
    return max(1, round(100 * (normal_price - price) / normal_price)) if normal_price - price >= 0.01 else 0


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    afs_lot_pricing = fields.Boolean(
        string="Korting per partij doorrekenen",
        help="De apotheek betaalt de prijs van de partij die ze krijgt (inkoopprijs min korting): in de shop, in "
             "de winkelwagen en op de factuur (een regel per partij). Werkt samen met Waardering per partij- of "
             "serienummer en het vinkje op de prijslijst.",
    )

    def _afs_uses_lot_pricing(self):
        """Volgt de prijs van dit product de partij? Vinkje aan, waardering per partij en voorraad bijhouden."""
        product = self.sudo()
        return bool(product.afs_lot_pricing and product.lot_valuated and product.is_storable)

    def _afs_search(self, model, domain):
        """Zoek records van dit product (alle varianten), zonder toegangsrechten."""
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

    def _afs_lot_rows(self, warehouse=None):
        """Vrije voorraad per partij, de oudste eerst: [(partij, aantal, kostprijs)]."""
        return self._afs_lot_stock(warehouse)[0]

    def _afs_lot_stock(self, warehouse=None, quoted=0.0):
        """Vrije voorraad per partij in het magazijn, de oudste partij eerst.

        Offertes die AFS nog moet bevestigen (`quoted` stuks) nemen eerst de oudste stuks. Wat de eigen
        orderregel (context afs_sale_line_id) reserveerde, telt voor haar als vrij.

        :return: ([(partij, aantal, kostprijs)], wat er van `quoted` overschiet voor de voorverkoop)
        """
        self.ensure_one()
        if not self._afs_uses_lot_pricing():
            return [], quoted
        warehouse = (warehouse or self._afs_warehouse()).sudo()
        location = warehouse.lot_stock_id
        if not location:
            return [], quoted

        free, first_in = defaultdict(float), {}
        quants = self._afs_search('stock.quant', [('location_id', 'child_of', location.id), ('lot_id', '!=', False)])
        for quant in quants:
            lot = quant.lot_id
            free[lot] += quant.quantity - quant.reserved_quantity
            if quant.in_date and (lot not in first_in or quant.in_date < first_in[lot]):
                first_in[lot] = quant.in_date
        now = fields.Datetime.now()
        lots = sorted(free, key=lambda lot: (first_in.get(lot) or now, lot.id))

        for lot in lots:
            taken = min(max(free[lot], 0.0), quoted)
            free[lot] -= taken
            quoted -= taken

        if line_id := self.env.context.get('afs_sale_line_id'):
            own = defaultdict(float)
            for move_line in self.env['stock.move.line'].sudo().search([
                ('move_id.sale_line_id', '=', line_id),
                ('state', 'not in', ('done', 'cancel')),
                ('lot_id', '!=', False),
                ('location_id', 'child_of', location.id),
            ]):
                own[move_line.lot_id] += move_line.product_uom_id._compute_quantity(
                    move_line.quantity, move_line.product_id.uom_id)
            for lot, qty in own.items():
                if lot in free:
                    free[lot] += qty

        company = warehouse.company_id or self.env.company
        rows = [(lot, free[lot], lot.sudo().with_company(company).standard_price) for lot in lots if free[lot] > 0]
        return rows, quoted

    def _afs_shop_rows(self, warehouse=None):
        """Wat een apotheek nog kan kopen, in de volgorde van levering: de vrije partijen, dan de voorverkoop.
        Webshopbestellingen die AFS nog moet bevestigen, nemen al de oudste stuks (de teller zakt meteen).

        :return: [(partij of inkoopregel, aantal, kostprijs)]
        """
        self.ensure_one()
        warehouse = (warehouse or self._afs_warehouse()).sudo()
        rows, quoted_rest = self._afs_lot_stock(warehouse, self._afs_quoted_qty(warehouse))
        presale = self._afs_presale(warehouse, quoted=quoted_rest)
        return rows + [(line, free, cost) for line, _todo, _ordered, free, cost in presale if free > 0]

    def _afs_presale(self, warehouse, quoted=None):
        """Voorverkoop: regels van inkoopoffertes met "Voorverkoop in de webshop" die nog niet (helemaal) binnen
        zijn. Ze tellen als partij aan de prijs van de offerte met korting. Bevestigde bestellingen die op voorraad
        wachten en offertes die de vrije partijen niet dekken (`quoted`, leeg = zelf berekenen), gaan eraf,
        de inkoop die het eerst binnenkomt eerst. Regels die samen binnenkomen zijn stappen in hun volgorde op de
        offerte (bv. normale prijs, dan 20%, dan 40%), zoals ze ook ontvangen worden.

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
                incoming = line._get_outgoing_incoming_moves()[1].filtered(lambda m: m.state != 'done')
                todo = sum(incoming.mapped('product_qty'))
            else:
                todo = line.product_uom_qty
            if line.product_id.uom_id.compare(todo, 0) <= 0:
                continue
            ordered = min(todo, waiting)
            waiting -= ordered
            res.append((line, todo, ordered, todo - ordered, line._get_stock_move_price_unit()))
        return res

    def _afs_presale_free_qty(self, warehouse, variant=None):
        """Wat nog te koop is in de voorverkoop (Nog te koop op de inkoopoffertes), eventueel van één variant."""
        self.ensure_one()
        if not warehouse:
            return 0.0
        return sum(free for line, _todo, _ordered, free, _cost in self.sudo()._afs_presale(warehouse.sudo())
                   if not variant or line.product_id == variant)

    def _afs_open_orders(self, warehouse):
        """Bestellingen die op dit product wachten, in de volgorde van levering: eerst de bevestigde bestellingen
        zonder voorraad, dan de offertes die AFS nog moet bevestigen (de oudste eerst).
        :return: [(bestelling, stuks, bevestigd)]"""
        self.ensure_one()
        qty, confirmed = defaultdict(float), {}
        for line in self._afs_search('sale.order.line', [
            ('display_type', '=', False),
            ('order_id.state', '=', 'sent'),
            ('order_id.warehouse_id', '=', warehouse.id),
            ('product_uom_qty', '>', 0),
        ]):
            qty[line.order_id] += line.product_uom_id._compute_quantity(line.product_uom_qty, line.product_id.uom_id)
            confirmed[line.order_id] = False
        location = warehouse.lot_stock_id
        for move in self._afs_search('stock.move', [
            ('state', 'in', ('confirmed', 'partially_available', 'waiting')),
            ('location_id', 'child_of', location.id),
            ('sale_line_id', '!=', False),
        ]):
            missing = move.product_qty - move.product_uom._compute_quantity(move.quantity, move.product_id.uom_id)
            if missing > 0 and not move.location_dest_id._child_of(location):
                order = move.sale_line_id.order_id
                qty[order] += missing
                confirmed[order] = True
        return sorted(((order, q, confirmed[order]) for order, q in qty.items() if q > 0),
                      key=lambda row: (not row[2], row[0].date_order, row[0].id))

    def _afs_presale_claims(self, warehouse):
        """Wie de voorverkoop al bestelde. Een offerte neemt eerst de gewone voorraad, net als in de shop, dus
        de stuks per bestelling tellen op tot Besteld op de inkoopregel.

        :return: [(inkoopregel, nog te ontvangen, [(bestelling, stuks, stuks in de bestelling, bevestigd)])],
                 zonder bestelling: andere leveringen uit de voorraad (geen verkoop)
        """
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
                    claims.append((False, ordered, ordered, True))
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
        """Bevestigde bestellingen uit deze locatie die nog op voorraad wachten (niet gereserveerd),
        zonder de eigen orderregel (context afs_sale_line_id)."""
        own_line_id = self.env.context.get('afs_sale_line_id')
        waiting = 0.0
        for move in self._afs_search('stock.move', [
            ('state', 'in', ('confirmed', 'partially_available', 'waiting')),
            ('location_id', 'child_of', stock_location.id),
        ]):
            if move.location_dest_id._child_of(stock_location) or (own_line_id and move.sale_line_id.id == own_line_id):
                continue
            reserved = move.product_uom._compute_quantity(move.quantity, move.product_id.uom_id)
            waiting += max(move.product_qty - reserved, 0.0)
        return waiting

    def _afs_quoted_qty(self, warehouse):
        """Besteld maar nog door AFS te bevestigen (offerte verstuurd, zo komt een webshopbestelling binnen),
        uit dit magazijn. Een winkelwagen telt niet mee, de eigen orderregel of order (context) ook niet.
        Met afs_quoted_before = (datum, id) alleen de bestellingen die eerder binnenkwamen."""
        context = self.env.context
        before = context.get('afs_quoted_before')

        def counts(line):
            order = line.order_id
            return (line.id != context.get('afs_sale_line_id') and order.id != context.get('afs_sale_order_id')
                    and (not before or (order.date_order, order.id) < before))

        lines = self._afs_search('sale.order.line', [
            ('display_type', '=', False),
            ('order_id.state', '=', 'sent'),
            ('order_id.warehouse_id', '=', warehouse.id),
            ('product_uom_qty', '>', 0),  # een regel met een negatief aantal geeft geen stuks vrij
        ])
        return sum(line.product_uom_id._compute_quantity(line.product_uom_qty, line.product_id.uom_id)
                   for line in lines if counts(line))

    def _afs_lot_counter(self, website=None, pricelist=None, taxed=True):
        """Wat er nog te koop is per prijs: de oudste partij eerst, dan de voorverkoop. Partijen na elkaar aan
        dezelfde prijs worden samengeteld. Leeg zonder korting per partij (prijslijst met het vinkje, niet die
        van het personeel, en een regel op kostprijs of een actie). Met `taxed` de prijs zoals de shop ze toont
        (met of zonder btw), anders zonder btw.

        :return: [{'qty', 'price', 'lot' (eerste partij), 'lots', 'presale', 'presale_qty'}]
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

        # zoals de shop prijzen toont: met of zonder btw (fiscale positie van de bezoeker)
        product_taxes = taxes = None
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
            name = source._afs_lot_name() if presale else source.name  # voorverkoop: naam bij de ontvangst
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
        """Productpagina, onder de prijs: het doel van de apotheken samen, de voorraad en de stappen, of None.

        De partijen zijn stappen in de volgorde van de inkoop (FIFO): eerst de normale prijs, dan bv. 20%, dan 40%
        korting (t.o.v. de normale prijs). Het doel is hoeveel stuks er samen nog weg moeten voor de volgende stap
        met meer korting: "Nog 100 stuks om het doel te bereiken, dan krijg je 20% korting."
        """
        rows = self._afs_lot_counter(website, pricelist)
        if not rows:
            return None
        steps = []  # partijen na elkaar met dezelfde korting zijn één stap
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
        """Shopkaartje: staat de prijs nog op de normale prijs maar komen er stappen met korting (partijen of
        voorverkoop), dan de tekst onder "Actie" op de sticker: "tot −40%". Anders None. Met korting toont de module
        Webshop promoties zelf het percentage."""
        self.ensure_one()
        if pricelist is None and request and getattr(request, 'pricelist', None) is not None:
            pricelist = request.pricelist
        if not pricelist or not self._afs_uses_lot_pricing():
            return None
        if _discount(self.list_price, pricelist.sudo()._get_product_price(self.sudo().product_variant_id, 1.0)):
            return None
        rows = self._afs_lot_counter(website, pricelist, taxed=False)
        best = max((_discount(self.list_price, row['price']) for row in rows), default=0)
        return 'tot −%d%%' % best if best else None

    def _get_promo_products(self, pricelist=None):
        """In actie (Lopende acties): ook de producten die nog aan de normale prijs staan maar stappen met korting
        hebben (sticker "Actie, tot −40%"). Zonder partijen met korting is een product niet in actie."""
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
