import logging

from markupsafe import Markup

from odoo import api, fields, models
from odoo.exceptions import RedirectWarning
from odoo.tools import float_compare

from .product_template import _pieces, order_item

NOTHING_SAVED = "Er is niets opgeslagen."
OPEN_ORDERS = ("Wat nu: open die bestellingen met de knop hieronder. Annuleer ze, of verlaag daar het aantal of haal "
               "het product eruit. %s")


def _claim_item(order, qty, total, confirmed):
    """<li>S00279 – Apotheek Pasa – 86 stuks – offerte, nog niet bevestigd</li>"""
    if not order:
        return Markup('<li>Andere leveringen uit de voorraad – %s</li>') % _pieces(qty)
    pieces = _pieces(qty) if round(qty - total, 2) == 0 else '%g van de %s' % (round(qty, 2), _pieces(total))
    return order_item(order, pieces, 'bevestigd, wacht op voorraad' if confirmed else 'offerte, nog niet bevestigd')


def _refusal(message, action, button):
    """Melding met een knop. Een gewone weigering: in het logboek zonder traceback."""
    exc = RedirectWarning(message, action, button)
    exc.loglevel = logging.WARNING
    return exc


def _step(line):
    return '%g%% korting' % round(line.discount, 2) if line.discount > 0 else 'normale prijs'


def _open_action(records, name):
    """Knop in een melding: het record zelf, of een lijst als het er meer zijn."""
    action = {'type': 'ir.actions.act_window', 'res_model': records._name, 'name': name, 'target': 'current',
              'context': {'create': False}}
    if len(records) == 1:
        action.update(res_id=records.id, views=[(False, 'form')], view_mode='form')
    else:
        action.update(domain=[('id', 'in', records.ids)], views=[(False, 'list'), (False, 'form')],
                      view_mode='list,form')
    return action


def _refuse_claims(env, problem, sale_lines, saved, todo):
    """Weiger: het probleem, de bestellingen, dat er niets veranderde, wat te doen, en een knop naar die bestellingen."""
    per_order = {}
    for line in sale_lines:
        per_order[line.order_id] = per_order.get(line.order_id, 0.0) + line._afs_claimed_qty()
    rows = sorted(per_order.items(), key=lambda row: (row[0].state != 'sale', row[0].id))
    listing = '\n'.join('- %s – %s – %s – %s' % (
        order.name, order.partner_id.commercial_partner_id.name, _pieces(qty),
        'bevestigd, wacht op levering' if order.state == 'sale' else 'offerte, nog niet bevestigd')
        for order, qty in rows)
    orders = sale_lines.order_id.sorted('id')
    button = env._("Open %s", orders.name) if len(orders) == 1 else env._("Open de %s bestellingen", len(orders))
    raise _refusal('%s\n\n%s\n\n%s\n\n%s' % (problem, listing, saved, todo),
                   _open_action(orders, env._("Bestellingen op de voorverkoop")), button)


class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    afs_presale = fields.Boolean(
        string="Voorverkoop in de webshop", copy=False, tracking=True,
        help="De producten van deze offerte staan al als partij in de webshop, aan de prijs van de offerte met "
             "korting, alsof ze al ingekocht zijn. Zo zie je wat de apotheken bestellen voor je bevestigt.\n"
             "Meer regels voor hetzelfde product zijn stappen, in de volgorde van de regels: bv. eerst 500 stuks "
             "zonder korting (normale prijs), dan 500 aan 20%, dan 1000 aan 40%. De shop toont telkens het doel: "
             "\"Nog 500 stuks om het doel te bereiken, dan krijg je 20% korting.\"\n"
             "Bestellingen die erin passen, wachten op deze inkoop en krijgen bij de ontvangst de stuks, de oudste "
             "eerst. Automatische aanvullingen komen nooit op deze offerte.",
    )
    afs_presale_taken = fields.Html(string="Al besteld", compute='_compute_afs_presale_taken', sanitize=False)

    def _compute_afs_presale_taken(self):
        """Melding bovenaan een voorverkoop: welke bestellingen de stuks al namen (uit wat opgeslagen is)."""
        for order in self:
            order.afs_presale_taken = False
            saved = order._origin
            warehouse = order.picking_type_id.warehouse_id
            if not (order.afs_presale and saved.id and warehouse) or saved.state in ('done', 'cancel'):
                continue
            parts = []
            for template in saved.order_line.product_id.product_tmpl_id:
                for line, todo, claims in template._afs_presale_claims(warehouse):
                    if line.order_id == saved and claims:
                        parts.append(Markup('<p class="mb-1"><strong>%s</strong> (%s): al %s van de %s besteld.</p>'
                                            '<ul class="mb-2">%s</ul>') % (
                            line.product_id.display_name, _step(line), '%g' % round(sum(c[1] for c in claims), 2),
                            _pieces(todo), Markup('').join(_claim_item(*claim) for claim in claims)))
            order.afs_presale_taken = Markup('').join(parts) or False

    # Bestellingen die met een voorverkoop rekenen (haar stuks en haar prijs), mogen die niet kwijtraken:
    # annuleren, het vinkje uit, een regel weg of lager, of een andere prijs kan pas als die bestellingen aangepast zijn.

    def _afs_check_claims(self, problem, saved, then):
        for order in self.filtered('afs_presale'):
            if claiming := order.order_line._afs_claiming_sale_lines():
                _refuse_claims(self.env, problem % {'po': order.name}, claiming, saved,
                               self.env._(OPEN_ORDERS, then % {'po': order.name}))

    def button_cancel(self):
        self._afs_check_claims(
            self.env._("%(po)s kan niet geannuleerd worden: deze bestellingen rekenen nog met de voorverkoop. Zonder "
                       "deze inkoop krijgen ze niets, of een andere prijs dan op hun bestelling."),
            self.env._("Er is niets veranderd."), self.env._("Annuleer daarna %(po)s."))
        self._afs_check_bills()
        return super().button_cancel()

    def _afs_check_bills(self):
        """Zelfde regel als Odoo (geen annulatie met een leveranciersfactuur), met uitleg en een knop naar de factuur."""
        for order in self:
            bills = order.invoice_ids.filtered(lambda bill: bill.state not in ('cancel', 'draft'))
            if bills:
                raise _refusal(
                    self.env._(
                        "%(po)s kan niet geannuleerd worden: er is al een leveranciersfactuur voor (%(bills)s).\n\n"
                        "Er is niets veranderd.\n\n"
                        "Wat nu: open de factuur met de knop hieronder, klik op Terugzetten naar concept en dan op "
                        "Annuleren. Annuleer daarna %(po)s.",
                        po=order.name, bills=', '.join(bills.mapped('name'))),
                    order.action_view_invoice(bills),
                    self.env._("Open %s", bills.name) if len(bills) == 1 else
                    self.env._("Open de %s facturen", len(bills)))

    def write(self, vals):
        if 'afs_presale' in vals and not vals['afs_presale']:
            self._afs_check_claims(
                self.env._("Het vinkje Voorverkoop in de webshop kan niet uit op %(po)s: deze bestellingen rekenen nog "
                           "met de voorverkoop."),
                self.env._(NOTHING_SAVED), self.env._("Zet daarna het vinkje uit."))
        return super().write(vals)

    def action_merge(self):
        """Een voorverkoop gaat niet op in een andere offerteaanvraag (haar regels zijn de stappen in de webshop)."""
        presale = self.filtered(lambda o: o.afs_presale and o.state in ('draft', 'sent'))
        if presale:
            names = ', '.join(presale.mapped('name'))
            raise _refusal(
                self.env._(
                    "%(orders)s staat in voorverkoop in de webshop en kan niet samengevoegd worden: de regels zijn de "
                    "stappen in de webshop en bestellingen rekenen erop.\n\n"
                    "Er is niets samengevoegd.\n\n"
                    "Wat nu: haal %(orders)s uit de selectie en voeg de andere samen. Moeten er producten bij de "
                    "voorverkoop, zet ze er dan zelf op (knop hieronder).", orders=names),
                _open_action(presale, self.env._("Voorverkoop")),
                self.env._("Open %s", names) if len(presale) == 1 else self.env._("Open de voorverkopen"))
        return super().action_merge()


class PurchaseOrderLine(models.Model):
    _inherit = 'purchase.order.line'

    afs_presale_ordered = fields.Float(
        string="Besteld door apotheken", compute='_compute_afs_presale', digits='Product Unit',
        help="Bestellingen van apotheken die op deze inkoop wachten (bevestigd of nog te bevestigen).")
    afs_presale_free = fields.Float(
        string="Nog te koop in de webshop", compute='_compute_afs_presale', digits='Product Unit',
        help="Wat de apotheken nog kunnen bestellen aan de prijs van deze partij.")

    @api.depends('order_id.afs_presale', 'order_id.state', 'product_id', 'product_qty', 'product_uom_id',
                 'qty_received', 'price_unit', 'discount')
    def _compute_afs_presale(self):
        """Uit wat opgeslagen is: een wijziging telt mee na Opslaan."""
        self.afs_presale_ordered = self.afs_presale_free = 0.0
        for line in self:
            warehouse = line.order_id.picking_type_id.warehouse_id
            if not (line._origin.id and line.order_id.afs_presale and line.product_id and warehouse):
                continue
            for presale_line, _todo, ordered, free, _cost in line.product_id.product_tmpl_id._afs_presale(warehouse):
                if presale_line == line._origin:
                    line.afs_presale_ordered = line.product_id.uom_id._compute_quantity(ordered, line.product_uom_id)
                    line.afs_presale_free = line.product_id.uom_id._compute_quantity(free, line.product_uom_id)

    @api.depends('product_qty', 'product_uom_id', 'company_id', 'order_id.partner_id')
    def _compute_price_unit_and_date_planned_and_name(self):
        """Voorverkoop: een ander aantal laat prijs en korting van de stap staan (Odoo zette die van de leverancier)."""
        keep = {
            line: (line.price_unit, line.discount, line.technical_price_unit)
            for line in self
            if line.order_id.afs_presale and line._origin.id and line.product_id
            and line.product_id == line._origin.product_id and line.product_uom_id == line._origin.product_uom_id
        }
        super()._compute_price_unit_and_date_planned_and_name()
        for line, (price, discount, technical) in keep.items():
            if line.price_unit != price or line.discount != discount:
                line.price_unit = price
                line.discount = discount
            if line.technical_price_unit != technical:
                line.technical_price_unit = technical

    def _afs_claiming_sale_lines(self):
        """Orderregels met de prijs van deze voorverkoopregels: offertes en nog niet geleverde bestellingen."""
        lines = self.filtered(lambda l: l.order_id.afs_presale and l.id)
        if not lines:
            return self.env['sale.order.line']
        return self.env['sale.order.line'].sudo().search([
            ('afs_presale_line_id', 'in', lines.ids), ('order_id.state', 'in', ('draft', 'sent', 'sale')),
        ]).filtered(lambda l: l.product_id.uom_id.compare(l._afs_claimed_qty(), 0) > 0)

    def _afs_check_qty_waiting(self, new_qty=0.0, removing=False):
        for line in self:
            claiming = line._afs_claiming_sale_lines()
            if not claiming:
                continue
            needed = sum(sale_line._afs_claimed_qty() for sale_line in claiming)
            have = line.product_uom_id._compute_quantity(new_qty, line.product_id.uom_id)
            if removing:
                then = self.env._("Zet daarna het aantal van de regel op 0 (een regel van een bevestigde inkoop "
                                  "verwijderen kan niet).") if line.order_id.state == 'purchase' else \
                    self.env._("Verwijder daarna de regel.")
                _refuse_claims(
                    self.env,
                    self.env._("Deze regel (%(product)s, %(step)s) kan niet weg: deze bestellingen rekenen nog met haar "
                               "stuks en haar prijs.", product=line.product_id.display_name, step=_step(line)),
                    claiming, self.env._(NOTHING_SAVED), self.env._(OPEN_ORDERS, then))
            if line.product_id.uom_id.compare(have, needed) < 0:
                _refuse_claims(
                    self.env,
                    self.env._("Minder dan %(needed)s kan niet op deze regel (%(product)s, %(step)s): deze bestellingen "
                               "rekenen nog met %(needed)s ervan.",
                               needed=_pieces(needed), product=line.product_id.display_name, step=_step(line)),
                    claiming, self.env._(NOTHING_SAVED), self.env._(OPEN_ORDERS, "Verlaag daarna de regel."))

    def _afs_check_fixed(self, vals):
        """Prijs, korting, product en eenheid liggen vast zodra bestellingen met de regel rekenen."""
        precision = self.env['decimal.precision']
        price_digits, discount_digits = precision.precision_get('Product Price'), precision.precision_get('Discount')
        for line in self:
            changed = (
                ('price_unit' in vals and float_compare(vals['price_unit'] or 0.0, line.price_unit,
                                                        precision_digits=price_digits))
                or ('discount' in vals and float_compare(vals['discount'] or 0.0, line.discount,
                                                         precision_digits=discount_digits))
                or ('product_id' in vals and (vals['product_id'] or False) != line.product_id.id)
                or ('product_uom_id' in vals and (vals['product_uom_id'] or False) != line.product_uom_id.id)
            )
            if changed and (claiming := line._afs_claiming_sale_lines()):
                _refuse_claims(
                    self.env,
                    self.env._("De prijs, de korting en het product van deze regel (%(product)s, %(step)s) liggen vast: "
                               "deze bestellingen rekenen er al mee. Met een andere prijs verschilt hun factuur van "
                               "hun bestelling.", product=line.product_id.display_name, step=_step(line)),
                    claiming, self.env._(NOTHING_SAVED), self.env._(
                        "Wat nu: een andere prijs voor nieuwe bestellingen? Voeg dan een regel toe met die prijs (een "
                        "nieuwe stap). Moet het ook voor deze bestellingen, open ze dan met de knop hieronder, annuleer "
                        "ze of haal het product eruit, en pas daarna de regel aan."))

    def unlink(self):
        self._afs_check_qty_waiting(removing=True)
        self._afs_check_confirmed_unlink()
        return super().unlink()

    def _afs_check_confirmed_unlink(self):
        """Zelfde regel als Odoo (geen regel weg van een bevestigde inkoop), met uitleg en een knop die de inkoop
        opnieuw opent. Gebeurt voor Odoo de ontvangst aanraakt (anders kwam een melding over de voorraad)."""
        lines = self.filtered(lambda l: l.order_id.state == 'purchase'
                              and l.display_type not in ('line_section', 'line_subsection', 'line_note'))
        if not lines:
            return
        order = lines.order_id[:1]
        todo = '\n'.join('- %s: zet het aantal op %s' % (
            line.product_id.display_name,
            '0' if line.product_uom_id.compare(line.qty_received, 0) <= 0 else
            '%g (wat al ontvangen is)' % round(line.qty_received, 2))
            for line in lines.filtered(lambda l: l.order_id == order))
        raise _refusal(
            self.env._(
                "Een regel van een bevestigde inkoop (%(po)s) kan niet weg: Odoo houdt ze bij voor de ontvangst en de "
                "factuur.\n\nEr is niets opgeslagen.\n\nWat nu: open %(po)s opnieuw met de knop hieronder (de regel "
                "staat er dan weer) en pas het aantal aan:\n%(todo)s\nOdoo past de ontvangst dan zelf aan. Moet de "
                "hele inkoop weg, klik dan op Annuleren.", po=order.name, todo=todo),
            _open_action(order, order.name), self.env._("Open %s opnieuw", order.name))

    def _afs_gross_cost(self):
        """Inkoopprijs zonder korting, zoals de kostprijs (zonder btw, eenheid van het product, munt van het
        bedrijf) maar niet afgerond."""
        self.ensure_one()
        order = self.order_id
        price = self.price_unit
        if self.tax_ids:
            qty = self.product_qty or 1
            taxes = self.tax_ids.compute_all(price, currency=order.currency_id, quantity=qty, product=self.product_id,
                                             partner=order.partner_id, rounding_method='round_globally')
            price = taxes['total_void'] / qty
        if self.product_uom_id and self.product_uom_id != self.product_id.uom_id:
            price = price / self.product_uom_id.factor * self.product_id.uom_id.factor
        if order.currency_id and order.company_id and order.currency_id != order.company_id.currency_id:
            price = order.currency_id._convert(price, order.company_id.currency_id, order.company_id,
                                               self.date_order or fields.Date.today(), round=False)
        return price

    def _afs_lot_name(self):
        """Partijnaam bij de ontvangst: LOT-P00045-20PROC met korting, STOCK-P00045 zonder; tweede regel van
        hetzelfde product: -2 erbij."""
        self.ensure_one()
        name = self.order_id.name
        same_product = self.order_id.order_line.filtered(lambda l: l.product_id == self.product_id).sorted('id')
        position = same_product.ids.index(self.id) + 1
        if position > 1:
            name = '%s-%d' % (name, position)
        if self.discount > 0.0001:
            return 'LOT-%s-%sPROC' % (name, ('%g' % round(self.discount, 2)).replace('.', ','))
        return 'STOCK-%s' % name

    def write(self, vals):
        """Andere korting na bevestigen: de voorgestelde partijnaam volgt (een zelf getypte naam blijft)."""
        if 'product_qty' in vals:
            self._afs_check_qty_waiting(new_qty=vals['product_qty'])
        if {'price_unit', 'discount', 'product_id', 'product_uom_id'} & set(vals):
            self._afs_check_fixed(vals)
        if 'discount' not in vals:
            return super().write(vals)
        open_moves = self.move_ids.filtered(lambda m: m.state not in ('done', 'cancel'))
        old_names = {move: move._afs_auto_lot_name() for move in open_moves}
        res = super().write(vals)
        for move, old_name in old_names.items():
            new_name = move._afs_auto_lot_name()
            if old_name and new_name and new_name != old_name:
                move.move_line_ids.filtered(lambda ml: ml.lot_name == old_name and not ml.lot_id).write(
                    {'lot_name': new_name})
        return res
