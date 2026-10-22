from collections import defaultdict

from markupsafe import Markup

from odoo import api, fields, models

from .product_pricelist import _per_uom, source_label
from .product_template import _pieces, order_item


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    afs_held_by = fields.Html(string="Vastgehouden door", compute='_compute_afs_held_by', sanitize=False)

    @api.depends('state', 'warehouse_id', 'order_line.afs_lot_id', 'order_line.afs_presale_line_id',
                 'order_line.product_uom_qty')
    def _compute_afs_held_by(self):
        for order in self:
            order.afs_held_by = order._afs_held_by_html() or False

    def _afs_held_by_html(self):
        """Melding bovenaan een offerte met stuks op "Nog niet op voorraad": wie de partijen vasthoudt, met een link.
        Volgt het formulier meteen (een partij kiezen doet ze verdwijnen); nieuwe regels tellen pas na Opslaan."""
        cart = self.website_id and self.state == 'draft'  # een winkelwagen wordt pas verdeeld bij het afrekenen
        if not self._origin.id or self.state not in ('draft', 'sent') or not self.warehouse_id or cart:
            return ''
        rest = self.order_line.filtered(lambda l: l._origin.id and l._afs_can_split()
                                        and not (l.afs_lot_id or l.afs_presale_line_id))
        html, waiting = Markup(''), False
        for product in rest.product_id:
            lines = rest.filtered(lambda l: l.product_id == product)
            qty = _pieces(sum(lines.mapped('product_uom_qty')))
            template = product.product_tmpl_id
            taken = self.order_line._afs_chosen_qty(product, only_chosen=False)
            if sum(lines[0].with_context(afs_taken=taken)._afs_lot_free().values()) > 0:
                html += Markup('<p class="mb-2"><strong>%s</strong>: %s staan op Nog niet op voorraad, maar er is nu vrije '
                               'voorraad. Klik op <strong>Prijzen bijwerken</strong>, dan krijgen ze hun partij.</p>') % (
                    product.display_name, qty)
                continue
            waiting = True
            holders = template._afs_holders(self.warehouse_id)
            holders.pop(self._origin, None)
            html += Markup('<p class="mb-1"><strong>%s</strong>: %s staan op Nog niet op voorraad (voorlopige prijs). %s</p>') % (
                product.display_name, qty, 'De partijen op voorraad zijn al genomen door:' if holders else 'Er is geen vrije voorraad.')
            if holders:
                html += Markup('<ul class="mb-1">%s</ul>') % Markup('').join(
                    order_item(o, _pieces(q), 'bevestigd, gereserveerd' if confirmed else 'offerte, nog niet bevestigd')
                    for o, (q, confirmed) in sorted(holders.items(), key=lambda row: row[0].id))
            if template._afs_buys_automatically(self.warehouse_id):
                html += Markup('<p class="mb-2">Bevestig je deze offerte, dan regelt Odoo die %s zelf: uit voorraad die '
                               'nog niet gereserveerd is, uit een voorverkoop, of met een inkoop (Aanvullen op order).</p>') % qty
            else:
                html += Markup('<p class="mb-2">Odoo koopt dit product niet vanzelf in: <a href="/odoo/action-purchase.'
                               'purchase_rfq/new" target="_blank">koop de %s in</a>, of zet op het product de route '
                               'Aanvullen op order (MTO).</p>') % qty
        if waiting:
            html += Markup('<p class="mb-0">Dat is in orde: de factuur rekent de prijs van de partij die echt geleverd wordt. '
                           'Moet deze offerte toch de partijen van een andere bestelling krijgen (bv. een testorder): '
                           'annuleer die bestelling en klik hier op Prijzen bijwerken.</p>')
        return html

    def _create_invoices(self, grouped=False, final=False, date=None):
        moves = super()._create_invoices(grouped=grouped, final=final, date=date)
        moves._afs_split_lot_lines()
        return moves

    def action_quotation_sent(self):
        self._afs_split_per_lot(placing=True)
        return super().action_quotation_sent()

    def action_confirm(self):
        self._afs_split_per_lot(placing=True)
        return super().action_confirm()

    def action_update_prices(self):
        self._afs_split_per_lot()
        return super().action_update_prices()

    def _get_free_qty(self, product):
        """Winkelwagen: wat nog te koop is in de voorverkoop, telt mee als beschikbaar."""
        qty = super()._get_free_qty(product)
        template = product.product_tmpl_id
        warehouse = template._afs_website_warehouse(self.website_id) if self.website_id else self.warehouse_id
        return qty + template._afs_presale_free_qty(warehouse, product)

    def _afs_summary_rows(self, tax_included=False):
        """Overzicht in de webshop: (regel, partij of False), een rij per partij."""
        rows = []
        for line in self.website_order_line:
            rows += [(line, part) for part in line._afs_lot_breakdown(tax_included)] or [(line, False)]
        return rows

    def _afs_split_per_lot(self, products=None, placing=False):
        """Een orderregel per partij met de echte prijs van die partij. De winkelwagen blijft een regel per product;
        bij afrekenen of bevestigen (`placing`) wordt ze verdeeld, wat al verdeeld is blijft dan zoals het is."""
        for order in self:
            cart = bool(order.website_id) and order.state == 'draft'
            if order.state not in ('draft', 'sent') or (cart and not placing):
                continue
            lines = order.order_line.filtered(
                lambda l: l._afs_can_split() and (products is None or l.product_id in products))
            lines.filtered('afs_lot_fixed')._afs_fit_chosen_lot()
            for product in lines.product_id:
                # verdelen kan regels van een vorig product verwijderen (bv. bij een kopie)
                group = (lines.exists() | order.order_line).filtered(
                    lambda l: l.product_id == product and l._afs_can_split() and not l.afs_lot_fixed)
                if group and not (placing and all(group.mapped('afs_split'))):
                    order._afs_split_product(group, all_quoted=cart)

    def _afs_split_product(self, lines, all_quoted=False):
        """Verdeel de regels van een product opnieuw over de partijen (bestaande regels hergebruikt, de rest weg).
        Eerdere bestellingen krijgen de oudste stuks; bij het afrekenen (`all_quoted`) tellen alle bestellingen mee."""
        self.ensure_one()
        lines = lines.sorted(lambda l: (l.sequence, l.id))
        first, product = lines[0], lines[0].product_id
        total = sum(lines.mapped('product_uom_qty'))
        if product.uom_id.compare(total, 0) <= 0:
            return  # aantal 0 of minder: de regel blijft zoals AFS ze zette
        date = first._get_order_date()
        rule = self.env['product.pricelist.item'].browse(
            self.pricelist_id._get_product_rule(product, quantity=total, uom=product.uom_id, date=date))
        if not rule._afs_lot_mode(product):
            return
        context = dict(first._get_product_price_context(), afs_sale_order_id=self.id,
                       afs_taken=self.order_line._afs_chosen_qty(product))
        context.pop('afs_sale_line_id', None)
        if not all_quoted:
            context['afs_quoted_before'] = (self.date_order, self.id)
        parts = rule._afs_lot_parts(product.with_context(**context), total, date,
                                    self.currency_id or self.company_id.currency_id, show_discount=False)
        split = len(parts) > 1 or bool(parts[0]['source'])

        def line_vals(source, qty):
            return {
                'product_uom_qty': qty,
                'afs_split': split,
                'afs_lot_id': source.id if source and source._name == 'stock.lot' else False,
                'afs_presale_line_id': source.id if source and source._name == 'purchase.order.line' else False,
            }

        plan = [line_vals(part['source'], part['qty']) for part in parts]
        current = [(l.product_uom_qty, l.afs_split, l.afs_lot_id.id, l.afs_presale_line_id.id) for l in lines]
        if current == [tuple(vals.values()) for vals in plan]:
            return
        keep = self.env['sale.order.line']
        for index, vals in enumerate(plan):
            if index < len(lines):
                line = lines[index]
                line.with_context(afs_no_split=True).write(vals)
            else:
                line = first.with_context(afs_no_split=True).copy(dict(vals, order_id=self.id))
            keep |= line
        (lines - keep).with_context(afs_no_split=True).unlink()
        keep._afs_reprice()


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    afs_split = fields.Boolean(string="Regel per partij", copy=False)
    afs_lot_id = fields.Many2one('stock.lot', string="Partij", copy=False, index='btree_not_null')
    afs_lot_fixed = fields.Boolean(string="Partij met de hand gekozen", copy=False)
    afs_lot_choices = fields.Many2many('stock.lot', string="Vrije partijen", compute='_compute_afs_lot_choices',
                                       compute_sudo=True)
    afs_presale_line_id = fields.Many2one('purchase.order.line', string="Voorverkoop", copy=False,
                                          index='btree_not_null')

    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        if not self.env.context.get('afs_no_split'):
            lines.order_id._afs_split_per_lot(lines.product_id)
        return lines

    def write(self, vals):
        if self.env.context.get('afs_no_split') or not {'product_uom_qty', 'product_id', 'product_uom_id',
                                                         'afs_lot_id'} & set(vals):
            return super().write(vals)
        products = self.product_id
        res = super().write(vals)
        self.order_id._afs_split_per_lot(products | self.product_id)
        return res

    def unlink(self):
        if self.env.context.get('afs_no_split'):
            return super().unlink()
        groups = {(line.order_id, line.product_id) for line in self if line.afs_split}
        res = super().unlink()
        for order, product in groups:
            if order.exists():
                order._afs_split_per_lot(product)
        return res

    # ---- Partij met de hand kiezen (backend) ----

    def _afs_lot_free(self):
        """{partij: vrij} voor deze regel: zoals de shop, zonder offertes van deze order, met wat zij al reserveerde."""
        self.ensure_one()
        warehouse = self.order_id.warehouse_id
        if not (self.product_id and warehouse and self.pricelist_item_id._afs_lot_mode(self.product_id)):
            return {}
        template = self.product_id.product_tmpl_id.with_context(**self._get_product_price_context(),
                                                                afs_sale_order_id=self.order_id._origin.id)
        rows, _rest = template._afs_lot_stock(warehouse, template._afs_quoted_qty(warehouse))
        return {lot: qty for lot, qty, _cost in rows}

    @api.depends('product_id', 'order_id.warehouse_id', 'order_id.pricelist_id')
    def _compute_afs_lot_choices(self):
        for line in self:
            line.afs_lot_choices = [lot.id for lot in line._afs_lot_free()]

    @api.onchange('afs_lot_id')
    def _onchange_afs_lot_id(self):
        """Partij gekozen: meteen haar prijs en korting, en bij Opslaan blijft ze. Leeg: weer automatisch verdeeld."""
        if not self.product_id or not (self.afs_lot_id or self.afs_lot_fixed):
            return
        self.update({'afs_lot_fixed': bool(self.afs_lot_id), 'afs_split': bool(self.afs_lot_id),
                     'afs_presale_line_id': False})
        self._afs_reprice()

    def _afs_chosen_qty(self, product, only_chosen=True):
        """{partij id: stuks} op deze regels (standaard alleen de met de hand gekozen): die zijn niet meer vrij."""
        taken = {}
        for line in self.filtered(lambda l: l.afs_lot_id and l.product_id == product and (l.afs_lot_fixed or not only_chosen)):
            taken[line.afs_lot_id.id] = taken.get(line.afs_lot_id.id, 0.0) + line.product_uom_qty
        return taken

    def _afs_fit_chosen_lot(self):
        """Een gekozen partij krijgt hoogstens wat er vrij is; de rest gaat naar een nieuwe regel die automatisch
        verdeeld wordt. Is de partij helemaal op, dan wordt de regel weer automatisch."""
        for line in self.sorted(lambda l: (l.sequence, l.id)):
            free = line._afs_lot_free().get(line.afs_lot_id, 0.0)
            free -= line.order_id.order_line._afs_chosen_qty(line.product_id).get(line.afs_lot_id.id, 0.0) - line.product_uom_qty
            auto = {'afs_lot_fixed': False, 'afs_split': False, 'afs_lot_id': False}
            if line.product_id.uom_id.compare(free, 0) <= 0:
                line.with_context(afs_no_split=True).write(auto)
            elif line.product_id.uom_id.compare(line.product_uom_qty, free) > 0:
                line.with_context(afs_no_split=True).copy(dict(auto, order_id=line.order_id.id,
                                                               product_uom_qty=line.product_uom_qty - free))
                line.with_context(afs_no_split=True).write({'product_uom_qty': free})
                line._afs_reprice()

    def _afs_claimed_qty(self):
        """Stuks die nog met hun partij of voorverkoop rekenen (eenheid van het product): bij een bevestigde
        bestelling wat nog geleverd moet worden, bij een offerte het aantal."""
        self.ensure_one()
        if self.order_id.state == 'sale':
            moves = self.move_ids.filtered(
                lambda m: m.state not in ('done', 'cancel') and m.location_dest_id.usage == 'customer')
            return sum(moves.mapped('product_qty'))
        if self.order_id.state in ('draft', 'sent') and self.product_uom_id:
            return self.product_uom_id._compute_quantity(self.product_uom_qty, self.product_id.uom_id)
        return 0.0

    def _afs_can_split(self):
        """Prijs per partij, eenheid van het product en prijs niet met de hand aangepast."""
        self.ensure_one()
        return bool(self.product_id and not self.display_type and not self.is_downpayment and not self.combo_item_id
                    and self.product_uom_id == self.product_id.uom_id and not self._afs_has_manual_price()
                    and self.pricelist_item_id._afs_lot_mode(self.product_id))

    def _afs_is_split(self):
        return self.afs_split and self.pricelist_item_id._afs_lot_mode(self.product_id)

    def _afs_has_manual_price(self):
        self.ensure_one()
        currency = self.currency_id or self.company_id.currency_id
        return bool(self.technical_price_unit) and \
            currency.compare_amounts(self.technical_price_unit, self.price_unit) != 0

    def _afs_reprice(self):
        """Na het verdelen: prijsregel, prijs, korting en omschrijving opnieuw."""
        self.invalidate_recordset(['pricelist_item_id'])
        self.with_context(force_price_recomputation=True)._compute_price_unit()
        self._compute_discount()
        for line in self:
            line.name = line._afs_line_name()

    def _afs_line_name(self):
        name = self.with_context(lang=self.order_id._get_lang())._get_sale_order_line_multiline_description_sale()
        return '%s\n%s' % (name, source_label(self.afs_lot_id or self.afs_presale_line_id)) if self.afs_split else name

    # ---- Prijs per partij ----

    def _get_product_price_context(self):
        """Het magazijn van de order en de regel zelf (wat ze al reserveerde, is vrij voor haar)."""
        res = super()._get_product_price_context()
        res['afs_order_line'] = True
        if self.order_id.warehouse_id:
            res['afs_warehouse_id'] = self.order_id.warehouse_id.id
        if isinstance(self._origin.id, int) and self._origin.id:
            res['afs_sale_line_id'] = self._origin.id
        return res

    def _get_pricelist_kwargs(self):
        """Een verdeelde regel kiest haar prijsregel (bv. een staffel) op het totaal van het product."""
        res = super()._get_pricelist_kwargs()
        if self.afs_split:
            group = self.order_id.order_line.filtered(lambda l: l.afs_split and l.product_id == self.product_id)
            res['quantity'] = sum(group.mapped('product_uom_qty')) or res['quantity']
        return res

    def _get_pricelist_price(self):
        if self._afs_is_split():
            return self._afs_split_price(show_discount=False)[0]
        return super()._get_pricelist_price()

    def _afs_price_args(self):
        kwargs = self._get_pricelist_kwargs()
        return kwargs, kwargs['currency'] or self.company_id.currency_id or self.env.company.currency_id

    def _afs_split_price(self, show_discount):
        """Verdeelde regel: (prijs, korting %) van haar partij, voorverkoopregel of de voorlopige prijs."""
        kwargs, currency = self._afs_price_args()
        source = (self.afs_lot_id or self.afs_presale_line_id).sudo()
        if source._name == 'stock.lot':
            cost = source.with_company(self.company_id).standard_price
        else:
            cost = source._get_stock_move_price_unit() if source else 0.0
        return self.pricelist_item_id._afs_part_price(self.product_id, source, cost, self.product_uom_qty,
                                                      kwargs['quantity'], kwargs['date'], currency, show_discount)

    def _afs_parts(self, show_discount):
        """Verdeling over de partijen van een (nog) niet verdeelde regel, zoals in de winkelwagen."""
        kwargs, currency = self._afs_price_args()
        qty = self.product_uom_id._compute_quantity(self.product_uom_qty or 1.0, self.product_id.uom_id)
        return self.pricelist_item_id._afs_lot_parts(self.product_id.with_context(**self._get_product_price_context()),
                                                     qty, kwargs['date'], currency, show_discount)

    # ---- Korting zichtbaar (Verkoop > Instellingen > Kortingen) ----

    def _afs_show_lot_discount(self):
        self.ensure_one()
        rule = self.pricelist_item_id
        return bool(self.product_id and not self.display_type and not self.combo_item_id and rule
                    and rule._is_discount_feature_enabled() and rule._afs_lot_mode(self.product_id))

    def _afs_shown_line(self):
        """(prijs, korting %): een regel uit een partij toont die partij; uit meer partijen het gemiddelde zonder
        korting, zodat het bedrag klopt met de verdeling eronder."""
        self.ensure_one()
        if self._afs_is_split():
            return self._afs_split_price(show_discount=True)
        parts = self._afs_parts(show_discount=True)
        if len(parts) == 1:
            price, discount = parts[0]['price'], parts[0]['discount']
        else:
            price, discount = sum(p['amount'] for p in parts) / sum(p['qty'] for p in parts), 0.0
        return _per_uom(self.product_id, price, self.product_uom_id), discount

    def _get_display_price_ignore_combo(self):
        if self._afs_show_lot_discount():
            return self._afs_shown_line()[0]
        return super()._get_display_price_ignore_combo()

    @api.depends('product_id', 'product_uom_id', 'product_uom_qty')
    def _compute_discount(self):
        super()._compute_discount()
        for line in self:
            if line.order_id.pricelist_id and line.product_uom_id and line._afs_show_lot_discount():
                line.discount = line.with_company(line.company_id)._afs_shown_line()[1]

    def _afs_lot_breakdown(self, tax_included=False):
        """Webshop: per partij aantal, prijs, korting, bedrag en een noot (voorverkoop, nog niet op voorraad)."""
        self.ensure_one()
        rule = self.pricelist_item_id
        if self.product_uom_id != self.product_id.uom_id or not rule._afs_lot_mode(self.product_id):
            return []
        if self._afs_is_split():
            parts = [{'source': self.afs_lot_id or self.afs_presale_line_id, 'qty': self.product_uom_qty,
                      'price': self.price_unit, 'discount': self.discount, 'amount': self.price_subtotal}]
        else:
            parts = self._afs_parts(rule._is_discount_feature_enabled())
            if len(parts) == 1 and not parts[0]['source']:
                return []  # geen partijen: gewoon de prijs van de regel
        display = 'total_included' if tax_included else 'total_excluded'
        for part in parts:
            source = part['source']
            if not source:
                part['note'] = 'nog niet op voorraad'
            else:
                part['note'] = 'voorverkoop' if source._name == 'purchase.order.line' else ''
            for key in ('price', 'amount'):
                part[key] = self.tax_ids.compute_all(part[key], self.currency_id, 1, self.product_id,
                                                     self.order_partner_id)[display]
        return parts

    def _afs_net_delivered_per_lot(self):
        """Netto geleverd per partij (leveringen min retours), eenheid van het product.
        :return: ({partij: aantal}, partijen in de volgorde van levering)"""
        self.ensure_one()
        qty, lots = defaultdict(float), []
        move_lines = self.move_ids.filtered(lambda m: m.state == 'done').move_line_ids
        for ml in move_lines.sorted(lambda ml: (ml.date or ml.create_date, ml.id)):
            to_customer, from_customer = ml.location_dest_id.usage == 'customer', ml.location_id.usage == 'customer'
            if not ml.lot_id or to_customer == from_customer:
                continue
            qty[ml.lot_id] += ml.quantity_product_uom if to_customer else -ml.quantity_product_uom
            if ml.lot_id not in lots:
                lots.append(ml.lot_id)
        return qty, lots
