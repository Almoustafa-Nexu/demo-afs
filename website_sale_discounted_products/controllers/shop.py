from odoo.fields import Domain
from odoo.http import request

from odoo.addons.website_sale.controllers.main import WebsiteSale


class WebsiteSalePromotions(WebsiteSale):
    """De producten in actie staan in een eigen blok, met de naam van de categorie met het vinkje
    Automatisch: producten in actie (bv. Lopende acties), anders "Promoties"."""

    def _shop_lookup_products(self, options, post, search, website):
        Product = request.env['product.template']
        promo_category = request.env['product.public.category']._afs_promotions_category()
        if promo_category and options.get('category') == str(promo_category.id):
            # De categorie Lopende acties toont de producten in actie (binnen zoekterm en filters),
            # niet de producten die er met de hand in staan.
            term, _count, products = super()._shop_lookup_products(dict(options, category=None), post, search, website)
            promo_ids = set(Product._get_promo_products().ids)
            products = products.filtered(lambda p: p.id in promo_ids)
            return term, len(products), products
        # Elders gaan de producten in actie uit de gewone lijst: ze staan in hun eigen blok
        term, count, products = super()._shop_lookup_products(options, post, search, website)
        if promo_products := Product._get_promo_products():
            products -= promo_products
            count = len(products)
        return term, count, products

    def _get_additional_shop_values(self, values, **post):
        """Hoofdpagina van de shop: bovenaan de producten in actie, daaronder een blok per categorie.
        Met een categorie, zoekterm of filter blijft de shop zoals in Odoo, met de acties onderaan."""
        res = super()._get_additional_shop_values(values, **post)
        promo_category = request.env['product.public.category']._afs_promotions_category()
        category = values.get('category')
        res['afs_promo_title'] = promo_category.name or "Promoties"
        res['afs_is_promotions_page'] = bool(promo_category and category and category.id == promo_category.id)
        params = request.params
        if (category or values.get('search') or values.get('attrib_set')
                or params.get('tags') or params.get('min_price') or params.get('max_price')):
            return res

        Product = request.env['product.template']
        order = self._get_search_order(post)
        slug = request.env['ir.http']._slug
        sections = []
        promo_products = Product._get_promo_products()
        if promo_products:
            promo_products = promo_products.search([('id', 'in', promo_products.ids)], order=order)
        if promo_products or promo_category:
            sections.append({
                'anchor': slug(promo_category) if promo_category else 'promoties',
                'title': res['afs_promo_title'],
                'products': promo_products,
                'category': promo_category,
                'empty_text': "Er lopen nu geen acties.",
            })
        for categ in values.get('category_entries') or []:
            if categ.id == promo_category.id:
                continue
            products = Product.sudo().search(Domain.AND([
                request.website.sale_product_domain(),
                [('is_published', '=', True), ('public_categ_ids', 'child_of', categ.id)],
            ]), order=order)
            if products:
                sections.append({'anchor': slug(categ), 'title': categ.name, 'products': products, 'category': categ})
        if sections:
            # het eerste raster heet zoals dat van Odoo: daarop past de editor het ontwerp van de shop aan
            if first := next((s for s in sections if s['products']), None):
                first['grid_id'] = 'o_wsale_products_grid'
            res['afs_sections'] = sections
            res['afs_section_anchors'] = {s['category'].id: s['anchor'] for s in sections if s['category']}
        return res
